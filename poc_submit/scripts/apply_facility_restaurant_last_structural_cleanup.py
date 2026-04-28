from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import apply_facility_restaurant_display_cleanup as base


POC_ROOT = Path(__file__).resolve().parents[1]
VALIDATION_DIR = POC_ROOT / "data" / "reports" / "facility_validation"
ARCHIVE_DIR = POC_ROOT / "archive" / "20260426_restaurant_last_structural_cleanup_before"

REMOVE_KEYS = {"barrier_free_facility:6851"}
OUT_SUMMARY_JSON = VALIDATION_DIR / "facility_restaurant_last_structural_cleanup_summary.json"
OUT_REMOVED_CSV = VALIDATION_DIR / "facility_restaurant_last_structural_cleanup_removed.csv"


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
    adopted_rows, place_id_by_source_key = base.update_adopted_all({}, REMOVE_KEYS)
    base.update_simple_csv(base.ADOPTED_PLACES, "place_key", "place_name", {}, REMOVE_KEYS)
    base.update_simple_csv(base.ADOPTED_ACCESSIBILITY, "place_key", "place_name", {}, REMOVE_KEYS)
    base.write_erd(adopted_rows)
    base.update_facilities_js({}, REMOVE_KEYS, place_id_by_source_key)
    base.write_accessibility_summary(adopted_rows)
    removed_report = [
        {
            "sourceKey": "barrier_free_facility:6851",
            "removedName": "우동 근생",
            "reason": "POI는 우화, 카카오는 동백섬횟집으로 충돌해 음식점 상호를 특정할 수 없음",
        }
    ]
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
        "applied": {"removed": 1, "processed": 1},
        "before": before_counts,
        "after": after_counts,
        "backupDir": str(ARCHIVE_DIR),
        "outputs": {"removed": str(OUT_REMOVED_CSV)},
    }
    OUT_SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
