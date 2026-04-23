from __future__ import annotations

from etl.common.centerline_loader import DisjointSet, line_length_meter, node_key


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
