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
ARCHIVE_DIR = POC_ROOT / "archive" / "20260427_healthcare_manual_policy_before"

ADOPTED_ALL = DATA_ADOPTED / "adopted_places_with_accessibility.csv"
MANUAL_CSV = REPORT_DIR / "healthcare_current_quality_remaining_manual.csv"
OUT_KEPT = REPORT_DIR / "healthcare_manual_policy_kept.csv"
OUT_REMOVED = REPORT_DIR / "healthcare_manual_policy_removed.csv"
OUT_RENAMED = REPORT_DIR / "healthcare_manual_policy_renamed.csv"
OUT_SUMMARY = REPORT_DIR / "healthcare_manual_policy_summary.json"

TYPO_FIXES = {
    "barrier_free_facility:4161": "백양메디칼센터",
}

WEAK_HEALTHCARE_TERMS = [
    "메디",
    "메디컬",
    "메디칼",
    "메디타운",
    "메디타워",
    "메디팰리스",
    "메디플러스",
    "의료재단",
    "의료센터",
]


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


def is_policy_keep(row: dict[str, str]) -> bool:
    if row["sourceKey"] in TYPO_FIXES:
        return True
    name = TYPO_FIXES.get(row["sourceKey"], row["name"])
    return any(term in name for term in WEAK_HEALTHCARE_TERMS)


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

    manual_rows = read_csv(MANUAL_CSV)
    manual_by_key = {row["sourceKey"]: row for row in manual_rows}
    keep_keys = {row["sourceKey"] for row in manual_rows if is_policy_keep(row)}
    remove_keys = set(manual_by_key) - keep_keys

    rows = read_csv(ADOPTED_ALL)
    fieldnames = list(rows[0].keys())
    kept_rows: list[dict[str, str]] = []
    kept_report: list[dict[str, Any]] = []
    removed_report: list[dict[str, Any]] = []
    renamed_report: list[dict[str, Any]] = []

    before_healthcare = [row for row in rows if row["dbCategory"] == "HEALTHCARE"]

    for row in rows:
        source_key = row["sourceKey"]
        if source_key in remove_keys:
            manual = manual_by_key[source_key]
            removed_report.append(
                {
                    "sourceKey": source_key,
                    "placeIdBefore": row["placeId"],
                    "name": row["name"],
                    "districtGu": row["districtGu"],
                    "address": row["address"],
                    "rawFacilityType": row["rawFacilityType"],
                    "removeReason": manual.get("reason", "의료·보건 수동검토 정책상 제거"),
                    "suggestionSource": manual.get("suggestionSource", ""),
                    "suggestionCategory": manual.get("suggestionCategory", ""),
                    "suggestionDistanceM": manual.get("suggestionDistanceM", ""),
                }
            )
            continue

        if source_key in keep_keys:
            old_name = row["name"]
            new_name = TYPO_FIXES.get(source_key, old_name)
            if new_name != old_name:
                row["name"] = new_name
                row["reviewFlags"] = append_pipe(row.get("reviewFlags", ""), "healthcare_typo_corrected")
                row["reviewReasons"] = append_pipe(row.get("reviewReasons", ""), f"의료·보건 표시명 오타 보정: {old_name} -> {new_name}")
                renamed_report.append(
                    {
                        "sourceKey": source_key,
                        "placeIdBefore": row["placeId"],
                        "oldName": old_name,
                        "newName": new_name,
                        "districtGu": row["districtGu"],
                        "address": row["address"],
                        "reason": "메티칼 -> 메디칼 오타 보정",
                    }
                )
            row["reviewFlags"] = append_pipe(row.get("reviewFlags", ""), "healthcare_manual_policy_kept")
            row["reviewReasons"] = append_pipe(row.get("reviewReasons", ""), "의료 포괄명은 수동 검토 정책에 따라 유지")
            kept_report.append(
                {
                    "sourceKey": source_key,
                    "placeIdBefore": row["placeId"],
                    "name": row["name"],
                    "districtGu": row["districtGu"],
                    "address": row["address"],
                    "rawFacilityType": row["rawFacilityType"],
                    "keepReason": "의료 포괄명 유지",
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
        OUT_KEPT,
        kept_report,
        ["sourceKey", "placeIdBefore", "name", "districtGu", "address", "rawFacilityType", "keepReason"],
    )
    write_csv(
        OUT_REMOVED,
        removed_report,
        [
            "sourceKey",
            "placeIdBefore",
            "name",
            "districtGu",
            "address",
            "rawFacilityType",
            "removeReason",
            "suggestionSource",
            "suggestionCategory",
            "suggestionDistanceM",
        ],
    )
    write_csv(
        OUT_RENAMED,
        renamed_report,
        ["sourceKey", "placeIdBefore", "oldName", "newName", "districtGu", "address", "reason"],
    )
    write_csv(MANUAL_CSV, [], list(manual_rows[0].keys()) if manual_rows else ["sourceKey"])

    after_healthcare = [row for row in kept_rows if row["dbCategory"] == "HEALTHCARE"]
    summary = {
        "before": {"places": len(rows), "healthcare": len(before_healthcare), "manualReview": len(manual_rows)},
        "after": {"places": len(kept_rows), "healthcare": len(after_healthcare), "manualReview": 0},
        "kept": len(kept_report),
        "renamed": len(renamed_report),
        "removed": len(removed_report),
        "outputs": {"kept": str(OUT_KEPT), "renamed": str(OUT_RENAMED), "removed": str(OUT_REMOVED)},
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
