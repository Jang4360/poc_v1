# 02C Centerline-First Segment/Node Load

## Workstream

`N3L_A0020000_26 원본 도로 중심선을 단계별 디버그 기준선으로 재구축`

## Goal

02A/02B의 side graph와 bridge/repair 단계에서 발생한 연결 오류를 한 번에 고치지 않고, 원천 SHP 중심선부터 카카오맵 SDK 위에 올려 단계별로 어디서 문제가 생기는지 분리한다. 02C는 중심선 preview에서 시작해, 도로폭 기반 sideline preview, sideline 교차 node, 중심선 접점 기반 prune 순서로 단계별 산출물을 남긴다.

## Scope

- `etl/raw/N3L_A0020000_26.shp` 원본 polyline을 읽는다.
- CRS는 `EPSG:5179 -> EPSG:4326`으로 변환한다.
- 해운대역 중심 좌표 `(35.1633200, 129.1588705)` 반경 5km 원 안에 교차하는 중심선만 clip한다.
- Step 0 산출물은 `CENTERLINE` segment만 포함한다.
- Step 1 산출물은 `SIDE_LEFT`, `SIDE_RIGHT` segment만 포함한다.
- Step 2B 산출물은 Step 1 raw sideline에서 다시 출발해 `INTERSECTION` node와 중심선 접점 prune만 포함한다.
- Step 2C 산출물은 Step 1 raw sideline에서 다시 출발해 point/overlap/near-overlap 교차 node와 dangling chain prune을 포함한다.
- Step 2D 산출물은 Step 2C에서 누락된 비평행 near-cross와 endpoint-adjacent cross를 보강한다.
- 카카오맵 preview를 단계별 HTML로 분리한다.

## Non-Goals

- node 생성/병합
- bridge 생성
- self-scan repair
- DB 적재
- GraphHopper import

## Step Plan

### Step 0. Raw Centerline Preview

- 입력: `N3L_A0020000_26` SHP sidecar
- 처리:
  - SHP part를 projected line으로 읽는다.
  - 5km circle과 교차하는 부분만 clip한다.
  - clip 결과를 WGS84 LineString으로 변환한다.
- 출력:
  - `etl/segment_02c_centerline.geojson`
  - `etl/segment_02c_centerline.html`
- 검증:
  - `segmentTypeCounts`가 `CENTERLINE`만 포함한다.
  - `roadNodes.features`는 비어 있다.
  - preview가 카카오맵 SDK에서 로드된다.

### Step 1. Raw Sideline Preview

- 입력: Step 0과 동일한 원본 SHP part
- 처리:
  - SHP `RVWD` 도로폭을 읽는다.
  - 중심선 기준 `offsetMeter = max(RVWD / 2, 1.0m)`로 좌/우 offset line을 만든다.
  - 5km circle과 교차하는 side line만 clip한다.
  - 중심선과 node는 출력하지 않는다.
- 출력:
  - `etl/segment_02c_sideline.geojson`
  - `etl/segment_02c_sideline.html`
- 검증:
  - `segmentTypeCounts`가 `SIDE_LEFT`, `SIDE_RIGHT`만 포함한다.
  - `CENTERLINE`, bridge, node는 없다.
  - preview가 카카오맵 SDK에서 로드된다.

### Step 2. Sideline Intersection Nodes + Width-Based Tail Prune (Rejected Diagnostic)

- 입력: Step 1 sideline 결과
- 처리:
  - `SIDE_LEFT × SIDE_LEFT`, `SIDE_RIGHT × SIDE_RIGHT`, `SIDE_LEFT × SIDE_RIGHT` 교차점을 찾는다.
  - 교차점이 양쪽 segment 내부에 있을 때 `INTERSECTION` node로 생성한다.
  - 교차점에서 각 원래 segment endpoint까지 남은 조각이 돌출 tail인지 판정한다.
  - tail 제거 기준:
    - 두 교차 segment의 `roadWidthMeter` 중 큰 값을 `tailPruneThresholdMeter`로 사용한다.
    - `roadWidthMeter`가 없는 경우 해당 segment의 `offsetMeter * 2`를 대체 폭으로 사용한다.
    - split된 조각이 원래 segment endpoint에 붙어 있고, 반대쪽 끝이 교차 node이며, 조각 길이가 `tailPruneThresholdMeter`보다 작으면 제거한다.
    - 두 교차 node 사이의 내부 조각은 이 단계에서 제거하지 않는다.
