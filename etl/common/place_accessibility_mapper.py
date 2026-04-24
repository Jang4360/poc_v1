from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT_DIR / "etl" / "raw"
RUNTIME_DIR = ROOT_DIR / "runtime" / "etl" / "03-reference-load"

SOURCE_CSV = RAW_DIR / "disabled_person_convenient_facilities.csv"
PLACES_CSV = RAW_DIR / "place_merged_broad_category_final.csv"
ACCESSIBILITY_CSV = RAW_DIR / "place_accessibility_features_merged_final.csv"
REPORT_JSON = RUNTIME_DIR / "place_accessibility_remap_report.json"

FEATURE_ORDER = [
    "accessibleEntrance",
    "ramp",
    "stepFree",
    "accessibleParking",
    "accessibleToilet",
    "elevator",
    "accessibleRoom",
    "guidanceFacility",
]

CATEGORY_DEFAULT_FEATURES: dict[str, tuple[str, ...]] = {
    "경찰서": ("accessibleEntrance", "accessibleToilet", "ramp", "stepFree"),
    "공중화장실": ("accessibleEntrance", "accessibleToilet", "ramp", "stepFree"),
    "관광숙박시설": (
        "accessibleEntrance",
        "accessibleParking",
        "accessibleToilet",
        "elevator",
        "ramp",
        "stepFree",
    ),
    "국민건강보험공단": (
        "accessibleEntrance",
        "accessibleParking",
        "accessibleToilet",
        "elevator",
        "ramp",
        "stepFree",
    ),
    "보건소": ("accessibleEntrance", "accessibleToilet", "ramp", "stepFree"),
    "복지시설": (
        "accessibleEntrance",
        "accessibleParking",
        "accessibleToilet",
        "elevator",
        "ramp",
        "stepFree",
    ),
    "은행": ("accessibleEntrance", "accessibleParking", "elevator", "ramp", "stepFree"),
    "음식점": ("accessibleEntrance", "ramp", "stepFree"),
    "종합병원": (
        "accessibleEntrance",
        "accessibleParking",
        "accessibleToilet",
        "elevator",
        "guidanceFacility",
        "ramp",
        "stepFree",
    ),
    "지역자치센터": ("accessibleEntrance", "accessibleToilet", "ramp", "stepFree"),
}


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return [{key: (value or "").strip() for key, value in row.items()} for row in csv.DictReader(fh)]


