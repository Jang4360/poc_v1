from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import build_source_places_accessibility as base


POC_ROOT = Path(__file__).resolve().parents[1]
DATA_ADOPTED = POC_ROOT / "data" / "adopted"
ASSETS_DATA = POC_ROOT / "assets" / "data"
REPORT_DIR = POC_ROOT / "data" / "reports" / "facility_validation"

ADOPTED_WITH_ACCESSIBILITY = DATA_ADOPTED / "adopted_places_with_accessibility.csv"
FACILITIES_JS = ASSETS_DATA / "facilities-data.js"

OUT_CANDIDATES = REPORT_DIR / "facility_toilet_context_remove_rule_candidates.csv"
OUT_REMOVED = REPORT_DIR / "facility_toilet_context_remove_rule_removed_applied.csv"
OUT_SUMMARY = REPORT_DIR / "facility_toilet_context_remove_rule_summary.json"

TOILET_CATEGORIES = {"TOILET"}

TRANSIT_KEYWORDS = [
    "지하철",
    "도시철도",
    "철도",
    "전철",
    "부산1호선",
    "부산2호선",
    "부산3호선",
    "부산4호선",
    "동해선",
    "터미널",
    "버스터미널",
]
TRANSIT_NAME_SUFFIXES = ("역",)

PRIVATE_OR_COMMERCIAL_KEYWORDS = [
    "음식점",
    "식당",
    "카페",
    "커피",
    "제과",
    "주유소",
    "오일뱅크",
    "호텔",
    "모텔",
    "빌딩",
    "아파트",
]

