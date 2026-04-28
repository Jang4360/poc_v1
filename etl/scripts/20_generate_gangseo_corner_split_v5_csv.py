#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from etl.common import segment_graph_db

corner_preview = importlib.import_module("etl.scripts.19_generate_sinho_corner_node_preview")

DEFAULT_SOURCE_NODE_CSV = segment_graph_db.ETL_DIR / "gangseo_road_nodes_v4.csv"
DEFAULT_SOURCE_SEGMENT_CSV = segment_graph_db.ETL_DIR / "gangseo_road_segments_v4.csv"
DEFAULT_OUTPUT_NODE_CSV = segment_graph_db.ETL_DIR / "gangseo_road_nodes_v5.csv"
DEFAULT_OUTPUT_SEGMENT_CSV = segment_graph_db.ETL_DIR / "gangseo_road_segments_v5.csv"


def generate_v5_csv(
    *,
    source_node_csv: Path,
    source_segment_csv: Path,
    output_node_csv: Path,
    output_segment_csv: Path,
    min_turn_degrees: float,
) -> dict[str, object]:
    source_payload = segment_graph_db.build_csv_payload(
        node_csv=source_node_csv,
        segment_csv=source_segment_csv,
        output_html=segment_graph_db.CSV_EDIT_OUTPUT_HTML,
        output_geojson=segment_graph_db.CSV_EDIT_OUTPUT_GEOJSON,
    )
    split_payload = corner_preview.split_payload_at_corners(
        source_payload,
        min_turn_degrees=min_turn_degrees,
        node_key_prefix="gangseo_corner_v5",
        title="강서구 Road Boundary v5 corner-node split CSV",
        stage="gangseo-road-boundary-v5-corner-split-csv",
    )
    split_payload["meta"].update(
        {
            "districtGu": "강서구",
            "sourceNodeCsv": str(source_node_csv),
            "sourceSegmentCsv": str(source_segment_csv),
            "outputNodeCsv": str(output_node_csv),
            "outputSegmentCsv": str(output_segment_csv),
        }
    )
    report = segment_graph_db.write_csv_outputs(
        split_payload,
        node_csv=output_node_csv,
        segment_csv=output_segment_csv,
    )
    return {
        "source": {
            "nodeCsv": str(source_node_csv),
            "segmentCsv": str(source_segment_csv),
            "nodeCount": source_payload["summary"]["nodeCount"],
            "segmentCount": source_payload["summary"]["segmentCount"],
        },
        "output": report,
        "summary": split_payload["summary"],
        "minTurnDegrees": min_turn_degrees,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Gangseo v5 CSV by splitting v4 road-boundary lines at corner nodes.")
    parser.add_argument("--source-node-csv", type=Path, default=DEFAULT_SOURCE_NODE_CSV)
    parser.add_argument("--source-segment-csv", type=Path, default=DEFAULT_SOURCE_SEGMENT_CSV)
    parser.add_argument("--output-node-csv", type=Path, default=DEFAULT_OUTPUT_NODE_CSV)
    parser.add_argument("--output-segment-csv", type=Path, default=DEFAULT_OUTPUT_SEGMENT_CSV)
    parser.add_argument("--min-turn-degrees", type=float, default=30.0)
    args = parser.parse_args()
    report = generate_v5_csv(
        source_node_csv=args.source_node_csv,
        source_segment_csv=args.source_segment_csv,
        output_node_csv=args.output_node_csv,
        output_segment_csv=args.output_segment_csv,
        min_turn_degrees=args.min_turn_degrees,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
