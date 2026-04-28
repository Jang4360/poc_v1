from __future__ import annotations

import csv
import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any


POC_ROOT = Path(__file__).resolve().parents[1]
DATA_ADOPTED = POC_ROOT / "data" / "adopted"
ASSETS_DATA = POC_ROOT / "assets" / "data"
REPORT_DIR = POC_ROOT / "data" / "reports" / "facility_validation"
ARCHIVE_DIR = POC_ROOT / "archive" / "20260427_welfare_remaining_manual_before"

ADOPTED_ALL = DATA_ADOPTED / "adopted_places_with_accessibility.csv"
ADOPTED_PLACES = DATA_ADOPTED / "adopted_places.csv"
ADOPTED_ACCESSIBILITY = DATA_ADOPTED / "adopted_place_accessibility.csv"
ERD_PLACES = DATA_ADOPTED / "places_erd.csv"
ERD_ACCESSIBILITY = DATA_ADOPTED / "place_accessibility_features_erd.csv"
FACILITIES_JS = ASSETS_DATA / "facilities-data.js"
ACCESSIBILITY_SUMMARY_JS = ASSETS_DATA / "accessibility-summary-data.js"

MANUAL_CSV = REPORT_DIR / "welfare_current_quality_remaining_manual.csv"
OUT_REMOVED = REPORT_DIR / "welfare_remaining_manual_removed.csv"
OUT_SUMMARY = REPORT_DIR / "welfare_remaining_manual_remove_summary.json"

