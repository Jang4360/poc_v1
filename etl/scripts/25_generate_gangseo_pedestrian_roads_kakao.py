#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT_DIR / "etl" / "raw"
OUTPUT_HTML = ROOT_DIR / "etl" / "gangseo_pedestrian_roads_kakao.html"
SEGMENT_CSV = RAW_DIR / "gangseo_road_segments_mapping.csv"
NODE_CSV = RAW_DIR / "gangseo_road_nodes_v6.csv"
KAKAO_JS_KEY = "fc0455f117ec0c48766f39c9673f18f0"

LINE_RE = re.compile(r"(?:SRID=4326;)?LINESTRING\((.*)\)")
POINT_RE = re.compile(r"(?:SRID=4326;)?POINT\(([-0-9.]+)\s+([-0-9.]+)\)")


def parse_linestring(value: str) -> list[list[float]]:
    match = LINE_RE.fullmatch(value.strip())
    if not match:
        raise ValueError(f"invalid LINESTRING: {value[:80]}")
    coords: list[list[float]] = []
    for item in match.group(1).split(","):
        lon_text, lat_text = item.strip().split()[:2]
        coords.append([float(lat_text), float(lon_text)])
    return coords


def parse_point(value: str) -> list[float]:
    match = POINT_RE.fullmatch(value.strip())
    if not match:
        raise ValueError(f"invalid POINT: {value[:80]}")
    lon_text, lat_text = match.groups()
    return [float(lat_text), float(lon_text)]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def build_payload() -> dict[str, Any]:
    segment_rows = read_csv(SEGMENT_CSV)
    node_rows = read_csv(NODE_CSV)
    pedestrian_types = {"SIDE_LINE", "SIDE_WALK"}

    segments: list[dict[str, Any]] = []
    bounds_points: list[list[float]] = []
    type_counts: Counter[str] = Counter()
    for row in segment_rows:
        segment_type = (row.get("segmentType") or "").strip()
        if segment_type not in pedestrian_types:
            continue
        coords = parse_linestring(row.get("geom", ""))
        type_counts[segment_type] += 1
        bounds_points.extend(coords)
        segments.append(
            {
                "id": row.get("edgeId", ""),
                "type": segment_type,
                "from": row.get("fromNodeId", ""),
                "to": row.get("toNodeId", ""),
                "length": row.get("lengthMeter", ""),
                "walkAccess": row.get("walkAccess", ""),
                "widthMeter": row.get("widthMeter", ""),
                "surfaceState": row.get("surfaceState", ""),
                "slopeState": row.get("slopeState", ""),
                "coords": coords,
            }
        )

    nodes: list[dict[str, Any]] = []
    for row in node_rows:
        try:
            lat, lon = parse_point(row.get("point", ""))
        except ValueError:
            continue
        nodes.append(
            {
                "id": row.get("vertexId", ""),
                "key": row.get("sourceNodeKey", ""),
                "lat": lat,
                "lng": lon,
            }
        )

    if not bounds_points:
        raise RuntimeError("no pedestrian segment geometry found")

    lats = [item[0] for item in bounds_points]
    lngs = [item[1] for item in bounds_points]
    return {
        "meta": {
            "title": "Gangseo Pedestrian Road Network",
            "segmentSource": str(SEGMENT_CSV.relative_to(ROOT_DIR)),
            "nodeSource": str(NODE_CSV.relative_to(ROOT_DIR)),
            "segmentCount": len(segments),
            "nodeCount": len(nodes),
            "segmentTypeCounts": dict(sorted(type_counts.items())),
            "bbox": [min(lngs), min(lats), max(lngs), max(lats)],
        },
        "segments": segments,
        "nodes": nodes,
    }


