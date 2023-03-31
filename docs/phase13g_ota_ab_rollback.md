# Phase 13G — Application-level A/B deployment, rollback and version compatibility

Status: **Pass** (Gates A-E complete on the physical Jetson Orin NX 16 GB).

Final runtime/package source SHA:
`315432ae1894f6c4e023c1e350445e3a4ec44fd2`.

The final source regression ran 670 tests with zero skips and all 16 mandatory
Phase 13G scenarios covered.

This phase gives the Jetson node an A/B release mechanism: a commit becomes an
immutable release, releases are activated by an atomic symlink switch, an
activation that cannot prove itself is rolled back automatically, and an update
interrupted by power loss is resolved deterministically on the next boot.

## What this phase is not

Stated first, because the mechanism resembles things it deliberately is not:

| Not provided | Why it is absent |
|---|---|
| Bootloader A/B, rootfs or kernel OTA | This switches an application directory. The bootloader, kernel and rootfs are untouched. |
| Secure Boot | Nothing verifies a chain of trust at power-on. |
| Signed artifacts, publisher identity | A package carries a SHA-256, not a signature. Anyone who can write the package can write the manifest beside it. |
| Anti-rollback security | Rollback is a *recovery* feature here. Nothing prevents deliberately activating an older release. |

**What is provided: SHA-256 integrity and version compatibility.** Authenticity
is Phase 13H.

Also not claimed, unchanged from earlier phases: full HIL, real MCU/CAN/UART,
physical camera or actuator, model accuracy, physical deployment.

## Layout

```
/opt/ma-vlna/
├── releases/<release-id>/     immutable after installation
├── current          -> releases/<active>
├── previous         -> releases/<previous>
├── last-known-good  -> releases/<confirmed>
├── staging/
└── state/           deployment.json, service.env
```

After activation the node runs from `/opt/ma-vlna/current`, never from a git
checkout. That distinction is the point of the phase: a checkout is mutable, so
`git pull` rewrites a running service's code and the SHA validated at startup
stops describing what is on disk. A release is read-only after install and
`current` is switched atomically, so "what is running" has exactly one answer at
every instant.

## The atomic switch

A symlink cannot be edited in place. The switch creates a uniquely named
temporary symlink beside the target and `os.rename`s it onto the target name.
`rename(2)` within a directory is atomic, so every observer — and every crash —
sees either the old release or the new one.

The obvious wrong version is `unlink` then `symlink`. It works almost always and
leaves no `current` at all if the process dies between the two calls. That
window is precisely what a functional test never reproduces and a power cut
eventually finds.

It is therefore tested by observation rather than by inspection: a thread reads
`current` continuously while the main thread performs 40 switches, and the test
asserts the link never resolved to `None` and never to anything but the two
releases involved.

## Compatibility model

Checked at validate time, before anything is switched. The asymmetry is
deliberate:

| Field | Rule |
|---|---|
| `protocol_version`, `command_packet_size`, `command_crc_coverage`, `jilf_*`, `jila_*` | **Exact match.** Frozen by Phase 13A/13B; a mismatch cannot reach the MCU safely. |
| `required_l4t`, `required_cuda`, `required_tensorrt`, `required_jetpack` | **Floors.** The observed version must be at least the required one. |
| `required_python`, `required_arch` | Exact. |
| Unknown observed version | **Fails.** An unreadable version is not a satisfied one. |
| `int8_authority_allowed` | Must be `false`. Refused at manifest construction, not merely at validation. |

A compatibility check is never weakened to produce a pass. Gate B exercises five
negative cases and requires each to be rejected with the right classification.

## State machine

```
IDLE → STAGED → VALIDATED → ACTIVATING → PROBATION → CONFIRMED
                                 ↓            ↓
                            ROLLING_BACK → ROLLED_BACK
                                 ↓
                              FAILED
```

State is persisted atomically (tempfile → `fsync` → `os.replace` → directory
`fsync`). A corrupt state file resolves to `FAILED`, not `IDLE`: an unreadable
state is not a clean one.

