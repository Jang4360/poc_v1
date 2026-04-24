from __future__ import annotations

from etl.common.place_accessibility_mapper import (
    CATEGORY_DEFAULT_FEATURES,
    PlaceIndex,
    PlaceRecord,
    build_accessibility_rows,
    default_features_for_category,
    match_source_row,
)


def test_default_features_for_category_uses_confirmed_mapping() -> None:
    assert default_features_for_category("음식점") == ("accessibleEntrance", "ramp", "stepFree")
    assert default_features_for_category("없는카테고리") == ()


def test_match_source_row_prefers_existing_feature_candidate_on_duplicate_name_address() -> None:
    places = [
        PlaceRecord(place_id=10, name="중복장소", address="부산광역시 중구 중앙대로 1", coords=(35.1, 129.0)),
        PlaceRecord(place_id=11, name="중복장소", address="부산광역시 중구 중앙대로 1", coords=(35.1, 129.0)),
    ]
    index = PlaceIndex(places)
    result = match_source_row(
        {
            "faclNm": "중복장소",
            "lcMnad": "부산광역시 중구 중앙대로 1",
            "faclLat": "35.1",
            "faclLng": "129.0",
            "faclTyCd": "공중화장실",
        },
        index,
        {11: {"accessibleToilet"}},
    )
    assert result.place_id == 11
    assert result.status == "exact_name_address_multi"
    assert result.used_existing_features is True


def test_match_source_row_uses_nearest_20m_fallback() -> None:
    places = [
        PlaceRecord(place_id=20, name="A", address="부산광역시 수영구 광안로 10", coords=(35.1535, 129.1185)),
        PlaceRecord(place_id=21, name="B", address="부산광역시 수영구 광안로 12", coords=(35.1537, 129.1189)),
    ]
    index = PlaceIndex(places)
    result = match_source_row(
        {
            "faclNm": "소스시설",
            "lcMnad": "부산광역시 수영구 광안로 99",
            "faclLat": "35.1535001",
            "faclLng": "129.1185001",
            "faclTyCd": "음식점",
        },
        index,
        {},
    )
    assert result.place_id == 20
    assert result.status == "nearest_20m"
    assert result.distance_m is not None
    assert result.distance_m < 20.0


def test_build_accessibility_rows_reuses_existing_and_applies_defaults() -> None:
    source_rows = [
        {
            "faclNm": "기존매핑시설",
            "lcMnad": "부산광역시 해운대구 해운대로 1",
            "faclLat": "35.1631",
            "faclLng": "129.1635",
            "faclTyCd": "관광숙박시설",
        },
        {
            "faclNm": "신규매핑시설",
            "lcMnad": "부산광역시 해운대구 해운대로 2",
            "faclLat": "35.1632",
            "faclLng": "129.1636",
            "faclTyCd": "음식점",
        },
        {
            "faclNm": "미매핑시설",
            "lcMnad": "부산광역시 해운대구 해운대로 999",
            "faclLat": "0",
            "faclLng": "0",
            "faclTyCd": "은행",
        },
    ]
    place_rows = [
        {
            "placeId": "100",
            "name": "기존매핑시설",
            "address": "부산광역시 해운대구 해운대로 1",
            "point": "POINT(129.1635000 35.1631000)",
        },
        {
            "placeId": "101",
            "name": "신규매핑시설",
            "address": "부산광역시 해운대구 해운대로 2",
            "point": "POINT(129.1636000 35.1632000)",
        },
    ]
    existing_features = {
        100: {"accessibleEntrance", "accessibleParking", "elevator"},
    }

    rows, report = build_accessibility_rows(source_rows, place_rows, existing_features)

    by_place = {}
    for row in rows:
        by_place.setdefault(row["placeId"], []).append(row["featureType"])

    assert sorted(by_place["100"]) == ["accessibleEntrance", "accessibleParking", "elevator"]
    assert sorted(by_place["101"]) == sorted(CATEGORY_DEFAULT_FEATURES["음식점"])
    assert report["matched_rows"] == 2
    assert report["unmatched_rows"] == 1
    assert report["defaulted_place_ids"] == 1
    assert report["reused_existing_feature_place_ids"] == 1
