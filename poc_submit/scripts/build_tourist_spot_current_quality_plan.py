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
OUT_CSV = REPORT_DIR / "tourist_spot_current_quality_plan.csv"
OUT_CANDIDATES = REPORT_DIR / "tourist_spot_current_quality_candidates.csv"
OUT_SUMMARY = REPORT_DIR / "tourist_spot_current_quality_plan_summary.json"

TOURIST_HINT_TERMS = [
    "해수욕장",
    "온천",
    "공원",
    "거리",
    "특구",
    "문화원",
    "문화회관",
    "미술관",
    "박물관",
    "도서관",
    "전시관",
    "시장",
    "지하도상가",
    "수목원",
    "전망대",
    "기념관",
    "아쿠아리움",
    "케이블카",
    "블루라인",
    "해상케이블카",
    "영화의 전당",
    "영화의전당",
    "벡스코",
    "BEXCO",
    "APEC",
    "F1963",
    "테마거리",
    "스파랜드",
    "아이스링크",
    "아울렛",
    "백화점",
    "타워",
    "산책로",
    "숲길",
    "둘레길",
    "해맞이",
    "역사관",
    "예술마을",
    "수련관",
    "체험",
    "문화관",
    "요트",
]

TOURIST_CATEGORY_TERMS = [
    "여행",
    "관광",
    "명소",
    "문화",
    "예술",
    "박물관",
    "전시관",
    "미술관",
    "공원",
    "시장",
    "상가",
    "아울렛",
    "백화점",
    "도서관",
    "테마파크",
    "해수욕장",
    "전망대",
    "체험",
    "수목원",
]

BAD_EXTERNAL_CATEGORY_TERMS = [
    "음식점",
    "카페",
    "편의점",
    "은행",
    "부동산",
    "주차장",
    "버스정류장",
    "화장실",
    "전기차",
    "병원",
    "약국",
    "학원",
    "제조업",
    "정보통신",
]

MANUAL_DECISIONS = {
    "tourist_spot:81": ("EXCLUDE_CANDIDATE", "", "수동 검토: 광주요는 공식 관광 목록에 있으나 단일 매장명이고 관광 목적지 근거가 약해 제거"),
    "tourist_spot:183": ("KEEP", "", "수동 검토: 공원명 자체가 목적지이므로 외부 근거가 약해도 유지"),
    "tourist_spot:216": ("KEEP", "", "수동 검토: 시장명 자체가 목적지이므로 외부 근거가 약해도 유지"),
    "tourist_spot:232": ("KEEP", "", "수동 검토: 요트 투어 목적지로 유지"),
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def has_any(text: str, terms: list[str]) -> bool:
    return any(term in (text or "") for term in terms)


def parse_float(value: str) -> float | None:
    try:
        if value == "":
            return None
        return float(value)
    except ValueError:
        return None


def distance_ok(value: str, max_m: float = 100) -> bool:
    distance = parse_float(value)
    return distance is not None and distance <= max_m


def normalize_name(value: str) -> str:
    value = (value or "").strip()
    value = re.sub(r"\([^)]*\)", "", value)
    value = re.sub(r"\s+", "", value)
    value = value.replace("부산광역시", "").replace("부산", "")
    return value.lower()


def names_same_enough(a: str, b: str) -> bool:
    left = normalize_name(a)
    right = normalize_name(b)
    return left == right or left in right or right in left


def clean_candidate_name(name: str) -> str:
    value = (name or "").strip()
    value = re.sub(r"\s*입구$", "", value).strip()
    value = re.sub(r"\s*주차장$", "", value).strip()
    value = re.sub(r"\s*화장실$", "", value).strip()
    if "/" in value:
        parts = [part.strip() for part in value.split("/") if part.strip()]
        for part in parts:
            if has_any(part, TOURIST_HINT_TERMS):
                return part
    return value


def tourist_external_candidate(cross: dict[str, str]) -> tuple[str, str, str, str]:
    candidates = [
        ("kakao", cross.get("kakao_place_name", ""), cross.get("kakao_category", ""), cross.get("kakao_distance_m", "")),
        ("poi", cross.get("poi_name", ""), cross.get("poi_category_label", ""), cross.get("poi_distance_m", "")),
    ]
    for source, raw_name, category, distance in candidates:
        if not raw_name or not distance_ok(distance):
            continue
        name = clean_candidate_name(raw_name)
        evidence = f"{name} {category}"
        if has_any(evidence, BAD_EXTERNAL_CATEGORY_TERMS) and not has_any(evidence, TOURIST_CATEGORY_TERMS):
            continue
        if has_any(evidence, TOURIST_HINT_TERMS + TOURIST_CATEGORY_TERMS):
            return source, name, category, distance
    return "", "", "", ""


def non_tourist_external_evidence(cross: dict[str, str]) -> tuple[str, str, str, str]:
    candidates = [
        ("kakao", cross.get("kakao_place_name", ""), cross.get("kakao_category", ""), cross.get("kakao_distance_m", "")),
        ("poi", cross.get("poi_name", ""), cross.get("poi_category_label", ""), cross.get("poi_distance_m", "")),
    ]
    for source, name, category, distance in candidates:
        if not name or not distance_ok(distance):
            continue
        evidence = f"{name} {category}"
        if has_any(evidence, TOURIST_HINT_TERMS + TOURIST_CATEGORY_TERMS):
            continue
        if has_any(evidence, BAD_EXTERNAL_CATEGORY_TERMS):
            return source, name, category, distance
    return "", "", "", ""


def classify(row: dict[str, str], cross: dict[str, str]) -> tuple[str, str, str, str, str, str]:
    manual = MANUAL_DECISIONS.get(row["sourceKey"])
    if manual:
        action, suggested_name, reason = manual
        return action, suggested_name, "manual", "", "", reason

    return "KEEP", "", "", "", "", "공식 관광 원본 대표명 유지"


def main() -> None:
    tourist_rows = [row for row in read_csv(FINAL) if row["dbCategory"] == "TOURIST_SPOT"]
    cross_rows = {row["place_key"]: row for row in read_csv(CROSS)}

    out: list[dict[str, Any]] = []
    for row in tourist_rows:
        cross = cross_rows.get(row["sourceKey"], {})
        action, suggested_name, source, category, distance, reason = classify(row, cross)
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
                "suggestionSource": source,
                "suggestionCategory": category,
                "suggestionDistanceM": distance,
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
    candidates = [row for row in out if row["recommendedAction"] != "KEEP"]
    write_csv(OUT_CANDIDATES, candidates, fieldnames)
    summary = {
        "totalTouristSpot": len(tourist_rows),
        "byRecommendedAction": dict(Counter(row["recommendedAction"] for row in out)),
        "candidateCount": len(candidates),
        "outputs": {"csv": str(OUT_CSV), "candidates": str(OUT_CANDIDATES)},
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for action in ["RENAME_CANDIDATE", "EXCLUDE_CANDIDATE", "MANUAL_REVIEW"]:
        subset = [row for row in out if row["recommendedAction"] == action]
        print(f"\n[{action}] {len(subset)}")
        for row in subset[:140]:
            suggestion = f" -> {row['suggestedName']}" if row["suggestedName"] else ""
            print(f"- {row['placeId']} {row['name']}{suggestion} | {row['reason']}")


if __name__ == "__main__":
    main()
