from __future__ import annotations

import csv
import json
import re
from collections import Counter
from pathlib import Path


POC_ROOT = Path(__file__).resolve().parents[1]
FINAL_DIR = POC_ROOT / "data" / "final" / "facilities"
VALIDATION_DIR = POC_ROOT / "data" / "reports" / "facility_validation"

FINAL_ADOPTED = FINAL_DIR / "adopted_places_with_accessibility_final.csv"
QUALITY_CANDIDATES = VALIDATION_DIR / "facility_display_quality_expanded_candidates.csv"
CROSS_VALIDATION = VALIDATION_DIR / "facility_cross_validation_all.csv"
OUT_PLAN = VALIDATION_DIR / "facility_restaurant_structural_name_plan.csv"
OUT_SUMMARY = VALIDATION_DIR / "facility_restaurant_structural_name_plan_summary.json"


STRUCTURAL_TERMS = ["빌딩", "건물", "건축물", "상가", "타워", "오피스텔", "아파트", "맨션", "빌라", "주택", "근생"]
GENERIC_NAMES = {"일반음식점", "휴게음식점", "제과점", "음식점", "카페", "상가", "빌딩"}

FOOD_CATEGORY_TERMS = [
    "음식점",
    "음식점업",
    "카페",
    "커피",
    "술집",
    "주점",
    "호프",
    "제과",
    "베이커리",
    "분식",
]

FOOD_NAME_TERMS = [
    "식당",
    "횟집",
    "한우",
    "갈비",
    "국밥",
    "밀면",
    "냉면",
    "초밥",
    "스시",
    "카츠",
    "돈까스",
    "분식",
    "카페",
    "커피",
    "베이커리",
    "제과",
    "김밥",
    "치킨",
    "피자",
    "족발",
    "보쌈",
    "돼지",
    "밥집",
    "밥상",
    "주점",
    "포차",
    "호프",
    "양꼬치",
    "중식",
    "반점",
]

NON_FOOD_TERMS = [
    "스터디카페",
    "만화카페",
    "공인중개사",
    "부동산",
    "약국",
    "병원",
    "의원",
    "치과",
    "한의원",
    "학원",
    "교습소",
    "센터",
    "헬스",
    "필라테스",
    "노래",
    "노래방",
    "당구",
    "PC",
    "피씨",
    "게임",
    "만화방",
    "미용",
    "헤어",
    "세탁",
    "마트",
    "슈퍼",
    "편의점",
    "은행",
    "멘토즈",
    "작심",
    "르하임",
]

