from __future__ import annotations

import argparse
import csv
import json
import math
import re
import subprocess
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Callable, Iterable

import tifffile
from pyproj import Transformer
from shapely import wkt
from shapely.geometry import LineString, Point, shape
from shapely.ops import transform
from shapely.strtree import STRtree


ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "etl" / "raw"
RUNTIME_DIR = ROOT / "runtime" / "etl" / "gangseo-osm-dem-attribute-enrichment"

DEFAULT_INPUT = RAW_DIR / "gangseo_road_segments_mapping_v2.csv"
DEFAULT_OUTPUT = RAW_DIR / "gangseo_road_segments_mapping_v3.csv"
DEFAULT_REPORT = RUNTIME_DIR / "report_v3.json"
DEFAULT_BRAILLE = RAW_DIR / "점자블록.csv"
DEFAULT_OSM = RAW_DIR / "부산광역시_260502.osm.pbf"
DEFAULT_DEM = RAW_DIR / "부산광역시_partial_N35_E128_DEM.tif"

TO_5179 = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
FROM_5179 = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)

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

UNKNOWN_VALUES = {"", "UNKNOWN", "NULL", "NONE", "NAN"}
SIDE_WALK = "SIDE_WALK"


@dataclass
class SourceStats:
    source: str
    target_columns: str
    source_rows: int = 0
    candidate_rows: int = 0
    matched_rows: int = 0
    updated_rows: int = 0
    skipped_existing: int = 0
    unmapped_rows: int = 0
    invalid_rows: int = 0
    updated_edges: set[str] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "source": self.source,
            "target_columns": self.target_columns,
            "source_rows": self.source_rows,
            "candidate_rows": self.candidate_rows,
            "matched_rows": self.matched_rows,
            "updated_rows": self.updated_rows,
            "skipped_existing": self.skipped_existing,
            "unmapped_rows": self.unmapped_rows,
            "invalid_rows": self.invalid_rows,
            "updated_edge_count": len(self.updated_edges),
            "notes": self.notes,
        }


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def parse_wkt_geometry(value: str | None):
    text = (value or "").strip()
    if not text:
        return None
    if text.upper().startswith("SRID="):
        text = text.split(";", 1)[1]
    try:
        geom = wkt.loads(text)
    except Exception:
        return None
    return None if geom.is_empty else geom


def to_5179(geom):
    return transform(TO_5179.transform, geom)


def from_5179(geom):
    return transform(FROM_5179.transform, geom)


def is_unknown(value: str | None) -> bool:
    return (value or "").strip().upper() in UNKNOWN_VALUES


def normalize_yes_no(value: str | None) -> str:
    text = (value or "").strip().upper()
    if text in {"YES", "Y", "TRUE", "1"}:
        return "YES"
    if text in {"NO", "N", "FALSE", "0"}:
        return "NO"
    return "UNKNOWN"


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


PAVED_SURFACES = {
    "ASPHALT",
    "CONCRETE",
    "PAVED",
    "PAVING_STONES",
    "CONCRETE:PLATES",
    "CONCRETE:LANES",
    "BRICKS",
    "SETT",
    "TARTAN",
}
UNPAVED_SURFACES = {
    "UNPAVED",
    "DIRT",
    "EARTH",
    "GROUND",
    "GRAVEL",
    "FINE_GRAVEL",
    "SAND",
    "GRASS",
    "WOODCHIPS",
    "PEBBLESTONE",
    "COMPACTED",
}


def normalize_surface(value: str | None) -> str:
    text = (value or "").strip().upper()
    if text in PAVED_SURFACES:
        return "PAVED"
    if text in UNPAVED_SURFACES:
        return "UNPAVED"
    return "UNKNOWN"


def parse_width(value: str | None) -> float | None:
    text = (value or "").strip().lower().replace(",", ".")
    if not text:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    width = parse_float(match.group(0))
    if width is None or width <= 0 or width > 20:
        return None
    return width


