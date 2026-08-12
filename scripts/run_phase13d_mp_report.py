"""Phase 13D-MP-RECOVERY — aggregate the candidate sweep and decide.

Reads every candidate's ``candidate_result.json``, builds the comparison table,
ranks the groups by how much class-branch signal each one recovers, and applies
the recovery criteria. It selects nothing on its own authority: a candidate is
only selectable if it already met the unmodified Phase 13D parity thresholds.

If no bounded candidate qualifies, the report says so and the phase freezes.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from run_phase13d_checks import Phase13DEvidence, new_run_id, utc_now_iso  # noqa: E402
from run_phase13d_mp_sensitivity import RECOVERY_THRESHOLDS  # noqa: E402

PHASE = "Phase 13D-MP-RECOVERY"

STATUS_RECOVERY_PASS = (
    "%s Mixed-Precision Recovery Pass — a bounded PTQ mixed-precision candidate met the "
    "unmodified Phase 13D parity thresholds while retaining measured INT8 execution." % PHASE
)
STATUS_FROZEN = (
    "%s Frozen — bounded PTQ mixed-precision sensitivity search did not recover "
    "INT8-vs-FP16 parity; the INT8 engine remains performance evidence only and is not "
    "permitted to provide command authority." % PHASE
)

#: Full Recovery adds these on top of the parity criteria.
FULL_RECOVERY_MIN_QUANTIZED_FRACTION = 0.50
FULL_RECOVERY_MIN_THROUGHPUT_SPEEDUP = 1.0


def load_candidates(evidence_root: Path) -> List[Dict[str, Any]]:
    results = []  # type: List[Dict[str, Any]]
    pattern = str(evidence_root / "phase13dmp-*-phase13d" / "candidate_result.json")
    for path in sorted(glob.glob(pattern)):
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        payload["evidence_dir"] = os.path.dirname(path)
        results.append(payload)
    # Also record candidates that failed to build, so a failure is never lost.
    failed = []  # type: List[Dict[str, Any]]
    for path in sorted(glob.glob(str(evidence_root / "phase13dmp-*-phase13d" / "summary.json"))):
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if "result" in payload:
            continue
        failed.append(
            {
                "candidate_id": payload.get("candidate_id"),
                "evidence_dir": os.path.dirname(path),
                "status": payload.get("status"),
                "blockers": payload.get("blockers", []),
                "build_failed": True,
            }
        )
    return sorted(results, key=lambda item: str(item.get("candidate_id"))) + failed


def recovery_verdict(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Apply the unmodified recovery criteria to one candidate."""

    failures = []  # type: List[str]
    for name, bound in RECOVERY_THRESHOLDS.items():
        value = candidate.get(name)
        if value is None:
            failures.append("%s:missing" % name)
        elif name == "confidence_abs_error_p95":
            if float(value) > bound:
                failures.append("%s:%.4f>%.2f" % (name, float(value), bound))
        elif float(value) < bound:
            failures.append("%s:%.4f<%.2f" % (name, float(value), bound))
    if int(candidate.get("frames_with_schema_error") or 0):
        failures.append("schema_errors")
    if int(candidate.get("frames_with_nonfinite_output") or 0):
        failures.append("nonfinite_output")
    if int(candidate.get("unsafe_authority_divergence_count") or 0):
        failures.append("unsafe_authority_divergence")
    if int(candidate.get("int8_layer_count") or 0) <= 0:
        failures.append("no_int8_layers")
    if candidate.get("thermal_throttling_observed"):
        failures.append("thermal_throttling")

    fraction = candidate.get("quantized_layer_fraction")
    speedup = candidate.get("throughput_speedup")
    full_failures = list(failures)
    if fraction is None or float(fraction) < FULL_RECOVERY_MIN_QUANTIZED_FRACTION:
        full_failures.append("quantized_layer_fraction<0.50")
    if speedup is None or float(speedup) <= FULL_RECOVERY_MIN_THROUGHPUT_SPEEDUP:
        full_failures.append("throughput_speedup<=1.0")

    return {
        "recovery_pass": not failures,
        "recovery_failures": failures,
        "full_recovery_eligible": not full_failures,
        "full_recovery_failures": full_failures,
    }


