# Phase 13D-MP-RECOVERY — PTQ Mixed-Precision Backbone/Neck Sensitivity Recovery

Phase 13D reached `Engine Pass` with a working, faster INT8 engine that failed
the INT8-vs-FP16 parity gate: box geometry survived quantization almost exactly
while class scores collapsed 25–30×. Forcing the whole detect head to FP16
recovered nothing, which placed the damage upstream.

This phase asks the follow-up question directly: **is there a smallest set of
upstream backbone/neck layer groups that must stay FP16 to recover parity while
retaining meaningful INT8 execution?**

The measured answer is no.

---

## 1. Status of this phase

**`Phase 13D-MP-RECOVERY Frozen`** — bounded PTQ mixed-precision sensitivity
search did not recover INT8-vs-FP16 parity; the INT8 engine remains performance
evidence only and is not permitted to provide command authority.

| Runtime SHA | Value |
| --- | --- |
| Sweep start (`da1c3891` verified clean, local = origin) | `da1c3891a9092a9ff0ea117e9700e755f5323db7` |
| Candidate sweep C00–C09, PC = Jetson | `f0ca5e92c89184661a7eb59572135aa5ef8eed3c` |
| Freeze enforcement + runtime demonstration, PC = Jetson | `7a3bb43907103392cf003669d441fbf1c118bbc8` |

This phase remains post-training quantization throughout. No weight was
changed, no retraining or fine-tuning happened, the Phase 13D 640-frame
calibration and 160-frame holdout splits were reused unchanged, and the
confidence, IoU and parity thresholds were never touched. Every candidate
records those facts in its own evidence.

---

## 2. Layer groups, read off the real graph

The 1245 TensorRT layers parsed from the exact Phase 13D ONNX carry
ONNX-derived names of the form `/model.<stage>/…`. The observed stage layout —
not taken from documentation — is:

| Stage | Role | Layers | Graph index |
| --- | --- | --- | --- |
| `model.0`, `model.1` | stem convolutions | 3 + 3 | 0–5 |
| `model.2` | RepNCSPELAN4 | 60 | 6–108 |
| `model.3` | ADown | 22 | 109–173 |
| `model.4` / `model.5` | RepNCSPELAN4 / ADown | 60 / 22 | 174–341 |
| `model.6` / `model.7` | RepNCSPELAN4 / ADown | 60 / 22 | 342–509 |
| `model.8` | RepNCSPELAN4 | 60 | 510–612 |
| `model.9` | SPPELAN | 10 | 613–622 |
| `model.10`–`model.12` | Resize / Concat / RepNCSPELAN4 | 1 + 1 + 60 | 623–727 |
| `model.13`–`model.15` | Resize / Concat / RepNCSPELAN4 | 1 + 1 + 60 | 728–832 |
| `model.16`–`model.18` | ADown / Concat / RepNCSPELAN4 | 21 + 1 + 60 | 833–1000 |
| `model.19`–`model.21` | ADown / Concat / RepNCSPELAN4 | 21 + 1 + 60 | 1001–1168 |
| `model.22` | DDetect head | 72 | 1169–1244 |

A further **563 layers carry no `/model.N/` name at all** — the shape, constant
and gather plumbing TensorRT synthesises. They belong to no group by design, and
the matcher reports how many layers each group actually matched so a group can
never be credited with more than it covers.

The seven semantic groups:

| id | group | ONNX stage prefixes | matched layers |
| --- | --- | --- | --- |
| **G1** | `early_backbone` | `/model.0/ /model.1/ /model.2/ /model.3/` | 88 |
| **G2** | `mid_backbone` | `/model.4/ /model.5/ /model.6/ /model.7/` | 164 |
| **G3** | `late_backbone_sppelan` | `/model.8/ /model.9/` | 70 |
| **G4** | `neck_topdown_low_res` | `/model.10/ /model.11/ /model.12/` | 62 |
| **G5** | `neck_topdown_high_res` | `/model.13/ /model.14/ /model.15/` | 62 |
| **G6** | `neck_bottomup_pan` | `/model.16/ … /model.21/` | 164 |
| **G7** | `detect_head` | `/model.22/` | 72 |

