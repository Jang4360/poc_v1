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
ARCHIVE_DIR = POC_ROOT / "archive" / "20260426_facility_apply_1_2_before"

ACTION_PLAN = VALIDATION_DIR / "facility_cross_validation_action_plan.csv"

ADOPTED_ALL = DATA_ADOPTED / "adopted_places_with_accessibility.csv"
ADOPTED_PLACES = DATA_ADOPTED / "adopted_places.csv"
ADOPTED_ACCESSIBILITY = DATA_ADOPTED / "adopted_place_accessibility.csv"
ERD_PLACES = DATA_ADOPTED / "places_erd.csv"
ERD_ACCESSIBILITY = DATA_ADOPTED / "place_accessibility_features_erd.csv"
FACILITIES_JS = ASSETS_DATA / "facilities-data.js"
ACCESSIBILITY_SUMMARY_JS = ASSETS_DATA / "accessibility-summary-data.js"

OUT_SUMMARY_JSON = VALIDATION_DIR / "facility_apply_1_2_summary.json"
OUT_EXCLUDED_CSV = VALIDATION_DIR / "facility_apply_1_2_excluded.csv"
OUT_RENAMED_CSV = VALIDATION_DIR / "facility_apply_1_2_renamed.csv"

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


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def backup_files(paths: list[Path]) -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    for path in paths:
        relative = path.relative_to(POC_ROOT)
        destination = ARCHIVE_DIR / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copy2(path, destination)


def split_pipe(value: str) -> list[str]:
    return [item for item in value.split("|") if item]


def normalize_flags(flags: str, add_flag: str | None = None, remove_flags: set[str] | None = None) -> str:
    values = split_pipe(flags)
    remove_flags = remove_flags or set()
    values = [value for value in values if value not in remove_flags]
    if add_flag and add_flag not in values:
        values.append(add_flag)
    return "|".join(values)


def normalize_reasons(reasons: str, add_reason: str | None = None, remove_reasons: set[str] | None = None) -> str:
    values = split_pipe(reasons)
    remove_reasons = remove_reasons or set()
    values = [value for value in values if value not in remove_reasons]
    if add_reason and add_reason not in values:
        values.append(add_reason)
    return "|".join(values)


def load_actions() -> tuple[set[str], dict[str, str], list[dict[str, str]], list[dict[str, str]]]:
    rows = read_csv(ACTION_PLAN)
    excluded = [
        row
        for row in rows
        if row["suggested_apply_action"] == "EXCLUDE_IF_INTERNAL_TOILET_POLICY_ACCEPTED"
    ]
    renamed = [
        row
        for row in rows
        if row["suggested_apply_action"] == "RENAME_TO_SUGGESTED_NAME"
    ]
    exclude_keys = {row["place_key"] for row in excluded}
    rename_map = {row["place_key"]: row["suggested_name"] for row in renamed}
    if not all(rename_map.values()):
        raise ValueError("Some rename candidates have empty suggested_name")
    if exclude_keys & set(rename_map):
        raise ValueError("Exclude and rename actions overlap")
    return exclude_keys, rename_map, excluded, renamed


def update_adopted_all(exclude_keys: set[str], rename_map: dict[str, str]) -> tuple[list[dict[str, str]], dict[str, str]]:
    rows = read_csv(ADOPTED_ALL)
    fieldnames = list(rows[0].keys())
    kept: list[dict[str, str]] = []
    place_id_by_source_key: dict[str, str] = {}

    for row in rows:
        source_key = row["sourceKey"]
        if source_key in exclude_keys:
            continue
        if source_key in rename_map:
            row["name"] = rename_map[source_key]
            row["reviewFlags"] = normalize_flags(
                row.get("reviewFlags", ""),
                add_flag="name_corrected",
                remove_flags={"generic_name"},
            )
            row["reviewReasons"] = normalize_reasons(
                row.get("reviewReasons", ""),
                add_reason="POI/카카오 기준 이름 보정",
                remove_reasons={"이름/분류 애매"},
            )
        row["placeId"] = str(len(kept) + 1)
        place_id_by_source_key[source_key] = row["placeId"]
        kept.append(row)

    write_csv(ADOPTED_ALL, kept, fieldnames)
    return kept, place_id_by_source_key


def update_adopted_places(exclude_keys: set[str], rename_map: dict[str, str]) -> None:
    rows = read_csv(ADOPTED_PLACES)
    fieldnames = list(rows[0].keys())
    kept: list[dict[str, str]] = []
    for row in rows:
        place_key = row["place_key"]
        if place_key in exclude_keys:
            continue
        if place_key in rename_map:
            row["place_name"] = rename_map[place_key]
        kept.append(row)
    write_csv(ADOPTED_PLACES, kept, fieldnames)


