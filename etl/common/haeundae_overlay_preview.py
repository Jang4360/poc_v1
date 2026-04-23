from __future__ import annotations

import html
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from etl.common.db import connect


ROOT_DIR = Path(__file__).resolve().parents[2]
ETL_DIR = ROOT_DIR / "etl"
OUTPUT_HTML = ETL_DIR / "haeundae_accessibility_overlay_preview.html"
OUTPUT_GEOJSON = ETL_DIR / "haeundae_accessibility_overlay_preview.geojson"

DEFAULT_CENTER_LAT = 35.1631
DEFAULT_CENTER_LON = 129.1635
DEFAULT_RADIUS_M = 5000

FEATURE_STYLES: dict[str, dict[str, Any]] = {
    "AUDIO_SIGNAL": {"color": "#f97316", "weight": 2, "radius": 5, "fillOpacity": 0.9},
    "CROSSWALK": {"color": "#ef4444", "weight": 2, "radius": 5, "fillOpacity": 0.9},
    "SUBWAY_ELEVATOR": {"color": "#22c55e", "weight": 2, "radius": 5, "fillOpacity": 0.9},
    "WIDTH": {"color": "#2563eb", "weight": 3, "radius": 5, "fillOpacity": 0.85},
    "SURFACE": {"color": "#06b6d4", "weight": 3, "radius": 5, "fillOpacity": 0.85},
    "SLOPE_ANALYSIS": {"color": "#a855f7", "weight": 2, "radius": 5, "fillOpacity": 0.18},
    "STAIRS": {"color": "#eab308", "weight": 2, "radius": 5, "fillOpacity": 0.22},
    "CONTINUOUS_MAP_N3A_A0063321": {"color": "#14b8a6", "weight": 2, "radius": 5, "fillOpacity": 0.16},
    "CONTINUOUS_MAP_N3A_A0070000": {"color": "#0f766e", "weight": 2, "radius": 5, "fillOpacity": 0.16},
    "CONTINUOUS_MAP_N3A_A0080000": {"color": "#f43f5e", "weight": 2, "radius": 5, "fillOpacity": 0.16},
    "CONTINUOUS_MAP_N3A_A0110020": {"color": "#8b5cf6", "weight": 2, "radius": 5, "fillOpacity": 0.16},
    "CONTINUOUS_MAP_N3L_A0123373": {"color": "#10b981", "weight": 2, "radius": 5, "fillOpacity": 0.16},
}

EDGE_STYLE = {"color": "#475569", "weight": 2, "opacity": 0.55}
NODE_STYLE = {"color": "#111827", "radius": 2, "fillOpacity": 0.8}


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
                    rs."avgSlopePercent",
                    rs."widthMeter",
                    rs."widthState",
                    rs."surfaceState",
                    rs."stairsState",
                    rs."elevatorState",
                    rs."audioSignalState",
                    rs."crossingState",
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
                        "avgSlopePercent": float(avg_slope) if avg_slope is not None else None,
                        "widthMeter": float(width_meter) if width_meter is not None else None,
                        "widthState": width_state,
                        "surfaceState": surface_state,
                        "stairsState": stairs_state,
                        "elevatorState": elevator_state,
                        "audioSignalState": audio_state,
                        "crossingState": crossing_state,
                    },
                    "geometry": _json_geometry(geometry),
                }
                for (
                    edge_id,
                    from_node_id,
                    to_node_id,
                    length_meter,
                    avg_slope,
                    width_meter,
                    width_state,
                    surface_state,
                    stairs_state,
                    elevator_state,
                    audio_state,
                    crossing_state,
                    geometry,
                ) in cur.fetchall()
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

            cur.execute(
                """
                WITH center AS (
                    SELECT ST_SetSRID(ST_MakePoint(%s, %s), 4326) AS geom
                )
                SELECT
                    sf."featureId",
                    sf."edgeId",
                    sf."featureType",
                    sf."sourceDataset",
                    sf."sourceLayer",
                    sf."sourceRowNumber",
                    sf."matchStatus",
                    sf."matchScore",
                    sf."properties"::text,
                    ST_AsGeoJSON(sf."geom")
                FROM segment_features sf, center c
                WHERE ST_DWithin(sf."geom"::geography, c.geom::geography, %s)
                ORDER BY sf."featureType", sf."featureId"
                """,
                (center_lon, center_lat, radius_m),
            )
            grouped_features: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for (
                feature_id,
                edge_id,
                feature_type,
                source_dataset,
                source_layer,
                source_row_number,
                match_status,
                match_score,
                properties_text,
                geometry,
            ) in cur.fetchall():
                grouped_features[feature_type].append(
                    {
                        "type": "Feature",
                        "properties": {
                            "featureId": int(feature_id),
                            "edgeId": int(edge_id),
                            "featureType": feature_type,
                            "sourceDataset": source_dataset,
                            "sourceLayer": source_layer,
                            "sourceRowNumber": source_row_number,
                            "matchStatus": match_status,
                            "matchScore": float(match_score) if match_score is not None else None,
                            "properties": json.loads(properties_text or "{}"),
                        },
                        "geometry": _json_geometry(geometry),
                    }
                )

    layers = {
        "roadSegments": _feature_collection(road_segment_features),
        "roadNodes": _feature_collection(road_node_features),
        "segmentFeatures": {key: _feature_collection(value) for key, value in sorted(grouped_features.items())},
    }
    return {
        "meta": {
            "title": "Haeundae Accessibility Overlay Preview",
            "centerLat": center_lat,
            "centerLon": center_lon,
            "radiusMeter": radius_m,
            "outputHtml": str(OUTPUT_HTML),
            "outputGeojson": str(OUTPUT_GEOJSON),
        },
        "summary": {
            "roadSegments": len(road_segment_features),
            "roadNodes": len(road_node_features),
            "featureCounts": {key: len(value["features"]) for key, value in layers["segmentFeatures"].items()},
        },
        "layers": layers,
    }


