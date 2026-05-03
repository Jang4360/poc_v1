#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from etl.common import segment_graph_db

DEFAULT_SOURCE_GEOJSON = segment_graph_db.ETL_DIR / "gangseo_road_boundary_v4.geojson"
DEFAULT_OUTPUT_NODE_CSV = segment_graph_db.ETL_DIR / "daejeo1_road_nodes_simplified_test.csv"
DEFAULT_OUTPUT_SEGMENT_CSV = segment_graph_db.ETL_DIR / "daejeo1_road_segments_simplified_test.csv"
DEFAULT_OUTPUT_HTML = segment_graph_db.ETL_DIR / "daejeo1_simplified_segment_02c_graph_edit.html"
DEFAULT_OUTPUT_GEOJSON = segment_graph_db.ETL_DIR / "daejeo1_simplified_segment_02c_graph_materialized.geojson"
DEFAULT_CRITERIA_DOC = segment_graph_db.ETL_DIR / "pedestrian_road_extraction_criteria_v3.md"


def coord_key(coord: list[float]) -> str:
    return f"{float(coord[0]):.8f}:{float(coord[1]):.8f}"


def dedupe_consecutive_coords(coords: list[list[float]]) -> list[list[float]]:
    output: list[list[float]] = []
    previous_key = ""
    for coord in coords:
        key = coord_key(coord)
        if key == previous_key:
            continue
        output.append([float(coord[0]), float(coord[1])])
        previous_key = key
    return output


def turn_angle_degrees(previous: list[float], current: list[float], following: list[float]) -> float:
    lat_scale = math.cos(math.radians(float(current[1])))
    ax = (float(current[0]) - float(previous[0])) * lat_scale
    ay = float(current[1]) - float(previous[1])
    bx = (float(following[0]) - float(current[0])) * lat_scale
    by = float(following[1]) - float(current[1])
    a_norm = math.hypot(ax, ay)
    b_norm = math.hypot(bx, by)
    if a_norm == 0 or b_norm == 0:
        return 0.0
    dot = max(-1.0, min(1.0, (ax * bx + ay * by) / (a_norm * b_norm)))
    return math.degrees(math.acos(dot))


def point_line_distance(point: list[float], start: list[float], end: list[float]) -> float:
    lat_scale = math.cos(math.radians(float(point[1])))
    px = float(point[0]) * lat_scale
    py = float(point[1])
    sx = float(start[0]) * lat_scale
    sy = float(start[1])
    ex = float(end[0]) * lat_scale
    ey = float(end[1])
    dx = ex - sx
    dy = ey - sy
    if dx == 0 and dy == 0:
        return math.hypot(px - sx, py - sy)
    t = max(0.0, min(1.0, ((px - sx) * dx + (py - sy) * dy) / (dx * dx + dy * dy)))
    closest_x = sx + t * dx
    closest_y = sy + t * dy
    return math.hypot(px - closest_x, py - closest_y)


def rdp_indexes(coords: list[list[float]], tolerance_degrees: float) -> list[int]:
    if len(coords) <= 2:
        return list(range(len(coords)))
    start = coords[0]
    end = coords[-1]
    max_distance = -1.0
    max_index = 0
    for index in range(1, len(coords) - 1):
        distance = point_line_distance(coords[index], start, end)
        if distance > max_distance:
            max_distance = distance
            max_index = index
    if max_distance <= tolerance_degrees:
        return [0, len(coords) - 1]
    left = rdp_indexes(coords[: max_index + 1], tolerance_degrees)
    right = rdp_indexes(coords[max_index:], tolerance_degrees)
    return left[:-1] + [index + max_index for index in right]


def simplify_line_coords(coords: list[list[float]], *, tolerance_degrees: float) -> list[list[float]]:
    clean_coords = dedupe_consecutive_coords(coords)
    if len(clean_coords) <= 2:
        return clean_coords
    indexes = rdp_indexes(clean_coords, tolerance_degrees=tolerance_degrees)
    return [clean_coords[index] for index in indexes]


