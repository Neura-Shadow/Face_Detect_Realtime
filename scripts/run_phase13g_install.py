"""Phase 13G unit renderer: release-managed node + boot-resume units.

Renders the two Phase 13G templates, validates them against the target's actual
systemd version, writes them to a staging directory, and prints the exact
commands an operator runs. It never executes sudo, never writes to ``/etc``, and
never enables a unit.

Two units, because activation and recovery are separate concerns:

``<service>.service``
    The node, run from ``<release-root>/current`` instead of a git checkout.
    Switching ``current`` and restarting is the activation step.

``ma-vlna-deploy-resume.service``
    Ordered ``Before`` the node service. On every boot it asks the deployment
    manager what an interrupted update should do, so a power cut during
    ACTIVATING or PROBATION cannot silently promote an unconfirmed release.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (str(REPO_ROOT), str(REPO_ROOT / "scripts")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from run_phase13f_install import (  # noqa: E402
    DIRECTIVE_MIN_VERSION,
    parse_directives,
    unresolved_placeholders,
)

PHASE = "13G-OTA-A-B-ROLLBACK-VERSION-COMPATIBILITY"

SYSTEMD_DIR = REPO_ROOT / "deployment" / "systemd"
RELEASE_TEMPLATE = SYSTEMD_DIR / "ma-vlna-jetson-node.release.service.template"
RESUME_TEMPLATE = SYSTEMD_DIR / "ma-vlna-deploy-resume.service.template"

#: Directives this phase adds on top of the Phase 13F set, with the first
#: systemd version that understands each.
EXTRA_DIRECTIVE_MIN_VERSION = {
    "ReadOnlyPaths": 231,
    "RemainAfterExit": 1,
    "TimeoutStartSec": 1,
    "TimeoutStopSec": 1,
    "Documentation": 1,
    "SupplementaryGroups": 1,
}

#: The release-managed node unit's contract.
RELEASE_REQUIRED = (
    "Type=notify",
    "WatchdogSec=",
    "Restart=on-failure",
    "RestartSec=",
    "StartLimitIntervalSec=",
    "StartLimitBurst=",
    "RuntimeDirectory=",
    "EnvironmentFile=",
    "User=",
    "WorkingDirectory=",
    "ReadOnlyPaths=",
)

#: The resume unit's contract. Deliberately different: it is a one-shot that
#: must finish before the node starts, so notify/watchdog directives would be
#: wrong here rather than merely absent.
RESUME_REQUIRED = (
    "Type=oneshot",
    "RemainAfterExit=",
    "ExecStart=",
    "User=",
    "TimeoutStartSec=",
)


def render(template: Path, values: Dict[str, str]) -> str:
    text = template.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("@%s@" % key, value)
    return text


def join_continuations(text: str) -> str:
    """Collapse systemd's trailing-backslash line continuations.

    Both units write ``ExecStart`` across many lines for legibility, and
    systemd joins them into one value. A line-by-line reader sees only
    ``ExecStart=... resume \\`` and none of the arguments -- which is how the
    first version of this validator reported the resume unit as missing its
    rollback policy when the policy was plainly there. The checks that look
    inside ExecStart have to read what systemd reads.
    """

    joined = []  # type: List[str]
    pending = ""
    for raw in text.splitlines():
        line = raw.rstrip()
        if pending:
            line = pending + " " + line.strip()
            pending = ""
        if line.endswith("\\"):
            pending = line[:-1].rstrip()
            continue
        joined.append(line)
    if pending:
        joined.append(pending)
    return "\n".join(joined)


def _version_problems(names, systemd_version: Optional[int]) -> List[Dict[str, Any]]:
    if not systemd_version:
        return []
    known = dict(DIRECTIVE_MIN_VERSION)
    known.update(EXTRA_DIRECTIVE_MIN_VERSION)
    problems = []  # type: List[Dict[str, Any]]
    for name in sorted(names):
        minimum = known.get(name)
        if minimum and minimum > systemd_version:
            problems.append({"directive": name, "requires_systemd": minimum})
    return problems


def _base_report(text: str, required, systemd_version: Optional[int]) -> Dict[str, Any]:
    directives = parse_directives(join_continuations(text))
    names = {key for key, _ in directives}
    missing = [item for item in required if item.split("=")[0] not in names]
    wrong = []  # type: List[str]
    for item in required:
        key, _, expected = item.partition("=")
        if not expected:
            continue
        found = [value for name, value in directives if name == key]
        if found and found[0] != expected:
            wrong.append("%s=%s (expected %s)" % (key, found[0], expected))
    placeholders = unresolved_placeholders(text)
    return {
        "directives": directives,
        "directive_count": len(directives),
        "missing_required": missing,
        "wrong_values": wrong,
        "directives_newer_than_target": _version_problems(names, systemd_version),
        "unresolved_placeholders": placeholders,
        "has_install_section": "[Install]" in text,
    }


def validate_release_unit(
    text: str, systemd_version: Optional[int], *, release_root: str
) -> Dict[str, Any]:
    """The node unit, plus the checks specific to running from a release."""

    report = _base_report(text, RELEASE_REQUIRED, systemd_version)
    directives = report.pop("directives")

    working = [value for name, value in directives if name == "WorkingDirectory"]
    env_files = [value for name, value in directives if name == "EnvironmentFile"]
    read_only = [value for name, value in directives if name == "ReadOnlyPaths"]

    expected_working = "%s/current" % release_root.rstrip("/")
    report["working_directory"] = working[0] if working else ""
    report["runs_from_release"] = bool(working) and working[0] == expected_working

    # The mistake this phase exists to prevent: a unit still pointing at a
    # mutable git checkout, where `git pull` changes the running service's code
    # and the validated SHA stops describing what is on disk.
    report["runs_from_git_checkout"] = bool(working) and (
        "Face_Detect_Realtime" in working[0] or working[0].rstrip("/").endswith(".git")
    )

    # Two environment files, and the deployment-owned one must come second:
    # systemd applies them in order, so the layer that carries the active
    # release's SHA only wins if it is applied after the pinned /etc default.
    state_env = "-%s/state/service.env" % release_root.rstrip("/")
    report["environment_files"] = env_files
    report["state_env_present"] = state_env in env_files
    report["state_env_is_last"] = bool(env_files) and env_files[-1] == state_env
    report["state_env_optional_prefix"] = state_env.startswith("-")

    expected_read_only = "%s/releases" % release_root.rstrip("/")
    report["releases_read_only"] = any(expected_read_only in value for value in read_only)

    report["valid"] = not (
        report["missing_required"]
        or report["wrong_values"]
        or report["directives_newer_than_target"]
        or report["unresolved_placeholders"]
    ) and all((
        report["has_install_section"],
        report["runs_from_release"],
        not report["runs_from_git_checkout"],
        report["state_env_present"],
        report["state_env_is_last"],
        report["releases_read_only"],
    ))
    return report


def validate_resume_unit(
    text: str, systemd_version: Optional[int], *, service_name: str
) -> Dict[str, Any]:
    """The boot-resume unit: ordering and policy are the substance."""

    report = _base_report(text, RESUME_REQUIRED, systemd_version)
    directives = report.pop("directives")
    before = [value for name, value in directives if name == "Before"]
    exec_start = " ".join(value for name, value in directives if name == "ExecStart")

    unit = "%s.service" % service_name
    # Ordering is the point. If this ran after the node, the node would start
    # from whatever `current` happened to be and then be switched underneath
    # itself -- the exact silent promotion the unit exists to prevent.
    report["before_node_service"] = any(unit in value for value in before)
    report["runs_resume"] = "resume" in exec_start
    report["rollback_policy"] = "--on-boot-unconfirmed rollback" in exec_start
    # The node is deliberately not up yet, so asking it for health here would
    # time out on every single boot.
    report["skips_service_status"] = "--skip-service-status" in exec_start

    report["valid"] = not (
        report["missing_required"]
        or report["wrong_values"]
        or report["directives_newer_than_target"]
        or report["unresolved_placeholders"]
    ) and all((
        report["has_install_section"],
        report["before_node_service"],
        report["runs_resume"],
        report["rollback_policy"],
        report["skips_service_status"],
    ))
    return report


def installation_commands(values: Dict[str, str]) -> List[str]:
    """The exact operator commands. Printed only; never executed here."""

    service_name = values["SERVICE_NAME"]
    unit = "%s.service" % service_name
    resume_unit = "ma-vlna-deploy-resume.service"
    staging = values["STAGING_DIR"]
    staged_unit = "%s/%s" % (staging, unit)
    staged_resume = "%s/%s" % (staging, resume_unit)
    release_root = values["RELEASE_ROOT"].rstrip("/")

    return [
        "# Phase 13G Gate C: install the release-managed units.",
        "#",
        "# The Phase 13F unit and this one have the same name, so installing this",
        "# REPLACES it. That is the intended change of authority: the node stops",
        "# running from the git checkout and starts running from a release.",
        "",
        "# 1. Read both rendered units before installing either.",
        "cat %s" % shlex.quote(staged_unit),
        "cat %s" % shlex.quote(staged_resume),
        "",
        "# 2. Keep a copy of the unit currently installed, so Gate C is reversible.",
        "sudo cp -a /etc/systemd/system/%s %s/%s.phase13f.bak" % (unit, staging, unit),
        "",
        "# 3. Stop the running service before changing where its code comes from.",
        "sudo systemctl stop %s" % unit,
        "",
        "# 4. Install both units.",
        "sudo install -m 0644 -o root -g root %s /etc/systemd/system/%s"
        % (shlex.quote(staged_unit), unit),
        "sudo install -m 0644 -o root -g root %s /etc/systemd/system/%s"
        % (shlex.quote(staged_resume), resume_unit),
        "",
        "# 5. Verify systemd accepts them BEFORE starting anything.",
        "sudo systemd-analyze verify /etc/systemd/system/%s" % unit,
        "sudo systemd-analyze verify /etc/systemd/system/%s" % resume_unit,
        "sudo systemctl daemon-reload",
        "",
        "# 6. Start, and watch. `current` must already point at a validated",
        "#    release -- Gate B left release A active and confirmed.",
        "ls -l %s/current" % release_root,
        "sudo systemctl start %s" % unit,
        "systemctl status %s --no-pager" % unit,
        "journalctl -u %s -n 60 --no-pager" % unit,
        "",
        "# 7. Only once it is healthy, enable both for boot.",
        "sudo systemctl enable %s" % unit,
        "sudo systemctl enable %s" % resume_unit,
        "",
        "# Reverting Gate C, if needed: restore the Phase 13F unit.",
        "sudo systemctl disable --now %s" % resume_unit,
        "sudo rm -f /etc/systemd/system/%s" % resume_unit,
        "sudo install -m 0644 -o root -g root %s/%s.phase13f.bak /etc/systemd/system/%s"
        % (staging, unit, unit),
        "sudo systemctl daemon-reload",
        "sudo systemctl restart %s" % unit,
    ]


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Phase 13G unit renderer (never runs sudo)"
    )
    parser.add_argument("--service-name", default="ma-vlna-jetson-node")
    parser.add_argument("--service-user", default="myjetsonnx")
    parser.add_argument("--service-group", default="myjetsonnx")
    parser.add_argument("--release-root", default="/opt/ma-vlna")
    parser.add_argument("--repo-root", default="/home/myjetsonnx/Face_Detect_Realtime")
    parser.add_argument("--python", default="/home/myjetsonnx/venvs/ma-vlna/bin/python")
    parser.add_argument("--env-file", default="/etc/ma-vlna/jetson-node.env")
    parser.add_argument(
        "--evidence-dir", default="/home/myjetsonnx/Face_Detect_Realtime/experiments/phase13"
    )
    parser.add_argument("--log-dir", default="/home/myjetsonnx/ma-vlna-logs")
    parser.add_argument("--log-path", default="/home/myjetsonnx/ma-vlna-logs/service.jsonl")
    parser.add_argument("--staging-dir", default="/home/myjetsonnx/ma-vlna-staging")
    parser.add_argument("--systemd-version", type=int, default=0)
    parser.add_argument("--write-staged", default="", help="Directory to write rendered units to.")
    parser.add_argument("--print-commands", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))

    values = {
        "SERVICE_NAME": args.service_name,
        "SERVICE_USER": args.service_user,
        "SERVICE_GROUP": args.service_group,
        "RELEASE_ROOT": args.release_root.rstrip("/"),
        "REPO_ROOT": args.repo_root,
        "PYTHON": args.python,
        "ENV_FILE": args.env_file,
        "EVIDENCE_DIR": args.evidence_dir,
        "LOG_DIR": args.log_dir,
        "LOG_PATH": args.log_path,
        "STAGING_DIR": args.staging_dir,
    }

    release_text = render(RELEASE_TEMPLATE, values)
    resume_text = render(RESUME_TEMPLATE, values)
    release_report = validate_release_unit(
        release_text, args.systemd_version, release_root=values["RELEASE_ROOT"]
    )
    resume_report = validate_resume_unit(
        resume_text, args.systemd_version, service_name=args.service_name
    )

    report = {
        "phase": PHASE,
        "values": values,
        "release_unit": release_report,
        "resume_unit": resume_report,
        "sudo_executed": False,
        "etc_modified": False,
        "units_enabled": False,
        "integrity_only": True,
        "signed": False,
        "secure_boot": False,
        "bootloader_ab": False,
        "anti_rollback_security": False,
    }  # type: Dict[str, Any]
    report["ok"] = bool(release_report["valid"] and resume_report["valid"])

    if args.write_staged:
        target = os.path.abspath(args.write_staged)
        os.makedirs(target, exist_ok=True)
        written = {}
        unit_path = os.path.join(target, "%s.service" % args.service_name)
        resume_path = os.path.join(target, "ma-vlna-deploy-resume.service")
        with open(unit_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(release_text)
        with open(resume_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(resume_text)
        written["release_unit"] = unit_path
        written["resume_unit"] = resume_path
        report["written"] = written

    commands = installation_commands(values)
    report["installation_commands"] = commands
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.print_commands:
        sys.stderr.write("\n".join(commands) + "\n")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
