from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SIDE_TYPES = {"SIDE_LEFT", "SIDE_RIGHT"}
BRIDGE_TYPES = {"SAME_SIDE_CORNER_BRIDGE", "CROSS_SIDE_CORNER_BRIDGE", "GAP_BRIDGE"}
REPAIRABLE_TYPES = SIDE_TYPES | BRIDGE_TYPES

EARTH_M_PER_DEG_LAT = 111_320.0
SNAP_CLUSTER_RADIUS_M = 4.0
DENSE_CLUSTER_MIN_NODES = 4
TAIL_MAX_M = 18.0
DENSE_INTERSECTION_RADIUS_M = 13.0
DENSE_INTERSECTION_TAIL_MAX_M = 42.0
SAME_SIDE_GAP_MAX_M = 32.0
SAME_SIDE_GAP_MIN_M = 2.0
SAME_SIDE_GAP_MAX_ANGLE_DEG = 38.0
SAME_SIDE_MICRO_GAP_MAX_M = 24.0
SAME_SIDE_MICRO_GAP_MAX_ANGLE_DEG = 30.0
SAME_SIDE_GAP_CONTINUATION_ANGLE_DEG = 145.0
SAME_SIDE_BRIDGE_MAX_M = 38.0
SAME_SIDE_BRIDGE_MAX_ANGLE_DEG = 34.0
SAME_SIDE_BRIDGE_MAX_DETOUR_RATIO = 1.05
SAME_SIDE_BRIDGE_MAX_TURN_DEG = 28.0
BRIDGE_ARTIFACT_MAX_M = 14.0
MICRO_LOOP_MAX_M = 8.0
MIN_SEGMENT_M = 0.75


@dataclass(frozen=True)
class SegmentFeature:
    edge_id: int
    segment_type: str
    coords: tuple[tuple[float, float], ...]
    properties: dict[str, Any]


@dataclass(frozen=True)
class ScanReport:
    iteration: int
    anomaly_count: int
    action_count: int
    removed_edges: int
    added_edges: int
    snapped_endpoints: int
    node_count: int
    segment_count: int
    details: dict[str, int]


class DisjointSet:
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


