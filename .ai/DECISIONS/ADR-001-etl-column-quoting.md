# ADR-001: ETL Python 스크립트의 DB 컬럼명 인용 규칙

## Status

Accepted

## Context

`db/schema.sql`은 PostgreSQL camelCase 컬럼명(`"placeId"`, `"fromNodeId"` 등)을 큰따옴표로 인용해 대소문자를 보존한다.
Spring Boot 쪽은 `hibernate.globally_quoted_identifiers=true`를 설정해 Hibernate가 모든 식별자를 자동 인용하므로 camelCase 필드명이 그대로 동작한다.
ETL Python 스크립트(psycopg3)는 컬럼명을 문자열로 직접 지정하는데, 큰따옴표 없이 `placeId`를 쓰면 PostgreSQL이 소문자로 fold해 `placeid`를 찾아 오류가 발생한다.

## Decision

ETL Python 스크립트에서 DB 컬럼명을 지정할 때는 반드시 psycopg3의 `sql.Identifier`를 사용하거나, 컬럼명을 큰따옴표로 명시 인용한다.

```python
# 올바른 방식 1 — sql.Identifier (권장)
from psycopg import sql
cur.execute(
    sql.SQL("INSERT INTO places ({}) VALUES ({})").format(
        sql.SQL(", ").join(map(sql.Identifier, ["placeId", "name", "category", "point"])),
        sql.SQL(", ").join([sql.Placeholder()] * 4),
    ),
    (place_id, name, category, point_wkt),
)

# 올바른 방식 2 — 문자열 직접 인용 (단순 쿼리에서만 허용)
cur.execute('INSERT INTO places ("placeId", "name") VALUES (%s, %s)', (1, "test"))

# 금지 — 인용 없는 camelCase
cur.execute("INSERT INTO places (placeId, name) VALUES (%s, %s)", ...)  # PostgreSQL이 placeid로 해석
```

## Consequences

- **Positive:** Spring Hibernate와 ETL이 동일한 실제 컬럼명을 참조하므로 스키마를 snake_case로 변경하지 않아도 된다.
- **Tradeoff:** ETL 스크립트 작성 시 컬럼명 인용을 누락하면 런타임 오류가 발생하지만 문법 오류가 아니므로 컴파일/린트 단계에서 잡히지 않는다.
- **Operational risk:** 신규 테이블 컬럼 추가 시 ETL 작성자가 이 규칙을 모르면 silent fold 오류가 발생할 수 있다.

## Follow-up

- 워크스트림 02(`02-shp-network-load.md`) ETL 구현 시 `sql.Identifier` 패턴을 `etl/common/db.py`에 헬퍼로 추가한다.
- `etl/README.md` 또는 인라인 주석으로 이 규칙을 명시한다.
- 코드 리뷰 체크리스트(`exception-checklist.md`)에 ETL 컬럼 인용 확인 항목을 추가하는 것을 검토한다.
