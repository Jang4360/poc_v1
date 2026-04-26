from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import median
from typing import Any, Iterable

import shapefile
from pyproj import Geod, Transformer
from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import nearest_points, substring, unary_union
from shapely.strtree import STRtree

from etl.common.centerline_loader import (
    DBF_ENCODINGS,
    DisjointSet,
    cluster_endpoint_indices,
    dedupe_consecutive_coords,
    line_length_meter,
    node_key,
    part_ranges,
    projected_length_meter,
    split_projected_segment,
)
from etl.common.db import connect, ewkt, insert_row


ROOT_DIR = Path(__file__).resolve().parents[2]
ETL_DIR = ROOT_DIR / "etl"
RAW_DIR = ETL_DIR / "raw"
RUNTIME_DIR = ROOT_DIR / "runtime" / "etl" / "side-graph-load-02b"
SHP_BASENAME = "N3L_A0020000_26"
NODE_SNAPSHOT = RUNTIME_DIR / "road_nodes_snapshot.csv"
SEGMENT_SNAPSHOT = RUNTIME_DIR / "road_segments_snapshot.csv"
SNAPSHOT_REPORT = RUNTIME_DIR / "side_graph_snapshot.json"
TOPOLOGY_REPORT = RUNTIME_DIR / "side_graph_topology_audit.json"
POST_LOAD_REPORT = RUNTIME_DIR / "side_graph_post_load_report.json"
PREVIEW_GEOJSON = ETL_DIR / "segment.geojson"
PREVIEW_HTML = ETL_DIR / "segment.html"
CROSSWALK_CSV = RAW_DIR / "stg_crosswalks_ready.csv"
ELEVATOR_CSV = RAW_DIR / "subway_elevator.csv"

TM5179_TO_WGS84 = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)
WGS84_TO_TM5179 = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
GEOD = Geod(ellps="GRS80")

SNAP_TOLERANCE_M = 2.0
NODE_MERGE_TOLERANCE_M = 0.5
JUNCTION_MERGE_RADIUS_M = 2.5
JUNCTION_POCKET_RADIUS_M = 3.0
POST_BRIDGE_POCKET_TAIL_PRUNE_M = 3.0
MIN_SPLIT_GAP_M = 0.05
OFFSET_FLOOR_M = 1.0
STUB_MAX_LENGTH_M = 1.0
CROSS_TYPE_TAIL_PRUNE_M = 5.0
JUNCTION_MERGE_ARTIFACT_PRUNE_M = 0.5
CROSS_TYPE_TAIL_PRUNE_M = 5.0
TRANSITION_CONNECTOR_MAX_M = 40.0
GAP_GROUP_MAX_M = 18.0
GAP_GROUP_ENDPOINT_NEAR_M = 10.0
GAP_BRIDGE_MAX_M = 12.0
GAP_BRIDGE_MAX_ANGLE_DEG = 110.0
CORNER_BRIDGE_ROOT_FACTOR = 3.0
CORNER_BRIDGE_ROOT_NEAR_FACTOR = 1.5
CORNER_BRIDGE_MIN_M = 25.0
CORNER_BRIDGE_HARD_CAP_M = 60.0
CORNER_ARM_MERGE_ANGLE_DEG = 18.0
CROSSWALK_ATTACH_MAX_M = 25.0
ELEVATOR_ATTACH_MAX_M = 60.0
CROSSWALK_PAIR_MAX_M = 60.0
TAIL_TRIM_MAX_M = 35.0
ENABLE_PRE_OFFSET_TAIL_TRIM = False
ENABLE_GAP_BRIDGES = False
INTERSECTION_NEAR_M = 2.0
TWO_LANE_MINIMUM_WIDTH_M = 5.5
SINGLE_LANE_THRESHOLD_M = round(TWO_LANE_MINIMUM_WIDTH_M * 0.8, 2)

LEFT_SEGMENT_TYPES = {"SIDE_LEFT"}
RIGHT_SEGMENT_TYPES = {"SIDE_RIGHT"}
TRAVERSABLE_TYPES = {"SIDE_LEFT", "SIDE_RIGHT"}
SIDE_SEGMENT_TYPES = {"SIDE_LEFT", "SIDE_RIGHT"}
CONNECTOR_SEGMENT_TYPES = {
    "GAP_BRIDGE",
    "SAME_SIDE_CORNER_BRIDGE",
    "CROSS_SIDE_CORNER_BRIDGE",
    "ELEVATOR_CONNECTOR",
}


@dataclass(frozen=True)
class SourceSegment:
    source_row_number: int
    source_ufid: str
    road_width_meter: float | None
    lane_count: int | None
    one_way: str | None
    coords: tuple[tuple[float, float], ...]

    @property
    def classification(self) -> str:
        if self.lane_count is not None and self.lane_count <= 1:
            return "CENTERLINE"
        if self.road_width_meter is not None and self.road_width_meter < SINGLE_LANE_THRESHOLD_M:
            return "CENTERLINE"
        return "MULTI_LANE"

    def with_coords(self, coords: tuple[tuple[float, float], ...]) -> "SourceSegment":
        return replace(self, coords=coords)


@dataclass(frozen=True)
class TempSegment:
    temp_id: int
    source_row_number: int
    source_ufid: str
    road_width_meter: float | None
    lane_count: int | None
    classification: str
    from_root: int
    to_root: int
    coords: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class Chain:
    chain_id: int
    classification: str
    start_root: int
    end_root: int
    coords: tuple[tuple[float, float], ...]
    segment_ids: tuple[int, ...]
    road_width_meter: float | None
    lane_count: int | None


@dataclass(frozen=True)
class BaseLine:
    line_id: str
    segment_type: str
    chain_id: int | None
    coords: tuple[tuple[float, float], ...]
    road_width_meter: float | None


@dataclass(frozen=True)
class TransitionSite:
    chain_id: int
    root: int
    candidate_chain_ids: tuple[int, ...]


@dataclass(frozen=True)
class Connector:
    connector_id: str
    segment_type: str
    coords: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class EventPoint:
    line_id: str
    point: tuple[float, float]
    node_type: str
    split_segment_types: tuple[str, ...]


@dataclass(frozen=True)
class IntersectionSector:
    root: int
    sector_index: int
    start_angle_rad: float
    end_angle_rad: float
    bisector_angle_rad: float


@dataclass(frozen=True)
class EndpointSectorAssignment:
    line_id: str
    segment_type: str
    endpoint_index: int
    point: tuple[float, float]
    outward: tuple[float, float] | None
    root: int
    sector_index: int


@dataclass(frozen=True)
class JunctionAnchorPlan:
    root: int
    archetype: str
    anchors_by_sector: dict[int, tuple[float, float]]
    single_anchor: tuple[float, float] | None = None


@dataclass(frozen=True)
class IntersectionClipIndex:
    root_ids: tuple[int, ...]
    buffers: tuple[Any, ...]
    tree: STRtree | None


@dataclass(frozen=True)
class NodeSnapshot:
    vertex_id: int
    source_node_key: str
    lon: float
    lat: float
    node_type: str
    degree: int

    @property
    def point_ewkt(self) -> str:
        return f"SRID=4326;POINT({self.lon:.8f} {self.lat:.8f})"


@dataclass(frozen=True)
class SegmentSnapshot:
    edge_id: int
    from_node_id: int
    to_node_id: int
    length_meter: float
    coords: tuple[tuple[float, float], ...]
    segment_type: str

    @property
    def geom_ewkt(self) -> str:
        coords_text = ", ".join(f"{lon:.8f} {lat:.8f}" for lon, lat in self.coords)
        return f"SRID=4326;LINESTRING({coords_text})"


def projected_segments_to_base_lines(
    projected_segments: list[tuple[str, tuple[tuple[float, float], ...]]],
) -> list[BaseLine]:
    return [
        BaseLine(
            line_id=f"resolved:{index}:{segment_type}",
            segment_type=segment_type,
            chain_id=index,
            coords=coords,
            road_width_meter=None,
        )
        for index, (segment_type, coords) in enumerate(projected_segments, start=1)
    ]


def ensure_runtime_dir() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def open_reader() -> tuple[shapefile.Reader, str]:
    shp_path = str(RAW_DIR / f"{SHP_BASENAME}.shp")
    last_error: UnicodeDecodeError | None = None
    for encoding in DBF_ENCODINGS:
        try:
            reader = shapefile.Reader(shp_path, encoding=encoding)
            if len(reader) > 0:
                reader.record(0)
            return reader, encoding
        except UnicodeDecodeError as exc:
            last_error = exc
    raise UnicodeDecodeError(
        last_error.encoding if last_error else "unknown",
        last_error.object if last_error else b"",
        last_error.start if last_error else 0,
        last_error.end if last_error else 0,
        f"failed to decode DBF with {', '.join(DBF_ENCODINGS)}",
    )


def transform_projected_point(point: tuple[float, float]) -> tuple[float, float]:
    lon, lat = TM5179_TO_WGS84.transform(point[0], point[1])
    return float(lon), float(lat)