def capped_shape_coords(coords: list[list[float]], *, max_points: int, tolerance_degrees: float) -> list[list[float]]:
    if len(coords) <= max_points:
        return coords
    indexes = rdp_indexes(coords, tolerance_degrees=tolerance_degrees)
    if len(indexes) > max_points:
        indexes = sorted(set(round(index * (len(coords) - 1) / (max_points - 1)) for index in range(max_points)))
    if indexes[0] != 0:
        indexes.insert(0, 0)
    if indexes[-1] != len(coords) - 1:
        indexes.append(len(coords) - 1)
    return [coords[index] for index in sorted(set(indexes))]


def normalize_piece_coords(coords: list[list[float]]) -> list[list[float]]:
    clean_coords = dedupe_consecutive_coords(coords)
    if len(clean_coords) >= 2:
        return clean_coords
    return []


def anchor_indexes(
    coords: list[list[float]],
    *,
    corner_angle_degrees: float,
    min_corner_leg_meter: float,
    max_corner_nodes_per_line: int,
) -> list[int]:
    if len(coords) <= 2:
        return [0, len(coords) - 1]
    candidates: list[tuple[float, int]] = []
    for index in range(1, len(coords) - 1):
        angle = turn_angle_degrees(coords[index - 1], coords[index], coords[index + 1])
        if angle < corner_angle_degrees:
            continue
        if segment_graph_db.point_distance_meter(coords[index - 1], coords[index]) < min_corner_leg_meter:
            continue
        if segment_graph_db.point_distance_meter(coords[index], coords[index + 1]) < min_corner_leg_meter:
            continue
        candidates.append((angle, index))
    if max_corner_nodes_per_line >= 0:
        candidates = sorted(candidates, reverse=True)[:max_corner_nodes_per_line]
    anchors = {0, len(coords) - 1, *(index for _angle, index in candidates)}
    return sorted(anchors)


def bbox_intersects(feature: dict[str, Any], bbox: tuple[float, float, float, float]) -> bool:
    feature_bbox = segment_graph_db.feature_bounds([feature])
    if feature_bbox is None:
        return False
    min_lon, min_lat, max_lon, max_lat = bbox
    f_min_lon, f_min_lat, f_max_lon, f_max_lat = feature_bbox
    return not (f_max_lon < min_lon or f_min_lon > max_lon or f_max_lat < min_lat or f_min_lat > max_lat)


class UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, value: int) -> int:
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def cluster_raw_nodes(raw_nodes: dict[str, dict[str, Any]], *, snap_meter: float) -> dict[str, dict[str, Any]]:
    keys = list(raw_nodes)
    if not keys:
        return {}
    union_find = UnionFind(len(keys))
    if snap_meter > 0:
        cell_degrees = max(snap_meter / 111_320.0, 0.000001)
        cells: dict[tuple[int, int], list[int]] = {}
        for index, key in enumerate(keys):
            coord = raw_nodes[key]["coord"]
            cell = (math.floor(float(coord[0]) / cell_degrees), math.floor(float(coord[1]) / cell_degrees))
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    for other_index in cells.get((cell[0] + dx, cell[1] + dy), []):
                        if segment_graph_db.point_distance_meter(coord, raw_nodes[keys[other_index]]["coord"]) <= snap_meter:
                            union_find.union(index, other_index)
            cells.setdefault(cell, []).append(index)

    indexes_by_root: dict[int, list[int]] = {}
    for index in range(len(keys)):
        indexes_by_root.setdefault(union_find.find(index), []).append(index)

    cluster_by_key: dict[str, dict[str, Any]] = {}
    for cluster_id, indexes in enumerate(indexes_by_root.values(), start=1):
        coords = [raw_nodes[keys[index]]["coord"] for index in indexes]
        centroid = [
            sum(float(coord[0]) for coord in coords) / len(coords),
            sum(float(coord[1]) for coord in coords) / len(coords),
        ]
        representative_index = min(
            indexes,
            key=lambda index: segment_graph_db.point_distance_meter(raw_nodes[keys[index]]["coord"], centroid),
        )
        representative_coord = raw_nodes[keys[representative_index]]["coord"]
        role_counts: Counter[str] = Counter()
        source_edge_ids: set[int] = set()
        for index in indexes:
            raw = raw_nodes[keys[index]]
            role_counts.update(raw["roles"])
            source_edge_ids.update(raw["sourceEdgeIds"])
        cluster = {
            "vertexId": cluster_id,
            "coord": [float(representative_coord[0]), float(representative_coord[1])],
            "size": len(indexes),
            "roles": dict(role_counts),
            "sourceEdgeIds": sorted(source_edge_ids),
        }
        for index in indexes:
            cluster_by_key[keys[index]] = cluster
    return cluster_by_key


