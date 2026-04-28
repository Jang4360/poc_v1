from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import pandas as pd


POC_ROOT = Path(__file__).resolve().parents[1]
POI_DIR = POC_ROOT / "data" / "source" / "poi"
VALIDATION_DIR = POC_ROOT / "data" / "reports" / "facility_validation"
TARGETS_IN = VALIDATION_DIR / "facility_validation_review_targets_all.csv"
OUT_CSV = VALIDATION_DIR / "facility_validation_review_targets_all_with_poi.csv"
OUT_P1_P2_CSV = VALIDATION_DIR / "facility_validation_review_targets_p1_p2_with_poi.csv"
OUT_P3_CSV = VALIDATION_DIR / "facility_validation_review_targets_p3_with_poi.csv"
OUT_FIRST_REVIEW_CSV = VALIDATION_DIR / "facility_validation_poi_first_review_159.csv"
OUT_FIRST_REVIEW_SUMMARY_CSV = VALIDATION_DIR / "facility_validation_poi_first_review_159_summary.csv"
SUMMARY_JSON = VALIDATION_DIR / "facility_validation_poi_match_summary.json"
SUMMARY_CSV = VALIDATION_DIR / "facility_validation_poi_match_summary.csv"

POI_CACHE = POI_DIR / "busan_poi_processed.csv"
CATEGORY_CACHE = POI_DIR / "poi_category_labels.csv"

CELL_SIZE_M = 200.0
SEARCH_RADIUS_M = 300.0


