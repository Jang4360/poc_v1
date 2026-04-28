from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(r"C:\Users\SSAFY\Desktop\poc")
STAIR_DIR = ROOT / "data" / "final" / "stairs"

INPUTS = [
    STAIR_DIR / "stair_candidates_keep_review.csv",
    STAIR_DIR / "stair_candidates_residential_manual_review.csv",
    STAIR_DIR / "stair_candidates_p4_manual_review.csv",
]

OUT_ALL = STAIR_DIR / "stair_first_pass_decisions.csv"
OUT_LIKELY_ADOPT = STAIR_DIR / "stair_first_pass_likely_adopt.csv"
OUT_LIKELY_EXCLUDE = STAIR_DIR / "stair_first_pass_likely_exclude.csv"
OUT_MANUAL_REVIEW = STAIR_DIR / "stair_first_pass_manual_review.csv"
OUT_SUMMARY = STAIR_DIR / "stair_first_pass_decision_summary.json"

GENERIC_STAIR_NAMES = {"", "계단", "NULL", "None", "none"}

PUBLIC_CONTEXT_TERMS = [
    "공원",
    "역",
    "지하철",
    "지하도",
    "육교",
    "해수욕장",
    "해변",
    "시장",
    "구청",
    "행정복지",
    "주민센터",
    "복지관",
    "도서관",
    "체육",
    "터미널",
    "광장",
    "관광",
    "전망대",
    "산책",
    "둘레길",
    "공영",
    "병원",
    "보건소",
    "세월교",
    "강변",
    "수영강",
]

WEAK_PRIVATE_CONTEXT_TERMS = [
    "주유소",
    "충전소",
    "빌딩",
    "상가",
    "마트",
    "호텔",
    "음식점",
    "카페",
    "식당",
    "공장",
]


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


def is_true(value: str) -> bool:
    return str(value).lower() == "true"


def has_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


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
        ]
    )


def has_public_context(row: dict[str, str]) -> bool:
    return has_any(context_text(row), PUBLIC_CONTEXT_TERMS)


def has_weak_private_context(row: dict[str, str]) -> bool:
    return has_any(context_text(row), WEAK_PRIVATE_CONTEXT_TERMS)


def is_generic_stair(row: dict[str, str]) -> bool:
    return (row.get("name", "") or "").strip() in GENERIC_STAIR_NAMES


def classify(row: dict[str, str]) -> tuple[str, str, str]:
    workset = row.get("workset", "")
    priority = row.get("priority", "")
    source_decision = row.get("decision", "")
    road = parse_float(row.get("nearestRoadDistanceM", ""))
    crosswalk = parse_float(row.get("nearestCrosswalkDistanceM", ""))
    facility = parse_float(row.get("nearestFacilityDistanceM", ""))
    near_crosswalk = is_true(row.get("nearCrosswalk30m", "")) or crosswalk <= 30
    near_facility = is_true(row.get("nearFacility50m", "")) or facility <= 50
    public_context = has_public_context(row)
    generic = is_generic_stair(row)
    weak_private_context = has_weak_private_context(row)

    if workset == "RESIDENTIAL_MANUAL_REVIEW":
        if road > 100 and not near_crosswalk and not near_facility:
            return "LIKELY_EXCLUDE", "MEDIUM_HIGH", "residential_gt_100m_no_nearby_public_clue"
        if priority == "P4" and road > 50 and not near_crosswalk and not near_facility and not public_context:
            return "LIKELY_EXCLUDE", "MEDIUM", "residential_p4_gt_50m_no_public_context"
        return "MANUAL_REVIEW", "MEDIUM", "residential_may_be_private_or_through_path"

    if workset == "P4_MANUAL_REVIEW":
        if source_decision == "REVIEW_P4_LOW_CONNECTIVITY":
            return "LIKELY_EXCLUDE", "MEDIUM", "p4_low_connectivity_no_public_context"
        if road > 100 and not near_crosswalk and not near_facility and not public_context:
            return "LIKELY_EXCLUDE", "MEDIUM_HIGH", "p4_gt_100m_no_nearby_public_clue"
        return "MANUAL_REVIEW", "MEDIUM", "p4_needs_map_check_before_adoption"

    if priority == "P1":
        if road <= 5 and (near_crosswalk or public_context):
            return "LIKELY_ADOPT", "HIGH", "p1_road_with_crosswalk_or_public_context"
        if road <= 5 and generic and near_facility and not weak_private_context:
            return "LIKELY_ADOPT", "MEDIUM_HIGH", "p1_generic_road_with_facility_context"
        if road <= 5 and generic:
            return "LIKELY_ADOPT", "MEDIUM", "p1_generic_road_connected"
        return "MANUAL_REVIEW", "MEDIUM", "p1_named_place_needs_context_check"

    if priority == "P2":
        if road <= 20 and (near_crosswalk or public_context):
            return "LIKELY_ADOPT", "MEDIUM_HIGH", "p2_road_with_crosswalk_or_public_context"
        if road <= 20 and generic and near_facility and not weak_private_context:
            return "LIKELY_ADOPT", "MEDIUM", "p2_generic_road_with_facility_context"
        return "MANUAL_REVIEW", "MEDIUM", "p2_needs_context_check"

    if priority == "P3":
        if road <= 10 and public_context:
            return "LIKELY_ADOPT", "MEDIUM", "p3_close_road_with_public_context"
        if road <= 10 and generic and not weak_private_context:
            return "MANUAL_REVIEW", "MEDIUM", "p3_close_road_generic_needs_visual_check"
        return "MANUAL_REVIEW", "LOW", "p3_no_nearby_crosswalk_or_facility"

    return "MANUAL_REVIEW", "LOW", "fallback_needs_manual_review"


