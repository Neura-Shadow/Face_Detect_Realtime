# Phase 12C-YOLOv9-V — YOLOv9 Post-Unlock Verification

## Status

```text
Phase 12C-YOLOv9-V Blocked — strict post-unlock verification was executed, but YOLOv9 no-fallback readiness could not be verified because the official external YOLOv9 source root and weights are not configured in the CARLA Python 3.12 runtime.
```

Phase 12C-YOLOv9-V is a strict post-unlock verification gate. Its default unlock mode is now `external_source`: the operator provides `YOLOV9_ROOT` and `YOLOV9_WEIGHTS` for the official YOLOv9 source repository and selected weights, then the gate verifies that MA-VLNA can use `perception_backend=yolov9` without falling back. Package mode remains available for alternate implementations, but `pip show yolov9` is no longer the only valid readiness path.

This phase does not install packages, does not modify baseline requirements, does not start CARLA, and does not claim YOLOv9 model accuracy or CARLA benchmark status.

## Evidence

```text
authoritative_evidence_dir=experiments\phase12\20260629T125701Z
historical_strict_evidence_dir=experiments\phase12\20260629T124925Z
```

Generated files:

- `manifest.json`
- `summary.json`
- `commands.txt`
- `environment.json`
- `README.md`
- `raw_outputs/`

The verifier also refreshed YOLOv9-only Phase 12C scaffold rows:

```text
experiments\phase12\20260629T124940Z
```

The latest full 15-row Phase 12C matrix after target-Python dependency probing is:

```text
experiments\phase12\20260629T070603Z
```

The Phase 12C-YOLOv9-SRC source-adapter gate supersedes package-only readiness for the official YOLOv9 path:

```text
post_unlock_external_source_evidence_dir=experiments\phase12\20260629T134856Z-1
source_adapter_evidence_dir=experiments\phase12\20260629T134856Z
yolov9_rows_refresh_dir=experiments\phase12\20260629T134856Z-1-2
```

## Verification Result

```text
phase=Phase 12C-YOLOv9-V
status=yolov9_post_unlock_blocked
authoritative_evidence_dir=experiments\phase12\20260629T125701Z
unlock_mode=external_source
post_unlock_verification_attempted=true
post_unlock_verified=false
require_verified_requested=true
strict_gate_exit_code=1
target_python_exists=true
carla_root_exists=true
yolov9_import_ready=false
yolov9_pip_metadata_ready=false
source_adapter_verified=false
yolov9_source_root_configured=false
yolov9_weights_configured=false
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=true
edge_yolov9_no_fallback_verified=false
phase12b_yolov9_dry_run_command_ready=true
phase11m_yolov9_cli_ready=true
phase11k_yolov9_cli_ready=true
phase12b_baseline_yolov9_cli_ready=true
phase12c_yolov9_rows_available=false
phase12c_yolov9_backend_unavailable_count=5
auto_install_performed=false
baseline_requirements_modified=false
carla_server_started=false
runtime_confirmation_executed=false
```

Interpretation: the code path is now wired for `yolov9`, including Phase 12B / 11M / 11K / baseline mapper CLI acceptance. For the official YOLOv9 path, readiness is controlled by `YOLOV9_ROOT` and `YOLOV9_WEIGHTS`; this local environment has not provided those assets, so EdgePerception still falls back to `DummyPerceptionBackend`, and the post-unlock gate must remain blocked.

## Pass Conditions

Phase 12C-YOLOv9-V external-source mode can only pass when all of the following are true:

- `yolov9_source_root_ready=true`
- `yolov9_weights_ready=true`
- `edge_yolov9_command_passed=true`
- `edge_yolov9_fallback_used=false`
- `edge_yolov9_no_fallback_verified=true`
- `source_adapter_verified=true`
- `phase12c_yolov9_rows_available=true`
- Phase 12B / 11M / 11K / baseline mapper CLI probes accept `--perception-backend yolov9`

## Command

```powershell
python scripts\run_phase12c_yolov9_post_unlock_verification.py --unlock-mode external_source --output-dir experiments\phase12
```

Strict gate after operator unlock:

```powershell
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install -r "$env:YOLOV9_ROOT\requirements.txt"
python scripts\run_phase12c_yolov9_source_adapter_verification.py --output-dir experiments\phase12 --require-verified
python scripts\run_phase12c_yolov9_post_unlock_verification.py --unlock-mode external_source --output-dir experiments\phase12 --require-verified
```

Current local result with `--require-verified` exits nonzero until the external source root and weights are configured and EdgePerception verifies no fallback. The authoritative strict evidence records:

```text
authoritative_evidence_dir=experiments\phase12\20260629T125701Z
require_verified_requested=true
strict_gate_exit_code=1
```

## Boundary

```text
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

Phase 12C-YOLOv9-V is not YOLOv9 runtime route validation, not YOLOv9 accuracy evidence, not RT-DETR validation, not CARLA Leaderboard, not a formal route benchmark, and not an infraction benchmark.
