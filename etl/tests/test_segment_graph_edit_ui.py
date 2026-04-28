from __future__ import annotations

from etl.common import segment_centerline_02c, segment_graph_candidate_review_ui, segment_graph_edit_ui


def test_graph_edit_ui_contains_manual_edit_controls() -> None:
    payload = segment_centerline_02c.build_graph_materialized_payload(radius_m=250)
    payload["meta"]["title"] = "Edit UI Test"

    rendered = segment_graph_edit_ui.render_html(payload)

    assert "mode-delete" in rendered
    assert "mode-add" in rendered
    assert "manual_edits" in rendered
    assert "delete_segment" in rendered
    assert "add_segment" in rendered
    assert "fromNodeId" in rendered
    assert "toNodeId" in rendered
    assert "Save JSON" in rendered
    assert "Update CSV" in rendered
    assert "Reset" in rendered
    assert "Save JSON + CSV" not in rendered
    assert "segment_02c_manual_edits.json" in rendered


def test_write_graph_edit_outputs_writes_html_only(tmp_path) -> None:
    output_html = tmp_path / "segment_02c_graph_edit.html"

    payload = segment_centerline_02c.write_graph_edit_outputs(
        output_html=output_html,
        radius_m=250,
    )

    assert output_html.exists()
    assert payload["meta"]["stage"] == "02c-step2g-manual-edit-ui"
    rendered = output_html.read_text(encoding="utf-8")
    assert "Reload bbox" in rendered
    assert "updateCsv" in rendered
    assert "renderAllFeaturesAndFit" in rendered
    assert "map.setBounds(bounds)" in rendered
    assert "saveJsonDocument" in rendered
    assert "localStorage" in rendered


def test_candidate_diff_preview_highlights_edit_actions() -> None:
    rendered = segment_graph_candidate_review_ui.render_diff_html(
        {
            "meta": {
                "candidateCounts": {"delete_segment": 1, "add_segment": 1, "total": 2},
                "motifCounts": {"delete_short_dangling_tail": 1, "add_side_gap_bridge": 1},
            },
            "context": {
                "roadSegments": {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {"edgeId": 1, "segmentType": "SIDE_LINE"},
                            "geometry": {"type": "LineString", "coordinates": [[128.1, 35.1], [128.2, 35.2]]},
                        }
                    ],
                }
            },
            "edits": [
                {
                    "action": "delete_segment",
                    "motif": "delete_short_dangling_tail",
                    "geom": {"type": "LineString", "coordinates": [[128.1, 35.1], [128.2, 35.2]]},
                },
                {
                    "action": "add_segment",
                    "motif": "add_side_gap_bridge",
                    "geom": {"type": "LineString", "coordinates": [[128.2, 35.2], [128.3, 35.3]]},
                },
            ],
        }
    )

    assert "delete candidate" in rendered
    assert "add candidate" in rendered
    assert "map.setBounds(bounds)" in rendered
