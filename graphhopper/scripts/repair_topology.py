#!/usr/bin/env python3
"""Repair node-on-edge topology for a bounded Gangseo routing graph slice."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from pyproj import Transformer
from shapely import STRtree
from shapely.geometry import LineString, Point, box
from shapely.ops import substring

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from validate_csv_graph import parse_linestring, parse_point


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_OUT_DIR = ROOT_DIR / "runtime" / "graphhopper" / "topology"
SINHO_BBOX = (128.858, 35.075, 128.895, 35.105)
POINT_PRECISION = 8


def strip_srid(wkt: str) -> str:
    value = (wkt or "").strip()
    if value.upper().startswith("SRID="):
        _, value = value.split(";", 1)
    return value.strip()


def point_wkt(coord: tuple[float, float]) -> str:
    return f"SRID=4326;POINT({coord[0]:.{POINT_PRECISION}f} {coord[1]:.{POINT_PRECISION}f})"


def line_wkt(coords: list[tuple[float, float]]) -> str:
    body = ", ".join(f"{lon:.{POINT_PRECISION}f} {lat:.{POINT_PRECISION}f}" for lon, lat in coords)
    return f"SRID=4326;LINESTRING({body})"


def bbox_intersects_geom(coords: list[tuple[float, float]], bbox: tuple[float, float, float, float]) -> bool:
    line = LineString(coords)
    return line.intersects(box(*bbox))


def xy_line(coords: list[tuple[float, float]], transformer: Transformer) -> LineString:
    return LineString([transformer.transform(lon, lat) for lon, lat in coords])


def lonlat_from_xy_line(line: LineString, transformer: Transformer) -> list[tuple[float, float]]:
    coords = list(line.coords)
    return [transformer.transform(x, y) for x, y in coords]


def read_nodes(path: Path) -> tuple[list[str], dict[str, dict[str, str]], dict[str, tuple[float, float]], dict[str, tuple[float, float]]]:
    with path.open(newline="", encoding="utf-8-sig") as fp:
        reader = csv.DictReader(fp)
        fieldnames = list(reader.fieldnames or [])
        rows: dict[str, dict[str, str]] = {}
        lonlat: dict[str, tuple[float, float]] = {}
        for row in reader:
            node_id = (row.get("vertexId") or "").strip()
            if not node_id:
                continue
            point = parse_point(row.get("point", ""))
            rows[node_id] = row
            lonlat[node_id] = point
    to_5179 = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    xy = {node_id: to_5179.transform(*coord) for node_id, coord in lonlat.items()}
    return fieldnames, rows, lonlat, xy


def read_segments(path: Path, bbox: tuple[float, float, float, float]) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as fp:
        reader = csv.DictReader(fp)
        fieldnames = list(reader.fieldnames or [])
        rows = []
        for row in reader:
            try:
                coords = parse_linestring(row.get("geom", ""))
            except Exception:
                continue
            if bbox_intersects_geom(coords, bbox):
                rows.append(row)
    return fieldnames, rows


def numeric_id(value: str) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def degree_counts(rows: list[dict[str, str]]) -> Counter[str]:
    degree: Counter[str] = Counter()
    for row in rows:
        degree[(row.get("fromNodeId") or "").strip()] += 1
        degree[(row.get("toNodeId") or "").strip()] += 1
    return degree


def choose_candidate(candidates: list[dict[str, Any]], review: dict[str, list[dict[str, Any]]]) -> dict[str, Any] | None:
    if not candidates:
        return None
    ordered = sorted(candidates, key=lambda item: (item["distanceMeter"], -item["interiorStabilityMeter"], -item["endpointDegreeSum"]))
    if len(ordered) == 1:
        return ordered[0]
    best = ordered[0]
    second = ordered[1]
    if second["distanceMeter"] - best["distanceMeter"] > 0.5:
        return best
    if best["interiorStabilityMeter"] - second["interiorStabilityMeter"] > 1.0:
        return best
    if best["endpointDegreeSum"] > second["endpointDegreeSum"]:
        return best
    review["AMBIGUOUS_BASE_EDGE"].append(
        {
            "nodeId": best["nodeId"],
            "reason": "multiple nearby base edges are too similar by distance, stability, and degree",
            "candidates": [
                {
                    "edgeId": item["edgeId"],
                    "distanceMeter": item["distanceMeter"],
                    "projectionMeter": item["projectionMeter"],
                    "interiorStabilityMeter": item["interiorStabilityMeter"],
                    "endpointDegreeSum": item["endpointDegreeSum"],
                }
                for item in ordered[:5]
            ],
        }
    )
    return None


def projected_candidate(
    *,
    node_id: str,
    node_xy: tuple[float, float],
    segment: dict[str, Any],
    degree: Counter[str],
    split_distance_meter: float,
    endpoint_exclusion_meter: float,
) -> dict[str, Any] | None:
    line: LineString = segment["xyLine"]
    point = Point(node_xy)
    projection = line.project(point)
    distance_meter = point.distance(line)
    if distance_meter > split_distance_meter:
        return None
    from_gap = projection
    to_gap = line.length - projection
    if min(from_gap, to_gap) <= endpoint_exclusion_meter:
        if from_gap <= to_gap:
            target_node_id = segment["fromNodeId"]
            target_endpoint = Point(line.coords[0])
        else:
            target_node_id = segment["toNodeId"]
            target_endpoint = Point(line.coords[-1])
        return {
            "type": "endpoint",
            "nodeId": node_id,
            "targetNodeId": target_node_id,
            "edgeId": segment["edgeId"],
            "distanceMeter": round(distance_meter, 3),
            "projectionMeter": round(projection, 3),
            "endpointDistanceMeter": round(min(from_gap, to_gap), 3),
            "targetEndpointDistanceMeter": round(point.distance(target_endpoint), 3),
            "targetEndpointDegree": degree[target_node_id],
        }
    return {
        "type": "interior",
        "nodeId": node_id,
        "edgeId": segment["edgeId"],
        "distanceMeter": round(distance_meter, 3),
        "projectionMeter": projection,
        "projectedPoint": line.interpolate(projection),
        "interiorStabilityMeter": min(from_gap, to_gap),
        "endpointDegreeSum": degree[segment["fromNodeId"]] + degree[segment["toNodeId"]],
    }


def length_change_ok(
    *,
    node_id: str,
    canonical_xy: tuple[float, float],
    incident_rows: list[dict[str, str]],
    node_xy: dict[str, tuple[float, float]],
    max_shift_floor_meter: float,
    max_shift_ratio: float,
    review: dict[str, list[dict[str, Any]]],
) -> bool:
    old_xy = node_xy[node_id]
    shift = math.hypot(canonical_xy[0] - old_xy[0], canonical_xy[1] - old_xy[1])
    for row in incident_rows:
        other_id = row["toNodeId"] if row["fromNodeId"] == node_id else row["fromNodeId"]
        if other_id not in node_xy:
            continue
        old_len = math.hypot(node_xy[other_id][0] - old_xy[0], node_xy[other_id][1] - old_xy[1])
        allowed = max(max_shift_floor_meter, old_len * max_shift_ratio)
        if shift > allowed:
            review["LARGE_ENDPOINT_SHIFT"].append(
                {
                    "nodeId": node_id,
                    "edgeId": row.get("edgeId", ""),
                    "shiftMeter": round(shift, 3),
                    "oldLengthMeter": round(old_len, 3),
                    "allowedMeter": round(allowed, 3),
                }
            )
            return False
    return True


def replace_endpoint_geometry(
    row: dict[str, str],
    from_coord: tuple[float, float],
    to_coord: tuple[float, float],
) -> list[tuple[float, float]]:
    coords = parse_linestring(row.get("geom", ""))
    coords[0] = from_coord
    coords[-1] = to_coord
    return coords


def feature_key(row: dict[str, str]) -> tuple[str, str, str]:
    left = (row.get("fromNodeId") or "").strip()
    right = (row.get("toNodeId") or "").strip()
    if left > right:
        left, right = right, left
    return left, right, (row.get("segmentType") or "").strip()


def repair(args: argparse.Namespace) -> dict[str, Any]:
    bbox = tuple(args.bbox)
    to_5179 = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    from_5179 = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)
    node_fields, node_rows_all, node_lonlat_all, node_xy_all = read_nodes(args.nodes)
    segment_fields, source_segments = read_segments(args.segments, bbox)

    referenced_node_ids = {
        node_id
        for row in source_segments
        for node_id in ((row.get("fromNodeId") or "").strip(), (row.get("toNodeId") or "").strip())
    }
    node_rows = {node_id: node_rows_all[node_id].copy() for node_id in referenced_node_ids if node_id in node_rows_all}
    node_lonlat = {node_id: node_lonlat_all[node_id] for node_id in node_rows}
    node_xy = {node_id: node_xy_all[node_id] for node_id in node_rows}
    degree = degree_counts(source_segments)
    incident: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in source_segments:
        incident[(row.get("fromNodeId") or "").strip()].append(row)
        incident[(row.get("toNodeId") or "").strip()].append(row)

    segments: list[dict[str, Any]] = []
    for row in source_segments:
        coords = parse_linestring(row.get("geom", ""))
        xyline = xy_line(coords, to_5179)
        segments.append(
            {
                "row": row,
                "edgeId": (row.get("edgeId") or "").strip(),
                "fromNodeId": (row.get("fromNodeId") or "").strip(),
                "toNodeId": (row.get("toNodeId") or "").strip(),
                "segmentType": (row.get("segmentType") or "").strip(),
                "xyLine": xyline,
            }
        )
    lines = [segment["xyLine"] for segment in segments]
    tree = STRtree(lines)
    segment_by_index = {index: segment for index, segment in enumerate(segments)}

    review: dict[str, list[dict[str, Any]]] = defaultdict(list)
    candidates_by_node: dict[str, list[dict[str, Any]]] = defaultdict(list)
    endpoint_candidates_by_node: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node_id, point_xy in node_xy.items():
        point = Point(point_xy)
        for raw_index in tree.query(point.buffer(args.split_distance_meter)):
            segment = segment_by_index[int(raw_index)]
            if node_id in {segment["fromNodeId"], segment["toNodeId"]}:
                continue
            candidate = projected_candidate(
                node_id=node_id,
                node_xy=point_xy,
                segment=segment,
                degree=degree,
                split_distance_meter=args.split_distance_meter,
                endpoint_exclusion_meter=args.endpoint_exclusion_meter,
            )
            if candidate is None:
                continue
            if candidate["type"] == "endpoint":
                endpoint_candidates_by_node[node_id].append(candidate)
                continue
            candidates_by_node[node_id].append(candidate)

    max_node_id = max((numeric_id(node_id) for node_id in node_rows_all), default=0)
    max_edge_id = max((numeric_id(row.get("edgeId", "")) for row in source_segments), default=0)
    next_node_id = max_node_id + 1
    next_edge_id = max_edge_id + 1

    canonical_nodes: list[dict[str, Any]] = []
    redirect: dict[str, str] = {}
    auto_endpoint_merges: list[dict[str, Any]] = []
    split_points_by_edge: dict[str, list[dict[str, Any]]] = defaultdict(list)
    segment_by_edge_id = {segment["edgeId"]: segment for segment in segments}

    for node_id, candidates in endpoint_candidates_by_node.items():
        valid_candidates = [
            item
            for item in candidates
            if item["targetNodeId"] in node_xy
            and item["targetNodeId"] != node_id
            and item["targetEndpointDistanceMeter"] <= args.endpoint_merge_meter
        ]
        if not valid_candidates:
            review["ENDPOINT_MERGE_CANDIDATE"].extend(candidates)
            continue
        chosen = sorted(
            valid_candidates,
            key=lambda item: (item["targetEndpointDistanceMeter"], item["distanceMeter"], -item["targetEndpointDegree"]),
        )[0]
        target_node_id = chosen["targetNodeId"]
        if length_change_ok(
            node_id=node_id,
            canonical_xy=node_xy[target_node_id],
            incident_rows=incident[node_id],
            node_xy=node_xy,
            max_shift_floor_meter=args.max_endpoint_shift_floor_meter,
            max_shift_ratio=args.max_endpoint_shift_ratio,
            review=review,
        ):
            redirect[node_id] = target_node_id
            auto_endpoint_merges.append(
                {
                    "oldNodeId": node_id,
                    "canonicalNodeId": target_node_id,
                    "edgeId": chosen["edgeId"],
                    "distanceMeter": chosen["targetEndpointDistanceMeter"],
                    "reason": "node is within endpoint_merge_meter of an existing edge endpoint",
                }
            )
        else:
            review["ENDPOINT_MERGE_CANDIDATE"].append(chosen)

    selected_by_edge: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node_id, candidates in candidates_by_node.items():
        if node_id in redirect:
            continue
        chosen = choose_candidate(candidates, review)
        if chosen:
            selected_by_edge[chosen["edgeId"]].append(chosen)

    for edge_id, candidates in selected_by_edge.items():
        ordered = sorted(candidates, key=lambda item: item["projectionMeter"])
        clusters: list[list[dict[str, Any]]] = []
        for candidate in ordered:
            if not clusters or candidate["projectionMeter"] - clusters[-1][-1]["projectionMeter"] > args.cluster_projection_meter:
                clusters.append([candidate])
            else:
                clusters[-1].append(candidate)
        for cluster_index, cluster in enumerate(clusters, start=1):
            avg_projection = sum(item["projectionMeter"] for item in cluster) / len(cluster)
            segment = segment_by_edge_id[edge_id]
            canonical_point = segment["xyLine"].interpolate(avg_projection)
            canonical_xy = (canonical_point.x, canonical_point.y)
            valid_old_nodes = [
                item["nodeId"]
                for item in cluster
                if item["nodeId"] not in redirect
                if length_change_ok(
                    node_id=item["nodeId"],
                    canonical_xy=canonical_xy,
                    incident_rows=incident[item["nodeId"]],
                    node_xy=node_xy,
                    max_shift_floor_meter=args.max_endpoint_shift_floor_meter,
                    max_shift_ratio=args.max_endpoint_shift_ratio,
                    review=review,
                )
            ]
            if not valid_old_nodes:
                continue
            new_node_id = str(next_node_id)
            next_node_id += 1
            canonical_lonlat = from_5179.transform(*canonical_xy)
            source_key = f"topology:split:{edge_id}:{cluster_index}"
            row = {field: "" for field in node_fields}
            row["vertexId"] = new_node_id
            row["sourceNodeKey"] = source_key
            row["point"] = point_wkt(canonical_lonlat)
            node_rows[new_node_id] = row
            node_lonlat[new_node_id] = canonical_lonlat
            node_xy[new_node_id] = canonical_xy
            for old_node_id in valid_old_nodes:
                redirect[old_node_id] = new_node_id
            canonical_nodes.append(
                {
                    "canonicalNodeId": new_node_id,
                    "edgeId": edge_id,
                    "clusterIndex": cluster_index,
                    "oldNodeIds": valid_old_nodes,
                    "projectionMeter": round(avg_projection, 3),
                    "point": [round(canonical_lonlat[0], 8), round(canonical_lonlat[1], 8)],
                }
            )
            split_points_by_edge[edge_id].append(
                {
                    "nodeId": new_node_id,
                    "projectionMeter": avg_projection,
                }
            )

    split_original_edge_ids = set(split_points_by_edge)
    repaired_rows: list[dict[str, str]] = []
    removed: dict[str, list[dict[str, Any]]] = defaultdict(list)
    short_edges: list[dict[str, Any]] = []

    def resolve_node_id(node_id: str) -> str:
        seen: set[str] = set()
        current = node_id
        while current in redirect and current not in seen:
            seen.add(current)
            current = redirect[current]
        return current

    def append_segment(row: dict[str, str], coords: list[tuple[float, float]], length_meter: float) -> None:
        if length_meter < args.remove_short_edge_meter:
            removed["length_lt_0_3m"].append({"edgeId": row.get("edgeId", ""), "lengthMeter": round(length_meter, 3)})
            return
        if length_meter < args.review_short_edge_meter:
            short_edges.append({"edgeId": row.get("edgeId", ""), "lengthMeter": round(length_meter, 3)})
        row["geom"] = line_wkt(coords)
        row["lengthMeter"] = f"{length_meter:.2f}"
        repaired_rows.append(row)

    for source in segments:
        edge_id = source["edgeId"]
        row = source["row"]
        if edge_id in split_original_edge_ids:
            split_points = sorted(split_points_by_edge[edge_id], key=lambda item: item["projectionMeter"])
            distances = [0.0] + [item["projectionMeter"] for item in split_points] + [source["xyLine"].length]
            nodes_for_parts = [resolve_node_id(source["fromNodeId"])] + [item["nodeId"] for item in split_points] + [resolve_node_id(source["toNodeId"])]
            for index in range(len(distances) - 1):
                start = distances[index]
                end = distances[index + 1]
                if end <= start:
                    review["INVALID_SPLIT_GEOMETRY"].append({"edgeId": edge_id, "start": start, "end": end})
                    continue
                part = substring(source["xyLine"], start, end)
                if part.geom_type != "LineString" or part.length <= 0:
                    review["INVALID_SPLIT_GEOMETRY"].append({"edgeId": edge_id, "start": start, "end": end})
                    continue
                new_row = row.copy()
                new_row["edgeId"] = str(next_edge_id)
                next_edge_id += 1
                new_row["fromNodeId"] = nodes_for_parts[index]
                new_row["toNodeId"] = nodes_for_parts[index + 1]
                coords = lonlat_from_xy_line(part, from_5179)
                append_segment(new_row, coords, part.length)
            removed["split_original_edges"].append({"edgeId": edge_id, "splitCount": len(split_points) + 1})
            continue

        from_id = resolve_node_id(source["fromNodeId"])
        to_id = resolve_node_id(source["toNodeId"])
        if from_id == to_id:
            removed["self_loops"].append({"edgeId": edge_id, "nodeId": from_id})
            continue
        new_row = row.copy()
        new_row["fromNodeId"] = from_id
        new_row["toNodeId"] = to_id
        coords = replace_endpoint_geometry(new_row, node_lonlat[from_id], node_lonlat[to_id])
        xycoords = [to_5179.transform(*coord) for coord in coords]
        length_meter = LineString(xycoords).length
        append_segment(new_row, coords, length_meter)

    duplicate_seen: dict[tuple[str, str, str], dict[str, str]] = {}
    deduped_rows: list[dict[str, str]] = []
    for row in repaired_rows:
        key = feature_key(row)
        if key in duplicate_seen:
            removed["duplicate_same_segment_type"].append(
                {
                    "edgeId": row.get("edgeId", ""),
                    "keptEdgeId": duplicate_seen[key].get("edgeId", ""),
                    "fromNodeId": row.get("fromNodeId", ""),
                    "toNodeId": row.get("toNodeId", ""),
                    "segmentType": row.get("segmentType", ""),
                }
            )
            continue
        duplicate_seen[key] = row
        deduped_rows.append(row)
    pair_types: dict[tuple[str, str], set[str]] = defaultdict(set)
    pair_edge_ids: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in deduped_rows:
        left = row["fromNodeId"]
        right = row["toNodeId"]
        if left > right:
            left, right = right, left
        pair = (left, right)
        pair_types[pair].add(row.get("segmentType", ""))
        pair_edge_ids[pair].append(row.get("edgeId", ""))
    for pair, types in pair_types.items():
        if len(types) > 1:
            review["DUPLICATE_DIFFERENT_SEGMENT_TYPE"].append(
                {
                    "fromNodeId": pair[0],
                    "toNodeId": pair[1],
                    "segmentTypes": sorted(types),
                    "edgeIds": pair_edge_ids[pair],
                }
            )
    review["SHORT_EDGE_REVIEW"].extend(short_edges)

    referenced_after = {
        node_id
        for row in deduped_rows
        for node_id in ((row.get("fromNodeId") or "").strip(), (row.get("toNodeId") or "").strip())
    }
    output_nodes = [node_rows[node_id] for node_id in sorted(referenced_after, key=lambda value: numeric_id(value))]

    args.output_dir.mkdir(parents=True, exist_ok=True)
    nodes_out = args.output_dir / args.output_nodes_name
    segments_out = args.output_dir / args.output_segments_name
    with nodes_out.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=node_fields)
        writer.writeheader()
        writer.writerows(output_nodes)
    with segments_out.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=segment_fields)
        writer.writeheader()
        writer.writerows(deduped_rows)

    report = {
        "input": {
            "nodes": str(args.nodes),
            "segments": str(args.segments),
            "bbox": bbox,
        },
        "output": {
            "nodes": str(nodes_out),
            "segments": str(segments_out),
        },
        "summary": {
            "sourceSegmentsInBbox": len(source_segments),
            "sourceReferencedNodes": len(node_rows),
            "canonicalNodesCreated": len(canonical_nodes),
            "autoEndpointMerges": len(auto_endpoint_merges),
            "oldNodesRedirected": len(redirect),
            "splitOriginalEdges": len(split_original_edge_ids),
            "outputSegments": len(deduped_rows),
            "outputNodes": len(output_nodes),
            "removed": {key: len(value) for key, value in removed.items()},
            "reviewCandidates": {key: len(value) for key, value in review.items()},
        },
        "canonicalNodes": canonical_nodes,
        "autoEndpointMerges": auto_endpoint_merges,
        "redirects": [
            {"oldNodeId": old, "canonicalNodeId": resolve_node_id(old)}
            for old in sorted(redirect, key=numeric_id)
        ],
        "removed": removed,
    }
    review_doc = {
        "meta": {
            "bbox": bbox,
            "nodes": str(nodes_out),
            "segments": str(segments_out),
        },
        "candidates": review,
    }
    report_path = args.output_dir / "topology_repair_report.json"
    review_path = args.output_dir / "topology_review_candidates.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    review_path.write_text(json.dumps(review_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--nodes", type=Path, default=ROOT_DIR / "etl" / "raw" / "gangseo_road_nodes_v7.csv")
    parser.add_argument("--segments", type=Path, default=ROOT_DIR / "etl" / "raw" / "gangseo_road_segments_v7.csv")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--output-nodes-name", default="sinho_road_nodes_v8.csv")
    parser.add_argument("--output-segments-name", default="sinho_road_segments_v8.csv")
    parser.add_argument("--bbox", type=float, nargs=4, default=SINHO_BBOX)
    parser.add_argument("--split-distance-meter", type=float, default=1.0)
    parser.add_argument("--endpoint-exclusion-meter", type=float, default=1.0)
    parser.add_argument("--endpoint-merge-meter", type=float, default=1.0)
    parser.add_argument("--cluster-projection-meter", type=float, default=1.0)
    parser.add_argument("--max-endpoint-shift-floor-meter", type=float, default=2.0)
    parser.add_argument("--max-endpoint-shift-ratio", type=float, default=0.2)
    parser.add_argument("--remove-short-edge-meter", type=float, default=0.3)
    parser.add_argument("--review-short-edge-meter", type=float, default=1.0)
    args = parser.parse_args()
    report = repair(args)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
