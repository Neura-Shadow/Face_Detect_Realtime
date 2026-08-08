# Phase 13A-EMBEDDED-CONTRACT-SIL

## Status

```text
Phase 13A-EMBEDDED-CONTRACT-SIL Pass — command protocol, Safety MCU state machine, range-shift rejection, stale-command rejection, and host SIL tests passed.
```

Authoritative local evidence:

```text
experiments\phase13\20260808T065044Z
```

This phase adds an embedded-oriented host software-in-the-loop vertical slice:

```text
synthetic camera frame
-> EdgePerception (dummy)
-> Input/Activation RangeShiftMonitor
-> MA-VLNA SafetyGate
-> EmbeddedCommandBridge
-> 64-byte bounded command packet
-> Safety MCU software emulator / portable C reference
-> ACK, reject, FSM, watchdog telemetry
```

It does not alter or reinterpret any Phase 12D experiment result.

## Command Contract

The authoritative machine-readable layout is
`embedded/protocol/command_contract.json`. The matching C definition is
`embedded/protocol/command_protocol.h`; the Python implementation is
`workers/core/embedded_command_bridge.py`.

| Property | Value |
|---|---:|
| Protocol version | `1` |
| Packet size | `64 bytes` |
| Endian | little-endian |
| Packing | packed, no implicit padding |
| RX bound | exactly `64 bytes` |
| CRC | CRC-32/ISO-HDLC over bytes `0..59` |
| CRC field | bytes `60..63` |
| Dynamic allocation in C reference | none |

Control values use fixed-width Q15-style integers. Steering maps signed
`[-32767, 32767]` to `[-1, 1]`; throttle, brake, and AI confidence map
`[0, 32767]` to `[0, 1]`. Reserved fields must remain zero for version 1.

The parser rejects invalid packet length, CRC, protocol version, validity
window, duplicate or out-of-order sequence, command lease, control range, and
invalid receive state. AI ACTIVE authority additionally requires
`range_shift_state=VALID`.

## Safety MCU FSM

The reference FSM states are:

```text
BOOT -> STANDBY -> READY -> ACTIVE
                    |         |
                    +-> DEGRADED
                    |         |
                    +------> FAILSAFE

FAILSAFE -- explicit clear --> STANDBY
```

All transitions are checked by `safety_fsm_can_transition`. Invalid transitions
are denied. Heartbeat timeout, repeated range rejection, and explicit safety
faults can enter FAILSAFE. Watchdog servicing is allowed only in READY, ACTIVE,
or DEGRADED; it is denied in BOOT, STANDBY, and FAILSAFE.

Command lease expiry and `valid_until_us` are independent gates. Clearing
FAILSAFE resets sequence tracking and requires explicit re-arm before a command
can become ACTIVE again.

## Range Contract

`RangeShiftMonitor` checks these deployment-facing fields:

- `source_pixel_format`, `model_color_order`, `input_dtype`, `input_layout`
- `raw_input_min/max`, `normalized_min/max`
- `channel_mean_bounds`, `channel_std_bounds`
- `selected_activation_percentile_bounds`
- `max_saturation_ratio`, `max_result_age_ms`

It distinguishes these states:

- `input_range_shift`
- `normalization_mismatch`
- `color_order_mismatch`
- `nan_or_inf`
- `activation_range_shift`
- `quantization_saturation`
- `output_range_invalid`
- `recovery_pending`

Any failure invalidates the current AI result. The bridge emits a bounded
SAFE_STOP packet (`steering=0`, `throttle=0`, `brake=1`) instead of ACTIVE AI
authority. The MCU accepts the safe command, records a range rejection, enters
DEGRADED, and enters FAILSAFE after three consecutive range failures. Recovery
requires three consecutive valid samples and explicit MCU fault recovery.

The default numerical bounds are deterministic SIL defaults, not model
calibration claims. A deployed model must replace them with calibration-derived
values.

## Verification

```powershell
python scripts\run_phase13a_embedded_contract_sil.py --output-dir experiments\phase13
```

```text
sil_tests=28/28
portable_c_build_test_status=passed
portable_c_ctest=1/1 passed
packets_sent=12
packets_accepted=5
crc_reject_count=1
stale_reject_count=1
sequence_reject_count=2
lease_reject_count=1
range_reject_count=3
failsafe_entry_count=2
failsafe_recovery_count=1
false_accept_count=0
false_reject_count=0
```

The portable C test was configured and built with CMake using GCC/MinGW, then
executed with CTest. On a host without a portable C toolchain, the runner records
`skipped_no_portable_c_toolchain` and does not claim a C firmware pass.

Evidence files are `manifest.json`, `summary.json`, `events.jsonl`,
`commands.txt`, and `README.md`. Generated evidence remains local and ignored
under `experiments/phase13/*/`.

## Strict Boundary

This Pass means the versioned host command contract, Python encoder/emulator,
portable C parser/FSM, fault rejection behavior, and host SIL tests passed. It
does not claim:

- real Safety MCU firmware or target-board pass;
- hardware-in-the-loop pass;
- actuator command or vehicle control;
- CARLA or route benchmark;
- model accuracy or range-calibration quality;
- OTA, secure boot, cryptographic authentication, or cybersecurity pass.
