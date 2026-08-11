"""Phase 13B Gate C — CARLA closed loop with a real Jetson in the loop.

    CARLA RGB camera -> bounded FramePublisher -> TCP -> real Jetson
      -> unchanged Phase 13A 64-byte UDP command -> C Virtual Safety MCU
      -> JILA ACK -> VirtualActuatorBridge -> carla.VehicleControl -> next tick

Only the Jetson compute node is physical. The camera, environment, vehicle,
Safety MCU, actuator and vehicle physics are all simulated. Perception is the
DummyPerceptionBackend; TensorRT deployment belongs to Phase 13C.
"""

from __future__ import annotations

import argparse
import queue
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import numpy as np

from run_phase13b_jil_checks import (  # noqa: E402  (path bootstrap above)
    BOUNDARY_FIELDS,
    PHASE,
    STATUS_BLOCKED,
    STATUS_PASS,
    STATUS_TRANSPORT_PASS,
    EvidenceWriter,
    JilSessionDriver,
    build_arg_parser,
    firewall_guidance,
    new_run_id,
    pc_environment,
    utc_now_iso,
)
from workers.core.carla_adapter import CarlaClientAdapter, CarlaControlCommand
from workers.core.clock_sync import monotonic_us

try:  # CARLA stays an optional runtime dependency for the rest of the repo.
    import carla  # type: ignore[import-not-found]

    HAS_CARLA = True
except ImportError:  # pragma: no cover - depends on the runtime environment
    carla = None  # type: ignore[assignment]
    HAS_CARLA = False


class CarlaSessionError(RuntimeError):
    """CARLA setup or runtime failure with a Phase 13B blocker classification."""

    def __init__(self, classification: str, message: str) -> None:
        super().__init__("%s: %s" % (classification, message))
        self.classification = classification