def transform_projected_coords(points: Iterable[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
    source_points = list(points)
    if not source_points:
        return ()
    xs = [point[0] for point in source_points]
    ys = [point[1] for point in source_points]
    lons, lats = TM5179_TO_WGS84.transform(xs, ys)
    return tuple((float(lon), float(lat)) for lon, lat in zip(lons, lats))


def point_distance_meter(left: tuple[float, float], right: tuple[float, float]) -> float:
    return math.hypot(right[0] - left[0], right[1] - left[1])


def rounded_projected_point(point: tuple[float, float], *, precision: int = 3) -> tuple[float, float]:
    return (round(point[0], precision), round(point[1], precision))


def geodesic_distance_meter(left: tuple[float, float], right: tuple[float, float]) -> float:
    return abs(float(GEOD.line_length([left[0], right[0]], [left[1], right[1]])))


def line_to_parts(geometry: Any) -> list[LineString]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, LineString):
        return [geometry] if geometry.length > MIN_SPLIT_GAP_M else []
    if isinstance(geometry, MultiLineString):
        return [part for part in geometry.geoms if part.length > MIN_SPLIT_GAP_M]
    if hasattr(geometry, "geoms"):
        parts: list[LineString] = []
        for geom in geometry.geoms:
            parts.extend(line_to_parts(geom))
        return parts
    return []


def _collect_line_intersection_points(geometry: Any) -> list[Point]:
    return _collect_intersection_points(geometry)


def normalize_csv_header(value: str | None) -> str:
    return (value or "").strip().strip('"')


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    for encoding in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
        try:
            with path.open("r", encoding=encoding, newline="") as fh:
                reader = csv.DictReader(fh)
                return [
                    {normalize_csv_header(key): (value or "").strip() for key, value in row.items()}
                    for row in reader
                ]
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("unknown", b"", 0, 0, f"unable to decode {path}")


def parse_optional_float(value: str | None) -> float | None:
    try:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if not text:
            return None
        return float(text)
    except (TypeError, ValueError):
        return None


def parse_optional_int(value: str | None) -> int | None:
    try:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        text = str(value).strip()
        if not text:
            return None
        return int(float(text))
    except (TypeError, ValueError):
        return None


def point_to_bbox_distance_meter(point: tuple[float, float], bbox: list[float]) -> float:
    x, y = point
    min_x, min_y, max_x, max_y = bbox
    dx = 0.0 if min_x <= x <= max_x else min(abs(x - min_x), abs(x - max_x))
    dy = 0.0 if min_y <= y <= max_y else min(abs(y - min_y), abs(y - max_y))
    return math.hypot(dx, dy)


def build_source_segments(
    *,
    center_lat: float | None = None,
    center_lon: float | None = None,
    radius_m: int | None = None,
) -> tuple[list[SourceSegment], dict[str, Any]]:
    reader, encoding = open_reader()
    fields = [field[0] for field in reader.fields[1:]]
    ufid_index = fields.index("UFID")
    lane_index = fields.index("RDLN")
    width_index = fields.index("RVWD")
    one_way_index = fields.index("ONSD")

    center_projected: tuple[float, float] | None = None
    if center_lat is not None and center_lon is not None and radius_m is not None:
        x, y = WGS84_TO_TM5179.transform(center_lon, center_lat)
        center_projected = (float(x), float(y))

    segments: list[SourceSegment] = []
    skipped_by_radius = 0

    for row_number, shape_record in enumerate(reader.iterShapeRecords(), start=1):
        shape = shape_record.shape
        if center_projected is not None and point_to_bbox_distance_meter(center_projected, shape.bbox) > radius_m + 120.0:
            skipped_by_radius += 1
            continue
        record = shape_record.record
        road_width = parse_optional_float(record[width_index])
        lane_count = parse_optional_int(record[lane_index])
        one_way = (record[one_way_index] or "").strip() or None
        source_ufid = (record[ufid_index] or "").strip()
        for start, end in part_ranges(shape):
            coords = dedupe_consecutive_coords(tuple((float(x), float(y)) for x, y in shape.points[start:end]))
            if len(coords) < 2 or projected_length_meter(coords) <= 0:
                continue
            if center_projected is not None:
                line = LineString(coords)
                if line.distance(Point(center_projected)) > radius_m + 80.0:
                    continue
            segments.append(
                SourceSegment(
                    source_row_number=row_number,
                    source_ufid=source_ufid,
                    road_width_meter=road_width,
                    lane_count=lane_count,
                    one_way=one_way,
                    coords=coords,
                )
            )

    report = {
        "dataset": SHP_BASENAME,
        "sourceShapeCount": len(reader),
        "sourceSegmentCount": len(segments),
        "encoding": encoding,
        "radiusFilterMeter": radius_m,
        "skippedShapesByRadius": skipped_by_radius,
    }
    return segments, report


def normalize_source_segments(
    segments: list[SourceSegment],
    *,
    snap_tolerance_meter: float = SNAP_TOLERANCE_M,
) -> tuple[list[SourceSegment], dict[str, Any]]:
    if not segments:
        return [], {
            "normalizedSourceSegmentCount": 0,
            "snappedEndpointCount": 0,
            "splitInsertions": 0,
        }

    lines = [LineString(segment.coords) for segment in segments]
    tree = STRtree(lines)
    endpoint_overrides: dict[tuple[int, int], tuple[float, float]] = {}
    split_points_by_segment: dict[int, list[tuple[float, float]]] = defaultdict(list)
    snapped_endpoint_count = 0

    for segment_index, segment in enumerate(segments):
        for endpoint_index, endpoint in enumerate((segment.coords[0], segment.coords[-1])):
            point = Point(endpoint)
            best: tuple[float, int, tuple[float, float]] | None = None
            for candidate_index in tree.query(point.buffer(snap_tolerance_meter)):
                candidate_index = int(candidate_index)
                if candidate_index == segment_index:
                    continue
                candidate_line = lines[candidate_index]
                distance_along = float(candidate_line.project(point))
                if distance_along <= MIN_SPLIT_GAP_M or distance_along >= candidate_line.length - MIN_SPLIT_GAP_M:
                    continue
                snapped = candidate_line.interpolate(distance_along)
                distance_to_line = float(point.distance(snapped))
                if distance_to_line > snap_tolerance_meter:
                    continue
                snapped_point = (float(snapped.x), float(snapped.y))
                candidate = (distance_to_line, candidate_index, snapped_point)
                if best is None or candidate < best:
                    best = candidate
            if best is None:
                continue
            _, candidate_index, snapped_point = best
            if point_distance_meter(snapped_point, endpoint) <= MIN_SPLIT_GAP_M:
                continue
            endpoint_overrides[(segment_index, endpoint_index)] = snapped_point
            split_points_by_segment[candidate_index].append(snapped_point)
            snapped_endpoint_count += 1

    normalized: list[SourceSegment] = []
    split_insertions = 0
    for segment_index, segment in enumerate(segments):
        adjusted_coords = list(segment.coords)
        if (segment_index, 0) in endpoint_overrides:
            adjusted_coords[0] = endpoint_overrides[(segment_index, 0)]
        if (segment_index, 1) in endpoint_overrides:
            adjusted_coords[-1] = endpoint_overrides[(segment_index, 1)]
        pieces = split_projected_segment(tuple(adjusted_coords), split_points_by_segment.get(segment_index, ()))
        split_insertions += max(0, len(pieces) - 1)
        for piece in pieces:
            normalized.append(segment.with_coords(piece))

    return normalized, {
        "normalizedSourceSegmentCount": len(normalized),
        "snappedEndpointCount": snapped_endpoint_count,
        "splitInsertions": split_insertions,
    }


def build_temp_graph(segments: list[SourceSegment]) -> tuple[list[TempSegment], dict[int, tuple[float, float]], dict[int, int], dict[int, set[int]]]:
    projected_segments = [segment.coords for segment in segments]
    endpoint_clusters = cluster_endpoint_indices(projected_segments, NODE_MERGE_TOLERANCE_M)
    endpoint_coords = [endpoint for coords in projected_segments for endpoint in (coords[0], coords[-1])]

    endpoint_root_by_index: dict[int, int] = {}
    cluster_centers: dict[int, tuple[float, float]] = {}
    for root, members in endpoint_clusters.items():
        for member in members:
            endpoint_root_by_index[member] = root
        cluster_centers[root] = (
            sum(endpoint_coords[index][0] for index in members) / len(members),
            sum(endpoint_coords[index][1] for index in members) / len(members),
        )

    temp_segments: list[TempSegment] = []
    node_degree: Counter[int] = Counter()
    adjacency: dict[int, set[int]] = defaultdict(set)
    for index, segment in enumerate(segments, start=1):
        from_root = endpoint_root_by_index[(index - 1) * 2]
        to_root = endpoint_root_by_index[(index - 1) * 2 + 1]
        coords = dedupe_consecutive_coords((cluster_centers[from_root], *segment.coords[1:-1], cluster_centers[to_root]))
        if len(coords) < 2 or projected_length_meter(coords) <= MIN_SPLIT_GAP_M:
            continue
        temp_segment = TempSegment(
            temp_id=index,
            source_row_number=segment.source_row_number,
            source_ufid=segment.source_ufid,
            road_width_meter=segment.road_width_meter,
            lane_count=segment.lane_count,
            classification=segment.classification,
            from_root=from_root,
            to_root=to_root,
            coords=coords,
        )
        temp_segments.append(temp_segment)
        node_degree[from_root] += 1
        node_degree[to_root] += 1
        adjacency[from_root].add(index)
        adjacency[to_root].add(index)
    return temp_segments, cluster_centers, dict(node_degree), adjacency


def compute_intersection_roots(
    temp_segments: list[TempSegment],
    cluster_centers: dict[int, tuple[float, float]],
    node_degree: dict[int, int],
) -> tuple[set[int], dict[int, float]]:
    width_candidates: dict[int, list[float]] = defaultdict(list)
    for segment in temp_segments:
        if segment.road_width_meter and segment.road_width_meter > 0:
            width_candidates[segment.from_root].append(segment.road_width_meter)
            width_candidates[segment.to_root].append(segment.road_width_meter)
    intersection_roots = {root for root, degree in node_degree.items() if degree >= 3}
    radii = {
        root: max((max(width_candidates.get(root, [0.0])) / 2.0), OFFSET_FLOOR_M)
        for root in cluster_centers
    }
    return intersection_roots, radii


def build_chains(
    temp_segments: list[TempSegment],
    node_degree: dict[int, int],
    adjacency: dict[int, set[int]],
    intersection_roots: set[int],
) -> list[Chain]:
    segments_by_id = {segment.temp_id: segment for segment in temp_segments}
    visited: set[int] = set()
    chains: list[Chain] = []

    def continuation_candidates(root: int, current_segment_id: int, classification: str) -> list[int]:
        return [
            candidate
            for candidate in adjacency.get(root, set())
            if candidate != current_segment_id and segments_by_id[candidate].classification == classification
        ]

    def should_stop(root: int, current_segment_id: int, classification: str) -> bool:
        if root in intersection_roots:
            return True
        if node_degree.get(root, 0) != 2:
            return True
        return len(continuation_candidates(root, current_segment_id, classification)) != 1

    for segment in temp_segments:
        if segment.temp_id in visited:
            continue
        classification = segment.classification
        endpoints = [segment.from_root, segment.to_root]
        stop_flags = [should_stop(endpoints[0], segment.temp_id, classification), should_stop(endpoints[1], segment.temp_id, classification)]
        start_root = endpoints[0] if stop_flags[0] or not stop_flags[1] else endpoints[1]
        current_segment = segment
        current_root = start_root
        chain_coords: list[tuple[float, float]] = []
        chain_segment_ids: list[int] = []
        widths: list[float] = []
        lane_counts: list[int] = []

        while True:
            visited.add(current_segment.temp_id)
            coords = current_segment.coords if current_segment.from_root == current_root else tuple(reversed(current_segment.coords))
            chain_coords.extend(coords if not chain_coords else coords[1:])
            chain_segment_ids.append(current_segment.temp_id)
            if current_segment.road_width_meter and current_segment.road_width_meter > 0:
                widths.append(current_segment.road_width_meter)
            if current_segment.lane_count is not None:
                lane_counts.append(current_segment.lane_count)
            next_root = current_segment.to_root if current_segment.from_root == current_root else current_segment.from_root
            candidates = continuation_candidates(next_root, current_segment.temp_id, classification)
            if should_stop(next_root, current_segment.temp_id, classification):
                chains.append(
                    Chain(
                        chain_id=len(chains) + 1,
                        classification=classification,
                        start_root=start_root,
                        end_root=next_root,
                        coords=dedupe_consecutive_coords(tuple(chain_coords)),
                        segment_ids=tuple(chain_segment_ids),
                        road_width_meter=float(median(widths)) if widths else None,
                        lane_count=int(round(median(lane_counts))) if lane_counts else None,
                    )
                )
                break
            next_segment_id = candidates[0]
            current_root = next_root
            current_segment = segments_by_id[next_segment_id]
            if current_segment.temp_id in visited:
                chains.append(
                    Chain(
                        chain_id=len(chains) + 1,
                        classification=classification,
                        start_root=start_root,
                        end_root=next_root,
                        coords=dedupe_consecutive_coords(tuple(chain_coords)),
                        segment_ids=tuple(chain_segment_ids),
                        road_width_meter=float(median(widths)) if widths else None,
                        lane_count=int(round(median(lane_counts))) if lane_counts else None,
                    )
                )
                break
    return chains


def build_intersection_union(cluster_centers: dict[int, tuple[float, float]], intersection_roots: set[int], radii: dict[int, float]) -> Any:
    if not intersection_roots:
        return None
    return unary_union([Point(cluster_centers[root]).buffer(radii[root]) for root in intersection_roots])


def build_intersection_clip_index(
    cluster_centers: dict[int, tuple[float, float]],
    intersection_roots: set[int],
    radii: dict[int, float],
) -> IntersectionClipIndex:
    root_ids = tuple(intersection_roots)
    buffers = tuple(Point(cluster_centers[root]).buffer(radii[root]) for root in root_ids)
    return IntersectionClipIndex(
        root_ids=root_ids,
        buffers=buffers,
        tree=STRtree(list(buffers)) if buffers else None,
    )


def _local_intersection_union(geometry: Any, intersection_source: Any) -> Any:
    if isinstance(intersection_source, IntersectionClipIndex):
        if intersection_source.tree is None:
            return None
        candidate_indexes = list(intersection_source.tree.query(geometry))
        if not candidate_indexes:
            return None
        candidates = [
            intersection_source.buffers[int(index)]
            for index in candidate_indexes
            if geometry.intersects(intersection_source.buffers[int(index)])
        ]
        if not candidates:
            return None
        return candidates[0] if len(candidates) == 1 else unary_union(candidates)
    return intersection_source


def _point_near_intersection(point: tuple[float, float], intersection_source: Any, distance_meter: float) -> bool:
    point_geom = Point(point)
    if isinstance(intersection_source, IntersectionClipIndex):
        if intersection_source.tree is None:
            return False
        for candidate_index in intersection_source.tree.query(point_geom.buffer(distance_meter)):
            buffer = intersection_source.buffers[int(candidate_index)]
            if point_geom.distance(buffer) <= distance_meter:
                return True
        return False
    return intersection_source is not None and not intersection_source.is_empty and point_geom.distance(intersection_source) <= distance_meter


def offset_line(coords: tuple[tuple[float, float], ...], distance_meter: float, *, side: str) -> list[tuple[tuple[float, float], ...]]:
    line = LineString(coords)
    if line.length <= MIN_SPLIT_GAP_M:
        return []
    distance = distance_meter if side == "left" else -distance_meter
    offset_geom = line.offset_curve(distance)
    pieces: list[tuple[tuple[float, float], ...]] = []
    for part in line_to_parts(offset_geom):
        coords_part = dedupe_consecutive_coords(tuple((float(x), float(y)) for x, y in part.coords))
        if len(coords_part) >= 2 and projected_length_meter(coords_part) > STUB_MAX_LENGTH_M:
            pieces.append(coords_part)
    return pieces


def clip_to_intersection_free_parts(parts: list[tuple[tuple[float, float], ...]], intersection_union: Any) -> list[tuple[tuple[float, float], ...]]:
    results: list[tuple[tuple[float, float], ...]] = []
    for part in parts:
        geom: Any = LineString(part)
        local_intersection_union = _local_intersection_union(geom, intersection_union)
        if local_intersection_union is not None and not local_intersection_union.is_empty:
            geom = geom.difference(local_intersection_union)
        for clipped in line_to_parts(geom):
            coords = dedupe_consecutive_coords(tuple((float(x), float(y)) for x, y in clipped.coords))
            if len(coords) >= 2 and projected_length_meter(coords) > STUB_MAX_LENGTH_M:
                results.append(coords)
    return results


def build_base_lines(
    chains: list[Chain],
    cluster_centers: dict[int, tuple[float, float]],
    intersection_roots: set[int],
    radii: dict[int, float],
    transition_roots_by_chain: dict[int, set[int]],
) -> tuple[list[BaseLine], dict[int, list[str]]]:
    intersection_union = build_intersection_clip_index(cluster_centers, intersection_roots, radii)
    base_lines: list[BaseLine] = []
    line_ids_by_chain: dict[int, list[str]] = defaultdict(list)

    for chain in chains:
        offset_meter = max((chain.road_width_meter or 0.0) / 2.0, OFFSET_FLOOR_M)
        left_parts = clip_to_intersection_free_parts(offset_line(chain.coords, offset_meter, side="left"), intersection_union)
        right_parts = clip_to_intersection_free_parts(offset_line(chain.coords, offset_meter, side="right"), intersection_union)
        for side_name, parts in (("SIDE_LEFT", left_parts), ("SIDE_RIGHT", right_parts)):
            for part_index, part in enumerate(parts, start=1):
                line_id = f"chain:{chain.chain_id}:{side_name}:{part_index}"
                base_lines.append(
                    BaseLine(
                        line_id=line_id,
                        segment_type=side_name,
                        chain_id=chain.chain_id,
                        coords=part,
                        road_width_meter=chain.road_width_meter,
                    )
                )
                line_ids_by_chain[chain.chain_id].append(line_id)
    # 02B handles short tails in staged post-split/post-bridge passes. The older
    # broad same-side pre-trim is expensive on 5km extracts and duplicates that responsibility.
    trimmed_lines = trim_side_line_tails(base_lines, intersection_union) if ENABLE_PRE_OFFSET_TAIL_TRIM else base_lines
    trimmed_ids_by_chain: dict[int, list[str]] = defaultdict(list)
    for line in trimmed_lines:
        if line.chain_id is not None:
            trimmed_ids_by_chain[line.chain_id].append(line.line_id)
    return trimmed_lines, trimmed_ids_by_chain


def trim_centerline_for_transition(
    chain: Chain,
    cluster_centers: dict[int, tuple[float, float]],
    radii: dict[int, float],
    transition_roots_by_chain: dict[int, set[int]],
) -> tuple[tuple[float, float], ...]:
    transition_roots = transition_roots_by_chain.get(chain.chain_id, set())
    if not transition_roots:
        return chain.coords

    line = LineString(chain.coords)
    trim_buffers = [Point(cluster_centers[root]).buffer(max(radii.get(root, OFFSET_FLOOR_M), OFFSET_FLOOR_M)) for root in transition_roots]
    trimmed = line.difference(unary_union(trim_buffers))
    parts = line_to_parts(trimmed)
    if not parts:
        return chain.coords
    longest = max(parts, key=lambda part: part.length)
    coords = dedupe_consecutive_coords(tuple((float(x), float(y)) for x, y in longest.coords))
    if len(coords) < 2 or projected_length_meter(coords) <= STUB_MAX_LENGTH_M:
        return chain.coords
    return coords


def _collect_intersection_points(geometry: Any) -> list[Point]:
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Point":
        return [geometry]
    if geometry.geom_type == "MultiPoint":
        return list(geometry.geoms)
    if geometry.geom_type == "GeometryCollection":
        points: list[Point] = []
        for geom in geometry.geoms:
            points.extend(_collect_intersection_points(geom))
        return points
    return []


def trim_side_line_tails(base_lines: list[BaseLine], intersection_union: Any) -> list[BaseLine]:
    if intersection_union is None:
        return base_lines
    if not isinstance(intersection_union, IntersectionClipIndex) and intersection_union.is_empty:
        return base_lines
    if isinstance(intersection_union, IntersectionClipIndex) and not intersection_union.buffers:
        return base_lines

    trimmed_lines: list[BaseLine] = []
    side_types = ("SIDE_LEFT", "SIDE_RIGHT")
    lines_by_side = {
        side_type: [line for line in base_lines if line.segment_type == side_type]
        for side_type in side_types
    }
    line_geometries_by_side = {
        side_type: [LineString(line.coords) for line in lines_by_side[side_type]]
        for side_type in side_types
    }
    trees_by_side = {
        side_type: STRtree(line_geometries_by_side[side_type]) if line_geometries_by_side[side_type] else None
        for side_type in side_types
    }

    for line in base_lines:
        if line.segment_type not in side_types:
            trimmed_lines.append(line)
            continue

        geometry = LineString(line.coords)
        same_side_lines = lines_by_side[line.segment_type]
        same_side_geometries = line_geometries_by_side[line.segment_type]
        same_side_tree = trees_by_side[line.segment_type]
        cut_distances: list[float] = []
        start_near_intersection = _point_near_intersection(line.coords[0], intersection_union, INTERSECTION_NEAR_M)
        end_near_intersection = _point_near_intersection(line.coords[-1], intersection_union, INTERSECTION_NEAR_M)

        if same_side_tree is None:
            trimmed_lines.append(line)
            continue

        for candidate_index in same_side_tree.query(geometry.buffer(TAIL_TRIM_MAX_M)):
            candidate_index = int(candidate_index)
            other_line = same_side_lines[candidate_index]
            if other_line.line_id == line.line_id:
                continue
            other_geometry = same_side_geometries[candidate_index]
            if not geometry.intersects(other_geometry) and not geometry.buffer(TAIL_TRIM_MAX_M).intersects(other_geometry):
                continue
            for point in _collect_intersection_points(geometry.intersection(other_geometry)):
                distance = float(geometry.project(point))
                if MIN_SPLIT_GAP_M < distance < geometry.length - MIN_SPLIT_GAP_M:
                    cut_distances.append(distance)

        if not cut_distances:
            trimmed_lines.append(line)
            continue

        start_distance = 0.0
        end_distance = float(geometry.length)
        if start_near_intersection:
            forward = [distance for distance in cut_distances if distance <= TAIL_TRIM_MAX_M]
            if forward:
                start_distance = min(forward)
        if end_near_intersection:
            backward = [distance for distance in cut_distances if geometry.length - distance <= TAIL_TRIM_MAX_M]
            if backward:
                end_distance = max(backward)

        if end_distance - start_distance <= STUB_MAX_LENGTH_M:
            continue

        if start_distance > 0 or end_distance < geometry.length:
            clipped = substring(geometry, start_distance, end_distance)
            coords = dedupe_consecutive_coords(tuple((float(x), float(y)) for x, y in clipped.coords))
            if len(coords) >= 2 and projected_length_meter(coords) > STUB_MAX_LENGTH_M:
                trimmed_lines.append(replace(line, coords=coords))
            continue

        trimmed_lines.append(line)

    return trimmed_lines


def prune_intersection_boundary_stubs(
    base_lines: list[BaseLine],
    cluster_centers: dict[int, tuple[float, float]],
    intersection_roots: set[int],
    intersection_radii: dict[int, float],
) -> tuple[list[BaseLine], int]:
    if not base_lines or not intersection_roots:
        return base_lines, 0

    root_points = [Point(cluster_centers[root]) for root in intersection_roots]
    root_ids = list(intersection_roots)
    root_tree = STRtree(root_points) if root_points else None
    kept: list[BaseLine] = []
    pruned = 0

    for line in base_lines:
        if line.segment_type not in LEFT_SEGMENT_TYPES | RIGHT_SEGMENT_TYPES:
            kept.append(line)
            continue
        length_meter = projected_length_meter(line.coords)
        if length_meter > STUB_MAX_LENGTH_M:
            kept.append(line)
            continue

        should_prune = False
        for endpoint in (line.coords[0], line.coords[-1]):
            if root_tree is None:
                continue
            for candidate_index in root_tree.query(Point(endpoint).buffer(STUB_MAX_LENGTH_M * 2.0)):
                root = root_ids[int(candidate_index)]
                if point_distance_meter(endpoint, cluster_centers[root]) <= intersection_radii.get(root, OFFSET_FLOOR_M) * 1.2:
                    should_prune = True
                    break
            if should_prune:
                break

        if should_prune:
            pruned += 1
            continue
        kept.append(line)

    return kept, pruned


def nearest_point_on_line(coords: tuple[tuple[float, float], ...], point: tuple[float, float]) -> tuple[tuple[float, float], float]:
    line = LineString(coords)
    snapped = line.interpolate(float(line.project(Point(point))))
    snapped_point = (float(snapped.x), float(snapped.y))
    return snapped_point, float(Point(point).distance(snapped))


def _vector_angle_deg(vec_a: tuple[float, float], vec_b: tuple[float, float]) -> float:
    mag_a = math.hypot(vec_a[0], vec_a[1])
    mag_b = math.hypot(vec_b[0], vec_b[1])
    if mag_a <= 0 or mag_b <= 0:
        return 180.0
    cos_value = max(-1.0, min(1.0, ((vec_a[0] * vec_b[0]) + (vec_a[1] * vec_b[1])) / (mag_a * mag_b)))
    return math.degrees(math.acos(cos_value))


def _angle_rad(origin: tuple[float, float], point: tuple[float, float]) -> float:
    angle = math.atan2(point[1] - origin[1], point[0] - origin[0])
    return angle if angle >= 0 else angle + (2 * math.pi)


def _angle_in_sector(angle_rad: float, start_angle_rad: float, end_angle_rad: float) -> bool:
    if start_angle_rad <= end_angle_rad:
        return start_angle_rad <= angle_rad <= end_angle_rad
    return angle_rad >= start_angle_rad or angle_rad <= end_angle_rad


def _sector_bisector(start_angle_rad: float, end_angle_rad: float) -> float:
    start = start_angle_rad
    end = end_angle_rad
    if end < start:
        end += 2 * math.pi
    bisector = (start + end) / 2.0
    return bisector if bisector < 2 * math.pi else bisector - (2 * math.pi)


def _endpoint_outward_vector(coords: tuple[tuple[float, float], ...], *, endpoint_index: int) -> tuple[float, float] | None:
    if len(coords) < 2:
        return None
    if endpoint_index == 0:
        anchor = coords[0]
        for candidate in coords[1:]:
            if point_distance_meter(anchor, candidate) > MIN_SPLIT_GAP_M:
                return (anchor[0] - candidate[0], anchor[1] - candidate[1])
        return None
    anchor = coords[-1]
    for candidate in reversed(coords[:-1]):
        if point_distance_meter(anchor, candidate) > MIN_SPLIT_GAP_M:
            return (anchor[0] - candidate[0], anchor[1] - candidate[1])
    return None


def _distance_to_line_endpoints(coords: tuple[tuple[float, float], ...], point: tuple[float, float]) -> float:
    return min(point_distance_meter(coords[0], point), point_distance_meter(coords[-1], point))


def _is_barrier_free_segment(
    start: tuple[float, float],
    end: tuple[float, float],
    barrier_tree: STRtree | None,
    barrier_geometries: list[LineString],
) -> bool:
    if point_distance_meter(start, end) <= MIN_SPLIT_GAP_M:
        return True
    bridge = LineString((start, end))
    tolerance = max(MIN_SPLIT_GAP_M, 0.25)
    candidate_indexes = range(len(barrier_geometries)) if barrier_tree is None else barrier_tree.query(bridge.buffer(tolerance))
    for candidate_index in candidate_indexes:
        barrier = barrier_geometries[int(candidate_index)]
        intersection = bridge.intersection(barrier)
        if intersection.is_empty:
            continue
        if intersection.geom_type in {"LineString", "MultiLineString"}:
            return False
        for point in _collect_intersection_points(intersection):
            if point_distance_meter(start, (float(point.x), float(point.y))) <= tolerance:
                continue
            if point_distance_meter(end, (float(point.x), float(point.y))) <= tolerance:
                continue
            return False
    return True


def build_side_corridor_groups(
    side_lines: list[BaseLine],
    barrier_geometries_by_side: dict[str, list[LineString]],
    barrier_trees_by_side: dict[str, STRtree | None],
) -> dict[str, int]:
    if not side_lines:
        return {}
    geometries = [LineString(line.coords) for line in side_lines]
    tree = STRtree(geometries)
    dsu = DisjointSet()
    for index in range(len(side_lines)):
        dsu.find(index)

    for index, line in enumerate(side_lines):
        geometry = geometries[index]
        for candidate_index in tree.query(geometry.buffer(GAP_GROUP_MAX_M)):
            candidate_index = int(candidate_index)
            if candidate_index <= index:
                continue
            other_line = side_lines[candidate_index]
            if other_line.segment_type != line.segment_type:
                continue
            point_a, point_b = nearest_points(geometry, geometries[candidate_index])
            point_a_coords = (float(point_a.x), float(point_a.y))
            point_b_coords = (float(point_b.x), float(point_b.y))
            if point_distance_meter(point_a_coords, point_b_coords) > GAP_GROUP_MAX_M:
                continue
            if line.chain_id != other_line.chain_id:
                near_a = _distance_to_line_endpoints(line.coords, point_a_coords) <= GAP_GROUP_ENDPOINT_NEAR_M
                near_b = _distance_to_line_endpoints(other_line.coords, point_b_coords) <= GAP_GROUP_ENDPOINT_NEAR_M
                if not (near_a and near_b):
                    continue
            if not _is_barrier_free_segment(
                point_a_coords,
                point_b_coords,
                barrier_trees_by_side.get(line.segment_type),
                barrier_geometries_by_side.get(line.segment_type, []),
            ):
                continue
            dsu.union(index, candidate_index)

    return {line.line_id: dsu.find(index) for index, line in enumerate(side_lines)}


def build_transition_sites(chains: list[Chain], temp_segments: list[TempSegment]) -> list[TransitionSite]:
    chain_by_segment_id = {segment_id: chain.chain_id for chain in chains for segment_id in chain.segment_ids}
    segments_by_root: dict[int, list[TempSegment]] = defaultdict(list)
    for segment in temp_segments:
        segments_by_root[segment.from_root].append(segment)
        segments_by_root[segment.to_root].append(segment)

    sites: list[TransitionSite] = []
    seen: set[tuple[int, int]] = set()
    for segment in temp_segments:
        if segment.classification != "CENTERLINE":
            continue
        chain_id = chain_by_segment_id[segment.temp_id]
        for root in (segment.from_root, segment.to_root):
            key = (chain_id, root)
            if key in seen:
                continue
            seen.add(key)
            candidate_chain_ids = sorted(
                {
                    chain_by_segment_id[other.temp_id]
                    for other in segments_by_root[root]
                    if other.classification == "MULTI_LANE"
                }
            )
            if candidate_chain_ids:
                sites.append(
                    TransitionSite(
                        chain_id=chain_id,
                        root=root,
                        candidate_chain_ids=tuple(candidate_chain_ids),
                    )
                )
    return sites


def build_intersection_sectors(
    temp_segments: list[TempSegment],
    cluster_centers: dict[int, tuple[float, float]],
    adjacency: dict[int, set[int]],
    intersection_roots: set[int],
) -> dict[int, list[IntersectionSector]]:
    segments_by_id = {segment.temp_id: segment for segment in temp_segments}
    sectors_by_root: dict[int, list[IntersectionSector]] = {}
    merge_tolerance_rad = math.radians(CORNER_ARM_MERGE_ANGLE_DEG)

    for root in intersection_roots:
        root_point = cluster_centers[root]
        arm_angles: list[float] = []
        for segment_id in adjacency.get(root, set()):
            segment = segments_by_id.get(segment_id)
            if segment is None:
                continue
            oriented_coords = segment.coords if segment.from_root == root else tuple(reversed(segment.coords))
            next_point = None
            for candidate in oriented_coords[1:]:
                if point_distance_meter(root_point, candidate) > MIN_SPLIT_GAP_M:
                    next_point = candidate
                    break
            if next_point is None:
                continue
            arm_angles.append(_angle_rad(root_point, next_point))

        if len(arm_angles) < 2:
            continue

        merged_angles: list[float] = []
        for angle in sorted(arm_angles):
            if not merged_angles:
                merged_angles.append(angle)
                continue
            if min(abs(angle - merged_angles[-1]), (2 * math.pi) - abs(angle - merged_angles[-1])) <= merge_tolerance_rad:
                merged_angles[-1] = (merged_angles[-1] + angle) / 2.0
            else:
                merged_angles.append(angle)
        if len(merged_angles) > 1 and min(abs((merged_angles[0] + (2 * math.pi)) - merged_angles[-1]), abs(merged_angles[0] - merged_angles[-1])) <= merge_tolerance_rad:
            first = merged_angles.pop(0)
            merged_angles[-1] = _sector_bisector(merged_angles[-1], first)

        if len(merged_angles) < 2:
            continue

        root_sectors: list[IntersectionSector] = []
        for index, start_angle in enumerate(merged_angles):
            end_angle = merged_angles[(index + 1) % len(merged_angles)]
            root_sectors.append(
                IntersectionSector(
                    root=root,
                    sector_index=index,
                    start_angle_rad=start_angle,
                    end_angle_rad=end_angle,
                    bisector_angle_rad=_sector_bisector(start_angle, end_angle),
                )
            )
        sectors_by_root[root] = root_sectors

    return sectors_by_root


def build_transition_connectors(
    transition_sites: list[TransitionSite],
    cluster_centers: dict[int, tuple[float, float]],
    base_lines: list[BaseLine],
    line_ids_by_chain: dict[int, list[str]],
) -> tuple[list[Connector], list[EventPoint]]:
    lines_by_id = {line.line_id: line for line in base_lines}

    connectors: list[Connector] = []
    events: list[EventPoint] = []
    for site in transition_sites:
        centerline_line_ids = [
            line_id
            for line_id in line_ids_by_chain.get(site.chain_id, [])
            if line_id in lines_by_id and lines_by_id[line_id].segment_type == "CENTERLINE"
        ]
        if not centerline_line_ids:
            continue
        centerline_line = lines_by_id[centerline_line_ids[0]]
        root_point = cluster_centers[site.root]
        center_candidates = (centerline_line.coords[0], centerline_line.coords[-1])
        center_point = min(center_candidates, key=lambda coord: point_distance_meter(coord, root_point))
        best_distance: float | None = None
        best_line: BaseLine | None = None
        best_attach_point: tuple[float, float] | None = None
        best_target_chain_id: int | None = None
        for target_chain_id in site.candidate_chain_ids:
            candidate_line_ids = [
                line_id
                for line_id in line_ids_by_chain.get(target_chain_id, [])
                if lines_by_id[line_id].segment_type in LEFT_SEGMENT_TYPES | RIGHT_SEGMENT_TYPES
            ]
            for line_id in candidate_line_ids:
                line = lines_by_id[line_id]
                snapped_point, distance_meter = nearest_point_on_line(line.coords, center_point)
                if best_distance is None or distance_meter < best_distance:
                    best_distance = distance_meter
                    best_line = line
                    best_attach_point = snapped_point
                    best_target_chain_id = target_chain_id
        if best_distance is None or best_line is None or best_attach_point is None or best_target_chain_id is None:
            continue
        if best_distance > TRANSITION_CONNECTOR_MAX_M:
            continue
        connectors.append(
            Connector(
                connector_id=f"transition:{site.root}:{site.chain_id}:{best_target_chain_id}",
                segment_type="TRANSITION_CONNECTOR",
                coords=(center_point, best_attach_point),
            )
        )
        events.append(
            EventPoint(
                line_id=best_line.line_id,
                point=best_attach_point,
                node_type="LANE_TRANSITION",
                split_segment_types=(best_line.segment_type,),
            )
        )
    return connectors, events


def build_gap_bridges(
    base_lines: list[BaseLine],
    *,
    cluster_centers: dict[int, tuple[float, float]] | None = None,
    intersection_roots: set[int] | None = None,
    intersection_radii: dict[int, float] | None = None,
    suppressed_endpoint_points: set[tuple[float, float]] | None = None,
    closed_single_node_roots: set[int] | None = None,
) -> tuple[list[Connector], list[EventPoint], dict[str, int]]:
    side_lines = [line for line in base_lines if line.segment_type in SIDE_SEGMENT_TYPES]
    if not side_lines:
        return [], [], {"gapBridgeCount": 0}

    side_geometries = [LineString(line.coords) for line in side_lines]
    side_tree = STRtree(side_geometries)
    barrier_geometries_by_side = {
        "SIDE_LEFT": [LineString(line.coords) for line in base_lines if line.segment_type in {"CENTERLINE", "SIDE_RIGHT"}],
        "SIDE_RIGHT": [LineString(line.coords) for line in base_lines if line.segment_type in {"CENTERLINE", "SIDE_LEFT"}],
    }
    barrier_trees_by_side = {
        side_type: STRtree(geometries) if geometries else None
        for side_type, geometries in barrier_geometries_by_side.items()
    }
    corridor_group_by_line_id = build_side_corridor_groups(side_lines, barrier_geometries_by_side, barrier_trees_by_side)

    connectors: list[Connector] = []
    events: list[EventPoint] = []
    used_source_endpoints: set[tuple[str, int]] = set()
    used_bridge_keys: set[tuple[tuple[float, float], tuple[float, float]]] = set()
    suppressed_endpoint_points = suppressed_endpoint_points or set()
    closed_single_node_roots = closed_single_node_roots or set()
    suppressed_inside_pocket_count = 0
    suppressed_by_claim_count = 0

    def should_suppress_gap_point(point: tuple[float, float]) -> bool:
        if rounded_projected_point(point) in suppressed_endpoint_points:
            return True
        if cluster_centers is None or not intersection_roots or not intersection_radii:
            return False
        for root in intersection_roots:
            radius = intersection_radii.get(root, OFFSET_FLOOR_M)
            suppression_radius = max(radius * CORNER_BRIDGE_ROOT_NEAR_FACTOR, OFFSET_FLOOR_M * 3.0) + JUNCTION_POCKET_RADIUS_M
            if point_distance_meter(point, cluster_centers[root]) <= suppression_radius:
                return root in closed_single_node_roots or point_distance_meter(point, cluster_centers[root]) <= max(radius, JUNCTION_POCKET_RADIUS_M)
        return False

    endpoint_candidates: list[tuple[int, BaseLine, int, tuple[float, float], tuple[float, float] | None]] = []
    for line_index, line in enumerate(side_lines):
        endpoint_candidates.append((line_index, line, 0, line.coords[0], _endpoint_outward_vector(line.coords, endpoint_index=0)))
        endpoint_candidates.append((line_index, line, 1, line.coords[-1], _endpoint_outward_vector(line.coords, endpoint_index=1)))

    created = 0
    for _, source_line, endpoint_index, source_point, outward in endpoint_candidates:
        if outward is None:
            continue
        if rounded_projected_point(source_point) in suppressed_endpoint_points:
            suppressed_by_claim_count += 1
            continue
        if cluster_centers is not None and intersection_roots and intersection_radii:
            near_intersection = False
            for root in intersection_roots:
                radius = intersection_radii.get(root, OFFSET_FLOOR_M)
                suppression_radius = max(radius * CORNER_BRIDGE_ROOT_NEAR_FACTOR, OFFSET_FLOOR_M * 3.0) + JUNCTION_POCKET_RADIUS_M
                if point_distance_meter(source_point, cluster_centers[root]) <= suppression_radius:
                    near_intersection = True
                    break
            if near_intersection:
                suppressed_inside_pocket_count += 1
                continue
        source_endpoint_key = (source_line.line_id, endpoint_index)
        if source_endpoint_key in used_source_endpoints:
            continue
        source_group = corridor_group_by_line_id.get(source_line.line_id)
        if source_group is None:
            continue

        best: tuple[float, int, BaseLine, tuple[float, float], bool] | None = None
        for candidate_index in side_tree.query(Point(source_point).buffer(GAP_BRIDGE_MAX_M)):
            candidate_index = int(candidate_index)
            target_line = side_lines[candidate_index]
            if target_line.line_id == source_line.line_id or target_line.segment_type != source_line.segment_type:
                continue
            if corridor_group_by_line_id.get(target_line.line_id) != source_group:
                continue
            attach_point, distance_meter = nearest_point_on_line(target_line.coords, source_point)
            if distance_meter <= MIN_SPLIT_GAP_M or distance_meter > GAP_BRIDGE_MAX_M:
                continue
            if should_suppress_gap_point(attach_point):
                suppressed_by_claim_count += 1
                continue
            bridge_vec = (attach_point[0] - source_point[0], attach_point[1] - source_point[1])
            if _vector_angle_deg(outward, bridge_vec) > GAP_BRIDGE_MAX_ANGLE_DEG:
                continue
            if not _is_barrier_free_segment(
                source_point,
                attach_point,
                barrier_trees_by_side.get(source_line.segment_type),
                barrier_geometries_by_side.get(source_line.segment_type, []),
            ):
                continue
            source_same_chain = 0 if source_line.chain_id is not None and target_line.chain_id is not None and source_line.chain_id == target_line.chain_id else 1
            target_endpoint_distance = _distance_to_line_endpoints(target_line.coords, attach_point)
            attachs_to_endpoint = target_endpoint_distance <= MIN_SPLIT_GAP_M
            candidate = (distance_meter, source_same_chain, target_line, attach_point, attachs_to_endpoint)
            if best is None or candidate[:2] < best[:2]:
                best = candidate

        if best is None:
            continue

        _, _, target_line, attach_point, attachs_to_endpoint = best
        bridge_key = tuple(sorted((rounded_projected_point(source_point), rounded_projected_point(attach_point))))
        if bridge_key in used_bridge_keys:
            continue
        used_bridge_keys.add(bridge_key)
        used_source_endpoints.add(source_endpoint_key)
        created += 1
        connectors.append(
            Connector(
                connector_id=f"gap:{source_line.line_id}:{created}",
                segment_type="GAP_BRIDGE",
                coords=(source_point, attach_point),
            )
        )
        events.append(
            EventPoint(
                line_id=target_line.line_id,
                point=attach_point,
                node_type="GRAPH_NODE",
                split_segment_types=(target_line.segment_type,),
            )
        )
        if attachs_to_endpoint:
            if point_distance_meter(target_line.coords[0], attach_point) <= MIN_SPLIT_GAP_M:
                used_source_endpoints.add((target_line.line_id, 0))
            if point_distance_meter(target_line.coords[-1], attach_point) <= MIN_SPLIT_GAP_M:
                used_source_endpoints.add((target_line.line_id, 1))

    return connectors, events, {
        "gapBridgeCount": len(connectors),
        "bridgeSuppressedInsidePocketCount": suppressed_inside_pocket_count,
        "bridgeSuppressedByClaimCount": suppressed_by_claim_count,
    }


def assign_fragment_sectors(
    side_lines: list[BaseLine],
    cluster_centers: dict[int, tuple[float, float]],
    intersection_radii: dict[int, float],
    sectors_by_root: dict[int, list[IntersectionSector]],
) -> list[EndpointSectorAssignment]:
    if not side_lines or not sectors_by_root:
        return []

    root_points = [Point(cluster_centers[root]) for root in sectors_by_root]
    root_ids = list(sectors_by_root.keys())
    root_tree = STRtree(root_points)
    assignments: list[EndpointSectorAssignment] = []

    for line in side_lines:
        for endpoint_index, point in ((0, line.coords[0]), (1, line.coords[-1])):
            outward = _endpoint_outward_vector(line.coords, endpoint_index=endpoint_index)
            search_distance = max(intersection_radii.values()) * CORNER_BRIDGE_ROOT_NEAR_FACTOR if intersection_radii else 0.0
            candidate_root_indexes = root_tree.query(Point(point).buffer(search_distance))
            best_root: int | None = None
            best_distance: float | None = None
            for candidate_index in candidate_root_indexes:
                root = root_ids[int(candidate_index)]
                root_point = cluster_centers[root]
                distance_meter = point_distance_meter(point, root_point)
                if distance_meter > max(intersection_radii.get(root, OFFSET_FLOOR_M) * CORNER_BRIDGE_ROOT_NEAR_FACTOR, OFFSET_FLOOR_M * 3):
                    continue
                if best_distance is None or distance_meter < best_distance:
                    best_distance = distance_meter
                    best_root = root
            if best_root is None:
                continue
            root_point = cluster_centers[best_root]
            point_angle = _angle_rad(root_point, point)
            sector_index = None
            for sector in sectors_by_root.get(best_root, []):
                if _angle_in_sector(point_angle, sector.start_angle_rad, sector.end_angle_rad):
                    sector_index = sector.sector_index
                    break
            if sector_index is None:
                continue
            assignments.append(
                EndpointSectorAssignment(
                    line_id=line.line_id,
                    segment_type=line.segment_type,
                    endpoint_index=endpoint_index,
                    point=point,
                    outward=outward,
                    root=best_root,
                    sector_index=sector_index,
                )
            )

    return assignments


def _max_pairwise_distance(points: list[tuple[float, float]]) -> float:
    max_distance = 0.0
    for index, left in enumerate(points):
        for right in points[index + 1 :]:
            max_distance = max(max_distance, point_distance_meter(left, right))
    return max_distance


def _centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )


def apply_junction_anchor_snap(
    base_lines: list[BaseLine],
    cluster_centers: dict[int, tuple[float, float]],
    intersection_radii: dict[int, float],
    sectors_by_root: dict[int, list[IntersectionSector]],
) -> tuple[list[BaseLine], dict[str, Any], dict[int, JunctionAnchorPlan], set[tuple[float, float]], set[int]]:
    """Classify junction pockets, choose anchors, and snap endpoint candidates before bridge generation."""
    side_lines = [line for line in base_lines if line.segment_type in SIDE_SEGMENT_TYPES]
    assignments = assign_fragment_sectors(side_lines, cluster_centers, intersection_radii, sectors_by_root)
    if not assignments:
        return base_lines, {
            "junctionArchetypeCounts": {},
            "junctionAnchorCount": 0,
            "anchorSnappedEndpointCount": 0,
        }, {}, set(), set()

    assignments_by_root: dict[int, list[EndpointSectorAssignment]] = defaultdict(list)
    assignments_by_root_sector: dict[tuple[int, int], list[EndpointSectorAssignment]] = defaultdict(list)
    for assignment in assignments:
        assignments_by_root[assignment.root].append(assignment)
        assignments_by_root_sector[(assignment.root, assignment.sector_index)].append(assignment)

    anchor_plans: dict[int, JunctionAnchorPlan] = {}
    archetype_counts: Counter[str] = Counter()
    for root, root_assignments in assignments_by_root.items():
        points = [assignment.point for assignment in root_assignments]
        sector_indexes = sorted({assignment.sector_index for assignment in root_assignments})
        max_spread = _max_pairwise_distance(points)
        if max_spread <= JUNCTION_POCKET_RADIUS_M and len(sector_indexes) <= 2:
            archetype = "single-node"
            single_anchor = _centroid(points)
            anchors_by_sector = {sector_index: single_anchor for sector_index in sector_indexes}
        elif len(sector_indexes) <= 2:
            archetype = "corner-pair"
            single_anchor = None
            anchors_by_sector = {
                sector_index: _centroid([assignment.point for assignment in assignments_by_root_sector[(root, sector_index)]])
                for sector_index in sector_indexes
            }
        else:
            archetype = "multi-corner-complex"
            single_anchor = None
            anchors_by_sector = {
                sector_index: _centroid([assignment.point for assignment in assignments_by_root_sector[(root, sector_index)]])
                for sector_index in sector_indexes
            }
        anchor_plans[root] = JunctionAnchorPlan(
            root=root,
            archetype=archetype,
            anchors_by_sector=anchors_by_sector,
            single_anchor=single_anchor,
        )
        archetype_counts[archetype] += 1

    endpoint_anchor_by_key: dict[tuple[str, int], tuple[float, float]] = {}
    suppressed_points: set[tuple[float, float]] = set()
    snapped_endpoint_count = 0
    for assignment in assignments:
        plan = anchor_plans[assignment.root]
        anchor = plan.single_anchor or plan.anchors_by_sector.get(assignment.sector_index)
        if anchor is None:
            continue
        if plan.archetype != "single-node" and point_distance_meter(assignment.point, anchor) > JUNCTION_POCKET_RADIUS_M:
            continue
        endpoint_anchor_by_key[(assignment.line_id, assignment.endpoint_index)] = anchor
        if point_distance_meter(assignment.point, anchor) > MIN_SPLIT_GAP_M:
            snapped_endpoint_count += 1
            suppressed_points.add(rounded_projected_point(assignment.point))
            suppressed_points.add(rounded_projected_point(anchor))
        elif plan.archetype == "single-node":
            suppressed_points.add(rounded_projected_point(anchor))

    anchored_lines: list[BaseLine] = []
    for line in base_lines:
        start = endpoint_anchor_by_key.get((line.line_id, 0), line.coords[0])
        end = endpoint_anchor_by_key.get((line.line_id, 1), line.coords[-1])
        anchored_coords = dedupe_consecutive_coords((start, *line.coords[1:-1], end))
        if len(anchored_coords) < 2 or projected_length_meter(anchored_coords) <= JUNCTION_MERGE_ARTIFACT_PRUNE_M:
            continue
        anchored_lines.append(replace(line, coords=anchored_coords))

    closed_single_node_roots = {
        root
        for root, plan in anchor_plans.items()
        if plan.archetype == "single-node"
    }
    stats = {
        "junctionArchetypeCounts": dict(sorted(archetype_counts.items())),
        "junctionAnchorCount": sum(len(plan.anchors_by_sector) for plan in anchor_plans.values()),
        "anchorSnappedEndpointCount": snapped_endpoint_count,
    }
    return anchored_lines, stats, anchor_plans, suppressed_points, closed_single_node_roots


