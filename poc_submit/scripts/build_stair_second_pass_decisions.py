from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(r"C:\Users\SSAFY\Desktop\poc")
STAIR_DIR = ROOT / "data" / "final" / "stairs"

IN_ALL = STAIR_DIR / "stair_first_pass_decisions.csv"
OUT_ALL = STAIR_DIR / "stair_second_pass_decisions.csv"
OUT_LIKELY_ADOPT = STAIR_DIR / "stair_second_pass_likely_adopt.csv"
OUT_LIKELY_EXCLUDE = STAIR_DIR / "stair_second_pass_likely_exclude.csv"
OUT_MANUAL_REVIEW = STAIR_DIR / "stair_second_pass_manual_review.csv"
OUT_SUMMARY = STAIR_DIR / "stair_second_pass_decision_summary.json"

PUBLIC_CONTEXT_TERMS = [
    "공원",
    "생태",
    "산책",
    "둘레길",
    "강변",
    "하천",
    "수영강",
    "해변",
    "해수욕장",
    "전망대",
    "관광",
    "시장",
    "광장",
    "역",
    "지하철",
    "육교",
    "지하도",
    "구청",
    "군청",
    "주민센터",
    "행정복지",
    "복지",
    "도서관",
    "체육",
    "운동장",
    "터미널",
    "공영",
    "파출소",
    "보건소",
]

RESIDENTIAL_TERMS = [
    "아파트",
    "오피스텔",
    "빌라",
    "맨션",
    "주택",
    "주공",
    "힐스테이트",
    "푸르지오",
    "자이",
    "래미안",
    "롯데캐슬",
    "더샵",
    "SK뷰",
    "데시앙",
    "해링턴",
    "그린코아",
]

PRIVATE_CONTEXT_TERMS = [
    "주유소",
    "호텔",
    "모텔",
    "빌딩",
    "상가",
    "프라자",
    "마트",
    "공장",
    "창고",
    "물류",
]

RELIGIOUS_TERMS = ["교회", "성당", "사찰", "문수사", "대덕사", "금용암", "암자"]
PRIVATE_FACILITY_TERMS = PRIVATE_CONTEXT_TERMS + RESIDENTIAL_TERMS + RELIGIOUS_TERMS + [
    "음식점",
    "식당",
    "카페",
    "커피",
]

PUBLIC_FACILITY_CATEGORIES = {
    "화장실",
    "복지·돌봄",
    "행정·공공기관",
    "전동보장구 충전소",
    "관광지",
    "의료·보건",
}

