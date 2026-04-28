from __future__ import annotations

import argparse
import csv
import json
import math
import re
import threading
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


POC_ROOT = Path(__file__).resolve().parents[1]
VALIDATION_DIR = POC_ROOT / "data" / "reports" / "facility_validation"

INPUT_CSV = VALIDATION_DIR / "facility_validation_review_targets_all_with_poi.csv"
CACHE_JSONL = VALIDATION_DIR / "kakao_search_cache.jsonl"

OUT_ALL = VALIDATION_DIR / "facility_cross_validation_all.csv"
OUT_SUMMARY = VALIDATION_DIR / "facility_cross_validation_summary.csv"
OUT_NEED_REVIEW = VALIDATION_DIR / "facility_cross_validation_need_review.csv"
OUT_KEEP = VALIDATION_DIR / "facility_cross_validation_keep_candidates.csv"
OUT_RENAME = VALIDATION_DIR / "facility_cross_validation_rename_candidates.csv"
OUT_EXCLUDE = VALIDATION_DIR / "facility_cross_validation_exclude_candidates.csv"

KAKAO_SEARCH_URL = "https://search.map.kakao.com/mapsearch/map.daum"
USER_AGENT = "Mozilla/5.0"
REQUEST_TIMEOUT_SECONDS = 12
MAX_CANDIDATES_PER_QUERY = 15

OUTPUT_FIELDNAMES = [
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
    "cross_check_status",
    "final_review_decision",
    "final_review_reason",
    "needs_human_decision",
]

INTERNAL_TOILET_KEYWORDS = [
    "주유소",
    "충전소",
    "병원",
    "의원",
    "대학교",
    "학교",
    "아파트",
    "빌딩",
    "교회",
    "성당",
    "사찰",
    "호텔",
    "금고",
    "은행",
]

PUBLIC_AREA_KEYWORDS = [
    "공원",
    "생태공원",
    "체육공원",
    "해수욕장",
    "해변",
    "산책로",
    "둘레길",
    "등산로",
    "약수터",
    "방파제",
    "항",
    "물양장",
    "시장",
    "지하도상가",
    "지하상가",
    "광장",
    "주차장",
    "마을",
    "유원지",
    "수원지",
    "저수지",
    "체육시설",
    "생활체육관",
    "역",
]

PUBLIC_BUILDING_KEYWORDS = [
    "도서관",
    "행정복지센터",
    "주민센터",
    "구청",
    "보건소",
    "우체국",
    "세관",
    "지구대",
    "파출소",
    "소방",
    "보훈회관",
    "문화원",
    "복지관",
]

GENERIC_NAME_KEYWORDS = [
    "일반음식점",
    "휴게음식점",
    "제과점",
    "공중화장실",
    "화장실",
    "의원·치과의원",
    "병원·치과병원",
    "노인복지시설",
    "사회복지시설",
    "장애인복지시설",
    "아동복지시설",
    "일반숙박시설",
    "관광숙박시설",
    "생활숙박시설",
    "경로당",
]

cache_lock = threading.Lock()
search_cache: dict[str, dict[str, Any]] = {}


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_text(value: Any) -> str:
    text = clean_text(value).lower()
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"주식회사|㈜|\(주\)|（주）", "", text)
    text = re.sub(r"[\s·ㆍ\-_.,/\\()\[\]{}]+", "", text)
    return text


def has_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def is_generic_name(name: str) -> bool:
    normalized = normalize_text(name)
    return any(normalize_text(keyword) in normalized for keyword in GENERIC_NAME_KEYWORDS)


def is_area_like(row: dict[str, str], kakao_category: str = "") -> bool:
    text = f"{row.get('place_name', '')} {row.get('address', '')} {kakao_category}"
    return has_any(text, PUBLIC_AREA_KEYWORDS)


def is_public_building_like(row: dict[str, str], kakao_category: str = "") -> bool:
    text = f"{row.get('place_name', '')} {row.get('address', '')} {kakao_category}"
    return has_any(text, PUBLIC_BUILDING_KEYWORDS)


