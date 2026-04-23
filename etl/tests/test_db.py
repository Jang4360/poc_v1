"""Tests for etl/common/db.py helpers."""
from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest
from psycopg import sql

from etl.common.db import ewkt, insert_row, insert_rows


def _make_cursor() -> MagicMock:
    return MagicMock()


class TestInsertRow:
    def test_calls_execute_once(self):
        cur = _make_cursor()
        insert_row(cur, "places", {"placeId": 1, "name": "테스트"})
        cur.execute.assert_called_once()

    def test_values_passed_in_order(self):
        cur = _make_cursor()
        insert_row(cur, "places", {"placeId": 42, "name": "카페"})
        _, args, _ = cur.execute.mock_calls[0]
        assert list(args[1]) == [42, "카페"]

    def test_query_uses_sql_composed(self):
        """execute 첫 번째 인자가 sql.Composed 타입이어야 한다 — 문자열 직접 조합 방지."""
        cur = _make_cursor()
        insert_row(cur, "places", {"placeId": 1, "name": "x"})
        query_arg = cur.execute.call_args[0][0]
        assert isinstance(query_arg, sql.Composed), (
            "쿼리가 sql.Composed가 아닙니다. "
            "camelCase 컬럼명이 PostgreSQL에 의해 소문자로 fold될 수 있습니다."
        )

    def test_empty_row_raises(self):
        cur = _make_cursor()
        with pytest.raises(Exception):
            insert_row(cur, "places", {})

    def test_ewkt_value_uses_composed_query(self):
        cur = _make_cursor()
        insert_row(cur, "road_nodes", {"point": ewkt("SRID=4326;POINT(129 35)")})
        query_arg = cur.execute.call_args[0][0]
        assert isinstance(query_arg, sql.Composed)
        assert cur.execute.call_args[0][1] == ["SRID=4326;POINT(129 35)"]


class TestInsertRows:
    def test_empty_sequence_does_not_call_executemany(self):
        cur = _make_cursor()
        insert_rows(cur, "places", [])
        cur.executemany.assert_not_called()

    def test_single_row_calls_executemany_once(self):
        cur = _make_cursor()
        insert_rows(cur, "places", [{"placeId": 1, "name": "A"}])
        cur.executemany.assert_called_once()

    def test_multiple_rows_values_passed_correctly(self):
        cur = _make_cursor()
        rows = [{"placeId": 1, "name": "A"}, {"placeId": 2, "name": "B"}]
        insert_rows(cur, "places", rows)
        _, args, _ = cur.executemany.mock_calls[0]
        assert args[1] == [[1, "A"], [2, "B"]]

    def test_query_uses_sql_composed(self):
        cur = _make_cursor()
        insert_rows(cur, "places", [{"placeId": 1, "name": "x"}])
        query_arg = cur.executemany.call_args[0][0]
        assert isinstance(query_arg, sql.Composed)
