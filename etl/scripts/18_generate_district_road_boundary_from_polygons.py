#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform, unary_union

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from etl.common import segment_centerline_02c, subway_elevator_preview


PROJECT_TO_WGS84 = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)
WGS84_TO_PROJECT = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)


def load_district_collection(source_js: Path, district: str) -> dict[str, Any]:
    text = source_js.read_text(encoding="utf-8")
    marker = f"[{json.dumps(district, ensure_ascii=False)}]"
    marker_index = text.find(marker)
    if marker_index < 0:
        raise ValueError(f"district not found in JS asset: {district}")
    assignment_index = text.find("= ", marker_index)
    if assignment_index < 0:
        raise ValueError(f"district assignment not found in JS asset: {district}")
    return json.loads(text[assignment_index + 2 : text.rfind(";")])


def build_boundary_payload(*, collection: dict[str, Any], district: str, source_js: Path) -> dict[str, Any]:
    projected_geometries = [
        transform(WGS84_TO_PROJECT.transform, shape(feature["geometry"]))
        for feature in collection.get("features", [])
    ]
    projected_geometries = [geometry for geometry in projected_geometries if not geometry.is_empty]
    merged_surface = unary_union(projected_geometries)
    if segment_centerline_02c.ROAD_BOUNDARY_SIMPLIFY_M > 0:
        merged_surface = merged_surface.simplify(
            segment_centerline_02c.ROAD_BOUNDARY_SIMPLIFY_M,
            preserve_topology=True,
        )

    boundary_lines = segment_centerline_02c.boundary_lines_from_surface(
        merged_surface,
        exterior_area_max_m2=None,
        remove_caps=True,
    )
    segment_features: list[dict[str, Any]] = []
    skipped_parts = 0
    for edge_id, (segment_type, projected_coords) in enumerate(boundary_lines, start=1):
        coords = segment_centerline_02c.transform_projected_coords(projected_coords)
        length_meter = segment_centerline_02c.line_length_meter(coords)
        if len(coords) < 2 or length_meter <= segment_centerline_02c.MIN_LINE_LENGTH_M:
            skipped_parts += 1
            continue
        segment_features.append(
            {
                "type": "Feature",
                "properties": {
                    "edgeId": len(segment_features) + 1,
                    "segmentType": segment_type,
                    "lengthMeter": round(length_meter, 2),
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[float(lng), float(lat)] for lng, lat in coords],
                },
            }
        )

    segment_counts = Counter(feature["properties"]["segmentType"] for feature in segment_features)
    bounds = merged_surface.bounds if not merged_surface.is_empty else (0.0, 0.0, 0.0, 0.0)
    min_lon, min_lat = PROJECT_TO_WGS84.transform(bounds[0], bounds[1])
    max_lon, max_lat = PROJECT_TO_WGS84.transform(bounds[2], bounds[3])
    return {
        "meta": {
            "title": f"{district} Road Boundary v4 Preview",
            "districtGu": district,
            "centerLat": round((min_lat + max_lat) / 2, 7),
            "centerLon": round((min_lon + max_lon) / 2, 7),
            "radiusMeter": 0,
            "sourceShp": str(source_js),
            "sourceEncoding": "utf-8",
            "outputHtml": "",
            "outputGeojson": "",
            "localhostUrl": "",
            "stage": "road-boundary-buffer-union",
            "sourceShapeCount": len(collection.get("features", [])),
            "clippedPartCount": len(projected_geometries),
            "bufferedPartCount": len(projected_geometries),
            "skippedPartCount": skipped_parts,
            "widthFallbackCount": 0,
            "boundaryRule": "union prepared district road-surface polygons, then render polygon boundary rings",
            "halfWidthRule": "uses prepared road polygon buffer widths from poc_submit road-polygons asset",
            "simplifyMeter": segment_centerline_02c.ROAD_BOUNDARY_SIMPLIFY_M,
            "capRemovalMaxMeter": segment_centerline_02c.ROAD_BOUNDARY_CAP_MAX_M,
            "internalPerpendicularPruneCount": 0,
            "internalPerpendicularMaxMeter": segment_centerline_02c.ROAD_BOUNDARY_INTERNAL_CAP_MAX_M,
            "internalPerpendicularCenterlineMaxMeter": segment_centerline_02c.ROAD_BOUNDARY_INTERNAL_CENTERLINE_MAX_M,
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


def main_with_args(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate district road-boundary preview from prepared road polygon JS.")
    parser.add_argument("--district", required=True)
    parser.add_argument("--source-js", type=Path, required=True)
    parser.add_argument("--output-geojson", type=Path, required=True)
    parser.add_argument("--output-html", type=Path, required=True)
    args = parser.parse_args(argv)

    collection = load_district_collection(args.source_js, args.district)
    payload = build_boundary_payload(collection=collection, district=args.district, source_js=args.source_js)
    payload["meta"]["outputHtml"] = str(args.output_html)
    payload["meta"]["outputGeojson"] = str(args.output_geojson)
    payload["meta"]["localhostUrl"] = f"http://127.0.0.1:3000/etl/{args.output_html.name}"
    args.output_geojson.parent.mkdir(parents=True, exist_ok=True)
    args.output_html.parent.mkdir(parents=True, exist_ok=True)
    args.output_geojson.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.output_html.write_text(subway_elevator_preview.render_html(payload), encoding="utf-8")
    print(json.dumps({"outputGeojson": str(args.output_geojson), **payload["summary"]}, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    return main_with_args()


if __name__ == "__main__":
    raise SystemExit(main())
