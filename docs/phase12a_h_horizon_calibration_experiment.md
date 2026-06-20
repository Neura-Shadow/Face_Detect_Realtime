# Phase 12A-H — Horizon Calibration Experiment

## Status

```text
Phase 12A-H Horizon Calibration Pass — calibrated per-route step horizons generated for all five fixed Town03 routes.
```

This phase turns the Phase 12A / R05B evidence into a route-level step-horizon matrix. It does not rerun CARLA, does not import `carla`, does not modify the Phase 11M GRP controller, and does not relabel Phase 12A as a formal benchmark.

## Evidence Sources

Primary Phase 12A route-scaling evidence:

```text
experiments\phase12\20260619T113705Z
```

Route 05 completion evidence from R05B:

```text
experiments\phase12\20260620T115855Z
```

Phase 12A-H calibration output:

```text
experiments\phase12\20260620T140648Z
```

## Calibration Rule

```text
recommended_horizon_steps =
  max(min_horizon_steps, ceil(goal_reach_step * headroom_factor / round_to_steps) * round_to_steps)
```

Default settings:

```text
headroom_factor=1.2
round_to_steps=100
min_horizon_steps=2500
original_steps=2500
```

## Result

```text
row_count=5
calibrated_route_count=5
all_routes_calibrated=true
max_recommended_horizon_steps=5400
route05_calibration_source=phase12a_r05b_extended_pass
```

Recommended horizon matrix:

```json
{
  "route_01": 2500,
  "route_02": 2800,
  "route_03": 2500,
  "route_04": 2500,
  "route_05": 5400
}
```

| route_id | calibration_source | goal_reach_step | recommended_horizon_steps | collision_count | lane_invasion_count |
|---|---|---:|---:|---:|---:|
| `route_01` | `phase12a_2500_pass` | 2073 | 2500 | 0 | 27 |
| `route_02` | `phase12a_2500_pass` | 2264 | 2800 | 0 | 28 |
| `route_03` | `phase12a_2500_pass` | 1567 | 2500 | 0 | 10 |
| `route_04` | `phase12a_2500_pass` | 1321 | 2500 | 0 | 10 |
| `route_05` | `phase12a_r05b_extended_pass` | 4431 | 5400 | 0 | 8 |

## Commands

```powershell
python -m py_compile scripts\run_phase12a_h_horizon_calibration_experiment.py
python scripts\run_phase12a_h_horizon_calibration_experiment.py --output-dir experiments\phase12 --require-complete-calibration
```

The runner writes:

```text
experiments\phase12\<timestamp>\
  manifest.json
  summary.csv
  summary.json
  horizon_matrix.json
  commands.txt
  README.md
```

## Interpretation

Phase 12A-H shows that a single 2500-step horizon is not a fair smoke horizon across the selected fixed routes. Routes 01, 03, and 04 retain the 2500-step minimum. Route 02 receives a modest headroom increase to 2800 steps. Route 05 requires a distinct 5400-step horizon derived from the R05B 5200-step completion evidence.

This is a calibration result, not a route benchmark. It should inform future Phase 12B-style experiments that compare route outcomes under calibrated horizons, controller settings, and perception modes.

## Boundary

This is evidence-backed calibration smoke only. It is not CARLA Leaderboard, not a formal route benchmark, not an infraction benchmark, and not proof of general driving policy quality.
