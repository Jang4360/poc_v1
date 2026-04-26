# 02A Side Graph Segment/Node Load

## Workstream

`중심선 기반 road_segments를 side-aware 보행 graph로 재구축`

## Reference

- 기반 워크스트림: [.ai/PLANS/current-sprint/02-shp-network-load.md](/Users/jangjooyoon/Desktop/JooYoon/ssafy/poc_v1/.ai/PLANS/current-sprint/02-shp-network-load.md)
- 관련 워크스트림: [.ai/PLANS/current-sprint/03a-road-buffer-filter-layer.md](/Users/jangjooyoon/Desktop/JooYoon/ssafy/poc_v1/.ai/PLANS/current-sprint/03a-road-buffer-filter-layer.md)

## Goal

기존 `road_segments` 중심선 graph를 운영 graph로 유지하지 않고, `N3L_A0020000_26` 중심선과 `RVWD` 폭, 교차로 zone, 횡단보도 endpoint, 엘리베이터 projection을 이용해 좌/우 side-aware 보행 graph를 새로 생성한다. 최종 산출물은 `road_nodes`, `road_segments`에 다시 적재되며, 해운대 5km 범위를 카카오맵 SDK 기반 HTML preview로 시각 검증한다.

## Scope

- 기존 중심선 graph를 side graph 생성용 입력으로만 사용
- 교차로 zone 계산과 chain merge 규칙 정의
- chain별 left/right offset line 생성
- intersection clipping, snap, gap bridge, stub 제거 후 topology 정리
- crosswalk / elevator event point를 graph node로 승격
- 정리된 offset line을 `road_nodes`, `road_segments`로 재구성
- DB 적재 후 카카오맵 SDK 기반 HTML preview 생성

## Non-Goals

- 중심선 graph와 side graph를 동시에 운영하는 이중 운영 체계 유지
- 요청 시점 동적 side graph 생성
- GraphHopper import 전환 (후속 워크스트림에서 별도 처리)
- 횡단보도 데이터셋의 의미 판정 자체를 이 문서에서 확정

## Problem Summary

- 기존 `road_segments`는 중심선 기반 graph라 반대편 인도와 더 가깝게 붙는 오매칭이 발생한다.
- 단순 nearest-segment + connector 접근은 횡단보도를 거쳐야 하는 상황을 표현하지 못한다.
- `03a` polygon은 candidate filter 용도이며, 운영 graph의 geometry truth로 쓰기에는 교차로와 비대칭 도로 폭을 충분히 설명하지 못한다.
- 따라서 운영 graph는 최소 `LEFT_SIDE`, `RIGHT_SIDE`, `CROSSING`, `CONNECTOR`를 구분하는 side-aware topology여야 한다.

## Success Criteria

- [x] 교차로 zone을 기준으로 side line이 교차로 한가운데로 튀어나오지 않도록 clipping 규칙이 고정된다.
- [x] 중심선 작은 edge를 교차로 사이 chain으로 merge한 뒤, lane classification으로 `CENTERLINE`/`MULTI_LANE`을 분류한 뒤 offset 하도록 구현 순서가 고정된다.
- [x] left/right offset line이 snap 기반 node merge와 stub 제거를 거쳐 연속된 side corridor로 정리된다.
- [x] 횡단보도 endpoint와 엘리베이터 projection point가 event node로 승격되는 규칙이 정의된다.
- [~] 최종 side-aware geometry가 `road_nodes`, `road_segments`로 다시 적재된다.
- [x] 해운대 5km 범위를 카카오맵 SDK HTML preview로 시각 검증한다.

## Inputs

- `etl/raw/N3L_A0020000_26.shp`
- `etl/raw/N3L_A0020000_26.dbf`
- `runtime/etl/centerline-load/road_nodes_snapshot.csv`
- `runtime/etl/centerline-load/road_segments_snapshot.csv`
- `etl/raw/stg_crosswalks_ready.csv`
- `etl/raw/subway_elevator.csv`
- `db/schema.sql`
- `etl/common/centerline_loader.py`
- `etl/common/reference_loader.py`
- `docs/erd_v2.md`

## Side Graph Design

### Canonical Decision

- `road_segments`의 운영 의미를 중심선 graph에서 side-aware graph로 전환한다.
- 기존 중심선 적재 결과는 재생성 가능한 중간 산출물로 간주한다.
- GraphHopper는 최종 `road_nodes`, `road_segments`만 읽고, 별도 `walkway_segments` 테이블은 두지 않는다.
- **실질적으로 2차로가 될 수 없는 협폭 도로는 side offset을 생성하지 않고 중심선 그대로 `CENTERLINE` segment로 유지한다.** 좌/우 offset은 `CENTERLINE` 기준을 넘는 도로에만 적용한다.

### Segment Types

