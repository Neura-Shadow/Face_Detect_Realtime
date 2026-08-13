"""Phase 13F sd_notify over ``NOTIFY_SOCKET``, with no new dependencies.

``Type=notify`` and ``WatchdogSec`` need the service to talk the systemd
notification protocol, which is a single ``AF_UNIX`` datagram carrying
newline-separated ``KEY=value`` pairs. That is small enough to implement
directly, and the Jetson venv is not somewhere to add a package for it —
``python-systemd`` needs a compiler and headers on the target.

The socket path comes from ``NOTIFY_SOCKET``. A leading ``@`` means the Linux
abstract namespace, which is expressed in Python as a leading NUL byte. When
the variable is absent the notifier is inert: every call succeeds and does
nothing, so the same wrapper runs identically under systemd, under a bare shell
during Gate B, and on the Windows PC during unit tests.

Watchdog timing comes from ``WATCHDOG_USEC``, and systemd's documented contract
is to ping at **half** that interval. ``WATCHDOG_PID`` is honoured so a child
process cannot accidentally answer the parent's watchdog.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import os
import socket
from typing import Any, Dict, Optional

#: systemd's own recommendation: ping at half the configured interval so a
#: single late ping does not trip the watchdog.
WATCHDOG_PING_FRACTION = 0.5


class SdNotifier:
    """Minimal systemd notification client.

    Inert when ``NOTIFY_SOCKET`` is unset, so the wrapper behaves the same way
    whether or not systemd is supervising it.
    """

    def __init__(
        self,
        *,
        environ: Optional[Dict[str, str]] = None,
        unset_environment: bool = False,
    ) -> None:
        env = dict(os.environ if environ is None else environ)
        self.address = env.get("NOTIFY_SOCKET", "")
        self.watchdog_usec = self._parse_int(env.get("WATCHDOG_USEC", ""))
        watchdog_pid = self._parse_int(env.get("WATCHDOG_PID", ""))
        # If systemd named a specific PID, only that process may answer.
        self.watchdog_enabled = bool(self.watchdog_usec) and (
            not watchdog_pid or watchdog_pid == os.getpid()
        )
        self.notify_count = 0
        self.watchdog_ping_count = 0
        self.failure_count = 0
        self.last_error = ""
        self._socket = None  # type: Optional[socket.socket]
        if unset_environment:
            for key in ("NOTIFY_SOCKET", "WATCHDOG_USEC", "WATCHDOG_PID"):
                os.environ.pop(key, None)

    @staticmethod
    def _parse_int(value: str) -> int:
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return 0

    @property
    def available(self) -> bool:
        return bool(self.address)

    @property
    def watchdog_interval_sec(self) -> Optional[float]:
        """How often to ping, or ``None`` when no watchdog is configured."""

        if not self.watchdog_enabled:
            return None
        return (self.watchdog_usec / 1e6) * WATCHDOG_PING_FRACTION

    # ── transport ───────────────────────────────────────────────────────────

    def _resolve_address(self) -> str:
        address = self.address
        if address.startswith("@"):
            # Abstract namespace: systemd writes '@', Python wants a NUL.
            return "\0" + address[1:]
        return address

    def _ensure_socket(self) -> Optional[socket.socket]:
        if self._socket is not None:
            return self._socket
        if not self.address:
            return None
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM | socket.SOCK_CLOEXEC)
        except AttributeError:  # pragma: no cover - non-Linux
            return None
        except OSError as exc:  # pragma: no cover - depends on platform
            self.failure_count += 1
            self.last_error = "%s: %s" % (type(exc).__name__, exc)
            return None
        self._socket = sock
        return sock

    def _send(self, message: str) -> bool:
        sock = self._ensure_socket()
        if sock is None:
            return not self.address
        try:
            sock.sendto(message.encode("utf-8"), self._resolve_address())
        except OSError as exc:
            self.failure_count += 1
            self.last_error = "%s: %s" % (type(exc).__name__, exc)
            return False
        self.notify_count += 1
        return True

    # ── protocol ────────────────────────────────────────────────────────────

    def notify(self, **fields: Any) -> bool:
        """Send arbitrary ``KEY=value`` pairs in one datagram."""

        if not fields:
            return True
        lines = []
        for key, value in fields.items():
            if value is None:
                continue
            text = str(value)
            # Newlines would be read as extra fields and corrupt the message.
            text = text.replace("\n", " ").replace("\r", " ")
            lines.append("%s=%s" % (str(key).upper(), text))
        if not lines:
            return True
        return self._send("\n".join(lines))

    def ready(self, status: str = "") -> bool:
        return self.notify(READY=1, STATUS=status or None)

    def status(self, status: str) -> bool:
        return self.notify(STATUS=status)

    def watchdog(self) -> bool:
        """Ping the watchdog. A no-op unless systemd configured one for us."""

        if not self.watchdog_enabled:
            return True
        sent = self._send("WATCHDOG=1")
        if sent:
            self.watchdog_ping_count += 1
        return sent

    def stopping(self, status: str = "") -> bool:
        return self.notify(STOPPING=1, STATUS=status or None)

    def reloading(self) -> bool:
        return self.notify(RELOADING=1)

    def close(self) -> None:
        if self._socket is not None:
            try:
                self._socket.close()
            finally:
                self._socket = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "notify_socket_present": bool(self.address),
            "notify_socket_kind": (
                "abstract" if self.address.startswith("@")
                else ("path" if self.address else "absent")
            ),
            "watchdog_enabled": self.watchdog_enabled,
            "watchdog_usec": self.watchdog_usec,
            "watchdog_ping_interval_sec": self.watchdog_interval_sec,
            "notify_count": self.notify_count,
            "watchdog_ping_count": self.watchdog_ping_count,
            "notify_failure_count": self.failure_count,
            "notify_last_error": self.last_error,
        }
