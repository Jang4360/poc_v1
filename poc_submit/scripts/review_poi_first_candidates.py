from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path


POC_ROOT = Path(__file__).resolve().parents[1]
VALIDATION_DIR = POC_ROOT / "data" / "reports" / "facility_validation"
INPUT_CSV = VALIDATION_DIR / "facility_validation_poi_first_review_159.csv"
OUTPUT_CSV = VALIDATION_DIR / "facility_validation_poi_first_review_159_reviewed.csv"
SUMMARY_CSV = VALIDATION_DIR / "facility_validation_poi_first_review_159_reviewed_summary.csv"


PUBLIC_AREA_KEYWORDS = [
    "공원",
    "생태공원",
    "체육공원",
    "해수욕장",
    "해변",
    "산책로",
    "둘레길",
    "등산로",
    "약수터",
    "방파제",
    "항",
    "물양장",
    "시장",
    "지하도상가",
    "지하상가",
    "광장",
    "주차장",
    "마을",
    "유원지",
    "체육시설",
    "생활체육관",
    "수원지",
    "저수지",
    "천",
    "교",
    "역",
]

PUBLIC_BUILDING_KEYWORDS = [
    "도서관",
    "행정복지센터",
    "주민센터",
    "구청",
    "보건소",
    "우체국",
    "세관",
    "지구대",
    "파출소",
    "소방",
    "보훈회관",
    "문화원",
    "복지관",
]

INTERNAL_PRIVATE_KEYWORDS = [
    "주유소",
    "충전소",
    "병원",
    "의원",
    "대학교",
    "학교",
    "아파트",
    "빌딩",
    "교회",
    "성당",
    "사찰",
    "호텔",
    "금고",
]

GENERIC_FOOD_NAMES = ["일반음식점", "휴게음식점", "제과점"]


