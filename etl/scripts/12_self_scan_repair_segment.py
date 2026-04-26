#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from etl.common import segment_self_scan_repair, subway_elevator_preview


def main() -> int:
    parser = argparse.ArgumentParser(description="Self-scan and repair generated segment preview geometry.")
    parser.add_argument("--input-geojson", type=Path, default=ROOT_DIR / "etl" / "segment.geojson")
    parser.add_argument("--output-geojson", type=Path, default=ROOT_DIR / "etl" / "segment_self_repaired.geojson")
    parser.add_argument("--output-html", type=Path, default=ROOT_DIR / "etl" / "segment_self_repaired.html")
    parser.add_argument("--report", type=Path, default=ROOT_DIR / "runtime" / "etl" / "segment-self-repair-report.json")
    parser.add_argument("--max-iterations", type=int, default=8)
    args = parser.parse_args()

    payload = segment_self_scan_repair.load_payload(args.input_geojson)
    repaired, report, _ = segment_self_scan_repair.run_self_scan_repair(
        payload,
        max_iterations=args.max_iterations,
    )
    output_payload = segment_self_scan_repair.build_payload_from_segments(
        payload,
        repaired["segments"],
        output_html=args.output_html,
        output_geojson=args.output_geojson,
        report=report,
    )
    args.output_geojson.parent.mkdir(parents=True, exist_ok=True)
    args.output_html.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    segment_self_scan_repair.write_payload(args.output_geojson, output_payload)
    args.output_html.write_text(subway_elevator_preview.render_html(output_payload), encoding="utf-8")
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print("segment-self-scan-repair: ok")
    print(json.dumps({
        "passed": report["passed"],
        "remainingActionableAnomalies": report["remainingActionableAnomalies"],
        "iterations": report["iterations"],
        "outputHtml": str(args.output_html),
        "outputGeojson": str(args.output_geojson),
        "report": str(args.report),
        "summary": output_payload["summary"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
