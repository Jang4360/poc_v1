from __future__ import annotations

from shapely.geometry import LineString
from shapely.ops import unary_union

from etl.common import segment_centerline_02c


def test_project_center_returns_projected_coordinates() -> None:
    x, y = segment_centerline_02c.project_center(35.16332, 129.1588705)

    assert 1_100_000 < x < 1_200_000
    assert 1_650_000 < y < 1_750_000


def test_transform_projected_coords_keeps_coordinate_count() -> None:
    center = segment_centerline_02c.project_center(35.16332, 129.1588705)
    coords = segment_centerline_02c.transform_projected_coords(
        [
            center,
            (center[0] + 10.0, center[1] + 10.0),
        ]
    )

    assert len(coords) == 2
    assert 129.0 < coords[0][0] < 130.0
    assert 35.0 < coords[0][1] < 36.0


def test_build_payload_contains_centerline_only() -> None:
    payload = segment_centerline_02c.build_payload(radius_m=250)

    assert payload["summary"]["segmentCount"] > 0
    assert payload["summary"]["nodeCount"] == 0
    assert payload["summary"]["segmentTypeCounts"] == [
        {"name": "CENTERLINE", "count": payload["summary"]["segmentCount"]}
    ]
    assert payload["layers"]["roadNodes"]["features"] == []
    assert {
        feature["properties"]["segmentType"]
        for feature in payload["layers"]["roadSegments"]["features"]
    } == {"CENTERLINE"}


def test_offset_line_parts_creates_left_and_right_lines() -> None:
    left_parts = segment_centerline_02c.offset_line_parts(((0.0, 0.0), (10.0, 0.0)), 2.0, side="left")
    right_parts = segment_centerline_02c.offset_line_parts(((0.0, 0.0), (10.0, 0.0)), 2.0, side="right")

    assert left_parts == [((0.0, 2.0), (10.0, 2.0))]
    assert right_parts == [((0.0, -2.0), (10.0, -2.0))]


def test_build_sideline_payload_contains_side_segments_only() -> None:
    payload = segment_centerline_02c.build_sideline_payload(radius_m=250)
    segment_types = {
        feature["properties"]["segmentType"]
        for feature in payload["layers"]["roadSegments"]["features"]
    }

    assert payload["summary"]["segmentCount"] > 0
    assert payload["summary"]["nodeCount"] == 0
    assert payload["layers"]["roadNodes"]["features"] == []
    assert segment_types == {"SIDE_LEFT", "SIDE_RIGHT"}
    assert "CENTERLINE" not in segment_types


def test_boundary_lines_from_surface_extracts_outer_ring() -> None:
    surface = unary_union(
        [
            LineString([(0.0, 0.0), (20.0, 0.0)]).buffer(3.0, cap_style=2, join_style=2),
            LineString([(10.0, -10.0), (10.0, 10.0)]).buffer(3.0, cap_style=2, join_style=2),
        ]
    )

    boundaries = segment_centerline_02c.boundary_lines_from_surface(surface)

    assert boundaries
    assert {segment_type for segment_type, _coords in boundaries} == {"ROAD_BOUNDARY"}
    assert all(len(coords) >= 2 for _segment_type, coords in boundaries)


def test_boundary_lines_from_surface_removes_short_perpendicular_caps() -> None:
    surface = LineString([(0.0, 0.0), (20.0, 0.0)]).buffer(3.0, cap_style=2, join_style=2)

    boundaries = segment_centerline_02c.boundary_lines_from_surface(surface)

    assert len(boundaries) == 2
    assert all(coords[0][0] != coords[-1][0] for _segment_type, coords in boundaries)
    assert all(segment_centerline_02c.projected_length_meter(coords) > 10.0 for _segment_type, coords in boundaries)


def test_filter_internal_perpendicular_boundaries_removes_centerline_cross_edge() -> None:
    boundary_lines = [
        (
            "ROAD_BOUNDARY",
            (
                (0.0, 3.0),
                (10.0, 3.0),
                (10.0, -3.0),
                (20.0, -3.0),
            ),
        )
    ]
    centerlines = [LineString([(0.0, 0.0), (20.0, 0.0)])]

    filtered, removed_edges = segment_centerline_02c.filter_internal_perpendicular_boundaries(
        boundary_lines,
        centerlines,
    )

    assert removed_edges == 1
    assert filtered == [
        ("ROAD_BOUNDARY", ((0.0, 3.0), (10.0, 3.0))),
        ("ROAD_BOUNDARY", ((10.0, -3.0), (20.0, -3.0))),
    ]


