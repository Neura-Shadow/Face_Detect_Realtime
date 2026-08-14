"""Phase 13D INT8 calibration dataset contract.

The calibration corpus is **controlled CARLA simulation data**. It is captured
outside this repository, never committed, and never described as real-world
representative. This module owns everything about it that has to be provable:

* per-frame identity (route, weather, frame id, SHA-256, size, resolution);
* per-frame image statistics in the normalized ``/255`` domain;
* the deterministic calibration / holdout split, and the proof that the two
  splits share no frame and that no frame content is duplicated;
* coverage against the declared minimums (routes, weather profiles, split
  sizes);
* the **calibration envelopes** derived from the calibration split, and the
  holdout false-reject rate they produce.

A TensorRT INT8 engine is only as trustworthy as the data that produced its
scales, so the dataset identity is hashed into the calibration cache key: a
different corpus means a stale cache and a mandatory recalibration.

Runtime compatibility: Jetson Python 3.8.10 (typing generics only).
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

DATASET_MANIFEST_VERSION = 1

#: Controlled-simulation provenance. Written into every dataset artefact.
DATA_SOURCE = "controlled_carla_simulation"
DEFAULT_TOWN = "Town03"

MIN_ROUTES = 5
MIN_WEATHER_PROFILES = 4
MIN_CALIBRATION_FRAMES = 512
MIN_HOLDOUT_FRAMES = 128
MAX_HOLDOUT_FALSE_REJECT_RATE = 0.01

DEFAULT_ENVELOPE_MARGIN_RATIO = 0.02
FRAME_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp")

_HASH_CHUNK_BYTES = 1024 * 1024


class DatasetError(RuntimeError):
    """Dataset contract violation carrying a Phase 13D classification."""

    def __init__(self, classification: str, message: str) -> None:
        super().__init__("%s: %s" % (classification, message))
        self.classification = classification
        self.message = message


def sha256_file(path: Path, *, chunk_bytes: int = _HASH_CHUNK_BYTES) -> str:
    digest = hashlib.sha256()
    with open(str(path), "rb") as handle:
        while True:
            chunk = handle.read(chunk_bytes)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def list_frame_files(root: Path) -> List[Path]:
    """Every image under ``root``, deterministically ordered."""

    directory = Path(root)
    if not directory.is_dir():
        return []
    found = [
        path
        for path in directory.rglob("*")
        if path.is_file() and path.suffix.lower() in FRAME_SUFFIXES
    ]
    return sorted(found, key=lambda item: str(item).replace("\\", "/"))


# ── Image statistics ────────────────────────────────────────────────────────


def image_statistics(frame: Any) -> Dict[str, Any]:
    """Statistics of one BGR8 frame in the normalized ``/255`` domain.

    These are *source-frame* statistics: they describe the pixels the camera
    produced, not the letterboxed network input. Letterbox padding would drag
    every channel mean toward the pad grey and make the numbers useless as a
    range-shift signal.
    """

    import numpy as np

    array = np.asarray(frame)
    if array.ndim != 3 or array.shape[2] != 3:
        raise DatasetError("dataset_frame_invalid", "expected HxWx3 BGR frame, got %s" % (array.shape,))
    scaled = array.astype(np.float32) / 255.0
    if not np.all(np.isfinite(scaled)):
        raise DatasetError("dataset_frame_nonfinite", "frame contains NaN/Inf")
    return {
        "width": int(array.shape[1]),
        "height": int(array.shape[0]),
        "pixel_min": round(float(np.min(scaled)), 6),
        "pixel_max": round(float(np.max(scaled)), 6),
        "pixel_mean": round(float(np.mean(scaled)), 6),
        # Channel order matches the stored BGR8 pixel order.
        "channel_means": [round(float(np.mean(scaled[:, :, index])), 6) for index in range(3)],
        "channel_stds": [round(float(np.std(scaled[:, :, index])), 6) for index in range(3)],
    }


# ── Frame records ───────────────────────────────────────────────────────────


@dataclass
class FrameRecord:
    """One calibration or holdout frame, fully identified."""

    frame_id: str = ""
    route: str = ""
    weather: str = ""
    split: str = ""
    path: str = ""
    relative_path: str = ""
    sha256: str = ""
    size_bytes: int = 0
    width: int = 0
    height: int = 0
    pixel_min: float = 0.0
    pixel_max: float = 0.0
    pixel_mean: float = 0.0
    channel_means: List[float] = field(default_factory=list)
    channel_stds: List[float] = field(default_factory=list)
    captured_at_utc: str = ""
    carla_frame: int = 0
    simulation_timestamp_us: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(payload: Dict[str, Any]) -> "FrameRecord":
        known = {key for key in FrameRecord().to_dict()}
        return FrameRecord(**{k: v for k, v in payload.items() if k in known})


def describe_frame(
    path: Path,
    *,
    frame_id: str,
    route: str,
    weather: str,
    statistics: Dict[str, Any],
    dataset_root: Optional[Path] = None,
    captured_at_utc: str = "",
    carla_frame: int = 0,
    simulation_timestamp_us: int = 0,
) -> FrameRecord:
    """Bind one image file to its route/weather/statistics identity."""

    resolved = Path(path)
    if not resolved.is_file():
        raise DatasetError("dataset_frame_missing", "frame not found: %s" % resolved)
    relative = str(resolved)
    if dataset_root is not None:
        try:
            relative = str(resolved.relative_to(Path(dataset_root)))
        except ValueError:
            relative = resolved.name
    return FrameRecord(
        frame_id=str(frame_id),
        route=str(route),
        weather=str(weather),
        split="",
        path=str(resolved),
        relative_path=relative.replace("\\", "/"),
        sha256=sha256_file(resolved),
        size_bytes=int(resolved.stat().st_size),
        width=int(statistics["width"]),
        height=int(statistics["height"]),
        pixel_min=float(statistics["pixel_min"]),
        pixel_max=float(statistics["pixel_max"]),
        pixel_mean=float(statistics["pixel_mean"]),
        channel_means=[float(value) for value in statistics["channel_means"]],
        channel_stds=[float(value) for value in statistics["channel_stds"]],
        captured_at_utc=str(captured_at_utc),
        carla_frame=int(carla_frame),
        simulation_timestamp_us=int(simulation_timestamp_us),
    )


# ── Deterministic split ─────────────────────────────────────────────────────


def assign_splits(
    records: Sequence[FrameRecord], *, holdout_stride: int = 5
) -> List[FrameRecord]:
    """Stride-assign a holdout split *inside every route/weather cell*.

    A random split could starve a whole weather profile; a per-cell stride
    cannot. Every ``holdout_stride``-th frame of each cell becomes holdout, so
    the two splits see the same routes, the same weather profiles and the same
    temporal spread, and they can never share a frame.
    """

    if int(holdout_stride) < 2:
        raise DatasetError("dataset_split_invalid", "holdout stride must be >= 2")
    grouped = {}  # type: Dict[Tuple[str, str], List[FrameRecord]]
    for record in records:
        grouped.setdefault((record.route, record.weather), []).append(record)

    assigned = []  # type: List[FrameRecord]
    for key in sorted(grouped):
        cell = sorted(grouped[key], key=lambda item: item.frame_id)
        for index, record in enumerate(cell):
            record.split = "holdout" if (index + 1) % int(holdout_stride) == 0 else "calibration"
            assigned.append(record)
    return sorted(assigned, key=lambda item: (item.route, item.weather, item.frame_id))


def dataset_sha256(records: Sequence[FrameRecord]) -> str:
    """Content identity of the whole corpus, order-independent per split."""

    material = "\n".join(
        sorted("%s|%s|%s" % (record.split, record.frame_id, record.sha256) for record in records)
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


# ── Manifest ────────────────────────────────────────────────────────────────


@dataclass
class DatasetManifest:
    """The committed-to-nothing, provable identity of the calibration corpus."""

    dataset_name: str = "carla-town03-int8-calibration"
    data_source: str = DATA_SOURCE
    real_world_representative: bool = False
    town: str = DEFAULT_TOWN
    capture_profile: Dict[str, Any] = field(default_factory=dict)
    routes: List[str] = field(default_factory=list)
    weather_profiles: List[str] = field(default_factory=list)
    frames: List[Dict[str, Any]] = field(default_factory=list)
    frame_count: int = 0
    calibration_count: int = 0
    holdout_count: int = 0
    holdout_stride: int = 5
    dataset_sha256: str = ""
    dataset_root: str = ""
    created_at_utc: str = ""
    manifest_version: int = DATASET_MANIFEST_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def records(self) -> List[FrameRecord]:
        return [FrameRecord.from_dict(item) for item in self.frames]

    def split(self, name: str) -> List[FrameRecord]:
        return [record for record in self.records() if record.split == name]

    def write(self, path: Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return target

    @staticmethod
    def load(path: Path) -> "DatasetManifest":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        known = {key for key in DatasetManifest().to_dict()}
        return DatasetManifest(**{k: v for k, v in payload.items() if k in known})


def build_manifest(
    records: Sequence[FrameRecord],
    *,
    dataset_name: str = "carla-town03-int8-calibration",
    town: str = DEFAULT_TOWN,
    capture_profile: Optional[Dict[str, Any]] = None,
    dataset_root: str = "",
    holdout_stride: int = 5,
    created_at_utc: str = "",
) -> DatasetManifest:
    ordered = list(records)
    calibration = [record for record in ordered if record.split == "calibration"]
    holdout = [record for record in ordered if record.split == "holdout"]
    return DatasetManifest(
        dataset_name=dataset_name,
        data_source=DATA_SOURCE,
        real_world_representative=False,
        town=town,
        capture_profile=dict(capture_profile or {}),
        routes=sorted({record.route for record in ordered}),
        weather_profiles=sorted({record.weather for record in ordered}),
        frames=[record.to_dict() for record in ordered],
        frame_count=len(ordered),
        calibration_count=len(calibration),
        holdout_count=len(holdout),
        holdout_stride=int(holdout_stride),
        dataset_sha256=dataset_sha256(ordered),
        dataset_root=str(dataset_root),
        created_at_utc=str(created_at_utc),
    )


# ── Coverage and disjointness ───────────────────────────────────────────────


def evaluate_coverage(
    manifest: DatasetManifest,
    *,
    min_routes: int = MIN_ROUTES,
    min_weather_profiles: int = MIN_WEATHER_PROFILES,
    min_calibration: int = MIN_CALIBRATION_FRAMES,
    min_holdout: int = MIN_HOLDOUT_FRAMES,
) -> Dict[str, Any]:
    """Coverage of routes, weather profiles and split sizes."""

    records = manifest.records()
    cells = {}  # type: Dict[str, int]
    for record in records:
        cells["%s|%s" % (record.route, record.weather)] = (
            cells.get("%s|%s" % (record.route, record.weather), 0) + 1
        )
    weather_per_route = {}  # type: Dict[str, int]
    for route in sorted({record.route for record in records}):
        weather_per_route[route] = len(
            {record.weather for record in records if record.route == route}
        )

    blockers = []  # type: List[str]
    if len(manifest.routes) < int(min_routes):
        blockers.append("dataset_route_coverage_insufficient")
    if len(manifest.weather_profiles) < int(min_weather_profiles):
        blockers.append("dataset_weather_coverage_insufficient")
    if manifest.calibration_count < int(min_calibration):
        blockers.append("calibration_frame_count_insufficient")
    if manifest.holdout_count < int(min_holdout):
        blockers.append("holdout_frame_count_insufficient")
    if weather_per_route and min(weather_per_route.values()) < int(min_weather_profiles):
        blockers.append("dataset_weather_coverage_per_route_insufficient")

    return {
        "route_count": len(manifest.routes),
        "weather_profile_count": len(manifest.weather_profiles),
        "routes": list(manifest.routes),
        "weather_profiles": list(manifest.weather_profiles),
        "route_weather_cell_count": len(cells),
        "route_weather_cell_frame_counts": cells,
        "weather_profiles_per_route": weather_per_route,
        "frame_count": manifest.frame_count,
        "calibration_count": manifest.calibration_count,
        "holdout_count": manifest.holdout_count,
        "min_routes_required": int(min_routes),
        "min_weather_profiles_required": int(min_weather_profiles),
        "min_calibration_required": int(min_calibration),
        "min_holdout_required": int(min_holdout),
        "coverage_passed": not blockers,
        "blockers": blockers,
    }


def evaluate_disjointness(manifest: DatasetManifest) -> Dict[str, Any]:
    """Duplicate content and split overlap must both be exactly zero."""

    records = manifest.records()
    by_sha = {}  # type: Dict[str, List[str]]
    by_frame_id = {}  # type: Dict[str, int]
    for record in records:
        by_sha.setdefault(record.sha256, []).append(record.frame_id)
        by_frame_id[record.frame_id] = by_frame_id.get(record.frame_id, 0) + 1

    duplicate_groups = {sha: ids for sha, ids in by_sha.items() if len(ids) > 1}
    duplicate_frame_count = sum(len(ids) - 1 for ids in duplicate_groups.values())
    repeated_ids = sorted(name for name, count in by_frame_id.items() if count > 1)

    calibration_ids = {record.frame_id for record in records if record.split == "calibration"}
    holdout_ids = {record.frame_id for record in records if record.split == "holdout"}
    calibration_shas = {record.sha256 for record in records if record.split == "calibration"}
    holdout_shas = {record.sha256 for record in records if record.split == "holdout"}
    unassigned = [record.frame_id for record in records if record.split not in ("calibration", "holdout")]

    id_overlap = sorted(calibration_ids & holdout_ids)
    sha_overlap = sorted(calibration_shas & holdout_shas)

    blockers = []  # type: List[str]
    if duplicate_frame_count:
        blockers.append("dataset_duplicate_frames")
    if repeated_ids:
        blockers.append("dataset_frame_id_collision")
    if id_overlap or sha_overlap:
        blockers.append("dataset_split_overlap")
    if unassigned:
        blockers.append("dataset_split_unassigned")

    return {
        "duplicate_sha256_count": duplicate_frame_count,
        "duplicate_sha256_groups": {sha: sorted(ids) for sha, ids in sorted(duplicate_groups.items())},
        "repeated_frame_ids": repeated_ids,
        "split_overlap_frame_id_count": len(id_overlap),
        "split_overlap_sha256_count": len(sha_overlap),
        "split_overlap_frame_ids": id_overlap[:32],
        "unassigned_frame_count": len(unassigned),
        "disjointness_passed": not blockers,
        "blockers": blockers,
    }


# ── Calibration envelopes ───────────────────────────────────────────────────


def _bounds(values: Sequence[float], margin_ratio: float) -> List[float]:
    """Observed [min, max] expanded by a fraction of the observed range."""

    numbers = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    if not numbers:
        raise DatasetError("calibration_envelope_unavailable", "no finite samples for an envelope")
    low = min(numbers)
    high = max(numbers)
    span = high - low
    margin = abs(span) * float(margin_ratio)
    if span <= 0.0:
        # A constant statistic still needs a non-degenerate envelope, otherwise
        # float rounding alone would reject an identical frame.
        margin = max(abs(low), 1.0) * float(margin_ratio)
    return [round(low - margin, 6), round(high + margin, 6)]


@dataclass
class CalibrationEnvelopes:
    """Per-statistic acceptance envelopes derived from the calibration split."""

    channel_mean_bounds: List[List[float]] = field(default_factory=list)
    channel_std_bounds: List[List[float]] = field(default_factory=list)
    pixel_min_bounds: List[float] = field(default_factory=list)
    pixel_max_bounds: List[float] = field(default_factory=list)
    pixel_mean_bounds: List[float] = field(default_factory=list)
    margin_ratio: float = DEFAULT_ENVELOPE_MARGIN_RATIO
    source_split: str = "calibration"
    source_frame_count: int = 0
    envelope_source: str = "calibration_split_min_max_with_margin"
    dataset_sha256: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(payload: Dict[str, Any]) -> "CalibrationEnvelopes":
        known = {key for key in CalibrationEnvelopes().to_dict()}
        return CalibrationEnvelopes(**{k: v for k, v in payload.items() if k in known})

    def violations(self, statistics: Dict[str, Any]) -> List[str]:
        """Which envelopes one frame's statistics violate. Empty means inside."""

        failures = []  # type: List[str]
        means = statistics.get("channel_means") or []
        stds = statistics.get("channel_stds") or []
        for index, bounds in enumerate(self.channel_mean_bounds):
            if index >= len(means):
                failures.append("channel_mean_missing:%d" % index)
                continue
            value = float(means[index])
            if not math.isfinite(value):
                failures.append("channel_mean_nonfinite:%d" % index)
            elif not float(bounds[0]) <= value <= float(bounds[1]):
                failures.append("channel_mean_out_of_envelope:%d" % index)
        for index, bounds in enumerate(self.channel_std_bounds):
            if index >= len(stds):
                failures.append("channel_std_missing:%d" % index)
                continue
            value = float(stds[index])
            if not math.isfinite(value):
                failures.append("channel_std_nonfinite:%d" % index)
            elif not float(bounds[0]) <= value <= float(bounds[1]):
                failures.append("channel_std_out_of_envelope:%d" % index)
        for key, bounds in (
            ("pixel_min", self.pixel_min_bounds),
            ("pixel_max", self.pixel_max_bounds),
            ("pixel_mean", self.pixel_mean_bounds),
        ):
            if not bounds:
                continue
            raw = statistics.get(key)
            if raw is None:
                failures.append("%s_missing" % key)
                continue
            value = float(raw)
            if not math.isfinite(value):
                failures.append("%s_nonfinite" % key)
            elif not float(bounds[0]) <= value <= float(bounds[1]):
                failures.append("%s_out_of_envelope" % key)
        return failures


