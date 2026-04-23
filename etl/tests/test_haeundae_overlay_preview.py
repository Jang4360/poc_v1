from __future__ import annotations

from etl.common import haeundae_overlay_preview


def test_feature_styles_cover_expected_accessibility_layers() -> None:
    expected = {
        "AUDIO_SIGNAL",
        "CROSSWALK",
        "SUBWAY_ELEVATOR",
        "WIDTH",
        "SURFACE",
        "SLOPE_ANALYSIS",
        "STAIRS",
    }
    assert expected.issubset(haeundae_overlay_preview.FEATURE_STYLES.keys())


def test_render_html_includes_expected_layers_and_summary() -> None:
    payload = {
        "meta": {
            "title": "Haeundae Accessibility Overlay Preview",
            "centerLat": 35.1631,
            "centerLon": 129.1635,
            "radiusMeter": 5000,
        },
        "summary": {
            "roadSegments": 2,
            "roadNodes": 3,
            "featureCounts": {"WIDTH": 1, "SLOPE_ANALYSIS": 1},
        },
        "layers": {
            "roadSegments": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"edgeId": 1},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[129.16, 35.16], [129.17, 35.17]],
                        },
                    }
                ],
            },
            "roadNodes": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"vertexId": 10},
                        "geometry": {"type": "Point", "coordinates": [129.16, 35.16]},
                    }
                ],
            },
            "segmentFeatures": {
                "WIDTH": {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {"featureType": "WIDTH"},
                            "geometry": {
                                "type": "LineString",
                                "coordinates": [[129.16, 35.16], [129.165, 35.165]],
                            },
                        }
                    ],
                },
                "SLOPE_ANALYSIS": {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {"featureType": "SLOPE_ANALYSIS"},
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [
                                    [
                                        [129.16, 35.16],
                                        [129.161, 35.16],
                                        [129.161, 35.161],
                                        [129.16, 35.161],
                                        [129.16, 35.16],
                                    ]
                                ],
                            },
                        }
                    ],
                },
            },
        },
    }

    rendered = haeundae_overlay_preview.render_html(payload)

    assert "Haeundae Accessibility Overlay Preview" in rendered
    assert "roadSegments" in rendered
    assert "roadNodes" in rendered
    assert "WIDTH" in rendered
    assert "SLOPE_ANALYSIS" in rendered
    assert "featureCounts" in rendered