def test_build_road_boundary_payload_contains_boundary_segments_only() -> None:
    payload = segment_centerline_02c.build_road_boundary_payload(radius_m=250)
    segment_types = {
        feature["properties"]["segmentType"]
        for feature in payload["layers"]["roadSegments"]["features"]
    }

    assert payload["summary"]["segmentCount"] > 0
    assert payload["summary"]["nodeCount"] == 0
    assert payload["meta"]["stage"] == "road-boundary-buffer-union"
    assert segment_types <= {"ROAD_BOUNDARY", "ROAD_BOUNDARY_INNER"}


def test_split_and_prune_at_intersections_removes_short_original_endpoint_tail() -> None:
    segments = [
        segment_centerline_02c.ProjectedSegment(
            segment_type="SIDE_LEFT",
            source_index=1,
            source_part=1,
            road_width_meter=8.0,
            offset_meter=4.0,
            coords=((0.0, 0.0), (50.0, 0.0)),
        ),
        segment_centerline_02c.ProjectedSegment(
            segment_type="SIDE_RIGHT",
            source_index=2,
            source_part=1,
            road_width_meter=20.0,
            offset_meter=10.0,
            coords=((25.0, -30.0), (25.0, 1.0)),
        ),
    ]

    cleaned, nodes, stats = segment_centerline_02c.split_and_prune_at_intersections(segments)

    assert stats["intersectionNodeCount"] == 1
    assert stats["tailPruneCount"] == 1
    assert len(nodes) == 1
    assert all(segment.coords != ((25.0, 0.0), (25.0, 1.0)) for segment in cleaned)
    assert any(segment.coords == ((25.0, -30.0), (25.0, 0.0)) for segment in cleaned)


def test_split_and_prune_at_intersections_keeps_long_original_endpoint_tail() -> None:
    segments = [
        segment_centerline_02c.ProjectedSegment(
            segment_type="SIDE_LEFT",
            source_index=1,
            source_part=1,
            road_width_meter=8.0,
            offset_meter=4.0,
            coords=((0.0, 0.0), (50.0, 0.0)),
        ),
        segment_centerline_02c.ProjectedSegment(
            segment_type="SIDE_RIGHT",
            source_index=2,
            source_part=1,
            road_width_meter=20.0,
            offset_meter=10.0,
            coords=((25.0, -30.0), (25.0, 30.0)),
        ),
    ]

    cleaned, nodes, stats = segment_centerline_02c.split_and_prune_at_intersections(segments)

    assert stats["intersectionNodeCount"] == 1
    assert stats["tailPruneCount"] == 0
    assert len(cleaned) == 4
    assert len(nodes) == 1


def test_split_and_prune_by_centerline_contacts_removes_node_to_contact_direction_only() -> None:
    segments = [
        segment_centerline_02c.ProjectedSegment(
            segment_type="SIDE_LEFT",
            source_index=1,
            source_part=1,
            road_width_meter=8.0,
            offset_meter=4.0,
            coords=((0.0, 0.0), (20.0, 0.0)),
        ),
        segment_centerline_02c.ProjectedSegment(
            segment_type="SIDE_RIGHT",
            source_index=2,
            source_part=1,
            road_width_meter=8.0,
            offset_meter=4.0,
            coords=((10.0, -5.0), (10.0, 5.0)),
        ),
    ]
    centerlines = [
        segment_centerline_02c.CenterlineReference(
            source_index=99,
            source_part=1,
            coords=((12.0, -5.0), (12.0, 5.0)),
        )
    ]

    cleaned, nodes, stats = segment_centerline_02c.split_and_prune_by_centerline_contacts(segments, centerlines)

    assert stats["intersectionNodeCount"] == 1
    assert stats["centerlineContactPruneCount"] == 1
    assert len(nodes) == 1
    assert any(segment.coords == ((12.0, 0.0), (20.0, 0.0)) for segment in cleaned)
    assert any(segment.coords == ((0.0, 0.0), (10.0, 0.0)) for segment in cleaned)
    assert all(segment.coords != ((10.0, 0.0), (12.0, 0.0)) for segment in cleaned)


def test_split_and_prune_by_centerline_contacts_ignores_same_source_centerline() -> None:
    segments = [
        segment_centerline_02c.ProjectedSegment(
            segment_type="SIDE_LEFT",
            source_index=1,
            source_part=1,
            road_width_meter=8.0,
            offset_meter=4.0,
            coords=((0.0, 0.0), (20.0, 0.0)),
        ),
        segment_centerline_02c.ProjectedSegment(
            segment_type="SIDE_RIGHT",
            source_index=2,
            source_part=1,
            road_width_meter=8.0,
            offset_meter=4.0,
            coords=((10.0, -5.0), (10.0, 5.0)),
        ),
    ]
    centerlines = [
        segment_centerline_02c.CenterlineReference(
            source_index=1,
            source_part=1,
            coords=((12.0, -5.0), (12.0, 5.0)),
        )
    ]

    cleaned, _nodes, stats = segment_centerline_02c.split_and_prune_by_centerline_contacts(segments, centerlines)

    assert stats["centerlineContactPruneCount"] == 0
    assert any(segment.coords == ((10.0, 0.0), (20.0, 0.0)) for segment in cleaned)


