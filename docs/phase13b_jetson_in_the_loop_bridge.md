# Phase 13B — Jetson-in-the-Loop Bridge

Phase 13B connects the simulated CARLA world running on the Windows simulation
PC to the **real** NVIDIA Jetson Orin NX compute module, and closes the loop
back into CARLA through the portable C Virtual Safety MCU.

`validation_type = processor_in_the_loop`

---

## 1. What is physical and what is simulated

Exactly one thing in this phase is physical: the Jetson compute node and the
cable it talks over.

| Physical (measured) | Simulated (modelled) |
| --- | --- |
| Jetson Linux (Ubuntu 20.04.6, kernel 5.10.192-tegra) | CARLA RGB camera |
| Jetson CPU / GPU / RAM | Environment and traffic |
| Jetson process and thread scheduling | Ego vehicle and vehicle physics |
| Jetson network stack | Safety MCU (portable C emulator) |
| CUDA 11.4.315 / TensorRT 8.5.2.2 installation | Actuator |
| Jetson thermal and resource telemetry | |
| USB cable + L4T USB Device Mode Ethernet transport | |

### Forbidden claims

Phase 13B does **not** demonstrate, and its evidence never asserts: full HIL, a
real MCU, a real S32K344, real CAN/UART timing, a physical camera, a physical
actuator, TensorRT inference or an inference benchmark, model or perception
accuracy, navigation quality, route completion, a CARLA Leaderboard result, an
infraction benchmark, or physical vehicle deployment.

TensorRT deployment is Phase 13C. Phase 13B is dummy-perception only.

---

## 2. Verified hardware and software baseline

| Item | Value |
| --- | --- |
| Board | Seeed Studio reComputer J4012 |
| Module | NVIDIA Jetson Orin NX 16 GB |
| Architecture | `aarch64` |
| OS | Ubuntu 20.04.6 |
| JetPack | 5.1.3 |
| L4T | R35.5.0 |
| Kernel | 5.10.192-tegra |
| Python | 3.8.10 |
| CUDA | 11.4.315 |
| TensorRT | 8.5.2.2 (installed, **not used** by Phase 13B) |
| nvpmodel | 15 W, mode 2 (**not modified**) |
| Jetson repo | `/home/myjetsonnx/Face_Detect_Realtime` |
| Jetson venv | `/home/myjetsonnx/venvs/ma-vlna` |
| CMake | 3.16.3 |
| GCC | 9.4.0 |
| OpenCV (`cv2`) | 4.5.4 (JetPack system package) |

Simulation PC: Windows 11, CARLA 0.9.16 at `D:\CARLA\packages\CARLA_0.9.16`,
CARLA Python at `D:\CARLA\envs\ma-vlna-carla312\python.exe`, RPC 127.0.0.1:2000.

### Transport medium

`transport_medium = usb_gadget_ethernet` — L4T USB Device Mode Ethernet
(`l4tbr0`), Jetson at `192.168.55.1`. This is **not** RJ45 and **not** Gigabit
Ethernet. The PC source address is *detected* from the routing table before
every run and recorded in evidence; `192.168.55.100` is never assumed.

---

## 3. Closed loop

```
Windows PC                                  Real Jetson Orin NX
──────────                                  ───────────────────
CARLA RGB camera (BGRA)
  └─ explicit BGRA -> BGR
       └─ JPEG encode
            └─ TCP :13510 ───────────────►  FrameReceiver
                                              └─ FixedBufferPool (3)
                                                   └─ LatestFrameMailbox(1)
                                                        └─ JPEG decode -> BGR8
                                                             └─ input-only RangeShift
                                                                  └─ DummyPerceptionBackend
                                                                       └─ diagnostic PlannerAction
                                                                            └─ SafetyGate
                                                                                 └─ PlannerAction->control mapper
                                                                                      └─ EmbeddedCommandBridge
C Virtual Safety MCU  ◄──── UDP :13511 ──────────────────────────────────────────────── 64-byte Phase 13A packet
  └─ ma_vlna_safety_mcu_ffi (ctypes)
       └─ 48-byte JILA ACK ── UDP :13512 ─►  ACK receiver
  └─ VirtualActuatorBridge
       └─ carla.VehicleControl
            └─ next CARLA tick
```

Control, clock-sync and metrics run over TCP `:13513` (Jetson-side server,
length-prefixed UTF-8 JSON, never pickle).

---

## 4. Wire contracts

### 4.1 Frame header — `JILF`, exactly 56 bytes, little-endian

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 4 | `magic` = `b"JILF"` |
| 4 | 2 | `protocol_version` = 1 |
| 6 | 2 | `flags` |
| 8 | 2 | `header_size` = 56 |
| 10 | 2 | `codec` (1 = JPEG) |
| 12 | 8 | `frame_id` |
| 20 | 8 | `simulation_timestamp_us` |
| 28 | 8 | `pc_monotonic_us` |
| 36 | 4 | `width` |
| 40 | 4 | `height` |
| 44 | 2 | `channels` |
| 46 | 2 | `pixel_format` (1 = BGR8) |
| 48 | 4 | `payload_size` |
| 52 | 4 | `payload_crc32` |