def build_envelopes(
    records: Sequence[FrameRecord],
    *,
    margin_ratio: float = DEFAULT_ENVELOPE_MARGIN_RATIO,
    dataset_sha256_value: str = "",
) -> CalibrationEnvelopes:
    """Derive envelopes from the calibration split only — never the holdout."""

    calibration = [record for record in records if record.split == "calibration"]
    if not calibration:
        raise DatasetError("calibration_envelope_unavailable", "calibration split is empty")
    channels = max(len(record.channel_means) for record in calibration)
    return CalibrationEnvelopes(
        channel_mean_bounds=[
            _bounds([record.channel_means[index] for record in calibration if index < len(record.channel_means)],
                    margin_ratio)
            for index in range(channels)
        ],
        channel_std_bounds=[
            _bounds([record.channel_stds[index] for record in calibration if index < len(record.channel_stds)],
                    margin_ratio)
            for index in range(channels)
        ],
        pixel_min_bounds=_bounds([record.pixel_min for record in calibration], margin_ratio),
        pixel_max_bounds=_bounds([record.pixel_max for record in calibration], margin_ratio),
        pixel_mean_bounds=_bounds([record.pixel_mean for record in calibration], margin_ratio),
        margin_ratio=float(margin_ratio),
        source_split="calibration",
        source_frame_count=len(calibration),
        dataset_sha256=str(dataset_sha256_value),
    )


