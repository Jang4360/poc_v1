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
OUT_CSV = REPORT_DIR / "welfare_current_quality_plan.csv"
OUT_CANDIDATES = REPORT_DIR / "welfare_current_quality_candidates.csv"
OUT_SUMMARY = REPORT_DIR / "welfare_current_quality_plan_summary.json"

GENERIC_EXACT_NAMES = {
    "노인복지시설",
    "이외 사회복지시설",
    "장애인복지시설",
    "아동복지시설",
    "사회복지시설",
    "복지시설",
    "경로당",
}

WELFARE_HINT_TERMS = [
    "복지관",
    "복지회관",
    "복지센터",
    "복지시설",
    "복지",
    "종합사회복지관",
    "사회복지",
    "가족센터",
    "육아종합지원센터",
    "드림스타트",
    "장애인",
    "경로당",
    "경로회관",
    "노인정",
    "노인회",
    "노인",
    "노인복지",
    "노인요양",
    "요양원",
    "요양센터",
    "요양시설",
    "재가센터",
    "재가노인",
    "주간보호",
    "주야간보호",
    "데이케어",
    "실버",
    "지역아동센터",
    "아동센터",
    "아동복지",
    "어린이집",
    "아동",
    "모자원",
    "보육원",
    "공동생활",
    "자활센터",
    "재활주간보호",
    "직업재활",
    "보호센터",
    "치매",
    "언어치료",
    "심리",
    "케어",
]

STRUCTURAL_TERMS = [
    "근린생활시설",
    "빌딩",
    "프라자",
    "오피스텔",
    "상가",
    "타워",
    "아파트",
    "빌라",
]

NON_WELFARE_TERMS = [
    "주유소",
    "조명",
    "마트",
    "상회",
    "식당",
    "횟집",
    "호텔",
    "모텔",
    "교회",
    "성당",
    "수녀회",
    "교육원",
    "관리사무소",
    "충전소",
    "전기차",
    "주차장",
    "편의점",
    "GS25",
    "CU",
    "세븐일레븐",
]

SHELTER_TERMS = ["무더위쉼터", "한파쉼터", "무더위,한파쉼터", "쉼터"]
BAD_EXTERNAL_TERMS = ["충전소", "전기차", "주차장", "편의점", "GS25", "CU", "세븐일레븐"]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def has_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def find_terms(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if term in text]


def parse_float(value: str) -> float | None:
    try:
        if value == "":
            return None
        return float(value)
    except ValueError:
        return None


def clean_candidate_name(name: str) -> str:
    value = (name or "").strip()
    for prefix in ["무더위,한파쉼터", "무더위쉼터", "한파쉼터"]:
        if value.startswith(prefix):
            value = value[len(prefix) :].strip()
    value = re.sub(r"^\([^)]*\)\s*", "", value).strip()
    if "/" in value:
        parts = [part.strip() for part in value.split("/") if part.strip()]
        for part in parts:
            if has_any(part, WELFARE_HINT_TERMS) and not has_any(part, STRUCTURAL_TERMS):
                return part
    return value


def normalize_candidate_name(name: str, category: str) -> str:
    value = clean_candidate_name(name)
    if "경로당" in category and value and not has_any(value, ["경로당", "노인정", "노인회", "경로회관"]):
        value = f"{value}경로당"
    return value


def parenthetical_welfare_name(name: str) -> str:
    for match in re.finditer(r"\(([^)]+)\)", name):
        candidate = match.group(1).strip()
        if candidate and has_any(candidate, WELFARE_HINT_TERMS):
            return candidate
    return ""


def looks_welfare_name(name: str) -> bool:
    if name in GENERIC_EXACT_NAMES:
        return False
    return has_any(name, WELFARE_HINT_TERMS)


def candidate_distance_ok(value: str) -> bool:
    distance = parse_float(value)
    return distance is not None and distance <= 50


def welfare_external_candidate(cross: dict[str, str]) -> tuple[str, str, str, str]:
    candidates = [
        (
            "kakao",
            normalize_candidate_name(cross.get("kakao_place_name", ""), cross.get("kakao_category", "")),
            cross.get("kakao_category", ""),
            cross.get("kakao_distance_m", ""),
        ),
        (
            "poi",
            normalize_candidate_name(cross.get("poi_name", ""), cross.get("poi_category_label", "")),
            cross.get("poi_category_label", ""),
            cross.get("poi_distance_m", ""),
        ),
    ]
    for source, candidate_name, category, distance in candidates:
        if not candidate_name or not candidate_distance_ok(distance):
            continue
        evidence_text = f"{candidate_name} {category}"
        if has_any(evidence_text, BAD_EXTERNAL_TERMS):
            continue
        if has_any(evidence_text, WELFARE_HINT_TERMS):
            return source, candidate_name, category, distance
    return "", "", "", ""


def public_office_external_candidate(cross: dict[str, str]) -> tuple[str, str, str, str]:
    candidates = [
        (
            "kakao",
            clean_candidate_name(cross.get("kakao_place_name", "")),
            cross.get("kakao_category", ""),
            cross.get("kakao_distance_m", ""),
        ),
        (
            "poi",
            clean_candidate_name(cross.get("poi_name", "")),
            cross.get("poi_category_label", ""),
            cross.get("poi_distance_m", ""),
        ),
    ]
    for source, candidate_name, category, distance in candidates:
        if not candidate_name or not candidate_distance_ok(distance):
            continue
        evidence_text = f"{candidate_name} {category}"
        if has_any(evidence_text, ["행정복지센터", "주민센터", "지방행정기관"]):
            return source, candidate_name, category, distance
    return "", "", "", ""


