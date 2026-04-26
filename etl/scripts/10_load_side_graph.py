#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from etl.common import side_graph_loader, subway_elevator_preview


def main() -> int:
    parser = argparse.ArgumentParser(description="Build side graph snapshots and optional preview.")
    parser.add_argument("--center-lat", type=float, default=subway_elevator_preview.DEFAULT_CENTER_LAT)
    parser.add_argument("--center-lon", type=float, default=subway_elevator_preview.DEFAULT_CENTER_LON)
    parser.add_argument("--radius-meter", type=int, default=subway_elevator_preview.DEFAULT_RADIUS_M)
    parser.add_argument("--load-db", action="store_true", help="Load generated side graph into PostGIS.")
    parser.add_argument("--output-html", type=Path, default=subway_elevator_preview.OUTPUT_HTML)
    parser.add_argument("--output-geojson", type=Path, default=subway_elevator_preview.OUTPUT_GEOJSON)
    args = parser.parse_args()

    payload, report, audit = side_graph_loader.generate_preview_dataset(
        center_lat=args.center_lat,
        center_lon=args.center_lon,
        radius_m=args.radius_meter,
    )
    payload["meta"]["outputHtml"] = str(args.output_html)
    payload["meta"]["outputGeojson"] = str(args.output_geojson)
    payload["meta"]["localhostUrl"] = f"http://127.0.0.1:3000/etl/{args.output_html.name}"
    args.output_geojson.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.output_html.write_text(
        subway_elevator_preview.render_html(payload),
        encoding="utf-8",
    )
    preview = {
        **payload["summary"],
        "outputHtml": str(args.output_html),
        "outputGeojson": str(args.output_geojson),
    }

    result = {
        "snapshot": report,
        "topology": audit,
        "preview": preview,
        "dbLoad": {"loaded": False},
    }
    if args.load_db:
        nodes, segments, _ = side_graph_loader.build_side_graph(
            center_lat=args.center_lat,
            center_lon=args.center_lon,
            radius_m=args.radius_meter,
        )
        result["dbLoad"] = side_graph_loader.load_db(nodes, segments)

    print("side-graph-load: ok")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