def record_statistics(record: FrameRecord) -> Dict[str, Any]:
    return {
        "channel_means": list(record.channel_means),
        "channel_stds": list(record.channel_stds),
        "pixel_min": record.pixel_min,
        "pixel_max": record.pixel_max,
        "pixel_mean": record.pixel_mean,
    }


def evaluate_holdout(
    envelopes: CalibrationEnvelopes,
    holdout: Sequence[FrameRecord],
    *,
    max_false_reject_rate: float = MAX_HOLDOUT_FALSE_REJECT_RATE,
) -> Dict[str, Any]:
    """A valid-in-distribution frame must not be rejected by the envelope.

    Every holdout frame came from the same controlled capture, so any holdout
    rejection is a *false* reject. The rate is the honest cost of the envelope
    and must stay at or below the declared bound.
    """

    frames = list(holdout)
    if not frames:
        return {
            "holdout_evaluated_count": 0,
            "holdout_false_reject_count": 0,
            "holdout_false_reject_rate": None,
            "holdout_false_reject_examples": [],
            "max_false_reject_rate": float(max_false_reject_rate),
            "holdout_passed": False,
            "blockers": ["holdout_frame_count_insufficient"],
        }
    rejected = []  # type: List[Dict[str, Any]]
    for record in frames:
        failures = envelopes.violations(record_statistics(record))
        if failures:
            rejected.append({"frame_id": record.frame_id, "violations": failures})
    rate = len(rejected) / float(len(frames))
    blockers = []  # type: List[str]
    if rate > float(max_false_reject_rate):
        blockers.append("holdout_false_reject_rate_exceeded")
    return {
        "holdout_evaluated_count": len(frames),
        "holdout_false_reject_count": len(rejected),
        "holdout_false_reject_rate": round(rate, 6),
        "holdout_false_reject_examples": rejected[:16],
        "max_false_reject_rate": float(max_false_reject_rate),
        "holdout_passed": not blockers,
        "blockers": blockers,
    }


