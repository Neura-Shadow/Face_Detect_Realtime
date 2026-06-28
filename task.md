# Current Task - Phase 12B-LIN

## Status

```text
Phase 12B-LIN Linear Spawn-Pair Controller Runtime Pass - all five calibrated Town03 routes passed the linear spawn-pair route-progress smoke gate after CARLA warm-up.
```

Maintained boundary:

```text
Phase 12B-LIN is a linear-controller route-progress smoke pass only. It does not claim CARLA Leaderboard, formal route benchmark, infraction benchmark, fixed-route goal-reach completion, all-controller ablation pass, baseline mapper controller pass, merge, git tag, GitHub Release, CARLA package commit, Python venv commit, .env commit, runtime_logs commit, or raw experiment evidence commit.
```

## Evidence

- Initial blocked evidence dir: `experiments\phase12\20260628T074345Z`.
- Initial blocked result: `row_count=5`, `passed_count=4`, `failed_count=1`, `all_runtime_rows_passed=false`.
- Initial blocked cause: `route_01` failed before setup due CARLA `load_world(Town03_Opt)` timeout.
- Warm-up route_01 retry evidence dir: `experiments\phase12\20260628T080432Z`.
- Final pass evidence dir: `experiments\phase12\20260628T080731Z`.
- Executed command: `scripts\run_phase12b_controller_ablation_experiment.py --execute-runtime --controller-mode linear_spawn_pair_follower`.
- CARLA server readiness: Phase 11D `--require-ready` passed before runtime.
- Final pass `row_count=5`.
- Final pass `executed_row_count=5`.
- Final pass `passed_count=5`.
- Final pass `all_runtime_rows_passed=true`.
- All final rows use `controller_mode=linear_spawn_pair_follower`.
- All final child rows returned `result=passed` and `exit_code=0`.
- All final child metrics loaded from evidence.
- All final child metrics assert:
  - `route_progress_verified=true`
  - `steps_completed=steps_requested`
  - `collision_sensor_attached=true`
  - `lane_invasion_sensor_attached=true`
- Boundary fields remain false:
  - `route_benchmark_verified=false`
  - `infraction_benchmark_verified=false`
  - `leaderboard_evaluated=false`
  - `leaderboard_routes_exported=false`
  - `leaderboard_route_criteria_evaluated=false`
- Runtime raw outputs and child evidence remain local under `experiments\phase12`.
- CARLA was stopped after runtime; `127.0.0.1:2000` is no longer reachable and no CARLA/UE4/Unreal process remains.

## Per-Route Final Pass Result

| route_id | route_progress_m | route_progress_pct | distance_to_goal_m | collision_count | lane_invasion_count | steps_completed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `route_01` | 307.662099 | 100.000000 | 6.914185 | 0 | 11 | 2500 |
| `route_02` | 24.236822 | 5.827989 | 391.652049 | 2677 | 11 | 2800 |
| `route_03` | 10.515416 | 5.744478 | 172.609764 | 2428 | 4 | 2500 |
| `route_04` | 6.983494 | 3.905891 | 171.816015 | 2439 | 1 | 2500 |
| `route_05` | 10.109821 | 3.013498 | 325.427040 | 7678 | 2 | 5400 |

## Interpretation

The final linear batch passed the Phase 11K route-progress smoke gate. It did
not prove safe completion: routes 02-05 remained far from the goal and recorded
large collision counts.

## Validation

- Phase 12B-LIN runtime blocked evidence assertions: passed.
- Phase 12B-LIN route_01 warm-up retry: passed.
- Phase 12B-LIN final 5-row pass assertions: passed.
- Phase 12B-LIN documentation: added.
- Phase 12B-LIN py_compile: passed.
- Base Python Phase 11 checks: 6/6 passed.
- Base Python demo checks: 6/6 passed.
- Source commit boundary gate: passed with 8 staged source/docs files and no blocked artifacts.

## Next Action

Run final validations, stage source-only files, commit, push to `codex/phase-11o-source-commit-boundary`, update PR #1 while keeping it Draft/open/unmerged, and preserve generated runtime evidence outside git.
