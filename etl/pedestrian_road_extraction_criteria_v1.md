# Pedestrian Road Extraction Criteria v1

이 문서는 Kakao basemap 위에서 보행자 도로 후보 `LineString`/`Point`를 재구성할 때 적용할 기준이다. 입력 원천은 CSV 또는 materialized graph의 기존 도로 후보 선이며, Kakao SDK는 좌표 렌더링과 시각 검수용 basemap으로만 사용한다.

## 입력

- `road_segments.csv` 계열의 `LINESTRING` segment
- `road_nodes.csv` 계열의 `POINT` node
- 대상 지역 bbox
- 기본 좌표계는 `EPSG:4326`

## 기본 도로 레이어

1. 대상 bbox에 닿는 `SIDE_LINE` segment를 수집한다.
2. 아주 짧게 튀어나온 dangling spur는 기반도로에서 먼저 제거한다.
   - 한쪽 endpoint만 dangling이고 길이 `<= 14m`
   - 양쪽 endpoint가 모두 dangling이고 길이 `<= 7m`
3. 가까운 endpoint는 대표 node로 snap한다.
   - endpoint 간 거리 `<= 2.5m`
   - snap 대표점은 endpoint 좌표 평균
   - 3개 이상 endpoint cluster는 intersection hub로 본다.

## 연결 금지 기준

다음 후보는 기반도로에 연결하지 않는다.

1. 횡단보도 또는 도로 횡단 후보
   - 두 endpoint tangent 차이가 `62~118도`
2. 기존 기반도로 조각을 가로지르는 후보
   - 후보 bridge가 의도된 양끝점 근처가 아닌 위치에서 기존 line piece와 교차
3. 긴 gap인데 반대편 평행 side-line 증거가 전혀 없는 후보
4. 도로 양쪽 선을 대각선으로 이어버리는 후보

## 같은 도로 연결 기준

다음 조건을 만족하면 같은 도로의 끊긴 구간으로 보고 bridge를 생성한다.

1. Short same-road gap
   - 거리 `<= 14m`
   - 양 endpoint tangent가 거의 반대 방향
   - bridge 방향이 양 endpoint의 바깥 방향과 잘 맞음
2. Long same-road gap
   - 거리 `<= 32m`
   - short gap보다 더 엄격한 tangent/alignment 조건 필요
3. Far same-road gap
   - 거리 `<= 48m`
   - 매우 엄격한 tangent/alignment 조건 필요
   - 가능한 경우 paired-side evidence 필요

## Paired-Side Evidence

복잡한 동네/곡선 도로에서는 한쪽 선만 보고 연결하면 오연결이 생긴다. 따라서 긴 bridge 후보는 근처에 평행한 다른 bridge 후보가 있는지 확인한다.

- 두 bridge 후보의 방향 차이 `<= 12도`
- 두 bridge 후보 사이 횡방향 거리 `3~18m`
- 진행 방향 projection이 서로 겹침
- bridge 길이 비율이 너무 크지 않음

이 조건을 만족하면 도로 양쪽 선이 함께 끊긴 것으로 보고 paired-side evidence가 있다고 판단한다.

## Visible Local Gap Fill

시각적으로 가까운 gap이 남는 문제를 보완하기 위한 후처리 기준이다.

1. 이미 수용된 기반도로 endpoint를 다시 검사한다.
2. endpoint degree가 조금 높아도 검사 대상에 포함한다.
   - 단, 명백한 대형 intersection hub는 제외한다.
3. 거리 `<= 28m`의 endpoint 쌍 중 다음을 만족하는 경우 bridge 후보로 본다.
   - tangent 관계가 횡단보도/수직 교차가 아님
   - bridge가 기존 기반도로를 가로지르지 않음
   - 적어도 한쪽 endpoint의 진행 방향과 bridge 방향이 자연스럽게 이어짐
   - 두 endpoint tangent가 완전히 무관하지 않음
4. 아주 짧은 gap은 paired-side evidence 없이도 허용할 수 있다.
   - 거리 `<= 10m`
   - 방향 정렬이 양호
5. 중간 거리 gap은 더 엄격하게 허용한다.
   - 거리 `<= 28m`
   - 방향 정렬이 양호하거나 paired-side evidence가 있음

## Corridor Continuation Across Junction

`Visible Local Gap Fill`만으로도 남는 gap은 대개 교차부, 횡단보도, 곡선부를 사이에 두고 같은 도로 corridor가 끊긴 경우다. 이 경우 기존 crossing block을 그대로 적용하면 실제로 이어져야 할 도로 양쪽 선이 계속 끊긴다.

다음 조건을 모두 만족하면 교차부를 사이에 둔 같은 도로 연속선으로 보고 bridge를 허용한다.

