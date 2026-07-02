"""
Phase 12C-R1-RT-DETR-ASSET-SETUP dependency and local asset gate.

This parent runner does not import CARLA and does not start a CARLA server. It
only prepares operator-visible setup commands, audits the CARLA Python 3.12
runtime, optionally runs an explicit dependency install, validates local
RT-DETR weights, and optionally runs an EdgePerception no-fallback smoke.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
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
DEFAULT_RTDETR_UNLOCK_EVIDENCE_DIR = Path(r"experiments\phase12\20260702T022636Z-1")
DEFAULT_LIGHTWEIGHT_EVIDENCE_DIR = Path(r"experiments\phase12\20260701T165325Z")
DEFAULT_ASSET_DIR = Path(r"D:\AIModels\rtdetr")
DEFAULT_ASSET_PATH = DEFAULT_ASSET_DIR / "rtdetr-l.pt"

PHASE = "Phase 12C-R1-RT-DETR-ASSET-SETUP"
RUNTIME_SCOPE = "rtdetr_dependency_asset_setup_only"
STATUS_PREPARED = "prepared"
STATUS_COMMAND_READY = "command_ready"
STATUS_BLOCKED = "blocked"
STATUS_LINES = {
    STATUS_PREPARED: (
        "Phase 12C-R1-RT-DETR-ASSET-SETUP Prepared - RT-DETR dependency and "
        "local asset setup are ready for no-fallback unlock verification."
    ),
    STATUS_COMMAND_READY: (
        "Phase 12C-R1-RT-DETR-ASSET-SETUP Command-Ready - explicit RT-DETR "
        "setup commands and asset contract are written, but setup was not executed."
    ),
    STATUS_BLOCKED: (
        "Phase 12C-R1-RT-DETR-ASSET-SETUP Blocked - RT-DETR dependency or "
        "local model assets remain unavailable."
    ),
}

BOUNDARY_FIELDS = {
    "baseline_requirements_modified": False,
    "auto_install_performed": False,
    "operator_explicit_install_required": True,
    "weights_downloaded": False,
    "weights_committed": False,
    "carla_server_started": False,
    "runtime_confirmation_executed": False,
    "carla_route_runtime_executed": False,
    "rtdetr_runtime_verified": False,
    "rtdetr_accuracy_verified": False,
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
    "status_line",
    "runtime_scope",
    "rtdetr_unlock_evidence_dir",
    "lightweight_evidence_dir",
    "target_perception_backend",
    "target_python",
    "carla_root",
    "ultralytics_import_ready_before",
    "ultralytics_import_ready_after",
    "ultralytics_version_before",
    "ultralytics_version_after",
    "dependency_install_requested",
    "dependency_install_executed",
    "dependency_install_exit_code",
    "baseline_requirements_modified",
    "auto_install_performed",
    "operator_explicit_install_required",
    "rtdetr_weights_configured",
    "rtdetr_weights_ready",
    "rtdetr_model_hint",
    "rtdetr_device",
    "rtdetr_img_size",
    "asset_dir_prepared",
    "weights_downloaded",
    "weights_committed",
    "edge_rtdetr_backend_registered",
    "edge_rtdetr_command_supported",
    "edge_rtdetr_command_passed",
    "edge_rtdetr_fallback_used",
    "edge_rtdetr_no_fallback_verified",
    "post_setup_smoke_executed",
    "phase12c_rtdetr_rows_available",
    "phase12c_rtdetr_backend_unavailable_count",
    "carla_server_started",
    "runtime_confirmation_executed",
    "carla_route_runtime_executed",
    "rtdetr_runtime_verified",
    "rtdetr_accuracy_verified",
    "selected_route_completion_verified",
    "full_phase12c_perception_ablation_runtime_pass",
    "route_benchmark_verified",
    "infraction_benchmark_verified",
    "leaderboard_evaluated",
    "leaderboard_routes_exported",
    "leaderboard_route_criteria_evaluated",
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


@dataclass(frozen=True)
class ImportProbe:
    ready: bool
    version: str | None
    command: list[str] | None
    result: CommandResult | None


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
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


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
    stdout_path: Path,
    stderr_path: Path,
    env: dict[str, str],
    timeout_sec: float,
) -> CommandResult:
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


def _bool_value(values: dict[str, str], key: str) -> bool | None:
    raw = values.get(key)
    if raw is None:
        return None
    if raw.lower() == "true":
        return True
    if raw.lower() == "false":
        return False
    return None


def _env_with_runtime_contract(args: argparse.Namespace) -> dict[str, str]:
    env = os.environ.copy()
    env["CARLA_ROOT"] = str(args.carla_root)
    env["PYTHONIOENCODING"] = "utf-8"
    weights = _configured_weights(args)
    if weights:
        env["RTDETR_WEIGHTS"] = str(weights)
    if args.rtdetr_model_hint:
        env["RTDETR_MODEL_HINT"] = args.rtdetr_model_hint
    if args.rtdetr_device:
        env["RTDETR_DEVICE"] = args.rtdetr_device
    if args.rtdetr_img_size:
        env["RTDETR_IMG_SIZE"] = str(args.rtdetr_img_size)
    return env


def _configured_weights(args: argparse.Namespace) -> Path | None:
    value = args.rtdetr_weights or os.getenv("RTDETR_WEIGHTS")
    if not value:
        return None
    return Path(value)


def _target_asset_dir(args: argparse.Namespace) -> Path:
    weights = _configured_weights(args)
    if weights:
        return weights.parent
    return DEFAULT_ASSET_DIR


def _probe_ultralytics(
    *,
    python_executable: str,
    run_dir: Path,
    env: dict[str, str],
    label: str,
    timeout_sec: float,
) -> ImportProbe:
    command = [
        python_executable,
        "-c",
        "import ultralytics; print(getattr(ultralytics, '__version__', 'unknown'))",
    ]
    if not Path(python_executable).is_file():
        return ImportProbe(ready=False, version=None, command=command, result=None)
    result = _run_command(
        name=f"ultralytics_import_{label}",
        command=command,
        stdout_path=run_dir / "raw_outputs" / f"ultralytics_import_{label}.stdout.txt",
        stderr_path=run_dir / "raw_outputs" / f"ultralytics_import_{label}.stderr.txt",
        env=env,
        timeout_sec=timeout_sec,
    )
    version = result.stdout_tail.strip().splitlines()[-1].strip() if result.ok and result.stdout_tail.strip() else None
    return ImportProbe(ready=result.ok, version=version, command=command, result=result)


def _sha256_file(path: Path, max_bytes: int = 1_000_000_000) -> str | None:
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size > max_bytes:
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _asset_payload(args: argparse.Namespace) -> dict[str, Any]:
    weights = _configured_weights(args)
    configured = weights is not None
    ready = bool(weights and weights.is_file())
    payload: dict[str, Any] = {
        "rtdetr_weights_configured": configured,
        "rtdetr_weights_ready": ready,
        "expected_asset_dir": str(_target_asset_dir(args)),
        "default_asset_contract_path": str(DEFAULT_ASSET_PATH),
    }
    if weights:
        payload["rtdetr_weights_path"] = str(weights)
    if ready and weights:
        stat = weights.stat()
        payload["rtdetr_weights_size_bytes"] = stat.st_size
        payload["rtdetr_weights_sha256"] = _sha256_file(weights)
    else:
        payload["rtdetr_weights_size_bytes"] = None
        payload["rtdetr_weights_sha256"] = None
    return payload


def _edge_values_from_unlock(unlock_summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "unlock_edge_rtdetr_backend_registered": unlock_summary.get("edge_rtdetr_backend_registered"),
        "unlock_edge_rtdetr_command_supported": unlock_summary.get("edge_rtdetr_command_supported"),
        "unlock_edge_rtdetr_command_passed": unlock_summary.get("edge_rtdetr_command_passed"),
        "unlock_edge_rtdetr_fallback_used": unlock_summary.get("edge_rtdetr_fallback_used"),
        "unlock_edge_rtdetr_no_fallback_verified": unlock_summary.get("edge_rtdetr_no_fallback_verified"),
        "unlock_phase12c_rtdetr_rows_available": unlock_summary.get("phase12c_rtdetr_rows_available"),
        "unlock_phase12c_rtdetr_backend_unavailable_count": unlock_summary.get("phase12c_rtdetr_backend_unavailable_count"),
    }


def _run_dependency_install(
    *,
    args: argparse.Namespace,
    run_dir: Path,
    env: dict[str, str],
) -> CommandResult | None:
    if not args.execute_dependency_install:
        return None
    if not Path(args.python_executable).is_file():
        return CommandResult(
            name="dependency_install",
            command=[args.python_executable, "-m", "pip", "install", "ultralytics"],
            exit_code=127,
            duration_sec=0.0,
            stdout_path=str(run_dir / "install_stdout.txt"),
            stderr_path=str(run_dir / "install_stderr.txt"),
            stdout_tail="",
            stderr_tail=f"target Python not found: {args.python_executable}",
        )
    if args.rtdetr_requirements:
        command = [args.python_executable, "-m", "pip", "install", "-r", str(args.rtdetr_requirements)]
    else:
        command = [args.python_executable, "-m", "pip", "install", "ultralytics"]
    return _run_command(
        name="dependency_install",
        command=command,
        stdout_path=run_dir / "install_stdout.txt",
        stderr_path=run_dir / "install_stderr.txt",
        env=env,
        timeout_sec=args.install_timeout_sec,
    )


def _run_post_setup_smoke(
    *,
    args: argparse.Namespace,
    run_dir: Path,
    env: dict[str, str],
    dependency_ready: bool,
    weights_ready: bool,
) -> tuple[CommandResult | None, dict[str, str]]:
    if not args.run_post_setup_smoke:
        return None, {}
    if not dependency_ready or not weights_ready or not Path(args.python_executable).is_file():
        return None, {}
    weights = _configured_weights(args)
    command = [
        args.python_executable,
        "-m",
        "workers.core.edge_perception",
        "--test",
        "rtdetr",
        "--rtdetr-weights",
        str(weights),
        "--rtdetr-model-hint",
        args.rtdetr_model_hint,
        "--rtdetr-device",
        args.rtdetr_device,
    ]
    if args.rtdetr_img_size:
        command.extend(["--rtdetr-img-size", str(args.rtdetr_img_size)])
    result = _run_command(
        name="post_setup_smoke",
        command=command,
        stdout_path=run_dir / "post_setup_smoke_stdout.txt",
        stderr_path=run_dir / "post_setup_smoke_stderr.txt",
        env=env,
        timeout_sec=args.smoke_timeout_sec,
    )
    values = _parse_key_values(result.stdout_tail + "\n" + result.stderr_tail)
    return result, values


def _run_rtdetr_rows_refresh(
    *,
    args: argparse.Namespace,
    run_dir: Path,
    env: dict[str, str],
    no_fallback_ready: bool,
) -> tuple[CommandResult | None, dict[str, Any] | None]:
    if not args.run_rtdetr_rows_refresh or not no_fallback_ready:
        return None, None
    rows_dir = run_dir / "rtdetr_rows_refresh"
    rows_dir.mkdir(exist_ok=True)
    command = [
        args.base_python,
        str(REPO_ROOT / "scripts" / "run_phase12c_perception_backend_ablation.py"),
        "--perception-backend-mode",
        "rt_detr_optional",
        "--python-executable",
        args.python_executable,
        "--output-dir",
        str(rows_dir),
        "--carla-root",
        str(args.carla_root),
    ]
    result = _run_command(
        name="rtdetr_rows_refresh",
        command=command,
        stdout_path=run_dir / "raw_outputs" / "rtdetr_rows_refresh.stdout.txt",
        stderr_path=run_dir / "raw_outputs" / "rtdetr_rows_refresh.stderr.txt",
        env=env,
        timeout_sec=args.rows_timeout_sec,
    )
    summary_path: Path | None = None
    if result.ok:
        for line in result.stdout_tail.splitlines():
            if line.startswith("experiment_dir="):
                summary_path = Path(line.split("=", 1)[1].strip()) / "summary.json"
                break
    rows_summary = _read_json(summary_path) if summary_path else None
    if rows_summary:
        _write_json(run_dir / "rtdetr_rows_summary.json", rows_summary)
        source_csv = Path(str(summary_path)).with_name("summary.csv") if summary_path else None
        if source_csv and source_csv.exists():
            shutil.copyfile(source_csv, run_dir / "rtdetr_rows_summary.csv")
    return result, rows_summary


def _classify_status(
    *,
    args: argparse.Namespace,
    target_python_exists: bool,
    dependency_after: bool,
    weights_ready: bool,
    smoke_executed: bool,
    no_fallback_verified: bool,
    fallback_used: bool | None,
) -> str:
    if dependency_after and weights_ready and smoke_executed and no_fallback_verified:
        return STATUS_PREPARED
    if args.dry_run and not args.execute_dependency_install and not smoke_executed:
        return STATUS_COMMAND_READY
    if not target_python_exists:
        return STATUS_BLOCKED
    if args.execute_dependency_install and not dependency_after:
        return STATUS_BLOCKED
    if args.run_post_setup_smoke and fallback_used is True:
        return STATUS_BLOCKED
    if args.run_post_setup_smoke and smoke_executed and not no_fallback_verified:
        return STATUS_BLOCKED
    if not weights_ready and not args.dry_run:
        return STATUS_BLOCKED
    return STATUS_COMMAND_READY


def _recommended_next_phase(
    *,
    status: str,
    dependency_after: bool,
    weights_ready: bool,
    smoke_executed: bool,
    fallback_used: bool | None,
    no_fallback_verified: bool,
) -> str:
    if status == STATUS_PREPARED or no_fallback_verified:
        return "R1-RT-DETR-UNLOCK-RERUN"
    if smoke_executed and fallback_used is True:
        return "R1-RT-DETR-ADAPTER-FIX"
    if not dependency_after or not weights_ready:
        return "R1-RT-DETR-ASSET-SETUP"
    return "BLOCKED"


def _write_commands(path: Path, args: argparse.Namespace, run_dir: Path) -> None:
    weights_contract = _configured_weights(args) or DEFAULT_ASSET_PATH
    requirements_text = (
        f"{args.python_executable} -m pip install -r {args.rtdetr_requirements}"
        if args.rtdetr_requirements
        else f"{args.python_executable} -m pip install ultralytics"
    )
    lines = [
        "# Phase 12C-R1-RT-DETR-ASSET-SETUP commands",
        "# These commands do not start CARLA route runtime and do not download weights automatically.",
        "",
        "# Dry-run / command scaffold",
        (
            "python scripts\\run_phase12c_rtdetr_asset_setup.py --dry-run "
            "--output-dir experiments\\phase12 "
            "--rtdetr-unlock-evidence-dir experiments\\phase12\\20260702T022636Z-1"
        ),
        "",
        "# Audit current local setup",
        (
            f"python scripts\\run_phase12c_rtdetr_asset_setup.py --output-dir experiments\\phase12 "
            f"--rtdetr-unlock-evidence-dir experiments\\phase12\\20260702T022636Z-1 "
            f"--python-executable {args.python_executable} --carla-root {args.carla_root}"
        ),
        "",
        "# Prepare asset directory only",
        (
            f"python scripts\\run_phase12c_rtdetr_asset_setup.py --output-dir experiments\\phase12 "
            f"--prepare-asset-dir --python-executable {args.python_executable} --carla-root {args.carla_root}"
        ),
        "",
        "# Explicit dependency install into the CARLA Python 3.12 runtime",
        (
            f"python scripts\\run_phase12c_rtdetr_asset_setup.py --output-dir experiments\\phase12 "
            f"--python-executable {args.python_executable} --carla-root {args.carla_root} "
            "--execute-dependency-install"
        ),
        "",
        "# Equivalent pip command executed only when --execute-dependency-install is passed",
        requirements_text,
        "",
        "# Operator-provided local weights contract",
        f'$env:RTDETR_WEIGHTS = "{weights_contract}"',
        f'$env:RTDETR_MODEL_HINT = "{args.rtdetr_model_hint}"',
        f'$env:RTDETR_DEVICE = "{args.rtdetr_device}"',
        f'$env:RTDETR_IMG_SIZE = "{args.rtdetr_img_size or 640}"',
        "",
        "# Post-setup EdgePerception no-fallback smoke; this does not start CARLA route runtime",
        (
            f"python scripts\\run_phase12c_rtdetr_asset_setup.py --output-dir experiments\\phase12 "
            f"--python-executable {args.python_executable} --carla-root {args.carla_root} "
            "--run-post-setup-smoke"
        ),
        "",
        "# Optional RT-DETR-only Phase 12C scaffold refresh after no-fallback smoke passes",
        (
            "python scripts\\run_phase12c_perception_backend_ablation.py "
            f"--perception-backend-mode rt_detr_optional --python-executable {args.python_executable} "
            "--output-dir experiments\\phase12"
        ),
        "",
        f"# This evidence run directory: {run_dir}",
    ]
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_readme(path: Path, summary: dict[str, Any]) -> None:
    body = f"""# Phase 12C-R1-RT-DETR-ASSET-SETUP

