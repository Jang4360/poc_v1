#!/usr/bin/env python3
"""Analyze Gangseo graph connectivity and generate connector candidates."""

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
from shapely.geometry import LineString, Point
from shapely.ops import nearest_points

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from validate_csv_graph import UnionFind, parse_linestring, parse_point


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = ROOT_DIR / "runtime" / "graphhopper" / "connectivity" / "connectivity_analysis.json"


def bbox_lonlat(coords: list[tuple[float, float]]) -> list[float]:
    return [
        min(lon for lon, _ in coords),
        min(lat for _, lat in coords),
        max(lon for lon, _ in coords),
        max(lat for _, lat in coords),
    ]


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def unit_vector(vector: tuple[float, float]) -> tuple[float, float] | None:
    length = math.hypot(vector[0], vector[1])
    if length <= 0.001:
        return None
    return vector[0] / length, vector[1] / length


def dot(left: tuple[float, float], right: tuple[float, float]) -> float:
    return left[0] * right[0] + left[1] * right[1]


def candidate_color(kind: str, distance_meter: float) -> str:
    if kind == "SPLIT_AND_CONNECT":
        return "yellow"
    return "orange" if distance_meter <= 12.0 else "red"


def load_nodes(path: Path, transformer: Transformer) -> dict[str, dict[str, Any]]:
    nodes: dict[str, dict[str, Any]] = {}
    with path.open(newline="", encoding="utf-8-sig") as fp:
        for row in csv.DictReader(fp):
            node_id = (row.get("vertexId") or "").strip()
            lonlat = parse_point(row.get("point", ""))
            xy = transformer.transform(lonlat[0], lonlat[1])
            nodes[node_id] = {
                "nodeId": node_id,
                "lon": lonlat[0],
                "lat": lonlat[1],
                "x": xy[0],
                "y": xy[1],
            }
    return nodes


def load_segments(path: Path, nodes: dict[str, dict[str, Any]], transformer: Transformer) -> tuple[list[dict[str, Any]], UnionFind, Counter[str]]:
    uf = UnionFind()
    degree: Counter[str] = Counter()
    segments: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8-sig") as fp:
        for row in csv.DictReader(fp):
            from_id = (row.get("fromNodeId") or "").strip()
            to_id = (row.get("toNodeId") or "").strip()
            if from_id not in nodes or to_id not in nodes or from_id == to_id:
                continue
            lonlat_coords = parse_linestring(row.get("geom", ""))
            xy_coords = [transformer.transform(lon, lat) for lon, lat in lonlat_coords]
            line = LineString(xy_coords)
            if line.length <= 0.01:
                continue
            uf.union(from_id, to_id)
            degree[from_id] += 1
            degree[to_id] += 1
            segments.append(
                {
                    "edgeId": (row.get("edgeId") or "").strip(),
                    "fromNodeId": from_id,
                    "toNodeId": to_id,
                    "segmentType": (row.get("segmentType") or "").strip(),
                    "coords": lonlat_coords,
                    "xyCoords": xy_coords,
                    "line": line,
                    "lengthMeter": round(line.length, 3),
                }
            )
    return segments, uf, degree


