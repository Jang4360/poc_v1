from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
from collections import Counter
from pathlib import Path
from typing import Any


POC_ROOT = Path(__file__).resolve().parents[1]
DATA_ADOPTED = POC_ROOT / "data" / "adopted"
DATA_FINAL = POC_ROOT / "data" / "final" / "facilities"
VALIDATION_DIR = POC_ROOT / "data" / "reports" / "facility_validation"

SOURCE_FILES = {
    "places_erd": DATA_ADOPTED / "places_erd.csv",
    "place_accessibility_features_erd": DATA_ADOPTED / "place_accessibility_features_erd.csv",
    "adopted_places_with_accessibility": DATA_ADOPTED / "adopted_places_with_accessibility.csv",
    "adopted_places": DATA_ADOPTED / "adopted_places.csv",
    "adopted_place_accessibility": DATA_ADOPTED / "adopted_place_accessibility.csv",
}

FINAL_FILES = {
    "places_erd": DATA_FINAL / "places_erd.csv",
    "place_accessibility_features_erd": DATA_FINAL / "place_accessibility_features_erd.csv",
    "adopted_places_with_accessibility": DATA_FINAL / "adopted_places_with_accessibility_final.csv",
    "adopted_places": DATA_FINAL / "adopted_places_final.csv",
    "adopted_place_accessibility": DATA_FINAL / "adopted_place_accessibility_final.csv",
}

SUMMARY_JSON = DATA_FINAL / "facility_final_summary.json"
VALIDATION_JSON = DATA_FINAL / "facility_final_validation_report.json"
QUALITY_WARNINGS_CSV = DATA_FINAL / "facility_final_quality_warnings.csv"
CHECKSUMS_JSON = DATA_FINAL / "facility_final_checksums.json"
README_MD = DATA_FINAL / "README.md"

