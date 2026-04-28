from __future__ import annotations

import csv
import json
import shutil
from collections import Counter
from pathlib import Path


POC_ROOT = Path(__file__).resolve().parents[1]
DATA_ADOPTED = POC_ROOT / "data" / "adopted"
ASSETS_DATA = POC_ROOT / "assets" / "data"
VALIDATION_DIR = POC_ROOT / "data" / "reports" / "facility_validation"
ARCHIVE_DIR = POC_ROOT / "archive" / "20260426_facility_category_v2_before"

ADOPTED_ALL = DATA_ADOPTED / "adopted_places_with_accessibility.csv"
ADOPTED_PLACES = DATA_ADOPTED / "adopted_places.csv"
ADOPTED_ACCESSIBILITY = DATA_ADOPTED / "adopted_place_accessibility.csv"
ERD_PLACES = DATA_ADOPTED / "places_erd.csv"
FACILITIES_JS = ASSETS_DATA / "facilities-data.js"

OUT_SUMMARY_JSON = VALIDATION_DIR / "facility_category_v2_cleanup_summary.json"
OUT_MAPPING_CSV = VALIDATION_DIR / "facility_category_v2_cleanup_mapping.csv"

LABEL_BY_CATEGORY = {
    "TOILET": "화장실",
    "RESTAURANT": "음식·카페",
    "TOURIST_SPOT": "관광지",
    "ACCOMMODATION": "숙박",
    "CHARGING_STATION": "전동보장구 충전소",
    "HEALTHCARE": "의료·보건",
    "WELFARE": "복지·돌봄",
    "PUBLIC_OFFICE": "공공기관",
}

HEALTHCARE_TYPES = {
    "의원·치과의원·한의원·조산소·산후조리원",
    "병원·치과병원·한방병원·정신병원·요양병원",
    "종합병원",
    "보건소",
}

WELFARE_TYPES = {
    "노인복지시설",
    "이외 사회복지시설",
    "경로당",
    "아동복지시설",
    "장애인복지시설",
}

