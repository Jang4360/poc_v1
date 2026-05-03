#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from argparse import Namespace
from collections import Counter
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from pyproj import Transformer


ROOT_DIR = Path(__file__).resolve().parents[2]
GRAPH_SCRIPTS_DIR = ROOT_DIR / "graphhopper" / "scripts"
if str(GRAPH_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(GRAPH_SCRIPTS_DIR))

import analyze_connectivity  # noqa: E402
import apply_connectivity_candidates  # noqa: E402
import bridge_remaining_components  # noqa: E402

SEGMENT_CSV = ROOT_DIR / "etl" / "raw" / "gangseo_road_segments_v7.csv"
NODE_CSV = ROOT_DIR / "etl" / "raw" / "gangseo_road_nodes_v7.csv"
ANALYSIS_JSON = ROOT_DIR / "runtime" / "graphhopper" / "connectivity" / "connectivity_analysis.json"
REVIEW_JSON = ROOT_DIR / "runtime" / "graphhopper" / "connectivity" / "connector_review.json"
HTML_PATH = ROOT_DIR / "etl" / "noksan_sinho_songjeong_hwajeon_segment_02c_graph_edit.html"
GRAPH_SEGMENT_CSV = ROOT_DIR / "etl" / "raw" / "gangseo_road_segments_v7.csv"
GRAPH_NODE_CSV = ROOT_DIR / "etl" / "raw" / "gangseo_road_nodes_v7.csv"
GRAPH_GEOJSON = ROOT_DIR / "etl" / "noksan_sinho_songjeong_hwajeon_segment_02c_graph_materialized.geojson"
FOUR_DONG_IDS = ("sinho", "noksan", "myeongji", "hwajeon")
GANGSEO_DONG_AREAS = {
    "gangseo_all": {
        "id": "gangseo_all",
        "name": "강서구 전체",
        "bbox": {"minLon": 128.765, "minLat": 34.993, "maxLon": 128.998, "maxLat": 35.236},
    },
    "myeongji": {"id": "myeongji", "name": "명지동", "bbox": {"minLon": 128.895, "minLat": 35.08, "maxLon": 128.94, "maxLat": 35.12}},
    "sinho": {"id": "sinho", "name": "신호동", "bbox": {"minLon": 128.858, "minLat": 35.075, "maxLon": 128.895, "maxLat": 35.105}},
    "noksan": {"id": "noksan", "name": "녹산동", "bbox": {"minLon": 128.815, "minLat": 35.075, "maxLon": 128.858, "maxLat": 35.135}},
    "hwajeon": {"id": "hwajeon", "name": "화전동", "bbox": {"minLon": 128.858, "minLat": 35.105, "maxLon": 128.895, "maxLat": 35.135}},
    "songjeong": {"id": "songjeong", "name": "송정동", "bbox": {"minLon": 128.815, "minLat": 35.045, "maxLon": 128.865, "maxLat": 35.085}},
    "mium": {"id": "mium", "name": "미음동", "bbox": {"minLon": 128.835, "minLat": 35.135, "maxLon": 128.895, "maxLat": 35.175}},
    "jisa": {"id": "jisa", "name": "지사동", "bbox": {"minLon": 128.83, "minLat": 35.14, "maxLon": 128.895, "maxLat": 35.185}},
    "saenggok": {"id": "saenggok", "name": "생곡동", "bbox": {"minLon": 128.855, "minLat": 35.125, "maxLon": 128.905, "maxLat": 35.165}},
    "beombang": {"id": "beombang", "name": "범방동", "bbox": {"minLon": 128.875, "minLat": 35.12, "maxLon": 128.925, "maxLat": 35.165}},
    "gurang": {"id": "gurang", "name": "구랑동", "bbox": {"minLon": 128.835, "minLat": 35.105, "maxLon": 128.875, "maxLat": 35.145}},
    "garak": {"id": "garak", "name": "가락동", "bbox": {"minLon": 128.825, "minLat": 35.175, "maxLon": 128.925, "maxLat": 35.235}},
    "gangdong": {"id": "gangdong", "name": "강동동", "bbox": {"minLon": 128.895, "minLat": 35.18, "maxLon": 128.965, "maxLat": 35.235}},
    "daejeo1": {"id": "daejeo1", "name": "대저1동", "bbox": {"minLon": 128.94, "minLat": 35.19, "maxLon": 129.005, "maxLat": 35.235}},
    "daejeo2": {"id": "daejeo2", "name": "대저2동", "bbox": {"minLon": 128.9, "minLat": 35.13, "maxLon": 129.005, "maxLat": 35.2}},
    "gonghang": {"id": "gonghang", "name": "공항동", "bbox": {"minLon": 128.92, "minLat": 35.145, "maxLon": 128.995, "maxLat": 35.2}},
    "gadeokdo": {"id": "gadeokdo", "name": "가덕도동", "bbox": {"minLon": 128.765, "minLat": 34.993, "maxLon": 128.855, "maxLat": 35.075}},
}
SIDE_LINE_ALIASES = {"SIDE_LEFT", "SIDE_RIGHT"}
GRAPH_BBOX_BUFFER_METER = float(os.environ.get("GANGSEO_GRAPH_BBOX_BUFFER_METER", "0"))
BRIDGE_MAX_DISTANCE_METER = float(os.environ.get("GANGSEO_BRIDGE_MAX_DISTANCE_METER", "0"))
GRAPH_PAYLOAD_PRESLICED = os.environ.get("GANGSEO_GRAPH_PAYLOAD_PRESLICED", "").lower() in {"1", "true", "yes"}


