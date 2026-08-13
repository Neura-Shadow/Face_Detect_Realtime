"""Phase 13F supervisor lifecycle tests with a real child process.

The supervisor's job is entirely about what happens when the child misbehaves,
so these tests spawn an actual process that binds the control port and then
exits cleanly, exits non-zero, never becomes ready, or refuses to die. Mocking
``Popen`` would test the mock.

The stub child is deliberately not the real node: this is about supervision, and
loading TensorRT would make every case take a minute and need a Jetson.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from typing import List
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from run_phase13f_service import ServiceSupervisor, parse_args  # noqa: E402
from workers.core.bounded_log import BoundedJsonlLog  # noqa: E402
from workers.core.service_health import STATE_FAILED, STATE_READY, STATE_SAFE_STOP  # noqa: E402
from workers.core.service_manifest import build_manifest  # noqa: E402
from workers.core.service_preflight import _git_sha  # noqa: E402

#: The fixture manifest carries the repository's real HEAD so preflight passes
#: for tests that are about supervision. Tests about preflight override it.
REPO_SHA = _git_sha(str(REPO_ROOT)) or ("b" * 40)

#: A stand-in node: binds the control port so readiness is observable, holds it
#: for `hold` seconds, then exits with `code`.
STUB_NODE = textwrap.dedent(
    """
    import socket, sys, time
    port = int(sys.argv[1]); hold = float(sys.argv[2]); code = int(sys.argv[3])
    bind = sys.argv[4] if len(sys.argv) > 4 else "1"
    if bind == "1":
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", port)); s.listen(4)
    time.sleep(hold)
    sys.exit(code)
    """
).strip()


def free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class SupervisorFixture:
    """A supervisor wired to a stub child instead of the real node."""

    def __init__(self, tmp: str, *, hold: float, code: int, bind: bool = True, **overrides):
        self.tmp = tmp
        engine = os.path.join(tmp, "engine.plan")
        with open(engine, "wb") as handle:
            handle.write(b"stub-engine")
        manifest_path = os.path.join(tmp, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump(
                build_manifest(
                    service_name="test-service",
                    repository_sha=REPO_SHA,
                    engine_path=engine,
                ),
                handle,
            )
        self.control_port = free_port()
        argv = [
            "--manifest", manifest_path,
            "--runtime-dir", os.path.join(tmp, "run"),
            "--evidence-dir", os.path.join(tmp, "evidence"),
            "--log-path", os.path.join(tmp, "logs", "service.jsonl"),
            "--no-log-echo",
            "--bind-host", "127.0.0.1",
            "--control-port", str(self.control_port),
            "--frame-port", str(free_port()),
            "--command-port", str(free_port()),
            "--ack-port", str(free_port()),
            "--skip-port-check",
            "--skip-tensorrt-check",
            "--node-ready-timeout-sec", "8",
            "--node-stop-timeout-sec", "3",
            "--restart-initial-sec", "0.05",
            "--restart-max-sec", "0.2",
            "--watchdog-poll-sec", "0.05",
        ]
        for key, value in overrides.items():
            argv += ["--%s" % key.replace("_", "-"), str(value)]
        self.args = parse_args(argv)
        self.supervisor = ServiceSupervisor(self.args)
        stub_path = os.path.join(tmp, "stub_node.py")
        with open(stub_path, "w", encoding="utf-8") as handle:
            handle.write(STUB_NODE)
        command = [
            sys.executable, stub_path, str(self.control_port),
            str(hold), str(code), "1" if bind else "0",
        ]
        self.supervisor.node_command = lambda: list(command)  # type: ignore[assignment]

    def close(self) -> None:
        """Release the log handle and any child, so tempdir cleanup works."""

        try:
            self.supervisor.stop_node(reason="fixture_cleanup")
        except Exception:
            pass
        self.supervisor.log.close()
        if self.supervisor.health_server is not None:
            self.supervisor.health_server.stop()


class JetsonMachineMixin(unittest.TestCase):
    """Pretend to be aarch64 for supervision tests.

    ``jetson_aarch64`` is a real production check -- the service is only valid
    on the Jetson -- so it is patched here rather than given a bypass flag that
    would exist in the shipped code. Tests that are *about* preflight leave it
    alone.
    """

    def setUp(self) -> None:
        patcher = mock.patch(
            "workers.core.service_preflight.platform.machine", return_value="aarch64"
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def make_fixture(self, *args, **kwargs) -> "SupervisorFixture":
        fixture = SupervisorFixture(*args, **kwargs)
        self.addCleanup(fixture.close)
        return fixture


class TestSupervisionOutcomes(JetsonMachineMixin):
    def setUp(self) -> None:
        super(TestSupervisionOutcomes, self).setUp()
        self._dir = tempfile.TemporaryDirectory(prefix="phase13f-sup-")
        self.tmp = self._dir.name
        self.addCleanup(self._dir.cleanup)

    def test_a_clean_child_exit_is_reported_clean(self) -> None:
        fixture = self.make_fixture(self.tmp, hold=4.0, code=0)
        outcome = fixture.supervisor.supervise_once()
        self.assertEqual(outcome, "clean")
        self.assertEqual(fixture.supervisor.node_clean_exit_count, 1)
        self.assertEqual(fixture.supervisor.node_failure_count, 0)
        # Readiness is the control port accepting, not exec returning.
        self.assertEqual(fixture.supervisor.health.state, STATE_READY)

    def test_a_nonzero_child_exit_is_reported_failed(self) -> None:
        fixture = self.make_fixture(self.tmp, hold=4.0, code=7)
        self.assertEqual(fixture.supervisor.supervise_once(), "failed")
        self.assertEqual(fixture.supervisor.node_failure_count, 1)
        self.assertEqual(fixture.supervisor.last_child_returncode, 7)
        self.assertEqual(
            fixture.supervisor.health.last_failure()["classification"], "node_exit_nonzero"
        )

    def test_a_child_that_never_binds_is_not_ready(self) -> None:
        fixture = self.make_fixture(
            self.tmp, hold=3.0, code=0, bind=False, node_ready_timeout_sec=1.0
        )
        self.assertEqual(fixture.supervisor.supervise_once(), "failed")
        self.assertEqual(
            fixture.supervisor.health.last_failure()["classification"], "node_not_ready"
        )

    def test_engine_load_is_counted_once_per_node_start(self) -> None:
        fixture = self.make_fixture(self.tmp, hold=3.0, code=0)
        fixture.supervisor.supervise_once()
        fixture.supervisor.supervise_once()
        self.assertEqual(fixture.supervisor.node_start_count, 2)
        self.assertEqual(fixture.supervisor.engine_load_count, 2)

    def test_stop_terminates_exactly_the_recorded_child(self) -> None:
        fixture = self.make_fixture(self.tmp, hold=30.0, code=0)
        self.assertTrue(fixture.supervisor.spawn_node())
        pid = fixture.supervisor.child_pid
        self.assertIsNotNone(pid)
        result = fixture.supervisor.stop_node(reason="test")
        self.assertTrue(result["stopped"])
        self.assertEqual(result["node_pid"], pid)
        self.assertIsNone(fixture.supervisor.child)

    def test_stopping_when_nothing_runs_is_harmless(self) -> None:
        fixture = self.make_fixture(self.tmp, hold=0.1, code=0)
        self.assertFalse(fixture.supervisor.stop_node(reason="test")["stopped"])


class TestFailClosedPreflight(JetsonMachineMixin):
    def setUp(self) -> None:
        super(TestFailClosedPreflight, self).setUp()
        self._dir = tempfile.TemporaryDirectory(prefix="phase13f-pre-")
        self.tmp = self._dir.name
        self.addCleanup(self._dir.cleanup)

    def test_a_bad_engine_hash_withholds_authority_and_enters_safe_stop(self) -> None:
        fixture = self.make_fixture(self.tmp, hold=0.1, code=0)
        engine = os.path.join(self.tmp, "engine.plan")
        with open(engine, "ab") as handle:
            handle.write(b"tampered-after-manifest-was-written")
        self.assertFalse(fixture.supervisor.preflight())
        self.assertEqual(fixture.supervisor.health.state, STATE_SAFE_STOP)
        self.assertFalse(fixture.supervisor.health.ai_authority_permitted)
        failed = fixture.supervisor.preflight_report["failed_required_checks"]
        self.assertIn("engine_hash_match", failed)

    def test_a_missing_engine_withholds_authority(self) -> None:
        fixture = self.make_fixture(self.tmp, hold=0.1, code=0)
        os.unlink(os.path.join(self.tmp, "engine.plan"))
        self.assertFalse(fixture.supervisor.preflight())
        self.assertIn("engine_present", fixture.supervisor.preflight_report["failed_required_checks"])
        self.assertEqual(fixture.supervisor.health.state, STATE_SAFE_STOP)

    def test_a_missing_manifest_withholds_authority(self) -> None:
        fixture = self.make_fixture(self.tmp, hold=0.1, code=0)
        os.unlink(fixture.args.manifest)
        self.assertFalse(fixture.supervisor.preflight())
        self.assertIn(
            "manifest_loadable", fixture.supervisor.preflight_report["failed_required_checks"]
        )

    @unittest.skipIf(
        sys.platform.startswith("win"),
        "Windows SO_REUSEADDR permits rebinding a LISTENing port; Linux does not, "
        "so this check is only meaningful on the target and runs there in Gate A",
    )
    def test_a_port_already_held_is_caught_by_preflight(self) -> None:
        fixture = self.make_fixture(self.tmp, hold=0.1, code=0)
        fixture.args.skip_port_check = False
        holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        holder.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        holder.bind(("127.0.0.1", fixture.control_port))
        holder.listen(1)
        self.addCleanup(holder.close)
        fixture.supervisor.preflight()
        failed = fixture.supervisor.preflight_report["failed_required_checks"]
        self.assertIn("port_available_control", failed)

    def test_repository_sha_mismatch_withholds_authority(self) -> None:
        fixture = self.make_fixture(self.tmp, hold=0.1, code=0)
        fixture.args.expected_repo_sha = "c" * 40
        self.assertFalse(fixture.supervisor.preflight())
        self.assertIn(
            "repository_sha_match", fixture.supervisor.preflight_report["failed_required_checks"]
        )


class TestRestartStorm(JetsonMachineMixin):
    def setUp(self) -> None:
        super(TestRestartStorm, self).setUp()
        self._dir = tempfile.TemporaryDirectory(prefix="phase13f-storm-")
        self.tmp = self._dir.name
        self.addCleanup(self._dir.cleanup)

    def test_a_crash_loop_is_blocked_and_enters_failed(self) -> None:
        # A child that fails immediately, forever. The supervisor must stop
        # respawning rather than spin.
        fixture = self.make_fixture(
            self.tmp, hold=0.05, code=9, bind=False,
            node_ready_timeout_sec=0.5, max_restarts=3, restart_window_sec=300,
        )
        fixture.supervisor.args.skip_port_check = True
        # Belt and braces: if preflight ever fails here the supervisor must
        # exit rather than idle, so a broken fixture cannot hang the suite.
        fixture.supervisor.args.exit_on_preflight_failure = True
        exit_code = fixture.supervisor.run()
        self.assertTrue(fixture.supervisor.preflight_report["preflight_passed"],
                        fixture.supervisor.preflight_report["failed_required_checks"])
        self.assertEqual(exit_code, 4, "restart storm must exit non-zero for systemd")
        self.assertEqual(
            fixture.supervisor.health.last_failure()["classification"], "restart_storm_blocked"
        )
        # run() always ends in shutdown, which transitions to SAFE_STOP, so
        # FAILED is asserted where it actually happened: in the history.
        states = [item["to"] for item in fixture.supervisor.health.snapshot()["recent_transitions"]]
        self.assertIn(STATE_FAILED, states)
        self.assertEqual(fixture.supervisor.health.state, STATE_SAFE_STOP)
        # Bounded: it stopped at the limit rather than restarting indefinitely.
        self.assertLessEqual(fixture.supervisor.node_start_count, 3)


class TestBoundedLog(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory(prefix="phase13f-log-")
        self.tmp = self._dir.name
        self.addCleanup(self._dir.cleanup)

    def test_log_rotates_and_total_size_stays_bounded(self) -> None:
        path = os.path.join(self.tmp, "service.jsonl")
        log = BoundedJsonlLog(path, max_bytes=4096, backup_count=2)
        for index in range(4000):
            log.write("noise", index=index, payload="x" * 200)
        log.close()
        self.assertGreater(log.rotation_count, 0)
        total = 0
        for name in os.listdir(self.tmp):
            total += os.path.getsize(os.path.join(self.tmp, name))
        self.assertLessEqual(total, log.max_total_bytes + 8192)
        self.assertEqual(log.max_total_bytes, 4096 * 3)

    def test_old_generations_are_deleted_not_accumulated(self) -> None:
        path = os.path.join(self.tmp, "service.jsonl")
        log = BoundedJsonlLog(path, max_bytes=2048, backup_count=1)
        for index in range(3000):
            log.write("noise", index=index, payload="y" * 200)
        log.close()
        generations = [name for name in os.listdir(self.tmp) if name.startswith("service.jsonl")]
        self.assertLessEqual(len(generations), 2)

    def test_unserialisable_record_is_dropped_not_raised(self) -> None:
        log = BoundedJsonlLog(os.path.join(self.tmp, "s.jsonl"))
        log.write("ok", value=object())
        log.close()
        # default=str keeps it serialisable, so this must simply not raise.
        self.assertEqual(log.write_failure_count, 0)

    def test_a_pathless_log_still_counts(self) -> None:
        log = BoundedJsonlLog(None)
        log.write("event", a=1)
        self.assertEqual(log.written_count, 1)
        self.assertTrue(log.to_dict()["log_bounded"])


if __name__ == "__main__":
    unittest.main()