def load_payload(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_payload(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def lonlat_to_xy(lon: float, lat: float, *, center_lat: float, center_lon: float) -> tuple[float, float]:
    x = (lon - center_lon) * EARTH_M_PER_DEG_LAT * math.cos(math.radians(center_lat))
    y = (lat - center_lat) * EARTH_M_PER_DEG_LAT
    return x, y


def xy_to_lonlat(x: float, y: float, *, center_lat: float, center_lon: float) -> tuple[float, float]:
    lon = x / (EARTH_M_PER_DEG_LAT * math.cos(math.radians(center_lat))) + center_lon
    lat = y / EARTH_M_PER_DEG_LAT + center_lat
    return lon, lat


def distance_m(left: tuple[float, float], right: tuple[float, float]) -> float:
    return math.hypot(right[0] - left[0], right[1] - left[1])


def vector_length(vector: tuple[float, float]) -> float:
    return math.hypot(vector[0], vector[1])


def angle_deg(left: tuple[float, float], right: tuple[float, float]) -> float:
    left_len = vector_length(left)
    right_len = vector_length(right)
    if left_len <= 0 or right_len <= 0:
        return 180.0
    value = max(-1.0, min(1.0, (left[0] * right[0] + left[1] * right[1]) / (left_len * right_len)))
    return math.degrees(math.acos(value))


def endpoint_outward_vector(
    segment: SegmentFeature,
    endpoint_index: int,
    *,
    center_lat: float,
    center_lon: float,
) -> tuple[float, float] | None:
    if len(segment.coords) < 2:
        return None
    if endpoint_index == 0:
        endpoint = lonlat_to_xy(segment.coords[0][0], segment.coords[0][1], center_lat=center_lat, center_lon=center_lon)
        neighbor = lonlat_to_xy(segment.coords[1][0], segment.coords[1][1], center_lat=center_lat, center_lon=center_lon)
    else:
        endpoint = lonlat_to_xy(segment.coords[-1][0], segment.coords[-1][1], center_lat=center_lat, center_lon=center_lon)
        neighbor = lonlat_to_xy(segment.coords[-2][0], segment.coords[-2][1], center_lat=center_lat, center_lon=center_lon)
    vector = (endpoint[0] - neighbor[0], endpoint[1] - neighbor[1])
    return vector if vector_length(vector) > 0 else None


def polyline_length_m(coords: tuple[tuple[float, float], ...], *, center_lat: float, center_lon: float) -> float:
    points = [lonlat_to_xy(lon, lat, center_lat=center_lat, center_lon=center_lon) for lon, lat in coords]
    return sum(distance_m(points[index], points[index + 1]) for index in range(len(points) - 1))


def polyline_detour_ratio(coords: tuple[tuple[float, float], ...], *, center_lat: float, center_lon: float) -> float:
    if len(coords) < 2:
        return math.inf
    length = polyline_length_m(coords, center_lat=center_lat, center_lon=center_lon)
    chord = distance_m(
        lonlat_to_xy(coords[0][0], coords[0][1], center_lat=center_lat, center_lon=center_lon),
        lonlat_to_xy(coords[-1][0], coords[-1][1], center_lat=center_lat, center_lon=center_lon),
    )
    return math.inf if chord <= 0 else length / chord


def max_polyline_turn_deg(coords: tuple[tuple[float, float], ...], *, center_lat: float, center_lon: float) -> float:
    if len(coords) < 3:
        return 0.0
    points = [lonlat_to_xy(lon, lat, center_lat=center_lat, center_lon=center_lon) for lon, lat in coords]
    max_turn = 0.0
    for index in range(1, len(points) - 1):
        incoming = (points[index][0] - points[index - 1][0], points[index][1] - points[index - 1][1])
        outgoing = (points[index + 1][0] - points[index][0], points[index + 1][1] - points[index][1])
        max_turn = max(max_turn, angle_deg(incoming, outgoing))
    return max_turn


def endpoint_key(point: tuple[float, float], *, center_lat: float, center_lon: float, precision_m: float = 0.75) -> tuple[int, int]:
    x, y = lonlat_to_xy(point[0], point[1], center_lat=center_lat, center_lon=center_lon)
    return (round(x / precision_m), round(y / precision_m))


def parse_segments(payload: dict[str, Any]) -> list[SegmentFeature]:
    segments: list[SegmentFeature] = []
    for index, feature in enumerate(payload["layers"]["roadSegments"]["features"], start=1):
        coords = tuple((float(lon), float(lat)) for lon, lat in feature["geometry"]["coordinates"])
        props = dict(feature.get("properties") or {})
        edge_id = int(props.get("edgeId", index))
        segment_type = str(props.get("segmentType", "UNKNOWN"))
        segments.append(SegmentFeature(edge_id=edge_id, segment_type=segment_type, coords=coords, properties=props))
    return segments


def endpoint_records(
    segments: list[SegmentFeature],
    *,
    center_lat: float,
    center_lon: float,
) -> tuple[list[tuple[int, int, tuple[float, float], tuple[float, float]]], Counter[tuple[int, int]]]:
    records: list[tuple[int, int, tuple[float, float], tuple[float, float]]] = []
    degree: Counter[tuple[int, int]] = Counter()
    for segment_index, segment in enumerate(segments):
        for endpoint_index, point in ((0, segment.coords[0]), (1, segment.coords[-1])):
            xy = lonlat_to_xy(point[0], point[1], center_lat=center_lat, center_lon=center_lon)
            key = endpoint_key(point, center_lat=center_lat, center_lon=center_lon)
            records.append((segment_index, endpoint_index, point, xy))
            degree[key] += 1
    return records, degree


def dense_endpoint_clusters(
    records: list[tuple[int, int, tuple[float, float], tuple[float, float]]],
) -> set[tuple[int, int]]:
    if not records:
        return set()
    grid_size = DENSE_INTERSECTION_RADIUS_M
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for index, (_, _, _, xy) in enumerate(records):
        cell = (math.floor(xy[0] / grid_size), math.floor(xy[1] / grid_size))
        grid[cell].append(index)

    dense_keys: set[tuple[int, int]] = set()
    for index, (_, _, point, xy) in enumerate(records):
        nearby = 0
        cell = (math.floor(xy[0] / grid_size), math.floor(xy[1] / grid_size))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other_index in grid.get((cell[0] + dx, cell[1] + dy), []):
                    if distance_m(xy, records[other_index][3]) <= DENSE_INTERSECTION_RADIUS_M:
                        nearby += 1
        if nearby >= DENSE_CLUSTER_MIN_NODES:
            # center coordinates are stable enough for membership checks at 0.75m precision.
            dense_keys.add((round(xy[0] / 0.75), round(xy[1] / 0.75)))
    return dense_keys


def endpoint_side_vectors(
    segments: list[SegmentFeature],
    *,
    center_lat: float,
    center_lon: float,
) -> dict[tuple[int, int], list[tuple[int, int, str, tuple[float, float]]]]:
    vectors: dict[tuple[int, int], list[tuple[int, int, str, tuple[float, float]]]] = defaultdict(list)
    for segment_index, segment in enumerate(segments):
        if segment.segment_type not in SIDE_TYPES:
            continue
        for endpoint_index, point in ((0, segment.coords[0]), (1, segment.coords[-1])):
            vector = endpoint_outward_vector(segment, endpoint_index, center_lat=center_lat, center_lon=center_lon)
            if vector is None:
                continue
            vectors[endpoint_key(point, center_lat=center_lat, center_lon=center_lon)].append(
                (segment_index, endpoint_index, segment.segment_type, vector)
            )
    return vectors


def cluster_endpoint_snaps(
    records: list[tuple[int, int, tuple[float, float], tuple[float, float]]],
    *,
    center_lat: float,
    center_lon: float,
) -> tuple[dict[tuple[int, int], tuple[float, float]], int]:
    if not records:
        return {}, 0

    grid_size = SNAP_CLUSTER_RADIUS_M
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for index, (_, _, _, xy) in enumerate(records):
        cell = (math.floor(xy[0] / grid_size), math.floor(xy[1] / grid_size))
        grid[cell].append(index)

    dsu = DisjointSet(len(records))
    for index, (_, _, _, xy) in enumerate(records):
        cell = (math.floor(xy[0] / grid_size), math.floor(xy[1] / grid_size))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other_index in grid.get((cell[0] + dx, cell[1] + dy), []):
                    if other_index <= index:
                        continue
                    if distance_m(xy, records[other_index][3]) <= SNAP_CLUSTER_RADIUS_M:
                        dsu.union(index, other_index)

    groups: dict[int, list[int]] = defaultdict(list)
    for index in range(len(records)):
        groups[dsu.find(index)].append(index)

    snaps: dict[tuple[int, int], tuple[float, float]] = {}
    snapped = 0
    for members in groups.values():
        if len(members) < 2:
            continue
        x = sum(records[index][3][0] for index in members) / len(members)
        y = sum(records[index][3][1] for index in members) / len(members)
        max_spread = max(distance_m((x, y), records[index][3]) for index in members)
        if max_spread > SNAP_CLUSTER_RADIUS_M:
            continue
        lonlat = xy_to_lonlat(x, y, center_lat=center_lat, center_lon=center_lon)
        for index in members:
            segment_index, endpoint_index, point, _ = records[index]
            if distance_m(lonlat_to_xy(point[0], point[1], center_lat=center_lat, center_lon=center_lon), (x, y)) > 0.2:
                snapped += 1
            snaps[(segment_index, endpoint_index)] = lonlat
    return snaps, snapped


def apply_endpoint_snaps(
    segments: list[SegmentFeature],
    snaps: dict[tuple[int, int], tuple[float, float]],
    *,
    center_lat: float,
    center_lon: float,
) -> list[SegmentFeature]:
    repaired: list[SegmentFeature] = []
    for index, segment in enumerate(segments):
        start = snaps.get((index, 0), segment.coords[0])
        end = snaps.get((index, 1), segment.coords[-1])
        coords = (start, *segment.coords[1:-1], end)
        deduped: list[tuple[float, float]] = []
        for point in coords:
            if not deduped or point != deduped[-1]:
                deduped.append(point)
        if len(deduped) < 2:
            continue
        if polyline_length_m(tuple(deduped), center_lat=center_lat, center_lon=center_lon) <= MIN_SEGMENT_M:
            continue
        repaired.append(SegmentFeature(segment.edge_id, segment.segment_type, tuple(deduped), dict(segment.properties)))
    return repaired


def normalize_same_side_corner_bridges(
    segments: list[SegmentFeature],
    *,
    center_lat: float,
    center_lon: float,
) -> tuple[list[SegmentFeature], Counter[str]]:
    incident_side_vectors: dict[tuple[int, int], list[tuple[str, tuple[float, float]]]] = defaultdict(list)
    for segment in segments:
        if segment.segment_type not in SIDE_TYPES:
            continue
        for endpoint_index, point in ((0, segment.coords[0]), (1, segment.coords[-1])):
            vector = endpoint_outward_vector(segment, endpoint_index, center_lat=center_lat, center_lon=center_lon)
            if vector is None:
                continue
            incident_side_vectors[endpoint_key(point, center_lat=center_lat, center_lon=center_lon)].append(
                (segment.segment_type, vector)
            )

    normalized: list[SegmentFeature] = []
    reasons: Counter[str] = Counter()
    next_edge_id = max((segment.edge_id for segment in segments), default=0) + 1

    for segment in segments:
        if segment.segment_type != "SAME_SIDE_CORNER_BRIDGE":
            normalized.append(segment)
            continue

        length = polyline_length_m(segment.coords, center_lat=center_lat, center_lon=center_lon)
        if length > SAME_SIDE_BRIDGE_MAX_M:
            reasons["sameSideCornerBridgeTooLong"] += 1
            continue
        if polyline_detour_ratio(segment.coords, center_lat=center_lat, center_lon=center_lon) > SAME_SIDE_BRIDGE_MAX_DETOUR_RATIO:
            reasons["sameSideCornerBridgeBent"] += 1
            continue
        if max_polyline_turn_deg(segment.coords, center_lat=center_lat, center_lon=center_lon) > SAME_SIDE_BRIDGE_MAX_TURN_DEG:
            reasons["sameSideCornerBridgeBent"] += 1
            continue

        start_key = endpoint_key(segment.coords[0], center_lat=center_lat, center_lon=center_lon)
        end_key = endpoint_key(segment.coords[-1], center_lat=center_lat, center_lon=center_lon)
        start_vectors = incident_side_vectors.get(start_key, [])
        end_vectors = incident_side_vectors.get(end_key, [])
        common_side_types = sorted({item[0] for item in start_vectors} & {item[0] for item in end_vectors})
        if not common_side_types:
            reasons["sameSideCornerBridgeNoSameSideIncident"] += 1
            continue

        start_xy = lonlat_to_xy(segment.coords[0][0], segment.coords[0][1], center_lat=center_lat, center_lon=center_lon)
        end_xy = lonlat_to_xy(segment.coords[-1][0], segment.coords[-1][1], center_lat=center_lat, center_lon=center_lon)
        chord_vector = (end_xy[0] - start_xy[0], end_xy[1] - start_xy[1])
        reverse_chord_vector = (-chord_vector[0], -chord_vector[1])
        valid_side_type: str | None = None
        for side_type in common_side_types:
            start_aligned = any(
                item_side == side_type and angle_deg(vector, chord_vector) <= SAME_SIDE_BRIDGE_MAX_ANGLE_DEG
                for item_side, vector in start_vectors
            )
            end_aligned = any(
                item_side == side_type and angle_deg(vector, reverse_chord_vector) <= SAME_SIDE_BRIDGE_MAX_ANGLE_DEG
                for item_side, vector in end_vectors
            )
            if start_aligned and end_aligned:
                valid_side_type = side_type
                break
        if valid_side_type is None:
            reasons["sameSideCornerBridgeBadAngle"] += 1
            continue

        properties = dict(segment.properties)
        properties["edgeId"] = next_edge_id
        properties["segmentType"] = valid_side_type
        properties["repairAction"] = "sameSideCornerBridgeNormalized"
        normalized.append(
            SegmentFeature(
                edge_id=next_edge_id,
                segment_type=valid_side_type,
                coords=(segment.coords[0], segment.coords[-1]),
                properties=properties,
            )
        )
        next_edge_id += 1
        reasons["sameSideCornerBridgeNormalized"] += 1

    return normalized, reasons


def detect_removal_edges(
    segments: list[SegmentFeature],
    *,
    center_lat: float,
    center_lon: float,
) -> tuple[set[int], Counter[str]]:
    records, degree = endpoint_records(segments, center_lat=center_lat, center_lon=center_lon)
    dense_keys = dense_endpoint_clusters(records)
    remove_indexes: set[int] = set()
    reasons: Counter[str] = Counter()

    for index, segment in enumerate(segments):
        if segment.segment_type not in REPAIRABLE_TYPES:
            continue
        if segment.properties.get("repairAction") in {"sameSideGapConnect", "sameSideCornerBridgeNormalized"}:
            continue
        length = polyline_length_m(segment.coords, center_lat=center_lat, center_lon=center_lon)
        start_key = endpoint_key(segment.coords[0], center_lat=center_lat, center_lon=center_lon)
        end_key = endpoint_key(segment.coords[-1], center_lat=center_lat, center_lon=center_lon)
        start_degree = degree[start_key]
        end_degree = degree[end_key]

        if length <= MICRO_LOOP_MAX_M and start_degree >= 2 and end_degree >= 2:
            remove_indexes.add(index)
            reasons["microLoop"] += 1
            continue

        if segment.segment_type in BRIDGE_TYPES and length <= BRIDGE_ARTIFACT_MAX_M:
            if start_degree >= 2 and end_degree >= 2:
                remove_indexes.add(index)
                reasons["shortBridgeArtifact"] += 1
                continue

        if segment.segment_type in SIDE_TYPES and length <= DENSE_INTERSECTION_TAIL_MAX_M:
            start_dense = start_key in dense_keys
            end_dense = end_key in dense_keys
            if (
                (start_dense and start_degree >= DENSE_CLUSTER_MIN_NODES and end_degree <= 2)
                or (end_dense and end_degree >= DENSE_CLUSTER_MIN_NODES and start_degree <= 2)
            ):
                remove_indexes.add(index)
                reasons["denseIntersectionTail"] += 1
                continue

        if segment.segment_type in SIDE_TYPES and length <= TAIL_MAX_M:
            if start_degree <= 1 < end_degree or end_degree <= 1 < start_degree:
                remove_indexes.add(index)
                reasons["danglingTail"] += 1
                continue

    return remove_indexes, reasons


def connect_same_side_gaps(
    segments: list[SegmentFeature],
    *,
    center_lat: float,
    center_lon: float,
) -> tuple[list[SegmentFeature], int]:
    records, degree = endpoint_records(segments, center_lat=center_lat, center_lon=center_lon)
    side_vectors_by_key = endpoint_side_vectors(segments, center_lat=center_lat, center_lon=center_lon)
    endpoint_candidates: list[tuple[int, int, int, tuple[float, float], tuple[float, float], tuple[float, float]]] = []
    for segment_index, endpoint_index, point, xy in records:
        segment = segments[segment_index]
        if segment.segment_type not in SIDE_TYPES:
            continue
        key = endpoint_key(point, center_lat=center_lat, center_lon=center_lon)
        if degree[key] > 2:
            continue
        outward = endpoint_outward_vector(segment, endpoint_index, center_lat=center_lat, center_lon=center_lon)
        if outward is None:
            continue
        has_same_side_continuation = any(
            other_segment_index != segment_index
            and other_type == segment.segment_type
            and angle_deg(outward, other_vector) >= SAME_SIDE_GAP_CONTINUATION_ANGLE_DEG
            for other_segment_index, _, other_type, other_vector in side_vectors_by_key.get(key, [])
        )
        if has_same_side_continuation:
            continue
        endpoint_candidates.append((segment_index, endpoint_index, degree[key], point, xy, outward))

    grid_size = SAME_SIDE_GAP_MAX_M
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for index, (_, _, _, _, xy, _) in enumerate(endpoint_candidates):
        grid[(math.floor(xy[0] / grid_size), math.floor(xy[1] / grid_size))].append(index)

    used_segments: set[int] = set()
    used_candidate_indexes: set[int] = set()
    additions: list[SegmentFeature] = []
    next_edge_id = max((segment.edge_id for segment in segments), default=0) + 1

    for index, (segment_index, _, endpoint_degree, point, xy, outward) in enumerate(endpoint_candidates):
        if index in used_candidate_indexes or segment_index in used_segments:
            continue
        segment = segments[segment_index]
        cell = (math.floor(xy[0] / grid_size), math.floor(xy[1] / grid_size))
        best: tuple[float, int, tuple[float, float]] | None = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other_index in grid.get((cell[0] + dx, cell[1] + dy), []):
                    if other_index == index or other_index in used_candidate_indexes:
                        continue
                    other_segment_index, _, other_endpoint_degree, other_point, other_xy, other_outward = endpoint_candidates[other_index]
                    other_segment = segments[other_segment_index]
                    if other_segment_index == segment_index or other_segment_index in used_segments:
                        continue
                    if other_segment.segment_type != segment.segment_type:
                        continue
                    gap_distance = distance_m(xy, other_xy)
                    max_gap = SAME_SIDE_GAP_MAX_M if endpoint_degree == 1 and other_endpoint_degree == 1 else SAME_SIDE_MICRO_GAP_MAX_M
                    max_angle = (
                        SAME_SIDE_GAP_MAX_ANGLE_DEG
                        if endpoint_degree == 1 and other_endpoint_degree == 1
                        else SAME_SIDE_MICRO_GAP_MAX_ANGLE_DEG
                    )
                    if gap_distance < SAME_SIDE_GAP_MIN_M or gap_distance > max_gap:
                        continue
                    gap_vector = (other_xy[0] - xy[0], other_xy[1] - xy[1])
                    reverse_gap_vector = (-gap_vector[0], -gap_vector[1])
                    if angle_deg(outward, gap_vector) > max_angle:
                        continue
                    if angle_deg(other_outward, reverse_gap_vector) > max_angle:
                        continue
                    if angle_deg(outward, reverse_gap_vector) < 135.0:
                        continue
                    candidate = (gap_distance, other_index, other_point)
                    if best is None or candidate[0] < best[0]:
                        best = candidate
        if best is None:
            continue
        _, other_index, other_point = best
        other_segment_index = endpoint_candidates[other_index][0]
        additions.append(
            SegmentFeature(
                edge_id=next_edge_id,
                segment_type=segment.segment_type,
                coords=(point, other_point),
                properties={
                    "edgeId": next_edge_id,
                    "segmentType": segment.segment_type,
                    "repairAction": "sameSideGapConnect",
                },
            )
        )
        next_edge_id += 1
        used_candidate_indexes.add(index)
        used_candidate_indexes.add(other_index)
        used_segments.add(segment_index)
        used_segments.add(other_segment_index)

    return [*segments, *additions], len(additions)


def rebuild_nodes(
    segments: list[SegmentFeature],
    *,
    center_lat: float,
    center_lon: float,
) -> list[dict[str, Any]]:
    endpoint_points: dict[tuple[int, int], list[tuple[float, float]]] = defaultdict(list)
    degree: Counter[tuple[int, int]] = Counter()
    for segment in segments:
        for point in (segment.coords[0], segment.coords[-1]):
            key = endpoint_key(point, center_lat=center_lat, center_lon=center_lon)
            endpoint_points[key].append(point)
            degree[key] += 1

    features: list[dict[str, Any]] = []
    for vertex_id, (key, points) in enumerate(endpoint_points.items(), start=1):
        lon = sum(point[0] for point in points) / len(points)
        lat = sum(point[1] for point in points) / len(points)
        node_degree = degree[key]
        node_type = "DEAD_END" if node_degree == 1 else "GRAPH_NODE" if node_degree < 3 else "CHAIN_JOIN"
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "vertexId": vertex_id,
                    "nodeType": node_type,
                    "degree": node_degree,
                },
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
            }
        )
    return features


