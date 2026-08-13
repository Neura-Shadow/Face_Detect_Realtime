# Phase 13E-R — Clock Drift, Backpressure and Recovery

Phase 13E ended **Blocked**. The FP16 command-authority path was not slow and
was not wrong; the comparison it was judged by was. This phase fixes the sender,
proves the fix on real hardware, and makes the backpressure gate capable of
failing.

Nothing in the frozen Phase 13A contract changes: the 64-byte packet, the CRC
range, the sequence and lease semantics, the JILF/JILA framing, and the C
Virtual Safety MCU validity rule are all untouched. The INT8 freeze from Phase
13D-MP-RECOVERY stands — FP16 remains the sole command authority.

---

## 1. What Phase 13E actually measured

The MCU rejected **55,804 of 56,671** commands as `STALE_REJECT`, starting about
2.4 minutes into the run. Latency was healthy throughout: 98 ms mean, 111 ms
p99, zero transport timeouts.

The frozen validity rule is:

```c
if (valid_until_us < now_us || issued_timestamp_us > now_us) {
    return reject(counters, PROTOCOL_STALE_REJECT);
}
```

The past bound tolerates a full second. The future bound tolerates **nothing**.
That asymmetry is correct — a command stamped in the receiver's future cannot be
reasoned about — but it means the sender must never overshoot, not even by a
microsecond.

The sender overshot because:

* the PC↔Jetson offset was estimated **once** at session start, with 513 µs of
  measured uncertainty, and never refreshed;
* the two machines run independent oscillators whose rates differ by a few parts
  per million;
* `issued_timestamp_us()` subtracted only the static uncertainty, with no term
  for how far the offset had moved since it was measured.

The mapped timestamp started marginally behind the receiver's clock, drifted at
a constant rate, crossed zero at roughly 140 seconds, and from then on was
permanently ahead. Everything after that point was refused.

Two properties of this failure are worth stating plainly, because they explain
why it survived several earlier phases:

* **It is time-dependent.** Any run shorter than the crossing point passes.
* **It is sign-dependent.** A negative rate error never crosses at all. Half the
  parameter space is silently safe.

---

## 2. Goal 1 — bounded periodic clock discipline

`workers/core/clock_discipline.py` replaces the one-shot domain with a model
that is kept alive and knows how stale it is.

### The guard band

```
guard_us            = clock_uncertainty_us + estimated_drift_error_us + safety_margin_us
issued_timestamp_us = estimated_pc_now_us - guard_us
valid_until_us      = issued_timestamp_us + command_validity_us
```

`estimated_drift_error_us` is `abs(drift_ppm) * model_age_sec` plus the maximum
residual of the least-squares fit, so the guard grows with the age of the model
and with how badly the recent window fits a straight line. `safety_margin_us`
defaults to 1000.

The guard can only ever move a timestamp **backwards**. It can make a command
look older than it is; it can never make one look fresher. It therefore cannot
mask a genuinely stale command — it only stops a fresh one being pushed past the
receiver's clock by estimation error.

### The model

* Initial sync: ≥40 samples, unchanged from Phase 13B.
* Periodic resync: every 15 s by default, configurable, 12 probes per resync.
* Window: a fixed-capacity `deque` (32) of recent accepted syncs. History is
  never unbounded.
* Estimator: minimum-RTT offset per sync, least-squares slope across the window
  for drift in ppm. `time.perf_counter_ns` throughout.
* Each sync is dated with the midpoint of its own minimum-RTT round trip, in the
  PC domain, so the drift fit has a correct time axis.

A resync is **rejected** — counted, not applied — if it is reported invalid, is
non-finite, exceeds the uncertainty budget, or jumps the offset discontinuously.

### Degradation

The model reports itself degraded, which forbids AI authority and forces
SAFE_STOP on the existing path, when:

| Reason | Condition |
| --- | --- |
| `no_valid_clock_sync` | no accepted sync yet |
| `clock_model_too_old` | age > 3 × resync interval |
| `clock_uncertainty_above_budget` | uncertainty > 5000 µs |
| `implausible_drift_ppm` | \|drift\| > 100 ppm |
| `nonfinite_offset` / `nonfinite_drift` | estimate is not finite |

Staleness is judged against the **live** clock by default. A model that stops
being refreshed stops being trusted without anyone having to ask it — which is
precisely what Phase 13E lacked.

### Measuring the skew rather than assuming it

The JILA ACK carries `receive_timestamp_us`: the exact `now_us` the C MCU used
for the validity comparison. So the margin is observed directly, not inferred:

