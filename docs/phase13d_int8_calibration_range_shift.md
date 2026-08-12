# Phase 13D — INT8 Calibration and Range Shift

Phase 13D calibrates and builds a **TensorRT INT8** engine on the real Jetson
Orin NX from a controlled CARLA Town03 corpus, gates it with a calibration
envelope, and compares it against the verified Phase 13C FP16 engine — while
preserving the Phase 13A/13B/13C transport, command and safety path unchanged.

`validation_type = processor_in_the_loop` · `precision = int8`

---

## 1. Status of this phase

**`Phase 13D-INT8-CALIBRATION-RANGE-SHIFT Engine Pass`** — a target-built INT8
TensorRT engine was calibrated and verified on the real Jetson with INT8 layers
observed and a bounded FP16-vs-INT8 benchmark, but the **INT8-vs-FP16 parity
gate did not pass**, so Gate D (streamed INT8 runtime) and Gate E (CARLA closed
loop) are Blocked.

| Gate | Requirement | Result |
| --- | --- | --- |
| **A** Prepared | local dataset/calibrator/cache/range/audit/parity/fault tests | **Passed** |
| **B** Dataset Pass | coverage, manifests, disjointness, range profile, activation proxy | **Passed** |
| **C** Engine Pass | exact SHA match, target cache + INT8 engine, INT8 layers observed, benchmark | **Passed** |
| **D** Runtime Pass | ≥300 streamed frames + valid INT8 inferences, mailbox depth 1, **parity**, regressions, 0 false accept/reject | **Blocked — parity only** |
| **E** Pass | CARLA Town03 closed loop | **Blocked — parity only** |

Gates D and E were executed in full against the real Jetson and real CARLA, and
each one blocks on **exactly one** criterion: the INT8-vs-FP16 parity gate.
Every other criterion of both gates was measured and passed — they are reported
in §10 and §11 so the runtime evidence is not lost, but neither gate is claimed
as a pass.

The blocking measurement is stated plainly in §9: the INT8 conversion preserves
box geometry almost exactly but collapses classification confidence by roughly
25–30×, which fails the mandated `matched_detection_rate ≥ 0.90` and
`confidence_abs_error_p95 ≤ 0.12` bounds. That is the parity gate doing its job.
No lower gate is inflated to cover it.

Executed 2026-08-12. The runtime gates ran at
`runtime_pc_git_sha = runtime_jetson_git_sha = 311ddc3e57bea2dbfa66cdc7bbd280cadb30e5ba`;
the INT8 engine and its calibration cache were produced by a full recalibration
on the target at `32df3adb`, from which only gate-side evidence parsing changed.

---

## 2. What is physical and what is simulated

Unchanged from Phase 13C, with INT8 execution added to the physical column:

| Physical (measured) | Simulated (modelled) |
| --- | --- |
| Jetson Linux, CPU, GPU, RAM | CARLA RGB camera |
| Jetson process and thread scheduling | Environment, traffic and weather |
| Jetson network stack | Ego vehicle and vehicle physics |
| CUDA 11.4.315 / TensorRT 8.5.2.2 **INT8** engine execution on the GPU | Safety MCU (portable C emulator) |
| INT8 calibration executed on the target GPU | Actuator |
| Jetson thermal and resource telemetry | |
| USB cable + L4T USB Device Mode Ethernet | |

### Forbidden claims

Phase 13D never asserts: model accuracy, mAP, recall, real-world perception
quality, real-world representativeness of the calibration corpus, safe
autonomous navigation, route completion, full HIL, a real MCU, real CAN/UART
timing, a physical camera, a physical actuator, QAT, a CARLA Leaderboard
result, a formal route or infraction benchmark, or physical vehicle deployment.

Two INT8-specific boundaries are enforced in code, not just in prose:

* **`all_layers_int8` is only ever true when every single layer reported INT8.**
  It is false in this phase and the measured per-layer precision counts are
  recorded instead.
* **TensorRT's internal activations are never observed.** A serialized plan does
  not expose them. The activation evidence in §7 is an *offline proxy* measured
  on the source model, and every artefact carries
  `runtime_tensorrt_internal_activations_observed = false`.

