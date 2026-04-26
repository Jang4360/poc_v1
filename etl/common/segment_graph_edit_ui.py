from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from etl.common.subway_elevator_preview import KAKAO_JAVASCRIPT_KEY, SEGMENT_STYLES


def render_html(payload: dict[str, Any]) -> str:
    meta = payload["meta"]
    summary = payload["summary"]
    payload_json = json.dumps(payload, ensure_ascii=False)
    segment_styles_json = json.dumps(SEGMENT_STYLES, ensure_ascii=False)
    kakao_javascript_key = html.escape(KAKAO_JAVASCRIPT_KEY)
    type_text = ", ".join(f"{item['name']} {item['count']}" for item in summary["segmentTypeCounts"]) or "-"
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
      font: 13px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: #0f172a;
    }}
    .toolbar {{
      position: absolute;
      z-index: 800;
      top: 12px;
      left: 12px;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px;
      max-width: calc(100vw - 392px);
      padding: 8px;
      background: rgba(255, 255, 255, 0.96);
      border: 1px solid #dbe3ef;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.14);
    }}
    .toolbar button, .toolbar select {{
      height: 32px;
      border: 1px solid #cbd5e1;
      background: #ffffff;
      color: #0f172a;
      padding: 0 10px;
      font: inherit;
      cursor: pointer;
    }}
    .toolbar button.active {{
      background: #0f172a;
      border-color: #0f172a;
      color: #ffffff;
    }}
    .toolbar .stat {{
      color: #475569;
      padding: 0 6px;
      white-space: nowrap;
    }}
    .side-panel {{
      position: absolute;
      z-index: 810;
      top: 0;
      right: 0;
      width: 360px;
      height: 100%;
      background: rgba(255, 255, 255, 0.97);
      border-left: 1px solid #dbe3ef;
      box-shadow: -10px 0 28px rgba(15, 23, 42, 0.16);
      display: grid;
      grid-template-rows: auto auto 1fr auto;
    }}
    .panel-header {{
      padding: 14px 14px 10px;
      border-bottom: 1px solid #e2e8f0;
    }}
    .panel-header h1 {{
      margin: 0 0 6px;
      font-size: 15px;
    }}
    .panel-header p {{
      margin: 0 0 4px;
      color: #475569;
    }}
    .panel-actions {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 6px;
      padding: 10px 14px;
      border-bottom: 1px solid #e2e8f0;
    }}
    .panel-actions button {{
      height: 32px;
      border: 1px solid #cbd5e1;
      background: #ffffff;
      cursor: pointer;
    }}
    .edits {{
      overflow: auto;
      padding: 10px 14px;
    }}
    .edit-card {{
      border: 1px solid #e2e8f0;
      padding: 8px;
      margin-bottom: 8px;
      background: #f8fafc;
    }}
    .edit-card strong {{
      display: block;
      margin-bottom: 4px;
    }}
    .edit-card code {{
      word-break: break-all;
      color: #334155;
    }}
    textarea {{
      width: calc(100% - 28px);
      height: 170px;
      margin: 0 14px 14px;
      resize: vertical;
      border: 1px solid #cbd5e1;
      font: 11px/1.35 ui-monospace, SFMono-Regular, Menlo, monospace;
    }}
    .toast {{
      position: absolute;
      z-index: 820;
      left: 12px;
      bottom: 12px;
      max-width: calc(100vw - 400px);
      padding: 9px 12px;
      color: #ffffff;
      background: rgba(15, 23, 42, 0.92);
      box-shadow: 0 8px 20px rgba(15, 23, 42, 0.16);
    }}
    .hidden {{
      display: none;
    }}
  </style>
