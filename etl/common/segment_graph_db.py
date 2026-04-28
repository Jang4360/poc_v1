from __future__ import annotations

import copy
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from pyproj import Geod

from etl.common import segment_graph_edit_ui, subway_elevator_preview
from etl.common.db import connect, ewkt, insert_row


ROOT_DIR = Path(__file__).resolve().parents[2]
ETL_DIR = ROOT_DIR / "etl"
DEFAULT_SOURCE_GEOJSON = ETL_DIR / "segment_02c_graph_materialized.geojson"
DB_OUTPUT_HTML = ETL_DIR / "segment_02c_graph_db.html"
DB_OUTPUT_GEOJSON = ETL_DIR / "segment_02c_graph_db.geojson"
CSV_NODE_OUTPUT = ETL_DIR / "segment_02c_road_nodes.csv"
CSV_SEGMENT_OUTPUT = ETL_DIR / "segment_02c_road_segments.csv"
CSV_EDIT_OUTPUT_HTML = ETL_DIR / "noksan_sinho_songjeong_hwajeon_segment_02c_graph_edit.html"
CSV_EDIT_OUTPUT_GEOJSON = ETL_DIR / "noksan_sinho_songjeong_hwajeon_segment_02c_graph_materialized.geojson"
GEOD = Geod(ellps="GRS80")
POINT_EWKT_RE = re.compile(r"^SRID=4326;POINT\(([-0-9.]+) ([-0-9.]+)\)$")
LINESTRING_EWKT_RE = re.compile(r"^SRID=4326;LINESTRING\((.+)\)$")
SIDE_LINE_ALIASES = {"SIDE_LEFT", "SIDE_RIGHT"}


def normalize_segment_type(segment_type: Any) -> str:
    value = str(segment_type or "CENTERLINE")
    if value in SIDE_LINE_ALIASES:
        return "SIDE_LINE"
    return value


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def coord_key(coord: list[float] | tuple[float, float]) -> str:
    return f"{float(coord[0]):.8f}:{float(coord[1]):.8f}"


def line_length_meter(coords: list[list[float]]) -> float:
    if len(coords) < 2:
        return 0.0
    lons = [float(coord[0]) for coord in coords]
    lats = [float(coord[1]) for coord in coords]
    return abs(float(GEOD.line_length(lons, lats)))


def point_distance_meter(left: list[float] | tuple[float, float], right: list[float] | tuple[float, float]) -> float:
    _az12, _az21, distance = GEOD.inv(float(left[0]), float(left[1]), float(right[0]), float(right[1]))
    return abs(float(distance))


def geometry_to_ewkt(geometry: dict[str, Any]) -> str:
    geom_type = geometry.get("type")
    coords = geometry.get("coordinates")
    if geom_type == "Point":
        lng, lat = coords
        return f"SRID=4326;POINT({float(lng):.8f} {float(lat):.8f})"
    if geom_type == "LineString":
        if not isinstance(coords, list) or len(coords) < 2:
            raise ValueError(f"invalid LineString coordinates: {coords!r}")
        pairs = ", ".join(f"{float(lng):.8f} {float(lat):.8f}" for lng, lat in coords)
        return f"SRID=4326;LINESTRING({pairs})"
    raise ValueError(f"unsupported geometry type: {geom_type!r}")


def ewkt_to_geometry(value: str) -> dict[str, Any]:
    point_match = POINT_EWKT_RE.match(value)
    if point_match:
        return {
            "type": "Point",
            "coordinates": [float(point_match.group(1)), float(point_match.group(2))],
        }
    linestring_match = LINESTRING_EWKT_RE.match(value)
    if linestring_match:
        coords: list[list[float]] = []
        for pair in linestring_match.group(1).split(", "):
            lng, lat = pair.split(" ")
            coords.append([float(lng), float(lat)])
        if len(coords) < 2:
            raise ValueError(f"invalid EWKT LineString: {value!r}")
        return {"type": "LineString", "coordinates": coords}
    raise ValueError(f"unsupported EWKT geometry: {value!r}")