def build_payload_from_segments(
    source_payload: dict[str, Any],
    segments: list[SegmentFeature],
    *,
    output_html: Path,
    output_geojson: Path,
    report: dict[str, Any],
) -> dict[str, Any]:
    meta = dict(source_payload["meta"])
    center_lat = float(meta["centerLat"])
    center_lon = float(meta["centerLon"])
    meta["title"] = "Haeundae 5km Side Graph Self-Repaired Preview"
    meta["outputHtml"] = str(output_html)
    meta["outputGeojson"] = str(output_geojson)
    meta["localhostUrl"] = f"http://127.0.0.1:3000/etl/{output_html.name}"
    meta["selfScanReport"] = report

    segment_counts = Counter(segment.segment_type for segment in segments)
    segment_features: list[dict[str, Any]] = []
    for edge_id, segment in enumerate(segments, start=1):
        props = dict(segment.properties)
        props["edgeId"] = edge_id
        props["segmentType"] = segment.segment_type
        props["lengthMeter"] = round(polyline_length_m(segment.coords, center_lat=center_lat, center_lon=center_lon), 2)
        segment_features.append(
            {
                "type": "Feature",
                "properties": props,
                "geometry": {"type": "LineString", "coordinates": [list(point) for point in segment.coords]},
            }
        )

    node_features = rebuild_nodes(segments, center_lat=center_lat, center_lon=center_lon)
    return {
        "meta": meta,
        "summary": {
            "nodeCount": len(node_features),
            "segmentCount": len(segment_features),
            "segmentTypeCounts": [{"name": name, "count": count} for name, count in sorted(segment_counts.items())],
            "transitionConnectorCount": segment_counts.get("TRANSITION_CONNECTOR", 0),
            "gapBridgeCount": segment_counts.get("GAP_BRIDGE", 0),
            "sameSideCornerBridgeCount": segment_counts.get("SAME_SIDE_CORNER_BRIDGE", 0),
            "crossSideCornerBridgeCount": segment_counts.get("CROSS_SIDE_CORNER_BRIDGE", 0),
            "crossingCount": segment_counts.get("CROSSING", 0),
            "elevatorConnectorCount": segment_counts.get("ELEVATOR_CONNECTOR", 0),
        },
        "layers": {
            "roadNodes": {"type": "FeatureCollection", "features": node_features},
            "roadSegments": {"type": "FeatureCollection", "features": segment_features},
        },
    }


