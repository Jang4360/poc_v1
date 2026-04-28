from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path


ROOT = Path(r"C:\Users\SSAFY\workspace")
PLACE_SOURCE = ROOT / "place" / "source"
ACCESSIBILITY_SOURCE = ROOT / "accessibility" / "source"
POC_ROOT = Path(__file__).resolve().parents[1]
ASSETS_DATA = POC_ROOT / "assets" / "data"
DATA_ROOT = POC_ROOT / "data"
DATA_SOURCE = DATA_ROOT / "source"
DATA_ADOPTED = DATA_ROOT / "adopted"
DATA_REPORTS = DATA_ROOT / "reports"

CSV_OUT = DATA_SOURCE / "source_places_with_accessibility.csv"
ADOPTED_CSV_OUT = DATA_ADOPTED / "adopted_places_with_accessibility.csv"
ADOPTED_PLACES_TABLE_OUT = DATA_ADOPTED / "adopted_places.csv"
ADOPTED_ACCESSIBILITY_TABLE_OUT = DATA_ADOPTED / "adopted_place_accessibility.csv"
ERD_PLACES_TABLE_OUT = DATA_ADOPTED / "places_erd.csv"
ERD_ACCESSIBILITY_TABLE_OUT = DATA_ADOPTED / "place_accessibility_features_erd.csv"
FACILITIES_JS_OUT = ASSETS_DATA / "facilities-data.js"
SUMMARY_JS_OUT = ASSETS_DATA / "accessibility-summary-data.js"
REPORT_OUT = DATA_REPORTS / "source_places_accessibility_report.json"
CATEGORY_REVIEW_OUT = DATA_REPORTS / "category_mapping_review.csv"
FACILITY_REVIEW_DIR = DATA_REPORTS / "facility_review"
FACILITY_REVIEW_CSV_OUT = FACILITY_REVIEW_DIR / "facility_review_candidates.csv"
FACILITY_REVIEW_SUMMARY_OUT = FACILITY_REVIEW_DIR / "facility_review_summary.json"

DISABLED_PUBLIC_CANDIDATES = [
    "disabled_person_convenient_facilities_busan_all_types.csv",
    "disabled_person_convenient_facilities.csv",
]

PLACE_SOURCES = [
    ("tourist_spot", "place_accessible_tourism_tourist_spot.csv", "place_accessibility_features_accessible_tourism_tourist_spot.csv"),
    ("restaurant", "place_accessible_tourism_restaurant.csv", "place_accessibility_features_accessible_tourism_restaurant.csv"),
    ("accommodation", "place_accessible_tourism_accommodation.csv", "place_accessibility_features_accessible_tourism_accommodation.csv"),
    ("barrier_free_facility", "place_barrier_free_facility.csv", "place_accessibility_features_barrier_free_facility.csv"),
    ("public_toilet", "place_public_toilet.csv", "place_accessibility_features_public_toilet.csv"),
    ("subway_station", "place_subway_station.csv", "place_accessibility_features_subway_station.csv"),
    ("charging_station", "place_charging_station.csv", None),
]

DISTRICTS = [
    "\uac15\uc11c\uad6c",
    "\uae08\uc815\uad6c",
    "\uae30\uc7a5\uad70",
    "\ub0a8\uad6c",
    "\ub3d9\uad6c",
    "\ub3d9\ub798\uad6c",
    "\ubd80\uc0b0\uc9c4\uad6c",
    "\ubd81\uad6c",
    "\uc0ac\uc0c1\uad6c",
    "\uc0ac\ud558\uad6c",
    "\uc11c\uad6c",
    "\uc218\uc601\uad6c",
    "\uc5f0\uc81c\uad6c",
    "\uc601\ub3c4\uad6c",
    "\uc911\uad6c",
    "\ud574\uc6b4\ub300\uad6c",
]

CATEGORY_LABELS = {
    "TOURIST_SPOT": "\uad00\uad11\uc9c0",
    "RESTAURANT": "\uc77c\ubc18\uc74c\uc2dd\uc810",
    "ACCOMMODATION": "\uad00\uad11\uc219\ubc15\uc2dc\uc124",
    "BARRIER_FREE_FACILITY": "\uc7a5\uc560\uc778\ud3b8\uc758\uc2dc\uc124",
    "TOILET": "\uacf5\uc911\ud654\uc7a5\uc2e4",
    "SUBWAY_STATION": "\ub3c4\uc2dc\ucca0\ub3c4\uc5ed",
    "CHARGING_STATION": "\uc804\ub3d9\ubcf4\uc7a5\uad6c \ucda9\uc804\uc18c",
}

PUBLIC_CATEGORY_OVERRIDES = {}

