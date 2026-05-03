#!/usr/bin/env python3
"""Convert Gangseo node/segment CSV files into OSM XML for GraphHopper import."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from xml.sax.saxutils import escape


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from validate_csv_graph import DEFAULT_NODES, DEFAULT_SEGMENTS, parse_linestring, parse_point, validate  # noqa: E402


DEFAULT_OUTPUT = Path("graphhopper/data/gangseo.osm")
DEFAULT_REPORT = Path("runtime/graphhopper/osm/gangseo_osm_report.json")

STATE_DEFAULTS = {
    "walkAccess": "UNKNOWN",
    "brailleBlockState": "UNKNOWN",
    "audioSignalState": "UNKNOWN",
    "slopeState": "UNKNOWN",
    "widthState": "UNKNOWN",
    "surfaceState": "UNKNOWN",
    "stairsState": "UNKNOWN",
    "signalState": "UNKNOWN",
    "segmentType": "UNKNOWN",
}

TAG_COLUMNS = {
    "edgeId": "ieum:edge_id",
    "walkAccess": "ieum:walk_access",
    "avgSlopePercent": "ieum:avg_slope_percent",
    "widthMeter": "ieum:width_meter",
    "brailleBlockState": "ieum:braille_block_state",
    "audioSignalState": "ieum:audio_signal_state",
    "slopeState": "ieum:slope_state",
    "widthState": "ieum:width_state",
    "surfaceState": "ieum:surface_state",
    "stairsState": "ieum:stairs_state",
    "signalState": "ieum:signal_state",
    "segmentType": "ieum:segment_type",
}

HARD_BLOCKER_SUMMARY_KEYS = (
    "missingSegmentColumns",
    "missingNodeColumns",
    "badNodeGeometries",
    "duplicateNodeIds",
    "badNodeReferences",
    "badSegmentGeometries",
    "endpointMismatches",
    "duplicateEdgeIds",
    "selfLoops",
    "isolatedNodes",
)


@dataclass(frozen=True)
class OsmNode:
    osm_id: int
    lon: float
    lat: float
    source: str


@dataclass(frozen=True)
class OsmWay:
    osm_id: int
    node_refs: tuple[int, ...]
    tags: dict[str, str]


def coord_key(coord: tuple[float, float]) -> tuple[float, float]:
    return round(coord[0], 8), round(coord[1], 8)


def parse_positive_int(value: str) -> int | None:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def hard_blockers(report: dict) -> list[str]:
    summary = report["summary"]
    blockers: list[str] = []
    for key in HARD_BLOCKER_SUMMARY_KEYS:
        value = summary.get(key)
        if isinstance(value, list):
            if value:
                blockers.append(f"{key}={value}")
        elif value:
            blockers.append(f"{key}={value}")
    enum_violations = summary.get("enumViolationColumns") or {}
    if enum_violations:
        blockers.append(f"enumViolationColumns={enum_violations}")
    return blockers


def allocate_existing_node_ids(node_rows: list[dict[str, str]]) -> dict[str, int]:
    numeric_ids = [parse_positive_int(row.get("vertexId", "")) for row in node_rows]
    used = {value for value in numeric_ids if value is not None}
    next_id = max(used, default=0) + 1
    node_id_by_vertex: dict[str, int] = {}
    for row, numeric_id in zip(node_rows, numeric_ids):
        vertex_id = (row.get("vertexId") or "").strip()
        if not vertex_id:
            raise ValueError("node row has blank vertexId")
        if numeric_id is not None and numeric_id not in node_id_by_vertex.values():
            node_id_by_vertex[vertex_id] = numeric_id
            continue
        while next_id in used:
            next_id += 1
        node_id_by_vertex[vertex_id] = next_id
        used.add(next_id)
        next_id += 1
    return node_id_by_vertex


def allocate_way_id(edge_id: str, used_way_ids: set[int], next_way_id: int) -> tuple[int, int]:
    parsed = parse_positive_int(edge_id)
    if parsed is not None and parsed not in used_way_ids:
        used_way_ids.add(parsed)
        return parsed, next_way_id
    while next_way_id in used_way_ids:
        next_way_id += 1
    used_way_ids.add(next_way_id)
    return next_way_id, next_way_id + 1


def normalize_tag_value(column: str, value: str | None) -> str:
    text = (value or "").strip()
    if text:
        return text
    return STATE_DEFAULTS.get(column, "UNKNOWN")


def build_way_tags(row: dict[str, str]) -> dict[str, str]:
    tags = {
        "highway": "footway",
        "foot": "yes",
        "oneway": "no",
        "source": "mapping.csv",
    }
    for column, tag in TAG_COLUMNS.items():
        tags[tag] = normalize_tag_value(column, row.get(column))
    return tags


def build_osm(nodes_path: Path, segments_path: Path) -> tuple[list[OsmNode], list[OsmWay], dict[str, int]]:
    node_rows = read_rows(nodes_path)
    segment_rows = read_rows(segments_path)
    if not node_rows:
        raise ValueError(f"node CSV has no rows: {nodes_path}")
    if not segment_rows:
        raise ValueError(f"segment CSV has no rows: {segments_path}")

    node_id_by_vertex = allocate_existing_node_ids(node_rows)
    osm_nodes: list[OsmNode] = []
    osm_node_by_coord: dict[tuple[float, float], int] = {}
    used_node_ids = set(node_id_by_vertex.values())

    for row in node_rows:
        vertex_id = (row.get("vertexId") or "").strip()
        lon, lat = parse_point(row.get("point", ""))
        osm_id = node_id_by_vertex[vertex_id]
        osm_nodes.append(OsmNode(osm_id=osm_id, lon=lon, lat=lat, source="road_nodes.csv"))
        osm_node_by_coord.setdefault(coord_key((lon, lat)), osm_id)

    next_node_id = max(used_node_ids, default=0) + 1
    used_way_ids: set[int] = set()
    next_way_id = 1
    osm_ways: list[OsmWay] = []
    synthetic_node_count = 0
    defaulted_tag_count = 0

    for row in segment_rows:
        edge_id = (row.get("edgeId") or "").strip()
        from_vertex = (row.get("fromNodeId") or "").strip()
        to_vertex = (row.get("toNodeId") or "").strip()
        if from_vertex not in node_id_by_vertex or to_vertex not in node_id_by_vertex:
            raise ValueError(f"segment {edge_id} references a missing node")
        points = parse_linestring(row.get("geom", ""))
        node_refs = [node_id_by_vertex[from_vertex]]

        for point in points[1:-1]:
            key = coord_key(point)
            osm_id = osm_node_by_coord.get(key)
            if osm_id is None:
                while next_node_id in used_node_ids:
                    next_node_id += 1
                lon, lat = key
                osm_id = next_node_id
                osm_node_by_coord[key] = osm_id
                used_node_ids.add(osm_id)
                osm_nodes.append(OsmNode(osm_id=osm_id, lon=lon, lat=lat, source="segment_shape"))
                synthetic_node_count += 1
                next_node_id += 1
            if node_refs[-1] != osm_id:
                node_refs.append(osm_id)

        to_osm_id = node_id_by_vertex[to_vertex]
        if node_refs[-1] != to_osm_id:
            node_refs.append(to_osm_id)

        way_id, next_way_id = allocate_way_id(edge_id, used_way_ids, next_way_id)
        tags = build_way_tags(row)
        defaulted_tag_count += sum(1 for column in TAG_COLUMNS if not (row.get(column) or "").strip())
        osm_ways.append(OsmWay(osm_id=way_id, node_refs=tuple(node_refs), tags=tags))

    report = {
        "sourceNodeRows": len(node_rows),
        "sourceSegmentRows": len(segment_rows),
        "osmNodes": len(osm_nodes),
        "osmWays": len(osm_ways),
        "syntheticShapeNodes": synthetic_node_count,
        "defaultedIeumTags": defaulted_tag_count,
    }
    return osm_nodes, osm_ways, report


def xml_attr(value: object) -> str:
    return escape(str(value), {'"': "&quot;"})


def write_osm_xml(path: Path, nodes: Iterable[OsmNode], ways: Iterable[OsmWay]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        fh.write('<osm version="0.6" generator="busan-eumgil-csv-to-osm">\n')
        for node in nodes:
            fh.write(f'  <node id="{node.osm_id}" lat="{node.lat:.8f}" lon="{node.lon:.8f}">\n')
            fh.write(f'    <tag k="source" v="{xml_attr(node.source)}" />\n')
            fh.write("  </node>\n")
        for way in ways:
            fh.write(f'  <way id="{way.osm_id}">\n')
            for node_ref in way.node_refs:
                fh.write(f'    <nd ref="{node_ref}" />\n')
            for key, value in way.tags.items():
                fh.write(f'    <tag k="{xml_attr(key)}" v="{xml_attr(value)}" />\n')
            fh.write("  </way>\n")
        fh.write("</osm>\n")


def convert(args: argparse.Namespace) -> dict:
    validation_report = validate(args)
    blockers = hard_blockers(validation_report)
    if blockers:
        raise SystemExit("CSV graph validation failed; OSM XML was not written:\n" + "\n".join(f"- {item}" for item in blockers))

    nodes, ways, conversion_report = build_osm(args.nodes, args.segments)
    write_osm_xml(args.output, nodes, ways)
    report = {
        "inputs": {
            "segments": str(args.segments),
            "nodes": str(args.nodes),
        },
        "output": str(args.output),
        "validationSummary": validation_report["summary"],
        "conversion": conversion_report,
        "warnings": {
            "duplicateNodePairEdges": validation_report["summary"].get("duplicateNodePairEdges", 0),
            "connectedComponents": validation_report["summary"].get("connectedComponents", 0),
            "largestComponentEdgeRatio": validation_report["summary"].get("largestComponentEdgeRatio", 0),
        },
    }
    if args.report_json:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert Gangseo routing CSV files to OSM XML.")
    parser.add_argument("--segments", type=Path, default=DEFAULT_SEGMENTS)
    parser.add_argument("--nodes", type=Path, default=DEFAULT_NODES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report-json", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--endpoint-tolerance-meter", type=float, default=1.0)
    parser.add_argument("--zero-length-meter", type=float, default=0.01)
    parser.add_argument("--small-component-edge-threshold", type=int, default=5)
    parser.add_argument("--sample-limit", type=int, default=20)
    args = parser.parse_args()

    report = convert(args)
    print(json.dumps({"output": report["output"], "conversion": report["conversion"], "warnings": report["warnings"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
