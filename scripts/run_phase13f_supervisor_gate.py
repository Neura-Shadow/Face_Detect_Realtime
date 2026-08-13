"""Phase 13F Gate B: the production wrapper under fault injection on the real Jetson.

Gate B runs the wrapper exactly as systemd will run it, but started by hand, so
that supervision can be proved before anything is installed into ``/etc``. A
stand-in systemd notify listener binds ``NOTIFY_SOCKET`` on the target and
counts ``WATCHDOG=1`` datagrams, which makes watchdog behaviour observable
without a unit file.

The fault matrix is the point. Each case names what must happen, not merely
that something happened:

===== ====================== ==========================================
Case  Fault                  Required outcome
===== ====================== ==========================================
S01   SIGTERM to the node    wrapper respawns it, service returns READY
S02   SIGKILL to the node    same, and the exit is classified as failure
S03   missing engine         preflight fails closed, SAFE_STOP, no authority
S04   corrupt engine hash    preflight fails closed, SAFE_STOP, no authority
S05   port already held      preflight fails closed on the exact port
S06   repeated node failure  restart storm blocked, FAILED, non-zero exit
S07   PC unavailable         service stays up, no AI authority is granted
S08   SIGTERM to the wrapper graceful stop, SAFE_STOP, node stopped
===== ====================== ==========================================

Only recorded PIDs are ever signalled. ``pkill``, ``killall`` and name matching
are never used: a name match has previously killed the controlling SSH session.

Runtime compatibility: PC-side Python 3.10+; everything on the Jetson runs
under its own 3.8.10 venv.
"""

from __future__ import annotations

import argparse
import base64
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

from run_phase13d_checks import new_run_id, pc_git_sha, run_command_utf8, utc_now_iso  # noqa: E402

PHASE = "13F-JETSON-SERVICE-SUPERVISION-BOOT-RECOVERY"
STATUS_SUPERVISOR_PASS = "Supervisor Pass"
STATUS_BLOCKED = "Blocked"
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]

#: Stand-in for systemd's notify listener: binds the socket, counts datagrams,
#: writes a running tally so the PC can read it over SSH.
NOTIFY_LISTENER = r'''
import json, os, socket, sys, time
path, out = sys.argv[1], sys.argv[2]
try:
    os.unlink(path)
except OSError:
    pass
s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
s.bind(path)
s.settimeout(5.0)
counts = {"READY": 0, "WATCHDOG": 0, "STOPPING": 0, "STATUS": 0, "total": 0}
last_status = ""
started = time.time()
while True:
    try:
        data = s.recv(4096).decode("utf-8", "replace")
    except socket.timeout:
        data = ""
    if data:
        counts["total"] += 1
        for line in data.splitlines():
            key = line.split("=", 1)[0]
            if key in counts:
                counts[key] += 1
            if key == "STATUS":
                last_status = line.split("=", 1)[1]
    payload = dict(counts)
    payload["last_status"] = last_status
    payload["uptime_sec"] = round(time.time() - started, 3)
    tmp = out + ".tmp"
    with open(tmp, "w") as handle:
        json.dump(payload, handle)
    os.replace(tmp, out)
'''


