"""
Phase 12C-R1-RT-DETR-UNLOCK optional backend readiness gate.

此 parent verifier 不匯入 CARLA，也不啟動 CARLA server。它只檢查
operator 提供的 RT-DETR dependency / weights contract、EdgePerception
no-fallback smoke，以及 Phase 12C RT-DETR-only scaffold rows。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "experiments" / "phase12"
DEFAULT_CARLA_ROOT = Path(r"D:\CARLA\packages\CARLA_0.9.16")
DEFAULT_CARLA_PYTHON = r"D:\CARLA\envs\ma-vlna-carla312\python.exe"
DEFAULT_LIGHTWEIGHT_EVIDENCE_DIR = Path(r"experiments\phase12\20260701T165325Z")
DEFAULT_LATENCY_OPT_EVIDENCE_DIR = Path(r"experiments\phase12\20260701T115744Z")

PHASE = "Phase 12C-R1-RT-DETR-UNLOCK"
STATUS_PASS = (
    "Phase 12C-R1-RT-DETR-UNLOCK Passed - RT-DETR optional backend verified "
    "with no fallback in the CARLA Python 3.12 runtime."
)
STATUS_BLOCKED = (
    "Phase 12C-R1-RT-DETR-UNLOCK Blocked - RT-DETR optional backend could not "
    "be verified because dependency or model assets are unavailable."
)
STATUS_PREPARED = (
    "Phase 12C-R1-RT-DETR-UNLOCK Prepared - RT-DETR unlock contract and "
    "verification commands are implemented, but no-fallback readiness has not yet passed."
)
RUNTIME_SCOPE = "rtdetr_optional_backend_unlock_no_fallback_readiness"

BOUNDARY_FIELDS = {
    "auto_install_performed": False,
    "baseline_requirements_modified": False,
    "carla_server_started": False,
    "runtime_confirmation_executed": False,
    "carla_route_runtime_executed": False,
    "rtdetr_runtime_verified": False,
    "rtdetr_accuracy_verified": False,
    "yolo_runtime_row_verified": False,
    "selected_route_completion_verified": False,
    "full_phase12c_perception_ablation_runtime_pass": False,
    "route_benchmark_verified": False,
    "infraction_benchmark_verified": False,
    "leaderboard_evaluated": False,
    "leaderboard_routes_exported": False,
    "leaderboard_route_criteria_evaluated": False,
}

SUMMARY_COLUMNS = (
    "phase",
    "status",
    "runtime_scope",
    "lightweight_evidence_dir",
    "latency_opt_evidence_dir",
    "route_id",
    "controller_mode",
    "previous_perception_backend",
    "target_perception_backend",
    "recommended_from_previous_phase",
    "ultralytics_import_ready",
    "ultralytics_version",
    "rtdetr_weights_configured",
    "rtdetr_weights_ready",
    "rtdetr_model_hint",
    "edge_rtdetr_backend_registered",
    "edge_rtdetr_command_supported",
    "edge_rtdetr_command_passed",
    "edge_rtdetr_fallback_used",
    "edge_rtdetr_no_fallback_verified",
    "phase12c_rtdetr_rows_available",
    "phase12c_rtdetr_backend_unavailable_count",
    "recommended_next_phase",
)


@dataclass(frozen=True)
class CommandResult:
    name: str
    command: list[str]
    exit_code: int
    duration_sec: float
    stdout_path: str
    stderr_path: str
    stdout_tail: str
    stderr_tail: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(now: datetime | None = None) -> str:
    return (now or _utc_now()).strftime("%Y%m%dT%H%M%SZ")


def _resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _next_run_dir(output_dir: Path, timestamp: str | None) -> Path:
    base = timestamp or _timestamp()
    candidate = output_dir / base
    suffix = 1
    while candidate.exists():
        candidate = output_dir / f"{base}-{suffix}"
        suffix += 1
    candidate.mkdir(parents=True, exist_ok=False)
    (candidate / "raw_outputs").mkdir(exist_ok=True)
    return candidate


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"json_read_error": f"file not found: {path}"}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"json_read_error": str(exc)}


def _write_csv(path: Path, summary: dict[str, Any]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_COLUMNS)
        writer.writeheader()
        writer.writerow({column: summary.get(column) for column in SUMMARY_COLUMNS})


def _tail(text: str, max_lines: int = 14) -> str:
    return "\n".join((text or "").splitlines()[-max_lines:])


def _command_text(command: list[str]) -> str:
    return subprocess.list2cmdline([str(part) for part in command])


def _run_command(
    *,
    name: str,
    command: list[str],
    raw_dir: Path,
    env: dict[str, str],
    timeout_sec: float,
) -> CommandResult:
    stdout_path = raw_dir / f"{name}.stdout.txt"
    stderr_path = raw_dir / f"{name}.stderr.txt"
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            check=False,
        )
        stdout = completed.stdout
        stderr = completed.stderr
        exit_code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        stderr = (stderr + f"\nTIMEOUT after {timeout_sec}s").strip()
        exit_code = 124
    except OSError as exc:
        stdout = ""
        stderr = f"OSERROR: {exc}"
        exit_code = 127
    stdout_path.write_text(stdout, encoding="utf-8", errors="replace")
    stderr_path.write_text(stderr, encoding="utf-8", errors="replace")
    return CommandResult(
        name=name,
        command=command,
        exit_code=exit_code,
        duration_sec=round(time.perf_counter() - started, 3),
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        stdout_tail=_tail(stdout),
        stderr_tail=_tail(stderr),
    )


def _result_payload(result: CommandResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return {
        "name": result.name,
        "command": _command_text(result.command),
        "exit_code": result.exit_code,
        "duration_sec": result.duration_sec,
        "stdout_path": result.stdout_path,
        "stderr_path": result.stderr_path,
        "stdout_tail": result.stdout_tail,
        "stderr_tail": result.stderr_tail,
    }


def _parse_key_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key and all(ch.isalnum() or ch == "_" for ch in key):
            values[key] = value.strip()
    return values


def _bool_value(values: dict[str, str], key: str) -> bool:
    return values.get(key, "").lower() == "true"


def _env_with_runtime_contract(args: argparse.Namespace) -> dict[str, str]:
    env = os.environ.copy()
    env["CARLA_ROOT"] = str(args.carla_root)
    env["PYTHONIOENCODING"] = "utf-8"
    if args.rtdetr_weights:
        env["RTDETR_WEIGHTS"] = args.rtdetr_weights
    if args.rtdetr_model_hint:
        env["RTDETR_MODEL_HINT"] = args.rtdetr_model_hint
    if args.rtdetr_device:
        env["RTDETR_DEVICE"] = args.rtdetr_device
    if args.rtdetr_img_size:
        env["RTDETR_IMG_SIZE"] = str(args.rtdetr_img_size)
    return env


def _rtdetr_contract(args: argparse.Namespace, env: dict[str, str]) -> dict[str, Any]:
    weights_value = args.rtdetr_weights or env.get("RTDETR_WEIGHTS")
    weights = Path(weights_value).expanduser() if weights_value else None
    return {
        "rtdetr_weights_configured": bool(weights_value),
        "rtdetr_weights": str(weights) if weights else None,
        "rtdetr_weights_ready": bool(weights and weights.is_file()),
        "rtdetr_model_hint": args.rtdetr_model_hint or env.get("RTDETR_MODEL_HINT") or "rtdetr-l.pt",
        "rtdetr_device": args.rtdetr_device or env.get("RTDETR_DEVICE") or "auto",
        "rtdetr_img_size": args.rtdetr_img_size or (int(env["RTDETR_IMG_SIZE"]) if env.get("RTDETR_IMG_SIZE") else None),
    }


def _ultralytics_probe(args: argparse.Namespace, raw_dir: Path, env: dict[str, str]) -> tuple[CommandResult, bool, str | None]:
    result = _run_command(
        name="target_ultralytics_import_probe",
        command=[
            args.python_executable,
            "-c",
            "import ultralytics; print(getattr(ultralytics, '__version__', 'unknown'))",
        ],
        raw_dir=raw_dir,
        env=env,
        timeout_sec=args.probe_timeout_sec,
    )
    version = None
    if result.ok:
        stdout = Path(result.stdout_path).read_text(encoding="utf-8", errors="replace")
        version = (stdout.strip().splitlines() or [None])[-1]
    return result, result.ok, version


def _edge_probe(args: argparse.Namespace, raw_dir: Path, env: dict[str, str]) -> tuple[CommandResult, dict[str, str]]:
    command = [
        args.python_executable,
        "-m",
        "workers.core.edge_perception",
        "--test",
        "rtdetr",
        "--rtdetr-model-hint",
        args.rtdetr_model_hint,
        "--rtdetr-device",
        args.rtdetr_device,
    ]
    if args.rtdetr_weights:
        command.extend(["--rtdetr-weights", args.rtdetr_weights])
    if args.rtdetr_img_size:
        command.extend(["--rtdetr-img-size", str(args.rtdetr_img_size)])
    result = _run_command(
        name="edge_rtdetr_no_fallback_probe",
        command=command,
        raw_dir=raw_dir,
        env=env,
        timeout_sec=args.edge_probe_timeout_sec,
    )
    stdout = Path(result.stdout_path).read_text(encoding="utf-8", errors="replace")
    stderr = Path(result.stderr_path).read_text(encoding="utf-8", errors="replace")
    return result, _parse_key_values(stdout + "\n" + stderr)


def _rows_refresh(args: argparse.Namespace, raw_dir: Path, env: dict[str, str], run_dir: Path) -> tuple[CommandResult, str | None, dict[str, Any]]:
    result = _run_command(
        name="phase12c_rtdetr_rows_refresh",
        command=[
            args.base_python,
            str(REPO_ROOT / "scripts" / "run_phase12c_perception_backend_ablation.py"),
            "--perception-backend-mode",
            "rt_detr_optional",
            "--python-executable",
            args.python_executable,
            "--output-dir",
            str(run_dir / "rows_refresh"),
            "--carla-root",
            str(args.carla_root),
        ],
        raw_dir=raw_dir,
        env=env,
        timeout_sec=args.rows_timeout_sec,
    )
    stdout = Path(result.stdout_path).read_text(encoding="utf-8", errors="replace")
    experiment_dir = None
    for line in stdout.splitlines():
        if line.strip().startswith("experiment_dir="):
            experiment_dir = line.split("=", 1)[1].strip()
            break
    summary = _read_json(Path(experiment_dir) / "summary.json") if experiment_dir else {}
    if experiment_dir:
        source_dir = Path(experiment_dir)
        if (source_dir / "summary.json").exists():
            shutil.copyfile(source_dir / "summary.json", run_dir / "rtdetr_rows_summary.json")
        if (source_dir / "summary.csv").exists():
            shutil.copyfile(source_dir / "summary.csv", run_dir / "rtdetr_rows_summary.csv")
    return result, experiment_dir, summary


def _recommend_next_phase(
    *,
    passed: bool,
    ultralytics_ready: bool,
    weights_ready: bool,
    fallback_used: bool | None,
) -> str:
    if passed:
        return "R1-RT-DETR-SHORT"
    if not ultralytics_ready or not weights_ready:
        return "R1-RT-DETR-ASSET-SETUP"
    if fallback_used:
        return "R1-RT-DETR-ADAPTER-FIX"
    return "BLOCKED"


def _build_summary(
    *,
    args: argparse.Namespace,
    run_dir: Path,
    contract: dict[str, Any],
    ultralytics_ready: bool,
    ultralytics_version: str | None,
    edge_values: dict[str, str],
    rows_summary: dict[str, Any],
    command_results: dict[str, CommandResult | None],
    rows_experiment_dir: str | None,
) -> dict[str, Any]:
    edge_command_passed = (
        command_results.get("edge_rtdetr") is not None
        and command_results["edge_rtdetr"].ok
        and _bool_value(edge_values, "edge_rtdetr_command_passed")
    )
    edge_fallback_value = edge_values.get("edge_rtdetr_fallback_used")
    edge_fallback_used = None if edge_fallback_value is None else edge_fallback_value.lower() == "true"
    edge_no_fallback = edge_command_passed and _bool_value(edge_values, "edge_rtdetr_no_fallback_verified")
    rtdetr_rows_available = rows_summary.get("available_row_count") == 5 and rows_summary.get("rtdetr_no_fallback_verified") is True
    backend_unavailable_count = rows_summary.get("backend_unavailable_count")
    passed = (
        ultralytics_ready
        and contract["rtdetr_weights_ready"]
        and edge_command_passed
        and edge_fallback_used is False
        and edge_no_fallback
        and rtdetr_rows_available
        and backend_unavailable_count == 0
    )
    if args.dry_run:
        status = STATUS_PREPARED
    else:
        status = STATUS_PASS if passed else STATUS_BLOCKED
    recommended_next_phase = _recommend_next_phase(
        passed=passed,
        ultralytics_ready=ultralytics_ready,
        weights_ready=contract["rtdetr_weights_ready"],
        fallback_used=edge_fallback_used,
    )
    blocked_reasons: list[str] = []
    if not args.dry_run:
        if not Path(args.python_executable).exists():
            blocked_reasons.append("target_python_missing")
        if not args.carla_root.exists():
            blocked_reasons.append("carla_root_missing")
        if not ultralytics_ready:
            blocked_reasons.append("dependency_missing")
        if not contract["rtdetr_weights_ready"]:
            blocked_reasons.append("weights_missing")
        if not edge_command_passed:
            blocked_reasons.append("edge_command_failed")
        if edge_fallback_used:
            blocked_reasons.append("fallback_used")
        if not rtdetr_rows_available:
            blocked_reasons.append("rtdetr_rows_unavailable")
    return {
        "phase": PHASE,
        "status": status,
        "dry_run": args.dry_run,
        "run_dir": str(run_dir),
        "runtime_scope": RUNTIME_SCOPE,
        "lightweight_evidence_dir": _display_path(args.lightweight_evidence_dir),
        "latency_opt_evidence_dir": _display_path(args.latency_opt_evidence_dir),
        "route_id": "route_01",
        "controller_mode": "grp_follower",
        "previous_perception_backend": "yolov9",
        "target_perception_backend": "rtdetr",
        "recommended_from_previous_phase": "R1-RT-DETR-UNLOCK",
        "target_python": args.python_executable,
        "target_python_exists": Path(args.python_executable).exists(),
        "base_python": args.base_python,
        "carla_root": str(args.carla_root),
        "carla_root_exists": args.carla_root.exists(),
        "ultralytics_import_ready": ultralytics_ready,
        "ultralytics_version": ultralytics_version,
        **contract,
        "edge_rtdetr_backend_registered": _bool_value(edge_values, "rtdetr_backend_registered"),
        "edge_rtdetr_command_supported": _bool_value(edge_values, "edge_rtdetr_command_supported"),
        "edge_rtdetr_command_passed": edge_command_passed,
        "edge_rtdetr_fallback_used": edge_fallback_used,
        "edge_rtdetr_no_fallback_verified": edge_no_fallback,
        "edge_probe_values": edge_values,
        "phase12c_rtdetr_rows_available": rtdetr_rows_available,
        "phase12c_rtdetr_backend_unavailable_count": int(backend_unavailable_count or 0),
        "phase12c_rtdetr_rows_experiment_dir": rows_experiment_dir,
        "recommended_next_phase": recommended_next_phase,
        "blocked_reason": "; ".join(blocked_reasons) if blocked_reasons else None,
        "command_results": {name: _result_payload(result) for name, result in command_results.items()},
        "rtdetr_rows_summary": rows_summary,
        "assertions": {
            "no_carla_import_in_parent": True,
            "carla_route_runtime_not_started": True,
            "weights_not_committed": True,
            "baseline_requirements_not_modified": True,
            "passed_requires_no_fallback": passed is True,
            "all_boundary_fields_false": all(value is False for value in BOUNDARY_FIELDS.values()),
        },
        **BOUNDARY_FIELDS,
    }


def _write_commands(path: Path, args: argparse.Namespace) -> None:
    lines = [
        "# Phase 12C-R1-RT-DETR-UNLOCK commands",
        "",
        "# Dry-run / scaffold",
        "python scripts\\run_phase12c_rtdetr_unlock_verification.py --dry-run --output-dir experiments\\phase12",
        "",
        "# Optional RT-DETR operator assets",
        '$env:RTDETR_WEIGHTS = "D:\\AIModels\\rtdetr\\rtdetr-l.pt"',
        '$env:RTDETR_MODEL_HINT = "rtdetr-l.pt"',
        '$env:RTDETR_DEVICE = "auto"',
        "",
        "# Strict verification",
        _command_text(
            [
                args.python_executable,
                str(REPO_ROOT / "scripts" / "run_phase12c_rtdetr_unlock_verification.py"),
                "--python-executable",
                args.python_executable,
                "--base-python",
                args.base_python,
                "--carla-root",
                str(args.carla_root),
                "--output-dir",
                "experiments\\phase12",
                "--require-verified",
            ]
        ),
        "",
        "# RT-DETR-only row refresh",
        _command_text(
            [
                args.base_python,
                str(REPO_ROOT / "scripts" / "run_phase12c_perception_backend_ablation.py"),
                "--perception-backend-mode",
                "rt_detr_optional",
                "--python-executable",
                args.python_executable,
                "--output-dir",
                "experiments\\phase12",
            ]
        ),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_manifest(path: Path, summary: dict[str, Any]) -> None:
    _write_json(
        path,
        {
            "phase": PHASE,
            "status": summary["status"],
            "created_at_utc": _utc_now().isoformat(),
            "run_dir": summary["run_dir"],
            "output_files": [
                "manifest.json",
                "summary.json",
                "summary.csv",
                "commands.txt",
                "environment.json",
                "README.md",
                "raw_outputs/",
                "rtdetr_rows_summary.json",
                "rtdetr_rows_summary.csv",
            ],
            "raw_runtime_evidence_committed": False,
            **BOUNDARY_FIELDS,
        },
    )


def _write_environment(path: Path, args: argparse.Namespace, summary: dict[str, Any]) -> None:
    _write_json(
        path,
        {
            "python": sys.version,
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "target_python": args.python_executable,
            "target_python_exists": summary["target_python_exists"],
            "base_python": args.base_python,
            "carla_root": str(args.carla_root),
            "carla_root_exists": summary["carla_root_exists"],
            "RTDETR_WEIGHTS_configured": summary["rtdetr_weights_configured"],
            "RTDETR_WEIGHTS_ready": summary["rtdetr_weights_ready"],
            "RTDETR_MODEL_HINT": summary["rtdetr_model_hint"],
            "RTDETR_DEVICE": summary["rtdetr_device"],
            "RTDETR_IMG_SIZE": summary["rtdetr_img_size"],
            "ultralytics_import_ready": summary["ultralytics_import_ready"],
            "ultralytics_version": summary["ultralytics_version"],
        },
    )


def _write_readme(path: Path, summary: dict[str, Any]) -> None:
    body = f"""# Phase 12C-R1-RT-DETR-UNLOCK

