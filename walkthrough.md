# Walkthrough — Phase 11P Remote Draft PR & Phase 12 Experiment Kickoff

1. Confirm branch `codex/phase-11o-source-commit-boundary` and HEAD `c69cad44`.
2. Confirm remote is `Neura-Shadow/Face_Detect_Realtime`.
3. Rerun the Phase 11O staged boundary gate against the 11O commit diff.
4. Rerun Phase 11 checks, demo checks, and py_compile.
5. Push the branch to origin.
6. Create a GitHub Draft PR targeting `master`.
7. Preserve Draft status; do not merge, tag, or create a GitHub Release.
8. Add `docs\phase12_experiment_kickoff_plan.md`.
9. Add `scripts\run_phase12_experiment_plan.py`.
10. Update `.gitignore` for Phase 12 raw run/output directories.
11. Update README, Phase 11 handoff docs, release checklist, final report, task, and walkthrough.
12. Run Phase 12 scaffold validation without CARLA.
13. Commit Phase 12 kickoff scaffold as the second commit.

Current result:

```text
Phase 11P Draft PR Pass — remote Draft PR created for source-only Phase 11 boundary.
Phase 12 Experiment Kickoff Pass — experiment planning and scaffold created without running large experiments.
```

Remote PR:

```text
https://github.com/Neura-Shadow/Face_Detect_Realtime/pull/1
draft=true
merged=false
```

Phase 12 scaffold:

```text
docs\phase12_experiment_kickoff_plan.md
scripts\run_phase12_experiment_plan.py
experiments\phase12\20260619T061407Z
```

Boundary fields:

```text
source_commit_boundary_verified=true
draft_pr_created=true
draft_pr_remains_draft=true
merged=false
tag_created=false
github_release_created=false
large_experiment_executed=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
```

Regression result:

```text
Phase 12 py_compile: passed
Phase 12 scaffold command: passed
Base Python Phase 11 checks: 6/6 passed
Base Python demo checks: 6/6 passed
```
