# Phase 11O — Source Commit Boundary & Draft PR Preparation

## Status

```text
Phase 11O Source Commit Boundary Pass — source-only commit boundary prepared, staged boundary gate added, and Draft PR body prepared locally.
```

Maintained boundary:

```text
Phase 11O creates a reviewable source commit boundary and local Draft PR handoff only. It does not create a git tag, push to origin, open a remote pull request, run CARLA Leaderboard, verify a formal route benchmark, or verify an infraction benchmark.
```

## Purpose

Phase 11N 產生的是 workspace release artifact snapshot。Phase 11O 將該成果轉成可審查的 source boundary：

- 只讓 source、docs、config template、schema、frontend、backend、worker、migration 與 scripts 進入 commit。
- 保留 `runtime_logs/` 與 `release_artifacts/` 作為本機 evidence/artifact，不納入 git。
- 增加 staged-file gate，避免把 `.env`、本機 runtime、release zip、pycache、log 或暫存檔誤放進 PR。
- 準備一份可貼到 GitHub Draft PR 的 reviewer-facing body。

## Source Boundary

Included path classes:

```text
.gitignore
README.md
task.md
walkthrough.md
backend/
config/
docs/
frontend/
migrations/
scripts/
shared/
workers/
```

Excluded path classes:

```text
config/.env
.env*
runtime_logs/
release_artifacts/
test_env/
node_modules/
.next/
__pycache__/
*.pyc
*.log
local CARLA packages or Python environments
```

`config/.env.example` may be committed only as a placeholder template. It must not contain real keys, tokens, host credentials, or personal environment values.

## Local Gate

Run after staging and before commit:

```powershell
python scripts\run_phase11o_source_commit_checks.py --require-staged
```

Expected pass text:

```text
phase11o source commit boundary passed
```

The gate emits structured JSON with:

```text
source_commit_boundary_verified=true
draft_pr_prepared=true
remote_pr_created=false
tag_created=false
leaderboard_evaluated=false
route_benchmark_verified=false
infraction_benchmark_verified=false
```

## Validation Commands

Recommended local validation before opening a Draft PR:

```powershell
python -m py_compile scripts\run_phase11o_source_commit_checks.py scripts\run_phase11n_release_packaging.py scripts\run_phase11m_grp_route_following.py scripts\run_phase11_carla_checks.py
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
python scripts\run_phase11o_source_commit_checks.py --require-staged
```

Optional CARLA Python 3.12 gates remain isolated to the dedicated CARLA runtime:

```powershell
$env:CARLA_ROOT="D:\CARLA\packages\CARLA_0.9.16"
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase11d_carla_provisioning_gate.py --require-ready
```

## Draft PR

### Title

```text
Phase 11O: Source commit boundary and Draft PR preparation
```

### Body

```markdown
## Summary
- Convert the MA-VLNA Phase 11 workspace into a reviewable source commit boundary.
- Keep generated CARLA runtime evidence and release artifacts out of git while preserving documented references to the Phase 11M/11N evidence path.
- Add a Phase 11O staged-file gate and Draft PR handoff document.

## Scope
- Includes MA-VLNA workers, FastAPI backend, Next.js dashboard, shared schemas, Supabase migration, CARLA Phase 11 runners, and documentation through Phase 11O.
- Preserves CARLA-only dependencies outside baseline requirements.
- Keeps VLM, SafetyGate, SemanticPlanner, baseline CARLA control mapper, and benchmark claims unchanged.

## Validation
- `python -m py_compile scripts\run_phase11o_source_commit_checks.py scripts\run_phase11n_release_packaging.py scripts\run_phase11m_grp_route_following.py scripts\run_phase11_carla_checks.py`
- `python scripts\run_phase11_carla_checks.py`
- `python scripts\run_demo_checks.py`
- `python scripts\run_phase11o_source_commit_checks.py --require-staged`

## Evidence Boundary
- Phase 11M selected evidence remains local under `runtime_logs\carla_runs\20260614T173740Z`.
- Phase 11N release artifacts remain local under `release_artifacts\`.
- Source commit excludes `.env`, runtime logs, release zips, local Python envs, transient logs, caches, and CARLA packages.

## Explicit Non-Claims
- No CARLA Leaderboard evaluation.
- No formal route benchmark verification.
- No infraction benchmark verification.
- No real YOLO/RT-DETR performance verification.
- No real OpenAI-compatible VLM endpoint verification.
- No remote PR is opened by this local preparation step.
```

## Reviewer Notes

Phase 11O is intentionally about source hygiene and PR readiness. It upgrades Phase 11N from artifact packaging to a clean local commit boundary while keeping generated evidence and benchmark claims outside the source snapshot.
