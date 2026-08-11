"""Phase 13B orchestrator — plans and (optionally) executes Gate A/B/C in order.

Responsibilities:

  1. re-check the repository/session guard before any runtime;
  2. detect the actual PC source address for the route to the Jetson;
  3. verify non-interactive SSH and the exact PC/Jetson runtime git SHA match;
  4. start the Jetson node with a run-specific PID/log path under ``/tmp``;
  5. run Gate A, then Gate B, then Gate C, stopping at the first failure;
  6. stop **only** the recorded Jetson PID and aggregate the evidence.

Safety rules enforced here: no password is ever stored or requested, no SSH,
firewall, ICS, nvpmodel, JetPack or kernel setting is modified, no Jetson
dependency is installed, and no broad process kill (``pkill python``) is used.
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

from run_phase13b_jil_checks import (  # noqa: E402
    PHASE,
    STATUS_BLOCKED,
    STATUS_PASS,
    STATUS_PREPARED,
    STATUS_TRANSPORT_PASS,
    EvidenceWriter,
    detect_pc_source_address,
    new_run_id,
    pc_git_sha,
    run_command,
    utc_now_iso,
)

DEFAULT_BRANCH = "codex/phase-11o-source-commit-boundary"
DEFAULT_JETSON_USER = "myjetsonnx"
DEFAULT_JETSON_HOST = "192.168.55.1"
DEFAULT_JETSON_REPO = "/home/myjetsonnx/Face_Detect_Realtime"
DEFAULT_JETSON_VENV = "/home/myjetsonnx/venvs/ma-vlna"
SSH_BATCH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]


def ssh(target: str, remote_command: str, *, timeout: int = 900) -> Dict[str, Any]:
    """Run a non-interactive remote command. Never prompts, never stores secrets."""

    return run_command(["ssh"] + SSH_BATCH_OPTS + [target, remote_command], timeout=timeout)


def repository_guard(branch: str) -> Dict[str, Any]:
    """Re-check branch, worktree, cleanliness and local/remote HEAD equality."""

    status = run_command(["git", "status", "--short"], timeout=60)
    current = run_command(["git", "branch", "--show-current"], timeout=60)
    head = run_command(["git", "rev-parse", "HEAD"], timeout=60)
    worktrees = run_command(["git", "worktree", "list"], timeout=60)
    remote = run_command(["git", "rev-parse", "origin/%s" % branch], timeout=60)
    payload = {
        "branch": current["stdout"].strip(),
        "branch_expected": branch,
        "head_sha": head["stdout"].strip(),
        "origin_head_sha": remote["stdout"].strip(),
        "worktree_clean": not status["stdout"].strip(),
        "worktree_list": worktrees["stdout"].strip().splitlines(),
        "status_short": status["stdout"].strip().splitlines(),
    }
    payload["local_matches_remote"] = bool(payload["head_sha"]) and (
        payload["head_sha"] == payload["origin_head_sha"]
    )
    payload["guard_passed"] = (
        payload["branch"] == branch
        and payload["worktree_clean"]
        and payload["local_matches_remote"]
        and len(payload["worktree_list"]) == 1
    )
    return payload


def jetson_sync(target: str, repo: str, branch: str, expected_sha: str) -> Dict[str, Any]:
    """Fetch and fast-forward the Jetson checkout to the exact committed SHA."""

    remote = " && ".join(
        [
            "cd %s" % shlex.quote(repo),
            "git fetch origin",
            "git checkout %s" % shlex.quote(branch),
            "git pull --ff-only origin %s" % shlex.quote(branch),
            "git rev-parse HEAD",
            "git status --short",
        ]
    )
    result = ssh(target, remote)
    lines = [line.strip() for line in result["stdout"].splitlines() if line.strip()]
    sha = ""
    for line in lines:
        if len(line) == 40 and all(char in "0123456789abcdef" for char in line):
            sha = line
    payload = {
        "jetson_sync_returncode": result["returncode"],
        "runtime_jetson_git_sha": sha,
        "runtime_pc_git_sha": expected_sha,
        "runtime_git_sha_match": bool(sha) and sha == expected_sha,
        "jetson_sync_stdout_tail": result["stdout"].strip().splitlines()[-10:],
        "jetson_sync_stderr_tail": result["stderr"].strip().splitlines()[-10:],
    }
    return payload


def jetson_node_command(args: argparse.Namespace, run_id: str) -> str:
    """Exact remote command that starts the Jetson node (recorded in evidence)."""

    pid_file = "/tmp/ma-vlna-phase13b-%s.pid" % run_id
    log_file = "/tmp/ma-vlna-phase13b-%s.log" % run_id
    node = " ".join(
        [
            "python",
            "scripts/run_phase13b_jetson_node.py",
            "--run-id %s" % shlex.quote(run_id),
            "--bind-host 0.0.0.0",
            "--frame-port %d" % args.frame_port,
            "--control-port %d" % args.control_port,
            "--pc-host %s" % shlex.quote(args.pc_host),
            "--command-port %d" % args.command_port,
            "--ack-port %d" % args.ack_port,
            "--output-dir experiments/phase13",
            "--pid-file %s" % pid_file,
        ]
        + (["--require-real-jetson"] if args.require_real_jetson else [])
        + (["--run-phase13a-preflight"] if args.run_phase13a_preflight else [])
        + (["--run-arm64-c-gate"] if args.run_arm64_c_gate else [])
    )
    return " && ".join(
        [
            "cd %s" % shlex.quote(args.jetson_repo),
            "source %s/bin/activate" % shlex.quote(args.jetson_venv),
            "nohup %s > %s 2>&1 &" % (node, log_file),
            "echo started_pid=$!",
        ]
    )


def stop_jetson_node(target: str, run_id: str) -> Dict[str, Any]:
    """Stop only the recorded PID. Never uses pkill/killall."""

    pid_file = "/tmp/ma-vlna-phase13b-%s.pid" % run_id
    remote = (
        'if [ -f %(pid)s ]; then PID=$(cat %(pid)s); '
        'if kill -0 "$PID" 2>/dev/null; then kill "$PID"; sleep 2; fi; '
        'if kill -0 "$PID" 2>/dev/null; then echo still_running=$PID; '
        'else echo stopped=$PID; fi; rm -f %(pid)s; '
        "else echo no_pid_file; fi" % {"pid": pid_file}
    )
    return ssh(target, remote, timeout=120)


def run_gate(script: str, arguments: List[str], *, python_executable: str) -> Dict[str, Any]:
    command = [python_executable, str(SCRIPTS_DIR / script)] + arguments
    result = run_command(command, timeout=3600)
    return {
        "command": command,
        "returncode": result["returncode"],
        "stdout_tail": result["stdout"].strip().splitlines()[-25:],
        "stderr_tail": result["stderr"].strip().splitlines()[-15:],
        "passed": result["returncode"] == 0,
    }


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13B gate orchestrator")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--jetson-user", default=DEFAULT_JETSON_USER)
    parser.add_argument("--jetson-host", default=DEFAULT_JETSON_HOST)
    parser.add_argument("--jetson-repo", default=DEFAULT_JETSON_REPO)
    parser.add_argument("--jetson-venv", default=DEFAULT_JETSON_VENV)
    parser.add_argument("--pc-host", default="")
    parser.add_argument("--frame-port", type=int, default=13510)
    parser.add_argument("--control-port", type=int, default=13513)
    parser.add_argument("--command-port", type=int, default=13511)
    parser.add_argument("--ack-port", type=int, default=13512)
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--synthetic-frames", type=int, default=300)
    parser.add_argument("--command-ack-cycles", type=int, default=1000)
    parser.add_argument("--carla-frames", type=int, default=300)
    parser.add_argument("--output-dir", default="experiments/phase13")
    parser.add_argument("--transport-medium", default="usb_gadget_ethernet")
    parser.add_argument("--require-real-jetson", action="store_true")
    parser.add_argument("--run-phase13a-preflight", action="store_true")
    parser.add_argument("--run-arm64-c-gate", action="store_true")
    parser.add_argument("--gate-a", action="store_true", help="run Gate A")
    parser.add_argument("--gate-b", action="store_true", help="run Gate B")
    parser.add_argument("--gate-c", action="store_true", help="run Gate C")
    parser.add_argument("--plan-only", action="store_true", help="print the plan, execute nothing")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    run_id = args.run_id or new_run_id()
    target = "%s@%s" % (args.jetson_user, args.jetson_host)
    address = detect_pc_source_address(args.jetson_host, port=args.control_port)
    if not args.pc_host:
        args.pc_host = address.get("pc_source_address_detected") or ""

    plan = {
        "phase": PHASE,
        "run_id": run_id,
        "created_at_utc": utc_now_iso(),
        "jetson_target": target,
        "pc_source_address": address,
        "transport_medium": args.transport_medium,
        "commands": {
            "gate_a": "%s scripts/run_phase13b_loopback_checks.py --run-id %s-gatea"
            % (args.python_executable, run_id),
            "jetson_node": jetson_node_command(args, run_id),
            "gate_b": (
                "%s scripts/run_phase13b_jil_checks.py --run-id %s --jetson-host %s "
                "--synthetic-frames %d --command-ack-cycles %d --require-real-jetson"
                % (
                    args.python_executable,
                    run_id,
                    args.jetson_host,
                    args.synthetic_frames,
                    args.command_ack_cycles,
                )
            ),
            "gate_c": (
                "%s scripts/run_phase13b_simulation_host.py --run-id %s --jetson-host %s "
                "--mode lockstep --frames %d --require-server --require-jetson"
                % (args.python_executable, run_id, args.jetson_host, args.carla_frames)
            ),
            "stop_jetson_node": "ssh %s <stop only the recorded PID>" % target,
        },
    }  # type: Dict[str, Any]

    guard = repository_guard(args.branch)
    plan["repository_guard"] = guard

    if args.plan_only:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0 if guard["guard_passed"] else 1

    evidence = EvidenceWriter(Path(args.output_dir), "%s-orchestrator" % run_id)
    summary = dict(plan)
    summary["gates"] = {}
    status = STATUS_BLOCKED

    if not guard["guard_passed"]:
        summary["status"] = STATUS_BLOCKED
        summary["blocker"] = "repository_guard_failed"
        evidence.write_json("summary.json", summary)
        print(STATUS_BLOCKED)
        print("blocker=repository_guard_failed")
        print(json.dumps(guard, ensure_ascii=False, indent=2))
        return 1

    runtime_pc_sha = pc_git_sha()
    summary["runtime_pc_git_sha"] = runtime_pc_sha

    if args.gate_a:
        summary["gates"]["A"] = run_gate(
            "run_phase13b_loopback_checks.py",
            ["--run-id", "%s-gatea" % run_id, "--output-dir", args.output_dir],
            python_executable=args.python_executable,
        )
        if not summary["gates"]["A"]["passed"]:
            summary["status"] = STATUS_BLOCKED
            summary["blocker"] = "gate_a_failed"
            evidence.write_json("summary.json", summary)
            print(STATUS_BLOCKED)
            print("blocker=gate_a_failed")
            return 1
        status = STATUS_PREPARED

    node_started = False
    if args.gate_b or args.gate_c:
        probe = ssh(target, "whoami; hostname; uname -m")
        summary["jetson_ssh"] = {
            "returncode": probe["returncode"],
            "stdout": probe["stdout"].strip().splitlines(),
        }
        if probe["returncode"] != 0:
            summary["status"] = STATUS_BLOCKED
            summary["blocker"] = "ssh_noninteractive_unavailable"
            evidence.write_json("summary.json", summary)
            print(STATUS_BLOCKED)
            print("blocker=ssh_noninteractive_unavailable")
            return 1

        sync = jetson_sync(target, args.jetson_repo, args.branch, runtime_pc_sha)
        summary["jetson_sync"] = sync
        if not sync["runtime_git_sha_match"]:
            summary["status"] = STATUS_BLOCKED
            summary["blocker"] = "git_sha_mismatch"
            evidence.write_json("summary.json", summary)
            print(STATUS_BLOCKED)
            print("blocker=git_sha_mismatch")
            return 1

        start = ssh(target, jetson_node_command(args, run_id), timeout=1800)
        summary["jetson_node_start"] = {
            "returncode": start["returncode"],
            "stdout": start["stdout"].strip().splitlines(),
            "pid_file": "/tmp/ma-vlna-phase13b-%s.pid" % run_id,
            "log_file": "/tmp/ma-vlna-phase13b-%s.log" % run_id,
        }
        node_started = start["returncode"] == 0
        time.sleep(5)

    try:
        if args.gate_b:
            summary["gates"]["B"] = run_gate(
                "run_phase13b_jil_checks.py",
                [
                    "--run-id",
                    run_id,
                    "--jetson-host",
                    args.jetson_host,
                    "--synthetic-frames",
                    str(args.synthetic_frames),
                    "--command-ack-cycles",
                    str(args.command_ack_cycles),
                    "--require-real-jetson",
                    "--output-dir",
                    args.output_dir,
                    "--transport-medium",
                    args.transport_medium,
                ],
                python_executable=args.python_executable,
            )
            if summary["gates"]["B"]["passed"]:
                status = STATUS_TRANSPORT_PASS
            else:
                summary["blocker"] = "gate_b_failed"

        if args.gate_c and summary.get("blocker") is None:
            summary["gates"]["C"] = run_gate(
                "run_phase13b_simulation_host.py",
                [
                    "--run-id",
                    "%s-gatec" % run_id,
                    "--jetson-host",
                    args.jetson_host,
                    "--mode",
                    "lockstep",
                    "--frames",
                    str(args.carla_frames),
                    "--require-server",
                    "--require-jetson",
                    "--output-dir",
                    args.output_dir,
                    "--transport-medium",
                    args.transport_medium,
                ],
                python_executable=args.python_executable,
            )
            if summary["gates"]["C"]["passed"]:
                status = STATUS_PASS
            else:
                summary["blocker"] = "gate_c_failed"
    finally:
        if node_started:
            summary["jetson_node_stop"] = stop_jetson_node(target, run_id)

    summary["status"] = status
    evidence.write_json("summary.json", summary)
    evidence.write_text(
        "commands.txt",
        "# Phase 13B orchestrator\n%s %s\n\n%s\n"
        % (
            sys.executable,
            " ".join(sys.argv),
            "\n".join("%s: %s" % (key, value) for key, value in plan["commands"].items()),
        ),
    )
    print(status)
    print("run_id=%s" % run_id)
    print("evidence_dir=%s" % evidence.run_dir)
    for gate, payload in sorted(summary["gates"].items()):
        print("gate_%s_passed=%s" % (gate.lower(), payload["passed"]))
    if summary.get("blocker"):
        print("blocker=%s" % summary["blocker"])
    return 0 if status in (STATUS_PASS, STATUS_TRANSPORT_PASS, STATUS_PREPARED) else 1


if __name__ == "__main__":
    raise SystemExit(main())
