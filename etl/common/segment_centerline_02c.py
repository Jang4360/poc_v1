from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from math import acos, cos, floor, pi
from pathlib import Path
from typing import Any, Iterable

import shapefile
from pyproj import Geod, Transformer
from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPoint, MultiPolygon, Point, Polygon, box
from shapely.ops import nearest_points
from shapely.ops import substring
from shapely.ops import unary_union
from shapely.strtree import STRtree

from etl.common import segment_graph_edit_ui, subway_elevator_preview


ROOT_DIR = Path(__file__).resolve().parents[2]
ETL_DIR = ROOT_DIR / "etl"
RAW_DIR = ETL_DIR / "raw"
SHP_BASENAME = "N3L_A0020000_26"
SIDECARS = [".shp", ".shx", ".dbf", ".prj"]
DBF_ENCODINGS = ("cp949", "euc-kr", "utf-8")

OUTPUT_HTML = ETL_DIR / "segment_02c_centerline.html"
OUTPUT_GEOJSON = ETL_DIR / "segment_02c_centerline.geojson"
SIDELINE_OUTPUT_HTML = ETL_DIR / "segment_02c_sideline.html"
SIDELINE_OUTPUT_GEOJSON = ETL_DIR / "segment_02c_sideline.geojson"
INTERSECTION_OUTPUT_HTML = ETL_DIR / "segment_02c_sideline_intersection.html"
INTERSECTION_OUTPUT_GEOJSON = ETL_DIR / "segment_02c_sideline_intersection.geojson"
CANDIDATE_INTERSECTION_OUTPUT_HTML = ETL_DIR / "segment_02c_sideline_intersection_01.html"
CANDIDATE_INTERSECTION_OUTPUT_GEOJSON = ETL_DIR / "segment_02c_sideline_intersection_01.geojson"
NEAR_CROSS_INTERSECTION_OUTPUT_HTML = ETL_DIR / "segment_02c_sideline_intersection_02.html"
NEAR_CROSS_INTERSECTION_OUTPUT_GEOJSON = ETL_DIR / "segment_02c_sideline_intersection_02.geojson"
CLUSTERED_INTERSECTION_OUTPUT_HTML = ETL_DIR / "segment_02c_sideline_intersection_03.html"
CLUSTERED_INTERSECTION_OUTPUT_GEOJSON = ETL_DIR / "segment_02c_sideline_intersection_03.geojson"
GRAPH_MATERIALIZED_OUTPUT_HTML = ETL_DIR / "segment_02c_graph_materialized.html"
GRAPH_MATERIALIZED_OUTPUT_GEOJSON = ETL_DIR / "segment_02c_graph_materialized.geojson"
GRAPH_EDIT_OUTPUT_HTML = ETL_DIR / "segment_02c_graph_edit.html"
CENTERLINE_PRUNED_OUTPUT_HTML = ETL_DIR / "segment_02c_sideline_centerline_pruned.html"
CENTERLINE_PRUNED_OUTPUT_GEOJSON = ETL_DIR / "segment_02c_sideline_centerline_pruned.geojson"
ROAD_BOUNDARY_OUTPUT_HTML = ETL_DIR / "haeundae_road_boundary.html"
ROAD_BOUNDARY_OUTPUT_GEOJSON = ETL_DIR / "haeundae_road_boundary.geojson"

DEFAULT_CENTER_LAT = 35.1633200
DEFAULT_CENTER_LON = 129.1588705
DEFAULT_RADIUS_M = 5000

PROJECT_TO_WGS84 = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)
WGS84_TO_PROJECT = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
GEOD = Geod(ellps="GRS80")
MIN_LINE_LENGTH_M = 0.75
OFFSET_FLOOR_M = 1.0
INTERSECTION_NODE_PRECISION_M = 0.75
INTERSECTION_SPLIT_MIN_GAP_M = 0.75
CENTERLINE_CONTACT_MIN_M = 0.25
CENTERLINE_CONTACT_THRESHOLD_FACTOR = 1.2
CENTERLINE_CONTACT_EXTRA_M = 1.0
NEAR_OVERLAP_TOLERANCE_M = 1.25
NEAR_OVERLAP_MIN_LENGTH_M = 2.0
NEAR_OVERLAP_MAX_ANGLE_DEG = 20.0
NEAR_CROSS_TOLERANCE_M = 2.5
NEAR_CROSS_MIN_ANGLE_DEG = 25.0
ENDPOINT_SNAP_TOLERANCE_M = 2.5
NEAR_CROSS_03_TOLERANCE_M = 1.6
NEAR_CROSS_03_MIN_ANGLE_DEG = 35.0
ENDPOINT_SNAP_03_TOLERANCE_M = 1.6
JUNCTION_NODE_CLUSTER_RADIUS_M = 5.0
ENDPOINT_GRAPH_SNAP_RADIUS_M = 1.5
JUNCTION_CHAIN_PRUNE_FACTOR = 2.0
JUNCTION_CHAIN_PRUNE_EXTRA_M = 2.0
JUNCTION_CHAIN_PRUNE_MAX_M = 55.0
ROAD_BOUNDARY_MIN_HALF_WIDTH_M = 2.5
ROAD_BOUNDARY_FALLBACK_HALF_WIDTH_M = 4.0
ROAD_BOUNDARY_SIMPLIFY_M = 0.25
ROAD_BOUNDARY_EXTERIOR_AREA_MAX_M2 = 60_000.0
ROAD_BOUNDARY_CAP_MAX_M = 18.0
ROAD_BOUNDARY_CAP_MIN_ANGLE_DEG = 55.0
ROAD_BOUNDARY_CAP_MAX_ANGLE_DEG = 125.0
ROAD_BOUNDARY_CAP_SIDE_ALIGNMENT_DEG = 135.0
ROAD_BOUNDARY_INTERNAL_CAP_MAX_M = 36.0
ROAD_BOUNDARY_INTERNAL_CENTERLINE_MAX_M = 16.0
ROAD_BOUNDARY_INTERNAL_MIN_ANGLE_DEG = 60.0
ROAD_BOUNDARY_INTERNAL_MAX_ANGLE_DEG = 120.0


@dataclass(frozen=True)
class ProjectedSegment:
    segment_type: str
    source_index: int
    source_part: int
    road_width_meter: float | None
    offset_meter: float
    coords: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class CenterlineReference:
    source_index: int
    source_part: int
    coords: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class SplitPiece:
    segment: ProjectedSegment
    start_key: tuple[int, int]
    end_key: tuple[int, int]
    length_meter: float


def validate_sidecars() -> list[Path]:
    paths = [RAW_DIR / f"{SHP_BASENAME}{suffix}" for suffix in SIDECARS]
    missing = [path for path in paths if not path.exists()]
    if missing:
        missing_text = "\n".join(f"- {path}" for path in missing)
        raise FileNotFoundError(f"missing SHP sidecar files:\n{missing_text}")
    return paths


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
    if last_error is not None:
        raise last_error
    raise UnicodeDecodeError("unknown", b"", 0, 0, "failed to decode DBF")


def parse_optional_float(value: object) -> float | None:
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


def part_ranges(shape: shapefile.Shape) -> list[tuple[int, int]]:
    starts = list(shape.parts) + [len(shape.points)]
    return [(starts[index], starts[index + 1]) for index in range(len(starts) - 1)]


def project_center(center_lat: float, center_lon: float) -> tuple[float, float]:
    x, y = WGS84_TO_PROJECT.transform(center_lon, center_lat)
    return float(x), float(y)


