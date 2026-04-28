from __future__ import annotations

import html
import json
import os
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

from etl.common import side_graph_loader


ROOT_DIR = Path(__file__).resolve().parents[2]
if load_dotenv is not None:
    load_dotenv(ROOT_DIR / ".env")

ETL_DIR = ROOT_DIR / "etl"
OUTPUT_HTML = ETL_DIR / "subway_elevator_preview.html"
OUTPUT_GEOJSON = ETL_DIR / "subway_elevator_preview.geojson"
KAKAO_JAVASCRIPT_KEY = os.getenv("KAKAO_JAVASCRIPT_KEY", "")

DEFAULT_CENTER_LAT = 35.1633200
DEFAULT_CENTER_LON = 129.1588705
DEFAULT_RADIUS_M = 5000

SEGMENT_STYLES = {
    "CENTERLINE": {"strokeColor": "#111827", "strokeWeight": 3, "strokeOpacity": 0.84},
    "SIDE_LINE": {"strokeColor": "#dc2626", "strokeWeight": 3, "strokeOpacity": 0.84},
    "ROAD_BOUNDARY": {"strokeColor": "#dc2626", "strokeWeight": 4, "strokeOpacity": 0.9},
    "ROAD_BOUNDARY_INNER": {"strokeColor": "#dc2626", "strokeWeight": 3, "strokeOpacity": 0.84},
    "SIDE_WALK": {"strokeColor": "#2563eb", "strokeWeight": 3, "strokeOpacity": 0.9},
    "SIDE_LEFT": {"strokeColor": "#dc2626", "strokeWeight": 3, "strokeOpacity": 0.84},
    "SIDE_RIGHT": {"strokeColor": "#dc2626", "strokeWeight": 3, "strokeOpacity": 0.84},
    "TRANSITION_CONNECTOR": {"strokeColor": "#7c3aed", "strokeWeight": 3, "strokeOpacity": 0.9},
    "GAP_BRIDGE": {"strokeColor": "#f59e0b", "strokeWeight": 3, "strokeOpacity": 0.92},
    "CORNER_BRIDGE": {"strokeColor": "#ea580c", "strokeWeight": 3, "strokeOpacity": 0.94},
    "SAME_SIDE_CORNER_BRIDGE": {"strokeColor": "#f97316", "strokeWeight": 3, "strokeOpacity": 0.94},
    "CROSS_SIDE_CORNER_BRIDGE": {"strokeColor": "#8b5cf6", "strokeWeight": 3, "strokeOpacity": 0.94},
    "CROSSING": {"strokeColor": "#059669", "strokeWeight": 3, "strokeOpacity": 0.9},
    "ELEVATOR_CONNECTOR": {"strokeColor": "#0ea5e9", "strokeWeight": 3, "strokeOpacity": 0.9},
}
NODE_MARKER_STYLE = {"color": "#111827", "fillColor": "#111827"}


def build_payload(
    *,
    center_lat: float = DEFAULT_CENTER_LAT,
    center_lon: float = DEFAULT_CENTER_LON,
    radius_m: int = DEFAULT_RADIUS_M,
) -> dict[str, Any]:
    payload, _, _ = side_graph_loader.generate_preview_dataset(
        center_lat=center_lat,
        center_lon=center_lon,
        radius_m=radius_m,
    )
    payload["meta"]["outputHtml"] = str(OUTPUT_HTML)
    payload["meta"]["outputGeojson"] = str(OUTPUT_GEOJSON)
    return payload