def parse_incline_percent(value: str | None) -> float | None:
    text = (value or "").strip().lower().replace(",", ".")
    if not text or text in {"up", "down", "yes", "no"}:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    incline = abs(float(match.group(0)))
    if "°" in text or "deg" in text:
        incline = math.tan(math.radians(incline)) * 100.0
    if incline > 40:
        return None
    return incline


class SegmentIndex:
    def __init__(self, rows: list[dict[str, str]]) -> None:
        self.rows = rows
        self.geoms_wgs = [parse_wkt_geometry(row["geom"]) for row in rows]
        if any(geom is None for geom in self.geoms_wgs):
            raise ValueError("mapping CSV contains invalid target geometries")
        self.geoms_5179 = [to_5179(geom) for geom in self.geoms_wgs]
        self.tree = STRtree(self.geoms_5179)

    def nearest(
        self,
        source_geom_wgs,
        radius_meter: float,
        *,
        segment_filter: Callable[[dict[str, str]], bool] | None = None,
        prefer_overlap: bool = True,
    ) -> tuple[int, float] | None:
        source_geom_5179 = to_5179(source_geom_wgs)
        best: tuple[float, float, int] | None = None
        for raw_index in self.tree.query(source_geom_5179.buffer(radius_meter)):
            index = int(raw_index)
            row = self.rows[index]
            if segment_filter and not segment_filter(row):
                continue
            target = self.geoms_5179[index]
            distance = float(source_geom_5179.distance(target))
            if not math.isfinite(distance) or distance > radius_meter:
                continue
            overlap = 0.0
            if prefer_overlap and source_geom_wgs.geom_type in {"LineString", "MultiLineString"}:
                overlap = float(source_geom_5179.intersection(target).length)
            candidate = (distance, -overlap, index)
            if best is None or candidate < best:
                best = candidate
        if best is None:
            return None
        return best[2], best[0]


def set_unknown(row: dict[str, str], field: str, value: str) -> bool:
    if not is_unknown(row.get(field)):
        return False
    if is_unknown(value):
        return False
    row[field] = value
    return True


def point_from_ewkt(value: str | None):
    geom = parse_wkt_geometry(value)
    if geom is None:
        return None
    if geom.geom_type != "Point":
        return geom.centroid
    return geom


def map_point_source(
    rows: Iterable[dict[str, str]],
    index: SegmentIndex,
    stats: SourceStats,
    *,
    radius_meter: float,
    value_getter: Callable[[dict[str, str]], str],
    geom_getter: Callable[[dict[str, str]], object | None],
    target_field: str,
    segment_filter: Callable[[dict[str, str]], bool] | None = None,
) -> None:
    for source_row in rows:
        stats.source_rows += 1
        value = value_getter(source_row)
        geom = geom_getter(source_row)
        if geom is None or is_unknown(value):
            stats.invalid_rows += 1
            continue
        stats.candidate_rows += 1
        match = index.nearest(geom, radius_meter, segment_filter=segment_filter, prefer_overlap=False)
        if match is None:
            stats.unmapped_rows += 1
            continue
        target_index, _distance = match
        stats.matched_rows += 1
        target = index.rows[target_index]
        if set_unknown(target, target_field, value):
            stats.updated_rows += 1
            stats.updated_edges.add(target["edgeId"])
        else:
            stats.skipped_existing += 1


def export_osm_geojson(osm_path: Path) -> list[dict[str, object]]:
    filters = [
        "n/tactile_paving",
        "w/tactile_paving",
        "n/traffic_signals:sound",
        "w/traffic_signals:sound",
        "n/crossing",
        "w/crossing",
        "n/crossing:signals",
        "w/crossing:signals",
        "n/highway=traffic_signals",
        "w/highway=traffic_signals",
        "w/surface",
        "w/width",
        "w/incline",
        "w/highway=steps",
        "w/step_count",
    ]
    with tempfile.TemporaryDirectory() as tmp:
        filtered = Path(tmp) / "filtered.pbf"
        geojson = Path(tmp) / "filtered.geojson"
        subprocess.run(["osmium", "tags-filter", str(osm_path), *filters, "-o", str(filtered)], check=True)
        subprocess.run(["osmium", "export", str(filtered), "-o", str(geojson), "-f", "geojson"], check=True)
        data = json.loads(geojson.read_text(encoding="utf-8"))
    return data.get("features", [])


