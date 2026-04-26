# 02B Universal Side Segment/Node Load

## Workstream

`모든 도로에 SIDE_LEFT / SIDE_RIGHT를 생성하는 side-only 보행 graph 재구축`

## Reference

- 기반 워크스트림: [.ai/PLANS/current-sprint/02-shp-network-load.md](/Users/jangjooyoon/Desktop/JooYoon/ssafy/poc_v1/.ai/PLANS/current-sprint/02-shp-network-load.md)
- 비교 워크스트림: [.ai/PLANS/02a-segment-node-load.md](/Users/jangjooyoon/Desktop/JooYoon/ssafy/poc_v1/.ai/PLANS/02a-segment-node-load.md)

## Goal

`CENTERLINE` 예외를 제거하고, 도로 폭과 차선 수에 상관없이 모든 도로 축에 대해 `SIDE_LEFT`와 `SIDE_RIGHT`를 생성한다. 이후 교차로 내부에서 발생하는 다중 node를 하나의 junction으로 병합하고, 돌출 stub를 제거한 뒤 최종 `road_nodes`, `road_segments`를 생성한다. 최종 검증은 해운대 5km 범위 카카오맵 SDK HTML preview로 수행한다.

## Scope

- 모든 원천 중심선 chain에 대해 좌/우 offset line 생성
- 협폭 도로도 `CENTERLINE` 없이 side-only graph로 통일
- 교차로 clipping, cross-type intersection resolution, junction consolidation, stub prune 재정의
- `TRANSITION_CONNECTOR` 제거 또는 최소화
- `GAP_BRIDGE`, `SAME_SIDE_CORNER_BRIDGE`, `CROSS_SIDE_CORNER_BRIDGE`, `ELEVATOR_CONNECTOR` 유지
- 최종 node/segment snapshot 및 카카오맵 preview 생성

## Non-Goals

- 기존 02A와 동시에 운영되는 이중 모델 유지
- 요청 시점 동적 graph 생성
- GraphHopper import 전환 자체
- 횡단보도 endpoint dataset 의미 판정 확정

## Problem Summary

- 02A의 `CENTERLINE` 예외는 협폭 도로에서 실제 보행 흐름보다 중심축 경로를 과도하게 남긴다.
- `CENTERLINE`과 `SIDE_LEFT/RIGHT`가 함께 있으면 transition과 junction이 복잡해지고, 보도 코너/교차로에서 잘못된 연결 또는 미연결이 동시에 발생한다.
- 현재 preview에서는 junction pocket 안에 여러 node가 남고, cross-side 교차에서 교차점 node 승격과 stub 제거가 불완전하다.
- 따라서 02B는 `CENTERLINE`을 제거하고, 처음부터 **모든 도로를 side-only topology**로 정규화해 junction 정리를 단순화한다.

## Success Criteria

- [ ] 모든 chain에 `SIDE_LEFT`, `SIDE_RIGHT`가 생성된다.
- [ ] `CENTERLINE`과 `TRANSITION_CONNECTOR` 없이도 교차로/협폭 도로 연결성이 유지된다.
- [ ] 하나의 junction pocket 안에 있는 node 후보가 canonical node 하나로 병합된다.
- [ ] `single-node junction`으로 분류된 pocket은 attach point가 canonical node 하나로 수렴한다.
- [ ] `corner pair junction`과 `multi-corner complex junction`은 shortcut 없이 코너별 anchor로만 수렴한다.
- [ ] `SIDE_LEFT × SIDE_RIGHT`, `SIDE × bridge` 교차가 유효 junction일 때만 node로 승격된다.
- [ ] 교차로 pocket 안 `<= 3m` stub와 micro-loop가 bridge 생성 전에 제거된다.
- [ ] bridge 생성 후 pocket 내부 `<= 3m` tail과 micro-loop가 다시 제거된다.
- [ ] `CROSS_SIDE_CORNER_BRIDGE`는 교차로 코너에서만 생성되고 일반 mid-block 구간에서는 생성되지 않는다.
- [ ] 같은 pocket 안에서 `CROSS_SIDE_CORNER_BRIDGE`와 `GAP_BRIDGE`가 같은 역할로 중복 생성되지 않는다.
- [ ] 교차 후 남는 돌출 stub가 staged prune으로 제거된다.
- [ ] 해운대 5km preview에서 교차로 node 중복과 cross-side 돌출이 줄어든다.