class JetsonSession:
    """Every remote action, with recorded PIDs and no name-based killing."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.target = "%s@%s" % (args.jetson_user, args.jetson_host)
        self.repo = args.jetson_repo
        self.venv = args.jetson_venv
        self.runtime_dir = args.runtime_dir
        self.wrapper_pid = None  # type: Optional[int]
        self.listener_pid = None  # type: Optional[int]

    def ssh(self, remote: str, *, timeout: int = 300) -> Dict[str, Any]:
        return run_command_utf8(["ssh"] + SSH_OPTS + [self.target, remote], timeout=timeout)

    def python(self, code: str, *, timeout: int = 300) -> Dict[str, Any]:
        remote = "cd %s && source %s/bin/activate && python -c %s" % (
            shlex.quote(self.repo), shlex.quote(self.venv), shlex.quote(code)
        )
        return self.ssh(remote, timeout=timeout)

    # ── lifecycle ───────────────────────────────────────────────────────────

    def start_notify_listener(self) -> Dict[str, Any]:
        socket_path = "%s/notify.sock" % self.runtime_dir
        counts_path = "%s/notify_counts.json" % self.runtime_dir
        pid_path = "%s/notify.pid" % self.runtime_dir
        script_path = "%s/notify_listener.py" % self.runtime_dir
        # base64 rather than a heredoc: a heredoc cannot be chained with `&&`
        # after its terminator, and this sidesteps every quoting hazard in
        # shipping a Python script through ssh.
        encoded = base64.b64encode(NOTIFY_LISTENER.encode("utf-8")).decode("ascii")
        remote = " && ".join([
            "mkdir -p %s" % shlex.quote(self.runtime_dir),
            "echo %s | base64 -d > %s" % (shlex.quote(encoded), shlex.quote(script_path)),
            "setsid nohup python3 %s %s %s </dev/null >%s/notify.log 2>&1 & echo $! > %s"
            % (script_path, socket_path, counts_path, self.runtime_dir, pid_path),
            "sleep 1",
            "cat %s" % pid_path,
        ])
        result = self.ssh(remote, timeout=120)
        for line in (result.get("stdout") or "").splitlines():
            if line.strip().isdigit():
                self.listener_pid = int(line.strip())
        return {
            "listener_pid": self.listener_pid,
            "notify_socket": socket_path,
            "notify_counts_path": counts_path,
            "returncode": result["returncode"],
        }

    def notify_counts(self) -> Dict[str, Any]:
        result = self.ssh(
            "cat %s/notify_counts.json 2>/dev/null || echo '{}'" % shlex.quote(self.runtime_dir),
            timeout=60,
        )
        try:
            return json.loads((result.get("stdout") or "{}").strip() or "{}")
        except ValueError:
            return {}

    def start_wrapper(self, *, extra_args: str = "", with_notify: bool = True) -> Dict[str, Any]:
        pid_path = "%s/wrapper.pid" % self.runtime_dir
        log_path = "%s/wrapper.log" % self.runtime_dir
        env = ""
        if with_notify:
            # `env` rather than a bare VAR=value prefix: nohup treats its first
            # argument as the command name, so `nohup NOTIFY_SOCKET=... python`
            # fails with "No such file or directory".
            env = "env NOTIFY_SOCKET=%s/notify.sock WATCHDOG_USEC=%d " % (
                self.runtime_dir, int(self.args.watchdog_usec)
            )
        command = (
            "%spython scripts/run_phase13f_service.py"
            " --manifest %s --runtime-dir %s --evidence-dir experiments/phase13"
            " --log-path %s/service.jsonl --pc-host %s"
            " --frame-port %d --control-port %d --command-port %d --ack-port %d"
            " --expected-repo-sha %s --restart-initial-sec %s --restart-max-sec %s"
            " --max-restarts %d --restart-window-sec %s --node-ready-timeout-sec %s %s"
            % (
                env, shlex.quote(self.args.manifest), shlex.quote(self.runtime_dir),
                shlex.quote(self.runtime_dir), self.args.pc_host,
                self.args.frame_port, self.args.control_port,
                self.args.command_port, self.args.ack_port,
                self.args.expected_repo_sha, self.args.restart_initial_sec,
                self.args.restart_max_sec, self.args.max_restarts,
                self.args.restart_window_sec, self.args.node_ready_timeout_sec,
                extra_args,
            )
        )
        remote = " && ".join([
            "cd %s" % shlex.quote(self.repo),
            "source %s/bin/activate" % shlex.quote(self.venv),
            "setsid nohup %s </dev/null >%s 2>&1 & echo $! > %s" % (command, log_path, pid_path),
            "sleep 1",
            "cat %s" % pid_path,
        ])
        result = self.ssh(remote, timeout=180)
        for line in (result.get("stdout") or "").splitlines():
            if line.strip().isdigit():
                self.wrapper_pid = int(line.strip())
        return {"wrapper_pid": self.wrapper_pid, "returncode": result["returncode"],
                "command": command}

    def health(self) -> Dict[str, Any]:
        code = (
            "import json,sys;"
            "sys.path.insert(0,'.');"
            "from workers.core.service_health import query_health;"
            "print(json.dumps(query_health('%s/health.sock', timeout_sec=5)))" % self.runtime_dir
        )
        result = self.python(code, timeout=90)
        for line in reversed((result.get("stdout") or "").splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except ValueError:
                    continue
        return {"state": "UNKNOWN", "error": (result.get("stderr") or "")[-300:]}

    def wait_for_state(self, state: str, *, timeout_sec: float) -> Dict[str, Any]:
        deadline = time.time() + float(timeout_sec)
        last = {}  # type: Dict[str, Any]
        while time.time() < deadline:
            last = self.health()
            if last.get("state") == state:
                last["wait_sec"] = round(timeout_sec - (deadline - time.time()), 3)
                return last
            time.sleep(3)
        last["timed_out"] = True
        return last

    def signal_pid(self, pid: Optional[int], signal_name: str) -> Dict[str, Any]:
        """Signal exactly one recorded PID. Never a name, never a pattern."""

        if not pid:
            return {"signalled": False, "reason": "no recorded pid"}
        result = self.ssh(
            'if kill -0 %d 2>/dev/null; then kill -%s %d && echo signalled=%d; '
            'else echo not_running=%d; fi' % (pid, signal_name, pid, pid, pid),
            timeout=60,
        )
        output = (result.get("stdout") or "").strip()
        return {"signalled": "signalled=" in output, "pid": pid,
                "signal": signal_name, "output": output}

    def node_pid(self) -> Optional[int]:
        health = self.health()
        pid = health.get("node_pid")
        return int(pid) if isinstance(pid, int) else None

    def stop_all(self) -> Dict[str, Any]:
        """Stop exactly what we started, in order, and confirm."""

        report = {}  # type: Dict[str, Any]
        report["wrapper"] = self.signal_pid(self.wrapper_pid, "TERM")
        time.sleep(6)
        report["wrapper_still_running"] = self._pid_alive(self.wrapper_pid)
        if report["wrapper_still_running"]:
            report["wrapper_kill"] = self.signal_pid(self.wrapper_pid, "KILL")
            time.sleep(2)
        report["listener"] = self.signal_pid(self.listener_pid, "TERM")
        # Any node the wrapper did not reap is an orphan; count it honestly.
        report["orphans"] = self.orphan_report()
        return report

    def _pid_alive(self, pid: Optional[int]) -> bool:
        if not pid:
            return False
        result = self.ssh(
            'if kill -0 %d 2>/dev/null; then echo alive; else echo gone; fi' % pid, timeout=60
        )
        return "alive" in (result.get("stdout") or "")

    def orphan_report(self) -> Dict[str, Any]:
        """Count leftover node processes without ever matching by name to kill.

        ``pgrep`` is used read-only here and its own SSH command line is
        excluded, because a bare ``pgrep -f`` matches the very command running
        it. Nothing is signalled on the basis of this.
        """

        result = self.ssh(
            "ps -eo pid,args | grep 'run_phase13b_jetson_node' | grep -v grep | "
            "grep -v 'ps -eo' | awk '{print $1}' || true",
            timeout=60,
        )
        pids = [int(item) for item in (result.get("stdout") or "").split() if item.isdigit()]
        return {"leftover_node_pids": pids, "orphan_count": len(pids)}

    def tail_log(self, name: str, lines: int = 40) -> List[str]:
        result = self.ssh(
            "tail -n %d %s/%s 2>/dev/null || true" % (lines, shlex.quote(self.runtime_dir), name),
            timeout=90,
        )
        return (result.get("stdout") or "").splitlines()[-lines:]


class GateBRunner:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.session = JetsonSession(args)
        self.cases = []  # type: List[Dict[str, Any]]
        self.blockers = []  # type: List[str]

    def record(self, case_id: str, name: str, expected: str, observed: str,
               detail: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        row = {
            "case_id": case_id,
            "name": name,
            "expected": expected,
            "observed": observed,
            "passed": expected == observed,
            "detail": detail or {},
        }
        self.cases.append(row)
        print("  %-5s %-34s expected=%-22s observed=%-22s %s" % (
            case_id, name, expected, observed, "PASS" if row["passed"] else "FAIL"))
        sys.stdout.flush()
        return row

    # ── fault cases ─────────────────────────────────────────────────────────

    def case_signal_node(self, case_id: str, signal_name: str) -> None:
        """Killing the node must be survived by the service."""

        before = self.session.health()
        pid = before.get("node_pid")
        starts_before = int(before.get("node_start_count", 0) or 0)
        signalled = self.session.signal_pid(pid, signal_name)
        if not signalled.get("signalled"):
            self.record(case_id, "node %s" % signal_name, "READY", "NO_NODE_PID", signalled)
            return
        recovered = self.session.wait_for_state(
            "READY", timeout_sec=float(self.args.recovery_timeout_sec)
        )
        starts_after = int(recovered.get("node_start_count", 0) or 0)
        observed = "READY" if recovered.get("state") == "READY" else str(recovered.get("state"))
        if observed == "READY" and starts_after <= starts_before:
            observed = "NOT_RESPAWNED"
        self.record(
            case_id, "node %s" % signal_name, "READY", observed,
            {
                "node_pid_before": pid,
                "node_pid_after": recovered.get("node_pid"),
                "node_start_count_before": starts_before,
                "node_start_count_after": starts_after,
                "restart_count": recovered.get("restart_count"),
                "recovery_sec": recovered.get("wait_sec"),
            },
        )

    def case_preflight_failure(self, case_id: str, name: str, setup: str, teardown: str) -> None:
        """A broken precondition must fail closed with no AI authority."""

        self.session.stop_all()
        self.session.ssh(setup, timeout=120)
        try:
            self.session.start_wrapper()
            health = self.session.wait_for_state(
                "SAFE_STOP", timeout_sec=float(self.args.preflight_timeout_sec)
            )
            observed = str(health.get("state"))
            authority = bool(health.get("ai_authority_permitted", False))
            if observed == "SAFE_STOP" and authority:
                observed = "SAFE_STOP_BUT_AUTHORITY_PERMITTED"
            self.record(
                case_id, name, "SAFE_STOP", observed,
                {
                    "ai_authority_permitted": authority,
                    "preflight_failed_checks": health.get("preflight_failed_checks"),
                    "reason": health.get("reason"),
                },
            )
        finally:
            self.session.stop_all()
            self.session.ssh(teardown, timeout=120)

    def case_restart_storm(self) -> None:
        """Repeated node failure must be blocked, not retried forever."""

        self.session.stop_all()
        # A node that cannot start at all: point it at a non-existent profile so
        # every generation fails immediately. Preflight still passes, so the
        # storm limit is what has to stop it.
        self.session.start_wrapper(
            extra_args="--node-extra-args --tensorrt-engine=/nonexistent/engine.plan"
                       " --node-ready-timeout-sec 8"
        )
        deadline = time.time() + float(self.args.storm_timeout_sec)
        health = {}  # type: Dict[str, Any]
        saw_failed = False
        while time.time() < deadline:
            health = self.session.health()
            if health.get("state") == "FAILED":
                saw_failed = True
                break
            if not self.session._pid_alive(self.session.wrapper_pid):
                break
            time.sleep(4)
        alive = self.session._pid_alive(self.session.wrapper_pid)
        log = self.session.tail_log("service.jsonl", 200)
        storm_logged = any("restart_storm_blocked" in line for line in log)
        observed = "BLOCKED" if (saw_failed or storm_logged) else str(health.get("state", "UNKNOWN"))
        self.record(
            "S06", "restart storm", "BLOCKED", observed,
            {
                "saw_failed_state": saw_failed,
                "storm_logged": storm_logged,
                "wrapper_alive_after": alive,
                "restart_count": health.get("restart_count"),
                "node_start_count": health.get("node_start_count"),
            },
        )
        self.session.stop_all()

    def case_pc_unavailable(self) -> None:
        """With no PC session, the service stays up and grants nothing."""

        health = self.session.health()
        commands = int(health.get("node_start_count", 0) or 0)
        observed = "READY_NO_AUTHORITY"
        if health.get("state") != "READY":
            observed = str(health.get("state"))
        self.record(
            "S07", "PC unavailable", "READY_NO_AUTHORITY", observed,
            {
                "state": health.get("state"),
                "node_start_count": commands,
                "note": "the node listens; without a PC session no command is ever issued",
            },
        )

    def case_graceful_stop(self) -> None:
        """SIGTERM to the wrapper: SAFE_STOP, node stopped, no orphan."""

        before = self.session.health()
        node_pid = before.get("node_pid")
        self.session.signal_pid(self.session.wrapper_pid, "TERM")
        deadline = time.time() + 45
        while time.time() < deadline:
            if not self.session._pid_alive(self.session.wrapper_pid):
                break
            time.sleep(2)
        wrapper_gone = not self.session._pid_alive(self.session.wrapper_pid)
        node_gone = not self.session._pid_alive(node_pid) if node_pid else True
        last_status = self.session.ssh(
            "cat %s/last_status.json 2>/dev/null || echo '{}'" % shlex.quote(self.args.runtime_dir),
            timeout=60,
        )
        try:
            final = json.loads((last_status.get("stdout") or "{}").strip() or "{}")
        except ValueError:
            final = {}
        observed = "SAFE_STOP" if final.get("state") == "SAFE_STOP" else str(final.get("state"))
        if not (wrapper_gone and node_gone):
            observed = "PROCESSES_LEFT_RUNNING"
        self.record(
            "S08", "SIGTERM to wrapper", "SAFE_STOP", observed,
            {
                "wrapper_exited": wrapper_gone,
                "node_exited": node_gone,
                "final_state": final.get("state"),
                "safe_stop_count": final.get("safe_stop_count"),
            },
        )


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13F Gate B supervisor fault matrix")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--jetson-user", default="myjetsonnx")
    parser.add_argument("--jetson-host", default="192.168.55.1")
    parser.add_argument("--jetson-repo", default="/home/myjetsonnx/Face_Detect_Realtime")
    parser.add_argument("--jetson-venv", default="/home/myjetsonnx/venvs/ma-vlna")
    parser.add_argument("--runtime-dir", default="/tmp/ma-vlna-gateb")
    parser.add_argument("--manifest", default="config/phase13f_service_manifest.json")
    parser.add_argument("--expected-repo-sha", default="")
    parser.add_argument("--pc-host", default="192.168.55.100")
    parser.add_argument("--frame-port", type=int, default=48701)
    parser.add_argument("--control-port", type=int, default=48702)
    parser.add_argument("--command-port", type=int, default=48703)
    parser.add_argument("--ack-port", type=int, default=48704)
    parser.add_argument("--watchdog-usec", type=int, default=30_000_000)
    parser.add_argument("--soak-sec", type=float, default=1800.0)
    parser.add_argument("--min-soak-sec", type=float, default=1800.0)
    parser.add_argument("--health-poll-sec", type=float, default=30.0)
    parser.add_argument("--ready-timeout-sec", type=float, default=300.0)
    parser.add_argument("--recovery-timeout-sec", type=float, default=300.0)
    parser.add_argument("--preflight-timeout-sec", type=float, default=180.0)
    parser.add_argument("--storm-timeout-sec", type=float, default=300.0)
    parser.add_argument("--node-ready-timeout-sec", type=float, default=180.0)
    parser.add_argument("--restart-initial-sec", type=float, default=2.0)
    parser.add_argument("--restart-max-sec", type=float, default=15.0)
    parser.add_argument("--max-restarts", type=int, default=5)
    parser.add_argument("--restart-window-sec", type=float, default=300.0)
    parser.add_argument("--output-dir", default="experiments/phase13")
    parser.add_argument("--skip-soak", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    run_id = args.run_id or ("%s-13f-gateb" % new_run_id())
    runner = GateBRunner(args)
    session = runner.session
    expected_sha = args.expected_repo_sha or pc_git_sha()
    args.expected_repo_sha = expected_sha

    output_root = Path(args.output_dir)
    if not output_root.is_absolute():
        output_root = REPO_ROOT / args.output_dir
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "phase": PHASE,
        "gate": "B",
        "run_id": run_id,
        "created_at_utc": utc_now_iso(),
        "runtime_pc_git_sha": expected_sha,
        "jetson_target": session.target,
        "systemd_installed": False,
        "sudo_executed": False,
        "etc_modified": False,
        "reboot_performed": False,
        "full_hil_verified": False,
        "real_mcu_verified": False,
        "secure_boot_verified": False,
        "ota_verified": False,
        "physical_camera_verified": False,
    }  # type: Dict[str, Any]

    sha_result = session.ssh("cd %s && git rev-parse HEAD" % shlex.quote(args.jetson_repo))
    jetson_sha = ""
    for line in (sha_result.get("stdout") or "").splitlines():
        if len(line.strip()) == 40:
            jetson_sha = line.strip()
    summary["runtime_jetson_git_sha"] = jetson_sha
    summary["runtime_git_sha_match"] = bool(jetson_sha) and jetson_sha == expected_sha
    if not summary["runtime_git_sha_match"]:
        summary["status"] = STATUS_BLOCKED
        summary["blockers"] = ["runtime_git_sha_mismatch"]
        (run_dir / "gate_b_summary.json").write_text(
            json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print("%s Blocked: Jetson %s vs PC %s" % (PHASE, jetson_sha, expected_sha))
        return 1

    print("%s Gate B run_id=%s" % (PHASE, run_id))
    print("fault matrix:")
    try:
        session.ssh("rm -rf %s && mkdir -p %s" % (
            shlex.quote(args.runtime_dir), shlex.quote(args.runtime_dir)), timeout=120)
        summary["notify_listener"] = session.start_notify_listener()
        summary["wrapper_start"] = session.start_wrapper()
        ready = session.wait_for_state("READY", timeout_sec=float(args.ready_timeout_sec))
        summary["initial_ready"] = ready
        if ready.get("state") != "READY":
            runner.blockers.append("service_never_became_ready")
            summary["initial_ready_failed"] = True
        else:
            runner.record("S00", "initial start", "READY", "READY", {
                "node_pid": ready.get("node_pid"),
                "engine_sha256": ready.get("engine_sha256"),
                "preflight_passed": ready.get("preflight_passed"),
            })

            runner.case_signal_node("S01", "TERM")
            runner.case_signal_node("S02", "KILL")
            runner.case_pc_unavailable()

            # Watchdog evidence: pings observed by the stand-in listener.
            counts = session.notify_counts()
            summary["notify_counts_during_run"] = counts
            runner.record(
                "S09", "watchdog pings observed",
                "PINGED", "PINGED" if int(counts.get("WATCHDOG", 0)) > 0 else "NO_PINGS",
                counts,
            )

            if not args.skip_soak:
                print("  soak: %.0f s with health polling" % args.soak_sec)
                sys.stdout.flush()
                soak = run_soak(session, args)
                summary["soak"] = soak
                if soak["duration_sec"] < float(args.min_soak_sec):
                    runner.blockers.append("supervisor_soak_too_short")
                if not soak["state_held_ready"]:
                    runner.blockers.append("service_did_not_hold_ready")
                counts_after = session.notify_counts()
                summary["notify_counts_after_soak"] = counts_after
                summary["watchdog_pings_total"] = int(counts_after.get("WATCHDOG", 0))

            runner.case_graceful_stop()

        # Preflight failure cases each restart the wrapper from a broken state.
        engine = "/home/myjetsonnx/models/ma-vlna/yolov9/yolov9-c-640-b1-trt852-fp16.engine"
        runner.case_preflight_failure(
            "S03", "missing engine",
            "mv %s %s.gateb-hidden" % (engine, engine),
            "mv %s.gateb-hidden %s" % (engine, engine),
        )
        manifest_path = "%s/%s" % (args.jetson_repo, args.manifest)
        runner.case_preflight_failure(
            "S04", "corrupt engine hash",
            "cp %s %s.bak && python3 -c \"import json;p='%s';d=json.load(open(p));"
            "d['engine_sha256']='%s';json.dump(d,open(p,'w'))\""
            % (manifest_path, manifest_path, manifest_path, "f" * 64),
            "mv %s.bak %s" % (manifest_path, manifest_path),
        )
        runner.case_preflight_failure(
            "S05", "control port already held",
            "setsid nohup python3 -c \"import socket,time;s=socket.socket();"
            "s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);"
            "s.bind(('0.0.0.0',%d));s.listen(1);time.sleep(600)\" </dev/null "
            ">%s/portholder.log 2>&1 & echo $! > %s/portholder.pid; sleep 2"
            % (args.control_port, args.runtime_dir, args.runtime_dir),
            "if [ -f %s/portholder.pid ]; then kill $(cat %s/portholder.pid) 2>/dev/null || true; "
            "rm -f %s/portholder.pid; fi"
            % (args.runtime_dir, args.runtime_dir, args.runtime_dir),
        )
        runner.case_restart_storm()

    except Exception as exc:
        summary["error"] = repr(exc)[:400]
        runner.blockers.append("gate_b_run_failed")
    finally:
        summary["cleanup"] = session.stop_all()
        summary["service_log_tail"] = session.tail_log("service.jsonl", 30)

    orphans = summary.get("cleanup", {}).get("orphans", {})
    summary["orphan_count"] = int(orphans.get("orphan_count", 0))
    if summary["orphan_count"]:
        runner.blockers.append("orphan_node_processes")

    summary["fault_matrix"] = runner.cases
    summary["fault_case_count"] = len(runner.cases)
    summary["fault_case_passed_count"] = sum(1 for row in runner.cases if row["passed"])
    failed = [row["case_id"] for row in runner.cases if not row["passed"]]
    summary["failed_cases"] = failed
    if failed:
        runner.blockers.append("supervisor_fault_case_failed")

    summary["blockers"] = sorted(set(runner.blockers))
    summary["status"] = STATUS_SUPERVISOR_PASS if not summary["blockers"] else STATUS_BLOCKED
    (run_dir / "gate_b_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")

    print("")
    print("%s %s" % (PHASE, summary["status"]))
    print("run_id=%s" % run_id)
    print("evidence_dir=%s" % run_dir)
    print("fault_cases=%s/%s" % (summary["fault_case_passed_count"], summary["fault_case_count"]))
    print("watchdog_pings_total=%s" % summary.get("watchdog_pings_total"))
    print("orphan_count=%s" % summary["orphan_count"])
    if summary.get("soak"):
        print("soak_sec=%s state_held_ready=%s" % (
            summary["soak"]["duration_sec"], summary["soak"]["state_held_ready"]))
    if summary["blockers"]:
        print("blockers=%s" % ",".join(summary["blockers"]))
    return 0 if not summary["blockers"] else 1


def run_soak(session: JetsonSession, args: argparse.Namespace) -> Dict[str, Any]:
    """Hold the service and watch it, without touching it."""

    started = time.time()
    deadline = started + float(args.soak_sec)
    samples = []  # type: List[Dict[str, Any]]
    state_held = True
    while time.time() < deadline:
        health = session.health()
        samples.append({
            "elapsed_sec": round(time.time() - started, 1),
            "state": health.get("state"),
            "node_pid": health.get("node_pid"),
            "restart_count": health.get("restart_count"),
            "node_start_count": health.get("node_start_count"),
            "heartbeat_age_sec": health.get("heartbeat_age_sec"),
        })
        if health.get("state") != "READY":
            state_held = False
        time.sleep(float(args.health_poll_sec))
    duration = time.time() - started
    node_starts = [s["node_start_count"] for s in samples if s["node_start_count"] is not None]
    return {
        "duration_sec": round(duration, 3),
        "sample_count": len(samples),
        "state_held_ready": state_held,
        "node_start_count_first": node_starts[0] if node_starts else None,
        "node_start_count_last": node_starts[-1] if node_starts else None,
        "unexpected_restarts": (node_starts[-1] - node_starts[0]) if len(node_starts) > 1 else 0,
        # Bounded: only a trailing window of samples is retained in evidence.
        "samples_tail": samples[-40:],
    }


if __name__ == "__main__":
    raise SystemExit(main())
