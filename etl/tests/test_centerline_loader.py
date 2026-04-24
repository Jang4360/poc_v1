from __future__ import annotations

from etl.common.centerline_loader import (
    DisjointSet,
    line_length_meter,
    node_key,
    normalize_projected_segments,
    split_projected_segment,
)


def test_node_key_rounds_to_six_decimals() -> None:
    assert node_key(129.123456789, 35.987654321) == "129.123457:35.987654"


def test_line_length_meter_is_positive_for_distinct_points() -> None:
    length = line_length_meter(((129.0, 35.0), (129.001, 35.001)))
    assert length > 0


def test_disjoint_set_counts_components() -> None:
    dsu = DisjointSet()
    dsu.union(1, 2)
    dsu.union(3, 4)
    dsu.union(2, 3)
    dsu.union(5, 5)
    assert dsu.component_count() == 2


def test_split_projected_segment_splits_line_at_interior_points() -> None:
    parts = split_projected_segment(((0.0, 0.0), (10.0, 0.0)), [(4.0, 0.0), (7.0, 0.0)])
    assert parts == [
        ((0.0, 0.0), (4.0, 0.0)),
        ((4.0, 0.0), (7.0, 0.0)),
        ((7.0, 0.0), (10.0, 0.0)),
    ]


def test_normalize_projected_segments_snaps_branch_endpoint_and_splits_mainline() -> None:
    normalized, report = normalize_projected_segments(
        [
            ((0.0, 0.0), (10.0, 0.0)),
            ((5.0, 1.5), (5.0, 6.0)),
        ],
        snap_tolerance_meter=2.0,
        node_merge_tolerance_meter=0.5,
    )

    assert report["snapped_endpoint_count"] == 1
    assert len(normalized) == 3
    assert ((0.0, 0.0), (5.0, 0.0)) in normalized
    assert ((5.0, 0.0), (10.0, 0.0)) in normalized
    assert ((5.0, 0.0), (5.0, 6.0)) in normalized


def test_normalize_projected_segments_does_not_snap_when_outside_tolerance() -> None:
    normalized, report = normalize_projected_segments(
        [
            ((0.0, 0.0), (10.0, 0.0)),
            ((5.0, 2.1), (5.0, 6.0)),
        ],
        snap_tolerance_meter=2.0,
        node_merge_tolerance_meter=0.5,
    )

    assert report["snapped_endpoint_count"] == 0
    assert normalized == [
        ((0.0, 0.0), (10.0, 0.0)),
        ((5.0, 2.1), (5.0, 6.0)),
    ]
