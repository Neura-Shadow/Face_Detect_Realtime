# Phase 11N — Git Snapshot, Artifact Boundary & Release Packaging

Phase 11N converts the Phase 11M GRP-backed route-following result into a portable release artifact. It records the current git snapshot, defines an explicit artifact boundary, copies the Phase 11M evidence pack, and creates a release zip.

This phase does not create a git commit, tag, branch, push, CARLA Leaderboard export, formal route benchmark, or infraction benchmark.

## Final Status

```text
Phase 11N Release Packaging Pass — git snapshot, artifact boundary, and release package generated.
```

## Release Directory

```text
release_artifacts\<timestamp>
```

Generated files:

- `manifest.json`
- `artifact_boundary.json`
- `git_snapshot.txt`
- `checksums_sha256.txt`
- `package.sha256`
- `regression.txt`
- `ma-vlna_phase11n_release_<timestamp>.zip`

Package checksum:

```text
See the generated `manifest.json` and `package.sha256` in the release directory.
```

## Command

```powershell
python scripts\run_phase11n_release_packaging.py --phase11m-evidence-dir runtime_logs\carla_runs\20260614T173740Z --output-dir release_artifacts --run-regressions
```

## Git Snapshot

```text
branch=master
head_short=d2a6d20
status_clean=false
status_entry_count=<recorded in git_snapshot.txt>
tracked_file_count=11
```

The repository still contains uncommitted and untracked workspace changes. Phase 11N records that state in `git_snapshot.txt`; it does not stage, commit, tag, or push.

## Artifact Boundary

Included:

- source/docs from `backend`, `config`, `docs`, `frontend`, `migrations`, `scripts`, `shared`, and `workers`
- root files: `.gitignore`, `README.md`, `task.md`, `walkthrough.md`
- Phase 11M evidence files from `runtime_logs\carla_runs\20260614T173740Z`
- release metadata and checksums

Excluded:

- `.git`
- `.env`, `config/.env`, `.env.example`, and other `.env*` files
- `runtime_logs` except the selected Phase 11M evidence files
- `release_artifacts`, `test_env`, `__pycache__`, `node_modules`, `.next`
- legacy face assets: `images`, `EncodeFile.p`
- transient logs: `*.log`

Boundary metrics:

```text
source_file_count=<recorded in manifest.json>
evidence_file_count=6
secret_file_boundary_verified=true
artifact_boundary_prepared=true
```

## Phase 11M Evidence Validation

```text
phase=Phase 11M
result=passed
grp_route_required=true
grp_route_available=true
grp_fallback_used=false
grp_route_following_verified=true
fixed_route_goal_reached=true
fixed_route_completion_verified=true
best_distance_to_goal_m=2.283447
regression_passed=true
```

## Benchmark Boundary

```text
benchmark_boundary_prepared=true
benchmark_boundary_scope=structured_release_artifact_only_not_carla_leaderboard
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
```

## Regression Proof

```text
phase11n_py_compile: passed
base_phase11_carla_checks: 6/6 passed
base_demo_checks: 6/6 passed
```

## Scope Notes

- The package is a release artifact snapshot, not a git commit.
- The package is designed for review and handoff, not production deployment.
- The CARLA Python 3.12 runtime and CARLA server package remain external dependencies.
