"""Phase 13D calibration-dataset contract tests.

Everything a Gate B claim rests on is checked here without CARLA: per-frame
identity and statistics, the deterministic split, duplicate and overlap
detection, coverage minimums, envelope derivation and the holdout false-reject
rate.
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
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from workers.core.int8_calibration_dataset import (  # noqa: E402
    DatasetError,
    FrameRecord,
    assign_splits,
    build_envelopes,
    build_manifest,
    dataset_sha256,
    describe_frame,
    evaluate_coverage,
    evaluate_disjointness,
    evaluate_holdout,
    image_statistics,
    list_frame_files,
    range_profile,
    record_statistics,
    verify_frame_files,
)

ROUTES = ["route_%02d" % index for index in range(5)]
WEATHERS = ["ClearNoon", "WetCloudyNoon", "HardRainNoon", "ClearSunset"]


def synthetic_records(
    *, frames_per_cell: int = 40, routes: List[str] = None, weathers: List[str] = None
) -> List[FrameRecord]:
    """A corpus shaped like a real capture, without touching the filesystem."""

    routes = routes or ROUTES
    weathers = weathers or WEATHERS
    records = []  # type: List[FrameRecord]
    counter = 0
    for route_index, route in enumerate(routes):
        for weather_index, weather in enumerate(weathers):
            for frame_index in range(frames_per_cell):
                counter += 1
                base = 0.30 + 0.02 * weather_index + 0.0005 * frame_index
                records.append(
                    FrameRecord(
                        frame_id="%s_%s_%05d" % (route, weather, frame_index),
                        route=route,
                        weather=weather,
                        path="/dev/null/%d.png" % counter,
                        relative_path="%s/%s/%05d.png" % (route, weather, frame_index),
                        sha256="%064x" % counter,
                        size_bytes=1000 + counter,
                        width=640,
                        height=360,
                        pixel_min=0.0,
                        pixel_max=1.0,
                        pixel_mean=round(base + 0.001 * route_index, 6),
                        channel_means=[
                            round(base + 0.001 * route_index, 6),
                            round(base + 0.01 + 0.001 * route_index, 6),
                            round(base + 0.02 + 0.001 * route_index, 6),
                        ],
                        channel_stds=[0.18, 0.19, 0.20],
                    )
                )
    return records


class TestImageStatistics(unittest.TestCase):
    def test_statistics_are_measured_in_the_normalized_domain(self) -> None:
        frame = np.zeros((8, 16, 3), dtype=np.uint8)
        frame[:, :, 0] = 51  # 0.2
        frame[:, :, 1] = 102  # 0.4
        frame[:, :, 2] = 153  # 0.6
        stats = image_statistics(frame)
        self.assertEqual(stats["width"], 16)
        self.assertEqual(stats["height"], 8)
        self.assertAlmostEqual(stats["channel_means"][0], 0.2, places=3)
        self.assertAlmostEqual(stats["channel_means"][2], 0.6, places=3)
        self.assertAlmostEqual(stats["pixel_mean"], 0.4, places=3)
        self.assertAlmostEqual(stats["pixel_min"], 0.2, places=3)
        self.assertAlmostEqual(stats["pixel_max"], 0.6, places=3)

    def test_pixel_mean_equals_the_mean_of_the_channel_means(self) -> None:
        rng = np.random.RandomState(7)
        frame = rng.randint(0, 256, size=(12, 20, 3)).astype(np.uint8)
        stats = image_statistics(frame)
        self.assertAlmostEqual(
            stats["pixel_mean"], sum(stats["channel_means"]) / 3.0, places=5
        )

    def test_a_non_bgr_frame_is_rejected(self) -> None:
        with self.assertRaises(DatasetError):
            image_statistics(np.zeros((8, 8), dtype=np.uint8))


class TestSplitAssignment(unittest.TestCase):
    def test_split_is_deterministic_and_per_cell(self) -> None:
        first = assign_splits(synthetic_records(), holdout_stride=5)
        second = assign_splits(synthetic_records(), holdout_stride=5)
        self.assertEqual(
            [(item.frame_id, item.split) for item in first],
            [(item.frame_id, item.split) for item in second],
        )
        for route in ROUTES:
            for weather in WEATHERS:
                cell = [
                    item for item in first if item.route == route and item.weather == weather
                ]
                holdout = [item for item in cell if item.split == "holdout"]
                self.assertEqual(len(holdout), 8, "%s/%s" % (route, weather))

    def test_split_sizes_meet_the_phase_minimums(self) -> None:
        manifest = build_manifest(assign_splits(synthetic_records(), holdout_stride=5))
        self.assertGreaterEqual(manifest.calibration_count, 512)
        self.assertGreaterEqual(manifest.holdout_count, 128)
        self.assertEqual(manifest.frame_count, 800)

    def test_a_degenerate_stride_is_rejected(self) -> None:
        with self.assertRaises(DatasetError):
            assign_splits(synthetic_records(frames_per_cell=2), holdout_stride=1)

    def test_dataset_sha_changes_when_any_frame_changes(self) -> None:
        records = assign_splits(synthetic_records(), holdout_stride=5)
        before = dataset_sha256(records)
        records[0].sha256 = "f" * 64
        self.assertNotEqual(before, dataset_sha256(records))


class TestCoverageAndDisjointness(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = build_manifest(assign_splits(synthetic_records(), holdout_stride=5))

    def test_full_corpus_passes_coverage(self) -> None:
        coverage = evaluate_coverage(self.manifest)
        self.assertTrue(coverage["coverage_passed"], coverage["blockers"])
        self.assertEqual(coverage["route_count"], 5)
        self.assertEqual(coverage["weather_profile_count"], 4)
        self.assertEqual(coverage["route_weather_cell_count"], 20)

    def test_missing_weather_profile_blocks_coverage(self) -> None:
        manifest = build_manifest(
            assign_splits(synthetic_records(weathers=WEATHERS[:3]), holdout_stride=5)
        )
        coverage = evaluate_coverage(manifest)
        self.assertFalse(coverage["coverage_passed"])
        self.assertIn("dataset_weather_coverage_insufficient", coverage["blockers"])

    def test_missing_route_blocks_coverage(self) -> None:
        manifest = build_manifest(
            assign_splits(synthetic_records(routes=ROUTES[:4]), holdout_stride=5)
        )
        coverage = evaluate_coverage(manifest)
        self.assertFalse(coverage["coverage_passed"])
        self.assertIn("dataset_route_coverage_insufficient", coverage["blockers"])

    def test_too_few_calibration_frames_blocks_coverage(self) -> None:
        manifest = build_manifest(
            assign_splits(synthetic_records(frames_per_cell=10), holdout_stride=5)
        )
        coverage = evaluate_coverage(manifest)
        self.assertFalse(coverage["coverage_passed"])
        self.assertIn("calibration_frame_count_insufficient", coverage["blockers"])

    def test_clean_corpus_has_no_duplicates_and_no_overlap(self) -> None:
        verdict = evaluate_disjointness(self.manifest)
        self.assertTrue(verdict["disjointness_passed"], verdict["blockers"])
        self.assertEqual(verdict["duplicate_sha256_count"], 0)
        self.assertEqual(verdict["split_overlap_frame_id_count"], 0)
        self.assertEqual(verdict["split_overlap_sha256_count"], 0)

    def test_duplicate_content_is_detected(self) -> None:
        records = assign_splits(synthetic_records(), holdout_stride=5)
        records[10].sha256 = records[0].sha256
        manifest = build_manifest(records)
        verdict = evaluate_disjointness(manifest)
        self.assertFalse(verdict["disjointness_passed"])
        self.assertIn("dataset_duplicate_frames", verdict["blockers"])
        self.assertEqual(verdict["duplicate_sha256_count"], 1)

    def test_split_overlap_is_detected(self) -> None:
        records = assign_splits(synthetic_records(), holdout_stride=5)
        holdout = next(item for item in records if item.split == "holdout")
        calibration = next(item for item in records if item.split == "calibration")
        holdout.frame_id = calibration.frame_id
        verdict = evaluate_disjointness(build_manifest(records))
        self.assertFalse(verdict["disjointness_passed"])
        self.assertIn("dataset_split_overlap", verdict["blockers"])

    def test_unassigned_frames_are_detected(self) -> None:
        records = assign_splits(synthetic_records(), holdout_stride=5)
        records[3].split = ""
        verdict = evaluate_disjointness(build_manifest(records))
        self.assertFalse(verdict["disjointness_passed"])
        self.assertIn("dataset_split_unassigned", verdict["blockers"])


class TestEnvelopes(unittest.TestCase):
    def setUp(self) -> None:
        self.records = assign_splits(synthetic_records(), holdout_stride=5)
        self.manifest = build_manifest(self.records)
        self.envelopes = build_envelopes(
            self.manifest.records(), dataset_sha256_value=self.manifest.dataset_sha256
        )

    def test_envelopes_are_derived_from_the_calibration_split_only(self) -> None:
        self.assertEqual(self.envelopes.source_split, "calibration")
        self.assertEqual(self.envelopes.source_frame_count, self.manifest.calibration_count)
        self.assertEqual(len(self.envelopes.channel_mean_bounds), 3)
        for low, high in self.envelopes.channel_mean_bounds:
            self.assertLess(low, high)

    def test_holdout_false_reject_rate_is_within_the_bound(self) -> None:
        verdict = evaluate_holdout(self.envelopes, self.manifest.split("holdout"))
        self.assertTrue(verdict["holdout_passed"], verdict)
        self.assertLessEqual(verdict["holdout_false_reject_rate"], 0.01)
        self.assertGreaterEqual(verdict["holdout_evaluated_count"], 128)

    def test_a_shifted_frame_is_rejected_by_the_envelope(self) -> None:
        shifted = FrameRecord(
            frame_id="shifted",
            route="route_00",
            weather="ClearNoon",
            split="holdout",
            channel_means=[0.95, 0.95, 0.95],
            channel_stds=[0.18, 0.19, 0.20],
            pixel_min=0.0,
            pixel_max=1.0,
            pixel_mean=0.95,
        )
        violations = self.envelopes.violations(record_statistics(shifted))
        self.assertTrue(violations)
        self.assertTrue(any(item.startswith("channel_mean_out_of_envelope") for item in violations))

    def test_a_constant_statistic_still_produces_a_usable_envelope(self) -> None:
        records = assign_splits(synthetic_records(frames_per_cell=40), holdout_stride=5)
        for record in records:
            record.channel_stds = [0.2, 0.2, 0.2]
        envelopes = build_envelopes(records)
        low, high = envelopes.channel_std_bounds[0]
        self.assertLess(low, 0.2)
        self.assertGreater(high, 0.2)
        inside = next(item for item in records if item.split == "calibration")
        self.assertEqual(envelopes.violations(record_statistics(inside)), [])

    def test_absent_statistics_are_a_violation_not_a_pass(self) -> None:
        records = assign_splits(synthetic_records(), holdout_stride=5)
        envelopes = build_envelopes(records)
        violations = envelopes.violations({"channel_means": [], "channel_stds": []})
        self.assertIn("channel_mean_missing:0", violations)
        self.assertIn("pixel_mean_missing", violations)

    def test_an_empty_calibration_split_is_an_error(self) -> None:
        records = assign_splits(synthetic_records(frames_per_cell=40), holdout_stride=5)
        for record in records:
            record.split = "holdout"
        with self.assertRaises(DatasetError):
            build_envelopes(records)

    def test_an_empty_holdout_split_never_reads_as_a_pass(self) -> None:
        verdict = evaluate_holdout(self.envelopes, [])
        self.assertFalse(verdict["holdout_passed"])
        self.assertIn("holdout_frame_count_insufficient", verdict["blockers"])


class TestRangeProfileAndFiles(unittest.TestCase):
    def test_range_profile_reports_both_splits(self) -> None:
        records = assign_splits(synthetic_records(), holdout_stride=5)
        profile = range_profile(records)
        self.assertEqual(profile["all"]["frame_count"], 800)
        self.assertGreater(profile["calibration"]["frame_count"], 0)
        self.assertGreater(profile["holdout"]["frame_count"], 0)
        self.assertFalse(profile["real_world_representative"])
        self.assertEqual(profile["data_source"], "controlled_carla_simulation")

    def test_describe_frame_and_verify_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cell = root / "route_00" / "ClearNoon"
            cell.mkdir(parents=True)
            target = cell / "frame_00000.png"
            target.write_bytes(b"not really a png, but hashable")
            record = describe_frame(
                target,
                frame_id="route_00_ClearNoon_00000",
                route="route_00",
                weather="ClearNoon",
                statistics={
                    "width": 640,
                    "height": 360,
                    "pixel_min": 0.0,
                    "pixel_max": 1.0,
                    "pixel_mean": 0.4,
                    "channel_means": [0.4, 0.4, 0.4],
                    "channel_stds": [0.2, 0.2, 0.2],
                },
                dataset_root=root,
            )
            self.assertEqual(record.relative_path, "route_00/ClearNoon/frame_00000.png")
            self.assertEqual(len(record.sha256), 64)
            record.split = "calibration"
            verdict = verify_frame_files([record])
            self.assertTrue(verdict["frame_files_verified"], verdict)

            target.write_bytes(b"tampered")
            verdict = verify_frame_files([record])
            self.assertFalse(verdict["frame_files_verified"])
            self.assertIn("dataset_frame_sha256_mismatch", verdict["blockers"])

    def test_missing_frame_is_reported(self) -> None:
        record = FrameRecord(frame_id="gone", path="/definitely/not/here.png", sha256="0" * 64)
        verdict = verify_frame_files([record])
        self.assertFalse(verdict["frame_files_verified"])
        self.assertIn("dataset_frame_missing", verdict["blockers"])

    def test_list_frame_files_is_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("b.png", "a.png", "c.jpg", "notes.txt"):
                (root / name).write_bytes(b"x")
            listed = [item.name for item in list_frame_files(root)]
            self.assertEqual(listed, ["a.png", "b.png", "c.jpg"])


if __name__ == "__main__":
    unittest.main()