def source_features_for_area(payload: dict[str, Any], area: dict[str, Any]) -> list[dict[str, Any]]:
    bbox = segment_graph_db.area_bbox_tuple(area)
    features = payload["layers"]["roadSegments"]["features"]
    return [feature for feature in features if segment_graph_db.feature_in_bbox(feature, bbox) or bbox_intersects(feature, bbox)]


def simplify_boundary_payload(
    payload: dict[str, Any],
    *,
    corner_angle_degrees: float,
    line_tolerance_degrees: float,
    max_shape_points: int,
    min_corner_leg_meter: float,
    max_corner_nodes_per_line: int,
    node_snap_meter: float,
) -> dict[str, Any]:
    raw_nodes: dict[str, dict[str, Any]] = {}
    segment_specs: list[dict[str, Any]] = []
    source_segments = payload["layers"]["roadSegments"]["features"]

    def register_raw_node(coord: list[float], role: str, source_edge_id: int) -> str:
        key = coord_key(coord)
        if key not in raw_nodes:
            raw_nodes[key] = {
                "coord": [float(coord[0]), float(coord[1])],
                "roles": Counter(),
                "sourceEdgeIds": set(),
            }
        raw_nodes[key]["roles"][role] += 1
        raw_nodes[key]["sourceEdgeIds"].add(source_edge_id)
        return key

    for source in source_segments:
        props = source["properties"]
        source_edge_id = int(props["edgeId"])
        segment_type = segment_graph_db.normalize_segment_type(props.get("segmentType"))
        raw_coords = source["geometry"]["coordinates"]
        coords = simplify_line_coords(raw_coords, tolerance_degrees=line_tolerance_degrees)
        if len(coords) < 2:
            continue
        anchors = anchor_indexes(
            coords,
            corner_angle_degrees=corner_angle_degrees,
            min_corner_leg_meter=min_corner_leg_meter,
            max_corner_nodes_per_line=max_corner_nodes_per_line,
        )
        for left_index, right_index in zip(anchors, anchors[1:]):
            piece_coords = capped_shape_coords(
                coords[left_index : right_index + 1],
                max_points=max_shape_points,
                tolerance_degrees=line_tolerance_degrees,
            )
            if len(piece_coords) < 2:
                continue
            from_role = "corner" if left_index not in {0, len(coords) - 1} else "endpoint"
            to_role = "corner" if right_index not in {0, len(coords) - 1} else "endpoint"
            segment_specs.append(
                {
                    "fromKey": register_raw_node(coords[left_index], from_role, source_edge_id),
                    "toKey": register_raw_node(coords[right_index], to_role, source_edge_id),
                    "segmentType": segment_type,
                    "sourceEdgeId": source_edge_id,
                    "coords": piece_coords,
                }
            )

    cluster_by_key = cluster_raw_nodes(raw_nodes, snap_meter=node_snap_meter)
    output_segments: list[dict[str, Any]] = []
    for spec in segment_specs:
        from_cluster = cluster_by_key[spec["fromKey"]]
        to_cluster = cluster_by_key[spec["toKey"]]
        if int(from_cluster["vertexId"]) == int(to_cluster["vertexId"]):
            continue
        original_coords = spec["coords"]
        piece_coords = normalize_piece_coords([from_cluster["coord"], *original_coords[1:-1], to_cluster["coord"]])
        length_meter = round(segment_graph_db.line_length_meter(piece_coords), 2)
        if length_meter <= 0:
            continue
        output_segments.append(
            {
                "type": "Feature",
                "properties": {
                    "edgeId": len(output_segments) + 1,
                    "fromNodeId": int(from_cluster["vertexId"]),
                    "toNodeId": int(to_cluster["vertexId"]),
                    "segmentType": spec["segmentType"],
                    "lengthMeter": length_meter,
                    "sourceEdgeIds": str(spec["sourceEdgeId"]),
                },
                "geometry": {"type": "LineString", "coordinates": piece_coords},
            }
        )

    degree: Counter[int] = Counter()
    for segment in output_segments:
        degree[int(segment["properties"]["fromNodeId"])] += 1
        degree[int(segment["properties"]["toNodeId"])] += 1
    used_node_ids = set(degree)
    output_nodes = []
    for cluster in sorted({id(cluster): cluster for cluster in cluster_by_key.values()}.values(), key=lambda item: int(item["vertexId"])):
        vertex_id = int(cluster["vertexId"])
        if vertex_id not in used_node_ids:
            continue
        output_nodes.append(
            {
                "type": "Feature",
                "properties": {
                    "vertexId": vertex_id,
                    "sourceNodeKey": f"daejeo1_v3_boundary_test:{coord_key(cluster['coord'])}",
                    "nodeType": "V3_BOUNDARY_SNAP_TEST",
                    "degree": degree[vertex_id],
                    "endpointCount": int(cluster["roles"].get("endpoint", 0)),
                    "projectedKey": "",
                    "simplifyRole": ",".join(sorted(cluster["roles"])),
                    "snapClusterSize": int(cluster["size"]),
                    "sourceEdgeIds": ",".join(str(edge_id) for edge_id in cluster["sourceEdgeIds"][:12]),
                },
                "geometry": {"type": "Point", "coordinates": cluster["coord"]},
            }
        )

    counts = Counter(segment["properties"]["segmentType"] for segment in output_segments)
    meta = dict(payload["meta"])
    meta.update(
        {
            "title": "강서구 대저1동 v2 road-boundary simplified test CSV-backed Graph Manual Edit UI",
            "districtGu": "강서구",
            "districtDong": "대저1동",
            "dongId": "daejeo1",
            "stage": "daejeo1-v3-boundary-snap-test-csv",
            "sourceGeojson": str(DEFAULT_SOURCE_GEOJSON),
            "criteriaDoc": str(DEFAULT_CRITERIA_DOC),
            "simplifyRule": (
                "v3 graph adapter from v2 road-boundary LineStrings; source lines are simplified independently; no graph-chain merging or "
                f"cross-feature connector inference; corner nodes kept at turns >= {corner_angle_degrees:g} degrees; "
                f"corner candidates require >= {min_corner_leg_meter:g}m legs and are capped to "
                f"{max_corner_nodes_per_line} per source line; "
                f"raw endpoint/corner nodes snap within {node_snap_meter:g}m; "
                f"curve shape coordinates capped to {max_shape_points} points per segment"
            ),
        }
    )
    return {
        "meta": meta,
        "summary": {
            "nodeCount": len(output_nodes),
            "segmentCount": len(output_segments),
            "segmentTypeCounts": [{"name": name, "count": count} for name, count in sorted(counts.items())],
            "transitionConnectorCount": 0,
            "gapBridgeCount": 0,
            "cornerBridgeCount": 0,
            "sameSideCornerBridgeCount": 0,
            "crossSideCornerBridgeCount": 0,
            "crossingCount": 0,
            "elevatorConnectorCount": 0,
            "sourceNodeCount": payload["summary"].get("nodeCount", 0),
            "sourceSegmentCount": payload["summary"]["segmentCount"],
            "sourceFeatureCount": len(source_segments),
            "rawNodeCandidateCount": len(raw_nodes),
            "snappedNodeCount": len(output_nodes),
            "nodeSnapMeter": node_snap_meter,
        },
        "layers": {
            "roadNodes": {"type": "FeatureCollection", "features": output_nodes},
            "roadSegments": {"type": "FeatureCollection", "features": output_segments},
        },
    }


