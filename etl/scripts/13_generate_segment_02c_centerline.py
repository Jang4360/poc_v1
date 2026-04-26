#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from etl.common import segment_centerline_02c


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate 02C Kakao preview artifacts.")
    parser.add_argument(
        "--variant",
        choices=[
            "centerline",
            "sideline",
            "sideline-intersection",
            "sideline-intersection-01",
            "sideline-intersection-02",
            "sideline-intersection-03",
            "graph-materialized",
            "graph-edit",
            "sideline-centerline-pruned",
        ],
        default="centerline",
    )
    parser.add_argument("--center-lat", type=float, default=segment_centerline_02c.DEFAULT_CENTER_LAT)
    parser.add_argument("--center-lon", type=float, default=segment_centerline_02c.DEFAULT_CENTER_LON)
    parser.add_argument("--radius-meter", type=int, default=segment_centerline_02c.DEFAULT_RADIUS_M)
    parser.add_argument("--output-html", type=Path)
    parser.add_argument("--output-geojson", type=Path)
    args = parser.parse_args()

    if args.variant == "graph-edit":
        output_html = args.output_html or segment_centerline_02c.GRAPH_EDIT_OUTPUT_HTML
        output_geojson = args.output_geojson or segment_centerline_02c.GRAPH_MATERIALIZED_OUTPUT_GEOJSON
        payload = segment_centerline_02c.write_graph_edit_outputs(
            output_html=output_html,
            center_lat=args.center_lat,
            center_lon=args.center_lon,
            radius_m=args.radius_meter,
        )
    elif args.variant == "graph-materialized":
        output_html = args.output_html or segment_centerline_02c.GRAPH_MATERIALIZED_OUTPUT_HTML
        output_geojson = args.output_geojson or segment_centerline_02c.GRAPH_MATERIALIZED_OUTPUT_GEOJSON
        payload = segment_centerline_02c.write_graph_materialized_outputs(
            output_html=output_html,
            output_geojson=output_geojson,
            center_lat=args.center_lat,
            center_lon=args.center_lon,
            radius_m=args.radius_meter,
        )
    elif args.variant == "sideline-intersection-03":
        output_html = args.output_html or segment_centerline_02c.CLUSTERED_INTERSECTION_OUTPUT_HTML
        output_geojson = args.output_geojson or segment_centerline_02c.CLUSTERED_INTERSECTION_OUTPUT_GEOJSON
        payload = segment_centerline_02c.write_sideline_intersection_03_outputs(
            output_html=output_html,
            output_geojson=output_geojson,
            center_lat=args.center_lat,
            center_lon=args.center_lon,
            radius_m=args.radius_meter,
        )
    elif args.variant == "sideline-intersection-02":
        output_html = args.output_html or segment_centerline_02c.NEAR_CROSS_INTERSECTION_OUTPUT_HTML
        output_geojson = args.output_geojson or segment_centerline_02c.NEAR_CROSS_INTERSECTION_OUTPUT_GEOJSON
        payload = segment_centerline_02c.write_sideline_intersection_02_outputs(
            output_html=output_html,
            output_geojson=output_geojson,
            center_lat=args.center_lat,
            center_lon=args.center_lon,
            radius_m=args.radius_meter,
        )
    elif args.variant == "sideline-intersection-01":
        output_html = args.output_html or segment_centerline_02c.CANDIDATE_INTERSECTION_OUTPUT_HTML
        output_geojson = args.output_geojson or segment_centerline_02c.CANDIDATE_INTERSECTION_OUTPUT_GEOJSON
        payload = segment_centerline_02c.write_sideline_intersection_01_outputs(
            output_html=output_html,
            output_geojson=output_geojson,
            center_lat=args.center_lat,
            center_lon=args.center_lon,
            radius_m=args.radius_meter,
        )
    elif args.variant == "sideline-centerline-pruned":
        output_html = args.output_html or segment_centerline_02c.CENTERLINE_PRUNED_OUTPUT_HTML
        output_geojson = args.output_geojson or segment_centerline_02c.CENTERLINE_PRUNED_OUTPUT_GEOJSON
        payload = segment_centerline_02c.write_sideline_centerline_pruned_outputs(
            output_html=output_html,
            output_geojson=output_geojson,
            center_lat=args.center_lat,
            center_lon=args.center_lon,
            radius_m=args.radius_meter,
        )
    elif args.variant == "sideline-intersection":
        output_html = args.output_html or segment_centerline_02c.INTERSECTION_OUTPUT_HTML
        output_geojson = args.output_geojson or segment_centerline_02c.INTERSECTION_OUTPUT_GEOJSON
        payload = segment_centerline_02c.write_sideline_intersection_outputs(
            output_html=output_html,
            output_geojson=output_geojson,
            center_lat=args.center_lat,
            center_lon=args.center_lon,
            radius_m=args.radius_meter,
        )
    elif args.variant == "sideline":
        output_html = args.output_html or segment_centerline_02c.SIDELINE_OUTPUT_HTML
        output_geojson = args.output_geojson or segment_centerline_02c.SIDELINE_OUTPUT_GEOJSON
        payload = segment_centerline_02c.write_sideline_outputs(
            output_html=output_html,
            output_geojson=output_geojson,
            center_lat=args.center_lat,
            center_lon=args.center_lon,
            radius_m=args.radius_meter,
        )
    else:
        output_html = args.output_html or segment_centerline_02c.OUTPUT_HTML
        output_geojson = args.output_geojson or segment_centerline_02c.OUTPUT_GEOJSON
        payload = segment_centerline_02c.write_outputs(
            output_html=output_html,
            output_geojson=output_geojson,
            center_lat=args.center_lat,
            center_lon=args.center_lon,
            radius_m=args.radius_meter,
        )
    print(f"segment-02c-{args.variant}: ok")
    print(
        json.dumps(
            {
                "outputHtml": str(output_html),
                "outputGeojson": str(output_geojson),
                "meta": payload["meta"],
                "summary": payload["summary"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
