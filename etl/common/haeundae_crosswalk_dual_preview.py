from __future__ import annotations

import csv
import html
import json
import math
import os
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is installed by etl/requirements.txt
    load_dotenv = None


ROOT_DIR = Path(__file__).resolve().parents[2]
if load_dotenv is not None:
    load_dotenv(ROOT_DIR / ".env")

ETL_DIR = ROOT_DIR / "etl"
RAW_DIR = ETL_DIR / "raw"
TMAP_CSV = RAW_DIR / "haeundae_tmap_crosswalk_geometry_points_v1_20260424_2000calls.csv"
BUSAN_CSV = RAW_DIR / "부산광역시 횡단보도 위치 정보_20250423.csv"
OUTPUT_HTML = ETL_DIR / "haeundae_crosswalk_dual_preview.html"
OUTPUT_GEOJSON = ETL_DIR / "haeundae_crosswalk_dual_preview.geojson"
KAKAO_JAVASCRIPT_KEY = os.getenv("KAKAO_JAVASCRIPT_KEY", "")

DEFAULT_CENTER_LAT = 35.1631
DEFAULT_CENTER_LON = 129.1635
DEFAULT_RADIUS_M = 5000

TMAP_POINT_STYLE = {
    "color": "#1d4ed8",
    "weight": 1,
    "fillColor": "#2563eb",
    "fillOpacity": 0.92,
}
BUSAN_POINT_STYLE = {
    "color": "#c2410c",
    "weight": 1,
    "fillColor": "#f97316",
    "fillOpacity": 0.92,
}


def _feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": features}


def _haversine_meter(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius = 6_371_000
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(d_lon / 2) ** 2
    )
    return earth_radius * 2 * math.asin(math.sqrt(a))


def _read_tmap_points(*, center_lat: float, center_lon: float, radius_m: int) -> tuple[list[dict[str, Any]], int]:
    features: list[dict[str, Any]] = []
    skipped = 0
    with TMAP_CSV.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            lat_text = (row.get("lat") or "").strip()
            lon_text = (row.get("lng") or "").strip()
            if not lat_text or not lon_text:
                skipped += 1
                continue
            lat = float(lat_text)
            lon = float(lon_text)
            distance_meter = _haversine_meter(center_lat, center_lon, lat, lon)
            if distance_meter > radius_m:
                continue
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "source": "TMAP",
                        "pointRole": (row.get("point_role") or "").strip(),
                        "observationCount": int((row.get("observation_count") or "0").strip() or 0),
                        "geometryType": (row.get("geometry_type") or "").strip(),
                        "turnTypeCode": (row.get("turn_type_code") or "").strip(),
                        "turnTypeNameKo": (row.get("turn_type_name_ko") or "").strip(),
                        "facilityTypeCode": (row.get("facility_type_code") or "").strip(),
                        "facilityTypeNameKo": (row.get("facility_type_name_ko") or "").strip(),
                        "roadTypeCode": (row.get("road_type_code") or "").strip(),
                        "description": (row.get("description") or "").strip(),
                        "name": (row.get("name") or "").strip(),
                        "caseIds": (row.get("case_ids") or "").strip(),
                        "requestIds": (row.get("request_ids") or "").strip(),
                        "vertexIndex": (row.get("vertex_index") or "").strip(),
                        "distanceMeter": round(distance_meter, 1),
                    },
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                }
            )
    features.sort(key=lambda feature: feature["properties"]["distanceMeter"])
    return features, skipped


def _read_busan_points(*, center_lat: float, center_lon: float, radius_m: int) -> tuple[list[dict[str, Any]], int]:
    features: list[dict[str, Any]] = []
    skipped = 0
    with BUSAN_CSV.open("r", encoding="cp949", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            lat_text = (row.get("위도") or "").strip()
            lon_text = (row.get("경도") or "").strip()
            if not lat_text or not lon_text:
                skipped += 1
                continue
            lat = float(lat_text)
            lon = float(lon_text)
            distance_meter = _haversine_meter(center_lat, center_lon, lat, lon)
            if distance_meter > radius_m:
                continue
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "source": "BUSAN_OPEN_DATA",
                        "seq": (row.get("순번") or "").strip(),
                        "gu": (row.get("행정구역(구)") or "").strip(),
                        "dong": (row.get("행정구역(동)") or "").strip(),
                        "lot": (row.get("지번") or "").strip(),
                        "intersection": (row.get("교차로") or "").strip(),
                        "signal": (row.get("신호등존재유무") or "").strip(),
                        "widthMeter": (row.get("가로길이") or "").strip(),
                        "heightMeter": (row.get("세로길이") or "").strip(),
                        "areaSqm": (row.get("면적") or "").strip(),
                        "distanceMeter": round(distance_meter, 1),
                    },
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                }
            )
    features.sort(key=lambda feature: feature["properties"]["distanceMeter"])
    return features, skipped


