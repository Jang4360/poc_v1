import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


TARGET_TYPE = "facility"
STATUS_LABELS = {
    "KEEP": "유지",
    "REMOVE": "제거",
    "FIX": "수정",
    "REVIEW": "보류",
}


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def safe_float(value, default=math.inf):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except ValueError:
        return default


def fmt_distance(value):
    number = safe_float(value)
    if not math.isfinite(number):
        return ""
    return f"{number:.1f}"


def is_yes(value):
    return str(value).strip().upper() == "Y"


def is_area_like(adopted):
    text = " ".join(
        [
            adopted.get("name", ""),
            adopted.get("facilityCategory", ""),
            adopted.get("rawFacilityType", ""),
            adopted.get("address", ""),
        ]
    )
    keywords = [
        "공원",
        "시장",
        "해수욕장",
        "유원지",
        "관광특구",
        "거리",
        "등산로",
        "생태공원",
        "체육공원",
        "광장",
    ]
    return adopted.get("dbCategory") == "TOURIST_SPOT" or any(keyword in text for keyword in keywords)


def is_internal_facility(adopted, evidence):
    if adopted.get("dbCategory") == "TOILET" and adopted.get("toiletScope") == "FACILITY_TOILET":
        return True
    reason = evidence.get("refreshReason", "")
    return "내부 화장실" in reason


def decision_for(adopted, evidence):
    category = adopted["dbCategory"]
    source_key = adopted["sourceKey"]
    action = evidence.get("recommendedAction", "")
    kakao_status = evidence.get("kakao_best_status", "")
    poi_status = evidence.get("poi_match_status", "")
    kakao_distance = safe_float(evidence.get("kakao_distance_m"))
    poi_distance = safe_float(evidence.get("poi_distance_m"))
    kakao_name_similarity = safe_float(evidence.get("kakao_name_similarity"), 0)
    poi_label = evidence.get("poi_category_label", "") or ""

    if action == "REVIEW_OR_REMOVE":
        return (
            "REVIEW",
            "근거 약함: 카카오/POI는 있으나 내부 화장실·상위 시설 맥락이라 지도 확인 필요",
        )

    if action == "REMOVE_REVIEW":
        if poi_status in {"MATCH_STRONG", "MATCH_MEDIUM"} and poi_distance <= 80:
            return "REVIEW", "근거 약함: 카카오 없음/약함, POI만 근거리라 지도 확인 필요"
        return "REMOVE", "지도/POI 근거 약함"

    kakao_distance_limit = 120 if category in {"TOILET", "TOURIST_SPOT"} or is_area_like(adopted) else 80
    if (
        kakao_status in {"KAKAO_STRONG", "KAKAO_MEDIUM"}
        and kakao_distance <= kakao_distance_limit
        and kakao_name_similarity >= 55
    ):
        return "KEEP", "카카오 지도에서 동일/유사 명칭 근거리 확인"

    if action in {"KEEP", "RENAME_REVIEW"} and is_yes(evidence.get("kakaoExists")) and kakao_distance <= 120:
        return "KEEP", "카카오 지도 근거 확인"

    if category == "TOILET" and source_key.startswith("public_toilet:"):
        if poi_status in {"MATCH_STRONG", "MATCH_MEDIUM"} and ("공중화장실" in poi_label or poi_distance <= 80):
            return "KEEP", "공중화장실/시설 POI 근거리 확인"
        if kakao_status in {"KAKAO_STRONG", "KAKAO_MEDIUM", "KAKAO_WEAK"} and kakao_distance <= 120:
            return "KEEP", "카카오 지도에서 상위 시설/공원 근거리 확인"
        return "REVIEW", "화장실은 지도명만으로 실재/개방 여부 확정 어려움"

    if poi_status in {"MATCH_STRONG", "MATCH_MEDIUM"} and poi_distance <= 80:
        if action in {"POI_ONLY_CATEGORY_RECHECK", "CATEGORY_REVIEW"}:
            return "KEEP", "POI 근거리 확인: 카테고리는 후순위 재확인 대상"
        return "KEEP", "POI 근거리 확인"

    if action in {"MANUAL_REVIEW", "POI_ONLY_CATEGORY_RECHECK", "POI_ONLY_RECHECK", "CATEGORY_REVIEW"}:
        return "REVIEW", "지도 근거는 있으나 이름/분류/거리 확인 필요"

    return "REVIEW", "자동 판정 기준 밖"


