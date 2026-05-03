# Current Sprint

## Goal

최신 `docs/prd.md`, `docs/기능명세서.md`, `docs/erd.md`, `docs/erd_v2.md`와 현재 저장소 상태만으로 부산이음길 MVP POC를 구현 가능한 수준의 실행 계획으로 정리한다. 이번 스프린트는 `docs/plans/` 없이도 진행 가능해야 하며, 기존 `busan.osm.pbf` 선적재 대신 국토교통부 SHP 도로 중심선을 기준 네트워크로 재정의한 뒤 `etl/raw`의 CSV와 정적 대중교통 참조 데이터로 접근성·시설·대중교통 참조 데이터를 보강하고, 그 결과를 GraphHopper와 Spring Boot API에 연결하는 순서로 진행한다.

## Request Mode

- Primary mode: spec-driven planning from canonical `docs/`
- Secondary inputs: current repository state, `.env`, `poc/`, `etl/raw/`
- Planning rule: `docs/plans/`를 제거해도 구현이 가능하도록 현재 계획은 canonical source 없이 독립적으로 읽혀야 한다

## Structured State

- Narrative plan: this file
- Machine-readable progress: `.ai/PLANS/progress.json`
- Quality and readiness metrics: `.ai/EVALS/metrics.json`
- Workstream subplans: `.ai/PLANS/current-sprint/`

## Checklist Status Rule

- `[ ]` not started
- `[~]` in progress
- `[x]` completed successfully
- `[!]` blocked, risky, or requires strategy change

## Planning Inputs

- Product specs: `docs/prd.md`, `docs/기능명세서.md`
- Data and schema spec: `docs/erd.md`
- Current environment and code:
  - `.env`
  - `poc/`
  - `etl/raw/N3L_A0020000_26.shp`
  - `etl/raw/N3L_A0020000_26.shx`
  - `etl/raw/N3L_A0020000_26.dbf`
  - `etl/raw/N3L_A0020000_26.prj`
  - `etl/raw/place_merged_broad_category_final.csv`
  - `etl/raw/place_accessibility_features_merged_final.csv`
  - `etl/raw/stg_audio_signals_ready.csv`
  - `etl/raw/stg_crosswalks_ready.csv`
  - `etl/raw/slope_analysis_staging.csv`
  - `etl/raw/subway_station_elevators_erd_ready.csv`

## Cross-Validation Notes

- PRD의 기술 스택에는 `MySQL`, `Kotlin/Jetpack`, `RabbitMQ`가 적혀 있지만, 최신 ERD는 `GEOMETRY`, `JSONB`, PostGIS 친화 스키마를 전제로 한다. 이번 계획은 최신 ERD와 실제 원시 데이터 형식을 우선하여 `PostgreSQL + PostGIS`를 기준으로 잡는다.
- PRD와 기능명세서는 local-first를 강조하므로, 로그인 기반 사용자 기능은 MVP POC의 핵심 경로가 아니다. `users`, `bookmarks`, `favorite_routes`, 제보/경로 로그 계열 테이블은 ERD에는 남기되 이번 초기 `db/schema.sql` 생성 대상에서는 제외한다.
- 최신 ERD는 저상버스 예약 API를 만들지 않고 외부 화면 연동을 전제로 한다. 따라서 MVP의 대중교통 구현은 `low_floor_bus_routes` 적재와 경로 후보 필터링에 집중한다.
- `subway_station_elevators_erd_ready.csv`는 ERD와 동일한 6개 컬럼(`elevatorId`, `stationId`, `stationName`, `lineName`, `entranceNo`, `point`)을 기대 입력으로 둔다. 실제 row 수, 결측, 중복은 구현 전 검증 단계에서 확인한다.
- 같은 `stationId + entranceNo + point` 조합의 중복 레코드가 일부 존재하므로, ETL은 raw row를 그대로 적재하기보다 중복 제거 또는 사전 검증 단계를 포함해야 한다.
- `lineName` 값은 현재 `1`, `2`, `3`, `4`만 존재하므로 이번 MVP 엘리베이터 범위는 부산 도시철도 1~4호선 기준으로 명시한다. 동해선, 부산김해경전철까지 보장하는 계획은 현재 데이터셋만으로는 세우지 않는다.
- `slope_analysis_staging.csv`는 세그먼트 수준 결과가 아니라 폴리곤 기반 staging 성격이 강하므로, `road_segments`와의 공간 매칭 단계가 ETL 핵심이다. 좌표계는 EPSG:5179(한국 TM)와 WGS84 두 컬럼이 모두 제공되며, ETL은 반드시 `geometry_wkt_4326` 컬럼을 사용해야 한다. `avgSlopePercent` 소스 컬럼은 `metric_mean`이다.
- 자동화는 MVP V2로 미루고, 이번 스프린트는 수동 실행 가능하고 재실행 안전한 ETL과 구현 순서 정리에 집중한다.

