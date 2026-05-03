#!/usr/bin/env python3
"""Bridge remaining small components to the largest pedestrian network."""

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
from shapely.ops import nearest_points, substring

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from validate_csv_graph import UnionFind, parse_linestring, parse_point


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_SEGMENTS = ROOT_DIR / "runtime" / "graphhopper" / "topology" / "sinho_road_segments_v9.csv"
DEFAULT_NODES = ROOT_DIR / "runtime" / "graphhopper" / "topology" / "sinho_road_nodes_v9.csv"
DEFAULT_REPORT = ROOT_DIR / "runtime" / "graphhopper" / "topology" / "sinho_v9_bridge_report.json"

SEGMENT_DEFAULTS = {
    "walkAccess": "YES",
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


def lonlat_from_xy_line(line: LineString, transformer: Transformer) -> list[tuple[float, float]]:
    return [(transformer.transform(x, y)) for x, y in line.coords]


def load_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="", encoding="utf-8-sig") as fp:
        reader = csv.DictReader(fp)
        return list(reader), list(reader.fieldnames or [])


def build_graph(
    segment_rows: list[dict[str, str]],
    node_rows: list[dict[str, str]],
    to_5179: Transformer,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, str], Counter[str]]:
    nodes: dict[str, dict[str, Any]] = {}
    for row in node_rows:
        node_id = (row.get("vertexId") or "").strip()
        lonlat = parse_point(row.get("point", ""))
        xy = to_5179.transform(*lonlat)
        nodes[node_id] = {
            "row": row,
            "lonlat": lonlat,
            "xy": xy,
        }

    uf = UnionFind()
    degree: Counter[str] = Counter()
    segments: list[dict[str, Any]] = []
    for row in segment_rows:
        from_id = (row.get("fromNodeId") or "").strip()
        to_id = (row.get("toNodeId") or "").strip()
        if from_id not in nodes or to_id not in nodes or from_id == to_id:
            continue
        lonlat_coords = parse_linestring(row.get("geom", ""))
        xy_coords = [to_5179.transform(*coord) for coord in lonlat_coords]
        line = LineString(xy_coords)
        if line.length <= 0.01:
            continue
        uf.union(from_id, to_id)
        degree[from_id] += 1
        degree[to_id] += 1
        segments.append(
            {
                "row": row,
                "edgeId": row.get("edgeId", ""),
                "fromNodeId": from_id,
                "toNodeId": to_id,
                "coords": lonlat_coords,
                "xyCoords": xy_coords,
                "line": line,
            }
        )

    edge_by_component: dict[str, list[dict[str, Any]]] = defaultdict(list)
    node_by_component: dict[str, set[str]] = defaultdict(set)
    node_component: dict[str, str] = {}
    for segment in segments:
        component_id = uf.find(segment["fromNodeId"])
        segment["componentId"] = component_id
        edge_by_component[component_id].append(segment)
        for node_id in (segment["fromNodeId"], segment["toNodeId"]):
            node_by_component[component_id].add(node_id)
            node_component[node_id] = component_id

    components: list[dict[str, Any]] = []
    for component_id, component_segments in edge_by_component.items():
        node_ids = node_by_component[component_id]
        endpoints = [node_id for node_id in node_ids if degree[node_id] == 1]
        components.append(
            {
                "componentId": component_id,
                "edgeCount": len(component_segments),
                "nodeCount": len(node_ids),
                "endpointCount": len(endpoints),
                "endpointNodeIds": sorted(endpoints, key=numeric_id),
                "segments": component_segments,
            }
        )
    components.sort(key=lambda item: (item["edgeCount"], item["nodeCount"]), reverse=True)
    return nodes, segments, components, node_component, degree


