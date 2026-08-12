"""Phase 13D Gate B — controlled CARLA Town03 calibration corpus.

Two modes, because capturing and judging are different jobs:

* ``--mode capture``  drives CARLA Town03 across N routes and M weather
  profiles and writes BGR PNG frames to an **external** directory. Nothing it
  writes ever enters this repository.
* ``--mode evaluate`` indexes that directory, builds the per-frame manifest
  (route, weather, frame id, SHA-256, image statistics), assigns the
  deterministic calibration/holdout split, proves duplicate-SHA and split
  overlap are zero, derives the calibration envelopes, measures the holdout
  false-reject rate, and validates the offline activation proxy.

The corpus is controlled simulation data. Every artefact says so, and nothing
in this phase describes it as real-world representative.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from run_phase13d_checks import (  # noqa: E402
    BOUNDARY_FIELDS,
    PHASE,
    STATUS_BLOCKED,
    STATUS_DATASET_PASS,
    Phase13DEvidence,
    new_run_id,
    pc_environment,
    utc_now_iso,
)
from workers.core.int8_activation_proxy import evaluate_proxy_report  # noqa: E402
from workers.core.int8_calibration_dataset import (  # noqa: E402
    DEFAULT_ENVELOPE_MARGIN_RATIO,
    MAX_HOLDOUT_FALSE_REJECT_RATE,
    MIN_CALIBRATION_FRAMES,
    MIN_HOLDOUT_FRAMES,
    MIN_ROUTES,
    MIN_WEATHER_PROFILES,
    DatasetError,
    DatasetManifest,
    assign_splits,
    build_envelopes,
    build_manifest,
    describe_frame,
    evaluate_coverage,
    evaluate_disjointness,
    evaluate_holdout,
    image_statistics,
    range_profile,
    verify_frame_files,
)

DEFAULT_WEATHERS = "ClearNoon,WetCloudyNoon,HardRainNoon,ClearSunset"
CAPTURE_INDEX_NAME = "capture_index.json"
DATASET_MANIFEST_NAME = "dataset_manifest.json"
ENVELOPE_NAME = "calibration_envelope.json"


# ── Capture ─────────────────────────────────────────────────────────────────


def _spawn_indices(count: int, routes: int, explicit: str) -> List[int]:
    if explicit.strip():
        return [int(value.strip()) % max(1, count) for value in explicit.split(",") if value.strip()]
    if count <= 0:
        raise DatasetError("carla_setup_failed", "map exposes no spawn points")
    stride = count / float(max(1, routes))
    return [int(round(index * stride)) % count for index in range(routes)]


def capture(args: argparse.Namespace) -> Dict[str, Any]:
    """Drive CARLA and write one PNG per captured camera frame."""

    import numpy as np

    try:
        import carla  # type: ignore[import-not-found]
    except Exception as exc:
        raise DatasetError("carla_unavailable", repr(exc)[:200])
    try:
        import cv2  # type: ignore[import-not-found]
    except Exception as exc:
        raise DatasetError("dataset_encoder_unavailable", repr(exc)[:200])

    weathers = [name.strip() for name in str(args.weathers).split(",") if name.strip()]
    if len(weathers) < MIN_WEATHER_PROFILES:
        raise DatasetError(
            "dataset_weather_coverage_insufficient",
            "%d weather profiles requested, %d required" % (len(weathers), MIN_WEATHER_PROFILES),
        )
    for name in weathers:
        if not hasattr(carla.WeatherParameters, name):
            raise DatasetError("dataset_weather_unknown", "unknown CARLA weather preset %r" % name)

    root = Path(args.output_root)
    root.mkdir(parents=True, exist_ok=True)

    client = carla.Client(args.carla_host, int(args.carla_port))
    client.set_timeout(float(args.setup_timeout_sec))
    world = client.get_world()
    current_map = str(getattr(world.get_map(), "name", "") or "")
    map_reused = args.town.lower() in current_map.lower()
    if not map_reused:
        world = client.load_world(args.town)
        current_map = str(getattr(world.get_map(), "name", "") or "")

    original_settings = world.get_settings()
    settings = world.get_settings()
    settings.synchronous_mode = True
    settings.fixed_delta_seconds = float(args.fixed_delta_seconds)
    world.apply_settings(settings)

    traffic_manager = None
    autopilot_available = False
    try:
        traffic_manager = client.get_trafficmanager(int(args.traffic_manager_port))
        traffic_manager.set_synchronous_mode(True)
        autopilot_available = True
    except Exception:
        traffic_manager = None
        autopilot_available = False

    blueprints = world.get_blueprint_library()
    vehicle_bp = blueprints.find(args.ego_blueprint)
    spawn_points = world.get_map().get_spawn_points()
    indices = _spawn_indices(len(spawn_points), int(args.routes), str(args.route_spawn_points))

    records = []  # type: List[Dict[str, Any]]
    ticks = 0
    dropped = 0
    started = time.time()
    deadline = started + float(args.run_timeout_sec)
    frames_per_cell = int(args.frames_per_cell)

    for route_position, spawn_index in enumerate(indices):
        route_name = "route_%02d" % route_position
        vehicle = None
        camera = None
        # A plain list is not safe here: the sensor callback runs on a CARLA
        # thread, and a list mutated from two threads is what makes the client
        # fault during teardown. Phase 13B already proved a bounded Queue.
        images = queue.Queue(maxsize=4)  # type: Any
        dropped_here = [0]

        def _on_image(image, sink=images, counter=dropped_here):
            try:
                sink.put_nowait(image)
            except queue.Full:
                counter[0] += 1

        def _latest(sink=images):
            newest = None
            while True:
                try:
                    newest = sink.get_nowait()
                except queue.Empty:
                    return newest

        try:
            vehicle = world.try_spawn_actor(vehicle_bp, spawn_points[spawn_index])
            if vehicle is None:
                raise DatasetError("carla_setup_failed", "ego spawn failed at index %d" % spawn_index)
            if autopilot_available:
                vehicle.set_autopilot(True, int(args.traffic_manager_port))
            else:
                vehicle.set_autopilot(False)

            camera_bp = blueprints.find("sensor.camera.rgb")
            camera_bp.set_attribute("image_size_x", str(int(args.camera_width)))
            camera_bp.set_attribute("image_size_y", str(int(args.camera_height)))
            camera_bp.set_attribute("fov", str(float(args.camera_fov)))
            camera_bp.set_attribute("sensor_tick", str(1.0 / max(1e-6, float(args.camera_fps))))
            transform = carla.Transform(
                carla.Location(x=1.6, y=0.0, z=1.7), carla.Rotation(pitch=0.0)
            )
            camera = world.spawn_actor(camera_bp, transform, attach_to=vehicle)
            camera.listen(_on_image)

            for weather_name in weathers:
                world.set_weather(getattr(carla.WeatherParameters, weather_name))
                cell_dir = root / route_name / weather_name
                cell_dir.mkdir(parents=True, exist_ok=True)

                for _ in range(int(args.warmup_ticks)):
                    world.tick()
                    ticks += 1
                    _latest()

                captured = 0
                while captured < frames_per_cell and time.time() < deadline:
                    world.tick()
                    ticks += 1
                    if not autopilot_available:
                        vehicle.apply_control(
                            carla.VehicleControl(throttle=float(args.manual_throttle), steer=0.0)
                        )
                    image = _latest()
                    if image is None:
                        continue

                    raw = np.frombuffer(image.raw_data, dtype=np.uint8)
                    bgra = raw.reshape((int(image.height), int(image.width), 4))
                    bgr = np.ascontiguousarray(bgra[:, :, :3])
                    frame_id = "%s_%s_%05d" % (route_name, weather_name, captured)
                    target = cell_dir / ("%s.png" % frame_id)
                    if not cv2.imwrite(str(target), bgr):
                        raise DatasetError("dataset_frame_write_failed", "cv2 could not write %s" % target)
                    records.append(
                        {
                            "frame_id": frame_id,
                            "route": route_name,
                            "weather": weather_name,
                            "path": str(target),
                            "carla_frame": int(getattr(image, "frame", 0)),
                            "simulation_timestamp_us": int(
                                float(getattr(image, "timestamp", 0.0)) * 1_000_000
                            ),
                            "captured_at_utc": utc_now_iso(),
                            "spawn_point_index": int(spawn_index),
                        }
                    )
                    captured += 1
                if captured < frames_per_cell:
                    raise DatasetError(
                        "dataset_capture_timeout",
                        "%s/%s captured %d of %d frames" % (route_name, weather_name, captured, frames_per_cell),
                    )
        finally:
            # Stop the sensor first, tick once so any in-flight callback has
            # already been delivered, and only then destroy. Destroying a
            # listening sensor mid-callback is what crashes the client.
            try:
                if camera is not None:
                    camera.stop()
                    world.tick()
                    ticks += 1
                    _latest()
            except Exception:
                pass
            try:
                if vehicle is not None and autopilot_available:
                    vehicle.set_autopilot(False, int(args.traffic_manager_port))
            except Exception:
                pass
            for actor in (camera, vehicle):
                try:
                    if actor is not None and actor.is_alive:
                        actor.destroy()
                except Exception:
                    pass
            try:
                world.tick()
                ticks += 1
            except Exception:
                pass
            dropped += int(dropped_here[0])

    try:
        if traffic_manager is not None:
            traffic_manager.set_synchronous_mode(False)
    except Exception:
        pass
    try:
        world.apply_settings(original_settings)
    except Exception:
        pass

    payload = {
        "capture_profile": {
            "town": str(args.town),
            "carla_map": current_map,
            "carla_map_reused": bool(map_reused),
            "routes": int(args.routes),
            "route_spawn_point_indices": [int(value) for value in indices],
            "weather_profiles": weathers,
            "frames_per_cell": frames_per_cell,
            "fixed_delta_seconds": float(args.fixed_delta_seconds),
            "simulator_frequency_hz": round(1.0 / float(args.fixed_delta_seconds), 3),
            "camera_fps": float(args.camera_fps),
            "camera_width": int(args.camera_width),
            "camera_height": int(args.camera_height),
            "camera_fov": float(args.camera_fov),
            "ego_blueprint": str(args.ego_blueprint),
            "ego_control": "traffic_manager_autopilot" if autopilot_available else "constant_throttle",
            "pixel_format": "BGR8",
            "container": "png",
            "data_source": "controlled_carla_simulation",
            "real_world_representative": False,
        },
        "frames": records,
        "frame_count": len(records),
        "carla_ticks": ticks,
        "camera_frames_dropped": dropped,
        "capture_duration_sec": round(time.time() - started, 3),
        "dataset_root": str(root),
        "created_at_utc": utc_now_iso(),
    }
    (root / CAPTURE_INDEX_NAME).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


# ── Evaluate ────────────────────────────────────────────────────────────────


def index_records(capture_payload: Dict[str, Any], dataset_root: Path) -> List[Any]:
    """Hash and measure every captured frame; an unreadable frame is fatal."""

    import cv2  # type: ignore[import-not-found]

    records = []
    for entry in capture_payload.get("frames", []):
        path = Path(entry["path"])
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            raise DatasetError("dataset_frame_unreadable", "cv2 could not decode %s" % path)
        statistics = image_statistics(image)
        records.append(
            describe_frame(
                path,
                frame_id=str(entry["frame_id"]),
                route=str(entry["route"]),
                weather=str(entry["weather"]),
                statistics=statistics,
                dataset_root=dataset_root,
                captured_at_utc=str(entry.get("captured_at_utc", "")),
                carla_frame=int(entry.get("carla_frame", 0)),
                simulation_timestamp_us=int(entry.get("simulation_timestamp_us", 0)),
            )
        )
    return records


def evaluate(args: argparse.Namespace) -> Dict[str, Any]:
    root = Path(args.output_root)
    index_path = root / CAPTURE_INDEX_NAME
    if not index_path.is_file():
        raise DatasetError("dataset_capture_index_missing", "no %s under %s" % (CAPTURE_INDEX_NAME, root))
    capture_payload = json.loads(index_path.read_text(encoding="utf-8"))

    records = index_records(capture_payload, root)
    if not records:
        raise DatasetError("dataset_frames_missing", "capture index lists no frames")
    assigned = assign_splits(records, holdout_stride=int(args.holdout_stride))
    manifest = build_manifest(
        assigned,
        dataset_name=str(args.dataset_name),
        town=str(capture_payload.get("capture_profile", {}).get("town", "Town03")),
        capture_profile=capture_payload.get("capture_profile", {}),
        dataset_root=str(root),
        holdout_stride=int(args.holdout_stride),
        created_at_utc=utc_now_iso(),
    )

    coverage = evaluate_coverage(
        manifest,
        min_routes=int(args.min_routes),
        min_weather_profiles=int(args.min_weather_profiles),
        min_calibration=int(args.min_calibration),
        min_holdout=int(args.min_holdout),
    )
    disjointness = evaluate_disjointness(manifest)
    files = verify_frame_files(manifest.records(), verify_hash=not args.skip_hash_verification)
    envelopes = build_envelopes(
        manifest.records(),
        margin_ratio=float(args.envelope_margin_ratio),
        dataset_sha256_value=manifest.dataset_sha256,
    )
    holdout = evaluate_holdout(
        envelopes,
        manifest.split("holdout"),
        max_false_reject_rate=float(args.max_false_reject_rate),
    )
    profile = range_profile(manifest.records())

    manifest.write(root / DATASET_MANIFEST_NAME)
    (root / ENVELOPE_NAME).write_text(
        json.dumps(envelopes.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    proxy_report = {}  # type: Dict[str, Any]
    proxy_verdict = {"activation_proxy_verified": False, "blockers": ["activation_proxy_missing"]}
    if args.activation_proxy_json:
        proxy_path = Path(args.activation_proxy_json)
        if proxy_path.is_file():
            proxy_report = json.loads(proxy_path.read_text(encoding="utf-8"))
            proxy_verdict = evaluate_proxy_report(
                proxy_report, min_layers=int(args.min_activation_proxy_layers)
            )
        else:
            proxy_verdict = {
                "activation_proxy_verified": False,
                "blockers": ["activation_proxy_missing"],
            }
    elif not args.require_activation_proxy:
        proxy_verdict = {"activation_proxy_verified": False, "blockers": [], "skipped": True}

    blockers = []  # type: List[str]
    blockers.extend(coverage["blockers"])
    blockers.extend(disjointness["blockers"])
    blockers.extend(files["blockers"])
    blockers.extend(holdout["blockers"])
    if args.require_activation_proxy:
        blockers.extend(proxy_verdict.get("blockers", []))

    return {
        "dataset_manifest_path": str(root / DATASET_MANIFEST_NAME),
        "calibration_envelope_path": str(root / ENVELOPE_NAME),
        "dataset_root": str(root),
        "dataset_sha256": manifest.dataset_sha256,
        "manifest": manifest,
        "coverage": coverage,
        "disjointness": disjointness,
        "frame_files": files,
        "calibration_envelope": envelopes.to_dict(),
        "holdout": holdout,
        "range_profile": profile,
        "activation_proxy": proxy_report,
        "activation_proxy_verdict": proxy_verdict,
        "blockers": sorted(set(blockers)),
    }


# ── CLI ─────────────────────────────────────────────────────────────────────


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13D Gate B calibration dataset")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--mode", choices=("capture", "evaluate", "all"), default="all")
    parser.add_argument("--output-root", required=True, help="external dataset directory")
    parser.add_argument("--dataset-name", default="carla-town03-int8-calibration")
    parser.add_argument("--carla-host", default="127.0.0.1")
    parser.add_argument("--carla-port", type=int, default=2000)
    parser.add_argument("--town", default="Town03")
    parser.add_argument("--routes", type=int, default=MIN_ROUTES)
    parser.add_argument("--route-spawn-points", default="")
    parser.add_argument("--weathers", default=DEFAULT_WEATHERS)
    parser.add_argument("--frames-per-cell", type=int, default=40)
    parser.add_argument("--fixed-delta-seconds", type=float, default=0.05)
    parser.add_argument("--camera-fps", type=float, default=5.0)
    parser.add_argument("--camera-width", type=int, default=640)
    parser.add_argument("--camera-height", type=int, default=360)
    parser.add_argument("--camera-fov", type=float, default=90.0)
    parser.add_argument("--ego-blueprint", default="vehicle.tesla.model3")
    parser.add_argument("--traffic-manager-port", type=int, default=8000)
    parser.add_argument("--manual-throttle", type=float, default=0.35)
    parser.add_argument("--warmup-ticks", type=int, default=20)
    parser.add_argument("--setup-timeout-sec", type=float, default=180.0)
    parser.add_argument("--run-timeout-sec", type=float, default=3600.0)
    parser.add_argument("--holdout-stride", type=int, default=5)
    parser.add_argument("--min-routes", type=int, default=MIN_ROUTES)
    parser.add_argument("--min-weather-profiles", type=int, default=MIN_WEATHER_PROFILES)
    parser.add_argument("--min-calibration", type=int, default=MIN_CALIBRATION_FRAMES)
    parser.add_argument("--min-holdout", type=int, default=MIN_HOLDOUT_FRAMES)
    parser.add_argument("--envelope-margin-ratio", type=float, default=DEFAULT_ENVELOPE_MARGIN_RATIO)
    parser.add_argument("--max-false-reject-rate", type=float, default=MAX_HOLDOUT_FALSE_REJECT_RATE)
    parser.add_argument("--activation-proxy-json", default="")
    parser.add_argument("--min-activation-proxy-layers", type=int, default=8)
    parser.add_argument("--require-activation-proxy", action="store_true")
    parser.add_argument("--skip-hash-verification", action="store_true")
    parser.add_argument("--output-dir", default="experiments/phase13")
    parser.add_argument("--require-dataset", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    run_id = args.run_id or new_run_id()
    evidence = Phase13DEvidence(Path(args.output_dir), run_id)
    environment = pc_environment()

    summary = {
        "phase": PHASE,
        "gate": "B_dataset",
        "run_id": run_id,
        "created_at_utc": utc_now_iso(),
        "mode": args.mode,
        "dataset_root": str(args.output_root),
        "calibration_dataset_captured": False,
    }  # type: Dict[str, Any]
    blockers = []  # type: List[str]
    manifest = None  # type: Optional[DatasetManifest]
    result = {}  # type: Dict[str, Any]

    try:
        if args.mode in ("capture", "all"):
            capture_payload = capture(args)
            summary["capture"] = {
                key: value for key, value in capture_payload.items() if key != "frames"
            }
            summary["calibration_dataset_captured"] = True
        if args.mode in ("evaluate", "all"):
            result = evaluate(args)
            manifest = result.pop("manifest")
            summary.update(
                {
                    "dataset_manifest_path": result["dataset_manifest_path"],
                    "calibration_envelope_path": result["calibration_envelope_path"],
                    "dataset_sha256": result["dataset_sha256"],
                    "coverage": result["coverage"],
                    "disjointness": result["disjointness"],
                    "frame_files": result["frame_files"],
                    "holdout": result["holdout"],
                    "range_profile": result["range_profile"],
                    "activation_proxy_verdict": result["activation_proxy_verdict"],
                }
            )
            blockers.extend(result["blockers"])
    except DatasetError as exc:
        blockers.append(exc.classification)
        summary["error"] = exc.message
    except Exception as exc:  # pragma: no cover - CARLA/runtime surface
        blockers.append("dataset_build_failed")
        summary["error"] = repr(exc)[:400]

    # Capture alone cannot earn Dataset Pass — only the evaluation decides that
    # — but a capture-only invocation still has to report whether it worked.
    executed_evaluation = args.mode in ("evaluate", "all") and manifest is not None
    executed_capture = bool(summary["calibration_dataset_captured"])
    completed = executed_capture if args.mode == "capture" else executed_evaluation
    passed = completed and not blockers
    summary["blockers"] = sorted(set(blockers))
    summary["dataset_gate_passed"] = bool(executed_evaluation and not blockers)
    summary["status"] = (
        STATUS_DATASET_PASS if summary["dataset_gate_passed"] else STATUS_BLOCKED
    )
    summary["pc_environment"] = environment
    summary.update(BOUNDARY_FIELDS)

    evidence.write_json("summary.json", summary)
    evidence.write_json("environment.json", environment)
    evidence.write_json(
        "dataset_manifest.json",
        manifest.to_dict() if manifest is not None else {"executed": False, "blockers": summary["blockers"]},
    )
    evidence.write_json(
        "range_metrics.json",
        {
            "range_profile": result.get("range_profile"),
            "calibration_envelope": result.get("calibration_envelope"),
            "holdout": result.get("holdout"),
            "int8_calibration_range_checked": bool(result.get("calibration_envelope")),
            "activation_range_checked": False,
            "runtime_tensorrt_internal_activations_observed": False,
        },
    )
    evidence.write_json(
        "activation_proxy.json",
        result.get("activation_proxy") or {"executed": False},
    )
    evidence.write_manifest("B_dataset", summary["status"])
    evidence.write_placeholders()
    evidence.write_fault_matrix([])
    evidence.write_events([])
    evidence.write_text(
        "commands.txt", "# Phase 13D Gate B\n%s %s\n" % (sys.executable, " ".join(sys.argv))
    )
    evidence.write_text(
        "README.md",
        "# Phase 13D Gate B evidence\n\nRun id: `%s`\n\nStatus: `%s`\n\n"
        "Controlled CARLA Town03 calibration corpus. Frames, manifests and envelopes live "
        "outside this repository and are never committed. The corpus is simulation data and "
        "is not real-world representative.\n" % (run_id, summary["status"]),
    )

    print(summary["status"])
    print("run_id=%s" % run_id)
    print("evidence_dir=%s" % evidence.run_dir)
    if manifest is not None:
        print("frame_count=%s" % manifest.frame_count)
        print("calibration_count=%s" % manifest.calibration_count)
        print("holdout_count=%s" % manifest.holdout_count)
        print("dataset_sha256=%s" % manifest.dataset_sha256)
    for key in ("coverage", "disjointness", "holdout"):
        payload = summary.get(key) or {}
        for name in (
            "coverage_passed",
            "disjointness_passed",
            "holdout_passed",
            "duplicate_sha256_count",
            "split_overlap_frame_id_count",
            "holdout_false_reject_rate",
        ):
            if name in payload:
                print("%s=%s" % (name, payload[name]))
    if summary["blockers"]:
        print("blockers=%s" % ",".join(summary["blockers"]), file=sys.stderr)

    exit_code = 0 if passed else 1
    # The CARLA Windows client faults (0xC0000409) while the interpreter
    # finalises its native handles. Every artefact is already written and every
    # line already printed by this point, but interpreter finalisation would
    # replace this exit code with a crash code and discard buffered output. So
    # after a CARLA session, flush and leave without finalising.
    sys.stdout.flush()
    sys.stderr.flush()
    if args.mode in ("capture", "all"):
        os._exit(exit_code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
