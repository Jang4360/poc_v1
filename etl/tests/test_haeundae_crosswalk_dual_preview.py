from __future__ import annotations

from etl.common import haeundae_crosswalk_dual_preview


def test_render_html_includes_both_marker_layers_and_roadview_action() -> None:
    payload = {
        "meta": {
            "title": "Haeundae Crosswalk Dual Preview",
            "centerLat": 35.1631,
            "centerLon": 129.1635,
            "radiusMeter": 5000,
            "tmapCsv": "C:/tmp/tmap.csv",
            "busanCsv": "C:/tmp/busan.csv",
            "localhostUrl": "http://127.0.0.1:3000/etl/haeundae_crosswalk_dual_preview.html",
        },
        "summary": {
            "tmapCount": 10,
            "busanCount": 20,
            "tmapSkippedNoCoordinate": 1,
            "busanSkippedNoCoordinate": 2,
        },
        "layers": {
            "tmapCrosswalks": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "source": "TMAP",
                            "observationCount": 2,
                            "turnTypeNamesKo": "우측 횡단보도",
                            "sampleDescription": "예시",
                            "distanceMeter": 111.1,
                        },
                        "geometry": {"type": "Point", "coordinates": [129.1639, 35.1616]},
                    }
                ],
            },
            "busanCrosswalks": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "source": "BUSAN_OPEN_DATA",
                            "seq": "1",
                            "gu": "해운대구",
                            "dong": "중동",
                            "intersection": "동성장여관",
                            "distanceMeter": 123.4,
                        },
                        "geometry": {"type": "Point", "coordinates": [129.1653, 35.1623]},
                    }
                ],
            },
        },
    }

    rendered = haeundae_crosswalk_dual_preview.render_html(payload)

    assert "Haeundae Crosswalk Dual Preview" in rendered
    assert "Tmap crosswalk (blue)" in rendered
    assert "Busan open data crosswalk (orange)" in rendered
    assert "openRoadviewTab" in rendered
    assert 'window.open(roadviewUrl, "_blank", "noopener,noreferrer")' in rendered
