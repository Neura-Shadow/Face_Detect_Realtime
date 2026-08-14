# MA-VLNA — Final Runbook

Operational reference for restoring context and inspecting the system after
time has passed. Every command below is taken from source already in this
repository — none are invented for this document. No passwords, tokens,
private keys, model binaries, TensorRT engines, secrets, or `.env` contents
appear here; where a command needs one, it is named as a placeholder.

For the full narrative and evidence behind the final state, see
[docs/final_project_status.md](final_project_status.md). For Phase 13G design
detail, see [docs/phase13g_ota_ab_rollback.md](phase13g_ota_ab_rollback.md).

## Repository

| | |
|---|---|
| Location | `Neura-Shadow/Face_Detect_Realtime` |
| Active branch | `codex/phase-11o-source-commit-boundary` |
| Final runtime/package SHA | `315432ae1894f6c4e023c1e350445e3a4ec44fd2` |
| Final repository HEAD | see `git log -1` on the branch above — documentation-only commits may follow the runtime SHA |
| Pull Request | [#1](https://github.com/Neura-Shadow/Face_Detect_Realtime/pull/1) — keep open, draft, unmerged unless a human explicitly decides otherwise |

```bash
git clone https://github.com/Neura-Shadow/Face_Detect_Realtime.git
git checkout codex/phase-11o-source-commit-boundary
git log --oneline -5
```

Two physical hosts are involved:

- **PC** — runs CARLA and the PC-side workers/orchestrators.
- **Jetson Orin NX** — runs the real FP16 TensorRT node, the C Virtual Safety
  MCU, and the Phase 13F/13G service and release infrastructure. Reached over
  the direct USB-gadget Ethernet link; the Jetson has no independent internet
  DNS, so code is transferred via `git bundle` when needed rather than a
  direct `git pull` on-target.

## PC / CARLA

CARLA and the Jetson relate as: CARLA supplies the simulated world, vehicle,
sensors and physics on the PC; the Jetson is the real compute node that
receives camera frames and returns command packets over the USB-gadget link;
the C Virtual Safety MCU (emulated) sits between the Jetson's command output
and CARLA's actuation, arbitrating every command. Nothing about this
relationship is Phase 13G-specific — 13G only changes *what code the Jetson
runs it from* (a release, not a checkout).

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase11b_real_carla_smoke.py --host 127.0.0.1 --port 2000 --steps 50 --require-server
```

See `README.md`'s Integration Status section and the individual
`docs/phase13*.md` files for the specific PC-side driver script used by each
phase's closed-loop or gate run — they differ per phase and are not
duplicated here.

## Jetson — service status

```bash
# Which unit is active, and where it runs from:
systemctl show ma-vlna-jetson-node.service -p ActiveState -p SubState -p MainPID -p WorkingDirectory -p ExecStart

# Is the boot-resume unit enabled (Phase 13G boot recovery)?
systemctl is-enabled ma-vlna-deploy-resume.service
systemctl is-enabled ma-vlna-jetson-node.service

# Recent logs:
journalctl -u ma-vlna-jetson-node.service -n 60 --no-pager
journalctl -u ma-vlna-deploy-resume.service --no-pager
```

`WorkingDirectory` should read `/opt/ma-vlna/current` (Phase 13G, release-
managed), not a path under `Face_Detect_Realtime` (which would mean the unit
is still the mutable Phase 13F git-checkout unit).

## Jetson — node health, READY, FP16, engine, preflight, AI authority

The deployment manager's `status` operation is the single source of truth: it
reports deployment state, the store's `current`/`previous`/`last-known-good`
links, the environment-layer agreement, and (unless `--skip-service-status`)
the live node health payload in one call.

```bash
source /home/myjetsonnx/venvs/ma-vlna/bin/activate
python /opt/ma-vlna/current/scripts/run_phase13g_deploy.py status \
    --root /opt/ma-vlna --unit ma-vlna-jetson-node.service
```

Fields to read from the `service_health` object in that output:

| Field | What it means |
|---|---|
| `state` | `READY` is the only state where AI command authority is held |
| `ai_authority_permitted` | must be `true` for the node to be issuing commands |
| `preflight_passed` | startup preflight (manifest, engine hash, repo SHA, TensorRT, CUDA, ports, …) |
| `precision` | must read `fp16` — INT8 is frozen `experimental_non_authoritative` and must never show here |
| `engine_sha256`, `manifest_sha256` | compare against the active release's `release.manifest.json` |
| `repository_sha` | the frozen Phase 13F runtime pin (constant across releases) — not the release identity; use `store_links`/`MA_VLNA_ACTIVE_RELEASE_ID` in the env layer for that |
| `restart_count`, `NRestarts` | should be `0` in steady state |
| `watchdog_enabled`, `watchdog_ping_count` | confirms `sd_notify` watchdog integration is live |

A standalone preflight dry run, without touching the running service:

```bash
python /opt/ma-vlna/current/scripts/run_phase13f_service.py --preflight-only \
    --service-name ma-vlna-jetson-node \
    --manifest /home/myjetsonnx/Face_Detect_Realtime/config/phase13f_service_manifest.json \
    --expected-repo-sha "$MA_VLNA_EXPECTED_SHA"
```

(`MA_VLNA_EXPECTED_SHA` comes from `/opt/ma-vlna/state/service.env` — see
below.)

## Phase 13G A/B — store, state, commands

Store layout:

```
/opt/ma-vlna/
├── releases/<release-id>/     immutable after installation
├── current          -> releases/<active>
├── previous         -> releases/<previous>
├── last-known-good  -> releases/<confirmed>
├── staging/
└── state/            deployment.json, service.env
```

```bash
# Where each link points, right now:
ls -l /opt/ma-vlna/

# The generated environment layer the node reads at startup
# (NOT a secret — it carries only an expected SHA and a release id):
cat /opt/ma-vlna/state/service.env

# Full deployment state, including transition history:
cat /opt/ma-vlna/state/deployment.json
```

Deployment manager operations (all via `run_phase13g_deploy.py <operation>
--root /opt/ma-vlna --unit ma-vlna-jetson-node.service`):

| Operation | Purpose |
|---|---|
| `status` | current state, store links, env-layer agreement, node health |
| `stage --package <path> --manifest <path>` | copy a package into `staging/`, verify its hash |
| `validate [--release-id <id>]` | run the full compatibility matrix against a staged release |
| `activate [--release-id <id>]` | atomic switch, restart, wait for READY, run probation, auto-confirm or auto-rollback |
| `confirm` | promote the current release to `last-known-good` |
| `rollback [--rollback-target <id>]` | manual switch back to last-known-good (or a named release) and restart |
| `resume` | boot-time recovery decision; run automatically by `ma-vlna-deploy-resume.service` |
| `publish-env` | (re)write the environment layer for whatever `current` already is, without restarting — needed once after any manual store edit, and always safe to re-run |
| `cleanup [--keep N]` | prune old releases; never removes `current`, `previous`, `last-known-good`, and never drops below two retained releases |

Rollback, concretely:

```bash
python /opt/ma-vlna/current/scripts/run_phase13g_deploy.py rollback \
    --root /opt/ma-vlna --unit ma-vlna-jetson-node.service
```

## What must never be committed or embedded here

Per project policy, unchanged since Phase 13F: no `/opt` or `/etc` files, no
release packages or engines/models, no secrets or `.env` contents, no runtime
state, no logs/evidence directories, no binaries or virtualenvs. Evidence for
past gates lives outside the repository (e.g. under the operator's home
directory on the Jetson) and is referenced by the relevant `docs/phase13*.md`
file, never copied into git.

## Recommended validation after restoring the system

```bash
# Full Phase 13G regression, on the Jetson (symlinks required):
python scripts/run_phase13g_checks.py

# Expect: mandatory_scenarios=16 covered=True, tests_run and skipped as
# reported, passed=True, store_scenarios_exercised=True. If the numbers
# differ from what docs/final_project_status.md records, treat that as a
# real signal to investigate, not something to silently reconcile.
```
