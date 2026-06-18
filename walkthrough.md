# Walkthrough — Phase 11O Source Commit Boundary & Draft PR Preparation

1. Preserve Phase 11M as the strict GRP-backed fixed-route smoke pass.
2. Preserve Phase 11N as release artifact packaging only.
3. Add `scripts\run_phase11o_source_commit_checks.py`.
4. Add `docs\phase11o_source_commit_boundary_draft_pr.md`.
5. Update README, Phase 11 docs, release checklist, final report, portfolio summary, release notes, task, and walkthrough.
6. Stage only source/docs/config/frontend/backend/shared/workers/scripts/migrations and root project docs.
7. Keep `runtime_logs`, `release_artifacts`, local envs, caches, transient logs, `.env`, and CARLA packages out of git.
8. Run py_compile for Phase 11O and related Phase 11 runners.
9. Run base Phase 11 checks.
10. Run base demo checks.
11. Run `python scripts\run_phase11o_source_commit_checks.py --require-staged`.
12. Commit the local source boundary.
13. Leave remote push, GitHub Draft PR creation, and git tag release as explicit follow-up actions.

Current result:

```text
Phase 11O Source Commit Boundary Pass — source-only commit boundary prepared, staged boundary gate added, and Draft PR body prepared locally.
```

Source boundary:

```text
included=.gitignore, README.md, task.md, walkthrough.md, backend, config, docs, frontend, migrations, scripts, shared, workers
excluded=.env, runtime_logs, release_artifacts, test_env, node_modules, .next, __pycache__, *.pyc, *.log, local CARLA packages/envs
```

Draft PR:

```text
docs\phase11o_source_commit_boundary_draft_pr.md
```

Boundary fields:

```text
source_commit_boundary_verified=true
draft_pr_prepared=true
remote_pr_created=false
tag_created=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
```

Regression result:

```text
Phase 11O py_compile: passed
Base Python Phase 11 checks: 6/6 passed
Base Python demo checks: 6/6 passed
Phase 11O staged boundary gate: passed with 124 staged files
```
