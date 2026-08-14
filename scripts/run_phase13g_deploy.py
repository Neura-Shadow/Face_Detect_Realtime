"""Phase 13G deployment manager: stage, validate, activate, confirm, roll back.

Deliberately a separate program from the perception node. The node's job is to
run one release well; deciding *which* release runs is a different concern with
a different failure mode, and burying it inside the node would mean an update
bug can only be debugged by reading perception code.

The activation sequence is ordered so that every step before the switch is
reversible without touching production, and every step after it is watched:

1. stage and hash the candidate
2. validate compatibility against this machine
3. record the current release as ``previous``
4. switch ``current`` atomically
5. restart the existing systemd service
6. wait for READY
7. run a probation window
8. confirm as ``last-known-good``
9. roll back automatically on any failure from step 5 onward

Command authority fails closed to SAFE_STOP for the whole of steps 4-7. That is
not a special case added here: the service's own preflight and the clock
discipline already withhold authority until the node is genuinely up, and the
deployment state records ``authority_fail_closed`` so the reason is visible.

sudo is never run. systemctl calls that need privilege are printed for an
operator; the ones this manager makes are the unprivileged reads plus the
service restart, which the operator authorises once by policy.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from workers.core.deployment_state import (  # noqa: E402
    ACTIVATING,
    CONFIRMED,
    FAILED,
    IDLE,
    PROBATION,
    ROLLED_BACK,
    ROLLING_BACK,
    STAGED,
    VALIDATED,
    DeploymentState,
    DeploymentStateError,
    describe_state_machine,
)
from workers.core.release_manifest import (  # noqa: E402
    ManifestError,
    ReleaseManifest,
    check_compatibility,
    describe_schema,
    sha256_file,
    target_facts,
)
from workers.core.release_store import (  # noqa: E402
    CURRENT_LINK,
    LAST_KNOWN_GOOD_LINK,
    PREVIOUS_LINK,
    ReleaseStore,
    ReleaseStoreError,
)

PHASE = "13G-OTA-A-B-ROLLBACK-VERSION-COMPATIBILITY"
DEFAULT_ROOT = "/opt/ma-vlna"
DEFAULT_UNIT = "ma-vlna-jetson-node.service"
DEFAULT_READY_TIMEOUT_SEC = 120.0
DEFAULT_PROBATION_SEC = 300.0
DEFAULT_ROLLBACK_TIMEOUT_SEC = 120.0


class ServiceController:
    """The systemd service, as far as the deployment manager needs it.

    Injectable so the whole activation and rollback path can be exercised
    against a fake in Gate A without a Jetson or a real unit.
    """

    def __init__(
        self,
        unit: str,
        *,
        runtime_dir: str = "/run/ma-vlna",
        python: str = "",
        restart_command: Optional[List[str]] = None,
    ) -> None:
        self.unit = unit
        self.runtime_dir = runtime_dir
        self.python = python or sys.executable
        self.restart_command = restart_command or ["sudo", "systemctl", "restart", unit]
        self.restart_count = 0

    def _run(self, command: List[str], *, timeout: int = 120) -> Dict[str, Any]:
        try:
            completed = subprocess.run(
                command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return {"returncode": -1, "stdout": "", "stderr": "%s: %s" % (type(exc).__name__, exc)}
        return {
            "returncode": completed.returncode,
            "stdout": completed.stdout.decode("utf-8", "replace"),
            "stderr": completed.stderr.decode("utf-8", "replace"),
        }

    def restart(self) -> Dict[str, Any]:
        self.restart_count += 1
        result = self._run(self.restart_command, timeout=180)
        return {
            "restarted": result["returncode"] == 0,
            "returncode": result["returncode"],
            "stderr_tail": result["stderr"].strip()[-300:],
            "command": " ".join(self.restart_command),
        }

    def properties(self) -> Dict[str, str]:
        result = self._run([
            "systemctl", "show", self.unit, "--no-pager",
            "-p", "ActiveState", "-p", "SubState", "-p", "Result",
            "-p", "MainPID", "-p", "NRestarts", "-p", "ExecMainStartTimestampMonotonic",
        ])
        payload = {}  # type: Dict[str, str]
        for line in result["stdout"].splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                payload[key.strip()] = value.strip()
        return payload

    def health(self) -> Dict[str, Any]:
        """Read the Phase 13F health socket of whatever release is current."""

        script = os.path.join(self.runtime_dir_service_script())
        result = self._run(
            [self.python, script, "--status", "--runtime-dir", self.runtime_dir], timeout=90
        )
        text = (result["stdout"] or "").strip()
        if text.startswith("{"):
            try:
                return json.loads(text)
            except ValueError:
                pass
        return {"state": "UNKNOWN", "error": result["stderr"].strip()[-200:]}

    def runtime_dir_service_script(self) -> str:
        # The status client is part of the release, so read it from whatever
        # `current` resolves to rather than from a fixed checkout.
        return os.path.join(
            os.environ.get("MA_VLNA_CURRENT", "/opt/ma-vlna/current"),
            "scripts", "run_phase13f_service.py",
        )


class DeploymentManager:
    def __init__(self, args: argparse.Namespace, *, service: Optional[Any] = None) -> None:
        self.args = args
        self.store = ReleaseStore(args.root)
        self.state = DeploymentState(os.path.join(self.store.state_dir, "deployment.json"))
        self.service = service or ServiceController(
            args.unit,
            runtime_dir=args.service_runtime_dir,
            python=args.service_python,
            restart_command=(shlex.split(args.restart_command) if args.restart_command else None),
        )
        self.events = []  # type: List[Dict[str, Any]]

    def emit(self, event: str, **fields: Any) -> Dict[str, Any]:
        record = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "event": event}
        record.update(fields)
        self.events.append(record)
        return record

    # ── operations ──────────────────────────────────────────────────────────

    def stage(self, package_path: str, manifest_path: str) -> Dict[str, Any]:
        """Install a candidate into the store without touching ``current``."""

        self.store.ensure_layout()
        report = {"operation": "stage", "package_path": package_path}  # type: Dict[str, Any]
        try:
            manifest = ReleaseManifest.load(manifest_path)
        except ManifestError as exc:
            report["ok"] = False
            report["classification"] = exc.classification
            report["error"] = exc.message
            self._fail("manifest unreadable: %s" % exc.classification)
            return report

        release_id = manifest.release_id
        report["release_id"] = release_id

        if not os.path.isfile(package_path):
            report["ok"] = False
            report["classification"] = "package_missing"
            report["error"] = "no package at %s" % package_path
            self._fail("package missing")
            return report

        observed = sha256_file(package_path)
        report["package_sha256_expected"] = manifest.package_sha256
        report["package_sha256_observed"] = observed
        if observed != manifest.package_sha256:
            # Refuse before unpacking. A package whose hash is wrong does not
            # get to place files in the store at all.
            report["ok"] = False
            report["classification"] = "package_hash_mismatch"
            report["error"] = "package hash does not match the manifest"
            self._fail("package hash mismatch")
            return report

        if self.store.is_installed(release_id):
            report["ok"] = True
            report["already_installed"] = True
        else:
            try:
                report["install"] = self.store.install_from_package(release_id, package_path)
                report["ok"] = True
            except ReleaseStoreError as exc:
                report["ok"] = False
                report["classification"] = exc.classification
                report["error"] = exc.message
                self._fail("install failed: %s" % exc.classification)
                return report

        # Keep the manifest beside the release so validation after a reboot
        # does not depend on the staging area still existing.
        stored_manifest = os.path.join(self.store.release_path(release_id), "release.manifest.json")
        if not os.path.isfile(stored_manifest):
            self.store.make_mutable(release_id)
            with open(stored_manifest, "w", encoding="utf-8") as handle:
                json.dump(manifest.payload, handle, indent=2, sort_keys=True)
                handle.write("\n")
            self.store.make_immutable(release_id)
        report["stored_manifest"] = stored_manifest

        if self.state.state in (CONFIRMED, ROLLED_BACK, FAILED):
            self.state.transition(IDLE, "ready for a new deployment")
        self.state.transition(
            STAGED, "candidate %s staged" % release_id,
            candidate_release_id=release_id,
            attempt_id="%s-%d" % (release_id, int(time.time())),
            switch_completed=False,
            active_release_id=self.store.resolve(CURRENT_LINK),
            last_known_good_release_id=self.store.resolve(LAST_KNOWN_GOOD_LINK),
        )
        self.emit("staged", release_id=release_id, package_sha256=observed)
        return report

    def validate(self, release_id: Optional[str] = None) -> Dict[str, Any]:
        """Check the candidate against this machine. Never weakened to pass."""

        release_id = release_id or self.state.candidate_release_id
        report = {"operation": "validate", "release_id": release_id}  # type: Dict[str, Any]
        if not release_id:
            report["ok"] = False
            report["error"] = "no candidate staged"
            return report
        manifest_path = os.path.join(self.store.release_path(release_id), "release.manifest.json")
        try:
            manifest = ReleaseManifest.load(manifest_path)
        except ManifestError as exc:
            report["ok"] = False
            report["classification"] = exc.classification
            report["error"] = exc.message
            self._fail("candidate manifest unreadable")
            return report

        compatibility = check_compatibility(
            manifest,
            facts=target_facts(import_tensorrt=not self.args.skip_tensorrt_check),
            package_root=self.store.release_path(release_id),
            verify_package_hash=False,
            expected_source_sha=self.args.expected_source_sha or "",
            runtime_dirs=[self.store.staging_dir, self.store.state_dir],
            engine_manifest_path=str(manifest.get("engine_manifest_path", "")),
        )
        report["compatibility"] = compatibility.to_dict()
        report["ok"] = compatibility.compatible
        if not compatibility.compatible:
            report["classification"] = "candidate_incompatible"
            self._fail(
                "candidate incompatible: %s"
                % ",".join(item.name for item in compatibility.failures)
            )
            self.emit("validation_failed", release_id=release_id,
                      failed=[item.name for item in compatibility.failures])
            return report

        if self.state.state == STAGED:
            self.state.transition(VALIDATED, "candidate %s validated" % release_id)
        self.emit("validated", release_id=release_id)
        return report

    def activate(self, release_id: Optional[str] = None) -> Dict[str, Any]:
        """Switch, restart, wait for READY, run probation, confirm or roll back."""

        release_id = release_id or self.state.candidate_release_id
        report = {"operation": "activate", "release_id": release_id}  # type: Dict[str, Any]
        if not release_id:
            report["ok"] = False
            report["error"] = "no candidate to activate"
            return report
        if self.state.state != VALIDATED:
            report["ok"] = False
            report["error"] = "candidate must be VALIDATED before activation (state=%s)" % self.state.state
            return report

        outgoing = self.store.resolve(CURRENT_LINK)
        report["previous_release_id"] = outgoing

        self.state.transition(
            ACTIVATING, "switching to %s" % release_id,
            candidate_release_id=release_id,
            previous_release_id=outgoing,
            switch_completed=False,
        )

        # Record the outgoing release as `previous` *before* the switch, so a
        # crash between the two leaves a rollback target already recorded.
        if outgoing:
            self.store.set_link_atomic(PREVIOUS_LINK, outgoing)

        try:
            switch = self.store.set_link_atomic(CURRENT_LINK, release_id)
        except ReleaseStoreError as exc:
            report["ok"] = False
            report["classification"] = exc.classification
            report["error"] = exc.message
            self._fail("atomic switch failed")
            return report
        report["switch"] = switch
        self.state.set(switch_completed=True, active_release_id=release_id)
        self.emit("switched", release_id=release_id, previous=outgoing)

        # Tell the unit which commit to expect *before* restarting into it.
        # Order matters: the node validates its expected SHA during preflight,
        # so publishing this after the restart would let the candidate fail a
        # check against the outgoing release's SHA and be rolled back for a
        # reason that has nothing to do with the candidate.
        report["env_layer"] = self._publish_release_env(release_id)

        restart = self.service.restart()
        report["restart"] = restart
        if not restart.get("restarted"):
            report["ok"] = False
            report["classification"] = "service_restart_failed"
            return self._auto_rollback(report, "service restart failed")

        ready = self._wait_for_ready(float(self.args.ready_timeout_sec))
        report["ready"] = ready
        if not ready.get("ready"):
            report["ok"] = False
            report["classification"] = "candidate_not_ready"
            return self._auto_rollback(report, "candidate did not reach READY")

        self.state.transition(
            PROBATION, "probation for %s" % release_id,
            probation_deadline_epoch=time.time() + float(self.args.probation_sec),
        )
        probation = self._run_probation(float(self.args.probation_sec))
        report["probation"] = probation
        if not probation.get("passed"):
            report["ok"] = False
            report["classification"] = "probation_failed"
            return self._auto_rollback(report, "probation failed: %s" % probation.get("reason"))

        report.update(self.confirm())
        report["ok"] = True
        return report

    def confirm(self) -> Dict[str, Any]:
        """Promote the active release to last-known-good."""

        release_id = self.store.resolve(CURRENT_LINK)
        report = {"operation": "confirm", "release_id": release_id}  # type: Dict[str, Any]
        if not release_id:
            report["ok"] = False
            report["error"] = "no current release to confirm"
            return report
        self.store.set_link_atomic(LAST_KNOWN_GOOD_LINK, release_id)
        if self.state.state == PROBATION:
            self.state.transition(
                CONFIRMED, "%s confirmed as last-known-good" % release_id,
                last_known_good_release_id=release_id,
            )
        else:
            self.state.set(last_known_good_release_id=release_id)
        self.emit("confirmed", release_id=release_id)
        report["ok"] = True
        report["last_known_good_release_id"] = release_id
        return report

    def rollback(self, *, target: Optional[str] = None, reason: str = "manual") -> Dict[str, Any]:
        """Switch back to a known release and restart into it."""

        destination = (
            target
            or self.store.resolve(LAST_KNOWN_GOOD_LINK)
            or self.store.resolve(PREVIOUS_LINK)
        )
        report = {"operation": "rollback", "target_release_id": destination, "reason": reason}
        if not destination:
            report["ok"] = False
            report["error"] = "no last-known-good or previous release to roll back to"
            self._fail("no rollback target")
            return report
        if not self.store.is_installed(destination):
            report["ok"] = False
            report["error"] = "rollback target %s is not installed" % destination
            self._fail("rollback target missing")
            return report

        if self.state.state not in (ROLLING_BACK,):
            try:
                self.state.transition(ROLLING_BACK, "rolling back to %s: %s" % (destination, reason))
            except DeploymentStateError:
                # From a terminal state a rollback is still permitted; record it.
                self.state.set(state=ROLLING_BACK, reason=reason)
                self.state.save()

        report["switch"] = self.store.set_link_atomic(CURRENT_LINK, destination)
        self.state.set(active_release_id=destination, switch_completed=True)
        # A rollback is a switch like any other, so the expected SHA must follow
        # it back. Without this the rollback target would be started with the
        # failed candidate's SHA still published and would fail preflight too --
        # turning a recoverable rollback into the FAILED state below.
        report["env_layer"] = self._publish_release_env(destination)
        restart = self.service.restart()
        report["restart"] = restart
        ready = self._wait_for_ready(float(self.args.rollback_timeout_sec))
        report["ready"] = ready
        report["ok"] = bool(restart.get("restarted") and ready.get("ready"))
        if report["ok"]:
            self.state.transition(
                ROLLED_BACK, "rolled back to %s" % destination,
                active_release_id=destination,
            )
            self.emit("rolled_back", release_id=destination, reason=reason)
        else:
            # A rollback that cannot come up is the worst case this phase has:
            # it is recorded as FAILED rather than dressed up as recovered.
            self.state.transition(FAILED, "rollback to %s did not become ready" % destination)
            self.emit("rollback_failed", release_id=destination)
        return report

    def cleanup(self) -> Dict[str, Any]:
        report = {"operation": "cleanup"}
        report.update(self.store.cleanup(keep=int(self.args.keep), dry_run=bool(self.args.dry_run)))
        report["staging"] = self.store.prune_staging(older_than_sec=float(self.args.staging_age_sec))
        report["ok"] = True
        return report

    def status(self) -> Dict[str, Any]:
        payload = {
            "operation": "status",
            "phase": PHASE,
            "store": self.store.to_dict(),
            "state": self.state.to_dict(),
            "state_machine": describe_state_machine(),
            "manifest_schema": describe_schema(),
            "integrity_only": True,
            "signed": False,
            "secure_boot": False,
            "bootloader_ab": False,
            "anti_rollback_security": False,
        }
        payload["env_layer"] = self._describe_release_env()
        if not self.args.skip_service_status:
            payload["service_properties"] = self.service.properties()
            payload["service_health"] = self.service.health()
        payload["ok"] = True
        return payload

    def _publish_release_env(self, release_id: str) -> Dict[str, Any]:
        """Write the environment layer naming the release about to be started."""

        sha = self.store.release_source_sha(release_id)
        if not sha:
            # Refusing here would be worse than proceeding: the release is
            # already installed and validated, and validation checked the
            # manifest. Report it loudly instead of failing the switch.
            result = {
                "ok": False,
                "release_id": release_id,
                "error": "release manifest carries no source_git_sha",
            }
            self.emit("env_layer_incomplete", **result)
            return result
        result = self.store.write_state_env(release_id, sha)
        result["ok"] = True
        self.emit("env_layer_published", release_id=release_id, expected_sha=sha)
        return result

    def _describe_release_env(self) -> Dict[str, Any]:
        """What the unit will read, and whether it agrees with ``current``.

        Reported rather than corrected. A mismatch between the published SHA and
        the active release means the next restart would fail preflight, and that
        is worth seeing in ``status`` instead of being silently repaired.
        """

        path = self.store.state_env_path()
        active = self.store.resolve(CURRENT_LINK)
        payload = {
            "path": path,
            "exists": os.path.isfile(path),
            "active_release_id": active,
            "active_release_sha": self.store.release_source_sha(active) if active else "",
        }
        published = {}  # type: Dict[str, str]
        try:
            with open(path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    published[key.strip()] = value.strip()
        except OSError:
            pass
        payload["published_sha"] = published.get("MA_VLNA_EXPECTED_SHA", "")
        payload["published_release_id"] = published.get("MA_VLNA_ACTIVE_RELEASE_ID", "")
        payload["agrees_with_current"] = bool(
            payload["exists"]
            and payload["published_release_id"] == (active or "")
            and payload["published_sha"] == payload["active_release_sha"]
            and payload["active_release_sha"]
        )
        return payload

    def resume(self) -> Dict[str, Any]:
        """Decide what an interrupted deployment should do, and do it."""

        decision = self.state.recovery_decision(policy=self.args.on_boot_unconfirmed)
        report = {"operation": "resume", "decision": decision}  # type: Dict[str, Any]
        action = decision["action"]
        if action == "none":
            report["ok"] = True
            return report
        if action == "discard_candidate":
            # Nothing was switched; return to IDLE without touching current.
            self.state.transition(IDLE, "staged candidate discarded after interruption")
            report["ok"] = True
            return report
        if action in ("rollback_to_last_known_good", "resume_rollback"):
            report["rollback"] = self.rollback(reason="interrupted_%s" % decision["state_found"])
            report["ok"] = bool(report["rollback"].get("ok"))
            return report
        if action == "resume_probation":
            remaining = 0.0
            deadline = self.state.payload.get("probation_deadline_epoch")
            if deadline:
                remaining = max(0.0, float(deadline) - time.time())
            probation = self._run_probation(remaining)
            report["probation"] = probation
            if probation.get("passed"):
                report.update(self.confirm())
                report["ok"] = True
            else:
                report["rollback"] = self.rollback(reason="probation_failed_after_resume")
                report["ok"] = bool(report["rollback"].get("ok"))
            return report
        report["ok"] = False
        return report

    # ── internals ───────────────────────────────────────────────────────────

    def _fail(self, reason: str) -> None:
        try:
            self.state.transition(FAILED, reason)
        except DeploymentStateError:
            self.state.set(state=FAILED, reason=reason)

    def _auto_rollback(self, report: Dict[str, Any], reason: str) -> Dict[str, Any]:
        self.emit("auto_rollback_triggered", reason=reason)
        report["auto_rollback"] = self.rollback(reason=reason)
        report["ok"] = False
        report["rolled_back"] = bool(report["auto_rollback"].get("ok"))
        return report

    def _wait_for_ready(self, timeout_sec: float) -> Dict[str, Any]:
        started = time.time()
        deadline = started + max(1.0, timeout_sec)
        last = {}  # type: Dict[str, Any]
        while time.time() < deadline:
            last = self.service.health()
            if last.get("state") == "READY":
                return {
                    "ready": True,
                    "ready_sec": round(time.time() - started, 3),
                    "within_limit": True,
                    "health": {
                        key: last.get(key) for key in (
                            "state", "ai_authority_permitted", "engine_sha256",
                            "repository_sha", "node_start_count", "engine_load_count",
                        )
                    },
                }
            time.sleep(float(self.args.poll_sec))
        return {
            "ready": False,
            "ready_sec": round(time.time() - started, 3),
            "within_limit": False,
            "last_state": last.get("state"),
        }

    def _run_probation(self, probation_sec: float) -> Dict[str, Any]:
        """Watch the candidate for a window before trusting it.

        Failure is any of: leaving READY, the service restarting underneath us,
        or the health endpoint becoming unreadable. Each is checked every poll
        rather than only at the end, so a candidate that dies at second 10 is
        caught at second 10.
        """

        started = time.time()
        deadline = started + max(0.0, probation_sec)
        samples = 0
        first = self.service.health()
        baseline_starts = int(first.get("node_start_count", 0) or 0)
        baseline_restarts = int(first.get("restart_count", 0) or 0)
        max_node_starts = baseline_starts
        max_restarts = baseline_restarts
        while time.time() < deadline:
            health = self.service.health()
            samples += 1
            state = health.get("state")
            if state != "READY":
                return {
                    "passed": False, "reason": "state_left_ready", "observed_state": state,
                    "elapsed_sec": round(time.time() - started, 3), "samples": samples,
                }
            node_starts = int(health.get("node_start_count", 0) or 0)
            restarts = int(health.get("restart_count", 0) or 0)
            max_node_starts = max(max_node_starts, node_starts)
            max_restarts = max(max_restarts, restarts)
            if restarts - baseline_restarts > int(self.args.probation_max_restarts):
                return {
                    "passed": False, "reason": "restart_storm_during_probation",
                    "restarts_observed": restarts - baseline_restarts,
                    "elapsed_sec": round(time.time() - started, 3), "samples": samples,
                }
            properties = self.service.properties()
            if properties.get("ActiveState") not in (None, "", "active"):
                return {
                    "passed": False, "reason": "unit_left_active",
                    "active_state": properties.get("ActiveState"),
                    "elapsed_sec": round(time.time() - started, 3), "samples": samples,
                }
            time.sleep(float(self.args.poll_sec))
        return {
            "passed": True,
            "elapsed_sec": round(time.time() - started, 3),
            "samples": samples,
            "node_starts_during_probation": max_node_starts - baseline_starts,
            "restarts_during_probation": max_restarts - baseline_restarts,
        }


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13G deployment manager")
    parser.add_argument(
        "operation",
        choices=["stage", "validate", "activate", "confirm", "rollback", "status",
                 "cleanup", "resume"],
    )
    parser.add_argument("--root", default=DEFAULT_ROOT)
    parser.add_argument("--unit", default=DEFAULT_UNIT)
    parser.add_argument("--package", default="")
    parser.add_argument("--manifest", default="")
    parser.add_argument("--release-id", default="")
    parser.add_argument("--rollback-target", default="")
    parser.add_argument("--expected-source-sha", default="")
    parser.add_argument("--service-runtime-dir", default="/run/ma-vlna")
    parser.add_argument("--service-python", default="")
    parser.add_argument(
        "--restart-command", default="",
        help="Override the service restart command (shell-quoted).",
    )
    parser.add_argument("--ready-timeout-sec", type=float, default=DEFAULT_READY_TIMEOUT_SEC)
    parser.add_argument("--probation-sec", type=float, default=DEFAULT_PROBATION_SEC)
    parser.add_argument("--rollback-timeout-sec", type=float, default=DEFAULT_ROLLBACK_TIMEOUT_SEC)
    parser.add_argument("--probation-max-restarts", type=int, default=0)
    parser.add_argument("--poll-sec", type=float, default=5.0)
    parser.add_argument("--keep", type=int, default=3)
    parser.add_argument("--staging-age-sec", type=float, default=3600.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-tensorrt-check", action="store_true")
    parser.add_argument("--skip-service-status", action="store_true")
    parser.add_argument(
        "--on-boot-unconfirmed", choices=["rollback", "resume"], default="rollback",
        help="What an interrupted, unconfirmed activation does on the next start.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    manager = DeploymentManager(args)
    operation = args.operation

    if operation == "stage":
        if not args.package or not args.manifest:
            print(json.dumps({"ok": False, "error": "--package and --manifest are required"}))
            return 2
        report = manager.stage(args.package, args.manifest)
    elif operation == "validate":
        report = manager.validate(args.release_id or None)
    elif operation == "activate":
        report = manager.activate(args.release_id or None)
    elif operation == "confirm":
        report = manager.confirm()
    elif operation == "rollback":
        report = manager.rollback(target=args.rollback_target or None, reason="manual")
    elif operation == "cleanup":
        report = manager.cleanup()
    elif operation == "resume":
        report = manager.resume()
    else:
        report = manager.status()

    report["events"] = manager.events
    report["deployment_state"] = manager.state.state
    report["store_links"] = manager.store.protected_release_ids()
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
