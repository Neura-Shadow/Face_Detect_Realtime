# Phase 11J — CARLA Sensor Metrics & Infraction Instrumentation

Purpose:
Phase 11J extends the real CARLA smoke runtime with CARLA-native sensor instrumentation. It attaches collision and lane invasion sensors to the ego vehicle, records speed and distance from CARLA vehicle state, and writes structured metrics into the evidence pack.

This is smoke-level sensor instrumentation, not route benchmark, not CARLA Leaderboard, and not full autonomous driving evaluation.

This phase verifies that metrics can be measured during a real CARLA runtime smoke test.
It does not verify route completion, traffic-rule compliance, leaderboard score, or driving policy quality.

## Final Status

```text
Phase 11J Sensor Metrics Pass — real CARLA smoke generated collision, lane invasion, speed, and distance instrumentation.
```

This status means:

- CARLA collision sensor instrumentation attached successfully.
- CARLA lane invasion sensor instrumentation attached successfully.
- `collision_count` and `lane_invasion_count` were measured during a real smoke run.
- Speed and distance were measured from CARLA vehicle state.

This status does not mean:

- CARLA route completion verified.
- CARLA infraction benchmark verified.
- CARLA Leaderboard passed.
- Driving policy is safe.
- Real YOLO / RT-DETR verified.
- Real OpenAI-compatible VLM verified.

## Evidence Directory

Generated evidence pack:

```text
runtime_logs\carla_runs\20260613T082452Z
```

Required files:

```text
runtime_logs\carla_runs\20260613T082452Z\manifest.json
runtime_logs\carla_runs\20260613T082452Z\metrics.json
runtime_logs\carla_runs\20260613T082452Z\events.jsonl
runtime_logs\carla_runs\20260613T082452Z\commands.txt
runtime_logs\carla_runs\20260613T082452Z\environment.txt
runtime_logs\carla_runs\20260613T082452Z\regression.txt
```

Raw stdout/stderr evidence is stored under:

```text
runtime_logs\carla_runs\20260613T082452Z\raw_outputs
```

## Added Components

```text
workers/core/carla_metrics.py
scripts/run_phase11j_carla_sensor_metrics.py
```

Updated instrumentation points:

```text
workers/core/carla_adapter.py
workers/CARLA_Closed_Loop_Agent.py
```

The modifications only add observation and metrics logging:

- No VLM decision logic changed.
- No SafetyGate rules changed.
- No planner policy changed.
- `carla` remains outside baseline requirements.
- Base Python 3.10 is not required to import `carla`.

## Executed Command

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"

D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase11j_carla_sensor_metrics.py `
  --host 127.0.0.1 `
  --port 2000 `
  --steps 50 `
  --perception-backend dummy `
  --require-server `
  --enable-metric-sensors `
  --require-sensors `
  --output-dir runtime_logs\carla_runs `
  --run-regressions
```

Result:

```text
Phase 11J Sensor Metrics Pass — real CARLA smoke generated collision, lane invasion, speed, and distance instrumentation.
evidence_dir=runtime_logs\carla_runs\20260613T082452Z
```

CARLA server was stopped after evidence collection.

## Manifest Summary

`manifest.json` includes:

```json
{
  "phase": "Phase 11J",
  "status": "sensor_metrics_smoke_pass",
  "carla_root": "D:\\CARLA\\packages\\CARLA_0.9.16",
  "python_executable": "D:\\CARLA\\envs\\ma-vlna-carla312\\python.exe",
  "python_version": "3.12.13",
  "carla_version": "0.9.16",
  "sensor_metrics_enabled": true,
  "require_sensors": true,
  "collision_sensor_requested": true,
  "lane_invasion_sensor_requested": true,
  "speed_distance_metrics_enabled": true,
  "benchmark_scope": "smoke_only",
  "route_completion_verified": false,
  "infraction_benchmark_verified": false,
  "leaderboard_evaluated": false,
  "result": "passed"
}
```

## Metrics Summary

`metrics.json` records:

```json
{
  "phase": "Phase 11J",
  "steps_requested": 50,
  "steps_completed": 50,
  "setup_completed": true,
  "cleanup_completed": true,
  "carla_import_ok": true,
  "server_reachable": true,
  "ego_spawned": true,
  "rgb_frame_received": true,
  "control_applied": true,
  "world_tick_advanced": true,
  "perception_backend": "dummy",
  "vlm_enabled": false,
  "collision_sensor_attached": true,
  "lane_invasion_sensor_attached": true,
  "collision_count": 0,
  "lane_invasion_count": 0,
  "avg_speed_kmh": 1.051892,
  "max_speed_kmh": 10.583999,
  "distance_traveled_m": 0.722641,
  "fallback_used": false,
  "route_completion_verified": false,
  "infraction_benchmark_verified": false,
  "leaderboard_evaluated": false,
  "result": "passed",
  "regression_passed": true
}
```

Interpretation:

- `collision_count=0` is valid because the collision sensor attached and no collision event was emitted.
- `lane_invasion_count=0` is valid because the lane invasion sensor attached and no lane invasion event was emitted.
- Speed and distance are measured smoke-level telemetry from CARLA vehicle state.
- Distance includes observed ego transform displacement during the smoke run; it is not route progress or route completion.

## Events Summary

`events.jsonl` includes:

```json
{"event": "setup_started", "step": null}
{"event": "carla_connected", "step": null}
{"event": "ego_spawned", "step": null}
{"event": "rgb_camera_attached", "step": null}
{"event": "collision_sensor_attached", "step": null}
{"event": "lane_invasion_sensor_attached", "step": null}
{"event": "rgb_frame_received", "step": 1}
{"event": "world_tick", "step": 1}
{"event": "control_applied", "step": 1, "planner_action": "turn_left"}
{"event": "vehicle_state", "step": 1, "speed_kmh": 1.764, "distance_traveled_m": 0.0}
{"event": "cleanup_completed", "step": null}
{"event": "run_passed", "step": 50}
```

No synthetic collision or lane invasion was created. The run only verifies instrumentation.

## Regression Proof

`regression.txt` records:

```text
Base Python 3.10 Phase 11 checks: 6/6 passed
Base Python 3.10 demo checks: 6/6 passed
Python 3.12 Phase 11 checks: 6/6 passed
Python 3.12 Phase 11D ready gate: passed
Python 3.12 py_compile: passed
```

## Remaining Unverified Items

- [ ] CARLA route completion verified
- [ ] CARLA infraction benchmark verified
- [ ] CARLA Leaderboard passed
- [ ] Real YOLO / RT-DETR verified
- [ ] Real OpenAI-compatible VLM verified

## Final Claim

Phase 11J verifies that real CARLA smoke runs can attach native collision and lane invasion sensors, collect vehicle speed, compute distance traveled, and persist structured metrics/events. It remains a smoke-level instrumentation gate, not an autonomous-driving benchmark.
