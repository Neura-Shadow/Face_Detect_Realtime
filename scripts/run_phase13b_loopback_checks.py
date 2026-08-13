"""Phase 13B Gate A — local loopback checks (no CARLA, no real Jetson).

Gate A exercises the *production* Phase 13B code paths on one machine:

  * protocol / mailbox / clock / C-FFI unit tests;
  * the portable C shared library built and loaded through ctypes;
  * a real ``run_phase13b_jetson_node.py`` process acting as the PC-local
    Jetson-node substitute, reached over the same TCP and UDP transports;
  * the same fixed buffer pool, depth-1 mailbox, clock sync, ACK protocol,
    reconnect handling and deterministic fault matrix.

Gate A alone permits only the ``Prepared`` status. It never claims real Jetson
transport or CARLA closed-loop execution.
"""

from __future__ import annotations

import argparse
import json
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

from run_phase13b_jil_checks import (  # noqa: E402  (path bootstrap above)
    BOUNDARY_FIELDS,
    PHASE,
    STATUS_BLOCKED,
    STATUS_PREPARED,
    EvidenceWriter,
    JilSessionDriver,
    new_run_id,
    pc_environment,
    run_command,
    utc_now_iso,
)
from simulation.virtual_safety_mcu_server import (  # noqa: E402
    build_safety_mcu_library,
    find_safety_mcu_library,
)

DEFAULT_LOOPBACK_HOST = "127.0.0.1"
DEFAULT_FRAME_PORT = 13610
DEFAULT_COMMAND_PORT = 13611
DEFAULT_ACK_PORT = 13612
DEFAULT_CONTROL_PORT = 13613
UNIT_TEST_MODULES = (
    "scripts/tests/test_phase13b_protocols.py",
    "scripts/tests/test_phase13b_mailbox.py",
    "scripts/tests/test_phase13b_clock_sync.py",
    "scripts/tests/test_phase13b_virtual_mcu_ffi.py",
)


def run_unit_tests() -> Dict[str, Any]:
    """Run the Phase 13B unit suites through unittest discovery."""

    result = run_command(
        [
            sys.executable,
            "-m",
            "unittest",
            "discover",
            "-s",
            "scripts/tests",
            "-p",
            "test_phase13b_*.py",
            "-v",
        ],
        timeout=900,
    )
    output = (result["stdout"] + "\n" + result["stderr"]).strip()
    return {
        "unit_tests_passed": result["returncode"] == 0,
        "unit_tests_returncode": result["returncode"],
        "unit_tests_output_tail": output.splitlines()[-25:],
    }


def build_c_targets() -> Dict[str, Any]:
    """Build the C targets and run CTest so Gate A covers the FFI library."""

    import shutil
    import tempfile

    cmake = shutil.which("cmake")
    ctest = shutil.which("ctest")
    if cmake is None or ctest is None:
        return {"c_ffi_tests_passed": False, "error": "cmake/ctest unavailable"}

    build_dir = Path(tempfile.mkdtemp(prefix="ma-vlna-phase13b-gatea-"))
    configure_cmd = [cmake, "-S", str(REPO_ROOT / "embedded"), "-B", str(build_dir)]
    generator_args = []  # type: List[str]
    if shutil.which("mingw32-make") and sys.platform.startswith("win"):
        generator_args = ["-G", "MinGW Makefiles"]
        gcc = shutil.which("gcc")
        if gcc:
            generator_args.append("-DCMAKE_C_COMPILER=%s" % gcc)
    configure = run_command(configure_cmd + generator_args)
    build = run_command([cmake, "--build", str(build_dir)])
    # CMake 3.16 compatible invocation: run ctest from inside the build tree.
    tests = run_command([ctest, "--output-on-failure"], cwd=build_dir)
    passed = all(item["returncode"] == 0 for item in (configure, build, tests))
    return {
        "c_ffi_tests_passed": passed,
        "c_build_dir": str(build_dir),
        "c_configure_returncode": configure["returncode"],
        "c_build_returncode": build["returncode"],
        "c_ctest_returncode": tests["returncode"],
        "c_ctest_output_tail": tests["stdout"].strip().splitlines()[-15:],
    }