def is_internal_toilet_like(row: dict[str, str], kakao_category: str = "") -> bool:
    text = f"{row.get('place_name', '')} {row.get('address', '')} {row.get('poi_category_label', '')} {kakao_category}"
    return has_any(text, INTERNAL_TOILET_KEYWORDS)


def extract_address_tokens(address: str) -> set[str]:
    tokens: set[str] = set()
    for pattern in [
        r"([가-힣0-9]+로\d*길)\s*(\d+(?:-\d+)?)",
        r"([가-힣0-9]+로)\s*(\d+(?:-\d+)?)",
        r"([가-힣0-9]+길)\s*(\d+(?:-\d+)?)",
        r"([가-힣]+동)\s*(\d+(?:-\d+)?)",
        r"([가-힣]+리)\s*(\d+(?:-\d+)?)",
    ]:
        for match in re.finditer(pattern, address):
            tokens.add(" ".join(match.groups()))
    return tokens


def extract_road_key(address: str) -> str:
    for pattern in [
        r"([가-힣0-9]+로\d*길)\s*(\d+(?:-\d+)?)",
        r"([가-힣0-9]+로)\s*(\d+(?:-\d+)?)",
        r"([가-힣0-9]+길)\s*(\d+(?:-\d+)?)",
    ]:
        match = re.search(pattern, address)
        if match:
            return " ".join(match.groups())
    return ""


def strip_address_detail(address: str) -> str:
    address = re.sub(r"\([^)]*\)", "", address)
    address = re.sub(r",.*$", "", address)
    return " ".join(address.split())


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_000.0
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def address_match_score(facility_address: str, kakao_address: str) -> tuple[int, str]:
    facility_tokens = extract_address_tokens(facility_address)
    kakao_tokens = extract_address_tokens(kakao_address)
    if facility_tokens and kakao_tokens and facility_tokens & kakao_tokens:
        return 25, "ADDRESS_TOKEN_MATCH"
    facility_norm = normalize_text(facility_address)
    kakao_norm = normalize_text(kakao_address)
    if facility_norm and kakao_norm and (facility_norm in kakao_norm or kakao_norm in facility_norm):
        return 18, "ADDRESS_TEXT_CONTAINS"
    return 0, ""


def category_assessment(ui_category: str, name: str, category: str) -> tuple[str, int]:
    text = normalize_text(f"{name} {category}")
    if ui_category == "화장실":
        if has_any(text, ["화장실", "공중화장실", "개방화장실"]):
            return "CATEGORY_MATCH", 15
        if has_any(text, ["주유소", "병원", "의원", "호텔", "아파트", "학교", "대학교", "은행", "빌딩"]):
            return "INTERNAL_TOILET_CONTEXT", 5
        return "CATEGORY_CHECK", 0
    if ui_category == "음식·카페":
        return ("CATEGORY_MATCH", 15) if has_any(text, ["음식", "식당", "카페", "커피", "제과", "한식", "일식", "중식", "분식", "피자", "국밥", "고기"]) else ("CATEGORY_CHECK", 0)
    if ui_category == "의료·보건":
        return ("CATEGORY_MATCH", 15) if has_any(text, ["병원", "의원", "보건", "약국", "의료"]) else ("CATEGORY_CHECK", 0)
    if ui_category == "복지·돌봄":
        return ("CATEGORY_MATCH", 15) if has_any(text, ["복지", "경로당", "노인", "장애인", "아동", "요양"]) else ("CATEGORY_CHECK", 0)
    if ui_category == "숙박":
        return ("CATEGORY_MATCH", 15) if has_any(text, ["숙박", "호텔", "모텔", "펜션", "리조트", "여관"]) else ("CATEGORY_CHECK", 0)
    if ui_category == "전동보장구 충전소":
        return ("CATEGORY_MATCH", 15) if has_any(text, ["충전", "전동", "휠체어", "보장구"]) else ("LOCATION_CONTEXT_ONLY", 0)
    if ui_category == "행정·공공기관":
        return ("CATEGORY_MATCH", 15) if has_any(text, ["행정", "주민센터", "구청", "시청", "공공", "기관", "센터", "경찰", "소방", "세관"]) else ("CATEGORY_CHECK", 0)
    if ui_category == "관광지":
        return ("CATEGORY_MATCH", 15) if has_any(text, ["관광", "공원", "해수욕장", "박물관", "기념", "문화", "유적", "시장"]) else ("CATEGORY_CHECK", 0)
    return "CATEGORY_CHECK", 0


