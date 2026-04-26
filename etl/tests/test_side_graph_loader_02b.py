from __future__ import annotations

from etl.common.side_graph_loader_02b import (
    BaseLine,
    IntersectionSector,
    JunctionAnchorPlan,
    apply_junction_anchor_snap,
    build_gap_bridges,
    reconcile_post_bridge_pockets,
)


def _single_sector() -> dict[int, list[IntersectionSector]]:
    return {
        1: [
            IntersectionSector(
                root=1,
                sector_index=0,
                start_angle_rad=0.0,
                end_angle_rad=1.57079632679,
                bisector_angle_rad=0.78539816339,
            )
        ]
    }


def test_anchor_snap_collapses_compact_single_node_junction_endpoints() -> None:
    lines = [
        BaseLine("left:a", "SIDE_LEFT", 1, ((1.0, 0.0), (20.0, 0.0)), 8.0),
        BaseLine("right:b", "SIDE_RIGHT", 2, ((1.2, 0.1), (20.0, 0.1)), 8.0),
    ]

    anchored, stats, plans, suppressed_points, closed_roots = apply_junction_anchor_snap(
        lines,
        {1: (0.0, 0.0)},
        {1: 5.0},
        _single_sector(),
    )

    assert stats["junctionArchetypeCounts"] == {"single-node": 1}
    assert stats["anchorSnappedEndpointCount"] == 2
    assert plans[1].single_anchor is not None
    assert closed_roots == {1}
    assert suppressed_points
    assert anchored[0].coords[0] == anchored[1].coords[0]


def test_gap_bridge_is_suppressed_for_claimed_junction_endpoint() -> None:
    lines = [
        BaseLine("left:a", "SIDE_LEFT", 1, ((0.0, 0.0), (5.0, 0.0)), 8.0),
        BaseLine("left:b", "SIDE_LEFT", 2, ((7.0, 0.0), (12.0, 0.0)), 8.0),
    ]

    connectors, events, stats = build_gap_bridges(
        lines,
        suppressed_endpoint_points={(5.0, 0.0)},
    )

    assert connectors == []
    assert events == []
    assert stats["bridgeSuppressedByClaimCount"] >= 1


def test_post_bridge_reconciliation_drops_duplicate_gap_when_cross_bridge_exists() -> None:
    segments = [
        ("CROSS_SIDE_CORNER_BRIDGE", ((1.0, 0.0), (2.0, 0.0))),
        ("GAP_BRIDGE", ((1.0, 0.0), (2.0, 0.0))),
        ("SIDE_LEFT", ((1.0, 0.0), (6.0, 0.0))),
    ]
    cleaned, stats = reconcile_post_bridge_pockets(
        segments,
        {1: (0.0, 0.0)},
        {1},
        {1: 5.0},
        _single_sector(),
        {
            1: JunctionAnchorPlan(
                root=1,
                archetype="multi-corner-complex",
                anchors_by_sector={0: (100.0, 100.0)},
            )
        },
    )

    assert stats["duplicateBridgeSuppressedCount"] >= 1
    assert stats["crossSideGapDuplicatePocketCount"] == 1
    assert [segment_type for segment_type, _ in cleaned].count("GAP_BRIDGE") == 0