def feature_in_bbox(feature: dict[str, Any], bbox: tuple[float, float, float, float]) -> bool:
    min_lon, min_lat, max_lon, max_lat = bbox
    geometry = feature.get("geometry", {})
    coords = geometry.get("coordinates") or []
    if geometry.get("type") == "Point":
        points = [coords]
    elif geometry.get("type") == "LineString":
        points = coords
    else:
        return False
    return any(min_lon <= float(lng) <= max_lon and min_lat <= float(lat) <= max_lat for lng, lat in points)


def refresh_summary(payload: dict[str, Any]) -> None:
    nodes = payload["layers"]["roadNodes"]["features"]
    segments = payload["layers"]["roadSegments"]["features"]
    degree: Counter[int] = Counter()
    for segment in segments:
        props = segment["properties"]
        degree[int(props["fromNodeId"])] += 1
        degree[int(props["toNodeId"])] += 1
    for node in nodes:
        node["properties"]["degree"] = degree[int(node["properties"]["vertexId"])]
    for segment in segments:
        segment["properties"]["segmentType"] = normalize_segment_type(segment["properties"].get("segmentType"))
    segment_counts = Counter(segment["properties"]["segmentType"] for segment in segments)
    payload["summary"].update(
        {
            "nodeCount": len(nodes),
            "segmentCount": len(segments),
            "segmentTypeCounts": [
                {"name": name, "count": count} for name, count in sorted(segment_counts.items())
            ],
        }
    )


