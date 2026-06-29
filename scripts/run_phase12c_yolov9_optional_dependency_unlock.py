"""
Phase 12C-YOLOv9-U optional dependency unlock preparation.

This script prepares a reproducible evidence pack for a future YOLOv9 optional
perception backend. It does not install packages, does not modify baseline
requirements, does not start CARLA, and does not run YOLOv9 runtime
confirmation.
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
DEFAULT_PACKAGE_SPEC = "<YOLOV9_PACKAGE_SPEC>"
DEFAULT_REQUIREMENTS_PATH = "<YOLOV9_REQUIREMENTS_PATH>"
DEFAULT_DEPENDENCY_MODULE = "yolov9"
DEFAULT_PIP_PACKAGE = "yolov9"

PHASE = "Phase 12C-YOLOv9-U"
STATUS_PREPARED = "yolov9_optional_dependency_unlock_prepared"
STATUS_READY = "yolov9_optional_dependency_ready"
BENCHMARK_BOUNDARY_SCOPE = "yolov9_optional_dependency_unlock_prepared_not_runtime_benchmark"

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
    if arg.startswith("<") and arg.endswith(">"):
        return arg
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


def _edge_yolov9_probe_command(args: argparse.Namespace) -> list[str]:
    return [args.python_executable, "-m", "workers.core.edge_perception", "--test", "yolov9"]


def _package_install_command(args: argparse.Namespace) -> list[str]:
    return [args.python_executable, "-m", "pip", "install", args.package_spec]


def _requirements_install_command(args: argparse.Namespace) -> list[str]:
    return [args.python_executable, "-m", "pip", "install", "-r", args.requirements_path]


def _future_runtime_command(args: argparse.Namespace) -> list[str]:
    return [
        args.python_executable,
        str(REPO_ROOT / "scripts" / "run_phase12b_controller_ablation_experiment.py"),
        "--execute-runtime",
        "--controller-mode",
        "grp_follower",
        "--perception-backend",
        "yolov9",
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
    ]


def _verification_commands(args: argparse.Namespace) -> dict[str, list[str]]:
    return {
        "option_a_package_install_if_supported": _package_install_command(args),
        "option_b_repository_requirements_install_if_required": _requirements_install_command(args),
        "verify_import": _import_check_command(args),
        "verify_pip_show": _pip_show_command(args),
        "verify_edge_yolov9": _edge_yolov9_probe_command(args),
        "refresh_phase12c_yolov9_rows": [
            args.base_python,
            str(REPO_ROOT / "scripts" / "run_phase12c_perception_backend_ablation.py"),
            "--perception-backend-mode",
            "yolov9_optional",
            "--output-dir",
            str(args.output_dir),
        ],
        "future_yolov9_runtime_confirmation_after_backend_support": _future_runtime_command(args),
    }


def _edge_command_supported(edge_result: CommandResult) -> bool:
    text = f"{edge_result.stdout_tail}\n{edge_result.stderr_tail}".lower()
    return not (edge_result.exit_code == 2 and ("invalid choice" in text or "argument --test" in text))


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
    import_result = by_name["carla312_import_yolov9_dependency"]
    pip_result = by_name["carla312_pip_show_yolov9_dependency"]
    edge_result = by_name["carla312_edge_yolov9_support_probe"]
    yolov9_import_ready = import_result.exit_code == 0
    yolov9_pip_metadata_ready = pip_result.exit_code == 0
    edge_yolov9_command_supported = _edge_command_supported(edge_result)
    edge_yolov9_command_passed = edge_result.exit_code == 0 if edge_yolov9_command_supported else None
    edge_yolov9_fallback_used = _edge_fallback_used(edge_result) if edge_yolov9_command_supported else None
    dependency_ready = (
        yolov9_import_ready
        and yolov9_pip_metadata_ready
        and edge_yolov9_command_supported
        and edge_yolov9_command_passed is True
        and edge_yolov9_fallback_used is False
    )
    assertions = {
        "target_python_exists": Path(args.python_executable).exists(),
        "carla_root_exists": args.carla_root.exists(),
        "yolov9_import_ready": yolov9_import_ready,
        "yolov9_pip_metadata_ready": yolov9_pip_metadata_ready,
        "edge_yolov9_command_supported": edge_yolov9_command_supported,
        "edge_yolov9_command_passed": edge_yolov9_command_passed,
        "edge_yolov9_fallback_used": edge_yolov9_fallback_used,
        "manual_unlock_required": not dependency_ready,
        "manual_unlock_commands_recorded": True,
        "post_unlock_verification_commands_recorded": True,
        "auto_install_performed": False,
        "baseline_requirements_modified": False,
        "runtime_confirmation_executed": False,
        "all_boundary_fields_false": all(value is False for value in BOUNDARY_FIELDS.values()),
    }
    return {
        "phase": PHASE,
        "status": STATUS_READY if dependency_ready else STATUS_PREPARED,
        "target_python": args.python_executable,
        "target_python_exists": Path(args.python_executable).exists(),
        "carla_root": str(args.carla_root),
        "carla_root_exists": args.carla_root.exists(),
        "perception_backend": "yolov9",
        "perception_backend_mode": "yolov9_optional",
        "model_hint": args.model_hint,
        "dependency_module": args.dependency_module,
        "pip_package": args.pip_package,
        "package_spec": args.package_spec,
        "requirements_path": args.requirements_path,
        "dependency_ready": dependency_ready,
        "dependency_missing": not dependency_ready,
        "manual_unlock_required": not dependency_ready,
        "yolov9_import_ready": yolov9_import_ready,
        "yolov9_pip_metadata_ready": yolov9_pip_metadata_ready,
        "edge_yolov9_command_supported": edge_yolov9_command_supported,
        "edge_yolov9_command_passed": edge_yolov9_command_passed,
        "edge_yolov9_fallback_used": edge_yolov9_fallback_used,
        "auto_install_performed": False,
        "baseline_requirements_modified": False,
        "runtime_confirmation_executed": False,
        "run_dir": str(run_dir),
        "commands": {name: _command_text(command) for name, command in _verification_commands(args).items()},
        "preflight_results": [_result_payload(result) for result in command_results],
        "assertions": assertions,
        "historical_note": "Phase 12C-YOLO-U was the earlier generic YOLO unlock preparation; Phase 12C-YOLOv9-U is the revised YOLOv9-specific target. Old evidence is not rewritten as YOLOv9 evidence.",
        "benchmark_boundary_prepared": True,
        "benchmark_boundary_scope": BENCHMARK_BOUNDARY_SCOPE,
        **BOUNDARY_FIELDS,
        "benchmark_boundaries": dict(BOUNDARY_FIELDS),
    }


def _write_commands(path: Path, args: argparse.Namespace, summary: dict[str, Any]) -> None:
    lines = [
        "# Phase 12C-YOLOv9-U parent command",
        _command_text([sys.executable, *sys.argv]),
        "",
        "# Manual/operator unlock actions. This script does not run these automatically.",
        "# Option A - package-based if supported by the selected YOLOv9 implementation:",
        summary["commands"]["option_a_package_install_if_supported"],
        "",
        "# Option B - repository/manual install if required; operator fills exact YOLOv9 install source:",
        summary["commands"]["option_b_repository_requirements_install_if_required"],
        "",
        "# Post-unlock verification commands",
    ]
    for name in (
        "verify_import",
        "verify_pip_show",
        "verify_edge_yolov9",
        "refresh_phase12c_yolov9_rows",
        "future_yolov9_runtime_confirmation_after_backend_support",
    ):
        lines.append(f"# {name}")
        lines.append(str(summary["commands"][name]))
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
        "dependency_module": args.dependency_module,
        "pip_package": args.pip_package,
        "package_spec": args.package_spec,
        "requirements_path": args.requirements_path,
    }
    _write_json(path, payload)


def _write_readme(path: Path, summary: dict[str, Any]) -> None:
    body = f"""# Phase 12C-YOLOv9-U YOLOv9 Optional Dependency Unlock Prepared

