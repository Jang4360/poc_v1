from __future__ import annotations

import math
from pathlib import Path

import pandas as pd


POC_ROOT = Path(__file__).resolve().parents[1]
VALIDATION_DIR = POC_ROOT / "data" / "reports" / "facility_validation"

INPUT_CSV = VALIDATION_DIR / "facility_cross_validation_all.csv"
OUT_ALL = VALIDATION_DIR / "facility_cross_validation_action_plan.csv"
OUT_HUMAN = VALIDATION_DIR / "facility_cross_validation_human_decision_plan.csv"
OUT_SUMMARY = VALIDATION_DIR / "facility_cross_validation_action_summary.csv"


GENERIC_NAMES = {
    "일반음식점",
    "휴게음식점",
    "제과점",
    "휴게음식점·제과점",
    "공중화장실",
    "화장실",
    "의원·치과의원",
    "병원·치과병원",
    "노인복지시설",
    "사회복지시설",
    "장애인복지시설",
    "아동복지시설",
    "일반숙박시설",
    "관광숙박시설",
    "생활숙박시설",
}

BAD_USER_FACING_NAME_KEYWORDS = [
    "일반음식점및주택",
    "입구",
]


def text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value).strip()


def number(value: object, default: float = 999999.0) -> float:
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def is_good_name(name: str, current_name: str) -> bool:
    name = text(name)
    if not name:
        return False
    if name in GENERIC_NAMES:
        return False
    if name == text(current_name):
        return False
    return not any(keyword in name for keyword in BAD_USER_FACING_NAME_KEYWORDS)


def candidate_score(prefix: str, row: pd.Series) -> float:
    distance = number(row.get(f"{prefix}_distance_m"))
    score_col = "kakao_best_score" if prefix == "kakao" else "poi_match_score"
    base_score = number(row.get(score_col), 0.0)
    category = text(row.get(f"{prefix}_category_assessment"))
    status_col = "kakao_best_status" if prefix == "kakao" else "poi_match_status"
    status = text(row.get(status_col))

    score = base_score
    if distance <= 10:
        score += 12
    elif distance <= 30:
        score += 8
    elif distance <= 80:
        score += 4
    else:
        score -= 60

    if category == "CATEGORY_MATCH":
        score += 18
    elif category == "CATEGORY_CHECK":
        score -= 8
    elif category == "INTERNAL_TOILET_CONTEXT":
        score -= 20

    if status.endswith("STRONG") or status == "MATCH_STRONG":
        score += 8
    elif status.endswith("MEDIUM") or status == "MATCH_MEDIUM":
        score += 3
    elif status.endswith("WEAK") or status == "MATCH_WEAK":
        score -= 8

    return score


def choose_suggested_name(row: pd.Series) -> tuple[str, str]:
    current_name = text(row.get("place_name"))
    candidates: list[tuple[float, str, str]] = []

    kakao_name = text(row.get("kakao_place_name"))
    kakao_distance = number(row.get("kakao_distance_m"))
    if is_good_name(kakao_name, current_name) and kakao_distance <= 100:
        candidates.append((candidate_score("kakao", row), kakao_name, "KAKAO"))

    poi_name = text(row.get("poi_name"))
    poi_distance = number(row.get("poi_distance_m"))
    if is_good_name(poi_name, current_name) and poi_distance <= 100:
        candidates.append((candidate_score("poi", row), poi_name, "POI"))

    if not candidates:
        return "", ""

    candidates.sort(reverse=True)
    _, name, source = candidates[0]
    return name, source


def evidence_grade(row: pd.Series) -> str:
    cross = text(row.get("cross_check_status"))
    kakao_status = text(row.get("kakao_best_status"))
    poi_status = text(row.get("poi_match_status"))
    kakao_distance = number(row.get("kakao_distance_m"))
    poi_distance = number(row.get("poi_distance_m"))

    if cross == "BOTH_STRONG" and min(kakao_distance, poi_distance) <= 50:
        return "HIGH"
    if cross in {"POI_ONLY", "KAKAO_ONLY"}:
        return "MEDIUM"
    if poi_status == "MATCH_STRONG" or kakao_status == "KAKAO_STRONG":
        return "MEDIUM"
    return "LOW"


def min_evidence_distance(row: pd.Series) -> float | None:
    distances = [
        number(row.get("poi_distance_m")),
        number(row.get("kakao_distance_m")),
    ]
    valid_distances = [distance for distance in distances if distance < 999999.0]
    if not valid_distances:
        return None
    return round(min(valid_distances), 1)


def coordinate_validation_status(row: pd.Series) -> str:
    poi_distance = number(row.get("poi_distance_m"))
    kakao_distance = number(row.get("kakao_distance_m"))
    poi_status = text(row.get("poi_match_status"))
    kakao_status = text(row.get("kakao_best_status"))
    cross_status = text(row.get("cross_check_status"))

    near_poi = poi_distance <= 50 and poi_status in {"MATCH_STRONG", "MATCH_MEDIUM"}
    near_kakao = kakao_distance <= 50 and kakao_status in {"KAKAO_STRONG", "KAKAO_MEDIUM"}

    if near_poi and near_kakao:
        return "A_BOTH_NEAR_50M"
    if near_poi or near_kakao:
        return "B_ONE_NEAR_50M"
    if poi_distance <= 100 or kakao_distance <= 100:
        return "C_NEAR_100M_REVIEW"
    if cross_status in {"NO_STRONG_EVIDENCE", "CONFLICT_OR_WEAK"}:
        return "D_COORD_REVIEW_REQUIRED"
    return "D_COORD_REVIEW_REQUIRED"


