from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path


POC_ROOT = Path(__file__).resolve().parents[1]
DATA_ADOPTED = POC_ROOT / "data" / "adopted"
DATA_FINAL = POC_ROOT / "data" / "final" / "facilities"
ASSETS_DATA = POC_ROOT / "assets" / "data"
VALIDATION_DIR = POC_ROOT / "data" / "reports" / "facility_validation"
ARCHIVE_DIR = POC_ROOT / "archive" / "20260426_legacy_barrier_free_category_before"

ADOPTED_ALL = DATA_ADOPTED / "adopted_places_with_accessibility.csv"
ADOPTED_PLACES = DATA_ADOPTED / "adopted_places.csv"
FACILITIES_JS = ASSETS_DATA / "facilities-data.js"
MAPPING_CSV = VALIDATION_DIR / "facility_category_v2_cleanup_mapping.csv"
MAPPING_SUMMARY_JSON = VALIDATION_DIR / "facility_category_v2_cleanup_summary.json"
SUMMARY_JSON = VALIDATION_DIR / "legacy_barrier_free_category_cleanup_summary.json"

LEGACY = "BARRIER_FREE_FACILITY"
LEGACY_LABEL = "LEGACY_ACCESSIBILITY_GROUP"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def backup_files(paths: list[Path]) -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    for path in paths:
        destination = ARCHIVE_DIR / path.relative_to(POC_ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copy2(path, destination)


def update_adopted_all() -> dict[str, str]:
    rows = read_csv(ADOPTED_ALL)
    fieldnames = list(rows[0].keys())
    source_category_updates = 0
    category_by_source_key: dict[str, str] = {}
    for row in rows:
        category_by_source_key[row["sourceKey"]] = row["dbCategory"]
        if row.get("sourceCategory") == LEGACY:
            row["sourceCategory"] = row["dbCategory"]
            source_category_updates += 1
    write_csv(ADOPTED_ALL, rows, fieldnames)
    return {"updates": str(source_category_updates), **category_by_source_key}


def update_adopted_places(category_by_source_key: dict[str, str]) -> int:
    rows = read_csv(ADOPTED_PLACES)
    fieldnames = list(rows[0].keys())
    updates = 0
    for row in rows:
        if row.get("source_category") == LEGACY:
            row["source_category"] = category_by_source_key[row["place_key"]]
            updates += 1
    write_csv(ADOPTED_PLACES, rows, fieldnames)
    return updates


def load_facilities_geojson() -> dict[str, object]:
    text = FACILITIES_JS.read_text(encoding="utf-8").strip()
    prefix = "window.FACILITIES_GEOJSON = "
    if not text.startswith(prefix):
        raise ValueError("Unexpected facilities JS format")
    if text.endswith(";"):
        text = text[:-1]
    return json.loads(text[len(prefix) :])


def update_facilities_js() -> int:
    geojson = load_facilities_geojson()
    updates = 0
    for feature in geojson["features"]:
        props = feature["properties"]
        if props.get("sourceCategory") == LEGACY:
            props["sourceCategory"] = props["dbCategory"]
            updates += 1
    FACILITIES_JS.write_text(
        "window.FACILITIES_GEOJSON = "
        + json.dumps(geojson, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )
    return updates


def update_mapping_report() -> int:
    rows = read_csv(MAPPING_CSV)
    fieldnames = list(rows[0].keys())
    updates = 0
    for row in rows:
        if row.get("beforeCategory") == LEGACY:
            row["beforeCategory"] = LEGACY_LABEL
            updates += 1
    write_csv(MAPPING_CSV, rows, fieldnames)

    if MAPPING_SUMMARY_JSON.exists():
        summary = json.loads(MAPPING_SUMMARY_JSON.read_text(encoding="utf-8"))
        before_counts = summary.get("beforeCategoryCounts", {})
        if LEGACY in before_counts:
            before_counts[LEGACY_LABEL] = before_counts.pop(LEGACY)
        MAPPING_SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return updates


def copy_final_files() -> None:
    DATA_FINAL.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ADOPTED_ALL, DATA_FINAL / "adopted_places_with_accessibility_final.csv")
    shutil.copy2(ADOPTED_PLACES, DATA_FINAL / "adopted_places_final.csv")


def main() -> None:
    backup_files([ADOPTED_ALL, ADOPTED_PLACES, FACILITIES_JS, MAPPING_CSV, MAPPING_SUMMARY_JSON])
    adopted_result = update_adopted_all()
    source_category_updates = int(adopted_result.pop("updates"))
    adopted_places_updates = update_adopted_places(adopted_result)
    facilities_js_updates = update_facilities_js()
    mapping_updates = update_mapping_report()
    copy_final_files()

    summary = {
        "sourceCategoryUpdates": source_category_updates,
        "sourceCategoryCsvUpdates": adopted_places_updates,
        "facilitiesJsUpdates": facilities_js_updates,
        "mappingReportUpdates": mapping_updates,
        "backupDir": str(ARCHIVE_DIR),
        "note": "원본 추적은 sourceDataset=barrier_free_facility 및 rawFacilityType으로 유지하고, 카테고리 계열 값에서는 레거시 코드를 제거했다.",
    }
    SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
