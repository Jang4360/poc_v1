from __future__ import annotations

from etl.common import subway_elevator_preview


def test_render_html_includes_side_graph_layers_and_kakao_link_action() -> None:
    payload = {
        "meta": {
            "title": "Haeundae 5km Side Graph Preview",
            "centerLat": 35.1796,
            "centerLon": 129.0756,
            "radiusMeter": 5000,
            "sourceShp": "C:/tmp/N3L_A0020000_26.shp",
            "localhostUrl": "http://127.0.0.1:3000/etl/subway_elevator_preview.html",
        },
        "summary": {
            "nodeCount": 23,
            "segmentCount": 40,
            "transitionConnectorCount": 2,
            "gapBridgeCount": 1,
            "cornerBridgeCount": 1,
            "crossingCount": 3,
            "elevatorConnectorCount": 1,
            "segmentTypeCounts": [
                {"name": "CENTERLINE", "count": 5},
                {"name": "SIDE_LEFT", "count": 10},
            ],
        },
        "layers": {
            "roadNodes": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"vertexId": 1, "nodeType": "LANE_TRANSITION", "degree": 3},
                        "geometry": {"type": "Point", "coordinates": [129.121, 35.18]},
                    }
                ],
            },
            "roadSegments": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"edgeId": 9, "segmentType": "SIDE_LEFT", "lengthMeter": 7.0},
                        "geometry": {"type": "LineString", "coordinates": [[129.121, 35.18], [129.122, 35.181]]},
                    }
                ],
            },
        },
    }

    rendered = subway_elevator_preview.render_html(payload)

    assert "Haeundae 5km Side Graph Preview" in rendered
    assert "road node" in rendered
    assert "centerline segment" in rendered
    assert "payload.layers.roadSegments.features" in rendered
    assert "payload.layers.roadNodes.features" in rendered
    assert "transition connector" in rendered
    assert "gap bridge" in rendered
    assert "corner bridge" in rendered
    assert "autoload=false" in rendered
    assert "kakao.maps.load(initializeMap)" in rendered