## Success Criteria

- [ ] `docs/plans/` 없이도 어떤 순서로 구현할지 `.ai/PLANS`만 보고 따라갈 수 있다.
- [x] SHP 기반 네트워크 적재 후 CSV/BIMS 기반 보강 적재 순서와 책임 테이블이 명확하다.
- [x] `etl/raw` 각 파일이 어떤 테이블과 컬럼을 채우는지, 그리고 point/polygon이 기존 `road_segments.geom`에 어떻게 매칭되는지 계획에 명시되어 있다.
- [ ] GraphHopper import 시 custom encoded value와 4개 custom model을 추가하는 구현 방향이 정리되어 있다.
- [ ] 데이터셋이 아직 완전하지 않은 POC 상태를 고려한 유연한 기준과, 원래 엄격한 기준을 주석으로 유지하는 전략이 반영되어 있다.
- [ ] 현재 `poc/` 기반 Spring Boot 구조에서 구현해야 할 API와 검증 흐름이 단계화되어 있다.

## Workstream Index

- [x] [01-setup-and-repo-alignment.md](.ai/PLANS/current-sprint/01-setup-and-repo-alignment.md)
- [x] [02-shp-network-load.md](.ai/PLANS/current-sprint/02-shp-network-load.md)
- [x] [03-csv-etl-and-reference-data.md](.ai/PLANS/current-sprint/03-csv-etl-and-reference-data.md)
- [x] [03a-road-buffer-filter-layer.md](.ai/PLANS/current-sprint/03a-road-buffer-filter-layer.md)
- [ ] [04-graphhopper-routing-profiles.md](.ai/PLANS/current-sprint/04-graphhopper-routing-profiles.md)
- [ ] [04-graphhopper-routing-profiles_v2.md](.ai/PLANS/current-sprint/04-graphhopper-routing-profiles_v2.md)
- [ ] [05-backend-api-and-orchestration.md](.ai/PLANS/current-sprint/05-backend-api-and-orchestration.md)
- [ ] [06-validation-demo-and-v2-boundary.md](.ai/PLANS/current-sprint/06-validation-demo-and-v2-boundary.md)
- [ ] [07-graphhopper-common-flow.md](.ai/PLANS/current-sprint/07-graphhopper-common-flow.md)

Planning guard for real service: all downstream ETL, GraphHopper import, and verification flows must use the same canonical `edgeId` handoff contract. The network load stage should stay split as `preflight -> extract -> topology-audit -> load-db -> post-load-validate -> visualize-html` so schema drift, graph connectivity defects, or empty DB loads fail before downstream work starts.

## Ordered Delivery Plan

1. `01`에서 저장소 구조, DB 선택, 실행 경로를 고정한다.
2. `02`에서 PostGIS 스키마를 source-agnostic 형태로 바꾸고 `N3L_A0020000_26` SHP를 `road_nodes`, `road_segments`에 적재한다.
3. `03`에서 CSV와 정적 대중교통 참조 데이터로 `places`, `place_accessibility_features`, `road_segments`, `segment_features`, `subway_station_elevators`, `low_floor_bus_routes`를 보강 적재한다.
4. `04`에서 GraphHopper import, custom encoded values, 4개 custom model과 분기 로직을 구현한다.
   - 대안 경로: `04-graphhopper-routing-profiles_v2.md`는 `road_segments direct graph import` 기반 재설계안이다.
