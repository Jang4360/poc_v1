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
OUT_CSV = REPORT_DIR / "healthcare_current_quality_plan.csv"
OUT_CANDIDATES = REPORT_DIR / "healthcare_current_quality_candidates.csv"
OUT_SUMMARY = REPORT_DIR / "healthcare_current_quality_plan_summary.json"

HEALTHCARE_HINT_TERMS = [
    "병원",
    "요양병원",
    "치과병원",
    "한방병원",
    "의원",
    "치과",
    "한의원",
    "보건소",
    "의료원",
    "클리닉",
    "산부인과",
    "내과",
    "외과",
    "정형외과",
    "신경외과",
    "흉부외과",
    "이비인후과",
    "안과",
    "피부과",
    "비뇨",
    "소아청소년과",
    "정신건강",
    "재활의학",
    "마취통증",
    "영상의학",
    "가정의학",
    "성형외과",
    "신경과",
    "통증",
    "검진센터",
    "건강검진",
    "요양원",
    "정신요양원",
    "산후조리원",
    "보건지소",
    "응급의료",
    "의학원",
    "건강관리",
]

WEAK_HEALTHCARE_TERMS = [
    "메디",
    "메디컬",
    "메디칼",
    "메디컬센터",
    "메디칼센터",
    "메디타운",
    "메디타워",
    "메디팰리스",
    "메디플러스",
    "의료센터",
    "의료재단",
    "건강센터",
    "헬스케어",
]

STRUCTURAL_TERMS = [
    "빌딩",
    "프라자",
    "상가",
    "타워",
    "오피스텔",
    "근린생활시설",
    "센터",
    "메디컬센터",
]

NON_HEALTHCARE_TERMS = [
    "약국",
    "주차장",
    "학원",
    "어학원",
    "의류",
    "비비안",
    "음식점",
    "식당",
    "카페",
    "교회",
    "주유소",
    "충전소",
    "은행",
    "관리사무소",
    "부동산",
    "버스정류장",
    "ATM",
    "동물병원",
    "동물의료",
]

GENERIC_EXACT_NAMES = {
    "병원",
    "의원",
    "치과의원",
    "한의원",
    "보건소",
    "종합병원",
    "의원·치과의원·한의원·조산소·산후조리원",
    "병원·치과병원·한방병원·정신병원·요양병원",
}

HEALTHCARE_CATEGORY_TERMS = [
    "의료",
    "건강",
    "병원",
    "의원",
    "치과",
    "한의",
    "보건",
    "요양",
    "산후조리",
]

BAD_EXTERNAL_CATEGORY_TERMS = [
    "편의점",
    "주차장",
    "버스정류장",
    "약국",
    "ATM",
    "은행",
    "학원",
    "부동산",
    "빌딩",
    "교통",
    "소매",
    "음식점",
    "종교",
    "전기차",
    "관리,운영",
    "동물병원",
    "동물의료",
]


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


def distance_ok(value: str, max_m: float = 60) -> bool:
    distance = parse_float(value)
    return distance is not None and distance <= max_m


def clean_candidate_name(name: str) -> str:
    value = (name or "").strip()
    value = re.sub(r"^\([^)]*\)\s*", "", value).strip()
    if "/" in value:
        parts = [part.strip() for part in value.split("/") if part.strip()]
        for part in parts:
            if has_any(part, HEALTHCARE_HINT_TERMS):
                return part
        for part in parts:
            if has_any(part, WEAK_HEALTHCARE_TERMS):
                return part
    return value


def looks_healthcare_name(name: str) -> bool:
    if name in GENERIC_EXACT_NAMES:
        return False
    return has_any(name, HEALTHCARE_HINT_TERMS)


def looks_weak_healthcare_name(name: str) -> bool:
    if looks_healthcare_name(name):
        return True
    return has_any(name, WEAK_HEALTHCARE_TERMS)