ERD_FEATURE_TYPES = ("ramp", "autoDoor", "elevator", "accessibleToilet", "chargingStation", "stepFree")
ERD_ACCESSIBILITY_LABELS = {
    "ramp": "경사로",
    "autoDoor": "자동문",
    "elevator": "엘리베이터",
    "accessibleToilet": "전용 화장실",
    "chargingStation": "전동보장구 충전",
    "stepFree": "단차 없음",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def split_pipe(value: str) -> list[str]:
    return [item for item in (value or "").split("|") if item]


def backup_files(paths: list[Path]) -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    for path in paths:
        if not path.exists():
            continue
        destination = ARCHIVE_DIR / path.relative_to(POC_ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copy2(path, destination)


def load_remove_keys() -> tuple[set[str], dict[str, dict[str, str]]]:
    rows = read_csv(MANUAL_CSV)
    by_key = {row["sourceKey"]: row for row in rows}
    return set(by_key), by_key


def update_adopted_all(remove_keys: set[str], manual_by_key: dict[str, dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    rows = read_csv(ADOPTED_ALL)
    fieldnames = list(rows[0].keys())
    kept: list[dict[str, str]] = []
    removed: list[dict[str, Any]] = []

    for row in rows:
        if row["sourceKey"] in remove_keys:
            manual = manual_by_key[row["sourceKey"]]
            removed.append(
                {
                    "sourceKey": row["sourceKey"],
                    "placeIdBefore": row["placeId"],
                    "name": row["name"],
                    "districtGu": row["districtGu"],
                    "address": row["address"],
                    "rawFacilityType": row["rawFacilityType"],
                    "removeReason": manual.get("reason", ""),
                    "kakaoPlaceName": manual.get("kakaoPlaceName", ""),
                    "kakaoCategory": manual.get("kakaoCategory", ""),
                    "kakaoDistanceM": manual.get("kakaoDistanceM", ""),
                    "poiName": manual.get("poiName", ""),
                    "poiCategory": manual.get("poiCategory", ""),
                    "poiDistanceM": manual.get("poiDistanceM", ""),
                }
            )
            continue
        kept.append(row)

    for idx, row in enumerate(kept, start=1):
        row["placeId"] = str(idx)

    write_csv(ADOPTED_ALL, kept, fieldnames)
    return kept, removed


def update_adopted_places(kept_rows: list[dict[str, str]]) -> None:
    by_key = {row["sourceKey"]: row for row in kept_rows}
    rows = read_csv(ADOPTED_PLACES)
    fieldnames = list(rows[0].keys())
    out_rows: list[dict[str, str]] = []
    for row in rows:
        adopted = by_key.get(row["place_key"])
        if not adopted:
            continue
        row["place_name"] = adopted["name"]
        row["ui_category"] = adopted["uiCategory"]
        row["source_category"] = adopted["sourceCategory"]
        out_rows.append(row)
    write_csv(ADOPTED_PLACES, out_rows, fieldnames)


def update_adopted_accessibility(kept_rows: list[dict[str, str]]) -> None:
    by_key = {row["sourceKey"]: row for row in kept_rows}
    rows = read_csv(ADOPTED_ACCESSIBILITY)
    fieldnames = list(rows[0].keys())
    out_rows: list[dict[str, str]] = []
    for row in rows:
        adopted = by_key.get(row["place_key"])
        if not adopted:
            continue
        row["place_name"] = adopted["name"]
        row["ui_category"] = adopted["uiCategory"]
        out_rows.append(row)
    write_csv(ADOPTED_ACCESSIBILITY, out_rows, fieldnames)


def write_erd(kept_rows: list[dict[str, str]]) -> None:
    place_rows = [
        {
            "placeId": row["placeId"],
            "name": row["name"],
            "category": row["dbCategory"],
            "address": row["address"],
            "point": row["point"],
            "providerPlaceId": row["providerPlaceId"],
        }
        for row in kept_rows
    ]
    write_csv(ERD_PLACES, place_rows, ["placeId", "name", "category", "address", "point", "providerPlaceId"])

    feature_rows: list[dict[str, str]] = []
    next_id = 1
    for row in kept_rows:
        for feature_type in split_pipe(row.get("erdAccessibilityTypes", "")):
            feature_rows.append(
                {
                    "id": str(next_id),
                    "placeId": row["placeId"],
                    "featureType": feature_type,
                    "isAvailable": "true",
                }
            )
            next_id += 1
    write_csv(ERD_ACCESSIBILITY, feature_rows, ["id", "placeId", "featureType", "isAvailable"])


def load_facilities_geojson() -> dict[str, Any]:
    text = FACILITIES_JS.read_text(encoding="utf-8").strip()
    prefix = "window.FACILITIES_GEOJSON = "
    if not text.startswith(prefix):
        raise ValueError("Unexpected facilities JS format")
    if text.endswith(";"):
        text = text[:-1]
    return json.loads(text[len(prefix) :])


def update_facilities_js(kept_rows: list[dict[str, str]]) -> None:
    by_key = {row["sourceKey"]: row for row in kept_rows}
    geojson = load_facilities_geojson()
    features = []
    for feature in geojson["features"]:
        props = feature["properties"]
        adopted = by_key.get(props.get("sourceId", ""))
        if not adopted:
            continue
        props["placeId"] = adopted["placeId"]
        props["name"] = adopted["name"]
        props["dbCategory"] = adopted["dbCategory"]
        props["dbCategoryLabel"] = adopted["dbCategoryLabel"]
        props["facilityCategory"] = adopted["facilityCategory"]
        props["uiCategory"] = adopted["uiCategory"]
        props["displaySource"] = adopted["facilityCategory"]
        props["sourceCategory"] = adopted["sourceCategory"]
        props["reviewFlags"] = split_pipe(adopted.get("reviewFlags", ""))
        props["reviewReasons"] = split_pipe(adopted.get("reviewReasons", ""))
        features.append(feature)
    geojson["features"] = features
    FACILITIES_JS.write_text(
        "window.FACILITIES_GEOJSON = "
        + json.dumps(geojson, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )


def write_accessibility_summary(kept_rows: list[dict[str, str]]) -> None:
    counter: Counter[str] = Counter()
    places_with_access = 0
    for row in kept_rows:
        values = split_pipe(row.get("erdAccessibilityTypes", ""))
        if values:
            places_with_access += 1
            counter.update(values)
    summary = {
        "totalRows": sum(counter.values()),
        "totalPlaces": places_with_access,
        "items": [
            {"featureType": key, "label": ERD_ACCESSIBILITY_LABELS.get(key, key), "count": counter[key]}
            for key in sorted(counter.keys(), key=lambda item: counter[item], reverse=True)
        ],
        "availableFeatureTypes": [
            {"featureType": key, "label": ERD_ACCESSIBILITY_LABELS.get(key, key), "count": counter[key]}
            for key in ERD_FEATURE_TYPES
        ],
    }
    ACCESSIBILITY_SUMMARY_JS.write_text(
        "window.ACCESSIBILITY_SUMMARY = "
        + json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )


def main() -> None:
    remove_keys, manual_by_key = load_remove_keys()
    affected = [
        ADOPTED_ALL,
        ADOPTED_PLACES,
        ADOPTED_ACCESSIBILITY,
        ERD_PLACES,
        ERD_ACCESSIBILITY,
        FACILITIES_JS,
        ACCESSIBILITY_SUMMARY_JS,
    ]
    backup_files(affected)

    before_rows = read_csv(ADOPTED_ALL)
    before_counts = Counter(row["dbCategory"] for row in before_rows)
    kept_rows, removed = update_adopted_all(remove_keys, manual_by_key)
    update_adopted_places(kept_rows)
    update_adopted_accessibility(kept_rows)
    write_erd(kept_rows)
    update_facilities_js(kept_rows)
    write_accessibility_summary(kept_rows)

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
            "kakaoPlaceName",
            "kakaoCategory",
            "kakaoDistanceM",
            "poiName",
            "poiCategory",
            "poiDistanceM",
        ],
    )

    after_counts = Counter(row["dbCategory"] for row in kept_rows)
    summary = {
        "before": {"places": len(before_rows), "categoryCounts": dict(sorted(before_counts.items()))},
        "after": {"places": len(kept_rows), "categoryCounts": dict(sorted(after_counts.items()))},
        "removed": len(removed),
        "outputs": {"removed": str(OUT_REMOVED)},
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