## Inputs

- `etl/raw/N3L_A0020000_26.shp`
- `etl/raw/N3L_A0020000_26.dbf`
- `etl/raw/stg_crosswalks_ready.csv`
- `etl/raw/subway_elevator.csv`
- `runtime/etl/centerline-load/road_nodes_snapshot.csv`
- `runtime/etl/centerline-load/road_segments_snapshot.csv`
- `etl/common/centerline_loader.py`
- `db/schema.sql`

## Canonical Decision

- 운영 graph는 `CENTERLINE` 없이 `SIDE_LEFT`, `SIDE_RIGHT` 중심으로 구성한다.
- 협폭 도로도 예외 없이 좌/우 보행선을 만든다.
- 교차로 연결성은 `Cross-Type Intersection Resolution + Junction Pocket Cleanup + Junction Consolidation`으로 해결한다.
- `TRANSITION_CONNECTOR`는 원칙적으로 제거한다.
  - 정말 필요한 경우만 후속 예외로 재도입 검토

## Segment Types

- `SIDE_LEFT` — 모든 도로 축의 좌측 보행선
- `SIDE_RIGHT` — 모든 도로 축의 우측 보행선
- `GAP_BRIDGE` — 같은 side corridor 단절 복구
- `SAME_SIDE_CORNER_BRIDGE` — 교차로 코너의 same-side fragment 연결
- `CROSS_SIDE_CORNER_BRIDGE` — 교차로 코너에서만 허용되는 cross-side fragment 연결
- `CROSSING` — 횡단보도 연결
- `ELEVATOR_CONNECTOR` — 엘리베이터 연결

> **시각화 매핑 필수**: `subway_elevator_preview.py`의 `segmentStyles` 딕셔너리에
> `SAME_SIDE_CORNER_BRIDGE`와 `CROSS_SIDE_CORNER_BRIDGE` 항목이 없으면
> JavaScript fallback으로 `segmentStyles.CENTERLINE`(`#111827` ≈ 검정)이 적용된다.
> 현재 preview의 **검은 삼각형**은 이 fallback이 원인이다.
> 두 타입을 style map에 추가하는 것이 디버깅의 첫 번째 단계다.
>
> | 타입 | 권장 색상 |
> |------|----------|
> | `SAME_SIDE_CORNER_BRIDGE` | `#f97316` (주황) |
> | `CROSS_SIDE_CORNER_BRIDGE` | `#8b5cf6` (보라) |

## Node Types

- `INTERSECTION_BOUNDARY`
- `CHAIN_JOIN`
- `CROSSING_ATTACH`
- `ELEVATOR_ATTACH`
- `GRAPH_NODE`
- `DEAD_END`

## Geometry Pipeline

### 1. Intersection Zone

- 원천 중심선 temp graph에서 `degree >= 3` root를 `intersection_root`로 식별한다.
- root 주변 반경은 `max(roadWidth / 2, floorMeter)`로 계산한다.
- 이 버퍼를 `intersection zone`으로 정의한다.

### 2. Chain Merge

- 중심선 작은 edge를 교차로 zone 사이 corridor chain으로 merge한다.
- chain 경계:
  - intersection zone 진입/이탈점
  - dead-end
  - 명시적 속성 단절점

### 3. Universal Offset Generation

- 모든 chain에 대해 `SIDE_LEFT`, `SIDE_RIGHT`를 생성한다.
- 기본 offset:
  - `offsetMeter = max(roadWidth / 2, minimumSideOffsetMeter)`
- 협폭 도로에서는 좌/우 선이 과도하게 겹치지 않도록 아래 중 하나를 적용한다.
  - `roadWidth / 2 - alpha`
  - 최소 side separation cap

### 4. Intersection Clipping

- 생성된 모든 side line에서 `intersection zone` 내부를 `difference`로 제거한다.
- 목적:
  - 교차로 한복판으로 파고드는 side line 제거
  - 이후 connector/bridge가 교차로 경계 기준으로만 복구되게 만들기

### 5. Intersection Boundary Node Confirmation

- clipping 직후 교차로 경계 endpoint를 우선 junction candidate로 수집한다.
- 이 점들은 이후 semantic merge의 입력이 된다.

### 6. Pass 1 Stub Prune

- connector 생성 전, 교차로 경계 안쪽에 남은 짧은 돌출 조각을 제거한다.
- 기준:
  - `stubPruneLengthMeter`
  - dead-end
  - 교차로 경계 안쪽 또는 바로 인접한 잔여 geometry

