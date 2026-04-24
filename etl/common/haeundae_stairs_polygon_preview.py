from __future__ import annotations

import csv
import html
import json
import math
import os
from pathlib import Path
from typing import Any

from etl.common.db import connect


ROOT_DIR = Path(__file__).resolve().parents[2]
ETL_DIR = ROOT_DIR / "etl"
STAIRS_CSV = ROOT_DIR / "etl" / "raw" / "stg_stairs_ready.csv"
SUBWAY_ELEVATORS_CSV = ROOT_DIR / "etl" / "raw" / "subway_station_elevators_erd_ready.csv"
OUTPUT_HTML = ETL_DIR / "haeundae_stairs_polygon_preview.html"
OUTPUT_GEOJSON = ETL_DIR / "haeundae_stairs_polygon_preview.geojson"
KAKAO_JAVASCRIPT_KEY = os.getenv("KAKAO_JAVASCRIPT_KEY", "")

DEFAULT_CENTER_LAT = 35.1631
DEFAULT_CENTER_LON = 129.1635
DEFAULT_RADIUS_M = 5000

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
STAIRS_POINT_STYLE = {
    "radius": 5,
    "color": "#b91c1c",
    "weight": 1,
    "fillColor": "#ef4444",
    "fillOpacity": 0.9,
}
ROAD_SEGMENT_STYLE = {
    "color": "#475569",
    "weight": 2,
    "opacity": 0.55,
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


def _read_candidate_stairs(
    *,
    center_lat: float,
    center_lon: float,
    radius_m: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    with STAIRS_CSV.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            lat_text = (row.get("lat") or "").strip()
            lon_text = (row.get("lng") or "").strip()
            if not lat_text or not lon_text:
                continue
            lat = float(lat_text)
            lon = float(lon_text)
            distance_meter = _haversine_meter(center_lat, center_lon, lat, lon)
            if distance_meter > radius_m:
                continue
            candidates.append(
                {
                    "sourceId": row.get("sourceId") or "",
                    "districtGu": row.get("districtGu") or "",
                    "name": row.get("name") or "",
                    "point": row.get("point") or "",
                    "lat": lat,
                    "lng": lon,
                    "widthMeter": row.get("widthMeter") or "",
                    "areaSquareMeter": row.get("areaSquareMeter") or "",
                    "structureCode": row.get("structureCode") or "",
                    "structureName": row.get("structureName") or "",
                    "scls": row.get("scls") or "",
                    "ufid": row.get("ufid") or "",
                    "distanceMeter": round(distance_meter, 2),
                }
            )
    return candidates


def _read_subway_station_features_from_csv() -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    with SUBWAY_ELEVATORS_CSV.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            point = (row.get("point") or "").strip()
            if not point.startswith("POINT(") or not point.endswith(")"):
                continue
            body = point.removeprefix("POINT(").removesuffix(")")
            lon_text, lat_text = body.split()[:2]
            lon = float(lon_text)
            lat = float(lat_text)
            station_id = (row.get("stationId") or "").strip()
            station_name = (row.get("stationName") or "").strip()
            line_name = (row.get("lineName") or "").strip()
            key = (station_id, station_name)
            bucket = grouped.setdefault(
                key,
                {
                    "stationId": station_id,
                    "stationName": station_name,
                    "lineNames": set(),
                    "sumLat": 0.0,
                    "sumLng": 0.0,
                    "count": 0,
                },
            )
            if line_name:
                bucket["lineNames"].add(f"{line_name}호선" if line_name.isdigit() else line_name)
            bucket["sumLat"] += lat
            bucket["sumLng"] += lon
            bucket["count"] += 1

    features: list[dict[str, Any]] = []
    for bucket in grouped.values():
        lat = bucket["sumLat"] / bucket["count"]
        lng = bucket["sumLng"] / bucket["count"]
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "stationId": bucket["stationId"],
                    "stationName": bucket["stationName"],
                    "lineName": " / ".join(sorted(bucket["lineNames"])),
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [lng, lat],
                },
            }
        )
    features.sort(key=lambda feature: (feature["properties"]["stationName"], feature["properties"]["stationId"]))
    return features