- `CENTERLINE` — 2차로 최소 기준폭의 `0.8` 미만인 협폭 도로. 중심선을 그대로 사용하며 offset 없음
- `SIDE_LEFT` — 다차로 도로 좌측 인도 offset
- `SIDE_RIGHT` — 다차로 도로 우측 인도 offset
- `TRANSITION_CONNECTOR` — `CENTERLINE`과 `SIDE_LEFT`/`SIDE_RIGHT`를 잇는 짧은 연결 segment
- `GAP_BRIDGE` — 같은 `MULTI_LANE` chain / same side 내부에서 clipping 또는 trim 후 남은 짧은 단절을 메우는 보수적 보정 segment
- `CORNER_BRIDGE` — `intersection zone` 경계에서 잘린 같은 교차로 코너 보도 fragment를 다시 잇는 전용 segment
- `CROSSING` — 횡단보도 연결
- `ELEVATOR_CONNECTOR` — 엘리베이터 연결

필요 시 `segment_features` 또는 `properties`에 타입을 보조 기록한다.

### Lane Classification Rule

chain의 타입(`CENTERLINE` vs offset 대상)을 결정하는 기준:

- **법정 2차로 최소폭 기반 기준**:
  - 현행 `도로의 구조ㆍ시설 기준에 관한 규칙`의 차로폭 최소 기준은 일반적으로 `3.0m`, 예외적으로 도시지역 저속 조건에서 `2.75m`까지 허용된다.
  - 따라서 이 계획에서는 **절대 2차로 최소폭**을 `twoLaneMinimumWidthMeter = 5.5` (`2.75m x 2`)로 둔다.
  - `singleLaneThresholdMeter = twoLaneMinimumWidthMeter x 0.8 = 4.4`로 계산한다.
  - **`RVWD < singleLaneThresholdMeter`이면 `CENTERLINE`으로 분류한다.**
- **명시 속성 보조 기준**:
  - SHP 속성에 `RDLN <= 1` 또는 신뢰 가능한 단일 차로 표기가 있으면 `CENTERLINE` 후보로 본다.
  - `ONSD`는 일방통행 참고 정보로만 쓰고, `CENTERLINE` 판정의 단독 근거로는 사용하지 않는다.
- `CENTERLINE` chain은 offset 생성 단계(Step 3)를 건너뛰고 중심선 geometry를 그대로 사용한다.

### Node Types

- `INTERSECTION_BOUNDARY` — 다차로 교차로 경계
- `LANE_TRANSITION` — `CENTERLINE` ↔ `SIDE_LEFT`/`SIDE_RIGHT` 전환점. 공유 node가 아니라 transition connector가 시작되는 분기점
- `DEAD_END`
- `CHAIN_JOIN`
- `CROSSING_ATTACH`
- `ELEVATOR_ATTACH`
- `ATTRIBUTE_BREAK`

node 타입은 별도 컬럼 또는 `sourceNodeKey` prefix / `properties`에 기록한다.

## Geometry Pipeline

### 1. Intersection Zone

- 중심선 기반 `road_nodes`에서 `degree >= 3` node를 분기 node로 식별한다.
- 분기 node 주변 버퍼 반경은 `max(roadWidth / 2, floorMeter)`를 기본으로 한다.
- 이 버퍼를 `intersection zone`으로 정의한다.

### 2. Chain Merge

- 중심선 작은 edge들을 교차로 zone 사이 corridor chain으로 merge한다.
- chain 경계는 다음으로 정의한다.
  - intersection zone 진입/이탈점
  - dead-end
  - 명시적 속성 단절점
  - **`CENTERLINE` ↔ `MULTI_LANE` 전환점** (차로 수 또는 폭 속성이 바뀌는 지점)

### 2.5. Lane Classification

- chain별로 `RVWD`(또는 차로수 속성)를 읽어 `CENTERLINE` / `MULTI_LANE`으로 분류한다.
- `CENTERLINE` chain:
  - offset 생성(Step 3)을 건너뛴다.
  - 중심선 geometry를 `CENTERLINE` segment로 그대로 사용한다.
  - **multi-lane 도로 또는 intersection zone과 만나는 endpoint는 `LANE_TRANSITION` node로 승격한다.**
  - `LANE_TRANSITION` node에서 `SIDE_LEFT`/`SIDE_RIGHT`로 직접 붙이지 않고, 각 side attach point까지 별도 `TRANSITION_CONNECTOR` segment를 생성한다.
- `MULTI_LANE` chain: Step 3 이하 offset 파이프라인을 정상 진행한다.

### 3. Offset Generation

- **`MULTI_LANE` chain에만 적용한다.**
- chain별로 좌/우 offset line을 생성한다.
- 기본 offset 거리:
  - `offsetMeter = max(roadWidth / 2, 1.0)`
- 필요 시 보수적으로 `roadWidth / 2 - alpha`를 허용하되 초기 구현은 단순 반폭으로 시작한다.

### 4. Intersection Clipping

- 생성된 offset line에서 intersection zone 영역을 `difference`로 제거한다.
- 목적:
  - 교차로 한복판으로 튀어나오는 선 제거
  - 다른 도로 side line과 과도하게 겹치는 구간 제거