def healthcare_external_candidate(cross: dict[str, str]) -> tuple[str, str, str, str]:
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
        if not candidate_name or not distance_ok(distance):
            continue
        evidence_text = f"{candidate_name} {category}"
        if has_any(evidence_text, BAD_EXTERNAL_CATEGORY_TERMS):
            continue
        if has_any(category, HEALTHCARE_CATEGORY_TERMS) and has_any(candidate_name, HEALTHCARE_HINT_TERMS + WEAK_HEALTHCARE_TERMS):
            return source, candidate_name, category, distance
    return "", "", "", ""


def non_healthcare_external_evidence(cross: dict[str, str]) -> tuple[str, str, str, str]:
    candidates = [
        ("kakao", cross.get("kakao_place_name", ""), cross.get("kakao_category", ""), cross.get("kakao_distance_m", "")),
        ("poi", cross.get("poi_name", ""), cross.get("poi_category_label", ""), cross.get("poi_distance_m", "")),
    ]
    for source, candidate_name, category, distance in candidates:
        if not candidate_name or not distance_ok(distance):
            continue
        evidence_text = f"{candidate_name} {category}"
        if has_any(evidence_text, BAD_EXTERNAL_CATEGORY_TERMS) and not has_any(category, HEALTHCARE_CATEGORY_TERMS):
            return source, candidate_name, category, distance
    return "", "", "", ""


def classify(row: dict[str, str], cross: dict[str, str]) -> tuple[str, str, str, str, str, str]:
    name = row["name"].strip()
    raw_type = row.get("rawFacilityType", "")
    structural_terms = find_terms(name, STRUCTURAL_TERMS)
    non_healthcare_terms = find_terms(name, NON_HEALTHCARE_TERMS)
    healthcare_source, healthcare_name, healthcare_category, healthcare_distance = healthcare_external_candidate(cross)
    non_source, non_name, non_category, non_distance = non_healthcare_external_evidence(cross)

    issues: list[str] = []
    if name in GENERIC_EXACT_NAMES:
        issues.append("시설 유형명만 남음")
    if structural_terms and not looks_healthcare_name(name):
        issues.append(f"건물/구조물명 의심: {'|'.join(structural_terms)}")
    if non_healthcare_terms and not looks_healthcare_name(name):
        issues.append(f"의료 목적지 외 명칭 의심: {'|'.join(non_healthcare_terms)}")
    if raw_type in {"의원·치과의원·한의원·조산소·산후조리원", "병원·치과병원·한방병원·정신병원·요양병원", "종합병원", "보건소"} and not looks_healthcare_name(name):
        issues.append("원본은 의료시설이나 표시명이 의료 목적지를 설명하지 못함")
    if has_any(name, WEAK_HEALTHCARE_TERMS) and not looks_healthcare_name(name):
        issues.append("메디컬/센터 계열 포괄명")

    if not issues:
        return "KEEP", "", "", "", "", "현재 이름 유지 가능"

    if looks_weak_healthcare_name(name):
        return "KEEP", "", "", "", "", "의료 포괄명은 수동 검토 정책에 따라 유지"

    if healthcare_name and healthcare_name != name:
        return "RENAME_CANDIDATE", healthcare_name, healthcare_source, healthcare_category, healthcare_distance, " / ".join(issues)

    if non_name and (non_healthcare_terms or name in GENERIC_EXACT_NAMES):
        return "EXCLUDE_CANDIDATE", "", non_source, non_category, non_distance, f"{' / '.join(issues)} / 외부 근거: {non_name}"

    if non_name and structural_terms and not looks_weak_healthcare_name(name):
        return "MANUAL_REVIEW", "", non_source, non_category, non_distance, f"{' / '.join(issues)} / 외부 근거: {non_name}"

    return "MANUAL_REVIEW", "", healthcare_source or non_source, healthcare_category or non_category, healthcare_distance or non_distance, " / ".join(issues)


def main() -> None:
    healthcare_rows = [row for row in read_csv(FINAL) if row["dbCategory"] == "HEALTHCARE"]
    cross_rows = {row["place_key"]: row for row in read_csv(CROSS)}

    out: list[dict[str, Any]] = []
    for row in healthcare_rows:
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
        "totalHealthcare": len(healthcare_rows),
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
