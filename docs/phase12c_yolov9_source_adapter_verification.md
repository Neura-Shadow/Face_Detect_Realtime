# Phase 12C-YOLOv9-SRC — Official YOLOv9 Source Adapter Verification

## Status

```text
Phase 12C-YOLOv9-SRC-V Passed — official YOLOv9 source adapter verified with no fallback in the CARLA Python 3.12 runtime.
```

This phase changes the YOLOv9 unlock contract from a fake `pip show yolov9` requirement to an operator-provided official source repository and weights path.

It does not commit YOLOv9 source, does not commit YOLOv9 weights, does not vendor YOLOv9 into this repository, does not start CARLA, does not execute YOLOv9 route runtime confirmation, and does not claim YOLOv9 model accuracy.

Phase distinction:

- Phase 12C-YOLOv9-SRC prepared the official external source adapter and no-fallback gate.
- Phase 12C-YOLOv9-SRC-V verified official source adapter no-fallback readiness in CARLA Python 3.12.
- Phase 12C-YOLOv9-R1-RERUN reached CARLA and launched the selected route runtime, but the child timed out before route metrics or goal-reach evidence were produced; full YOLOv9 runtime pass remains unverified.

## Environment Contract

Operator-provided local assets:

```powershell
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"

D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install -r "$env:YOLOV9_ROOT\requirements.txt"
```

The repository only records the env var names:

```text
YOLOV9_ROOT=<path to official YOLOv9 source repository>
YOLOV9_WEIGHTS=<path to selected YOLOv9 weights>
```

Expected source entries:

```text
detect.py
detect_dual.py
models/
utils/
```

## Evidence

Latest local source-adapter verification evidence:

```text
source_adapter_verified_evidence_dir=experiments\phase12\20260630T060621Z
```

Latest YOLOv9-only Phase 12C matrix refresh using source-adapter availability:

```text
yolov9_rows_refresh_dir=experiments\phase12\20260630T060823Z
post_unlock_external_source_verified_dir=experiments\phase12\20260630T061015Z
```

Generated files:

- `manifest.json`
- `summary.json`
- `commands.txt`
- `environment.json`
- `README.md`
- `raw_outputs/`

## Verification Result

```text
phase=Phase 12C-YOLOv9-SRC
status=yolov9_source_adapter_verified
source_adapter_verified=true
strict_gate_exit_code=0
require_verified_requested=true
YOLOV9_ROOT_configured=true
YOLOV9_WEIGHTS_configured=true
yolov9_source_root_configured=true
yolov9_weights_configured=true
yolov9_source_root_ready=true
yolov9_weights_ready=true
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
post_unlock_verified=true
unlock_mode=external_source
phase12c_yolov9_rows_available=true
backend_unavailable_count=0
runtime_confirmation_executed=false
carla_route_runtime_executed=false
auto_install_performed=false
baseline_requirements_modified=false
carla_server_started=false
```

Interpretation: the source adapter and strict gate are implemented, and the strict no-fallback gate now passes in the dedicated CARLA Python 3.12 runtime. YOLOv9 optional rows are now available / command-ready in the Phase 12C scaffold after no-fallback source adapter verification. This is not a full Phase 12C perception ablation runtime pass.

## Strict Pass Conditions

Strict mode can pass only when all of the following are true:

```text
yolov9_source_root_ready=true
yolov9_weights_ready=true
edge_yolov9_command_passed=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
source_adapter_verified=true
```

The current verified evidence satisfies these conditions. This is not a CARLA route runtime confirmation.

Strict command:

```powershell
python scripts\run_phase12c_yolov9_source_adapter_verification.py --output-dir experiments\phase12 --require-verified
```

Then refresh Phase 12C YOLOv9 rows:

```powershell
python scripts\run_phase12c_perception_backend_ablation.py --perception-backend-mode yolov9_optional --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --output-dir experiments\phase12
```

## Boundary

```text
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

Phase 12C-YOLOv9-SRC is not YOLOv9 route runtime validation, not YOLOv9 accuracy evidence, not RT-DETR validation, not CARLA Leaderboard, not a formal route benchmark, and not an infraction benchmark.

YOLOv9 source repo remains external and is not committed. YOLOv9 weights remain external and are not committed. No YOLOv9 source is vendored into MA-VLNA. No baseline requirements were modified. No YOLOv9 model accuracy claim is made.

## Follow-up Runtime Attempt

Phase 12C-YOLOv9-R1 has now attempted one selected runtime row after this source-adapter verification:

```text
runtime_evidence_dir=experiments\phase12\20260630T134322Z
previous_blocked_evidence_dir=experiments\phase12\20260630T094645Z
status=Phase 12C-YOLOv9-R1 Runtime Confirmation Blocked - selected YOLOv9 backend row did not complete or did not satisfy the selected runtime smoke gate.
carla_server_reachable=true
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
source_adapter_verified=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
runtime_confirmation_executed=true
carla_route_runtime_executed=true
child_row_result=timeout
child_inner_exit_code=124
metrics_read_status=loaded
```

The R1-RERUN blocker is the selected route child timeout, not the YOLOv9 source adapter. R1 remains selected single-route evidence only and is not a full Phase 12C perception ablation runtime pass.

## Follow-up Timeout Diagnosis

Phase 12C-YOLOv9-R1-DIAG preserved the source-adapter no-fallback pass and classified the selected-row runtime blocker:

```text
diagnostic_evidence_dir=experiments\phase12\20260630T150500Z
previous_runtime_evidence_dir=experiments\phase12\20260630T134322Z
source_adapter_verified=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
carla_server_reachable=true
timeout_classification=map_load_or_spawn_stall
diagnosis_confidence=high
diagnostic_steps_completed=0
heartbeat_count=0
world_tick_count=0
rgb_frame_received_count=0
edge_perception_call_count=0
yolov9_inference_call_count=0
yolo_runtime_row_verified=false
```

The source adapter remains verified. The diagnosis is not YOLOv9 route runtime pass evidence.
