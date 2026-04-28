from __future__ import annotations

from importlib import import_module


corner_preview = import_module("etl.scripts.19_generate_sinho_corner_node_preview")


def test_split_payload_at_corners_creates_corner_nodes_and_split_segments() -> None:
    payload = {
        "meta": {"centerLat": 35.0, "centerLon": 128.0},
        "summary": {"nodeCount": 0, "segmentCount": 1, "segmentTypeCounts": []},
        "layers": {
            "roadNodes": {"type": "FeatureCollection", "features": []},
            "roadSegments": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"edgeId": 7, "segmentType": "ROAD_BOUNDARY"},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [
                                [128.0, 35.0],
                                [128.001, 35.0],
                                [128.001, 35.001],
                            ],
                        },
                    }
                ],
            },
        },
    }

    result = corner_preview.split_payload_at_corners(payload, min_turn_degrees=30)

    assert result["summary"]["nodeCount"] == 3
    assert result["summary"]["segmentCount"] == 2
    assert result["summary"]["cornerNodeCount"] == 1
    assert {segment["properties"]["sourceEdgeId"] for segment in result["layers"]["roadSegments"]["features"]} == {7}
    assert [
        node["properties"]["cornerRole"] for node in result["layers"]["roadNodes"]["features"]
    ].count("corner") == 1


def test_split_payload_at_corners_keeps_shallow_bend_unsplit() -> None:
    payload = {
        "meta": {"centerLat": 35.0, "centerLon": 128.0},
        "summary": {"nodeCount": 0, "segmentCount": 1, "segmentTypeCounts": []},
        "layers": {
            "roadNodes": {"type": "FeatureCollection", "features": []},
            "roadSegments": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"edgeId": 9, "segmentType": "ROAD_BOUNDARY_INNER"},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [
                                [128.0, 35.0],
                                [128.001, 35.0],
                                [128.002, 35.00005],
                            ],
                        },
                    }
                ],
            },
        },
    }

    result = corner_preview.split_payload_at_corners(payload, min_turn_degrees=30)

    assert result["summary"]["nodeCount"] == 2
    assert result["summary"]["segmentCount"] == 1
    assert result["summary"]["cornerNodeCount"] == 0
