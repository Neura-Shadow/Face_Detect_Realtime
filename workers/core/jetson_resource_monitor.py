"""Phase 13B real Jetson resource / thermal telemetry.

Collects Jetson runtime telemetry **without changing** nvpmodel, clocks,
JetPack, the kernel or the thermal policy. Sources, in preference order:

* ``tegrastats`` (read-only subprocess) for RAM/SWAP/CPU/GR3D/thermal zones;
* ``/proc`` and ``/sys`` for process RSS, thread count, fd count and clocks;
* ``psutil`` only when it is *already* installed (it is not installed in the
  Jetson venv, so the standard-library path is the normal one).

Power is only reported when an actual supported power field is parsed from
telemetry. On boards without INA power monitors (the reComputer J4012 Orin NX
16 GB used here) ``power_measurement_available`` stays ``False`` and
``power_metrics`` stays ``None``. Power is never inferred from utilisation.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import threading
from typing import Any, Dict, List, Optional

TEGRASTATS_DEFAULT_PATH = "/usr/bin/tegrastats"
DEFAULT_INTERVAL_MS = 1000
MIN_REQUIRED_SAMPLES = 5

_RAM_RE = re.compile(r"RAM (\d+)/(\d+)MB")
_SWAP_RE = re.compile(r"SWAP (\d+)/(\d+)MB")
_CPU_BLOCK_RE = re.compile(r"CPU \[([^\]]+)\]")
_CPU_CORE_RE = re.compile(r"(\d+)%@(\d+)")
_GR3D_RE = re.compile(r"GR3D_FREQ (\d+)%")
_EMC_RE = re.compile(r"EMC_FREQ (\d+)%")
_TEMP_RE = re.compile(r"([A-Za-z0-9_]+)@(-?\d+(?:\.\d+)?)C")
_POWER_RE = re.compile(r"(VDD[_A-Z0-9]*|POM[_A-Z0-9]*)\s+(\d+)mW/(\d+)mW")


def _read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r") as handle:
            return handle.read().strip()
    except (OSError, IOError):
        return None


def _read_int(path: str) -> Optional[int]:
    text = _read_text(path)
    if text is None:
        return None
    try:
        return int(text.split()[0])
    except (ValueError, IndexError):
        return None


def parse_tegrastats_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse one ``tegrastats`` line into a structured sample.

    Returns ``None`` for lines that carry no recognisable RAM field, which keeps
    banner or error lines out of the sample set.
    """

    ram = _RAM_RE.search(line)
    if ram is None:
        return None

    sample = {}  # type: Dict[str, Any]
    sample["ram_used_bytes"] = int(ram.group(1)) * 1024 * 1024
    sample["ram_total_bytes"] = int(ram.group(2)) * 1024 * 1024
    sample["ram_available_bytes"] = sample["ram_total_bytes"] - sample["ram_used_bytes"]

    swap = _SWAP_RE.search(line)
    if swap is not None:
        sample["swap_used_bytes"] = int(swap.group(1)) * 1024 * 1024
        sample["swap_total_bytes"] = int(swap.group(2)) * 1024 * 1024

    cpu_block = _CPU_BLOCK_RE.search(line)
    if cpu_block is not None:
        cores = _CPU_CORE_RE.findall(cpu_block.group(1))
        if cores:
            loads = [float(item[0]) for item in cores]
            freqs = [int(item[1]) for item in cores]
            sample["cpu_core_count_online"] = len(cores)
            sample["cpu_utilization_percent"] = round(sum(loads) / len(loads), 3)
            sample["cpu_utilization_max_percent"] = max(loads)
            sample["cpu_frequency_hz"] = max(freqs) * 1_000_000

    gr3d = _GR3D_RE.search(line)
    if gr3d is not None:
        sample["gr3d_gpu_utilization_percent"] = float(gr3d.group(1))
    emc = _EMC_RE.search(line)
    if emc is not None:
        sample["emc_utilization_percent"] = float(emc.group(1))

    temperatures = {}  # type: Dict[str, float]
    for name, value in _TEMP_RE.findall(line):
        temperature = float(value)
        # -256C is the Jetson "sensor not populated" sentinel.
        if temperature > -100.0:
            temperatures[name.upper()] = temperature
    if temperatures:
        sample["temperatures_c"] = temperatures
        if "CPU" in temperatures:
            sample["cpu_temperature_c"] = temperatures["CPU"]
        if "GPU" in temperatures:
            sample["gpu_temperature_c"] = temperatures["GPU"]
        soc_values = [value for name, value in temperatures.items() if name.startswith("SOC")]
        if soc_values:
            sample["soc_temperature_c"] = round(max(soc_values), 3)
        if "TJ" in temperatures:
            sample["tj_temperature_c"] = temperatures["TJ"]

    powers = _POWER_RE.findall(line)
    if powers:
        sample["power_mw"] = {name: int(instant) for name, instant, _ in powers}

    return sample