def strip_srid(wkt: str) -> str:
    value = (wkt or "").strip()
    if value.upper().startswith("SRID="):
        _, value = value.split(";", 1)
    return value.strip()


def parse_linestring(wkt: str) -> list[list[float]]:
    value = strip_srid(wkt)
    prefix = "LINESTRING("
    if not value.upper().startswith(prefix) or not value.endswith(")"):
        raise ValueError("not a LINESTRING WKT")
    coords: list[list[float]] = []
    for raw in value[len(prefix) : -1].split(","):
        lon, lat = raw.strip().split()[:2]
        coords.append([float(lon), float(lat)])
    return coords


def parse_point(wkt: str) -> list[float]:
    value = strip_srid(wkt)
    prefix = "POINT("
    if not value.upper().startswith(prefix) or not value.endswith(")"):
        raise ValueError("not a POINT WKT")
    lon, lat = value[len(prefix) : -1].strip().split()[:2]
    return [float(lon), float(lat)]


def feature_bbox(coords: list[list[float]]) -> list[float]:
    return [
        min(coord[0] for coord in coords),
        min(coord[1] for coord in coords),
        max(coord[0] for coord in coords),
        max(coord[1] for coord in coords),
    ]


def bbox_intersects(left: list[float], right: tuple[float, float, float, float]) -> bool:
    return left[2] >= right[0] and left[0] <= right[2] and left[3] >= right[1] and left[1] <= right[3]


