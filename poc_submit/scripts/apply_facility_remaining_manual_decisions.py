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
ARCHIVE_DIR = POC_ROOT / "archive" / "20260426_remaining_manual_before"

ADOPTED_ALL = DATA_ADOPTED / "adopted_places_with_accessibility.csv"
ADOPTED_PLACES = DATA_ADOPTED / "adopted_places.csv"
ADOPTED_ACCESSIBILITY = DATA_ADOPTED / "adopted_place_accessibility.csv"
ERD_PLACES = DATA_ADOPTED / "places_erd.csv"
ERD_ACCESSIBILITY = DATA_ADOPTED / "place_accessibility_features_erd.csv"
FACILITIES_JS = ASSETS_DATA / "facilities-data.js"
ACCESSIBILITY_SUMMARY_JS = ASSETS_DATA / "accessibility-summary-data.js"

REMAINING_MANUAL_IN = VALIDATION_DIR / "facility_apply_welfare_remaining_manual_94.csv"
REMAINING_MANUAL_OUT = VALIDATION_DIR / "facility_apply_remaining_manual_0.csv"
OUT_SUMMARY_JSON = VALIDATION_DIR / "facility_apply_remaining_manual_summary.json"
OUT_REMOVED_CSV = VALIDATION_DIR / "facility_apply_remaining_manual_removed.csv"
OUT_RENAMED_CSV = VALIDATION_DIR / "facility_apply_remaining_manual_renamed.csv"
OUT_KEPT_CSV = VALIDATION_DIR / "facility_apply_remaining_manual_kept_as_is.csv"

ERD_FEATURE_TYPES = ("ramp", "autoDoor", "elevator", "accessibleToilet", "chargingStation", "stepFree")
ERD_ACCESSIBILITY_LABELS = {
    "ramp": "경사로",
    "autoDoor": "자동문",
    "elevator": "엘리베이터",
    "accessibleToilet": "전용 화장실",
    "chargingStation": "전동보장구 충전",
    "stepFree": "단차 없음",
}

# Remove rows whose evidence points to a different service category, a building/entrance,
# or a broad tourist area where the current point is not a reliable destination.
REMOVE_KEYS = {
    # 음식·카페 category mismatch / entrance / building / non-food.
    "barrier_free_facility:9797",
    "barrier_free_facility:9819",
    "barrier_free_facility:9126",
    "barrier_free_facility:12446",
    "barrier_free_facility:12608",
    "barrier_free_facility:12922",
    "barrier_free_facility:12928",
    "barrier_free_facility:12955",
    "barrier_free_facility:12522",
    "barrier_free_facility:5910",
    "barrier_free_facility:4483",
    "barrier_free_facility:4578",
    "barrier_free_facility:3563",
    "barrier_free_facility:3729",
    "barrier_free_facility:4118",
    "barrier_free_facility:4177",
    "barrier_free_facility:6628",
    "barrier_free_facility:8152",
    "barrier_free_facility:5799",
    "barrier_free_facility:2938",
    "barrier_free_facility:12149",
    # 의료·보건 category mismatch.
    "barrier_free_facility:8370",
    "barrier_free_facility:12774",
    "barrier_free_facility:5922",
    "barrier_free_facility:4524",
    "barrier_free_facility:3003",
    "barrier_free_facility:2939",
    # 행정·공공기관 weak/wrong evidence.
    "barrier_free_facility:12961",
    "barrier_free_facility:2843",
    "barrier_free_facility:2860",
    "barrier_free_facility:2947",
    "barrier_free_facility:2942",
    "barrier_free_facility:2786",
    # 관광지 unreliable broad/incorrect evidence.
    "tourist_spot:101",
    "tourist_spot:18",
    "tourist_spot:190",
    "tourist_spot:214",
    "tourist_spot:132",
    "tourist_spot:140",
    # 숙박 wrong evidence.
    "barrier_free_facility:3024",
    "accommodation:129",
}