def distance_score(distance_m: float) -> int:
    if distance_m <= 30:
        return 45
    if distance_m <= 50:
        return 38
    if distance_m <= 100:
        return 28
    if distance_m <= 200:
        return 15
    if distance_m <= 300:
        return 5
    return 0


def kakao_status(score: int, distance_m: float, name_similarity: float, address_match: str) -> str:
    if score >= 75 and distance_m <= 100:
        return "KAKAO_STRONG"
    if score >= 55 and distance_m <= 200:
        return "KAKAO_MEDIUM"
    if score >= 38:
        return "KAKAO_WEAK"
    if address_match or name_similarity >= 0.55:
        return "KAKAO_REVIEW"
    return "KAKAO_NEARBY_ONLY"


def load_cache() -> None:
    if not CACHE_JSONL.exists():
        return
    with CACHE_JSONL.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            query = entry.get("query")
            if query:
                search_cache[query] = entry


def append_cache(entry: dict[str, Any]) -> None:
    with cache_lock:
        search_cache[entry["query"]] = entry
        with CACHE_JSONL.open("a", encoding="utf-8") as file:
            file.write(json.dumps(entry, ensure_ascii=False) + "\n")


def fetch_kakao(query: str, retries: int = 2) -> dict[str, Any]:
    query = " ".join(query.split())
    if not query:
        return {"query": query, "ok": False, "error": "EMPTY_QUERY", "places": []}

    with cache_lock:
        cached = search_cache.get(query)
    if cached is not None:
        return cached

    params = urllib.parse.urlencode({"q": query, "msFlag": "S", "page": "1", "sort": "0"})
    url = f"{KAKAO_SEARCH_URL}?{params}"
    headers = {"Referer": "https://map.kakao.com/", "User-Agent": USER_AGENT}

    last_error = ""
    for attempt in range(retries + 1):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                data = json.loads(response.read().decode("utf-8"))
            places = []
            for place in (data.get("place") or [])[:MAX_CANDIDATES_PER_QUERY]:
                places.append(
                    {
                        "id": clean_text(place.get("confirmid") or place.get("sourceId")),
                        "name": clean_text(place.get("name")),
                        "road_address": clean_text(place.get("new_address")),
                        "jibun_address": clean_text(place.get("address")),
                        "lat": clean_text(place.get("lat")),
                        "lon": clean_text(place.get("lon")),
                        "category": " > ".join(
                            part
                            for part in [
                                clean_text(place.get("cate_name_depth1")),
                                clean_text(place.get("cate_name_depth2")),
                                clean_text(place.get("cate_name_depth3")),
                                clean_text(place.get("cate_name_depth4")),
                                clean_text(place.get("last_cate_name")),
                            ]
                            if part
                        ),
                    }
                )
            entry = {"query": query, "ok": True, "error": "", "places": places}
            append_cache(entry)
            return entry
        except Exception as exc:  # network can fail; cache failed query too.
            last_error = str(exc)
            time.sleep(0.4 * (attempt + 1))

    entry = {"query": query, "ok": False, "error": last_error, "places": []}
    append_cache(entry)
    return entry


def query_plan(row: dict[str, str]) -> list[str]:
    name = clean_text(row.get("place_name"))
    address = clean_text(row.get("address"))
    district = clean_text(row.get("district_gu"))
    road_key = extract_road_key(address)
    short_address = strip_address_detail(address)

    queries = [
        f"{name} {short_address}",
        f"{name} {road_key}" if road_key else "",
        f"{name} {district}" if district else "",
        name,
        short_address,
    ]
    seen = set()
    result = []
    for query in queries:
        query = " ".join(query.split())
        if query and query not in seen:
            seen.add(query)
            result.append(query)
    return result


