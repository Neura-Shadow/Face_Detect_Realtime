"""Phase 13C Gate A — local source, unit and fail-closed checks.

Gate A runs entirely on the simulation PC. It requires no TensorRT engine, no
Jetson and no CARLA, and it therefore permits **only** the ``Prepared`` status.

It also hosts the shared Phase 13C helpers (status strings, boundary fields,
latency statistics, evidence layout) that the other Phase 13C scripts import,
so the phase has exactly one definition of each.
"""

from __future__ import annotations

import argparse
import json
import platform
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

PHASE = "Phase 13C-TENSORRT-FP16-EDGE-PERCEPTION"
DEFAULT_OUTPUT_DIR = "experiments/phase13"

STATUS_PREPARED = (
    "%s Prepared — TensorRT source integration, asset contracts, unit tests and local "
    "fail-closed gates passed, but no real Jetson FP16 engine was verified." % PHASE
)
STATUS_ENGINE_PASS = (
    "%s Engine Pass — a target-built FP16 TensorRT engine was verified on the real "
    "Jetson and completed bounded standalone inference, but streamed JIL runtime was "
    "not completed." % PHASE
)
STATUS_RUNTIME_PASS = (
    "%s Runtime Pass — real Jetson TensorRT FP16 inference processed streamed frames "
    "with no fallback and preserved the Phase 13B command/ACK safety path, but the "
    "CARLA closed loop was not completed." % PHASE
)
STATUS_PASS = (
    "%s Pass — real Jetson TensorRT FP16 perception processed simulated CARLA frames, "
    "passed input/output range and backend-consistency gates, produced fresh "
    "no-fallback perception results in the command authority path, and closed the loop "
    "through the C Virtual Safety MCU into CARLA virtual actuation." % PHASE
)
STATUS_BLOCKED = (
    "%s Blocked — a required asset, export, TensorRT, CUDA, parity, latency, safety, "
    "Jetson, transport or CARLA gate did not pass." % PHASE
)

#: Everything Phase 13C must never claim, written into every evidence file.
BOUNDARY_FIELDS = {
    "validation_type": "processor_in_the_loop",
    "precision": "fp16",
    "int8_engine_built": False,
    "int8_calibration_verified": False,
    "qat_verified": False,
    "model_accuracy_verified": False,
    "map_evaluated": False,
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
}

DEFAULT_COMMAND_VALIDITY_MS = 1000
DEFAULT_SAFETY_MARGIN_MS = 50


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def new_run_id() -> str:
    return "phase13c-%s-%s" % (
        datetime.utcnow().strftime("%Y%m%dT%H%M%SZ"),
        uuid.uuid4().hex[:6],
    )


def run_command(
    command: List[str], *, cwd: Optional[Path] = None, timeout: int = 1800
) -> Dict[str, Any]:
    started = time.perf_counter_ns()
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd or REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=timeout,
        )
        return {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "duration_sec": round((time.perf_counter_ns() - started) / 1e9, 3),
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "command": command,
            "returncode": -1,
            "stdout": "",
            "stderr": repr(exc),
            "duration_sec": round((time.perf_counter_ns() - started) / 1e9, 3),
        }


def pc_git_sha() -> str:
    result = run_command(["git", "rev-parse", "HEAD"], timeout=60)
    return result["stdout"].strip() if result["returncode"] == 0 else ""


# ── Latency statistics ──────────────────────────────────────────────────────


def _percentile(ordered: List[float], percentile: float) -> float:
    """Nearest-rank percentile; deterministic and numpy-free."""

    if not ordered:
        return 0.0
    rank = int(round((percentile / 100.0) * (len(ordered) - 1)))
    return ordered[max(0, min(len(ordered) - 1, rank))]


def latency_stats(samples: Sequence[float]) -> Dict[str, Any]:
    """min / p50 / p95 / p99 / max / mean / sample_count for one metric."""

    values = [float(value) for value in samples if value is not None]
    if not values:
        return {
            "min": None,
            "p50": None,
            "p95": None,
            "p99": None,
            "max": None,
            "mean": None,
            "sample_count": 0,
        }
    ordered = sorted(values)
    return {
        "min": round(ordered[0], 4),
        "p50": round(_percentile(ordered, 50.0), 4),
        "p95": round(_percentile(ordered, 95.0), 4),
        "p99": round(_percentile(ordered, 99.0), 4),
        "max": round(ordered[-1], 4),
        "mean": round(sum(ordered) / len(ordered), 4),
        "sample_count": len(ordered),
    }