WEAK_FACILITY_CATEGORIES = {"음식·카페", "숙박"}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_float(value: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 999999.0


def context_text(row: dict[str, str]) -> str:
    return " ".join(
        row.get(key, "") or ""
        for key in [
            "name",
            "nearestRoadName",
            "nearestCrosswalkLabel",
            "nearestFacilityName",
            "nearestFacilityCategory",
            "reviewReason",
            "decisionReasonCode",
        ]
    )


def facility_text(row: dict[str, str]) -> str:
    return " ".join(row.get(key, "") or "" for key in ["nearestFacilityName", "nearestFacilityCategory"])


def has_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def is_generic_name(row: dict[str, str]) -> bool:
    return (row.get("name", "") or "").strip() in {"", "계단", "NULL", "None", "none"}


def has_public_context(row: dict[str, str]) -> bool:
    return has_any(context_text(row), PUBLIC_CONTEXT_TERMS)


def has_residential_context(row: dict[str, str]) -> bool:
    return has_any(context_text(row), RESIDENTIAL_TERMS)


def has_private_context(row: dict[str, str]) -> bool:
    return has_any(context_text(row), PRIVATE_CONTEXT_TERMS)


def has_religious_context(row: dict[str, str]) -> bool:
    return has_any(context_text(row), RELIGIOUS_TERMS)


def is_near_public_facility(row: dict[str, str], max_m: float) -> bool:
    if has_any(facility_text(row), PRIVATE_FACILITY_TERMS):
        return False
    return (
        parse_float(row.get("nearestFacilityDistanceM", "")) <= max_m
        and (row.get("nearestFacilityCategory", "") or "") in PUBLIC_FACILITY_CATEGORIES
    )


def is_near_weak_facility(row: dict[str, str], max_m: float) -> bool:
    return (
        parse_float(row.get("nearestFacilityDistanceM", "")) <= max_m
        and (row.get("nearestFacilityCategory", "") or "") in WEAK_FACILITY_CATEGORIES
    )


def classify_manual_review(row: dict[str, str]) -> tuple[str, str, str]:
    priority = row.get("priority", "")
    reason = row.get("firstPassReasonCode", "")
    road = parse_float(row.get("nearestRoadDistanceM", ""))
    crosswalk = parse_float(row.get("nearestCrosswalkDistanceM", ""))
    facility = parse_float(row.get("nearestFacilityDistanceM", ""))
    public_context = has_public_context(row)
    residential_context = has_residential_context(row)
    private_context = has_private_context(row)
    religious_context = has_religious_context(row)
    generic = is_generic_name(row)
    near_public_80 = is_near_public_facility(row, 80)
    near_public_150 = is_near_public_facility(row, 150)
    weak_private = private_context or is_near_weak_facility(row, 60)

    if residential_context:
        if crosswalk <= 50 or near_public_80:
            return "MANUAL_REVIEW", "MEDIUM", "residential_near_public_clue_needs_visual_check"
        return "LIKELY_EXCLUDE", "MEDIUM_HIGH", "residential_internal_or_private_access"

    if religious_context:
        if road <= 5 and (crosswalk <= 80 or near_public_80):
            return "MANUAL_REVIEW", "MEDIUM", "religious_site_near_public_clue_needs_visual_check"
        return "LIKELY_EXCLUDE", "MEDIUM", "religious_site_internal_access"

    if priority in {"P1", "P2"}:
        if (public_context or near_public_80) and not private_context:
            return "LIKELY_ADOPT", "MEDIUM_HIGH", "p1_p2_public_context_promoted"
        if generic and road <= 10 and crosswalk <= 80 and not weak_private:
            return "LIKELY_ADOPT", "MEDIUM", "p1_p2_close_road_crosswalk_promoted"
        if weak_private and crosswalk > 100:
            return "LIKELY_EXCLUDE", "MEDIUM", "p1_p2_private_or_commercial_context_weak_walk_clue"
        return "MANUAL_REVIEW", "MEDIUM", "p1_p2_still_needs_visual_context"

    if priority == "P3":
        if road <= 10 and (public_context or near_public_150 or crosswalk <= 80) and not weak_private:
            return "LIKELY_ADOPT", "MEDIUM", "p3_public_walk_context_promoted"
        if generic and road <= 8 and crosswalk <= 80 and not weak_private:
            return "LIKELY_ADOPT", "LOW_MEDIUM", "p3_close_road_crosswalk_promoted"
        if road > 12 and crosswalk > 300 and facility > 300 and not public_context:
            return "LIKELY_EXCLUDE", "MEDIUM", "p3_isolated_no_public_walk_clue"
        if weak_private and crosswalk > 120 and not near_public_150:
            return "LIKELY_EXCLUDE", "MEDIUM", "p3_private_or_commercial_context_weak_walk_clue"
        return "MANUAL_REVIEW", "MEDIUM", f"{reason}_still_needs_visual_check"

    if priority == "P4":
        if road <= 50 and (public_context or is_near_public_facility(row, 50) or crosswalk <= 80) and not (
            residential_context or religious_context or private_context
        ):
            return "LIKELY_ADOPT", "LOW_MEDIUM", "p4_public_context_promoted_but_low_connectivity"
        if road > 50 and crosswalk > 120 and not is_near_public_facility(row, 80) and not public_context:
            return "LIKELY_EXCLUDE", "MEDIUM_HIGH", "p4_low_connectivity_no_public_walk_clue"
        if road > 120 and crosswalk > 120 and not is_near_public_facility(row, 50):
            return "LIKELY_EXCLUDE", "MEDIUM", "p4_far_from_road_and_public_facility"
        return "MANUAL_REVIEW", "MEDIUM", "p4_public_or_edge_case_needs_visual_check"

    return "MANUAL_REVIEW", "LOW", "fallback_still_needs_visual_check"


def classify(row: dict[str, str]) -> tuple[str, str, str]:
    first_pass = row.get("firstPassDecision", "")
    if first_pass == "LIKELY_ADOPT":
        return "LIKELY_ADOPT", row.get("firstPassConfidence", "MEDIUM"), "first_pass_likely_adopt"
    if first_pass == "LIKELY_EXCLUDE":
        return "LIKELY_EXCLUDE", row.get("firstPassConfidence", "MEDIUM"), "first_pass_likely_exclude"
    return classify_manual_review(row)


def enrich(row: dict[str, str]) -> dict[str, str]:
    decision, confidence, reason_code = classify(row)
    out = dict(row)
    out["secondPassDecision"] = decision
    out["secondPassConfidence"] = confidence
    out["secondPassReasonCode"] = reason_code
    return out


def main() -> None:
    rows = read_csv(IN_ALL)
    out_rows = [enrich(row) for row in rows]
    likely_adopt = [row for row in out_rows if row["secondPassDecision"] == "LIKELY_ADOPT"]
    likely_exclude = [row for row in out_rows if row["secondPassDecision"] == "LIKELY_EXCLUDE"]
    manual_review = [row for row in out_rows if row["secondPassDecision"] == "MANUAL_REVIEW"]

    fieldnames = list(out_rows[0].keys()) if out_rows else ["secondPassDecision"]
    write_csv(OUT_ALL, out_rows, fieldnames)
    write_csv(OUT_LIKELY_ADOPT, likely_adopt, fieldnames)
    write_csv(OUT_LIKELY_EXCLUDE, likely_exclude, fieldnames)
    write_csv(OUT_MANUAL_REVIEW, manual_review, fieldnames)

    summary = {
        "input": str(IN_ALL),
        "outputs": {
            "all": str(OUT_ALL),
            "likelyAdopt": str(OUT_LIKELY_ADOPT),
            "likelyExclude": str(OUT_LIKELY_EXCLUDE),
            "manualReview": str(OUT_MANUAL_REVIEW),
        },
        "counts": {
            "total": len(out_rows),
            "likelyAdopt": len(likely_adopt),
            "likelyExclude": len(likely_exclude),
            "manualReview": len(manual_review),
        },
        "decisionCounts": dict(Counter(row["secondPassDecision"] for row in out_rows)),
        "decisionByPriority": {
            priority: dict(Counter(row["secondPassDecision"] for row in out_rows if row.get("priority") == priority))
            for priority in ["P1", "P2", "P3", "P4"]
        },
        "decisionByFirstPass": {
            first_pass: dict(
                Counter(row["secondPassDecision"] for row in out_rows if row.get("firstPassDecision") == first_pass)
            )
            for first_pass in ["LIKELY_ADOPT", "LIKELY_EXCLUDE", "MANUAL_REVIEW"]
        },
        "reasonCodeByDecision": {
            decision: dict(
                Counter(row["secondPassReasonCode"] for row in out_rows if row["secondPassDecision"] == decision)
            )
            for decision in ["LIKELY_ADOPT", "LIKELY_EXCLUDE", "MANUAL_REVIEW"]
        },
        "districtDecisionCounts": {
            district: dict(Counter(row["secondPassDecision"] for row in out_rows if row.get("districtGu") == district))
            for district in sorted({row.get("districtGu", "") for row in out_rows})
        },
        "note": "Second pass reduces MANUAL_REVIEW using only data-context rules. It is not roadview confirmation.",
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
