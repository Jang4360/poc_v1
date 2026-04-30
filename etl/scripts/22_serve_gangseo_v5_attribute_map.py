#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import heapq
import json
import math
import mimetypes
import os
import re
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

ROOT_DIR = Path(__file__).resolve().parents[2]
ETL_DIR = ROOT_DIR / "etl"

SEGMENT_CSV = ETL_DIR / "gangseo_road_segments_v6.csv"
SHARED_CSV = ETL_DIR / "shared_local_road_edges.csv"
STAIRS_CSV = ETL_DIR / "stair_p1_p2_candidates.csv"
SLOPE_CSV = ETL_DIR / "road_slope_surface_width.csv"
SIDEWALK_CSV = ETL_DIR / "sidewalk_segments.csv"
NODE_CSV = ETL_DIR / "gangseo_road_nodes_v6.csv"
ROUTE_SEGMENT_CSV = ETL_DIR / "gangseo_road_segments_v6.csv"
HTML_PATH = ETL_DIR / "gangseo_v5_attribute_overlay_map.html"

NOKSAN = {
    "minLng": 128.815,
    "minLat": 35.075,
    "maxLng": 128.858,
    "maxLat": 35.135,
    "centerLng": 128.8365,
    "centerLat": 35.105,
}

NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


@dataclass(frozen=True)
class Feature:
    id: str
    coords: list[list[float]]
    bbox: tuple[float, float, float, float]
    props: dict[str, Any]


@dataclass(frozen=True)
class RouteArc:
    to_node: str
    edge_id: str
    coords: list[list[float]]
    length_m: float
    props: dict[str, Any]


@dataclass
class RouteGraph:
    nodes: dict[str, list[float]]
    adjacency: dict[str, list[RouteArc]]
    component_by_node: dict[str, int]
    edge_count: int


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def parse_geometry(value: str) -> list[list[float]]:
    if not value:
        return []
    if value.startswith("SRID="):
        value = value.split(";", 1)[1]
    values = [float(item) for item in NUMBER_RE.findall(value)]
    if len(values) < 2 or len(values) % 2:
        return []
    return [[lng, lat] for lng, lat in zip(values[0::2], values[1::2])]


def bbox_for(coords: list[list[float]]) -> tuple[float, float, float, float]:
    lngs = [coord[0] for coord in coords]
    lats = [coord[1] for coord in coords]
    return min(lngs), min(lats), max(lngs), max(lats)


def intersects(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return a[2] >= b[0] and a[0] <= b[2] and a[3] >= b[1] and a[1] <= b[3]


def compact_props(row: dict[str, str], keys: list[str]) -> dict[str, str]:
    return {key: row.get(key, "") for key in keys if row.get(key, "") not in {"", "NULL"}}


def parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    value = value.strip()
    if not value or value.upper() == "NULL":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def haversine_m(a: list[float], b: list[float]) -> float:
    lng1, lat1 = math.radians(a[0]), math.radians(a[1])
    lng2, lat2 = math.radians(b[0]), math.radians(b[1])
    d_lng = lng2 - lng1
    d_lat = lat2 - lat1
    value = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lng / 2) ** 2
    return 6371008.8 * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def slope_state(row: dict[str, str]) -> str:
    slope_max = parse_float(row.get("slopeMax"))
    width_meter = parse_float(row.get("widthMeter"))
    width_level = (row.get("widthLevel") or "").strip()
    if (width_meter is not None and width_meter < 2.0) or width_level == "VERY_NARROW":
        return "IMPASSABLE"
    if slope_max is None:
        return "UNKNOWN"
    if slope_max <= 3.0:
        return "FLAT"
    if slope_max <= 5.56:
        return "MODERATE"
    if slope_max <= 8.33:
        return "STEEP"
    return "IMPASSABLE"


