"""Phase 13C FP16 engine build — runs on the real Jetson only.

A serialized TensorRT plan is not portable across TensorRT version, CUDA
version, GPU or precision, so the engine is **always** built on the target and
never copied from Windows. The builder is selected from what the board actually
provides (TensorRT 8.5 Python builder, or the JetPack ``trtexec``), and the
resulting engine is bound to its inputs by an engine cache key.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
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

from run_phase13c_checks import (  # noqa: E402
    BOUNDARY_FIELDS,
    PHASE,
    STATUS_BLOCKED,
    STATUS_ENGINE_PASS,
    Phase13CEvidence,
    new_run_id,
    run_command,
    utc_now_iso,
)
from workers.core.tensorrt_asset_contract import (
    DEFAULT_PRECISION,
    EngineManifest,
    ModelManifest,
    PostprocessProfile,
    describe_file,
    engine_cache_key,
    evaluate_engine_staleness,
    verify_onnx_asset,
)
from workers.core.tensorrt_runtime import (
    DEFAULT_WORKSPACE_BYTES,
    TensorRTEngineRunner,
    TensorRTRuntimeError,
    cuda_preflight,
    tensorrt_preflight,
)

TRTEXEC_CANDIDATES = (
    "/usr/src/tensorrt/bin/trtexec",
    "/usr/local/tensorrt/bin/trtexec",
)


def find_trtexec() -> Optional[str]:
    explicit = os.environ.get("MA_VLNA_TRTEXEC", "").strip()
    if explicit and os.path.isfile(explicit):
        return explicit
    for candidate in TRTEXEC_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    return shutil.which("trtexec")


def jetson_identity() -> Dict[str, Any]:
    """Read-only board identity. Never changes nvpmodel, clocks or thermals."""

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

    gpu_name = model or "unknown"
    compute_capability = ""
    try:
        import tensorrt as trt  # type: ignore[import-not-found]

        # TensorRT does not expose SM directly; the Orin NX GPU is SM 8.7.
        if "orin" in gpu_name.lower():
            compute_capability = "8.7"
        _ = trt
    except Exception:
        pass

    return {
        "jetson_model": model,
        "gpu_name": gpu_name,
        "compute_capability": compute_capability,
        "l4t_release": l4t,
        "jetson_arch": platform.machine(),
        "real_jetson_detected": platform.machine() == "aarch64" and bool(l4t),
        "python_version": platform.python_version(),
        "nvpmodel_modified": False,
        "clocks_modified": False,
        "jetson_clocks_invoked": False,
        "thermal_policy_modified": False,
    }


def build_with_trtexec(
    *,
    trtexec: str,
    onnx_path: Path,
    engine_path: Path,
    input_name: str,
    input_shape: str,
    workspace_bytes: int,
    timeout_sec: int,
) -> Dict[str, Any]:
    """Build with the JetPack trtexec, using TensorRT 8 flag names only."""

    help_probe = run_command([trtexec, "--help"], timeout=120)
    help_text = (help_probe["stdout"] + help_probe["stderr"]).lower()
    # TensorRT 8.5 uses --workspace (MiB); TensorRT 10 replaced it with
    # --memPoolSize. Select from the binary's own help, never assumed.
    uses_mem_pool = "--mempoolsize" in help_text
    workspace_mib = max(1, int(workspace_bytes // (1024 * 1024)))

    command = [
        trtexec,
        "--onnx=%s" % onnx_path,
        "--saveEngine=%s" % engine_path,
        "--fp16",
        "--shapes=%s:%s" % (input_name, input_shape.replace("x", "x")),
    ]
    if uses_mem_pool:
        command.append("--memPoolSize=workspace:%dM" % workspace_mib)
    else:
        command.append("--workspace=%d" % workspace_mib)

    started = time.perf_counter_ns()
    result = run_command(command, timeout=timeout_sec)
    duration = (time.perf_counter_ns() - started) / 1e9
    return {
        "engine_builder": "trtexec",
        "engine_build_command": command,
        "engine_build_returncode": result["returncode"],
        "engine_build_duration_sec": round(duration, 3),
        "engine_build_stdout_tail": result["stdout"].strip().splitlines()[-25:],
        "engine_build_stderr_tail": result["stderr"].strip().splitlines()[-15:],
        "trtexec_help_uses_mem_pool": uses_mem_pool,
        "trtexec_path": trtexec,
    }


def build_with_python_api(
    *,
    onnx_path: Path,
    engine_path: Path,
    input_shape: List[int],
    workspace_bytes: int,
) -> Dict[str, Any]:
    """Build with the TensorRT 8.5 Python builder as the fallback path."""

    import tensorrt as trt  # type: ignore[import-not-found]

    started = time.perf_counter_ns()
    logger = trt.Logger(trt.Logger.WARNING)
    builder = trt.Builder(logger)
    network = builder.create_network(
        1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH)
    )
    parser = trt.OnnxParser(network, logger)
    with open(str(onnx_path), "rb") as handle:
        if not parser.parse(handle.read()):
            errors = [str(parser.get_error(index)) for index in range(parser.num_errors)]
            return {
                "engine_builder": "tensorrt_python",
                "engine_build_returncode": 1,
                "onnx_parser_errors": errors,
                "engine_build_duration_sec": round((time.perf_counter_ns() - started) / 1e9, 3),
            }

    config = builder.create_builder_config()
    if hasattr(config, "set_memory_pool_limit"):
        config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, int(workspace_bytes))
    else:  # pragma: no cover - older TensorRT 8 point releases
        config.max_workspace_size = int(workspace_bytes)
    if not builder.platform_has_fast_fp16:
        return {
            "engine_builder": "tensorrt_python",
            "engine_build_returncode": 1,
            "error": "fp16_unsupported",
            "engine_build_duration_sec": round((time.perf_counter_ns() - started) / 1e9, 3),
        }
    config.set_flag(trt.BuilderFlag.FP16)

    profile = builder.create_optimization_profile()
    input_tensor = network.get_input(0)
    profile.set_shape(input_tensor.name, tuple(input_shape), tuple(input_shape), tuple(input_shape))
    config.add_optimization_profile(profile)

    plan = builder.build_serialized_network(network, config)
    duration = (time.perf_counter_ns() - started) / 1e9
    if plan is None:
        return {
            "engine_builder": "tensorrt_python",
            "engine_build_returncode": 1,
            "error": "build_serialized_network returned None",
            "engine_build_duration_sec": round(duration, 3),
        }
    engine_path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(engine_path), "wb") as handle:
        handle.write(plan)
    return {
        "engine_builder": "tensorrt_python",
        "engine_build_command": ["<tensorrt.Builder>", str(onnx_path), str(engine_path)],
        "engine_build_returncode": 0,
        "engine_build_duration_sec": round(duration, 3),
        "network_input_name": str(input_tensor.name),
    }


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13C target FP16 engine build")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--onnx", required=True)
    parser.add_argument("--engine", required=True)
    parser.add_argument("--model-manifest", default="")
    parser.add_argument("--engine-manifest", default="")
    parser.add_argument("--precision", default=DEFAULT_PRECISION, choices=("fp16",))
    parser.add_argument("--input-shape", default="1x3x640x640")
    parser.add_argument("--input-name", default="images")
    parser.add_argument("--profile", default="yolov9-c")
    parser.add_argument("--workspace-bytes", type=int, default=DEFAULT_WORKSPACE_BYTES)
    parser.add_argument("--builder", default="auto", choices=("auto", "trtexec", "python"))
    parser.add_argument("--build-timeout-sec", type=int, default=3600)
    parser.add_argument("--output-dir", default="experiments/phase13")
    parser.add_argument("--require-real-jetson", action="store_true")
    parser.add_argument("--require-engine", action="store_true")
    parser.add_argument("--force-rebuild", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    run_id = args.run_id or new_run_id()
    evidence = Phase13CEvidence(Path(args.output_dir), run_id)

    identity = jetson_identity()
    trt_report = tensorrt_preflight()
    cuda_report = cuda_preflight()
    summary = {
        "phase": PHASE,
        "gate": "B_engine_build",
        "run_id": run_id,
        "created_at_utc": utc_now_iso(),
        "jetson": identity,
        "tensorrt": trt_report,
        "cuda": cuda_report,
        "fp16_engine_built_on_target": False,
        "fp16_engine_verified": False,
        "engine_deserialization_verified": False,
        "engine_binding_contract_verified": False,
    }  # type: Dict[str, Any]
    blockers = []  # type: List[str]

    if args.require_real_jetson and not identity["real_jetson_detected"]:
        blockers.append("jetson_environment_mismatch")
    if not trt_report["tensorrt_available"]:
        blockers.append("tensorrt_builder_unavailable")
    elif trt_report["tensorrt_major"] != 8:
        blockers.append("tensorrt_builder_unavailable")
    if cuda_report["cuda_allocator_backend"] == "unavailable":
        blockers.append("cuda_runtime_unavailable")

    onnx_path = Path(args.onnx)
    engine_path = Path(args.engine)
    model_manifest = None  # type: Optional[ModelManifest]
    if args.model_manifest and Path(args.model_manifest).is_file():
        model_manifest = ModelManifest.load(Path(args.model_manifest))
    elif onnx_path.with_suffix(".manifest.json").is_file():
        model_manifest = ModelManifest.load(onnx_path.with_suffix(".manifest.json"))

    onnx_report = verify_onnx_asset(
        onnx_path, expected_sha256=model_manifest.onnx_sha256 if model_manifest else ""
    )
    summary["onnx"] = onnx_report
    blockers.extend(onnx_report["blockers"])

    input_shape = [int(value) for value in str(args.input_shape).lower().split("x")]
    postprocess = PostprocessProfile(name=str(args.profile))
    if model_manifest and model_manifest.postprocess_profile:
        stored = model_manifest.postprocess_profile
        postprocess = PostprocessProfile(
            name=str(stored.get("name", args.profile)),
            confidence_threshold=float(stored.get("confidence_threshold", 0.25)),
            nms_iou_threshold=float(stored.get("nms_iou_threshold", 0.45)),
            max_detections=int(stored.get("max_detections", 300)),
        )

    engine_manifest_path = (
        Path(args.engine_manifest) if args.engine_manifest else engine_path.with_suffix(".manifest.json")
    )
    cache_key = engine_cache_key(
        onnx_sha256=onnx_report["onnx_sha256"] or "",
        tensorrt_version=trt_report["tensorrt_version"],
        cuda_version=cuda_report["cuda_runtime_version"],
        gpu_name=identity["gpu_name"],
        compute_capability=identity["compute_capability"],
        precision=args.precision,
        input_profile=args.input_shape,
        postprocess_profile=postprocess.cache_fragment(),
    )
    summary["engine_cache_key"] = cache_key

    # Reuse a cached engine only when every cache-key axis still matches.
    reuse = False
    if engine_manifest_path.is_file() and engine_path.is_file() and not args.force_rebuild:
        try:
            existing = EngineManifest.load(engine_manifest_path)
            verdict = evaluate_engine_staleness(
                existing,
                engine_path=engine_path,
                observed_onnx_sha256=onnx_report["onnx_sha256"] or "",
                observed_tensorrt_version=trt_report["tensorrt_version"],
                observed_cuda_version=cuda_report["cuda_runtime_version"],
                observed_gpu_name=identity["gpu_name"],
                observed_compute_capability=identity["compute_capability"],
                precision=args.precision,
                input_profile=args.input_shape,
                postprocess_profile=postprocess.cache_fragment(),
            )
            summary["cached_engine"] = verdict.to_dict()
            reuse = not verdict.stale
        except Exception as exc:
            summary["cached_engine_error"] = repr(exc)[:200]

    build_report = {}  # type: Dict[str, Any]
    if not blockers and not reuse:
        builder = args.builder
        trtexec = find_trtexec()
        summary["trtexec_path"] = trtexec
        if builder == "auto":
            builder = "trtexec" if trtexec else "python"
        if builder == "trtexec":
            if not trtexec:
                blockers.append("trtexec_unavailable")
            else:
                build_report = build_with_trtexec(
                    trtexec=trtexec,
                    onnx_path=onnx_path,
                    engine_path=engine_path,
                    input_name=args.input_name,
                    input_shape=args.input_shape,
                    workspace_bytes=int(args.workspace_bytes),
                    timeout_sec=int(args.build_timeout_sec),
                )
        if builder == "python" or (build_report and build_report.get("engine_build_returncode")):
            try:
                build_report = build_with_python_api(
                    onnx_path=onnx_path,
                    engine_path=engine_path,
                    input_shape=input_shape,
                    workspace_bytes=int(args.workspace_bytes),
                )
            except Exception as exc:
                build_report = {
                    "engine_builder": "tensorrt_python",
                    "engine_build_returncode": 1,
                    "error": repr(exc)[:300],
                }
        if build_report.get("engine_build_returncode") not in (0, None):
            blockers.append("engine_build_failed")
    summary["build"] = build_report

    engine_info = describe_file(engine_path)
    summary["engine"] = engine_info
    if not engine_info["exists"] and not blockers:
        blockers.append("engine_build_failed")

    engine_manifest = None  # type: Optional[EngineManifest]
    if engine_info["exists"] and not blockers:
        try:
            runner = TensorRTEngineRunner(
                str(engine_path),
                expected_input_shape=input_shape,
                expected_input_name=args.input_name,
            )
        except TensorRTRuntimeError as exc:
            blockers.append(exc.classification)
            summary["engine_load_error"] = exc.message
        else:
            try:
                bindings = runner.binding_report()
                summary.update(bindings)
                summary["engine_deserialization_verified"] = True
                summary["engine_binding_contract_verified"] = True
                summary["fp16_engine_built_on_target"] = True
                summary["fp16_engine_verified"] = True
                engine_manifest = EngineManifest(
                    engine_path=str(engine_path),
                    engine_sha256=engine_info["sha256"] or "",
                    engine_size_bytes=int(engine_info["size_bytes"] or 0),
                    engine_precision=str(args.precision),
                    engine_builder=str(build_report.get("engine_builder", "reused")),
                    engine_build_command=list(build_report.get("engine_build_command", [])),
                    engine_build_duration_sec=float(build_report.get("engine_build_duration_sec", 0.0)),
                    workspace_limit_bytes=int(args.workspace_bytes),
                    onnx_sha256=onnx_report["onnx_sha256"] or "",
                    onnx_path=str(onnx_path),
                    tensorrt_version=trt_report["tensorrt_version"],
                    cuda_version=cuda_report["cuda_runtime_version"],
                    jetson_model=identity["jetson_model"],
                    gpu_name=identity["gpu_name"],
                    compute_capability=identity["compute_capability"],
                    input_profile=str(args.input_shape),
                    postprocess_profile=postprocess.cache_fragment(),
                    engine_cache_key=cache_key,
                    engine_binding_count=int(bindings["engine_binding_count"]),
                    engine_input_bindings=bindings["engine_input_bindings"],
                    engine_output_bindings=bindings["engine_output_bindings"],
                    engine_dynamic_shapes=bool(bindings["engine_dynamic_shapes"]),
                    engine_serialization_verified=True,
                    engine_deserialization_verified=True,
                    engine_compatibility_verified=True,
                    int8_engine_built=False,
                    dla_enabled=False,
                    built_on_target=True,
                    created_at_utc=utc_now_iso(),
                )
                engine_manifest.write(engine_manifest_path)
                summary["engine_manifest_path"] = str(engine_manifest_path)
            finally:
                runner.close()

    summary["blockers"] = sorted(set(blockers))
    passed = bool(summary["fp16_engine_verified"]) and not summary["blockers"]
    summary["status"] = STATUS_ENGINE_PASS if passed else STATUS_BLOCKED
    summary.update(BOUNDARY_FIELDS)

    evidence.write_json("summary.json", summary)
    evidence.write_json(
        "engine_manifest.json",
        engine_manifest.to_dict() if engine_manifest else {"executed": False, "blockers": summary["blockers"]},
    )
    evidence.write_json(
        "environment.json", {"jetson": identity, "tensorrt": trt_report, "cuda": cuda_report}
    )
    evidence.write_json(
        "manifest.json",
        {
            "phase": PHASE,
            "gate": "B_engine_build",
            "run_id": run_id,
            "status": summary["status"],
            "created_at_utc": utc_now_iso(),
            "evidence_dir": str(evidence.run_dir),
            "generated_evidence_git_policy": "ignored_local_only",
            **BOUNDARY_FIELDS,
        },
    )
    evidence.write_text(
        "commands.txt", "# Phase 13C engine build\n%s %s\n" % (sys.executable, " ".join(sys.argv))
    )
    evidence.write_text(
        "README.md",
        "# Phase 13C engine build evidence\n\nRun id: `%s`\n\nStatus: `%s`\n\n"
        "The FP16 engine is built on the real Jetson; a serialized plan is never "
        "copied from another machine.\n" % (run_id, summary["status"]),
    )

    print(summary["status"])
    print("run_id=%s" % run_id)
    print("evidence_dir=%s" % evidence.run_dir)
    print("engine_path=%s" % engine_path)
    print("engine_sha256=%s" % (engine_info["sha256"] or ""))
    print("fp16_engine_built_on_target=%s" % summary["fp16_engine_built_on_target"])
    print("engine_binding_contract_verified=%s" % summary["engine_binding_contract_verified"])
    if summary["blockers"]:
        print("blockers=%s" % ",".join(summary["blockers"]), file=sys.stderr)
    if args.require_engine and not passed:
        return 1
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
