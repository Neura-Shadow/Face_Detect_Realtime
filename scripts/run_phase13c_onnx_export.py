"""Phase 13C ONNX export gate (simulation PC).

Exports the external YOLOv9 weights to a fixed 1x3x640x640 ONNX graph and
records the full model manifest. It never downloads anything and never installs
a dependency.

Why this does not shell out to the external ``export.py``: that script calls
``check_requirements('onnx')``, which **pip-installs** ``onnx`` when it is
missing. Phase 13C forbids automatic dependency installation, so this gate
drives ``torch.onnx.export`` directly while reproducing the same contract that
``export.py``'s ONNX branch uses — ``input_names=['images']``,
``output_names=['output0']``, ``do_constant_folding=True``, fixed shape — and
loads the checkpoint through the repository's existing trusted YOLOv9 loader.

If the ``onnx`` package is absent the gate stops with
``onnx_export_dependency_missing`` and prints the exact operator command; it
never installs it.
"""

from __future__ import annotations

import argparse
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
    STATUS_PREPARED,
    Phase13CEvidence,
    new_run_id,
    pc_environment,
    utc_now_iso,
)
from workers.core.tensorrt_asset_contract import (
    DEFAULT_INPUT_SIZE,
    DEFAULT_MODEL_FAMILY,
    DEFAULT_MODEL_VARIANT,
    InputContract,
    ModelManifest,
    OutputContract,
    PostprocessProfile,
    describe_file,
    external_git_sha,
    resolve_external_path,
    verify_model_assets,
)

DEFAULT_OPSET = 12  # TensorRT 8.5 parses opset <= 17; 12 matches YOLOv9 export.py.


def dependency_preflight() -> Dict[str, Any]:
    """Report exactly which export dependencies exist. Installs nothing."""

    report = {
        "torch_available": False,
        "torch_version": "",
        "onnx_available": False,
        "onnx_version": "",
        "onnx_checker_available": False,
        "auto_install_performed": False,
    }  # type: Dict[str, Any]
    try:
        import torch  # type: ignore[import-not-found]

        report["torch_available"] = True
        report["torch_version"] = str(torch.__version__)
    except Exception as exc:
        report["torch_error"] = repr(exc)[:200]
    try:
        import onnx  # type: ignore[import-not-found]

        report["onnx_available"] = True
        report["onnx_version"] = str(getattr(onnx, "__version__", ""))
        report["onnx_checker_available"] = hasattr(onnx, "checker")
    except Exception as exc:
        report["onnx_error"] = repr(exc)[:200]
    return report


def unlock_commands(python_executable: str) -> List[str]:
    """Exact operator command to unlock the export. Never executed here."""

    return [
        "# Phase 13C ONNX export requires the `onnx` package in the export runtime.",
        "# Phase 13C never installs dependencies automatically. Run this yourself:",
        '"%s" -m pip install onnx' % python_executable,
        "# Optional, only if you want graph simplification:",
        '# "%s" -m pip install onnxsim' % python_executable,
        "# Then re-run scripts/run_phase13c_onnx_export.py.",
    ]


def load_yolov9_model(source_root: Path, weights: Path) -> Any:
    """Load the checkpoint through the repository's existing trusted loader."""

    import torch  # type: ignore[import-not-found]

    from workers.core.edge_perception import YOLOv9PerceptionBackend

    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))
    original_load = YOLOv9PerceptionBackend._patch_torch_load_for_trusted_yolov9_checkpoint(torch)
    try:
        from models.experimental import attempt_load  # type: ignore[import-not-found]

        model = attempt_load(str(weights), device=torch.device("cpu"), inplace=True, fuse=True)
    finally:
        torch.load = original_load
    model.eval()
    # `fuse=True` folds BatchNorm into the preceding convolution, so some
    # parameters become *computed* (non-leaf) tensors. Assigning
    # `requires_grad` on a non-leaf tensor raises, so only leaves are touched;
    # the export itself additionally runs under `torch.no_grad()`.
    for parameter in model.parameters():
        if parameter.is_leaf:
            parameter.requires_grad_(False)
    return model


