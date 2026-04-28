from __future__ import annotations

import csv
import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any


POC_ROOT = Path(__file__).resolve().parents[1]
DATA_ADOPTED = POC_ROOT / "data" / "adopted"
DATA_FINAL = POC_ROOT / "data" / "final" / "facilities"
ASSETS_DATA = POC_ROOT / "assets" / "data"
REPORT_DIR = POC_ROOT / "data" / "reports" / "facility_validation"
ARCHIVE_DIR = POC_ROOT / "archive" / "20260427_toilet_display_scope_policy_before"

ADOPTED_ALL = DATA_ADOPTED / "adopted_places_with_accessibility.csv"
ADOPTED_PLACES = DATA_ADOPTED / "adopted_places.csv"
ADOPTED_ACCESSIBILITY = DATA_ADOPTED / "adopted_place_accessibility.csv"
ERD_PLACES = DATA_ADOPTED / "places_erd.csv"
ERD_ACCESSIBILITY = DATA_ADOPTED / "place_accessibility_features_erd.csv"
FACILITIES_JS = ASSETS_DATA / "facilities-data.js"
ACCESSIBILITY_SUMMARY_JS = ASSETS_DATA / "accessibility-summary-data.js"

CLASSIFIED_CSV = REPORT_DIR / "toilet_display_scope_policy_classified.csv"
REMOVED_CSV = REPORT_DIR / "toilet_display_scope_policy_removed.csv"
SUMMARY_JSON = REPORT_DIR / "toilet_display_scope_policy_summary.json"

ERD_FEATURE_TYPES = ("ramp", "autoDoor", "elevator", "accessibleToilet", "chargingStation", "stepFree")
ERD_ACCESSIBILITY_LABELS = {
    "ramp": "경사로",
    "autoDoor": "자동문",
    "elevator": "엘리베이터",
    "accessibleToilet": "전용 화장실",
    "chargingStation": "전동보장구 충전",
    "stepFree": "단차 없음",
}

PRIVATE_TOILET_NAME_TERMS = [
    "고객편의시설",
    "백화점",
    "아울렛",
    "쇼핑",
    "호텔",
    "모텔",
    "여관",
    "주유소",
    "아파트",
    "오피스텔",
    "상가",
    "마트",
]

PUBLIC_TOILET_TERMS = [
    "공중화장실",
    "공용화장실",
    "공공화장실",
    "간이화장실",
    "이동식화장실",
    "개방화장실",
]

PUBLIC_AREA_TERMS = [
    "공원",
    "해수욕장",
    "광장",
    "산책로",
    "등산로",
    "둘레길",
    "수변",
    "강변",
    "하천",
    "유원지",
    "해변",
    "항",
    "섬",
    "숲",
    "유수지",
    "전망대",
    "문화마당",
    "문화마을",
    "마루터",
    "쉼터",
    "봉",
    "약수터",
    "방파제",
    "대교",
    "수원지",
    "천변",
    "마을",
]

PUBLIC_FACILITY_TERMS = [
    "주민센터",
    "행정복지센터",
    "도서관",
    "복지관",
    "보건소",
    "경찰서",
    "지구대",
    "파출소",
    "치안센터",
    "소방서",
    "119",
    "우체국",
    "구청",
    "시청",
    "군청",
    "세무서",
    "세관",
    "출입국",
    "공단",
    "국민건강보험",
    "센터",
    "터미널",
    "역",
    "지하철",
    "체육",
    "박물관",
    "미술관",
    "관광안내소",
    "관리사무소",
    "관리동",
    "관리",
    "회관",
    "문화원",
    "기념관",
    "공연장",
    "소극장",
    "영화의전당",
    "학교",
    "시장",
]

LOCATION_HINT_TERMS = ["옆", "앞", "뒤", "입구", "인근", "주변", "부근", "맞은편", "내"]

