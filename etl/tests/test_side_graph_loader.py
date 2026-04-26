from __future__ import annotations

from shapely.geometry import Point

from etl.common.side_graph_loader import (
    BaseLine,
    Chain,
    EventPoint,
    IntersectionSector,
    SINGLE_LANE_THRESHOLD_M,
    SourceSegment,
    TransitionSite,
    build_cross_side_corner_bridges,
    build_gap_bridges,
    build_intersection_sectors,
    build_same_side_corner_bridges,
    build_transition_connectors,
    cleanup_junction_pockets,
    consolidate_junction_candidates,
    resolve_cross_type_intersections,
    split_base_lines,
    trim_centerline_for_transition,
    trim_side_line_tails,
    TempSegment,
)


def test_source_segment_classification_uses_lane_count_or_width_threshold() -> None:
    narrow_by_lane = SourceSegment(
        source_row_number=1,
        source_ufid="A",
        road_width_meter=10.0,
        lane_count=1,
        one_way=None,
        coords=((0.0, 0.0), (5.0, 0.0)),
    )
    narrow_by_width = SourceSegment(
        source_row_number=2,
        source_ufid="B",
        road_width_meter=SINGLE_LANE_THRESHOLD_M - 0.1,
        lane_count=2,
        one_way=None,
        coords=((0.0, 0.0), (5.0, 0.0)),
    )
    multi_lane = SourceSegment(
        source_row_number=3,
        source_ufid="C",
        road_width_meter=SINGLE_LANE_THRESHOLD_M + 1.0,
        lane_count=2,
        one_way=None,
        coords=((0.0, 0.0), (5.0, 0.0)),
    )

    assert narrow_by_lane.classification == "CENTERLINE"
    assert narrow_by_width.classification == "CENTERLINE"
    assert multi_lane.classification == "MULTI_LANE"


def test_build_transition_connectors_links_centerline_to_single_best_side_line() -> None:
    base_lines = [
        BaseLine(
            line_id="chain:2:SIDE_LEFT:1",
            segment_type="SIDE_LEFT",
            chain_id=2,
            coords=((-3.0, 0.0), (-3.0, 10.0)),
            road_width_meter=8.0,
        ),
        BaseLine(
            line_id="chain:2:SIDE_RIGHT:1",
            segment_type="SIDE_RIGHT",
            chain_id=2,
            coords=((3.0, 0.0), (3.0, 10.0)),
            road_width_meter=8.0,
        ),
    ]

    connectors, events = build_transition_connectors(
        [TransitionSite(chain_id=1, root=1, candidate_chain_ids=(2,))],
        {1: (0.0, 0.0), 2: (5.0, 0.0), 3: (0.0, 10.0)},
        [BaseLine(line_id="chain:1:center", segment_type="CENTERLINE", chain_id=1, coords=((0.0, 0.0), (5.0, 0.0)), road_width_meter=3.0), *base_lines],
        {1: ["chain:1:center"], 2: [line.line_id for line in base_lines]},
    )

    assert len(connectors) == 1
    assert {connector.segment_type for connector in connectors} == {"TRANSITION_CONNECTOR"}
    assert len(events) == 1
    assert connectors[0].coords[1] in {(-3.0, 0.0), (3.0, 0.0)}
    assert events[0].split_segment_types in {("SIDE_LEFT",), ("SIDE_RIGHT",)}


def test_build_gap_bridges_connects_short_same_chain_same_side_gap() -> None:
    connectors, events, stats = build_gap_bridges(
        [
            BaseLine(
                line_id="left:a",
                segment_type="SIDE_LEFT",
                chain_id=7,
                coords=((0.0, 0.0), (5.0, 0.0)),
                road_width_meter=8.0,
            ),
            BaseLine(
                line_id="left:b",
                segment_type="SIDE_LEFT",
                chain_id=7,
                coords=((7.0, 0.0), (12.0, 0.0)),
                road_width_meter=8.0,
            ),
        ]
    )

    assert stats["gapBridgeCount"] == 1
    assert len(connectors) == 1
    assert len(events) == 1
    assert connectors[0].segment_type == "GAP_BRIDGE"
    assert connectors[0].coords == ((5.0, 0.0), (7.0, 0.0))
    assert events[0].line_id == "left:b"