ADOPTED_CATEGORY_GROUPS = {
    "\ud654\uc7a5\uc2e4": [
        "\uacf5\uc911\ud654\uc7a5\uc2e4",
    ],
    "\uc804\ub3d9\ubcf4\uc7a5\uad6c \ucda9\uc804\uc18c": [
        "\uc804\ub3d9\ubcf4\uc7a5\uad6c \ucda9\uc804\uc18c",
    ],
    "\uc758\ub8cc\u00b7\ubcf4\uac74": [
        "\uc885\ud569\ubcd1\uc6d0",
        "\ubcd1\uc6d0\u00b7\uce58\uacfc\ubcd1\uc6d0\u00b7\ud55c\ubc29\ubcd1\uc6d0\u00b7\uc815\uc2e0\ubcd1\uc6d0\u00b7\uc694\uc591\ubcd1\uc6d0",
        "\uc758\uc6d0\u00b7\uce58\uacfc\uc758\uc6d0\u00b7\ud55c\uc758\uc6d0\u00b7\uc870\uc0b0\uc18c\u00b7\uc0b0\ud6c4\uc870\ub9ac\uc6d0",
        "\ubcf4\uac74\uc18c",
    ],
    "\ud589\uc815\u00b7\uacf5\uacf5\uae30\uad00": [
        "\uad6d\uac00 \ub610\ub294 \uc9c0\uc790\uccb4 \uccad\uc0ac",
        "\uc9c0\uc5ed\uc790\uce58\uc13c\ud130",
        "\uad6d\ubbfc\uac74\uac15\ubcf4\ud5d8\uacf5\ub2e8 \ubc0f \uc9c0\uc0ac",
        "\uad6d\ubbfc\uc5f0\uae08\uacf5\ub2e8 \ubc0f \uc9c0\uc0ac",
        "\uadfc\ub85c\ubcf5\uc9c0\uacf5\ub2e8 \ubc0f \uc9c0\uc0ac",
        "\uc6b0\uccb4\uad6d",
        "\ud30c\ucd9c\uc18c, \uc9c0\uad6c\ub300",
    ],
    "\ubcf5\uc9c0\u00b7\ub3cc\ubd04": [
        "\uc7a5\uc560\uc778\ubcf5\uc9c0\uc2dc\uc124",
        "\ub178\uc778\ubcf5\uc9c0\uc2dc\uc124",
        "\uc774\uc678 \uc0ac\ud68c\ubcf5\uc9c0\uc2dc\uc124",
        "\uc544\ub3d9\ubcf5\uc9c0\uc2dc\uc124",
        "\uc9c0\uc5ed\uc544\ub3d9\uc13c\ud130",
        "\uacbd\ub85c\ub2f9",
    ],
    "\uc74c\uc2dd\u00b7\uce74\ud398": [
        "\uc77c\ubc18\uc74c\uc2dd\uc810",
        "\ud734\uac8c\uc74c\uc2dd\uc810\u00b7\uc81c\uacfc\uc810",
        "\ud734\uac8c\uc74c\uc2dd\uc810\u00b7\uc81c\uacfc\uc810 \ub4f1",
    ],
    "\uc219\ubc15": [
        "\uad00\uad11\uc219\ubc15\uc2dc\uc124",
        "\uc77c\ubc18\uc219\ubc15\uc2dc\uc124",
        "\uc0dd\ud65c\uc219\ubc15\uc2dc\uc124",
    ],
    "\uad00\uad11\uc9c0": [
        "\uad00\uad11\uc9c0",
    ],
}

ADOPTED_CATEGORY_BY_RAW = {
    raw_category: ui_category
    for ui_category, raw_categories in ADOPTED_CATEGORY_GROUPS.items()
    for raw_category in raw_categories
}

ACCESSIBILITY_LABELS = {
    "accessibleEntrance": "\ubcf4\ud589\uc57d\uc790 \ucd9c\uc785",
    "stepFree": "\ub2e8\ucc28 \uc5c6\uc74c",
    "ramp": "\uacbd\uc0ac\ub85c",
    "elevator": "\uc5d8\ub9ac\ubca0\uc774\ud130",
    "accessibleParking": "\uc804\uc6a9 \uc8fc\ucc28\uad6c\uc5ed",
    "accessibleToilet": "\uc804\uc6a9 \ud654\uc7a5\uc2e4",
    "guidanceFacility": "\uc548\ub0b4\uc2dc\uc124",
    "accessibleRoom": "\uc774\uc6a9 \uac00\ub2a5 \uacf5\uac04",
}

ERD_PLACE_CATEGORIES = {
    "RESTAURANT",
    "TOURIST_SPOT",
    "TOILET",
    "BUS_STATION",
    "ELEVATOR",
    "CHARGING_STATION",
    "BARRIER_FREE_FACILITY",
    "ACCOMMODATION",
}

ERD_CATEGORY_LABELS = {
    "RESTAURANT": "\uc74c\uc2dd\u00b7\uce74\ud398",
    "TOURIST_SPOT": "\uad00\uad11\uc9c0",
    "TOILET": "\ud654\uc7a5\uc2e4",
    "BUS_STATION": "\ubc84\uc2a4\uc815\ub958\uc7a5",
    "ELEVATOR": "\uc5d8\ub9ac\ubca0\uc774\ud130",
    "CHARGING_STATION": "\uc804\ub3d9\ubcf4\uc7a5\uad6c \ucda9\uc804\uc18c",
    "BARRIER_FREE_FACILITY": "\ubcf4\ud589\uc57d\uc790 \ud3b8\uc758\uc2dc\uc124",
    "ACCOMMODATION": "\uc219\ubc15",
}

UI_CATEGORY_TO_ERD_CATEGORY = {
    "\ud654\uc7a5\uc2e4": "TOILET",
    "\uc804\ub3d9\ubcf4\uc7a5\uad6c \ucda9\uc804\uc18c": "CHARGING_STATION",
    "\uc74c\uc2dd\u00b7\uce74\ud398": "RESTAURANT",
    "\uc219\ubc15": "ACCOMMODATION",
    "\uad00\uad11\uc9c0": "TOURIST_SPOT",
    "\uc758\ub8cc\u00b7\ubcf4\uac74": "BARRIER_FREE_FACILITY",
    "\ud589\uc815\u00b7\uacf5\uacf5\uae30\uad00": "BARRIER_FREE_FACILITY",
    "\ubcf5\uc9c0\u00b7\ub3cc\ubd04": "BARRIER_FREE_FACILITY",
}

