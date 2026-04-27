#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from etl.common import segment_graph_auto_edit


def parse_bbox(value: str | None) -> tuple[float, float, float, float] | None:
    if value is None:
        return segment_graph_auto_edit.DEFAULT_TRAINING_BBOX
    if value.strip().lower() in {"none", "infer"}:
        return None
    values = tuple(float(item) for item in value.split(","))
    if len(values) != 4:
        raise ValueError("--training-bbox must be minLon,minLat,maxLon,maxLat")
    return values


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Learn from Gangseo 02C manual edits and generate review-only manual_edits "
            "candidates for the rest of the Gangseo CSV graph."
        )
    )
    parser.add_argument("--manual-edits", type=Path, required=True)
    parser.add_argument("--node-csv", type=Path, default=ROOT_DIR / "etl" / "gangseo_road_nodes.csv")
    parser.add_argument("--segment-csv", type=Path, default=ROOT_DIR / "etl" / "gangseo_road_segments.csv")
    parser.add_argument("--output-dir", type=Path, default=segment_graph_auto_edit.DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output-html", type=Path)
    parser.add_argument(
        "--training-bbox",
        default=",".join(str(value) for value in segment_graph_auto_edit.DEFAULT_TRAINING_BBOX),
        help="Training area to exclude from candidate generation, or 'infer' to use the manual edit extent.",
    )
    parser.add_argument(
        "--add-segment-type",
        choices=["SIDE_WALK", "SIDE_LINE", "learned"],
        default="learned",
        help="Segment type for generated add_segment candidates.",
    )
    parser.add_argument("--max-delete-candidates", type=int, default=500)
    parser.add_argument("--max-add-candidates", type=int, default=300)
    args = parser.parse_args()

    report = segment_graph_auto_edit.write_auto_edit_outputs(
        manual_edits=args.manual_edits,
        node_csv=args.node_csv,
        segment_csv=args.segment_csv,
        output_dir=args.output_dir,
        output_html=args.output_html,
        training_bbox=parse_bbox(args.training_bbox),
        output_add_segment_type=args.add_segment_type,
        max_delete_candidates=args.max_delete_candidates,
        max_add_candidates=args.max_add_candidates,
    )

    print("gangseo-auto-edit-candidates: ok")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
