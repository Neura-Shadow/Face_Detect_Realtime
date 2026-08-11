# Phase 13C — TensorRT FP16 Edge Perception

Phase 13C replaces the Phase 13B `DummyPerceptionBackend` on the **real** Jetson
Orin NX with a real TensorRT FP16 perception backend, while preserving the
verified Phase 13B Jetson-in-the-loop transport and safety path unchanged.

`validation_type = processor_in_the_loop` · `precision = fp16`

---

## 1. Status of this phase

**`Phase 13C-TENSORRT-FP16-EDGE-PERCEPTION Prepared`** — the TensorRT source
integration, asset contracts, unit tests and local fail-closed gates pass, but
no real Jetson FP16 engine was verified.

Gates B, C and D are **blocked** by a verified external dependency gap:

```
blocker = onnx_export_dependency_missing
```

Every Python environment on the simulation PC that has PyTorch also lacks the
`onnx` package, and PyTorch 2.12 requires it for *every* export path:

| Environment | Python | torch | `onnx` | `torch.onnx.export` |
| --- | --- | --- | --- | --- |
| `D:\CARLA\envs\ma-vlna-carla312` | 3.12.13 | 2.12.1+cpu | absent | `OnnxExporterError('Module onnx is not installed!')` |
| `C:\Users\zongx\anaconda3` | 3.10.14 | 2.12.0+cpu | absent | same |
| `D:\Face_Detect_Realtime\test_env` | 3.10.14 | 2.12.0+cpu | absent | same |

Passing `dynamo=False` to select the legacy TorchScript exporter does **not**
avoid it in torch 2.12. The Jetson has neither torch nor onnx, so the export
cannot be moved there either.

Phase 13C is forbidden from installing dependencies automatically, so the run
stops here rather than silently installing a package. **Operator unlock:**

```bash
D:\CARLA\envs\ma-vlna-carla312\python.exe -m pip install onnx
```

Then re-run `scripts/run_phase13c_onnx_export.py`. Nothing else is blocked: the
external YOLOv9 source and weights are both present and verified.

---

## 2. What is physical and what is simulated

Unchanged from Phase 13B, with one addition: the GPU now actually computes.

| Physical (measured) | Simulated (modelled) |
| --- | --- |
| Jetson Linux, CPU, **GPU**, RAM | CARLA RGB camera |
| Jetson process and thread scheduling | Environment and traffic |
| Jetson network stack | Ego vehicle and vehicle physics |
| CUDA 11.4.315 / TensorRT 8.5.2.2 execution | Safety MCU (portable C emulator) |
| Jetson thermal and resource telemetry | Actuator |
| USB cable + L4T USB Device Mode Ethernet | |

### Forbidden claims

Phase 13C never asserts: model accuracy, mAP, recall, real-world perception
quality, safe autonomous navigation, route completion, full HIL, a real MCU,
real CAN/UART timing, a physical camera, a physical actuator, INT8 or QAT
verification, a CARLA Leaderboard result, a formal route benchmark, an
infraction benchmark, or physical vehicle deployment.

INT8 calibration is **Phase 13D-INT8-CALIBRATION-RANGE-SHIFT**.

---

## 3. Target closed loop

```
CARLA RGB frame
  -> USB-gadget Ethernet (JILF 56-byte frame header, unchanged)
    -> real Jetson
      -> JPEG decode -> BGR8
        -> TensorRT preprocessing (letterbox 640x640, BGR->RGB, /255, NCHW)
          -> TensorRT FP16 inference on the real Orin NX GPU
            -> bounded numpy postprocessing (class-wise NMS)
              -> TensorRT input/output range contract
                -> existing SafetyGate
                  -> existing diagnostic control mapper
                    -> unchanged Phase 13A 64-byte command
                      -> C Virtual Safety MCU
                        -> JILA 48-byte ACK
                          -> virtual CARLA actuator
```

An `AI_ACTIVE` diagnostic command requires a **fresh, successful, no-fallback**
TensorRT result for the *same frame id*. Missing, invalid, stale, timed-out,
range-invalid or fallback results all produce `SAFE_STOP`.

The control proposal itself remains deterministic and diagnostic: the detector
gates authority, it does not steer.

---