### 7. Phase A — Base Line Cross-Type Resolution + Pass 1.5 Tail Prune

> **현재 코드 버그**: bridge를 먼저 생성한 뒤 cross-type resolution을 실행함.
> 이로 인해 bridge가 unclean 엔드포인트에서 생성되어 삼각 micro-loop가 발생한다.
> 아래 두 단계(7A/7B)는 bridge 생성 **전에** base line만을 대상으로 먼저 수행해야 한다.

#### 7A. Base Line에 대한 Cross-Type Resolution

- `split_base_lines()` 결과 **(bridge 없이)**를 대상으로 `SIDE_LEFT × SIDE_RIGHT` 교차를 먼저 처리한다.
- `SIDE_LEFT × SIDE_RIGHT` 판정:
  - 같은 `intersection_root` 기준 `intersection_zone_radius * 1.5` 이내
  - 같은 `arm-vector sector`
  - 교차 후 양쪽이 모두 실제로 이어지는 유효 junction
  → 모두 만족 시: 교차점을 split event로 등록
  → 불만족 시: 교차점을 split event로 등록하되 결과 piece를 `cross-type tail` 후보로 마킹

#### 7B. Cross-Type Tail Prune (Pass 1.5)

- 7A 직후, base line split 결과에서 `cross-type tail` 마킹된 조각을 제거한다.
- **threshold: `CROSS_TYPE_TAIL_PRUNE_M`** — `STUB_MAX_LENGTH_M`(1m)이 아닌 별도 상수
  - 권장 초기값: `5.0m`
  - 이유: 이미지에서 관찰된 꼬투리는 수 m 길이이며, 1m threshold로는 제거되지 않는다
- 추가 조건: tail piece가 dead-end이고 intersection zone 방향으로 향하는 경우에만 제거
  - dead-end가 아닌 piece (양쪽이 연결된 경우)는 tail 후보에서 제외
- `cross_type_tail_prune_count`를 리포트에 기록한다

### 8. Junction Pocket Cleanup (bridge 생성 전)

> **순서 필수**: 이 단계는 bridge 생성(Step 9) **전에** 실행해야 한다.
> 현재 코드는 bridge 후 cleanup을 실행하므로 삼각형 bridge가 cleanup 전에 이미 생성된다.

- pocket 정의:
  - 동일 `intersection_root`의 `intersection zone` 내부
  - 반경 `junctionPocketRadiusMeter = 3m`
- pocket 내부에서:
  - node 후보를 cluster해 canonical node 하나로 병합
  - 두 endpoint가 모두 같은 pocket에 속하고 길이 ≤ `junctionPocketRadiusMeter`인 segment 제거 (micro-loop 포함)
  - dead-end 형태이고 길이 ≤ `JUNCTION_MERGE_ARTIFACT_PRUNE_M`인 artifact 제거
  - **bridge source가 되어선 안 되는 dead-end 조각은 이 단계에서 제거**
- 목적:
  - pocket 안 잔여 stub가 bridge source로 재사용되어 삼각형 micro-loop를 만드는 현상 차단
  - 교차점 주변 삼각형 / 루프 bridge 생성 근본 차단

### 9. Junction Archetype Classification + Anchor Selection

> **핵심 원칙**: bridge는 junction을 만드는 수단이 아니라, canonical junction으로 닫히지 않는 잔여 단절만 복구하는 수단이다.
> 따라서 bridge 생성 전에 pocket별 junction 구조를 먼저 확정한다.

#### 9A. Junction Archetype Classification

- 각 `intersection_root` 또는 merged pocket을 아래 archetype 중 하나로 분류한다.
  - `single-node junction`
  - `corner pair junction`
  - `multi-corner complex junction`
- `single-node junction` 허용 조건은 모두 만족해야 한다.
  - pocket 내부 attach point의 최대 pairwise distance가 `JUNCTION_POCKET_RADIUS_M` 이내
  - sector spread가 하나의 compact cluster 또는 같은 교차 event centroid 주변에 집중됨
  - pocket 내부 crosswalk/elevator attach가 별도 코너 의미를 강제하지 않음
  - collapse 후 생성되는 edge가 교차로를 shortcut으로 관통하지 않음