`ACTIVATING` and `PROBATION` are the unconfirmed states. Combined with
`ROLLING_BACK` they are fail-closed for AI authority — a node in transition does
not hold command authority.

Defaults: `ready_timeout_sec=120`, `probation_sec=300`, `rollback_timeout_sec=120`.

## Boot recovery

`ma-vlna-deploy-resume.service` is a one-shot ordered `Before` the node service.
On every boot it asks the deployment manager what an interrupted update should
do. The default for an unconfirmed activation is rollback to last-known-good,
because an activation that could not finish is not evidence that the candidate
works.

Ordering matters: were it to run after the node, the node would start from
whatever `current` happened to be and then be switched underneath itself — the
silent promotion the unit exists to prevent. The renderer refuses a unit that
lacks the `Before` ordering.

## Two design points found before Gate C, not during it

Both would have failed Gate C on its first command, and both would have looked
like a bad candidate rather than a bad mechanism.

### The expected-SHA environment layer

The node validates at startup that its code is the commit it was told to expect.
In Phase 13F that expectation was a single SHA pinned in the root-owned
`/etc/ma-vlna/jetson-node.env` — correct when one checkout ran forever.

It cannot survive releases. Each release carries its own `source_git_sha`, so a
single pinned value lets at most one release start; every other activation fails
preflight, never reaches READY, and is auto-rolled back with the candidate
blamed. Repinning `/etc` per activation would require `sudo` per update, which
would defeat A/B deployment entirely.

The unit therefore layers a second environment file:

```
EnvironmentFile=/etc/ma-vlna/jetson-node.env
EnvironmentFile=-/opt/ma-vlna/state/service.env
```

systemd applies these in order, so the deployment-owned layer wins. It is
written without privilege, renamed into place after `fsync` (systemd parses
whatever is present at unit start, so a half-written file would be read as
truth), and published at **both** switch points before the restart — activation
and rollback alike. A rollback that republished nothing would start the recovery
target expecting the failed candidate's commit and turn a recoverable rollback
into `FAILED`.

Ordering is verified by observation, not assertion: the test double samples the
environment file at the moment of restart and the tests check what the restart
actually saw.

Because the layer is optional (`-` prefix), the first start after Gate B — where
nothing has been activated — would fall through to the `/etc` pin. Hence
`publish-env`, which writes the layer for whatever `current` already is. It is
idempotent and needs no privilege, and it is step 6 of the Gate C sequence.

**This is not a security boundary.** The service user can write this file and
already runs the code it describes. Integrity rests on the SHA-256 values in the
release manifest.

### The startup manifest is referenced, not packaged

Release `relB` was found carrying `config/phase13f_service_manifest.json` with
`repository_sha = dabbbaba…` (the frozen Phase 13F runtime pin) inside a release
whose own `source_git_sha` was a later commit — two contradictory answers to
"which commit is this?" in one immutable directory.

That file is generated on the target and pins an absolute engine path. It is
host state, which is why it is gitignored rather than committed. The rule the
phase already states covers it: a release contains repository-owned files and
*references* to external assets. The release manifest already records
`engine_manifest_path` and `engine_manifest_sha256`, so it is referenced by path
and hash — the same treatment as the 52 MB engine, which is likewise never
copied per release.

Drift is therefore detected at validate time rather than discovered at start
time. The renderer refuses a unit whose `--manifest` points inside the release
root, so this cannot return by editing the template.

## Gate A — Prepared

150 tests, **zero skipped on the Jetson** (55 skip on Windows, which has no
symlinks without Developer Mode; they run on the target).

All 16 mandatory scenarios are covered and mapped to named tests by
`scripts/run_phase13g_checks.py`. Notable coverage:

- atomic switch observed across 40 concurrent switches
- release immutability, partial-install detection, path/link traversal guards
- cleanup protections: `current`/`previous`/`last-known-good` are never removed,
  and never fewer than two releases are retained
- compatibility matrix including exact/floor/unknown-version cases
- secret scan in both directions
- systemd unit contract, with every refusal proven by mutating the rendered unit