def line_distance_candidate(
    *,
    candidate_id: str,
    mode: str,
    from_component_id: str,
    from_edge: dict[str, Any] | None,
    from_node_id: str | None,
    from_point: Point,
    to_edge: dict[str, Any],
    to_point: Point,
    from_5179: Transformer,
    distance_meter: float,
    auto_bridge_max_meter: float,
    review_bridge_max_meter: float,
) -> dict[str, Any]:
    from_lonlat = from_5179.transform(from_point.x, from_point.y)
    to_lonlat = from_5179.transform(to_point.x, to_point.y)
    return {
        "candidateId": candidate_id,
        "type": "PROPOSED_BRIDGE",
        "color": "blue",
        "priority": "AUTO"
        if distance_meter <= auto_bridge_max_meter
        else "REVIEW"
        if distance_meter <= review_bridge_max_meter
        else "HELD",
        "mode": mode,
        "fromComponentId": from_component_id,
        "toComponentId": to_edge["componentId"],
        "fromNodeId": from_node_id or "",
        "fromEdgeId": from_edge["edgeId"] if from_edge else "",
        "toEdgeId": to_edge["edgeId"],
        "distanceMeter": round(distance_meter, 3),
        "fromPoint": [from_lonlat[0], from_lonlat[1]],
        "toPoint": [to_lonlat[0], to_lonlat[1]],
        "geometry": [[from_lonlat[0], from_lonlat[1]], [to_lonlat[0], to_lonlat[1]]],
        "reason": "남은 component를 main network에 붙이기 위한 component-to-main 최단거리 bridge 후보입니다.",
        "review": {"status": "pending"},
    }


def nearest_main_for_endpoint(
    *,
    endpoint_id: str,
    component_id: str,
    nodes: dict[str, dict[str, Any]],
    main_segments: list[dict[str, Any]],
    from_5179: Transformer,
    index: int,
    auto_bridge_max_meter: float,
    review_bridge_max_meter: float,
) -> dict[str, Any]:
    point = Point(nodes[endpoint_id]["xy"])
    best: tuple[float, dict[str, Any], Point] | None = None
    for segment in main_segments:
        to_point = nearest_points(point, segment["line"])[1]
        gap = point.distance(to_point)
        if best is None or gap < best[0]:
            best = (gap, segment, to_point)
    if best is None:
        raise RuntimeError("no main segment available")
    gap, to_edge, to_point = best
    return line_distance_candidate(
        candidate_id=f"bridge-{index:05d}",
        mode="ENDPOINT_TO_MAIN_SEGMENT",
        from_component_id=component_id,
        from_edge=None,
        from_node_id=endpoint_id,
        from_point=point,
        to_edge=to_edge,
        to_point=to_point,
        from_5179=from_5179,
        distance_meter=gap,
        auto_bridge_max_meter=auto_bridge_max_meter,
        review_bridge_max_meter=review_bridge_max_meter,
    )


def nearest_main_for_closed_component(
    *,
    component: dict[str, Any],
    main_segments: list[dict[str, Any]],
    from_5179: Transformer,
    index: int,
    auto_bridge_max_meter: float,
    review_bridge_max_meter: float,
) -> dict[str, Any]:
    best: tuple[float, dict[str, Any], dict[str, Any], Point, Point] | None = None
    for from_edge in component["segments"]:
        for to_edge in main_segments:
            from_point, to_point = nearest_points(from_edge["line"], to_edge["line"])
            gap = from_point.distance(to_point)
            if best is None or gap < best[0]:
                best = (gap, from_edge, to_edge, from_point, to_point)
    if best is None:
        raise RuntimeError("no segment pair available")
    gap, from_edge, to_edge, from_point, to_point = best
    return line_distance_candidate(
        candidate_id=f"bridge-{index:05d}",
        mode="SEGMENT_TO_MAIN_SEGMENT",
        from_component_id=component["componentId"],
        from_edge=from_edge,
        from_node_id=None,
        from_point=from_point,
        to_edge=to_edge,
        to_point=to_point,
        from_5179=from_5179,
        distance_meter=gap,
        auto_bridge_max_meter=auto_bridge_max_meter,
        review_bridge_max_meter=review_bridge_max_meter,
    )


