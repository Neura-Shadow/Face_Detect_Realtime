# Current Task — Phase 12A-R05B

## Status

```text
Phase 12A-R05B Pass — late-route waypoint progression diagnosed; extended 5200-step run reached the fixed Route 05 goal.
```

Maintained boundary:

```text
Phase 12A is controlled multi-route smoke orchestration only; no CARLA Leaderboard, formal route benchmark, infraction benchmark, merge, git tag, GitHub Release, CARLA package commit, Python venv commit, .env commit, runtime_logs commit, or release_artifacts commit is created.
```

## Evidence

- Added `scripts\run_phase12a_route_scaling_experiment.py`.
- Added `docs\phase12a_carla_route_scaling_experiment.md`.
- Updated `.gitignore` to keep `experiments\phase12\<timestamp>` output local by default.
- Updated README, Phase 12 kickoff plan, release checklist, final report, task, and walkthrough.
- Route matrix: `route_01 3->30`, `route_02 8->52`, `route_03 12->74`, `route_04 25->101`, `route_05 40->126`.
- Batch policy: continue all routes; exit success only if all five child Phase 11M runs pass.
- Dry-run policy: write manifest, commands, README, and five dry-run summary rows without launching CARLA.
- Dry-run output dir: `experiments\phase12\20260619T110549Z`.
- Batch runner does not import CARLA and does not modify VLM, SafetyGate, SemanticPlanner, GRP controller, or baseline requirements.
- benchmark_boundary_prepared: true.
- route_benchmark_verified: false.
- infraction_benchmark_verified: false.
- leaderboard_evaluated: false.
- Phase 12A py_compile: passed.
- Phase 12A dry-run: passed with 5 route rows.
- Phase 12A dry-run summary assertions: passed.
- Phase 12A real CARLA run: completed with exit code 1 because strict all-route gate blocked.
- Phase 12A real evidence dir: `experiments\phase12\20260619T113705Z`.
- Phase 12A real evidence assertions: passed.
- Phase 12A real aggregate result: `passed_count=4`, `blocked_or_failed_count=1`, `all_routes_passed=false`.
- route_05 result: `goal_reach_blocked`, `distance_to_goal_m=322.443754`, `collision_count=2408`.
- route_05 failure diagnosis: first collision at step 88 against `traffic.traffic_light`; progress stayed near 3.89%.
- Added `scripts\run_phase12a_r05_recovery_experiment.py`.
- Added `docs\phase12a_r05_failure_diagnosis_recovery.md`.
- Phase 12A-R05 dry-run: passed with baseline reference plus 4 recovery variant commands.
- Phase 11D ready gate: passed before real R05 recovery runtime.
- Phase 12A-R05 real evidence dir: `experiments\phase12\20260620T110904Z`.
- Phase 12A-R05 real aggregate result: `recovery_attempt_count=4`, `recovered_count=0`, `recovery_passed=false`.
- Best observed variant: `r05_slow_short_lookahead`, `route_progress_pct=71.067782`, `distance_to_goal_m=99.482140`, `collision_count=0`, `lane_invasion_count=3`.
- R05 recovery conclusion: early traffic-light collision can be avoided with short lookahead / denser sampling, but strict fixed-route goal reach remains blocked.
- Phase 12A-R05 py_compile: passed.
- Phase 12A-R05 evidence assertions: passed.
- Added `scripts\run_phase12a_r05b_waypoint_progression_diagnosis.py`.
- Added `docs\phase12a_r05b_late_route_waypoint_progression_diagnosis.md`.
- Phase 12A-R05B py_compile: passed.
- Phase 12A-R05B dry-run: passed with source reference plus 5200-step extended command.
- Phase 12A-R05B evidence assertions: passed.
- Phase 12A-R05B source diagnosis: `r05_slow_short_lookahead` was still progressing at step 2500, with final 200-step `grp_index_delta=21`, `route_progress_delta_m=20.358841`, and `distance_to_goal_delta_m=19.420991`.
- Phase 12A-R05B 4000-step diagnostic: still blocked, `distance_to_goal_m=45.168395`, `grp_current_waypoint_index=392`, `collision_count=0`, and status remained `progressing_step_budget_limited`.
- Phase 12A-R05B final evidence dir: `experiments\phase12\20260620T115855Z`.
- Phase 12A-R05B final result: `extended_goal_reached=true`, `goal_reach_step=4431`, `distance_to_goal_m=2.950533`, `collision_count=0`, `lane_invasion_count=8`.
- R05B conclusion: the 2500-step Route 05 failure was horizon-limited, not a late-route waypoint-index stall. This does not retroactively change the original Phase 12A all-route gate.
- Base Python Phase 11 checks: 6/6 passed.
- Base Python demo checks: 6/6 passed.

## Next Action

Use the R05B diagnosis to decide whether Phase 12B should standardize route-specific horizon budgets or introduce controller-level time/progress normalization. Do not relabel the original 2500-step Phase 12A gate as a benchmark pass, and do not commit generated experiment outputs unless a later packaging phase explicitly requests selected artifacts.
