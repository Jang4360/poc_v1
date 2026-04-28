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
OUT_CSV = REPORT_DIR / "accommodation_current_quality_plan.csv"
OUT_CANDIDATES = REPORT_DIR / "accommodation_current_quality_candidates.csv"
OUT_SUMMARY = REPORT_DIR / "accommodation_current_quality_plan_summary.json"

ACCOMMODATION_HINT_TERMS = [
    "호텔",
    "모텔",
    "호스텔",
    "게스트하우스",
    "게스트 하우스",
    "펜션",
    "리조트",
    "스테이",
    "인",
    "여관",
    "콘도",
    "레지던스",
    "Residence",
    "HOTEL",
    "Hotel",
    "MOTEL",
    "Motel",
    "STAY",
    "Stay",
    "INN",
    "Inn",
]

GENERIC_EXACT_NAMES = {
    "일반숙박시설",
    "관광숙박시설",
    "생활숙박시설",
    "ACCOMMODATION",
}

STRUCTURAL_TERMS = [
    "빌딩",
    "타워",
    "상가",
    "건물",
    "PARK",
    "파크",
    "센터",
]

BAD_EXTERNAL_CATEGORY_TERMS = [
    "음식점",
    "카페",
    "편의점",
    "은행",
    "부동산",
    "주차장",
    "전기차",
    "전기차충전소",
    "병원",
    "약국",
    "학원",
    "미용",
]

