from __future__ import annotations

from etl.common import segment_centerline_02c, segment_graph_candidate_review_ui, segment_graph_db, segment_graph_edit_ui


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
    assert "Edit CSV" in rendered
    assert "Clear" in rendered
    assert "box-delete-drag" in rendered
    assert "box-delete-apply" in rendered
    assert "Delete all" in rendered
    assert "Drag" in rendered
    assert "drawSelectionPolygon" in rendered
    assert "deleteFeaturesInSelectionPolygon" in rendered
    assert "manual_polygon_delete" in rendered
    assert "pointInPolygon" in rendered
    assert "4/4 points selected" in rendered
    assert "Click exactly 4 polygon points first" in rendered
    assert "district-select" in rendered
    assert "switchDistrict" in rendered
    assert '<option value="SIDE_LINE">SIDE_LINE</option>' in rendered
    assert '<option value="SIDE_WALK">SIDE_WALK</option>' in rendered
    assert '<option value="ROAD_BOUNDARY">ROAD_BOUNDARY</option>' not in rendered
    assert '<option value="ROAD_BOUNDARY_INNER">ROAD_BOUNDARY_INNER</option>' not in rendered
    assert 'const addableSegmentTypes = ["SIDE_LINE", "SIDE_WALK"];' in rendered
    assert "Save JSON + CSV" not in rendered
    assert "segment_02c_manual_edits.json" in rendered
    assert "maxInteractiveSegmentOverlays" in rendered
    assert "renderAllFeaturesAndFit" in rendered
    assert "scheduleRenderVisible" in rendered
    assert "editPreviewLimit" in rendered
    assert "full JSON is generated only when needed" in rendered


def test_graph_edit_ui_supports_lazy_dong_payloads() -> None:
    payload = segment_centerline_02c.build_graph_materialized_payload(radius_m=250)
    payload["meta"]["title"] = "Lazy Edit UI Test"

    rendered = segment_graph_edit_ui.render_html(
        payload,
        lazy_payload_endpoint="/api/segment-02c/payload",
        dong_areas=segment_graph_db.GANGSEO_DONG_AREAS,
        default_dong_id="sinho",
    )

    assert 'const districtPayloads = {};' in rendered
    assert 'const lazyPayloadEndpoint = "/api/segment-02c/payload";' in rendered
    assert '"id": "sinho"' in rendered
    assert "신호동" in rendered
    assert 'aria-label="동 선택"' in rendered
    assert "loadPayloadForArea" in rendered


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
