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
    source_name = html.escape(Path(meta.get("outputGeojson", "segment_02c_graph_materialized.geojson")).name)
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
    button, select {{
      height: 32px;
      border: 1px solid #cbd5e1;
      background: #ffffff;
      color: #0f172a;
      padding: 0 10px;
      font: inherit;
      cursor: pointer;
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
      height: 190px;
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
    <span id="visible-stat" class="stat">visible -</span>
  </div>
  <aside class="side-panel">
    <div class="panel-header">
      <h1>{html.escape(meta['title'])}</h1>
      <p>source: {source_name}</p>
      <p>nodes {summary['nodeCount']}, segments {summary['segmentCount']}</p>
      <p>types: {html.escape(type_text)}</p>
    </div>
    <div class="panel-actions">
      <button id="copy-edits" type="button">Copy JSON</button>
      <button id="download-edits" type="button">Save JSON + CSV</button>
      <button id="undo-edit" type="button">Undo</button>
      <button id="clear-edits" type="button">Clear</button>
    </div>
    <div id="edits" class="edits"></div>
    <textarea id="edits-json" spellcheck="false" readonly></textarea>
  </aside>
  <div id="toast" class="toast hidden"></div>
  <script src="https://dapi.kakao.com/v2/maps/sdk.js?appkey={kakao_javascript_key}"></script>
  <script>
    const payload = {payload_json};
    const segmentStyles = {segment_styles_json};
    const storageKey = `segment_02c_manual_edits_v3:${{payload.meta.outputGeojson}}`;
    const sourceVersion = "02c_graph_materialized";
    const nodeSnapRadiusMeter = 1.0;
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
    const targetTypeEl = document.getElementById("target-type");
    const segmentTypeEl = document.getElementById("segment-type");

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

    function renderEdits() {{
      editsEl.innerHTML = "";
      manualEdits.slice().reverse().forEach((edit, reverseIndex) => {{
        const index = manualEdits.length - reverseIndex;
        const card = document.createElement("div");
        card.className = "edit-card";
        card.innerHTML = `<strong>${{index}}. ${{labelForEdit(edit)}}</strong><code>${{JSON.stringify(edit)}}</code>`;
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
      if (mode === "delete") showToast(`Click a ${{targetTypeEl.value}} to delete`);
      else if (mode === "add") showToast(targetTypeEl.value === "node" ? "Click the map to add a node" : "Click two map points to add a segment");
      else showToast("Select mode");
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
        renderVisible();
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

    function renderVisible() {{
      clearOverlays();
      const box = boundsToBox(map.getBounds());
      const hiddenSegments = deletedSegmentIds();
      const hiddenNodes = deletedNodeIds();
      const visibleSegments = payload.layers.roadSegments.features
        .filter(feature => !hiddenSegments.has(feature.properties.edgeId))
        .filter(feature => lineInBox(feature.geometry.coordinates, box));
      const visibleNodeIds = new Set();
      visibleSegments.forEach(feature => {{
        visibleNodeIds.add(feature.properties.fromNodeId);
        visibleNodeIds.add(feature.properties.toNodeId);
        addLine(feature);
      }});
      const visibleNodes = payload.layers.roadNodes.features
        .filter(feature => visibleNodeIds.has(feature.properties.vertexId))
        .filter(feature => !hiddenNodes.has(feature.properties.vertexId));
      visibleNodes.forEach(addNode);
      manualEdits
        .filter(edit => edit.action === "add_segment")
        .filter(edit => lineInBox(edit.geom.coordinates, box))
        .forEach(addManualSegmentOverlay);
      manualEdits
        .filter(edit => edit.action === "add_node")
        .filter(edit => pointInBox(edit.geom.coordinates, box))
        .forEach(addManualNodeOverlay);
      visibleStat.textContent = `visible segments ${{visibleSegments.length}}, nodes ${{visibleNodes.length}}, edits ${{manualEdits.length}}`;
    }}

    function fallbackDownloadEdits(editDoc) {{
      const blob = new Blob([JSON.stringify(editDoc, null, 2) + "\\n"], {{ type: "application/json" }});
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "segment_02c_manual_edits.json";
      anchor.click();
      URL.revokeObjectURL(url);
    }}

    function applyEndpointCandidates() {{
      const endpoints = [];
      if (window.location.protocol === "http:" || window.location.protocol === "https:") {{
        endpoints.push(`${{window.location.origin}}/api/segment-02c/apply-edits`);
      }}
      endpoints.push("http://127.0.0.1:3000/api/segment-02c/apply-edits");
      return [...new Set(endpoints)];
    }}

    async function downloadEdits() {{
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
      fallbackDownloadEdits(editDoc);
      showToast(`CSV server unavailable; JSON downloaded${{lastError ? ": " + lastError.message : ""}}`);
    }}

    if (!window.kakao || !window.kakao.maps) {{
      mapEl.innerHTML = "<p style='padding:16px'>Kakao Maps SDK failed to load.</p>";
    }} else {{
      var map = new kakao.maps.Map(mapEl, {{
        center: new kakao.maps.LatLng(payload.meta.centerLat, payload.meta.centerLon),
        level: 4
      }});
      kakao.maps.event.addListener(map, "idle", renderVisible);
      kakao.maps.event.addListener(map, "click", event => {{
        if (mode !== "add") return;
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
          renderVisible();
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
        renderVisible();
        showToast("segment add recorded");
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
      showToast("manual_edits JSON copied");
    }});
    document.getElementById("undo-edit").addEventListener("click", () => {{
      manualEdits.pop();
      persistEdits();
      renderVisible();
      showToast("last edit removed");
    }});
    document.getElementById("clear-edits").addEventListener("click", () => {{
      manualEdits = [];
      persistEdits();
      renderVisible();
      showToast("manual_edits cleared");
    }});
    targetTypeEl.addEventListener("change", () => {{
      selectedStart = null;
      addPreviewMarkers.forEach(marker => marker.setMap(null));
      addPreviewMarkers = [];
      showToast(`target: ${{targetTypeEl.value}}`);
    }});
    renderEdits();
  </script>
</body>
</html>
"""