def build_area_source_payload(source_geojson: Path, *, area: dict[str, Any]) -> dict[str, Any]:
    source_payload = segment_graph_db.load_json(source_geojson)
    source_features = source_features_for_area(source_payload, area)
    counts = Counter(segment_graph_db.normalize_segment_type(feature["properties"].get("segmentType")) for feature in source_features)
    meta = dict(source_payload.get("meta", {}))
    meta.update(
        {
            "title": "강서구 대저1동 v2 road-boundary source subset",
            "districtGu": "강서구",
            "districtDong": "대저1동",
            "dongId": "daejeo1",
            "sourceGeojson": str(source_geojson),
        }
    )
    return {
        "meta": meta,
        "summary": {
            "nodeCount": 0,
            "segmentCount": len(source_features),
            "segmentTypeCounts": [{"name": name, "count": count} for name, count in sorted(counts.items())],
        },
        "layers": {
            "roadNodes": {"type": "FeatureCollection", "features": []},
            "roadSegments": {"type": "FeatureCollection", "features": source_features},
        },
    }


def generate_outputs(
    *,
    source_geojson: Path,
    output_node_csv: Path,
    output_segment_csv: Path,
    output_html: Path,
    output_geojson: Path,
    corner_angle_degrees: float,
    line_tolerance_degrees: float,
    max_shape_points: int,
    min_corner_leg_meter: float,
    max_corner_nodes_per_line: int,
    node_snap_meter: float,
) -> dict[str, Any]:
    area = segment_graph_db.gangseo_dong_area("daejeo1")
    source_payload = build_area_source_payload(source_geojson, area=area)
    simplified_payload = simplify_boundary_payload(
        source_payload,
        corner_angle_degrees=corner_angle_degrees,
        line_tolerance_degrees=line_tolerance_degrees,
        max_shape_points=max_shape_points,
        min_corner_leg_meter=min_corner_leg_meter,
        max_corner_nodes_per_line=max_corner_nodes_per_line,
        node_snap_meter=node_snap_meter,
    )
    report = segment_graph_db.write_csv_outputs(
        simplified_payload,
        node_csv=output_node_csv,
        segment_csv=output_segment_csv,
    )
    preview_payload = segment_graph_db.write_csv_edit_outputs(
        node_csv=output_node_csv,
        segment_csv=output_segment_csv,
        output_html=output_html,
        output_geojson=output_geojson,
        dong_areas=[area],
        default_dong_id="daejeo1",
    )
    preview_payload["meta"].update(simplified_payload["meta"])
    output_geojson.write_text(json.dumps(preview_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "source": {
            "geojson": str(source_geojson),
            "nodeCount": source_payload["summary"]["nodeCount"],
            "segmentCount": source_payload["summary"]["segmentCount"],
        },
        "output": report,
        "preview": {
            "outputHtml": str(output_html),
            "outputGeojson": str(output_geojson),
            "localhostUrl": f"http://127.0.0.1:3000/etl/{output_html.name}",
            "nodeCount": preview_payload["summary"]["nodeCount"],
            "segmentCount": preview_payload["summary"]["segmentCount"],
        },
        "summary": simplified_payload["summary"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a Daejeo1 v2 road-boundary test CSV without touching Gangseo v5 source CSVs.")
    parser.add_argument("--source-geojson", type=Path, default=DEFAULT_SOURCE_GEOJSON)
    parser.add_argument("--output-node-csv", type=Path, default=DEFAULT_OUTPUT_NODE_CSV)
    parser.add_argument("--output-segment-csv", type=Path, default=DEFAULT_OUTPUT_SEGMENT_CSV)
    parser.add_argument("--output-html", type=Path, default=DEFAULT_OUTPUT_HTML)
    parser.add_argument("--output-geojson", type=Path, default=DEFAULT_OUTPUT_GEOJSON)
    parser.add_argument("--corner-angle-degrees", type=float, default=55.0)
    parser.add_argument("--line-tolerance-degrees", type=float, default=0.00002)
    parser.add_argument("--max-shape-points", type=int, default=5)
    parser.add_argument("--min-corner-leg-meter", type=float, default=15.0)
    parser.add_argument("--max-corner-nodes-per-line", type=int, default=1)
    parser.add_argument("--node-snap-meter", type=float, default=8.0)
    args = parser.parse_args()
    report = generate_outputs(
        source_geojson=args.source_geojson,
        output_node_csv=args.output_node_csv,
        output_segment_csv=args.output_segment_csv,
        output_html=args.output_html,
        output_geojson=args.output_geojson,
        corner_angle_degrees=args.corner_angle_degrees,
        line_tolerance_degrees=args.line_tolerance_degrees,
        max_shape_points=args.max_shape_points,
        min_corner_leg_meter=args.min_corner_leg_meter,
        max_corner_nodes_per_line=args.max_corner_nodes_per_line,
        node_snap_meter=args.node_snap_meter,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