- 위 조건을 만족하지 않으면 single-node collapse를 금지하고, `corner pair` 또는 `multi-corner complex`로 남긴다.
- `multi-corner complex junction`은 넓은 사거리, 겹친 root, 복합 횡단보도, school-zone island처럼 한 점 collapse가 실제 보행 topology를 망가뜨릴 수 있는 경우의 기본 fallback이다.

#### 9B. Junction Anchor Selection

- `single-node junction`:
  - pocket당 canonical anchor 하나만 선택한다.
  - anchor 후보 우선순위:
    1. incident edge가 가장 많은 endpoint cluster center
    2. 유효 `SIDE_LEFT × SIDE_RIGHT` cross event centroid
    3. `intersection_root` center
- `corner pair junction`:
  - 같은 root 안에서 코너별 최대 2개 anchor만 선택한다.
  - 같은 sector 안의 나머지 attach point는 bridge source가 아니라 해당 anchor로 snap 대상이 된다.
- `multi-corner complex junction`:
  - sector별 또는 corner별 anchor를 유지한다.
  - 서로 다른 corner anchor 사이를 무조건 merge하지 않는다.
- anchor 외 endpoint 처리:
  - 같은 root + 같은 sector + anchor radius 안에 있으면 endpoint를 anchor로 snap한다.
  - anchor로 snap된 endpoint는 bridge source/target 후보에서 제외한다.
  - anchor snap으로 해결된 pocket은 bridge 생성 단계에서 이미 closed로 간주한다.

#### 9C. Pocket Bridge Suppression State

- pocket별로 `claimed endpoint`, `claimed sector`, `closed pocket role`을 기록한다.
- 같은 endpoint는 bridge source 또는 target으로 한 번만 사용할 수 있다.
- 같은 sector/side 역할은 기본적으로 max 1 bridge만 허용한다.
- `single-node junction`으로 닫힌 pocket 내부에서는 `GAP_BRIDGE`를 생성하지 않는다.
- `SAME_SIDE_CORNER_BRIDGE`가 해결한 source/target은 `CROSS_SIDE_CORNER_BRIDGE`와 `GAP_BRIDGE` 후보에서 제외한다.
- `CROSS_SIDE_CORNER_BRIDGE`가 해결한 pocket pair에는 같은 역할의 `GAP_BRIDGE`를 금지한다.

### 10. Bridge Generation (cleaned + anchored base lines 기반)

- **입력**: 7A/7B, Step 8 cleanup, Step 9 archetype/anchor snap이 완료된 cleaned base lines
- 일반 corridor 단절: `GAP_BRIDGE`
- 교차로 코너 same-side 단절: `SAME_SIDE_CORNER_BRIDGE`
- 교차로 코너 cross-side 단절: `CROSS_SIDE_CORNER_BRIDGE`
- pocket 내부 연결 우선순위:
  1. canonical node merge / anchor snap
  2. `SAME_SIDE_CORNER_BRIDGE`
  3. `CROSS_SIDE_CORNER_BRIDGE`
  4. `GAP_BRIDGE`
- `GAP_BRIDGE`는 junction pocket 내부 복구 수단이 아니다.
  - source 또는 target이 `JUNCTION_POCKET_RADIUS_M` 안에 있고 해당 pocket이 open 상태가 아니면 생성하지 않는다.
  - pocket 경계 밖으로 살짝 나온 endpoint라도 같은 root/sector anchor에 snap 가능하면 `GAP_BRIDGE` 후보에서 제외한다.
- `CROSS_SIDE_CORNER_BRIDGE` 허용 조건 (모두 만족):
  - 같은 `intersection_root`
  - 같은 pocket 또는 같은 pocket pair
  - arm-vector 기준 인접 arm / 코너 관계
  - source/target 모두 dead-end 또는 boundary endpoint
  - source/target이 anchor snap이나 canonical merge로 이미 해결되지 않음
  - 직선 또는 2-segment 경로가 pocket 내부를 크게 벗어나지 않음
  - mid-block 횡단 형태 금지
- bridge 개수 상한:
  - same root + same sector + same bridge role 기준 max 1
  - 같은 rounded source/target endpoint pair 기준 max 1
  - bridge끼리 교차하거나 micro-loop를 만드는 후보는 생성 버그로 로깅 후 스킵
- attach target이 line interior면 split event를 추가한다.

### 11. Combined Cross-Type Resolution (bridge + base lines)