def generate_bridge_candidates(
    *,
    components: list[dict[str, Any]],
    nodes: dict[str, dict[str, Any]],
    from_5179: Transformer,
    auto_bridge_max_meter: float,
    review_bridge_max_meter: float,
) -> tuple[str, list[dict[str, Any]]]:
    if not components:
        return "", []
    main_component_id = components[0]["componentId"]
    main_segments = components[0]["segments"]
    main_tree = STRtree([segment["line"] for segment in main_segments])

    def nearest_main_segment(geometry: Any) -> dict[str, Any]:
        return main_segments[int(main_tree.nearest(geometry))]

    candidates: list[dict[str, Any]] = []
    index = 1
    for component in components[1:]:
        endpoint_candidates: list[dict[str, Any]] = []
        for endpoint_id in component["endpointNodeIds"]:
            point = Point(nodes[endpoint_id]["xy"])
            to_edge = nearest_main_segment(point)
            to_point = nearest_points(point, to_edge["line"])[1]
            endpoint_candidates.append(
                line_distance_candidate(
                    candidate_id=f"bridge-{index:05d}",
                    mode="ENDPOINT_TO_MAIN_SEGMENT",
                    from_component_id=component["componentId"],
                    from_edge=None,
                    from_node_id=endpoint_id,
                    from_point=point,
                    to_edge=to_edge,
                    to_point=to_point,
                    from_5179=from_5179,
                    distance_meter=point.distance(to_point),
                    auto_bridge_max_meter=auto_bridge_max_meter,
                    review_bridge_max_meter=review_bridge_max_meter,
                )
            )
            index += 1
        if endpoint_candidates:
            candidates.append(min(endpoint_candidates, key=lambda item: item["distanceMeter"]))
            continue
        closed_candidates: list[dict[str, Any]] = []
        for from_edge in component["segments"]:
            to_edge = nearest_main_segment(from_edge["line"])
            from_point, to_point = nearest_points(from_edge["line"], to_edge["line"])
            closed_candidates.append(
                line_distance_candidate(
                    candidate_id=f"bridge-{index:05d}",
                    mode="SEGMENT_TO_MAIN_SEGMENT",
                    from_component_id=component["componentId"],
                    from_edge=from_edge,
                    from_node_id=None,
                    from_point=from_point,
                    to_edge=to_edge,
                    to_point=to_point,
                    from_5179=from_5179,
                    distance_meter=from_point.distance(to_point),
                    auto_bridge_max_meter=auto_bridge_max_meter,
                    review_bridge_max_meter=review_bridge_max_meter,
                )
            )
            index += 1
        candidates.append(min(closed_candidates, key=lambda item: item["distanceMeter"]))
    candidates.sort(key=lambda item: (item["distanceMeter"], item["fromComponentId"]))
    for index, candidate in enumerate(candidates, start=1):
        candidate["candidateId"] = f"bridge-{index:05d}"
    return main_component_id, candidates


def make_node(
    *,
    node_id: str,
    coord: tuple[float, float],
    node_fields: list[str],
    source_key: str,
) -> dict[str, str]:
    row = {field: "" for field in node_fields}
    row["vertexId"] = node_id
    row["sourceNodeKey"] = source_key
    row["point"] = point_wkt(coord)
    return row


def new_connector_row(
    *,
    edge_id: str,
    from_id: str,
    to_id: str,
    from_coord: tuple[float, float],
    to_coord: tuple[float, float],
    segment_fields: list[str],
    to_5179: Transformer,
    source: str,
) -> dict[str, str]:
    row = {field: "" for field in segment_fields}
    row.update(SEGMENT_DEFAULTS)
    row["edgeId"] = edge_id
    row["fromNodeId"] = from_id
    row["toNodeId"] = to_id
    row["geom"] = line_wkt([from_coord, to_coord])
    row["lengthMeter"] = f"{LineString([to_5179.transform(*from_coord), to_5179.transform(*to_coord)]).length:.2f}"
    if "source" in row:
        row["source"] = source
    return row