def start_local_node(args: argparse.Namespace, run_id: str, log_path: Path) -> subprocess.Popen:
    """Start the real Jetson node script as the PC-local substitute process."""

    command = [
        sys.executable,
        str(SCRIPTS_DIR / "run_phase13b_jetson_node.py"),
        "--run-id",
        "%s-node" % run_id,
        "--bind-host",
        args.bind_host,
        "--frame-port",
        str(args.frame_port),
        "--control-port",
        str(args.control_port),
        "--pc-host",
        args.loopback_host,
        "--command-port",
        str(args.command_port),
        "--ack-port",
        str(args.ack_port),
        "--output-dir",
        args.output_dir,
        "--diagnostic-throttle",
        str(args.diagnostic_throttle),
        "--command-validity-ms",
        str(args.command_validity_ms),
        "--ack-timeout-ms",
        str(args.ack_timeout_ms),
        "--frame-accept-poll-sec",
        "1.0",
    ]
    if getattr(args, "decoupled_consumer", False):
        command.append("--decoupled-consumer")
    if getattr(args, "metrics_ring_capacity", None):
        command += ["--metrics-ring-capacity", str(args.metrics_ring_capacity)]
    handle = open(str(log_path), "w", encoding="utf-8")
    return subprocess.Popen(
        command,
        cwd=str(REPO_ROOT),
        stdout=handle,
        stderr=subprocess.STDOUT,
        universal_newlines=True,
    )


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13B Gate A local loopback checks")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--loopback-host", default=DEFAULT_LOOPBACK_HOST)
    parser.add_argument("--bind-host", default=DEFAULT_LOOPBACK_HOST)
    parser.add_argument("--frame-port", type=int, default=DEFAULT_FRAME_PORT)
    parser.add_argument("--control-port", type=int, default=DEFAULT_CONTROL_PORT)
    parser.add_argument("--command-port", type=int, default=DEFAULT_COMMAND_PORT)
    parser.add_argument("--ack-port", type=int, default=DEFAULT_ACK_PORT)
    parser.add_argument("--frames", type=int, default=60)
    parser.add_argument("--command-ack-cycles", type=int, default=200)
    parser.add_argument("--camera-width", type=int, default=320)
    parser.add_argument("--camera-height", type=int, default=180)
    parser.add_argument("--clock-samples", type=int, default=40)
    parser.add_argument("--heartbeat-timeout-ms", type=int, default=3000)
    parser.add_argument("--command-validity-ms", type=int, default=500)
    parser.add_argument("--diagnostic-throttle", type=float, default=0.20)
    parser.add_argument("--ack-timeout-ms", type=int, default=500)
    parser.add_argument("--mcu-library", default="")
    parser.add_argument("--output-dir", default="experiments/phase13")
    parser.add_argument("--node-start-timeout-sec", type=float, default=90.0)
    parser.add_argument(
        "--decoupled-consumer", action="store_true",
        help="Phase 13E-R Goal 2: run the node pipeline on its own thread.",
    )
    parser.add_argument("--metrics-ring-capacity", type=int, default=0)
    parser.add_argument("--skip-unit-tests", action="store_true")
    parser.add_argument("--skip-c-build", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    run_id = args.run_id or ("%s-gatea" % new_run_id())
    evidence = EvidenceWriter(Path(args.output_dir), run_id)
    environment = pc_environment(argparse.Namespace(transport_medium="loopback"))

    summary = {
        "phase": PHASE,
        "gate": "A",
        "run_id": run_id,
        "created_at_utc": utc_now_iso(),
        "transport_medium": "loopback",
        "gate_a_source_implementation_ready": True,
    }  # type: Dict[str, Any]

    if not args.skip_unit_tests:
        unit = run_unit_tests()
    else:
        unit = {"unit_tests_passed": False, "skipped": True}
    summary.update(unit)
    summary["gate_a_protocol_tests_passed"] = bool(unit.get("unit_tests_passed"))
    summary["gate_a_mailbox_tests_passed"] = bool(unit.get("unit_tests_passed"))
    summary["gate_a_clock_tests_passed"] = bool(unit.get("unit_tests_passed"))

    if not args.skip_c_build:
        c_report = build_c_targets()
    else:
        c_report = {"c_ffi_tests_passed": False, "skipped": True}
    summary.update(c_report)
    summary["gate_a_c_ffi_tests_passed"] = bool(c_report.get("c_ffi_tests_passed"))

    library = find_safety_mcu_library(args.mcu_library or None)
    if library is None and not args.mcu_library:
        summary["mcu_library_build"] = build_safety_mcu_library()
        library = find_safety_mcu_library(None)
    summary["mcu_library_path"] = str(library) if library else None

    log_path = evidence.run_dir / "raw_outputs" / "loopback_node.log"
    node = start_local_node(args, run_id, log_path)
    driver = JilSessionDriver(
        run_id=run_id,
        jetson_host=args.loopback_host,
        frame_port=args.frame_port,
        control_port=args.control_port,
        command_port=args.command_port,
        ack_port=args.ack_port,
        pc_bind_host=args.loopback_host,
        mcu_library_path=args.mcu_library or (str(library) if library else None),
        heartbeat_timeout_ms=args.heartbeat_timeout_ms,
        command_validity_ms=args.command_validity_ms,
        clock_samples=args.clock_samples,
        camera_width=args.camera_width,
        camera_height=args.camera_height,
        pin_source_host=True,
        auto_build_mcu_library=False,
    )

    loopback_passed = False
    jetson_evidence = {"metrics": {}, "events": []}  # type: Dict[str, Any]
    try:
        mcu = driver.start_virtual_mcu()
        summary["virtual_mcu"] = mcu
        if not mcu.get("ok"):
            raise RuntimeError("virtual safety MCU could not start")

        deadline = time.time() + float(args.node_start_timeout_sec)
        connected = False
        while time.time() < deadline and not connected:
            if node.poll() is not None:
                raise RuntimeError("loopback node exited early with code %s" % node.returncode)
            try:
                driver.connect_control(connect_timeout_sec=3.0)
                connected = True
            except OSError:
                time.sleep(0.5)
        if not connected:
            raise RuntimeError("loopback node control channel never became reachable")

        summary["clock"] = driver.synchronise_clocks()
        driver.start_session(start_frame_server=True)
        if not driver.connect_frames():
            raise RuntimeError("loopback frame transport could not be established")

        summary["frames"] = driver.publish_synthetic_frames(int(args.frames), wait_timeout_sec=90.0)
        summary["command_ack_stress"] = driver.command_ack_stress(int(args.command_ack_cycles))
        summary["fault_matrix"] = driver.run_fault_matrix("A")

        jetson_evidence = driver.collect_jetson_evidence()
        node_metrics = jetson_evidence["metrics"]
        # A frame is retired when it has been processed or deliberately
        # superseded in the depth-1 mailbox. Requiring processed >= sent assumes
        # the reader and the pipeline run in lock step, which stops being true
        # as soon as latest-frame-only actually drops anything.
        retired = int(node_metrics.get("frames_processed", 0)) + int(
            node_metrics.get("frames_dropped_mailbox", 0)
        )
        loopback_passed = (
            retired >= int(args.frames)
            and int(node_metrics.get("max_mailbox_depth", 0)) == 1
            and int(node_metrics.get("valid_acks_received", 0)) > 0
            and bool(summary["fault_matrix"].get("fault_matrix_passed"))
            and int(summary["fault_matrix"].get("false_accept_count", 0)) == 0
            and int(summary["fault_matrix"].get("false_reject_count", 0)) == 0
            and int(driver.server.command_accept_count if driver.server else 0) > 0
            and not bool(node_metrics.get("buffer_leak_detected", False))
        )
    except Exception as exc:
        summary["error"] = repr(exc)
        driver.emit("gate_a_error", error=repr(exc))
    finally:
        pc_metrics_payload = driver.pc_metrics()
        driver.shutdown()
        try:
            node.wait(timeout=30)
        except subprocess.TimeoutExpired:
            node.terminate()
            try:
                node.wait(timeout=10)
            except subprocess.TimeoutExpired:
                node.kill()

    summary["gate_a_loopback_passed"] = loopback_passed
    gate_a_passed = (
        bool(summary.get("gate_a_protocol_tests_passed"))
        and bool(summary.get("gate_a_c_ffi_tests_passed"))
        and loopback_passed
    )
    summary["gate_a_passed"] = gate_a_passed
    summary["status"] = STATUS_PREPARED if gate_a_passed else STATUS_BLOCKED
    summary["blockers"] = list(driver.blockers)
    summary["pc_environment"] = environment
    summary.update(BOUNDARY_FIELDS)
    summary["real_jetson_detected"] = False
    summary["gate_b_executed"] = False
    summary["gate_c_executed"] = False

    evidence.write_json("summary.json", summary)
    evidence.write_json("pc_metrics.json", pc_metrics_payload)
    evidence.write_json("jetson_metrics.json", jetson_evidence.get("metrics", {}))
    evidence.write_json("environment.json", environment)
    evidence.write_fault_matrix(driver.fault_rows)
    evidence.write_events(driver.events + list(jetson_evidence.get("events", [])))
    evidence.write_json(
        "network_metrics.json",
        {
            "transport_medium": "loopback",
            "loopback_host": args.loopback_host,
            "frame_port": args.frame_port,
            "control_port": args.control_port,
            "command_port": args.command_port,
            "ack_port": args.ack_port,
            "clock": driver.clock_result.to_dict() if driver.clock_result else None,
        },
    )
    evidence.write_json(
        "manifest.json",
        {
            "phase": PHASE,
            "gate": "A",
            "run_id": run_id,
            "status": summary["status"],
            "created_at_utc": utc_now_iso(),
            "evidence_dir": str(evidence.run_dir),
            "generated_evidence_git_policy": "ignored_local_only",
            **BOUNDARY_FIELDS,
        },
    )
    evidence.write_text(
        "commands.txt", "# Phase 13B Gate A\n%s %s\n" % (sys.executable, " ".join(sys.argv))
    )
    evidence.write_text(
        "README.md",
        "# Phase 13B Gate A evidence\n\nRun id: `%s`\n\nStatus: `%s`\n\n"
        "Local loopback only. No real Jetson, no CARLA server and no physical hardware "
        "was involved. Gate A alone permits only the Prepared status.\n"
        % (run_id, summary["status"]),
    )

    print(summary["status"])
    print("run_id=%s" % run_id)
    print("evidence_dir=%s" % evidence.run_dir)
    for key in (
        "gate_a_source_implementation_ready",
        "gate_a_protocol_tests_passed",
        "gate_a_mailbox_tests_passed",
        "gate_a_clock_tests_passed",
        "gate_a_c_ffi_tests_passed",
        "gate_a_loopback_passed",
    ):
        print("%s=%s" % (key, summary.get(key)))
    if not gate_a_passed and summary.get("error"):
        print("error=%s" % summary["error"], file=sys.stderr)
    return 0 if gate_a_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