`struct.calcsize("<4sHHHHQQQIIHHII") == 56` is asserted at import time and
re-asserted by `scripts/tests/test_phase13b_protocols.py`.

**Payload CRC is CRC-32/ISO-HDLC over the encoded JPEG payload only.** The
56-byte header is not covered. Regression vectors are shared by both sides.

Rejections: unsupported version → `FRAME_PROTOCOL_REJECT`; unsupported codec →
`FRAME_CODEC_REJECT`; unsupported pixel format → `FRAME_PIXEL_FORMAT_REJECT`;
zero/oversized payload, bad dimensions, wrong length → `FRAME_SIZE_REJECT`;
payload CRC mismatch → `FRAME_CRC_REJECT`.

Bounds: default max payload 4 MiB (configurable), fixed pool of 3 buffers,
mailbox depth exactly 1, bounded socket timeouts, partial read/write handling,
reconnect handling, no pickle, no unbounded receive buffer.

**Colour path is mandatory:** CARLA raw BGRA → explicit BGRA-to-BGR → JPEG →
TCP → Jetson JPEG decode → BGR8. Raw BGRA is never sent while declaring BGR8.

### 4.2 Command packet — unchanged Phase 13A, exactly 64 bytes

Phase 13B does not touch the Phase 13A command contract:
`protocol_version = 1`, `packet_size_bytes = 64`, `little_endian = true`,
`crc_coverage_bytes = 60` (CRC-32/ISO-HDLC over bytes 0..59).

One UDP datagram = one 64-byte packet. No wrapper, no JSON, no extra header.
Any other datagram size is an error. The receiver can pin the expected source
host. Field semantics — sequence, lease, `valid_until_us`, `control_mode`,
`range_shift_state`, `result_age_ms`, flags, CRC — are all unchanged.

### 4.3 ACK/status packet — `JILA`, exactly 48 bytes, little-endian

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 4 | `magic` = `b"JILA"` |
| 4 | 2 | `protocol_version` = 1 |
| 6 | 2 | `message_type` |
| 8 | 4 | `acked_sequence` |
| 12 | 8 | `receive_timestamp_us` |
| 20 | 8 | `send_timestamp_us` |
| 28 | 1 | `mcu_state` |
| 29 | 1 | `result_code` |
| 30 | 1 | `accepted` |
| 31 | 1 | `range_shift_state` |
| 32 | 4 | `fault_flags` |
| 36 | 4 | `last_valid_command_age_ms` |
| 40 | 4 | `heartbeat_age_ms` |
| 44 | 4 | `crc32` |

CRC-32/ISO-HDLC over bytes 0..43; the CRC field occupies bytes 44..47.
`struct.calcsize("<4sHHIQQBBBBIIII") == 48`.

`result_code` maps one-to-one onto the frozen Phase 13A C `protocol_result_t`:

| `result_code` | C enum | Classification |
| --- | --- | --- |
| 0 | `PROTOCOL_ACCEPTED` | `ACCEPTED` |
| 1 | `PROTOCOL_LENGTH_REJECT` | `LENGTH_REJECT` |
| 2 | `PROTOCOL_CRC_REJECT` | `CRC_REJECT` |
| 3 | `PROTOCOL_STALE_REJECT` | `STALE_REJECT` |
| 4 | `PROTOCOL_SEQUENCE_REJECT` | `SEQUENCE_REJECT` |
| 5 | `PROTOCOL_LEASE_REJECT` | `LEASE_REJECT` |
| 6 | `PROTOCOL_VERSION_REJECT` | `VERSION_REJECT` |
| 7 | `PROTOCOL_RANGE_REJECT` | `RANGE_REJECT` |
| 8 | `PROTOCOL_STATE_REJECT` | `STATE_REJECT` |

An ACK is rejected on wrong magic, wrong version, wrong size, CRC mismatch,
sequence mismatch, stale sequence or an unexpected sender.

---

## 5. Bounded buffering

`workers/core/latest_frame_mailbox.py` provides a fixed pool (default 3) and a
mailbox whose depth is exactly 1. Ownership states are `FREE`,
`TRANSPORT_OWNED`, `MAILBOX_OWNED`, `PROCESSING_OWNED`; double release,
use-after-release, foreign release and mailbox depth > 1 are all explicit
errors. Publishing a newer frame releases the older buffer and increments the
overwrite counter — nothing queues.

Recorded metrics: `frames_received`, `frames_decoded`, `frames_processed`,
`frames_dropped_transport`, `frames_dropped_mailbox`, `buffer_acquire_failures`,
`max_mailbox_depth`, `latest_frame_overwrite_count`, `buffer_pool_size`,
`buffer_pool_high_watermark`, `stale_frame_reject_count`, `frame_age_ms_p50`,
`frame_age_ms_p95`, `frame_age_ms_p99`.