```
issued_future_skew_us = issued_timestamp_us - ack.receive_timestamp_us
```

`future_timestamp_reject_count` counts only `STALE_REJECT`s where the skew was
genuinely positive. The injected `expired_command` fault deliberately back-dates
validity, so it is excluded — its rejection is the injected outcome, not a clock
defect. Nothing here changes the rule; it only watches it.

### Deterministic proof

`scripts/tests/test_phase13er_clock_discipline.py` simulates two oscillators at
**−50, −10, 0, +10 and +50 ppm** for **three simulated hours** each, resyncing
every 15 simulated seconds, and asserts `issued_future_skew_us <= 0` on every one
of ~67,500 commands.

The same simulation is then run against the old one-shot model, which fails at
+10 and +50 ppm and passes at −50. That second half matters: without it the test
would pass vacuously, and it is also the direct explanation for why the defect
went unnoticed for so long.

---

## 3. Goal 2 — a producer CARLA cannot throttle

Phase 13E's burst published from inside the driving loop, so every publish was
preceded by `session.tick()`. A nominal 10 FPS burst delivered **2.48 FPS**: the
simulator was the bottleneck, input never exceeded what the Jetson could retire,
nothing was ever dropped, and latest-frame-only was never exercised. The gate
could not have failed, so it proved nothing.

`simulation/independent_frame_producer.py` runs on its own thread, paced by its
own monotonic clock, publishing over the same real JILF transport to the same
real Jetson and FP16 engine. Payloads are encoded **once** up front and replayed
from a bounded ring of real CARLA camera frames captured while driving — a
producer that re-encodes every frame is limited by the PC's JPEG encoder rather
than by its own clock, which is the same class of mistake as pacing on ticks.
Replayed frames carry a fresh timestamp so the consumer does not see them all as
equally stale.

CARLA keeps ticking and keeps receiving actuation during the burst; it simply no
longer decides when frames are offered. **No claim is made about closed-loop
control rate during a burst** — the burst measures the transport and the
consumer.

### What overload immediately exposed

Neither of these could appear without a burst that actually overloads.

**The mailbox could not drop.** The reader and the pipeline shared a thread:
`publish()` was followed by take-and-process in the same loop, so the depth-1
mailbox was never contended and `frames_dropped_mailbox` was structurally always
zero. The backlog went into the kernel socket buffer instead. The first real
burst read 3,028 frames, decoded 628, and rejected 2,400 as stale with a frame
age p99 of 2.0 s, issuing 2,402 SAFE_STOPs. That is correct fail-closed
behaviour, but it is an unbounded queue reporting a bounded one's metrics.
`--decoupled-consumer` gives the pipeline its own thread so the reader keeps
draining the socket and the mailbox discards what the pipeline did not reach.
Phase 13B/C/D keep the lock-step loop they were validated with.

**A healthy in-flight buffer read as a leak.** `buffer_leak_detected` was
computed from any non-free buffer, so sampling metrics while a frame was
legitimately in flight reported a leak. Idle runs happened to be clean, which is
why it had never fired. `leak_check` now takes the allowance the pipeline is
entitled to (receiving + mailbox + processing) and stays strict at rest.

Fixing the first then broke two lock-step assumptions that had been invisible for
the same reason: `publish_synthetic_frames` and the loopback gate both waited for
`processed >= sent`, which cannot happen once a superseded frame is discarded.
That failure is quiet — it burns the whole timeout, and a long enough idle then
tears the frame connection down on its own receive timeout, which is how one
15-second burst ended up publishing a single frame. Both now count a frame as
retired when it has been **processed or deliberately dropped**.

---

## 4. Goal 3 — bounded metric memory

`workers/core/bounded_metrics.py` provides the three shapes that replace the
per-frame lists:

* `OnlineStat` — exact count/min/max/mean/variance in constant memory (Welford).
* `BoundedSeries` — `OnlineStat` plus a fixed-bucket histogram for percentiles
  and a bounded ring of recent samples.
* `JsonlSink` — streams records to disk instead of accumulating them in RAM.

Replaced on the Jetson node: `frame_command_records`, `command_rtt_ms`,
`frame_to_command_ms`, `one_way_latency_ms`, `tensorrt_latency_samples`,
`diagnostic_throttle_applied` and `events`. Also `encode_ms_samples` and
`payload_size_samples` in the frame publisher.

Two honesty notes:

* Percentiles are now **histogram estimates** and say so. Every block reports
  `percentile_method`, `histogram_bucket_width` and its overflow counts, so the
  resolution is visible rather than implied. Minimum and maximum stay exact.
