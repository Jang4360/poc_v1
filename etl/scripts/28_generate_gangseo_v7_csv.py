#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from etl.common import segment_graph_db


RAW_DIR = ROOT_DIR / "etl" / "raw"
REPORT_OUTPUT = ROOT_DIR / "etl" / "gangseo_road_v7_merge_report.json"

DEFAULT_BASE_NODE_CSV = RAW_DIR / "gangseo_road_nodes_v6.csv"
DEFAULT_BASE_SEGMENT_CSV = RAW_DIR / "gangseo_road_segments_v6_jooyoon.csv"
DEFAULT_REPLACEMENT_NODE_CSV = RAW_DIR / "gangseo_road_nodes_v7_eungseo.csv"
DEFAULT_REPLACEMENT_SEGMENT_CSV = RAW_DIR / "gangseo_road_segments_v7_eungseo.csv"
DEFAULT_OUTPUT_NODE_CSV = RAW_DIR / "gangseo_road_nodes_v7.csv"
DEFAULT_OUTPUT_SEGMENT_CSV = RAW_DIR / "gangseo_road_segments_v6.csv"

TARGET_DONG_IDS = ("myeongji", "hwajeon")
SOURCE_NODE_SNAP_TOLERANCE_METER = 5.0
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
TARGET_NODE_FIELDS = ["vertexId", "sourceNodeKey", "point"]

