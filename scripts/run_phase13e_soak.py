"""Phase 13E — FP16 soak, thermal, backpressure and fault injection.

Drives the real Jetson FP16 command-authority path for hours:

    CARLA -> USB-gadget Ethernet -> real Jetson FP16 TensorRT -> range/SafetyGate
    -> unchanged 64-byte command -> C Virtual Safety MCU -> CARLA virtual actuator

It composes the verified Phase 13B transport and CARLA session rather than
forking them, and adds what a soak needs: a duration-bounded loop, periodic
telemetry sampling, windowed drift detection, a bounded backpressure burst and
a fault-injection matrix with explicit recovery verification.

INT8 is never used here. Phase 13D-MP-RECOVERY froze it as
``experimental_non_authoritative``; FP16 is the command-authority backend.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from run_phase13b_jil_checks import JilSessionDriver  # noqa: E402
from run_phase13b_simulation_host import CarlaLockstepSession  # noqa: E402
from run_phase13e_checks import (  # noqa: E402
    BOUNDARY_FIELDS,
    DEFAULT_COMMAND_VALIDITY_MS,
    DEFAULT_SAFETY_MARGIN_MS,
    PHASE,
    STATUS_BLOCKED,
    STATUS_BURN_IN_PASS,
    STATUS_PASS,
    STATUS_PREFLIGHT_PASS,
    Phase13EEvidence,
    latency_budget_ms,
    new_run_id,
    pc_environment,
    utc_now_iso,
)
from workers.core.clock_sync import monotonic_us  # noqa: E402
from workers.core.soak_metrics import (  # noqa: E402
    DriftLimits,
    SoakSeries,
    classify_soak,
    distribution,
    evaluate_backpressure_recovery,
    evaluate_drift,
    window_stats,
)

SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]

#: Jetson telemetry gauges sampled as time series, with their drift kind.
TELEMETRY_SERIES = (
    ("jetson_process_rss_bytes", "process_rss_bytes", "resource"),
    ("jetson_process_fd_count", "open_fd_count", "resource"),
    ("jetson_process_thread_count", "thread_count", "resource"),
    ("swap_used_bytes", "swap_used_bytes", "resource"),
    ("ram_used_bytes", "ram_used_bytes", "resource"),
    ("cpu_utilization_percent", "cpu_utilization_percent", "gauge"),
    ("gr3d_gpu_utilization_percent", "gpu_utilization_percent", "gauge"),
    ("cpu_frequency_hz", "cpu_frequency_hz", "gauge"),
    ("gpu_frequency_hz", "gpu_frequency_hz", "gauge"),
    ("cpu_temperature_c", "cpu_temperature_c", "temperature"),
    ("gpu_temperature_c", "gpu_temperature_c", "temperature"),
    ("soc_temperature_c", "soc_temperature_c", "temperature"),
    ("tj_temperature_c", "tj_temperature_c", "temperature"),
)


def ssh(target: str, remote: str, *, timeout: int = 300) -> Dict[str, Any]:
    try:
        completed = subprocess.run(
            ["ssh"] + SSH_OPTS + [target, remote],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return {
            "returncode": completed.returncode,
            "stdout": completed.stdout or "",
            "stderr": completed.stderr or "",
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"returncode": -1, "stdout": "", "stderr": repr(exc)}


class SoakRunner:
    """One Phase 13E session: preflight, phases, faults and drift."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.target = "%s@%s" % (args.jetson_user, args.jetson_host)
        self.driver = JilSessionDriver(
            run_id=args.run_id,
            jetson_host=args.jetson_host,
            frame_port=args.frame_port,
            control_port=args.control_port,
            command_port=args.command_port,
            ack_port=args.ack_port,
            pc_bind_host=args.pc_bind_host,
            mcu_library_path=args.mcu_library or None,
            heartbeat_timeout_ms=args.heartbeat_timeout_ms,
            command_validity_ms=args.command_validity_ms,
            camera_width=args.camera_width,
            camera_height=args.camera_height,
        )
        self.session = None  # type: Optional[CarlaLockstepSession]
        self.series = {}  # type: Dict[str, SoakSeries]
        self.phases = []  # type: List[Dict[str, Any]]
        self.fault_rows = []  # type: List[Dict[str, Any]]
        self.events = []  # type: List[Dict[str, Any]]
        self.blockers = []  # type: List[str]
        self.started_at = time.time()
        self.jetson_snapshots = []  # type: List[Dict[str, Any]]
        self.last_metrics = {}  # type: Dict[str, Any]

    # ── helpers ─────────────────────────────────────────────────────────────

    def elapsed(self) -> float:
        return time.time() - self.started_at

    def emit(self, event_type: str, **details: Any) -> None:
        event = {
            "timestamp_utc": utc_now_iso(),
            "elapsed_sec": round(self.elapsed(), 3),
            "source": "phase13e_soak",
            "event_type": event_type,
        }
        event.update(details)
        self.events.append(event)

    def track(self, name: str, value: Any) -> None:
        if name not in self.series:
            self.series[name] = SoakSeries(name)
        self.series[name].add(self.elapsed(), value)

    def sample_telemetry(self, *, phase: str) -> Dict[str, Any]:
        """Pull one Jetson metrics snapshot and fan it out into the series."""

        try:
            metrics = self.driver.control.request("get_metrics").get("metrics", {})
        except Exception as exc:
            self.emit("telemetry_sample_failed", error=repr(exc)[:200])
            return {}
        self.last_metrics = metrics
        for source_key, series_name, _kind in TELEMETRY_SERIES:
            self.track(series_name, metrics.get(source_key))
        self.track("max_mailbox_depth", metrics.get("max_mailbox_depth"))
        self.track("frames_dropped_mailbox", metrics.get("frames_dropped_mailbox"))
        self.track("cuda_error_count", metrics.get("cuda_error_count"))
        self.track(
            "per_frame_device_allocation_count", metrics.get("per_frame_device_allocation_count")
        )
        self.track("tensorrt_fallback_count", metrics.get("tensorrt_fallback_count"))
        snapshot = {
            "elapsed_sec": round(self.elapsed(), 3),
            "phase": phase,
            "thermal_throttling_observed": bool(metrics.get("thermal_throttling_observed")),
        }
        for source_key, series_name, _kind in TELEMETRY_SERIES:
            snapshot[series_name] = metrics.get(source_key)
        self.jetson_snapshots.append(snapshot)
        return metrics

    # ── preflight ───────────────────────────────────────────────────────────

    def preflight(self) -> Dict[str, Any]:
        """Verify the FP16 engine on the target and run the 13B fault matrix."""

        payload = {}  # type: Dict[str, Any]
        remote = (
            "cd %s && source %s/bin/activate && python -c \"%s\""
            % (
                shlex.quote(self.args.jetson_repo),
                shlex.quote(self.args.jetson_venv),
                (
                    "import json,sys;sys.path.insert(0,'.');"
                    "from workers.core.tensorrt_runtime import TensorRTEngineRunner;"
                    "from workers.core.int8_calibration_dataset import sha256_file;"
                    "from pathlib import Path;"
                    "e=r'%s';"
                    "r=TensorRTEngineRunner(e, expected_input_shape=[1,3,640,640], expected_input_name='images');"
                    "b=r.binding_report();r.close();"
                    "print(json.dumps({'engine_sha256':sha256_file(Path(e)),"
                    "'engine_size_bytes':Path(e).stat().st_size,'bindings':b}))"
                )
                % self.args.fp16_engine,
            )
        )
        result = ssh(self.target, remote, timeout=600)
        payload["engine_probe_returncode"] = result["returncode"]
        engine = {}  # type: Dict[str, Any]
        for line in result["stdout"].splitlines():
            line = line.strip()
            if line.startswith("{") and "engine_sha256" in line:
                try:
                    engine = json.loads(line)
                except ValueError:
                    engine = {}
        payload["engine"] = engine
        payload["engine_deserialize_verified"] = bool(
            engine.get("bindings", {}).get("engine_deserialization_verified")
        )
        payload["engine_binding_contract_verified"] = bool(
            engine.get("bindings", {}).get("engine_binding_contract_verified")
        )
        payload["engine_sha256"] = engine.get("engine_sha256", "")
        if self.args.expected_engine_sha256:
            payload["engine_sha256_expected"] = self.args.expected_engine_sha256
            payload["engine_sha256_match"] = (
                payload["engine_sha256"] == self.args.expected_engine_sha256
            )
            if not payload["engine_sha256_match"]:
                self.blockers.append("fp16_engine_sha256_mismatch")
        if not payload["engine_deserialize_verified"]:
            self.blockers.append("fp16_engine_deserialize_failed")
        if not payload["engine_binding_contract_verified"]:
            self.blockers.append("fp16_engine_binding_mismatch")
        return payload

    def run_phase13b_fault_matrix(self) -> Dict[str, Any]:
        """Run the Phase 13B matrix, then restore the transport it tears down.

        Two of its cases deliberately break the frame transport — a truncated
        payload and a disconnect/reconnect — so after the matrix the frame
        client may be closed. Phase 13C and 13D ran the matrix *after* their
        streaming, so it never mattered there. This phase runs it first, and a
        closed frame client would leave every later phase ticking CARLA with
        nowhere to publish.
        """

        outcome = self.driver.run_fault_matrix("E13E")
        for row in self.driver.fault_rows:
            entry = dict(row)
            entry["recovered"] = ""
            entry["recovery_sec"] = ""
            self.fault_rows.append(entry)
        reconnected = self.driver.reconnect_frames()
        outcome["frame_transport_restored"] = bool(reconnected)
        self.emit("frame_transport_restored", reconnected=bool(reconnected))
        if not reconnected:
            self.blockers.append("frame_transport_restore_failed")
        return outcome

    # ── main loop ───────────────────────────────────────────────────────────

    def _drive_once(self, *, wait_for_command: bool) -> Dict[str, Any]:
        """One CARLA tick; publish a new camera frame if one arrived."""

        session = self.session
        outcome = {"tick": True, "frame": False, "latency_ms": None, "timeout": False}
        session.tick()
        image = session.latest_image()
        if image is None:
            session.apply(self.driver.actuator.decide(None, reason="no_new_camera_frame"))
            return outcome

        bgra = self.driver.publisher.carla_image_to_bgra(image)
        baseline = self.driver.server.processed_count()
        published_us = monotonic_us()
        result = self.driver.publisher.publish_bgra(
            bgra,
            simulation_timestamp_us=int(float(getattr(image, "timestamp", 0.0)) * 1_000_000),
        )
        if not result.published:
            session.apply(self.driver.actuator.force_safe_stop("frame_publish_failed"))
            return outcome
        outcome["frame"] = True
        if not wait_for_command:
            return outcome

        mcu_result = self.driver.server.wait_for_next_result(
            baseline, timeout_sec=float(self.args.command_timeout_ms) / 1000.0
        )
        if mcu_result is None:
            outcome["timeout"] = True
            session.apply(self.driver.actuator.force_safe_stop("command_timeout"))
        else:
            session.apply(self.driver.actuator.decide(mcu_result))
            outcome["latency_ms"] = round((monotonic_us() - published_us) / 1000.0, 3)
        return outcome

    def run_timed_phase(
        self,
        name: str,
        duration_sec: float,
        *,
        wait_for_command: bool = True,
        publish_interval_sec: float = 0.0,
        jitter_sec: float = 0.0,
    ) -> Dict[str, Any]:
        """Drive the loop for a fixed wall-clock duration, sampling telemetry."""

        started = time.time()
        deadline = started + float(duration_sec)
        next_sample = started
        ticks = frames = timeouts = 0
        latencies = []  # type: List[float]
        actuator = self.driver.actuator
        active_before = actuator.active_control_applied_count
        safe_stop_before = actuator.safe_stop_applied_count
        self.emit("phase_started", phase=name, duration_sec=duration_sec)

        stalled_ticks = 0
        stall_limit = int(self.args.frame_stall_tick_limit)
        while time.time() < deadline:
            if publish_interval_sec:
                time.sleep(max(0.0, publish_interval_sec))
            if jitter_sec:
                time.sleep(abs(jitter_sec) * ((ticks % 7) / 7.0))
            outcome = self._drive_once(wait_for_command=wait_for_command)
            ticks += 1
            if outcome["frame"]:
                frames += 1
                stalled_ticks = 0
            else:
                # A camera that never delivers, or a transport with nowhere to
                # publish, must not be able to masquerade as hours of soak. The
                # phase aborts instead of ticking an empty loop to the deadline.
                stalled_ticks += 1
                if stall_limit and stalled_ticks >= stall_limit:
                    self.blockers.append("frame_transport_stalled")
                    self.emit(
                        "frame_transport_stalled",
                        phase=name, ticks=ticks, stalled_ticks=stalled_ticks,
                    )
                    break
            if outcome["timeout"]:
                timeouts += 1
            if outcome["latency_ms"] is not None:
                latencies.append(outcome["latency_ms"])
                self.track("frame_to_command_ms", outcome["latency_ms"])
            if time.time() >= next_sample:
                self.sample_telemetry(phase=name)
                next_sample = time.time() + float(self.args.telemetry_interval_sec)

        metrics = self.sample_telemetry(phase=name)
        payload = {
            "phase": name,
            "frame_transport_stalled": bool(stall_limit and stalled_ticks >= stall_limit),
            "requested_duration_sec": round(float(duration_sec), 3),
            "actual_duration_sec": round(time.time() - started, 3),
            "carla_ticks": ticks,
            "frames_published": frames,
            "command_timeouts": timeouts,
            "latency_ms": distribution(latencies),
            "active_control_applied": actuator.active_control_applied_count - active_before,
            "safe_stop_applied": actuator.safe_stop_applied_count - safe_stop_before,
            "max_mailbox_depth": int(metrics.get("max_mailbox_depth", 0) or 0),
            "frames_dropped_mailbox": int(metrics.get("frames_dropped_mailbox", 0) or 0),
            "tensorrt_fallback_count": int(metrics.get("tensorrt_fallback_count", 0) or 0),
            "cuda_error_count": int(metrics.get("cuda_error_count", 0) or 0),
            "per_frame_device_allocation_count": int(
                metrics.get("per_frame_device_allocation_count", 0) or 0
            ),
            "thermal_throttling_observed": bool(metrics.get("thermal_throttling_observed")),
            "precision": metrics.get("precision"),
            "perception_mode": metrics.get("perception_mode"),
        }
        self.phases.append(payload)
        self.emit("phase_completed", **payload)
        return payload

    # ── backpressure ────────────────────────────────────────────────────────

    def run_backpressure(self) -> Dict[str, Any]:
        """Burst input above the paced rate and require latest-frame-only."""

        pre = self.run_timed_phase("backpressure_pre", float(self.args.backpressure_settle_sec))
        before = self.sample_telemetry(phase="backpressure_burst")
        drops_before = int(before.get("frames_dropped_mailbox", 0) or 0)
        received_before = int(before.get("frames_received", 0) or 0)

        # Burst: publish at the requested rate without waiting for each command,
        # so frames arrive faster than the pipeline retires them.
        started = time.time()
        deadline = started + float(self.args.backpressure_burst_sec)
        interval = 1.0 / max(1e-6, float(self.args.backpressure_burst_fps))
        burst_frames = 0
        next_publish = started
        while time.time() < deadline:
            now = time.time()
            if now < next_publish:
                time.sleep(min(0.005, next_publish - now))
                continue
            next_publish += interval
            outcome = self._drive_once(wait_for_command=False)
            if outcome["frame"]:
                burst_frames += 1
        burst_metrics = self.sample_telemetry(phase="backpressure_burst")
        burst_stats = {
            "burst_seconds": round(time.time() - started, 3),
            "burst_target_fps": float(self.args.backpressure_burst_fps),
            "burst_frames_published": burst_frames,
            "burst_effective_fps": round(burst_frames / max(1e-6, time.time() - started), 3),
            "max_mailbox_depth_during_burst": int(burst_metrics.get("max_mailbox_depth", 0) or 0),
        }

        post = self.run_timed_phase("backpressure_post", float(self.args.backpressure_settle_sec))
        after = self.sample_telemetry(phase="backpressure_post")
        drops_after = int(after.get("frames_dropped_mailbox", 0) or 0)
        received_after = int(after.get("frames_received", 0) or 0)

        recovery = evaluate_backpressure_recovery(
            pre_burst_p99_ms=pre["latency_ms"].get("p99"),
            burst_p99_ms=None,
            post_burst_p99_ms=post["latency_ms"].get("p99"),
            recovery_ratio_max=float(self.args.backpressure_recovery_ratio_max),
        )
        payload = {
            "pre_burst": pre,
            "burst": burst_stats,
            "post_burst": post,
            "frames_received_delta": received_after - received_before,
            "mailbox_drops_delta": drops_after - drops_before,
            "max_mailbox_depth": int(after.get("max_mailbox_depth", 0) or 0),
            "latest_frame_only": int(after.get("max_mailbox_depth", 0) or 0) == 1,
            "old_frames_dropped_not_queued": (drops_after - drops_before) >= 0,
            "recovery": recovery,
        }
        self.emit("backpressure_completed", **{k: v for k, v in payload.items() if k != "pre_burst"})
        return payload

    # ── fault injection ─────────────────────────────────────────────────────

    def verify_recovery(self, *, required: int = 3, timeout_sec: float = 30.0) -> Dict[str, Any]:
        """Recovery needs three consecutive valid FP16 results in a row."""

        started = time.time()
        consecutive = 0
        attempts = 0
        actuator = self.driver.actuator
        while time.time() - started < timeout_sec and consecutive < int(required):
            before = actuator.active_control_applied_count
            outcome = self._drive_once(wait_for_command=True)
            attempts += 1
            if not outcome["frame"]:
                continue
            if actuator.active_control_applied_count > before:
                consecutive += 1
            else:
                consecutive = 0
        return {
            "recovered": consecutive >= int(required),
            "consecutive_valid_required": int(required),
            "consecutive_valid_observed": consecutive,
            "recovery_sec": round(time.time() - started, 3),
            "recovery_attempts": attempts,
        }

    def _fault_row(
        self,
        fault_id: str,
        name: str,
        step: str,
        expected: str,
        observed: str,
        details: Dict[str, Any],
        recovery: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        row = {
            "fault_id": fault_id,
            "fault_name": name,
            "gate": "E13E",
            "injection_step": step,
            "expected_classification": expected,
            "observed_classification": observed,
            "passed": observed == expected,
            "recovered": bool(recovery.get("recovered")) if recovery else "",
            "recovery_sec": recovery.get("recovery_sec") if recovery else "",
            "details": json.dumps(details, ensure_ascii=False, sort_keys=True, default=str),
        }
        self.fault_rows.append(row)
        self.emit("fault_case_completed", **{k: row[k] for k in ("fault_id", "fault_name", "observed_classification", "passed", "recovered")})
        return row

    def _node_fault_case(self, fault_id: str, name: str, fault: str) -> Dict[str, Any]:
        """Arm a node-side fault, drive one frame and require SAFE_STOP."""

        actuator = self.driver.actuator
        before_safe = actuator.safe_stop_applied_count
        before_active = actuator.active_control_applied_count
        try:
            self.driver.control.request("inject_fault", fault=fault, count=1)
        except Exception as exc:
            return self._fault_row(
                fault_id, name, "perception_path", "SAFE_STOP", "NO_OBSERVATION",
                {"error": repr(exc)[:200]},
            )
        observed = "NO_OBSERVATION"
        for _ in range(20):
            outcome = self._drive_once(wait_for_command=True)
            if not outcome["frame"]:
                continue
            if actuator.safe_stop_applied_count > before_safe:
                observed = "SAFE_STOP"
                break
            if actuator.active_control_applied_count > before_active:
                observed = "AI_ACTIVE"
                break
        recovery = self.verify_recovery()
        return self._fault_row(
            fault_id, name, "perception_path", "SAFE_STOP", observed,
            {"injected_fault": fault}, recovery,
        )

    def run_phase13e_faults(self) -> List[Dict[str, Any]]:
        rows = []  # type: List[Dict[str, Any]]
        rows.append(self._node_fault_case("E01", "inference timeout", "inference_timeout"))
        rows.append(self._node_fault_case("E02", "CUDA test-double error", "cuda_error"))
        rows.append(self._node_fault_case("E03", "stale AI result", "stale_result_age"))
        rows.append(self._node_fault_case("E04", "invalid input range", "black_frame"))
        rows.append(self._node_fault_case("E05", "clock uncertainty violation", "force_clock_degraded"))

        # E06 network jitter: the delay is applied on the publishing side only.
        # The Jetson network configuration is never touched.
        jitter = self.run_timed_phase(
            "fault_network_jitter", float(self.args.fault_window_sec),
            jitter_sec=float(self.args.jitter_sec),
        )
        recovery = self.verify_recovery()
        rows.append(
            self._fault_row(
                "E06", "network jitter", "transport_path", "RECOVERED",
                "RECOVERED" if recovery["recovered"] else "NOT_RECOVERED",
                {"jitter_sec": float(self.args.jitter_sec),
                 "latency_ms": jitter["latency_ms"], "command_timeouts": jitter["command_timeouts"]},
                recovery,
            )
        )

        # E07 CPU contention and E08 memory pressure: bounded, self-terminating
        # background load on the Jetson. Nothing is left running: `timeout`
        # bounds each one and no configuration is modified.
        cpu = ssh(
            self.target,
            "nohup timeout %d sh -c 'while :; do :; done' >/dev/null 2>&1 & "
            "nohup timeout %d sh -c 'while :; do :; done' >/dev/null 2>&1 & echo armed"
            % (int(self.args.contention_sec), int(self.args.contention_sec)),
            timeout=60,
        )
        contention = self.run_timed_phase(
            "fault_cpu_contention", float(self.args.contention_sec)
        )
        recovery = self.verify_recovery()
        rows.append(
            self._fault_row(
                "E07", "temporary CPU contention", "resource_path", "RECOVERED",
                "RECOVERED" if recovery["recovered"] else "NOT_RECOVERED",
                {"armed": cpu["returncode"] == 0, "seconds": int(self.args.contention_sec),
                 "latency_ms": contention["latency_ms"]},
                recovery,
            )
        )

        memory = ssh(
            self.target,
            "nohup timeout %d python3 -c \"import time; b=bytearray(%d*1024*1024); time.sleep(%d)\" "
            ">/dev/null 2>&1 & echo armed"
            % (int(self.args.contention_sec) + 5, int(self.args.memory_pressure_mb),
               int(self.args.contention_sec)),
            timeout=60,
        )
        pressure = self.run_timed_phase(
            "fault_memory_pressure", float(self.args.contention_sec)
        )
        recovery = self.verify_recovery()
        rows.append(
            self._fault_row(
                "E08", "temporary memory pressure", "resource_path", "RECOVERED",
                "RECOVERED" if recovery["recovered"] else "NOT_RECOVERED",
                {"armed": memory["returncode"] == 0,
                 "megabytes": int(self.args.memory_pressure_mb),
                 "latency_ms": pressure["latency_ms"]},
                recovery,
            )
        )
        return rows

    # ── teardown ────────────────────────────────────────────────────────────

    def drift_report(self, *, total_sec: float) -> Dict[str, Any]:
        limits = DriftLimits(
            resource_growth_ratio_max=float(self.args.resource_growth_ratio_max),
            rss_growth_bytes_max=int(self.args.rss_growth_mb_max) * 1024 * 1024,
            latency_p99_growth_ratio_max=float(self.args.latency_growth_ratio_max),
            temperature_rise_c_max=float(self.args.temperature_rise_c_max),
        )
        window = max(60.0, float(total_sec) * 0.1)
        verdicts = []  # type: List[Dict[str, Any]]
        windows = {}  # type: Dict[str, Any]
        kinds = {name: kind for _src, name, kind in TELEMETRY_SERIES}
        kinds["frame_to_command_ms"] = "latency"
        for name, series in sorted(self.series.items()):
            kind = kinds.get(name)
            if kind not in ("resource", "latency", "temperature"):
                continue
            stats = window_stats(series, window_sec=window, total_sec=total_sec)
            windows[name] = stats
            verdicts.append(evaluate_drift(series, stats, limits=limits, kind=kind))
        return {
            "drift_limits": limits.to_dict(),
            "window_sec": window,
            "window_stats": windows,
            "drift_verdicts": verdicts,
        }


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13E FP16 soak")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--phases", default="preflight,burn_in,soak,backpressure,fault")
    parser.add_argument("--jetson-user", default="myjetsonnx")
    parser.add_argument("--jetson-host", default="192.168.55.1")
    parser.add_argument("--jetson-repo", default="/home/myjetsonnx/Face_Detect_Realtime")
    parser.add_argument("--jetson-venv", default="/home/myjetsonnx/venvs/ma-vlna")
    parser.add_argument(
        "--fp16-engine",
        default="/home/myjetsonnx/models/ma-vlna/yolov9/yolov9-c-640-b1-trt852-fp16.engine",
    )
    parser.add_argument("--expected-engine-sha256", default="")
    parser.add_argument("--carla-host", default="127.0.0.1")
    parser.add_argument("--carla-port", type=int, default=2000)
    parser.add_argument("--town", default="Town03")
    parser.add_argument("--frame-port", type=int, default=13510)
    parser.add_argument("--control-port", type=int, default=13513)
    parser.add_argument("--command-port", type=int, default=13511)
    parser.add_argument("--ack-port", type=int, default=13512)
    parser.add_argument("--pc-bind-host", default="0.0.0.0")
    parser.add_argument("--mcu-library", default="")
    parser.add_argument("--camera-width", type=int, default=640)
    parser.add_argument("--camera-height", type=int, default=360)
    parser.add_argument("--camera-fps", type=float, default=5.0)
    parser.add_argument("--camera-fov", type=float, default=90.0)
    parser.add_argument("--fixed-delta-seconds", type=float, default=0.05)
    parser.add_argument("--spawn-point-index", type=int, default=0)
    parser.add_argument("--ego-blueprint", default="vehicle.tesla.model3")
    parser.add_argument("--map-load-mode", default="reuse_or_load")
    parser.add_argument("--setup-timeout-sec", type=float, default=180.0)
    parser.add_argument("--warmup-ticks", type=int, default=20)
    parser.add_argument("--command-timeout-ms", type=int, default=900)
    parser.add_argument("--command-validity-ms", type=int, default=DEFAULT_COMMAND_VALIDITY_MS)
    parser.add_argument("--safety-margin-ms", type=int, default=DEFAULT_SAFETY_MARGIN_MS)
    parser.add_argument("--heartbeat-timeout-ms", type=int, default=15000)
    parser.add_argument("--burn-in-sec", type=float, default=1800.0)
    parser.add_argument("--soak-sec", type=float, default=7200.0)
    parser.add_argument("--min-soak-sec", type=float, default=7200.0)
    parser.add_argument("--telemetry-interval-sec", type=float, default=5.0)
    parser.add_argument("--backpressure-burst-fps", type=float, default=10.0)
    parser.add_argument("--backpressure-burst-sec", type=float, default=60.0)
    parser.add_argument("--backpressure-settle-sec", type=float, default=60.0)
    parser.add_argument("--backpressure-recovery-ratio-max", type=float, default=1.25)
    parser.add_argument("--fault-window-sec", type=float, default=30.0)
    parser.add_argument(
        "--frame-stall-tick-limit",
        type=int,
        default=600,
        help="abort a phase after this many consecutive ticks with no published frame",
    )
    parser.add_argument("--jitter-sec", type=float, default=0.15)
    parser.add_argument("--contention-sec", type=int, default=30)
    parser.add_argument("--memory-pressure-mb", type=int, default=512)
    parser.add_argument("--resource-growth-ratio-max", type=float, default=1.15)
    parser.add_argument("--rss-growth-mb-max", type=int, default=256)
    parser.add_argument("--latency-growth-ratio-max", type=float, default=1.25)
    parser.add_argument("--temperature-rise-c-max", type=float, default=12.0)
    parser.add_argument("--transport-medium", default="usb_gadget_ethernet")
    parser.add_argument("--output-dir", default="experiments/phase13")
    parser.add_argument("--require-real-jetson", action="store_true")
    parser.add_argument("--skip-phase13b-fault-matrix", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    args.run_id = args.run_id or new_run_id()
    requested = [item.strip() for item in str(args.phases).split(",") if item.strip()]
    evidence = Phase13EEvidence(Path(args.output_dir), args.run_id)
    environment = pc_environment()
    runner = SoakRunner(args)

    summary = {
        "phase": PHASE,
        "gate": "+".join(requested),
        "run_id": args.run_id,
        "created_at_utc": utc_now_iso(),
        "requested_phases": requested,
        "transport_medium": args.transport_medium,
        "soak_profile": {
            "town": args.town,
            "fixed_delta_seconds": float(args.fixed_delta_seconds),
            "simulator_frequency_hz": round(1.0 / float(args.fixed_delta_seconds), 3),
            "camera_fps": float(args.camera_fps),
            "burn_in_sec": float(args.burn_in_sec),
            "soak_sec": float(args.soak_sec),
            "telemetry_interval_sec": float(args.telemetry_interval_sec),
            "backpressure_burst_fps": float(args.backpressure_burst_fps),
        },
    }  # type: Dict[str, Any]
    status = STATUS_BLOCKED
    exit_code = 1
    jetson_metrics = {}  # type: Dict[str, Any]

    try:
        mcu = runner.driver.start_virtual_mcu()
        summary["virtual_mcu"] = mcu
        if not mcu.get("ok"):
            raise RuntimeError("virtual safety MCU could not start")

        hello = runner.driver.connect_control()
        jetson_env = dict(hello.get("environment", {}))
        summary["jetson_environment"] = jetson_env
        runtime_pc_sha = environment.get("runtime_pc_git_sha", "")
        runtime_jetson_sha = jetson_env.get("runtime_jetson_git_sha", "")
        summary["runtime_pc_git_sha"] = runtime_pc_sha
        summary["runtime_jetson_git_sha"] = runtime_jetson_sha
        summary["runtime_git_sha_match"] = bool(runtime_pc_sha) and runtime_pc_sha == runtime_jetson_sha
        if args.require_real_jetson and not jetson_env.get("real_jetson_detected", False):
            runner.blockers.append("jetson_environment_mismatch")
            raise RuntimeError("real Jetson required but not detected")
        if args.require_real_jetson and not summary["runtime_git_sha_match"]:
            runner.blockers.append("git_sha_mismatch")
            raise RuntimeError("runtime git SHA mismatch between PC and Jetson")

        if "preflight" in requested:
            summary["preflight"] = runner.preflight()

        summary["clock"] = runner.driver.synchronise_clocks()
        runner.driver.start_session(start_frame_server=True)
        if not runner.driver.connect_frames():
            runner.blockers.append("frame_transport_failed")
            raise RuntimeError("frame transport could not be established")

        session = CarlaLockstepSession(args)
        summary["carla"] = session.setup()
        runner.session = session
        for _ in range(int(args.warmup_ticks)):
            session.tick()
            session.latest_image()
            session.apply(runner.driver.actuator.force_safe_stop("warmup"))
        runner.driver.actuator.control_applied_count = 0
        runner.driver.actuator.active_control_applied_count = 0
        runner.driver.actuator.safe_stop_applied_count = 0
        runner.driver.actuator.hold_applied_count = 0
        runner.driver.actuator.records = []
        runner.started_at = time.time()

        if "preflight" in requested and not args.skip_phase13b_fault_matrix:
            summary["phase13b_fault_matrix"] = runner.run_phase13b_fault_matrix()

        if "burn_in" in requested:
            summary["burn_in"] = runner.run_timed_phase("burn_in", float(args.burn_in_sec))
        if "soak" in requested:
            summary["soak"] = runner.run_timed_phase("soak", float(args.soak_sec))
        if "backpressure" in requested:
            summary["backpressure"] = runner.run_backpressure()
        if "fault" in requested:
            summary["phase13e_faults"] = runner.run_phase13e_faults()

        jetson_metrics = runner.sample_telemetry(phase="final")
        total_sec = runner.elapsed()
        summary["total_runtime_sec"] = round(total_sec, 3)
        summary["drift"] = runner.drift_report(total_sec=total_sec)

        soak_seconds = float(summary.get("soak", {}).get("actual_duration_sec", 0.0))
        backpressure = summary.get("backpressure", {}).get("recovery")
        classification = classify_soak(
            summary["drift"]["drift_verdicts"],
            backpressure=backpressure,
            thermal_throttling_observed=bool(jetson_metrics.get("thermal_throttling_observed")),
        )
        summary["soak_classification"] = classification

        clock_uncertainty_ms = float(summary["clock"].get("clock_uncertainty_us", 0)) / 1000.0
        budget = latency_budget_ms(
            command_validity_ms=int(args.command_validity_ms),
            clock_uncertainty_ms=clock_uncertainty_ms,
            safety_margin_ms=int(args.safety_margin_ms),
        )
        overall_latency = distribution(runner.series.get("frame_to_command_ms", SoakSeries("x")).values)
        summary["latency_budget_ms"] = round(budget, 4)
        summary["frame_to_command_ms"] = overall_latency

        fault_rows = runner.fault_rows
        false_accept = sum(
            1 for row in fault_rows if row.get("observed_classification") == "AI_ACTIVE"
        )
        false_reject = sum(
            1
            for row in fault_rows
            if row.get("expected_classification") == "ACCEPTED"
            and row.get("observed_classification") not in ("ACCEPTED", "")
        )
        unrecovered = [
            row["fault_id"] for row in fault_rows if row.get("recovered") is False
        ]
        summary["fault_summary"] = {
            "fault_case_count": len(fault_rows),
            "fault_case_passed_count": sum(1 for row in fault_rows if row.get("passed")),
            "false_accept_count": false_accept,
            "false_reject_count": false_reject,
            "unrecovered_faults": unrecovered,
        }

        blockers = list(runner.blockers)
        if "soak" in requested and soak_seconds < float(args.min_soak_sec):
            blockers.append("soak_duration_insufficient")
        for phase in runner.phases:
            if phase["tensorrt_fallback_count"]:
                blockers.append("tensorrt_fallback_used")
            if phase["cuda_error_count"]:
                blockers.append("cuda_execution_error")
            if phase["per_frame_device_allocation_count"]:
                blockers.append("per_frame_device_allocation")
            if phase["max_mailbox_depth"] != 1:
                blockers.append("mailbox_depth_violation")
            if phase["precision"] != "fp16":
                blockers.append("fp16_backend_not_selected")
        if jetson_metrics.get("thermal_throttling_observed"):
            blockers.append("thermal_throttling_observed")
        if classification["drift_labels"]:
            blockers.extend(classification["drift_labels"])
        if overall_latency.get("p99") is not None and float(overall_latency["p99"]) >= budget:
            blockers.append("inference_deadline_missed")
        active_total = sum(phase["active_control_applied"] for phase in runner.phases)
        safe_total = sum(phase["safe_stop_applied"] for phase in runner.phases)
        summary["active_control_total"] = active_total
        summary["safe_stop_total"] = safe_total
        # Only a driving phase can apply control. A preflight-only run verifies
        # the engine and the fault matrix and never drives, so requiring control
        # of it would fail a run that did exactly what was asked.
        drove = bool(runner.phases)
        summary["driving_phase_executed"] = drove
        if drove:
            if active_total <= 0:
                blockers.append("no_active_control_applied")
            if safe_total <= 0:
                blockers.append("no_safe_stop_path_observed")
        if false_accept or false_reject:
            blockers.append("fault_matrix_false_classification")
        if unrecovered:
            blockers.append("fault_recovery_failed")
        fault_matrix = summary.get("phase13b_fault_matrix", {}) or {}
        if "preflight" in requested and not args.skip_phase13b_fault_matrix:
            if not fault_matrix.get("fault_matrix_passed"):
                blockers.append("phase13b_fault_matrix_regression_failed")
        timeouts = sum(phase["command_timeouts"] for phase in runner.phases)
        summary["command_timeouts_total"] = timeouts

        summary["blockers"] = sorted(set(blockers + list(runner.driver.blockers)))
        soaked = "soak" in requested and soak_seconds >= float(args.min_soak_sec)
        passed = not summary["blockers"] and soaked
        if passed:
            status = STATUS_PASS
        elif not summary["blockers"] and "burn_in" in requested:
            status = STATUS_BURN_IN_PASS
        elif not summary["blockers"] and requested == ["preflight"]:
            status = STATUS_PREFLIGHT_PASS
        else:
            status = STATUS_BLOCKED
        exit_code = 0 if not summary["blockers"] else 1
    except Exception as exc:
        summary["error"] = repr(exc)[:400]
        runner.emit("soak_error", error=repr(exc)[:300])
        summary.setdefault("blockers", sorted(set(runner.blockers + ["soak_run_failed"])))
    finally:
        try:
            if runner.session is not None:
                runner.session.close()
        except Exception:
            pass
        summary["status"] = status
        summary["pc_environment"] = environment
        summary.setdefault("blockers", sorted(set(runner.blockers)))
        summary.update(BOUNDARY_FIELDS)

        evidence.write_json("summary.json", summary)
        evidence.write_json("environment.json", environment)
        evidence.write_json("jetson_metrics.json", jetson_metrics or runner.last_metrics)
        evidence.write_json(
            "engine_manifest.json", summary.get("preflight", {}).get("engine", {"executed": False})
        )
        evidence.write_json(
            "soak_timeseries.json",
            {
                "telemetry_interval_sec": float(args.telemetry_interval_sec),
                "snapshots": runner.jetson_snapshots,
                "series": {
                    name: series.to_dict(max_points=2000)
                    for name, series in sorted(runner.series.items())
                },
            },
        )
        evidence.write_json("drift_report.json", summary.get("drift", {"executed": False}))
        evidence.write_json(
            "latency_metrics.json",
            {
                "frame_to_command_ms": summary.get("frame_to_command_ms"),
                "latency_budget_ms": summary.get("latency_budget_ms"),
                "phases": runner.phases,
            },
        )
        evidence.write_json(
            "backpressure_metrics.json", summary.get("backpressure", {"executed": False})
        )
        evidence.write_json(
            "network_metrics.json",
            {
                "transport_medium": args.transport_medium,
                "jetson_host": args.jetson_host,
                "pc_source_address": runner.driver.pc_address,
                "clock": runner.driver.clock_result.to_dict() if runner.driver.clock_result else None,
            },
        )
        evidence.write_fault_matrix(runner.fault_rows)
        evidence.write_fault_matrix(runner.fault_rows, name="fault_injection_matrix")
        evidence.write_events(runner.events + runner.driver.events)
        evidence.write_manifest("+".join(requested), status)
        evidence.write_placeholders()
        evidence.write_text(
            "commands.txt", "# Phase 13E soak\n%s %s\n" % (sys.executable, " ".join(sys.argv))
        )
        evidence.write_text(
            "README.md",
            "# Phase 13E soak evidence\n\nRun id: `%s`\n\nStatus: `%s`\n\n"
            "Real Jetson FP16 command-authority soak. INT8 is not used: Phase "
            "13D-MP-RECOVERY froze it as experimental_non_authoritative.\n"
            % (args.run_id, status),
        )
        try:
            runner.driver.shutdown()
        except Exception:
            pass

    print(status)
    print("run_id=%s" % args.run_id)
    print("evidence_dir=%s" % evidence.run_dir)
    for key in (
        "total_runtime_sec",
        "active_control_total",
        "safe_stop_total",
        "command_timeouts_total",
        "latency_budget_ms",
    ):
        if key in summary:
            print("%s=%s" % (key, summary[key]))
    if "frame_to_command_ms" in summary:
        print("frame_to_command_ms=%s" % json.dumps(summary["frame_to_command_ms"]))
    for phase in runner.phases:
        print(
            "phase=%s duration=%.1f frames=%d ticks=%d mailbox=%d fallback=%d cuda=%d p99=%s"
            % (
                phase["phase"], phase["actual_duration_sec"], phase["frames_published"],
                phase["carla_ticks"], phase["max_mailbox_depth"],
                phase["tensorrt_fallback_count"], phase["cuda_error_count"],
                phase["latency_ms"].get("p99"),
            )
        )
    if "soak_classification" in summary:
        print("drift_labels=%s" % ",".join(summary["soak_classification"]["drift_labels"]) or "(none)")
    if "fault_summary" in summary:
        print("fault_summary=%s" % json.dumps(summary["fault_summary"]))
    if summary.get("blockers"):
        print("blockers=%s" % ",".join(summary["blockers"]), file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
