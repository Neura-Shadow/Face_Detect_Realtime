# Phase 12C-YOLOv9-V — YOLOv9 Post-Unlock Verification

## Status

```text
Phase 12C-YOLOv9-SRC-V Passed — official YOLOv9 source adapter verified with no fallback in the CARLA Python 3.12 runtime.
```

Phase 12C-YOLOv9-V is a strict post-unlock verification gate. Its default unlock mode is now `external_source`: the operator provides `YOLOV9_ROOT` and `YOLOV9_WEIGHTS` for the official YOLOv9 source repository and selected weights, then the gate verifies that MA-VLNA can use `perception_backend=yolov9` without falling back. Package mode remains available for alternate implementations, but `pip show yolov9` is no longer the only valid readiness path.

This phase does not install packages, does not modify baseline requirements, does not start CARLA, and does not claim YOLOv9 model accuracy or CARLA benchmark status.

Phase distinction:

- Phase 12C-YOLOv9-SRC prepared the official external source adapter and no-fallback gate.
- Phase 12C-YOLOv9-SRC-V verified official source adapter no-fallback readiness in CARLA Python 3.12.
- Phase 12C-YOLOv9-R1 has been attempted and is blocked by local CARLA server reachability; full YOLOv9 runtime pass remains unverified.

## Evidence

```text
source_adapter_verified_evidence_dir=experiments\phase12\20260630T060621Z
post_unlock_external_source_verified_dir=experiments\phase12\20260630T061015Z
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
experiments\phase12\20260630T060823Z
```

The latest full 15-row Phase 12C matrix after target-Python dependency probing is:

```text
experiments\phase12\20260629T070603Z
```

The Phase 12C-YOLOv9-SRC source-adapter gate supersedes package-only readiness for the official YOLOv9 path:

```text
source_adapter_verified_evidence_dir=experiments\phase12\20260630T060621Z
yolov9_rows_refresh_dir=experiments\phase12\20260630T060823Z
post_unlock_external_source_verified_dir=experiments\phase12\20260630T061015Z
```

## Verification Result

```text
phase=Phase 12C-YOLOv9-V
status=yolov9_post_unlock_verified
authoritative_evidence_dir=experiments\phase12\20260630T061015Z
unlock_mode=external_source
post_unlock_verification_attempted=true
post_unlock_verified=true
require_verified_requested=true
strict_gate_exit_code=0
target_python_exists=true
carla_root_exists=true
yolov9_import_ready=false
yolov9_pip_metadata_ready=false
source_adapter_verified=true
YOLOV9_ROOT_configured=true
YOLOV9_WEIGHTS_configured=true
yolov9_source_root_ready=true
yolov9_weights_ready=true
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
phase12b_yolov9_dry_run_command_ready=true
phase11m_yolov9_cli_ready=true
phase11k_yolov9_cli_ready=true
phase12b_baseline_yolov9_cli_ready=true
phase12c_yolov9_rows_available=true
phase12c_yolov9_backend_unavailable_count=0
auto_install_performed=false
baseline_requirements_modified=false
carla_server_started=false
runtime_confirmation_executed=false
carla_route_runtime_executed=false
```

Interpretation: the code path is wired for `yolov9`, including Phase 12B / 11M / 11K / baseline mapper CLI acceptance. For the official YOLOv9 path, readiness is controlled by `YOLOV9_ROOT` and `YOLOV9_WEIGHTS`; those assets are now configured locally, EdgePerception verifies no fallback, and YOLOv9 optional rows are available / command-ready in the Phase 12C scaffold. This is not a CARLA route runtime confirmation and not a full Phase 12C perception ablation runtime pass.

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

Current local result with `--require-verified` exits zero after the external source root and weights are configured and EdgePerception verifies no fallback. The authoritative strict evidence records:

```text
authoritative_evidence_dir=experiments\phase12\20260630T061015Z
require_verified_requested=true
strict_gate_exit_code=0
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

YOLOv9 source repo remains external and is not committed. YOLOv9 weights remain external and are not committed. No YOLOv9 source is vendored into MA-VLNA. No baseline requirements were modified. No YOLOv9 model accuracy claim is made.

## Follow-up Runtime Attempt

Phase 12C-YOLOv9-R1 attempted a selected single-route runtime confirmation after this post-unlock verification:

```text
runtime_evidence_dir=experiments\phase12\20260630T094645Z
status=Phase 12C-YOLOv9-R1 Runtime Confirmation Blocked - selected YOLOv9 backend row did not complete or did not satisfy the selected runtime smoke gate.
blocked_reason=CARLA server is not reachable
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
post_unlock_verified=true
phase12c_yolov9_rows_available=true
backend_unavailable_count=0
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
runtime_confirmation_executed=false
carla_route_runtime_executed=false
```

The R1 runtime child was not launched because the formal wrapper preflight could not reach `127.0.0.1:2000`. This preserves blocked evidence without changing the post-unlock no-fallback pass.
