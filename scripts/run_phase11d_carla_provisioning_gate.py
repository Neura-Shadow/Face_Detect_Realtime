"""
Phase 11D CARLA Runtime Provisioning Gate.

此腳本是 read-only provisioning preflight，不會下載、安裝或啟動 CARLA。
它的目標是回答一個問題：

    這台機器是否已經具備 Phase 11C real CARLA runtime execution 的前提？

Phase 11C 狀態必須維持嚴格：

    Phase 11C Blocked Locally — real CARLA runtime execution attempted with
    --require-server, but local environment lacks both carla Python package
    and reachable CARLA server.

只有當本腳本顯示 provisioning ready，且
`scripts/run_phase11b_real_carla_smoke.py --require-server` 真正通過後，
才可升級為 CARLA Server Runtime Pass。
"""

from __future__ import annotations

import argparse
import csv
import glob
import importlib.util
import json
import os
import platform
import socket
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

Status = Literal["pass", "fail", "warn", "info"]

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class GateCheck:
    """單一 provisioning gate 檢查結果。"""

    name: str
    status: Status
    detail: str
    remediation: str = ""


@dataclass(frozen=True)
class ProvisioningReport:
    """Phase 11D provisioning gate 的結構化報告。"""

    phase: str
    status: str
    timestamp_utc: str
    host: str
    port: int
    checks: list[GateCheck]
    next_runtime_command: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


def _run_command(command: list[str], timeout_sec: float = 8.0) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            check=False,
        )
        return completed.returncode, completed.stdout.strip(), completed.stderr.strip()
    except Exception as exc:
        return 1, "", str(exc)


def _is_local_host(host: str) -> bool:
    return host in {"127.0.0.1", "localhost", "::1"} or host.startswith("127.")


def _check_python() -> GateCheck:
    return GateCheck(
        name="python_interpreter",
        status="pass",
        detail=f"{sys.executable} ({platform.python_version()})",
    )


def _check_carla_import() -> GateCheck:
    spec = importlib.util.find_spec("carla")
    if spec is None:
        return GateCheck(
            name="carla_python_package",
            status="fail",
            detail="carla Python package is not importable in the active interpreter.",
            remediation=(
                "Install the CARLA Python wheel that matches the CARLA server package, "
                "then rerun this gate from the same Python interpreter."
            ),
        )

    version = "unknown"
    try:
        import carla  # type: ignore[import-not-found]

        version = str(getattr(carla, "__version__", "unknown"))
    except Exception as exc:
        return GateCheck(
            name="carla_python_package",
            status="fail",
            detail=f"carla package found at {spec.origin}, but import failed: {exc}",
            remediation="Reinstall the CARLA wheel for this Python ABI and platform.",
        )

    return GateCheck(
        name="carla_python_package",
        status="pass",
        detail=f"carla import ok; version={version}; origin={spec.origin}",
    )


def _check_pip_show() -> GateCheck:
    code, stdout, stderr = _run_command([sys.executable, "-m", "pip", "show", "carla"])
    if code != 0:
        detail = stderr or stdout or "pip show carla returned no package."
        return GateCheck(
            name="pip_package_metadata",
            status="warn",
            detail=detail,
            remediation="This is expected if CARLA is not installed in the active interpreter.",
        )
    one_line = " | ".join(line for line in stdout.splitlines() if line.startswith(("Name:", "Version:", "Location:")))
    return GateCheck(name="pip_package_metadata", status="pass", detail=one_line or stdout)


def _tcp_reachable(host: str, port: int, timeout_sec: float) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_sec):
            return True
    except OSError:
        return False


def _check_tcp(host: str, port: int, timeout_sec: float) -> GateCheck:
    if _tcp_reachable(host, port, timeout_sec):
        return GateCheck(
            name="carla_tcp_endpoint",
            status="pass",
            detail=f"{host}:{port} is reachable.",
        )
    return GateCheck(
        name="carla_tcp_endpoint",
        status="fail",
        detail=f"{host}:{port} is not reachable.",
        remediation="Start CARLA server, confirm RPC port, and check firewall or container port publishing.",
    )


def _expand_roots(values: list[str]) -> list[Path]:
    roots: list[Path] = []
    for raw in values:
        if not raw:
            continue
        expanded = os.path.expandvars(os.path.expanduser(raw))
        matches = glob.glob(expanded)
        for match in matches or [expanded]:
            path = Path(match)
            if path.exists() and path.is_dir():
                roots.append(path.resolve())
    seen: set[str] = set()
    unique: list[Path] = []
    for root in roots:
        key = str(root).lower()
        if key not in seen:
            seen.add(key)
            unique.append(root)
    return unique


