from __future__ import annotations

from etl.common import segment_self_scan_repair as repair


def _payload(features: list[dict]) -> dict:
    return {
        "meta": {
            "title": "test",
            "centerLat": 35.0,
            "centerLon": 129.0,
            "radiusMeter": 5000,
        },
        "summary": {},
        "layers": {
            "roadNodes": {"type": "FeatureCollection", "features": []},
            "roadSegments": {"type": "FeatureCollection", "features": features},
        },
    }


def _line(edge_id: int, segment_type: str, coords: list[list[float]]) -> dict:
    return {
        "type": "Feature",
        "properties": {"edgeId": edge_id, "segmentType": segment_type},
        "geometry": {"type": "LineString", "coordinates": coords},
    }


def test_self_scan_removes_short_dangling_tail() -> None:
    payload = _payload(
        [
            _line(1, "SIDE_LEFT", [[129.0, 35.0], [129.0005, 35.0]]),
            _line(2, "SIDE_LEFT", [[129.0, 35.0], [129.0, 35.0005]]),
            _line(3, "SIDE_LEFT", [[129.0, 35.0], [129.00002, 35.0]]),
        ]
    )

    repaired, report, _ = repair.run_self_scan_repair(payload, max_iterations=4)

    assert report["passed"] is True
    assert len(repaired["segments"]) == 2
    assert report["reports"][0]["action_count"] >= 1


def test_self_scan_snaps_close_endpoint_cluster() -> None:
    payload = _payload(
        [
            _line(1, "SIDE_LEFT", [[129.0, 35.0], [129.0005, 35.0]]),
            _line(2, "SIDE_RIGHT", [[129.00001, 35.00001], [129.0005, 35.0005]]),
        ]
    )

    repaired, report, _ = repair.run_self_scan_repair(payload, max_iterations=4)

    assert report["passed"] is True
    assert repaired["segments"][0].coords[0] == repaired["segments"][1].coords[0]
    assert report["reports"][0]["snapped_endpoints"] >= 1


def test_build_payload_rebuilds_nodes_and_summary() -> None:
    payload = _payload(
        [
            _line(1, "SIDE_LEFT", [[129.0, 35.0], [129.0005, 35.0]]),
            _line(2, "SIDE_RIGHT", [[129.0, 35.0], [129.0, 35.0005]]),
        ]
    )
    segments = repair.parse_segments(payload)
    output = repair.build_payload_from_segments(
        payload,
        segments,
        output_html=__import__("pathlib").Path("etl/out.html"),
        output_geojson=__import__("pathlib").Path("etl/out.geojson"),
        report={"passed": True},
    )

    assert output["summary"]["segmentCount"] == 2
    assert output["summary"]["nodeCount"] == 3
    assert output["meta"]["selfScanReport"]["passed"] is True


def test_self_scan_connects_same_side_collinear_gap() -> None:
    payload = _payload(
        [
            _line(1, "SIDE_LEFT", [[129.0, 35.0], [129.0002, 35.0]]),
            _line(2, "SIDE_LEFT", [[129.00035, 35.0], [129.00055, 35.0]]),
        ]
    )

    repaired, report, _ = repair.run_self_scan_repair(payload, max_iterations=4)

    assert report["passed"] is True
    assert any(segment.properties.get("repairAction") == "sameSideGapConnect" for segment in repaired["segments"])
    assert any(item["added_edges"] >= 1 for item in report["reports"])


def test_self_scan_does_not_connect_opposite_side_gap() -> None:
    payload = _payload(
        [
            _line(1, "SIDE_LEFT", [[129.0, 35.0], [129.0002, 35.0]]),
            _line(2, "SIDE_RIGHT", [[129.00035, 35.0], [129.00055, 35.0]]),
        ]
    )

    repaired, report, _ = repair.run_self_scan_repair(payload, max_iterations=2)

    assert not any(segment.properties.get("repairAction") == "sameSideGapConnect" for segment in repaired["segments"])
    assert report["passed"] is True


def test_self_scan_removes_dense_intersection_tail() -> None:
    payload = _payload(
        [
            _line(1, "SIDE_LEFT", [[129.0, 35.0], [129.0005, 35.0]]),
            _line(2, "SIDE_RIGHT", [[129.0, 35.0], [129.0, 35.0005]]),
            _line(3, "SIDE_LEFT", [[129.0, 35.0], [128.9995, 35.0]]),
            _line(4, "SIDE_RIGHT", [[129.0, 35.0], [129.0, 34.9995]]),
            _line(5, "SIDE_LEFT", [[129.0, 35.0], [129.00012, 35.00002]]),
        ]
    )

    repaired, report, _ = repair.run_self_scan_repair(payload, max_iterations=4)

    assert report["passed"] is True
    assert len(repaired["segments"]) < 5
    assert any("denseIntersectionTail" in item["details"] for item in report["reports"])