5. `05`에서 Spring Boot API와 대중교통 오케스트레이션을 붙인다.
6. `06`에서 POC 검증 흐름, smoke, 시연 범위와 V2 경계를 정리한다.

## Think

- [ ] MVP POC의 핵심은 `경로 탐색`, `시설 조회`, `접근성 데이터 적재`, `저상버스/역 엘리베이터 참조 데이터`로 고정한다.
- [ ] 사용자 유형은 `VISUAL`, `MOBILITY` 두 축으로 고정한다.
- [ ] 경로 옵션은 `SAFE_WALK`, `FAST_WALK`, `ACCESSIBLE_TRANSIT`으로 고정한다.
- [ ] 운영 자동화와 완전한 계정 기능은 V2로 분리한다.

## Plan

- [ ] PostGIS 중심 스키마와 current repo 구조를 정렬한다.
- [ ] ETL을 `SHP 네트워크 적재 -> CSV/BIMS 보강 적재 -> GraphHopper import` 순서로 정의한다.
- [ ] 데이터 부족 상태에서는 유연한 POC 기준을 적용하고, 원래 엄격 기준은 주석으로 남기는 전략을 확정한다.
- [ ] API와 검증 시나리오를 구현 순서에 맞춰 끊는다.

## Build

- [x] DB 스키마와 SHP 네트워크 적재기를 구현한다.
- [x] CSV 기반 보강 ETL을 구현한다.
- [ ] GraphHopper 플러그인과 custom model을 구현한다.
- [ ] Spring Boot API와 검증용 UI 또는 시연 흐름을 구현한다.

## Review

- [ ] 최신 ERD와 실제 적재 대상 컬럼 사이 불일치를 점검한다.
- [ ] 공간 매칭 ETL이 과도하게 추정에 의존하지 않는지 점검한다.
- [ ] GraphHopper 분기 기준이 현재 데이터 가용성에 맞는지 점검한다.

## Test

- [x] 문서 변경 후 `scripts/verify.sh`를 통과한다.
- [ ] SHP 네트워크 적재, CSV 적재, GraphHopper import, API 호출 순서의 smoke를 정의한다.
- [ ] 휠체어 경로, 시각장애 경로, 시설 조회, 저상버스 필터링의 핵심 시나리오를 검증한다.

## Ship

- [ ] 로컬 실행 순서를 runbook 수준으로 정리한다.
- [ ] 시연용 최소 데이터 범위와 실패 시 대체 경로를 정리한다.

## Reflect

- [ ] 반복 보정이 필요한 공간 매칭 규칙은 `.ai/MEMORY/` 또는 `.ai/EVALS/`로 승격한다.
- [ ] V2로 미뤄진 자동화와 운영 기능은 backlog로 격리한다.

## Risks and Open Questions

- [ ] `subway_station_elevators_erd_ready.csv`의 실제 헤더와 중복 규칙이 적재 계획에 반영된다.
- [ ] `slope_analysis_staging.csv`는 용량이 크고 폴리곤 기반이라 공간 조인 비용이 높을 수 있다.
- [ ] `stg_audio_signals_ready.csv`, `stg_crosswalks_ready.csv`는 포인트 feature라 `road_segments` 업데이트 기준 반경과 우선순위가 필요하다.
- [ ] PRD의 플랫폼 기술 서술과 현재 저장소 구현 상태가 다르므로, MVP POC는 현재 리포 기준 웹/API 우선 검증이 현실적이다.
- [ ] `place_merged_final.csv`와 `place_merged_broad_category_final.csv` 두 파일이 `etl/data/raw/`에 모두 존재하며 헤더가 동일하다. 실제 행 수를 비교해 `place_merged_broad_category_final.csv`로 단일화 여부를 확인해야 한다.
- [ ] `poc/build.gradle`에 Hibernate Spatial이 없으므로 GEOMETRY 컬럼을 JPA 엔티티로 매핑하려면 의존성 추가가 필수다.
- [ ] PostGIS와 GH 컨테이너 설정은 현재 저장소의 `docker-compose.yml`을 기준으로 검증한다.
- [ ] GraphHopper custom encoded value는 Java SPI 플러그인을 별도 모듈(`graphhopper-plugin/`)로 작성해야 한다. 이 모듈은 현재 `poc/`에 없다.