- 이 단계는 교차로를 “묶는” 단계가 아니라, **교차로 내부로 과하게 들어간 geometry를 잘라내는 단계**다.
- clipping 직후에는 교차로 경계에 node 후보가 남고, 잘린 결과로 생긴 짧은 꼬투리(stub)가 같이 생길 수 있다.

### 5. Intersection Boundary Node Confirmation + Pass 1 Stub Prune

- `intersection clipping` 이후 생긴 교차로 경계 endpoint를 우선 node 후보로 확정한다.
- 이 단계에서 교차로 내부에 남은 짧은 꼬투리(stub)를 먼저 제거한다.
- 목적:
  - connector가 “꼬투리끼리” 연결되는 것을 방지
  - 교차로에서 실제 의미 있는 경계점만 다음 단계 입력으로 남기기
- 기본 기준:
  - `stubPruneLengthMeter` 이하
  - dead-end 형태
  - 교차로 경계 안쪽 또는 바로 인접한 잔여 조각

### 5A. Snap / Gap Bridge Current State

- 현재 `GAP_BRIDGE`는 `same side + corridor group + endpoint -> target line attach + target split`까지 반영되어 있다.
- 이 단계는 `intersection clipping` 또는 `tail trim` 이후 남는 일반적인 side corridor 단절을 줄이는 데는 효과가 있다.
- 다만 해운대 5km preview를 보면 다음 유형은 여전히 누락된다.
  - `intersection zone` 경계에서 잘린 코너 fragment 사이 연결
  - 같은 교차로 코너에 속하지만 직선 bridge가 `CENTERLINE` 또는 반대편 side를 스친다고 판정되는 경우
  - `same corridor`보다는 `same corner sector` 판정이 더 중요한 교차로 보도 회전 구간
- 따라서 다음 단계는 `GAP_BRIDGE`의 거리만 늘리는 것이 아니라, **교차로 코너 전용 연결 타입**을 추가하는 것이다.

### 5B. General Bridge Generation

- 교차로 외부의 일반적인 side corridor 단절은 `GAP_BRIDGE`가 담당한다.
- `GAP_BRIDGE`는 same-side, same-corridor 조건을 만족하는 짧은 단절만 복구한다.
- attach target이 line interior면 split event를 추가한다.

### 5C. Corner Bridge Improvement Plan

#### Problem Statement

- 현재 미연결 사례의 주원인은 일반 side corridor gap이 아니라 **intersection corner continuity** 부족이다.
- 교차로 코너에서는 `intersection clipping`으로 의도적으로 잘라낸 뒤 다시 연결해야 하는데, 현재 `GAP_BRIDGE`는 이를 일반 gap과 같은 규칙으로 다뤄 정확도가 떨어진다.
- 기존 플랜의 `03a` polygon 의존 방식은 외부 선행 데이터가 필요해 self-contained하지 않다.

#### Revised Approach — Arm-Vector Sector (03a 의존 제거)

`03a` polygon 없이 이미 보유한 `cluster_centers` + `adjacency` 정보만으로 sector를 계산한다.

- `intersection_root`에서 인접 chain의 첫 번째 non-root node를 이용해 **arm 방향 벡터**를 계산한다.
- arm 벡터를 각도 기준으로 정렬해 인접 arm 쌍이 이루는 **sector**를 정의한다.
  - `n`개의 arm이 있으면 `n`개의 sector가 생긴다 (각 arm 사이 각도 범위).
- 각 fragment endpoint를 가장 가까운 intersection root에 귀속시킨 뒤, root 기준 각도로 **sector 라벨**을 할당한다.
- sector 계산은 `build_intersection_sectors()` 함수로 캡슐화한다.

#### New Segment Type

- `CORNER_BRIDGE` — `intersection zone` 경계에서 잘린 같은 코너 보도 fragment를 다시 잇는 전용 segment

#### Candidate Scope

- `intersection root` 주변 `intersection zone` 경계 안팎에서 끝나는 `SIDE_LEFT` / `SIDE_RIGHT` fragment endpoint만 후보로 본다.
- 일반 도로 중간 단절은 계속 `GAP_BRIDGE`가 담당하고, 교차로 코너 연결만 `CORNER_BRIDGE`가 담당한다.

#### Eligibility Rule

- 같은 `intersection root` 인근이어야 한다 (endpoint가 root 기준 `intersection_zone_radius * 1.5` 이내).
- 같은 side(`SIDE_LEFT` 또는 `SIDE_RIGHT`)여야 한다.
- 같은 `arm-vector sector` 안에 있어야 한다.
  - 두 endpoint가 root 기준 동일한 sector angle 범위에 속하는지를 기준으로 한다.
- 직선 거리뿐 아니라 `corner turn continuity`를 함께 본다.
  - endpoint outward 방향 벡터
  - root 기준 회전 방향
  - 같은 sector 내부 여부

#### Geometry Rule

