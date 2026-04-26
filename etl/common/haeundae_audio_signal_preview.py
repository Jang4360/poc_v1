from __future__ import annotations

import csv
import html
import json
import math
import os
from pathlib import Path
from typing import Any

import requests

from etl.common.db import connect

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is installed by etl/requirements.txt
    load_dotenv = None


ROOT_DIR = Path(__file__).resolve().parents[2]
if load_dotenv is not None:
    load_dotenv(ROOT_DIR / ".env")

ETL_DIR = ROOT_DIR / "etl"
RAW_AUDIO_SIGNALS = ETL_DIR / "raw" / "stg_audio_signals_ready.csv"
OUTPUT_HTML = ETL_DIR / "haeundae_audio_signal_preview.html"
OUTPUT_GEOJSON = ETL_DIR / "haeundae_audio_signal_preview.geojson"
KAKAO_JAVASCRIPT_KEY = os.getenv("KAKAO_JAVASCRIPT_KEY", "")

DEFAULT_CENTER_LAT = 35.1631
DEFAULT_CENTER_LON = 129.1635
DEFAULT_RADIUS_M = 5000
DEFAULT_PAGE_SIZE = 1000

DEFAULT_API_BASE_URL = "https://apis.data.go.kr/6260000/BusanAcstcBcnInfoService"
SERVICE_KEY_ENV = "BUSAN_ACSTC_BCN_SERVICE_KEY_DECODING"

ALL_POLYGON_STYLE = {
    "color": "#2563eb",
    "weight": 1,
    "opacity": 0.45,
    "fillColor": "#93c5fd",
    "fillOpacity": 0.08,
}
MATCHED_POLYGON_STYLE = {
    "color": "#2563eb",
    "weight": 1.5,
    "opacity": 0.9,
    "fillColor": "#60a5fa",
    "fillOpacity": 0.18,
}
AUDIO_SIGNAL_POINT_STYLE = {
    "radius": 5,
    "color": "#c2410c",
    "weight": 1,
    "fillColor": "#f97316",
    "fillOpacity": 0.92,
}


def _feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": features}