def _candidate_root_patterns(extra_roots: list[str]) -> list[str]:
    home = str(Path.home())
    patterns = list(extra_roots)
    for env_key in ("CARLA_ROOT", "CARLA_HOME"):
        value = os.getenv(env_key)
        if value:
            patterns.append(value)
    patterns.extend(
        [
            r"C:\CARLA*",
            r"D:\CARLA*",
            rf"{home}\Downloads\CARLA*",
            rf"{home}\Documents\CARLA*",
            "/opt/carla*",
            "/usr/local/carla*",
            "~/CARLA*",
            "~/Downloads/CARLA*",
        ]
    )
    return patterns


def _find_server_executables(roots: list[Path], max_results: int = 20) -> list[Path]:
    names = ("CarlaUE4.exe", "CarlaUnreal.exe", "CarlaUE4.sh", "CarlaUnreal.sh")
    found: list[Path] = []
    for root in roots:
        for name in names:
            direct = root / name
            if direct.exists():
                found.append(direct)
        for pattern in names:
            try:
                for candidate in root.glob(f"**/{pattern}"):
                    found.append(candidate)
                    if len(found) >= max_results:
                        return _unique_paths(found)
            except OSError:
                continue
    return _unique_paths(found)


def _find_wheels(roots: list[Path], max_results: int = 30) -> list[Path]:
    found: list[Path] = []
    for root in roots:
        try:
            for candidate in root.glob("**/carla-*.whl"):
                found.append(candidate)
                if len(found) >= max_results:
                    return _unique_paths(found)
        except OSError:
            continue
    return _unique_paths(found)


def _unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _compatible_wheels(wheels: list[Path]) -> list[Path]:
    cp_tag = f"cp{sys.version_info.major}{sys.version_info.minor}"
    py_tag = "py3"
    compatible: list[Path] = []
    for wheel in wheels:
        name = wheel.name.lower()
        if cp_tag in name or py_tag in name:
            compatible.append(wheel)
    return compatible


def _check_roots(roots: list[Path], executables: list[Path], wheels: list[Path]) -> GateCheck:
    if roots:
        display = "; ".join(str(root) for root in roots[:6])
        suffix = "" if len(roots) <= 6 else f"; +{len(roots) - 6} more"
        status: Status = "pass" if (executables or wheels) else "warn"
        detail = f"candidate roots: {display}{suffix}"
        if status == "warn":
            detail += " (no CARLA server executable or carla wheel found under these roots)"
        return GateCheck(
            name="carla_server_package_root",
            status=status,
            detail=detail,
            remediation="" if status == "pass" else "Set CARLA_ROOT to the extracted CARLA package directory.",
        )
    return GateCheck(
        name="carla_server_package_root",
        status="fail",
        detail="No CARLA package root found in CARLA_ROOT/CARLA_HOME or common install paths.",
        remediation="Download/extract CARLA, then set CARLA_ROOT to the package directory.",
    )


def _check_server_executable(executables: list[Path], host: str) -> GateCheck:
    if executables:
        display = "; ".join(str(path) for path in executables[:5])
        return GateCheck(name="carla_server_executable", status="pass", detail=display)
    status: Status = "fail" if _is_local_host(host) else "warn"
    return GateCheck(
        name="carla_server_executable",
        status=status,
        detail="No CarlaUE4/CarlaUnreal server executable found locally.",
        remediation="For local server, install/extract CARLA package. For remote server, ensure --host points to it.",
    )


def _check_wheels(wheels: list[Path], carla_import_ok: bool) -> GateCheck:
    compatible = _compatible_wheels(wheels)
    if compatible:
        display = "; ".join(str(path) for path in compatible[:5])
        return GateCheck(name="carla_wheel_candidate", status="pass", detail=display)
    if wheels:
        display = "; ".join(str(path) for path in wheels[:5])
        return GateCheck(
            name="carla_wheel_candidate",
            status="warn" if carla_import_ok else "fail",
            detail=f"wheel candidates found, but none clearly match Python {platform.python_version()}: {display}",
            remediation="Use a Python version matching the CARLA wheel ABI, or install a compatible CARLA wheel.",
        )
    return GateCheck(
        name="carla_wheel_candidate",
        status="warn" if carla_import_ok else "fail",
        detail="No local carla-*.whl candidates found under CARLA package roots.",
        remediation="Use the CARLA package wheel under PythonAPI/carla/dist or install an official matching package.",
    )