def build_components(
    *,
    nodes: dict[str, dict[str, Any]],
    segments: list[dict[str, Any]],
    uf: UnionFind,
    degree: Counter[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    component_nodes: dict[str, set[str]] = defaultdict(set)
    component_edges: dict[str, list[dict[str, Any]]] = defaultdict(list)
    node_component: dict[str, str] = {}
    for segment in segments:
        root = uf.find(segment["fromNodeId"])
        component_edges[root].append(segment)
        for node_id in (segment["fromNodeId"], segment["toNodeId"]):
            component_nodes[root].add(node_id)
            node_component[node_id] = root

    endpoints: list[dict[str, Any]] = []
    components: list[dict[str, Any]] = []
    for component_id, node_ids in component_nodes.items():
        edge_items = component_edges[component_id]
        component_endpoints = [node_id for node_id in node_ids if degree[node_id] == 1]
        all_coords = [coord for edge in edge_items for coord in edge["coords"]]
        for node_id in component_endpoints:
            node = nodes[node_id]
            endpoints.append(
                {
                    "nodeId": node_id,
                    "componentId": component_id,
                    "degree": degree[node_id],
                    "lon": node["lon"],
                    "lat": node["lat"],
                    "x": node["x"],
                    "y": node["y"],
                }
            )
        components.append(
            {
                "componentId": component_id,
                "nodeCount": len(node_ids),
                "edgeCount": len(edge_items),
                "endpointCount": len(component_endpoints),
                "bbox": bbox_lonlat(all_coords),
            }
        )
    components.sort(key=lambda item: (item["edgeCount"], item["nodeCount"]), reverse=True)
    endpoints.sort(key=lambda item: (item["componentId"], item["nodeId"]))
    return components, endpoints, node_component


def endpoint_tangents(segments: list[dict[str, Any]]) -> dict[str, tuple[float, float]]:
    tangents: dict[str, tuple[float, float]] = {}
    for segment in segments:
        coords = segment["xyCoords"]
        if len(coords) < 2:
            continue
        from_unit = unit_vector((coords[1][0] - coords[0][0], coords[1][1] - coords[0][1]))
        to_unit = unit_vector((coords[-2][0] - coords[-1][0], coords[-2][1] - coords[-1][1]))
        if from_unit:
            tangents[segment["fromNodeId"]] = from_unit
        if to_unit:
            tangents[segment["toNodeId"]] = to_unit
    return tangents


def connector_direction_ok(
    endpoint: dict[str, Any],
    other: dict[str, Any],
    tangents: dict[str, tuple[float, float]],
    *,
    min_outward_alignment: float,
    min_not_backward_alignment: float,
) -> bool:
    connector = unit_vector((other["x"] - endpoint["x"], other["y"] - endpoint["y"]))
    reverse_connector = unit_vector((endpoint["x"] - other["x"], endpoint["y"] - other["y"]))
    from_tangent = tangents.get(endpoint["nodeId"])
    to_tangent = tangents.get(other["nodeId"])
    if not connector or not reverse_connector or not from_tangent or not to_tangent:
        return False
    from_outward = (-from_tangent[0], -from_tangent[1])
    to_outward = (-to_tangent[0], -to_tangent[1])
    from_alignment = dot(connector, from_outward)
    to_alignment = dot(reverse_connector, to_outward)
    return (
        max(from_alignment, to_alignment) >= min_outward_alignment
        and min(from_alignment, to_alignment) >= min_not_backward_alignment
    )


def generate_near_node_merge_candidates(
    endpoints: list[dict[str, Any]],
    nodes: dict[str, dict[str, Any]],
    node_component: dict[str, str],
    *,
    max_node_merge_meter: float,
) -> tuple[list[dict[str, Any]], set[str]]:
    cell_size = max_node_merge_meter
    grid: dict[tuple[int, int], list[str]] = defaultdict(list)
    for node_id, node in nodes.items():
        if node_id not in node_component:
            continue
        grid[(int(node["x"] // cell_size), int(node["y"] // cell_size))].append(node_id)

    merge_candidates: list[dict[str, Any]] = []
    blocked_endpoint_ids: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    for endpoint in endpoints:
        cx = int(endpoint["x"] // cell_size)
        cy = int(endpoint["y"] // cell_size)
        nearest: tuple[float, str] | None = None
        for gx in range(cx - 1, cx + 2):
            for gy in range(cy - 1, cy + 2):
                for node_id in grid.get((gx, gy), []):
                    if node_id == endpoint["nodeId"]:
                        continue
                    if node_component.get(node_id) == endpoint["componentId"]:
                        continue
                    node = nodes[node_id]
                    gap = distance((endpoint["x"], endpoint["y"]), (node["x"], node["y"]))
                    if gap > max_node_merge_meter:
                        continue
                    if nearest is None or gap < nearest[0]:
                        nearest = (gap, node_id)
        if nearest is None:
            continue
        gap, target_node_id = nearest
        pair = tuple(sorted((endpoint["nodeId"], target_node_id)))
        if pair in seen_pairs:
            blocked_endpoint_ids.add(endpoint["nodeId"])
            continue
        seen_pairs.add(pair)
        target_node = nodes[target_node_id]
        merge_candidates.append(
            {
                "type": "NODE_MERGE",
                "color": "blue",
                "fromNodeId": endpoint["nodeId"],
                "toNodeId": target_node_id,
                "fromComponentId": endpoint["componentId"],
                "toComponentId": node_component.get(target_node_id, ""),
                "distanceMeter": round(gap, 3),
                "point": [target_node["lon"], target_node["lat"]],
                "geometry": [[endpoint["lon"], endpoint["lat"]], [target_node["lon"], target_node["lat"]]],
                "reason": "endpoint 주변 node가 merge 반경 안에 있어 endpoint connector보다 node merge가 우선입니다.",
            }
        )
        blocked_endpoint_ids.add(endpoint["nodeId"])
    merge_candidates.sort(key=lambda item: item["distanceMeter"])
    return merge_candidates, blocked_endpoint_ids


def generate_endpoint_candidates(
    endpoints: list[dict[str, Any]],
    tangents: dict[str, tuple[float, float]],
    *,
    max_radius_meter: float,
    min_connector_meter: float,
    endpoint_candidate_max_meter: float,
    direction_check_min_meter: float,
    direction_min_outward_alignment: float,
    direction_min_not_backward_alignment: float,
    max_per_component_pair: int,
    blocked_endpoint_ids: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    cell_size = max_radius_meter
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for index, endpoint in enumerate(endpoints):
        if endpoint["nodeId"] in blocked_endpoint_ids:
            continue
        grid[(int(endpoint["x"] // cell_size), int(endpoint["y"] // cell_size))].append(index)

    best_by_component_pair: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    merge_candidates: list[dict[str, Any]] = []
    low_priority_candidates: list[dict[str, Any]] = []
    seen_node_pairs: set[tuple[str, str]] = set()
    for index, endpoint in enumerate(endpoints):
        if endpoint["nodeId"] in blocked_endpoint_ids:
            continue
        cx = int(endpoint["x"] // cell_size)
        cy = int(endpoint["y"] // cell_size)
        for gx in range(cx - 1, cx + 2):
            for gy in range(cy - 1, cy + 2):
                for other_index in grid.get((gx, gy), []):
                    if other_index <= index:
                        continue
                    other = endpoints[other_index]
                    if endpoint["componentId"] == other["componentId"]:
                        continue
                    if other["nodeId"] in blocked_endpoint_ids:
                        continue
                    node_pair = tuple(sorted((endpoint["nodeId"], other["nodeId"])))
                    if node_pair in seen_node_pairs:
                        continue
                    seen_node_pairs.add(node_pair)
                    gap = distance((endpoint["x"], endpoint["y"]), (other["x"], other["y"]))
                    if gap > max_radius_meter:
                        continue
                    if gap <= min_connector_meter:
                        merge_candidates.append(
                            {
                                "type": "NODE_MERGE",
                                "fromNodeId": endpoint["nodeId"],
                                "toNodeId": other["nodeId"],
                                "fromComponentId": endpoint["componentId"],
                                "toComponentId": other["componentId"],
                                "distanceMeter": round(gap, 3),
                                "point": [endpoint["lon"], endpoint["lat"]],
                                "reason": "서로 다른 component endpoint가 거의 같은 좌표에 있어 connector line 대신 node merge 후보로 분류됨",
                            }
                        )
                        continue
                    component_pair = tuple(sorted((endpoint["componentId"], other["componentId"])))
                    candidate = {
                        "candidateId": "",
                        "type": "ENDPOINT_TO_ENDPOINT",
                        "color": candidate_color("ENDPOINT_TO_ENDPOINT", gap),
                        "fromNodeId": endpoint["nodeId"],
                        "toNodeId": other["nodeId"],
                        "fromComponentId": endpoint["componentId"],
                        "toComponentId": other["componentId"],
                        "distanceMeter": round(gap, 3),
                        "geometry": [[endpoint["lon"], endpoint["lat"]], [other["lon"], other["lat"]]],
                        "reason": "서로 다른 component의 endpoint가 탐색 반경 안에 있어 connector 후보로 생성됨",
                    }
                    if gap > endpoint_candidate_max_meter:
                        low_priority_candidates.append(
                            {
                                **candidate,
                                "priority": "LOW_PRIORITY",
                                "reason": (
                                    "endpoint 간 거리가 기본 검수 반경을 초과해 지도 기본 표시에서 제외됩니다."
                                ),
                            }
                        )
                        continue
                    if gap > direction_check_min_meter and not connector_direction_ok(
                        endpoint,
                        other,
                        tangents,
                        min_outward_alignment=direction_min_outward_alignment,
                        min_not_backward_alignment=direction_min_not_backward_alignment,
                    ):
                        low_priority_candidates.append(
                            {
                                **candidate,
                                "priority": "LOW_PRIORITY",
                                "reason": (
                                    "endpoint 방향성 검사에 실패해 지도 기본 표시에서 제외됩니다."
                                ),
                            }
                        )
                        continue
                    bucket = best_by_component_pair[component_pair]
                    bucket.append(candidate)
                    bucket.sort(key=lambda item: item["distanceMeter"])
                    del bucket[max_per_component_pair:]

    candidates = [item for bucket in best_by_component_pair.values() for item in bucket]
    candidates.sort(key=lambda item: item["distanceMeter"])
    merge_candidates.sort(key=lambda item: item["distanceMeter"])
    low_priority_candidates.sort(key=lambda item: item["distanceMeter"])
    return candidates, merge_candidates, low_priority_candidates


def generate_split_candidates(
    endpoints: list[dict[str, Any]],
    segments: list[dict[str, Any]],
    node_component: dict[str, str],
    inverse_transformer: Transformer,
    *,
    max_radius_meter: float,
    split_connector_max_meter: float,
    endpoint_exclusion_meter: float,
) -> tuple[list[dict[str, Any]], set[str]]:
    lines = [segment["line"] for segment in segments]
    tree = STRtree(lines)
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for endpoint in endpoints:
        point = Point(endpoint["x"], endpoint["y"])
        nearest: dict[str, Any] | None = None
        for raw_index in tree.query(point.buffer(max_radius_meter)):
            segment = segments[int(raw_index)]
            target_component = node_component.get(segment["fromNodeId"])
            if not target_component or target_component == endpoint["componentId"]:
                continue
            projected_gap = point.distance(segment["line"])
            if projected_gap > max_radius_meter or projected_gap > split_connector_max_meter:
                continue
            start_gap = distance((endpoint["x"], endpoint["y"]), segment["xyCoords"][0])
            end_gap = distance((endpoint["x"], endpoint["y"]), segment["xyCoords"][-1])
            if min(start_gap, end_gap) <= endpoint_exclusion_meter:
                continue
            split_point = nearest_points(point, segment["line"])[1]
            distance_from_segment_ends = min(
                split_point.distance(Point(segment["xyCoords"][0])),
                split_point.distance(Point(segment["xyCoords"][-1])),
            )
            if distance_from_segment_ends <= endpoint_exclusion_meter:
                continue
            if nearest is None or projected_gap < nearest["distanceMeter"]:
                split_lon, split_lat = inverse_transformer.transform(split_point.x, split_point.y)
                nearest = {
                    "candidateId": "",
                    "type": "SPLIT_AND_CONNECT",
                    "color": "yellow",
                    "fromNodeId": endpoint["nodeId"],
                    "toEdgeId": segment["edgeId"],
                    "fromComponentId": endpoint["componentId"],
                    "toComponentId": target_component,
                    "distanceMeter": round(projected_gap, 3),
                    "splitPoint": [split_lon, split_lat],
                    "geometry": [[endpoint["lon"], endpoint["lat"]], [split_lon, split_lat]],
                    "reason": (
                        "endpoint가 다른 component의 segment 중간에 더 가깝습니다. "
                        "GraphHopper는 node에서만 회전/연결할 수 있으므로 target segment를 split해 접점 node를 만들어야 합니다."
                    ),
                }
        if nearest:
            key = (nearest["fromNodeId"], nearest["toEdgeId"])
            if key not in seen:
                seen.add(key)
                candidates.append(nearest)

    candidates.sort(key=lambda item: item["distanceMeter"])
    return candidates, {candidate["fromNodeId"] for candidate in candidates}


def number_candidates(candidates: list[dict[str, Any]], *, prefix: str = "conn") -> list[dict[str, Any]]:
    for index, candidate in enumerate(candidates, start=1):
        candidate["candidateId"] = f"{prefix}-{index:05d}"
        candidate["review"] = {"status": "pending"}
    return candidates


def analyze(args: argparse.Namespace) -> dict[str, Any]:
    to_5179 = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    from_5179 = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)
    nodes = load_nodes(args.nodes, to_5179)
    segments, uf, degree = load_segments(args.segments, nodes, to_5179)
    components, endpoints, node_component = build_components(nodes=nodes, segments=segments, uf=uf, degree=degree)
    tangents = endpoint_tangents(segments)

    near_node_merge_candidates, node_merge_blocked_endpoint_ids = generate_near_node_merge_candidates(
        endpoints,
        nodes,
        node_component,
        max_node_merge_meter=args.node_merge_meter,
    )
    split_candidates, split_blocked_endpoint_ids = generate_split_candidates(
        endpoints,
        segments,
        node_component,
        from_5179,
        max_radius_meter=args.max_radius_meter,
        split_connector_max_meter=args.split_connector_max_meter,
        endpoint_exclusion_meter=args.endpoint_exclusion_meter,
    )
    blocked_endpoint_ids = node_merge_blocked_endpoint_ids | split_blocked_endpoint_ids
    endpoint_candidates, close_merge_candidates, low_priority_candidates = generate_endpoint_candidates(
        endpoints,
        tangents,
        max_radius_meter=args.max_radius_meter,
        min_connector_meter=args.min_connector_meter,
        endpoint_candidate_max_meter=args.endpoint_candidate_max_meter,
        direction_check_min_meter=args.direction_check_min_meter,
        direction_min_outward_alignment=args.direction_min_outward_alignment,
        direction_min_not_backward_alignment=args.direction_min_not_backward_alignment,
        max_per_component_pair=args.max_per_component_pair,
        blocked_endpoint_ids=blocked_endpoint_ids,
    )
    merge_candidates = number_candidates(near_node_merge_candidates + close_merge_candidates, prefix="merge")
    combined_candidates = endpoint_candidates + split_candidates
    combined_candidates.sort(key=lambda item: (item["distanceMeter"], item["type"]))
    candidates = number_candidates(combined_candidates)
    low_priority_candidates = number_candidates(low_priority_candidates, prefix="low")
    generated_candidate_count = len(candidates)
    if args.max_candidates and len(candidates) > args.max_candidates:
        candidates = candidates[: args.max_candidates]

    color_counts = Counter(candidate["color"] for candidate in candidates)
    type_counts = Counter(candidate["type"] for candidate in candidates)
    return {
        "meta": {
            "segments": str(args.segments),
            "nodes": str(args.nodes),
            "crs": "EPSG:5179",
            "maxRadiusMeter": args.max_radius_meter,
            "orangeThresholdMeter": 12.0,
            "redThresholdMeter": args.max_radius_meter,
            "endpointExclusionMeter": args.endpoint_exclusion_meter,
            "splitConnectorMaxMeter": args.split_connector_max_meter,
            "nodeMergeMeter": args.node_merge_meter,
            "minConnectorMeter": args.min_connector_meter,
            "endpointCandidateMaxMeter": args.endpoint_candidate_max_meter,
            "directionCheckMinMeter": args.direction_check_min_meter,
        },
        "summary": {
            "segmentCount": len(segments),
            "nodeCount": len(nodes),
            "componentCount": len(components),
            "endpointCount": len(endpoints),
            "candidateCount": len(candidates),
            "generatedCandidateCount": generated_candidate_count,
            "candidateOutputTruncated": generated_candidate_count > len(candidates),
            "nodeMergeCandidateCount": len(merge_candidates),
            "lowPriorityCandidateCount": len(low_priority_candidates),
            "blockedEndpointCount": len(blocked_endpoint_ids),
            "candidateTypeCounts": dict(type_counts),
            "candidateColorCounts": dict(color_counts),
            "largestComponents": components[:10],
        },
        "components": components,
        "endpoints": [
            {key: value for key, value in endpoint.items() if key not in {"x", "y"}}
            for endpoint in endpoints
        ],
        "segmentComponents": [
            {
                "edgeId": segment["edgeId"],
                "componentId": node_component.get(segment["fromNodeId"], ""),
                "segmentType": segment["segmentType"],
            }
            for segment in segments
        ],
        "candidates": candidates,
        "lowPriorityCandidates": low_priority_candidates,
        "nodeMergeCandidates": merge_candidates,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--segments", type=Path, default=ROOT_DIR / "etl" / "raw" / "gangseo_road_segments_v7.csv")
    parser.add_argument("--nodes", type=Path, default=ROOT_DIR / "etl" / "raw" / "gangseo_road_nodes_v7.csv")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-radius-meter", type=float, default=20.0)
    parser.add_argument("--min-connector-meter", type=float, default=0.75)
    parser.add_argument("--endpoint-exclusion-meter", type=float, default=1.0)
    parser.add_argument("--split-connector-max-meter", type=float, default=1.0)
    parser.add_argument("--node-merge-meter", type=float, default=2.0)
    parser.add_argument("--endpoint-candidate-max-meter", type=float, default=12.0)
    parser.add_argument("--direction-check-min-meter", type=float, default=3.0)
    parser.add_argument("--direction-min-outward-alignment", type=float, default=0.34)
    parser.add_argument("--direction-min-not-backward-alignment", type=float, default=-0.35)
    parser.add_argument("--max-per-component-pair", type=int, default=2)
    parser.add_argument("--max-candidates", type=int, default=25000)
    args = parser.parse_args()

    report = analyze(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
