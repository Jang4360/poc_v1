from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


POC_ROOT = Path(__file__).resolve().parents[1]
ADOPTED_PLACES = POC_ROOT / "data" / "adopted" / "adopted_places.csv"
OUT_DIR = POC_ROOT / "data" / "reports" / "facility_validation"
QUEUE_ALL_OUT = OUT_DIR / "facility_validation_queue.csv"
QUEUE_HIGH_OUT = OUT_DIR / "facility_validation_queue_high.csv"
QUEUE_HIGH_FIRST_PASS_OUT = OUT_DIR / "facility_validation_high_first_pass.csv"
QUEUE_MEDIUM_OUT = OUT_DIR / "facility_validation_queue_medium.csv"
QUEUE_MEDIUM_GROUPED_OUT = OUT_DIR / "facility_validation_medium_grouped_summary.csv"
QUEUE_LOW_OUT = OUT_DIR / "facility_validation_queue_low.csv"
QUEUE_REVIEW_TARGETS_ALL_OUT = OUT_DIR / "facility_validation_review_targets_all.csv"
QUEUE_REVIEW_TARGETS_ALL_SUMMARY_OUT = OUT_DIR / "facility_validation_review_targets_all_summary.csv"
QUEUE_REVIEW_TARGETS_OUT = OUT_DIR / "facility_validation_review_targets_p1_p2.csv"
QUEUE_REVIEW_TARGETS_SUMMARY_OUT = OUT_DIR / "facility_validation_review_targets_p1_p2_summary.csv"
QUEUE_HAEUNDAE_OUT = OUT_DIR / "facility_validation_queue_haeundae.csv"
QUEUE_HAEUNDAE_HIGH_OUT = OUT_DIR / "facility_validation_queue_haeundae_high.csv"
DISTRICT_HIGH_DIR = OUT_DIR / "district_high"
DISTRICT_SUMMARY_OUT = OUT_DIR / "facility_validation_district_summary.csv"
SUMMARY_OUT = OUT_DIR / "facility_validation_summary.json"

HAEUNDAE = "해운대구"

INTERNAL_TOILET_KEYWORDS = [
    "빌딩",
    "타워",
    "은행",
    "주유소",
    "아파트",
    "호텔",
    "병원",
    "의원",
    "학교",
    "대학교",
    "유치원",
    "교회",
    "성당",
    "사찰",
]

PUBLIC_TOILET_KEEP_HINTS = [
    "공원",
    "해수욕장",
    "광장",
    "유원지",
    "공영주차장",
    "주민센터",
    "행정복지센터",
    "구청",
    "시청",
    "도서관",
    "복지관",
    "시장",
    "지하상가",
    "지하도상가",
    "관광",
]

GENERIC_NAMES_BY_CATEGORY = {
    "화장실": ["공중화장실", "화장실"],
    "음식·카페": ["일반음식점", "휴게음식점·제과점", "휴게음식점·제과점 등"],
    "의료·보건": [
        "의원·치과의원·한의원·조산소·산후조리원",
        "병원·치과병원·한방병원·정신병원·요양병원",
        "종합병원",
        "보건소",
    ],
    "복지·돌봄": [
        "노인복지시설",
        "이외 사회복지시설",
        "장애인복지시설",
        "아동복지시설",
        "경로당",
    ],
    "숙박": ["일반숙박시설", "관광숙박시설", "생활숙박시설"],
}

PLACEHOLDER_NAME_KEYWORDS = [
    "일반음식점",
    "휴게음식점",
    "의원·치과의원",
    "병원·치과병원",
    "노인복지시설",
    "사회복지시설",
    "일반숙박시설",
    "관광숙박시설",
    "생활숙박시설",
]

FIELDNAMES = [
    "validation_priority",
    "recommended_action",
    "validation_types",
    "validation_reasons",
    "place_key",
    "source_dataset",
    "source_place_id",
    "place_name",
    "ui_category",
    "raw_category",
    "source_category",
    "district_gu",
    "address",
    "latitude",
    "longitude",
    "accessibility_count",
    "accessibility_type_labels",
    "roadview_url",
    "map_url",
    "review_status",
    "review_note",
]

FIRST_PASS_FIELDNAMES = [
    *FIELDNAMES,
    "first_pass_decision",
    "first_pass_reason",
]