def parse_bbox(value: str | None, fallback: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
    if not value:
        return fallback
    parts = [float(item) for item in value.split(",")]
    if len(parts) != 4:
        raise ValueError("bbox must be minLng,minLat,maxLng,maxLat")
    return parts[0], parts[1], parts[2], parts[3]


def load_analysis(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_base_segments(segment_csv: Path, analysis: dict[str, Any]) -> tuple[list[dict[str, Any]], tuple[float, float, float, float]]:
    component_by_edge = {
        str(item.get("edgeId")): str(item.get("componentId", ""))
        for item in analysis.get("segmentComponents", [])
    }
    features: list[dict[str, Any]] = []
    bounds: list[list[float]] = []
    with segment_csv.open(newline="", encoding="utf-8-sig") as fp:
        for row in csv.DictReader(fp):
            try:
                coords = parse_linestring(row.get("geom", ""))
            except Exception:
                continue
            bbox = feature_bbox(coords)
            bounds.append(bbox)
            edge_id = row.get("edgeId", "")
            features.append(
                {
                    "id": edge_id,
                    "bbox": bbox,
                    "geometry": {"type": "LineString", "coordinates": coords},
                    "properties": {
                        "edgeId": edge_id,
                        "componentId": component_by_edge.get(edge_id, ""),
                        "segmentType": row.get("segmentType", ""),
                    },
                }
            )
    if not bounds:
        raise RuntimeError("no valid segment geometry")
    full_bbox = (
        min(item[0] for item in bounds),
        min(item[1] for item in bounds),
        max(item[2] for item in bounds),
        max(item[3] for item in bounds),
    )
    return features, full_bbox


def load_nodes(node_csv: Path) -> list[dict[str, Any]]:
    features: list[dict[str, Any]] = []
    with node_csv.open(newline="", encoding="utf-8-sig") as fp:
        for row in csv.DictReader(fp):
            try:
                coord = parse_point(row.get("point", ""))
            except Exception:
                continue
            node_id = row.get("vertexId", "")
            features.append(
                {
                    "id": node_id,
                    "bbox": [coord[0], coord[1], coord[0], coord[1]],
                    "geometry": {"type": "Point", "coordinates": coord},
                    "properties": {
                        "vertexId": node_id,
                        "sourceNodeKey": row.get("sourceNodeKey", ""),
                    },
                }
            )
    return features


def display_candidates_from_analysis(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    return (
        list(analysis.get("candidates", []))
        + list(analysis.get("lowPriorityCandidates", []))
        + list(analysis.get("bridgeCandidates", []))
    )


def candidate_feature(candidate: dict[str, Any]) -> dict[str, Any]:
    coords = candidate.get("geometry") or []
    return {
        "id": candidate.get("candidateId", ""),
        "bbox": feature_bbox(coords),
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {
            key: value
            for key, value in candidate.items()
            if key not in {"geometry", "review"}
        },
    }


def display_state_from_analysis(
    *,
    segment_csv: Path,
    node_csv: Path,
    analysis: dict[str, Any],
) -> dict[str, Any]:
    base_features, full_bbox = load_base_segments(segment_csv, analysis)
    node_features = load_nodes(node_csv)
    candidate_features = [
        candidate_feature(candidate)
        for candidate in display_candidates_from_analysis(analysis)
        if candidate.get("geometry")
    ]
    display_color_counts: dict[str, int] = {}
    for feature in candidate_features:
        color = str(feature["properties"].get("color") or "")
        display_color_counts[color] = display_color_counts.get(color, 0) + 1
    summary = dict(analysis.get("summary", {}))
    summary["candidateCount"] = len(candidate_features)
    summary["candidateColorCounts"] = display_color_counts
    analysis["summary"] = summary
    return {
        "analysis": analysis,
        "base_features": base_features,
        "node_features": node_features,
        "candidate_features": candidate_features,
        "full_bbox": full_bbox,
    }


def build_bridge_only_analysis(segment_csv: Path, node_csv: Path) -> dict[str, Any]:
    analysis = analyze_graph_connectivity(segment_csv, node_csv)
    to_5179 = Transformer.from_crs("EPSG:4326", "EPSG:5179", always_xy=True)
    from_5179 = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)
    node_rows, _node_fields = bridge_remaining_components.load_rows(node_csv)
    segment_rows, _segment_fields = bridge_remaining_components.load_rows(segment_csv)
    nodes, _segments, components, _node_component, _degree = bridge_remaining_components.build_graph(
        segment_rows,
        node_rows,
        to_5179,
    )
    _main_component_id, bridge_candidates = bridge_remaining_components.generate_bridge_candidates(
        components=components,
        nodes=nodes,
        from_5179=from_5179,
        auto_bridge_max_meter=3.0,
        review_bridge_max_meter=12.0,
    )
    if BRIDGE_MAX_DISTANCE_METER > 0:
        bridge_candidates = [
            candidate
            for candidate in bridge_candidates
            if float(candidate.get("distanceMeter") or 0) <= BRIDGE_MAX_DISTANCE_METER
        ]
    priority_counts = Counter(candidate["priority"] for candidate in bridge_candidates)
    analysis["candidates"] = []
    analysis["lowPriorityCandidates"] = []
    analysis["bridgeCandidates"] = bridge_candidates
    summary = dict(analysis.get("summary", {}))
    summary.update(
        {
            "candidateCount": len(bridge_candidates),
            "generatedCandidateCount": 0,
            "candidateOutputTruncated": False,
            "candidateTypeCounts": {"PROPOSED_BRIDGE": len(bridge_candidates)},
            "candidateColorCounts": {"blue": len(bridge_candidates)},
            "bridgeCandidateCount": len(bridge_candidates),
            "autoBridgeCandidateCount": priority_counts.get("AUTO", 0),
            "reviewBridgeCandidateCount": priority_counts.get("REVIEW", 0),
            "heldBridgeCandidateCount": priority_counts.get("HELD", 0),
            "displayScope": "current edited graph proposed bridges only",
            "bridgeMaxDistanceMeter": BRIDGE_MAX_DISTANCE_METER or None,
        }
    )
    analysis["summary"] = summary
    return analysis


def analyze_graph_connectivity(segment_csv: Path, node_csv: Path) -> dict[str, Any]:
    return analyze_connectivity.analyze(
        Namespace(
            segments=segment_csv,
            nodes=node_csv,
            max_radius_meter=20.0,
            min_connector_meter=0.75,
            endpoint_exclusion_meter=1.0,
            split_connector_max_meter=1.0,
            node_merge_meter=2.0,
            endpoint_candidate_max_meter=12.0,
            direction_check_min_meter=3.0,
            direction_min_outward_alignment=0.34,
            direction_min_not_backward_alignment=-0.35,
            max_per_component_pair=2,
            max_candidates=25000,
        )
    )


def build_auto_apply_analysis(segment_csv: Path, node_csv: Path) -> dict[str, Any]:
    analysis = analyze_graph_connectivity(segment_csv, node_csv)
    apply_candidates = [
        candidate
        for candidate in analysis.get("candidates", [])
        if candidate.get("color") == "orange" or candidate.get("type") == "SPLIT_AND_CONNECT"
    ]
    apply_low_priority = [
        candidate
        for candidate in analysis.get("lowPriorityCandidates", [])
        if candidate.get("color") == "orange"
    ]
    analysis["candidates"] = apply_candidates
    analysis["lowPriorityCandidates"] = apply_low_priority
    color_counts = Counter(candidate.get("color") for candidate in apply_candidates)
    color_counts.update(candidate.get("color") for candidate in apply_low_priority)
    type_counts = Counter(candidate.get("type") for candidate in apply_candidates)
    summary = dict(analysis.get("summary", {}))
    summary.update(
        {
            "candidateCount": len(apply_candidates),
            "lowPriorityCandidateCount": len(apply_low_priority),
            "candidateColorCounts": dict(color_counts),
            "candidateTypeCounts": dict(type_counts),
            "displayScope": "auto-apply 0-12m orange connectors, split connectors, and prerequisite node merges; red 12-20m excluded",
        }
    )
    analysis["summary"] = summary
    return analysis


def apply_auto_connectivity_candidates(server: Any) -> dict[str, Any]:
    analysis = build_auto_apply_analysis(server.graph_segment_csv, server.graph_node_csv)
    base = server.analysis_json.with_name(server.analysis_json.stem + "_auto_0_12_split")
    analysis_path = base.with_suffix(".json")
    report_path = server.analysis_json.with_name(server.analysis_json.stem + "_auto_0_12_split_apply_report.json")
    tmp_segments = server.graph_segment_csv.with_name(server.graph_segment_csv.stem + ".auto.tmp.csv")
    tmp_nodes = server.graph_node_csv.with_name(server.graph_node_csv.stem + ".auto.tmp.csv")
    analysis_path.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = apply_connectivity_candidates.apply(
        Namespace(
            segments=server.graph_segment_csv,
            nodes=server.graph_node_csv,
            analysis=analysis_path,
            output_segments=tmp_segments,
            output_nodes=tmp_nodes,
            report=report_path,
            split_cluster_meter=1.0,
            yellow_merge_meter=1.0,
            remove_short_edge_meter=0.3,
            include_low_priority=True,
            include_node_merges=True,
        )
    )
    os.replace(tmp_segments, server.graph_segment_csv)
    os.replace(tmp_nodes, server.graph_node_csv)
    return report


def refresh_server_connectivity_state(server: Any) -> dict[str, Any]:
    analysis = build_bridge_only_analysis(server.graph_segment_csv, server.graph_node_csv)
    if getattr(server, "analysis_json", None):
        server.analysis_json.parent.mkdir(parents=True, exist_ok=True)
        server.analysis_json.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state = display_state_from_analysis(
        segment_csv=server.graph_segment_csv,
        node_csv=server.graph_node_csv,
        analysis=analysis,
    )
    server.analysis = state["analysis"]
    server.base_features = state["base_features"]
    server.node_features = state["node_features"]
    server.candidate_features = state["candidate_features"]
    server.full_bbox = state["full_bbox"]
    return server.analysis.get("summary", {})


def normalize_segment_type(segment_type: Any) -> str:
    value = str(segment_type or "CENTERLINE")
    return "SIDE_LINE" if value in SIDE_LINE_ALIASES else value


def dong_area(dong_id_or_name: str | None) -> dict[str, Any]:
    lookup = str(dong_id_or_name or "sinho")
    for area in GANGSEO_DONG_AREAS.values():
        if lookup in {area["id"], area["name"]}:
            return area
    return GANGSEO_DONG_AREAS["sinho"]


def area_bbox_tuple(area: dict[str, Any]) -> tuple[float, float, float, float]:
    bbox = area["bbox"]
    base = (bbox["minLon"], bbox["minLat"], bbox["maxLon"], bbox["maxLat"])
    if GRAPH_BBOX_BUFFER_METER <= 0:
        return base
    min_lon, min_lat, max_lon, max_lat = base
    mid_lat = (min_lat + max_lat) / 2
    delta_lat = GRAPH_BBOX_BUFFER_METER / 110540
    delta_lon = GRAPH_BBOX_BUFFER_METER / (111320 * math.cos(math.radians(mid_lat)))
    return (min_lon - delta_lon, min_lat - delta_lat, max_lon + delta_lon, max_lat + delta_lat)


def ewkt_to_geometry(value: str) -> dict[str, Any]:
    stripped = strip_srid(value)
    if stripped.startswith("POINT("):
        return {"type": "Point", "coordinates": parse_point(value)}
    if stripped.startswith("LINESTRING("):
        return {"type": "LineString", "coordinates": parse_linestring(value)}
    raise ValueError(f"unsupported EWKT geometry: {value!r}")


def geometry_to_ewkt(geometry: dict[str, Any]) -> str:
    coords = geometry.get("coordinates")
    if geometry.get("type") == "Point":
        return f"SRID=4326;POINT({float(coords[0]):.8f} {float(coords[1]):.8f})"
    if geometry.get("type") == "LineString":
        body = ", ".join(f"{float(lng):.8f} {float(lat):.8f}" for lng, lat in coords)
        return f"SRID=4326;LINESTRING({body})"
    raise ValueError(f"unsupported geometry type: {geometry.get('type')!r}")


def feature_in_bbox(feature: dict[str, Any], bbox: tuple[float, float, float, float]) -> bool:
    min_lon, min_lat, max_lon, max_lat = bbox
    geometry = feature.get("geometry", {})
    coords = geometry.get("coordinates") or []
    points = [coords] if geometry.get("type") == "Point" else coords
    return any(min_lon <= float(lng) <= max_lon and min_lat <= float(lat) <= max_lat for lng, lat in points)


def feature_intersects_bbox(feature: dict[str, Any], bbox: tuple[float, float, float, float]) -> bool:
    geometry = feature.get("geometry", {})
    coords = geometry.get("coordinates") or []
    if geometry.get("type") == "Point":
        return feature_in_bbox(feature, bbox)
    if geometry.get("type") == "LineString":
        return bbox_intersects(feature_bbox(coords), bbox)
    return feature_in_bbox(feature, bbox)


def graph_feature_bounds(features: list[dict[str, Any]]) -> dict[str, float] | None:
    boxes: list[list[float]] = []
    for feature in features:
        geometry = feature.get("geometry", {})
        coords = geometry.get("coordinates") or []
        if geometry.get("type") == "Point":
            boxes.append([coords[0], coords[1], coords[0], coords[1]])
        elif geometry.get("type") == "LineString":
            boxes.append(feature_bbox(coords))
    if not boxes:
        return None
    return {
        "minLon": min(item[0] for item in boxes),
        "minLat": min(item[1] for item in boxes),
        "maxLon": max(item[2] for item in boxes),
        "maxLat": max(item[3] for item in boxes),
    }


def refresh_graph_summary(payload: dict[str, Any]) -> None:
    degree: dict[int, int] = {}
    segments = payload["layers"]["roadSegments"]["features"]
    nodes = payload["layers"]["roadNodes"]["features"]
    for segment in segments:
        props = segment["properties"]
        props["segmentType"] = normalize_segment_type(props.get("segmentType"))
        for key in ("fromNodeId", "toNodeId"):
            node_id = int(props[key])
            degree[node_id] = degree.get(node_id, 0) + 1
    counts: dict[str, int] = {}
    for segment in segments:
        segment_type = segment["properties"]["segmentType"]
        counts[segment_type] = counts.get(segment_type, 0) + 1
    for node in nodes:
        node["properties"]["degree"] = degree.get(int(node["properties"]["vertexId"]), 0)
    payload["summary"].update(
        {
            "nodeCount": len(nodes),
            "segmentCount": len(segments),
            "segmentTypeCounts": [{"name": name, "count": count} for name, count in sorted(counts.items())],
        }
    )


def build_csv_payload(
    *,
    node_csv: Path,
    segment_csv: Path,
    output_html: Path,
    output_geojson: Path,
    bbox: tuple[float, float, float, float] | None,
) -> dict[str, Any]:
    node_features: dict[int, dict[str, Any]] = {}
    with node_csv.open(newline="", encoding="utf-8-sig") as fp:
        for row in csv.DictReader(fp):
            vertex_id = int(row["vertexId"])
            node_features[vertex_id] = {
                "type": "Feature",
                "properties": {
                    "vertexId": vertex_id,
                    "sourceNodeKey": row.get("sourceNodeKey", ""),
                    "nodeType": "CSV",
                    "degree": 0,
                    "endpointCount": 1,
                    "projectedKey": "",
                },
                "geometry": ewkt_to_geometry(row["point"]),
            }

    segment_features: list[dict[str, Any]] = []
    referenced_node_ids: set[int] = set()
    with segment_csv.open(newline="", encoding="utf-8-sig") as fp:
        for row in csv.DictReader(fp):
            try:
                feature = {
                    "type": "Feature",
                    "properties": {
                        "edgeId": int(row["edgeId"]),
                        "fromNodeId": int(row["fromNodeId"]),
                        "toNodeId": int(row["toNodeId"]),
                        "segmentType": normalize_segment_type(row.get("segmentType")),
                        "lengthMeter": float(row.get("lengthMeter") or 0),
                    },
                    "geometry": ewkt_to_geometry(row["geom"]),
                }
            except Exception:
                continue
            if bbox is not None and not feature_intersects_bbox(feature, bbox):
                continue
            segment_features.append(feature)
            referenced_node_ids.add(feature["properties"]["fromNodeId"])
            referenced_node_ids.add(feature["properties"]["toNodeId"])

    visible_nodes = [
        feature
        for vertex_id, feature in node_features.items()
        if vertex_id in referenced_node_ids or (bbox is not None and feature_in_bbox(feature, bbox))
    ]
    bounds = graph_feature_bounds(segment_features + visible_nodes)
    if bounds is None and bbox is not None:
        bounds = {"minLon": bbox[0], "minLat": bbox[1], "maxLon": bbox[2], "maxLat": bbox[3]}
    center_lon = ((bounds or {"minLon": 128.872, "maxLon": 128.872})["minLon"] + (bounds or {"minLon": 128.872, "maxLon": 128.872})["maxLon"]) / 2
    center_lat = ((bounds or {"minLat": 35.095, "maxLat": 35.095})["minLat"] + (bounds or {"minLat": 35.095, "maxLat": 35.095})["maxLat"]) / 2
    payload = {
        "meta": {
            "title": "강서구 CSV-backed Graph Manual Edit UI",
            "districtGu": "강서구",
            "centerLat": round(center_lat, 7),
            "centerLon": round(center_lon, 7),
            "radiusMeter": 0,
            "sourceShp": "road_nodes/road_segments CSV",
            "outputHtml": str(output_html),
            "outputGeojson": str(output_geojson),
            "localhostUrl": f"http://127.0.0.1:3000/etl/{output_html.name}",
            "stage": "02c-csv-backed-manual-edit-ui",
            "manualEditRule": "CSV-backed 강서구 graph; export manual_edits JSON for the next patch cycle",
        },
        "summary": {"nodeCount": 0, "segmentCount": 0, "segmentTypeCounts": []},
        "layers": {
            "roadNodes": {"type": "FeatureCollection", "features": visible_nodes},
            "roadSegments": {"type": "FeatureCollection", "features": segment_features},
        },
    }
    if bounds is not None:
        payload["meta"]["bbox"] = bounds
    refresh_graph_summary(payload)
    return payload


def merge_bounds(bounds: list[dict[str, float]]) -> dict[str, float]:
    return {
        "minLon": min(item["minLon"] for item in bounds),
        "minLat": min(item["minLat"] for item in bounds),
        "maxLon": max(item["maxLon"] for item in bounds),
        "maxLat": max(item["maxLat"] for item in bounds),
    }


def combined_four_dong_payload(
    *,
    node_csv: Path,
    segment_csv: Path,
    output_html: Path,
    output_geojson: Path,
) -> dict[str, Any]:
    if GRAPH_PAYLOAD_PRESLICED:
        payload = build_csv_payload(
            node_csv=node_csv,
            segment_csv=segment_csv,
            output_html=output_html,
            output_geojson=output_geojson,
            bbox=None,
        )
        payload["meta"].update(
            {
                "title": "강서구 신호동/녹산동/명지동/화전동 CSV-backed Graph Manual Edit UI",
                "districtGu": "강서구",
                "dongId": "gangseo_four",
                "districtDong": "신호동, 녹산동, 명지동, 화전동",
                "stage": "02c-csv-backed-four-dong-manual-edit-ui",
                "manualEditRule": "CSV-backed 강서구 4개 동 graph; export manual_edits JSON for the next patch cycle",
            }
        )
        return payload

    merged_nodes: dict[int, dict[str, Any]] = {}
    merged_segments: dict[int, dict[str, Any]] = {}
    bounds: list[dict[str, float]] = []
    for dong_id in FOUR_DONG_IDS:
        area = dong_area(dong_id)
        payload = build_csv_payload(
            node_csv=node_csv,
            segment_csv=segment_csv,
            output_html=output_html,
            output_geojson=output_geojson,
            bbox=area_bbox_tuple(area),
        )
        for node in payload["layers"]["roadNodes"]["features"]:
            merged_nodes[int(node["properties"]["vertexId"])] = node
        for segment in payload["layers"]["roadSegments"]["features"]:
            merged_segments[int(segment["properties"]["edgeId"])] = segment
        if "bbox" in payload["meta"]:
            bounds.append(payload["meta"]["bbox"])

    bbox = graph_feature_bounds(list(merged_segments.values()) + list(merged_nodes.values()))
    if bbox is None and bounds:
        bbox = merge_bounds(bounds)
    center_lon = ((bbox or {"minLon": 128.815, "maxLon": 128.94})["minLon"] + (bbox or {"minLon": 128.815, "maxLon": 128.94})["maxLon"]) / 2
    center_lat = ((bbox or {"minLat": 35.075, "maxLat": 35.135})["minLat"] + (bbox or {"minLat": 35.075, "maxLat": 35.135})["maxLat"]) / 2
    payload = {
        "meta": {
            "title": "강서구 신호동/녹산동/명지동/화전동 CSV-backed Graph Manual Edit UI",
            "districtGu": "강서구",
            "dongId": "gangseo_four",
            "districtDong": "신호동, 녹산동, 명지동, 화전동",
            "centerLat": round(center_lat, 7),
            "centerLon": round(center_lon, 7),
            "radiusMeter": 0,
            "sourceShp": "road_nodes/road_segments CSV",
            "outputHtml": str(output_html),
            "outputGeojson": str(output_geojson),
            "localhostUrl": f"http://127.0.0.1:3000/etl/{output_html.name}",
            "stage": "02c-csv-backed-four-dong-manual-edit-ui",
            "manualEditRule": "CSV-backed 강서구 4개 동 graph; export manual_edits JSON for the next patch cycle",
        },
        "summary": {
            "nodeCount": 0,
            "segmentCount": 0,
            "segmentTypeCounts": [],
            "transitionConnectorCount": 0,
            "gapBridgeCount": 0,
            "cornerBridgeCount": 0,
            "sameSideCornerBridgeCount": 0,
            "crossSideCornerBridgeCount": 0,
            "crossingCount": 0,
            "elevatorConnectorCount": 0,
        },
        "layers": {
            "roadNodes": {"type": "FeatureCollection", "features": sorted(merged_nodes.values(), key=lambda item: int(item["properties"]["vertexId"]))},
            "roadSegments": {"type": "FeatureCollection", "features": sorted(merged_segments.values(), key=lambda item: int(item["properties"]["edgeId"]))},
        },
    }
    if bbox is not None:
        payload["meta"]["bbox"] = bbox
    refresh_graph_summary(payload)
    return payload


def graph_payload_for_dong(
    *,
    dong_id: str,
    node_csv: Path,
    segment_csv: Path,
    output_html: Path,
    output_geojson: Path,
) -> dict[str, Any]:
    if dong_id in {"gangseo_all", "all", "gangseo"}:
        area = dong_area("gangseo_all")
        payload = build_csv_payload(
            node_csv=node_csv,
            segment_csv=segment_csv,
            output_html=output_html,
            output_geojson=output_geojson,
            bbox=None,
        )
        payload["meta"].update(
            {
                "title": "강서구 전체 CSV-backed Graph Manual Edit UI",
                "districtGu": "강서구",
                "dongId": area["id"],
                "districtDong": area["name"],
                "stage": "02c-csv-backed-gangseo-all-manual-edit-ui",
                "manualEditRule": "CSV-backed Gangseo full graph; use dong scopes for lighter review.",
                "selectionBbox": area_bbox_tuple(area),
                "bufferMeter": 0,
            }
        )
        return payload
    if dong_id in {"gangseo_four", "four", "all4"}:
        return combined_four_dong_payload(
            node_csv=node_csv,
            segment_csv=segment_csv,
            output_html=output_html,
            output_geojson=output_geojson,
        )
    area = dong_area(dong_id)
    payload = build_csv_payload(
        node_csv=node_csv,
        segment_csv=segment_csv,
        output_html=output_html,
        output_geojson=output_geojson,
        bbox=area_bbox_tuple(area),
    )
    payload["meta"].update(
        {
            "title": f"강서구 {area['name']} CSV-backed Graph Manual Edit UI",
            "districtGu": "강서구",
            "dongId": area["id"],
            "districtDong": area["name"],
            "selectionBbox": area_bbox_tuple(area),
            "bufferMeter": GRAPH_BBOX_BUFFER_METER,
        }
    )
    return payload


def distance_meter(left: list[float], right: list[float]) -> float:
    lat1 = math.radians(left[1])
    lat2 = math.radians(right[1])
    delta_lat = math.radians(right[1] - left[1])
    delta_lng = math.radians(right[0] - left[0])
    value = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lng / 2) ** 2
    return 6371008.8 * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def line_length_meter(coords: list[list[float]]) -> float:
    return sum(distance_meter(coords[index - 1], coords[index]) for index in range(1, len(coords)))


def coord_key(coord: list[float]) -> str:
    return f"{float(coord[0]):.8f}:{float(coord[1]):.8f}"


def load_csv_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open(newline="", encoding="utf-8-sig") as fp:
        reader = csv.DictReader(fp)
        return list(reader), list(reader.fieldnames or [])


def apply_csv_edit_document(
    *,
    node_csv: Path,
    segment_csv: Path,
    edit_document: dict[str, Any],
) -> dict[str, Any]:
    node_rows, node_fields = load_csv_rows(node_csv)
    segment_rows, segment_fields = load_csv_rows(segment_csv)
    node_by_id = {int(row["vertexId"]): row for row in node_rows}
    node_by_coord = {coord_key(parse_point(row["point"])): int(row["vertexId"]) for row in node_rows}
    next_node_id = max(node_by_id, default=0) + 1
    next_edge_id = max((int(row["edgeId"]) for row in segment_rows), default=0) + 1
    delete_segment_ids = {int(edit["edgeId"]) for edit in edit_document.get("edits", []) if edit.get("action") == "delete_segment"}
    requested_delete_node_ids = {int(edit["vertexId"]) for edit in edit_document.get("edits", []) if edit.get("action") == "delete_node"}

    segment_rows = [row for row in segment_rows if int(row["edgeId"]) not in delete_segment_ids]
    referenced_after_delete = {int(row["fromNodeId"]) for row in segment_rows} | {int(row["toNodeId"]) for row in segment_rows}
    removable_nodes = requested_delete_node_ids - referenced_after_delete
    if removable_nodes:
        node_rows = [row for row in node_rows if int(row["vertexId"]) not in removable_nodes]
        node_by_id = {int(row["vertexId"]): row for row in node_rows}

    def create_node(coord: list[float], source_key: str | None = None) -> int:
        nonlocal next_node_id
        key = coord_key(coord)
        if key in node_by_coord:
            return node_by_coord[key]
        node_id = next_node_id
        next_node_id += 1
        row = {field: "" for field in node_fields}
        row["vertexId"] = str(node_id)
        row["sourceNodeKey"] = source_key or f"manual_node:{key}"
        row["point"] = geometry_to_ewkt({"type": "Point", "coordinates": coord})
        node_rows.append(row)
        node_by_id[node_id] = row
        node_by_coord[key] = node_id
        return node_id

    def resolve_node(node_ref: dict[str, Any] | None, fallback_coord: list[float]) -> int:
        if node_ref and node_ref.get("mode") == "existing" and node_ref.get("vertexId") is not None:
            node_id = int(node_ref["vertexId"])
            if node_id in node_by_id:
                return node_id
        coord = (node_ref or {}).get("geom", {}).get("coordinates") or fallback_coord
        return create_node(coord, (node_ref or {}).get("sourceNodeKey"))

    for edit in edit_document.get("edits", []):
        if edit.get("action") == "add_node":
            create_node(edit.get("geom", {}).get("coordinates"), edit.get("sourceNodeKey"))
        elif edit.get("action") == "add_segment":
            coords = edit.get("geom", {}).get("coordinates") or []
            if len(coords) < 2:
                continue
            from_id = resolve_node(edit.get("fromNode"), coords[0])
            to_id = resolve_node(edit.get("toNode"), coords[-1])
            if from_id == to_id:
                continue
            row = {field: "" for field in segment_fields}
            row.update(
                {
                    "edgeId": str(next_edge_id),
                    "fromNodeId": str(from_id),
                    "toNodeId": str(to_id),
                    "geom": geometry_to_ewkt({"type": "LineString", "coordinates": coords}),
                    "lengthMeter": f"{line_length_meter(coords):.2f}",
                    "walkAccess": "UNKNOWN",
                    "brailleBlockState": "UNKNOWN",
                    "audioSignalState": "UNKNOWN",
                    "slopeState": "UNKNOWN",
                    "widthState": "UNKNOWN",
                    "surfaceState": "UNKNOWN",
                    "stairsState": "UNKNOWN",
                    "signalState": "UNKNOWN",
                    "segmentType": normalize_segment_type(edit.get("segmentType")),
                }
            )
            next_edge_id += 1
            segment_rows.append(row)

    with node_csv.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=node_fields)
        writer.writeheader()
        writer.writerows(sorted(node_rows, key=lambda row: int(row["vertexId"])))
    with segment_csv.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=segment_fields)
        writer.writeheader()
        writer.writerows(sorted(segment_rows, key=lambda row: int(row["edgeId"])))
    return {
        "nodeCsv": str(node_csv),
        "segmentCsv": str(segment_csv),
        "nodeCount": len(node_rows),
        "segmentCount": len(segment_rows),
    }