PUBLIC_OFFICE_TYPES = {
    "국가 또는 지자체 청사",
    "파출소, 지구대",
    "지역자치센터",
    "우체국",
    "국민연금공단 및 지사",
    "근로복지공단 및 지사",
    "국민건강보험공단 및 지사",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def backup_files(paths: list[Path]) -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    for path in paths:
        destination = ARCHIVE_DIR / path.relative_to(POC_ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copy2(path, destination)


def classify(row: dict[str, str]) -> str:
    current = row.get("dbCategory") or row.get("category") or ""
    if current != "BARRIER_FREE_FACILITY":
        return current

    facility_type = (
        row.get("facilityCategory")
        or row.get("rawFacilityType")
        or row.get("publicFacilityType")
        or row.get("raw_category")
        or row.get("source_category")
        or ""
    )
    if facility_type in HEALTHCARE_TYPES:
        return "HEALTHCARE"
    if facility_type in WELFARE_TYPES:
        return "WELFARE"
    if facility_type in PUBLIC_OFFICE_TYPES:
        return "PUBLIC_OFFICE"
    raise ValueError(f"Unmapped barrier-free facility type: {facility_type} ({row})")


def sync_adopted_all() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    rows = read_csv(ADOPTED_ALL)
    fieldnames = list(rows[0].keys())
    mapping_rows: list[dict[str, str]] = []
    for row in rows:
        before = row["dbCategory"]
        after = classify(row)
        if before != after:
            mapping_rows.append(
                {
                    "sourceKey": row["sourceKey"],
                    "placeId": row["placeId"],
                    "name": row["name"],
                    "beforeCategory": before,
                    "afterCategory": after,
                    "afterLabel": LABEL_BY_CATEGORY[after],
                    "facilityCategory": row["facilityCategory"],
                    "rawFacilityType": row["rawFacilityType"],
                    "address": row["address"],
                }
            )
        row["dbCategory"] = after
        row["dbCategoryLabel"] = LABEL_BY_CATEGORY[after]
        row["uiCategory"] = LABEL_BY_CATEGORY[after]
        row["facilityCategory"] = LABEL_BY_CATEGORY[after]
    write_csv(ADOPTED_ALL, rows, fieldnames)
    return rows, mapping_rows


def sync_adopted_places(mapping_by_key: dict[str, dict[str, str]]) -> None:
    rows = read_csv(ADOPTED_PLACES)
    fieldnames = list(rows[0].keys())
    for row in rows:
        mapping = mapping_by_key.get(row["place_key"])
        if mapping:
            row["ui_category"] = mapping["afterLabel"]
    write_csv(ADOPTED_PLACES, rows, fieldnames)


def sync_adopted_accessibility(mapping_by_key: dict[str, dict[str, str]]) -> None:
    rows = read_csv(ADOPTED_ACCESSIBILITY)
    fieldnames = list(rows[0].keys())
    for row in rows:
        mapping = mapping_by_key.get(row["place_key"])
        if mapping:
            row["ui_category"] = mapping["afterLabel"]
    write_csv(ADOPTED_ACCESSIBILITY, rows, fieldnames)


def write_erd_places(adopted_rows: list[dict[str, str]]) -> None:
    rows = [
        {
            "placeId": row["placeId"],
            "name": row["name"],
            "category": row["dbCategory"],
            "address": row["address"],
            "point": row["point"],
            "providerPlaceId": row["providerPlaceId"],
        }
        for row in adopted_rows
    ]
    write_csv(ERD_PLACES, rows, ["placeId", "name", "category", "address", "point", "providerPlaceId"])


def load_facilities_geojson() -> dict[str, object]:
    text = FACILITIES_JS.read_text(encoding="utf-8").strip()
    prefix = "window.FACILITIES_GEOJSON = "
    if not text.startswith(prefix):
        raise ValueError("Unexpected facilities JS format")
    if text.endswith(";"):
        text = text[:-1]
    return json.loads(text[len(prefix) :])


def sync_facilities_js(mapping_by_key: dict[str, dict[str, str]]) -> None:
    geojson = load_facilities_geojson()
    for feature in geojson["features"]:
        props = feature["properties"]
        mapping = mapping_by_key.get(props["sourceId"])
        if mapping:
            after = mapping["afterCategory"]
            label = mapping["afterLabel"]
            props["dbCategory"] = after
            props["dbCategoryLabel"] = label
            props["uiCategory"] = label
            props["facilityCategory"] = label
            props["displaySource"] = label
    FACILITIES_JS.write_text(
        "window.FACILITIES_GEOJSON = "
        + json.dumps(geojson, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )


def main() -> None:
    affected = [ADOPTED_ALL, ADOPTED_PLACES, ADOPTED_ACCESSIBILITY, ERD_PLACES, FACILITIES_JS]
    backup_files(affected)
    before_rows = read_csv(ADOPTED_ALL)
    before_counts = Counter(row["dbCategory"] for row in before_rows)

    adopted_rows, mapping_rows = sync_adopted_all()
    mapping_by_key = {row["sourceKey"]: row for row in mapping_rows}
    sync_adopted_places(mapping_by_key)
    sync_adopted_accessibility(mapping_by_key)
    write_erd_places(adopted_rows)
    sync_facilities_js(mapping_by_key)

    after_counts = Counter(row["dbCategory"] for row in adopted_rows)
    write_csv(
        OUT_MAPPING_CSV,
        mapping_rows,
        [
            "sourceKey",
            "placeId",
            "name",
            "beforeCategory",
            "afterCategory",
            "afterLabel",
            "facilityCategory",
            "rawFacilityType",
            "address",
        ],
    )
    summary = {
        "processed": len(mapping_rows),
        "beforeCategoryCounts": dict(sorted(before_counts.items())),
        "afterCategoryCounts": dict(sorted(after_counts.items())),
        "mappingCounts": dict(Counter(row["afterCategory"] for row in mapping_rows)),
        "backupDir": str(ARCHIVE_DIR),
        "mappingFile": str(OUT_MAPPING_CSV),
    }
    OUT_SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
