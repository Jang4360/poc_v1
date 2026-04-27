from __future__ import annotations

from etl.common import segment_centerline_02c, segment_graph_edit_ui


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
    assert "saveJsonDocument" in rendered
    assert "localStorage" in rendered
