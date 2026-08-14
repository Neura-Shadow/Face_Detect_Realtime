"""
Phase 12C-YOLOv9-SRC official YOLOv9 external-source adapter verification.

此 runner 只驗證 source-root / weights 環境合約與 EdgePerception
no-fallback gate。它不安裝 YOLOv9、不 vendor source、不啟動 CARLA，
也不宣稱 YOLOv9 route runtime 或模型準確率。
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

PHASE = "Phase 12C-YOLOv9-SRC"
STATUS_VERIFIED = "yolov9_source_adapter_verified"
STATUS_BLOCKED = "yolov9_source_adapter_blocked"
BENCHMARK_BOUNDARY_SCOPE = "yolov9_source_adapter_prepared_not_runtime_benchmark"
EXPECTED_SOURCE_ENTRIES = ("detect.py", "detect_dual.py", "models", "utils")

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


def _tail(text: str, max_lines: int = 16) -> str:
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
        stdout = completed.stdout
        stderr = completed.stderr
        exit_code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        stderr = (stderr + f"\nTIMEOUT after {timeout_sec}s").strip()
        exit_code = 124
    except OSError as exc:
        stdout = ""
        stderr = f"OSERROR: {exc}"
        exit_code = 127
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
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


def _bool_from_key(values: dict[str, str], key: str) -> bool:
    return values.get(key, "").lower() == "true"


def _edge_yolov9_command(args: argparse.Namespace) -> list[str]:
    return [args.python_executable, "-m", "workers.core.edge_perception", "--test", "yolov9"]


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
        "yolov9_expected_source_files": list(EXPECTED_SOURCE_ENTRIES),
        "yolov9_expected_source_files_ready": source_root_ready and not missing_entries,
        "yolov9_missing_source_entries": missing_entries,
    }


def _build_summary(
    *,
    args: argparse.Namespace,
    run_dir: Path,
    edge_result: CommandResult,
) -> dict[str, Any]:
    contract = _source_contract(args)
    stdout = Path(edge_result.stdout_path).read_text(encoding="utf-8", errors="replace")
    stderr = Path(edge_result.stderr_path).read_text(encoding="utf-8", errors="replace")
    edge_values = _parse_key_values(stdout + "\n" + stderr)
    edge_passed = edge_result.exit_code == 0 and _bool_from_key(edge_values, "edge_yolov9_command_passed")
    edge_fallback = _bool_from_key(edge_values, "edge_yolov9_fallback_used")
    edge_no_fallback = edge_passed and _bool_from_key(edge_values, "edge_yolov9_no_fallback_verified")
    source_adapter_verified = all(
        [
            Path(args.python_executable).exists(),
            contract["yolov9_source_root_configured"],
            contract["yolov9_weights_configured"],
            contract["yolov9_source_root_ready"],
            contract["yolov9_expected_source_files_ready"],
            contract["yolov9_weights_ready"],
            edge_passed,
            not edge_fallback,
            edge_no_fallback,
        ]
    )
    blocked_parts: list[str] = []
    if not Path(args.python_executable).exists():
        blocked_parts.append("target CARLA Python does not exist")
    if not contract["yolov9_source_root_configured"]:
        blocked_parts.append(f"{args.source_root_env} is not set")
    elif not contract["yolov9_source_root_ready"]:
        blocked_parts.append(f"{args.source_root_env} path is missing or not a directory")
    if contract["yolov9_missing_source_entries"]:
        blocked_parts.append("missing source entries: " + ", ".join(contract["yolov9_missing_source_entries"]))
    if not contract["yolov9_weights_configured"]:
        blocked_parts.append(f"{args.weights_env} is not set")
    elif not contract["yolov9_weights_ready"]:
        blocked_parts.append(f"{args.weights_env} path is missing or not a file")
    if edge_fallback:
        blocked_parts.append(edge_values.get("blocked_reason") or "EdgePerception used fallback")
    if edge_result.exit_code != 0:
        blocked_parts.append("EdgePerception command failed")
    return {
        "phase": PHASE,
        "status": STATUS_VERIFIED if source_adapter_verified else STATUS_BLOCKED,
        "source_adapter_verification_attempted": True,
        "source_adapter_verified": source_adapter_verified,
        "require_verified_requested": args.require_verified,
        "strict_gate_exit_code": 0 if source_adapter_verified or not args.require_verified else 1,
        "target_python": args.python_executable,
        "target_python_exists": Path(args.python_executable).exists(),
        "perception_backend": "yolov9",
        "perception_backend_mode": "yolov9_optional",
        **contract,
        "edge_yolov9_command_passed": edge_passed,
        "edge_yolov9_fallback_used": edge_fallback,
        "edge_yolov9_no_fallback_verified": edge_no_fallback,
        "edge_yolov9_runtime_backend": edge_values.get("runtime_backend"),
        "edge_yolov9_blocked_reason": edge_values.get("blocked_reason"),
        "auto_install_performed": False,
        "baseline_requirements_modified": False,
        "carla_server_started": False,
        "runtime_confirmation_executed": False,
        "yolov9_source_repo_committed": False,
        "yolov9_weights_committed": False,
        "run_dir": str(run_dir),
        "preflight_results": [_result_payload(edge_result)],
        "assertions": {
            "source_root_contract_checked": True,
            "weights_contract_checked": True,
            "edge_command_checked": True,
            "no_fallback_required_for_strict_pass": True,
            "source_adapter_verified": source_adapter_verified,
            "all_boundary_fields_false": all(value is False for value in BOUNDARY_FIELDS.values()),
        },
        "blocked_reason": None if source_adapter_verified else "; ".join(dict.fromkeys(part for part in blocked_parts if part)),
        "benchmark_boundary_prepared": True,
        "benchmark_boundary_scope": BENCHMARK_BOUNDARY_SCOPE,
        **BOUNDARY_FIELDS,
        "benchmark_boundaries": dict(BOUNDARY_FIELDS),
    }


def _write_commands(path: Path, args: argparse.Namespace) -> None:
    lines = [
        "# Phase 12C-YOLOv9-SRC parent command",
        _command_text([sys.executable, *sys.argv]),
        "",
        "# Manual operator setup example; values are not committed",
        '$env:YOLOV9_ROOT = "D:\\AIModels\\yolov9"',
        '$env:YOLOV9_WEIGHTS = "D:\\AIModels\\yolov9\\yolov9-c-converted.pt"',
        'D:\\CARLA\\envs\\ma-vlna-carla312\\python.exe -m pip install -r "$env:YOLOV9_ROOT\\requirements.txt"',
        "",
        "# Source adapter no-fallback probe",
        _command_text(_edge_yolov9_command(args)),
        "",
        "# Strict verification",
        _command_text([sys.executable, str(REPO_ROOT / "scripts" / "run_phase12c_yolov9_source_adapter_verification.py"), "--output-dir", str(args.output_dir), "--require-verified"]),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_environment(path: Path, args: argparse.Namespace, summary: dict[str, Any]) -> None:
    _write_json(
        path,
        {
            "python": sys.version,
            "python_executable": sys.executable,
            "platform": platform.platform(),
            "target_python": args.python_executable,
            "target_python_exists": summary["target_python_exists"],
            "source_root_env": args.source_root_env,
            "weights_env": args.weights_env,
            "yolov9_source_root_configured": summary["yolov9_source_root_configured"],
            "yolov9_weights_configured": summary["yolov9_weights_configured"],
            "yolov9_source_root_ready": summary["yolov9_source_root_ready"],
            "yolov9_weights_ready": summary["yolov9_weights_ready"],
        },
    )


def _write_readme(path: Path, summary: dict[str, Any]) -> None:
    body = f"""# Phase 12C-YOLOv9-SRC Source Adapter Verification

