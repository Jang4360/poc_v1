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
REMOVE_CANDIDATES = REPORT_DIR / "facility_kakao_poi_existence_rule_remove_candidates.csv"
EXISTENCE_ALL = REPORT_DIR / "facility_kakao_poi_existence_rule_all.csv"
APPLIED_REMOVED = REPORT_DIR / "facility_kakao_poi_existence_rule_removed_applied.csv"
APPLY_SUMMARY = REPORT_DIR / "facility_kakao_poi_existence_rule_apply_summary.json"

FACILITIES_JS = ASSETS_DATA / "facilities-data.js"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows([{field: row.get(field, "") for field in fieldnames} for row in rows])


def split_pipe(value: str) -> list[str]:
    return [item for item in value.split("|") if item]


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


def main() -> None:
    adopted_rows = read_csv(ADOPTED_WITH_ACCESSIBILITY)
    remove_rows = read_csv(REMOVE_CANDIDATES)
    remove_keys = {row["sourceKey"] for row in remove_rows}
    existence_by_key = {row["sourceKey"]: row for row in read_csv(EXISTENCE_ALL)}

    removed = [row for row in adopted_rows if row["sourceKey"] in remove_keys]
    kept = [dict(row) for row in adopted_rows if row["sourceKey"] not in remove_keys]

    if len(removed) != len(remove_keys):
        missing = sorted(remove_keys - {row["sourceKey"] for row in removed})
        raise RuntimeError(f"Remove keys not found in adopted data: {missing[:20]}")

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
    erd_place_rows = [
        base.to_erd_place_table_row(row, place_id_by_source_key[row["sourceKey"]])
        for row in kept
    ]

    erd_accessibility_rows: list[dict[str, str]] = []
    next_accessibility_id = 1
    for row in kept:
        place_id = place_id_by_source_key[row["sourceKey"]]
        output_rows = base.to_erd_accessibility_table_rows(row, place_id, next_accessibility_id)
        erd_accessibility_rows.extend(output_rows)
        next_accessibility_id += len(output_rows)

    geojson = load_facilities_geojson()
    features = []
    for feature in geojson.get("features", []):
        source_key = feature.get("properties", {}).get("sourceId", "")
        if source_key in remove_keys:
            continue
        if source_key not in place_id_by_source_key:
            continue
        props = feature["properties"]
        props["sourcePlaceId"] = props.get("sourcePlaceId", props.get("placeId", ""))
        props["placeId"] = str(place_id_by_source_key[source_key])
        features.append(feature)

    facility_review_rows = [
        base.to_facility_review_row(row, place_id_by_source_key[row["sourceKey"]])
        for row in kept
    ]
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

    write_csv(ADOPTED_WITH_ACCESSIBILITY, kept, list(adopted_rows[0].keys()))
    write_csv(base.ADOPTED_PLACES_TABLE_OUT, adopted_place_rows, base.PLACE_TABLE_FIELDS)
    write_csv(base.ADOPTED_ACCESSIBILITY_TABLE_OUT, adopted_accessibility_rows, base.ACCESSIBILITY_TABLE_FIELDS)
    write_csv(base.ERD_PLACES_TABLE_OUT, erd_place_rows, base.ERD_PLACE_TABLE_FIELDS)
    write_csv(base.ERD_ACCESSIBILITY_TABLE_OUT, erd_accessibility_rows, base.ERD_ACCESSIBILITY_TABLE_FIELDS)
    write_csv(base.FACILITY_REVIEW_CSV_OUT, facility_review_rows, base.FACILITY_REVIEW_FIELDS)
    write_facilities_geojson(features)
    accessibility_summary = write_accessibility_summary(kept)

    removed_output = []
    for row in removed:
        evidence = existence_by_key.get(row["sourceKey"], {})
        removed_output.append(
            {
                **row,
                "existenceStatus": evidence.get("existenceStatus", ""),
                "kakao_best_status": evidence.get("kakao_best_status", ""),
                "kakao_place_name": evidence.get("kakao_place_name", ""),
                "poi_match_status": evidence.get("poi_match_status", ""),
                "poi_name": evidence.get("poi_name", ""),
                "existenceReason": evidence.get("existenceReason", ""),
                "removedAt": datetime.now().isoformat(),
            }
        )
    write_csv(APPLIED_REMOVED, removed_output, list(removed_output[0].keys()))

    summary = {
        "appliedAt": datetime.now().isoformat(),
        "inputPlacesBefore": len(adopted_rows),
        "removedPlaces": len(removed),
        "placesAfter": len(kept),
        "adoptedAccessibilityRowsAfter": len(adopted_accessibility_rows),
        "erdPlacesAfter": len(erd_place_rows),
        "erdAccessibilityRowsAfter": len(erd_accessibility_rows),
        "mapFeaturesAfter": len(features),
        "removedByUiCategory": dict(Counter(row["uiCategory"] for row in removed)),
        "remainingByDbCategory": dict(Counter(row["dbCategory"] for row in kept)),
        "accessibilitySummary": accessibility_summary,
        "files": {
            "removedApplied": str(APPLIED_REMOVED),
            "adoptedPlacesWithAccessibility": str(ADOPTED_WITH_ACCESSIBILITY),
            "adoptedPlaces": str(base.ADOPTED_PLACES_TABLE_OUT),
            "adoptedAccessibility": str(base.ADOPTED_ACCESSIBILITY_TABLE_OUT),
            "erdPlaces": str(base.ERD_PLACES_TABLE_OUT),
            "erdAccessibility": str(base.ERD_ACCESSIBILITY_TABLE_OUT),
            "facilitiesMapJs": str(FACILITIES_JS),
            "accessibilitySummaryJs": str(base.SUMMARY_JS_OUT),
        },
    }
    APPLY_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
