#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from etl.common import segment_graph_db
from etl.common.subway_elevator_preview import KAKAO_JAVASCRIPT_KEY

DEFAULT_OUTPUT_HTML = segment_graph_db.ETL_DIR / "sinho_corner_nodes_split_preview.html"
DEFAULT_OUTPUT_GEOJSON = segment_graph_db.ETL_DIR / "sinho_corner_nodes_split_preview.geojson"


def turn_angle_degrees(
    previous: list[float],
    current: list[float],
    following: list[float],
) -> float:
    lat_scale = math.cos(math.radians(float(current[1])))
    ax = (float(current[0]) - float(previous[0])) * lat_scale
    ay = float(current[1]) - float(previous[1])
    bx = (float(following[0]) - float(current[0])) * lat_scale
    by = float(following[1]) - float(current[1])
    a_norm = math.hypot(ax, ay)
    b_norm = math.hypot(bx, by)
    if a_norm == 0 or b_norm == 0:
        return 0.0
    dot = max(-1.0, min(1.0, (ax * bx + ay * by) / (a_norm * b_norm)))
    return math.degrees(math.acos(dot))


def coord_key(coord: list[float]) -> str:
    return f"{float(coord[0]):.8f}:{float(coord[1]):.8f}"


def dedupe_consecutive(coords: list[list[float]]) -> list[list[float]]:
    deduped: list[list[float]] = []
    previous_key: str | None = None
    for coord in coords:
        key = coord_key(coord)
        if key == previous_key:
            continue
        deduped.append([round(float(coord[0]), 8), round(float(coord[1]), 8)])
        previous_key = key
    return deduped


def split_payload_at_corners(
    payload: dict[str, Any],
    *,
    min_turn_degrees: float,
    node_key_prefix: str = "sinho_corner",
    title: str = "강서구 신호동 corner-node split preview",
    stage: str = "sinho-corner-node-split-preview",
) -> dict[str, Any]:
    node_id_by_key: dict[str, int] = {}
    nodes: list[dict[str, Any]] = []
    split_segments: list[dict[str, Any]] = []
    next_vertex_id = 1
    next_edge_id = 1

    def ensure_node(coord: list[float], *, source_edge_id: int, role: str, turn_angle: float | None = None) -> int:
        nonlocal next_vertex_id
        key = coord_key(coord)
        if key in node_id_by_key:
            return node_id_by_key[key]
        vertex_id = next_vertex_id
        next_vertex_id += 1
        node_id_by_key[key] = vertex_id
        props: dict[str, Any] = {
            "vertexId": vertex_id,
            "sourceNodeKey": f"{node_key_prefix}:{key}",
            "nodeType": "CORNER_SPLIT",
            "sourceEdgeId": source_edge_id,
            "cornerRole": role,
            "degree": 0,
        }
        if turn_angle is not None:
            props["turnAngleDegree"] = round(turn_angle, 2)
        nodes.append(
            {
                "type": "Feature",
                "properties": props,
                "geometry": {"type": "Point", "coordinates": [float(coord[0]), float(coord[1])]},
            }
        )
        return vertex_id

    for feature in payload["layers"]["roadSegments"]["features"]:
        props = feature["properties"]
        source_edge_id = int(props["edgeId"])
        coords = dedupe_consecutive(feature["geometry"]["coordinates"])
        if len(coords) < 2:
            continue

        anchor_indexes: dict[int, tuple[str, float | None]] = {
            0: ("endpoint", None),
            len(coords) - 1: ("endpoint", None),
        }
        for index in range(1, len(coords) - 1):
            angle = turn_angle_degrees(coords[index - 1], coords[index], coords[index + 1])
            if angle >= min_turn_degrees:
                anchor_indexes[index] = ("corner", angle)

        sorted_indexes = sorted(anchor_indexes)
        for left_index, right_index in zip(sorted_indexes, sorted_indexes[1:]):
            piece_coords = coords[left_index : right_index + 1]
            if len(piece_coords) < 2:
                continue
            from_role, from_angle = anchor_indexes[left_index]
            to_role, to_angle = anchor_indexes[right_index]
            from_node_id = ensure_node(
                coords[left_index],
                source_edge_id=source_edge_id,
                role=from_role,
                turn_angle=from_angle,
            )
            to_node_id = ensure_node(
                coords[right_index],
                source_edge_id=source_edge_id,
                role=to_role,
                turn_angle=to_angle,
            )
            if from_node_id == to_node_id:
                continue
            length_meter = round(segment_graph_db.line_length_meter(piece_coords), 2)
            if length_meter <= 0:
                continue
            split_segments.append(
                {
                    "type": "Feature",
                    "properties": {
                        "edgeId": next_edge_id,
                        "sourceEdgeId": source_edge_id,
                        "splitIndex": len(split_segments),
                        "fromNodeId": from_node_id,
                        "toNodeId": to_node_id,
                        "segmentType": props.get("segmentType", "ROAD_BOUNDARY"),
                        "lengthMeter": length_meter,
                    },
                    "geometry": {"type": "LineString", "coordinates": piece_coords},
                }
            )
            next_edge_id += 1

    degree: Counter[int] = Counter()
    for segment in split_segments:
        degree[int(segment["properties"]["fromNodeId"])] += 1
        degree[int(segment["properties"]["toNodeId"])] += 1
    for node in nodes:
        node["properties"]["degree"] = degree[int(node["properties"]["vertexId"])]

    segment_counts = Counter(segment["properties"]["segmentType"] for segment in split_segments)
    meta = dict(payload["meta"])
    meta.update(
        {
            "title": title,
            "outputHtml": str(DEFAULT_OUTPUT_HTML),
            "outputGeojson": str(DEFAULT_OUTPUT_GEOJSON),
            "localhostUrl": f"http://127.0.0.1:3000/etl/{DEFAULT_OUTPUT_HTML.name}",
            "cornerNodeRule": f"endpoints plus interior vertices with turn angle >= {min_turn_degrees:g} degrees",
            "stage": stage,
        }
    )
    return {
        "meta": meta,
        "summary": {
            **payload["summary"],
            "nodeCount": len(nodes),
            "segmentCount": len(split_segments),
            "segmentTypeCounts": [{"name": name, "count": count} for name, count in sorted(segment_counts.items())],
            "cornerNodeCount": sum(1 for node in nodes if node["properties"]["cornerRole"] == "corner"),
            "endpointNodeCount": sum(1 for node in nodes if node["properties"]["cornerRole"] == "endpoint"),
            "sourceSegmentCount": payload["summary"]["segmentCount"],
            "minTurnDegrees": min_turn_degrees,
        },
        "layers": {
            "roadNodes": {"type": "FeatureCollection", "features": nodes},
            "roadSegments": {"type": "FeatureCollection", "features": split_segments},
        },
    }


