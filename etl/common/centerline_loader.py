from __future__ import annotations

import csv
import html
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from math import floor, hypot
from pathlib import Path
from typing import Iterable

import shapefile
from pyproj import Geod, Transformer
from shapely.geometry import LineString, Point
from shapely.ops import substring
from shapely.strtree import STRtree

from etl.common.db import connect, ewkt, insert_row


ROOT_DIR = Path(__file__).resolve().parents[2]
ETL_DIR = ROOT_DIR / "etl"
RAW_DIR = ETL_DIR / "raw"
RUNTIME_DIR = ROOT_DIR / "runtime" / "etl" / "centerline-load"
SHP_BASENAME = "N3L_A0020000_26"
SIDECARS = [".shp", ".shx", ".dbf", ".prj"]
DBF_ENCODINGS = ("cp949", "euc-kr", "utf-8")

NODE_SNAPSHOT = RUNTIME_DIR / "road_nodes_snapshot.csv"
SEGMENT_SNAPSHOT = RUNTIME_DIR / "road_segments_snapshot.csv"
SNAPSHOT_REPORT = RUNTIME_DIR / "centerline_snapshot.json"
TOPOLOGY_REPORT = RUNTIME_DIR / "centerline_topology_audit.json"
POST_LOAD_REPORT = RUNTIME_DIR / "road_network_post_load_report.json"
PREVIEW_GEOJSON = RUNTIME_DIR / "road_network_preview.geojson"
PREVIEW_HTML = RUNTIME_DIR / "road_network_preview.html"

TRANSFORMER = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)
GEOD = Geod(ellps="GRS80")
SNAP_TOLERANCE_M = 2.0
NODE_MERGE_TOLERANCE_M = 0.5
MIN_SPLIT_GAP_M = 0.05


@dataclass(frozen=True)
class NodeSnapshot:
    vertex_id: int
    source_node_key: str
    lon: float
    lat: float

    @property
    def ewkt(self) -> str:
        return f"SRID=4326;POINT({self.lon:.8f} {self.lat:.8f})"


@dataclass(frozen=True)
class SegmentSnapshot:
    edge_id: int
    from_node_id: int
    to_node_id: int
    length_meter: float
    coords: tuple[tuple[float, float], ...]

    @property
    def ewkt(self) -> str:
        pairs = ", ".join(f"{lon:.8f} {lat:.8f}" for lon, lat in self.coords)
        return f"SRID=4326;LINESTRING({pairs})"


class DisjointSet:
    def __init__(self) -> None:
        self.parent: dict[int, int] = {}

    def find(self, value: int) -> int:
        self.parent.setdefault(value, value)
        if self.parent[value] != value:
            self.parent[value] = self.find(self.parent[value])
        return self.parent[value]

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root

    def component_count(self) -> int:
        return len({self.find(value) for value in self.parent})


def ensure_runtime_dir() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)


def validate_sidecars() -> list[Path]:
    paths = [RAW_DIR / f"{SHP_BASENAME}{suffix}" for suffix in SIDECARS]
    missing = [path for path in paths if not path.exists()]
    if missing:
        missing_text = "\n".join(f"- {path}" for path in missing)
        raise FileNotFoundError(f"missing SHP sidecar files:\n{missing_text}")
    return paths


def read_prj() -> str:
    return (RAW_DIR / f"{SHP_BASENAME}.prj").read_text(encoding="utf-8", errors="replace")


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


def preflight_report() -> dict[str, object]:
    validate_sidecars()
    reader, encoding = open_reader()
    prj = read_prj()
    return {
        "dataset": SHP_BASENAME,
        "shape_count": len(reader),
        "shape_type": reader.shapeTypeName,
        "encoding": encoding,
        "encoding_fallback_order": list(DBF_ENCODINGS),
        "crs_hint": "EPSG:5179" if "Korea_Unified_Coordinate_System" in prj else "unknown",
        "sidecars": [str(RAW_DIR / f"{SHP_BASENAME}{suffix}") for suffix in SIDECARS],
    }