- 출력:
  - `etl/segment_02c_sideline_intersection.geojson`
  - `etl/segment_02c_sideline_intersection.html`
- 검증:
  - `roadNodes`에는 `INTERSECTION` node만 생성된다.
  - `roadSegments`에는 `SIDE_LEFT`, `SIDE_RIGHT`만 남는다.
  - 중심선, bridge, connector는 없다.
- 판정:
  - 지도 확인 결과 정상 sideline까지 제거하는 경우가 있어 후속 기준으로 사용하지 않는다.
  - 산출물은 비교/진단용으로만 유지하고, 다음 단계는 Step 1 raw sideline에서 다시 시작한다.

### Step 2B. Sideline Nodes + Centerline Contact Prune

- 입력:
  - Step 1 raw sideline
  - 원본 centerline geometry reference
- 5단계 처리:
  - 1. Step 1 sideline을 기준 입력으로 사용하고, Step 2 width-pruned 결과는 사용하지 않는다.
  - 2. centerline은 지도에 그리지 않고 prune 판정용 spatial index로만 유지한다.
  - 3. `SIDE_LEFT × SIDE_LEFT`, `SIDE_RIGHT × SIDE_RIGHT`, `SIDE_LEFT × SIDE_RIGHT` 교차점이 양쪽 segment 내부에 있을 때 `INTERSECTION` node를 찍는다.
  - 4. split된 sideline 조각 중 한쪽 끝만 node인 조각을 검사한다.
  - 5. node에서 조각 방향으로 진행했을 때 다른 원본 road의 centerline과 짧은 거리 안에서 접점이 생기면, node부터 centerline 접점까지만 제거하고 나머지 조각은 유지한다.
- 제거 기준:
  - 같은 `sourceIndex/sourcePart`의 centerline 접점은 무시한다.
  - 접점까지 거리는 `0.25m`보다 커야 한다.
  - 접점까지 거리는 `max(roadWidthMeter, offsetMeter * 2, 2m) * 1.2 + 1m` 이하여야 한다.
  - 양쪽 끝이 모두 node인 내부 조각은 이 단계에서 제거하지 않는다.
  - centerline과 선형 overlap인 경우는 보수적으로 제거하지 않는다.
- 출력:
  - `etl/segment_02c_sideline_centerline_pruned.geojson`
  - `etl/segment_02c_sideline_centerline_pruned.html`
- 검증:
  - `roadNodes`에는 `INTERSECTION` node만 생성된다.
  - `roadSegments`에는 `SIDE_LEFT`, `SIDE_RIGHT`만 남는다.
  - 중심선, bridge, connector는 없다.
  - Step 2B는 Step 2 산출물을 읽지 않는다.

### Step 2C. Robust Sideline Intersection 01

- 입력:
  - Step 1 raw sideline
- 처리:
  - Step 2/2B 결과를 읽지 않고 raw sideline에서 다시 시작한다.
  - `Point`, `MultiPoint` 교차는 기존처럼 `INTERSECTION` node로 찍는다.
  - `LineString`, `MultiLineString` overlap은 overlap 시작점, midpoint, 끝점을 대표 node로 찍는다.
  - 완전히 겹치지 않아도 `1.25m` 이내이고 heading 차이가 `20도` 이하이며 겹침 길이가 `2m` 이상이면 near-overlap 대표 node를 찍는다.
  - node를 기준으로 segment를 split한다.
  - junction node에서 시작하는 dangling chain을 graph traversal로 따라가며 누적 길이가 `min(localWidth * 2 + 2m, 55m)` 이내이고 끝이 dead-end이면 chain 전체를 제거한다.
- 출력:
  - `etl/segment_02c_sideline_intersection_01.geojson`
  - `etl/segment_02c_sideline_intersection_01.html`
- 검증:
  - `roadNodes`에는 `INTERSECTION` node만 생성된다.
  - overlap이 point node 누락 없이 대표 node로 남는다.
  - 여러 조각으로 나뉜 짧은 돌출 chain이 1-hop이 아니라 chain 단위로 제거된다.
  - 중심선, bridge, connector는 없다.

### Step 2C Findings. Remaining Missed Intersections

- 관찰:
  - `segment_02c_sideline_intersection_01.html`에서도 화면상 교차처럼 보이지만 node가 없는 위치가 남는다.