1. 두 endpoint 사이 거리는 `<= 55m`
2. 두 endpoint는 이미 수용된 기반도로 위의 endpoint이며, 대형 hub가 아니다.
3. 두 endpoint를 연결한 bridge 방향이 최소 한쪽 endpoint 진행 방향과 자연스럽게 이어진다.
4. 두 endpoint tangent가 완전한 수직/횡단보도 관계가 아니다.
5. bridge 주변에 같은 방향의 도로 line piece가 존재한다.
   - bridge midpoint 기준 `35m` 이내
   - bridge 방향과 line piece 방향 차이 `<= 20도`
6. crossing block은 완화한다.
   - 기존 기반도로를 가로질러도, 교차하는 선의 방향이 bridge와 거의 수직이고 gap의 양끝이 같은 corridor 방향이면 허용할 수 있다.
   - 단, bridge가 여러 unrelated line을 대각선으로 통과하면 여전히 차단한다.
7. 가능하면 paired-side evidence를 우선한다.
   - 반대편에도 비슷한 방향/길이의 gap 후보가 있으면 우선 허용한다.
   - paired-side evidence가 없어도 길이가 짧고 corridor direction evidence가 강하면 허용한다.

이 단계는 `Visible Local Gap Fill` 이후에 실행한다. 목적은 “이미 도로라고 판단한 line 위에서 남은 끊김”을 보완하는 것이며, 새로운 골목이나 횡단보도를 적극적으로 발견하는 단계가 아니다.

## 출력

출력은 다음 두 geometry로 분리한다.

- 도로 segment: GeoJSON `LineString`
- topology node: GeoJSON `Point`

CSV로 저장할 때는 기존 `road_nodes.csv`, `road_segments.csv` 스키마를 유지한다. 새로 생성한 bridge segment의 접근성 관련 상태값은 확정 데이터가 없으면 `UNKNOWN`으로 둔다.

## 검수 원칙

- Kakao basemap의 횡단보도 stripe를 직접 벡터로 읽을 수 없으므로, 횡단보도 여부는 geometry와 화면 검수로 판단한다.
- 자동 생성 결과는 최종 확정 데이터가 아니라 후보 기반도로다.
- 복잡한 지역은 `Rejected sample` 또는 debug overlay를 함께 보고 기준을 조정한다.

## Degree-1 Same-Side Continuation

`Corridor Continuation Across Junction`를 너무 넓게 적용하면 같은 도로의 반대편 side-line까지 대각선으로 연결되는 문제가 생긴다. 이 단계는 그런 과연결을 막기 위해 V4 계열의 보수적인 기반도로에서 다시 시작하고, 실제로 끊긴 endpoint만 최소 연결한다.

1. 대상 endpoint는 topology degree가 정확히 `1`인 node로 제한한다.
   - 이미 두 개 이상 segment가 물린 node는 교차부 또는 hub로 보고 자동 gap 연결 대상에서 제외한다.
2. 연결 후보는 다른 degree-1 endpoint와의 pair만 허용한다.
   - 한 endpoint는 최종적으로 하나의 bridge에만 참여할 수 있다.
   - 후보 선택은 단순 최단거리보다 tangent alignment와 same-side score를 우선한다.
3. 반대편 도로를 가로지르는 diagonal bridge는 금지한다.
   - bridge 방향이 양쪽 endpoint의 연장 방향과 맞지 않으면 제외한다.
   - bridge가 endpoint tangent line에서 크게 벗어나면 제외한다.
   - 기존 기반도로를 비스듬히 가로질러 여러 line을 통과하면 제외한다.
4. 같은 side-line의 짧은 끊김만 연결한다.
   - endpoint 간 거리 상한은 기본 `45m`다.
   - 두 endpoint 모두 bridge 방향과 자연스럽게 이어져야 한다.
   - 한쪽만 맞고 다른 쪽은 꺾이는 후보는 제외한다.
5. 최종 선택은 greedy one-to-one matching으로 한다.
   - score가 낮은 후보부터 선택한다.
   - 이미 선택된 endpoint가 포함된 후보는 버린다.

이 기준은 누락된 선을 적극적으로 메우기 위한 기준이 아니라, 사람이 보기에 "한 segment만 연결된 node끼리 같은 선상에서 끊긴 경우"를 보수적으로 잇기 위한 기준이다.

## Degree-1 Corner Dogleg Continuation

`Degree-1 Same-Side Continuation`은 직선 또는 거의 직선으로 끊긴 선을 잇는 기준이다. 그러나 실제 보도/도로 윤곽은 교차부 가장자리에서 ㄱ자 또는 완만한 꺾임으로 이어지는 경우가 있다. 이 경우 두 endpoint 사이를 단순 직선으로 잇거나, 반대편 side-line으로 대각 연결하면 안 된다. 대신 두 endpoint의 진행 방향이 만나는 corner point를 만들어 `LineString(endpoint A, corner point, endpoint B)` 형태로 연결한다.

