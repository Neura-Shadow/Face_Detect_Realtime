"""Phase 13C external asset contract, manifest schema and engine cache key."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workers.core.tensorrt_asset_contract import (
    DEFAULT_PRECISION,
    EngineManifest,
    InputContract,
    ModelManifest,
    OutputContract,
    PostprocessProfile,
    boundary_fields,
    describe_file,
    engine_cache_key,
    evaluate_engine_staleness,
    resolve_external_path,
    sha256_file,
    verify_model_assets,
    verify_onnx_asset,
)


class TestFileIdentity(unittest.TestCase):
    def test_sha256_and_size_are_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "asset.bin"
            path.write_bytes(b"phase13c" * 100)
            info = describe_file(path)
            self.assertTrue(info["exists"])
            self.assertEqual(info["size_bytes"], 800)
            self.assertEqual(info["sha256"], sha256_file(path))
            self.assertEqual(len(info["sha256"]), 64)

    def test_missing_file_is_reported_not_raised(self) -> None:
        info = describe_file(Path("does-not-exist.onnx"))
        self.assertFalse(info["exists"])
        self.assertIsNone(info["sha256"])

    def test_none_path_is_tolerated(self) -> None:
        info = describe_file(None)
        self.assertFalse(info["exists"])
        self.assertIsNone(info["path"])


class TestExternalPathResolution(unittest.TestCase):
    def test_cli_argument_wins_over_environment(self) -> None:
        import os

        os.environ["MA_VLNA_TEST_ASSET"] = "from-env"
        try:
            self.assertEqual(
                resolve_external_path("from-cli", "MA_VLNA_TEST_ASSET"), Path("from-cli")
            )
            self.assertEqual(
                resolve_external_path("", "MA_VLNA_TEST_ASSET"), Path("from-env")
            )
        finally:
            del os.environ["MA_VLNA_TEST_ASSET"]

    def test_absent_environment_yields_none(self) -> None:
        self.assertIsNone(resolve_external_path("", "MA_VLNA_DEFINITELY_UNSET_VAR"))


class TestAssetVerification(unittest.TestCase):
    def test_missing_source_and_weights_are_classified(self) -> None:
        report = verify_model_assets(source_root=Path("nope"), weights=Path("nope.pt"))
        self.assertIn("model_source_missing", report["blockers"])
        self.assertIn("model_weights_missing", report["blockers"])
        self.assertFalse(report["external_model_source_ready"])
        self.assertFalse(report["assets_committed_to_repository"])
        self.assertFalse(report["assets_downloaded"])

    def test_present_assets_record_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "models").mkdir()
            (root / "utils").mkdir()
            (root / "export.py").write_text("# stub", encoding="utf-8")
            weights = root / "weights.pt"
            weights.write_bytes(b"weights")
            report = verify_model_assets(source_root=root, weights=weights)
            self.assertEqual(report["blockers"], [])
            self.assertTrue(report["external_model_source_ready"])
            self.assertTrue(report["weights_sha256_recorded"])
            self.assertTrue(report["source_has_export_script"])

    def test_onnx_hash_mismatch_is_a_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            onnx = Path(directory) / "model.onnx"
            onnx.write_bytes(b"graph")
            good = verify_onnx_asset(onnx, expected_sha256=sha256_file(onnx))
            self.assertEqual(good["blockers"], [])
            bad = verify_onnx_asset(onnx, expected_sha256="0" * 64)
            self.assertIn("onnx_sha256_mismatch", bad["blockers"])

    def test_missing_onnx_is_a_blocker(self) -> None:
        report = verify_onnx_asset(Path("absent.onnx"))
        self.assertIn("onnx_missing", report["blockers"])


class TestContracts(unittest.TestCase):
    def test_input_contract_shape(self) -> None:
        contract = InputContract()
        self.assertEqual(contract.shape, [1, 3, 640, 640])
        self.assertEqual(contract.shape_text, "1x3x640x640")
        payload = contract.to_dict()
        self.assertEqual(payload["input_color_order"], "RGB")
        self.assertEqual(payload["source_pixel_format"], "BGR8")
        self.assertEqual(payload["normalization_scale"], 255.0)

    def test_postprocess_profile_defaults_and_cache_fragment(self) -> None:
        profile = PostprocessProfile()
        self.assertEqual(profile.confidence_threshold, 0.25)
        self.assertEqual(profile.nms_iou_threshold, 0.45)
        self.assertEqual(profile.max_detections, 300)
        self.assertIn("conf=0.2500", profile.cache_fragment())

    def test_boundary_fields_pin_fp16_only(self) -> None:
        fields = boundary_fields()
        self.assertEqual(fields["precision"], DEFAULT_PRECISION)
        self.assertFalse(fields["int8_engine_built"])
        self.assertFalse(fields["int8_calibration_verified"])
        self.assertFalse(fields["qat_verified"])
        self.assertFalse(fields["dla_enabled"])


class TestManifests(unittest.TestCase):
    def test_model_manifest_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = ModelManifest(
                weights_sha256="a" * 64,
                onnx_sha256="b" * 64,
                onnx_opset=12,
                input_contract=InputContract().to_dict(),
                output_contract=OutputContract(class_count=80).to_dict(),
                postprocess_profile=PostprocessProfile().to_dict(),
            )
            path = manifest.write(Path(directory) / "model.manifest.json")
            loaded = ModelManifest.load(path)
            self.assertEqual(loaded.onnx_sha256, "b" * 64)
            self.assertEqual(loaded.onnx_opset, 12)
            self.assertEqual(loaded.output_contract["class_count"], 80)

    def test_engine_manifest_round_trip_and_expected_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = EngineManifest(
                onnx_sha256="c" * 64,
                tensorrt_version="8.5.2.2",
                cuda_version="11.4",
                gpu_name="Orin NX",
                compute_capability="8.7",
                engine_precision="fp16",
                input_profile="1x3x640x640",
                postprocess_profile="yolov9-c|conf=0.2500|iou=0.4500|max=300",
                built_on_target=True,
            )
            manifest.engine_cache_key = manifest.expected_cache_key()
            path = manifest.write(Path(directory) / "engine.manifest.json")
            loaded = EngineManifest.load(path)
            self.assertEqual(loaded.engine_cache_key, manifest.engine_cache_key)
            self.assertEqual(loaded.expected_cache_key(), manifest.engine_cache_key)
            self.assertFalse(loaded.int8_engine_built)
            self.assertTrue(loaded.built_on_target)


class TestEngineCacheKey(unittest.TestCase):
    BASE = dict(
        onnx_sha256="d" * 64,
        tensorrt_version="8.5.2.2",
        cuda_version="11.4",
        gpu_name="Orin NX",
        compute_capability="8.7",
        precision="fp16",
        input_profile="1x3x640x640",
        postprocess_profile="yolov9-c",
    )

    def test_key_is_stable(self) -> None:
        self.assertEqual(engine_cache_key(**self.BASE), engine_cache_key(**self.BASE))

    def test_every_axis_changes_the_key(self) -> None:
        baseline = engine_cache_key(**self.BASE)
        for field, replacement in (
            ("onnx_sha256", "e" * 64),
            ("tensorrt_version", "8.6.0.0"),
            ("cuda_version", "12.2"),
            ("gpu_name", "Xavier NX"),
            ("compute_capability", "7.2"),
            ("precision", "int8"),
            ("input_profile", "1x3x1280x1280"),
            ("postprocess_profile", "yolov9-e"),
        ):
            payload = dict(self.BASE)
            payload[field] = replacement
            self.assertNotEqual(
                baseline, engine_cache_key(**payload), "%s must invalidate the engine" % field
            )


class TestEngineStaleness(unittest.TestCase):
    def _manifest(self, engine_path: Path) -> EngineManifest:
        manifest = EngineManifest(
            engine_path=str(engine_path),
            engine_sha256=sha256_file(engine_path),
            onnx_sha256="f" * 64,
            tensorrt_version="8.5.2.2",
            cuda_version="11.4",
            gpu_name="Orin NX",
            compute_capability="8.7",
            engine_precision="fp16",
            input_profile="1x3x640x640",
            postprocess_profile="yolov9-c",
            built_on_target=True,
        )
        manifest.engine_cache_key = manifest.expected_cache_key()
        return manifest

    def _evaluate(self, manifest: EngineManifest, engine_path: Path, **overrides):
        payload = dict(
            observed_onnx_sha256="f" * 64,
            observed_tensorrt_version="8.5.2.2",
            observed_cuda_version="11.4",
            observed_gpu_name="Orin NX",
            observed_compute_capability="8.7",
            precision="fp16",
            input_profile="1x3x640x640",
            postprocess_profile="yolov9-c",
        )
        payload.update(overrides)
        return evaluate_engine_staleness(manifest, engine_path=engine_path, **payload)

    def test_matching_engine_is_reusable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = Path(directory) / "model.engine"
            engine.write_bytes(b"plan")
            verdict = self._evaluate(self._manifest(engine), engine)
            self.assertFalse(verdict.stale, verdict.reasons)
            self.assertEqual(verdict.observed_cache_key, verdict.manifest_cache_key)

    def test_changed_tensorrt_version_makes_it_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = Path(directory) / "model.engine"
            engine.write_bytes(b"plan")
            verdict = self._evaluate(
                self._manifest(engine), engine, observed_tensorrt_version="8.6.1.6"
            )
            self.assertTrue(verdict.stale)
            self.assertIn("tensorrt_version_mismatch", verdict.reasons)
            self.assertIn("engine_cache_key_mismatch", verdict.reasons)

    def test_tampered_engine_file_makes_it_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = Path(directory) / "model.engine"
            engine.write_bytes(b"plan")
            manifest = self._manifest(engine)
            engine.write_bytes(b"tampered")
            verdict = self._evaluate(manifest, engine)
            self.assertTrue(verdict.stale)
            self.assertIn("engine_sha256_mismatch", verdict.reasons)

    def test_missing_engine_file_makes_it_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = Path(directory) / "model.engine"
            engine.write_bytes(b"plan")
            manifest = self._manifest(engine)
            engine.unlink()
            verdict = self._evaluate(manifest, engine)
            self.assertTrue(verdict.stale)
            self.assertIn("engine_file_missing", verdict.reasons)

    def test_engine_not_built_on_target_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            engine = Path(directory) / "model.engine"
            engine.write_bytes(b"plan")
            manifest = self._manifest(engine)
            manifest.built_on_target = False
            verdict = self._evaluate(manifest, engine)
            self.assertTrue(verdict.stale)
            self.assertIn("engine_not_built_on_target", verdict.reasons)


if __name__ == "__main__":
    unittest.main()