def suggested_action(row: pd.Series, suggested_name: str) -> tuple[str, str, int]:
    decision = text(row.get("final_review_decision"))
    ui_category = text(row.get("ui_category"))

    if decision in {"KEEP", "KEEP_WITH_CONTEXT", "KEEP_AREA_PLACE"}:
        return "KEEP_AS_IS", "AUTO_KEEP", 9
    if decision == "KEEP_LOCATION_REVIEW":
        return "KEEP_WITH_LOCATION_SAMPLE_CHECK", "AUTO_KEEP_WITH_NOTE", 6
    if decision == "EXCLUDE_CANDIDATE":
        if ui_category == "화장실":
            return "EXCLUDE_IF_INTERNAL_TOILET_POLICY_ACCEPTED", "POLICY_EXCLUDE_CANDIDATE", 1
        return "EXCLUDE_CANDIDATE_REVIEW", "POLICY_EXCLUDE_CANDIDATE", 2
    if decision == "RENAME_CANDIDATE":
        if suggested_name:
            return "RENAME_TO_SUGGESTED_NAME", "RENAME_CANDIDATE", 2
        return "RENAME_NEEDS_MANUAL_NAME", "RENAME_CANDIDATE", 2
    if decision == "RENAME_OR_EXCLUDE":
        return "MANUAL_RENAME_OR_EXCLUDE", "MANUAL_DECISION", 3
    return "MANUAL_REVIEW", "MANUAL_DECISION", 4


def build_action_plan() -> pd.DataFrame:
    df = pd.read_csv(INPUT_CSV, encoding="utf-8-sig")
    rows: list[dict[str, object]] = []

    for _, row in df.iterrows():
        suggested_name, suggested_name_source = choose_suggested_name(row)
        action, bucket, human_priority = suggested_action(row, suggested_name)
        rows.append(
            {
                "place_key": text(row.get("place_key")),
                "current_name": text(row.get("place_name")),
                "suggested_name": suggested_name,
                "suggested_name_source": suggested_name_source,
                "ui_category": text(row.get("ui_category")),
                "district_gu": text(row.get("district_gu")),
                "address": text(row.get("address")),
                "latitude": row.get("latitude"),
                "longitude": row.get("longitude"),
                "accessibility_type_labels": text(row.get("accessibility_type_labels")),
                "final_review_decision": text(row.get("final_review_decision")),
                "suggested_apply_action": action,
                "decision_bucket": bucket,
                "human_priority": human_priority,
                "evidence_grade": evidence_grade(row),
                "coord_validation_status": coordinate_validation_status(row),
                "min_evidence_distance_m": min_evidence_distance(row),
                "cross_check_status": text(row.get("cross_check_status")),
                "poi_match_status": text(row.get("poi_match_status")),
                "poi_distance_m": row.get("poi_distance_m"),
                "poi_name": text(row.get("poi_name")),
                "poi_category_label": text(row.get("poi_category_label")),
                "kakao_best_status": text(row.get("kakao_best_status")),
                "kakao_distance_m": row.get("kakao_distance_m"),
                "kakao_place_name": text(row.get("kakao_place_name")),
                "kakao_category": text(row.get("kakao_category")),
                "final_review_reason": text(row.get("final_review_reason")),
                "map_url": text(row.get("map_url")),
                "roadview_url": text(row.get("roadview_url")),
            }
        )

    plan = pd.DataFrame(rows)
    return plan.sort_values(
        ["human_priority", "ui_category", "district_gu", "current_name", "place_key"],
        kind="stable",
    )


def write_summary(plan: pd.DataFrame) -> None:
    rows: list[dict[str, object]] = []
    for group_cols in [
        ["decision_bucket"],
        ["suggested_apply_action"],
        ["ui_category", "suggested_apply_action"],
        ["evidence_grade", "decision_bucket"],
        ["coord_validation_status"],
        ["ui_category", "coord_validation_status"],
    ]:
        grouped = (
            plan.groupby(group_cols, dropna=False)
            .size()
            .reset_index(name="count")
            .sort_values("count", ascending=False)
        )
        summary_type = " / ".join(group_cols)
        for _, row in grouped.iterrows():
            key = " / ".join(text(row.get(col)) for col in group_cols)
            rows.append({"summary_type": summary_type, "key": key, "count": int(row["count"])})

    pd.DataFrame(rows).to_csv(OUT_SUMMARY, index=False, encoding="utf-8-sig")


def main() -> None:
    plan = build_action_plan()
    plan.to_csv(OUT_ALL, index=False, encoding="utf-8-sig")
    plan[plan["human_priority"] <= 4].to_csv(OUT_HUMAN, index=False, encoding="utf-8-sig")
    write_summary(plan)

    print(f"wrote {OUT_ALL} ({len(plan):,} rows)")
    print(f"wrote {OUT_HUMAN} ({(plan['human_priority'] <= 4).sum():,} rows)")
    print(f"wrote {OUT_SUMMARY}")


if __name__ == "__main__":
    main()
