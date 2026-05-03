from __future__ import annotations

import argparse
import csv
import json
import math
import warnings
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, median
from typing import Callable, Iterable

from pyproj import Transformer
from shapely import wkt
from shapely.geometry import LineString, Point
from shapely.ops import transform
from shapely.strtree import STRtree


ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "etl" / "raw"
RUNTIME_DIR = ROOT / "runtime" / "etl" / "gangseo-v6-attribute-mapping"

DEFAULT_SEGMENTS = RAW_DIR / "gangseo_road_segments_v8.csv"
DEFAULT_OUTPUT = RAW_DIR / "gangseo_road_segments_mapping_v2.csv"
DEFAULT_REPORT = RUNTIME_DIR / "report_v2.json"

WGS84_TO_TM5179 = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)

AUDIO_SIGNAL_RADIUS_METER = 20.0
CROSSWALK_SIGNAL_RADIUS_METER = 20.0

TARGET_FIELDS = [
    "edgeId",
    "fromNodeId",
    "toNodeId",
    "geom",
    "lengthMeter",
    "walkAccess",
    "avgSlopePercent",
    "widthMeter",
    "brailleBlockState",
    "audioSignalState",
    "slopeState",
    "widthState",
    "surfaceState",
    "stairsState",
    "signalState",
    "segmentType",
]

SOURCE_SCHEMA_RULES = [
    ("인도&인도폭.csv", RAW_DIR / "인도&인도폭.csv", ("districtGu", "wkt", "widthMeter"), ()),
    (
        "이면도로.csv",
        RAW_DIR / "이면도로.csv",
        ("districtGu", "geometryWkt", "networkType", "networkLabel", "stairCode", "slopePercent"),
        (),
    ),
    (
        "경사도&표면타입.csv",
        RAW_DIR / "경사도&표면타입.csv",
        ("districtGu", "geometryWkt", "slopeMean", "slopeMax", "riskLevel", "surfaceType", "widthMeter"),
        (),
    ),
    (
        "횡단보도_음향신호기.csv",
        RAW_DIR / "횡단보도_음향신호기.csv",
        ("sigungu", "audioSignalState", "stat"),
        (("point",), ("lat", "lng")),
    ),
    (
        "횡단보도_신호등.csv",
        RAW_DIR / "횡단보도_신호등.csv",
        ("districtGu", "crossingState"),
        (("point",), ("lat", "lng")),
    ),
    (
        "계단.csv",
        RAW_DIR / "계단.csv",
        ("districtGu", "stairsState"),
        (("geometryWkt",), ("lat", "lng")),
    ),
]


@dataclass
class MatchStats:
    dataset: str
    column: str
    source_rows: int = 0
    mapped_rows: int = 0
    unmapped_rows: int = 0
    invalid_rows: int = 0
    updated_edges: set[str] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "dataset": self.dataset,
            "column": self.column,
            "source_rows": self.source_rows,
            "mapped_rows": self.mapped_rows,
            "unmapped_rows": self.unmapped_rows,
            "invalid_rows": self.invalid_rows,
            "updated_edge_count": len(self.updated_edges),
            "notes": self.notes,
        }


def parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_wkt_geometry(value: str | None):
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if text.upper().startswith("SRID="):
        _, text = text.split(";", 1)
    try:
        geom = wkt.loads(text)
    except Exception:
        return None
    if geom.is_empty:
        return None
    return geom


def point_from_row(row: dict[str, str], *, wkt_key: str = "point"):
    geom = parse_wkt_geometry(row.get(wkt_key))
    if geom is not None:
        return geom
    lng = parse_float(row.get("lng"))
    lat = parse_float(row.get("lat"))
    if lng is None or lat is None:
        return None
    return Point(lng, lat)


def to_tm5179(geom):
    return transform(WGS84_TO_TM5179.transform, geom)


def derive_width_state(width_meter: float | None) -> str:
    if width_meter is None or width_meter <= 0:
        return "UNKNOWN"
    if width_meter >= 1.5:
        return "ADEQUATE_150"
    if width_meter >= 1.2:
        return "ADEQUATE_120"
    return "NARROW"


def derive_slope_state(slope_percent: float | None) -> str:
    if slope_percent is None:
        return "UNKNOWN"
    if slope_percent < 3.0:
        return "FLAT"
    if slope_percent < 5.56:
        return "MODERATE"
    if slope_percent < 8.33:
        return "STEEP"
    return "RISK"


def normalize_surface_state(value: str | None) -> str:
    text = (value or "").strip().upper()
    if text in {"PAVED", "UNPAVED"}:
        return text
    return "UNKNOWN"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def read_headers(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or [])


