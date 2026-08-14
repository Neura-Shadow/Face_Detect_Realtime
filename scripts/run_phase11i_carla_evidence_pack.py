"""
Phase 11I CARLA runtime evidence pack runner.

此腳本只負責蒐集真實 CARLA smoke test 的可審核證據：

1. 建立 timestamped evidence directory。
2. 執行 Phase 11D ready gate。
3. 執行 Phase 11C 5-step 與 50-step real CARLA smoke。
4. 產生 manifest / metrics / events / commands / environment / regression。

它不修改 MA-VLNA 核心控制邏輯，不做 CARLA Leaderboard，也不宣稱 route
completion 或 infraction metrics。沒有感測器量測的欄位一律寫入 null。
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CARLA_ROOT = Path(os.environ.get("CARLA_ROOT", r"D:\CARLA\packages\CARLA_0.9.16"))
DEFAULT_OUTPUT_DIR = REPO_ROOT / "runtime_logs" / "carla_runs"

CONTROL_RE = re.compile(r"\[CARLA\] control #(?P<step>\d+):.*? action=(?P<action>[a-z_]+)")
REACHED_STEPS_RE = re.compile(r"達到指定 CARLA closed-loop 步數: (?P<steps>\d+)")


@dataclass(frozen=True)
class CommandResult:
    """單一外部命令的執行結果。"""

    name: str
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_sec: float

    @property
    def command_text(self) -> str:
        return subprocess.list2cmdline(self.command)

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_command(
    name: str,
    command: list[str],
    *,
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
        return CommandResult(
            name=name,
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout.strip(),
            stderr=completed.stderr.strip(),
            duration_sec=round(time.perf_counter() - started, 3),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return CommandResult(
            name=name,
            command=command,
            returncode=124,
            stdout=stdout.strip(),
            stderr=(stderr.strip() or f"timeout after {timeout_sec}s"),
            duration_sec=round(time.perf_counter() - started, 3),
        )


def _tcp_reachable(host: str, port: int, timeout_sec: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            return True
    except OSError:
        return False


def _timestamped_run_dir(output_dir: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = output_dir / stamp
    suffix = 1
    while run_dir.exists():
        run_dir = output_dir / f"{stamp}-{suffix}"
        suffix += 1
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "raw_outputs").mkdir(parents=True, exist_ok=True)
    return run_dir


def _read_pip_show_version(text: str) -> str | None:
    for line in text.splitlines():
        if line.startswith("Version:"):
            return line.split(":", 1)[1].strip()
    return None


def _find_carla_wheel(carla_root: Path) -> Path | None:
    dist_dir = carla_root / "PythonAPI" / "carla" / "dist"
    if not dist_dir.exists():
        return None
    wheels = sorted(dist_dir.glob("carla-*.whl"))
    return wheels[0] if wheels else None


def _parse_control_events(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for match in CONTROL_RE.finditer(text):
        step = int(match.group("step"))
        events.append(
            {
                "event": "step",
                "step": step,
                "rgb_frame_received": True,
                "planner_action": match.group("action"),
                "control_applied": True,
                "world_tick_advanced": True,
            }
        )
    return events


def _steps_completed(text: str) -> int:
    reached = [int(match.group("steps")) for match in REACHED_STEPS_RE.finditer(text)]
    controls = [int(match.group("step")) for match in CONTROL_RE.finditer(text)]
    return max(reached + controls, default=0)


def _build_metrics(args: argparse.Namespace, smoke_result: CommandResult) -> dict[str, Any]:
    output = "\n".join(part for part in (smoke_result.stdout, smoke_result.stderr) if part)
    steps_completed = _steps_completed(output)
    setup_completed = "CARLA adapter setup 完成" in output
    cleanup_completed = "Phase 11 CARLA closed-loop runner stopped" in output
    ego_spawned = "ego vehicle spawned" in output
    rgb_frame_received = "RGB camera attached" in output or steps_completed > 0
    control_applied = bool(CONTROL_RE.search(output))
    result = "passed" if smoke_result.ok and steps_completed >= args.steps else "failed"

    return {
        "metrics_scope": "real_carla_smoke_only_not_benchmark",
        "steps_requested": args.steps,
        "steps_completed": steps_completed,
        "setup_completed": setup_completed,
        "cleanup_completed": cleanup_completed,
        "carla_import_ok": True,
        "server_reachable": True,
        "ego_spawned": ego_spawned,
        "rgb_frame_received": rgb_frame_received,
        "control_applied": control_applied,
        "world_tick_advanced": control_applied and steps_completed > 0,
        "vlm_enabled": args.enable_vlm,
        "perception_backend": args.perception_backend,
        "collision_count": None,
        "lane_invasion_count": None,
        "avg_speed_kmh": None,
        "max_speed_kmh": None,
        "distance_traveled_m": None,
        "fallback_used": False,
        "telemetry_fallback_used": "fallback 本地檔案" in output or "telemetry_fallback.jsonl" in output,
        "route_completion_verified": False,
        "infraction_metrics_verified": False,
        "leaderboard_evaluated": False,
        "result": result,
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, events: list[dict[str, Any]]) -> None:
    lines = [json.dumps(event, ensure_ascii=False) for event in events]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_raw_outputs(run_dir: Path, results: list[CommandResult]) -> None:
    raw_dir = run_dir / "raw_outputs"
    for result in results:
        safe_name = result.name.replace(" ", "_")
        (raw_dir / f"{safe_name}_stdout.txt").write_text(result.stdout + "\n", encoding="utf-8")
        (raw_dir / f"{safe_name}_stderr.txt").write_text(result.stderr + "\n", encoding="utf-8")


def _build_environment_text(results: list[CommandResult], host: str, port: int) -> str:
    lines = ["# Phase 11I environment snapshot", ""]
    lines.append(f"captured_at_utc={_utc_now()}")
    lines.append(f"platform={platform.platform()}")
    lines.append(f"tcp_reachable={_tcp_reachable(host, port)}")
    lines.append("")
    for result in results:
        lines.append(f"## {result.name}")
        lines.append(f"command: {result.command_text}")
        lines.append(f"returncode: {result.returncode}")
        lines.append(f"duration_sec: {result.duration_sec}")
        lines.append("")
        lines.append("stdout:")
        lines.append(result.stdout or "(empty)")
        lines.append("")
        lines.append("stderr:")
        lines.append(result.stderr or "(empty)")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _build_commands_text(args: argparse.Namespace, commands: list[CommandResult]) -> str:
    lines = [
        "$env:CARLA_ROOT = " + json.dumps(str(args.carla_root), ensure_ascii=False),
        "",
    ]
    for result in commands:
        lines.append(result.command_text)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _build_regression_text(results: list[CommandResult]) -> str:
    lines = ["# Phase 11I regression proof", ""]
    for result in results:
        lines.append(f"## {result.name}")
        lines.append(f"command: {result.command_text}")
        lines.append(f"returncode: {result.returncode}")
        lines.append(f"duration_sec: {result.duration_sec}")
        lines.append("")
        lines.append("stdout:")
        lines.append(result.stdout or "(empty)")
        lines.append("")
        lines.append("stderr:")
        lines.append(result.stderr or "(empty)")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _build_events(metrics: dict[str, Any], smoke_output: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = [
        {"timestamp_utc": _utc_now(), "event": "setup_started", "step": None},
    ]
    if metrics["server_reachable"]:
        events.append({"timestamp_utc": _utc_now(), "event": "carla_connected", "step": None})
    if metrics["ego_spawned"]:
        events.append({"timestamp_utc": _utc_now(), "event": "ego_spawned", "step": None})
    if metrics["rgb_frame_received"]:
        events.append({"timestamp_utc": _utc_now(), "event": "rgb_frame_received", "step": 0})
    if metrics["control_applied"]:
        events.append({"timestamp_utc": _utc_now(), "event": "control_applied", "step": 0})
    if metrics["world_tick_advanced"]:
        events.append({"timestamp_utc": _utc_now(), "event": "world_tick", "step": 0})

    for event in _parse_control_events(smoke_output):
        event["timestamp_utc"] = _utc_now()
        events.append(event)

    if metrics["cleanup_completed"]:
        events.append({"timestamp_utc": _utc_now(), "event": "cleanup_completed", "step": None})
    terminal_event = "run_passed" if metrics["result"] == "passed" else "run_failed"
    events.append({"timestamp_utc": _utc_now(), "event": terminal_event, "step": metrics["steps_completed"]})
    return events


def _build_manifest(
    args: argparse.Namespace,
    *,
    run_dir: Path,
    carla_version: str | None,
    wheel: Path | None,
    result: str,
) -> dict[str, Any]:
    server_executable = args.carla_root / "CarlaUE4.exe"
    return {
        "phase": "Phase 11I",
        "status": "real_carla_runtime_smoke_pass" if result == "passed" else "real_carla_runtime_smoke_failed",
        "created_at_utc": _utc_now(),
        "run_dir": str(run_dir),
        "carla_root": str(args.carla_root),
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "carla_version": carla_version,
        "carla_wheel": wheel.name if wheel else None,
        "host": args.host,
        "port": args.port,
        "steps_requested": args.steps,
        "short_steps_requested": args.short_steps,
        "perception_backend": args.perception_backend,
        "require_server": args.require_server,
        "server_executable": str(server_executable) if server_executable.exists() else None,
        "benchmark_scope": "smoke_only",
        "route_completion_verified": False,
        "infraction_metrics_verified": False,
        "leaderboard_evaluated": False,
        "result": result,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MA-VLNA Phase 11I CARLA evidence pack runner")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--steps", type=int, default=50)
    parser.add_argument("--short-steps", type=int, default=5)
    parser.add_argument("--perception-backend", default="dummy", choices=["dummy", "yolo", "yolov9", "rtdetr"])
    parser.add_argument("--require-server", action="store_true")
    parser.add_argument("--enable-vlm", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--carla-root", type=Path, default=DEFAULT_CARLA_ROOT)
    parser.add_argument("--base-python", default="python", help="Base Python used for Python 3.10 regressions")
    parser.add_argument("--run-regressions", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    args.carla_root = args.carla_root.resolve()
    run_dir = _timestamped_run_dir(args.output_dir)

    env = os.environ.copy()
    env["CARLA_ROOT"] = str(args.carla_root)
    env["PYTHONIOENCODING"] = "utf-8"

    py = sys.executable
    environment_commands = [
        CommandResult(
            name="tcp_precheck",
            command=["tcp", args.host, str(args.port)],
            returncode=0 if _tcp_reachable(args.host, args.port) else 1,
            stdout=f"tcp_reachable={_tcp_reachable(args.host, args.port)}",
            stderr="",
            duration_sec=0.0,
        ),
        _run_command(
            "python_platform",
            [py, "-c", "import sys, platform; print(sys.executable); print(sys.version); print(platform.platform())"],
            env=env,
            timeout_sec=30,
        ),
        _run_command(
            "carla_import",
            [py, "-c", "import carla; print(carla.__file__)"],
            env=env,
            timeout_sec=30,
        ),
        _run_command("pip_show_carla", [py, "-m", "pip", "show", "carla"], env=env, timeout_sec=30),
    ]
    if platform.system().lower() == "windows":
        environment_commands.append(
            _run_command(
                "test_net_connection",
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"Test-NetConnection -ComputerName {args.host} -Port {args.port} | Select-Object ComputerName,RemoteAddress,RemotePort,TcpTestSucceeded",
                ],
                env=env,
                timeout_sec=30,
            )
        )

    phase11d_command = [
        py,
        "scripts\\run_phase11d_carla_provisioning_gate.py",
        "--carla-root",
        str(args.carla_root),
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--steps",
        str(args.steps),
        "--json",
        "--require-ready",
    ]
    phase11d_result = _run_command("phase11d_require_ready", phase11d_command, env=env, timeout_sec=60)

    command_results: list[CommandResult] = [phase11d_result]
    smoke5_result: CommandResult | None = None
    smoke50_result: CommandResult | None = None
    regression_results: list[CommandResult] = []

    if phase11d_result.ok:
        smoke5_command = [
            py,
            "scripts\\run_phase11b_real_carla_smoke.py",
            "--host",
            args.host,
            "--port",
            str(args.port),
            "--steps",
            str(args.short_steps),
            "--perception-backend",
            args.perception_backend,
        ]
        if args.require_server:
            smoke5_command.append("--require-server")
        if args.enable_vlm:
            smoke5_command.append("--enable-vlm")
        smoke5_result = _run_command("phase11c_smoke_5_step", smoke5_command, env=env, timeout_sec=240)
        command_results.append(smoke5_result)

    if smoke5_result and smoke5_result.ok:
        smoke50_command = [
            py,
            "scripts\\run_phase11b_real_carla_smoke.py",
            "--host",
            args.host,
            "--port",
            str(args.port),
            "--steps",
            str(args.steps),
            "--perception-backend",
            args.perception_backend,
        ]
        if args.require_server:
            smoke50_command.append("--require-server")
        if args.enable_vlm:
            smoke50_command.append("--enable-vlm")
        smoke50_result = _run_command("phase11c_smoke_50_step", smoke50_command, env=env, timeout_sec=300)
        command_results.append(smoke50_result)

    if smoke50_result and smoke50_result.ok and args.run_regressions:
        regression_results.extend(
            [
                _run_command(
                    "base_phase11_carla_checks",
                    [args.base_python, "scripts\\run_phase11_carla_checks.py"],
                    env=env,
                    timeout_sec=180,
                ),
                _run_command(
                    "base_demo_checks",
                    [args.base_python, "scripts\\run_demo_checks.py"],
                    env=env,
                    timeout_sec=300,
                ),
                _run_command(
                    "py312_phase11_carla_checks",
                    [py, "scripts\\run_phase11_carla_checks.py"],
                    env=env,
                    timeout_sec=180,
                ),
                _run_command(
                    "py312_phase11d_require_ready",
                    [
                        py,
                        "scripts\\run_phase11d_carla_provisioning_gate.py",
                        "--carla-root",
                        str(args.carla_root),
                        "--host",
                        args.host,
                        "--port",
                        str(args.port),
                        "--steps",
                        str(args.steps),
                        "--require-ready",
                    ],
                    env=env,
                    timeout_sec=60,
                ),
                _run_command(
                    "py312_py_compile",
                    [
                        py,
                        "-m",
                        "py_compile",
                        "scripts\\run_phase11b_real_carla_smoke.py",
                        "scripts\\run_phase11d_carla_provisioning_gate.py",
                        "scripts\\run_phase11i_carla_evidence_pack.py",
                    ],
                    env=env,
                    timeout_sec=60,
                ),
            ]
        )

    all_results = environment_commands + command_results + regression_results
    _write_raw_outputs(run_dir, all_results)

    carla_version = _read_pip_show_version(next((r.stdout for r in environment_commands if r.name == "pip_show_carla"), ""))
    wheel = _find_carla_wheel(args.carla_root)
    smoke_output = ""
    metrics: dict[str, Any]
    if smoke50_result:
        smoke_output = "\n".join(part for part in (smoke50_result.stdout, smoke50_result.stderr) if part)
        metrics = _build_metrics(args, smoke50_result)
    else:
        metrics = {
            "metrics_scope": "real_carla_smoke_only_not_benchmark",
            "steps_requested": args.steps,
            "steps_completed": 0,
            "setup_completed": False,
            "cleanup_completed": False,
            "carla_import_ok": next((r.ok for r in environment_commands if r.name == "carla_import"), False),
            "server_reachable": _tcp_reachable(args.host, args.port),
            "ego_spawned": False,
            "rgb_frame_received": False,
            "control_applied": False,
            "world_tick_advanced": False,
            "vlm_enabled": args.enable_vlm,
            "perception_backend": args.perception_backend,
            "collision_count": None,
            "lane_invasion_count": None,
            "avg_speed_kmh": None,
            "max_speed_kmh": None,
            "distance_traveled_m": None,
            "fallback_used": False,
            "telemetry_fallback_used": False,
            "route_completion_verified": False,
            "infraction_metrics_verified": False,
            "leaderboard_evaluated": False,
            "result": "failed",
        }

    regression_passed = bool(regression_results) and all(result.ok for result in regression_results)
    if args.run_regressions:
        metrics["regression_passed"] = regression_passed
    result = "passed" if metrics["result"] == "passed" and (not args.run_regressions or regression_passed) else "failed"
    if result != "passed":
        metrics["result"] = "failed"

    manifest = _build_manifest(args, run_dir=run_dir, carla_version=carla_version, wheel=wheel, result=result)
    manifest["regression_passed"] = regression_passed if args.run_regressions else None

    _write_json(run_dir / "manifest.json", manifest)
    _write_json(run_dir / "metrics.json", metrics)
    _write_jsonl(run_dir / "events.jsonl", _build_events(metrics, smoke_output))
    (run_dir / "commands.txt").write_text(_build_commands_text(args, command_results + regression_results), encoding="utf-8")
    (run_dir / "environment.txt").write_text(_build_environment_text(environment_commands, args.host, args.port), encoding="utf-8")
    (run_dir / "regression.txt").write_text(_build_regression_text(command_results + regression_results), encoding="utf-8")

    if result == "passed":
        print("Phase 11I Evidence Pack Pass — structured evidence for real CARLA 5-step and 50-step smoke generated.")
        print(f"evidence_dir={run_dir}")
        return 0

    if not phase11d_result.ok:
        print("Phase 11I Blocked — CARLA server is not running or TCP endpoint is unreachable.")
    else:
        failing = next((item for item in command_results + regression_results if not item.ok), None)
        reason = f"{failing.name} exit={failing.returncode}" if failing else "unknown"
        print(f"Phase 11I Runtime Failed — evidence run failed during real CARLA smoke: {reason}")
    print(f"evidence_dir={run_dir}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
