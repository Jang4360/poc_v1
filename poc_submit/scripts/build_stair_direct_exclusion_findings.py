from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(r"C:\Users\SSAFY\Desktop\poc")
SRC = ROOT / "data" / "reports" / "stair_review" / "busan_stair_review_candidates.csv"
OUT = ROOT / "data" / "reports" / "stair_review" / "stair_direct_exclusion_findings.csv"
SUMMARY = ROOT / "data" / "reports" / "stair_review" / "stair_direct_exclusion_findings_summary.json"

TERM_GROUPS = {
    "EXCLUDE_PRIVATE_SCHOOL_CAMPUS": [
        "\ud559\uad50",
        "\ucd08\uad50",
        "\uc911\uad50",
        "\uace0\uad50",
        "\ucd08\ub4f1",
        "\uc911\ub4f1",
        "\uace0\ub4f1",
        "\ub300\ud559\uad50",
        "\ub300\ud559",
        "\ucea0\ud37c\uc2a4",
        "\uc720\uce58\uc6d0",
        "\uc5b4\ub9b0\uc774\uc9d1",
        "\ud559\uc6d0",
    ],
    "EXCLUDE_PRIVATE_RESIDENTIAL": [
        "\uc544\ud30c\ud2b8",
        "\ube4c\ub77c",
        "\ub9e8\uc158",
        "\uc8fc\ud0dd",
        "\uc624\ud53c\uc2a4\ud154",
        "\uc6d0\ub8f8",
        "\uc8fc\uacf5",
        "\ube4c\ub9ac\uc9c0",
        "\ud558\uc774\uce20",
        "\ud0c0\uc6b4\ud558\uc6b0\uc2a4",
    ],
    "EXCLUDE_PRIVATE_RELIGIOUS": [
        "\uad50\ud68c",
        "\uc131\ub2f9",
        "\uc0ac\ucc30",
        "\uc554\uc790",
        "\uc120\uc6d0",
    ],
    "EXCLUDE_PRIVATE_INDUSTRIAL": [
        "\uacf5\uc7a5",
        "\uc0b0\uc5c5",
        "\ubb3c\ub958",
        "\ucc3d\uace0",
        "\uacf5\ub2e8",
        "\uc81c\uc870",
        "\uc8fc\uc720\uc18c",
        "\ucda9\uc804\uc18c",
    ],
    "EXCLUDE_PRIVATE_BUILDING_COMMERCIAL": [
        "\ube4c\ub529",
        "\uc0c1\uac00",
        "\ub9c8\ud2b8",
        "\ud50c\ub77c\uc790",
        "\ubab0",
    ],
}

