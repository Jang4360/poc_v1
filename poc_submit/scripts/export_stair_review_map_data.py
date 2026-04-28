from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(r"C:\Users\SSAFY\Desktop\poc")
MAP_SOURCE = ROOT / "data" / "final" / "stairs" / "stair_second_pass_likely_adopt.csv"
OUT_GEOJSON = ROOT / "data" / "final" / "stairs" / "stair_second_pass_likely_adopt.geojson"
OUT_JS = ROOT / "assets" / "data" / "busan-stair-review-keep-review-data.js"
OUT_SUMMARY = ROOT / "data" / "final" / "stairs" / "stair_candidates_map_data_summary.json"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def parse_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def feature_from_row(row: dict[str, str]) -> dict[str, Any]:
    lat = parse_float(row.get("lat", ""))
    lng = parse_float(row.get("lng", ""))
    properties = dict(row)
    properties.pop("lat", None)
    properties.pop("lng", None)
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lng, lat]},
        "properties": properties,
    }


def main() -> None:
    rows = read_csv(MAP_SOURCE)
    collection = {
        "type": "FeatureCollection",
        "features": [feature_from_row(row) for row in rows],
    }
    OUT_GEOJSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_GEOJSON.write_text(json.dumps(collection, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    OUT_JS.write_text(
        "window.BUSAN_STAIR_REVIEW_GEOJSON = "
        + json.dumps(collection, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )
    summary = {
        "source": str(MAP_SOURCE),
        "geojson": str(OUT_GEOJSON),
        "js": str(OUT_JS),
        "total": len(rows),
        "priorityCounts": dict(Counter(row["priority"] for row in rows)),
        "districtCounts": dict(Counter(row["districtGu"] for row in rows)),
        "decisionCounts": dict(Counter(row["secondPassDecision"] for row in rows)),
        "note": "지도 계단 후보는 자동 2차 판정 LIKELY_ADOPT만 표시한다. JS 파일명은 index.html 호환을 위해 유지한다.",
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