Status:

```text
{summary["status"]}
```

```text
dependency_ready={str(summary["dependency_ready"]).lower()}
dependency_missing={str(summary["dependency_missing"]).lower()}
perception_backend=yolov9
perception_backend_mode=yolov9_optional
edge_yolov9_command_supported={str(summary["edge_yolov9_command_supported"]).lower()}
edge_yolov9_command_passed={summary["edge_yolov9_command_passed"]}
edge_yolov9_fallback_used={summary["edge_yolov9_fallback_used"]}
auto_install_performed=false
baseline_requirements_modified=false
runtime_confirmation_executed=false
```

This is YOLOv9 optional dependency preparation only. It does not validate
YOLOv9 runtime, does not install dependencies automatically, does not modify
baseline requirements, and does not start CARLA.

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
    parser = argparse.ArgumentParser(description="Prepare Phase 12C-YOLOv9-U optional dependency unlock evidence")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--town", default="Town03")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timestamp", default=None)
    parser.add_argument("--carla-root", type=Path, default=DEFAULT_CARLA_ROOT)
    parser.add_argument("--python-executable", default=DEFAULT_CARLA_PYTHON)
    parser.add_argument("--base-python", default="python")
    parser.add_argument("--dependency-module", default=DEFAULT_DEPENDENCY_MODULE)
    parser.add_argument("--pip-package", default=DEFAULT_PIP_PACKAGE)
    parser.add_argument("--package-spec", default=DEFAULT_PACKAGE_SPEC)
    parser.add_argument("--requirements-path", default=DEFAULT_REQUIREMENTS_PATH)
    parser.add_argument("--model-hint", default="yolov9")
    parser.add_argument("--child-timeout-sec", type=float, default=2400.0)
    parser.add_argument("--preflight-timeout-sec", type=float, default=120.0)
    parser.add_argument("--require-ready", action="store_true", help="Exit nonzero when YOLOv9 dependency/backend support is not ready")
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
        ("carla312_edge_yolov9_support_probe", _edge_yolov9_probe_command(args)),
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
            "perception_backend": "yolov9",
            "perception_backend_mode": "yolov9_optional",
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
        print("Phase 12C-YOLOv9-U Ready - YOLOv9 dependency and EdgePerception command support are available.")
        return 0
    print("Phase 12C-YOLOv9-U Prepared - YOLOv9 optional dependency unlock commands and evidence were written.")
    return 1 if args.require_ready else 0


if __name__ == "__main__":
    raise SystemExit(main())