1. 대상은 여전히 topology degree가 정확히 `1`인 endpoint pair로 제한한다.
2. 두 endpoint 사이 거리는 기본 `55m` 이하로 제한한다.
3. 두 endpoint의 outward tangent ray를 계산하고, 두 ray가 전방에서 만나는 경우만 dogleg 후보로 본다.
   - ray intersection이 각 endpoint에서 너무 멀면 제외한다.
   - corner point가 두 endpoint를 잇는 bounding box에서 크게 벗어나면 제외한다.
4. dogleg의 두 leg는 각각 자기 endpoint의 outward tangent와 자연스럽게 이어져야 한다.
   - 각 leg와 해당 endpoint tangent의 각도 차이는 `35도` 이하를 기본값으로 둔다.
   - 전체 꺾임은 `45도~135도` 범위를 우선한다.
5. 반대편 도로 side-line으로 건너가는 대각 bridge는 계속 금지한다.
   - dogleg가 기존 기반도로를 endpoint 주변이 아닌 곳에서 가로지르면 제외한다.
   - 두 leg 중 하나가 긴 대각선으로 여러 line을 관통하면 제외한다.
6. 같은 endpoint가 straight continuation과 dogleg continuation에 동시에 선택되면 straight continuation을 우선한다.
   - dogleg는 straight continuation 이후에도 남은 degree-1 endpoint만 대상으로 한다.
7. 최종 선택은 one-to-one matching으로 한다.
   - score가 낮은 후보부터 선택하고, 이미 사용된 endpoint가 포함된 후보는 버린다.

이 기준의 목적은 누락된 코너 윤곽을 복원하는 것이다. 새로운 골목을 발견하거나, 횡단보도/차도 횡단선을 만드는 기준이 아니다.

## Iterative Scan and Conservative Dogleg Filter

`Degree-1 Corner Dogleg Continuation` 이후에도 끊김이 남거나 불필요한 dogleg가 생길 수 있다. 최종 생성은 한 번의 후보 추가로 끝내지 않고, 다음 검증 루프를 반복한다.

1. 기반은 과연결이 적은 V4 계열 topology로 되돌려 시작한다.
2. 각 반복에서 현재 topology의 degree-1 endpoint만 다시 스캔한다.
3. straight continuation을 먼저 적용하고, dogleg continuation은 남은 endpoint만 대상으로 한다.
4. dogleg는 다음 추가 필터를 통과해야 한다.
   - 두 leg 길이의 비율이 과도하게 크지 않다.
   - dogleg corner가 두 endpoint 사이의 국소 bbox 밖으로 크게 튀어나가지 않는다.
   - dogleg 전체가 기존 기반도로 또는 이미 추가된 bridge를 endpoint 주변이 아닌 위치에서 가로지르지 않는다.
   - 후보 dogleg 주변에 같은 방향으로 이어지는 다른 side-line 근거가 있거나, 같은 corridor에서 비슷한 방향의 paired 후보가 존재한다.
5. dogleg가 한쪽 line을 따라가다가 반대편 side-line을 닫아버리는 cap 형태이면 제외한다.
   - 짧은 세로/가로 cap이 도로 폭을 가로지르는 경우는 보도 윤곽 연결이 아니라 과연결로 본다.
6. 반복은 새로 추가된 연결이 없거나 최대 반복 수에 도달하면 중단한다.
   - 기본 최대 반복 수는 `4`다.
   - 한 반복에서 추가된 endpoint는 다음 반복에서 다시 degree를 계산해 후보에서 제외한다.

이 루프의 목적은 사람이 찍은 이상적인 선처럼 "남은 끊김"을 점진적으로 줄이되, 이전 단계에서 확인된 무분별한 반대편 연결을 다시 만들지 않는 것이다.

## Iterative Self-Scan Repair Gate

해운대구 Kakao HTML 검수에서 같은 도로 side-line이 중간에 끊기거나, 교차부 주변에 불필요한 짧은 segment가 남는 패턴이 반복 확인되었다. 최종 HTML은 아래 self-scan repair gate를 통과한 결과만 검수 대상으로 삼는다.

1. 매 반복은 현재 topology에서 endpoint snap, bridge 정규화, same-side gap 연결, 불필요 segment 제거 순서로 실행한다.
   - 가까운 endpoint cluster는 먼저 대표점으로 snap한다.
   - 이미 같은 side-line으로 자연스럽게 이어진 node에는 새 bridge를 추가하지 않는다.
   - 추가 bridge를 만든 뒤 다시 제거 조건을 평가한다.
