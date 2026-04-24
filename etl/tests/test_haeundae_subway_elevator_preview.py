from __future__ import annotations

from etl.common import haeundae_subway_elevator_preview


def test_render_html_includes_elevator_layer_and_roadview_action() -> None:
    payload = {
        "meta": {
            "title": "Haeundae Subway Elevator Preview",
            "centerLat": 35.1631,
            "centerLon": 129.1635,
            "radiusMeter": 5000,
            "elevatorCsv": "C:/tmp/subway_station_elevators_erd_ready.csv",
            "localhostUrl": "http://127.0.0.1:3000/etl/haeundae_subway_elevator_preview.html",
        },
        "summary": {
            "elevatorCount": 12,
            "skippedNoCoordinate": 1,
            "stationCounts": [
                {"name": "해운대", "count": 4},
                {"name": "중동", "count": 2},
            ],
        },
        "layers": {
            "subwayElevators": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "source": "SUBWAY_ELEVATOR",
                            "elevatorId": "1",
                            "stationId": "201",
                            "stationName": "해운대",
                            "lineName": "2",
                            "entranceNo": "3",
                            "distanceMeter": 123.4,
                        },
                        "geometry": {"type": "Point", "coordinates": [129.1639, 35.1616]},
                    }
                ],
            }
        },
    }

    rendered = haeundae_subway_elevator_preview.render_html(payload)

    assert "Haeundae Subway Elevator Preview" in rendered
    assert "Subway elevator" in rendered
    assert "openRoadviewTab" in rendered
    assert 'window.open(roadviewUrl, "_blank", "noopener,noreferrer")' in rendered