def apply_manual_edits(payload: dict[str, Any], edit_document: dict[str, Any]) -> dict[str, Any]:
    patched = copy.deepcopy(payload)
    nodes = patched["layers"]["roadNodes"]["features"]
    segments = patched["layers"]["roadSegments"]["features"]

    delete_segment_ids: set[int] = set()
    requested_delete_node_ids: set[int] = set()
    for edit in edit_document.get("edits", []):
        if edit.get("action") == "delete_segment":
            delete_segment_ids.add(int(edit["edgeId"]))
        elif edit.get("action") == "delete_node":
            requested_delete_node_ids.add(int(edit["vertexId"]))

    if delete_segment_ids:
        segments[:] = [
            segment
            for segment in segments
            if int(segment["properties"]["edgeId"]) not in delete_segment_ids
        ]
    if requested_delete_node_ids:
        referenced_node_ids: set[int] = set()
        for segment in segments:
            referenced_node_ids.add(int(segment["properties"]["fromNodeId"]))
            referenced_node_ids.add(int(segment["properties"]["toNodeId"]))
        removable_node_ids = requested_delete_node_ids - referenced_node_ids
        if removable_node_ids:
            nodes[:] = [node for node in nodes if int(node["properties"]["vertexId"]) not in removable_node_ids]

    next_vertex_id = max((int(node["properties"]["vertexId"]) for node in nodes), default=0) + 1
    next_edge_id = max((int(segment["properties"]["edgeId"]) for segment in segments), default=0) + 1
    node_by_coord = {coord_key(node["geometry"]["coordinates"]): int(node["properties"]["vertexId"]) for node in nodes}
    node_feature_by_id = {int(node["properties"]["vertexId"]): node for node in nodes}

    def existing_node_within(coord: list[float], snap_radius_meter: float = 1.0) -> int | None:
        best: tuple[float, int] | None = None
        for node in nodes:
            vertex_id = int(node["properties"]["vertexId"])
            distance = point_distance_meter(coord, node["geometry"]["coordinates"])
            if distance <= snap_radius_meter and (best is None or distance < best[0]):
                best = (distance, vertex_id)
        return best[1] if best else None

    def resolve_node_ref(node_ref: dict[str, Any] | None, fallback_coord: list[float]) -> int:
        if node_ref and node_ref.get("mode") == "existing" and node_ref.get("vertexId") is not None:
            try:
                vertex_id = int(node_ref["vertexId"])
            except (TypeError, ValueError):
                return create_node(
                    node_ref.get("geom", {}).get("coordinates") or fallback_coord,
                    node_ref.get("sourceNodeKey"),
                )
            else:
                if vertex_id in node_feature_by_id:
                    return vertex_id
        if node_ref and node_ref.get("mode") == "new":
            return create_node(
                node_ref.get("geom", {}).get("coordinates") or fallback_coord,
                node_ref.get("sourceNodeKey"),
            )
        return create_node(fallback_coord)

    def create_node(coord: list[float], source_node_key: str | None = None) -> int:
        nonlocal next_vertex_id
        key = coord_key(coord)
        if key in node_by_coord:
            return node_by_coord[key]
        existing_vertex_id = existing_node_within(coord)
        if existing_vertex_id is not None:
            node_by_coord[key] = existing_vertex_id
            return existing_vertex_id
        vertex_id = next_vertex_id
        next_vertex_id += 1
        node_by_coord[key] = vertex_id
        node = {
            "type": "Feature",
            "properties": {
                "vertexId": vertex_id,
                "sourceNodeKey": source_node_key or f"manual_endpoint:{key}",
                "nodeType": "MANUAL",
                "degree": 0,
                "endpointCount": 1,
                "projectedKey": "",
            },
            "geometry": {"type": "Point", "coordinates": [float(coord[0]), float(coord[1])]},
        }
        nodes.append(node)
        node_feature_by_id[vertex_id] = node
        return vertex_id

    for edit in edit_document.get("edits", []):
        action = edit.get("action")
        geometry = edit.get("geom") or {}
        if action == "add_node":
            if geometry.get("type") != "Point":
                raise ValueError(f"add_node requires Point geom: {edit!r}")
            create_node(geometry["coordinates"], edit.get("sourceNodeKey"))
        elif action == "add_segment":
            if geometry.get("type") != "LineString":
                raise ValueError(f"add_segment requires LineString geom: {edit!r}")
            coords = geometry["coordinates"]
            if len(coords) < 2:
                raise ValueError(f"add_segment requires at least two coordinates: {edit!r}")
            from_node_id = resolve_node_ref(edit.get("fromNode"), coords[0])
            to_node_id = resolve_node_ref(edit.get("toNode"), coords[-1])
            if from_node_id == to_node_id:
                continue
            segments.append(
                {
                    "type": "Feature",
                    "properties": {
                        "edgeId": next_edge_id,
                        "fromNodeId": from_node_id,
                        "toNodeId": to_node_id,
                        "segmentType": normalize_segment_type(edit.get("segmentType", "SIDE_LINE")),
                        "sourceIndex": 0,
                        "sourcePart": 0,
                        "roadWidthMeter": None,
                        "offsetMeter": None,
                        "lengthMeter": round(line_length_meter(coords), 2),
                    },
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[float(lng), float(lat)] for lng, lat in coords],
                    },
                }
            )
            next_edge_id += 1

    patched["meta"]["title"] = f"{patched['meta'].get('title', '02C graph')} with Manual Edits"
    patched["meta"]["manualEditCount"] = len(edit_document.get("edits", []))
    refresh_summary(patched)
    return patched


def validate_payload(payload: dict[str, Any]) -> dict[str, int]:
    nodes = payload["layers"]["roadNodes"]["features"]
    segments = payload["layers"]["roadSegments"]["features"]
    node_ids = {int(node["properties"]["vertexId"]) for node in nodes}
    orphan_edges = 0
    invalid_geometries = 0
    invalid_lengths = 0
    for node in nodes:
        if node.get("geometry", {}).get("type") != "Point":
            invalid_geometries += 1
    for segment in segments:
        props = segment["properties"]
        geometry = segment.get("geometry", {})
        if int(props["fromNodeId"]) not in node_ids or int(props["toNodeId"]) not in node_ids:
            orphan_edges += 1
        if geometry.get("type") != "LineString" or len(geometry.get("coordinates") or []) < 2:
            invalid_geometries += 1
        if float(props.get("lengthMeter") or 0) <= 0:
            invalid_lengths += 1
    report = {
        "node_count": len(nodes),
        "segment_count": len(segments),
        "orphan_edges": orphan_edges,
        "invalid_geometries": invalid_geometries,
        "invalid_lengths": invalid_lengths,
    }
    failures = {key: value for key, value in report.items() if key not in {"node_count", "segment_count"} and value}
    if report["node_count"] == 0 or report["segment_count"] == 0 or failures:
        raise RuntimeError(f"invalid graph payload: {report}")
    return report


