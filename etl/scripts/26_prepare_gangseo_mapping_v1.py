#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "etl" / "raw"
DEFAULT_INPUT = RAW_DIR / "gangseo_road_segments_v6_jooyoon.csv"
DEFAULT_OUTPUT = RAW_DIR / "gangseo_road_segments_mapping_v1.csv"

TARGET_FIELDS = [
    "edgeId",
    "fromNodeId",
    "toNodeId",
    "geom",
    "lengthMeter",
    "walkAccess",
    "avgSlopePercent",
    "widthMeter",
    "brailleBlockState",
    "audioSignalState",
    "slopeState",
    "widthState",
    "surfaceState",
    "stairsState",
    "signalState",
    "segmentType",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def normalize_segment_type(value: str) -> str:
    segment_type = value.strip().upper()
    if segment_type in {"ROAD_BOUNDARY", "ROAD_BOUNDARY_INNER"}:
        return "SIDE_LINE"
    return segment_type


def normalize_row(row: dict[str, str]) -> dict[str, str]:
    return {
        "edgeId": row.get("edgeId", ""),
        "fromNodeId": row.get("fromNodeId", ""),
        "toNodeId": row.get("toNodeId", ""),
        "geom": row.get("geom", ""),
        "lengthMeter": row.get("lengthMeter", ""),
        "walkAccess": row.get("walkAccess") or "UNKNOWN",
        "avgSlopePercent": row.get("avgSlopePercent", ""),
        "widthMeter": row.get("widthMeter", ""),
        "brailleBlockState": row.get("brailleBlockState") or "UNKNOWN",
        "audioSignalState": row.get("audioSignalState") or "UNKNOWN",
        "slopeState": "UNKNOWN",
        "widthState": row.get("widthState") or "UNKNOWN",
        "surfaceState": row.get("surfaceState") or "UNKNOWN",
        "stairsState": row.get("stairsState") or "UNKNOWN",
        "signalState": "UNKNOWN",
        "segmentType": normalize_segment_type(row.get("segmentType", "")),
    }


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=TARGET_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare full Gangseo mapping v1 CSV from v6_jooyoon graph segments.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    source_rows = read_csv(args.input)
    output_rows = [normalize_row(row) for row in source_rows]
    write_csv(args.output, output_rows)

    report = {
        "input": str(args.input),
        "output": str(args.output),
        "source_rows": len(source_rows),
        "output_rows": len(output_rows),
        "source_segment_type_counts": Counter(row.get("segmentType", "") for row in source_rows),
        "output_segment_type_counts": Counter(row.get("segmentType", "") for row in output_rows),
        "removed_columns": ["elevatorState"],
        "renamed_or_replaced_columns": {
            "rampState": "slopeState",
            "crossingState": "signalState",
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
