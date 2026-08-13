"""Phase 13F supervised service wrapper for the real Jetson FP16 node.

This is the process systemd supervises. It owns the lifecycle the node itself
has no opinion about:

    preflight -> spawn node -> notify READY -> ping watchdog -> node exits
              -> backoff -> respawn ...  (or) SIGTERM -> SAFE_STOP -> exit

Why a wrapper rather than running the node directly under systemd:

* The node exits cleanly at the end of every PC session. Under
  ``Restart=on-failure`` that ends the service; under ``Restart=always`` a
  genuine crash-loop becomes indistinguishable from normal session churn. The
  wrapper keeps the *service* up across sessions and reports the difference.
* systemd 245 — the version actually on this Jetson — has no ``RestartSteps``
  or ``RestartMaxDelaySec``; exponential backoff arrived in 254. So bounded
  backoff has to live here.
* ``Type=notify`` wants one process that knows when the thing is really usable.
  That is after preflight and after the node's control port is accepting, not
  when exec returns.

Restart-storm protection is layered deliberately. The wrapper refuses to
respawn after ``--max-restarts`` within ``--restart-window-sec`` and exits
non-zero into ``FAILED``; systemd's own ``StartLimitBurst`` then stops
restarting the wrapper. Two independent limits, so neither has to be perfect.

What this does **not** do: it never edits ``/etc``, never calls sudo, never
reboots, and never installs itself. Those are operator actions and the unit
template is printed for a human to apply.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
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

from workers.core.bounded_log import BoundedJsonlLog  # noqa: E402
from workers.core.sd_notify import SdNotifier  # noqa: E402
from workers.core.service_health import (  # noqa: E402
    STATE_DEGRADED,
    STATE_FAILED,
    STATE_READY,
    STATE_RESTARTING,
    STATE_SAFE_STOP,
    STATE_STARTING,
    HealthSocketServer,
    ServiceHealth,
    query_health,
)
from workers.core.service_manifest import ManifestError, ServiceManifest  # noqa: E402
from workers.core.service_preflight import run_preflight  # noqa: E402

PHASE = "13F-JETSON-SERVICE-SUPERVISION-BOOT-RECOVERY"
DEFAULT_SERVICE_NAME = "ma-vlna-jetson-node"


class RestartPolicy:
    """Bounded exponential backoff plus a restart-storm limit.

    systemd 245 cannot express this itself, and even where it can, the wrapper
    is the only place that knows the difference between "the PC session ended"
    and "the node died on start-up".
    """

    def __init__(
        self,
        *,
        initial_sec: float = 1.0,
        max_sec: float = 30.0,
        factor: float = 2.0,
        max_restarts: int = 5,
        window_sec: float = 300.0,
    ) -> None:
        self.initial_sec = max(0.0, float(initial_sec))
        self.max_sec = max(self.initial_sec, float(max_sec))
        self.factor = max(1.0, float(factor))
        self.max_restarts = max(1, int(max_restarts))
        self.window_sec = max(1.0, float(window_sec))
        self.restart_times = []  # type: List[float]
        self.consecutive_failures = 0

    def record_restart(self, now: float) -> None:
        self.restart_times.append(now)
        # Bounded: only the current window is ever retained.
        cutoff = now - self.window_sec
        self.restart_times = [item for item in self.restart_times if item >= cutoff]

    def restarts_in_window(self, now: float) -> int:
        cutoff = now - self.window_sec
        return sum(1 for item in self.restart_times if item >= cutoff)

    def storm_detected(self, now: float) -> bool:
        return self.restarts_in_window(now) >= self.max_restarts

    def backoff_sec(self) -> float:
        if self.consecutive_failures <= 0:
            return 0.0
        delay = self.initial_sec * (self.factor ** (self.consecutive_failures - 1))
        return min(self.max_sec, delay)

    def on_clean_exit(self) -> None:
        self.consecutive_failures = 0

    def on_failure(self) -> None:
        self.consecutive_failures += 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "restart_initial_sec": self.initial_sec,
            "restart_max_sec": self.max_sec,
            "restart_factor": self.factor,
            "restart_max_restarts": self.max_restarts,
            "restart_window_sec": self.window_sec,
            "restart_consecutive_failures": self.consecutive_failures,
            "restart_backoff_next_sec": self.backoff_sec(),
        }


class ServiceSupervisor:
    """Owns preflight, the child node, the watchdog and the restart policy."""

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.health = ServiceHealth(service_name=args.service_name)
        self.notifier = SdNotifier()
        self.log = BoundedJsonlLog(
            args.log_path or None,
            max_bytes=int(args.log_max_bytes),
            backup_count=int(args.log_backup_count),
            echo=not args.no_log_echo,
        )
        self.policy = RestartPolicy(
            initial_sec=args.restart_initial_sec,
            max_sec=args.restart_max_sec,
            factor=args.restart_factor,
            max_restarts=args.max_restarts,
            window_sec=args.restart_window_sec,
        )
        self.health_server = None  # type: Optional[HealthSocketServer]
        self.child = None  # type: Optional[subprocess.Popen]
        self.child_pid = None  # type: Optional[int]
        self.manifest = None  # type: Optional[ServiceManifest]
        self.preflight_report = None  # type: Optional[Dict[str, Any]]
        self.stop_requested = False
        self.stop_signal = None  # type: Optional[int]
        self.node_start_count = 0
        self.node_clean_exit_count = 0
        self.node_failure_count = 0
        self.engine_load_count = 0
        self.last_child_returncode = None  # type: Optional[int]
        self.started_at = time.time()

    # ── evidence ────────────────────────────────────────────────────────────

    def emit(self, event_type: str, **fields: Any) -> None:
        self.log.write(event_type, state=self.health.state, **fields)

    def status_extra(self) -> Dict[str, Any]:
        payload = {
            "phase": PHASE,
            "node_pid": self.child_pid,
            "node_start_count": self.node_start_count,
            "node_clean_exit_count": self.node_clean_exit_count,
            "node_failure_count": self.node_failure_count,
            "engine_load_count": self.engine_load_count,
            "last_child_returncode": self.last_child_returncode,
            "supervisor_uptime_sec": round(time.time() - self.started_at, 3),
            "restarts_in_window": self.policy.restarts_in_window(time.time()),
        }
        payload.update(self.policy.to_dict())
        payload.update(self.notifier.to_dict())
        payload.update(self.log.to_dict())
        if self.manifest is not None:
            payload["manifest_sha256"] = self.manifest.manifest_sha256
            payload["engine_sha256"] = self.manifest.engine_sha256
            payload["repository_sha"] = self.manifest.repository_sha
            payload["precision"] = self.manifest.precision
        if self.preflight_report is not None:
            payload["preflight_passed"] = self.preflight_report.get("preflight_passed")
            payload["preflight_failed_checks"] = self.preflight_report.get(
                "failed_required_checks"
            )
        return payload

    # ── lifecycle ───────────────────────────────────────────────────────────

    def install_signal_handlers(self) -> None:
        def handler(signum: int, _frame: Any) -> None:
            # Only record here; the work happens on the main loop so shutdown
            # is not attempted from inside a signal context.
            self.stop_requested = True
            self.stop_signal = int(signum)

        for name in ("SIGTERM", "SIGINT", "SIGHUP"):
            signum = getattr(signal, name, None)
            if signum is not None:
                try:
                    signal.signal(signum, handler)
                except (OSError, ValueError, RuntimeError):
                    pass

    def preflight(self) -> bool:
        self.health.transition(STATE_STARTING, "running preflight")
        self.notifier.status("preflight")
        try:
            self.manifest = ServiceManifest.load(self.args.manifest)
        except ManifestError as exc:
            self.manifest = None
            self.health.record_failure(exc.classification, exc.message)
            self.emit("preflight_manifest_failed", classification=exc.classification,
                      detail=exc.message)

        ports = {
            "control": int(self.args.control_port),
            "frame": int(self.args.frame_port),
            "ack": int(self.args.ack_port),
        }
        report = run_preflight(
            manifest_path=self.args.manifest,
            repo_root=str(REPO_ROOT),
            expected_repo_sha=self.args.expected_repo_sha,
            runtime_dir=self.args.runtime_dir,
            evidence_dir=self.args.evidence_dir,
            ports=ports,
            bind_host=self.args.bind_host,
            pc_host=self.args.pc_host,
            check_ports=not self.args.skip_port_check,
            import_tensorrt=not self.args.skip_tensorrt_check,
        )
        self.preflight_report = report.to_dict()
        self.emit(
            "preflight_completed",
            passed=report.passed,
            failed_required=[item.name for item in report.failures],
            failed_advisory=[item.name for item in report.advisories],
        )
        if self.manifest is not None:
            self.health.set_facts(
                repository_sha=self.manifest.repository_sha,
                engine_sha256=self.manifest.engine_sha256,
                manifest_sha256=self.manifest.manifest_sha256,
                precision=self.manifest.precision,
            )
        if not report.ai_authority_permitted:
            for item in report.failures:
                self.health.record_failure("preflight_%s" % item.name, item.detail)
            # A failed preflight must never reach AI authority. The service
            # stays up and answerable in SAFE_STOP rather than pretending.
            self.health.transition(STATE_SAFE_STOP, "preflight failed; AI authority withheld")
            self.notifier.status("preflight failed: %s" % ",".join(
                item.name for item in report.failures
            ))
        return report.ai_authority_permitted

    def node_command(self) -> List[str]:
        run_id = "%s-%d-%d" % (self.args.run_id_prefix, int(time.time()), self.node_start_count + 1)
        command = [
            sys.executable,
            str(SCRIPTS_DIR / "run_phase13b_jetson_node.py"),
            "--run-id", run_id,
            "--bind-host", self.args.bind_host,
            "--frame-port", str(self.args.frame_port),
            "--control-port", str(self.args.control_port),
            "--command-port", str(self.args.command_port),
            "--ack-port", str(self.args.ack_port),
            "--perception-backend", "tensorrt",
            "--tensorrt-precision", "fp16",
            "--require-no-fallback",
            "--require-real-jetson",
            "--decoupled-consumer",
            "--output-dir", self.args.evidence_dir,
            "--control-timeout-sec", str(self.args.node_control_timeout_sec),
            "--accept-timeout-sec", str(self.args.node_accept_timeout_sec),
            "--pid-file", os.path.join(self.args.runtime_dir, "node.pid"),
        ]
        if self.args.pc_host:
            command += ["--pc-host", self.args.pc_host]
        if self.manifest is not None:
            command += ["--tensorrt-engine", self.manifest.engine_path]
        if self.args.tensorrt_profile:
            command += ["--tensorrt-profile", self.args.tensorrt_profile]
        if self.args.node_extra_args:
            command += self.args.node_extra_args.split()
        return command

    def spawn_node(self) -> bool:
        command = self.node_command()
        env = dict(os.environ)
        # The child must never answer the parent's watchdog or claim readiness.
        for key in ("NOTIFY_SOCKET", "WATCHDOG_USEC", "WATCHDOG_PID"):
            env.pop(key, None)
        try:
            self.child = subprocess.Popen(
                command,
                cwd=str(REPO_ROOT),
                env=env,
                stdout=subprocess.DEVNULL if self.args.discard_node_stdout else None,
                stderr=subprocess.STDOUT if self.args.discard_node_stdout else None,
                start_new_session=False,
            )
        except OSError as exc:
            self.child = None
            self.child_pid = None
            self.health.record_failure("node_spawn_failed", "%s: %s" % (type(exc).__name__, exc))
            self.emit("node_spawn_failed", error="%s: %s" % (type(exc).__name__, exc))
            return False
        self.child_pid = self.child.pid
        self.node_start_count += 1
        # A node process loads its engine exactly once, at construction.
        self.engine_load_count += 1
        self.health.set_facts(node_pid=self.child_pid, node_start_count=self.node_start_count)
        self.emit("node_started", node_pid=self.child_pid, command=" ".join(command))
        return True

    def wait_for_node_ready(self) -> bool:
        """Readiness is the control port accepting, not exec returning."""

        deadline = time.time() + float(self.args.node_ready_timeout_sec)
        while time.time() < deadline:
            if self.stop_requested:
                return False
            if self.child is not None and self.child.poll() is not None:
                return False
            if self._control_port_open():
                return True
            self._tick_watchdog()
            time.sleep(0.5)
        return False

    def _control_port_open(self) -> bool:
        host = "127.0.0.1" if self.args.bind_host in ("0.0.0.0", "") else self.args.bind_host
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        try:
            sock.connect((host, int(self.args.control_port)))
            return True
        except OSError:
            return False
        finally:
            try:
                sock.close()
            except OSError:
                pass

    def _tick_watchdog(self) -> None:
        self.health.heartbeat()
        self.notifier.watchdog()

    def stop_node(self, *, reason: str) -> Dict[str, Any]:
        """Stop exactly the child we started. Never pkill, never by name."""

        child = self.child
        if child is None or child.poll() is not None:
            return {"stopped": False, "reason": "no running node"}
        pid = child.pid
        self.emit("node_stop_requested", node_pid=pid, reason=reason)
        result = {"node_pid": pid, "reason": reason, "escalated_to_kill": False}
        try:
            child.terminate()
        except OSError as exc:
            result["terminate_error"] = "%s: %s" % (type(exc).__name__, exc)
        deadline = time.time() + float(self.args.node_stop_timeout_sec)
        while time.time() < deadline:
            if child.poll() is not None:
                break
            self._tick_watchdog()
            time.sleep(0.2)
        if child.poll() is None:
            # Escalation is bounded and recorded; a node that ignores SIGTERM
            # must not be able to hold the service open indefinitely.
            result["escalated_to_kill"] = True
            try:
                child.kill()
            except OSError as exc:
                result["kill_error"] = "%s: %s" % (type(exc).__name__, exc)
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                result["still_running"] = True
        result["stopped"] = child.poll() is not None
        result["returncode"] = child.returncode
        self.last_child_returncode = child.returncode
        self.emit("node_stopped", **result)
        self.child = None
        self.child_pid = None
        return result

    def supervise_once(self) -> str:
        """Run one node generation. Returns 'clean', 'failed' or 'stopped'."""

        if not self.spawn_node():
            return "failed"
        if self.wait_for_node_ready():
            self.health.transition(STATE_READY, "node control port accepting")
            self.notifier.ready("node ready pid=%s" % self.child_pid)
            self.emit("service_ready", node_pid=self.child_pid)
        else:
            if self.stop_requested:
                return "stopped"
            self.health.transition(STATE_DEGRADED, "node did not become ready in time")
            self.health.record_failure("node_not_ready", "control port never accepted")
            self.emit("node_not_ready", node_pid=self.child_pid)
            # Ready-timeout is a failure of this generation, not of the service.
            self.stop_node(reason="not_ready")
            return "failed"

        child = self.child
        while child is not None and child.poll() is None:
            if self.stop_requested:
                return "stopped"
            self._tick_watchdog()
            time.sleep(min(1.0, self.args.watchdog_poll_sec))

        self.last_child_returncode = child.returncode if child is not None else None
        self.child = None
        self.child_pid = None
        clean = self.last_child_returncode == 0
        self.emit("node_exited", returncode=self.last_child_returncode, clean=clean)
        if clean:
            self.node_clean_exit_count += 1
            return "clean"
        self.node_failure_count += 1
        self.health.record_failure(
            "node_exit_nonzero", "returncode=%s" % self.last_child_returncode
        )
        return "failed"

    def run(self) -> int:
        self.install_signal_handlers()
        os.makedirs(self.args.runtime_dir, exist_ok=True)
        self.emit("supervisor_started", pid=os.getpid(), phase=PHASE,
                  systemd_notify=self.notifier.available)

        self.health_server = HealthSocketServer(
            os.path.join(self.args.runtime_dir, "health.sock"),
            self.health,
            extra_provider=self.status_extra,
        )
        if not self.health_server.start():
            self.emit("health_socket_unavailable", error=self.health_server.last_error)

        ok = self.preflight()
        if not ok:
            # Still notify READY: the unit is up and answerable, and systemd
            # must not restart-loop a machine whose engine hash is wrong. The
            # state says SAFE_STOP and AI authority is withheld.
            self.notifier.ready("preflight failed; SAFE_STOP, AI authority withheld")
            self.emit("service_safe_stop_no_authority")
            if self.args.exit_on_preflight_failure:
                self.shutdown(reason="preflight_failed")
                return 3
            return self.idle_until_stopped()

        exit_code = 0
        while not self.stop_requested:
            outcome = self.supervise_once()
            if outcome == "stopped":
                break
            now = time.time()
            if outcome == "clean":
                self.policy.on_clean_exit()
            else:
                self.policy.on_failure()
            self.policy.record_restart(now)

            if self.args.once:
                break
            if self.policy.storm_detected(now):
                self.health.transition(
                    STATE_FAILED,
                    "restart storm: %d restarts within %.0fs"
                    % (self.policy.restarts_in_window(now), self.policy.window_sec),
                )
                self.health.record_failure(
                    "restart_storm_blocked",
                    "%d restarts in %.0fs exceeds limit %d"
                    % (self.policy.restarts_in_window(now), self.policy.window_sec,
                       self.policy.max_restarts),
                )
                self.emit(
                    "restart_storm_blocked",
                    restarts_in_window=self.policy.restarts_in_window(now),
                    window_sec=self.policy.window_sec,
                    max_restarts=self.policy.max_restarts,
                )
                self.notifier.status("restart storm blocked")
                exit_code = 4
                break

            delay = self.policy.backoff_sec()
            self.health.transition(
                STATE_RESTARTING, "respawning after %s exit in %.2fs" % (outcome, delay)
            )
            self.notifier.status("restarting in %.1fs" % delay)
            self.emit("node_restart_scheduled", backoff_sec=round(delay, 3), outcome=outcome,
                      consecutive_failures=self.policy.consecutive_failures)
            if not self._sleep_interruptible(delay):
                break

        self.shutdown(reason="signal_%s" % self.stop_signal if self.stop_signal else "loop_exit")
        return exit_code

    def idle_until_stopped(self) -> int:
        """Stay up, answerable and without authority after a failed preflight."""

        self.emit("supervisor_idle_safe_stop")
        while not self.stop_requested:
            self._tick_watchdog()
            time.sleep(min(1.0, self.args.watchdog_poll_sec))
        self.shutdown(reason="signal_%s" % self.stop_signal)
        return 0

    def _sleep_interruptible(self, seconds: float) -> bool:
        deadline = time.time() + max(0.0, float(seconds))
        while time.time() < deadline:
            if self.stop_requested:
                return False
            self._tick_watchdog()
            time.sleep(min(0.25, self.args.watchdog_poll_sec))
        return not self.stop_requested

    def shutdown(self, *, reason: str) -> None:
        self.notifier.stopping("shutting down: %s" % reason)
        # Graceful path: ask the node to stop so it can emit SAFE_STOP itself.
        # If it cannot, the PC-side MCU heartbeat timeout produces SAFE_STOP
        # anyway -- that is the fail-closed guarantee, and it does not depend
        # on this process getting a chance to be polite.
        self.health.transition(STATE_SAFE_STOP, "service stopping: %s" % reason)
        stop_result = self.stop_node(reason=reason)
        self.emit("supervisor_stopping", reason=reason, **{
            k: v for k, v in stop_result.items() if k not in ("reason",)
        })
        if self.health_server is not None:
            self.health_server.stop()
        summary = self.status_extra()
        summary["final_state"] = self.health.state
        summary["shutdown_reason"] = reason
        self.emit("supervisor_stopped", **{
            k: v for k, v in summary.items() if not isinstance(v, (dict, list))
        })
        try:
            path = os.path.join(self.args.runtime_dir, "last_status.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(self.health.snapshot(), handle, indent=2, sort_keys=True, default=str)
        except OSError:
            pass
        self.log.close()
        self.notifier.close()


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13F supervised Jetson node service")
    parser.add_argument("--service-name", default=DEFAULT_SERVICE_NAME)
    parser.add_argument("--manifest", default="config/phase13f_service_manifest.json")
    parser.add_argument("--expected-repo-sha", default="")
    parser.add_argument("--runtime-dir", default="/run/ma-vlna")
    parser.add_argument("--evidence-dir", default="experiments/phase13")
    parser.add_argument("--log-path", default="")
    parser.add_argument("--log-max-bytes", type=int, default=8 * 1024 * 1024)
    parser.add_argument("--log-backup-count", type=int, default=3)
    parser.add_argument("--no-log-echo", action="store_true")
    parser.add_argument("--bind-host", default="0.0.0.0")
    parser.add_argument("--pc-host", default="")
    parser.add_argument("--frame-port", type=int, default=48701)
    parser.add_argument("--control-port", type=int, default=48702)
    parser.add_argument("--command-port", type=int, default=48703)
    parser.add_argument("--ack-port", type=int, default=48704)
    parser.add_argument("--tensorrt-profile", default="config/phase13c_tensorrt_profile.json")
    parser.add_argument("--run-id-prefix", default="phase13f")
    parser.add_argument("--node-extra-args", default="")
    parser.add_argument("--node-ready-timeout-sec", type=float, default=180.0)
    parser.add_argument("--node-stop-timeout-sec", type=float, default=20.0)
    parser.add_argument("--node-control-timeout-sec", type=int, default=86400)
    parser.add_argument("--node-accept-timeout-sec", type=int, default=86400)
    parser.add_argument("--watchdog-poll-sec", type=float, default=1.0)
    parser.add_argument("--restart-initial-sec", type=float, default=1.0)
    parser.add_argument("--restart-max-sec", type=float, default=30.0)
    parser.add_argument("--restart-factor", type=float, default=2.0)
    parser.add_argument("--max-restarts", type=int, default=5)
    parser.add_argument("--restart-window-sec", type=float, default=300.0)
    parser.add_argument("--once", action="store_true", help="Run one node generation and exit.")
    parser.add_argument("--skip-port-check", action="store_true")
    parser.add_argument("--skip-tensorrt-check", action="store_true")
    parser.add_argument("--discard-node-stdout", action="store_true")
    parser.add_argument(
        "--exit-on-preflight-failure", action="store_true",
        help="Exit non-zero instead of idling in SAFE_STOP when preflight fails.",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="Query the running service's health socket and print it.",
    )
    parser.add_argument("--status-timeout-sec", type=float, default=5.0)
    parser.add_argument(
        "--preflight-only", action="store_true",
        help="Run preflight, print the report and exit without starting the node.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))

    if args.status:
        path = os.path.join(args.runtime_dir, "health.sock")
        try:
            payload = query_health(path, timeout_sec=args.status_timeout_sec)
        except (OSError, ValueError) as exc:
            print(json.dumps({
                "service_name": args.service_name,
                "state": "UNKNOWN",
                "error": "%s: %s" % (type(exc).__name__, exc),
                "health_socket_path": path,
            }, indent=2))
            return 1
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    supervisor = ServiceSupervisor(args)
    if args.preflight_only:
        ok = supervisor.preflight()
        print(json.dumps(supervisor.preflight_report, indent=2, sort_keys=True))
        supervisor.log.close()
        return 0 if ok else 3
    return supervisor.run()


if __name__ == "__main__":
    raise SystemExit(main())
