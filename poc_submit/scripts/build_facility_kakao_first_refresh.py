from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import cross_validate_facilities_with_poi_kakao as kakao_matcher
import match_facility_with_poi as poi_matcher


POC_ROOT = Path(__file__).resolve().parents[1]
ADOPTED_CSV = POC_ROOT / "data" / "adopted" / "adopted_places_with_accessibility.csv"
VALIDATION_DIR = POC_ROOT / "data" / "reports" / "facility_validation"

OUT_ALL = VALIDATION_DIR / "facility_kakao_first_refresh_all.csv"
OUT_REVIEW = VALIDATION_DIR / "facility_kakao_first_refresh_review.csv"
OUT_RENAME = VALIDATION_DIR / "facility_kakao_first_refresh_rename_candidates.csv"
OUT_POI_FALLBACK = VALIDATION_DIR / "facility_kakao_first_refresh_poi_fallback.csv"
OUT_EXCLUDE = VALIDATION_DIR / "facility_kakao_first_refresh_remove_candidates.csv"
OUT_SUMMARY_CSV = VALIDATION_DIR / "facility_kakao_first_refresh_summary.csv"
OUT_SUMMARY_JSON = VALIDATION_DIR / "facility_kakao_first_refresh_summary.json"

KAKAO_STRONG_STATUSES = {"KAKAO_STRONG", "KAKAO_MEDIUM"}
POI_STRONG_STATUSES = {"MATCH_STRONG", "MATCH_MEDIUM"}

BASE_FIELDS = [
    "sourceKey",
    "sourceDataset",
    "placeId",
    "name",
    "uiCategory",
    "dbCategory",
    "districtGu",
    "address",
    "lat",
    "lng",
    "providerPlaceId",
    "accessibilityLabels",
    "erdAccessibilityLabels",
    "reviewPriority",
    "reviewScore",
]

KAKAO_FIELDS = [
    "kakao_best_status",
    "kakao_best_score",
    "kakao_best_query",
    "kakao_result_count",
    "kakao_place_id",
    "kakao_place_name",
    "kakao_road_address",
    "kakao_jibun_address",
    "kakao_category",
    "kakao_distance_m",
    "kakao_name_similarity",
    "kakao_address_match",
    "kakao_category_assessment",
    "kakao_match_reason",
]

POI_FIELDS = [
    "poi_match_status",
    "poi_match_score",
    "poi_distance_m",
    "poi_candidate_count_300m",
    "poi_id",
    "poi_name",
    "poi_road_address",
    "poi_jibun_address",
    "poi_category_code",
    "poi_category_label",
    "poi_name_similarity",
    "poi_address_match",
    "poi_category_assessment",
    "poi_match_reason",
]

DECISION_FIELDS = [
    "kakaoFirstStatus",
    "recommendedAction",
    "needsHumanReview",
    "refreshReason",
    "suggestedName",
    "suggestedAddress",
    "suggestedProviderPlaceId",
    "evidencePriority",
]