**Pass requirement: `max_mailbox_depth == 1`.**

---

## 6. The portable C library is the runtime source of truth

Phase 13B does **not** add a second Python implementation of the Virtual Safety
MCU. `embedded/safety_mcu/src/safety_mcu_ffi.c` exposes the *unchanged*
Phase 13A parser and FSM through a narrow C ABI, built as a shared library and
loaded with `ctypes`:

- Windows: `ma_vlna_safety_mcu_ffi.dll`
- Linux: `libma_vlna_safety_mcu_ffi.so`
- CLI override: `--mcu-library <path>`

Exported API: `safety_mcu_get_abi_version`, `safety_mcu_get_protocol_version`,
`safety_mcu_get_command_packet_size`, `safety_mcu_get_crc_coverage_bytes`,
`safety_mcu_get_control_scale`, `safety_mcu_get_receive_result_size`,
`safety_mcu_get_counters_size`, `safety_mcu_crc32`, `safety_mcu_create`,
`safety_mcu_destroy`, `safety_mcu_reset`, `safety_mcu_complete_boot`,
`safety_mcu_arm`, `safety_mcu_clear_failsafe`, `safety_mcu_set_lease`,
`safety_mcu_begin_session`, `safety_mcu_receive_packet`, `safety_mcu_tick`,
`safety_mcu_get_state`, `safety_mcu_get_counters`.

`safety_mcu_receive_result_t` is 28 bytes with fixed-width fields, explicit
padding and compile-time `_Static_assert` layout checks; the ctypes mirror
asserts the same size and offsets. There is no dynamic allocation per received
packet (allocation happens only in create/destroy), no global singleton, and
multiple instances are independent.

At startup the runtime verifies the FFI ABI version, the Phase 13A protocol
version and the Phase 13A command packet size, and refuses to run on a
mismatch (`virtual_mcu_ffi_failed`).

`VirtualActuatorBridge` consumes the C-validated q15 control values. Python
never re-parses the accepted 64-byte packet to decide actuator authority; it
only serialises the ACK and maps the already-validated values onto
`carla.VehicleControl`.

`SafetyMCUEmulator` (Python) is used **only** as a unit-test oracle and is
cross-checked against the C decisions in
`scripts/tests/test_phase13b_virtual_mcu_ffi.py`.

---

## 7. Session, lease and clock domain

The control channel negotiates `run_id`, protocol versions, command and ACK
packet sizes, expected hosts and ports, a **non-zero** `command_lease_id`, the
lease expiry, the heartbeat policy and the clock-sync samples.

- The orchestrator generates a fresh non-zero lease id per runtime session.
- The PC MCU receives it via `safety_mcu_set_lease` and rejects any command
  with a wrong or expired lease.
- The Jetson uses the exact negotiated lease id and never hardcodes one.
- Sequence is monotonic within a negotiated session.
- A restarted Jetson node performs a new handshake; old run-id/lease/sequence
  packets do not become valid again.
- A bare reconnect never resets the C FSM: only the explicit
  `safety_mcu_begin_session` bootstrap rewinds the sequence window.

### Clock synchronisation

At least 20 NTP-style four-timestamp probes over the control channel, with the
mandated sign convention:

```
jetson_minus_pc_offset_us = ((t2 - t1) + (t3 - t4)) / 2
network_delay_us          = (t4 - t1) - (t3 - t2)
clock_uncertainty_us      = max(0, network_delay_us / 2)
pc_clock_us               = jetson_clock_us - jetson_minus_pc_offset_us
```

The minimum-RTT valid sample is the estimator. The converted PC clock domain is
used for `issued_timestamp_us`, `valid_until_us`, command freshness and one-way
latency. `issued_timestamp_us` additionally subtracts the measured uncertainty
as a guard band: this can only make a command *older*, never fresher, so it
cannot mask a stale command, and it keeps a valid command from being pushed
past the receiver's clock by conversion error.

Default budget: `clock_uncertainty_us <= 5000`. Above it, one-way latency
fields are `null`, `AI_ACTIVE` is forbidden, `SAFE_STOP` is emitted and
`clock_sync_degraded = true`. RTT metrics stay valid when one-way metrics are
null.

`simulation_timestamp_us` is CARLA simulation time only and is never compared
against Jetson wall or monotonic time. Frame network age uses `pc_monotonic_us`
plus the explicit clock-domain conversion.

---

## 8. Range-shift scope (input-only)

Phase 13B uses `DummyPerceptionBackend`, so no real model activation tensors
exist. Activation-range, quantization-saturation and TensorRT tensor evidence
are **never** fabricated.

`InputOnlyRangeProfile` (in `workers/core/range_shift_monitor.py`) reuses the
existing `RangeShiftMonitor` with a *separate* Phase 13B contract instance and
supplies no activations at all, so those code paths cannot fire. It checks raw
input min/max, decoded dtype, width/height/channels, the BGR/RGB contract,
normalized min/max, channel mean/std, NaN/Inf, frame age, result age and output
control bounds. The default full Phase 13A contract is untouched.