RENAME_MAP = {
    # 숙박.
    "barrier_free_facility:2846": "스마일모텔",
    "barrier_free_facility:3750": "사우스반데코호텔",
    "barrier_free_facility:3691": "다뉴브호텔",
    "barrier_free_facility:3749": "유나호텔 비지니스",
    "barrier_free_facility:11679": "세느모텔",
    "barrier_free_facility:11680": "호텔콤마",
    "barrier_free_facility:11681": "빈스70호텔",
    "barrier_free_facility:11688": "아비숑모텔",
    "barrier_free_facility:11696": "호텔앤레스트",
    "barrier_free_facility:11707": "하이모텔",
    "barrier_free_facility:10120": "호텔유아인",
    # 음식·카페.
    "barrier_free_facility:12930": "블레스브루",
    "barrier_free_facility:4017": "하린플라워숲공예카페",
    "barrier_free_facility:12403": "손이가네아이스크림할인백화점",
    "barrier_free_facility:11661": "경성코페사상점",
    "barrier_free_facility:3238": "영도우",
    "barrier_free_facility:6862": "구멍가게식당",
    # 의료·보건.
    "barrier_free_facility:8151": "금정형주요양병원",
    "barrier_free_facility:8333": "보람요양병원",
    "barrier_free_facility:8327": "한솔한의원",
    "barrier_free_facility:8348": "참좋은안과의원",
    "barrier_free_facility:8541": "동비한의원",
    "barrier_free_facility:4517": "김진동삼성내과의원",
    "barrier_free_facility:4559": "훈내과의원",
    "barrier_free_facility:3709": "드로잉의원",
    "barrier_free_facility:3733": "이미지플러스치과교정과치과의원",
    "barrier_free_facility:3449": "늘푸른의원",
    "barrier_free_facility:3710": "인애한의원 부산서면점",
    "barrier_free_facility:3711": "시스템성형외과의원",
    "barrier_free_facility:3713": "서면한의원",
    "barrier_free_facility:3735": "튼튼마디한의원",
    "barrier_free_facility:3740": "해아림한의원",
    "barrier_free_facility:3890": "본디올욱당한의원",
    "barrier_free_facility:4288": "신세계치과의원",
    "barrier_free_facility:11546": "씨티요양병원",
    "barrier_free_facility:11952": "강한의원",
    "barrier_free_facility:12183": "명인내과의원",
    "barrier_free_facility:11949": "주례정치과의원",
    "barrier_free_facility:8063": "감천참편한요양병원",
    "barrier_free_facility:2804": "장원송도요양병원",
    "barrier_free_facility:10086": "비에스정형외과의원",
    "barrier_free_facility:6550": "미소요양병원",
    "barrier_free_facility:6596": "한마음치과의원",
    "barrier_free_facility:6622": "센텀부부치과의원",
    "barrier_free_facility:6878": "성모이비인후과의원",
    "barrier_free_facility:6693": "센텀힐병원",
    # 행정·공공기관.
    "barrier_free_facility:6418": "구포제2동행정복지센터",
    "barrier_free_facility:8059": "감천2치안센터",
    "barrier_free_facility:3210": "봉래1동행정복지센터",
    # 관광지.
    "tourist_spot:161": "거가대교 홍보전시관",
    "tourist_spot:24": "부산강서문화원",
}