Status:

```text
{summary["status"]}
```

```text
source_adapter_verified={str(summary["source_adapter_verified"]).lower()}
require_verified_requested={str(summary["require_verified_requested"]).lower()}
strict_gate_exit_code={summary["strict_gate_exit_code"]}
yolov9_source_root_configured={str(summary["yolov9_source_root_configured"]).lower()}
yolov9_source_root_ready={str(summary["yolov9_source_root_ready"]).lower()}
yolov9_weights_configured={str(summary["yolov9_weights_configured"]).lower()}
yolov9_weights_ready={str(summary["yolov9_weights_ready"]).lower()}
edge_yolov9_command_passed={str(summary["edge_yolov9_command_passed"]).lower()}
edge_yolov9_fallback_used={str(summary["edge_yolov9_fallback_used"]).lower()}
edge_yolov9_no_fallback_verified={str(summary["edge_yolov9_no_fallback_verified"]).lower()}
runtime_confirmation_executed=false
```

YOLOv9 source and weights are external operator-provided assets. They are not
committed, vendored, or packaged by this repository.

Blocked reason:

```text
{summary["blocked_reason"] or "null"}
```
"""
    path.write_text(body, encoding="utf-8")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify Phase 12C-YOLOv9-SRC external source adapter")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timestamp", default=None)
    parser.add_argument("--python-executable", default=DEFAULT_CARLA_PYTHON)
    parser.add_argument("--source-root-env", default="YOLOV9_ROOT")
    parser.add_argument("--weights-env", default="YOLOV9_WEIGHTS")
    parser.add_argument("--timeout-sec", type=float, default=180.0)
    parser.add_argument("--require-verified", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    args.output_dir = _resolve_repo_path(args.output_dir)
    run_dir = _next_run_dir(args.output_dir, args.timestamp)
    raw_dir = run_dir / "raw_outputs"
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    edge_result = _run_command(
        name="carla312_edge_yolov9_source_adapter_probe",
        command=_edge_yolov9_command(args),
        raw_dir=raw_dir,
        timeout_sec=args.timeout_sec,
        env=env,
    )
    summary = _build_summary(args=args, run_dir=run_dir, edge_result=edge_result)
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
            "source_adapter_verification_attempted": True,
            "source_adapter_verified": summary["source_adapter_verified"],
            "require_verified_requested": args.require_verified,
            "strict_gate_exit_code": summary["strict_gate_exit_code"],
            "auto_install_performed": False,
            "baseline_requirements_modified": False,
            "carla_server_started": False,
            "runtime_confirmation_executed": False,
            "yolov9_source_repo_committed": False,
            "yolov9_weights_committed": False,
            **BOUNDARY_FIELDS,
        },
    )
    _write_commands(run_dir / "commands.txt", args)
    _write_environment(run_dir / "environment.json", args, summary)
    _write_readme(run_dir / "README.md", summary)
    print(f"experiment_dir={run_dir}")
    if summary["source_adapter_verified"]:
        print("Phase 12C-YOLOv9-SRC Verified - official source adapter no-fallback readiness is confirmed.")
        return 0
    print("Phase 12C-YOLOv9-SRC Blocked - official source adapter no-fallback readiness is not verified.")
    return 1 if args.require_verified else 0


if __name__ == "__main__":
    raise SystemExit(main())