def render_preview_html(payload: dict[str, Any]) -> str:
    payload_json = json.dumps(payload, ensure_ascii=False)
    kakao_javascript_key = html.escape(KAKAO_JAVASCRIPT_KEY)
    meta = payload["meta"]
    summary = payload["summary"]
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(meta["title"])}</title>
  <style>
    html, body, #map {{
      width: 100%;
      height: 100%;
      margin: 0;
      font: 13px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: #0f172a;
    }}
    body {{ overflow: hidden; }}
    .panel {{
      position: absolute;
      z-index: 700;
      left: 12px;
      top: 12px;
      padding: 10px 12px;
      background: rgba(255, 255, 255, 0.92);
      border: 1px solid #d1d5db;
      box-shadow: 0 8px 24px rgba(15, 23, 42, 0.14);
    }}
    .panel h1 {{
      margin: 0 0 6px;
      font-size: 15px;
    }}
    .panel p {{
      margin: 0;
      color: #334155;
    }}
    .warning {{
      margin-top: 6px;
      color: #b91c1c;
    }}
  </style>
</head>
<body>
  <div id="map"></div>
  <aside class="panel">
    <h1>{html.escape(meta["title"])}</h1>
    <p>nodes {summary["nodeCount"]} / segments {summary["segmentCount"]}</p>
    <p>corner nodes {summary["cornerNodeCount"]}, endpoint nodes {summary["endpointNodeCount"]}</p>
    <p>source segments {summary["sourceSegmentCount"]}, min turn {summary["minTurnDegrees"]:g} deg</p>
    <p id="warning" class="warning"></p>
  </aside>
  <script src="https://dapi.kakao.com/v2/maps/sdk.js?appkey={kakao_javascript_key}"></script>
  <script>
    const payload = {payload_json};
    const warningEl = document.getElementById("warning");

    function latLng(coord) {{
      return new kakao.maps.LatLng(coord[1], coord[0]);
    }}

    function lineStyle(segmentType) {{
      if (segmentType === "ROAD_BOUNDARY_INNER") {{
        return {{ color: "#ef4444", weight: 3, opacity: 0.78 }};
      }}
      return {{ color: "#ef4444", weight: 4, opacity: 0.88 }};
    }}

    function popupHtml(properties) {{
      return `<div style="padding:8px 10px;font:12px/1.4 -apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;min-width:220px">${{Object.entries(properties || {{}})
        .map(([key, value]) => `<div><strong style="display:inline-block;min-width:92px">${{key}}</strong>${{String(value ?? "-")}}</div>`)
        .join("")}}</div>`;
    }}

    if (!window.kakao || !window.kakao.maps) {{
      warningEl.textContent = "Kakao Maps SDK failed to load.";
    }} else {{
      const map = new kakao.maps.Map(document.getElementById("map"), {{
        center: new kakao.maps.LatLng(payload.meta.centerLat, payload.meta.centerLon),
        level: 4
      }});
      const bounds = new kakao.maps.LatLngBounds();
      const infoWindow = new kakao.maps.InfoWindow({{ removable: true }});

      payload.layers.roadSegments.features.forEach(feature => {{
        const style = lineStyle(feature.properties.segmentType);
        const coords = feature.geometry.coordinates;
        coords.forEach(coord => bounds.extend(latLng(coord)));
        const line = new kakao.maps.Polyline({{
          map,
          path: coords.map(latLng),
          strokeColor: style.color,
          strokeWeight: style.weight,
          strokeOpacity: style.opacity,
          zIndex: 3
        }});
        kakao.maps.event.addListener(line, "click", event => {{
          infoWindow.setContent(popupHtml(feature.properties));
          infoWindow.setPosition(event.latLng);
          infoWindow.open(map);
        }});
      }});

      payload.layers.roadNodes.features.forEach(feature => {{
        const coord = feature.geometry.coordinates;
        const position = latLng(coord);
        bounds.extend(position);
        const isCorner = feature.properties.cornerRole === "corner";
        const node = new kakao.maps.Circle({{
          map,
          center: position,
          radius: isCorner ? 1.9 : 1.7,
          strokeWeight: 3,
          strokeColor: "#16a34a",
          strokeOpacity: 0.95,
          fillColor: "#4ade80",
          fillOpacity: 0.82,
          zIndex: 8
        }});
        kakao.maps.event.addListener(node, "click", () => {{
          infoWindow.setContent(popupHtml(feature.properties));
          infoWindow.setPosition(position);
          infoWindow.open(map);
        }});
      }});

      if (!bounds.isEmpty()) {{
        map.setBounds(bounds);
      }}
    }}
  </script>