def scan_once(
    segments: list[SegmentFeature],
    *,
    center_lat: float,
    center_lon: float,
    iteration: int,
) -> tuple[list[SegmentFeature], ScanReport]:
    records, _ = endpoint_records(segments, center_lat=center_lat, center_lon=center_lon)
    snaps, snapped_count = cluster_endpoint_snaps(records, center_lat=center_lat, center_lon=center_lon)
    snapped_segments = apply_endpoint_snaps(segments, snaps, center_lat=center_lat, center_lon=center_lon)
    normalized_segments, normalize_reasons = normalize_same_side_corner_bridges(
        snapped_segments,
        center_lat=center_lat,
        center_lon=center_lon,
    )
    connected_segments, added_edges = connect_same_side_gaps(normalized_segments, center_lat=center_lat, center_lon=center_lon)
    remove_indexes, reasons = detect_removal_edges(connected_segments, center_lat=center_lat, center_lon=center_lon)
    reasons.update(normalize_reasons)
    repaired = [segment for index, segment in enumerate(connected_segments) if index not in remove_indexes]
    node_features = rebuild_nodes(repaired, center_lat=center_lat, center_lon=center_lon)
    normalize_action_count = sum(normalize_reasons.values())
    anomaly_count = snapped_count + added_edges + sum(reasons.values())
    report = ScanReport(
        iteration=iteration,
        anomaly_count=anomaly_count,
        action_count=(1 if snapped_count else 0) + added_edges + len(remove_indexes) + normalize_action_count,
        removed_edges=len(remove_indexes),
        added_edges=added_edges,
        snapped_endpoints=snapped_count,
        node_count=len(node_features),
        segment_count=len(repaired),
        details=dict(reasons),
    )
    return repaired, report


