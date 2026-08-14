"""Phase 13F startup-manifest builder.

Runs on the Jetson, because the manifest's whole value is that it records the
hash of the engine file that is actually on that machine. Building it on the PC
from a remembered digest would defeat the point.

The written manifest is runtime configuration, not source: it names host paths
and pins a commit, so it is generated on the target and is not committed. The
schema, the builder and the validator are source and are.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from workers.core.service_manifest import (  # noqa: E402
    ManifestError,
    ServiceManifest,
    build_manifest,
    describe_schema,
)

PHASE = "13F-JETSON-SERVICE-SUPERVISION-BOOT-RECOVERY"


def repository_sha(repo_root: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo_root,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.decode("utf-8", "replace").strip() if completed.returncode == 0 else ""


def tensorrt_version() -> str:
    try:
        import tensorrt  # type: ignore[import-not-found]

        return str(tensorrt.__version__)
    except Exception:
        return ""


def cuda_runtime_version() -> Optional[int]:
    import ctypes

    for name in ("libcudart.so", "libcudart.so.11.0"):
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


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13F manifest builder")
    parser.add_argument("--service-name", default="ma-vlna-jetson-node")
    parser.add_argument(
        "--engine",
        default="/home/myjetsonnx/models/ma-vlna/yolov9/yolov9-c-640-b1-trt852-fp16.engine",
    )
    parser.add_argument("--output", default="config/phase13f_service_manifest.json")
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--frame-port", type=int, default=48701)
    parser.add_argument("--control-port", type=int, default=48702)
    parser.add_argument("--command-port", type=int, default=48703)
    parser.add_argument("--ack-port", type=int, default=48704)
    parser.add_argument("--pc-host", default="192.168.55.100")
    parser.add_argument("--print-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    if not os.path.isfile(args.engine):
        print(json.dumps({
            "phase": PHASE, "ok": False,
            "error": "engine not found: %s" % args.engine,
        }, indent=2))
        return 2

    sha = repository_sha(args.repo_root)
    payload = build_manifest(
        service_name=args.service_name,
        repository_sha=sha,
        engine_path=os.path.abspath(args.engine),
        extra={
            # Recorded for evidence and for the preflight to compare against.
            # None of these grant anything; they describe what was true when
            # the manifest was built so drift is visible.
            "built_on_machine": platform.machine(),
            "built_on_python": platform.python_version(),
            "tensorrt_version": tensorrt_version(),
            "cuda_runtime_version": cuda_runtime_version(),
            "command_packet_size_bytes": 64,
            "ack_packet_size_bytes": 48,
            "frame_header_size_bytes": 56,
            "protocol_version": 1,
            "frame_port": int(args.frame_port),
            "control_port": int(args.control_port),
            "command_port": int(args.command_port),
            "ack_port": int(args.ack_port),
            "pc_host": args.pc_host,
            "command_authority_backend": "fp16_tensorrt_yolov9c",
            "full_hil_verified": False,
            "real_mcu_verified": False,
            "physical_camera_verified": False,
            "physical_actuator_control_executed": False,
            "secure_boot_verified": False,
            "ota_verified": False,
        },
    )

    # Parse what we just built, so a manifest that cannot be loaded is never
    # written in the first place.
    try:
        manifest = ServiceManifest(payload)
    except ManifestError as exc:
        print(json.dumps({
            "phase": PHASE, "ok": False,
            "classification": exc.classification, "error": exc.message,
        }, indent=2))
        return 3

    if args.print_only:
        print(json.dumps(manifest.to_dict(), indent=2, sort_keys=True))
        return 0

    output = Path(args.output)
    if not output.is_absolute():
        output = REPO_ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    verification = manifest.verify_engine()
    print(json.dumps({
        "phase": PHASE,
        "ok": bool(verification["engine_hash_match"]),
        "manifest_path": str(output),
        "manifest_sha256": manifest.manifest_sha256,
        "repository_sha": sha,
        "engine_path": manifest.engine_path,
        "engine_sha256": manifest.engine_sha256,
        "engine_size_bytes": verification["engine_size_bytes"],
        "precision": manifest.precision,
        "schema": describe_schema(),
    }, indent=2, sort_keys=True))
    return 0 if verification["engine_hash_match"] else 4


if __name__ == "__main__":
    raise SystemExit(main())