def build_csv_payload(
    *,
    node_csv: Path,
    segment_csv: Path,
    output_html: Path = CSV_EDIT_OUTPUT_HTML,
    output_geojson: Path = CSV_EDIT_OUTPUT_GEOJSON,
    bbox: tuple[float, float, float, float] | None = None,
) -> dict[str, Any]:
    with node_csv.open("r", encoding="utf-8", newline="") as fh:
        node_features = [
            {
                "type": "Feature",
                "properties": {
                    "vertexId": int(row["vertexId"]),
                    "sourceNodeKey": row["sourceNodeKey"],
                    "nodeType": "CSV",
                    "degree": 0,
                    "endpointCount": 1,
                    "projectedKey": "",
                },
                "geometry": ewkt_to_geometry(row["point"]),
            }
            for row in csv.DictReader(fh)
        ]

    with segment_csv.open("r", encoding="utf-8", newline="") as fh:
        segment_features = [
            {
                "type": "Feature",
                "properties": {
                    "edgeId": int(row["edgeId"]),
                    "fromNodeId": int(row["fromNodeId"]),
                    "toNodeId": int(row["toNodeId"]),
                    "segmentType": normalize_segment_type(row.get("segmentType")),
                    "lengthMeter": float(row["lengthMeter"]),
                },
                "geometry": ewkt_to_geometry(row["geom"]),
            }
            for row in csv.DictReader(fh)
        ]

    if bbox is not None:
        segment_features = [feature for feature in segment_features if feature_in_bbox(feature, bbox)]
        visible_node_ids: set[int] = set()
        for segment in segment_features:
            props = segment["properties"]
            visible_node_ids.add(int(props["fromNodeId"]))
            visible_node_ids.add(int(props["toNodeId"]))
        node_features = [
            feature
            for feature in node_features
            if int(feature["properties"]["vertexId"]) in visible_node_ids or feature_in_bbox(feature, bbox)
        ]

    center_lon = 128.872
    center_lat = 35.095
    if bbox is not None:
        center_lon = (bbox[0] + bbox[2]) / 2
        center_lat = (bbox[1] + bbox[3]) / 2

    payload = {
        "meta": {
            "title": "02C CSV-backed Graph Manual Edit UI",
            "centerLat": round(center_lat, 7),
            "centerLon": round(center_lon, 7),
            "radiusMeter": 0,
            "sourceShp": "road_nodes/road_segments CSV",
            "outputHtml": str(output_html),
            "outputGeojson": str(output_geojson),
            "localhostUrl": f"http://127.0.0.1:3000/etl/{output_html.name}",
            "stage": "02c-csv-backed-manual-edit-ui",
            "manualEditRule": (
                "CSV-backed subset for Songjeong-dong, Sinho-dong, Noksan-dong, and Hwajeon-dong; "
                "export manual_edits JSON for the next patch cycle"
            ),
        },
        "summary": {
            "nodeCount": len(node_features),
            "segmentCount": len(segment_features),
            "segmentTypeCounts": [],
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
    if bbox is not None:
        payload["meta"]["bbox"] = {
            "minLon": bbox[0],
            "minLat": bbox[1],
            "maxLon": bbox[2],
            "maxLat": bbox[3],
        }
    refresh_summary(payload)
    validate_payload(payload)
    return payload


def ensure_graph_schema(cur: Any) -> None:
    cur.execute(
        """
        ALTER TABLE "road_segments"
        ADD COLUMN IF NOT EXISTS "segmentType" VARCHAR(30) NOT NULL DEFAULT 'CENTERLINE'
        """
    )
    cur.execute('CREATE INDEX IF NOT EXISTS idx_road_segments_geom ON "road_segments" USING GIST ("geom")')
    cur.execute(
        'CREATE INDEX IF NOT EXISTS idx_road_segments_nodes ON "road_segments" ("fromNodeId", "toNodeId")'
    )


def load_payload_to_db(payload: dict[str, Any]) -> dict[str, int]:
    validate_payload(payload)
    nodes = payload["layers"]["roadNodes"]["features"]
    segments = payload["layers"]["roadSegments"]["features"]
    with connect() as conn:
        with conn.cursor() as cur:
            ensure_graph_schema(cur)
            cur.execute('TRUNCATE TABLE "segment_features", "road_segments", "road_nodes" RESTART IDENTITY CASCADE')
            for node in nodes:
                props = node["properties"]
                insert_row(
                    cur,
                    "road_nodes",
                    {
                        "vertexId": int(props["vertexId"]),
                        "sourceNodeKey": str(props["sourceNodeKey"]),
                        "point": ewkt(geometry_to_ewkt(node["geometry"])),
                    },
                )
            for segment in segments:
                props = segment["properties"]
                insert_row(
                    cur,
                    "road_segments",
                    {
                        "edgeId": int(props["edgeId"]),
                        "fromNodeId": int(props["fromNodeId"]),
                        "toNodeId": int(props["toNodeId"]),
                        "geom": ewkt(geometry_to_ewkt(segment["geometry"])),
                        "lengthMeter": float(props["lengthMeter"]),
                        "segmentType": normalize_segment_type(props.get("segmentType")),
                    },
                )
        conn.commit()
    return post_load_validate()


def write_csv_outputs(
    payload: dict[str, Any],
    *,
    node_csv: Path = CSV_NODE_OUTPUT,
    segment_csv: Path = CSV_SEGMENT_OUTPUT,
) -> dict[str, Any]:
    validate_payload(payload)
    nodes = payload["layers"]["roadNodes"]["features"]
    segments = payload["layers"]["roadSegments"]["features"]
    node_csv.parent.mkdir(parents=True, exist_ok=True)
    segment_csv.parent.mkdir(parents=True, exist_ok=True)

    with node_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["vertexId", "sourceNodeKey", "point"])
        writer.writeheader()
        for node in nodes:
            props = node["properties"]
            writer.writerow(
                {
                    "vertexId": int(props["vertexId"]),
                    "sourceNodeKey": str(props["sourceNodeKey"]),
                    "point": geometry_to_ewkt(node["geometry"]),
                }
            )

    segment_fields = [
        "edgeId",
        "fromNodeId",
        "toNodeId",
        "geom",
        "lengthMeter",
        "walkAccess",
        "avgSlopePercent",
        "widthMeter",
        "brailleBlockState",
        "audioSignalState",
        "rampState",
        "widthState",
        "surfaceState",
        "stairsState",
        "elevatorState",
        "crossingState",
        "segmentType",
    ]
    with segment_csv.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=segment_fields)
        writer.writeheader()
        for segment in segments:
            props = segment["properties"]
            writer.writerow(
                {
                    "edgeId": int(props["edgeId"]),
                    "fromNodeId": int(props["fromNodeId"]),
                    "toNodeId": int(props["toNodeId"]),
                    "geom": geometry_to_ewkt(segment["geometry"]),
                    "lengthMeter": f"{float(props['lengthMeter']):.2f}",
                    "walkAccess": "UNKNOWN",
                    "avgSlopePercent": "",
                    "widthMeter": "",
                    "brailleBlockState": "UNKNOWN",
                    "audioSignalState": "UNKNOWN",
                    "rampState": "UNKNOWN",
                    "widthState": "UNKNOWN",
                    "surfaceState": "UNKNOWN",
                    "stairsState": "UNKNOWN",
                    "elevatorState": "UNKNOWN",
                    "crossingState": "UNKNOWN",
                        "segmentType": normalize_segment_type(props.get("segmentType")),
                }
            )

    return {
        "nodeCsv": str(node_csv),
        "segmentCsv": str(segment_csv),
        "nodeCount": len(nodes),
        "segmentCount": len(segments),
    }


