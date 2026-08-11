# Current Task - Phase 13A-EMBEDDED-CONTRACT-SIL

## Latest Status

```text
Phase 13A-EMBEDDED-CONTRACT-SIL Pass — command protocol, Safety MCU state machine, range-shift rejection, stale-command rejection, and host SIL tests passed.
```

```text
evidence_dir=experiments\phase13\20260808T065044Z
protocol_version=1
packet_size_bytes=64
fsm_test_result=passed
range_shift_tests_passed=true
sil_tests=28/28
portable_c_build_test_status=passed
crc_reject_count=1
stale_reject_count=1
sequence_reject_count=2
lease_reject_count=1
range_reject_count=3
false_accept_count=0
false_reject_count=0
```

The verified host path is `EdgePerception -> RangeShiftMonitor -> SafetyGate -> EmbeddedCommandBridge -> bounded binary packet -> Safety MCU emulator`. Portable C parser/FSM tests also passed through CMake/CTest. Generated evidence remains ignored.

Boundary: this is host software-in-the-loop evidence. It does not claim real MCU firmware, HIL, actuator control, CARLA benchmark, model accuracy, or OTA/security validation.

## Previous Task - Phase 12C-YOLOv9-R1 Formal Runtime Rerun

## Previous Status

```text
Phase 12C-YOLOv9-R1 Runtime Confirmation Blocked - selected YOLOv9 backend row did not complete or did not satisfy the selected runtime smoke gate.
```

Maintained boundary:

```text
This targeted rerun covers only `route_01 + grp_follower + yolov9`. It does not claim full Phase 12C perception ablation runtime pass, YOLOv9 model accuracy, RT-DETR runtime verification, CARLA Leaderboard, a formal route benchmark, or an infraction benchmark.
```

## Latest Evidence

```text
runtime_evidence_dir=experiments\phase12\20260713T190904Z
dry_run_evidence_dir=experiments\phase12\20260713T190811Z
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
source_adapter_verified=true
edge_yolov9_fallback_used=false
edge_yolov9_no_fallback_verified=true
carla_server_reachable=true
runtime_confirmation_executed=true
carla_route_runtime_executed=true
child_row_result=grp_blocked
steps_completed=0
goal_reached=false
yolo_runtime_row_verified=false
full_phase12c_perception_ablation_runtime_pass=false
```

The child reached the real CARLA path but `load_world("Town03_Opt")` exceeded the 60-second setup timeout before ego spawn or route ticks. Generated evidence remains local and ignored, and the CARLA server was stopped after the gate.

## Previous Phase - Phase 12D-VLM-TRIGGER-SCAFFOLD

Phase 12D-VLM-TRIGGER-SCAFFOLD remains prepared at commit `8d3b74cc`: the 20-row VLM-mode matrix is source-ready without claiming CARLA runtime or external VLM execution.

## Previous Phase - Phase 12C-SUM

Phase 12C-SUM remains the authoritative perception handoff: dummy runtime smoke is confirmed, YOLOv9 has route-begin/latency evidence without route completion, and RT-DETR is frozen as an external local-weight blocker. It does not claim full Phase 12C perception ablation runtime pass.

## Previous Phase - RT-DETR-ASSET-BLOCKER-FREEZE

```text
Phase 12C-R1-RT-DETR-ASSET-BLOCKER-FREEZE Completed - RT-DETR branch is formally frozen as external local-weight blocked and Phase 12C summary handoff is prepared.
```

```text
rtdetr_weights_local_rerun_evidence_dir=experiments\phase12\20260702T125105Z
rtdetr_asset_exec_evidence_dir=experiments\phase12\20260702T044516Z
rtdetr_unlock_evidence_dir=experiments\phase12\20260702T022636Z-1
rt_detr_branch_frozen_external_asset_blocker=true
rtdetr_dependency_ready=true
rtdetr_weights_ready=false
missing_weight_path=D:\AIModels\rtdetr\rtdetr-l.pt
rtdetr_no_fallback_ready=false
phase12c_rtdetr_rows_available=false
```

