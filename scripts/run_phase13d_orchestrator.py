"""Phase 13D orchestrator — plans and (optionally) executes Gates A..E in order.

Enforces the mandated execution order: local gates, then commit/push, then an
exact SHA match on the Jetson, then the calibration corpus, then the offline
activation proxy, then the target INT8 calibration and engine build, then the
FP16-vs-INT8 benchmark and parity, then the streamed INT8 runtime, and only
then the CARLA closed loop.

Safety rules: no password is stored, no SSH/firewall/ICS/nvpmodel/JetPack/kernel
setting is modified, no dependency is installed, and only the run-specific
Jetson PID started here is stopped (never ``pkill``).
"""

from __future__ import annotations

import argparse
import json
import shlex
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
    BOUNDARY_FIELDS,
    DEFAULT_COMMAND_VALIDITY_MS,
    DEFAULT_SAFETY_MARGIN_MS,
    PHASE,
    STATUS_BLOCKED,
    STATUS_DATASET_PASS,
    STATUS_ENGINE_PASS,
    STATUS_PASS,
    STATUS_PREPARED,
    STATUS_RUNTIME_PASS,
    Phase13DEvidence,
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
DEFAULT_JETSON_ASSETS = "/home/myjetsonnx/models/ma-vlna/yolov9"
DEFAULT_JETSON_DATASET = "/home/myjetsonnx/models/ma-vlna/int8_calibration"
DEFAULT_PC_DATASET = "D:\\AIModels\\yolov9\\int8_calibration"
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]


def ssh(target: str, remote: str, *, timeout: int = 1800) -> Dict[str, Any]:
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


def jetson_sync(target: str, repo: str, branch: str, expected_sha: str) -> Dict[str, Any]:
    remote = " && ".join(
        [
            "cd %s" % shlex.quote(repo),
            "git fetch origin",
            "git checkout %s" % shlex.quote(branch),
            "git pull --ff-only origin %s" % shlex.quote(branch),
            "git rev-parse HEAD",
        ]
    )
    result = ssh(target, remote)
    sha = ""
    for line in result["stdout"].splitlines():
        candidate = line.strip()
        if len(candidate) == 40 and all(char in "0123456789abcdef" for char in candidate):
            sha = candidate
    return {
        "jetson_sync_returncode": result["returncode"],
        "runtime_pc_git_sha": expected_sha,
        "runtime_jetson_git_sha": sha,
        "runtime_git_sha_match": bool(sha) and sha == expected_sha,
        "jetson_sync_stderr_tail": result["stderr"].strip().splitlines()[-8:],
    }


def jetson_node_command(args: argparse.Namespace, run_id: str) -> str:
    pid_file = "/tmp/ma-vlna-phase13d-%s.pid" % run_id
    log_file = "/tmp/ma-vlna-phase13d-%s.log" % run_id
    node = " ".join(
        [
            "python",
            "scripts/run_phase13b_jetson_node.py",
            "--run-id %s" % shlex.quote(run_id),
            "--bind-host 0.0.0.0",
            "--frame-port %d" % args.frame_port,
            "--control-port %d" % args.control_port,
            "--pc-host %s" % shlex.quote(args.pc_host or ""),
            "--command-port %d" % args.command_port,
            "--ack-port %d" % args.ack_port,
            "--perception-backend tensorrt",
            "--tensorrt-engine %s" % shlex.quote(args.int8_engine),
            "--tensorrt-profile %s" % shlex.quote(args.profile),
            "--tensorrt-precision int8",
            "--int8-calibration-envelope %s" % shlex.quote(args.jetson_envelope),
            "--int8-activation-proxy %s" % shlex.quote(args.jetson_activation_proxy),
            "--require-no-fallback",
            "--require-real-jetson",
            "--command-validity-ms %d" % args.command_validity_ms,
            "--output-dir experiments/phase13",
            "--pid-file %s" % pid_file,
        ]
    )
    return " && ".join(
        [
            "cd %s" % shlex.quote(args.jetson_repo),
            "source %s/bin/activate" % shlex.quote(args.jetson_venv),
            "setsid nohup %s </dev/null > %s 2>&1 & disown" % (node, log_file),
            "echo launch_requested",
        ]
    )


