from __future__ import annotations

from pathlib import Path

from etl.common import segment_graph_db


def test_ewkt_to_geometry_parses_point():
    assert segment_graph_db.ewkt_to_geometry("SRID=4326;POINT(128.1 35.2)") == {
        "type": "Point",
        "coordinates": [128.1, 35.2],
    }


def test_ewkt_to_geometry_parses_linestring():
    assert segment_graph_db.ewkt_to_geometry("SRID=4326;LINESTRING(128.1 35.2, 128.3 35.4)") == {
        "type": "LineString",
        "coordinates": [[128.1, 35.2], [128.3, 35.4]],
    }


def test_normalize_segment_type_collapses_side_aliases():
    assert segment_graph_db.normalize_segment_type("SIDE_LEFT") == "SIDE_LINE"
    assert segment_graph_db.normalize_segment_type("SIDE_RIGHT") == "SIDE_LINE"
    assert segment_graph_db.normalize_segment_type("SIDE_WALK") == "SIDE_WALK"


def test_build_csv_payload_filters_to_bbox(tmp_path: Path):
    node_csv = tmp_path / "road_nodes.csv"
    segment_csv = tmp_path / "road_segments.csv"
    node_csv.write_text(
        "\n".join(
            [
                "vertexId,sourceNodeKey,point",
                "1,a,SRID=4326;POINT(128.85 35.09)",
                "2,b,SRID=4326;POINT(128.86 35.10)",
                "3,c,SRID=4326;POINT(129.10 35.50)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    segment_csv.write_text(
        "\n".join(
            [
                "edgeId,fromNodeId,toNodeId,geom,lengthMeter,walkAccess,avgSlopePercent,widthMeter,brailleBlockState,audioSignalState,rampState,widthState,surfaceState,stairsState,elevatorState,crossingState,segmentType",
                '10,1,2,"SRID=4326;LINESTRING(128.85 35.09, 128.86 35.10)",5.00,UNKNOWN,,,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,SIDE_LEFT',
                '11,2,3,"SRID=4326;LINESTRING(129.00 35.40, 129.10 35.50)",6.00,UNKNOWN,,,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,SIDE_RIGHT',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = segment_graph_db.build_csv_payload(
        node_csv=node_csv,
        segment_csv=segment_csv,
        bbox=(128.8, 35.0, 128.9, 35.2),
    )

    assert payload["summary"]["nodeCount"] == 2
    assert payload["summary"]["segmentCount"] == 1
    assert payload["meta"]["centerLon"] == 128.85
    assert payload["meta"]["centerLat"] == 35.1
    segment = payload["layers"]["roadSegments"]["features"][0]
    assert segment["properties"]["edgeId"] == 10
    assert segment["properties"]["segmentType"] == "SIDE_LINE"


def test_apply_manual_edits_resolves_temp_existing_node_refs():
    payload = {
        "meta": {"title": "test"},
        "summary": {"nodeCount": 0, "segmentCount": 0, "segmentTypeCounts": []},
        "layers": {
            "roadNodes": {"type": "FeatureCollection", "features": []},
            "roadSegments": {"type": "FeatureCollection", "features": []},
        },
    }
    edit_document = {
        "edits": [
            {
                "action": "add_node",
                "geom": {"type": "Point", "coordinates": [128.1, 35.1]},
                "sourceNodeKey": "manual_node:128.10000000:35.10000000",
            },
            {
                "action": "add_segment",
                "segmentType": "SIDE_LEFT",
                "fromNode": {
                    "mode": "existing",
                    "vertexId": "manual_node:128.10000000:35.10000000",
                    "sourceNodeKey": "manual_node:128.10000000:35.10000000",
                    "geom": {"type": "Point", "coordinates": [128.1, 35.1]},
                },
                "toNode": {
                    "mode": "new",
                    "sourceNodeKey": "manual_node:128.2:35.2",
                    "geom": {"type": "Point", "coordinates": [128.2, 35.2]},
                },
                "geom": {"type": "LineString", "coordinates": [[128.1, 35.1], [128.2, 35.2]]},
            },
        ]
    }

    patched = segment_graph_db.apply_manual_edits(payload, edit_document)

    assert patched["summary"]["nodeCount"] == 2
    assert patched["summary"]["segmentCount"] == 1
    assert patched["layers"]["roadSegments"]["features"][0]["properties"]["segmentType"] == "SIDE_LINE"


def test_apply_csv_manual_edits_updates_csv_files(tmp_path: Path):
    node_csv = tmp_path / "road_nodes.csv"
    segment_csv = tmp_path / "road_segments.csv"
    edits_json = tmp_path / "edits.json"
    node_csv.write_text(
        "\n".join(
            [
                "vertexId,sourceNodeKey,point",
                "1,a,SRID=4326;POINT(128.1 35.1)",
                "2,b,SRID=4326;POINT(128.2 35.2)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    segment_csv.write_text(
        "\n".join(
            [
                "edgeId,fromNodeId,toNodeId,geom,lengthMeter,walkAccess,avgSlopePercent,widthMeter,brailleBlockState,audioSignalState,rampState,widthState,surfaceState,stairsState,elevatorState,crossingState,segmentType",
                '10,1,2,"SRID=4326;LINESTRING(128.1 35.1, 128.2 35.2)",5.00,UNKNOWN,,,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,SIDE_LEFT',
                '11,2,1,"SRID=4326;LINESTRING(128.2 35.2, 128.1 35.1)",5.00,UNKNOWN,,,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,SIDE_RIGHT',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    edits_json.write_text(
        '{"edits":[{"action":"delete_segment","edgeId":10}]}',
        encoding="utf-8",
    )

    report = segment_graph_db.apply_csv_manual_edits(
        node_csv=node_csv,
        segment_csv=segment_csv,
        manual_edits=edits_json,
    )

    assert report["segmentCount"] == 1
    assert "10,1,2" not in segment_csv.read_text(encoding="utf-8")
    assert "SIDE_RIGHT" not in segment_csv.read_text(encoding="utf-8")
    assert "SIDE_LINE" in segment_csv.read_text(encoding="utf-8")


def test_apply_csv_edit_document_updates_csv_files(tmp_path: Path):
    node_csv = tmp_path / "road_nodes.csv"
    segment_csv = tmp_path / "road_segments.csv"
    node_csv.write_text(
        "\n".join(
            [
                "vertexId,sourceNodeKey,point",
                "1,a,SRID=4326;POINT(128.1 35.1)",
                "2,b,SRID=4326;POINT(128.2 35.2)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    segment_csv.write_text(
        "\n".join(
            [
                "edgeId,fromNodeId,toNodeId,geom,lengthMeter,walkAccess,avgSlopePercent,widthMeter,brailleBlockState,audioSignalState,rampState,widthState,surfaceState,stairsState,elevatorState,crossingState,segmentType",
                '10,1,2,"SRID=4326;LINESTRING(128.1 35.1, 128.2 35.2)",5.00,UNKNOWN,,,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,SIDE_LINE',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    report = segment_graph_db.apply_csv_edit_document(
        node_csv=node_csv,
        segment_csv=segment_csv,
        edit_document={
            "edits": [
                {
                    "action": "add_segment",
                    "segmentType": "SIDE_WALK",
                    "fromNode": {"mode": "existing", "vertexId": 1},
                    "toNode": {"mode": "existing", "vertexId": 2},
                    "geom": {"type": "LineString", "coordinates": [[128.1, 35.1], [128.2, 35.2]]},
                }
            ]
        },
    )

    assert report["segmentCount"] == 2
    assert "SIDE_WALK" in segment_csv.read_text(encoding="utf-8")