Status:

```text
{summary['status_line']}
```

This evidence pack is dependency and local asset setup only. It does not start
CARLA route runtime, does not download model weights, and does not modify
baseline requirements.

Key fields:

```text
target_perception_backend={summary['target_perception_backend']}
ultralytics_import_ready_before={summary['ultralytics_import_ready_before']}
ultralytics_import_ready_after={summary['ultralytics_import_ready_after']}
dependency_install_requested={summary['dependency_install_requested']}
dependency_install_executed={summary['dependency_install_executed']}
rtdetr_weights_configured={summary['rtdetr_weights_configured']}
rtdetr_weights_ready={summary['rtdetr_weights_ready']}
edge_rtdetr_command_passed={summary['edge_rtdetr_command_passed']}
edge_rtdetr_fallback_used={summary['edge_rtdetr_fallback_used']}
edge_rtdetr_no_fallback_verified={summary['edge_rtdetr_no_fallback_verified']}
phase12c_rtdetr_rows_available={summary['phase12c_rtdetr_rows_available']}
recommended_next_phase={summary['recommended_next_phase']}
```
"""
    path.write_text(body, encoding="utf-8")


def _manifest_payload(args: argparse.Namespace, run_dir: Path, summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": PHASE,
        "status": summary["status"],
        "status_line": summary["status_line"],
        "created_at_utc": _utc_now().isoformat(),
        "run_dir": str(run_dir),
        "output_files": [
            "manifest.json",
            "summary.json",
            "summary.csv",
            "commands.txt",
            "environment.json",
            "README.md",
            "raw_outputs/",
        ],
        "target_python": args.python_executable,
        "carla_root": str(args.carla_root),
        "carla_import_required": False,
        "carla_server_required": False,
        "dependency_install_requested": summary["dependency_install_requested"],
        "dependency_install_executed": summary["dependency_install_executed"],
        "post_setup_smoke_executed": summary["post_setup_smoke_executed"],
        "raw_runtime_evidence_committed": False,
        "model_weights_committed": False,
        **BOUNDARY_FIELDS,
    }


def _environment_payload(args: argparse.Namespace, run_dir: Path) -> dict[str, Any]:
    configured_weights = _configured_weights(args)
    return {
        "phase": PHASE,
        "run_dir": str(run_dir),
        "platform": platform.platform(),
        "base_python_executable": sys.executable,
        "base_python_version": sys.version,
        "target_python": args.python_executable,
        "target_python_exists": Path(args.python_executable).is_file(),
        "carla_root": str(args.carla_root),
        "carla_root_exists": args.carla_root.exists(),
        "carla_root_env": os.getenv("CARLA_ROOT"),
        "rtdetr_weights_env_present": "RTDETR_WEIGHTS" in os.environ,
        "rtdetr_weights_configured_path": str(configured_weights) if configured_weights else None,
        "rtdetr_model_hint": args.rtdetr_model_hint,
        "rtdetr_device": args.rtdetr_device,
        "rtdetr_img_size": args.rtdetr_img_size,
        "path_contains_carla_runtime": str(args.carla_root) in os.getenv("PATH", ""),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=PHASE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timestamp", default=None)
    parser.add_argument("--python-executable", default=DEFAULT_CARLA_PYTHON)
    parser.add_argument("--base-python", default=sys.executable)
    parser.add_argument("--carla-root", type=Path, default=DEFAULT_CARLA_ROOT)
    parser.add_argument("--rtdetr-unlock-evidence-dir", type=Path, default=DEFAULT_RTDETR_UNLOCK_EVIDENCE_DIR)
    parser.add_argument("--lightweight-evidence-dir", type=Path, default=DEFAULT_LIGHTWEIGHT_EVIDENCE_DIR)
    parser.add_argument("--rtdetr-weights", default=None)
    parser.add_argument("--rtdetr-model-hint", default=os.getenv("RTDETR_MODEL_HINT", "rtdetr-l.pt"))
    parser.add_argument("--rtdetr-device", default=os.getenv("RTDETR_DEVICE", "auto"))
    parser.add_argument("--rtdetr-img-size", type=int, default=int(os.getenv("RTDETR_IMG_SIZE", "0") or 0) or None)
    parser.add_argument("--rtdetr-requirements", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--prepare-asset-dir", action="store_true")
    parser.add_argument("--execute-dependency-install", action="store_true")
    parser.add_argument("--run-post-setup-smoke", action="store_true")
    parser.add_argument("--run-rtdetr-rows-refresh", action="store_true")
    parser.add_argument("--install-timeout-sec", type=float, default=900.0)
    parser.add_argument("--probe-timeout-sec", type=float, default=60.0)
    parser.add_argument("--smoke-timeout-sec", type=float, default=240.0)
    parser.add_argument("--rows-timeout-sec", type=float, default=240.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    args.output_dir = _resolve_repo_path(args.output_dir)
    args.rtdetr_unlock_evidence_dir = _resolve_repo_path(args.rtdetr_unlock_evidence_dir)
    args.lightweight_evidence_dir = _resolve_repo_path(args.lightweight_evidence_dir)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_dir = _next_run_dir(args.output_dir, args.timestamp)
    env = _env_with_runtime_contract(args)

    unlock_summary = _read_json(args.rtdetr_unlock_evidence_dir / "summary.json")
    target_python_exists = Path(args.python_executable).is_file()
    before_probe = _probe_ultralytics(
        python_executable=args.python_executable,
        run_dir=run_dir,
        env=env,
        label="before",
        timeout_sec=args.probe_timeout_sec,
    )

    asset_dir_prepared = False
    if args.prepare_asset_dir:
        _target_asset_dir(args).mkdir(parents=True, exist_ok=True)
        asset_dir_prepared = True

    install_result = _run_dependency_install(args=args, run_dir=run_dir, env=env)
    dependency_install_executed = bool(install_result is not None and install_result.duration_sec > 0.0)
    if install_result is not None and install_result.duration_sec == 0.0:
        (run_dir / "install_stdout.txt").write_text(install_result.stdout_tail, encoding="utf-8")
        (run_dir / "install_stderr.txt").write_text(install_result.stderr_tail, encoding="utf-8")

    after_probe = _probe_ultralytics(
        python_executable=args.python_executable,
        run_dir=run_dir,
        env=env,
        label="after",
        timeout_sec=args.probe_timeout_sec,
    )
    asset = _asset_payload(args)

    smoke_result, smoke_values = _run_post_setup_smoke(
        args=args,
        run_dir=run_dir,
        env=env,
        dependency_ready=after_probe.ready,
        weights_ready=asset["rtdetr_weights_ready"],
    )
    post_setup_smoke_executed = smoke_result is not None
    smoke_passed = smoke_result.ok if smoke_result else None
    fallback_used = _bool_value(smoke_values, "edge_rtdetr_fallback_used") if smoke_result else None
    no_fallback_verified = (
        bool(smoke_result and smoke_result.ok)
        and _bool_value(smoke_values, "edge_rtdetr_no_fallback_verified") is True
        and fallback_used is False
    )
    edge_backend_registered = (
        _bool_value(smoke_values, "rtdetr_backend_registered")
        if smoke_result
        else bool(unlock_summary.get("edge_rtdetr_backend_registered", False))
    )
    edge_command_supported = (
        _bool_value(smoke_values, "edge_rtdetr_command_supported")
        if smoke_result
        else bool(unlock_summary.get("edge_rtdetr_command_supported", False))
    )

    rows_result, rows_summary = _run_rtdetr_rows_refresh(
        args=args,
        run_dir=run_dir,
        env=env,
        no_fallback_ready=no_fallback_verified,
    )
    if rows_summary:
        rows_available = any(
            row.get("backend_available") is True
            for row in rows_summary.get("results", [])
            if row.get("perception_backend_mode") == "rt_detr_optional"
        )
        rows_unavailable_count = rows_summary.get("backend_unavailable_count")
    else:
        rows_available = bool(unlock_summary.get("phase12c_rtdetr_rows_available", False))
        rows_unavailable_count = unlock_summary.get("phase12c_rtdetr_backend_unavailable_count")

    status = _classify_status(
        args=args,
        target_python_exists=target_python_exists,
        dependency_after=after_probe.ready,
        weights_ready=asset["rtdetr_weights_ready"],
        smoke_executed=post_setup_smoke_executed,
        no_fallback_verified=no_fallback_verified,
        fallback_used=fallback_used,
    )
    recommended_next_phase = _recommended_next_phase(
        status=status,
        dependency_after=after_probe.ready,
        weights_ready=asset["rtdetr_weights_ready"],
        smoke_executed=post_setup_smoke_executed,
        fallback_used=fallback_used,
        no_fallback_verified=no_fallback_verified,
    )

    summary: dict[str, Any] = {
        "phase": PHASE,
        "status": status,
        "status_line": STATUS_LINES[status],
        "dry_run": bool(args.dry_run),
        "runtime_scope": RUNTIME_SCOPE,
        "run_dir": str(run_dir),
        "rtdetr_unlock_evidence_dir": _display_path(args.rtdetr_unlock_evidence_dir),
        "lightweight_evidence_dir": _display_path(args.lightweight_evidence_dir),
        "target_perception_backend": "rtdetr",
        "target_python": args.python_executable,
        "target_python_exists": target_python_exists,
        "carla_root": str(args.carla_root),
        "carla_root_exists": args.carla_root.exists(),
        "ultralytics_import_ready_before": before_probe.ready,
        "ultralytics_import_ready_after": after_probe.ready,
        "ultralytics_version_before": before_probe.version,
        "ultralytics_version_after": after_probe.version,
        "dependency_install_requested": bool(args.execute_dependency_install),
        "dependency_install_executed": dependency_install_executed,
        "dependency_install_exit_code": install_result.exit_code if install_result else None,
        **BOUNDARY_FIELDS,
        **asset,
        "rtdetr_model_hint": args.rtdetr_model_hint,
        "rtdetr_device": args.rtdetr_device,
        "rtdetr_img_size": args.rtdetr_img_size,
        "asset_dir_prepared": asset_dir_prepared,
        "edge_rtdetr_backend_registered": edge_backend_registered,
        "edge_rtdetr_command_supported": edge_command_supported,
        "edge_rtdetr_command_passed": smoke_passed,
        "edge_rtdetr_fallback_used": fallback_used,
        "edge_rtdetr_no_fallback_verified": no_fallback_verified,
        "post_setup_smoke_executed": post_setup_smoke_executed,
        "phase12c_rtdetr_rows_available": rows_available,
        "phase12c_rtdetr_backend_unavailable_count": rows_unavailable_count,
        "rtdetr_rows_refresh_executed": rows_result is not None,
        "recommended_next_phase": recommended_next_phase,
        "command_results": {
            "ultralytics_import_before": _result_payload(before_probe.result),
            "dependency_install": _result_payload(install_result),
            "ultralytics_import_after": _result_payload(after_probe.result),
            "post_setup_smoke": _result_payload(smoke_result),
            "rtdetr_rows_refresh": _result_payload(rows_result),
        },
        "unlock_evidence_fields": _edge_values_from_unlock(unlock_summary),
        "assertions": {
            "no_carla_import_in_parent": True,
            "carla_route_runtime_not_started": True,
            "weights_not_downloaded": True,
            "weights_not_committed": True,
            "baseline_requirements_not_modified": True,
            "dependency_install_requires_explicit_flag": True,
            "all_boundary_fields_false": all(value is False for value in BOUNDARY_FIELDS.values() if isinstance(value, bool)),
        },
    }

    _write_json(run_dir / "summary.json", summary)
    _write_csv(run_dir / "summary.csv", summary)
    _write_json(run_dir / "manifest.json", _manifest_payload(args, run_dir, summary))
    _write_json(run_dir / "environment.json", _environment_payload(args, run_dir))
    _write_commands(run_dir / "commands.txt", args, run_dir)
    _write_readme(run_dir / "README.md", summary)

    print(summary["status_line"])
    print(f"evidence_dir={run_dir}")
    print(f"ultralytics_import_ready_before={str(before_probe.ready).lower()}")
    print(f"ultralytics_import_ready_after={str(after_probe.ready).lower()}")
    print(f"dependency_install_requested={str(bool(args.execute_dependency_install)).lower()}")
    print(f"dependency_install_executed={str(dependency_install_executed).lower()}")
    print(f"rtdetr_weights_configured={str(asset['rtdetr_weights_configured']).lower()}")
    print(f"rtdetr_weights_ready={str(asset['rtdetr_weights_ready']).lower()}")
    print(f"edge_rtdetr_command_passed={str(smoke_passed).lower() if smoke_passed is not None else 'null'}")
    print(f"edge_rtdetr_fallback_used={str(fallback_used).lower() if fallback_used is not None else 'null'}")
    print(f"edge_rtdetr_no_fallback_verified={str(no_fallback_verified).lower()}")
    print(f"phase12c_rtdetr_rows_available={str(rows_available).lower()}")
    print(f"recommended_next_phase={recommended_next_phase}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