- 원인:
  - Step 2C의 `near-overlap`은 heading 차이가 `20도` 이하인 평행/준평행 근접 segment만 교차 후보로 본다.
  - 첨부 이미지의 누락 지점은 대부분 서로 비평행으로 접근하거나 교차하는 `near-cross` 형태라서 `near-overlap` 조건에서 제외된다.
  - offset line 생성/clip/simplification 과정에서 실제 좌표는 맞닿지 않지만, 카카오맵 stroke 두께와 확대 수준에서는 교차처럼 보이는 경우가 있다.
  - 현재 node 생성은 실제 `Point` 교차, 선형 overlap, 평행 near-overlap에 치우쳐 있어 `최단거리 기반 비평행 교차 후보`를 만들지 않는다.
  - `INTERSECTION_SPLIT_MIN_GAP_M = 0.75m` 조건 때문에 교차 후보가 segment endpoint 근처에 있으면 node 표시 또는 split 대상에서 제외될 수 있다.
  - Step 2C의 dangling chain prune은 교차점이 먼저 찍혀야 동작하므로, node 누락 지점에서는 prune도 시작되지 않는다.
- 결론:
  - 다음 개선은 prune보다 intersection detector를 먼저 보강해야 한다.
  - `parallel near-overlap`과 별도로 `non-parallel near-cross` detector가 필요하다.
  - endpoint-adjacent 교차는 버리지 말고 endpoint snap/canonical node로 흡수해야 한다.

### Step 2D. Robust Sideline Intersection 02: Near-Cross + Endpoint Snap

- 입력:
  - Step 1 raw sideline
  - Step 2C는 비교/진단용으로만 사용하고, Step 2D도 raw sideline에서 다시 시작한다.
- 처리:
  - 1. 기존 Step 2C detector를 유지한다.
    - actual `Point/MultiPoint`
    - exact `LineString/MultiLineString` overlap representatives
    - parallel near-overlap representatives
  - 2. 새 `near-cross` detector를 추가한다.
    - 두 segment의 최소 거리가 `nearCrossToleranceMeter` 이하이면 후보로 본다.
    - 기본값은 `2.5m`로 시작하고, HTML meta에 기록한다.
    - 두 segment의 heading 차이가 `25도` 이상이면 비평행 near-cross 후보로 본다.
    - closest point의 projection이 양쪽 모두 segment 내부이거나 endpoint snap 허용 범위 안에 있어야 한다.
  - 3. near-cross node 위치는 두 closest point의 midpoint를 canonical node로 사용한다.
    - 실제 split point는 각 segment 위의 closest point를 사용한다.
    - display node는 canonical midpoint에 찍는다.
    - 같은 canonical bucket 안에 여러 후보가 있으면 하나의 node로 cluster한다.
  - 4. endpoint-adjacent cross를 별도로 처리한다.
    - closest point가 endpoint에서 `endpointSnapToleranceMeter` 이하이면 endpoint를 버리지 않고 node 후보로 승격한다.
    - 기본값은 `2.5m`로 시작한다.
    - endpoint와 interior point가 같은 pocket에 들어오면 canonical node 하나로 collapse한다.
  - 5. split 기준을 node display point가 아니라 per-segment split point로 분리한다.
    - 기존에는 node point를 각 segment에 project해서 split했다.
    - Step 2D에서는 `nodeKey -> segmentIndex -> splitPoint`를 저장해, midpoint node라도 각 segment의 실제 closest point에서 split한다.
  - 6. prune은 Step 2C의 dangling chain prune을 재사용하되, 시작 node 집합에 near-cross/endpoint-snap node를 포함한다.
- 필터:
  - 같은 `sourceIndex/sourcePart`의 좌우 side끼리 생기는 자기 교차 후보는 우선 제외한다.
  - 두 segment의 bounding boxes가 tolerance buffer 안에서 겹치지 않으면 제외한다.
  - segment 길이가 `2m` 미만인 micro segment는 near-cross 후보에서 제외한다.
  - near-cross 후보가 이미 actual point/overlap node cluster 안에 있으면 중복 생성하지 않는다.
- 출력:
  - `etl/segment_02c_sideline_intersection_02.geojson`
  - `etl/segment_02c_sideline_intersection_02.html`