def stop_jetson_node(target: str, run_id: str) -> Dict[str, Any]:
    """Stop only the recorded PID. Never pkill/killall."""

    pid_file = "/tmp/ma-vlna-phase13d-%s.pid" % run_id
    remote = (
        'if [ -f %(pid)s ]; then PID=$(cat %(pid)s); '
        'if kill -0 "$PID" 2>/dev/null; then kill "$PID"; sleep 2; fi; '
        'if kill -0 "$PID" 2>/dev/null; then echo still_running=$PID; '
        'else echo stopped=$PID; fi; rm -f %(pid)s; else echo no_pid_file; fi'
        % {"pid": pid_file}
    )
    return ssh(target, remote, timeout=120)


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13D orchestrator")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--jetson-user", default=DEFAULT_JETSON_USER)
    parser.add_argument("--jetson-host", default=DEFAULT_JETSON_HOST)
    parser.add_argument("--jetson-repo", default=DEFAULT_JETSON_REPO)
    parser.add_argument("--jetson-venv", default=DEFAULT_JETSON_VENV)
    parser.add_argument("--jetson-asset-root", default=DEFAULT_JETSON_ASSETS)
    parser.add_argument("--jetson-dataset-root", default=DEFAULT_JETSON_DATASET)
    parser.add_argument("--pc-dataset-root", default=DEFAULT_PC_DATASET)
    parser.add_argument("--pc-host", default="")
    parser.add_argument("--onnx", default="%s/yolov9-c-640-b1.onnx" % DEFAULT_JETSON_ASSETS)
    parser.add_argument(
        "--fp16-engine", default="%s/yolov9-c-640-b1-trt852-fp16.engine" % DEFAULT_JETSON_ASSETS
    )
    parser.add_argument(
        "--int8-engine", default="%s/yolov9-c-640-b1-trt852-int8.engine" % DEFAULT_JETSON_ASSETS
    )
    parser.add_argument(
        "--jetson-dataset-manifest",
        default="%s/dataset_manifest.json" % DEFAULT_JETSON_DATASET,
    )
    parser.add_argument(
        "--jetson-envelope", default="%s/calibration_envelope.json" % DEFAULT_JETSON_DATASET
    )
    parser.add_argument(
        "--jetson-activation-proxy", default="%s/activation_proxy.json" % DEFAULT_JETSON_DATASET
    )
    parser.add_argument("--source-root", default="D:\\AIModels\\yolov9")
    parser.add_argument("--weights", default="D:\\AIModels\\yolov9\\yolov9-c-converted.pt")
    parser.add_argument("--profile", default="yolov9-c")
    parser.add_argument("--frame-port", type=int, default=13510)
    parser.add_argument("--control-port", type=int, default=13513)
    parser.add_argument("--command-port", type=int, default=13511)
    parser.add_argument("--ack-port", type=int, default=13512)
    parser.add_argument("--camera-fps", type=float, default=5.0)
    parser.add_argument("--frames", type=int, default=300)
    parser.add_argument("--routes", type=int, default=5)
    parser.add_argument("--frames-per-cell", type=int, default=40)
    parser.add_argument("--command-validity-ms", type=int, default=DEFAULT_COMMAND_VALIDITY_MS)
    parser.add_argument("--safety-margin-ms", type=int, default=DEFAULT_SAFETY_MARGIN_MS)
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--output-dir", default="experiments/phase13")
    parser.add_argument("--require-real-jetson", action="store_true")
    parser.add_argument("--require-carla", action="store_true")
    parser.add_argument("--require-no-fallback", action="store_true")
    parser.add_argument("--gate-a", action="store_true")
    parser.add_argument("--gate-b", action="store_true")
    parser.add_argument("--gate-c", action="store_true")
    parser.add_argument("--gate-d", action="store_true")
    parser.add_argument("--gate-e", action="store_true")
    parser.add_argument("--plan-only", action="store_true")
    return parser.parse_args(argv)


