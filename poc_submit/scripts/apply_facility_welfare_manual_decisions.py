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
ARCHIVE_DIR = POC_ROOT / "archive" / "20260426_welfare_manual_before"

ADOPTED_ALL = DATA_ADOPTED / "adopted_places_with_accessibility.csv"
ADOPTED_PLACES = DATA_ADOPTED / "adopted_places.csv"
ADOPTED_ACCESSIBILITY = DATA_ADOPTED / "adopted_place_accessibility.csv"
ERD_PLACES = DATA_ADOPTED / "places_erd.csv"
ERD_ACCESSIBILITY = DATA_ADOPTED / "place_accessibility_features_erd.csv"
FACILITIES_JS = ASSETS_DATA / "facilities-data.js"
ACCESSIBILITY_SUMMARY_JS = ASSETS_DATA / "accessibility-summary-data.js"

REMAINING_MANUAL_IN = VALIDATION_DIR / "facility_apply_1_2_remaining_manual_174.csv"
REMAINING_MANUAL_OUT = VALIDATION_DIR / "facility_apply_welfare_remaining_manual_94.csv"
OUT_SUMMARY_JSON = VALIDATION_DIR / "facility_apply_welfare_summary.json"
OUT_REMOVED_CSV = VALIDATION_DIR / "facility_apply_welfare_removed.csv"
OUT_RENAMED_CSV = VALIDATION_DIR / "facility_apply_welfare_renamed.csv"
OUT_KEPT_CSV = VALIDATION_DIR / "facility_apply_welfare_kept_as_is.csv"

ERD_FEATURE_TYPES = ("ramp", "autoDoor", "elevator", "accessibleToilet", "chargingStation", "stepFree")
ERD_ACCESSIBILITY_LABELS = {
    "ramp": "경사로",
    "autoDoor": "자동문",
    "elevator": "엘리베이터",
    "accessibleToilet": "전용 화장실",
    "chargingStation": "전동보장구 충전",
    "stepFree": "단차 없음",
}

# Criteria:
# - Keep social-welfare destinations: 경로당/노인정/노인회, 노인복지, 요양, 데이케어, 주간보호,
#   지역아동센터, 복지원, 사회복지법인, 모성원/위기임산부상담.
# - Do not use shelter-only labels like 무더위쉼터/한파쉼터 as place names.
# - Remove rows whose best evidence points to non-welfare places such as church, shop,
#   apartment charger, villa, restaurant, or plain community hall without welfare context.
REMOVE_KEYS = {
    "barrier_free_facility:12537",  # 장안상회/마을회관: 경로당명 근거 부족
    "barrier_free_facility:12954",  # 상리마을회관: 복지 목적지명 근거 부족
    "barrier_free_facility:12499",  # 우리교회
    "barrier_free_facility:12600",  # 효암이주민회관
    "barrier_free_facility:12733",  # 강변독점마을회관/쉼터
    "barrier_free_facility:4374",   # 요양보호사교육원
    "barrier_free_facility:3442",   # 수녀회
    "barrier_free_facility:10160",  # 삼전빌라
    "barrier_free_facility:8082",   # 노포마을회관
    "barrier_free_facility:2337",   # 해뜨는집/갈대집, 음식점 근거
}