def node_key(lon: float, lat: float) -> str:
    return f"{lon:.6f}:{lat:.6f}"


def source_part(points: Iterable[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
    return tuple((float(x), float(y)) for x, y in points)


def transformed_part(points: Iterable[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
    source_points = list(points)
    if len(source_points) < 2:
        return ()
    xs = [point[0] for point in source_points]
    ys = [point[1] for point in source_points]
    lons, lats = TRANSFORMER.transform(xs, ys)
    return tuple((float(lon), float(lat)) for lon, lat in zip(lons, lats, strict=True))


def part_ranges(shape: shapefile.Shape) -> list[tuple[int, int]]:
    starts = list(shape.parts) + [len(shape.points)]
    return [(starts[i], starts[i + 1]) for i in range(len(starts) - 1)]


def transform_projected_point(point: tuple[float, float]) -> tuple[float, float]:
    lon, lat = TRANSFORMER.transform(point[0], point[1])
    return float(lon), float(lat)


def transform_projected_coords(points: Iterable[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
    source_points = list(points)
    if not source_points:
        return ()
    xs = [point[0] for point in source_points]
    ys = [point[1] for point in source_points]
    lons, lats = TRANSFORMER.transform(xs, ys)
    return tuple((float(lon), float(lat)) for lon, lat in zip(lons, lats, strict=True))


def projected_length_meter(coords: tuple[tuple[float, float], ...]) -> float:
    if len(coords) < 2:
        return 0.0
    return sum(hypot(right[0] - left[0], right[1] - left[1]) for left, right in zip(coords, coords[1:]))


def line_length_meter(coords: tuple[tuple[float, float], ...]) -> float:
    if len(coords) < 2:
        return 0.0
    lons = [coord[0] for coord in coords]
    lats = [coord[1] for coord in coords]
    return abs(float(GEOD.line_length(lons, lats)))


def dedupe_consecutive_coords(coords: tuple[tuple[float, float], ...]) -> tuple[tuple[float, float], ...]:
    if not coords:
        return ()
    deduped = [coords[0]]
    for coord in coords[1:]:
        if coord != deduped[-1]:
            deduped.append(coord)
    return tuple(deduped)


def build_raw_segments() -> tuple[list[tuple[tuple[float, float], ...]], dict[str, object]]:
    validate_sidecars()
    reader, encoding = open_reader()

    raw_segments: list[tuple[tuple[float, float], ...]] = []
    skipped_parts = 0
    invalid_parts = 0

    for shape in reader.iterShapes():
        for start, end in part_ranges(shape):
            coords = source_part(shape.points[start:end])
            if len(coords) < 2:
                skipped_parts += 1
                continue
            length_meter = projected_length_meter(coords)
            if length_meter <= 0:
                invalid_parts += 1
                continue
            raw_segments.append(coords)

    report = {
        "dataset": SHP_BASENAME,
        "source_shape_count": len(reader),
        "raw_segment_count": len(raw_segments),
        "skipped_parts": skipped_parts,
        "invalid_parts": invalid_parts,
        "crs": "EPSG:5179 -> EPSG:4326",
        "encoding": encoding,
    }
    return raw_segments, report


def raw_node_count(raw_segments: list[tuple[tuple[float, float], ...]]) -> int:
    keys: set[str] = set()
    for coords in raw_segments:
        for endpoint in (coords[0], coords[-1]):
            lon, lat = transform_projected_point(endpoint)
            keys.add(node_key(lon, lat))
    return len(keys)


def split_projected_segment(
    coords: tuple[tuple[float, float], ...],
    split_points: Iterable[tuple[float, float]],
    min_gap_meter: float = MIN_SPLIT_GAP_M,
) -> list[tuple[tuple[float, float], ...]]:
    coords = dedupe_consecutive_coords(coords)
    if len(coords) < 2:
        return []

    line = LineString(coords)
    if line.length <= min_gap_meter:
        return [coords]

    distances: list[float] = []
    for split_point in split_points:
        distance_along = float(line.project(Point(split_point)))
        if min_gap_meter < distance_along < line.length - min_gap_meter:
            distances.append(distance_along)

    ordered = sorted(distances)
    filtered: list[float] = []
    for distance_along in ordered:
        if not filtered or abs(distance_along - filtered[-1]) > min_gap_meter:
            filtered.append(distance_along)

    if not filtered:
        return [coords]

    pieces: list[tuple[tuple[float, float], ...]] = []
    boundaries = [0.0, *filtered, float(line.length)]
    for start_distance, end_distance in zip(boundaries, boundaries[1:]):
        if end_distance - start_distance <= min_gap_meter:
            continue
        piece = substring(line, start_distance, end_distance)
        if piece.is_empty or piece.geom_type != "LineString":
            continue
        piece_coords = dedupe_consecutive_coords(tuple((float(x), float(y)) for x, y in piece.coords))
        if len(piece_coords) >= 2 and projected_length_meter(piece_coords) > 0:
            pieces.append(piece_coords)

    return pieces or [coords]


def normalize_projected_segments(
    raw_segments: list[tuple[tuple[float, float], ...]],
    snap_tolerance_meter: float = SNAP_TOLERANCE_M,
    node_merge_tolerance_meter: float = NODE_MERGE_TOLERANCE_M,
) -> tuple[list[tuple[tuple[float, float], ...]], dict[str, object]]:
    if not raw_segments:
        return [], {
            "snap_tolerance_meter": snap_tolerance_meter,
            "node_merge_tolerance_meter": node_merge_tolerance_meter,
            "snapped_endpoint_count": 0,
            "split_insertions": 0,
            "junction_collapse_count": 0,
        }

    lines = [LineString(coords) for coords in raw_segments]
    tree = STRtree(lines)
    endpoint_overrides: dict[tuple[int, int], tuple[float, float]] = {}
    split_points_by_segment: dict[int, list[tuple[float, float]]] = defaultdict(list)
    snapped_endpoint_count = 0

    for segment_index, coords in enumerate(raw_segments):
        for endpoint_index, endpoint in enumerate((coords[0], coords[-1])):
            point = Point(endpoint)
            best: tuple[float, int, tuple[float, float]] | None = None
            for candidate_ref in tree.query(point.buffer(snap_tolerance_meter)):
                candidate_index = int(candidate_ref)
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
            if hypot(snapped_point[0] - endpoint[0], snapped_point[1] - endpoint[1]) <= MIN_SPLIT_GAP_M:
                continue
            endpoint_overrides[(segment_index, endpoint_index)] = snapped_point
            split_points_by_segment[candidate_index].append(snapped_point)
            snapped_endpoint_count += 1

    normalized_segments: list[tuple[tuple[float, float], ...]] = []
    split_insertions = 0
    for segment_index, coords in enumerate(raw_segments):
        adjusted_coords = list(coords)
        if (segment_index, 0) in endpoint_overrides:
            adjusted_coords[0] = endpoint_overrides[(segment_index, 0)]
        if (segment_index, 1) in endpoint_overrides:
            adjusted_coords[-1] = endpoint_overrides[(segment_index, 1)]
        pieces = split_projected_segment(tuple(adjusted_coords), split_points_by_segment.get(segment_index, ()))
        split_insertions += max(0, len(pieces) - 1)
        normalized_segments.extend(pieces)

    endpoint_clusters = cluster_endpoint_indices(normalized_segments, node_merge_tolerance_meter)
    junction_collapse_count = sum(1 for members in endpoint_clusters.values() if len(members) > 1)
    return normalized_segments, {
        "snap_tolerance_meter": snap_tolerance_meter,
        "node_merge_tolerance_meter": node_merge_tolerance_meter,
        "snapped_endpoint_count": snapped_endpoint_count,
        "split_insertions": split_insertions,
        "junction_collapse_count": junction_collapse_count,
    }


def cluster_endpoint_indices(
    projected_segments: list[tuple[tuple[float, float], ...]],
    merge_tolerance_meter: float,
) -> dict[int, list[int]]:
    endpoint_coords: list[tuple[float, float]] = []
    for coords in projected_segments:
        endpoint_coords.extend((coords[0], coords[-1]))

    dsu = DisjointSet()
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)

    for index, coord in enumerate(endpoint_coords):
        dsu.find(index)
        cell = (floor(coord[0] / merge_tolerance_meter), floor(coord[1] / merge_tolerance_meter))
        for offset_x in (-1, 0, 1):
            for offset_y in (-1, 0, 1):
                for other_index in grid.get((cell[0] + offset_x, cell[1] + offset_y), []):
                    other = endpoint_coords[other_index]
                    if hypot(coord[0] - other[0], coord[1] - other[1]) <= merge_tolerance_meter:
                        dsu.union(index, other_index)
        grid[cell].append(index)

    clusters: dict[int, list[int]] = defaultdict(list)
    for index in range(len(endpoint_coords)):
        clusters[dsu.find(index)].append(index)
    return clusters


def build_snapshots() -> tuple[list[NodeSnapshot], list[SegmentSnapshot], dict[str, object]]:
    raw_segments, raw_report = build_raw_segments()
    normalized_segments, normalization_report = normalize_projected_segments(raw_segments)
    raw_nodes = raw_node_count(raw_segments)

    endpoint_clusters = cluster_endpoint_indices(normalized_segments, NODE_MERGE_TOLERANCE_M)
    endpoint_coords = [endpoint for coords in normalized_segments for endpoint in (coords[0], coords[-1])]
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

    ordered_roots = sorted(cluster_centers, key=cluster_first_seen.get)
    nodes_by_root: dict[int, NodeSnapshot] = {}
    for vertex_id, root in enumerate(ordered_roots, start=1):
        lon, lat = transform_projected_point(cluster_centers[root])
        nodes_by_root[root] = NodeSnapshot(
            vertex_id=vertex_id,
            source_node_key=node_key(lon, lat),
            lon=lon,
            lat=lat,
        )

    segments: list[SegmentSnapshot] = []
    invalid_normalized_segments = 0
    for segment_index, coords in enumerate(normalized_segments, start=1):
        from_root = endpoint_root_by_index[(segment_index - 1) * 2]
        to_root = endpoint_root_by_index[(segment_index - 1) * 2 + 1]
        projected_coords = dedupe_consecutive_coords(
            (
                cluster_centers[from_root],
                *coords[1:-1],
                cluster_centers[to_root],
            )
        )
        if len(projected_coords) < 2 or projected_length_meter(projected_coords) <= 0:
            invalid_normalized_segments += 1
            continue
        lonlat_coords = transform_projected_coords(projected_coords)
        length_meter = line_length_meter(lonlat_coords)
        if length_meter <= 0:
            invalid_normalized_segments += 1
            continue
        rounded_length_meter = round(length_meter, 2)
        if rounded_length_meter <= 0:
            invalid_normalized_segments += 1
            continue
        segments.append(
            SegmentSnapshot(
                edge_id=len(segments) + 1,
                from_node_id=nodes_by_root[from_root].vertex_id,
                to_node_id=nodes_by_root[to_root].vertex_id,
                length_meter=rounded_length_meter,
                coords=lonlat_coords,
            )
        )

    nodes = [nodes_by_root[root] for root in ordered_roots]
    report = {
        **raw_report,
        **normalization_report,
        "raw_node_count": raw_nodes,
        "node_count": len(nodes),
        "segment_count": len(segments),
        "segment_delta_from_split": len(segments) - len(raw_segments),
        "node_reduction_from_merge": raw_nodes - len(nodes),
        "invalid_normalized_segments": invalid_normalized_segments,
    }
    return nodes, segments, report


def write_snapshots(nodes: list[NodeSnapshot], segments: list[SegmentSnapshot], report: dict[str, object]) -> None:
    ensure_runtime_dir()
    with NODE_SNAPSHOT.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["vertexId", "sourceNodeKey", "point"])
        writer.writeheader()
        for node in nodes:
            writer.writerow(
                {
                    "vertexId": node.vertex_id,
                    "sourceNodeKey": node.source_node_key,
                    "point": node.ewkt,
                }
            )

    with SEGMENT_SNAPSHOT.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["edgeId", "fromNodeId", "toNodeId", "geom", "lengthMeter"])
        writer.writeheader()
        for segment in segments:
            writer.writerow(
                {
                    "edgeId": segment.edge_id,
                    "fromNodeId": segment.from_node_id,
                    "toNodeId": segment.to_node_id,
                    "geom": segment.ewkt,
                    "lengthMeter": f"{segment.length_meter:.2f}",
                }
            )

    SNAPSHOT_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_node_snapshot() -> list[dict[str, str]]:
    with NODE_SNAPSHOT.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def load_segment_snapshot() -> list[dict[str, str]]:
    with SEGMENT_SNAPSHOT.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def load_snapshot_report() -> dict[str, object]:
    if not SNAPSHOT_REPORT.exists():
        return {}
    return json.loads(SNAPSHOT_REPORT.read_text(encoding="utf-8"))


def ensure_snapshots() -> None:
    if NODE_SNAPSHOT.exists() and SEGMENT_SNAPSHOT.exists():
        return
    nodes, segments, report = build_snapshots()
    write_snapshots(nodes, segments, report)


def extract_shp() -> dict[str, object]:
    nodes, segments, report = build_snapshots()
    write_snapshots(nodes, segments, report)
    return report


def topology_audit() -> dict[str, object]:
    ensure_snapshots()
    nodes = load_node_snapshot()
    segments = load_segment_snapshot()
    snapshot_report = load_snapshot_report()
    node_ids = {int(node["vertexId"]) for node in nodes}
    edge_ids: set[int] = set()
    duplicate_edge_ids = 0
    orphan_edges = 0
    invalid_lengths = 0
    degree_by_node: Counter[int] = Counter()
    dsu = DisjointSet()

    for segment in segments:
        edge_id = int(segment["edgeId"])
        if edge_id in edge_ids:
            duplicate_edge_ids += 1
        edge_ids.add(edge_id)

        from_node = int(segment["fromNodeId"])
        to_node = int(segment["toNodeId"])
        if from_node not in node_ids or to_node not in node_ids:
            orphan_edges += 1
        dsu.union(from_node, to_node)
        degree_by_node[from_node] += 1
        degree_by_node[to_node] += 1

        if float(segment["lengthMeter"]) <= 0:
            invalid_lengths += 1

    degree_distribution = Counter(degree_by_node.values())
    report = {
        "node_count": len(nodes),
        "segment_count": len(segments),
        "duplicate_edge_ids": duplicate_edge_ids,
        "orphan_edges": orphan_edges,
        "invalid_lengths": invalid_lengths,
        "connected_components": dsu.component_count(),
        "degree_distribution": {str(key): degree_distribution[key] for key in sorted(degree_distribution)},
    }
    for key in (
        "raw_segment_count",
        "raw_node_count",
        "snap_tolerance_meter",
        "node_merge_tolerance_meter",
        "snapped_endpoint_count",
        "split_insertions",
        "junction_collapse_count",
        "segment_delta_from_split",
        "node_reduction_from_merge",
    ):
        if key in snapshot_report:
            report[key] = snapshot_report[key]
    ensure_runtime_dir()
    TOPOLOGY_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def load_db() -> dict[str, int]:
    ensure_snapshots()
    nodes = load_node_snapshot()
    segments = load_segment_snapshot()

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute('TRUNCATE TABLE "segment_features", "road_segments", "road_nodes" RESTART IDENTITY CASCADE')
            for node in nodes:
                insert_row(
                    cur,
                    "road_nodes",
                    {
                        "vertexId": int(node["vertexId"]),
                        "sourceNodeKey": node["sourceNodeKey"],
                        "point": ewkt(node["point"]),
                    },
                )
            for segment in segments:
                insert_row(
                    cur,
                    "road_segments",
                    {
                        "edgeId": int(segment["edgeId"]),
                        "fromNodeId": int(segment["fromNodeId"]),
                        "toNodeId": int(segment["toNodeId"]),
                        "geom": ewkt(segment["geom"]),
                        "lengthMeter": float(segment["lengthMeter"]),
                    },
                )
        conn.commit()

    return post_load_validate()


def post_load_validate() -> dict[str, object]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM "road_nodes"')
            node_count = cur.fetchone()[0]
            cur.execute('SELECT COUNT(*) FROM "road_segments"')
            segment_count = cur.fetchone()[0]
            cur.execute(
                """
                SELECT COUNT(*)
                FROM "road_segments" rs
                LEFT JOIN "road_nodes" f ON f."vertexId" = rs."fromNodeId"
                LEFT JOIN "road_nodes" t ON t."vertexId" = rs."toNodeId"
                WHERE f."vertexId" IS NULL OR t."vertexId" IS NULL
                """
            )
            orphan_edges = cur.fetchone()[0]
            cur.execute('SELECT COUNT(*) FROM "road_segments" WHERE NOT ST_IsValid("geom")')
            invalid_geometries = cur.fetchone()[0]
            cur.execute('SELECT COUNT(*) FROM "road_segments" WHERE ST_SRID("geom") <> 4326')
            invalid_srid = cur.fetchone()[0]
            cur.execute('SELECT COUNT(*) FROM "road_segments" WHERE "lengthMeter" <= 0')
            invalid_lengths = cur.fetchone()[0]
            cur.execute(
                """
                SELECT COUNT(*)
                FROM (
                    SELECT "edgeId"
                    FROM "road_segments"
                    GROUP BY "edgeId"
                    HAVING COUNT(*) > 1
                ) duplicated
                """
            )
            duplicate_edge_ids = cur.fetchone()[0]

    report = {
        "node_count": node_count,
        "segment_count": segment_count,
        "orphan_edges": orphan_edges,
        "invalid_geometries": invalid_geometries,
        "invalid_srid": invalid_srid,
        "invalid_lengths": invalid_lengths,
        "duplicate_edge_ids": duplicate_edge_ids,
    }
    ensure_runtime_dir()
    POST_LOAD_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    failures = {key: value for key, value in report.items() if key not in {"node_count", "segment_count"} and value != 0}
    if node_count == 0 or segment_count == 0:
        raise RuntimeError(f"empty road network load: {report}")
    if failures:
        raise RuntimeError(f"post-load validation failed: {report}")
    return report


def visualize_html(limit: int = 5000) -> dict[str, object]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM "road_nodes"')
            total_nodes = cur.fetchone()[0]
            cur.execute('SELECT COUNT(*) FROM "road_segments"')
            total_segments = cur.fetchone()[0]
            cur.execute(
                """
                SELECT COUNT(*)
                FROM "road_segments" rs
                LEFT JOIN "road_nodes" f ON f."vertexId" = rs."fromNodeId"
                LEFT JOIN "road_nodes" t ON t."vertexId" = rs."toNodeId"
                WHERE f."vertexId" IS NULL OR t."vertexId" IS NULL
                """
            )
            orphan_edges = cur.fetchone()[0]
            cur.execute('SELECT COUNT(*) FROM "road_segments" WHERE NOT ST_IsValid("geom")')
            invalid_geometries = cur.fetchone()[0]
            cur.execute('SELECT COUNT(*) FROM "road_segments" WHERE ST_SRID("geom") <> 4326')
            invalid_srid = cur.fetchone()[0]
            cur.execute('SELECT COUNT(*) FROM "road_segments" WHERE "lengthMeter" <= 0')
            invalid_lengths = cur.fetchone()[0]
            cur.execute(
                """
                SELECT "edgeId", ST_AsGeoJSON("geom")::json
                FROM "road_segments"
                ORDER BY "edgeId"
                LIMIT %s
                """,
                (limit,),
            )
            segment_features = [
                {
                    "type": "Feature",
                    "properties": {"edgeId": edge_id},
                    "geometry": geometry,
                }
                for edge_id, geometry in cur.fetchall()
            ]
            cur.execute(
                """
                SELECT "vertexId", ST_AsGeoJSON("point")::json
                FROM "road_nodes"
                ORDER BY "vertexId"
                LIMIT %s
                """,
                (limit,),
            )
            node_features = [
                {
                    "type": "Feature",
                    "properties": {"vertexId": vertex_id},
                    "geometry": geometry,
                }
                for vertex_id, geometry in cur.fetchall()
            ]

    geojson = {
        "type": "FeatureCollection",
        "features": segment_features + node_features,
        "properties": {
            "totalNodes": total_nodes,
            "totalSegments": total_segments,
            "renderedNodes": len(node_features),
            "renderedSegments": len(segment_features),
            "limit": limit,
            "orphanEdges": orphan_edges,
            "invalidGeometries": invalid_geometries,
            "invalidSrid": invalid_srid,
            "invalidLengths": invalid_lengths,
        },
    }
    ensure_runtime_dir()
    PREVIEW_GEOJSON.write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")
    PREVIEW_HTML.write_text(render_html(geojson), encoding="utf-8")
    return geojson["properties"]


def render_html(geojson: dict[str, object]) -> str:
    props = geojson["properties"]
    payload = json.dumps(geojson, ensure_ascii=False)
    summary = html.escape(
        f"nodes {props['renderedNodes']}/{props['totalNodes']}, "
        f"segments {props['renderedSegments']}/{props['totalSegments']}, "
        f"limit {props['limit']}, "
        f"orphan {props['orphanEdges']}, invalid geom {props['invalidGeometries']}, "
        f"invalid srid {props['invalidSrid']}, invalid length {props['invalidLengths']}"
    )
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Busan EumGil Road Network Preview</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <style>
    html, body, #map {{ height: 100%; margin: 0; }}
    .summary {{
      position: absolute;
      z-index: 500;
      top: 12px;
      left: 12px;
      padding: 10px 12px;
      background: rgba(255, 255, 255, 0.92);
      border: 1px solid #d0d7de;
      font: 13px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
  </style>
</head>
<body>
  <div id="map"></div>
  <div class="summary">{summary}</div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    const data = {payload};
    const map = L.map('map').setView([35.1796, 129.0756], 12);
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors'
    }}).addTo(map);

    const segments = L.geoJSON(data, {{
      filter: feature => feature.geometry.type === 'LineString',
      style: {{ color: '#0067b1', weight: 2, opacity: 0.72 }}
    }}).addTo(map);
    L.geoJSON(data, {{
      filter: feature => feature.geometry.type === 'Point',
      pointToLayer: (feature, latlng) => L.circleMarker(latlng, {{
        radius: 2,
        color: '#d83b01',
        fillColor: '#d83b01',
        fillOpacity: 0.8,
        weight: 0
      }})
    }}).addTo(map);
    if (segments.getBounds().isValid()) {{
      map.fitBounds(segments.getBounds(), {{ padding: [20, 20] }});
    }}
  </script>
</body>
</html>
"""


def run_full() -> dict[str, object]:
    preflight = preflight_report()
    snapshot = extract_shp()
    audit = topology_audit()
    load_report = load_db()
    preview = visualize_html()
    return {
        "preflight": preflight,
        "snapshot": snapshot,
        "topology": audit,
        "post_load": load_report,
        "preview": preview,
    }