POINT_RE = re.compile(r"^SRID=4326;POINT\(([-0-9.]+) ([-0-9.]+)\)$")
LINE_RE = re.compile(r"^SRID=4326;LINESTRING\((.+)\)$")
YES_NO_UNKNOWN = {"YES", "NO", "UNKNOWN"}
SLOPE_STATES = {"FLAT", "MODERATE", "STEEP", "RISK", "UNKNOWN"}
SIGNAL_STATES = {"TRAFFIC_SIGNALS", "NO", "UNKNOWN"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def parse_point(value: str) -> tuple[float, float]:
    match = POINT_RE.match(value.strip())
    if not match:
        raise ValueError(f"unsupported POINT EWKT: {value!r}")
    return float(match.group(1)), float(match.group(2))


def parse_linestring(value: str) -> list[tuple[float, float]]:
    match = LINE_RE.match(value.strip())
    if not match:
        raise ValueError(f"unsupported LINESTRING EWKT: {value!r}")
    coords: list[tuple[float, float]] = []
    for pair in match.group(1).split(","):
        lon, lat = pair.strip().split(" ")
        coords.append((float(lon), float(lat)))
    if len(coords) < 2:
        raise ValueError(f"LINESTRING must have at least two points: {value!r}")
    return coords


def point_ewkt(coord: tuple[float, float]) -> str:
    return f"SRID=4326;POINT({coord[0]:.8f} {coord[1]:.8f})"


def coord_key(coord: tuple[float, float]) -> str:
    return f"{coord[0]:.8f}:{coord[1]:.8f}"


def meters(left: tuple[float, float], right: tuple[float, float]) -> float:
    lon1, lat1 = left
    lon2, lat2 = right
    lat_mid = math.radians((lat1 + lat2) / 2.0)
    dx = (lon2 - lon1) * 111_320.0 * math.cos(lat_mid)
    dy = (lat2 - lat1) * 110_540.0
    return math.hypot(dx, dy)


def line_length_meter(coords: list[tuple[float, float]]) -> float:
    return sum(meters(left, right) for left, right in zip(coords, coords[1:]))


def in_bbox(coord: tuple[float, float], bbox: tuple[float, float, float, float]) -> bool:
    min_lon, min_lat, max_lon, max_lat = bbox
    lon, lat = coord
    return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat


def segment_in_any_target(coords: list[tuple[float, float]], bboxes: dict[str, tuple[float, float, float, float]]) -> bool:
    return any(in_bbox(coord, bbox) for coord in coords for bbox in bboxes.values())


def matching_dongs(coords: list[tuple[float, float]], bboxes: dict[str, tuple[float, float, float, float]]) -> list[str]:
    matches = []
    for dong_id, bbox in bboxes.items():
        if any(in_bbox(coord, bbox) for coord in coords):
            matches.append(dong_id)
    return matches


def node_lookup(rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {(row.get("vertexId") or "").strip(): row for row in rows}


def normalize_yes_no_unknown(value: str | None) -> str:
    normalized = (value or "").strip().upper()
    return normalized if normalized in YES_NO_UNKNOWN else "UNKNOWN"


def normalize_slope_state(row: dict[str, str]) -> str:
    normalized = (row.get("slopeState") or row.get("rampState") or "UNKNOWN").strip().upper()
    return normalized if normalized in SLOPE_STATES else "UNKNOWN"


def normalize_signal_state(row: dict[str, str]) -> str:
    normalized = (row.get("signalState") or row.get("crossingState") or "UNKNOWN").strip().upper()
    if normalized == "YES":
        return "TRAFFIC_SIGNALS"
    return normalized if normalized in SIGNAL_STATES else "UNKNOWN"


def normalize_segment_type(value: str | None) -> str:
    normalized = (value or "").strip().upper()
    if normalized in {"ROAD_BOUNDARY", "ROAD_BOUNDARY_INNER", "SIDE_LEFT", "SIDE_RIGHT"}:
        return "SIDE_LINE"
    return normalized if normalized in {"SIDE_LINE", "SIDE_WALK"} else "SIDE_LINE"


def select_segments(
    rows: list[dict[str, str]],
    *,
    target_bboxes: dict[str, tuple[float, float, float, float]],
    include_target: bool,
) -> tuple[list[dict[str, Any]], Counter[str]]:
    selected: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for row in rows:
        coords = parse_linestring(row.get("geom", ""))
        matched_dongs = matching_dongs(coords, target_bboxes)
        is_target = bool(matched_dongs)
        for dong_id in matched_dongs:
            counts[dong_id] += 1
        if is_target == include_target:
            selected.append({"row": row, "coords": coords, "matchedDongs": matched_dongs})
    return selected, counts


def build_outputs(
    *,
    base_nodes: list[dict[str, str]],
    base_segments: list[dict[str, str]],
    replacement_nodes: list[dict[str, str]],
    replacement_segments: list[dict[str, str]],
    target_bboxes: dict[str, tuple[float, float, float, float]],
) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, Any]]:
    base_selected, base_target_counts = select_segments(
        base_segments,
        target_bboxes=target_bboxes,
        include_target=False,
    )
    replacement_selected, replacement_target_counts = select_segments(
        replacement_segments,
        target_bboxes=target_bboxes,
        include_target=True,
    )

    source_nodes = {
        "base": node_lookup(base_nodes),
        "replacement": node_lookup(replacement_nodes),
    }
    merged_nodes: list[dict[str, str]] = []
    merged_segments: list[dict[str, str]] = []
    new_node_id_by_coord: dict[str, int] = {}
    next_vertex_id = 1
    skipped_invalid_length_segments: Counter[str] = Counter()
    endpoint_geometry_fallbacks: Counter[str] = Counter()
    endpoint_source_node_snaps: Counter[str] = Counter()

    def resolve_node(source: str, old_node_id: str, fallback: tuple[float, float]) -> tuple[int, tuple[float, float]]:
        nonlocal next_vertex_id
        source_row = source_nodes[source].get(old_node_id)
        source_coord = parse_point(source_row["point"]) if source_row else None
        if source_coord and meters(source_coord, fallback) <= SOURCE_NODE_SNAP_TOLERANCE_METER:
            coord = source_coord
            endpoint_source_node_snaps[source] += 1
        else:
            coord = fallback
            endpoint_geometry_fallbacks[source] += 1
        key = coord_key(coord)
        if key in new_node_id_by_coord:
            return new_node_id_by_coord[key], coord
        new_vertex_id = next_vertex_id
        next_vertex_id += 1
        new_node_id_by_coord[key] = new_vertex_id
        source_key = source_row.get("sourceNodeKey", "") if source_row else f"missing:{source}:{old_node_id}"
        merged_nodes.append(
            {
                "vertexId": str(new_vertex_id),
                "sourceNodeKey": f"v7:{source}:{source_key}",
                "point": point_ewkt(coord),
            }
        )
        return new_vertex_id, coord

    def append_segments(source: str, selected: list[dict[str, Any]]) -> Counter[str]:
        type_counts: Counter[str] = Counter()
        for item in selected:
            row = item["row"]
            coords = item["coords"]
            if line_length_meter(coords) <= 0.01:
                skipped_invalid_length_segments[source] += 1
                continue
            from_node_id, from_coord = resolve_node(source, (row.get("fromNodeId") or "").strip(), coords[0])
            to_node_id, to_coord = resolve_node(source, (row.get("toNodeId") or "").strip(), coords[-1])
            output_coords = [from_coord, *coords[1:-1], to_coord]
            if line_length_meter(output_coords) <= 0.01:
                skipped_invalid_length_segments[source] += 1
                continue
            segment_type = normalize_segment_type(row.get("segmentType"))
            type_counts[segment_type] += 1
            merged_segments.append(
                {
                    "edgeId": str(len(merged_segments) + 1),
                    "fromNodeId": str(from_node_id),
                    "toNodeId": str(to_node_id),
                    "geom": "SRID=4326;LINESTRING("
                    + ", ".join(f"{lon:.8f} {lat:.8f}" for lon, lat in output_coords)
                    + ")",
                    "lengthMeter": row.get("lengthMeter", ""),
                    "walkAccess": normalize_yes_no_unknown(row.get("walkAccess")),
                    "avgSlopePercent": row.get("avgSlopePercent", ""),
                    "widthMeter": row.get("widthMeter", ""),
                    "brailleBlockState": normalize_yes_no_unknown(row.get("brailleBlockState")),
                    "audioSignalState": normalize_yes_no_unknown(row.get("audioSignalState")),
                    "slopeState": normalize_slope_state(row),
                    "widthState": row.get("widthState") or "UNKNOWN",
                    "surfaceState": row.get("surfaceState") or "UNKNOWN",
                    "stairsState": normalize_yes_no_unknown(row.get("stairsState")),
                    "signalState": normalize_signal_state(row),
                    "segmentType": segment_type,
                }
            )
        return type_counts

    base_output_type_counts = append_segments("base", base_selected)
    replacement_output_type_counts = append_segments("replacement", replacement_selected)
    output_type_counts = Counter(row["segmentType"] for row in merged_segments)

    report = {
        "outputs": {
            "nodeCsv": str(DEFAULT_OUTPUT_NODE_CSV.relative_to(ROOT_DIR)),
            "segmentCsv": str(DEFAULT_OUTPUT_SEGMENT_CSV.relative_to(ROOT_DIR)),
        },
        "sources": {
            "base": {
                "nodeCsv": str(DEFAULT_BASE_NODE_CSV.relative_to(ROOT_DIR)),
                "segmentCsv": str(DEFAULT_BASE_SEGMENT_CSV.relative_to(ROOT_DIR)),
            },
            "replacement": {
                "nodeCsv": str(DEFAULT_REPLACEMENT_NODE_CSV.relative_to(ROOT_DIR)),
                "segmentCsv": str(DEFAULT_REPLACEMENT_SEGMENT_CSV.relative_to(ROOT_DIR)),
            },
        },
        "targetDongIds": list(TARGET_DONG_IDS),
        "targetRule": "segment is selected when any LineString vertex falls inside the target dong bbox rectangles from GANGSEO_DONG_AREAS",
        "base": {
            "inputSegments": len(base_segments),
            "keptSegments": len(base_selected),
            "removedTargetSegments": len(base_segments) - len(base_selected),
            "removedTargetSegmentsByDongBbox": dict(base_target_counts),
            "outputSegmentTypeCounts": dict(sorted(base_output_type_counts.items())),
        },
        "replacement": {
            "inputSegments": len(replacement_segments),
            "takenTargetSegments": len(replacement_selected),
            "takenTargetSegmentsByDongBbox": dict(replacement_target_counts),
            "outputSegmentTypeCounts": dict(sorted(replacement_output_type_counts.items())),
        },
        "output": {
            "nodeCount": len(merged_nodes),
            "segmentCount": len(merged_segments),
            "segmentTypeCounts": dict(sorted(output_type_counts.items())),
            "skippedInvalidLengthSegments": dict(sorted(skipped_invalid_length_segments.items())),
            "endpointGeometryFallbacks": dict(sorted(endpoint_geometry_fallbacks.items())),
            "endpointSourceNodeSnaps": dict(sorted(endpoint_source_node_snaps.items())),
        },
        "schemaPolicy": {
            "segmentType": "ROAD_BOUNDARY, ROAD_BOUNDARY_INNER, SIDE_LEFT, SIDE_RIGHT are normalized to SIDE_LINE; SIDE_WALK is preserved.",
            "removedColumns": ["elevatorState", "crossingState", "rampState"],
            "renamedOrReplacedColumns": {
                "rampState": "slopeState",
                "crossingState": "signalState",
            },
        },
        "idPolicy": f"v7 renumbers all vertexId and edgeId sequentially, snaps segment endpoints to source nodes within {SOURCE_NODE_SNAP_TOLERANCE_METER:g}m, falls back to segment geometry endpoints for stale references, and merges endpoint nodes with identical 8-decimal lon/lat coordinates.",
    }
    return merged_nodes, merged_segments, report


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Gangseo v7 merged node CSV and normalized segment CSV.")
    parser.add_argument("--base-node-csv", type=Path, default=DEFAULT_BASE_NODE_CSV)
    parser.add_argument("--base-segment-csv", type=Path, default=DEFAULT_BASE_SEGMENT_CSV)
    parser.add_argument("--replacement-node-csv", type=Path, default=DEFAULT_REPLACEMENT_NODE_CSV)
    parser.add_argument("--replacement-segment-csv", type=Path, default=DEFAULT_REPLACEMENT_SEGMENT_CSV)
    parser.add_argument("--output-node-csv", type=Path, default=DEFAULT_OUTPUT_NODE_CSV)
    parser.add_argument("--output-segment-csv", type=Path, default=DEFAULT_OUTPUT_SEGMENT_CSV)
    parser.add_argument("--report-json", type=Path, default=REPORT_OUTPUT)
    args = parser.parse_args()

    target_bboxes = {
        dong_id: segment_graph_db.area_bbox_tuple(segment_graph_db.gangseo_dong_area(dong_id))
        for dong_id in TARGET_DONG_IDS
    }
    nodes, segments, report = build_outputs(
        base_nodes=read_csv(args.base_node_csv),
        base_segments=read_csv(args.base_segment_csv),
        replacement_nodes=read_csv(args.replacement_node_csv),
        replacement_segments=read_csv(args.replacement_segment_csv),
        target_bboxes=target_bboxes,
    )
    report["outputs"] = {
        "nodeCsv": str(args.output_node_csv.relative_to(ROOT_DIR)),
        "segmentCsv": str(args.output_segment_csv.relative_to(ROOT_DIR)),
    }
    write_csv(args.output_node_csv, nodes, TARGET_NODE_FIELDS)
    write_csv(args.output_segment_csv, segments, TARGET_SEGMENT_FIELDS)
    args.report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