def score_kakao_candidate(row: dict[str, str], query: str, candidate: dict[str, str]) -> dict[str, Any]:
    try:
        facility_lat = float(row["latitude"])
        facility_lon = float(row["longitude"])
        lat = float(candidate["lat"])
        lon = float(candidate["lon"])
        distance_m = haversine_m(facility_lat, facility_lon, lat, lon)
    except (TypeError, ValueError):
        distance_m = 999999.0

    name = clean_text(row.get("place_name"))
    generic_name = is_generic_name(name)
    name_similarity = 0.0 if generic_name else SequenceMatcher(None, normalize_text(name), normalize_text(candidate["name"])).ratio()
    name_points = int(name_similarity * 35) if not generic_name else 0
    address_text = f"{candidate.get('road_address', '')} {candidate.get('jibun_address', '')}"
    address_points, address_match = address_match_score(row.get("address", ""), address_text)
    category_result, category_points = category_assessment(row.get("ui_category", ""), candidate.get("name", ""), candidate.get("category", ""))
    score = distance_score(distance_m) + name_points + address_points + category_points

    return {
        "query": query,
        "candidate": candidate,
        "score": score,
        "distance_m": distance_m,
        "name_similarity": name_similarity,
        "address_match": address_match,
        "category_assessment": category_result,
    }


def search_kakao_best(row: dict[str, str]) -> dict[str, str]:
    best: dict[str, Any] | None = None
    total_results = 0
    best_query = ""

    for query in query_plan(row):
        result = fetch_kakao(query)
        places = result.get("places") or []
        total_results += len(places)
        for candidate in places:
            scored = score_kakao_candidate(row, query, candidate)
            if best is None or (scored["score"], -scored["distance_m"], scored["name_similarity"]) > (
                best["score"],
                -best["distance_m"],
                best["name_similarity"],
            ):
                best = scored
                best_query = query
        if best is not None and best["score"] >= 80 and best["distance_m"] <= 80:
            break

    if best is None:
        return {
            "kakao_best_status": "KAKAO_NO_RESULT",
            "kakao_best_score": "0",
            "kakao_best_query": query_plan(row)[0] if query_plan(row) else "",
            "kakao_result_count": str(total_results),
            "kakao_place_id": "",
            "kakao_place_name": "",
            "kakao_road_address": "",
            "kakao_jibun_address": "",
            "kakao_category": "",
            "kakao_distance_m": "",
            "kakao_name_similarity": "",
            "kakao_address_match": "",
            "kakao_category_assessment": "",
            "kakao_match_reason": "카카오맵 검색 결과 없음",
        }

    candidate = best["candidate"]
    status = kakao_status(int(best["score"]), float(best["distance_m"]), float(best["name_similarity"]), str(best["address_match"]))
    reason = [
        f"distance={best['distance_m']:.1f}m",
        f"name_sim={best['name_similarity']:.2f}",
    ]
    if best["address_match"]:
        reason.append(str(best["address_match"]))
    reason.append(str(best["category_assessment"]))

    return {
        "kakao_best_status": status,
        "kakao_best_score": str(int(best["score"])),
        "kakao_best_query": best_query,
        "kakao_result_count": str(total_results),
        "kakao_place_id": candidate.get("id", ""),
        "kakao_place_name": candidate.get("name", ""),
        "kakao_road_address": candidate.get("road_address", ""),
        "kakao_jibun_address": candidate.get("jibun_address", ""),
        "kakao_category": candidate.get("category", ""),
        "kakao_distance_m": f"{best['distance_m']:.1f}",
        "kakao_name_similarity": f"{best['name_similarity']:.3f}",
        "kakao_address_match": str(best["address_match"]),
        "kakao_category_assessment": str(best["category_assessment"]),
        "kakao_match_reason": " | ".join(reason),
    }


def is_strong_poi(row: dict[str, str]) -> bool:
    return row.get("poi_match_status") in {"MATCH_STRONG", "MATCH_MEDIUM"}