def update_adopted_accessibility(exclude_keys: set[str], rename_map: dict[str, str]) -> None:
    rows = read_csv(ADOPTED_ACCESSIBILITY)
    fieldnames = list(rows[0].keys())
    kept: list[dict[str, str]] = []
    for row in rows:
        place_key = row["place_key"]
        if place_key in exclude_keys:
            continue
        if place_key in rename_map:
            row["place_name"] = rename_map[place_key]
        kept.append(row)
    write_csv(ADOPTED_ACCESSIBILITY, kept, fieldnames)


def write_erd_tables(adopted_rows: list[dict[str, str]]) -> None:
    erd_place_rows = [
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
    write_csv(ERD_PLACES, erd_place_rows, ["placeId", "name", "category", "address", "point", "providerPlaceId"])

    erd_accessibility_rows: list[dict[str, str]] = []
    next_id = 1
    for row in adopted_rows:
        for feature_type in split_pipe(row.get("erdAccessibilityTypes", "")):
            erd_accessibility_rows.append(
                {
                    "id": str(next_id),
                    "placeId": row["placeId"],
                    "featureType": feature_type,
                    "isAvailable": "true",
                }
            )
            next_id += 1
    write_csv(ERD_ACCESSIBILITY, erd_accessibility_rows, ["id", "placeId", "featureType", "isAvailable"])


def load_facilities_geojson() -> dict[str, object]:
    text = FACILITIES_JS.read_text(encoding="utf-8").strip()
    prefix = "window.FACILITIES_GEOJSON = "
    if not text.startswith(prefix):
        raise ValueError(f"Unexpected facilities-data.js prefix: {text[:80]}")
    if text.endswith(";"):
        text = text[:-1]
    return json.loads(text[len(prefix):])


def update_facilities_js(exclude_keys: set[str], rename_map: dict[str, str], place_id_by_source_key: dict[str, str]) -> None:
    geojson = load_facilities_geojson()
    features = []
    for feature in geojson["features"]:
        properties = feature["properties"]
        source_id = properties["sourceId"]
        if source_id in exclude_keys:
            continue
        if source_id in rename_map:
            properties["name"] = rename_map[source_id]
            flags = properties.get("reviewFlags", [])
            if isinstance(flags, list):
                flags = [flag for flag in flags if flag != "generic_name"]
                if "name_corrected" not in flags:
                    flags.append("name_corrected")
                properties["reviewFlags"] = flags
            reasons = properties.get("reviewReasons", [])
            if isinstance(reasons, list):
                reasons = [reason for reason in reasons if reason != "이름/분류 애매"]
                if "POI/카카오 기준 이름 보정" not in reasons:
                    reasons.append("POI/카카오 기준 이름 보정")
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
    affected_files = [
        ADOPTED_ALL,
        ADOPTED_PLACES,
        ADOPTED_ACCESSIBILITY,
        ERD_PLACES,
        ERD_ACCESSIBILITY,
        FACILITIES_JS,
        ACCESSIBILITY_SUMMARY_JS,
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

    exclude_keys, rename_map, excluded_rows, renamed_rows = load_actions()
    adopted_rows, place_id_by_source_key = update_adopted_all(exclude_keys, rename_map)
    update_adopted_places(exclude_keys, rename_map)
    update_adopted_accessibility(exclude_keys, rename_map)
    write_erd_tables(adopted_rows)
    update_facilities_js(exclude_keys, rename_map, place_id_by_source_key)
    write_accessibility_summary(adopted_rows)

    after_counts = {
        "adopted_places_with_accessibility": len(read_csv(ADOPTED_ALL)),
        "adopted_places": len(read_csv(ADOPTED_PLACES)),
        "adopted_place_accessibility": len(read_csv(ADOPTED_ACCESSIBILITY)),
        "places_erd": len(read_csv(ERD_PLACES)),
        "place_accessibility_features_erd": len(read_csv(ERD_ACCESSIBILITY)),
        "facilities_geojson_features": len(load_facilities_geojson()["features"]),
    }

    write_csv(OUT_EXCLUDED_CSV, excluded_rows, list(excluded_rows[0].keys()))
    write_csv(OUT_RENAMED_CSV, renamed_rows, list(renamed_rows[0].keys()))

    summary = {
        "applied": {
            "excluded_internal_toilets": len(exclude_keys),
            "renamed_places": len(rename_map),
        },
        "before": before_counts,
        "after": after_counts,
        "backup_dir": str(ARCHIVE_DIR),
        "outputs": {
            "excluded": str(OUT_EXCLUDED_CSV),
            "renamed": str(OUT_RENAMED_CSV),
        },
    }
    OUT_SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
