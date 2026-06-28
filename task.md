# Current Task - Phase 12C

## Status

```text
Phase 12C Perception Backend Ablation Prepared - backend matrix, optional dependency preflight, and command scaffold are implemented.
```

Maintained boundary:

```text
Phase 12C is a perception backend ablation scaffold, not a runtime pass. It does not claim YOLO runtime validation, RT-DETR runtime validation, CARLA Leaderboard, formal route benchmark, infraction benchmark, merge, git tag, GitHub Release, CARLA package commit, Python venv commit, .env commit, runtime_logs commit, or raw experiment evidence commit.
```

## Matrix

- Routes: calibrated 5-route `Town03` spawn-pair matrix.
- Controller: fixed `grp_follower`.
- Backends:
  - `dummy`
  - `yolo_optional`
  - `rt_detr_optional`

## Generated Local Summary

- Output dir: `experiments\phase12\20260628T170342Z`.
- Generated files:
  - `manifest.json`
  - `summary.csv`
  - `summary.json`
  - `commands.txt`
  - `README.md`
- Generated output remains local and is not committed.

## Result

```text
row_count=15
route_count=5
backend_count=3
available_row_count=5
backend_unavailable_count=10
```

本機目前未安裝 `ultralytics`，因此 YOLO / RT-DETR optional rows 正確標記為 `backend_unavailable`。這是預期的 prepared-state behavior，不會讓 Phase 12C scaffold 失敗。

## Validation

- `python -m py_compile scripts\run_phase12c_perception_backend_ablation.py`: passed.
- `python scripts\run_phase12c_perception_backend_ablation.py --output-dir experiments\phase12`: passed.
- Summary assertions:
  - `row_count=15`
  - dummy rows available
  - optional backend unavailable rows do not fail scaffold
  - CARLA import/server not required
  - benchmark boundary fields false

## Next Action

Run full regression checks, source commit boundary gate, then stage source-only files, commit, push to `codex/phase-11o-source-commit-boundary`, and update PR #1 while keeping it Draft/open/unmerged.