def build_same_side_corner_bridges(
    base_lines: list[BaseLine],
    cluster_centers: dict[int, tuple[float, float]],
    intersection_radii: dict[int, float],
    sectors_by_root: dict[int, list[IntersectionSector]],
    *,
    existing_connectors: list[Connector] | None = None,
    suppressed_endpoint_points: set[tuple[float, float]] | None = None,
) -> tuple[list[Connector], list[EventPoint], dict[str, int]]:
    side_lines = [line for line in base_lines if line.segment_type in SIDE_SEGMENT_TYPES]
    if not side_lines:
        return [], [], {"sameSideCornerBridgeCount": 0}

    lines_by_id = {line.line_id: line for line in side_lines}
    assignments = assign_fragment_sectors(side_lines, cluster_centers, intersection_radii, sectors_by_root)
    if not assignments:
        return [], [], {"sameSideCornerBridgeCount": 0}

    assignments_by_key: dict[tuple[int, str, int], list[EndpointSectorAssignment]] = defaultdict(list)
    for assignment in assignments:
        assignments_by_key[(assignment.root, assignment.segment_type, assignment.sector_index)].append(assignment)

    barrier_geometries_by_side = {
        "SIDE_LEFT": [LineString(line.coords) for line in base_lines if line.segment_type == "SIDE_RIGHT"],
        "SIDE_RIGHT": [LineString(line.coords) for line in base_lines if line.segment_type == "SIDE_LEFT"],
    }
    barrier_trees_by_side = {
        side_type: STRtree(geometries) if geometries else None
        for side_type, geometries in barrier_geometries_by_side.items()
    }

    occupied_points: set[tuple[float, float]] = set()
    for connector in existing_connectors or []:
        occupied_points.add((round(connector.coords[0][0], 3), round(connector.coords[0][1], 3)))

    connectors: list[Connector] = []
    events: list[EventPoint] = []
    used_endpoints: set[tuple[str, int]] = set()
    suppressed_endpoint_points = suppressed_endpoint_points or set()
    duplicate_suppressed_count = 0
    suppressed_by_claim_count = 0
    created = 0

    for key, group in assignments_by_key.items():
        root, segment_type, sector_index = key
        root_point = cluster_centers[root]
        max_distance = min(max(intersection_radii.get(root, OFFSET_FLOOR_M) * CORNER_BRIDGE_ROOT_FACTOR, CORNER_BRIDGE_MIN_M), CORNER_BRIDGE_HARD_CAP_M)
        sector = next((item for item in sectors_by_root.get(root, []) if item.sector_index == sector_index), None)
        if sector is None:
            continue
        group_line_ids = {assignment.line_id for assignment in group}
        group_lines = [lines_by_id[line_id] for line_id in group_line_ids if line_id in lines_by_id]
        bend_radius = max(intersection_radii.get(root, OFFSET_FLOOR_M) * 0.9, OFFSET_FLOOR_M * 2.0)
        bend_point = (
            root_point[0] + math.cos(sector.bisector_angle_rad) * bend_radius,
            root_point[1] + math.sin(sector.bisector_angle_rad) * bend_radius,
        )

        for assignment in sorted(group, key=lambda item: point_distance_meter(item.point, root_point)):
            source_key = (assignment.line_id, assignment.endpoint_index)
            rounded_source = rounded_projected_point(assignment.point)
            if source_key in used_endpoints or rounded_source in occupied_points:
                duplicate_suppressed_count += 1
                continue
            if rounded_source in suppressed_endpoint_points:
                suppressed_by_claim_count += 1
                continue
            source_line = lines_by_id[assignment.line_id]
            best: tuple[float, BaseLine, tuple[float, float], bool] | None = None
            for target_line in group_lines:
                if target_line.line_id == assignment.line_id or target_line.segment_type != segment_type:
                    continue
                attach_point, distance_meter = nearest_point_on_line(target_line.coords, assignment.point)
                if distance_meter <= MIN_SPLIT_GAP_M or distance_meter > max_distance:
                    continue
                target_rounded = rounded_projected_point(attach_point)
                if target_rounded in occupied_points:
                    duplicate_suppressed_count += 1
                    continue
                if target_rounded in suppressed_endpoint_points:
                    suppressed_by_claim_count += 1
                    continue
                target_assignments = [
                    item for item in group
                    if item.line_id == target_line.line_id
                ]
                if not target_assignments:
                    continue
                target_endpoint_distance = _distance_to_line_endpoints(target_line.coords, attach_point)
                attachs_to_endpoint = target_endpoint_distance <= MIN_SPLIT_GAP_M
                direct_allowed = _is_barrier_free_segment(
                    assignment.point,
                    attach_point,
                    barrier_trees_by_side.get(segment_type),
                    barrier_geometries_by_side.get(segment_type, []),
                )
                if assignment.outward is not None:
                    bridge_vec = (attach_point[0] - assignment.point[0], attach_point[1] - assignment.point[1])
                    if _vector_angle_deg(assignment.outward, bridge_vec) > GAP_BRIDGE_MAX_ANGLE_DEG:
                        direct_allowed = False
                candidate = (distance_meter, target_line, attach_point, direct_allowed and attachs_to_endpoint)
                if best is None or candidate[0] < best[0]:
                    best = candidate

            if best is None:
                continue

            _, target_line, attach_point, use_direct = best
            direct_dist = point_distance_meter(assignment.point, attach_point)
            if direct_dist <= STUB_MAX_LENGTH_M:
                continue
            if use_direct:
                coords = (assignment.point, attach_point)
            else:
                bend_dist = point_distance_meter(assignment.point, bend_point)
                if bend_dist <= STUB_MAX_LENGTH_M:
                    coords = (assignment.point, attach_point)
                else:
                    coords = dedupe_consecutive_coords((assignment.point, bend_point, attach_point))
                if len(coords) < 2:
                    continue
            if projected_length_meter(coords) <= STUB_MAX_LENGTH_M:
                continue

            created += 1
            connectors.append(
                Connector(
                    connector_id=f"same-corner:{root}:{segment_type}:{sector_index}:{created}",
                    segment_type="SAME_SIDE_CORNER_BRIDGE",
                    coords=coords,
                )
            )
            events.append(
                EventPoint(
                    line_id=target_line.line_id,
                    point=attach_point,
                    node_type="GRAPH_NODE",
                    split_segment_types=(target_line.segment_type,),
                )
            )
            used_endpoints.add(source_key)
            occupied_points.add(rounded_source)
            occupied_points.add(rounded_projected_point(attach_point))
            break

    return connectors, events, {
        "sameSideCornerBridgeCount": len(connectors),
        "sameSideDuplicateBridgeSuppressedCount": duplicate_suppressed_count,
        "sameSideBridgeSuppressedByClaimCount": suppressed_by_claim_count,
    }