Fourteen unit tests pin the prefix semantics, including that `/model.2/` does
not swallow `/model.20/` or `/model.22/`, and that the plumbing belongs to no
group.

---

## 3. Method

Every candidate used the same ONNX, the same verified 640-frame calibration
cache, the same 160-frame holdout, the same preprocessing and postprocessing,
and the same thresholds. Builds used `BuilderFlag.INT8`, `BuilderFlag.FP16` and
`OBEY_PRECISION_CONSTRAINTS`, with DLA never enabled.

Diagnostic candidates reused the verified calibration cache and a TensorRT
tactic **timing cache**, which caches kernel timings and never results. It cut
build time from ~3280 s cold to 54–183 s, which is what made a ten-candidate
sweep affordable. Every engine records whether it used one.

Ten candidates were evaluated — the stated bound — and no candidate's evidence
was overwritten, including none that failed.

---

## 4. Candidate comparison

FP16 reference on the same holdout: peak class score **0.708984**, box p50
**122.125**, box p99 **625.0**.

| candidate | forced FP16 groups | forced layers | INT8 | FP16 | FP32 | quantized fraction | class max ratio | class MAE | matched rate | class agree | IoU mean | conf err p95 | unsafe div | p50 ms | speedup | recovery |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `C00` | (none — baseline) | 0 | 202 | 26 | 11 | 0.8452 | 0.1068 | 3.97e-06 | 0.0949 | 1.000 | 0.8913 | 0.4985 | 0 | 70.16 | 1.218 | fail |
| `C01` | G1 early_backbone | 88 | 178 | 53 | 11 | 0.7355 | 0.1321 | 3.60e-06 | 0.1564 | 1.000 | 0.9021 | 0.4260 | 0 | 74.21 | 1.152 | fail |
| `C02` | G2 mid_backbone | 164 | 158 | 82 | 11 | 0.6295 | 0.1529 | 3.91e-06 | 0.0949 | 1.000 | 0.8992 | 0.4817 | 0 | 75.03 | 1.131 | fail |
| `C03` | G3 late_backbone_sppelan | 70 | 176 | 59 | 11 | 0.7154 | 0.1220 | 3.98e-06 | 0.1051 | 1.000 | 0.8969 | 0.4658 | 0 | 70.96 | 1.200 | fail |
| `C04` | G4 neck_topdown_low_res | 62 | 183 | 49 | 11 | 0.7531 | **0.2045** | 3.91e-06 | 0.1154 | 1.000 | 0.8989 | 0.4565 | 0 | 71.84 | 1.185 | fail |
| `C05` | G5 neck_topdown_high_res | 62 | 182 | 50 | 11 | 0.7490 | 0.1207 | 3.94e-06 | 0.1487 | 1.000 | 0.8981 | 0.4121 | 0 | 72.64 | 1.178 | fail |
| `C06` | G6 neck_bottomup_pan | 164 | 157 | 75 | 11 | 0.6461 | 0.1068 | 3.96e-06 | 0.0949 | 1.000 | 0.8922 | 0.4985 | 0 | 71.91 | 1.184 | fail |
| `C07` | G7 detect_head | 72 | 188 | 56 | 2 | 0.7642 | 0.1515 | 3.93e-06 | 0.0949 | 1.000 | 0.8867 | 0.4868 | 0 | 74.01 | 1.150 | fail |
| `C08` | G1–G6 (backbone + neck) | 610 | 21 | 230 | 11 | 0.0802 | 0.5306 | 2.37e-06 | 0.5538 | 1.000 | 0.9480 | 0.3284 | 0 | 83.73 | 1.015 | fail |
| `C09` | G1–G7 (every named layer) | 682 | **4** | 251 | 2 | **0.0156** | 0.9215 | 1.61e-06 | **0.8179** | 1.000 | 0.9692 | **0.2007** | 0 | 86.52 | **0.987** | fail |