- 기본은 `endpoint -> endpoint` 또는 `endpoint -> line attach` 이다.
- 단, 코너 회전이 필요한 경우는 직선 1개로 연결하지 않고 아래 중 하나를 허용한다.
  - `root` 주변 2-segment polyline (endpoint → root vicinity midpoint → target endpoint)
  - 짧은 arc에 준하는 꺾인 polyline
- attach target이 line interior면 해당 target line은 split 한다.

#### Barrier Rule

- 일반 `GAP_BRIDGE`는 현재 barrier 규칙을 유지한다.
- `CORNER_BRIDGE`는 같은 `intersection zone` 내부에서는 `CENTERLINE` 교차를 차단하지 않는다.
- 대신 아래를 동시에 만족해야 한다.
  - 같은 `arm-vector sector`
  - 같은 side
  - `intersection root` 기준 인접 코너 fragment
  - 반대편 side 또는 다른 sector로 넘어가지 않음

#### Distance Rule

- `GAP_BRIDGE`: 기존 상수 유지 (`GAP_BRIDGE_MAX_M = 12m`)
- `CORNER_BRIDGE`: `intersection_zone_radius * 3.0` 또는 최소 25m 중 큰 값을 상한으로 사용
- 최대 상한 cap: `CORNER_BRIDGE_HARD_CAP_M = 60m`

### 6. Cross-Type Intersection Resolution

- `split_base_lines()` 결과와 connector/bridge segment를 **합친 전체 geometry**를 대상으로 교차를 검사한다.
- 포함할 조합:
  - `SIDE_LEFT` × `SIDE_RIGHT`
  - `SIDE_LEFT / SIDE_RIGHT` × `GAP_BRIDGE`
  - `SIDE_LEFT / SIDE_RIGHT` × `CORNER_BRIDGE`
  - `TRANSITION_CONNECTOR` × `SIDE_LEFT / SIDE_RIGHT`
- 제외할 조합:
  - `GAP_BRIDGE` × `CORNER_BRIDGE`
    - 이 경우는 교차 해소 대상이 아니라 bridge 생성 버그로 본다.
  - `CENTERLINE` × `SIDE_LEFT / SIDE_RIGHT`
    - offset 기준선 충돌로 간주하고 로깅 후 스킵한다.
- `SIDE_LEFT` × `SIDE_RIGHT` 교차 판정:
  - **유효 junction 승격 조건 (모두 만족해야 함):**
    - 같은 `intersection_root` 기준 `intersection_zone_radius * 1.5` 이내
    - 같은 `arm-vector sector`
    - 교차 후 양쪽 segment가 모두 실제로 이어지는 경우 (양쪽 다 dead-end가 아님)
  - **유효 junction 조건 만족 시:** 교차점을 event point로 승격하고 양쪽 segment를 재 split한다.
  - **조건 불만족 시:** node 승격 없이 교차로 생긴 꼬리(`Cross-Type Tail`)를 prune 대상으로 마킹한다.
- `SIDE_LEFT/RIGHT × GAP_BRIDGE`, `SIDE_LEFT/RIGHT × CORNER_BRIDGE`, `TRANSITION_CONNECTOR × SIDE_*` 교차:
  - 교차점을 event point로 승격하고 재 split한다. (junction 조건 검사 없이 항상 처리)
- **Cross-Type Tail Prune — 이 단계 직후 즉시 실행한다:**
  - prune 대상: 유효하지 않은 교차로 마킹된 꼬리 + 재 split 후 새로 생긴 dangling segment
  - **threshold: `stubPruneLengthMeter` (1.0~2.0m)** — `junctionMergeArtifactPruneM`이 아님
  - same-side / cross-side 구분 없이 동일하게 적용
  - 이유: 교차 후 꼬리는 merge artifact가 아니라 geometry 잔여이므로 보행 의미 기준 threshold를 써야 한다

### 7. Event Point Split

- 최종 traversable line은 다음 event point에서 split한다.
  - chain start/end
  - snapped join point
  - crosswalk attach point
  - elevator attach point
  - 속성 단절점
  - `LANE_TRANSITION` node (`CENTERLINE` chain의 시작/종료 endpoint)
  - `TRANSITION_CONNECTOR` attach point
  - `GAP_BRIDGE` / `CORNER_BRIDGE` attach point
  - `Cross-Type Intersection Resolution`에서 등록된 교차 event

### 8. Junction Consolidation

- `build_node_snapshots()` 내부의 `cluster_endpoint_indices()`는 floating-point 오차 보정용이며, 의미론적 junction merge와 역할이 다르다.
- 따라서 최종 node ID 부여 전에 별도 `Junction Consolidation` 단계를 둔다.
- 정확한 위치:
  - `split_base_lines()` 결과 + connector segments 결합
  - `Cross-Type Intersection Resolution`
  - 전체 segment 재 split + `Cross-Type Tail Prune`
  - **`Junction Consolidation`**
  - `Pass 2 Stub Prune`
  - `build_node_snapshots()`
