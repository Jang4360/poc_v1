from __future__ import annotations

import csv
import json
import shutil
from collections import Counter
from pathlib import Path


POC_ROOT = Path(__file__).resolve().parents[1]
DATA_ADOPTED = POC_ROOT / "data" / "adopted"
ASSETS_DATA = POC_ROOT / "assets" / "data"
VALIDATION_DIR = POC_ROOT / "data" / "reports" / "facility_validation"
ARCHIVE_DIR = POC_ROOT / "archive" / "20260426_toilet_public_private_cleanup_before"

ADOPTED_ALL = DATA_ADOPTED / "adopted_places_with_accessibility.csv"
ADOPTED_PLACES = DATA_ADOPTED / "adopted_places.csv"
ADOPTED_ACCESSIBILITY = DATA_ADOPTED / "adopted_place_accessibility.csv"
ERD_PLACES = DATA_ADOPTED / "places_erd.csv"
ERD_ACCESSIBILITY = DATA_ADOPTED / "place_accessibility_features_erd.csv"
FACILITIES_JS = ASSETS_DATA / "facilities-data.js"
ACCESSIBILITY_SUMMARY_JS = ASSETS_DATA / "accessibility-summary-data.js"

PLAN_CSV = VALIDATION_DIR / "toilet_public_private_cleanup_plan.csv"
OUT_SUMMARY_JSON = VALIDATION_DIR / "toilet_public_private_cleanup_summary.json"
OUT_REMOVED_CSV = VALIDATION_DIR / "toilet_public_private_cleanup_removed.csv"
OUT_KEPT_CSV = VALIDATION_DIR / "toilet_public_private_cleanup_kept.csv"

ERD_FEATURE_TYPES = ("ramp", "autoDoor", "elevator", "accessibleToilet", "chargingStation", "stepFree")
ERD_ACCESSIBILITY_LABELS = {
    "ramp": "경사로",
    "autoDoor": "자동문",
    "elevator": "엘리베이터",
    "accessibleToilet": "전용 화장실",
    "chargingStation": "전동보장구 충전",
    "stepFree": "단차 없음",
}