- 검증:
  - 첨부 이미지처럼 stroke상 교차하지만 node가 없는 비평행 near-cross 지점에 node가 생긴다.
  - endpoint 근처에서 만나거나 끊긴 segment도 canonical node로 흡수된다.
  - node 수 증가가 과도하면 `nearCrossToleranceMeter`를 낮추고, 누락이 남으면 높인다.
  - `nearCrossCount`, `endpointSnapCrossCount`, `clusteredIntersectionNodeCount`, `duplicateSuppressedCount`를 meta에 기록한다.
  - `roadSegments`에는 `SIDE_LEFT`, `SIDE_RIGHT`만 남고, 중심선/bridge/connector는 없다.

### Step 2D Findings. Over-Marked Junctions

- 관찰:
  - `segment_02c_sideline_intersection_02.html`은 누락 교차점은 크게 줄였지만, 한 교차 지점 주변에 여러 marker가 찍힌다.
- 원인:
  - near-cross 후보가 pair 단위로 생성되어 한 junction pocket 안에서도 segment pair 수만큼 후보 node가 생긴다.
  - endpoint snap 후보와 interior closest-point 후보가 같은 교차로 안에서 서로 다른 canonical bucket으로 남는다.
  - `nearCrossToleranceMeter = 2.5m`, `endpointSnapToleranceMeter = 2.5m`, `nearCrossMinAngleDegree = 25도` 조합이 보수적 누락 방지에는 유리하지만 marker 과밀을 만든다.
- 결론:
  - detector를 더 보수적으로 낮추고, 최종 marker는 개별 후보가 아니라 junction pocket cluster 단위로 collapse해야 한다.

### Step 2E. Robust Sideline Intersection 03: One Marker Per Junction Pocket

- 입력:
  - Step 1 raw sideline
  - Step 2D는 비교/진단용으로만 사용하고, Step 2E도 raw sideline에서 다시 시작한다.
- 처리:
  - 1. Step 2D detector를 유지하되 near-cross 기준을 낮춘다.
    - `nearCrossToleranceMeter = 1.6m`
    - `endpointSnapToleranceMeter = 1.6m`
    - `nearCrossMinAngleDegree = 35도`
  - 2. 후보 intersection node를 바로 출력하지 않는다.
  - 3. 후보 node들을 `junctionNodeClusterRadiusMeter = 5m` 안에서 cluster한다.
  - 4. cluster당 display marker는 centroid/canonical point 하나만 생성한다.
  - 5. split은 cluster marker 위치가 아니라 segment별 closest/snap split point를 유지하되, 같은 segment가 같은 cluster에 여러 split point를 갖는 경우 cluster 중심에 가장 가까운 split point 하나만 선택한다.
  - 6. dangling chain prune은 cluster node 기준으로 실행한다.
- 출력:
  - `etl/segment_02c_sideline_intersection_03.geojson`
  - `etl/segment_02c_sideline_intersection_03.html`
- 검증:
  - 한 교차로 주변에 여러 marker가 아니라 cluster당 marker 하나가 표시된다.
  - 누락 교차점이 다시 발생하면 `junctionNodeClusterRadiusMeter`를 유지한 채 `nearCrossToleranceMeter`만 소폭 올린다.
  - marker 과밀이 남으면 `nearCrossToleranceMeter` 또는 `endpointSnapToleranceMeter`를 낮춘다.
  - `rawIntersectionNodeCount`, `clusteredIntersectionNodeCount`, `clusterReductionCount`, `maxIntersectionClusterSize`를 meta에 기록한다.
  - `roadSegments`에는 `SIDE_LEFT`, `SIDE_RIGHT`만 남고, 중심선/bridge/connector는 없다.

### Step 2F. DB-Ready Endpoint Graph Materialization

- 입력:
  - Step 2E `SIDE_LEFT`, `SIDE_RIGHT` cleaned segment
  - Step 2E intersection marker는 진단용으로만 사용하고, DB graph node는 모든 segment endpoint에서 다시 만든다.
- 처리:
  - 1. 모든 segment의 시작점/끝점을 endpoint node 후보로 생성한다.
  - 2. `endpointGraphSnapRadiusMeter = 1.5m` 이내 endpoint 후보를 하나의 graph node로 cluster한다.
  - 3. segment의 시작/끝 좌표를 cluster 대표 node 좌표로 snap한다.
  - 4. 각 segment에 DB 적재 전제 필드인 `fromNodeId`, `toNodeId`를 부여한다.
  - 5. 같은 node로 시작/끝이 접히는 degenerate segment는 적재 후보에서 제외한다.
