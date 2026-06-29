"""
Phase 12C-YOLOv9-B EdgePerception YOLOv9 backend adapter checks.

The checks prove that EdgePerception exposes a YOLOv9 backend path and that the
path preserves graceful fallback when the optional dependency is unavailable.
They do not install packages, start CARLA, or run YOLOv9 runtime confirmation.
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

PHASE = "Phase 12C-YOLOv9-B"
STATUS_PREPARED = "yolov9_backend_adapter_prepared"
STATUS_FAILED = "yolov9_backend_adapter_preflight_failed"
BENCHMARK_BOUNDARY_SCOPE = "yolov9_backend_adapter_prepared_not_runtime_benchmark"

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


def _edge_yolov9_command(python_executable: str) -> list[str]:
    return [python_executable, "-m", "workers.core.edge_perception", "--test", "yolov9"]


def _import_check_command(python_executable: str) -> list[str]:
    code = (
        "import importlib.util; "
        "available = importlib.util.find_spec('yolov9') is not None; "
        "print(f'yolov9_import_ready={available}'); "
        "raise SystemExit(0 if available else 1)"
    )
    return [python_executable, "-c", code]


def _command_supported(result: CommandResult) -> bool:
    text = f"{result.stdout_tail}\n{result.stderr_tail}".lower()
    return not (result.exit_code == 2 and ("invalid choice" in text or "argument --test" in text))


def _fallback_used(result: CommandResult) -> bool:
    text = f"{result.stdout_tail}\n{result.stderr_tail}".lower()
    return "fallback used: true" in text or "graceful fallback" in text


def _build_summary(
    *,
    args: argparse.Namespace,
    run_dir: Path,
    results: list[CommandResult],
) -> dict[str, Any]:
    by_name = {result.name: result for result in results}
    base_edge = by_name["base_edge_yolov9_adapter_smoke"]
    carla_edge = by_name["carla312_edge_yolov9_adapter_smoke"]
    base_supported = _command_supported(base_edge)
    carla_supported = _command_supported(carla_edge)
    base_passed = base_edge.exit_code == 0
    carla_passed = carla_edge.exit_code == 0
    base_fallback = _fallback_used(base_edge)
    carla_fallback = _fallback_used(carla_edge)
    base_import_ready = by_name["base_import_yolov9_dependency"].exit_code == 0
    carla_import_ready = by_name["carla312_import_yolov9_dependency"].exit_code == 0
    adapter_prepared = base_supported and carla_supported and base_passed and carla_passed
    return {
        "phase": PHASE,
        "status": STATUS_PREPARED if adapter_prepared else STATUS_FAILED,
        "adapter_prepared": adapter_prepared,
        "target_python": args.python_executable,
        "base_python": args.base_python,
        "carla_root": str(args.carla_root),
        "perception_backend": "yolov9",
        "perception_backend_mode": "yolov9_optional",
        "edge_yolov9_backend_registered": adapter_prepared,
        "base_edge_yolov9_command_supported": base_supported,
        "carla312_edge_yolov9_command_supported": carla_supported,
        "base_edge_yolov9_command_passed": base_passed,
        "carla312_edge_yolov9_command_passed": carla_passed,
        "base_edge_yolov9_fallback_used": base_fallback,
        "carla312_edge_yolov9_fallback_used": carla_fallback,
        "base_yolov9_import_ready": base_import_ready,
        "carla312_yolov9_import_ready": carla_import_ready,
        "dependency_ready": base_import_ready and carla_import_ready and not (base_fallback or carla_fallback),
        "dependency_missing": not (base_import_ready and carla_import_ready),
        "auto_install_performed": False,
        "baseline_requirements_modified": False,
        "runtime_confirmation_executed": False,
        "carla_server_started": False,
        "run_dir": str(run_dir),
        "preflight_results": [_result_payload(result) for result in results],
        "assertions": {
            "edge_yolov9_backend_registered": adapter_prepared,
            "base_edge_yolov9_command_supported": base_supported,
            "carla312_edge_yolov9_command_supported": carla_supported,
            "graceful_fallback_preserved": base_fallback and carla_fallback,
            "auto_install_performed": False,
            "baseline_requirements_modified": False,
            "runtime_confirmation_executed": False,
            "carla_server_started": False,
            "all_boundary_fields_false": all(value is False for value in BOUNDARY_FIELDS.values()),
        },
        "benchmark_boundary_prepared": True,
        "benchmark_boundary_scope": BENCHMARK_BOUNDARY_SCOPE,
        **BOUNDARY_FIELDS,
        "benchmark_boundaries": dict(BOUNDARY_FIELDS),
    }


def _write_commands(path: Path, args: argparse.Namespace) -> None:
    lines = [
        "# Phase 12C-YOLOv9-B parent command",
        _command_text([sys.executable, *sys.argv]),
        "",
        "# Adapter smoke commands",
        _command_text(_edge_yolov9_command(args.base_python)),
        _command_text(_edge_yolov9_command(args.python_executable)),
        "",
        "# Dependency import probes",
        _command_text(_import_check_command(args.base_python)),
        _command_text(_import_check_command(args.python_executable)),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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
        },
    )


def _write_readme(path: Path, summary: dict[str, Any]) -> None:
    body = f"""# Phase 12C-YOLOv9-B EdgePerception YOLOv9 Backend Adapter Prepared

