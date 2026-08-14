"""Phase 13F startup preflight for the supervised Jetson service.

A service that restarts unattended must re-establish, every single time, that
it is the thing it claims to be. This module answers that in one pass and
returns a verdict that is safe to act on: **a failed preflight must not start
AI authority.**

Every check is independent and every one records what it observed rather than
only whether it liked it, so a failure says what was actually found. Checks are
grouped as *required* (a failure blocks AI authority) and *advisory* (recorded,
does not block) — the split is explicit rather than implied by ordering.

Nothing here modifies the system. It reads files, imports libraries, asks the
kernel for a route, and tests whether paths are writable by writing and
removing a temporary file inside them.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import os
import platform
import socket
import subprocess
import sys
import tempfile
from typing import Any, Callable, Dict, List, Optional

from workers.core.service_manifest import ManifestError, ServiceManifest

#: Frozen Phase 13A wire contract. These are re-asserted at every service start
#: because a service is allowed to restart into a repository that changed.
EXPECTED_COMMAND_PACKET_SIZE = 64
EXPECTED_ACK_PACKET_SIZE = 48
EXPECTED_FRAME_HEADER_SIZE = 56
EXPECTED_PROTOCOL_VERSION = 1
EXPECTED_MACHINE = "aarch64"


class CheckResult:
    """One preflight observation."""

    __slots__ = ("name", "passed", "required", "detail", "observed", "expected")

    def __init__(
        self,
        name: str,
        passed: bool,
        *,
        required: bool = True,
        detail: str = "",
        observed: Any = None,
        expected: Any = None,
    ) -> None:
        self.name = name
        self.passed = bool(passed)
        self.required = bool(required)
        self.detail = detail
        self.observed = observed
        self.expected = expected

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check": self.name,
            "passed": self.passed,
            "required": self.required,
            "detail": self.detail,
            "observed": self.observed,
            "expected": self.expected,
        }


class PreflightReport:
    """Aggregate verdict. ``ai_authority_permitted`` is the one to act on."""

    def __init__(self, checks: List[CheckResult]) -> None:
        self.checks = list(checks)

    @property
    def failures(self) -> List[CheckResult]:
        return [item for item in self.checks if not item.passed and item.required]

    @property
    def advisories(self) -> List[CheckResult]:
        return [item for item in self.checks if not item.passed and not item.required]

    @property
    def passed(self) -> bool:
        return not self.failures

    @property
    def ai_authority_permitted(self) -> bool:
        # Identical to `passed` today, and kept separate on purpose: the thing
        # callers must branch on is authority, not tidiness.
        return self.passed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "preflight_passed": self.passed,
            "ai_authority_permitted": self.ai_authority_permitted,
            "check_count": len(self.checks),
            "failed_required_checks": [item.name for item in self.failures],
            "failed_advisory_checks": [item.name for item in self.advisories],
            "checks": [item.to_dict() for item in self.checks],
        }


def _git_sha(repo_root: str) -> str:
    """The commit this tree came from.

    Two cases, and the second is not a fallback so much as the normal one in
    production. A git checkout answers with ``git rev-parse``. An **immutable
    release** has no ``.git`` at all -- that is the point of it -- so the commit
    is read from the release manifest sitting at the release root, whose hash
    was validated before the release was allowed to become ``current``.

    Reading it from the manifest is not weaker than asking git. A checkout can
    be changed under the running service by a ``git pull``; a release cannot,
    and its manifest is covered by the package hash. What the check is for is
    "is the running code the code we validated", and in a release the manifest
    is the more direct answer.
    """

    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        if completed.returncode == 0:
            sha = completed.stdout.decode("utf-8", "replace").strip()
            if sha:
                return sha
    except (OSError, subprocess.SubprocessError):
        pass
    return _release_source_sha(repo_root)


def _release_source_sha(repo_root: str) -> str:
    """``source_git_sha`` from the release manifest, when this is a release."""

    for name in ("release.manifest.json", os.path.join("config", "release.manifest.json")):
        path = os.path.join(repo_root, name)
        if not os.path.isfile(path):
            continue
        try:
            import json

            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, ValueError):
            continue
        sha = str(payload.get("source_git_sha", "")).strip()
        if sha:
            return sha
    return ""


def _path_writable(path: str) -> bool:
    """Prove a directory is writable by writing to it, not by asking."""

    try:
        os.makedirs(path, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(dir=path, prefix=".phase13f-", delete=True)
        handle.close()
        return True
    except (OSError, ValueError):
        return False


def _port_free(host: str, port: int) -> bool:
    """Whether a TCP port can be bound right now."""

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, int(port)))
        return True
    except OSError:
        return False
    finally:
        try:
            sock.close()
        except OSError:
            pass


def _route_to(host: str) -> Dict[str, Any]:
    """Ask the kernel whether a route to the PC exists. Never modifies it."""

    try:
        completed = subprocess.run(
            ["ip", "route", "get", str(host)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "error": "%s: %s" % (type(exc).__name__, exc)}
    text = completed.stdout.decode("utf-8", "replace").strip()
    return {
        "available": completed.returncode == 0 and bool(text),
        "route": text.splitlines()[0] if text else "",
    }


def run_preflight(
    *,
    manifest_path: str,
    repo_root: str,
    expected_repo_sha: str = "",
    runtime_dir: str = "",
    evidence_dir: str = "",
    ports: Optional[Dict[str, int]] = None,
    bind_host: str = "0.0.0.0",
    pc_host: str = "",
    check_ports: bool = True,
    import_tensorrt: bool = True,
    machine_provider: Optional[Callable[[], str]] = None,
) -> PreflightReport:
    """Run every startup check and return the aggregate verdict."""

    checks = []  # type: List[CheckResult]

    # ── manifest ────────────────────────────────────────────────────────────
    manifest = None  # type: Optional[ServiceManifest]
    try:
        manifest = ServiceManifest.load(manifest_path)
        checks.append(
            CheckResult(
                "manifest_loadable", True,
                detail="schema v%d" % manifest.schema_version,
                observed=manifest.manifest_sha256,
            )
        )
    except ManifestError as exc:
        checks.append(
            CheckResult("manifest_loadable", False, detail=exc.message, observed=exc.classification)
        )

    # ── repository identity ─────────────────────────────────────────────────
    observed_sha = _git_sha(repo_root)
    expected = expected_repo_sha or (manifest.repository_sha if manifest else "")
    checks.append(
        CheckResult(
            "repository_sha_match",
            bool(observed_sha) and bool(expected) and observed_sha == expected,
            detail="service must run the commit it was built for",
            observed=observed_sha,
            expected=expected,
        )
    )

    # ── engine ──────────────────────────────────────────────────────────────
    if manifest is not None:
        engine = manifest.verify_engine()
        checks.append(
            CheckResult(
                "engine_present", bool(engine["engine_present"]),
                detail=manifest.engine_path, observed=engine["engine_size_bytes"],
            )
        )
        checks.append(
            CheckResult(
                "engine_hash_match", bool(engine["engine_hash_match"]),
                detail=str(engine.get("classification", "")),
                observed=engine["engine_sha256_observed"],
                expected=engine["engine_sha256_expected"],
            )
        )
        checks.append(
            CheckResult(
                "precision_is_authoritative", manifest.precision == "fp16",
                detail="only FP16 may hold command authority",
                observed=manifest.precision, expected="fp16",
            )
        )
        checks.append(
            CheckResult(
                "int8_not_authoritative",
                not bool(manifest.get("int8_authoritative", False)),
                detail="Phase 13D-MP-RECOVERY freeze",
                observed=manifest.get("int8_role"),
                expected="experimental_non_authoritative",
            )
        )

    # ── target identity ─────────────────────────────────────────────────────
    machine = (machine_provider or platform.machine)()
    checks.append(
        CheckResult(
            "jetson_aarch64", machine == EXPECTED_MACHINE,
            detail="service is only valid on the Jetson",
            observed=machine, expected=EXPECTED_MACHINE,
        )
    )
    tegra_release = ""
    try:
        with open("/etc/nv_tegra_release", "r", encoding="utf-8") as handle:
            tegra_release = handle.readline().strip()
    except OSError:
        tegra_release = ""
    checks.append(
        CheckResult(
            "tegra_release_readable", bool(tegra_release),
            required=False, detail="advisory identity record", observed=tegra_release,
        )
    )

    # ── CUDA / TensorRT ─────────────────────────────────────────────────────
    if import_tensorrt:
        try:
            import tensorrt  # type: ignore[import-not-found]

            trt_version = str(tensorrt.__version__)
            checks.append(
                CheckResult(
                    "tensorrt_importable", True,
                    detail="TensorRT 8.x binding API", observed=trt_version,
                )
            )
            checks.append(
                CheckResult(
                    "tensorrt_major_version", trt_version.startswith("8."),
                    detail="Phase 13C/13D used the TensorRT 8 binding API only",
                    observed=trt_version, expected="8.x",
                )
            )
        except Exception as exc:
            checks.append(
                CheckResult(
                    "tensorrt_importable", False,
                    detail="%s: %s" % (type(exc).__name__, exc), observed=None,
                )
            )
        cuda_version = _cuda_runtime_version()
        checks.append(
            CheckResult(
                "cuda_runtime_available", bool(cuda_version),
                detail="libcudart via ctypes; no PyCUDA dependency",
                observed=cuda_version,
            )
        )

    # ── protocol contract ───────────────────────────────────────────────────
    try:
        from workers.core.embedded_command_bridge import PACKET_SIZE, PROTOCOL_VERSION
        from workers.core.jil_protocol import ACK_PACKET_SIZE, FRAME_HEADER_SIZE

        sizes_ok = (
            PACKET_SIZE == EXPECTED_COMMAND_PACKET_SIZE
            and ACK_PACKET_SIZE == EXPECTED_ACK_PACKET_SIZE
            and FRAME_HEADER_SIZE == EXPECTED_FRAME_HEADER_SIZE
            and PROTOCOL_VERSION == EXPECTED_PROTOCOL_VERSION
        )
        checks.append(
            CheckResult(
                "protocol_contract_frozen", sizes_ok,
                detail="Phase 13A packet, JILA ACK and JILF header sizes",
                observed={
                    "command_packet_size": PACKET_SIZE,
                    "ack_packet_size": ACK_PACKET_SIZE,
                    "frame_header_size": FRAME_HEADER_SIZE,
                    "protocol_version": PROTOCOL_VERSION,
                },
                expected={
                    "command_packet_size": EXPECTED_COMMAND_PACKET_SIZE,
                    "ack_packet_size": EXPECTED_ACK_PACKET_SIZE,
                    "frame_header_size": EXPECTED_FRAME_HEADER_SIZE,
                    "protocol_version": EXPECTED_PROTOCOL_VERSION,
                },
            )
        )
    except Exception as exc:
        checks.append(
            CheckResult(
                "protocol_contract_frozen", False,
                detail="%s: %s" % (type(exc).__name__, exc),
            )
        )

    # ── writable paths ──────────────────────────────────────────────────────
    for label, path in (("runtime_dir_writable", runtime_dir), ("evidence_dir_writable", evidence_dir)):
        if not path:
            continue
        checks.append(
            CheckResult(label, _path_writable(path), detail=path, observed=path)
        )

    # ── ports ───────────────────────────────────────────────────────────────
    if check_ports and ports:
        for name, port in sorted(ports.items()):
            free = _port_free(bind_host, int(port))
            checks.append(
                CheckResult(
                    "port_available_%s" % name, free,
                    detail="a stale process holding this port blocks the service",
                    observed={"host": bind_host, "port": int(port), "free": free},
                )
            )

    # ── network route ───────────────────────────────────────────────────────
    if pc_host:
        route = _route_to(pc_host)
        checks.append(
            CheckResult(
                "route_to_pc", bool(route.get("available")),
                detail="required to reach the PC MCU and frame publisher",
                observed=route,
                expected=pc_host,
            )
        )

    return PreflightReport(checks)


def _cuda_runtime_version() -> Optional[int]:
    """CUDA runtime version via ctypes. No PyCUDA, no cuda-python."""

    import ctypes

    for name in ("libcudart.so", "libcudart.so.11.0", "libcudart.so.10.2"):
        try:
            library = ctypes.CDLL(name)
        except OSError:
            continue
        try:
            value = ctypes.c_int()
            if library.cudaRuntimeGetVersion(ctypes.byref(value)) == 0:
                return int(value.value)
        except AttributeError:
            continue
    return None