MATCH_CATEGORY_ALIASES = {
    "공중화장실": "화장실",
    "시설 내 화장실": "화장실",
    "공공기관": "행정·공공기관",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows([{field: row.get(field, "") for field in fieldnames} for row in rows])


def to_match_row(row: dict[str, str]) -> dict[str, str]:
    ui_category = row.get("uiCategory", "")
    return {
        "validation_priority": row.get("reviewPriority", ""),
        "recommended_action": "",
        "validation_types": "",
        "validation_reasons": "",
        "place_key": row.get("sourceKey", ""),
        "source_dataset": row.get("sourceDataset", ""),
        "source_place_id": row.get("sourceKey", "").split(":", 1)[1] if ":" in row.get("sourceKey", "") else "",
        "place_name": row.get("name", ""),
        "ui_category": MATCH_CATEGORY_ALIASES.get(ui_category, ui_category),
        "raw_category": row.get("rawFacilityType", ""),
        "source_category": row.get("dbCategory", ""),
        "district_gu": row.get("districtGu", ""),
        "address": row.get("address", ""),
        "latitude": row.get("lat", ""),
        "longitude": row.get("lng", ""),
        "accessibility_count": row.get("erdAccessibilityCount", row.get("accessibilityCount", "")),
        "accessibility_type_labels": row.get("erdAccessibilityLabels", row.get("accessibilityLabels", "")),
    }


def parse_float(value: Any, default: float = 999999.0) -> float:
    try:
        if value in (None, ""):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def materially_different_name(source_name: str, kakao_name: str, name_similarity: float) -> bool:
    if not kakao_name:
        return False
    source_norm = kakao_matcher.normalize_text(source_name)
    kakao_norm = kakao_matcher.normalize_text(kakao_name)
    if source_norm == kakao_norm:
        return False
    if kakao_matcher.is_generic_name(source_name):
        return True
    if source_norm in kakao_norm or kakao_norm in source_norm:
        return False
    if name_similarity < 0.72:
        return True
    return len(kakao_norm) >= 4


def decision(row: dict[str, str]) -> dict[str, str]:
    ui_category = row.get("uiCategory", "")
    match_category = MATCH_CATEGORY_ALIASES.get(ui_category, ui_category)
    source_name = row.get("name", "")
    kakao_status = row.get("kakao_best_status", "")
    poi_status = row.get("poi_match_status", "")
    kakao_category_assessment = row.get("kakao_category_assessment", "")
    poi_category_assessment = row.get("poi_category_assessment", "")
    kakao_name = row.get("kakao_place_name", "")
    kakao_similarity = parse_float(row.get("kakao_name_similarity"), 0.0)
    kakao_distance = parse_float(row.get("kakao_distance_m"))

    if kakao_status in KAKAO_STRONG_STATUSES:
        if match_category == "화장실" and row.get("kakao_category_assessment") == "INTERNAL_TOILET_CONTEXT":
            return {
                "kakaoFirstStatus": "KAKAO_INTERNAL_CONTEXT",
                "recommendedAction": "REVIEW_OR_REMOVE",
                "needsHumanReview": "Y",
                "refreshReason": "카카오맵에서는 주유소/병원/아파트/건물 등 내부 화장실 맥락으로 확인됨",
                "suggestedName": kakao_name,
                "suggestedAddress": row.get("kakao_road_address") or row.get("kakao_jibun_address"),
                "suggestedProviderPlaceId": row.get("kakao_place_id", ""),
                "evidencePriority": "KAKAO",
            }
        if materially_different_name(source_name, kakao_name, kakao_similarity):
            return {
                "kakaoFirstStatus": "KAKAO_RENAME_CANDIDATE",
                "recommendedAction": "RENAME_REVIEW",
                "needsHumanReview": "Y",
                "refreshReason": "카카오맵에서 더 최신/구체적인 명칭 후보가 강하게 확인됨",
                "suggestedName": kakao_name,
                "suggestedAddress": row.get("kakao_road_address") or row.get("kakao_jibun_address"),
                "suggestedProviderPlaceId": row.get("kakao_place_id", ""),
                "evidencePriority": "KAKAO",
            }
        if kakao_category_assessment == "CATEGORY_CHECK" and match_category not in {"전동보장구 충전소"}:
            return {
                "kakaoFirstStatus": "KAKAO_CATEGORY_REVIEW",
                "recommendedAction": "CATEGORY_REVIEW",
                "needsHumanReview": "Y",
                "refreshReason": "카카오맵 장소는 가깝지만 서비스 카테고리와 직접 일치하지 않음",
                "suggestedName": kakao_name,
                "suggestedAddress": row.get("kakao_road_address") or row.get("kakao_jibun_address"),
                "suggestedProviderPlaceId": row.get("kakao_place_id", ""),
                "evidencePriority": "KAKAO",
            }
        return {
            "kakaoFirstStatus": "KAKAO_CONFIRMED",
            "recommendedAction": "KEEP",
            "needsHumanReview": "N",
            "refreshReason": f"카카오맵 우선 매칭 강함: {kakao_status}, distance={kakao_distance:.1f}m",
            "suggestedName": kakao_name,
            "suggestedAddress": row.get("kakao_road_address") or row.get("kakao_jibun_address"),
            "suggestedProviderPlaceId": row.get("kakao_place_id", ""),
            "evidencePriority": "KAKAO",
        }

    if poi_status in POI_STRONG_STATUSES:
        action = "POI_ONLY_RECHECK"
        needs_review = "Y"
        status = "POI_ONLY_RECHECK"
        reason = "카카오맵 강한 근거는 없고 POI에서만 보조 확인됨. POI는 과거명/구 데이터 가능성이 있어 재확인 필요"
        if poi_category_assessment == "CATEGORY_CHECK":
            action = "POI_ONLY_CATEGORY_RECHECK"
            needs_review = "Y"
            status = "POI_ONLY_CATEGORY_RECHECK"
            reason = "카카오맵 강한 근거가 없고 POI 카테고리도 서비스 카테고리와 직접 일치하지 않음"
        return {
            "kakaoFirstStatus": status,
            "recommendedAction": action,
            "needsHumanReview": needs_review,
            "refreshReason": reason,
            "suggestedName": row.get("poi_name", ""),
            "suggestedAddress": row.get("poi_road_address") or row.get("poi_jibun_address"),
            "suggestedProviderPlaceId": row.get("providerPlaceId", ""),
            "evidencePriority": "POI_ONLY_RECHECK",
        }

    if kakao_status == "KAKAO_NO_RESULT" and poi_status in {"NO_MATCH", "NEARBY_ONLY"}:
        return {
            "kakaoFirstStatus": "NO_CURRENT_EVIDENCE",
            "recommendedAction": "REMOVE_REVIEW",
            "needsHumanReview": "Y",
            "refreshReason": "카카오맵과 POI 모두 강한 근거가 없어 최신성/존재 여부 확인 필요",
            "suggestedName": "",
            "suggestedAddress": "",
            "suggestedProviderPlaceId": "",
            "evidencePriority": "NONE",
        }

    return {
        "kakaoFirstStatus": "KAKAO_WEAK_REVIEW",
        "recommendedAction": "MANUAL_REVIEW",
        "needsHumanReview": "Y",
        "refreshReason": "카카오맵 근거가 약하거나 주변 후보만 확인됨",
        "suggestedName": kakao_name or row.get("poi_name", ""),
        "suggestedAddress": row.get("kakao_road_address") or row.get("kakao_jibun_address") or row.get("poi_road_address") or row.get("poi_jibun_address"),
        "suggestedProviderPlaceId": row.get("kakao_place_id") or row.get("providerPlaceId", ""),
        "evidencePriority": "KAKAO_WEAK",
    }


def validate_one(row: dict[str, str], pois: list[dict[str, Any]], grid: dict[tuple[int, int], list[int]]) -> dict[str, str]:
    match_row = to_match_row(row)
    kakao = kakao_matcher.search_kakao_best(match_row)
    poi = poi_matcher.match_facility(match_row, pois, grid)
    output = {
        **{field: row.get(field, "") for field in BASE_FIELDS},
        **kakao,
        **poi,
    }
    return {**output, **decision(output)}


def write_summary(rows: list[dict[str, str]], elapsed_sec: float) -> None:
    summary_rows: list[dict[str, str]] = []
    for group_name, key in [
        ("kakaoFirstStatus", "kakaoFirstStatus"),
        ("recommendedAction", "recommendedAction"),
        ("needsHumanReview", "needsHumanReview"),
        ("uiCategory", "uiCategory"),
        ("uiCategoryByAction", "uiCategory|recommendedAction"),
        ("kakaoStatus", "kakao_best_status"),
        ("poiStatus", "poi_match_status"),
        ("evidencePriority", "evidencePriority"),
    ]:
        if "|" in key:
            left, right = key.split("|", 1)
            counter = Counter(f"{row.get(left, '')} / {row.get(right, '')}" for row in rows)
        else:
            counter = Counter(row.get(key, "") for row in rows)
        for name, count in sorted(counter.items(), key=lambda item: (-item[1], item[0])):
            summary_rows.append({"group": group_name, "name": name, "count": str(count)})

    write_csv(OUT_SUMMARY_CSV, summary_rows, ["group", "name", "count"])
    payload = {
        "total": len(rows),
        "elapsedSec": round(elapsed_sec, 1),
        "kakaoFirstStatusCounts": dict(Counter(row["kakaoFirstStatus"] for row in rows)),
        "recommendedActionCounts": dict(Counter(row["recommendedAction"] for row in rows)),
        "needsHumanReviewCounts": dict(Counter(row["needsHumanReview"] for row in rows)),
        "kakaoStatusCounts": dict(Counter(row["kakao_best_status"] for row in rows)),
        "poiStatusCounts": dict(Counter(row["poi_match_status"] for row in rows)),
        "files": {
            "all": str(OUT_ALL),
            "review": str(OUT_REVIEW),
            "renameCandidates": str(OUT_RENAME),
            "poiFallback": str(OUT_POI_FALLBACK),
            "removeCandidates": str(OUT_EXCLUDE),
            "summaryCsv": str(OUT_SUMMARY_CSV),
            "summaryJson": str(OUT_SUMMARY_JSON),
        },
    }
    OUT_SUMMARY_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    started = time.time()
    VALIDATION_DIR.mkdir(parents=True, exist_ok=True)

    kakao_matcher.load_cache()
    pois = poi_matcher.load_pois()
    grid = poi_matcher.build_grid(pois)

    rows = read_csv(ADOPTED_CSV)
    if args.limit:
        rows = rows[: args.limit]

    results: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = [executor.submit(validate_one, row, pois, grid) for row in rows]
        for index, future in enumerate(as_completed(futures), start=1):
            results.append(future.result())
            if index % 100 == 0 or index == len(rows):
                print(f"validated {index}/{len(rows)} cache={len(kakao_matcher.search_cache)} elapsed={time.time() - started:.1f}s")

    order = {row["sourceKey"]: index for index, row in enumerate(rows)}
    results.sort(key=lambda row: order.get(row["sourceKey"], 999999))
    fieldnames = [*BASE_FIELDS, *KAKAO_FIELDS, *POI_FIELDS, *DECISION_FIELDS]

    write_csv(OUT_ALL, results, fieldnames)
    write_csv(OUT_REVIEW, [row for row in results if row["needsHumanReview"] == "Y"], fieldnames)
    write_csv(OUT_RENAME, [row for row in results if row["recommendedAction"] == "RENAME_REVIEW"], fieldnames)
    write_csv(OUT_POI_FALLBACK, [row for row in results if row["evidencePriority"] == "POI_FALLBACK"], fieldnames)
    write_csv(OUT_EXCLUDE, [row for row in results if row["recommendedAction"] == "REMOVE_REVIEW"], fieldnames)
    write_summary(results, time.time() - started)

    print("done", len(results))
    for action, count in sorted(Counter(row["recommendedAction"] for row in results).items()):
        print(action, count)
    print("needsHumanReview", dict(Counter(row["needsHumanReview"] for row in results)))


if __name__ == "__main__":
    main()
