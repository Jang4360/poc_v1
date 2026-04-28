from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any


POC_ROOT = Path(__file__).resolve().parents[1]
FACILITIES_JS = POC_ROOT / "assets" / "data" / "facilities-data.js"
SEED_JS = POC_ROOT / "assets" / "data" / "manual-review-seed-data.js"
KAKAO_REFRESH_CSV = POC_ROOT / "data" / "reports" / "facility_validation" / "facility_kakao_first_refresh_all.csv"
OUT_CSV = POC_ROOT / "data" / "reports" / "facility_validation" / "facility_direct_category_review.csv"
OUT_SUMMARY = POC_ROOT / "data" / "reports" / "facility_validation" / "facility_direct_category_review_summary.json"


def load_js_assignment(path: Path, marker: str) -> Any:
    text = path.read_text(encoding="utf-8")
    prefix = f"window.{marker} = "
    if not text.startswith(prefix):
        raise ValueError(f"Unexpected JS data format: {path}")
    payload = text[len(prefix) :].strip()
    if payload.endswith(";"):
        payload = payload[:-1]
    return json.loads(payload)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def manual_review_key(feature: dict[str, Any]) -> str:
    properties = feature.get("properties", {})
    coordinates = feature.get("geometry", {}).get("coordinates", ["", ""])
    source_id = (
        properties.get("placeId")
        or properties.get("sourceKey")
        or properties.get("sourceId")
        or properties.get("providerPlaceId")
        or f"{properties.get('name', 'facility')}:{coordinates[1]}:{coordinates[0]}"
    )
    return f"facility:{source_id}"


def normalize(value: str) -> str:
    return re.sub(r"\s+", "", value or "").lower()


def category_from_kakao(kakao_category: str, kakao_name: str = "") -> str:
    text = f"{kakao_category} {kakao_name}"
    if re.search(r"화장실", text):
        return "TOILET"
    if re.search(r"휠체어|보장구", text):
        return "CHARGING_STATION"
    if re.search(r"음식점|한식|중식|일식|양식|분식|카페|커피|술집|주점|제과|디저트|패스트푸드|간식", text):
        return "RESTAURANT"
    if re.search(r"호텔|모텔|숙박|펜션|콘도|리조트|게스트하우스", text):
        return "ACCOMMODATION"
    if re.search(r"병원|의원|치과|한의원|보건소|의료|약국|요양병원", text):
        return "HEALTHCARE"
    if re.search(r"복지|경로당|요양원|장애인|노인|사회복지|돌봄", text):
        return "WELFARE"
    if re.search(r"행정기관|공공기관|경찰서|지구대|파출소|소방서|우체국|공단|주민센터|행정복지센터|도서관|교육청", text):
        return "PUBLIC_OFFICE"
    if re.search(r"관광|명소|공원|해수욕장|사찰|절|박물관|미술관|전시|공연|영화관|문화|놀이|테마파크|수련관|체험|아울렛|백화점|쇼핑", text):
        return "TOURIST_SPOT"
    return ""


def is_hard_remove_context(kakao_category: str, kakao_name: str, poi_name: str) -> bool:
    text = f"{kakao_category} {kakao_name} {poi_name}"
    return bool(re.search(r"석유|에너지|제조|공장|산업|기업|회사|건물|빌딩|프라자|타워|아파트|오피스텔", text))


def name_matches(source_name: str, kakao_name: str, poi_name: str) -> bool:
    source = normalize(source_name)
    kakao = normalize(kakao_name)
    poi = normalize(poi_name)
    if not source:
        return False
    return bool(
        kakao and (source in kakao or kakao in source)
        or poi and (source in poi or poi in source)
    )