DISTRICT_SUMMARY_FIELDNAMES = [
    "district_gu",
    "total",
    "priority_high",
    "priority_medium",
    "priority_low",
    "high_exclude_candidate",
    "high_exclude_or_rename",
    "high_rename_candidate",
    "high_location_review",
    "high_policy_review",
    "high_keep_sample",
    "high_toilet",
    "high_food_cafe",
    "high_medical_health",
    "high_welfare_care",
]

MEDIUM_GROUPED_FIELDNAMES = [
    "group_key",
    "ui_category",
    "recommended_action",
    "validation_types",
    "count",
    "decision_hint",
    "example_names",
]

REVIEW_TARGET_FIELDNAMES = [
    *FIELDNAMES,
    "auto_decision",
    "needs_visual_check",
    "check_reason",
]

REVIEW_TARGET_SUMMARY_FIELDNAMES = [
    "auto_decision",
    "needs_visual_check",
    "count",
    "description",
]


def has_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def is_generic_name(row: dict[str, str]) -> bool:
    name = (row.get("place_name") or "").strip()
    raw_category = (row.get("raw_category") or "").strip()
    ui_category = row.get("ui_category") or ""
    if not name:
        return True
    if raw_category and name == raw_category:
        return True
    if name in GENERIC_NAMES_BY_CATEGORY.get(ui_category, []):
        return True
    return any(keyword in name for keyword in PLACEHOLDER_NAME_KEYWORDS)


def is_internal_toilet_candidate(row: dict[str, str]) -> bool:
    name = row.get("place_name", "")
    raw_category = row.get("raw_category", "")
    address = row.get("address", "")
    name_text = " ".join([name, raw_category])
    if has_any(name_text, INTERNAL_TOILET_KEYWORDS):
        return True

    # Address-only keywords are weak. Use them only when the place name itself
    # is generic, otherwise public facilities inside apartment blocks get caught.
    if is_generic_name(row) and has_any(address, INTERNAL_TOILET_KEYWORDS):
        return True

    return False


def roadview_url(row: dict[str, str]) -> str:
    return f"https://map.kakao.com/link/roadview/{row['latitude']},{row['longitude']}"


def map_url(row: dict[str, str]) -> str:
    return f"https://map.kakao.com/link/map/{row['place_name']},{row['latitude']},{row['longitude']}"


def district_label(row: dict[str, str]) -> str:
    return (row.get("district_gu") or "").strip() or "구군미분류"


def safe_filename(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in value)


