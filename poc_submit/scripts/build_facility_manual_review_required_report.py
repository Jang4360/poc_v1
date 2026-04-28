from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


POC_ROOT = Path(__file__).resolve().parents[1]
ASSETS_DATA = POC_ROOT / "assets" / "data"
REPORT_DIR = POC_ROOT / "data" / "reports" / "facility_validation"

FACILITIES_JS = ASSETS_DATA / "facilities-data.js"
MANUAL_REVIEW_SEED_JS = ASSETS_DATA / "manual-review-seed-data.js"

OUT_CSV = REPORT_DIR / "facility_manual_review_required_cases.csv"
OUT_SUMMARY = REPORT_DIR / "facility_manual_review_required_cases_summary.json"

CSV_FIELDS = [
    "reasonCode",
    "placeId",
    "sourceId",
    "name",
    "dbCategory",
    "uiCategory",
    "districtGu",
    "address",
    "coordinateQuality",
    "coordinateQualityReason",
    "evidenceAction",
    "status",
    "kakaoStatus",
    "kakaoPlaceName",
    "kakaoDistanceM",
    "poiStatus",
    "poiName",
    "poiDistanceM",
    "reviewFlags",
    "reviewReasons",
]


def load_assignment(path: Path, variable_name: str) -> Any:
    text = path.read_text(encoding="utf-8").strip()
    prefix = f"window.{variable_name} = "
    if not text.startswith(prefix):
        raise ValueError(f"Unexpected JS assignment format: {path}")
    if text.endswith(";"):
        text = text[:-1]
    return json.loads(text[len(prefix) :])


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows([{field: row.get(field, "") for field in CSV_FIELDS} for row in rows])


def is_internal_only(record: dict[str, Any]) -> bool:
    return str(record.get("coordinateQuality") or "").upper() == "INTERNAL"


def is_category_review_required(record: dict[str, Any]) -> bool:
    if is_internal_only(record):
        return False
    evidence_action = str(record.get("evidenceAction") or "").upper()
    if evidence_action == "POLICY_CATEGORY_DECIDED":
        return False
    return "CATEGORY" in evidence_action


def reason_code_for(feature: dict[str, Any], record: dict[str, Any]) -> str:
    if is_internal_only(record):
        return ""

    props = feature.get("properties") or {}
    status = str(record.get("status") or "").upper()
    evidence_action = str(record.get("evidenceAction") or "").upper()
    review_flags = props.get("reviewFlags") or []

    if status and status != "KEEP":
        return "STATUS_NOT_KEEP"
    if is_category_review_required(record):
        return "CATEGORY_REVIEW"
    if evidence_action in {"RENAME_REVIEW", "MANUAL_REVIEW", "REVIEW_OR_REMOVE"}:
        return evidence_action
    if "generic_name" in review_flags:
        return "GENERIC_NAME"
    return ""


def make_row(feature: dict[str, Any], record: dict[str, Any], reason_code: str) -> dict[str, Any]:
    props = feature.get("properties") or {}
    return {
        "reasonCode": reason_code,
        "placeId": props.get("placeId", record.get("placeId", "")),
        "sourceId": props.get("sourceId", record.get("sourceId", "")),
        "name": props.get("name", record.get("name", "")),
        "dbCategory": props.get("dbCategory", record.get("category", "")),
        "uiCategory": props.get("uiCategory", props.get("dbCategoryLabel", "")),
        "districtGu": props.get("districtGu", record.get("districtGu", "")),
        "address": props.get("address", ""),
        "coordinateQuality": record.get("coordinateQuality", ""),
        "coordinateQualityReason": record.get("coordinateQualityReason", ""),
        "evidenceAction": record.get("evidenceAction", ""),
        "status": record.get("status", ""),
        "kakaoStatus": record.get("kakaoStatus", ""),
        "kakaoPlaceName": record.get("kakaoPlaceName", ""),
        "kakaoDistanceM": record.get("kakaoDistanceM", ""),
        "poiStatus": record.get("poiStatus", ""),
        "poiName": record.get("poiName", ""),
        "poiDistanceM": record.get("poiDistanceM", ""),
        "reviewFlags": "|".join(props.get("reviewFlags") or []),
        "reviewReasons": "|".join(props.get("reviewReasons") or []),
    }


def main() -> None:
    geojson = load_assignment(FACILITIES_JS, "FACILITIES_GEOJSON")
    seed = load_assignment(MANUAL_REVIEW_SEED_JS, "MANUAL_REVIEW_SEED")

    rows: list[dict[str, Any]] = []
    for feature in geojson.get("features", []):
        props = feature.get("properties") or {}
        place_id = str(props.get("placeId") or "")
        key = f"facility:{place_id}"
        record = seed.get(key)
        if not record:
            continue
        reason_code = reason_code_for(feature, record)
        if not reason_code:
            continue
        rows.append(make_row(feature, record, reason_code))

    rows.sort(
        key=lambda row: (
            row["reasonCode"],
            row["districtGu"],
            row["dbCategory"],
            row["name"],
            int(row["placeId"] or 0),
        )
    )
    write_csv(OUT_CSV, rows)

    summary = {
        "generatedAt": datetime.now().isoformat(),
        "total": len(rows),
        "byReasonCode": dict(Counter(row["reasonCode"] for row in rows)),
        "byEvidenceAction": dict(Counter(row["evidenceAction"] for row in rows)),
        "byStatus": dict(Counter(row["status"] for row in rows)),
        "byDbCategory": dict(Counter(row["dbCategory"] for row in rows)),
        "byUiCategory": dict(Counter(row["uiCategory"] for row in rows)),
        "byCoordinateQuality": dict(Counter(row["coordinateQuality"] for row in rows)),
        "byDistrictGu": dict(Counter(row["districtGu"] for row in rows)),
        "outputCsv": str(OUT_CSV),
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