## Previous Phase - RT-DETR-WEIGHTS-LOCAL

```text
Phase 12C-R1-RT-DETR-WEIGHTS-LOCAL Blocked - local RT-DETR weights are still missing.
```

```text
rtdetr_weights_local_evidence_dir=experiments\phase12\20260702T125105Z
rtdetr_asset_exec_evidence_dir=experiments\phase12\20260702T044516Z
rtdetr_asset_setup_evidence_dir=experiments\phase12\20260702T040554Z
rtdetr_unlock_evidence_dir=experiments\phase12\20260702T022636Z-1
rtdetr_weights_configured=true
rtdetr_weights_ready=false
missing_weight_path=D:\AIModels\rtdetr\rtdetr-l.pt
edge_rtdetr_no_fallback_verified=false
phase12c_rtdetr_rows_available=false
recommended_next_phase=R1-RT-DETR-ASSET-SETUP
```

## Previous Phase - RT-DETR-ASSET-EXEC

```text
Phase 12C-R1-RT-DETR-ASSET-EXEC Blocked - RT-DETR setup execution did not reach no-fallback readiness.
```

```text
rtdetr_asset_exec_evidence_dir=experiments\phase12\20260702T044516Z
ultralytics_import_ready_after=true
ultralytics_version_after=8.4.84
dependency_install_requested=true
dependency_install_executed=true
dependency_install_exit_code=0
rtdetr_weights_configured=true
rtdetr_weights_ready=false
post_setup_smoke_executed=false
edge_rtdetr_no_fallback_verified=false
recommended_next_phase=R1-RT-DETR-ASSET-SETUP
```

## Previous Phase - RT-DETR-ASSET-SETUP

```text
Phase 12C-R1-RT-DETR-ASSET-SETUP Command-Ready - explicit RT-DETR setup commands and asset contract are written, but setup was not executed.
```

```text
rtdetr_asset_setup_evidence_dir=experiments\phase12\20260702T040554Z
dependency_install_requested=false
dependency_install_executed=false
rtdetr_weights_configured=false
rtdetr_weights_ready=false
post_setup_smoke_executed=false
edge_rtdetr_no_fallback_verified=false
recommended_next_phase=R1-RT-DETR-ASSET-SETUP
```

## Previous Phase - RT-DETR-UNLOCK

```text
Phase 12C-R1-RT-DETR-UNLOCK Blocked - RT-DETR optional backend could not be verified because dependency or model assets are unavailable.
```

```text
rtdetr_unlock_evidence_dir=experiments\phase12\20260702T022636Z-1
ultralytics_import_ready=false
rtdetr_weights_configured=false
rtdetr_weights_ready=false
edge_rtdetr_command_supported=true
edge_rtdetr_command_passed=true
edge_rtdetr_fallback_used=true
edge_rtdetr_no_fallback_verified=false
phase12c_rtdetr_rows_available=false
phase12c_rtdetr_backend_unavailable_count=5
recommended_next_phase=R1-RT-DETR-ASSET-SETUP
```

## Previous Phase - R1-YOLOv9-LIGHTWEIGHT

```text
Phase 12C-YOLOv9-R1-YOLOv9-LIGHTWEIGHT Blocked - lightweight YOLOv9 probe could not produce bounded no-fallback route-loop timing evidence.
```

```text
lightweight_evidence_dir=experiments\phase12\20260701T165325Z
lightweight_dry_run_evidence_dir=experiments\phase12\20260701T165245Z
lightweight_weights_configured=false
lightweight_weights_ready=false
lightweight_bottleneck_classification=lightweight_weights_missing
useful_lightweight_profile_verified=false
recommended_next_phase=R1-RT-DETR-UNLOCK
```

## Previous Phase - R1-LATENCY-OPT

```text
Phase 12C-YOLOv9-R1-LATENCY-OPT No-Improvement - optimization probe completed, but YOLOv9 forward latency remains too high for route completion.
```

