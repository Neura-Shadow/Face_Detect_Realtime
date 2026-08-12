# Phase 13E — FP16 Soak, Thermal, Backpressure and Fault Injection

Phase 13D-MP-RECOVERY froze INT8 as `experimental_non_authoritative`. This phase
therefore soaks the backend that actually holds command authority: the real
Jetson Orin NX running the verified FP16 TensorRT YOLOv9-c engine, driving the
full closed loop for hours.

```
CARLA -> USB-gadget Ethernet -> real Jetson FP16 TensorRT -> range/SafetyGate
      -> unchanged 64-byte command -> C Virtual Safety MCU -> CARLA virtual actuator
```

`validation_type = processor_in_the_loop` · `precision = fp16` ·
`command_authority_backend = fp16_tensorrt_yolov9c`

---

## 1. Status of this phase

**`Phase 13E-FP16-SOAK-THERMAL-BACKPRESSURE-FAULT-INJECTION Blocked`**
Classification: **`fault_recovery_failed`**
Root cause: **`command_validity_future_bound_zero_tolerance`**

The soak itself ran to completion and held every endurance property it was
built to test — 2 h 41 m in one continuous process, no crash, no restart, no
fallback, no CUDA error, no per-frame allocation, mailbox depth 1 throughout,
and no thermal, memory or latency drift. What it exposed is a defect that only a
long run can reach: after about 2.4 minutes the C Virtual Safety MCU began
rejecting **every** command as stale, and never stopped. 55,804 of 56,671
commands were `STALE_REJECT`.

That is the soak doing its job, and it is why no Pass is claimed.

| Requirement | Result |
| --- | --- |
| Formal soak ≥ 2 h | **7200.5 s (2.0001 h)** ✓ |
| Burn-in ≥ 1800 s | **1800.1 s** ✓ |
| One continuous process | ✓ |
| Unplanned restarts / unexpected exits | **0 / 0** ✓ |
| Engine load / reload | **1 / 0** ✓ |
| Fallback / CUDA errors / execute failures | **0 / 0 / 0** ✓ |
| Per-frame device allocation | **0** ✓ |
| Max mailbox depth | **1** ✓ |
| Resource / thermal / latency drift | **none** ✓ |
| Frame-to-command p99 inside budget | **111.2 ms of 949.5 ms** ✓ |
| Active control > 0 | **3453** ✓ |
| SAFE_STOP > 0 | **215,958** ✓ |
| Unexpected command timeouts | **0** ✓ |
| Backpressure recovery | **passed** ✓ (overload not achieved — §7) |
| Fault recovery | **failed** ✗ |
| False accept / false reject | **0 / 1** ✗ |
| INT8 authority count | **0** ✓ |

---

## 2. Runtime identity and continuity

| Field | Value |
| --- | --- |
| Runtime PC SHA | `e9972721a6094c1f1a547280233448e14f5b049e` |
| Runtime Jetson SHA | `e9972721a6094c1f1a547280233448e14f5b049e` |
| SHA equality | **true** |
| PC runner PID | 75132 |
| Jetson node PID | 58151 — **62 samples, all identical** |
| CARLA PID | 72112 |
| Total runtime | 9653.7 s (2 h 40 m 54 s) |
| Engine load count | 1 (`asserted_from_jetson_node_pid_continuity`) |
| Engine reload count | 0 |
| Planned restarts | 0 |
| Unplanned restarts | 0 |
| Unexpected process exits | 0 |
| FP16 engine SHA-256 | `0a596c079751f0a68b156face1eb6ee59c673cfc7d48667e0496def4f51690b3` (matches manifest) |

Frames and inferences continued throughout: every driving phase published frames
at 2.4–6.4 FPS with none starved, 54,851 frame-to-command samples and 56,671
completed inferences. Telemetry: 1763 snapshots, 1760 inside driving phases,
mean interval 5.39 s.

