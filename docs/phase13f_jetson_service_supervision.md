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

## 6. Four defects Gate B found, all of one kind

Every one of these was mine, and three share a single root cause.

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

_Recorded in the phase evidence; see the final report._

### Gates C and D

Gate C installs the unit into `/etc/systemd/system` and Gate D reboots the
Jetson. Both require **explicit operator approval**, and neither is performed
here without it. `run_phase13f_install.py` renders the unit, validates it and
prints the exact commands — it never runs sudo, never writes `/etc`, never
enables or starts a unit, and never asks for or stores a password.

---

## 8. Artifact boundary

Committed: the schema, builder, validator, wrapper, unit template, environment
**example**, tests and this document.

Not committed: the generated manifest (`config/phase13f_service_manifest.json` —
host-specific absolute paths, a pinned commit and a real hash), rendered units
staged for installation, service logs, runtime evidence, engines and models.
The environment example is committed; a real environment file never is.

---

## 9. Not claimed

No full HIL. No real MCU, CAN or UART. No secure boot. No OTA. No physical
camera, actuator or vehicle deployment. No model accuracy, mAP, recall or route
benchmark. Power is never inferred from utilisation.

No JetPack, kernel, nvpmodel, clock or thermal setting was changed. Nothing was
signalled except exact recorded PIDs; `pkill`, `killall` and name-matched kills
are never used, because a name match has previously killed the controlling SSH
session.
