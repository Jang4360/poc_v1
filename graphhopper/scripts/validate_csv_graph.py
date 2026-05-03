#!/usr/bin/env python3
"""Validate Gangseo road CSV files before converting them to OSM/PBF."""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


REQUIRED_SEGMENT_COLUMNS = {"edgeId", "fromNodeId", "toNodeId", "geom", "segmentType"}
REQUIRED_NODE_COLUMNS = {"vertexId", "point"}
DEFAULT_SEGMENTS = Path("etl/raw/gangseo_road_segments_mapping_v2.csv")
DEFAULT_NODES = Path("etl/raw/gangseo_road_nodes_v8.csv")

ALLOWED_ENUMS = {
    "segmentType": {"SIDE_LINE", "SIDE_WALK"},
    "walkAccess": {"YES", "NO", "UNKNOWN"},
    "brailleBlockState": {"YES", "NO", "UNKNOWN"},
    "audioSignalState": {"YES", "NO", "UNKNOWN"},
    "slopeState": {"FLAT", "MODERATE", "STEEP", "RISK", "UNKNOWN"},
    "widthState": {"ADEQUATE_150", "ADEQUATE_120", "NARROW", "UNKNOWN"},
    "surfaceState": {"PAVED", "UNPAVED", "UNKNOWN"},
    "stairsState": {"YES", "NO", "UNKNOWN"},
    "signalState": {"TRAFFIC_SIGNALS", "NO", "UNKNOWN"},
}


def strip_srid(wkt: str) -> str:
    value = (wkt or "").strip()
    if value.upper().startswith("SRID="):
        _, value = value.split(";", 1)
    return value.strip()


def parse_point(wkt: str) -> tuple[float, float]:
    value = strip_srid(wkt)
    prefix = "POINT("
    if not value.upper().startswith(prefix) or not value.endswith(")"):
        raise ValueError("not a POINT WKT")
    coords = value[len(prefix) : -1].strip().split()
    if len(coords) != 2:
        raise ValueError("POINT must have two coordinates")
    return float(coords[0]), float(coords[1])


def parse_linestring(wkt: str) -> list[tuple[float, float]]:
    value = strip_srid(wkt)
    prefix = "LINESTRING("
    if not value.upper().startswith(prefix) or not value.endswith(")"):
        raise ValueError("not a LINESTRING WKT")
    points: list[tuple[float, float]] = []
    for raw_point in value[len(prefix) : -1].split(","):
        coords = raw_point.strip().split()
        if len(coords) != 2:
            raise ValueError("LINESTRING point must have two coordinates")
        points.append((float(coords[0]), float(coords[1])))
    if len(points) < 2:
        raise ValueError("LINESTRING must have at least two points")
    return points


def meters(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon1, lat1 = a
    lon2, lat2 = b
    lat_mid = math.radians((lat1 + lat2) / 2.0)
    dx = (lon2 - lon1) * 111_320.0 * math.cos(lat_mid)
    dy = (lat2 - lat1) * 110_540.0
    return math.hypot(dx, dy)


def line_length(points: Iterable[tuple[float, float]]) -> float:
    coords = list(points)
    return sum(meters(a, b) for a, b in zip(coords, coords[1:]))


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}
        self.size: Counter[str] = Counter()

    def add(self, item: str) -> None:
        if item not in self.parent:
            self.parent[item] = item
            self.size[item] = 1

    def find(self, item: str) -> str:
        self.add(item)
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[item] != item:
            parent = self.parent[item]
            self.parent[item] = root
            item = parent
        return root

    def union(self, a: str, b: str) -> None:
        root_a = self.find(a)
        root_b = self.find(b)
        if root_a == root_b:
            return
        if self.size[root_a] < self.size[root_b]:
            root_a, root_b = root_b, root_a
        self.parent[root_b] = root_a
        self.size[root_a] += self.size[root_b]


def sample(values: list[dict], limit: int) -> list[dict]:
    return values[:limit]


