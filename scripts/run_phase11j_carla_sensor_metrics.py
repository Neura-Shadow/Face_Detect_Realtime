"""
Phase 11J CARLA sensor metrics runner.

此 runner 使用 dedicated Python 3.12 CARLA runtime 執行真實 CARLA smoke，
並啟用 collision / lane invasion sensors、speed samples 與 distance metrics。

這是 smoke-level instrumentation，不是 route benchmark，也不是 CARLA
Leaderboard 或完整自駕評測。
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import io
import json
import logging
import os
import platform
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workers.CARLA_Closed_Loop_Agent import CarlaClosedLoopAgent
from workers.core.carla_metrics import CarlaRuntimeMetrics
from workers.core.config import AgentConfig

DEFAULT_CARLA_ROOT = Path(os.environ.get("CARLA_ROOT", r"D:\CARLA\packages\CARLA_0.9.16"))
DEFAULT_OUTPUT_DIR = REPO_ROOT / "runtime_logs" / "carla_runs"


@dataclass(frozen=True)
class CommandResult:
    """外部命令執行結果。"""

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


def _find_carla_wheel(carla_root: Path) -> Path | None:
    dist_dir = carla_root / "PythonAPI" / "carla" / "dist"
    if not dist_dir.exists():
        return None
    wheels = sorted(dist_dir.glob("carla-*.whl"))
    return wheels[0] if wheels else None


def _read_pip_show_version(text: str) -> str | None:
    for line in text.splitlines():
        if line.startswith("Version:"):
            return line.split(":", 1)[1].strip()
    return None


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


def _build_config(args: argparse.Namespace) -> AgentConfig:
    config = AgentConfig.load()
    carla_cfg = dataclasses.replace(
        config.carla,
        host=args.host,
        port=args.port,
        timeout_sec=args.timeout_sec,
        town=args.town,
        spawn_point_index=args.spawn_point_index,
        synchronous_mode=not args.async_world,
        camera_width=args.camera_width,
        camera_height=args.camera_height,
    )
    perception_cfg = dataclasses.replace(
        config.perception,
        backend=args.perception_backend,
        model_name=args.perception_model,
    )
    trigger_cfg = dataclasses.replace(
        config.trigger,
        cooldown_sec=0.0 if args.enable_vlm else config.trigger.cooldown_sec,
        force_interval_frames=args.force_vlm_every,
    )
    telemetry_cfg = dataclasses.replace(
        config.telemetry,
        publish_interval_sec=0.1,
        batch_size=4,
    )
    supabase_cfg = config.supabase
    if not args.publish_telemetry:
        supabase_cfg = dataclasses.replace(config.supabase, url="", key="")

    return dataclasses.replace(
        config,
        agent_id="phase11j-carla-sensor-metrics",
        mode="carla",
        main_loop_hz=args.loop_hz,
        carla=carla_cfg,
        perception=perception_cfg,
        trigger=trigger_cfg,
        telemetry=telemetry_cfg,
        supabase=supabase_cfg,
    )


async def _run_sensor_smoke(args: argparse.Namespace, metrics: CarlaRuntimeMetrics) -> None:
    config = _build_config(args)
    agent = CarlaClosedLoopAgent(
        config=config,
        enable_vlm=args.enable_vlm,
        runtime_metrics=metrics,
        enable_metric_sensors=args.enable_metric_sensors,
        require_sensors=args.require_sensors,
    )
    await agent.run(max_steps=args.steps)


def _capture_sensor_smoke(args: argparse.Namespace, metrics: CarlaRuntimeMetrics) -> CommandResult:
    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s"))
    root = logging.getLogger()
    previous_level = root.level
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    started = time.perf_counter()
    try:
        asyncio.run(_run_sensor_smoke(args, metrics))
        returncode = 0
        stderr = ""
    except Exception as exc:
        returncode = 1
        stderr = str(exc)
        logging.getLogger(__name__).exception("Phase 11J sensor metrics smoke failed")
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)

    return CommandResult(
        name="phase11j_sensor_metrics_smoke",
        command=[sys.executable, *sys.argv],
        returncode=returncode,
        stdout=log_stream.getvalue().strip(),
        stderr=stderr,
        duration_sec=round(time.perf_counter() - started, 3),
    )


def _environment_commands(args: argparse.Namespace, env: dict[str, str]) -> list[CommandResult]:
    commands = [
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
            [sys.executable, "-c", "import sys, platform; print(sys.executable); print(sys.version); print(platform.platform())"],
            env=env,
            timeout_sec=30,
        ),
        _run_command(
            "carla_import",
            [sys.executable, "-c", "import carla; print(carla.__file__)"],
            env=env,
            timeout_sec=30,
        ),
        _run_command("pip_show_carla", [sys.executable, "-m", "pip", "show", "carla"], env=env, timeout_sec=30),
    ]
    if platform.system().lower() == "windows":
        commands.append(
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
    return commands


def _build_manifest(
    args: argparse.Namespace,
    *,
    run_dir: Path,
    carla_version: str | None,
    wheel: Path | None,
    result: str,
    regression_passed: bool | None,
) -> dict[str, Any]:
    server_executable = args.carla_root / "CarlaUE4.exe"
    return {
        "phase": "Phase 11J",
        "status": "sensor_metrics_smoke_pass" if result == "passed" else "sensor_metrics_smoke_failed",
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
        "perception_backend": args.perception_backend,
        "require_server": args.require_server,
        "server_executable": str(server_executable) if server_executable.exists() else None,
        "sensor_metrics_enabled": args.enable_metric_sensors,
        "require_sensors": args.require_sensors,
        "collision_sensor_requested": args.enable_metric_sensors,
        "lane_invasion_sensor_requested": args.enable_metric_sensors,
        "speed_distance_metrics_enabled": True,
        "benchmark_scope": "smoke_only",
        "route_completion_verified": False,
        "infraction_benchmark_verified": False,
        "leaderboard_evaluated": False,
        "result": result,
        "regression_passed": regression_passed,
    }


def _build_text_report(title: str, results: list[CommandResult]) -> str:
    lines = [title, ""]
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


def _build_commands_text(args: argparse.Namespace, results: list[CommandResult]) -> str:
    lines = [
        "$env:CARLA_ROOT = " + json.dumps(str(args.carla_root), ensure_ascii=False),
        "",
        subprocess.list2cmdline([sys.executable, *sys.argv]),
        "",
    ]
    for result in results:
        lines.append(result.command_text)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MA-VLNA Phase 11J CARLA sensor metrics runner")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--timeout-sec", type=float, default=5.0)
    parser.add_argument("--steps", type=int, default=50)
    parser.add_argument("--loop-hz", type=int, default=20)
    parser.add_argument("--town", default="")
    parser.add_argument("--spawn-point-index", type=int, default=0)
    parser.add_argument("--camera-width", type=int, default=320)
    parser.add_argument("--camera-height", type=int, default=180)
    parser.add_argument("--async-world", action="store_true")
    parser.add_argument("--perception-backend", default="dummy", choices=["dummy", "yolo", "yolov9", "rtdetr"])
    parser.add_argument("--perception-model", default="dummy")
    parser.add_argument("--enable-vlm", action="store_true")
    parser.add_argument("--force-vlm-every", type=int, default=0)
    parser.add_argument("--publish-telemetry", action="store_true")
    parser.add_argument("--require-server", action="store_true")
    parser.add_argument("--enable-metric-sensors", action="store_true")
    parser.add_argument("--require-sensors", action="store_true")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--carla-root", type=Path, default=DEFAULT_CARLA_ROOT)
    parser.add_argument("--base-python", default="python")
    parser.add_argument("--run-regressions", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    args.carla_root = args.carla_root.resolve()
    run_dir = _timestamped_run_dir(args.output_dir)

    env = os.environ.copy()
    env["CARLA_ROOT"] = str(args.carla_root)
    env["PYTHONIOENCODING"] = "utf-8"

    environment_results = _environment_commands(args, env)
    metrics = CarlaRuntimeMetrics()
    metrics.carla_import_ok = next((item.ok for item in environment_results if item.name == "carla_import"), False)
    metrics.server_reachable = _tcp_reachable(args.host, args.port)
    metrics.steps_requested = args.steps

    phase11d_result = _run_command(
        "phase11d_require_ready",
        [
            sys.executable,
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
    )

    command_results: list[CommandResult] = [phase11d_result]
    smoke_result: CommandResult | None = None
    regression_results: list[CommandResult] = []

    if phase11d_result.ok:
        smoke_result = _capture_sensor_smoke(args, metrics)
        command_results.append(smoke_result)

    result = "failed"
    if smoke_result and smoke_result.ok and metrics.steps_completed >= args.steps:
        sensors_ok = (
            not args.require_sensors
            or (metrics.collision_sensor_attached and metrics.lane_invasion_sensor_attached)
        )
        result = "passed" if sensors_ok else "sensor_blocked"

    if result == "passed" and args.run_regressions:
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
                    [sys.executable, "scripts\\run_phase11_carla_checks.py"],
                    env=env,
                    timeout_sec=180,
                ),
                _run_command(
                    "py312_phase11d_require_ready",
                    [
                        sys.executable,
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
                        sys.executable,
                        "-m",
                        "py_compile",
                        "scripts\\run_phase11b_real_carla_smoke.py",
                        "scripts\\run_phase11d_carla_provisioning_gate.py",
                        "scripts\\run_phase11i_carla_evidence_pack.py",
                        "scripts\\run_phase11j_carla_sensor_metrics.py",
                        "workers\\core\\carla_metrics.py",
                    ],
                    env=env,
                    timeout_sec=60,
                ),
            ]
        )
        if not all(item.ok for item in regression_results):
            result = "failed"

    regression_passed = bool(regression_results) and all(item.ok for item in regression_results)
    metrics_dict = metrics.to_metrics_dict(
        perception_backend=args.perception_backend,
        vlm_enabled=args.enable_vlm,
        fallback_used=False,
        result="passed" if result == "passed" else "failed",
    )
    if args.run_regressions:
        metrics_dict["regression_passed"] = regression_passed

    carla_version = _read_pip_show_version(next((item.stdout for item in environment_results if item.name == "pip_show_carla"), ""))
    manifest = _build_manifest(
        args,
        run_dir=run_dir,
        carla_version=carla_version,
        wheel=_find_carla_wheel(args.carla_root),
        result="passed" if result == "passed" else "failed",
        regression_passed=regression_passed if args.run_regressions else None,
    )

    all_results = environment_results + command_results + regression_results
    _write_raw_outputs(run_dir, all_results)
    _write_json(run_dir / "manifest.json", manifest)
    _write_json(run_dir / "metrics.json", metrics_dict)
    _write_jsonl(run_dir / "events.jsonl", metrics.to_events("passed" if result == "passed" else "failed"))
    (run_dir / "commands.txt").write_text(_build_commands_text(args, command_results + regression_results), encoding="utf-8")
    (run_dir / "environment.txt").write_text(_build_text_report("# Phase 11J environment snapshot", environment_results), encoding="utf-8")
    (run_dir / "regression.txt").write_text(_build_text_report("# Phase 11J regression proof", command_results + regression_results), encoding="utf-8")

    if result == "passed":
        print(
            "Phase 11J Sensor Metrics Pass — real CARLA smoke generated collision, lane invasion, speed, and distance instrumentation."
        )
        print(f"evidence_dir={run_dir}")
        return 0

    if result == "sensor_blocked":
        print("Phase 11J Sensor Blocked — required CARLA metric sensors could not be attached.")
    else:
        failing = next((item for item in command_results + regression_results if not item.ok), None)
        reason = f"{failing.name} exit={failing.returncode}" if failing else "unknown"
        print(f"Phase 11J Runtime Failed — sensor metrics run failed: {reason}")
    print(f"evidence_dir={run_dir}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