def test_find_sideline_intersections_robust_marks_linear_overlap_nodes() -> None:
    segments = [
        segment_centerline_02c.ProjectedSegment(
            segment_type="SIDE_LEFT",
            source_index=1,
            source_part=1,
            road_width_meter=8.0,
            offset_meter=4.0,
            coords=((0.0, 0.0), (30.0, 0.0)),
        ),
        segment_centerline_02c.ProjectedSegment(
            segment_type="SIDE_RIGHT",
            source_index=2,
            source_part=1,
            road_width_meter=8.0,
            offset_meter=4.0,
            coords=((10.0, 0.0), (20.0, 0.0)),
        ),
    ]

    split_points, node_points, _thresholds, stats = segment_centerline_02c.find_sideline_intersections_robust(segments)

    assert len(node_points) == 3
    assert stats["overlapIntersectionCount"] == 3
    assert len(split_points[0]) == 3
    assert len(split_points[1]) == 1


def test_split_and_prune_sideline_intersection_01_removes_dangling_chain_from_junction() -> None:
    segments = [
        segment_centerline_02c.ProjectedSegment(
            segment_type="SIDE_LEFT",
            source_index=1,
            source_part=1,
            road_width_meter=8.0,
            offset_meter=4.0,
            coords=((-40.0, 0.0), (8.0, 0.0)),
        ),
        segment_centerline_02c.ProjectedSegment(
            segment_type="SIDE_RIGHT",
            source_index=2,
            source_part=1,
            road_width_meter=8.0,
            offset_meter=4.0,
            coords=((0.0, -20.0), (0.0, 20.0)),
        ),
    ]

    cleaned, nodes, stats = segment_centerline_02c.split_and_prune_sideline_intersection_01(segments)

    assert len(nodes) == 1
    assert stats["junctionChainPruneCount"] == 1
    assert any(segment.coords == ((-40.0, 0.0), (0.0, 0.0)) for segment in cleaned)
    assert all(segment.coords != ((0.0, 0.0), (8.0, 0.0)) for segment in cleaned)


def test_find_sideline_intersections_robust_02_marks_non_parallel_near_cross() -> None:
    segments = [
        segment_centerline_02c.ProjectedSegment(
            segment_type="SIDE_LEFT",
            source_index=1,
            source_part=1,
            road_width_meter=8.0,
            offset_meter=4.0,
            coords=((0.0, 0.0), (10.0, 0.0)),
        ),
        segment_centerline_02c.ProjectedSegment(
            segment_type="SIDE_RIGHT",
            source_index=2,
            source_part=1,
            road_width_meter=8.0,
            offset_meter=4.0,
            coords=((5.0, 1.0), (5.0, 10.0)),
        ),
    ]

    split_points, node_points, _thresholds, stats = segment_centerline_02c.find_sideline_intersections_robust_02(
        segments
    )

    assert len(node_points) == 1
    assert stats["nearCrossCount"] == 1
    assert stats["endpointSnapCrossCount"] == 1
    assert len(split_points[0]) == 1
    assert len(split_points[1]) == 1


def test_split_and_prune_sideline_intersection_02_uses_endpoint_snap_node_for_chain_prune() -> None:
    segments = [
        segment_centerline_02c.ProjectedSegment(
            segment_type="SIDE_LEFT",
            source_index=1,
            source_part=1,
            road_width_meter=8.0,
            offset_meter=4.0,
            coords=((0.0, 0.0), (10.0, 0.0)),
        ),
        segment_centerline_02c.ProjectedSegment(
            segment_type="SIDE_RIGHT",
            source_index=2,
            source_part=1,
            road_width_meter=8.0,
            offset_meter=4.0,
            coords=((5.0, 1.0), (5.0, 6.0)),
        ),
    ]

    cleaned, nodes, stats = segment_centerline_02c.split_and_prune_sideline_intersection_02(segments)

    assert len(nodes) == 1
    assert stats["nearCrossCount"] == 1
    assert stats["junctionChainPruneCount"] >= 1
    assert all(segment.coords != ((5.0, 1.0), (5.0, 6.0)) for segment in cleaned)