def post_load_validate() -> dict[str, int]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM "road_nodes"')
            node_count = int(cur.fetchone()[0])
            cur.execute('SELECT COUNT(*) FROM "road_segments"')
            segment_count = int(cur.fetchone()[0])
            cur.execute(
                """
                SELECT COUNT(*)
                FROM "road_segments" rs
                LEFT JOIN "road_nodes" f ON f."vertexId" = rs."fromNodeId"
                LEFT JOIN "road_nodes" t ON t."vertexId" = rs."toNodeId"
                WHERE f."vertexId" IS NULL OR t."vertexId" IS NULL
                """
            )
            orphan_edges = int(cur.fetchone()[0])
            cur.execute('SELECT COUNT(*) FROM "road_segments" WHERE NOT ST_IsValid("geom")')
            invalid_geometries = int(cur.fetchone()[0])
            cur.execute('SELECT COUNT(*) FROM "road_segments" WHERE ST_SRID("geom") <> 4326')
            invalid_srid = int(cur.fetchone()[0])
            cur.execute('SELECT COUNT(*) FROM "road_segments" WHERE "lengthMeter" <= 0')
            invalid_lengths = int(cur.fetchone()[0])
    report = {
        "node_count": node_count,
        "segment_count": segment_count,
        "orphan_edges": orphan_edges,
        "invalid_geometries": invalid_geometries,
        "invalid_srid": invalid_srid,
        "invalid_lengths": invalid_lengths,
    }
    failures = {key: value for key, value in report.items() if key not in {"node_count", "segment_count"} and value}
    if node_count == 0 or segment_count == 0 or failures:
        raise RuntimeError(f"post-load validation failed: {report}")
    return report


