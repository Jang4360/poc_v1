from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path


POC_ROOT = Path(__file__).resolve().parents[1]
VALIDATION_DIR = POC_ROOT / "data" / "reports" / "facility_validation"
FINAL_DIR = POC_ROOT / "data" / "final" / "facilities"

ISSUE_CSV = VALIDATION_DIR / "facility_display_quality_expanded_candidates.csv"
FINAL_ADOPTED = FINAL_DIR / "adopted_places_with_accessibility_final.csv"
OUT_PLAN = VALIDATION_DIR / "toilet_public_private_cleanup_plan.csv"
OUT_SUMMARY = VALIDATION_DIR / "toilet_public_private_cleanup_plan_summary.json"

REMOVE_TERMS = [
    "주유소",
    "병원",
    "의원",
    "은행",
    "교회",
    "성당",
    "아파트",
    "오피스텔",
    "빌딩",
    "마트",
]

KEEP_TERMS = [
    "지하상가",
    "지하도상가",
    "시장",
    "고객편의시설",
    "상가시장",
]

REVIEW_TERMS = [
    "상가",
    "터미널",
    "학교",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def contains_any(text: str, terms: list[str]) -> str:
    for term in terms:
        if term in text:
            return term
    return ""


def decide(name: str, address: str) -> tuple[str, str, str]:
    text = f"{name} {address}"
    keep_term = contains_any(text, KEEP_TERMS)
    if keep_term:
        return "KEEP", keep_term, "시장/지하상가/고객편의시설 계열은 공공 개방 가능성이 높아 유지"

    remove_term = contains_any(text, REMOVE_TERMS)
    if remove_term:
        return "REMOVE", remove_term, "민간/내부시설 화장실 가능성이 높아 공중화장실 목적지에서 제외"

    review_term = contains_any(text, REVIEW_TERMS)
    if review_term:
        return "REVIEW", review_term, "개방 여부 판단이 필요해 보류"

    return "REVIEW", "", "규칙으로 판단하기 어려워 보류"


def main() -> None:
    adopted = {row["placeId"]: row for row in read_csv(FINAL_ADOPTED)}
    issues = [
        row
        for row in read_csv(ISSUE_CSV)
        if row["issueType"] == "TOILET_NAME_LOOKS_INTERNAL_OR_PRIVATE"
    ]
    output: list[dict[str, str]] = []
    for issue in issues:
        row = adopted[issue["placeId"]]
        action, matched_term, reason = decide(row["name"], row["address"])
        output.append(
            {
                "action": action,
                "matchedTerm": matched_term,
                "sourceKey": row["sourceKey"],
                "placeId": row["placeId"],
                "name": row["name"],
                "address": row["address"],
                "districtGu": row["districtGu"],
                "sourceDataset": row["sourceDataset"],
                "reason": reason,
            }
        )

    write_csv(
        OUT_PLAN,
        output,
        ["action", "matchedTerm", "sourceKey", "placeId", "name", "address", "districtGu", "sourceDataset", "reason"],
    )
    summary = {
        "total": len(output),
        "byAction": dict(Counter(row["action"] for row in output)),
        "byMatchedTerm": dict(Counter(row["matchedTerm"] for row in output if row["matchedTerm"])),
        "output": str(OUT_PLAN),
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