def run_self_scan_repair(
    payload: dict[str, Any],
    *,
    max_iterations: int = 8,
) -> tuple[dict[str, Any], dict[str, Any], list[ScanReport]]:
    center_lat = float(payload["meta"]["centerLat"])
    center_lon = float(payload["meta"]["centerLon"])
    segments = parse_segments(payload)
    reports: list[ScanReport] = []
    for iteration in range(1, max_iterations + 1):
        repaired, report = scan_once(segments, center_lat=center_lat, center_lon=center_lon, iteration=iteration)
        reports.append(report)
        segments = repaired
        if report.anomaly_count == 0 or report.action_count == 0:
            break

    final_records, _ = endpoint_records(segments, center_lat=center_lat, center_lon=center_lon)
    _, final_snapped_count = cluster_endpoint_snaps(final_records, center_lat=center_lat, center_lon=center_lon)
    final_normalized_segments, final_normalize_reasons = normalize_same_side_corner_bridges(
        segments,
        center_lat=center_lat,
        center_lon=center_lon,
    )
    _, final_added_edges = connect_same_side_gaps(final_normalized_segments, center_lat=center_lat, center_lon=center_lon)
    final_remove, final_reasons = detect_removal_edges(final_normalized_segments, center_lat=center_lat, center_lon=center_lon)
    final_reasons.update(final_normalize_reasons)
    passed = final_snapped_count == 0 and final_added_edges == 0 and not final_remove
    final_report = {
        "passed": passed,
        "iterations": len(reports),
        "remainingActionableAnomalies": final_snapped_count + final_added_edges + len(final_remove) + sum(final_normalize_reasons.values()),
        "remainingSameSideGapConnects": final_added_edges,
        "remainingRemovalReasons": dict(final_reasons),
        "reports": [report.__dict__ for report in reports],
    }
    return {"segments": segments}, final_report, reports
