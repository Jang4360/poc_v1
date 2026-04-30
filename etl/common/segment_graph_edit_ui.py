from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from etl.common.subway_elevator_preview import KAKAO_JAVASCRIPT_KEY, SEGMENT_STYLES


def render_html(
    payload: dict[str, Any],
    *,
    lazy_payload_endpoint: str | None = None,
    dong_areas: list[dict[str, Any]] | None = None,
    default_dong_id: str | None = None,
) -> str:
    meta = payload["meta"]
    summary = payload["summary"]
    district_name = str(meta.get("districtGu") or meta.get("district") or "강서구")
    district_payloads = {} if lazy_payload_endpoint else {district_name: payload}
    district_payloads_json = json.dumps(district_payloads, ensure_ascii=False)
    lazy_payload_endpoint_json = json.dumps(lazy_payload_endpoint or "", ensure_ascii=False)
    dong_areas_json = json.dumps(dong_areas or [], ensure_ascii=False)
    default_area_id_json = json.dumps(default_dong_id or district_name, ensure_ascii=False)
    segment_styles_json = json.dumps(SEGMENT_STYLES, ensure_ascii=False)
    kakao_javascript_key = html.escape(KAKAO_JAVASCRIPT_KEY)
    initial_center_lat = float(meta.get("centerLat") or 35.095)
    initial_center_lon = float(meta.get("centerLon") or 128.872)
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(meta['title'])}</title>
  <style>
    * {{
      box-sizing: border-box;
    }}
    .toolbar .danger {{
      border-color: #dc2626;
      color: #b91c1c;
    }}
    .toolbar .danger.active {{
      background: #dc2626;
      border-color: #dc2626;
      color: #ffffff;
    }}
    html, body, #map {{
      width: 100%;
      height: 100%;
      margin: 0;
      font: 13px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: #0f172a;
    }}
    body {{
      overflow: hidden;
    }}
    button, select {{
      height: 32px;
      border: 1px solid #cbd5e1;
      background: #ffffff;
      color: #0f172a;
      padding: 0 10px;
      font: inherit;
      cursor: pointer;
      min-width: 0;
      white-space: nowrap;
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
      max-width: calc(100vw - 460px);
      padding: 8px;
      background: rgba(255, 255, 255, 0.96);
      border: 1px solid #dbe3ef;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.14);
    }}
    .toolbar button.active {{
      background: #0f172a;
      border-color: #0f172a;
      color: #ffffff;
    }}
    #map.roadview-pick-mode {{
      cursor: crosshair;
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
      width: clamp(420px, 28vw, 560px);
      max-width: calc(100vw - 24px);
      height: 100%;
      background: rgba(255, 255, 255, 0.97);
      border-left: 1px solid #dbe3ef;
      box-shadow: -10px 0 28px rgba(15, 23, 42, 0.16);
      display: grid;
      grid-template-rows: auto auto 1fr auto;
      overflow: hidden;
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
      overflow-wrap: anywhere;
    }}
    .panel-actions {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 6px;
      padding: 10px 14px;
      border-bottom: 1px solid #e2e8f0;
    }}
    .panel-actions .wide {{
      grid-column: 1 / -1;
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
    .edit-note {{
      margin-bottom: 8px;
      color: #475569;
      font-size: 12px;
    }}
    textarea {{
      width: calc(100% - 28px);
      height: 190px;
      margin: 0 14px 14px;
      resize: vertical;
      border: 1px solid #cbd5e1;
      font: 11px/1.35 ui-monospace, SFMono-Regular, Menlo, monospace;
    }}
    .roadview-panel {{
      position: absolute;
      inset: 0;
      z-index: 2;
      display: grid;
      grid-template-rows: auto 1fr;
      background: #ffffff;
    }}
    .roadview-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 10px 12px;
      border-bottom: 1px solid #e2e8f0;
      font-weight: 700;
    }}
    .roadview-close {{
      width: 28px;
      min-width: 28px;
      height: 28px;
      padding: 0;
      font-size: 16px;
      line-height: 1;
    }}
    .roadview-body {{
      position: relative;
      min-height: 0;
    }}
    #roadview-container {{
      width: 100%;
      height: 100%;
    }}
    .roadview-empty {{
      position: absolute;
      inset: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 24px;
      color: #475569;
      text-align: center;
      background: #f8fafc;
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
    @media (max-width: 900px) {{
      .toolbar {{
        max-width: calc(100vw - 24px);
      }}
      .side-panel {{
        width: min(100vw, 420px);
      }}
    }}
  </style>
</head>
<body>
  <div id="map"></div>
  <div class="toolbar">
    <select id="district-select" aria-label="동 선택"></select>
    <button id="mode-pan" class="active" type="button">Select</button>
    <button id="mode-delete" type="button">Delete</button>
    <button id="mode-add" type="button">Add</button>
    <select id="target-type" aria-label="edit target">
      <option value="segment">segment</option>
      <option value="node">node</option>
    </select>
    <select id="segment-type" aria-label="segment type">
      <option value="SIDE_LINE">SIDE_LINE</option>
      <option value="SIDE_WALK">SIDE_WALK</option>
    </select>
    <button id="reload-bbox" type="button">Reload bbox</button>
    <button id="mode-roadview" type="button">Roadview</button>
    <button id="box-delete-drag" class="danger hidden" type="button">Drag</button>
    <button id="box-delete-apply" class="danger hidden" type="button">Delete all</button>
    <span id="visible-stat" class="stat">visible -</span>
  </div>
  <aside class="side-panel">
    <div class="panel-header">
      <h1 id="panel-title">{html.escape(meta['title'])}</h1>
      <p id="panel-source">source: -</p>
      <p id="panel-counts">nodes -, segments -</p>
      <p id="panel-types">types: -</p>
    </div>
    <div class="panel-actions">
      <button id="undo-edit" type="button">Undo</button>
      <button id="save-edits" type="button">Save JSON</button>
      <button id="update-csv" type="button">Edit CSV</button>
      <button id="copy-edits" type="button">Copy JSON</button>
      <button id="clear-edits" class="wide" type="button">Clear</button>
    </div>
    <div id="edits" class="edits"></div>
    <textarea id="edits-json" spellcheck="false" readonly></textarea>
    <div id="roadview-panel" class="roadview-panel hidden">
      <div class="roadview-header">
        <span>Roadview</span>
        <button id="roadview-close" class="roadview-close" type="button" aria-label="Close roadview">x</button>
      </div>
      <div class="roadview-body">
        <div id="roadview-container"></div>
        <div id="roadview-empty" class="roadview-empty">Click the map to open Kakao Roadview.</div>
      </div>
    </div>
  </aside>
  <div id="toast" class="toast hidden"></div>
  <script src="https://dapi.kakao.com/v2/maps/sdk.js?appkey={kakao_javascript_key}"></script>
  <script>
    const districtPayloads = {district_payloads_json};
    const lazyPayloadEndpoint = {lazy_payload_endpoint_json};
    const dongAreas = {dong_areas_json};
    const defaultAreaId = {default_area_id_json};
    let activeAreaId = defaultAreaId;
    let activeDistrict = "";
    let payload = districtPayloads[Object.keys(districtPayloads)[0]] || null;
    const segmentStyles = {segment_styles_json};
    const addableSegmentTypes = ["SIDE_LINE", "SIDE_WALK"];
    const sourceVersion = "02c_graph_materialized";
    const nodeSnapRadiusMeter = 1.0;
    let mode = "pan";
    let map = null;
    let overlays = [];
    let selectedStart = null;
    let addPreviewMarkers = [];
    let manualEdits = [];
    const maxInteractiveSegmentOverlays = 3600;
    const maxInteractiveNodeOverlays = 5000;
    const editPreviewLimit = 80;
    const editJsonPreviewLimit = 120;
    let renderVisibleTimer = null;
    let boxDeleteEnabled = false;
    let selectionPoints = [];
    let selectionShape = null;
    let selectionVertexMarkers = [];
    let roadview = null;
    let roadviewClient = null;
    let roadviewMarker = null;

    const mapEl = document.getElementById("map");
    const visibleStat = document.getElementById("visible-stat");
    const editsEl = document.getElementById("edits");
    const editsJsonEl = document.getElementById("edits-json");
    const toastEl = document.getElementById("toast");
    const districtSelectEl = document.getElementById("district-select");
    const targetTypeEl = document.getElementById("target-type");
    const segmentTypeEl = document.getElementById("segment-type");
    const boxDeleteDragEl = document.getElementById("box-delete-drag");
    const boxDeleteApplyEl = document.getElementById("box-delete-apply");
    const panelTitleEl = document.getElementById("panel-title");
    const panelSourceEl = document.getElementById("panel-source");
    const panelCountsEl = document.getElementById("panel-counts");
    const panelTypesEl = document.getElementById("panel-types");
    const roadviewPanelEl = document.getElementById("roadview-panel");
    const roadviewContainerEl = document.getElementById("roadview-container");
    const roadviewEmptyEl = document.getElementById("roadview-empty");

    function showToast(message) {{
      toastEl.textContent = message;
      toastEl.classList.remove("hidden");
      window.clearTimeout(showToast.timer);
      showToast.timer = window.setTimeout(() => toastEl.classList.add("hidden"), 1800);
    }}

    function updateDeleteBoxControls() {{
      const show = mode === "delete";
      boxDeleteDragEl.classList.toggle("hidden", !show);
      boxDeleteApplyEl.classList.toggle("hidden", !show || selectionPoints.length !== 4);
      boxDeleteDragEl.classList.toggle("active", boxDeleteEnabled);
    }}

    function clearSelectionPolygon() {{
      selectionPoints = [];
      if (selectionShape) {{
        selectionShape.setMap(null);
        selectionShape = null;
      }}
      selectionVertexMarkers.forEach(marker => marker.setMap(null));
      selectionVertexMarkers = [];
      updateDeleteBoxControls();
    }}

    function setBoxDeleteEnabled(enabled) {{
      boxDeleteEnabled = enabled;
      if (!enabled) clearSelectionPolygon();
      updateDeleteBoxControls();
    }}

    function storageKey() {{
      return `segment_02c_manual_edits_v3:${{payload?.meta?.outputGeojson || "pending"}}:${{activeAreaId}}`;
    }}

    function escapeText(value) {{
      return String(value ?? "");
    }}

    function renderPanelHeader() {{
      if (!payload) {{
        panelTitleEl.textContent = "Graph Manual Edit UI";
        panelSourceEl.textContent = "source: loading";
        panelCountsEl.textContent = "nodes -, segments -";
        panelTypesEl.textContent = "types: -";
        return;
      }}
      const summary = payload.summary || {{}};
      const typeText = (summary.segmentTypeCounts || [])
        .map(item => `${{item.name}} ${{item.count}}`)
        .join(", ") || "-";
      const sourceName = (payload.meta.outputGeojson || "segment_02c_graph_materialized.geojson").split("/").pop();
      panelTitleEl.textContent = payload.meta.title || "Graph Manual Edit UI";
      panelSourceEl.textContent = `source: ${{sourceName}}`;
      panelCountsEl.textContent = `nodes ${{summary.nodeCount || 0}}, segments ${{summary.segmentCount || 0}}`;
      panelTypesEl.textContent = `types: ${{typeText}}`;
      const selected = segmentTypeEl.value;
      segmentTypeEl.innerHTML = addableSegmentTypes
        .map(type => `<option value="${{escapeText(type)}}">${{escapeText(type)}}</option>`)
        .join("");
      segmentTypeEl.value = addableSegmentTypes.includes(selected) ? selected : addableSegmentTypes[0];
    }}

    function renderDistrictOptions() {{
      const options = dongAreas.length
        ? dongAreas
        : Object.keys(districtPayloads).map(district => ({{ id: district, name: district }}));
      districtSelectEl.innerHTML = options
        .map(area => `<option value="${{escapeText(area.id)}}">${{escapeText(area.name)}}</option>`)
        .join("");
      districtSelectEl.value = activeAreaId;
    }}

    function loadEdits() {{
      try {{
        const stored = localStorage.getItem(storageKey());
        return stored ? JSON.parse(stored) : [];
      }} catch (_error) {{
        return [];
      }}
    }}

    function persistEdits() {{
      if (!payload) return;
      localStorage.setItem(storageKey(), JSON.stringify(manualEdits));
      renderEdits();
    }}

    function editDocument() {{
      if (!payload) {{
        return {{
          version: sourceVersion,
          districtGu: activeDistrict,
          dongId: activeAreaId,
          districtDong: areaName(activeAreaId),
          sourceHtml: "",
          sourceGeojson: "",
          createdAt: new Date().toISOString(),
          edits: manualEdits
        }};
      }}
      return {{
        version: sourceVersion,
        districtGu: activeDistrict,
        dongId: activeAreaId,
        districtDong: payload.meta.districtDong || areaName(activeAreaId),
        sourceHtml: payload.meta.outputHtml,
        sourceGeojson: payload.meta.outputGeojson,
        createdAt: new Date().toISOString(),
        edits: manualEdits
      }};
    }}

    function areaName(areaId) {{
      const area = dongAreas.find(item => item.id === areaId);
      return area ? area.name : areaId;
    }}

    async function loadPayloadForArea(areaId) {{
      if (!lazyPayloadEndpoint) {{
        return districtPayloads[areaId] || Object.values(districtPayloads)[0] || null;
      }}
      const url = new URL(lazyPayloadEndpoint, window.location.origin);
      url.searchParams.set("dong", areaId);
      const response = await fetch(url.toString());
      const result = await response.json();
      if (!response.ok || !result.ok) {{
        throw new Error(result.error || `HTTP ${{response.status}}`);
      }}
      return result.payload;
    }}

    async function switchDistrict(nextAreaId) {{
      activeAreaId = nextAreaId;
      activeDistrict = areaName(nextAreaId);
      payload = null;
      clearOverlays();
      clearSelectionPolygon();
      setBoxDeleteEnabled(false);
      renderPanelHeader();
      renderEdits();
      visibleStat.textContent = "loading...";
      try {{
        payload = await loadPayloadForArea(nextAreaId);
      }} catch (error) {{
        showToast(`동 데이터를 불러오지 못했습니다: ${{error.message}}`);
        visibleStat.textContent = "load failed";
        return;
      }}
      activeDistrict = payload.meta.districtGu || activeDistrict;
      manualEdits = loadEdits();
      selectedStart = null;
      addPreviewMarkers.forEach(marker => marker.setMap(null));
      addPreviewMarkers = [];
      renderPanelHeader();
      renderEdits();
      if (map) {{
        map.setCenter(new kakao.maps.LatLng(payload.meta.centerLat, payload.meta.centerLon));
        renderAllFeaturesAndFit();
      }}
      showToast(`${{payload.meta.districtDong || areaName(activeAreaId)}} loaded`);
    }}

    function geometryPoint(coord) {{
      return {{ type: "Point", coordinates: coord }};
    }}

    function geometryLine(coords) {{
      return {{ type: "LineString", coordinates: coords }};
    }}

    function distanceMeter(left, right) {{
      const lat1 = left[1] * Math.PI / 180;
      const lat2 = right[1] * Math.PI / 180;
      const deltaLat = (right[1] - left[1]) * Math.PI / 180;
      const deltaLng = (right[0] - left[0]) * Math.PI / 180;
      const a = Math.sin(deltaLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(deltaLng / 2) ** 2;
      return 6371008.8 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    }}

    function nodeRefFromFeature(feature, distance) {{
      const props = feature.properties;
      const coord = feature.geometry.coordinates;
      return {{
        mode: "existing",
        vertexId: props.vertexId,
        sourceNodeKey: props.sourceNodeKey,
        geom: geometryPoint(coord),
        snapDistanceMeter: Number(distance.toFixed(3))
      }};
    }}

    function nodeRefForNew(coord) {{
      const key = `manual_node:${{coord[0].toFixed(8)}}:${{coord[1].toFixed(8)}}`;
      return {{
        mode: "new",
        tempNodeId: key,
        sourceNodeKey: key,
        geom: geometryPoint(coord),
        snapDistanceMeter: null
      }};
    }}

    function activeNodeFeatures() {{
      if (!payload) return [];
      const hiddenNodes = deletedNodeIds();
      const existing = payload.layers.roadNodes.features.filter(feature => !hiddenNodes.has(feature.properties.vertexId));
      const added = manualEdits
        .filter(edit => edit.action === "add_node")
        .map(edit => ({{
          type: "Feature",
          properties: {{
            vertexId: edit.tempNodeId,
            sourceNodeKey: edit.sourceNodeKey,
            degree: 0
          }},
          geometry: edit.geom
        }}));
      return existing.concat(added);
    }}

    function snapNode(coord) {{
      let best = null;
      activeNodeFeatures().forEach(feature => {{
        const distance = distanceMeter(coord, feature.geometry.coordinates);
        if (distance <= nodeSnapRadiusMeter && (!best || distance < best.distance)) {{
          best = {{ feature, distance }};
        }}
      }});
      if (!best) {{
        return {{ coord, node: nodeRefForNew(coord), snapped: false }};
      }}
      return {{
        coord: best.feature.geometry.coordinates,
        node: nodeRefFromFeature(best.feature, best.distance),
        snapped: true
      }};
    }}

    function labelForEdit(edit) {{
      if (edit.action === "delete_segment") return `delete segment #${{edit.edgeId}}`;
      if (edit.action === "delete_node") return `delete node #${{edit.vertexId}}`;
      if (edit.action === "add_node") return `add node ${{edit.tempNodeId}}`;
      if (edit.action === "add_segment") return `add ${{edit.segmentType}}`;
      return edit.action;
    }}

    function summarizeEdit(edit) {{
      if (edit.action === "delete_segment") return `${{edit.reason || "manual"}} edge=${{edit.edgeId}} type=${{edit.segmentType || "-"}}`;
      if (edit.action === "delete_node") return `${{edit.reason || "manual"}} vertex=${{edit.vertexId}} incident=${{(edit.incidentSegmentIds || []).length}}`;
      if (edit.action === "add_node") return `temp=${{edit.tempNodeId}}`;
      if (edit.action === "add_segment") return `temp=${{edit.tempEdgeId}} type=${{edit.segmentType}}`;
      return JSON.stringify(edit);
    }}

    function renderEdits() {{
      editsEl.innerHTML = "";
      if (manualEdits.length > editPreviewLimit) {{
        const note = document.createElement("div");
        note.className = "edit-note";
        note.textContent = `Showing latest ${{editPreviewLimit}} of ${{manualEdits.length}} edits. Full JSON is generated only when needed by Save JSON, Copy JSON, or Edit CSV.`;
        editsEl.appendChild(note);
      }}
      const fragment = document.createDocumentFragment();
      manualEdits.slice(-editPreviewLimit).reverse().forEach((edit, reverseIndex) => {{
        const index = manualEdits.length - reverseIndex;
        const card = document.createElement("div");
        card.className = "edit-card";
        const title = document.createElement("strong");
        title.textContent = `${{index}}. ${{labelForEdit(edit)}}`;
        const detail = document.createElement("code");
        detail.textContent = summarizeEdit(edit);
        card.appendChild(title);
        card.appendChild(detail);
        fragment.appendChild(card);
      }});
      editsEl.appendChild(fragment);
      if (manualEdits.length <= editJsonPreviewLimit) {{
        editsJsonEl.value = JSON.stringify(editDocument(), null, 2);
      }} else {{
        editsJsonEl.value = JSON.stringify({{
          ...editDocument(),
          edits: [],
          editCount: manualEdits.length,
          note: "full JSON is generated only when needed by Save JSON, Copy JSON, or Edit CSV"
        }}, null, 2);
      }}
    }}

    function setMode(nextMode) {{
      mode = nextMode;
      selectedStart = null;
      addPreviewMarkers.forEach(marker => marker.setMap(null));
      addPreviewMarkers = [];
      if (mode !== "delete") {{
        clearSelectionPolygon();
        setBoxDeleteEnabled(false);
      }}
      mapEl.classList.toggle("roadview-pick-mode", mode === "roadview");
      ["pan", "delete", "add", "roadview"].forEach(name => {{
        document.getElementById(`mode-${{name}}`).classList.toggle("active", mode === name);
      }});
      if (mode === "delete") showToast(`Click a ${{targetTypeEl.value}} to delete`);
      else if (mode === "add") showToast(targetTypeEl.value === "node" ? "Click the map to add a node" : "Click two map points to add a segment");
      else if (mode === "roadview") showToast("Click the map to open Roadview");
      else showToast("Select mode");
      updateDeleteBoxControls();
    }}

    function closeRoadviewPanel() {{
      roadviewPanelEl.classList.add("hidden");
      roadviewEmptyEl.classList.remove("hidden");
      roadviewEmptyEl.textContent = "Click the map to open Kakao Roadview.";
      if (roadviewMarker) {{
        roadviewMarker.setMap(null);
        roadviewMarker = null;
      }}
      if (mode === "roadview") setMode("pan");
    }}

    function showRoadviewAt(latLng) {{
      if (!roadviewClient || !window.kakao.maps.Roadview) {{
        showToast("Kakao Roadview is unavailable");
        return;
      }}
      roadviewPanelEl.classList.remove("hidden");
      roadviewEmptyEl.classList.remove("hidden");
      roadviewEmptyEl.textContent = "Searching nearby Roadview...";
      if (!roadview) {{
        roadview = new kakao.maps.Roadview(roadviewContainerEl);
      }}
      if (roadviewMarker) roadviewMarker.setMap(null);
      roadviewMarker = new kakao.maps.Marker({{
        map,
        position: latLng
      }});
      roadviewClient.getNearestPanoId(latLng, 80, panoId => {{
        if (!panoId) {{
          roadviewEmptyEl.classList.remove("hidden");
          roadviewEmptyEl.textContent = "No Kakao Roadview was found near this point.";
          showToast("No nearby Roadview");
          return;
        }}
        roadviewEmptyEl.classList.add("hidden");
        roadview.setPanoId(panoId, latLng);
        window.setTimeout(() => {{
          if (roadview && typeof roadview.relayout === "function") roadview.relayout();
        }}, 0);
      }});
    }}

    function deletedSegmentIds() {{
      const ids = new Set();
      manualEdits.forEach(edit => {{
        if (edit.action === "delete_segment") ids.add(edit.edgeId);
      }});
      return ids;
    }}

    function deletedNodeIds() {{
      return new Set(manualEdits.filter(edit => edit.action === "delete_node").map(edit => edit.vertexId));
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

    function normalizeBox(left, right) {{
      return {{
        minLng: Math.min(left[0], right[0]),
        minLat: Math.min(left[1], right[1]),
        maxLng: Math.max(left[0], right[0]),
        maxLat: Math.max(left[1], right[1])
      }};
    }}

    function boxToBounds(box) {{
      const sw = new kakao.maps.LatLng(box.minLat, box.minLng);
      const ne = new kakao.maps.LatLng(box.maxLat, box.maxLng);
      return new kakao.maps.LatLngBounds(sw, ne);
    }}

    function drawSelectionPolygon() {{
      if (selectionShape) {{
        selectionShape.setMap(null);
        selectionShape = null;
      }}
      selectionVertexMarkers.forEach(marker => marker.setMap(null));
      selectionVertexMarkers = [];
      selectionPoints.forEach((coord, index) => {{
        const marker = new kakao.maps.Circle({{
          map,
          center: latLngFromCoord(coord),
          radius: 2.1,
          strokeWeight: 2,
          strokeColor: "#dc2626",
          strokeOpacity: 1,
          fillColor: "#ffffff",
          fillOpacity: 0.95,
          zIndex: 31
        }});
        selectionVertexMarkers.push(marker);
      }});
      const path = selectionPoints.map(latLngFromCoord);
      if (selectionPoints.length === 4) {{
        selectionShape = new kakao.maps.Polygon({{
          map,
          path,
          strokeWeight: 2,
          strokeColor: "#dc2626",
          strokeOpacity: 0.95,
          strokeStyle: "solid",
          fillColor: "#ef4444",
          fillOpacity: 0.13,
          zIndex: 30
        }});
      }} else if (selectionPoints.length >= 2) {{
        selectionShape = new kakao.maps.Polyline({{
          map,
          path,
          strokeWeight: 2,
          strokeColor: "#dc2626",
          strokeOpacity: 0.95,
          strokeStyle: "solid",
          zIndex: 30
        }});
      }}
      updateDeleteBoxControls();
    }}

    function addSelectionPoint(coord) {{
      if (selectionPoints.length >= 4) {{
        showToast("4 points selected; press Delete all or toggle Drag to redraw");
        return;
      }}
      selectionPoints.push(coord);
      drawSelectionPolygon();
      showToast(selectionPoints.length < 4 ? `${{selectionPoints.length}}/4 points selected` : "4/4 points selected; Delete all applies polygon");
    }}

    function lineSegmentsIntersect(a, b, c, d) {{
      function direction(p, q, r) {{
        return (r[0] - p[0]) * (q[1] - p[1]) - (q[0] - p[0]) * (r[1] - p[1]);
      }}
      function onSegment(p, q, r) {{
        return (
          Math.min(p[0], r[0]) <= q[0] && q[0] <= Math.max(p[0], r[0]) &&
          Math.min(p[1], r[1]) <= q[1] && q[1] <= Math.max(p[1], r[1])
        );
      }}
      const d1 = direction(c, d, a);
      const d2 = direction(c, d, b);
      const d3 = direction(a, b, c);
      const d4 = direction(a, b, d);
      if (((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) && ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0))) {{
        return true;
      }}
      if (d1 === 0 && onSegment(c, a, d)) return true;
      if (d2 === 0 && onSegment(c, b, d)) return true;
      if (d3 === 0 && onSegment(a, c, b)) return true;
      if (d4 === 0 && onSegment(a, d, b)) return true;
      return false;
    }}

    function pointInPolygon(coord, polygon) {{
      const [lng, lat] = coord;
      let inside = false;
      for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i, i += 1) {{
        const [lngI, latI] = polygon[i];
        const [lngJ, latJ] = polygon[j];
        const intersects = ((latI > lat) !== (latJ > lat)) && (lng < (lngJ - lngI) * (lat - latI) / (latJ - latI) + lngI);
        if (intersects) inside = !inside;
      }}
      return inside;
    }}

    function lineTouchesPolygon(coords, polygon) {{
      if (coords.some(coord => pointInPolygon(coord, polygon))) return true;
      const edges = polygon.map((coord, index) => [coord, polygon[(index + 1) % polygon.length]]);
      for (let index = 1; index < coords.length; index += 1) {{
        const left = coords[index - 1];
        const right = coords[index];
        if (edges.some(([edgeLeft, edgeRight]) => lineSegmentsIntersect(left, right, edgeLeft, edgeRight))) {{
          return true;
        }}
      }}
      return false;
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

    function incidentSegmentIds(vertexId) {{
      if (!payload) return [];
      return payload.layers.roadSegments.features
        .filter(feature => feature.properties.fromNodeId === vertexId || feature.properties.toNodeId === vertexId)
        .map(feature => feature.properties.edgeId);
    }}

    function addNode(feature) {{
      const props = feature.properties;
      const coord = feature.geometry.coordinates;
      const marker = new kakao.maps.Circle({{
        map,
        center: latLngFromCoord(coord),
        radius: props.degree > 2 ? 1.45 : 1.05,
        strokeWeight: 1,
        strokeColor: "#111827",
        strokeOpacity: 0.9,
        fillColor: "#111827",
        fillOpacity: 0.95,
        zIndex: 6
      }});
      kakao.maps.event.addListener(marker, "click", () => {{
        if (mode !== "delete" || targetTypeEl.value !== "node") return;
        if (deletedNodeIds().has(props.vertexId)) return;
        manualEdits.push({{
          action: "delete_node",
          entity: "road_node",
          operation: "delete",
          vertexId: props.vertexId,
          sourceNodeKey: props.sourceNodeKey,
          geom: geometryPoint(coord),
          incidentSegmentIds: incidentSegmentIds(props.vertexId),
          note: "Node-only delete for edit display. DB/CSV apply must keep this node if any road_segment still references it.",
          reason: "manual_delete",
          createdAt: new Date().toISOString()
        }});
        marker.setMap(null);
        persistEdits();
        scheduleRenderVisible();
        showToast(`node #${{props.vertexId}} delete recorded`);
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
        if (mode !== "delete" || targetTypeEl.value !== "segment") return;
        if (deletedSegmentIds().has(props.edgeId)) return;
        manualEdits.push({{
          action: "delete_segment",
          entity: "road_segment",
          operation: "delete",
          edgeId: props.edgeId,
          fromNodeId: props.fromNodeId,
          toNodeId: props.toNodeId,
          segmentType: props.segmentType,
          geom: geometryLine(feature.geometry.coordinates),
          reason: "manual_delete",
          createdAt: new Date().toISOString()
        }});
        visibleLine.setMap(null);
        hitLine.setMap(null);
        persistEdits();
        showToast(`segment #${{props.edgeId}} delete recorded`);
      }});
      overlays.push(visibleLine, hitLine);
    }}

    function addManualSegmentOverlay(edit) {{
      const style = styleFor(edit.segmentType);
      const line = new kakao.maps.Polyline({{
        map,
        path: edit.geom.coordinates.map(latLngFromCoord),
        strokeColor: style.strokeColor,
        strokeWeight: 5,
        strokeOpacity: 0.95,
        zIndex: 7
      }});
      overlays.push(line);
    }}

    function addManualNodeOverlay(edit) {{
      const marker = new kakao.maps.Circle({{
        map,
        center: latLngFromCoord(edit.geom.coordinates),
        radius: 1.8,
        strokeWeight: 2,
        strokeColor: "#16a34a",
        strokeOpacity: 1,
        fillColor: "#22c55e",
        fillOpacity: 0.9,
        zIndex: 8
      }});
      overlays.push(marker);
    }}

    function scheduleRenderVisible() {{
      if (renderVisibleTimer) window.clearTimeout(renderVisibleTimer);
      renderVisibleTimer = window.setTimeout(() => {{
        renderVisibleTimer = null;
        renderVisible();
      }}, 90);
    }}

    function renderVisible() {{
      clearOverlays();
      if (!map || !payload) return;
      let box = null;
      try {{
        box = boundsToBox(map.getBounds());
      }} catch (error) {{
        const bbox = payload.meta.bbox || {{}};
        if (
          Number.isFinite(bbox.minLon) &&
          Number.isFinite(bbox.minLat) &&
          Number.isFinite(bbox.maxLon) &&
          Number.isFinite(bbox.maxLat)
        ) {{
          box = {{ minLng: bbox.minLon, minLat: bbox.minLat, maxLng: bbox.maxLon, maxLat: bbox.maxLat }};
        }}
      }}
      if (!box) {{
        visibleStat.textContent = "visible unavailable";
        return;
      }}
      const hiddenSegments = deletedSegmentIds();
      const hiddenNodes = deletedNodeIds();
      const visibleSegments = payload.layers.roadSegments.features
        .filter(feature => !hiddenSegments.has(feature.properties.edgeId))
        .filter(feature => lineInBox(feature.geometry.coordinates, box));
      if (visibleSegments.length > maxInteractiveSegmentOverlays) {{
        visibleStat.textContent = `visible segments ${{visibleSegments.length}}; zoom in for interactive render (limit ${{maxInteractiveSegmentOverlays}}), edits ${{manualEdits.length}}`;
        return;
      }}
      const visibleNodeIds = new Set();
      visibleSegments.forEach(feature => {{
        visibleNodeIds.add(feature.properties.fromNodeId);
        visibleNodeIds.add(feature.properties.toNodeId);
        addLine(feature);
      }});
      const visibleNodes = payload.layers.roadNodes.features
        .filter(feature => visibleNodeIds.has(feature.properties.vertexId))
        .filter(feature => !hiddenNodes.has(feature.properties.vertexId));
      if (visibleNodes.length <= maxInteractiveNodeOverlays) {{
        visibleNodes.forEach(addNode);
      }}
      manualEdits
        .filter(edit => edit.action === "add_segment")
        .filter(edit => lineInBox(edit.geom.coordinates, box))
        .forEach(addManualSegmentOverlay);
      manualEdits
        .filter(edit => edit.action === "add_node")
        .filter(edit => pointInBox(edit.geom.coordinates, box))
        .forEach(addManualNodeOverlay);
      const nodeText = visibleNodes.length > maxInteractiveNodeOverlays ? `${{visibleNodes.length}} (hidden; zoom in)` : visibleNodes.length;
      visibleStat.textContent = `visible segments ${{visibleSegments.length}}, nodes ${{nodeText}}, edits ${{manualEdits.length}}`;
    }}

    function renderAllFeaturesAndFit() {{
      if (!map || !payload) return;
      clearOverlays();
      const hiddenSegments = deletedSegmentIds();
      const hiddenNodes = deletedNodeIds();
      const bounds = new kakao.maps.LatLngBounds();
      let boundsCount = 0;
      const visibleNodeIds = new Set();
      const visibleSegments = payload.layers.roadSegments.features
        .filter(feature => !hiddenSegments.has(feature.properties.edgeId));
      visibleSegments.forEach(feature => {{
        feature.geometry.coordinates.forEach(coord => {{
          bounds.extend(latLngFromCoord(coord));
          boundsCount += 1;
        }});
        visibleNodeIds.add(feature.properties.fromNodeId);
        visibleNodeIds.add(feature.properties.toNodeId);
      }});
      const visibleNodes = payload.layers.roadNodes.features
        .filter(feature => visibleNodeIds.has(feature.properties.vertexId))
        .filter(feature => !hiddenNodes.has(feature.properties.vertexId));
      visibleNodes.forEach(feature => {{
        bounds.extend(latLngFromCoord(feature.geometry.coordinates));
        boundsCount += 1;
      }});
      manualEdits
        .filter(edit => edit.action === "add_segment")
        .forEach(edit => {{
          edit.geom.coordinates.forEach(coord => {{
            bounds.extend(latLngFromCoord(coord));
            boundsCount += 1;
          }});
        }});
      manualEdits
        .filter(edit => edit.action === "add_node")
        .forEach(edit => {{
          bounds.extend(latLngFromCoord(edit.geom.coordinates));
          boundsCount += 1;
        }});
      if (boundsCount > 0) {{
        map.setBounds(bounds);
      }}
      visibleStat.textContent = `fit bbox: segments ${{visibleSegments.length}}, nodes ${{visibleNodes.length}}, edits ${{manualEdits.length}}`;
      scheduleRenderVisible();
    }}

    function deleteFeaturesInSelectionPolygon() {{
      if (!payload || selectionPoints.length !== 4) {{
        showToast("Click exactly 4 polygon points first");
        return;
      }}
      const hiddenSegments = deletedSegmentIds();
      const hiddenNodes = deletedNodeIds();
      const createdAt = new Date().toISOString();
      const polygonMeta = selectionPoints.map(coord => [
        Number(coord[0].toFixed(8)),
        Number(coord[1].toFixed(8))
      ]);
      const segmentEdits = payload.layers.roadSegments.features
        .filter(feature => !hiddenSegments.has(feature.properties.edgeId))
        .filter(feature => lineTouchesPolygon(feature.geometry.coordinates, selectionPoints))
        .map(feature => {{
          const props = feature.properties;
          return {{
            action: "delete_segment",
            entity: "road_segment",
            operation: "delete",
            edgeId: props.edgeId,
            fromNodeId: props.fromNodeId,
            toNodeId: props.toNodeId,
            segmentType: props.segmentType,
            geom: geometryLine(feature.geometry.coordinates),
            selectionPolygon: polygonMeta,
            reason: "manual_polygon_delete",
            createdAt
          }};
        }});
      const nodeEdits = payload.layers.roadNodes.features
        .filter(feature => !hiddenNodes.has(feature.properties.vertexId))
        .filter(feature => pointInPolygon(feature.geometry.coordinates, selectionPoints))
        .map(feature => {{
          const props = feature.properties;
          return {{
            action: "delete_node",
            entity: "road_node",
            operation: "delete",
            vertexId: props.vertexId,
            sourceNodeKey: props.sourceNodeKey,
            geom: geometryPoint(feature.geometry.coordinates),
            incidentSegmentIds: incidentSegmentIds(props.vertexId),
            selectionPolygon: polygonMeta,
            note: "Polygon delete records node removal; CSV apply keeps this node if any remaining road_segment still references it.",
            reason: "manual_polygon_delete",
            createdAt
          }};
        }});
      if (!segmentEdits.length && !nodeEdits.length) {{
        showToast("No node or segment in delete polygon");
        return;
      }}
      manualEdits.push(...segmentEdits, ...nodeEdits);
      persistEdits();
      clearSelectionPolygon();
      scheduleRenderVisible();
      showToast(`polygon delete recorded: ${{segmentEdits.length}} segments, ${{nodeEdits.length}} nodes`);
    }}

    function saveJsonDocument(editDoc) {{
      const blob = new Blob([JSON.stringify(editDoc, null, 2) + "\\n"], {{ type: "application/json" }});
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "segment_02c_manual_edits.json";
      anchor.click();
      URL.revokeObjectURL(url);
      showToast("manual_edits JSON saved");
    }}

    function applyEndpointCandidates() {{
      const endpoints = [];
      if (window.location.protocol === "http:" || window.location.protocol === "https:") {{
        endpoints.push(`${{window.location.origin}}/api/segment-02c/apply-edits`);
      }}
      endpoints.push("http://127.0.0.1:3000/api/segment-02c/apply-edits");
      return [...new Set(endpoints)];
    }}

    async function updateCsv() {{
      const editDoc = editDocument();
      let lastError = null;
      for (const endpoint of applyEndpointCandidates()) {{
        try {{
          showToast("applying edits to CSV...");
          const response = await fetch(endpoint, {{
            method: "POST",
            headers: {{ "Content-Type": "application/json" }},
            body: JSON.stringify(editDoc)
          }});
          const result = await response.json();
          if (!response.ok || !result.ok) {{
            throw new Error(result.error || `HTTP ${{response.status}}`);
          }}
          manualEdits = [];
          persistEdits();
          showToast(`CSV updated: ${{result.csv.segmentCount}} segments`);
          window.setTimeout(() => window.location.reload(), 1200);
          return;
        }} catch (error) {{
          lastError = error;
        }}
      }}
      showToast(`CSV server unavailable; use Save JSON${{lastError ? ": " + lastError.message : ""}}`);
    }}

    if (!window.kakao || !window.kakao.maps) {{
      mapEl.innerHTML = "<p style='padding:16px'>Kakao Maps SDK failed to load.</p>";
    }} else {{
      map = new kakao.maps.Map(mapEl, {{
        center: new kakao.maps.LatLng({initial_center_lat:.7f}, {initial_center_lon:.7f}),
        level: 4
      }});
      if (window.kakao.maps.RoadviewClient) {{
        roadviewClient = new kakao.maps.RoadviewClient();
      }}
      kakao.maps.event.addListener(map, "idle", scheduleRenderVisible);
      kakao.maps.event.addListener(map, "click", event => {{
        if (mode === "roadview") {{
          showRoadviewAt(event.latLng);
          return;
        }}
        if (mode === "delete" && boxDeleteEnabled && payload) {{
          addSelectionPoint(coordFromLatLng(event.latLng));
          return;
        }}
        if (mode !== "add" || !payload) return;
        const coord = coordFromLatLng(event.latLng);
        if (targetTypeEl.value === "node") {{
          const snapped = snapNode(coord);
          if (snapped.snapped) {{
            showToast(`existing node #${{snapped.node.vertexId}} is within ${{snapped.node.snapDistanceMeter}}m`);
            return;
          }}
          const edit = {{
            action: "add_node",
            entity: "road_node",
            operation: "insert",
            tempNodeId: snapped.node.tempNodeId,
            sourceNodeKey: snapped.node.sourceNodeKey,
            geom: snapped.node.geom,
            snapRadiusMeter: nodeSnapRadiusMeter,
            reason: "manual_add",
            createdAt: new Date().toISOString()
          }};
          manualEdits.push(edit);
          persistEdits();
          scheduleRenderVisible();
          showToast("node add recorded");
          return;
        }}
        const endpoint = snapNode(coord);
        const marker = new kakao.maps.Circle({{
          map,
          center: latLngFromCoord(endpoint.coord),
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
          selectedStart = endpoint;
          showToast(endpoint.snapped ? `start snapped to node #${{endpoint.node.vertexId}}` : "Click the second point");
          return;
        }}
        const lineCoords = [selectedStart.coord, endpoint.coord];
        const edit = {{
          action: "add_segment",
          entity: "road_segment",
          operation: "insert",
          tempEdgeId: `manual-segment-${{Date.now()}}`,
          segmentType: segmentTypeEl.value,
          fromNode: selectedStart.node,
          toNode: endpoint.node,
          geom: geometryLine(lineCoords),
          snapRadiusMeter: nodeSnapRadiusMeter,
          reason: "manual_add",
          createdAt: new Date().toISOString()
        }};
        manualEdits.push(edit);
        selectedStart = null;
        addPreviewMarkers.forEach(item => item.setMap(null));
        addPreviewMarkers = [];
        persistEdits();
        scheduleRenderVisible();
        showToast("segment add recorded");
      }});
    }}

    document.getElementById("mode-pan").addEventListener("click", () => setMode("pan"));
    document.getElementById("mode-delete").addEventListener("click", () => setMode("delete"));
    document.getElementById("mode-add").addEventListener("click", () => setMode("add"));
    document.getElementById("mode-roadview").addEventListener("click", () => setMode("roadview"));
    document.getElementById("roadview-close").addEventListener("click", closeRoadviewPanel);
    document.getElementById("reload-bbox").addEventListener("click", renderAllFeaturesAndFit);
    boxDeleteDragEl.addEventListener("click", () => {{
      if (mode !== "delete") setMode("delete");
      setBoxDeleteEnabled(!boxDeleteEnabled);
      showToast(boxDeleteEnabled ? "Click polygon points on the map" : "Polygon delete off");
    }});
    boxDeleteApplyEl.addEventListener("click", deleteFeaturesInSelectionPolygon);
    document.getElementById("save-edits").addEventListener("click", () => saveJsonDocument(editDocument()));
    document.getElementById("update-csv").addEventListener("click", updateCsv);
    document.getElementById("copy-edits").addEventListener("click", async () => {{
      await navigator.clipboard.writeText(JSON.stringify(editDocument(), null, 2));
      showToast("manual_edits JSON copied");
    }});
    document.getElementById("undo-edit").addEventListener("click", () => {{
      manualEdits.pop();
      persistEdits();
      scheduleRenderVisible();
      showToast("last edit removed");
    }});
    document.getElementById("clear-edits").addEventListener("click", () => {{
      manualEdits = [];
      persistEdits();
      scheduleRenderVisible();
      showToast("manual_edits cleared");
    }});
    districtSelectEl.addEventListener("change", event => switchDistrict(event.target.value));
    targetTypeEl.addEventListener("change", () => {{
      selectedStart = null;
      addPreviewMarkers.forEach(marker => marker.setMap(null));
      addPreviewMarkers = [];
      showToast(`target: ${{targetTypeEl.value}}`);
    }});
    renderDistrictOptions();
    renderPanelHeader();
    renderEdits();
    if (districtSelectEl.value) {{
      switchDistrict(districtSelectEl.value);
    }}
  </script>
</body>
</html>
"""
