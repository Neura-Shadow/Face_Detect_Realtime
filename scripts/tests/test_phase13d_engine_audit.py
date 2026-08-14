"""Phase 13D INT8 engine-audit contract tests.

The audit is what turns "we set the INT8 builder flag" into "TensorRT actually
assigned INT8 to these layers". The parsing half is TensorRT-free on purpose so
that contract can be proved on the simulation PC, including the rule that
``all_layers_int8`` may never be true while any layer's precision is unknown.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from workers.core.int8_engine_audit import (  # noqa: E402
    FP16,
    FP32,
    INT8,
    UNKNOWN,
    EngineAuditError,
    audit_engine,
    extract_layer_precision,
    normalize_precision,
    summarize_layer_precisions,
    verify_output_contract,
)


def layer(name: str, precision: str, layer_type: str = "CaskConvolution") -> Dict[str, Any]:
    return {"Name": name, "LayerType": layer_type, "Precision": precision}


def tensor_format_layer(name: str, datatype: str) -> Dict[str, Any]:
    """A layer whose precision is only visible through its tensor formats."""

    return {
        "Name": name,
        "LayerType": "CaskConvolution",
        "Inputs": [{"Name": "in", "Format/Datatype": datatype}],
        "Outputs": [{"Name": "out", "Format/Datatype": datatype}],
    }


class TestPrecisionNormalization(unittest.TestCase):
    def test_known_precisions_are_mapped(self) -> None:
        self.assertEqual(normalize_precision("Int8"), INT8)
        self.assertEqual(normalize_precision("INT8"), INT8)
        self.assertEqual(normalize_precision("Half"), FP16)
        self.assertEqual(normalize_precision("FP16"), FP16)
        self.assertEqual(normalize_precision("Float"), FP32)
        self.assertEqual(normalize_precision("FP32"), FP32)

    def test_shape_plumbing_is_not_a_compute_precision_decision(self) -> None:
        self.assertEqual(normalize_precision("Int32"), FP32)
        self.assertEqual(normalize_precision("Bool"), FP32)

    def test_absent_or_unrecognised_precision_stays_unknown(self) -> None:
        self.assertEqual(normalize_precision(None), UNKNOWN)
        self.assertEqual(normalize_precision(""), UNKNOWN)
        self.assertEqual(normalize_precision("something else"), UNKNOWN)


class TestLayerExtraction(unittest.TestCase):
    def test_explicit_precision_field_wins(self) -> None:
        parsed = extract_layer_precision(layer("Conv_0", "Int8"))
        self.assertEqual(parsed["precision"], INT8)
        self.assertEqual(parsed["precision_source"], "Precision")
        self.assertEqual(parsed["name"], "Conv_0")
        self.assertEqual(parsed["layer_type"], "CaskConvolution")

    def test_tensor_format_is_used_when_no_precision_field_exists(self) -> None:
        parsed = extract_layer_precision(
            tensor_format_layer("Conv_1", "Int8 format for a tensor of shape (1,64,320,320)")
        )
        self.assertEqual(parsed["precision"], INT8)
        self.assertEqual(parsed["precision_source"], "tensor_format")

    def test_a_layer_with_no_usable_signal_is_unknown_not_guessed(self) -> None:
        parsed = extract_layer_precision({"Name": "Mystery", "LayerType": "PluginV2"})
        self.assertEqual(parsed["precision"], UNKNOWN)
        self.assertEqual(parsed["precision_source"], "absent")

    def test_an_unparsable_entry_is_unknown(self) -> None:
        parsed = extract_layer_precision([])  # type: ignore[arg-type]
        self.assertEqual(parsed["precision"], UNKNOWN)
        self.assertEqual(parsed["precision_source"], "unparsable")


class TestSummary(unittest.TestCase):
    def test_mixed_precision_engine_counts_correctly(self) -> None:
        layers = (
            [layer("Conv_%d" % index, "Int8") for index in range(7)]
            + [layer("Conv_fp16_%d" % index, "Half") for index in range(2)]
            + [layer("Reformat", "Float", layer_type="Reformat")]
        )
        summary = summarize_layer_precisions(layers)
        self.assertEqual(summary["engine_layer_count"], 10)
        self.assertEqual(summary["int8_layer_count"], 7)
        self.assertEqual(summary["fp16_layer_count"], 2)
        self.assertEqual(summary["fp32_layer_count"], 1)
        self.assertEqual(summary["precision_fallback_layer_count"], 3)
        self.assertTrue(summary["int8_layers_observed"])
        self.assertFalse(summary["all_layers_int8"])
        self.assertAlmostEqual(summary["int8_layer_ratio"], 0.7)

    def test_all_int8_is_only_claimed_when_every_layer_reported_int8(self) -> None:
        summary = summarize_layer_precisions([layer("Conv_%d" % index, "Int8") for index in range(4)])
        self.assertTrue(summary["all_layers_int8"])
        self.assertEqual(summary["precision_fallback_layer_count"], 0)

    def test_one_unknown_layer_forbids_the_all_int8_claim(self) -> None:
        layers = [layer("Conv_%d" % index, "Int8") for index in range(4)]
        layers.append({"Name": "Mystery", "LayerType": "PluginV2"})
        summary = summarize_layer_precisions(layers)
        self.assertEqual(summary["unknown_precision_layer_count"], 1)
        self.assertFalse(summary["all_layers_int8"])
        self.assertFalse(summary["all_layers_int8_claimed"])
        self.assertTrue(summary["int8_layers_observed"])

    def test_an_engine_with_no_int8_layers_is_visible(self) -> None:
        summary = summarize_layer_precisions([layer("Conv_%d" % index, "Half") for index in range(3)])
        self.assertEqual(summary["int8_layer_count"], 0)
        self.assertFalse(summary["int8_layers_observed"])
        self.assertFalse(summary["all_layers_int8"])

    def test_an_empty_engine_never_reads_as_all_int8(self) -> None:
        summary = summarize_layer_precisions([])
        self.assertEqual(summary["engine_layer_count"], 0)
        self.assertFalse(summary["all_layers_int8"])
        self.assertIsNone(summary["int8_layer_ratio"])

    def test_fallback_layers_are_named(self) -> None:
        layers = [layer("Conv_0", "Int8"), layer("Head", "Half")]
        summary = summarize_layer_precisions(layers)
        self.assertEqual(
            summary["precision_fallback_layers"],
            [{"name": "Head", "layer_type": "CaskConvolution", "precision": FP16}],
        )


class TestOutputContract(unittest.TestCase):
    def _bindings(self, **overrides: Any) -> Dict[str, Any]:
        payload = {
            "engine_input_bindings": [
                {"name": "images", "shape": [1, 3, 640, 640], "dtype": "FLOAT"}
            ],
            "engine_output_bindings": [
                {"name": "output0", "shape": [1, 84, 8400], "dtype": "FLOAT"}
            ],
        }
        payload.update(overrides)
        return payload

    def test_matching_contract_passes(self) -> None:
        verdict = verify_output_contract(
            self._bindings(),
            expected_input_name="images",
            expected_input_shape=[1, 3, 640, 640],
            expected_output_names=["output0"],
            expected_output_shapes=[[1, 84, 8400]],
        )
        self.assertTrue(verdict["output_contract_verified"], verdict)

    def test_a_renamed_input_binding_fails(self) -> None:
        verdict = verify_output_contract(
            self._bindings(),
            expected_input_name="input",
            expected_input_shape=[1, 3, 640, 640],
        )
        self.assertFalse(verdict["output_contract_verified"])
        self.assertIn("input_binding_name_mismatch", verdict["output_contract_failures"])

    def test_a_reshaped_input_binding_fails(self) -> None:
        verdict = verify_output_contract(
            self._bindings(),
            expected_input_name="images",
            expected_input_shape=[1, 3, 512, 512],
        )
        self.assertIn("input_binding_shape_mismatch", verdict["output_contract_failures"])

    def test_extra_outputs_fail_the_contract(self) -> None:
        bindings = self._bindings(
            engine_output_bindings=[
                {"name": "output0", "shape": [1, 84, 8400]},
                {"name": "feature_map_0", "shape": [1, 144, 80, 80]},
            ]
        )
        verdict = verify_output_contract(
            bindings,
            expected_input_name="images",
            expected_input_shape=[1, 3, 640, 640],
            expected_output_names=["output0"],
        )
        self.assertFalse(verdict["output_contract_verified"])
        self.assertIn("output_binding_name_mismatch", verdict["output_contract_failures"])

    def test_missing_outputs_fail_the_contract(self) -> None:
        verdict = verify_output_contract(
            self._bindings(engine_output_bindings=[]),
            expected_input_name="images",
            expected_input_shape=[1, 3, 640, 640],
        )
        self.assertIn("output_binding_missing", verdict["output_contract_failures"])

    def test_two_input_bindings_fail_the_contract(self) -> None:
        bindings = self._bindings(
            engine_input_bindings=[
                {"name": "images", "shape": [1, 3, 640, 640]},
                {"name": "extra", "shape": [1, 1]},
            ]
        )
        verdict = verify_output_contract(
            bindings, expected_input_name="images", expected_input_shape=[1, 3, 640, 640]
        )
        self.assertIn("input_binding_count_mismatch", verdict["output_contract_failures"])


class TestAuditEntryPoint(unittest.TestCase):
    def test_a_missing_engine_is_classified_not_swallowed(self) -> None:
        with self.assertRaises(EngineAuditError) as caught:
            audit_engine("definitely-not-an-engine.plan")
        self.assertIn(
            caught.exception.classification, ("engine_missing", "tensorrt_builder_unavailable")
        )


if __name__ == "__main__":
    unittest.main()