def non_welfare_external_evidence(cross: dict[str, str]) -> tuple[str, str, str, str]:
    candidates = [
        ("kakao", cross.get("kakao_place_name", ""), cross.get("kakao_category", ""), cross.get("kakao_distance_m", "")),
        ("poi", cross.get("poi_name", ""), cross.get("poi_category_label", ""), cross.get("poi_distance_m", "")),
    ]
    for source, candidate_name, category, distance in candidates:
        if not candidate_name or not candidate_distance_ok(distance):
            continue
        evidence_text = f"{candidate_name} {category}"
        if has_any(evidence_text, NON_WELFARE_TERMS) and not has_any(evidence_text, WELFARE_HINT_TERMS):
            return source, candidate_name, category, distance
    return "", "", "", ""


def classify(row: dict[str, str], cross: dict[str, str]) -> tuple[str, str, str, str, str, str]:
    name = row["name"].strip()
    raw_type = row.get("rawFacilityType", "")
    welfare_source, welfare_name, welfare_category, welfare_distance = welfare_external_candidate(cross)
    public_source, public_name, public_category, public_distance = public_office_external_candidate(cross)
    non_source, non_name, non_category, non_distance = non_welfare_external_evidence(cross)
    parenthetical = parenthetical_welfare_name(name)

    issues: list[str] = []
    structural_terms = find_terms(name, STRUCTURAL_TERMS)
    non_welfare_terms = find_terms(name, NON_WELFARE_TERMS)
    shelter_terms = find_terms(name, SHELTER_TERMS)

    if name in GENERIC_EXACT_NAMES:
        issues.append("시설 유형명만 남음")
    if structural_terms and not looks_welfare_name(name):
        issues.append(f"건물/구조물명 의심: {'|'.join(structural_terms)}")
    if non_welfare_terms and not looks_welfare_name(name):
        issues.append(f"복지 목적지 외 명칭 의심: {'|'.join(non_welfare_terms)}")
    if shelter_terms and not looks_welfare_name(name):
        issues.append(f"쉼터 단독 명칭 의심: {'|'.join(shelter_terms)}")
    if "마을회관" in name and not looks_welfare_name(name):
        issues.append("마을회관 단독 명칭")
    if raw_type in {"노인복지시설", "이외 사회복지시설", "아동복지시설", "장애인복지시설"} and not looks_welfare_name(name):
        issues.append("원본은 복지시설이나 표시명이 복지 목적지를 설명하지 못함")

    if not issues:
        return "KEEP", "", "", "", "", "현재 이름 유지 가능"

    if public_name and ("주민센터" in name or "행정복지센터" in public_name):
        return "RECATEGORY_PUBLIC_OFFICE", public_name, public_source, public_category, public_distance, "WELFARE가 아니라 공공기관 성격"

    if parenthetical:
        return "RENAME_CANDIDATE", parenthetical, "name_parentheses", "", "", " / ".join(issues)

    if welfare_name and welfare_name != name:
        if "마을회관" in name and "마을회관" in welfare_name and not has_any(welfare_name, ["경로당", "경로회관", "복지"]):
            return "MANUAL_REVIEW", "", welfare_source, welfare_category, welfare_distance, " / ".join(issues)
        return "RENAME_CANDIDATE", welfare_name, welfare_source, welfare_category, welfare_distance, " / ".join(issues)

    if non_name and (non_welfare_terms or name in GENERIC_EXACT_NAMES):
        reason = " / ".join(issues)
        return "EXCLUDE_CANDIDATE", "", non_source, non_category, non_distance, f"{reason} / 외부 근거: {non_name}"

    if structural_terms or non_welfare_terms or "마을회관" in name or name in GENERIC_EXACT_NAMES:
        return "MANUAL_REVIEW", "", welfare_source or non_source, welfare_category or non_category, welfare_distance or non_distance, " / ".join(issues)

    return "KEEP", "", "", "", "", "현재 이름 유지 가능"


def main() -> None:
    welfare_rows = [row for row in read_csv(FINAL) if row["dbCategory"] == "WELFARE"]
    cross_rows = {row["place_key"]: row for row in read_csv(CROSS)}

    out: list[dict[str, Any]] = []
    for row in welfare_rows:
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
        "totalWelfare": len(welfare_rows),
        "byRecommendedAction": dict(Counter(row["recommendedAction"] for row in out)),
        "candidateCount": len(candidates),
        "outputs": {"csv": str(OUT_CSV), "candidates": str(OUT_CANDIDATES)},
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for action in ["RENAME_CANDIDATE", "RECATEGORY_PUBLIC_OFFICE", "EXCLUDE_CANDIDATE", "MANUAL_REVIEW"]:
        subset = [row for row in out if row["recommendedAction"] == action]
        print(f"\n[{action}] {len(subset)}")
        for row in subset[:120]:
            suggestion = f" -> {row['suggestedName']}" if row["suggestedName"] else ""
            print(f"- {row['placeId']} {row['name']}{suggestion} | {row['reason']}")


if __name__ == "__main__":
    main()
