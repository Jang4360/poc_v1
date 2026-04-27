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

from etl.common import segment_graph_auto_edit, segment_graph_db

DEFAULT_BBOX = (128.815, 35.055, 128.93, 35.135)
DEFAULT_NODE_CSV = segment_graph_db.ETL_DIR / "gangseo_road_nodes.csv"
DEFAULT_SEGMENT_CSV = segment_graph_db.ETL_DIR / "gangseo_road_segments.csv"
ALIAS_NODE_CSV = segment_graph_db.ETL_DIR / "road_nodes.csv"
ALIAS_SEGMENT_CSV = segment_graph_db.ETL_DIR / "road_segments.csv"
DEFAULT_CANDIDATE_JSON = segment_graph_auto_edit.DEFAULT_OUTPUT_DIR / "gangseo_02c_auto_manual_edit_candidates.json"
DEFAULT_APPROVED_JSON = segment_graph_auto_edit.DEFAULT_APPROVED_JSON


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
    meta = edit_document.get("meta") or {}
    if meta.get("doNotApplyWithoutHumanApproval") is True and meta.get("approvedOnly") is not True:
        raise ValueError("auto edit candidates cannot be applied before human approval")
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


def save_candidate_review(
    *,
    reviewed_document: dict[str, Any],
    candidate_json: Path,
    approved_json: Path,
) -> dict[str, Any]:
    if not isinstance(reviewed_document.get("edits"), list):
        raise ValueError("review JSON must contain edits[]")
    for edit in reviewed_document["edits"]:
        if not edit.get("reviewId"):
            raise ValueError("every reviewed edit must contain reviewId")
        review = edit.get("review")
        if not isinstance(review, dict) or "approved" not in review:
            raise ValueError("every reviewed edit must contain review.approved")
    approved_document = segment_graph_auto_edit.approved_review_document(reviewed_document)
    candidate_json.parent.mkdir(parents=True, exist_ok=True)
    approved_json.parent.mkdir(parents=True, exist_ok=True)
    candidate_json.write_text(json.dumps(reviewed_document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    approved_json.write_text(json.dumps(approved_document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "candidateJson": str(candidate_json),
        "approvedJson": str(approved_json),
        "approvedCount": len(approved_document["edits"]),
        "totalCount": len(reviewed_document["edits"]),
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
        path = self.path.split("?", 1)[0]
        if path not in {"/api/segment-02c/apply-edits", "/api/gangseo-auto-edit/save-review"}:
            self.send_error(404, "unknown endpoint")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            request_document = json.loads(body.decode("utf-8"))
            if path == "/api/segment-02c/apply-edits":
                if not isinstance(request_document.get("edits"), list):
                    raise ValueError("request JSON must contain edits[]")
                report = apply_and_render(
                    edit_document=request_document,
                    node_csv=self.server.node_csv,  # type: ignore[attr-defined]
                    segment_csv=self.server.segment_csv,  # type: ignore[attr-defined]
                    output_html=self.server.output_html,  # type: ignore[attr-defined]
                    output_geojson=self.server.output_geojson,  # type: ignore[attr-defined]
                    bbox=self.server.bbox,  # type: ignore[attr-defined]
                )
            else:
                report = {
                    "review": save_candidate_review(
                        reviewed_document=request_document,
                        candidate_json=self.server.candidate_json,  # type: ignore[attr-defined]
                        approved_json=self.server.approved_json,  # type: ignore[attr-defined]
                    )
                }
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
    parser.add_argument("--candidate-json", type=Path, default=DEFAULT_CANDIDATE_JSON)
    parser.add_argument("--approved-json", type=Path, default=DEFAULT_APPROVED_JSON)
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
    server.candidate_json = args.candidate_json
    server.approved_json = args.approved_json
    server.bbox = parse_bbox(args.bbox)
    print(f"segment-02c-editor-server: http://{args.host}:{args.port}/etl/{args.output_html.name}")
    print("segment-02c-editor-server: POST /api/segment-02c/apply-edits updates Gangseo CSVs")
    print("segment-02c-editor-server: POST /api/gangseo-auto-edit/save-review updates review JSON")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
