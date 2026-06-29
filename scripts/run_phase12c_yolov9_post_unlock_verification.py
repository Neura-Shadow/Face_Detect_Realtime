"""
Phase 12C-YOLOv9-V post-unlock verification gate.

This runner verifies the operator-managed YOLOv9 unlock after dependencies or
the official external YOLOv9 source-root contract have been prepared in the
dedicated CARLA Python 3.12 runtime. It never installs packages, never edits
baseline requirements, never starts CARLA, and never claims CARLA Leaderboard /
route benchmark / infraction benchmark status.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = REPO_ROOT / "experiments" / "phase12"
DEFAULT_CARLA_PYTHON = r"D:\CARLA\envs\ma-vlna-carla312\python.exe"
DEFAULT_CARLA_ROOT = Path(r"D:\CARLA\packages\CARLA_0.9.16")
DEFAULT_DEPENDENCY_MODULE = "yolov9"
DEFAULT_PIP_PACKAGE = "yolov9"
EXPECTED_SOURCE_ENTRIES = ("detect.py", "detect_dual.py", "models", "utils")

PHASE = "Phase 12C-YOLOv9-V"
STATUS_VERIFIED = "yolov9_post_unlock_verified"
STATUS_BLOCKED = "yolov9_post_unlock_blocked"
BENCHMARK_BOUNDARY_SCOPE = "yolov9_post_unlock_verification_not_runtime_benchmark"

BOUNDARY_FIELDS = {
    "route_benchmark_verified": False,
    "infraction_benchmark_verified": False,
    "leaderboard_evaluated": False,
    "leaderboard_routes_exported": False,
    "leaderboard_route_criteria_evaluated": False,
}


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


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(now: datetime) -> str:
    return now.strftime("%Y%m%dT%H%M%SZ")


def _resolve_repo_path(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def _next_run_dir(output_dir: Path, timestamp: str | None) -> Path:
    base = timestamp or _timestamp(_utc_now())
    candidate = output_dir / base
    suffix = 1
    while candidate.exists():
        candidate = output_dir / f"{base}-{suffix}"
        suffix += 1
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _quote_powershell_arg(arg: str) -> str:
    if arg == "":
        return '""'
    if any(ch.isspace() or ch in '<>&|()' for ch in arg):
        return '"' + arg.replace("`", "``").replace('"', '`"') + '"'
    return arg


def _command_text(command: list[str]) -> str:
    return " ".join(_quote_powershell_arg(str(part)) for part in command)


def _tail(text: str, max_lines: int = 12) -> str:
    return "\n".join(text.splitlines()[-max_lines:])


def _run_command(
    *,
    name: str,
    command: list[str],
    raw_dir: Path,
    timeout_sec: float,
    env: dict[str, str],
) -> CommandResult:
    raw_dir.mkdir(parents=True, exist_ok=True)
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
        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        stdout_path.write_text(stdout, encoding="utf-8", errors="replace")
        stderr_path.write_text(stderr, encoding="utf-8", errors="replace")
        return CommandResult(
            name=name,
            command=command,
            exit_code=completed.returncode,
            duration_sec=round(time.perf_counter() - started, 3),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            stdout_tail=_tail(stdout),
            stderr_tail=_tail(stderr),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        timeout_stderr = stderr.strip() or f"timeout after {timeout_sec}s"
        stdout_path.write_text(stdout.strip(), encoding="utf-8", errors="replace")
        stderr_path.write_text(timeout_stderr, encoding="utf-8", errors="replace")
        return CommandResult(
            name=name,
            command=command,
            exit_code=124,
            duration_sec=round(time.perf_counter() - started, 3),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            stdout_tail=_tail(stdout),
            stderr_tail=_tail(timeout_stderr),
        )
    except OSError as exc:
        stderr = str(exc)
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8", errors="replace")
        return CommandResult(
            name=name,
            command=command,
            exit_code=127,
            duration_sec=round(time.perf_counter() - started, 3),
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            stdout_tail="",
            stderr_tail=stderr,
        )


def _result_payload(result: CommandResult) -> dict[str, Any]:
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


def _import_check_command(args: argparse.Namespace) -> list[str]:
    code = (
        "import importlib.util; "
        f"module={args.dependency_module!r}; "
        "available = importlib.util.find_spec(module) is not None; "
        "print(f'yolov9_import_ready={available}'); "
        "raise SystemExit(0 if available else 1)"
    )
    return [args.python_executable, "-c", code]


def _pip_show_command(args: argparse.Namespace) -> list[str]:
    return [args.python_executable, "-m", "pip", "show", args.pip_package]


def _edge_yolov9_command(args: argparse.Namespace) -> list[str]:
    return [args.python_executable, "-m", "workers.core.edge_perception", "--test", "yolov9"]


def _parser_probe_command(module_name: str) -> list[str]:
    code = (
        f"from {module_name} import _build_parser; "
        "_build_parser().parse_args(['--perception-backend', 'yolov9']); "
        f"print('{module_name}_yolov9_cli_ready=True')"
    )
    return [sys.executable, "-c", code]


def _phase12c_refresh_command(args: argparse.Namespace) -> list[str]:
    return [
        args.base_python,
        str(REPO_ROOT / "scripts" / "run_phase12c_perception_backend_ablation.py"),
        "--perception-backend-mode",
        "yolov9_optional",
        "--output-dir",
        str(args.output_dir),
        "--python-executable",
        args.python_executable,
        "--base-python",
        args.base_python,
        "--carla-root",
        str(args.carla_root),
    ]


def _phase12b_dry_run_command(args: argparse.Namespace) -> list[str]:
    return [
        args.base_python,
        str(REPO_ROOT / "scripts" / "run_phase12b_controller_ablation_experiment.py"),
        "--dry-run",
        "--route-id",
        "route_01",
        "--controller-mode",
        "grp_follower",
        "--perception-backend",
        "yolov9",
        "--output-dir",
        str(args.output_dir),
        "--python-executable",
        args.python_executable,
        "--base-python",
        args.base_python,
        "--carla-root",
        str(args.carla_root),
    ]


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


def _edge_key_values(edge_result: CommandResult) -> dict[str, str]:
    stdout = Path(edge_result.stdout_path).read_text(encoding="utf-8", errors="replace")
    stderr = Path(edge_result.stderr_path).read_text(encoding="utf-8", errors="replace")
    return _parse_key_values(stdout + "\n" + stderr)


def _edge_fallback_used(edge_result: CommandResult) -> bool:
    values = _edge_key_values(edge_result)
    if "edge_yolov9_fallback_used" in values:
        return values["edge_yolov9_fallback_used"].lower() == "true"
    text = f"{edge_result.stdout_tail}\n{edge_result.stderr_tail}".lower()
    return "fallback used: true" in text or "graceful fallback" in text


def _source_contract(args: argparse.Namespace) -> dict[str, Any]:
    source_root_value = os.getenv(args.source_root_env)
    weights_value = os.getenv(args.weights_env)
    source_root = Path(source_root_value).expanduser() if source_root_value else None
    weights = Path(weights_value).expanduser() if weights_value else None
    source_root_ready = bool(source_root and source_root.exists() and source_root.is_dir())
    weights_ready = bool(weights and weights.exists() and weights.is_file())
    missing_entries: list[str] = []
    if source_root_ready and source_root is not None:
        missing_entries = [entry for entry in EXPECTED_SOURCE_ENTRIES if not (source_root / entry).exists()]
    elif source_root_value:
        missing_entries = list(EXPECTED_SOURCE_ENTRIES)
    return {
        "source_root_env": args.source_root_env,
        "weights_env": args.weights_env,
        "yolov9_source_root": str(source_root.resolve()) if source_root and source_root.exists() else (str(source_root) if source_root else None),
        "yolov9_weights": str(weights.resolve()) if weights and weights.exists() else (str(weights) if weights else None),
        "yolov9_source_root_configured": bool(source_root_value),
        "yolov9_weights_configured": bool(weights_value),
        "yolov9_source_root_ready": source_root_ready,
        "yolov9_weights_ready": weights_ready,
        "yolov9_expected_source_files_ready": source_root_ready and not missing_entries,
        "yolov9_missing_source_entries": missing_entries,
    }


def _extract_experiment_dir(result: CommandResult) -> str | None:
    for line in result.stdout_tail.splitlines():
        if line.startswith("experiment_dir="):
            return line.split("=", 1)[1].strip()
    return None


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"json_read_error": f"file not found: {path}"}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"json_read_error": str(exc)}


def _phase12c_yolov9_rows_available(result: CommandResult) -> tuple[bool, int | None, str | None]:
    run_dir_text = _extract_experiment_dir(result)
    if not run_dir_text:
        return False, None, None
    run_dir = Path(run_dir_text)
    summary = _read_json(run_dir / "summary.json")
    rows = [
        row for row in summary.get("results", [])
        if row.get("perception_backend_mode") == "yolov9_optional"
    ]
    if not rows:
        return False, summary.get("backend_unavailable_count"), run_dir_text
    rows_available = all(row.get("backend_available") is True for row in rows)
    unavailable_count = sum(1 for row in rows if row.get("result") == "backend_unavailable")
    return rows_available, unavailable_count, run_dir_text


def _build_summary(
    *,
    args: argparse.Namespace,
    run_dir: Path,
    results: list[CommandResult],
) -> dict[str, Any]:
    by_name = {result.name: result for result in results}
    import_ready = by_name["carla312_import_yolov9_dependency"].exit_code == 0
    pip_ready = by_name["carla312_pip_show_yolov9_dependency"].exit_code == 0
    edge_result = by_name["carla312_edge_yolov9_no_fallback_probe"]
    edge_values = _edge_key_values(edge_result)
    edge_passed = edge_result.exit_code == 0
    edge_fallback = _edge_fallback_used(edge_result)
    edge_no_fallback = edge_passed and edge_values.get("edge_yolov9_no_fallback_verified", str(not edge_fallback)).lower() == "true" and not edge_fallback
    phase12b_cli_ready = by_name["phase12b_yolov9_dry_run_command_probe"].exit_code == 0
    phase11m_cli_ready = by_name["phase11m_yolov9_cli_parser_probe"].exit_code == 0
    phase11k_cli_ready = by_name["phase11k_yolov9_cli_parser_probe"].exit_code == 0
    baseline_cli_ready = by_name["phase12b_baseline_yolov9_cli_parser_probe"].exit_code == 0
    phase12c_rows_available, phase12c_unavailable_count, phase12c_run_dir = _phase12c_yolov9_rows_available(
        by_name["phase12c_yolov9_rows_refresh"]
    )
    source_contract = _source_contract(args)
    source_adapter_verified = all(
        [
            source_contract["yolov9_source_root_configured"],
            source_contract["yolov9_weights_configured"],
            source_contract["yolov9_source_root_ready"],
            source_contract["yolov9_expected_source_files_ready"],
            source_contract["yolov9_weights_ready"],
            edge_passed,
            not edge_fallback,
            edge_no_fallback,
        ]
    )
    dependency_ready = (
        import_ready and pip_ready
        if args.unlock_mode == "package"
        else source_adapter_verified
    )
    post_unlock_verified = all(
        [
            Path(args.python_executable).exists(),
            dependency_ready,
            edge_passed,
            not edge_fallback,
            phase12b_cli_ready,
            phase11m_cli_ready,
            phase11k_cli_ready,
            baseline_cli_ready,
            phase12c_rows_available,
        ]
    )
    assertions = {
        "target_python_exists": Path(args.python_executable).exists(),
        "carla_root_exists": args.carla_root.exists(),
        "unlock_mode": args.unlock_mode,
        "yolov9_import_ready": import_ready,
        "yolov9_pip_metadata_ready": pip_ready,
        "source_adapter_verified": source_adapter_verified,
        "edge_yolov9_command_passed": edge_passed,
        "edge_yolov9_fallback_used": edge_fallback,
        "edge_yolov9_no_fallback_verified": edge_no_fallback,
        "phase12b_yolov9_dry_run_command_ready": phase12b_cli_ready,
        "phase11m_yolov9_cli_ready": phase11m_cli_ready,
        "phase11k_yolov9_cli_ready": phase11k_cli_ready,
        "phase12b_baseline_yolov9_cli_ready": baseline_cli_ready,
        "phase12c_yolov9_rows_available": phase12c_rows_available,
        "auto_install_performed": False,
        "baseline_requirements_modified": False,
        "carla_server_started": False,
        "runtime_confirmation_executed": False,
        "all_boundary_fields_false": all(value is False for value in BOUNDARY_FIELDS.values()),
    }
    return {
        "phase": PHASE,
        "status": STATUS_VERIFIED if post_unlock_verified else STATUS_BLOCKED,
        "unlock_mode": args.unlock_mode,
        "post_unlock_verification_attempted": True,
        "post_unlock_verified": post_unlock_verified,
        "require_verified_requested": args.require_verified,
        "strict_gate_exit_code": 0 if post_unlock_verified or not args.require_verified else 1,
        "target_python": args.python_executable,
        "target_python_exists": Path(args.python_executable).exists(),
        "carla_root": str(args.carla_root),
        "carla_root_exists": args.carla_root.exists(),
        "dependency_module": args.dependency_module,
        "pip_package": args.pip_package,
        "perception_backend": "yolov9",
        "perception_backend_mode": "yolov9_optional",
        "dependency_ready": dependency_ready,
        "dependency_missing": not dependency_ready,
        "yolov9_import_ready": import_ready,
        "yolov9_pip_metadata_ready": pip_ready,
        "source_adapter_verified": source_adapter_verified,
        **source_contract,
        "edge_yolov9_command_passed": edge_passed,
        "edge_yolov9_fallback_used": edge_fallback,
        "edge_yolov9_no_fallback_verified": edge_no_fallback,
        "phase12b_yolov9_dry_run_command_ready": phase12b_cli_ready,
        "phase11m_yolov9_cli_ready": phase11m_cli_ready,
        "phase11k_yolov9_cli_ready": phase11k_cli_ready,
        "phase12b_baseline_yolov9_cli_ready": baseline_cli_ready,
        "phase12c_yolov9_rows_available": phase12c_rows_available,
        "phase12c_yolov9_backend_unavailable_count": phase12c_unavailable_count,
        "phase12c_refresh_evidence_dir": phase12c_run_dir,
        "auto_install_performed": False,
        "baseline_requirements_modified": False,
        "carla_server_started": False,
        "runtime_confirmation_executed": False,
        "run_dir": str(run_dir),
        "preflight_results": [_result_payload(result) for result in results],
        "assertions": assertions,
        "blocked_reason": None
        if post_unlock_verified
        else "YOLOv9 package-mode dependency or external-source no-fallback readiness is not verified in the target CARLA Python environment.",
        "benchmark_boundary_prepared": True,
        "benchmark_boundary_scope": BENCHMARK_BOUNDARY_SCOPE,
        **BOUNDARY_FIELDS,
        "benchmark_boundaries": dict(BOUNDARY_FIELDS),
    }


def _write_commands(path: Path, args: argparse.Namespace) -> None:
    commands = [
        ("verify_import", _import_check_command(args)),
        ("verify_pip_show", _pip_show_command(args)),
        ("verify_edge_yolov9_no_fallback", _edge_yolov9_command(args)),
        ("verify_phase12b_yolov9_dry_run", _phase12b_dry_run_command(args)),
        ("refresh_phase12c_yolov9_rows", _phase12c_refresh_command(args)),
    ]
    lines = [
        "# Phase 12C-YOLOv9-V parent command",
        _command_text([sys.executable, *sys.argv]),
        "",
        "# Post-unlock verification commands",
    ]
    for name, command in commands:
        lines.append(f"# {name}")
        lines.append(_command_text(command))
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_environment(path: Path, args: argparse.Namespace) -> None:
    _write_json(
        path,
        {
            "python": sys.version,
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "base_python": args.base_python,
            "target_python": args.python_executable,
            "target_python_exists": Path(args.python_executable).exists(),
            "carla_root": str(args.carla_root),
            "carla_root_exists": args.carla_root.exists(),
            "dependency_module": args.dependency_module,
            "pip_package": args.pip_package,
            "unlock_mode": args.unlock_mode,
            "source_root_env": args.source_root_env,
            "weights_env": args.weights_env,
        },
    )


def _write_readme(path: Path, summary: dict[str, Any]) -> None:
    body = f"""# Phase 12C-YOLOv9-V YOLOv9 Post-Unlock Verification