```text
latency_opt_evidence_dir=experiments\phase12\20260701T115744Z
useful_latency_improvement_verified=false
best_variant_id=variant_01_baseline_recheck
best_variant_yolov9_avg_ms=2194.8
best_variant_effective_fps=0.168392
recommended_next_phase=R1-YOLOv9-LIGHTWEIGHT
```

## Previous Phase - R1-LATENCY

## Status

```text
Phase 12C-YOLOv9-R1-LATENCY Completed - selected YOLOv9 route-loop latency and cadence evidence produced without claiming route completion.
```

Maintained boundary:

```text
Phase 12C-YOLOv9-R1-LATENCY is latency and cadence evidence only. It does not claim selected YOLOv9 route runtime pass, route completion, YOLOv9 model accuracy, full Phase 12C perception ablation runtime pass, RT-DETR runtime verification, CARLA Leaderboard, formal route benchmark, or infraction benchmark.
```

## Background

```text
short_route_begin_evidence_dir=experiments\phase12\20260701T064944Z
setup_evidence_dir=experiments\phase12\20260701T045047Z
diagnostic_evidence_dir=experiments\phase12\20260630T150500Z
previous_runtime_evidence_dir=experiments\phase12\20260630T134322Z
```

R1-SHORT proved that the selected row enters the closed-loop route loop and emits early YOLOv9 no-fallback breadcrumbs. R1-LATENCY profiles route-loop speed, inference timing components, and diagnostic cadence behavior before any later route-completion attempt.

## Selected Row

```text
route_id=route_01
controller_mode=grp_follower
perception_backend=yolov9
```

## Generated Local Evidence

```text
latency_evidence_dir=experiments\phase12\20260701T103721Z
dry_run_evidence_dir=experiments\phase12\20260701T102823Z
```

Generated runtime output remains local and is not committed.

## Top-Level Result

```text
variant_count=4
executed_variant_count=2
completed_variant_count=1
blocked_variant_count=1
best_variant_id=variant_01_current_cadence
best_variant_effective_fps=0.239313
best_variant_yolov9_avg_ms=2522.06
baseline_current_cadence_yolov9_avg_ms=2522.06
latency_bottleneck_classification=yolov9_forward_dominant
recommended_next_phase=R1-LATENCY-OPT
latency_probe_completed=true
```

## Executed Variants

### variant_01_current_cadence

```text
diagnostic_steps_completed=50
duration_sec=208.931
effective_fps=0.239313
world_tick_count=50
rgb_frame_received_count=50
edge_perception_call_count=50
yolov9_inference_call_count=50
cached_perception_result_count=0
real_inference_ratio=1.0
edge_yolov9_fallback_used_during_route=false
partial_route_progress_seen=true
yolov9_preprocess_ms_avg=6.8
yolov9_model_forward_ms_avg=2512.84
yolov9_nms_ms_avg=2.84
yolov9_postprocess_ms_avg=0.0
yolov9_total_inference_ms_avg=2522.06
yolov9_total_inference_ms_p95=7014.8
latency_bottleneck_classification=yolov9_forward_dominant
```

### variant_02_stride_5_cached

```text
diagnostic_steps_completed=1
duration_sec=206.497
effective_fps=0.004843
world_tick_count=0
rgb_frame_received_count=0
edge_perception_call_count=0
yolov9_inference_call_count=0
partial_route_progress_seen=false
latency_bottleneck_classification=timeout_before_latency_profile
```

Stride-5 cached mode did not produce a valid route-loop latency profile in this run, so cache/cadence improvement is not yet verified.

## Implementation

```text
latency_wrapper=scripts\run_phase12c_yolov9_r1_latency_probe.py
diagnostic_stride_flags=workers\CARLA_Closed_Loop_Agent.py + scripts\run_phase11m_grp_route_following.py + scripts\run_phase12b_controller_ablation_experiment.py + scripts\run_phase12c_yolov9_runtime_timeout_diagnosis.py
documentation=docs\phase12c_yolov9_r1_latency_probe.md
```

Diagnostic stride/cache behavior is optional and disabled by default:

```text
perception_inference_stride=1
reuse_last_perception_between_inference=false
```

## Commands

Dry-run:

```powershell
python scripts\run_phase12c_yolov9_r1_latency_probe.py --dry-run --output-dir experiments\phase12
```

Latency probe:

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
$env:YOLOV9_ROOT = "D:\AIModels\yolov9"
$env:YOLOV9_WEIGHTS = "D:\AIModels\yolov9\yolov9-c-converted.pt"

D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase12c_yolov9_r1_latency_probe.py --route-id route_01 --host 127.0.0.1 --port 2000 --python-executable D:\CARLA\envs\ma-vlna-carla312\python.exe --base-python python --carla-root D:\CARLA\packages\CARLA_0.9.16 --output-dir experiments\phase12 --short-route-begin-evidence-dir experiments\phase12\20260701T064944Z --setup-evidence-dir experiments\phase12\20260701T045047Z --require-yolov9-ready --require-setup-passed --require-short-route-begin-passed --child-timeout-sec 600 --parent-timeout-sec 2400
```

## Boundary Fields

```text
yolo_runtime_row_verified=false
selected_route_completion_verified=false
full_phase12c_perception_ablation_runtime_pass=false
rt_detr_runtime_verified=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
leaderboard_routes_exported=false
leaderboard_route_criteria_evaluated=false
```

## Next Safe Step

The recommended next phase is `R1-LATENCY-OPT`, focused on YOLOv9 forward-path latency reduction or stronger diagnostic cadence isolation. A route-completion attempt remains premature from this evidence.

---

# Phase 13B-JETSON-IN-THE-LOOP-BRIDGE

## Scope

Connect the simulated CARLA world on the Windows simulation PC to the **real**
Jetson Orin NX compute node, and close the loop back into CARLA through the
portable C Virtual Safety MCU.

```text
validation_type=processor_in_the_loop
transport_medium=usb_gadget_ethernet
```

Physical: Jetson Linux, CPU/GPU/RAM, process and thread scheduling, network
stack, CUDA/TensorRT installation, thermal and resource telemetry, the USB cable
and the USB-gadget network transport.

Simulated: CARLA camera, environment, vehicle, Safety MCU, actuator and vehicle
physics.

Perception is `DummyPerceptionBackend`. TensorRT deployment is Phase 13C.

## Contracts

```text
frame_header_magic=JILF
frame_header_size_bytes=56
frame_codec=JPEG
frame_declared_decoded_pixel_format=BGR8
frame_payload_crc=CRC-32/ISO-HDLC over the encoded payload only

command_protocol_version=1
command_packet_size_bytes=64
command_crc_coverage_bytes=60
command_datagram_rule=one UDP datagram carries exactly one unchanged Phase 13A packet

ack_magic=JILA
ack_packet_size_bytes=48
ack_crc_coverage_bytes=44

buffer_pool_size=3
mailbox_depth=1
max_payload_bytes=4194304
```

Ports (all CLI-configurable): Jetson frame TCP 13510, Jetson control/clock/
metrics TCP 13513, Jetson ACK UDP 13512, PC command UDP 13511.

## Gates

- **Gate A** — local loopback, no CARLA and no Jetson. Permits only `Prepared`.
- **Gate B** — real Jetson transport: >=300 frames through the production TCP
  path plus >=1000 command/ACK cycles with >=990 valid ACKs. Command/ACK-only
  execution is not sufficient for Transport Pass.
- **Gate C** — CARLA closed loop: >=300 camera frames and at least one
  C-accepted non-SAFE_STOP diagnostic control applied to CARLA.

## Commands

Gate A (PC only):

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase13b_loopback_checks.py
```

Jetson node:

```bash
cd /home/myjetsonnx/Face_Detect_Realtime
git fetch origin
git checkout codex/phase-11o-source-commit-boundary
git pull --ff-only origin codex/phase-11o-source-commit-boundary
source /home/myjetsonnx/venvs/ma-vlna/bin/activate
python scripts/run_phase13b_jetson_node.py --run-id <RUN_ID> --bind-host 0.0.0.0 \
  --frame-port 13510 --control-port 13513 --pc-host 192.168.55.100 \
  --command-port 13511 --ack-port 13512 --require-real-jetson \
  --run-phase13a-preflight --output-dir experiments/phase13
```

