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
MANUAL_REVIEW_CASES = REPORT_DIR / "facility_manual_review_required_cases.csv"
FACILITIES_JS = ASSETS_DATA / "facilities-data.js"
MANUAL_REVIEW_SEED_JS = ASSETS_DATA / "manual-review-seed-data.js"

OUT_CANDIDATES = REPORT_DIR / "facility_priority_manual_remove_candidates.csv"
OUT_REMOVED = REPORT_DIR / "facility_priority_manual_removed_applied.csv"
OUT_SUMMARY = REPORT_DIR / "facility_priority_manual_remove_summary.json"

REMOVE_REASON_CODES = {"MANUAL_REVIEW", "STATUS_NOT_KEEP"}


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


def rebuild_outputs(kept: list[dict[str, str]], remove_keys: set[str]) -> dict[str, Any]:
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

    write_csv(ADOPTED_WITH_ACCESSIBILITY, kept, list(read_csv(ADOPTED_WITH_ACCESSIBILITY)[0].keys()))
    write_csv(base.ADOPTED_PLACES_TABLE_OUT, adopted_place_rows, base.PLACE_TABLE_FIELDS)
    write_csv(base.ADOPTED_ACCESSIBILITY_TABLE_OUT, adopted_accessibility_rows, base.ACCESSIBILITY_TABLE_FIELDS)
    write_csv(base.ERD_PLACES_TABLE_OUT, erd_place_rows, base.ERD_PLACE_TABLE_FIELDS)
    write_csv(base.ERD_ACCESSIBILITY_TABLE_OUT, erd_accessibility_rows, base.ERD_ACCESSIBILITY_TABLE_FIELDS)
    write_csv(base.FACILITY_REVIEW_CSV_OUT, facility_review_rows, base.FACILITY_REVIEW_FIELDS)
    write_assignment(FACILITIES_JS, "FACILITIES_GEOJSON", {"type": "FeatureCollection", "features": features})
    seed_removed_count = rebuild_manual_review_seed(place_id_by_source_key, remove_keys)
    accessibility_summary = write_accessibility_summary(kept)

    return {
        "adoptedAccessibilityRowsAfter": len(adopted_accessibility_rows),
        "erdPlacesAfter": len(erd_place_rows),
        "erdAccessibilityRowsAfter": len(erd_accessibility_rows),
        "mapFeaturesAfter": len(features),
        "manualReviewSeedRemoved": seed_removed_count,
        "accessibilitySummary": accessibility_summary,
    }


def main() -> None:
    adopted_rows = read_csv(ADOPTED_WITH_ACCESSIBILITY)
    cases = read_csv(MANUAL_REVIEW_CASES)
    target_cases = [row for row in cases if row.get("reasonCode") in REMOVE_REASON_CODES]
    remove_keys = {row["sourceId"] for row in target_cases if row.get("sourceId")}

    if not remove_keys:
        raise RuntimeError("No priority manual review targets found.")

    adopted_by_key = {row["sourceKey"]: row for row in adopted_rows}
    present_remove_keys = remove_keys & set(adopted_by_key)

    if not present_remove_keys:
        summary = {
            "alreadyApplied": True,
            "checkedAt": datetime.now().isoformat(),
            "placesAfter": len(adopted_rows),
            "candidateCount": len(remove_keys),
            "missingSourceKeys": sorted(remove_keys),
        }
        OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    if present_remove_keys != remove_keys:
        missing = sorted(remove_keys - present_remove_keys)
        raise RuntimeError(f"Partial remove key mismatch. Missing: {missing}")

    removed = []
    case_by_source_key = {row["sourceId"]: row for row in target_cases}
    for source_key in sorted(remove_keys):
        row = adopted_by_key[source_key]
        case = case_by_source_key[source_key]
        removed.append(
            {
                **row,
                "removeRule": f"REMOVE_{case['reasonCode']}",
                "removeReason": "우선 수동검증 대상 25건은 서비스 표시 품질 리스크가 높아 제외하기로 결정",
                "caseReasonCode": case.get("reasonCode", ""),
                "caseCoordinateQuality": case.get("coordinateQuality", ""),
                "caseEvidenceAction": case.get("evidenceAction", ""),
                "caseStatus": case.get("status", ""),
                "caseKakaoPlaceName": case.get("kakaoPlaceName", ""),
                "caseKakaoDistanceM": case.get("kakaoDistanceM", ""),
                "casePoiName": case.get("poiName", ""),
                "casePoiDistanceM": case.get("poiDistanceM", ""),
            }
        )

    kept = [dict(row) for row in adopted_rows if row["sourceKey"] not in remove_keys]
    rebuild_summary = rebuild_outputs(kept, remove_keys)

    candidate_fields = list(target_cases[0].keys())
    removed_fields = list(adopted_rows[0].keys()) + [
        "removeRule",
        "removeReason",
        "caseReasonCode",
        "caseCoordinateQuality",
        "caseEvidenceAction",
        "caseStatus",
        "caseKakaoPlaceName",
        "caseKakaoDistanceM",
        "casePoiName",
        "casePoiDistanceM",
        "removedAt",
    ]
    now = datetime.now().isoformat()
    write_csv(OUT_CANDIDATES, target_cases, candidate_fields)
    write_csv(OUT_REMOVED, [{**row, "removedAt": now} for row in removed], removed_fields)

    summary = {
        "appliedAt": now,
        "inputPlacesBefore": len(adopted_rows),
        "removedPlaces": len(removed),
        "placesAfter": len(kept),
        "removedByReasonCode": dict(Counter(row["caseReasonCode"] for row in removed)),
        "removedByDbCategory": dict(Counter(row["dbCategory"] for row in removed)),
        "removedByUiCategory": dict(Counter(row["uiCategory"] for row in removed)),
        "remainingByDbCategory": dict(Counter(row["dbCategory"] for row in kept)),
        "files": {
            "candidates": str(OUT_CANDIDATES),
            "removedApplied": str(OUT_REMOVED),
            "adoptedPlacesWithAccessibility": str(ADOPTED_WITH_ACCESSIBILITY),
            "facilitiesMapJs": str(FACILITIES_JS),
            "manualReviewSeedJs": str(MANUAL_REVIEW_SEED_JS),
        },
        **rebuild_summary,
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