Evidence fields:

```
input_range_checked = true
activation_range_checked = false
quantization_saturation_checked = false
range_validation_scope = input_only_dummy_backend
```

On input-validation failure: `AI_ACTIVE` is forbidden, `SAFE_STOP` is emitted
with a precise reason, the SAFE_STOP packet goes through the unchanged
`EmbeddedCommandBridge`, the C Virtual Safety MCU validates it, and the virtual
actuator applies the C-accepted SAFE_STOP.

Note that the monitor's Phase 13A recovery rule still applies: after any
failure, three consecutive valid samples are required before `AI_ACTIVE`
resumes. The first two frames of any run are therefore `RECOVERY_PENDING` →
`SAFE_STOP` by design.

---

## 9. Jetson diagnostic control policy

Deterministic, runner-scoped, bounded, and explicitly **not** a
navigation-quality policy.

When every gate passes: one forward action step at low speed with zero
steering, mapped to `steering = 0.0`, `throttle = 0.20` (default, CLI
configurable via `--diagnostic-throttle`), `brake = 0.0`, with
`--command-validity-ms 500`.

The speed on the diagnostic `ActionStep` is derived by inverting the
**existing, unmodified** `PlannerActionToCarlaControl` mapper so the requested
throttle falls out of the baseline chain. The mapper is never changed to make
Phase 13B pass, and the existing `SafetyGate` still runs and may clamp the
speed — in which case the lower applied throttle is simply recorded.

When any gate fails: `steering = 0.0`, `throttle = 0.0`, `brake = 1.0`,
`control_mode = SAFE_STOP`.

---

## 10. CARLA host, camera and timing

Defaults: `Town03` (or a compatible `Town03_Opt`), `map_load_mode
reuse_or_load`, `fixed_delta_seconds 0.05`, `camera 640x360 @ 10 FPS`,
`setup_timeout_sec 180`, `warmup_ticks 20`, `frames 300`.

```
fixed_delta_seconds = 0.05  ->  simulator frequency = 20 Hz
camera_fps = 10             ->  sensor_tick = 0.10 s
```

**The RGB sensor therefore emits one frame every two simulation ticks.** Phase
13B never assumes that every CARLA tick produces a camera frame.

Lockstep: tick → detect a new camera frame → if new, publish it and wait a
bounded time for the matching Jetson command, let the C MCU validate it, then
apply the accepted diagnostic control or SAFE_STOP; on an intermediate tick
with no new frame, hold the last C-accepted control only while its validity
window is open, otherwise apply SAFE_STOP.

Realtime: CARLA advances independently, latest-frame policy applies, commands
past `valid_until` are rejected, and a timeout means SAFE_STOP.

`carla.VehicleControl` is applied only after the C Virtual Safety MCU accepts
the matching command. On reject, command timeout, invalid or missing ACK,
heartbeat timeout, clock invalidity or transport disconnect, the bridge applies
`steer = 0.0, throttle = 0.0, brake = 1.0`.

CARLA lifecycle: an already-running server is reused; only the configured CARLA
package is ever started; unrelated Unreal processes are never killed; and only
processes this run started are stopped.

---

## 11. Fault matrix

28 deterministic one-at-a-time cases, written to `fault_matrix.json` and
`fault_matrix.csv` with `fault_id`, `fault_name`, `gate`, `injection_step`,
`expected_classification`, `observed_classification`, `passed`, `details`.

| ID | Fault | Step | Expected |
| --- | --- | --- | --- |
| F01 | valid command | command_path | `ACCEPTED` |
| F02 | corrupt command CRC | command_path | `CRC_REJECT` |
| F03 | duplicate command | command_path | `SEQUENCE_REJECT` |
| F04 | out-of-order command | command_path | `SEQUENCE_REJECT` |
| F05 | delay beyond `valid_until` | command_path | `STALE_REJECT` |
| F06 | wrong lease | command_path | `LEASE_REJECT` |
| F07 | expired lease | command_path | `LEASE_REJECT` |
| F08 | drop command | command_path | `TRANSPORT_TIMEOUT` |
| F09 | drop ACK | ack_path | `TRANSPORT_TIMEOUT` |
| F10 | ACK CRC corruption | ack_path | `CRC_REJECT` |
| F11 | ACK sequence mismatch | ack_path | `SEQUENCE_REJECT` |
| F12 | stale ACK | ack_path | `STALE_REJECT` |
| F13 | unexpected sender | command_path | `TRANSPORT_TIMEOUT` |
| F14 | stop heartbeat | watchdog | `FAILSAFE` |
| F15 | NaN/Inf frame input | range_path | `SAFE_STOP` |
| F16 | invalid input range | range_path | `SAFE_STOP` |
| F17 | BGR/RGB contract mismatch | range_path | `SAFE_STOP` |
| F18 | stale AI result age | range_path | `RANGE_REJECT` |
| F19 | clock uncertainty violation | clock_path | `SAFE_STOP` |
| F20 | frame payload CRC corruption | frame_path | `FRAME_CRC_REJECT` |
| F21 | oversized frame payload | frame_path | `FRAME_SIZE_REJECT` |
| F22 | invalid frame dimensions | frame_path | `FRAME_SIZE_REJECT` |
| F23 | unsupported frame codec | frame_path | `FRAME_CODEC_REJECT` |
| F24 | unsupported frame version | frame_path | `FRAME_PROTOCOL_REJECT` |
| F25 | zero-size frame payload | frame_path | `FRAME_SIZE_REJECT` |
| F26 | partial payload / early disconnect | frame_path | `TRANSPORT_TIMEOUT` |
| F27 | TCP disconnect and reconnect | frame_path | `TRANSPORT_TIMEOUT` |
| F28 | stale frame | frame_path | `SAFE_STOP` |

