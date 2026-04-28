from __future__ import annotations

import importlib

district_boundary = importlib.import_module("etl.scripts.18_generate_district_road_boundary_from_polygons")


def test_build_boundary_payload_unions_prepared_polygons() -> None:
    collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [128.0, 35.0],
                            [128.001, 35.0],
                            [128.001, 35.001],
                            [128.0, 35.001],
                            [128.0, 35.0],
                        ]
                    ],
                },
                "properties": {},
            }
        ],
    }

    payload = district_boundary.build_boundary_payload(
        collection=collection,
        district="강서구",
        source_js="road-polygons-gangseo-data.js",
    )

    assert payload["meta"]["stage"] == "road-boundary-buffer-union"
    assert payload["summary"]["nodeCount"] == 0
    assert payload["summary"]["segmentCount"] >= 1
    assert payload["layers"]["roadNodes"]["features"] == []
