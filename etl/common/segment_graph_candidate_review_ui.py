from __future__ import annotations

import html
import json
from typing import Any

from etl.common.subway_elevator_preview import KAKAO_JAVASCRIPT_KEY


def render_html(candidate_document: dict[str, Any]) -> str:
    payload_json = json.dumps(candidate_document, ensure_ascii=False)
    title = "Gangseo 02C Auto Candidate Review"
    counts = candidate_document.get("meta", {}).get("candidateCounts", {})
    context_counts = candidate_document.get("meta", {}).get("contextCounts", {})
    count_text = (
        f"delete {counts.get('delete_segment', 0)}, "
        f"add {counts.get('add_segment', 0)}, total {counts.get('total', 0)}, "
        f"context segments {context_counts.get('segments', 0)}"
    )
    return (
        _HTML_TEMPLATE.replace("__TITLE__", html.escape(title))
        .replace("__COUNT_TEXT__", html.escape(count_text))
        .replace("__KAKAO_KEY__", html.escape(KAKAO_JAVASCRIPT_KEY))
        .replace("__CANDIDATE_DOCUMENT__", payload_json)
    )


def render_diff_html(candidate_document: dict[str, Any]) -> str:
    payload_json = json.dumps(candidate_document, ensure_ascii=False)
    title = "Gangseo 02C Auto Candidate Diff Preview"
    counts = candidate_document.get("meta", {}).get("candidateCounts", {})
    motifs = candidate_document.get("meta", {}).get("motifCounts", {})
    count_text = (
        f"delete {counts.get('delete_segment', 0)}, "
        f"add {counts.get('add_segment', 0)}, total {counts.get('total', 0)}"
    )
    motif_text = ", ".join(f"{key} {value}" for key, value in sorted(motifs.items())) or "-"
    return (
        _DIFF_HTML_TEMPLATE.replace("__TITLE__", html.escape(title))
        .replace("__COUNT_TEXT__", html.escape(count_text))
        .replace("__MOTIF_TEXT__", html.escape(motif_text))
        .replace("__KAKAO_KEY__", html.escape(KAKAO_JAVASCRIPT_KEY))
        .replace("__CANDIDATE_DOCUMENT__", payload_json)
    )


_HTML_TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>__TITLE__</title>
  <style>
    html, body, #map {
      width: 100%;
      height: 100%;
      margin: 0;
      font: 13px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: #0f172a;
    }
    button, input, select {
      font: inherit;
    }
    button {
      height: 32px;
      border: 1px solid #cbd5e1;
      background: #fff;
      color: #0f172a;
      padding: 0 10px;
      cursor: pointer;
    }
    button.active {
      background: #0f172a;
      border-color: #0f172a;
      color: #fff;
    }
    .toolbar {
      position: absolute;
      z-index: 800;
      top: 12px;
      left: 12px;
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 8px;
      background: rgba(255, 255, 255, 0.96);
      border: 1px solid #dbe3ef;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.14);
    }
    .toolbar .stat {
      color: #475569;
      padding: 0 6px;
      white-space: nowrap;
    }
    .side-panel {
      position: absolute;
      z-index: 810;
      top: 0;
      right: 0;
      width: 420px;
      height: 100%;
      background: rgba(255, 255, 255, 0.98);
      border-left: 1px solid #dbe3ef;
      box-shadow: -10px 0 28px rgba(15, 23, 42, 0.16);
      display: grid;
      grid-template-rows: auto auto auto auto 1fr auto;
    }
    .panel-header {
      padding: 14px 14px 10px;
      border-bottom: 1px solid #e2e8f0;
    }
    .panel-header h1 {
      margin: 0 0 6px;
      font-size: 16px;
    }
    .panel-header p {
      margin: 0 0 4px;
      color: #475569;
    }
    .panel-actions {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 6px;
      padding: 10px 14px;
      border-bottom: 1px solid #e2e8f0;
    }
    .filters {
      display: flex;
      gap: 6px;
      padding: 10px 14px;
      border-bottom: 1px solid #e2e8f0;
    }
    .filters button {
      flex: 1;
    }
    .legend {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      padding: 8px 14px;
      color: #475569;
      border-bottom: 1px solid #e2e8f0;
      font-size: 12px;
    }
    .legend-item {
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }
    .swatch {
      width: 18px;
      height: 3px;
      display: inline-block;
    }
    .candidate-list {
      overflow: auto;
      padding: 10px 14px;
    }
    .candidate-card {
      border: 1px solid #e2e8f0;
      background: #f8fafc;
      padding: 8px;
      margin-bottom: 8px;
      cursor: pointer;
    }
    .candidate-card.selected {
      border-color: #0f172a;
      background: #eef2ff;
    }
    .candidate-card.approved {
      border-color: #16a34a;
      background: #f0fdf4;
    }
    .candidate-row {
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 4px;
    }
    .candidate-title {
      flex: 1;
      font-weight: 700;
    }
    .candidate-meta {
      color: #475569;
      font-size: 12px;
      word-break: break-all;
    }
    .json-preview {
      width: calc(100% - 28px);
      height: 170px;
      margin: 0 14px 14px;
      resize: vertical;
      border: 1px solid #cbd5e1;
      font: 11px/1.35 ui-monospace, SFMono-Regular, Menlo, monospace;
    }
    .toast {
      position: absolute;
      z-index: 820;
      left: 12px;
      bottom: 12px;
      max-width: calc(100vw - 450px);
      padding: 9px 12px;
      color: #fff;
      background: rgba(15, 23, 42, 0.92);
      box-shadow: 0 8px 20px rgba(15, 23, 42, 0.16);
    }
    .hidden {
      display: none;
    }
  </style>