def enrich(row: dict[str, str]) -> dict[str, str]:
    first_pass, confidence, reason_code = classify(row)
    out = dict(row)
    out["firstPassDecision"] = first_pass
    out["firstPassConfidence"] = confidence
    out["firstPassReasonCode"] = reason_code
    return out


def main() -> None:
    rows: list[dict[str, str]] = []
    for path in INPUTS:
        rows.extend(read_csv(path))

    out_rows = [enrich(row) for row in rows]
    likely_adopt = [row for row in out_rows if row["firstPassDecision"] == "LIKELY_ADOPT"]
    likely_exclude = [row for row in out_rows if row["firstPassDecision"] == "LIKELY_EXCLUDE"]
    manual_review = [row for row in out_rows if row["firstPassDecision"] == "MANUAL_REVIEW"]

    fieldnames = list(out_rows[0].keys()) if out_rows else ["firstPassDecision"]
    write_csv(OUT_ALL, out_rows, fieldnames)
    write_csv(OUT_LIKELY_ADOPT, likely_adopt, fieldnames)
    write_csv(OUT_LIKELY_EXCLUDE, likely_exclude, fieldnames)
    write_csv(OUT_MANUAL_REVIEW, manual_review, fieldnames)

    summary = {
        "inputs": [str(path) for path in INPUTS],
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
        "decisionCounts": dict(Counter(row["firstPassDecision"] for row in out_rows)),
        "decisionByWorkset": {
            workset: dict(Counter(row["firstPassDecision"] for row in out_rows if row.get("workset") == workset))
            for workset in sorted({row.get("workset", "") for row in out_rows})
        },
        "decisionByPriority": {
            priority: dict(Counter(row["firstPassDecision"] for row in out_rows if row.get("priority") == priority))
            for priority in ["P1", "P2", "P3", "P4"]
        },
        "reasonCodeCounts": dict(Counter(row["firstPassReasonCode"] for row in out_rows)),
        "reasonCodeByDecision": {
            decision: dict(
                Counter(row["firstPassReasonCode"] for row in out_rows if row["firstPassDecision"] == decision)
            )
            for decision in ["LIKELY_ADOPT", "LIKELY_EXCLUDE", "MANUAL_REVIEW"]
        },
        "districtDecisionCounts": {
            district: dict(Counter(row["firstPassDecision"] for row in out_rows if row.get("districtGu") == district))
            for district in sorted({row.get("districtGu", "") for row in out_rows})
        },
        "note": "LIKELY_* is a first-pass data decision, not final confirmation. MANUAL_REVIEW remains the visual review target.",
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