</head>
<body>
  <div id="map"></div>
  <div class="toolbar">
    <button id="mode-pan" class="active" type="button">선택</button>
    <button id="mode-delete" type="button">삭제</button>
    <button id="mode-add" type="button">추가</button>
    <select id="add-type" aria-label="추가 segment type">
      <option value="SIDE_LEFT">SIDE_LEFT</option>
      <option value="SIDE_RIGHT">SIDE_RIGHT</option>
    </select>
    <button id="reload-bbox" type="button">현재 bbox 새로고침</button>
    <span id="visible-stat" class="stat">visible -</span>
  </div>
  <aside class="side-panel">
    <div class="panel-header">
      <h1>{html.escape(meta['title'])}</h1>
      <p>source: {html.escape(Path(meta.get('outputGeojson', 'segment_02c_graph_materialized.geojson')).name)}</p>
      <p>nodes {summary['nodeCount']}, segments {summary['segmentCount']}</p>
      <p>types: {html.escape(type_text)}</p>
    </div>
    <div class="panel-actions">
      <button id="copy-edits" type="button">JSON 복사</button>
      <button id="download-edits" type="button">JSON 저장</button>
      <button id="undo-edit" type="button">되돌리기</button>
      <button id="clear-edits" type="button">전체 초기화</button>
    </div>
    <div id="edits" class="edits"></div>
    <textarea id="edits-json" spellcheck="false" readonly></textarea>
  </aside>
  <div id="toast" class="toast hidden"></div>
  <script src="https://dapi.kakao.com/v2/maps/sdk.js?appkey={kakao_javascript_key}"></script>
  <script>
    const payload = {payload_json};
    const segmentStyles = {segment_styles_json};
    const storageKey = "segment_02c_manual_edits_v1";
    const sourceVersion = "02c_graph_materialized";
    let mode = "pan";
    let overlays = [];
    let selectedStart = null;
    let addPreviewMarkers = [];
    let manualEdits = loadEdits();

    const mapEl = document.getElementById("map");
    const visibleStat = document.getElementById("visible-stat");
    const editsEl = document.getElementById("edits");
    const editsJsonEl = document.getElementById("edits-json");
    const toastEl = document.getElementById("toast");
    const addTypeEl = document.getElementById("add-type");

    function showToast(message) {{
      toastEl.textContent = message;
      toastEl.classList.remove("hidden");
      window.clearTimeout(showToast.timer);
      showToast.timer = window.setTimeout(() => toastEl.classList.add("hidden"), 1800);
    }}

    function loadEdits() {{
      try {{
        const stored = localStorage.getItem(storageKey);
        return stored ? JSON.parse(stored) : [];
      }} catch (_error) {{
        return [];
      }}
    }}

    function persistEdits() {{
      localStorage.setItem(storageKey, JSON.stringify(manualEdits));
      renderEdits();
    }}

    function editDocument() {{
      return {{
        version: sourceVersion,
        sourceHtml: payload.meta.outputHtml,
        sourceGeojson: payload.meta.outputGeojson,
        createdAt: new Date().toISOString(),
        edits: manualEdits
      }};
    }}

    function renderEdits() {{
      editsEl.innerHTML = "";
      manualEdits.slice().reverse().forEach((edit, reverseIndex) => {{
        const index = manualEdits.length - reverseIndex;
        const card = document.createElement("div");
        card.className = "edit-card";
        const label = edit.action === "delete_segment" ? `delete edge #${{edit.edgeId}}` : `add ${{edit.segmentType}}`;
        card.innerHTML = `<strong>${{index}}. ${{label}}</strong><code>${{JSON.stringify(edit)}}</code>`;
        editsEl.appendChild(card);
      }});
      editsJsonEl.value = JSON.stringify(editDocument(), null, 2);
    }}

    function setMode(nextMode) {{
      mode = nextMode;
      selectedStart = null;
      addPreviewMarkers.forEach(marker => marker.setMap(null));
      addPreviewMarkers = [];
      ["pan", "delete", "add"].forEach(name => {{
        document.getElementById(`mode-${{name}}`).classList.toggle("active", mode === name);
      }});
      showToast(mode === "delete" ? "삭제할 세그먼트를 클릭하세요." : mode === "add" ? "첫 번째 지점을 클릭하세요." : "선택 모드입니다.");
    }}

    function segmentDeleted(edgeId) {{
      return manualEdits.some(edit => edit.action === "delete_segment" && edit.edgeId === edgeId);
    }}

    function boundsToBox(bounds) {{
      const sw = bounds.getSouthWest();
      const ne = bounds.getNorthEast();
      return {{ minLng: sw.getLng(), minLat: sw.getLat(), maxLng: ne.getLng(), maxLat: ne.getLat() }};
    }}

    function pointInBox(coord, box) {{
      const [lng, lat] = coord;
      return lng >= box.minLng && lng <= box.maxLng && lat >= box.minLat && lat <= box.maxLat;
    }}

    function lineInBox(coords, box) {{
      return coords.some(coord => pointInBox(coord, box));
    }}

    function clearOverlays() {{
      overlays.forEach(overlay => overlay.setMap(null));
      overlays = [];
    }}

    function styleFor(segmentType) {{
      return segmentStyles[segmentType] || segmentStyles.CENTERLINE;
    }}

    function latLngFromCoord(coord) {{
      return new kakao.maps.LatLng(coord[1], coord[0]);
    }}

    function coordFromLatLng(latLng) {{
      return [Number(latLng.getLng().toFixed(8)), Number(latLng.getLat().toFixed(8))];
    }}

    function addNode(feature) {{
      const marker = new kakao.maps.Circle({{
        map,
        center: latLngFromCoord(feature.geometry.coordinates),
        radius: feature.properties.degree > 2 ? 1.45 : 1.05,
        strokeWeight: 1,
        strokeColor: "#111827",
        strokeOpacity: 0.9,
        fillColor: "#111827",
        fillOpacity: 0.95,
        zIndex: 6
      }});
      overlays.push(marker);
    }}

    function addLine(feature) {{
      const props = feature.properties;
      const style = styleFor(props.segmentType);
      const path = feature.geometry.coordinates.map(latLngFromCoord);
      const visibleLine = new kakao.maps.Polyline({{
        map,
        path,
        strokeColor: style.strokeColor,
        strokeWeight: style.strokeWeight,
        strokeOpacity: style.strokeOpacity,
        zIndex: 4
      }});
      const hitLine = new kakao.maps.Polyline({{
        map,
        path,
        strokeColor: "#000000",
        strokeWeight: 14,
        strokeOpacity: 0.01,
        zIndex: 5
      }});
      kakao.maps.event.addListener(hitLine, "click", () => {{
        if (mode !== "delete") return;
        if (segmentDeleted(props.edgeId)) return;
        manualEdits.push({{
          action: "delete_segment",
          edgeId: props.edgeId,
          fromNodeId: props.fromNodeId,
          toNodeId: props.toNodeId,
          segmentType: props.segmentType,
          coords: feature.geometry.coordinates,
          reason: "manual_delete",
          createdAt: new Date().toISOString()
        }});
        visibleLine.setMap(null);
        hitLine.setMap(null);
        persistEdits();
        showToast(`edge #${{props.edgeId}} 삭제 기록`);
      }});
      overlays.push(visibleLine, hitLine);
    }}

    function addManualSegmentOverlay(edit) {{
      const style = styleFor(edit.segmentType);
      const line = new kakao.maps.Polyline({{
        map,
        path: edit.coords.map(latLngFromCoord),
        strokeColor: style.strokeColor,
        strokeWeight: 5,
        strokeOpacity: 0.95,
        zIndex: 7
      }});
      overlays.push(line);
    }}

    function renderVisible() {{
      clearOverlays();
      const box = boundsToBox(map.getBounds());
      const visibleSegments = payload.layers.roadSegments.features
        .filter(feature => !segmentDeleted(feature.properties.edgeId))
        .filter(feature => lineInBox(feature.geometry.coordinates, box));
      const visibleNodeIds = new Set();
      visibleSegments.forEach(feature => {{
        visibleNodeIds.add(feature.properties.fromNodeId);
        visibleNodeIds.add(feature.properties.toNodeId);
        addLine(feature);
      }});
      const visibleNodes = payload.layers.roadNodes.features
        .filter(feature => visibleNodeIds.has(feature.properties.vertexId));
      visibleNodes.forEach(addNode);
      manualEdits
        .filter(edit => edit.action === "add_segment")
        .filter(edit => lineInBox(edit.coords, box))
        .forEach(addManualSegmentOverlay);
      visibleStat.textContent = `visible segments ${{visibleSegments.length}}, nodes ${{visibleNodes.length}}, edits ${{manualEdits.length}}`;
    }}

    function downloadEdits() {{
      const blob = new Blob([JSON.stringify(editDocument(), null, 2) + "\\n"], {{ type: "application/json" }});
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "segment_02c_manual_edits.json";
      anchor.click();
      URL.revokeObjectURL(url);
    }}

    if (!window.kakao || !window.kakao.maps) {{
      mapEl.innerHTML = "<p style='padding:16px'>Kakao Maps SDK를 불러오지 못했습니다.</p>";
    }} else {{
      var map = new kakao.maps.Map(mapEl, {{
        center: new kakao.maps.LatLng(payload.meta.centerLat, payload.meta.centerLon),
        level: 4
      }});
      kakao.maps.event.addListener(map, "idle", renderVisible);
      kakao.maps.event.addListener(map, "click", event => {{
        if (mode !== "add") return;
        const coord = coordFromLatLng(event.latLng);
        const marker = new kakao.maps.Circle({{
          map,
          center: event.latLng,
          radius: 1.8,
          strokeWeight: 2,
          strokeColor: "#16a34a",
          strokeOpacity: 1,
          fillColor: "#22c55e",
          fillOpacity: 0.9,
          zIndex: 9
        }});
        addPreviewMarkers.push(marker);
        if (!selectedStart) {{
          selectedStart = coord;
          showToast("두 번째 지점을 클릭하세요.");
          return;
        }}
        const edit = {{
          action: "add_segment",
          tempEdgeId: `manual-${{Date.now()}}`,
          segmentType: addTypeEl.value,
          coords: [selectedStart, coord],
          reason: "manual_add",
          createdAt: new Date().toISOString()
        }};
        manualEdits.push(edit);
        selectedStart = null;
        addPreviewMarkers.forEach(item => item.setMap(null));
        addPreviewMarkers = [];
        persistEdits();
        renderVisible();
        showToast("새 segment 추가 기록");
      }});
      renderVisible();
    }}

    document.getElementById("mode-pan").addEventListener("click", () => setMode("pan"));
    document.getElementById("mode-delete").addEventListener("click", () => setMode("delete"));
    document.getElementById("mode-add").addEventListener("click", () => setMode("add"));
    document.getElementById("reload-bbox").addEventListener("click", renderVisible);
    document.getElementById("download-edits").addEventListener("click", downloadEdits);
    document.getElementById("copy-edits").addEventListener("click", async () => {{
      await navigator.clipboard.writeText(JSON.stringify(editDocument(), null, 2));
      showToast("manual_edits JSON 복사 완료");
    }});
    document.getElementById("undo-edit").addEventListener("click", () => {{
      manualEdits.pop();
      persistEdits();
      renderVisible();
      showToast("마지막 편집을 되돌렸습니다.");
    }});
    document.getElementById("clear-edits").addEventListener("click", () => {{
      manualEdits = [];
      persistEdits();
      renderVisible();
      showToast("manual_edits 초기화");
    }});
    renderEdits();
  </script>
</body>
</html>
"""