def classify(row: dict[str, str]) -> dict[str, str]:
    ui_category = row.get("ui_category", "")
    name = row.get("place_name", "")
    raw_category = row.get("raw_category", "")
    address = row.get("address", "")
    accessibility_count = int(row.get("accessibility_count") or 0)
    text = " ".join([name, raw_category, address])
    score = 0
    validation_types: list[str] = []
    reasons: list[str] = []
    recommended_action = "KEEP_SAMPLE"

    if ui_category == "화장실":
        if is_internal_toilet_candidate(row):
            score += 100
            validation_types.append("INTERNAL_TOILET_CANDIDATE")
            reasons.append("빌딩/은행/주유소/아파트/호텔/병원/학교/종교시설 등 내부 화장실 가능성")
            recommended_action = "EXCLUDE_CANDIDATE"
        elif has_any(text, PUBLIC_TOILET_KEEP_HINTS):
            score += 20
            validation_types.append("PUBLIC_TOILET_KEEP_SAMPLE")
            reasons.append("공원/공공기관/시장/지하상가 등 공공 이용 가능성이 높은 화장실")
        else:
            score += 45
            validation_types.append("TOILET_USAGE_REVIEW")
            reasons.append("공공 이용 가능성 확인 필요")

        if is_generic_name(row):
            score += 35
            validation_types.append("NAME_TOO_GENERIC")
            reasons.append("장소명이 일반명이라 주변 장소명을 붙일 필요가 있음")
            if recommended_action != "EXCLUDE_CANDIDATE":
                recommended_action = "RENAME_CANDIDATE"

    elif ui_category == "음식·카페":
        if is_generic_name(row):
            score += 100
            validation_types.append("NAME_TOO_GENERIC")
            reasons.append("음식점 상호명이 아니라 업종명만 있음")
            recommended_action = "EXCLUDE_OR_RENAME"
        else:
            score += 35
            validation_types.append("PLACE_EXISTS_REVIEW")
            reasons.append("실제 상호/좌표 확인 필요")

    elif ui_category == "의료·보건":
        if is_generic_name(row):
            score += 85
            validation_types.append("NAME_TOO_GENERIC")
            reasons.append("의료기관명이 아니라 시설 유형명일 가능성")
            recommended_action = "RENAME_CANDIDATE"
        elif raw_category in {"종합병원", "보건소"}:
            score += 20
            validation_types.append("KEEP_SAMPLE")
            reasons.append("공공성/목적지성이 높은 의료시설")
        else:
            score += 35
            validation_types.append("PLACE_EXISTS_REVIEW")
            reasons.append("의원급 실제 존재 여부 확인")

    elif ui_category == "복지·돌봄":
        if is_generic_name(row):
            score += 75
            validation_types.append("NAME_TOO_GENERIC")
            reasons.append("복지시설명이 아니라 시설 유형명일 가능성")
            recommended_action = "RENAME_CANDIDATE"
        if raw_category == "경로당":
            score += 45
            validation_types.append("POLICY_REVIEW")
            reasons.append("경로당을 일반 목적지로 보여줄지 정책 결정 필요")
            if recommended_action == "KEEP_SAMPLE":
                recommended_action = "POLICY_REVIEW"
        if score == 0:
            score += 30
            validation_types.append("PLACE_EXISTS_REVIEW")
            reasons.append("시설명/좌표 확인 필요")

    elif ui_category == "행정·공공기관":
        score += 20
        validation_types.append("KEEP_SAMPLE")
        reasons.append("공공 이용 가능성이 높아 위치/명칭 샘플 확인")

    elif ui_category == "숙박":
        if is_generic_name(row):
            score += 80
            validation_types.append("NAME_TOO_GENERIC")
            reasons.append("숙박시설명이 아니라 시설 유형명일 가능성")
            recommended_action = "RENAME_CANDIDATE"
        else:
            score += 30
            validation_types.append("PLACE_EXISTS_REVIEW")
            reasons.append("실제 숙박시설명/좌표 확인 필요")

    elif ui_category == "전동보장구 충전소":
        score += 55
        validation_types.append("DESTINATION_LOCATION_REVIEW")
        reasons.append("목적지는 명확하지만 실물이 작아 좌표/시설 내부 위치 확인 필요")

    elif ui_category == "관광지":
        score += 25
        validation_types.append("REPRESENTATIVE_POINT_REVIEW")
        reasons.append("관광지 범위가 넓을 수 있어 대표 좌표 적절성 확인")

    if accessibility_count >= 4:
        score += 15
        validation_types.append("MANY_ACCESSIBILITY_FEATURES")
        reasons.append("접근성 속성이 많아 잘못 표시될 경우 영향이 큼")

    if not row.get("district_gu"):
        score += 60
        validation_types.append("MISSING_DISTRICT")
        reasons.append("주소에서 구군을 판별하지 못함")
        if recommended_action == "KEEP_SAMPLE":
            recommended_action = "LOCATION_REVIEW"

    if score >= 100:
        priority = "1_높음"
    elif score >= 55:
        priority = "2_중간"
    else:
        priority = "3_낮음"

    return {
        "validation_priority": priority,
        "recommended_action": recommended_action,
        "validation_types": "|".join(dict.fromkeys(validation_types)),
        "validation_reasons": "|".join(dict.fromkeys(reasons)),
    }


def to_queue_row(row: dict[str, str]) -> dict[str, str]:
    classification = classify(row)
    return {
        **classification,
        "place_key": row["place_key"],
        "source_dataset": row["source_dataset"],
        "source_place_id": row["source_place_id"],
        "place_name": row["place_name"],
        "ui_category": row["ui_category"],
        "raw_category": row["raw_category"],
        "source_category": row["source_category"],
        "district_gu": row["district_gu"],
        "address": row["address"],
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "accessibility_count": row["accessibility_count"],
        "accessibility_type_labels": row["accessibility_type_labels"],
        "roadview_url": roadview_url(row),
        "map_url": map_url(row),
        "review_status": "",
        "review_note": "",
    }