Gate B:

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase13b_jil_checks.py `
  --run-id <RUN_ID> --jetson-host 192.168.55.1 --frame-port 13510 `
  --control-port 13513 --command-port 13511 --ack-port 13512 `
  --synthetic-frames 300 --command-ack-cycles 1000 --require-real-jetson `
  --output-dir experiments\phase13
```

Gate C:

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase13b_simulation_host.py `
  --run-id <RUN_ID> --carla-host 127.0.0.1 --carla-port 2000 `
  --jetson-host 192.168.55.1 --frame-port 13510 --control-port 13513 `
  --command-port 13511 --ack-port 13512 --mode lockstep --frames 300 `
  --fixed-delta-seconds 0.05 --camera-width 640 --camera-height 360 `
  --camera-fps 10 --map-load-mode reuse_or_load --setup-timeout-sec 180 `
  --warmup-ticks 20 --require-server --require-jetson --output-dir experiments\phase13
```

Firewall commands are generated but never executed. Windows ICS and the Jetson
firewall are never modified.

## Boundary Fields

```text
validation_type=processor_in_the_loop
physical_actuator_control_executed=false
physical_camera_verified=false
real_mcu_verified=false
real_s32k344_verified=false
full_hil_verified=false
real_can_uart_timing_verified=false
tensorrt_inference_verified=false
model_accuracy_verified=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
physical_vehicle_deployment=false
input_range_checked=true
activation_range_checked=false
quantization_saturation_checked=false
range_validation_scope=input_only_dummy_backend
power_measurement_available=false
```

## Next Safe Step

`Phase 13C` — TensorRT deployment on the real Jetson, using the Phase 13B
bridge as the transport and safety substrate.

## Phase 13B Runtime Result — executed 2026-08-11

```text
status=Phase 13B-JETSON-IN-THE-LOOP-BRIDGE Pass
runtime_pc_git_sha=a05e22f60848d6cc25dc17866e322b9f638ee6db
runtime_jetson_git_sha=a05e22f60848d6cc25dc17866e322b9f638ee6db
runtime_git_sha_match=true
runtime_code_changed_after_runtime=false

gate_a=Prepared (loopback passed, unit suites 83/83, CTest 2/2)
gate_b=Transport Pass  experiments\phase13\phase13b-20260811T145056Z
gate_c=Pass            experiments\phase13\phase13b-20260811T145709Z-gatec

real_jetson_detected=true
jetson_arch=aarch64
transport_medium=usb_gadget_ethernet
pc_source_address_detected=192.168.55.100

phase13a_python_preflight_passed=true (28/28)
phase13a_arm64_ctest_passed=true (2/2)
phase13a_arm64_binary_verified=true (ELF 64-bit LSB, ARM aarch64)
phase13a_arm64_direct_test_exit_code=0

gate_b_frames_sent=300
gate_b_frames_received=306
gate_b_frames_decoded=305
gate_b_frames_processed=305
gate_b_max_mailbox_depth=1
gate_b_transport_packets_sent=1319
gate_b_valid_acks_received=1314
gate_b_command_accept_count=1311
gate_b_command_reject_count=7

gate_c_carla_frames_sent=300
gate_c_carla_frames_processed=305
gate_c_carla_ticks=600
gate_c_command_accept_count=311
gate_c_command_reject_count=7
gate_c_virtual_actuator_control_applied_count=610
gate_c_virtual_actuator_active_control_applied_count=598
gate_c_virtual_actuator_safe_stop_applied_count=12
gate_c_lockstep_passed=true
gate_c_realtime_stale_gate_passed=true

clock_sync_valid=true
clock_uncertainty_us=392 (Gate B) / 477 (Gate C)
clock_valid_sample_count=40/40
clock_source=time.perf_counter_ns

fault_matrix_passed=true (28/28 on both gates)
false_accept_count=0
false_reject_count=0
```

## Next Safe Step (updated)