def append_recalculated(
    *,
    row: dict[str, str],
    output: list[dict[str, str]],
    node_lonlat: dict[str, tuple[float, float]],
    to_5179: Transformer,
    remove_short_edge_meter: float,
    removed: dict[str, list[dict[str, Any]]],
) -> None:
    from_id = row.get("fromNodeId", "")
    to_id = row.get("toNodeId", "")
    if from_id == to_id:
        removed["selfLoops"].append({"edgeId": row.get("edgeId", ""), "nodeId": from_id})
        return
    if from_id not in node_lonlat or to_id not in node_lonlat:
        removed["missingRefs"].append({"edgeId": row.get("edgeId", ""), "fromNodeId": from_id, "toNodeId": to_id})
        return
    coords = parse_linestring(row["geom"])
    coords[0] = node_lonlat[from_id]
    coords[-1] = node_lonlat[to_id]
    length = LineString([to_5179.transform(*coord) for coord in coords]).length
    if length < remove_short_edge_meter:
        removed["shortEdges"].append({"edgeId": row.get("edgeId", ""), "lengthMeter": round(length, 3)})
        return
    new_row = row.copy()
    new_row["geom"] = line_wkt(coords)
    new_row["lengthMeter"] = f"{length:.2f}"
    output.append(new_row)


