"""Phase 13C external model / engine asset contract.

Phase 13C never vendors, downloads or commits model assets. The YOLOv9 source
tree, the PyTorch weights, the exported ONNX graph and the target-built
TensorRT engine all stay **external** to this repository and are addressed
through CLI/environment contracts.

This module owns:

* SHA-256 / size identity for every external asset;
* the model manifest (source -> weights -> ONNX contract);
* the engine manifest (ONNX -> target-built engine contract);
* the **engine cache key**, which binds an engine to the exact ONNX, TensorRT
  version, CUDA version, GPU, precision, input profile and postprocess profile
  that produced it. Any difference makes the engine stale and it must be
  rebuilt on the target.

Runtime compatibility: Jetson Python 3.8.10 (typing generics only).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

MODEL_MANIFEST_VERSION = 1
ENGINE_MANIFEST_VERSION = 1

#: Formal Phase 13C model target. FP16 only; INT8 is Phase 13D.
DEFAULT_MODEL_FAMILY = "yolov9"
DEFAULT_MODEL_VARIANT = "yolov9-c"
DEFAULT_PRECISION = "fp16"
DEFAULT_BATCH_SIZE = 1
DEFAULT_INPUT_SIZE = 640
DEFAULT_POSTPROCESS_PROFILE = "yolov9-c"
SUPPORTED_PRECISIONS = ("fp16",)

_HASH_CHUNK_BYTES = 1024 * 1024


class AssetContractError(RuntimeError):
    """External asset contract violation carrying a Phase 13C classification."""

    def __init__(self, classification: str, message: str) -> None:
        super().__init__("%s: %s" % (classification, message))
        self.classification = classification
        self.message = message


def sha256_file(path: Path, *, chunk_bytes: int = _HASH_CHUNK_BYTES) -> str:
    """Streaming SHA-256 so a 50 MB checkpoint never lands in memory at once."""

    digest = hashlib.sha256()
    with open(str(path), "rb") as handle:
        while True:
            chunk = handle.read(chunk_bytes)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def describe_file(path: Optional[Path]) -> Dict[str, Any]:
    """Identity of one external asset without ever copying or moving it."""

    if path is None:
        return {"path": None, "exists": False, "sha256": None, "size_bytes": None}
    candidate = Path(path)
    if not candidate.is_file():
        return {
            "path": str(candidate),
            "exists": False,
            "sha256": None,
            "size_bytes": None,
        }
    return {
        "path": str(candidate),
        "exists": True,
        "sha256": sha256_file(candidate),
        "size_bytes": int(candidate.stat().st_size),
    }


def external_git_sha(source_root: Optional[Path]) -> str:
    """Read-only git SHA of the external model source tree, if it is a repo."""

    if source_root is None or not Path(source_root).is_dir():
        return ""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(source_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


# ── Input / output contract ─────────────────────────────────────────────────


@dataclass
class InputContract:
    """The exact tensor the engine expects, and how a BGR frame becomes it."""

    input_name: str = "images"
    batch_size: int = DEFAULT_BATCH_SIZE
    channels: int = 3
    height: int = DEFAULT_INPUT_SIZE
    width: int = DEFAULT_INPUT_SIZE
    input_dtype: str = "float32"
    input_color_order: str = "RGB"
    source_pixel_format: str = "BGR8"
    normalization_scale: float = 255.0
    letterbox_policy: str = "ratio_preserving_pad_114_stride32"
    layout: str = "NCHW"

    @property
    def shape(self) -> List[int]:
        return [self.batch_size, self.channels, self.height, self.width]

    @property
    def shape_text(self) -> str:
        return "x".join(str(value) for value in self.shape)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["input_shape"] = self.shape
        payload["input_shape_text"] = self.shape_text
        return payload


@dataclass
class OutputContract:
    """What the exported graph actually emits — never assumed, always recorded.

    ``layout`` is derived by inspecting the real exported graph:
    ``channels_first`` is ``(1, 4 + num_classes, anchors)`` and
    ``anchors_first`` is ``(1, anchors, 4 + num_classes)``. ``has_objectness``
    marks the legacy ``(1, anchors, 5 + num_classes)`` encoding.
    """

    output_names: List[str] = field(default_factory=lambda: ["output0"])
    output_shapes: List[List[int]] = field(default_factory=list)
    output_dtypes: List[str] = field(default_factory=lambda: ["float32"])
    layout: str = "unknown"
    nms_embedded: bool = False
    has_objectness: bool = False
    box_encoding: str = "cxcywh"
    coordinate_space: str = "letterbox_pixels"
    class_count: int = 0
    class_names_source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PostprocessProfile:
    """Bounded postprocess thresholds; identical on both parity backends."""

    name: str = DEFAULT_POSTPROCESS_PROFILE
    confidence_threshold: float = 0.25
    nms_iou_threshold: float = 0.45
    max_detections: int = 300

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def cache_fragment(self) -> str:
        return "%s|conf=%.4f|iou=%.4f|max=%d" % (
            self.name,
            self.confidence_threshold,
            self.nms_iou_threshold,
            self.max_detections,
        )


# ── Model manifest ──────────────────────────────────────────────────────────


@dataclass
class ModelManifest:
    """External source -> weights -> ONNX identity, written next to the ONNX."""

    model_family: str = DEFAULT_MODEL_FAMILY
    model_variant: str = DEFAULT_MODEL_VARIANT
    external_source_root: str = ""
    external_source_git_sha: str = ""
    weights_path: str = ""
    weights_sha256: str = ""
    weights_size_bytes: int = 0
    onnx_path: str = ""
    onnx_sha256: str = ""
    onnx_size_bytes: int = 0
    onnx_opset: int = 0
    exporter: str = ""
    export_command: List[str] = field(default_factory=list)
    export_duration_sec: float = 0.0
    torch_version: str = ""
    input_contract: Dict[str, Any] = field(default_factory=dict)
    output_contract: Dict[str, Any] = field(default_factory=dict)
    postprocess_profile: Dict[str, Any] = field(default_factory=dict)
    created_at_utc: str = ""
    manifest_version: int = MODEL_MANIFEST_VERSION

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
    def load(path: Path) -> "ModelManifest":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        known = {item for item in ModelManifest().to_dict()}
        return ModelManifest(**{k: v for k, v in payload.items() if k in known})


# ── Engine manifest and cache key ───────────────────────────────────────────


def engine_cache_key(
    *,
    onnx_sha256: str,
    tensorrt_version: str,
    cuda_version: str,
    gpu_name: str,
    compute_capability: str,
    precision: str,
    input_profile: str,
    postprocess_profile: str,
) -> str:
    """Bind an engine to everything that can invalidate it.

    A TensorRT plan is not portable across any of these axes, so all of them
    are hashed. If a single one differs at load time the engine is stale and
    must be rebuilt on the target — it is never silently reused.
    """

    material = "\n".join(
        [
            "onnx_sha256=%s" % onnx_sha256,
            "tensorrt_version=%s" % tensorrt_version,
            "cuda_version=%s" % cuda_version,
            "gpu_name=%s" % gpu_name,
            "compute_capability=%s" % compute_capability,
            "precision=%s" % precision,
            "input_profile=%s" % input_profile,
            "postprocess_profile=%s" % postprocess_profile,
        ]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass
class EngineManifest:
    """Target-built engine identity, written next to the .engine file."""

    engine_path: str = ""
    engine_sha256: str = ""
    engine_size_bytes: int = 0
    engine_precision: str = DEFAULT_PRECISION
    engine_builder: str = ""
    engine_build_command: List[str] = field(default_factory=list)
    engine_build_duration_sec: float = 0.0
    workspace_limit_bytes: int = 0
    onnx_sha256: str = ""
    onnx_path: str = ""
    tensorrt_version: str = ""
    cuda_version: str = ""
    jetson_model: str = ""
    gpu_name: str = ""
    compute_capability: str = ""
    input_profile: str = ""
    postprocess_profile: str = ""
    engine_cache_key: str = ""
    engine_binding_count: int = 0
    engine_input_bindings: List[Dict[str, Any]] = field(default_factory=list)
    engine_output_bindings: List[Dict[str, Any]] = field(default_factory=list)
    engine_dynamic_shapes: bool = False
    engine_serialization_verified: bool = False
    engine_deserialization_verified: bool = False
    engine_compatibility_verified: bool = False
    int8_engine_built: bool = False
    dla_enabled: bool = False
    built_on_target: bool = False
    created_at_utc: str = ""
    manifest_version: int = ENGINE_MANIFEST_VERSION

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
    def load(path: Path) -> "EngineManifest":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        known = {item for item in EngineManifest().to_dict()}
        return EngineManifest(**{k: v for k, v in payload.items() if k in known})

    def expected_cache_key(self) -> str:
        return engine_cache_key(
            onnx_sha256=self.onnx_sha256,
            tensorrt_version=self.tensorrt_version,
            cuda_version=self.cuda_version,
            gpu_name=self.gpu_name,
            compute_capability=self.compute_capability,
            precision=self.engine_precision,
            input_profile=self.input_profile,
            postprocess_profile=self.postprocess_profile,
        )


@dataclass(frozen=True)
class StalenessVerdict:
    """Why an engine may or may not be reused."""

    stale: bool
    reasons: List[str]
    observed_cache_key: str
    manifest_cache_key: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "engine_stale": self.stale,
            "engine_stale_reasons": list(self.reasons),
            "engine_observed_cache_key": self.observed_cache_key,
            "engine_manifest_cache_key": self.manifest_cache_key,
        }


def evaluate_engine_staleness(
    manifest: EngineManifest,
    *,
    engine_path: Path,
    observed_onnx_sha256: str,
    observed_tensorrt_version: str,
    observed_cuda_version: str,
    observed_gpu_name: str,
    observed_compute_capability: str,
    precision: str,
    input_profile: str,
    postprocess_profile: str,
    verify_engine_hash: bool = True,
) -> StalenessVerdict:
    """Decide whether a cached engine may be reused, and say exactly why not."""

    reasons = []  # type: List[str]
    observed_key = engine_cache_key(
        onnx_sha256=observed_onnx_sha256,
        tensorrt_version=observed_tensorrt_version,
        cuda_version=observed_cuda_version,
        gpu_name=observed_gpu_name,
        compute_capability=observed_compute_capability,
        precision=precision,
        input_profile=input_profile,
        postprocess_profile=postprocess_profile,
    )
    manifest_key = manifest.engine_cache_key or manifest.expected_cache_key()

    if not Path(engine_path).is_file():
        reasons.append("engine_file_missing")
    elif verify_engine_hash and manifest.engine_sha256:
        actual = sha256_file(Path(engine_path))
        if actual != manifest.engine_sha256:
            reasons.append("engine_sha256_mismatch")

    for label, expected, observed in (
        ("onnx_sha256", manifest.onnx_sha256, observed_onnx_sha256),
        ("tensorrt_version", manifest.tensorrt_version, observed_tensorrt_version),
        ("cuda_version", manifest.cuda_version, observed_cuda_version),
        ("gpu_name", manifest.gpu_name, observed_gpu_name),
        ("compute_capability", manifest.compute_capability, observed_compute_capability),
        ("precision", manifest.engine_precision, precision),
        ("input_profile", manifest.input_profile, input_profile),
        ("postprocess_profile", manifest.postprocess_profile, postprocess_profile),
    ):
        if expected and observed and expected != observed:
            reasons.append("%s_mismatch" % label)

    if manifest_key and observed_key and manifest_key != observed_key:
        reasons.append("engine_cache_key_mismatch")
    if not manifest.built_on_target:
        reasons.append("engine_not_built_on_target")

    return StalenessVerdict(
        stale=bool(reasons),
        reasons=reasons,
        observed_cache_key=observed_key,
        manifest_cache_key=manifest_key,
    )


# ── External asset discovery ────────────────────────────────────────────────


def resolve_external_path(
    explicit: Optional[str], environment_variable: str
) -> Optional[Path]:
    """CLI argument wins, then the environment. No machine-specific default."""

    if explicit:
        return Path(explicit)
    value = os.environ.get(environment_variable, "").strip()
    return Path(value) if value else None


def verify_model_assets(
    *,
    source_root: Optional[Path],
    weights: Optional[Path],
    require_source: bool = True,
    require_weights: bool = True,
) -> Dict[str, Any]:
    """Report the external source/weights contract without modifying anything."""

    source_ready = source_root is not None and Path(source_root).is_dir()
    weights_info = describe_file(weights)
    blockers = []  # type: List[str]
    if require_source and not source_ready:
        blockers.append("model_source_missing")
    if require_weights and not weights_info["exists"]:
        blockers.append("model_weights_missing")

    payload = {
        "external_source_root": str(source_root) if source_root else None,
        "external_model_source_ready": bool(source_ready),
        "external_source_git_sha": external_git_sha(source_root) if source_ready else "",
        "external_weights_ready": bool(weights_info["exists"]),
        "weights_path": weights_info["path"],
        "weights_sha256": weights_info["sha256"],
        "weights_sha256_recorded": bool(weights_info["sha256"]),
        "weights_size_bytes": weights_info["size_bytes"],
        "assets_committed_to_repository": False,
        "assets_downloaded": False,
        "blockers": blockers,
    }
    if source_ready:
        root = Path(source_root)
        payload["source_has_export_script"] = (root / "export.py").is_file()
        payload["source_has_models_package"] = (root / "models").is_dir()
        payload["source_has_utils_package"] = (root / "utils").is_dir()
        payload["source_class_names_file"] = (
            str(root / "data" / "coco.yaml") if (root / "data" / "coco.yaml").is_file() else ""
        )
    return payload


def verify_onnx_asset(
    onnx_path: Optional[Path], *, expected_sha256: str = ""
) -> Dict[str, Any]:
    """Report ONNX identity and, when given, confirm it against a manifest."""

    info = describe_file(onnx_path)
    blockers = []  # type: List[str]
    if not info["exists"]:
        blockers.append("onnx_missing")
    elif expected_sha256 and info["sha256"] != expected_sha256:
        blockers.append("onnx_sha256_mismatch")
    return {
        "onnx_path": info["path"],
        "onnx_ready": info["exists"],
        "onnx_sha256": info["sha256"],
        "onnx_sha256_recorded": bool(info["sha256"]),
        "onnx_size_bytes": info["size_bytes"],
        "onnx_sha256_expected": expected_sha256 or None,
        "blockers": blockers,
    }


def boundary_fields() -> Dict[str, Any]:
    """Phase 13C precision boundary. INT8/QAT belong to Phase 13D."""

    return {
        "precision": DEFAULT_PRECISION,
        "int8_engine_built": False,
        "int8_calibration_verified": False,
        "qat_verified": False,
        "dla_enabled": False,
    }