- 병합 규칙:
  - `junctionMergeRadiusMeter` 이내
  - same root / same sector 제약 만족
  - **same side 제약은 segment type에 따라 다르게 적용한다:**
    - `SIDE_LEFT` endpoint ↔ `SIDE_LEFT` endpoint: same side 적용
    - `SIDE_RIGHT` endpoint ↔ `SIDE_RIGHT` endpoint: same side 적용
    - `TRANSITION_CONNECTOR` endpoint: side 제약 면제, root / sector만 적용
      - `TRANSITION_CONNECTOR`는 `CENTERLINE` ↔ `SIDE_*` 경계에 놓이므로 정의상 cross-side 위치이기 때문
    - `GAP_BRIDGE` / `CORNER_BRIDGE` endpoint: 해당 bridge가 연결하는 side 기준 적용
  - 같은 junction pocket으로 판단되는 node 후보만 semantic merge
- 결과:
  - cluster별 canonical node 1개만 남기고
  - incident edge endpoint를 대표 node로 재연결
  - **재연결 시 edge의 첫/마지막 좌표도 canonical node 좌표로 함께 업데이트한다**
    - endpoint만 바꾸고 geometry를 그대로 두면 node와 edge 좌표 불일치가 생긴다

### 9. Pass 2 Stub Prune

- `Junction Consolidation` 이후 merge artifact로 생긴 매우 짧은 dangling segment를 다시 제거한다.
- `Pass 1`과 역할이 다르므로 threshold를 분리한다.
  - `stubPruneLengthMeter`: 일반 보행 의미 스케일 (`1.0~2.0m`)
  - `junctionMergeArtifactPruneM`: merge 후 artifact 전용 (`0.3~0.5m`)
- `Pass 2`는 매우 짧은 것만 제거해 실제 의미 있는 짧은 connector가 날아가지 않게 한다.

#### Acceptance Criteria

- 현재 preview에서 남아 있는 교차로 코너 단절이 `CORNER_BRIDGE`로 연결된다.
- 일반 도로 중간 구간에서 `GAP_BRIDGE`가 과하게 늘지 않는다.
- `CORNER_BRIDGE`는 다른 side 또는 반대편 코너로 점프하지 않는다.
- `CENTERLINE`을 가로질렀더라도 같은 corner sector 내부인 경우만 허용된다.
- preview 검토 시 코너 회전 흐름이 직선 점프보다 자연스럽게 보인다.
- `03a` polygon 없이 독립적으로 실행된다.

### 10. Crosswalk Projection

- 횡단보도 양끝점 dataset을 이용해 각 endpoint를 nearest traversable line에 projection 한다.
- `MULTI_LANE` chain에서는 nearest side line, `CENTERLINE` chain에서는 nearest centerline을 attach 대상로 사용한다.
- projection point는 `CROSSING_ATTACH` node가 된다.
- 양쪽 attach node를 잇는 `CROSSING` segment를 생성한다.

### 11. Elevator Projection

- 엘리베이터 point를 nearest traversable line에 projection 한다.
- `MULTI_LANE` chain에서는 nearest side line, `CENTERLINE` chain에서는 nearest centerline을 attach 대상로 사용한다.
- projection point는 `ELEVATOR_ATTACH` node가 된다.
- projection point와 실제 엘리베이터 point를 잇는 `ELEVATOR_CONNECTOR` segment를 생성한다.

## DB Load Design

### Node Generation Rule

- 최종 `road_nodes`는 중심선 raw endpoint를 그대로 쓰지 않는다.
- `CENTERLINE`, side line, crossing, connector 위 event point 좌표를 기준으로 새 `vertexId`를 생성한다.
- 단, 이 좌표는 `Cross-Type Intersection Resolution`과 `Junction Consolidation`을 거쳐 **semantic merge된 junction 후보 좌표**여야 한다.
- `build_node_snapshots()` 내부의 endpoint cluster merge는 부동소수점 오차 보정용으로만 남기고, 의미론적 junction merge 책임은 이 단계 이전에 처리한다.
- `sourceNodeKey`는 최종 WGS84 좌표를 tolerance-rounding해 생성한다.

### Segment Generation Rule

- 최종 `road_segments`는 event point 사이 geometry를 저장한다.
- 각 segment는 최소 다음 정보를 유지한다.
  - `edgeId`
  - `fromNodeId`
  - `toNodeId`
  - `geom`
  - `lengthMeter`
  - `walkAccess`
- side/centerline/crossing/connector 타입 정보는 `segment_features` 또는 후속 schema revision으로 보강한다.

### Replace Strategy

- 적재 단계는 기존 중심선 `road_nodes`, `road_segments`를 truncate 후 side graph로 재적재한다.
- 중심선 snapshot은 `runtime/etl/centerline-load/`에 보존한다.
- side graph snapshot은 별도 디렉터리 예:
  - `runtime/etl/side-graph-load/road_nodes_snapshot.csv`
  - `runtime/etl/side-graph-load/road_segments_snapshot.csv`

