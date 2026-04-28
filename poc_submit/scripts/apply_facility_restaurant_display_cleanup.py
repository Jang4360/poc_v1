from __future__ import annotations

import csv
import json
import re
import shutil
from collections import Counter
from pathlib import Path


POC_ROOT = Path(__file__).resolve().parents[1]
DATA_ADOPTED = POC_ROOT / "data" / "adopted"
ASSETS_DATA = POC_ROOT / "assets" / "data"
VALIDATION_DIR = POC_ROOT / "data" / "reports" / "facility_validation"
ARCHIVE_DIR = POC_ROOT / "archive" / "20260426_restaurant_display_cleanup_before"

ADOPTED_ALL = DATA_ADOPTED / "adopted_places_with_accessibility.csv"
ADOPTED_PLACES = DATA_ADOPTED / "adopted_places.csv"
ADOPTED_ACCESSIBILITY = DATA_ADOPTED / "adopted_place_accessibility.csv"
ERD_PLACES = DATA_ADOPTED / "places_erd.csv"
ERD_ACCESSIBILITY = DATA_ADOPTED / "place_accessibility_features_erd.csv"
FACILITIES_JS = ASSETS_DATA / "facilities-data.js"
ACCESSIBILITY_SUMMARY_JS = ASSETS_DATA / "accessibility-summary-data.js"

PLAN_CSV = VALIDATION_DIR / "facility_restaurant_structural_name_plan.csv"
OUT_SUMMARY_JSON = VALIDATION_DIR / "facility_restaurant_display_cleanup_summary.json"
OUT_RENAMED_CSV = VALIDATION_DIR / "facility_restaurant_display_cleanup_renamed.csv"
OUT_REMOVED_CSV = VALIDATION_DIR / "facility_restaurant_display_cleanup_removed.csv"

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


def normalize(value: str) -> str:
    return re.sub(r"\s+", "", value or "").strip().lower()


def common_prefix_len(a: str, b: str) -> int:
    left = normalize(a)
    right = normalize(b)
    count = 0
    for lc, rc in zip(left, right):
        if lc != rc:
            break
        count += 1
    return count


def similar_candidate_names(a: str, b: str) -> bool:
    left = normalize(a)
    right = normalize(b)
    if not left or not right:
        return False
    if left in right or right in left:
        return True
    return common_prefix_len(left, right) >= 3


def current_parentheses_contains(current_name: str, proposed_name: str) -> bool:
    for inner in re.findall(r"\(([^()]+)\)", current_name or ""):
        cleaned = re.sub(r"\s*외\s*\d+\s*개\s*$", "", inner).strip()
        if cleaned and normalize(cleaned) == normalize(proposed_name):
            return True
    return False


def final_decision(plan_row: dict[str, str]) -> tuple[str, str]:
    action = plan_row["action"]
    if action == "RENAME":
        return "RENAME", "자동 근거 충분"
    if action == "EXCLUDE":
        return "EXCLUDE", "음식점명 복구 불가 또는 비음식점 근거"

    proposed = plan_row.get("proposedName", "")
    second = plan_row.get("secondCandidateName", "")
    current = plan_row.get("currentName", "")
    if not proposed:
        return "EXCLUDE", "복구 가능한 음식점명 없음"
    if current_parentheses_contains(current, proposed):
        return "RENAME", "원본 괄호 안에 음식점명이 있음"
    if second and similar_candidate_names(proposed, second):
        return "RENAME", "POI/카카오 후보명이 같은 장소로 볼 수 있음"
    return "EXCLUDE", "음식점 후보가 서로 충돌해 임의 선택 제외"