def latency_budget_ms(
    *,
    command_validity_ms: int = DEFAULT_COMMAND_VALIDITY_MS,
    clock_uncertainty_ms: float = 0.0,
    safety_margin_ms: int = DEFAULT_SAFETY_MARGIN_MS,
) -> float:
    """``command_validity_ms - clock_uncertainty_ms - safety_margin_ms``."""

    return float(command_validity_ms) - float(clock_uncertainty_ms) - float(safety_margin_ms)


# ── Evidence ────────────────────────────────────────────────────────────────


class Phase13CEvidence:
    """Writes the Phase 13C evidence tree; generated output stays uncommitted."""

    REQUIRED_FILES = (
        "manifest.json",
        "summary.json",
        "environment.json",
        "model_manifest.json",
        "engine_manifest.json",
        "latency_metrics.json",
        "range_metrics.json",
        "parity_metrics.json",
        "phase13c_fault_matrix.json",
        "phase13c_fault_matrix.csv",
        "jetson_metrics.json",
        "network_metrics.json",
        "events.jsonl",
        "commands.txt",
        "README.md",
        "raw_outputs/",
    )

    def __init__(self, output_dir: Path, run_id: str) -> None:
        root = Path(output_dir)
        if not root.is_absolute():
            root = REPO_ROOT / root
        self.run_id = run_id
        self.run_dir = root / ("%s-phase13c" % run_id if not run_id.endswith("-phase13c") else run_id)
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

    def write_events(self, events: List[Dict[str, Any]]) -> None:
        self.write_text(
            "events.jsonl",
            "".join(json.dumps(event, ensure_ascii=False, default=str) + "\n" for event in events),
        )

    def write_fault_matrix(self, rows: List[Dict[str, Any]]) -> None:
        import csv

        self.write_json("phase13c_fault_matrix.json", rows)
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
            str(self.run_dir / "phase13c_fault_matrix.csv"), "w", newline="", encoding="utf-8"
        ) as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key, "") for key in columns})

    def write_placeholders(self, names: Sequence[str], payload: Any = None) -> None:
        """Keep the evidence layout complete even when a gate did not execute."""

        for name in names:
            target = self.run_dir / name
            if not target.exists():
                self.write_json(name, payload if payload is not None else {"executed": False})


def pc_environment() -> Dict[str, Any]:
    payload = {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "arch": platform.machine(),
        "runtime_pc_git_sha": pc_git_sha(),
        "repository_root": str(REPO_ROOT),
        "dependencies_auto_installed": False,
    }
    for module_name in ("numpy", "torch", "onnx", "cv2", "tensorrt", "yaml"):
        try:
            module = __import__(module_name)
            payload["dep_%s" % module_name] = str(getattr(module, "__version__", "present"))
        except Exception:
            payload["dep_%s" % module_name] = "MISSING"
    return payload


# ── Gate A checks ───────────────────────────────────────────────────────────

PHASE13C_SOURCE_FILES = (
    "workers/core/tensorrt_asset_contract.py",
    "workers/core/tensorrt_runtime.py",
    "workers/core/tensorrt_perception.py",
    "workers/core/tensorrt_range_monitor.py",
    "scripts/run_phase13c_onnx_export.py",
    "scripts/run_phase13c_engine_build.py",
    "scripts/run_phase13c_standalone_benchmark.py",
    "scripts/run_phase13c_backend_parity.py",
    "scripts/run_phase13c_streamed_runtime.py",
    "scripts/run_phase13c_carla_closed_loop.py",
    "scripts/run_phase13c_checks.py",
    "scripts/run_phase13c_orchestrator.py",
)


def check_python38_compatibility() -> Dict[str, Any]:
    """Parse every Jetson-side module under a 3.8 feature guard.

    ``ast.parse(feature_version=(3, 8))`` rejects syntax that Python 3.8 cannot
    parse, which is the failure mode that would otherwise only appear on the
    Jetson.
    """

    import ast

    jetson_modules = [
        "workers/core/tensorrt_asset_contract.py",
        "workers/core/tensorrt_runtime.py",
        "workers/core/tensorrt_perception.py",
        "workers/core/tensorrt_range_monitor.py",
        "scripts/run_phase13c_engine_build.py",
        "scripts/run_phase13c_standalone_benchmark.py",
        "scripts/run_phase13b_jetson_node.py",
    ]
    failures = []  # type: List[Dict[str, str]]
    for relative in jetson_modules:
        path = REPO_ROOT / relative
        if not path.is_file():
            failures.append({"file": relative, "error": "missing"})
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8"), filename=relative, feature_version=(3, 8))
        except SyntaxError as exc:
            failures.append({"file": relative, "error": "%s (line %s)" % (exc.msg, exc.lineno)})
    return {
        "python38_parse_checked_count": len(jetson_modules),
        "python38_parse_failures": failures,
        "python38_parse_passed": not failures,
    }