def feature_geom(feature: dict[str, object]):
    try:
        geom = shape(feature.get("geometry"))
    except Exception:
        return None
    return None if geom.is_empty else geom


def feature_props(feature: dict[str, object]) -> dict[str, str]:
    props = feature.get("properties") or {}
    return {str(k): str(v) for k, v in dict(props).items() if v is not None}


def is_signal_feature(props: dict[str, str]) -> bool:
    return (
        props.get("crossing", "").lower() == "traffic_signals"
        or props.get("crossing:signals", "").lower() == "yes"
        or props.get("highway", "").lower() == "traffic_signals"
        or bool(props.get("traffic_signals"))
    )


def is_audio_feature(props: dict[str, str]) -> bool:
    return props.get("traffic_signals:sound", "").lower() in {"yes", "walk", "locate"}


def tactile_value(props: dict[str, str]) -> str:
    value = props.get("tactile_paving", "").lower()
    if value in {"yes", "partial"}:
        return "YES"
    if value == "no":
        return "NO"
    return "UNKNOWN"


def is_steps_feature(props: dict[str, str]) -> bool:
    return props.get("highway", "").lower() == "steps" or bool(props.get("step_count"))


def map_osm_features(features: list[dict[str, object]], index: SegmentIndex) -> list[SourceStats]:
    side_walk_only = lambda row: row.get("segmentType") == SIDE_WALK
    stats = {
        "surface": SourceStats("부산광역시_260502.osm.pbf surface", "surfaceState"),
        "width": SourceStats("부산광역시_260502.osm.pbf width", "widthMeter,widthState"),
        "stairs": SourceStats("부산광역시_260502.osm.pbf steps", "stairsState"),
        "signal": SourceStats("부산광역시_260502.osm.pbf signals", "signalState"),
        "audio": SourceStats("부산광역시_260502.osm.pbf audio signals", "audioSignalState"),
        "braille": SourceStats("부산광역시_260502.osm.pbf tactile_paving", "brailleBlockState"),
        "incline": SourceStats("부산광역시_260502.osm.pbf incline", "avgSlopePercent,slopeState"),
    }
    width_candidates: dict[int, list[float]] = defaultdict(list)
    surface_candidates: dict[int, Counter[str]] = defaultdict(Counter)
    incline_candidates: dict[int, list[float]] = defaultdict(list)

    for feature in features:
        geom = feature_geom(feature)
        props = feature_props(feature)
        if geom is None:
            for item in stats.values():
                item.source_rows += 1
                item.invalid_rows += 1
            continue

        if "surface" in props:
            item = stats["surface"]
            item.source_rows += 1
            surface = normalize_surface(props.get("surface"))
            if is_unknown(surface):
                item.invalid_rows += 1
            else:
                item.candidate_rows += 1
                match = index.nearest(geom, 5.0)
                if match is None:
                    item.unmapped_rows += 1
                else:
                    target_index, _ = match
                    item.matched_rows += 1
                    surface_candidates[target_index][surface] += 1

        width = parse_width(props.get("width"))
        if width is not None:
            item = stats["width"]
            item.source_rows += 1
            item.candidate_rows += 1
            match = index.nearest(geom, 5.0)
            if match is None:
                item.unmapped_rows += 1
            else:
                target_index, _ = match
                item.matched_rows += 1
                width_candidates[target_index].append(width)
        elif "width" in props:
            stats["width"].source_rows += 1
            stats["width"].invalid_rows += 1

        if is_steps_feature(props):
            item = stats["stairs"]
            item.source_rows += 1
            item.candidate_rows += 1
            match = index.nearest(geom, 2.0)
            if match is None:
                item.unmapped_rows += 1
            else:
                target_index, _ = match
                item.matched_rows += 1
                target = index.rows[target_index]
                if set_unknown(target, "stairsState", "YES"):
                    item.updated_rows += 1
                    item.updated_edges.add(target["edgeId"])
                else:
                    item.skipped_existing += 1

        if is_signal_feature(props):
            item = stats["signal"]
            item.source_rows += 1
            item.candidate_rows += 1
            match = index.nearest(geom, 5.0, segment_filter=side_walk_only, prefer_overlap=False)
            if match is None:
                item.unmapped_rows += 1
            else:
                target_index, _ = match
                item.matched_rows += 1
                target = index.rows[target_index]
                if set_unknown(target, "signalState", "TRAFFIC_SIGNALS"):
                    item.updated_rows += 1
                    item.updated_edges.add(target["edgeId"])
                else:
                    item.skipped_existing += 1

        if is_audio_feature(props):
            item = stats["audio"]
            item.source_rows += 1
            item.candidate_rows += 1
            match = index.nearest(geom, 5.0, segment_filter=side_walk_only, prefer_overlap=False)
            if match is None:
                item.unmapped_rows += 1
            else:
                target_index, _ = match
                item.matched_rows += 1
                target = index.rows[target_index]
                if set_unknown(target, "audioSignalState", "YES"):
                    item.updated_rows += 1
                    item.updated_edges.add(target["edgeId"])
                else:
                    item.skipped_existing += 1

        tactile = tactile_value(props)
        if not is_unknown(tactile):
            item = stats["braille"]
            item.source_rows += 1
            item.candidate_rows += 1
            match = index.nearest(geom, 5.0, segment_filter=side_walk_only, prefer_overlap=False)
            if match is None:
                item.unmapped_rows += 1
            else:
                target_index, _ = match
                item.matched_rows += 1
                target = index.rows[target_index]
                if set_unknown(target, "brailleBlockState", tactile):
                    item.updated_rows += 1
                    item.updated_edges.add(target["edgeId"])
                else:
                    item.skipped_existing += 1

        incline = parse_incline_percent(props.get("incline"))
        if incline is not None:
            item = stats["incline"]
            item.source_rows += 1
            item.candidate_rows += 1
            match = index.nearest(geom, 10.0)
            if match is None:
                item.unmapped_rows += 1
            else:
                target_index, _ = match
                item.matched_rows += 1
                incline_candidates[target_index].append(incline)
        elif "incline" in props:
            stats["incline"].source_rows += 1
            stats["incline"].invalid_rows += 1

    for target_index, votes in surface_candidates.items():
        item = stats["surface"]
        target = index.rows[target_index]
        value = votes.most_common(1)[0][0]
        if set_unknown(target, "surfaceState", value):
            item.updated_rows += 1
            item.updated_edges.add(target["edgeId"])
        else:
            item.skipped_existing += 1

    for target_index, values in width_candidates.items():
        item = stats["width"]
        target = index.rows[target_index]
        if is_unknown(target.get("widthMeter")):
            width = round(median(values), 2)
            target["widthMeter"] = f"{width:.2f}"
            if is_unknown(target.get("widthState")):
                target["widthState"] = derive_width_state(width)
            item.updated_rows += 1
            item.updated_edges.add(target["edgeId"])
        else:
            item.skipped_existing += 1

    for target_index, values in incline_candidates.items():
        item = stats["incline"]
        target = index.rows[target_index]
        if is_unknown(target.get("avgSlopePercent")):
            slope = round(median(values), 2)
            target["avgSlopePercent"] = f"{slope:.2f}"
            if is_unknown(target.get("slopeState")):
                target["slopeState"] = derive_slope_state(slope)
            item.updated_rows += 1
            item.updated_edges.add(target["edgeId"])
        else:
            item.skipped_existing += 1

    stats["surface"].notes.append("5m radius")
    stats["width"].notes.append("5m radius")
    stats["stairs"].notes.append("2m radius")
    stats["signal"].notes.append("SIDE_WALK only; 5m radius")
    stats["audio"].notes.append("SIDE_WALK only; 5m radius")
    stats["braille"].notes.append("OSM fallback after 점자블록.csv; SIDE_WALK only; 5m radius")
    stats["incline"].notes.append("OSM incline fallback after DEM; 10m radius")
    return list(stats.values())