ERD_FEATURE_TYPES = ("ramp", "autoDoor", "elevator", "accessibleToilet", "chargingStation", "stepFree")
ERD_FEATURE_TYPE_SET = set(ERD_FEATURE_TYPES)
ERD_ACCESSIBILITY_LABELS = {
    "ramp": ACCESSIBILITY_LABELS["ramp"],
    "autoDoor": "\uc790\ub3d9\ubb38",
    "elevator": ACCESSIBILITY_LABELS["elevator"],
    "accessibleToilet": ACCESSIBILITY_LABELS["accessibleToilet"],
    "chargingStation": "\uc804\ub3d9\ubcf4\uc7a5\uad6c \ucda9\uc804",
    "stepFree": ACCESSIBILITY_LABELS["stepFree"],
}

GENERIC_REVIEW_NAME_PATTERNS = [
    "\uc77c\ubc18\uc74c\uc2dd\uc810",
    "\ud734\uac8c\uc74c\uc2dd\uc810",
    "\uae08\uc735\uc5c5\uc18c",
    "\uacf5\uc911\ud654\uc7a5\uc2e4",
    "\uad00\uad11\uc219\ubc15\uc2dc\uc124",
    "\uc77c\ubc18\uc219\ubc15\uc2dc\uc124",
    "\uc0dd\ud65c\uc219\ubc15\uc2dc\uc124",
    "\uc758\uc6d0\u00b7\uce58\uacfc\uc758\uc6d0",
    "\ubcd1\uc6d0\u00b7\uce58\uacfc\ubcd1\uc6d0",
    "\ub178\uc778\ubcf5\uc9c0\uc2dc\uc124",
    "\uc774\uc678 \uc0ac\ud68c\ubcf5\uc9c0\uc2dc\uc124",
]

FACILITY_REVIEW_LABELS = {
    "F1": "\ucd5c\uc6b0\uc120",
    "F2": "\uc6b0\uc120",
    "F3": "\uc77c\ubc18",
}

PLACE_TABLE_FIELDS = [
    "place_key",
    "source_dataset",
    "source_place_id",
    "place_name",
    "ui_category",
    "raw_category",
    "source_category",
    "category_source",
    "category_match_method",
    "is_adopted_category",
    "district_gu",
    "address",
    "point_wkt",
    "latitude",
    "longitude",
    "provider_place_id",
    "public_facility_type",
    "public_facility_id",
    "public_facility_name",
    "public_facility_address",
    "accessibility_count",
    "accessibility_type_codes",
    "accessibility_type_labels",
]

ACCESSIBILITY_TABLE_FIELDS = [
    "place_key",
    "source_dataset",
    "source_place_id",
    "place_name",
    "ui_category",
    "district_gu",
    "address",
    "latitude",
    "longitude",
    "accessibility_order",
    "accessibility_type_code",
    "accessibility_type_label",
]

ERD_PLACE_TABLE_FIELDS = [
    "placeId",
    "name",
    "category",
    "address",
    "point",
    "providerPlaceId",
]

ERD_ACCESSIBILITY_TABLE_FIELDS = [
    "id",
    "placeId",
    "featureType",
    "isAvailable",
]

FACILITY_REVIEW_FIELDS = [
    "review_priority",
    "review_priority_label",
    "review_score",
    "review_flags",
    "review_reasons",
    "placeId",
    "source_place_id",
    "place_name",
    "ui_category",
    "db_category",
    "raw_category",
    "district_gu",
    "address",
    "latitude",
    "longitude",
    "accessibility_count",
    "accessibility_type_labels",
    "source_accessibility_count",
    "source_accessibility_type_labels",
    "kakao_roadview_url",
]


def parse_point(point: str) -> tuple[float | None, float | None]:
    match = re.search(r"POINT\(([-0-9.]+)\s+([-0-9.]+)\)", point or "")
    if not match:
        return None, None
    return float(match.group(2)), float(match.group(1))


def point_key(lat: float, lng: float) -> tuple[float, float]:
    return round(float(lat), 7), round(float(lng), 7)


def district_from_address(address: str | None) -> str:
    # Match longer district names first so "강서구" is not misread as "서구".
    return next((district for district in sorted(DISTRICTS, key=len, reverse=True) if district in (address or "")), "")


def normalize(text: str | None) -> str:
    value = (text or "").lower()
    value = re.sub(r"\([^)]*\)", "", value)
    value = re.sub(r"[^0-9a-z\uac00-\ud7a3]", "", value)
    return value


def public_display_category(raw_type: str | None) -> str:
    value = (raw_type or "").strip()
    return PUBLIC_CATEGORY_OVERRIDES.get(value, value)


def adopted_ui_category(raw_category: str | None) -> str:
    return ADOPTED_CATEGORY_BY_RAW.get((raw_category or "").strip(), "")


def erd_category(source_category: str | None, ui_category: str | None) -> str:
    ui_value = (ui_category or "").strip()
    if ui_value in UI_CATEGORY_TO_ERD_CATEGORY:
        return UI_CATEGORY_TO_ERD_CATEGORY[ui_value]

    source_value = (source_category or "").strip()
    if source_value in ERD_PLACE_CATEGORIES:
        return source_value

    return "BARRIER_FREE_FACILITY"