def validate_mapping_inputs(segment_path: Path) -> list[str]:
    problems: list[str] = []
    if not segment_path.exists():
        problems.append(f"segment CSV missing: {segment_path}")
    else:
        segment_headers = set(read_headers(segment_path))
        missing = [field for field in TARGET_FIELDS if field not in segment_headers]
        if missing:
            problems.append(f"{segment_path.name}: missing target fields {missing}")

    for label, path, required_fields, alternative_groups in SOURCE_SCHEMA_RULES:
        if not path.exists():
            problems.append(f"{label}: source CSV missing: {path}")
            continue
        headers = set(read_headers(path))
        missing = [field for field in required_fields if field not in headers]
        if missing:
            problems.append(f"{label}: missing source fields {missing}")
        if alternative_groups and not any(all(field in headers for field in group) for group in alternative_groups):
            rendered = ["+".join(group) for group in alternative_groups]
            problems.append(f"{label}: missing one of geometry field groups {rendered}")
    return problems


def gangseo_rows(path: Path, gu_key: str = "districtGu") -> list[dict[str, str]]:
    rows = read_csv(path)
    return [row for row in rows if (row.get(gu_key) or "").strip() == "강서구"]


class SegmentMatcher:
    def __init__(self, rows: list[dict[str, str]]) -> None:
        self.rows = rows
        self.geometries = [to_tm5179(parse_wkt_geometry(row["geom"])) for row in rows]
        self.tree = STRtree(self.geometries)

    def nearest(
        self,
        geom,
        radius_meter: float,
        *,
        segment_filter: Callable[[dict[str, str]], bool] | None = None,
        prefer_overlap: bool = True,
    ) -> tuple[int, float] | None:
        projected = to_tm5179(geom)
        best: tuple[float, float, int] | None = None
        for index in self.tree.query(projected.buffer(radius_meter)):
            row = self.rows[int(index)]
            if segment_filter is not None and not segment_filter(row):
                continue
            target = self.geometries[int(index)]
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                distance = float(projected.distance(target))
            if not math.isfinite(distance):
                continue
            if distance > radius_meter:
                continue
            overlap = 0.0
            if prefer_overlap and (isinstance(projected, LineString) or projected.geom_type in {"LineString", "MultiLineString"}):
                overlap = float(projected.intersection(target).length)
            candidate = (distance, -overlap, int(index))
            if best is None or candidate < best:
                best = candidate
        if best is None:
            return None
        return best[2], best[0]


def map_sources(
    *,
    rows: Iterable[dict[str, str]],
    matcher: SegmentMatcher,
    radius_meter: float,
    stats: MatchStats,
    geom_getter: Callable[[dict[str, str]], object | None],
    on_match: Callable[[dict[str, str], int], None],
    segment_filter: Callable[[dict[str, str]], bool] | None = None,
    radius_getter: Callable[[dict[str, str]], float] | None = None,
) -> None:
    for row in rows:
        stats.source_rows += 1
        geom = geom_getter(row)
        if geom is None:
            stats.invalid_rows += 1
            continue
        radius = radius_getter(row) if radius_getter is not None else radius_meter
        match = matcher.nearest(geom, radius, segment_filter=segment_filter)
        if match is None:
            stats.unmapped_rows += 1
            continue
        target_index, _distance = match
        on_match(row, target_index)
        stats.mapped_rows += 1
        stats.updated_edges.add(matcher.rows[target_index]["edgeId"])


def set_if_meaningful(row: dict[str, str], field: str, value: str) -> bool:
    value = value.strip().upper()
    if not value:
        return False
    row[field] = value
    return True


def current_blank(row: dict[str, str], field: str) -> bool:
    return (row.get(field) or "").strip().upper() in {"", "UNKNOWN", "NULL"}


def slope_surface_radius(row: dict[str, str]) -> float:
    width = parse_float(row.get("widthMeter"))
    if width is None or width <= 0:
        return 10.0
    return max(10.0, width / 2.0 + 2.0)