## 4. Verified baseline

Phase 13B is already verified and is not modified by this phase: the JILF frame
header stays 56 bytes, the Phase 13A command stays 64 bytes with CRC over bytes
0..59, the JILA ACK stays 48 bytes, the mailbox depth stays exactly 1, and the C
Virtual Safety MCU remains the command authority.

Jetson (measured this phase): Seeed reComputer J4012 · Orin NX 16 GB ·
`aarch64` · Ubuntu 20.04.6 · JetPack 5.1.3 · L4T R35.5.0 · Python 3.8.10 ·
CUDA 11.4.315 (`libcudart.so.11.4.298`) · TensorRT **8.5.2.2** · OpenCV 4.5.4 ·
`trtexec` at `/usr/src/tensorrt/bin/trtexec` · nvpmodel 15 W mode 2, unchanged.

**PyCUDA and cuda-python are not installed** on the Jetson, and Phase 13C is
forbidden from installing them — hence the ctypes CUDA-runtime allocator below.

---

## 5. Model and asset contract

Formal target: `model_family=yolov9`, `model_variant=yolov9-c`,
`precision=fp16`, `batch_size=1`, `input_size=640x640`.

External assets, all uncommitted:

| Asset | Location | State |
| --- | --- | --- |
| YOLOv9 source | `D:\AIModels\yolov9` | present (git repo, `export.py`, `models/`, `utils/`) |
| Weights | `D:\AIModels\yolov9\yolov9-c-converted.pt` | present, 51 477 927 bytes |
| ONNX | `D:\AIModels\yolov9\exports\yolov9-c-640-b1.onnx` | **not produced** (export blocked) |
| Engine | `/home/myjetsonnx/models/ma-vlna/yolov9/…-trt852-fp16.engine` | **not built** |

`workers/core/tensorrt_asset_contract.py` records `model_family`,
`model_variant`, `external_source_root`, `external_source_git_sha`,
`weights_path`/`sha256`/`size`, `onnx_path`/`sha256`/`size`/`opset`,
`engine_path`/`sha256`/`size`, the full input and output contracts, the
postprocess profile, `class_count` and `class_names_source`.

### Engine cache key

A TensorRT plan is not portable, so the engine is bound to a SHA-256 over:

```
onnx_sha256 · tensorrt_version · cuda_version · gpu_name ·
compute_capability · precision · input_profile · postprocess_profile
```

If any axis differs, or the engine file hash does not match its manifest, or the
manifest does not say `built_on_target`, the engine is **stale** and must be
rebuilt on the Jetson. `evaluate_engine_staleness()` returns the exact reasons.

---

## 6. ONNX export gate

The external `export.py` was inspected rather than assumed. Its ONNX branch
calls `check_requirements('onnx')`, which **pip-installs** `onnx` when missing —
forbidden here. `scripts/run_phase13c_onnx_export.py` therefore drives
`torch.onnx.export` directly while reproducing that branch's contract:

* checkpoint loaded through the repository's existing trusted YOLOv9 loader
  (`_patch_torch_load_for_trusted_yolov9_checkpoint` + `attempt_load`);