def apply_auto_bridges(args: argparse.Namespace, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    to_5179 = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    from_5179 = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)
    node_rows, node_fields = load_rows(args.nodes)
    segment_rows, segment_fields = load_rows(args.segments)

    auto_candidates = [item for item in candidates if item["priority"] == "AUTO"]
    node_by_id = {row["vertexId"]: row for row in node_rows}
    node_lonlat = {node_id: tuple(parse_point(row["point"])) for node_id, row in node_by_id.items()}
    segment_by_edge = {row["edgeId"]: row for row in segment_rows}
    max_node_id = max((numeric_id(row.get("vertexId")) for row in node_rows), default=0)
    max_edge_id = max((numeric_id(row.get("edgeId")) for row in segment_rows), default=0)
    next_node_id = max_node_id + 1
    next_edge_id = max_edge_id + 1

    split_points_by_edge: dict[str, list[dict[str, Any]]] = defaultdict(list)
    connector_specs: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    generated_split_nodes: set[str] = set()

    def ensure_split_node(edge_id: str, point_lonlat: list[float], candidate_id: str, role: str) -> str | None:
        nonlocal next_node_id
        if edge_id not in segment_by_edge:
            skipped.append({"candidateId": candidate_id, "reason": f"{role} edge missing", "edgeId": edge_id})
            return None
        node_id = str(next_node_id)
        next_node_id += 1
        node_row = make_node(
            node_id=node_id,
            coord=(point_lonlat[0], point_lonlat[1]),
            node_fields=node_fields,
            source_key=f"bridge:split:{edge_id}:{candidate_id}:{role}",
        )
        node_by_id[node_id] = node_row
        node_lonlat[node_id] = (point_lonlat[0], point_lonlat[1])
        generated_split_nodes.add(node_id)
        split_points_by_edge[edge_id].append({"nodeId": node_id, "point": point_lonlat, "candidateId": candidate_id})
        return node_id

    for candidate in auto_candidates:
        candidate_id = candidate["candidateId"]
        if candidate["mode"] == "ENDPOINT_TO_MAIN_SEGMENT":
            from_id = str(candidate.get("fromNodeId") or "")
            if from_id not in node_lonlat:
                skipped.append({"candidateId": candidate_id, "reason": "from endpoint missing"})
                continue
            to_id = ensure_split_node(str(candidate.get("toEdgeId") or ""), candidate["toPoint"], candidate_id, "to")
            if not to_id:
                continue
            connector_specs.append(
                {
                    "candidateId": candidate_id,
                    "fromNodeId": from_id,
                    "toNodeId": to_id,
                }
            )
            continue

        from_id = ensure_split_node(str(candidate.get("fromEdgeId") or ""), candidate["fromPoint"], candidate_id, "from")
        to_id = ensure_split_node(str(candidate.get("toEdgeId") or ""), candidate["toPoint"], candidate_id, "to")
        if not from_id or not to_id:
            continue
        connector_specs.append({"candidateId": candidate_id, "fromNodeId": from_id, "toNodeId": to_id})

    split_nodes_by_edge: dict[str, list[dict[str, Any]]] = defaultdict(list)
    valid_split_nodes: set[str] = set()
    split_node_alias: dict[str, str] = {}
    for edge_id, split_points in split_points_by_edge.items():
        source_row = segment_by_edge[edge_id]
        source_line = LineString([to_5179.transform(*coord) for coord in parse_linestring(source_row["geom"])])
        prepared: list[dict[str, Any]] = []
        for split in split_points:
            point_xy = to_5179.transform(*split["point"])
            projection = source_line.project(Point(point_xy))
            if projection <= args.endpoint_exclusion_meter:
                split_node_alias[split["nodeId"]] = source_row["fromNodeId"]
                skipped.append(
                    {
                        "candidateId": split["candidateId"],
                        "reason": "bridge split point snapped to existing from endpoint",
                        "nodeId": source_row["fromNodeId"],
                    }
                )
                continue
            if projection >= source_line.length - args.endpoint_exclusion_meter:
                split_node_alias[split["nodeId"]] = source_row["toNodeId"]
                skipped.append(
                    {
                        "candidateId": split["candidateId"],
                        "reason": "bridge split point snapped to existing to endpoint",
                        "nodeId": source_row["toNodeId"],
                    }
                )
                continue
            prepared.append({"nodeId": split["nodeId"], "projectionMeter": projection})
        prepared.sort(key=lambda item: item["projectionMeter"])
        clusters: list[list[dict[str, Any]]] = []
        for item in prepared:
            if not clusters or item["projectionMeter"] - clusters[-1][-1]["projectionMeter"] > args.split_cluster_meter:
                clusters.append([item])
            else:
                clusters[-1].append(item)
        for cluster in clusters:
            canonical = cluster[0]["nodeId"]
            projection = sum(item["projectionMeter"] for item in cluster) / len(cluster)
            point = source_line.interpolate(projection)
            lonlat = from_5179.transform(point.x, point.y)
            node_lonlat[canonical] = lonlat
            node_by_id[canonical]["point"] = point_wkt(lonlat)
            valid_split_nodes.add(canonical)
            split_nodes_by_edge[edge_id].append({"nodeId": canonical, "projectionMeter": projection})
            for duplicate in cluster[1:]:
                for spec in connector_specs:
                    if spec["fromNodeId"] == duplicate["nodeId"]:
                        spec["fromNodeId"] = canonical
                    if spec["toNodeId"] == duplicate["nodeId"]:
                        spec["toNodeId"] = canonical
                node_by_id.pop(duplicate["nodeId"], None)
                node_lonlat.pop(duplicate["nodeId"], None)

    for spec in connector_specs:
        if spec["fromNodeId"] in split_node_alias:
            spec["fromNodeId"] = split_node_alias[spec["fromNodeId"]]
        if spec["toNodeId"] in split_node_alias:
            spec["toNodeId"] = split_node_alias[spec["toNodeId"]]

    filtered_connector_specs: list[dict[str, Any]] = []
    for spec in connector_specs:
        generated_nodes = [
            node_id
            for node_id in (spec["fromNodeId"], spec["toNodeId"])
            if node_id in generated_split_nodes
        ]
        if any(node_id not in valid_split_nodes for node_id in generated_nodes):
            skipped.append(
                {
                    "candidateId": spec["candidateId"],
                    "reason": "connector skipped because required split node was rejected",
                }
            )
            continue
        filtered_connector_specs.append(spec)
    connector_specs = filtered_connector_specs

    for node_id in sorted(generated_split_nodes - valid_split_nodes - set(split_node_alias), key=numeric_id):
        node_by_id.pop(node_id, None)
        node_lonlat.pop(node_id, None)
    for node_id in split_node_alias:
        node_by_id.pop(node_id, None)
        node_lonlat.pop(node_id, None)

    output_segments: list[dict[str, str]] = []
    removed: dict[str, list[dict[str, Any]]] = defaultdict(list)
    removed_original_edges: list[str] = []

    for row in segment_rows:
        edge_id = row["edgeId"]
        if edge_id not in split_nodes_by_edge:
            append_recalculated(
                row=row,
                output=output_segments,
                node_lonlat=node_lonlat,
                to_5179=to_5179,
                remove_short_edge_meter=args.remove_short_edge_meter,
                removed=removed,
            )
            continue

        source_line = LineString([to_5179.transform(*coord) for coord in parse_linestring(row["geom"])])
        split_nodes = sorted(split_nodes_by_edge[edge_id], key=lambda item: item["projectionMeter"])
        distances = [0.0] + [item["projectionMeter"] for item in split_nodes] + [source_line.length]
        node_ids = [row["fromNodeId"]] + [item["nodeId"] for item in split_nodes] + [row["toNodeId"]]
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
            append_recalculated(
                row=new_row,
                output=output_segments,
                node_lonlat=node_lonlat,
                to_5179=to_5179,
                remove_short_edge_meter=args.remove_short_edge_meter,
                removed=removed,
            )
        removed_original_edges.append(edge_id)

    added_connectors: list[dict[str, Any]] = []
    for spec in connector_specs:
        from_id = spec["fromNodeId"]
        to_id = spec["toNodeId"]
        if from_id == to_id:
            skipped.append({"candidateId": spec["candidateId"], "reason": "connector resolves to same node"})
            continue
        if from_id not in node_lonlat or to_id not in node_lonlat:
            skipped.append({"candidateId": spec["candidateId"], "reason": "connector node missing"})
            continue
        connector = new_connector_row(
            edge_id=str(next_edge_id),
            from_id=from_id,
            to_id=to_id,
            from_coord=node_lonlat[from_id],
            to_coord=node_lonlat[to_id],
            segment_fields=segment_fields,
            to_5179=to_5179,
            source=spec["candidateId"],
        )
        next_edge_id += 1
        added_connectors.append({"candidateId": spec["candidateId"], "edgeId": connector["edgeId"]})
        append_recalculated(
            row=connector,
            output=output_segments,
            node_lonlat=node_lonlat,
            to_5179=to_5179,
            remove_short_edge_meter=args.remove_short_edge_meter,
            removed=removed,
        )

    deduped_segments: list[dict[str, str]] = []
    seen: dict[tuple[str, str, str], str] = {}
    for row in output_segments:
        left = row["fromNodeId"]
        right = row["toNodeId"]
        if left > right:
            left, right = right, left
        key = (left, right, row.get("segmentType", ""))
        if key in seen:
            removed["duplicates"].append({"edgeId": row["edgeId"], "keptEdgeId": seen[key]})
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

    return {
        "autoCandidates": auto_candidates,
        "addedConnectors": added_connectors,
        "newSplitNodes": sum(len(items) for items in split_nodes_by_edge.values()),
        "removedOriginalSplitEdges": removed_original_edges,
        "removed": dict(removed),
        "skipped": skipped,
        "outputSegments": len(deduped_segments),
        "outputNodes": len(output_nodes),
    }