def test_self_scan_removes_bent_same_side_corner_bridge() -> None:
    payload = _payload(
        [
            _line(1, "SIDE_LEFT", [[129.0, 35.0], [129.0002, 35.0]]),
            _line(2, "SIDE_LEFT", [[129.0005, 35.0], [129.0007, 35.0]]),
            _line(3, "SAME_SIDE_CORNER_BRIDGE", [[129.0002, 35.0], [129.00035, 35.00016], [129.0005, 35.0]]),
        ]
    )

    repaired, report, _ = repair.run_self_scan_repair(payload, max_iterations=4)

    assert report["passed"] is True
    assert not any(segment.segment_type == "SAME_SIDE_CORNER_BRIDGE" for segment in repaired["segments"])
    assert any(
        "sameSideCornerBridgeBent" in item["details"] or "sameSideCornerBridgeTooLong" in item["details"]
        for item in report["reports"]
    )


def test_self_scan_normalizes_aligned_same_side_corner_bridge_to_side_segment() -> None:
    payload = _payload(
        [
            _line(1, "SIDE_LEFT", [[129.0, 35.0], [129.0002, 35.0]]),
            _line(2, "SIDE_LEFT", [[129.0005, 35.0], [129.0007, 35.0]]),
            _line(3, "SAME_SIDE_CORNER_BRIDGE", [[129.0002, 35.0], [129.0005, 35.0]]),
        ]
    )

    repaired, report, _ = repair.run_self_scan_repair(payload, max_iterations=4)

    assert report["passed"] is True
    assert not any(segment.segment_type == "SAME_SIDE_CORNER_BRIDGE" for segment in repaired["segments"])
    assert any(
        segment.segment_type == "SIDE_LEFT" and segment.properties.get("repairAction") == "sameSideCornerBridgeNormalized"
        for segment in repaired["segments"]
    )


def test_self_scan_removes_misaligned_same_side_corner_bridge_then_connects_gap() -> None:
    payload = _payload(
        [
            _line(1, "SIDE_RIGHT", [[129.0, 35.0], [129.0002, 35.0]]),
            _line(2, "SIDE_RIGHT", [[129.0005, 35.0], [129.0007, 35.0]]),
            _line(3, "SAME_SIDE_CORNER_BRIDGE", [[129.0002, 35.0], [129.00025, 35.00018]]),
        ]
    )

    repaired, report, _ = repair.run_self_scan_repair(payload, max_iterations=4)

    assert report["passed"] is True
    assert not any(segment.segment_type == "SAME_SIDE_CORNER_BRIDGE" for segment in repaired["segments"])
    assert any(segment.properties.get("repairAction") == "sameSideGapConnect" for segment in repaired["segments"])


def test_self_scan_connects_short_same_side_micro_gap_when_endpoint_has_cross_side_degree_two() -> None:
    payload = _payload(
        [
            _line(1, "SIDE_LEFT", [[129.0, 35.0], [129.0002, 35.0]]),
            _line(2, "SIDE_RIGHT", [[129.0002, 35.0], [129.0002, 35.0002]]),
            _line(3, "SIDE_LEFT", [[129.00045, 35.0], [129.00065, 35.0]]),
        ]
    )

    repaired, report, _ = repair.run_self_scan_repair(payload, max_iterations=4)

    assert report["passed"] is True
    assert any(segment.properties.get("repairAction") == "sameSideGapConnect" for segment in repaired["segments"])


def test_self_scan_does_not_connect_long_degree_two_gap() -> None:
    payload = _payload(
        [
            _line(1, "SIDE_LEFT", [[129.0, 35.0], [129.0002, 35.0]]),
            _line(2, "SIDE_RIGHT", [[129.0002, 35.0], [129.0002, 35.0002]]),
            _line(3, "SIDE_LEFT", [[129.00055, 35.0], [129.00075, 35.0]]),
        ]
    )

    repaired, report, _ = repair.run_self_scan_repair(payload, max_iterations=4)

    assert report["passed"] is True
    assert not any(segment.properties.get("repairAction") == "sameSideGapConnect" for segment in repaired["segments"])


def test_self_scan_does_not_reconnect_already_continuous_same_side_node() -> None:
    payload = _payload(
        [
            _line(1, "SIDE_LEFT", [[129.0, 35.0], [129.0002, 35.0]]),
            _line(2, "SIDE_LEFT", [[129.0002, 35.0], [129.0004, 35.0]]),
            _line(3, "SIDE_LEFT", [[129.00065, 35.0], [129.00085, 35.0]]),
        ]
    )

    repaired, report, _ = repair.run_self_scan_repair(payload, max_iterations=4)

    assert report["passed"] is True
    assert not any(
        segment.properties.get("repairAction") == "sameSideGapConnect"
        and segment.coords[0] == (129.0002, 35.0)
        for segment in repaired["segments"]
    )
