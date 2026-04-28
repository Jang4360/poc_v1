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
OUT_CSV = REPORT_DIR / "public_office_current_quality_plan.csv"
OUT_CANDIDATES = REPORT_DIR / "public_office_current_quality_candidates.csv"
OUT_SUMMARY = REPORT_DIR / "public_office_current_quality_plan_summary.json"

PUBLIC_HINT_TERMS = [
    "주민센터",
    "행정복지센터",
    "동사무소",
    "주민자치센터",
    "구청",
    "시청",
    "군청",
    "세무서",
    "경찰서",
    "파출소",
    "지구대",
    "치안센터",
    "경찰청",
    "해양경찰",
    "소방서",
    "소방본부",
    "119",
    "안전센터",
    "우체국",
    "우편취급국",
    "국토관리청",
    "관리청",
    "수산청",
    "병무청",
    "국세청",
    "세관",
    "검찰청",
    "선거관리위원회",
    "국가기록원",
    "청사",
    "공단",
    "국민연금",
    "국민건강보험",
    "근로복지",
    "고용노동",
    "노동청",
    "한국전력공사",
    "한국수산자원",
    "농업기술센터",
    "차량등록사업소",
    "민원센터",
    "문화센터",
    "문화복합센터",
    "문화회관",
    "어업관리단",
    "교통정보",
    "교통관제",
    "순찰대",
    "출장소",
]

RENAME_HINT_TERMS = [
    "동사무소",
    "주민자치센터",
    "파줄소",
    "파출소, 지구대",
    "노동부",
    "지방국토관리청",
    "국민연금부산회관",
    "국민건강보험공단",
    "이정빌딩",
    "업무시설",
]

HEALTHCARE_TERMS = ["보건소", "보건지소"]
WELFARE_TERMS = ["건강가정지원센터", "가족센터"]

BAD_PUBLIC_EVIDENCE_TERMS = [
    "전기차충전소",
    "전기차 충전소",
    "입구",
    "버스정류장",
    "무더위",
    "한파",
    "주차장",
    "편의점",
    "카페",
    "음식점",
    "부동산",
    "은행",
    "학원",
]

NON_PUBLIC_STRONG_TERMS = [
    "수직농장",
    "Complex Town",
    "씨사이드",
    "Sea Side",
    "SeaSide",
    "유람선터미널",
]