SCHOOL_MILITARY_PRIVATE_KEYWORDS = [
    "학교",
    "초등",
    "중등",
    "고등",
    "대학교",
    "예비군",
    "군부대",
    "군사",
    "사격장",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows([{field: row.get(field, "") for field in fieldnames} for row in rows])


def load_facilities_geojson() -> dict[str, Any]:
    text = FACILITIES_JS.read_text(encoding="utf-8").strip()
    prefix = "window.FACILITIES_GEOJSON = "
    if not text.startswith(prefix):
        raise ValueError(f"Unexpected facilities-data.js format: {FACILITIES_JS}")
    if text.endswith(";"):
        text = text[:-1]
    return json.loads(text[len(prefix) :])


def write_facilities_geojson(features: list[dict[str, Any]]) -> None:
    FACILITIES_JS.write_text(
        "window.FACILITIES_GEOJSON = "
        + json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )


def split_pipe(value: str) -> list[str]:
    return [item for item in value.split("|") if item]


def text_blob(row: dict[str, str]) -> str:
    return " ".join(
        [
            row.get("name", ""),
            row.get("uiCategory", ""),
            row.get("facilityCategory", ""),
            row.get("rawFacilityType", ""),
            row.get("publicFacilityName", ""),
            row.get("publicFacilityType", ""),
            row.get("address", ""),
            row.get("reviewReasons", ""),
        ]
    )


def is_toilet(row: dict[str, str]) -> bool:
    return row.get("dbCategory") in TOILET_CATEGORIES or "화장실" in row.get("uiCategory", "")


def contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def station_name_hit(name: str) -> bool:
    if not name.endswith(TRANSIT_NAME_SUFFIXES):
        return False
    # Avoid false positives such as "주차장" by requiring a short station-like name
    # or explicit rail/transit context in the full text.
    return 2 <= len(name.replace(" ", "")) <= 12


def classify_remove_rule(row: dict[str, str]) -> tuple[str, str]:
    if not is_toilet(row):
        return "", ""

    name = row.get("name", "")
    blob = text_blob(row)

    if contains_any(blob, TRANSIT_KEYWORDS) or station_name_hit(name):
        return "REMOVE_TRANSIT_TOILET", "지하철역/철도역/터미널 화장실은 별도 편의시설 장소에서 제거"

    if contains_any(blob, PRIVATE_OR_COMMERCIAL_KEYWORDS):
        return "REMOVE_PRIVATE_COMMERCIAL_TOILET", "음식점/카페/주유소/호텔/빌딩/아파트 계열 내부 화장실 제거 후보 규칙 적용"

    if contains_any(blob, SCHOOL_MILITARY_PRIVATE_KEYWORDS):
        return "REMOVE_SCHOOL_MILITARY_PRIVATE_TOILET", "학교/예비군/군부대/사유시설 계열 내부 화장실 제거 후보 규칙 적용"

    return "", ""


def write_accessibility_summary(rows: list[dict[str, str]]) -> dict[str, Any]:
    access_counter: Counter[str] = Counter()
    places_with_access = 0
    for row in rows:
        values = split_pipe(row.get("erdAccessibilityTypes", ""))
        if values:
            places_with_access += 1
            access_counter.update(values)
    summary = {
        "totalRows": sum(access_counter.values()),
        "totalPlaces": places_with_access,
        "items": [
            {"featureType": key, "label": base.ERD_ACCESSIBILITY_LABELS.get(key, key), "count": access_counter[key]}
            for key in sorted(access_counter.keys(), key=lambda item: access_counter[item], reverse=True)
        ],
        "availableFeatureTypes": [
            {"featureType": key, "label": base.ERD_ACCESSIBILITY_LABELS.get(key, key), "count": access_counter[key]}
            for key in base.ERD_FEATURE_TYPES
        ],
    }
    base.SUMMARY_JS_OUT.write_text(
        "window.ACCESSIBILITY_SUMMARY = " + json.dumps(summary, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    return summary


def rebuild_outputs(kept: list[dict[str, str]], remove_keys: set[str]) -> tuple[int, int, int, int]:
    place_id_by_source_key: dict[str, int] = {}
    for index, row in enumerate(kept, start=1):
        place_id_by_source_key[row["sourceKey"]] = index
        row["placeId"] = str(index)

    adopted_place_rows = [base.to_place_table_row(row) for row in kept]
    adopted_accessibility_rows = [
        accessibility_row
        for row in kept
        for accessibility_row in base.to_accessibility_table_rows(row)
    ]
    erd_place_rows = [base.to_erd_place_table_row(row, place_id_by_source_key[row["sourceKey"]]) for row in kept]

    erd_accessibility_rows: list[dict[str, str]] = []
    next_accessibility_id = 1
    for row in kept:
        output_rows = base.to_erd_accessibility_table_rows(row, place_id_by_source_key[row["sourceKey"]], next_accessibility_id)
        erd_accessibility_rows.extend(output_rows)
        next_accessibility_id += len(output_rows)

    geojson = load_facilities_geojson()
    features = []
    for feature in geojson.get("features", []):
        source_key = feature.get("properties", {}).get("sourceId", "")
        if source_key in remove_keys or source_key not in place_id_by_source_key:
            continue
        props = feature["properties"]
        props["sourcePlaceId"] = props.get("sourcePlaceId", props.get("placeId", ""))
        props["placeId"] = str(place_id_by_source_key[source_key])
        features.append(feature)

    facility_review_rows = [base.to_facility_review_row(row, place_id_by_source_key[row["sourceKey"]]) for row in kept]
    review_priority_rank = {"F1": 0, "F2": 1, "F3": 2}
    facility_review_rows.sort(
        key=lambda row: (
            review_priority_rank.get(row["review_priority"], 9),
            -int(row["review_score"]),
            row["district_gu"],
            row["ui_category"],
            row["place_name"],
        )
    )

    original_fields = list(read_csv(ADOPTED_WITH_ACCESSIBILITY)[0].keys())
    write_csv(ADOPTED_WITH_ACCESSIBILITY, kept, original_fields)
    write_csv(base.ADOPTED_PLACES_TABLE_OUT, adopted_place_rows, base.PLACE_TABLE_FIELDS)
    write_csv(base.ADOPTED_ACCESSIBILITY_TABLE_OUT, adopted_accessibility_rows, base.ACCESSIBILITY_TABLE_FIELDS)
    write_csv(base.ERD_PLACES_TABLE_OUT, erd_place_rows, base.ERD_PLACE_TABLE_FIELDS)
    write_csv(base.ERD_ACCESSIBILITY_TABLE_OUT, erd_accessibility_rows, base.ERD_ACCESSIBILITY_TABLE_FIELDS)
    write_csv(base.FACILITY_REVIEW_CSV_OUT, facility_review_rows, base.FACILITY_REVIEW_FIELDS)
    write_facilities_geojson(features)
    write_accessibility_summary(kept)
    return len(adopted_accessibility_rows), len(erd_place_rows), len(erd_accessibility_rows), len(features)


def main() -> None:
    rows = read_csv(ADOPTED_WITH_ACCESSIBILITY)
    candidates = []
    for row in rows:
        rule, reason = classify_remove_rule(row)
        if rule:
            candidates.append({**row, "removeRule": rule, "removeReason": reason})

    if not candidates:
        print("no candidates")
        return

    remove_keys = {row["sourceKey"] for row in candidates}
    kept = [dict(row) for row in rows if row["sourceKey"] not in remove_keys]
    removed = [row for row in rows if row["sourceKey"] in remove_keys]

    candidate_fields = list(rows[0].keys()) + ["removeRule", "removeReason"]
    write_csv(OUT_CANDIDATES, candidates, candidate_fields)

    removed_by_key = {row["sourceKey"]: row for row in candidates}
    removed_output = []
    for row in removed:
        candidate = removed_by_key[row["sourceKey"]]
        removed_output.append({**row, "removeRule": candidate["removeRule"], "removeReason": candidate["removeReason"], "removedAt": datetime.now().isoformat()})
    write_csv(OUT_REMOVED, removed_output, list(removed_output[0].keys()))

    adopted_access_count, erd_places_count, erd_access_count, feature_count = rebuild_outputs(kept, remove_keys)

    summary = {
        "appliedAt": datetime.now().isoformat(),
        "inputPlacesBefore": len(rows),
        "removedPlaces": len(removed),
        "placesAfter": len(kept),
        "removedByRule": dict(Counter(row["removeRule"] for row in candidates)),
        "removedByUiCategory": dict(Counter(row["uiCategory"] for row in candidates)),
        "remainingByDbCategory": dict(Counter(row["dbCategory"] for row in kept)),
        "adoptedAccessibilityRowsAfter": adopted_access_count,
        "erdPlacesAfter": erd_places_count,
        "erdAccessibilityRowsAfter": erd_access_count,
        "mapFeaturesAfter": feature_count,
        "files": {
            "candidates": str(OUT_CANDIDATES),
            "removedApplied": str(OUT_REMOVED),
            "adoptedPlacesWithAccessibility": str(ADOPTED_WITH_ACCESSIBILITY),
            "erdPlaces": str(base.ERD_PLACES_TABLE_OUT),
            "erdAccessibility": str(base.ERD_ACCESSIBILITY_TABLE_OUT),
            "facilitiesMapJs": str(FACILITIES_JS),
        },
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