Required to pass: matched rate ≥ 0.90, class agreement ≥ 0.98, IoU mean ≥ 0.75,
confidence error p95 ≤ 0.12, schema/non-finite errors 0, unsafe divergence 0,
INT8 layers > 0. Schema errors, non-finite outputs and unsafe authority
divergence were **0 for all ten candidates**.

Build durations: 183.5 s (C04), 86.2 s (C08), 53.7 s (C09); engine SHA-256
prefixes `a4e22210…`, `708ca966…`, `a841a946…`; C00 reused the Phase 13D engine
`9152064741d8…`. No thermal throttling was observed in any candidate.

### Group sensitivity ranking

By class-branch recovery (single-group candidates, most recovery first):

| rank | group | class max ratio | matched rate | conf err p95 |
| --- | --- | --- | --- | --- |
| 1 | G4 `neck_topdown_low_res` | 0.2045 | 0.1154 | 0.4565 |
| 2 | G2 `mid_backbone` | 0.1529 | 0.0949 | 0.4817 |
| 3 | G7 `detect_head` | 0.1515 | 0.0949 | 0.4868 |
| 4 | G1 `early_backbone` | 0.1321 | 0.1564 | 0.4260 |
| 5 | G3 `late_backbone_sppelan` | 0.1220 | 0.1051 | 0.4658 |
| 6 | G5 `neck_topdown_high_res` | 0.1207 | 0.1487 | 0.4121 |
| 7 | G6 `neck_bottomup_pan` | 0.1068 | 0.0949 | 0.4985 |

The two ranking signals disagree — G4 recovers the most class magnitude while
G1 and G5 recover the most matched detections — which is itself evidence that no
single group owns the damage.

### Tensor distributions

The box branch is essentially precision-independent across the whole sweep,
while the class branch recovers only as almost everything leaves INT8:

| candidate | class max (INT8) | class mean (INT8) | box p50 | box p99 |
| --- | --- | --- | --- | --- |
| FP16 reference | 0.708984 | 4.61e-06 | 122.125 | 625.0 |
| `C00` 202 INT8 layers | 0.075745 | 1.11e-06 | 122.875 | 619.0 |
| `C04` 183 INT8 layers | 0.145020 | 1.31e-06 | 122.750 | 619.0 |
| `C08` 21 INT8 layers | 0.376221 | 2.55e-06 | 122.3125 | 623.0 |
| `C09` 4 INT8 layers | 0.653320 | 3.56e-06 | 122.53125 | 625.0 |

---

## 5. Why the search froze

The trend across the ten candidates is monotone and leaves no room for a
bounded selection:

* **No single group recovers.** The best single group lifts the INT8 peak class
  score from 10.7 % to 20.5 % of FP16, against the ~100 % that parity needs.
* **Backbone + neck in FP16 is not enough.** `C08` leaves 21 INT8 layers, an
  8.0 % quantized fraction, and still only reaches 0.554 matched detection rate
  with confidence error 0.328.
* **Even the degenerate limit fails.** `C09` forces every named layer to FP16,
  leaving 4 INT8 layers and a 1.6 % quantized fraction. It reaches 0.818 matched
  and 0.201 confidence error — **still failing both bounds** — and by then it is
  *slower* than plain FP16 at 0.987× throughput.

So the degradation is distributed across the whole network rather than
concentrated in any group, and the region where parity could conceivably be met
is also the region where nothing meaningful is left in INT8 and the performance
benefit is gone. There is no smallest recovering set to select.

Recovering this would require changing the quantization itself — QAT,
retraining, or per-tensor dynamic-range overrides — all of which this phase is
forbidden from doing or claiming.

---

## 6. Freeze enforcement, in code

The freeze is enforced rather than merely written down.

`Int8RangeContract.authoritative` now defaults to **False**. A non-authoritative
INT8 backend still runs, still validates against the calibration envelope and
still records everything — it simply cannot grant AI authority. The refusal is
reported as `RECOVERY_PENDING` with classification `int8_non_authoritative` and
deliberately does **not** touch the range reject counters, because nothing
failed: the sample is valid and the refusal is a policy decision. A genuine
fault still reports as a fault. Enabling authority requires passing
`--int8-authoritative` deliberately.

