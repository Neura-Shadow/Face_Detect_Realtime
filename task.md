# Current Task - Phase 12B-SUM

## Status

```text
Phase 12B-SUM Controller Ablation Comparative Summary Prepared - GRP, linear, and baseline mapper evidence has been normalized into comparable controller and route tables.
```

Maintained boundary:

```text
Phase 12B-SUM is a comparative evidence summary, not a new runtime pass. It does not claim CARLA Leaderboard, formal route benchmark, infraction benchmark, all-controller runtime pass, merge, git tag, GitHub Release, CARLA package commit, Python venv commit, .env commit, runtime_logs commit, or raw experiment evidence commit.
```

## Source Evidence

- GRP final evidence: `experiments\phase12\20260628T065257Z`.
- Linear final evidence: `experiments\phase12\20260628T080731Z`.
- Baseline final evidence: `experiments\phase12\20260628T122108Z`.

## Generated Local Summary

- SUM output dir: `experiments\phase12\20260628T125344Z`.
- Generated files:
  - `controller_summary.csv`
  - `route_comparison.csv`
  - `summary.json`
  - `manifest.json`
  - `README.md`
- Generated output remains local and is not committed.

## Controller-Level Result

| controller_mode | outcome | passed_count | blocked_count | total_collision_count | avg_route_progress_pct | avg_distance_to_goal_m |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `grp_follower` | strongest goal-reach smoke controller | 5 | 0 | 0 | 99.884826 | 2.474271 |
| `linear_spawn_pair_follower` | route-progress smoke pass with high collision counts | 5 | 0 | 15222 | 23.698371 | 213.683811 |
| `baseline_planner_action_mapper` | closed-loop executable but route-progress blocked | 0 | 5 | 0 | 0.000000 | 284.172953 |

## Comparative Conclusion

- `grp_follower` is the only 5/5 fixed-route goal-reach smoke controller.
- `linear_spawn_pair_follower` passes only the route-progress smoke gate; it is not completion-proven and records high collision counts.
- `baseline_planner_action_mapper` executes closed-loop control and telemetry but makes no measurable spawn-pair route progress.
- Phase 12B remains a differentiated controller-ablation outcome, not an all-controller pass.

## Validation

- `python -m py_compile scripts\run_phase12b_controller_ablation_summary.py`: passed.
- `python scripts\run_phase12b_controller_ablation_summary.py --require-complete --output-dir experiments\phase12`: passed.
- SUM assertions:
  - controller rows = 3
  - route rows = 15
  - benchmark boundary fields false

## Next Action

Run full regression checks, source commit boundary gate, then stage source-only files, commit, push to `codex/phase-11o-source-commit-boundary`, and update PR #1 while keeping it Draft/open/unmerged.