def coordinate_evidence(adopted, evidence):
    category = adopted.get("dbCategory", "")
    kakao_distance = safe_float(evidence.get("kakao_distance_m"))
    poi_distance = safe_float(evidence.get("poi_distance_m"))
    kakao_name = evidence.get("kakao_place_name", "")
    poi_name = evidence.get("poi_name", "")
    kakao_status = evidence.get("kakao_best_status", "")
    poi_status = evidence.get("poi_match_status", "")

    if category == "TOILET":
        if "화장실" in kakao_name and math.isfinite(kakao_distance):
            return "KAKAO", kakao_distance, kakao_name
        if poi_status in {"MATCH_STRONG", "MATCH_MEDIUM", "MATCH_WEAK", "NEARBY_ONLY"} and math.isfinite(poi_distance):
            return "POI", poi_distance, poi_name
        if math.isfinite(kakao_distance):
            return "KAKAO", kakao_distance, kakao_name
        return "", math.inf, ""

    if evidence.get("primarySource") == "KAKAO" and kakao_status != "KAKAO_NO_RESULT" and math.isfinite(kakao_distance):
        return "KAKAO", kakao_distance, kakao_name
    if math.isfinite(poi_distance):
        return "POI", poi_distance, poi_name
    if math.isfinite(kakao_distance):
        return "KAKAO", kakao_distance, kakao_name
    return "", math.inf, ""


def coordinate_quality_for(adopted, evidence, status):
    if status == "REMOVE":
        return "BAD", "제거 후보라 좌표 보정 대상에서 제외", "", ""

    if is_internal_facility(adopted, evidence):
        source, distance, name = coordinate_evidence(adopted, evidence)
        distance_text = fmt_distance(distance)
        reason = "건물/시설 내부 편의시설이라 지도 좌표만으로 접근 가능한 입구를 확정할 수 없음"
        if source and distance_text:
            reason = f"{reason}; {source} 근거 {name} {distance_text}m"
        return "INTERNAL", reason, source, distance_text

    source, distance, name = coordinate_evidence(adopted, evidence)
    distance_text = fmt_distance(distance)
    if not math.isfinite(distance):
        return "BAD", "카카오/POI 거리 근거 없음", source, distance_text

    if distance <= 30:
        return "GOOD", f"{source} 근거 {name} {distance_text}m: 원본 좌표가 지도상 시설 근처", source, distance_text

    if distance <= 80:
        return "CHECK", f"{source} 근거 {name} {distance_text}m: 좌표는 근처지만 입구/정확 위치 확인 필요", source, distance_text

    if is_area_like(adopted) and distance <= 200:
        return "CHECK", f"{source} 근거 {name} {distance_text}m: 공원/시장/관광지 등 영역형 시설이라 대표 접근점 확인 필요", source, distance_text

    return "BAD", f"{source} 근거 {name} {distance_text}m: 원본 좌표와 지도 근거가 멀어 위치 보정 필요", source, distance_text


def compact_evidence(evidence):
    parts = []
    if evidence.get("kakao_place_name"):
        parts.append(f"카카오={evidence.get('kakao_place_name')}({evidence.get('kakao_distance_m')}m)")
    if evidence.get("poi_name"):
        parts.append(f"POI={evidence.get('poi_name')}({evidence.get('poi_distance_m')}m)")
    return "; ".join(parts)


def make_record(adopted, evidence, status, reason, coordinate_quality, coordinate_reason, coordinate_source, coordinate_distance, updated_at):
    place_id = adopted["placeId"]
    key = f"{TARGET_TYPE}:{place_id}"
    evidence_text = compact_evidence(evidence)
    note = f"[지도/POI 1차판정] {reason} / [좌표품질:{coordinate_quality}] {coordinate_reason}"
    if evidence_text:
        note = f"{note} / {evidence_text}"

    return {
        "key": key,
        "targetType": TARGET_TYPE,
        "targetId": str(place_id),
        "districtGu": adopted.get("districtGu", ""),
        "name": adopted.get("name", ""),
        "category": adopted.get("dbCategory", ""),
        "status": status,
        "statusLabel": STATUS_LABELS.get(status, status),
        "note": note,
        "lat": adopted.get("lat", ""),
        "lng": adopted.get("lng", ""),
        "fixedLat": "",
        "fixedLng": "",
        "fixedSource": "",
        "fixedSourceUrl": "",
        "kakaoUrlX": "",
        "kakaoUrlY": "",
        "sourceKey": adopted.get("sourceKey", ""),
        "placeId": str(place_id),
        "ufid": "",
        "sourceId": adopted.get("sourceKey", ""),
        "updatedAt": updated_at,
        "coordinateQuality": coordinate_quality,
        "coordinateQualityReason": coordinate_reason,
        "coordinateEvidenceSource": coordinate_source,
        "coordinateEvidenceDistanceM": coordinate_distance,
        "evidenceAction": evidence.get("recommendedAction", ""),
        "evidencePrimarySource": evidence.get("primarySource", ""),
        "kakaoStatus": evidence.get("kakao_best_status", ""),
        "kakaoPlaceName": evidence.get("kakao_place_name", ""),
        "kakaoDistanceM": evidence.get("kakao_distance_m", ""),
        "poiStatus": evidence.get("poi_match_status", ""),
        "poiName": evidence.get("poi_name", ""),
        "poiDistanceM": evidence.get("poi_distance_m", ""),
    }


