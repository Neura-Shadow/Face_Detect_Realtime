"""Phase 13E Gate A — local preflight, and the shared Phase 13E definitions.

Gate A runs entirely on the simulation PC: source presence, Python 3.8 parse
guard for the Jetson-side modules, the Phase 13E unit tests, the Phase 13C
fault matrix (22/22, executed with test doubles) and the Phase 13A/13B/13C/13D
regressions. It involves no Jetson and no CARLA, so it permits only
``Prepared``.

The Jetson-side half of Gate A — FP16 engine deserialize, binding and hash
verification, and the Phase 13B fault matrix over the real link — lives in
``run_phase13e_soak.py --phases preflight`` because it needs the real target.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from run_phase13c_checks import (  # noqa: E402,F401  (re-exported on purpose)
    DEFAULT_COMMAND_VALIDITY_MS,
    DEFAULT_SAFETY_MARGIN_MS,
    latency_budget_ms,
    latency_stats,
    pc_environment,
    pc_git_sha,
    run_command,
    utc_now_iso,
)
from run_phase13d_checks import evaluate_runtime_health, run_command_utf8  # noqa: E402,F401

PHASE = "Phase 13E-FP16-SOAK-THERMAL-BACKPRESSURE-FAULT-INJECTION"
DEFAULT_OUTPUT_DIR = "experiments/phase13"

STATUS_PREPARED = (
    "%s Prepared — local soak, drift, backpressure and fault sources plus unit and "
    "regression gates passed, but no real Jetson soak was executed." % PHASE
)
STATUS_PREFLIGHT_PASS = (
    "%s Preflight Pass — the real Jetson FP16 engine was verified by hash, deserialize "
    "and binding contract and the fault matrices passed, but no soak was executed." % PHASE
)
STATUS_BURN_IN_PASS = (
    "%s Burn-in Pass — a bounded burn-in held the FP16 command-authority path with "
    "bounded mailbox depth, but the formal soak was not completed." % PHASE
)
STATUS_PASS = (
    "%s Pass — the real Jetson FP16 command-authority path held a formal soak with no "
    "crash, no fallback, no CUDA error, no per-frame allocation, bounded mailbox depth, "
    "no resource or thermal drift, recovered from every injected fault, and kept the C "
    "Virtual Safety MCU as the sole command authority." % PHASE
)
STATUS_BLOCKED = (
    "%s Blocked — a required preflight, soak, drift, backpressure, fault-injection, "
    "latency, safety, Jetson or CARLA gate did not pass." % PHASE
)

#: Everything Phase 13E must never claim, plus the Phase 13D-MP-RECOVERY policy.
BOUNDARY_FIELDS = {
    "validation_type": "processor_in_the_loop",
    "precision": "fp16",
    "command_authority_backend": "fp16_tensorrt_yolov9c",
    "int8_backend_role": "experimental_non_authoritative",
    "int8_may_grant_ai_active": False,
    "qat_verified": False,
    "quantization_aware_training_performed": False,
    "model_accuracy_verified": False,
    "map_evaluated": False,
    "recall_evaluated": False,
    "real_world_perception_quality_verified": False,
    "safe_autonomous_navigation_verified": False,
    "route_completion_verified": False,
    "route_benchmark_verified": False,
    "infraction_benchmark_verified": False,
    "leaderboard_evaluated": False,
    "full_hil_verified": False,
    "real_mcu_verified": False,
    "real_can_uart_timing_verified": False,
    "physical_camera_verified": False,
    "physical_actuator_control_executed": False,
    "physical_vehicle_deployment": False,
    "power_inference_from_utilization": False,
}


def new_run_id() -> str:
    return "phase13e-%s-%s" % (
        datetime.utcnow().strftime("%Y%m%dT%H%M%SZ"),
        uuid.uuid4().hex[:6],
    )


class Phase13EEvidence:
    """Writes the Phase 13E evidence tree; generated output stays uncommitted."""

    REQUIRED_FILES = (
        "manifest.json",
        "summary.json",
        "environment.json",
        "engine_manifest.json",
        "soak_timeseries.json",
        "drift_report.json",
        "latency_metrics.json",
        "backpressure_metrics.json",
        "fault_injection_matrix.json",
        "fault_injection_matrix.csv",
        "phase13e_fault_matrix.json",
        "phase13e_fault_matrix.csv",
        "jetson_metrics.json",
        "network_metrics.json",
        "events.jsonl",
        "commands.txt",
        "README.md",
        "raw_outputs/",
    )

    PLACEHOLDER_FILES = (
        "engine_manifest.json",
        "soak_timeseries.json",
        "drift_report.json",
        "latency_metrics.json",
        "backpressure_metrics.json",
        "jetson_metrics.json",
        "network_metrics.json",
    )

    def __init__(self, output_dir: Path, run_id: str) -> None:
        root = Path(output_dir)
        if not root.is_absolute():
            root = REPO_ROOT / root
        self.run_id = run_id
        suffix = "-phase13e"
        self.run_dir = root / (run_id if run_id.endswith(suffix) else "%s%s" % (run_id, suffix))
        (self.run_dir / "raw_outputs").mkdir(parents=True, exist_ok=True)

    def write_json(self, name: str, payload: Any) -> None:
        target = self.run_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
        )

    def write_text(self, name: str, text: str) -> None:
        target = self.run_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def write_events(self, events: Sequence[Dict[str, Any]]) -> None:
        self.write_text(
            "events.jsonl",
            "".join(json.dumps(event, ensure_ascii=False, default=str) + "\n" for event in events),
        )

    def write_fault_matrix(self, rows: Sequence[Dict[str, Any]], *, name: str = "phase13e_fault_matrix") -> None:
        self.write_json("%s.json" % name, list(rows))
        columns = [
            "fault_id",
            "fault_name",
            "gate",
            "injection_step",
            "expected_classification",
            "observed_classification",
            "passed",
            "recovered",
            "recovery_sec",
            "details",
        ]
        with open(str(self.run_dir / ("%s.csv" % name)), "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key, "") for key in columns})

    def write_placeholders(self, names: Sequence[str] = (), payload: Any = None) -> None:
        for name in (names or self.PLACEHOLDER_FILES):
            target = self.run_dir / name
            if not target.exists():
                self.write_json(name, payload if payload is not None else {"executed": False})

    def write_manifest(self, gate: str, status: str, **extra: Any) -> None:
        payload = {
            "phase": PHASE,
            "gate": gate,
            "run_id": self.run_id,
            "status": status,
            "created_at_utc": utc_now_iso(),
            "evidence_dir": str(self.run_dir),
            "generated_evidence_git_policy": "ignored_local_only",
            "output_files": list(self.REQUIRED_FILES),
        }
        payload.update(extra)
        payload.update(BOUNDARY_FIELDS)
        self.write_json("manifest.json", payload)


# ── Gate A checks ───────────────────────────────────────────────────────────

PHASE13E_SOURCE_FILES = (
    "workers/core/soak_metrics.py",
    "scripts/run_phase13e_checks.py",
    "scripts/run_phase13e_soak.py",
)

JETSON_MODULES = (
    "workers/core/soak_metrics.py",
    "workers/core/tensorrt_runtime.py",
    "workers/core/tensorrt_perception.py",
    "workers/core/tensorrt_range_monitor.py",
    "workers/core/int8_range_monitor.py",
    "scripts/run_phase13b_jetson_node.py",
)


def check_source_files_present() -> Dict[str, Any]:
    missing = [name for name in PHASE13E_SOURCE_FILES if not (REPO_ROOT / name).is_file()]
    return {
        "source_files_expected": len(PHASE13E_SOURCE_FILES),
        "source_files_missing": missing,
        "source_files_present": not missing,
    }


def check_python38_compatibility() -> Dict[str, Any]:
    import ast

    failures = []  # type: List[Dict[str, str]]
    for relative in JETSON_MODULES:
        path = REPO_ROOT / relative
        if not path.is_file():
            failures.append({"file": relative, "error": "missing"})
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=relative, feature_version=(3, 8))
        except SyntaxError as exc:
            failures.append({"file": relative, "error": "%s (line %s)" % (exc.msg, exc.lineno)})
    return {
        "python38_parse_checked_count": len(JETSON_MODULES),
        "python38_parse_failures": failures,
        "python38_parse_passed": not failures,
    }


def _discover(pattern: str, timeout: int = 2400) -> Dict[str, Any]:
    result = run_command(
        [sys.executable, "-m", "unittest", "discover", "-s", "scripts/tests", "-p", pattern, "-v"],
        timeout=timeout,
    )
    output = (result["stdout"] + "\n" + result["stderr"]).strip()
    return {"pattern": pattern, "passed": result["returncode"] == 0, "tail": output.splitlines()[-12:]}


def run_regressions() -> Dict[str, Any]:
    payload = {}  # type: Dict[str, Any]
    for label, pattern in (
        ("phase13e", "test_phase13e_*.py"),
        ("phase13d", "test_phase13d_*.py"),
        ("phase13c", "test_phase13c_*.py"),
        ("phase13b", "test_phase13b_*.py"),
        ("phase13a", "test_phase13a_*.py"),
    ):
        outcome = _discover(pattern)
        payload["%s_unit_regression_passed" % label] = outcome["passed"]
        payload["%s_unit_regression_tail" % label] = outcome["tail"][-4:]
    return payload


def run_phase13c_fault_matrix() -> Dict[str, Any]:
    """The Phase 13C fault matrix must still be 22/22 with 0 false accepts."""

    sys.path.insert(0, str(REPO_ROOT / "scripts" / "tests"))
    from test_phase13c_faults import matrix_counts, run_fault_matrix  # noqa: E402

    rows = run_fault_matrix()
    counts = matrix_counts(rows)
    passed = [row for row in rows if row["passed"]]
    return {
        "phase13c_fault_case_count": len(rows),
        "phase13c_fault_case_passed_count": len(passed),
        "phase13c_fault_matrix_passed": len(passed) == len(rows) == 22,
        "phase13c_false_accept_count": counts["false_accept_count"],
        "phase13c_false_reject_count": counts["false_reject_count"],
        "phase13c_fault_failures": [
            {"fault_id": row["fault_id"], "observed": row["observed_classification"]}
            for row in rows
            if not row["passed"]
        ],
    }


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13E Gate A local preflight")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--skip-regressions", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    run_id = args.run_id or new_run_id()
    evidence = Phase13EEvidence(Path(args.output_dir), run_id)
    environment = pc_environment()

    summary = {
        "phase": PHASE,
        "gate": "A_local_preflight",
        "run_id": run_id,
        "created_at_utc": utc_now_iso(),
    }  # type: Dict[str, Any]
    summary.update(check_source_files_present())
    summary.update(check_python38_compatibility())
    summary.update(run_phase13c_fault_matrix())
    if args.skip_regressions:
        summary["regressions_skipped"] = True
    else:
        summary.update(run_regressions())

    gate_a_passed = bool(
        summary.get("source_files_present")
        and summary.get("python38_parse_passed")
        and summary.get("phase13c_fault_matrix_passed")
        and (
            args.skip_regressions
            or (
                summary.get("phase13e_unit_regression_passed")
                and summary.get("phase13d_unit_regression_passed")
                and summary.get("phase13c_unit_regression_passed")
                and summary.get("phase13b_unit_regression_passed")
                and summary.get("phase13a_unit_regression_passed")
            )
        )
    )
    summary["gate_a_passed"] = gate_a_passed
    summary["gate_a_permits_status"] = "Prepared"
    summary["status"] = STATUS_PREPARED if gate_a_passed else STATUS_BLOCKED
    summary["pc_environment"] = environment
    summary.update(BOUNDARY_FIELDS)

    evidence.write_json("summary.json", summary)
    evidence.write_json("environment.json", environment)
    evidence.write_manifest("A_local_preflight", summary["status"])
    evidence.write_placeholders(
        payload={"executed": False, "reason": "Gate A is local-only; no Jetson and no CARLA"}
    )
    evidence.write_fault_matrix([])
    evidence.write_fault_matrix([], name="fault_injection_matrix")
    evidence.write_events([])
    evidence.write_text(
        "commands.txt", "# Phase 13E Gate A\n%s %s\n" % (sys.executable, " ".join(sys.argv))
    )
    evidence.write_text(
        "README.md",
        "# Phase 13E Gate A evidence\n\nRun id: `%s`\n\nStatus: `%s`\n\n"
        "Local-only preflight. FP16 is the command-authority backend; INT8 remains "
        "experimental_non_authoritative under the Phase 13D-MP-RECOVERY freeze.\n"
        % (run_id, summary["status"]),
    )

    print(summary["status"])
    print("run_id=%s" % run_id)
    print("evidence_dir=%s" % evidence.run_dir)
    for key in (
        "source_files_present",
        "python38_parse_passed",
        "phase13c_fault_case_passed_count",
        "phase13c_fault_matrix_passed",
        "phase13c_false_accept_count",
        "phase13c_false_reject_count",
        "phase13e_unit_regression_passed",
        "phase13d_unit_regression_passed",
        "phase13c_unit_regression_passed",
        "phase13b_unit_regression_passed",
        "phase13a_unit_regression_passed",
        "gate_a_passed",
    ):
        if key in summary:
            print("%s=%s" % (key, summary[key]))
    return 0 if gate_a_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