## Implementation Notes

- [x] 2026-04-28: `pedestrian_road_extraction_criteria_v2.md`의 도로면 boundary 방식에 맞춰 강서구 v4 편집 산출물을 추가했다.
  - Outputs: `etl/gangseo_road_boundary_v4.geojson`, `etl/gangseo_road_boundary_v4.html`, `etl/gangseo_road_nodes_v4.csv`, `etl/gangseo_road_segments_v4.csv`.
  - CSV adapter rule: v2 GeoJSON source keeps `roadNodes` empty, then `etl/scripts/17_export_road_boundary_csv.py` creates endpoint nodes only for the manual edit UI contract.
  - UI: `etl/noksan_sinho_songjeong_hwajeon_segment_02c_graph_edit.html` now exposes a district selector, loads the Gangseo node/segment payload, and keeps Add/Delete node/segment plus Undo, Save JSON, Edit CSV, Copy JSON, Clear controls.
  - Correction: the full Gangseo payload made the editor too heavy on initial page load, so the editor now ships a lightweight Gangseo base shell and fetches only the selected 동 subset from `/api/segment-02c/payload?dong=...`. Available default selector values are `명지동`, `신호동`, `녹산동`, `화전동`; the default is `신호동`.
  - Editor correction: manual add/undo/clear now redraws only the current viewport instead of fitting all features again, so the map zoom and pan stay in place while the side-panel edit list grows. The new-segment type selector is limited to `SIDE_LINE` and `SIDE_WALK`; existing `ROAD_BOUNDARY`/`ROAD_BOUNDARY_INNER` source segments still render normally.
  - Sinho preview: `etl/scripts/19_generate_sinho_corner_node_preview.py` creates a read-only 신호동 result HTML that promotes endpoints and visible corner vertices to nodes, then splits source road-boundary lines at those nodes. This preview does not overwrite the v4 CSVs.
  - Gangseo v5: `etl/scripts/20_generate_gangseo_corner_split_v5_csv.py` regenerates Gangseo CSVs as `gangseo_road_nodes_v5.csv` and `gangseo_road_segments_v5.csv` by applying the same corner-node split rule to the full v4 road-boundary graph. The edit server now defaults to v5 CSVs.
  - Gangseo v6: `gangseo_road_nodes_v6.csv` and `gangseo_road_segments_v6.csv` merge the current v5 graph with replacement bbox slices for 강동동, 대저1동, 대저2동, and 공항동 from the `(1)` v5 CSVs. The edit server now defaults to v6 CSVs so `Edit CSV` mutates v6.
  - Editor correction: delete mode now exposes `Drag` and `Delete all` controls beside `Reload bbox`; clicking exactly 4 polygon vertices records delete edits for all segments intersecting the polygon and all nodes inside the polygon before the user applies them with `Edit CSV`.
  - Editor coverage: the Gangseo selector now includes the full v5 CSV extent plus additional Gangseo bbox work areas beyond the original four: 송정동, 미음동, 지사동, 생곡동, 범방동, 구랑동, 가락동, 강동동, 대저1동, 대저2동, 공항동, 가덕도동.
  - Validation: `python -m pytest etl/tests/test_segment_centerline_02c.py etl/tests/test_segment_graph_edit_ui.py etl/tests/test_road_boundary_csv_export.py etl/tests/test_district_road_boundary_from_polygons.py -q` passed; `scripts/verify.sh` passed.
  - Accepted risk: direct full-radius `etl.scripts.13_generate_segment_02c_centerline --variant road-boundary` for Gangseo timed out in the large union stage, so v4 generation used the prepared `poc_submit` Gangseo road-polygon asset as the road-surface input before union and boundary extraction. Retry was recorded as `gangseo-road-boundary-v2-radius-18000-union-timeout`.
