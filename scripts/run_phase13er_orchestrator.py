"""Phase 13E-R orchestrator: one continuous process set per soak run.

Gate C requires the burn-in and the soak to come from a single uninterrupted
run. Starting the Jetson node by hand and then driving it from a second shell
makes that hard to guarantee and impossible to prove afterwards, so this script
owns the whole lifecycle: verify both repositories are at the same commit, start
exactly one node, drive every requested phase, then stop exactly the PID it
started.

Safety rules carried forward unchanged: no password is stored, no JetPack,
kernel, nvpmodel, clock, thermal, SSH, firewall or ICS setting is touched, no
dependency is installed, and only the run-specific PID recorded here is stopped
-- never ``pkill`` or a broad ``kill``, which has previously matched and killed
the controlling SSH session itself.
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

from run_phase13d_checks import (  # noqa: E402
    new_run_id,
    pc_git_sha,
    run_command,
    utc_now_iso,
)

PHASE = "13E-R-CLOCK-DRIFT-BACKPRESSURE-RECOVERY"
DEFAULT_BRANCH = "codex/phase-11o-source-commit-boundary"
DEFAULT_JETSON_USER = "myjetsonnx"
DEFAULT_JETSON_HOST = "192.168.55.1"
DEFAULT_JETSON_REPO = "/home/myjetsonnx/Face_Detect_Realtime"
DEFAULT_JETSON_VENV = "/home/myjetsonnx/venvs/ma-vlna"
DEFAULT_FP16_ENGINE = (
    "/home/myjetsonnx/models/ma-vlna/yolov9/yolov9-c-640-b1-trt852-fp16.engine"
)
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]


def ssh(target: str, remote: str, *, timeout: int = 600) -> Dict[str, Any]:
    return run_command(["ssh"] + SSH_OPTS + [target, remote], timeout=timeout)


def repository_guard(branch: str) -> Dict[str, Any]:
    status = run_command(["git", "status", "--short"], timeout=60)
    current = run_command(["git", "branch", "--show-current"], timeout=60)
    head = run_command(["git", "rev-parse", "HEAD"], timeout=60)
    remote = run_command(["git", "rev-parse", "origin/%s" % branch], timeout=60)
    worktrees = run_command(["git", "worktree", "list"], timeout=60)
    payload = {
        "branch": current["stdout"].strip(),
        "branch_expected": branch,
        "head_sha": head["stdout"].strip(),
        "origin_head_sha": remote["stdout"].strip(),
        "worktree_clean": not status["stdout"].strip(),
        "worktree_count": len(worktrees["stdout"].strip().splitlines()),
    }
    payload["local_matches_remote"] = bool(payload["head_sha"]) and (
        payload["head_sha"] == payload["origin_head_sha"]
    )
    payload["guard_passed"] = (
        payload["branch"] == branch
        and payload["worktree_clean"]
        and payload["local_matches_remote"]
        and payload["worktree_count"] == 1
    )
    return payload


def jetson_sha(target: str, repo: str) -> str:
    result = ssh(target, "cd %s && git rev-parse HEAD" % shlex.quote(repo), timeout=120)
    for line in result["stdout"].splitlines():
        candidate = line.strip()
        if len(candidate) == 40 and all(char in "0123456789abcdef" for char in candidate):
            return candidate
    return ""


def pid_path(run_id: str) -> str:
    return "/tmp/ma-vlna-phase13er-%s.pid" % run_id


def log_path(run_id: str) -> str:
    return "/tmp/ma-vlna-phase13er-%s.log" % run_id


def jetson_node_command(args: argparse.Namespace, run_id: str) -> str:
    node = " ".join(
        [
            "python",
            "scripts/run_phase13b_jetson_node.py",
            "--run-id %s" % shlex.quote("%s-node" % run_id),
            "--bind-host 0.0.0.0",
            "--frame-port %d" % args.frame_port,
            "--control-port %d" % args.control_port,
            "--pc-host %s" % shlex.quote(args.pc_host or ""),
            "--command-port %d" % args.command_port,
            "--ack-port %d" % args.ack_port,
            "--perception-backend tensorrt",
            "--tensorrt-engine %s" % shlex.quote(args.fp16_engine),
            "--tensorrt-profile %s" % shlex.quote(args.profile),
            "--tensorrt-precision fp16",
            "--require-no-fallback",
            "--require-real-jetson",
            "--command-validity-ms %d" % args.command_validity_ms,
            # Phase 13E-R Goal 1: periodic discipline needs a live model, so the
            # node must not be able to sit on a stale one for the whole run.
            "--clock-resync-interval-sec %s" % args.clock_resync_interval_sec,
            "--clock-safety-margin-us %d" % args.clock_safety_margin_us,
            # Phase 13E-R Goal 2: the reader must keep draining the socket so
            # the depth-1 mailbox drops superseded frames instead of queueing.
            "--decoupled-consumer",
            # Phase 13E-R Goal 3: fixed metric memory for a multi-hour run.
            "--metrics-ring-capacity %d" % args.metrics_ring_capacity,
            "--control-timeout-sec %d" % args.control_timeout_sec,
            "--accept-timeout-sec %d" % args.accept_timeout_sec,
            "--output-dir experiments/phase13",
            "--pid-file %s" % pid_path(run_id),
        ]
    )
    return " && ".join(
        [
            "cd %s" % shlex.quote(args.jetson_repo),
            "source %s/bin/activate" % shlex.quote(args.jetson_venv),
            # setsid+nohup detaches the node from this SSH channel. Without it
            # the channel never closes and the orchestrator hangs here.
            "setsid nohup %s </dev/null > %s 2>&1 & disown"
            % (node, log_path(run_id)),
            "echo launch_requested",
        ]
    )


def wait_for_node(target: str, run_id: str, *, timeout_sec: float) -> Dict[str, Any]:
    """Poll the node log until it announces readiness, or give up."""

    deadline = time.time() + float(timeout_sec)
    tail = ""
    while time.time() < deadline:
        result = ssh(
            target,
            "test -f %(log)s && tail -c 4000 %(log)s || echo waiting_for_log"
            % {"log": log_path(run_id)},
            timeout=120,
        )
        tail = result["stdout"]
        if "phase13b_jetson_node_ready" in tail:
            pid = ssh(
                target,
                "cat %s 2>/dev/null || echo none" % pid_path(run_id),
                timeout=60,
            )["stdout"].strip()
            return {"node_ready": True, "node_pid": pid, "node_log_tail": tail.splitlines()[-10:]}
        if "Traceback" in tail:
            return {
                "node_ready": False,
                "node_pid": "",
                "node_log_tail": tail.splitlines()[-30:],
                "error": "node exited during start-up",
            }
        time.sleep(3)
    return {
        "node_ready": False,
        "node_pid": "",
        "node_log_tail": tail.splitlines()[-30:],
        "error": "node did not become ready within %ss" % timeout_sec,
    }


def stop_jetson_node(target: str, run_id: str) -> Dict[str, Any]:
    """Stop only the recorded PID. Never pkill, killall or pgrep -f."""

    pid_file = pid_path(run_id)
    remote = (
        'if [ -f %(pid)s ]; then PID=$(cat %(pid)s); '
        'if kill -0 "$PID" 2>/dev/null; then kill "$PID"; sleep 3; fi; '
        'if kill -0 "$PID" 2>/dev/null; then echo still_running=$PID; '
        'else echo stopped=$PID; fi; rm -f %(pid)s; else echo no_pid_file; fi'
        % {"pid": pid_file}
    )
    result = ssh(target, remote, timeout=180)
    return {
        "stop_returncode": result["returncode"],
        "stop_output": result["stdout"].strip(),
        "stopped_cleanly": "stopped=" in result["stdout"] or "no_pid_file" in result["stdout"],
    }


def soak_command(args: argparse.Namespace, run_id: str) -> List[str]:
    command = [
        sys.executable,
        str(SCRIPTS_DIR / "run_phase13e_soak.py"),
        "--run-id", run_id,
        "--phases", args.phases,
        "--jetson-user", args.jetson_user,
        "--jetson-host", args.jetson_host,
        "--jetson-repo", args.jetson_repo,
        "--jetson-venv", args.jetson_venv,
        "--fp16-engine", args.fp16_engine,
        "--frame-port", str(args.frame_port),
        "--control-port", str(args.control_port),
        "--command-port", str(args.command_port),
        "--ack-port", str(args.ack_port),
        "--carla-host", args.carla_host,
        "--carla-port", str(args.carla_port),
        "--town", args.town,
        "--burn-in-sec", str(args.burn_in_sec),
        "--soak-sec", str(args.soak_sec),
        "--min-soak-sec", str(args.min_soak_sec),
        "--command-validity-ms", str(args.command_validity_ms),
        "--clock-resync-interval-sec", str(args.clock_resync_interval_sec),
        "--backpressure-burst-fps", str(args.backpressure_burst_fps),
        "--backpressure-burst-sec", str(args.backpressure_burst_sec),
        "--output-dir", args.output_dir,
    ]
    if args.expected_engine_sha256:
        command += ["--expected-engine-sha256", args.expected_engine_sha256]
    if args.skip_phase13b_fault_matrix:
        command += ["--skip-phase13b-fault-matrix"]
    return command


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13E-R orchestrator")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--phases", default="preflight,burn_in,soak,backpressure,fault")
    parser.add_argument("--jetson-user", default=DEFAULT_JETSON_USER)
    parser.add_argument("--jetson-host", default=DEFAULT_JETSON_HOST)
    parser.add_argument("--jetson-repo", default=DEFAULT_JETSON_REPO)
    parser.add_argument("--jetson-venv", default=DEFAULT_JETSON_VENV)
    parser.add_argument("--fp16-engine", default=DEFAULT_FP16_ENGINE)
    parser.add_argument("--expected-engine-sha256", default="")
    parser.add_argument("--profile", default="config/phase13c_tensorrt_profile.json")
    parser.add_argument("--pc-host", default="192.168.55.100")
    parser.add_argument("--frame-port", type=int, default=48701)
    parser.add_argument("--control-port", type=int, default=48702)
    parser.add_argument("--command-port", type=int, default=48703)
    parser.add_argument("--ack-port", type=int, default=48704)
    parser.add_argument("--carla-host", default="127.0.0.1")
    parser.add_argument("--carla-port", type=int, default=2000)
    parser.add_argument("--town", default="Town03")
    parser.add_argument("--burn-in-sec", type=float, default=1800.0)
    parser.add_argument("--soak-sec", type=float, default=7200.0)
    parser.add_argument("--min-soak-sec", type=float, default=7200.0)
    parser.add_argument("--command-validity-ms", type=int, default=500)
    parser.add_argument("--clock-resync-interval-sec", type=float, default=15.0)
    parser.add_argument("--clock-safety-margin-us", type=int, default=1000)
    parser.add_argument("--metrics-ring-capacity", type=int, default=512)
    parser.add_argument("--backpressure-burst-fps", type=float, default=15.0)
    parser.add_argument("--backpressure-burst-sec", type=float, default=330.0)
    parser.add_argument("--control-timeout-sec", type=int, default=43200)
    parser.add_argument("--accept-timeout-sec", type=int, default=1800)
    parser.add_argument("--node-ready-timeout-sec", type=float, default=420.0)
    parser.add_argument("--output-dir", default="experiments/phase13")
    parser.add_argument("--skip-phase13b-fault-matrix", action="store_true")
    parser.add_argument("--allow-dirty-worktree", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    run_id = args.run_id or ("%s-13er" % new_run_id())
    target = "%s@%s" % (args.jetson_user, args.jetson_host)
    output_root = Path(args.output_dir)
    if not output_root.is_absolute():
        output_root = REPO_ROOT / output_root
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "phase": PHASE,
        "run_id": run_id,
        "created_at_utc": utc_now_iso(),
        "phases_requested": args.phases,
        "jetson_target": target,
        "one_continuous_process_set": True,
    }  # type: Dict[str, Any]

    guard = repository_guard(args.branch)
    summary["repository_guard"] = guard
    expected_sha = pc_git_sha()
    summary["runtime_pc_git_sha"] = expected_sha
    if not guard["guard_passed"] and not args.allow_dirty_worktree:
        summary["status"] = "Blocked"
        summary["blockers"] = ["repository_guard_failed"]
        (run_dir / "orchestrator_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print("%s Blocked: repository guard failed" % PHASE)
        print(json.dumps(guard, indent=2))
        return 1

    remote_sha = jetson_sha(target, args.jetson_repo)
    summary["runtime_jetson_git_sha"] = remote_sha
    summary["runtime_git_sha_match"] = bool(remote_sha) and remote_sha == expected_sha
    if not summary["runtime_git_sha_match"]:
        summary["status"] = "Blocked"
        summary["blockers"] = ["runtime_git_sha_mismatch"]
        (run_dir / "orchestrator_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print("%s Blocked: Jetson is at %s, PC is at %s" % (PHASE, remote_sha, expected_sha))
        return 1

    # Clear any stale PID file for this run id before starting, so the stop
    # step can never target a PID that belongs to something else.
    ssh(target, "rm -f %s" % pid_path(run_id), timeout=60)

    launch = ssh(target, jetson_node_command(args, run_id), timeout=300)
    summary["node_launch_returncode"] = launch["returncode"]
    summary["node_launch_requested"] = "launch_requested" in launch["stdout"]
    ready = wait_for_node(target, run_id, timeout_sec=args.node_ready_timeout_sec)
    summary.update(ready)

    soak_returncode = 1
    if ready.get("node_ready"):
        command = soak_command(args, run_id)
        summary["soak_command"] = " ".join(command)
        print("%s starting soak run_id=%s pid=%s" % (PHASE, run_id, ready.get("node_pid")))
        sys.stdout.flush()
        completed = subprocess.run(command, cwd=str(REPO_ROOT))
        soak_returncode = completed.returncode
    else:
        print("%s Blocked: Jetson node did not start" % PHASE)
        for line in ready.get("node_log_tail", []):
            print("  %s" % line)

    summary["soak_returncode"] = soak_returncode
    summary["node_stop"] = stop_jetson_node(target, run_id)
    summary["completed_at_utc"] = utc_now_iso()
    summary["status"] = "Completed" if soak_returncode == 0 else "Blocked"
    (run_dir / "orchestrator_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print("%s orchestrator %s" % (PHASE, summary["status"]))
    print("run_id=%s" % run_id)
    print("evidence_dir=%s" % run_dir)
    print("runtime_git_sha=%s" % expected_sha)
    print("node_pid=%s" % ready.get("node_pid"))
    print("node_stop=%s" % summary["node_stop"].get("stop_output"))
    return 0 if soak_returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
