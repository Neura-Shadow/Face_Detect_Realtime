"""Phase 13F Gate D: controlled reboot cycles against the installed systemd unit.

Boot recovery is the one claim that cannot be made from a running system: the
service has to come back on its own, from a cold kernel, with nobody launching
anything. So each cycle reboots the Jetson for real, proves the reboot happened
by comparing kernel boot ids, and then measures how long the *machine* took to
reach a service that is READY.

Readiness is taken from systemd's own ``ActiveEnterTimestampMonotonic``, which
is microseconds since boot and, for a ``Type=notify`` unit, is the moment the
supervisor sent ``READY=1``. That is a better number than anything this script
could time from outside, because it excludes SSH coming back and does not
depend on when the PC happened to poll.

"No manual launch" is verified structurally rather than promised: the
supervisor's parent must be PID 1, and the node's parent must be the supervisor.

Reboots are destructive and are performed only with explicit operator
approval, recorded in the evidence. This script never installs, enables or
edits a unit, and never configures sudo.

Runtime compatibility: PC-side Python 3.10+.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from run_phase13b_jil_checks import JilSessionDriver  # noqa: E402
from run_phase13d_checks import new_run_id, pc_git_sha, run_command_utf8, utc_now_iso  # noqa: E402

PHASE = "13F-JETSON-SERVICE-SUPERVISION-BOOT-RECOVERY"
STATUS_BOOT_PASS = "Boot Pass"
STATUS_BLOCKED = "Blocked"
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]

SHOW_PROPERTIES = (
    "ActiveState", "SubState", "Result", "MainPID", "NRestarts",
    "ActiveEnterTimestampMonotonic", "ExecMainStartTimestampMonotonic",
    "WatchdogUSec", "WatchdogTimestampMonotonic", "UnitFileState",
)


class Target:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.target = "%s@%s" % (args.jetson_user, args.jetson_host)
        self.unit = args.unit

    def ssh(self, remote: str, *, timeout: int = 120) -> Dict[str, Any]:
        return run_command_utf8(["ssh"] + SSH_OPTS + [self.target, remote], timeout=timeout)

    def reachable(self) -> bool:
        result = self.ssh("echo up", timeout=25)
        return "up" in (result.get("stdout") or "")

    def boot_id(self) -> str:
        result = self.ssh("cat /proc/sys/kernel/random/boot_id", timeout=40)
        return (result.get("stdout") or "").strip()

    def unit_properties(self) -> Dict[str, str]:
        remote = "systemctl show %s --no-pager %s" % (
            shlex.quote(self.unit), " ".join("-p %s" % name for name in SHOW_PROPERTIES)
        )
        result = self.ssh(remote, timeout=90)
        payload = {}  # type: Dict[str, str]
        for line in (result.get("stdout") or "").splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                payload[key.strip()] = value.strip()
        return payload

    def health(self) -> Dict[str, Any]:
        remote = (
            "cd %s && source %s/bin/activate && python scripts/run_phase13f_service.py"
            " --status --runtime-dir %s 2>/dev/null"
            % (shlex.quote(self.args.jetson_repo), shlex.quote(self.args.jetson_venv),
               shlex.quote(self.args.runtime_dir))
        )
        result = self.ssh(remote, timeout=120)
        text = (result.get("stdout") or "").strip()
        if text.startswith("{"):
            try:
                return json.loads(text)
            except ValueError:
                pass
        return {"state": "UNKNOWN"}

    def process_lineage(self) -> Dict[str, Any]:
        """Prove nothing launched the service by hand.

        The supervisor's parent must be PID 1, and the node's parent must be
        the supervisor. Read-only: nothing here is ever signalled.
        """

        remote = (
            "MAIN=$(systemctl show %s -p MainPID --value); "
            "if [ -z \"$MAIN\" ] || [ \"$MAIN\" = 0 ]; then echo 'no_main'; exit 0; fi; "
            "echo \"main=$MAIN\"; echo \"main_ppid=$(ps -o ppid= -p $MAIN | tr -d ' ')\"; "
            "CHILD=$(ps -o pid= --ppid $MAIN | tr -d ' ' | head -1); "
            "echo \"child=$CHILD\"; "
            "if [ -n \"$CHILD\" ]; then echo \"child_cmd=$(ps -o args= -p $CHILD | head -c 120)\"; fi"
            % shlex.quote(self.unit)
        )
        result = self.ssh(remote, timeout=90)
        payload = {}  # type: Dict[str, Any]
        for line in (result.get("stdout") or "").splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                payload[key.strip()] = value.strip()
        return payload

    def reboot(self) -> Dict[str, Any]:
        """Reboot the target. Operator-approved; recorded as such."""

        result = self.ssh("sudo systemctl reboot", timeout=45)
        return {
            "reboot_requested": True,
            "returncode": result["returncode"],
            "stderr_tail": (result.get("stderr") or "").strip()[-200:],
        }

    def wait_until_down(self, *, timeout_sec: float) -> bool:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if not self.reachable():
                return True
            time.sleep(3)
        return False

    def wait_until_up(self, *, timeout_sec: float) -> Dict[str, Any]:
        started = time.time()
        deadline = started + timeout_sec
        while time.time() < deadline:
            if self.reachable():
                return {"reachable": True, "ssh_return_sec": round(time.time() - started, 3)}
            time.sleep(4)
        return {"reachable": False, "ssh_return_sec": round(time.time() - started, 3)}

    def wait_for_ready(self, *, timeout_sec: float) -> Dict[str, Any]:
        started = time.time()
        deadline = started + timeout_sec
        last = {}  # type: Dict[str, Any]
        while time.time() < deadline:
            last = self.health()
            if last.get("state") == "READY":
                last["polled_ready_sec"] = round(time.time() - started, 3)
                return last
            time.sleep(4)
        last["timed_out"] = True
        return last


def verify_fp16_authority(args: argparse.Namespace) -> Dict[str, Any]:
    """Attach a PC session and confirm FP16 authority is genuinely restored.

    A service that is READY has not yet proved it can command anything. This
    runs the real Phase 13B session against the rebooted node: new lease, new
    clock sync, periodic resync, synthetic frames over the real JILF transport,
    and commands classified by the real C Virtual Safety MCU.
    """

    driver = JilSessionDriver(
        run_id="phase13f-boot-%d" % int(time.time()),
        jetson_host=args.jetson_host,
        frame_port=args.frame_port,
        control_port=args.control_port,
        command_port=args.command_port,
        ack_port=args.ack_port,
        pc_bind_host=args.pc_bind_host,
        heartbeat_timeout_ms=args.heartbeat_timeout_ms,
        command_validity_ms=args.command_validity_ms,
        camera_width=args.camera_width,
        camera_height=args.camera_height,
    )
    report = {"session_attempted": True}  # type: Dict[str, Any]
    try:
        mcu = driver.start_virtual_mcu()
        report["virtual_mcu_ok"] = bool(mcu.get("ok"))
        if not mcu.get("ok"):
            report["error"] = "virtual MCU did not start"
            return report
        driver.connect_control(connect_timeout_sec=60.0)
        clock = driver.synchronise_clocks()
        report["clock_sync_valid"] = bool(clock.get("clock_sync_valid"))
        report["clock_uncertainty_us"] = clock.get("clock_uncertainty_us")
        driver.start_session(start_frame_server=True)
        # Periodic discipline must work after a reboot too, not just at start.
        # Space the resync like the real service does: resyncing a second after
        # the initial sync gives the drift fit a baseline too short to mean
        # anything, which is how the first Gate D run produced 455 ppm.
        time.sleep(max(0.0, float(args.resync_spacing_sec)))
        resync = driver.resync_clocks()
        report["clock_resync_accepted"] = bool(resync.get("clock_sync_accepted"))
        report["estimated_drift_ppm"] = resync.get("estimated_drift_ppm")
        report["clock_guard_us"] = resync.get("clock_guard_us")
        report["clock_sync_degraded"] = resync.get("clock_sync_degraded")
        report["clock_degraded_reasons"] = resync.get("clock_degraded_reasons")
        report["drift_baseline_sec"] = resync.get("drift_baseline_sec")
        report["drift_estimable"] = resync.get("drift_estimable")
        report["clock_resync_count"] = driver.clock_resync_count

        if not driver.connect_frames():
            report["error"] = "frame transport could not be established"
            return report
        frames = driver.publish_synthetic_frames(int(args.frames), wait_timeout_sec=120.0)
        report["frames"] = frames

        metrics = driver.collect_jetson_evidence().get("metrics", {})
        report["ai_active_command_count"] = metrics.get("ai_active_command_count")
        report["safe_stop_command_count"] = metrics.get("safe_stop_command_count")
        report["command_classifications"] = metrics.get("command_classifications")
        report["precision"] = metrics.get("precision")
        report["perception_mode"] = metrics.get("perception_mode")
        report["tensorrt_active_authority_count"] = metrics.get("tensorrt_active_authority_count")
        report["tensorrt_fallback_count"] = metrics.get("tensorrt_fallback_count")
        report["cuda_error_count"] = metrics.get("cuda_error_count")
        report["max_mailbox_depth"] = metrics.get("max_mailbox_depth")
        report["issued_future_skew_us_max"] = metrics.get("issued_future_skew_us_max")
        report["future_timestamp_reject_count"] = metrics.get("future_timestamp_reject_count")
        report["engine_sha256"] = metrics.get("engine_sha256")
        # INT8 must never hold authority; recorded as measured, not assumed.
        report["int8_authority_count"] = int(metrics.get("int8_authority_count", 0) or 0)
        accepted = int((metrics.get("command_classifications") or {}).get("ACCEPTED", 0))
        report["accepted_command_count"] = accepted
        report["fp16_authority_restored"] = bool(
            accepted > 0 and int(metrics.get("ai_active_command_count", 0) or 0) > 0
        )
    except Exception as exc:
        report["error"] = repr(exc)[:300]
        report["fp16_authority_restored"] = False
    finally:
        try:
            driver.shutdown()
        except Exception:
            pass
    return report


def run_cycle(target: Target, args: argparse.Namespace, index: int) -> Dict[str, Any]:
    print("  cycle %d: recording pre-reboot state" % index)
    sys.stdout.flush()
    before_boot_id = target.boot_id()
    before_props = target.unit_properties()
    before_health = target.health()

    cycle = {
        "cycle": index,
        "before_boot_id": before_boot_id,
        "before_active_state": before_props.get("ActiveState"),
        "before_main_pid": before_props.get("MainPID"),
        "before_nrestarts": before_props.get("NRestarts"),
        "before_state": before_health.get("state"),
        "reboot_approved_by_operator": True,
    }  # type: Dict[str, Any]

    print("  cycle %d: rebooting (operator-approved)" % index)
    sys.stdout.flush()
    reboot_started = time.time()
    cycle["reboot"] = target.reboot()
    cycle["went_down"] = target.wait_until_down(timeout_sec=float(args.down_timeout_sec))
    up = target.wait_until_up(timeout_sec=float(args.up_timeout_sec))
    cycle.update(up)
    cycle["reboot_wall_sec"] = round(time.time() - reboot_started, 3)
    if not up.get("reachable"):
        cycle["error"] = "target did not come back within %ss" % args.up_timeout_sec
        return cycle

    after_boot_id = target.boot_id()
    cycle["after_boot_id"] = after_boot_id
    # A changed kernel boot id is what proves this was a real reboot rather
    # than a service restart that happened to look like one.
    cycle["boot_id_changed"] = bool(after_boot_id) and after_boot_id != before_boot_id

    ready = target.wait_for_ready(timeout_sec=float(args.ready_timeout_sec))
    cycle["service_state_after_boot"] = ready.get("state")
    cycle["polled_ready_sec"] = ready.get("polled_ready_sec")

    props = target.unit_properties()
    cycle["after_active_state"] = props.get("ActiveState")
    cycle["after_sub_state"] = props.get("SubState")
    cycle["after_result"] = props.get("Result")
    cycle["after_main_pid"] = props.get("MainPID")
    cycle["after_nrestarts"] = props.get("NRestarts")
    cycle["unit_file_state"] = props.get("UnitFileState")
    # systemd's own measurement, in microseconds since boot: for Type=notify
    # this is the moment READY=1 arrived.
    try:
        active_enter_us = int(props.get("ActiveEnterTimestampMonotonic", "0") or 0)
    except ValueError:
        active_enter_us = 0
    cycle["boot_to_ready_sec"] = round(active_enter_us / 1e6, 3) if active_enter_us else None
    cycle["boot_to_ready_within_limit"] = bool(
        cycle["boot_to_ready_sec"] is not None
        and cycle["boot_to_ready_sec"] <= float(args.readiness_limit_sec)
    )

    cycle["lineage"] = target.process_lineage()
    lineage = cycle["lineage"]
    # Structural proof that nothing was launched by hand: systemd is the parent.
    cycle["supervisor_parent_is_systemd"] = lineage.get("main_ppid") == "1"
    cycle["node_parent_is_supervisor"] = bool(
        lineage.get("child") and lineage.get("main") == lineage.get("main")
    ) and bool(lineage.get("child"))

    cycle["health_after_boot"] = {
        key: ready.get(key) for key in (
            "state", "ai_authority_permitted", "engine_sha256", "repository_sha",
            "precision", "preflight_passed", "engine_load_count", "node_start_count",
            "restart_count", "watchdog_enabled", "watchdog_ping_count",
        )
    }
    cycle["engine_hash_verified_after_boot"] = (
        ready.get("engine_sha256") == args.expected_engine_sha256
        if args.expected_engine_sha256 else bool(ready.get("engine_sha256"))
    )
    cycle["engine_loaded_once"] = ready.get("engine_load_count") == 1

    if not args.skip_authority_check:
        print("  cycle %d: verifying FP16 authority with a real PC session" % index)
        sys.stdout.flush()
        cycle["authority"] = verify_fp16_authority(args)

    return cycle


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13F Gate D boot recovery")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--jetson-user", default="myjetsonnx")
    parser.add_argument("--jetson-host", default="192.168.55.1")
    parser.add_argument("--jetson-repo", default="/home/myjetsonnx/Face_Detect_Realtime")
    parser.add_argument("--jetson-venv", default="/home/myjetsonnx/venvs/ma-vlna")
    parser.add_argument("--unit", default="ma-vlna-jetson-node.service")
    parser.add_argument("--runtime-dir", default="/run/ma-vlna")
    parser.add_argument("--cycles", type=int, default=2)
    parser.add_argument("--readiness-limit-sec", type=float, default=120.0)
    parser.add_argument("--down-timeout-sec", type=float, default=180.0)
    parser.add_argument("--up-timeout-sec", type=float, default=420.0)
    parser.add_argument("--ready-timeout-sec", type=float, default=420.0)
    parser.add_argument("--expected-engine-sha256", default="")
    parser.add_argument("--pc-bind-host", default="192.168.55.100")
    parser.add_argument("--frame-port", type=int, default=48701)
    parser.add_argument("--control-port", type=int, default=48702)
    parser.add_argument("--command-port", type=int, default=48703)
    parser.add_argument("--ack-port", type=int, default=48704)
    parser.add_argument("--heartbeat-timeout-ms", type=int, default=3000)
    parser.add_argument("--command-validity-ms", type=int, default=500)
    parser.add_argument("--camera-width", type=int, default=320)
    parser.add_argument("--camera-height", type=int, default=180)
    parser.add_argument("--frames", type=int, default=40)
    parser.add_argument(
        "--resync-spacing-sec", type=float, default=16.0,
        help="Gap between the initial sync and the resync, matching the service interval.",
    )
    parser.add_argument("--skip-authority-check", action="store_true")
    parser.add_argument("--output-dir", default="experiments/phase13")
    parser.add_argument(
        "--operator-approved-reboot", action="store_true", required=True,
        help="Required. Reboots are destructive and are never performed implicitly.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    run_id = args.run_id or ("%s-13f-gated" % new_run_id())
    target = Target(args)

    output_root = Path(args.output_dir)
    if not output_root.is_absolute():
        output_root = REPO_ROOT / args.output_dir
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "phase": PHASE,
        "gate": "D",
        "run_id": run_id,
        "created_at_utc": utc_now_iso(),
        "runtime_pc_git_sha": pc_git_sha(),
        "jetson_target": target.target,
        "unit": args.unit,
        "cycles_requested": int(args.cycles),
        "readiness_limit_sec": float(args.readiness_limit_sec),
        "operator_approved_reboot": True,
        "sudo_configured_by_claude": False,
        "passwordless_sudo_enabled_by_claude": False,
        "unit_installed_by_claude": False,
        "etc_modified_by_claude": False,
        "full_hil_verified": False,
        "real_mcu_verified": False,
        "secure_boot_verified": False,
        "ota_verified": False,
        "physical_camera_verified": False,
    }  # type: Dict[str, Any]

    sha = target.ssh("cd %s && git rev-parse HEAD" % shlex.quote(args.jetson_repo), timeout=60)
    jetson_sha = ""
    for line in (sha.get("stdout") or "").splitlines():
        if len(line.strip()) == 40:
            jetson_sha = line.strip()
    summary["runtime_jetson_git_sha"] = jetson_sha
    summary["runtime_git_sha_match"] = jetson_sha == summary["runtime_pc_git_sha"]

    print("%s Gate D run_id=%s cycles=%d" % (PHASE, run_id, args.cycles))
    cycles = []  # type: List[Dict[str, Any]]
    blockers = []  # type: List[str]
    try:
        for index in range(1, int(args.cycles) + 1):
            cycle = run_cycle(target, args, index)
            cycles.append(cycle)
            print("  cycle %d: boot_to_ready=%ss within_limit=%s boot_id_changed=%s authority=%s"
                  % (index, cycle.get("boot_to_ready_sec"),
                     cycle.get("boot_to_ready_within_limit"), cycle.get("boot_id_changed"),
                     (cycle.get("authority") or {}).get("fp16_authority_restored")))
    except Exception as exc:
        summary["error"] = repr(exc)[:400]
        blockers.append("gate_d_run_failed")

    summary["cycles"] = cycles
    summary["cycles_completed"] = len(cycles)
    if len(cycles) < int(args.cycles):
        blockers.append("insufficient_reboot_cycles")
    for cycle in cycles:
        if not cycle.get("boot_id_changed"):
            blockers.append("reboot_not_observed")
        if cycle.get("service_state_after_boot") != "READY":
            blockers.append("service_not_ready_after_boot")
        if not cycle.get("boot_to_ready_within_limit"):
            blockers.append("readiness_exceeded_limit")
        if not cycle.get("engine_hash_verified_after_boot"):
            blockers.append("engine_hash_not_verified_after_boot")
        if not cycle.get("engine_loaded_once"):
            blockers.append("engine_not_loaded_once_per_start")
        if not cycle.get("supervisor_parent_is_systemd"):
            blockers.append("service_not_started_by_systemd")
        authority = cycle.get("authority") or {}
        if not args.skip_authority_check:
            if not authority.get("fp16_authority_restored"):
                blockers.append("fp16_authority_not_restored")
            if int(authority.get("int8_authority_count", 0) or 0):
                blockers.append("int8_authority_observed")
            if not authority.get("clock_resync_accepted"):
                blockers.append("clock_resync_failed_after_boot")

    summary["blockers"] = sorted(set(blockers))
    summary["status"] = STATUS_BOOT_PASS if not summary["blockers"] else STATUS_BLOCKED
    (run_dir / "gate_d_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")

    print("")
    print("%s %s" % (PHASE, summary["status"]))
    print("run_id=%s" % run_id)
    print("evidence_dir=%s" % run_dir)
    print("cycles_completed=%s/%s" % (summary["cycles_completed"], args.cycles))
    for cycle in cycles:
        print("cycle %s: boot_to_ready=%ss limit=%s reboot=%s engine_hash=%s fp16=%s" % (
            cycle["cycle"], cycle.get("boot_to_ready_sec"),
            cycle.get("boot_to_ready_within_limit"), cycle.get("boot_id_changed"),
            cycle.get("engine_hash_verified_after_boot"),
            (cycle.get("authority") or {}).get("fp16_authority_restored")))
    if summary["blockers"]:
        print("blockers=%s" % ",".join(summary["blockers"]))
    return 0 if not summary["blockers"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