def is_strong_kakao(row: dict[str, str]) -> bool:
    return row.get("kakao_best_status") in {"KAKAO_STRONG", "KAKAO_MEDIUM"}


def cross_check(row: dict[str, str]) -> str:
    poi_strong = is_strong_poi(row)
    kakao_strong = is_strong_kakao(row)
    if poi_strong and kakao_strong:
        return "BOTH_STRONG"
    if poi_strong and row.get("kakao_best_status") == "KAKAO_NO_RESULT":
        return "POI_ONLY"
    if kakao_strong and row.get("poi_match_status") in {"NO_MATCH", "NEARBY_ONLY", "MATCH_REVIEW", "MATCH_WEAK"}:
        return "KAKAO_ONLY"
    if not poi_strong and not kakao_strong:
        return "NO_STRONG_EVIDENCE"
    return "CONFLICT_OR_WEAK"


def final_decision(row: dict[str, str]) -> dict[str, str]:
    category = row.get("ui_category", "")
    cross_status = row["cross_check_status"]
    kakao_category = row.get("kakao_category", "")
    kakao_name = row.get("kakao_place_name", "")
    poi_category = row.get("poi_category_label", "")

    if category == "화장실":
        if is_internal_toilet_like(row, kakao_category):
            if row.get("poi_category_assessment") == "CATEGORY_MATCH" or row.get("kakao_category_assessment") == "CATEGORY_MATCH":
                return {
                    "final_review_decision": "KEEP_WITH_CONTEXT",
                    "needs_human_decision": "N",
                    "final_review_reason": "화장실 근거가 있으나 내부시설 맥락이 있어 표시 문구 검토",
                }
            return {
                "final_review_decision": "EXCLUDE_CANDIDATE",
                "needs_human_decision": "Y",
                "final_review_reason": "주유소/병원/학교/아파트 등 내부 화장실 가능성이 높고 공중화장실 근거가 약함",
            }
        if is_area_like(row, kakao_category) or row.get("poi_category_assessment") == "CATEGORY_MATCH" or row.get("kakao_category_assessment") == "CATEGORY_MATCH":
            return {
                "final_review_decision": "KEEP",
                "needs_human_decision": "N",
                "final_review_reason": "공중화장실 또는 구역형 공공장소 근거가 있음",
            }
        if is_public_building_like(row, kakao_category):
            return {
                "final_review_decision": "KEEP_WITH_CONTEXT",
                "needs_human_decision": "N",
                "final_review_reason": "공공시설 내부 화장실로 보이며 표시 맥락 필요",
            }

    if category == "전동보장구 충전소":
        return {
            "final_review_decision": "KEEP_LOCATION_REVIEW",
            "needs_human_decision": "N",
            "final_review_reason": "전동보장구 충전소는 서비스 목적상 유지하되 좌표 대표점 확인 대상",
        }

    if is_generic_name(row.get("place_name", "")):
        if category == "음식·카페" and ("음식" in poi_category or "카페" in poi_category or "음식" in kakao_category or "카페" in kakao_category):
            return {
                "final_review_decision": "RENAME_CANDIDATE",
                "needs_human_decision": "Y",
                "final_review_reason": "원본명은 업종명이나 POI/카카오에서 실제 음식점 후보 확인",
            }
        return {
            "final_review_decision": "RENAME_OR_EXCLUDE",
            "needs_human_decision": "Y",
            "final_review_reason": "원본명이 실제 장소명이 아니라 유형명임",
        }

    if cross_status == "BOTH_STRONG":
        return {
            "final_review_decision": "KEEP",
            "needs_human_decision": "N",
            "final_review_reason": "POI와 카카오맵 모두 강한 근거",
        }
    if cross_status == "KAKAO_ONLY":
        return {
            "final_review_decision": "KEEP",
            "needs_human_decision": "N",
            "final_review_reason": "POI는 약하지만 카카오맵에서 강한 근거",
        }
    if cross_status == "POI_ONLY":
        return {
            "final_review_decision": "KEEP",
            "needs_human_decision": "N",
            "final_review_reason": "카카오 검색은 약하지만 POI 근거가 강함",
        }
    if cross_status == "NO_STRONG_EVIDENCE":
        if is_area_like(row, kakao_category):
            return {
                "final_review_decision": "KEEP_AREA_PLACE",
                "needs_human_decision": "N",
                "final_review_reason": "구역형 장소라 단일 POI/카카오 매칭이 약할 수 있음",
            }
        return {
            "final_review_decision": "REVIEW",
            "needs_human_decision": "Y",
            "final_review_reason": "POI와 카카오맵 모두 강한 근거가 부족함",
        }

    if kakao_name and normalize_text(row.get("place_name", "")) != normalize_text(kakao_name) and row.get("kakao_best_status") == "KAKAO_STRONG":
        return {
            "final_review_decision": "RENAME_CANDIDATE",
            "needs_human_decision": "Y",
            "final_review_reason": "카카오맵에서 더 구체적인 장소명이 강하게 확인됨",
        }

    return {
        "final_review_decision": "REVIEW",
        "needs_human_decision": "Y",
        "final_review_reason": "POI와 카카오 근거가 일부 충돌하거나 약함",
    }