* `input_names=['images']`, `output_names=['output0']`;
* `do_constant_folding=True`, fixed shape `1x3x640x640`, no dynamic axes;
* `dynamo=False` to select the legacy exporter;
* opset 12 (TensorRT 8.5 parses ≤ 17; 12 matches `export.py`'s default);
* no automatic model download, no training-only outputs.

Recorded statuses: `onnx_export_executed`, `onnx_export_passed`,
`onnx_checker_available`, `onnx_checker_passed`,
`onnx_input_contract_verified`, `onnx_output_contract_verified`.

Blockers: `onnx_export_dependency_missing`, `onnx_export_failed`,
`onnx_graph_invalid`, `onnx_contract_mismatch`, `unsupported_onnx_operator`.

**The output contract is derived from a real reference forward pass**, not
guessed: the export gate runs the loaded model once at 640×640, records the
actual output shape and class names, and infers whether the layout is
channels-first, anchors-first and whether it carries objectness.

---

## 7. Target-side engine build

`scripts/run_phase13c_engine_build.py` runs **on the Jetson only**.

Builder selection is made from the board, not assumed: `trtexec` is preferred
when present, otherwise the TensorRT 8.5 Python builder. The script reads
`trtexec --help` and picks `--workspace` (TensorRT 8) or `--memPoolSize`
(TensorRT 10) from the binary's own help text, so it never guesses flag names.

Profile: TensorRT 8.5.2.2, CUDA 11.4, batch 1, `1x3x640x640`, FP16 enabled, no
INT8, no DLA, bounded workspace (1 GiB default), no custom plugin.

After the build the engine is deserialized and its bindings verified before the
manifest is written, so `engine_deserialization_verified` and
`engine_binding_contract_verified` are real observations.

Blockers: `trtexec_unavailable`, `tensorrt_builder_unavailable`,
`engine_build_failed`, `engine_deserialize_failed`, `engine_binding_mismatch`,
`engine_stale`, `plugin_missing`, `fp16_unsupported`.

---

## 8. TensorRT runtime and the ctypes CUDA allocator

`workers/core/tensorrt_runtime.py` targets TensorRT **8** and refuses any other
major version. It uses the TensorRT 8 binding API only: `num_bindings`,
`binding_is_input`, `get_binding_shape`, `set_binding_shape`,
`execute_async_v2`. No TensorRT 10-only call appears anywhere.

Because PyCUDA and cuda-python are absent, the allocator is a narrow `ctypes`
wrapper over the installed `libcudart`:

```
cudaMalloc · cudaFree · cudaMemcpyAsync · cudaStreamCreate ·
cudaStreamDestroy · cudaStreamSynchronize · cudaEventCreate ·
cudaEventRecord · cudaEventSynchronize · cudaEventElapsedTime · cudaEventDestroy
```

Every call is status-checked and converted into a classified
`TensorRTRuntimeError`; `cuda_error_count` is reported.

Guarantees: one reusable stream per engine; input and output buffers allocated
**once** in `_allocate_once()`; nothing allocated on the device per frame;
deterministic `close()` with no leak; binding dtype/shape validated against the
declared contract; explicit synchronisation; batch size 1 only.

Recorded: `cuda_allocator_backend`, `device_allocation_count`,
`host_allocation_count`, `per_frame_device_allocation_count`,
`cuda_error_count`, `engine_execute_count`, `engine_execute_failure_count`,
`device_memory_bytes`, `host_buffer_bytes`.

Full Pass requires `per_frame_device_allocation_count = 0`,
`cuda_error_count = 0` and `engine_execute_failure_count = 0`.

---

## 9. Preprocess and postprocess contracts

Preprocess mirrors the official YOLOv9 letterbox the repository backend already
uses: ratio-preserving resize, symmetric padding with value 114, BGR→RGB,
`/255.0`, NCHW, contiguous, batch 1, then a binding-dtype conversion. Recorded
per sampled inference: `original_width/height`, `letterbox_width/height`,
`scale_ratio`, `pad_x`, `pad_y`, `input_min/max`, `channel_means`,
`channel_stds`, `input_dtype`, `binding_dtype`, `input_contiguous`.

Postprocess decodes the **recorded** output contract. The layout resolver
excludes any axis narrower than 5 elements from being the attribute axis (a
naive "larger axis is the anchor axis" rule misreads a single-anchor tensor such
as `(1, 84, 1)`), then lets the recorded contract decide, and only falls back to
the larger anchor count when nothing is recorded. Class-wise NMS runs in pure
numpy — no torch on the Jetson.

Defaults: `confidence_threshold=0.25`, `nms_iou_threshold=0.45`,
`max_detections=300`.

Every surviving detection is validated: class id in range, confidence finite and
within [0, 1], box coordinates finite, `x1 <= x2`, `y1 <= y2`, box clipped to
the source image, and detection count within the cap. The result is the existing
`PerceptionResult` schema with `backend=tensorrt`, `model_name=yolov9-c`,
`fallback_used=false`. **Any fallback in a formal gate fails that gate.**

---

## 10. Backend consistency (not accuracy)

`scripts/run_phase13c_backend_parity.py` compares the official YOLOv9 source
backend (reference, on the PC) with TensorRT FP16 (candidate, on the Jetson) on
identical local, uncommitted frames, using identical letterbox policy, colour
order, thresholds, class mapping and detection cap. Detections are matched
greedily by IoU.

Required: `reference_frame_count >= 32`, `parity_evaluable_frame_count > 0`,
`matched_detection_rate >= 0.90`, `matched_class_agreement >= 0.95`,
`matched_box_iou_mean >= 0.75`, `confidence_abs_error_p95 <= 0.10`,
`frames_with_schema_error == 0`, `frames_with_nonfinite_output == 0`.

These thresholds measure **conversion consistency only**. They establish no
ground truth, no mAP, no recall, no safety effectiveness and no navigation
quality. With no evaluable reference detections the gate reports
`reference_parity_not_evaluable` and full Pass is blocked.

---

## 11. Range-shift / fail-closed contract

```
input_range_checked             = true
tensor_output_range_checked     = true
detection_schema_checked        = true
activation_range_checked        = false
quantization_saturation_checked = false
int8_calibration_range_checked  = false
range_validation_scope          = tensorrt_fp16_input_and_final_output
```

A serialized TensorRT plan does not expose internal activations, so Phase 13C
checks the engine **input tensor** and the **final decoded output** — and says
so, rather than claiming internal monitoring it does not perform.

Fails closed on: NaN/Inf input, NaN/Inf output, shape mismatch, dtype mismatch,
colour-order mismatch, invalid class id, confidence outside [0, 1], invalid
bbox, excessive detection count, inference timeout, stale result, engine
execution failure, fallback use, and range drift beyond the contract.

On failure `AI_ACTIVE` is forbidden and `SAFE_STOP` is issued through the
unchanged `EmbeddedCommandBridge`. The Phase 13A recovery rule is preserved:
**three consecutive valid TensorRT results** are required before authority
resumes.

---

## 12. Performance measurement

All host timing uses `time.perf_counter_ns` (Phase 13B proved
`time.monotonic()` is 15.625 ms-granular on Windows); GPU time uses CUDA events.

Measured separately, each with min/p50/p95/p99/max/mean/sample_count:
`jpeg_decode_ms`, `preprocess_ms`, `h2d_ms`, `tensorrt_enqueue_ms`,
`gpu_execution_ms`, `d2h_ms`, `postprocess_ms`, `inference_total_ms`,
`frame_to_perception_ms`, `frame_to_command_ms`, `command_rtt_ms`.

Standalone benchmark: ≥ 50 warm-up and ≥ 300 measured iterations. **No FPS
threshold is asserted in advance** — the board's throughput is measured, not
predicted.

The closed loop instead enforces a deadline:

```
latency_budget_ms = command_validity_ms - clock_uncertainty_ms - safety_margin_ms
                  = 1000 - clock_uncertainty_ms - 50   (defaults)

require: frame_to_command_ms_p99 < latency_budget_ms
```

If it is missed, commands past validity are rejected, `SAFE_STOP` is applied and
the run is classified `inference_deadline_missed`. It is never inflated to Pass.

---

## 13. Phase 13B integration

The Phase 13B bridge is reused, not redesigned. The Jetson node gained one
selector:

```
--perception-backend dummy|tensorrt      (default: dummy)
--tensorrt-engine <external-engine-path>
--tensorrt-profile yolov9-c
--require-no-fallback
```

The default remains `dummy`, so Phase 13B behaviour is byte-for-byte unchanged.
With `--require-no-fallback`, a Jetson node whose TensorRT backend failed to
initialise **refuses to start** rather than quietly degrading.

Recorded: `tensorrt_frames_received`, `tensorrt_inference_requested_count`,
`tensorrt_inference_completed_count`, `tensorrt_inference_failed_count`,
`tensorrt_fallback_count`, `tensorrt_safe_stop_count`,
`tensorrt_active_authority_count`, `tensorrt_result_stale_count`,
`tensorrt_range_reject_count`. Formal gates require
`tensorrt_fallback_count = 0`.

---

## 14. CARLA formal profile

```
fixed_delta_seconds = 0.05  -> simulator 20 Hz
camera_fps          = 5     -> sensor_tick 0.20 s
=> one camera frame every FOUR simulation ticks
frames >= 300               -> >= 1200 CARLA ticks
```

Town03 and the Phase 13B lifecycle rules are reused. The 10 FPS capacity profile
is optional and is **not** a prerequisite for the primary Pass. No route
completion is required.

---

## 15. Fault matrix

The Phase 13B 28-case matrix is preserved and re-run. Phase 13C adds 22
TensorRT-specific deterministic cases (`scripts/tests/test_phase13c_faults.py`),
all of which pass at Gate A:

| ID | Fault | Expected |
| --- | --- | --- |
| T01 | missing engine | backend unavailable |
| T02 | engine hash mismatch | backend unavailable |
| T03 | engine manifest mismatch | backend unavailable |
| T04 | engine deserialize failure | backend unavailable |
| T05 | binding count mismatch | backend unavailable |
| T06 | input shape mismatch | SAFE_STOP |
| T07 | input dtype mismatch | SAFE_STOP |
| T08 | NaN input tensor | SAFE_STOP |
| T09 | Inf input tensor | SAFE_STOP |
| T10 | output NaN | SAFE_STOP |
| T11 | output Inf | SAFE_STOP |
| T12 | output shape mismatch | SAFE_STOP |
| T13 | confidence out of range | SAFE_STOP |
| T14 | invalid class id | SAFE_STOP |
| T15 | bbox out of bounds | SAFE_STOP |
| T16 | excessive detection count | SAFE_STOP |
| T17 | inference timeout | SAFE_STOP |
| T18 | stale inference result | SAFE_STOP |
| T19 | CUDA execution error (test double) | SAFE_STOP |
| T20 | fallback attempted | gate failure |
| T21 | parity threshold failure | gate failure |
| T22 | command validity exceeded by latency | SAFE_STOP |

The invariant asserted by every row: **no invalid TensorRT result may ever
produce `AI_ACTIVE`.** Required: `false_accept_count = 0`,
`false_reject_count = 0`.

---

## 16. Four gates

| Gate | Requires | Status word |
| --- | --- | --- |
| **A** | asset contract, manifest schema, runtime tests with fakes, CUDA wrapper with test doubles, preprocess, letterbox reverse-mapping, output schema, range/fail-closed, TensorRT fault matrix, Phase 13B regression, Python 3.8 parsing | `Prepared` |
| **B** | exact SHA match, real `aarch64` Jetson, external ONNX + hash, TensorRT parser, FP16 engine built on target, manifest, deserialize, binding contract, 50 warm-ups, 300 measured inferences, no fallback, no CUDA error, no per-frame allocation, telemetry, no throttling | `Engine Pass` |
| **C** | ≥ 300 frames through the real Phase 13B TCP path, Jetson JPEG decode, real FP16 inference, valid `PerceptionResult`, output/range checks, unchanged 64-byte command, C MCU, valid ACK, mailbox depth 1, parity passed, zero false accept/reject, no fallback | `Runtime Pass` |
| **D** | real CARLA + real Jetson + real FP16 inference in the command authority path, ≥ 300 camera frames, ≥ 300 valid inferences, ≥ 1 active diagnostic control, ≥ 1 SAFE_STOP path, p99 within budget, Phase 13B regressions still passing, no fallback, no throttling | `Pass` |

`Prepared`, `Engine Pass` and `Runtime Pass` are never inflated into full
`Pass`.

---

## 17. Evidence

PC: `experiments\phase13\<run-id>-phase13c\` · Jetson:
`experiments/phase13/<same-run-id>-phase13c/`, containing `manifest.json`,
`summary.json`, `environment.json`, `model_manifest.json`,
`engine_manifest.json`, `latency_metrics.json`, `range_metrics.json`,
`parity_metrics.json`, `phase13c_fault_matrix.json` / `.csv`,
`jetson_metrics.json`, `network_metrics.json`, `events.jsonl`, `commands.txt`,
`README.md`, `raw_outputs/`.

Recorded: `runtime_pc_git_sha`, `runtime_jetson_git_sha`,
`runtime_git_sha_match`, `final_source_head_sha`,
`runtime_code_changed_after_runtime`.

**Never committed:** `.pt`, `.pth`, `.onnx`, `.engine`, calibration caches,
captured model input images, output tensors, TensorRT timing caches, compiled
CUDA artifacts, raw runtime logs, raw tegrastats logs, or the external source
repository.

---

## 18. Operation

Gate A (PC, nothing external required):

```bash
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase13c_checks.py
```

ONNX export (PC) — currently blocked until `onnx` is installed by the operator:

```bash
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase13c_onnx_export.py --source-root D:\AIModels\yolov9 --weights D:\AIModels\yolov9\yolov9-c-converted.pt --output D:\AIModels\yolov9\exports\yolov9-c-640-b1.onnx --img-size 640 --batch-size 1 --require-export
```

Transfer only the external ONNX and its manifest:

```bash
ssh myjetsonnx@192.168.55.1 "mkdir -p /home/myjetsonnx/models/ma-vlna/yolov9"
```

Gate B (Jetson) — engine build then standalone benchmark:

```bash
ssh myjetsonnx@192.168.55.1 "cd /home/myjetsonnx/Face_Detect_Realtime && source /home/myjetsonnx/venvs/ma-vlna/bin/activate && python scripts/run_phase13c_engine_build.py --onnx /home/myjetsonnx/models/ma-vlna/yolov9/yolov9-c-640-b1.onnx --engine /home/myjetsonnx/models/ma-vlna/yolov9/yolov9-c-640-b1-trt852-fp16.engine --precision fp16 --input-shape 1x3x640x640 --require-real-jetson --require-engine"
```

Gate C (PC drives the Jetson node started with `--perception-backend tensorrt`):

```bash
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase13c_streamed_runtime.py --jetson-host 192.168.55.1 --frames 300 --require-real-jetson --require-no-fallback
```

Gate D (PC, full closed loop):

```bash
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase13c_orchestrator.py --jetson-host 192.168.55.1 --engine /home/myjetsonnx/models/ma-vlna/yolov9/yolov9-c-640-b1-trt852-fp16.engine --profile yolov9-c --camera-fps 5 --frames 300 --command-validity-ms 1000 --safety-margin-ms 50 --require-real-jetson --require-carla --require-no-fallback --output-dir experiments\phase13
```

No password is stored. Only run-specific Jetson and CARLA processes started by
the run are stopped, by recorded PID; `pkill` is never used.

---

## 19. Full Pass conditions

Beyond the Phase 13B conditions, Phase 13C additionally requires:

```
external_model_source_ready = true      external_weights_ready = true
weights_sha256_recorded = true          onnx_export_passed = true
onnx_contract_verified = true           onnx_sha256_recorded = true
fp16_engine_built_on_target = true      fp16_engine_verified = true
engine_deserialization_verified = true  engine_binding_contract_verified = true
engine_sha256_recorded = true           tensorrt_version = 8.5.2.2
tensorrt_backend_no_fallback = true     tensorrt_fallback_count = 0
standalone_warmup_count >= 50           standalone_measured_inference_count >= 300
engine_execute_failure_count = 0        cuda_error_count = 0
per_frame_device_allocation_count = 0
reference_frame_count >= 32             parity_evaluable_frame_count > 0
matched_detection_rate >= 0.90          matched_class_agreement >= 0.95
matched_box_iou_mean >= 0.75            confidence_abs_error_p95 <= 0.10
gate_c_streamed_inference_count >= 300  gate_c_max_mailbox_depth == 1
gate_d_carla_frames_sent >= 300         gate_d_tensorrt_inference_completed_count >= 300
gate_d_active_control_count > 0         gate_d_safe_stop_count > 0
gate_d_command_timeout_count == 0       frame_to_command_ms_p99 < latency_budget_ms
phase13c_fault_matrix_passed = true     phase13b_fault_matrix_regression_passed = true
false_accept_count == 0                 false_reject_count == 0
thermal_throttling_observed = false
int8_engine_built = false               int8_calibration_verified = false
qat_verified = false                    model_accuracy_verified = false
```

`goal_reached`, `route_completion`, an mAP threshold and the 10 FPS capacity
profile are **not** required.

---

## 20. Recommended next phase

`Phase 13D-INT8-CALIBRATION-RANGE-SHIFT` — after a real FP16 Pass. Until the
`onnx` dependency is unlocked, the immediate next step is the operator command
in §1.