def render_html(payload: dict[str, Any]) -> str:
    meta = payload["meta"]
    summary = payload["summary"]
    payload_json = json.dumps(payload, ensure_ascii=False)
    segment_styles_json = json.dumps(SEGMENT_STYLES, ensure_ascii=False)
    node_marker_style_json = json.dumps(NODE_MARKER_STYLE, ensure_ascii=False)
    kakao_javascript_key = html.escape(KAKAO_JAVASCRIPT_KEY)
    type_text = ", ".join(f"{item['name']} {item['count']}" for item in summary["segmentTypeCounts"]) or "-"
    summary_text = html.escape(
        f"center ({meta['centerLat']:.4f}, {meta['centerLon']:.4f}), radius {meta['radiusMeter']}m, "
        f"nodes {summary['nodeCount']}, segments {summary['segmentCount']}"
    )
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(meta['title'])}</title>
  <style>
    html, body, #map {{
      width: 100%;
      height: 100%;
      margin: 0;
      background: linear-gradient(180deg, #fff7ed 0%, #fffbeb 100%);
      font: 13px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: #0f172a;
    }}
    .map-shell {{
      position: relative;
      width: 100%;
      height: 100%;
    }}
    .panel {{
      position: absolute;
      z-index: 700;
      top: 12px;
      left: 12px;
      width: min(620px, calc(100vw - 24px));
      padding: 14px 16px;
      background: rgba(255, 255, 255, 0.95);
      border: 1px solid #fed7aa;
      box-shadow: 0 10px 28px rgba(15, 23, 42, 0.14);
      backdrop-filter: blur(10px);
    }}
    .panel h1 {{
      margin: 0 0 8px;
      font-size: 16px;
    }}
    .panel p {{
      margin: 0 0 8px;
      color: #334155;
    }}
    .warning {{
      padding: 8px 10px;
      background: #eff6ff;
      border: 1px solid #93c5fd;
      color: #1d4ed8;
      font-size: 12px;
    }}
    .legend {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
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
    .legend-line {{
      width: 18px;
      height: 0;
      flex: 0 0 auto;
      border-top-width: 3px;
      border-top-style: solid;
    }}
    .legend-label {{
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .info-window {{
      min-width: 260px;
      padding: 10px 12px;
      font: 12px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: #0f172a;
    }}
    .info-window strong {{
      display: inline-block;
      min-width: 120px;
      color: #334155;
    }}
    .info-window pre {{
      white-space: pre-wrap;
      margin: 0 0 6px;
      font-size: 11px;
    }}
  </style>
</head>
<body>
  <section class="map-shell">
    <div id="map"></div>
    <div class="panel">
      <h1>{html.escape(meta['title'])}</h1>
      <p>{summary_text}</p>
      <p>Types: {html.escape(type_text)}</p>
      <p>Transition connectors: {summary['transitionConnectorCount']}, gap bridges: {summary.get('gapBridgeCount', 0)}, corner bridges: {summary.get('cornerBridgeCount', 0)}, elevator connectors: {summary['elevatorConnectorCount']}</p>
      <p>SHP: {html.escape(Path(meta['sourceShp']).name)}</p>
      <p id="host-warning" class="warning" hidden></p>
      <div class="legend">
        <div class="legend-item"><span class="legend-swatch" style="background:#111827"></span><span class="legend-label">road node</span></div>
        <div class="legend-item"><span class="legend-line" style="border-top-color:#111827"></span><span class="legend-label">centerline segment</span></div>
        <div class="legend-item"><span class="legend-line" style="border-top-color:#dc2626"></span><span class="legend-label">side line segment</span></div>
        <div class="legend-item"><span class="legend-line" style="border-top-color:#dc2626"></span><span class="legend-label">road boundary</span></div>
        <div class="legend-item"><span class="legend-line" style="border-top-color:#2563eb"></span><span class="legend-label">side walk / crosswalk segment</span></div>
        <div class="legend-item"><span class="legend-line" style="border-top-color:#7c3aed"></span><span class="legend-label">transition connector</span></div>
        <div class="legend-item"><span class="legend-line" style="border-top-color:#f59e0b"></span><span class="legend-label">gap bridge</span></div>
        <div class="legend-item"><span class="legend-line" style="border-top-color:#ea580c"></span><span class="legend-label">corner bridge (legacy)</span></div>
        <div class="legend-item"><span class="legend-line" style="border-top-color:#f97316"></span><span class="legend-label">same-side corner bridge</span></div>
        <div class="legend-item"><span class="legend-line" style="border-top-color:#8b5cf6"></span><span class="legend-label">cross-side corner bridge</span></div>
        <div class="legend-item"><span class="legend-line" style="border-top-color:#0ea5e9"></span><span class="legend-label">elevator connector</span></div>
      </div>
    </div>
  </section>
  <script src="https://dapi.kakao.com/v2/maps/sdk.js?appkey={kakao_javascript_key}&autoload=false" onerror="window.__kakaoSdkLoadFailed = true"></script>
  <script>
    const payload = {payload_json};
    const segmentStyles = {segment_styles_json};
    const nodeMarkerStyle = {node_marker_style_json};
    const hostWarning = document.getElementById("host-warning");

    function setWarning(message) {{
      hostWarning.hidden = false;
      hostWarning.innerHTML = message;
    }}

    function popupHtml(properties) {{
      return `<div class="info-window">${{Object.entries(properties || {{}})
        .map(([key, value]) => `<div><strong>${{key}}</strong><pre>${{String(value ?? "-")}}</pre></div>`)
        .join("")}}</div>`;
    }}

    function pointMarkerImage(style, size) {{
      const markerSvg = `data:image/svg+xml;charset=UTF-8,${{encodeURIComponent(`
        <svg xmlns="http://www.w3.org/2000/svg" width="${{size}}" height="${{size}}" viewBox="0 0 ${{size}} ${{size}}">
          <circle cx="${{size / 2}}" cy="${{size / 2}}" r="${{size / 2 - 1.2}}" fill="${{style.fillColor}}" stroke="${{style.color}}" stroke-width="1.2"/>
        </svg>
      `)}}`;
      return new kakao.maps.MarkerImage(
        markerSvg,
        new kakao.maps.Size(size, size),
        {{ offset: new kakao.maps.Point(size / 2, size / 2) }}
      );
    }}

    if (location.protocol === "file:") {{
      setWarning(`현재 <code>file://</code> 경로입니다. 카카오 SDK 안정성을 위해 <a href="${{payload.meta.localhostUrl}}">${{payload.meta.localhostUrl}}</a> 로 여는 편이 안전합니다.`);
    }}

    function initializeMap() {{
      const map = new kakao.maps.Map(document.getElementById("map"), {{
        center: new kakao.maps.LatLng(payload.meta.centerLat, payload.meta.centerLon),
        level: 5
      }});
      const bounds = new kakao.maps.LatLngBounds();
      const infoWindow = new kakao.maps.InfoWindow({{ removable: true }});

      function extendBounds(coords) {{
        coords.forEach(([lng, lat]) => bounds.extend(new kakao.maps.LatLng(lat, lng)));
      }}

      function addPointFeature(feature, style, size) {{
        const [lng, lat] = feature.geometry.coordinates;
        const position = new kakao.maps.LatLng(lat, lng);
        bounds.extend(position);
        const marker = new kakao.maps.Marker({{
          map,
          position,
          image: pointMarkerImage(style, size)
        }});
        kakao.maps.event.addListener(marker, "click", () => {{
          infoWindow.setContent(popupHtml(feature.properties));
          infoWindow.setPosition(position);
          infoWindow.open(map, marker);
        }});
      }}

      function addLineFeature(feature) {{
        const style = segmentStyles[feature.properties.segmentType] || segmentStyles.CENTERLINE;
        const coords = feature.geometry.coordinates || [];
        extendBounds(coords);
        const path = coords.map(([lng, lat]) => new kakao.maps.LatLng(lat, lng));
        const line = new kakao.maps.Polyline({{
          map,
          path,
          strokeWeight: style.strokeWeight,
          strokeColor: style.strokeColor,
          strokeOpacity: style.strokeOpacity,
          strokeStyle: "solid"
        }});
        kakao.maps.event.addListener(line, "click", (mouseEvent) => {{
          infoWindow.setContent(popupHtml(feature.properties));
          infoWindow.setPosition(mouseEvent.latLng);
          infoWindow.open(map);
        }});
      }}

      payload.layers.roadSegments.features.forEach((feature) => addLineFeature(feature));
      payload.layers.roadNodes.features.forEach((feature) => addPointFeature(feature, nodeMarkerStyle, 8));

      kakao.maps.event.addListener(map, "click", () => infoWindow.close());
      map.setBounds(bounds);
    }}

    function renderKakaoMap() {{
      if (window.__kakaoSdkLoadFailed || !window.kakao || !window.kakao.maps || !window.kakao.maps.load) {{
        setWarning(`Kakao Maps SDK를 불러오지 못했습니다. <a href="${{payload.meta.localhostUrl}}">${{payload.meta.localhostUrl}}</a> 로 다시 열어보세요.`);
        return;
      }}
      kakao.maps.load(initializeMap);
    }}

    renderKakaoMap();
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