### Measured effect, both backends, same 310-frame stream

| Measurement | FP16 backend | INT8 backend (frozen) |
| --- | --- | --- |
| `precision` | `fp16` | `int8` |
| streamed inferences | 314 | 310 |
| **perception results granted AI authority** | **308** | **0** |
| `int8_non_authoritative_suppression_count` | — | **308** |
| `ai_active` commands from perception | 308 | **0** |
| `safe_stop` commands | 8 | 316 |
| commands accepted by the C Safety MCU | **320** | 0 |
| commands rejected by the C Safety MCU | 8 | 324 |
| max mailbox depth | 1 | 1 |
| perception fallback | 0 | 0 |
| p99 frame-to-command | 100.32 ms (budget 949.49) | — |
| fault matrix | **27/28**, false accept 0, false reject 0 | not meaningful (see below) |

The two columns are exactly complementary: FP16 granted authority on 308
perception results, and the frozen INT8 backend suppressed authority on exactly
308. Both runs recorded 12 further `AI_ACTIVE` commands that came from the fault
matrix's own injected packets, not from perception — the same 12 appear in both,
which is how they are identified.

The FP16 fault matrix's one failure is `F28 stale frame`, observed as
`STALE_REJECT` where `SAFE_STOP` was expected: the command was refused by the C
Safety MCU rather than suppressed at the Jetson, so it was still never applied
and false accepts stayed at 0. This is the same timing-sensitive case already
recorded in the Phase 13D document.

Running the Phase 13B fault matrix against the **frozen INT8** backend is not
meaningful and is not claimed as a result: the matrix's healthy-path cases
expect a backend that can grant authority, and a permanently non-authoritative
backend keeps the C Safety MCU in a rejecting state, so eleven cases re-classify.
That is the freeze working, not a regression — but it is why the production
fault-matrix evidence above comes from the FP16 backend.

### Enforced policy

* **FP16 remains the production command-authority backend.**
* **INT8 is `experimental_non_authoritative`.**
* **INT8 may not produce `AI_ACTIVE`** — enforced in the range monitor and
  demonstrated at runtime.
* No QAT is attempted or scheduled automatically.

Not implemented and not claimed: INT8 is not wired as a genuine parallel shadow
backend running alongside FP16. What is enforced is the safety property that
matters — INT8 cannot command — and INT8 remains available for offline
measurement, which is how every number in §4 was produced.

---

## 7. What Phase 13D-MP-RECOVERY does not claim

Unchanged from Phase 13D, and re-stated because this phase touched precision
policy: no model accuracy, no mAP, no recall, no real-world perception quality,
no real-world representativeness of the calibration corpus, no safe autonomous
navigation, no route completion, no full HIL, no real MCU, no real CAN/UART
timing, no physical camera or actuator, no QAT, no Leaderboard or route or
infraction benchmark, and no physical vehicle deployment.

Additionally, and specific to this phase: **no parity threshold was weakened, no
confidence or IoU threshold was lowered, no calibration or holdout split was
changed, and no post-hoc score scaling was applied anywhere.** The parity gate
that blocked Phase 13D is the same gate that blocked all ten candidates here.

---

## 8. Evidence layout

All evidence is written under `experiments/phase13/` and is **gitignored**.
Each candidate has its own directory `phase13dmp-<candidate>-phase13d/`
containing `summary.json`, `candidate_result.json`, `engine_audit.json`,
`parity_metrics.json`, `latency_metrics.json`, `jetson_metrics.json` and
`raw_outputs/` with the exact forced-FP16 layer names and both engines' decoded
frames. The aggregate report lives in `mp-report-final-phase13d/` with
`mp_candidates.json` and `mp_candidate_table.md`.

Candidate engines, the calibration cache and the TensorRT timing cache live
outside the repository under `/home/myjetsonnx/models/ma-vlna/yolov9/mp/` and
are never committed.

---

## 9. Next phase

**`Phase 13E-FP16-SOAK-THERMAL-BACKPRESSURE-FAULT-INJECTION`** — the soak phase
runs against the FP16 backend, which is the backend that holds command
authority.