def build_cross_side_corner_bridges(
    base_lines: list[BaseLine],
    cluster_centers: dict[int, tuple[float, float]],
    intersection_radii: dict[int, float],
    sectors_by_root: dict[int, list[IntersectionSector]],
    *,
    existing_connectors: list[Connector] | None = None,
    suppressed_endpoint_points: set[tuple[float, float]] | None = None,
) -> tuple[list[Connector], list[EventPoint], dict[str, int]]:
    side_lines = [line for line in base_lines if line.segment_type in SIDE_SEGMENT_TYPES]
    if not side_lines:
        return [], [], {"crossSideCornerBridgeCount": 0}

    lines_by_id = {line.line_id: line for line in side_lines}
    assignments = assign_fragment_sectors(side_lines, cluster_centers, intersection_radii, sectors_by_root)
    if not assignments:
        return [], [], {"crossSideCornerBridgeCount": 0}

    assignments_by_key: dict[tuple[int, int], list[EndpointSectorAssignment]] = defaultdict(list)
    for assignment in assignments:
        assignments_by_key[(assignment.root, assignment.sector_index)].append(assignment)

    occupied_points: set[tuple[float, float]] = set()
    for connector in existing_connectors or []:
        for point in connector.coords:
            occupied_points.add((round(point[0], 3), round(point[1], 3)))

    connectors: list[Connector] = []
    events: list[EventPoint] = []
    used_endpoints: set[tuple[str, int]] = set()
    suppressed_endpoint_points = suppressed_endpoint_points or set()
    duplicate_suppressed_count = 0
    suppressed_by_claim_count = 0
    created = 0

    for (root, sector_index), group in assignments_by_key.items():
        left_assignments = [assignment for assignment in group if assignment.segment_type == "SIDE_LEFT"]
        right_assignments = [assignment for assignment in group if assignment.segment_type == "SIDE_RIGHT"]
        if not left_assignments or not right_assignments:
            continue
        sector = next((item for item in sectors_by_root.get(root, []) if item.sector_index == sector_index), None)
        if sector is None:
            continue
        root_point = cluster_centers[root]
        max_distance = min(max(intersection_radii.get(root, OFFSET_FLOOR_M) * CORNER_BRIDGE_ROOT_FACTOR, CORNER_BRIDGE_MIN_M), CORNER_BRIDGE_HARD_CAP_M)
        bend_radius = max(intersection_radii.get(root, OFFSET_FLOOR_M) * 0.7, OFFSET_FLOOR_M * 1.5)
        bend_point = (
            root_point[0] + math.cos(sector.bisector_angle_rad) * bend_radius,
            root_point[1] + math.sin(sector.bisector_angle_rad) * bend_radius,
        )

        for source in sorted(left_assignments + right_assignments, key=lambda item: point_distance_meter(item.point, root_point)):
            source_key = (source.line_id, source.endpoint_index)
            rounded_source = rounded_projected_point(source.point)
            if source_key in used_endpoints or rounded_source in occupied_points:
                duplicate_suppressed_count += 1
                continue
            if rounded_source in suppressed_endpoint_points:
                suppressed_by_claim_count += 1
                continue
            target_group = right_assignments if source.segment_type == "SIDE_LEFT" else left_assignments
            best: tuple[float, EndpointSectorAssignment, tuple[float, float], bool] | None = None
            for target in target_group:
                if target.line_id == source.line_id:
                    continue
                target_line = lines_by_id[target.line_id]
                attach_point, distance_meter = nearest_point_on_line(target_line.coords, source.point)
                if distance_meter <= MIN_SPLIT_GAP_M or distance_meter > max_distance:
                    continue
                target_rounded = rounded_projected_point(attach_point)
                if target_rounded in occupied_points:
                    duplicate_suppressed_count += 1
                    continue
                if target_rounded in suppressed_endpoint_points:
                    suppressed_by_claim_count += 1
                    continue
                path = dedupe_consecutive_coords((source.point, bend_point, attach_point))
                zone_limit = intersection_radii.get(root, OFFSET_FLOOR_M) * 1.35 + JUNCTION_POCKET_RADIUS_M
                if max(point_distance_meter(point, root_point) for point in path) > zone_limit:
                    continue
                direct_allowed = _distance_to_line_endpoints(target_line.coords, attach_point) <= MIN_SPLIT_GAP_M
                if not direct_allowed:
                    continue
                candidate = (distance_meter, target, attach_point, direct_allowed)
                if best is None or candidate[0] < best[0]:
                    best = candidate
            if best is None:
                continue
            _, target, attach_point, use_direct = best
            target_line = lines_by_id[target.line_id]
            direct_dist = point_distance_meter(source.point, attach_point)
            if direct_dist <= STUB_MAX_LENGTH_M:
                continue
            if use_direct:
                coords = (source.point, attach_point)
            else:
                bend_dist = point_distance_meter(source.point, bend_point)
                if bend_dist <= STUB_MAX_LENGTH_M:
                    coords = (source.point, attach_point)
                else:
                    coords = dedupe_consecutive_coords((source.point, bend_point, attach_point))
            if len(coords) < 2 or projected_length_meter(coords) <= STUB_MAX_LENGTH_M:
                continue
            created += 1
            connectors.append(
                Connector(
                    connector_id=f"cross-corner:{root}:{sector_index}:{created}",
                    segment_type="CROSS_SIDE_CORNER_BRIDGE",
                    coords=coords,
                )
            )
            events.append(
                EventPoint(
                    line_id=target_line.line_id,
                    point=attach_point,
                    node_type="GRAPH_NODE",
                    split_segment_types=(target_line.segment_type,),
                )
            )
            used_endpoints.add(source_key)
            occupied_points.add(rounded_source)
            occupied_points.add(rounded_projected_point(attach_point))
            break

    return connectors, events, {
        "crossSideCornerBridgeCount": len(connectors),
        "crossSideDuplicateBridgeSuppressedCount": duplicate_suppressed_count,
        "crossSideBridgeSuppressedByClaimCount": suppressed_by_claim_count,
    }


def build_traversable_tree(base_lines: list[BaseLine]) -> tuple[STRtree, list[LineString], list[BaseLine]]:
    traversable = [line for line in base_lines if line.segment_type in TRAVERSABLE_TYPES]
    geometries = [LineString(line.coords) for line in traversable]
    return STRtree(geometries), geometries, traversable


