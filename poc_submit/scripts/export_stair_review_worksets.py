from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(r"C:\Users\SSAFY\Desktop\poc")
STAIRS = ROOT / "data" / "reports" / "stair_review" / "busan_stair_review_candidates.csv"
FINDINGS = ROOT / "data" / "reports" / "stair_review" / "stair_direct_exclusion_findings.csv"
OUT_DIR = ROOT / "data" / "final" / "stairs"

ADOPTED_REVIEW = OUT_DIR / "stair_candidates_keep_review.csv"
P4_REVIEW = OUT_DIR / "stair_candidates_p4_manual_review.csv"
RESIDENTIAL_REVIEW = OUT_DIR / "stair_candidates_residential_manual_review.csv"
EXCLUDED = OUT_DIR / "stair_candidates_excluded.csv"
SUMMARY = OUT_DIR / "stair_candidates_workset_summary.json"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def enrich(row: dict[str, str], finding: dict[str, str] | None, workset: str) -> dict[str, str]:
    out = dict(row)
    out["workset"] = workset
    out["decision"] = finding["decision"] if finding else "KEEP_REVIEW"
    out["decisionConfidence"] = finding["confidence"] if finding else "MEDIUM"
    out["decisionReasonCode"] = finding["reasonCode"] if finding else "p1_p2_p3_no_private_keyword"
    lat = row.get("lat", "")
    lng = row.get("lng", "")
    out["kakaoMapUrl"] = f"https://map.kakao.com/link/map/{lat},{lng}"
    out["kakaoRoadviewUrl"] = f"https://map.kakao.com/link/roadview/{lat},{lng}"
    return out


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stair_rows = read_csv(STAIRS)
    findings = {row["sourceId"]: row for row in read_csv(FINDINGS)}

    keep_review: list[dict[str, str]] = []
    p4_review: list[dict[str, str]] = []
    residential_review: list[dict[str, str]] = []
    excluded: list[dict[str, str]] = []

    for row in stair_rows:
        finding = findings.get(row["sourceId"])
        if finding and finding["decision"] == "EXCLUDE_PRIVATE_RESIDENTIAL":
            residential_review.append(enrich(row, finding, "RESIDENTIAL_MANUAL_REVIEW"))
        elif finding and finding["decision"].startswith("EXCLUDE_"):
            excluded.append(enrich(row, finding, "EXCLUDED"))
        elif finding and finding["decision"].startswith("REVIEW_"):
            p4_review.append(enrich(row, finding, "P4_MANUAL_REVIEW"))
        else:
            keep_review.append(enrich(row, None, "KEEP_REVIEW"))

    fieldnames = list(keep_review[0].keys()) if keep_review else list(stair_rows[0].keys())
    write_csv(ADOPTED_REVIEW, keep_review, fieldnames)
    write_csv(P4_REVIEW, p4_review, fieldnames)
    write_csv(RESIDENTIAL_REVIEW, residential_review, fieldnames)
    write_csv(EXCLUDED, excluded, fieldnames)

    summary = {
        "source": str(STAIRS),
        "findings": str(FINDINGS),
        "outputs": {
            "keepReview": str(ADOPTED_REVIEW),
            "p4ManualReview": str(P4_REVIEW),
            "residentialManualReview": str(RESIDENTIAL_REVIEW),
            "excluded": str(EXCLUDED),
        },
        "counts": {
            "total": len(stair_rows),
            "keepReview": len(keep_review),
            "p4ManualReview": len(p4_review),
            "residentialManualReview": len(residential_review),
            "excluded": len(excluded),
        },
        "priorityCounts": {
            "keepReview": dict(Counter(row["priority"] for row in keep_review)),
            "p4ManualReview": dict(Counter(row["priority"] for row in p4_review)),
            "residentialManualReview": dict(Counter(row["priority"] for row in residential_review)),
            "excluded": dict(Counter(row["priority"] for row in excluded)),
        },
        "excludedByDecision": dict(Counter(row["decision"] for row in excluded)),
        "p4ReviewByDecision": dict(Counter(row["decision"] for row in p4_review)),
        "residentialReviewByDecision": dict(Counter(row["decision"] for row in residential_review)),
        "districtCounts": {
            "keepReview": dict(Counter(row["districtGu"] for row in keep_review)),
            "p4ManualReview": dict(Counter(row["districtGu"] for row in p4_review)),
            "residentialManualReview": dict(Counter(row["districtGu"] for row in residential_review)),
            "excluded": dict(Counter(row["districtGu"] for row in excluded)),
        },
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
