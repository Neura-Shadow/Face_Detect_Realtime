# Phase 11I — CARLA Runtime Evidence Pack & Structured Metrics

Purpose:
Phase 11I converts the Phase 11H real CARLA runtime pass into a reproducible evidence pack. It records the dedicated Python 3.12 runtime, CARLA 0.9.16 package, carla cp312 wheel, server endpoint, 5-step / 50-step real smoke commands, structured metrics, event logs, and regression results.

This is an evidence and observability phase, not a new driving capability phase.

## Final Status

```text
Phase 11I Evidence Pack Pass — structured evidence for real CARLA 5-step and 50-step smoke generated.
```

This status supports:

```text
Phase 11C Real CARLA Runtime Pass — 50-step real CARLA --require-server smoke test verified through setup/tick/control/cleanup.
```

It does not support:

```text
CARLA route completion verified
CARLA infraction metrics verified
CARLA Leaderboard passed
Real YOLO / RT-DETR verified
Real OpenAI-compatible VLM verified
```

## Evidence Directory

Generated evidence pack:

```text
runtime_logs\carla_runs\20260613T073948Z
```

Required files:

```text
runtime_logs\carla_runs\20260613T073948Z\manifest.json
runtime_logs\carla_runs\20260613T073948Z\metrics.json
runtime_logs\carla_runs\20260613T073948Z\events.jsonl
runtime_logs\carla_runs\20260613T073948Z\commands.txt
runtime_logs\carla_runs\20260613T073948Z\environment.txt
runtime_logs\carla_runs\20260613T073948Z\regression.txt
```

Additional raw stdout/stderr files are stored under:

```text
runtime_logs\carla_runs\20260613T073948Z\raw_outputs
```

## Evidence Runner

Added wrapper:

```text
scripts/run_phase11i_carla_evidence_pack.py
```

The wrapper only orchestrates existing gates with subprocess calls:

- Phase 11D `--require-ready`
- Phase 11C 5-step `--require-server`
- Phase 11C 50-step `--require-server`
- Base Python 3.10 regressions
- Python 3.12 CARLA environment regressions

It does not modify MA-VLNA control architecture, `EdgePerception`, `VLMReasoner`, `SafetyGate`, or CARLA adapter logic.

## Executed Command

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"

D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase11i_carla_evidence_pack.py `
  --host 127.0.0.1 `
  --port 2000 `
  --steps 50 `
  --perception-backend dummy `
  --require-server `
  --output-dir runtime_logs\carla_runs `
  --run-regressions
```

Result:

```text
Phase 11I Evidence Pack Pass — structured evidence for real CARLA 5-step and 50-step smoke generated.
evidence_dir=runtime_logs\carla_runs\20260613T073948Z
```

CARLA server was stopped after evidence collection.

## Manifest Summary

`manifest.json` records:

```json
{
  "phase": "Phase 11I",
  "status": "real_carla_runtime_smoke_pass",
  "carla_root": "D:\\CARLA\\packages\\CARLA_0.9.16",
  "python_executable": "D:\\CARLA\\envs\\ma-vlna-carla312\\python.exe",
  "python_version": "3.12.13",
  "carla_version": "0.9.16",
  "carla_wheel": "carla-0.9.16-cp312-cp312-win_amd64.whl",
  "host": "127.0.0.1",
  "port": 2000,
  "steps_requested": 50,
  "perception_backend": "dummy",
  "require_server": true,
  "server_executable": "D:\\CARLA\\packages\\CARLA_0.9.16\\CarlaUE4.exe",
  "benchmark_scope": "smoke_only",
  "route_completion_verified": false,
  "infraction_metrics_verified": false,
  "leaderboard_evaluated": false,
  "result": "passed",
  "regression_passed": true
}
```

## Metrics Summary

`metrics.json` records smoke-only runtime metrics:

```json
{
  "metrics_scope": "real_carla_smoke_only_not_benchmark",
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
  "vlm_enabled": false,
  "perception_backend": "dummy",
  "collision_count": null,
  "lane_invasion_count": null,
  "avg_speed_kmh": null,
  "max_speed_kmh": null,
  "distance_traveled_m": null,
  "fallback_used": false,
  "telemetry_fallback_used": true,
  "route_completion_verified": false,
  "infraction_metrics_verified": false,
  "leaderboard_evaluated": false,
  "result": "passed",
  "regression_passed": true
}
```

Important metric boundary:

- `collision_count` is `null` because no collision sensor is wired.
- `lane_invasion_count` is `null` because no lane invasion sensor is wired.
- Speed and distance metrics are `null` because this smoke gate does not measure them.
- `fallback_used=false` means the real CARLA runtime path did not fall back to fake runtime.
- `telemetry_fallback_used=true` means Supabase was not required and telemetry was written to local fallback JSONL.

## Events Summary

`events.jsonl` contains JSON events including:

```json
{"event": "setup_started", "step": null}
{"event": "carla_connected", "step": null}
{"event": "ego_spawned", "step": null}
{"event": "rgb_frame_received", "step": 0}
{"event": "control_applied", "step": 0}
{"event": "world_tick", "step": 0}
{"event": "step", "step": 1, "rgb_frame_received": true, "planner_action": "turn_left", "control_applied": true, "world_tick_advanced": true}
{"event": "cleanup_completed", "step": null}
{"event": "run_passed", "step": 50}
```

The observed planner action during the smoke run was `turn_left`. This is logged as an observed smoke behavior, not as a route-quality claim.

## Environment Snapshot

`environment.txt` records:

- Python executable and version.
- `carla.__file__`.
- `pip show carla`.
- TCP reachability for `127.0.0.1:2000`.
- `Test-NetConnection` output.

Key values:

```text
Python: D:\CARLA\envs\ma-vlna-carla312\python.exe
Python version: 3.12.13
carla version: 0.9.16
TCP: 127.0.0.1:2000 reachable
```

## Regression Proof

`regression.txt` records command return codes and stdout/stderr for:

```powershell
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase11_carla_checks.py
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase11d_carla_provisioning_gate.py --require-ready
D:\CARLA\envs\ma-vlna-carla312\python.exe -m py_compile scripts\run_phase11b_real_carla_smoke.py scripts\run_phase11d_carla_provisioning_gate.py scripts\run_phase11i_carla_evidence_pack.py
```

Results:

```text
Base Python 3.10 Phase 11 checks: 6/6 passed
Base Python 3.10 demo checks: 6/6 passed
Python 3.12 Phase 11 checks: 6/6 passed
Python 3.12 Phase 11D ready gate: passed
Python 3.12 py_compile: passed
```

## Remaining Unverified Items

- [ ] CARLA route completion verified
- [ ] CARLA infraction metrics verified
- [ ] CARLA Leaderboard passed
- [ ] Real YOLO / RT-DETR verified
- [ ] Real OpenAI-compatible VLM verified

## Final Claim

Phase 11I makes the Phase 11H real CARLA runtime pass auditable and repeatable with structured evidence. It remains a smoke-test evidence pack, not a benchmark, not a route-completion result, and not a CARLA Leaderboard submission.

## Extended By Phase 11J

Phase 11J extends this evidence pack with CARLA-native sensor instrumentation:

```text
Phase 11J Sensor Metrics Pass — real CARLA smoke generated collision, lane invasion, speed, and distance instrumentation.
```

Latest sensor metrics evidence:

```text
runtime_logs\carla_runs\20260613T082452Z
```

Phase 11J verifies sensor attachment and measurement during smoke. It still does not verify route completion, infraction benchmark, CARLA Leaderboard, real YOLO/RT-DETR, or real OpenAI-compatible VLM.
