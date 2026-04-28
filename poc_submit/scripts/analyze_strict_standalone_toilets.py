from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path


POC_ROOT = Path(__file__).resolve().parents[1]
FINAL = POC_ROOT / "data" / "final" / "facilities" / "adopted_places_with_accessibility_final.csv"
OUT_DIR = POC_ROOT / "data" / "reports" / "facility_validation"
OUT_CSV = OUT_DIR / "toilet_strict_standalone_analysis.csv"
OUT_SUMMARY = OUT_DIR / "toilet_strict_standalone_analysis_summary.json"


STRICT_PUBLIC_TERMS = [
    "공중화장실",
    "공용화장실",
    "공공화장실",
    "간이화장실",
    "이동식화장실",
    "개방화장실",
]

FACILITY_ATTACHED_TERMS = [
    "주민센터",
    "행정복지센터",
    "센터",
    "도서관",
    "박물관",
    "미술관",
    "체육",
    "관리",
    "사무소",
    "사무실",
    "터미널",
    "시장",
    "역",
    "지하철",
    "주차장",
    "층",
    "관광안내소",
    "복지관",
    "보건소",
    "소방서",
    "119",
    "경찰서",
    "지구대",
    "치안센터",
    "파출소",
    "세무서",
    "세관",
    "출입국",
    "우체국",
    "구청",
    "시청",
    "군청",
    "학교",
    "유치원",
    "성당",
    "교회",
    "병원",
    "의원",
    "주유소",
    "은행",
    "빌딩",
    "건물",
    "상가",
    "아파트",
    "오피스텔",
    "마트",
    "경기장",
    "야구장",
    "축구장",
    "게이트볼장",
    "인라인",
    "숭림사",
]

AREA_TERMS = [
    "공원",
    "해수욕장",
    "광장",
    "등산로",
    "산책로",
    "둘레길",
    "수변",
    "강변",
    "하천",
    "유원지",
    "해변",
    "체육공원",
    "근린공원",
    "소공원",
    "어린이공원",
    "항",
    "섬",
    "산",
    "숲",
    "유수지",
    "전망대",
    "문화마당",
    "문화마을",
    "마루터",
    "쉼터",
    "봉",
    "약수터",
    "방파제",
    "대교",
    "수원지",
    "천변",
    "마을",
]

LOCATION_HINT_TERMS = [
    "옆",
    "뒤",
    "앞",
    "입구",
    "내",
    "인근",
    "주변",
    "부근",
    "맞은편",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def find_term(text: str, terms: list[str]) -> str:
    for term in terms:
        if term in text:
            return term
    return ""


def classify(name: str) -> tuple[str, str, str]:
    public_term = find_term(name, STRICT_PUBLIC_TERMS)
    facility_term = find_term(name, FACILITY_ATTACHED_TERMS)
    area_term = find_term(name, AREA_TERMS)
    location_term = find_term(name, LOCATION_HINT_TERMS)

    if public_term and not facility_term and not location_term and not area_term:
        return "STRICT_STANDALONE", public_term, "이름 자체가 독립 공중화장실 계열"
    if public_term and area_term and not facility_term:
        return "AREA_PUBLIC_TOILET", area_term, "공원/해변 등 구역명 기반 공중화장실"
    if facility_term:
        return "FACILITY_ATTACHED", facility_term, "기관/건물/시설 부속 화장실"
    if area_term:
        return "AREA_ATTACHED", area_term, "공원/광장/해변 등 구역 단위 화장실"
    if location_term:
        return "LOCATION_HINT", location_term, "위치 설명 기반 화장실"
    if "화장실" in name:
        return "NAMED_TOILET_OTHER", "화장실", "화장실명이나 독립성 추가 판단 필요"
    return "NO_TOILET_NAME", "", "이름에 화장실 표현이 없음"


def main() -> None:
    toilets = [row for row in read_csv(FINAL) if row["dbCategory"] == "TOILET"]
    out = []
    for row in toilets:
        bucket, term, reason = classify(row["name"])
        out.append(
            {
                "bucket": bucket,
                "matchedTerm": term,
                "placeId": row["placeId"],
                "name": row["name"],
                "address": row["address"],
                "districtGu": row["districtGu"],
                "sourceDataset": row["sourceDataset"],
                "reason": reason,
            }
        )
    write_csv(
        OUT_CSV,
        out,
        ["bucket", "matchedTerm", "placeId", "name", "address", "districtGu", "sourceDataset", "reason"],
    )
    summary = {
        "totalToilets": len(toilets),
        "byBucket": dict(Counter(row["bucket"] for row in out)),
        "byMatchedTerm": dict(Counter(row["matchedTerm"] for row in out if row["matchedTerm"])),
        "strictStandaloneCount": sum(1 for row in out if row["bucket"] == "STRICT_STANDALONE"),
        "strictStandaloneOrAreaPublicCount": sum(
            1 for row in out if row["bucket"] in {"STRICT_STANDALONE", "AREA_PUBLIC_TOILET"}
        ),
        "output": str(OUT_CSV),
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