RENAME_MAP = {
    "barrier_free_facility:9651": "성산1구경로당",
    "barrier_free_facility:9367": "순서경로당",
    "barrier_free_facility:9831": "진애원",
    "barrier_free_facility:8367": "구서1동경로당",
    "barrier_free_facility:9096": "금동경로당",
    "barrier_free_facility:8341": "금정데이케어센터",
    "barrier_free_facility:8891": "케어링 주간보호센터 부산금정점",
    "barrier_free_facility:9129": "회동경로당",
    "barrier_free_facility:12511": "시장마을여자경로당",
    "barrier_free_facility:12543": "용소경로당",
    "barrier_free_facility:12567": "소풍노인복지센터",
    "barrier_free_facility:12920": "이천동서여자경로당",
    "barrier_free_facility:12580": "공원실버케어센터",
    "barrier_free_facility:12597": "임랑해맞이마을 노인정",
    "barrier_free_facility:12949": "사회복지법인대성원",
    "barrier_free_facility:5931": "활기찬성모재활센터",
    "barrier_free_facility:5916": "푸른솔경로당",
    "barrier_free_facility:5814": "한솔보금자리실버홈",
    "barrier_free_facility:5888": "중부녀경로당",
    "barrier_free_facility:2949": "수오부녀경로당",
    "barrier_free_facility:3009": "좌천4동통합경로당",
    "barrier_free_facility:2859": "선화부녀경로당",
    "barrier_free_facility:4527": "동부산재활주간보호센터",
    "barrier_free_facility:4652": "동래주간보호센터",
    "barrier_free_facility:3564": "보성경로당",
    "barrier_free_facility:6408": "구남경로당",
    "barrier_free_facility:6226": "상학경로당",
    "barrier_free_facility:6304": "음정골경로당",
    "barrier_free_facility:11871": "감전본동경로당",
    "barrier_free_facility:11605": "효심주간보호센터",
    "barrier_free_facility:11633": "햇살재활주간보호센터",
    "barrier_free_facility:11655": "서부산노인요양원",
    "barrier_free_facility:11663": "괘내행복마을지역아동센터",
    "barrier_free_facility:11945": "온골경로당",
    "barrier_free_facility:11917": "동주경로당",
    "barrier_free_facility:2509": "실버웰노인요양센터",
    "barrier_free_facility:2777": "1308 위기임산부상담 부산지역상담기관",
    "barrier_free_facility:10777": "일송정경로당",
    "barrier_free_facility:10143": "녹원요양원",
    "barrier_free_facility:9869": "대림복지센터",
    "barrier_free_facility:10135": "연오경로당",
    "barrier_free_facility:10194": "연산6동경로당",
    "barrier_free_facility:3127": "신남항경로당",
    "barrier_free_facility:3249": "청학1동경로당",
    "barrier_free_facility:6551": "송원경로당",
    "barrier_free_facility:6583": "신촌경로당",
    "barrier_free_facility:6531": "반송지역아동센터",
    "barrier_free_facility:6703": "영화소규모요양시설",
    "barrier_free_facility:9373": "월포경로당",
}

KEEP_AS_IS_KEYS = {
    "barrier_free_facility:12507",
    "barrier_free_facility:12975",
    "barrier_free_facility:3005",
    "barrier_free_facility:4163",
    "barrier_free_facility:3567",
    "barrier_free_facility:6318",
    "barrier_free_facility:6441",
    "barrier_free_facility:6075",
    "barrier_free_facility:6315",
    "barrier_free_facility:6098",
    "barrier_free_facility:6397",
    "barrier_free_facility:11848",
    "barrier_free_facility:11566",
    "barrier_free_facility:12092",
    "barrier_free_facility:9871",
    "barrier_free_facility:9880",
    "barrier_free_facility:3253",
    "barrier_free_facility:6608",
    "barrier_free_facility:7341",
    "barrier_free_facility:6533",
    "barrier_free_facility:9818",
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
        row["reviewFlags"] = update_pipe(row.get("reviewFlags", ""), "welfare_manual_reviewed")
    if "reviewReasons" in row:
        row["reviewReasons"] = update_pipe(row.get("reviewReasons", ""), "복지·돌봄 수동 검토 반영")


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
        processed_keep_keys = set(RENAME_MAP) | KEEP_AS_IS_KEYS
        if isinstance(flags, list) and source_id in processed_keep_keys:
            if "welfare_manual_reviewed" not in flags:
                flags.append("welfare_manual_reviewed")
            properties["reviewFlags"] = flags
        reasons = properties.get("reviewReasons", [])
        if isinstance(reasons, list) and source_id in processed_keep_keys:
            if "복지·돌봄 수동 검토 반영" not in reasons:
                reasons.append("복지·돌봄 수동 검토 반영")
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

    removed = [by_key[key] for key in sorted(REMOVE_KEYS)]
    renamed = []
    for key in sorted(RENAME_MAP):
        row = dict(by_key[key])
        row["applied_name"] = RENAME_MAP[key]
        renamed.append(row)
    kept = [by_key[key] for key in sorted(KEEP_AS_IS_KEYS)]
    remaining = [row for row in manual_rows if row["place_key"] not in processed_keys]

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
            "welfare_removed": len(REMOVE_KEYS),
            "welfare_renamed": len(RENAME_MAP),
            "welfare_kept_as_is": len(KEEP_AS_IS_KEYS),
            "welfare_processed": len(REMOVE_KEYS | set(RENAME_MAP) | KEEP_AS_IS_KEYS),
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
