# Phase 13F — Jetson Service Supervision and Boot Recovery

Phase 13E-R proved the FP16 command-authority path holds for two hours when a
person starts it. This phase makes it a service: something that starts itself,
re-establishes what it is on every restart, reports its own health, and fails
closed when it cannot.

Nothing about perception, the model, the protocol or control semantics changes.
The 64-byte Phase 13A packet, JILF/JILA framing, the C Virtual Safety MCU's
authority and the Phase 13E-R clock discipline are all untouched. INT8 remains
`experimental_non_authoritative`.

---

## 1. The target decides the design

The Jetson runs **systemd 245** (Ubuntu 20.04, JetPack R35.5.0, aarch64). That
was checked before anything was written, and it rules out the obvious approach:

| Wanted | systemd 245 | Consequence |
| --- | --- | --- |
| Exponential restart backoff | `RestartSteps` is 254+ | Backoff lives in the wrapper |
| Bounded max backoff | `RestartMaxDelaySec` is 254+ | Same |
| Start-limit directives | present, but in `[Unit]` | Placed there, not in `[Service]` |
| `Type=notify`, `WatchdogSec` | present | Used |
| `RuntimeDirectory` | 211+ | Used |

The unit is validated against a directive-to-first-version table, so a unit
written for a newer systemd is caught before it reaches the target rather than
failing at load time with a message that reads like a broken service.

### Why a wrapper and not the node directly

The node exits cleanly at the end of every PC session. Under
`Restart=on-failure` that ends the service. Under `Restart=always` a genuine
crash-loop becomes indistinguishable from ordinary session churn. The wrapper
keeps the *service* alive across sessions and reports the difference between
"the session ended" and "the node died on start-up" — a distinction systemd
cannot make for us.

It also gives `Type=notify` one process that knows when the thing is genuinely
usable: after preflight, when the node has announced itself. Not when `exec`
returned.

---

## 2. Service contract

```ini
Type=notify              NotifyAccess=main
User=…  Group=…          SupplementaryGroups=video render
WorkingDirectory=…       EnvironmentFile=…
RuntimeDirectory=ma-vlna RuntimeDirectoryMode=0750
WatchdogSec=60           Restart=on-failure   RestartSec=5
StartLimitIntervalSec=600  StartLimitBurst=5     ([Unit])
KillSignal=SIGTERM       KillMode=mixed       TimeoutStopSec=45
```

Secrets and host-specific values live in `EnvironmentFile`, never in the unit
and never shell-expanded onto the command line where they would appear in `ps`
and journald metadata. The validator refuses a unit with a secret-looking
`Environment=` directive.

Hardening is deliberately modest. The node needs `/dev/nvhost*`, the CUDA and
TensorRT stack, and the `l4tbr0` gadget interface; a unit that cannot reach them
is not a safer service, just a broken one.

### sd_notify without a dependency

`python-systemd` needs a compiler and headers on the target, which is not a
thing to add to a Jetson venv for one datagram. The protocol is one `AF_UNIX`
datagram of newline-separated `KEY=value` pairs, implemented directly.

* `NOTIFY_SOCKET` absent → the notifier is inert and every call is a successful
  no-op, so the same wrapper runs under systemd, under a bare shell in Gate B,
  and on Windows in unit tests.
* A leading `@` is the abstract namespace, expressed as a leading NUL.
* Pings go at **half** `WATCHDOG_USEC`, per systemd's contract.
* `WATCHDOG_PID` is honoured, and the child's environment is stripped of all
  three variables, so a node can never answer its parent's watchdog.
* Newlines in a status string are flattened, so a status cannot forge an extra
  field.

---

## 3. Preflight: what must be true before authority exists

Re-checked on **every** start, because a service that restarts unattended must
re-establish that it is what it claims to be. Verified on the real Jetson:

```
manifest_loadable            PASS      jetson_aarch64            PASS
repository_sha_match         PASS      tegra_release_readable    PASS
engine_present               PASS      tensorrt_importable       PASS  (8.5.2.2)
engine_hash_match            PASS      tensorrt_major_version    PASS
precision_is_authoritative   PASS      cuda_runtime_available    PASS  (11040)
int8_not_authoritative       PASS      protocol_contract_frozen  PASS  (64/48/56, v1)
runtime_dir_writable         PASS      port_available_control    PASS
evidence_dir_writable        PASS      port_available_frame      PASS
route_to_pc                  PASS      port_available_ack        PASS
```

The engine hash is recomputed from the file on disk and compared to the
manifest; a manifest that merely records what was once true is a changelog, not
a gate. Writable paths are proved by writing, not by asking.

**A failed preflight never reaches AI authority.** The service stays up and
answerable in `SAFE_STOP`, and it still notifies `READY` — deliberately, because
systemd must not restart-loop a machine whose engine hash is wrong. The state
says what is true; the exit code is not used to express it.

### The manifest refuses rather than guesses

Versioned, and a different `schema_version` is rejected outright rather than
interpreted optimistically — the same field names may mean something else. It
also cannot declare INT8 authoritative: `precision`, `int8_role` and
`int8_authoritative` are each refused. This file is not where the Phase
13D-MP-RECOVERY freeze gets undone.