def read_features(path: Path, *, id_keys: list[str], geom_key: str, prop_keys: list[str]) -> list[Feature]:
    features: list[Feature] = []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for idx, row in enumerate(reader, start=1):
            coords = parse_geometry(row.get(geom_key, ""))
            if not coords:
                continue
            feature_id = next((row.get(key, "") for key in id_keys if row.get(key, "")), str(idx))
            props = compact_props(row, prop_keys)
            if path == SLOPE_CSV:
                props["slopeState"] = slope_state(row)
                props["surfaceType"] = (row.get("surfaceType") or "UNKNOWN").strip().upper() or "UNKNOWN"
            features.append(
                Feature(
                    id=feature_id,
                    coords=coords,
                    bbox=bbox_for(coords),
                    props=props,
                )
            )
    return features


def full_bbox(features: list[Feature]) -> dict[str, float]:
    min_lng = min(feature.bbox[0] for feature in features)
    min_lat = min(feature.bbox[1] for feature in features)
    max_lng = max(feature.bbox[2] for feature in features)
    max_lat = max(feature.bbox[3] for feature in features)
    return {
        "minLng": min_lng,
        "minLat": min_lat,
        "maxLng": max_lng,
        "maxLat": max_lat,
        "centerLng": (min_lng + max_lng) / 2,
        "centerLat": (min_lat + max_lat) / 2,
    }


def feature_json(feature: Feature) -> dict[str, Any]:
    return {"id": feature.id, "coords": feature.coords, "props": feature.props}