TOILET_SCOPE_LABELS = {
    "PUBLIC_TOILET": "공중화장실",
    "FACILITY_TOILET": "시설 내 화장실",
    "REVIEW_TOILET": "화장실 검토 필요",
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


def append_pipe(value: str, item: str) -> str:
    values = split_pipe(value)
    if item not in values:
        values.append(item)
    return "|".join(values)


def find_term(text: str, terms: list[str]) -> str:
    for term in terms:
        if term and term in text:
            return term
    return ""


def text_for_private_check(row: dict[str, str]) -> str:
    return " ".join([row.get("name", ""), row.get("publicFacilityName", "")])


def text_for_scope_check(row: dict[str, str]) -> str:
    return " ".join(
        [
            row.get("name", ""),
            row.get("publicFacilityName", ""),
            row.get("publicFacilityType", ""),
        ]
    )


def classify_toilet(row: dict[str, str]) -> tuple[str, str, str, str]:
    private_term = find_term(text_for_private_check(row), PRIVATE_TOILET_NAME_TERMS)
    if private_term:
        return "REMOVE_PRIVATE_OR_INTERNAL", private_term, "", "민간/상업 시설 내부 화장실 가능성이 높아 서비스 목적지에서 제외"

    text = text_for_scope_check(row)
    public_term = find_term(text, PUBLIC_TOILET_TERMS)
    area_term = find_term(text, PUBLIC_AREA_TERMS)
    facility_term = find_term(text, PUBLIC_FACILITY_TERMS)
    location_term = find_term(text, LOCATION_HINT_TERMS)

    if public_term and not facility_term:
        return "KEEP", public_term, "PUBLIC_TOILET", "명칭 자체가 공중/개방 화장실 계열"
    if area_term and not facility_term:
        return "KEEP", area_term, "PUBLIC_TOILET", "공원/해변/광장 등 공공 구역 화장실"
    if facility_term:
        return "KEEP", facility_term, "FACILITY_TOILET", "공공시설 또는 다중이용시설 내부 화장실"
    if public_term or area_term:
        return "KEEP", public_term or area_term, "PUBLIC_TOILET", "공중 이용 가능성이 있는 화장실"
    if "화장실" in text or location_term:
        return "KEEP", location_term or "화장실", "REVIEW_TOILET", "명칭만으로 공중/시설 내부 여부 추가 확인 필요"
    return "KEEP", "", "REVIEW_TOILET", "공중화장실 원본이나 명칭에 화장실 표현이 없어 표시 품질 확인 필요"


def backup_files(paths: list[Path]) -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    for path in paths:
        if not path.exists():
            continue
        destination = ARCHIVE_DIR / path.relative_to(POC_ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copy2(path, destination)


def read_policy_start_rows() -> list[dict[str, str]]:
    archived = ARCHIVE_DIR / ADOPTED_ALL.relative_to(POC_ROOT)
    if archived.exists():
        return read_csv(archived)
    return read_csv(ADOPTED_ALL)


def load_facilities_geojson() -> dict[str, Any]:
    text = FACILITIES_JS.read_text(encoding="utf-8").strip()
    prefix = "window.FACILITIES_GEOJSON = "
    if not text.startswith(prefix):
        raise ValueError("Unexpected facilities JS format")
    if text.endswith(";"):
        text = text[:-1]
    return json.loads(text[len(prefix) :])


def write_facilities_geojson(geojson: dict[str, Any]) -> None:
    FACILITIES_JS.write_text(
        "window.FACILITIES_GEOJSON = "
        + json.dumps(geojson, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )


def update_adopted_all() -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, Any]]]:
    rows = read_csv(ADOPTED_ALL)
    fieldnames = list(rows[0].keys())
    for extra in ["toiletScope", "toiletScopeLabel", "toiletScopeReason"]:
        if extra not in fieldnames:
            fieldnames.append(extra)

    kept: list[dict[str, str]] = []
    removed: list[dict[str, str]] = []
    classified: list[dict[str, Any]] = []

    for row in rows:
        if row["dbCategory"] != "TOILET":
            row.setdefault("toiletScope", "")
            row.setdefault("toiletScopeLabel", "")
            row.setdefault("toiletScopeReason", "")
            kept.append(row)
            continue

        action, matched_term, scope, reason = classify_toilet(row)
        classified.append(
            {
                "sourceKey": row["sourceKey"],
                "placeIdBefore": row["placeId"],
                "name": row["name"],
                "address": row["address"],
                "sourceDataset": row["sourceDataset"],
                "action": action,
                "matchedTerm": matched_term,
                "toiletScope": scope,
                "toiletScopeLabel": TOILET_SCOPE_LABELS.get(scope, ""),
                "reason": reason,
            }
        )

        if action.startswith("REMOVE"):
            out = dict(row)
            out["removeReason"] = reason
            out["matchedTerm"] = matched_term
            removed.append(out)
            continue

        row["toiletScope"] = scope
        row["toiletScopeLabel"] = TOILET_SCOPE_LABELS.get(scope, "화장실")
        row["toiletScopeReason"] = reason
        row["facilityCategory"] = row["toiletScopeLabel"]
        row["uiCategory"] = row["toiletScopeLabel"]
        row["reviewFlags"] = append_pipe(row.get("reviewFlags", ""), "toilet_display_scope_classified")
        row["reviewReasons"] = append_pipe(row.get("reviewReasons", ""), reason)
        kept.append(row)

    for idx, row in enumerate(kept, start=1):
        row["placeId"] = str(idx)

    write_csv(ADOPTED_ALL, kept, fieldnames)
    return kept, removed, classified