class DemSampler:
    def __init__(self, path: Path) -> None:
        with tifffile.TiffFile(path) as tif:
            page = tif.pages[0]
            self.array = page.asarray()
            self.scale = tuple(float(x) for x in page.tags[33550].value)
            self.tie = tuple(float(x) for x in page.tags[33922].value)
        self.origin_x = self.tie[3]
        self.origin_y = self.tie[4]
        self.pixel_x = self.scale[0]
        self.pixel_y = self.scale[1]

    def elevation(self, lon: float, lat: float) -> float | None:
        col = int((lon - self.origin_x) / self.pixel_x)
        row = int((self.origin_y - lat) / self.pixel_y)
        if row < 0 or col < 0 or row >= self.array.shape[0] or col >= self.array.shape[1]:
            return None
        value = float(self.array[row, col])
        return value if math.isfinite(value) else None


def sample_dem_slope(line_5179, sampler: DemSampler) -> float | None:
    length = float(line_5179.length)
    if length < 1.0:
        return None
    start = line_5179.interpolate(0)
    end = line_5179.interpolate(length)
    start_wgs = from_5179(start)
    end_wgs = from_5179(end)
    z0 = sampler.elevation(start_wgs.x, start_wgs.y)
    z1 = sampler.elevation(end_wgs.x, end_wgs.y)
    if z0 is None or z1 is None:
        return None
    slope = abs(z1 - z0) / length * 100.0
    if slope > 40:
        return None
    return slope


