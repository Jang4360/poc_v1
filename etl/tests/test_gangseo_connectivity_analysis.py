from __future__ import annotations

import csv
import importlib.util
from argparse import Namespace
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT_DIR / "graphhopper" / "scripts" / "analyze_connectivity.py"


def load_module():
    spec = importlib.util.spec_from_file_location("analyze_connectivity", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_analyze_generates_endpoint_and_split_candidates(tmp_path: Path) -> None:
    module = load_module()
    nodes = tmp_path / "nodes.csv"
    segments = tmp_path / "segments.csv"
    write_csv(
        nodes,
        [
            {"vertexId": "1", "point": "SRID=4326;POINT(128.88000000 35.08000000)"},
            {"vertexId": "2", "point": "SRID=4326;POINT(128.88005000 35.08000000)"},
            {"vertexId": "3", "point": "SRID=4326;POINT(128.88010000 35.08000000)"},
            {"vertexId": "4", "point": "SRID=4326;POINT(128.88011000 35.08000000)"},
            {"vertexId": "5", "point": "SRID=4326;POINT(128.88002500 35.08000500)"},
            {"vertexId": "6", "point": "SRID=4326;POINT(128.88002500 35.08002000)"},
        ],
        ["vertexId", "point"],
    )
    write_csv(
        segments,
        [
            {
                "edgeId": "10",
                "fromNodeId": "1",
                "toNodeId": "2",
                "geom": "SRID=4326;LINESTRING(128.88000000 35.08000000, 128.88005000 35.08000000)",
                "segmentType": "SIDE_LINE",
            },
            {
                "edgeId": "20",
                "fromNodeId": "3",
                "toNodeId": "4",
                "geom": "SRID=4326;LINESTRING(128.88010000 35.08000000, 128.88011000 35.08000000)",
                "segmentType": "SIDE_LINE",
            },
            {
                "edgeId": "30",
                "fromNodeId": "5",
                "toNodeId": "6",
                "geom": "SRID=4326;LINESTRING(128.88002500 35.08000500, 128.88002500 35.08002000)",
                "segmentType": "SIDE_LINE",
            },
        ],
        ["edgeId", "fromNodeId", "toNodeId", "geom", "segmentType"],
    )

    report = module.analyze(
        Namespace(
            nodes=nodes,
            segments=segments,
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
            max_candidates=100,
        )
    )

    candidate_types = {candidate["type"] for candidate in report["candidates"]}
    assert "ENDPOINT_TO_ENDPOINT" in candidate_types
    assert "SPLIT_AND_CONNECT" in candidate_types
    assert report["summary"]["componentCount"] == 3
    assert report["summary"]["candidateColorCounts"]["orange"] >= 1
    assert report["summary"]["candidateColorCounts"]["yellow"] >= 1


def test_analyze_hides_far_endpoint_candidates_as_low_priority(tmp_path: Path) -> None:
    module = load_module()
    nodes = tmp_path / "nodes.csv"
    segments = tmp_path / "segments.csv"
    write_csv(
        nodes,
        [
            {"vertexId": "1", "point": "SRID=4326;POINT(128.88000000 35.08000000)"},
            {"vertexId": "2", "point": "SRID=4326;POINT(128.88001000 35.08000000)"},
            {"vertexId": "3", "point": "SRID=4326;POINT(128.88015000 35.08000000)"},
            {"vertexId": "4", "point": "SRID=4326;POINT(128.88016000 35.08000000)"},
        ],
        ["vertexId", "point"],
    )
    write_csv(
        segments,
        [
            {
                "edgeId": "10",
                "fromNodeId": "1",
                "toNodeId": "2",
                "geom": "SRID=4326;LINESTRING(128.88000000 35.08000000, 128.88001000 35.08000000)",
                "segmentType": "SIDE_LINE",
            },
            {
                "edgeId": "20",
                "fromNodeId": "3",
                "toNodeId": "4",
                "geom": "SRID=4326;LINESTRING(128.88015000 35.08000000, 128.88016000 35.08000000)",
                "segmentType": "SIDE_LINE",
            },
        ],
        ["edgeId", "fromNodeId", "toNodeId", "geom", "segmentType"],
    )

    report = module.analyze(
        Namespace(
            nodes=nodes,
            segments=segments,
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
            max_candidates=100,
        )
    )

    assert report["summary"]["candidateCount"] == 0
    assert report["summary"]["lowPriorityCandidateCount"] >= 1
