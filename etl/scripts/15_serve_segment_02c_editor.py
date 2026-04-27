#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from etl.common import segment_graph_db

DEFAULT_BBOX = (128.815, 35.055, 128.93, 35.135)
DEFAULT_NODE_CSV = segment_graph_db.ETL_DIR / "gangseo_road_nodes.csv"
DEFAULT_SEGMENT_CSV = segment_graph_db.ETL_DIR / "gangseo_road_segments.csv"
ALIAS_NODE_CSV = segment_graph_db.ETL_DIR / "road_nodes.csv"
ALIAS_SEGMENT_CSV = segment_graph_db.ETL_DIR / "road_segments.csv"


def parse_bbox(value: str | None) -> tuple[float, float, float, float]:
    if not value:
        return DEFAULT_BBOX
    values = tuple(float(item) for item in value.split(","))
    if len(values) != 4:
        raise ValueError("--bbox must be minLon,minLat,maxLon,maxLat")
    return values


def apply_and_render(
    *,
    edit_document: dict[str, Any],
    node_csv: Path,
    segment_csv: Path,
    output_html: Path,
    output_geojson: Path,
    bbox: tuple[float, float, float, float],
) -> dict[str, Any]:
    csv_report = segment_graph_db.apply_csv_edit_document(
        node_csv=node_csv,
        segment_csv=segment_csv,
        edit_document=edit_document,
    )
    if node_csv.resolve() != ALIAS_NODE_CSV.resolve():
        shutil.copyfile(node_csv, ALIAS_NODE_CSV)
    if segment_csv.resolve() != ALIAS_SEGMENT_CSV.resolve():
        shutil.copyfile(segment_csv, ALIAS_SEGMENT_CSV)
    payload = segment_graph_db.write_csv_edit_outputs(
        node_csv=node_csv,
        segment_csv=segment_csv,
        output_html=output_html,
        output_geojson=output_geojson,
        bbox=bbox,
    )
    return {
        "csv": csv_report,
        "aliases": {
            "nodeCsv": str(ALIAS_NODE_CSV),
            "segmentCsv": str(ALIAS_SEGMENT_CSV),
        },
        "preview": {
            "outputHtml": str(output_html),
            "outputGeojson": str(output_geojson),
            "localhostUrl": payload["meta"]["localhostUrl"],
            "nodeCount": payload["summary"]["nodeCount"],
            "segmentCount": payload["summary"]["segmentCount"],
            "segmentTypeCounts": payload["summary"]["segmentTypeCounts"],
        },
    }


class SegmentEditorHandler(SimpleHTTPRequestHandler):
    server_version = "Segment02CEditor/1.0"

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != "/api/segment-02c/apply-edits":
            self.send_error(404, "unknown endpoint")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            edit_document = json.loads(body.decode("utf-8"))
            if not isinstance(edit_document.get("edits"), list):
                raise ValueError("request JSON must contain edits[]")
            report = apply_and_render(
                edit_document=edit_document,
                node_csv=self.server.node_csv,  # type: ignore[attr-defined]
                segment_csv=self.server.segment_csv,  # type: ignore[attr-defined]
                output_html=self.server.output_html,  # type: ignore[attr-defined]
                output_geojson=self.server.output_geojson,  # type: ignore[attr-defined]
                bbox=self.server.bbox,  # type: ignore[attr-defined]
            )
        except Exception as exc:
            payload = json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False).encode("utf-8")
            self.send_response(500)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        payload = json.dumps({"ok": True, **report}, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the 02C edit UI and apply saved edits to CSV files.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3000)
    parser.add_argument("--node-csv", type=Path, default=DEFAULT_NODE_CSV)
    parser.add_argument("--segment-csv", type=Path, default=DEFAULT_SEGMENT_CSV)
    parser.add_argument("--output-html", type=Path, default=segment_graph_db.CSV_EDIT_OUTPUT_HTML)
    parser.add_argument("--output-geojson", type=Path, default=segment_graph_db.CSV_EDIT_OUTPUT_GEOJSON)
    parser.add_argument("--bbox", default=",".join(str(value) for value in DEFAULT_BBOX))
    args = parser.parse_args()

    handler = lambda *handler_args, **handler_kwargs: SegmentEditorHandler(  # noqa: E731
        *handler_args,
        directory=str(ROOT_DIR),
        **handler_kwargs,
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    server.node_csv = args.node_csv
    server.segment_csv = args.segment_csv
    server.output_html = args.output_html
    server.output_geojson = args.output_geojson
    server.bbox = parse_bbox(args.bbox)
    print(f"segment-02c-editor-server: http://{args.host}:{args.port}/etl/{args.output_html.name}")
    print("segment-02c-editor-server: POST /api/segment-02c/apply-edits updates Gangseo CSVs")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
