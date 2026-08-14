"""Phase 13D offline activation-proxy tests.

The proxy is the only activation evidence this phase has, so its arithmetic has
to be exact and its boundary has to be explicit: it measures the **source**
model offline and never claims to observe TensorRT's internal activations.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from workers.core.int8_activation_proxy import (  # noqa: E402
    ACTIVATION_PROXY_BACKEND,
    MIN_PROXY_LAYERS,
    ActivationProxyCollector,
    ActivationProxyError,
    LayerActivationAccumulator,
    evaluate_proxy_report,
    summarize_proxy_layers,
)


class TestAccumulatorArithmetic(unittest.TestCase):
    def test_streaming_aggregates_match_numpy(self) -> None:
        rng = np.random.RandomState(11)
        chunks = [rng.normal(0.0, 1.5, size=512).astype(np.float32) for _ in range(6)]
        accumulator = LayerActivationAccumulator("conv", "Conv2d", histogram_bins=1024,
                                                 histogram_max=16.0)
        for chunk in chunks:
            accumulator.update(chunk)
        summary = accumulator.summary()
        combined = np.concatenate(chunks).astype(np.float64)
        self.assertEqual(summary.sample_count, combined.size)
        self.assertEqual(summary.observation_count, 6)
        self.assertAlmostEqual(summary.mean, round(float(combined.mean()), 6), places=4)
        self.assertAlmostEqual(summary.std, round(float(combined.std()), 6), places=4)
        self.assertAlmostEqual(summary.minimum, round(float(combined.min()), 6), places=5)
        self.assertAlmostEqual(summary.maximum, round(float(combined.max()), 6), places=5)
        self.assertAlmostEqual(summary.absmax, round(float(np.abs(combined).max()), 6), places=5)

    def test_absolute_quantiles_are_close_to_the_true_ones(self) -> None:
        values = np.linspace(-1.0, 1.0, 20001, dtype=np.float32)
        accumulator = LayerActivationAccumulator("uniform", histogram_bins=2000, histogram_max=2.0)
        accumulator.update(values)
        summary = accumulator.summary()
        magnitudes = np.abs(values.astype(np.float64))
        self.assertAlmostEqual(summary.abs_p99, float(np.percentile(magnitudes, 99.0)), delta=0.01)
        self.assertAlmostEqual(summary.abs_p999, float(np.percentile(magnitudes, 99.9)), delta=0.01)

    def test_zero_fraction_is_measured(self) -> None:
        accumulator = LayerActivationAccumulator("relu")
        accumulator.update(np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32))
        self.assertAlmostEqual(accumulator.summary().zero_fraction, 0.75)

    def test_values_beyond_the_histogram_cap_are_counted_not_hidden(self) -> None:
        accumulator = LayerActivationAccumulator("wide", histogram_bins=64, histogram_max=1.0)
        accumulator.update(np.array([0.1, 0.2, 5.0], dtype=np.float32))
        summary = accumulator.summary()
        self.assertEqual(summary.histogram_overflow_count, 1)
        self.assertAlmostEqual(summary.histogram_overflow_fraction, 1.0 / 3.0, places=6)
        self.assertAlmostEqual(summary.absmax, 5.0, places=5)

    def test_nonfinite_values_are_excluded_and_counted(self) -> None:
        accumulator = LayerActivationAccumulator("noisy")
        accumulator.update(np.array([1.0, np.nan, 2.0, np.inf], dtype=np.float32))
        summary = accumulator.summary()
        self.assertEqual(summary.nonfinite_count, 2)
        self.assertEqual(summary.sample_count, 2)
        self.assertAlmostEqual(summary.mean, 1.5, places=6)

    def test_int8_step_and_outlier_ratio_are_derived(self) -> None:
        accumulator = LayerActivationAccumulator("outliers", histogram_bins=4096,
                                                 histogram_max=200.0)
        accumulator.update(np.concatenate([np.ones(9999, dtype=np.float32), np.array([100.0])]))
        summary = accumulator.summary()
        self.assertAlmostEqual(summary.absmax, 100.0, places=5)
        self.assertAlmostEqual(summary.int8_step_at_absmax, 100.0 / 127.0, places=6)
        self.assertGreater(summary.outlier_ratio_absmax_over_p999, 1.0)

    def test_a_layer_with_no_activations_is_an_error_not_a_zero(self) -> None:
        with self.assertRaises(ActivationProxyError) as caught:
            LayerActivationAccumulator("empty").summary()
        self.assertEqual(caught.exception.classification, "activation_proxy_empty")


class TestCollectorReport(unittest.TestCase):
    def _collector(self, layers: int, frames: int = 4) -> ActivationProxyCollector:
        collector = ActivationProxyCollector(histogram_bins=256, histogram_max=8.0)
        rng = np.random.RandomState(3)
        for frame in range(frames):
            for index in range(layers):
                collector.observe(
                    "model.%d.conv" % index,
                    rng.normal(0.0, 0.5 + 0.1 * index, size=128).astype(np.float32),
                    layer_type="Conv2d",
                )
            collector.mark_frame()
        return collector

    def test_a_report_over_enough_layers_passes(self) -> None:
        report = self._collector(MIN_PROXY_LAYERS).report()
        self.assertTrue(report["activation_proxy_passed"], report["blockers"])
        self.assertEqual(report["activation_proxy_layer_count"], MIN_PROXY_LAYERS)
        self.assertEqual(report["activation_proxy_frames_observed"], 4)
        self.assertEqual(report["activation_proxy_backend"], ACTIVATION_PROXY_BACKEND)

    def test_too_few_layers_blocks_the_report(self) -> None:
        report = self._collector(MIN_PROXY_LAYERS - 1).report()
        self.assertFalse(report["activation_proxy_passed"])
        self.assertIn("activation_proxy_layer_count_insufficient", report["blockers"])

    def test_no_frames_blocks_the_report(self) -> None:
        collector = ActivationProxyCollector()
        for index in range(MIN_PROXY_LAYERS):
            collector.observe("layer_%d" % index, np.ones(8, dtype=np.float32))
        report = collector.report()
        self.assertFalse(report["activation_proxy_passed"])
        self.assertIn("activation_proxy_frames_missing", report["blockers"])

    def test_the_report_declares_its_own_boundary(self) -> None:
        report = self._collector(MIN_PROXY_LAYERS).report()
        self.assertFalse(report["runtime_tensorrt_internal_activations_observed"])
        self.assertFalse(report["internal_tensor_monitoring_claimed"])
        self.assertFalse(report["activation_range_checked_at_runtime"])
        self.assertFalse(report["qat_verified"])
        self.assertTrue(report["quantization_saturation_measured_on_source_model_only"])

    def test_layers_keep_their_observation_order(self) -> None:
        collector = self._collector(3, frames=2)
        names = [item.name for item in collector.summaries()]
        self.assertEqual(names, ["model.0.conv", "model.1.conv", "model.2.conv"])

    def test_aggregate_summary_names_the_widest_layer(self) -> None:
        collector = ActivationProxyCollector(histogram_bins=2048, histogram_max=200.0)
        collector.observe("narrow", np.ones(4096, dtype=np.float32))
        collector.observe(
            "wide", np.concatenate([np.ones(4095, dtype=np.float32), np.array([150.0])])
        )
        collector.mark_frame()
        aggregate = summarize_proxy_layers(collector.summaries())
        self.assertEqual(aggregate["activation_proxy_layer_count"], 2)
        self.assertEqual(aggregate["activation_proxy_widest_layer"], "wide")
        self.assertAlmostEqual(aggregate["activation_proxy_absmax_max"], 150.0, places=4)


class TestStoredReportValidation(unittest.TestCase):
    def _report(self, layers: int) -> Dict[str, Any]:
        return {
            "activation_proxy_layers": [
                {"name": "l%d" % index, "absmax": 3.0, "abs_p999": 2.0, "std": 0.5}
                for index in range(layers)
            ],
            "runtime_tensorrt_internal_activations_observed": False,
        }

    def test_a_valid_stored_report_verifies(self) -> None:
        verdict = evaluate_proxy_report(self._report(MIN_PROXY_LAYERS))
        self.assertTrue(verdict["activation_proxy_verified"], verdict["blockers"])

    def test_too_few_stored_layers_blocks(self) -> None:
        verdict = evaluate_proxy_report(self._report(4))
        self.assertFalse(verdict["activation_proxy_verified"])
        self.assertIn("activation_proxy_layer_count_insufficient", verdict["blockers"])

    def test_a_report_claiming_runtime_observation_is_rejected(self) -> None:
        report = self._report(MIN_PROXY_LAYERS)
        report["runtime_tensorrt_internal_activations_observed"] = True
        verdict = evaluate_proxy_report(report)
        self.assertFalse(verdict["activation_proxy_verified"])
        self.assertIn("activation_proxy_claims_runtime_observation", verdict["blockers"])

    def test_a_nonfinite_stored_statistic_is_rejected(self) -> None:
        report = self._report(MIN_PROXY_LAYERS)
        report["activation_proxy_layers"][0]["absmax"] = float("inf")
        verdict = evaluate_proxy_report(report)
        self.assertFalse(verdict["activation_proxy_verified"])
        self.assertIn("activation_proxy_nonfinite", verdict["blockers"])


if __name__ == "__main__":
    unittest.main()