def range_profile(records: Sequence[FrameRecord]) -> Dict[str, Any]:
    """Aggregate range profile of the corpus, split by calibration/holdout."""

    def _profile(subset: Sequence[FrameRecord]) -> Dict[str, Any]:
        if not subset:
            return {"frame_count": 0}
        channels = max(len(record.channel_means) for record in subset)
        return {
            "frame_count": len(subset),
            "pixel_min": round(min(record.pixel_min for record in subset), 6),
            "pixel_max": round(max(record.pixel_max for record in subset), 6),
            "pixel_mean_mean": round(
                sum(record.pixel_mean for record in subset) / len(subset), 6
            ),
            "channel_mean_min": [
                round(min(record.channel_means[index] for record in subset if index < len(record.channel_means)), 6)
                for index in range(channels)
            ],
            "channel_mean_max": [
                round(max(record.channel_means[index] for record in subset if index < len(record.channel_means)), 6)
                for index in range(channels)
            ],
            "channel_std_min": [
                round(min(record.channel_stds[index] for record in subset if index < len(record.channel_stds)), 6)
                for index in range(channels)
            ],
            "channel_std_max": [
                round(max(record.channel_stds[index] for record in subset if index < len(record.channel_stds)), 6)
                for index in range(channels)
            ],
        }

    ordered = list(records)
    return {
        "all": _profile(ordered),
        "calibration": _profile([item for item in ordered if item.split == "calibration"]),
        "holdout": _profile([item for item in ordered if item.split == "holdout"]),
        "normalization": "divide_by_255",
        "statistics_domain": "source_frame_bgr8",
        "real_world_representative": False,
        "data_source": DATA_SOURCE,
    }


def verify_frame_files(records: Iterable[FrameRecord], *, verify_hash: bool = True) -> Dict[str, Any]:
    """Confirm every manifest entry still exists with the recorded content."""

    missing = []  # type: List[str]
    mismatched = []  # type: List[str]
    checked = 0
    for record in records:
        checked += 1
        path = Path(record.path)
        if not path.is_file():
            missing.append(record.frame_id)
            continue
        if verify_hash and sha256_file(path) != record.sha256:
            mismatched.append(record.frame_id)
    blockers = []  # type: List[str]
    if missing:
        blockers.append("dataset_frame_missing")
    if mismatched:
        blockers.append("dataset_frame_sha256_mismatch")
    return {
        "frames_checked": checked,
        "frames_missing": missing[:32],
        "frames_missing_count": len(missing),
        "frames_sha256_mismatch": mismatched[:32],
        "frames_sha256_mismatch_count": len(mismatched),
        "frame_files_verified": not blockers,
        "blockers": blockers,
    }
