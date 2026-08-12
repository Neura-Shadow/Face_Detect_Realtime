"""Phase 13B Jetson-in-the-loop node (runs on the real Jetson Orin NX).

Pipeline on the real Jetson:

    FrameReceiver -> FixedBufferPool -> LatestFrameMailbox(depth=1)
      -> JPEG decode (BGR8)
      -> input-only RangeShift validation (dummy backend)
         or TensorRT FP16 inference + input/output range contract (Phase 13C)
      -> DummyPerceptionBackend or TensorRTPerceptionBackend
      -> diagnostic PlannerAction -> existing SafetyGate
      -> existing PlannerAction-to-control mapper
      -> EmbeddedCommandBridge (unchanged Phase 13A 64-byte packet)
      -> UDP -> PC C Virtual Safety MCU -> JILA ACK -> ACK validation

The simulation PC drives the whole run over the control/clock/metrics TCP
channel, so every gate step is deterministic and reproducible.

This module must run on Jetson Python 3.8.10: only ``typing`` generics, no
3.9/3.10+ runtime APIs.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np

from workers.core.clock_sync import (
    DEFAULT_MAX_UNCERTAINTY_US,
    JetsonClockDomain,
    monotonic_us,
)
from workers.core.config import ActionStep, AgentConfig, PerceptionConfig, PlannerAction
from workers.core.carla_adapter import PlannerActionToCarlaControl
from workers.core.edge_perception import EdgePerception
from workers.core.embedded_command_bridge import (
    CONTROL_SCALE,
    PACKET_SIZE,
    PROTOCOL_VERSION,
    EmbeddedCommandBridge,
    encode_packet,
)
from workers.core.frame_transport import (
    FrameStreamServer,
    FrameTransportError,
    JpegCodec,
    jpeg_codec_preflight,
    recv_control_message,
    send_control_message,
)
from workers.core.jetson_resource_monitor import JetsonResourceMonitor
from workers.core.jil_protocol import (
    ACK_PACKET_SIZE,
    DEFAULT_MAX_PAYLOAD_BYTES,
    FRAME_HEADER_SIZE,
    JilProtocolError,
    frame_age_ms,
    protocol_descriptor,
)
from workers.core.latest_frame_mailbox import (
    DEFAULT_POOL_SIZE,
    FixedBufferPool,
    FrameFlowMetrics,
    LatestFrameMailbox,
)
from workers.core.range_shift_monitor import (
    PHASE13B_RANGE_VALIDATION_SCOPE,
    InputOnlyRangeProfile,
    RangeShiftState,
    build_phase13b_input_contract,
)
from workers.core.safety_gate import SafetyGate
from workers.core.udp_command_transport import (
    AckUdpReceiver,
    CommandUdpSender,
    UdpTransportError,
)

PHASE = "Phase 13B-JETSON-IN-THE-LOOP-BRIDGE"
DEFAULT_FRAME_PORT = 13510
DEFAULT_CONTROL_PORT = 13513
DEFAULT_COMMAND_PORT = 13511
DEFAULT_ACK_PORT = 13512
DEFAULT_DIAGNOSTIC_THROTTLE = 0.20
DEFAULT_COMMAND_VALIDITY_MS = 500
DEFAULT_OUTPUT_DIR = "experiments/phase13"
DEFAULT_STALE_FRAME_MS = 2000.0


def _utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _run(command: List[str], *, cwd: Optional[Path] = None, timeout: int = 900) -> Dict[str, Any]:
    started = time.time()
    try:
        completed = subprocess.run(
            command,
            cwd=str(cwd or REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            timeout=timeout,
        )
        return {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "duration_sec": round(time.time() - started, 3),
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "command": command,
            "returncode": -1,
            "stdout": "",
            "stderr": repr(exc),
            "duration_sec": round(time.time() - started, 3),
        }


def _git_sha() -> str:
    result = _run(["git", "rev-parse", "HEAD"], timeout=60)
    return result["stdout"].strip() if result["returncode"] == 0 else ""


def _git_status_clean() -> bool:
    result = _run(["git", "status", "--porcelain", "--untracked-files=no"], timeout=60)
    return result["returncode"] == 0 and not result["stdout"].strip()


def collect_environment(*, require_real_jetson: bool) -> Dict[str, Any]:
    """Capture the Jetson runtime baseline without changing anything."""

    machine = platform.machine()
    model = ""
    for path in ("/proc/device-tree/model", "/sys/firmware/devicetree/base/model"):
        try:
            with open(path, "rb") as handle:
                model = handle.read().decode("utf-8", "replace").strip("\x00").strip()
            break
        except (OSError, IOError):
            continue
    l4t = ""
    try:
        with open("/etc/nv_tegra_release", "r") as handle:
            l4t = handle.readline().strip()
    except (OSError, IOError):
        pass
    jetpack = ""
    try:
        with open("/etc/nv_boot_control.conf", "r") as handle:
            jetpack = handle.read().strip().splitlines()[0] if handle else ""
    except (OSError, IOError):
        pass

    is_aarch64 = machine == "aarch64"
    is_tegra = bool(l4t) or "NVIDIA" in model.upper() or os.path.exists("/etc/nv_tegra_release")
    real_jetson = is_aarch64 and is_tegra

    payload = {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "jetson_arch": machine,
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "device_tree_model": model,
        "l4t_release": l4t,
        "nv_boot_control_head": jetpack,
        "kernel_release": platform.release(),
        "real_jetson_detected": real_jetson,
        "require_real_jetson": require_real_jetson,
        "repository_root": str(REPO_ROOT),
        "runtime_jetson_git_sha": _git_sha(),
        "jetson_worktree_clean": _git_status_clean(),
        "numpy_version": np.__version__,
        "nvpmodel_modified": False,
        "clocks_modified": False,
        "jetpack_modified": False,
        "kernel_modified": False,
        "dependencies_auto_installed": False,
    }
    for module_name in ("cv2", "dotenv", "yaml", "pydantic", "eval_type_backport", "tensorrt"):
        try:
            module = __import__(module_name)
            payload["dep_%s" % module_name] = str(getattr(module, "__version__", "present"))
        except Exception as exc:  # pragma: no cover - environment dependent
            payload["dep_%s" % module_name] = "MISSING: %r" % (exc,)
    payload.update(jpeg_codec_preflight())
    return payload


class JetsonNode:
    """Phase 13B Jetson runtime, driven by the PC control channel."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.run_id = args.run_id or ("phase13b-%s" % uuid.uuid4().hex[:12])
        self.output_root = Path(args.output_dir)
        if not self.output_root.is_absolute():
            self.output_root = REPO_ROOT / self.output_root
        self.evidence_dir = self.output_root / self.run_id
        self.evidence_dir.mkdir(parents=True, exist_ok=True)

        self.events = []  # type: List[Dict[str, Any]]
        self.events_lock = threading.Lock()
        self.environment = collect_environment(require_real_jetson=args.require_real_jetson)
        self.blockers = []  # type: List[str]

        max_payload = int(args.max_payload_bytes)
        self.pool = FixedBufferPool(size=int(args.pool_size), capacity_bytes=max_payload)
        self.mailbox = LatestFrameMailbox(self.pool)
        self.flow = FrameFlowMetrics()
        self.codec = JpegCodec(quality=int(args.jpeg_quality))

        self.frame_server = FrameStreamServer(
            args.bind_host,
            int(args.frame_port),
            pool=self.pool,
            timeout_sec=float(args.socket_timeout_sec),
            max_payload_bytes=max_payload,
        )
        self.ack_receiver = AckUdpReceiver(
            args.bind_host,
            int(args.ack_port),
            timeout_sec=float(args.ack_timeout_ms) / 1000.0,
        )
        self.command_sender = None  # type: Optional[CommandUdpSender]

        self.config = AgentConfig.load()
        self.config = self._with_dummy_backend(self.config)
        self.perception = EdgePerception(self.config)
        self.safety_gate = SafetyGate(self.config)
        self.control_mapper = PlannerActionToCarlaControl(self.config.carla)
        self.range_profile = InputOnlyRangeProfile(build_phase13b_input_contract())
        self.bridge = EmbeddedCommandBridge(
            lease_duration_us=int(args.command_validity_ms) * 1000
        )
        self.clock = JetsonClockDomain(
            jetson_minus_pc_offset_us=0,
            clock_uncertainty_us=DEFAULT_MAX_UNCERTAINTY_US + 1,
            clock_sync_valid=False,
            max_uncertainty_us=int(args.max_clock_uncertainty_us),
        )
        self.resources = JetsonResourceMonitor(interval_ms=int(args.tegrastats_interval_ms))

        self.session = {
            "run_id": self.run_id,
            "command_lease_id": 0,
            "lease_expires_pc_us": 0,
            "session_id": "",
            "started": False,
        }  # type: Dict[str, Any]

        self.faults = {
            "corrupt_command_crc": 0,
            "duplicate_command": 0,
            "out_of_order_command": 0,
            "expired_command": 0,
            "wrong_lease_command": 0,
            "drop_command": 0,
            "stop_heartbeat": 0,
            "nan_frame": 0,
            "black_frame": 0,
            "color_order_mismatch": 0,
            "stale_result_age": 0,
            "force_clock_degraded": 0,
            "ack_sequence_unchecked": 0,
        }  # type: Dict[str, int]

        self.commands_sent = 0
        self.commands_skipped = 0
        self.ack_resync_drops = 0
        # Phase 13C TensorRT counters; all stay zero on the default dummy path.
        self.tensorrt_frames_received = 0
        self.tensorrt_inference_requested_count = 0
        self.tensorrt_inference_completed_count = 0
        self.tensorrt_inference_failed_count = 0
        self.tensorrt_fallback_count = 0
        self.tensorrt_safe_stop_count = 0
        self.tensorrt_active_authority_count = 0
        self.tensorrt_result_stale_count = 0
        self.tensorrt_latency_samples = {}  # type: Dict[str, List[float]]
        self.tensorrt_warmup_count = 0
        self.tensorrt_warmup_first_ms = None  # type: Optional[float]
        self.tensorrt_warmup_last_ms = None  # type: Optional[float]
        self.command_classifications = {}  # type: Dict[str, int]
        self.ack_timeouts = 0
        self.ai_active_command_count = 0
        self.safe_stop_command_count = 0
        self.diagnostic_throttle_applied = []  # type: List[float]
        self.frame_command_records = []  # type: List[Dict[str, Any]]
        self.range_state_counts = {}  # type: Dict[str, int]
        self.one_way_latency_ms = []  # type: List[float]
        self.command_rtt_ms = []  # type: List[float]
        self.frame_to_command_ms = []  # type: List[float]

        self.perception_mode = str(getattr(args, "perception_backend", "dummy")).lower()
        self.tensorrt_backend = None  # type: Optional[Any]
        self.tensorrt_monitor = None  # type: Optional[Any]
        self.tensorrt_error = None  # type: Optional[str]
        if self.perception_mode == "tensorrt":
            self._init_tensorrt_backend()

        self._frame_thread = None  # type: Optional[threading.Thread]
        self._stop_frames = threading.Event()
        self._pipeline_lock = threading.Lock()
        self._frames_target = 0
        self._frames_done = threading.Event()

    # ── helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _with_dummy_backend(config: AgentConfig) -> AgentConfig:
        """Phase 13B is dummy-perception only; TensorRT belongs to Phase 13C."""

        import dataclasses

        perception = dataclasses.replace(
            config.perception, backend="dummy", model_name="dummy"
        )  # type: PerceptionConfig
        return dataclasses.replace(config, perception=perception)

    def emit(self, event_type: str, **details: Any) -> None:
        event = {
            "timestamp_utc": _utc_now_iso(),
            "monotonic_us": monotonic_us(),
            "source": "jetson",
            "run_id": self.run_id,
            "event_type": event_type,
        }
        event.update(details)
        with self.events_lock:
            self.events.append(event)

    def _bump(self, mapping: Dict[str, int], key: str) -> None:
        mapping[key] = mapping.get(key, 0) + 1

    # ── Phase 13A preflight ─────────────────────────────────────────────────

    def run_phase13a_preflight(self) -> Dict[str, Any]:
        """Run the frozen Phase 13A SIL with a relative script path."""

        result = _run(
            [
                sys.executable,
                os.path.join("scripts", "run_phase13a_embedded_contract_sil.py"),
                "--output-dir",
                DEFAULT_OUTPUT_DIR,
            ]
        )
        stdout = result["stdout"]
        sil_line = ""
        for line in stdout.splitlines():
            if line.startswith("sil_tests="):
                sil_line = line.strip()
        payload = {
            "phase13a_python_preflight_passed": result["returncode"] == 0 and sil_line.endswith("28/28"),
            "phase13a_preflight_returncode": result["returncode"],
            "phase13a_sil_tests": sil_line.replace("sil_tests=", "") if sil_line else "",
            "phase13a_preflight_invocation": "relative_path",
            "phase13a_preflight_stdout_tail": stdout.strip().splitlines()[-8:],
            "phase13a_preflight_stderr_tail": result["stderr"].strip().splitlines()[-8:],
        }
        if not payload["phase13a_python_preflight_passed"]:
            self.blockers.append("phase13a_preflight_failed")
        self.emit("phase13a_preflight", **payload)
        return payload

    def run_arm64_c_gate(self) -> Dict[str, Any]:
        """Native ARM64 CMake configure/build/CTest plus a direct binary run."""

        import shutil
        import tempfile

        cmake = shutil.which("cmake")
        ctest = shutil.which("ctest")
        if cmake is None or ctest is None:
            payload = {
                "phase13a_arm64_ctest_passed": False,
                "arm64_c_gate_error": "cmake/ctest not available",
            }
            self.blockers.append("arm64_ctest_failed")
            self.emit("arm64_c_gate", **payload)
            return payload

        tmp_root = "/tmp" if os.path.isdir("/tmp") else None
        build_dir = Path(tempfile.mkdtemp(prefix="ma-vlna-phase13b-build-", dir=tmp_root))
        configure = _run([cmake, "-S", str(REPO_ROOT / "embedded"), "-B", str(build_dir)])
        build = _run([cmake, "--build", str(build_dir)])
        # CMake 3.16 on JetPack 5 has no `ctest --test-dir`; run from the build dir.
        tests = _run([ctest, "--output-on-failure"], cwd=build_dir)

        binaries = {}  # type: Dict[str, Any]
        direct_exit = None  # type: Optional[int]
        arm64_verified = False
        file_tool = shutil.which("file")
        for name in ("phase13a_safety_mcu_tests", "phase13b_safety_mcu_ffi_tests"):
            binary = build_dir / name
            entry = {"exists": binary.is_file()}
            if binary.is_file() and file_tool:
                described = _run([file_tool, str(binary)])
                entry["file_output"] = described["stdout"].strip()
                entry["arm64_verified"] = "aarch64" in described["stdout"].lower()
                arm64_verified = arm64_verified or bool(entry["arm64_verified"])
            if binary.is_file():
                direct = _run([str(binary)])
                entry["direct_exit_code"] = direct["returncode"]
                entry["direct_stdout"] = direct["stdout"].strip()
                if name == "phase13a_safety_mcu_tests":
                    direct_exit = direct["returncode"]
            binaries[name] = entry

        library = build_dir / "libma_vlna_safety_mcu_ffi.so"
        ffi_entry = {"exists": library.is_file()}
        if library.is_file() and file_tool:
            described = _run([file_tool, str(library)])
            ffi_entry["file_output"] = described["stdout"].strip()
            ffi_entry["arm64_verified"] = "aarch64" in described["stdout"].lower()

        ctest_passed = tests["returncode"] == 0 and build["returncode"] == 0 and configure["returncode"] == 0
        payload = {
            "phase13a_arm64_ctest_passed": ctest_passed,
            "phase13a_arm64_binary_verified": arm64_verified,
            "phase13a_arm64_direct_test_exit_code": direct_exit,
            "arm64_build_dir": str(build_dir),
            "arm64_configure_returncode": configure["returncode"],
            "arm64_build_returncode": build["returncode"],
            "arm64_ctest_returncode": tests["returncode"],
            "arm64_ctest_stdout_tail": tests["stdout"].strip().splitlines()[-12:],
            "arm64_binaries": binaries,
            "arm64_ffi_shared_library": ffi_entry,
            "ctest_invocation": "cd <build-dir> && ctest --output-on-failure",
        }
        if not ctest_passed:
            self.blockers.append("arm64_ctest_failed")
        self.emit("arm64_c_gate", **payload)
        return payload

    # ── frame pipeline ──────────────────────────────────────────────────────

    def _frame_loop(self) -> None:
        """Accept publisher connections and pump frames into the depth-1 mailbox.

        A header-level rejection leaves the rest of that frame in the TCP
        stream, so the publisher always closes the connection after injecting a
        header fault. This loop therefore re-accepts instead of terminating,
        which is also the Phase 13B reconnect path.
        """

        while not self._stop_frames.is_set():
            try:
                peer = self.frame_server.accept(timeout_sec=float(self.args.frame_accept_poll_sec))
            except FrameTransportError as exc:
                if exc.classification != "TRANSPORT_TIMEOUT":
                    self.emit(
                        "frame_publisher_accept_failed",
                        classification=exc.classification,
                        error=exc.message,
                    )
                continue
            self.emit(
                "frame_publisher_connected",
                peer_host=peer[0],
                peer_port=peer[1],
                accept_count=self.frame_server.accept_count,
            )
            self._frame_connection_loop()
            self.frame_server.close_connection()
            self.emit("frame_publisher_disconnected", accept_count=self.frame_server.accept_count)

        self.mailbox.drain()
        self._frames_done.set()

    def _frame_connection_loop(self) -> None:
        while not self._stop_frames.is_set():
            try:
                header, buffer = self.frame_server.receive_frame(
                    timeout_sec=float(self.args.frame_timeout_sec)
                )
            except JilProtocolError as exc:
                self.flow.record_reject(exc.classification)
                self.flow.frames_dropped_transport += 1
                self.emit("frame_rejected", classification=exc.classification, error=exc.message)
                # A rejected header leaves an unread payload behind: the
                # publisher reconnects, so stop reading this connection.
                if exc.classification != "FRAME_CRC_REJECT":
                    return
                continue
            except FrameTransportError as exc:
                self.flow.record_reject(exc.classification)
                self.emit(
                    "frame_transport_error", classification=exc.classification, error=exc.message
                )
                return

            self.flow.frames_received += 1
            dropped = self.mailbox.publish(buffer)
            if dropped:
                self.flow.frames_dropped_mailbox += 1
            self._process_latest()
            if self._frames_target and self.flow.frames_processed >= self._frames_target:
                self._frames_done.set()

    def _process_latest(self) -> None:
        """Take the newest frame and run the Jetson diagnostic pipeline once."""

        buffer = self.mailbox.take()
        if buffer is None:
            return
        header = buffer.meta.get("header")
        payload = buffer.payload()
        try:
            self._process_frame(header, payload)
        finally:
            self.pool.release(buffer)

    def _process_frame(self, header: Any, payload: bytes) -> None:
        receive_us = monotonic_us()
        now_pc_us = self.clock.to_pc_clock_us(receive_us)
        age_ms = frame_age_ms(int(header.pc_monotonic_us), now_pc_us)
        self.flow.record_frame_age(age_ms)

        if age_ms is not None and age_ms > float(self.args.stale_frame_ms):
            self.flow.stale_frame_reject_count += 1
            self.flow.record_reject("STALE_REJECT")
            self.emit(
                "frame_stale_rejected",
                frame_id=int(header.frame_id),
                frame_age_ms=age_ms,
                classification="STALE_REJECT",
            )
            self._send_safe_stop("stale_frame", frame_id=int(header.frame_id))
            return

        try:
            frame = self.codec.decode_to_bgr(payload)
            self.flow.frames_decoded += 1
        except Exception as exc:
            self.flow.frame_decode_failure_count += 1
            self.flow.record_reject("FRAME_CODEC_REJECT")
            self.emit(
                "frame_decode_failed",
                frame_id=int(header.frame_id),
                classification="FRAME_CODEC_REJECT",
                error=repr(exc),
            )
            self._send_safe_stop("frame_decode_failed", frame_id=int(header.frame_id))
            return

        model_color_order = "RGB"
        if self.faults["nan_frame"]:
            self.faults["nan_frame"] -= 1
            frame = frame.astype(np.float32)
            frame[0, 0, 0] = np.nan
        elif self.faults["black_frame"]:
            self.faults["black_frame"] -= 1
            frame = np.zeros_like(frame)
        elif self.faults["color_order_mismatch"]:
            self.faults["color_order_mismatch"] -= 1
            model_color_order = "BGR"

        result_age_ms = float(self.args.nominal_result_age_ms)
        if self.faults["stale_result_age"]:
            self.faults["stale_result_age"] -= 1
            result_age_ms = float(self.range_profile.contract.max_result_age_ms) + 50.0

        clock_degraded = self.clock.clock_sync_degraded
        if self.faults["force_clock_degraded"]:
            self.faults["force_clock_degraded"] -= 1
            clock_degraded = True

        target_throttle = float(self.args.diagnostic_throttle)
        if self.perception_mode == "tensorrt":
            # Phase 13C: a real engine decides authority for THIS frame id.
            tensorrt_frame = frame
            if tensorrt_frame.dtype != np.uint8:
                tensorrt_frame = np.nan_to_num(
                    tensorrt_frame, nan=np.nan, posinf=np.inf, neginf=-np.inf
                )
            range_result, backend_name, _ = self._run_tensorrt_perception(
                tensorrt_frame,
                int(header.frame_id),
                result_age_ms,
                clock_degraded,
                declared_color_order=model_color_order,
            )
        else:
            perception_frame = frame
            if perception_frame.dtype != np.uint8:
                perception_frame = np.nan_to_num(
                    perception_frame, nan=0.0, posinf=255.0, neginf=0.0
                ).astype(np.uint8)
            perception = self.perception.process(
                perception_frame, frame_id=int(header.frame_id)
            )
            backend_name = str(getattr(perception, "backend", "dummy"))
            range_result = self.range_profile.evaluate_frame(
                bgr_frame=frame,
                outputs={
                    "steering": 0.0,
                    "throttle": target_throttle,
                    "brake": 0.0,
                    "ai_confidence": float(self.args.diagnostic_confidence),
                },
                result_age_ms=result_age_ms,
                model_color_order=model_color_order,
            )
        self._bump(self.range_state_counts, range_result.state.name)

        action = self._diagnostic_planner_action(target_throttle)
        gate_result = self.safety_gate.validate_planner_action(action)
        approved_action = gate_result.modified_action or action
        control = self.control_mapper.map_action(approved_action)

        gate_ok = gate_result.approved and not clock_degraded
        self.flow.frames_processed += 1

        record = self._send_command(
            frame_id=int(header.frame_id),
            frame_receive_us=receive_us,
            frame_age_ms=age_ms,
            range_result=range_result,
            gate_approved=gate_ok,
            steering=0.0 if clock_degraded else float(control.steer),
            throttle=0.0 if clock_degraded else float(control.throttle),
            brake=1.0 if clock_degraded else float(control.brake),
            result_age_ms=result_age_ms,
            clock_degraded=clock_degraded,
            perception_backend=backend_name,
            simulation_timestamp_us=int(header.simulation_timestamp_us),
            pc_monotonic_us=int(header.pc_monotonic_us),
        )
        if record is not None:
            self.frame_command_records.append(record)

    def _init_tensorrt_backend(self) -> None:
        """Build the Phase 13C TensorRT backend. Never silently falls back."""

        from run_phase13c_standalone_benchmark import load_contracts
        from workers.core.tensorrt_perception import (
            TensorRTPerceptionBackend,
            load_class_names,
        )
        from workers.core.tensorrt_runtime import TensorRTEngineRunner, TensorRTRuntimeError

        engine = str(getattr(self.args, "tensorrt_engine", "") or "")
        if not engine:
            self.tensorrt_error = "tensorrt_engine_path_missing"
            self.blockers.append("engine_missing")
            self.emit("tensorrt_backend_unavailable", classification="engine_missing")
            return
        try:
            contracts = load_contracts(
                str(getattr(self.args, "tensorrt_model_manifest", "") or ""),
                str(getattr(self.args, "tensorrt_engine_manifest", "") or ""),
                str(getattr(self.args, "tensorrt_profile", "yolov9-c")),
            )
            runner = TensorRTEngineRunner(
                engine,
                expected_input_shape=contracts["input_contract"].shape,
                expected_input_name=contracts["input_contract"].input_name,
            )
            class_names, class_names_source = load_class_names(
                str(getattr(self.args, "tensorrt_class_names", "") or "")
                or contracts["class_names_source"]
                or None
            )
            self.tensorrt_backend = TensorRTPerceptionBackend(
                runner,
                input_contract=contracts["input_contract"],
                output_contract=contracts["output_contract"],
                profile=contracts["postprocess_profile"],
                class_names=class_names,
                model_name=str(getattr(self.args, "tensorrt_profile", "yolov9-c")),
                precision=str(getattr(self.args, "tensorrt_precision", "fp16") or "fp16"),
            )
            self.tensorrt_monitor = self._build_range_monitor(contracts)
            # Warm the engine before any real frame arrives. The first
            # inference after deserialization pays lazy CUDA context and kernel
            # initialisation (measured at ~1.28 s on the Orin NX versus a ~78 ms
            # steady state). Without this, frame 1 blows the inference-timeout
            # gate, and three consecutive non-VALID range states drive the C
            # Safety MCU into FAILSAFE, after which every later command is
            # STATE_REJECTed.
            warmup = max(0, int(getattr(self.args, "tensorrt_warmup", 0)))
            warmup_ms = []  # type: List[float]
            if warmup:
                probe = np.full((360, 640, 3), 128, dtype=np.uint8)
                for _ in range(warmup):
                    self.tensorrt_backend.detect(probe)
                    value = self.tensorrt_backend.last_timing.get("frame_to_perception_ms")
                    if value is not None:
                        warmup_ms.append(float(value))
                # Warm-up must not pollute the runtime counters.
                self.tensorrt_backend.inference_count = 0
                self.tensorrt_backend.failure_count = 0
            self.tensorrt_warmup_count = warmup
            self.tensorrt_warmup_first_ms = round(warmup_ms[0], 3) if warmup_ms else None
            self.tensorrt_warmup_last_ms = round(warmup_ms[-1], 3) if warmup_ms else None
            self.emit(
                "tensorrt_backend_ready",
                engine=engine,
                class_names_source=class_names_source,
                tensorrt_warmup_count=self.tensorrt_warmup_count,
                tensorrt_warmup_first_ms=self.tensorrt_warmup_first_ms,
                tensorrt_warmup_last_ms=self.tensorrt_warmup_last_ms,
                **runner.binding_report()
            )
        except TensorRTRuntimeError as exc:
            self.tensorrt_error = exc.classification
            self.blockers.append(exc.classification)
            self.emit("tensorrt_backend_unavailable", classification=exc.classification,
                      error=exc.message)
        except Exception as exc:
            self.tensorrt_error = "tensorrt_backend_init_failed"
            self.blockers.append("tensorrt_backend_init_failed")
            self.emit("tensorrt_backend_unavailable",
                      classification="tensorrt_backend_init_failed", error=repr(exc)[:200])

    def _build_range_monitor(self, contracts: Dict[str, Any]) -> Any:
        """Phase 13C FP16 monitor, or the Phase 13D INT8 envelope monitor.

        Passing ``--int8-calibration-envelope`` is what upgrades the gate. With
        no envelope the node behaves exactly as it did in Phase 13C; with an
        envelope that cannot be loaded it refuses to start, because an INT8
        engine whose calibration envelope is unknown cannot be gated at all.
        """

        from workers.core.tensorrt_range_monitor import (
            TensorRTRangeContract,
            TensorRTRangeMonitor,
        )
        from workers.core.tensorrt_runtime import TensorRTRuntimeError

        shared = {
            "expected_input_shape": tuple(contracts["input_contract"].shape),
            "max_result_age_ms": int(self.range_profile.contract.max_result_age_ms),
            "max_inference_ms": float(getattr(self.args, "tensorrt_max_inference_ms", 1000.0)),
        }

        envelope_path = str(getattr(self.args, "int8_calibration_envelope", "") or "")
        if not envelope_path:
            return TensorRTRangeMonitor(TensorRTRangeContract(**shared))

        from workers.core.int8_range_monitor import Int8RangeContract, Int8RangeMonitor, load_envelopes

        envelopes = load_envelopes(envelope_path)
        if envelopes is None:
            raise TensorRTRuntimeError(
                "calibration_envelope_missing",
                "INT8 calibration envelope could not be loaded from %s" % envelope_path,
            )
        proxy = {}  # type: Dict[str, Any]
        proxy_path = str(getattr(self.args, "int8_activation_proxy", "") or "")
        if proxy_path and Path(proxy_path).is_file():
            try:
                proxy = json.loads(Path(proxy_path).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                proxy = {}
        self.emit(
            "int8_calibration_envelope_loaded",
            envelope_path=envelope_path,
            envelope_dataset_sha256=envelopes.dataset_sha256,
            envelope_source_frame_count=envelopes.source_frame_count,
            activation_proxy_loaded=bool(proxy),
        )
        # Phase 13D-MP-RECOVERY froze the INT8 backend as
        # experimental_non_authoritative. It runs, validates and records, but it
        # may not grant AI authority unless that is turned on deliberately.
        authoritative = bool(getattr(self.args, "int8_authoritative", False))
        self.emit(
            "int8_backend_role",
            int8_authoritative=authoritative,
            int8_backend_role=(
                "authoritative" if authoritative else "experimental_non_authoritative"
            ),
        )
        return Int8RangeMonitor(
            Int8RangeContract(authoritative=authoritative, **shared),
            envelopes=envelopes,
            activation_proxy=proxy,
        )

    def _record_tensorrt_latency(self, timing: Dict[str, Any]) -> None:
        for key, value in timing.items():
            if value is None:
                continue
            self.tensorrt_latency_samples.setdefault(key, []).append(float(value))

    def _run_tensorrt_perception(
        self,
        frame: Any,
        frame_id: int,
        result_age_ms: float,
        clock_degraded: bool,
        declared_color_order: str = "RGB",
    ) -> Tuple[Any, str, Optional[Any]]:
        """Run TensorRT for one frame and gate authority on the same frame id.

        Returns ``(range_result, backend_name, perception_result)``. Any failure
        produces a fail-closed verdict, never a fallback to another backend.
        """

        from workers.core.tensorrt_perception import TensorRTPerceptionError
        from workers.core.tensorrt_range_monitor import TensorRTRangeResult
        from workers.core.tensorrt_runtime import TensorRTRuntimeError

        self.tensorrt_frames_received += 1
        if self.tensorrt_backend is None or self.tensorrt_monitor is None:
            self.tensorrt_safe_stop_count += 1
            return (
                TensorRTRangeResult(
                    state=RangeShiftState.OUTPUT_RANGE_INVALID,
                    sample_valid=False,
                    ai_result_valid=False,
                    reason="tensorrt backend unavailable: %s" % (self.tensorrt_error or "unknown"),
                    classification=self.tensorrt_error or "tensorrt_backend_unavailable",
                ),
                "tensorrt_unavailable",
                None,
            )

        self.tensorrt_inference_requested_count += 1
        try:
            detections, inference_ms = self.tensorrt_backend.detect(frame)
        except (TensorRTPerceptionError, TensorRTRuntimeError) as exc:
            self.tensorrt_inference_failed_count += 1
            self.tensorrt_safe_stop_count += 1
            self.emit(
                "tensorrt_inference_failed",
                frame_id=frame_id,
                classification=exc.classification,
                error=exc.message,
            )
            return (
                TensorRTRangeResult(
                    state=RangeShiftState.OUTPUT_RANGE_INVALID,
                    sample_valid=False,
                    ai_result_valid=False,
                    reason=exc.message,
                    classification=exc.classification,
                ),
                "tensorrt",
                None,
            )

        self.tensorrt_inference_completed_count += 1
        self._record_tensorrt_latency(self.tensorrt_backend.last_timing)
        input_stats = dict(self.tensorrt_backend.last_stats)
        # A colour-order fault means the frame was delivered in an order the
        # engine was not calibrated for; declare that to the range monitor so
        # its colour-order check can fire on the TensorRT path too.
        if declared_color_order and declared_color_order.upper() != "RGB":
            input_stats["input_color_order"] = declared_color_order
        verdict = self.tensorrt_monitor.evaluate(
            input_stats=input_stats,
            detections=detections,
            output_stats=self.tensorrt_backend.last_stats,
            inference_ms=float(self.tensorrt_backend.last_timing.get("frame_to_perception_ms", 0.0)),
            result_age_ms=float(result_age_ms),
            engine_execute_ok=True,
            fallback_used=bool(self.tensorrt_backend.fallback_used),
        )
        if self.tensorrt_backend.fallback_used:
            self.tensorrt_fallback_count += 1
        if verdict.classification == "result_stale":
            self.tensorrt_result_stale_count += 1
        if verdict.ai_result_valid and not clock_degraded:
            self.tensorrt_active_authority_count += 1
        else:
            self.tensorrt_safe_stop_count += 1
        return verdict, "tensorrt", detections

    def _diagnostic_planner_action(self, target_throttle: float) -> PlannerAction:
        """One bounded forward step, deterministic, runner-scoped.

        The speed is derived by inverting the *existing, unmodified*
        PlannerAction-to-control mapper so that the requested diagnostic
        throttle falls out of the baseline mapper. The mapper itself is never
        changed to make Phase 13B pass, and the SafetyGate may still clamp the
        speed, in which case the applied throttle is simply recorded lower.
        """

        carla_config = self.config.carla
        gain = max(1e-6, float(carla_config.throttle_gain))
        speed_mps = (float(target_throttle) / gain) * max(0.1, float(carla_config.max_control_speed_mps))
        return PlannerAction(
            plan_id="phase13b-diagnostic",
            timestamp=_utc_now_iso(),
            source="local_planner",
            waypoints=[],
            action_sequence=[
                ActionStep(
                    action="forward",
                    duration_sec=float(self.args.command_validity_ms) / 1000.0,
                    speed_mps=speed_mps,
                    steering_deg=0.0,
                )
            ],
            validated=True,
        )

    # ── command / ACK path ──────────────────────────────────────────────────

    def _send_safe_stop(self, reason: str, *, frame_id: Optional[int] = None) -> None:
        from workers.core.range_shift_monitor import RangeShiftResult

        forced = RangeShiftResult(
            state=RangeShiftState.OUTPUT_RANGE_INVALID,
            sample_valid=False,
            ai_result_valid=False,
            reason=reason,
            consecutive_valid_samples=0,
            recovered=False,
            observations={"reason": reason},
        )
        self._send_command(
            frame_id=frame_id if frame_id is not None else -1,
            frame_receive_us=monotonic_us(),
            frame_age_ms=None,
            range_result=forced,
            gate_approved=False,
            steering=0.0,
            throttle=0.0,
            brake=1.0,
            result_age_ms=0.0,
            clock_degraded=self.clock.clock_sync_degraded,
            perception_backend="dummy",
            simulation_timestamp_us=0,
            pc_monotonic_us=0,
            reason=reason,
        )

    def _send_command(
        self,
        *,
        frame_id: int,
        frame_receive_us: int,
        frame_age_ms: Optional[float],
        range_result: Any,
        gate_approved: bool,
        steering: float,
        throttle: float,
        brake: float,
        result_age_ms: float,
        clock_degraded: bool,
        perception_backend: str,
        simulation_timestamp_us: int,
        pc_monotonic_us: int,
        reason: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Build, optionally fault-inject, send and ACK one Phase 13A command."""

        if self.command_sender is None:
            return None

        with self._pipeline_lock:
            lease_id = int(self.session["command_lease_id"])
            issued_us = self.clock.issued_timestamp_us()
            source_us = self.clock.to_pc_clock_us(frame_receive_us)
            if source_us > issued_us:
                source_us = issued_us

            wrong_lease = False
            if self.faults["wrong_lease_command"]:
                self.faults["wrong_lease_command"] -= 1
                wrong_lease = True

            packet, encoded = self.bridge.build_command(
                source_timestamp_us=source_us,
                issued_timestamp_us=issued_us,
                command_lease_id=(lease_id ^ 0xA5A5A5A5) if wrong_lease else lease_id,
                safety_gate_approved=gate_approved,
                range_result=range_result,
                steering=steering,
                throttle=throttle,
                brake=brake,
                ai_confidence=float(self.args.diagnostic_confidence),
                result_age_ms=int(round(result_age_ms)),
            )

            expected = "ACCEPTED"
            injected = None  # type: Optional[str]
            wire = encoded
            duplicate_of = None  # type: Optional[bytes]

            if wrong_lease:
                expected = "LEASE_REJECT"
                injected = "wrong_lease"
            elif self.faults["corrupt_command_crc"]:
                self.faults["corrupt_command_crc"] -= 1
                mutated = bytearray(encoded)
                mutated[12] ^= 0x01
                wire = bytes(mutated)
                expected = "CRC_REJECT"
                injected = "corrupt_command_crc"
            elif self.faults["expired_command"]:
                self.faults["expired_command"] -= 1
                from dataclasses import replace

                stale = replace(packet, valid_until_us=max(0, issued_us - 1_000_000))
                wire = encode_packet(stale)
                expected = "STALE_REJECT"
                injected = "expired_command"
            elif self.faults["out_of_order_command"]:
                self.faults["out_of_order_command"] -= 1
                from dataclasses import replace

                lowered = replace(packet, sequence=1)
                wire = encode_packet(lowered)
                expected = "SEQUENCE_REJECT"
                injected = "out_of_order_command"
            elif self.faults["duplicate_command"]:
                self.faults["duplicate_command"] -= 1
                duplicate_of = encoded
                injected = "duplicate_command"
            elif self.faults["drop_command"]:
                self.faults["drop_command"] -= 1
                self.commands_skipped += 1
                self._bump(self.command_classifications, "TRANSPORT_TIMEOUT")
                self.emit(
                    "command_dropped_injected",
                    frame_id=frame_id,
                    sequence=packet.sequence,
                    classification="TRANSPORT_TIMEOUT",
                )
                return {
                    "frame_id": frame_id,
                    "sequence": packet.sequence,
                    "injected_fault": "drop_command",
                    "expected_classification": "TRANSPORT_TIMEOUT",
                    "observed_classification": "TRANSPORT_TIMEOUT",
                    "sent": False,
                }
            elif self.faults["stop_heartbeat"]:
                self.commands_skipped += 1
                self._bump(self.command_classifications, "FAILSAFE")
                return {
                    "frame_id": frame_id,
                    "sequence": packet.sequence,
                    "injected_fault": "stop_heartbeat",
                    "expected_classification": "FAILSAFE",
                    "observed_classification": "FAILSAFE",
                    "sent": False,
                }

            control_mode = int(packet.control_mode)
            # Discard any ACK left over from a previously timed-out command so
            # the ACK received below unambiguously belongs to this command.
            self.ack_resync_drops += self.ack_receiver.drain()
            send_us = monotonic_us()
            self.command_sender.send_command(wire)
            self.commands_sent += 1
            if control_mode == 2:
                self.ai_active_command_count += 1
                self.diagnostic_throttle_applied.append(round(float(packet.throttle), 6))
            else:
                self.safe_stop_command_count += 1

        observed = self._await_ack(None if injected else packet.sequence)
        if duplicate_of is not None:
            with self._pipeline_lock:
                self.command_sender.send_command(duplicate_of)
                self.commands_sent += 1
            observed = self._await_ack(None)
            expected = "SEQUENCE_REJECT"

        rtt_ms = round((monotonic_us() - send_us) / 1000.0, 3)
        self.command_rtt_ms.append(rtt_ms)
        self._bump(self.command_classifications, observed)

        record = {
            "frame_id": frame_id,
            "sequence": int(packet.sequence),
            "control_mode": control_mode,
            "range_shift_state": int(packet.range_shift_state),
            "range_state_name": range_result.state.name,
            "gate_approved": gate_approved,
            "clock_degraded": clock_degraded,
            "throttle": round(float(packet.throttle), 6),
            "steering": round(float(packet.steering), 6),
            "brake": round(float(packet.brake), 6),
            "result_age_ms": int(round(result_age_ms)),
            "frame_age_ms": frame_age_ms,
            "command_rtt_ms": rtt_ms,
            "injected_fault": injected,
            "expected_classification": expected,
            "observed_classification": observed,
            "perception_backend": perception_backend,
            "simulation_timestamp_us": simulation_timestamp_us,
            "pc_monotonic_us": pc_monotonic_us,
            "reason": reason,
            "sent": True,
        }
        one_way = self.clock.one_way_latency_ms(pc_monotonic_us, frame_receive_us) if pc_monotonic_us else None
        record["frame_one_way_latency_ms"] = one_way
        # Phase 13C deadline metric: PC frame emission -> command issuance,
        # expressed in the PC clock domain so it is comparable with the
        # command validity window.
        frame_to_command = None
        if pc_monotonic_us and not self.clock.clock_sync_degraded:
            delta_us = self.clock.to_pc_clock_us(send_us) - int(pc_monotonic_us)
            if delta_us >= 0:
                frame_to_command = round(delta_us / 1000.0, 4)
        record["frame_to_command_ms"] = frame_to_command
        if frame_to_command is not None:
            self.frame_to_command_ms.append(frame_to_command)
        if one_way is not None:
            self.one_way_latency_ms.append(one_way)
        self.emit("command_sent", **record)
        return record

    def _await_ack(self, expected_sequence: Optional[int]) -> str:
        if self.faults["ack_sequence_unchecked"]:
            self.faults["ack_sequence_unchecked"] -= 1
            expected_sequence = None
        try:
            ack = self.ack_receiver.receive_ack(
                expected_sequence=expected_sequence,
                timeout_sec=float(self.args.ack_timeout_ms) / 1000.0,
            )
        except UdpTransportError as exc:
            if exc.classification == "TRANSPORT_TIMEOUT":
                self.ack_timeouts += 1
            return exc.classification
        except JilProtocolError as exc:
            return exc.classification
        return ack.classification

    # ── command/ACK stress (no frames) ──────────────────────────────────────

    def command_ack_stress(self, cycles: int) -> Dict[str, Any]:
        """Run bounded command/ACK cycles to exercise the transport at volume."""

        from workers.core.range_shift_monitor import RangeShiftResult

        valid = RangeShiftResult(
            state=RangeShiftState.VALID,
            sample_valid=True,
            ai_result_valid=True,
            reason="stress_valid",
            consecutive_valid_samples=3,
            recovered=False,
            observations={},
        )
        started = monotonic_us()
        accepted = 0
        classifications = {}  # type: Dict[str, int]
        clock_degraded = self.clock.clock_sync_degraded
        for index in range(int(cycles)):
            record = self._send_command(
                frame_id=-1,
                frame_receive_us=monotonic_us(),
                frame_age_ms=None,
                range_result=valid,
                gate_approved=not clock_degraded,
                steering=0.0,
                throttle=0.0 if clock_degraded else float(self.args.diagnostic_throttle),
                brake=1.0 if clock_degraded else 0.0,
                result_age_ms=float(self.args.nominal_result_age_ms),
                clock_degraded=clock_degraded,
                perception_backend="dummy",
                simulation_timestamp_us=0,
                pc_monotonic_us=0,
                reason="command_ack_stress",
            )
            if record is None:
                continue
            observed = record["observed_classification"]
            classifications[observed] = classifications.get(observed, 0) + 1
            if observed == "ACCEPTED":
                accepted += 1
        payload = {
            "stress_cycles_requested": int(cycles),
            "stress_accepted": accepted,
            "stress_classifications": classifications,
            "stress_duration_ms": round((monotonic_us() - started) / 1000.0, 3),
            "stress_valid_acks": self.ack_receiver.valid_acks,
            "stress_clock_degraded": clock_degraded,
        }
        self.emit("command_ack_stress_completed", **payload)
        return payload

    # ── metrics ─────────────────────────────────────────────────────────────

    def metrics(self) -> Dict[str, Any]:
        def _mean(values: List[float]) -> Optional[float]:
            return round(sum(values) / len(values), 3) if values else None

        payload = {
            "run_id": self.run_id,
            "phase": PHASE,
            "source": "jetson",
            "commands_sent": self.commands_sent,
            "commands_skipped_injected": self.commands_skipped,
            "command_classifications": dict(self.command_classifications),
            "ai_active_command_count": self.ai_active_command_count,
            "safe_stop_command_count": self.safe_stop_command_count,
            "ack_timeout_count": self.ack_timeouts,
            "ack_resync_drops": self.ack_resync_drops,
            "diagnostic_throttle_target": float(self.args.diagnostic_throttle),
            "diagnostic_throttle_applied_mean": _mean(self.diagnostic_throttle_applied),
            "diagnostic_throttle_applied_max": max(self.diagnostic_throttle_applied)
            if self.diagnostic_throttle_applied
            else None,
            "frame_to_command_ms_mean": _mean(self.frame_to_command_ms),
            "frame_to_command_ms_sample_count": len(self.frame_to_command_ms),
            "command_rtt_ms_mean": _mean(self.command_rtt_ms),
            "command_rtt_ms_max": round(max(self.command_rtt_ms), 3) if self.command_rtt_ms else None,
            "frame_one_way_latency_ms_mean": _mean(self.one_way_latency_ms),
            "one_way_latency_reported": bool(self.one_way_latency_ms),
            "range_state_counts": dict(self.range_state_counts),
            "command_packet_size_bytes": PACKET_SIZE,
            "command_protocol_version": PROTOCOL_VERSION,
            "command_control_scale": CONTROL_SCALE,
            "ack_packet_size_bytes": ACK_PACKET_SIZE,
            "frame_header_size_bytes": FRAME_HEADER_SIZE,
            "range_validation_scope": PHASE13B_RANGE_VALIDATION_SCOPE,
            "perception_backend": (
                "TensorRTPerceptionBackend"
                if self.perception_mode == "tensorrt"
                else "DummyPerceptionBackend"
            ),
            "perception_mode": self.perception_mode,
            "tensorrt_frames_received": self.tensorrt_frames_received,
            "tensorrt_inference_requested_count": self.tensorrt_inference_requested_count,
            "tensorrt_inference_completed_count": self.tensorrt_inference_completed_count,
            "tensorrt_inference_failed_count": self.tensorrt_inference_failed_count,
            "tensorrt_fallback_count": self.tensorrt_fallback_count,
            "tensorrt_safe_stop_count": self.tensorrt_safe_stop_count,
            "tensorrt_active_authority_count": self.tensorrt_active_authority_count,
            "tensorrt_result_stale_count": self.tensorrt_result_stale_count,
            "tensorrt_backend_error": self.tensorrt_error,
            "tensorrt_warmup_count": self.tensorrt_warmup_count,
            "tensorrt_warmup_first_ms": self.tensorrt_warmup_first_ms,
            "tensorrt_warmup_last_ms": self.tensorrt_warmup_last_ms,
            "tensorrt_inference_verified": self.perception_mode == "tensorrt"
            and self.tensorrt_inference_completed_count > 0,
            "physical_camera_verified": False,
            "physical_actuator_control_executed": False,
            "real_mcu_verified": False,
            "full_hil_verified": False,
        }
        payload.update(self.flow.to_dict(self.pool, self.mailbox))
        payload.update(self.frame_server.metrics())
        payload.update(self.ack_receiver.metrics())
        if self.command_sender is not None:
            payload.update(self.command_sender.metrics())
        if self.frame_to_command_ms:
            from run_phase13c_checks import latency_stats

            payload["frame_to_command_ms_stats"] = latency_stats(self.frame_to_command_ms)
        payload.update(self.range_profile.evidence())
        if self.tensorrt_monitor is not None:
            payload.update(self.tensorrt_monitor.evidence())
        if self.tensorrt_backend is not None:
            payload.update(self.tensorrt_backend.metadata())
        if self.tensorrt_latency_samples:
            from run_phase13c_checks import latency_stats

            payload["tensorrt_latency_metrics"] = {
                name: latency_stats(values)
                for name, values in self.tensorrt_latency_samples.items()
            }
        payload.update(self.clock.to_dict())
        payload.update(self.resources.summary())
        payload.update(protocol_descriptor())
        payload["blockers"] = list(self.blockers)
        return payload

    def write_evidence(self) -> Dict[str, Any]:
        metrics = self.metrics()
        manifest = {
            "phase": PHASE,
            "run_id": self.run_id,
            "created_at_utc": _utc_now_iso(),
            "source": "jetson",
            "repository_root": str(REPO_ROOT),
            "evidence_dir": str(self.evidence_dir),
            "runtime_jetson_git_sha": self.environment.get("runtime_jetson_git_sha", ""),
            "jetson_arch": self.environment.get("jetson_arch", ""),
            "real_jetson_detected": self.environment.get("real_jetson_detected", False),
            "transport_medium": self.args.transport_medium,
            "validation_type": "processor_in_the_loop",
            "output_files": [
                "manifest.json",
                "jetson_metrics.json",
                "events.jsonl",
                "environment.json",
                "commands.txt",
                "README.md",
            ],
            "generated_evidence_git_policy": "ignored_local_only",
        }
        (self.evidence_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (self.evidence_dir / "jetson_metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (self.evidence_dir / "environment.json").write_text(
            json.dumps(self.environment, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        with self.events_lock:
            events = list(self.events)
        (self.evidence_dir / "events.jsonl").write_text(
            "".join(json.dumps(event, ensure_ascii=False) + "\n" for event in events),
            encoding="utf-8",
        )
        (self.evidence_dir / "commands.txt").write_text(
            "# Phase 13B Jetson node\n%s %s\n"
            % (sys.executable, " ".join(sys.argv)),
            encoding="utf-8",
        )
        (self.evidence_dir / "README.md").write_text(
            "# Phase 13B Jetson evidence\n\n"
            "Run id: `%s`\n\n"
            "Real Jetson processor-in-the-loop evidence. Simulated: CARLA camera, "
            "environment, vehicle, Safety MCU, actuator and vehicle physics. "
            "No full HIL, no real MCU, no physical camera or actuator, no TensorRT "
            "inference and no route/infraction benchmark is claimed.\n" % self.run_id,
            encoding="utf-8",
        )
        return metrics

    # ── control channel ─────────────────────────────────────────────────────

    def serve_control(self) -> int:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((self.args.bind_host, int(self.args.control_port)))
        listener.listen(1)
        listener.settimeout(float(self.args.accept_timeout_sec))
        self.frame_server.bind()
        self.resources.start()
        self.emit(
            "jetson_node_started",
            control_port=int(self.args.control_port),
            frame_port=self.frame_server.port,
            ack_port=self.ack_receiver.port,
            pool_size=self.pool.size,
            environment=self.environment,
        )
        print("phase13b_jetson_node_ready run_id=%s control_port=%s frame_port=%s ack_port=%s"
              % (self.run_id, self.args.control_port, self.frame_server.port, self.ack_receiver.port))
        sys.stdout.flush()

        exit_code = 0
        try:
            conn, addr = listener.accept()
            conn.settimeout(float(self.args.control_timeout_sec))
            # Nagle would batch the clock-probe response and inflate the
            # measured network delay, which feeds clock_uncertainty_us.
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.emit("control_channel_connected", peer_host=addr[0], peer_port=addr[1])
            exit_code = self._control_loop(conn, addr[0])
        except socket.timeout:
            self.emit("control_channel_accept_timeout", classification="TRANSPORT_TIMEOUT")
            self.blockers.append("command_transport_failed")
            exit_code = 2
        finally:
            self._stop_frames.set()
            if self._frame_thread is not None:
                self._frame_thread.join(timeout=10)
            self.resources.stop()
            if self.tensorrt_backend is not None:
                try:
                    self.tensorrt_backend.close()
                except Exception:
                    pass
            self.frame_server.close()
            self.ack_receiver.close()
            if self.command_sender is not None:
                self.command_sender.close()
            try:
                listener.close()
            except OSError:
                pass
            self.write_evidence()
        return exit_code

    def _control_loop(self, conn: socket.socket, peer_host: str) -> int:
        while True:
            try:
                message = recv_control_message(conn, timeout_sec=float(self.args.control_timeout_sec))
            except FrameTransportError as exc:
                self.emit("control_channel_error", classification=exc.classification, error=exc.message)
                return 3
            command = str(message.get("command", ""))
            response = {"command": command, "ok": True}  # type: Dict[str, Any]

            if command == "hello":
                response.update(self._handle_hello(message, peer_host))
            elif command == "clock_probe":
                response["t2_jetson_recv_us"] = monotonic_us()
                response["sample_index"] = message.get("sample_index")
                response["t3_jetson_send_us"] = monotonic_us()
            elif command == "start_session":
                response.update(self._handle_start_session(message))
            elif command == "run_frames":
                response.update(self._handle_run_frames(message))
            elif command == "command_ack_stress":
                response.update(self.command_ack_stress(int(message.get("cycles", 0))))
            elif command == "inject_fault":
                response.update(self._handle_inject_fault(message))
            elif command == "phase13a_preflight":
                response.update(self.run_phase13a_preflight())
            elif command == "arm64_c_gate":
                response.update(self.run_arm64_c_gate())
            elif command == "send_heartbeat_commands":
                response.update(self._handle_heartbeat_commands(message))
            elif command == "get_metrics":
                response["metrics"] = self.metrics()
            elif command == "get_events":
                with self.events_lock:
                    response["events"] = list(self.events)
            elif command == "shutdown":
                send_control_message(conn, {"command": command, "ok": True})
                self.emit("control_shutdown_requested")
                return 0
            else:
                response["ok"] = False
                response["error"] = "unknown command %r" % command

            try:
                send_control_message(conn, response)
            except FrameTransportError as exc:
                self.emit("control_response_failed", classification=exc.classification, error=exc.message)
                return 3

    def _handle_hello(self, message: Dict[str, Any], peer_host: str) -> Dict[str, Any]:
        pc_host = str(message.get("pc_host") or self.args.pc_host or peer_host)
        self.command_sender = CommandUdpSender(pc_host, int(message.get("command_port", self.args.command_port)))
        self.ack_receiver.expected_source_host = pc_host
        self.frame_server.expected_peer_host = pc_host if self.args.pin_peer_host else None
        payload = {
            "run_id": self.run_id,
            "environment": self.environment,
            "protocol": protocol_descriptor(),
            "command_packet_size_bytes": PACKET_SIZE,
            "command_protocol_version": PROTOCOL_VERSION,
            "ack_packet_size_bytes": ACK_PACKET_SIZE,
            "frame_header_size_bytes": FRAME_HEADER_SIZE,
            "frame_port": self.frame_server.port,
            "ack_port": self.ack_receiver.port,
            "pc_host": pc_host,
            "pool_size": self.pool.size,
            "mailbox_depth": 1,
            "jpeg": self.codec.describe(),
        }
        self.emit("control_hello", pc_host=pc_host, command_port=self.command_sender.command_port)
        return payload

    def _handle_start_session(self, message: Dict[str, Any]) -> Dict[str, Any]:
        lease_id = int(message.get("command_lease_id", 0))
        if lease_id == 0:
            return {"ok": False, "error": "command_lease_id must be non-zero"}
        self.session["command_lease_id"] = lease_id
        self.session["lease_expires_pc_us"] = int(message.get("lease_expires_pc_us", 0))
        self.session["session_id"] = str(message.get("session_id", uuid.uuid4().hex))
        self.session["started"] = True
        self.clock = JetsonClockDomain(
            jetson_minus_pc_offset_us=int(message.get("jetson_minus_pc_offset_us", 0)),
            clock_uncertainty_us=int(message.get("clock_uncertainty_us", 0)),
            clock_sync_valid=bool(message.get("clock_sync_valid", False)),
            max_uncertainty_us=int(self.args.max_clock_uncertainty_us),
        )
        self._stop_frames.clear()
        self._frames_done.clear()
        if bool(message.get("start_frame_server", True)) and self._frame_thread is None:
            self._frame_thread = threading.Thread(
                target=self._frame_loop, name="phase13b-frames", daemon=True
            )
            self._frame_thread.start()
        payload = {
            "session_id": self.session["session_id"],
            "command_lease_id": lease_id,
            "clock": self.clock.to_dict(),
            "frame_server_started": self._frame_thread is not None,
        }
        self.emit("session_started", **payload)
        return payload

    def _handle_run_frames(self, message: Dict[str, Any]) -> Dict[str, Any]:
        target = int(message.get("frames", 0))
        timeout_sec = float(message.get("timeout_sec", 120.0))
        self._frames_target = self.flow.frames_processed + target if target else 0
        self._frames_done.clear()
        if target:
            self._frames_done.wait(timeout=timeout_sec)
        payload = {
            "frames_processed": self.flow.frames_processed,
            "frames_received": self.flow.frames_received,
            "frames_decoded": self.flow.frames_decoded,
            "max_mailbox_depth": self.mailbox.max_depth_observed,
            "target_reached": bool(target == 0 or self.flow.frames_processed >= self._frames_target),
        }
        self._frames_target = 0
        self.emit("run_frames_completed", **payload)
        return payload

    def _handle_inject_fault(self, message: Dict[str, Any]) -> Dict[str, Any]:
        name = str(message.get("fault", ""))
        count = int(message.get("count", 1))
        if name not in self.faults:
            return {"ok": False, "error": "unknown jetson fault %r" % name}
        self.faults[name] = count
        self.emit("fault_armed", fault=name, count=count)
        return {"fault": name, "count": count}

    def _handle_heartbeat_commands(self, message: Dict[str, Any]) -> Dict[str, Any]:
        """Emit N valid commands with no frame input (heartbeat/lease keep-alive)."""

        return self.command_ack_stress(int(message.get("count", 1)))


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13B Jetson-in-the-loop node")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--bind-host", default="0.0.0.0")
    parser.add_argument("--frame-port", type=int, default=DEFAULT_FRAME_PORT)
    parser.add_argument("--control-port", type=int, default=DEFAULT_CONTROL_PORT)
    parser.add_argument("--pc-host", default="")
    parser.add_argument("--command-port", type=int, default=DEFAULT_COMMAND_PORT)
    parser.add_argument("--ack-port", type=int, default=DEFAULT_ACK_PORT)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--require-real-jetson", action="store_true")
    parser.add_argument("--run-phase13a-preflight", action="store_true")
    parser.add_argument("--run-arm64-c-gate", action="store_true")
    parser.add_argument("--pool-size", type=int, default=DEFAULT_POOL_SIZE)
    parser.add_argument("--max-payload-bytes", type=int, default=DEFAULT_MAX_PAYLOAD_BYTES)
    parser.add_argument("--jpeg-quality", type=int, default=85)
    parser.add_argument("--diagnostic-throttle", type=float, default=DEFAULT_DIAGNOSTIC_THROTTLE)
    parser.add_argument("--diagnostic-confidence", type=float, default=0.90)
    parser.add_argument("--command-validity-ms", type=int, default=DEFAULT_COMMAND_VALIDITY_MS)
    parser.add_argument("--nominal-result-age-ms", type=float, default=20.0)
    parser.add_argument("--stale-frame-ms", type=float, default=DEFAULT_STALE_FRAME_MS)
    parser.add_argument("--max-clock-uncertainty-us", type=int, default=DEFAULT_MAX_UNCERTAINTY_US)
    parser.add_argument("--ack-timeout-ms", type=int, default=500)
    parser.add_argument("--socket-timeout-sec", type=float, default=10.0)
    parser.add_argument("--frame-timeout-sec", type=float, default=20.0)
    parser.add_argument("--accept-timeout-sec", type=float, default=300.0)
    parser.add_argument("--frame-accept-poll-sec", type=float, default=2.0)
    parser.add_argument("--control-timeout-sec", type=float, default=900.0)
    parser.add_argument("--tegrastats-interval-ms", type=int, default=1000)
    parser.add_argument("--transport-medium", default="usb_gadget_ethernet")
    parser.add_argument("--pin-peer-host", action="store_true")
    # Phase 13C: the default stays `dummy`, so Phase 13B behaviour is unchanged.
    parser.add_argument(
        "--perception-backend", choices=("dummy", "tensorrt"), default="dummy"
    )
    parser.add_argument("--tensorrt-engine", default="")
    parser.add_argument("--tensorrt-profile", default="yolov9-c")
    parser.add_argument("--tensorrt-model-manifest", default="")
    parser.add_argument("--tensorrt-engine-manifest", default="")
    parser.add_argument("--tensorrt-class-names", default="")
    parser.add_argument("--tensorrt-max-inference-ms", type=float, default=1000.0)
    parser.add_argument("--tensorrt-warmup", type=int, default=20)
    # Phase 13D: the precision is a manifest-derived label, and the calibration
    # envelope is what turns the Phase 13C gate into the INT8 gate. Both stay
    # empty/fp16 by default, so Phase 13B and 13C behaviour is unchanged.
    parser.add_argument("--tensorrt-precision", default="fp16")
    parser.add_argument("--int8-calibration-envelope", default="")
    parser.add_argument("--int8-activation-proxy", default="")
    # Phase 13D-MP-RECOVERY freeze: INT8 is experimental_non_authoritative and
    # cannot grant AI_ACTIVE unless this is passed deliberately.
    parser.add_argument("--int8-authoritative", action="store_true")
    parser.add_argument("--require-no-fallback", action="store_true")
    parser.add_argument("--pid-file", default="")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    node = JetsonNode(args)

    if args.pid_file:
        try:
            Path(args.pid_file).write_text("%d\n" % os.getpid(), encoding="utf-8")
        except OSError:
            pass

    if args.require_real_jetson and not node.environment.get("real_jetson_detected", False):
        node.blockers.append("jetson_environment_mismatch")
        node.emit(
            "real_jetson_required_but_not_detected",
            jetson_arch=node.environment.get("jetson_arch"),
            classification="jetson_environment_mismatch",
        )
        node.write_evidence()
        print("Phase 13B Blocked: jetson_environment_mismatch", file=sys.stderr)
        return 2
    if not node.environment.get("jpeg_roundtrip_passed", False):
        node.blockers.append("jpeg_codec_unavailable")
        node.write_evidence()
        print("Phase 13B Blocked: jpeg_codec_unavailable", file=sys.stderr)
        return 2

    if args.perception_backend == "tensorrt" and args.require_no_fallback:
        if node.tensorrt_backend is None:
            node.write_evidence()
            print(
                "Phase 13C Blocked: %s" % (node.tensorrt_error or "tensorrt_backend_unavailable"),
                file=sys.stderr,
            )
            return 2

    if args.run_phase13a_preflight:
        preflight = node.run_phase13a_preflight()
        if not preflight["phase13a_python_preflight_passed"]:
            node.write_evidence()
            print("Phase 13B Blocked: phase13a_preflight_failed", file=sys.stderr)
            return 2
    if args.run_arm64_c_gate:
        gate = node.run_arm64_c_gate()
        if not gate["phase13a_arm64_ctest_passed"]:
            node.write_evidence()
            print("Phase 13B Blocked: arm64_ctest_failed", file=sys.stderr)
            return 2

    return node.serve_control()


if __name__ == "__main__":
    raise SystemExit(main())
