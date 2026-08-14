"""Phase 13G deployment state machine, persisted atomically.

The state file is the only thing that survives a power cut in the middle of an
update, so it is written the same way the ``current`` symlink is switched:
into a temporary file, fsynced, then renamed onto the real name. A reader
therefore sees either the previous state or the new one — never a truncated
JSON document, which is what a plain ``open(path, "w")`` produces if the
machine dies mid-write.

The transition table is explicit. An update is a sequence of moments where the
answer to "what is running, and is it trusted yet?" changes, and the dangerous
ones are the two in the middle:

* ``ACTIVATING`` — ``current`` may already point at the candidate, but nothing
  has confirmed it works.
* ``PROBATION`` — the candidate is live and being watched, and is still not
  trusted.

Both are *unconfirmed*: if the machine reboots while in either, the deployment
manager must decide deterministically what to do rather than resume whatever it
happened to be doing. The default policy here is to roll back to
last-known-good, because an activation that could not finish is not evidence
that the candidate is good.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

STATE_SCHEMA_VERSION = 1

IDLE = "IDLE"
STAGED = "STAGED"
VALIDATED = "VALIDATED"
ACTIVATING = "ACTIVATING"
PROBATION = "PROBATION"
CONFIRMED = "CONFIRMED"
ROLLING_BACK = "ROLLING_BACK"
ROLLED_BACK = "ROLLED_BACK"
FAILED = "FAILED"

DEPLOYMENT_STATES = (
    IDLE, STAGED, VALIDATED, ACTIVATING, PROBATION, CONFIRMED,
    ROLLING_BACK, ROLLED_BACK, FAILED,
)

#: States in which an activation is in flight and not yet trusted. A reboot in
#: any of these needs a deliberate recovery decision.
UNCONFIRMED_STATES = frozenset({ACTIVATING, PROBATION})

#: States from which command authority must be fail-closed to SAFE_STOP: the
#: service is being restarted, replaced or reverted underneath it.
FAIL_CLOSED_STATES = frozenset({ACTIVATING, PROBATION, ROLLING_BACK})

#: Terminal states of one deployment attempt.
TERMINAL_STATES = frozenset({CONFIRMED, ROLLED_BACK, FAILED, IDLE})

#: The legal moves. Anything not listed is refused, so a bug cannot walk the
#: deployment into a state its recovery logic was never written for.
ALLOWED_TRANSITIONS = {
    IDLE: {STAGED, FAILED},
    STAGED: {VALIDATED, FAILED, IDLE},
    VALIDATED: {ACTIVATING, FAILED, IDLE},
    ACTIVATING: {PROBATION, ROLLING_BACK, FAILED},
    PROBATION: {CONFIRMED, ROLLING_BACK, FAILED},
    CONFIRMED: {IDLE, STAGED},
    ROLLING_BACK: {ROLLED_BACK, FAILED},
    ROLLED_BACK: {IDLE, STAGED},
    FAILED: {IDLE, STAGED, ROLLING_BACK},
}


class DeploymentStateError(RuntimeError):
    def __init__(self, classification: str, message: str) -> None:
        super(DeploymentStateError, self).__init__("%s: %s" % (classification, message))
        self.classification = classification
        self.message = message


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class DeploymentState:
    """Atomically persisted deployment state with a bounded history."""

    HISTORY_LIMIT = 64

    def __init__(
        self,
        path: str,
        *,
        clock: Optional[Callable[[], float]] = None,
        history_limit: int = HISTORY_LIMIT,
    ) -> None:
        self.path = os.path.abspath(path)
        self._clock = clock or time.time
        self.history_limit = max(1, int(history_limit))
        self.payload = self._load()

    # ── persistence ─────────────────────────────────────────────────────────

    def _default(self) -> Dict[str, Any]:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "state": IDLE,
            "reason": "no deployment in progress",
            "updated_at_utc": utc_now(),
            "updated_at_monotonic": None,
            "candidate_release_id": None,
            "active_release_id": None,
            "previous_release_id": None,
            "last_known_good_release_id": None,
            "attempt_id": None,
            "probation_deadline_epoch": None,
            "switch_completed": False,
            "history": [],
            "transition_count": 0,
        }

    def _load(self) -> Dict[str, Any]:
        if not os.path.isfile(self.path):
            return self._default()
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError):
            # A corrupt state file is treated as "unknown", not as IDLE: the
            # caller has to decide, and pretending nothing was happening is
            # exactly the wrong default mid-update.
            payload = self._default()
            payload["state"] = FAILED
            payload["reason"] = "state file unreadable or corrupt"
            payload["recovered_from_corrupt_state"] = True
            return payload
        if payload.get("schema_version") != STATE_SCHEMA_VERSION:
            payload = self._default()
            payload["state"] = FAILED
            payload["reason"] = "state schema mismatch"
            payload["recovered_from_schema_mismatch"] = True
        return payload

    def save(self) -> None:
        """Write atomically: temp file, fsync, rename, fsync directory."""

        directory = os.path.dirname(self.path)
        os.makedirs(directory, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=directory,
            prefix=".deployment-state-", suffix=".tmp", delete=False,
        )
        temporary = handle.name
        try:
            json.dump(self.payload, handle, indent=2, sort_keys=True, default=str)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()
        os.replace(temporary, self.path)
        try:
            fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass

    # ── state ───────────────────────────────────────────────────────────────

    @property
    def state(self) -> str:
        return str(self.payload.get("state", IDLE))

    @property
    def candidate_release_id(self) -> Optional[str]:
        return self.payload.get("candidate_release_id")

    @property
    def switch_completed(self) -> bool:
        return bool(self.payload.get("switch_completed"))

    @property
    def is_unconfirmed(self) -> bool:
        return self.state in UNCONFIRMED_STATES

    @property
    def authority_fail_closed(self) -> bool:
        """Whether command authority must be withheld in this state."""

        return self.state in FAIL_CLOSED_STATES

    def can_transition(self, target: str) -> bool:
        return target in ALLOWED_TRANSITIONS.get(self.state, set())

    def transition(self, target: str, reason: str = "", **fields: Any) -> Dict[str, Any]:
        """Move to ``target``, persisting before returning."""

        if target not in DEPLOYMENT_STATES:
            raise DeploymentStateError("unknown_state", "unknown state %r" % (target,))
        if not self.can_transition(target):
            raise DeploymentStateError(
                "illegal_transition",
                "%s -> %s is not an allowed transition" % (self.state, target),
            )
        previous = self.state
        self.payload["state"] = target
        self.payload["reason"] = reason or target
        self.payload["updated_at_utc"] = utc_now()
        self.payload["updated_at_monotonic"] = round(time.monotonic(), 6)
        self.payload["transition_count"] = int(self.payload.get("transition_count", 0)) + 1
        for key, value in fields.items():
            self.payload[key] = value
        history = list(self.payload.get("history", []))
        history.append({
            "at": utc_now(),
            "from": previous,
            "to": target,
            "reason": self.payload["reason"],
        })
        # Bounded: a device that updates for years must not grow its state file.
        self.payload["history"] = history[-self.history_limit:]
        self.save()
        return {"from": previous, "to": target, "reason": self.payload["reason"]}

    def set(self, **fields: Any) -> None:
        self.payload.update(fields)
        self.payload["updated_at_utc"] = utc_now()
        self.save()

    def reset_to_idle(self, reason: str = "reset") -> None:
        """Return to IDLE from any state, for an operator-driven reset."""

        payload = self._default()
        payload["reason"] = reason
        payload["last_known_good_release_id"] = self.payload.get("last_known_good_release_id")
        payload["active_release_id"] = self.payload.get("active_release_id")
        payload["history"] = list(self.payload.get("history", []))[-self.history_limit:]
        self.payload = payload
        self.save()

    # ── recovery ────────────────────────────────────────────────────────────

    def recovery_decision(self, *, policy: str = "rollback") -> Dict[str, Any]:
        """What to do when the process starts and finds a state in flight.

        The two unconfirmed states are the interesting ones. ``rollback`` is
        the default because an activation that could not finish is not evidence
        that the candidate works, and a device that reboots into an unproven
        release has quietly promoted it without anyone confirming anything.
        """

        state = self.state
        decision = {
            "state_found": state,
            "policy": policy,
            "switch_completed": self.switch_completed,
            "candidate_release_id": self.candidate_release_id,
            "last_known_good_release_id": self.payload.get("last_known_good_release_id"),
        }
        if state in TERMINAL_STATES:
            decision["action"] = "none"
            decision["detail"] = "no deployment was in flight"
            return decision
        if state in (STAGED, VALIDATED):
            # Nothing was switched, so production authority never moved.
            decision["action"] = "discard_candidate"
            decision["detail"] = "candidate staged but never activated; current is untouched"
            return decision
        if state == ROLLING_BACK:
            decision["action"] = "resume_rollback"
            decision["detail"] = "a rollback was interrupted and must be completed"
            return decision
        if state in UNCONFIRMED_STATES:
            if policy == "resume" and state == PROBATION:
                decision["action"] = "resume_probation"
                decision["detail"] = "probation was running and may continue"
                return decision
            decision["action"] = "rollback_to_last_known_good"
            decision["detail"] = (
                "activation was interrupted before confirmation; an unconfirmed "
                "release is not promoted by a reboot"
            )
            return decision
        decision["action"] = "none"
        return decision

    def to_dict(self) -> Dict[str, Any]:
        payload = dict(self.payload)
        payload["state_path"] = self.path
        payload["authority_fail_closed"] = self.authority_fail_closed
        payload["is_unconfirmed"] = self.is_unconfirmed
        payload["allowed_next_states"] = sorted(ALLOWED_TRANSITIONS.get(self.state, set()))
        return payload


def describe_state_machine() -> Dict[str, Any]:
    return {
        "state_schema_version": STATE_SCHEMA_VERSION,
        "states": list(DEPLOYMENT_STATES),
        "allowed_transitions": {
            key: sorted(value) for key, value in ALLOWED_TRANSITIONS.items()
        },
        "unconfirmed_states": sorted(UNCONFIRMED_STATES),
        "fail_closed_states": sorted(FAIL_CLOSED_STATES),
        "terminal_states": sorted(TERMINAL_STATES),
        "persistence": "tempfile+fsync+rename+dir-fsync",
        "default_reboot_policy": "rollback_to_last_known_good",
    }
