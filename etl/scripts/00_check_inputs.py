#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


ETL_DIR = Path(__file__).resolve().parents[1]
RAW_DIR = ETL_DIR / "raw"

REQUIRED_INPUTS = [
    "N3L_A0020000_26.shp",
    "N3L_A0020000_26.shx",
    "N3L_A0020000_26.dbf",
    "N3L_A0020000_26.prj",
    "place_merged_broad_category_final.csv",
    "place_accessibility_features_merged_final.csv",
    "stg_audio_signals_ready.csv",
    "stg_crosswalks_ready.csv",
    "slope_analysis_staging.csv",
    "subway_station_elevators_erd_ready.csv",
    "부산광역시_시내버스 업체별 연도별 버스 등록대수_20260330.csv",
]


def main() -> int:
    missing = [name for name in REQUIRED_INPUTS if not (RAW_DIR / name).exists()]
    if missing:
        print("etl-inputs: missing required files")
        for name in missing:
            print(f"- {name}")
        return 1

    print("etl-inputs: ok")
    print(f"raw_dir={RAW_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
