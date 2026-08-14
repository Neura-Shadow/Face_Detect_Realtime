"""Phase 13F service health state, bounded status store and local query socket.

The supervised node has to be answerable without a PC session attached: after a
crash, during backoff, or before the PC has ever connected, an operator on the
Jetson still needs to know what state it is in and why. That is what this
provides — a small state machine, a bounded record of recent transitions and
failures, and an ``AF_UNIX`` socket that hands back one JSON object.

Two properties matter more than the shape of the data:

* **Bounded.** Transition history, failure history and the response itself are
  all capped. A status endpoint that grows with uptime is a leak in the one
  process that is supposed to run for months.
* **Fail-closed.** ``SAFE_STOP`` and ``FAILED`` are never reachable *out of*
  by accident; leaving them takes an explicit transition, and a state that
  cannot grant AI authority says so through :attr:`ai_authority_permitted`
  rather than leaving the caller to infer it.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional

#: The six states the phase names, in the order they normally progress.
STATE_STARTING = "STARTING"
STATE_READY = "READY"
STATE_DEGRADED = "DEGRADED"
STATE_SAFE_STOP = "SAFE_STOP"
STATE_RESTARTING = "RESTARTING"
STATE_FAILED = "FAILED"

SERVICE_STATES = (
    STATE_STARTING,
    STATE_READY,
    STATE_DEGRADED,
    STATE_SAFE_STOP,
    STATE_RESTARTING,
    STATE_FAILED,
)

#: Only READY may hold AI authority. DEGRADED keeps the process alive and
#: reporting but must not drive.
AI_AUTHORITY_STATES = frozenset({STATE_READY})

DEFAULT_HISTORY_CAPACITY = 64
DEFAULT_FAILURE_CAPACITY = 32
#: Hard cap on one status response, so a query can never return an unbounded
#: blob no matter what accumulated inside the service.
DEFAULT_MAX_RESPONSE_BYTES = 64 * 1024


class ServiceHealth:
    """Thread-safe health state with bounded history."""

    def __init__(
        self,
        *,
        service_name: str = "ma-vlna-jetson-node",
        history_capacity: int = DEFAULT_HISTORY_CAPACITY,
        failure_capacity: int = DEFAULT_FAILURE_CAPACITY,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self.service_name = str(service_name)
        self._clock = clock or time.time
        self._lock = threading.Lock()
        self._state = STATE_STARTING
        self._reason = "service starting"
        self.started_at = self._clock()
        self.state_entered_at = self.started_at
        self._history = deque(maxlen=max(1, int(history_capacity)))  # type: Deque[Dict[str, Any]]
        self._failures = deque(maxlen=max(1, int(failure_capacity)))  # type: Deque[Dict[str, Any]]
        self._facts = {}  # type: Dict[str, Any]
        self.transition_count = 0
        self.restart_count = 0
        self.safe_stop_count = 0
        self.last_heartbeat_at = None  # type: Optional[float]
        self._history.append(
            {"at": self.started_at, "from": "", "to": self._state, "reason": self._reason}
        )

    # ── state ───────────────────────────────────────────────────────────────

    @property
    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def reason(self) -> str:
        with self._lock:
            return self._reason

    @property
    def ai_authority_permitted(self) -> bool:
        """Whether this state may hold AI authority at all.

        This is a statement about the *service*, not a grant. The range monitor
        and clock discipline still gate each individual frame.
        """

        with self._lock:
            return self._state in AI_AUTHORITY_STATES

    def transition(self, state: str, reason: str = "") -> bool:
        """Move to ``state``. Returns whether the state actually changed."""

        if state not in SERVICE_STATES:
            raise ValueError("unknown service state %r" % (state,))
        now = self._clock()
        with self._lock:
            if state == self._state:
                if reason:
                    self._reason = reason
                return False
            previous = self._state
            self._state = state
            self._reason = reason or state
            self.state_entered_at = now
            self.transition_count += 1
            if state == STATE_RESTARTING:
                self.restart_count += 1
            if state == STATE_SAFE_STOP:
                self.safe_stop_count += 1
            self._history.append(
                {"at": now, "from": previous, "to": state, "reason": self._reason}
            )
        return True

    def record_failure(self, classification: str, detail: str = "") -> None:
        with self._lock:
            self._failures.append(
                {
                    "at": self._clock(),
                    "classification": str(classification),
                    "detail": str(detail)[:400],
                }
            )

    def heartbeat(self) -> None:
        with self._lock:
            self.last_heartbeat_at = self._clock()

    def heartbeat_age_sec(self) -> Optional[float]:
        with self._lock:
            if self.last_heartbeat_at is None:
                return None
            return max(0.0, self._clock() - self.last_heartbeat_at)

    def set_facts(self, **facts: Any) -> None:
        """Attach immutable-ish run facts (SHA, engine hash, ports, PID)."""

        with self._lock:
            for key, value in facts.items():
                self._facts[str(key)] = value

    # ── reporting ───────────────────────────────────────────────────────────

    def last_failure(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            return dict(self._failures[-1]) if self._failures else None

    def snapshot(self, *, history_limit: int = 12, failure_limit: int = 5) -> Dict[str, Any]:
        now = self._clock()
        with self._lock:
            history = list(self._history)[-max(0, int(history_limit)):]
            failures = list(self._failures)[-max(0, int(failure_limit)):]
            payload = {
                "service_name": self.service_name,
                "state": self._state,
                "reason": self._reason,
                "ai_authority_permitted": self._state in AI_AUTHORITY_STATES,
                "pid": os.getpid(),
                "uptime_sec": round(now - self.started_at, 3),
                "state_age_sec": round(now - self.state_entered_at, 3),
                "transition_count": self.transition_count,
                "restart_count": self.restart_count,
                "safe_stop_count": self.safe_stop_count,
                "heartbeat_age_sec": (
                    None if self.last_heartbeat_at is None
                    else round(max(0.0, now - self.last_heartbeat_at), 3)
                ),
                "recent_transitions": history,
                "recent_failures": failures,
                "last_failure": dict(failures[-1]) if failures else None,
                "history_capacity": self._history.maxlen,
                "failure_capacity": self._failures.maxlen,
            }
            payload.update(self._facts)
        return payload


def encode_status(payload: Dict[str, Any], *, max_bytes: int = DEFAULT_MAX_RESPONSE_BYTES) -> bytes:
    """Serialise a status payload, degrading rather than exceeding the cap.

    An over-long response is replaced by a smaller one that says it was
    truncated. Silently cutting JSON in half would hand the caller something
    that does not parse.
    """

    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    if len(encoded) <= max_bytes:
        return encoded
    reduced = dict(payload)
    reduced["recent_transitions"] = reduced.get("recent_transitions", [])[-3:]
    reduced["recent_failures"] = reduced.get("recent_failures", [])[-1:]
    reduced["status_truncated"] = True
    reduced["status_truncated_from_bytes"] = len(encoded)
    encoded = json.dumps(reduced, sort_keys=True, default=str).encode("utf-8")
    if len(encoded) <= max_bytes:
        return encoded
    minimal = {
        "service_name": payload.get("service_name"),
        "state": payload.get("state"),
        "reason": payload.get("reason"),
        "pid": payload.get("pid"),
        "status_truncated": True,
        "status_truncated_from_bytes": len(encoded),
    }
    return json.dumps(minimal, sort_keys=True, default=str).encode("utf-8")


class HealthSocketServer:
    """One-shot ``AF_UNIX`` status endpoint: connect, read one JSON object.

    Deliberately trivial: no request parsing, no commands, nothing that can
    mutate the service. It exists so an operator on the Jetson can ask what is
    happening without attaching a PC session, and a read-only endpoint cannot
    become an accidental control path.
    """

    def __init__(
        self,
        path: str,
        health: ServiceHealth,
        *,
        extra_provider: Optional[Callable[[], Dict[str, Any]]] = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        backlog: int = 4,
    ) -> None:
        self.path = str(path)
        self.health = health
        self.extra_provider = extra_provider
        self.max_response_bytes = int(max_response_bytes)
        self.backlog = int(backlog)
        self.request_count = 0
        self.error_count = 0
        self.last_error = ""
        self._server = None  # type: Optional[socket.socket]
        self._thread = None  # type: Optional[threading.Thread]
        self._stop = threading.Event()

    def start(self) -> bool:
        if self._thread is not None:
            return True
        try:
            directory = os.path.dirname(os.path.abspath(self.path))
            if directory:
                os.makedirs(directory, exist_ok=True)
            # A stale socket file from a killed predecessor would block bind().
            if os.path.exists(self.path):
                os.unlink(self.path)
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.settimeout(0.5)
            server.bind(self.path)
            server.listen(self.backlog)
            try:
                os.chmod(self.path, 0o660)
            except OSError:
                pass
        except (OSError, AttributeError) as exc:
            self.error_count += 1
            self.last_error = "%s: %s" % (type(exc).__name__, exc)
            return False
        self._server = server
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._serve, name="phase13f-health", daemon=True
        )
        self._thread.start()
        return True

    def _serve(self) -> None:
        while not self._stop.is_set():
            server = self._server
            if server is None:
                return
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                conn.settimeout(2.0)
                conn.sendall(self.payload())
                self.request_count += 1
            except OSError as exc:
                self.error_count += 1
                self.last_error = "%s: %s" % (type(exc).__name__, exc)
            finally:
                try:
                    conn.close()
                except OSError:
                    pass

    def payload(self) -> bytes:
        snapshot = self.health.snapshot()
        if self.extra_provider is not None:
            try:
                extra = self.extra_provider() or {}
                snapshot.update(extra)
            except Exception as exc:  # a broken provider must not kill status
                snapshot["status_provider_error"] = "%s: %s" % (type(exc).__name__, exc)
        return encode_status(snapshot, max_bytes=self.max_response_bytes)

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
            self._server = None
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
        try:
            if os.path.exists(self.path):
                os.unlink(self.path)
        except OSError:
            pass

    def to_dict(self) -> Dict[str, Any]:
        return {
            "health_socket_path": self.path,
            "health_socket_active": self._thread is not None,
            "health_request_count": self.request_count,
            "health_error_count": self.error_count,
            "health_last_error": self.last_error,
            "health_max_response_bytes": self.max_response_bytes,
        }


def query_health(path: str, *, timeout_sec: float = 5.0) -> Dict[str, Any]:
    """Read one status object from a running service."""

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(float(timeout_sec))
    chunks = []  # type: List[bytes]
    try:
        sock.connect(str(path))
        while True:
            chunk = sock.recv(8192)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        try:
            sock.close()
        except OSError:
            pass
    if not chunks:
        raise OSError("health socket returned no data")
    return json.loads(b"".join(chunks).decode("utf-8"))
