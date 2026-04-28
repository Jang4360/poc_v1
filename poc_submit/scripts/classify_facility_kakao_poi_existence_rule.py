from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


POC_ROOT = Path(__file__).resolve().parents[1]
VALIDATION_DIR = POC_ROOT / "data" / "reports" / "facility_validation"
INPUT_CSV = VALIDATION_DIR / "facility_kakao_first_refresh_all.csv"

OUT_ALL = VALIDATION_DIR / "facility_kakao_poi_existence_rule_all.csv"
OUT_KEEP = VALIDATION_DIR / "facility_kakao_poi_existence_rule_keep.csv"
OUT_REMOVE = VALIDATION_DIR / "facility_kakao_poi_existence_rule_remove_candidates.csv"
OUT_SUMMARY_CSV = VALIDATION_DIR / "facility_kakao_poi_existence_rule_summary.csv"
OUT_SUMMARY_JSON = VALIDATION_DIR / "facility_kakao_poi_existence_rule_summary.json"

KAKAO_EXISTS_STATUSES = {"KAKAO_STRONG", "KAKAO_MEDIUM"}
POI_EXISTS_STATUSES = {"MATCH_STRONG", "MATCH_MEDIUM"}
TOILET_CATEGORIES = {"공중화장실", "시설 내 화장실"}

OUTPUT_FIELDS = [
    "existenceDecision",
    "existenceStatus",
    "primarySource",
    "kakaoExists",
    "poiExists",
    "existenceReason",
]


def parse_float(value: Any, default: float = 999999.0) -> float:
    try:
        if value in ("", None):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def has_toilet_evidence(text: str) -> bool:
    return "화장실" in (text or "")


def is_toilet_row(row: dict[str, str]) -> bool:
    return row.get("uiCategory", "") in TOILET_CATEGORIES or "화장실" in row.get("uiCategory", "")


def kakao_exists(row: dict[str, str]) -> tuple[bool, str]:
    status = row.get("kakao_best_status", "")
    if status in KAKAO_EXISTS_STATUSES:
        return True, status

    if is_toilet_row(row):
        text = f"{row.get('kakao_place_name', '')} {row.get('kakao_category', '')}"
        distance_m = parse_float(row.get("kakao_distance_m"))
        if has_toilet_evidence(text) and distance_m <= 120:
            return True, f"KAKAO_TOILET_CATEGORY_WITHIN_{distance_m:.1f}m"

    return False, status or "KAKAO_EMPTY"


def poi_exists(row: dict[str, str]) -> tuple[bool, str]:
    status = row.get("poi_match_status", "")
    if status in POI_EXISTS_STATUSES:
        return True, status

    if is_toilet_row(row):
        text = f"{row.get('poi_name', '')} {row.get('poi_category_label', '')}"
        distance_m = parse_float(row.get("poi_distance_m"))
        if has_toilet_evidence(text) and distance_m <= 300:
            return True, f"POI_TOILET_CATEGORY_WITHIN_{distance_m:.1f}m"

    return False, status or "POI_EMPTY"


def classify(row: dict[str, str]) -> dict[str, str]:
    has_kakao, kakao_reason = kakao_exists(row)
    has_poi, poi_reason = poi_exists(row)

    if has_kakao and has_poi:
        return {
            "existenceDecision": "KEEP",
            "existenceStatus": "BOTH_EXISTS_KAKAO_PRIMARY",
            "primarySource": "KAKAO",
            "kakaoExists": "Y",
            "poiExists": "Y",
            "existenceReason": f"카카오와 POI 모두 근거 있음. 최신 명칭/좌표는 카카오 우선. kakao={kakao_reason}, poi={poi_reason}",
        }
    if has_kakao:
        return {
            "existenceDecision": "KEEP",
            "existenceStatus": "KAKAO_ONLY_EXISTS",
            "primarySource": "KAKAO",
            "kakaoExists": "Y",
            "poiExists": "N",
            "existenceReason": f"카카오 근거 있음. POI는 보조 근거 없음/약함. kakao={kakao_reason}, poi={poi_reason}",
        }
    if has_poi:
        return {
            "existenceDecision": "KEEP",
            "existenceStatus": "POI_ONLY_EXISTS",
            "primarySource": "POI",
            "kakaoExists": "N",
            "poiExists": "Y",
            "existenceReason": f"카카오 근거는 약하지만 POI 근거 있음. poi={poi_reason}, kakao={kakao_reason}",
        }
    return {
        "existenceDecision": "REMOVE_REVIEW",
        "existenceStatus": "NO_KAKAO_NO_POI",
        "primarySource": "NONE",
        "kakaoExists": "N",
        "poiExists": "N",
        "existenceReason": f"카카오와 POI 모두 존재 근거가 약함. kakao={kakao_reason}, poi={poi_reason}",
    }


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows([{field: row.get(field, "") for field in fieldnames} for row in rows])


def write_summary(rows: list[dict[str, str]]) -> None:
    summary_rows: list[dict[str, str]] = []
    for group, key in [
        ("existenceDecision", "existenceDecision"),
        ("existenceStatus", "existenceStatus"),
        ("primarySource", "primarySource"),
        ("uiCategory", "uiCategory"),
        ("uiCategoryByExistence", "uiCategory|existenceStatus"),
        ("recommendedActionByExistence", "recommendedAction|existenceStatus"),
    ]:
        if "|" in key:
            left, right = key.split("|", 1)
            counter = Counter(f"{row.get(left, '')} / {row.get(right, '')}" for row in rows)
        else:
            counter = Counter(row.get(key, "") for row in rows)
        for name, count in sorted(counter.items(), key=lambda item: (-item[1], item[0])):
            summary_rows.append({"group": group, "name": name, "count": str(count)})

    write_csv(OUT_SUMMARY_CSV, summary_rows, ["group", "name", "count"])
    OUT_SUMMARY_JSON.write_text(
        json.dumps(
            {
                "total": len(rows),
                "existenceDecisionCounts": dict(Counter(row["existenceDecision"] for row in rows)),
                "existenceStatusCounts": dict(Counter(row["existenceStatus"] for row in rows)),
                "primarySourceCounts": dict(Counter(row["primarySource"] for row in rows)),
                "uiCategoryCounts": dict(Counter(row["uiCategory"] for row in rows)),
                "files": {
                    "all": str(OUT_ALL),
                    "keep": str(OUT_KEEP),
                    "removeCandidates": str(OUT_REMOVE),
                    "summaryCsv": str(OUT_SUMMARY_CSV),
                    "summaryJson": str(OUT_SUMMARY_JSON),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    rows = read_csv(INPUT_CSV)
    output = [{**row, **classify(row)} for row in rows]
    fieldnames = list(rows[0].keys()) + OUTPUT_FIELDS
    write_csv(OUT_ALL, output, fieldnames)
    write_csv(OUT_KEEP, [row for row in output if row["existenceDecision"] == "KEEP"], fieldnames)
    write_csv(OUT_REMOVE, [row for row in output if row["existenceDecision"] == "REMOVE_REVIEW"], fieldnames)
    write_summary(output)

    print("done", len(output))
    print("existenceDecision", dict(Counter(row["existenceDecision"] for row in output)))
    print("existenceStatus", dict(Counter(row["existenceStatus"] for row in output)))
    print("primarySource", dict(Counter(row["primarySource"] for row in output)))


if __name__ == "__main__":
    main()