class ConnectorEditorHandler(SimpleHTTPRequestHandler):
    server_version = "GangseoConnectorEditor/1.0"

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/segment-02c/payload":
            try:
                query = parse_qs(parsed.query)
                dong = query.get("dong", ["myeongji"])[0]
                payload = graph_payload_for_dong(
                    dong_id=dong,
                    node_csv=self.server.graph_node_csv,  # type: ignore[attr-defined]
                    segment_csv=self.server.graph_segment_csv,  # type: ignore[attr-defined]
                    output_html=self.server.graph_output_html,  # type: ignore[attr-defined]
                    output_geojson=self.server.graph_output_geojson,  # type: ignore[attr-defined]
                )
                self.send_json(
                    200,
                    {
                        "ok": True,
                        "payload": payload,
                        "areas": list(GANGSEO_DONG_AREAS.values()),
                    },
                )
            except Exception as exc:
                self.send_json(500, {"ok": False, "error": str(exc)})
            return
        if parsed.path == "/api/gangseo-connectivity-data":
            try:
                query = parse_qs(parsed.query)
                limit = int(query.get("limit", ["10000"])[0])
                bbox = parse_bbox(query.get("bbox", [None])[0], self.server.full_bbox)  # type: ignore[attr-defined]
                color_filter = set((query.get("colors", ["orange,red,yellow"])[0] or "").split(","))
                base_features = [
                    feature for feature in self.server.base_features  # type: ignore[attr-defined]
                    if bbox_intersects(feature["bbox"], bbox)
                ][:limit]
                node_features = [
                    feature for feature in self.server.node_features  # type: ignore[attr-defined]
                    if bbox_intersects(feature["bbox"], bbox)
                ][:limit]
                candidate_features = [
                    feature for feature in self.server.candidate_features  # type: ignore[attr-defined]
                    if feature["properties"].get("color") in color_filter and bbox_intersects(feature["bbox"], bbox)
                ][:limit]
                self.send_json(
                    200,
                    {
                        "ok": True,
                        "summary": self.server.analysis.get("summary", {}),  # type: ignore[attr-defined]
                        "fullBBox": self.server.full_bbox,  # type: ignore[attr-defined]
                        "base": {
                            "type": "FeatureCollection",
                            "returned": len(base_features),
                            "features": base_features,
                        },
                        "nodes": {
                            "type": "FeatureCollection",
                            "returned": len(node_features),
                            "features": node_features,
                        },
                        "candidates": {
                            "type": "FeatureCollection",
                            "returned": len(candidate_features),
                            "features": candidate_features,
                        },
                    },
                )
            except Exception as exc:
                self.send_json(500, {"ok": False, "error": str(exc)})
            return
        if parsed.path in {"/api", "/api/"}:
            self.send_json(200, {"ok": True, "service": "gangseo-four-dong-connector-editor"})
            return
        super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/segment-02c/apply-edits":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                document = json.loads(body.decode("utf-8"))
                if not isinstance(document.get("edits"), list):
                    raise ValueError("request JSON must contain edits[]")
                report = apply_csv_edit_document(
                    node_csv=self.server.graph_node_csv,  # type: ignore[attr-defined]
                    segment_csv=self.server.graph_segment_csv,  # type: ignore[attr-defined]
                    edit_document=document,
                )
                auto_report = apply_auto_connectivity_candidates(self.server)  # type: ignore[arg-type]
                summary = refresh_server_connectivity_state(self.server)  # type: ignore[arg-type]
                self.send_json(200, {"ok": True, "csv": report, "autoConnectivity": auto_report.get("summary", {}), "summary": summary})
            except Exception as exc:
                self.send_json(500, {"ok": False, "error": str(exc)})
            return
        if parsed.path != "/api/gangseo-connectivity-save-review":
            self.send_error(404, "unknown endpoint")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            document = json.loads(body.decode("utf-8"))
            review_json = self.server.review_json  # type: ignore[attr-defined]
            review_json.parent.mkdir(parents=True, exist_ok=True)
            review_json.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            self.send_json(200, {"ok": True, "reviewJson": str(review_json)})
        except Exception as exc:
            self.send_json(500, {"ok": False, "error": str(exc)})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3002)
    parser.add_argument("--segment-csv", type=Path, default=SEGMENT_CSV)
    parser.add_argument("--node-csv", type=Path, default=NODE_CSV)
    parser.add_argument("--analysis-json", type=Path, default=ANALYSIS_JSON)
    parser.add_argument("--review-json", type=Path, default=REVIEW_JSON)
    parser.add_argument("--graph-segment-csv", type=Path, default=GRAPH_SEGMENT_CSV)
    parser.add_argument("--graph-node-csv", type=Path, default=GRAPH_NODE_CSV)
    parser.add_argument("--graph-output-html", type=Path, default=HTML_PATH)
    parser.add_argument("--graph-output-geojson", type=Path, default=GRAPH_GEOJSON)
    args = parser.parse_args()

    state = display_state_from_analysis(
        segment_csv=args.segment_csv,
        node_csv=args.node_csv,
        analysis=load_analysis(args.analysis_json),
    )

    handler = lambda *handler_args, **handler_kwargs: ConnectorEditorHandler(  # noqa: E731
        *handler_args,
        directory=str(ROOT_DIR),
        **handler_kwargs,
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    server.analysis = state["analysis"]
    server.base_features = state["base_features"]
    server.node_features = state["node_features"]
    server.candidate_features = state["candidate_features"]
    server.full_bbox = state["full_bbox"]
    server.analysis_json = args.analysis_json
    server.review_json = args.review_json
    server.graph_segment_csv = args.graph_segment_csv
    server.graph_node_csv = args.graph_node_csv
    server.graph_output_html = args.graph_output_html
    server.graph_output_geojson = args.graph_output_geojson
    print(f"gangseo-four-dong-connector-editor: api http://{args.host}:{args.port}/api/")
    print(f"gangseo-four-dong-connector-editor: html http://localhost:3000/etl/{args.graph_output_html.name}")
    print("gangseo-four-dong-connector-editor: GET /api/segment-02c/payload?dong=<gangseo_all|dong_id>")
    print("gangseo-four-dong-connector-editor: POST /api/segment-02c/apply-edits updates Gangseo graph CSVs")
    print(f"gangseo-connector-editor: save review -> {args.review_json}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