2. 같은 도로 side-line 연결은 보수적으로 허용한다.
   - `SIDE_LEFT`는 `SIDE_LEFT`끼리, `SIDE_RIGHT`는 `SIDE_RIGHT`끼리만 연결한다.
   - degree-1 endpoint 쌍은 거리 `<= 32m`, 두 endpoint의 outward tangent와 bridge 방향 차이 `<= 38도`를 기본 상한으로 둔다.
   - degree-2 이하의 짧은 micro gap은 거리 `<= 24m`, 방향 차이 `<= 30도`일 때만 허용한다.
   - 한쪽 endpoint가 이미 같은 side-line continuation을 갖고 있으면 추가 연결 후보에서 제외한다.
3. 제거 대상은 연결보다 먼저/나중에 모두 재검사한다.
   - 양 endpoint가 이미 다른 segment와 연결된 길이 `<= 8m` 조각은 `microLoop`로 제거한다.
   - 한쪽만 dangling이고 길이 `<= 18m`인 side-line은 `danglingTail`로 제거한다.
   - endpoint가 밀집 교차부 cluster에 붙어 있고 총 길이 `<= 42m`인 짧은 tail은 `denseIntersectionTail`로 제거한다.
   - 양 endpoint가 이미 연결된 길이 `<= 14m` bridge artifact는 제거한다.
4. 반복 수렴 조건을 명확히 둔다.
   - `snapped_endpoints + added_edges + removed_edges = 0`이면 통과한다.
   - 기본 최대 반복 수는 `8`이다. 최대 반복 후에도 actionable anomaly가 남으면 HTML은 확정본이 아니라 후보본으로 표시한다.
   - 한 반복에서 추가된 bridge는 다음 반복에서 endpoint degree를 다시 계산한 뒤 후보에서 제외될 수 있다.
5. 해운대구 5km graph-materialized 기준 관측값은 다음과 같다.
   - 원본: `26,179` nodes, `22,253` segments
   - self-scan 수렴 후: `13,158` nodes, `14,890` segments
   - 7회 반복 후 `remainingActionableAnomalies = 0`
   - 주요 제거/수정 사유는 `denseIntersectionTail`, `danglingTail`, `microLoop`, endpoint snap, same-side gap 연결이다.

이 gate는 지도 위 시각 검수에서 발견되는 "같은 도로 선의 중간 끊김"과 "교차부에 남은 불필요한 짧은 segment"를 줄이기 위한 확정 전 처리 기준이다. 새 골목, 횡단보도, 반대편 side-line 연결을 적극적으로 생성하는 기준으로 사용하지 않는다.

## Endpoint-to-Line Projection Snap

남은 빈 공간 중 일부는 `degree-1 endpoint` 반대편에 또 다른 endpoint가 있는 형태가 아니다. 긴 기반 line의 중간 지점 근처에서 짧게 끊긴 경우가 있으며, 이때 endpoint pair 탐색만 반복하면 계속 놓친다. 이 경우 endpoint를 기존 line 위의 projection point로 붙인다.

1. 대상은 topology degree가 정확히 `1`인 endpoint다.
2. 연결 대상은 기존 기반도로 또는 이전 반복에서 확정된 line의 내부 projection point다.
   - projection point가 대상 line의 endpoint에서 너무 가까우면 endpoint-to-endpoint 후보로 처리한다.
   - 같은 source line 또는 같은 추가 bridge의 자기 자신으로 붙이지 않는다.
3. projection 거리는 기본 `18m` 이하로 제한한다.
4. endpoint의 outward tangent가 projection 방향과 자연스럽게 이어져야 한다.
   - 직선 보강은 방향 차이 `35도` 이하를 기본값으로 한다.
   - 코너 보강은 짧은 dogleg로 만들 수 있으나, 기존 line을 가로지르는 cap 형태이면 제외한다.
5. projection snap은 교차부를 새로 만드는 기능이 아니다.
   - 횡단보도/차도 폭을 가로질러 반대편 side-line으로 붙는 후보는 제외한다.
   - 생성된 bridge가 기존 line 또는 다른 생성 bridge와 내부에서 X자로 교차하면 제거한다.
6. 모든 추가 bridge 생성 후 전역 교차 정리를 수행한다.
   - 추가 bridge끼리 내부 교차하면 점수가 낮은 하나만 남긴다.
   - 추가 bridge가 기존 기반도로를 endpoint/projection 주변이 아닌 곳에서 교차하면 제거한다.

이 기준은 시각적으로 끊긴 보도 윤곽을 line 중간에 정확히 접속하기 위한 기준이며, 도로망의 교차 링크를 임의로 추가하기 위한 기준이 아니다.