LABELS = {
    "HEALTHCARE": "의료·보건",
    "WELFARE": "복지·돌봄",
    "PUBLIC_OFFICE": "공공기관",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
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


def distance_ok(value: str, max_m: float = 80) -> bool:
    distance = parse_float(value)
    return distance is not None and distance <= max_m


def normalize_name(value: str) -> str:
    value = (value or "").strip()
    value = re.sub(r"\s+", " ", value)
    value = value.replace(" ", "")
    value = value.replace("제1동", "1동").replace("제2동", "2동").replace("제3동", "3동").replace("제4동", "4동")
    return value


def names_same_enough(a: str, b: str) -> bool:
    left = normalize_name(a)
    right = normalize_name(b)
    return left == right or left in right or right in left


def clean_candidate_name(name: str) -> str:
    value = (name or "").strip()
    value = re.sub(r"\s*전기차충전소$", "", value).strip()
    value = re.sub(r"\s*\(버스정류장\)$", "", value).strip()
    value = re.sub(r"\s*입구$", "", value).strip()
    if "/" in value:
        parts = [part.strip() for part in value.split("/") if part.strip()]
        for part in parts:
            if has_any(part, PUBLIC_HINT_TERMS):
                return part
    return value


def public_external_candidate(cross: dict[str, str]) -> tuple[str, str, str, str]:
    candidates = [
        ("kakao", cross.get("kakao_place_name", ""), cross.get("kakao_category", ""), cross.get("kakao_distance_m", "")),
        ("poi", cross.get("poi_name", ""), cross.get("poi_category_label", ""), cross.get("poi_distance_m", "")),
    ]
    for source, raw_name, category, distance in candidates:
        if not raw_name or not distance_ok(distance):
            continue
        name = clean_candidate_name(raw_name)
        evidence = f"{name} {category}"
        if has_any(evidence, BAD_PUBLIC_EVIDENCE_TERMS):
            continue
        if has_any(evidence, PUBLIC_HINT_TERMS) or "사회,공공기관" in category or "기관명 > 행정부" in category:
            return source, name, category, distance
    return "", "", "", ""


def non_public_external_evidence(cross: dict[str, str]) -> tuple[str, str, str, str]:
    candidates = [
        ("kakao", cross.get("kakao_place_name", ""), cross.get("kakao_category", ""), cross.get("kakao_distance_m", "")),
        ("poi", cross.get("poi_name", ""), cross.get("poi_category_label", ""), cross.get("poi_distance_m", "")),
    ]
    for source, name, category, distance in candidates:
        if not name or not distance_ok(distance):
            continue
        evidence = f"{name} {category}"
        if has_any(evidence, PUBLIC_HINT_TERMS):
            continue
        if has_any(evidence, BAD_PUBLIC_EVIDENCE_TERMS) or has_any(evidence, NON_PUBLIC_STRONG_TERMS):
            return source, name, category, distance
    return "", "", "", ""


def recategory_target(row: dict[str, str], cross: dict[str, str]) -> tuple[str, str, str]:
    name = row["name"]
    kakao_name = cross.get("kakao_place_name", "")
    if has_any(name, HEALTHCARE_TERMS) or has_any(kakao_name, HEALTHCARE_TERMS):
        suggested = name
        if has_any(kakao_name, HEALTHCARE_TERMS) and not has_any(kakao_name, BAD_PUBLIC_EVIDENCE_TERMS):
            suggested = clean_candidate_name(kakao_name)
        return "HEALTHCARE", LABELS["HEALTHCARE"], suggested
    if has_any(name, WELFARE_TERMS) or has_any(kakao_name, WELFARE_TERMS):
        suggested = clean_candidate_name(kakao_name) if kakao_name else name
        return "WELFARE", LABELS["WELFARE"], suggested
    if "복합건강센터" in name:
        return "WELFARE", LABELS["WELFARE"], name
    return "", "", ""


def classify(row: dict[str, str], cross: dict[str, str]) -> tuple[str, str, str, str, str, str, str]:
    name = row["name"].strip()
    raw_type = row.get("rawFacilityType", "")
    target_category, target_label, recat_name = recategory_target(row, cross)
    if target_category:
        reason = f"공공기관보다 {target_label} 성격이 강함"
        return "RECATEGORY_CANDIDATE", recat_name if recat_name != name else "", target_category, "", "", "", reason

    public_source, public_name, public_category, public_distance = public_external_candidate(cross)
    non_source, non_name, non_category, non_distance = non_public_external_evidence(cross)

    if name == "파출소, 지구대" and public_name:
        return "RENAME_CANDIDATE", public_name, "", public_source, public_category, public_distance, "시설 유형명만 남아 실제 치안센터/파출소명으로 보정"

    if has_any(name, RENAME_HINT_TERMS) and public_name and not names_same_enough(name, public_name):
        return "RENAME_CANDIDATE", public_name, "", public_source, public_category, public_distance, "현재 표시명이 오래됐거나 포괄적이어서 POI/카카오 공공기관명으로 보정"

    if "파줄소" in name and public_name:
        return "RENAME_CANDIDATE", public_name, "", public_source, public_category, public_distance, "파출소 오타 보정"

    if public_name and not names_same_enough(name, public_name):
        if any(token in public_name for token in ["행정복지센터", "우체국", "지구대", "파출소", "치안센터", "세무서", "공단"]):
            if has_any(name, ["동사무소", "주민자치센터", "국민연금", "국민건강보험", "근로복지", "노동부"]):
                return "RENAME_CANDIDATE", public_name, "", public_source, public_category, public_distance, "공공기관 최신/정식 명칭으로 보정"

    if has_any(name, NON_PUBLIC_STRONG_TERMS):
        return "EXCLUDE_CANDIDATE", "", "", non_source, non_category, non_distance, "공공기관 목적지로 보기 어려운 시설명"

    if non_name and not has_any(name, PUBLIC_HINT_TERMS):
        return "EXCLUDE_CANDIDATE", "", "", non_source, non_category, non_distance, f"공공기관 근거 약함 / 외부 근거: {non_name}"

    if not has_any(name, PUBLIC_HINT_TERMS) and not public_name:
        return "MANUAL_REVIEW", "", "", "", "", "", "공공기관명 근거가 약해 수동 확인 필요"

    return "KEEP", "", "", "", "", "", "현재 이름 유지 가능"


def main() -> None:
    public_rows = [row for row in read_csv(FINAL) if row["dbCategory"] == "PUBLIC_OFFICE"]
    cross_rows = {row["place_key"]: row for row in read_csv(CROSS)}

    out: list[dict[str, Any]] = []
    for row in public_rows:
        cross = cross_rows.get(row["sourceKey"], {})
        action, suggested_name, suggested_category, source, category, distance, reason = classify(row, cross)
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
                "suggestedCategory": suggested_category,
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
        "totalPublicOffice": len(public_rows),
        "byRecommendedAction": dict(Counter(row["recommendedAction"] for row in out)),
        "candidateCount": len(candidates),
        "outputs": {"csv": str(OUT_CSV), "candidates": str(OUT_CANDIDATES)},
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for action in ["RENAME_CANDIDATE", "RECATEGORY_CANDIDATE", "EXCLUDE_CANDIDATE", "MANUAL_REVIEW"]:
        subset = [row for row in out if row["recommendedAction"] == action]
        print(f"\n[{action}] {len(subset)}")
        for row in subset[:120]:
            suffix = ""
            if row["suggestedName"]:
                suffix += f" -> {row['suggestedName']}"
            if row["suggestedCategory"]:
                suffix += f" [{row['suggestedCategory']}]"
            print(f"- {row['placeId']} {row['name']}{suffix} | {row['reason']}")


if __name__ == "__main__":
    main()