def render_html(payload: dict[str, Any]) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Gangseo Pedestrian Road Network</title>
  <style>
    html, body, #map {{ height: 100%; margin: 0; }}
    body {{ font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color: #111827; }}
    .panel {{
      position: absolute; z-index: 10; top: 12px; left: 12px; width: 350px;
      max-height: calc(100vh - 24px); overflow: auto; background: rgba(255,255,255,0.94);
      border: 1px solid #d1d5db; border-radius: 8px; box-shadow: 0 8px 24px rgba(15,23,42,0.18);
      padding: 12px;
    }}
    h1 {{ font-size: 17px; margin: 0 0 10px; }}
    .meta {{ font-size: 12px; color: #4b5563; line-height: 1.45; margin-bottom: 10px; }}
    .row {{ display: flex; align-items: center; gap: 8px; margin: 8px 0; font-size: 13px; }}
    .row input {{ width: 16px; height: 16px; }}
    .swatch {{ width: 18px; height: 4px; display: inline-block; border-radius: 2px; background: #000; }}
    .node-dot {{
      width: 6px; height: 6px; border-radius: 50%; background: #2563eb;
      border: 1px solid #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.35); transform: translate(-50%, -50%);
    }}
    .status {{ margin-top: 10px; font-size: 12px; color: #374151; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 10px; }}
    th, td {{ border-top: 1px solid #e5e7eb; padding: 5px 3px; text-align: right; }}
    th:first-child, td:first-child {{ text-align: left; }}
    .popup {{ max-width: 300px; background: #fff; border: 1px solid #d1d5db; border-radius: 6px; padding: 8px; font-size: 12px; }}
    .popup table {{ margin: 0; }}
    .popup td {{ text-align: left; vertical-align: top; border-top: 1px solid #e5e7eb; padding: 3px 4px; }}
    .popup td:first-child {{ color: #6b7280; white-space: nowrap; }}
  </style>
</head>
<body>
  <div id="map"></div>
  <div class="panel">
    <h1>Gangseo Pedestrian Road Network</h1>
    <div class="meta">
      Segment: <code>gangseo_road_segments_mapping.csv</code><br />
      Nodes: <code>gangseo_road_nodes_v6.csv</code><br />
      Basemap: Kakao Maps SDK
    </div>
    <label class="row"><input type="checkbox" id="toggleSegments" checked><span class="swatch"></span>보행자 도로 segment 표시</label>
    <label class="row"><input type="checkbox" id="toggleNodes">노드 표시</label>
    <table>
      <tbody>
        <tr><td>SIDE_LINE</td><td id="sideLineCount"></td></tr>
        <tr><td>SIDE_WALK</td><td id="sideWalkCount"></td></tr>
        <tr><td>nodes</td><td id="nodeCount"></td></tr>
      </tbody>
    </table>
    <div class="status" id="status">loading Kakao map...</div>
  </div>

  <script src="https://dapi.kakao.com/v2/maps/sdk.js?appkey={KAKAO_JS_KEY}&autoload=false"></script>
  <script>
    const payload = {payload_json};
    let map = null;
    let infoWindow = null;
    const segmentObjects = [];
    const nodeObjects = [];
    const maxNodesInView = 1800;

    function init() {{
      if (!window.kakao || !window.kakao.maps) {{
        document.getElementById("status").textContent = "Kakao Maps SDK load failed. Open through http://localhost:3000.";
        return;
      }}
      kakao.maps.load(() => {{
        map = new kakao.maps.Map(document.getElementById("map"), {{
          center: new kakao.maps.LatLng(35.13, 128.92),
          level: 8
        }});
        infoWindow = new kakao.maps.InfoWindow({{ removable: true }});
        document.getElementById("toggleSegments").addEventListener("change", renderSegments);
        document.getElementById("toggleNodes").addEventListener("change", renderNodes);
        kakao.maps.event.addListener(map, "idle", renderNodes);
        renderSummary();
        renderSegments();
        fitBounds();
        renderNodes();
      }});
    }}

    function renderSummary() {{
      document.getElementById("sideLineCount").textContent = payload.meta.segmentTypeCounts.SIDE_LINE || 0;
      document.getElementById("sideWalkCount").textContent = payload.meta.segmentTypeCounts.SIDE_WALK || 0;
      document.getElementById("nodeCount").textContent = payload.meta.nodeCount || 0;
    }}

    function fitBounds() {{
      const [minLng, minLat, maxLng, maxLat] = payload.meta.bbox;
      const bounds = new kakao.maps.LatLngBounds();
      bounds.extend(new kakao.maps.LatLng(minLat, minLng));
      bounds.extend(new kakao.maps.LatLng(maxLat, maxLng));
      map.setBounds(bounds);
    }}

    function renderSegments() {{
      clearObjects(segmentObjects);
      if (!document.getElementById("toggleSegments").checked) {{
        updateStatus();
        return;
      }}
      for (const segment of payload.segments) {{
        const path = segment.coords.map(([lat, lng]) => new kakao.maps.LatLng(lat, lng));
        const line = new kakao.maps.Polyline({{
          path,
          strokeWeight: 3,
          strokeColor: "#000000",
          strokeOpacity: 0.9,
          strokeStyle: "solid"
        }});
        kakao.maps.event.addListener(line, "click", event => openInfo(event.latLng, segment));
        line.setMap(map);
        segmentObjects.push(line);
      }}
      updateStatus();
    }}

    function renderNodes() {{
      clearObjects(nodeObjects);
      if (!map || !document.getElementById("toggleNodes").checked) {{
        updateStatus();
        return;
      }}
      const bounds = map.getBounds();
      let rendered = 0;
      for (const node of payload.nodes) {{
        if (rendered >= maxNodesInView) break;
        const position = new kakao.maps.LatLng(node.lat, node.lng);
        if (!bounds.contain(position)) continue;
        const content = document.createElement("div");
        content.className = "node-dot";
        content.addEventListener("click", () => openInfo(position, node));
        const overlay = new kakao.maps.CustomOverlay({{
          position,
          content,
          xAnchor: 0.5,
          yAnchor: 0.5,
          clickable: true
        }});
        overlay.setMap(map);
        nodeObjects.push(overlay);
        rendered += 1;
      }}
      updateStatus();
    }}

    function clearObjects(objects) {{
      while (objects.length) {{
        objects.pop().setMap(null);
      }}
    }}

    function updateStatus() {{
      const segmentText = document.getElementById("toggleSegments").checked ? `${{segmentObjects.length}} segments` : "segments hidden";
      const nodeText = document.getElementById("toggleNodes").checked ? `${{nodeObjects.length}} nodes in view` : "nodes hidden";
      document.getElementById("status").textContent = `${{segmentText}}, ${{nodeText}}, updated ${{new Date().toLocaleTimeString()}}`;
    }}

    function openInfo(position, props) {{
      infoWindow.setContent(`<div class="popup">${{popupHtml(props)}}</div>`);
      infoWindow.setPosition(position);
      infoWindow.open(map);
    }}

    function popupHtml(props) {{
      const rows = Object.entries(props)
        .filter(([key]) => key !== "coords")
        .map(([key, value]) => `<tr><td>${{escapeHtml(key)}}</td><td>${{escapeHtml(String(value ?? ""))}}</td></tr>`)
        .join("");
      return `<table>${{rows}}</table>`;
    }}

    function escapeHtml(text) {{
      return text.replace(/[&<>"']/g, ch => ({{ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }}[ch]));
    }}

    init();
  </script>
</body>
</html>
"""


def main() -> int:
    payload = build_payload()
    OUTPUT_HTML.write_text(render_html(payload), encoding="utf-8")
    print(f"generated {OUTPUT_HTML}")
    print(json.dumps(payload["meta"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