def parse_bbox(value: str | None) -> tuple[float, float, float, float]:
    if not value:
        return NOKSAN["minLng"], NOKSAN["minLat"], NOKSAN["maxLng"], NOKSAN["maxLat"]
    parts = [float(part) for part in value.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must be minLng,minLat,maxLng,maxLat")
    return parts[0], parts[1], parts[2], parts[3]


def load_all() -> dict[str, list[Feature]]:
    print("loading CSV map layers...")
    data = {
        "base": read_features(
            SEGMENT_CSV,
            id_keys=["edgeId"],
            geom_key="geom",
            prop_keys=["edgeId", "lengthMeter", "segmentType", "walkAccess", "avgSlopePercent", "stairsState"],
        ),
        "shared": read_features(
            SHARED_CSV,
            id_keys=["handoffEdgeId", "sourceId", "nfId"],
            geom_key="geometryWkt",
            prop_keys=["handoffEdgeId", "sourceId", "districtGu", "roadName", "widthMeter", "widthLevel", "slopePercent", "surfaceLabel"],
        ),
        "slope": read_features(
            SLOPE_CSV,
            id_keys=["handoffEdgeId", "sourceId", "ufid"],
            geom_key="geometryWkt",
            prop_keys=["handoffEdgeId", "sourceId", "districtGu", "name", "roadName", "widthMeter", "slopeMean", "slopeMax", "widthLevel", "surfaceType"],
        ),
        "stairs": read_features(
            STAIRS_CSV,
            id_keys=["sourceId", "ufid"],
            geom_key="geometryWkt",
            prop_keys=["sourceId", "districtGu", "name", "priority", "reviewStatus", "decision", "nearestRoadDistanceM"],
        ),
        "sidewalk": read_features(
            SIDEWALK_CSV,
            id_keys=["segmentId", "sourceId"],
            geom_key="wkt",
            prop_keys=[
                "segmentId",
                "districtGu",
                "segmentType",
                "sourceId",
                "lengthMeter",
                "widthMeter",
                "surfaceLabel",
                "routingStage",
            ],
        ),
    }
    print("loaded:", {key: len(value) for key, value in data.items()})
    return data


def load_node_points(path: Path) -> dict[str, list[float]]:
    nodes: dict[str, list[float]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            coords = parse_geometry(row.get("point", ""))
            vertex_id = row.get("vertexId", "")
            if vertex_id and coords:
                nodes[vertex_id] = coords[0]
    return nodes


def normalized_state(value: str | None, fallback: str = "UNKNOWN") -> str:
    value = (value or "").strip().upper()
    return value if value and value != "NULL" else fallback


def edge_props(row: dict[str, str]) -> dict[str, Any]:
    return {
        "walkAccess": normalized_state(row.get("walkAccess")),
        "slopeState": normalized_state(row.get("slopeState") or row.get("rampState")),
        "avgSlopePercent": parse_float(row.get("avgSlopePercent")),
        "widthMeter": parse_float(row.get("widthMeter")),
        "surfaceType": normalized_state(row.get("surfaceType")),
        "surfaceState": normalized_state(row.get("surfaceState")),
        "stairsState": normalized_state(row.get("stairsState")),
        "segmentType": normalized_state(row.get("segmentType"), ""),
    }


def load_route_graph() -> RouteGraph:
    print("loading route graph...")
    nodes = load_node_points(NODE_CSV)
    adjacency: dict[str, list[RouteArc]] = {}
    edge_count = 0
    with ROUTE_SEGMENT_CSV.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            from_node = row.get("fromNodeId", "")
            to_node = row.get("toNodeId", "")
            if not from_node or not to_node or from_node not in nodes or to_node not in nodes:
                continue
            coords = parse_geometry(row.get("geom", ""))
            if len(coords) < 2:
                coords = [nodes[from_node], nodes[to_node]]
            length_m = parse_float(row.get("lengthMeter"))
            if length_m is None:
                length_m = sum(haversine_m(a, b) for a, b in zip(coords, coords[1:]))
            props = edge_props(row)
            edge_id = row.get("edgeId", str(edge_count + 1))
            adjacency.setdefault(from_node, []).append(RouteArc(to_node, edge_id, coords, length_m, props))
            adjacency.setdefault(to_node, []).append(RouteArc(from_node, edge_id, list(reversed(coords)), length_m, props))
            edge_count += 1
    active_nodes = {node for node, arcs in adjacency.items() if arcs}
    nodes = {node: coord for node, coord in nodes.items() if node in active_nodes}
    component_by_node = connected_components(adjacency)
    print("route graph loaded:", {"nodes": len(nodes), "edges": edge_count, "components": len(set(component_by_node.values()))})
    return RouteGraph(nodes=nodes, adjacency=adjacency, component_by_node=component_by_node, edge_count=edge_count)


def connected_components(adjacency: dict[str, list[RouteArc]]) -> dict[str, int]:
    component_by_node: dict[str, int] = {}
    component_id = 0
    for node in adjacency:
        if node in component_by_node:
            continue
        stack = [node]
        component_by_node[node] = component_id
        while stack:
            current = stack.pop()
            for arc in adjacency.get(current, []):
                if arc.to_node not in component_by_node:
                    component_by_node[arc.to_node] = component_id
                    stack.append(arc.to_node)
        component_id += 1
    return component_by_node


def nearest_node(graph: RouteGraph, lng: float, lat: float) -> tuple[str, float]:
    target = [lng, lat]
    best_node = ""
    best_distance = float("inf")
    for node_id, coord in graph.nodes.items():
        distance = haversine_m(target, coord)
        if distance < best_distance:
            best_node = node_id
            best_distance = distance
    if not best_node:
        raise ValueError("route graph has no nodes")
    return best_node, best_distance


def nearest_node_candidates(graph: RouteGraph, lng: float, lat: float, limit: int = 80) -> list[tuple[str, float]]:
    target = [lng, lat]
    candidates = [(node_id, haversine_m(target, coord)) for node_id, coord in graph.nodes.items()]
    candidates.sort(key=lambda item: item[1])
    return candidates[:limit]


def nearest_connected_pair(
    graph: RouteGraph,
    origin_lng: float,
    origin_lat: float,
    destination_lng: float,
    destination_lat: float,
) -> tuple[str, float, str, float]:
    origin_candidates = nearest_node_candidates(graph, origin_lng, origin_lat)
    destination_candidates = nearest_node_candidates(graph, destination_lng, destination_lat)
    best: tuple[float, str, float, str, float] | None = None
    for origin_node, origin_distance in origin_candidates:
        origin_component = graph.component_by_node.get(origin_node)
        for destination_node, destination_distance in destination_candidates:
            if origin_component != graph.component_by_node.get(destination_node):
                continue
            score = origin_distance + destination_distance
            if best is None or score < best[0]:
                best = (score, origin_node, origin_distance, destination_node, destination_distance)
    if best is None:
        start_node, start_snap_m = nearest_node(graph, origin_lng, origin_lat)
        end_node, end_snap_m = nearest_node(graph, destination_lng, destination_lat)
        return start_node, start_snap_m, end_node, end_snap_m
    _, start_node, start_snap_m, end_node, end_snap_m = best
    return start_node, start_snap_m, end_node, end_snap_m


def route_multiplier(props: dict[str, Any], profile: str, route_kind: str) -> float:
    slope = props.get("slopeState", "UNKNOWN")
    surface = props.get("surfaceType", "UNKNOWN")
    stairs = props.get("stairsState", "UNKNOWN")
    width = props.get("widthMeter")
    walk_access = props.get("walkAccess", "UNKNOWN")
    multiplier = 1.0

    if route_kind == "fast":
        multiplier += {"FLAT": 0.0, "MODERATE": 0.04, "STEEP": 0.14, "IMPASSABLE": 0.7, "UNKNOWN": 0.08}.get(slope, 0.08)
        multiplier += {"PAVED": 0.0, "UNPAVED": 0.12, "UNKNOWN": 0.05}.get(surface, 0.05)
        if stairs == "YES":
            multiplier += 0.8 if profile == "visuality" else 3.0
        if isinstance(width, float) and width < 1.2:
            multiplier += 0.45 if profile == "visuality" else 1.2
        return multiplier

    if profile == "mobility":
        multiplier += {"FLAT": 0.0, "MODERATE": 0.35, "STEEP": 1.4, "IMPASSABLE": 8.0, "UNKNOWN": 0.45}.get(slope, 0.45)
        multiplier += {"PAVED": 0.0, "UNPAVED": 1.1, "UNKNOWN": 0.35}.get(surface, 0.35)
        if stairs == "YES":
            multiplier += 20.0
        if isinstance(width, float):
            if width < 1.2:
                multiplier += 5.0
            elif width < 1.5:
                multiplier += 1.2
            elif width >= 2.0:
                multiplier -= 0.08
    else:
        multiplier += {"FLAT": 0.0, "MODERATE": 0.18, "STEEP": 0.65, "IMPASSABLE": 2.0, "UNKNOWN": 0.28}.get(slope, 0.28)
        multiplier += {"PAVED": 0.0, "UNPAVED": 0.35, "UNKNOWN": 0.16}.get(surface, 0.16)
        if stairs == "YES":
            multiplier += 2.5
        if isinstance(width, float) and width < 1.2:
            multiplier += 0.75

    if walk_access == "YES":
        multiplier -= 0.05
    return max(multiplier, 0.2)


def edge_warnings(props: dict[str, Any], profile: str) -> list[str]:
    warnings: list[str] = []
    if props.get("stairsState") == "YES":
        warnings.append("stairs")
    if props.get("slopeState") in {"STEEP", "IMPASSABLE"}:
        warnings.append(f"slope:{props.get('slopeState')}")
    if props.get("surfaceType") == "UNPAVED":
        warnings.append("surface:UNPAVED")
    width = props.get("widthMeter")
    if isinstance(width, float) and width < (1.5 if profile == "mobility" else 1.2):
        warnings.append("narrow")
    return warnings


def dijkstra(graph: RouteGraph, start_node: str, end_node: str, profile: str, route_kind: str) -> dict[str, Any]:
    queue: list[tuple[float, str]] = [(0.0, start_node)]
    distances = {start_node: 0.0}
    previous: dict[str, tuple[str, RouteArc]] = {}
    visited: set[str] = set()

    while queue:
        cost, node = heapq.heappop(queue)
        if node in visited:
            continue
        visited.add(node)
        if node == end_node:
            break
        for arc in graph.adjacency.get(node, []):
            next_cost = cost + arc.length_m * route_multiplier(arc.props, profile, route_kind)
            if next_cost < distances.get(arc.to_node, float("inf")):
                distances[arc.to_node] = next_cost
                previous[arc.to_node] = (node, arc)
                heapq.heappush(queue, (next_cost, arc.to_node))

    if end_node not in previous and start_node != end_node:
        raise ValueError("route not found between selected points")

    arcs: list[RouteArc] = []
    node = end_node
    while node != start_node:
        prev_node, arc = previous[node]
        arcs.append(arc)
        node = prev_node
    arcs.reverse()

    coords: list[list[float]] = []
    slope_counts: dict[str, int] = {}
    surface_counts: dict[str, int] = {}
    warning_counts: dict[str, int] = {}
    distance_m = 0.0
    for arc in arcs:
        if coords and arc.coords and coords[-1] == arc.coords[0]:
            coords.extend(arc.coords[1:])
        else:
            coords.extend(arc.coords)
        distance_m += arc.length_m
        slope = arc.props.get("slopeState", "UNKNOWN")
        surface = arc.props.get("surfaceType", "UNKNOWN")
        slope_counts[slope] = slope_counts.get(slope, 0) + 1
        surface_counts[surface] = surface_counts.get(surface, 0) + 1
        for warning in edge_warnings(arc.props, profile):
            warning_counts[warning] = warning_counts.get(warning, 0) + 1

    speed_mps = 1.05 if route_kind == "safe" else 1.22
    return {
        "kind": route_kind,
        "label": "안전한길" if route_kind == "safe" else "빠른길",
        "profile": profile,
        "coords": coords,
        "distanceMeter": round(distance_m, 1),
        "estimatedMinutes": round(distance_m / speed_mps / 60, 1) if distance_m else 0,
        "cost": round(distances.get(end_node, 0.0), 1),
        "edgeCount": len(arcs),
        "slopeStateCounts": slope_counts,
        "surfaceTypeCounts": surface_counts,
        "warningCounts": warning_counts,
        "edgeIds": [arc.edge_id for arc in arcs],
    }


def route_payload(graph: RouteGraph, query: dict[str, list[str]]) -> dict[str, Any]:
    profile = (query.get("profile", ["mobility"])[0] or "mobility").lower()
    if profile not in {"mobility", "visuality"}:
        raise ValueError("profile must be mobility or visuality")
    origin_lng = float(query.get("originLng", [""])[0])
    origin_lat = float(query.get("originLat", [""])[0])
    destination_lng = float(query.get("destinationLng", [""])[0])
    destination_lat = float(query.get("destinationLat", [""])[0])
    start_node, start_snap_m, end_node, end_snap_m = nearest_connected_pair(
        graph,
        origin_lng,
        origin_lat,
        destination_lng,
        destination_lat,
    )
    return {
        "profile": profile,
        "origin": {"lng": origin_lng, "lat": origin_lat, "nodeId": start_node, "snapDistanceMeter": round(start_snap_m, 1)},
        "destination": {
            "lng": destination_lng,
            "lat": destination_lat,
            "nodeId": end_node,
            "snapDistanceMeter": round(end_snap_m, 1),
        },
        "routes": [
            dijkstra(graph, start_node, end_node, profile, "safe"),
            dijkstra(graph, start_node, end_node, profile, "fast"),
        ],
    }


class MapHandler(BaseHTTPRequestHandler):
    data: dict[str, list[Feature]] = {}
    meta: dict[str, Any] = {}
    route_graph: RouteGraph | None = None

    def log_message(self, format: str, *args: Any) -> None:
        return

    def send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path) -> None:
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            if path in {"/", "/gangseo_v5_attribute_overlay_map.html"}:
                self.send_file(HTML_PATH)
                return
            if path == "/api/kakao-key":
                key = os.getenv("KAKAO_JAVASCRIPT_KEY", "")
                if not key:
                    self.send_json({"error": "KAKAO_JAVASCRIPT_KEY is missing"}, status=500)
                    return
                self.send_json({"key": key})
                return
            if path == "/api/gangseo-v5-attribute-map-meta":
                self.send_json(self.meta)
                return
            if path == "/api/walk-route":
                if self.route_graph is None:
                    self.send_json({"error": "route graph is not loaded"}, status=500)
                    return
                self.send_json(route_payload(self.route_graph, parse_qs(parsed.query)))
                return
            if path == "/api/gangseo-v5-attribute-map-data":
                query = parse_qs(parsed.query)
                bbox = parse_bbox(query.get("bbox", [None])[0])
                requested_slope_state = (query.get("slopeState", ["ALL"])[0] or "ALL").upper()
                requested_surface_type = (query.get("surfaceType", ["NONE"])[0] or "NONE").upper()
                payload: dict[str, list[dict[str, Any]]] = {}
                for layer, features in self.data.items():
                    filtered = [feature for feature in features if intersects(feature.bbox, bbox)]
                    if layer == "slope" and requested_slope_state != "ALL":
                        if requested_slope_state == "NONE":
                            filtered = []
                        else:
                            filtered = [
                                feature
                                for feature in filtered
                                if str(feature.props.get("slopeState", "UNKNOWN")).upper() == requested_slope_state
                            ]
                    payload[layer] = [feature_json(feature) for feature in filtered]
                surface_features = [feature for feature in self.data["slope"] if intersects(feature.bbox, bbox)]
                if requested_surface_type == "NONE":
                    surface_features = []
                else:
                    surface_features = [
                        feature
                        for feature in surface_features
                        if str(feature.props.get("surfaceType", "UNKNOWN")).upper() == requested_surface_type
                    ]
                payload["surface"] = [feature_json(feature) for feature in surface_features]
                self.send_json(payload)
                return
            if path.startswith("/etl/"):
                candidate = ROOT_DIR / path.lstrip("/")
                if candidate.exists() and candidate.is_file():
                    self.send_file(candidate)
                    return
            self.send_json({"error": "not found"}, status=404)
        except Exception as exc:  # noqa: BLE001
            self.send_json({"error": str(exc)}, status=500)


def build_meta(data: dict[str, list[Feature]], route_graph: RouteGraph) -> dict[str, Any]:
    return {
        "counts": {layer: len(features) for layer, features in data.items()},
        "noksan": NOKSAN,
        "full": full_bbox(data["base"]),
        "sources": {
            "base": str(SEGMENT_CSV),
            "shared": str(SHARED_CSV),
            "slope": str(SLOPE_CSV),
            "stairs": str(STAIRS_CSV),
            "sidewalk": str(SIDEWALK_CSV),
            "routeSegments": str(ROUTE_SEGMENT_CSV),
            "routeNodes": str(NODE_CSV),
        },
        "routeGraph": {
            "nodes": len(route_graph.nodes),
            "edges": route_graph.edge_count,
            "components": len(set(route_graph.component_by_node.values())),
            "profiles": ["mobility", "visuality"],
            "routeKinds": ["safe", "fast"],
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve Gangseo v5 segment and attribute overlay Kakao map.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(ROOT_DIR / ".env")
    data = load_all()
    route_graph = load_route_graph()
    MapHandler.data = data
    MapHandler.route_graph = route_graph
    MapHandler.meta = build_meta(data, route_graph)
    server = ThreadingHTTPServer((args.host, args.port), MapHandler)
    url = f"http://{args.host}:{args.port}/gangseo_v5_attribute_overlay_map.html"
    print(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