KEEP_REVIEW_NAMES = {"만덕상학초등학교 옆"}
REMOVE_REVIEW_TERMS = {"상가"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def split_pipe(value: str) -> list[str]:
    return [item for item in value.split("|") if item]


def update_pipe(value: str, add: str) -> str:
    values = split_pipe(value)
    if add not in values:
        values.append(add)
    return "|".join(values)


def backup_files(paths: list[Path]) -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    for path in paths:
        destination = ARCHIVE_DIR / path.relative_to(POC_ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copy2(path, destination)


def final_action(row: dict[str, str]) -> tuple[str, str]:
    if row["action"] == "KEEP":
        return "KEEP", row["reason"]
    if row["action"] == "REMOVE":
        return "REMOVE", row["reason"]
    if row["name"] in KEEP_REVIEW_NAMES:
        return "KEEP", "학교 내부가 아니라 주변 위치 설명으로 보여 공중화장실 후보 유지"
    if row["matchedTerm"] in REMOVE_REVIEW_TERMS:
        return "REMOVE", "일반 상가 화장실은 내부/민간시설 가능성이 높아 제외"
    return "REMOVE", "개방 근거가 부족해 공중화장실 목적지에서 제외"


def load_decisions() -> tuple[set[str], list[dict[str, str]], list[dict[str, str]]]:
    remove_keys: set[str] = set()
    removed: list[dict[str, str]] = []
    kept: list[dict[str, str]] = []
    for row in read_csv(PLAN_CSV):
        action, reason = final_action(row)
        out = dict(row)
        out["finalAction"] = action
        out["finalReason"] = reason
        if action == "REMOVE":
            remove_keys.add(row["sourceKey"])
            removed.append(out)
        else:
            kept.append(out)
    return remove_keys, removed, kept


def update_adopted_all(remove_keys: set[str]) -> tuple[list[dict[str, str]], dict[str, str]]:
    rows = read_csv(ADOPTED_ALL)
    fieldnames = list(rows[0].keys())
    kept_rows: list[dict[str, str]] = []
    place_id_by_source_key: dict[str, str] = {}
    for row in rows:
        source_key = row["sourceKey"]
        if source_key in remove_keys:
            continue
        if row["dbCategory"] == "TOILET":
            row["reviewFlags"] = update_pipe(row.get("reviewFlags", ""), "toilet_public_private_reviewed")
            row["reviewReasons"] = update_pipe(row.get("reviewReasons", ""), "화장실 공공성 검토 반영")
        row["placeId"] = str(len(kept_rows) + 1)
        place_id_by_source_key[source_key] = row["placeId"]
        kept_rows.append(row)
    write_csv(ADOPTED_ALL, kept_rows, fieldnames)
    return kept_rows, place_id_by_source_key


def update_simple_csv(path: Path, key_field: str, remove_keys: set[str]) -> None:
    rows = read_csv(path)
    fieldnames = list(rows[0].keys())
    kept = [row for row in rows if row[key_field] not in remove_keys]
    write_csv(path, kept, fieldnames)


def write_erd(adopted_rows: list[dict[str, str]]) -> None:
    place_rows = [
        {
            "placeId": row["placeId"],
            "name": row["name"],
            "category": row["dbCategory"],
            "address": row["address"],
            "point": row["point"],
            "providerPlaceId": row["providerPlaceId"],
        }
        for row in adopted_rows
    ]
    write_csv(ERD_PLACES, place_rows, ["placeId", "name", "category", "address", "point", "providerPlaceId"])

    feature_rows: list[dict[str, str]] = []
    next_id = 1
    for row in adopted_rows:
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


def load_facilities_geojson() -> dict[str, object]:
    text = FACILITIES_JS.read_text(encoding="utf-8").strip()
    prefix = "window.FACILITIES_GEOJSON = "
    if not text.startswith(prefix):
        raise ValueError("Unexpected facilities JS format")
    if text.endswith(";"):
        text = text[:-1]
    return json.loads(text[len(prefix) :])


def update_facilities_js(remove_keys: set[str], place_id_by_source_key: dict[str, str]) -> None:
    geojson = load_facilities_geojson()
    features = []
    for feature in geojson["features"]:
        props = feature["properties"]
        source_id = props["sourceId"]
        if source_id in remove_keys:
            continue
        props["placeId"] = place_id_by_source_key[source_id]
        if props.get("dbCategory") == "TOILET":
            flags = props.get("reviewFlags", [])
            if isinstance(flags, list) and "toilet_public_private_reviewed" not in flags:
                flags.append("toilet_public_private_reviewed")
                props["reviewFlags"] = flags
            reasons = props.get("reviewReasons", [])
            if isinstance(reasons, list) and "화장실 공공성 검토 반영" not in reasons:
                reasons.append("화장실 공공성 검토 반영")
                props["reviewReasons"] = reasons
        features.append(feature)
    geojson["features"] = features
    FACILITIES_JS.write_text(
        "window.FACILITIES_GEOJSON = "
        + json.dumps(geojson, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )


def write_accessibility_summary(adopted_rows: list[dict[str, str]]) -> None:
    counter: Counter[str] = Counter()
    places_with_access = 0
    for row in adopted_rows:
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
    remove_keys, removed, kept = load_decisions()
    affected = [
        ADOPTED_ALL,
        ADOPTED_PLACES,
        ADOPTED_ACCESSIBILITY,
        ERD_PLACES,
        ERD_ACCESSIBILITY,
        FACILITIES_JS,
        ACCESSIBILITY_SUMMARY_JS,
        PLAN_CSV,
    ]
    backup_files(affected)
    before_counts = {
        "adopted_places_with_accessibility": len(read_csv(ADOPTED_ALL)),
        "adopted_places": len(read_csv(ADOPTED_PLACES)),
        "adopted_place_accessibility": len(read_csv(ADOPTED_ACCESSIBILITY)),
        "places_erd": len(read_csv(ERD_PLACES)),
        "place_accessibility_features_erd": len(read_csv(ERD_ACCESSIBILITY)),
        "facilities_geojson_features": len(load_facilities_geojson()["features"]),
    }
    adopted_rows, place_id_by_source_key = update_adopted_all(remove_keys)
    update_simple_csv(ADOPTED_PLACES, "place_key", remove_keys)
    update_simple_csv(ADOPTED_ACCESSIBILITY, "place_key", remove_keys)
    write_erd(adopted_rows)
    update_facilities_js(remove_keys, place_id_by_source_key)
    write_accessibility_summary(adopted_rows)
    write_csv(OUT_REMOVED_CSV, removed, list(removed[0].keys()))
    write_csv(OUT_KEPT_CSV, kept, list(kept[0].keys()))
    after_counts = {
        "adopted_places_with_accessibility": len(read_csv(ADOPTED_ALL)),
        "adopted_places": len(read_csv(ADOPTED_PLACES)),
        "adopted_place_accessibility": len(read_csv(ADOPTED_ACCESSIBILITY)),
        "places_erd": len(read_csv(ERD_PLACES)),
        "place_accessibility_features_erd": len(read_csv(ERD_ACCESSIBILITY)),
        "facilities_geojson_features": len(load_facilities_geojson()["features"]),
    }
    summary = {
        "applied": {
            "removed": len(removed),
            "kept": len(kept),
            "processed": len(removed) + len(kept),
        },
        "before": before_counts,
        "after": after_counts,
        "backupDir": str(ARCHIVE_DIR),
        "outputs": {
            "removed": str(OUT_REMOVED_CSV),
            "kept": str(OUT_KEPT_CSV),
        },
    }
    OUT_SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