def classify(row: dict[str, str], feature: dict[str, Any], seed: dict[str, str]) -> dict[str, str]:
    properties = feature.get("properties", {})
    current_category = properties.get("dbCategory", "")
    kakao_category = row.get("kakao_category", "")
    kakao_name = row.get("kakao_place_name") or seed.get("kakaoPlaceName", "")
    poi_name = row.get("poi_name") or seed.get("poiName", "")
    mapped_category = category_from_kakao(kakao_category, kakao_name)
    matched_name = name_matches(properties.get("name", ""), kakao_name, poi_name)

    if is_hard_remove_context(kakao_category, kakao_name, poi_name) and mapped_category not in {
        "PUBLIC_OFFICE",
        "HEALTHCARE",
        "WELFARE",
        "ACCOMMODATION",
    }:
        return {
            "suggestedAction": "REMOVE_CANDIDATE",
            "suggestedCategory": "",
            "confidence": "HIGH" if matched_name else "MEDIUM",
            "decisionReason": "카카오/POI 근거가 산업·기업·건물 맥락이라 서비스 채택 카테고리와 맞지 않음",
        }

    if mapped_category and mapped_category == current_category:
        return {
            "suggestedAction": "KEEP",
            "suggestedCategory": current_category,
            "confidence": "HIGH" if matched_name else "MEDIUM",
            "decisionReason": "카카오 카테고리가 현재 서비스 카테고리와 일치",
        }

    if mapped_category and mapped_category != current_category:
        return {
            "suggestedAction": "RECATEGORY",
            "suggestedCategory": mapped_category,
            "confidence": "HIGH" if matched_name else "MEDIUM",
            "decisionReason": "장소명 근거는 있으나 카카오 카테고리 기준 서비스 카테고리 변경 필요",
        }

    return {
        "suggestedAction": "MANUAL_REVIEW",
        "suggestedCategory": "",
        "confidence": "LOW",
        "decisionReason": "카카오 카테고리를 서비스 카테고리로 자동 매핑하기 어려움",
    }


def main() -> None:
    facilities = load_js_assignment(FACILITIES_JS, "FACILITIES_GEOJSON")["features"]
    seed_records = load_js_assignment(SEED_JS, "MANUAL_REVIEW_SEED")
    kakao_rows = read_csv(KAKAO_REFRESH_CSV)
    kakao_by_source_key = {row.get("sourceKey", ""): row for row in kakao_rows if row.get("sourceKey")}

    rows: list[dict[str, Any]] = []
    for feature in facilities:
        properties = feature.get("properties", {})
        key = manual_review_key(feature)
        seed = seed_records.get(key, {})
        evidence_action = str(seed.get("evidenceAction", "")).upper()
        coordinate_quality = str(seed.get("coordinateQuality", "")).upper()
        if coordinate_quality == "INTERNAL" or "CATEGORY" not in evidence_action:
            continue

        source_key = properties.get("sourceKey") or properties.get("sourceId", "")
        kakao_row = kakao_by_source_key.get(source_key, {})
        decision = classify(kakao_row, feature, seed)
        rows.append(
            {
                "key": key,
                "placeId": properties.get("placeId", ""),
                "sourceKey": source_key,
                "districtGu": properties.get("districtGu", ""),
                "name": properties.get("name", ""),
                "currentCategory": properties.get("dbCategory", ""),
                "currentCategoryLabel": properties.get("dbCategoryLabel", ""),
                "rawFacilityCategory": properties.get("rawFacilityCategory", ""),
                "publicFacilityType": properties.get("publicFacilityType", ""),
                "address": properties.get("address", ""),
                "kakaoPlaceName": kakao_row.get("kakao_place_name") or seed.get("kakaoPlaceName", ""),
                "kakaoCategory": kakao_row.get("kakao_category", ""),
                "kakaoDistanceM": kakao_row.get("kakao_distance_m") or seed.get("kakaoDistanceM", ""),
                "poiName": kakao_row.get("poi_name") or seed.get("poiName", ""),
                "poiCategoryLabel": kakao_row.get("poi_category_label", ""),
                "poiDistanceM": kakao_row.get("poi_distance_m") or seed.get("poiDistanceM", ""),
                "coordinateQuality": seed.get("coordinateQuality", ""),
                "evidenceAction": seed.get("evidenceAction", ""),
                **decision,
                "note": seed.get("note", ""),
            }
        )

    fieldnames = [
        "key",
        "placeId",
        "sourceKey",
        "districtGu",
        "name",
        "currentCategory",
        "currentCategoryLabel",
        "rawFacilityCategory",
        "publicFacilityType",
        "address",
        "kakaoPlaceName",
        "kakaoCategory",
        "kakaoDistanceM",
        "poiName",
        "poiCategoryLabel",
        "poiDistanceM",
        "coordinateQuality",
        "evidenceAction",
        "suggestedAction",
        "suggestedCategory",
        "confidence",
        "decisionReason",
        "note",
    ]
    write_csv(OUT_CSV, rows, fieldnames)

    summary = {
        "total": len(rows),
        "byAction": {},
        "byDistrict": {},
        "output": str(OUT_CSV),
    }
    for row in rows:
        summary["byAction"][row["suggestedAction"]] = summary["byAction"].get(row["suggestedAction"], 0) + 1
        district = row["districtGu"] or "구 미기재"
        summary["byDistrict"][district] = summary["byDistrict"].get(district, 0) + 1
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
