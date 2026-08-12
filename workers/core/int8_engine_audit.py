"""Phase 13D INT8 engine layer-precision audit.

Setting ``BuilderFlag.INT8`` does **not** mean the resulting plan runs in INT8.
TensorRT keeps a layer in a higher precision whenever that is faster or when
the layer has no INT8 implementation, so a build log is not evidence. This
module reads the precision TensorRT actually assigned, from the serialized
plan, through ``EngineInspector``.

What may be claimed is bounded by what was observed:

* ``int8_layer_count > 0`` is a Phase 13D requirement and is *measured*;
* ``all_layers_int8`` is only ever true when every layer reported INT8 **and**
  no layer reported an unknown precision — otherwise it stays false;
* layers that did not land in INT8 are recorded as *precision fallback layers*.
  They are a property of the build, not a runtime perception fallback.

The parsing half is deliberately TensorRT-free so the audit contract can be
unit-tested on the simulation PC.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Sequence

INT8 = "INT8"
FP16 = "FP16"
FP32 = "FP32"
UNKNOWN = "UNKNOWN"

MAX_RECORDED_FALLBACK_LAYERS = 64


class EngineAuditError(RuntimeError):
    """Engine audit failure carrying a Phase 13D classification."""

    def __init__(self, classification: str, message: str) -> None:
        super().__init__("%s: %s" % (classification, message))
        self.classification = classification
        self.message = message


def normalize_precision(text: Any) -> str:
    """Map a TensorRT precision/format string onto one of the four buckets."""

    if text is None:
        return UNKNOWN
    value = str(text).strip().upper()
    if not value:
        return UNKNOWN
    if "INT8" in value:
        return INT8
    if "FP16" in value or "HALF" in value:
        return FP16
    if "FP32" in value or "FLOAT" in value:
        return FP32
    if "INT32" in value or "BOOL" in value:
        # Shape/index plumbing; not a compute precision decision.
        return FP32
    return UNKNOWN


def _tensor_precision_hints(entries: Any) -> List[str]:
    hints = []  # type: List[str]
    if not isinstance(entries, (list, tuple)):
        return hints
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for key in ("Format/Datatype", "Format", "Datatype", "DataType", "format", "datatype"):
            if key in entry and entry[key]:
                hints.append(str(entry[key]))
    return hints


def extract_layer_precision(layer: Dict[str, Any]) -> Dict[str, Any]:
    """Read one layer's precision, recording *where* the value came from.

    An audit that silently guessed would be worse than one that reports
    ``UNKNOWN``, so the source of every verdict is kept.
    """

    if not isinstance(layer, dict):
        return {"name": "", "layer_type": "", "precision": UNKNOWN, "precision_source": "unparsable"}
    name = str(layer.get("Name", layer.get("name", "")))
    layer_type = str(layer.get("LayerType", layer.get("ParameterType", layer.get("layer_type", ""))))

    for key in ("Precision", "precision", "LayerPrecision", "ComputePrecision"):
        if key in layer and layer[key]:
            return {
                "name": name,
                "layer_type": layer_type,
                "precision": normalize_precision(layer[key]),
                "precision_source": key,
            }

    hints = _tensor_precision_hints(layer.get("Outputs")) + _tensor_precision_hints(layer.get("Inputs"))
    for hint in hints:
        precision = normalize_precision(hint)
        if precision != UNKNOWN:
            return {
                "name": name,
                "layer_type": layer_type,
                "precision": precision,
                "precision_source": "tensor_format",
            }
    return {"name": name, "layer_type": layer_type, "precision": UNKNOWN, "precision_source": "absent"}


def summarize_layer_precisions(layers: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Count the precisions TensorRT assigned and name the fallback layers."""

    parsed = [extract_layer_precision(layer) for layer in layers]
    counts = {INT8: 0, FP16: 0, FP32: 0, UNKNOWN: 0}
    for entry in parsed:
        counts[entry["precision"]] = counts.get(entry["precision"], 0) + 1
    total = len(parsed)
    int8_count = counts[INT8]
    fallback = [entry for entry in parsed if entry["precision"] != INT8]
    all_int8 = bool(total) and int8_count == total and counts[UNKNOWN] == 0

    return {
        "engine_layer_count": total,
        "int8_layer_count": int8_count,
        "fp16_layer_count": counts[FP16],
        "fp32_layer_count": counts[FP32],
        "unknown_precision_layer_count": counts[UNKNOWN],
        "precision_fallback_layer_count": len(fallback),
        "precision_fallback_layers": [
            {"name": entry["name"], "layer_type": entry["layer_type"], "precision": entry["precision"]}
            for entry in fallback[:MAX_RECORDED_FALLBACK_LAYERS]
        ],
        "int8_layer_ratio": round(int8_count / float(total), 6) if total else None,
        "int8_layers_observed": int8_count > 0,
        # Only ever true when literally every layer reported INT8.
        "all_layers_int8": all_int8,
        "all_layers_int8_claimed": all_int8,
        "layer_precision_source": "tensorrt_engine_inspector",
        "layer_precisions": [
            {"name": entry["name"], "layer_type": entry["layer_type"], "precision": entry["precision"],
             "precision_source": entry["precision_source"]}
            for entry in parsed
        ],
    }


