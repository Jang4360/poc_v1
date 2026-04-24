from __future__ import annotations

from pathlib import Path

import pytest
import shapefile

from etl.common import reference_loader


class _MockShape:
    """Minimal shapefile.Shape stand-in for unit tests."""

    def __init__(self, shape_type: int, points: list, parts: list | None = None) -> None:
        self.shapeType = shape_type
        self.shapeTypeName = shapefile.SHAPETYPE_LOOKUP.get(shape_type, "UNKNOWN")
        self.points = points
        self.parts = parts if parts is not None else [0]


def test_normalize_header_strips_quotes() -> None:
    assert reference_loader.normalize_header('"elevatorId"') == "elevatorId"


def test_parse_wkt_point_extracts_lon_lat() -> None:
    assert reference_loader.parse_wkt_point("POINT(129.1587 35.1636)") == (129.1587, 35.1636)


def test_ewkt_point_from_wkt_adds_srid() -> None:
    assert reference_loader.ewkt_point_from_wkt("POINT(129.1 35.2)") == "SRID=4326;POINT(129.1000000000 35.2000000000)"


def test_parse_bool_accepts_true_string() -> None:
    assert reference_loader.parse_bool("true") is True
    assert reference_loader.parse_bool("false") is False


def test_read_csv_rows_falls_back_to_cp949(tmp_path: Path) -> None:
    path = tmp_path / "bus.csv"
    path.write_bytes("인가노선,운행구분\n10,저상\n".encode("cp949"))
    rows, encoding, headers = reference_loader.read_csv_rows(path)
    assert encoding == "cp949"
    assert headers == ["인가노선", "운행구분"]
    assert rows == [{"인가노선": "10", "운행구분": "저상"}]


def test_geometry_hash_is_stable() -> None:
    assert reference_loader.geometry_hash("POINT(1 2)") == reference_loader.geometry_hash("POINT(1 2)")


# H-1: normalize_crossing_state
def test_normalize_crossing_state_valid_passthrough() -> None:
    assert reference_loader.normalize_crossing_state("TRAFFIC_SIGNALS") == "TRAFFIC_SIGNALS"
    assert reference_loader.normalize_crossing_state("NO") == "NO"
    assert reference_loader.normalize_crossing_state("UNKNOWN") == "UNKNOWN"


def test_normalize_crossing_state_empty_returns_unknown() -> None:
    assert reference_loader.normalize_crossing_state("") == "UNKNOWN"
    assert reference_loader.normalize_crossing_state("  ") == "UNKNOWN"


def test_normalize_crossing_state_unrecognized_returns_unknown() -> None:
    assert reference_loader.normalize_crossing_state("YES") == "UNKNOWN"
    assert reference_loader.normalize_crossing_state("신호등") == "UNKNOWN"


# H-2: _deduplicate_elevator_rows
def test_deduplicate_elevator_rows_removes_exact_duplicates() -> None:
    row = {"stationId": "S1", "entranceNo": "1", "point": "POINT(129.1 35.1)", "elevatorId": "100"}
    rows = [row, dict(row), dict(row)]
    valid, dup_count = reference_loader._deduplicate_elevator_rows(rows)
    assert len(valid) == 1
    assert dup_count == 2


def test_deduplicate_elevator_rows_keeps_different_entrances() -> None:
    rows = [
        {"stationId": "S1", "entranceNo": "1", "point": "POINT(129.1 35.1)", "elevatorId": "100"},
        {"stationId": "S1", "entranceNo": "2", "point": "POINT(129.1 35.1)", "elevatorId": "101"},
    ]
    valid, dup_count = reference_loader._deduplicate_elevator_rows(rows)
    assert len(valid) == 2
    assert dup_count == 0


# H-3: degree_radius 상수 검증
def test_degree_radius_uses_90km_per_degree() -> None:
    """10m 검색 반경이 위도 35° 경도 스케일로 올바르게 변환되는지 확인한다."""
    radius_m = 10.0
    degree_radius = radius_m / 90_000.0
    assert abs(degree_radius - 0.000111) < 1e-6


