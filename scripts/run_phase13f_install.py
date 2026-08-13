"""Phase 13F unit renderer and installation-command printer.

This renders the systemd unit and environment file from the template and prints
the exact commands an operator runs to install them. It **never** runs sudo,
never writes to ``/etc``, never enables or starts a unit, and never asks for or
stores a password. Installing a system service is an operator action; this
script exists so that action is exact and reviewable rather than improvised.

It also validates the rendered unit against the systemd version actually on the
target, because a unit that references a directive the target does not
understand fails at load time with a message that is easy to misread as a
problem with the service.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PHASE = "13F-JETSON-SERVICE-SUPERVISION-BOOT-RECOVERY"
TEMPLATE = REPO_ROOT / "deployment" / "systemd" / "ma-vlna-jetson-node.service.template"
ENV_EXAMPLE = REPO_ROOT / "deployment" / "systemd" / "ma-vlna-jetson-node.env.example"

#: Directives and the first systemd version that understands them. Only entries
#: that could plausibly be reached for are listed; the point is to catch a unit
#: written against a newer systemd than the target runs.
DIRECTIVE_MIN_VERSION = {
    "RestartSteps": 254,
    "RestartMaxDelaySec": 254,
    "StartLimitIntervalSec": 229,
    "StartLimitBurst": 229,
    "RuntimeDirectory": 211,
    "RuntimeDirectoryMode": 211,
    "NotifyAccess": 1,
    "WatchdogSec": 1,
    "ProtectSystem": 214,
    "ProtectHome": 214,
    "NoNewPrivileges": 187,
    "PrivateTmp": 1,
    "ReadWritePaths": 231,
    "SupplementaryGroups": 1,
    "SyslogIdentifier": 1,
    "KillMode": 1,
    "KillSignal": 1,
}

#: Directives that must be present for this phase's service contract.
REQUIRED_DIRECTIVES = (
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
)


def render(values: Dict[str, str]) -> str:
    text = TEMPLATE.read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace("@%s@" % key, value)
    return text


def unresolved_placeholders(text: str) -> List[str]:
    """Placeholders left in *directives*.

    Comment lines are skipped: the template documents its own substitution
    syntax, and matching the word ``@PLACEHOLDER@`` in that prose would report
    a fully rendered unit as incomplete.
    """

    found = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        found.update(re.findall(r"@([A-Z_]+)@", line))
    return sorted(found)


def parse_directives(text: str) -> List[Tuple[str, str]]:
    directives = []  # type: List[Tuple[str, str]]
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        directives.append((key.strip(), value.strip()))
    return directives


def validate_unit(text: str, systemd_version: Optional[int]) -> Dict[str, Any]:
    """Check the rendered unit for completeness and target compatibility."""

    directives = parse_directives(text)
    names = {key for key, _ in directives}
    missing = [item for item in REQUIRED_DIRECTIVES if item.split("=")[0] not in names]
    # A directive present but set to the wrong value is not "missing".
    wrong = []  # type: List[str]
    wanted = {"Type": "notify", "Restart": "on-failure"}
    for key, expected in wanted.items():
        found = [value for name, value in directives if name == key]
        if found and found[0] != expected:
            wrong.append("%s=%s (expected %s)" % (key, found[0], expected))

    too_new = []  # type: List[Dict[str, Any]]
    if systemd_version:
        for name in sorted(names):
            minimum = DIRECTIVE_MIN_VERSION.get(name)
            if minimum and minimum > systemd_version:
                too_new.append({"directive": name, "requires_systemd": minimum})

    # Guard against the mistake this template is written to avoid.
    secrets_inline = [
        value for name, value in directives
        if name == "Environment" and any(
            token in value.lower() for token in ("password", "secret", "token", "key=")
        )
    ]

    placeholders = unresolved_placeholders(text)
    report = {
        "systemd_version": systemd_version,
        "directive_count": len(directives),
        "missing_required": missing,
        "wrong_values": wrong,
        "directives_newer_than_target": too_new,
        "unresolved_placeholders": placeholders,
        "inline_secret_suspects": secrets_inline,
        "has_install_section": "[Install]" in text,
        "notify_access_main": ("NotifyAccess", "main") in directives,
    }
    report["valid"] = not (
        missing or wrong or too_new or placeholders or secrets_inline
    ) and report["has_install_section"]
    return report


def installation_commands(values: Dict[str, str]) -> List[str]:
    """The exact operator commands. Printed only; never executed here."""

    unit_name = "%s.service" % values["SERVICE_NAME"]
    staged_unit = "%s/%s" % (values["STAGING_DIR"], unit_name)
    staged_env = "%s/%s.env" % (values["STAGING_DIR"], values["SERVICE_NAME"])
    return [
        "# 1. Review the rendered unit and environment file before installing.",
        "cat %s" % shlex.quote(staged_unit),
        "cat %s" % shlex.quote(staged_env),
        "",
        "# 2. Install the environment file with restrictive permissions.",
        "sudo install -d -m 0755 %s" % shlex.quote(os.path.dirname(values["ENV_FILE"])),
        "sudo install -m 0640 -o root -g %s %s %s"
        % (values["SERVICE_GROUP"], shlex.quote(staged_env), shlex.quote(values["ENV_FILE"])),
        "",
        "# 3. Install the unit.",
        "sudo install -m 0644 -o root -g root %s /etc/systemd/system/%s"
        % (shlex.quote(staged_unit), unit_name),
        "",
        "# 4. Verify systemd accepts it BEFORE enabling anything.",
        "sudo systemd-analyze verify /etc/systemd/system/%s" % unit_name,
        "sudo systemctl daemon-reload",
        "",
        "# 5. Start once, in the foreground of your attention, and watch it.",
        "sudo systemctl start %s" % unit_name,
        "systemctl status %s --no-pager" % unit_name,
        "journalctl -u %s -n 50 --no-pager" % unit_name,
        "",
        "# 6. Only after it is healthy, enable it for boot.",
        "sudo systemctl enable %s" % unit_name,
        "",
        "# Rollback, if needed:",
        "sudo systemctl disable --now %s" % unit_name,
        "sudo rm -f /etc/systemd/system/%s" % unit_name,
        "sudo systemctl daemon-reload",
    ]


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13F unit renderer (never runs sudo)")
    parser.add_argument("--service-name", default="ma-vlna-jetson-node")
    parser.add_argument("--service-user", default="myjetsonnx")
    parser.add_argument("--service-group", default="myjetsonnx")
    parser.add_argument("--repo-root", default="/home/myjetsonnx/Face_Detect_Realtime")
    parser.add_argument("--python", default="/home/myjetsonnx/venvs/ma-vlna/bin/python")
    parser.add_argument("--manifest", default="config/phase13f_service_manifest.json")
    parser.add_argument("--env-file", default="/etc/ma-vlna/jetson-node.env")
    parser.add_argument("--evidence-dir", default="/home/myjetsonnx/Face_Detect_Realtime/experiments/phase13")
    parser.add_argument("--log-dir", default="/home/myjetsonnx/ma-vlna-logs")
    parser.add_argument("--log-path", default="/home/myjetsonnx/ma-vlna-logs/service.jsonl")
    parser.add_argument("--staging-dir", default="/home/myjetsonnx/ma-vlna-staging")
    parser.add_argument("--systemd-version", type=int, default=0)
    parser.add_argument("--write-staged", default="", help="Directory to write rendered files to.")
    parser.add_argument("--print-commands", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    values = {
        "SERVICE_NAME": args.service_name,
        "SERVICE_USER": args.service_user,
        "SERVICE_GROUP": args.service_group,
        "REPO_ROOT": args.repo_root,
        "PYTHON": args.python,
        "MANIFEST": args.manifest,
        "ENV_FILE": args.env_file,
        "EVIDENCE_DIR": args.evidence_dir,
        "LOG_DIR": args.log_dir,
        "LOG_PATH": args.log_path,
        "STAGING_DIR": args.staging_dir,
    }
    unit_text = render(values)
    report = validate_unit(unit_text, args.systemd_version or None)
    report["service_name"] = args.service_name
    report["phase"] = PHASE
    report["sudo_executed"] = False
    report["etc_modified"] = False
    report["unit_installed"] = False

    if args.write_staged:
        staging = Path(args.write_staged)
        staging.mkdir(parents=True, exist_ok=True)
        unit_path = staging / ("%s.service" % args.service_name)
        env_path = staging / ("%s.env" % args.service_name)
        unit_path.write_text(unit_text, encoding="utf-8")
        env_text = ENV_EXAMPLE.read_text(encoding="utf-8")
        env_path.write_text(env_text, encoding="utf-8")
        report["staged_unit_path"] = str(unit_path)
        report["staged_env_path"] = str(env_path)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("%s unit validation" % PHASE)
        print("valid=%s" % report["valid"])
        for key in (
            "missing_required", "wrong_values", "directives_newer_than_target",
            "unresolved_placeholders", "inline_secret_suspects",
        ):
            if report[key]:
                print("%s=%s" % (key, report[key]))
        if report.get("staged_unit_path"):
            print("staged_unit=%s" % report["staged_unit_path"])
            print("staged_env=%s" % report["staged_env_path"])

    if args.print_commands:
        print("")
        print("# ---- operator installation commands (NOT run by this script) ----")
        for line in installation_commands(values):
            print(line)

    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