def test_build_gap_bridges_can_attach_endpoint_to_line_interior() -> None:
    connectors, events, stats = build_gap_bridges(
        [
            BaseLine(
                line_id="left:a",
                segment_type="SIDE_LEFT",
                chain_id=7,
                coords=((0.0, 0.0), (5.0, 0.0)),
                road_width_meter=8.0,
            ),
            BaseLine(
                line_id="left:target",
                segment_type="SIDE_LEFT",
                chain_id=8,
                coords=((7.0, -4.0), (7.0, 4.0)),
                road_width_meter=8.0,
            ),
        ]
    )

    assert stats["gapBridgeCount"] == 1
    assert connectors[0].coords == ((5.0, 0.0), (7.0, 0.0))
    assert events[0].line_id == "left:target"
    assert events[0].point == (7.0, 0.0)


def test_build_gap_bridges_rejects_barrier_crossing_candidate() -> None:
    connectors, events, stats = build_gap_bridges(
        [
            BaseLine(
                line_id="left:a",
                segment_type="SIDE_LEFT",
                chain_id=7,
                coords=((0.0, 0.0), (5.0, 0.0)),
                road_width_meter=8.0,
            ),
            BaseLine(
                line_id="left:b",
                segment_type="SIDE_LEFT",
                chain_id=8,
                coords=((7.0, 0.0), (12.0, 0.0)),
                road_width_meter=8.0,
            ),
            BaseLine(
                line_id="center:barrier",
                segment_type="CENTERLINE",
                chain_id=99,
                coords=((6.0, -5.0), (6.0, 5.0)),
                road_width_meter=3.0,
            ),
        ]
    )

    assert stats["gapBridgeCount"] == 0
    assert connectors == []
    assert events == []


def test_build_intersection_sectors_returns_sector_per_arm_gap() -> None:
    temp_segments = [
        TempSegment(1, 1, "a", 8.0, 2, "MULTI_LANE", 1, 2, ((0.0, 0.0), (10.0, 0.0))),
        TempSegment(2, 2, "b", 8.0, 2, "MULTI_LANE", 1, 3, ((0.0, 0.0), (0.0, 10.0))),
        TempSegment(3, 3, "c", 8.0, 2, "MULTI_LANE", 1, 4, ((0.0, 0.0), (-10.0, 0.0))),
    ]
    sectors = build_intersection_sectors(
        temp_segments,
        {1: (0.0, 0.0), 2: (10.0, 0.0), 3: (0.0, 10.0), 4: (-10.0, 0.0)},
        {1: {1, 2, 3}, 2: {1}, 3: {2}, 4: {3}},
        {1},
    )

    assert 1 in sectors
    assert len(sectors[1]) == 3


def test_build_same_side_corner_bridges_connects_same_root_same_sector_fragments() -> None:
    connectors, events, stats = build_same_side_corner_bridges(
        [
            BaseLine("left:a", "SIDE_LEFT", 1, ((9.0, 1.0), (6.0, 1.0)), 8.0),
            BaseLine("left:b", "SIDE_LEFT", 2, ((1.0, 9.0), (1.0, 6.0)), 8.0),
            BaseLine("right:c", "SIDE_RIGHT", 3, ((-9.0, -1.0), (-6.0, -1.0)), 8.0),
        ],
        {1: (0.0, 0.0)},
        {1: 5.0},
        {
            1: [
                IntersectionSector(
                    root=1,
                    sector_index=0,
                    start_angle_rad=0.0,
                    end_angle_rad=1.57079632679,
                    bisector_angle_rad=0.78539816339,
                ),
            ]
        },
    )

    assert stats["sameSideCornerBridgeCount"] >= 1
    assert connectors
    assert connectors[0].segment_type == "SAME_SIDE_CORNER_BRIDGE"
    assert events


def test_build_cross_side_corner_bridges_connects_left_and_right_within_same_sector() -> None:
    connectors, events, stats = build_cross_side_corner_bridges(
        [
            BaseLine("left:a", "SIDE_LEFT", 1, ((9.0, 1.0), (6.0, 1.0)), 8.0),
            BaseLine("right:b", "SIDE_RIGHT", 2, ((8.5, 2.0), (5.5, 2.0)), 8.0),
        ],
        {1: (0.0, 0.0)},
        {1: 8.0},
        {
            1: [
                IntersectionSector(
                    root=1,
                    sector_index=0,
                    start_angle_rad=0.0,
                    end_angle_rad=1.57079632679,
                    bisector_angle_rad=0.78539816339,
                ),
            ]
        },
    )

    assert stats["crossSideCornerBridgeCount"] >= 1
    assert connectors
    assert connectors[0].segment_type == "CROSS_SIDE_CORNER_BRIDGE"
    assert events


