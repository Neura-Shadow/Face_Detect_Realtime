"""Phase 13D Gate A — local source, unit and fail-closed checks.

Gate A runs entirely on the simulation PC. It requires no calibration dataset,
no INT8 engine, no Jetson and no CARLA, and it therefore permits **only** the
``Prepared`` status.

It also hosts the shared Phase 13D definitions (status strings, boundary
fields, evidence layout) that the other Phase 13D scripts import. Anything that
Phase 13C already defined exactly once — ``run_command``, ``latency_stats``,
``latency_budget_ms``, ``pc_environment`` — is imported from Phase 13C rather
than redefined, so the two phases cannot drift apart.
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

PHASE = "Phase 13D-INT8-CALIBRATION-RANGE-SHIFT"
DEFAULT_OUTPUT_DIR = "experiments/phase13"

STATUS_PREPARED = (
    "%s Prepared — INT8 dataset, calibrator, cache, range, audit, parity and fault "
    "sources plus local unit and fail-closed gates passed, but no calibration corpus "
    "was captured and no INT8 engine was built." % PHASE
)
STATUS_DATASET_PASS = (
    "%s Dataset Pass — a controlled CARLA Town03 calibration corpus was captured with "
    "the required route and weather coverage, disjoint splits, per-frame manifests, a "
    "range profile and an offline activation proxy, but no INT8 engine was built." % PHASE
)
STATUS_ENGINE_PASS = (
    "%s Engine Pass — a target-built INT8 TensorRT engine was calibrated and verified on "
    "the real Jetson with INT8 layers observed and a bounded FP16-vs-INT8 benchmark, but "
    "streamed INT8 runtime was not completed." % PHASE
)
STATUS_RUNTIME_PASS = (
    "%s Runtime Pass — real Jetson TensorRT INT8 inference processed streamed frames with "
    "no fallback, held the calibration envelope and preserved the Phase 13B command/ACK "
    "safety path, but the CARLA closed loop was not completed." % PHASE
)
STATUS_PASS = (
    "%s Pass — real Jetson TensorRT INT8 perception processed simulated CARLA frames, "
    "passed the calibration-envelope, output-range and FP16-parity gates, produced fresh "
    "no-fallback perception results in the command authority path, and closed the loop "
    "through the C Virtual Safety MCU into CARLA virtual actuation." % PHASE
)
STATUS_BLOCKED = (
    "%s Blocked — a required dataset, calibration, cache, engine, audit, parity, latency, "
    "safety, Jetson, transport or CARLA gate did not pass." % PHASE
)

#: Everything Phase 13D must never claim, written into every evidence file.
#: Deliberately excludes every *measured* INT8 field (``int8_engine_built``,
#: ``int8_layers_observed``, ``all_layers_int8``, ``int8_layer_count``) so that
#: a late ``summary.update(BOUNDARY_FIELDS)`` can never overwrite evidence.
BOUNDARY_FIELDS = {
    "validation_type": "processor_in_the_loop",
    "precision": "int8",
    "qat_verified": False,
    "quantization_aware_training_performed": False,
    "model_accuracy_verified": False,
    "map_evaluated": False,
    "recall_evaluated": False,
    "real_world_perception_quality_verified": False,
    "dataset_real_world_representative": False,
    "dataset_source": "controlled_carla_simulation",
    "runtime_internal_activation_monitoring_verified": False,
    "runtime_tensorrt_internal_activations_observed": False,
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
    return "phase13d-%s-%s" % (
        datetime.utcnow().strftime("%Y%m%dT%H%M%SZ"),
        uuid.uuid4().hex[:6],
    )


# ── Shared runtime-health rules ─────────────────────────────────────────────

#: Metric name -> blocker emitted when the metric is non-zero / true.
_NONZERO_BLOCKERS = (
    ("tensorrt_fallback_count", "tensorrt_fallback_used"),
    ("per_frame_device_allocation_count", "per_frame_device_allocation"),
    ("per_batch_device_allocation_count", "per_batch_device_allocation"),
    ("cuda_error_count", "cuda_execution_error"),
    ("engine_execute_failure_count", "engine_execute_failed"),
    ("tensorrt_inference_failed_count", "tensorrt_inference_failed"),
    ("skipped_frame_count", "calibration_frame_skipped"),
)


def evaluate_runtime_health(
    metrics: Dict[str, Any], *, deadline_ms: Optional[float] = None,
    observed_p99_ms: Optional[float] = None,
) -> Dict[str, Any]:
    """One definition of the run-health rules every Phase 13D gate applies.

    Fallback, per-frame or per-batch device allocation, CUDA errors, execute
    failures, skipped calibration frames, observed thermal throttling and a
    missed deadline are gate blockers wherever they appear, so they are decided
    here once rather than re-implemented per script.
    """

    blockers = []  # type: List[str]
    if metrics.get("thermal_throttling_observed"):
        blockers.append("thermal_throttling_observed")
    for key, blocker in _NONZERO_BLOCKERS:
        value = metrics.get(key)
        if value:
            blockers.append(blocker)
    if deadline_ms is not None:
        if observed_p99_ms is None:
            blockers.append("frame_to_command_latency_unavailable")
        elif float(observed_p99_ms) >= float(deadline_ms):
            blockers.append("inference_deadline_missed")
    return {
        "runtime_health_passed": not blockers,
        "runtime_health_deadline_ms": deadline_ms,
        "runtime_health_observed_p99_ms": observed_p99_ms,
        "blockers": sorted(set(blockers)),
    }


# ── Evidence ────────────────────────────────────────────────────────────────


class Phase13DEvidence:
    """Writes the Phase 13D evidence tree; generated output stays uncommitted."""

    REQUIRED_FILES = (
        "manifest.json",
        "summary.json",
        "environment.json",
        "dataset_manifest.json",
        "calibration_cache_manifest.json",
        "engine_manifest.json",
        "engine_audit.json",
        "activation_proxy.json",
        "latency_metrics.json",
        "precision_benchmark.json",
        "range_metrics.json",
        "parity_metrics.json",
        "phase13d_fault_matrix.json",
        "phase13d_fault_matrix.csv",
        "jetson_metrics.json",
        "network_metrics.json",
        "events.jsonl",
        "commands.txt",
        "README.md",
        "raw_outputs/",
    )

    PLACEHOLDER_FILES = (
        "dataset_manifest.json",
        "calibration_cache_manifest.json",
        "engine_manifest.json",
        "engine_audit.json",
        "activation_proxy.json",
        "latency_metrics.json",
        "precision_benchmark.json",
        "range_metrics.json",
        "parity_metrics.json",
        "jetson_metrics.json",
        "network_metrics.json",
    )

    def __init__(self, output_dir: Path, run_id: str) -> None:
        root = Path(output_dir)
        if not root.is_absolute():
            root = REPO_ROOT / root
        self.run_id = run_id
        suffix = "-phase13d"
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

    def write_fault_matrix(self, rows: Sequence[Dict[str, Any]]) -> None:
        self.write_json("phase13d_fault_matrix.json", list(rows))
        columns = [
            "fault_id",
            "fault_name",
            "gate",
            "injection_step",
            "expected_classification",
            "observed_classification",
            "passed",
            "details",
        ]
        with open(
            str(self.run_dir / "phase13d_fault_matrix.csv"), "w", newline="", encoding="utf-8"
        ) as handle:
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

PHASE13D_SOURCE_FILES = (
    "workers/core/int8_calibration_dataset.py",
    "workers/core/int8_calibrator.py",
    "workers/core/int8_engine_audit.py",
    "workers/core/int8_range_monitor.py",
    "workers/core/int8_activation_proxy.py",
    "scripts/run_phase13d_checks.py",
    "scripts/run_phase13d_dataset_build.py",
    "scripts/run_phase13d_activation_proxy.py",
    "scripts/run_phase13d_int8_engine_build.py",
    "scripts/run_phase13d_precision_benchmark.py",
    "scripts/run_phase13d_precision_parity.py",
    "scripts/run_phase13d_streamed_runtime.py",
    "scripts/run_phase13d_carla_closed_loop.py",
    "scripts/run_phase13d_orchestrator.py",
)

#: Modules that must import and parse under Jetson Python 3.8.
JETSON_MODULES = (
    "workers/core/int8_calibration_dataset.py",
    "workers/core/int8_calibrator.py",
    "workers/core/int8_engine_audit.py",
    "workers/core/int8_range_monitor.py",
    "workers/core/int8_activation_proxy.py",
    "workers/core/tensorrt_asset_contract.py",
    "workers/core/tensorrt_runtime.py",
    "workers/core/tensorrt_perception.py",
    "workers/core/tensorrt_range_monitor.py",
    "scripts/run_phase13d_int8_engine_build.py",
    "scripts/run_phase13d_precision_benchmark.py",
    "scripts/run_phase13d_precision_parity.py",
    "scripts/run_phase13b_jetson_node.py",
)


def check_source_files_present() -> Dict[str, Any]:
    missing = [name for name in PHASE13D_SOURCE_FILES if not (REPO_ROOT / name).is_file()]
    return {
        "source_files_expected": len(PHASE13D_SOURCE_FILES),
        "source_files_missing": missing,
        "source_files_present": not missing,
    }


def check_python38_compatibility() -> Dict[str, Any]:
    """Parse every Jetson-side module under a 3.8 feature guard."""

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
    return {
        "pattern": pattern,
        "returncode": result["returncode"],
        "passed": result["returncode"] == 0,
        "tail": output.splitlines()[-20:],
    }


def run_unit_tests() -> Dict[str, Any]:
    payload = _discover("test_phase13d_*.py")
    return {
        "unit_tests_passed": payload["passed"],
        "unit_tests_returncode": payload["returncode"],
        "unit_tests_output_tail": payload["tail"],
    }


def run_regressions() -> Dict[str, Any]:
    """Phase 13A/13B/13C must keep passing: Phase 13D may not regress them."""

    phase13c = _discover("test_phase13c_*.py")
    phase13b = _discover("test_phase13b_*.py")
    phase13a = _discover("test_phase13a_*.py")
    return {
        "phase13c_unit_regression_passed": phase13c["passed"],
        "phase13c_unit_regression_tail": phase13c["tail"][-6:],
        "phase13b_unit_regression_passed": phase13b["passed"],
        "phase13b_unit_regression_tail": phase13b["tail"][-6:],
        "phase13a_unit_regression_passed": phase13a["passed"],
        "phase13a_unit_regression_tail": phase13a["tail"][-6:],
    }


def probe_local_runtimes() -> Dict[str, Any]:
    """Report TensorRT/CUDA availability on this host; installs nothing."""

    from workers.core.tensorrt_runtime import cuda_preflight, tensorrt_preflight

    return {"tensorrt": tensorrt_preflight(), "cuda": cuda_preflight()}


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13D Gate A local checks")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--skip-unit-tests", action="store_true")
    parser.add_argument("--skip-regressions", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    run_id = args.run_id or new_run_id()
    evidence = Phase13DEvidence(Path(args.output_dir), run_id)
    environment = pc_environment()

    summary = {
        "phase": PHASE,
        "gate": "A",
        "run_id": run_id,
        "created_at_utc": utc_now_iso(),
    }  # type: Dict[str, Any]

    summary.update(check_source_files_present())
    summary.update(check_python38_compatibility())
    summary["local_runtimes"] = probe_local_runtimes()

    unit = (
        {"unit_tests_passed": False, "unit_tests_skipped": True}
        if args.skip_unit_tests
        else run_unit_tests()
    )
    summary.update(unit)
    regressions = (
        {
            "phase13c_unit_regression_passed": False,
            "phase13b_unit_regression_passed": False,
            "phase13a_unit_regression_passed": False,
            "regressions_skipped": True,
        }
        if args.skip_regressions
        else run_regressions()
    )
    summary.update(regressions)

    gate_a_passed = bool(
        summary.get("source_files_present")
        and summary.get("python38_parse_passed")
        and summary.get("unit_tests_passed")
        and summary.get("phase13c_unit_regression_passed")
        and summary.get("phase13b_unit_regression_passed")
        and summary.get("phase13a_unit_regression_passed")
    )
    summary["gate_a_passed"] = gate_a_passed
    summary["gate_a_permits_status"] = "Prepared"
    for gate in ("b", "c", "d", "e"):
        summary["gate_%s_executed" % gate] = False
    summary["int8_engine_built"] = False
    summary["int8_layers_observed"] = False
    summary["all_layers_int8"] = False
    summary["calibration_dataset_captured"] = False
    summary["status"] = STATUS_PREPARED if gate_a_passed else STATUS_BLOCKED
    summary["pc_environment"] = environment
    summary.update(BOUNDARY_FIELDS)

    evidence.write_json("summary.json", summary)
    evidence.write_json("environment.json", environment)
    evidence.write_manifest("A", summary["status"])
    evidence.write_placeholders(
        payload={"executed": False, "reason": "Gate A is local-only; no dataset, engine, Jetson or CARLA"}
    )
    evidence.write_fault_matrix([])
    evidence.write_events([])
    evidence.write_text(
        "commands.txt", "# Phase 13D Gate A\n%s %s\n" % (sys.executable, " ".join(sys.argv))
    )
    evidence.write_text(
        "README.md",
        "# Phase 13D Gate A evidence\n\nRun id: `%s`\n\nStatus: `%s`\n\n"
        "Local-only source, unit and fail-closed checks. No calibration dataset, no INT8 "
        "engine, no real Jetson and no CARLA were involved, so Gate A alone permits only "
        "`Prepared`.\n" % (run_id, summary["status"]),
    )

    print(summary["status"])
    print("run_id=%s" % run_id)
    print("evidence_dir=%s" % evidence.run_dir)
    for key in (
        "source_files_present",
        "python38_parse_passed",
        "unit_tests_passed",
        "phase13c_unit_regression_passed",
        "phase13b_unit_regression_passed",
        "phase13a_unit_regression_passed",
        "gate_a_passed",
    ):
        print("%s=%s" % (key, summary.get(key)))
    return 0 if gate_a_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
