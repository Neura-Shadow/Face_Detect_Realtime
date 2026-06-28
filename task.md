# Current Task - Phase 12C-DUMMY

## Status

```text
Phase 12C-DUMMY Runtime Confirmation Pass - dummy backend rows confirmed in real CARLA runtime.
```

Maintained boundary:

```text
Phase 12C-DUMMY is a dummy perception backend runtime confirmation, not a YOLO runtime validation, RT-DETR runtime validation, CARLA Leaderboard result, formal route benchmark, infraction benchmark, merge, git tag, GitHub Release, CARLA package commit, Python venv commit, .env commit, runtime_logs commit, or raw experiment evidence commit.
```

## Runtime Scope

- Routes: calibrated 5-route `Town03` spawn-pair matrix.
- Controller: fixed `grp_follower`.
- Perception backend: fixed `dummy`.
- Runtime parent: `scripts\run_phase12c_dummy_runtime_confirmation.py`.
- Delegated runtime path: `scripts\run_phase12b_controller_ablation_experiment.py --execute-runtime --controller-mode grp_follower --perception-backend dummy`.

## Generated Local Evidence

- Output dir: `experiments\phase12\20260628T173019Z`.
- Child Phase 12B runtime dir: `experiments\phase12\20260628T173019Z\runs\20260628T173021Z`.
- Generated files:
  - `manifest.json`
  - `summary.json`
  - `summary.csv`
  - `commands.txt`
  - `environment.json`
  - `README.md`
  - `raw_outputs\phase12b_parent.stdout.txt`
  - `raw_outputs\phase12b_parent.stderr.txt`
- Generated output remains local and is not committed.

## Result

```text
row_count=5
passed_count=5
blocked_count=0
failed_count=0
collision_count_total=0
lane_invasion_count_total=83
all_dummy_routes_confirmed=true
```

All five calibrated dummy backend rows reached goal tolerance. Lane invasion counts are preserved as sensor metrics and do not make this an infraction benchmark.

## Validation

- `D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase11d_carla_provisioning_gate.py --carla-root D:\CARLA\packages\CARLA_0.9.16 --host 127.0.0.1 --port 2000 --steps 5 --require-ready`: passed.
- `D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12c_dummy_runtime_confirmation.py --host 127.0.0.1 --port 2000 --output-dir experiments\phase12 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --child-timeout-sec 2400 --parent-timeout-sec 14400`: passed.
- Runtime assertions:
  - child summary loaded
  - row count matches requested routes
  - all rows `grp_follower`
  - all rows goal reached
  - all rows runtime passed
  - benchmark boundary fields false

## Next Action

Run source regressions, source commit boundary gate, then stage source-only files, commit, push to `codex/phase-11o-source-commit-boundary`, and update PR #1 while keeping it Draft/open/unmerged.
