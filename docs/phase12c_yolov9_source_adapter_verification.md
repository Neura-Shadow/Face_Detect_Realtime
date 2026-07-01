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

## Follow-up Setup Recovery Probe

Phase 12C-YOLOv9-R1-SETUP reuses the same source-adapter readiness gate and then probes only CARLA setup/spawn stages:

```text
setup_evidence_dir=experiments\phase12\20260701T045047Z
parent_wrapper=scripts\run_phase12c_yolov9_r1_setup_recovery.py
child_probe=scripts\run_phase12c_carla_setup_spawn_probe.py
source_adapter_verified=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
setup_scope=map_load_spawn_rgb_grp_warmup_only
setup_probe_passed=true
setup_blocker_classification=setup_probe_passed
yolo_runtime_row_verified=false
```

The source adapter can remain verified while the selected route runtime remains blocked.

## Follow-Up Route-Begin Probe

Phase 12C-YOLOv9-R1-SHORT uses this official YOLOv9 source adapter readiness in a bounded route-begin probe:

```text
short_route_begin_evidence_dir=experiments\phase12\20260701T064944Z
setup_evidence_dir=experiments\phase12\20260701T045047Z
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
source_adapter_verified=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
diagnostic_steps_completed=50
world_tick_count=50
rgb_frame_received_count=50
edge_perception_call_count=50
yolov9_inference_call_count=11
edge_yolov9_fallback_used_during_route=false
partial_route_progress_seen=true
short_route_begin_verified=true
yolo_runtime_row_verified=false
```

This confirms early route-loop YOLOv9 no-fallback inference for the selected row only. It is not route completion, model accuracy verification, full Phase 12C ablation, Leaderboard, formal route benchmark, or infraction benchmark evidence.

## Follow-Up Latency Probe

Phase 12C-YOLOv9-R1-LATENCY profiles the same selected row after route-begin entry:

```text
latency_evidence_dir=experiments\phase12\20260701T103721Z
best_variant_id=variant_01_current_cadence
best_variant_effective_fps=0.239313
baseline_current_cadence_yolov9_avg_ms=2522.06
yolov9_model_forward_ms_avg=2512.84
latency_bottleneck_classification=yolov9_forward_dominant
recommended_next_phase=R1-LATENCY-OPT
```

The official source adapter remains no-fallback verified; the measured bottleneck is runtime model-forward latency, not missing source readiness. This is still not route completion or model accuracy evidence.

## Follow-Up: R1-LATENCY-OPT Probe

R1-LATENCY-OPT completed bounded optimization profiling at `experiments\phase12\20260701T115744Z` with `status=completed_no_improvement`. The best variant was `variant_01_baseline_recheck` with `best_variant_yolov9_avg_ms=2194.8`, `best_avg_ms_improvement_pct=12.976`, and `best_fps_improvement_pct=-29.635`; `useful_latency_improvement_verified=false`.

The source adapter remains verified. The remaining issue is insufficient YOLOv9 forward-latency improvement, so the recommended next phase is `R1-YOLOv9-LIGHTWEIGHT`, not route completion or full Phase 12C ablation.

## Follow-Up: R1-YOLOv9-LIGHTWEIGHT Probe

R1-YOLOv9-LIGHTWEIGHT produced blocked evidence at `experiments\phase12\20260701T165325Z`. Baseline no-fallback readiness remained true, but `YOLOV9_LIGHTWEIGHT_WEIGHTS` was not configured, so no lightweight route-loop timing profile was executed.

`lightweight_bottleneck_classification=lightweight_weights_missing`, `useful_lightweight_profile_verified=false`, and `recommended_next_phase=R1-RT-DETR-UNLOCK`. This does not claim route completion, YOLOv9 model accuracy, full Phase 12C ablation, Leaderboard, formal route benchmark, or infraction benchmark.

## Follow-Up: R1 Formal Runtime Gate Rerun

The latest selected runtime confirmation gate produced blocked evidence at `experiments\phase12\20260701T172906Z`. The external YOLOv9 source-root and weights remained ready, and `EdgePerception --test yolov9` stayed no-fallback: `edge_yolov9_fallback_used=false` and `edge_yolov9_no_fallback_verified=true`. The runtime blocker was `carla_server_reachable=false`, so no child route runtime was launched and `metrics_read_status=not_run`.

This is not a full Phase 12C perception ablation runtime pass, not YOLOv9 accuracy evidence, not RT-DETR runtime verification, not CARLA Leaderboard, not a formal route benchmark, and not an infraction benchmark.