KEEP_AS_IS_KEYS = {
    # 숙박 current name is better than weak POI/Kakao result.
    "barrier_free_facility:3025",
    "barrier_free_facility:11673",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
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


def apply_name_decision(row: dict[str, str], key_field: str, name_field: str) -> None:
    key = row[key_field]
    if key in RENAME_MAP:
        row[name_field] = RENAME_MAP[key]
    if "reviewFlags" in row:
        row["reviewFlags"] = update_pipe(row.get("reviewFlags", ""), "remaining_manual_reviewed")
    if "reviewReasons" in row:
        row["reviewReasons"] = update_pipe(row.get("reviewReasons", ""), "잔여 수동 검토 반영")


def update_adopted_all() -> tuple[list[dict[str, str]], dict[str, str]]:
    rows = read_csv(ADOPTED_ALL)
    fieldnames = list(rows[0].keys())
    kept: list[dict[str, str]] = []
    place_id_by_source_key: dict[str, str] = {}
    for row in rows:
        source_key = row["sourceKey"]
        if source_key in REMOVE_KEYS:
            continue
        apply_name_decision(row, "sourceKey", "name")
        row["placeId"] = str(len(kept) + 1)
        place_id_by_source_key[source_key] = row["placeId"]
        kept.append(row)
    write_csv(ADOPTED_ALL, kept, fieldnames)
    return kept, place_id_by_source_key


def update_simple_csv(path: Path, key_field: str, name_field: str) -> None:
    rows = read_csv(path)
    fieldnames = list(rows[0].keys())
    kept: list[dict[str, str]] = []
    for row in rows:
        key = row[key_field]
        if key in REMOVE_KEYS:
            continue
        apply_name_decision(row, key_field, name_field)
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
    return json.loads(text[len(prefix):])


def update_facilities_js(place_id_by_source_key: dict[str, str]) -> None:
    processed_keep_keys = set(RENAME_MAP) | KEEP_AS_IS_KEYS
    geojson = load_facilities_geojson()
    features = []
    for feature in geojson["features"]:
        properties = feature["properties"]
        source_id = properties["sourceId"]
        if source_id in REMOVE_KEYS:
            continue
        if source_id in RENAME_MAP:
            properties["name"] = RENAME_MAP[source_id]
        flags = properties.get("reviewFlags", [])
        if isinstance(flags, list) and source_id in processed_keep_keys:
            if "remaining_manual_reviewed" not in flags:
                flags.append("remaining_manual_reviewed")
            properties["reviewFlags"] = flags
        reasons = properties.get("reviewReasons", [])
        if isinstance(reasons, list) and source_id in processed_keep_keys:
            if "잔여 수동 검토 반영" not in reasons:
                reasons.append("잔여 수동 검토 반영")
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


def write_decision_reports() -> None:
    manual_rows = read_csv(REMAINING_MANUAL_IN)
    by_key = {row["place_key"]: row for row in manual_rows}
    processed_keys = REMOVE_KEYS | set(RENAME_MAP) | KEEP_AS_IS_KEYS
    missing = processed_keys - set(by_key)
    if missing:
        raise ValueError(f"Decision key missing from manual file: {sorted(missing)}")
    remaining = [row for row in manual_rows if row["place_key"] not in processed_keys]
    if remaining:
        raise ValueError(f"Unprocessed manual keys remain: {[row['place_key'] for row in remaining]}")

    removed = [by_key[key] for key in sorted(REMOVE_KEYS)]
    renamed = []
    for key in sorted(RENAME_MAP):
        row = dict(by_key[key])
        row["applied_name"] = RENAME_MAP[key]
        renamed.append(row)
    kept = [by_key[key] for key in sorted(KEEP_AS_IS_KEYS)]

    write_csv(OUT_REMOVED_CSV, removed, list(removed[0].keys()))
    write_csv(OUT_RENAMED_CSV, renamed, list(renamed[0].keys()))
    write_csv(OUT_KEPT_CSV, kept, list(kept[0].keys()))
    write_csv(REMAINING_MANUAL_OUT, remaining, list(manual_rows[0].keys()))


def main() -> None:
    affected_files = [
        ADOPTED_ALL,
        ADOPTED_PLACES,
        ADOPTED_ACCESSIBILITY,
        ERD_PLACES,
        ERD_ACCESSIBILITY,
        FACILITIES_JS,
        ACCESSIBILITY_SUMMARY_JS,
        REMAINING_MANUAL_IN,
    ]
    backup_files(affected_files)
    before_counts = {
        "adopted_places_with_accessibility": len(read_csv(ADOPTED_ALL)),
        "adopted_places": len(read_csv(ADOPTED_PLACES)),
        "adopted_place_accessibility": len(read_csv(ADOPTED_ACCESSIBILITY)),
        "places_erd": len(read_csv(ERD_PLACES)),
        "place_accessibility_features_erd": len(read_csv(ERD_ACCESSIBILITY)),
        "facilities_geojson_features": len(load_facilities_geojson()["features"]),
        "remaining_manual": len(read_csv(REMAINING_MANUAL_IN)),
    }

    adopted_rows, place_id_by_source_key = update_adopted_all()
    update_simple_csv(ADOPTED_PLACES, "place_key", "place_name")
    update_simple_csv(ADOPTED_ACCESSIBILITY, "place_key", "place_name")
    write_erd(adopted_rows)
    update_facilities_js(place_id_by_source_key)
    write_accessibility_summary(adopted_rows)
    write_decision_reports()

    after_counts = {
        "adopted_places_with_accessibility": len(read_csv(ADOPTED_ALL)),
        "adopted_places": len(read_csv(ADOPTED_PLACES)),
        "adopted_place_accessibility": len(read_csv(ADOPTED_ACCESSIBILITY)),
        "places_erd": len(read_csv(ERD_PLACES)),
        "place_accessibility_features_erd": len(read_csv(ERD_ACCESSIBILITY)),
        "facilities_geojson_features": len(load_facilities_geojson()["features"]),
        "remaining_manual": len(read_csv(REMAINING_MANUAL_OUT)),
    }
    summary = {
        "applied": {
            "removed": len(REMOVE_KEYS),
            "renamed": len(RENAME_MAP),
            "kept_as_is": len(KEEP_AS_IS_KEYS),
            "processed": len(REMOVE_KEYS | set(RENAME_MAP) | KEEP_AS_IS_KEYS),
        },
        "before": before_counts,
        "after": after_counts,
        "backup_dir": str(ARCHIVE_DIR),
        "outputs": {
            "removed": str(OUT_REMOVED_CSV),
            "renamed": str(OUT_RENAMED_CSV),
            "kept_as_is": str(OUT_KEPT_CSV),
            "remaining_manual": str(REMAINING_MANUAL_OUT),
        },
    }
    OUT_SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