def erd_accessibility_types(accessibility_types: list[str]) -> list[str]:
    output = []
    seen = set()
    for accessibility_type in accessibility_types:
        if accessibility_type not in ERD_FEATURE_TYPE_SET or accessibility_type in seen:
            continue
        output.append(accessibility_type)
        seen.add(accessibility_type)
    return output


def provider_place_id(row: dict[str, str]) -> str:
    return row["providerPlaceId"] or row["publicFacilityId"] or row["sourceKey"]


def has_generic_review_name(row: dict[str, str]) -> bool:
    name = (row.get("name") or "").strip()
    raw_category = (row.get("facilityCategory") or "").strip()
    public_name = (row.get("publicFacilityName") or "").strip()
    haystack = " ".join([name, raw_category, public_name])
    if name and raw_category and name == raw_category:
        return True
    return any(pattern in haystack for pattern in GENERIC_REVIEW_NAME_PATTERNS)


def facility_review_meta(row: dict[str, str]) -> dict[str, str | int | list[str]]:
    ui_category = row.get("uiCategory", "")
    erd_accessibility = [item for item in row.get("erdAccessibilityTypes", "").split("|") if item]
    source_accessibility = [item for item in row.get("accessibilityTypes", "").split("|") if item]
    source_only_accessibility = [item for item in source_accessibility if item not in ERD_FEATURE_TYPE_SET]
    reasons: list[str] = []
    flags: list[str] = []
    score = 0

    if ui_category in {"\ud654\uc7a5\uc2e4", "\uc804\ub3d9\ubcf4\uc7a5\uad6c \ucda9\uc804\uc18c"}:
        score += 50
        flags.append("destination")
        reasons.append("\ub3c5\ub9bd \ubaa9\uc801\uc9c0")

    if has_generic_review_name(row):
        score += 45
        flags.append("generic_name")
        reasons.append("\uc774\ub984/\ubd84\ub958 \uc560\ub9e4")

    if len(erd_accessibility) >= 4 or len(source_accessibility) >= 5:
        score += 25
        flags.append("many_accessibility")
        reasons.append("\uc811\uadfc\uc131 \uc815\ubcf4 \ub9ce\uc74c")

    if "accessibleToilet" in erd_accessibility:
        score += 20
        flags.append("accessible_toilet")
        reasons.append("\uc804\uc6a9 \ud654\uc7a5\uc2e4 \uc788\uc74c")

    if source_only_accessibility:
        score += min(20, len(source_only_accessibility) * 5)
        flags.append("source_only_accessibility")
        reasons.append("ERD \ubbf8\ubc18\uc601 \uc6d0\ubcf8 \uc811\uadfc\uc131 \uc788\uc74c")

    if row.get("categorySource") == "disabled_public" and row.get("dbCategory") == "BARRIER_FREE_FACILITY":
        score += 10
        flags.append("broad_facility_category")
        reasons.append("\ud3b8\uc758\uc2dc\uc124 \uad11\uc5ed\ubd84\ub958")

    is_generic = "generic_name" in flags
    is_high_accessibility = "many_accessibility" in flags or "accessible_toilet" in flags
    if is_generic and is_high_accessibility:
        priority = "F1"
    elif score >= 50:
        priority = "F2"
    else:
        priority = "F3"

    return {
        "priority": priority,
        "priorityLabel": FACILITY_REVIEW_LABELS[priority],
        "score": score,
        "flags": flags,
        "reasons": reasons,
    }


def to_place_table_row(row: dict[str, str]) -> dict[str, str]:
    return {
        "place_key": row["sourceKey"],
        "source_dataset": row["sourceDataset"],
        "source_place_id": row["placeId"],
        "place_name": row["name"],
        "ui_category": row["uiCategory"],
        "raw_category": row["facilityCategory"],
        "source_category": row["sourceCategory"],
        "category_source": row["categorySource"],
        "category_match_method": row["categoryMatchMethod"],
        "is_adopted_category": row["isAdoptedCategory"],
        "district_gu": row["districtGu"],
        "address": row["address"],
        "point_wkt": row["point"],
        "latitude": row["lat"],
        "longitude": row["lng"],
        "provider_place_id": row["providerPlaceId"],
        "public_facility_type": row["publicFacilityType"],
        "public_facility_id": row["publicFacilityId"],
        "public_facility_name": row["publicFacilityName"],
        "public_facility_address": row["publicFacilityAddress"],
        "accessibility_count": row["accessibilityCount"],
        "accessibility_type_codes": row["accessibilityTypes"],
        "accessibility_type_labels": row["accessibilityLabels"],
    }


def to_accessibility_table_rows(row: dict[str, str]) -> list[dict[str, str]]:
    accessibility_types = [item for item in row["accessibilityTypes"].split("|") if item]
    accessibility_labels = [item for item in row["accessibilityLabels"].split("|") if item]
    output = []
    for index, accessibility_type in enumerate(accessibility_types, start=1):
        output.append(
            {
                "place_key": row["sourceKey"],
                "source_dataset": row["sourceDataset"],
                "source_place_id": row["placeId"],
                "place_name": row["name"],
                "ui_category": row["uiCategory"],
                "district_gu": row["districtGu"],
                "address": row["address"],
                "latitude": row["lat"],
                "longitude": row["lng"],
                "accessibility_order": str(index),
                "accessibility_type_code": accessibility_type,
                "accessibility_type_label": (
                    accessibility_labels[index - 1]
                    if index <= len(accessibility_labels)
                    else ACCESSIBILITY_LABELS.get(accessibility_type, accessibility_type)
                ),
            }
        )
    return output