</head>
<body>
  <div id="map"></div>
  <div class="toolbar">
    <button id="prev-candidate" type="button">Prev</button>
    <button id="next-candidate" type="button">Next</button>
    <button id="toggle-selected" type="button">Toggle Pass</button>
    <span id="review-stat" class="stat">-</span>
  </div>
  <aside class="side-panel">
    <div class="panel-header">
      <h1>__TITLE__</h1>
      <p>__COUNT_TEXT__</p>
      <p>선택한 후보 1개와 주변 기존 CSV 라인을 함께 보여줍니다.</p>
    </div>
    <div class="panel-actions">
      <button id="save-review" type="button">Save Review JSON</button>
      <button id="download-approved" type="button">Download Approved</button>
      <button id="copy-approved" type="button">Copy Approved</button>
      <button id="clear-review" type="button">Clear Checks</button>
    </div>
    <div class="filters">
      <button class="active" id="filter-all" type="button">All</button>
      <button id="filter-pending" type="button">Pending</button>
      <button id="filter-approved" type="button">Passed</button>
    </div>
    <div class="filters">
      <button class="active" id="action-all" type="button">All Actions</button>
      <button id="action-delete" type="button">Delete</button>
      <button id="action-add" type="button">Add</button>
    </div>
    <div class="legend">
      <span class="legend-item"><span class="swatch" style="background:#991b1b"></span>기존 SIDE_LINE</span>
      <span class="legend-item"><span class="swatch" style="background:#2563eb"></span>기존 SIDE_WALK</span>
      <span class="legend-item"><span class="swatch" style="background:#ef4444"></span>삭제 후보</span>
      <span class="legend-item"><span class="swatch" style="background:#0ea5e9"></span>추가 후보</span>
    </div>
    <div id="candidate-list" class="candidate-list"></div>
    <textarea id="json-preview" class="json-preview" spellcheck="false" readonly></textarea>
  </aside>
  <div id="toast" class="toast hidden"></div>
  <script src="https://dapi.kakao.com/v2/maps/sdk.js?appkey=__KAKAO_KEY__"></script>
  <script>
    const candidateDocument = __CANDIDATE_DOCUMENT__;
    const storageKey = `gangseo_02c_candidate_review:${candidateDocument.createdAt}`;
    let filterMode = "all";
    let actionMode = "all";
    let selectedIndex = 0;
    let overlays = [];
    let reviewState = loadReviewState();

    const mapEl = document.getElementById("map");
    const listEl = document.getElementById("candidate-list");
    const previewEl = document.getElementById("json-preview");
    const statEl = document.getElementById("review-stat");
    const toastEl = document.getElementById("toast");

    function showToast(message) {
      toastEl.textContent = message;
      toastEl.classList.remove("hidden");
      window.clearTimeout(showToast.timer);
      showToast.timer = window.setTimeout(() => toastEl.classList.add("hidden"), 1800);
    }

    function loadReviewState() {
      const base = {};
      candidateDocument.edits.forEach(edit => {
        const review = edit.review || {};
        base[edit.reviewId] = {
          approved: Boolean(review.approved),
          status: review.status || "pending",
          reviewedAt: review.reviewedAt || null
        };
      });
      try {
        const stored = localStorage.getItem(storageKey);
        return stored ? { ...base, ...JSON.parse(stored) } : base;
      } catch (_error) {
        return base;
      }
    }

    function persistReviewState() {
      localStorage.setItem(storageKey, JSON.stringify(reviewState));
      render();
    }

    function latLngFromCoord(coord) {
      return new kakao.maps.LatLng(coord[1], coord[0]);
    }

    function candidateCoords(edit) {
      if (!edit) return [];
      const geom = edit.geom || {};
      if (geom.type === "LineString") return geom.coordinates;
      if (geom.type === "Point") return [geom.coordinates];
      return [];
    }

    function candidateCenter(edit) {
      const coords = candidateCoords(edit);
      if (!coords.length) return [128.9, 35.15];
      const lng = coords.reduce((sum, coord) => sum + coord[0], 0) / coords.length;
      const lat = coords.reduce((sum, coord) => sum + coord[1], 0) / coords.length;
      return [lng, lat];
    }

    function candidateBBox(edit, padding) {
      const coords = candidateCoords(edit);
      if (!coords.length) return null;
      const lons = coords.map(coord => coord[0]);
      const lats = coords.map(coord => coord[1]);
      return {
        minLng: Math.min(...lons) - padding,
        minLat: Math.min(...lats) - padding,
        maxLng: Math.max(...lons) + padding,
        maxLat: Math.max(...lats) + padding
      };
    }

    function pointInBox(coord, box) {
      return coord[0] >= box.minLng && coord[0] <= box.maxLng && coord[1] >= box.minLat && coord[1] <= box.maxLat;
    }

    function lineInBox(coords, box) {
      return coords.some(coord => pointInBox(coord, box));
    }

    function baseStyleFor(segmentType) {
      if (segmentType === "SIDE_WALK") return { color: "#2563eb", weight: 3, opacity: 0.42 };
      return { color: "#991b1b", weight: 3, opacity: 0.34 };
    }

    function styleFor(edit) {
      if (edit.action === "delete_segment") {
        return { color: "#ef4444", weight: 5, opacity: 0.95 };
      }
      if (edit.action === "add_segment") {
        return { color: "#2563eb", weight: 5, opacity: 0.95 };
      }
      return { color: "#111827", weight: 4, opacity: 0.9 };
    }

    function reviewFor(edit) {
      return reviewState[edit.reviewId] || { approved: false, status: "pending", reviewedAt: null };
    }

    function reviewedDocument() {
      const edits = candidateDocument.edits.map(edit => {
        const review = reviewFor(edit);
        return {
          ...edit,
          review: {
            approved: Boolean(review.approved),
            status: review.approved ? "approved" : "pending",
            reviewedAt: review.reviewedAt || null
          }
        };
      });
      const approvedCount = edits.filter(edit => edit.review.approved).length;
      return {
        ...candidateDocument,
        reviewedAt: new Date().toISOString(),
        meta: {
          ...candidateDocument.meta,
          reviewCounts: {
            approved: approvedCount,
            pending: edits.length - approvedCount,
            total: edits.length
          }
        },
        edits
      };
    }

    function approvedDocument() {
      const reviewed = reviewedDocument();
      return {
        version: "02c_auto_edit_approved_manual_edits",
        sourceHtml: reviewed.sourceHtml,
        sourceGeojson: reviewed.sourceGeojson,
        createdAt: new Date().toISOString(),
        meta: {
          ...reviewed.meta,
          sourceCandidateJson: reviewed.meta.outputJson || "gangseo_02c_auto_manual_edit_candidates.json",
          approvedOnly: true
        },
        edits: reviewed.edits.filter(edit => edit.review.approved)
      };
    }

    function filteredEdits() {
      let edits = candidateDocument.edits;
      if (actionMode === "delete") {
        edits = edits.filter(edit => edit.action === "delete_segment");
      } else if (actionMode === "add") {
        edits = edits.filter(edit => edit.action === "add_segment");
      }
      if (filterMode === "approved") {
        return edits.filter(edit => reviewFor(edit).approved);
      }
      if (filterMode === "pending") {
        return edits.filter(edit => !reviewFor(edit).approved);
      }
      return edits;
    }

    function labelFor(edit) {
      if (edit.action === "delete_segment") return `delete #${edit.edgeId}`;
      if (edit.action === "add_segment") return `add ${edit.segmentType}`;
      return edit.action;
    }

    function selectCandidate(index) {
      const edits = candidateDocument.edits;
      if (!edits.length) return;
      selectedIndex = Math.max(0, Math.min(index, edits.length - 1));
      const edit = edits[selectedIndex];
      const center = candidateCenter(edit);
      map.panTo(latLngFromCoord(center));
      render();
    }

    function toggleReview(index) {
      const edit = candidateDocument.edits[index];
      if (!edit) return;
      const current = reviewFor(edit);
      reviewState[edit.reviewId] = {
        approved: !current.approved,
        status: current.approved ? "pending" : "approved",
        reviewedAt: current.approved ? null : new Date().toISOString()
      };
      persistReviewState();
    }

    function clearOverlays() {
      overlays.forEach(overlay => overlay.setMap(null));
      overlays = [];
    }

    function drawBaseContext() {
      const selected = candidateDocument.edits[selectedIndex];
      if (!selected) return;
      const box = candidateBBox(selected, 0.00075);
      if (!box || !candidateDocument.context) return;
      const segments = candidateDocument.context.roadSegments.features
        .filter(feature => lineInBox(feature.geometry.coordinates, box));
      segments.forEach(feature => {
        const style = baseStyleFor(feature.properties.segmentType);
        const line = new kakao.maps.Polyline({
          map,
          path: feature.geometry.coordinates.map(latLngFromCoord),
          strokeColor: style.color,
          strokeWeight: style.weight,
          strokeOpacity: style.opacity,
          zIndex: 2
        });
        overlays.push(line);
      });
    }

    function drawCandidate(edit, index) {
      const coords = candidateCoords(edit);
      const style = styleFor(edit);
      if (!coords.length) return;
      if ((edit.geom || {}).type === "LineString") {
        const line = new kakao.maps.Polyline({
          map,
          path: coords.map(latLngFromCoord),
          strokeColor: style.color,
          strokeWeight: index === selectedIndex ? style.weight + 3 : style.weight,
          strokeOpacity: style.opacity,
          zIndex: index === selectedIndex ? 12 : 8
        });
        kakao.maps.event.addListener(line, "click", () => selectCandidate(index));
        overlays.push(line);
      }
      const center = candidateCenter(edit);
      const marker = new kakao.maps.Circle({
        map,
        center: latLngFromCoord(center),
        radius: index === selectedIndex ? 5.5 : 3.0,
        strokeWeight: 2,
        strokeColor: reviewFor(edit).approved ? "#16a34a" : style.color,
        strokeOpacity: 1,
        fillColor: reviewFor(edit).approved ? "#22c55e" : style.color,
        fillOpacity: 0.75,
        zIndex: index === selectedIndex ? 13 : 9
      });
      kakao.maps.event.addListener(marker, "click", () => selectCandidate(index));
      overlays.push(marker);
    }

    function renderMap() {
      clearOverlays();
      if (!candidateDocument.edits.length) return;
      drawBaseContext();
      drawCandidate(candidateDocument.edits[selectedIndex], selectedIndex);
    }

    function renderList() {
      const visible = filteredEdits();
      listEl.innerHTML = "";
      visible.forEach(edit => {
        const index = candidateDocument.edits.indexOf(edit);
        const review = reviewFor(edit);
        const card = document.createElement("div");
        card.className = `candidate-card ${index === selectedIndex ? "selected" : ""} ${review.approved ? "approved" : ""}`;
        card.innerHTML = `
          <div class="candidate-row">
            <input type="checkbox" ${review.approved ? "checked" : ""} aria-label="review pass" />
            <span class="candidate-title">${index + 1}. ${labelFor(edit)}</span>
            <span>${Number(edit.confidence || 0).toFixed(3)}</span>
          </div>
          <div class="candidate-meta">${edit.motif || ""} ${edit.reason || ""}</div>
          <div class="candidate-meta">${JSON.stringify(edit.evidence || {})}</div>
          <div class="candidate-meta">${edit.reviewId}</div>
        `;
        card.addEventListener("click", event => {
          if (event.target.tagName !== "INPUT") selectCandidate(index);
        });
        card.querySelector("input").addEventListener("change", () => toggleReview(index));
        listEl.appendChild(card);
      });
    }

    function renderStats() {
      const doc = reviewedDocument();
      const counts = doc.meta.reviewCounts;
      const context = candidateDocument.meta.contextCounts || {};
      statEl.textContent = `passed ${counts.approved}, pending ${counts.pending}, total ${counts.total}, context ${context.segments || 0}`;
      previewEl.value = JSON.stringify(approvedDocument(), null, 2);
    }

    function render() {
      renderMap();
      renderList();
      renderStats();
    }

    function setFilter(nextFilter) {
      filterMode = nextFilter;
      ["all", "pending", "approved"].forEach(name => {
        document.getElementById(`filter-${name}`).classList.toggle("active", filterMode === name);
      });
      render();
    }

    function setActionFilter(nextFilter) {
      actionMode = nextFilter;
      ["all", "delete", "add"].forEach(name => {
        document.getElementById(`action-${name}`).classList.toggle("active", actionMode === name);
      });
      render();
    }

    function downloadJson(doc, filename) {
      const blob = new Blob([JSON.stringify(doc, null, 2) + "\\n"], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      anchor.click();
      URL.revokeObjectURL(url);
    }

    async function saveReview() {
      const reviewed = reviewedDocument();
      const endpoints = [];
      if (window.location.protocol === "http:" || window.location.protocol === "https:") {
        endpoints.push(`${window.location.origin}/api/gangseo-auto-edit/save-review`);
      }
      endpoints.push("http://127.0.0.1:3000/api/gangseo-auto-edit/save-review");
      let lastError = null;
      for (const endpoint of [...new Set(endpoints)]) {
        try {
          const response = await fetch(endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(reviewed)
          });
          const result = await response.json();
          if (!response.ok || !result.ok) throw new Error(result.error || `HTTP ${response.status}`);
          showToast(`saved ${result.review.approvedCount} approved edits`);
          return;
        } catch (error) {
          lastError = error;
        }
      }
      downloadJson(reviewed, "gangseo_02c_auto_manual_edit_candidates.reviewed.json");
      showToast(`server unavailable; reviewed JSON downloaded${lastError ? ": " + lastError.message : ""}`);
    }

    if (!window.kakao || !window.kakao.maps) {
      mapEl.innerHTML = "<p style='padding:16px'>Kakao Maps SDK failed to load.</p>";
    } else {
      const firstCenter = candidateCenter(candidateDocument.edits[0] || {});
      var map = new kakao.maps.Map(mapEl, {
        center: latLngFromCoord(firstCenter),
        level: 4
      });
      render();
    }

    document.getElementById("prev-candidate").addEventListener("click", () => selectCandidate(selectedIndex - 1));
    document.getElementById("next-candidate").addEventListener("click", () => selectCandidate(selectedIndex + 1));
    document.getElementById("toggle-selected").addEventListener("click", () => toggleReview(selectedIndex));
    document.getElementById("save-review").addEventListener("click", saveReview);
    document.getElementById("download-approved").addEventListener("click", () => downloadJson(approvedDocument(), "gangseo_02c_approved_manual_edits.json"));
    document.getElementById("copy-approved").addEventListener("click", async () => {
      await navigator.clipboard.writeText(JSON.stringify(approvedDocument(), null, 2));
      showToast("approved JSON copied");
    });
    document.getElementById("clear-review").addEventListener("click", () => {
      reviewState = {};
      candidateDocument.edits.forEach(edit => {
        reviewState[edit.reviewId] = { approved: false, status: "pending", reviewedAt: null };
      });
      persistReviewState();
      showToast("review checks cleared");
    });
    document.getElementById("filter-all").addEventListener("click", () => setFilter("all"));
    document.getElementById("filter-pending").addEventListener("click", () => setFilter("pending"));
    document.getElementById("filter-approved").addEventListener("click", () => setFilter("approved"));
    document.getElementById("action-all").addEventListener("click", () => setActionFilter("all"));
    document.getElementById("action-delete").addEventListener("click", () => setActionFilter("delete"));
    document.getElementById("action-add").addEventListener("click", () => setActionFilter("add"));
  </script>