def prepare_model_for_export(model: Any, *, img_size: int, batch_size: int) -> Dict[str, Any]:
    """Reproduce the vendor ``export.py`` model preparation, inspected not guessed.

    ``export.py``'s ``run()`` walks ``named_modules()`` and sets
    ``inplace`` / ``dynamic`` / ``export`` on every detect head before calling
    ``torch.onnx.export``, then performs two dry runs. Without ``export=True``
    the head *also* returns its three per-scale feature maps, and the exported
    graph gains three extra outputs alongside ``output0`` — which would make the
    recorded single-output contract a lie and force the engine to allocate and
    copy back tensors nothing consumes.
    """

    import torch  # type: ignore[import-not-found]

    report = {
        "detect_head_types_available": False,
        "detect_heads_prepared": [],
        "dry_runs": 0,
    }  # type: Dict[str, Any]
    try:
        from models.yolo import (  # type: ignore[import-not-found]
            DDetect,
            Detect,
            DualDDetect,
            DualDetect,
        )

        detect_types = (Detect, DDetect, DualDetect, DualDDetect)
        report["detect_head_types_available"] = True
    except Exception as exc:
        report["detect_head_import_error"] = repr(exc)[:200]
        return report

    for name, module in model.named_modules():
        if isinstance(module, detect_types):
            module.inplace = False
            module.dynamic = False
            module.export = True
            report["detect_heads_prepared"].append(
                {"name": name, "type": type(module).__name__}
            )

    dummy = torch.zeros(batch_size, 3, img_size, img_size)
    with torch.no_grad():
        for _ in range(2):
            model(dummy)
    report["dry_runs"] = 2
    return report


def describe_model_outputs(model: Any, size: int) -> Dict[str, Any]:
    """Run one bounded reference forward pass to record the real output shape."""

    import torch  # type: ignore[import-not-found]

    with torch.no_grad():
        raw = model(torch.zeros(1, 3, size, size))
    primary = raw[0] if isinstance(raw, (list, tuple)) else raw
    while isinstance(primary, (list, tuple)):
        primary = primary[0]
    shape = [int(value) for value in primary.shape]
    names = getattr(model, "names", {})
    if isinstance(names, dict):
        class_names = [str(names[key]) for key in sorted(names, key=lambda item: int(item))]
    elif isinstance(names, (list, tuple)):
        class_names = [str(item) for item in names]
    else:
        class_names = []
    return {
        "reference_output_shape": shape,
        "reference_output_dtype": str(primary.dtype).replace("torch.", ""),
        "class_names": class_names,
        "stride": int(max(getattr(model, "stride", [32]))) if hasattr(model, "stride") else 32,
    }