A fault expected to be rejected but accepted increments `false_accept_count`; a
valid operation expected to be accepted but rejected increments
`false_reject_count`. Both must be `0`.

---

## 12. Gates and status semantics

**Gate A — local loopback.** No CARLA, no Jetson. Unit tests, the C build and
CTest, and a real `run_phase13b_jetson_node.py` process acting as a PC-local
substitute over the same TCP/UDP transports, plus the full fault matrix. Gate A
alone permits only **Prepared**.

**Gate B — real Jetson transport.** Requires the real Jetson, non-interactive
SSH, an exact PC/Jetson runtime git SHA match, `aarch64`, the captured
environment baseline, the Phase 13A Python preflight (28/28), a native ARM64
build and CTest, `file`-verified ARM64 binaries and a direct C test exit code of
0. Then ≥300 synthetic JPEG frames through the production TCP path plus a
≥1000-cycle command/ACK stress with ≥990 valid ACKs. **Command/ACK-only
execution is not sufficient — the frame path must execute.**

**Gate C — CARLA closed loop.** Real CARLA 0.9.16 + real Jetson + C Virtual
Safety MCU, ≥300 camera frames, at least one C-accepted non-SAFE_STOP
diagnostic control applied to CARLA, a bounded lockstep run, a short realtime
stale-command test and an observed SAFE_STOP on a fault/timeout path.

| Status | Meaning |
| --- | --- |
| **Prepared** | Source implementation and local loopback gates passed; real Jetson transport and CARLA closed loop not completed. |
| **Transport Pass** | Real Jetson frame/command/ACK transport and C Virtual Safety MCU gates passed; CARLA closed loop not completed. |
| **Pass** | Real Jetson processed simulated CARLA frames, emitted unchanged Phase 13A packets, received C MCU ACK/REJECT responses and closed the loop into CARLA virtual actuation. |
| **Blocked** | A required gate did not pass. |

Prepared and Transport Pass are never inflated into a full Pass.

Blocker classifications: `jetson_unreachable`, `ssh_noninteractive_unavailable`,
`git_sha_mismatch`, `jetson_environment_mismatch`, `jetson_dependency_missing`,
`windows_dependency_missing`, `jpeg_codec_unavailable`,
`phase13a_preflight_failed`, `arm64_ctest_failed`, `frame_transport_failed`,
`clock_sync_failed`, `virtual_mcu_ffi_failed`, `command_transport_failed`,
`ack_transport_failed`, `windows_firewall_or_port_blocked`,
`jetson_firewall_or_port_blocked`, `carla_server_unreachable`,
`carla_setup_failed`, `closed_loop_timeout`, `metrics_missing`,
`unknown_blocker`.

---

## 13. Jetson resource and thermal telemetry

Collected read-only from `tegrastats`, `/proc` and `/sys`. `psutil` is used only
if already installed (it is not in the Jetson venv, so the standard-library
path is the normal one). nvpmodel, clocks, JetPack, the kernel and the thermal
policy are never modified.

Recorded: `tegrastats_sample_count`, `ram_used_bytes`, `ram_available_bytes`,
`swap_used_bytes`, `cpu_utilization_percent`, `gr3d_gpu_utilization_percent`,
`cpu_temperature_c`, `gpu_temperature_c`, `soc_temperature_c`,
`cpu_frequency_hz`, `gpu_frequency_hz`, `thermal_throttling_observed`,
`jetson_process_rss_bytes`, `jetson_process_thread_count`,
`jetson_process_fd_count`. At least 5 valid samples are required for Gate B and
formal Gate C.

**Power:** the reComputer J4012 `tegrastats` output on this board carries no
`VDD_*` rail fields, so `power_measurement_available = false` and
`power_metrics = null`. Power is never inferred from utilisation.

---

## 14. Evidence and SHA semantics

One `run_id` is generated on the PC and passed to the Jetson.