Status:

```text
{summary["status"]}
```

```text
unlock_mode={summary["unlock_mode"]}
post_unlock_verified={str(summary["post_unlock_verified"]).lower()}
require_verified_requested={str(summary["require_verified_requested"]).lower()}
strict_gate_exit_code={summary["strict_gate_exit_code"]}
yolov9_import_ready={str(summary["yolov9_import_ready"]).lower()}
yolov9_pip_metadata_ready={str(summary["yolov9_pip_metadata_ready"]).lower()}
source_adapter_verified={str(summary["source_adapter_verified"]).lower()}
yolov9_source_root_configured={str(summary["yolov9_source_root_configured"]).lower()}
yolov9_weights_configured={str(summary["yolov9_weights_configured"]).lower()}
edge_yolov9_command_passed={str(summary["edge_yolov9_command_passed"]).lower()}
edge_yolov9_fallback_used={str(summary["edge_yolov9_fallback_used"]).lower()}
phase12c_yolov9_rows_available={str(summary["phase12c_yolov9_rows_available"]).lower()}
auto_install_performed=false
baseline_requirements_modified=false
carla_server_started=false
runtime_confirmation_executed=false
```

This gate verifies the YOLOv9 unlock after the operator has prepared either
package mode or the official external source-root mode in the CARLA Python 3.12
runtime. A blocked result means the environment is not unlocked yet; it is not
converted into a runtime pass.
"""
    path.write_text(body, encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify Phase 12C-YOLOv9-V post-unlock readiness")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timestamp", default=None)
    parser.add_argument("--carla-root", type=Path, default=DEFAULT_CARLA_ROOT)
    parser.add_argument("--python-executable", default=DEFAULT_CARLA_PYTHON)
    parser.add_argument("--base-python", default="python")
    parser.add_argument("--dependency-module", default=DEFAULT_DEPENDENCY_MODULE)
    parser.add_argument("--pip-package", default=DEFAULT_PIP_PACKAGE)
    parser.add_argument("--unlock-mode", choices=["external_source", "package"], default="external_source")
    parser.add_argument("--source-root-env", default="YOLOV9_ROOT")
    parser.add_argument("--weights-env", default="YOLOV9_WEIGHTS")
    parser.add_argument("--timeout-sec", type=float, default=120.0)
    parser.add_argument("--require-verified", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    args.output_dir = _resolve_repo_path(args.output_dir)
    args.carla_root = _resolve_repo_path(args.carla_root)
    run_dir = _next_run_dir(args.output_dir, args.timestamp)
    raw_dir = run_dir / "raw_outputs"
    env = os.environ.copy()
    env["CARLA_ROOT"] = str(args.carla_root)
    env["PYTHONIOENCODING"] = "utf-8"
    checks = [
        ("carla312_import_yolov9_dependency", _import_check_command(args)),
        ("carla312_pip_show_yolov9_dependency", _pip_show_command(args)),
        ("carla312_edge_yolov9_no_fallback_probe", _edge_yolov9_command(args)),
        ("phase12b_yolov9_dry_run_command_probe", _phase12b_dry_run_command(args)),
        ("phase11m_yolov9_cli_parser_probe", _parser_probe_command("scripts.run_phase11m_grp_route_following")),
        ("phase11k_yolov9_cli_parser_probe", _parser_probe_command("scripts.run_phase11k_fixed_route_smoke")),
        (
            "phase12b_baseline_yolov9_cli_parser_probe",
            _parser_probe_command("scripts.run_phase12b_baseline_mapper_route_metrics"),
        ),
        ("phase12c_yolov9_rows_refresh", _phase12c_refresh_command(args)),
    ]
    results = [
        _run_command(name=name, command=command, raw_dir=raw_dir, timeout_sec=args.timeout_sec, env=env)
        for name, command in checks
    ]
    summary = _build_summary(args=args, run_dir=run_dir, results=results)
    _write_json(run_dir / "summary.json", summary)
    _write_json(
        run_dir / "manifest.json",
        {
            "phase": PHASE,
            "status": summary["status"],
            "created_at_utc": _utc_now().isoformat(),
            "run_dir": str(run_dir),
            "output_files": [
                "manifest.json",
                "summary.json",
                "commands.txt",
                "environment.json",
                "README.md",
                "raw_outputs/",
            ],
            "unlock_mode": summary["unlock_mode"],
            "post_unlock_verification_attempted": True,
            "post_unlock_verified": summary["post_unlock_verified"],
            "require_verified_requested": args.require_verified,
            "strict_gate_exit_code": summary["strict_gate_exit_code"],
            "auto_install_performed": False,
            "baseline_requirements_modified": False,
            "carla_server_started": False,
            "runtime_confirmation_executed": False,
            **BOUNDARY_FIELDS,
        },
    )
    _write_commands(run_dir / "commands.txt", args)
    _write_environment(run_dir / "environment.json", args)
    _write_readme(run_dir / "README.md", summary)
    print(f"experiment_dir={run_dir}")
    if summary["post_unlock_verified"]:
        print("Phase 12C-YOLOv9-V Verified - YOLOv9 post-unlock readiness is confirmed.")
        return 0
    print("Phase 12C-YOLOv9-V Blocked - YOLOv9 post-unlock readiness is not verified.")
    return 1 if args.require_verified else 0


if __name__ == "__main__":
    raise SystemExit(main())