</body>
</html>
"""


_DIFF_HTML_TEMPLATE = """<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>__TITLE__</title>
  <style>
    html, body, #map {
      width: 100%;
      height: 100%;
      margin: 0;
      font: 13px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: #0f172a;
    }
    .panel {
      position: absolute;
      z-index: 800;
      top: 12px;
      left: 12px;
      width: min(620px, calc(100vw - 24px));
      padding: 12px 14px;
      background: rgba(255, 255, 255, 0.96);
      border: 1px solid #dbe3ef;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.14);
    }
    .panel h1 {
      margin: 0 0 6px;
      font-size: 16px;
    }
    .panel p {
      margin: 0 0 6px;
      color: #475569;
    }
    .legend {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }
    .legend-item {
      display: inline-flex;
      align-items: center;
      gap: 5px;
    }
    .swatch {
      width: 22px;
      height: 4px;
      display: inline-block;
    }
    .warning {
      padding: 8px 10px;
      background: #eff6ff;
      border: 1px solid #93c5fd;
      color: #1d4ed8;
    }
  </style>
</head>
<body>
  <div id="map"></div>
  <section class="panel">
    <h1>__TITLE__</h1>
    <p>__COUNT_TEXT__</p>
    <p>motifs: __MOTIF_TEXT__</p>
    <p id="warning" class="warning" hidden></p>
    <div class="legend">
      <span class="legend-item"><span class="swatch" style="background:#b91c1c;opacity:.35"></span>existing</span>
      <span class="legend-item"><span class="swatch" style="background:#7c3aed"></span>delete candidate</span>
      <span class="legend-item"><span class="swatch" style="background:#16a34a"></span>add candidate</span>
    </div>
  </section>
  <script src="https://dapi.kakao.com/v2/maps/sdk.js?appkey=__KAKAO_KEY__"></script>
  <script>
    const candidateDocument = __CANDIDATE_DOCUMENT__;
    const warningEl = document.getElementById("warning");
    const mapEl = document.getElementById("map");

    function showWarning(message) {
      warningEl.hidden = false;
      warningEl.innerHTML = message;
    }

    function latLngFromCoord(coord) {
      return new kakao.maps.LatLng(coord[1], coord[0]);
    }

    function extendBounds(bounds, coords) {
      coords.forEach(coord => bounds.extend(latLngFromCoord(coord)));
    }

    function candidateCoords(edit) {
      const geom = edit.geom || {};
      if (geom.type === "LineString") return geom.coordinates || [];
      if (geom.type === "Point") return [geom.coordinates];
      return [];
    }

    function popupHtml(properties) {
      return `<div style="padding:8px;max-width:360px;font:12px/1.4 sans-serif;word-break:break-word">${Object.entries(properties || {})
        .map(([key, value]) => `<div><strong>${key}</strong>: ${typeof value === "object" ? JSON.stringify(value) : String(value ?? "-")}</div>`)
        .join("")}</div>`;
    }

    if (!window.kakao || !window.kakao.maps) {
      showWarning("Kakao Maps SDK failed to load. Open this file from the Kakao-allowed localhost port.");
    } else {
      const firstEdit = candidateDocument.edits[0] || {};
      const firstCoords = candidateCoords(firstEdit);
      const firstCenter = firstCoords[0] || [128.88, 35.13];
      const map = new kakao.maps.Map(mapEl, {
        center: latLngFromCoord(firstCenter),
        level: 5
      });
      const bounds = new kakao.maps.LatLngBounds();
      const infoWindow = new kakao.maps.InfoWindow({ removable: true });
      let boundsCount = 0;

      function addLine(coords, style, properties) {
        if (!coords.length) return;
        extendBounds(bounds, coords);
        boundsCount += coords.length;
        const line = new kakao.maps.Polyline({
          map,
          path: coords.map(latLngFromCoord),
          strokeColor: style.color,
          strokeWeight: style.weight,
          strokeOpacity: style.opacity,
          strokeStyle: style.strokeStyle || "solid",
          zIndex: style.zIndex || 1
        });
        kakao.maps.event.addListener(line, "click", (mouseEvent) => {
          infoWindow.setContent(popupHtml(properties));
          infoWindow.setPosition(mouseEvent.latLng);
          infoWindow.open(map);
        });
      }

      ((candidateDocument.context || {}).roadSegments || { features: [] }).features.forEach(feature => {
        addLine(feature.geometry.coordinates || [], {
          color: "#b91c1c",
          weight: 2,
          opacity: 0.28,
          zIndex: 1
        }, feature.properties);
      });

      candidateDocument.edits.forEach(edit => {
        const coords = candidateCoords(edit);
        if (edit.action === "delete_segment") {
          addLine(coords, {
            color: "#7c3aed",
            weight: 6,
            opacity: 0.95,
            strokeStyle: "dash",
            zIndex: 10
          }, edit);
        } else if (edit.action === "add_segment") {
          addLine(coords, {
            color: "#16a34a",
            weight: 6,
            opacity: 0.95,
            zIndex: 11
          }, edit);
        }
      });

      if (boundsCount > 0) map.setBounds(bounds);
    }
  </script>
</body>
</html>
"""