- cleaned base lines + bridge segments를 합친 전체 geometry를 대상으로 2차 cross-type resolution을 수행한다.
- 이 단계에서 포함하는 조합 (bridge×side 교차만 추가):
  - `SIDE_LEFT / SIDE_RIGHT × GAP_BRIDGE`
  - `SIDE_LEFT / SIDE_RIGHT × SAME_SIDE_CORNER_BRIDGE`
  - `SIDE_LEFT / SIDE_RIGHT × CROSS_SIDE_CORNER_BRIDGE`
- 이 단계에서도 교차 후 짧은 꼬리는 `CROSS_TYPE_TAIL_PRUNE_M`으로 제거한다.
- 제외 조합:
  - bridge × bridge (생성 버그로 간주, 로깅 후 스킵)
  - `SIDE_LEFT × SIDE_RIGHT` (Step 7A에서 이미 처리)

### 12. Post-Bridge Pocket Reconciliation

> bridge 생성 후에도 bridge endpoint, side endpoint, split event가 다시 작은 tail이나 다중 node를 만들 수 있으므로 pocket 내부를 한 번 더 닫는다.

- 적용 대상:
  - `SIDE_LEFT`
  - `SIDE_RIGHT`
  - `SAME_SIDE_CORNER_BRIDGE`
  - `CROSS_SIDE_CORNER_BRIDGE`
  - `GAP_BRIDGE`
- 제외 대상:
  - `ELEVATOR_CONNECTOR`
  - 이후 별도 의미 판정이 필요한 feature connector
- 처리 순서:
  1. bridge endpoint와 side endpoint를 pocket anchor로 재cluster
  2. `single-node junction` pocket은 canonical node 하나로 재snap
  3. `corner pair`/`multi-corner` pocket은 코너별 anchor로만 재snap
  4. pocket 내부 `<= 3m` dangling tail 제거
  5. pocket 내부 micro-loop 제거
  6. 같은 role의 `CROSS_SIDE_CORNER_BRIDGE + GAP_BRIDGE` 중복이 발견되면 priority가 낮은 bridge 제거
- 이 단계의 prune은 pocket 내부 artifact 전용이다.
  - 일반 corridor 단절을 제거하지 않는다.
  - feature connector endpoint를 임의로 옮기지 않는다.

### 13. Junction Consolidation

- `build_node_snapshots()` 전에 semantic merge를 수행한다.
- 병합 대상:
  - Step 12까지 정리된 모든 segment의 endpoint
- 규칙:
  - `junctionMergeRadiusMeter`
  - same root / same sector 제약
  - 같은 junction pocket으로 보이는 후보만 merge
- cluster별 canonical node 1개만 남기고 incident edge endpoint를 재연결한다.
- **edge의 첫/마지막 좌표도 canonical node 좌표로 함께 업데이트한다** (geometry 불일치 방지)

### 14. Pass 2.5 Stub Prune

- junction merge와 post-bridge reconciliation 이후 생긴 매우 짧은 dangling artifact만 제거한다.
- threshold: `junctionMergeArtifactPruneM = 0.5m`
- pocket 내부 tail threshold: `POST_BRIDGE_POCKET_TAIL_PRUNE_M = 3.0m`
- 이 단계는 **merge/bridge 부산물 제거 전용**이며, 일반 tail prune이나 cross-type tail prune과 혼용하지 않는다.

### Threshold 분류 정리

| 상수 | 용도 | 권장값 |
|------|------|--------|
| `STUB_MAX_LENGTH_M` | 최소 보행 segment 기준 | 1.0m |
| `CROSS_TYPE_TAIL_PRUNE_M` | cross-type 교차 후 dead-end tail 제거 | 5.0m |
| `JUNCTION_POCKET_RADIUS_M` | pocket 내 micro-loop 제거 반경 | 3.0m |
| `JUNCTION_MERGE_ARTIFACT_PRUNE_M` | junction merge 후 artifact 제거 | 0.5m |
| `POST_BRIDGE_POCKET_TAIL_PRUNE_M` | bridge 생성 후 pocket 내부 dangling tail 제거 | 3.0m |

### 15. Feature Projection

- 횡단보도 endpoint는 nearest side line에 projection
- 엘리베이터 point도 nearest side line에 projection
- attach target이 line interior면 split event를 추가한다.

### 16. Final Snapshot

- semantic merge와 prune이 끝난 geometry에 대해서만 `build_node_snapshots()`를 수행한다.
- 최종 `road_nodes`, `road_segments` snapshot을 생성한다.