def has_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def number(value: str, default: float = 999999.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def is_poi_public_toilet(row: dict[str, str]) -> bool:
    return "전국공중화장실" in row.get("poi_category_label", "") or row.get("poi_name") == "공중화장실"


def is_food_poi(row: dict[str, str]) -> bool:
    text = row.get("poi_category_label", "")
    return any(keyword in text for keyword in ["음식점업", "카페", "비알코올음료점업", "제과", "피자", "김밥"])


def is_area_like(row: dict[str, str]) -> bool:
    text = f"{row.get('place_name', '')} {row.get('address', '')} {row.get('poi_category_label', '')}"
    return has_any(text, PUBLIC_AREA_KEYWORDS)


def is_public_building_like(row: dict[str, str]) -> bool:
    text = f"{row.get('place_name', '')} {row.get('address', '')}"
    return has_any(text, PUBLIC_BUILDING_KEYWORDS)


def is_internal_private_like(row: dict[str, str]) -> bool:
    text = f"{row.get('place_name', '')} {row.get('address', '')} {row.get('poi_category_label', '')}"
    return has_any(text, INTERNAL_PRIVATE_KEYWORDS)


def normalize_name(value: str) -> str:
    value = re.sub(r"주식회사|㈜|\(주\)|（주）", "", value or "")
    value = re.sub(r"[\s·ㆍ\-_.,/\\()\[\]{}]+", "", value)
    return value


MANUAL_SEARCH_OVERRIDES = {
    "barrier_free_facility:9421": {
        "review_decision": "RENAME_CANDIDATE",
        "review_confidence": "HIGH",
        "review_reason": "카카오 검색에서 같은 주소의 '스타벅스 명지강변DT점' 확인",
        "next_action": "장소명을 '스타벅스 명지강변DT점'으로 보정 후보 처리",
    },
    "barrier_free_facility:6211": {
        "review_decision": "RENAME_CANDIDATE",
        "review_confidence": "HIGH",
        "review_reason": "카카오 검색에서 같은 주소의 '스타벅스 부산만덕DT점' 확인",
        "next_action": "장소명을 '스타벅스 부산만덕DT점'으로 보정 후보 처리",
    },
    "barrier_free_facility:9649": {
        "review_decision": "EXCLUDE_CANDIDATE",
        "review_confidence": "MEDIUM",
        "review_reason": "카카오 검색 결과가 없고 주변 POI도 다른 음식점으로 잡혀 원본 장소 확인 불가",
        "next_action": "제외 후보로 반영",
    },
    "barrier_free_facility:9206": {
        "review_decision": "EXCLUDE_CANDIDATE",
        "review_confidence": "MEDIUM",
        "review_reason": "카카오 검색 결과가 없고 주변 POI가 버스정류장으로 잡혀 음식·카페 근거 부족",
        "next_action": "제외 후보로 반영",
    },
    "barrier_free_facility:9205": {
        "review_decision": "EXCLUDE_CANDIDATE",
        "review_confidence": "MEDIUM",
        "review_reason": "카카오 검색 결과가 없고 주변 POI가 식음료 목적지로 보기 어려움",
        "next_action": "제외 후보로 반영",
    },
    "barrier_free_facility:12835": {
        "review_decision": "EXCLUDE_CANDIDATE",
        "review_confidence": "HIGH",
        "review_reason": "카카오 검색에서 같은 주소의 대한이씨아이가 확인되지만 시공업체로, 음식·카페 카테고리와 불일치",
        "next_action": "제외 후보로 반영",
    },
    "barrier_free_facility:3314": {
        "review_decision": "EXCLUDE_CANDIDATE",
        "review_confidence": "MEDIUM",
        "review_reason": "카카오 검색에서 같은 주소의 착한소를 확인하지 못했고, 검색 결과는 다른 지역 음식점임",
        "next_action": "제외 후보로 반영",
    },
    "barrier_free_facility:9330": {
        "review_decision": "EXCLUDE_CANDIDATE",
        "review_confidence": "MEDIUM",
        "review_reason": "카카오 검색 결과가 없고 주변 POI가 공장으로 잡혀 행정·공공기관 목적지 근거 부족",
        "next_action": "제외 후보로 반영",
    },
}


def review(row: dict[str, str]) -> dict[str, str]:
    if row.get("place_key") in MANUAL_SEARCH_OVERRIDES:
        return MANUAL_SEARCH_OVERRIDES[row["place_key"]]

    category = row["ui_category"]
    name = row["place_name"]
    poi_status = row["poi_match_status"]
    poi_distance = number(row.get("poi_distance_m", ""))
    poi_name = row.get("poi_name", "")
    poi_category = row.get("poi_category_label", "")
    auto_decision = row.get("auto_decision", "")

    if category == "음식·카페":
        if any(keyword in name for keyword in GENERIC_FOOD_NAMES):
            if is_food_poi(row) and poi_distance <= 100 and poi_name:
                return {
                    "review_decision": "RENAME_CANDIDATE",
                    "review_confidence": "MEDIUM",
                    "review_reason": f"원본명은 업종명뿐이지만 {poi_distance:.1f}m 근처 음식점 POI '{poi_name}'가 있어 이름 보정 후보",
                    "next_action": "POI명으로 보정할지 원본과 대조",
                }
            return {
                "review_decision": "EXCLUDE_CANDIDATE",
                "review_confidence": "HIGH",
                "review_reason": "원본명이 업종명뿐이고 주변 POI도 음식점 근거가 약해 서비스 장소로 노출하기 어려움",
                "next_action": "제외 후보로 반영",
            }
        if is_food_poi(row) and normalize_name(name) == normalize_name(poi_name):
            return {
                "review_decision": "KEEP",
                "review_confidence": "MEDIUM",
                "review_reason": "음식점 POI와 이름이 일치",
                "next_action": "유지",
            }
        return {
            "review_decision": "REVIEW",
            "review_confidence": "MEDIUM",
            "review_reason": "음식·카페 원본과 POI명 또는 업종이 충분히 일치하지 않음",
            "next_action": "카카오맵 검색으로 상호 확인",
        }

    if category == "화장실":
        if is_poi_public_toilet(row):
            return {
                "review_decision": "KEEP",
                "review_confidence": "HIGH" if poi_distance <= 100 else "MEDIUM",
                "review_reason": f"{poi_distance:.1f}m 근처에 전국공중화장실 POI가 있음",
                "next_action": "유지",
            }
        if is_area_like(row):
            return {
                "review_decision": "KEEP_AREA_TOILET",
                "review_confidence": "MEDIUM",
                "review_reason": "공원/시장/해변/산책로/체육시설 등 구역형 공중화장실로 POI 단일점 매칭이 약할 수 있음",
                "next_action": "유지하되 지도에서 대표 위치만 확인",
            }
        if is_public_building_like(row):
            return {
                "review_decision": "REVIEW_PUBLIC_BUILDING_TOILET",
                "review_confidence": "MEDIUM",
                "review_reason": "공공시설 내부 화장실로 보이며 서비스에 노출할지 기준 확인 필요",
                "next_action": "공공시설 내부 화장실 유지 여부 결정",
            }
        if auto_decision == "INTERNAL_TOILET_POLICY_REVIEW" or is_internal_private_like(row):
            return {
                "review_decision": "EXCLUDE_CANDIDATE",
                "review_confidence": "HIGH",
                "review_reason": "주유소/병원/학교/아파트/종교시설 등 내부 화장실 가능성이 높고 공중화장실 POI 근거가 약함",
                "next_action": "내부 화장실 제외 기준이면 제외",
            }
        if poi_status == "NO_MATCH":
            return {
                "review_decision": "REVIEW",
                "review_confidence": "LOW",
                "review_reason": "300m 이내 POI 후보가 없어 위치 검증 필요",
                "next_action": "지도/카카오맵 검색으로 확인",
            }
        return {
            "review_decision": "REVIEW",
            "review_confidence": "LOW",
            "review_reason": "화장실 POI 또는 공공 구역 단서가 부족함",
            "next_action": "지도/카카오맵 검색으로 확인",
        }

    if category == "전동보장구 충전소":
        if "휠체어급속충전기" in poi_name or "휠체어급속충전기" in poi_category:
            return {
                "review_decision": "KEEP",
                "review_confidence": "HIGH",
                "review_reason": "POI가 휠체어급속충전기로 확인됨",
                "next_action": "유지",
            }
        return {
            "review_decision": "KEEP_LOCATION_REVIEW",
            "review_confidence": "MEDIUM",
            "review_reason": "충전소 목적지는 유지하되 POI가 충전기 자체가 아니라 주변 시설로 잡힘",
            "next_action": "좌표 대표점 확인",
        }

    if category == "관광지":
        if is_area_like(row) or "관광" in poi_category:
            return {
                "review_decision": "KEEP_AREA_PLACE",
                "review_confidence": "MEDIUM",
                "review_reason": "관광지/구역형 장소라 대표 좌표 매칭으로 보는 것이 적절함",
                "next_action": "유지",
            }
        return {
            "review_decision": "REVIEW",
            "review_confidence": "LOW",
            "review_reason": "관광지 POI 맥락이 약함",
            "next_action": "지도 확인",
        }

    if category == "숙박":
        if "숙박" in poi_category or "호텔" in poi_category or normalize_name(name) == normalize_name(poi_name):
            return {
                "review_decision": "KEEP",
                "review_confidence": "MEDIUM",
                "review_reason": "숙박 POI 또는 이름 일치 근거가 있음",
                "next_action": "유지",
            }
        return {
            "review_decision": "REVIEW",
            "review_confidence": "MEDIUM",
            "review_reason": "숙박 POI와 충분히 일치하지 않음",
            "next_action": "카카오맵 검색 확인",
        }

    if category == "행정·공공기관":
        if normalize_name(name) == normalize_name(poi_name) or is_public_building_like(row):
            return {
                "review_decision": "KEEP",
                "review_confidence": "MEDIUM",
                "review_reason": "공공기관명 또는 공공시설 단서가 있음",
                "next_action": "유지",
            }
        return {
            "review_decision": "REVIEW",
            "review_confidence": "MEDIUM",
            "review_reason": "공공기관 POI 매칭이 약함",
            "next_action": "지도 확인",
        }

    return {
        "review_decision": "REVIEW",
        "review_confidence": "LOW",
        "review_reason": "자동 판정 규칙 없음",
        "next_action": "수동 확인",
    }


def main() -> None:
    with INPUT_CSV.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))

    reviewed = [{**row, **review(row)} for row in rows]
    fieldnames = [*rows[0].keys(), "review_decision", "review_confidence", "review_reason", "next_action"]

    with OUTPUT_CSV.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(reviewed)

    summary_rows = []
    for group_name, key in [
        ("decision", "review_decision"),
        ("confidence", "review_confidence"),
        ("category_decision", "ui_category|review_decision"),
    ]:
        if "|" in key:
            left, right = key.split("|")
            counter = Counter(f"{row[left]} / {row[right]}" for row in reviewed)
        else:
            counter = Counter(row[key] for row in reviewed)
        for name, count in sorted(counter.items(), key=lambda item: (-item[1], item[0])):
            summary_rows.append({"group": group_name, "name": name, "count": str(count)})

    with SUMMARY_CSV.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["group", "name", "count"])
        writer.writeheader()
        writer.writerows(summary_rows)

    print("reviewed", len(reviewed))
    for decision, count in sorted(Counter(row["review_decision"] for row in reviewed).items()):
        print(decision, count)


if __name__ == "__main__":
    main()
