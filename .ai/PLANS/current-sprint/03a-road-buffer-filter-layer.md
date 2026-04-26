# 03A Road Buffer Filter Layer

## Workstream

`N3L_A0020000_26 중심선 + 폭(RVWD) 기반 보조 polygon 필터 레이어 적재`

## Source Inputs

- `etl/raw/N3L_A0020000_26.shp`
- `etl/raw/N3L_A0020000_26.dbf`
- `etl/raw/N3L_A0020000_26.prj`
- `db/schema.sql`
- `etl/common/centerline_loader.py`
- `etl/common/reference_loader.py`
- `docs/erd_v2.md`
- `.ai/ARCHITECTURE.md`

## Goal

`road_segments`를 canonical 보행 네트워크로 유지한 상태에서, `N3L_A0020000_26`의 중심선 geometry와 `RVWD` 폭 속성을 이용해 ETL 사전 필터링용 보조 polygon 레이어를 DB 테이블로 적재한다. 이 레이어는 운영 서비스용 truth 테이블이 아니라 reference ETL의 candidate 축소와 false positive 감소를 위한 판별 레이어로만 사용한다.

## Scope

- `N3L_A0020000_26` 원본 shape/DBF를 읽어 `edgeId` 기준 보조 polygon 생성 규칙을 정의
- 보조 polygon 적재용 DB 테이블 추가
- `road_segments`와 동일한 `edgeId` handoff 계약 유지
- reference ETL에서 point/polygon feature를 먼저 보조 polygon으로 필터링하는 단계 추가
- 재생성 가능한 비운영 테이블로 유지

## Non-Goals

- 실제 도로 경계를 복원하는 정밀 polygon 구축
- `road_segments` 대체 또는 GraphHopper 기준 geometry 변경
- 운영 API가 직접 조회하는 서비스 테이블 추가
- 기존 `segment_features` truth semantics 변경

## Success Criteria

- [x] 보조 polygon 테이블이 `road_segments.edgeId`와 1:1 또는 deterministic하게 연결된다.
- [x] `N3L_A0020000_26`만으로 생성 가능한 polygon이 "정확한 경계"가 아니라 "buffer 기반 후보 필터"임을 계획에 명시한다.
- [x] 적재 테이블이 재생성 가능한 ETL 보조 레이어로 정의되고 운영 테이블과 분리된다.
- [x] 이후 feature ETL이 `polygon candidate filter -> edge match -> road_segments/segment_features 반영` 순서를 따르도록 계획이 정리된다.
- [x] 생성/검증 SQL과 실패 기준이 포함된다.

## Table Design

권장 테이블명: `road_segment_filter_polygons`

권장 컬럼:

- `edgeId BIGINT PRIMARY KEY REFERENCES road_segments("edgeId") ON DELETE CASCADE`
- `sourceRowNumber INTEGER NOT NULL`
- `sourceUfid VARCHAR(34) NULL`
- `roadWidthMeter NUMERIC(8,2) NOT NULL`
- `bufferHalfWidthMeter NUMERIC(8,2) NOT NULL`
- `geom GEOMETRY(MULTIPOLYGON, 5179) NOT NULL`
- `createdAt TIMESTAMP NOT NULL DEFAULT NOW()`

권장 인덱스:

- `PRIMARY KEY (edgeId)`
- `GIST (geom)`
- 필요 시 `BTREE (sourceUfid)`

설계 원칙:

- geometry는 meter 기반 overlay 비용을 줄이기 위해 `EPSG:5179`로 저장한다.
- `geom`은 `ST_Multi(ST_Buffer(...))` 결과를 그대로 저장한다.
- 이 테이블은 `TRUNCATE + rebuild` 가능한 derived table이다.
- 운영 API나 GraphHopper import는 이 테이블을 직접 참조하지 않는다.

## Buffer Construction Rule

원천 판정:

- `N3L_A0020000_26`는 `POLYLINE`이며 polygon source가 아니다.
- `RVWD`가 전 건수에 존재하므로 centerline buffer 기반 보조 polygon 생성은 가능하다.

생성 규칙:

- 원천 geometry는 SHP를 재파싱하지 않고 **`road_segments.geom`(EPSG:4326)을 EPSG:5179로 변환한 값**을 사용한다. 이렇게 하면 edgeId ↔ SHP row 매핑 문제가 발생하지 않는다.
- RVWD는 SHP DBF에서 읽되, split으로 생기는 자식 edge는 **부모 SHP row의 RVWD를 상속**한다. 이 매핑은 `centerline_loader` extract-shp 단계에서 `edgeId → sourceUfid → RVWD` snapshot을 추가로 남겨 보장한다.
- 기본 반폭: `RVWD / 2.0`
- 최소 반폭 가드: `GREATEST(RVWD / 2.0, 1.0)`
- polygon 생성식: `ST_Multi(ST_Buffer(ST_Transform(rs.geom, 5179), GREATEST(rvwd / 2.0, 1.0), 'endcap=flat join=round'))`

보수적 해석:

- 이 polygon은 실제 도로 경계가 아니라 "해당 edge의 영향권"이다.
- 교차로, 곡선, 비대칭 폭, 중앙분리대는 정확히 표현하지 못한다.
- 따라서 downstream에서는 candidate filter로만 사용하고 최종 매칭 근거는 별도 scoring으로 남긴다.

## Implementation Plan

