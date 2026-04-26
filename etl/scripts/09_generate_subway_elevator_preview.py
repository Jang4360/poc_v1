#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import argparse
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from etl.common import subway_elevator_preview


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate subway elevator preview HTML.")
    parser.add_argument("--center-lat", type=float, default=subway_elevator_preview.DEFAULT_CENTER_LAT)
    parser.add_argument("--center-lon", type=float, default=subway_elevator_preview.DEFAULT_CENTER_LON)
    parser.add_argument("--radius-meter", type=int, default=subway_elevator_preview.DEFAULT_RADIUS_M)
    args = parser.parse_args()

    report = subway_elevator_preview.generate_preview(
        center_lat=args.center_lat,
        center_lon=args.center_lon,
        radius_m=args.radius_meter,
    )
    print("subway-elevator-preview: ok")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
