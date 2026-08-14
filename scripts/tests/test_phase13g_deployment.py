"""Phase 13G deployment manager: the sixteen mandatory scenarios.

Each scenario drives the real manager against a fake systemd, so the activation
and rollback paths under test are the ones that will run on the Jetson — only
the service underneath is substituted. A mock of the manager itself would prove
nothing.

The fake models the three things that actually go wrong during an update: the
restart fails, the candidate never reaches READY, or it reaches READY and then
does not stay there.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tarfile
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from run_phase13g_deploy import DeploymentManager, parse_args  # noqa: E402
from workers.core.deployment_state import (  # noqa: E402
    ACTIVATING,
    CONFIRMED,
    FAILED,
    IDLE,
    PROBATION,
    ROLLED_BACK,
    STAGED,
    VALIDATED,
    DeploymentState,
)
from workers.core.release_manifest import build_release_manifest, sha256_file  # noqa: E402
from workers.core.release_store import (  # noqa: E402
    CURRENT_LINK,
    LAST_KNOWN_GOOD_LINK,
    PREVIOUS_LINK,
    ReleaseStore,
)


def _symlinks_supported() -> bool:
    """Whether this host can create symlinks at all.

    The store is Linux-targeted; Windows needs Developer Mode or admin rights.
    These cases run for real on the Jetson during Gate A on target, and a skip
    here is reported as a skip rather than counted as a pass.
    """

    if not hasattr(os, "symlink"):
        return False
    probe = tempfile.mkdtemp(prefix="symlink-probe-")
    try:
        target = os.path.join(probe, "target")
        os.makedirs(target)
        os.symlink("target", os.path.join(probe, "link"))
        return True
    except (OSError, NotImplementedError, AttributeError):
        return False
    finally:
        import shutil

        shutil.rmtree(probe, ignore_errors=True)


requires_symlinks = unittest.skipUnless(
    _symlinks_supported(), "symlinks unavailable on this host; runs on the Jetson"
)

TARGET_FACTS = {
    "arch": "aarch64", "python": "3.8.10", "l4t": "35.5.0",
    "jetpack": "5.1.3", "cuda": "11.4", "tensorrt": "8.5.2.2",
}


class FakeService:
    """A systemd service that can fail in the ways that matter."""

    def __init__(
        self,
        *,
        restart_ok: bool = True,
        restart_fails_for: Optional[Any] = None,
        ready_after_polls: int = 1,
        never_ready: bool = False,
        leave_ready_after_polls: Optional[int] = None,
        restart_storm_after_polls: Optional[int] = None,
        unit_inactive_after_polls: Optional[int] = None,
        release_provider: Optional[Any] = None,
    ) -> None:
        self.restart_ok = restart_ok
        # Releases whose ExecStart is broken. Realistic: the candidate
        # fails to start, the release being rolled back to does not.
        self.restart_fails_for = set(restart_fails_for or ())
        self.ready_after_polls = ready_after_polls
        self.never_ready = never_ready
        self.leave_ready_after_polls = leave_ready_after_polls
        self.restart_storm_after_polls = restart_storm_after_polls
        self.unit_inactive_after_polls = unit_inactive_after_polls
        self.release_provider = release_provider
        self.restart_count = 0
        self.health_polls = 0
        self.polls_since_restart = 0
        self.node_start_count = 1
        self.service_restart_count = 0

    def restart(self) -> Dict[str, Any]:
        self.restart_count += 1
        self.polls_since_restart = 0
        self.node_start_count += 1
        active = self.release_provider() if self.release_provider else None
        ok = bool(self.restart_ok) and active not in self.restart_fails_for
        return {
            "restarted": ok,
            "returncode": 0 if ok else 1,
            "active_release_id": active,
            "command": "fake systemctl restart",
        }

    def properties(self) -> Dict[str, str]:
        inactive = (
            self.unit_inactive_after_polls is not None
            and self.polls_since_restart >= self.unit_inactive_after_polls
        )
        return {
            "ActiveState": "failed" if inactive else "active",
            "SubState": "failed" if inactive else "running",
            "MainPID": "4242",
            "NRestarts": str(self.service_restart_count),
        }

    def health(self) -> Dict[str, Any]:
        self.health_polls += 1
        self.polls_since_restart += 1
        if self.never_ready:
            return {"state": "STARTING", "ai_authority_permitted": False}
        if self.polls_since_restart < self.ready_after_polls:
            return {"state": "STARTING", "ai_authority_permitted": False}
        if (
            self.leave_ready_after_polls is not None
            and self.polls_since_restart > self.leave_ready_after_polls
        ):
            return {"state": "SAFE_STOP", "ai_authority_permitted": False}
        if (
            self.restart_storm_after_polls is not None
            and self.polls_since_restart > self.restart_storm_after_polls
        ):
            self.service_restart_count += 1
        return {
            "state": "READY",
            "ai_authority_permitted": True,
            "engine_sha256": "e" * 64,
            "repository_sha": "a" * 40,
            "node_start_count": self.node_start_count,
            "restart_count": self.service_restart_count,
            "release_id": self.release_provider() if self.release_provider else None,
        }


class DeploymentFixture:
    """A store with release A active, and a candidate package B on disk."""

    def __init__(self, tmp: str, **service_kwargs) -> None:
        self.tmp = tmp
        self.root = os.path.join(tmp, "opt")
        self.store = ReleaseStore(self.root)
        self.store.ensure_layout()
        self.engine = os.path.join(tmp, "engine.plan")
        with open(self.engine, "wb") as handle:
            handle.write(b"fp16-engine-bytes")
        self.startup = os.path.join(tmp, "startup.json")
        with open(self.startup, "w", encoding="utf-8") as handle:
            handle.write("{}")
        self.service = FakeService(
            release_provider=lambda: self.store.resolve(CURRENT_LINK), **service_kwargs
        )
        self.args = self._args()
        self.manager = DeploymentManager(self.args, service=self.service)

    def _args(self) -> argparse.Namespace:
        return parse_args([
            "status",
            "--root", self.root,
            "--ready-timeout-sec", "3",
            "--probation-sec", "1",
            "--rollback-timeout-sec", "3",
            "--poll-sec", "0.01",
            "--skip-tensorrt-check",
            "--skip-service-status",
        ])

    def manifest_payload(self, release_id: str, **overrides) -> Dict[str, Any]:
        payload = build_release_manifest(
            release_id=release_id,
            source_git_sha="a" * 40,
            created_at_utc="2026-01-01T00:00:00Z",
            package_sha256="0" * 64,
            engine_path=self.engine,
            engine_sha256=sha256_file(self.engine),
            engine_manifest_sha256=sha256_file(self.startup),
            facts=dict(TARGET_FACTS),
            extra={"engine_manifest_path": self.startup},
        )
        payload.update(overrides)
        return payload

    def build_package(self, release_id: str, **manifest_overrides):
        """Create a package plus a manifest whose hash matches it."""

        payload_dir = os.path.join(self.tmp, "payload-%s" % release_id)
        os.makedirs(os.path.join(payload_dir, "scripts"), exist_ok=True)
        with open(os.path.join(payload_dir, "scripts", "run.py"), "w", encoding="utf-8") as handle:
            handle.write("# %s\n" % release_id)
        package = os.path.join(self.tmp, "%s.tar.gz" % release_id)
        with tarfile.open(package, "w:gz") as archive:
            archive.add(payload_dir, arcname=release_id)
        payload = self.manifest_payload(release_id, package_sha256=sha256_file(package))
        payload.update(manifest_overrides)
        manifest_path = os.path.join(self.tmp, "%s.manifest.json" % release_id)
        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        return package, manifest_path

    def install_release_a(self) -> str:
        package, manifest = self.build_package("relA")
        self.manager.stage(package, manifest)
        self.manager.validate("relA")
        self.store.set_link_atomic(CURRENT_LINK, "relA")
        self.store.set_link_atomic(LAST_KNOWN_GOOD_LINK, "relA")
        self.manager.state.reset_to_idle("release A is the baseline")
        self.manager.state.set(
            active_release_id="relA", last_known_good_release_id="relA",
        )
        return "relA"

    def patch_facts(self, **overrides) -> None:
        facts = dict(TARGET_FACTS)
        facts.update(overrides)
        import workers.core.release_manifest as rm
        import run_phase13g_deploy as deploy

        deploy.target_facts = lambda **_kwargs: dict(facts)


@requires_symlinks
class DeploymentScenarioTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory(prefix="phase13g-deploy-")
        self.addCleanup(self._dir.cleanup)
        self.tmp = self._dir.name
        import run_phase13g_deploy as deploy

        self._original_facts = deploy.target_facts
        deploy.target_facts = lambda **_kwargs: dict(TARGET_FACTS)
        self.addCleanup(self._restore_facts)

    def _restore_facts(self) -> None:
        import run_phase13g_deploy as deploy

        deploy.target_facts = self._original_facts

    def fixture(self, **service_kwargs) -> DeploymentFixture:
        return DeploymentFixture(self.tmp, **service_kwargs)


class TestSuccessfulUpdate(DeploymentScenarioTest):
    """Scenario 1: a clean A -> B update."""

    def test_a_to_b_update_confirms_b(self) -> None:
        fixture = self.fixture()
        fixture.install_release_a()
        package, manifest = fixture.build_package("relB")

        staged = fixture.manager.stage(package, manifest)
        self.assertTrue(staged["ok"], staged)
        self.assertEqual(fixture.manager.state.state, STAGED)

        validated = fixture.manager.validate()
        self.assertTrue(validated["ok"], validated["compatibility"]["failed_checks"])
        self.assertEqual(fixture.manager.state.state, VALIDATED)

        activated = fixture.manager.activate()
        self.assertTrue(activated["ok"], activated)
        self.assertTrue(activated["switch"]["atomic"])
        self.assertTrue(activated["ready"]["ready"])
        self.assertTrue(activated["probation"]["passed"])

        self.assertEqual(fixture.store.resolve(CURRENT_LINK), "relB")
        self.assertEqual(fixture.store.resolve(PREVIOUS_LINK), "relA")
        self.assertEqual(fixture.store.resolve(LAST_KNOWN_GOOD_LINK), "relB")
        self.assertEqual(fixture.manager.state.state, CONFIRMED)
        self.assertEqual(fixture.store.partial_release_count(), 0)

    def test_the_service_is_restarted_exactly_once_for_a_clean_update(self) -> None:
        # A new service process is what produces a new run id, lease and clock
        # sync; more than one restart would mean something retried silently.
        fixture = self.fixture()
        fixture.install_release_a()
        package, manifest = fixture.build_package("relB")
        fixture.manager.stage(package, manifest)
        fixture.manager.validate()
        fixture.manager.activate()
        self.assertEqual(fixture.service.restart_count, 1)


class TestCandidateRejection(DeploymentScenarioTest):
    """Scenarios 2-6: a candidate that must never reach authority."""

    def _staged_then_validated(self, **manifest_overrides):
        fixture = self.fixture()
        fixture.install_release_a()
        package, manifest = fixture.build_package("relB", **manifest_overrides)
        staged = fixture.manager.stage(package, manifest)
        return fixture, staged

    def test_source_sha_mismatch_is_rejected(self) -> None:
        fixture, staged = self._staged_then_validated()
        self.assertTrue(staged["ok"])
        fixture.args.expected_source_sha = "f" * 40
        result = fixture.manager.validate()
        self.assertFalse(result["ok"])
        self.assertIn("source_git_sha_matches", result["compatibility"]["failed_checks"])
        self.assertEqual(fixture.store.resolve(CURRENT_LINK), "relA")

    def test_package_hash_mismatch_is_rejected_before_unpacking(self) -> None:
        fixture = self.fixture()
        fixture.install_release_a()
        package, manifest = fixture.build_package("relB")
        # Corrupt the package after its hash was recorded.
        with open(package, "ab") as handle:
            handle.write(b"tampered")
        result = fixture.manager.stage(package, manifest)
        self.assertFalse(result["ok"])
        self.assertEqual(result["classification"], "package_hash_mismatch")
        # Nothing was installed, so the store cannot hold a bad release.
        self.assertNotIn("relB", fixture.store.list_releases())
        self.assertEqual(fixture.store.resolve(CURRENT_LINK), "relA")

    def test_engine_hash_mismatch_is_rejected(self) -> None:
        fixture, staged = self._staged_then_validated(engine_sha256="d" * 64)
        result = fixture.manager.validate()
        self.assertFalse(result["ok"])
        self.assertIn("engine_sha256_matches", result["compatibility"]["failed_checks"])
        self.assertEqual(fixture.manager.state.state, FAILED)

    def test_protocol_incompatibility_is_rejected(self) -> None:
        fixture, _ = self._staged_then_validated(command_packet_size=32)
        result = fixture.manager.validate()
        self.assertFalse(result["ok"])
        self.assertIn("protocol_command_packet_size", result["compatibility"]["failed_checks"])

    def test_missing_manifest_field_is_rejected_at_stage(self) -> None:
        # "Missing environment field": a manifest that does not describe the
        # service schema cannot be checked against the installed environment.
        fixture = self.fixture()
        fixture.install_release_a()
        package, manifest_path = fixture.build_package("relB")
        with open(manifest_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        del payload["service_schema_version"]
        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        result = fixture.manager.stage(package, manifest_path)
        self.assertFalse(result["ok"])
        self.assertEqual(result["classification"], "manifest_incomplete")

    def test_int8_authority_request_is_rejected(self) -> None:
        fixture = self.fixture()
        fixture.install_release_a()
        package, manifest_path = fixture.build_package("relB")
        with open(manifest_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        payload["int8_authority_allowed"] = True
        with open(manifest_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        result = fixture.manager.stage(package, manifest_path)
        self.assertFalse(result["ok"])
        self.assertEqual(result["classification"], "manifest_int8_authority_forbidden")

    def test_a_rejected_candidate_never_becomes_current(self) -> None:
        for overrides in ({"engine_sha256": "d" * 64}, {"jilf_header_size": 99},
                          {"jila_packet_size": 1}):
            fixture, _ = self._staged_then_validated(**overrides)
            fixture.manager.validate()
            self.assertEqual(
                fixture.store.resolve(CURRENT_LINK), "relA",
                "current moved for an invalid candidate: %s" % overrides,
            )


class TestAutomaticRollback(DeploymentScenarioTest):
    """Scenarios 7, 8, 9, 14, 15: failures after the switch."""

    def _activate_failing(self, **service_kwargs):
        fixture = self.fixture(**service_kwargs)
        fixture.install_release_a()
        package, manifest = fixture.build_package("relB")
        fixture.manager.stage(package, manifest)
        fixture.manager.validate()
        return fixture, fixture.manager.activate()

    def test_service_startup_failure_rolls_back(self) -> None:
        # Only the candidate is broken; rolling back to A must still work.
        fixture, result = self._activate_failing(restart_fails_for={"relB"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["classification"], "service_restart_failed")
        self.assertTrue(result["rolled_back"])
        self.assertEqual(fixture.store.resolve(CURRENT_LINK), "relA")
        self.assertEqual(fixture.manager.state.state, ROLLED_BACK)

    def test_candidate_that_never_becomes_ready_rolls_back(self) -> None:
        fixture, result = self._activate_failing(never_ready=True)
        self.assertFalse(result["ok"])
        self.assertEqual(result["classification"], "candidate_not_ready")
        self.assertEqual(fixture.store.resolve(CURRENT_LINK), "relA")

    def test_watchdog_failure_during_probation_rolls_back(self) -> None:
        # Leaving READY mid-probation is what a watchdog kill looks like from
        # the deployment manager's side.
        fixture, result = self._activate_failing(leave_ready_after_polls=2)
        self.assertFalse(result["ok"])
        self.assertEqual(result["classification"], "probation_failed")
        self.assertEqual(result["probation"]["reason"], "state_left_ready")
        self.assertEqual(fixture.store.resolve(CURRENT_LINK), "relA")

    def test_restart_storm_during_probation_rolls_back(self) -> None:
        fixture, result = self._activate_failing(restart_storm_after_polls=1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["probation"]["reason"], "restart_storm_during_probation")
        self.assertEqual(fixture.store.resolve(CURRENT_LINK), "relA")

    def test_unit_leaving_active_during_probation_rolls_back(self) -> None:
        fixture, result = self._activate_failing(unit_inactive_after_polls=2)
        self.assertFalse(result["ok"])
        self.assertEqual(result["probation"]["reason"], "unit_left_active")

    def test_last_known_good_is_preserved_through_a_failed_update(self) -> None:
        fixture, result = self._activate_failing(never_ready=True)
        self.assertEqual(fixture.store.resolve(LAST_KNOWN_GOOD_LINK), "relA")

    def test_rollback_that_also_fails_is_recorded_as_failed(self) -> None:
        # Scenario 15: the worst case -- nothing will start. It must not be
        # dressed up as recovered.
        fixture = self.fixture(never_ready=True)
        fixture.install_release_a()
        package, manifest = fixture.build_package("relB")
        fixture.manager.stage(package, manifest)
        fixture.manager.validate()
        result = fixture.manager.activate()
        self.assertFalse(result["ok"])
        self.assertFalse(result["auto_rollback"]["ok"])
        self.assertEqual(fixture.manager.state.state, FAILED)


class TestManualRollback(DeploymentScenarioTest):
    """Scenario 13: an operator reverts B to A."""

    def test_manual_rollback_returns_to_a(self) -> None:
        fixture = self.fixture()
        fixture.install_release_a()
        package, manifest = fixture.build_package("relB")
        fixture.manager.stage(package, manifest)
        fixture.manager.validate()
        self.assertTrue(fixture.manager.activate()["ok"])
        self.assertEqual(fixture.store.resolve(CURRENT_LINK), "relB")

        result = fixture.manager.rollback(target="relA", reason="manual")
        self.assertTrue(result["ok"], result)
        self.assertEqual(fixture.store.resolve(CURRENT_LINK), "relA")
        self.assertEqual(fixture.manager.state.state, ROLLED_BACK)
        # Two restarts total: one to activate B, one to return to A.
        self.assertEqual(fixture.service.restart_count, 2)

    def test_rollback_to_a_missing_release_is_refused(self) -> None:
        fixture = self.fixture()
        fixture.install_release_a()
        result = fixture.manager.rollback(target="relZ", reason="manual")
        self.assertFalse(result["ok"])
        self.assertEqual(fixture.store.resolve(CURRENT_LINK), "relA")


class TestInterruptionRecovery(DeploymentScenarioTest):
    """Scenarios 10, 11, 12: staging and reboots at the dangerous moments."""

    def test_interrupted_staging_leaves_no_installed_release(self) -> None:
        fixture = self.fixture()
        fixture.install_release_a()
        # A payload directory exists but the marker was never written.
        partial = fixture.store.release_path("relPartial")
        os.makedirs(partial, exist_ok=True)
        with open(os.path.join(partial, "half"), "w", encoding="utf-8") as handle:
            handle.write("x")
        self.assertFalse(fixture.store.is_installed("relPartial"))
        self.assertEqual(fixture.store.resolve(CURRENT_LINK), "relA")

    def test_reboot_before_the_switch_discards_the_candidate(self) -> None:
        fixture = self.fixture()
        fixture.install_release_a()
        package, manifest = fixture.build_package("relB")
        fixture.manager.stage(package, manifest)
        fixture.manager.validate()
        # A reboot here: a fresh manager reads the persisted state.
        resumed = DeploymentManager(fixture.args, service=fixture.service)
        report = resumed.resume()
        self.assertEqual(report["decision"]["action"], "discard_candidate")
        self.assertEqual(fixture.store.resolve(CURRENT_LINK), "relA")
        self.assertEqual(resumed.state.state, IDLE)

    def test_reboot_after_the_switch_rolls_back_to_last_known_good(self) -> None:
        fixture = self.fixture()
        fixture.install_release_a()
        package, manifest = fixture.build_package("relB")
        fixture.manager.stage(package, manifest)
        fixture.manager.validate()
        # Simulate dying immediately after the atomic switch.
        fixture.manager.state.transition(ACTIVATING, "switching", candidate_release_id="relB")
        fixture.store.set_link_atomic(PREVIOUS_LINK, "relA")
        fixture.store.set_link_atomic(CURRENT_LINK, "relB")
        fixture.manager.state.set(switch_completed=True, active_release_id="relB")

        resumed = DeploymentManager(fixture.args, service=fixture.service)
        report = resumed.resume()
        self.assertEqual(report["decision"]["action"], "rollback_to_last_known_good")
        self.assertTrue(report["ok"], report)
        self.assertEqual(fixture.store.resolve(CURRENT_LINK), "relA")

    def test_reboot_during_probation_rolls_back_by_default(self) -> None:
        fixture = self.fixture()
        fixture.install_release_a()
        package, manifest = fixture.build_package("relB")
        fixture.manager.stage(package, manifest)
        fixture.manager.validate()
        fixture.manager.state.transition(ACTIVATING, "a", candidate_release_id="relB")
        fixture.store.set_link_atomic(PREVIOUS_LINK, "relA")
        fixture.store.set_link_atomic(CURRENT_LINK, "relB")
        fixture.manager.state.set(switch_completed=True)
        fixture.manager.state.transition(PROBATION, "p")

        resumed = DeploymentManager(fixture.args, service=fixture.service)
        report = resumed.resume()
        self.assertEqual(report["decision"]["action"], "rollback_to_last_known_good")
        self.assertEqual(fixture.store.resolve(CURRENT_LINK), "relA")

    def test_resume_policy_can_finish_probation_instead(self) -> None:
        fixture = self.fixture()
        fixture.install_release_a()
        package, manifest = fixture.build_package("relB")
        fixture.manager.stage(package, manifest)
        fixture.manager.validate()
        fixture.manager.state.transition(ACTIVATING, "a", candidate_release_id="relB")
        fixture.store.set_link_atomic(PREVIOUS_LINK, "relA")
        fixture.store.set_link_atomic(CURRENT_LINK, "relB")
        fixture.manager.state.set(switch_completed=True)
        fixture.manager.state.transition(
            PROBATION, "p", probation_deadline_epoch=time.time() + 0.2
        )

        fixture.args.on_boot_unconfirmed = "resume"
        resumed = DeploymentManager(fixture.args, service=fixture.service)
        report = resumed.resume()
        self.assertEqual(report["decision"]["action"], "resume_probation")
        self.assertTrue(report["ok"], report)
        self.assertEqual(fixture.store.resolve(CURRENT_LINK), "relB")
        self.assertEqual(fixture.store.resolve(LAST_KNOWN_GOOD_LINK), "relB")

    def test_recovery_is_deterministic_for_the_same_state(self) -> None:
        # Two independent readers of the same state file must decide the same
        # thing; a recovery that depends on timing is not a recovery.
        fixture = self.fixture()
        fixture.install_release_a()
        fixture.manager.state.transition(STAGED, "s", candidate_release_id="relB")
        fixture.manager.state.transition(VALIDATED, "v")
        fixture.manager.state.transition(ACTIVATING, "a")
        first = DeploymentManager(fixture.args, service=fixture.service)
        second = DeploymentManager(fixture.args, service=fixture.service)
        self.assertEqual(
            first.state.recovery_decision()["action"],
            second.state.recovery_decision()["action"],
        )


class TestAuthorityAndCleanup(DeploymentScenarioTest):
    """Scenario 16 and the retention guarantees."""

    def test_authority_is_fail_closed_across_the_whole_switch(self) -> None:
        fixture = self.fixture()
        fixture.install_release_a()
        package, manifest = fixture.build_package("relB")
        fixture.manager.stage(package, manifest)
        fixture.manager.validate()
        self.assertFalse(fixture.manager.state.authority_fail_closed)
        fixture.manager.state.transition(ACTIVATING, "a")
        self.assertTrue(fixture.manager.state.authority_fail_closed)
        fixture.manager.state.transition(PROBATION, "p")
        self.assertTrue(fixture.manager.state.authority_fail_closed)
        fixture.manager.state.transition(CONFIRMED, "c")
        self.assertFalse(fixture.manager.state.authority_fail_closed)

    def test_activation_forces_a_new_service_process(self) -> None:
        # A new process is what invalidates old sessions: the node takes a new
        # run id and the PC grants a new lease, so packets minted against the
        # old lease are refused by the frozen Phase 13A rule.
        fixture = self.fixture()
        fixture.install_release_a()
        package, manifest = fixture.build_package("relB")
        fixture.manager.stage(package, manifest)
        fixture.manager.validate()
        before = fixture.service.node_start_count
        fixture.manager.activate()
        self.assertGreater(fixture.service.node_start_count, before)

    def test_a_staged_candidate_can_be_replaced_before_activation(self) -> None:
        # Nothing has moved in production yet, so staging a different
        # candidate is an ordinary operation rather than an error.
        fixture = self.fixture()
        fixture.install_release_a()
        first_pkg, first_man = fixture.build_package("relB")
        self.assertTrue(fixture.manager.stage(first_pkg, first_man)["ok"])
        second_pkg, second_man = fixture.build_package("relC")
        result = fixture.manager.stage(second_pkg, second_man)
        self.assertTrue(result["ok"], result)
        self.assertEqual(fixture.manager.state.candidate_release_id, "relC")
        self.assertEqual(fixture.store.resolve(CURRENT_LINK), "relA")

    def test_cleanup_keeps_current_previous_and_last_known_good(self) -> None:
        fixture = self.fixture()
        fixture.install_release_a()
        package, manifest = fixture.build_package("relB")
        fixture.manager.stage(package, manifest)
        fixture.manager.validate()
        fixture.manager.activate()
        for extra in ("relC", "relD"):
            pkg, man = fixture.build_package(extra)
            fixture.manager.stage(pkg, man)
        fixture.args.keep = 2
        report = fixture.manager.cleanup()
        self.assertEqual(fixture.store.resolve(CURRENT_LINK), "relB")
        for protected in ("relA", "relB"):
            self.assertNotIn(protected, report["removed"])
        self.assertGreaterEqual(len(fixture.store.list_releases()), 2)

    def test_status_declares_the_phase_boundary(self) -> None:
        fixture = self.fixture()
        status = fixture.manager.status()
        for claim in ("signed", "secure_boot", "bootloader_ab", "anti_rollback_security"):
            self.assertFalse(status[claim])
        self.assertTrue(status["integrity_only"])


if __name__ == "__main__":
    unittest.main()