def update_adopted_places(kept_rows: list[dict[str, str]]) -> None:
    by_key = {row["sourceKey"]: row for row in kept_rows}
    rows = read_csv(ADOPTED_PLACES)
    fieldnames = list(rows[0].keys())
    for extra in ["toilet_scope", "toilet_scope_label", "toilet_scope_reason"]:
        if extra not in fieldnames:
            fieldnames.append(extra)

    out_rows: list[dict[str, str]] = []
    for row in rows:
        source_key = row["place_key"]
        adopted = by_key.get(source_key)
        if not adopted:
            continue
        row["ui_category"] = adopted["uiCategory"]
        row["toilet_scope"] = adopted.get("toiletScope", "")
        row["toilet_scope_label"] = adopted.get("toiletScopeLabel", "")
        row["toilet_scope_reason"] = adopted.get("toiletScopeReason", "")
        out_rows.append(row)
    write_csv(ADOPTED_PLACES, out_rows, fieldnames)


def update_adopted_accessibility(kept_rows: list[dict[str, str]]) -> None:
    by_key = {row["sourceKey"]: row for row in kept_rows}
    rows = read_csv(ADOPTED_ACCESSIBILITY)
    fieldnames = list(rows[0].keys())
    out_rows: list[dict[str, str]] = []
    for row in rows:
        source_key = row["place_key"]
        adopted = by_key.get(source_key)
        if not adopted:
            continue
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
        props["facilityCategory"] = adopted["facilityCategory"]
        props["uiCategory"] = adopted["uiCategory"]
        props["displaySource"] = adopted["facilityCategory"]
        props["toiletScope"] = adopted.get("toiletScope", "")
        props["toiletScopeLabel"] = adopted.get("toiletScopeLabel", "")
        props["toiletScopeReason"] = adopted.get("toiletScopeReason", "")
        if adopted["dbCategory"] == "TOILET":
            flags = props.get("reviewFlags", [])
            if isinstance(flags, list) and "toilet_display_scope_classified" not in flags:
                flags.append("toilet_display_scope_classified")
                props["reviewFlags"] = flags
            reasons = props.get("reviewReasons", [])
            reason = adopted.get("toiletScopeReason", "")
            if isinstance(reasons, list) and reason and reason not in reasons:
                reasons.append(reason)
                props["reviewReasons"] = reasons
        features.append(feature)
    geojson["features"] = features
    write_facilities_geojson(geojson)


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