def validate_row(row: dict[str, str]) -> dict[str, str]:
    kakao = search_kakao_best(row)
    merged = {**row, **kakao}
    merged["cross_check_status"] = cross_check(merged)
    return {**merged, **final_decision(merged)}


def write_csv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(rows: list[dict[str, str]], input_fieldnames: list[str]) -> None:
    fieldnames = [*input_fieldnames, *OUTPUT_FIELDNAMES]
    write_csv(OUT_ALL, rows, fieldnames)
    write_csv(OUT_NEED_REVIEW, [row for row in rows if row["needs_human_decision"] == "Y"], fieldnames)
    write_csv(OUT_KEEP, [row for row in rows if row["final_review_decision"].startswith("KEEP")], fieldnames)
    write_csv(OUT_RENAME, [row for row in rows if "RENAME" in row["final_review_decision"]], fieldnames)
    write_csv(OUT_EXCLUDE, [row for row in rows if row["final_review_decision"] == "EXCLUDE_CANDIDATE"], fieldnames)

    summary_rows = []
    for group_name, key in [
        ("cross_check_status", "cross_check_status"),
        ("final_review_decision", "final_review_decision"),
        ("needs_human_decision", "needs_human_decision"),
        ("kakao_best_status", "kakao_best_status"),
        ("poi_match_status", "poi_match_status"),
        ("priority_decision", "validation_priority|final_review_decision"),
        ("category_decision", "ui_category|final_review_decision"),
    ]:
        if "|" in key:
            left, right = key.split("|")
            counter = Counter(f"{row[left]} / {row[right]}" for row in rows)
        else:
            counter = Counter(row[key] for row in rows)
        for name, count in sorted(counter.items(), key=lambda item: (-item[1], item[0])):
            summary_rows.append({"group": group_name, "name": name, "count": str(count)})
    write_csv(OUT_SUMMARY, summary_rows, ["group", "name", "count"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    load_cache()
    with INPUT_CSV.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        input_fieldnames = list(reader.fieldnames or [])
        rows = list(reader)

    if args.limit:
        rows = rows[: args.limit]

    results: list[dict[str, str]] = []
    completed = 0
    started = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(validate_row, row) for row in rows]
        for future in as_completed(futures):
            results.append(future.result())
            completed += 1
            if completed % 100 == 0 or completed == len(rows):
                elapsed = time.time() - started
                print(f"validated {completed}/{len(rows)} elapsed={elapsed:.1f}s cache={len(search_cache)}")

    # Restore deterministic order by original place key order.
    order = {row["place_key"]: index for index, row in enumerate(rows)}
    results.sort(key=lambda row: order.get(row["place_key"], 999999))
    write_outputs(results, input_fieldnames)

    print("done", len(results))
    for decision, count in sorted(Counter(row["final_review_decision"] for row in results).items()):
        print(decision, count)
    print("needs_human_decision", dict(Counter(row["needs_human_decision"] for row in results)))


if __name__ == "__main__":
    main()