def read_engine_layers(engine_path: str, *, logger_severity: str = "ERROR") -> Dict[str, Any]:
    """Deserialize a plan and dump every layer's inspector JSON."""

    try:
        import tensorrt as trt  # type: ignore[import-not-found]
    except Exception as exc:
        raise EngineAuditError("tensorrt_builder_unavailable", repr(exc)[:200])
    if not os.path.isfile(engine_path):
        raise EngineAuditError("engine_missing", "engine not found: %s" % engine_path)

    severity = getattr(trt.Logger, logger_severity, trt.Logger.ERROR)
    logger = trt.Logger(severity)
    runtime = trt.Runtime(logger)
    with open(engine_path, "rb") as handle:
        engine = runtime.deserialize_cuda_engine(handle.read())
    if engine is None:
        raise EngineAuditError("engine_deserialize_failed", "deserialize_cuda_engine returned None")

    if not hasattr(engine, "create_engine_inspector"):
        raise EngineAuditError(
            "engine_inspector_unavailable",
            "TensorRT %s exposes no EngineInspector" % getattr(trt, "__version__", "?"),
        )
    inspector = engine.create_engine_inspector()
    layers = []  # type: List[Dict[str, Any]]
    parse_failures = 0
    layer_count = int(getattr(engine, "num_layers", 0))
    for index in range(layer_count):
        try:
            raw = inspector.get_layer_information(index, trt.LayerInformationFormat.JSON)
            layers.append(json.loads(raw))
        except Exception:
            parse_failures += 1
            layers.append({})
    engine_information = ""
    try:
        engine_information = str(
            inspector.get_engine_information(trt.LayerInformationFormat.JSON)
        )
    except Exception:
        engine_information = ""

    return {
        "engine_path": engine_path,
        "engine_num_layers": layer_count,
        "engine_layer_json": layers,
        "engine_layer_parse_failures": parse_failures,
        "engine_information_available": bool(engine_information),
        "engine_information_bytes": len(engine_information),
        "engine_deserialized": True,
        "tensorrt_version": str(getattr(trt, "__version__", "")),
    }


def audit_engine(engine_path: str, *, require_int8: bool = True) -> Dict[str, Any]:
    """Full audit: deserialize, inspect every layer, classify the precisions."""

    dump = read_engine_layers(engine_path)
    summary = summarize_layer_precisions(dump["engine_layer_json"])
    blockers = []  # type: List[str]
    if dump["engine_layer_parse_failures"]:
        blockers.append("engine_layer_inspection_incomplete")
    if require_int8 and summary["int8_layer_count"] <= 0:
        blockers.append("int8_layers_not_observed")

    payload = {
        "engine_path": engine_path,
        "engine_deserialization_verified": True,
        "engine_num_layers": dump["engine_num_layers"],
        "engine_layer_parse_failures": dump["engine_layer_parse_failures"],
        "engine_information_available": dump["engine_information_available"],
        "tensorrt_version": dump["tensorrt_version"],
        "dla_enabled": False,
        "dla_core_used": None,
        "audit_passed": not blockers,
        "blockers": blockers,
    }
    payload.update(summary)
    # The audit reads a serialized plan; it never observes running activations.
    payload["runtime_internal_activation_observed"] = False
    payload["internal_tensor_monitoring_claimed"] = False
    return payload


def verify_output_contract(
    binding_report: Dict[str, Any],
    *,
    expected_input_name: str,
    expected_input_shape: Sequence[int],
    expected_output_names: Optional[Sequence[str]] = None,
    expected_output_shapes: Optional[Sequence[Sequence[int]]] = None,
) -> Dict[str, Any]:
    """The INT8 plan must expose the same I/O contract as the FP16 plan."""

    failures = []  # type: List[str]
    inputs = binding_report.get("engine_input_bindings") or []
    outputs = binding_report.get("engine_output_bindings") or []

    if len(inputs) != 1:
        failures.append("input_binding_count_mismatch")
    else:
        primary = inputs[0]
        if expected_input_name and str(primary.get("name")) != str(expected_input_name):
            failures.append("input_binding_name_mismatch")
        if [int(value) for value in primary.get("shape", [])] != [int(v) for v in expected_input_shape]:
            failures.append("input_binding_shape_mismatch")

    if expected_output_names:
        observed_names = [str(item.get("name")) for item in outputs]
        if observed_names != [str(name) for name in expected_output_names]:
            failures.append("output_binding_name_mismatch")
    if expected_output_shapes:
        observed_shapes = [[int(v) for v in item.get("shape", [])] for item in outputs]
        expected = [[int(v) for v in shape] for shape in expected_output_shapes]
        if observed_shapes != expected:
            failures.append("output_binding_shape_mismatch")
    if not outputs:
        failures.append("output_binding_missing")

    return {
        "output_contract_verified": not failures,
        "output_contract_failures": failures,
        "observed_input_bindings": inputs,
        "observed_output_bindings": outputs,
        "blockers": failures,
    }