def write_csv_rows(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_point_wkt(value: str) -> tuple[float, float] | None:
    text = (value or "").strip()
    if not text or "POINT(" not in text:
        return None
    body = text.split("POINT(", 1)[1].rstrip(")")
    lon, lat = body.split()[:2]
    return float(lat), float(lon)


def parse_source_coords(row: dict[str, str]) -> tuple[float, float] | None:
    lat_text = (row.get("faclLat") or "").strip()
    lon_text = (row.get("faclLng") or "").strip()
    if not lat_text or not lon_text:
        return None
    lat = float(lat_text)
    lon = float(lon_text)
    if lat == 0 or lon == 0:
        return None
    return lat, lon


def haversine_distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    radius_m = 6_371_000.0
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    d_lat = lat2 - lat1
    d_lon = lon2 - lon1
    sin_lat = math.sin(d_lat / 2.0)
    sin_lon = math.sin(d_lon / 2.0)
    value = sin_lat**2 + math.cos(lat1) * math.cos(lat2) * sin_lon**2
    return 2.0 * radius_m * math.asin(math.sqrt(value))


@dataclass(frozen=True)
class PlaceRecord:
    place_id: int
    name: str
    address: str
    coords: tuple[float, float] | None

    @classmethod
    def from_row(cls, row: dict[str, str]) -> "PlaceRecord":
        return cls(
            place_id=int(row["placeId"]),
            name=row["name"],
            address=row["address"],
            coords=parse_point_wkt(row.get("point", "")),
        )


@dataclass
class MatchResult:
    place_id: int | None
    status: str
    used_existing_features: bool = False
    distance_m: float | None = None


class PlaceIndex:
    def __init__(self, places: list[PlaceRecord]) -> None:
        self.by_name_address: dict[tuple[str, str], list[PlaceRecord]] = defaultdict(list)
        self.by_address: dict[str, list[PlaceRecord]] = defaultdict(list)
        self.by_prefix: dict[str, list[PlaceRecord]] = defaultdict(list)
        for place in places:
            self.by_name_address[(place.name, place.address)].append(place)
            self.by_address[place.address].append(place)
            self.by_prefix[address_prefix(place.address)].append(place)


def address_prefix(address: str) -> str:
    return " ".join((address or "").split()[:2])


def feature_sort_key(feature_type: str) -> tuple[int, str]:
    try:
        return (FEATURE_ORDER.index(feature_type), feature_type)
    except ValueError:
        return (len(FEATURE_ORDER), feature_type)


def default_features_for_category(category: str) -> tuple[str, ...]:
    return CATEGORY_DEFAULT_FEATURES.get(category, ())


def select_candidate(
    candidates: list[PlaceRecord],
    row: dict[str, str],
    existing_features: dict[int, set[str]],
    *,
    distance_limit_m: float | None = None,
) -> tuple[PlaceRecord | None, bool, float | None]:
    if not candidates:
        return None, False, None

    if len(candidates) == 1:
        place = candidates[0]
        if distance_limit_m is None:
            return place, bool(existing_features.get(place.place_id)), None
        source_coords = parse_source_coords(row)
        if source_coords is None or place.coords is None:
            return None, False, None
        distance_m = haversine_distance_m(source_coords, place.coords)
        if distance_m <= distance_limit_m:
            return place, bool(existing_features.get(place.place_id)), distance_m
        return None, False, distance_m

    candidates_with_features = [place for place in candidates if existing_features.get(place.place_id)]
    narrowed = candidates_with_features or candidates
    used_existing_features = len(candidates_with_features) == 1

    source_coords = parse_source_coords(row)
    if source_coords is not None:
        scored: list[tuple[float, int, PlaceRecord]] = []
        for place in narrowed:
            if place.coords is None:
                continue
            scored.append((haversine_distance_m(source_coords, place.coords), place.place_id, place))
        if scored:
            scored.sort(key=lambda item: (item[0], item[1]))
            distance_m, _, place = scored[0]
            if distance_limit_m is None or distance_m <= distance_limit_m:
                return place, used_existing_features or bool(existing_features.get(place.place_id)), distance_m

    place = min(narrowed, key=lambda item: item.place_id)
    if distance_limit_m is not None:
        return None, False, None
    return place, used_existing_features or bool(existing_features.get(place.place_id)), None


def match_source_row(
    row: dict[str, str],
    index: PlaceIndex,
    existing_features: dict[int, set[str]],
) -> MatchResult:
    candidates = index.by_name_address.get((row["faclNm"], row["lcMnad"]), [])
    if candidates:
        place, used_existing, distance_m = select_candidate(candidates, row, existing_features)
        if place is not None:
            status = "exact_name_address" if len(candidates) == 1 else "exact_name_address_multi"
            return MatchResult(place.place_id, status, used_existing, distance_m)

    candidates = index.by_address.get(row["lcMnad"], [])
    if candidates:
        place, used_existing, distance_m = select_candidate(candidates, row, existing_features)
        if place is not None:
            status = "exact_address" if len(candidates) == 1 else "exact_address_multi"
            return MatchResult(place.place_id, status, used_existing, distance_m)

    source_coords = parse_source_coords(row)
    if source_coords is None:
        return MatchResult(None, "unmatched")

    prefix_candidates = index.by_prefix.get(address_prefix(row["lcMnad"]), [])
    place, used_existing, distance_m = select_candidate(
        prefix_candidates,
        row,
        existing_features,
        distance_limit_m=20.0,
    )
    if place is not None:
        return MatchResult(place.place_id, "nearest_20m", used_existing, distance_m)
    return MatchResult(None, "unmatched")


def load_existing_features(path: Path) -> dict[int, set[str]]:
    features: dict[int, set[str]] = defaultdict(set)
    for row in read_csv_rows(path):
        features[int(row["placeId"])].add(row["featureType"])
    return features


def build_accessibility_rows(
    source_rows: list[dict[str, str]],
    place_rows: list[dict[str, str]],
    existing_features: dict[int, set[str]],
) -> tuple[list[dict[str, str]], dict[str, Any]]:
    places = [PlaceRecord.from_row(row) for row in place_rows]
    index = PlaceIndex(places)
    result_features: dict[int, set[str]] = defaultdict(set)
    match_status_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    unmatched_rows: list[dict[str, str]] = []
    defaulted_place_ids: set[int] = set()
    reused_place_ids: set[int] = set()

    for row in source_rows:
        match = match_source_row(row, index, existing_features)
        match_status_counts[match.status] += 1
        if match.place_id is None:
            unmatched_rows.append(row)
            continue

        category = row["faclTyCd"]
        category_counts[category] += 1

        existing = existing_features.get(match.place_id, set())
        if existing:
            result_features[match.place_id].update(existing)
            reused_place_ids.add(match.place_id)
            continue

        defaults = default_features_for_category(category)
        if defaults:
            result_features[match.place_id].update(defaults)
            defaulted_place_ids.add(match.place_id)

    rows: list[dict[str, str]] = []
    next_id = 1
    for place_id in sorted(result_features):
        for feature_type in sorted(result_features[place_id], key=feature_sort_key):
            rows.append(
                {
                    "id": str(next_id),
                    "placeId": str(place_id),
                    "featureType": feature_type,
                    "isAvailable": "true",
                }
            )
            next_id += 1

    report = {
        "source_rows": len(source_rows),
        "matched_rows": len(source_rows) - len(unmatched_rows),
        "unmatched_rows": len(unmatched_rows),
        "matched_unique_place_ids": len(result_features),
        "reused_existing_feature_place_ids": len(reused_place_ids),
        "defaulted_place_ids": len(defaulted_place_ids),
        "output_rows": len(rows),
        "match_status_counts": dict(sorted(match_status_counts.items())),
        "category_counts": dict(sorted(category_counts.items())),
        "unmatched_samples": [
            {
                "faclTyCd": row["faclTyCd"],
                "faclNm": row["faclNm"],
                "lcMnad": row["lcMnad"],
            }
            for row in unmatched_rows[:25]
        ],
    }
    return rows, report


def remap_place_accessibility(
    *,
    source_csv: Path = SOURCE_CSV,
    places_csv: Path = PLACES_CSV,
    seed_csv: Path = ACCESSIBILITY_CSV,
    output_csv: Path = ACCESSIBILITY_CSV,
    report_json: Path | None = REPORT_JSON,
) -> dict[str, Any]:
    source_rows = read_csv_rows(source_csv)
    place_rows = read_csv_rows(places_csv)
    existing_features = load_existing_features(seed_csv)
    rows, report = build_accessibility_rows(source_rows, place_rows, existing_features)
    write_csv_rows(output_csv, rows, ["id", "placeId", "featureType", "isAvailable"])
    if report_json is not None:
        write_report(report_json, report)
    return report
