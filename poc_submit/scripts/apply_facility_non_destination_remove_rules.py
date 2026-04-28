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
MANUAL_REVIEW_SEED_JS = ASSETS_DATA / "manual-review-seed-data.js"

OUT_CANDIDATES = REPORT_DIR / "facility_non_destination_remove_rule_candidates.csv"
OUT_REMOVED = REPORT_DIR / "facility_non_destination_remove_rule_removed_applied.csv"
OUT_SUMMARY = REPORT_DIR / "facility_non_destination_remove_rule_summary.json"

REMOVE_SOURCE_KEYS = {
    "barrier_free_facility:3332": "카카오명이 티앤에이치로 확인되어 음식점/방문 목적지로 보기 어려움",
    "barrier_free_facility:6432": "원천은 휴게음식점이나 카카오명이 부성테크로 확인되어 공구/테크 계열로 판단",
    "barrier_free_facility:9365": "카카오명이 한국미쓰도요 부산지점으로 확인되어 회사/지점 계열로 판단",
    "barrier_free_facility:9634": "카카오명이 세우루브로 확인되어 산업/윤활유 계열 회사명으로 판단",
    "barrier_free_facility:12835": "카카오명이 대한이씨아이로 확인되어 회사명으로 판단",
}


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


def load_assignment(path: Path, variable_name: str) -> Any:
    text = path.read_text(encoding="utf-8").strip()
    prefix = f"window.{variable_name} = "
    if not text.startswith(prefix):
        raise ValueError(f"Unexpected JS assignment format: {path}")
    if text.endswith(";"):
        text = text[:-1]
    return json.loads(text[len(prefix) :])


def write_assignment(path: Path, variable_name: str, value: Any) -> None:
    path.write_text(
        f"window.{variable_name} = "
        + json.dumps(value, ensure_ascii=False, separators=(",", ":"))
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
    write_assignment(base.SUMMARY_JS_OUT, "ACCESSIBILITY_SUMMARY", summary)
    return summary


def rebuild_manual_review_seed(place_id_by_source_key: dict[str, int], remove_keys: set[str]) -> int:
    seed = load_assignment(MANUAL_REVIEW_SEED_JS, "MANUAL_REVIEW_SEED")
    rebuilt: dict[str, dict[str, Any]] = {}
    removed_count = 0

    for key, record in seed.items():
        if record.get("targetType") != "facility":
            rebuilt[key] = record
            continue

        source_key = record.get("sourceKey") or record.get("sourceId") or ""
        if source_key in remove_keys:
            removed_count += 1
            continue
        if source_key not in place_id_by_source_key:
            removed_count += 1
            continue

        new_place_id = str(place_id_by_source_key[source_key])
        new_key = f"facility:{new_place_id}"
        updated = dict(record)
        updated["key"] = new_key
        updated["targetId"] = new_place_id
        updated["placeId"] = new_place_id
        rebuilt[new_key] = updated

    write_assignment(MANUAL_REVIEW_SEED_JS, "MANUAL_REVIEW_SEED", rebuilt)
    return removed_count


def main() -> None:
    rows = read_csv(ADOPTED_WITH_ACCESSIBILITY)
    remove_keys = set(REMOVE_SOURCE_KEYS)
    rows_by_key = {row["sourceKey"]: row for row in rows}

    missing = sorted(remove_keys - set(rows_by_key))
    if missing and len(missing) == len(remove_keys):
        summary = {
            "alreadyApplied": True,
            "checkedAt": datetime.now().isoformat(),
            "placesAfter": len(rows),
            "missingSourceKeys": missing,
            "removedAppliedReport": str(OUT_REMOVED),
        }
        OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if missing:
        raise RuntimeError(f"Some remove source keys are not found: {missing}")

    removed = [{**rows_by_key[key], "removeRule": "REMOVE_COMPANY_NON_DESTINATION", "removeReason": reason} for key, reason in REMOVE_SOURCE_KEYS.items()]
    kept = [dict(row) for row in rows if row["sourceKey"] not in remove_keys]

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

    geojson = load_assignment(FACILITIES_JS, "FACILITIES_GEOJSON")
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

    write_csv(ADOPTED_WITH_ACCESSIBILITY, kept, list(rows[0].keys()))
    write_csv(base.ADOPTED_PLACES_TABLE_OUT, adopted_place_rows, base.PLACE_TABLE_FIELDS)
    write_csv(base.ADOPTED_ACCESSIBILITY_TABLE_OUT, adopted_accessibility_rows, base.ACCESSIBILITY_TABLE_FIELDS)
    write_csv(base.ERD_PLACES_TABLE_OUT, erd_place_rows, base.ERD_PLACE_TABLE_FIELDS)
    write_csv(base.ERD_ACCESSIBILITY_TABLE_OUT, erd_accessibility_rows, base.ERD_ACCESSIBILITY_TABLE_FIELDS)
    write_csv(base.FACILITY_REVIEW_CSV_OUT, facility_review_rows, base.FACILITY_REVIEW_FIELDS)
    write_assignment(FACILITIES_JS, "FACILITIES_GEOJSON", {"type": "FeatureCollection", "features": features})
    seed_removed_count = rebuild_manual_review_seed(place_id_by_source_key, remove_keys)
    accessibility_summary = write_accessibility_summary(kept)

    removed_output = [
        {**row, "removedAt": datetime.now().isoformat()}
        for row in removed
    ]
    output_fields = list(rows[0].keys()) + ["removeRule", "removeReason", "removedAt"]
    write_csv(OUT_CANDIDATES, removed, output_fields[:-1])
    write_csv(OUT_REMOVED, removed_output, output_fields)

    summary = {
        "appliedAt": datetime.now().isoformat(),
        "inputPlacesBefore": len(rows),
        "removedPlaces": len(removed),
        "placesAfter": len(kept),
        "removedSourceKeys": sorted(remove_keys),
        "removedNames": [row["name"] for row in removed],
        "removedBySourceCategory": dict(Counter(row.get("sourceCategory", "") for row in removed)),
        "removedByRawFacilityCategory": dict(Counter(row.get("rawFacilityCategory") or row.get("rawFacilityType", "") for row in removed)),
        "remainingByDbCategory": dict(Counter(row["dbCategory"] for row in kept)),
        "adoptedAccessibilityRowsAfter": len(adopted_accessibility_rows),
        "erdPlacesAfter": len(erd_place_rows),
        "erdAccessibilityRowsAfter": len(erd_accessibility_rows),
        "mapFeaturesAfter": len(features),
        "manualReviewSeedRemoved": seed_removed_count,
        "accessibilitySummary": accessibility_summary,
        "files": {
            "candidates": str(OUT_CANDIDATES),
            "removedApplied": str(OUT_REMOVED),
            "adoptedPlacesWithAccessibility": str(ADOPTED_WITH_ACCESSIBILITY),
            "erdPlaces": str(base.ERD_PLACES_TABLE_OUT),
            "erdAccessibility": str(base.ERD_ACCESSIBILITY_TABLE_OUT),
            "facilitiesMapJs": str(FACILITIES_JS),
            "manualReviewSeedJs": str(MANUAL_REVIEW_SEED_JS),
        },
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
