# Phase 12C-YOLOv9-V — YOLOv9 Post-Unlock Verification

## Status

```text
Phase 12C-YOLOv9-V Blocked — strict post-unlock verification was executed, but YOLOv9 no-fallback readiness could not be verified because the selected YOLOv9 package is not installed/importable in the CARLA Python 3.12 runtime.
```

Phase 12C-YOLOv9-V is a strict post-unlock verification gate. It assumes the operator has already installed the selected YOLOv9 implementation into the dedicated CARLA Python 3.12 runtime, then verifies that the MA-VLNA pipeline can use `perception_backend=yolov9` without falling back.

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

## Verification Result

```text
phase=Phase 12C-YOLOv9-V
status=yolov9_post_unlock_blocked
authoritative_evidence_dir=experiments\phase12\20260629T125701Z
post_unlock_verification_attempted=true
post_unlock_verified=false
require_verified_requested=true
strict_gate_exit_code=1
target_python_exists=true
carla_root_exists=true
yolov9_import_ready=false
yolov9_pip_metadata_ready=false
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

Interpretation: the code path is now wired for `yolov9`, including Phase 12B / 11M / 11K / baseline mapper CLI acceptance, but the selected YOLOv9 dependency is not installed/importable in `D:\CARLA\envs\ma-vlna-carla312`. Therefore EdgePerception still falls back to `DummyPerceptionBackend`, and the post-unlock gate must remain blocked.

## Pass Conditions

Phase 12C-YOLOv9-V can only pass when all of the following are true:

- `yolov9_import_ready=true`
- `yolov9_pip_metadata_ready=true`
- `edge_yolov9_command_passed=true`
- `edge_yolov9_fallback_used=false`
- `phase12c_yolov9_rows_available=true`
- Phase 12B / 11M / 11K / baseline mapper CLI probes accept `--perception-backend yolov9`

## Command

```powershell
python scripts\run_phase12c_yolov9_post_unlock_verification.py --output-dir experiments\phase12
```

Strict gate after operator unlock:

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install <YOLOV9_PACKAGE_SPEC>
python scripts\run_phase12c_yolov9_post_unlock_verification.py --output-dir experiments\phase12 --require-verified
```

Current local result with `--require-verified` exits nonzero until the selected YOLOv9 package is installed and importable in the CARLA Python 3.12 runtime. The authoritative strict evidence records:

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
