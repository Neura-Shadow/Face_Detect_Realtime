"""Phase 13D-MP-RECOVERY semantic layer groups, derived from the real graph.

The groups below are not taken from documentation. They were read off the
TensorRT network parsed from the exact ONNX this phase builds from, whose 1245
layers carry ONNX-derived names of the form ``/model.<stage>/...``. The observed
stage layout is:

    model.0, model.1   stem convolutions
    model.2            RepNCSPELAN4
    model.3            ADown
    model.4            RepNCSPELAN4      model.5   ADown
    model.6            RepNCSPELAN4      model.7   ADown
    model.8            RepNCSPELAN4
    model.9            SPPELAN
    model.10  Resize   model.11 Concat   model.12  RepNCSPELAN4   (top-down, low res)
    model.13  Resize   model.14 Concat   model.15  RepNCSPELAN4   (top-down, high res)
    model.16  ADown    model.17 Concat   model.18  RepNCSPELAN4   (bottom-up PAN)
    model.19  ADown    model.20 Concat   model.21  RepNCSPELAN4   (bottom-up PAN)
    model.22           DDetect head

563 further layers carry no ``/model.N/`` name at all — they are the shape,
constant and gather plumbing TensorRT synthesises. They are deliberately not
members of any group: they are not compute layers whose precision is worth
constraining, and the matcher reports how many layers each group actually
matched so a group can never be assumed to have matched more than it did.

Runtime compatibility: Jetson Python 3.8.10.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

#: group id -> (human name, ONNX stage prefixes)
LAYER_GROUPS = (
    ("G1", "early_backbone", ("/model.0/", "/model.1/", "/model.2/", "/model.3/")),
    ("G2", "mid_backbone", ("/model.4/", "/model.5/", "/model.6/", "/model.7/")),
    ("G3", "late_backbone_sppelan", ("/model.8/", "/model.9/")),
    ("G4", "neck_topdown_low_res", ("/model.10/", "/model.11/", "/model.12/")),
    ("G5", "neck_topdown_high_res", ("/model.13/", "/model.14/", "/model.15/")),
    (
        "G6",
        "neck_bottomup_pan",
        ("/model.16/", "/model.17/", "/model.18/", "/model.19/", "/model.20/", "/model.21/"),
    ),
    ("G7", "detect_head", ("/model.22/",)),
)

GROUP_IDS = tuple(item[0] for item in LAYER_GROUPS)


class LayerGroupError(ValueError):
    """An unknown group id was requested."""


def group_table() -> List[Dict[str, Any]]:
    return [
        {"group_id": group_id, "group_name": name, "prefixes": list(prefixes)}
        for group_id, name, prefixes in LAYER_GROUPS
    ]


def group_by_id(group_id: str) -> Tuple[str, str, Tuple[str, ...]]:
    for item in LAYER_GROUPS:
        if item[0] == str(group_id).strip().upper():
            return item
    raise LayerGroupError("unknown layer group %r (known: %s)" % (group_id, ", ".join(GROUP_IDS)))


def parse_group_spec(spec: Optional[str]) -> List[str]:
    """``"G1,G3"`` -> ``["G1", "G3"]``; empty means the unconstrained baseline."""

    if not spec:
        return []
    ids = []  # type: List[str]
    for raw in str(spec).replace(";", ",").split(","):
        token = raw.strip().upper()
        if not token:
            continue
        group_by_id(token)  # validates
        if token not in ids:
            ids.append(token)
    return ids


def prefixes_for(group_ids: Sequence[str]) -> List[str]:
    prefixes = []  # type: List[str]
    for group_id in group_ids:
        for prefix in group_by_id(group_id)[2]:
            if prefix not in prefixes:
                prefixes.append(prefix)
    return prefixes


def assign_group(name: str) -> Optional[str]:
    """Which group a layer name belongs to, or ``None`` for graph plumbing."""

    text = str(name)
    for group_id, _group_name, prefixes in LAYER_GROUPS:
        if any(text.startswith(prefix) for prefix in prefixes):
            return group_id
    return None


def summarize_groups(layer_names: Sequence[str]) -> Dict[str, Any]:
    """Matched-layer counts per group over a real layer-name list."""

    counts = {group_id: 0 for group_id in GROUP_IDS}
    ungrouped = 0
    for name in layer_names:
        group_id = assign_group(name)
        if group_id is None:
            ungrouped += 1
        else:
            counts[group_id] += 1
    return {
        "layer_count": len(layer_names),
        "group_matched_counts": counts,
        "ungrouped_layer_count": ungrouped,
        "groups": group_table(),
    }


def group_membership(layer_names: Sequence[str], group_ids: Sequence[str]) -> Dict[str, Any]:
    """Exact names a candidate's forced-FP16 groups match in this graph."""

    wanted = [group_by_id(group_id)[0] for group_id in group_ids]
    matched = [name for name in layer_names if assign_group(name) in wanted]
    return {
        "forced_fp16_group_ids": list(wanted),
        "forced_fp16_group_names": [group_by_id(group_id)[1] for group_id in wanted],
        "forced_fp16_prefixes": prefixes_for(wanted),
        "forced_fp16_matched_layer_count": len(matched),
        "forced_fp16_matched_layer_names": matched,
    }