PC: `experiments/phase13/<run-id>/` with `manifest.json`, `summary.json`,
`events.jsonl`, `pc_metrics.json`, `jetson_metrics.json`,
`network_metrics.json`, `fault_matrix.json`, `fault_matrix.csv`,
`commands.txt`, `environment.json`, `README.md`, `raw_outputs/`.

Jetson: `experiments/phase13/<same-run-id>/` with `manifest.json`,
`jetson_metrics.json`, `events.jsonl`, `environment.json`, `commands.txt`,
`README.md`. The control channel returns the final Jetson metrics to the PC so
the PC evidence is self-contained.

Every event carries `timestamp_utc`, `monotonic_us`,
`source ∈ {pc, jetson, virtual_mcu}`, `run_id`, `event_type`, plus `sequence`
and `frame_id` where applicable, and `details`.

SHA fields: `runtime_pc_git_sha`, `runtime_jetson_git_sha`,
`runtime_git_sha_match`, `final_source_head_sha`,
`runtime_code_changed_after_runtime`. A docs-only commit after runtime keeps
`runtime_code_changed_after_runtime = false` and records both SHAs; a runtime
code change after runtime sets it `true` and requires the affected gate to be
re-run at the new exact SHA.

**Generated evidence stays ignored, local and uncommitted.** Raw runtime
evidence, Jetson logs, CARLA logs, packet dumps and compiled FFI binaries are
never committed. The FFI build tree lives at
`experiments/phase13/_ffi_build/`, which `.gitignore` already covers.

---

## 15. Operation

Detect the real PC source address first (do not assume `192.168.55.100`):

```powershell
Find-NetRoute -RemoteIPAddress 192.168.55.1 | Select-Object -First 1 IPAddress
```

Jetson node:

```bash
cd /home/myjetsonnx/Face_Detect_Realtime
git fetch origin
git checkout codex/phase-11o-source-commit-boundary
git pull --ff-only origin codex/phase-11o-source-commit-boundary
git status --short
git rev-parse HEAD
source /home/myjetsonnx/venvs/ma-vlna/bin/activate
python scripts/run_phase13b_jetson_node.py \
  --run-id <RUN_ID> \
  --bind-host 0.0.0.0 \
  --frame-port 13510 \
  --control-port 13513 \
  --pc-host 192.168.55.100 \
  --command-port 13511 \
  --ack-port 13512 \
  --require-real-jetson \
  --run-phase13a-preflight \
  --output-dir experiments/phase13
```

Gate A (PC, no Jetson, no CARLA):

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe scripts\run_phase13b_loopback_checks.py
```

Gate B (PC, real Jetson):

```powershell
D:\CARLA\envs\ma-vlna-carla312\python.exe `
  scripts\run_phase13b_jil_checks.py `
  --run-id <RUN_ID> --jetson-host 192.168.55.1 `
  --frame-port 13510 --control-port 13513 `
  --command-port 13511 --ack-port 13512 `
  --synthetic-frames 300 --command-ack-cycles 1000 `
  --require-real-jetson --output-dir experiments\phase13
```

Gate C (PC, real CARLA + real Jetson):

```powershell
$env:CARLA_ROOT = "D:\CARLA\packages\CARLA_0.9.16"
D:\CARLA\envs\ma-vlna-carla312\python.exe `
  scripts\run_phase13b_simulation_host.py `
  --run-id <RUN_ID> --carla-host 127.0.0.1 --carla-port 2000 `
  --jetson-host 192.168.55.1 `
  --frame-port 13510 --control-port 13513 `
  --command-port 13511 --ack-port 13512 `
  --mode lockstep --frames 300 --fixed-delta-seconds 0.05 `
  --camera-width 640 --camera-height 360 --camera-fps 10 `
  --map-load-mode reuse_or_load --setup-timeout-sec 180 --warmup-ticks 20 `
  --require-server --require-jetson --output-dir experiments\phase13
```

All hosts and ports are CLI-configurable.

### Firewall

Phase 13B **generates but never executes** firewall commands, and never
modifies Windows ICS or the Jetson firewall. The PC command listener is the
only inbound rule normally required:

```
netsh advfirewall firewall add rule name="MA-VLNA Phase13B command UDP 13511" dir=in action=allow protocol=UDP localport=13511
```

The frame (TCP 13510), control (TCP 13513) and ACK (UDP 13512) listeners run on
the Jetson. If a port is blocked, the exact host/port/protocol is recorded, the
run is classified `windows_firewall_or_port_blocked` or
`jetson_firewall_or_port_blocked`, and the required operator command is printed.

### Remote process safety

The node runs with a run-specific PID and log path
(`/tmp/ma-vlna-phase13b-<run-id>.pid` / `.log`); only that exact PID is
stopped. `pkill python` and `taskkill /IM python.exe /F` are never used. No
password is requested or stored, no SSH key is stored, passwordless sudo is
never enabled, and no Jetson dependency is installed automatically.

---

## 16. Validation

Windows source validation:

```
python -m py_compile <all new or modified Python files>
python -m unittest discover -s scripts/tests -p "test_phase13b_*.py"
python scripts\run_phase13b_loopback_checks.py
python scripts\run_phase13a_embedded_contract_sil.py --output-dir experiments\phase13
python scripts\run_phase11_carla_checks.py
python scripts\run_demo_checks.py
git diff --check
python scripts\run_phase11o_source_commit_checks.py --require-staged
```

C targets (both the Phase 13A static library and the Phase 13B shared library):

```
cmake -S embedded -B <build-dir>
cmake --build <build-dir>
cd <build-dir> && ctest --output-on-failure
```

CMake 3.16 on JetPack 5 has no `ctest --test-dir`, so CTest is always run from
inside the build directory. The Phase 13A test (`phase13a_safety_mcu_tests`)
still passes; Phase 13B adds `phase13b_safety_mcu_ffi_tests`, so the suite is
now 2 tests rather than 1.

Regression contract: Phase 13A protocol unchanged, Phase 13A SIL 28/28
unchanged, command packet still 64 bytes with CRC over bytes 0..59, existing C
tests still passing, demo checks still passing, benchmark boundary fields still
`false`.

---

## 17. Full Pass conditions

```
real_jetson_detected = true
jetson_arch = aarch64
runtime_pc_git_sha == runtime_jetson_git_sha
phase13a_python_preflight_passed = true
phase13a_arm64_ctest_passed = true
phase13a_arm64_binary_verified = true
phase13a_arm64_direct_test_exit_code = 0
clock_sync_valid = true and clock_uncertainty_us <= 5000
gate_a_loopback_passed = true
gate_b_frames_sent >= 300, gate_b_frames_received >= 300
gate_b_frames_decoded > 0, gate_b_frames_processed > 0
gate_b_max_mailbox_depth == 1
gate_b_transport_packets_sent >= 1000, gate_b_valid_acks_received >= 990
gate_b_command_accept_count > 0, gate_b_fault_matrix_passed = true
gate_b_false_accept_count == 0, gate_b_false_reject_count == 0
gate_c_carla_frames_sent >= 300, gate_c_carla_frames_processed >= 300
gate_c_command_accept_count > 0
gate_c_virtual_actuator_control_applied_count > 0
gate_c_virtual_actuator_active_control_applied_count > 0
gate_c_virtual_actuator_safe_stop_applied_count > 0
gate_c_lockstep_passed = true, gate_c_realtime_stale_gate_passed = true
crc/stale/sequence/lease/heartbeat/range/frame-crc fault cases all passed
false_accept_count == 0, false_reject_count == 0
physical_actuator_control_executed = false
physical_camera_verified = false
real_mcu_verified = false
full_hil_verified = false
tensorrt_inference_verified = false
route_benchmark_verified = false
infraction_benchmark_verified = false
leaderboard_evaluated = false
```

`goal_reached` and `route_completion` are **not** required: Phase 13B measures
the bridge, not navigation quality.

---

## 18. Runtime results — executed 2026-08-11

`runtime_pc_git_sha = runtime_jetson_git_sha = a05e22f60848d6cc25dc17866e322b9f638ee6db`
(`runtime_git_sha_match = true`, `runtime_code_changed_after_runtime = false`)

**Status: `Phase 13B-JETSON-IN-THE-LOOP-BRIDGE Pass`.**

### Gate A — local loopback (Prepared)

Unit suites 83/83; portable C configure/build/CTest 2/2; loopback session over
the production TCP/UDP transports with the real `run_phase13b_jetson_node.py`
process as the PC-local substitute; fault matrix 28/28; `max_mailbox_depth == 1`;
no buffer leak.

### Gate B — real Jetson transport (Transport Pass)

Evidence: `experiments\phase13\phase13b-20260811T145056Z`

| Metric | Value |
| --- | --- |
| `real_jetson_detected` / `jetson_arch` | `true` / `aarch64` |
| Device tree model | NVIDIA Orin NX Developer Kit |
| L4T | R35 rev 5.0, GCID 35550185, EABI aarch64 |
| Phase 13A Python preflight | 28/28 |
| ARM64 CTest | 2/2 (`phase13a_safety_mcu_tests`, `phase13b_safety_mcu_ffi_tests`) |
| ARM64 binaries verified by `file` | ELF 64-bit LSB, ARM aarch64 |
| Direct C test exit code | 0 |
| `gate_b_frames_sent` / `received` / `decoded` / `processed` | 300 / 306 / 305 / 305 |
| `gate_b_max_mailbox_depth` | 1 |
| `gate_b_transport_packets_sent` | 1319 |
| `gate_b_valid_acks_received` | 1314 |
| `gate_b_command_accept_count` / `reject_count` | 1311 / 7 |
| `gate_b_fault_matrix_passed` | true (28/28) |
| `false_accept_count` / `false_reject_count` | 0 / 0 |
| `clock_uncertainty_us` / `clock_rtt_us` | 392 / 788 |
| `clock_valid_sample_count` / `clock_sample_count` | 40 / 40 |
| `frame_age_ms` p50 / p95 / p99 | 1.421 / 1.766 / 2.554 |
| `frame_one_way_latency_ms_mean` | 1.513 |
| `command_rtt_ms_mean` | 2.089 |

