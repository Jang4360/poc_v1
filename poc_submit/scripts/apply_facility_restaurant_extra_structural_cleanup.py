from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import apply_facility_restaurant_display_cleanup as base


POC_ROOT = Path(__file__).resolve().parents[1]
VALIDATION_DIR = POC_ROOT / "data" / "reports" / "facility_validation"
ARCHIVE_DIR = POC_ROOT / "archive" / "20260426_restaurant_extra_structural_cleanup_before"

RENAME_MAP = {
    "barrier_free_facility:5848": "동산횟집",
}

REMOVE_KEYS = {
    "barrier_free_facility:10870",
}

OUT_SUMMARY_JSON = VALIDATION_DIR / "facility_restaurant_extra_structural_cleanup_summary.json"
OUT_RENAMED_CSV = VALIDATION_DIR / "facility_restaurant_extra_structural_cleanup_renamed.csv"
OUT_REMOVED_CSV = VALIDATION_DIR / "facility_restaurant_extra_structural_cleanup_removed.csv"


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
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


def main() -> None:
    affected_files = [
        base.ADOPTED_ALL,
        base.ADOPTED_PLACES,
        base.ADOPTED_ACCESSIBILITY,
        base.ERD_PLACES,
        base.ERD_ACCESSIBILITY,
        base.FACILITIES_JS,
        base.ACCESSIBILITY_SUMMARY_JS,
    ]
    backup_files(affected_files)

    before_counts = {
        "adopted_places_with_accessibility": len(base.read_csv(base.ADOPTED_ALL)),
        "adopted_places": len(base.read_csv(base.ADOPTED_PLACES)),
        "adopted_place_accessibility": len(base.read_csv(base.ADOPTED_ACCESSIBILITY)),
        "places_erd": len(base.read_csv(base.ERD_PLACES)),
        "place_accessibility_features_erd": len(base.read_csv(base.ERD_ACCESSIBILITY)),
        "facilities_geojson_features": len(base.load_facilities_geojson()["features"]),
    }

    adopted_rows, place_id_by_source_key = base.update_adopted_all(RENAME_MAP, REMOVE_KEYS)
    base.update_simple_csv(base.ADOPTED_PLACES, "place_key", "place_name", RENAME_MAP, REMOVE_KEYS)
    base.update_simple_csv(base.ADOPTED_ACCESSIBILITY, "place_key", "place_name", RENAME_MAP, REMOVE_KEYS)
    base.write_erd(adopted_rows)
    base.update_facilities_js(RENAME_MAP, REMOVE_KEYS, place_id_by_source_key)
    base.write_accessibility_summary(adopted_rows)

    adopted_by_key = {row["sourceKey"]: row for row in adopted_rows}
    renamed_report = [
        {
            "sourceKey": key,
            "appliedName": name,
            "reason": "POI와 카카오 모두 동산횟집으로 음식점 근거",
        }
        for key, name in RENAME_MAP.items()
    ]
    removed_report = [
        {
            "sourceKey": key,
            "reason": "POI/Kakao 근거가 음식점명으로 복구되지 않아 제외",
        }
        for key in sorted(REMOVE_KEYS)
    ]
    write_csv(OUT_RENAMED_CSV, renamed_report, list(renamed_report[0].keys()))
    write_csv(OUT_REMOVED_CSV, removed_report, list(removed_report[0].keys()))

    after_counts = {
        "adopted_places_with_accessibility": len(base.read_csv(base.ADOPTED_ALL)),
        "adopted_places": len(base.read_csv(base.ADOPTED_PLACES)),
        "adopted_place_accessibility": len(base.read_csv(base.ADOPTED_ACCESSIBILITY)),
        "places_erd": len(base.read_csv(base.ERD_PLACES)),
        "place_accessibility_features_erd": len(base.read_csv(base.ERD_ACCESSIBILITY)),
        "facilities_geojson_features": len(base.load_facilities_geojson()["features"]),
    }
    summary = {
        "applied": {
            "renamed": len(RENAME_MAP),
            "removed": len(REMOVE_KEYS),
            "processed": len(RENAME_MAP) + len(REMOVE_KEYS),
        },
        "before": before_counts,
        "after": after_counts,
        "backupDir": str(ARCHIVE_DIR),
        "outputs": {
            "renamed": str(OUT_RENAMED_CSV),
            "removed": str(OUT_REMOVED_CSV),
        },
    }
    OUT_SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