1. `db/schema.sql`에 `road_segment_filter_polygons` 테이블과 GIST index를 추가한다.
2. `etl/common/centerline_loader.py`의 extract-shp 단계에 `edgeId → sourceUfid → RVWD` 매핑 snapshot(`edgeId_rvwd_snapshot.csv`)을 추가한다. split으로 생긴 자식 edge는 부모 SHP row의 RVWD를 상속한다.
3. 별도 적재 단계 `load_segment_filter_polygons()`를 `etl/common/reference_loader.py`에 추가한다.
4. 적재 단계는 `road_segments.geom`을 JOIN해 `ST_Transform(geom, 5179)`로 변환한 뒤 `ST_Buffer`를 적용한다. SHP를 재파싱하지 않는다.
5. 적재 단계는 `road_segments`를 변경하지 않고 `road_segment_filter_polygons`만 `TRUNCATE/INSERT` 한다.
6. reference ETL에서 feature 입력 시 1차 후보를 `road_segment_filter_polygons`로 축소한다.
7. 후보 축소 후 기존 규칙대로 nearest segment 또는 overlap scoring으로 최종 `edgeId`를 정한다.

## Implementation Result

- 스키마 반영: `db/schema.sql`에 `road_segment_filter_polygons`와 GIST/UFID 인덱스가 추가되었다.
- 로더 반영: `etl/common/reference_loader.py`에 `load_road_segment_filter_polygons()`가 구현되었고 `etl/scripts/02_reference_load.py --stage load-road-segment-filter-polygons`로 실행 가능하다.
- 실제 적재 결과: `2026-04-24` 기준 `road_segment_filter_polygons 248,458건`, `road_segments 248,458건`으로 1:1 적재가 완료됐다.
- 매칭 결과: source SHP row `248,425건`, matched edge `248,458건`, unmatched edge `0건`, shared source row `53건`이다.
- 산출물: `runtime/etl/03-reference-load/road_segment_filter_polygons_load_report.json`, `runtime/etl/03-reference-load/post_load_validate.json`

## Reference ETL Integration Rule

후보 필터 규칙:

- point feature:
  - 1차: `ST_Intersects(point, polygon)` 또는 `ST_DWithin(point, polygon, 1.0)`
  - 2차: 남은 후보에 대해 기존 nearest segment distance 적용
- polygon feature:
  - 1차: `ST_Intersects(feature_polygon, road_segment_filter_polygons.geom)`
  - 2차: overlap ratio 또는 intersection length ranking
- linestring feature:
  - 1차: `ST_Intersects(feature_line, road_segment_filter_polygons.geom)`
  - 2차: overlap length ranking

적용 우선순위:

- `slope`, `width`, `surface`, `stairs`부터 우선 적용
- `crosswalk`, `audio_signal`, `elevator`는 기존 point matching과 비교 실험 후 확대

point filter tolerance:

- `ST_DWithin` 기준 거리는 `POINT_FILTER_TOLERANCE_M = 1.0`으로 named constant로 선언한다. 실험적으로 조정이 필요하면 이 값만 변경한다.

최종 반영 규칙:

- candidate filter에서 탈락한 row는 DB에 기록하지 않고 **JSON report count로만 남긴다**. `segment_features` 스키마 변경을 유발하지 않는다.
- 최종 truth update는 계속 `road_segments`와 `segment_features`에만 반영한다.

## Validation Plan

스키마 검증:

- 테이블 생성 성공
- `geom` SRID = 5179
- `edgeId` unique = row count
- invalid geometry count = 0

정합성 검증:

- `road_segment_filter_polygons` row count == `road_segments` row count
- `road_segment_filter_polygons.edgeId` orphan count = 0
- `roadWidthMeter <= 0` row count = 0

품질 검증:

- 다음 SQL로 `roadWidthMeter`와 polygon 면적 간 상관계수를 확인한다. 기대값 0.9 이상:
  ```sql
  SELECT corr("roadWidthMeter", ST_Area(geom)) FROM road_segment_filter_polygons;
  ```
- sample 20건에서 polygon bbox가 중심선을 포함하는지 확인
- 해운대 subset에서 기존 unmatched feature가 후보군에 들어오는지 비교
- 기존 matched feature가 대량으로 탈락하지 않는지 compare report 생성

필수 리포트:

- `runtime/etl/03-reference-load/road_segment_filter_polygon_load_report.json`
- `runtime/etl/03-reference-load/road_segment_filter_polygon_compare_report.json`

## Risks

- `edgeId` ↔ SHP row 매핑 문제 → **해소**: `road_segments.geom` 직접 사용으로 SHP row 재매핑 불필요.
- `RVWD` 해석이 실제 보도 폭이 아니라 전체 도로 폭일 수 있어 candidate 영역이 과대해질 수 있다.
- 인접 도로 polygon이 겹치면 후보가 과다 생성될 수 있다.
- 1m tolerance 상수화 → **해소**: `POINT_FILTER_TOLERANCE_M = 1.0`으로 선언.

## Open Questions

- `RVWD`를 전체 도로 폭으로 볼지, 보행 가능한 유효 폭의 근사치로 볼지 확정이 필요하다.
- `crosswalk`, `audio_signal`, `elevator`까지 이 filter를 강제 적용할지, polygon source 위주 feature에만 먼저 적용할지 결정이 필요하다.

## Handoff

- 구현 handoff: `start` 또는 `implement-feature`
- 검증 handoff: `check`
- 전제: `road_segments` canonical contract는 유지하고, 새 테이블은 ETL-derived helper layer로만 취급한다.
