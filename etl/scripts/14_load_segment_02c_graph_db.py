#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from etl.common import segment_graph_db


def main() -> int:
    parser = argparse.ArgumentParser(description="Load 02C materialized graph payload into local PostGIS.")
    parser.add_argument(
        "--source-geojson",
        type=Path,
        default=segment_graph_db.DEFAULT_SOURCE_GEOJSON,
        help="02C graph payload to load.",
    )
    parser.add_argument(
        "--manual-edits",
        type=Path,
        help="Optional segment_02c_manual_edits.json exported by the edit UI.",
    )
    parser.add_argument(
        "--stage",
        choices=["export-csv", "apply-csv-edits", "load-db", "render-db", "render-edit-csv", "full"],
        default="full",
    )
    parser.add_argument("--node-csv", type=Path, default=segment_graph_db.CSV_NODE_OUTPUT)
    parser.add_argument("--segment-csv", type=Path, default=segment_graph_db.CSV_SEGMENT_OUTPUT)
    parser.add_argument("--output-html", type=Path, default=segment_graph_db.CSV_EDIT_OUTPUT_HTML)
    parser.add_argument("--output-geojson", type=Path, default=segment_graph_db.CSV_EDIT_OUTPUT_GEOJSON)
    parser.add_argument(
        "--bbox",
        help="Optional CSV render bbox as minLon,minLat,maxLon,maxLat.",
    )
    args = parser.parse_args()

    if args.stage == "export-csv":
        report = {
            "csv": segment_graph_db.export_graph_file_to_csv(
                source_geojson=args.source_geojson,
                manual_edits=args.manual_edits,
                node_csv=args.node_csv,
                segment_csv=args.segment_csv,
            )
        }
    elif args.stage == "apply-csv-edits":
        if args.manual_edits is None:
            raise ValueError("--manual-edits is required for --stage apply-csv-edits")
        report = {
            "csv": segment_graph_db.apply_csv_manual_edits(
                node_csv=args.node_csv,
                segment_csv=args.segment_csv,
                manual_edits=args.manual_edits,
            )
        }
    elif args.stage == "render-edit-csv":
        bbox = None
        if args.bbox:
            values = tuple(float(value) for value in args.bbox.split(","))
            if len(values) != 4:
                raise ValueError("--bbox must be minLon,minLat,maxLon,maxLat")
            bbox = values
        payload = segment_graph_db.write_csv_edit_outputs(
            node_csv=args.node_csv,
            segment_csv=args.segment_csv,
            output_html=args.output_html,
            output_geojson=args.output_geojson,
            bbox=bbox,
        )
        report = {
            "preview": {
                "outputHtml": str(args.output_html),
                "outputGeojson": str(args.output_geojson),
                "localhostUrl": payload["meta"]["localhostUrl"],
                "nodeCount": payload["summary"]["nodeCount"],
                "segmentCount": payload["summary"]["segmentCount"],
                "segmentTypeCounts": payload["summary"]["segmentTypeCounts"],
            }
        }
    elif args.stage == "render-db":
        payload = segment_graph_db.write_db_outputs()
        report = {
            "preview": {
                "outputHtml": str(segment_graph_db.DB_OUTPUT_HTML),
                "outputGeojson": str(segment_graph_db.DB_OUTPUT_GEOJSON),
                "nodeCount": payload["summary"]["nodeCount"],
                "segmentCount": payload["summary"]["segmentCount"],
                "segmentTypeCounts": payload["summary"]["segmentTypeCounts"],
            }
        }
    elif args.stage == "load-db":
        payload = segment_graph_db.load_json(args.source_geojson)
        if args.manual_edits is not None:
            payload = segment_graph_db.apply_manual_edits(payload, segment_graph_db.load_json(args.manual_edits))
        report = {"load": segment_graph_db.load_payload_to_db(payload)}
    else:
        report = segment_graph_db.load_graph_file_to_db(
            source_geojson=args.source_geojson,
            manual_edits=args.manual_edits,
        )

    print("segment-02c-graph-db: ok")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
