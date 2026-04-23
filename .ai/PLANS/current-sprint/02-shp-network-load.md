# 02 SHP 네트워크 스키마 및 DB 적재

## 워크스트림

`SHP 기반 보행 네트워크 DB 적재`

## 목표

`etl/raw/N3L_A0020000_26.shp` 기반으로 보행 네트워크 스키마를 정리하고, 파이프라인 산출물 생성에서 멈추지 않고 `road_nodes`, `road_segments`를 실제 PostGIS DB에 적재한다. 적재 후에는 DB 기반 검증과 HTML 지도 시각화로 node/edge 결과를 확인할 수 있게 만든다.

## 범위

- 공식 도로 중심선 SHP를 PostGIS 정규 그래프 테이블로 적재
- OSM natural key 의존 제거
- SHP 종단점 기반 결정적 노드 식별 생성
- preflight, extract, topology audit, DB load, post-load validation, HTML visualization 단계 분리
- 후속 워크스트림의 기준 키를 `edgeId`로 고정

## 비목표

- CSV 접근성 ETL 구현
- GraphHopper import 구현
- SHP와 OSM을 적재 시점에 혼합하는 하이브리드 로직
- 최종 보행 가능성 판정 규칙 완성

## 입력 근거

- `etl/raw/N3L_A0020000_26.shp`
- `etl/raw/N3L_A0020000_26.shx`
- `etl/raw/N3L_A0020000_26.dbf`
- `etl/raw/N3L_A0020000_26.prj`
- `db/schema.sql`
- `docs/erd.md`
- `docs/erd_v2.md`
- `.ai/PLANS/current-sprint/03-csv-etl-and-reference-data.md`

## 성공 기준

- [x] `N3L_A0020000_26`을 `road_segments`의 정규 네트워크 소스로 고정한다.
- [x] OSM 전용 식별 컬럼을 소스 비종속 스키마로 대체한다.
- [x] SHP에서 `road_nodes`, `road_segments`를 결정적으로 파생하는 규칙을 정의한다.
- [x] `road_nodes`, `road_segments`를 PostGIS DB에 실제 적재한다.
- [x] topology audit, DB load, post-load validation을 명시적 단계로 분리한다.
- [x] DB에 적재된 node/edge를 지도 위에 그리는 HTML 결과물을 생성한다.
- [x] 후속 워크스트림은 `edgeId` 중심 핸드오프를 사용한다.

## 주요 설계 결정

- 워크스트림 `02`의 정규 네트워크 소스는 `busan.osm.pbf`가 아니라 `N3L_A0020000_26` SHP다.
- 기존 OSM 식별자 조합과 SHP 원본 feature ID는 더 이상 정규 키가 아니다.
  - 기존: `(sourceWayId, sourceOsmFromNodeId, sourceOsmToNodeId, segmentOrdinal)`
  - 신규: `edgeId`
- `road_nodes`의 정체성은 OSM node id가 아니라 정규화된 SHP 좌표에서 파생한다.
- `road_segments`의 정체성은 SHP `UFID`가 아니라 `edgeId`로 관리한다. 이번 POC에서는 `N3L_A0020000_26`을 고정 기준 네트워크로 보고 반복 재적재를 전제로 하지 않는다.
- `walkAccess`는 적재 시점에 `UNKNOWN`으로 유지하고, 후속 보강 단계가 별도로 판단한다.
- topology audit는 라인 적재와 분리된 독립 단계로 유지한다.

## 구현 계획

- [x] `db/schema.sql`의 보행 네트워크 테이블을 SHP 우선 구조로 정리한다.
  - `road_nodes.source_node_key`를 필수로 만든다.
  - `road_segments`에서는 OSM 전용 source 컬럼과 SHP `source_feature_id` 컬럼을 두지 않는다.
  - `edgeId`를 정규 간선 PK로 사용한다.
- [x] `etl/common/centerline_loader.py`를 추가한다.
  - SHP sidecar 파일 검증
  - `EPSG:5179` CRS 검증
  - `cp949 -> euc-kr -> utf-8` 순서의 인코딩 fallback
  - 결정적 endpoint key 생성과 고정 SHP 순서 기반 `vertexId` 생성
  - snapshot CSV와 topology audit 산출물 생성
  - PostGIS `road_nodes`, `road_segments` 적재 흐름
- [x] `etl/scripts/01_centerline_load.py`를 추가한다.
  - `preflight`, `extract-shp`, `topology-audit`, `load-db`, `post-load-validate`, `visualize-html`, `full` 단계 제공
  - snapshot CSV가 있으면 `load-db` 단계에서 SHP 재파싱 없이 적재 가능
  - `load-db`는 `road_nodes`와 `road_segments`에 insert하고, 적재된 DB count를 리포트로 남긴다.
  - `post-load-validate`는 DB에 적재된 값 기준으로 orphan edge, invalid geometry, SRID, length, count를 검증한다.
  - `visualize-html`은 DB에서 `road_nodes`와 `road_segments`를 조회해 Leaflet 기반 HTML 지도를 생성한다.
- [x] `etl/scripts/01_osm_load.py`를 정규 진입점에서 제외한다.
  - `01_centerline_load.py`가 정규 로더라는 메시지만 출력하도록 한다.