def copy_to_final() -> None:
    DATA_FINAL.mkdir(parents=True, exist_ok=True)
    copies = {
        ADOPTED_ALL: DATA_FINAL / "adopted_places_with_accessibility_final.csv",
        ADOPTED_PLACES: DATA_FINAL / "adopted_places_final.csv",
        ADOPTED_ACCESSIBILITY: DATA_FINAL / "adopted_place_accessibility_final.csv",
        ERD_PLACES: DATA_FINAL / "places_erd.csv",
        ERD_ACCESSIBILITY: DATA_FINAL / "place_accessibility_features_erd.csv",
    }
    for source, destination in copies.items():
        shutil.copy2(source, destination)


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
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

    policy_start_rows = read_policy_start_rows()
    before_rows = read_csv(ADOPTED_ALL)
    before_counts = {
        "places": len(before_rows),
        "toilets": sum(1 for row in before_rows if row["dbCategory"] == "TOILET"),
    }

    kept_rows, removed, classified = update_adopted_all()
    update_adopted_places(kept_rows)
    update_adopted_accessibility(kept_rows)
    write_erd(kept_rows)
    update_facilities_js(kept_rows)
    write_accessibility_summary(kept_rows)
    copy_to_final()

    final_toilets = [row for row in kept_rows if row["dbCategory"] == "TOILET"]
    current_source_keys = {row["sourceKey"] for row in kept_rows}
    removed_since_policy_start = [row for row in policy_start_rows if row["sourceKey"] not in current_source_keys]
    after_counts = {
        "places": len(kept_rows),
        "toilets": len(final_toilets),
        "toiletScopeLabels": dict(Counter(row.get("toiletScopeLabel", "") for row in final_toilets)),
        "facilityCategoryCounts": dict(Counter(row["facilityCategory"] for row in kept_rows)),
        "removedThisRun": len(removed),
        "removedSincePolicyStart": len(removed_since_policy_start),
    }

    write_csv(
        CLASSIFIED_CSV,
        classified,
        [
            "sourceKey",
            "placeIdBefore",
            "name",
            "address",
            "sourceDataset",
            "action",
            "matchedTerm",
            "toiletScope",
            "toiletScopeLabel",
            "reason",
        ],
    )
    removed_report = [
        {
            "sourceKey": row["sourceKey"],
            "sourceDataset": row["sourceDataset"],
            "placeIdBefore": row["placeId"],
            "name": row["name"],
            "address": row["address"],
            "removeReason": row.get("removeReason", "민간/상업 시설 내부 화장실 가능성이 높아 서비스 목적지에서 제외"),
            "matchedTerm": row.get("matchedTerm", ""),
        }
        for row in (removed or removed_since_policy_start)
    ]
    write_csv(
        REMOVED_CSV,
        removed_report,
        ["sourceKey", "sourceDataset", "placeIdBefore", "name", "address", "removeReason", "matchedTerm"],
    )

    summary = {
        "policy": {
            "keepPublicToilet": "독립 공중화장실, 공원/해변/광장 등 공공 구역 화장실",
            "keepFacilityToilet": "공공시설 또는 다중이용시설 내부 화장실. 지도에는 시설 내 화장실로 표시",
            "remove": "마트/상가/호텔/주유소/아파트/고객편의시설 등 공개성이 낮은 민간 내부 화장실",
        },
        "policyStart": {
            "places": len(policy_start_rows),
            "toilets": sum(1 for row in policy_start_rows if row["dbCategory"] == "TOILET"),
        },
        "before": before_counts,
        "after": after_counts,
        "outputs": {
            "classified": str(CLASSIFIED_CSV),
            "removed": str(REMOVED_CSV),
        },
    }
    SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