def to_erd_place_table_row(row: dict[str, str], place_id: int) -> dict[str, str]:
    return {
        "placeId": str(place_id),
        "name": row["name"],
        "category": row["dbCategory"],
        "address": row["address"],
        "point": row["point"],
        "providerPlaceId": provider_place_id(row),
    }


def to_erd_accessibility_table_rows(row: dict[str, str], place_id: int, start_id: int) -> list[dict[str, str]]:
    accessibility_types = [item for item in row["erdAccessibilityTypes"].split("|") if item]
    return [
        {
            "id": str(start_id + index),
            "placeId": str(place_id),
            "featureType": accessibility_type,
            "isAvailable": "true",
        }
    for index, accessibility_type in enumerate(accessibility_types)
    ]


def to_facility_review_row(row: dict[str, str], place_id: int) -> dict[str, str]:
    return {
        "review_priority": row["reviewPriority"],
        "review_priority_label": row["reviewPriorityLabel"],
        "review_score": row["reviewScore"],
        "review_flags": row["reviewFlags"],
        "review_reasons": row["reviewReasons"],
        "placeId": str(place_id),
        "source_place_id": row["placeId"],
        "place_name": row["name"],
        "ui_category": row["uiCategory"],
        "db_category": row["dbCategory"],
        "raw_category": row["facilityCategory"],
        "district_gu": row["districtGu"],
        "address": row["address"],
        "latitude": row["lat"],
        "longitude": row["lng"],
        "accessibility_count": row["erdAccessibilityCount"],
        "accessibility_type_labels": row["erdAccessibilityLabels"],
        "source_accessibility_count": row["accessibilityCount"],
        "source_accessibility_type_labels": row["accessibilityLabels"],
        "kakao_roadview_url": f"https://map.kakao.com/link/roadview/{row['lat']},{row['lng']}",
    }


def read_accessibility(filename: str | None) -> dict[str, list[str]]:
    if filename is None:
        return {}
    path = ACCESSIBILITY_SOURCE / filename
    access_by_place: dict[str, list[str]] = defaultdict(list)
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            if str(row.get("isAvailable", "")).lower() == "true":
                access_by_place[row["placeId"]].append(row["featureType"])
    return access_by_place


def read_disabled_type_by_coordinate() -> tuple[dict[tuple[float, float], list[dict[str, str]]], Counter[str], str]:
    path = next((DATA_SOURCE / filename for filename in DISABLED_PUBLIC_CANDIDATES if (DATA_SOURCE / filename).exists()), None)
    result: dict[tuple[float, float], list[dict[str, str]]] = defaultdict(list)
    type_counts: Counter[str] = Counter()
    if path is None:
        return result, type_counts, ""
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            raw_type = (row.get("faclTyCd") or "").strip()
            if raw_type:
                type_counts[raw_type] += 1
            try:
                lat = float(row.get("faclLat") or 0)
                lng = float(row.get("faclLng") or 0)
            except ValueError:
                continue
            if lat == 0 or lng == 0:
                continue
            result[point_key(lat, lng)].append(row)
    return result, type_counts, path.name


def choose_disabled_match(place: dict[str, str], candidates: list[dict[str, str]]) -> dict[str, str] | None:
    if not candidates:
        return None
    place_name = normalize(place.get("name"))
    place_address = normalize(place.get("address"))
    best = None
    best_score = -1.0
    for candidate in candidates:
        candidate_name = normalize(candidate.get("faclNm"))
        candidate_address = normalize(candidate.get("lcMnad"))
        name_score = SequenceMatcher(None, place_name, candidate_name).ratio() if place_name and candidate_name else 0
        if place_address and candidate_address:
            if place_address in candidate_address or candidate_address in place_address:
                address_score = 1.0
            else:
                address_score = SequenceMatcher(None, place_address, candidate_address).ratio()
        else:
            address_score = 0.0
        score = name_score * 0.55 + address_score * 0.45
        if score > best_score:
            best = candidate
            best_score = score
    return best


def write_category_review(
    rows: list[dict[str, str]],
    public_type_counts: Counter[str],
) -> None:
    public_category_counts: Counter[str] = Counter()
    public_raw_by_category: dict[str, list[str]] = defaultdict(list)
    for raw_type, count in public_type_counts.items():
        category = public_display_category(raw_type)
        public_category_counts[category] += count
        public_raw_by_category[category].append(raw_type)

    adopted_rows = [row for row in rows if row.get("isAdoptedCategory") == "true"]
    map_category_counts = Counter(row["facilityCategory"] for row in adopted_rows)
    matched_public_category_counts = Counter(
        row["facilityCategory"] for row in adopted_rows if row["categorySource"] == "disabled_public"
    )
    source_fallback_category_counts = Counter(
        row["facilityCategory"] for row in adopted_rows if row["categorySource"] == "source_fallback"
    )

    review_rows = []
    for category, public_count in public_category_counts.most_common():
        matched_count = matched_public_category_counts[category]
        review_rows.append(
            {
                "uiCategory": category,
                "publicRawTypes": " + ".join(sorted(public_raw_by_category[category])),
                "publicCount": public_count,
                "matchedSourceRows": matched_count,
                "currentMapRows": map_category_counts[category],
                "sourceFallbackRows": source_fallback_category_counts[category],
                "publicMissingApprox": max(public_count - matched_count, 0),
                "status": "PUBLIC_CATEGORY_PARTIAL_SOURCE_MATCH"
                if matched_count < public_count
                else "PUBLIC_CATEGORY_MATCHED",
            }
        )

    for category, count in map_category_counts.most_common():
        if category in public_category_counts:
            continue
        review_rows.append(
            {
                "uiCategory": category,
                "publicRawTypes": "-",
                "publicCount": 0,
                "matchedSourceRows": 0,
                "currentMapRows": count,
                "sourceFallbackRows": source_fallback_category_counts[category],
                "publicMissingApprox": 0,
                "status": "SOURCE_ONLY_CATEGORY",
            }
        )

    with CATEGORY_REVIEW_OUT.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(review_rows[0].keys()))
        writer.writeheader()
        writer.writerows(review_rows)


