# Current Task — Phase 12A

## Status

```text
Phase 12A Real Runtime Evidence Produced — real 5-route CARLA batch completed with aggregated evidence; strict all-route pass gate is blocked by route_05 goal-reach failure.
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
- Base Python Phase 11 checks: 6/6 passed.
- Base Python demo checks: 6/6 passed.

## Next Action

Use the Phase 12A aggregate evidence for diagnosis or ablation planning. Do not relabel the blocked all-route gate as a benchmark pass, and do not commit generated experiment outputs unless a later packaging phase explicitly requests selected artifacts.