def build_output_contract(shape: List[int], class_names: List[str]) -> OutputContract:
    """Derive the decode contract from the observed shape — never guessed."""

    from workers.core.tensorrt_perception import infer_output_layout

    layout = infer_output_layout(shape)
    attributes = int(layout["attributes"])
    class_count = len(class_names)
    has_objectness = bool(class_count and attributes == class_count + 5)
    if not class_count:
        class_count = attributes - 4
    return OutputContract(
        output_names=["output0"],
        output_shapes=[shape],
        output_dtypes=["float32"],
        layout=str(layout["layout"]),
        nms_embedded=False,
        has_objectness=has_objectness,
        box_encoding="cxcywh",
        coordinate_space="letterbox_pixels",
        class_count=int(class_count),
        class_names_source="external_source:data/coco.yaml",
    )


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13C ONNX export gate")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--source-root", default="")
    parser.add_argument("--weights", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--manifest", default="")
    parser.add_argument("--img-size", type=int, default=DEFAULT_INPUT_SIZE)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--opset", type=int, default=DEFAULT_OPSET)
    parser.add_argument("--model-family", default=DEFAULT_MODEL_FAMILY)
    parser.add_argument("--model-variant", default=DEFAULT_MODEL_VARIANT)
    parser.add_argument("--confidence-threshold", type=float, default=0.25)
    parser.add_argument("--nms-iou-threshold", type=float, default=0.45)
    parser.add_argument("--max-detections", type=int, default=300)
    parser.add_argument("--output-dir", default="experiments/phase13")
    parser.add_argument("--require-export", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    run_id = args.run_id or new_run_id()
    evidence = Phase13CEvidence(Path(args.output_dir), run_id)
    environment = pc_environment()

    source_root = resolve_external_path(args.source_root, "YOLOV9_ROOT")
    weights = resolve_external_path(args.weights, "YOLOV9_WEIGHTS")
    if weights is None and source_root is not None:
        candidate = Path(source_root) / "yolov9-c-converted.pt"
        weights = candidate if candidate.is_file() else None

    summary = {
        "phase": PHASE,
        "gate": "onnx_export",
        "run_id": run_id,
        "created_at_utc": utc_now_iso(),
        "onnx_export_executed": False,
        "onnx_export_passed": False,
        "onnx_input_contract_verified": False,
        "onnx_output_contract_verified": False,
    }  # type: Dict[str, Any]

    assets = verify_model_assets(source_root=source_root, weights=weights)
    summary["assets"] = assets
    blockers = list(assets["blockers"])

    preflight = dependency_preflight()
    summary["export_dependencies"] = preflight
    summary["onnx_checker_available"] = bool(preflight["onnx_checker_available"])
    summary["onnx_checker_passed"] = False

    if not preflight["torch_available"]:
        blockers.append("onnx_export_dependency_missing")
    if not preflight["onnx_available"]:
        # torch >= 2.9 requires the onnx package for *every* export path,
        # including the legacy TorchScript exporter.
        blockers.append("onnx_export_dependency_missing")

    summary["unlock_commands"] = unlock_commands(sys.executable)

    model_manifest = None  # type: Optional[ModelManifest]
    if not blockers:
        onnx_path = Path(args.output) if args.output else (
            Path(source_root) / "exports" / "yolov9-c-640-b1.onnx"
        )
        onnx_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            import torch  # type: ignore[import-not-found]

            model = load_yolov9_model(Path(source_root), Path(weights))
            # Prepare BEFORE the reference forward so the recorded output
            # contract describes the graph that is actually exported.
            summary["export_preparation"] = prepare_model_for_export(
                model, img_size=int(args.img_size), batch_size=int(args.batch_size)
            )
            described = describe_model_outputs(model, int(args.img_size))
            summary["reference_forward"] = described

            input_contract = InputContract(
                batch_size=int(args.batch_size),
                height=int(args.img_size),
                width=int(args.img_size),
            )
            profile = PostprocessProfile(
                confidence_threshold=float(args.confidence_threshold),
                nms_iou_threshold=float(args.nms_iou_threshold),
                max_detections=int(args.max_detections),
            )
            output_contract = build_output_contract(
                described["reference_output_shape"], described["class_names"]
            )

            dummy = torch.zeros(*input_contract.shape)
            export_kwargs = {
                "opset_version": int(args.opset),
                "do_constant_folding": True,
                "input_names": [input_contract.input_name],
                "output_names": list(output_contract.output_names),
                "dynamic_axes": None,
            }
            import inspect

            if "dynamo" in inspect.signature(torch.onnx.export).parameters:
                export_kwargs["dynamo"] = False

            started = time.perf_counter_ns()
            with torch.no_grad():
                torch.onnx.export(model, dummy, str(onnx_path), **export_kwargs)
            duration = (time.perf_counter_ns() - started) / 1e9
            summary["onnx_export_executed"] = True

            checker_passed = False
            graph_report = {}  # type: Dict[str, Any]
            try:
                import onnx  # type: ignore[import-not-found]

                graph = onnx.load(str(onnx_path))
                # full_check runs shape inference in strict mode as well, so a
                # graph that merely parses but cannot be shape-inferred fails
                # here rather than later inside the TensorRT parser.
                onnx.checker.check_model(graph, full_check=True)
                checker_passed = True

                def _tensor_shape(value: Any) -> List[Any]:
                    dims = []  # type: List[Any]
                    for dimension in value.type.tensor_type.shape.dim:
                        dims.append(
                            int(dimension.dim_value)
                            if dimension.HasField("dim_value")
                            else str(dimension.dim_param)
                        )
                    return dims

                def _tensor_dtype(value: Any) -> str:
                    return str(
                        onnx.TensorProto.DataType.Name(value.type.tensor_type.elem_type)
                    )

                graph_report = {
                    "graph_inputs": [item.name for item in graph.graph.input],
                    "graph_outputs": [item.name for item in graph.graph.output],
                    "graph_input_shapes": [_tensor_shape(item) for item in graph.graph.input],
                    "graph_input_dtypes": [_tensor_dtype(item) for item in graph.graph.input],
                    "graph_output_shapes": [_tensor_shape(item) for item in graph.graph.output],
                    "graph_output_dtypes": [_tensor_dtype(item) for item in graph.graph.output],
                    "ir_version": int(graph.ir_version),
                    "opset_imports": [int(item.version) for item in graph.opset_import],
                    "producer_name": str(graph.producer_name),
                    "node_count": len(graph.graph.node),
                    "full_check": True,
                }
            except Exception as exc:
                graph_report = {"checker_error": repr(exc)[:200]}
            summary["onnx_checker_passed"] = checker_passed
            summary["onnx_graph"] = graph_report

            summary["onnx_input_contract_verified"] = bool(
                graph_report.get("graph_inputs") == [input_contract.input_name]
            )
            summary["onnx_output_contract_verified"] = bool(
                graph_report.get("graph_outputs") == list(output_contract.output_names)
            )

            onnx_info = describe_file(onnx_path)
            model_manifest = ModelManifest(
                model_family=str(args.model_family),
                model_variant=str(args.model_variant),
                external_source_root=str(source_root),
                external_source_git_sha=external_git_sha(Path(source_root)),
                weights_path=str(weights),
                weights_sha256=assets["weights_sha256"] or "",
                weights_size_bytes=int(assets["weights_size_bytes"] or 0),
                onnx_path=str(onnx_path),
                onnx_sha256=onnx_info["sha256"] or "",
                onnx_size_bytes=int(onnx_info["size_bytes"] or 0),
                onnx_opset=int(args.opset),
                exporter="torch.onnx.export(dynamo=False)",
                export_command=[sys.executable] + list(sys.argv),
                export_duration_sec=round(duration, 3),
                torch_version=str(torch.__version__),
                input_contract=input_contract.to_dict(),
                output_contract=output_contract.to_dict(),
                postprocess_profile=profile.to_dict(),
                created_at_utc=utc_now_iso(),
            )
            manifest_path = Path(args.manifest) if args.manifest else onnx_path.with_suffix(
                ".manifest.json"
            )
            model_manifest.write(manifest_path)
            summary["model_manifest_path"] = str(manifest_path)
            summary["onnx_export_passed"] = bool(
                summary["onnx_export_executed"] and onnx_info["exists"]
            )
        except Exception as exc:
            blockers.append("onnx_export_failed")
            summary["export_error"] = repr(exc)[:400]

    summary["blockers"] = blockers
    summary["status"] = (
        STATUS_PREPARED if summary["onnx_export_passed"] and not blockers else STATUS_BLOCKED
    )
    summary["pc_environment"] = environment
    summary.update(BOUNDARY_FIELDS)

    evidence.write_json("summary.json", summary)
    evidence.write_json("environment.json", environment)
    evidence.write_json(
        "model_manifest.json",
        model_manifest.to_dict() if model_manifest else {"executed": False, "blockers": blockers},
    )
    evidence.write_json(
        "manifest.json",
        {
            "phase": PHASE,
            "gate": "onnx_export",
            "run_id": run_id,
            "status": summary["status"],
            "created_at_utc": utc_now_iso(),
            "evidence_dir": str(evidence.run_dir),
            "generated_evidence_git_policy": "ignored_local_only",
            **BOUNDARY_FIELDS,
        },
    )
    evidence.write_text(
        "commands.txt",
        "# Phase 13C ONNX export\n%s %s\n\n%s\n"
        % (sys.executable, " ".join(sys.argv), "\n".join(summary["unlock_commands"])),
    )
    evidence.write_text(
        "README.md",
        "# Phase 13C ONNX export evidence\n\nRun id: `%s`\n\nStatus: `%s`\n\n"
        "External model assets are never committed, downloaded or auto-installed.\n"
        % (run_id, summary["status"]),
    )

    print(summary["status"])
    print("run_id=%s" % run_id)
    print("evidence_dir=%s" % evidence.run_dir)
    print("external_model_source_ready=%s" % assets["external_model_source_ready"])
    print("external_weights_ready=%s" % assets["external_weights_ready"])
    print("weights_sha256=%s" % (assets["weights_sha256"] or ""))
    print("onnx_export_executed=%s" % summary["onnx_export_executed"])
    print("onnx_export_passed=%s" % summary["onnx_export_passed"])
    if blockers:
        print("blockers=%s" % ",".join(sorted(set(blockers))), file=sys.stderr)
        for line in summary["unlock_commands"]:
            print(line, file=sys.stderr)
    if args.require_export and not summary["onnx_export_passed"]:
        return 1
    return 0 if not blockers else 1


if __name__ == "__main__":
    raise SystemExit(main())