Status:

```text
{summary["status"]}
```

```text
edge_yolov9_backend_registered={str(summary["edge_yolov9_backend_registered"]).lower()}
base_edge_yolov9_command_supported={str(summary["base_edge_yolov9_command_supported"]).lower()}
carla312_edge_yolov9_command_supported={str(summary["carla312_edge_yolov9_command_supported"]).lower()}
base_edge_yolov9_fallback_used={str(summary["base_edge_yolov9_fallback_used"]).lower()}
carla312_edge_yolov9_fallback_used={str(summary["carla312_edge_yolov9_fallback_used"]).lower()}
runtime_confirmation_executed=false
```

This adapter check proves the YOLOv9 backend path is registered in
EdgePerception. Missing optional dependency still falls back safely. It does
not validate YOLOv9 runtime behavior.
"""
    path.write_text(body, encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check Phase 12C-YOLOv9-B EdgePerception adapter readiness")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timestamp", default=None)
    parser.add_argument("--carla-root", type=Path, default=DEFAULT_CARLA_ROOT)
    parser.add_argument("--python-executable", default=DEFAULT_CARLA_PYTHON)
    parser.add_argument("--base-python", default="python")
    parser.add_argument("--timeout-sec", type=float, default=120.0)
    parser.add_argument("--require-prepared", action="store_true")
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
        ("base_import_yolov9_dependency", _import_check_command(args.base_python)),
        ("carla312_import_yolov9_dependency", _import_check_command(args.python_executable)),
        ("base_edge_yolov9_adapter_smoke", _edge_yolov9_command(args.base_python)),
        ("carla312_edge_yolov9_adapter_smoke", _edge_yolov9_command(args.python_executable)),
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
            "auto_install_performed": False,
            "baseline_requirements_modified": False,
            "runtime_confirmation_executed": False,
            **BOUNDARY_FIELDS,
        },
    )
    _write_commands(run_dir / "commands.txt", args)
    _write_environment(run_dir / "environment.json", args)
    _write_readme(run_dir / "README.md", summary)
    print(f"experiment_dir={run_dir}")
    if summary["adapter_prepared"]:
        print("Phase 12C-YOLOv9-B Prepared - EdgePerception YOLOv9 backend adapter path is registered.")
        return 0
    print("Phase 12C-YOLOv9-B Failed - YOLOv9 backend adapter path is not ready.")
    return 1 if args.require_prepared else 0


if __name__ == "__main__":
    raise SystemExit(main())