</body>
</html>
"""


def generate_preview(*, min_turn_degrees: float, output_html: Path, output_geojson: Path) -> dict[str, Any]:
    area = segment_graph_db.gangseo_dong_area("sinho")
    base_payload = segment_graph_db.build_csv_payload(
        node_csv=segment_graph_db.ETL_DIR / "gangseo_road_nodes_v4.csv",
        segment_csv=segment_graph_db.ETL_DIR / "gangseo_road_segments_v4.csv",
        output_html=output_html,
        output_geojson=output_geojson,
        bbox=segment_graph_db.area_bbox_tuple(area),
    )
    payload = split_payload_at_corners(base_payload, min_turn_degrees=min_turn_degrees)
    payload["meta"]["outputHtml"] = str(output_html)
    payload["meta"]["outputGeojson"] = str(output_geojson)
    payload["meta"]["localhostUrl"] = f"http://127.0.0.1:3000/etl/{output_html.name}"
    output_geojson.parent.mkdir(parents=True, exist_ok=True)
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_geojson.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_html.write_text(render_preview_html(payload), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Sinho-dong corner-node split preview HTML.")
    parser.add_argument("--min-turn-degrees", type=float, default=30.0)
    parser.add_argument("--output-html", type=Path, default=DEFAULT_OUTPUT_HTML)
    parser.add_argument("--output-geojson", type=Path, default=DEFAULT_OUTPUT_GEOJSON)
    args = parser.parse_args()
    payload = generate_preview(
        min_turn_degrees=args.min_turn_degrees,
        output_html=args.output_html,
        output_geojson=args.output_geojson,
    )
    print(
        json.dumps(
            {
                "outputHtml": str(args.output_html),
                "outputGeojson": str(args.output_geojson),
                "localhostUrl": payload["meta"]["localhostUrl"],
                "summary": payload["summary"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