def main() -> None:
    for directory in (ASSETS_DATA, DATA_SOURCE, DATA_ADOPTED, DATA_REPORTS, FACILITY_REVIEW_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    disabled_by_coordinate, public_type_counts, public_data_file = read_disabled_type_by_coordinate()
    rows = []
    features = []
    report = {
        "sources": {},
        "skippedNoPoint": 0,
        "publicDataFile": public_data_file,
        "disabledTypeEnriched": 0,
        "duplicateSourceKeys": 0,
        "excludedDuplicateAggregateFiles": [
            "place_accessible_tourism.csv",
            "place_accessibility_features_accessible_tourism.csv",
        ],
        "excludedNoJoinKeyFiles": ["subway_station_elevators_accessibility.csv"],
    }
    seen_source_keys = set()

    for source_name, place_file, accessibility_file in PLACE_SOURCES:
        access_by_place = read_accessibility(accessibility_file)
        source_rows = 0
        source_access_rows = 0
        source_with_access = 0
        with (PLACE_SOURCE / place_file).open("r", encoding="utf-8-sig", newline="") as file:
            for place in csv.DictReader(file):
                source_rows += 1
                source_key = f"{source_name}:{place['placeId']}"
                if source_key in seen_source_keys:
                    report["duplicateSourceKeys"] += 1
                    continue
                seen_source_keys.add(source_key)

                lat, lng = parse_point(place.get("point", ""))
                if lat is None or lng is None:
                    report["skippedNoPoint"] += 1
                    continue

                accessibility_types = access_by_place.get(place["placeId"], [])
                accessibility_labels = [ACCESSIBILITY_LABELS.get(item, item) for item in accessibility_types]
                source_access_rows += len(accessibility_types)
                if accessibility_types:
                    source_with_access += 1

                raw_type = place.get("category", "")
                display_category = CATEGORY_LABELS.get(raw_type, raw_type)
                disabled_raw_type = ""
                disabled_match = None
                category_source = "source_fallback"
                category_match_method = "source_category"
                public_facility_id = ""
                public_facility_name = ""
                public_facility_address = ""
                if source_name == "barrier_free_facility":
                    disabled_match = choose_disabled_match(place, disabled_by_coordinate.get(point_key(lat, lng), []))
                    if disabled_match:
                        disabled_raw_type = disabled_match.get("faclTyCd", "")
                        display_category = public_display_category(disabled_raw_type)
                        category_source = "disabled_public"
                        category_match_method = "coordinate_name_address"
                        public_facility_id = disabled_match.get("faclInfId", "")
                        public_facility_name = disabled_match.get("faclNm", "")
                        public_facility_address = disabled_match.get("lcMnad", "")
                        report["disabledTypeEnriched"] += 1

                ui_category = adopted_ui_category(display_category)
                is_adopted_category = bool(ui_category)
                db_category = erd_category(raw_type, ui_category)
                erd_accessibility = erd_accessibility_types(accessibility_types)
                erd_accessibility_labels = [
                    ERD_ACCESSIBILITY_LABELS.get(item, item) for item in erd_accessibility
                ]
                row = {
                    "sourceKey": source_key,
                    "sourceDataset": source_name,
                    "placeId": place["placeId"],
                    "name": place.get("name", ""),
                    "sourceCategory": raw_type,
                    "dbCategory": db_category,
                    "dbCategoryLabel": ERD_CATEGORY_LABELS.get(db_category, db_category),
                    "facilityCategory": display_category,
                    "uiCategory": ui_category,
                    "isAdoptedCategory": str(is_adopted_category).lower(),
                    "rawFacilityType": disabled_raw_type or raw_type,
                    "categorySource": category_source,
                    "categoryMatchMethod": category_match_method,
                    "publicFacilityType": disabled_raw_type,
                    "publicFacilityId": public_facility_id,
                    "publicFacilityName": public_facility_name,
                    "publicFacilityAddress": public_facility_address,
                    "districtGu": district_from_address(place.get("address")),
                    "address": place.get("address", ""),
                    "point": place.get("point", ""),
                    "lat": f"{lat:.7f}",
                    "lng": f"{lng:.7f}",
                    "providerPlaceId": place.get("providerPlaceId", ""),
                    "accessibilityTypes": "|".join(accessibility_types),
                    "accessibilityLabels": "|".join(accessibility_labels),
                    "accessibilityCount": str(len(accessibility_types)),
                    "erdAccessibilityTypes": "|".join(erd_accessibility),
                    "erdAccessibilityLabels": "|".join(erd_accessibility_labels),
                    "erdAccessibilityCount": str(len(erd_accessibility)),
                }
                review_meta = facility_review_meta(row)
                row.update(
                    {
                        "reviewPriority": str(review_meta["priority"]),
                        "reviewPriorityLabel": str(review_meta["priorityLabel"]),
                        "reviewScore": str(review_meta["score"]),
                        "reviewFlags": "|".join(review_meta["flags"]),
                        "reviewReasons": "|".join(review_meta["reasons"]),
                    }
                )
                rows.append(row)
                if is_adopted_category:
                    features.append(
                        {
                            "type": "Feature",
                            "geometry": {"type": "Point", "coordinates": [lng, lat]},
                            "properties": {
                                "sourceId": source_key,
                                "sourceDataset": source_name,
                                "placeId": place["placeId"],
                                "sourcePlaceId": place["placeId"],
                                "name": place.get("name", ""),
                                "dbCategory": db_category,
                                "dbCategoryLabel": ERD_CATEGORY_LABELS.get(db_category, db_category),
                                "facilityCategory": ui_category,
                                "uiCategory": ui_category,
                                "displaySource": ui_category,
                                "rawFacilityCategory": display_category,
                                "rawFacilityType": disabled_raw_type or raw_type,
                                "categorySource": category_source,
                                "categoryMatchMethod": category_match_method,
                                "publicFacilityType": disabled_raw_type,
                                "publicFacilityId": public_facility_id,
                                "publicFacilityName": public_facility_name,
                                "publicFacilityAddress": public_facility_address,
                                "sourceCategory": raw_type,
                                "districtGu": row["districtGu"],
                                "address": place.get("address", ""),
                                "providerPlaceId": place.get("providerPlaceId", ""),
                                "accessibilityTypes": erd_accessibility,
                                "accessibilityLabels": erd_accessibility_labels,
                                "accessibilityCount": len(erd_accessibility),
                                "sourceAccessibilityTypes": accessibility_types,
                                "sourceAccessibilityLabels": accessibility_labels,
                                "sourceAccessibilityCount": len(accessibility_types),
                                "reviewPriority": row["reviewPriority"],
                                "reviewPriorityLabel": row["reviewPriorityLabel"],
                                "reviewScore": int(row["reviewScore"]),
                                "reviewFlags": row["reviewFlags"].split("|") if row["reviewFlags"] else [],
                                "reviewReasons": row["reviewReasons"].split("|") if row["reviewReasons"] else [],
                            },
                        }
                    )

        report["sources"][source_name] = {
            "placeFile": place_file,
            "accessibilityFile": accessibility_file,
            "placeRows": source_rows,
            "accessibilityRows": source_access_rows,
            "placesWithAccessibility": source_with_access,
        }

    with CSV_OUT.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    adopted_rows = [row for row in rows if row["isAdoptedCategory"] == "true"]
    with ADOPTED_CSV_OUT.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(adopted_rows)

    adopted_place_rows = [to_place_table_row(row) for row in adopted_rows]
    adopted_accessibility_rows = [
        accessibility_row
        for row in adopted_rows
        for accessibility_row in to_accessibility_table_rows(row)
    ]
    place_id_by_source_key = {
        row["sourceKey"]: index
        for index, row in enumerate(adopted_rows, start=1)
    }
    erd_place_rows = [
        to_erd_place_table_row(row, place_id_by_source_key[row["sourceKey"]])
        for row in adopted_rows
    ]
    erd_accessibility_rows = []
    next_accessibility_id = 1
    for row in adopted_rows:
        place_id = place_id_by_source_key[row["sourceKey"]]
        output_rows = to_erd_accessibility_table_rows(row, place_id, next_accessibility_id)
        erd_accessibility_rows.extend(output_rows)
        next_accessibility_id += len(output_rows)

    for feature in features:
        properties = feature["properties"]
        source_key = properties["sourceId"]
        properties["sourcePlaceId"] = properties.get("sourcePlaceId", properties.get("placeId", ""))
        properties["placeId"] = str(place_id_by_source_key[source_key])

    review_priority_rank = {"F1": 0, "F2": 1, "F3": 2}
    facility_review_rows = [
        to_facility_review_row(row, place_id_by_source_key[row["sourceKey"]])
        for row in adopted_rows
    ]
    facility_review_rows.sort(
        key=lambda row: (
            review_priority_rank.get(row["review_priority"], 9),
            -int(row["review_score"]),
            row["district_gu"],
            row["ui_category"],
            row["place_name"],
        )
    )

    with ADOPTED_PLACES_TABLE_OUT.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=PLACE_TABLE_FIELDS)
        writer.writeheader()
        writer.writerows(adopted_place_rows)

    with ADOPTED_ACCESSIBILITY_TABLE_OUT.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=ACCESSIBILITY_TABLE_FIELDS)
        writer.writeheader()
        writer.writerows(adopted_accessibility_rows)

    with ERD_PLACES_TABLE_OUT.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=ERD_PLACE_TABLE_FIELDS)
        writer.writeheader()
        writer.writerows(erd_place_rows)

    with ERD_ACCESSIBILITY_TABLE_OUT.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=ERD_ACCESSIBILITY_TABLE_FIELDS)
        writer.writeheader()
        writer.writerows(erd_accessibility_rows)

    with FACILITY_REVIEW_CSV_OUT.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FACILITY_REVIEW_FIELDS)
        writer.writeheader()
        writer.writerows(facility_review_rows)

    FACILITIES_JS_OUT.write_text(
        "window.FACILITIES_GEOJSON = "
        + json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )

    access_counter = Counter()
    source_access_counter = Counter()
    unsupported_access_counter = Counter()
    places_with_access = 0
    source_places_with_access = 0
    for row in adopted_rows:
        source_values = [item for item in row["accessibilityTypes"].split("|") if item]
        values = [item for item in row["erdAccessibilityTypes"].split("|") if item]
        if source_values:
            source_places_with_access += 1
            source_access_counter.update(source_values)
            unsupported_access_counter.update(
                item for item in source_values if item not in ERD_FEATURE_TYPE_SET
            )
        if values:
            places_with_access += 1
            access_counter.update(values)

    summary = {
        "totalRows": sum(access_counter.values()),
        "totalPlaces": places_with_access,
        "items": [
            {"featureType": key, "label": ERD_ACCESSIBILITY_LABELS.get(key, key), "count": access_counter[key]}
            for key in sorted(access_counter.keys(), key=lambda item: access_counter[item], reverse=True)
        ],
        "availableFeatureTypes": [
            {"featureType": key, "label": ERD_ACCESSIBILITY_LABELS.get(key, key), "count": access_counter[key]}
            for key in ERD_FEATURE_TYPES
        ],
    }
    SUMMARY_JS_OUT.write_text(
        "window.ACCESSIBILITY_SUMMARY = " + json.dumps(summary, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )

    report["outputPlaces"] = len(rows)
    report["adoptedPlaces"] = len(adopted_rows)
    report["removedPlaces"] = len(rows) - len(adopted_rows)
    report["outputPlacesWithAccessibility"] = places_with_access
    report["outputAccessibilityRows"] = sum(access_counter.values())
    report["sourceOutputPlacesWithAccessibility"] = source_places_with_access
    report["sourceOutputAccessibilityRows"] = sum(source_access_counter.values())
    report["sourceUnsupportedAccessibilityRows"] = sum(unsupported_access_counter.values())
    report["sourceUnsupportedAccessibilityCounts"] = dict(unsupported_access_counter)
    report["erd"] = {
        "placesTable": str(ERD_PLACES_TABLE_OUT),
        "accessibilityTable": str(ERD_ACCESSIBILITY_TABLE_OUT),
        "placeRows": len(erd_place_rows),
        "accessibilityRows": len(erd_accessibility_rows),
        "categoryCounts": dict(Counter(row["dbCategory"] for row in adopted_rows)),
        "featureTypeCounts": dict(access_counter),
        "notDerivedFeatureTypes": {
            "autoDoor": "source data has no automatic-door field",
            "chargingStation": "charging stations are modeled as places.category=CHARGING_STATION unless a host-place charging feature exists",
        },
    }
    review_summary = {
        "total": len(facility_review_rows),
        "priorityCounts": dict(Counter(row["review_priority"] for row in facility_review_rows)),
        "flagCounts": dict(
            Counter(
                flag
                for row in facility_review_rows
                for flag in row["review_flags"].split("|")
                if flag
            )
        ),
        "districtPriorityCounts": {
            district: dict(Counter(row["review_priority"] for row in facility_review_rows if row["district_gu"] == district))
            for district in sorted({row["district_gu"] for row in facility_review_rows})
        },
        "csv": str(FACILITY_REVIEW_CSV_OUT),
    }
    FACILITY_REVIEW_SUMMARY_OUT.write_text(
        json.dumps(review_summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    report["facilityReview"] = review_summary
    report["categoryCounts"] = dict(Counter(row["facilityCategory"] for row in rows))
    report["adoptedUiCategoryCounts"] = dict(Counter(row["uiCategory"] for row in adopted_rows))
    report["adoptedRawCategoryCounts"] = dict(Counter(row["facilityCategory"] for row in adopted_rows))
    report["removedCategoryCounts"] = dict(
        Counter(row["facilityCategory"] for row in rows if row["isAdoptedCategory"] != "true")
    )
    report["categoryCorrection"] = {
        "rule": "disabled_public_raw_category_first_then_source_fallback",
        "publicDataFile": public_data_file,
        "publicTypeCounts": dict(public_type_counts),
        "publicCategoryCounts": dict(
            Counter(
                {
                    public_display_category(raw_type): sum(
                        count
                        for source_raw_type, count in public_type_counts.items()
                        if public_display_category(source_raw_type) == public_display_category(raw_type)
                    )
                    for raw_type in public_type_counts
                }
            )
        ),
        "categorySourceCounts": dict(Counter(row["categorySource"] for row in rows)),
        "adoptedCategorySourceCounts": dict(Counter(row["categorySource"] for row in adopted_rows)),
        "adoptedCsv": str(ADOPTED_CSV_OUT),
        "adoptedPlacesTable": str(ADOPTED_PLACES_TABLE_OUT),
        "adoptedAccessibilityTable": str(ADOPTED_ACCESSIBILITY_TABLE_OUT),
        "erdPlacesTable": str(ERD_PLACES_TABLE_OUT),
        "erdAccessibilityTable": str(ERD_ACCESSIBILITY_TABLE_OUT),
        "mapDataFile": str(FACILITIES_JS_OUT),
        "reviewFile": str(CATEGORY_REVIEW_OUT),
    }
    REPORT_OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_category_review(rows, public_type_counts)

    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"csv={CSV_OUT}")
    print(f"js={FACILITIES_JS_OUT}")


if __name__ == "__main__":
    main()