def project_to_nearest_traversable_line(
    point: tuple[float, float],
    traversable_tree: STRtree,
    traversable_geometries: list[LineString],
    traversable_lines: list[BaseLine],
    *,
    max_distance_meter: float,
) -> tuple[BaseLine, tuple[float, float], float] | None:
    point_geom = Point(point)
    candidate_indexes = list(traversable_tree.query(point_geom.buffer(max_distance_meter)))
    best_distance: float | None = None
    best_line: BaseLine | None = None
    best_attach_point: tuple[float, float] | None = None
    for candidate_index in candidate_indexes:
        candidate_index = int(candidate_index)
        geometry = traversable_geometries[candidate_index]
        snapped = geometry.interpolate(float(geometry.project(point_geom)))
        distance_meter = float(point_geom.distance(snapped))
        if distance_meter > max_distance_meter:
            continue
        snapped_point = (float(snapped.x), float(snapped.y))
        if best_distance is None or distance_meter < best_distance:
            best_distance = distance_meter
            best_line = traversable_lines[candidate_index]
            best_attach_point = snapped_point
    if best_distance is None or best_line is None or best_attach_point is None:
        return None
    return best_line, best_attach_point, best_distance


def load_elevator_points(*, center_lat: float | None = None, center_lon: float | None = None, radius_m: int | None = None) -> list[tuple[str, tuple[float, float]]]:
    rows = read_csv_rows(ELEVATOR_CSV)
    center: tuple[float, float] | None = None
    if center_lat is not None and center_lon is not None and radius_m is not None:
        center = (center_lon, center_lat)
    elevators: list[tuple[str, tuple[float, float]]] = []
    for index, row in enumerate(rows, start=1):
        lat = parse_optional_float(row.get("위도"))
        lon = parse_optional_float(row.get("경도"))
        if lat is None or lon is None:
            continue
        if center is not None and geodesic_distance_meter(center, (lon, lat)) > radius_m:
            continue
        x, y = WGS84_TO_TM5179.transform(lon, lat)
        elevators.append((f"elevator:{index}", (float(x), float(y))))
    return elevators


def group_crosswalk_rows(rows: list[dict[str, str]]) -> dict[tuple[str, str, str], list[dict[str, str]]]:
    groups: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        location_label = row.get("locationLabel", "")
        if not location_label:
            continue
        key = (row.get("districtGu", ""), row.get("districtDong", ""), location_label)
        groups[key].append(row)
    return groups


def pair_crosswalk_rows(rows: list[dict[str, str]]) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    grouped = group_crosswalk_rows(rows)
    pairs: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for group_rows in grouped.values():
        points = []
        for row in group_rows:
            lat = parse_optional_float(row.get("lat"))
            lng = parse_optional_float(row.get("lng"))
            if lat is None or lng is None:
                continue
            x, y = WGS84_TO_TM5179.transform(lng, lat)
            points.append((float(x), float(y)))
        used: set[int] = set()
        for index, point in enumerate(points):
            if index in used:
                continue
            best: tuple[float, int] | None = None
            for other_index in range(index + 1, len(points)):
                if other_index in used:
                    continue
                distance_meter = point_distance_meter(point, points[other_index])
                if distance_meter > CROSSWALK_PAIR_MAX_M:
                    continue
                candidate = (distance_meter, other_index)
                if best is None or candidate < best:
                    best = candidate
            if best is None:
                continue
            _, other_index = best
            used.add(index)
            used.add(other_index)
            pairs.append((point, points[other_index]))
    return pairs


def load_crosswalk_pairs(*, center_lat: float | None = None, center_lon: float | None = None, radius_m: int | None = None) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    rows = read_csv_rows(CROSSWALK_CSV)
    if center_lat is not None and center_lon is not None and radius_m is not None:
        center = (center_lon, center_lat)
        filtered_rows = []
        for row in rows:
            lat = parse_optional_float(row.get("lat"))
            lng = parse_optional_float(row.get("lng"))
            if lat is None or lng is None:
                continue
            if geodesic_distance_meter(center, (lng, lat)) <= radius_m:
                filtered_rows.append(row)
        rows = filtered_rows
    return pair_crosswalk_rows(rows)


def build_feature_connectors(
    base_lines: list[BaseLine],
    *,
    center_lat: float | None = None,
    center_lon: float | None = None,
    radius_m: int | None = None,
) -> tuple[list[Connector], list[EventPoint], dict[str, int]]:
    traversable_tree, traversable_geometries, traversable_lines = build_traversable_tree(base_lines)
    connectors: list[Connector] = []
    events: list[EventPoint] = []
    stats = {
        "crosswalkAttachFailures": 0,
        "elevatorAttachFailures": 0,
        "crossingCount": 0,
        "elevatorConnectorCount": 0,
    }

    for elevator_id, point in load_elevator_points(center_lat=center_lat, center_lon=center_lon, radius_m=radius_m):
        match = project_to_nearest_traversable_line(
            point,
            traversable_tree,
            traversable_geometries,
            traversable_lines,
            max_distance_meter=ELEVATOR_ATTACH_MAX_M,
        )
        if match is None:
            stats["elevatorAttachFailures"] += 1
            continue
        line, attach_point, _ = match
        connectors.append(
            Connector(
                connector_id=elevator_id,
                segment_type="ELEVATOR_CONNECTOR",
                coords=(attach_point, point),
            )
        )
        events.append(
            EventPoint(
                line_id=line.line_id,
                point=attach_point,
                node_type="ELEVATOR_ATTACH",
                split_segment_types=(line.segment_type,),
            )
        )
        stats["elevatorConnectorCount"] += 1
    return connectors, events, stats


def _segment_pair_key(segment_type_a: str, segment_type_b: str) -> tuple[str, str]:
    return tuple(sorted((segment_type_a, segment_type_b)))


def _is_cross_type_pair_allowed(segment_type_a: str, segment_type_b: str) -> bool:
    allowed_pairs = {
        ("SIDE_LEFT", "SIDE_RIGHT"),
        ("GAP_BRIDGE", "SIDE_LEFT"),
        ("GAP_BRIDGE", "SIDE_RIGHT"),
        ("SAME_SIDE_CORNER_BRIDGE", "SIDE_LEFT"),
        ("SAME_SIDE_CORNER_BRIDGE", "SIDE_RIGHT"),
        ("CROSS_SIDE_CORNER_BRIDGE", "SIDE_LEFT"),
        ("CROSS_SIDE_CORNER_BRIDGE", "SIDE_RIGHT"),
        ("SIDE_LEFT", "TRANSITION_CONNECTOR"),
        ("SIDE_RIGHT", "TRANSITION_CONNECTOR"),
    }
    return _segment_pair_key(segment_type_a, segment_type_b) in allowed_pairs


def _point_root_sector(
    point: tuple[float, float],
    cluster_centers: dict[int, tuple[float, float]],
    intersection_roots: set[int],
    intersection_radii: dict[int, float],
    sectors_by_root: dict[int, list[IntersectionSector]],
) -> tuple[int, int] | None:
    best_root: int | None = None
    best_distance: float | None = None
    for root in intersection_roots:
        distance_meter = point_distance_meter(point, cluster_centers[root])
        if distance_meter > intersection_radii.get(root, OFFSET_FLOOR_M) * 1.5:
            continue
        if best_distance is None or distance_meter < best_distance:
            best_distance = distance_meter
            best_root = root
    if best_root is None:
        return None
    angle = _angle_rad(cluster_centers[best_root], point)
    for sector in sectors_by_root.get(best_root, []):
        if _angle_in_sector(angle, sector.start_angle_rad, sector.end_angle_rad):
            return best_root, sector.sector_index
    return None


def _local_tangent_vector(coords: tuple[tuple[float, float], ...], point: tuple[float, float]) -> tuple[float, float] | None:
    geometry = LineString(coords)
    distance = float(geometry.project(Point(point)))
    if geometry.length <= MIN_SPLIT_GAP_M:
        return None
    back = geometry.interpolate(max(0.0, distance - 0.3))
    forward = geometry.interpolate(min(geometry.length, distance + 0.3))
    vector = (float(forward.x - back.x), float(forward.y - back.y))
    if math.hypot(*vector) <= MIN_SPLIT_GAP_M:
        return None
    return vector


def resolve_cross_type_intersections(
    projected_segments: list[tuple[str, tuple[tuple[float, float], ...]]],
    cluster_centers: dict[int, tuple[float, float]],
    intersection_roots: set[int],
    intersection_radii: dict[int, float],
    sectors_by_root: dict[int, list[IntersectionSector]],
    *,
    include_side_pairs: bool = True,
) -> tuple[list[tuple[str, tuple[tuple[float, float], ...]]], dict[str, int]]:
    if not projected_segments:
        return projected_segments, {"crossTypeIntersectionCount": 0}

    geometries = [LineString(coords) for _, coords in projected_segments]
    tree = STRtree(geometries)
    split_points_by_segment: dict[int, list[tuple[float, float]]] = defaultdict(list)
    invalid_tail_pts_by_segment: dict[int, set[tuple[float, float]]] = defaultdict(set)
    cross_type_intersection_count = 0

    for index, (segment_type, coords) in enumerate(projected_segments):
        geometry = geometries[index]
        for candidate_index in tree.query(geometry):
            candidate_index = int(candidate_index)
            if candidate_index <= index:
                continue
            other_type, other_coords = projected_segments[candidate_index]
            if not _is_cross_type_pair_allowed(segment_type, other_type):
                continue
            if not include_side_pairs and {segment_type, other_type} == {"SIDE_LEFT", "SIDE_RIGHT"}:
                continue
            intersection = geometry.intersection(geometries[candidate_index])
            for point in _collect_line_intersection_points(intersection):
                point_coords = (float(point.x), float(point.y))
                allow_junction = True
                if {segment_type, other_type} == {"SIDE_LEFT", "SIDE_RIGHT"}:
                    root_sector_a = _point_root_sector(point_coords, cluster_centers, intersection_roots, intersection_radii, sectors_by_root)
                    root_sector_b = _point_root_sector(point_coords, cluster_centers, intersection_roots, intersection_radii, sectors_by_root)
                    tangent_a = _local_tangent_vector(coords, point_coords)
                    tangent_b = _local_tangent_vector(other_coords, point_coords)
                    if root_sector_a is None or root_sector_b is None or root_sector_a != root_sector_b:
                        allow_junction = False
                    elif tangent_a is None or tangent_b is None:
                        allow_junction = False
                    else:
                        crossing_angle = _vector_angle_deg(tangent_a, tangent_b)
                        if crossing_angle < 30.0 or crossing_angle > 150.0:
                            allow_junction = False
                split_points_by_segment[index].append(point_coords)
                split_points_by_segment[candidate_index].append(point_coords)
                if not allow_junction:
                    rounded = (round(point_coords[0], 3), round(point_coords[1], 3))
                    invalid_tail_pts_by_segment[index].add(rounded)
                    invalid_tail_pts_by_segment[candidate_index].add(rounded)
                    continue
                cross_type_intersection_count += 1

    cross_type_tail_prune_count = 0
    resolved_segments: list[tuple[str, tuple[tuple[float, float], ...]]] = []
    for index, (segment_type, coords) in enumerate(projected_segments):
        invalid_pts = invalid_tail_pts_by_segment.get(index, set())
        split_points = [coords[0], coords[-1], *split_points_by_segment.get(index, [])]
        for piece in split_projected_segment(coords, split_points):
            length_meter = projected_length_meter(piece)
            if segment_type in CONNECTOR_SEGMENT_TYPES | {"TRANSITION_CONNECTOR"}:
                if length_meter > JUNCTION_MERGE_ARTIFACT_PRUNE_M:
                    resolved_segments.append((segment_type, piece))
            elif segment_type in SIDE_SEGMENT_TYPES and invalid_pts:
                piece_start_r = (round(piece[0][0], 3), round(piece[0][1], 3))
                piece_end_r = (round(piece[-1][0], 3), round(piece[-1][1], 3))
                at_invalid = piece_start_r in invalid_pts or piece_end_r in invalid_pts
                if at_invalid:
                    if length_meter > CROSS_TYPE_TAIL_PRUNE_M:
                        resolved_segments.append((segment_type, piece))
                    else:
                        cross_type_tail_prune_count += 1
                elif length_meter > STUB_MAX_LENGTH_M:
                    resolved_segments.append((segment_type, piece))
            elif length_meter > STUB_MAX_LENGTH_M:
                resolved_segments.append((segment_type, piece))
    return resolved_segments, {
        "crossTypeIntersectionCount": cross_type_intersection_count,
        "crossTypeTailPruneCount": cross_type_tail_prune_count,
    }


def cleanup_junction_pockets(
    projected_segments: list[tuple[str, tuple[tuple[float, float], ...]]],
    cluster_centers: dict[int, tuple[float, float]],
    intersection_roots: set[int],
    intersection_radii: dict[int, float],
) -> tuple[list[tuple[str, tuple[tuple[float, float], ...]]], dict[str, int]]:
    if not projected_segments or not intersection_roots:
        return projected_segments, {
            "junctionPocketCleanupCount": 0,
            "junctionPocketRemovedNodeCount": 0,
            "junctionPocketRemovedStubCount": 0,
        }

    canonical_pockets: list[tuple[float, float]] = []
    for root in intersection_roots:
        center = cluster_centers[root]
        matched_index = None
        for index, pocket_center in enumerate(canonical_pockets):
            if point_distance_meter(center, pocket_center) <= JUNCTION_POCKET_RADIUS_M:
                matched_index = index
                break
        if matched_index is None:
            canonical_pockets.append(center)
            continue
        existing = canonical_pockets[matched_index]
        canonical_pockets[matched_index] = ((existing[0] + center[0]) / 2.0, (existing[1] + center[1]) / 2.0)

    cleaned: list[tuple[str, tuple[tuple[float, float], ...]]] = []
    removed_stub_count = 0
    snapped_endpoint_count = 0
    pocket_points = [Point(center) for center in canonical_pockets]
    pocket_tree = STRtree(pocket_points) if pocket_points else None

    def find_pocket(point: tuple[float, float]) -> tuple[float, float] | None:
        if pocket_tree is None:
            return None
        point_geom = Point(point)
        best: tuple[float, tuple[float, float]] | None = None
        for candidate_index in pocket_tree.query(point_geom.buffer(JUNCTION_POCKET_RADIUS_M)):
            center = canonical_pockets[int(candidate_index)]
            distance_meter = point_distance_meter(point, center)
            if distance_meter > JUNCTION_POCKET_RADIUS_M:
                continue
            candidate = (distance_meter, center)
            if best is None or candidate[0] < best[0]:
                best = candidate
        return best[1] if best is not None else None

    for segment_type, coords in projected_segments:
        start = coords[0]
        end = coords[-1]
        start_pocket = find_pocket(start)
        end_pocket = find_pocket(end)

        normalized_start = start_pocket if start_pocket is not None else start
        normalized_end = end_pocket if end_pocket is not None else end
        if normalized_start != start:
            snapped_endpoint_count += 1
        if normalized_end != end:
            snapped_endpoint_count += 1

        normalized_coords = dedupe_consecutive_coords((normalized_start, *coords[1:-1], normalized_end))
        length_meter = projected_length_meter(normalized_coords)
        if start_pocket is not None and end_pocket is not None and start_pocket == end_pocket and length_meter <= JUNCTION_POCKET_RADIUS_M:
            removed_stub_count += 1
            continue
        if length_meter <= JUNCTION_MERGE_ARTIFACT_PRUNE_M:
            removed_stub_count += 1
            continue
        cleaned.append((segment_type, normalized_coords))

    return cleaned, {
        "junctionPocketCleanupCount": len(canonical_pockets),
        "junctionPocketRemovedNodeCount": snapped_endpoint_count,
        "junctionPocketRemovedStubCount": removed_stub_count,
    }