def write_csv(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = [
        "key",
        "targetType",
        "targetId",
        "districtGu",
        "name",
        "category",
        "status",
        "statusLabel",
        "coordinateQuality",
        "coordinateQualityReason",
        "coordinateEvidenceSource",
        "coordinateEvidenceDistanceM",
        "note",
        "lat",
        "lng",
        "fixedLat",
        "fixedLng",
        "fixedSource",
        "fixedSourceUrl",
        "kakaoUrlX",
        "kakaoUrlY",
        "sourceKey",
        "placeId",
        "ufid",
        "sourceId",
        "updatedAt",
        "evidenceAction",
        "evidencePrimarySource",
        "kakaoStatus",
        "kakaoPlaceName",
        "kakaoDistanceM",
        "poiStatus",
        "poiName",
        "poiDistanceM",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def write_seed_js(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    seed = {record["key"]: record for record in records}
    path.write_text(
        "window.MANUAL_REVIEW_SEED = "
        + json.dumps(seed, ensure_ascii=False, indent=2)
        + ";\n",
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=r"C:\Users\SSAFY\Desktop\poc_submit")
    parser.add_argument(
        "--validation-csv",
        default=r"C:\Users\SSAFY\Desktop\poc\data\reports\facility_validation\facility_kakao_poi_existence_rule_all.csv",
    )
    args = parser.parse_args()

    root = Path(args.root)
    adopted_path = root / "data" / "adopted" / "adopted_places_with_accessibility.csv"
    validation_path = Path(args.validation_csv)
    out_dir = root / "data" / "reports" / "manual_review"
    out_all_csv = out_dir / "facility_map_review_decisions_all.csv"
    out_attention_csv = out_dir / "facility_map_review_attention_targets.csv"
    out_hard_csv = out_dir / "facility_map_review_hard_targets.csv"
    out_internal_csv = out_dir / "facility_map_review_internal_targets.csv"
    out_summary = out_dir / "facility_map_review_summary.json"
    out_seed = root / "assets" / "data" / "manual-review-seed-data.js"

    adopted_rows = read_csv(adopted_path)
    evidence_by_source_key = {
        row["sourceKey"]: row
        for row in read_csv(validation_path)
        if row.get("sourceKey")
    }

    updated_at = datetime.now(timezone.utc).isoformat()
    records = []
    missing = []
    for adopted in adopted_rows:
        evidence = evidence_by_source_key.get(adopted["sourceKey"])
        if not evidence:
            missing.append(adopted["sourceKey"])
            evidence = {}
            status, reason = "REVIEW", "검증 리포트 매칭 없음"
        else:
            status, reason = decision_for(adopted, evidence)
        coordinate_quality, coordinate_reason, coordinate_source, coordinate_distance = coordinate_quality_for(adopted, evidence, status)
        records.append(
            make_record(
                adopted,
                evidence,
                status,
                reason,
                coordinate_quality,
                coordinate_reason,
                coordinate_source,
                coordinate_distance,
                updated_at,
            )
        )

    records.sort(key=lambda row: (row["districtGu"], row["status"], row["coordinateQuality"], row["category"], row["name"]))
    attention_records = [
        record for record in records
        if record["status"] != "KEEP" or record["coordinateQuality"] != "GOOD"
    ]
    hard_records = [
        record for record in records
        if record["status"] != "KEEP" or record["coordinateQuality"] in {"BAD", "CHECK"}
    ]
    internal_records = [
        record for record in records
        if record["status"] == "KEEP" and record["coordinateQuality"] == "INTERNAL"
    ]

    write_csv(out_all_csv, records)
    write_csv(out_attention_csv, attention_records)
    write_csv(out_hard_csv, hard_records)
    write_csv(out_internal_csv, internal_records)
    write_seed_js(out_seed, records)

    by_district = defaultdict(Counter)
    by_district_quality = defaultdict(Counter)
    for record in records:
        district = record["districtGu"] or "미분류"
        by_district[district][record["status"]] += 1
        by_district_quality[district][record["coordinateQuality"]] += 1

    summary = {
        "targetType": TARGET_TYPE,
        "sourceAdoptedCsv": str(adopted_path),
        "sourceValidationCsv": str(validation_path),
        "outputAllCsv": str(out_all_csv),
        "outputAttentionCsv": str(out_attention_csv),
        "outputHardCsv": str(out_hard_csv),
        "outputInternalCsv": str(out_internal_csv),
        "outputSeedJs": str(out_seed),
        "total": len(records),
        "attentionTotal": len(attention_records),
        "hardReviewTotal": len(hard_records),
        "internalReferenceTotal": len(internal_records),
        "missingEvidenceCount": len(missing),
        "missingEvidenceSample": missing[:20],
        "byStatus": dict(Counter(record["status"] for record in records)),
        "byCoordinateQuality": dict(Counter(record["coordinateQuality"] for record in records)),
        "byCategory": dict(Counter(record["category"] for record in records)),
        "byEvidenceAction": dict(Counter(record["evidenceAction"] for record in records)),
        "byDistrictStatus": {district: dict(counter) for district, counter in sorted(by_district.items())},
        "byDistrictCoordinateQuality": {district: dict(counter) for district, counter in sorted(by_district_quality.items())},
        "updatedAt": updated_at,
    }
    out_summary.parent.mkdir(parents=True, exist_ok=True)
    out_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