- [x] 2026-05-02: 4개 동 graph 편집 UI를 신호동 connector 검수 레이어와 통합했다.
  - UI: `etl/noksan_sinho_songjeong_hwajeon_segment_02c_graph_edit.html` now removes the dong selector and loads a combined `신호동/녹산동/명지동/화전동` payload by default.
  - Connector overlay: the top toolbar now includes layer toggles for 기존 segment, 0-12m connector, 12-20m connector, split connector, and proposed bridge; 4개 동 v7 preview candidates live in `runtime/graphhopper/topology/gangseo_four_dong_v7_connectivity_analysis_with_bridges.json`.
  - API: `etl/scripts/27_serve_gangseo_connector_editor.py` now serves both connector JSON API and `/api/segment-02c/payload?dong=gangseo_four` plus `/api/segment-02c/apply-edits` from CSV without requiring DB dependencies.
  - Preview state: v7 source remains untouched; current server is pointed at `gangseo_four_dong_road_segments_v7_preview.csv` / `gangseo_four_dong_road_nodes_v7_preview.csv` for map verification.
  - Validation: `python3 -m py_compile etl/scripts/27_serve_gangseo_connector_editor.py`, HTML script `node --check`, and API smoke passed with 3,242 visible connector candidates: orange 157, red 77, yellow 2,915, blue bridge 93.
- [x] 2026-05-03: 4개 동 v7 원본에 0-12m connector와 split connector를 반영하고, 남은 검수 후보를 재계산했다.
  - Applied to source CSV: `etl/raw/gangseo_road_segments_v7.csv` and `etl/raw/gangseo_road_nodes_v7.csv`.
  - Backup before apply: `runtime/graphhopper/topology/backups/gangseo_road_segments_v7_before_0_12_split_20260503.csv` and `runtime/graphhopper/topology/backups/gangseo_road_nodes_v7_before_0_12_split_20260503.csv`.
  - Scope control: only the 4-dong slice was replaced in v7; non-slice Gangseo rows were preserved instead of running global cleanup over the whole CSV.
  - Applied candidates: 157 orange 0-12m endpoint connectors, 2,915 split candidates, and prerequisite node merges. Excluded red 12-20m connectors and proposed bridges.
  - Current review overlay: `runtime/graphhopper/topology/gangseo_four_dong_v7_after_0_12_split_review_overlay_analysis.json` shows only 9 red 12-20m connectors and 103 blue proposed bridges.
  - Validation: merged v7 validation passed with 46,713 segments, 48,911 nodes, and no bad references, bad geometries, duplicate edge IDs, self-loops, isolated nodes, or enum violations.
- [x] 2026-05-03: 4개 동 검수 편집기를 bbox 기준보다 1km 확장한 proposed-bridge-only 프리뷰로 전환했다.
  - Preview scope: `gangseo_four_dong_plus1km_road_segments_v7_after_0_12_split.csv` and `gangseo_four_dong_plus1km_road_nodes_v7_after_0_12_split.csv` contain the current v7 graph after 0-12m/split application, clipped by each target dong bbox plus roughly 1km.
  - Connector overlay: `gangseo_four_dong_plus1km_v7_after_0_12_split_bridge_only_analysis.json` intentionally clears orange/red/yellow connector candidates and displays only blue proposed bridges.
  - Current counts: expanded preview has 15,532 segments, 14,102 nodes, 648 components, and 647 proposed bridge candidates.
  - Server mode: `GANGSEO_GRAPH_BBOX_BUFFER_METER=1000` keeps `/api/segment-02c/payload?dong=gangseo_four` aligned with the expanded preview instead of the original tight dong bboxes.
