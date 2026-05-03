#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import mimetypes
import sys
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from shapely.geometry import mapping as shapely_mapping


ROOT_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT_DIR / "etl" / "raw"
ETL_DIR = ROOT_DIR / "etl"

SEGMENT_CSV = RAW_DIR / "gangseo_road_segments_mapping_v2.csv"
HTML_PATH = ETL_DIR / "gangseo_mapping_gap_overlay_map.html"
BACKEND_ROUTE_URL = "http://127.0.0.1:18080/api/v1/routes/search"


def load_mapping_module():
    script = Path(__file__).resolve().parent / "23_map_gangseo_v6_attributes.py"
    spec = importlib.util.spec_from_file_location("gangseo_v6_attribute_mapping", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load mapping module: {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


MAPPING = load_mapping_module()


@dataclass(frozen=True)
class LayerSpec:
    key: str
    title: str
    dataset: str
    column: str
    path: Path
    radius_meter: float
    radius_getter: Callable[[dict[str, str]], float] | None
    geom_getter: Callable[[dict[str, str]], object | None]
    row_filter: Callable[[dict[str, str]], bool]
    segment_filter: Callable[[dict[str, str]], bool] | None
    prop_keys: tuple[str, ...]
    color: str


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def gangseo_rows(path: Path, gu_key: str = "districtGu") -> list[dict[str, str]]:
    return [row for row in read_csv(path) if (row.get(gu_key) or "").strip() == "강서구"]


def geom_to_json(geom) -> dict[str, Any]:
    return shapely_mapping(geom)


def bbox_intersects(left: tuple[float, float, float, float], right: tuple[float, float, float, float]) -> bool:
    return left[2] >= right[0] and left[0] <= right[2] and left[3] >= right[1] and left[1] <= right[3]


def parse_bbox(value: str | None, fallback: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    if not value:
        return fallback
    parts = [float(part) for part in value.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must be minLng,minLat,maxLng,maxLat")
    return parts[0], parts[1], parts[2], parts[3]


def compact_props(row: dict[str, str], keys: tuple[str, ...]) -> dict[str, str]:
    return {key: row.get(key, "") for key in keys if row.get(key, "") not in {"", None}}


def slope_surface_radius(row: dict[str, str]) -> float:
    width = MAPPING.parse_float(row.get("widthMeter"))
    if width is None or width <= 0:
        return 10.0
    return max(10.0, width / 2.0 + 2.0)


def source_rows_for(spec: LayerSpec) -> list[dict[str, str]]:
    if spec.key == "audio":
        rows = gangseo_rows(spec.path, "sigungu")
    else:
        rows = gangseo_rows(spec.path)
    return [row for row in rows if spec.row_filter(row)]


def layer_specs() -> list[LayerSpec]:
    side_walk_only = lambda row: row.get("segmentType") == "SIDE_WALK"
    always = lambda row: True
    return [
        LayerSpec(
            key="sidewalk",
            title="미매핑 인도/인도폭",
            dataset="인도&인도폭.csv",
            column="walkAccess,widthMeter",
            path=RAW_DIR / "인도&인도폭.csv",
            radius_meter=10.0,
            radius_getter=None,
            geom_getter=lambda row: MAPPING.parse_wkt_geometry(row.get("wkt")),
            row_filter=always,
            segment_filter=None,
            prop_keys=("segmentId", "districtGu", "segmentType", "widthMeter", "surfaceLabel", "routingStage"),
            color="#16a34a",
        ),
        LayerSpec(
            key="local",
            title="미매핑 이면도로",
            dataset="이면도로.csv",
            column="walkAccess,avgSlopePercent,slopeState",
            path=RAW_DIR / "이면도로.csv",
            radius_meter=10.0,
            radius_getter=None,
            geom_getter=lambda row: MAPPING.parse_wkt_geometry(row.get("geometryWkt")),
            row_filter=always,
            segment_filter=None,
            prop_keys=("sourceId", "networkLabel", "roadName", "widthMeter", "slopePercent", "surfaceLabel", "sidewalkLabel"),
            color="#64748b",
        ),
        LayerSpec(
            key="slope",
            title="미매핑 경사도/표면",
            dataset="경사도&표면타입.csv",
            column="avgSlopePercent,slopeState,surfaceState",
            path=RAW_DIR / "경사도&표면타입.csv",
            radius_meter=10.0,
            radius_getter=slope_surface_radius,
            geom_getter=lambda row: MAPPING.parse_wkt_geometry(row.get("geometryWkt")),
            row_filter=always,
            segment_filter=None,
            prop_keys=("sourceId", "roadName", "surfaceType", "slopeMean", "slopeMax", "slopeLevel", "riskLevel", "widthMeter"),
            color="#f97316",
        ),
        LayerSpec(
            key="audio",
            title="미매핑 음향신호기",
            dataset="횡단보도_음향신호기.csv",
            column="audioSignalState",
            path=RAW_DIR / "횡단보도_음향신호기.csv",
            radius_meter=MAPPING.AUDIO_SIGNAL_RADIUS_METER,
            radius_getter=None,
            geom_getter=MAPPING.point_from_row,
            row_filter=lambda row: (row.get("audioSignalState") or "").strip().upper() == "YES"
            and (row.get("stat") or "").strip() == "정상동작",
            segment_filter=side_walk_only,
            prop_keys=("sourceId", "location", "address", "audioSignalState", "stat", "confirmDate"),
            color="#8b5cf6",
        ),
        LayerSpec(
            key="signal",
            title="미매핑 횡단보도 신호등",
            dataset="횡단보도_신호등.csv",
            column="signalState",
            path=RAW_DIR / "횡단보도_신호등.csv",
            radius_meter=MAPPING.CROSSWALK_SIGNAL_RADIUS_METER,
            radius_getter=None,
            geom_getter=MAPPING.point_from_row,
            row_filter=lambda row: (row.get("crossingState") or "").strip().upper() == "TRAFFIC_SIGNALS",
            segment_filter=side_walk_only,
            prop_keys=("sourceId", "districtDong", "locationLabel", "crossingState", "widthMeter", "lengthMeter"),
            color="#ef4444",
        ),
        LayerSpec(
            key="stairs",
            title="미매핑 계단",
            dataset="계단.csv",
            column="stairsState",
            path=RAW_DIR / "계단.csv",
            radius_meter=2.0,
            radius_getter=None,
            geom_getter=lambda row: MAPPING.parse_wkt_geometry(row.get("geometryWkt")) or MAPPING.point_from_row(row),
            row_filter=lambda row: (row.get("stairsState") or "").strip().upper() == "YES",
            segment_filter=None,
            prop_keys=("sourceId", "name", "featureType", "stairsState", "nearestRoadDistanceM", "nearestRoadName"),
            color="#111827",
        ),
    ]


def load_base_segments() -> tuple[list[dict[str, Any]], list[dict[str, str]], tuple[float, float, float, float]]:
    rows = read_csv(SEGMENT_CSV)
    features: list[dict[str, Any]] = []
    bounds: list[tuple[float, float, float, float]] = []
    for row in rows:
        geom = MAPPING.parse_wkt_geometry(row.get("geom"))
        if geom is None:
            continue
        bounds.append(geom.bounds)
        features.append(
            {
                "id": row.get("edgeId", ""),
                "bbox": geom.bounds,
                "geometry": geom_to_json(geom),
                "properties": {
                    "edgeId": row.get("edgeId", ""),
                    "segmentType": row.get("segmentType", ""),
                    "walkAccess": row.get("walkAccess", ""),
                    "avgSlopePercent": row.get("avgSlopePercent", ""),
                    "widthMeter": row.get("widthMeter", ""),
                    "slopeState": row.get("slopeState", ""),
                    "surfaceState": row.get("surfaceState", ""),
                    "stairsState": row.get("stairsState", ""),
                    "signalState": row.get("signalState", ""),
                    "audioSignalState": row.get("audioSignalState", ""),
                },
            }
        )
    if not bounds:
        raise RuntimeError("base mapping segment CSV has no valid geometry")
    full = (
        min(item[0] for item in bounds),
        min(item[1] for item in bounds),
        max(item[2] for item in bounds),
        max(item[3] for item in bounds),
    )
    return features, rows, full


def build_unmatched_layers(segment_rows: list[dict[str, str]]) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    matcher = MAPPING.SegmentMatcher(segment_rows)
    layers: dict[str, list[dict[str, Any]]] = {}
    summary: list[dict[str, Any]] = []
    for spec in layer_specs():
        features: list[dict[str, Any]] = []
        source_rows = source_rows_for(spec)
        mapped = 0
        invalid = 0
        for index, row in enumerate(source_rows, start=1):
            geom = spec.geom_getter(row)
            if geom is None:
                invalid += 1
                continue
            radius_meter = spec.radius_getter(row) if spec.radius_getter is not None else spec.radius_meter
            match = matcher.nearest(geom, radius_meter, segment_filter=spec.segment_filter, prefer_overlap=False)
            if match is not None:
                mapped += 1
                continue
            features.append(
                {
                    "id": row.get("sourceId") or row.get("segmentId") or str(index),
                    "bbox": geom.bounds,
                    "geometry": geom_to_json(geom),
                    "properties": {
                        **compact_props(row, spec.prop_keys),
                        "dataset": spec.dataset,
                        "mappedColumn": spec.column,
                        "radiusMeter": round(radius_meter, 2),
                    },
                }
            )
        layers[spec.key] = features
        summary.append(
            {
                "key": spec.key,
                "title": spec.title,
                "dataset": spec.dataset,
                "column": spec.column,
                "sourceRows": len(source_rows),
                "mappedRows": mapped,
                "unmappedRows": len(features),
                "invalidRows": invalid,
                "color": spec.color,
            }
        )
    return layers, summary


def feature_collection(features: list[dict[str, Any]], bbox: tuple[float, float, float, float], limit: int) -> dict[str, Any]:
    selected = [feature for feature in features if bbox_intersects(feature["bbox"], bbox)]
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": feature["id"],
                "properties": feature["properties"],
                "geometry": feature["geometry"],
            }
            for feature in selected[:limit]
        ],
        "totalInBbox": len(selected),
        "returned": min(len(selected), limit),
        "limit": limit,
    }


def load_data() -> dict[str, Any]:
    base, segment_rows, full_bbox = load_base_segments()
    unmatched, summary = build_unmatched_layers(segment_rows)
    return {
        "base": base,
        "unmatched": unmatched,
        "summary": summary,
        "fullBBox": full_bbox,
    }


class GapMapHandler(BaseHTTPRequestHandler):
    server_version = "GangseoMappingGapMap/1.0"

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def redirect_to_map_host(self) -> None:
        self.send_response(302)
        self.send_header("Location", "http://localhost:3000/etl/gangseo_mapping_gap_overlay_map.html")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/api", "/api/"}:
            self.send_json({
                "ok": True,
                "service": "gangseo-mapping-gap-map",
                "mapUrl": "http://localhost:3000/etl/gangseo_mapping_gap_overlay_map.html",
                "dataEndpoint": "/api/gangseo-mapping-gap-data",
            })
            return
        if parsed.path == "/api/gangseo-mapping-gap-data":
            self.handle_data(parsed.query)
            return
        if parsed.path == "/" or parsed.path == "/etl/gangseo_mapping_gap_overlay_map.html":
            self.redirect_to_map_host()
            return
        if parsed.path.startswith("/etl/"):
            self.send_file(ROOT_DIR / parsed.path.lstrip("/"))
            return
        self.send_error(404, "not found")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/gangseo-route-search":
            self.handle_route_search()
            return
        self.send_error(404, "not found")

    def handle_route_search(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            request = Request(
                BACKEND_ROUTE_URL,
                data=body,
                headers={"Content-Type": self.headers.get("Content-Type", "application/json")},
                method="POST",
            )
            with urlopen(request, timeout=30) as response:
                response_body = response.read()
                status = response.status
                content_type = response.headers.get("Content-Type", "application/json; charset=utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=502)

    def handle_data(self, query: str) -> None:
        try:
            params = parse_qs(query)
            data = self.server.data  # type: ignore[attr-defined]
            bbox = parse_bbox(params.get("bbox", [None])[0], data["fullBBox"])
            limit = int(params.get("limit", ["5000"])[0])
            layer_filter = params.get("layers", [""])[0]
            requested = {item for item in layer_filter.split(",") if item} or set(data["unmatched"].keys())
            payload = {
                "ok": True,
                "fullBBox": data["fullBBox"],
                "summary": data["summary"],
                "base": feature_collection(data["base"], bbox, limit),
                "unmatched": {
                    key: feature_collection(features, bbox, limit)
                    for key, features in data["unmatched"].items()
                    if key in requested
                },
            }
            self.send_json(payload)
        except Exception as exc:
            self.send_json({"ok": False, "error": str(exc)}, status=500)

    def send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404, "file not found")
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if path.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve Gangseo mapping segments and unmatched source overlays.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3001)
    args = parser.parse_args()

    data = load_data()
    server = ThreadingHTTPServer((args.host, args.port), GapMapHandler)
    server.data = data
    print(f"gangseo-mapping-gap-map: http://{args.host}:{args.port}/etl/gangseo_mapping_gap_overlay_map.html")
    print("gangseo-mapping-gap-map: loaded", json.dumps({item["key"]: item["unmappedRows"] for item in data["summary"]}, ensure_ascii=False))
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