class CarlaLockstepSession:
    """Minimal Phase 13B CARLA session: reuse-or-load, spawn, camera, tick."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.client = None  # type: Any
        self.world = None  # type: Any
        self.original_settings = None  # type: Any
        self.vehicle = None  # type: Any
        self.camera = None  # type: Any
        self.actors = []  # type: List[Any]
        self.image_queue = queue.Queue(maxsize=4)  # type: queue.Queue
        self.map_name = ""
        self.map_reused = False
        self.camera_sensor_tick = 1.0 / max(1e-6, float(args.camera_fps))
        self.dropped_images = 0

    def setup(self) -> Dict[str, Any]:
        if not HAS_CARLA:
            raise CarlaSessionError("carla_setup_failed", "carla Python package unavailable")
        started = time.time()
        self.client = carla.Client(self.args.carla_host, int(self.args.carla_port))
        self.client.set_timeout(float(self.args.setup_timeout_sec))
        try:
            current = self.client.get_world()
        except Exception as exc:
            raise CarlaSessionError("carla_server_unreachable", repr(exc))

        current_name = str(getattr(current.get_map(), "name", "") or "")
        if self.args.map_load_mode == "reuse_or_load" and CarlaClientAdapter._map_matches_town(
            current_name, self.args.town
        ):
            self.world = current
            self.map_reused = True
        elif self.args.map_load_mode == "reuse_only":
            self.world = current
            self.map_reused = True
        else:
            self.world = self.client.load_world(self.args.town)
            self.map_reused = False
        self.map_name = str(getattr(self.world.get_map(), "name", "") or "")

        self.original_settings = self.world.get_settings()
        settings = self.world.get_settings()
        settings.synchronous_mode = True
        settings.fixed_delta_seconds = float(self.args.fixed_delta_seconds)
        self.world.apply_settings(settings)

        blueprints = self.world.get_blueprint_library()
        try:
            vehicle_bp = blueprints.find(self.args.ego_blueprint)
        except Exception:
            candidates = blueprints.filter("vehicle.*")
            if not candidates:
                raise CarlaSessionError("carla_setup_failed", "no vehicle blueprint available")
            vehicle_bp = candidates[0]

        spawn_points = self.world.get_map().get_spawn_points()
        if not spawn_points:
            raise CarlaSessionError("carla_setup_failed", "map has no spawn points")
        spawn = spawn_points[int(self.args.spawn_point_index) % len(spawn_points)]
        self.vehicle = self.world.try_spawn_actor(vehicle_bp, spawn)
        if self.vehicle is None:
            raise CarlaSessionError("carla_setup_failed", "ego vehicle spawn failed")
        self.vehicle.set_autopilot(False)
        self.actors.append(self.vehicle)

        camera_bp = blueprints.find("sensor.camera.rgb")
        camera_bp.set_attribute("image_size_x", str(int(self.args.camera_width)))
        camera_bp.set_attribute("image_size_y", str(int(self.args.camera_height)))
        camera_bp.set_attribute("fov", str(float(self.args.camera_fov)))
        # sensor_tick pins the camera to camera_fps; at fixed_delta 0.05 s
        # (20 Hz) and 10 FPS the sensor emits one frame every two ticks.
        camera_bp.set_attribute("sensor_tick", str(self.camera_sensor_tick))
        transform = carla.Transform(carla.Location(x=1.6, y=0.0, z=1.7), carla.Rotation(pitch=0.0))
        self.camera = self.world.spawn_actor(camera_bp, transform, attach_to=self.vehicle)
        self.camera.listen(self._on_image)
        self.actors.append(self.camera)

        return {
            "carla_map": self.map_name,
            "carla_map_reused": self.map_reused,
            "carla_fixed_delta_seconds": float(self.args.fixed_delta_seconds),
            "carla_simulator_frequency_hz": round(1.0 / float(self.args.fixed_delta_seconds), 3),
            "carla_camera_fps": float(self.args.camera_fps),
            "carla_camera_sensor_tick_sec": round(self.camera_sensor_tick, 6),
            "carla_ticks_per_camera_frame": round(
                self.camera_sensor_tick / float(self.args.fixed_delta_seconds), 3
            ),
            "carla_setup_duration_sec": round(time.time() - started, 3),
            "carla_spawn_point_index": int(self.args.spawn_point_index),
            "carla_ego_blueprint": str(self.vehicle.type_id),
        }

    def _on_image(self, image: Any) -> None:
        try:
            self.image_queue.put_nowait(image)
        except queue.Full:
            self.dropped_images += 1

    def tick(self) -> int:
        return int(self.world.tick())

    def latest_image(self) -> Optional[Any]:
        """Return the newest queued camera image, discarding older ones."""

        image = None
        while True:
            try:
                image = self.image_queue.get_nowait()
            except queue.Empty:
                break
        return image

    def apply(self, command: CarlaControlCommand) -> None:
        self.vehicle.apply_control(CarlaClientAdapter._to_vehicle_control(command))

    def ego_state(self) -> Dict[str, Any]:
        transform = self.vehicle.get_transform()
        velocity = self.vehicle.get_velocity()
        speed = (velocity.x ** 2 + velocity.y ** 2 + velocity.z ** 2) ** 0.5
        return {
            "x": round(float(transform.location.x), 4),
            "y": round(float(transform.location.y), 4),
            "speed_mps": round(float(speed), 4),
        }

    def set_synchronous(self, synchronous: bool) -> None:
        settings = self.world.get_settings()
        settings.synchronous_mode = bool(synchronous)
        if not synchronous:
            settings.fixed_delta_seconds = None
        else:
            settings.fixed_delta_seconds = float(self.args.fixed_delta_seconds)
        self.world.apply_settings(settings)

    def close(self) -> None:
        for actor in reversed(self.actors):
            try:
                if actor is not None and hasattr(actor, "stop"):
                    actor.stop()
                if actor is not None and actor.is_alive:
                    actor.destroy()
            except Exception:
                pass
        self.actors = []
        if self.world is not None and self.original_settings is not None:
            try:
                self.world.apply_settings(self.original_settings)
            except Exception:
                pass


def run_lockstep(
    session: CarlaLockstepSession,
    driver: JilSessionDriver,
    args: argparse.Namespace,
) -> Dict[str, Any]:
    """Bounded lockstep loop: tick, publish new frames, actuate C-accepted control."""

    frames_sent = 0
    frames_with_command = 0
    command_timeouts = 0
    ticks = 0
    ego_samples = []  # type: List[Dict[str, Any]]
    started = monotonic_us()

    for _ in range(int(args.warmup_ticks)):
        session.tick()
        session.latest_image()
        session.apply(driver.actuator.force_safe_stop("warmup"))

    driver.actuator.control_applied_count = 0
    driver.actuator.active_control_applied_count = 0
    driver.actuator.safe_stop_applied_count = 0
    driver.actuator.hold_applied_count = 0
    driver.actuator.records = []

    deadline = time.time() + float(args.run_timeout_sec)
    while frames_sent < int(args.frames) and time.time() < deadline:
        snapshot_frame = session.tick()
        ticks += 1
        image = session.latest_image()
        if image is None:
            # Intermediate tick with no new camera frame: hold the last
            # C-accepted control only while its validity window is open.
            session.apply(driver.actuator.decide(None, reason="no_new_camera_frame"))
            continue

        bgra = driver.publisher.carla_image_to_bgra(image)
        baseline = driver.server.processed_count()
        result = driver.publisher.publish_bgra(
            bgra,
            simulation_timestamp_us=int(float(getattr(image, "timestamp", 0.0)) * 1_000_000),
        )
        if not result.published:
            session.apply(driver.actuator.force_safe_stop("frame_publish_failed"))
            continue
        frames_sent += 1

        mcu_result = driver.server.wait_for_next_result(
            baseline, timeout_sec=float(args.command_timeout_ms) / 1000.0
        )
        if mcu_result is None:
            command_timeouts += 1
            session.apply(driver.actuator.force_safe_stop("command_timeout"))
        else:
            frames_with_command += 1
            session.apply(driver.actuator.decide(mcu_result))
        if frames_sent % 25 == 0:
            ego_samples.append(dict(session.ego_state(), frame=frames_sent, carla_frame=snapshot_frame))

    driver.frames_sent += frames_sent
    payload = {
        "gate_c_carla_frames_sent": frames_sent,
        "gate_c_carla_ticks": ticks,
        "gate_c_frames_with_matched_command": frames_with_command,
        "gate_c_command_timeouts": command_timeouts,
        "gate_c_lockstep_duration_ms": round((monotonic_us() - started) / 1000.0, 3),
        "gate_c_camera_images_dropped_by_queue": session.dropped_images,
        "gate_c_ego_samples": ego_samples,
    }
    driver.emit("gate_c_lockstep_completed", **{k: v for k, v in payload.items() if k != "gate_c_ego_samples"})
    return payload


def run_realtime_stale_gate(
    session: CarlaLockstepSession,
    driver: JilSessionDriver,
    args: argparse.Namespace,
) -> Dict[str, Any]:
    """Short realtime subtest: an expired command must never be actuated."""

    safe_stop_before = driver.actuator.safe_stop_applied_count
    active_before = driver.actuator.active_control_applied_count
    session.set_synchronous(False)
    time.sleep(0.2)

    # Stop publishing frames. Once the configured command validity window has
    # elapsed, the bridge must fall back to SAFE_STOP instead of replaying the
    # last accepted control.
    hold_deadline = time.time() + (float(args.command_validity_ms) / 1000.0) + 0.5
    applied_stale = False
    while time.time() < hold_deadline:
        command = driver.actuator.decide(None, reason="realtime_no_frame")
        session.apply(command)
        if command.brake >= 1.0 and command.throttle == 0.0:
            applied_stale = True
        time.sleep(0.1)

    session.set_synchronous(True)
    payload = {
        "gate_c_realtime_stale_gate_passed": applied_stale
        and driver.actuator.safe_stop_applied_count > safe_stop_before,
        "gate_c_realtime_safe_stop_delta": driver.actuator.safe_stop_applied_count - safe_stop_before,
        "gate_c_realtime_active_delta": driver.actuator.active_control_applied_count - active_before,
    }
    driver.emit("gate_c_realtime_stale_gate", **payload)
    return payload


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = build_arg_parser("Phase 13B Gate C CARLA closed loop")
    parser.add_argument("--carla-host", dest="carla_host", default="127.0.0.1")
    parser.add_argument("--carla-port", dest="carla_port", type=int, default=2000)
    parser.add_argument("--host", dest="carla_host")
    parser.add_argument("--port", dest="carla_port", type=int)
    parser.add_argument("--town", default="Town03")
    parser.add_argument(
        "--map-load-mode", choices=("reuse_or_load", "load", "reuse_only"), default="reuse_or_load"
    )
    parser.add_argument("--mode", choices=("lockstep", "realtime"), default="lockstep")
    parser.add_argument("--frames", type=int, default=300)
    parser.add_argument("--fixed-delta-seconds", type=float, default=0.05)
    parser.add_argument("--camera-fps", type=float, default=10.0)
    parser.add_argument("--camera-fov", type=float, default=90.0)
    parser.add_argument("--ego-blueprint", default="vehicle.tesla.model3")
    parser.add_argument("--spawn-point-index", type=int, default=0)
    parser.add_argument("--setup-timeout-sec", type=float, default=180.0)
    parser.add_argument("--warmup-ticks", type=int, default=20)
    parser.add_argument("--command-timeout-ms", type=int, default=400)
    parser.add_argument("--run-timeout-sec", type=float, default=900.0)
    parser.add_argument("--require-server", action="store_true")
    parser.add_argument("--require-jetson", action="store_true")
    parser.add_argument("--skip-fault-matrix", action="store_true")
    parser.add_argument("--skip-realtime-gate", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    run_id = args.run_id or new_run_id()
    evidence = EvidenceWriter(Path(args.output_dir), run_id)
    environment = pc_environment(args)

    driver = JilSessionDriver(
        run_id=run_id,
        jetson_host=args.jetson_host,
        frame_port=args.frame_port,
        control_port=args.control_port,
        command_port=args.command_port,
        ack_port=args.ack_port,
        pc_bind_host=args.pc_bind_host,
        mcu_library_path=args.mcu_library or None,
        heartbeat_timeout_ms=args.heartbeat_timeout_ms,
        command_validity_ms=args.command_validity_ms,
        max_clock_uncertainty_us=args.max_clock_uncertainty_us,
        clock_samples=args.clock_samples,
        clock_warmup_probes=args.clock_warmup_probes,
        camera_width=args.camera_width,
        camera_height=args.camera_height,
        jpeg_quality=args.jpeg_quality,
        pin_source_host=not args.no_pin_source_host,
    )

    summary = {
        "phase": PHASE,
        "gate": "C",
        "run_id": run_id,
        "created_at_utc": utc_now_iso(),
        "transport_medium": args.transport_medium,
        "mode": args.mode,
    }  # type: Dict[str, Any]
    session = CarlaLockstepSession(args)
    jetson_evidence = {"metrics": {}, "events": []}  # type: Dict[str, Any]
    status = STATUS_BLOCKED
    exit_code = 1

    try:
        if args.require_server and not HAS_CARLA:
            driver.blockers.append("carla_setup_failed")
            raise RuntimeError("carla Python package is unavailable")

        mcu = driver.start_virtual_mcu()
        summary["virtual_mcu"] = mcu
        if not mcu.get("ok"):
            raise RuntimeError("virtual safety MCU could not start")

        hello = driver.connect_control()
        jetson_env = dict(hello.get("environment", {}))
        summary["jetson_environment"] = jetson_env
        if args.require_jetson and not jetson_env.get("real_jetson_detected", False):
            driver.blockers.append("jetson_environment_mismatch")
            raise RuntimeError("real Jetson required but not detected")

        runtime_pc_sha = environment.get("runtime_pc_git_sha", "")
        runtime_jetson_sha = jetson_env.get("runtime_jetson_git_sha", "")
        sha_match = bool(runtime_pc_sha) and runtime_pc_sha == runtime_jetson_sha
        summary["runtime_pc_git_sha"] = runtime_pc_sha
        summary["runtime_jetson_git_sha"] = runtime_jetson_sha
        summary["runtime_git_sha_match"] = sha_match
        if args.require_jetson and not sha_match:
            driver.blockers.append("git_sha_mismatch")
            raise RuntimeError("runtime git SHA mismatch between PC and Jetson")

        summary["clock"] = driver.synchronise_clocks()
        driver.start_session(start_frame_server=True)
        if not driver.connect_frames():
            raise RuntimeError("frame transport could not be established")

        try:
            summary["carla"] = session.setup()
        except CarlaSessionError as exc:
            driver.blockers.append(exc.classification)
            raise

        lockstep = run_lockstep(session, driver, args)
        summary["lockstep"] = lockstep
        summary["gate_c_lockstep_passed"] = (
            lockstep["gate_c_carla_frames_sent"] >= int(args.frames)
            and driver.actuator.active_control_applied_count > 0
        )

        if not args.skip_realtime_gate:
            summary["realtime"] = run_realtime_stale_gate(session, driver, args)
        else:
            summary["realtime"] = {"gate_c_realtime_stale_gate_passed": False, "skipped": True}

        if not args.skip_fault_matrix:
            summary["fault_matrix"] = driver.run_fault_matrix("C")
        else:
            summary["fault_matrix"] = {"fault_matrix_passed": False, "skipped": True}

        jetson_evidence = driver.collect_jetson_evidence()
        jetson_metrics = jetson_evidence["metrics"]
        actuator = driver.actuator.metrics()

        gate_c = {
            "gate_c_carla_frames_sent": lockstep["gate_c_carla_frames_sent"],
            "gate_c_carla_frames_processed": int(jetson_metrics.get("frames_processed", 0)),
            "gate_c_command_accept_count": int(driver.server.command_accept_count),
            "gate_c_command_reject_count": int(driver.server.command_reject_count),
            "gate_c_virtual_actuator_control_applied_count": actuator[
                "virtual_actuator_control_applied_count"
            ],
            "gate_c_virtual_actuator_active_control_applied_count": actuator[
                "virtual_actuator_active_control_applied_count"
            ],
            "gate_c_virtual_actuator_safe_stop_applied_count": actuator[
                "virtual_actuator_safe_stop_applied_count"
            ],
            "gate_c_lockstep_passed": bool(summary["gate_c_lockstep_passed"]),
            "gate_c_realtime_stale_gate_passed": bool(
                summary["realtime"].get("gate_c_realtime_stale_gate_passed")
            ),
            "gate_c_fault_matrix_passed": bool(summary["fault_matrix"].get("fault_matrix_passed")),
            "gate_c_false_accept_count": int(summary["fault_matrix"].get("false_accept_count", 0)),
            "gate_c_false_reject_count": int(summary["fault_matrix"].get("false_reject_count", 0)),
        }
        summary["gate_c"] = gate_c

        gate_c_pass = (
            gate_c["gate_c_carla_frames_sent"] >= 300
            and gate_c["gate_c_carla_frames_processed"] >= 300
            and gate_c["gate_c_command_accept_count"] > 0
            and gate_c["gate_c_virtual_actuator_control_applied_count"] > 0
            and gate_c["gate_c_virtual_actuator_active_control_applied_count"] > 0
            and gate_c["gate_c_virtual_actuator_safe_stop_applied_count"] > 0
            and gate_c["gate_c_lockstep_passed"]
            and gate_c["gate_c_realtime_stale_gate_passed"]
            and gate_c["gate_c_fault_matrix_passed"]
            and gate_c["gate_c_false_accept_count"] == 0
            and gate_c["gate_c_false_reject_count"] == 0
            and not driver.blockers
        )
        summary["gate_c_pass"] = gate_c_pass
        status = STATUS_PASS if gate_c_pass else STATUS_BLOCKED
        exit_code = 0 if gate_c_pass else 1
    except Exception as exc:
        summary["error"] = repr(exc)
        driver.emit("gate_c_error", error=repr(exc))
    finally:
        pc_metrics = driver.pc_metrics()
        try:
            session.close()
        except Exception:
            pass
        summary["status"] = status
        summary["blockers"] = list(driver.blockers)
        summary["pc_environment"] = environment
        summary.update(BOUNDARY_FIELDS)
        evidence.write_json("summary.json", summary)
        evidence.write_json("pc_metrics.json", pc_metrics)
        evidence.write_json("jetson_metrics.json", jetson_evidence.get("metrics", {}))
        evidence.write_json("environment.json", environment)
        evidence.write_fault_matrix(driver.fault_rows)
        evidence.write_events(driver.events + list(jetson_evidence.get("events", [])))
        evidence.write_json(
            "network_metrics.json",
            {
                "transport_medium": args.transport_medium,
                "jetson_host": args.jetson_host,
                "frame_port": args.frame_port,
                "control_port": args.control_port,
                "command_port": args.command_port,
                "ack_port": args.ack_port,
                "pc_source_address": driver.pc_address,
                "clock": driver.clock_result.to_dict() if driver.clock_result else None,
            },
        )
        evidence.write_json(
            "raw_outputs/virtual_actuator_records.json", driver.actuator.records_as_dicts()
        )
        evidence.write_json(
            "manifest.json",
            {
                "phase": PHASE,
                "gate": "C",
                "run_id": run_id,
                "status": status,
                "created_at_utc": utc_now_iso(),
                "evidence_dir": str(evidence.run_dir),
                "generated_evidence_git_policy": "ignored_local_only",
                **BOUNDARY_FIELDS,
            },
        )
        evidence.write_text(
            "commands.txt",
            "# Phase 13B Gate C\n%s %s\n\n%s\n"
            % (sys.executable, " ".join(sys.argv), "\n".join(firewall_guidance(args))),
        )
        evidence.write_text(
            "README.md",
            "# Phase 13B Gate C evidence\n\nRun id: `%s`\n\nStatus: `%s`\n\n"
            "Jetson-in-the-loop (processor-in-the-loop) closed loop. Physical: the Jetson "
            "Orin NX compute node and the USB-gadget Ethernet link. Simulated: CARLA camera, "
            "environment, vehicle, Safety MCU, actuator and vehicle physics. No full HIL, no "
            "real MCU, no physical camera or actuator, no TensorRT inference, no perception "
            "accuracy, no navigation quality, no route or infraction benchmark.\n"
            % (run_id, status),
        )
        driver.shutdown()

    print(status)
    print("run_id=%s" % run_id)
    print("evidence_dir=%s" % evidence.run_dir)
    for key, value in sorted(summary.get("gate_c", {}).items()):
        print("%s=%s" % (key, value))
    if summary.get("error"):
        print("error=%s" % summary["error"], file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
