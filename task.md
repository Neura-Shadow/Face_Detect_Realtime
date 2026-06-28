# Current Task - Phase 12B-GRP

## Status

```text
Phase 12B-GRP GRP Controller Ablation Runtime Pass - all five calibrated Town03 routes passed with the grp_follower controller.
```

Maintained boundary:

```text
Phase 12B-GRP is a GRP-controller subset runtime pass only. It does not claim CARLA Leaderboard, formal route benchmark, infraction benchmark, all-controller ablation pass, linear controller pass, baseline mapper controller pass, merge, git tag, GitHub Release, CARLA package commit, Python venv commit, .env commit, runtime_logs commit, or raw experiment evidence commit.
```

## Evidence

- Runtime evidence dir: `experiments\phase12\20260628T065257Z`.
- Executed command: `scripts\run_phase12b_controller_ablation_experiment.py --execute-runtime --controller-mode grp_follower`.
- CARLA server readiness: Phase 11D `--require-ready` passed before runtime.
- `row_count=5`.
- `executed_row_count=5`.
- `passed_count=5`.
- `all_runtime_rows_passed=true`.
- All rows use `controller_mode=grp_follower`.
- All child rows returned `result=passed` and `exit_code=0`.
- All child metrics loaded from evidence.
- All child metrics assert:
  - `fixed_route_goal_reached=true`
  - `fixed_route_completion_verified=true`
  - `grp_route_following_verified=true`
  - `grp_fallback_used=false`
- Boundary fields remain false:
  - `route_benchmark_verified=false`
  - `infraction_benchmark_verified=false`
  - `leaderboard_evaluated=false`
  - `leaderboard_routes_exported=false`
  - `leaderboard_route_criteria_evaluated=false`
- Runtime raw outputs and child evidence remain local under `experiments\phase12`.
- CARLA was stopped after runtime; `127.0.0.1:2000` is no longer reachable and no CARLA/UE4/Unreal process remains.

## Per-Route Result

| route_id | goal_reach_step | distance_to_goal_m | collision_count | lane_invasion_count |
| --- | ---: | ---: | ---: | ---: |
| `route_01` | 2073 | 2.284790 | 0 | 27 |
| `route_02` | 2264 | 2.316571 | 0 | 28 |
| `route_03` | 1567 | 2.374137 | 0 | 10 |
| `route_04` | 1320 | 2.443187 | 0 | 10 |
| `route_05` | 4431 | 2.952668 | 0 | 8 |

## Validation

- Phase 12B-GRP runtime assertions: passed.
- Phase 12B-GRP documentation: added.
- Phase 12B-GRP py_compile: passed.
- Base Python Phase 11 checks: 6/6 passed.
- Base Python demo checks: 6/6 passed.
- Source commit boundary gate: passed with 8 staged source/docs files and no blocked artifacts.

## Next Action

Run final validations, stage source-only files, commit, push to `codex/phase-11o-source-commit-boundary`, update PR #1 while keeping it Draft/open/unmerged, and preserve generated runtime evidence outside git.
