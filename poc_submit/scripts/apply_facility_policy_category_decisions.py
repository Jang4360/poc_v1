from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


LABEL_BY_CATEGORY = {
    "TOILET": "화장실",
    "RESTAURANT": "음식·카페",
    "TOURIST_SPOT": "관광지",
    "ACCOMMODATION": "숙박",
    "CHARGING_STATION": "전동보장구 충전소",
    "HEALTHCARE": "의료·보건",
    "WELFARE": "복지·돌봄",
    "PUBLIC_OFFICE": "공공기관",
    "ETC": "기타 편의시설",
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


def load_js_assignment(path: Path, marker: str) -> Any:
    text = path.read_text(encoding="utf-8").strip()
    prefix = f"window.{marker} = "
    if not text.startswith(prefix):
        raise ValueError(f"Unexpected JS data format: {path}")
    if text.endswith(";"):
        text = text[:-1]
    return json.loads(text[len(prefix) :])


def write_js_assignment(path: Path, marker: str, payload: Any) -> None:
    path.write_text(
        f"window.{marker} = " + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )


def has_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def mapped_category_from_kakao(kakao_category: str) -> str:
    if re.search(r"화장실", kakao_category):
        return "TOILET"
    if re.search(r"휠체어|보장구", kakao_category):
        return "CHARGING_STATION"
    if re.search(r"음식점|한식|중식|일식|양식|분식|카페|커피|술집|주점|제과|디저트|패스트푸드|간식", kakao_category):
        return "RESTAURANT"
    if re.search(r"호텔|모텔|숙박|펜션|콘도|리조트|게스트하우스", kakao_category):
        return "ACCOMMODATION"
    if re.search(r"병원|의원|치과|한의원|보건소|의료|약국|요양병원", kakao_category):
        return "HEALTHCARE"
    if re.search(r"복지|경로당|요양원|장애인|노인|사회복지|돌봄", kakao_category):
        return "WELFARE"
    if re.search(r"행정기관|공공기관|경찰서|지구대|파출소|소방서|우체국|공단|주민센터|행정복지센터", kakao_category):
        return "PUBLIC_OFFICE"
    if re.search(r"관광|명소|공원|해수욕장|사찰|절|박물관|미술관|전시|공연|영화관|문화|놀이|테마파크|체험|아울렛|백화점|쇼핑", kakao_category):
        return "TOURIST_SPOT"
    return ""


def is_policy_etc_public_culture(name: str, kakao_category: str) -> bool:
    text = f"{name} {kakao_category}"
    return has_any(text, ["도서관", "문화원", "교육원", "청소년수련관", "수련관"])


def is_medical_building_like(name: str, kakao_name: str, kakao_category: str, poi_name: str) -> bool:
    text = f"{name} {kakao_name} {kakao_category} {poi_name}"
    if has_any(text, ["메디컬타워", "메디칼타워", "메디컬빌딩", "메디칼빌딩", "메디타워", "메디컬센터", "메디칼센터", "메디컬센타", "메디칼센타"]):
        return True
    if ("부동산 > 빌딩" in kakao_category or "건물" in poi_name) and has_any(name, ["메디컬", "메디칼", "메디타워"]):
        return True
    return False


def is_famous_tourist_spot(name: str, current_category: str) -> bool:
    if current_category == "TOURIST_SPOT":
        return True
    return has_any(
        name,
        [
            "해수욕장",
            "해변",
            "공원",
            "산책로",
            "숲길",
            "동백섬",
            "부산타워",
            "누리마루",
            "벡스코",
            "아쿠아리움",
            "키자니아",
            "아이스링크",
            "백화점",
            "아울렛",
            "르네시떼",
            "국제시장",
            "자갈치시장",
            "부평깡통시장",
            "범어사",
            "태종대",
            "허심청",
            "온천",
            "스파랜드",
        ],
    )


def policy_category(row: dict[str, str]) -> tuple[str, str]:
    name = row["name"]
    current = row["currentCategory"]
    kakao_category = row["kakaoCategory"]
    kakao_name = row["kakaoPlaceName"]
    poi_name = row["poiName"]
    mapped = mapped_category_from_kakao(kakao_category)

    if is_policy_etc_public_culture(name, kakao_category):
        return "ETC", "정책 1: 도서관/문화원/교육원 계열은 기타 편의시설로 보존"

    if is_medical_building_like(name, kakao_name, kakao_category, poi_name):
        return "ETC", "정책 7: 메디컬 빌딩/센터/타워는 병원 단일 장소가 아니므로 기타 편의시설로 보존"

    if current == "TOURIST_SPOT":
        if is_famous_tourist_spot(name, current):
            return "TOURIST_SPOT", "정책 2-6: 기존 관광지 원천의 대표 목적지는 관광지로 유지"
        return "ETC", "정책 2-6: 대표 관광 목적지로 보기 애매해 기타 편의시설로 보존"

    if current == "ACCOMMODATION":
        return "ACCOMMODATION", "숙박 원천 장소는 카카오 하위 매장명보다 원본 숙박 카테고리를 우선"

    if current in {"TOILET", "CHARGING_STATION", "WELFARE", "PUBLIC_OFFICE"}:
        return current, "현재 카테고리가 서비스 채택 카테고리와 부합하므로 유지"

    if current == "HEALTHCARE":
        return "HEALTHCARE" if mapped == "HEALTHCARE" else "ETC", "의료기관으로 확정되지 않은 의료 계열명은 기타 편의시설로 보존"

    if current == "RESTAURANT":
        return "RESTAURANT" if mapped == "RESTAURANT" else "ETC", "음식·카페로 확정되지 않는 원본 일반음식점은 기타 편의시설로 보존"

    return current if current in LABEL_BY_CATEGORY else "ETC", "정책 기준 밖 카테고리는 기타 편의시설로 보존"


def split_pipe(value: str) -> list[str]:
    return [item for item in (value or "").split("|") if item]


def join_pipe(items: list[str]) -> str:
    return "|".join(items)


def append_unique_pipe(value: str, item: str) -> str:
    items = split_pipe(value)
    if item not in items:
        items.append(item)
    return join_pipe(items)


def apply_to_root(root: Path, decisions_csv: Path) -> dict[str, Any]:
    data_adopted = root / "data" / "adopted"
    assets_data = root / "assets" / "data"
    validation_dir = root / "data" / "reports" / "facility_validation"

    adopted_all = data_adopted / "adopted_places_with_accessibility.csv"
    adopted_places = data_adopted / "adopted_places.csv"
    adopted_accessibility = data_adopted / "adopted_place_accessibility.csv"
    erd_places = data_adopted / "places_erd.csv"
    facilities_js = assets_data / "facilities-data.js"
    seed_js = assets_data / "manual-review-seed-data.js"
    out_mapping = validation_dir / "facility_policy_category_decisions_applied.csv"
    out_summary = validation_dir / "facility_policy_category_decisions_summary.json"

    decisions = read_csv(decisions_csv)
    policy_rows: list[dict[str, str]] = []
    mapping: dict[str, dict[str, str]] = {}
    for row in decisions:
        after, reason = policy_category(row)
        before = row["currentCategory"]
        policy_row = {
            **row,
            "beforeCategory": before,
            "afterCategory": after,
            "afterLabel": LABEL_BY_CATEGORY[after],
            "policyReason": reason,
        }
        policy_rows.append(policy_row)
        if after != before:
            mapping[row["sourceKey"]] = policy_row

    adopted_rows = read_csv(adopted_all)
    adopted_fieldnames = list(adopted_rows[0].keys())
    for row in adopted_rows:
        item = mapping.get(row["sourceKey"])
        if not item:
            continue
        row["dbCategory"] = item["afterCategory"]
        row["dbCategoryLabel"] = item["afterLabel"]
        row["uiCategory"] = item["afterLabel"]
        row["facilityCategory"] = item["afterLabel"]
        row["reviewFlags"] = append_unique_pipe(row.get("reviewFlags", ""), "policy_category_decision")
        row["reviewReasons"] = append_unique_pipe(row.get("reviewReasons", ""), item["policyReason"])
    write_csv(adopted_all, adopted_rows, adopted_fieldnames)

    adopted_places_rows = read_csv(adopted_places)
    adopted_places_fieldnames = list(adopted_places_rows[0].keys())
    for row in adopted_places_rows:
        item = mapping.get(row["place_key"])
        if not item:
            continue
        row["ui_category"] = item["afterLabel"]
    write_csv(adopted_places, adopted_places_rows, adopted_places_fieldnames)

    adopted_accessibility_rows = read_csv(adopted_accessibility)
    adopted_accessibility_fieldnames = list(adopted_accessibility_rows[0].keys())
    for row in adopted_accessibility_rows:
        item = mapping.get(row["place_key"])
        if item:
            row["ui_category"] = item["afterLabel"]
    write_csv(adopted_accessibility, adopted_accessibility_rows, adopted_accessibility_fieldnames)

    write_csv(
        erd_places,
        [
            {
                "placeId": row["placeId"],
                "name": row["name"],
                "category": row["dbCategory"],
                "address": row["address"],
                "point": row["point"],
                "providerPlaceId": row["providerPlaceId"],
            }
            for row in adopted_rows
        ],
        ["placeId", "name", "category", "address", "point", "providerPlaceId"],
    )

    geojson = load_js_assignment(facilities_js, "FACILITIES_GEOJSON")
    for feature in geojson["features"]:
        props = feature["properties"]
        source_key = props.get("sourceKey") or props.get("sourceId")
        item = mapping.get(source_key)
        if not item:
            continue
        props["dbCategory"] = item["afterCategory"]
        props["dbCategoryLabel"] = item["afterLabel"]
        props["uiCategory"] = item["afterLabel"]
        props["facilityCategory"] = item["afterLabel"]
        props["displaySource"] = item["afterLabel"]
        props["reviewFlags"] = split_pipe(append_unique_pipe(join_pipe(props.get("reviewFlags", [])), "policy_category_decision"))
        props["reviewReasons"] = split_pipe(append_unique_pipe(join_pipe(props.get("reviewReasons", [])), item["policyReason"]))
    write_js_assignment(facilities_js, "FACILITIES_GEOJSON", geojson)

    seed = load_js_assignment(seed_js, "MANUAL_REVIEW_SEED")
    policy_by_source_key = {row["sourceKey"]: row for row in policy_rows}
    for record in seed.values():
        item = policy_by_source_key.get(record.get("sourceKey", ""))
        if item:
            record["category"] = item["afterCategory"]
            record["evidenceAction"] = "POLICY_CATEGORY_DECIDED"
            record["note"] = f"{record.get('note', '')} / [정책분류] {item['beforeCategory']} -> {item['afterCategory']}: {item['policyReason']}"
    write_js_assignment(seed_js, "MANUAL_REVIEW_SEED", seed)

    write_csv(
        out_mapping,
        policy_rows,
        [
            "sourceKey",
            "placeId",
            "districtGu",
            "name",
            "beforeCategory",
            "afterCategory",
            "afterLabel",
            "kakaoPlaceName",
            "kakaoCategory",
            "poiName",
            "poiCategoryLabel",
            "evidenceAction",
            "policyReason",
        ],
    )

    summary = {
        "root": str(root),
        "processedCandidates": len(decisions),
        "changed": len(mapping),
        "changedByCategory": dict(Counter(row["afterCategory"] for row in mapping.values())),
        "policyAfterCategoryCounts": dict(Counter(row["afterCategory"] for row in policy_rows)),
        "changedBeforeCategoryCounts": dict(Counter(row["beforeCategory"] for row in mapping.values())),
        "changedAfterCategoryCounts": dict(Counter(row["afterCategory"] for row in mapping.values())),
        "mappingFile": str(out_mapping),
    }
    out_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--decisions", type=Path, default=None)
    args = parser.parse_args()

    root = args.root.resolve()
    decisions = args.decisions or root / "data" / "reports" / "facility_validation" / "facility_direct_category_review.csv"
    summary = apply_to_root(root, decisions)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