## DB Load Design

### Node Generation Rule

- 최종 `road_nodes`는 semantic merge가 끝난 canonical junction 좌표만 사용한다.
- 부동소수점 오차 보정용 cluster merge는 `build_node_snapshots()` 내부에 남기되, 의미론적 merge 책임은 그 이전 단계에서 처리한다.

### Segment Generation Rule

- 최종 `road_segments`는 side-only graph를 저장한다.
- `CENTERLINE`과 `TRANSITION_CONNECTOR`는 기본적으로 생성하지 않는다.
- 각 segment는 최소 다음을 유지한다.
  - `edgeId`
  - `fromNodeId`
  - `toNodeId`
  - `geom`
  - `lengthMeter`
  - `walkAccess`
  - `segmentType`

### Replace Strategy

- 적재 시 기존 `road_nodes`, `road_segments`를 truncate 후 02B side-only graph로 재적재한다.
- 다만 DB 적재 전에는 반드시 preview-first 검증을 통과해야 한다.

## Implementation Plan

### 즉시 해결 (검은 삼각형 색상 문제)

0. `subway_elevator_preview.py`의 `segmentStyles`에 두 항목을 추가한다:
   ```python
   "SAME_SIDE_CORNER_BRIDGE":  {"strokeColor": "#f97316", "strokeWeight": 3, "strokeOpacity": 0.94},
   "CROSS_SIDE_CORNER_BRIDGE": {"strokeColor": "#8b5cf6", "strokeWeight": 3, "strokeOpacity": 0.94},
   ```
   legend에도 두 항목을 추가한다. 이 변경만으로 검은 삼각형의 실제 타입이 시각적으로 식별 가능해진다.

### 파이프라인 순서 수정 (삼각형 제거의 근본 해결)

현재 코드의 실행 순서: `bridge 생성 → split → cross-type resolution → pocket cleanup`
**올바른 순서**:

1. 02A에서 `CENTERLINE` 분기와 `TRANSITION_CONNECTOR` 경로를 제거한다.
2. 모든 chain에 대해 `SIDE_LEFT`, `SIDE_RIGHT` 생성으로 통일한다.
3. 협폭 도로 offset safety rule을 추가한다.
4. `intersection clipping` 후 `Pass 1 Stub Prune`을 실행한다.
5. **base line만을 대상으로** `SIDE_LEFT × SIDE_RIGHT` Cross-Type Resolution을 수행한다.
6. 교차 후 dead-end tail을 `CROSS_TYPE_TAIL_PRUNE_M = 5.0m`으로 제거한다 (Pass 1.5).
7. **`Junction Pocket Cleanup`을 bridge 생성 전에 수행한다.**
   - 두 endpoint가 같은 pocket에 속하고 길이 ≤ 3m인 segment 제거 (micro-loop 차단)
   - dead-end 길이 ≤ 0.5m artifact 제거
8. pocket별 `single-node`, `corner pair`, `multi-corner complex` archetype을 분류한다.
9. archetype별 canonical anchor를 선택하고, anchor로 해결 가능한 endpoint를 bridge 후보에서 제외한다.
10. pocket별 `claimed endpoint`, `claimed sector`, `closed pocket role` 상태를 만든다.
11. cleaned + anchored base lines 기반으로 `SAME_SIDE_CORNER_BRIDGE`, `CROSS_SIDE_CORNER_BRIDGE`, `GAP_BRIDGE`를 이 순서로 생성한다.
    - 같은 endpoint는 bridge source/target으로 1회만 사용
    - same root + same sector + same bridge role 기준 max 1
    - `CROSS_SIDE_CORNER_BRIDGE`가 해결한 pocket pair에는 같은 역할의 `GAP_BRIDGE` 금지
12. cleaned base lines + bridge segments를 결합하고 bridge×side 교차에 대해 Combined Cross-Type Resolution을 수행한다.
13. **Post-Bridge Pocket Reconciliation**을 수행한다.
    - bridge endpoint와 side endpoint를 pocket anchor로 재cluster
    - pocket 내부 `<= 3m` dangling tail 제거
    - pocket 내부 micro-loop 제거
    - 같은 역할의 cross-side + gap bridge 중복 제거
14. `Junction Consolidation`을 `build_node_snapshots()` 전에 수행한다.
    - `JUNCTION_MERGE_RADIUS_M` 이내 endpoint를 semantic merge
    - incident edge의 첫/마지막 좌표도 canonical node 좌표로 업데이트
