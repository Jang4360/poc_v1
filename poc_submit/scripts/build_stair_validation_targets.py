from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(r"C:\Users\SSAFY\Desktop\poc")
STAIR_DIR = ROOT / "data" / "final" / "stairs"
MANUAL_REVIEW = STAIR_DIR / "stair_second_pass_manual_review.csv"
LIKELY_ADOPT = STAIR_DIR / "stair_second_pass_likely_adopt.csv"
OUT_CSV = STAIR_DIR / "stair_roadview_validation_targets.csv"
OUT_SUMMARY = STAIR_DIR / "stair_roadview_validation_targets_summary.json"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else ["sourceId"]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    rows: list[dict[str, str]] = []
    for row in read_csv(MANUAL_REVIEW):
        out = dict(row)
        out["validationTargetGroup"] = "MANUAL_REVIEW"
        rows.append(out)
    for row in read_csv(LIKELY_ADOPT):
        if row.get("priority") != "P4":
            continue
        out = dict(row)
        out["validationTargetGroup"] = "P4_LIKELY_ADOPT"
        rows.append(out)

    deduped: dict[str, dict[str, str]] = {}
    for row in rows:
        deduped[row["sourceId"]] = row
    rows = list(deduped.values())
    rows.sort(key=lambda row: (row.get("districtGu", ""), row.get("validationTargetGroup", ""), row.get("sourceId", "")))

    write_csv(OUT_CSV, rows)
    summary = {
        "sourceFiles": [str(MANUAL_REVIEW), str(LIKELY_ADOPT)],
        "output": str(OUT_CSV),
        "total": len(rows),
        "targetGroupCounts": dict(Counter(row["validationTargetGroup"] for row in rows)),
        "priorityCounts": dict(Counter(row["priority"] for row in rows)),
        "districtCounts": dict(Counter(row["districtGu"] for row in rows)),
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