class JetsonResourceMonitor:
    """Background tegrastats reader plus /proc and /sys sampling."""

    def __init__(
        self,
        *,
        interval_ms: int = DEFAULT_INTERVAL_MS,
        tegrastats_path: str = TEGRASTATS_DEFAULT_PATH,
        max_samples: int = 600,
    ) -> None:
        self.interval_ms = int(interval_ms)
        self.tegrastats_path = tegrastats_path if os.path.exists(tegrastats_path) else (
            shutil.which("tegrastats") or ""
        )
        self.max_samples = int(max_samples)
        self.samples = []  # type: List[Dict[str, Any]]
        self.parse_failure_count = 0
        self.tegrastats_available = bool(self.tegrastats_path)
        self.tegrastats_error = None  # type: Optional[str]
        self._process = None  # type: Optional[subprocess.Popen]
        self._thread = None  # type: Optional[threading.Thread]
        self._stop = threading.Event()
        self._lock = threading.Lock()

    # ── lifecycle ───────────────────────────────────────────────────────────

    def start(self) -> bool:
        """Start the read-only tegrastats reader. Returns availability."""

        if not self.tegrastats_available:
            self.tegrastats_error = "tegrastats binary not found"
            return False
        try:
            self._process = subprocess.Popen(
                [self.tegrastats_path, "--interval", str(self.interval_ms)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
                bufsize=1,
            )
        except (OSError, ValueError) as exc:
            self.tegrastats_available = False
            self.tegrastats_error = repr(exc)
            return False
        self._thread = threading.Thread(target=self._reader, name="tegrastats-reader", daemon=True)
        self._thread.start()
        return True

    def _reader(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            if self._stop.is_set():
                break
            sample = parse_tegrastats_line(line)
            if sample is None:
                self.parse_failure_count += 1
                continue
            with self._lock:
                if len(self.samples) < self.max_samples:
                    self.samples.append(sample)

    def stop(self) -> None:
        self._stop.set()
        process = self._process
        self._process = None
        if process is not None:
            try:
                process.terminate()
                process.wait(timeout=5)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    process.kill()
                except OSError:
                    pass
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=3)

    # ── /proc and /sys sampling ─────────────────────────────────────────────

    @staticmethod
    def process_metrics() -> Dict[str, Any]:
        """Current process RSS, thread count and fd count via /proc (or psutil)."""

        metrics = {
            "jetson_process_rss_bytes": None,
            "jetson_process_thread_count": None,
            "jetson_process_fd_count": None,
            "process_metrics_source": "unavailable",
        }  # type: Dict[str, Any]

        status = _read_text("/proc/self/status")
        if status is not None:
            for line in status.splitlines():
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        metrics["jetson_process_rss_bytes"] = int(parts[1]) * 1024
                elif line.startswith("Threads:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        metrics["jetson_process_thread_count"] = int(parts[1])
            try:
                metrics["jetson_process_fd_count"] = len(os.listdir("/proc/self/fd"))
            except OSError:
                pass
            metrics["process_metrics_source"] = "proc"
            return metrics

        try:  # psutil is used only when it is already installed.
            import psutil  # type: ignore[import-not-found]

            process = psutil.Process()
            metrics["jetson_process_rss_bytes"] = int(process.memory_info().rss)
            metrics["jetson_process_thread_count"] = int(process.num_threads())
            try:
                metrics["jetson_process_fd_count"] = int(process.num_fds())
            except Exception:  # pragma: no cover - platform dependent
                pass
            metrics["process_metrics_source"] = "psutil"
        except Exception:  # pragma: no cover - psutil absent on the Jetson venv
            pass
        return metrics

    @staticmethod
    def clock_metrics() -> Dict[str, Any]:
        """Best-effort CPU/GPU frequency read from /sys (no writes)."""

        metrics = {"cpu_frequency_hz": None, "gpu_frequency_hz": None}  # type: Dict[str, Any]
        cpu_freqs = []  # type: List[int]
        for path in sorted(glob.glob("/sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq")):
            value = _read_int(path)
            if value:
                cpu_freqs.append(value * 1000)
        if cpu_freqs:
            metrics["cpu_frequency_hz"] = max(cpu_freqs)

        gpu_candidates = sorted(glob.glob("/sys/class/devfreq/*/cur_freq")) + sorted(
            glob.glob("/sys/devices/gpu.0/devfreq/*/cur_freq")
        )
        for path in gpu_candidates:
            value = _read_int(path)
            if value:
                metrics["gpu_frequency_hz"] = value
                break
        return metrics

    @staticmethod
    def thermal_trip_status() -> Dict[str, Any]:
        """Compare measured zone temperatures against declared passive trips.

        This is a read-only observation. It never changes the thermal policy and
        never infers throttling from utilisation.
        """

        crossed = []  # type: List[Dict[str, Any]]
        zones_checked = 0
        for zone in sorted(glob.glob("/sys/devices/virtual/thermal/thermal_zone*")):
            temperature = _read_int(os.path.join(zone, "temp"))
            if temperature is None:
                continue
            zones_checked += 1
            zone_type = _read_text(os.path.join(zone, "type")) or os.path.basename(zone)
            for trip_temp_path in sorted(glob.glob(os.path.join(zone, "trip_point_*_temp"))):
                trip_type_path = trip_temp_path.replace("_temp", "_type")
                trip_type = _read_text(trip_type_path) or ""
                if trip_type not in ("passive", "hot", "critical"):
                    continue
                trip_value = _read_int(trip_temp_path)
                if trip_value is None or trip_value <= 0:
                    continue
                if temperature >= trip_value:
                    crossed.append(
                        {
                            "zone": zone_type,
                            "trip_type": trip_type,
                            "temperature_c": round(temperature / 1000.0, 3),
                            "trip_c": round(trip_value / 1000.0, 3),
                        }
                    )
        return {
            "thermal_zones_checked": zones_checked,
            "thermal_trip_points_crossed": crossed,
            "thermal_throttling_observed": bool(crossed),
            "thermal_throttling_detection_method": "sysfs_passive_hot_critical_trip_comparison",
        }

    # ── aggregation ─────────────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        """Aggregate all collected telemetry into the Phase 13B metric names."""

        with self._lock:
            samples = list(self.samples)

        def _pick(key: str) -> List[float]:
            return [float(item[key]) for item in samples if item.get(key) is not None]

        def _stat(key: str) -> Dict[str, Any]:
            values = _pick(key)
            if not values:
                return {"min": None, "max": None, "mean": None}
            return {
                "min": round(min(values), 3),
                "max": round(max(values), 3),
                "mean": round(sum(values) / len(values), 3),
            }

        power_samples = [item["power_mw"] for item in samples if item.get("power_mw")]
        power_available = bool(power_samples)
        power_metrics = None  # type: Optional[Dict[str, Any]]
        if power_available:
            rails = {}  # type: Dict[str, List[float]]
            for entry in power_samples:
                for rail, value in entry.items():
                    rails.setdefault(rail, []).append(float(value))
            power_metrics = {
                rail: {
                    "min_mw": round(min(values), 3),
                    "max_mw": round(max(values), 3),
                    "mean_mw": round(sum(values) / len(values), 3),
                }
                for rail, values in rails.items()
            }

        last = samples[-1] if samples else {}
        thermal = self.thermal_trip_status()
        clocks = self.clock_metrics()
        process = self.process_metrics()

        return {
            "tegrastats_available": self.tegrastats_available,
            "tegrastats_path": self.tegrastats_path,
            "tegrastats_error": self.tegrastats_error,
            "tegrastats_sample_count": len(samples),
            "tegrastats_parse_failure_count": self.parse_failure_count,
            "tegrastats_min_required_samples": MIN_REQUIRED_SAMPLES,
            "tegrastats_sample_gate_passed": len(samples) >= MIN_REQUIRED_SAMPLES,
            "ram_used_bytes": last.get("ram_used_bytes"),
            "ram_available_bytes": last.get("ram_available_bytes"),
            "ram_total_bytes": last.get("ram_total_bytes"),
            "ram_used_bytes_stats": _stat("ram_used_bytes"),
            "swap_used_bytes": last.get("swap_used_bytes"),
            "swap_total_bytes": last.get("swap_total_bytes"),
            "cpu_utilization_percent": last.get("cpu_utilization_percent"),
            "cpu_utilization_percent_stats": _stat("cpu_utilization_percent"),
            "gr3d_gpu_utilization_percent": last.get("gr3d_gpu_utilization_percent"),
            "gr3d_gpu_utilization_percent_stats": _stat("gr3d_gpu_utilization_percent"),
            "emc_utilization_percent": last.get("emc_utilization_percent"),
            "cpu_temperature_c": last.get("cpu_temperature_c"),
            "cpu_temperature_c_stats": _stat("cpu_temperature_c"),
            "gpu_temperature_c": last.get("gpu_temperature_c"),
            "gpu_temperature_c_stats": _stat("gpu_temperature_c"),
            "soc_temperature_c": last.get("soc_temperature_c"),
            "tj_temperature_c": last.get("tj_temperature_c"),
            "cpu_frequency_hz": last.get("cpu_frequency_hz") or clocks.get("cpu_frequency_hz"),
            "gpu_frequency_hz": clocks.get("gpu_frequency_hz"),
            "power_measurement_available": power_available,
            "power_metrics": power_metrics,
            "power_inference_from_utilization": False,
            "nvpmodel_modified": False,
            "clocks_modified": False,
            "thermal_policy_modified": False,
            **thermal,
            **process,
        }
