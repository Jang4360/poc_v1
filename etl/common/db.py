from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import psycopg
from psycopg import sql

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is installed by etl/requirements.txt
    load_dotenv = None


ROOT_DIR = Path(__file__).resolve().parents[2]
if load_dotenv is not None:
    load_dotenv(ROOT_DIR / ".env")


@dataclass(frozen=True)
class DbConfig:
    host: str
    port: int
    database: str
    user: str
    password: str

    @classmethod
    def from_env(cls) -> "DbConfig":
        return cls(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_HOST_PORT", "15432")),
            database=os.getenv("POSTGRES_DB", "ieumgil"),
            user=os.getenv("POSTGRES_USER", "ieumgil"),
            password=os.getenv("POSTGRES_PASSWORD", "ieumgil"),
        )


def connect(config: DbConfig | None = None) -> psycopg.Connection:
    cfg = config or DbConfig.from_env()
    return psycopg.connect(
        host=cfg.host,
        port=cfg.port,
        dbname=cfg.database,
        user=cfg.user,
        password=cfg.password,
    )


@dataclass(frozen=True)
class SqlValue:
    expression: sql.Composable
    value: Any


def ewkt(value: str) -> SqlValue:
    return SqlValue(sql.SQL("ST_GeomFromEWKT({})"), value)


def execute_script(path: Path, config: DbConfig | None = None) -> None:
    """Execute a SQL script against the configured database."""
    script = path.read_text(encoding="utf-8")
    with connect(config) as conn:
        with conn.cursor() as cur:
            cur.execute(script)
        conn.commit()


def insert_row(
    cur: psycopg.Cursor,
    table: str,
    row: dict[str, Any],
) -> None:
    """camelCase 컬럼명을 sql.Identifier로 인용해 단일 행을 INSERT한다.

    PostgreSQL은 큰따옴표 없이 camelCase를 소문자로 fold하므로
    db/schema.sql의 인용된 컬럼명과 일치시키려면 반드시 이 함수를 사용한다.
    ADR-001-etl-column-quoting.md 참조.
    """
    if not row:
        raise ValueError("row must not be empty")
    columns = list(row.keys())
    values: list[Any] = []
    placeholders: list[sql.Composable] = []
    for value in row.values():
        if isinstance(value, SqlValue):
            placeholders.append(value.expression.format(sql.Placeholder()))
            values.append(value.value)
        else:
            placeholders.append(sql.Placeholder())
            values.append(value)
    query = sql.SQL("INSERT INTO {table} ({cols}) VALUES ({vals})").format(
        table=sql.Identifier(table),
        cols=sql.SQL(", ").join(map(sql.Identifier, columns)),
        vals=sql.SQL(", ").join(placeholders),
    )
    cur.execute(query, values)


def insert_rows(
    cur: psycopg.Cursor,
    table: str,
    rows: Sequence[dict[str, Any]],
) -> None:
    """camelCase 컬럼명을 sql.Identifier로 인용해 여러 행을 executemany로 INSERT한다."""
    if not rows:
        return
    columns = list(rows[0].keys())
    query = sql.SQL("INSERT INTO {table} ({cols}) VALUES ({vals})").format(
        table=sql.Identifier(table),
        cols=sql.SQL(", ").join(map(sql.Identifier, columns)),
        vals=sql.SQL(", ").join([sql.Placeholder()] * len(columns)),
    )
    cur.executemany(query, [list(r.values()) for r in rows])