`Phase 13C` — TensorRT deployment on the real Jetson, using the verified
Phase 13B bridge as the transport and safety substrate.

---

# Phase 13C-TENSORRT-FP16-EDGE-PERCEPTION

## Scope

Replace the Phase 13B `DummyPerceptionBackend` on the real Jetson with a real
TensorRT FP16 perception backend, preserving the verified Phase 13B transport
and safety path.

```text
validation_type=processor_in_the_loop
precision=fp16
model_family=yolov9
model_variant=yolov9-c
batch_size=1
input_size=640x640
```

The TensorRT result is in the command authority path: an AI_ACTIVE diagnostic
command requires a fresh, successful, no-fallback TensorRT result for the same
frame id. Missing, invalid, stale, timed-out, range-invalid or fallback results
produce SAFE_STOP.

## Status

```text
status=Phase 13C-TENSORRT-FP16-EDGE-PERCEPTION Prepared
gate_a=passed (100/100 unit tests, py3.8 parse gate, Phase 13B regression)
gate_b=blocked
gate_c=blocked
gate_d=blocked
blocker=onnx_export_dependency_missing
```

The external YOLOv9 source and weights are present and verified. Every PC
environment carrying torch lacks the `onnx` package, and torch 2.12 requires it
for every export path. Phase 13C never installs dependencies automatically.

## Operator unlock

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install onnx
```

Then re-run `scripts\run_phase13c_onnx_export.py`.

## Commands

Gate A:

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase13c_checks.py
```

ONNX export (after the unlock above):

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase13c_onnx_export.py `
  --source-root D:\AIModels\yolov9 `
  --weights D:\AIModels\yolov9\yolov9-c-converted.pt `
  --output D:\AIModels\yolov9\exports\yolov9-c-640-b1.onnx `
  --img-size 640 --batch-size 1 --require-export
```

Gate B on the Jetson (engine build, then standalone benchmark):

```bash
ssh myjetsonnx@192.168.55.1 "cd /home/myjetsonnx/Face_Detect_Realtime && \
  source /home/myjetsonnx/venvs/ma-vlna/bin/activate && \
  python scripts/run_phase13c_engine_build.py \
    --onnx /home/myjetsonnx/models/ma-vlna/yolov9/yolov9-c-640-b1.onnx \
    --engine /home/myjetsonnx/models/ma-vlna/yolov9/yolov9-c-640-b1-trt852-fp16.engine \
    --precision fp16 --input-shape 1x3x640x640 --require-real-jetson --require-engine"
```

Gate C and Gate D:

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase13c_streamed_runtime.py `
  --jetson-host 192.168.55.1 --frames 300 --require-real-jetson --require-no-fallback

D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase13c_orchestrator.py `
  --jetson-host 192.168.55.1 `
  --engine /home/myjetsonnx/models/ma-vlna/yolov9/yolov9-c-640-b1-trt852-fp16.engine `
  --profile yolov9-c --camera-fps 5 --frames 300 `
  --command-validity-ms 1000 --safety-margin-ms 50 `
  --require-real-jetson --require-carla --require-no-fallback `
  --output-dir experiments\phase13
```

## Boundary Fields

```text
precision=fp16
fp16_engine_verified=false
int8_engine_built=false
int8_calibration_verified=false
qat_verified=false
input_range_checked=true
tensor_output_range_checked=true
detection_schema_checked=true
activation_range_checked=false
quantization_saturation_checked=false
int8_calibration_range_checked=false
range_validation_scope=tensorrt_fp16_input_and_final_output
model_accuracy_verified=false
map_evaluated=false
route_completion_verified=false
route_benchmark_verified=false
infraction_benchmark_verified=false
leaderboard_evaluated=false
full_hil_verified=false
real_mcu_verified=false
physical_camera_verified=false
physical_actuator_control_executed=false
physical_vehicle_deployment=false
```

## Next Safe Step

Install `onnx` in the export environment, re-run the export gate, then Gates
B/C/D. After a real FP16 Pass the next phase is
`Phase 13D-INT8-CALIBRATION-RANGE-SHIFT`.
