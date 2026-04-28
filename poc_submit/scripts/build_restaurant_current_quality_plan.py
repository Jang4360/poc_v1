from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


POC_ROOT = Path(__file__).resolve().parents[1]
FINAL = POC_ROOT / "data" / "final" / "facilities" / "adopted_places_with_accessibility_final.csv"
CROSS = POC_ROOT / "data" / "reports" / "facility_validation" / "facility_cross_validation_all.csv"
REPORT_DIR = POC_ROOT / "data" / "reports" / "facility_validation"
OUT_CSV = REPORT_DIR / "restaurant_current_quality_plan.csv"
OUT_SUMMARY = REPORT_DIR / "restaurant_current_quality_plan_summary.json"

STRUCTURAL_TERMS = [
    "근린생활시설",
    "제2종근린생활시설",
    "프라자",
    "메디컬센터",
    "센터",
    "빌딩",
    "상가",
    "타워",
    "오피스텔",
    "스퀘어",
]

NON_RESTAURANT_TERMS = [
    "조명",
    "주유소",
    "충전소",
    "병원",
    "의원",
    "약국",
    "도서",
    "은행",
    "공사",
    "전력",
    "복지",
]

FOOD_HINT_TERMS = [
    "한우",
    "회센터",
    "활어",
    "식당",
    "밥",
    "카페",
    "커피",
    "횟집",
    "곰장어",
    "돼지국밥",
    "곱창",
    "국밥",
    "고기",
    "푸드",
    "브레드",
    "베이커리",
    "레스토랑",
    "분식",
]

BAD_EXACT_NAMES = {"근린생활시설", "일반음식점", "휴게음식점·제과점"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def find_term(text: str, terms: list[str]) -> str:
    for term in terms:
        if term in text:
            return term
    return ""


def is_address_like(name: str) -> bool:
    return bool(
        re.search(r"[가-힣]+동\s*\d", name)
        or re.search(r"\d+-\d+", name)
        or "번지" in name
        or "제2종근린생활시설" in name
    )


def looks_food_name(name: str) -> bool:
    return bool(find_term(name, FOOD_HINT_TERMS))


def external_food_candidate(cross: dict[str, str]) -> tuple[str, str, str]:
    candidates = [
        ("kakao", cross.get("kakao_place_name", ""), cross.get("kakao_category", "")),
        ("poi", cross.get("poi_name", ""), cross.get("poi_category_label", "")),
    ]
    for source, candidate_name, category in candidates:
        if not candidate_name:
            continue
        if any(token in category for token in ["음식", "카페", "간식", "제과", "커피"]):
            return source, candidate_name, category
    return "", "", ""


def classify(row: dict[str, str], cross: dict[str, str]) -> tuple[str, str, str, str, str]:
    name = row["name"].strip()
    structural = find_term(name, STRUCTURAL_TERMS)
    non_restaurant = find_term(name, NON_RESTAURANT_TERMS)
    address_like = is_address_like(name)
    exact_bad = name in BAD_EXACT_NAMES
    food_hint = looks_food_name(name)
    external_source, external_name, external_category = external_food_candidate(cross)

    issue_parts: list[str] = []
    if exact_bad:
        issue_parts.append("상호가 아니라 업종/시설 유형명")
    if address_like:
        issue_parts.append("주소/지번/근린생활시설형 이름")
    if structural and not food_hint:
        issue_parts.append(f"건물/구조물명 의심: {structural}")
    if non_restaurant:
        issue_parts.append(f"음식점 외 시설명 의심: {non_restaurant}")

    if not issue_parts:
        return "KEEP", "", "", "", "현재 이름 유지 가능"

    if external_name and external_name != name:
        return "RENAME_CANDIDATE", external_name, external_source, external_category, " / ".join(issue_parts)

    if non_restaurant or exact_bad or address_like or (structural and not food_hint):
        return "REMOVE_OR_MANUAL", "", "", "", " / ".join(issue_parts)

    return "MANUAL_REVIEW", "", "", "", " / ".join(issue_parts)


def main() -> None:
    restaurants = [row for row in read_csv(FINAL) if row["dbCategory"] == "RESTAURANT"]
    cross_rows = {row["place_key"]: row for row in read_csv(CROSS)}

    out: list[dict[str, Any]] = []
    for row in restaurants:
        cross = cross_rows.get(row["sourceKey"], {})
        action, suggested_name, suggestion_source, suggestion_category, reason = classify(row, cross)
        out.append(
            {
                "placeId": row["placeId"],
                "sourceKey": row["sourceKey"],
                "name": row["name"],
                "districtGu": row["districtGu"],
                "address": row["address"],
                "rawFacilityType": row["rawFacilityType"],
                "accessibilityLabels": row["accessibilityLabels"],
                "recommendedAction": action,
                "suggestedName": suggested_name,
                "suggestionSource": suggestion_source,
                "suggestionCategory": suggestion_category,
                "reason": reason,
                "kakaoPlaceName": cross.get("kakao_place_name", ""),
                "kakaoCategory": cross.get("kakao_category", ""),
                "kakaoDistanceM": cross.get("kakao_distance_m", ""),
                "poiName": cross.get("poi_name", ""),
                "poiCategory": cross.get("poi_category_label", ""),
                "poiDistanceM": cross.get("poi_distance_m", ""),
            }
        )

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    fieldnames = list(out[0].keys()) if out else []
    write_csv(OUT_CSV, out, fieldnames)
    summary = {
        "totalRestaurants": len(restaurants),
        "byRecommendedAction": dict(Counter(row["recommendedAction"] for row in out)),
        "candidateCount": sum(1 for row in out if row["recommendedAction"] != "KEEP"),
        "outputs": {"csv": str(OUT_CSV)},
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for action in ["RENAME_CANDIDATE", "REMOVE_OR_MANUAL", "MANUAL_REVIEW"]:
        subset = [row for row in out if row["recommendedAction"] == action]
        print(f"\n[{action}] {len(subset)}")
        for row in subset[:80]:
            suggestion = f" -> {row['suggestedName']}" if row["suggestedName"] else ""
            print(f"- {row['placeId']} {row['name']}{suggestion} | {row['reason']}")


if __name__ == "__main__":
    main()