def build_payload(
    *,
    center_lat: float = DEFAULT_CENTER_LAT,
    center_lon: float = DEFAULT_CENTER_LON,
    radius_m: int = DEFAULT_RADIUS_M,
) -> dict[str, Any]:
    tmap_features, tmap_skipped = _read_tmap_points(center_lat=center_lat, center_lon=center_lon, radius_m=radius_m)
    busan_features, busan_skipped = _read_busan_points(center_lat=center_lat, center_lon=center_lon, radius_m=radius_m)
    return {
        "meta": {
            "title": "Haeundae Crosswalk Dual Preview",
            "centerLat": center_lat,
            "centerLon": center_lon,
            "radiusMeter": radius_m,
            "tmapCsv": str(TMAP_CSV),
            "busanCsv": str(BUSAN_CSV),
            "localhostUrl": f"http://127.0.0.1:3000/etl/{OUTPUT_HTML.name}",
            "outputHtml": str(OUTPUT_HTML),
            "outputGeojson": str(OUTPUT_GEOJSON),
        },
        "summary": {
            "tmapCount": len(tmap_features),
            "busanCount": len(busan_features),
            "tmapSkippedNoCoordinate": tmap_skipped,
            "busanSkippedNoCoordinate": busan_skipped,
        },
        "layers": {
            "tmapCrosswalks": _feature_collection(tmap_features),
            "busanCrosswalks": _feature_collection(busan_features),
        },
    }