The one 167 s telemetry gap is the Phase 13B fault matrix, which does not sample
telemetry, and it falls outside every driving phase. Continuity is derived from
the per-phase records rather than the stored latency series, because that series
is downsampled to bound the evidence file and gaps between its points are a
property of the downsampling, not of the run — deriving continuity from it would
invent interruptions that never happened.

---

## 3. Gate A — local preflight

| Check | Result |
| --- | --- |
| Phase 13E unit tests | 38 / 38 |
| Phase 13C fault matrix (test doubles) | **22 / 22**, false accept 0, false reject 0 |
| Phase 13D / 13C / 13B / 13A regressions | 161 / 107 / 83 / 2 |

### F28 made deterministic

F28 flapped between `SAFE_STOP` and `STALE_REJECT` because the fault observer
polled until `commands_sent` moved, while a command's classification is only
recorded once its ACK resolves — the snapshot could land on either side of that
gap. The observer now waits for a *complete* observation, and the stale-frame
case is classified from the signal it exercises: the Jetson refused a stale
frame and emitted SAFE_STOP. The MCU's own verdict is recorded but not
substituted, because the backdated timestamp propagates into the command and
reading the MCU's refusal would report a downstream refusal instead of the one
under test. The expected classification stays exactly `SAFE_STOP` — narrowed,
not broadened. Verified **28/28** on the real link in the preflight-only run.

In the definitive soak F28 could not be observed at all (`NO_OBSERVATION`),
because by then the MCU rejected every command — see §8.

---

## 4. Preflight — FP16 engine identity on the target

Verified on the Jetson before driving: SHA-256 matched the recorded manifest,
`deserialize_cuda_engine` succeeded, and the binding contract was
`images [1,3,640,640] FLOAT → output0 [1,84,8400] FLOAT`.

---

## 5. Burn-in and formal soak

| Phase | Duration | Frames | Ticks | FPS | p99 latency | Mailbox | Fallback | CUDA |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| burn_in | 1800.1 s | 11,059 | 44,236 | 6.14 | 110.5 ms | 1 | 0 | 0 |
| **soak** | **7200.5 s** | **42,566** | **170,272** | **5.91** | **111.3 ms** | 1 | 0 | 0 |

Overall frame-to-command across 54,851 samples: min 92.2, p50 97.6, p95 104.0,
**p99 111.2**, max 228.0 ms, mean 98.4 ms — against a 949.5 ms validity budget.

---

## 6. Resource and thermal drift

Start / middle / end windows, with per-hour rates:

| Series | Start | Middle | End | Per hour |
| --- | --- | --- | --- | --- |
| Process RSS | 2.714 GB | 2.804 GB | 2.885 GB | **+63.6 MB/h** |
| Open FDs | 46 | 46 | 46 | **0** |
| Threads | 4 | 4 | 4 | **0** |
| Swap used | 0 | 0 | 0 | **0** |
| RAM used | 5.440 GB | 5.444 GB | 5.444 GB | +1.5 MB/h |
| Frame-to-command | 98.08 ms | 98.99 ms | 98.09 ms | **+0.006 ms/h** |
| CPU temperature | 54.61 °C | 54.91 °C | 54.91 °C | +0.11 °C/h |
| GPU temperature | 52.74 °C | 52.97 °C | 52.97 °C | +0.09 °C/h |
| SoC temperature | 54.73 °C | 55.13 °C | 55.13 °C | +0.15 °C/h |
| Tj | 54.75 °C | 55.06 °C | 55.06 °C | +0.12 °C/h |

`drift_labels = []`, `steady_state_held = true`, **thermal throttling not
observed**. Temperatures plateaued: the middle and end windows are identical to
two decimal places, so the rise happened during warm-up and then stopped.

File descriptors and threads were **exactly flat** across 2 h 41 m, and swap
never left zero.

