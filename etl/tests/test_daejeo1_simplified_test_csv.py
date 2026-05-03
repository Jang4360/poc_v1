from __future__ import annotations

from importlib import import_module


daejeo1_simplify = import_module("etl.scripts.21_generate_daejeo1_simplified_test_csv")


def _payload(features: list[dict]) -> dict:
    return {
        "meta": {"centerLat": 35.0, "centerLon": 128.0},
        "summary": {"nodeCount": 0, "segmentCount": len(features)},
        "layers": {
            "roadNodes": {"type": "FeatureCollection", "features": []},
            "roadSegments": {"type": "FeatureCollection", "features": features},
        },
    }


def _line(edge_id: int, coords: list[list[float]], segment_type: str = "ROAD_BOUNDARY") -> dict:
    return {
        "type": "Feature",
        "properties": {"edgeId": edge_id, "segmentType": segment_type},
        "geometry": {"type": "LineString", "coordinates": coords},
    }


def test_simplify_boundary_payload_keeps_right_angle_corner_node() -> None:
    payload = _payload(
        [
            _line(
                1,
                [
                    [128.0, 35.0],
                    [128.001, 35.0],
                    [128.001, 35.001],
                ],
            )
        ]
    )

    result = daejeo1_simplify.simplify_boundary_payload(
        payload,
        corner_angle_degrees=45,
        line_tolerance_degrees=0.000001,
        max_shape_points=5,
        min_corner_leg_meter=0,
        max_corner_nodes_per_line=1,
        node_snap_meter=0,
    )

    assert result["summary"]["nodeCount"] == 3
    assert result["summary"]["segmentCount"] == 2
    assert any(node["properties"]["simplifyRole"] == "corner" for node in result["layers"]["roadNodes"]["features"])


def test_simplify_boundary_payload_preserves_separate_source_lines_without_connecting_them() -> None:
    payload = _payload(
        [
            _line(1, [[128.0, 35.0], [128.001, 35.0]]),
            _line(2, [[128.0011, 35.0001], [128.002, 35.001]]),
        ]
    )

    result = daejeo1_simplify.simplify_boundary_payload(
        payload,
        corner_angle_degrees=45,
        line_tolerance_degrees=0.000001,
        max_shape_points=5,
        min_corner_leg_meter=0,
        max_corner_nodes_per_line=1,
        node_snap_meter=0,
    )

    segments = result["layers"]["roadSegments"]["features"]
    assert result["summary"]["segmentCount"] == 2
    assert [segment["properties"]["sourceEdgeIds"] for segment in segments] == ["1", "2"]
    assert segments[0]["geometry"]["coordinates"] == [[128.0, 35.0], [128.001, 35.0]]
    assert segments[1]["geometry"]["coordinates"] == [[128.0011, 35.0001], [128.002, 35.001]]


def test_simplify_boundary_payload_collapses_smooth_curve_to_endpoint_nodes_with_shape_coords() -> None:
    payload = _payload(
        [
            _line(
                1,
                [
                    [128.0, 35.0],
                    [128.0005, 35.00003],
                    [128.001, 35.00005],
                    [128.0015, 35.00003],
                    [128.002, 35.0],
                ],
                "ROAD_BOUNDARY_INNER",
            )
        ]
    )

    result = daejeo1_simplify.simplify_boundary_payload(
        payload,
        corner_angle_degrees=45,
        line_tolerance_degrees=0.000001,
        max_shape_points=5,
        min_corner_leg_meter=0,
        max_corner_nodes_per_line=1,
        node_snap_meter=0,
    )

    segments = result["layers"]["roadSegments"]["features"]
    assert result["summary"]["nodeCount"] == 2
    assert result["summary"]["segmentCount"] == 1
    assert segments[0]["properties"]["segmentType"] == "ROAD_BOUNDARY_INNER"
    assert 2 <= len(segments[0]["geometry"]["coordinates"]) <= 5


def test_simplify_boundary_payload_snaps_nearby_endpoint_nodes_and_keeps_segments_connected() -> None:
    payload = _payload(
        [
            _line(1, [[128.0, 35.0], [128.001, 35.0]]),
            _line(2, [[128.00102, 35.0], [128.002, 35.0]]),
        ]
    )

    result = daejeo1_simplify.simplify_boundary_payload(
        payload,
        corner_angle_degrees=45,
        line_tolerance_degrees=0.000001,
        max_shape_points=5,
        min_corner_leg_meter=0,
        max_corner_nodes_per_line=1,
        node_snap_meter=3,
    )

    segments = result["layers"]["roadSegments"]["features"]
    assert result["summary"]["nodeCount"] == 3
    assert result["summary"]["segmentCount"] == 2
    assert segments[0]["properties"]["toNodeId"] == segments[1]["properties"]["fromNodeId"]


def test_simplify_boundary_payload_moves_segment_endpoints_to_snapped_node_coordinates() -> None:
    payload = _payload(
        [
            _line(1, [[128.0, 35.0], [128.001, 35.0]]),
            _line(2, [[128.00102, 35.0], [128.002, 35.0]]),
        ]
    )

    result = daejeo1_simplify.simplify_boundary_payload(
        payload,
        corner_angle_degrees=45,
        line_tolerance_degrees=0.000001,
        max_shape_points=5,
        min_corner_leg_meter=0,
        max_corner_nodes_per_line=1,
        node_snap_meter=3,
    )

    node_by_id = {
        node["properties"]["vertexId"]: node["geometry"]["coordinates"]
        for node in result["layers"]["roadNodes"]["features"]
    }
    for segment in result["layers"]["roadSegments"]["features"]:
        props = segment["properties"]
        coords = segment["geometry"]["coordinates"]
        assert coords[0] == node_by_id[props["fromNodeId"]]
        assert coords[-1] == node_by_id[props["toNodeId"]]