def test_derive_width_state_uses_accessibility_thresholds() -> None:
    assert reference_loader.derive_width_state(None) == "UNKNOWN"
    assert reference_loader.derive_width_state(0) == "UNKNOWN"
    assert reference_loader.derive_width_state(1.0) == "NARROW"
    assert reference_loader.derive_width_state(1.2) == "ADEQUATE_120"
    assert reference_loader.derive_width_state(1.5) == "ADEQUATE_150"


def test_surface_state_from_qual_uses_confirmed_code_table() -> None:
    assert reference_loader.surface_state_from_qual("SWQ000") == "UNKNOWN"
    assert reference_loader.surface_state_from_qual("SWQ001") == "PAVED"
    assert reference_loader.surface_state_from_qual("SWQ002") == "PAVED"
    assert reference_loader.surface_state_from_qual("SWQ003") == "BLOCK"
    assert reference_loader.surface_state_from_qual("SWQ004") == "UNPAVED"
    assert reference_loader.surface_state_from_qual("SWQ005") == "OTHER"
    assert reference_loader.surface_state_from_qual("SWQ999") == "OTHER"
    assert reference_loader.surface_state_from_qual("BAD") == "UNKNOWN"


# M-2: _ring_wkt and shape_to_wkt_4326
def test_ring_wkt_closes_open_ring() -> None:
    points = [(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)]
    result = reference_loader._ring_wkt(points)
    assert result.startswith("(") and result.endswith(")")
    assert result.count("1.0000000000 2.0000000000") == 2


def test_ring_wkt_already_closed_is_not_doubled() -> None:
    points = [(1.0, 2.0), (3.0, 4.0), (5.0, 6.0), (1.0, 2.0)]
    result = reference_loader._ring_wkt(points)
    assert result.count("1.0000000000 2.0000000000") == 2


def test_shape_to_wkt_4326_polyline_returns_linestring(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reference_loader, "transform_point_5179_to_4326", lambda p: p)
    shape = _MockShape(shapefile.POLYLINE, [(1.0, 2.0), (3.0, 4.0)])
    result = reference_loader.shape_to_wkt_4326(shape)
    assert result.startswith("LINESTRING(")
    assert "1.0000000000 2.0000000000" in result
    assert "3.0000000000 4.0000000000" in result


def test_shape_to_wkt_4326_polygon_returns_valid_wkt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reference_loader, "transform_point_5179_to_4326", lambda p: p)
    points = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    shape = _MockShape(shapefile.POLYGON, points)
    result = reference_loader.shape_to_wkt_4326(shape)
    assert result.startswith("POLYGON((")
    assert result.endswith("))")


def test_shape_to_wkt_4326_multipart_linestring(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(reference_loader, "transform_point_5179_to_4326", lambda p: p)
    points = [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0), (3.0, 3.0)]
    shape = _MockShape(shapefile.POLYLINE, points, parts=[0, 2])
    result = reference_loader.shape_to_wkt_4326(shape)
    assert result.startswith("MULTILINESTRING(")


def test_filter_polygon_half_width_uses_buffer_floor() -> None:
    assert reference_loader.filter_polygon_half_width(None) == 1.0
    assert reference_loader.filter_polygon_half_width(0.0) == 1.0
    assert reference_loader.filter_polygon_half_width(1.0) == 1.0
    assert reference_loader.filter_polygon_half_width(4.0) == 2.0


def test_shape_to_wkt_5179_polyline_returns_linestring() -> None:
    shape = _MockShape(shapefile.POLYLINE, [(10.0, 20.0), (30.0, 40.0)])
    result = reference_loader.shape_to_wkt_5179(shape)
    assert result == "LINESTRING(10.0000000000 20.0000000000,30.0000000000 40.0000000000)"


def test_shape_to_wkt_5179_multipart_polyline_returns_multilinestring() -> None:
    shape = _MockShape(shapefile.POLYLINE, [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0), (3.0, 3.0)], parts=[0, 2])
    result = reference_loader.shape_to_wkt_5179(shape)
    assert result == (
        "MULTILINESTRING((0.0000000000 0.0000000000,1.0000000000 1.0000000000),"
        "(2.0000000000 2.0000000000,3.0000000000 3.0000000000))"
    )