RSS grew 63.6 MB/h and is the one number worth naming rather than waving past.
It is bounded, non-progressive by the leak test, and well inside both limits
(170 MB total against a 256 MB allowance; ratio 1.063 against 1.15). Its source
is known: the Jetson node appends a per-frame record, plus latency and RTT
samples, to unbounded in-memory lists. That is bookkeeping proportional to
frames processed, not a leak in the perception or transport path — but it is
unbounded by construction and would matter for a run of days rather than hours.

---

## 7. Backpressure

| Window | FPS | p95 | p99 | Mailbox depth | Drops |
| --- | --- | --- | --- | --- | --- |
| Pre-burst (60.5 s) | 6.34 | 102.4 ms | 107.4 ms | 1 | — |
| Burst (60.4 s, target 10 FPS) | **2.48 effective** | — | — | **1** | 0 |
| Post-burst (60.5 s) | 6.40 | 102.7 ms | 106.2 ms | 1 | 0 |

Recovery ratio 0.988 against a 1.25 bound → `backpressure_recovery_passed =
true`. Latest-frame-only held and mailbox depth never exceeded 1.

**The overload condition was not actually achieved, and this is not claimed as a
demonstration of drop-under-overload.** The burst publishes from the CARLA
lockstep loop, so it is paced by simulator ticking rather than by the requested
rate: the effective rate was 2.48 FPS against a 10 FPS target — *below* the
consumer's ~6 FPS, not above it. Mailbox drops were therefore 0, and the
requirement "mailbox drop count > 0 during overload when expected" was never
exercised. Producing real overload needs a publisher decoupled from the tick
loop; that is not implemented.

---

## 8. Fault injection and recovery

### Fail-closed behaviour: intact

Every invalid or stale condition emitted `SAFE_STOP`, as required:

| Case | Fault | Expected | Observed | Pass |
| --- | --- | --- | --- | --- |
| E01 | inference timeout | SAFE_STOP | **SAFE_STOP** | ✓ |
| E02 | CUDA test-double error | SAFE_STOP | **SAFE_STOP** | ✓ |
| E03 | stale AI result | SAFE_STOP | **SAFE_STOP** | ✓ |
| E04 | invalid input range | SAFE_STOP | **SAFE_STOP** | ✓ |
| E05 | clock uncertainty violation | SAFE_STOP | **SAFE_STOP** | ✓ |

`false_accept_count = 0` — nothing invalid was ever accepted.

### Recovery: failed

| Case | Fault | Result |
| --- | --- | --- |
| E01–E05 | as above | classification passed, **recovery failed** |
| E06 | network jitter | NOT_RECOVERED |
| E07 | temporary CPU contention | NOT_RECOVERED |
| E08 | temporary memory pressure | NOT_RECOVERED |

Phase 13B matrix: **9 of 28** passed (F02, F05, F08–F13, F27). The 19 failures
are all one of two shapes — a case expecting an MCU classification observed as
`STALE_REJECT`, or a case observed as `NO_OBSERVATION` because no command was
ever accepted. `false_reject_count = 1` (F01, expecting `ACCEPTED`, observed
`STALE_REJECT`).

### Root cause

The Jetson side was healthy for the entire run:

```
tensorrt_inference_completed_count = 56671
tensorrt_active_authority_count    = 56659
ai_active_command_count            = 56671
range_state_counts = {VALID: 56660, RECOVERY_PENDING: 8,
                      OUTPUT_RANGE_INVALID: 3, INPUT_RANGE_SHIFT: 1}
```

The FP16 perception granted authority on essentially every frame. The C Virtual
Safety MCU then refused those commands:

```
command_classifications = {ACCEPTED: 865, STALE_REJECT: 55804,
                           STATE_REJECT: 10, CRC_REJECT: 2,
                           TRANSPORT_TIMEOUT: 3, SEQUENCE_REJECT: 1}
```

All 865 acceptances fall inside the first ~2.4 minutes. The validity rule is:

```python
if packet.valid_until_us < now_us or packet.issued_timestamp_us > now_us:
    STALE_REJECT
```