- [x] 핸드오프 문서를 갱신한다.
  - `docs/erd.md`
  - `docs/erd_v2.md`
  - `.ai/PLANS/current-sprint/03-csv-etl-and-reference-data.md`

## 구현 결과

- 정규 로더: `etl/scripts/01_centerline_load.py`
- 공통 구현: `etl/common/centerline_loader.py`, `etl/common/db.py`
- 단위 테스트: `etl/tests/test_db.py`, `etl/tests/test_centerline_loader.py`
- 생성 노드 수: `229,129`
- 생성 세그먼트 수: `248,458`
- topology audit: duplicate edge `0`, orphan edge `0`, invalid length `0`, connected components `1,241`
- DB post-load validation: orphan edge `0`, invalid geometry `0`, invalid SRID `0`, invalid length `0`, duplicate edgeId `0`
- HTML preview: `runtime/etl/centerline-load/road_network_preview.html`

## 예정 산출물

- 산출물 디렉터리: `runtime/etl/centerline-load/`
- 주요 산출물:
  - `centerline_snapshot.json`
  - `centerline_topology_audit.json`
  - `road_nodes_snapshot.csv`
  - `road_segments_snapshot.csv`
  - `road_network_post_load_report.json`
  - `road_network_preview.geojson`
  - `road_network_preview.html`

## DB 적재 계약

- `load-db` 단계는 `db/schema.sql`이 적용된 PostGIS DB를 대상으로 한다.
- 적재 대상은 `road_nodes`, `road_segments` 두 테이블이다.
- `road_nodes.vertexId`는 endpoint 기반 노드 식별자이며 `road_segments.fromNodeId`, `road_segments.toNodeId`가 이를 참조한다.
- `road_segments.edgeId`는 정규 간선 PK이며 후속 CSV ETL, GraphHopper import, HTML 검증의 공통 기준이다.
- `load-db` 완료 후에는 반드시 `post-load-validate`를 실행해 DB에 실제로 적재됐는지 검증한다.

## HTML 시각화 계약

- HTML 시각화는 snapshot 파일이 아니라 DB에 적재된 `road_nodes`, `road_segments`를 조회해 만든다.
- 기본 산출물은 `runtime/etl/centerline-load/road_network_preview.html`이다.
- HTML에는 최소한 다음 레이어가 있어야 한다.
  - `road_segments` edge line layer
  - `road_nodes` node point layer
  - edge/node count summary
  - invalid/orphan 검증 요약
- 부산 전체 데이터가 너무 무거우면 bbox 또는 sample limit 옵션을 제공하되, HTML에 적용된 bbox/limit을 명시한다.

## 검증 계획

- [x] `python -m compileall etl`을 실행한다.
- [x] `python -s -m pytest etl/tests/test_db.py etl/tests/test_centerline_loader.py -q`를 실행한다.
- [x] `python etl/scripts/01_centerline_load.py --stage preflight`로 SHP sidecar, CRS, DBF 인코딩, 원본 레코드 수를 확인한다.
- [x] `python etl/scripts/01_centerline_load.py --stage extract-shp`로 snapshot 산출물을 생성한다.
- [x] `python etl/scripts/01_centerline_load.py --stage topology-audit`로 파생 세그먼트, 파생 노드, invalid geometry, 중복 edge identity, orphan endpoint, connected component를 확인한다.
- [x] `python etl/scripts/01_centerline_load.py --stage load-db`로 `road_nodes`, `road_segments`에 실제 적재한다.
- [x] `python etl/scripts/01_centerline_load.py --stage post-load-validate`로 DB count, FK orphan, invalid geometry, SRID, length 값, duplicate edge key를 검증한다.
- [x] `python etl/scripts/01_centerline_load.py --stage visualize-html`로 DB 기반 HTML 지도를 생성한다.
- [x] 생성된 HTML에서 edge line과 node point가 지도 위에 표시되는지 확인한다.
- [x] `python etl/scripts/01_centerline_load.py --stage full`이 `preflight -> extract-shp -> topology-audit -> load-db -> post-load-validate -> visualize-html` 전체 순서를 실행하는지 확인한다.

검증 메모: user-site의 `pytest 8.4.2`가 현재 로컬에서 출력 없이 종료되어, 검증은 Anaconda 기본 pytest 경로를 쓰는 `python3 -s -m pytest ...`로 수행했다. 결과는 `12 passed`다.

## 위험 및 열린 질문

- `N3L_A0020000_26`은 보도 전용이 아니라 도로 중심선 데이터다.
- `RDDV`, `DVYN`, `ONSD` 값은 현재 trace용 참고 정보이며, 직접적인 라우팅 규칙은 아니다.
- 연결 컴포넌트와 near-miss endpoint 수치를 보면 라우팅 품질 개선은 `04`에서 계속 다뤄야 한다.
- `03`의 실제 접근성 CSV와 `edgeId` 기반 공간 매칭 검증은 다음 워크스트림 과제로 남아 있다.

## 의존성

- PostGIS가 활성화된 로컬 DB
- `.env`의 DB 연결 정보

## 핸드오프

- Build skill: `implement-feature`
- Validation skill: `check`
- Ship readiness note: 정규 네트워크 적재와 `edgeId` 중심 핸드오프가 확정되면, 후속 워크스트림은 이 기준을 깨지 않고 보강만 수행해야 한다.