def transform_projected_coords(points: Iterable[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
    source_points = list(points)
    if not source_points:
        return ()
    xs = [point[0] for point in source_points]
    ys = [point[1] for point in source_points]
    lons, lats = PROJECT_TO_WGS84.transform(xs, ys)
    return tuple((float(lon), float(lat)) for lon, lat in zip(lons, lats))


def transform_wgs84_coords(points: Iterable[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
    source_points = list(points)
    if not source_points:
        return ()
    lons = [point[0] for point in source_points]
    lats = [point[1] for point in source_points]
    xs, ys = WGS84_TO_PROJECT.transform(lons, lats)
    return tuple((float(x), float(y)) for x, y in zip(xs, ys))


def line_length_meter(coords: tuple[tuple[float, float], ...]) -> float:
    if len(coords) < 2:
        return 0.0
    lons = [coord[0] for coord in coords]
    lats = [coord[1] for coord in coords]
    return abs(float(GEOD.line_length(lons, lats)))


def projected_length_meter(coords: tuple[tuple[float, float], ...]) -> float:
    if len(coords) < 2:
        return 0.0
    return sum(
        ((right[0] - left[0]) ** 2 + (right[1] - left[1]) ** 2) ** 0.5
        for left, right in zip(coords, coords[1:])
    )


def dedupe_consecutive_coords(coords: tuple[tuple[float, float], ...]) -> tuple[tuple[float, float], ...]:
    if not coords:
        return ()
    deduped = [coords[0]]
    for coord in coords[1:]:
        if coord != deduped[-1]:
            deduped.append(coord)
    return tuple(deduped)


def iter_lines(geometry: object) -> Iterable[LineString]:
    if isinstance(geometry, LineString):
        yield geometry
        return
    if isinstance(geometry, MultiLineString):
        yield from geometry.geoms
        return
    if isinstance(geometry, GeometryCollection):
        for item in geometry.geoms:
            yield from iter_lines(item)


def iter_polygons(geometry: object) -> Iterable[Polygon]:
    if isinstance(geometry, Polygon):
        if not geometry.is_empty:
            yield geometry
        return
    if isinstance(geometry, MultiPolygon):
        for item in geometry.geoms:
            if not item.is_empty:
                yield item
        return
    if isinstance(geometry, GeometryCollection):
        for item in geometry.geoms:
            yield from iter_polygons(item)


def road_boundary_half_width(road_width_meter: float | None) -> float:
    if road_width_meter is None or road_width_meter <= 0:
        return ROAD_BOUNDARY_FALLBACK_HALF_WIDTH_M
    return max(road_width_meter / 2.0, ROAD_BOUNDARY_MIN_HALF_WIDTH_M)


def vector_angle_degree(left: tuple[float, float], right: tuple[float, float]) -> float:
    left_length = (left[0] * left[0] + left[1] * left[1]) ** 0.5
    right_length = (right[0] * right[0] + right[1] * right[1]) ** 0.5
    if left_length <= 0 or right_length <= 0:
        return 180.0
    value = max(-1.0, min(1.0, (left[0] * right[0] + left[1] * right[1]) / (left_length * right_length)))
    return acos(value) * 180.0 / pi


def ring_edge_vector(points: list[tuple[float, float]], index: int) -> tuple[float, float]:
    start = points[index]
    end = points[(index + 1) % len(points)]
    return end[0] - start[0], end[1] - start[1]


def is_boundary_cap_edge(points: list[tuple[float, float]], index: int) -> bool:
    current = ring_edge_vector(points, index)
    current_length = (current[0] * current[0] + current[1] * current[1]) ** 0.5
    if current_length > ROAD_BOUNDARY_CAP_MAX_M:
        return False
    previous = ring_edge_vector(points, (index - 1) % len(points))
    following = ring_edge_vector(points, (index + 1) % len(points))
    previous_angle = vector_angle_degree(previous, current)
    following_angle = vector_angle_degree(current, following)
    side_alignment = vector_angle_degree(previous, following)
    return (
        ROAD_BOUNDARY_CAP_MIN_ANGLE_DEG <= previous_angle <= ROAD_BOUNDARY_CAP_MAX_ANGLE_DEG
        and ROAD_BOUNDARY_CAP_MIN_ANGLE_DEG <= following_angle <= ROAD_BOUNDARY_CAP_MAX_ANGLE_DEG
        and side_alignment >= ROAD_BOUNDARY_CAP_SIDE_ALIGNMENT_DEG
    )


def split_boundary_ring(
    coords: tuple[tuple[float, float], ...],
    *,
    remove_caps: bool = True,
) -> list[tuple[tuple[float, float], ...]]:
    if len(coords) < 2:
        return []
    points = list(coords[:-1] if coords[0] == coords[-1] else coords)
    if len(points) < 2:
        return []
    remove_indexes = {
        index
        for index in range(len(points))
        if remove_caps and is_boundary_cap_edge(points, index)
    }
    if not remove_indexes:
        ring = tuple([*points, points[0]])
        return [ring] if projected_length_meter(ring) > MIN_LINE_LENGTH_M else []

    keep = [index not in remove_indexes for index in range(len(points))]
    chains: list[tuple[tuple[float, float], ...]] = []
    visited: set[int] = set()
    starts = [
        index
        for index, keep_edge in enumerate(keep)
        if keep_edge and not keep[(index - 1) % len(points)]
    ]
    for start in starts:
        if start in visited:
            continue
        chain = [points[start]]
        index = start
        while keep[index] and index not in visited:
            visited.add(index)
            chain.append(points[(index + 1) % len(points)])
            index = (index + 1) % len(points)
        chain_coords = tuple(chain)
        if len(chain_coords) >= 2 and projected_length_meter(chain_coords) > MIN_LINE_LENGTH_M:
            chains.append(chain_coords)
    return chains


def line_direction_at_distance(line: LineString, distance_along: float) -> tuple[float, float] | None:
    coords = list(line.coords)
    if len(coords) < 2:
        return None
    distance_left = max(0.0, min(distance_along, line.length))
    for left, right in zip(coords, coords[1:]):
        segment_vector = (float(right[0] - left[0]), float(right[1] - left[1]))
        segment_length = (segment_vector[0] * segment_vector[0] + segment_vector[1] * segment_vector[1]) ** 0.5
        if segment_length <= 0:
            continue
        if distance_left <= segment_length:
            return segment_vector
        distance_left -= segment_length
    left = coords[-2]
    right = coords[-1]
    return float(right[0] - left[0]), float(right[1] - left[1])


def nearest_centerline_direction(
    point: Point,
    centerline_geometries: list[LineString],
    centerline_tree: STRtree,
    *,
    search_radius_m: float = ROAD_BOUNDARY_INTERNAL_CENTERLINE_MAX_M,
) -> tuple[float, tuple[float, float] | None]:
    best_distance = float("inf")
    best_vector: tuple[float, float] | None = None
    for candidate in centerline_tree.query(point.buffer(search_radius_m)):
        index = int(candidate)
        line = centerline_geometries[index]
        distance_to_line = point.distance(line)
        if distance_to_line > search_radius_m or distance_to_line >= best_distance:
            continue
        direction = line_direction_at_distance(line, line.project(point))
        if direction is None:
            continue
        best_distance = distance_to_line
        best_vector = direction
    return best_distance, best_vector


def is_internal_perpendicular_boundary_edge(
    start: tuple[float, float],
    end: tuple[float, float],
    centerline_geometries: list[LineString],
    centerline_tree: STRtree,
) -> bool:
    edge_vector = (end[0] - start[0], end[1] - start[1])
    edge_length = (edge_vector[0] * edge_vector[0] + edge_vector[1] * edge_vector[1]) ** 0.5
    if edge_length > ROAD_BOUNDARY_INTERNAL_CAP_MAX_M:
        return False
    midpoint = Point((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
    distance_to_centerline, centerline_vector = nearest_centerline_direction(
        midpoint,
        centerline_geometries,
        centerline_tree,
    )
    if centerline_vector is None or distance_to_centerline > ROAD_BOUNDARY_INTERNAL_CENTERLINE_MAX_M:
        return False
    angle = vector_angle_degree(edge_vector, centerline_vector)
    angle = min(angle, 180.0 - angle)
    return (
        ROAD_BOUNDARY_INTERNAL_MIN_ANGLE_DEG
        <= angle
        <= min(90.0, ROAD_BOUNDARY_INTERNAL_MAX_ANGLE_DEG)
    )


def split_boundary_coords_by_removed_edges(
    coords: tuple[tuple[float, float], ...],
    remove_indexes: set[int],
) -> list[tuple[tuple[float, float], ...]]:
    if not remove_indexes:
        return [coords]
    if len(coords) < 2:
        return []
    closed = coords[0] == coords[-1]
    points = list(coords[:-1] if closed else coords)
    edge_count = len(points) if closed else len(points) - 1
    if edge_count <= 0:
        return []
    keep = [index not in remove_indexes for index in range(edge_count)]
    chains: list[tuple[tuple[float, float], ...]] = []
    if closed:
        starts = [index for index, keep_edge in enumerate(keep) if keep_edge and not keep[(index - 1) % edge_count]]
        visited: set[int] = set()
        for start in starts:
            chain = [points[start]]
            index = start
            while keep[index] and index not in visited:
                visited.add(index)
                chain.append(points[(index + 1) % len(points)])
                index = (index + 1) % edge_count
            chain_coords = tuple(chain)
            if len(chain_coords) >= 2 and projected_length_meter(chain_coords) > MIN_LINE_LENGTH_M:
                chains.append(chain_coords)
        return chains

    chain: list[tuple[float, float]] = []
    for index in range(edge_count):
        if keep[index]:
            if not chain:
                chain = [points[index]]
            chain.append(points[index + 1])
            continue
        chain_coords = tuple(chain)
        if len(chain_coords) >= 2 and projected_length_meter(chain_coords) > MIN_LINE_LENGTH_M:
            chains.append(chain_coords)
        chain = []
    chain_coords = tuple(chain)
    if len(chain_coords) >= 2 and projected_length_meter(chain_coords) > MIN_LINE_LENGTH_M:
        chains.append(chain_coords)
    return chains


def filter_internal_perpendicular_boundaries(
    boundary_lines: list[tuple[str, tuple[tuple[float, float], ...]]],
    centerline_geometries: list[LineString],
) -> tuple[list[tuple[str, tuple[tuple[float, float], ...]]], int]:
    if not boundary_lines or not centerline_geometries:
        return boundary_lines, 0
    centerline_tree = STRtree(centerline_geometries)
    filtered: list[tuple[str, tuple[tuple[float, float], ...]]] = []
    removed_edges = 0
    for segment_type, coords in boundary_lines:
        closed = len(coords) >= 2 and coords[0] == coords[-1]
        edge_count = len(coords) - 1
        if closed:
            edge_count = len(coords) - 1
        remove_indexes: set[int] = set()
        for index in range(edge_count):
            start = coords[index]
            end = coords[(index + 1) % len(coords)]
            if is_internal_perpendicular_boundary_edge(start, end, centerline_geometries, centerline_tree):
                remove_indexes.add(index)
        removed_edges += len(remove_indexes)
        for chain in split_boundary_coords_by_removed_edges(coords, remove_indexes):
            filtered.append((segment_type, chain))
    return filtered, removed_edges


def boundary_lines_from_surface(
    surface: object,
    *,
    exterior_area_max_m2: float | None = None,
    remove_caps: bool = True,
) -> list[tuple[str, tuple[tuple[float, float], ...]]]:
    boundary_lines: list[tuple[str, tuple[tuple[float, float], ...]]] = []
    for polygon in iter_polygons(surface):
        if exterior_area_max_m2 is None or polygon.area <= exterior_area_max_m2:
            exterior = dedupe_consecutive_coords(tuple((float(x), float(y)) for x, y in polygon.exterior.coords))
            for line_coords in split_boundary_ring(exterior, remove_caps=remove_caps):
                boundary_lines.append(("ROAD_BOUNDARY", line_coords))
        for interior in polygon.interiors:
            coords = dedupe_consecutive_coords(tuple((float(x), float(y)) for x, y in interior.coords))
            for line_coords in split_boundary_ring(coords, remove_caps=remove_caps):
                boundary_lines.append(("ROAD_BOUNDARY_INNER", line_coords))
    return boundary_lines


def offset_line_parts(
    coords: tuple[tuple[float, float], ...],
    offset_meter: float,
    *,
    side: str,
) -> list[tuple[tuple[float, float], ...]]:
    line = LineString(coords)
    if line.is_empty or line.length <= MIN_LINE_LENGTH_M:
        return []
    distance = offset_meter if side == "left" else -offset_meter
    offset_geometry = line.offset_curve(distance)
    parts: list[tuple[tuple[float, float], ...]] = []
    for part in iter_lines(offset_geometry):
        part_coords = dedupe_consecutive_coords(tuple((float(x), float(y)) for x, y in part.coords))
        if len(part_coords) >= 2 and projected_length_meter(part_coords) > MIN_LINE_LENGTH_M:
            parts.append(part_coords)
    return parts


def projected_point_key(point: tuple[float, float], precision_m: float = INTERSECTION_NODE_PRECISION_M) -> tuple[int, int]:
    return round(point[0] / precision_m), round(point[1] / precision_m)


def width_threshold(left: ProjectedSegment, right: ProjectedSegment) -> float:
    left_width = left.road_width_meter or (left.offset_meter * 2.0)
    right_width = right.road_width_meter or (right.offset_meter * 2.0)
    return max(left_width, right_width, OFFSET_FLOOR_M * 2.0)


def point_intersections(geometry: object) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    if isinstance(geometry, Point):
        if not geometry.is_empty:
            points.append((float(geometry.x), float(geometry.y)))
    elif isinstance(geometry, MultiPoint):
        for item in geometry.geoms:
            points.append((float(item.x), float(item.y)))
    elif isinstance(geometry, GeometryCollection):
        for item in geometry.geoms:
            points.extend(point_intersections(item))
    return points


def line_heading_radian(line: LineString) -> float | None:
    coords = list(line.coords)
    if len(coords) < 2:
        return None
    start = coords[0]
    end = coords[-1]
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = (dx * dx + dy * dy) ** 0.5
    if length <= 0:
        return None
    return acos(max(-1.0, min(1.0, dx / length))) if dy >= 0 else -acos(max(-1.0, min(1.0, dx / length)))


def lines_are_near_parallel(left: LineString, right: LineString) -> bool:
    left_heading = line_heading_radian(left)
    right_heading = line_heading_radian(right)
    if left_heading is None or right_heading is None:
        return False
    difference = abs(left_heading - right_heading) % pi
    difference = min(difference, pi - difference)
    return difference <= (NEAR_OVERLAP_MAX_ANGLE_DEG * pi / 180.0)


def heading_difference_degree(left: LineString, right: LineString) -> float | None:
    left_heading = line_heading_radian(left)
    right_heading = line_heading_radian(right)
    if left_heading is None or right_heading is None:
        return None
    difference = abs(left_heading - right_heading) % pi
    difference = min(difference, pi - difference)
    return difference * 180.0 / pi


def representative_line_points(geometry: object) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    if isinstance(geometry, LineString):
        if geometry.is_empty or geometry.length <= 0:
            return points
        start = geometry.interpolate(0.0)
        mid = geometry.interpolate(geometry.length / 2.0)
        end = geometry.interpolate(geometry.length)
        points.extend(
            [
                (float(start.x), float(start.y)),
                (float(mid.x), float(mid.y)),
                (float(end.x), float(end.y)),
            ]
        )
    elif isinstance(geometry, MultiLineString):
        for item in geometry.geoms:
            points.extend(representative_line_points(item))
    elif isinstance(geometry, GeometryCollection):
        for item in geometry.geoms:
            points.extend(representative_line_points(item))
    return points


def robust_intersection_points(left: LineString, right: LineString) -> tuple[list[tuple[float, float]], str]:
    intersection = left.intersection(right)
    points = point_intersections(intersection)
    if points:
        return points, "point"
    overlap_points = representative_line_points(intersection)
    if overlap_points:
        return overlap_points, "overlap"
    if left.distance(right) > NEAR_OVERLAP_TOLERANCE_M:
        return [], "none"
    if not lines_are_near_parallel(left, right):
        return [], "none"
    buffered_overlap = left.buffer(NEAR_OVERLAP_TOLERANCE_M).intersection(right)
    overlap_length = sum(line.length for line in iter_lines(buffered_overlap))
    if overlap_length < NEAR_OVERLAP_MIN_LENGTH_M:
        return [], "none"
    left_point, right_point = nearest_points(left, right)
    return [((float(left_point.x) + float(right_point.x)) / 2.0, (float(left_point.y) + float(right_point.y)) / 2.0)], "near_overlap"


def segment_width_meter(segment: ProjectedSegment) -> float:
    return max(segment.road_width_meter or (segment.offset_meter * 2.0), OFFSET_FLOOR_M * 2.0)


def is_interior_distance(line: LineString, distance_along: float) -> bool:
    return INTERSECTION_SPLIT_MIN_GAP_M < distance_along < line.length - INTERSECTION_SPLIT_MIN_GAP_M


def is_endpoint_snap_distance(
    line: LineString,
    distance_along: float,
    tolerance_meter: float = ENDPOINT_SNAP_TOLERANCE_M,
) -> bool:
    return min(distance_along, line.length - distance_along) <= tolerance_meter


def add_segment_intersection_candidate(
    *,
    left_index: int,
    right_index: int,
    left_geometry: LineString,
    right_geometry: LineString,
    left_split_point: tuple[float, float],
    right_split_point: tuple[float, float],
    display_point: tuple[float, float],
    threshold: float,
    reason: str,
    split_points_by_segment: dict[int, dict[tuple[int, int], tuple[float, float]]],
    node_points: dict[tuple[int, int], tuple[float, float]],
    node_thresholds: dict[tuple[int, int], float],
    stats: Counter[str],
    endpoint_snap_tolerance_meter: float = ENDPOINT_SNAP_TOLERANCE_M,
) -> None:
    left_distance = left_geometry.project(Point(left_split_point))
    right_distance = right_geometry.project(Point(right_split_point))
    left_allowed = is_interior_distance(left_geometry, left_distance) or is_endpoint_snap_distance(
        left_geometry, left_distance, endpoint_snap_tolerance_meter
    )
    right_allowed = is_interior_distance(right_geometry, right_distance) or is_endpoint_snap_distance(
        right_geometry, right_distance, endpoint_snap_tolerance_meter
    )
    if not left_allowed and not right_allowed:
        return

    key = projected_point_key(display_point)
    if key in node_points:
        stats["duplicateSuppressedCount"] += 1
    else:
        node_points[key] = display_point
    node_thresholds[key] = max(node_thresholds.get(key, 0.0), threshold)
    if left_allowed:
        split_points_by_segment.setdefault(left_index, {})[key] = left_split_point
    if right_allowed:
        split_points_by_segment.setdefault(right_index, {})[key] = right_split_point
    stats[reason] += 1
    if is_endpoint_snap_distance(left_geometry, left_distance, endpoint_snap_tolerance_meter) or is_endpoint_snap_distance(
        right_geometry, right_distance, endpoint_snap_tolerance_meter
    ):
        stats["endpointSnapCrossCount"] += 1


def find_sideline_intersections_robust(
    segments: list[ProjectedSegment],
) -> tuple[
    dict[int, dict[tuple[int, int], tuple[float, float]]],
    dict[tuple[int, int], tuple[float, float]],
    dict[tuple[int, int], float],
    dict[str, int],
]:
    geometries = [LineString(segment.coords) for segment in segments]
    tree = STRtree(geometries)
    split_points_by_segment: dict[int, dict[tuple[int, int], tuple[float, float]]] = {}
    node_points: dict[tuple[int, int], tuple[float, float]] = {}
    node_thresholds: dict[tuple[int, int], float] = {}
    stats = Counter(
        {
            "pointIntersectionCount": 0,
            "overlapIntersectionCount": 0,
            "nearOverlapIntersectionCount": 0,
            "candidatePairCount": 0,
        }
    )

    for left_index, left_geometry in enumerate(geometries):
        query_geometry = left_geometry.buffer(NEAR_OVERLAP_TOLERANCE_M)
        for candidate in tree.query(query_geometry):
            right_index = int(candidate)
            if right_index <= left_index:
                continue
            right_geometry = geometries[right_index]
            if not query_geometry.intersects(right_geometry):
                continue
            stats["candidatePairCount"] += 1
            points, reason = robust_intersection_points(left_geometry, right_geometry)
            if not points:
                continue
            threshold = width_threshold(segments[left_index], segments[right_index])
            for point in points:
                left_distance = left_geometry.project(Point(point))
                right_distance = right_geometry.project(Point(point))
                left_interior = is_interior_distance(left_geometry, left_distance)
                right_interior = is_interior_distance(right_geometry, right_distance)
                if not left_interior and not right_interior:
                    continue
                key = projected_point_key(point)
                node_points[key] = point
                node_thresholds[key] = max(node_thresholds.get(key, 0.0), threshold)
                if left_interior:
                    split_points_by_segment.setdefault(left_index, {})[key] = point
                if right_interior:
                    split_points_by_segment.setdefault(right_index, {})[key] = point
                if reason == "point":
                    stats["pointIntersectionCount"] += 1
                elif reason == "overlap":
                    stats["overlapIntersectionCount"] += 1
                elif reason == "near_overlap":
                    stats["nearOverlapIntersectionCount"] += 1

    return split_points_by_segment, node_points, node_thresholds, dict(stats)


def find_sideline_intersections_robust_02(
    segments: list[ProjectedSegment],
) -> tuple[
    dict[int, dict[tuple[int, int], tuple[float, float]]],
    dict[tuple[int, int], tuple[float, float]],
    dict[tuple[int, int], float],
    dict[str, int],
]:
    geometries = [LineString(segment.coords) for segment in segments]
    tree = STRtree(geometries)
    split_points_by_segment: dict[int, dict[tuple[int, int], tuple[float, float]]] = {}
    node_points: dict[tuple[int, int], tuple[float, float]] = {}
    node_thresholds: dict[tuple[int, int], float] = {}
    stats = Counter(
        {
            "pointIntersectionCount": 0,
            "overlapIntersectionCount": 0,
            "nearOverlapIntersectionCount": 0,
            "nearCrossCount": 0,
            "endpointSnapCrossCount": 0,
            "duplicateSuppressedCount": 0,
            "candidatePairCount": 0,
        }
    )
    query_tolerance = max(NEAR_OVERLAP_TOLERANCE_M, NEAR_CROSS_TOLERANCE_M)

    for left_index, left_geometry in enumerate(geometries):
        if left_geometry.length < MIN_LINE_LENGTH_M:
            continue
        query_geometry = left_geometry.buffer(query_tolerance)
        for candidate in tree.query(query_geometry):
            right_index = int(candidate)
            if right_index <= left_index:
                continue
            right_geometry = geometries[right_index]
            if right_geometry.length < MIN_LINE_LENGTH_M or not query_geometry.intersects(right_geometry):
                continue
            stats["candidatePairCount"] += 1
            threshold = width_threshold(segments[left_index], segments[right_index])
            points, reason = robust_intersection_points(left_geometry, right_geometry)
            if points:
                reason_key = {
                    "point": "pointIntersectionCount",
                    "overlap": "overlapIntersectionCount",
                    "near_overlap": "nearOverlapIntersectionCount",
                }[reason]
                for point in points:
                    add_segment_intersection_candidate(
                        left_index=left_index,
                        right_index=right_index,
                        left_geometry=left_geometry,
                        right_geometry=right_geometry,
                        left_split_point=point,
                        right_split_point=point,
                        display_point=point,
                        threshold=threshold,
                        reason=reason_key,
                        split_points_by_segment=split_points_by_segment,
                        node_points=node_points,
                        node_thresholds=node_thresholds,
                        stats=stats,
                    )
                continue

            if (
                segments[left_index].source_index == segments[right_index].source_index
                and segments[left_index].source_part == segments[right_index].source_part
            ):
                continue
            if left_geometry.distance(right_geometry) > NEAR_CROSS_TOLERANCE_M:
                continue
            angle_difference = heading_difference_degree(left_geometry, right_geometry)
            if angle_difference is None or angle_difference < NEAR_CROSS_MIN_ANGLE_DEG:
                continue
            left_point, right_point = nearest_points(left_geometry, right_geometry)
            left_split_point = (float(left_point.x), float(left_point.y))
            right_split_point = (float(right_point.x), float(right_point.y))
            display_point = (
                (left_split_point[0] + right_split_point[0]) / 2.0,
                (left_split_point[1] + right_split_point[1]) / 2.0,
            )
            add_segment_intersection_candidate(
                left_index=left_index,
                right_index=right_index,
                left_geometry=left_geometry,
                right_geometry=right_geometry,
                left_split_point=left_split_point,
                right_split_point=right_split_point,
                display_point=display_point,
                threshold=threshold,
                reason="nearCrossCount",
                split_points_by_segment=split_points_by_segment,
                node_points=node_points,
                node_thresholds=node_thresholds,
                stats=stats,
            )

    stats["clusteredIntersectionNodeCount"] = len(node_points)
    return split_points_by_segment, node_points, node_thresholds, dict(stats)


def find_sideline_intersections_robust_03(
    segments: list[ProjectedSegment],
) -> tuple[
    dict[int, dict[tuple[int, int], tuple[float, float]]],
    dict[tuple[int, int], tuple[float, float]],
    dict[tuple[int, int], float],
    dict[str, int],
]:
    geometries = [LineString(segment.coords) for segment in segments]
    tree = STRtree(geometries)
    split_points_by_segment: dict[int, dict[tuple[int, int], tuple[float, float]]] = {}
    node_points: dict[tuple[int, int], tuple[float, float]] = {}
    node_thresholds: dict[tuple[int, int], float] = {}
    stats = Counter(
        {
            "pointIntersectionCount": 0,
            "overlapIntersectionCount": 0,
            "nearOverlapIntersectionCount": 0,
            "nearCrossCount": 0,
            "endpointSnapCrossCount": 0,
            "duplicateSuppressedCount": 0,
            "candidatePairCount": 0,
        }
    )
    query_tolerance = max(NEAR_OVERLAP_TOLERANCE_M, NEAR_CROSS_03_TOLERANCE_M)

    for left_index, left_geometry in enumerate(geometries):
        if left_geometry.length < MIN_LINE_LENGTH_M:
            continue
        query_geometry = left_geometry.buffer(query_tolerance)
        for candidate in tree.query(query_geometry):
            right_index = int(candidate)
            if right_index <= left_index:
                continue
            right_geometry = geometries[right_index]
            if right_geometry.length < MIN_LINE_LENGTH_M or not query_geometry.intersects(right_geometry):
                continue
            stats["candidatePairCount"] += 1
            threshold = width_threshold(segments[left_index], segments[right_index])
            points, reason = robust_intersection_points(left_geometry, right_geometry)
            if points:
                reason_key = {
                    "point": "pointIntersectionCount",
                    "overlap": "overlapIntersectionCount",
                    "near_overlap": "nearOverlapIntersectionCount",
                }[reason]
                for point in points:
                    add_segment_intersection_candidate(
                        left_index=left_index,
                        right_index=right_index,
                        left_geometry=left_geometry,
                        right_geometry=right_geometry,
                        left_split_point=point,
                        right_split_point=point,
                        display_point=point,
                        threshold=threshold,
                        reason=reason_key,
                        split_points_by_segment=split_points_by_segment,
                        node_points=node_points,
                        node_thresholds=node_thresholds,
                        stats=stats,
                        endpoint_snap_tolerance_meter=ENDPOINT_SNAP_03_TOLERANCE_M,
                    )
                continue

            if (
                segments[left_index].source_index == segments[right_index].source_index
                and segments[left_index].source_part == segments[right_index].source_part
            ):
                continue
            if left_geometry.distance(right_geometry) > NEAR_CROSS_03_TOLERANCE_M:
                continue
            angle_difference = heading_difference_degree(left_geometry, right_geometry)
            if angle_difference is None or angle_difference < NEAR_CROSS_03_MIN_ANGLE_DEG:
                continue
            left_point, right_point = nearest_points(left_geometry, right_geometry)
            left_split_point = (float(left_point.x), float(left_point.y))
            right_split_point = (float(right_point.x), float(right_point.y))
            display_point = (
                (left_split_point[0] + right_split_point[0]) / 2.0,
                (left_split_point[1] + right_split_point[1]) / 2.0,
            )
            add_segment_intersection_candidate(
                left_index=left_index,
                right_index=right_index,
                left_geometry=left_geometry,
                right_geometry=right_geometry,
                left_split_point=left_split_point,
                right_split_point=right_split_point,
                display_point=display_point,
                threshold=threshold,
                reason="nearCrossCount",
                split_points_by_segment=split_points_by_segment,
                node_points=node_points,
                node_thresholds=node_thresholds,
                stats=stats,
                endpoint_snap_tolerance_meter=ENDPOINT_SNAP_03_TOLERANCE_M,
            )

    stats["rawIntersectionNodeCount"] = len(node_points)
    return split_points_by_segment, node_points, node_thresholds, dict(stats)


def squared_distance(left: tuple[float, float], right: tuple[float, float]) -> float:
    return (left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2


def cluster_intersection_candidates(
    split_points_by_segment: dict[int, dict[tuple[int, int], tuple[float, float]]],
    node_points: dict[tuple[int, int], tuple[float, float]],
    node_thresholds: dict[tuple[int, int], float],
    *,
    radius_meter: float = JUNCTION_NODE_CLUSTER_RADIUS_M,
) -> tuple[
    dict[int, dict[tuple[int, int], tuple[float, float]]],
    dict[tuple[int, int], tuple[float, float]],
    dict[tuple[int, int], float],
    dict[str, int],
]:
    keys = list(node_points)
    parent = list(range(len(keys)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    radius_squared = radius_meter * radius_meter
    for index, key in enumerate(keys):
        point = node_points[key]
        cell = (floor(point[0] / radius_meter), floor(point[1] / radius_meter))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other_index in grid.get((cell[0] + dx, cell[1] + dy), []):
                    if squared_distance(point, node_points[keys[other_index]]) <= radius_squared:
                        union(index, other_index)
        grid[cell].append(index)

    groups: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for index, key in enumerate(keys):
        groups[find(index)].append(key)

    original_to_cluster: dict[tuple[int, int], tuple[int, int]] = {}
    clustered_node_points: dict[tuple[int, int], tuple[float, float]] = {}
    clustered_thresholds: dict[tuple[int, int], float] = {}
    max_cluster_size = 0
    for group_keys in groups.values():
        max_cluster_size = max(max_cluster_size, len(group_keys))
        x = sum(node_points[key][0] for key in group_keys) / len(group_keys)
        y = sum(node_points[key][1] for key in group_keys) / len(group_keys)
        cluster_key = projected_point_key((x, y))
        while cluster_key in clustered_node_points:
            cluster_key = (cluster_key[0] + 1, cluster_key[1])
        clustered_node_points[cluster_key] = (x, y)
        clustered_thresholds[cluster_key] = max(node_thresholds.get(key, 0.0) for key in group_keys)
        for key in group_keys:
            original_to_cluster[key] = cluster_key

    clustered_split_points: dict[int, dict[tuple[int, int], tuple[float, float]]] = {}
    for segment_index, points_by_key in split_points_by_segment.items():
        for original_key, split_point in points_by_key.items():
            cluster_key = original_to_cluster.get(original_key)
            if cluster_key is None:
                continue
            existing = clustered_split_points.setdefault(segment_index, {}).get(cluster_key)
            if existing is None:
                clustered_split_points[segment_index][cluster_key] = split_point
                continue
            cluster_point = clustered_node_points[cluster_key]
            if squared_distance(split_point, cluster_point) < squared_distance(existing, cluster_point):
                clustered_split_points[segment_index][cluster_key] = split_point

    return clustered_split_points, clustered_node_points, clustered_thresholds, {
        "rawIntersectionNodeCount": len(node_points),
        "clusteredIntersectionNodeCount": len(clustered_node_points),
        "clusterReductionCount": len(node_points) - len(clustered_node_points),
        "maxIntersectionClusterSize": max_cluster_size,
        "junctionNodeClusterRadiusMeter": int(radius_meter) if radius_meter.is_integer() else radius_meter,
    }


def split_segments_for_junctions(
    segments: list[ProjectedSegment],
    split_points_by_segment: dict[int, dict[tuple[int, int], tuple[float, float]]],
) -> list[SplitPiece]:
    pieces: list[SplitPiece] = []
    for segment_index, segment in enumerate(segments):
        line = LineString(segment.coords)
        split_points = split_points_by_segment.get(segment_index, {})
        distance_points: dict[float, tuple[float, float]] = {}
        for point in split_points.values():
            distance_along = line.project(Point(point))
            if is_interior_distance(line, distance_along):
                distance_points[distance_along] = point
        distances = [0.0, *sorted(distance_points), line.length]
        for start, end in zip(distances, distances[1:]):
            if end - start <= MIN_LINE_LENGTH_M:
                continue
            piece = substring(line, start, end)
            for piece_line in iter_lines(piece):
                coords = dedupe_consecutive_coords(tuple((float(x), float(y)) for x, y in piece_line.coords))
                if len(coords) < 2 or projected_length_meter(coords) <= MIN_LINE_LENGTH_M:
                    continue
                pieces.append(
                    SplitPiece(
                        segment=ProjectedSegment(
                            segment_type=segment.segment_type,
                            source_index=segment.source_index,
                            source_part=segment.source_part,
                            road_width_meter=segment.road_width_meter,
                            offset_meter=segment.offset_meter,
                            coords=coords,
                        ),
                        start_key=projected_point_key(coords[0]),
                        end_key=projected_point_key(coords[-1]),
                        length_meter=projected_length_meter(coords),
                    )
                )
    return pieces


def split_segments_for_junctions_02(
    segments: list[ProjectedSegment],
    split_points_by_segment: dict[int, dict[tuple[int, int], tuple[float, float]]],
) -> list[SplitPiece]:
    pieces: list[SplitPiece] = []
    for segment_index, segment in enumerate(segments):
        line = LineString(segment.coords)
        split_points = split_points_by_segment.get(segment_index, {})
        distance_nodes: dict[float, tuple[tuple[int, int], tuple[float, float]]] = {}
        start_node_key: tuple[int, int] | None = None
        end_node_key: tuple[int, int] | None = None
        for node_key, point in split_points.items():
            distance_along = line.project(Point(point))
            if is_interior_distance(line, distance_along):
                distance_nodes[distance_along] = (node_key, point)
            elif distance_along <= ENDPOINT_SNAP_TOLERANCE_M:
                start_node_key = node_key
            elif line.length - distance_along <= ENDPOINT_SNAP_TOLERANCE_M:
                end_node_key = node_key

        distances = [0.0, *sorted(distance_nodes), line.length]
        for start, end in zip(distances, distances[1:]):
            if end - start <= MIN_LINE_LENGTH_M:
                continue
            piece = substring(line, start, end)
            for piece_line in iter_lines(piece):
                coords = dedupe_consecutive_coords(tuple((float(x), float(y)) for x, y in piece_line.coords))
                if len(coords) < 2 or projected_length_meter(coords) <= MIN_LINE_LENGTH_M:
                    continue
                if start in distance_nodes:
                    start_key = distance_nodes[start][0]
                elif start == 0.0 and start_node_key is not None:
                    start_key = start_node_key
                else:
                    start_key = projected_point_key(coords[0])
                if end in distance_nodes:
                    end_key = distance_nodes[end][0]
                elif end == line.length and end_node_key is not None:
                    end_key = end_node_key
                else:
                    end_key = projected_point_key(coords[-1])
                pieces.append(
                    SplitPiece(
                        segment=ProjectedSegment(
                            segment_type=segment.segment_type,
                            source_index=segment.source_index,
                            source_part=segment.source_part,
                            road_width_meter=segment.road_width_meter,
                            offset_meter=segment.offset_meter,
                            coords=coords,
                        ),
                        start_key=start_key,
                        end_key=end_key,
                        length_meter=projected_length_meter(coords),
                    )
                )
    return pieces


def piece_other_key(piece: SplitPiece, key: tuple[int, int]) -> tuple[int, int]:
    return piece.end_key if key == piece.start_key else piece.start_key


def prune_dangling_junction_chains(
    pieces: list[SplitPiece],
    intersection_keys: set[tuple[int, int]],
    node_thresholds: dict[tuple[int, int], float],
) -> tuple[list[ProjectedSegment], dict[str, int]]:
    adjacency: dict[tuple[int, int], list[int]] = defaultdict(list)
    for index, piece in enumerate(pieces):
        adjacency[piece.start_key].append(index)
        adjacency[piece.end_key].append(index)

    remove_piece_indexes: set[int] = set()
    chain_prune_count = 0
    chain_piece_prune_count = 0
    for start_key in sorted(intersection_keys):
        threshold = min(
            max(node_thresholds.get(start_key, OFFSET_FLOOR_M * 2.0) * JUNCTION_CHAIN_PRUNE_FACTOR + JUNCTION_CHAIN_PRUNE_EXTRA_M, 0.0),
            JUNCTION_CHAIN_PRUNE_MAX_M,
        )
        for start_piece_index in adjacency.get(start_key, []):
            if start_piece_index in remove_piece_indexes:
                continue
            chain: list[int] = []
            total_length = 0.0
            current_key = start_key
            current_piece_index = start_piece_index
            seen_piece_indexes: set[int] = set()
            while True:
                if current_piece_index in seen_piece_indexes or current_piece_index in remove_piece_indexes:
                    break
                seen_piece_indexes.add(current_piece_index)
                piece = pieces[current_piece_index]
                chain.append(current_piece_index)
                total_length += piece.length_meter
                if total_length > threshold:
                    break
                next_key = piece_other_key(piece, current_key)
                if next_key in intersection_keys:
                    break
                next_piece_indexes = [
                    candidate
                    for candidate in adjacency.get(next_key, [])
                    if candidate != current_piece_index and candidate not in remove_piece_indexes
                ]
                if not next_piece_indexes:
                    remove_piece_indexes.update(chain)
                    chain_prune_count += 1
                    chain_piece_prune_count += len(chain)
                    break
                if len(next_piece_indexes) > 1:
                    break
                current_key = next_key
                current_piece_index = next_piece_indexes[0]

    cleaned = [piece.segment for index, piece in enumerate(pieces) if index not in remove_piece_indexes]
    return cleaned, {
        "junctionChainPruneCount": chain_prune_count,
        "junctionChainPiecePruneCount": chain_piece_prune_count,
    }


def split_and_prune_sideline_intersection_01(
    segments: list[ProjectedSegment],
) -> tuple[list[ProjectedSegment], list[dict[str, Any]], dict[str, int]]:
    if not segments:
        return [], [], {
            "intersectionNodeCount": 0,
            "junctionChainPruneCount": 0,
            "junctionChainPiecePruneCount": 0,
            "splitPieceCount": 0,
        }

    split_points_by_segment, node_points, node_thresholds, intersection_stats = find_sideline_intersections_robust(
        segments
    )
    split_pieces = split_segments_for_junctions(segments, split_points_by_segment)
    cleaned_segments, prune_stats = prune_dangling_junction_chains(
        split_pieces,
        set(node_points.keys()),
        node_thresholds,
    )
    node_features = intersection_node_features(node_points, source="sideline_intersection_01")
    return cleaned_segments, node_features, {
        "intersectionNodeCount": len(node_features),
        "splitPieceCount": len(split_pieces),
        **intersection_stats,
        **prune_stats,
    }


def split_and_prune_sideline_intersection_02(
    segments: list[ProjectedSegment],
) -> tuple[list[ProjectedSegment], list[dict[str, Any]], dict[str, int]]:
    if not segments:
        return [], [], {
            "intersectionNodeCount": 0,
            "nearCrossCount": 0,
            "endpointSnapCrossCount": 0,
            "junctionChainPruneCount": 0,
            "junctionChainPiecePruneCount": 0,
            "splitPieceCount": 0,
        }

    split_points_by_segment, node_points, node_thresholds, intersection_stats = (
        find_sideline_intersections_robust_02(segments)
    )
    split_pieces = split_segments_for_junctions_02(segments, split_points_by_segment)
    cleaned_segments, prune_stats = prune_dangling_junction_chains(
        split_pieces,
        set(node_points.keys()),
        node_thresholds,
    )
    node_features = intersection_node_features(node_points, source="sideline_intersection_02")
    return cleaned_segments, node_features, {
        "intersectionNodeCount": len(node_features),
        "splitPieceCount": len(split_pieces),
        **intersection_stats,
        **prune_stats,
    }


def split_and_prune_sideline_intersection_03(
    segments: list[ProjectedSegment],
) -> tuple[list[ProjectedSegment], list[dict[str, Any]], dict[str, int]]:
    if not segments:
        return [], [], {
            "intersectionNodeCount": 0,
            "nearCrossCount": 0,
            "endpointSnapCrossCount": 0,
            "clusterReductionCount": 0,
            "junctionChainPruneCount": 0,
            "junctionChainPiecePruneCount": 0,
            "splitPieceCount": 0,
        }

    split_points_by_segment, node_points, node_thresholds, intersection_stats = (
        find_sideline_intersections_robust_03(segments)
    )
    clustered_split_points, clustered_node_points, clustered_thresholds, cluster_stats = (
        cluster_intersection_candidates(split_points_by_segment, node_points, node_thresholds)
    )
    split_pieces = split_segments_for_junctions_02(segments, clustered_split_points)
    cleaned_segments, prune_stats = prune_dangling_junction_chains(
        split_pieces,
        set(clustered_node_points.keys()),
        clustered_thresholds,
    )
    node_features = intersection_node_features(clustered_node_points, source="sideline_intersection_03")
    return cleaned_segments, node_features, {
        "intersectionNodeCount": len(node_features),
        "splitPieceCount": len(split_pieces),
        **intersection_stats,
        **cluster_stats,
        **prune_stats,
    }


def find_sideline_intersections(
    segments: list[ProjectedSegment],
) -> tuple[dict[int, dict[tuple[int, int], tuple[float, float]]], dict[tuple[int, int], tuple[float, float]]]:
    geometries = [LineString(segment.coords) for segment in segments]
    tree = STRtree(geometries)
    split_points_by_segment: dict[int, dict[tuple[int, int], tuple[float, float]]] = {}
    node_points: dict[tuple[int, int], tuple[float, float]] = {}

    for left_index, left_geometry in enumerate(geometries):
        for candidate in tree.query(left_geometry):
            right_index = int(candidate)
            if right_index <= left_index:
                continue
            right_geometry = geometries[right_index]
            if not left_geometry.intersects(right_geometry):
                continue
            for point in point_intersections(left_geometry.intersection(right_geometry)):
                left_distance = left_geometry.project(Point(point))
                right_distance = right_geometry.project(Point(point))
                if (
                    left_distance <= INTERSECTION_SPLIT_MIN_GAP_M
                    or left_distance >= left_geometry.length - INTERSECTION_SPLIT_MIN_GAP_M
                    or right_distance <= INTERSECTION_SPLIT_MIN_GAP_M
                    or right_distance >= right_geometry.length - INTERSECTION_SPLIT_MIN_GAP_M
                ):
                    continue
                key = projected_point_key(point)
                node_points[key] = point
                split_points_by_segment.setdefault(left_index, {})[key] = point
                split_points_by_segment.setdefault(right_index, {})[key] = point
    return split_points_by_segment, node_points


def build_centerline_references(
    *,
    center_lat: float = DEFAULT_CENTER_LAT,
    center_lon: float = DEFAULT_CENTER_LON,
    radius_m: int = DEFAULT_RADIUS_M,
) -> list[CenterlineReference]:
    validate_sidecars()
    reader, _encoding = open_reader()
    center_x, center_y = project_center(center_lat, center_lon)
    clip_circle = Point(center_x, center_y).buffer(radius_m, resolution=64)

    centerlines: list[CenterlineReference] = []
    for source_index, shape in enumerate(reader.iterShapes(), start=1):
        if shape.bbox and not box(*shape.bbox).intersects(clip_circle):
            continue
        for part_index, (start, end) in enumerate(part_ranges(shape), start=1):
            points = dedupe_consecutive_coords(tuple((float(x), float(y)) for x, y in shape.points[start:end]))
            if len(points) < 2:
                continue
            line = LineString(points)
            if line.is_empty or line.length <= MIN_LINE_LENGTH_M or not line.intersects(clip_circle):
                continue
            clipped = line.intersection(clip_circle)
            for clipped_line in iter_lines(clipped):
                coords = dedupe_consecutive_coords(tuple((float(x), float(y)) for x, y in clipped_line.coords))
                if len(coords) >= 2 and projected_length_meter(coords) > MIN_LINE_LENGTH_M:
                    centerlines.append(
                        CenterlineReference(source_index=source_index, source_part=part_index, coords=coords)
                    )
    return centerlines


def intersection_node_features(node_points: dict[tuple[int, int], tuple[float, float]], *, source: str) -> list[dict[str, Any]]:
    node_features: list[dict[str, Any]] = []
    for vertex_id, (key, point) in enumerate(sorted(node_points.items()), start=1):
        lon, lat = transform_projected_coords([point])[0]
        node_features.append(
            {
                "type": "Feature",
                "properties": {
                    "vertexId": vertex_id,
                    "nodeType": "INTERSECTION",
                    "source": source,
                    "projectedKey": f"{key[0]}:{key[1]}",
                },
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
            }
        )
    return node_features


def split_piece_at_centerline_contact(
    piece: LineString,
    *,
    node_at_start: bool,
    segment: ProjectedSegment,
    centerline_references: list[CenterlineReference],
    centerline_geometries: list[LineString],
    centerline_tree: STRtree,
) -> tuple[list[tuple[tuple[float, float], ...]], bool]:
    threshold = max(
        segment.road_width_meter or (segment.offset_meter * 2.0),
        OFFSET_FLOOR_M * 2.0,
    )
    threshold = threshold * CENTERLINE_CONTACT_THRESHOLD_FACTOR + CENTERLINE_CONTACT_EXTRA_M
    best_piece_distance: float | None = None
    best_from_node: float | None = None

    for candidate in centerline_tree.query(piece):
        centerline_index = int(candidate)
        centerline_reference = centerline_references[centerline_index]
        if (
            centerline_reference.source_index == segment.source_index
            and centerline_reference.source_part == segment.source_part
        ):
            continue
        centerline_geometry = centerline_geometries[centerline_index]
        if not piece.intersects(centerline_geometry):
            continue
        for point in point_intersections(piece.intersection(centerline_geometry)):
            piece_distance = piece.project(Point(point))
            from_node = piece_distance if node_at_start else piece.length - piece_distance
            if from_node <= CENTERLINE_CONTACT_MIN_M or from_node > threshold:
                continue
            if best_from_node is None or from_node < best_from_node:
                best_from_node = from_node
                best_piece_distance = piece_distance

    if best_piece_distance is None:
        coords = dedupe_consecutive_coords(tuple((float(x), float(y)) for x, y in piece.coords))
        return [coords], False

    if node_at_start:
        keep_start, keep_end = best_piece_distance, piece.length
    else:
        keep_start, keep_end = 0.0, best_piece_distance
    if keep_end - keep_start <= MIN_LINE_LENGTH_M:
        return [], True

    kept_parts: list[tuple[tuple[float, float], ...]] = []
    kept = substring(piece, keep_start, keep_end)
    for kept_line in iter_lines(kept):
        coords = dedupe_consecutive_coords(tuple((float(x), float(y)) for x, y in kept_line.coords))
        if len(coords) >= 2 and projected_length_meter(coords) > MIN_LINE_LENGTH_M:
            kept_parts.append(coords)
    return kept_parts, True


def split_and_prune_by_centerline_contacts(
    segments: list[ProjectedSegment],
    centerline_references: list[CenterlineReference],
) -> tuple[list[ProjectedSegment], list[dict[str, Any]], dict[str, int]]:
    if not segments:
        return [], [], {
            "intersectionNodeCount": 0,
            "centerlineContactPruneCount": 0,
            "centerlineReferenceCount": len(centerline_references),
            "splitPieceCount": 0,
        }

    split_points_by_segment, node_points = find_sideline_intersections(segments)
    centerline_geometries = [LineString(reference.coords) for reference in centerline_references]
    centerline_tree = STRtree(centerline_geometries) if centerline_geometries else None

    cleaned: list[ProjectedSegment] = []
    prune_count = 0
    split_piece_count = 0
    for segment_index, segment in enumerate(segments):
        line = LineString(segment.coords)
        split_points = split_points_by_segment.get(segment_index, {})
        if not split_points:
            cleaned.append(segment)
            continue

        distance_points: dict[float, tuple[float, float]] = {}
        for point in split_points.values():
            distance_along = line.project(Point(point))
            if distance_along <= INTERSECTION_SPLIT_MIN_GAP_M or distance_along >= line.length - INTERSECTION_SPLIT_MIN_GAP_M:
                continue
            distance_points[distance_along] = point

        distances = [0.0, *sorted(distance_points), line.length]
        for start, end in zip(distances, distances[1:]):
            if end - start <= MIN_LINE_LENGTH_M:
                continue
            piece = substring(line, start, end)
            start_is_node = start in distance_points
            end_is_node = end in distance_points
            piece_parts: list[tuple[tuple[float, float], ...]]
            pruned_piece = False

            if centerline_tree is not None and start_is_node != end_is_node:
                piece_parts, pruned_piece = split_piece_at_centerline_contact(
                    piece,
                    node_at_start=start_is_node,
                    segment=segment,
                    centerline_references=centerline_references,
                    centerline_geometries=centerline_geometries,
                    centerline_tree=centerline_tree,
                )
            else:
                piece_parts = [
                    dedupe_consecutive_coords(tuple((float(x), float(y)) for x, y in piece_line.coords))
                    for piece_line in iter_lines(piece)
                ]

            if pruned_piece:
                prune_count += 1
            for coords in piece_parts:
                if len(coords) < 2 or projected_length_meter(coords) <= MIN_LINE_LENGTH_M:
                    continue
                split_piece_count += 1
                cleaned.append(
                    ProjectedSegment(
                        segment_type=segment.segment_type,
                        source_index=segment.source_index,
                        source_part=segment.source_part,
                        road_width_meter=segment.road_width_meter,
                        offset_meter=segment.offset_meter,
                        coords=coords,
                    )
                )

    node_features = intersection_node_features(node_points, source="sideline_centerline_contact")
    return cleaned, node_features, {
        "intersectionNodeCount": len(node_features),
        "centerlineContactPruneCount": prune_count,
        "centerlineReferenceCount": len(centerline_references),
        "splitPieceCount": split_piece_count,
    }


def split_and_prune_at_intersections(
    segments: list[ProjectedSegment],
) -> tuple[list[ProjectedSegment], list[dict[str, Any]], dict[str, int]]:
    if not segments:
        return [], [], {"intersectionNodeCount": 0, "tailPruneCount": 0}

    geometries = [LineString(segment.coords) for segment in segments]
    tree = STRtree(geometries)
    split_points_by_segment: dict[int, dict[tuple[int, int], tuple[tuple[float, float], float]]] = {}
    node_points: dict[tuple[int, int], tuple[float, float]] = {}

    for left_index, left_geometry in enumerate(geometries):
        for candidate in tree.query(left_geometry):
            right_index = int(candidate)
            if right_index <= left_index:
                continue
            right_geometry = geometries[right_index]
            if not left_geometry.intersects(right_geometry):
                continue
            threshold = width_threshold(segments[left_index], segments[right_index])
            for point in point_intersections(left_geometry.intersection(right_geometry)):
                left_distance = left_geometry.project(Point(point))
                right_distance = right_geometry.project(Point(point))
                if (
                    left_distance <= INTERSECTION_SPLIT_MIN_GAP_M
                    or left_distance >= left_geometry.length - INTERSECTION_SPLIT_MIN_GAP_M
                    or right_distance <= INTERSECTION_SPLIT_MIN_GAP_M
                    or right_distance >= right_geometry.length - INTERSECTION_SPLIT_MIN_GAP_M
                ):
                    continue
                key = projected_point_key(point)
                node_points[key] = point
                for segment_index in (left_index, right_index):
                    split_points_by_segment.setdefault(segment_index, {})
                    existing = split_points_by_segment[segment_index].get(key)
                    if existing is None or threshold > existing[1]:
                        split_points_by_segment[segment_index][key] = (point, threshold)

    pruned: list[ProjectedSegment] = []
    tail_prune_count = 0
    split_piece_count = 0
    for segment_index, segment in enumerate(segments):
        line = geometries[segment_index]
        split_points = split_points_by_segment.get(segment_index, {})
        if not split_points:
            pruned.append(segment)
            continue
        distance_thresholds: dict[float, float] = {}
        for point, threshold in split_points.values():
            distance_along = line.project(Point(point))
            if distance_along <= INTERSECTION_SPLIT_MIN_GAP_M or distance_along >= line.length - INTERSECTION_SPLIT_MIN_GAP_M:
                continue
            existing = distance_thresholds.get(distance_along)
            if existing is None or threshold > existing:
                distance_thresholds[distance_along] = threshold
        distances = [0.0, *sorted(distance_thresholds), line.length]
        for start, end in zip(distances, distances[1:]):
            if end - start <= MIN_LINE_LENGTH_M:
                continue
            start_is_intersection = start in distance_thresholds
            end_is_intersection = end in distance_thresholds
            touches_original_endpoint = start == 0.0 or end == line.length
            touches_intersection = start_is_intersection or end_is_intersection
            threshold = 0.0
            if start_is_intersection:
                threshold = max(threshold, distance_thresholds[start])
            if end_is_intersection:
                threshold = max(threshold, distance_thresholds[end])
            if touches_original_endpoint and touches_intersection and end - start < threshold:
                tail_prune_count += 1
                continue
            piece = substring(line, start, end)
            for piece_line in iter_lines(piece):
                coords = dedupe_consecutive_coords(tuple((float(x), float(y)) for x, y in piece_line.coords))
                if len(coords) >= 2 and projected_length_meter(coords) > MIN_LINE_LENGTH_M:
                    split_piece_count += 1
                    pruned.append(
                        ProjectedSegment(
                            segment_type=segment.segment_type,
                            source_index=segment.source_index,
                            source_part=segment.source_part,
                            road_width_meter=segment.road_width_meter,
                            offset_meter=segment.offset_meter,
                            coords=coords,
                        )
                    )

    node_features: list[dict[str, Any]] = []
    for vertex_id, (key, point) in enumerate(sorted(node_points.items()), start=1):
        lon, lat = transform_projected_coords([point])[0]
        node_features.append(
            {
                "type": "Feature",
                "properties": {
                    "vertexId": vertex_id,
                    "nodeType": "INTERSECTION",
                    "source": "sideline_intersection",
                    "projectedKey": f"{key[0]}:{key[1]}",
                },
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
            }
        )
    return pruned, node_features, {
        "intersectionNodeCount": len(node_features),
        "tailPruneCount": tail_prune_count,
        "splitPieceCount": split_piece_count,
    }


def build_payload(
    *,
    center_lat: float = DEFAULT_CENTER_LAT,
    center_lon: float = DEFAULT_CENTER_LON,
    radius_m: int = DEFAULT_RADIUS_M,
) -> dict[str, Any]:
    validate_sidecars()
    reader, encoding = open_reader()
    center_x, center_y = project_center(center_lat, center_lon)
    clip_circle = Point(center_x, center_y).buffer(radius_m, resolution=64)

    segment_features: list[dict[str, Any]] = []
    skipped_parts = 0
    clipped_parts = 0
    edge_id = 1

    for source_index, shape in enumerate(reader.iterShapes(), start=1):
        for part_index, (start, end) in enumerate(part_ranges(shape), start=1):
            points = tuple((float(x), float(y)) for x, y in shape.points[start:end])
            if len(points) < 2:
                skipped_parts += 1
                continue
            line = LineString(points)
            if line.is_empty or line.length <= 0 or not line.intersects(clip_circle):
                continue
            clipped = line.intersection(clip_circle)
            for clipped_line in iter_lines(clipped):
                clipped_coords = tuple((float(x), float(y)) for x, y in clipped_line.coords)
                coords = transform_projected_coords(clipped_coords)
                length_meter = line_length_meter(coords)
                if len(coords) < 2 or length_meter <= MIN_LINE_LENGTH_M:
                    skipped_parts += 1
                    continue
                clipped_parts += 1
                segment_features.append(
                    {
                        "type": "Feature",
                        "properties": {
                            "edgeId": edge_id,
                            "segmentType": "CENTERLINE",
                            "sourceIndex": source_index,
                            "sourcePart": part_index,
                            "lengthMeter": round(length_meter, 2),
                        },
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [list(point) for point in coords],
                        },
                    }
                )
                edge_id += 1

    segment_counts = Counter(feature["properties"]["segmentType"] for feature in segment_features)
    return {
        "meta": {
            "title": "02C Haeundae 5km Raw Centerline Preview",
            "centerLat": center_lat,
            "centerLon": center_lon,
            "radiusMeter": radius_m,
            "sourceShp": str(RAW_DIR / f"{SHP_BASENAME}.shp"),
            "sourceEncoding": encoding,
            "outputHtml": str(OUTPUT_HTML),
            "outputGeojson": str(OUTPUT_GEOJSON),
            "localhostUrl": f"http://127.0.0.1:3000/etl/{OUTPUT_HTML.name}",
            "stage": "02c-step0-raw-centerline",
            "sourceShapeCount": len(reader),
            "clippedPartCount": clipped_parts,
            "skippedPartCount": skipped_parts,
        },
        "summary": {
            "nodeCount": 0,
            "segmentCount": len(segment_features),
            "segmentTypeCounts": [{"name": name, "count": count} for name, count in sorted(segment_counts.items())],
            "transitionConnectorCount": 0,
            "gapBridgeCount": 0,
            "cornerBridgeCount": 0,
            "sameSideCornerBridgeCount": 0,
            "crossSideCornerBridgeCount": 0,
            "crossingCount": 0,
            "elevatorConnectorCount": 0,
        },
        "layers": {
            "roadNodes": {"type": "FeatureCollection", "features": []},
            "roadSegments": {"type": "FeatureCollection", "features": segment_features},
        },
    }


def build_sideline_payload(
    *,
    center_lat: float = DEFAULT_CENTER_LAT,
    center_lon: float = DEFAULT_CENTER_LON,
    radius_m: int = DEFAULT_RADIUS_M,
) -> dict[str, Any]:
    validate_sidecars()
    reader, encoding = open_reader()
    fields = [field[0] for field in reader.fields[1:]]
    width_index = fields.index("RVWD")
    center_x, center_y = project_center(center_lat, center_lon)
    clip_circle = Point(center_x, center_y).buffer(radius_m, resolution=64)

    segment_features: list[dict[str, Any]] = []
    skipped_parts = 0
    clipped_parts = 0
    offset_part_count = 0
    edge_id = 1

    for source_index, shape_record in enumerate(reader.iterShapeRecords(), start=1):
        shape = shape_record.shape
        record = shape_record.record
        road_width_meter = parse_optional_float(record[width_index])
        offset_meter = max((road_width_meter or 0.0) / 2.0, OFFSET_FLOOR_M)
        if shape.bbox and not box(*shape.bbox).buffer(offset_meter + 1.0).intersects(clip_circle):
            continue
        for part_index, (start, end) in enumerate(part_ranges(shape), start=1):
            points = dedupe_consecutive_coords(tuple((float(x), float(y)) for x, y in shape.points[start:end]))
            if len(points) < 2:
                skipped_parts += 1
                continue
            centerline = LineString(points)
            if centerline.is_empty or centerline.length <= 0:
                skipped_parts += 1
                continue
            if centerline.distance(Point(center_x, center_y)) > radius_m + offset_meter + 10.0:
                continue
            for segment_type, side_name in (("SIDE_LEFT", "left"), ("SIDE_RIGHT", "right")):
                for side_coords in offset_line_parts(points, offset_meter, side=side_name):
                    side_line = LineString(side_coords)
                    if not side_line.intersects(clip_circle):
                        continue
                    clipped = side_line.intersection(clip_circle)
                    for clipped_line in iter_lines(clipped):
                        clipped_coords = dedupe_consecutive_coords(
                            tuple((float(x), float(y)) for x, y in clipped_line.coords)
                        )
                        coords = transform_projected_coords(clipped_coords)
                        length_meter = line_length_meter(coords)
                        if len(coords) < 2 or length_meter <= MIN_LINE_LENGTH_M:
                            skipped_parts += 1
                            continue
                        clipped_parts += 1
                        offset_part_count += 1
                        segment_features.append(
                            {
                                "type": "Feature",
                                "properties": {
                                    "edgeId": edge_id,
                                    "segmentType": segment_type,
                                    "sourceIndex": source_index,
                                    "sourcePart": part_index,
                                    "roadWidthMeter": road_width_meter,
                                    "offsetMeter": round(offset_meter, 2),
                                    "lengthMeter": round(length_meter, 2),
                                },
                                "geometry": {
                                    "type": "LineString",
                                    "coordinates": [list(point) for point in coords],
                                },
                            }
                        )
                        edge_id += 1

    segment_counts = Counter(feature["properties"]["segmentType"] for feature in segment_features)
    return {
        "meta": {
            "title": "02C Haeundae 5km Raw Sideline Preview",
            "centerLat": center_lat,
            "centerLon": center_lon,
            "radiusMeter": radius_m,
            "sourceShp": str(RAW_DIR / f"{SHP_BASENAME}.shp"),
            "sourceEncoding": encoding,
            "outputHtml": str(SIDELINE_OUTPUT_HTML),
            "outputGeojson": str(SIDELINE_OUTPUT_GEOJSON),
            "localhostUrl": f"http://127.0.0.1:3000/etl/{SIDELINE_OUTPUT_HTML.name}",
            "stage": "02c-step1-raw-sideline",
            "sourceShapeCount": len(reader),
            "clippedPartCount": clipped_parts,
            "offsetPartCount": offset_part_count,
            "skippedPartCount": skipped_parts,
            "offsetRule": "offsetMeter = max(RVWD / 2, 1.0m)",
        },
        "summary": {
            "nodeCount": 0,
            "segmentCount": len(segment_features),
            "segmentTypeCounts": [{"name": name, "count": count} for name, count in sorted(segment_counts.items())],
            "transitionConnectorCount": 0,
            "gapBridgeCount": 0,
            "cornerBridgeCount": 0,
            "sameSideCornerBridgeCount": 0,
            "crossSideCornerBridgeCount": 0,
            "crossingCount": 0,
            "elevatorConnectorCount": 0,
        },
        "layers": {
            "roadNodes": {"type": "FeatureCollection", "features": []},
            "roadSegments": {"type": "FeatureCollection", "features": segment_features},
        },
    }


def build_road_boundary_payload(
    *,
    center_lat: float = DEFAULT_CENTER_LAT,
    center_lon: float = DEFAULT_CENTER_LON,
    radius_m: int = DEFAULT_RADIUS_M,
) -> dict[str, Any]:
    validate_sidecars()
    reader, encoding = open_reader()
    fields = [field[0] for field in reader.fields[1:]]
    width_index = fields.index("RVWD")
    center_x, center_y = project_center(center_lat, center_lon)
    clip_circle = Point(center_x, center_y).buffer(radius_m, resolution=64)

    road_surfaces = []
    centerline_geometries: list[LineString] = []
    clipped_parts = 0
    skipped_parts = 0
    buffered_parts = 0
    width_fallback_count = 0

    for source_index, shape_record in enumerate(reader.iterShapeRecords(), start=1):
        shape = shape_record.shape
        record = shape_record.record
        road_width_meter = parse_optional_float(record[width_index])
        half_width = road_boundary_half_width(road_width_meter)
        if road_width_meter is None or road_width_meter <= 0:
            width_fallback_count += 1
        if shape.bbox and not box(*shape.bbox).buffer(half_width + 1.0).intersects(clip_circle):
            continue
        for start, end in part_ranges(shape):
            points = dedupe_consecutive_coords(tuple((float(x), float(y)) for x, y in shape.points[start:end]))
            if len(points) < 2:
                skipped_parts += 1
                continue
            centerline = LineString(points)
            if centerline.is_empty or centerline.length <= MIN_LINE_LENGTH_M or not centerline.intersects(clip_circle):
                continue
            clipped = centerline.intersection(clip_circle)
            for clipped_line in iter_lines(clipped):
                clipped_coords = dedupe_consecutive_coords(tuple((float(x), float(y)) for x, y in clipped_line.coords))
                if len(clipped_coords) < 2 or projected_length_meter(clipped_coords) <= MIN_LINE_LENGTH_M:
                    skipped_parts += 1
                    continue
                clipped_parts += 1
                clipped_centerline = LineString(clipped_coords)
                centerline_geometries.append(clipped_centerline)
                surface = clipped_centerline.buffer(
                    half_width,
                    cap_style=2,
                    join_style=2,
                    mitre_limit=2.0,
                    resolution=4,
                )
                if surface.is_empty:
                    skipped_parts += 1
                    continue
                road_surfaces.append(surface)
                buffered_parts += 1

    merged_surface = unary_union(road_surfaces) if road_surfaces else GeometryCollection()
    if ROAD_BOUNDARY_SIMPLIFY_M > 0:
        merged_surface = merged_surface.simplify(ROAD_BOUNDARY_SIMPLIFY_M, preserve_topology=True)

    raw_boundary_lines = boundary_lines_from_surface(
        merged_surface,
        exterior_area_max_m2=None,
        remove_caps=True,
    )
    boundary_lines, internal_perpendicular_prune_count = filter_internal_perpendicular_boundaries(
        raw_boundary_lines,
        centerline_geometries,
    )

    segment_features: list[dict[str, Any]] = []
    edge_id = 1
    for segment_type, projected_coords in boundary_lines:
        coords = transform_projected_coords(projected_coords)
        length_meter = line_length_meter(coords)
        if len(coords) < 2 or length_meter <= MIN_LINE_LENGTH_M:
            skipped_parts += 1
            continue
        segment_features.append(
            {
                "type": "Feature",
                "properties": {
                    "edgeId": edge_id,
                    "segmentType": segment_type,
                    "lengthMeter": round(length_meter, 2),
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [list(point) for point in coords],
                },
            }
        )
        edge_id += 1

    segment_counts = Counter(feature["properties"]["segmentType"] for feature in segment_features)
    return {
        "meta": {
            "title": "Haeundae 5km Road Boundary Preview",
            "centerLat": center_lat,
            "centerLon": center_lon,
            "radiusMeter": radius_m,
            "sourceShp": str(RAW_DIR / f"{SHP_BASENAME}.shp"),
            "sourceEncoding": encoding,
            "outputHtml": str(ROAD_BOUNDARY_OUTPUT_HTML),
            "outputGeojson": str(ROAD_BOUNDARY_OUTPUT_GEOJSON),
            "localhostUrl": f"http://127.0.0.1:3000/etl/{ROAD_BOUNDARY_OUTPUT_HTML.name}",
            "stage": "road-boundary-buffer-union",
            "sourceShapeCount": len(reader),
            "clippedPartCount": clipped_parts,
            "bufferedPartCount": buffered_parts,
            "skippedPartCount": skipped_parts,
            "widthFallbackCount": width_fallback_count,
            "boundaryRule": (
                "buffer clipped centerlines by RVWD/2, union all road surfaces, then render polygon boundary rings"
            ),
            "halfWidthRule": (
                f"halfWidth=max(RVWD/2,{ROAD_BOUNDARY_MIN_HALF_WIDTH_M}m); "
                f"fallback={ROAD_BOUNDARY_FALLBACK_HALF_WIDTH_M}m"
            ),
            "simplifyMeter": ROAD_BOUNDARY_SIMPLIFY_M,
            "exteriorAreaMaxMeter2": None,
            "capRemovalMaxMeter": ROAD_BOUNDARY_CAP_MAX_M,
            "internalPerpendicularPruneCount": internal_perpendicular_prune_count,
            "internalPerpendicularMaxMeter": ROAD_BOUNDARY_INTERNAL_CAP_MAX_M,
            "internalPerpendicularCenterlineMaxMeter": ROAD_BOUNDARY_INTERNAL_CENTERLINE_MAX_M,
        },
        "summary": {
            "nodeCount": 0,
            "segmentCount": len(segment_features),
            "segmentTypeCounts": [{"name": name, "count": count} for name, count in sorted(segment_counts.items())],
            "transitionConnectorCount": 0,
            "gapBridgeCount": 0,
            "cornerBridgeCount": 0,
            "sameSideCornerBridgeCount": 0,
            "crossSideCornerBridgeCount": 0,
            "crossingCount": 0,
            "elevatorConnectorCount": 0,
        },
        "layers": {
            "roadNodes": {"type": "FeatureCollection", "features": []},
            "roadSegments": {"type": "FeatureCollection", "features": segment_features},
        },
    }


def projected_segments_from_payload(payload: dict[str, Any]) -> list[ProjectedSegment]:
    projected_segments: list[ProjectedSegment] = []
    for feature in payload["layers"]["roadSegments"]["features"]:
        props = feature["properties"]
        coords = transform_wgs84_coords(tuple((float(lon), float(lat)) for lon, lat in feature["geometry"]["coordinates"]))
        if len(coords) < 2 or projected_length_meter(coords) <= MIN_LINE_LENGTH_M:
            continue
        projected_segments.append(
            ProjectedSegment(
                segment_type=str(props["segmentType"]),
                source_index=int(props["sourceIndex"]),
                source_part=int(props["sourcePart"]),
                road_width_meter=parse_optional_float(props.get("roadWidthMeter")),
                offset_meter=float(props.get("offsetMeter") or OFFSET_FLOOR_M),
                coords=coords,
            )
        )
    return projected_segments


def segment_features_from_projected(segments: list[ProjectedSegment]) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    for edge_id, segment in enumerate(segments, start=1):
        coords = transform_projected_coords(segment.coords)
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "edgeId": edge_id,
                    "segmentType": segment.segment_type,
                    "sourceIndex": segment.source_index,
                    "sourcePart": segment.source_part,
                    "roadWidthMeter": segment.road_width_meter,
                    "offsetMeter": round(segment.offset_meter, 2),
                    "lengthMeter": round(line_length_meter(coords), 2),
                },
                "geometry": {"type": "LineString", "coordinates": [list(point) for point in coords]},
            }
        )
    return features


def materialize_endpoint_graph(
    segments: list[ProjectedSegment],
    *,
    snap_radius_meter: float = ENDPOINT_GRAPH_SNAP_RADIUS_M,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    endpoint_records: list[tuple[int, int, tuple[float, float]]] = []
    for segment_index, segment in enumerate(segments):
        if len(segment.coords) < 2 or projected_length_meter(segment.coords) <= MIN_LINE_LENGTH_M:
            continue
        endpoint_records.append((segment_index, 0, segment.coords[0]))
        endpoint_records.append((segment_index, 1, segment.coords[-1]))

    if not endpoint_records:
        return [], [], {
            "endpointGraphSnapRadiusMeter": snap_radius_meter,
            "rawEndpointCount": 0,
            "endpointNodeCount": 0,
            "endpointClusterReductionCount": 0,
            "maxEndpointClusterSize": 0,
            "snappedSegmentCount": 0,
            "droppedDegenerateSegmentCount": 0,
        }

    parent = list(range(len(endpoint_records)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    cell_size = snap_radius_meter
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for endpoint_index, (_segment_index, _end_index, point) in enumerate(endpoint_records):
        cell = (floor(point[0] / cell_size), floor(point[1] / cell_size))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other_index in grid.get((cell[0] + dx, cell[1] + dy), []):
                    if squared_distance(point, endpoint_records[other_index][2]) <= snap_radius_meter**2:
                        union(endpoint_index, other_index)
        grid[cell].append(endpoint_index)

    clusters: dict[int, list[int]] = defaultdict(list)
    for endpoint_index in range(len(endpoint_records)):
        clusters[find(endpoint_index)].append(endpoint_index)

    cluster_items = sorted(
        clusters.values(),
        key=lambda indexes: (
            min(endpoint_records[index][2][0] for index in indexes),
            min(endpoint_records[index][2][1] for index in indexes),
            min(indexes),
        ),
    )

    endpoint_to_vertex: dict[tuple[int, int], int] = {}
    vertex_points: dict[int, tuple[float, float]] = {}
    cluster_sizes: dict[int, int] = {}
    for vertex_id, indexes in enumerate(cluster_items, start=1):
        x = sum(endpoint_records[index][2][0] for index in indexes) / len(indexes)
        y = sum(endpoint_records[index][2][1] for index in indexes) / len(indexes)
        vertex_points[vertex_id] = (x, y)
        cluster_sizes[vertex_id] = len(indexes)
        for endpoint_index in indexes:
            segment_index, end_index, _point = endpoint_records[endpoint_index]
            endpoint_to_vertex[(segment_index, end_index)] = vertex_id

    degrees: Counter[int] = Counter()
    segment_features: list[dict[str, Any]] = []
    dropped_degenerate_count = 0
    for edge_id, segment_index in enumerate(sorted({record[0] for record in endpoint_records}), start=1):
        segment = segments[segment_index]
        from_node_id = endpoint_to_vertex[(segment_index, 0)]
        to_node_id = endpoint_to_vertex[(segment_index, 1)]
        if from_node_id == to_node_id:
            dropped_degenerate_count += 1
            continue
        snapped_coords = (
            vertex_points[from_node_id],
            *segment.coords[1:-1],
            vertex_points[to_node_id],
        )
        if projected_length_meter(snapped_coords) <= MIN_LINE_LENGTH_M:
            dropped_degenerate_count += 1
            continue
        degrees[from_node_id] += 1
        degrees[to_node_id] += 1
        wgs84_coords = transform_projected_coords(snapped_coords)
        segment_features.append(
            {
                "type": "Feature",
                "properties": {
                    "edgeId": len(segment_features) + 1,
                    "fromNodeId": from_node_id,
                    "toNodeId": to_node_id,
                    "segmentType": segment.segment_type,
                    "sourceIndex": segment.source_index,
                    "sourcePart": segment.source_part,
                    "roadWidthMeter": segment.road_width_meter,
                    "offsetMeter": round(segment.offset_meter, 2),
                    "lengthMeter": round(line_length_meter(wgs84_coords), 2),
                },
                "geometry": {"type": "LineString", "coordinates": [list(point) for point in wgs84_coords]},
            }
        )

    node_features: list[dict[str, Any]] = []
    for vertex_id in sorted(vertex_points):
        point = vertex_points[vertex_id]
        lon, lat = transform_projected_coords((point,))[0]
        node_features.append(
            {
                "type": "Feature",
                "properties": {
                    "vertexId": vertex_id,
                    "sourceNodeKey": f"02c_endpoint_graph:{projected_point_key(point)[0]}:{projected_point_key(point)[1]}",
                    "nodeType": "GRAPH_ENDPOINT",
                    "degree": degrees[vertex_id],
                    "endpointCount": cluster_sizes[vertex_id],
                    "projectedKey": f"{projected_point_key(point)[0]}:{projected_point_key(point)[1]}",
                },
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
            }
        )

    return node_features, segment_features, {
        "endpointGraphSnapRadiusMeter": snap_radius_meter,
        "rawEndpointCount": len(endpoint_records),
        "endpointNodeCount": len(node_features),
        "endpointClusterReductionCount": len(endpoint_records) - len(node_features),
        "maxEndpointClusterSize": max(cluster_sizes.values(), default=0),
        "snappedSegmentCount": len(segment_features),
        "droppedDegenerateSegmentCount": dropped_degenerate_count,
    }


def build_sideline_intersection_payload(
    *,
    center_lat: float = DEFAULT_CENTER_LAT,
    center_lon: float = DEFAULT_CENTER_LON,
    radius_m: int = DEFAULT_RADIUS_M,
) -> dict[str, Any]:
    base_payload = build_sideline_payload(center_lat=center_lat, center_lon=center_lon, radius_m=radius_m)
    projected_segments = projected_segments_from_payload(base_payload)
    cleaned_segments, node_features, intersection_stats = split_and_prune_at_intersections(projected_segments)
    segment_features = segment_features_from_projected(cleaned_segments)
    segment_counts = Counter(feature["properties"]["segmentType"] for feature in segment_features)
    meta = dict(base_payload["meta"])
    meta.update(
        {
            "title": "02C Haeundae 5km Sideline Intersection Preview",
            "outputHtml": str(INTERSECTION_OUTPUT_HTML),
            "outputGeojson": str(INTERSECTION_OUTPUT_GEOJSON),
            "localhostUrl": f"http://127.0.0.1:3000/etl/{INTERSECTION_OUTPUT_HTML.name}",
            "stage": "02c-step2-sideline-intersection",
            "intersectionRule": "split SIDE_LEFT/SIDE_RIGHT intersections; prune original-end tail if tail length < max(intersecting road widths)",
            **intersection_stats,
        }
    )
    return {
        "meta": meta,
        "summary": {
            "nodeCount": len(node_features),
            "segmentCount": len(segment_features),
            "segmentTypeCounts": [{"name": name, "count": count} for name, count in sorted(segment_counts.items())],
            "transitionConnectorCount": 0,
            "gapBridgeCount": 0,
            "cornerBridgeCount": 0,
            "sameSideCornerBridgeCount": 0,
            "crossSideCornerBridgeCount": 0,
            "crossingCount": 0,
            "elevatorConnectorCount": 0,
        },
        "layers": {
            "roadNodes": {"type": "FeatureCollection", "features": node_features},
            "roadSegments": {"type": "FeatureCollection", "features": segment_features},
        },
    }


def build_sideline_intersection_01_payload(
    *,
    center_lat: float = DEFAULT_CENTER_LAT,
    center_lon: float = DEFAULT_CENTER_LON,
    radius_m: int = DEFAULT_RADIUS_M,
) -> dict[str, Any]:
    base_payload = build_sideline_payload(center_lat=center_lat, center_lon=center_lon, radius_m=radius_m)
    projected_segments = projected_segments_from_payload(base_payload)
    cleaned_segments, node_features, intersection_stats = split_and_prune_sideline_intersection_01(projected_segments)
    segment_features = segment_features_from_projected(cleaned_segments)
    segment_counts = Counter(feature["properties"]["segmentType"] for feature in segment_features)
    meta = dict(base_payload["meta"])
    meta.update(
        {
            "title": "02C Haeundae 5km Sideline Intersection 01 Preview",
            "outputHtml": str(CANDIDATE_INTERSECTION_OUTPUT_HTML),
            "outputGeojson": str(CANDIDATE_INTERSECTION_OUTPUT_GEOJSON),
            "localhostUrl": f"http://127.0.0.1:3000/etl/{CANDIDATE_INTERSECTION_OUTPUT_HTML.name}",
            "stage": "02c-step2c-sideline-intersection-01",
            "intersectionRule": (
                "split raw sideline at point intersections, linear overlap representatives, and near-parallel "
                "near-overlap representatives"
            ),
            "pruneRule": (
                "from robust intersection nodes, remove connected dangling chains whose cumulative length stays "
                "within local wider-road threshold"
            ),
            "nearOverlapToleranceMeter": NEAR_OVERLAP_TOLERANCE_M,
            "junctionChainPruneMaxMeter": JUNCTION_CHAIN_PRUNE_MAX_M,
            **intersection_stats,
        }
    )
    return {
        "meta": meta,
        "summary": {
            "nodeCount": len(node_features),
            "segmentCount": len(segment_features),
            "segmentTypeCounts": [{"name": name, "count": count} for name, count in sorted(segment_counts.items())],
            "transitionConnectorCount": 0,
            "gapBridgeCount": 0,
            "cornerBridgeCount": 0,
            "sameSideCornerBridgeCount": 0,
            "crossSideCornerBridgeCount": 0,
            "crossingCount": 0,
            "elevatorConnectorCount": 0,
        },
        "layers": {
            "roadNodes": {"type": "FeatureCollection", "features": node_features},
            "roadSegments": {"type": "FeatureCollection", "features": segment_features},
        },
    }


def build_sideline_intersection_02_payload(
    *,
    center_lat: float = DEFAULT_CENTER_LAT,
    center_lon: float = DEFAULT_CENTER_LON,
    radius_m: int = DEFAULT_RADIUS_M,
) -> dict[str, Any]:
    base_payload = build_sideline_payload(center_lat=center_lat, center_lon=center_lon, radius_m=radius_m)
    projected_segments = projected_segments_from_payload(base_payload)
    cleaned_segments, node_features, intersection_stats = split_and_prune_sideline_intersection_02(projected_segments)
    segment_features = segment_features_from_projected(cleaned_segments)
    segment_counts = Counter(feature["properties"]["segmentType"] for feature in segment_features)
    meta = dict(base_payload["meta"])
    meta.update(
        {
            "title": "02C Haeundae 5km Sideline Intersection 02 Preview",
            "outputHtml": str(NEAR_CROSS_INTERSECTION_OUTPUT_HTML),
            "outputGeojson": str(NEAR_CROSS_INTERSECTION_OUTPUT_GEOJSON),
            "localhostUrl": f"http://127.0.0.1:3000/etl/{NEAR_CROSS_INTERSECTION_OUTPUT_HTML.name}",
            "stage": "02c-step2d-sideline-intersection-02",
            "intersectionRule": (
                "split raw sideline at point/overlap/near-overlap intersections plus non-parallel near-cross "
                "and endpoint-snap candidates"
            ),
            "pruneRule": (
                "from robust intersection nodes, remove connected dangling chains whose cumulative length stays "
                "within local wider-road threshold"
            ),
            "nearOverlapToleranceMeter": NEAR_OVERLAP_TOLERANCE_M,
            "nearCrossToleranceMeter": NEAR_CROSS_TOLERANCE_M,
            "nearCrossMinAngleDegree": NEAR_CROSS_MIN_ANGLE_DEG,
            "endpointSnapToleranceMeter": ENDPOINT_SNAP_TOLERANCE_M,
            "junctionChainPruneMaxMeter": JUNCTION_CHAIN_PRUNE_MAX_M,
            **intersection_stats,
        }
    )
    return {
        "meta": meta,
        "summary": {
            "nodeCount": len(node_features),
            "segmentCount": len(segment_features),
            "segmentTypeCounts": [{"name": name, "count": count} for name, count in sorted(segment_counts.items())],
            "transitionConnectorCount": 0,
            "gapBridgeCount": 0,
            "cornerBridgeCount": 0,
            "sameSideCornerBridgeCount": 0,
            "crossSideCornerBridgeCount": 0,
            "crossingCount": 0,
            "elevatorConnectorCount": 0,
        },
        "layers": {
            "roadNodes": {"type": "FeatureCollection", "features": node_features},
            "roadSegments": {"type": "FeatureCollection", "features": segment_features},
        },
    }


def build_sideline_intersection_03_payload(
    *,
    center_lat: float = DEFAULT_CENTER_LAT,
    center_lon: float = DEFAULT_CENTER_LON,
    radius_m: int = DEFAULT_RADIUS_M,
) -> dict[str, Any]:
    base_payload = build_sideline_payload(center_lat=center_lat, center_lon=center_lon, radius_m=radius_m)
    projected_segments = projected_segments_from_payload(base_payload)
    cleaned_segments, node_features, intersection_stats = split_and_prune_sideline_intersection_03(projected_segments)
    segment_features = segment_features_from_projected(cleaned_segments)
    segment_counts = Counter(feature["properties"]["segmentType"] for feature in segment_features)
    meta = dict(base_payload["meta"])
    meta.update(
        {
            "title": "02C Haeundae 5km Sideline Intersection 03 Preview",
            "outputHtml": str(CLUSTERED_INTERSECTION_OUTPUT_HTML),
            "outputGeojson": str(CLUSTERED_INTERSECTION_OUTPUT_GEOJSON),
            "localhostUrl": f"http://127.0.0.1:3000/etl/{CLUSTERED_INTERSECTION_OUTPUT_HTML.name}",
            "stage": "02c-step2e-sideline-intersection-03",
            "intersectionRule": (
                "split raw sideline with conservative near-cross detection, then collapse nearby intersection "
                "candidates into one marker per junction pocket"
            ),
            "pruneRule": (
                "from clustered junction nodes, remove connected dangling chains whose cumulative length stays "
                "within local wider-road threshold"
            ),
            "nearOverlapToleranceMeter": NEAR_OVERLAP_TOLERANCE_M,
            "nearCrossToleranceMeter": NEAR_CROSS_03_TOLERANCE_M,
            "nearCrossMinAngleDegree": NEAR_CROSS_03_MIN_ANGLE_DEG,
            "endpointSnapToleranceMeter": ENDPOINT_SNAP_03_TOLERANCE_M,
            "junctionChainPruneMaxMeter": JUNCTION_CHAIN_PRUNE_MAX_M,
            **intersection_stats,
        }
    )
    return {
        "meta": meta,
        "summary": {
            "nodeCount": len(node_features),
            "segmentCount": len(segment_features),
            "segmentTypeCounts": [{"name": name, "count": count} for name, count in sorted(segment_counts.items())],
            "transitionConnectorCount": 0,
            "gapBridgeCount": 0,
            "cornerBridgeCount": 0,
            "sameSideCornerBridgeCount": 0,
            "crossSideCornerBridgeCount": 0,
            "crossingCount": 0,
            "elevatorConnectorCount": 0,
        },
        "layers": {
            "roadNodes": {"type": "FeatureCollection", "features": node_features},
            "roadSegments": {"type": "FeatureCollection", "features": segment_features},
        },
    }


def build_graph_materialized_payload(
    *,
    center_lat: float = DEFAULT_CENTER_LAT,
    center_lon: float = DEFAULT_CENTER_LON,
    radius_m: int = DEFAULT_RADIUS_M,
) -> dict[str, Any]:
    base_payload = build_sideline_intersection_03_payload(
        center_lat=center_lat,
        center_lon=center_lon,
        radius_m=radius_m,
    )
    projected_segments = projected_segments_from_payload(base_payload)
    node_features, segment_features, graph_stats = materialize_endpoint_graph(projected_segments)
    segment_counts = Counter(feature["properties"]["segmentType"] for feature in segment_features)
    meta = dict(base_payload["meta"])
    meta.update(
        {
            "title": "02C Haeundae 5km Materialized Endpoint Graph Preview",
            "outputHtml": str(GRAPH_MATERIALIZED_OUTPUT_HTML),
            "outputGeojson": str(GRAPH_MATERIALIZED_OUTPUT_GEOJSON),
            "localhostUrl": f"http://127.0.0.1:3000/etl/{GRAPH_MATERIALIZED_OUTPUT_HTML.name}",
            "stage": "02c-step2f-endpoint-graph-materialized",
            "graphMaterializeRule": (
                "create nodes from every segment endpoint, cluster endpoints within snap radius, snap segment "
                "start/end coordinates to clustered node points, and assign fromNodeId/toNodeId"
            ),
            **graph_stats,
        }
    )
    return {
        "meta": meta,
        "summary": {
            "nodeCount": len(node_features),
            "segmentCount": len(segment_features),
            "segmentTypeCounts": [{"name": name, "count": count} for name, count in sorted(segment_counts.items())],
            "transitionConnectorCount": 0,
            "gapBridgeCount": 0,
            "cornerBridgeCount": 0,
            "sameSideCornerBridgeCount": 0,
            "crossSideCornerBridgeCount": 0,
            "crossingCount": 0,
            "elevatorConnectorCount": 0,
        },
        "layers": {
            "roadNodes": {"type": "FeatureCollection", "features": node_features},
            "roadSegments": {"type": "FeatureCollection", "features": segment_features},
        },
    }


def build_sideline_centerline_pruned_payload(
    *,
    center_lat: float = DEFAULT_CENTER_LAT,
    center_lon: float = DEFAULT_CENTER_LON,
    radius_m: int = DEFAULT_RADIUS_M,
) -> dict[str, Any]:
    base_payload = build_sideline_payload(center_lat=center_lat, center_lon=center_lon, radius_m=radius_m)
    projected_segments = projected_segments_from_payload(base_payload)
    centerline_references = build_centerline_references(
        center_lat=center_lat,
        center_lon=center_lon,
        radius_m=radius_m,
    )
    cleaned_segments, node_features, prune_stats = split_and_prune_by_centerline_contacts(
        projected_segments,
        centerline_references,
    )
    segment_features = segment_features_from_projected(cleaned_segments)
    segment_counts = Counter(feature["properties"]["segmentType"] for feature in segment_features)
    meta = dict(base_payload["meta"])
    meta.update(
        {
            "title": "02C Haeundae 5km Sideline Centerline-Contact Pruned Preview",
            "outputHtml": str(CENTERLINE_PRUNED_OUTPUT_HTML),
            "outputGeojson": str(CENTERLINE_PRUNED_OUTPUT_GEOJSON),
            "localhostUrl": f"http://127.0.0.1:3000/etl/{CENTERLINE_PRUNED_OUTPUT_HTML.name}",
            "stage": "02c-step2b-sideline-centerline-contact-pruned",
            "intersectionRule": (
                "split raw sideline at sideline intersections; from each one-node split piece, prune only the "
                "node-to-centerline-contact direction when the contact is within local road width threshold"
            ),
            "centerlineContactThresholdRule": (
                "threshold = max(roadWidthMeter, offsetMeter * 2, 2m) * 1.2 + 1m; same-source centerline ignored"
            ),
            **prune_stats,
        }
    )
    return {
        "meta": meta,
        "summary": {
            "nodeCount": len(node_features),
            "segmentCount": len(segment_features),
            "segmentTypeCounts": [{"name": name, "count": count} for name, count in sorted(segment_counts.items())],
            "transitionConnectorCount": 0,
            "gapBridgeCount": 0,
            "cornerBridgeCount": 0,
            "sameSideCornerBridgeCount": 0,
            "crossSideCornerBridgeCount": 0,
            "crossingCount": 0,
            "elevatorConnectorCount": 0,
        },
        "layers": {
            "roadNodes": {"type": "FeatureCollection", "features": node_features},
            "roadSegments": {"type": "FeatureCollection", "features": segment_features},
        },
    }


def write_outputs(
    *,
    output_html: Path = OUTPUT_HTML,
    output_geojson: Path = OUTPUT_GEOJSON,
    center_lat: float = DEFAULT_CENTER_LAT,
    center_lon: float = DEFAULT_CENTER_LON,
    radius_m: int = DEFAULT_RADIUS_M,
) -> dict[str, Any]:
    payload = build_payload(center_lat=center_lat, center_lon=center_lon, radius_m=radius_m)
    payload["meta"]["outputHtml"] = str(output_html)
    payload["meta"]["outputGeojson"] = str(output_geojson)
    payload["meta"]["localhostUrl"] = f"http://127.0.0.1:3000/etl/{output_html.name}"
    output_geojson.parent.mkdir(parents=True, exist_ok=True)
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_geojson.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_html.write_text(subway_elevator_preview.render_html(payload), encoding="utf-8")
    return payload


def write_sideline_outputs(
    *,
    output_html: Path = SIDELINE_OUTPUT_HTML,
    output_geojson: Path = SIDELINE_OUTPUT_GEOJSON,
    center_lat: float = DEFAULT_CENTER_LAT,
    center_lon: float = DEFAULT_CENTER_LON,
    radius_m: int = DEFAULT_RADIUS_M,
) -> dict[str, Any]:
    payload = build_sideline_payload(center_lat=center_lat, center_lon=center_lon, radius_m=radius_m)
    payload["meta"]["outputHtml"] = str(output_html)
    payload["meta"]["outputGeojson"] = str(output_geojson)
    payload["meta"]["localhostUrl"] = f"http://127.0.0.1:3000/etl/{output_html.name}"
    output_geojson.parent.mkdir(parents=True, exist_ok=True)
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_geojson.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_html.write_text(subway_elevator_preview.render_html(payload), encoding="utf-8")
    return payload


def write_sideline_intersection_outputs(
    *,
    output_html: Path = INTERSECTION_OUTPUT_HTML,
    output_geojson: Path = INTERSECTION_OUTPUT_GEOJSON,
    center_lat: float = DEFAULT_CENTER_LAT,
    center_lon: float = DEFAULT_CENTER_LON,
    radius_m: int = DEFAULT_RADIUS_M,
) -> dict[str, Any]:
    payload = build_sideline_intersection_payload(center_lat=center_lat, center_lon=center_lon, radius_m=radius_m)
    payload["meta"]["outputHtml"] = str(output_html)
    payload["meta"]["outputGeojson"] = str(output_geojson)
    payload["meta"]["localhostUrl"] = f"http://127.0.0.1:3000/etl/{output_html.name}"
    output_geojson.parent.mkdir(parents=True, exist_ok=True)
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_geojson.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_html.write_text(subway_elevator_preview.render_html(payload), encoding="utf-8")
    return payload


def write_sideline_intersection_01_outputs(
    *,
    output_html: Path = CANDIDATE_INTERSECTION_OUTPUT_HTML,
    output_geojson: Path = CANDIDATE_INTERSECTION_OUTPUT_GEOJSON,
    center_lat: float = DEFAULT_CENTER_LAT,
    center_lon: float = DEFAULT_CENTER_LON,
    radius_m: int = DEFAULT_RADIUS_M,
) -> dict[str, Any]:
    payload = build_sideline_intersection_01_payload(
        center_lat=center_lat,
        center_lon=center_lon,
        radius_m=radius_m,
    )
    payload["meta"]["outputHtml"] = str(output_html)
    payload["meta"]["outputGeojson"] = str(output_geojson)
    payload["meta"]["localhostUrl"] = f"http://127.0.0.1:3000/etl/{output_html.name}"
    output_geojson.parent.mkdir(parents=True, exist_ok=True)
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_geojson.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_html.write_text(subway_elevator_preview.render_html(payload), encoding="utf-8")
    return payload


def write_sideline_intersection_02_outputs(
    *,
    output_html: Path = NEAR_CROSS_INTERSECTION_OUTPUT_HTML,
    output_geojson: Path = NEAR_CROSS_INTERSECTION_OUTPUT_GEOJSON,
    center_lat: float = DEFAULT_CENTER_LAT,
    center_lon: float = DEFAULT_CENTER_LON,
    radius_m: int = DEFAULT_RADIUS_M,
) -> dict[str, Any]:
    payload = build_sideline_intersection_02_payload(
        center_lat=center_lat,
        center_lon=center_lon,
        radius_m=radius_m,
    )
    payload["meta"]["outputHtml"] = str(output_html)
    payload["meta"]["outputGeojson"] = str(output_geojson)
    payload["meta"]["localhostUrl"] = f"http://127.0.0.1:3000/etl/{output_html.name}"
    output_geojson.parent.mkdir(parents=True, exist_ok=True)
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_geojson.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_html.write_text(subway_elevator_preview.render_html(payload), encoding="utf-8")
    return payload


def write_sideline_intersection_03_outputs(
    *,
    output_html: Path = CLUSTERED_INTERSECTION_OUTPUT_HTML,
    output_geojson: Path = CLUSTERED_INTERSECTION_OUTPUT_GEOJSON,
    center_lat: float = DEFAULT_CENTER_LAT,
    center_lon: float = DEFAULT_CENTER_LON,
    radius_m: int = DEFAULT_RADIUS_M,
) -> dict[str, Any]:
    payload = build_sideline_intersection_03_payload(
        center_lat=center_lat,
        center_lon=center_lon,
        radius_m=radius_m,
    )
    payload["meta"]["outputHtml"] = str(output_html)
    payload["meta"]["outputGeojson"] = str(output_geojson)
    payload["meta"]["localhostUrl"] = f"http://127.0.0.1:3000/etl/{output_html.name}"
    output_geojson.parent.mkdir(parents=True, exist_ok=True)
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_geojson.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_html.write_text(subway_elevator_preview.render_html(payload), encoding="utf-8")
    return payload


def write_graph_materialized_outputs(
    *,
    output_html: Path = GRAPH_MATERIALIZED_OUTPUT_HTML,
    output_geojson: Path = GRAPH_MATERIALIZED_OUTPUT_GEOJSON,
    center_lat: float = DEFAULT_CENTER_LAT,
    center_lon: float = DEFAULT_CENTER_LON,
    radius_m: int = DEFAULT_RADIUS_M,
) -> dict[str, Any]:
    payload = build_graph_materialized_payload(
        center_lat=center_lat,
        center_lon=center_lon,
        radius_m=radius_m,
    )
    payload["meta"]["outputHtml"] = str(output_html)
    payload["meta"]["outputGeojson"] = str(output_geojson)
    payload["meta"]["localhostUrl"] = f"http://127.0.0.1:3000/etl/{output_html.name}"
    output_geojson.parent.mkdir(parents=True, exist_ok=True)
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_geojson.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_html.write_text(subway_elevator_preview.render_html(payload), encoding="utf-8")
    return payload


def write_road_boundary_outputs(
    *,
    output_html: Path = ROAD_BOUNDARY_OUTPUT_HTML,
    output_geojson: Path = ROAD_BOUNDARY_OUTPUT_GEOJSON,
    center_lat: float = DEFAULT_CENTER_LAT,
    center_lon: float = DEFAULT_CENTER_LON,
    radius_m: int = DEFAULT_RADIUS_M,
) -> dict[str, Any]:
    payload = build_road_boundary_payload(
        center_lat=center_lat,
        center_lon=center_lon,
        radius_m=radius_m,
    )
    payload["meta"]["outputHtml"] = str(output_html)
    payload["meta"]["outputGeojson"] = str(output_geojson)
    payload["meta"]["localhostUrl"] = f"http://127.0.0.1:3000/etl/{output_html.name}"
    output_geojson.parent.mkdir(parents=True, exist_ok=True)
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_geojson.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_html.write_text(subway_elevator_preview.render_html(payload), encoding="utf-8")
    return payload


def write_graph_edit_outputs(
    *,
    output_html: Path = GRAPH_EDIT_OUTPUT_HTML,
    center_lat: float = DEFAULT_CENTER_LAT,
    center_lon: float = DEFAULT_CENTER_LON,
    radius_m: int = DEFAULT_RADIUS_M,
) -> dict[str, Any]:
    payload = build_graph_materialized_payload(
        center_lat=center_lat,
        center_lon=center_lon,
        radius_m=radius_m,
    )
    payload["meta"]["title"] = "02C Haeundae 5km Graph Manual Edit UI"
    payload["meta"]["outputHtml"] = str(output_html)
    payload["meta"]["localhostUrl"] = f"http://127.0.0.1:3000/etl/{output_html.name}"
    payload["meta"]["stage"] = "02c-step2g-manual-edit-ui"
    payload["meta"]["manualEditRule"] = (
        "render only current map bbox, record delete/add operations as manual_edits in localStorage and export JSON; "
        "do not mutate source graph records directly"
    )
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(segment_graph_edit_ui.render_html(payload), encoding="utf-8")
    return payload


def write_sideline_centerline_pruned_outputs(
    *,
    output_html: Path = CENTERLINE_PRUNED_OUTPUT_HTML,
    output_geojson: Path = CENTERLINE_PRUNED_OUTPUT_GEOJSON,
    center_lat: float = DEFAULT_CENTER_LAT,
    center_lon: float = DEFAULT_CENTER_LON,
    radius_m: int = DEFAULT_RADIUS_M,
) -> dict[str, Any]:
    payload = build_sideline_centerline_pruned_payload(
        center_lat=center_lat,
        center_lon=center_lon,
        radius_m=radius_m,
    )
    payload["meta"]["outputHtml"] = str(output_html)
    payload["meta"]["outputGeojson"] = str(output_geojson)
    payload["meta"]["localhostUrl"] = f"http://127.0.0.1:3000/etl/{output_html.name}"
    output_geojson.parent.mkdir(parents=True, exist_ok=True)
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_geojson.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_html.write_text(subway_elevator_preview.render_html(payload), encoding="utf-8")
    return payload