- [x] 2026-05-03: `Edit CSV` 후 지도와 proposed bridge를 즉시 재계산하도록 편집 서버를 갱신했다.
  - API behavior: `/api/segment-02c/apply-edits` now applies the manual edits, rebuilds connectivity, replaces the in-memory proposed bridge overlay, and returns the recalculated summary in the same response.
  - UI behavior: the editor now reloads the current graph payload and connector candidates after `Edit CSV` instead of depending on a full page refresh.
  - Performance: `bridge_remaining_components.py` now uses an STRtree lookup for nearest-main-segment bridge generation so repeated review cycles complete interactively on the 1km expanded four-dong slice.
- [x] 2026-05-03: 수정된 v7 기반 4동+1km live slice에 0-12m/split/node-merge를 재적용하고 1km 이내 proposed bridge만 표시했다.
  - Input state: current live slice had 14,668 segments, 13,253 nodes, and 539 components after prior manual edits.
  - Applied candidates: 127 orange 0-12m endpoint connectors, 102 split candidates, and 240 prerequisite node merges; red 12-20m connectors remained excluded.
  - Output state: `gangseo_four_dong_plus1km_current_v7_live_0_12_split_segments.csv` / `...nodes.csv` validate with 14,839 segments, 12,932 nodes, and 197 components.
  - Bridge display: `GANGSEO_BRIDGE_MAX_DISTANCE_METER=1000` limits the proposed bridge overlay to 148 blue candidates within 1km of the main component.
- [x] 2026-05-03: `Edit CSV` apply flow now automatically runs 0-12m/split/node-merge before reconnecting proposed bridges.
  - Apply order: manual edits are written to the active CSV, then the server analyzes the edited graph, applies orange 0-12m connectors, split connectors, and prerequisite node merges, excludes red 12-20m connectors, and finally rebuilds the 1km-limited proposed bridge overlay.
  - UI feedback: the editor toast reports auto connector, split, and merge counts before reloading the updated map and bridge candidates.
  - Current refreshed state after one endpoint-driven auto pass: 14,840 segments, 12,796 nodes, 102 components, and 97 proposed bridge candidates within 1km.
- [x] 2026-05-03: 4동+1km live editor graph reached the current bridge-review terminal state.
  - Current API state: 14,855 segments, 12,648 nodes, 2 components, 903 endpoints, and 0 proposed bridge candidates within 1km.
  - Interpretation: the editor showing bridge count 0 is expected for the current active CSV state; the remaining non-main component does not generate a bridge candidate under the current 1km bridge rule.
  - Reproduction notes: `.ai/MEMORY/gangseo-connectivity-preprocessing.md` records the source/runtime files, editor server command, and future-session prompt for this preprocessing flow.
- [x] 2026-05-03: 4동+1km live editor graph를 강서구 전체 v7 원본의 나머지 구역과 병합해 v8 CSV를 생성했다.
  - Outputs: `etl/raw/gangseo_road_segments_v8.csv`, `etl/raw/gangseo_road_nodes_v8.csv`, `runtime/graphhopper/topology/gangseo_v8_merge_report.json`, and `runtime/graphhopper/topology/gangseo_v8_validate_report.json`.
  - Merge rule: full v7에서 live slice edgeId와 겹치거나 4동+1km expanded bbox에 걸리는 segment를 제거하고, live slice를 우선 삽입했다. Node CSV는 최종 segment 참조 기준으로 재구성했고 duplicate `vertexId`는 live row를 우선했다.
  - V8 validation: 46,036 segments, 47,489 nodes, 5,152 connected components, and no bad references, bad geometries, endpoint mismatches, duplicate IDs, self-loops, enum violations, or isolated nodes.
  - Accepted existing condition: duplicate node-pair edges remain 471, down from 493 in full v7; this is pre-existing full-Gangseo reverse/parallel edge cleanup outside the 4동 connector scope.