def rank_groups(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Rank single-group candidates by how much class signal they restore."""

    ranked = []  # type: List[Dict[str, Any]]
    for candidate in candidates:
        groups = candidate.get("forced_fp16_group_ids") or []
        if len(groups) != 1:
            continue
        ranked.append(
            {
                "group_id": groups[0],
                "group_name": (candidate.get("forced_fp16_group_names") or [""])[0],
                "candidate_id": candidate.get("candidate_id"),
                "class_max_ratio_int8_over_fp16": candidate.get("class_max_ratio_int8_over_fp16"),
                "class_tensor_mae_vs_fp16": candidate.get("class_tensor_mae_vs_fp16"),
                "matched_detection_rate": candidate.get("matched_detection_rate"),
                "confidence_abs_error_p95": candidate.get("confidence_abs_error_p95"),
                "quantized_layer_fraction": candidate.get("quantized_layer_fraction"),
            }
        )
    # Most class recovery first: a higher INT8/FP16 peak-score ratio means more
    # of the classification signal survived when that group stayed in FP16.
    ranked.sort(
        key=lambda item: (
            -(item["class_max_ratio_int8_over_fp16"] or 0.0),
            item["class_tensor_mae_vs_fp16"] if item["class_tensor_mae_vs_fp16"] is not None else 1e9,
        )
    )
    for position, item in enumerate(ranked, start=1):
        item["rank"] = position
    return ranked


def select_candidate(candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Smallest qualifying candidate: fewest groups, then fewest forced layers."""

    qualifying = [
        candidate
        for candidate in candidates
        if not candidate.get("build_failed") and recovery_verdict(candidate)["recovery_pass"]
    ]
    if not qualifying:
        return None
    qualifying.sort(
        key=lambda item: (
            len(item.get("forced_fp16_group_ids") or []),
            int(item.get("forced_fp16_matched_layer_count") or 0),
            -(float(item.get("quantized_layer_fraction") or 0.0)),
        )
    )
    return qualifying[0]


def markdown_table(candidates: List[Dict[str, Any]]) -> str:
    header = (
        "| candidate | forced FP16 groups | forced layers | INT8 | FP16 | FP32 | quantized | "
        "class max ratio | class MAE | matched rate | class agree | IoU mean | conf err p95 | "
        "unsafe div | p50 ms | speedup | recovery |\n"
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
    )
    rows = []
    for candidate in candidates:
        if candidate.get("build_failed"):
            rows.append(
                "| `%s` | — | — | — | — | — | — | — | — | — | — | — | — | — | — | — | **build failed** |"
                % candidate.get("candidate_id")
            )
            continue
        verdict = recovery_verdict(candidate)
        rows.append(
            "| `%s` | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |"
            % (
                candidate.get("candidate_id"),
                ", ".join(candidate.get("forced_fp16_group_ids") or []) or "(none)",
                candidate.get("forced_fp16_matched_layer_count"),
                candidate.get("int8_layer_count"),
                candidate.get("fp16_layer_count"),
                candidate.get("fp32_layer_count"),
                candidate.get("quantized_layer_fraction"),
                candidate.get("class_max_ratio_int8_over_fp16"),
                candidate.get("class_tensor_mae_vs_fp16"),
                candidate.get("matched_detection_rate"),
                candidate.get("matched_class_agreement"),
                candidate.get("matched_box_iou_mean"),
                candidate.get("confidence_abs_error_p95"),
                candidate.get("unsafe_authority_divergence_count"),
                candidate.get("total_inference_ms_p50"),
                candidate.get("total_speedup_p50"),
                "**pass**" if verdict["recovery_pass"] else "fail",
            )
        )
    return header + "\n".join(rows) + "\n"


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13D-MP-RECOVERY candidate report")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--evidence-root", default="experiments/phase13")
    parser.add_argument("--output-dir", default="experiments/phase13")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    run_id = args.run_id or ("mp-report-%s" % new_run_id())
    root = Path(args.evidence_root)
    if not root.is_absolute():
        root = REPO_ROOT / root

    candidates = load_candidates(root)
    for candidate in candidates:
        if not candidate.get("build_failed"):
            candidate.update(recovery_verdict(candidate))

    ranking = rank_groups(candidates)
    selected = select_candidate(candidates)
    evidence = Phase13DEvidence(Path(args.output_dir), run_id)

    summary = {
        "phase": PHASE,
        "run_id": run_id,
        "created_at_utc": utc_now_iso(),
        "candidate_count": len(candidates),
        "candidate_ids": [item.get("candidate_id") for item in candidates],
        "parity_thresholds": dict(RECOVERY_THRESHOLDS),
        "parity_thresholds_modified": False,
        "full_recovery_min_quantized_layer_fraction": FULL_RECOVERY_MIN_QUANTIZED_FRACTION,
        "full_recovery_min_throughput_speedup": FULL_RECOVERY_MIN_THROUGHPUT_SPEEDUP,
        "group_sensitivity_ranking": ranking,
        "candidates": candidates,
        "selected_candidate": selected,
        "recovery_achieved": selected is not None,
        "status": STATUS_RECOVERY_PASS if selected is not None else STATUS_FROZEN,
    }  # type: Dict[str, Any]
    if selected is not None:
        summary["full_recovery_eligible"] = bool(selected.get("full_recovery_eligible"))
    else:
        summary["int8_backend_role"] = "experimental_non_authoritative"
        summary["production_command_authority_backend"] = "fp16"
        summary["int8_may_grant_ai_active"] = False
        summary["recommended_next_phase"] = (
            "Phase 13E-FP16-SOAK-THERMAL-BACKPRESSURE-FAULT-INJECTION"
        )
    if selected is not None:
        summary["recommended_next_phase"] = (
            "Phase 13E-INT8-SOAK-THERMAL-BACKPRESSURE-FAULT-INJECTION"
        )

    evidence.write_json("summary.json", summary)
    evidence.write_json("mp_candidates.json", candidates)
    evidence.write_text("mp_candidate_table.md", markdown_table(candidates))
    evidence.write_manifest("mp_recovery_report", summary["status"])
    evidence.write_placeholders()

    print(summary["status"])
    print("run_id=%s" % run_id)
    print("evidence_dir=%s" % evidence.run_dir)
    print("candidate_count=%d" % len(candidates))
    print()
    print(markdown_table(candidates))
    print("group sensitivity ranking (single-group candidates, most class recovery first):")
    for item in ranking:
        print(
            "  %d. %-8s %-24s class_max_ratio=%s mae=%s matched=%s conf_p95=%s"
            % (
                item["rank"], item["group_id"], item["group_name"],
                item["class_max_ratio_int8_over_fp16"], item["class_tensor_mae_vs_fp16"],
                item["matched_detection_rate"], item["confidence_abs_error_p95"],
            )
        )
    print()
    if selected is not None:
        print("selected_candidate=%s" % selected.get("candidate_id"))
        print("selected_groups=%s" % ",".join(selected.get("forced_fp16_group_ids") or []))
        print("full_recovery_eligible=%s" % selected.get("full_recovery_eligible"))
    else:
        print("selected_candidate=(none)")
        print("int8_backend_role=experimental_non_authoritative")
    return 0 if selected is not None else 2


if __name__ == "__main__":
    raise SystemExit(main())
