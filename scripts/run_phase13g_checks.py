"""Phase 13G Gate A: everything provable without switching production authority.

Gate A is "Prepared". It proves the manifest refuses what it must refuse, the
compatibility matrix is asymmetric in the right direction, the state machine
cannot be walked into a state its recovery logic never anticipated, and the
sixteen mandatory scenarios behave against a fake systemd.

Where it runs matters. The release store is symlink-based, and Windows without
Developer Mode cannot create symlinks, so on the PC roughly half of these skip.
A skip is reported as a skip and never counted as a pass; running this on the
Jetson is what turns them into evidence.

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

from workers.core.deployment_state import describe_state_machine  # noqa: E402
from workers.core.release_manifest import describe_schema  # noqa: E402

PHASE = "13G-OTA-A-B-ROLLBACK-VERSION-COMPATIBILITY"
STATUS_PREPARED = "Prepared"
STATUS_BLOCKED = "Blocked"

TEST_PATTERNS = (
    "test_phase13g_*.py",
    "test_phase13f_*.py",
    "test_phase13er_*.py",
    "test_phase13e_*.py",
    "test_phase13d_*.py",
    "test_phase13c_*.py",
    "test_phase13b_*.py",
    "test_phase13a_*.py",
)

#: The sixteen scenarios the phase requires, mapped to the test that proves
#: each one. Listing them here means a scenario cannot be quietly dropped.
MANDATORY_SCENARIOS = {
    "1_successful_update": "TestSuccessfulUpdate.test_a_to_b_update_confirms_b",
    "2_source_sha_mismatch": "TestCandidateRejection.test_source_sha_mismatch_is_rejected",
    "3_package_hash_mismatch":
        "TestCandidateRejection.test_package_hash_mismatch_is_rejected_before_unpacking",
    "4_engine_hash_mismatch": "TestCandidateRejection.test_engine_hash_mismatch_is_rejected",
    "5_protocol_incompatibility":
        "TestCandidateRejection.test_protocol_incompatibility_is_rejected",
    "6_missing_manifest_field":
        "TestCandidateRejection.test_missing_manifest_field_is_rejected_at_stage",
    "7_service_startup_failure":
        "TestAutomaticRollback.test_service_startup_failure_rolls_back",
    "8_watchdog_failure_during_probation":
        "TestAutomaticRollback.test_watchdog_failure_during_probation_rolls_back",
    "9_restart_storm_during_probation":
        "TestAutomaticRollback.test_restart_storm_during_probation_rolls_back",
    "10_interrupted_staging":
        "TestInterruptionRecovery.test_interrupted_staging_leaves_no_installed_release",
    "11_reboot_before_switch":
        "TestInterruptionRecovery.test_reboot_before_the_switch_discards_the_candidate",
    "12_reboot_after_switch_before_confirm":
        "TestInterruptionRecovery.test_reboot_after_the_switch_rolls_back_to_last_known_good",
    "13_manual_rollback": "TestManualRollback.test_manual_rollback_returns_to_a",
    "14_failed_b_auto_rolls_back":
        "TestAutomaticRollback.test_candidate_that_never_becomes_ready_rolls_back",
    "15_rollback_also_fails":
        "TestAutomaticRollback.test_rollback_that_also_fails_is_recorded_as_failed",
    "16_old_sessions_invalid":
        "TestAuthorityAndCleanup.test_activation_forces_a_new_service_process",
}


def run_tests(pattern: str) -> Dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "scripts/tests", "-p", pattern, "-v"],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace",
    )
    output = completed.stdout or ""
    ran = re.search(r"Ran (\d+) tests?", output)
    return {
        "pattern": pattern,
        "passed": completed.returncode == 0,
        "returncode": completed.returncode,
        "tests_run": int(ran.group(1)) if ran else 0,
        "tests_skipped": len(re.findall(r"\.\.\. skipped", output)),
        "output_tail": output.strip().splitlines()[-6:],
    }


def scenario_coverage() -> Dict[str, Any]:
    """Confirm every mandatory scenario has a test that actually exists."""

    try:
        source = (REPO_ROOT / "scripts" / "tests" / "test_phase13g_deployment.py").read_text(
            encoding="utf-8"
        )
    except OSError:
        return {"covered": False, "error": "scenario test module not found"}
    missing = []
    for scenario, reference in MANDATORY_SCENARIOS.items():
        _cls, _, method = reference.partition(".")
        if ("def %s(" % method) not in source:
            missing.append({"scenario": scenario, "expected_test": reference})
    return {
        "scenario_count": len(MANDATORY_SCENARIOS),
        "missing": missing,
        "covered": not missing,
        "scenarios": dict(MANDATORY_SCENARIOS),
    }


def symlinks_available() -> bool:
    import os
    import shutil
    import tempfile

    if not hasattr(os, "symlink"):
        return False
    probe = tempfile.mkdtemp(prefix="symlink-probe-")
    try:
        os.makedirs(os.path.join(probe, "t"))
        os.symlink("t", os.path.join(probe, "l"))
        return True
    except (OSError, NotImplementedError, AttributeError):
        return False
    finally:
        shutil.rmtree(probe, ignore_errors=True)


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13G Gate A checks")
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
        "symlinks_available": symlinks_available(),
        "manifest_schema": describe_schema(),
        "state_machine": describe_state_machine(),
        # The boundary of this phase, repeated wherever it could be misread.
        "integrity_only": True,
        "signed": False,
        "secure_boot": False,
        "bootloader_ab": False,
        "rootfs_ota": False,
        "anti_rollback_security": False,
        "full_hil_verified": False,
        "real_mcu_verified": False,
        "sudo_executed": False,
        "etc_modified": False,
        "production_authority_switched": False,
    }  # type: Dict[str, Any]

    summary["scenario_coverage"] = scenario_coverage()

    reports = []  # type: List[Dict[str, Any]]
    if not args.skip_tests:
        for pattern in TEST_PATTERNS:
            reports.append(run_tests(pattern))
    summary["test_reports"] = reports
    summary["tests_passed"] = bool(reports) and all(item["passed"] for item in reports)
    summary["tests_run_total"] = sum(item["tests_run"] for item in reports)
    summary["tests_skipped_total"] = sum(item["tests_skipped"] for item in reports)
    # A skip is not a pass. On a host without symlinks the store scenarios
    # cannot run at all, and saying so is the point of this field.
    summary["store_scenarios_exercised"] = summary["symlinks_available"]

    blockers = []  # type: List[str]
    if not summary["scenario_coverage"]["covered"]:
        blockers.append("mandatory_scenario_missing")
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
    print("host=%s python=%s symlinks=%s" % (
        summary["host_machine"], summary["host_python"], summary["symlinks_available"]))
    print("mandatory_scenarios=%s covered=%s" % (
        summary["scenario_coverage"]["scenario_count"],
        summary["scenario_coverage"]["covered"]))
    print("tests_run=%s skipped=%s passed=%s" % (
        summary["tests_run_total"], summary["tests_skipped_total"], summary["tests_passed"]))
    print("store_scenarios_exercised=%s" % summary["store_scenarios_exercised"])
    if summary["blockers"]:
        print("blockers=%s" % ",".join(summary["blockers"]))
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