- 출력:
  - `etl/segment_02c_graph_materialized.geojson`
  - `etl/segment_02c_graph_materialized.html`
- 검증:
  - 모든 `roadSegments`가 `fromNodeId`, `toNodeId`를 가진다.
  - 모든 `fromNodeId`, `toNodeId`가 `roadNodes.vertexId`에 존재한다.
  - `roadNodes`에는 `sourceNodeKey`, `point`, `degree`, `endpointCount`를 추적할 수 있는 속성이 있다.
  - `endpointClusterReductionCount`, `maxEndpointClusterSize`, `droppedDegenerateSegmentCount`를 meta에 기록한다.

### Step 2G. Local Manual Edit UI Before DB Apply

- 입력:
  - Step 2F materialized graph payload
- 처리:
  - 1. 전체 payload는 로더에 포함하되, 지도에는 현재 viewport bbox와 교차하는 segment만 렌더링한다.
  - 2. `삭제` 모드에서 segment를 클릭하면 원본을 직접 수정하지 않고 `manual_edits.edits[]`에 `delete_segment`를 누적한다.
  - 3. `추가` 모드에서 지도 두 지점을 클릭하면 `add_segment` 편집 내역과 임시 선을 누적한다.
  - 4. 편집 내역은 브라우저 `localStorage`에 보존하고, 사이드패널에서 JSON 복사/다운로드를 제공한다.
  - 5. 이 JSON은 후속 DB 반영 단계에서 source graph 위에 patch로 적용한다.
- 출력:
  - `etl/segment_02c_graph_edit.html`
- 검증:
  - HTML에는 선택/삭제/추가/현재 bbox 새로고침/JSON 복사/JSON 저장/되돌리기/초기화 컨트롤이 있다.
  - 편집 내역 schema는 `version`, `sourceHtml`, `sourceGeojson`, `createdAt`, `edits[]`를 포함한다.
  - source `road_segments`, `road_nodes` payload는 직접 변경하지 않는다.

### Step 2H. Local DB Load and DB-backed Preview

- 입력:
  - `etl/segment_02c_graph_materialized.geojson`
  - 선택 입력: 편집 UI가 내보낸 `segment_02c_manual_edits.json`
- 처리:
  - 1. materialized payload의 `roadNodes`와 `roadSegments`를 검증한다.
  - 2. 선택 편집 JSON이 있으면 `delete_node`, `delete_segment`, `add_node`, `add_segment` patch를 payload에 적용한다.
  - 3. `road_nodes`, `road_segments`를 재적재한다.
  - 4. DB에서 다시 조회한 결과로 `etl/segment_02c_graph_db.geojson`과 `etl/segment_02c_graph_db.html`을 생성한다.
- 출력:
  - `etl/segment_02c_graph_db.geojson`
  - `etl/segment_02c_graph_db.html`
- 검증:
  - DB 적재 후 orphan edge, invalid geometry, invalid SRID, invalid length가 모두 0이다.
  - DB 기반 HTML의 node/segment 건수가 DB 쿼리 결과와 일치한다.

### Step 3. Centerline Topology Nodes

- 중심선 endpoint와 교차점 node만 추가한다.
- side offset과 bridge는 아직 생성하지 않는다.
- 이 단계에서 node 과다 생성이 시작되는지 확인한다.

### Step 4. Centerline Split

- 중심선끼리의 실제 교차점에서만 split한다.
- snap tolerance별 변화량을 리포트한다.

### Step 5. Split-Based Side Offset

- 검증된 centerline split 결과에서만 `SIDE_LEFT/RIGHT`를 생성한다.
- Step 1 raw sideline 결과와 비교해 split 이후 문제를 분리한다.

### Step 6. Junction/Repair

- side offset 결과를 기준으로 junction cleanup과 repair를 하나씩 추가한다.
- 각 단계 산출물을 별도 HTML로 남겨 회귀 위치를 좁힌다.

## Success Criteria

