#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from etl.common import haeundae_audio_signal_preview


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Haeundae audio signal preview from Busan public API.")
    parser.add_argument("--center-lat", type=float, default=haeundae_audio_signal_preview.DEFAULT_CENTER_LAT)
    parser.add_argument("--center-lon", type=float, default=haeundae_audio_signal_preview.DEFAULT_CENTER_LON)
    parser.add_argument("--radius-meter", type=int, default=haeundae_audio_signal_preview.DEFAULT_RADIUS_M)
    args = parser.parse_args()

    report = haeundae_audio_signal_preview.generate_preview(
        center_lat=args.center_lat,
        center_lon=args.center_lon,
        radius_m=args.radius_meter,
    )
    print("haeundae-audio-signal-preview: ok")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