OUTPUT_FIELDNAMES = [
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

FIRST_REVIEW_STATUSES = {"NO_MATCH", "NEARBY_ONLY", "MATCH_REVIEW", "MATCH_WEAK"}


def find_source_files() -> tuple[Path, Path]:
    files = sorted(POI_DIR.glob("*.xlsx"), key=lambda path: path.stat().st_size, reverse=True)
    if len(files) < 2:
        raise FileNotFoundError(f"POI xlsx files not found in {POI_DIR}")
    return files[0], files[1]


def normalize_text(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.lower()
    text = re.sub(r"\([^)]*\)", "", text)
    text = re.sub(r"주식회사|㈜|\(주\)|（주）", "", text)
    text = re.sub(r"[\s·ㆍ\-_.,/\\()\[\]{}]+", "", text)
    return text


def clean_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return str(value).strip()


def code_text(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    text = re.sub(r"\D", "", text)
    return text.zfill(12) if text else ""


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


def text_contains_any(text: str, keywords: list[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def is_generic_facility_name(name: str) -> bool:
    normalized = normalize_text(name)
    generic_keywords = [
        "일반음식점",
        "휴게음식점",
        "공중화장실",
        "화장실",
        "의원치과의원한의원조산소산후조리원",
        "병원치과병원한방병원정신병원요양병원",
        "노인복지시설",
        "사회복지시설",
        "장애인복지시설",
        "아동복지시설",
        "일반숙박시설",
        "관광숙박시설",
        "생활숙박시설",
        "경로당",
    ]
    return normalized in generic_keywords or any(keyword in normalized for keyword in generic_keywords)


def lonlat_to_epsg5179(lon: float, lat: float) -> tuple[float, float]:
    # EPSG:5179 Korea 2000 / Unified CS. GRS80 ellipsoid is effectively
    # identical to WGS84 for this matching tolerance.
    a = 6378137.0
    inv_f = 298.257222101
    f = 1 / inv_f
    e2 = 2 * f - f * f
    ep2 = e2 / (1 - e2)
    lat0 = math.radians(38.0)
    lon0 = math.radians(127.5)
    k0 = 0.9996
    false_easting = 1_000_000.0
    false_northing = 2_000_000.0

    phi = math.radians(lat)
    lam = math.radians(lon)

    def meridional_arc(p: float) -> float:
        return a * (
            (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256) * p
            - (3 * e2 / 8 + 3 * e2**2 / 32 + 45 * e2**3 / 1024) * math.sin(2 * p)
            + (15 * e2**2 / 256 + 45 * e2**3 / 1024) * math.sin(4 * p)
            - (35 * e2**3 / 3072) * math.sin(6 * p)
        )

    n = a / math.sqrt(1 - e2 * math.sin(phi) ** 2)
    t = math.tan(phi) ** 2
    c = ep2 * math.cos(phi) ** 2
    aa = (lam - lon0) * math.cos(phi)
    m = meridional_arc(phi)
    m0 = meridional_arc(lat0)

    x = false_easting + k0 * n * (
        aa
        + (1 - t + c) * aa**3 / 6
        + (5 - 18 * t + t**2 + 72 * c - 58 * ep2) * aa**5 / 120
    )
    y = false_northing + k0 * (
        (m - m0)
        + n
        * math.tan(phi)
        * (
            aa**2 / 2
            + (5 - t + 9 * c + 4 * c**2) * aa**4 / 24
            + (61 - 58 * t + t**2 + 600 * c - 330 * ep2) * aa**6 / 720
        )
    )
    return x, y


def build_category_cache(category_xlsx: Path) -> dict[str, str]:
    if CATEGORY_CACHE.exists():
        with CATEGORY_CACHE.open("r", encoding="utf-8-sig", newline="") as file:
            return {row["poi_category_code"]: row["poi_category_label"] for row in csv.DictReader(file)}

    df = pd.read_excel(category_xlsx, header=1, dtype=str)
    labels: dict[str, str] = {}
    for _, row in df.iterrows():
        code = code_text(row.get("실제입력코드"))
        if not code:
            continue
        parts = [
            clean_text(row.get(column))
            for column in ["LCLASDC", "MLSFCDC", "SCLASDC", "DCLASDC", "DFCLASDC", "DGCLASDC"]
        ]
        parts = [part for part in parts if part and part != "-"]
        labels[code] = " > ".join(parts)

    with CATEGORY_CACHE.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["poi_category_code", "poi_category_label"])
        writer.writeheader()
        for code, label in sorted(labels.items()):
            writer.writerow({"poi_category_code": code, "poi_category_label": label})
    return labels


def build_poi_cache(poi_xlsx: Path, category_labels: dict[str, str]) -> None:
    if POI_CACHE.exists():
        return

    usecols = [
        "고유식별자 아이디",
        "관심지점 명칭",
        "관심지점 분류 설명",
        "도로명 주소 명칭",
        "지번 주소 명칭",
        "x(EPSG:5179)",
        "y(EPSG:5179)",
    ]
    df = pd.read_excel(poi_xlsx, usecols=usecols, dtype=str)
    df = df.rename(
        columns={
            "고유식별자 아이디": "poi_id",
            "관심지점 명칭": "poi_name",
            "관심지점 분류 설명": "poi_category_code",
            "도로명 주소 명칭": "poi_road_address",
            "지번 주소 명칭": "poi_jibun_address",
            "x(EPSG:5179)": "poi_x",
            "y(EPSG:5179)": "poi_y",
        }
    )
    df["poi_category_code"] = df["poi_category_code"].map(code_text)
    df["poi_category_label"] = df["poi_category_code"].map(category_labels).fillna("")
    df["poi_name_norm"] = df["poi_name"].map(normalize_text)
    df["poi_address_text"] = (
        df["poi_road_address"].fillna("").astype(str) + " " + df["poi_jibun_address"].fillna("").astype(str)
    ).str.strip()
    df["poi_x"] = pd.to_numeric(df["poi_x"], errors="coerce")
    df["poi_y"] = pd.to_numeric(df["poi_y"], errors="coerce")
    df = df.dropna(subset=["poi_x", "poi_y"])
    df.to_csv(POI_CACHE, index=False, encoding="utf-8-sig")


def load_pois() -> list[dict[str, Any]]:
    df = pd.read_csv(POI_CACHE, dtype=str)
    df["poi_x"] = pd.to_numeric(df["poi_x"], errors="coerce")
    df["poi_y"] = pd.to_numeric(df["poi_y"], errors="coerce")
    df = df.dropna(subset=["poi_x", "poi_y"])
    return df.fillna("").to_dict("records")


def build_grid(pois: list[dict[str, Any]]) -> dict[tuple[int, int], list[int]]:
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for index, poi in enumerate(pois):
        cell = (int(float(poi["poi_x"]) // CELL_SIZE_M), int(float(poi["poi_y"]) // CELL_SIZE_M))
        grid[cell].append(index)
    return grid


def candidate_indexes(grid: dict[tuple[int, int], list[int]], x: float, y: float) -> list[int]:
    cx = int(x // CELL_SIZE_M)
    cy = int(y // CELL_SIZE_M)
    span = math.ceil(SEARCH_RADIUS_M / CELL_SIZE_M)
    indexes: list[int] = []
    for gx in range(cx - span, cx + span + 1):
        for gy in range(cy - span, cy + span + 1):
            indexes.extend(grid.get((gx, gy), []))
    return indexes


def address_match_score(facility_address: str, poi_address: str) -> tuple[int, str]:
    facility_tokens = extract_address_tokens(facility_address)
    poi_tokens = extract_address_tokens(poi_address)
    if facility_tokens and poi_tokens and facility_tokens & poi_tokens:
        return 25, "ADDRESS_TOKEN_MATCH"
    facility_norm = normalize_text(facility_address)
    poi_norm = normalize_text(poi_address)
    if facility_norm and poi_norm and (facility_norm in poi_norm or poi_norm in facility_norm):
        return 18, "ADDRESS_TEXT_CONTAINS"
    return 0, ""


def category_assessment(ui_category: str, poi_name: str, poi_label: str) -> tuple[str, int]:
    text = normalize_text(f"{poi_name} {poi_label}")
    if ui_category == "화장실":
        if text_contains_any(text, ["화장실", "공중화장실", "개방화장실"]):
            return "CATEGORY_MATCH", 15
        if text_contains_any(text, ["주유소", "병원", "의원", "호텔", "아파트", "학교", "대학교", "은행", "빌딩"]):
            return "INTERNAL_TOILET_CONTEXT", 5
        return "CATEGORY_CHECK", 0
    if ui_category == "음식·카페":
        return ("CATEGORY_MATCH", 15) if text_contains_any(text, ["음식", "식당", "카페", "커피", "제과", "음식점"]) else ("CATEGORY_CHECK", 0)
    if ui_category == "의료·보건":
        return ("CATEGORY_MATCH", 15) if text_contains_any(text, ["병원", "의원", "보건", "약국", "의료"]) else ("CATEGORY_CHECK", 0)
    if ui_category == "복지·돌봄":
        return ("CATEGORY_MATCH", 15) if text_contains_any(text, ["복지", "경로당", "노인", "장애인", "아동", "요양"]) else ("CATEGORY_CHECK", 0)
    if ui_category == "숙박":
        return ("CATEGORY_MATCH", 15) if text_contains_any(text, ["숙박", "호텔", "모텔", "펜션", "리조트", "여관"]) else ("CATEGORY_CHECK", 0)
    if ui_category == "전동보장구 충전소":
        return ("CATEGORY_MATCH", 15) if text_contains_any(text, ["충전", "전동", "휠체어", "보장구"]) else ("LOCATION_CONTEXT_ONLY", 0)
    if ui_category == "행정·공공기관":
        return ("CATEGORY_MATCH", 15) if text_contains_any(text, ["행정", "주민센터", "구청", "시청", "공공", "기관", "센터"]) else ("CATEGORY_CHECK", 0)
    if ui_category == "관광지":
        return ("CATEGORY_MATCH", 15) if text_contains_any(text, ["관광", "공원", "해수욕장", "박물관", "기념", "문화", "유적"]) else ("CATEGORY_CHECK", 0)
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
    if distance_m <= SEARCH_RADIUS_M:
        return 5
    return 0


def match_status(score: int, distance_m: float, name_similarity: float, address_match: str) -> str:
    if score >= 75 and distance_m <= 80:
        return "MATCH_STRONG"
    if score >= 55 and distance_m <= 150:
        return "MATCH_MEDIUM"
    if score >= 38:
        return "MATCH_WEAK"
    if address_match or name_similarity >= 0.55:
        return "MATCH_REVIEW"
    return "NEARBY_ONLY"


def score_candidate(row: dict[str, str], poi: dict[str, Any], facility_x: float, facility_y: float) -> dict[str, Any]:
    distance_m = math.hypot(float(poi["poi_x"]) - facility_x, float(poi["poi_y"]) - facility_y)
    name = row.get("place_name", "")
    generic_name = is_generic_facility_name(name)
    name_similarity = 0.0 if generic_name else SequenceMatcher(None, normalize_text(name), poi["poi_name_norm"]).ratio()
    name_points = int(name_similarity * 35) if not generic_name else 0
    address_points, address_match = address_match_score(row.get("address", ""), poi.get("poi_address_text", ""))
    poi_category_assessment, category_points = category_assessment(
        row.get("ui_category", ""), poi.get("poi_name", ""), poi.get("poi_category_label", "")
    )
    score = distance_score(distance_m) + name_points + address_points + category_points
    return {
        "score": score,
        "distance_m": distance_m,
        "name_similarity": name_similarity,
        "address_match": address_match,
        "poi_category_assessment": poi_category_assessment,
    }


def empty_match(reason: str) -> dict[str, str]:
    return {
        "poi_match_status": "NO_MATCH",
        "poi_match_score": "0",
        "poi_distance_m": "",
        "poi_candidate_count_300m": "0",
        "poi_id": "",
        "poi_name": "",
        "poi_road_address": "",
        "poi_jibun_address": "",
        "poi_category_code": "",
        "poi_category_label": "",
        "poi_name_similarity": "",
        "poi_address_match": "",
        "poi_category_assessment": "",
        "poi_match_reason": reason,
    }


def match_facility(row: dict[str, str], pois: list[dict[str, Any]], grid: dict[tuple[int, int], list[int]]) -> dict[str, str]:
    try:
        lon = float(row["longitude"])
        lat = float(row["latitude"])
    except (TypeError, ValueError):
        return empty_match("시설 좌표가 비어 있거나 숫자가 아님")

    facility_x, facility_y = lonlat_to_epsg5179(lon, lat)
    indexes = candidate_indexes(grid, facility_x, facility_y)
    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []

    for index in indexes:
        poi = pois[index]
        distance_m = math.hypot(float(poi["poi_x"]) - facility_x, float(poi["poi_y"]) - facility_y)
        if distance_m <= SEARCH_RADIUS_M:
            candidates.append((poi, score_candidate(row, poi, facility_x, facility_y)))

    if not candidates:
        return empty_match("300m 이내 POI 후보 없음")

    candidates.sort(
        key=lambda item: (
            item[1]["score"],
            -item[1]["distance_m"],
            item[1]["name_similarity"],
        ),
        reverse=True,
    )
    poi, scored = candidates[0]
    status = match_status(
        int(scored["score"]),
        float(scored["distance_m"]),
        float(scored["name_similarity"]),
        str(scored["address_match"]),
    )
    reason_parts = [
        f"distance={scored['distance_m']:.1f}m",
        f"name_sim={scored['name_similarity']:.2f}",
    ]
    if scored["address_match"]:
        reason_parts.append(str(scored["address_match"]))
    reason_parts.append(str(scored["poi_category_assessment"]))

    return {
        "poi_match_status": status,
        "poi_match_score": str(int(scored["score"])),
        "poi_distance_m": f"{scored['distance_m']:.1f}",
        "poi_candidate_count_300m": str(len(candidates)),
        "poi_id": str(poi.get("poi_id", "")),
        "poi_name": str(poi.get("poi_name", "")),
        "poi_road_address": str(poi.get("poi_road_address", "")),
        "poi_jibun_address": str(poi.get("poi_jibun_address", "")),
        "poi_category_code": str(poi.get("poi_category_code", "")),
        "poi_category_label": str(poi.get("poi_category_label", "")),
        "poi_name_similarity": f"{scored['name_similarity']:.3f}",
        "poi_address_match": str(scored["address_match"]),
        "poi_category_assessment": str(scored["poi_category_assessment"]),
        "poi_match_reason": " | ".join(reason_parts),
    }


def write_summary(rows: list[dict[str, str]]) -> None:
    summary = {
        "total": len(rows),
        "poiMatchStatusCounts": dict(Counter(row["poi_match_status"] for row in rows)),
        "priorityStatusCounts": {
            priority: dict(Counter(row["poi_match_status"] for row in rows if row["validation_priority"] == priority))
            for priority in sorted({row["validation_priority"] for row in rows})
        },
        "categoryStatusCounts": {
            category: dict(Counter(row["poi_match_status"] for row in rows if row["ui_category"] == category))
            for category in sorted({row["ui_category"] for row in rows})
        },
        "categoryAssessmentCounts": dict(Counter(row["poi_category_assessment"] for row in rows)),
        "files": {
            "matched": str(OUT_CSV),
            "matchedP1P2": str(OUT_P1_P2_CSV),
            "matchedP3": str(OUT_P3_CSV),
            "firstReview159": str(OUT_FIRST_REVIEW_CSV),
            "firstReview159Summary": str(OUT_FIRST_REVIEW_SUMMARY_CSV),
            "summaryCsv": str(SUMMARY_CSV),
            "summaryJson": str(SUMMARY_JSON),
        },
    }
    SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    summary_rows = []
    for status, count in sorted(Counter(row["poi_match_status"] for row in rows).items()):
        summary_rows.append({"group": "poi_match_status", "name": status, "count": str(count)})
    for assessment, count in sorted(Counter(row["poi_category_assessment"] for row in rows).items()):
        summary_rows.append({"group": "poi_category_assessment", "name": assessment, "count": str(count)})
    with SUMMARY_CSV.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["group", "name", "count"])
        writer.writeheader()
        writer.writerows(summary_rows)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> None:
    poi_xlsx, category_xlsx = find_source_files()
    category_labels = build_category_cache(category_xlsx)
    build_poi_cache(poi_xlsx, category_labels)
    pois = load_pois()
    grid = build_grid(pois)

    with TARGETS_IN.open("r", encoding="utf-8-sig", newline="") as file:
        target_rows = list(csv.DictReader(file))

    output_rows: list[dict[str, str]] = []
    for index, row in enumerate(target_rows, start=1):
        matched = match_facility(row, pois, grid)
        output_rows.append({**row, **matched})
        if index % 500 == 0:
            print(f"matched {index}/{len(target_rows)}")

    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=[*target_rows[0].keys(), *OUTPUT_FIELDNAMES])
        writer.writeheader()
        writer.writerows(output_rows)

    p1_p2_rows = [row for row in output_rows if row["validation_priority"] in {"1_높음", "2_중간"}]
    p3_rows = [row for row in output_rows if row["validation_priority"] == "3_낮음"]
    first_review_rows = [row for row in output_rows if row["poi_match_status"] in FIRST_REVIEW_STATUSES]
    for path, rows in [(OUT_P1_P2_CSV, p1_p2_rows), (OUT_P3_CSV, p3_rows), (OUT_FIRST_REVIEW_CSV, first_review_rows)]:
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=[*target_rows[0].keys(), *OUTPUT_FIELDNAMES])
            writer.writeheader()
            writer.writerows(rows)

    summary_groups = []
    for group_name, key in [
        ("status", "poi_match_status"),
        ("priority", "validation_priority"),
        ("category", "ui_category"),
        ("auto_decision", "auto_decision"),
    ]:
        for name, count in sorted(Counter(row[key] for row in first_review_rows).items()):
            summary_groups.append({"group": group_name, "name": name, "count": str(count)})
    with OUT_FIRST_REVIEW_SUMMARY_CSV.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["group", "name", "count"])
        writer.writeheader()
        writer.writerows(summary_groups)

    write_summary(output_rows)


if __name__ == "__main__":
    main()