- [x] 02C 계획 파일이 존재한다.
- [x] Step 0 HTML이 해운대역 반경 5km `CENTERLINE`만 표시한다.
- [x] Step 0 GeoJSON에는 `SIDE_*`, bridge, node가 없다.
- [x] Step 0 산출물은 기존 02B/repair 산출물을 덮어쓰지 않는다.
- [x] Step 0 테스트와 repository verify가 통과한다.
- [x] Step 1 HTML이 해운대역 반경 5km `SIDE_LEFT`, `SIDE_RIGHT`만 표시한다.
- [x] Step 1 GeoJSON에는 `CENTERLINE`, bridge, node가 없다.
- [x] Step 1 산출물은 Step 0 및 기존 02B/repair 산출물을 덮어쓰지 않는다.
- [x] Step 1 테스트와 repository verify가 통과한다.
- [x] Step 2 HTML이 sideline 교차점 node를 표시한다.
- [x] Step 2는 원래 endpoint에 붙은 짧은 돌출 segment만 도로폭 기준으로 제거한다.
- [x] Step 2 GeoJSON에는 `CENTERLINE`, bridge, connector가 없다.
- [x] Step 2 산출물은 이전 단계 산출물을 덮어쓰지 않는다.
- [x] Step 2 테스트와 repository verify가 통과한다.
- [x] Step 2 width-based prune은 후속 기준에서 제외하고 진단용으로만 남긴다.
- [x] Step 2B HTML이 Step 1 raw sideline에서 다시 시작해 중심선 접점 방향만 prune한다.
- [x] Step 2B GeoJSON에는 `CENTERLINE`, bridge, connector가 없다.
- [x] Step 2B 산출물은 이전 단계 산출물을 덮어쓰지 않는다.
- [x] Step 2C 계획이 point/overlap/near-overlap node와 chain prune 기준을 명시한다.
- [x] Step 2C HTML이 `segment_02c_sideline_intersection_01.html`로 생성된다.
- [x] Step 2C GeoJSON에는 `CENTERLINE`, bridge, connector가 없다.
- [x] Step 2C 테스트와 repository verify가 통과한다.
- [x] Step 2C 누락 원인을 near-cross/endpoint-adjacent 미검출로 기록한다.
- [x] Step 2D 계획이 near-cross와 endpoint snap 기준을 명시한다.
- [x] Step 2D HTML이 `segment_02c_sideline_intersection_02.html`로 생성된다.
- [x] Step 2D GeoJSON에는 `CENTERLINE`, bridge, connector가 없다.
- [x] Step 2D 테스트와 repository verify가 통과한다.
- [x] Step 2D marker 과밀 원인을 pair-level near-cross 후보 과다로 기록한다.
- [x] Step 2E 계획이 junction pocket cluster당 marker 1개 기준을 명시한다.
- [x] Step 2E HTML이 `segment_02c_sideline_intersection_03.html`로 생성된다.
- [x] Step 2E GeoJSON에는 `CENTERLINE`, bridge, connector가 없다.
- [x] Step 2E 테스트와 repository verify가 통과한다.
- [x] Step 2F 계획이 endpoint graph materialization 기준을 명시한다.
- [x] Step 2F HTML이 `segment_02c_graph_materialized.html`로 생성된다.
- [x] Step 2F 모든 segment가 유효한 `fromNodeId`, `toNodeId`를 가진다.
- [x] Step 2F 테스트와 repository verify가 통과한다.
- [x] Step 2G 편집 UI 계획이 bbox 렌더링과 manual_edits 저장 기준을 명시한다.
- [x] Step 2G HTML이 `segment_02c_graph_edit.html`로 생성된다.
- [x] Step 2G 테스트가 통과한다.
- [x] Step 2H DB 적재 스크립트가 `road_nodes`, `road_segments`를 재적재한다.
- [x] Step 2H DB 기반 HTML이 `segment_02c_graph_db.html`로 생성된다.
- [x] Step 2H DB 적재 검증에서 orphan/invalid geometry/SRID/length가 0이다.
- [!] repository verify는 Windows 환경에 `/bin/bash`가 없어 실행되지 않았다.

## Validation Commands