The six frames above the 300 sent are the deterministic fault-matrix
injections; the mismatch between 306 received and 305 decoded is the injected
payload-CRC corruption, rejected before decode exactly as designed.

### Gate C — CARLA closed loop (Pass)

Evidence: `experiments\phase13\phase13b-20260811T145709Z-gatec`

| Metric | Value |
| --- | --- |
| CARLA map / reused | `Carla/Maps/Town03` / true |
| `fixed_delta_seconds` / simulator frequency | 0.05 / 20 Hz |
| `camera_fps` / `sensor_tick` / ticks per camera frame | 10 / 0.10 s / **2.0** |
| `gate_c_carla_frames_sent` / `processed` | 300 / 305 |
| CARLA ticks executed | 600 |
| Frames with a matched command | 300 |
| Command timeouts | 0 |
| `gate_c_command_accept_count` / `reject_count` | 311 / 7 |
| `gate_c_virtual_actuator_control_applied_count` | 610 |
| `gate_c_virtual_actuator_active_control_applied_count` | 598 |
| `gate_c_virtual_actuator_safe_stop_applied_count` | 12 |
| `gate_c_lockstep_passed` | true |
| `gate_c_realtime_stale_gate_passed` | true |
| `gate_c_fault_matrix_passed` | true (28/28) |
| `false_accept_count` / `false_reject_count` | 0 / 0 |
| `clock_uncertainty_us` / valid samples | 477 / 40 of 40 |
| `max_mailbox_depth` / overwrite count / buffer leak | 1 / 0 / false |

600 ticks produced exactly 300 camera frames, confirming the documented
one-frame-per-two-ticks relationship in practice.

### Real Jetson resource and thermal telemetry

| Metric | Gate B | Gate C |
| --- | --- | --- |
| `tegrastats_sample_count` | 46 | 66 |
| `cpu_temperature_c` | 50.94 | 50.94 |
| `gpu_temperature_c` | 49.09 | 49.22 |
| `soc_temperature_c` | 51.38 | 51.59 |
| `cpu_utilization_percent` | 0.75 | 0.75 |
| `gr3d_gpu_utilization_percent` | 0.0 | 0.0 |
| `ram_used_bytes` | 1 128 267 776 | 1 126 170 624 |
| `swap_used_bytes` | 0 | 0 |
| `cpu_frequency_hz` / `gpu_frequency_hz` | 729 MHz / 115.2 MHz | 729 MHz / 115.2 MHz |
| `thermal_throttling_observed` | false | false |
| `jetson_process_rss_bytes` | 194 551 808 | 194 113 536 |
| `jetson_process_thread_count` / `fd_count` | 3 / 12 | 3 / 12 |
| `power_measurement_available` | false | false |

GR3D utilisation is 0 % because Phase 13B is dummy-perception only; nothing is
dispatched to the GPU. `power_measurement_available=false` because the
reComputer J4012 `tegrastats` output carries no `VDD_*` rail fields on this
board — power is never inferred from utilisation.

### Two defects found and fixed by real hardware

Both were invisible to Gate A and only appeared against the real Jetson:

1. **ACK stream desynchronisation.** After a single ACK timeout the stale
   datagram stayed queued and every later command read the *previous*
   command's ACK. It surfaced as fault case F06 (wrong lease) reporting
   `STALE_REJECT` — in fact F05's ACK. Fixed by draining the ACK socket
   immediately before each send.
2. **Clock resolution.** `clock_uncertainty_us` measured 7497 then 7999 against
   a 5000 us budget, while ICMP RTT over the same link is 0–1 ms. On Windows
   before Python 3.13, `time.monotonic()` is `GetTickCount64`-backed with a
   15.625 ms granularity — coarser than the whole budget — so every probe
   quantised to a 0 us or 15625 us round trip. Fixed by taking every Phase 13B
   timestamp from `time.perf_counter_ns` (100 ns on Windows, 1 ns on the
   Jetson), with regression tests that fail if the resolution ever regresses.

### Explicit boundary for this run

Allowed and evidenced: real Jetson frame processing executed; real Jetson
Linux, network and resource behaviour measured; unchanged Phase 13A packets
traversed the network; the C Virtual Safety MCU validated commands; accepted
commands controlled only the virtual CARLA actuator; the Jetson-in-the-loop
closed loop was verified.

Not claimed and not evidenced: full HIL, real MCU, real S32K344, real CAN/UART
timing, physical camera, physical actuator, TensorRT deployment or inference
benchmark, perception accuracy, navigation quality, route completion, CARLA
Leaderboard, infraction benchmark, physical vehicle deployment.
