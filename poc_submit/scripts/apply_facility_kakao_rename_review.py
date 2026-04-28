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

OUT_APPLIED = REPORT_DIR / "facility_kakao_rename_review_applied.csv"
OUT_SUMMARY = REPORT_DIR / "facility_kakao_rename_review_summary.json"


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


def join_pipe(items: list[str]) -> str:
    output: list[str] = []
    for item in items:
        if item and item not in output:
            output.append(item)
    return "|".join(output)


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


def main() -> None:
    rows = read_csv(ADOPTED_WITH_ACCESSIBILITY)
    seed = load_assignment(MANUAL_REVIEW_SEED_JS, "MANUAL_REVIEW_SEED")

    rename_by_source_key: dict[str, dict[str, Any]] = {}
    for record in seed.values():
        if record.get("targetType") != "facility":
            continue
        if record.get("evidenceAction") != "RENAME_REVIEW":
            continue
        kakao_name = str(record.get("kakaoPlaceName") or "").strip()
        source_key = record.get("sourceKey") or record.get("sourceId") or ""
        if source_key and kakao_name:
            rename_by_source_key[source_key] = record

    if not rename_by_source_key:
        summary = {
            "alreadyApplied": True,
            "checkedAt": datetime.now().isoformat(),
            "places": len(rows),
        }
        OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return

    applied: list[dict[str, Any]] = []
    changed_source_keys: set[str] = set()
    updated_rows: list[dict[str, str]] = []
    now = datetime.now().isoformat()

    for row in rows:
        source_key = row["sourceKey"]
        record = rename_by_source_key.get(source_key)
        if not record:
            updated_rows.append(dict(row))
            continue

        before_name = row["name"]
        after_name = str(record.get("kakaoPlaceName") or "").strip()
        updated = dict(row)
        updated["name"] = after_name
        updated["reviewFlags"] = join_pipe(split_pipe(updated.get("reviewFlags", "")) + ["name_corrected", "kakao_rename_applied"])
        updated["reviewReasons"] = join_pipe(
            split_pipe(updated.get("reviewReasons", ""))
            + [f"카카오명 기준 표시명 보정: {before_name} -> {after_name}"]
        )
        updated_rows.append(updated)
        changed_source_keys.add(source_key)
        applied.append(
            {
                "sourceKey": source_key,
                "placeId": row["placeId"],
                "beforeName": before_name,
                "afterName": after_name,
                "dbCategory": row["dbCategory"],
                "uiCategory": row["uiCategory"],
                "districtGu": row["districtGu"],
                "address": row["address"],
                "kakaoDistanceM": record.get("kakaoDistanceM", ""),
                "poiName": record.get("poiName", ""),
                "poiDistanceM": record.get("poiDistanceM", ""),
                "appliedAt": now,
            }
        )

    place_id_by_source_key = {row["sourceKey"]: int(row["placeId"]) for row in updated_rows}
    adopted_place_rows = [base.to_place_table_row(row) for row in updated_rows]
    adopted_accessibility_rows = [
        accessibility_row
        for row in updated_rows
        for accessibility_row in base.to_accessibility_table_rows(row)
    ]
    erd_place_rows = [base.to_erd_place_table_row(row, place_id_by_source_key[row["sourceKey"]]) for row in updated_rows]

    erd_accessibility_rows: list[dict[str, str]] = []
    next_accessibility_id = 1
    for row in updated_rows:
        output_rows = base.to_erd_accessibility_table_rows(row, place_id_by_source_key[row["sourceKey"]], next_accessibility_id)
        erd_accessibility_rows.extend(output_rows)
        next_accessibility_id += len(output_rows)

    facility_review_rows = [base.to_facility_review_row(row, place_id_by_source_key[row["sourceKey"]]) for row in updated_rows]
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

    geojson = load_assignment(FACILITIES_JS, "FACILITIES_GEOJSON")
    for feature in geojson.get("features", []):
        props = feature.get("properties", {})
        source_key = props.get("sourceId", "")
        if source_key not in changed_source_keys:
            continue
        applied_row = next(item for item in applied if item["sourceKey"] == source_key)
        props["name"] = applied_row["afterName"]
        flags = props.get("reviewFlags") or []
        for flag in ["name_corrected", "kakao_rename_applied"]:
            if flag not in flags:
                flags.append(flag)
        props["reviewFlags"] = flags
        reasons = props.get("reviewReasons") or []
        reason = f"카카오명 기준 표시명 보정: {applied_row['beforeName']} -> {applied_row['afterName']}"
        if reason not in reasons:
            reasons.append(reason)
        props["reviewReasons"] = reasons

    for key, record in list(seed.items()):
        if record.get("targetType") != "facility":
            continue
        source_key = record.get("sourceKey") or record.get("sourceId") or ""
        if source_key not in changed_source_keys:
            continue
        applied_row = next(item for item in applied if item["sourceKey"] == source_key)
        record["name"] = applied_row["afterName"]
        record["status"] = "KEEP"
        record["statusLabel"] = "유지"
        record["evidenceAction"] = "KAKAO_RENAME_APPLIED"
        note = str(record.get("note") or "")
        append_note = f"[표시명보정] {applied_row['beforeName']} -> {applied_row['afterName']}"
        record["note"] = f"{note} / {append_note}" if note and append_note not in note else note or append_note
        record["updatedAt"] = now

    write_csv(ADOPTED_WITH_ACCESSIBILITY, updated_rows, list(rows[0].keys()))
    write_csv(base.ADOPTED_PLACES_TABLE_OUT, adopted_place_rows, base.PLACE_TABLE_FIELDS)
    write_csv(base.ADOPTED_ACCESSIBILITY_TABLE_OUT, adopted_accessibility_rows, base.ACCESSIBILITY_TABLE_FIELDS)
    write_csv(base.ERD_PLACES_TABLE_OUT, erd_place_rows, base.ERD_PLACE_TABLE_FIELDS)
    write_csv(base.ERD_ACCESSIBILITY_TABLE_OUT, erd_accessibility_rows, base.ERD_ACCESSIBILITY_TABLE_FIELDS)
    write_csv(base.FACILITY_REVIEW_CSV_OUT, facility_review_rows, base.FACILITY_REVIEW_FIELDS)
    write_assignment(FACILITIES_JS, "FACILITIES_GEOJSON", geojson)
    write_assignment(MANUAL_REVIEW_SEED_JS, "MANUAL_REVIEW_SEED", seed)
    accessibility_summary = write_accessibility_summary(updated_rows)

    write_csv(
        OUT_APPLIED,
        applied,
        [
            "sourceKey",
            "placeId",
            "beforeName",
            "afterName",
            "dbCategory",
            "uiCategory",
            "districtGu",
            "address",
            "kakaoDistanceM",
            "poiName",
            "poiDistanceM",
            "appliedAt",
        ],
    )

    summary = {
        "appliedAt": now,
        "renamedPlaces": len(applied),
        "placesAfter": len(updated_rows),
        "renamedByDbCategory": dict(Counter(row["dbCategory"] for row in applied)),
        "renamedByUiCategory": dict(Counter(row["uiCategory"] for row in applied)),
        "accessibilityRowsAfter": len(erd_accessibility_rows),
        "accessibilitySummary": accessibility_summary,
        "files": {
            "applied": str(OUT_APPLIED),
            "adoptedPlacesWithAccessibility": str(ADOPTED_WITH_ACCESSIBILITY),
            "facilitiesMapJs": str(FACILITIES_JS),
            "manualReviewSeedJs": str(MANUAL_REVIEW_SEED_JS),
        },
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