NON_FOOD_CATEGORY_TERMS = [
    "스터디카페",
    "스터디룸",
    "만화카페",
    "만화방",
    "공간대여",
    "서비스,산업",
    "교육",
    "학문",
    "부동산",
    "전기차 충전소",
    "주차장",
    "미용",
    "여가시설",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def to_float(value: str, default: float = 999999.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize(value: str) -> str:
    return re.sub(r"\s+", "", value or "").strip().lower()


def has_any(value: str, terms: list[str]) -> bool:
    compact = normalize(value)
    return any(normalize(term) in compact for term in terms)


def is_structural_name(name: str) -> bool:
    return has_any(name, STRUCTURAL_TERMS)


def is_non_food_name(name: str) -> bool:
    return has_any(name, NON_FOOD_TERMS)


def is_food_category(category: str) -> bool:
    if has_any(category, NON_FOOD_CATEGORY_TERMS):
        return False
    return has_any(category, FOOD_CATEGORY_TERMS)


def is_food_name(name: str) -> bool:
    return has_any(name, FOOD_NAME_TERMS) and not is_non_food_name(name)


def name_similarity(a: str, b: str) -> float:
    left = set(normalize(a))
    right = set(normalize(b))
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def clean_candidate_name(name: str, current_name: str) -> list[tuple[str, str]]:
    raw = (name or "").strip()
    if not raw:
        return []
    raw = re.sub(r"\s*외\s*\d+\s*개\s*$", "", raw).strip()
    candidates: list[tuple[str, str]] = [(raw, "raw")]
    for part in re.split(r"[/|,]", raw):
        part = part.strip()
        part = re.sub(r"\s*외\s*\d+\s*개\s*$", "", part).strip()
        if part and part != raw:
            candidates.append((part, "split"))
    for part in re.findall(r"\(([^()]+)\)", current_name or ""):
        part = part.strip()
        part = re.sub(r"\s*외\s*\d+\s*개\s*$", "", part).strip()
        if part:
            candidates.append((part, "current_parentheses"))

    deduped: list[tuple[str, str]] = []
    seen = set()
    for candidate, source in candidates:
        key = normalize(candidate)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append((candidate, source))
    return deduped


def candidate_options(row: dict[str, str]) -> list[dict[str, str | float]]:
    current = row["place_name"]
    options: list[dict[str, str | float]] = []
    sources = [
        {
            "source": "KAKAO",
            "name": row.get("kakao_place_name", ""),
            "category": row.get("kakao_category", ""),
            "distance": to_float(row.get("kakao_distance_m", "")),
            "status": row.get("kakao_best_status", ""),
        },
        {
            "source": "POI",
            "name": row.get("poi_name", ""),
            "category": row.get("poi_category_label", ""),
            "distance": to_float(row.get("poi_distance_m", "")),
            "status": row.get("poi_match_status", ""),
        },
    ]
    for source in sources:
        for name, name_source in clean_candidate_name(str(source["name"]), current):
            if normalize(name) == normalize(current):
                continue
            if name in GENERIC_NAMES:
                continue
            if is_structural_name(name):
                continue
            if is_non_food_name(name):
                continue

            food_category = is_food_category(str(source["category"]))
            food_name = is_food_name(name)
            distance = float(source["distance"])
            strong = str(source["status"]) in {"KAKAO_STRONG", "MATCH_STRONG"}
            if distance > 50:
                continue
            if not food_category and not (food_name and distance <= 10 and strong):
                continue

            score = 0.0
            if food_category:
                score += 55
            if food_name:
                score += 25
            if distance <= 5:
                score += 20
            elif distance <= 10:
                score += 16
            elif distance <= 30:
                score += 10
            if strong:
                score += 10
            if name_source == "split":
                score += 6
            if name_source == "current_parentheses":
                score += 4
            score += name_similarity(name, current) * 10

            options.append(
                {
                    "candidateName": name,
                    "candidateSource": str(source["source"]),
                    "candidateNameSource": name_source,
                    "candidateCategory": str(source["category"]),
                    "candidateDistanceM": distance,
                    "candidateStatus": str(source["status"]),
                    "candidateScore": round(score, 2),
                }
            )
    merged: dict[str, dict[str, str | float]] = {}
    for option in options:
        key = normalize(str(option["candidateName"]))
        existing = merged.get(key)
        if not existing or float(option["candidateScore"]) > float(existing["candidateScore"]):
            merged[key] = option
        elif existing:
            existing["candidateSource"] = f"{existing['candidateSource']}+{option['candidateSource']}"
            existing["candidateScore"] = round(float(existing["candidateScore"]) + 8, 2)
    return sorted(merged.values(), key=lambda item: float(item["candidateScore"]), reverse=True)


def strong_non_food_or_structural_evidence(row: dict[str, str]) -> bool:
    close_kakao = to_float(row.get("kakao_distance_m", "")) <= 20 and row.get("kakao_best_status") == "KAKAO_STRONG"
    close_poi = to_float(row.get("poi_distance_m", "")) <= 20 and row.get("poi_match_status") == "MATCH_STRONG"
    category_text = f"{row.get('kakao_category', '')} {row.get('poi_category_label', '')}"
    buildingish = has_any(category_text, ["부동산", "빌딩", "건물", "건축구조물", "소매업", "교육", "학원"])
    return (close_kakao or close_poi) and buildingish


def has_conflicting_food_candidates(best: dict[str, str | float] | None, second: dict[str, str | float] | None) -> bool:
    if not best or not second:
        return False
    if name_similarity(str(best["candidateName"]), str(second["candidateName"])) >= 0.55:
        return False
    if float(best["candidateDistanceM"]) <= 20 and float(second["candidateDistanceM"]) <= 20:
        return True
    return False


def main() -> None:
    final_rows = read_csv(FINAL_ADOPTED)
    by_place_id = {row["placeId"]: row for row in final_rows}
    cross_rows = read_csv(CROSS_VALIDATION)
    by_source_key = {row["place_key"]: row for row in cross_rows}
    candidate_rows = [
        row
        for row in read_csv(QUALITY_CANDIDATES)
        if row["issueType"] == "RESTAURANT_NAME_LOOKS_STRUCTURAL"
    ]

    output: list[dict[str, str]] = []
    for issue in candidate_rows:
        final_row = by_place_id[issue["placeId"]]
        source_key = final_row["sourceKey"]
        cross = by_source_key.get(source_key)
        if not cross:
            raise ValueError(f"Missing cross validation row: {source_key}")

        options = candidate_options(cross)
        best = options[0] if options else None
        second = options[1] if len(options) > 1 else None

        if best and has_conflicting_food_candidates(best, second):
            action = "REVIEW"
            proposed_name = str(best["candidateName"])
            reason = "가까운 음식점 후보가 둘 이상이라 임의 선택 위험"
        elif best and (not second or float(best["candidateScore"]) - float(second["candidateScore"]) >= 8):
            action = "RENAME"
            proposed_name = str(best["candidateName"])
            reason = "가까운 POI/카카오 음식점 후보가 명확함"
        elif best:
            action = "REVIEW"
            proposed_name = str(best["candidateName"])
            reason = "음식점 후보가 있으나 후보 간 점수 차이가 작아 직접 확인 필요"
        elif strong_non_food_or_structural_evidence(cross):
            action = "EXCLUDE"
            proposed_name = ""
            reason = "가까운 근거가 건물/비음식점으로만 잡혀 음식점 목적지로 부적합"
        else:
            action = "REVIEW"
            proposed_name = ""
            reason = "자동으로 복구할 음식점명이 부족함"

        output.append(
            {
                "action": action,
                "sourceKey": source_key,
                "placeId": final_row["placeId"],
                "currentName": final_row["name"],
                "proposedName": proposed_name,
                "dbCategory": final_row["dbCategory"],
                "address": final_row["address"],
                "districtGu": final_row["districtGu"],
                "reason": reason,
                "bestCandidateSource": str(best["candidateSource"]) if best else "",
                "bestCandidateNameSource": str(best["candidateNameSource"]) if best else "",
                "bestCandidateCategory": str(best["candidateCategory"]) if best else "",
                "bestCandidateDistanceM": str(best["candidateDistanceM"]) if best else "",
                "bestCandidateStatus": str(best["candidateStatus"]) if best else "",
                "bestCandidateScore": str(best["candidateScore"]) if best else "",
                "secondCandidateName": str(second["candidateName"]) if second else "",
                "secondCandidateSource": str(second["candidateSource"]) if second else "",
                "kakaoName": cross.get("kakao_place_name", ""),
                "kakaoCategory": cross.get("kakao_category", ""),
                "kakaoDistanceM": cross.get("kakao_distance_m", ""),
                "poiName": cross.get("poi_name", ""),
                "poiCategory": cross.get("poi_category_label", ""),
                "poiDistanceM": cross.get("poi_distance_m", ""),
            }
        )

    fieldnames = list(output[0].keys())
    write_csv(OUT_PLAN, output, fieldnames)
    summary = {
        "total": len(output),
        "byAction": dict(Counter(row["action"] for row in output)),
        "output": str(OUT_PLAN),
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
