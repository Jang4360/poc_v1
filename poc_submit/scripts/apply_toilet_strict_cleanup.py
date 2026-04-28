from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import apply_toilet_public_private_cleanup as base


POC_ROOT = Path(__file__).resolve().parents[1]
VALIDATION_DIR = POC_ROOT / "data" / "reports" / "facility_validation"
ARCHIVE_DIR = POC_ROOT / "archive" / "20260426_toilet_strict_cleanup_before"

KEPT_CSV = VALIDATION_DIR / "toilet_public_private_cleanup_kept.csv"
OUT_SUMMARY_JSON = VALIDATION_DIR / "toilet_strict_cleanup_summary.json"
OUT_REMOVED_CSV = VALIDATION_DIR / "toilet_strict_cleanup_removed.csv"


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
    remove_rows = base.read_csv(KEPT_CSV)
    remove_keys = {row["sourceKey"] for row in remove_rows}
    affected = [
        base.ADOPTED_ALL,
        base.ADOPTED_PLACES,
        base.ADOPTED_ACCESSIBILITY,
        base.ERD_PLACES,
        base.ERD_ACCESSIBILITY,
        base.FACILITIES_JS,
        base.ACCESSIBILITY_SUMMARY_JS,
        KEPT_CSV,
    ]
    backup_files(affected)
    before_counts = {
        "adopted_places_with_accessibility": len(base.read_csv(base.ADOPTED_ALL)),
        "adopted_places": len(base.read_csv(base.ADOPTED_PLACES)),
        "adopted_place_accessibility": len(base.read_csv(base.ADOPTED_ACCESSIBILITY)),
        "places_erd": len(base.read_csv(base.ERD_PLACES)),
        "place_accessibility_features_erd": len(base.read_csv(base.ERD_ACCESSIBILITY)),
        "facilities_geojson_features": len(base.load_facilities_geojson()["features"]),
    }
    adopted_rows, place_id_by_source_key = base.update_adopted_all(remove_keys)
    base.update_simple_csv(base.ADOPTED_PLACES, "place_key", remove_keys)
    base.update_simple_csv(base.ADOPTED_ACCESSIBILITY, "place_key", remove_keys)
    base.write_erd(adopted_rows)
    base.update_facilities_js(remove_keys, place_id_by_source_key)
    base.write_accessibility_summary(adopted_rows)

    for row in remove_rows:
        row["strictReason"] = "화장실 위치가 시장/지하상가/상가/주변 설명 단위라 정확도 우선 기준으로 제외"
    write_csv(OUT_REMOVED_CSV, remove_rows, list(remove_rows[0].keys()))

    after_counts = {
        "adopted_places_with_accessibility": len(base.read_csv(base.ADOPTED_ALL)),
        "adopted_places": len(base.read_csv(base.ADOPTED_PLACES)),
        "adopted_place_accessibility": len(base.read_csv(base.ADOPTED_ACCESSIBILITY)),
        "places_erd": len(base.read_csv(base.ERD_PLACES)),
        "place_accessibility_features_erd": len(base.read_csv(base.ERD_ACCESSIBILITY)),
        "facilities_geojson_features": len(base.load_facilities_geojson()["features"]),
    }
    summary = {
        "applied": {"removed": len(remove_rows)},
        "before": before_counts,
        "after": after_counts,
        "backupDir": str(ARCHIVE_DIR),
        "outputs": {"removed": str(OUT_REMOVED_CSV)},
    }
    OUT_SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
