from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from etl.common import segment_graph_auto_edit


SEGMENT_HEADER = (
    "edgeId,fromNodeId,toNodeId,geom,lengthMeter,walkAccess,avgSlopePercent,widthMeter,"
    "brailleBlockState,audioSignalState,rampState,widthState,surfaceState,stairsState,"
    "elevatorState,crossingState,segmentType"
)


def write_fixture_csvs(tmp_path: Path) -> tuple[Path, Path]:
    node_csv = tmp_path / "gangseo_road_nodes.csv"
    segment_csv = tmp_path / "gangseo_road_segments.csv"
    node_csv.write_text(
        "\n".join(
            [
                "vertexId,sourceNodeKey,point",
                "1,training-a,SRID=4326;POINT(128.8500 35.0900)",
                "2,training-b,SRID=4326;POINT(128.8501 35.0901)",
                "3,hub,SRID=4326;POINT(128.9500 35.1500)",
                "4,dangling,SRID=4326;POINT(128.9501 35.1500)",
                "5,near-a,SRID=4326;POINT(128.9510 35.1500)",
                "6,near-b,SRID=4326;POINT(128.9512 35.1500)",
                "7,far-a,SRID=4326;POINT(128.9600 35.1600)",
                "8,cross-a,SRID=4326;POINT(128.8300 35.0900)",
                "9,cross-b,SRID=4326;POINT(128.8700 35.0900)",
                "10,outside-gen-a,SRID=4326;POINT(128.9000 35.1400)",
                "11,outside-gen-b,SRID=4326;POINT(128.9001 35.1400)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    segment_csv.write_text(
        "\n".join(
            [
                SEGMENT_HEADER,
                '10,1,2,"SRID=4326;LINESTRING(128.8500 35.0900, 128.8501 35.0901)",15.00,UNKNOWN,,,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,SIDE_LEFT',
                '19,10,11,"SRID=4326;LINESTRING(128.9000 35.1400, 128.9001 35.1400)",8.00,UNKNOWN,,,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,SIDE_LINE',
                '20,3,4,"SRID=4326;LINESTRING(128.9500 35.1500, 128.9501 35.1500)",9.00,UNKNOWN,,,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,SIDE_LINE',
                '21,3,5,"SRID=4326;LINESTRING(128.9500 35.1500, 128.9510 35.1500)",90.00,UNKNOWN,,,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,SIDE_LINE',
                '22,6,7,"SRID=4326;LINESTRING(128.9512 35.1500, 128.9600 35.1600)",900.00,UNKNOWN,,,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,SIDE_LINE',
                '30,8,9,"SRID=4326;LINESTRING(128.8300 35.0900, 128.8700 35.0900)",9.00,UNKNOWN,,,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,UNKNOWN,SIDE_LINE',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return node_csv, segment_csv


def test_build_training_dataset_and_profile(tmp_path: Path):
    manual_edits = tmp_path / "manual_edits.json"
    manual_edits.write_text(
        json.dumps(
            {
                "edits": [
                    {
                        "action": "delete_segment",
                        "segmentType": "SIDE_RIGHT",
                        "edgeId": 10,
                        "geom": {
                            "type": "LineString",
                            "coordinates": [[128.85, 35.09], [128.8501, 35.0901]],
                        },
                    },
                    {
                        "action": "add_segment",
                        "segmentType": "SIDE_WALK",
                        "geom": {
                            "type": "LineString",
                            "coordinates": [[128.85, 35.09], [128.8502, 35.09]],
                        },
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    dataset = segment_graph_auto_edit.build_training_dataset(manual_edits=manual_edits, training_bbox=None)
    profile = segment_graph_auto_edit.learn_profile(dataset)

    assert dataset["summary"]["actionCounts"] == {"add_segment": 1, "delete_segment": 1}
    assert dataset["summary"]["segmentTypeCounts"]["SIDE_LINE"] == 1
    assert dataset["summary"]["motifCounts"]["delete_short_dangling_tail"] == 1
    assert dataset["examples"][0]["beforeAfterPatch"]["hasGeometry"] is True
    assert profile["learnedAddSegmentType"] == "SIDE_WALK"
    assert profile["learnedMotifCounts"]["add_outline_or_corner_connector"] == 1
    assert profile["policy"]["mode"] == "review_required"


def test_generate_candidate_edits_excludes_training_bbox(tmp_path: Path):
    node_csv, segment_csv = write_fixture_csvs(tmp_path)
    profile = {
        "trainingBbox": {"minLon": 128.84, "minLat": 35.08, "maxLon": 128.86, "maxLat": 35.10},
        "thresholds": {
            "danglingDeleteMaxMeter": 20.0,
            "gapAddMinMeter": 5.0,
            "gapAddMaxMeter": 30.0,
        },
        "learnedAddSegmentType": "SIDE_LINE",
    }

    candidates = segment_graph_auto_edit.generate_candidate_edits(
        node_csv=node_csv,
        segment_csv=segment_csv,
        profile=profile,
        output_add_segment_type="SIDE_WALK",
        max_delete_candidates=10,
        max_add_candidates=10,
    )

    delete_ids = {
        edit["edgeId"]
        for edit in candidates["edits"]
        if edit["action"] == "delete_segment"
    }
    add_types = {
        edit["segmentType"]
        for edit in candidates["edits"]
        if edit["action"] == "add_segment"
    }

    assert 10 not in delete_ids
    assert 20 in delete_ids
    assert 30 not in delete_ids
    assert "SIDE_WALK" in add_types
    assert all(
        {edit["fromNode"]["vertexId"], edit["toNode"]["vertexId"]} != {4, 5}
        for edit in candidates["edits"]
        if edit["action"] == "add_segment"
    )
    assert candidates["meta"]["reviewRequired"] is True
    assert candidates["meta"]["motifCounts"]
    assert all("reviewId" in edit for edit in candidates["edits"])
    assert all("motif" in edit for edit in candidates["edits"])
    assert all("evidence" in edit for edit in candidates["edits"])
    assert all(edit["review"]["approved"] is False for edit in candidates["edits"])
    assert candidates["meta"]["candidateCounts"]["total"] == len(candidates["edits"])


def test_generation_bbox_filters_before_candidate_caps(tmp_path: Path):
    node_csv, segment_csv = write_fixture_csvs(tmp_path)
    profile = {
        "trainingBbox": {"minLon": 128.84, "minLat": 35.08, "maxLon": 128.86, "maxLat": 35.10},
        "thresholds": {
            "danglingDeleteMaxMeter": 20.0,
            "gapAddMinMeter": 5.0,
            "gapAddMaxMeter": 30.0,
        },
        "learnedAddSegmentType": "SIDE_LINE",
    }

    candidates = segment_graph_auto_edit.generate_candidate_edits(
        node_csv=node_csv,
        segment_csv=segment_csv,
        profile=profile,
        output_add_segment_type="SIDE_LINE",
        max_delete_candidates=1,
        max_add_candidates=0,
        generation_bbox=(128.949, 35.149, 128.952, 35.151),
    )

    delete_ids = [edit["edgeId"] for edit in candidates["edits"] if edit["action"] == "delete_segment"]
    assert delete_ids == [20]
    assert candidates["meta"]["generationBbox"] == {
        "minLon": 128.949,
        "minLat": 35.149,
        "maxLon": 128.952,
        "maxLat": 35.151,
    }


def test_write_auto_edit_outputs_writes_review_artifacts(tmp_path: Path):
    node_csv, segment_csv = write_fixture_csvs(tmp_path)
    manual_edits = tmp_path / "manual_edits.json"
    manual_edits.write_text(
        json.dumps(
            {
                "edits": [
                    {
                        "action": "delete_segment",
                        "edgeId": 10,
                        "segmentType": "SIDE_LINE",
                        "geom": {
                            "type": "LineString",
                            "coordinates": [[128.85, 35.09], [128.8501, 35.0901]],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    report = segment_graph_auto_edit.write_auto_edit_outputs(
        manual_edits=manual_edits,
        node_csv=node_csv,
        segment_csv=segment_csv,
        output_dir=tmp_path / "out",
        training_bbox=(128.84, 35.08, 128.86, 35.10),
        max_delete_candidates=5,
        max_add_candidates=5,
    )

    candidate_path = Path(report["candidates"])
    candidates = json.loads(candidate_path.read_text(encoding="utf-8"))
    assert candidate_path.exists()
    assert Path(report["trainingData"]).exists()
    assert Path(report["profile"]).exists()
    assert Path(report["reviewHtml"]).exists()
    assert Path(report["diffPreviewHtml"]).exists()
    assert candidates["meta"]["doNotApplyWithoutHumanApproval"] is True


def test_approved_review_document_keeps_only_approved_edits():
    reviewed = {
        "sourceHtml": "review.html",
        "sourceGeojson": "review.geojson",
        "meta": {},
        "edits": [
            {"action": "delete_segment", "reviewId": "delete_segment:1", "review": {"approved": True}},
            {"action": "delete_segment", "reviewId": "delete_segment:2", "review": {"approved": False}},
        ],
    }

    approved = segment_graph_auto_edit.approved_review_document(reviewed)

    assert approved["version"] == "02c_auto_edit_approved_manual_edits"
    assert len(approved["edits"]) == 1
    assert approved["meta"]["reviewCounts"] == {"approved": 1, "pending": 1, "total": 2}


def test_apply_and_render_rejects_unapproved_auto_candidates(tmp_path: Path):
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "15_serve_segment_02c_editor.py"
    spec = importlib.util.spec_from_file_location("serve_segment_02c_editor", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    try:
        module.apply_and_render(
            edit_document={
                "meta": {
                    "doNotApplyWithoutHumanApproval": True,
                    "approvedOnly": False,
                },
                "edits": [{"action": "delete_segment", "edgeId": 1}],
            },
            node_csv=tmp_path / "missing_nodes.csv",
            segment_csv=tmp_path / "missing_segments.csv",
            output_html=tmp_path / "out.html",
            output_geojson=tmp_path / "out.geojson",
            bbox=(0, 0, 1, 1),
        )
    except ValueError as exc:
        assert "cannot be applied before human approval" in str(exc)
    else:
        raise AssertionError("unapproved auto candidates should be rejected")
