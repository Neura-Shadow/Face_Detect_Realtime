"""
Phase 12C-YOLO-U optional YOLO dependency unlock preparation.

This script prepares a reproducible dependency unlock evidence pack for the
YOLO optional perception backend. It does not install packages by default and
does not add ultralytics to baseline requirements. The target runtime remains
the dedicated CARLA Python 3.12 environment.
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
DEFAULT_PACKAGE_SPEC = "ultralytics>=8,<9"

PHASE = "Phase 12C-YOLO-U"
STATUS_PREPARED = "yolo_optional_dependency_unlock_prepared"
STATUS_READY = "yolo_optional_dependency_ready"
STATUS_FAILED = "yolo_optional_dependency_unlock_preflight_failed"
BENCHMARK_BOUNDARY_SCOPE = "yolo_optional_dependency_unlock_prepared_not_runtime_benchmark"

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
        timeout_stderr = (stderr.strip() or f"timeout after {timeout_sec}s")
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


def _import_check_command(python_executable: str) -> list[str]:
    code = (
        "import importlib.util; "
        "available = importlib.util.find_spec('ultralytics') is not None; "
        "print(f'ultralytics_available={available}'); "
        "raise SystemExit(0 if available else 1)"
    )
    return [python_executable, "-c", code]


def _pip_show_command(python_executable: str) -> list[str]:
    return [python_executable, "-m", "pip", "show", "ultralytics"]


def _edge_yolo_command(python_executable: str) -> list[str]:
    return [python_executable, "-m", "workers.core.edge_perception", "--test", "yolo"]


def _install_command(args: argparse.Namespace) -> list[str]:
    return [args.python_executable, "-m", "pip", "install", args.package_spec]


def _verify_commands(args: argparse.Namespace) -> dict[str, list[str]]:
    return {
        "install_ultralytics": _install_command(args),
        "verify_import": _import_check_command(args.python_executable),
        "verify_pip_show": _pip_show_command(args.python_executable),
        "verify_edge_yolo": _edge_yolo_command(args.python_executable),
        "refresh_phase12c_yolo_rows": [
            args.base_python,
            str(REPO_ROOT / "scripts" / "run_phase12c_perception_backend_ablation.py"),
            "--perception-backend-mode",
            "yolo_optional",
            "--output-dir",
            str(args.output_dir),
        ],
        "future_yolo_runtime_confirmation": [
            args.python_executable,
            str(REPO_ROOT / "scripts" / "run_phase12b_controller_ablation_experiment.py"),
            "--execute-runtime",
            "--controller-mode",
            "grp_follower",
            "--perception-backend",
            "yolo",
            "--host",
            args.host,
            "--port",
            str(args.port),
            "--town",
            args.town,
            "--python-executable",
            args.python_executable,
            "--base-python",
            args.base_python,
            "--child-timeout-sec",
            str(args.child_timeout_sec),
            "--output-dir",
            str(args.output_dir),
            "--carla-root",
            str(args.carla_root),
        ],
    }


def _edge_fallback_used(edge_result: CommandResult) -> bool:
    text = f"{edge_result.stdout_tail}\n{edge_result.stderr_tail}".lower()
    return "fallback used: true" in text or "graceful fallback" in text


def _build_summary(
    *,
    args: argparse.Namespace,
    run_dir: Path,
    command_results: list[CommandResult],
) -> dict[str, Any]:
    by_name = {result.name: result for result in command_results}
    import_ready = by_name["carla312_import_ultralytics"].exit_code == 0
    pip_ready = by_name["carla312_pip_show_ultralytics"].exit_code == 0
    edge_result = by_name["carla312_edge_yolo_smoke"]
    edge_yolo_fallback_used = _edge_fallback_used(edge_result)
    edge_command_passed = edge_result.exit_code == 0
    dependency_ready = import_ready and pip_ready and edge_command_passed and not edge_yolo_fallback_used
    status = STATUS_READY if dependency_ready else STATUS_PREPARED
    assertions = {
        "target_python_exists": Path(args.python_executable).exists(),
        "carla_root_exists": args.carla_root.exists(),
        "ultralytics_import_ready": import_ready,
        "ultralytics_pip_metadata_ready": pip_ready,
        "edge_yolo_command_passed": edge_command_passed,
        "edge_yolo_fallback_used": edge_yolo_fallback_used,
        "manual_install_command_recorded": True,
        "post_install_verify_commands_recorded": True,
        "auto_install_performed": False,
        "baseline_requirements_modified": False,
        "runtime_confirmation_executed": False,
        "all_boundary_fields_false": all(value is False for value in BOUNDARY_FIELDS.values()),
    }
    return {
        "phase": PHASE,
        "status": status,
        "dependency_ready": dependency_ready,
        "dependency_missing": not dependency_ready,
        "run_dir": str(run_dir),
        "target_python": args.python_executable,
        "target_python_exists": Path(args.python_executable).exists(),
        "carla_root": str(args.carla_root),
        "carla_root_exists": args.carla_root.exists(),
        "package_spec": args.package_spec,
        "perception_backend_mode": "yolo_optional",
        "perception_backend": "yolo",
        "model_hint": args.model_name,
        "manual_unlock_required": not dependency_ready,
        "auto_install_performed": False,
        "baseline_requirements_modified": False,
        "runtime_confirmation_executed": False,
        "install_command": _command_text(_install_command(args)),
        "commands": {name: _command_text(command) for name, command in _verify_commands(args).items()},
        "preflight_results": [_result_payload(result) for result in command_results],
        "assertions": assertions,
        "benchmark_boundary_prepared": True,
        "benchmark_boundary_scope": BENCHMARK_BOUNDARY_SCOPE,
        **BOUNDARY_FIELDS,
        "benchmark_boundaries": dict(BOUNDARY_FIELDS),
    }


def _write_commands(path: Path, args: argparse.Namespace, summary: dict[str, Any]) -> None:
    lines = [
        "# Phase 12C-YOLO-U parent command",
        _command_text([sys.executable, *sys.argv]),
        "",
        "# Manual unlock command. This script does not run it automatically.",
        summary["install_command"],
        "",
        "# Post-unlock verification commands",
    ]
    for name, command in summary["commands"].items():
        lines.append(f"# {name}")
        lines.append(str(command))
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_environment(path: Path, args: argparse.Namespace) -> None:
    payload = {
        "python": sys.version,
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "host": args.host,
        "port": args.port,
        "target_python": args.python_executable,
        "target_python_exists": Path(args.python_executable).exists(),
        "carla_root": str(args.carla_root),
        "carla_root_exists": args.carla_root.exists(),
        "base_python": args.base_python,
        "package_spec": args.package_spec,
    }
    _write_json(path, payload)


def _write_readme(path: Path, summary: dict[str, Any]) -> None:
    body = f"""# Phase 12C-YOLO-U YOLO Optional Dependency Unlock Prepared