EXPECTED_PLACES_COLUMNS = ["placeId", "name", "category", "address", "point", "providerPlaceId"]
EXPECTED_FEATURE_COLUMNS = ["id", "placeId", "featureType", "isAvailable"]
ALLOWED_CATEGORIES = {
    "FOOD_CAFE",
    "TOURIST_SPOT",
    "ACCOMMODATION",
    "HEALTHCARE",
    "WELFARE",
    "PUBLIC_OFFICE",
    "ETC",
}
ALLOWED_FEATURE_TYPES = {
    "ramp",
    "accessibleEntrance",
    "autoDoor",
    "elevator",
    "accessibleToilet",
    "accessibleParking",
    "chargingStation",
    "stepFree",
    "accessibleRoom",
    "guidanceFacility",
}
GENERIC_NAME_EXACT = {
    "공중화장실",
    "일반음식점",
    "휴게음식점·제과점",
    "일반숙박시설",
    "관광숙박시설",
    "파출소, 지구대",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def read_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return next(csv.reader(file))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_int_string(value: str) -> bool:
    return bool(re.fullmatch(r"\d+", value or ""))


def point_is_valid(value: str) -> bool:
    return bool(re.fullmatch(r"POINT\([0-9.\-]+ [0-9.\-]+\)", value or ""))


def extract_lng_lat(point: str) -> tuple[float, float] | None:
    match = re.fullmatch(r"POINT\(([0-9.\-]+) ([0-9.\-]+)\)", point or "")
    if not match:
        return None
    return float(match.group(1)), float(match.group(2))


def add_check(checks: list[dict[str, Any]], name: str, passed: bool, detail: str = "") -> None:
    checks.append({"name": name, "passed": bool(passed), "detail": detail})


def validate(places: list[dict[str, str]], features: list[dict[str, str]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    place_header = read_header(SOURCE_FILES["places_erd"])
    feature_header = read_header(SOURCE_FILES["place_accessibility_features_erd"])
    add_check(checks, "places schema", place_header == EXPECTED_PLACES_COLUMNS, str(place_header))
    add_check(checks, "features schema", feature_header == EXPECTED_FEATURE_COLUMNS, str(feature_header))

    place_ids = [row["placeId"] for row in places]
    numeric_place_ids = all(is_int_string(value) for value in place_ids)
    add_check(checks, "placeId numeric", numeric_place_ids)
    add_check(checks, "placeId unique", len(place_ids) == len(set(place_ids)))
    if numeric_place_ids:
        place_id_numbers = [int(value) for value in place_ids]
        add_check(
            checks,
            "placeId continuous",
            place_id_numbers == list(range(1, len(place_id_numbers) + 1)),
            f"min={min(place_id_numbers)}, max={max(place_id_numbers)}",
        )

    add_check(checks, "place name not blank", all(row["name"].strip() for row in places))
    add_check(checks, "place category not blank", all(row["category"].strip() for row in places))
    add_check(checks, "place point not blank", all(row["point"].strip() for row in places))
    add_check(checks, "place point WKT format", all(point_is_valid(row["point"]) for row in places))
    bad_categories = sorted({row["category"] for row in places} - ALLOWED_CATEGORIES)
    add_check(checks, "place category enum", not bad_categories, ",".join(bad_categories))

    busan_bounds_bad: list[str] = []
    for row in places:
        parsed = extract_lng_lat(row["point"])
        if not parsed:
            continue
        lng, lat = parsed
        if not (128.7 <= lng <= 129.4 and 34.8 <= lat <= 35.5):
            busan_bounds_bad.append(row["placeId"])
    add_check(checks, "point within broad Busan bounds", not busan_bounds_bad, ",".join(busan_bounds_bad[:20]))

    feature_ids = [row["id"] for row in features]
    numeric_feature_ids = all(is_int_string(value) for value in feature_ids)
    add_check(checks, "feature id numeric", numeric_feature_ids)
    add_check(checks, "feature id unique", len(feature_ids) == len(set(feature_ids)))
    if numeric_feature_ids:
        feature_id_numbers = [int(value) for value in feature_ids]
        add_check(
            checks,
            "feature id continuous",
            feature_id_numbers == list(range(1, len(feature_id_numbers) + 1)),
            f"min={min(feature_id_numbers)}, max={max(feature_id_numbers)}",
        )

    feature_place_ids = [row["placeId"] for row in features]
    place_id_set = set(place_ids)
    missing_fk = sorted(set(feature_place_ids) - place_id_set)
    add_check(checks, "feature FK places.placeId", not missing_fk, ",".join(missing_fk[:20]))
    bad_feature_types = sorted({row["featureType"] for row in features} - ALLOWED_FEATURE_TYPES)
    add_check(checks, "featureType enum", not bad_feature_types, ",".join(bad_feature_types))
    add_check(checks, "isAvailable boolean true", {row["isAvailable"] for row in features} <= {"true", "TRUE", "True"})
    duplicate_place_features = [
        key for key, count in Counter((row["placeId"], row["featureType"]) for row in features).items() if count > 1
    ]
    add_check(checks, "unique(placeId, featureType)", not duplicate_place_features, str(duplicate_place_features[:20]))

    # Quality warnings are not DB blockers, but they are useful before team handoff.
    for row in places:
        if row["name"] in GENERIC_NAME_EXACT:
            warnings.append(
                {
                    "severity": "WARN",
                    "type": "GENERIC_NAME",
                    "placeId": row["placeId"],
                    "name": row["name"],
                    "category": row["category"],
                    "address": row["address"],
                    "detail": "서비스 표시명으로는 다소 포괄적인 이름",
                }
            )

    for (name, address), count in Counter((row["name"], row["address"]) for row in places).items():
        if count > 1:
            matched = [row for row in places if row["name"] == name and row["address"] == address]
            warnings.append(
                {
                    "severity": "WARN",
                    "type": "DUPLICATE_NAME_ADDRESS",
                    "placeId": "|".join(row["placeId"] for row in matched[:10]),
                    "name": name,
                    "category": "|".join(sorted({row["category"] for row in matched})),
                    "address": address,
                    "detail": f"동일 이름+주소 {count}건",
                }
            )

    for row in places:
        if row["category"] == "FOOD_CAFE" and any(token in row["name"] for token in ["빌딩", "건축물", "주택"]):
            warnings.append(
                {
                    "severity": "WARN",
                    "type": "FOOD_CAFE_NAME_LOOKS_STRUCTURAL",
                    "placeId": row["placeId"],
                    "name": row["name"],
                    "category": row["category"],
                    "address": row["address"],
                    "detail": "음식·카페인데 건물/구조물명처럼 보임",
                }
            )

    validation = {
        "status": "PASS" if all(check["passed"] for check in checks) else "FAIL",
        "checks": checks,
        "blockingFailureCount": sum(1 for check in checks if not check["passed"]),
        "qualityWarningCount": len(warnings),
    }
    return validation, warnings


def write_readme(summary: dict[str, Any], validation: dict[str, Any]) -> None:
    README_MD.write_text(
        "\n".join(
            [
                "# 편의시설 최종 ERD 반영본",
                "",
                "이 폴더는 PoC 검증을 거친 편의시설 최종 반영본이다.",
                "",
                "## 파일",
                "",
                "| 파일 | 용도 |",
                "|---|---|",
                "| `places_erd.csv` | DB `places` 반영 후보 |",
                "| `place_accessibility_features_erd.csv` | DB `place_accessibility_features` 반영 후보 |",
                "| `adopted_places_with_accessibility_final.csv` | 검증/추적용 통합 원본 |",
                "| `adopted_places_final.csv` | 장소 검토용 확장 테이블 |",
                "| `adopted_place_accessibility_final.csv` | 장소-접근성 검토용 확장 테이블 |",
                "| `facility_final_summary.json` | 최종 개수/분포 요약 |",
                "| `facility_final_validation_report.json` | PK/FK/enum/좌표 검증 결과 |",
                "| `facility_final_quality_warnings.csv` | DB 차단은 아니지만 확인할 품질 경고 |",
                "| `facility_final_checksums.json` | 산출 파일 SHA-256 |",
                "",
                "## 최종 개수",
                "",
                f"- 장소: `{summary['counts']['places']:,}`개",
                f"- 접근성 row: `{summary['counts']['accessibilityFeatures']:,}`개",
                f"- 접근성 있는 장소: `{summary['counts']['placesWithAccessibility']:,}`개",
                f"- 검증 상태: `{validation['status']}`",
                f"- 품질 경고: `{validation['qualityWarningCount']:,}`개",
                "",
                "## 주의",
                "",
                "- `facility_final_quality_warnings.csv`는 DB 반영 차단 사유가 아니다.",
                "- `공중화장실`처럼 이름이 포괄적인 데이터는 공공화장실 원본 특성 때문에 일부 남아 있다.",
                "- 최종 DB 반영 전에는 이 폴더의 `places_erd.csv`, `place_accessibility_features_erd.csv`를 기준으로 사용한다.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> None:
    DATA_FINAL.mkdir(parents=True, exist_ok=True)

    for key, source in SOURCE_FILES.items():
        shutil.copy2(source, FINAL_FILES[key])

    places = read_csv(FINAL_FILES["places_erd"])
    features = read_csv(FINAL_FILES["place_accessibility_features_erd"])
    adopted = read_csv(FINAL_FILES["adopted_places_with_accessibility"])

    validation, warnings = validate(places, features)

    category_counts = Counter(row["category"] for row in places)
    feature_counts = Counter(row["featureType"] for row in features)
    places_with_accessibility = len({row["placeId"] for row in features})
    district_counts = Counter(row.get("districtGu", "") for row in adopted)
    source_dataset_counts = Counter(row.get("sourceDataset", "") for row in adopted)

    summary = {
        "counts": {
            "places": len(places),
            "accessibilityFeatures": len(features),
            "placesWithAccessibility": places_with_accessibility,
            "placesWithoutAccessibility": len(places) - places_with_accessibility,
        },
        "categoryCounts": dict(sorted(category_counts.items())),
        "featureTypeCounts": dict(sorted(feature_counts.items())),
        "districtCounts": dict(sorted(district_counts.items())),
        "sourceDatasetCounts": dict(sorted(source_dataset_counts.items())),
        "validationStatus": validation["status"],
        "qualityWarningCount": len(warnings),
    }

    SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    VALIDATION_JSON.write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_csv(
        QUALITY_WARNINGS_CSV,
        warnings,
        ["severity", "type", "placeId", "name", "category", "address", "detail"],
    )

    checksums = {
        path.name: sha256_file(path)
        for path in [
            *FINAL_FILES.values(),
            SUMMARY_JSON,
            VALIDATION_JSON,
            QUALITY_WARNINGS_CSV,
        ]
    }
    CHECKSUMS_JSON.write_text(json.dumps(checksums, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_readme(summary, validation)

    print(json.dumps({"finalDir": str(DATA_FINAL), "summary": summary, "validation": validation}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