---

## 4. Health states

`STARTING → READY → DEGRADED → SAFE_STOP → RESTARTING → FAILED`

Only `READY` may hold AI authority, and that is a statement about the
*service* — the range monitor and clock discipline still gate every frame.
Transition history, failure history and the status response are all bounded; a
status endpoint that grows with uptime is a leak in the one process meant to run
for months.

`--status` reads one JSON object from an `AF_UNIX` socket in the runtime
directory: PID, repository SHA, engine hash, heartbeat age, node start count,
restart count, last failure, watchdog counters, log bounds. The endpoint is
read-only by construction — no request parsing, nothing that can mutate the
service — so it cannot become an accidental control path.

---

## 5. Restart and storm protection, in two independent layers

The wrapper backs off exponentially from `--restart-initial-sec`, capped at
`--restart-max-sec`, and refuses to respawn after `--max-restarts` within
`--restart-window-sec`, exiting non-zero into `FAILED`. systemd's
`StartLimitBurst` then stops restarting the wrapper. Neither layer has to be
perfect.

Restart history is itself bounded: only the current window is retained, never a
growing list of timestamps.

---

## 6. Six defects the gates found, all of them mine

Four of them share a single root cause; the last two only became reachable
once the service was under systemd and rebooting.

**The readiness probe killed what it was probing.** The wrapper checked
readiness by connecting to the node's control port. The node accepts exactly one
control connection and treats it as the session; the probe was consumed as that
session, `recv` failed, and the node exited 3. Five generations died in a row on
the Jetson until the restart-storm limit stopped it. The storm protection worked
correctly — what it was protecting against was the wrapper. Readiness now comes
from the node's own `phase13b_jetson_node_ready` banner, which is why its output
is captured rather than inherited.

**`$!` is not the supervisor.** `setsid nohup env python … & echo $!` records
the PID of the backgrounded `setsid`, which execs or forks into something else.
Every recorded wrapper PID was wrong, every stop reported `not_running`, and
each case started another wrapper on top of the last: **four supervisors** ended
up competing for the same ports, respawning nodes nobody was tracking. The
process that knows its PID is the supervisor, so it writes it. The Gate B port
holder had the identical bug — it survived its own teardown and made the next
case fail preflight on a port that was supposed to be free.

**Recovery was assumed, not observed.** The first fault run recorded a 0.5 s
"recovery" from SIGTERM in which the node PID never changed and the start count
never moved: immediately after the kill the wrapper has not noticed yet, so a
status read returns the previous `READY` with the previous PID. Recovery now
means a *new* generation reached `READY`, proved by the start count advancing.

**Interrupted fault cases left the target broken.** The preflight cases hide the
engine and corrupt the manifest on purpose and restore them in their teardown.
Interrupting the driver skips that, and the engine was left renamed. Repair now
runs at the start of every run as well as the end, and is idempotent.

**A stopping supervisor deleted its successor's PID file.** `remove_pid_file`
removed by path. The node's TensorRT teardown takes tens of seconds, so a
supervisor can finish stopping after its replacement has already written its own
PID — and then delete it, leaving anything watching to conclude the new service
never started. It now removes the file only while the contents are still its own
PID.

**The restart-storm case measured the wrong thing.** It reported failure three
times while the service log showed the storm blocked correctly each time:
`restart_storm_blocked`, `restarts_in_window: 5`, `state: FAILED`. It was trying
to catch a PID file that exists only for the ~35 s the storm lasts, over an SSH
poll, while the process owning it was exiting. What the phase requires is that
the storm was blocked, so the case now counts `restart_storm_blocked` records
before and after. Status stayed **Blocked** until this was fixed and genuinely
reached 10/10.

### And one in the clock discipline, which only a reboot could reach

Gate D's first two cycles were textbook — real reboots, 25.8 s and 26.8 s to
ready, engine hash verified — and both failed FP16 authority.
`estimated_drift_ppm` came back as **455** and **257**. The boot check synced and
resynced about a second apart, and a few hundred microseconds of scatter across a
one-second baseline is hundreds of ppm when fitted as a rate. The model saw
|drift| > 100 ppm, reported `implausible_drift_ppm`, withheld AI authority, and
every command was `ACCEPTED` as SAFE_STOP.

Nothing was broken. The estimator was answering a question it did not yet have
the data for. `estimate_drift_ppm` now reports no slope until the window spans a
minimum baseline — the honest answer to "we have not been watching long enough to
know", and the safe one: the measured scatter still inflates the guard as its
residual, and the drift term scales with a model age that is small by definition
when the window is young. A genuinely implausible rate over a real baseline is
still caught, with a test pinning that so the guard cannot become a way to hide a
fault.

This was never boot-specific. It applied to any freshly started session; a reboot
simply makes the window newest.

---

## 7. Gate results

### Gate A — Prepared

Run on both hosts. On the PC five tests skip: the `AF_UNIX` notify protocol and
the port-availability check, which are only meaningful on Linux. Gate A reports
skips rather than counting them as passes, and running it on the Jetson is what
converts them into evidence.