Status:

```text
{summary["status"]}
```

```text
dependency_ready={str(summary["dependency_ready"]).lower()}
dependency_missing={str(summary["dependency_missing"]).lower()}
perception_backend=yolo
package_spec={summary["package_spec"]}
auto_install_performed=false
baseline_requirements_modified=false
runtime_confirmation_executed=false
```

Manual unlock:

```powershell
{summary["install_command"]}
```

Boundary:

```text
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```
"""
    path.write_text(body, encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare Phase 12C YOLO optional dependency unlock evidence")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--town", default="Town03")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timestamp", default=None)
    parser.add_argument("--carla-root", type=Path, default=DEFAULT_CARLA_ROOT)
    parser.add_argument("--python-executable", default=DEFAULT_CARLA_PYTHON)
    parser.add_argument("--base-python", default="python")
    parser.add_argument("--package-spec", default=DEFAULT_PACKAGE_SPEC)
    parser.add_argument("--model-name", default="yolov8n.pt")
    parser.add_argument("--child-timeout-sec", type=float, default=2400.0)
    parser.add_argument("--preflight-timeout-sec", type=float, default=120.0)
    parser.add_argument("--require-ready", action="store_true", help="Exit nonzero when ultralytics is not ready")
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
        ("carla312_import_ultralytics", _import_check_command(args.python_executable)),
        ("carla312_pip_show_ultralytics", _pip_show_command(args.python_executable)),
        ("carla312_edge_yolo_smoke", _edge_yolo_command(args.python_executable)),
    ]
    command_results = [
        _run_command(name=name, command=command, raw_dir=raw_dir, timeout_sec=args.preflight_timeout_sec, env=env)
        for name, command in checks
    ]
    summary = _build_summary(args=args, run_dir=run_dir, command_results=command_results)
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
            "target_python": args.python_executable,
            "package_spec": args.package_spec,
            "auto_install_performed": False,
            "baseline_requirements_modified": False,
            "runtime_confirmation_executed": False,
            "benchmark_boundary_prepared": True,
            "benchmark_boundary_scope": BENCHMARK_BOUNDARY_SCOPE,
            **BOUNDARY_FIELDS,
        },
    )
    _write_commands(run_dir / "commands.txt", args, summary)
    _write_environment(run_dir / "environment.json", args)
    _write_readme(run_dir / "README.md", summary)

    print(f"experiment_dir={run_dir}")
    if summary["dependency_ready"]:
        print("Phase 12C-YOLO-U Ready - ultralytics dependency is available in the target runtime.")
        return 0
    print("Phase 12C-YOLO-U Prepared - YOLO optional dependency unlock commands and evidence were written.")
    return 1 if args.require_ready else 0


if __name__ == "__main__":
    raise SystemExit(main())