## Implementation Plan

기반 파이프라인(Steps 1–11)은 구현돼 있으나, 교차로 내부 topology 정리가 부족하다. 이하 계획은 **교차로 node 확정 + connector 생성 순서 재배치 + semantic junction merge**에 초점을 둔다.

### Phase 1 — 교차로 경계 확정과 Pass 1 Stub Prune 선행

1. `intersection clipping` 직후 교차로 경계 endpoint를 `junction candidate`로 수집한다.
2. connector 생성보다 먼저 `Pass 1 Stub Prune`을 실행한다.
   - `stubPruneLengthMeter` 이하
   - dead-end 형태
   - 교차로 경계 안쪽/직후 잔여 geometry
3. 목적:
   - connector가 잘못된 꼬투리끼리 연결되는 현상 방지
   - 실제 junction pocket만 다음 단계 입력으로 남기기

### Phase 2 — 전이 및 일반/코너 보정 segment 생성

4. `TRANSITION_CONNECTOR`를 생성한다.
5. 일반 corridor 단절용 `GAP_BRIDGE`를 생성한다.
6. 교차로 코너 전용 `CORNER_BRIDGE`를 생성한다.
   - `build_intersection_sectors()`
   - `assign_fragment_sectors()`
   - `build_corner_bridges()`
7. 이 단계 산출은 아직 최종 node 확정이 아니라, **재 split 대상 geometry**로 본다.

### Phase 3 — Combined Geometry 기준 Cross-Type Resolution + Cross-Type Tail Prune

8. `split_base_lines()` 결과와 `TRANSITION_CONNECTOR`, `GAP_BRIDGE`, `CORNER_BRIDGE`, `ELEVATOR_CONNECTOR`를 합친 전체 geometry를 만든다.
9. 이 combined geometry 전체를 대상으로 `Cross-Type Intersection Resolution`을 수행한다.
10. 포함 조합:
   - `SIDE_LEFT` × `SIDE_RIGHT`
   - `SIDE_LEFT / SIDE_RIGHT` × `GAP_BRIDGE`
   - `SIDE_LEFT / SIDE_RIGHT` × `CORNER_BRIDGE`
   - `TRANSITION_CONNECTOR` × `SIDE_LEFT / SIDE_RIGHT`
11. 제외 조합:
   - `GAP_BRIDGE` × `CORNER_BRIDGE`
   - `CENTERLINE` × `SIDE_LEFT / SIDE_RIGHT`
12. `SIDE_LEFT × SIDE_RIGHT` 교차 판정:
   - 아래 조건을 **모두** 만족하면 유효 junction으로 승격한다.
     - 같은 `intersection_root` 기준 `intersection_zone_radius * 1.5` 이내
     - 같은 `arm-vector sector`
     - 교차 후 양쪽 segment가 모두 실제로 이어지는 경우 (양쪽 다 dead-end가 아님)
   - `SIDE_LEFT/RIGHT × GAP_BRIDGE`, `SIDE_LEFT/RIGHT × CORNER_BRIDGE`, `TRANSITION_CONNECTOR × SIDE_*` 교차는 조건 검사 없이 항상 event 승격한다.
13. 유효 교차는 event point로 등록하고 전체 geometry를 재 split한다.
14. 조건 불만족 `SIDE_LEFT × SIDE_RIGHT` 교차는 node 승격 없이 꼬리를 prune 대상으로 마킹한다.
15. **Cross-Type Tail Prune을 이 단계 직후 즉시 실행한다.**
   - prune 대상: step 14에서 마킹된 꼬리 + 재 split 후 새로 생긴 dangling segment
   - **threshold: `stubPruneLengthMeter` (1.0~2.0m)**
   - `junctionMergeArtifactPruneM`(0.3~0.5m)을 쓰지 않는다. 교차 후 꼬리는 geometry 잔여이므로 보행 의미 기준 threshold를 적용해야 한다.
   - same-side / cross-side 구분 없이 동일하게 적용한다.

### Phase 4 — Junction Consolidation + Pass 2 Stub Prune

16. `Junction Consolidation`을 `build_node_snapshots()` 전에 수행한다.
17. 병합 대상은 `split + connector + cross-type event + Cross-Type Tail Prune`까지 반영된 **node 후보 좌표**다.
18. 병합 규칙:
   - `junctionMergeRadiusMeter` 적용
   - same root / same sector 제약
   - **same side 제약은 segment type별로 다르게 적용한다:**
     - `SIDE_LEFT` ↔ `SIDE_LEFT`, `SIDE_RIGHT` ↔ `SIDE_RIGHT`: same side 적용
     - `TRANSITION_CONNECTOR` endpoint: side 제약 면제, root / sector만 적용
       - `TRANSITION_CONNECTOR`는 `CENTERLINE` ↔ `SIDE_*` 경계에 위치하므로 정의상 cross-side
     - `GAP_BRIDGE` / `CORNER_BRIDGE` endpoint: bridge가 연결하는 side 기준 적용
   - 같은 junction pocket으로 판단되는 후보만 semantic merge