def test_resolve_cross_type_intersections_splits_side_and_gap_bridge() -> None:
    segments, stats = resolve_cross_type_intersections(
        [
            ("SIDE_LEFT", ((0.0, 0.0), (10.0, 0.0))),
            ("GAP_BRIDGE", ((5.0, -2.0), (5.0, 2.0))),
        ],
        {1: (5.0, 0.0)},
        {1},
        {1: 5.0},
        {},
    )

    assert stats["crossTypeIntersectionCount"] >= 1
    assert len(segments) == 4


def test_consolidate_junction_candidates_merges_close_endpoints() -> None:
    consolidated, stats = consolidate_junction_candidates(
        [
            ("SIDE_LEFT", ((0.0, 0.0), (5.0, 0.0))),
            ("GAP_BRIDGE", ((5.2, 0.1), (6.0, 1.0))),
        ]
    )

    assert stats["junctionConsolidationClusterCount"] >= 1
    assert stats["mergedJunctionNodeCount"] >= 1
    assert consolidated


def test_cleanup_junction_pockets_removes_short_loop_inside_pocket() -> None:
    cleaned, stats = cleanup_junction_pockets(
        [
            ("SIDE_LEFT", ((0.0, 0.0), (5.0, 0.0))),
            ("GAP_BRIDGE", ((0.5, 0.5), (1.0, 1.0), (0.6, 0.4))),
        ],
        {1: (0.0, 0.0)},
        {1},
        {1: 5.0},
    )

    assert stats["junctionPocketCleanupCount"] >= 1
    assert stats["junctionPocketRemovedStubCount"] >= 1
    assert all(segment_type != "GAP_BRIDGE" for segment_type, _ in cleaned)


def test_trim_centerline_for_transition_cuts_root_side_of_chain() -> None:
    chain = Chain(
        chain_id=1,
        classification="CENTERLINE",
        start_root=1,
        end_root=2,
        coords=((0.0, 0.0), (10.0, 0.0)),
        segment_ids=(1,),
        road_width_meter=3.0,
        lane_count=1,
    )

    trimmed = trim_centerline_for_transition(
        chain,
        {1: (0.0, 0.0), 2: (10.0, 0.0)},
        {1: 2.0, 2: 1.0},
        {1: {1}},
    )

    assert trimmed[0][0] > 0.0
    assert trimmed[-1] == (10.0, 0.0)


def test_trim_side_line_tails_cuts_dangling_segment_after_same_side_intersection() -> None:
    lines = [
        BaseLine(
            line_id="a",
            segment_type="SIDE_LEFT",
            chain_id=1,
            coords=((0.0, 0.0), (10.0, 0.0)),
            road_width_meter=8.0,
        ),
        BaseLine(
            line_id="b",
            segment_type="SIDE_LEFT",
            chain_id=2,
            coords=((2.0, -5.0), (2.0, 2.0)),
            road_width_meter=8.0,
        ),
    ]

    trimmed = trim_side_line_tails(lines, Point(0.0, 0.0).buffer(2.0))

    trimmed_by_id = {line.line_id: line for line in trimmed}
    assert trimmed_by_id["a"].coords[0] == (2.0, 0.0)
    assert trimmed_by_id["b"].coords[-1] == (2.0, 0.0)


def test_split_base_lines_does_not_split_centerline_on_transition_event() -> None:
    centerline = BaseLine(
        line_id="center",
        segment_type="CENTERLINE",
        chain_id=1,
        coords=((0.0, 0.0), (10.0, 0.0)),
        road_width_meter=3.0,
    )
    side = BaseLine(
        line_id="side",
        segment_type="SIDE_LEFT",
        chain_id=2,
        coords=((3.0, -2.0), (3.0, 4.0)),
        road_width_meter=8.0,
    )
    pieces = split_base_lines(
        [centerline, side],
        [
            EventPoint(
                line_id="center",
                point=(0.0, 0.0),
                node_type="LANE_TRANSITION",
                split_segment_types=("SIDE_LEFT",),
            ),
            EventPoint(
                line_id="side",
                point=(3.0, 0.0),
                node_type="LANE_TRANSITION",
                split_segment_types=("SIDE_LEFT",),
            ),
        ],
    )

    center_pieces = [coords for segment_type, coords in pieces if segment_type == "CENTERLINE"]
    side_pieces = [coords for segment_type, coords in pieces if segment_type == "SIDE_LEFT"]

    assert center_pieces == [((0.0, 0.0), (10.0, 0.0))]
    assert side_pieces == [((3.0, -2.0), (3.0, 0.0)), ((3.0, 0.0), (3.0, 4.0))]
