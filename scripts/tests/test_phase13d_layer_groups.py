"""Phase 13D-MP-RECOVERY semantic layer group tests.

The groups decide which subgraph a candidate keeps in FP16, so a silent
mismatch between a prefix and the real graph would make a whole sensitivity
sweep meaningless. These tests pin the prefix semantics against layer names
taken from the actual parsed network.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import List

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from workers.core.int8_layer_groups import (  # noqa: E402
    GROUP_IDS,
    LAYER_GROUPS,
    LayerGroupError,
    assign_group,
    group_by_id,
    group_membership,
    group_table,
    parse_group_spec,
    prefixes_for,
    summarize_groups,
)

#: Real names observed in the parsed TensorRT network for this ONNX.
REAL_NAMES = [
    "/model.0/conv/Conv",
    "/model.1/conv/Conv",
    "/model.2/cv1/conv/Conv",
    "/model.2/cv3/0/m/0/cv1/conv/Conv",
    "/model.3/cv1/conv/Conv",
    "/model.4/cv2/1/conv/Conv",
    "/model.5/cv2/conv/Conv",
    "/model.6/cv2/0/cv2/conv/Conv",
    "/model.7/cv1/conv/Conv",
    "/model.8/cv4/conv/Conv",
    "/model.9/cv1/conv/Conv",
    "/model.10/Resize",
    "/model.11/Concat",
    "/model.12/cv1/conv/Conv",
    "/model.13/Resize",
    "/model.14/Concat",
    "/model.15/cv4/conv/Conv",
    "/model.16/cv1/conv/Conv",
    "/model.17/Concat",
    "/model.18/cv1/conv/Conv",
    "/model.19/cv2/conv/Conv",
    "/model.20/Concat",
    "/model.21/cv4/conv/Conv",
    "/model.22/cv3.0/cv3.0.2/Conv",
    "/model.22/Sigmoid",
    "(Unnamed Layer* 18) [Constant]",
    "(Unnamed Layer* 1235) [Constant]",
]


class TestGroupTable(unittest.TestCase):
    def test_seven_groups_cover_the_required_regions(self) -> None:
        names = [item[1] for item in LAYER_GROUPS]
        self.assertEqual(len(LAYER_GROUPS), 7)
        self.assertEqual(GROUP_IDS, ("G1", "G2", "G3", "G4", "G5", "G6", "G7"))
        for expected in ("early_backbone", "mid_backbone", "late_backbone_sppelan",
                         "neck_topdown_low_res", "neck_topdown_high_res",
                         "neck_bottomup_pan", "detect_head"):
            self.assertIn(expected, names)

    def test_every_stage_from_0_to_22_belongs_to_exactly_one_group(self) -> None:
        seen = {}
        for group_id, _name, prefixes in LAYER_GROUPS:
            for prefix in prefixes:
                self.assertTrue(prefix.startswith("/model."))
                self.assertTrue(prefix.endswith("/"))
                self.assertNotIn(prefix, seen, "%s claimed twice" % prefix)
                seen[prefix] = group_id
        self.assertEqual(len(seen), 23)
        for stage in range(23):
            self.assertIn("/model.%d/" % stage, seen)

    def test_group_table_is_serialisable(self) -> None:
        table = group_table()
        self.assertEqual(len(table), 7)
        self.assertEqual(sorted(table[0]), ["group_id", "group_name", "prefixes"])


class TestAssignment(unittest.TestCase):
    def test_real_names_land_in_the_expected_groups(self) -> None:
        expected = {
            "/model.0/conv/Conv": "G1",
            "/model.3/cv1/conv/Conv": "G1",
            "/model.4/cv2/1/conv/Conv": "G2",
            "/model.7/cv1/conv/Conv": "G2",
            "/model.8/cv4/conv/Conv": "G3",
            "/model.9/cv1/conv/Conv": "G3",
            "/model.10/Resize": "G4",
            "/model.12/cv1/conv/Conv": "G4",
            "/model.13/Resize": "G5",
            "/model.15/cv4/conv/Conv": "G5",
            "/model.16/cv1/conv/Conv": "G6",
            "/model.21/cv4/conv/Conv": "G6",
            "/model.22/Sigmoid": "G7",
        }
        for name, group_id in expected.items():
            self.assertEqual(assign_group(name), group_id, name)

    def test_stage_2_prefix_does_not_swallow_stage_20_or_22(self) -> None:
        self.assertEqual(assign_group("/model.2/cv1/conv/Conv"), "G1")
        self.assertEqual(assign_group("/model.20/Concat"), "G6")
        self.assertEqual(assign_group("/model.22/Sigmoid"), "G7")

    def test_stage_1_prefix_does_not_swallow_the_teens(self) -> None:
        self.assertEqual(assign_group("/model.1/conv/Conv"), "G1")
        self.assertEqual(assign_group("/model.12/cv1/conv/Conv"), "G4")
        self.assertEqual(assign_group("/model.18/cv1/conv/Conv"), "G6")

    def test_graph_plumbing_belongs_to_no_group(self) -> None:
        self.assertIsNone(assign_group("(Unnamed Layer* 18) [Constant]"))
        self.assertIsNone(assign_group("(Unnamed Layer* 1235) [Constant]"))


class TestSummaries(unittest.TestCase):
    def test_summary_counts_match_the_real_name_sample(self) -> None:
        summary = summarize_groups(REAL_NAMES)
        counts = summary["group_matched_counts"]
        self.assertEqual(summary["layer_count"], len(REAL_NAMES))
        self.assertEqual(summary["ungrouped_layer_count"], 2)
        self.assertEqual(counts["G1"], 5)
        self.assertEqual(counts["G2"], 4)
        self.assertEqual(counts["G3"], 2)
        self.assertEqual(counts["G4"], 3)
        self.assertEqual(counts["G5"], 3)
        self.assertEqual(counts["G6"], 6)
        self.assertEqual(counts["G7"], 2)
        self.assertEqual(sum(counts.values()) + summary["ungrouped_layer_count"], len(REAL_NAMES))

    def test_membership_reports_exact_names(self) -> None:
        membership = group_membership(REAL_NAMES, ["G3", "G7"])
        self.assertEqual(membership["forced_fp16_group_ids"], ["G3", "G7"])
        self.assertEqual(
            membership["forced_fp16_group_names"], ["late_backbone_sppelan", "detect_head"]
        )
        self.assertEqual(membership["forced_fp16_matched_layer_count"], 4)
        self.assertIn("/model.8/cv4/conv/Conv", membership["forced_fp16_matched_layer_names"])
        self.assertIn("/model.22/Sigmoid", membership["forced_fp16_matched_layer_names"])
        self.assertNotIn("/model.0/conv/Conv", membership["forced_fp16_matched_layer_names"])

    def test_empty_membership_is_the_unconstrained_baseline(self) -> None:
        membership = group_membership(REAL_NAMES, [])
        self.assertEqual(membership["forced_fp16_matched_layer_count"], 0)
        self.assertEqual(membership["forced_fp16_prefixes"], [])


class TestSpecParsing(unittest.TestCase):
    def test_spec_is_parsed_and_deduplicated(self) -> None:
        self.assertEqual(parse_group_spec("G1,G3,G1"), ["G1", "G3"])
        self.assertEqual(parse_group_spec(" g2 ; g5 "), ["G2", "G5"])

    def test_empty_spec_means_baseline(self) -> None:
        self.assertEqual(parse_group_spec(""), [])
        self.assertEqual(parse_group_spec(None), [])

    def test_an_unknown_group_is_rejected_not_ignored(self) -> None:
        with self.assertRaises(LayerGroupError):
            parse_group_spec("G1,G9")
        with self.assertRaises(LayerGroupError):
            group_by_id("nope")

    def test_prefixes_for_is_ordered_and_deduplicated(self) -> None:
        prefixes = prefixes_for(["G3", "G3", "G7"])
        self.assertEqual(prefixes, ["/model.8/", "/model.9/", "/model.22/"])


if __name__ == "__main__":
    unittest.main()