19. cluster마다 canonical node 1개를 남기고 incident edge endpoint를 재연결한다.
   - **edge의 첫/마지막 좌표도 canonical node 좌표로 함께 업데이트한다** (geometry 불일치 방지)
20. 그 다음 `Pass 2 Stub Prune`을 수행한다.
   - `junctionMergeArtifactPruneM` (0.3~0.5m) 사용
   - merge로 인해 새로 발생한 매우 짧은 dangling artifact만 제거
   - 실제 의미 있는 짧은 connector가 삭제되지 않도록 threshold를 작게 유지한다.

### Phase 5 — 최종 node/segment 확정과 검증

21. `build_node_snapshots()`는 semantic merge가 끝난 geometry에 대해서만 최종 `vertexId` / `edgeId`를 부여한다.
22. preview를 재생성해 아래를 검토한다.
   - 한 junction pocket 안에 node가 하나로 수렴하는지 (이미지 1·2 케이스)
   - `SIDE_LEFT × SIDE_RIGHT` 교차에서 유효 junction만 node로 승격되는지 (이미지 3·4 케이스)
   - same-side / cross-side 교차 뒤 짧은 꼬리가 `stubPruneLengthMeter` 기준으로 제거되는지
   - `TRANSITION_CONNECTOR` endpoint가 인근 side line endpoint와 올바르게 병합되는지
23. 리포트 항목:
   - `gapBridgeCount`
   - `cornerBridgeCount`
   - `crossTypeIntersectionCount` (유효 junction 승격 건수)
   - `crossTypeTailPruneCount` (Cross-Type Tail Prune 제거 건수)
   - `junctionConsolidationClusterCount`
   - `transitionConnectorMergeCount` (side 제약 면제로 병합된 TRANSITION_CONNECTOR endpoint 건수)
   - `pass1StubPruneCount`
   - `pass2StubPruneCount`
24. topology audit에서는 `connectedComponents`와 함께 `mergedJunctionNodeCount`도 남긴다.

---

### 참고: 완료된 기반 파이프라인 (변경 없음)

1. `02` 중심선 로더 snapshot을 side graph 입력으로 재사용
2. 분기 node degree 계산 + intersection zone 생성
3. chain merge (`CENTERLINE` ↔ `MULTI_LANE` 전환점 포함)
4. `RVWD` 기반 lane classification + `LANE_TRANSITION` node 승격
5. `MULTI_LANE` chain left/right offset line 생성
6. intersection zone clipping
7. 교차로 경계 node 후보 확정 + Pass 1 stub prune
8. `TRANSITION_CONNECTOR` / `GAP_BRIDGE` / `CORNER_BRIDGE` 생성
9. crosswalk projection (현재 dataset 미비로 보류)
10. elevator projection + connector 생성
11. combined geometry 기준 `Cross-Type Intersection Resolution`
12. `Junction Consolidation` + Pass 2 stub prune
13. event point 기반 node split + snapshot 생성
14. DB 적재
15. 카카오맵 SDK 기반 HTML preview 생성

## Validation Plan

- side graph node/segment count를 중심선 graph와 비교해 과도한 증식 여부를 확인한다.
- `CENTERLINE` / `MULTI_LANE` chain 분류 건수와 `LANE_TRANSITION` node 생성 건수를 리포트로 남긴다.
- `TRANSITION_CONNECTOR` 생성 건수와 평균 길이를 리포트로 남긴다.
- `GAP_BRIDGE` / `CORNER_BRIDGE` 생성 건수와 평균 길이를 분리 리포트로 남긴다.
- `Cross-Type Intersection Resolution`에서 등록된 교차 event 수를 리포트로 남긴다.
- `Junction Consolidation` cluster 수와 병합된 node 수를 리포트로 남긴다.
- `Pass 1 Stub Prune`과 `Pass 2 Stub Prune` 제거 건수를 분리 리포트로 남긴다.
- crosswalk attach 실패 row count를 남긴다.
- elevator attach 실패 row count를 남긴다.
- 해운대역 5km 범위에서 HTML preview로 다음을 수동 검토한다.
  - 교차로에서 튀어나오는 side line 감소
  - 같은 junction pocket 안의 node가 하나로 수렴하는지
  - 이어져야 할 선 간 gap 감소
  - `SIDE_LEFT × SIDE_RIGHT` 교차에서 유효 junction만 node로 승격되는지
  - cross-side 교차 후 짧은 꼬리가 제거되는지
  - 횡단보도 기반 side-to-side 연결 여부
  - 엘리베이터가 반대편 side에 잘못 붙지 않는지
- DB post-load validation:
  - orphan edge 0
  - invalid geometry 0
  - invalid SRID 0
  - non-positive length 0

## Risks