Status:

```text
{summary["status"]}
```

```text
runtime_scope={summary["runtime_scope"]}
lightweight_evidence_dir={summary["lightweight_evidence_dir"]}
target_perception_backend={summary["target_perception_backend"]}
ultralytics_import_ready={str(summary["ultralytics_import_ready"]).lower()}
rtdetr_weights_configured={str(summary["rtdetr_weights_configured"]).lower()}
rtdetr_weights_ready={str(summary["rtdetr_weights_ready"]).lower()}
edge_rtdetr_command_passed={str(summary["edge_rtdetr_command_passed"]).lower()}
edge_rtdetr_fallback_used={str(summary["edge_rtdetr_fallback_used"]).lower()}
edge_rtdetr_no_fallback_verified={str(summary["edge_rtdetr_no_fallback_verified"]).lower()}
phase12c_rtdetr_rows_available={str(summary["phase12c_rtdetr_rows_available"]).lower()}
phase12c_rtdetr_backend_unavailable_count={summary["phase12c_rtdetr_backend_unavailable_count"]}
recommended_next_phase={summary["recommended_next_phase"]}
```

Boundary: this phase does not start CARLA route runtime, does not claim
RT-DETR accuracy, and does not claim full Phase 12C ablation, Leaderboard,
formal route benchmark, or infraction benchmark results.
"""
    path.write_text(body, encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify Phase 12C RT-DETR no-fallback backend readiness")
    parser.add_argument("--python-executable", default=DEFAULT_CARLA_PYTHON)
    parser.add_argument("--base-python", default="python")
    parser.add_argument("--carla-root", type=Path, default=DEFAULT_CARLA_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timestamp", default=None)
    parser.add_argument("--lightweight-evidence-dir", type=Path, default=DEFAULT_LIGHTWEIGHT_EVIDENCE_DIR)
    parser.add_argument("--latency-opt-evidence-dir", type=Path, default=DEFAULT_LATENCY_OPT_EVIDENCE_DIR)
    parser.add_argument("--rtdetr-weights", default=os.getenv("RTDETR_WEIGHTS"))
    parser.add_argument("--rtdetr-model-hint", default=os.getenv("RTDETR_MODEL_HINT", "rtdetr-l.pt"))
    parser.add_argument("--rtdetr-device", default=os.getenv("RTDETR_DEVICE", "auto"))
    parser.add_argument("--rtdetr-img-size", type=int, default=int(os.getenv("RTDETR_IMG_SIZE", "0") or 0))
    parser.add_argument("--probe-timeout-sec", type=float, default=120.0)
    parser.add_argument("--edge-probe-timeout-sec", type=float, default=240.0)
    parser.add_argument("--rows-timeout-sec", type=float, default=300.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--require-verified", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    args.output_dir = _resolve_repo_path(args.output_dir)
    args.carla_root = _resolve_repo_path(args.carla_root)
    args.lightweight_evidence_dir = _resolve_repo_path(args.lightweight_evidence_dir)
    args.latency_opt_evidence_dir = _resolve_repo_path(args.latency_opt_evidence_dir)

    run_dir = _next_run_dir(args.output_dir, args.timestamp)
    raw_dir = run_dir / "raw_outputs"
    env = _env_with_runtime_contract(args)
    contract = _rtdetr_contract(args, env)

    command_results: dict[str, CommandResult | None] = {
        "ultralytics_import": None,
        "edge_rtdetr": None,
        "rtdetr_rows_refresh": None,
    }
    ultralytics_ready = False
    ultralytics_version = None
    edge_values: dict[str, str] = {}
    rows_summary: dict[str, Any] = {}
    rows_experiment_dir: str | None = None

    if args.dry_run:
        edge_values = {
            "rtdetr_backend_registered": "true",
            "edge_rtdetr_command_supported": "true",
            "edge_rtdetr_command_passed": "false",
            "edge_rtdetr_fallback_used": "true",
            "edge_rtdetr_no_fallback_verified": "false",
        }
        rows_summary = {
            "row_count": 5,
            "available_row_count": 0,
            "backend_unavailable_count": 5,
            "rtdetr_no_fallback_verified": False,
        }
    else:
        import_result, ultralytics_ready, ultralytics_version = _ultralytics_probe(args, raw_dir, env)
        command_results["ultralytics_import"] = import_result
        edge_result, edge_values = _edge_probe(args, raw_dir, env)
        command_results["edge_rtdetr"] = edge_result
        rows_result, rows_experiment_dir, rows_summary = _rows_refresh(args, raw_dir, env, run_dir)
        command_results["rtdetr_rows_refresh"] = rows_result

    summary = _build_summary(
        args=args,
        run_dir=run_dir,
        contract=contract,
        ultralytics_ready=ultralytics_ready,
        ultralytics_version=ultralytics_version,
        edge_values=edge_values,
        rows_summary=rows_summary,
        command_results=command_results,
        rows_experiment_dir=rows_experiment_dir,
    )
    _write_json(run_dir / "summary.json", summary)
    _write_csv(run_dir / "summary.csv", summary)
    _write_manifest(run_dir / "manifest.json", summary)
    _write_environment(run_dir / "environment.json", args, summary)
    _write_commands(run_dir / "commands.txt", args)
    _write_readme(run_dir / "README.md", summary)

    print(f"experiment_dir={run_dir}")
    print(summary["status"])
    if summary.get("blocked_reason"):
        print(f"blocked_reason={summary['blocked_reason']}")
    if args.dry_run:
        return 0
    if summary["status"] == STATUS_PASS:
        return 0
    return 1 if args.require_verified else 0


if __name__ == "__main__":
    raise SystemExit(main())
