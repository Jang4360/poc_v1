from __future__ import annotations

import csv
import json
import shutil
import sys
from pathlib import Path
from typing import Any


POC_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = POC_ROOT / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import apply_healthcare_current_quality_decisions as base  # noqa: E402


DATA_ADOPTED = POC_ROOT / "data" / "adopted"
REPORT_DIR = POC_ROOT / "data" / "reports" / "facility_validation"
ARCHIVE_DIR = POC_ROOT / "archive" / "20260427_public_office_current_quality_before"

ADOPTED_ALL = DATA_ADOPTED / "adopted_places_with_accessibility.csv"
PLAN_CSV = REPORT_DIR / "public_office_current_quality_plan.csv"
OUT_RENAMED = REPORT_DIR / "public_office_current_quality_decisions_renamed.csv"
OUT_RECATEGORIZED = REPORT_DIR / "public_office_current_quality_decisions_recategorized.csv"
OUT_REMOVED = REPORT_DIR / "public_office_current_quality_decisions_removed.csv"
OUT_MANUAL = REPORT_DIR / "public_office_current_quality_remaining_manual.csv"
OUT_SUMMARY = REPORT_DIR / "public_office_current_quality_decisions_summary.json"

CATEGORY_LABELS = {
    "HEALTHCARE": "의료·보건",
    "WELFARE": "복지·돌봄",
    "PUBLIC_OFFICE": "공공기관",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def append_pipe(value: str, item: str) -> str:
    values = [part for part in (value or "").split("|") if part]
    if item not in values:
        values.append(item)
    return "|".join(values)


def backup_files(paths: list[Path]) -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    for path in paths:
        if not path.exists():
            continue
        destination = ARCHIVE_DIR / path.relative_to(POC_ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copy2(path, destination)


def load_plan() -> dict[str, dict[str, str]]:
    return {
        row["sourceKey"]: row
        for row in read_csv(PLAN_CSV)
        if row["recommendedAction"] in {"RENAME_CANDIDATE", "RECATEGORY_CANDIDATE", "EXCLUDE_CANDIDATE"}
    }


def load_manual_rows() -> list[dict[str, str]]:
    return [row for row in read_csv(PLAN_CSV) if row["recommendedAction"] == "MANUAL_REVIEW"]


def main() -> None:
    backup_files(
        [
            base.ADOPTED_ALL,
            base.ADOPTED_PLACES,
            base.ADOPTED_ACCESSIBILITY,
            base.ERD_PLACES,
            base.ERD_ACCESSIBILITY,
            base.FACILITIES_JS,
            base.ACCESSIBILITY_SUMMARY_JS,
        ]
    )

    decisions = load_plan()
    rows = read_csv(ADOPTED_ALL)
    fieldnames = list(rows[0].keys())
    before_public = [row for row in rows if row["dbCategory"] == "PUBLIC_OFFICE"]

    kept_rows: list[dict[str, str]] = []
    renamed: list[dict[str, Any]] = []
    recategorized: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []

    for row in rows:
        decision = decisions.get(row["sourceKey"])
        if row["dbCategory"] != "PUBLIC_OFFICE" or not decision:
            kept_rows.append(row)
            continue

        action = decision["recommendedAction"]
        if action == "EXCLUDE_CANDIDATE":
            removed.append(
                {
                    "sourceKey": row["sourceKey"],
                    "placeIdBefore": row["placeId"],
                    "name": row["name"],
                    "districtGu": row["districtGu"],
                    "address": row["address"],
                    "rawFacilityType": row["rawFacilityType"],
                    "removeReason": decision["reason"],
                    "evidenceSource": decision["suggestionSource"],
                    "evidenceCategory": decision["suggestionCategory"],
                    "evidenceDistanceM": decision["suggestionDistanceM"],
                }
            )
            continue

        if action == "RENAME_CANDIDATE":
            old_name = row["name"]
            new_name = decision["suggestedName"].strip()
            if new_name and new_name != old_name:
                row["name"] = new_name
                row["reviewFlags"] = append_pipe(row.get("reviewFlags", ""), "public_office_current_quality_renamed")
                row["reviewReasons"] = append_pipe(row.get("reviewReasons", ""), f"공공기관 표시명 보정: {old_name} -> {new_name}")
                renamed.append(
                    {
                        "sourceKey": row["sourceKey"],
                        "placeIdBefore": row["placeId"],
                        "oldName": old_name,
                        "newName": new_name,
                        "districtGu": row["districtGu"],
                        "address": row["address"],
                        "rawFacilityType": row["rawFacilityType"],
                        "suggestionSource": decision["suggestionSource"],
                        "suggestionCategory": decision["suggestionCategory"],
                        "suggestionDistanceM": decision["suggestionDistanceM"],
                        "reason": decision["reason"],
                    }
                )

        if action == "RECATEGORY_CANDIDATE":
            old_category = row["dbCategory"]
            old_label = row["dbCategoryLabel"]
            old_name = row["name"]
            new_category = decision["suggestedCategory"]
            new_label = CATEGORY_LABELS[new_category]
            new_name = decision["suggestedName"].strip() or old_name
            row["dbCategory"] = new_category
            row["dbCategoryLabel"] = new_label
            row["facilityCategory"] = new_label
            row["uiCategory"] = new_label
            row["name"] = new_name
            row["reviewFlags"] = append_pipe(row.get("reviewFlags", ""), "public_office_current_quality_recategorized")
            row["reviewReasons"] = append_pipe(row.get("reviewReasons", ""), f"공공기관 카테고리 보정: {old_label} -> {new_label}")
            recategorized.append(
                {
                    "sourceKey": row["sourceKey"],
                    "placeIdBefore": row["placeId"],
                    "oldName": old_name,
                    "newName": new_name,
                    "oldCategory": old_category,
                    "newCategory": new_category,
                    "districtGu": row["districtGu"],
                    "address": row["address"],
                    "rawFacilityType": row["rawFacilityType"],
                    "reason": decision["reason"],
                }
            )

        kept_rows.append(row)

    for idx, row in enumerate(kept_rows, start=1):
        row["placeId"] = str(idx)

    write_csv(ADOPTED_ALL, kept_rows, fieldnames)
    base.update_adopted_places(kept_rows)
    base.update_adopted_accessibility(kept_rows)
    base.write_erd(kept_rows)
    base.update_facilities_js(kept_rows)
    base.write_accessibility_summary(kept_rows)

    write_csv(
        OUT_RENAMED,
        renamed,
        [
            "sourceKey",
            "placeIdBefore",
            "oldName",
            "newName",
            "districtGu",
            "address",
            "rawFacilityType",
            "suggestionSource",
            "suggestionCategory",
            "suggestionDistanceM",
            "reason",
        ],
    )
    write_csv(
        OUT_RECATEGORIZED,
        recategorized,
        ["sourceKey", "placeIdBefore", "oldName", "newName", "oldCategory", "newCategory", "districtGu", "address", "rawFacilityType", "reason"],
    )
    write_csv(
        OUT_REMOVED,
        removed,
        [
            "sourceKey",
            "placeIdBefore",
            "name",
            "districtGu",
            "address",
            "rawFacilityType",
            "removeReason",
            "evidenceSource",
            "evidenceCategory",
            "evidenceDistanceM",
        ],
    )
    manual_rows = load_manual_rows()
    write_csv(OUT_MANUAL, manual_rows, list(manual_rows[0].keys()) if manual_rows else ["sourceKey"])

    after_public = [row for row in kept_rows if row["dbCategory"] == "PUBLIC_OFFICE"]
    summary = {
        "before": {"places": len(rows), "publicOffice": len(before_public)},
        "after": {"places": len(kept_rows), "publicOffice": len(after_public)},
        "renamed": len(renamed),
        "recategorized": len(recategorized),
        "removed": len(removed),
        "manualRemaining": len(manual_rows),
        "outputs": {
            "renamed": str(OUT_RENAMED),
            "recategorized": str(OUT_RECATEGORIZED),
            "removed": str(OUT_REMOVED),
            "manual": str(OUT_MANUAL),
        },
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