def sort_key(row: dict[str, str]) -> tuple:
    priority_rank = {"1_높음": 0, "2_중간": 1, "3_낮음": 2}
    action_rank = {
        "EXCLUDE_CANDIDATE": 0,
        "EXCLUDE_OR_RENAME": 1,
        "RENAME_CANDIDATE": 2,
        "POLICY_REVIEW": 3,
        "LOCATION_REVIEW": 4,
        "KEEP_SAMPLE": 5,
    }
    return (
        priority_rank.get(row["validation_priority"], 9),
        action_rank.get(row["recommended_action"], 9),
        row["ui_category"],
        row["district_gu"],
        row["place_name"],
    )


def first_pass_decision(row: dict[str, str]) -> dict[str, str]:
    if row["ui_category"] == "화장실" and row["recommended_action"] == "EXCLUDE_CANDIDATE":
        return {
            "first_pass_decision": "LIKELY_EXCLUDE",
            "first_pass_reason": "주유소/빌딩/아파트/병원 등 내부 화장실 가능성이 높아 서비스 목적지 화장실에서는 제외 후보",
        }

    if row["ui_category"] == "음식·카페" and row["recommended_action"] == "EXCLUDE_OR_RENAME":
        return {
            "first_pass_decision": "EXCLUDE_UNLESS_NAME_MATCHED",
            "first_pass_reason": "상호명이 없고 일반음식점 업종명만 있어 장소로 노출 불가. 실제 상호를 복구하지 못하면 제외",
        }

    if row["recommended_action"] == "RENAME_CANDIDATE":
        return {
            "first_pass_decision": "RENAME_OR_EXCLUDE",
            "first_pass_reason": "실제 시설명이 아니라 시설 유형명만 있어 원본에서 시설명 복구 필요. 복구 불가 시 제외",
        }

    if row["recommended_action"] == "LOCATION_REVIEW":
        return {
            "first_pass_decision": "LOCATION_REVIEW",
            "first_pass_reason": "주소 또는 구군 판별이 약해 위치 확인 필요",
        }

    return {
        "first_pass_decision": "MANUAL_REVIEW",
        "first_pass_reason": "지도/로드뷰로 위치와 실제 목적지성을 확인",
    }


def to_first_pass_row(row: dict[str, str]) -> dict[str, str]:
    return {
        **row,
        **first_pass_decision(row),
    }


def review_target_decision(row: dict[str, str]) -> dict[str, str]:
    ui_category = row["ui_category"]
    action = row["recommended_action"]
    validation_types = row["validation_types"]

    if ui_category == "음식·카페" and action == "EXCLUDE_OR_RENAME":
        return {
            "auto_decision": "NAME_DATA_INVALID",
            "needs_visual_check": "N",
            "check_reason": "상호명이 아니라 업종명만 있어 로드뷰로 존재를 확인해도 서비스 장소명으로 사용할 수 없음",
        }

    if action == "RENAME_CANDIDATE":
        return {
            "auto_decision": "NEEDS_SOURCE_NAME_RECOVERY",
            "needs_visual_check": "N",
            "check_reason": "실제 시설명이 아니라 유형명만 있어 원본/주소 기반 이름 복구가 먼저 필요함",
        }

    if ui_category == "화장실" and action == "EXCLUDE_CANDIDATE":
        return {
            "auto_decision": "INTERNAL_TOILET_POLICY_REVIEW",
            "needs_visual_check": "Y",
            "check_reason": "주유소/빌딩/아파트/병원 등 내부 화장실 가능성이 높아 서비스에서 제외할지 정책 확인 필요",
        }

    if ui_category == "화장실":
        return {
            "auto_decision": "PUBLIC_TOILET_VISUAL_REVIEW",
            "needs_visual_check": "Y",
            "check_reason": "공공 이용 가능성과 위치 적절성을 지도/로드뷰로 확인 필요",
        }

    if ui_category == "전동보장구 충전소":
        return {
            "auto_decision": "KEEP_BUT_LOCATION_SAMPLE_REVIEW",
            "needs_visual_check": "Y",
            "check_reason": "서비스 목적지로 유지하되 좌표가 충전기 위치인지 건물 대표점인지 샘플 확인 필요",
        }

    if ui_category == "복지·돌봄" and "POLICY_REVIEW" in validation_types:
        return {
            "auto_decision": "WELFARE_POLICY_REVIEW",
            "needs_visual_check": "N",
            "check_reason": "경로당을 일반 목적지로 노출할지 서비스 정책 결정이 먼저 필요함",
        }

    if action == "LOCATION_REVIEW":
        return {
            "auto_decision": "LOCATION_VISUAL_REVIEW",
            "needs_visual_check": "Y",
            "check_reason": "구군/위치 판별이 약해 지도 확인 필요",
        }

    if row["validation_priority"] == "3_낮음":
        return {
            "auto_decision": "POI_MATCH_REVIEW",
            "needs_visual_check": "N",
            "check_reason": "우선순위는 낮지만 POI 매칭으로 이름/좌표/카테고리 일치 여부 확인",
        }

    return {
        "auto_decision": "MANUAL_REVIEW",
        "needs_visual_check": "Y",
        "check_reason": "자동 룰로 충분하지 않아 지도/로드뷰 확인 필요",
    }