def apply_dem(rows: list[dict[str, str]], index: SegmentIndex, dem_path: Path) -> SourceStats:
    sampler = DemSampler(dem_path)
    stats = SourceStats(dem_path.name, "avgSlopePercent,slopeState")
    stats.source_rows = len(rows)
    for target_index, row in enumerate(rows):
        if not is_unknown(row.get("avgSlopePercent")):
            stats.skipped_existing += 1
            continue
        slope = sample_dem_slope(index.geoms_5179[target_index], sampler)
        if slope is None:
            stats.unmapped_rows += 1
            continue
        stats.candidate_rows += 1
        row["avgSlopePercent"] = f"{round(slope, 2):.2f}"
        if is_unknown(row.get("slopeState")):
            row["slopeState"] = derive_slope_state(slope)
        stats.updated_rows += 1
        stats.updated_edges.add(row["edgeId"])
    stats.notes.append("direct target segment DEM endpoint sampling; no spatial radius")
    return stats


def apply_derived_states(rows: list[dict[str, str]]) -> dict[str, int]:
    counts = Counter()
    for row in rows:
        if is_unknown(row.get("widthState")):
            width = parse_float(row.get("widthMeter"))
            state = derive_width_state(width)
            if not is_unknown(state):
                row["widthState"] = state
                counts["widthState_from_existing_widthMeter"] += 1
        if is_unknown(row.get("slopeState")):
            slope = parse_float(row.get("avgSlopePercent"))
            state = derive_slope_state(slope)
            if not is_unknown(state):
                row["slopeState"] = state
                counts["slopeState_from_existing_avgSlopePercent"] += 1
    return dict(counts)


