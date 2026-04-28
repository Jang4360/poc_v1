import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(r"C:\Users\SSAFY\Desktop\poc")
FINAL_DIR = ROOT / "data" / "final" / "facilities"
REPORT_DIR = ROOT / "data" / "reports" / "facility_validation"
SOURCE = FINAL_DIR / "adopted_places_with_accessibility_final.csv"
OUT_CSV = REPORT_DIR / "facility_display_quality_expanded_candidates.csv"
OUT_SUMMARY = REPORT_DIR / "facility_display_quality_expanded_summary.json"


STRUCTURAL_TERMS = [
    "빌딩",
    "건물",
    "건축물",
    "상가",
    "타워",
    "오피스텔",
    "아파트",
    "맨션",
    "빌라",
    "주택",
    "근생",
]

GENERIC_EXACT = {
    "공중화장실",
    "화장실",
    "파출소, 지구대",
    "파출소",
    "지구대",
    "일반음식점",
    "휴게음식점",
    "휴게음식점, 제과점",
    "제과점",
    "숙박시설",
    "관광숙박시설",
    "은행",
}

TOILET_INTERNAL_TERMS = [
    "빌딩",
    "상가",
    "아파트",
    "오피스텔",
    "호텔",
    "병원",
    "의원",
    "은행",
    "주유소",
    "학교",
    "교회",
    "성당",
    "사찰",
]

WELFARE_GENERIC_TERMS = [
    "무더위쉼터",
    "한파쉼터",
]


def add_issue(issues, row, issue_type, severity, reason, suggested_action):
    key = (row["placeId"], issue_type)
    if key in issues:
        return
    issues[key] = {
        "severity": severity,
        "issueType": issue_type,
        "placeId": row["placeId"],
        "name": row["name"],
        "dbCategory": row["dbCategory"],
        "address": row["address"],
        "districtGu": row["districtGu"],
        "sourceDataset": row["sourceDataset"],
        "accessibilityTypes": row["accessibilityTypes"],
        "reason": reason,
        "suggestedAction": suggested_action,
    }


def main():
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with SOURCE.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    issues = {}

    by_name_addr = defaultdict(list)
    by_point = defaultdict(list)

    for row in rows:
        name = (row["name"] or "").strip()
        category = row["dbCategory"]
        address = (row["address"] or "").strip()
        source = row["sourceDataset"]
        point = row["point"]

        by_name_addr[(name, address)].append(row)
        by_point[point].append(row)

        if name in GENERIC_EXACT:
            add_issue(
                issues,
                row,
                "GENERIC_DISPLAY_NAME",
                "WARN",
                "표시명이 시설명이 아니라 유형명에 가까움",
                "실제 시설명 복구 또는 제외 판단",
            )

        if any(term in name for term in WELFARE_GENERIC_TERMS):
            add_issue(
                issues,
                row,
                "WELFARE_SHELTER_GENERIC_NAME",
                "WARN",
                "쉼터명은 실제 시설명보다 운영 용도명일 가능성이 큼",
                "실제 경로당/복지시설명으로 보정하거나 제외",
            )

        if category == "RESTAURANT" and any(term in name for term in STRUCTURAL_TERMS):
            add_issue(
                issues,
                row,
                "RESTAURANT_NAME_LOOKS_STRUCTURAL",
                "WARN",
                "음식·카페인데 표시명이 상호가 아니라 건물/구조물명처럼 보임",
                "POI/카카오 기준 실제 상호명 복구 또는 제외",
            )

        if category == "TOILET" and any(term in name for term in TOILET_INTERNAL_TERMS):
            add_issue(
                issues,
                row,
                "TOILET_NAME_LOOKS_INTERNAL_OR_PRIVATE",
                "REVIEW",
                "공중화장실 목적지라기보다 건물/민간시설 내부 화장실처럼 보일 수 있음",
                "공공 개방 화장실인지 확인 후 유지/제외",
            )

        if category == "CHARGING_STATION" and "충전" not in name:
            add_issue(
                issues,
                row,
                "CHARGING_STATION_HOST_FACILITY_NAME",
                "INFO",
                "충전소 자체 명칭이 아니라 설치 장소명으로 표시됨",
                "UI에서 '전동보장구 충전 가능' 같은 배지로 보완",
            )

        if source == "barrier_free_facility" and category == "RESTAURANT":
            add_issue(
                issues,
                row,
                "RESTAURANT_FROM_ACCESSIBILITY_SOURCE",
                "INFO",
                "음식점 원천이 일반 POI가 아니라 장애인편의시설 데이터임",
                "표시명/업종명만 재확인",
            )

    for (_, _), group in by_name_addr.items():
        if len(group) > 1:
            categories = "|".join(sorted({r["dbCategory"] for r in group}))
            ids = "|".join(r["placeId"] for r in group)
            for row in group:
                add_issue(
                    issues,
                    row,
                    "DUPLICATE_NAME_ADDRESS",
                    "WARN",
                    f"동일 이름+주소 {len(group)}건, categories={categories}, ids={ids}",
                    "중복 장소 병합 여부 결정",
                )

    for _, group in by_point.items():
        if len(group) >= 3:
            categories = "|".join(sorted({r["dbCategory"] for r in group}))
            ids = "|".join(r["placeId"] for r in group[:20])
            for row in group:
                add_issue(
                    issues,
                    row,
                    "SAME_POINT_MANY_PLACES",
                    "INFO",
                    f"동일 좌표에 {len(group)}개 장소가 있음, categories={categories}, sampleIds={ids}",
                    "대형 시설 대표점인지 중복인지 확인",
                )

    ordered = sorted(
        issues.values(),
        key=lambda r: (
            {"WARN": 0, "REVIEW": 1, "INFO": 2}.get(r["severity"], 9),
            r["issueType"],
            int(r["placeId"]),
        ),
    )

    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "severity",
                "issueType",
                "placeId",
                "name",
                "dbCategory",
                "address",
                "districtGu",
                "sourceDataset",
                "accessibilityTypes",
                "reason",
                "suggestedAction",
            ],
        )
        writer.writeheader()
        writer.writerows(ordered)

    summary = {
        "source": str(SOURCE),
        "totalPlaces": len(rows),
        "totalIssueRows": len(ordered),
        "bySeverity": dict(Counter(r["severity"] for r in ordered)),
        "byIssueType": dict(Counter(r["issueType"] for r in ordered)),
        "note": "INFO는 반드시 삭제/수정할 대상이 아니라 UI 표시 방식 또는 중복 정책 확인용이다.",
    }
    with OUT_SUMMARY.open("w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