def to_review_target_row(row: dict[str, str]) -> dict[str, str]:
    return {
        **row,
        **review_target_decision(row),
    }


def to_review_target_summary_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    descriptions = {
        "NAME_DATA_INVALID": "이름 데이터가 서비스 노출용 장소명으로 부적합",
        "NEEDS_SOURCE_NAME_RECOVERY": "원본/주소 기반 실제 시설명 복구 필요",
        "INTERNAL_TOILET_POLICY_REVIEW": "내부 화장실 가능성이 높아 서비스 정책 판단 필요",
        "PUBLIC_TOILET_VISUAL_REVIEW": "공공 화장실로 유지 가능한지 지도/로드뷰 확인 필요",
        "KEEP_BUT_LOCATION_SAMPLE_REVIEW": "유지하되 좌표 품질 샘플 확인 필요",
        "WELFARE_POLICY_REVIEW": "복지시설 노출 정책 판단 필요",
        "LOCATION_VISUAL_REVIEW": "좌표/구군 확인 필요",
        "MANUAL_REVIEW": "수동 확인 필요",
    }
    grouped = Counter((row["auto_decision"], row["needs_visual_check"]) for row in rows)
    return [
        {
            "auto_decision": auto_decision,
            "needs_visual_check": needs_visual_check,
            "count": str(count),
            "description": descriptions.get(auto_decision, ""),
        }
        for (auto_decision, needs_visual_check), count in sorted(
            grouped.items(),
            key=lambda item: (-item[1], item[0][1], item[0][0]),
        )
    ]


