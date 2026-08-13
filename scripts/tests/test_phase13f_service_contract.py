"""Phase 13F manifest, health-state, restart-policy and unit-template tests.

These cover the parts of the service contract that decide whether AI authority
may exist at all, so each one is written as "what must be refused" rather than
"what should work".
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from run_phase13f_install import (  # noqa: E402
    REQUIRED_DIRECTIVES,
    parse_directives,
    render,
    unresolved_placeholders,
    validate_unit,
)
from run_phase13f_service import RestartPolicy  # noqa: E402
from workers.core.service_health import (  # noqa: E402
    SERVICE_STATES,
    STATE_DEGRADED,
    STATE_FAILED,
    STATE_READY,
    STATE_RESTARTING,
    STATE_SAFE_STOP,
    STATE_STARTING,
    ServiceHealth,
    encode_status,
)
from workers.core.service_manifest import (  # noqa: E402
    MANIFEST_SCHEMA_VERSION,
    ManifestError,
    ServiceManifest,
    build_manifest,
    sha256_file,
)

UNIT_VALUES = {
    "SERVICE_NAME": "ma-vlna-jetson-node",
    "SERVICE_USER": "myjetsonnx",
    "SERVICE_GROUP": "myjetsonnx",
    "REPO_ROOT": "/home/myjetsonnx/Face_Detect_Realtime",
    "PYTHON": "/home/myjetsonnx/venvs/ma-vlna/bin/python",
    "MANIFEST": "config/phase13f_service_manifest.json",
    "ENV_FILE": "/etc/ma-vlna/jetson-node.env",
    "EVIDENCE_DIR": "/home/myjetsonnx/Face_Detect_Realtime/experiments/phase13",
    "LOG_DIR": "/home/myjetsonnx/ma-vlna-logs",
    "LOG_PATH": "/home/myjetsonnx/ma-vlna-logs/service.jsonl",
    "STAGING_DIR": "/home/myjetsonnx/ma-vlna-staging",
}


class TestManifest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="phase13f-manifest-")
        self.engine = os.path.join(self.tmp, "engine.plan")
        with open(self.engine, "wb") as handle:
            handle.write(b"not-a-real-engine-but-a-real-file")

    def _write(self, payload) -> str:
        path = os.path.join(self.tmp, "manifest.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        return path

    def _valid_payload(self):
        return build_manifest(
            service_name="ma-vlna-jetson-node",
            repository_sha="a" * 40,
            engine_path=self.engine,
        )

    def test_a_valid_manifest_loads_and_verifies(self) -> None:
        manifest = ServiceManifest.load(self._write(self._valid_payload()))
        report = manifest.verify_engine()
        self.assertTrue(report["engine_hash_match"])
        self.assertEqual(report["classification"], "ok")
        self.assertEqual(manifest.precision, "fp16")

    def test_a_changed_engine_fails_the_hash_check(self) -> None:
        path = self._write(self._valid_payload())
        with open(self.engine, "ab") as handle:
            handle.write(b"tampered")
        report = ServiceManifest.load(path).verify_engine()
        self.assertFalse(report["engine_hash_match"])
        self.assertEqual(report["classification"], "engine_hash_mismatch")

    def test_a_missing_engine_is_reported_not_raised(self) -> None:
        path = self._write(self._valid_payload())
        os.unlink(self.engine)
        report = ServiceManifest.load(path).verify_engine()
        self.assertEqual(report["classification"], "engine_missing")
        self.assertFalse(report["engine_hash_match"])

    def test_another_schema_version_is_refused(self) -> None:
        payload = self._valid_payload()
        payload["schema_version"] = MANIFEST_SCHEMA_VERSION + 1
        with self.assertRaises(ManifestError) as ctx:
            ServiceManifest.load(self._write(payload))
        self.assertEqual(ctx.exception.classification, "manifest_schema_mismatch")

    def test_int8_cannot_be_declared_authoritative(self) -> None:
        payload = self._valid_payload()
        payload["int8_authoritative"] = True
        with self.assertRaises(ManifestError) as ctx:
            ServiceManifest.load(self._write(payload))
        self.assertEqual(ctx.exception.classification, "manifest_int8_authority_forbidden")

    def test_int8_role_cannot_be_relabelled(self) -> None:
        payload = self._valid_payload()
        payload["int8_role"] = "authoritative"
        with self.assertRaises(ManifestError) as ctx:
            ServiceManifest.load(self._write(payload))
        self.assertEqual(ctx.exception.classification, "manifest_int8_authority_forbidden")

    def test_int8_precision_cannot_hold_authority(self) -> None:
        payload = self._valid_payload()
        payload["precision"] = "int8"
        with self.assertRaises(ManifestError) as ctx:
            ServiceManifest.load(self._write(payload))
        self.assertEqual(ctx.exception.classification, "manifest_precision_forbidden")

    def test_a_corrupt_manifest_is_refused(self) -> None:
        path = os.path.join(self.tmp, "bad.json")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        with self.assertRaises(ManifestError) as ctx:
            ServiceManifest.load(path)
        self.assertEqual(ctx.exception.classification, "manifest_unparsable")

    def test_a_missing_manifest_is_refused(self) -> None:
        with self.assertRaises(ManifestError) as ctx:
            ServiceManifest.load(os.path.join(self.tmp, "absent.json"))
        self.assertEqual(ctx.exception.classification, "manifest_missing")

    def test_incomplete_manifest_names_the_missing_fields(self) -> None:
        with self.assertRaises(ManifestError) as ctx:
            ServiceManifest.load(self._write({"schema_version": MANIFEST_SCHEMA_VERSION}))
        self.assertEqual(ctx.exception.classification, "manifest_incomplete")

    def test_a_malformed_hash_is_refused(self) -> None:
        payload = self._valid_payload()
        payload["engine_sha256"] = "zzzz"
        with self.assertRaises(ManifestError) as ctx:
            ServiceManifest.load(self._write(payload))
        self.assertEqual(ctx.exception.classification, "manifest_hash_malformed")

    def test_manifest_hash_changes_with_content(self) -> None:
        first = ServiceManifest(self._valid_payload()).manifest_sha256
        payload = self._valid_payload()
        payload["service_name"] = "something-else"
        self.assertNotEqual(first, ServiceManifest(payload).manifest_sha256)

    def test_streamed_file_hash_matches_hashlib(self) -> None:
        import hashlib

        with open(self.engine, "rb") as handle:
            expected = hashlib.sha256(handle.read()).hexdigest()
        self.assertEqual(sha256_file(self.engine, chunk_bytes=7), expected)


class TestHealthStates(unittest.TestCase):
    def test_only_ready_may_hold_authority(self) -> None:
        health = ServiceHealth()
        for state in SERVICE_STATES:
            health.transition(state, "test")
            self.assertEqual(
                health.ai_authority_permitted, state == STATE_READY,
                "%s must%s permit authority" % (state, "" if state == STATE_READY else " not"),
            )

    def test_starting_state_has_no_authority(self) -> None:
        self.assertFalse(ServiceHealth().ai_authority_permitted)

    def test_transitions_are_counted_and_bounded(self) -> None:
        health = ServiceHealth(history_capacity=4)
        for index in range(20):
            health.transition(STATE_READY if index % 2 else STATE_DEGRADED, "flap")
        snapshot = health.snapshot()
        self.assertEqual(snapshot["history_capacity"], 4)
        self.assertLessEqual(len(snapshot["recent_transitions"]), 4)
        self.assertEqual(health.transition_count, 20)

    def test_restart_and_safe_stop_counters(self) -> None:
        health = ServiceHealth()
        health.transition(STATE_RESTARTING, "a")
        health.transition(STATE_READY, "b")
        health.transition(STATE_RESTARTING, "c")
        health.transition(STATE_SAFE_STOP, "d")
        self.assertEqual(health.restart_count, 2)
        self.assertEqual(health.safe_stop_count, 1)

    def test_repeat_transition_is_not_counted(self) -> None:
        health = ServiceHealth()
        health.transition(STATE_READY, "first")
        self.assertFalse(health.transition(STATE_READY, "again"))
        self.assertEqual(health.transition_count, 1)

    def test_unknown_state_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ServiceHealth().transition("SOMEWHAT_READY")

    def test_failures_are_bounded_and_last_is_available(self) -> None:
        health = ServiceHealth(failure_capacity=3)
        for index in range(10):
            health.record_failure("kind_%d" % index, "detail")
        self.assertEqual(len(health.snapshot()["recent_failures"]), 3)
        self.assertEqual(health.last_failure()["classification"], "kind_9")

    def test_heartbeat_age_is_none_until_first_beat(self) -> None:
        health = ServiceHealth()
        self.assertIsNone(health.heartbeat_age_sec())
        health.heartbeat()
        self.assertIsNotNone(health.heartbeat_age_sec())

    def test_status_encoding_is_capped(self) -> None:
        health = ServiceHealth(history_capacity=500, failure_capacity=500)
        for index in range(400):
            health.record_failure("kind", "x" * 300)
            health.transition(STATE_READY if index % 2 else STATE_DEGRADED, "y" * 200)
        encoded = encode_status(health.snapshot(history_limit=500, failure_limit=500), max_bytes=4096)
        self.assertLessEqual(len(encoded), 4096)
        self.assertTrue(json.loads(encoded.decode("utf-8"))["status_truncated"])

    def test_capped_status_is_still_valid_json(self) -> None:
        payload = {"service_name": "x", "state": "READY", "blob": "y" * 100000,
                   "recent_transitions": [], "recent_failures": []}
        decoded = json.loads(encode_status(payload, max_bytes=512).decode("utf-8"))
        self.assertTrue(decoded["status_truncated"])


class TestRestartPolicy(unittest.TestCase):
    def test_backoff_grows_and_is_capped(self) -> None:
        policy = RestartPolicy(initial_sec=1.0, max_sec=10.0, factor=2.0)
        observed = []
        for _ in range(8):
            policy.on_failure()
            observed.append(policy.backoff_sec())
        self.assertEqual(observed[:4], [1.0, 2.0, 4.0, 8.0])
        self.assertTrue(all(value <= 10.0 for value in observed))
        self.assertEqual(observed[-1], 10.0)

    def test_clean_exit_resets_backoff(self) -> None:
        policy = RestartPolicy(initial_sec=1.0, max_sec=10.0)
        policy.on_failure()
        policy.on_failure()
        self.assertGreater(policy.backoff_sec(), 0)
        policy.on_clean_exit()
        self.assertEqual(policy.backoff_sec(), 0.0)

    def test_storm_is_detected_at_the_limit(self) -> None:
        policy = RestartPolicy(max_restarts=3, window_sec=100.0)
        now = 1000.0
        for index in range(2):
            policy.record_restart(now + index)
        self.assertFalse(policy.storm_detected(now + 2))
        policy.record_restart(now + 2)
        self.assertTrue(policy.storm_detected(now + 2))

    def test_restarts_outside_the_window_do_not_count(self) -> None:
        policy = RestartPolicy(max_restarts=3, window_sec=60.0)
        policy.record_restart(1000.0)
        policy.record_restart(1001.0)
        policy.record_restart(2000.0)
        # The two old ones aged out; only the recent one is in the window.
        self.assertEqual(policy.restarts_in_window(2000.0), 1)
        self.assertFalse(policy.storm_detected(2000.0))

    def test_restart_history_stays_bounded(self) -> None:
        policy = RestartPolicy(max_restarts=3, window_sec=10.0)
        for index in range(1000):
            policy.record_restart(1000.0 + index)
        # Only the trailing window is retained, not 1000 timestamps.
        self.assertLessEqual(len(policy.restart_times), 11)


class TestUnitTemplate(unittest.TestCase):
    def setUp(self) -> None:
        self.text = render(UNIT_VALUES)

    def test_rendered_unit_has_no_unresolved_directives(self) -> None:
        self.assertEqual(unresolved_placeholders(self.text), [])

    def test_required_service_contract_directives_are_present(self) -> None:
        for directive in REQUIRED_DIRECTIVES:
            self.assertIn(directive, self.text, "missing %s" % directive)

    def test_unit_validates_against_the_jetsons_systemd_245(self) -> None:
        report = validate_unit(self.text, 245)
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["directives_newer_than_target"], [])

    def test_directives_newer_than_the_target_are_caught(self) -> None:
        # systemd 254 introduced RestartSteps; on 245 it must be flagged.
        broken = self.text.replace("RestartSec=5", "RestartSec=5\nRestartSteps=5")
        report = validate_unit(broken, 245)
        self.assertFalse(report["valid"])
        self.assertIn(
            "RestartSteps", [item["directive"] for item in report["directives_newer_than_target"]]
        )

    def test_wrong_restart_policy_is_caught(self) -> None:
        broken = self.text.replace("Restart=on-failure", "Restart=always")
        self.assertFalse(validate_unit(broken, 245)["valid"])

    def test_service_does_not_run_as_root(self) -> None:
        self.assertIn("User=myjetsonnx", self.text)
        self.assertNotIn("User=root", self.text)

    def test_secrets_are_not_shell_expanded_into_execstart(self) -> None:
        self.assertIn("EnvironmentFile=", self.text)
        # Scan directives, not prose: the template's own comments discuss
        # passwordless sudo, and matching that would be a false positive.
        for name, value in parse_directives(self.text):
            upper = ("%s=%s" % (name, value)).upper()
            for token in ("PASSWORD", "SECRET", "TOKEN"):
                self.assertNotIn(token, upper, "secret-looking directive: %s" % name)

    def test_inline_secret_environment_is_caught(self) -> None:
        broken = self.text.replace(
            "Type=notify", "Type=notify\nEnvironment=MA_VLNA_PASSWORD=hunter2"
        )
        report = validate_unit(broken, 245)
        self.assertFalse(report["valid"])
        self.assertTrue(report["inline_secret_suspects"])

    def test_runtime_directory_is_managed_by_systemd(self) -> None:
        self.assertIn("RuntimeDirectory=ma-vlna", self.text)
        self.assertIn("--runtime-dir %t/ma-vlna", self.text)


if __name__ == "__main__":
    unittest.main()
