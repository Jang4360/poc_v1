from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any


POC_ROOT = Path(__file__).resolve().parents[1]
FINAL = POC_ROOT / "data" / "final" / "facilities" / "adopted_places_with_accessibility_final.csv"
CROSS = POC_ROOT / "data" / "reports" / "facility_validation" / "facility_cross_validation_all.csv"
REPORT_DIR = POC_ROOT / "data" / "reports" / "facility_validation"
OUT_CSV = REPORT_DIR / "charging_station_current_quality_plan.csv"
OUT_CANDIDATES = REPORT_DIR / "charging_station_current_quality_candidates.csv"
OUT_SUMMARY = REPORT_DIR / "charging_station_current_quality_plan_summary.json"

MANUAL_DECISIONS = {
    "charging_station:9": (
        "RENAME_CANDIDATE",
        "장전2동행정복지센터",
        "POI 0.1m가 장전2동행정복지센터로 확인되어 원본 오타 보정",
    ),
    "charging_station:13": (
        "RENAME_CANDIDATE",
        "금정구종합사회복지관",
        "카카오/POI가 금정구종합사회복지관 계열로 확인되어 공식 표기 보정",
    ),
    "charging_station:39": (
        "RENAME_CANDIDATE",
        "남성경로당",
        "좌표 1m 이내 POI/카카오가 모두 남성경로당으로 확인되어 표시명 보정",
    ),
    "charging_station:43": (
        "RENAME_CANDIDATE",
        "초량2동행정복지센터",
        "카카오 2.7m 기준 현재 행정복지센터 명칭으로 보정",
    ),
    "charging_station:47": (
        "RENAME_CANDIDATE",
        "동구 장애인전동보조기기사전안전예방교육장",
        "카카오 0m 기준 지자체 구분이 포함된 공식 명칭으로 보정",
    ),
    "charging_station:65": (
        "RENAME_CANDIDATE",
        "온천2동행정복지센터",
        "카카오 2.9m 기준 현재 행정복지센터 명칭으로 보정",
    ),
    "charging_station:67": (
        "RENAME_CANDIDATE",
        "명장1동행정복지센터",
        "카카오 7.5m 기준 현재 행정복지센터 명칭으로 보정",
    ),
    "charging_station:103": (
        "RENAME_CANDIDATE",
        "사상생활사박물관",
        "POI/카카오 3m 이내 명칭 기준으로 보정",
    ),
    "charging_station:121": (
        "RENAME_CANDIDATE",
        "서부산권장애인스포츠센터",
        "POI 0m와 카카오 11m가 같은 명칭으로 확인되어 보정",
    ),
    "charging_station:133": (
        "RENAME_CANDIDATE",
        "부산대학교병원",
        "POI 8.4m 기준 공식 병원명으로 보정",
    ),
    "charging_station:140": (
        "RENAME_CANDIDATE",
        "수영구장애인협회",
        "POI 1.7m 기준 띄어쓰기 없는 기관명으로 보정",
    ),
    "charging_station:150": (
        "RENAME_CANDIDATE",
        "수영구장애인복지관",
        "POI/카카오 5m 이내에서 구체 시설명이 확인되어 보정",
    ),
    "charging_station:165": (
        "RENAME_CANDIDATE",
        "부산광역시의료원",
        "POI 2.9m 기준 공식 의료기관명으로 보정",
    ),
    "charging_station:196": (
        "RENAME_CANDIDATE",
        "해운대구장애인복지관",
        "POI 0.2m 기준 구체 시설명으로 보정",
    ),
    "charging_station:51": (
        "EXCLUDE_CANDIDATE",
        "",
        "charging_station:52와 같은 좌표/주소/시설인 중복 항목이며 52가 외부 POI 명칭과 일치",
    ),
    "charging_station:84": (
        "EXCLUDE_CANDIDATE",
        "",
        "charging_station:98 구포역과 같은 좌표/주소/시설인 중복 항목",
    ),
    "charging_station:167": (
        "EXCLUDE_CANDIDATE",
        "",
        "같은 주소의 charging_station:166 연산6동행정복지센터와 중복되고 POI/카카오도 연산6동으로 확인",
    ),
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def classify(row: dict[str, str]) -> tuple[str, str, str]:
    manual = MANUAL_DECISIONS.get(row["sourceKey"])
    if not manual:
        return "KEEP", "", "전동보장구 충전소 설치 장소명으로 유지"

    action, suggested_name, reason = manual
    if action == "RENAME_CANDIDATE" and row["name"] == suggested_name:
        return "KEEP", "", "이미 보정된 충전소 설치 장소명"
    return action, suggested_name, reason


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    charging_rows = [row for row in read_csv(FINAL) if row["dbCategory"] == "CHARGING_STATION"]
    cross_rows = {row["place_key"]: row for row in read_csv(CROSS)}

    out: list[dict[str, Any]] = []
    for row in charging_rows:
        cross = cross_rows.get(row["sourceKey"], {})
        action, suggested_name, reason = classify(row)
        out.append(
            {
                "placeId": row["placeId"],
                "sourceKey": row["sourceKey"],
                "name": row["name"],
                "districtGu": row["districtGu"],
                "address": row["address"],
                "point": row["point"],
                "recommendedAction": action,
                "suggestedName": suggested_name,
                "suggestionSource": "manual_rule" if action != "KEEP" else "",
                "suggestionCategory": cross.get("poi_category_label", "") or cross.get("kakao_category", ""),
                "suggestionDistanceM": cross.get("poi_distance_m", "") or cross.get("kakao_distance_m", ""),
                "reason": reason,
                "poiName": cross.get("poi_name", ""),
                "poiCategory": cross.get("poi_category_label", ""),
                "poiDistanceM": cross.get("poi_distance_m", ""),
                "kakaoPlaceName": cross.get("kakao_place_name", ""),
                "kakaoCategory": cross.get("kakao_category", ""),
                "kakaoDistanceM": cross.get("kakao_distance_m", ""),
            }
        )

    fieldnames = [
        "placeId",
        "sourceKey",
        "name",
        "districtGu",
        "address",
        "point",
        "recommendedAction",
        "suggestedName",
        "suggestionSource",
        "suggestionCategory",
        "suggestionDistanceM",
        "reason",
        "poiName",
        "poiCategory",
        "poiDistanceM",
        "kakaoPlaceName",
        "kakaoCategory",
        "kakaoDistanceM",
    ]
    candidates = [row for row in out if row["recommendedAction"] != "KEEP"]
    write_csv(OUT_CSV, out, fieldnames)
    write_csv(OUT_CANDIDATES, candidates, fieldnames)

    summary = {
        "total": len(out),
        "candidateCount": len(candidates),
        "byAction": dict(Counter(row["recommendedAction"] for row in out)),
        "outputs": {"plan": str(OUT_CSV), "candidates": str(OUT_CANDIDATES)},
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