`power_measurement_available = false` — the reComputer J4012 exposes no `VDD_*`
rail, and power is never inferred from utilisation.

---

## 3. Target closed loop

```
CARLA RGB frame
  -> USB-gadget Ethernet (JILF 56-byte frame header, unchanged)
    -> real Jetson
      -> JPEG decode -> BGR8
        -> preprocessing (letterbox 640x640, BGR->RGB, /255, NCHW)
          -> TensorRT INT8 inference on the real Orin NX GPU
            -> bounded numpy postprocessing (class-wise NMS)
              -> INT8 calibration-envelope + output range contract
                -> existing SafetyGate
                  -> existing diagnostic control mapper
                    -> unchanged Phase 13A 64-byte command
                      -> C Virtual Safety MCU
                        -> JILA 48-byte ACK
                          -> virtual CARLA actuator
```

An `AI_ACTIVE` diagnostic command requires a **fresh, successful, no-fallback,
range-valid** INT8 result for the *same frame id*. Missing, invalid, stale,
timed-out, range-shifted, envelope-violating or fallback results all produce
`SAFE_STOP`. The Phase 13A recovery rule is preserved: after any rejection,
three consecutive valid results are required before AI authority may resume.

---

## 4. Verified baseline

Phase 13A/13B/13C are not modified by this phase. The JILF frame header stays
56 bytes, the Phase 13A command stays 64 bytes with CRC over bytes 0..59, the
JILA ACK stays 48 bytes, the mailbox depth stays exactly 1, and the C Virtual
Safety MCU remains the only command authority.

Two backward-compatible additions were made:

* `TensorRTPerceptionBackend` takes a `precision` label, defaulting to `fp16`.
* The Jetson node takes `--tensorrt-precision`, `--int8-calibration-envelope`
  and `--int8-activation-proxy`. All are inert unless supplied, so the Phase 13B
  and 13C invocations behave exactly as before. Supplying an envelope path that
  cannot be loaded makes the node refuse to start: an INT8 engine whose
  calibration envelope is unknown cannot be gated at all.

Jetson (measured this phase): Seeed reComputer J4012 · Orin NX 16 GB ·
`aarch64` · Ubuntu 20.04.6 · JetPack 5.1.3 · L4T R35.5.0 · Python 3.8.10 ·
CUDA 11.4.315 · TensorRT 8.5.2.2 · nvpmodel 15 W mode 2, unchanged. PyCUDA and
cuda-python are still absent and still not installed, so calibration drives CUDA
through the Phase 13C ctypes `libcudart` path.

---

## 5. Gate A — local source, unit and fail-closed checks

Executed on the simulation PC; no dataset, engine, Jetson or CARLA involved, so
Gate A alone permits only `Prepared`.

| Check | Result |
| --- | --- |
| Phase 13D unit tests | 141 / 141 |
| Phase 13D fault matrix (D01..D35) | 35 / 35, false accept 0, false reject 0 |
| Phase 13C regression | 107 / 107 |
| Phase 13B regression | 83 / 83 |
| Phase 13A regression | 2 / 2 |
| Python 3.8 parse guard (13 Jetson modules) | passed |
| `run_demo_checks.py` | 6 / 6 |
| `run_phase11_core_runtime_checks.py` | passed |
| `run_phase11o_source_commit_checks.py` | passed |
| CMake configure/build + CTest (MinGW, TDM-GCC 64) | 2 / 2 |
| `compileall` over `workers`, `scripts`, `simulation` | passed |
| `git diff --check` | clean |

The same MSVC configuration fails to build the embedded C suite on this host
with `C4819` (source files contain characters not representable in code page
950, and `/WX` promotes it). That is pre-existing and unrelated to Phase 13D —
no file under `embedded/` was touched. The MinGW toolchain the repository has
used since Phase 13A builds and passes.

### Fault matrix families

`D01..D35` cover every family the phase is required to inject, all with test
doubles and no hardware:

| Family | Cases |
| --- | --- |
| dataset coverage / split | D01 D02 D03 D04 |
| dataset disjointness / integrity | D05 D06 D07 |
| calibration envelope | D08 D09 |
| calibration cache | D10 D11 D12 D13 |
| calibration feed | D14 D15 D16 D18 |
| calibration memory | D17 D19 |
| engine build / cache / audit | D20 D21 D22 D23 D24 D25 |
| runtime range | D26 D27 D31 |
| runtime deadline | D28 D29 D33 |
| runtime fallback | D30 |
| runtime throttling | D32 |
| parity | D34 D35 |

Every case asserts the same invariant: **no invalid INT8 result ever produced
`AI_ACTIVE`**.

---

## 6. Gate B — controlled CARLA Town03 calibration corpus

The corpus is **controlled CARLA simulation data**. It lives outside this
repository, is never committed, and is never described as real-world
representative. Every artefact carries
`data_source = controlled_carla_simulation` and
`real_world_representative = false`.

### Capture profile (measured)

| Field | Value |
| --- | --- |
| Map | `Carla/Maps/Town03`, reused (not re-loaded) |
| Routes | 5, spawn point indices 0 / 53 / 106 / 159 / 212 |
| Weather profiles | `ClearNoon`, `WetCloudyNoon`, `HardRainNoon`, `ClearSunset` |
| Frames per route × weather cell | 40 |
| Total frames | **800** over **3445** CARLA ticks, 0 camera frames dropped |
| Capture duration | 71.5 s |
| `fixed_delta_seconds` | 0.05 (20 Hz simulator) |
| `camera_fps` | 5 → `sensor_tick` 0.20 s → one frame every 4 ticks |
| Camera | 640 × 360, FOV 90, `vehicle.tesla.model3`, traffic-manager autopilot |
| Pixel format / container | BGR8 / PNG (lossless) |

The camera profile is deliberately identical to the Phase 13C/13D runtime
profile, so the calibration tensors have the same letterbox geometry — and the
same 44 % pad region — that the engine sees at runtime.

### Split, identity and disjointness (measured)

| Field | Value |
| --- | --- |
| Split rule | every 5th frame *within each route × weather cell* becomes holdout |
| Calibration frames | **640** (bound ≥ 512) |
| Holdout frames | **160** (bound ≥ 128) |
| `dataset_sha256` | `4f136b99558a0d3860a0ad19982a2fb944014ff063cd1a682556683a68d1e3ca` |
| Duplicate SHA-256 count | **0** |
| Split overlap (frame id / SHA-256) | **0 / 0** |
| Unassigned frames | 0 |
| Files re-verified by SHA-256 on the PC | 800 / 800 |
| Files re-verified by SHA-256 on the Jetson after transfer | 800 / 800 |

A per-cell stride was chosen over a random split because a random split can
starve a whole weather profile; a per-cell stride cannot, and it makes overlap
structurally impossible.

### Calibration envelopes (measured)

Derived from the **calibration split only**, as the observed min/max of each
source-frame statistic expanded by a 2 % margin of the observed range.
Statistics are source-frame BGR8 in the normalized `/255` domain — never the
letterboxed tensor, whose pad grey would drag every channel mean toward 0.447
and make the numbers useless as a range-shift signal.

| Statistic | Envelope |
| --- | --- |
| Channel 0 (B) mean | [0.4224, 0.6614] |
| Channel 1 (G) mean | [0.4106, 0.6562] |
| Channel 2 (R) mean | [0.4148, 0.6623] |
| Channel 0 std | [0.0426, 0.2293] |
| Channel 1 std | [0.0456, 0.2172] |
| Channel 2 std | [0.0451, 0.2201] |
| Pixel min | [-0.0064, 0.3240] |
| Pixel max | [0.7480, 1.0049] |
| Pixel mean | [0.4159, 0.6597] |

**Holdout false-reject rate: 0.000 (0 / 160), bound ≤ 0.01.** Every holdout
frame came from the same controlled capture, so any holdout rejection would be a
*false* reject; the measured rate is the honest cost of the envelope.

