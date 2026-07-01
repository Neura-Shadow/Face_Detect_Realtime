"""
Phase 12C-YOLOv9-R1-SETUP child CARLA setup/spawn probe.

This child process is intended to run inside the dedicated CARLA Python 3.12
environment. It imports CARLA directly and tests the setup path stage by stage
before any YOLOv9 closed-loop route retry is attempted.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import queue
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_CARLA_ROOT = Path(os.environ.get("CARLA_ROOT", r"D:\CARLA\packages\CARLA_0.9.16"))
DEFAULT_OUTPUT_DIR = REPO_ROOT / "experiments" / "phase12"
PHASE = "Phase 12C-YOLOv9-R1-SETUP-CHILD"

STAGE_NAMES = (
    "stage_01_client_connect",
    "stage_02_world_available",
    "stage_03_town03_loaded_or_reused",
    "stage_04_settings_applied",
    "stage_05_spawn_points_loaded",
    "stage_06_ego_spawned",
    "stage_07_rgb_sensor_attached",
    "stage_08_first_rgb_frame_received",
    "stage_09_grp_route_generated",
    "stage_10_warmup_ticks_completed",
    "stage_11_cleanup_completed",
)

BOUNDARY_FIELDS = {
    "runtime_confirmation_executed": False,
    "carla_route_runtime_executed": False,
    "yolo_runtime_row_verified": False,
    "full_phase12c_perception_ablation_runtime_pass": False,
    "rt_detr_runtime_verified": False,
    "route_benchmark_verified": False,
    "infraction_benchmark_verified": False,
    "leaderboard_evaluated": False,
    "leaderboard_routes_exported": False,
    "leaderboard_route_criteria_evaluated": False,
}


@dataclass
class StageRecord:
    name: str
    started: bool = False
    finished: bool = False
    duration_sec: float | None = None
    error_type: str | None = None
    error_message: str | None = None
    timeout_sec: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.name,
            "started": self.started,
            "finished": self.finished,
            "duration_sec": self.duration_sec,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "timeout_sec": self.timeout_sec,
        }


@dataclass
class ProbeContext:
    stages: dict[str, StageRecord] = field(default_factory=lambda: {name: StageRecord(name) for name in STAGE_NAMES})
    events: list[dict[str, Any]] = field(default_factory=list)
    actors_created: list[Any] = field(default_factory=list)
    original_settings: Any | None = None
    client: Any | None = None
    world: Any | None = None
    ego_vehicle: Any | None = None
    rgb_sensor: Any | None = None
    first_frame: Any | None = None
    frame_queue: queue.Queue[Any] = field(default_factory=lambda: queue.Queue(maxsize=16))

    def event(self, event: str, **payload: Any) -> None:
        item = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **payload,
        }
        self.events.append(item)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _next_run_dir(output_dir: Path, timestamp: str | None) -> Path:
    base = timestamp or _timestamp()
    candidate = output_dir / base
    suffix = 1
    while candidate.exists():
        candidate = output_dir / f"{base}-{suffix}"
        suffix += 1
    candidate.mkdir(parents=True, exist_ok=False)
    (candidate / "raw_outputs").mkdir(parents=True, exist_ok=True)
    return candidate


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _append_carla_paths(carla_root: Path) -> None:
    python_api = carla_root / "PythonAPI" / "carla"
    agents_path = carla_root / "PythonAPI" / "carla" / "agents"
    for path in (python_api, agents_path):
        if path.exists() and str(path) not in sys.path:
            sys.path.insert(0, str(path))


def _map_matches_town(map_name: str | None, town: str) -> bool:
    if not map_name:
        return False
    leaf = str(map_name).replace("\\", "/").split("/")[-1].lower()
    target = town.lower()
    return leaf == target or leaf == f"{target}_opt"


def _location_distance(a: Any, b: Any) -> float:
    return float(math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2))


def _route_distance(route: list[Any]) -> float:
    total = 0.0
    previous = None
    for waypoint, _road_option in route:
        location = waypoint.transform.location
        if previous is not None:
            total += _location_distance(previous, location)
        previous = location
    return total


def _stage_timeout(args: argparse.Namespace, stage: str) -> float:
    if stage == "stage_03_town03_loaded_or_reused":
        return float(args.map_load_timeout_sec)
    if stage == "stage_06_ego_spawned":
        return float(args.spawn_timeout_sec)
    if stage in {"stage_07_rgb_sensor_attached", "stage_08_first_rgb_frame_received"}:
        return float(args.sensor_timeout_sec)
    if stage == "stage_10_warmup_ticks_completed":
        return float(args.warmup_timeout_sec)
    return float(args.setup_timeout_sec)


def _run_stage(ctx: ProbeContext, args: argparse.Namespace, stage: str, func: Any) -> bool:
    record = ctx.stages[stage]
    record.started = True
    record.timeout_sec = _stage_timeout(args, stage)
    ctx.event(f"{stage}_started", timeout_sec=record.timeout_sec)
    started = time.perf_counter()
    try:
        func()
    except Exception as exc:  # noqa: BLE001 - stage evidence must preserve exact failure.
        record.finished = False
        record.duration_sec = round(time.perf_counter() - started, 3)
        record.error_type = type(exc).__name__
        record.error_message = str(exc)
        ctx.event(
            f"{stage}_failed",
            duration_sec=record.duration_sec,
            error_type=record.error_type,
            error_message=record.error_message,
        )
        return False
    record.finished = True
    record.duration_sec = round(time.perf_counter() - started, 3)
    ctx.event(f"{stage}_finished", duration_sec=record.duration_sec)
    return True


def _cleanup_matching_actors(world: Any, role_name: str) -> int:
    removed = 0
    actors = world.get_actors()
    for actor in actors.filter("vehicle.*"):
        try:
            attrs = getattr(actor, "attributes", {}) or {}
            if attrs.get("role_name") == role_name:
                actor.destroy()
                removed += 1
        except Exception:
            continue
    return removed


def _destroy_created_actors(ctx: ProbeContext) -> tuple[bool, str | None]:
    errors: list[str] = []
    for actor in reversed(ctx.actors_created):
        try:
            if actor is not None and hasattr(actor, "stop"):
                actor.stop()
            if actor is not None and getattr(actor, "is_alive", False):
                actor.destroy()
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{type(exc).__name__}: {exc}")
    ctx.actors_created.clear()
    if ctx.world is not None and ctx.original_settings is not None:
        try:
            ctx.world.apply_settings(ctx.original_settings)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"settings_restore:{type(exc).__name__}: {exc}")
    return not errors, "; ".join(errors) if errors else None


def _classify_blocker(summary: dict[str, Any], stages: dict[str, StageRecord]) -> tuple[str, str | None]:
    for stage in STAGE_NAMES:
        record = stages[stage]
        if record.started and not record.finished:
            mapping = {
                "stage_01_client_connect": "client_connect_failed",
                "stage_02_world_available": "client_connect_failed",
                "stage_03_town03_loaded_or_reused": "map_load_timeout",
                "stage_04_settings_applied": "setup_probe_unknown_blocker",
                "stage_05_spawn_points_loaded": "spawn_points_unavailable",
                "stage_06_ego_spawned": "ego_spawn_failed",
                "stage_07_rgb_sensor_attached": "rgb_sensor_attach_failed",
                "stage_08_first_rgb_frame_received": "first_rgb_frame_timeout",
                "stage_09_grp_route_generated": "grp_route_generation_failed",
                "stage_10_warmup_ticks_completed": "warmup_tick_stall",
                "stage_11_cleanup_completed": "cleanup_failed",
            }
            if stage == "stage_03_town03_loaded_or_reused" and not summary.get("town_ready"):
                return "map_not_town03", stage
            return mapping.get(stage, "setup_probe_unknown_blocker"), stage
    if summary.get("setup_probe_passed"):
        return "setup_probe_passed", None
    return "setup_probe_unknown_blocker", None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Child CARLA setup/spawn probe for Phase 12C-YOLOv9-R1-SETUP")
    parser.add_argument("--route-id", default="route_01", choices=["route_01"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=2000)
    parser.add_argument("--town", default="Town03")
    parser.add_argument("--start-spawn-index", type=int, default=3)
    parser.add_argument("--end-spawn-index", type=int, default=30)
    parser.add_argument("--map-load-mode", choices=["reuse_or_load", "force_load", "reuse_existing"], default="reuse_or_load")
    parser.add_argument("--cleanup-existing-actors", action="store_true")
    parser.add_argument("--cleanup-role-name", default="hero")
    parser.add_argument("--setup-timeout-sec", type=float, default=300.0)
    parser.add_argument("--map-load-timeout-sec", type=float, default=180.0)
    parser.add_argument("--spawn-timeout-sec", type=float, default=120.0)
    parser.add_argument("--sensor-timeout-sec", type=float, default=120.0)
    parser.add_argument("--warmup-ticks", type=int, default=20)
    parser.add_argument("--warmup-timeout-sec", type=float, default=120.0)
    parser.add_argument("--sync-mode", action="store_true")
    parser.add_argument("--fixed-delta-seconds", type=float, default=0.05)
    parser.add_argument("--camera-width", type=int, default=800)
    parser.add_argument("--camera-height", type=int, default=600)
    parser.add_argument("--route-sampling-resolution-m", type=float, default=2.0)
    parser.add_argument("--carla-root", type=Path, default=DEFAULT_CARLA_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--timestamp", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    output_dir = args.output_dir if args.output_dir.is_absolute() else REPO_ROOT / args.output_dir
    carla_root = args.carla_root if args.carla_root.is_absolute() else REPO_ROOT / args.carla_root
    run_dir = _next_run_dir(output_dir, args.timestamp)
    started_at = time.perf_counter()
    ctx = ProbeContext()

    summary: dict[str, Any] = {
        "phase": PHASE,
        "run_dir": str(run_dir),
        "route_id": args.route_id,
        "controller_mode": "grp_follower",
        "perception_backend": "yolov9",
        "target_town": args.town,
        "target_map_name": args.town,
        "start_spawn_index": args.start_spawn_index,
        "end_spawn_index": args.end_spawn_index,
        "map_load_mode": args.map_load_mode,
        "current_map_name": None,
        "carla_server_reachable": True,
        "client_connect_ok": False,
        "world_ready": False,
        "town_ready": False,
        "spawn_point_count": None,
        "start_spawn_available": False,
        "end_spawn_available": False,
        "ego_spawned": False,
        "ego_actor_id": None,
        "rgb_sensor_attached": False,
        "rgb_sensor_actor_id": None,
        "first_rgb_frame_received": False,
        "first_rgb_frame_width": None,
        "first_rgb_frame_height": None,
        "first_rgb_frame_latency_sec": None,
        "grp_route_generated": False,
        "grp_route_waypoint_count": None,
        "grp_route_distance_m": None,
        "warmup_ticks_requested": args.warmup_ticks,
        "warmup_ticks_completed": 0,
        "cleanup_completed": False,
        **BOUNDARY_FIELDS,
    }

    try:
        _append_carla_paths(carla_root)
        import carla  # type: ignore[import-not-found]

        def stage_01() -> None:
            ctx.client = carla.Client(args.host, args.port)
            ctx.client.set_timeout(float(args.setup_timeout_sec))
            summary["client_connect_ok"] = True

        def stage_02() -> None:
            assert ctx.client is not None
            ctx.world = ctx.client.get_world()
            summary["world_ready"] = ctx.world is not None
            summary["current_map_name"] = str(getattr(ctx.world.get_map(), "name", "") or "")

        def stage_03() -> None:
            assert ctx.client is not None
            assert ctx.world is not None
            current_name = str(getattr(ctx.world.get_map(), "name", "") or "")
            summary["current_map_name"] = current_name
            if args.map_load_mode == "reuse_existing":
                if not _map_matches_town(current_name, args.town):
                    raise RuntimeError(f"current map is not {args.town}: {current_name}")
            elif args.map_load_mode == "force_load":
                ctx.client.set_timeout(float(args.map_load_timeout_sec))
                ctx.world = ctx.client.load_world(args.town)
            elif not _map_matches_town(current_name, args.town):
                ctx.client.set_timeout(float(args.map_load_timeout_sec))
                ctx.world = ctx.client.load_world(args.town)
            ctx.client.set_timeout(float(args.setup_timeout_sec))
            summary["current_map_name"] = str(getattr(ctx.world.get_map(), "name", "") or "")
            summary["town_ready"] = _map_matches_town(summary["current_map_name"], args.town)
            if not summary["town_ready"]:
                raise RuntimeError(f"loaded map is not {args.town}: {summary['current_map_name']}")

        def stage_04() -> None:
            assert ctx.world is not None
            ctx.original_settings = ctx.world.get_settings()
            if args.sync_mode:
                settings = ctx.world.get_settings()
                settings.synchronous_mode = True
                settings.fixed_delta_seconds = float(args.fixed_delta_seconds)
                ctx.world.apply_settings(settings)

        def stage_05() -> None:
            assert ctx.world is not None
            spawn_points = list(ctx.world.get_map().get_spawn_points())
            summary["spawn_point_count"] = len(spawn_points)
            summary["start_spawn_available"] = 0 <= int(args.start_spawn_index) < len(spawn_points)
            summary["end_spawn_available"] = 0 <= int(args.end_spawn_index) < len(spawn_points)
            if not spawn_points:
                raise RuntimeError("no spawn points available")
            if not summary["start_spawn_available"]:
                raise IndexError(f"start_spawn_index invalid: {args.start_spawn_index}")
            if not summary["end_spawn_available"]:
                raise IndexError(f"end_spawn_index invalid: {args.end_spawn_index}")

        def stage_06() -> None:
            assert ctx.world is not None
            if args.cleanup_existing_actors:
                removed = _cleanup_matching_actors(ctx.world, args.cleanup_role_name)
                summary["cleanup_existing_actor_count"] = removed
            spawn_points = list(ctx.world.get_map().get_spawn_points())
            blueprint_library = ctx.world.get_blueprint_library()
            vehicle_bp = blueprint_library.filter("vehicle.tesla.model3")[0]
            if vehicle_bp.has_attribute("role_name"):
                vehicle_bp.set_attribute("role_name", args.cleanup_role_name)
            vehicle = ctx.world.try_spawn_actor(vehicle_bp, spawn_points[int(args.start_spawn_index)])
            if vehicle is None:
                raise RuntimeError(f"ego spawn failed at index {args.start_spawn_index}")
            ctx.ego_vehicle = vehicle
            ctx.actors_created.append(vehicle)
            summary["ego_spawned"] = True
            summary["ego_actor_id"] = int(vehicle.id)

        def stage_07() -> None:
            assert ctx.world is not None
            assert ctx.ego_vehicle is not None
            camera_bp = ctx.world.get_blueprint_library().find("sensor.camera.rgb")
            camera_bp.set_attribute("image_size_x", str(args.camera_width))
            camera_bp.set_attribute("image_size_y", str(args.camera_height))
            camera_bp.set_attribute("fov", "90")
            transform = carla.Transform(carla.Location(x=1.5, z=2.4))
            sensor = ctx.world.spawn_actor(camera_bp, transform, attach_to=ctx.ego_vehicle)
            sensor.listen(lambda image: ctx.frame_queue.put(image))
            ctx.rgb_sensor = sensor
            ctx.actors_created.append(sensor)
            summary["rgb_sensor_attached"] = True
            summary["rgb_sensor_actor_id"] = int(sensor.id)

        def stage_08() -> None:
            assert ctx.world is not None
            started = time.perf_counter()
            deadline = started + float(args.sensor_timeout_sec)
            while time.perf_counter() < deadline:
                if args.sync_mode:
                    ctx.world.tick()
                else:
                    ctx.world.wait_for_tick(max(1.0, float(args.fixed_delta_seconds)))
                try:
                    image = ctx.frame_queue.get(timeout=1.0)
                except queue.Empty:
                    continue
                ctx.first_frame = image
                summary["first_rgb_frame_received"] = True
                summary["first_rgb_frame_width"] = int(getattr(image, "width", 0))
                summary["first_rgb_frame_height"] = int(getattr(image, "height", 0))
                summary["first_rgb_frame_latency_sec"] = round(time.perf_counter() - started, 3)
                return
            raise TimeoutError("first RGB frame timed out")

        def stage_09() -> None:
            assert ctx.world is not None
            spawn_points = list(ctx.world.get_map().get_spawn_points())
            from agents.navigation.global_route_planner import GlobalRoutePlanner  # type: ignore[import-not-found]

            planner = GlobalRoutePlanner(ctx.world.get_map(), float(args.route_sampling_resolution_m))
            origin = spawn_points[int(args.start_spawn_index)].location
            destination = spawn_points[int(args.end_spawn_index)].location
            route = planner.trace_route(origin, destination)
            if len(route) < 2:
                raise RuntimeError("GlobalRoutePlanner returned fewer than two waypoints")
            summary["grp_route_generated"] = True
            summary["grp_route_waypoint_count"] = len(route)
            summary["grp_route_distance_m"] = round(_route_distance(route), 6)

        def stage_10() -> None:
            assert ctx.world is not None
            deadline = time.perf_counter() + float(args.warmup_timeout_sec)
            completed = 0
            for _ in range(max(0, int(args.warmup_ticks))):
                if time.perf_counter() > deadline:
                    raise TimeoutError("warmup tick timeout")
                if args.sync_mode:
                    ctx.world.tick()
                else:
                    ctx.world.wait_for_tick(max(1.0, float(args.fixed_delta_seconds)))
                completed += 1
                summary["warmup_ticks_completed"] = completed

        def stage_11() -> None:
            ok, error = _destroy_created_actors(ctx)
            summary["cleanup_completed"] = ok
            if not ok:
                raise RuntimeError(error or "cleanup failed")

        stage_funcs = {
            "stage_01_client_connect": stage_01,
            "stage_02_world_available": stage_02,
            "stage_03_town03_loaded_or_reused": stage_03,
            "stage_04_settings_applied": stage_04,
            "stage_05_spawn_points_loaded": stage_05,
            "stage_06_ego_spawned": stage_06,
            "stage_07_rgb_sensor_attached": stage_07,
            "stage_08_first_rgb_frame_received": stage_08,
            "stage_09_grp_route_generated": stage_09,
            "stage_10_warmup_ticks_completed": stage_10,
            "stage_11_cleanup_completed": stage_11,
        }
        for stage in STAGE_NAMES:
            if not _run_stage(ctx, args, stage, stage_funcs[stage]):
                if stage != "stage_11_cleanup_completed":
                    ok, error = _destroy_created_actors(ctx)
                    summary["cleanup_completed"] = ok
                    if not ok:
                        ctx.event("cleanup_after_failure_failed", error_message=error)
                break
    except Exception as exc:  # noqa: BLE001
        ctx.event("setup_probe_unhandled_exception", error_type=type(exc).__name__, error_message=str(exc))
        if not summary.get("cleanup_completed"):
            ok, error = _destroy_created_actors(ctx)
            summary["cleanup_completed"] = ok
            if not ok:
                ctx.event("cleanup_after_exception_failed", error_message=error)

    summary["setup_probe_passed"] = all(ctx.stages[name].finished for name in STAGE_NAMES)
    classification, failed_stage = _classify_blocker(summary, ctx.stages)
    summary["setup_blocker_classification"] = classification
    summary["setup_stage_failed"] = failed_stage
    summary["setup_probe_duration_sec"] = round(time.perf_counter() - started_at, 3)
    summary["status"] = (
        "Phase 12C-YOLOv9-R1-SETUP Probe Pass - selected route setup reached map ready, ego spawn, RGB sensor attach, first RGB frame, GRP route generation, and warm-up ticks."
        if summary["setup_probe_passed"]
        else "Phase 12C-YOLOv9-R1-SETUP Blocked - selected route setup still failed before closed-loop route ticks."
    )
    summary["stages"] = {name: ctx.stages[name].as_dict() for name in STAGE_NAMES}

    _write_json(run_dir / "summary.json", summary)
    _write_json(run_dir / "manifest.json", {"phase": PHASE, "status": summary["status"], "run_dir": str(run_dir)})
    _write_json(run_dir / "environment.json", {"python": sys.version, "python_executable": sys.executable, "carla_root": str(carla_root), "timestamp_utc": _utc_now()})
    _write_jsonl(run_dir / "events.jsonl", ctx.events)
    (run_dir / "commands.txt").write_text(" ".join([sys.executable, *sys.argv]) + "\n", encoding="utf-8")
    (run_dir / "README.md").write_text(
        f"# Phase 12C-YOLOv9-R1-SETUP Child Probe\n\n{summary['status']}\n\nsetup_blocker_classification={classification}\n",
        encoding="utf-8",
    )
    print(f"experiment_dir={run_dir}")
    print(summary["status"])
    print(f"setup_blocker_classification={classification}")
    return 0 if summary["setup_probe_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
