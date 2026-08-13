"""Phase 13F Gate A: everything that can be established without installing a service.

Gate A is "Prepared", not "it works": it proves the unit is valid for the
systemd actually on the target, that the manifest schema refuses what it must
refuse, that preflight fails closed, and that the supervisor's restart and
watchdog behaviour holds under a real child process.

Two of the test groups only mean anything on Linux -- the ``AF_UNIX`` notify
protocol and the port-availability check -- so this script reports which ones
were skipped rather than counting a skip as a pass. Running it on the Jetson is
what turns those from skipped into evidence.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from run_phase13f_install import render, validate_unit  # noqa: E402
from workers.core.service_manifest import describe_schema  # noqa: E402

PHASE = "13F-JETSON-SERVICE-SUPERVISION-BOOT-RECOVERY"
STATUS_PREPARED = "Prepared"
STATUS_BLOCKED = "Blocked"

TEST_PATTERNS = (
    "test_phase13f_*.py",
    "test_phase13er_*.py",
    "test_phase13e_*.py",
    "test_phase13d_*.py",
    "test_phase13c_*.py",
    "test_phase13b_*.py",
    "test_phase13a_*.py",
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


def local_systemd_version() -> Optional[int]:
    try:
        completed = subprocess.run(
            ["systemctl", "--version"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    match = re.search(r"systemd\s+(\d+)", completed.stdout.decode("utf-8", "replace"))
    return int(match.group(1)) if match else None


def run_tests(pattern: str) -> Dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "scripts/tests", "-p", pattern, "-v"],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace",
    )
    output = completed.stdout or ""
    ran = re.search(r"Ran (\d+) tests?", output)
    skipped = len(re.findall(r"\.\.\. skipped", output))
    return {
        "pattern": pattern,
        "passed": completed.returncode == 0,
        "returncode": completed.returncode,
        "tests_run": int(ran.group(1)) if ran else 0,
        "tests_skipped": skipped,
        "output_tail": output.strip().splitlines()[-6:],
    }


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13F Gate A checks")
    parser.add_argument(
        "--target-systemd-version", type=int, default=245,
        help="systemd version on the Jetson; the unit is validated against it.",
    )
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--output", default="")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))

    summary = {
        "phase": PHASE,
        "gate": "A",
        "host_machine": platform.machine(),
        "host_python": platform.python_version(),
        "host_systemd_version": local_systemd_version(),
        "target_systemd_version": args.target_systemd_version,
        "manifest_schema": describe_schema(),
        # Stated up front and never contradicted elsewhere in this phase.
        "full_hil_verified": False,
        "real_mcu_verified": False,
        "secure_boot_verified": False,
        "ota_verified": False,
        "physical_camera_verified": False,
        "physical_actuator_control_executed": False,
        "sudo_executed": False,
        "etc_modified": False,
        "service_installed": False,
        "reboot_performed": False,
    }  # type: Dict[str, Any]

    unit_text = render(UNIT_VALUES)
    summary["unit_validation"] = validate_unit(unit_text, args.target_systemd_version)
    # Also validate against whatever systemd this host has, when it has one.
    if summary["host_systemd_version"]:
        summary["unit_validation_host"] = validate_unit(
            unit_text, summary["host_systemd_version"]
        )

    test_reports = []  # type: List[Dict[str, Any]]
    if not args.skip_tests:
        for pattern in TEST_PATTERNS:
            test_reports.append(run_tests(pattern))
    summary["test_reports"] = test_reports
    summary["tests_passed"] = bool(test_reports) and all(r["passed"] for r in test_reports)
    summary["tests_run_total"] = sum(r["tests_run"] for r in test_reports)
    summary["tests_skipped_total"] = sum(r["tests_skipped"] for r in test_reports)
    # A skip is not a pass. On the PC the AF_UNIX and port checks skip; running
    # this on the Jetson is what converts them into evidence.
    summary["linux_only_checks_exercised"] = (
        not platform.system().lower().startswith("win")
    )

    blockers = []  # type: List[str]
    if not summary["unit_validation"]["valid"]:
        blockers.append("unit_template_invalid")
    if not args.skip_tests and not summary["tests_passed"]:
        blockers.append("unit_tests_failed")

    summary["blockers"] = sorted(set(blockers))
    summary["status"] = STATUS_PREPARED if not blockers else STATUS_BLOCKED

    if args.output:
        path = Path(args.output)
        if not path.is_absolute():
            path = REPO_ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print("%s %s" % (PHASE, summary["status"]))
    print("host=%s python=%s systemd=%s" % (
        summary["host_machine"], summary["host_python"], summary["host_systemd_version"]))
    print("unit_valid_for_systemd_%s=%s" % (
        args.target_systemd_version, summary["unit_validation"]["valid"]))
    print("tests_run=%s skipped=%s passed=%s" % (
        summary["tests_run_total"], summary["tests_skipped_total"], summary["tests_passed"]))
    print("linux_only_checks_exercised=%s" % summary["linux_only_checks_exercised"])
    if summary["blockers"]:
        print("blockers=%s" % ",".join(summary["blockers"]))
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
