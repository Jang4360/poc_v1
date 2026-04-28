from __future__ import annotations

import csv
import importlib

from etl.common import segment_graph_db

road_boundary_csv = importlib.import_module("etl.scripts.17_export_road_boundary_csv")


def test_road_boundary_payload_to_csv_graph_creates_endpoint_nodes() -> None:
    payload = {
        "meta": {"centerLat": 35.1, "centerLon": 128.9},
        "layers": {
            "roadSegments": {
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"edgeId": 7, "segmentType": "ROAD_BOUNDARY", "lengthMeter": 10.0},
                        "geometry": {"type": "LineString", "coordinates": [[128.1, 35.1], [128.2, 35.2]]},
                    },
                    {
                        "type": "Feature",
                        "properties": {"edgeId": 8, "segmentType": "ROAD_BOUNDARY_INNER", "lengthMeter": 12.0},
                        "geometry": {"type": "LineString", "coordinates": [[128.2, 35.2], [128.3, 35.3]]},
                    },
                ]
            }
        },
    }

    csv_payload = road_boundary_csv.road_boundary_payload_to_csv_graph(payload, district="강서구")

    assert csv_payload["meta"]["districtGu"] == "강서구"
    assert csv_payload["summary"]["nodeCount"] == 3
    assert csv_payload["summary"]["segmentCount"] == 2
    first_segment = csv_payload["layers"]["roadSegments"]["features"][0]["properties"]
    second_segment = csv_payload["layers"]["roadSegments"]["features"][1]["properties"]
    assert first_segment["fromNodeId"] == 1
    assert first_segment["toNodeId"] == 2
    assert second_segment["fromNodeId"] == 2
    assert second_segment["toNodeId"] == 3


def test_road_boundary_payload_to_csv_graph_keeps_closed_rings() -> None:
    payload = {
        "meta": {"centerLat": 35.1, "centerLon": 128.9},
        "layers": {
            "roadSegments": {
                "features": [
                    {
                        "type": "Feature",
                        "properties": {"edgeId": 1, "segmentType": "ROAD_BOUNDARY", "lengthMeter": 30.0},
                        "geometry": {
                            "type": "LineString",
                            "coordinates": [[128.1, 35.1], [128.2, 35.1], [128.1, 35.1]],
                        },
                    }
                ]
            }
        },
    }

    csv_payload = road_boundary_csv.road_boundary_payload_to_csv_graph(payload, district="강서구")

    assert csv_payload["summary"]["segmentCount"] == 1
    segment = csv_payload["layers"]["roadSegments"]["features"][0]["properties"]
    assert segment["fromNodeId"] != segment["toNodeId"]


def test_main_writes_csv_files(tmp_path) -> None:
    source_geojson = tmp_path / "road_boundary.geojson"
    node_csv = tmp_path / "nodes.csv"
    segment_csv = tmp_path / "segments.csv"
    source_geojson.write_text(
        """
        {
          "meta": {"centerLat": 35.1, "centerLon": 128.9},
          "layers": {
            "roadSegments": {
              "features": [
                {
                  "type": "Feature",
                  "properties": {"edgeId": 1, "segmentType": "ROAD_BOUNDARY", "lengthMeter": 2.5},
                  "geometry": {"type": "LineString", "coordinates": [[128.1, 35.1], [128.2, 35.2]]}
                }
              ]
            }
          }
        }
        """,
        encoding="utf-8",
    )

    exit_code = road_boundary_csv.main_with_args(
        [
            "--source-geojson",
            str(source_geojson),
            "--node-csv",
            str(node_csv),
            "--segment-csv",
            str(segment_csv),
            "--district",
            "강서구",
        ]
    )

    assert exit_code == 0
    with node_csv.open(encoding="utf-8", newline="") as fh:
        assert len(list(csv.DictReader(fh))) == 2
    with segment_csv.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["segmentType"] == "ROAD_BOUNDARY"


def test_csv_payload_infers_gangseo_district(tmp_path) -> None:
    node_csv = tmp_path / "gangseo_road_nodes_v4.csv"
    segment_csv = tmp_path / "gangseo_road_segments_v4.csv"
    node_csv.write_text(
        "vertexId,sourceNodeKey,point\n"
        "1,n1,SRID=4326;POINT(128.1 35.1)\n"
        "2,n2,SRID=4326;POINT(128.2 35.2)\n",
        encoding="utf-8",
    )
    segment_csv.write_text(
        "edgeId,fromNodeId,toNodeId,geom,lengthMeter,walkAccess,avgSlopePercent,widthMeter,"
        "brailleBlockState,audioSignalState,rampState,widthState,surfaceState,stairsState,"
        "elevatorState,crossingState,segmentType\n"
        '1,1,2,"SRID=4326;LINESTRING(128.1 35.1, 128.2 35.2)",10.00,UNKNOWN,,,'
        "UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,ROAD_BOUNDARY\n",
        encoding="utf-8",
    )

    payload = segment_graph_db.build_csv_payload(node_csv=node_csv, segment_csv=segment_csv)

    assert payload["meta"]["districtGu"] == "강서구"
    assert payload["meta"]["title"].startswith("강서구")
    assert payload["meta"]["centerLon"] == 128.15
    assert payload["meta"]["bbox"]["minLon"] == 128.1