PUBLIC_CONTEXT_TERMS = [
    "\uacf5\uc6d0",
    "\uc5ed",
    "\ud574\uc218\uc695\uc7a5",
    "\uc2dc\uc7a5",
    "\uad6c\uccad",
    "\uc8fc\ubbfc\uc13c\ud130",
    "\ud589\uc815\ubcf5\uc9c0",
    "\ubcf5\uc9c0\uad00",
    "\ub3c4\uc11c\uad00",
    "\uccb4\uc721",
    "\ud130\ubbf8\ub110",
    "\uad11\uc7a5",
    "\uc0b0\ucc45",
    "\ub458\ub808\uae38",
    "\ub4f1\uc0b0",
    "\uacf5\uc601",
    "\uc9c0\ud558\ucca0",
    "\ubcd1\uc6d0",
    "\ubcf4\uac74\uc18c",
    "\uad00\uad11",
    "\ud574\ubcc0",
    "\ud56d",
    "\uc721\uad50",
    "\uc9c0\ud558\ub3c4",
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


def text_context(row: dict[str, str]) -> str:
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


def matched_private_group(row: dict[str, str]) -> tuple[str, str]:
    name = row.get("name", "") or ""
    for group, terms in TERM_GROUPS.items():
        found = [term for term in terms if term in name]
        if found:
            return group, "|".join(found)
    return "", ""


def has_public_context(row: dict[str, str]) -> bool:
    context = text_context(row)
    return any(term in context for term in PUBLIC_CONTEXT_TERMS)


def classify(row: dict[str, str]) -> tuple[str, str, str] | None:
    group, matched_terms = matched_private_group(row)
    if group:
        return group, "HIGH", f"name_has_private_internal_keyword:{matched_terms}"

    if row["priority"] != "P4":
        return None

    road_distance = parse_float(row.get("nearestRoadDistanceM", ""))
    has_near_clue = is_true(row.get("nearCrosswalk30m", "")) or is_true(row.get("nearFacility50m", ""))

    if road_distance > 50 and has_public_context(row):
        return "REVIEW_P4_PUBLIC_CONTEXT", "MEDIUM", "p4_road_gt_50m_public_context_needs_map_check"

    if road_distance > 100 and not has_near_clue:
        return "EXCLUDE_LOW_CONNECTIVITY_VERY_STRONG", "MEDIUM_HIGH", "p4_road_gt_100m_no_crosswalk30_no_facility50"

    if road_distance > 50 and not has_near_clue:
        return "REVIEW_P4_LOW_CONNECTIVITY", "MEDIUM", "p4_road_gt_50m_no_clue_needs_map_check"

    return "REVIEW_P4_NEAR_ROAD_OR_CLUE", "MEDIUM", "p4_road_le_50m_or_has_nearby_clue"


def make_output_row(row: dict[str, str], decision: str, confidence: str, reason_code: str) -> dict[str, str]:
    lat = row.get("lat", "")
    lng = row.get("lng", "")
    return {
        "decision": decision,
        "confidence": confidence,
        "reasonCode": reason_code,
        "sourceId": row.get("sourceId", ""),
        "districtGu": row.get("districtGu", ""),
        "name": row.get("name", ""),
        "priority": row.get("priority", ""),
        "reviewStatus": row.get("reviewStatus", ""),
        "nearestRoadDistanceM": row.get("nearestRoadDistanceM", ""),
        "nearestCrosswalkDistanceM": row.get("nearestCrosswalkDistanceM", ""),
        "nearestFacilityDistanceM": row.get("nearestFacilityDistanceM", ""),
        "nearestFacilityName": row.get("nearestFacilityName", ""),
        "reviewReason": row.get("reviewReason", ""),
        "lat": lat,
        "lng": lng,
        "kakaoMapUrl": f"https://map.kakao.com/link/map/{lat},{lng}",
        "kakaoRoadviewUrl": f"https://map.kakao.com/link/roadview/{lat},{lng}",
    }


def build_summary(source_rows: list[dict[str, str]], out_rows: list[dict[str, str]]) -> dict[str, Any]:
    haeundae_rows = [row for row in out_rows if row["districtGu"] == "\ud574\uc6b4\ub300\uad6c"]
    return {
        "source": str(SRC),
        "output": str(OUT),
        "totalStairs": len(source_rows),
        "findingRows": len(out_rows),
        "byDecision": dict(Counter(row["decision"] for row in out_rows)),
        "byConfidence": dict(Counter(row["confidence"] for row in out_rows)),
        "excludeCandidateCount": sum(1 for row in out_rows if row["decision"].startswith("EXCLUDE_")),
        "reviewCandidateCount": sum(1 for row in out_rows if row["decision"].startswith("REVIEW_")),
        "excludeByPriority": dict(Counter(row["priority"] for row in out_rows if row["decision"].startswith("EXCLUDE_"))),
        "haeundae": {
            "findingRows": len(haeundae_rows),
            "byDecision": dict(Counter(row["decision"] for row in haeundae_rows)),
            "excludeCandidateCount": sum(1 for row in haeundae_rows if row["decision"].startswith("EXCLUDE_")),
            "reviewCandidateCount": sum(1 for row in haeundae_rows if row["decision"].startswith("REVIEW_")),
            "excludeByPriority": dict(Counter(row["priority"] for row in haeundae_rows if row["decision"].startswith("EXCLUDE_"))),
        },
    }


def main() -> None:
    source_rows = read_csv(SRC)
    out_rows: list[dict[str, str]] = []
    for row in source_rows:
        classified = classify(row)
        if not classified:
            continue
        out_rows.append(make_output_row(row, *classified))

    fieldnames = list(out_rows[0].keys()) if out_rows else ["decision"]
    write_csv(OUT, out_rows, fieldnames)
    summary = build_summary(source_rows, out_rows)
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