def _json_geometry(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return json.loads(value)
    return value


def build_db_payload(
    *,
    output_html: Path = DB_OUTPUT_HTML,
    output_geojson: Path = DB_OUTPUT_GEOJSON,
) -> dict[str, Any]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH degree AS (
                    SELECT node_id, COUNT(*)::int AS degree
                    FROM (
                        SELECT "fromNodeId" AS node_id FROM "road_segments"
                        UNION ALL
                        SELECT "toNodeId" AS node_id FROM "road_segments"
                    ) edges
                    GROUP BY node_id
                )
                SELECT rn."vertexId", rn."sourceNodeKey", COALESCE(d.degree, 0), ST_AsGeoJSON(rn."point")::json
                FROM "road_nodes" rn
                LEFT JOIN degree d ON d.node_id = rn."vertexId"
                ORDER BY rn."vertexId"
                """
            )
            node_features = [
                {
                    "type": "Feature",
                    "properties": {
                        "vertexId": int(vertex_id),
                        "sourceNodeKey": source_node_key,
                        "nodeType": "DB",
                        "degree": int(degree),
                    },
                    "geometry": _json_geometry(geometry),
                }
                for vertex_id, source_node_key, degree, geometry in cur.fetchall()
            ]
            cur.execute(
                """
                SELECT
                    "edgeId",
                    "fromNodeId",
                    "toNodeId",
                    "segmentType",
                    "lengthMeter",
                    ST_AsGeoJSON("geom")::json
                FROM "road_segments"
                ORDER BY "edgeId"
                """
            )
            segment_features = [
                {
                    "type": "Feature",
                    "properties": {
                        "edgeId": int(edge_id),
                        "fromNodeId": int(from_node_id),
                        "toNodeId": int(to_node_id),
                        "segmentType": normalize_segment_type(segment_type),
                        "lengthMeter": float(length_meter),
                    },
                    "geometry": _json_geometry(geometry),
                }
                for edge_id, from_node_id, to_node_id, segment_type, length_meter, geometry in cur.fetchall()
            ]

    segment_counts = Counter(feature["properties"]["segmentType"] for feature in segment_features)
    return {
        "meta": {
            "title": "02C DB-backed Road Graph Preview",
            "centerLat": 35.1633200,
            "centerLon": 129.1588705,
            "radiusMeter": 5000,
            "sourceShp": "road_nodes/road_segments",
            "outputHtml": str(output_html),
            "outputGeojson": str(output_geojson),
            "localhostUrl": f"http://127.0.0.1:3000/etl/{output_html.name}",
            "stage": "02c-db-backed-preview",
        },
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


def write_db_outputs(
    *,
    output_html: Path = DB_OUTPUT_HTML,
    output_geojson: Path = DB_OUTPUT_GEOJSON,
) -> dict[str, Any]:
    payload = build_db_payload(output_html=output_html, output_geojson=output_geojson)
    output_geojson.parent.mkdir(parents=True, exist_ok=True)
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_geojson.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_html.write_text(subway_elevator_preview.render_html(payload), encoding="utf-8")
    return payload


def write_csv_edit_outputs(
    *,
    node_csv: Path,
    segment_csv: Path,
    output_html: Path = CSV_EDIT_OUTPUT_HTML,
    output_geojson: Path = CSV_EDIT_OUTPUT_GEOJSON,
    bbox: tuple[float, float, float, float] | None = None,
) -> dict[str, Any]:
    payload = build_csv_payload(
        node_csv=node_csv,
        segment_csv=segment_csv,
        output_html=output_html,
        output_geojson=output_geojson,
        bbox=bbox,
    )
    output_geojson.parent.mkdir(parents=True, exist_ok=True)
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_geojson.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_html.write_text(segment_graph_edit_ui.render_html(payload), encoding="utf-8")
    return payload


def apply_csv_manual_edits(
    *,
    node_csv: Path,
    segment_csv: Path,
    manual_edits: Path,
) -> dict[str, Any]:
    payload = build_csv_payload(node_csv=node_csv, segment_csv=segment_csv)
    patched = apply_manual_edits(payload, load_json(manual_edits))
    return write_csv_outputs(patched, node_csv=node_csv, segment_csv=segment_csv)


def apply_csv_edit_document(
    *,
    node_csv: Path,
    segment_csv: Path,
    edit_document: dict[str, Any],
) -> dict[str, Any]:
    payload = build_csv_payload(node_csv=node_csv, segment_csv=segment_csv)
    patched = apply_manual_edits(payload, edit_document)
    return write_csv_outputs(patched, node_csv=node_csv, segment_csv=segment_csv)


def load_graph_file_to_db(
    *,
    source_geojson: Path = DEFAULT_SOURCE_GEOJSON,
    manual_edits: Path | None = None,
) -> dict[str, Any]:
    payload = load_json(source_geojson)
    if manual_edits is not None:
        payload = apply_manual_edits(payload, load_json(manual_edits))
    load_report = load_payload_to_db(payload)
    db_payload = write_db_outputs()
    return {
        "load": load_report,
        "preview": {
            "outputHtml": str(DB_OUTPUT_HTML),
            "outputGeojson": str(DB_OUTPUT_GEOJSON),
            "nodeCount": db_payload["summary"]["nodeCount"],
            "segmentCount": db_payload["summary"]["segmentCount"],
            "segmentTypeCounts": db_payload["summary"]["segmentTypeCounts"],
        },
    }


def export_graph_file_to_csv(
    *,
    source_geojson: Path = DEFAULT_SOURCE_GEOJSON,
    manual_edits: Path | None = None,
    node_csv: Path = CSV_NODE_OUTPUT,
    segment_csv: Path = CSV_SEGMENT_OUTPUT,
) -> dict[str, Any]:
    payload = load_json(source_geojson)
    if manual_edits is not None:
        payload = apply_manual_edits(payload, load_json(manual_edits))
    return write_csv_outputs(payload, node_csv=node_csv, segment_csv=segment_csv)