def bridge(args: argparse.Namespace) -> dict[str, Any]:
    to_5179 = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    from_5179 = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)
    node_rows, _node_fields = load_rows(args.nodes)
    segment_rows, _segment_fields = load_rows(args.segments)
    nodes, _segments, components, _node_component, _degree = build_graph(segment_rows, node_rows, to_5179)
    main_component_id, candidates = generate_bridge_candidates(
        components=components,
        nodes=nodes,
        from_5179=from_5179,
        auto_bridge_max_meter=args.auto_bridge_max_meter,
        review_bridge_max_meter=args.review_bridge_max_meter,
    )
    auto_candidates = [item for item in candidates if item["priority"] == "AUTO"]
    review_candidates = [item for item in candidates if item["priority"] == "REVIEW"]
    held_candidates = [item for item in candidates if item["priority"] == "HELD"]

    apply_result: dict[str, Any] = {
        "autoCandidates": [],
        "addedConnectors": [],
        "newSplitNodes": 0,
        "removedOriginalSplitEdges": [],
        "removed": {},
        "skipped": [],
        "outputSegments": len(segment_rows),
        "outputNodes": len(node_rows),
    }
    if args.apply_auto and auto_candidates:
        apply_result = apply_auto_bridges(args, candidates)
    elif args.output_segments != args.segments or args.output_nodes != args.nodes:
        args.output_segments.parent.mkdir(parents=True, exist_ok=True)
        args.output_nodes.parent.mkdir(parents=True, exist_ok=True)
        args.output_segments.write_text(args.segments.read_text(encoding="utf-8-sig"), encoding="utf-8")
        args.output_nodes.write_text(args.nodes.read_text(encoding="utf-8-sig"), encoding="utf-8")

    report = {
        "inputs": {"segments": str(args.segments), "nodes": str(args.nodes)},
        "outputs": {"segments": str(args.output_segments), "nodes": str(args.output_nodes)},
        "parameters": {
            "autoBridgeMaxMeter": args.auto_bridge_max_meter,
            "reviewBridgeMaxMeter": args.review_bridge_max_meter,
            "splitClusterMeter": args.split_cluster_meter,
            "endpointExclusionMeter": args.endpoint_exclusion_meter,
        },
        "summary": {
            "componentsBefore": len(components),
            "mainComponentId": main_component_id,
            "mainComponentEdges": components[0]["edgeCount"] if components else 0,
            "remainingComponentsBefore": max(len(components) - 1, 0),
            "bridgeCandidates": len(candidates),
            "autoBridgeCandidates": len(auto_candidates),
            "reviewBridgeCandidates": len(review_candidates),
            "heldBridgeCandidates": len(held_candidates),
            "appliedAutoBridges": len(apply_result["addedConnectors"]) if args.apply_auto else 0,
            "newSplitNodes": apply_result["newSplitNodes"],
            "outputSegments": apply_result["outputSegments"],
            "outputNodes": apply_result["outputNodes"],
            "skipped": len(apply_result["skipped"]),
        },
        "componentsBefore": [
            {
                "componentId": item["componentId"],
                "edgeCount": item["edgeCount"],
                "nodeCount": item["nodeCount"],
                "endpointCount": item["endpointCount"],
            }
            for item in components
        ],
        "autoBridgeCandidates": auto_candidates,
        "reviewBridgeCandidates": review_candidates,
        "heldBridgeCandidates": held_candidates,
        "apply": apply_result,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--segments", type=Path, default=DEFAULT_SEGMENTS)
    parser.add_argument("--nodes", type=Path, default=DEFAULT_NODES)
    parser.add_argument("--output-segments", type=Path, default=DEFAULT_SEGMENTS)
    parser.add_argument("--output-nodes", type=Path, default=DEFAULT_NODES)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--auto-bridge-max-meter", type=float, default=3.0)
    parser.add_argument("--review-bridge-max-meter", type=float, default=12.0)
    parser.add_argument("--split-cluster-meter", type=float, default=1.0)
    parser.add_argument("--endpoint-exclusion-meter", type=float, default=1.0)
    parser.add_argument("--remove-short-edge-meter", type=float, default=0.3)
    parser.add_argument("--apply-auto", action="store_true")
    args = parser.parse_args()
    report = bridge(args)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