def to_district_summary_rows(queue_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    districts = sorted({district_label(row) for row in queue_rows})

    for district in districts:
        district_rows = [row for row in queue_rows if district_label(row) == district]
        high_rows = [row for row in district_rows if row["validation_priority"] == "1_높음"]
        priority_counts = Counter(row["validation_priority"] for row in district_rows)
        high_action_counts = Counter(row["recommended_action"] for row in high_rows)
        high_category_counts = Counter(row["ui_category"] for row in high_rows)

        rows.append(
            {
                "district_gu": district,
                "total": str(len(district_rows)),
                "priority_high": str(priority_counts.get("1_높음", 0)),
                "priority_medium": str(priority_counts.get("2_중간", 0)),
                "priority_low": str(priority_counts.get("3_낮음", 0)),
                "high_exclude_candidate": str(high_action_counts.get("EXCLUDE_CANDIDATE", 0)),
                "high_exclude_or_rename": str(high_action_counts.get("EXCLUDE_OR_RENAME", 0)),
                "high_rename_candidate": str(high_action_counts.get("RENAME_CANDIDATE", 0)),
                "high_location_review": str(high_action_counts.get("LOCATION_REVIEW", 0)),
                "high_policy_review": str(high_action_counts.get("POLICY_REVIEW", 0)),
                "high_keep_sample": str(high_action_counts.get("KEEP_SAMPLE", 0)),
                "high_toilet": str(high_category_counts.get("화장실", 0)),
                "high_food_cafe": str(high_category_counts.get("음식·카페", 0)),
                "high_medical_health": str(high_category_counts.get("의료·보건", 0)),
                "high_welfare_care": str(high_category_counts.get("복지·돌봄", 0)),
            }
        )

    return rows


def medium_decision_hint(row: dict[str, str]) -> str:
    ui_category = row["ui_category"]
    validation_types = row["validation_types"]
    recommended_action = row["recommended_action"]

    if ui_category == "전동보장구 충전소":
        return "서비스 목적지로 유지하되 좌표가 건물 대표점인지 충전기 위치인지 샘플 확인"
    if ui_category == "복지·돌봄" and "POLICY_REVIEW" in validation_types:
        return "경로당을 일반 목적지로 노출할지 정책 결정 필요"
    if ui_category == "화장실":
        return "공공 이용 가능성 기준 확인 후 유지/이름보정 결정"
    if recommended_action == "RENAME_CANDIDATE":
        return "실제 시설명 복구 가능 여부 확인"
    if ui_category == "숙박":
        return "숙박시설명을 복구할 수 있으면 유지, 유형명만 있으면 제외 후보"
    return "샘플 확인 후 같은 유형은 일괄 기준 적용"


def to_medium_grouped_summary_rows(medium_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    groups: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for row in medium_rows:
        groups[(row["ui_category"], row["recommended_action"], row["validation_types"])].append(row)

    rows: list[dict[str, str]] = []
    for (ui_category, recommended_action, validation_types), group_rows in sorted(
        groups.items(),
        key=lambda item: (-len(item[1]), item[0][0], item[0][1], item[0][2]),
    ):
        example_names = []
        for row in group_rows:
            name = row["place_name"]
            if name not in example_names:
                example_names.append(name)
            if len(example_names) >= 5:
                break

        rows.append(
            {
                "group_key": f"{ui_category}::{recommended_action}::{validation_types}",
                "ui_category": ui_category,
                "recommended_action": recommended_action,
                "validation_types": validation_types,
                "count": str(len(group_rows)),
                "decision_hint": medium_decision_hint(group_rows[0]),
                "example_names": " | ".join(example_names),
            }
        )

    return rows


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str] = FIELDNAMES) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    DISTRICT_HIGH_DIR.mkdir(parents=True, exist_ok=True)
    with ADOPTED_PLACES.open("r", encoding="utf-8-sig", newline="") as file:
        source_rows = list(csv.DictReader(file))

    queue_rows = [to_queue_row(row) for row in source_rows]
    queue_rows.sort(key=sort_key)
    high_rows = [row for row in queue_rows if row["validation_priority"] == "1_높음"]
    high_first_pass_rows = [to_first_pass_row(row) for row in high_rows]
    medium_rows = [row for row in queue_rows if row["validation_priority"] == "2_중간"]
    medium_grouped_summary_rows = to_medium_grouped_summary_rows(medium_rows)
    low_rows = [row for row in queue_rows if row["validation_priority"] == "3_낮음"]
    review_target_rows = [to_review_target_row(row) for row in [*high_rows, *medium_rows]]
    review_target_summary_rows = to_review_target_summary_rows(review_target_rows)
    all_review_target_rows = [to_review_target_row(row) for row in queue_rows]
    all_review_target_summary_rows = to_review_target_summary_rows(all_review_target_rows)
    haeundae_rows = [row for row in queue_rows if row["district_gu"] == HAEUNDAE]
    haeundae_high_rows = [row for row in haeundae_rows if row["validation_priority"] == "1_높음"]
    district_summary_rows = to_district_summary_rows(queue_rows)

    write_csv(QUEUE_ALL_OUT, queue_rows)
    write_csv(QUEUE_HIGH_OUT, high_rows)
    write_csv(QUEUE_HIGH_FIRST_PASS_OUT, high_first_pass_rows, FIRST_PASS_FIELDNAMES)
    write_csv(QUEUE_MEDIUM_OUT, medium_rows)
    write_csv(QUEUE_MEDIUM_GROUPED_OUT, medium_grouped_summary_rows, MEDIUM_GROUPED_FIELDNAMES)
    write_csv(QUEUE_LOW_OUT, low_rows)
    write_csv(QUEUE_REVIEW_TARGETS_OUT, review_target_rows, REVIEW_TARGET_FIELDNAMES)
    write_csv(QUEUE_REVIEW_TARGETS_SUMMARY_OUT, review_target_summary_rows, REVIEW_TARGET_SUMMARY_FIELDNAMES)
    write_csv(QUEUE_REVIEW_TARGETS_ALL_OUT, all_review_target_rows, REVIEW_TARGET_FIELDNAMES)
    write_csv(QUEUE_REVIEW_TARGETS_ALL_SUMMARY_OUT, all_review_target_summary_rows, REVIEW_TARGET_SUMMARY_FIELDNAMES)
    write_csv(QUEUE_HAEUNDAE_OUT, haeundae_rows)
    write_csv(QUEUE_HAEUNDAE_HIGH_OUT, haeundae_high_rows)
    write_csv(DISTRICT_SUMMARY_OUT, district_summary_rows, DISTRICT_SUMMARY_FIELDNAMES)

    for district in sorted({district_label(row) for row in high_rows}):
        district_high_rows = [row for row in high_rows if district_label(row) == district]
        write_csv(DISTRICT_HIGH_DIR / f"facility_validation_high_{safe_filename(district)}.csv", district_high_rows)

    summary = {
        "total": len(queue_rows),
        "highTotal": len(high_rows),
        "haeundaeTotal": len(haeundae_rows),
        "priorityCounts": dict(Counter(row["validation_priority"] for row in queue_rows)),
        "recommendedActionCounts": dict(Counter(row["recommended_action"] for row in queue_rows)),
        "highRecommendedActionCounts": dict(Counter(row["recommended_action"] for row in high_rows)),
        "highFirstPassDecisionCounts": dict(Counter(row["first_pass_decision"] for row in high_first_pass_rows)),
        "mediumTotal": len(medium_rows),
        "mediumRecommendedActionCounts": dict(Counter(row["recommended_action"] for row in medium_rows)),
        "mediumCategoryCounts": dict(Counter(row["ui_category"] for row in medium_rows)),
        "reviewTargetTotal": len(review_target_rows),
        "reviewTargetVisualCheckCounts": dict(Counter(row["needs_visual_check"] for row in review_target_rows)),
        "reviewTargetAutoDecisionCounts": dict(Counter(row["auto_decision"] for row in review_target_rows)),
        "lowTotal": len(low_rows),
        "allReviewTargetTotal": len(all_review_target_rows),
        "allReviewTargetVisualCheckCounts": dict(Counter(row["needs_visual_check"] for row in all_review_target_rows)),
        "allReviewTargetAutoDecisionCounts": dict(Counter(row["auto_decision"] for row in all_review_target_rows)),
        "categoryPriorityCounts": {
            category: dict(Counter(row["validation_priority"] for row in queue_rows if row["ui_category"] == category))
            for category in sorted({row["ui_category"] for row in queue_rows})
        },
        "districtHighCounts": {
            row["district_gu"]: int(row["priority_high"])
            for row in district_summary_rows
        },
        "haeundaePriorityCounts": dict(Counter(row["validation_priority"] for row in haeundae_rows)),
        "haeundaeRecommendedActionCounts": dict(Counter(row["recommended_action"] for row in haeundae_rows)),
        "haeundaeHighTotal": len(haeundae_high_rows),
        "haeundaeHighRecommendedActionCounts": dict(Counter(row["recommended_action"] for row in haeundae_high_rows)),
        "files": {
            "all": str(QUEUE_ALL_OUT),
            "high": str(QUEUE_HIGH_OUT),
            "highFirstPass": str(QUEUE_HIGH_FIRST_PASS_OUT),
            "medium": str(QUEUE_MEDIUM_OUT),
            "mediumGroupedSummary": str(QUEUE_MEDIUM_GROUPED_OUT),
            "low": str(QUEUE_LOW_OUT),
            "reviewTargetsP1P2": str(QUEUE_REVIEW_TARGETS_OUT),
            "reviewTargetsP1P2Summary": str(QUEUE_REVIEW_TARGETS_SUMMARY_OUT),
            "reviewTargetsAll": str(QUEUE_REVIEW_TARGETS_ALL_OUT),
            "reviewTargetsAllSummary": str(QUEUE_REVIEW_TARGETS_ALL_SUMMARY_OUT),
            "districtHighDir": str(DISTRICT_HIGH_DIR),
            "districtSummary": str(DISTRICT_SUMMARY_OUT),
            "haeundae": str(QUEUE_HAEUNDAE_OUT),
            "haeundaeHigh": str(QUEUE_HAEUNDAE_HIGH_OUT),
        },
    }
    SUMMARY_OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