def reconcile_post_bridge_pockets(
    projected_segments: list[tuple[str, tuple[tuple[float, float], ...]]],
    cluster_centers: dict[int, tuple[float, float]],
    intersection_roots: set[int],
    intersection_radii: dict[int, float],
    sectors_by_root: dict[int, list[IntersectionSector]],
    anchor_plans: dict[int, JunctionAnchorPlan],
) -> tuple[list[tuple[str, tuple[tuple[float, float], ...]]], dict[str, int]]:
    if not projected_segments or not anchor_plans:
        return projected_segments, {
            "postBridgePocketTailPruneCount": 0,
            "postBridgePocketMicroLoopPruneCount": 0,
            "duplicateBridgeSuppressedCount": 0,
            "crossSideGapDuplicatePocketCount": 0,
        }

    reconciled: list[tuple[str, tuple[tuple[float, float], ...]]] = []
    for segment_type, coords in projected_segments:
        if segment_type not in SIDE_SEGMENT_TYPES | {"SAME_SIDE_CORNER_BRIDGE", "CROSS_SIDE_CORNER_BRIDGE", "GAP_BRIDGE"}:
            reconciled.append((segment_type, coords))
            continue

        def snap_endpoint(point: tuple[float, float]) -> tuple[float, float]:
            root_sector = _point_root_sector(point, cluster_centers, intersection_roots, intersection_radii, sectors_by_root)
            if root_sector is None:
                return point
            root, sector_index = root_sector
            plan = anchor_plans.get(root)
            if plan is None:
                return point
            anchor = plan.single_anchor or plan.anchors_by_sector.get(sector_index)
            if anchor is None:
                return point
            if point_distance_meter(point, anchor) <= JUNCTION_POCKET_RADIUS_M:
                return anchor
            return point

        start = snap_endpoint(coords[0])
        end = snap_endpoint(coords[-1])
        normalized = dedupe_consecutive_coords((start, *coords[1:-1], end))
        if len(normalized) >= 2:
            reconciled.append((segment_type, normalized))

    endpoint_degree: Counter[tuple[float, float]] = Counter()
    for _, coords in reconciled:
        endpoint_degree[rounded_projected_point(coords[0])] += 1
        endpoint_degree[rounded_projected_point(coords[-1])] += 1

    duplicate_bridge_suppressed = 0
    cross_side_gap_duplicate_pockets: set[tuple[Any, ...]] = set()
    best_bridge_by_role: dict[tuple[Any, ...], tuple[int, int, str]] = {}
    bridge_priorities = {
        "SAME_SIDE_CORNER_BRIDGE": 3,
        "CROSS_SIDE_CORNER_BRIDGE": 2,
        "GAP_BRIDGE": 1,
    }
    keep_indexes: set[int] = set(range(len(reconciled)))

    for index, (segment_type, coords) in enumerate(reconciled):
        if segment_type not in bridge_priorities:
            continue
        start_context = _point_root_sector(coords[0], cluster_centers, intersection_roots, intersection_radii, sectors_by_root)
        end_context = _point_root_sector(coords[-1], cluster_centers, intersection_roots, intersection_radii, sectors_by_root)
        if start_context is None or end_context is None or start_context[0] != end_context[0]:
            continue
        role_key = (start_context[0], tuple(sorted((start_context[1], end_context[1]))))
        priority = bridge_priorities[segment_type]
        existing = best_bridge_by_role.get(role_key)
        if existing is None:
            best_bridge_by_role[role_key] = (priority, index, segment_type)
            continue
        existing_priority, existing_index, existing_type = existing
        if {existing_type, segment_type} == {"CROSS_SIDE_CORNER_BRIDGE", "GAP_BRIDGE"}:
            cross_side_gap_duplicate_pockets.add(role_key)
        duplicate_bridge_suppressed += 1
        if priority > existing_priority:
            keep_indexes.discard(existing_index)
            best_bridge_by_role[role_key] = (priority, index, segment_type)
        else:
            keep_indexes.discard(index)

    cleaned: list[tuple[str, tuple[tuple[float, float], ...]]] = []
    tail_pruned = 0
    micro_loop_pruned = 0
    for index, (segment_type, coords) in enumerate(reconciled):
        if index not in keep_indexes:
            continue
        length_meter = projected_length_meter(coords)
        start_key = rounded_projected_point(coords[0])
        end_key = rounded_projected_point(coords[-1])
        start_context = _point_root_sector(coords[0], cluster_centers, intersection_roots, intersection_radii, sectors_by_root)
        end_context = _point_root_sector(coords[-1], cluster_centers, intersection_roots, intersection_radii, sectors_by_root)
        in_pocket = start_context is not None or end_context is not None
        same_context = start_context is not None and start_context == end_context

        if segment_type in SIDE_SEGMENT_TYPES | {"SAME_SIDE_CORNER_BRIDGE", "CROSS_SIDE_CORNER_BRIDGE", "GAP_BRIDGE"}:
            if same_context and length_meter <= POST_BRIDGE_POCKET_TAIL_PRUNE_M:
                micro_loop_pruned += 1
                continue
            if in_pocket and length_meter <= POST_BRIDGE_POCKET_TAIL_PRUNE_M and (
                endpoint_degree[start_key] <= 1 or endpoint_degree[end_key] <= 1
            ):
                tail_pruned += 1
                continue

        cleaned.append((segment_type, coords))

    return cleaned, {
        "postBridgePocketTailPruneCount": tail_pruned,
        "postBridgePocketMicroLoopPruneCount": micro_loop_pruned,
        "duplicateBridgeSuppressedCount": duplicate_bridge_suppressed,
        "crossSideGapDuplicatePocketCount": len(cross_side_gap_duplicate_pockets),
    }


def audit_junction_residuals(
    projected_segments: list[tuple[str, tuple[tuple[float, float], ...]]],
    cluster_centers: dict[int, tuple[float, float]],
    intersection_roots: set[int],
    intersection_radii: dict[int, float],
    sectors_by_root: dict[int, list[IntersectionSector]],
    anchor_plans: dict[int, JunctionAnchorPlan],
) -> dict[str, int]:
    single_node_endpoint_sets: dict[int, set[tuple[float, float]]] = defaultdict(set)
    pocket_internal_gap_bridge_count = 0
    for segment_type, coords in projected_segments:
        start_context = _point_root_sector(coords[0], cluster_centers, intersection_roots, intersection_radii, sectors_by_root)
        end_context = _point_root_sector(coords[-1], cluster_centers, intersection_roots, intersection_radii, sectors_by_root)
        if segment_type == "GAP_BRIDGE" and (start_context is not None or end_context is not None):
            pocket_internal_gap_bridge_count += 1
        for context, point in ((start_context, coords[0]), (end_context, coords[-1])):
            if context is None:
                continue
            root, _ = context
            plan = anchor_plans.get(root)
            if plan is not None and plan.archetype == "single-node":
                single_node_endpoint_sets[root].add(rounded_projected_point(point))

    return {
        "singleNodeJunctionMultiNodeResidualCount": sum(
            1 for endpoints in single_node_endpoint_sets.values() if len(endpoints) > 1
        ),
        "pocketInternalGapBridgeCount": pocket_internal_gap_bridge_count,
    }


def consolidate_junction_candidates(
    projected_segments: list[tuple[str, tuple[tuple[float, float], ...]]],
) -> tuple[list[tuple[str, tuple[tuple[float, float], ...]]], dict[str, int]]:
    if not projected_segments:
        return projected_segments, {"junctionConsolidationClusterCount": 0, "mergedJunctionNodeCount": 0, "pass2StubPruneCount": 0}

    coords_list = [coords for _, coords in projected_segments]
    endpoint_clusters = cluster_endpoint_indices(coords_list, JUNCTION_MERGE_RADIUS_M)
    endpoint_coords = [endpoint for coords in coords_list for endpoint in (coords[0], coords[-1])]
    endpoint_root_by_index: dict[int, int] = {}
    cluster_centers: dict[int, tuple[float, float]] = {}
    for root, members in endpoint_clusters.items():
        for member in members:
            endpoint_root_by_index[member] = root
        cluster_centers[root] = (
            sum(endpoint_coords[index][0] for index in members) / len(members),
            sum(endpoint_coords[index][1] for index in members) / len(members),
        )

    consolidated: list[tuple[str, tuple[tuple[float, float], ...]]] = []
    pass2_pruned = 0
    merged_roots = sum(1 for members in endpoint_clusters.values() if len(members) > 1)
    merged_nodes = sum(len(members) - 1 for members in endpoint_clusters.values() if len(members) > 1)
    for segment_index, (segment_type, coords) in enumerate(projected_segments):
        from_root = endpoint_root_by_index[segment_index * 2]
        to_root = endpoint_root_by_index[segment_index * 2 + 1]
        normalized_coords = dedupe_consecutive_coords((cluster_centers[from_root], *coords[1:-1], cluster_centers[to_root]))
        length_meter = projected_length_meter(normalized_coords)
        prune_threshold = JUNCTION_MERGE_ARTIFACT_PRUNE_M if segment_type not in {"CENTERLINE", "SIDE_LEFT", "SIDE_RIGHT"} else STUB_MAX_LENGTH_M
        if length_meter <= prune_threshold:
            pass2_pruned += 1
            continue
        consolidated.append((segment_type, normalized_coords))

    return consolidated, {
        "junctionConsolidationClusterCount": merged_roots,
        "mergedJunctionNodeCount": merged_nodes,
        "pass2StubPruneCount": pass2_pruned,
    }


def split_base_lines(base_lines: list[BaseLine], events: list[EventPoint]) -> list[tuple[str, tuple[tuple[float, float], ...]]]:
    event_points_by_line: dict[str, list[EventPoint]] = defaultdict(list)
    for event in events:
        event_points_by_line[event.line_id].append(event)
    pieces: list[tuple[str, tuple[tuple[float, float], ...]]] = []
    for line in base_lines:
        split_points = [line.coords[0], line.coords[-1]]
        for event in event_points_by_line.get(line.line_id, []):
            if line.segment_type in event.split_segment_types:
                split_points.append(event.point)
        for piece in split_projected_segment(line.coords, split_points):
            if projected_length_meter(piece) > STUB_MAX_LENGTH_M:
                pieces.append((line.segment_type, piece))
    return pieces


def build_node_snapshots(
    projected_segments: list[tuple[str, tuple[tuple[float, float], ...]]],
    event_points: list[EventPoint],
) -> tuple[list[NodeSnapshot], list[SegmentSnapshot]]:
    coords_list = [coords for _, coords in projected_segments]
    endpoint_clusters = cluster_endpoint_indices(coords_list, NODE_MERGE_TOLERANCE_M)
    endpoint_coords = [endpoint for coords in coords_list for endpoint in (coords[0], coords[-1])]
    endpoint_root_by_index: dict[int, int] = {}
    cluster_centers: dict[int, tuple[float, float]] = {}
    cluster_first_seen: dict[int, int] = {}
    for root, members in endpoint_clusters.items():
        for member in members:
            endpoint_root_by_index[member] = root
        cluster_centers[root] = (
            sum(endpoint_coords[index][0] for index in members) / len(members),
            sum(endpoint_coords[index][1] for index in members) / len(members),
        )
        cluster_first_seen[root] = min(members)

    degree_counter: Counter[int] = Counter()
    for segment_index, _ in enumerate(projected_segments):
        degree_counter[endpoint_root_by_index[segment_index * 2]] += 1
        degree_counter[endpoint_root_by_index[segment_index * 2 + 1]] += 1

    cell_size = NODE_MERGE_TOLERANCE_M
    center_grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for root, center in cluster_centers.items():
        cell = (math.floor(center[0] / cell_size), math.floor(center[1] / cell_size))
        center_grid[cell].append(root)

    event_types_by_root: dict[int, set[str]] = defaultdict(set)
    for event in event_points:
        event_cell = (math.floor(event.point[0] / cell_size), math.floor(event.point[1] / cell_size))
        for offset_x in (-1, 0, 1):
            for offset_y in (-1, 0, 1):
                for root in center_grid.get((event_cell[0] + offset_x, event_cell[1] + offset_y), []):
                    center = cluster_centers[root]
                    if point_distance_meter(event.point, center) <= NODE_MERGE_TOLERANCE_M:
                        event_types_by_root[root].add(event.node_type)

    ordered_roots = sorted(cluster_centers, key=cluster_first_seen.get)
    nodes_by_root: dict[int, NodeSnapshot] = {}
    for vertex_id, root in enumerate(ordered_roots, start=1):
        lon, lat = transform_projected_point(cluster_centers[root])
        event_types = event_types_by_root.get(root, set())
        if "LANE_TRANSITION" in event_types:
            node_type = "LANE_TRANSITION"
        elif "CROSSING_ATTACH" in event_types:
            node_type = "CROSSING_ATTACH"
        elif "ELEVATOR_ATTACH" in event_types:
            node_type = "ELEVATOR_ATTACH"
        elif degree_counter[root] == 1:
            node_type = "DEAD_END"
        elif degree_counter[root] >= 3:
            node_type = "CHAIN_JOIN"
        else:
            node_type = "GRAPH_NODE"
        nodes_by_root[root] = NodeSnapshot(
            vertex_id=vertex_id,
            source_node_key=node_key(lon, lat),
            lon=lon,
            lat=lat,
            node_type=node_type,
            degree=degree_counter[root],
        )

    segments: list[SegmentSnapshot] = []
    for segment_index, (segment_type, coords) in enumerate(projected_segments, start=1):
        from_root = endpoint_root_by_index[(segment_index - 1) * 2]
        to_root = endpoint_root_by_index[(segment_index - 1) * 2 + 1]
        normalized_coords = dedupe_consecutive_coords((cluster_centers[from_root], *coords[1:-1], cluster_centers[to_root]))
        lonlat_coords = transform_projected_coords(normalized_coords)
        length_meter = round(line_length_meter(lonlat_coords), 2)
        if length_meter <= 0:
            continue
        segments.append(
            SegmentSnapshot(
                edge_id=len(segments) + 1,
                from_node_id=nodes_by_root[from_root].vertex_id,
                to_node_id=nodes_by_root[to_root].vertex_id,
                length_meter=length_meter,
                coords=lonlat_coords,
                segment_type=segment_type,
            )
        )

    return [nodes_by_root[root] for root in ordered_roots], segments