def validate(args: argparse.Namespace) -> dict:
    endpoint_tolerance = args.endpoint_tolerance_meter
    sample_limit = args.sample_limit

    with args.nodes.open(newline="", encoding="utf-8-sig") as fp:
        node_reader = csv.DictReader(fp)
        node_columns = set(node_reader.fieldnames or [])
        missing_node_columns = sorted(REQUIRED_NODE_COLUMNS - node_columns)
        nodes: dict[str, tuple[float, float]] = {}
        bad_nodes: list[dict] = []
        duplicate_nodes: list[dict] = []
        for line_no, row in enumerate(node_reader, start=2):
            node_id = (row.get("vertexId") or "").strip()
            if node_id in nodes:
                duplicate_nodes.append({"line": line_no, "vertexId": node_id})
                continue
            try:
                nodes[node_id] = parse_point(row.get("point", ""))
            except Exception as exc:
                bad_nodes.append({"line": line_no, "vertexId": node_id, "error": str(exc)})

    with args.segments.open(newline="", encoding="utf-8-sig") as fp:
        segment_reader = csv.DictReader(fp)
        segment_columns = set(segment_reader.fieldnames or [])
        missing_segment_columns = sorted(REQUIRED_SEGMENT_COLUMNS - segment_columns)

        edge_count = 0
        referenced_nodes: set[str] = set()
        bad_refs: list[dict] = []
        bad_geoms: list[dict] = []
        endpoint_mismatches: list[dict] = []
        enum_violations: dict[str, Counter[str]] = defaultdict(Counter)
        enum_samples: dict[str, list[dict]] = defaultdict(list)
        duplicate_edges: list[dict] = []
        self_loops: list[dict] = []
        edge_keys: dict[tuple[str, str], str] = {}
        duplicate_edge_ids: list[dict] = []
        edge_ids: set[str] = set()
        segment_type_counts: Counter[str] = Counter()
        uf = UnionFind()
        edge_count_by_root: Counter[str] = Counter()

        for line_no, row in enumerate(segment_reader, start=2):
            edge_count += 1
            edge_id = (row.get("edgeId") or "").strip()
            from_id = (row.get("fromNodeId") or "").strip()
            to_id = (row.get("toNodeId") or "").strip()
            segment_type_counts[(row.get("segmentType") or "").strip() or "(blank)"] += 1

            if edge_id in edge_ids:
                duplicate_edge_ids.append({"line": line_no, "edgeId": edge_id})
            edge_ids.add(edge_id)

            if from_id == to_id:
                self_loops.append({"line": line_no, "edgeId": edge_id, "nodeId": from_id})

            edge_key = (from_id, to_id)
            reverse_key = (to_id, from_id)
            if edge_key in edge_keys or reverse_key in edge_keys:
                duplicate_edges.append(
                    {
                        "line": line_no,
                        "edgeId": edge_id,
                        "fromNodeId": from_id,
                        "toNodeId": to_id,
                        "firstEdgeId": edge_keys.get(edge_key) or edge_keys.get(reverse_key),
                    }
                )
            else:
                edge_keys[edge_key] = edge_id

            for node_id, role in ((from_id, "fromNodeId"), (to_id, "toNodeId")):
                referenced_nodes.add(node_id)
                if node_id not in nodes:
                    bad_refs.append({"line": line_no, "edgeId": edge_id, "column": role, "nodeId": node_id})

            try:
                line = parse_linestring(row.get("geom", ""))
                length = line_length(line)
                if length <= args.zero_length_meter:
                    bad_geoms.append({"line": line_no, "edgeId": edge_id, "error": f"length {length:.3f}m"})
                if from_id in nodes:
                    from_gap = meters(line[0], nodes[from_id])
                    if from_gap > endpoint_tolerance:
                        endpoint_mismatches.append(
                            {
                                "line": line_no,
                                "edgeId": edge_id,
                                "column": "fromNodeId",
                                "nodeId": from_id,
                                "distanceMeter": round(from_gap, 3),
                            }
                        )
                if to_id in nodes:
                    to_gap = meters(line[-1], nodes[to_id])
                    if to_gap > endpoint_tolerance:
                        endpoint_mismatches.append(
                            {
                                "line": line_no,
                                "edgeId": edge_id,
                                "column": "toNodeId",
                                "nodeId": to_id,
                                "distanceMeter": round(to_gap, 3),
                            }
                        )
            except Exception as exc:
                bad_geoms.append({"line": line_no, "edgeId": edge_id, "error": str(exc)})

            for column, allowed in ALLOWED_ENUMS.items():
                if column not in segment_columns:
                    continue
                value = (row.get(column) or "").strip()
                if value and value not in allowed:
                    enum_violations[column][value] += 1
                    if len(enum_samples[column]) < sample_limit:
                        enum_samples[column].append({"line": line_no, "edgeId": edge_id, "value": value})

            if from_id in nodes and to_id in nodes and from_id != to_id:
                uf.union(from_id, to_id)

        for from_id, to_id in edge_keys:
            if from_id in nodes and to_id in nodes and from_id != to_id:
                edge_count_by_root[uf.find(from_id)] += 1

    isolated_nodes = sorted(set(nodes) - referenced_nodes, key=lambda x: int(x) if x.isdigit() else x)
    component_node_sizes: Counter[str] = Counter()
    for node_id in referenced_nodes:
        if node_id in nodes:
            component_node_sizes[uf.find(node_id)] += 1

    components = [
        {
            "componentId": root,
            "nodes": component_node_sizes[root],
            "edges": edge_count_by_root[root],
        }
        for root in component_node_sizes
    ]
    components.sort(key=lambda item: (item["edges"], item["nodes"]), reverse=True)
    small_components = [
        component
        for component in components
        if component["edges"] <= args.small_component_edge_threshold
    ]
    component_edge_bins = Counter()
    for component in components:
        edges = component["edges"]
        if edges == 1:
            component_edge_bins["1"] += 1
        elif edges <= 5:
            component_edge_bins["2-5"] += 1
        elif edges <= 10:
            component_edge_bins["6-10"] += 1
        elif edges <= 50:
            component_edge_bins["11-50"] += 1
        elif edges <= 100:
            component_edge_bins["51-100"] += 1
        else:
            component_edge_bins[">100"] += 1
    largest_component_edges = components[0]["edges"] if components else 0

    return {
        "inputs": {
            "segments": str(args.segments),
            "nodes": str(args.nodes),
            "endpointToleranceMeter": endpoint_tolerance,
            "smallComponentEdgeThreshold": args.small_component_edge_threshold,
        },
        "summary": {
            "segments": edge_count,
            "nodes": len(nodes),
            "segmentTypes": dict(segment_type_counts),
            "missingSegmentColumns": missing_segment_columns,
            "missingNodeColumns": missing_node_columns,
            "badNodeGeometries": len(bad_nodes),
            "duplicateNodeIds": len(duplicate_nodes),
            "badNodeReferences": len(bad_refs),
            "badSegmentGeometries": len(bad_geoms),
            "endpointMismatches": len(endpoint_mismatches),
            "enumViolationColumns": {column: sum(values.values()) for column, values in enum_violations.items()},
            "duplicateEdgeIds": len(duplicate_edge_ids),
            "duplicateNodePairEdges": len(duplicate_edges),
            "selfLoops": len(self_loops),
            "referencedNodes": len(referenced_nodes & set(nodes)),
            "isolatedNodes": len(isolated_nodes),
            "connectedComponents": len(components),
            "smallComponents": len(small_components),
            "componentEdgeBins": dict(component_edge_bins),
            "largestComponentEdges": largest_component_edges,
            "largestComponentEdgeRatio": round(largest_component_edges / edge_count, 6) if edge_count else 0,
            "smallComponentEdges": sum(component["edges"] for component in small_components),
        },
        "samples": {
            "badNodes": sample(bad_nodes, sample_limit),
            "duplicateNodes": sample(duplicate_nodes, sample_limit),
            "badNodeReferences": sample(bad_refs, sample_limit),
            "badSegmentGeometries": sample(bad_geoms, sample_limit),
            "endpointMismatches": sample(endpoint_mismatches, sample_limit),
            "enumViolations": {
                column: {
                    "counts": dict(values),
                    "samples": enum_samples[column],
                }
                for column, values in enum_violations.items()
            },
            "duplicateEdgeIds": sample(duplicate_edge_ids, sample_limit),
            "duplicateNodePairEdges": sample(duplicate_edges, sample_limit),
            "selfLoops": sample(self_loops, sample_limit),
            "isolatedNodes": isolated_nodes[:sample_limit],
            "largestComponents": components[:10],
            "smallComponents": small_components[:sample_limit],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--segments", type=Path, default=DEFAULT_SEGMENTS)
    parser.add_argument("--nodes", type=Path, default=DEFAULT_NODES)
    parser.add_argument("--endpoint-tolerance-meter", type=float, default=1.0)
    parser.add_argument("--zero-length-meter", type=float, default=0.01)
    parser.add_argument("--small-component-edge-threshold", type=int, default=5)
    parser.add_argument("--sample-limit", type=int, default=20)
    parser.add_argument("--report-json", type=Path)
    args = parser.parse_args()

    report = validate(args)
    if args.report_json:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
