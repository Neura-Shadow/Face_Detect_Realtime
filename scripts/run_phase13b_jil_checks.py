"""Phase 13B Gate B — real Jetson transport checks (simulation PC side).

Drives the whole Jetson-in-the-loop session from the PC:

  control/clock handshake -> C Virtual Safety MCU bring-up -> synthetic JPEG
  frame transport over TCP -> unchanged Phase 13A 64-byte commands over UDP ->
  JILA ACK/status packets -> deterministic fault matrix -> evidence.

The :class:`JilSessionDriver` in this module is shared by the Gate A loopback
checks and the Gate C CARLA simulation host so all three gates exercise the
same production transports and the same C Virtual Safety MCU.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import socket
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from simulation.carla_frame_publisher import CarlaFramePublisher, synthetic_bgr_frame
from simulation.carla_virtual_actuator_bridge import VirtualActuatorBridge
from simulation.virtual_safety_mcu_server import (
    SafetyMcuFfiError,
    SafetyMcuLibrary,
    VirtualSafetyMCUServer,
    build_safety_mcu_library,
    find_safety_mcu_library,
)
from workers.core.clock_sync import (
    DEFAULT_MAX_UNCERTAINTY_US,
    DEFAULT_SAMPLE_COUNT,
    ClockSyncSample,
    estimate_clock_offset,
    monotonic_us,
)
from workers.core.frame_transport import (
    FrameStreamClient,
    FrameTransportError,
    JpegCodec,
    jpeg_codec_preflight,
    recv_control_message,
    send_control_message,
)
from workers.core.jil_protocol import (
    ACK_PACKET_SIZE,
    FRAME_HEADER_SIZE,
    protocol_descriptor,
)
from workers.core.embedded_command_bridge import PACKET_SIZE as COMMAND_PACKET_SIZE
from workers.core.embedded_command_bridge import PROTOCOL_VERSION as COMMAND_PROTOCOL_VERSION
from workers.core.udp_command_transport import AckUdpSender, CommandUdpReceiver

PHASE = "Phase 13B-JETSON-IN-THE-LOOP-BRIDGE"
DEFAULT_OUTPUT_DIR = "experiments/phase13"
DEFAULT_FRAME_PORT = 13510
DEFAULT_CONTROL_PORT = 13513
DEFAULT_COMMAND_PORT = 13511
DEFAULT_ACK_PORT = 13512
DEFAULT_HEARTBEAT_TIMEOUT_MS = 5000
#: Collect more probes than the mandated minimum of 20 so the minimum-RTT
#: estimator has a better chance of catching an un-queued round trip.
DEFAULT_CLOCK_SAMPLES = 40
DEFAULT_CLOCK_WARMUP_PROBES = 5
DEFAULT_CAMERA_WIDTH = 640
DEFAULT_CAMERA_HEIGHT = 360

STATUS_PREPARED = (
    "%s Prepared — source implementation and local loopback gates passed, but real "
    "Jetson transport and CARLA closed-loop execution were not completed." % PHASE
)
STATUS_TRANSPORT_PASS = (
    "%s Transport Pass — real Jetson frame/command/ACK transport and C Virtual Safety "
    "MCU gates passed, but CARLA closed loop was not completed." % PHASE
)
STATUS_PASS = (
    "%s Pass — real Jetson processed simulated CARLA frames, emitted unchanged Phase 13A "
    "command packets, received C Virtual Safety MCU ACK/REJECT responses, and closed the "
    "loop into CARLA virtual actuation." % PHASE
)
STATUS_BLOCKED = (
    "%s Blocked — a required real Jetson, dependency, protocol, network, C FFI, clock, "
    "CARLA, evidence, or actuation gate did not pass." % PHASE
)

BOUNDARY_FIELDS = {
    "physical_actuator_control_executed": False,
    "physical_camera_verified": False,
    "real_mcu_verified": False,
    "real_s32k344_verified": False,
    "full_hil_verified": False,
    "real_can_uart_timing_verified": False,
    "tensorrt_inference_verified": False,
    "model_accuracy_verified": False,
    "route_benchmark_verified": False,
    "infraction_benchmark_verified": False,
    "leaderboard_evaluated": False,
    "physical_vehicle_deployment": False,
    "validation_type": "processor_in_the_loop",
}


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def run_command(command: List[str], *, cwd: Optional[Path] = None, timeout: int = 600) -> Dict[str, Any]:
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


def pc_git_sha() -> str:
    result = run_command(["git", "rev-parse", "HEAD"], timeout=60)
    return result["stdout"].strip() if result["returncode"] == 0 else ""


def detect_pc_source_address(jetson_host: str, *, port: int = 13513) -> Dict[str, Any]:
    """Detect the actual local address used to reach the Jetson.

    Never assumes 192.168.55.100: the address is measured from the routing
    table via a connectionless UDP socket, so a changed route is visible in
    evidence instead of being silently wrong.
    """

    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    detected = ""
    error = None  # type: Optional[str]
    try:
        probe.connect((jetson_host, int(port)))
        detected = probe.getsockname()[0]
    except OSError as exc:
        error = repr(exc)
    finally:
        probe.close()
    return {
        "pc_source_address_detected": detected,
        "pc_source_address_error": error,
        "pc_source_address_assumed": False,
        "jetson_host": jetson_host,
    }


def new_run_id() -> str:
    return "phase13b-%s-%s" % (
        datetime.utcnow().strftime("%Y%m%dT%H%M%SZ"),
        uuid.uuid4().hex[:6],
    )


class ControlChannel:
    """PC side of the Jetson control/clock/metrics TCP channel."""

    def __init__(self, host: str, port: int, *, timeout_sec: float = 900.0) -> None:
        self.host = host
        self.port = int(port)
        self.timeout_sec = float(timeout_sec)
        self._sock = None  # type: Optional[socket.socket]

    def connect(self, *, connect_timeout_sec: float = 30.0) -> None:
        sock = socket.create_connection((self.host, self.port), timeout=connect_timeout_sec)
        sock.settimeout(self.timeout_sec)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock = sock

    def request(self, command: str, **payload: Any) -> Dict[str, Any]:
        if self._sock is None:
            raise FrameTransportError("TRANSPORT_TIMEOUT", "control channel is not connected")
        message = {"command": command}
        message.update(payload)
        send_control_message(self._sock, message)
        return recv_control_message(self._sock, timeout_sec=self.timeout_sec)

    def local_address(self) -> str:
        return str(self._sock.getsockname()[0]) if self._sock is not None else ""

    def close(self) -> None:
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


class FaultCase:
    """One deterministic fault-matrix row."""

    def __init__(
        self,
        fault_id: str,
        fault_name: str,
        gate: str,
        injection_step: str,
        expected_classification: str,
        runner: Callable[[], Tuple[str, Dict[str, Any]]],
    ) -> None:
        self.fault_id = fault_id
        self.fault_name = fault_name
        self.gate = gate
        self.injection_step = injection_step
        self.expected_classification = expected_classification
        self.runner = runner


class JilSessionDriver:
    """Drives a full Phase 13B session against a Jetson node (real or local)."""

    def __init__(
        self,
        *,
        run_id: str,
        jetson_host: str,
        frame_port: int = DEFAULT_FRAME_PORT,
        control_port: int = DEFAULT_CONTROL_PORT,
        command_port: int = DEFAULT_COMMAND_PORT,
        ack_port: int = DEFAULT_ACK_PORT,
        pc_bind_host: str = "0.0.0.0",
        mcu_library_path: Optional[str] = None,
        heartbeat_timeout_ms: int = DEFAULT_HEARTBEAT_TIMEOUT_MS,
        command_validity_ms: int = 500,
        max_clock_uncertainty_us: int = DEFAULT_MAX_UNCERTAINTY_US,
        clock_samples: int = DEFAULT_CLOCK_SAMPLES,
        clock_warmup_probes: int = DEFAULT_CLOCK_WARMUP_PROBES,
        camera_width: int = DEFAULT_CAMERA_WIDTH,
        camera_height: int = DEFAULT_CAMERA_HEIGHT,
        jpeg_quality: int = 85,
        pin_source_host: bool = True,
        auto_build_mcu_library: bool = True,
    ) -> None:
        self.run_id = run_id
        self.jetson_host = jetson_host
        self.frame_port = int(frame_port)
        self.command_port = int(command_port)
        self.ack_port = int(ack_port)
        self.pc_bind_host = pc_bind_host
        self.heartbeat_timeout_us = int(heartbeat_timeout_ms) * 1000
        self.command_validity_ms = int(command_validity_ms)
        self.max_clock_uncertainty_us = int(max_clock_uncertainty_us)
        self.clock_samples = max(DEFAULT_SAMPLE_COUNT, int(clock_samples))
        self.clock_warmup_probes = max(0, int(clock_warmup_probes))
        self.camera_width = int(camera_width)
        self.camera_height = int(camera_height)
        self.pin_source_host = bool(pin_source_host)

        self.events = []  # type: List[Dict[str, Any]]
        self.blockers = []  # type: List[str]
        self.control = ControlChannel(jetson_host, control_port)
        self.jetson_hello = {}  # type: Dict[str, Any]
        self.clock_result = None  # type: Optional[Any]
        self.command_lease_id = 0
        self.session_id = uuid.uuid4().hex

        self.codec = JpegCodec(quality=int(jpeg_quality))
        self.library_report = self._resolve_library(mcu_library_path, auto_build_mcu_library)
        self.library = None  # type: Optional[SafetyMcuLibrary]
        self.server = None  # type: Optional[VirtualSafetyMCUServer]
        self.receiver = None  # type: Optional[CommandUdpReceiver]
        self.ack_sender = None  # type: Optional[AckUdpSender]
        self.frame_client = None  # type: Optional[FrameStreamClient]
        self.publisher = None  # type: Optional[CarlaFramePublisher]
        self.actuator = VirtualActuatorBridge(command_validity_ms=self.command_validity_ms)
        self.fault_rows = []  # type: List[Dict[str, Any]]
        self.pc_address = detect_pc_source_address(jetson_host, port=control_port)
        self.frames_sent = 0
        self.failsafe_recoveries = 0

    # ── setup ───────────────────────────────────────────────────────────────

    def emit(self, event_type: str, **details: Any) -> None:
        event = {
            "timestamp_utc": utc_now_iso(),
            "monotonic_us": monotonic_us(),
            "source": details.pop("source", "pc"),
            "run_id": self.run_id,
            "event_type": event_type,
        }
        event.update(details)
        self.events.append(event)

    def _mcu_event(self, event_type: str, details: Dict[str, Any]) -> None:
        payload = dict(details)
        payload["source"] = "virtual_mcu"
        self.emit(event_type, **payload)

    def _resolve_library(self, explicit: Optional[str], auto_build: bool) -> Dict[str, Any]:
        found = find_safety_mcu_library(explicit)
        report = {"mcu_library_search_explicit": explicit, "mcu_library_auto_build": False}
        if found is None and auto_build and not explicit:
            build = build_safety_mcu_library()
            report["mcu_library_auto_build"] = True
            report["mcu_library_build"] = build
            found = find_safety_mcu_library(None)
        report["mcu_library_resolved_path"] = str(found) if found else None
        return report

    def start_virtual_mcu(self) -> Dict[str, Any]:
        """Load the C library, bind the UDP sockets and bring the FSM to READY."""

        path = self.library_report.get("mcu_library_resolved_path")
        if not path:
            self.blockers.append("virtual_mcu_ffi_failed")
            self.emit("virtual_mcu_library_missing", classification="virtual_mcu_ffi_failed")
            return {"ok": False, "error": "safety MCU FFI shared library not found"}
        try:
            self.library = SafetyMcuLibrary(Path(path))
        except SafetyMcuFfiError as exc:
            self.blockers.append("virtual_mcu_ffi_failed")
            self.emit("virtual_mcu_ffi_error", classification="virtual_mcu_ffi_failed", error=str(exc))
            return {"ok": False, "error": str(exc)}

        expected_source = self.jetson_host if self.pin_source_host else None
        try:
            self.receiver = CommandUdpReceiver(
                self.pc_bind_host,
                self.command_port,
                timeout_sec=0.2,
                expected_source_host=expected_source,
            )
        except OSError as exc:
            self.blockers.append("windows_firewall_or_port_blocked")
            self.emit(
                "command_port_bind_failed",
                classification="windows_firewall_or_port_blocked",
                host=self.pc_bind_host,
                port=self.command_port,
                error=repr(exc),
            )
            return {"ok": False, "error": repr(exc)}

        self.ack_sender = AckUdpSender(self.jetson_host, self.ack_port)
        self.server = VirtualSafetyMCUServer(
            library=self.library,
            receiver=self.receiver,
            ack_sender=self.ack_sender,
            heartbeat_timeout_us=self.heartbeat_timeout_us,
            event_sink=self._mcu_event,
        )
        self.command_lease_id = (uuid.uuid4().int & 0x7FFFFFFF) or 0x13B00001
        bootstrap = self.server.bootstrap(
            lease_id=self.command_lease_id,
            lease_expires_us=monotonic_us() + 3_600_000_000,
        )
        self.server.start(poll_timeout_sec=0.05)
        payload = {"ok": True, "lease": bootstrap}
        payload.update(self.library.describe())
        return payload

    def ensure_ready(self) -> bool:
        """Recover explicitly if the C watchdog moved the FSM into FAILSAFE."""

        if self.server is None or self.library is None:
            return False
        state = self.library.get_state(self.server.handle)
        if state == 5:  # FAILSAFE
            self.server.recover_from_failsafe(
                lease_id=self.command_lease_id,
                lease_expires_us=monotonic_us() + 3_600_000_000,
            )
            self.failsafe_recoveries += 1
            self.emit("virtual_mcu_explicit_failsafe_recovery", previous_state=state)
            self.control.request("inject_fault", fault="stop_heartbeat", count=0)
            return True
        return False

    def connect_control(self, *, connect_timeout_sec: float = 60.0) -> Dict[str, Any]:
        self.control.connect(connect_timeout_sec=connect_timeout_sec)
        local = self.control.local_address()
        self.pc_address["pc_source_address_control_channel"] = local
        hello = self.control.request(
            "hello",
            run_id=self.run_id,
            pc_host=local,
            command_port=self.command_port,
            ack_port=self.ack_port,
            command_packet_size_bytes=COMMAND_PACKET_SIZE,
            command_protocol_version=COMMAND_PROTOCOL_VERSION,
            ack_packet_size_bytes=ACK_PACKET_SIZE,
            frame_header_size_bytes=FRAME_HEADER_SIZE,
        )
        self.jetson_hello = hello
        self.emit("control_handshake", jetson_run_id=hello.get("run_id"), pc_source_address=local)
        return hello

    def synchronise_clocks(self) -> Dict[str, Any]:
        # Warm-up probes are discarded: the first round trips on a freshly
        # established TCP connection pay connection-setup and interpreter
        # warm-up costs that are not representative of the link.
        for index in range(self.clock_warmup_probes):
            self.control.request("clock_probe", sample_index=-1 - index)

        samples = []  # type: List[ClockSyncSample]
        for index in range(self.clock_samples):
            t1 = monotonic_us()
            response = self.control.request("clock_probe", sample_index=index)
            t4 = monotonic_us()
            samples.append(
                ClockSyncSample(
                    t1_pc_send_us=t1,
                    t2_jetson_recv_us=int(response.get("t2_jetson_recv_us", 0)),
                    t3_jetson_send_us=int(response.get("t3_jetson_send_us", 0)),
                    t4_pc_recv_us=t4,
                )
            )
        result = estimate_clock_offset(
            samples,
            max_uncertainty_us=self.max_clock_uncertainty_us,
            min_sample_count=min(self.clock_samples, DEFAULT_SAMPLE_COUNT),
        )
        self.clock_result = result
        payload = result.to_dict()
        payload["clock_samples"] = [sample.to_dict() for sample in samples]
        self.emit("clock_sync_completed", **result.to_dict())
        if not result.clock_sync_valid:
            self.blockers.append("clock_sync_failed")
        return payload

    def start_session(self, *, start_frame_server: bool = True) -> Dict[str, Any]:
        if self.clock_result is None:
            raise RuntimeError("clock sync must run before start_session")
        response = self.control.request(
            "start_session",
            session_id=self.session_id,
            command_lease_id=self.command_lease_id,
            lease_expires_pc_us=monotonic_us() + 3_600_000_000,
            jetson_minus_pc_offset_us=self.clock_result.jetson_minus_pc_offset_us,
            clock_uncertainty_us=self.clock_result.clock_uncertainty_us,
            clock_sync_valid=self.clock_result.clock_sync_valid,
            start_frame_server=start_frame_server,
        )
        self.emit("session_started", **{k: v for k, v in response.items() if k != "ok"})
        return response

    def connect_frames(self, *, retries: int = 20, delay_sec: float = 0.5) -> bool:
        self.frame_client = FrameStreamClient(
            self.jetson_host, self.frame_port, timeout_sec=10.0
        )
        for _ in range(retries):
            try:
                self.frame_client.connect()
                break
            except OSError:
                time.sleep(delay_sec)
        if not self.frame_client.connected:
            self.blockers.append("frame_transport_failed")
            self.emit(
                "frame_client_connect_failed",
                classification="frame_transport_failed",
                host=self.jetson_host,
                port=self.frame_port,
            )
            return False
        self.publisher = CarlaFramePublisher(
            self.frame_client,
            codec=self.codec,
            width=self.camera_width,
            height=self.camera_height,
        )
        self.emit("frame_client_connected", host=self.jetson_host, port=self.frame_port)
        return True

    def reconnect_frames(self) -> bool:
        if self.frame_client is None:
            return False
        self.frame_client.close()
        for _ in range(40):
            try:
                self.frame_client.connect()
                return True
            except OSError:
                time.sleep(0.25)
        return False

    # ── frame publishing ────────────────────────────────────────────────────

    def publish_synthetic_frames(
        self,
        count: int,
        *,
        interval_sec: float = 0.0,
        wait_timeout_sec: float = 240.0,
    ) -> Dict[str, Any]:
        """Publish ``count`` synthetic JPEG frames through the production path."""

        if self.publisher is None:
            return {"ok": False, "error": "frame publisher is not connected"}
        started = monotonic_us()
        for index in range(int(count)):
            frame = synthetic_bgr_frame(self.camera_width, self.camera_height, frame_index=index)
            result = self.publisher.publish_bgra(
                self._as_bgra(frame),
                simulation_timestamp_us=started + index * 100_000,
            )
            if result.published:
                self.frames_sent += 1
            if interval_sec:
                time.sleep(interval_sec)
        response = self.control.request(
            "run_frames", frames=0, timeout_sec=wait_timeout_sec
        )
        # Give the Jetson pipeline a bounded drain window before reading metrics.
        deadline = time.time() + wait_timeout_sec
        while time.time() < deadline:
            status = self.control.request("run_frames", frames=0, timeout_sec=1.0)
            if int(status.get("frames_processed", 0)) >= self.frames_sent:
                response = status
                break
            time.sleep(0.2)
        payload = {
            "frames_sent": self.frames_sent,
            "frames_processed": int(response.get("frames_processed", 0)),
            "frames_received": int(response.get("frames_received", 0)),
            "frames_decoded": int(response.get("frames_decoded", 0)),
            "max_mailbox_depth": int(response.get("max_mailbox_depth", 0)),
            "publish_duration_ms": round((monotonic_us() - started) / 1000.0, 3),
        }
        self.emit("synthetic_frames_published", **payload)
        return payload

    @staticmethod
    def _as_bgra(bgr: Any) -> Any:
        import numpy as np

        height, width = bgr.shape[0], bgr.shape[1]
        bgra = np.empty((height, width, 4), dtype=np.uint8)
        bgra[:, :, :3] = bgr
        bgra[:, :, 3] = 255
        return bgra

    # ── command / ACK stress ────────────────────────────────────────────────

    def command_ack_stress(self, cycles: int) -> Dict[str, Any]:
        self.ensure_ready()
        response = self.control.request("command_ack_stress", cycles=int(cycles))
        self.emit("command_ack_stress", **{k: v for k, v in response.items() if k != "ok"})
        return response

    # ── fault matrix ────────────────────────────────────────────────────────

    def _jetson_metrics(self) -> Dict[str, Any]:
        response = self.control.request("get_metrics")
        return dict(response.get("metrics", {}))

    def _single_jetson_command(self, fault: Optional[str] = None, count: int = 1) -> str:
        """Arm an optional Jetson-side fault and emit exactly one command."""

        if fault:
            self.control.request("inject_fault", fault=fault, count=count)
        before = self._jetson_metrics()
        self.control.request("send_heartbeat_commands", count=1)
        after = self._jetson_metrics()
        before_counts = dict(before.get("command_classifications", {}))
        after_counts = dict(after.get("command_classifications", {}))
        for name, value in after_counts.items():
            if value > before_counts.get(name, 0):
                return name
        return "NO_OBSERVATION"

    def _publish_one_frame(self, *, frame_index: int = 9991) -> Any:
        frame = synthetic_bgr_frame(self.camera_width, self.camera_height, frame_index=frame_index)
        return self.publisher.publish_bgra(self._as_bgra(frame))

    def _frame_fault_observation(self, arm: Callable[[], None]) -> Tuple[str, Dict[str, Any]]:
        """Inject one frame-transport fault and read back the Jetson reject counters."""

        if self.publisher is None:
            return "NO_OBSERVATION", {"error": "frame publisher unavailable"}
        before = self._jetson_metrics().get("frame_reject_counts", {})
        arm()
        result = self._publish_one_frame()
        reconnected = False
        if result.requires_reconnect:
            time.sleep(0.4)
            reconnected = self.reconnect_frames()
        time.sleep(0.6)
        after = self._jetson_metrics().get("frame_reject_counts", {})
        observed = "NO_OBSERVATION"
        for name, value in after.items():
            if value > before.get(name, 0):
                observed = name
                break
        return observed, {
            "injected_fault": result.fault,
            "reconnected": reconnected,
            "reject_counts_before": before,
            "reject_counts_after": after,
        }

    @staticmethod
    def _derive_pipeline_classification(before: Dict[str, Any], after: Dict[str, Any]) -> str:
        """Classify one frame-pipeline outcome from the Jetson metric deltas."""

        before_counts = dict(before.get("command_classifications", {}))
        after_counts = dict(after.get("command_classifications", {}))
        increased = [
            name for name, value in after_counts.items() if value > before_counts.get(name, 0)
        ]
        rejected = [name for name in increased if name != "ACCEPTED"]
        if rejected:
            return sorted(rejected)[0]
        safe_stop_delta = int(after.get("safe_stop_command_count", 0)) - int(
            before.get("safe_stop_command_count", 0)
        )
        if safe_stop_delta > 0:
            return "SAFE_STOP"
        if "ACCEPTED" in increased:
            return "ACCEPTED"
        return "NO_OBSERVATION"

    def _frame_pipeline_fault_observation(
        self,
        *,
        jetson_fault: Optional[str] = None,
        publisher_attribute: Optional[str] = None,
        timeout_sec: float = 15.0,
    ) -> Tuple[str, Dict[str, Any]]:
        """Arm a Jetson pipeline fault, publish one frame and read the outcome.

        Range, clock and stale-frame faults only exist inside the frame
        pipeline, so they must be injected against a real published frame
        rather than a bare command.
        """

        if self.publisher is None:
            return "NO_OBSERVATION", {"error": "frame publisher unavailable"}
        before = self._jetson_metrics()
        if jetson_fault:
            self.control.request("inject_fault", fault=jetson_fault, count=1)
        if publisher_attribute:
            setattr(self.publisher.faults, publisher_attribute, 1)
        result = self._publish_one_frame()
        deadline = time.time() + timeout_sec
        after = before
        while time.time() < deadline:
            time.sleep(0.2)
            after = self._jetson_metrics()
            if int(after.get("commands_sent", 0)) > int(before.get("commands_sent", 0)):
                break
        observed = self._derive_pipeline_classification(before, after)
        return observed, {
            "jetson_fault": jetson_fault,
            "publisher_fault": result.fault,
            "commands_sent_before": before.get("commands_sent"),
            "commands_sent_after": after.get("commands_sent"),
            "safe_stop_before": before.get("safe_stop_command_count"),
            "safe_stop_after": after.get("safe_stop_command_count"),
            "stale_frame_reject_before": before.get("stale_frame_reject_count"),
            "stale_frame_reject_after": after.get("stale_frame_reject_count"),
            "range_state_counts_after": after.get("range_state_counts"),
        }

    def build_fault_cases(self, gate: str) -> List[FaultCase]:
        """Deterministic, one-at-a-time fault cases for the given gate."""

        cases = []  # type: List[FaultCase]

        def command_case(
            fault_id: str,
            name: str,
            step: str,
            expected: str,
            jetson_fault: Optional[str] = None,
            pc_setup: Optional[Callable[[], None]] = None,
            pc_teardown: Optional[Callable[[], None]] = None,
        ) -> FaultCase:
            def runner() -> Tuple[str, Dict[str, Any]]:
                self.ensure_ready()
                if pc_setup is not None:
                    pc_setup()
                try:
                    observed = self._single_jetson_command(jetson_fault)
                finally:
                    if pc_teardown is not None:
                        pc_teardown()
                return observed, {"jetson_fault": jetson_fault}

            return FaultCase(fault_id, name, gate, step, expected, runner)

        cases.append(command_case("F01", "valid command", "command_path", "ACCEPTED"))
        cases.append(
            command_case("F02", "corrupt command CRC", "command_path", "CRC_REJECT", "corrupt_command_crc")
        )
        cases.append(
            command_case("F03", "duplicate command", "command_path", "SEQUENCE_REJECT", "duplicate_command")
        )
        cases.append(
            command_case(
                "F04", "out-of-order command", "command_path", "SEQUENCE_REJECT", "out_of_order_command"
            )
        )
        cases.append(
            command_case(
                "F05", "delay command beyond valid_until", "command_path", "STALE_REJECT", "expired_command"
            )
        )
        cases.append(
            command_case("F06", "wrong lease", "command_path", "LEASE_REJECT", "wrong_lease_command")
        )

        def expire_lease() -> None:
            if self.server is not None:
                self.server.refresh_lease(self.command_lease_id, max(0, monotonic_us() - 1_000_000))

        def restore_lease() -> None:
            if self.server is not None:
                self.server.refresh_lease(self.command_lease_id, monotonic_us() + 3_600_000_000)

        cases.append(
            command_case(
                "F07",
                "expired lease",
                "command_path",
                "LEASE_REJECT",
                None,
                pc_setup=expire_lease,
                pc_teardown=restore_lease,
            )
        )
        cases.append(
            command_case("F08", "drop command", "command_path", "TRANSPORT_TIMEOUT", "drop_command")
        )

        def drop_ack() -> None:
            if self.server is not None:
                self.server.faults.drop_next_ack = 1

        def corrupt_ack() -> None:
            if self.server is not None:
                self.server.faults.corrupt_next_ack_crc = 1

        cases.append(
            command_case("F09", "drop ACK", "ack_path", "TRANSPORT_TIMEOUT", None, pc_setup=drop_ack)
        )
        cases.append(
            command_case("F10", "ACK CRC corruption", "ack_path", "CRC_REJECT", None, pc_setup=corrupt_ack)
        )

        def force_ack_sequence_mismatch() -> None:
            if self.server is not None:
                self.server.faults.force_ack_sequence = 0xFFFF0000

        cases.append(
            command_case(
                "F11",
                "ACK sequence mismatch",
                "ack_path",
                "SEQUENCE_REJECT",
                None,
                pc_setup=force_ack_sequence_mismatch,
            )
        )

        def force_stale_ack() -> None:
            if self.server is not None:
                self.server.faults.force_ack_sequence = 1

        cases.append(
            command_case(
                "F12",
                "stale ACK",
                "ack_path",
                "STALE_REJECT",
                "ack_sequence_unchecked",
                pc_setup=force_stale_ack,
            )
        )

        def unexpected_sender_on() -> None:
            if self.receiver is not None:
                self.receiver.expected_source_host = "203.0.113.255"

        def unexpected_sender_off() -> None:
            if self.receiver is not None:
                self.receiver.expected_source_host = self.jetson_host if self.pin_source_host else None

        cases.append(
            command_case(
                "F13",
                "unexpected sender",
                "command_path",
                "TRANSPORT_TIMEOUT",
                None,
                pc_setup=unexpected_sender_on,
                pc_teardown=unexpected_sender_off,
            )
        )

        def heartbeat_runner() -> Tuple[str, Dict[str, Any]]:
            self.ensure_ready()
            self.control.request("inject_fault", fault="stop_heartbeat", count=1)
            deadline = time.time() + (self.heartbeat_timeout_us / 1_000_000.0) + 2.0
            state = 0
            while time.time() < deadline:
                state = self.server.tick() if self.server is not None else 0
                if state == 5:
                    break
                time.sleep(0.2)
            observed = "FAILSAFE" if state == 5 else "NO_OBSERVATION"
            self.control.request("inject_fault", fault="stop_heartbeat", count=0)
            if self.server is not None and state == 5:
                self.server.recover_from_failsafe(
                    lease_id=self.command_lease_id,
                    lease_expires_us=monotonic_us() + 3_600_000_000,
                )
                self.failsafe_recoveries += 1
            return observed, {"mcu_state": state, "explicit_recovery": state == 5}

        cases.append(
            FaultCase(
                "F14",
                "stop heartbeat",
                gate,
                "watchdog",
                "FAILSAFE",
                heartbeat_runner,
            )
        )

        def pipeline_case(
            fault_id: str,
            name: str,
            step: str,
            expected: str,
            jetson_fault: Optional[str] = None,
            publisher_attribute: Optional[str] = None,
        ) -> FaultCase:
            def runner() -> Tuple[str, Dict[str, Any]]:
                self.ensure_ready()
                return self._frame_pipeline_fault_observation(
                    jetson_fault=jetson_fault, publisher_attribute=publisher_attribute
                )

            return FaultCase(fault_id, name, gate, step, expected, runner)

        cases.append(
            pipeline_case("F15", "NaN/Inf frame input", "range_path", "SAFE_STOP", "nan_frame")
        )
        cases.append(
            pipeline_case("F16", "invalid input range", "range_path", "SAFE_STOP", "black_frame")
        )
        cases.append(
            pipeline_case(
                "F17", "BGR/RGB contract mismatch", "range_path", "SAFE_STOP", "color_order_mismatch"
            )
        )
        cases.append(
            pipeline_case("F18", "stale AI result age", "range_path", "RANGE_REJECT", "stale_result_age")
        )
        cases.append(
            pipeline_case(
                "F19", "clock uncertainty violation", "clock_path", "SAFE_STOP", "force_clock_degraded"
            )
        )
        cases.append(
            pipeline_case(
                "F28",
                "stale frame",
                "frame_path",
                "SAFE_STOP",
                None,
                publisher_attribute="stale_timestamp",
            )
        )

        # ── frame-path faults ───────────────────────────────────────────────
        def frame_case(
            fault_id: str, name: str, expected: str, arm: Callable[[], None]
        ) -> FaultCase:
            def runner() -> Tuple[str, Dict[str, Any]]:
                return self._frame_fault_observation(arm)

            return FaultCase(fault_id, name, gate, "frame_path", expected, runner)

        def arm(attribute: str) -> Callable[[], None]:
            def setter() -> None:
                if self.publisher is not None:
                    setattr(self.publisher.faults, attribute, 1)

            return setter

        cases.append(
            frame_case("F20", "frame payload CRC corruption", "FRAME_CRC_REJECT", arm("corrupt_payload_crc"))
        )
        cases.append(
            frame_case("F21", "oversized frame payload", "FRAME_SIZE_REJECT", arm("oversized_payload"))
        )
        cases.append(
            frame_case("F22", "invalid frame dimensions", "FRAME_SIZE_REJECT", arm("invalid_dimensions"))
        )
        cases.append(
            frame_case("F23", "unsupported frame codec", "FRAME_CODEC_REJECT", arm("unsupported_codec"))
        )
        cases.append(
            frame_case(
                "F24", "unsupported frame version", "FRAME_PROTOCOL_REJECT", arm("unsupported_version")
            )
        )
        cases.append(
            frame_case("F25", "zero-size frame payload", "FRAME_SIZE_REJECT", arm("zero_payload"))
        )
        cases.append(
            frame_case(
                "F26", "partial TCP payload / early disconnect", "TRANSPORT_TIMEOUT", arm("partial_payload")
            )
        )

        def transport_disconnect_runner() -> Tuple[str, Dict[str, Any]]:
            before = self._jetson_metrics()
            if self.frame_client is not None:
                self.frame_client.close()
            time.sleep(0.6)
            reconnected = self.reconnect_frames()
            time.sleep(0.6)
            after = self._jetson_metrics()
            observed = (
                "TRANSPORT_TIMEOUT"
                if int(after.get("frame_server_accept_count", 0))
                > int(before.get("frame_server_accept_count", 0))
                else "NO_OBSERVATION"
            )
            return observed, {
                "reconnected": reconnected,
                "accept_count_before": before.get("frame_server_accept_count"),
                "accept_count_after": after.get("frame_server_accept_count"),
            }

        cases.append(
            FaultCase(
                "F27",
                "TCP transport disconnect and reconnect",
                gate,
                "frame_path",
                "TRANSPORT_TIMEOUT",
                transport_disconnect_runner,
            )
        )
        return cases

    def run_fault_matrix(self, gate: str) -> Dict[str, Any]:
        cases = self.build_fault_cases(gate)
        rows = []  # type: List[Dict[str, Any]]
        false_accept = 0
        false_reject = 0
        for case in cases:
            try:
                observed, details = case.runner()
            except Exception as exc:  # pragma: no cover - runtime robustness
                observed, details = "RUNNER_ERROR", {"error": repr(exc)}
            passed = observed == case.expected_classification
            if not passed:
                if case.expected_classification == "ACCEPTED" and observed != "ACCEPTED":
                    false_reject += 1
                elif case.expected_classification != "ACCEPTED" and observed == "ACCEPTED":
                    false_accept += 1
            row = {
                "fault_id": case.fault_id,
                "fault_name": case.fault_name,
                "gate": case.gate,
                "injection_step": case.injection_step,
                "expected_classification": case.expected_classification,
                "observed_classification": observed,
                "passed": passed,
                "details": json.dumps(details, ensure_ascii=False, sort_keys=True),
            }
            rows.append(row)
            self.emit("fault_case_completed", **row)
        self.fault_rows = rows
        payload = {
            "fault_case_count": len(rows),
            "fault_case_passed_count": sum(1 for row in rows if row["passed"]),
            "fault_matrix_passed": all(row["passed"] for row in rows),
            "false_accept_count": false_accept,
            "false_reject_count": false_reject,
        }
        self.emit("fault_matrix_completed", **payload)
        return payload

    # ── teardown / evidence ─────────────────────────────────────────────────

    def collect_jetson_evidence(self) -> Dict[str, Any]:
        metrics = self._jetson_metrics()
        try:
            events = self.control.request("get_events").get("events", [])
        except FrameTransportError:
            events = []
        return {"metrics": metrics, "events": events}

    def shutdown(self) -> None:
        try:
            self.control.request("shutdown")
        except Exception:
            pass
        self.control.close()
        if self.frame_client is not None:
            self.frame_client.close()
        if self.server is not None:
            self.server.close()
        if self.receiver is not None:
            self.receiver.close()
        if self.ack_sender is not None:
            self.ack_sender.close()

    def pc_metrics(self) -> Dict[str, Any]:
        payload = {
            "run_id": self.run_id,
            "phase": PHASE,
            "source": "pc",
            "pc_frames_sent": self.frames_sent,
            "pc_failsafe_recoveries": self.failsafe_recoveries,
            "command_lease_id": self.command_lease_id,
            "session_id": self.session_id,
            "heartbeat_timeout_us": self.heartbeat_timeout_us,
            "command_validity_ms": self.command_validity_ms,
        }
        payload.update(self.pc_address)
        payload.update(self.library_report)
        if self.publisher is not None:
            payload.update(self.publisher.metrics())
        if self.server is not None:
            payload.update(self.server.metrics())
        payload.update(self.actuator.metrics())
        if self.clock_result is not None:
            payload.update(self.clock_result.to_dict())
        payload.update(protocol_descriptor())
        payload["blockers"] = list(self.blockers)
        return payload


class EvidenceWriter:
    """Writes the Phase 13B PC evidence tree."""

    def __init__(self, output_dir: Path, run_id: str) -> None:
        root = Path(output_dir)
        if not root.is_absolute():
            root = REPO_ROOT / root
        self.run_dir = root / run_id
        (self.run_dir / "raw_outputs").mkdir(parents=True, exist_ok=True)
        self.run_id = run_id

    def write_json(self, name: str, payload: Any) -> None:
        (self.run_dir / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8"
        )

    def write_events(self, events: List[Dict[str, Any]]) -> None:
        (self.run_dir / "events.jsonl").write_text(
            "".join(json.dumps(event, ensure_ascii=False, default=str) + "\n" for event in events),
            encoding="utf-8",
        )

    def write_fault_matrix(self, rows: List[Dict[str, Any]]) -> None:
        self.write_json("fault_matrix.json", rows)
        columns = [
            "fault_id",
            "fault_name",
            "gate",
            "injection_step",
            "expected_classification",
            "observed_classification",
            "passed",
            "details",
        ]
        with open(str(self.run_dir / "fault_matrix.csv"), "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: row.get(key, "") for key in columns})

    def write_text(self, name: str, text: str) -> None:
        (self.run_dir / name).write_text(text, encoding="utf-8")

    def write_raw(self, name: str, text: str) -> None:
        (self.run_dir / "raw_outputs" / name).write_text(text, encoding="utf-8")


def pc_environment(args: argparse.Namespace) -> Dict[str, Any]:
    payload = {
        "hostname": socket.gethostname(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "arch": platform.machine(),
        "runtime_pc_git_sha": pc_git_sha(),
        "repository_root": str(REPO_ROOT),
        "transport_medium": args.transport_medium,
        "cwd": os.getcwd(),
    }
    payload.update(jpeg_codec_preflight())
    try:
        import numpy

        payload["numpy_version"] = numpy.__version__
    except Exception as exc:  # pragma: no cover
        payload["numpy_version"] = "MISSING: %r" % (exc,)
    return payload


def firewall_guidance(args: argparse.Namespace) -> List[str]:
    """Exact operator commands. These are printed, never executed."""

    return [
        "# Windows inbound rules required by Phase 13B (run as Administrator).",
        "# Claude Code does not modify the Windows firewall, ICS, or Jetson firewall.",
        'netsh advfirewall firewall add rule name="MA-VLNA Phase13B command UDP %d" '
        "dir=in action=allow protocol=UDP localport=%d" % (args.command_port, args.command_port),
        "# The frame (TCP %d), control (TCP %d) and ACK (UDP %d) listeners run on the Jetson;"
        % (args.frame_port, args.control_port, args.ack_port),
        "# only the PC command listener needs an inbound Windows rule.",
    ]


def build_arg_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--jetson-host", default="192.168.55.1")
    parser.add_argument("--frame-port", type=int, default=DEFAULT_FRAME_PORT)
    parser.add_argument("--control-port", type=int, default=DEFAULT_CONTROL_PORT)
    parser.add_argument("--command-port", type=int, default=DEFAULT_COMMAND_PORT)
    parser.add_argument("--ack-port", type=int, default=DEFAULT_ACK_PORT)
    parser.add_argument("--pc-bind-host", default="0.0.0.0")
    parser.add_argument("--mcu-library", default="")
    parser.add_argument("--heartbeat-timeout-ms", type=int, default=DEFAULT_HEARTBEAT_TIMEOUT_MS)
    parser.add_argument("--command-validity-ms", type=int, default=500)
    parser.add_argument("--diagnostic-throttle", type=float, default=0.20)
    parser.add_argument("--clock-samples", type=int, default=DEFAULT_CLOCK_SAMPLES)
    parser.add_argument(
        "--clock-warmup-probes", type=int, default=DEFAULT_CLOCK_WARMUP_PROBES
    )
    parser.add_argument("--max-clock-uncertainty-us", type=int, default=DEFAULT_MAX_UNCERTAINTY_US)
    parser.add_argument("--camera-width", type=int, default=DEFAULT_CAMERA_WIDTH)
    parser.add_argument("--camera-height", type=int, default=DEFAULT_CAMERA_HEIGHT)
    parser.add_argument("--jpeg-quality", type=int, default=85)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--transport-medium", default="usb_gadget_ethernet")
    parser.add_argument("--require-real-jetson", action="store_true")
    parser.add_argument("--no-pin-source-host", action="store_true")
    return parser


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = build_arg_parser("Phase 13B Gate B real Jetson transport checks")
    parser.add_argument("--synthetic-frames", type=int, default=300)
    parser.add_argument("--command-ack-cycles", type=int, default=1000)
    parser.add_argument("--frame-interval-sec", type=float, default=0.0)
    parser.add_argument("--skip-fault-matrix", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    run_id = args.run_id or new_run_id()
    evidence = EvidenceWriter(Path(args.output_dir), run_id)
    environment = pc_environment(args)

    driver = JilSessionDriver(
        run_id=run_id,
        jetson_host=args.jetson_host,
        frame_port=args.frame_port,
        control_port=args.control_port,
        command_port=args.command_port,
        ack_port=args.ack_port,
        pc_bind_host=args.pc_bind_host,
        mcu_library_path=args.mcu_library or None,
        heartbeat_timeout_ms=args.heartbeat_timeout_ms,
        command_validity_ms=args.command_validity_ms,
        max_clock_uncertainty_us=args.max_clock_uncertainty_us,
        clock_samples=args.clock_samples,
        clock_warmup_probes=args.clock_warmup_probes,
        camera_width=args.camera_width,
        camera_height=args.camera_height,
        jpeg_quality=args.jpeg_quality,
        pin_source_host=not args.no_pin_source_host,
    )

    summary = {
        "phase": PHASE,
        "gate": "B",
        "run_id": run_id,
        "created_at_utc": utc_now_iso(),
        "transport_medium": args.transport_medium,
    }  # type: Dict[str, Any]
    jetson_evidence = {"metrics": {}, "events": []}  # type: Dict[str, Any]
    status = STATUS_BLOCKED
    exit_code = 1

    try:
        mcu = driver.start_virtual_mcu()
        summary["virtual_mcu"] = mcu
        if not mcu.get("ok"):
            raise RuntimeError("virtual safety MCU could not start")

        hello = driver.connect_control()
        jetson_env = dict(hello.get("environment", {}))
        summary["jetson_environment"] = jetson_env
        if args.require_real_jetson and not jetson_env.get("real_jetson_detected", False):
            driver.blockers.append("jetson_environment_mismatch")
            raise RuntimeError("real Jetson required but not detected")

        runtime_pc_sha = environment.get("runtime_pc_git_sha", "")
        runtime_jetson_sha = jetson_env.get("runtime_jetson_git_sha", "")
        sha_match = bool(runtime_pc_sha) and runtime_pc_sha == runtime_jetson_sha
        summary["runtime_pc_git_sha"] = runtime_pc_sha
        summary["runtime_jetson_git_sha"] = runtime_jetson_sha
        summary["runtime_git_sha_match"] = sha_match
        if args.require_real_jetson and not sha_match:
            driver.blockers.append("git_sha_mismatch")
            raise RuntimeError("runtime git SHA mismatch between PC and Jetson")

        summary["clock"] = driver.synchronise_clocks()
        driver.start_session(start_frame_server=True)
        if not driver.connect_frames():
            raise RuntimeError("frame transport could not be established")

        frames = driver.publish_synthetic_frames(
            int(args.synthetic_frames), interval_sec=float(args.frame_interval_sec)
        )
        summary["frames"] = frames

        stress = driver.command_ack_stress(int(args.command_ack_cycles))
        summary["command_ack_stress"] = stress

        if not args.skip_fault_matrix:
            summary["fault_matrix"] = driver.run_fault_matrix("B")
        else:
            summary["fault_matrix"] = {"fault_matrix_passed": False, "skipped": True}

        jetson_evidence = driver.collect_jetson_evidence()
        jetson_metrics = jetson_evidence["metrics"]

        gate_b = {
            "gate_b_frames_sent": driver.frames_sent,
            "gate_b_frames_received": int(jetson_metrics.get("frames_received", 0)),
            "gate_b_frames_decoded": int(jetson_metrics.get("frames_decoded", 0)),
            "gate_b_frames_processed": int(jetson_metrics.get("frames_processed", 0)),
            "gate_b_transport_packets_sent": int(jetson_metrics.get("commands_sent", 0)),
            "gate_b_valid_acks_received": int(jetson_metrics.get("valid_acks_received", 0)),
            "gate_b_command_accept_count": int(
                driver.server.command_accept_count if driver.server else 0
            ),
            "gate_b_command_reject_count": int(
                driver.server.command_reject_count if driver.server else 0
            ),
            "gate_b_max_mailbox_depth": int(jetson_metrics.get("max_mailbox_depth", 0)),
            "gate_b_fault_matrix_passed": bool(summary["fault_matrix"].get("fault_matrix_passed")),
            "gate_b_false_accept_count": int(summary["fault_matrix"].get("false_accept_count", 0)),
            "gate_b_false_reject_count": int(summary["fault_matrix"].get("false_reject_count", 0)),
        }
        summary["gate_b"] = gate_b

        transport_pass = (
            gate_b["gate_b_frames_sent"] >= 300
            and gate_b["gate_b_frames_received"] >= 300
            and gate_b["gate_b_frames_decoded"] > 0
            and gate_b["gate_b_frames_processed"] > 0
            and gate_b["gate_b_max_mailbox_depth"] == 1
            and gate_b["gate_b_transport_packets_sent"] >= 1000
            and gate_b["gate_b_valid_acks_received"] >= 990
            and gate_b["gate_b_command_accept_count"] > 0
            and gate_b["gate_b_fault_matrix_passed"]
            and gate_b["gate_b_false_accept_count"] == 0
            and gate_b["gate_b_false_reject_count"] == 0
            and not driver.blockers
        )
        summary["gate_b_transport_pass"] = transport_pass
        status = STATUS_TRANSPORT_PASS if transport_pass else STATUS_BLOCKED
        exit_code = 0 if transport_pass else 1
    except Exception as exc:
        summary["error"] = repr(exc)
        driver.emit("gate_b_error", error=repr(exc))
    finally:
        summary["status"] = status
        summary["blockers"] = list(driver.blockers)
        summary["pc_environment"] = environment
        summary.update(BOUNDARY_FIELDS)
        pc_metrics = driver.pc_metrics()
        evidence.write_json("summary.json", summary)
        evidence.write_json("pc_metrics.json", pc_metrics)
        evidence.write_json("jetson_metrics.json", jetson_evidence.get("metrics", {}))
        evidence.write_json(
            "network_metrics.json",
            {
                "transport_medium": args.transport_medium,
                "jetson_host": args.jetson_host,
                "frame_port": args.frame_port,
                "control_port": args.control_port,
                "command_port": args.command_port,
                "ack_port": args.ack_port,
                "pc_source_address": driver.pc_address,
                "clock": driver.clock_result.to_dict() if driver.clock_result else None,
                "command_rtt_ms_mean": jetson_evidence.get("metrics", {}).get("command_rtt_ms_mean"),
                "frame_one_way_latency_ms_mean": jetson_evidence.get("metrics", {}).get(
                    "frame_one_way_latency_ms_mean"
                ),
            },
        )
        evidence.write_json("environment.json", environment)
        evidence.write_fault_matrix(driver.fault_rows)
        evidence.write_events(driver.events + list(jetson_evidence.get("events", [])))
        evidence.write_json(
            "manifest.json",
            {
                "phase": PHASE,
                "gate": "B",
                "run_id": run_id,
                "status": status,
                "created_at_utc": utc_now_iso(),
                "evidence_dir": str(evidence.run_dir),
                "generated_evidence_git_policy": "ignored_local_only",
                "output_files": [
                    "manifest.json",
                    "summary.json",
                    "events.jsonl",
                    "pc_metrics.json",
                    "jetson_metrics.json",
                    "network_metrics.json",
                    "fault_matrix.json",
                    "fault_matrix.csv",
                    "commands.txt",
                    "environment.json",
                    "README.md",
                    "raw_outputs/",
                ],
                **BOUNDARY_FIELDS,
            },
        )
        evidence.write_text(
            "commands.txt",
            "# Phase 13B Gate B\n%s %s\n\n%s\n"
            % (sys.executable, " ".join(sys.argv), "\n".join(firewall_guidance(args))),
        )
        evidence.write_text(
            "README.md",
            "# Phase 13B Gate B evidence\n\nRun id: `%s`\n\nStatus: `%s`\n\n"
            "Real Jetson processor-in-the-loop transport evidence. Physical: Jetson Linux, "
            "CPU/GPU/RAM, scheduling, network stack, CUDA/TensorRT installation, thermal "
            "telemetry and the USB-gadget Ethernet link. Simulated: camera, environment, "
            "vehicle, Safety MCU, actuator and vehicle physics. No full HIL, no real MCU, "
            "no physical camera or actuator, no TensorRT inference, no route or infraction "
            "benchmark.\n" % (run_id, status),
        )
        driver.shutdown()

    print(status)
    print("run_id=%s" % run_id)
    print("evidence_dir=%s" % evidence.run_dir)
    for key, value in sorted(summary.get("gate_b", {}).items()):
        print("%s=%s" % (key, value))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
