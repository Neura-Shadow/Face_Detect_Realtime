# MA-VLNA — Final Project Status

**Classification: Research Engineering Prototype Complete.**

Not production-ready autonomous driving, not a certified safety-critical
system, not a complete HIL platform, not a production automotive controller,
not a fully autonomous real-world vehicle system. Where this document says
"verified" it means: verified against the specific, narrow claim stated,
against evidence checked directly (git history, live system state, journal
logs, boot IDs, test output) — not against a broader claim the words might
suggest.

Repository: `Neura-Shadow/Face_Detect_Realtime`
Branch: `codex/phase-11o-source-commit-boundary`
Final runtime/package source SHA: `315432ae1894f6c4e023c1e350445e3a4ec44fd2`
Final repository HEAD (documentation-only beyond the runtime SHA):
`2c870baec0253ea9ef990e8ce2d9392031589209`
Pull Request: [#1](https://github.com/Neura-Shadow/Face_Detect_Realtime/pull/1)
— open, draft, unmerged.

## What this system is

A research prototype demonstrating a specific, narrow claim: a Jetson Orin NX
edge compute node can run FP16 TensorRT perception inside a hard-real-time
command-authority loop, guarded by an independent C safety MCU (emulated),
with bounded latency, deterministic fail-closed behavior under fault
injection, a supervised OS-level service lifecycle, and an application-level
A/B release mechanism with automatic rollback. Every phase below states
explicitly what it does **not** claim; those exclusions are load-bearing, not
boilerplate.

## Phase-by-phase final state

### Phase 1–9 — Application scaffold (simulation-only)

Architecture refactor, workers, mock mode, APIs, frontend, Supabase
integration, real webcam capture, edge-perception fallback chain, SafetyGate
regression, VLM reasoner fallback, automated release demo (6/6). No CARLA, no
Jetson, no embedded MCU involvement. Simulation- and workstation-only.

### Phase 10–11 — CARLA simulation integration

CARLA-based closed-loop simulation of the perception → planning →
control chain. Simulated vehicle, simulated sensors, simulated actuation. No
physical hardware.

### Phase 12 — YOLOv9 backend selection

Backend evaluation and selection culminating in the YOLOv9 row used from
Phase 13C onward. Workstation-side, pre-embedded work.

### Phase 13A — Embedded safety contract (SIL, then Jetson-native)

**Passed.** Protocol v1: fixed 64-byte little-endian command packet, CRC
coverage bytes 0–59, range-shift authority gate, portable C Safety MCU
emulator and FSM, 28/28 host software-in-the-loop tests. Revalidated natively
on the physical Jetson Orin NX (aarch64, JetPack 5.1.3, Python 3.8.10):
28/28 Python SIL and the native ARM64 CTest suite passed. Host SIL only — no
real MCU, no HIL, no actuator, no model accuracy, no OTA/security claim.
[docs/phase13a_embedded_contract_sil.md](phase13a_embedded_contract_sil.md)

### Phase 13B — Jetson-in-the-loop bridge

**Pass.** The real Jetson processed 300 simulated CARLA camera frames,
emitted the unchanged Phase 13A 64-byte command packet over USB-gadget
Ethernet, and closed the loop through the C Virtual Safety MCU back into
CARLA virtual actuation: 598 accepted active controls, 12 SAFE_STOPs,
`max_mailbox_depth=1`, clock uncertainty 477 µs, fault matrix 28/28,
`false_accept_count=0`, `false_reject_count=0`.
`validation_type = processor_in_the_loop`: only the Jetson and the
USB-gadget Ethernet link are physical; camera, environment, vehicle, MCU,
actuator and physics are simulated. Perception was still
`DummyPerceptionBackend`. No full HIL, no real MCU/S32K344, no real CAN/UART
timing, no physical camera/actuator, no perception accuracy claim.
[docs/phase13b_jetson_in_the_loop_bridge.md](phase13b_jetson_in_the_loop_bridge.md)

### Phase 13C — TensorRT FP16 edge perception

**Pass.** Replaced the dummy backend with a target-built TensorRT FP16
YOLOv9-c engine (52.8 MB) in the command-authority path, keeping the Phase
13B transport and safety contract byte-for-byte unchanged. Gate C streamed
300/300 frames, 300 commands accepted, 0 rejected. Gate D ran 1200 Town03
ticks: 300 camera frames, 304 inferences, 1197 active controls, 18
SAFE_STOPs, 0 command timeouts, `frame_to_command_ms_p99=99.1` against a
949.6 ms budget. Backend parity against the official YOLOv9 source: matched
rate 1.000, class agreement 1.000, box IoU mean 0.954 — a conversion-fidelity
check, not an accuracy benchmark. Fault matrix 28/28. No mAP, no navigation
quality, no route completion claim.
[docs/phase13c_tensorrt_fp16_edge_perception.md](phase13c_tensorrt_fp16_edge_perception.md)

### Phase 13D — INT8 calibration and range-shift authority

**Complete**, with a documented recovery cycle. INT8 calibration, audit and
range-shift gating were built and gated end to end (dataset capture, target
engine build, benchmark, parity, streamed runtime, CARLA closed loop). A
sensitivity sweep on the Jetson led to **Phase 13D-MP-RECOVERY**: INT8 was
frozen as `experimental_non_authoritative` rather than promoted to command
authority, and FP16 was confirmed as the sole production command-authority
precision going forward. This boundary is unchanged through every later
phase. [docs/phase13d_int8_calibration_range_shift.md](phase13d_int8_calibration_range_shift.md),
[docs/phase13d_mp_recovery.md](phase13d_mp_recovery.md)

### Phase 13E — FP16 continuous soak

**Pass.** Extended continuous-operation soak of the FP16 command-authority
path to establish long-run stability before the reliability work in 13E-R.
[docs/phase13e_fp16_soak.md](phase13e_fp16_soak.md)

### Phase 13E-R — Clock-drift, backpressure and recovery hardening

**Full Pass.** Three goals: (1) bounded periodic clock discipline (least-squares
drift estimate, `guard_us` safety margin, degrade to SAFE_STOP rather than
extend AI_ACTIVE) verified deterministically at ±10/±50 ppm for ≥3 simulated
hours with `issued_future_skew_us≤0` and zero future-timestamp rejects; (2) a
frame producer decoupled from CARLA tick pacing, sustaining ≥10 FPS for
≥300 s against the real JILF pipeline with observable, bounded backpressure
(`mailbox_drop_count>0`, `max_mailbox_depth==1`, no unbounded queue); (3)
removal of unbounded per-frame in-memory accumulation in favor of bounded
online statistics, bounded rings and streamed JSONL, with measured rss/fd/thread
drift per hour. [docs/phase13er_clock_drift_backpressure_recovery.md](phase13er_clock_drift_backpressure_recovery.md)

### Phase 13F — Jetson service supervision and boot recovery

**Boot Pass.** The Jetson FP16 node runs as a supervised Embedded Linux
service: `systemd` `Type=notify` with `sd_notify`/watchdog integration,
versioned startup manifest, dependency/asset preflight, bounded logs,
graceful shutdown, crash/restart backoff with restart-storm protection
(backoff implemented in the supervisor wrapper because the target's systemd
245 predates `RestartSteps`), boot-time recovery, and fail-closed SAFE_STOP
during service loss. Verified through two controlled reboot cycles on the
physical target with readiness within the required 120 s window.
[docs/phase13f_jetson_service_supervision.md](phase13f_jetson_service_supervision.md)

### Phase 13G — OTA A/B, rollback and version compatibility

**Pass — Gates A through E complete on the physical Jetson Orin NX.** See
below; this is the phase this document closes out.

## Phase 13G — what it provides, and does not

**Provides: SHA-256 integrity and version compatibility for an
application-level A/B release mechanism.** A commit becomes an immutable,
read-only release under `/opt/ma-vlna/releases/<id>/`; activation is an
atomic symlink switch (`current -> releases/<id>`, via temp-symlink +
`rename(2)`, never observably absent); an activation that cannot prove
itself (READY within 120 s, then 300 s probation) is rolled back
automatically; a reboot during an unconfirmed update is resolved
deterministically by a boot-resume unit that defaults to rollback.

**Deliberately does not provide, and does not claim:** bootloader A/B,
rootfs or kernel OTA (this switches an application directory only); Secure
Boot; signed artifacts or publisher identity (a package carries a SHA-256,
not a signature — anyone who can write the package can write the manifest
beside it); anti-rollback security (rollback here is a *recovery* feature,
not a protection against deliberately activating an older release). Also
unchanged from earlier phases: no full HIL, no real MCU/CAN/UART, no
physical camera/actuator, no model-accuracy or route-benchmark claim, no
physical vehicle deployment. Authenticity is explicitly out of scope and
deferred — see Future Work.

### Gate results

| Gate | Result | Evidence |
|---|---|---|
| A — Prepared | Pass | 670 tests, 0 skipped, on target; 16/16 mandatory scenarios covered; store scenarios exercised |
| B — Staging Pass | Pass | Two candidate releases packaged, hashed, validated (22 compatibility checks each, 0 failures); 5 negative cases rejected with correct classification; production service untouched (`unchanged=True`) |
| C — Activation Pass | Pass | Release-managed unit installed; node reached READY from a release (not a git checkout); FP16 command authority confirmed |
| D — Rollback Pass | Pass | Both automatic rollback (failed/expired probation) and manual rollback exercised against the real store and the real systemd unit |
| E — Reboot Recovery Pass | Pass | Two real reboot cycles, each proven by a differing kernel boot ID before/after — not merely a state-file check |

### Gate E in detail, because "reboot recovery" is easy to overstate

Two independent reboot cycles were run, each verified by a differing kernel
boot ID (`/proc/sys/kernel/random/boot_id` and `journalctl --list-boots`
before vs. after), not by reasoning about state alone:

- **Cycle 1 — reboot while a candidate was staged, before activation.**
  Boot recovery correctly chose `discard_candidate` ("candidate staged but
  never activated; current is untouched"), left `current`/`last-known-good`
  on the pre-existing release, and the node reached READY with
  `preflight_passed=true`, `ai_authority_permitted=true`,
  `NRestarts=0`, `boot_to_active_sec=26.6`.
- **Cycle 2 — reboot after activation, during the 300 s probation window,
  before confirmation.** Boot recovery correctly chose
  `rollback_to_last_known_good` ("activation was interrupted before
  confirmation; an unconfirmed release is not promoted by a reboot"),
  atomically switched `current` back to the last-known-good release,
  republished its expected SHA, and completed. The node came up on the
  rolled-back release: READY, `preflight_passed=true`,
  `ai_authority_permitted=true`, `NRestarts=0`, `boot_to_active_sec=26.4`.
  Both figures are well inside the 120 s requirement.

**A real defect was found and fixed by this testing, not around it.** The
first attempt at Cycle 2 exposed a genuine systemd ordering deadlock: the
boot-resume unit is ordered `Before=` the node service, but the original
recovery path called the normal runtime `rollback()`, which synchronously
ran `systemctl restart` on the node — a unit the resume process itself
blocks from starting. Boot hung. The fix (`rollback_for_boot`, in
`scripts/run_phase13g_deploy.py`) switches `current`, republishes the
environment layer, and returns without restarting or waiting; systemd
completes the boot transaction and starts the selected release once the
resume unit exits. Verified by both: (a) a regression test asserting
`restart_count == 0` down this path, and (b) the real Cycle 2 reboot above.

### Two other defects found before Gate C ran, not during it

Both would otherwise have failed Gate C's first command and looked like a
bad candidate rather than a mechanism bug:

- **Expected-SHA pinning.** Each release carries its own `source_git_sha`,
  but the unit originally read one SHA pinned in a root-owned `/etc` file —
  correct for Phase 13F's single mutable checkout, wrong once multiple
  releases exist (at most one could ever pass preflight). Fixed with a
  deployment-owned environment layer (`/opt/ma-vlna/state/service.env`),
  written without privilege and applied second so it overrides the `/etc`
  default, published before every restart at both activation and rollback.
- **Startup-manifest identity conflict.** A packaged release was found
  carrying a copy of the Phase 13F startup manifest pinning the frozen
  runtime SHA `dabbbaba…`, inside a release whose own `source_git_sha` was a
  later commit — two answers to "which commit is this" in one directory.
  The manifest is host-generated state; it is now referenced by path and
  SHA-256, like the 52 MB engine, never packaged.

## Simulation-only vs. real-hardware components, summarized

| Component | Status |
|---|---|
| CARLA world, vehicle physics, environment | Simulated throughout |
| Camera | Simulated throughout |
| Jetson Orin NX compute | **Real**, from Phase 13B onward |
| USB-gadget Ethernet transport | **Real**, from Phase 13B onward |
| TensorRT FP16 inference | **Real**, on-target, from Phase 13C onward |
| Safety MCU (S32K344-class FSM) | Portable C emulator throughout — never a physical MCU |
| CAN/UART timing | Not exercised — the link is USB-gadget Ethernet |
| Actuator | Simulated (CARLA) throughout |
| systemd service supervision | **Real**, on-target, from Phase 13F onward |
| A/B release store, atomic switch, rollback | **Real**, on-target, Phase 13G |
| Physical reboot recovery | **Real**, on-target, Phase 13G Gate E (boot-ID verified) |

## Completed major capabilities

- Frozen, byte-exact embedded command protocol with independent C safety
  authority and deterministic fail-closed behavior under 28/28 injected
  faults, reproduced natively on-target.
- Real Jetson TensorRT FP16 inference inside the command-authority loop with
  bounded, measured end-to-end latency.
- INT8 explored and deliberately not promoted — a documented, reversible
  engineering decision, not an oversight.
- Disciplined clock synchronization surviving sustained drift, and a
  perception pipeline that exhibits genuine, bounded, observable backpressure
  rather than either dropping silently or growing without bound.
- A supervised OS service with watchdog integration, bounded logs, and
  verified boot-time recovery.
- An application-level A/B deployment mechanism with an atomic switch proven
  never-absent under concurrent observation, automatic and manual rollback,
  and boot-interrupted-update recovery proven with real, boot-ID-verified
  reboots — including a genuine ordering-deadlock defect found and fixed by
  that testing.

## Unresolved limitations

- No physical camera, actuator, or vehicle has ever been in the loop.
- No real Safety MCU silicon (S32K344 or equivalent) — the FSM is a portable
  C emulator, chosen specifically so its logic ports unchanged to real
  silicon, but that port has not been done.
- No CAN or UART bus timing has been exercised; the physical link is
  USB-gadget Ethernet.
- No model-accuracy, mAP, infraction, or CARLA Leaderboard-style route
  benchmark has been run at any phase.
- INT8 precision is built, calibrated and gated, but frozen as
  `experimental_non_authoritative` — not a production path.
- Phase 13G provides integrity (SHA-256) and compatibility checking, not
  authenticity: no signature, no Secure Boot, no anti-rollback protection.
  Anyone who can write a release package can write its manifest.
- All Phase 13G physical evidence was gathered on a single Jetson unit
  without a battery-backed RTC (visible in this session as system-clock
  values reading 2023 instead of 2026); reboot *occurrence* was verified
  independently via kernel boot IDs, which are clock-independent, but
  wall-clock timestamps in raw logs from that unit should be read as
  relative, not absolute.

## Explicitly unsupported claims

This system does **not** support, and this document does not assert:

- Production-ready autonomous driving.
- A certified safety-critical system (no functional-safety certification of
  any kind — ISO 26262 or otherwise — has been pursued).
- A complete hardware-in-the-loop platform.
- A production automotive controller.
- A fully autonomous real-world vehicle system.
- Cryptographic authenticity, Secure Boot, or anti-rollback security for the
  deployment mechanism (Phase 13G is integrity-and-compatibility only).

## Future Production Hardening (out of scope for this closure)

None of the following are blockers for the status recorded in this
document. They are not part of the current engineering cycle and no
implementation work has been opened for them:

- Signed release artifacts and publisher identity.
- Secure Boot / verified boot chain.
- Hardware anti-rollback (fuse-based or equivalent).
- Key rotation and key revocation.
- Production trust-chain hardening generally (candidate name if opened:
  `Phase 13H-SIGNED-ARTIFACT-SECURE-BOOT-ANTI-ROLLBACK` — not started).
- Physical camera, actuator and MCU integration.
- Formal model-accuracy benchmarking.
- Formal route / infraction benchmarking.
- Any production certification or safety case.

## Operational reference

See [docs/final_runbook.md](final_runbook.md) for restoring and inspecting
the system, and [docs/phase13g_ota_ab_rollback.md](phase13g_ota_ab_rollback.md)
for the full Phase 13G design record and evidence.