MANUAL_DECISIONS = {
    "accommodation:93": ("KEEP", "", "수동 검토: 공식 숙박 원본이며 POI 호텔업 근거가 있어 유지"),
    "barrier_free_facility:3722": ("RENAME_CANDIDATE", "호텔티티", "수동 검토: T.T는 숙박시설명으로 너무 축약되어 호텔티티로 보정"),
    "barrier_free_facility:3762": ("KEEP", "", "수동 검토: 생활형숙박시설 근거가 있어 유지"),
    "barrier_free_facility:4395": ("KEEP", "", "수동 검토: 생활숙박시설 원본 근거가 있어 유지"),
    "barrier_free_facility:6808": ("EXCLUDE_CANDIDATE", "", "수동 검토: 지엠타워는 숙박 목적지명이 아니라 건물명으로 판단해 제거"),
    "barrier_free_facility:6856": ("KEEP", "", "수동 검토: 더펫텔 프리미엄 스위트는 숙박시설명으로 유지"),
    "barrier_free_facility:6956": ("KEEP", "", "수동 검토: 콘도/리조트 숙박 근거가 있어 유지"),
    "barrier_free_facility:7054": ("KEEP", "", "수동 검토: 페어필드 바이 메리어트 부산은 숙박시설명으로 유지"),
    "barrier_free_facility:7132": ("RENAME_CANDIDATE", "엘리시아부티크호텔", "수동 검토: 실제 숙박시설명으로 보정"),
    "barrier_free_facility:7345": ("EXCLUDE_CANDIDATE", "", "수동 검토: 외부 근거가 불교시설/근린생활시설로 숙박 목적지 근거가 약함"),
    "barrier_free_facility:7347": ("RENAME_CANDIDATE", "해수락", "수동 검토: 실제 숙박시설명으로 보정"),
    "barrier_free_facility:6889": ("KEEP", "", "수동 검토: 파크하얏트 부산은 숙박시설명으로 유지"),
    "barrier_free_facility:8323": ("RENAME_CANDIDATE", "로즈베이호텔", "수동 검토: 실제 숙박시설명으로 보정"),
    "barrier_free_facility:10105": ("RENAME_CANDIDATE", "웁스모텔", "수동 검토: 실제 숙박시설명으로 보정"),
    "barrier_free_facility:12146": ("RENAME_CANDIDATE", "브라운도트호텔 엄궁점", "수동 검토: 실제 숙박시설명으로 보정"),
    "barrier_free_facility:12150": ("RENAME_CANDIDATE", "썸호텔", "수동 검토: 실제 숙박시설명으로 보정"),
    "barrier_free_facility:12484": ("RENAME_CANDIDATE", "아난티 코브", "수동 검토: 포괄 주소형 이름을 실제 숙박시설명으로 보정"),
    "barrier_free_facility:12497": ("RENAME_CANDIDATE", "마티에 오시리아", "수동 검토: POI 근거 기준 실제 숙박시설명으로 보정"),
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


def find_terms(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if term in (text or "")]


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
    value = re.sub(r"\[[^\]]+\]", "", value)
    value = re.sub(r"\([^)]*\)", "", value)
    value = value.replace(" ", "").replace(".", "").replace("·", "")
    return value.lower()


def names_same_enough(a: str, b: str) -> bool:
    left = normalize_name(a)
    right = normalize_name(b)
    return left == right or left in right or right in left


def clean_candidate_name(name: str) -> str:
    value = (name or "").strip()
    value = re.sub(r"\[[^\]]+\]", "", value).strip()
    value = re.sub(r"\s*입구$", "", value).strip()
    if "/" in value:
        parts = [part.strip() for part in value.split("/") if part.strip()]
        for part in parts:
            if has_any(part, ACCOMMODATION_HINT_TERMS):
                return part
    return value


def accommodation_external_candidate(cross: dict[str, str]) -> tuple[str, str, str, str]:
    candidates = [
        ("kakao", cross.get("kakao_place_name", ""), cross.get("kakao_category", ""), cross.get("kakao_distance_m", "")),
        ("poi", cross.get("poi_name", ""), cross.get("poi_category_label", ""), cross.get("poi_distance_m", "")),
    ]
    for source, raw_name, category, distance in candidates:
        if not raw_name or not distance_ok(distance):
            continue
        name = clean_candidate_name(raw_name)
        evidence = f"{name} {category}"
        if has_any(evidence, BAD_EXTERNAL_CATEGORY_TERMS):
            continue
        if has_any(evidence, ACCOMMODATION_HINT_TERMS) or "숙박" in category or "호텔" in category or "여관" in category or "콘도" in category:
            return source, name, category, distance
    return "", "", "", ""


def non_accommodation_external_evidence(cross: dict[str, str]) -> tuple[str, str, str, str]:
    candidates = [
        ("kakao", cross.get("kakao_place_name", ""), cross.get("kakao_category", ""), cross.get("kakao_distance_m", "")),
        ("poi", cross.get("poi_name", ""), cross.get("poi_category_label", ""), cross.get("poi_distance_m", "")),
    ]
    for source, name, category, distance in candidates:
        if not name or not distance_ok(distance):
            continue
        evidence = f"{name} {category}"
        if has_any(evidence, ACCOMMODATION_HINT_TERMS):
            continue
        if has_any(evidence, BAD_EXTERNAL_CATEGORY_TERMS):
            return source, name, category, distance
    return "", "", "", ""


def classify(row: dict[str, str], cross: dict[str, str]) -> tuple[str, str, str, str, str, str]:
    manual = MANUAL_DECISIONS.get(row["sourceKey"])
    if manual:
        action, suggested_name, reason = manual
        if action == "RENAME_CANDIDATE" and row["name"].strip() == suggested_name:
            return "KEEP", "", "manual", "", "", "수동 보정 반영 완료"
        return action, suggested_name, "manual", "", "", reason

    name = row["name"].strip()
    source_dataset = row["sourceDataset"]
    accommodation_source, accommodation_name, accommodation_category, accommodation_distance = accommodation_external_candidate(cross)
    non_source, non_name, non_category, non_distance = non_accommodation_external_evidence(cross)

    issues: list[str] = []
    if name in GENERIC_EXACT_NAMES:
        issues.append("시설 유형명만 남음")
    if find_terms(name, STRUCTURAL_TERMS) and not has_any(name, ACCOMMODATION_HINT_TERMS):
        issues.append(f"건물/구조물명 의심: {'|'.join(find_terms(name, STRUCTURAL_TERMS))}")
    if source_dataset == "barrier_free_facility" and not has_any(name, ACCOMMODATION_HINT_TERMS):
        issues.append("장애인편의시설 원본 기반 숙박이나 표시명이 숙박 목적지를 설명하지 못함")

    if not issues:
        return "KEEP", "", "", "", "", "현재 이름 유지 가능"

    if accommodation_name and accommodation_name != name and not names_same_enough(name, accommodation_name):
        return "RENAME_CANDIDATE", accommodation_name, accommodation_source, accommodation_category, accommodation_distance, " / ".join(issues)

    if non_name:
        return "EXCLUDE_CANDIDATE", "", non_source, non_category, non_distance, f"{' / '.join(issues)} / 외부 근거: {non_name}"

    return "MANUAL_REVIEW", "", accommodation_source, accommodation_category, accommodation_distance, " / ".join(issues)


def main() -> None:
    accommodation_rows = [row for row in read_csv(FINAL) if row["dbCategory"] == "ACCOMMODATION"]
    cross_rows = {row["place_key"]: row for row in read_csv(CROSS)}

    out: list[dict[str, Any]] = []
    for row in accommodation_rows:
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
        "totalAccommodation": len(accommodation_rows),
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
