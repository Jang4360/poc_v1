import argparse
import csv
import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


DISTRICT = "강서구"
TARGET_TYPE = "facility"


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


def is_yes(value):
    return str(value).strip().upper() == "Y"


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

    if action in {"REMOVE_REVIEW", "REVIEW_OR_REMOVE"}:
        if action == "REVIEW_OR_REMOVE":
            return (
                "REVIEW",
                "근거 약함: 카카오/POI는 있으나 내부 화장실·상위 시설 맥락이라 지도 확인 필요",
            )
        if poi_status in {"MATCH_STRONG", "MATCH_MEDIUM"} and poi_distance <= 80:
            return (
                "REVIEW",
                "근거 약함: 카카오 없음/약함, POI만 근거리라 지도 확인 필요",
            )
        return "REMOVE", "지도/POI 근거 약함"

    kakao_distance_limit = 120 if category in {"TOILET", "TOURIST_SPOT"} else 80
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


def compact_evidence(evidence):
    kakao_name = evidence.get("kakao_place_name", "")
    poi_name = evidence.get("poi_name", "")
    kakao_distance = evidence.get("kakao_distance_m", "")
    poi_distance = evidence.get("poi_distance_m", "")
    parts = []
    if kakao_name:
        parts.append(f"카카오={kakao_name}({kakao_distance}m)")
    if poi_name:
        parts.append(f"POI={poi_name}({poi_distance}m)")
    return "; ".join(parts)


def make_record(adopted, evidence, status, reason, updated_at):
    place_id = adopted["placeId"]
    key = f"{TARGET_TYPE}:{place_id}"
    status_labels = {
        "KEEP": "유지",
        "REMOVE": "제거",
        "FIX": "수정",
        "REVIEW": "보류",
    }
    evidence_text = compact_evidence(evidence)
    note = f"[지도/POI 1차판정] {reason}"
    if evidence_text:
        note = f"{note} / {evidence_text}"

    return {
        "key": key,
        "targetType": TARGET_TYPE,
        "targetId": str(place_id),
        "districtGu": adopted["districtGu"],
        "name": adopted["name"],
        "category": adopted["dbCategory"],
        "status": status,
        "statusLabel": status_labels.get(status, status),
        "note": note,
        "lat": adopted["lat"],
        "lng": adopted["lng"],
        "fixedLat": "",
        "fixedLng": "",
        "fixedSource": "",
        "fixedSourceUrl": "",
        "kakaoUrlX": "",
        "kakaoUrlY": "",
        "sourceKey": adopted["sourceKey"],
        "placeId": str(place_id),
        "ufid": "",
        "sourceId": adopted["sourceKey"],
        "updatedAt": updated_at,
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
    out_csv = root / "data" / "reports" / "manual_review" / "gangseo_facility_map_review_decisions.csv"
    out_summary = root / "data" / "reports" / "manual_review" / "gangseo_facility_map_review_summary.json"
    out_seed = root / "assets" / "data" / "manual-review-seed-data.js"

    adopted_rows = [row for row in read_csv(adopted_path) if row.get("districtGu") == DISTRICT]
    evidence_by_source_key = {
        row["sourceKey"]: row
        for row in read_csv(validation_path)
        if row.get("districtGu") == DISTRICT
    }

    missing = [row["sourceKey"] for row in adopted_rows if row["sourceKey"] not in evidence_by_source_key]
    if missing:
        raise RuntimeError(f"검증 리포트에 없는 sourceKey가 있습니다: {missing[:10]}")

    updated_at = datetime.now(timezone.utc).isoformat()
    records = []
    for adopted in adopted_rows:
        evidence = evidence_by_source_key[adopted["sourceKey"]]
        status, reason = decision_for(adopted, evidence)
        records.append(make_record(adopted, evidence, status, reason, updated_at))

    records.sort(key=lambda row: (row["status"], row["category"], row["name"]))
    write_csv(out_csv, records)
    write_seed_js(out_seed, records)

    summary = {
        "district": DISTRICT,
        "targetType": TARGET_TYPE,
        "sourceAdoptedCsv": str(adopted_path),
        "sourceValidationCsv": str(validation_path),
        "outputCsv": str(out_csv),
        "outputSeedJs": str(out_seed),
        "total": len(records),
        "byStatus": dict(Counter(record["status"] for record in records)),
        "byCategory": dict(Counter(record["category"] for record in records)),
        "byEvidenceAction": dict(Counter(record["evidenceAction"] for record in records)),
        "updatedAt": updated_at,
    }
    out_summary.parent.mkdir(parents=True, exist_ok=True)
    out_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