def build_plan(args: argparse.Namespace, run_id: str, target: str) -> Dict[str, Any]:
    python = args.python_executable
    return {
        "gate_a": "%s scripts/run_phase13d_checks.py --run-id %s" % (python, run_id),
        "gate_b_dataset": (
            "%s scripts/run_phase13d_dataset_build.py --run-id %s --mode all --output-root %s "
            "--routes %d --frames-per-cell %d --require-dataset"
            % (python, run_id, args.pc_dataset_root, args.routes, args.frames_per_cell)
        ),
        "gate_b_activation_proxy": (
            "%s scripts/run_phase13d_activation_proxy.py --run-id %s "
            "--dataset-manifest %s\\dataset_manifest.json --source-root %s --weights %s "
            "--output %s\\activation_proxy.json --require-proxy"
            % (python, run_id, args.pc_dataset_root, args.source_root, args.weights,
               args.pc_dataset_root)
        ),
        "dataset_transfer": (
            "ssh %s \"mkdir -p %s\" && scp -r %s\\* %s:%s/"
            % (target, args.jetson_dataset_root, args.pc_dataset_root, target,
               args.jetson_dataset_root)
        ),
        "gate_c_int8_build": (
            "ssh %s \"cd %s && source %s/bin/activate && python "
            "scripts/run_phase13d_int8_engine_build.py --onnx %s --engine %s "
            "--dataset-manifest %s --dataset-root-override %s --input-shape 1x3x640x640 "
            "--require-real-jetson --require-engine --require-int8-layers\""
            % (target, args.jetson_repo, args.jetson_venv, args.onnx, args.int8_engine,
               args.jetson_dataset_manifest, args.jetson_dataset_root)
        ),
        "gate_c_benchmark": (
            "ssh %s \"cd %s && source %s/bin/activate && python "
            "scripts/run_phase13d_precision_benchmark.py --fp16-engine %s --int8-engine %s "
            "--dataset-manifest %s --dataset-root-override %s --warmup 50 --iterations 300 "
            "--require-real-jetson --require-benchmark\""
            % (target, args.jetson_repo, args.jetson_venv, args.fp16_engine, args.int8_engine,
               args.jetson_dataset_manifest, args.jetson_dataset_root)
        ),
        "gate_c_parity": (
            "ssh %s \"cd %s && source %s/bin/activate && python "
            "scripts/run_phase13d_precision_parity.py --mode all --fp16-engine %s "
            "--int8-engine %s --dataset-manifest %s --dataset-root-override %s "
            "--frame-split holdout --require-parity\""
            % (target, args.jetson_repo, args.jetson_venv, args.fp16_engine, args.int8_engine,
               args.jetson_dataset_manifest, args.jetson_dataset_root)
        ),
        "jetson_node": jetson_node_command(args, run_id),
        "gate_d_streamed": (
            "%s scripts/run_phase13d_streamed_runtime.py --run-id %s --jetson-host %s "
            "--frames %d --require-real-jetson --require-no-fallback --require-parity"
            % (python, run_id, args.jetson_host, args.frames)
        ),
        "gate_e_carla": (
            "%s scripts/run_phase13d_carla_closed_loop.py --run-id %s --jetson-host %s "
            "--camera-fps %s --frames %d --command-validity-ms %d --safety-margin-ms %d "
            "--require-carla --require-real-jetson --require-no-fallback"
            % (python, run_id, args.jetson_host, args.camera_fps, args.frames,
               args.command_validity_ms, args.safety_margin_ms)
        ),
        "stop_jetson_node": "ssh %s <stop only the recorded PID>" % target,
    }


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    run_id = args.run_id or new_run_id()
    target = "%s@%s" % (args.jetson_user, args.jetson_host)
    python = args.python_executable

    plan = {
        "phase": PHASE,
        "run_id": run_id,
        "created_at_utc": utc_now_iso(),
        "jetson_target": target,
        "commands": build_plan(args, run_id, target),
    }  # type: Dict[str, Any]

    guard = repository_guard(args.branch)
    plan["repository_guard"] = guard

    if args.plan_only:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0 if guard["guard_passed"] else 1

    evidence = Phase13DEvidence(Path(args.output_dir), "%s-orchestrator" % run_id)
    summary = dict(plan)
    summary["gates"] = {}
    status = STATUS_BLOCKED

    if not guard["guard_passed"]:
        summary["status"] = STATUS_BLOCKED
        summary["blocker"] = "repository_guard_failed"
        evidence.write_json("summary.json", summary)
        print(STATUS_BLOCKED)
        print("blocker=repository_guard_failed")
        return 1

    runtime_pc_sha = pc_git_sha()
    summary["runtime_pc_git_sha"] = runtime_pc_sha

    if args.gate_a:
        gate = run_command(
            [python, str(SCRIPTS_DIR / "run_phase13d_checks.py"), "--run-id", run_id,
             "--output-dir", args.output_dir],
            timeout=5400,
        )
        gate["passed"] = gate["returncode"] == 0
        summary["gates"]["A"] = gate
        if not gate["passed"]:
            summary["status"] = STATUS_BLOCKED
            summary["blocker"] = "gate_a_failed"
            evidence.write_json("summary.json", summary)
            print(STATUS_BLOCKED)
            print("blocker=gate_a_failed")
            return 1
        status = STATUS_PREPARED

    if args.gate_b:
        dataset = run_command(
            [
                python, str(SCRIPTS_DIR / "run_phase13d_dataset_build.py"),
                "--run-id", run_id, "--mode", "all", "--output-root", args.pc_dataset_root,
                "--routes", str(args.routes), "--frames-per-cell", str(args.frames_per_cell),
                "--output-dir", args.output_dir, "--require-dataset",
            ],
            timeout=7200,
        )
        summary["gates"]["B_dataset"] = {
            "returncode": dataset["returncode"],
            "stdout_tail": dataset["stdout"].strip().splitlines()[-20:],
            "passed": dataset["returncode"] == 0,
        }
        proxy = run_command(
            [
                python, str(SCRIPTS_DIR / "run_phase13d_activation_proxy.py"),
                "--run-id", run_id,
                "--dataset-manifest", str(Path(args.pc_dataset_root) / "dataset_manifest.json"),
                "--source-root", args.source_root, "--weights", args.weights,
                "--output", str(Path(args.pc_dataset_root) / "activation_proxy.json"),
                "--output-dir", args.output_dir, "--require-proxy",
            ],
            timeout=7200,
        ) if dataset["returncode"] == 0 else {"returncode": 1, "stdout": "", "stderr": "dataset failed"}
        summary["gates"]["B_activation_proxy"] = {
            "returncode": proxy["returncode"],
            "stdout_tail": proxy["stdout"].strip().splitlines()[-20:],
            "passed": proxy["returncode"] == 0,
        }
        if dataset["returncode"] == 0 and proxy["returncode"] == 0:
            status = STATUS_DATASET_PASS
        else:
            summary["blocker"] = "gate_b_failed"

    node_started = False
    if (args.gate_c or args.gate_d or args.gate_e) and summary.get("blocker") is None:
        probe = ssh(target, "whoami; uname -m")
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

    try:
        if args.gate_c and summary.get("blocker") is None:
            build = ssh(target, plan["commands"]["gate_c_int8_build"], timeout=14400)
            bench = (
                ssh(target, plan["commands"]["gate_c_benchmark"], timeout=5400)
                if build["returncode"] == 0
                else {"returncode": 1, "stdout": "", "stderr": "int8 engine build failed"}
            )
            parity = (
                ssh(target, plan["commands"]["gate_c_parity"], timeout=5400)
                if bench["returncode"] == 0
                else {"returncode": 1, "stdout": "", "stderr": "benchmark failed"}
            )
            summary["gates"]["C"] = {
                "engine_build_returncode": build["returncode"],
                "engine_build_stdout_tail": build["stdout"].strip().splitlines()[-25:],
                "benchmark_returncode": bench["returncode"],
                "benchmark_stdout_tail": bench["stdout"].strip().splitlines()[-25:],
                "parity_returncode": parity["returncode"],
                "parity_stdout_tail": parity["stdout"].strip().splitlines()[-25:],
                "passed": build["returncode"] == 0
                and bench["returncode"] == 0
                and parity["returncode"] == 0,
            }
            if summary["gates"]["C"]["passed"]:
                status = STATUS_ENGINE_PASS
            else:
                summary["blocker"] = "gate_c_failed"

        if (args.gate_d or args.gate_e) and summary.get("blocker") is None:
            start = ssh(target, jetson_node_command(args, run_id), timeout=900)
            node_started = start["returncode"] == 0
            summary["jetson_node_start"] = {
                "returncode": start["returncode"],
                "pid_file": "/tmp/ma-vlna-phase13d-%s.pid" % run_id,
                "log_file": "/tmp/ma-vlna-phase13d-%s.log" % run_id,
            }
            time.sleep(15)

        if args.gate_d and summary.get("blocker") is None:
            gate_d = run_command(
                [
                    python, str(SCRIPTS_DIR / "run_phase13d_streamed_runtime.py"),
                    "--run-id", run_id, "--jetson-host", args.jetson_host,
                    "--frames", str(args.frames), "--output-dir", args.output_dir,
                ]
                + (["--require-real-jetson"] if args.require_real_jetson else [])
                + (["--require-no-fallback"] if args.require_no_fallback else []),
                timeout=5400,
            )
            gate_d["passed"] = gate_d["returncode"] == 0
            summary["gates"]["D"] = gate_d
            if gate_d["passed"]:
                status = STATUS_RUNTIME_PASS
            else:
                summary["blocker"] = "gate_d_failed"

        if args.gate_e and summary.get("blocker") is None:
            gate_e = run_command(
                [
                    python, str(SCRIPTS_DIR / "run_phase13d_carla_closed_loop.py"),
                    "--run-id", run_id, "--jetson-host", args.jetson_host,
                    "--camera-fps", str(args.camera_fps), "--frames", str(args.frames),
                    "--command-validity-ms", str(args.command_validity_ms),
                    "--safety-margin-ms", str(args.safety_margin_ms),
                    "--output-dir", args.output_dir,
                ]
                + (["--require-carla"] if args.require_carla else [])
                + (["--require-real-jetson"] if args.require_real_jetson else [])
                + (["--require-no-fallback"] if args.require_no_fallback else []),
                timeout=7200,
            )
            gate_e["passed"] = gate_e["returncode"] == 0
            summary["gates"]["E"] = gate_e
            if gate_e["passed"]:
                status = STATUS_PASS
            else:
                summary["blocker"] = "gate_e_failed"
    finally:
        if node_started:
            summary["jetson_node_stop"] = stop_jetson_node(target, run_id)

    summary["status"] = status
    summary.update(BOUNDARY_FIELDS)
    evidence.write_json("summary.json", summary)
    evidence.write_text(
        "commands.txt",
        "# Phase 13D orchestrator\n%s %s\n\n%s\n"
        % (
            sys.executable,
            " ".join(sys.argv),
            "\n\n".join("%s:\n%s" % (key, value) for key, value in plan["commands"].items()),
        ),
    )
    print(status)
    print("run_id=%s" % run_id)
    print("evidence_dir=%s" % evidence.run_dir)
    for gate, payload in sorted(summary["gates"].items()):
        print("gate_%s_passed=%s" % (gate.lower(), payload.get("passed")))
    if summary.get("blocker"):
        print("blocker=%s" % summary["blocker"])
    return 0 if status != STATUS_BLOCKED else 1


if __name__ == "__main__":
    raise SystemExit(main())