* The control channel returns a **bounded tail** of events, not the whole
  stream, and records `events_total_count`, `events_tail_capacity` and
  `events_truncated`. The complete stream is on the Jetson at
  `events.jsonl`; per-frame records are at `frame_command_records.jsonl`.

Evidence: `metrics_ring_capacity`, `metrics_ring_high_watermark` (overall and
per series), `metrics_unbounded_list_count`, and the RSS/FD/thread per-hour
drift rates the existing soak analyser already computes.

---

## 5. Gate A — local, on the real loopback transport

`scripts/run_phase13er_checks.py`. Unit tests alone cannot show any of this;
all three goals need a real transport, a real control channel and the real C
MCU in the loop.

```
issued_future_skew_us_max      -1332      (never in the future)
future_timestamp_reject_count  0
clock_resync_count             6
estimated_drift_ppm            -7.14
clock_guard_us                 1160
burst_input_fps                399.7
burst_processed_fps            32.7
mailbox_drop_count             7349
max_mailbox_depth              1
metrics_ring_high_watermark    512 of 512
```

Loopback consumers are fast, so the burst rate is raised until it overloads
them; the point is that overload is **reachable at all**, which Phase 13E never
showed.

Regressions: **443 unit tests pass**, and the Phase 13B fault matrix was re-run
in both consumer modes — **28/28**, zero false accepts, zero false rejects.

---

## 6. Real-hardware evidence

Measured live on the Jetson with the FP16 engine, one command record:

```
estimated_drift_ppm     11.39
clock_guard_us          1615
issued_future_skew_us   -2455
observed_classification ACCEPTED
control_mode            2 (AI_ACTIVE)
frame_to_command_ms     102.8
```

The measured drift on this hardware pair is **11.4 ppm**, larger than the ~3.5
ppm inferred after Phase 13E. At that rate the old one-shot model would have
crossed into the receiver's future in roughly 45 seconds. The disciplined model
holds the timestamp 2.455 ms in the receiver's past and the command is accepted
with full AI authority.

### Producer verification on hardware

A 90-second shakedown burst against the real Jetson and FP16 engine:

```
burst_target_fps               15.0
burst_input_fps                15.008     (producer holds its own rate)
burst_processed_fps            10.908
burst_mailbox_drops            367
max_mailbox_depth_during_burst 1
producer_publish_failures      0
producer_late_wakeups          0
```

Input exceeded what the consumer retired, superseded frames were dropped rather
than queued, and depth never left one. Compare Phase 13E, where a nominal 10 FPS
burst delivered 2.48 FPS and dropped nothing.

This shakedown is reported as **not** demonstrating the gate: its 90-second
burst is shorter than the formal ≥300 s requirement, and the gate says so rather
than accepting a burst that met every other condition. Same run, driving phases:
120 s burn-in, 732 frames, mailbox depth 1, zero fallbacks, zero CUDA errors,
zero command timeouts, frame-to-command p99 135.7 ms against a 449.6 ms budget,
6,185 AI_ACTIVE commands applied.

### An honest note on a stalled first attempt

The first hardware attempt aborted with `frame_transport_stalled`: 604 CARLA
ticks with zero frames published and `frames_received = 0` on the Jetson. Every
connection stage succeeded — control handshake, clock sync, session start, frame
client connect — and the CARLA session reported a successful Town03 load with
the ego vehicle and camera spawned.

A retry against the already-loaded map worked immediately and has run
continuously since. **The root cause was not established.** One hypothesis — that
a sensor registered through the handle returned by `load_world()` does not
deliver — was tested directly in isolation and **disproven**: both that handle
and a freshly acquired `get_world()` delivered 50 frames in 200 ticks. The
change made on that hypothesis was reverted rather than kept as an unjustified
edit to shared Phase 13B code. The remaining untested possibility is that the
CARLA server had only just started and its first episode's sensor stream was not
yet serving; that is timing, not a defect this phase has evidence for.

What did work correctly is the Phase 13E stall guard: the run **aborted** instead
of ticking an empty loop to the deadline and reporting hours of soak that never
happened.

---

## 7. Not claimed

No full HIL. No real MCU, CAN or UART timing. No physical camera, actuator or
vehicle. No model accuracy, mAP, recall or real-world perception quality. No
route, map or Leaderboard benchmark. No QAT. Power is never inferred from
utilisation. INT8 remains `experimental_non_authoritative` and may never grant
AI_ACTIVE.

The backpressure burst measures the transport and the consumer; it is not a
claim about CARLA closed-loop control rate.
