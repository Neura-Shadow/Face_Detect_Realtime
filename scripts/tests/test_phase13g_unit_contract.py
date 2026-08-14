"""Phase 13G systemd unit contract tests.

The renderer's job is to refuse a unit that would misbehave on the target, so
every check is tested in the direction that matters: a mutated unit that should
fail must actually fail. A validator that only ever passes is decoration.

Targeted at systemd 245 (Ubuntu 20.04 / JetPack R35.5.0), which is what the
Jetson actually runs.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Dict

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from run_phase13g_install import (  # noqa: E402
    RELEASE_TEMPLATE,
    RESUME_TEMPLATE,
    installation_commands,
    join_continuations,
    render,
    validate_release_unit,
    validate_resume_unit,
)

TARGET_SYSTEMD = 245
RELEASE_ROOT = "/opt/ma-vlna"
SERVICE_NAME = "ma-vlna-jetson-node"

VALUES = {
    "SERVICE_NAME": SERVICE_NAME,
    "SERVICE_USER": "myjetsonnx",
    "SERVICE_GROUP": "myjetsonnx",
    "RELEASE_ROOT": RELEASE_ROOT,
    "REPO_ROOT": "/home/myjetsonnx/Face_Detect_Realtime",
    "PYTHON": "/home/myjetsonnx/venvs/ma-vlna/bin/python",
    "ENV_FILE": "/etc/ma-vlna/jetson-node.env",
    "EVIDENCE_DIR": "/home/myjetsonnx/Face_Detect_Realtime/experiments/phase13",
    "LOG_DIR": "/home/myjetsonnx/ma-vlna-logs",
    "LOG_PATH": "/home/myjetsonnx/ma-vlna-logs/service.jsonl",
    "STAGING_DIR": "/home/myjetsonnx/ma-vlna-staging",
}  # type: Dict[str, str]


def release_unit() -> str:
    return render(RELEASE_TEMPLATE, VALUES)


def resume_unit() -> str:
    return render(RESUME_TEMPLATE, VALUES)


def check_release(text: str):
    return validate_release_unit(text, TARGET_SYSTEMD, release_root=RELEASE_ROOT)


def check_resume(text: str):
    return validate_resume_unit(text, TARGET_SYSTEMD, service_name=SERVICE_NAME)


class TestLineContinuations(unittest.TestCase):
    """systemd joins backslash continuations; a validator must too."""

    def test_continuation_lines_are_joined(self) -> None:
        joined = join_continuations("ExecStart=/bin/x \\\n    --flag one \\\n    --flag two\n")
        self.assertEqual(joined.strip(), "ExecStart=/bin/x --flag one --flag two")

    def test_ordinary_lines_are_untouched(self) -> None:
        joined = join_continuations("Type=notify\nUser=x\n")
        self.assertEqual(joined.strip().splitlines(), ["Type=notify", "User=x"])

    def test_a_trailing_continuation_is_not_dropped(self) -> None:
        self.assertEqual(join_continuations("ExecStart=/bin/x \\\n").strip(), "ExecStart=/bin/x")

    def test_resume_arguments_are_visible_after_joining(self) -> None:
        """The concrete bug: arguments live on continuation lines.

        Read line by line, the resume unit's ExecStart is just
        ``...run_phase13g_deploy.py resume \\`` and every flag is invisible.
        """

        self.assertIn("--on-boot-unconfirmed rollback", join_continuations(resume_unit()))


class TestRenderedUnitsAreValid(unittest.TestCase):
    def test_release_unit_is_valid_on_the_target(self) -> None:
        report = check_release(release_unit())
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["unresolved_placeholders"], [])
        self.assertEqual(report["directives_newer_than_target"], [])

    def test_resume_unit_is_valid_on_the_target(self) -> None:
        report = check_resume(resume_unit())
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["unresolved_placeholders"], [])
        self.assertEqual(report["directives_newer_than_target"], [])

    def test_release_unit_runs_from_the_release_not_a_checkout(self) -> None:
        report = check_release(release_unit())
        self.assertEqual(report["working_directory"], "%s/current" % RELEASE_ROOT)
        self.assertTrue(report["runs_from_release"])
        self.assertFalse(report["runs_from_git_checkout"])

    def test_release_unit_layers_the_state_env_last(self) -> None:
        report = check_release(release_unit())
        self.assertEqual(
            report["environment_files"],
            ["/etc/ma-vlna/jetson-node.env", "-%s/state/service.env" % RELEASE_ROOT],
        )
        self.assertTrue(report["state_env_is_last"])

    def test_release_unit_keeps_the_release_tree_read_only(self) -> None:
        self.assertTrue(check_release(release_unit())["releases_read_only"])

    def test_resume_unit_is_ordered_before_the_node(self) -> None:
        report = check_resume(resume_unit())
        self.assertTrue(report["before_node_service"])
        self.assertTrue(report["rollback_policy"])
        self.assertTrue(report["skips_service_status"])


class TestValidatorRefusesBadUnits(unittest.TestCase):
    """Each mutation breaks one real property, and must be caught."""

    def test_a_unit_still_pointing_at_a_git_checkout_is_refused(self) -> None:
        """The regression this phase exists to prevent.

        A mutable checkout means `git pull` rewrites the running service's code
        and the SHA validated at startup stops describing what is on disk.
        """

        text = release_unit().replace(
            "WorkingDirectory=%s/current" % RELEASE_ROOT,
            "WorkingDirectory=/home/myjetsonnx/Face_Detect_Realtime",
        )
        report = check_release(text)
        self.assertFalse(report["valid"])
        self.assertTrue(report["runs_from_git_checkout"])
        self.assertFalse(report["runs_from_release"])

    def test_dropping_the_state_env_layer_is_refused(self) -> None:
        text = release_unit().replace(
            "EnvironmentFile=-%s/state/service.env" % RELEASE_ROOT, ""
        )
        report = check_release(text)
        self.assertFalse(report["valid"])
        self.assertFalse(report["state_env_present"])

    def test_the_state_env_layer_applied_first_is_refused(self) -> None:
        """Order decides which value wins, so order is part of the contract.

        Applied before the /etc file, the pinned default would override the
        release's own SHA and every activation but one would fail preflight.
        """

        state_line = "EnvironmentFile=-%s/state/service.env" % RELEASE_ROOT
        etc_line = "EnvironmentFile=/etc/ma-vlna/jetson-node.env"
        text = release_unit().replace(state_line, "@SWAP@").replace(etc_line, state_line)
        text = text.replace("@SWAP@", etc_line)
        report = check_release(text)
        self.assertFalse(report["valid"])
        self.assertTrue(report["state_env_present"])
        self.assertFalse(report["state_env_is_last"])

    def test_a_writable_release_tree_is_refused(self) -> None:
        text = release_unit().replace("ReadOnlyPaths=%s/releases" % RELEASE_ROOT, "")
        report = check_release(text)
        self.assertFalse(report["valid"])
        self.assertFalse(report["releases_read_only"])

    def test_a_directive_newer_than_the_target_is_refused(self) -> None:
        """`RestartSteps` is systemd 254; the Jetson runs 245."""

        text = release_unit().replace("RestartSec=5", "RestartSec=5\nRestartSteps=5")
        report = check_release(text)
        self.assertFalse(report["valid"])
        self.assertIn(
            "RestartSteps",
            [item["directive"] for item in report["directives_newer_than_target"]],
        )

    def test_an_unrendered_placeholder_is_refused(self) -> None:
        text = release_unit().replace("%s/current" % RELEASE_ROOT, "@RELEASE_ROOT@/current")
        report = check_release(text)
        self.assertFalse(report["valid"])
        self.assertIn("RELEASE_ROOT", report["unresolved_placeholders"])

    def test_the_wrong_service_type_is_refused(self) -> None:
        report = check_release(release_unit().replace("Type=notify", "Type=simple"))
        self.assertFalse(report["valid"])
        self.assertTrue(report["wrong_values"])

    def test_a_resume_unit_without_the_rollback_policy_is_refused(self) -> None:
        """Defaulting to anything else would promote an unconfirmed release."""

        text = resume_unit().replace("--on-boot-unconfirmed rollback", "--on-boot-unconfirmed keep")
        report = check_resume(text)
        self.assertFalse(report["valid"])
        self.assertFalse(report["rollback_policy"])

    def test_a_resume_unit_not_ordered_before_the_node_is_refused(self) -> None:
        text = resume_unit().replace("Before=%s.service" % SERVICE_NAME, "")
        report = check_resume(text)
        self.assertFalse(report["valid"])
        self.assertFalse(report["before_node_service"])

    def test_a_resume_unit_that_probes_the_service_is_refused(self) -> None:
        """The node is deliberately not up yet; probing it stalls every boot."""

        report = check_resume(resume_unit().replace("--skip-service-status", ""))
        self.assertFalse(report["valid"])
        self.assertFalse(report["skips_service_status"])

    def test_a_oneshot_turned_into_notify_is_refused(self) -> None:
        report = check_resume(resume_unit().replace("Type=oneshot", "Type=notify"))
        self.assertFalse(report["valid"])
        self.assertTrue(report["wrong_values"])


class TestInstallationCommands(unittest.TestCase):
    def test_commands_are_printed_never_run(self) -> None:
        """This module renders and validates. Installing is an operator action."""

        commands = installation_commands(VALUES)
        joined = "\n".join(commands)
        self.assertIn("sudo systemd-analyze verify", joined)
        self.assertIn("sudo systemctl daemon-reload", joined)

    def test_verification_precedes_starting(self) -> None:
        commands = installation_commands(VALUES)
        verify = next(i for i, c in enumerate(commands) if "systemd-analyze verify" in c)
        start = next(i for i, c in enumerate(commands) if c.startswith("sudo systemctl start"))
        self.assertLess(verify, start, "unit is started before systemd validates it")

    def test_enabling_comes_after_starting(self) -> None:
        """Enabling an unproven unit makes a bad release survive reboots."""

        commands = installation_commands(VALUES)
        start = next(i for i, c in enumerate(commands) if c.startswith("sudo systemctl start"))
        enable = next(i for i, c in enumerate(commands) if c.startswith("sudo systemctl enable"))
        self.assertLess(start, enable)

    def test_the_phase_13f_unit_is_backed_up_first(self) -> None:
        """Gate C replaces the 13F unit, so it has to be reversible."""

        commands = installation_commands(VALUES)
        joined = "\n".join(commands)
        self.assertIn("phase13f.bak", joined)
        backup = next(i for i, c in enumerate(commands) if "phase13f.bak" in c)
        install = next(
            i for i, c in enumerate(commands)
            if c.startswith("sudo install") and "/etc/systemd/system/" in c
        )
        self.assertLess(backup, install, "the old unit is overwritten before being saved")

    def test_no_passwordless_sudo_or_credential_handling(self) -> None:
        joined = "\n".join(installation_commands(VALUES)).lower()
        for forbidden in ("nopasswd", "visudo", "/etc/sudoers", "sudo -s", "echo $password"):
            self.assertNotIn(forbidden, joined)


if __name__ == "__main__":
    unittest.main()