---

## 7. Offline activation proxy

TensorRT does not expose the tensors flowing between the layers of a serialized
plan, so this phase does not claim to watch them. Instead the **source** YOLOv9
model was run on the CPU over a deterministic even-stride subsample of the
calibration split, with forward hooks on real convolution layers.

| Field | Value |
| --- | --- |
| Backend | `pytorch_forward_hooks_offline` |
| Layers observed | **12** (bound ≥ 8), evenly spread `nn.Conv2d` modules |
| Frames observed | 48, even-stride subsample of the 640 calibration frames |
| Preprocessing | the runtime `preprocess_bgr`, so the proxy sees the engine's tensors |
| `runtime_tensorrt_internal_activations_observed` | **false** |
| `internal_tensor_monitoring_claimed` | **false** |
| `qat_verified` | **false** |

Representative measurements (`absmax`, the 99.9th percentile of |x|, their
ratio, and the INT8 step at the p99.9 scale relative to the layer's own spread):

| Layer | absmax | abs p99.9 | absmax / p99.9 | relative INT8 step |
| --- | --- | --- | --- | --- |
| `model.0.conv` | 67.956 | 12.750 | 5.33 | 0.0410 |
| `model.2.cv3.0.m.0.cv1.conv` | 7.692 | 3.750 | 2.05 | 0.0340 |
| `model.4.cv2.1.conv` | 8.203 | 4.250 | 1.93 | 0.0344 |
| `model.6.cv2.0.cv2.conv` | 10.525 | 4.000 | 2.63 | 0.0331 |

The first convolution's `absmax / p99.9` of 5.33 says most of its dynamic range
is driven by rare outliers — naive absmax scaling would waste 80 % of the INT8
code space there. This is a proxy signal about where quantization is tight; it is
not a measurement of TensorRT's own activations.

---

## 8. Gate C — target INT8 calibration, engine build and benchmark

### Calibration (measured on the Jetson)

| Field | Value |
| --- | --- |
| Algorithm | `IInt8EntropyCalibrator2` |
| Batch size | 1 |
| Preprocessing | `workers.core.tensorrt_perception.preprocess_bgr` (the runtime function) |
| Calibration frames read / batches served | 640 / 640 |
| **Skipped frames** | **0** |
| **Device allocations** | **1** (one reusable buffer) |
| **Per-batch device allocations** | **0** |
| Batch uploads | 640 |
| Calibration tensor range | [0.000, 1.000] |
| CUDA errors | **0** |
| Cache written | 26 420 bytes, `built_on_target = true` |

The cache is bound to a hashed key over the ONNX SHA-256, the dataset SHA-256,
the frame count, the algorithm, the batch size, the input profile, the
preprocess profile, and the target TensorRT/CUDA/GPU identity. Any difference
makes it stale and forces recalibration; the key and a content hash are written
to a sidecar so staleness is decidable offline.

### Engine build (measured on the Jetson)

| Field | Value |
| --- | --- |
| Builder | TensorRT 8.5 Python builder (`trtexec` cannot host a custom calibrator) |
| Flags | `INT8` + `FP16`, `ProfilingVerbosity.DETAILED` |
| DLA | **not enabled** (`default_device_type` left at GPU, no DLA core selected) |
| Parsed network layers | 1245 |
| Build duration | 3284.1 s on the target |
| Engine size | 27 491 481 bytes (FP16: 52 779 823 — 52.1 %) |
| Engine SHA-256 | `9152064741d89731…` |
| Deserialize / bindings / output contract | verified |
| Input binding | `images` `[1, 3, 640, 640]` FLOAT |
| Output binding | `output0` `[1, 84, 8400]` FLOAT |

### Layer precision audit (measured from the plan, not the build log)

Read back through `EngineInspector` at `DETAILED` verbosity:

| Field | Value |
| --- | --- |
| Engine layers | 239 |
| **INT8 layers** | **202** |
| FP16 layers | 26 |
| FP32 layers | 11 |
| Unknown-precision layers | **0** |
| Precision fallback layers | 37 |
| INT8 layer ratio | 0.845 |
| **`all_layers_int8`** | **false** |

`int8_layer_count > 0` is therefore measured, not asserted, and the phase never
claims the whole network runs in INT8.

### Benchmark — FP16 and INT8, same board, same run, same frames

Both plans were benchmarked back to back in one process over the same holdout
frames, so the comparison is not across two thermal states. 50 warm-up
iterations discarded, 300 measured per precision.

| Metric | FP16 | INT8 | Ratio |
| --- | --- | --- | --- |
| `frame_to_perception_ms` p50 | 85.55 | **70.29** | **1.217×** |
| p95 | 86.61 | 70.71 | 1.225× |
| p99 | 87.50 | 71.04 | 1.232× |
| Throughput (measured) | 11.67 fps | **14.22 fps** | — |
| GPU execution p50 | — | — | **1.424×** |

Per-frame device allocations 0, CUDA errors 0, execute failures 0, perception
fallback 0, thermal throttling not observed (`tj` 54.8 °C peak, GR3D peaked at
99 %, mean 65.1 % under sustained load). The speedup is a measured latency
ratio and carries no claim whatsoever about detection quality.

---

## 9. Why the parity gate did not pass

This is the blocking result of the phase, and it is reported as measured.

### Parity metrics (160 holdout frames, INT8 candidate vs verified FP16 reference)

| Metric | Bound | Measured | Verdict |
| --- | --- | --- | --- |
| `matched_detection_rate` | ≥ 0.90 | **0.0949** | **fail** |
| `matched_class_agreement` | ≥ 0.98 | 1.000 | pass |
| `matched_box_iou_mean` | ≥ 0.75 | 0.891 | pass |
| `confidence_abs_error_p95` | ≤ 0.12 | **0.4985** | **fail** |
| schema errors | 0 | 0 | pass |
| non-finite outputs | 0 | 0 | pass |
| **unsafe authority divergence** | 0 | **0** | pass |

Shared frames 160, evaluable frames 84, FP16 detections 390, INT8 detections 37.
Every INT8 detection that survived matched an FP16 detection, with perfect class
agreement — so the boxes are not the problem.

### Located, not guessed

Raw output tensors were compared for the same frames through both engines:

| Frame | FP16 peak class score | INT8 peak class score | FP16 box p99 | INT8 box p99 |
| --- | --- | --- | --- | --- |
| `route_00_ClearNoon_00004` | 0.3433 | 0.0163 | 374.5 | 375.5 |
| `route_00_ClearNoon_00009` | 0.7090 | 0.0190 | 375.0 | 376.0 |
| `route_00_ClearNoon_00014` | 0.5293 | 0.0471 | 375.0 | 374.5 |
| `route_00_ClearNoon_00019` | 0.3923 | 0.0137 | 374.0 | 374.8 |

The **box branch is intact** — the decoded box p99 agrees to within 0.3 % — while
the **class scores collapse by roughly 25–30×**, with their ranking preserved. In
logit terms the class head is clipped about 4.8 lower: `sigmoid(+0.89) = 0.709`
becomes `sigmoid(-3.95) = 0.019`. Lowering the confidence threshold from 0.25 to
0.05 recovered nothing (matched rate 0.053), which rules out a threshold effect.

That signature is entropy calibration selecting an activation range from a
distribution in which essentially every class logit belongs to background:
the rare positive logits that constitute a detection get clipped away.

### What was tried

1. **Detect head constrained to FP16, `PREFER_PRECISION_CONSTRAINTS`.** TensorRT
   logged nine `no implementation obeys the requested constraints` fallbacks and
   parity was unchanged to the digit (0.0949 / 0.503).
2. **Detect head constrained to FP16, `OBEY_PRECISION_CONSTRAINTS`.** The
   constraint was honoured: all 46 `/model.22/*` layers in the plan came back
   **FP16 (44) / FP32 (2), zero INT8**, and the INT8 layer count fell from 202 to
   188. Peak INT8 class score moved only from 0.0163 to 0.0196.

Since removing the entire detect head from INT8 changes almost nothing, the
degradation is **upstream, in the backbone and neck** — the features arriving at
the head are already damaged. Recovering parity from here would mean removing so
much of the network from INT8 that the result would no longer be an INT8 engine,
or using QAT, which this phase is forbidden from claiming.

The engine kept as the phase artefact is therefore the honest one: the fully
recalibrated, **unconstrained** INT8 build, which has the highest measured INT8
coverage and identical parity behaviour to the constrained variants.

### What this means for safety

The parity gate is a conversion-consistency gate, not an accuracy evaluation. It
established no ground truth, no mAP and no recall. What it did do is catch, before
any closed-loop run was allowed to claim a pass, an INT8 conversion that would
have silently degraded perception — and `unsafe_authority_divergence_count = 0`
confirms the INT8 engine never granted authority on a frame where the verified
FP16 engine could not.

---

## 10. Gate D — streamed INT8 runtime (executed, blocked on parity only)

310 frames streamed over the verified Phase 13B transport to the real Jetson
running the INT8 plan under the enforced calibration envelope, followed by the
Phase 13B fault matrix in the same session.

| Criterion | Bound | Measured | Verdict |
| --- | --- | --- | --- |
| perception mode | `tensorrt` | `tensorrt` | pass |
| **precision** | `int8` | **`int8`** | pass |
| calibration envelope loaded / enforced | both true | **true / true** | pass |
| `int8_calibration_range_checked` | true | **true** | pass |
| streamed INT8 inferences | ≥ 300 | **310** | pass |
| valid (authority-granting) INT8 inferences | ≥ 300 | **308** | pass |
| streamed inference failures | 0 | **0** | pass |
| streamed range rejects / envelope rejects | 0 | **0 / 0** | pass |
| perception fallback | 0 | **0** | pass |
| **max mailbox depth** | exactly 1 | **1** | pass |
| mailbox drops | 0 | **0** | pass |
| Phase 13B fault matrix | pass | **28 / 28** | pass |
| false accept / false reject | 0 / 0 | **0 / 0** | pass |
| Phase 13A/13B/13C regressions | pass | **pass** | pass |
| p99 frame-to-command | < 949.59 ms | **90.62 ms** | pass |
| **INT8-vs-FP16 parity** | pass | **fail** | **blocked** |

Commands accepted 321, rejected 7 (the fault matrix's injected rejections),
valid ACKs 324, engine warm-up 20 iterations.

310 frames rather than 300 because the Phase 13A recovery rule requires three
consecutive valid results before AI authority may resume, so the first two
frames of any session are `RECOVERY_PENDING` by design. Streaming exactly 300
can therefore never yield 300 authority-granting results. The frame count was
raised to satisfy the requirement as written; the rule itself was not weakened.

The streamed phase is measured from a snapshot taken **before** the fault matrix
runs. The fault matrix deliberately feeds invalid frames, so its one injected
`input_dtype_mismatch` failure at frame 311 and its three injected range
rejections belong to the fault verdict — which passed 28/28 with zero false
accepts and zero false rejects — and not to the streamed-inference counts.

---

## 11. Gate E — CARLA Town03 closed loop (executed, blocked on parity only)

Real CARLA Town03, real Jetson INT8 perception, real C Virtual Safety MCU, real
virtual actuation.

| Criterion | Bound | Measured | Verdict |
| --- | --- | --- | --- |
| Town / simulator rate | Town03, 20 Hz | **Town03, 20 Hz** | pass |
| camera rate | 5 FPS (4 ticks/frame) | **5 FPS** | pass |
| CARLA ticks | ≥ 1200 | **1200** | pass |
| CARLA frames sent / processed | ≥ 300 | **300 / 305** | pass |
| INT8 inferences completed | ≥ 300 | **304** | pass |
| **active control applied** | > 0 | **1197** | pass |
| **SAFE_STOP applied** | > 0 | **18** | pass |
| command timeouts | 0 | **0** | pass |
| perception fallback | 0 | **0** | pass |
| thermal throttling | not observed | **not observed** | pass |
| max mailbox depth | exactly 1 | **1** | pass |
| precision / envelope enforced | `int8` / true | **`int8` / true** | pass |
| envelope rejects | — | 0 | — |
| fault matrix | pass | **28 / 28** | pass |
| false accept / false reject | 0 / 0 | **0 / 0** | pass |
| p99 frame-to-command | < 949.67 ms | **92.74 ms** | pass |
| **INT8-vs-FP16 parity** | pass | **fail** | **blocked** |

Clock uncertainty 0.329 ms. Commands accepted 311.

An earlier Gate E run recorded 27 of 28 fault cases, with `F28 stale frame`
observed as `STALE_REJECT` where `SAFE_STOP` was expected — the command was
refused by the C Safety MCU instead of being suppressed at the Jetson, so it
was still never applied, and false accepts stayed at 0. The following run
recorded 28/28, so the case is timing-sensitive under the faster INT8 profile
rather than systematically broken. It is recorded here because a flaky safety
fault case is worth knowing about, and Phase 13E is where soak and fault
injection belong.

---

## 12. Known gaps

* **Gate D and Gate E were not earned.** Both were executed in full and both
  block on the parity gate alone, as tabulated in §10 and §11. No Runtime Pass
  and no Pass status is claimed.
* **One Phase 13B fault case is timing-sensitive under INT8.** `F28 stale frame`
  was observed once as `STALE_REJECT` rather than `SAFE_STOP` and once correctly;
  in both readings the command was refused and false accepts stayed at 0.
* **Entropy calibration only.** `IInt8EntropyCalibrator2` is the mandated
  algorithm for this phase, so no alternative calibrator was measured. Whether a
  min/max calibrator would preserve the class head is unmeasured and unclaimed.
* **The corpus is temporally dense.** Each route × weather cell is 40 frames at
  5 FPS, i.e. an 8-second window, so consecutive calibration frames are highly
  correlated. Whether a longer, sparser capture changes the calibrated ranges is
  unmeasured.
* **The 44 % letterbox pad region is part of every calibration tensor**, because
  it is part of every runtime tensor. Its effect on the entropy histograms is
  unmeasured.
* Inherited from Phase 13C: when a `trtexec` attempt fails and a Python-builder
  attempt then succeeds, the Phase 13C FP16 build script overwrote the first
  attempt's report. Phase 13D's build script appends every attempt to a list
  instead, so this gap does not apply to the INT8 path.

---

## 13. Evidence layout

All Phase 13D evidence is written under `experiments/phase13/<run-id>-phase13d/`
and is **gitignored** — generated evidence is never committed, and neither are
datasets, frames, ONNX graphs, engines, calibration caches, tensors, binaries,
logs or environments.

```
manifest.json                  summary.json                environment.json
dataset_manifest.json          calibration_cache_manifest.json
engine_manifest.json           engine_audit.json           activation_proxy.json
latency_metrics.json           precision_benchmark.json    range_metrics.json
parity_metrics.json            jetson_metrics.json         network_metrics.json
phase13d_fault_matrix.json     phase13d_fault_matrix.csv
events.jsonl                   commands.txt                README.md
raw_outputs/
```

External, uncommitted assets:

| Asset | Location |
| --- | --- |
| YOLOv9 source tree | `D:\AIModels\yolov9` (git `5b1ea9a8`) |
| Weights | `yolov9-c-converted.pt` |
| ONNX | `D:\AIModels\yolov9\exports\yolov9-c-640-b1.onnx` |
| Calibration corpus | `D:\AIModels\yolov9\int8_calibration` → `/home/myjetsonnx/models/ma-vlna/int8_calibration` |
| FP16 engine | `/home/myjetsonnx/models/ma-vlna/yolov9/yolov9-c-640-b1-trt852-fp16.engine` |
| INT8 engine + calibration cache | `/home/myjetsonnx/models/ma-vlna/yolov9/yolov9-c-640-b1-trt852-int8.*` |

---

## 14. Next phase

`Phase 13E-SOAK-THERMAL-BACKPRESSURE-FAULT-INJECTION`.