def render_html(payload: dict[str, Any]) -> str:
    meta = payload["meta"]
    summary = payload["summary"]
    feature_counts = ", ".join(f"{key} {count}" for key, count in summary["featureCounts"].items()) or "없음"
    summary_text = html.escape(
        f"center ({meta['centerLat']:.4f}, {meta['centerLon']:.4f}), radius {meta['radiusMeter']}m, "
        f"edges {summary['roadSegments']}, nodes {summary['roadNodes']}, features {feature_counts}"
    )
    payload_json = json.dumps(payload, ensure_ascii=False)
    style_json = json.dumps(FEATURE_STYLES, ensure_ascii=False)
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
      width: min(420px, calc(100vw - 24px));
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
      grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
      gap: 6px 10px;
      margin-top: 8px;
    }}
    .legend-item {{
      display: flex;
      align-items: center;
      gap: 8px;
      min-width: 0;
    }}
    .legend-swatch {{
      width: 12px;
      height: 12px;
      border-radius: 999px;
      border: 1px solid rgba(15, 23, 42, 0.18);
      flex: 0 0 auto;
    }}
    .legend-label {{
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
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
    <div class="legend" id="legend"></div>
  </div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    const payload = {payload_json};
    const featureStyles = {style_json};
    const edgeStyle = {edge_style_json};
    const nodeStyle = {node_style_json};

    const map = L.map('map').setView([payload.meta.centerLat, payload.meta.centerLon], 14);
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
      maxZoom: 19,
      attribution: '&copy; OpenStreetMap contributors'
    }}).addTo(map);

    function popupHtml(properties) {{
      const entries = Object.entries(properties || {{}})
        .map(([key, value]) => {{
          const rendered = typeof value === 'object' && value !== null
            ? JSON.stringify(value, null, 2)
            : String(value);
          return `<strong>${{key}}</strong>: <pre>${{rendered}}</pre>`;
        }});
      return entries.join('');
    }}

    function makeGeoJsonLayer(collection, style) {{
      return L.geoJSON(collection, {{
        style: feature => {{
          const geometryType = feature.geometry && feature.geometry.type;
          if (geometryType === 'Polygon' || geometryType === 'MultiPolygon') {{
            return {{
              color: style.color,
              weight: style.weight || 2,
              fillColor: style.color,
              fillOpacity: style.fillOpacity ?? 0.18
            }};
          }}
          return {{
            color: style.color,
            weight: style.weight || 2,
            opacity: style.opacity ?? 0.9
          }};
        }},
        pointToLayer: (feature, latlng) => L.circleMarker(latlng, {{
          radius: style.radius || 5,
          color: style.color,
          fillColor: style.color,
          fillOpacity: style.fillOpacity ?? 0.9,
          weight: 1
        }}),
        onEachFeature: (feature, layer) => layer.bindPopup(popupHtml(feature.properties || {{}}))
      }});
    }}

    const overlays = {{}};
    const baseEdges = makeGeoJsonLayer(payload.layers.roadSegments, edgeStyle).addTo(map);
    const baseNodes = makeGeoJsonLayer(payload.layers.roadNodes, nodeStyle).addTo(map);
    overlays.roadSegments = baseEdges;
    overlays.roadNodes = baseNodes;

    for (const [featureType, collection] of Object.entries(payload.layers.segmentFeatures)) {{
      const style = featureStyles[featureType] || {{ color: '#64748b', weight: 2, radius: 5, fillOpacity: 0.16 }};
      overlays[featureType] = makeGeoJsonLayer(collection, style).addTo(map);
    }}

    const layerControl = L.control.layers({{}}, overlays, {{ collapsed: false }}).addTo(map);

    const legend = document.getElementById('legend');
    const legendItems = [
      ['roadSegments', edgeStyle.color],
      ['roadNodes', nodeStyle.color],
      ...Object.entries(featureStyles).filter(([featureType]) => payload.summary.featureCounts[featureType] > 0)
        .map(([featureType, style]) => [featureType, style.color])
    ];
    legend.innerHTML = legendItems.map(([label, color]) => `
      <div class="legend-item">
        <span class="legend-swatch" style="background:${{color}}"></span>
        <span class="legend-label">${{label}}</span>
      </div>
    `).join('');

    const fitLayer = L.featureGroup(Object.values(overlays).filter(Boolean));
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
