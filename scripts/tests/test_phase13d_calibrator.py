"""Phase 13D INT8 calibrator contract tests.

No TensorRT and no GPU are required: the CUDA runtime is the Phase 13C ctypes
test double and the batch feeder is deliberately TensorRT-free, so Gate A can
prove the whole calibration contract — cache identity and staleness, a single
reusable device allocation, zero skipped frames, and preprocessing that is
literally the runtime preprocessing function.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
TESTS_DIR = Path(__file__).resolve().parent
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR), str(TESTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from test_phase13c_tensorrt_runtime import FakeCudaLibrary, make_cuda_runtime  # noqa: E402
from workers.core.int8_calibrator import (  # noqa: E402
    CALIBRATOR_ALGORITHM,
    CalibrationBatchFeeder,
    CalibrationCacheMeta,
    CalibrationError,
    ReusableDeviceBuffer,
    calibration_cache_key,
    calibration_meta_path,
    evaluate_cache_staleness,
    preprocess_profile_fragment,
    sha256_bytes,
)
from workers.core.tensorrt_asset_contract import InputContract  # noqa: E402
from workers.core.tensorrt_perception import preprocess_bgr  # noqa: E402

BASE_KEY_ARGS = {
    "onnx_sha256": "a" * 64,
    "dataset_sha256": "b" * 64,
    "calibration_frame_count": 640,
    "algorithm": CALIBRATOR_ALGORITHM,
    "batch_size": 1,
    "input_profile": "1x3x640x640",
    "preprocess_profile": preprocess_profile_fragment(InputContract()),
    "tensorrt_version": "8.5.2.2",
    "cuda_version": "11.4",
    "gpu_name": "Orin NX",
}


def small_contract() -> InputContract:
    """A 64x64 contract keeps the tests fast without changing the semantics."""

    return InputContract(height=64, width=64)


def frame(value: int = 120, *, width: int = 96, height: int = 54) -> np.ndarray:
    rng = np.random.RandomState(value)
    base = np.full((height, width, 3), value, dtype=np.int16)
    noise = rng.randint(-8, 9, size=(height, width, 3))
    return np.clip(base + noise, 8, 240).astype(np.uint8)


class TestCalibrationCacheKey(unittest.TestCase):
    def test_key_is_deterministic(self) -> None:
        self.assertEqual(
            calibration_cache_key(**BASE_KEY_ARGS), calibration_cache_key(**BASE_KEY_ARGS)
        )

    def test_every_axis_changes_the_key(self) -> None:
        baseline = calibration_cache_key(**BASE_KEY_ARGS)
        for field, replacement in (
            ("onnx_sha256", "c" * 64),
            ("dataset_sha256", "d" * 64),
            ("calibration_frame_count", 512),
            ("algorithm", "IInt8MinMaxCalibrator"),
            ("batch_size", 2),
            ("input_profile", "1x3x512x512"),
            ("preprocess_profile", "different"),
            ("tensorrt_version", "8.6.1"),
            ("cuda_version", "11.8"),
            ("gpu_name", "AGX Orin"),
        ):
            payload = dict(BASE_KEY_ARGS)
            payload[field] = replacement
            self.assertNotEqual(baseline, calibration_cache_key(**payload), field)

    def test_preprocess_fragment_tracks_the_contract(self) -> None:
        fragment = preprocess_profile_fragment(InputContract())
        self.assertIn("order=RGB", fragment)
        self.assertIn("scale=255.0000", fragment)
        self.assertIn("shape=1x3x640x640", fragment)
        self.assertNotEqual(
            fragment, preprocess_profile_fragment(InputContract(input_color_order="BGR"))
        )


class TestCacheStaleness(unittest.TestCase):
    def _meta(self, cache: Path, key: str) -> CalibrationCacheMeta:
        payload = cache.read_bytes()
        return CalibrationCacheMeta(
            cache_path=str(cache),
            cache_sha256=sha256_bytes(payload),
            cache_size_bytes=len(payload),
            calibration_cache_key=key,
            built_on_target=True,
        )

    def test_a_matching_cache_is_reusable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "model.calibration.cache"
            cache.write_bytes(b"TRT-CALIBRATION-CACHE")
            key = calibration_cache_key(**BASE_KEY_ARGS)
            verdict = evaluate_cache_staleness(
                self._meta(cache, key), cache_path=cache, expected_key=key
            )
            self.assertFalse(verdict["calibration_cache_stale"], verdict)

    def test_a_different_dataset_makes_the_cache_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "model.calibration.cache"
            cache.write_bytes(b"TRT-CALIBRATION-CACHE")
            recorded = calibration_cache_key(**BASE_KEY_ARGS)
            payload = dict(BASE_KEY_ARGS)
            payload["dataset_sha256"] = "e" * 64
            verdict = evaluate_cache_staleness(
                self._meta(cache, recorded),
                cache_path=cache,
                expected_key=calibration_cache_key(**payload),
            )
            self.assertTrue(verdict["calibration_cache_stale"])
            self.assertIn("calibration_cache_key_mismatch", verdict["calibration_cache_stale_reasons"])

    def test_a_tampered_cache_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "model.calibration.cache"
            cache.write_bytes(b"TRT-CALIBRATION-CACHE")
            key = calibration_cache_key(**BASE_KEY_ARGS)
            meta = self._meta(cache, key)
            cache.write_bytes(b"TAMPERED")
            verdict = evaluate_cache_staleness(meta, cache_path=cache, expected_key=key)
            self.assertTrue(verdict["calibration_cache_stale"])
            self.assertIn(
                "calibration_cache_sha256_mismatch", verdict["calibration_cache_stale_reasons"]
            )

    def test_a_missing_cache_or_meta_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "absent.cache"
            verdict = evaluate_cache_staleness(None, cache_path=cache, expected_key="k")
            self.assertTrue(verdict["calibration_cache_stale"])
            self.assertIn("calibration_cache_meta_missing", verdict["calibration_cache_stale_reasons"])
            self.assertIn("calibration_cache_missing", verdict["calibration_cache_stale_reasons"])

    def test_a_cache_not_built_on_target_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "model.calibration.cache"
            cache.write_bytes(b"TRT-CALIBRATION-CACHE")
            key = calibration_cache_key(**BASE_KEY_ARGS)
            meta = self._meta(cache, key)
            meta.built_on_target = False
            verdict = evaluate_cache_staleness(meta, cache_path=cache, expected_key=key)
            self.assertTrue(verdict["calibration_cache_stale"])
            self.assertIn(
                "calibration_cache_not_built_on_target", verdict["calibration_cache_stale_reasons"]
            )

    def test_meta_round_trips_through_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "model.calibration.cache"
            cache.write_bytes(b"TRT-CALIBRATION-CACHE")
            meta = self._meta(cache, calibration_cache_key(**BASE_KEY_ARGS))
            meta.dataset_sha256 = "b" * 64
            path = calibration_meta_path(cache)
            meta.write(path)
            self.assertTrue(str(path).endswith(".cache.meta.json"))
            loaded = CalibrationCacheMeta.load(path)
            self.assertEqual(loaded.to_dict(), meta.to_dict())


class TestReusableDeviceBuffer(unittest.TestCase):
    def test_one_allocation_serves_every_batch(self) -> None:
        fake = FakeCudaLibrary()
        runtime = make_cuda_runtime(fake)
        buffer = ReusableDeviceBuffer(runtime, 4 * 16)
        pointers = set()
        for index in range(8):
            pointers.add(buffer.upload(np.full(16, index, dtype=np.float32)))
        self.assertEqual(len(pointers), 1)
        metrics = buffer.metrics()
        self.assertEqual(metrics["calibration_device_allocation_count"], 1)
        self.assertEqual(metrics["per_batch_device_allocation_count"], 0)
        self.assertEqual(metrics["calibration_batch_upload_count"], 8)
        self.assertEqual(fake.calls.count("cudaMalloc"), 1)
        buffer.close()
        self.assertEqual(len(fake.freed), 1)
        self.assertEqual(runtime.error_count, 0)

    def test_a_wrong_sized_batch_is_refused(self) -> None:
        buffer = ReusableDeviceBuffer(make_cuda_runtime(FakeCudaLibrary()), 4 * 16)
        with self.assertRaises(CalibrationError) as caught:
            buffer.upload(np.zeros(8, dtype=np.float32))
        self.assertEqual(caught.exception.classification, "calibration_buffer_size_mismatch")
        buffer.close()

    def test_upload_after_close_is_refused(self) -> None:
        buffer = ReusableDeviceBuffer(make_cuda_runtime(FakeCudaLibrary()), 4 * 4)
        buffer.close()
        with self.assertRaises(CalibrationError) as caught:
            buffer.upload(np.zeros(4, dtype=np.float32))
        self.assertEqual(caught.exception.classification, "calibration_buffer_closed")

    def test_close_is_idempotent(self) -> None:
        fake = FakeCudaLibrary()
        buffer = ReusableDeviceBuffer(make_cuda_runtime(fake), 16)
        buffer.close()
        buffer.close()
        self.assertEqual(len(fake.freed), 1)

    def test_a_zero_sized_buffer_is_refused(self) -> None:
        with self.assertRaises(CalibrationError):
            ReusableDeviceBuffer(make_cuda_runtime(FakeCudaLibrary()), 0)


class TestCalibrationBatchFeeder(unittest.TestCase):
    def _feeder(self, count: int = 5, **kwargs: Any) -> CalibrationBatchFeeder:
        images = {Path("frame_%02d.png" % index): frame(60 + index * 20) for index in range(count)}
        kwargs.setdefault("input_contract", small_contract())
        kwargs.setdefault("reader", lambda path: images[Path(path)])
        return CalibrationBatchFeeder(sorted(images), **kwargs)

    def test_batches_are_produced_in_order_and_then_exhaust(self) -> None:
        feeder = self._feeder(count=4)
        shapes = []  # type: List[Any]
        while True:
            batch = feeder.next_batch()
            if batch is None:
                break
            shapes.append(batch.shape)
        self.assertEqual(len(shapes), 4)
        self.assertTrue(all(shape == (1, 3, 64, 64) for shape in shapes))
        self.assertTrue(feeder.exhausted())
        self.assertIsNone(feeder.next_batch())

    def test_zero_frames_are_ever_skipped(self) -> None:
        feeder = self._feeder(count=6)
        while feeder.next_batch() is not None:
            pass
        metrics = feeder.metrics()
        self.assertEqual(metrics["skipped_frame_count"], 0)
        self.assertEqual(metrics["calibration_frames_read"], 6)
        self.assertEqual(metrics["calibration_batches_produced"], 6)
        self.assertEqual(metrics["calibration_batch_size"], 1)
        self.assertEqual(
            metrics["calibration_preprocess_source"],
            "workers.core.tensorrt_perception.preprocess_bgr",
        )

    def test_preprocessing_is_the_runtime_preprocessing_function(self) -> None:
        contract = small_contract()
        image = frame(133)
        feeder = CalibrationBatchFeeder(
            [Path("only.png")], input_contract=contract, reader=lambda _path: image
        )
        produced = feeder.next_batch()
        expected, _letterbox, _stats = preprocess_bgr(image, contract)
        np.testing.assert_array_equal(produced, expected)
        self.assertEqual(produced.dtype, np.float32)

    def test_tensor_byte_size_matches_the_contract(self) -> None:
        feeder = self._feeder(count=1)
        self.assertEqual(feeder.tensor_nbytes, 1 * 3 * 64 * 64 * 4)

    def test_statistics_are_recorded_across_the_corpus(self) -> None:
        feeder = self._feeder(count=5)
        while feeder.next_batch() is not None:
            pass
        metrics = feeder.metrics()
        self.assertIsNotNone(metrics["calibration_tensor_min"])
        self.assertIsNotNone(metrics["calibration_tensor_max"])
        self.assertGreaterEqual(metrics["calibration_tensor_min"], 0.0)
        self.assertLessEqual(metrics["calibration_tensor_max"], 1.0)
        self.assertEqual(len(metrics["calibration_tensor_channel_mean"]), 3)

    def test_an_unreadable_frame_is_a_hard_failure_not_a_skip(self) -> None:
        def _reader(_path: Any) -> Any:
            raise CalibrationError("calibration_frame_unreadable", "decode failed")

        feeder = CalibrationBatchFeeder(
            [Path("bad.png")], input_contract=small_contract(), reader=_reader
        )
        with self.assertRaises(CalibrationError) as caught:
            feeder.next_batch()
        self.assertEqual(caught.exception.classification, "calibration_frame_unreadable")
        self.assertEqual(feeder.metrics()["skipped_frame_count"], 0)

    def test_a_malformed_frame_fails_preprocessing_rather_than_being_dropped(self) -> None:
        feeder = CalibrationBatchFeeder(
            [Path("bad.png")],
            input_contract=small_contract(),
            reader=lambda _path: np.zeros((16, 16), dtype=np.uint8),
        )
        with self.assertRaises(CalibrationError) as caught:
            feeder.next_batch()
        self.assertEqual(caught.exception.classification, "calibration_frame_preprocess_failed")

    def test_batch_sizes_other_than_one_are_refused(self) -> None:
        with self.assertRaises(CalibrationError) as caught:
            CalibrationBatchFeeder([Path("a.png")], batch_size=8)
        self.assertEqual(caught.exception.classification, "calibration_batch_size_unsupported")

    def test_an_empty_corpus_is_refused(self) -> None:
        with self.assertRaises(CalibrationError) as caught:
            CalibrationBatchFeeder([])
        self.assertEqual(caught.exception.classification, "calibration_frames_missing")


if __name__ == "__main__":
    unittest.main()