def update_target(rows: list[dict[str, str]]) -> dict[str, object]:
    matcher = SegmentMatcher(rows)
    stats: list[MatchStats] = []
    width_values: dict[int, list[float]] = defaultdict(list)
    slope_primary_values: dict[int, list[float]] = defaultdict(list)
    slope_fallback_values: dict[int, list[float]] = defaultdict(list)
    surface_votes: dict[int, Counter[str]] = defaultdict(Counter)

    side_walk_only = lambda row: row.get("segmentType") == "SIDE_WALK"

    sidewalk_stats = MatchStats("인도&인도폭.csv", "walkAccess,widthMeter")
    sidewalk_rows = gangseo_rows(RAW_DIR / "인도&인도폭.csv")

    def on_sidewalk(row: dict[str, str], target_index: int) -> None:
        rows[target_index]["walkAccess"] = "YES"
        width = parse_float(row.get("widthMeter"))
        if width is not None and width > 0:
            width_values[target_index].append(width)

    map_sources(
        rows=sidewalk_rows,
        matcher=matcher,
        radius_meter=10.0,
        stats=sidewalk_stats,
        geom_getter=lambda row: parse_wkt_geometry(row.get("wkt")),
        on_match=on_sidewalk,
    )
    stats.append(sidewalk_stats)

    local_stats = MatchStats("이면도로.csv", "walkAccess,avgSlopePercent,slopeState")
    local_rows = gangseo_rows(RAW_DIR / "이면도로.csv")

    def on_local(row: dict[str, str], target_index: int) -> None:
        rows[target_index]["walkAccess"] = "YES"
        slope = parse_float(row.get("slopePercent"))
        if slope is not None:
            slope_fallback_values[target_index].append(slope)

    map_sources(
        rows=local_rows,
        matcher=matcher,
        radius_meter=10.0,
        stats=local_stats,
        geom_getter=lambda row: parse_wkt_geometry(row.get("geometryWkt")),
        on_match=on_local,
    )
    stats.append(local_stats)

    slope_stats = MatchStats("경사도&표면타입.csv", "avgSlopePercent,slopeState,surfaceState")
    slope_rows = gangseo_rows(RAW_DIR / "경사도&표면타입.csv")

    def on_slope(row: dict[str, str], target_index: int) -> None:
        slope = parse_float(row.get("slopeMean"))
        if slope is not None:
            slope_primary_values[target_index].append(slope)
        surface_votes[target_index][normalize_surface_state(row.get("surfaceType"))] += 1

    map_sources(
        rows=slope_rows,
        matcher=matcher,
        radius_meter=10.0,
        stats=slope_stats,
        geom_getter=lambda row: parse_wkt_geometry(row.get("geometryWkt")),
        on_match=on_slope,
        radius_getter=slope_surface_radius,
    )
    slope_stats.notes.append("dynamic radius=max(10m,widthMeter/2+2m)")
    stats.append(slope_stats)

    audio_stats = MatchStats("횡단보도_음향신호기.csv", "audioSignalState")
    audio_rows = [
        row
        for row in gangseo_rows(RAW_DIR / "횡단보도_음향신호기.csv", "sigungu")
        if (row.get("audioSignalState") or "").strip().upper() == "YES" and (row.get("stat") or "").strip() == "정상동작"
    ]

    def on_audio(row: dict[str, str], target_index: int) -> None:
        rows[target_index]["audioSignalState"] = "YES"

    map_sources(
        rows=audio_rows,
        matcher=matcher,
        radius_meter=AUDIO_SIGNAL_RADIUS_METER,
        stats=audio_stats,
        geom_getter=point_from_row,
        on_match=on_audio,
        segment_filter=side_walk_only,
    )
    audio_stats.notes.append(f"SIDE_WALK segment only; radius={AUDIO_SIGNAL_RADIUS_METER:g}m")
    stats.append(audio_stats)

    signal_stats = MatchStats("횡단보도_신호등.csv", "signalState")
    signal_rows = [
        row
        for row in gangseo_rows(RAW_DIR / "횡단보도_신호등.csv")
        if (row.get("crossingState") or "").strip().upper() == "TRAFFIC_SIGNALS"
    ]

    def on_signal(row: dict[str, str], target_index: int) -> None:
        rows[target_index]["signalState"] = "TRAFFIC_SIGNALS"

    map_sources(
        rows=signal_rows,
        matcher=matcher,
        radius_meter=CROSSWALK_SIGNAL_RADIUS_METER,
        stats=signal_stats,
        geom_getter=point_from_row,
        on_match=on_signal,
        segment_filter=side_walk_only,
    )
    signal_stats.notes.append(f"SIDE_WALK segment only; radius={CROSSWALK_SIGNAL_RADIUS_METER:g}m")
    stats.append(signal_stats)

    stairs_stats = MatchStats("계단.csv", "stairsState")
    stairs_rows = [row for row in gangseo_rows(RAW_DIR / "계단.csv") if (row.get("stairsState") or "").strip().upper() == "YES"]

    def on_stairs(row: dict[str, str], target_index: int) -> None:
        rows[target_index]["stairsState"] = "YES"

    map_sources(
        rows=stairs_rows,
        matcher=matcher,
        radius_meter=2.0,
        stats=stairs_stats,
        geom_getter=lambda row: parse_wkt_geometry(row.get("geometryWkt")) or point_from_row(row),
        on_match=on_stairs,
    )
    stairs_stats.notes.append("2m radius")
    stats.append(stairs_stats)

    for target_index, values in width_values.items():
        width = round(median(values), 2)
        rows[target_index]["widthMeter"] = f"{width:.2f}"
        rows[target_index]["widthState"] = derive_width_state(width)

    direct_width_indexes = {index for index, values in width_values.items() if values}
    node_to_indexes: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        node_to_indexes[row["fromNodeId"]].append(index)
        node_to_indexes[row["toNodeId"]].append(index)

    neighbor_filled = 0
    direct_width_by_index = {
        index: parse_float(rows[index].get("widthMeter"))
        for index in direct_width_indexes
        if parse_float(rows[index].get("widthMeter")) is not None
    }
    for index, row in enumerate(rows):
        if not current_blank(row, "widthMeter"):
            continue
        neighbor_indexes = set(node_to_indexes[row["fromNodeId"]] + node_to_indexes[row["toNodeId"]])
        neighbor_widths = [direct_width_by_index[i] for i in neighbor_indexes if i in direct_width_by_index]
        if not neighbor_widths:
            continue
        width = round(median(neighbor_widths), 2)
        row["widthMeter"] = f"{width:.2f}"
        row["widthState"] = derive_width_state(width)
        neighbor_filled += 1

    for target_index, values in slope_primary_values.items():
        slope = round(mean(values), 2)
        rows[target_index]["avgSlopePercent"] = f"{slope:.2f}"
        rows[target_index]["slopeState"] = derive_slope_state(slope)

    for target_index, values in slope_fallback_values.items():
        if not current_blank(rows[target_index], "avgSlopePercent"):
            continue
        slope = round(mean(values), 2)
        rows[target_index]["avgSlopePercent"] = f"{slope:.2f}"
        rows[target_index]["slopeState"] = derive_slope_state(slope)

    for target_index, votes in surface_votes.items():
        if votes:
            rows[target_index]["surfaceState"] = votes.most_common(1)[0][0]

    column_counts = {
        "walkAccess=YES": sum(1 for row in rows if row.get("walkAccess") == "YES"),
        "avgSlopePercent filled": sum(1 for row in rows if not current_blank(row, "avgSlopePercent")),
        "widthMeter filled": sum(1 for row in rows if not current_blank(row, "widthMeter")),
        "widthMeter neighbor-filled": neighbor_filled,
        "audioSignalState=YES": sum(1 for row in rows if row.get("audioSignalState") == "YES"),
        "slopeState filled": sum(1 for row in rows if not current_blank(row, "slopeState")),
        "surfaceState filled": sum(1 for row in rows if not current_blank(row, "surfaceState")),
        "stairsState=YES": sum(1 for row in rows if row.get("stairsState") == "YES"),
        "signalState filled": sum(1 for row in rows if not current_blank(row, "signalState")),
    }

    problems = []
    for item in stats:
        if item.invalid_rows:
            problems.append(f"{item.dataset}: invalid geometry/value rows={item.invalid_rows}")
        if item.unmapped_rows:
            problems.append(f"{item.dataset}: no segment within radius rows={item.unmapped_rows}")
    if neighbor_filled:
        problems.append(f"widthMeter: filled {neighbor_filled} empty target rows from one-hop node neighbors")

    return {
        "stats": [item.as_dict() for item in stats],
        "column_counts": column_counts,
        "problems": problems,
    }


def write_segments(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=TARGET_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in TARGET_FIELDS})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_SEGMENTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    schema_problems = validate_mapping_inputs(args.input)
    if schema_problems:
        raise SystemExit("input schema mismatch; output was not written:\n" + "\n".join(f"- {item}" for item in schema_problems))

    rows = read_csv(args.input)
    if not rows:
        raise SystemExit("input segment CSV has no rows; output was not written")
    missing = [field for field in TARGET_FIELDS if field not in rows[0]]
    if missing:
        raise SystemExit(f"input is missing expected fields: {missing}")

    report = update_target(rows)
    report["input"] = str(args.input)
    report["output"] = str(args.output)
    report["row_count"] = len(rows)
    report["segment_type_counts"] = dict(Counter(row.get("segmentType", "") for row in rows))
    write_segments(args.output, rows)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
