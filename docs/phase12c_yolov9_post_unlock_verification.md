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
- Phase 12C-YOLOv9-R1-RERUN reached CARLA and launched the selected route runtime, but the child timed out before route metrics or goal-reach evidence were produced; full YOLOv9 runtime pass remains unverified.

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
runtime_evidence_dir=experiments\phase12\20260630T134322Z
previous_blocked_evidence_dir=experiments\phase12\20260630T094645Z
status=Phase 12C-YOLOv9-R1 Runtime Confirmation Blocked - selected YOLOv9 backend row did not complete or did not satisfy the selected runtime smoke gate.
carla_server_reachable=true
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
post_unlock_verified=true
phase12c_yolov9_rows_available=true
backend_unavailable_count=0
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
runtime_confirmation_executed=true
carla_route_runtime_executed=true
child_row_result=timeout
child_inner_exit_code=124
metrics_read_status=loaded
```

The R1-RERUN runtime child launched after CARLA became reachable, but the selected route child timed out before producing route metrics. This preserves blocked evidence without changing the post-unlock no-fallback pass.

## Follow-up Timeout Diagnosis

Phase 12C-YOLOv9-R1-DIAG keeps the post-unlock no-fallback pass intact and adds timeout classification:

```text
diagnostic_evidence_dir=experiments\phase12\20260630T150500Z
previous_runtime_evidence_dir=experiments\phase12\20260630T134322Z
post_unlock_verified=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
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

The diagnostic run did not reach per-frame YOLOv9 inference; it failed before CARLA setup completion and route-loop ticks.

## Follow-up Setup Recovery Probe

Phase 12C-YOLOv9-R1-SETUP preserves the post-unlock no-fallback result and probes CARLA setup before another route retry:

```text
setup_evidence_dir=experiments\phase12\20260701T045047Z
parent_wrapper=scripts\run_phase12c_yolov9_r1_setup_recovery.py
child_probe=scripts\run_phase12c_carla_setup_spawn_probe.py
post_unlock_verified=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
setup_scope=map_load_spawn_rgb_grp_warmup_only
setup_probe_passed=true
setup_blocker_classification=setup_probe_passed
yolo_runtime_row_verified=false
```

This setup probe does not change the post-unlock pass boundary into a CARLA route runtime pass.

## Follow-Up Route-Begin Probe

Phase 12C-YOLOv9-R1-SHORT uses the post-unlock no-fallback readiness and R1-SETUP evidence to run a bounded route-begin probe:

```text
short_route_begin_evidence_dir=experiments\phase12\20260701T064944Z
setup_evidence_dir=experiments\phase12\20260701T045047Z
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
post_unlock_verified=true
source_adapter_verified=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
diagnostic_steps_completed=50
world_tick_count=50
rgb_frame_received_count=50
edge_perception_call_count=50
yolov9_inference_call_count=11
edge_yolov9_fallback_used_during_route=false
short_route_begin_verified=true
yolo_runtime_row_verified=false
selected_route_completion_verified=false
```

This proves selected-row route-begin breadcrumbs only. It is not a route completion pass, YOLOv9 model accuracy result, full Phase 12C ablation, Leaderboard, formal route benchmark, or infraction benchmark.

## Follow-Up Latency Probe

Phase 12C-YOLOv9-R1-LATENCY uses the post-unlock no-fallback readiness and R1-SHORT route-begin evidence to measure route-loop latency:

```text
latency_evidence_dir=experiments\phase12\20260701T103721Z
executed_variant_count=2
completed_variant_count=1
blocked_variant_count=1
best_variant_effective_fps=0.239313
baseline_current_cadence_yolov9_avg_ms=2522.06
latency_bottleneck_classification=yolov9_forward_dominant
recommended_next_phase=R1-LATENCY-OPT
```

The post-unlock gate remains readiness evidence. R1-LATENCY adds performance/cadence evidence and still does not claim route completion, model accuracy, full Phase 12C ablation, or benchmark pass.

## Follow-Up: R1-LATENCY-OPT Probe

R1-LATENCY-OPT used the post-unlock no-fallback readiness and R1-LATENCY baseline to test bounded optimization variants. Evidence `experiments\phase12\20260701T115744Z` records `status=completed_no_improvement`, `latency_opt_completed=true`, `useful_latency_improvement_verified=false`, `best_variant_id=variant_01_baseline_recheck`, `best_variant_yolov9_avg_ms=2194.8`, and `recommended_next_phase=R1-YOLOv9-LIGHTWEIGHT`.

This follow-up keeps image-size, half precision, forward-only profiling, stride, and cached perception behavior diagnostic-only. It does not claim route completion, model accuracy, full Phase 12C ablation, Leaderboard, formal route benchmark, or infraction benchmark.

## Follow-Up: R1-YOLOv9-LIGHTWEIGHT Probe

R1-YOLOv9-LIGHTWEIGHT produced blocked evidence at `experiments\phase12\20260701T165325Z`. Baseline no-fallback readiness remained true, but `YOLOV9_LIGHTWEIGHT_WEIGHTS` was not configured, so no lightweight route-loop timing profile was executed.

`lightweight_bottleneck_classification=lightweight_weights_missing`, `useful_lightweight_profile_verified=false`, and `recommended_next_phase=R1-RT-DETR-UNLOCK`. This does not claim route completion, YOLOv9 model accuracy, full Phase 12C ablation, Leaderboard, formal route benchmark, or infraction benchmark.