def _json_geometry(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return json.loads(value)
    return value


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


def _coerce_items(body: dict[str, Any]) -> list[dict[str, Any]]:
    items = body.get("items", {}).get("item", [])
    if isinstance(items, dict):
        return [items]
    return list(items)


def _load_audio_signal_rows_from_csv(path: Path = RAW_AUDIO_SIGNALS) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            rows.append(
                {
                    "seq": row.get("sourceId", ""),
                    "sigungu": row.get("sigungu", ""),
                    "location": row.get("location", ""),
                    "address": row.get("address", ""),
                    "place": row.get("place", ""),
                    "stat": row.get("stat", ""),
                    "status": row.get("audioSignalState", ""),
                    "ins_company": "",
                    "ins_year": "",
                    "confirm_date": row.get("confirmDate", ""),
                    "lat": row.get("lat", ""),
                    "lng": row.get("lng", ""),
                }
            )
    return rows


def fetch_audio_signal_rows(
    *,
    api_base_url: str | None = None,
    service_key: str | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> list[dict[str, Any]]:
    base_url = (api_base_url or os.getenv("BUSAN_ACSTC_BCN_API_BASE_URL") or DEFAULT_API_BASE_URL).rstrip("/")
    key = service_key or os.getenv(SERVICE_KEY_ENV, "")
    if not key:
        if RAW_AUDIO_SIGNALS.exists():
            return _load_audio_signal_rows_from_csv()
        raise RuntimeError(f"missing service key in env: {SERVICE_KEY_ENV}")

    url = f"{base_url}/getAcstcBcnInfo"
    rows: list[dict[str, Any]] = []
    page_no = 1

    while True:
        response = requests.get(
            url,
            params={
                "ServiceKey": key,
                "pageNo": page_no,
                "numOfRows": page_size,
                "resultType": "json",
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()["response"]
        header = payload["header"]
        if header.get("resultCode") != "00":
            raise RuntimeError(f"acoustic beacon api error: {header}")

        body = payload["body"]
        rows.extend(_coerce_items(body))
        total_count = int(body["totalCount"])
        if len(rows) >= total_count:
            break
        page_no += 1

    return rows


def _match_audio_signal_to_polygons(cur: Any, signal: dict[str, Any]) -> list[dict[str, Any]]:
    cur.execute(
        """
        WITH point_geom AS (
            SELECT ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 4326), 5179) AS geom
        )
        SELECT
            rp."edgeId",
            rp."sourceRowNumber",
            rp."sourceUfid"
        FROM road_segment_filter_polygons rp, point_geom p
        WHERE ST_Covers(rp."geom", p.geom)
        ORDER BY rp."edgeId"
        """,
        (signal["lng"], signal["lat"]),
    )
    return [
        {
            "edgeId": int(edge_id),
            "sourceRowNumber": int(source_row_number),
            "sourceUfid": source_ufid,
        }
        for edge_id, source_row_number, source_ufid in cur.fetchall()
    ]


def build_payload(
    *,
    center_lat: float = DEFAULT_CENTER_LAT,
    center_lon: float = DEFAULT_CENTER_LON,
    radius_m: int = DEFAULT_RADIUS_M,
) -> dict[str, Any]:
    all_rows = fetch_audio_signal_rows()
    data_source = (
        os.getenv("BUSAN_ACSTC_BCN_API_BASE_URL", DEFAULT_API_BASE_URL)
        if os.getenv(SERVICE_KEY_ENV, "")
        else str(RAW_AUDIO_SIGNALS)
    )
    candidate_signals: list[dict[str, Any]] = []
    skipped_no_coordinate = 0
    district_counts: dict[str, int] = {}

    for row in all_rows:
        lat_text = str(row.get("lat") or "").strip()
        lon_text = str(row.get("lng") or "").strip()
        if not lat_text or not lon_text:
            skipped_no_coordinate += 1
            continue

        lat = float(lat_text)
        lon = float(lon_text)
        distance_meter = _haversine_meter(center_lat, center_lon, lat, lon)
        if distance_meter > radius_m:
            continue

        district = str(row.get("sigungu") or "").strip() or "알 수 없음"
        district_counts[district] = district_counts.get(district, 0) + 1
        candidate_signals.append(
            {
                "seq": str(row.get("seq") or "").strip(),
                "sigungu": district,
                "location": str(row.get("location") or "").strip(),
                "address": str(row.get("address") or "").strip(),
                "place": str(row.get("place") or "").strip(),
                "stat": str(row.get("stat") or "").strip(),
                "status": str(row.get("status") or "").strip(),
                "insCompany": str(row.get("ins_company") or "").strip(),
                "insYear": str(row.get("ins_year") or "").strip(),
                "confirmDate": str(row.get("confirm_date") or "").strip(),
                "lat": lat,
                "lng": lon,
                "distanceMeter": round(distance_meter, 1),
            }
        )

    matched_polygon_by_edge: dict[int, int] = {}
    audio_signal_features = [
        {
            "type": "Feature",
            "properties": {
                **signal,
                "matchedPolygonCount": 0,
                "matchedEdgeIds": [],
            },
            "geometry": {"type": "Point", "coordinates": [signal["lng"], signal["lat"]]},
        }
        for signal in candidate_signals
    ]
    matched_signal_features: list[dict[str, Any]] = []
    polygon_features: list[dict[str, Any]] = []
    db_error = ""

    try:
        with connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH center AS (
                        SELECT ST_SetSRID(ST_MakePoint(%s, %s), 4326) AS geom
                    )
                    SELECT
                        rp."edgeId",
                        rp."sourceRowNumber",
                        rp."sourceUfid",
                        rp."roadWidthMeter",
                        rp."bufferHalfWidthMeter",
                        ST_AsGeoJSON(ST_Transform(rp."geom", 4326))
                    FROM road_segment_filter_polygons rp, center c
                    WHERE ST_DWithin(ST_Transform(rp."geom", 4326)::geography, c.geom::geography, %s)
                    ORDER BY rp."edgeId"
                    """,
                    (center_lon, center_lat, radius_m),
                )
                polygon_features = [
                    {
                        "type": "Feature",
                        "properties": {
                            "edgeId": int(edge_id),
                            "sourceRowNumber": int(source_row_number),
                            "sourceUfid": source_ufid,
                            "roadWidthMeter": float(road_width_meter),
                            "bufferHalfWidthMeter": float(buffer_half_width_meter),
                            "hasMatchedAudioSignal": False,
                            "matchedAudioSignalCount": 0,
                        },
                        "geometry": _json_geometry(geometry),
                    }
                    for edge_id, source_row_number, source_ufid, road_width_meter, buffer_half_width_meter, geometry in cur.fetchall()
                ]

                for signal, signal_feature in zip(candidate_signals, audio_signal_features):
                    matched_polygons = _match_audio_signal_to_polygons(cur, signal)
                    if not matched_polygons:
                        continue

                    matched_edge_ids = [item["edgeId"] for item in matched_polygons]
                    for edge_id in matched_edge_ids:
                        matched_polygon_by_edge[edge_id] = matched_polygon_by_edge.get(edge_id, 0) + 1

                    signal_feature["properties"]["matchedPolygonCount"] = len(matched_polygons)
                    signal_feature["properties"]["matchedEdgeIds"] = matched_edge_ids
                    matched_signal_features.append(signal_feature)
    except Exception as exc:
        db_error = str(exc).splitlines()[0]

    matched_polygon_features = []
    for feature in polygon_features:
        edge_id = feature["properties"]["edgeId"]
        matched_count = matched_polygon_by_edge.get(edge_id, 0)
        if matched_count:
            feature["properties"]["hasMatchedAudioSignal"] = True
            feature["properties"]["matchedAudioSignalCount"] = matched_count
            matched_polygon_features.append(feature)

    matched_signal_features.sort(
        key=lambda feature: (
            feature["properties"]["distanceMeter"],
            feature["properties"]["seq"],
        )
    )
    audio_signal_features.sort(
        key=lambda feature: (
            feature["properties"]["distanceMeter"],
            feature["properties"]["seq"],
        )
    )
    top_districts = [
        {"name": name, "count": count}
        for name, count in sorted(district_counts.items(), key=lambda item: (-item[1], item[0]))
    ]

    return {
        "meta": {
            "title": "Haeundae Audio Signal Polygon Preview",
            "centerLat": center_lat,
            "centerLon": center_lon,
            "radiusMeter": radius_m,
            "apiBaseUrl": os.getenv("BUSAN_ACSTC_BCN_API_BASE_URL", DEFAULT_API_BASE_URL),
            "dataSource": data_source,
            "dbError": db_error,
            "localhostUrl": f"http://127.0.0.1:3000/etl/{OUTPUT_HTML.name}",
            "outputHtml": str(OUTPUT_HTML),
            "outputGeojson": str(OUTPUT_GEOJSON),
        },
        "summary": {
            "totalFetched": len(all_rows),
            "audioSignalCandidates": len(candidate_signals),
            "audioSignalMarkers": len(audio_signal_features),
            "audioSignalsMatched": len(matched_signal_features),
            "filterPolygons": len(polygon_features),
            "matchedPolygons": len(matched_polygon_features),
            "skippedNoCoordinate": skipped_no_coordinate,
            "districtCounts": top_districts,
        },
        "layers": {
            "filterPolygons": _feature_collection(polygon_features),
            "matchedPolygons": _feature_collection(matched_polygon_features),
            "audioSignals": _feature_collection(audio_signal_features),
        },
    }


def render_html(payload: dict[str, Any]) -> str:
    meta = payload["meta"]
    summary = payload["summary"]
    summary_text = html.escape(
        f"center ({meta['centerLat']:.4f}, {meta['centerLon']:.4f}), radius {meta['radiusMeter']}m, "
        f"polygons {summary['filterPolygons']}, matched polygons {summary['matchedPolygons']}, "
        f"audio signal markers {summary.get('audioSignalMarkers', summary['audioSignalCandidates'])} / candidates {summary['audioSignalCandidates']}, "
        f"matched {summary['audioSignalsMatched']}, "
        f"skipped(no coordinate) {summary['skippedNoCoordinate']}"
    )
    top_districts_text = ", ".join(
        f"{item['name']} {item['count']}" for item in summary["districtCounts"][:8]
    ) or "-"
    payload_json = json.dumps(payload, ensure_ascii=False)
    all_polygon_style_json = json.dumps(ALL_POLYGON_STYLE, ensure_ascii=False)
    matched_polygon_style_json = json.dumps(MATCHED_POLYGON_STYLE, ensure_ascii=False)
    audio_signal_style_json = json.dumps(AUDIO_SIGNAL_POINT_STYLE, ensure_ascii=False)
    kakao_javascript_key = html.escape(KAKAO_JAVASCRIPT_KEY)
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(meta['title'])}</title>
  <style>
    html, body {{
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
      min-width: 0;
      min-height: 0;
    }}
    #map {{
      width: 100%;
      height: 100%;
    }}
    .panel {{
      position: absolute;
      z-index: 700;
      top: 12px;
      left: 12px;
      width: min(460px, calc(100vw - 24px));
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
      min-width: 220px;
      padding: 10px 12px;
      font: 12px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: #0f172a;
    }}
    .info-window strong {{
      display: inline-block;
      min-width: 126px;
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
      <p>Districts: {html.escape(top_districts_text)}</p>
      <p>Data source: {html.escape(meta.get('dataSource', meta['apiBaseUrl']))}</p>
      <p>Source API: {html.escape(meta['apiBaseUrl'])}</p>
      {f'<p>DB matching skipped: {html.escape(meta["dbError"])}</p>' if meta.get("dbError") else ""}
      <p id="host-warning" class="warning" hidden></p>
      <div class="legend">
        <div class="legend-item">
          <span class="legend-swatch" style="background:{ALL_POLYGON_STYLE['fillColor']}"></span>
          <span class="legend-label">All filter polygons</span>
        </div>
        <div class="legend-item">
          <span class="legend-swatch" style="background:{MATCHED_POLYGON_STYLE['fillColor']}"></span>
          <span class="legend-label">Polygons containing audio signals</span>
        </div>
        <div class="legend-item">
          <span class="legend-swatch" style="background:{AUDIO_SIGNAL_POINT_STYLE['fillColor']}"></span>
          <span class="legend-label">Audio signal marker</span>
        </div>
        <div class="legend-item">
          <span class="legend-line"></span>
          <span class="legend-label">5km radius</span>
        </div>
      </div>
    </div>
  </section>
  <script>
    if (location.protocol === "http:" && location.hostname === "127.0.0.1" && location.port && location.port !== "3000") {{
      location.replace("{html.escape(meta['localhostUrl'])}");
    }}
  </script>
  <script src="https://dapi.kakao.com/v2/maps/sdk.js?appkey={kakao_javascript_key}&libraries=services"></script>
  <script>
    const payload = {payload_json};
    const allPolygonStyle = {all_polygon_style_json};
    const matchedPolygonStyle = {matched_polygon_style_json};
    const audioSignalStyle = {audio_signal_style_json};
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
        level: 4
      }});
      const bounds = new kakao.maps.LatLngBounds();
      const infoWindow = new kakao.maps.InfoWindow({{ removable: true }});
      const markerSvg = `data:image/svg+xml;charset=UTF-8,${{encodeURIComponent(`
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 14 14">
          <circle cx="7" cy="7" r="5" fill="${{audioSignalStyle.fillColor}}" stroke="${{audioSignalStyle.color}}" stroke-width="1"/>
        </svg>
      `)}}`;
      const markerImage = new kakao.maps.MarkerImage(
        markerSvg,
        new kakao.maps.Size(14, 14),
        {{ offset: new kakao.maps.Point(7, 7) }}
      );

      function extendBounds(lng, lat) {{
        bounds.extend(new kakao.maps.LatLng(lat, lng));
      }}

      function popupHtml(properties) {{
        return `<div class="info-window">${{Object.entries(properties || {{}})
          .map(([key, value]) => `<div><strong>${{key}}</strong><pre>${{Array.isArray(value) ? value.join(", ") : String(value || "-")}}</pre></div>`)
          .join("")}}</div>`;
      }}

      function openInfo(position, properties) {{
        infoWindow.setContent(popupHtml(properties));
        infoWindow.setPosition(position);
        infoWindow.open(map);
      }}

      function ringToPath(ring) {{
        return ring.map(([lng, lat]) => {{
          extendBounds(lng, lat);
          return new kakao.maps.LatLng(lat, lng);
        }});
      }}

      function addPolygonFeature(feature, style) {{
        const geometry = feature.geometry || {{}};
        const polygonGroups = geometry.type === "Polygon" ? [geometry.coordinates] : (geometry.coordinates || []);
        polygonGroups.forEach((polygonCoords) => {{
          const path = polygonCoords.map(ringToPath);
          const polygon = new kakao.maps.Polygon({{
            map,
            path: path.length === 1 ? path[0] : path,
            strokeWeight: style.weight,
            strokeColor: style.color,
            strokeOpacity: style.opacity,
            fillColor: style.fillColor,
            fillOpacity: style.fillOpacity
          }});
          kakao.maps.event.addListener(polygon, "click", (mouseEvent) => {{
            openInfo(mouseEvent.latLng, feature.properties || {{}});
          }});
        }});
      }}

      function openRoadviewTab(feature) {{
        const [lng, lat] = feature.geometry.coordinates;
        const roadviewUrl = `https://map.kakao.com/link/roadview/${{lat}},${{lng}}`;
        window.open(roadviewUrl, "_blank", "noopener,noreferrer");
      }}

      payload.layers.filterPolygons.features.forEach((feature) => addPolygonFeature(feature, allPolygonStyle));
      payload.layers.matchedPolygons.features.forEach((feature) => addPolygonFeature(feature, matchedPolygonStyle));

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

      payload.layers.audioSignals.features.forEach((feature) => {{
        const [lng, lat] = feature.geometry.coordinates;
        const position = new kakao.maps.LatLng(lat, lng);
        extendBounds(lng, lat);
        const marker = new kakao.maps.Marker({{
          map,
          position,
          image: markerImage
        }});
        kakao.maps.event.addListener(marker, "click", () => {{
          openInfo(position, {{
            ...(feature.properties || {{}}),
            roadviewAction: "새 탭에서 카카오맵 로드뷰 열기"
          }});
          openRoadviewTab(feature);
        }});
      }});

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
