#!/usr/bin/env python3
"""Apply accepted Sinho connectivity candidates to CSV graph outputs."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

from pyproj import Transformer
from shapely.geometry import LineString, Point
from shapely.ops import substring

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from validate_csv_graph import parse_linestring, parse_point


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_SEGMENTS = ROOT_DIR / "runtime" / "graphhopper" / "topology" / "sinho_road_segments_v8.csv"
DEFAULT_NODES = ROOT_DIR / "runtime" / "graphhopper" / "topology" / "sinho_road_nodes_v8.csv"
DEFAULT_ANALYSIS = ROOT_DIR / "runtime" / "graphhopper" / "topology" / "sinho_connectivity_analysis.json"
DEFAULT_OUTPUT_SEGMENTS = ROOT_DIR / "runtime" / "graphhopper" / "topology" / "sinho_road_segments_v9.csv"
DEFAULT_OUTPUT_NODES = ROOT_DIR / "runtime" / "graphhopper" / "topology" / "sinho_road_nodes_v9.csv"
DEFAULT_REPORT = ROOT_DIR / "runtime" / "graphhopper" / "topology" / "sinho_connectivity_apply_report.json"


SEGMENT_DEFAULTS = {
    "walkAccess": "UNKNOWN",
    "avgSlopePercent": "",
    "widthMeter": "",
    "brailleBlockState": "UNKNOWN",
    "audioSignalState": "UNKNOWN",
    "slopeState": "UNKNOWN",
    "widthState": "UNKNOWN",
    "surfaceState": "UNKNOWN",
    "stairsState": "UNKNOWN",
    "signalState": "UNKNOWN",
    "segmentType": "SIDE_LINE",
}


def numeric_id(value: str | int | None) -> int:
    try:
        return int(str(value or "").strip())
    except ValueError:
        return 0


def point_wkt(coord: tuple[float, float]) -> str:
    return f"SRID=4326;POINT({coord[0]:.8f} {coord[1]:.8f})"


def line_wkt(coords: list[tuple[float, float]]) -> str:
    body = ", ".join(f"{lon:.8f} {lat:.8f}" for lon, lat in coords)
    return f"SRID=4326;LINESTRING({body})"


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def lonlat_from_xy_line(line: LineString, transformer: Transformer) -> list[tuple[float, float]]:
    coords: list[tuple[float, float]] = []
    for x, y in line.coords:
        lon, lat = transformer.transform(x, y)
        coords.append((lon, lat))
    return coords


def load_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="", encoding="utf-8-sig") as fp:
        reader = csv.DictReader(fp)
        return list(reader), list(reader.fieldnames or [])


def new_connector_row(
    *,
    edge_id: int,
    from_node_id: str,
    to_node_id: str,
    from_coord: tuple[float, float],
    to_coord: tuple[float, float],
    to_5179: Transformer,
    segment_fields: list[str],
    source: str,
) -> dict[str, str]:
    xy = [to_5179.transform(*from_coord), to_5179.transform(*to_coord)]
    length_meter = LineString(xy).length
    row = {field: "" for field in segment_fields}
    row.update(SEGMENT_DEFAULTS)
    row["edgeId"] = str(edge_id)
    row["fromNodeId"] = from_node_id
    row["toNodeId"] = to_node_id
    row["geom"] = line_wkt([from_coord, to_coord])
    row["lengthMeter"] = f"{length_meter:.2f}"
    row["walkAccess"] = "YES"
    row["surfaceState"] = "UNKNOWN"
    row["slopeState"] = "UNKNOWN"
    row["segmentType"] = "SIDE_LINE"
    if "source" in row:
        row["source"] = source
    return row


def apply(args: argparse.Namespace) -> dict[str, Any]:
    to_5179 = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    from_5179 = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)
    node_rows, node_fields = load_rows(args.nodes)
    segment_rows, segment_fields = load_rows(args.segments)
    analysis = json.loads(args.analysis.read_text(encoding="utf-8"))

    node_by_id = {row["vertexId"]: row for row in node_rows}
    node_lonlat = {node_id: tuple(parse_point(row["point"])) for node_id, row in node_by_id.items()}
    node_xy = {node_id: to_5179.transform(*coord) for node_id, coord in node_lonlat.items()}
    segment_by_edge = {row["edgeId"]: row for row in segment_rows}
    max_node_id = max((numeric_id(row.get("vertexId")) for row in node_rows), default=0)
    max_edge_id = max((numeric_id(row.get("edgeId")) for row in segment_rows), default=0)
    next_node_id = max_node_id + 1
    next_edge_id = max_edge_id + 1

    accepted = [
        item
        for item in analysis.get("candidates", [])
        if item.get("color") in {"orange", "red", "yellow"}
    ]
    if args.include_low_priority:
        accepted.extend(
            item
            for item in analysis.get("lowPriorityCandidates", [])
            if item.get("color") in {"orange", "red"}
        )
    yellow = [item for item in accepted if item.get("type") == "SPLIT_AND_CONNECT"]
    endpoint_connectors = [item for item in accepted if item.get("type") == "ENDPOINT_TO_ENDPOINT"]

    split_candidates_by_edge: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in yellow:
        edge_id = str(candidate.get("toEdgeId") or "")
        if edge_id in segment_by_edge:
            split_candidates_by_edge[edge_id].append(candidate)

    split_nodes_by_edge: dict[str, list[dict[str, Any]]] = defaultdict(list)
    redirect: dict[str, str] = {}
    yellow_connectors: list[tuple[str, str, str]] = []
    applied_yellow_merges: list[dict[str, Any]] = []
    applied_node_merges: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    def resolve_node_id(node_id: str) -> str:
        seen: set[str] = set()
        current = node_id
        while current in redirect and current not in seen:
            seen.add(current)
            current = redirect[current]
        return current

    if args.include_node_merges:
        for candidate in sorted(analysis.get("nodeMergeCandidates", []), key=lambda item: item.get("distanceMeter", 0)):
            from_id = resolve_node_id(str(candidate.get("fromNodeId") or ""))
            to_id = resolve_node_id(str(candidate.get("toNodeId") or ""))
            if not from_id or not to_id or from_id == to_id:
                skipped.append({"candidateId": candidate.get("candidateId"), "reason": "node merge resolves to same node"})
                continue
            if from_id not in node_xy or to_id not in node_xy:
                skipped.append({"candidateId": candidate.get("candidateId"), "reason": "node merge endpoint missing"})
                continue
            redirect[from_id] = to_id
            applied_node_merges.append(
                {
                    "candidateId": candidate.get("candidateId"),
                    "fromNodeId": from_id,
                    "canonicalNodeId": to_id,
                    "distanceMeter": candidate.get("distanceMeter"),
                }
            )

    for edge_id, candidates in split_candidates_by_edge.items():
        source_row = segment_by_edge[edge_id]
        source_coords = parse_linestring(source_row["geom"])
        source_xy = [to_5179.transform(*coord) for coord in source_coords]
        line = LineString(source_xy)
        prepared: list[dict[str, Any]] = []
        for candidate in candidates:
            split_point_lonlat = tuple(candidate.get("splitPoint") or candidate.get("geometry", [[], []])[-1])
            split_xy = to_5179.transform(*split_point_lonlat)
            projection = line.project(Point(split_xy))
            if projection <= 0.01 or projection >= line.length - 0.01:
                skipped.append({"candidateId": candidate.get("candidateId"), "reason": "split point is at edge endpoint"})
                continue
            prepared.append({**candidate, "projectionMeter": projection, "splitXY": split_xy})
        prepared.sort(key=lambda item: item["projectionMeter"])
        clusters: list[list[dict[str, Any]]] = []
        for item in prepared:
            if not clusters or item["projectionMeter"] - clusters[-1][-1]["projectionMeter"] > args.split_cluster_meter:
                clusters.append([item])
            else:
                clusters[-1].append(item)
        for cluster_index, cluster in enumerate(clusters, start=1):
            projection = sum(item["projectionMeter"] for item in cluster) / len(cluster)
            point = line.interpolate(projection)
            split_xy = (point.x, point.y)
            split_lonlat = from_5179.transform(*split_xy)
            node_id = str(next_node_id)
            next_node_id += 1
            row = {field: "" for field in node_fields}
            row["vertexId"] = node_id
            row["sourceNodeKey"] = f"connectivity:split:{edge_id}:{cluster_index}"
            row["point"] = point_wkt(split_lonlat)
            node_by_id[node_id] = row
            node_lonlat[node_id] = split_lonlat
            node_xy[node_id] = split_xy
            split_nodes_by_edge[edge_id].append({"nodeId": node_id, "projectionMeter": projection})
            for item in cluster:
                from_node_id = str(item.get("fromNodeId") or "")
                if from_node_id not in node_xy:
                    skipped.append({"candidateId": item.get("candidateId"), "reason": "from node missing"})
                    continue
                gap = distance(node_xy[from_node_id], split_xy)
                if gap <= args.yellow_merge_meter:
                    redirect[from_node_id] = node_id
                    applied_yellow_merges.append(
                        {
                            "candidateId": item.get("candidateId"),
                            "fromNodeId": from_node_id,
                            "canonicalNodeId": node_id,
                            "distanceMeter": round(gap, 3),
                        }
                    )
                else:
                    yellow_connectors.append((str(item.get("candidateId") or ""), from_node_id, node_id))

    output_segments: list[dict[str, str]] = []
    removed_original_edges: list[str] = []
    removed_short_edges: list[dict[str, Any]] = []
    removed_self_loops: list[dict[str, Any]] = []

    def append_segment(row: dict[str, str]) -> None:
        from_id = resolve_node_id(row.get("fromNodeId", ""))
        to_id = resolve_node_id(row.get("toNodeId", ""))
        if from_id == to_id:
            removed_self_loops.append({"edgeId": row.get("edgeId", ""), "nodeId": from_id})
            return
        if from_id not in node_lonlat or to_id not in node_lonlat:
            skipped.append({"edgeId": row.get("edgeId"), "reason": "segment endpoint node missing"})
            return
        coords = parse_linestring(row["geom"])
        coords[0] = node_lonlat[from_id]
        coords[-1] = node_lonlat[to_id]
        length_meter = LineString([to_5179.transform(*coord) for coord in coords]).length
        if length_meter < args.remove_short_edge_meter:
            removed_short_edges.append({"edgeId": row.get("edgeId", ""), "lengthMeter": round(length_meter, 3)})
            return
        new_row = row.copy()
        new_row["fromNodeId"] = from_id
        new_row["toNodeId"] = to_id
        new_row["geom"] = line_wkt(coords)
        new_row["lengthMeter"] = f"{length_meter:.2f}"
        output_segments.append(new_row)

    for row in segment_rows:
        edge_id = row["edgeId"]
        if edge_id not in split_nodes_by_edge:
            append_segment(row)
            continue
        source_coords = parse_linestring(row["geom"])
        source_line = LineString([to_5179.transform(*coord) for coord in source_coords])
        split_points = sorted(split_nodes_by_edge[edge_id], key=lambda item: item["projectionMeter"])
        distances = [0.0] + [item["projectionMeter"] for item in split_points] + [source_line.length]
        node_ids = [resolve_node_id(row["fromNodeId"])] + [item["nodeId"] for item in split_points] + [resolve_node_id(row["toNodeId"])]
        for index in range(len(distances) - 1):
            start = distances[index]
            end = distances[index + 1]
            if end <= start:
                continue
            part = substring(source_line, start, end)
            if part.geom_type != "LineString" or part.length <= 0:
                continue
            new_row = row.copy()
            new_row["edgeId"] = str(next_edge_id)
            next_edge_id += 1
            new_row["fromNodeId"] = node_ids[index]
            new_row["toNodeId"] = node_ids[index + 1]
            new_row["geom"] = line_wkt(lonlat_from_xy_line(part, from_5179))
            append_segment(new_row)
        removed_original_edges.append(edge_id)

    added_orange: list[dict[str, Any]] = []
    added_yellow_connectors: list[dict[str, Any]] = []
    for candidate in endpoint_connectors:
        from_id = resolve_node_id(str(candidate.get("fromNodeId") or ""))
        to_id = resolve_node_id(str(candidate.get("toNodeId") or ""))
        if from_id == to_id:
            skipped.append({"candidateId": candidate.get("candidateId"), "reason": "resolved endpoint is same node"})
            continue
        if from_id not in node_lonlat or to_id not in node_lonlat:
            skipped.append({"candidateId": candidate.get("candidateId"), "reason": "endpoint node missing"})
            continue
        row = new_connector_row(
            edge_id=next_edge_id,
            from_node_id=from_id,
            to_node_id=to_id,
            from_coord=node_lonlat[from_id],
            to_coord=node_lonlat[to_id],
            to_5179=to_5179,
            segment_fields=segment_fields,
            source=str(candidate.get("candidateId") or ""),
        )
        next_edge_id += 1
        added_orange.append({"candidateId": candidate.get("candidateId"), "edgeId": row["edgeId"], "color": candidate.get("color")})
        append_segment(row)

    for candidate_id, from_id_raw, to_id_raw in yellow_connectors:
        from_id = resolve_node_id(from_id_raw)
        to_id = resolve_node_id(to_id_raw)
        if from_id == to_id:
            continue
        row = new_connector_row(
            edge_id=next_edge_id,
            from_node_id=from_id,
            to_node_id=to_id,
            from_coord=node_lonlat[from_id],
            to_coord=node_lonlat[to_id],
            to_5179=to_5179,
            segment_fields=segment_fields,
            source=candidate_id,
        )
        next_edge_id += 1
        added_yellow_connectors.append({"candidateId": candidate_id, "edgeId": row["edgeId"]})
        append_segment(row)

    deduped_segments: list[dict[str, str]] = []
    seen: dict[tuple[str, str, str], str] = {}
    removed_duplicates: list[dict[str, Any]] = []
    for row in output_segments:
        left = row["fromNodeId"]
        right = row["toNodeId"]
        if left > right:
            left, right = right, left
        key = (left, right, row.get("segmentType", ""))
        if key in seen:
            removed_duplicates.append({"edgeId": row["edgeId"], "keptEdgeId": seen[key]})
            continue
        seen[key] = row["edgeId"]
        deduped_segments.append(row)

    referenced_nodes = {
        node_id
        for row in deduped_segments
        for node_id in (row.get("fromNodeId", ""), row.get("toNodeId", ""))
        if node_id in node_by_id
    }
    output_nodes = [node_by_id[node_id] for node_id in sorted(referenced_nodes, key=numeric_id)]

    args.output_segments.parent.mkdir(parents=True, exist_ok=True)
    args.output_nodes.parent.mkdir(parents=True, exist_ok=True)
    with args.output_segments.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=segment_fields)
        writer.writeheader()
        writer.writerows(deduped_segments)
    with args.output_nodes.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=node_fields)
        writer.writeheader()
        writer.writerows(output_nodes)

    report = {
        "inputs": {
            "segments": str(args.segments),
            "nodes": str(args.nodes),
            "analysis": str(args.analysis),
        },
        "outputs": {
            "segments": str(args.output_segments),
            "nodes": str(args.output_nodes),
        },
        "summary": {
            "sourceSegments": len(segment_rows),
            "sourceNodes": len(node_rows),
            "acceptedEndpointCandidates": len(endpoint_connectors),
            "acceptedOrangeCandidates": sum(1 for item in endpoint_connectors if item.get("color") == "orange"),
            "acceptedRedCandidates": sum(1 for item in endpoint_connectors if item.get("color") == "red"),
            "acceptedYellowCandidates": len(yellow),
            "appliedNodeMerges": len(applied_node_merges),
            "newSplitNodes": sum(len(items) for items in split_nodes_by_edge.values()),
            "yellowNodeMerges": len(applied_yellow_merges),
            "addedOrangeConnectors": len(added_orange),
            "addedYellowConnectors": len(added_yellow_connectors),
            "removedOriginalSplitEdges": len(removed_original_edges),
            "removedSelfLoops": len(removed_self_loops),
            "removedShortEdges": len(removed_short_edges),
            "removedDuplicates": len(removed_duplicates),
            "outputSegments": len(deduped_segments),
            "outputNodes": len(output_nodes),
            "skipped": len(skipped),
        },
        "addedOrange": added_orange,
        "addedYellowConnectors": added_yellow_connectors,
        "nodeMerges": applied_node_merges,
        "yellowNodeMerges": applied_yellow_merges,
        "removed": {
            "originalSplitEdges": removed_original_edges,
            "selfLoops": removed_self_loops,
            "shortEdges": removed_short_edges,
            "duplicates": removed_duplicates,
        },
        "skipped": skipped,
    }
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--segments", type=Path, default=DEFAULT_SEGMENTS)
    parser.add_argument("--nodes", type=Path, default=DEFAULT_NODES)
    parser.add_argument("--analysis", type=Path, default=DEFAULT_ANALYSIS)
    parser.add_argument("--output-segments", type=Path, default=DEFAULT_OUTPUT_SEGMENTS)
    parser.add_argument("--output-nodes", type=Path, default=DEFAULT_OUTPUT_NODES)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--split-cluster-meter", type=float, default=1.0)
    parser.add_argument("--yellow-merge-meter", type=float, default=1.0)
    parser.add_argument("--remove-short-edge-meter", type=float, default=0.3)
    parser.add_argument("--include-low-priority", action="store_true")
    parser.add_argument("--include-node-merges", action="store_true")
    args = parser.parse_args()
    report = apply(args)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