def test_cluster_intersection_candidates_collapses_nearby_markers() -> None:
    split_points = {
        0: {
            (0, 0): (0.0, 0.0),
            (1, 1): (1.0, 1.0),
            (30, 0): (30.0, 0.0),
        }
    }
    node_points = {
        (0, 0): (0.0, 0.0),
        (1, 1): (1.0, 1.0),
        (30, 0): (30.0, 0.0),
    }
    thresholds = {(0, 0): 8.0, (1, 1): 10.0, (30, 0): 8.0}

    clustered_split, clustered_nodes, clustered_thresholds, stats = (
        segment_centerline_02c.cluster_intersection_candidates(
            split_points,
            node_points,
            thresholds,
            radius_meter=5.0,
        )
    )

    assert len(clustered_nodes) == 2
    assert stats["clusterReductionCount"] == 1
    assert max(clustered_thresholds.values()) == 10.0
    assert len(clustered_split[0]) == 2


def test_split_and_prune_sideline_intersection_03_clusters_multiple_near_cross_markers() -> None:
    segments = [
        segment_centerline_02c.ProjectedSegment(
            segment_type="SIDE_LEFT",
            source_index=1,
            source_part=1,
            road_width_meter=8.0,
            offset_meter=4.0,
            coords=((0.0, 0.0), (20.0, 0.0)),
        ),
        segment_centerline_02c.ProjectedSegment(
            segment_type="SIDE_RIGHT",
            source_index=2,
            source_part=1,
            road_width_meter=8.0,
            offset_meter=4.0,
            coords=((5.0, 1.0), (5.0, 8.0)),
        ),
        segment_centerline_02c.ProjectedSegment(
            segment_type="SIDE_RIGHT",
            source_index=3,
            source_part=1,
            road_width_meter=8.0,
            offset_meter=4.0,
            coords=((7.0, 1.0), (7.0, 8.0)),
        ),
    ]

    _cleaned, nodes, stats = segment_centerline_02c.split_and_prune_sideline_intersection_03(segments)

    assert stats["rawIntersectionNodeCount"] >= 2
    assert stats["clusterReductionCount"] >= 1
    assert len(nodes) == 1


def test_materialize_endpoint_graph_clusters_close_endpoints_and_assigns_node_refs() -> None:
    segments = [
        segment_centerline_02c.ProjectedSegment(
            segment_type="SIDE_LEFT",
            source_index=1,
            source_part=1,
            road_width_meter=8.0,
            offset_meter=4.0,
            coords=((0.0, 0.0), (10.0, 0.0)),
        ),
        segment_centerline_02c.ProjectedSegment(
            segment_type="SIDE_LEFT",
            source_index=2,
            source_part=1,
            road_width_meter=8.0,
            offset_meter=4.0,
            coords=((10.8, 0.2), (20.0, 0.0)),
        ),
    ]

    nodes, graph_segments, stats = segment_centerline_02c.materialize_endpoint_graph(
        segments,
        snap_radius_meter=1.5,
    )

    assert stats["rawEndpointCount"] == 4
    assert stats["endpointNodeCount"] == 3
    assert stats["endpointClusterReductionCount"] == 1
    assert {node["properties"]["endpointCount"] for node in nodes} == {1, 2}
    assert all("fromNodeId" in segment["properties"] for segment in graph_segments)
    assert all("toNodeId" in segment["properties"] for segment in graph_segments)
    assert graph_segments[0]["properties"]["toNodeId"] == graph_segments[1]["properties"]["fromNodeId"]


def test_build_graph_materialized_payload_assigns_from_to_nodes() -> None:
    payload = segment_centerline_02c.build_graph_materialized_payload(radius_m=250)
    node_ids = {feature["properties"]["vertexId"] for feature in payload["layers"]["roadNodes"]["features"]}
    segment_features = payload["layers"]["roadSegments"]["features"]

    assert payload["summary"]["nodeCount"] > 0
    assert payload["summary"]["segmentCount"] > 0
    assert payload["meta"]["endpointClusterReductionCount"] > 0
    assert all(feature["properties"]["fromNodeId"] in node_ids for feature in segment_features)
    assert all(feature["properties"]["toNodeId"] in node_ids for feature in segment_features)
    assert {
        feature["properties"]["segmentType"]
        for feature in segment_features
    } <= {"SIDE_LEFT", "SIDE_RIGHT"}


def test_build_sideline_intersection_payload_adds_nodes_and_keeps_side_only_segments() -> None:
    payload = segment_centerline_02c.build_sideline_intersection_payload(radius_m=250)
    segment_types = {
        feature["properties"]["segmentType"]
        for feature in payload["layers"]["roadSegments"]["features"]
    }

    assert payload["summary"]["segmentCount"] > 0
    assert payload["summary"]["nodeCount"] > 0
    assert segment_types <= {"SIDE_LEFT", "SIDE_RIGHT"}
    assert payload["meta"]["tailPruneCount"] >= 0
