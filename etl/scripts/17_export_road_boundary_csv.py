#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from etl.common import segment_graph_db


def coord_key(coord: list[float] | tuple[float, float]) -> str:
    return f"{float(coord[0]):.8f}:{float(coord[1]):.8f}"


def road_boundary_payload_to_csv_graph(payload: dict[str, Any], *, district: str) -> dict[str, Any]:
    source_segments = payload["layers"]["roadSegments"]["features"]
    nodes: list[dict[str, Any]] = []
    segments: list[dict[str, Any]] = []
    node_id_by_coord: dict[str, int] = {}
    degree: Counter[int] = Counter()

    def node_id_for(coord: list[float], *, key_suffix: str = "") -> int:
        key = f"{coord_key(coord)}{key_suffix}"
        if not key_suffix and key in node_id_by_coord:
            return node_id_by_coord[key]
        vertex_id = len(node_id_by_coord) + 1
        node_id_by_coord[key] = vertex_id
        nodes.append(
            {
                "type": "Feature",
                "properties": {
                    "vertexId": vertex_id,
                    "sourceNodeKey": f"road_boundary_v4:{key}",
                    "nodeType": "ROAD_BOUNDARY_ENDPOINT",
                    "degree": 0,
                    "endpointCount": 1,
                    "projectedKey": "",
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(coord[0]), float(coord[1])],
                },
            }
        )
        return vertex_id

    for edge_index, feature in enumerate(source_segments, start=1):
        coords = feature.get("geometry", {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        from_node_id = node_id_for(coords[0])
        to_node_id = node_id_for(coords[-1])
        if from_node_id == to_node_id:
            to_node_id = node_id_for(coords[-1], key_suffix=f":edge:{edge_index}:end")
        degree[from_node_id] += 1
        degree[to_node_id] += 1
        props = feature.get("properties", {})
        segments.append(
            {
                "type": "Feature",
                "properties": {
                    "edgeId": edge_index,
                    "fromNodeId": from_node_id,
                    "toNodeId": to_node_id,
                    "segmentType": props.get("segmentType", "ROAD_BOUNDARY"),
                    "lengthMeter": float(props.get("lengthMeter") or segment_graph_db.line_length_meter(coords)),
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[float(lng), float(lat)] for lng, lat in coords],
                },
            }
        )

    for node in nodes:
        node["properties"]["degree"] = degree[int(node["properties"]["vertexId"])]

    segment_counts = Counter(segment["properties"]["segmentType"] for segment in segments)
    meta = dict(payload.get("meta") or {})
    meta.update(
        {
            "title": f"{district} Road Boundary v4 CSV Edit UI",
            "districtGu": district,
            "stage": "road-boundary-buffer-union-csv-adapter",
            "csvAdapterRule": (
                "v2 road boundary GeoJSON keeps roadNodes empty; this CSV adapter creates endpoint nodes "
                "only so the manual edit UI can add/delete nodes and segments."
            ),
        }
    )
    return {
        "meta": meta,
        "summary": {
            "nodeCount": len(nodes),
            "segmentCount": len(segments),
            "segmentTypeCounts": [{"name": name, "count": count} for name, count in sorted(segment_counts.items())],
            "transitionConnectorCount": 0,
            "gapBridgeCount": 0,
            "cornerBridgeCount": 0,
            "sameSideCornerBridgeCount": 0,
            "crossSideCornerBridgeCount": 0,
            "crossingCount": 0,
            "elevatorConnectorCount": 0,
        },
        "layers": {
            "roadNodes": {"type": "FeatureCollection", "features": nodes},
            "roadSegments": {"type": "FeatureCollection", "features": segments},
        },
    }


def main_with_args(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export v2 road-boundary GeoJSON to editable road_nodes/road_segments CSVs.")
    parser.add_argument("--source-geojson", type=Path, required=True)
    parser.add_argument("--node-csv", type=Path, required=True)
    parser.add_argument("--segment-csv", type=Path, required=True)
    parser.add_argument("--district", default="강서구")
    args = parser.parse_args(argv)

    payload = json.loads(args.source_geojson.read_text(encoding="utf-8"))
    csv_payload = road_boundary_payload_to_csv_graph(payload, district=args.district)
    report = segment_graph_db.write_csv_outputs(csv_payload, node_csv=args.node_csv, segment_csv=args.segment_csv)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    return main_with_args()


if __name__ == "__main__":
    raise SystemExit(main())