def render_html(payload: dict[str, Any]) -> str:
    meta = payload["meta"]
    summary = payload["summary"]
    payload_json = json.dumps(payload, ensure_ascii=False)
    tmap_style_json = json.dumps(TMAP_POINT_STYLE, ensure_ascii=False)
    busan_style_json = json.dumps(BUSAN_POINT_STYLE, ensure_ascii=False)
    kakao_javascript_key = html.escape(KAKAO_JAVASCRIPT_KEY)
    summary_text = html.escape(
        f"center ({meta['centerLat']:.4f}, {meta['centerLon']:.4f}), radius {meta['radiusMeter']}m, "
        f"Tmap {summary['tmapCount']} / skipped {summary['tmapSkippedNoCoordinate']}, "
        f"Busan open data {summary['busanCount']} / skipped {summary['busanSkippedNoCoordinate']}"
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
      background: #f8fafc;
      font: 13px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
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
      width: min(470px, calc(100vw - 24px));
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
    .warning {{
      padding: 8px 10px;
      background: #eff6ff;
      border: 1px solid #93c5fd;
      color: #1d4ed8;
      font-size: 12px;
    }}
    .legend {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
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
      width: 16px;
      height: 0;
      border-top: 2px dashed #2563eb;
      flex: 0 0 auto;
    }}
    .legend-label {{
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .info-window {{
      min-width: 240px;
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
      <p>Tmap CSV: {html.escape(Path(meta['tmapCsv']).name)}</p>
      <p>Busan CSV: {html.escape(Path(meta['busanCsv']).name)}</p>
      <p id="host-warning" class="warning" hidden></p>
      <div class="legend">
        <div class="legend-item">
          <span class="legend-swatch" style="background:{TMAP_POINT_STYLE['fillColor']}"></span>
          <span class="legend-label">Tmap crosswalk (blue)</span>
        </div>
        <div class="legend-item">
          <span class="legend-swatch" style="background:{BUSAN_POINT_STYLE['fillColor']}"></span>
          <span class="legend-label">Busan open data crosswalk (orange)</span>
        </div>
        <div class="legend-item">
          <span class="legend-swatch" style="background:#0f172a"></span>
          <span class="legend-label">Haeundae Station center</span>
        </div>
        <div class="legend-item">
          <span class="legend-line"></span>
          <span class="legend-label">5km radius</span>
        </div>
      </div>
    </div>
  </section>
  <script src="https://dapi.kakao.com/v2/maps/sdk.js?appkey={kakao_javascript_key}&libraries=services"></script>
  <script>
    const payload = {payload_json};
    const tmapStyle = {tmap_style_json};
    const busanStyle = {busan_style_json};
    const hostWarning = document.getElementById("host-warning");

    function setWarning(message) {{
      hostWarning.hidden = false;
      hostWarning.innerHTML = message;
    }}

    if (location.protocol === "file:") {{
      setWarning(`현재 <code>file://</code> 경로로 열려 있어 카카오 SDK가 차단될 수 있습니다. <a href="${{payload.meta.localhostUrl}}">${{payload.meta.localhostUrl}}</a> 로 여는 편이 안정적입니다.`);
    }}

    if (!window.kakao || !window.kakao.maps) {{
      setWarning(`Kakao Maps SDK를 불러오지 못했습니다. <a href="${{payload.meta.localhostUrl}}">${{payload.meta.localhostUrl}}</a> 로 다시 열어보세요.`);
    }} else {{
      const map = new kakao.maps.Map(document.getElementById("map"), {{
        center: new kakao.maps.LatLng(payload.meta.centerLat, payload.meta.centerLon),
        level: 5
      }});
      const bounds = new kakao.maps.LatLngBounds();
      const infoWindow = new kakao.maps.InfoWindow({{ removable: true }});

      function markerImage(style) {{
        const markerSvg = `data:image/svg+xml;charset=UTF-8,${{encodeURIComponent(`
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 14 14">
            <circle cx="7" cy="7" r="5" fill="${{style.fillColor}}" stroke="${{style.color}}" stroke-width="1"/>
          </svg>
        `)}}`;
        return new kakao.maps.MarkerImage(
          markerSvg,
          new kakao.maps.Size(14, 14),
          {{ offset: new kakao.maps.Point(7, 7) }}
        );
      }}

      function extendBounds(lng, lat) {{
        bounds.extend(new kakao.maps.LatLng(lat, lng));
      }}

      function popupHtml(properties) {{
        return `<div class="info-window">${{Object.entries(properties || {{}})
          .map(([key, value]) => `<div><strong>${{key}}</strong><pre>${{String(value || "-")}}</pre></div>`)
          .join("")}}</div>`;
      }}

      function openInfo(position, properties) {{
        infoWindow.setContent(popupHtml(properties));
        infoWindow.setPosition(position);
        infoWindow.open(map);
      }}

      function openRoadviewTab(feature) {{
        const [lng, lat] = feature.geometry.coordinates;
        const roadviewUrl = `https://map.kakao.com/link/roadview/${{lat}},${{lng}}`;
        window.open(roadviewUrl, "_blank", "noopener,noreferrer");
      }}

      function addMarkerFeature(feature, style) {{
        const [lng, lat] = feature.geometry.coordinates;
        const position = new kakao.maps.LatLng(lat, lng);
        extendBounds(lng, lat);
        const marker = new kakao.maps.Marker({{
          map,
          position,
          image: markerImage(style)
        }});
        kakao.maps.event.addListener(marker, "click", () => {{
          openInfo(position, {{
            ...(feature.properties || {{}}),
            roadviewAction: "새 탭에서 카카오맵 로드뷰 열기"
          }});
          openRoadviewTab(feature);
        }});
      }}

      const centerPosition = new kakao.maps.LatLng(payload.meta.centerLat, payload.meta.centerLon);
      extendBounds(payload.meta.centerLon, payload.meta.centerLat);
      const centerMarker = new kakao.maps.Marker({{
        map,
        position: centerPosition
      }});
      kakao.maps.event.addListener(centerMarker, "click", () => {{
        openInfo(centerPosition, {{ title: "Haeundae Station center" }});
      }});

      new kakao.maps.Circle({{
        map,
        center: centerPosition,
        radius: payload.meta.radiusMeter,
        strokeWeight: 2,
        strokeColor: "#2563eb",
        strokeOpacity: 0.8,
        strokeStyle: "dash",
        fillColor: "#93c5fd",
        fillOpacity: 0.05
      }});

      payload.layers.tmapCrosswalks.features.forEach((feature) => addMarkerFeature(feature, tmapStyle));
      payload.layers.busanCrosswalks.features.forEach((feature) => addMarkerFeature(feature, busanStyle));

      kakao.maps.event.addListener(map, "click", () => infoWindow.close());
      map.setBounds(bounds);
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
