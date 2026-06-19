# Current Task — Phase 12A

## Status

```text
Phase 12A Route Scaling Prepared — batch runner, fixed route matrix, dry-run scaffold, and summary aggregation are implemented.
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
- Base Python Phase 11 checks: 6/6 passed.
- Base Python demo checks: 6/6 passed.

## Next Action

Run the Phase 12A dry-run and source checks, then optionally run the real CARLA Python 3.12 command when the external CARLA server is ready. Do not claim formal benchmark status or commit generated experiment outputs unless a later packaging phase explicitly requests it.
