from __future__ import annotations

import csv
import html
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import shapefile
from pyproj import Geod, Transformer

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


def line_length_meter(coords: tuple[tuple[float, float], ...]) -> float:
    if len(coords) < 2:
        return 0.0
    lons = [coord[0] for coord in coords]
    lats = [coord[1] for coord in coords]
    return abs(float(GEOD.line_length(lons, lats)))


def build_snapshots() -> tuple[list[NodeSnapshot], list[SegmentSnapshot], dict[str, object]]:
    validate_sidecars()
    reader, encoding = open_reader()

    nodes_by_key: dict[str, NodeSnapshot] = {}
    segments: list[SegmentSnapshot] = []
    skipped_parts = 0
    invalid_parts = 0

    def get_node(lon: float, lat: float) -> NodeSnapshot:
        key = node_key(lon, lat)
        existing = nodes_by_key.get(key)
        if existing is not None:
            return existing
        node = NodeSnapshot(
            vertex_id=len(nodes_by_key) + 1,
            source_node_key=key,
            lon=lon,
            lat=lat,
        )
        nodes_by_key[key] = node
        return node

    for shape in reader.iterShapes():
        for start, end in part_ranges(shape):
            coords = transformed_part(shape.points[start:end])
            if len(coords) < 2:
                skipped_parts += 1
                continue
            length_meter = line_length_meter(coords)
            if length_meter <= 0:
                invalid_parts += 1
                continue
            from_node = get_node(*coords[0])
            to_node = get_node(*coords[-1])
            segments.append(
                SegmentSnapshot(
                    edge_id=len(segments) + 1,
                    from_node_id=from_node.vertex_id,
                    to_node_id=to_node.vertex_id,
                    length_meter=round(length_meter, 2),
                    coords=coords,
                )
            )

    nodes = sorted(nodes_by_key.values(), key=lambda item: item.vertex_id)
    report = {
        "dataset": SHP_BASENAME,
        "source_shape_count": len(reader),
        "node_count": len(nodes),
        "segment_count": len(segments),
        "skipped_parts": skipped_parts,
        "invalid_parts": invalid_parts,
        "crs": "EPSG:5179 -> EPSG:4326",
        "encoding": encoding,
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
    node_ids = {int(node["vertexId"]) for node in nodes}
    edge_ids: set[int] = set()
    duplicate_edge_ids = 0
    orphan_edges = 0
    invalid_lengths = 0
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

        if float(segment["lengthMeter"]) <= 0:
            invalid_lengths += 1

    report = {
        "node_count": len(nodes),
        "segment_count": len(segments),
        "duplicate_edge_ids": duplicate_edge_ids,
        "orphan_edges": orphan_edges,
        "invalid_lengths": invalid_lengths,
        "connected_components": dsu.component_count(),
    }
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
