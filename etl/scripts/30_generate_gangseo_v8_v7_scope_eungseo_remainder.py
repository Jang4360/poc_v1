#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from pyproj import Transformer


ROOT_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT_DIR / "etl" / "raw"
TO_5179 = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)

DEFAULT_V7_NODE_CSV = RAW_DIR / "gangseo_road_nodes_v7.csv"
DEFAULT_V7_SEGMENT_CSV = RAW_DIR / "gangseo_road_segments_v7.csv"
DEFAULT_EUNGSEO_NODE_CSV = RAW_DIR / "gangseo_road_nodes_v8_eungseo.csv"
DEFAULT_EUNGSEO_SEGMENT_CSV = RAW_DIR / "gangseo_road_segments_v8_eungseo.csv"
DEFAULT_OUTPUT_NODE_CSV = RAW_DIR / "gangseo_road_nodes_v8.csv"
DEFAULT_OUTPUT_SEGMENT_CSV = RAW_DIR / "gangseo_road_segments_v8.csv"
DEFAULT_REPORT_JSON = ROOT_DIR / "runtime" / "graphhopper" / "topology" / "gangseo_v8_v7_scope_eungseo_remainder_merge_report.json"

TARGET_NODE_FIELDS = ["vertexId", "sourceNodeKey", "point"]
TARGET_SEGMENT_FIELDS = [
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

POINT_RE = re.compile(r"^SRID=4326;POINT\(([-0-9.]+) ([-0-9.]+)\)$")
LINE_RE = re.compile(r"^SRID=4326;LINESTRING\((.+)\)$")
YES_NO_UNKNOWN = {"YES", "NO", "UNKNOWN"}
SLOPE_STATES = {"FLAT", "MODERATE", "STEEP", "RISK", "UNKNOWN"}
SIGNAL_STATES = {"TRAFFIC_SIGNALS", "NO", "UNKNOWN"}
WIDTH_STATES = {"ADEQUATE_150", "ADEQUATE_120", "NARROW", "UNKNOWN"}
SURFACE_STATES = {"PAVED", "UNPAVED", "UNKNOWN"}
SOURCE_NODE_SNAP_TOLERANCE_METER = 5.0

# Reuse the already accepted four-dong + 1km scope from the previous v8 merge report.
EXPANDED_FOUR_DONG_BBOXES = {
    "sinho": {
        "name": "신호동",
        "expandedBbox": [128.84702155690093, 35.065953500995114, 128.9059784430991, 35.114046499004886],
    },
    "noksan": {
        "name": "녹산동",
        "expandedBbox": [128.8040195369162, 35.065953500995114, 128.8689804630838, 35.14404649900489],
    },
    "hwajeon": {
        "name": "화전동",
        "expandedBbox": [128.84701751543517, 35.09595350099511, 128.90598248456484, 35.14404649900489],
    },
    "myeongji": {
        "name": "명지동",
        "expandedBbox": [128.88402021041065, 35.07095350099511, 128.95097978958935, 35.129046499004886],
    },
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def parse_point(value: str) -> tuple[float, float]:
    match = POINT_RE.match((value or "").strip())
    if not match:
        raise ValueError(f"unsupported POINT EWKT: {value!r}")
    return float(match.group(1)), float(match.group(2))


def parse_linestring(value: str) -> list[tuple[float, float]]:
    match = LINE_RE.match((value or "").strip())
    if not match:
        raise ValueError(f"unsupported LINESTRING EWKT: {value!r}")
    coords: list[tuple[float, float]] = []
    for pair in match.group(1).split(","):
        lon, lat = pair.strip().split(" ")
        coords.append((float(lon), float(lat)))
    if len(coords) < 2:
        raise ValueError(f"LINESTRING must contain at least two points: {value!r}")
    return coords


def point_ewkt(coord: tuple[float, float]) -> str:
    return f"SRID=4326;POINT({coord[0]:.8f} {coord[1]:.8f})"


def line_ewkt(coords: list[tuple[float, float]]) -> str:
    return "SRID=4326;LINESTRING(" + ", ".join(f"{lon:.8f} {lat:.8f}" for lon, lat in coords) + ")"


def coord_key(coord: tuple[float, float]) -> str:
    return f"{coord[0]:.8f}:{coord[1]:.8f}"


def distance_meter(left: tuple[float, float], right: tuple[float, float]) -> float:
    left_x, left_y = TO_5179.transform(*left)
    right_x, right_y = TO_5179.transform(*right)
    return math.hypot(right_x - left_x, right_y - left_y)


def line_length_meter(coords: list[tuple[float, float]]) -> float:
    return sum(distance_meter(left, right) for left, right in zip(coords, coords[1:]))


def in_bbox(coord: tuple[float, float], bbox: list[float]) -> bool:
    min_lon, min_lat, max_lon, max_lat = bbox
    lon, lat = coord
    return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat


def matching_scope_ids(coords: list[tuple[float, float]], bboxes: dict[str, dict[str, Any]]) -> list[str]:
    matches = []
    for scope_id, item in bboxes.items():
        if any(in_bbox(coord, item["expandedBbox"]) for coord in coords):
            matches.append(scope_id)
    return matches


def node_lookup(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {(row.get("vertexId") or "").strip(): row for row in rows}


def normalize_yes_no_unknown(value: str | None) -> str:
    normalized = (value or "").strip().upper()
    return normalized if normalized in YES_NO_UNKNOWN else "UNKNOWN"


def normalize_slope_state(value: str | None) -> str:
    normalized = (value or "").strip().upper()
    return normalized if normalized in SLOPE_STATES else "UNKNOWN"


def normalize_signal_state(value: str | None) -> str:
    normalized = (value or "").strip().upper()
    return normalized if normalized in SIGNAL_STATES else "UNKNOWN"


def normalize_width_state(value: str | None) -> str:
    normalized = (value or "").strip().upper()
    return normalized if normalized in WIDTH_STATES else "UNKNOWN"


def normalize_surface_state(value: str | None) -> str:
    normalized = (value or "").strip().upper()
    return normalized if normalized in SURFACE_STATES else "UNKNOWN"


def normalize_segment_type(value: str | None) -> str:
    normalized = (value or "").strip().upper()
    if normalized in {"ROAD_BOUNDARY", "ROAD_BOUNDARY_INNER", "SIDE_LEFT", "SIDE_RIGHT"}:
        return "SIDE_LINE"
    return normalized if normalized in {"SIDE_LINE", "SIDE_WALK"} else "SIDE_LINE"


def select_segments(
    rows: list[dict[str, str]],
    *,
    bboxes: dict[str, dict[str, Any]],
    include_scope: bool,
) -> tuple[list[dict[str, Any]], Counter[str], int]:
    selected: list[dict[str, Any]] = []
    scope_counts: Counter[str] = Counter()
    invalid_geometry = 0
    for row in rows:
        try:
            coords = parse_linestring(row.get("geom", ""))
        except ValueError:
            invalid_geometry += 1
            continue
        matched_scope_ids = matching_scope_ids(coords, bboxes)
        for scope_id in matched_scope_ids:
            scope_counts[scope_id] += 1
        if bool(matched_scope_ids) == include_scope:
            selected.append({"row": row, "coords": coords, "scopeIds": matched_scope_ids})
    return selected, scope_counts, invalid_geometry


def build_outputs(
    *,
    v7_nodes: list[dict[str, str]],
    v7_segments: list[dict[str, str]],
    eungseo_nodes: list[dict[str, str]],
    eungseo_segments: list[dict[str, str]],
    bboxes: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, Any]]:
    v7_selected, v7_scope_counts, v7_invalid_geoms = select_segments(v7_segments, bboxes=bboxes, include_scope=True)
    eungseo_selected, eungseo_scope_counts, eungseo_invalid_geoms = select_segments(
        eungseo_segments,
        bboxes=bboxes,
        include_scope=False,
    )

    source_nodes = {
        "v7": node_lookup(v7_nodes),
        "eungseo": node_lookup(eungseo_nodes),
    }
    merged_nodes: list[dict[str, str]] = []
    merged_segments: list[dict[str, str]] = []
    new_node_id_by_coord: dict[str, int] = {}
    next_vertex_id = 1
    endpoint_source_node_snaps: Counter[str] = Counter()
    endpoint_geometry_fallbacks: Counter[str] = Counter()
    skipped_invalid_length: Counter[str] = Counter()
    defaulted_missing_fields: Counter[str] = Counter()

    def resolve_node(source: str, old_node_id: str, fallback: tuple[float, float]) -> tuple[int, tuple[float, float]]:
        nonlocal next_vertex_id
        source_row = source_nodes[source].get(old_node_id)
        source_coord = parse_point(source_row["point"]) if source_row else None
        if source_coord is not None and distance_meter(source_coord, fallback) <= SOURCE_NODE_SNAP_TOLERANCE_METER:
            coord = source_coord
            endpoint_source_node_snaps[source] += 1
        else:
            coord = fallback
            endpoint_geometry_fallbacks[source] += 1
        key = coord_key(coord)
        existing_id = new_node_id_by_coord.get(key)
        if existing_id is not None:
            return existing_id, coord
        new_vertex_id = next_vertex_id
        next_vertex_id += 1
        new_node_id_by_coord[key] = new_vertex_id
        source_key = source_row.get("sourceNodeKey", "") if source_row else f"missing:{source}:{old_node_id}"
        merged_nodes.append(
            {
                "vertexId": str(new_vertex_id),
                "sourceNodeKey": f"v8:{source}:{source_key}",
                "point": point_ewkt(coord),
            }
        )
        return new_vertex_id, coord

    def source_value(row: dict[str, str], source: str, field: str) -> str:
        if field in row:
            return row.get(field, "")
        defaulted_missing_fields[f"{source}.{field}"] += 1
        return ""

    def append_segments(source: str, selected: list[dict[str, Any]]) -> Counter[str]:
        type_counts: Counter[str] = Counter()
        for item in selected:
            row = item["row"]
            coords = item["coords"]
            if line_length_meter(coords) <= 0.01:
                skipped_invalid_length[source] += 1
                continue
            from_node_id, from_coord = resolve_node(source, (row.get("fromNodeId") or "").strip(), coords[0])
            to_node_id, to_coord = resolve_node(source, (row.get("toNodeId") or "").strip(), coords[-1])
            output_coords = [from_coord, *coords[1:-1], to_coord]
            if line_length_meter(output_coords) <= 0.01:
                skipped_invalid_length[source] += 1
                continue
            segment_type = normalize_segment_type(row.get("segmentType"))
            type_counts[segment_type] += 1
            slope_state = normalize_slope_state(row.get("slopeState")) if source == "v7" else "UNKNOWN"
            signal_state = normalize_signal_state(row.get("signalState")) if source == "v7" else "UNKNOWN"
            if source != "v7":
                defaulted_missing_fields[f"{source}.slopeState"] += 1
                defaulted_missing_fields[f"{source}.signalState"] += 1
            merged_segments.append(
                {
                    "edgeId": str(len(merged_segments) + 1),
                    "fromNodeId": str(from_node_id),
                    "toNodeId": str(to_node_id),
                    "geom": line_ewkt(output_coords),
                    "lengthMeter": source_value(row, source, "lengthMeter"),
                    "walkAccess": normalize_yes_no_unknown(source_value(row, source, "walkAccess")),
                    "avgSlopePercent": source_value(row, source, "avgSlopePercent"),
                    "widthMeter": source_value(row, source, "widthMeter"),
                    "brailleBlockState": normalize_yes_no_unknown(source_value(row, source, "brailleBlockState")),
                    "audioSignalState": normalize_yes_no_unknown(source_value(row, source, "audioSignalState")),
                    "slopeState": slope_state,
                    "widthState": normalize_width_state(source_value(row, source, "widthState")),
                    "surfaceState": normalize_surface_state(source_value(row, source, "surfaceState")),
                    "stairsState": normalize_yes_no_unknown(source_value(row, source, "stairsState")),
                    "signalState": signal_state,
                    "segmentType": segment_type,
                }
            )
        return type_counts

    v7_type_counts = append_segments("v7", v7_selected)
    eungseo_type_counts = append_segments("eungseo", eungseo_selected)
    output_type_counts = Counter(row["segmentType"] for row in merged_segments)

    report = {
        "sources": {
            "v7": {
                "segments": str(DEFAULT_V7_SEGMENT_CSV.relative_to(ROOT_DIR)),
                "nodes": str(DEFAULT_V7_NODE_CSV.relative_to(ROOT_DIR)),
                "inputSegmentCount": len(v7_segments),
                "inputNodeCount": len(v7_nodes),
                "selectedInsideFourDongPlus1km": len(v7_selected),
                "invalidGeometries": v7_invalid_geoms,
                "matchedScopeCounts": dict(sorted(v7_scope_counts.items())),
                "outputSegmentTypeCounts": dict(sorted(v7_type_counts.items())),
            },
            "eungseo": {
                "segments": str(DEFAULT_EUNGSEO_SEGMENT_CSV.relative_to(ROOT_DIR)),
                "nodes": str(DEFAULT_EUNGSEO_NODE_CSV.relative_to(ROOT_DIR)),
                "inputSegmentCount": len(eungseo_segments),
                "inputNodeCount": len(eungseo_nodes),
                "selectedOutsideFourDongPlus1km": len(eungseo_selected),
                "removedInsideFourDongPlus1km": len(eungseo_segments) - len(eungseo_selected) - eungseo_invalid_geoms,
                "invalidGeometries": eungseo_invalid_geoms,
                "matchedScopeCounts": dict(sorted(eungseo_scope_counts.items())),
                "outputSegmentTypeCounts": dict(sorted(eungseo_type_counts.items())),
            },
        },
        "scope": {
            "rule": "v7 segments are selected when any LineString vertex falls inside a four-dong expanded bbox; eungseo segments are selected only when no vertex falls inside those bboxes.",
            "bufferMeter": 1000,
            "areas": bboxes,
        },
        "output": {
            "segments": str(DEFAULT_OUTPUT_SEGMENT_CSV.relative_to(ROOT_DIR)),
            "nodes": str(DEFAULT_OUTPUT_NODE_CSV.relative_to(ROOT_DIR)),
            "segmentCount": len(merged_segments),
            "nodeCount": len(merged_nodes),
            "segmentTypeCounts": dict(sorted(output_type_counts.items())),
            "skippedInvalidLengthSegments": dict(sorted(skipped_invalid_length.items())),
            "endpointSourceNodeSnaps": dict(sorted(endpoint_source_node_snaps.items())),
            "endpointGeometryFallbacks": dict(sorted(endpoint_geometry_fallbacks.items())),
            "defaultedMissingOrNonCommonFields": dict(sorted(defaulted_missing_fields.items())),
        },
        "schemaPolicy": {
            "nodeColumns": TARGET_NODE_FIELDS,
            "segmentColumns": TARGET_SEGMENT_FIELDS,
            "baseSchema": "gangseo_road_nodes_v7.csv and gangseo_road_segments_v7.csv",
            "eungseoPolicy": "Only columns common with the v7 schema are copied. eungseo-only columns rampState, elevatorState, and crossingState are not mapped. Missing slopeState and signalState default to UNKNOWN.",
            "segmentTypeNormalization": "ROAD_BOUNDARY, ROAD_BOUNDARY_INNER, SIDE_LEFT, and SIDE_RIGHT are normalized to SIDE_LINE; SIDE_WALK is preserved.",
        },
    }
    return merged_nodes, merged_segments, report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate Gangseo v8 from v7 four-dong+1km scope and v8_eungseo remainder.",
    )
    parser.add_argument("--v7-node-csv", type=Path, default=DEFAULT_V7_NODE_CSV)
    parser.add_argument("--v7-segment-csv", type=Path, default=DEFAULT_V7_SEGMENT_CSV)
    parser.add_argument("--eungseo-node-csv", type=Path, default=DEFAULT_EUNGSEO_NODE_CSV)
    parser.add_argument("--eungseo-segment-csv", type=Path, default=DEFAULT_EUNGSEO_SEGMENT_CSV)
    parser.add_argument("--output-node-csv", type=Path, default=DEFAULT_OUTPUT_NODE_CSV)
    parser.add_argument("--output-segment-csv", type=Path, default=DEFAULT_OUTPUT_SEGMENT_CSV)
    parser.add_argument("--report-json", type=Path, default=DEFAULT_REPORT_JSON)
    args = parser.parse_args()

    nodes, segments, report = build_outputs(
        v7_nodes=read_csv(args.v7_node_csv),
        v7_segments=read_csv(args.v7_segment_csv),
        eungseo_nodes=read_csv(args.eungseo_node_csv),
        eungseo_segments=read_csv(args.eungseo_segment_csv),
        bboxes=EXPANDED_FOUR_DONG_BBOXES,
    )
    report["outputs"] = {
        "nodeCsv": str(args.output_node_csv.relative_to(ROOT_DIR)),
        "segmentCsv": str(args.output_segment_csv.relative_to(ROOT_DIR)),
        "reportJson": str(args.report_json.relative_to(ROOT_DIR)),
    }
    write_csv(args.output_node_csv, nodes, TARGET_NODE_FIELDS)
    write_csv(args.output_segment_csv, segments, TARGET_SEGMENT_FIELDS)
    args.report_json.parent.mkdir(parents=True, exist_ok=True)
    args.report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
