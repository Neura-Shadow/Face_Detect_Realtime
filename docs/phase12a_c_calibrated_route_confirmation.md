# Phase 12A-C — Calibrated 5-Route Runtime Confirmation

## Status

```text
Phase 12A-C Calibrated Route Confirmation Pass — all five calibrated fixed Town03 routes reached the goal.
```

Phase 12A-C applies the Phase 12A-H horizon matrix back to the five fixed `Town03` routes and reruns each route through the unchanged Phase 11M GRP runner. It is runtime confirmation of the calibrated smoke setup, not CARLA Leaderboard, not a formal route benchmark, and not an infraction benchmark.

## Calibration Input

```text
experiments\phase12\20260620T140648Z
```

Calibrated horizon matrix:

```json
{
  "route_01": 2500,
  "route_02": 2800,
  "route_03": 2500,
  "route_04": 2500,
  "route_05": 5400
}
```

Route 05 uses the R05B slow-short-lookahead setting:

```text
target_speed_kmh=8.0
route_sampling_resolution_m=1.0
lookahead_waypoints=3
```

Routes 01-04 retain the Phase 12A baseline GRP setting:

```text
target_speed_kmh=18.0
route_sampling_resolution_m=2.0
lookahead_waypoints=8
```

## Runtime Evidence

```text
experiments\phase12\20260621T074706Z
```

Top-level output:

```text
manifest.json
summary.csv
summary.json
commands.txt
README.md
runs\<route_id>\<phase11m_timestamp>\
```

Aggregate result:

```text
row_count=5
confirmed_route_count=5
all_routes_confirmed=true
status=calibrated_route_confirmation_pass
```

| route_id | calibrated_horizon_steps | goal_reach_step | distance_to_goal_m | collision_count | lane_invasion_count |
|---|---:|---:|---:|---:|---:|
| `route_01` | 2500 | 2073 | 2.284790 | 0 | 27 |
| `route_02` | 2800 | 2264 | 2.316571 | 0 | 28 |
| `route_03` | 2500 | 1567 | 2.374137 | 0 | 10 |
| `route_04` | 2500 | 1320 | 2.443187 | 0 | 10 |
| `route_05` | 5400 | 4431 | 2.952242 | 0 | 8 |

## Commands

Dry run:

```powershell
python scripts\run_phase12a_c_calibrated_route_confirmation.py --dry-run --output-dir experiments\phase12
```

Real runtime:

```powershell
$env:CARLA_ROOT="D:\CARLA\packages\CARLA_0.9.16"
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12a_c_calibrated_route_confirmation.py --host 127.0.0.1 --port 2000 --output-dir experiments\phase12
```

## Verification

```text
python -m py_compile scripts\run_phase12a_c_calibrated_route_confirmation.py -> passed
python scripts\run_phase12a_c_calibrated_route_confirmation.py --dry-run --output-dir experiments\phase12 -> passed
Phase 12A-C runtime assertions -> passed
```

## Boundary

Phase 12A-C confirms the calibrated smoke horizon setup. It does not retroactively convert the original 2500-step Phase 12A route-scaling run into a pass, and it does not claim CARLA Leaderboard, formal route benchmark, infraction benchmark, real YOLO / RT-DETR verification, or real VLM verification.