- `.venv/bin/python -m pytest etl/tests/test_segment_centerline_02c.py`
- `.venv/bin/python etl/scripts/13_generate_segment_02c_centerline.py`
- `.venv/bin/python etl/scripts/13_generate_segment_02c_centerline.py --variant sideline`
- `.venv/bin/python etl/scripts/13_generate_segment_02c_centerline.py --variant sideline-intersection`
- `.venv/bin/python etl/scripts/13_generate_segment_02c_centerline.py --variant sideline-intersection-01`
- `.venv/bin/python etl/scripts/13_generate_segment_02c_centerline.py --variant sideline-intersection-02`
- `.venv/bin/python etl/scripts/13_generate_segment_02c_centerline.py --variant sideline-intersection-03`
- `.venv/bin/python etl/scripts/13_generate_segment_02c_centerline.py --variant graph-materialized`
- `.venv/bin/python etl/scripts/13_generate_segment_02c_centerline.py --variant graph-edit`
- `.venv/bin/python etl/scripts/14_load_segment_02c_graph_db.py --stage full`
- `.venv/bin/python etl/scripts/13_generate_segment_02c_centerline.py --variant sideline-centerline-pruned`
- `scripts/verify.sh`

## Handoff

Step 2B 결과를 지도에서 확인한 뒤, 사용자가 중심선 접점 기반 prune이 실제 교차로 돌출 제거 문제를 해결하는지 판단한다. 다음 턴에서는 필요한 경우 중심선 topology node 또는 접점 threshold를 별도 HTML로 비교한다.

## 2026-04-27 Manual Edit Handoff

- Input manual edits: `C:/Users/SSAFY/Downloads/segment_02c_manual_edits.json`
- Applied edits: 478 `delete_segment` records, 2 `delete_node` records.
- CSV outputs regenerated from `etl/gangseo_segment_02c_graph_materialized.geojson` with manual edits applied:
  - `etl/gangseo_road_nodes.csv`
  - `etl/gangseo_road_segments.csv`
  - `etl/road_nodes.csv`
  - `etl/road_segments.csv`
- CSV-backed edit preview regenerated for Songjeong/Sinho/Noksan/Hwajeon bbox `128.815,35.055,128.93,35.135`:
  - `etl/noksan_sinho_songjeong_hwajeon_segment_02c_graph_edit.html`
  - `etl/noksan_sinho_songjeong_hwajeon_segment_02c_graph_materialized.geojson`
- Handoff to next stage: load the regenerated CSV into DB, then render DB-backed HTML to confirm the same deleted edge IDs remain absent.

## 2026-04-27 Manual Edit Handoff 2

- Input manual edits: `C:/Users/SSAFY/Downloads/segment_02c_manual_edits (2).json`
- Applied cumulative edits: 1,384 `delete_segment` records, 7 `delete_node` records.
- Additional segments removed from the current Gangseo CSV: 906.
- CSV outputs regenerated from the existing edited `etl/gangseo_road_nodes.csv` and `etl/gangseo_road_segments.csv`:
  - `etl/gangseo_road_nodes.csv`
  - `etl/gangseo_road_segments.csv`
  - `etl/road_nodes.csv`
  - `etl/road_segments.csv`
- CSV-backed edit preview regenerated for Songjeong/Sinho/Noksan/Hwajeon bbox `128.815,35.055,128.93,35.135`:
  - `etl/noksan_sinho_songjeong_hwajeon_segment_02c_graph_edit.html`
  - `etl/noksan_sinho_songjeong_hwajeon_segment_02c_graph_materialized.geojson`
- Handoff to next stage: load the regenerated CSV into DB and render DB-backed HTML.

## 2026-04-27 Manual Edit Handoff 4

- Input manual edits: `C:/Users/SSAFY/Downloads/segment_02c_manual_edits (4).json`
- Applied cumulative edits: 1,489 `delete_segment`, 75 `delete_node`, 24 `add_node`, and 263 `add_segment` records.
- Existing `SIDE_LEFT` and `SIDE_RIGHT` segment types were normalized to `SIDE_LINE` in CSV outputs.
- Edit UI segment choices now allow `SIDE_LINE` for red side lines and `SIDE_WALK` for blue crosswalk/sidewalk additions.
- CSV outputs regenerated from the existing edited Gangseo CSV files:
  - `etl/gangseo_road_nodes.csv`
  - `etl/gangseo_road_segments.csv`
  - `etl/road_nodes.csv`
  - `etl/road_segments.csv`
- CSV-backed edit preview regenerated for Songjeong/Sinho/Noksan/Hwajeon bbox `128.815,35.055,128.93,35.135`:
  - `etl/noksan_sinho_songjeong_hwajeon_segment_02c_graph_edit.html`
  - `etl/noksan_sinho_songjeong_hwajeon_segment_02c_graph_materialized.geojson`