## Gate B — Staging Pass

Run `phase13g-gate-b`, source `47f7373366ef669f72c8749f00caa0a4ff4e2a8a`.

```
release A  relA-20260814082659  sha256 bac39a0a1e6981a2  599453 bytes  159 files
release B  relB-20260814082659  sha256 079fc741c632ab86  599477 bytes  159 files
           22 compatibility checks, 0 failures each
store      current=relA  last-known-good=relA  releases=7  partial=0
```

Negative cases, all rejected with the expected classification:

| Case | Classification |
|---|---|
| `package_hash_mismatch` | `package_hash_mismatch` |
| `engine_hash_mismatch` | `candidate_incompatible` |
| `int8_authority_requested` | `manifest_int8_authority_forbidden` |
| `protocol_mismatch` | `candidate_incompatible` |
| `source_sha_mismatch` | `candidate_incompatible` |

Production authority was **not** switched, which is the safety property Gate B
exists to demonstrate:

```
service before: active/running pid=1139
service after : active/running pid=1139  unchanged=True  runs_from_release=False
production_authority_switched=False
```

### Packaging provenance

The packager refuses to build unless the package will match `source_git_sha`.
That is narrower than "the worktree is pristine", and the distinction is
load-bearing: Gate B was first blocked by an untracked `Testing/` directory
(CTest output at the repository root) that no packaging rule could ever reach.

| Condition | Result |
|---|---|
| Tracked file modified, staged or deleted (anywhere) | **Refuse** — the commit no longer describes the tree |
| Untracked file inside a packaged tree | **Refuse** — whole directories are copied, so it would ship |
| Untracked file outside the packaged trees | Record and proceed — it cannot enter the package |
| Not a git repository | **Refuse** — unverifiable provenance is not clean provenance |

All three categories appear in the packager's JSON output either way.

### Pre-Gate-C dry run

The node's own preflight was run from the release, non-privileged, with exactly
the arguments the unit passes:

```
preflight_passed      : False
failed_required_checks: ['port_available_control', 'port_available_frame']
repository_sha_match  : expected 47f73733… observed 47f73733…  PASSED
manifest_loadable     : PASSED
engine_hash_match     : PASSED
```

The two failures are the ports held by the still-running Phase 13F service
(PID 1139); Gate C stops it at step 3. All 15 other required checks pass,
including both checks that the two design fixes above address. The running
service was not stopped to obtain this evidence, because that would change
production authority without approval.

## Gate C — Activation Pass

Gate C was executed on the physical Jetson using the release-managed systemd
unit.

The original Gate C release pair was:


release A relA-20260814082659
release B relB-20260814082659
source 47f7373366ef669f72c8749f00caa0a4ff4e2a8a


A -> B activation passed:

- atomic `current` switch by symlink + rename
- per-release expected-SHA environment published before restart
- candidate reached READY
- FP16 remained the only production command authority
- engine hash matched
- preflight passed
- probation completed for approximately 302 s with no observed service restart
- B was confirmed as `last-known-good`

The health payload's legacy `repository_sha` field continued to reflect the
external Phase 13F startup manifest. The authoritative release expectation is
the per-release `MA_VLNA_EXPECTED_SHA`; startup preflight passed against that
value. This is an observability ambiguity, not a failed activation.

## Gate D — Rollback Pass

Both rollback paths were exercised on the physical Jetson.

**Manual rollback:** B -> A completed successfully. The release symlink and
environment layer both returned to A, the node returned to READY, FP16 authority
was restored, and the engine hash and startup preflight remained valid.

**Automatic rollback:** the exact node PID was killed during B probation. The
deployment manager observed `state_left_ready`, classified the candidate
activation as `probation_failed`, entered `ROLLING_BACK`, restored A and its
environment layer, and completed in `ROLLED_BACK`.

No broad process kill such as `pkill` was used.

## Gate E — Reboot Recovery Pass

Gate E was repeated with fixed releases built from:


runtime/package SHA 315432ae1894f6c4e023c1e350445e3a4ec44fd2
A2 relA2-20230331003500
B2 relB2-20230331003500


Both packages reported `package_matches_commit=true`.

### Cycle 1 — reboot with B2 only staged

Before reboot:


current = A2
last-known-good = A2
candidate = B2
state = STAGED
switch_completed = false


Boot IDs proved a real reboot:


before 39d36f00-25f1-4d28-93ca-5f069bc7e0c5
after b9861ab2-4778-4bbe-9e7e-d537a17d7e14


Boot recovery selected `discard_candidate`, returned the deployment state to
`IDLE`, and left both `current` and `last-known-good` on A2.

The node then reached:


state = READY
precision = fp16
preflight_passed = true
ai_authority_permitted = true
NRestarts = 0
boot_to_active_sec = 26.638679


Cycle 1 therefore passed the 120 s boot readiness limit.

### Cycle 2 — reboot during B2 probation

B2 was validated and activated while A2 remained last-known-good. The system was
rebooted while deployment state was `PROBATION`.

Boot IDs again proved a real reboot:


before b9861ab2-4778-4bbe-9e7e-d537a17d7e14
after 18adbe68-bacb-489d-91dc-6ccf0924bf91


Recovery observed:


state_found = PROBATION
action = rollback_to_last_known_good
target = A2


It atomically switched `current` from B2 to A2, republished A2's expected SHA,
and completed:


operation = rollback_for_boot
service_restart_deferred = true
ready_check_deferred = true
deployment_state = ROLLED_BACK


The resume unit completed with:


Result = success
ExecMainStatus = 0
ActiveState = active
SubState = exited


After the resume one-shot exited, systemd started the node normally from A2:


current = A2
last-known-good = A2
environment/current = agree
expected SHA = 315432ae1894f6c4e023c1e350445e3a4ec44fd2
state = READY
precision = fp16
preflight_passed = true
ai_authority_permitted = true
NRestarts = 0
boot_to_active_sec = 26.412298


Cycle 2 therefore passed the 120 s boot readiness limit.

### Boot-resume deadlock found and fixed during Gate E

The first Cycle 2 attempt exposed a real systemd ordering defect.

`ma-vlna-deploy-resume.service` is ordered `Before=` the node service, but the
original boot recovery reused the normal runtime `rollback()` implementation.
That implementation synchronously executed:


sudo systemctl restart ma-vlna-jetson-node.service


The resume process therefore waited for the node service while systemd kept the
node start job waiting for the `Before=` resume unit to finish: a dependency
deadlock.

The fix separates boot recovery from runtime rollback. `rollback_for_boot()`
performs only the operations that must happen before the node starts:

1. enter `ROLLING_BACK`
2. atomically restore `current`
3. publish the target release environment
4. enter `ROLLED_BACK`
5. return successfully without restarting or waiting for the node

systemd then continues its existing boot transaction and starts the selected
release after the resume unit exits.

The same no-restart rule is used if a resumed probation subsequently fails.

Regression coverage includes seven interruption-recovery tests. Final target
regression:


mandatory_scenarios=16 covered=True
tests_run=670
skipped=0
passed=True
store_scenarios_exercised=True


The repaired Cycle 2 journal contains `rollback_for_boot`,
`service_restart_deferred=true` and `boot_rollback_prepared`, with no nested
`sudo` or `systemctl restart` invocation.

**Gate E result: PASS. The boot-resume deadlock fix was verified by real reboot
on the physical Jetson.**


## Operational notes

- Cleanup keeps at least two releases and never deletes `current`, `previous` or
  `last-known-good`, whatever `--keep` is set to.
- Releases are read-only after installation. That guards against accident, not
  against an attacker — anyone who can write the store can `chmod` it back.
- The engine is referenced, never copied. It is 52 MB and identical across
  releases; duplicating it would turn a 2 MB update into a 54 MB one and add a
  second copy that can drift from the one the manifest hashes.

## Next phase

`Phase 13H-SIGNED-ARTIFACT-SECURE-BOOT-ANTI-ROLLBACK`