The **past** bound tolerates a full `command_validity_ms` (1000 ms). The
**future** bound has *zero* tolerance: a command whose issued timestamp maps
even one microsecond ahead of the MCU's clock is stale.

The PC↔Jetson offset is measured **once** at session start — 40 samples,
513 µs uncertainty, min-RTT estimator — and never refreshed. The two clocks are
independent monotonic oscillators, so their relative rate differs by a few ppm.
The mapped Jetson timestamp starts marginally *behind* the PC clock and drifts;
once it crosses zero it is permanently ahead, and from that instant every
command is "from the future". Crossing after ~140 s implies a drift of roughly
3.5 ppm — entirely ordinary for two crystals, and invisible to every previous
phase because none ran longer than a few minutes.

Measured latency rules out the alternatives: frame-to-command stayed at 98 ms
mean with p99 111 ms and zero command timeouts for the whole run, so commands
were arriving promptly. Nothing was slow; the comparison was wrong.

Two candidate fixes, neither applied here because both change the frozen Phase
13A/13B command-validity contract and that is a safety-relevant decision rather
than a cleanup:

1. Give the future bound a tolerance equal to the measured clock uncertainty
   (plus a margin), matching the asymmetry the past bound already has.
2. Re-synchronise the clock periodically during long sessions and re-derive the
   offset, instead of trusting one measurement for hours.

---

## 9. Safety posture unchanged

* **FP16 held command authority**: 56,659 authority grants from perception.
* **INT8 authority count: 0** — INT8 was never loaded; the node ran
  `--tensorrt-precision fp16` against the FP16 engine.
* **No invalid result was ever accepted**: `false_accept_count = 0`.
* When the MCU stopped accepting commands, the system degraded to continuous
  `SAFE_STOP` (215,958 applications). The failure mode was fail-closed.

---

## 10. Defects this phase exposed

Four, each found by running against real hardware:

1. **The Phase 13B fault matrix cannot run before the driving phases.** Two of
   its cases tear down the frame transport and reconnecting does not restore a
   usable stream. With the matrix first, burn-in stalled with zero frames; with
   no matrix, the same build sustained 575 frames in 90 s. It now runs last —
   the position 13C and 13D already use.
2. **A stalled transport could masquerade as a soak.** One attempt ran every
   phase to its full wall-clock duration reporting burn-in, soak, backpressure
   and fault phases, each with `frames=0`. A stall now aborts the whole run.
3. **A killed run leaves its spawn point occupied**, so the host now tries
   bounded successive spawn points and records which was used.
4. **Command validity has a zero-tolerance future bound** (§8) — the finding
   this phase exists to produce.

---

## 11. Forbidden claims

Phase 13E asserts none of: full HIL, a real MCU, real CAN/UART timing, a
physical camera, a physical actuator, model accuracy, mAP, recall, a route or
infraction benchmark, a CARLA Leaderboard result, or physical vehicle
deployment. Power is never inferred from utilisation and the board exposes no
`VDD_*` rail.

---

## 12. Evidence layout

All evidence is under `experiments/phase13/<run-id>-phase13e/` and is
**gitignored**. Engines, models, datasets, frames, logs, telemetry and runtime
evidence are never committed.

```
manifest.json   summary.json   environment.json   engine_manifest.json
soak_timeseries.json   drift_report.json   continuity_report.json
latency_metrics.json   backpressure_metrics.json   jetson_metrics.json
phase13e_fault_matrix.json/.csv   fault_injection_matrix.json/.csv
network_metrics.json   events.jsonl   commands.txt   README.md   raw_outputs/
```

---

## 13. Next step

The soak infrastructure and the FP16 endurance properties are established. The
blocking defect is in the command-validity comparison, not in perception,
transport or thermals. The next phase should decide the validity-tolerance
question deliberately — it changes a frozen safety contract — and then re-run
this soak unchanged.
