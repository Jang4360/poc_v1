#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from etl.common.place_accessibility_mapper import (
    ACCESSIBILITY_CSV,
    PLACES_CSV,
    REPORT_JSON,
    SOURCE_CSV,
    remap_place_accessibility,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Regenerate place accessibility features from finalized source CSV.")
    parser.add_argument("--source", type=Path, default=SOURCE_CSV)
    parser.add_argument("--places", type=Path, default=PLACES_CSV)
    parser.add_argument("--seed", type=Path, default=ACCESSIBILITY_CSV)
    parser.add_argument("--output", type=Path, default=ACCESSIBILITY_CSV)
    parser.add_argument("--report", type=Path, default=REPORT_JSON)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    report = remap_place_accessibility(
        source_csv=args.source,
        places_csv=args.places,
        seed_csv=args.seed,
        output_csv=args.output,
        report_json=args.report,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
