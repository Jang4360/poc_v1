from __future__ import annotations

from etl.common import haeundae_audio_signal_preview


def test_render_html_includes_kakao_polygon_and_new_tab_roadview_bits() -> None:
    payload = {
        "meta": {
            "title": "Haeundae Audio Signal Polygon Preview",
            "centerLat": 35.1631,
            "centerLon": 129.1635,
            "radiusMeter": 5000,
            "apiBaseUrl": "https://apis.data.go.kr/6260000/BusanAcstcBcnInfoService",
            "localhostUrl": "http://127.0.0.1:3000/etl/haeundae_audio_signal_preview.html",
        },
        "summary": {
            "totalFetched": 25,
            "audioSignalCandidates": 7,
            "audioSignalsMatched": 3,
            "filterPolygons": 10,
            "matchedPolygons": 2,
            "skippedNoCoordinate": 1,
            "districtCounts": [
                {"name": "해운대구", "count": 5},
                {"name": "수영구", "count": 2},
            ],
        },
        "layers": {
            "filterPolygons": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"edgeId": 1, "matchedAudioSignalCount": 0},
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
            "matchedPolygons": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"edgeId": 2, "matchedAudioSignalCount": 1},
                        "geometry": {
                            "type": "Polygon",
                            "coordinates": [
                                [
                                    [129.162, 35.162],
                                    [129.163, 35.162],
                                    [129.163, 35.163],
                                    [129.162, 35.163],
                                    [129.162, 35.162],
                                ]
                            ],
                        },
                    }
                ],
            },
            "audioSignals": {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "properties": {
                            "seq": "1",
                            "sigungu": "해운대구",
                            "location": "예시 위치",
                            "address": "부산광역시 해운대구",
                            "place": "제어기",
                            "stat": "정상동작",
                            "status": "",
                            "insCompany": "예시업체",
                            "insYear": "20-Jan",
                            "confirmDate": "2020-12-31",
                            "distanceMeter": 123.4,
                            "matchedPolygonCount": 1,
                            "matchedEdgeIds": [2],
                        },
                        "geometry": {"type": "Point", "coordinates": [129.1639, 35.1616]},
                    }
                ],
            },
        },
    }

    rendered = haeundae_audio_signal_preview.render_html(payload)

    assert "Haeundae Audio Signal Polygon Preview" in rendered
    assert "Districts: 해운대구 5, 수영구 2" in rendered
    assert "Polygons containing audio signals" in rendered
    assert "openRoadviewTab" in rendered
    assert "window.open(roadviewUrl, \"_blank\", \"noopener,noreferrer\")" in rendered
    assert "새 탭에서 카카오맵 로드뷰 열기" in rendered