15. `Pass 2.5 Stub Prune`을 junction merge 뒤에 수행한다.
    - `junctionMergeArtifactPruneM = 0.5m`
    - `postBridgePocketTailPruneM = 3.0m`
16. 최종 snapshot을 생성한다.
17. 카카오맵 SDK preview를 생성한다.

## Validation Plan

### 리포트 항목
- `CENTERLINE`, `TRANSITION_CONNECTOR` count가 0인지 확인한다.
- `SIDE_LEFT`, `SIDE_RIGHT` coverage를 전체 chain 수와 비교한다.
- `crossTypeIntersectionCount` — 유효 junction 승격 건수
- `crossTypeTailPruneCount` — Pass 1.5에서 제거된 꼬투리 건수 (새 항목)
- `junctionPocketCleanupCount`, `junctionPocketRemovedNodeCount`, `junctionPocketRemovedStubCount`
- `junctionArchetypeCounts` — `single-node`, `corner-pair`, `multi-corner-complex` 분류 수
- `junctionAnchorCount`, `anchorSnappedEndpointCount`
- `bridgeSuppressedInsidePocketCount`
- `bridgeSuppressedByClaimCount`
- `duplicateBridgeSuppressedCount`
- `postBridgePocketTailPruneCount`
- `postBridgePocketMicroLoopPruneCount`
- `junctionConsolidationClusterCount`, `mergedJunctionNodeCount`
- `pass1StubPruneCount`, `pass15TailPruneCount`, `pass2StubPruneCount`, `pass25PocketTailPruneCount`
- `singleNodeJunctionMultiNodeResidualCount` — single-node junction인데 2개 이상 node가 남은 pocket 수
- `crossSideGapDuplicatePocketCount` — 같은 역할의 cross-side + gap bridge 중복 발생 pocket 수
- `pocketInternalGapBridgeCount` — pocket 내부에 남은 `GAP_BRIDGE` 수

### Preview 시각 검증 체크리스트
- [ ] `SAME_SIDE_CORNER_BRIDGE`가 주황(#f97316)으로, `CROSS_SIDE_CORNER_BRIDGE`가 보라(#8b5cf6)로 표시되는지 확인
- [ ] 기존 preview의 **검은 삼각형이 사라졌는지** 확인 (fallback 색상 제거 여부)
- [ ] 주황/보라로 표시된 bridge가 삼각형/루프 형태를 만들지 않는지 확인
- [ ] single-node junction으로 분류된 pocket 안 node가 하나만 남는지 확인
- [ ] corner pair / multi-corner pocket에서 과도한 shortcut merge가 생기지 않는지 확인
- [ ] `SIDE_LEFT × SIDE_RIGHT` 교차 후 꼬투리(tail)가 제거되는지 확인
- [ ] bridge 생성 후 pocket 내부 `<= 3m` tail이 남지 않는지 확인
- [ ] 유효 junction에서만 교차점 node가 생기고, 무효 교차는 tail만 제거되는지 확인
- [ ] 하나의 junction pocket 안에 node가 하나로 수렴하는지
- [ ] 같은 pocket에서 `CROSS_SIDE_CORNER_BRIDGE`와 `GAP_BRIDGE`가 같은 역할로 중복되지 않는지 확인
- [ ] pocket 내부 `GAP_BRIDGE`가 일반 corridor 단절 복구가 아닌 junction 대체 수단으로 생성되지 않는지 확인
- [ ] `CROSS_SIDE_CORNER_BRIDGE`가 교차로 코너에서만 생성되는지
- [ ] 협폭 도로에서도 side-only graph가 자연스럽게 이어지는지

## Acceptance Risks

- 협폭 도로에서 좌/우 side line이 물리적으로 충분히 분리되지 않을 수 있다.
- side-only graph는 보행축 표현은 단순해지지만, 매우 좁은 골목에서는 실제 보도 구분이 없는 공간을 인위적으로 좌/우로 나눌 수 있다.
- 따라서 02B는 02A보다 junction 정리는 단순해질 가능성이 높지만, 협폭 도로 geometry fidelity는 별도 검증이 필요하다.

## Handoff

- Build: `implement-feature`
- Validation: `check`
- Ship note: 02B는 02A의 대안 설계다. DB 재적재 전까지는 preview-first로만 검증한다.
