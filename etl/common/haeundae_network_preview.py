from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from etl.common.db import connect


ROOT_DIR = Path(__file__).resolve().parents[2]
ETL_DIR = ROOT_DIR / "etl"
OUTPUT_HTML = ETL_DIR / "haeundae_network_preview.html"
OUTPUT_GEOJSON = ETL_DIR / "haeundae_network_preview.geojson"

DEFAULT_CENTER_LAT = 35.1631
DEFAULT_CENTER_LON = 129.1635
DEFAULT_RADIUS_M = 5000

EDGE_STYLE = {"color": "#475569", "weight": 2, "opacity": 0.72}
NODE_STYLE = {"color": "#111827", "radius": 2, "fillOpacity": 0.85}


def _feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": features}


def _json_geometry(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return json.loads(value)
    return value


def build_payload(
    *,
    center_lat: float = DEFAULT_CENTER_LAT,
    center_lon: float = DEFAULT_CENTER_LON,
    radius_m: int = DEFAULT_RADIUS_M,
) -> dict[str, Any]:
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH center AS (
                    SELECT ST_SetSRID(ST_MakePoint(%s, %s), 4326) AS geom
                )
                SELECT
                    rs."edgeId",
                    rs."fromNodeId",
                    rs."toNodeId",
                    rs."lengthMeter",
                    ST_AsGeoJSON(rs."geom")
                FROM road_segments rs, center c
                WHERE ST_DWithin(rs."geom"::geography, c.geom::geography, %s)
                ORDER BY rs."edgeId"
                """,
                (center_lon, center_lat, radius_m),
            )
            road_segment_features = [
                {
                    "type": "Feature",
                    "properties": {
                        "edgeId": int(edge_id),
                        "fromNodeId": int(from_node_id),
                        "toNodeId": int(to_node_id),
                        "lengthMeter": float(length_meter),
                    },
                    "geometry": _json_geometry(geometry),
                }
                for edge_id, from_node_id, to_node_id, length_meter, geometry in cur.fetchall()
            ]

            cur.execute(
                """
                WITH center AS (
                    SELECT ST_SetSRID(ST_MakePoint(%s, %s), 4326) AS geom
                )
                SELECT
                    rn."vertexId",
                    rn."sourceNodeKey",
                    ST_AsGeoJSON(rn."point")
                FROM road_nodes rn, center c
                WHERE ST_DWithin(rn."point"::geography, c.geom::geography, %s)
                ORDER BY rn."vertexId"
                """,
                (center_lon, center_lat, radius_m),
            )
            road_node_features = [
                {
                    "type": "Feature",
                    "properties": {"vertexId": int(vertex_id), "sourceNodeKey": source_node_key},
                    "geometry": _json_geometry(geometry),
                }
                for vertex_id, source_node_key, geometry in cur.fetchall()
            ]

    return {
        "meta": {
            "title": "Haeundae Network Preview",
            "centerLat": center_lat,
            "centerLon": center_lon,
            "radiusMeter": radius_m,
            "outputHtml": str(OUTPUT_HTML),
            "outputGeojson": str(OUTPUT_GEOJSON),
        },
        "summary": {
            "roadSegments": len(road_segment_features),
            "roadNodes": len(road_node_features),
        },
        "layers": {
            "roadSegments": _feature_collection(road_segment_features),
            "roadNodes": _feature_collection(road_node_features),
        },
    }


def render_html(payload: dict[str, Any]) -> str:
    meta = payload["meta"]
    summary = payload["summary"]
    summary_text = html.escape(
        f"center ({meta['centerLat']:.4f}, {meta['centerLon']:.4f}), radius {meta['radiusMeter']}m, "
        f"edges {summary['roadSegments']}, nodes {summary['roadNodes']}"
    )
    payload_json = json.dumps(payload, ensure_ascii=False)
    edge_style_json = json.dumps(EDGE_STYLE, ensure_ascii=False)
    node_style_json = json.dumps(NODE_STYLE, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(meta['title'])}</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <style>
    html, body, #map {{ height: 100%; margin: 0; }}
    body {{ font: 13px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .panel {{
      position: absolute;
      z-index: 700;
      top: 12px;
      left: 12px;
      width: min(360px, calc(100vw - 24px));
      padding: 12px 14px;
      background: rgba(255, 255, 255, 0.94);
      border: 1px solid #cbd5e1;
      box-shadow: 0 6px 20px rgba(15, 23, 42, 0.12);
    }}
    .panel h1 {{
      margin: 0 0 8px;
      font-size: 15px;
    }}
    .panel p {{
      margin: 0 0 10px;
      color: #334155;
    }}
    .legend {{
      display: grid;
      grid-template-columns: repeat(2, minmax(120px, 1fr));
      gap: 6px 10px;
      margin-top: 8px;
    }}
    .legend-item {{
      display: flex;
      align-items: center;
      gap: 8px;
    }}
    .legend-swatch {{
      width: 12px;
      height: 12px;
      border-radius: 999px;
      border: 1px solid rgba(15, 23, 42, 0.18);
      flex: 0 0 auto;
    }}
    .leaflet-popup-content pre {{
      white-space: pre-wrap;
      margin: 0;
      font-size: 11px;
    }}
  </style>
</head>
<body>
  <div id="map"></div>
  <div class="panel">
    <h1>{html.escape(meta['title'])}</h1>
    <p>{summary_text}</p>
    <div class="legend">
      <div class="legend-item">
        <span class="legend-swatch" style="background:{EDGE_STYLE['color']}"></span>
        <span>roadSegments</span>
      </div>
      <div class="legend-item">
        <span class="legend-swatch" style="background:{NODE_STYLE['color']}"></span>
        <span>roadNodes</span>
      </div>
    </div>
  </div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    const payload = {payload_json};
    const edgeStyle = {edge_style_json};
    const nodeStyle = {node_style_json};

    const map = L.map('map').setView([payload.meta.centerLat, payload.meta.centerLon], 14);
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors'
    }}).addTo(map);

    function popupHtml(properties) {{
      return Object.entries(properties || {{}})
        .map(([key, value]) => `<strong>${{key}}</strong>: <pre>${{String(value)}}</pre>`)
        .join('');
    }}

    const edgeLayer = L.geoJSON(payload.layers.roadSegments, {{
      style: edgeStyle,
      onEachFeature: (feature, layer) => layer.bindPopup(popupHtml(feature.properties || {{}}))
    }}).addTo(map);

    const nodeLayer = L.geoJSON(payload.layers.roadNodes, {{
      pointToLayer: (feature, latlng) => L.circleMarker(latlng, {{
        radius: nodeStyle.radius,
        color: nodeStyle.color,
        fillColor: nodeStyle.color,
        fillOpacity: nodeStyle.fillOpacity,
        weight: 1
      }}),
      onEachFeature: (feature, layer) => layer.bindPopup(popupHtml(feature.properties || {{}}))
    }}).addTo(map);

    L.control.layers({{}}, {{
      roadSegments: edgeLayer,
      roadNodes: nodeLayer
    }}, {{ collapsed: false }}).addTo(map);

    const fitLayer = L.featureGroup([edgeLayer, nodeLayer]);
    if (fitLayer.getBounds().isValid()) {{
      map.fitBounds(fitLayer.getBounds(), {{ padding: [20, 20] }});
    }}
  </script>
</body>
</html>
"""


def generate_preview(
    *,
    center_lat: float = DEFAULT_CENTER_LAT,
    center_lon: float = DEFAULT_CENTER_LON,
    radius_m: int = DEFAULT_RADIUS_M,
) -> dict[str, Any]:
    payload = build_payload(center_lat=center_lat, center_lon=center_lon, radius_m=radius_m)
    OUTPUT_GEOJSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUTPUT_HTML.write_text(render_html(payload), encoding="utf-8")
    return payload["summary"] | {"outputHtml": str(OUTPUT_HTML), "outputGeojson": str(OUTPUT_GEOJSON)}
