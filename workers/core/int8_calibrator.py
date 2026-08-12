"""Phase 13D TensorRT 8.5 INT8 entropy calibrator.

The Jetson venv still has **no PyCUDA and no cuda-python**, and Phase 13D is
still forbidden from installing either, so the calibrator drives CUDA through
the same ``ctypes`` ``libcudart`` runtime Phase 13C proved. On top of that it
enforces the rules that make an INT8 calibration defensible:

* the calibration tensor is produced by the **runtime preprocessing function**
  (``BGR8 -> letterbox 640 -> RGB -> /255 -> NCHW``), never a re-implementation,
  so calibration and inference cannot drift apart;
* batch size 1;
* **one** device buffer, allocated once and reused for every batch —
  ``per_batch_device_allocation_count`` must stay 0;
* a frame that cannot be read or preprocessed is a hard failure, never a skip:
  ``skipped_frame_count`` must stay 0;
* every CUDA call is status-checked;
* the calibration cache is bound to a hashed key over the ONNX, the dataset,
  the algorithm, the input/preprocess profile and the target runtime. Any
  difference makes the cache stale and calibration must run again.

Import stays safe when TensorRT or CUDA are absent so Gate A can run on the PC.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:  # pragma: no cover - import bootstrap
    sys.path.insert(0, str(REPO_ROOT))

from workers.core.tensorrt_asset_contract import InputContract
from workers.core.tensorrt_perception import preprocess_bgr

CALIBRATION_CACHE_VERSION = 1
CALIBRATOR_ALGORITHM = "IInt8EntropyCalibrator2"
DEFAULT_BATCH_SIZE = 1


class CalibrationError(RuntimeError):
    """Calibration contract violation carrying a Phase 13D classification."""

    def __init__(self, classification: str, message: str) -> None:
        super().__init__("%s: %s" % (classification, message))
        self.classification = classification
        self.message = message


# ── Cache identity ──────────────────────────────────────────────────────────


def preprocess_profile_fragment(contract: InputContract) -> str:
    """Everything about preprocessing that changes the calibration scales."""

    return "|".join(
        [
            "src=%s" % contract.source_pixel_format,
            "order=%s" % contract.input_color_order,
            "scale=%.4f" % float(contract.normalization_scale),
            "letterbox=%s" % contract.letterbox_policy,
            "layout=%s" % contract.layout,
            "dtype=%s" % contract.input_dtype,
            "shape=%s" % contract.shape_text,
        ]
    )


def calibration_cache_key(
    *,
    onnx_sha256: str,
    dataset_sha256: str,
    calibration_frame_count: int,
    algorithm: str,
    batch_size: int,
    input_profile: str,
    preprocess_profile: str,
    tensorrt_version: str,
    cuda_version: str,
    gpu_name: str,
) -> str:
    """Bind a calibration cache to everything that can invalidate its scales."""

    material = "\n".join(
        [
            "cache_version=%d" % CALIBRATION_CACHE_VERSION,
            "onnx_sha256=%s" % onnx_sha256,
            "dataset_sha256=%s" % dataset_sha256,
            "calibration_frame_count=%d" % int(calibration_frame_count),
            "algorithm=%s" % algorithm,
            "batch_size=%d" % int(batch_size),
            "input_profile=%s" % input_profile,
            "preprocess_profile=%s" % preprocess_profile,
            "tensorrt_version=%s" % tensorrt_version,
            "cuda_version=%s" % cuda_version,
            "gpu_name=%s" % gpu_name,
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass
class CalibrationCacheMeta:
    """Sidecar written next to the cache so staleness is decidable offline."""

    cache_path: str = ""
    cache_sha256: str = ""
    cache_size_bytes: int = 0
    calibration_cache_key: str = ""
    onnx_sha256: str = ""
    dataset_sha256: str = ""
    dataset_manifest_path: str = ""
    calibration_frame_count: int = 0
    algorithm: str = CALIBRATOR_ALGORITHM
    batch_size: int = DEFAULT_BATCH_SIZE
    input_profile: str = ""
    preprocess_profile: str = ""
    tensorrt_version: str = ""
    cuda_version: str = ""
    gpu_name: str = ""
    built_on_target: bool = False
    created_at_utc: str = ""
    cache_version: int = CALIBRATION_CACHE_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def write(self, path: Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return target

    @staticmethod
    def load(path: Path) -> "CalibrationCacheMeta":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        known = {key for key in CalibrationCacheMeta().to_dict()}
        return CalibrationCacheMeta(**{k: v for k, v in payload.items() if k in known})


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def evaluate_cache_staleness(
    meta: Optional[CalibrationCacheMeta],
    *,
    cache_path: Path,
    expected_key: str,
    verify_hash: bool = True,
) -> Dict[str, Any]:
    """Decide whether a calibration cache may be reused, and say why not."""

    reasons = []  # type: List[str]
    path = Path(cache_path)
    if meta is None:
        reasons.append("calibration_cache_meta_missing")
    if not path.is_file():
        reasons.append("calibration_cache_missing")
    elif meta is not None and verify_hash and meta.cache_sha256:
        actual = sha256_bytes(path.read_bytes())
        if actual != meta.cache_sha256:
            reasons.append("calibration_cache_sha256_mismatch")
    if meta is not None:
        if meta.calibration_cache_key and expected_key and meta.calibration_cache_key != expected_key:
            reasons.append("calibration_cache_key_mismatch")
        if meta.cache_version != CALIBRATION_CACHE_VERSION:
            reasons.append("calibration_cache_version_mismatch")
        if not meta.built_on_target:
            reasons.append("calibration_cache_not_built_on_target")
    return {
        "calibration_cache_stale": bool(reasons),
        "calibration_cache_stale_reasons": reasons,
        "calibration_cache_expected_key": expected_key,
        "calibration_cache_recorded_key": meta.calibration_cache_key if meta else "",
    }


# ── Reusable device memory ──────────────────────────────────────────────────


class ReusableDeviceBuffer:
    """One device allocation, reused for every calibration batch.

    The allocation happens in ``__init__``. ``upload`` only copies; if it ever
    allocated, ``per_batch_allocation_count`` would become non-zero and the
    calibration gate would fail closed.
    """

    def __init__(self, cuda: Any, nbytes: int) -> None:
        if int(nbytes) <= 0:
            raise CalibrationError("calibration_buffer_invalid", "buffer size must be positive")
        self.cuda = cuda
        self.nbytes = int(nbytes)
        self.allocation_count = 0
        self.per_batch_allocation_count = 0
        self.upload_count = 0
        self._closed = False
        self.stream = cuda.stream_create()
        self.pointer = cuda.malloc(self.nbytes)
        self.allocation_count += 1

    def upload(self, host: np.ndarray) -> int:
        if self._closed:
            raise CalibrationError("calibration_buffer_closed", "buffer already released")
        array = np.ascontiguousarray(host)
        if int(array.nbytes) != self.nbytes:
            raise CalibrationError(
                "calibration_buffer_size_mismatch",
                "batch is %d bytes, buffer is %d bytes" % (int(array.nbytes), self.nbytes),
            )
        self.cuda.memcpy_htod_async(self.pointer, array, self.nbytes, self.stream)
        self.cuda.stream_synchronize(self.stream)
        self.upload_count += 1
        return int(self.pointer)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self.pointer:
                self.cuda.free(self.pointer)
        finally:
            self.pointer = 0
            if self.stream:
                self.cuda.stream_destroy(self.stream)
                self.stream = 0

    def metrics(self) -> Dict[str, Any]:
        return {
            "calibration_device_allocation_count": self.allocation_count,
            "per_batch_device_allocation_count": self.per_batch_allocation_count,
            "calibration_device_buffer_bytes": self.nbytes,
            "calibration_batch_upload_count": self.upload_count,
        }


# ── Batch feeder ────────────────────────────────────────────────────────────


def read_bgr_frame(path: Path) -> np.ndarray:
    """Decode one calibration frame. An unreadable frame is a hard failure."""

    try:
        import cv2  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - cv2 is present on both hosts
        raise CalibrationError("calibration_decoder_unavailable", repr(exc)[:200])
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None:
        raise CalibrationError("calibration_frame_unreadable", "cv2 could not decode %s" % path)
    return image


class CalibrationBatchFeeder:
    """Turns calibration frames into engine-ready batch-1 tensors, in order.

    Deliberately free of TensorRT and CUDA so the whole feeding contract —
    ordering, preprocessing identity, zero skips, statistics — is unit-testable
    on the simulation PC.
    """

    def __init__(
        self,
        frame_paths: Sequence[Any],
        *,
        input_contract: Optional[InputContract] = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
        reader: Optional[Any] = None,
    ) -> None:
        if int(batch_size) != DEFAULT_BATCH_SIZE:
            raise CalibrationError(
                "calibration_batch_size_unsupported",
                "Phase 13D calibrates at batch size 1, got %d" % int(batch_size),
            )
        self.frame_paths = [Path(item) for item in frame_paths]
        if not self.frame_paths:
            raise CalibrationError("calibration_frames_missing", "no calibration frames supplied")
        self.input_contract = input_contract or InputContract()
        self.batch_size = int(batch_size)
        self._reader = reader or read_bgr_frame
        self._index = 0
        self.frames_read = 0
        self.batches_produced = 0
        self.skipped_frame_count = 0
        self.tensor_min = None  # type: Optional[float]
        self.tensor_max = None  # type: Optional[float]
        self.channel_mean_sums = [0.0, 0.0, 0.0]
        self.nonfinite_frame_count = 0

    @property
    def frame_count(self) -> int:
        return len(self.frame_paths)

    @property
    def tensor_nbytes(self) -> int:
        contract = self.input_contract
        elements = 1
        for value in contract.shape:
            elements *= int(value)
        return elements * int(np.dtype(contract.input_dtype).itemsize)

    def exhausted(self) -> bool:
        return self._index >= len(self.frame_paths)

    def next_batch(self) -> Optional[np.ndarray]:
        """The next batch-1 tensor, or ``None`` once the corpus is consumed."""

        if self.exhausted():
            return None
        path = self.frame_paths[self._index]
        self._index += 1
        frame = self._reader(path)
        try:
            tensor, _letterbox, stats = preprocess_bgr(np.asarray(frame), self.input_contract)
        except Exception as exc:
            raise CalibrationError(
                "calibration_frame_preprocess_failed",
                "%s: %s" % (path.name, repr(exc)[:160]),
            )
        if not np.all(np.isfinite(tensor)):
            self.nonfinite_frame_count += 1
            raise CalibrationError(
                "calibration_tensor_nonfinite", "%s produced a non-finite tensor" % path.name
            )
        minimum = float(stats["input_min"])
        maximum = float(stats["input_max"])
        self.tensor_min = minimum if self.tensor_min is None else min(self.tensor_min, minimum)
        self.tensor_max = maximum if self.tensor_max is None else max(self.tensor_max, maximum)
        for index, value in enumerate(stats["channel_means"][:3]):
            self.channel_mean_sums[index] += float(value)
        self.frames_read += 1
        self.batches_produced += 1
        return np.ascontiguousarray(tensor)

    def metrics(self) -> Dict[str, Any]:
        divisor = max(1, self.frames_read)
        return {
            "calibration_frame_count": self.frame_count,
            "calibration_frames_read": self.frames_read,
            "calibration_batches_produced": self.batches_produced,
            "calibration_batch_size": self.batch_size,
            "skipped_frame_count": self.skipped_frame_count,
            "calibration_nonfinite_frame_count": self.nonfinite_frame_count,
            "calibration_tensor_min": round(self.tensor_min, 6) if self.tensor_min is not None else None,
            "calibration_tensor_max": round(self.tensor_max, 6) if self.tensor_max is not None else None,
            "calibration_tensor_channel_mean": [
                round(value / divisor, 6) for value in self.channel_mean_sums
            ],
            "calibration_preprocess_profile": preprocess_profile_fragment(self.input_contract),
            "calibration_preprocess_source": "workers.core.tensorrt_perception.preprocess_bgr",
        }


# ── TensorRT calibrator ─────────────────────────────────────────────────────


@dataclass
class CalibratorReport:
    """What the calibrator actually did, for the evidence tree."""

    calibration_executed: bool = False
    cache_reused: bool = False
    cache_written: bool = False
    cache_path: str = ""
    cache_sha256: str = ""
    cache_size_bytes: int = 0
    calibration_cache_key: str = ""
    cuda_error_count: int = 0
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload.update(payload.pop("details"))
        return payload


def build_entropy_calibrator(
    *,
    feeder: CalibrationBatchFeeder,
    cuda_runtime: Any,
    cache_path: Path,
    cache_key: str,
    allow_cache_reuse: bool = True,
) -> Any:
    """Create a TensorRT 8.5 ``IInt8EntropyCalibrator2`` bound to ``feeder``.

    The class is defined lazily because it must subclass a TensorRT type, and
    TensorRT is absent on the simulation PC where Gate A runs.
    """

    try:
        import tensorrt as trt  # type: ignore[import-not-found]
    except Exception as exc:
        raise CalibrationError("tensorrt_builder_unavailable", repr(exc)[:200])

    version = str(getattr(trt, "__version__", ""))
    try:
        major = int(version.split(".")[0])
    except (ValueError, IndexError):
        major = 0
    if major != 8:
        raise CalibrationError(
            "tensorrt_builder_unavailable",
            "Phase 13D targets TensorRT 8, found %s" % version,
        )

    class _EntropyCalibrator(trt.IInt8EntropyCalibrator2):  # type: ignore[misc]
        """Batch-1 entropy calibrator over a single reusable device buffer."""

        def __init__(self) -> None:
            super(_EntropyCalibrator, self).__init__()
            self.feeder = feeder
            self.buffer = ReusableDeviceBuffer(cuda_runtime, feeder.tensor_nbytes)
            self.cache_path = Path(cache_path)
            self.cache_key = str(cache_key)
            self.allow_cache_reuse = bool(allow_cache_reuse)
            self.cache_read_count = 0
            self.cache_write_count = 0
            self.cache_bytes_written = 0
            self.batches_served = 0
            self.error = None  # type: Optional[str]

        # TensorRT calibrator protocol ------------------------------------
        def get_batch_size(self) -> int:
            return int(self.feeder.batch_size)

        def get_batch(self, names: Any, *args: Any) -> Optional[List[int]]:
            tensor = self.feeder.next_batch()
            if tensor is None:
                return None
            pointer = self.buffer.upload(tensor.reshape(-1))
            self.batches_served += 1
            return [int(pointer)]

        def read_calibration_cache(self) -> Optional[bytes]:
            if not self.allow_cache_reuse:
                return None
            meta_path = calibration_meta_path(self.cache_path)
            meta = None  # type: Optional[CalibrationCacheMeta]
            if meta_path.is_file():
                try:
                    meta = CalibrationCacheMeta.load(meta_path)
                except Exception:
                    meta = None
            verdict = evaluate_cache_staleness(
                meta, cache_path=self.cache_path, expected_key=self.cache_key
            )
            if verdict["calibration_cache_stale"]:
                return None
            self.cache_read_count += 1
            return self.cache_path.read_bytes()

        def write_calibration_cache(self, cache: Any) -> None:
            payload = bytes(cache)
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_bytes(payload)
            self.cache_write_count += 1
            self.cache_bytes_written = len(payload)

        # Housekeeping -----------------------------------------------------
        def close(self) -> None:
            self.buffer.close()

        def metrics(self) -> Dict[str, Any]:
            payload = {
                "calibration_batches_served": self.batches_served,
                "calibration_cache_read_count": self.cache_read_count,
                "calibration_cache_write_count": self.cache_write_count,
                "calibration_cache_bytes_written": self.cache_bytes_written,
                "calibration_algorithm": CALIBRATOR_ALGORITHM,
            }
            payload.update(self.feeder.metrics())
            payload.update(self.buffer.metrics())
            payload["cuda_error_count"] = int(getattr(cuda_runtime, "error_count", 0))
            return payload

    return _EntropyCalibrator()


def calibration_meta_path(cache_path: Path) -> Path:
    return Path(str(cache_path) + ".meta.json")