- [x] 2026-05-03: 4동+1km 범위는 v7 원본을 유지하고 나머지 강서구 범위는 `v8_eungseo` 데이터셋으로 교체한 새 v8 기준 CSV를 생성했다.
  - Outputs: `etl/raw/gangseo_road_segments_v8.csv`, `etl/raw/gangseo_road_nodes_v8.csv`, `runtime/graphhopper/topology/gangseo_v8_v7_scope_eungseo_remainder_merge_report.json`, and `runtime/graphhopper/topology/gangseo_v8_v7_scope_eungseo_remainder_validate_report.json`.
  - Merge rule: `gangseo_road_segments_v7.csv`에서 신호동/녹산동/화전동/명지동 expanded bbox(1km)를 포함하는 segment 15,532개를 선택하고, `gangseo_road_segments_v8_eungseo.csv`에서는 같은 범위와 겹치지 않는 segment 32,241개를 선택했다.
  - Schema policy: output은 v7 node/segment 컬럼을 기준으로 고정했고, eungseo-only 컬럼(`rampState`, `elevatorState`, `crossingState`)은 적재하지 않았다. eungseo의 `ROAD_BOUNDARY` 계열 segmentType은 downstream enum에 맞춰 `SIDE_LINE`으로 정규화했다.
  - Validation: 47,772 segments, 50,430 nodes, 6,238 connected components, and no bad references, bad geometries, endpoint mismatches, duplicate IDs, self-loops, enum violations, or isolated nodes.
  - Next target: 4동+1km 바깥의 eungseo 기반 remainder graph에서 component 수를 줄이는 connector 작업을 진행한다.
- [x] 2026-05-03: 강서구 전체 v8 graph에 0-12m/split/prerequisite node merge connector 전처리를 적용하고 v9 CSV를 생성했다.
  - Outputs: `etl/raw/gangseo_road_segments_v9.csv`, `etl/raw/gangseo_road_nodes_v9.csv`, `runtime/graphhopper/topology/gangseo_all_v8_final_merge_report.json`, and `runtime/graphhopper/topology/gangseo_all_v8_final_validate_report.json`.
  - Scope: v8 전체를 presliced 작업 대상으로 사용해 기존 4동+1km 내부 연결뿐 아니라 다른 동과의 접점까지 같은 connector review flow에서 다룬다.
  - Applied candidates: 2,091 orange 0-12m endpoint connectors, 1,638 split candidates, and 2,431 prerequisite node merges; red 12-20m connectors and proposed bridges were not auto-applied.
  - Result: 47,772 segments / 50,430 nodes / 6,238 components became 50,525 segments / 48,054 nodes / 2,036 components after auto preprocessing.
  - Bridge review: `runtime/graphhopper/topology/gangseo_all_v8_0_12_split_bridge_only_analysis.json` keeps only 1,062 proposed bridge candidates within 1km for manual review.
  - Validation: v9 passes graph validation with no bad references, bad geometries, endpoint mismatches, duplicate IDs, self-loops, enum violations, or isolated nodes; duplicate node-pair edges remain 29.
- [x] 2026-05-03: 강서구 전체 connector editor를 동별 +1km 검수 모드로 전환했다.
  - UI: `etl/noksan_sinho_songjeong_hwajeon_segment_02c_graph_edit.html` now has a scope selector for `강서구 전체` and each Gangseo dong, defaulting to `명지동` to avoid loading the full graph on first open.
  - API: `etl/scripts/27_serve_gangseo_connector_editor.py` now serves `/api/segment-02c/payload?dong=<id>` from the live graph CSV using the selected dong bbox plus `GANGSEO_GRAPH_BBOX_BUFFER_METER=1000`.
  - Bridge overlay: `/api/gangseo-connectivity-data` is queried with the same selected bbox, so the page shows only bridge candidates relevant to the chosen dong +1km review area.