```
PC      host=AMD64    python=3.10.14  systemd=None  tests_run=513 skipped=5
Jetson  host=aarch64  python=3.8.10   systemd=245   tests_run=513 skipped=0
unit_valid_for_systemd_245=True   (both)
```

### Gate B — Supervisor Pass

Production wrapper run by hand on the real Jetson, 10/10 fault cases:

```
soak                    1827.206 s, state held READY, unexpected restarts 0
watchdog pings          2071          (stand-in notify listener counted them)
orphan processes        0
S00 initial start      READY        S05 port already held   SAFE_STOP
S01 node SIGTERM       READY        S06 restart storm       BLOCKED
S02 node SIGKILL       READY        S07 PC unavailable      READY, no authority
S03 missing engine     SAFE_STOP    S08 SIGTERM to wrapper  SAFE_STOP
S04 corrupt hash       SAFE_STOP    S09 watchdog            PINGED
```

### Gate C — Service Pass

Installed by the operator; every sudo command was theirs. Verified against
systemd itself rather than the service's own report:

```
Type=notify   NotifyAccess=main   User=myjetsonnx (non-root)
ActiveState=active  SubState=running  Result=success  NRestarts=0
WatchdogUSec=1min   watchdog timestamp fresh
Restart=on-failure  RestartUSec=5s   UnitFileState=enabled
StartLimitIntervalUSec=10min  StartLimitBurst=5  RuntimeDirectory=ma-vlna
```

Health socket: READY, authority permitted, engine hash matching the manifest,
`engine_load_count=1`, watchdog pinging at 30 s — half of `WatchdogSec`, per
systemd's contract — and logs bounded at 32 MiB total.

The SHA pin was exercised rather than assumed. With the repository moved and the
env still pinned to the old commit, preflight failed on `repository_sha_match`;
with the pin updated it passed. Both directions were measured.

### Gate D — Boot Pass

Two operator-approved reboot cycles. Each reboot is proved by a changed kernel
boot id, because a service restart that looks like a reboot does not change one.

| | cycle 1 | cycle 2 |
| --- | --- | --- |
| boot id changed | yes | yes |
| `boot_to_ready_sec` (systemd, from boot) | **27.234** | **25.684** |
| within 120 s limit | yes | yes |
| service state | READY | READY |
| `NRestarts` | 0 | 0 |
| `UnitFileState` | enabled | enabled |
| supervisor parent is PID 1 | yes | yes |
| engine hash re-verified | yes | yes |
| engine loaded exactly once | yes | yes |
| FP16 authority restored | yes | yes |
| INT8 authority count | 0 | 0 |
| fallback / CUDA errors | 0 / 0 | 0 / 0 |
| mailbox depth | 1 | 1 |
| clock resync accepted | yes | yes |
| drift ppm (baseline 16 s) | −27.4 | −26.0 |
| `issued_future_skew_us_max` | −2216 | −2137 |
| future-timestamp rejects | 0 | 0 |

Readiness is systemd's `ActiveEnterTimestampMonotonic` — microseconds since boot,
and for a `Type=notify` unit the moment `READY=1` arrived. SSH came back at ~43 s
in both cycles, *after* the service was already READY, which is why timing from
the PC would have overstated it.

"No manual launch" is structural: the supervisor's parent is PID 1.

---

## 8. Two operational notes worth recording

**Passwordless sudo already exists on this host.** `/etc/sudoers` carries
`%sudo ALL=(ALL:ALL) NOPASSWD:ALL`, which predates this phase. It was not created
here and nothing in this phase configures sudo. It is recorded because it is why
`sudo systemctl reboot` worked non-interactively for Gate D, and that should be
visible rather than quietly relied on.

**The Jetson lost internet DNS across the reboots.** `git fetch origin` failed
with `Could not resolve host: github.com` — the ICS path from the PC did not
re-establish. ICS is on the do-not-touch list, so the repository was synced with
a `git bundle` carried over the direct USB-gadget link instead. That keeps real
git objects and a real HEAD, where copying files would have left the commit
claiming something the working tree did not match.

**The env pin moved three times**, once per fix that changed the commit the
service is bound to. That is the pin doing its job, but it is friction: a real
deployment would regenerate the manifest and environment file as one step of
installation rather than by hand.

---

## 9. Artifact boundary

Committed: the schema, builder, validator, wrapper, unit template, environment
**example**, tests and this document.

Not committed: the generated manifest (`config/phase13f_service_manifest.json` —
host-specific absolute paths, a pinned commit and a real hash), rendered units
staged for installation, service logs, runtime evidence, engines and models.
The environment example is committed; a real environment file never is.

---

## 10. Not claimed

No full HIL. No real MCU, CAN or UART. No secure boot. No OTA. No physical
camera, actuator or vehicle deployment. No model accuracy, mAP, recall or route
benchmark. Power is never inferred from utilisation.

No JetPack, kernel, nvpmodel, clock or thermal setting was changed. Nothing was
signalled except exact recorded PIDs; `pkill`, `killall` and name-matched kills
are never used, because a name match has previously killed the controlling SSH
session.