def build_side_graph(
    *,
    center_lat: float | None = None,
    center_lon: float | None = None,
    radius_m: int | None = None,
) -> tuple[list[NodeSnapshot], list[SegmentSnapshot], dict[str, Any]]:
    source_segments, source_report = build_source_segments(center_lat=center_lat, center_lon=center_lon, radius_m=radius_m)
    normalized_source_segments, normalization_report = normalize_source_segments(source_segments)
    temp_segments, cluster_centers, node_degree, adjacency = build_temp_graph(normalized_source_segments)
    temp_segments = [replace(segment, classification="MULTI_LANE") for segment in temp_segments]
    intersection_roots, intersection_radii = compute_intersection_roots(temp_segments, cluster_centers, node_degree)
    sectors_by_root = build_intersection_sectors(temp_segments, cluster_centers, adjacency, intersection_roots)
    chains = build_chains(temp_segments, node_degree, adjacency, intersection_roots)
    base_lines, line_ids_by_chain = build_base_lines(
        chains,
        cluster_centers,
        intersection_roots,
        intersection_radii,
        {},
    )
    base_lines, pass1_pruned = prune_intersection_boundary_stubs(
        base_lines,
        cluster_centers,
        intersection_roots,
        intersection_radii,
    )
    line_ids_by_chain = defaultdict(list)
    for line in base_lines:
        if line.chain_id is not None:
            line_ids_by_chain[line.chain_id].append(line.line_id)
    base_split_segments = split_base_lines(base_lines, [])
    base_resolved_segments, base_cross_type_stats = resolve_cross_type_intersections(
        base_split_segments,
        cluster_centers,
        intersection_roots,
        intersection_radii,
        sectors_by_root,
    )
    cleaned_base_projected_segments, pocket_stats = cleanup_junction_pockets(
        base_resolved_segments,
        cluster_centers,
        intersection_roots,
        intersection_radii,
    )
    cleaned_base_lines = projected_segments_to_base_lines(cleaned_base_projected_segments)
    anchored_base_lines, anchor_stats, anchor_plans, suppressed_endpoint_points, closed_single_node_roots = apply_junction_anchor_snap(
        cleaned_base_lines,
        cluster_centers,
        intersection_radii,
        sectors_by_root,
    )

    same_side_corner_bridges, same_side_corner_events, same_side_corner_stats = build_same_side_corner_bridges(
        anchored_base_lines,
        cluster_centers,
        intersection_radii,
        sectors_by_root,
        existing_connectors=[],
        suppressed_endpoint_points=suppressed_endpoint_points,
    )
    cross_side_corner_bridges, cross_side_corner_events, cross_side_corner_stats = build_cross_side_corner_bridges(
        anchored_base_lines,
        cluster_centers,
        intersection_radii,
        sectors_by_root,
        existing_connectors=[*same_side_corner_bridges],
        suppressed_endpoint_points=suppressed_endpoint_points,
    )
    if ENABLE_GAP_BRIDGES:
        gap_bridges, gap_bridge_events, gap_bridge_stats = build_gap_bridges(
            anchored_base_lines,
            cluster_centers=cluster_centers,
            intersection_roots=intersection_roots,
            intersection_radii=intersection_radii,
            suppressed_endpoint_points=suppressed_endpoint_points,
            closed_single_node_roots=closed_single_node_roots,
        )
    else:
        gap_bridges, gap_bridge_events, gap_bridge_stats = [], [], {
            "gapBridgeCount": 0,
            "bridgeSuppressedInsidePocketCount": 0,
            "bridgeSuppressedByClaimCount": 0,
            "gapBridgeGenerationSkipped": 1,
        }
    feature_connectors, feature_events, feature_stats = build_feature_connectors(
        anchored_base_lines,
        center_lat=center_lat,
        center_lon=center_lon,
        radius_m=radius_m,
    )
    all_events = [
        *same_side_corner_events,
        *cross_side_corner_events,
        *gap_bridge_events,
        *feature_events,
    ]
    split_segments = split_base_lines(anchored_base_lines, all_events)
    connector_segments = [
        (connector.segment_type, connector.coords)
        for connector in [
            *same_side_corner_bridges,
            *cross_side_corner_bridges,
            *gap_bridges,
            *feature_connectors,
        ]
    ]
    all_projected_segments = [*split_segments, *connector_segments]
    resolved_segments, combined_cross_type_stats = resolve_cross_type_intersections(
        all_projected_segments,
        cluster_centers,
        intersection_roots,
        intersection_radii,
        sectors_by_root,
        include_side_pairs=False,
    )
    reconciled_segments, post_bridge_stats = reconcile_post_bridge_pockets(
        resolved_segments,
        cluster_centers,
        intersection_roots,
        intersection_radii,
        sectors_by_root,
        anchor_plans,
    )
    consolidated_segments, junction_stats = consolidate_junction_candidates(reconciled_segments)
    residual_stats = audit_junction_residuals(
        consolidated_segments,
        cluster_centers,
        intersection_roots,
        intersection_radii,
        sectors_by_root,
        anchor_plans,
    )
    nodes, segments = build_node_snapshots(consolidated_segments, all_events)

    type_counts = Counter(segment.segment_type for segment in segments)
    total_bridge_suppressed_by_claim = (
        same_side_corner_stats.get("sameSideBridgeSuppressedByClaimCount", 0)
        + cross_side_corner_stats.get("crossSideBridgeSuppressedByClaimCount", 0)
        + gap_bridge_stats.get("bridgeSuppressedByClaimCount", 0)
    )
    total_duplicate_bridge_suppressed = (
        same_side_corner_stats.get("sameSideDuplicateBridgeSuppressedCount", 0)
        + cross_side_corner_stats.get("crossSideDuplicateBridgeSuppressedCount", 0)
        + post_bridge_stats.get("duplicateBridgeSuppressedCount", 0)
    )
    report = {
        **source_report,
        **normalization_report,
        "tempSegmentCount": len(temp_segments),
        "tempNodeCount": len(cluster_centers),
        "intersectionNodeCount": len(intersection_roots),
        "chainCount": len(chains),
        "centerlineChainCount": 0,
        "multiLaneChainCount": len(chains),
        "baseLineCount": len(base_lines),
        "transitionConnectorCount": 0,
        "cleanedBaseLineCount": len(cleaned_base_lines),
        "anchoredBaseLineCount": len(anchored_base_lines),
        **same_side_corner_stats,
        **cross_side_corner_stats,
        **gap_bridge_stats,
        "bridgeSuppressedByClaimCount": total_bridge_suppressed_by_claim,
        "pass1StubPruneCount": pass1_pruned,
        "baseCrossTypeIntersectionCount": base_cross_type_stats["crossTypeIntersectionCount"],
        "baseCrossTypeTailPruneCount": base_cross_type_stats["crossTypeTailPruneCount"],
        "combinedCrossTypeIntersectionCount": combined_cross_type_stats["crossTypeIntersectionCount"],
        "combinedCrossTypeTailPruneCount": combined_cross_type_stats["crossTypeTailPruneCount"],
        "crossTypeIntersectionCount": base_cross_type_stats["crossTypeIntersectionCount"] + combined_cross_type_stats["crossTypeIntersectionCount"],
        "crossTypeTailPruneCount": base_cross_type_stats["crossTypeTailPruneCount"] + combined_cross_type_stats["crossTypeTailPruneCount"],
        **pocket_stats,
        **anchor_stats,
        **post_bridge_stats,
        "duplicateBridgeSuppressedCount": total_duplicate_bridge_suppressed,
        **junction_stats,
        **residual_stats,
        "nodeCount": len(nodes),
        "segmentCount": len(segments),
        "segmentTypeCounts": dict(sorted(type_counts.items())),
        **feature_stats,
        "singleLaneThresholdMeter": SINGLE_LANE_THRESHOLD_M,
        "twoLaneMinimumWidthMeter": TWO_LANE_MINIMUM_WIDTH_M,
    }
    return nodes, segments, report


def write_snapshots(nodes: list[NodeSnapshot], segments: list[SegmentSnapshot], report: dict[str, Any]) -> None:
    ensure_runtime_dir()
    with NODE_SNAPSHOT.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["vertexId", "sourceNodeKey", "point", "nodeType", "degree"])
        writer.writeheader()
        for node in nodes:
            writer.writerow(
                {
                    "vertexId": node.vertex_id,
                    "sourceNodeKey": node.source_node_key,
                    "point": node.point_ewkt,
                    "nodeType": node.node_type,
                    "degree": node.degree,
                }
            )
    with SEGMENT_SNAPSHOT.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=["edgeId", "fromNodeId", "toNodeId", "geom", "lengthMeter", "segmentType", "walkAccess"],
        )
        writer.writeheader()
        for segment in segments:
            writer.writerow(
                {
                    "edgeId": segment.edge_id,
                    "fromNodeId": segment.from_node_id,
                    "toNodeId": segment.to_node_id,
                    "geom": segment.geom_ewkt,
                    "lengthMeter": segment.length_meter,
                    "segmentType": segment.segment_type,
                    "walkAccess": "UNKNOWN",
                }
            )
    SNAPSHOT_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def topology_audit(nodes: list[NodeSnapshot], segments: list[SegmentSnapshot], report: dict[str, Any]) -> dict[str, Any]:
    node_ids = {node.vertex_id for node in nodes}
    degree = Counter()
    dsu = DisjointSet()
    for node in nodes:
        dsu.find(node.vertex_id)
    orphan_edges = 0
    for segment in segments:
        if segment.from_node_id not in node_ids or segment.to_node_id not in node_ids:
            orphan_edges += 1
            continue
        degree[segment.from_node_id] += 1
        degree[segment.to_node_id] += 1
        dsu.union(segment.from_node_id, segment.to_node_id)
    audit = {
        "nodeCount": len(nodes),
        "segmentCount": len(segments),
        "orphanEdges": orphan_edges,
        "connectedComponents": dsu.component_count() if nodes else 0,
        "degreeDistribution": dict(sorted((str(key), value) for key, value in Counter(degree.values()).items())),
        "segmentTypeCounts": report.get("segmentTypeCounts", {}),
    }
    TOPOLOGY_REPORT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return audit


def load_db(nodes: list[NodeSnapshot], segments: list[SegmentSnapshot]) -> dict[str, Any]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute('TRUNCATE TABLE "segment_features", "road_segments", "road_nodes" RESTART IDENTITY CASCADE')
            for node in nodes:
                insert_row(
                    cur,
                    "road_nodes",
                    {
                        "vertexId": node.vertex_id,
                        "sourceNodeKey": node.source_node_key,
                        "point": ewkt(node.point_ewkt),
                    },
                )
            for segment in segments:
                insert_row(
                    cur,
                    "road_segments",
                    {
                        "edgeId": segment.edge_id,
                        "fromNodeId": segment.from_node_id,
                        "toNodeId": segment.to_node_id,
                        "geom": ewkt(segment.geom_ewkt),
                        "lengthMeter": segment.length_meter,
                        "walkAccess": "UNKNOWN",
                        "segmentType": segment.segment_type,
                    },
                )
        conn.commit()

    report = {
        "nodeCount": len(nodes),
        "segmentCount": len(segments),
        "loaded": True,
    }
    POST_LOAD_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def build_preview_payload(nodes: list[NodeSnapshot], segments: list[SegmentSnapshot], report: dict[str, Any], *, center_lat: float, center_lon: float, radius_m: int) -> dict[str, Any]:
    actual_type_counts = Counter(segment.segment_type for segment in segments)
    node_features = [
        {
            "type": "Feature",
            "properties": {
                "vertexId": node.vertex_id,
                "nodeType": node.node_type,
                "degree": node.degree,
            },
            "geometry": {"type": "Point", "coordinates": [node.lon, node.lat]},
        }
        for node in nodes
    ]
    segment_features = [
        {
            "type": "Feature",
            "properties": {
                "edgeId": segment.edge_id,
                "segmentType": segment.segment_type,
                "lengthMeter": segment.length_meter,
            },
            "geometry": {"type": "LineString", "coordinates": [list(coord) for coord in segment.coords]},
        }
        for segment in segments
    ]
    return {
        "meta": {
            "title": "Haeundae 5km Side Graph 02B Preview",
            "centerLat": center_lat,
            "centerLon": center_lon,
            "radiusMeter": radius_m,
            "sourceShp": str(RAW_DIR / f"{SHP_BASENAME}.shp"),
            "outputHtml": str(PREVIEW_HTML),
            "outputGeojson": str(PREVIEW_GEOJSON),
            "localhostUrl": f"http://127.0.0.1:3000/etl/{PREVIEW_HTML.name}",
        },
        "summary": {
            "nodeCount": len(nodes),
            "segmentCount": len(segments),
            "segmentTypeCounts": [{"name": name, "count": count} for name, count in sorted(actual_type_counts.items())],
            "transitionConnectorCount": actual_type_counts.get("TRANSITION_CONNECTOR", 0),
            "gapBridgeCount": actual_type_counts.get("GAP_BRIDGE", 0),
            "sameSideCornerBridgeCount": actual_type_counts.get("SAME_SIDE_CORNER_BRIDGE", 0),
            "crossSideCornerBridgeCount": actual_type_counts.get("CROSS_SIDE_CORNER_BRIDGE", 0),
            "crossingCount": actual_type_counts.get("CROSSING", 0),
            "elevatorConnectorCount": actual_type_counts.get("ELEVATOR_CONNECTOR", 0),
        },
        "layers": {
            "roadNodes": {"type": "FeatureCollection", "features": node_features},
            "roadSegments": {"type": "FeatureCollection", "features": segment_features},
        },
    }


def generate_preview_dataset(*, center_lat: float, center_lon: float, radius_m: int) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    nodes, segments, report = build_side_graph(center_lat=center_lat, center_lon=center_lon, radius_m=radius_m)
    write_snapshots(nodes, segments, report)
    audit = topology_audit(nodes, segments, report)
    payload = build_preview_payload(nodes, segments, report, center_lat=center_lat, center_lon=center_lon, radius_m=radius_m)
    return payload, report, audit
