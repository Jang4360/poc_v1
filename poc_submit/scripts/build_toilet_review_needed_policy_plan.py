from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


POC_ROOT = Path(__file__).resolve().parents[1]
FINAL = POC_ROOT / "data" / "final" / "facilities" / "adopted_places_with_accessibility_final.csv"
REPORT_DIR = POC_ROOT / "data" / "reports" / "facility_validation"
OUT_CSV = REPORT_DIR / "toilet_review_needed_policy_plan.csv"
OUT_SUMMARY = REPORT_DIR / "toilet_review_needed_policy_plan_summary.json"

PUBLIC_TERMS = [
    "공영주차장",
    "주차장",
    "공원",
    "산책로",
    "해안",
    "해변",
    "해수천",
    "물양장",
    "등대",
    "파고라",
    "배수지",
    "고개",
    "야영장",
    "광장",
    "수변",
    "쉼터",
    "백양산",
    "엄광산",
    "범방산",
    "해파랑길",
    "이기대",
    "신선대",
    "동생말",
    "섶자리",
    "암남항",
    "저수지",
    "폭포",
    "선착장",
    "방조제",
    "녹지",
    "묘지",
    "자전거도로",
    "동산",
    "솔밭",
    "오랑대",
    "왜성",
    "해맞이",
    "입구",
    "길",
]

FACILITY_TERMS = [
    "보훈청",
    "전화국",
    "문화",
    "사업본부",
    "사업소",
    "기상청",
    "우편",
    "수련관",
    "한국전력",
    "토지주택공사",
    "부동산원",
    "도시공사",
    "공사",
    "플랫폼",
    "트래블라운지",
    "혈액원",
    "국악원",
    "보호작업장",
    "학습관",
    "시니어클럽",
    "전시관",
    "게이트볼장",
    "사격장",
    "체육",
    "회관",
    "센터",
    "복지",
    "청소년",
    "운동장",
    "관리",
    "도서관",
    "구청",
    "학교",
    "장애인",
    "현장민원실",
    "복합청사",
    "교육지원청",
    "운전면허시험장",
    "빙상장",
    "휴게소",
    "로파크",
    "여성가족개발원",
    "교육관",
    "등기소",
    "영화촬영스튜디오",
    "검찰청",
    "법원",
    "유스호스텔",
    "영업소",
    "연수원",
    "연구소",
    "보건지소",
    "보건진료소",
    "보육원",
    "야구장",
    "과학관",
    "판매장",
    "경로식당",
    "노인대학",
    "경비동",
    "체험장",
    "구조대",
    "월드컵빌리지",
    "민속관",
    "과학원",
]

REMOVE_TERMS = [
    "홈플러스",
    "신협",
    "무인카페",
    "카페",
    "파크타워",
    "유니크스테이",
    "프라자",
    "엑센시티",
    "지오플레이스",
    "전자랜드",
    "블루포트",
    "피아크",
    "마트",
    "모텔",
    "호텔",
    "상가",
    "빌딩",
    "LPG",
    "가스충전소",
    "르노삼성자동차",
    "삼성자동차",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def find_term(text: str, terms: list[str]) -> str:
    for term in terms:
        if term in text:
            return term
    return ""


def classify(row: dict[str, str]) -> tuple[str, str, str, str]:
    name = row["name"]
    address = row["address"]

    if "공중화장실" in address:
        return "PROMOTE_PUBLIC_TOILET", "공중화장실", "주소:공중화장실", "주소에 공중화장실이 명시되어 공중화장실로 흡수 가능"

    remove_term = find_term(name, REMOVE_TERMS)
    if remove_term:
        return "REMOVE_CANDIDATE", "제거 후보", remove_term, "민간/상업시설명으로 공개 화장실 보장 약함"

    public_term = find_term(name, PUBLIC_TERMS)
    facility_term = find_term(name, FACILITY_TERMS)

    if public_term and not facility_term:
        return "PROMOTE_PUBLIC_TOILET", "공중화장실", public_term, "공영주차장/공원/야외 지점 등 공공 접근 가능성이 높음"

    if facility_term:
        return "PROMOTE_FACILITY_TOILET", "시설 내 화장실", facility_term, "공공기관/문화·체육·복지 등 시설 내부 화장실로 보는 것이 자연스러움"

    if public_term:
        return "PROMOTE_PUBLIC_TOILET", "공중화장실", public_term, "야외/공공 구역 기반 화장실로 보는 것이 자연스러움"

    if "화장실" in name:
        return "PROMOTE_FACILITY_TOILET", "시설 내 화장실", "화장실", "명칭에 화장실은 있으나 독립/야외보다 시설 부속 가능성이 큼"

    return "MANUAL_REVIEW", "수동 검토", "", "명칭만으로 공개성/부속성 판단 부족"


def main() -> None:
    rows = [row for row in read_csv(FINAL) if row.get("toiletScope") == "REVIEW_TOILET"]
    classified: list[dict[str, Any]] = []
    for row in rows:
        action, target_label, matched_term, reason = classify(row)
        classified.append(
            {
                "sourceKey": row["sourceKey"],
                "placeId": row["placeId"],
                "name": row["name"],
                "address": row["address"],
                "districtGu": row["districtGu"],
                "sourceDataset": row["sourceDataset"],
                "toiletScope": row["toiletScope"],
                "toiletScopeLabel": row["toiletScopeLabel"],
                "toiletScopeReason": row["toiletScopeReason"],
                "proposedAction": action,
                "proposedTargetLabel": target_label,
                "matchedTerm": matched_term,
                "proposedReason": reason,
            }
        )

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(
        OUT_CSV,
        classified,
        [
            "sourceKey",
            "placeId",
            "name",
            "address",
            "districtGu",
            "sourceDataset",
            "toiletScope",
            "toiletScopeLabel",
            "toiletScopeReason",
            "proposedAction",
            "proposedTargetLabel",
            "matchedTerm",
            "proposedReason",
        ],
    )
    summary = {
        "total": len(classified),
        "byAction": dict(Counter(row["proposedAction"] for row in classified)),
        "byTargetLabel": dict(Counter(row["proposedTargetLabel"] for row in classified)),
        "outputs": {"csv": str(OUT_CSV)},
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for action in ["PROMOTE_PUBLIC_TOILET", "PROMOTE_FACILITY_TOILET", "REMOVE_CANDIDATE", "MANUAL_REVIEW"]:
        subset = [row for row in classified if row["proposedAction"] == action]
        print(f"\n[{action}] {len(subset)}")
        for row in subset[:25]:
            print(f"- {row['name']} | {row['matchedTerm']} | {row['districtGu']}")


if __name__ == "__main__":
    main()