ATTRIBUTE_GROUPS = [
    ("brailleBlockState", ("brailleBlockState",), "점자블록.csv + OSM tactile_paving"),
    ("audioSignalState", ("audioSignalState",), "OSM traffic_signals:sound fallback"),
    ("stairsState", ("stairsState",), "OSM steps fallback"),
    ("signalState", ("signalState",), "OSM traffic signal fallback"),
    ("walkAccess", ("walkAccess",), "not updated in v3 enrichment"),
    ("widthMeter / widthState", ("widthMeter", "widthState"), "OSM width fallback"),
    ("surfaceState", ("surfaceState",), "OSM surface fallback"),
    ("avgSlopePercent / slopeState", ("avgSlopePercent", "slopeState"), "DEM first, OSM incline fallback"),
]


def coverage(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    total = len(rows)
    result = []
    for label, fields, note in ATTRIBUTE_GROUPS:
        unknown = sum(1 for row in rows if any(is_unknown(row.get(field)) for field in fields))
        result.append(
            {
                "attribute": label,
                "unknown_or_blank": unknown,
                "filled": total - unknown,
                "unknown_rate": round(unknown / total * 100.0, 2) if total else 0.0,
                "note": note,
            }
        )
    return result


def enrich(args: argparse.Namespace) -> dict[str, object]:
    rows = read_csv(args.input)
    if not rows:
        raise SystemExit("input mapping CSV has no rows")
    fieldnames = list(rows[0].keys())
    missing = [field for field in TARGET_FIELDS if field not in fieldnames]
    if missing:
        raise SystemExit(f"input mapping CSV is missing fields: {missing}")

    before = coverage(rows)
    index = SegmentIndex(rows)
    stats: list[SourceStats] = []

    braille_stats = SourceStats(args.braille.name, "brailleBlockState")
    map_point_source(
        read_csv(args.braille),
        index,
        braille_stats,
        radius_meter=5.0,
        value_getter=lambda row: normalize_yes_no(row.get("brailleBlockState")),
        geom_getter=lambda row: point_from_ewkt(row.get("geom")),
        target_field="brailleBlockState",
        segment_filter=lambda row: row.get("segmentType") == SIDE_WALK,
    )
    braille_stats.notes.append("primary braille source; SIDE_WALK only; 5m radius")
    stats.append(braille_stats)

    dem_stats = apply_dem(rows, index, args.dem)
    stats.append(dem_stats)

    osm_features = export_osm_geojson(args.osm)
    osm_stats = map_osm_features(osm_features, index)
    stats.extend(osm_stats)

    derived_counts = apply_derived_states(rows)
    after = coverage(rows)

    write_csv(args.output, rows, fieldnames)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "input": str(args.input),
        "output": str(args.output),
        "braille_source": str(args.braille),
        "osm_source": str(args.osm),
        "dem_source": str(args.dem),
        "row_count": len(rows),
        "update_policy": "copy v2 to v3; preserve existing populated values; update UNKNOWN/blank only",
        "coverage_before": before,
        "coverage_after": after,
        "coverage_delta": [
            {
                "attribute": old["attribute"],
                "unknown_before": old["unknown_or_blank"],
                "unknown_after": new["unknown_or_blank"],
                "unknown_reduced_by": old["unknown_or_blank"] - new["unknown_or_blank"],
                "filled_before": old["filled"],
                "filled_after": new["filled"],
                "filled_increased_by": new["filled"] - old["filled"],
                "unknown_rate_before": old["unknown_rate"],
                "unknown_rate_after": new["unknown_rate"],
                "note": new["note"],
            }
            for old, new in zip(before, after)
        ],
        "source_stats": [item.as_dict() for item in stats],
        "derived_counts": derived_counts,
        "segment_type_counts": dict(Counter(row.get("segmentType", "") for row in rows)),
    }
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--braille", type=Path, default=DEFAULT_BRAILLE)
    parser.add_argument("--osm", type=Path, default=DEFAULT_OSM)
    parser.add_argument("--dem", type=Path, default=DEFAULT_DEM)
    args = parser.parse_args()
    for path in (args.input, args.braille, args.osm, args.dem):
        if not path.exists():
            raise SystemExit(f"required input missing: {path}")
    report = enrich(args)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