def _match_stair_to_polygons(cur: Any, stair: dict[str, Any]) -> list[dict[str, Any]]:
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
        (stair["lng"], stair["lat"]),
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
    candidate_stairs = _read_candidate_stairs(center_lat=center_lat, center_lon=center_lon, radius_m=radius_m)
    matched_polygon_by_edge: dict[int, int] = {}
    matched_stairs_features: list[dict[str, Any]] = []

    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH
                station_points AS (
                    SELECT
                        se."stationId",
                        se."stationName",
                        string_agg(DISTINCT se."lineName", ' / ' ORDER BY se."lineName") AS "lineNames",
                        ST_Centroid(ST_Collect(se."point")) AS station_point
                    FROM subway_station_elevators se
                    GROUP BY se."stationId", se."stationName"
                )
                SELECT
                    "stationId",
                    "stationName",
                    "lineNames",
                    ST_Y(station_point) AS lat,
                    ST_X(station_point) AS lng
                FROM station_points
                ORDER BY "stationName", "stationId"
                """,
            )
            subway_station_features = [
                {
                    "type": "Feature",
                    "properties": {
                        "stationId": station_id,
                        "stationName": station_name,
                        "lineName": line_name,
                    },
                    "geometry": {
                        "type": "Point",
                        "coordinates": [float(lng), float(lat)],
                    },
                }
                for station_id, station_name, line_name, lat, lng in cur.fetchall()
            ]
            if not subway_station_features:
                subway_station_features = _read_subway_station_features_from_csv()

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
            polygon_features = []
            for edge_id, source_row_number, source_ufid, road_width_meter, buffer_half_width_meter, geometry in cur.fetchall():
                polygon_features.append(
                    {
                        "type": "Feature",
                        "properties": {
                            "edgeId": int(edge_id),
                            "sourceRowNumber": int(source_row_number),
                            "sourceUfid": source_ufid,
                            "roadWidthMeter": float(road_width_meter),
                            "bufferHalfWidthMeter": float(buffer_half_width_meter),
                            "hasMatchedStair": False,
                            "matchedStairCount": 0,
                        },
                        "geometry": _json_geometry(geometry),
                    }
                )

            for stair in candidate_stairs:
                matched_polygons = _match_stair_to_polygons(cur, stair)
                if not matched_polygons:
                    continue
                matched_edge_ids = [item["edgeId"] for item in matched_polygons]
                for edge_id in matched_edge_ids:
                    matched_polygon_by_edge[edge_id] = matched_polygon_by_edge.get(edge_id, 0) + 1
                matched_stairs_features.append(
                    {
                        "type": "Feature",
                        "properties": {
                            **stair,
                            "matchedPolygonCount": len(matched_polygons),
                            "matchedEdgeIds": matched_edge_ids,
                        },
                        "geometry": {
                            "type": "Point",
                            "coordinates": [stair["lng"], stair["lat"]],
                        },
                    }
                )

    matched_polygon_features = []
    for feature in polygon_features:
        edge_id = feature["properties"]["edgeId"]
        matched_count = matched_polygon_by_edge.get(edge_id, 0)
        if matched_count:
            feature["properties"]["hasMatchedStair"] = True
            feature["properties"]["matchedStairCount"] = matched_count
            matched_polygon_features.append(feature)

    return {
        "meta": {
            "title": "Busan Station Picker",
            "centerLat": center_lat,
            "centerLon": center_lon,
            "radiusMeter": radius_m,
            "stairsCsv": str(STAIRS_CSV),
            "localhostUrl": f"http://127.0.0.1:3000/etl/{OUTPUT_HTML.name}",
            "outputHtml": str(OUTPUT_HTML),
            "outputGeojson": str(OUTPUT_GEOJSON),
        },
        "summary": {
            "roadSegments": len(road_segment_features),
            "subwayStations": len(subway_station_features),
            "filterPolygons": len(polygon_features),
            "stairsCandidates": len(candidate_stairs),
            "stairsMatched": len(matched_stairs_features),
            "matchedPolygons": len(matched_polygon_features),
        },
        "layers": {
            "roadSegments": _feature_collection(road_segment_features),
            "subwayStations": _feature_collection(subway_station_features),
            "filterPolygons": _feature_collection(polygon_features),
            "matchedPolygons": _feature_collection(matched_polygon_features),
            "stairs": _feature_collection(matched_stairs_features),
        },
    }


def render_html(payload: dict[str, Any]) -> str:
    meta = payload["meta"]
    payload_json = json.dumps(payload, ensure_ascii=False)
    kakao_javascript_key = html.escape(KAKAO_JAVASCRIPT_KEY)
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(meta['title'])}</title>
  <style>
    html, body, #map {{ height: 100%; margin: 0; }}
    body {{ font: 13px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
    .panel {{
      position: absolute;
      z-index: 700;
      top: 12px;
      left: 12px;
      width: min(440px, calc(100vw - 24px));
      padding: 12px 14px;
      background: rgba(255, 255, 255, 0.94);
      border: 1px solid #cbd5e1;
      box-shadow: 0 6px 20px rgba(15, 23, 42, 0.12);
    }}
    .side-panel {{
      position: absolute;
      z-index: 700;
      top: 12px;
      right: 12px;
      width: min(420px, calc(100vw - 24px));
      max-height: calc(100vh - 24px);
      overflow: auto;
      padding: 12px 14px;
      background: rgba(255, 255, 255, 0.96);
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
    .info-window {{
      min-width: 220px;
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
    .capture-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      margin-top: 10px;
    }}
    .capture-field {{
      display: flex;
      flex-direction: column;
      gap: 4px;
    }}
    .capture-field.full {{
      grid-column: 1 / -1;
    }}
    .capture-field label {{
      font-size: 12px;
      color: #334155;
    }}
    .capture-field input {{
      height: 34px;
      padding: 0 10px;
      border: 1px solid #cbd5e1;
      font: inherit;
    }}
    .capture-actions {{
      display: flex;
      gap: 8px;
      margin-top: 10px;
      flex-wrap: wrap;
    }}
    .button {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 34px;
      padding: 0 12px;
      border: 1px solid #94a3b8;
      background: #f8fafc;
      color: #0f172a;
      font: inherit;
      cursor: pointer;
    }}
    .button.primary {{
      background: #2563eb;
      border-color: #2563eb;
      color: #fff;
    }}
    .button:disabled {{
      opacity: 0.5;
      cursor: not-allowed;
    }}
    .status-text {{
      margin-top: 8px;
      font-size: 12px;
      color: #475569;
    }}
    .capture-table-wrap {{
      margin-top: 12px;
      border: 1px solid #e2e8f0;
      overflow: hidden;
    }}
    .capture-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }}
    .capture-table th,
    .capture-table td {{
      padding: 8px 10px;
      border-bottom: 1px solid #e2e8f0;
      text-align: left;
      vertical-align: top;
    }}
    .capture-table th {{
      background: #f8fafc;
      color: #334155;
      position: sticky;
      top: 0;
    }}
    .capture-table tbody tr:last-child td {{
      border-bottom: 0;
    }}
    .empty-text {{
      margin: 10px 0 0;
      font-size: 12px;
      color: #64748b;
    }}
    @media (max-width: 1200px) {{
      .side-panel {{
        top: auto;
        bottom: 12px;
        max-height: 42vh;
      }}
    }}
  </style>
</head>
<body>
  <div id="map"></div>
  <div class="panel">
    <h1>{html.escape(meta['title'])}</h1>
    <p>지도를 클릭하면 가장 가까운 부산 지하철역이 자동 입력됩니다.</p>
    <p id="host-warning" class="warning" hidden></p>
  </div>
  <div class="side-panel">
    <h1>역 좌표 채집</h1>
    <p>지도를 클릭하면 임시 마커가 찍힙니다. 역이름과 호선 번호를 입력한 뒤 확인을 누르면 표에 적재됩니다.</p>
    <div class="capture-grid">
      <div class="capture-field full">
        <label for="station-name">역이름</label>
        <input id="station-name" type="text" placeholder="예: 해운대역" />
      </div>
      <div class="capture-field">
        <label for="line-name">호선 번호</label>
        <input id="line-name" type="text" placeholder="예: 2호선" />
      </div>
      <div class="capture-field">
        <label for="selected-lat">위도</label>
        <input id="selected-lat" type="text" readonly />
      </div>
      <div class="capture-field">
        <label for="selected-lng">경도</label>
        <input id="selected-lng" type="text" readonly />
      </div>
    </div>
    <div class="capture-actions">
      <button id="confirm-capture" class="button primary" type="button" disabled>확인</button>
      <button id="copy-capture" class="button" type="button" disabled>복사</button>
      <button id="clear-capture" class="button" type="button" disabled>전체 지우기</button>
    </div>
    <p id="capture-status" class="status-text">지도를 클릭해 좌표를 선택하세요.</p>
    <div class="capture-table-wrap">
      <table class="capture-table">
        <thead>
          <tr>
            <th>역이름</th>
            <th>호선 번호</th>
            <th>위도</th>
            <th>경도</th>
          </tr>
        </thead>
        <tbody id="capture-table-body"></tbody>
      </table>
    </div>
    <p id="capture-empty" class="empty-text">아직 적재된 좌표가 없습니다.</p>
  </div>
  <script src="https://dapi.kakao.com/v2/maps/sdk.js?appkey={kakao_javascript_key}"></script>
  <script>
    const payload = {payload_json};
    const hostWarning = document.getElementById("host-warning");
    const stationNameInput = document.getElementById("station-name");
    const lineNameInput = document.getElementById("line-name");
    const selectedLatInput = document.getElementById("selected-lat");
    const selectedLngInput = document.getElementById("selected-lng");
    const confirmCaptureButton = document.getElementById("confirm-capture");
    const copyCaptureButton = document.getElementById("copy-capture");
    const clearCaptureButton = document.getElementById("clear-capture");
    const captureStatus = document.getElementById("capture-status");
    const captureTableBody = document.getElementById("capture-table-body");
    const captureEmpty = document.getElementById("capture-empty");
    const subwayStations = payload.layers.subwayStations.features || [];

    function setWarning(message) {{
      hostWarning.hidden = false;
      hostWarning.innerHTML = message;
    }}

    if (location.protocol === "file:") {{
      setWarning(`현재는 <code>file://</code> 로 열려 있어서 카카오맵 SDK 도메인 제한에 걸립니다. <a href="${{payload.meta.localhostUrl}}">${{payload.meta.localhostUrl}}</a> 로 열어야 합니다.`);
    }}

    if (!window.kakao || !window.kakao.maps) {{
      setWarning(`Kakao Maps SDK를 불러오지 못했습니다. <a href="${{payload.meta.localhostUrl}}">${{payload.meta.localhostUrl}}</a> 로 접속하고, 등록 도메인/키를 다시 확인하세요.`);
    }} else {{
      const mapContainer = document.getElementById("map");
      const map = new kakao.maps.Map(mapContainer, {{
        center: new kakao.maps.LatLng(payload.meta.centerLat, payload.meta.centerLon),
        level: 4
      }});
      const bounds = new kakao.maps.LatLngBounds();
      const infoWindow = new kakao.maps.InfoWindow({{ removable: true }});
      let selectedPoint = null;
      let selectedMarker = null;
      const capturedStations = [];
      const selectedMarkerSvg = `data:image/svg+xml;charset=UTF-8,${{encodeURIComponent(`
        <svg xmlns="http://www.w3.org/2000/svg" width="20" height="28" viewBox="0 0 20 28">
          <path d="M10 0C4.5 0 0 4.5 0 10c0 7.4 10 18 10 18s10-10.6 10-18C20 4.5 15.5 0 10 0z" fill="#111827"/>
          <circle cx="10" cy="10" r="4" fill="#ffffff"/>
        </svg>
      `)}}`;
      const selectedMarkerImage = new kakao.maps.MarkerImage(
        selectedMarkerSvg,
        new kakao.maps.Size(20, 28),
        {{ offset: new kakao.maps.Point(10, 28) }}
      );

      function extendBounds(lng, lat) {{
        bounds.extend(new kakao.maps.LatLng(lat, lng));
      }}

      function syncCaptureButtons() {{
        const hasSelection = Boolean(selectedPoint);
        const hasRows = capturedStations.length > 0;
        confirmCaptureButton.disabled = !hasSelection;
        copyCaptureButton.disabled = !hasRows;
        clearCaptureButton.disabled = !hasRows;
        captureEmpty.hidden = hasRows;
      }}

      function updateSelectedInputs() {{
        selectedLatInput.value = selectedPoint ? selectedPoint.lat.toFixed(7) : "";
        selectedLngInput.value = selectedPoint ? selectedPoint.lng.toFixed(7) : "";
      }}

      function renderCaptureTable() {{
        captureTableBody.innerHTML = capturedStations.map((row) => `
          <tr>
            <td>${{row.stationName}}</td>
            <td>${{row.lineName}}</td>
            <td>${{row.lat}}</td>
            <td>${{row.lng}}</td>
          </tr>
        `).join("");
        syncCaptureButtons();
      }}

      function haversineMeter(lat1, lon1, lat2, lon2) {{
        const earthRadius = 6371000;
        const dLat = (lat2 - lat1) * Math.PI / 180;
        const dLon = (lon2 - lon1) * Math.PI / 180;
        const a = Math.sin(dLat / 2) ** 2
          + Math.cos(lat1 * Math.PI / 180)
          * Math.cos(lat2 * Math.PI / 180)
          * Math.sin(dLon / 2) ** 2;
        return earthRadius * 2 * Math.asin(Math.sqrt(a));
      }}

      function nearestSubwayStation(lat, lng) {{
        let best = null;
        subwayStations.forEach((feature) => {{
          const [stationLng, stationLat] = feature.geometry.coordinates;
          const distanceMeter = haversineMeter(lat, lng, stationLat, stationLng);
          if (!best || distanceMeter < best.distanceMeter) {{
            best = {{
              stationName: feature.properties.stationName || "",
              lineName: feature.properties.lineName || "",
              distanceMeter,
            }};
          }}
        }});
        return best;
      }}

      function setSelectedPoint(lat, lng) {{
        selectedPoint = {{ lat: Number(lat), lng: Number(lng) }};
        updateSelectedInputs();
        const nearestStation = nearestSubwayStation(selectedPoint.lat, selectedPoint.lng);
        if (nearestStation && nearestStation.distanceMeter <= 500) {{
          stationNameInput.value = nearestStation.stationName;
          lineNameInput.value = nearestStation.lineName;
          captureStatus.textContent = `선택 좌표: 위도 ${{selectedPoint.lat.toFixed(7)}}, 경도 ${{selectedPoint.lng.toFixed(7)}} | 최근접 역 ${{nearestStation.stationName}} (${{nearestStation.lineName}}), ${{nearestStation.distanceMeter.toFixed(0)}}m`;
        }} else {{
          stationNameInput.value = "";
          lineNameInput.value = "";
          captureStatus.textContent = `선택 좌표: 위도 ${{selectedPoint.lat.toFixed(7)}}, 경도 ${{selectedPoint.lng.toFixed(7)}} | 500m 내 자동 추정 역 없음`;
        }}
        if (selectedMarker) {{
          selectedMarker.setMap(null);
        }}
        selectedMarker = new kakao.maps.Marker({{
          map,
          position: new kakao.maps.LatLng(selectedPoint.lat, selectedPoint.lng),
          image: selectedMarkerImage
        }});
        syncCaptureButtons();
      }}

      function popupHtml(properties) {{
        return `<div class="info-window">${{Object.entries(properties || {{}})
          .map(([key, value]) => `<div><strong>${{key}}</strong><pre>${{Array.isArray(value) ? value.join(", ") : String(value)}}</pre></div>`)
          .join("")}}</div>`;
      }}

      function openInfo(position, properties) {{
        infoWindow.setContent(popupHtml(properties));
        infoWindow.setPosition(position);
        infoWindow.open(map);
      }}

      subwayStations.forEach((feature) => {{
        const [lng, lat] = feature.geometry.coordinates;
        extendBounds(lng, lat);
      }});

      kakao.maps.event.addListener(map, "click", (mouseEvent) => {{
        infoWindow.close();
        setSelectedPoint(mouseEvent.latLng.getLat(), mouseEvent.latLng.getLng());
      }});
      kakao.maps.event.addListener(map, "click", () => infoWindow.close());
      if (subwayStations.length > 0) {{
        map.setBounds(bounds);
      }}

      confirmCaptureButton.addEventListener("click", () => {{
        if (!selectedPoint) {{
          captureStatus.textContent = "먼저 지도에서 좌표를 선택하세요.";
          return;
        }}
        const stationName = stationNameInput.value.trim();
        const lineName = lineNameInput.value.trim();
        if (!stationName) {{
          captureStatus.textContent = "역이름을 입력하세요.";
          stationNameInput.focus();
          return;
        }}
        capturedStations.push({{
          stationName,
          lineName,
          lat: selectedPoint.lat.toFixed(7),
          lng: selectedPoint.lng.toFixed(7)
        }});
        renderCaptureTable();
        captureStatus.textContent = `${{stationName}} 좌표를 표에 적재했습니다.`;
        stationNameInput.value = "";
        lineNameInput.value = "";
      }});

      copyCaptureButton.addEventListener("click", async () => {{
        const lines = [
          ["역이름", "호선 번호", "위도", "경도"].join("\\t"),
          ...capturedStations.map((row) => [row.stationName, row.lineName, row.lat, row.lng].join("\\t"))
        ];
        try {{
          await navigator.clipboard.writeText(lines.join("\\n"));
          captureStatus.textContent = `${{capturedStations.length}}개 행을 클립보드에 복사했습니다.`;
        }} catch (error) {{
          captureStatus.textContent = "복사에 실패했습니다. 브라우저 권한을 확인하세요.";
        }}
      }});

      clearCaptureButton.addEventListener("click", () => {{
        capturedStations.length = 0;
        renderCaptureTable();
        captureStatus.textContent = "적재된 좌표를 모두 지웠습니다.";
      }});

      renderCaptureTable();
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