- `RVWD`가 전체 차도 폭이라 실제 보도 중심축과 차이가 날 수 있다.
- `ST_OffsetCurve`만으로는 곡선/합류부에서 geometry artifact가 남을 수 있다.
- crosswalk endpoint dataset 품질이 낮으면 잘못된 side-to-side 연결이 생길 수 있다.
- 중심선 graph를 완전히 대체하면 기존 `edgeId` 기반 참조와 호환성이 깨진다. POC 단계에서는 전체 재적재로 처리한다.

## Open Questions

- side/crossing/connector 타입을 `road_segments` 정규 컬럼으로 둘지, `segment_features`/`properties`로 둘지
- intersection zone 반경 기본값을 `max(roadWidth / 2, 1.0)`로 고정할지, 추가 상한/하한을 둘지
- gap bridge를 독립 segment로 저장할지, endpoint snap만 허용할지

## Outputs

- `runtime/etl/side-graph-load/side_graph_snapshot.json`
- `runtime/etl/side-graph-load/road_nodes_snapshot.csv`
- `runtime/etl/side-graph-load/road_segments_snapshot.csv`
- `runtime/etl/side-graph-load/side_graph_topology_audit.json`
- `runtime/etl/side-graph-load/side_graph_post_load_report.json`
- `runtime/etl/side-graph-load/side_graph_preview.html`

## Implementation Status

- 2026-04-25 기준 `etl/common/side_graph_loader.py`와 `etl/scripts/10_load_side_graph.py`를 추가해 02a side graph 생성 경로를 구현했다.
- 해운대역 반경 5km 기준 preview 산출물 생성 완료:
  - `runtime/etl/side-graph-load/road_nodes_snapshot.csv`
  - `runtime/etl/side-graph-load/road_segments_snapshot.csv`
  - `runtime/etl/side-graph-load/side_graph_snapshot.json`
  - `runtime/etl/side-graph-load/side_graph_topology_audit.json`
  - `etl/subway_elevator_preview.html`
  - `etl/subway_elevator_preview.geojson`
- 최근 실행 기준 요약:
  - `sourceSegmentCount`: 16,874
  - `normalizedSourceSegmentCount`: 17,289
  - `nodeCount`: 11,649
  - `segmentCount`: 12,842
  - `segmentTypeCounts`: `CENTERLINE 5,826`, `SIDE_LEFT 2,217`, `SIDE_RIGHT 2,439`, `TRANSITION_CONNECTOR 592`, `GAP_BRIDGE 1,740`, `ELEVATOR_CONNECTOR 28`
  - `transition zone` 기준으로 `CENTERLINE`을 먼저 trim한 뒤 `TRANSITION_CONNECTOR`를 생성하도록 수정해, 큰 도로 중심 root를 경유하는 간접 연결을 줄였다.
  - 같은 side line의 짧은 단절은 `corridor group + endpoint->line attach + target split` 방식의 `GAP_BRIDGE`로 메우도록 구현했다.
- Accepted risk:
  - `stg_crosswalks_ready.csv`는 양끝점 쌍이 명시되지 않아 현재 `CROSSING` 생성에서 제외한다. 횡단보도 endpoint dataset 확보 후 다시 연결한다.
  - `GAP_BRIDGE`는 연결성 개선에는 효과적이지만, 현재는 corridor grouping이 완전한 ground truth가 아니어서 일부 과연결 가능성이 남아 있다. 해운대 5km preview에서 우선 시각 검증하고, 필요 시 road-class 또는 intersection-corner 제약을 추가한다.
  - preview 산출은 해운대 5km subset 기준이다. 전체 부산 범위 재적재와 PostGIS `load_db` 실행은 현재 Docker/PostGIS 미가동 상태라 이번 턴에서 검증하지 못했다.
- 2026-04-25 기준 미연결 문제 분석 완료:
  - 근본 원인: `intersection clipping` 이후 `GAP_BRIDGE`의 barrier/group 조건이 교차로 코너에서 과하게 보수적으로 동작.
  - `build_side_corridor_groups()` cross-chain `near_a and near_b` 동시 조건으로 인해 교차로 fragment가 다른 group으로 분류되어 bridge 후보 자체가 생성되지 않는 경우가 주요 원인.
  - `_is_barrier_free_segment()`가 교차로 코너에서 같은 도로 `CENTERLINE`을 barrier로 판단해 차단.
  - 해결 방향: Phase 1(파라미터 + barrier 완화) → Phase 2(arm-vector sector 기반 `CORNER_BRIDGE`) → Phase 3(시각 검증).
  - `03a` polygon 의존 방식을 arm-vector sector 방식으로 대체해 self-contained 구현으로 변경 확정.

## Handoff

- Build: `implement-feature`
- Validation: `check`
- Ship note: `road_segments`의 운영 의미가 중심선 graph에서 side-aware graph로 바뀌므로, 후속 GraphHopper import는 새 topology 기준으로 별도 워크스트림에서 재검토한다.