def _list_carla_processes() -> list[str]:
    if platform.system().lower() == "windows":
        code, stdout, _ = _run_command(["tasklist", "/FO", "CSV", "/NH"], timeout_sec=8.0)
        if code != 0 or not stdout:
            return []
        processes: list[str] = []
        for row in csv.reader(stdout.splitlines()):
            if not row:
                continue
            name = row[0]
            if any(token in name.lower() for token in ("carla", "ue4", "unreal")):
                processes.append(", ".join(row[:2]))
        return processes

    code, stdout, _ = _run_command(["ps", "-A", "-o", "pid=,comm=,args="], timeout_sec=8.0)
    if code != 0:
        return []
    return [
        line.strip()
        for line in stdout.splitlines()
        if any(token in line.lower() for token in ("carla", "ue4", "unreal"))
    ]


def _check_processes(host: str, tcp_ok: bool) -> GateCheck:
    processes = _list_carla_processes()
    if processes:
        return GateCheck(
            name="carla_server_process",
            status="pass",
            detail="; ".join(processes[:5]),
        )
    if not _is_local_host(host):
        return GateCheck(
            name="carla_server_process",
            status="info",
            detail="No local CARLA process found; remote host mode does not require a local process.",
        )
    status: Status = "warn" if tcp_ok else "fail"
    return GateCheck(
        name="carla_server_process",
        status=status,
        detail="No local CARLA/UE4/Unreal process found.",
        remediation="Start CARLA server before running Phase 11C real runtime.",
    )


def _build_report(args: argparse.Namespace) -> ProvisioningReport:
    roots = _expand_roots(_candidate_root_patterns(args.carla_root))
    executables = _find_server_executables(roots)
    wheels = _find_wheels(roots)

    python_check = _check_python()
    import_check = _check_carla_import()
    pip_check = _check_pip_show()
    tcp_check = _check_tcp(args.host, args.port, args.timeout_sec)
    root_check = _check_roots(roots, executables, wheels)
    executable_check = _check_server_executable(executables, args.host)
    wheel_check = _check_wheels(wheels, import_check.status == "pass")
    process_check = _check_processes(args.host, tcp_check.status == "pass")

    checks = [
        python_check,
        import_check,
        pip_check,
        root_check,
        executable_check,
        wheel_check,
        process_check,
        tcp_check,
    ]

    required_names = {"carla_python_package", "carla_tcp_endpoint"}
    required_failed = [check for check in checks if check.name in required_names and check.status != "pass"]
    status = "ready" if not required_failed else "blocked"
    runtime_command = (
        f"{sys.executable} scripts\\run_phase11b_real_carla_smoke.py "
        f"--host {args.host} --port {args.port} --steps {args.steps} --require-server"
    )
    return ProvisioningReport(
        phase="Phase 11D — CARLA Runtime Provisioning Gate",
        status=status,
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
        host=args.host,
        port=args.port,
        checks=checks,
        next_runtime_command=runtime_command,
    )


def _print_text(report: ProvisioningReport) -> None:
    print(report.phase)
    print(f"status: {report.status}")
    print(f"target: {report.host}:{report.port}")
    print("")
    for check in report.checks:
        label = check.status.upper()
        print(f"[{label}] {check.name}: {check.detail}")
        if check.remediation:
            print(f"  remediation: {check.remediation}")
    print("")
    print(f"next_runtime_command: {report.next_runtime_command}")
    print(f"phase11d carla provisioning gate {report.status}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MA-VLNA Phase 11D CARLA runtime provisioning gate")
    parser.add_argument("--host", default="127.0.0.1", help="CARLA server host")
    parser.add_argument("--port", type=int, default=2000, help="CARLA server RPC port")
    parser.add_argument("--timeout-sec", type=float, default=3.0, help="TCP preflight timeout")
    parser.add_argument("--steps", type=int, default=5, help="Next Phase 11C runtime smoke step count")
    parser.add_argument(
        "--carla-root",
        action="append",
        default=[],
        help="Additional CARLA package root. Can be supplied multiple times.",
    )
    parser.add_argument("--json", action="store_true", help="Print structured JSON report")
    parser.add_argument("--require-ready", action="store_true", help="Exit 1 unless provisioning status is ready")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = _build_report(args)
    if args.json:
        print(report.to_json())
    else:
        _print_text(report)
    if args.require_ready and report.status != "ready":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