def backup_files(paths: list[Path]) -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    for path in paths:
        destination = ARCHIVE_DIR / path.relative_to(POC_ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copy2(path, destination)


def load_decisions() -> tuple[dict[str, str], set[str], list[dict[str, str]], list[dict[str, str]]]:
    rename_map: dict[str, str] = {}
    remove_keys: set[str] = set()
    renamed_report: list[dict[str, str]] = []
    removed_report: list[dict[str, str]] = []

    for row in read_csv(PLAN_CSV):
        decision, decision_reason = final_decision(row)
        out = dict(row)
        out["finalAction"] = decision
        out["finalActionReason"] = decision_reason
        if decision == "RENAME":
            rename_map[row["sourceKey"]] = row["proposedName"]
            renamed_report.append(out)
        else:
            remove_keys.add(row["sourceKey"])
            removed_report.append(out)

    if set(rename_map) & remove_keys:
        raise ValueError("Rename/remove decision overlap")
    return rename_map, remove_keys, renamed_report, removed_report


def apply_name_decision(row: dict[str, str], key_field: str, name_field: str, rename_map: dict[str, str]) -> None:
    key = row[key_field]
    if key in rename_map:
        row[name_field] = rename_map[key]
    if "reviewFlags" in row:
        row["reviewFlags"] = update_pipe(row.get("reviewFlags", ""), "restaurant_display_quality_cleaned")
    if "reviewReasons" in row:
        row["reviewReasons"] = update_pipe(row.get("reviewReasons", ""), "음식점 건물명 표시 정리")


def update_adopted_all(rename_map: dict[str, str], remove_keys: set[str]) -> tuple[list[dict[str, str]], dict[str, str]]:
    rows = read_csv(ADOPTED_ALL)
    fieldnames = list(rows[0].keys())
    kept: list[dict[str, str]] = []
    place_id_by_source_key: dict[str, str] = {}
    for row in rows:
        source_key = row["sourceKey"]
        if source_key in remove_keys:
            continue
        if source_key in rename_map:
            apply_name_decision(row, "sourceKey", "name", rename_map)
        row["placeId"] = str(len(kept) + 1)
        place_id_by_source_key[source_key] = row["placeId"]
        kept.append(row)
    write_csv(ADOPTED_ALL, kept, fieldnames)
    return kept, place_id_by_source_key


def update_simple_csv(path: Path, key_field: str, name_field: str, rename_map: dict[str, str], remove_keys: set[str]) -> None:
    rows = read_csv(path)
    fieldnames = list(rows[0].keys())
    kept: list[dict[str, str]] = []
    for row in rows:
        key = row[key_field]
        if key in remove_keys:
            continue
        if key in rename_map:
            row[name_field] = rename_map[key]
        kept.append(row)
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


def update_facilities_js(rename_map: dict[str, str], remove_keys: set[str], place_id_by_source_key: dict[str, str]) -> None:
    geojson = load_facilities_geojson()
    features = []
    for feature in geojson["features"]:
        properties = feature["properties"]
        source_id = properties["sourceId"]
        if source_id in remove_keys:
            continue
        if source_id in rename_map:
            properties["name"] = rename_map[source_id]
            flags = properties.get("reviewFlags", [])
            if isinstance(flags, list) and "restaurant_display_quality_cleaned" not in flags:
                flags.append("restaurant_display_quality_cleaned")
                properties["reviewFlags"] = flags
            reasons = properties.get("reviewReasons", [])
            if isinstance(reasons, list) and "음식점 건물명 표시 정리" not in reasons:
                reasons.append("음식점 건물명 표시 정리")
                properties["reviewReasons"] = reasons
        properties["placeId"] = place_id_by_source_key[source_id]
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
    rename_map, remove_keys, renamed_report, removed_report = load_decisions()
    affected_files = [
        ADOPTED_ALL,
        ADOPTED_PLACES,
        ADOPTED_ACCESSIBILITY,
        ERD_PLACES,
        ERD_ACCESSIBILITY,
        FACILITIES_JS,
        ACCESSIBILITY_SUMMARY_JS,
        PLAN_CSV,
    ]
    backup_files(affected_files)

    before_counts = {
        "adopted_places_with_accessibility": len(read_csv(ADOPTED_ALL)),
        "adopted_places": len(read_csv(ADOPTED_PLACES)),
        "adopted_place_accessibility": len(read_csv(ADOPTED_ACCESSIBILITY)),
        "places_erd": len(read_csv(ERD_PLACES)),
        "place_accessibility_features_erd": len(read_csv(ERD_ACCESSIBILITY)),
        "facilities_geojson_features": len(load_facilities_geojson()["features"]),
    }

    adopted_rows, place_id_by_source_key = update_adopted_all(rename_map, remove_keys)
    update_simple_csv(ADOPTED_PLACES, "place_key", "place_name", rename_map, remove_keys)
    update_simple_csv(ADOPTED_ACCESSIBILITY, "place_key", "place_name", rename_map, remove_keys)
    write_erd(adopted_rows)
    update_facilities_js(rename_map, remove_keys, place_id_by_source_key)
    write_accessibility_summary(adopted_rows)

    if renamed_report:
        write_csv(OUT_RENAMED_CSV, renamed_report, list(renamed_report[0].keys()))
    if removed_report:
        write_csv(OUT_REMOVED_CSV, removed_report, list(removed_report[0].keys()))

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
            "renamed": len(rename_map),
            "removed": len(remove_keys),
            "processed": len(rename_map) + len(remove_keys),
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
