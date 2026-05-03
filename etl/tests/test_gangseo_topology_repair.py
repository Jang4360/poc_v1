from __future__ import annotations

import csv
import importlib.util
from argparse import Namespace
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT_DIR / "graphhopper" / "scripts" / "repair_topology.py"


def load_module():
    spec = importlib.util.spec_from_file_location("repair_topology", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_repair_splits_base_edge_and_redirects_connector(tmp_path: Path) -> None:
    module = load_module()
    nodes = tmp_path / "nodes.csv"
    segments = tmp_path / "segments.csv"
    out = tmp_path / "out"
    node_fields = ["vertexId", "sourceNodeKey", "point"]
    segment_fields = ["edgeId", "fromNodeId", "toNodeId", "geom", "lengthMeter", "segmentType"]
    write_csv(
        nodes,
        [
            {"vertexId": "1", "sourceNodeKey": "a", "point": "SRID=4326;POINT(128.88000000 35.08000000)"},
            {"vertexId": "2", "sourceNodeKey": "b", "point": "SRID=4326;POINT(128.88010000 35.08000000)"},
            {"vertexId": "3", "sourceNodeKey": "old", "point": "SRID=4326;POINT(128.88005000 35.08000200)"},
            {"vertexId": "4", "sourceNodeKey": "c", "point": "SRID=4326;POINT(128.88005000 35.08005000)"},
        ],
        node_fields,
    )
    write_csv(
        segments,
        [
            {
                "edgeId": "10",
                "fromNodeId": "1",
                "toNodeId": "2",
                "geom": "SRID=4326;LINESTRING(128.88000000 35.08000000, 128.88010000 35.08000000)",
                "lengthMeter": "9.12",
                "segmentType": "SIDE_LINE",
            },
            {
                "edgeId": "20",
                "fromNodeId": "3",
                "toNodeId": "4",
                "geom": "SRID=4326;LINESTRING(128.88005000 35.08000200, 128.88005000 35.08005000)",
                "lengthMeter": "5.31",
                "segmentType": "SIDE_LINE",
            },
        ],
        segment_fields,
    )

    report = module.repair(
        Namespace(
            nodes=nodes,
            segments=segments,
            output_dir=out,
            output_nodes_name="nodes_v8.csv",
            output_segments_name="segments_v8.csv",
            bbox=(128.879, 35.079, 128.881, 35.081),
            split_distance_meter=1.0,
            endpoint_exclusion_meter=1.0,
            endpoint_merge_meter=1.0,
            cluster_projection_meter=1.0,
            max_endpoint_shift_floor_meter=2.0,
            max_endpoint_shift_ratio=0.2,
            remove_short_edge_meter=0.3,
            review_short_edge_meter=1.0,
        )
    )

    assert report["summary"]["canonicalNodesCreated"] == 1
    assert report["summary"]["oldNodesRedirected"] == 1
    with (out / "segments_v8.csv").open(newline="", encoding="utf-8") as fp:
        rows = list(csv.DictReader(fp))
    assert len(rows) == 3
    assert all(row["fromNodeId"] != row["toNodeId"] for row in rows)
