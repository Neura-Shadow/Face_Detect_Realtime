"""Phase 13D offline activation proxy — simulation PC only.

TensorRT does not expose the tensors flowing between the layers of a
serialized plan, so Phase 13D does not claim to watch them. Instead it runs the
**source** YOLOv9 model, on the CPU, over a deterministic subsample of the same
calibration frames, with forward hooks on real convolution layers, and records
the activation distributions that INT8 scales have to cover.

That is a proxy and is labelled as one everywhere it appears:

    activation_proxy_backend                       = pytorch_forward_hooks_offline
    runtime_tensorrt_internal_activations_observed = false

Preprocessing is the runtime preprocessing function, so the proxy sees exactly
the tensors the engine will see.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
for _path in (str(REPO_ROOT), str(SCRIPTS_DIR)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from run_phase13d_checks import (  # noqa: E402
    BOUNDARY_FIELDS,
    PHASE,
    STATUS_BLOCKED,
    STATUS_PREPARED,
    Phase13DEvidence,
    new_run_id,
    pc_environment,
    utc_now_iso,
)
from workers.core.int8_activation_proxy import (  # noqa: E402
    MIN_PROXY_LAYERS,
    ActivationProxyError,
    collect_torch_activations,
    summarize_proxy_layers,
)
from workers.core.int8_calibration_dataset import DatasetManifest, FrameRecord  # noqa: E402
from workers.core.tensorrt_asset_contract import InputContract  # noqa: E402
from workers.core.tensorrt_perception import preprocess_bgr  # noqa: E402


def select_frames(records: List[FrameRecord], limit: int) -> List[FrameRecord]:
    """Even, deterministic subsample across the ordered calibration split."""

    ordered = sorted(records, key=lambda item: (item.route, item.weather, item.frame_id))
    if limit <= 0 or len(ordered) <= limit:
        return ordered
    stride = len(ordered) / float(limit)
    picked = []  # type: List[FrameRecord]
    seen = set()  # type: set
    for index in range(limit):
        position = min(len(ordered) - 1, int(round(index * stride)))
        if position in seen:
            continue
        seen.add(position)
        picked.append(ordered[position])
    return picked


def tensor_stream(records: List[FrameRecord], contract: InputContract) -> Iterator[Any]:
    import cv2  # type: ignore[import-not-found]
    import numpy as np

    for record in records:
        image = cv2.imread(record.path, cv2.IMREAD_COLOR)
        if image is None:
            raise ActivationProxyError(
                "activation_proxy_frame_unreadable", "cv2 could not decode %s" % record.path
            )
        tensor, _letterbox, _stats = preprocess_bgr(np.asarray(image), contract)
        yield tensor


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase 13D offline activation proxy")
    parser.add_argument("--run-id", default="")
    parser.add_argument("--dataset-manifest", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--weights", required=True)
    parser.add_argument("--output", required=True, help="external JSON path for the proxy report")
    parser.add_argument("--frames", type=int, default=48)
    parser.add_argument("--layers", type=int, default=12)
    parser.add_argument("--img-size", type=int, default=640)
    parser.add_argument("--min-layers", type=int, default=MIN_PROXY_LAYERS)
    parser.add_argument("--histogram-bins", type=int, default=2048)
    parser.add_argument("--histogram-max", type=float, default=512.0)
    parser.add_argument("--output-dir", default="experiments/phase13")
    parser.add_argument("--require-proxy", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    run_id = args.run_id or new_run_id()
    evidence = Phase13DEvidence(Path(args.output_dir), run_id)
    environment = pc_environment()

    summary = {
        "phase": PHASE,
        "gate": "B_activation_proxy",
        "run_id": run_id,
        "created_at_utc": utc_now_iso(),
        "dataset_manifest": str(args.dataset_manifest),
    }  # type: Dict[str, Any]
    blockers = []  # type: List[str]
    report = {}  # type: Dict[str, Any]

    try:
        manifest_path = Path(args.dataset_manifest)
        if not manifest_path.is_file():
            raise ActivationProxyError(
                "dataset_manifest_missing", "no manifest at %s" % manifest_path
            )
        manifest = DatasetManifest.load(manifest_path)
        calibration = manifest.split("calibration")
        if not calibration:
            raise ActivationProxyError(
                "calibration_frame_count_insufficient", "manifest has no calibration split"
            )
        selected = select_frames(calibration, int(args.frames))
        summary["calibration_frame_count"] = len(calibration)
        summary["activation_proxy_frame_count"] = len(selected)
        summary["activation_proxy_frame_selection"] = "even_stride_subsample_of_calibration_split"
        summary["dataset_sha256"] = manifest.dataset_sha256

        from run_phase13c_onnx_export import load_yolov9_model, prepare_model_for_export

        started = time.perf_counter_ns()
        model = load_yolov9_model(Path(args.source_root), Path(args.weights))
        summary["model_preparation"] = prepare_model_for_export(
            model, img_size=int(args.img_size), batch_size=1
        )
        contract = InputContract(height=int(args.img_size), width=int(args.img_size))
        collector = collect_torch_activations(
            model,
            tensor_stream(selected, contract),
            layer_limit=int(args.layers),
            histogram_bins=int(args.histogram_bins),
            histogram_max=float(args.histogram_max),
        )
        report = collector.report(min_layers=int(args.min_layers))
        report["dataset_sha256"] = manifest.dataset_sha256
        report["dataset_manifest_path"] = str(manifest_path)
        report["activation_proxy_source_model"] = str(args.weights)
        report["activation_proxy_duration_sec"] = round(
            (time.perf_counter_ns() - started) / 1e9, 3
        )
        report["activation_proxy_preprocess_source"] = (
            "workers.core.tensorrt_perception.preprocess_bgr"
        )
        summary.update(summarize_proxy_layers(collector.summaries()))
        summary["activation_proxy_passed"] = bool(report.get("activation_proxy_passed"))
        blockers.extend(report.get("blockers", []))

        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        summary["activation_proxy_path"] = str(target)
    except ActivationProxyError as exc:
        blockers.append(exc.classification)
        summary["error"] = exc.message
    except Exception as exc:
        blockers.append("activation_proxy_failed")
        summary["error"] = repr(exc)[:400]

    passed = bool(report.get("activation_proxy_passed")) and not blockers
    summary["blockers"] = sorted(set(blockers))
    summary["status"] = STATUS_PREPARED if passed else STATUS_BLOCKED
    summary["pc_environment"] = environment
    summary.update(BOUNDARY_FIELDS)

    evidence.write_json("summary.json", summary)
    evidence.write_json("environment.json", environment)
    evidence.write_json("activation_proxy.json", report or {"executed": False})
    evidence.write_manifest("B_activation_proxy", summary["status"])
    evidence.write_placeholders()
    evidence.write_fault_matrix([])
    evidence.write_events([])
    evidence.write_text(
        "commands.txt",
        "# Phase 13D activation proxy\n%s %s\n" % (sys.executable, " ".join(sys.argv)),
    )
    evidence.write_text(
        "README.md",
        "# Phase 13D offline activation proxy evidence\n\nRun id: `%s`\n\nStatus: `%s`\n\n"
        "Activation statistics measured on the **source** model with PyTorch forward hooks, "
        "offline, on the simulation PC. TensorRT's own internal activations are not observed "
        "and are never claimed to be.\n" % (run_id, summary["status"]),
    )

    print(summary["status"])
    print("run_id=%s" % run_id)
    print("evidence_dir=%s" % evidence.run_dir)
    print("activation_proxy_layer_count=%s" % report.get("activation_proxy_layer_count"))
    print("activation_proxy_frames_observed=%s" % report.get("activation_proxy_frames_observed"))
    print(
        "runtime_tensorrt_internal_activations_observed=%s"
        % report.get("runtime_tensorrt_internal_activations_observed")
    )
    if summary["blockers"]:
        print("blockers=%s" % ",".join(summary["blockers"]), file=sys.stderr)
    if args.require_proxy and not passed:
        return 1
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
