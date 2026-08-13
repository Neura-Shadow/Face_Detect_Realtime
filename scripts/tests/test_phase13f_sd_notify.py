"""Phase 13F sd_notify tests against a real AF_UNIX socket.

The notification protocol is one datagram of newline-separated KEY=value pairs.
These tests bind an actual socket and read what the notifier sends, because the
failure mode that matters -- systemd silently ignoring a malformed message and
killing the service on watchdog timeout -- is invisible to a mock.
"""

from __future__ import annotations

import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workers.core.sd_notify import WATCHDOG_PING_FRACTION, SdNotifier  # noqa: E402

HAS_AF_UNIX = hasattr(socket, "AF_UNIX")


class FakeSystemd:
    """A real datagram socket standing in for systemd's notify listener."""

    def __init__(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="phase13f-notify-")
        self.path = os.path.join(self.dir, "notify.sock")
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.sock.bind(self.path)
        self.sock.settimeout(2.0)

    def receive(self) -> str:
        return self.sock.recv(4096).decode("utf-8")

    def close(self) -> None:
        try:
            self.sock.close()
        finally:
            try:
                os.unlink(self.path)
            except OSError:
                pass
            try:
                os.rmdir(self.dir)
            except OSError:
                pass


@unittest.skipUnless(HAS_AF_UNIX, "AF_UNIX is Linux-only")
class TestNotifyProtocol(unittest.TestCase):
    def setUp(self) -> None:
        self.systemd = FakeSystemd()
        self.addCleanup(self.systemd.close)

    def _notifier(self, **env) -> SdNotifier:
        environ = {"NOTIFY_SOCKET": self.systemd.path}
        environ.update(env)
        return SdNotifier(environ=environ)

    def test_ready_is_sent_verbatim(self) -> None:
        notifier = self._notifier()
        self.assertTrue(notifier.ready("node up"))
        message = self.systemd.receive()
        self.assertIn("READY=1", message)
        self.assertIn("STATUS=node up", message)

    def test_watchdog_message_is_exact(self) -> None:
        notifier = self._notifier(WATCHDOG_USEC="60000000")
        self.assertTrue(notifier.watchdog())
        self.assertEqual(self.systemd.receive(), "WATCHDOG=1")
        self.assertEqual(notifier.watchdog_ping_count, 1)

    def test_newlines_in_status_cannot_forge_extra_fields(self) -> None:
        notifier = self._notifier()
        notifier.status("first\nREADY=1")
        message = self.systemd.receive()
        # Exactly one field: the injected READY must not become its own line.
        self.assertEqual(len(message.splitlines()), 1)
        self.assertTrue(message.startswith("STATUS="))

    def test_stopping_is_sent(self) -> None:
        notifier = self._notifier()
        notifier.stopping("bye")
        message = self.systemd.receive()
        self.assertIn("STOPPING=1", message)


class TestWatchdogConfiguration(unittest.TestCase):
    def test_watchdog_interval_is_half_the_configured_timeout(self) -> None:
        notifier = SdNotifier(environ={"NOTIFY_SOCKET": "/x", "WATCHDOG_USEC": "60000000"})
        self.assertEqual(notifier.watchdog_interval_sec, 60.0 * WATCHDOG_PING_FRACTION)

    def test_no_watchdog_configured_means_no_interval(self) -> None:
        notifier = SdNotifier(environ={"NOTIFY_SOCKET": "/x"})
        self.assertIsNone(notifier.watchdog_interval_sec)
        self.assertTrue(notifier.watchdog(), "must be a successful no-op")

    def test_watchdog_pid_belonging_to_another_process_is_refused(self) -> None:
        # A child must never answer the parent's watchdog.
        notifier = SdNotifier(environ={
            "NOTIFY_SOCKET": "/x", "WATCHDOG_USEC": "60000000",
            "WATCHDOG_PID": str(os.getpid() + 1),
        })
        self.assertFalse(notifier.watchdog_enabled)
        self.assertIsNone(notifier.watchdog_interval_sec)

    def test_watchdog_pid_matching_us_is_accepted(self) -> None:
        notifier = SdNotifier(environ={
            "NOTIFY_SOCKET": "/x", "WATCHDOG_USEC": "30000000",
            "WATCHDOG_PID": str(os.getpid()),
        })
        self.assertTrue(notifier.watchdog_enabled)

    def test_malformed_watchdog_usec_disables_rather_than_raises(self) -> None:
        notifier = SdNotifier(environ={"NOTIFY_SOCKET": "/x", "WATCHDOG_USEC": "not-a-number"})
        self.assertFalse(notifier.watchdog_enabled)


class TestInertWithoutSystemd(unittest.TestCase):
    """The same wrapper has to run under a bare shell and on Windows."""

    def test_absent_notify_socket_makes_every_call_a_successful_no_op(self) -> None:
        notifier = SdNotifier(environ={})
        self.assertFalse(notifier.available)
        self.assertTrue(notifier.ready())
        self.assertTrue(notifier.watchdog())
        self.assertTrue(notifier.status("anything"))
        self.assertTrue(notifier.stopping())
        self.assertEqual(notifier.failure_count, 0)

    def test_abstract_namespace_address_is_recognised(self) -> None:
        notifier = SdNotifier(environ={"NOTIFY_SOCKET": "@/org/freedesktop/systemd1/notify"})
        self.assertEqual(notifier.to_dict()["notify_socket_kind"], "abstract")
        self.assertTrue(notifier._resolve_address().startswith("\0"))

    def test_evidence_surface_is_complete(self) -> None:
        payload = SdNotifier(environ={"NOTIFY_SOCKET": "/x", "WATCHDOG_USEC": "10000000"}).to_dict()
        for key in (
            "notify_socket_present", "watchdog_enabled", "watchdog_usec",
            "watchdog_ping_interval_sec", "notify_count", "watchdog_ping_count",
        ):
            self.assertIn(key, payload)


if __name__ == "__main__":
    unittest.main()
