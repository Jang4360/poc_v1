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
ELEVATOR_CSV = RAW_DIR / "subway_station_elevators_erd_ready.csv"
OUTPUT_HTML = ETL_DIR / "haeundae_subway_elevator_preview.html"
OUTPUT_GEOJSON = ETL_DIR / "haeundae_subway_elevator_preview.geojson"
KAKAO_JAVASCRIPT_KEY = os.getenv("KAKAO_JAVASCRIPT_KEY", "")

DEFAULT_CENTER_LAT = 35.1631
DEFAULT_CENTER_LON = 129.1635
DEFAULT_RADIUS_M = 5000

ELEVATOR_POINT_STYLE = {
    "color": "#16a34a",
    "weight": 1,
    "fillColor": "#22c55e",
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


def _parse_point_wkt(value: str) -> tuple[float, float] | None:
    text = (value or "").strip()
    if not text.startswith("POINT(") or not text.endswith(")"):
        return None
    coords = text[6:-1].strip().split()
    if len(coords) != 2:
        return None
    lon, lat = float(coords[0]), float(coords[1])
    return lon, lat


def build_payload(
    *,
    center_lat: float = DEFAULT_CENTER_LAT,
    center_lon: float = DEFAULT_CENTER_LON,
    radius_m: int = DEFAULT_RADIUS_M,
) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    skipped_no_coordinate = 0
    station_counts: dict[str, int] = {}

    with ELEVATOR_CSV.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            point_value = (row.get("point") or "").strip()
            parsed = _parse_point_wkt(point_value)
            if parsed is None:
                skipped_no_coordinate += 1
                continue

            lon, lat = parsed
            distance_meter = _haversine_meter(center_lat, center_lon, lat, lon)
            if distance_meter > radius_m:
                continue

            station_name = (row.get("stationName") or "").strip() or "Unknown"
            station_counts[station_name] = station_counts.get(station_name, 0) + 1
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "source": "SUBWAY_ELEVATOR",
                        "elevatorId": (row.get("elevatorId") or "").strip(),
                        "stationId": (row.get("stationId") or "").strip(),
                        "stationName": station_name,
                        "lineName": (row.get("lineName") or "").strip(),
                        "entranceNo": (row.get("entranceNo") or "").strip(),
                        "distanceMeter": round(distance_meter, 1),
                    },
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                }
            )

    features.sort(
        key=lambda feature: (
            feature["properties"]["distanceMeter"],
            feature["properties"]["stationName"],
            feature["properties"]["elevatorId"],
        )
    )
    top_stations = [
        {"name": name, "count": count}
        for name, count in sorted(station_counts.items(), key=lambda item: (-item[1], item[0]))
    ]

    return {
        "meta": {
            "title": "Haeundae Subway Elevator Preview",
            "centerLat": center_lat,
            "centerLon": center_lon,
            "radiusMeter": radius_m,
            "elevatorCsv": str(ELEVATOR_CSV),
            "localhostUrl": f"http://127.0.0.1:3000/etl/{OUTPUT_HTML.name}",
            "outputHtml": str(OUTPUT_HTML),
            "outputGeojson": str(OUTPUT_GEOJSON),
        },
        "summary": {
            "elevatorCount": len(features),
            "skippedNoCoordinate": skipped_no_coordinate,
            "stationCounts": top_stations,
        },
        "layers": {
            "subwayElevators": _feature_collection(features),
        },
    }


def render_html(payload: dict[str, Any]) -> str:
    meta = payload["meta"]
    summary = payload["summary"]
    payload_json = json.dumps(payload, ensure_ascii=False)
    elevator_style_json = json.dumps(ELEVATOR_POINT_STYLE, ensure_ascii=False)
    kakao_javascript_key = html.escape(KAKAO_JAVASCRIPT_KEY)
    station_text = ", ".join(
        f"{item['name']} {item['count']}" for item in summary["stationCounts"][:8]
    ) or "-"
    summary_text = html.escape(
        f"center ({meta['centerLat']:.4f}, {meta['centerLon']:.4f}), radius {meta['radiusMeter']}m, "
        f"elevators {summary['elevatorCount']}, skipped(no coordinate) {summary['skippedNoCoordinate']}"
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
      <p>Stations: {html.escape(station_text)}</p>
      <p>CSV: {html.escape(Path(meta['elevatorCsv']).name)}</p>
      <p id="host-warning" class="warning" hidden></p>
      <div class="legend">
        <div class="legend-item">
          <span class="legend-swatch" style="background:{ELEVATOR_POINT_STYLE['fillColor']}"></span>
          <span class="legend-label">Subway elevator</span>
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
    const elevatorStyle = {elevator_style_json};
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

      function addMarkerFeature(feature) {{
        const [lng, lat] = feature.geometry.coordinates;
        const position = new kakao.maps.LatLng(lat, lng);
        extendBounds(lng, lat);
        const marker = new kakao.maps.Marker({{
          map,
          position,
          image: markerImage(elevatorStyle)
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

      payload.layers.subwayElevators.features.forEach(addMarkerFeature);

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