def check_source_files_present() -> Dict[str, Any]:
    missing = [name for name in PHASE13C_SOURCE_FILES if not (REPO_ROOT / name).is_file()]
    return {
        "source_files_expected": len(PHASE13C_SOURCE_FILES),
        "source_files_missing": missing,
        "source_files_present": not missing,
    }


def run_unit_tests() -> Dict[str, Any]:
    result = run_command(
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "scripts/tests",
            "-p",
            "test_phase13c_*.py",
            "-v",
        ],
        timeout=1800,
    )
    output = (result["stdout"] + "\n" + result["stderr"]).strip()
    return {
        "unit_tests_passed": result["returncode"] == 0,
        "unit_tests_returncode": result["returncode"],
        "unit_tests_output_tail": output.splitlines()[-20:],
    }


def run_phase13b_regression() -> Dict[str, Any]:
    """Phase 13B must keep passing: Phase 13C may not regress the bridge."""

    result = run_command(
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "scripts/tests",
            "-p",
            "test_phase13b_*.py",
        ],
        timeout=1800,
    )
    output = (result["stdout"] + "\n" + result["stderr"]).strip()
    return {
        "phase13b_unit_regression_passed": result["returncode"] == 0,
        "phase13b_unit_regression_tail": output.splitlines()[-6:],
    }


def probe_local_runtimes() -> Dict[str, Any]:
    """Report TensorRT/CUDA availability on this host; installs nothing."""

    from workers.core.tensorrt_runtime import cuda_preflight, tensorrt_preflight

    return {"tensorrt": tensorrt_preflight(), "cuda": cuda_preflight()}


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13C Gate A local checks")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--skip-unit-tests", action="store_true")
    parser.add_argument("--skip-phase13b-regression", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    run_id = args.run_id or new_run_id()
    evidence = Phase13CEvidence(Path(args.output_dir), run_id)
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

    unit = {"unit_tests_passed": False, "skipped": True} if args.skip_unit_tests else run_unit_tests()
    summary.update(unit)
    regression = (
        {"phase13b_unit_regression_passed": False, "skipped": True}
        if args.skip_phase13b_regression
        else run_phase13b_regression()
    )
    summary.update(regression)

    gate_a_passed = bool(
        summary.get("source_files_present")
        and summary.get("python38_parse_passed")
        and summary.get("unit_tests_passed")
        and summary.get("phase13b_unit_regression_passed")
    )
    summary["gate_a_passed"] = gate_a_passed
    summary["gate_a_permits_status"] = "Prepared"
    summary["gate_b_executed"] = False
    summary["gate_c_executed"] = False
    summary["gate_d_executed"] = False
    summary["status"] = STATUS_PREPARED if gate_a_passed else STATUS_BLOCKED
    summary["pc_environment"] = environment
    summary.update(BOUNDARY_FIELDS)

    evidence.write_json("summary.json", summary)
    evidence.write_json("environment.json", environment)
    evidence.write_json(
        "manifest.json",
        {
            "phase": PHASE,
            "gate": "A",
            "run_id": run_id,
            "status": summary["status"],
            "created_at_utc": utc_now_iso(),
            "evidence_dir": str(evidence.run_dir),
            "generated_evidence_git_policy": "ignored_local_only",
            "output_files": list(Phase13CEvidence.REQUIRED_FILES),
            **BOUNDARY_FIELDS,
        },
    )
    evidence.write_placeholders(
        [
            "model_manifest.json",
            "engine_manifest.json",
            "latency_metrics.json",
            "range_metrics.json",
            "parity_metrics.json",
            "jetson_metrics.json",
            "network_metrics.json",
        ],
        {"executed": False, "reason": "Gate A is local-only; no engine or Jetson involved"},
    )
    evidence.write_fault_matrix([])
    evidence.write_events([])
    evidence.write_text(
        "commands.txt", "# Phase 13C Gate A\n%s %s\n" % (sys.executable, " ".join(sys.argv))
    )
    evidence.write_text(
        "README.md",
        "# Phase 13C Gate A evidence\n\nRun id: `%s`\n\nStatus: `%s`\n\n"
        "Local-only source, unit and fail-closed checks. No TensorRT engine, no real "
        "Jetson and no CARLA were involved, so Gate A alone permits only `Prepared`.\n"
        % (run_id, summary["status"]),
    )

    print(summary["status"])
    print("run_id=%s" % run_id)
    print("evidence_dir=%s" % evidence.run_dir)
    for key in (
        "source_files_present",
        "python38_parse_passed",
        "unit_tests_passed",
        "phase13b_unit_regression_passed",
        "gate_a_passed",
    ):
        print("%s=%s" % (key, summary.get(key)))
    return 0 if gate_a_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
