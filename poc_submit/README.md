# 부산 보행약자 지도 PoC

부산 지역 보행약자 이동 지원을 위해 계단 후보, 횡단보도, 편의시설 접근성, 도로 경사/노면/폭을 한 화면에서 검토하는 정적 HTML PoC입니다.

## 현재 최종 기준

- 계단 후보는 P1/P2만 지도 기본 대상으로 사용합니다. 총 790개입니다.
- 장소 category는 ERD v3 기준 7개만 사용합니다.
- 화장실과 전동보장구 충전소는 장소 category가 아니라 접근성 featureType으로 조회합니다.
- 도로 보행 등급은 아직 확정하지 않고, 현재 지도에서는 경사 구간, 노면 선 모양, 폭 5단계만 해석합니다.
- 도로 레이어는 용량과 렌더링 부담이 커서 기본 OFF이며, 선택 구군만 로드합니다.

## 실행

`index.html`을 브라우저로 열면 됩니다. 외부 서버 없이 `assets/data`의 정적 JS 데이터를 읽습니다.

## 핵심 산출물

| 경로 | 설명 |
|---|---|
| `index.html` | 지도 PoC 본체 |
| `assets/data/facilities-data.js` | ERD v3 기준 편의시설 지도 데이터 |
| `assets/data/busan-stair-review-keep-review-data.js` | P1/P2 계단 후보 790개 |
| `assets/data/road-slope-surface/` | 구군별 도로 경사/노면/폭 데이터 |
| `data/final/facilities/places_erd.csv` | DB `places` 반영 후보 |
| `data/final/facilities/place_accessibility_features_erd.csv` | DB `place_accessibility_features` 반영 후보 |
| `data/final/stairs/stair_candidates_p1_p2.csv` | 지도 표시 기준 계단 후보 |
| `docs/` | PoC 기준과 시행착오 기록 |

## 최종 수치

| 항목 | 개수 |
|---|---:|
| 편의시설 장소 | 13,564 |
| 편의시설 접근성 feature row | 42,565 |
| 접근성 feature 보유 장소 | 12,309 |
| 계단 P1/P2 후보 | 790 |

## 표시 기준

장소 category는 `FOOD_CAFE`, `TOURIST_SPOT`, `ACCOMMODATION`, `HEALTHCARE`, `WELFARE`, `PUBLIC_OFFICE`, `ETC`만 사용합니다.

빠른 접근성 필터는 `accessibleToilet`, `elevator`, `chargingStation`을 우선합니다. 그 외 `ramp`, `accessibleEntrance`, `autoDoor`, `accessibleParking`, `stepFree`, `accessibleRoom`, `guidanceFacility`는 상세 정보와 후속 필터 후보로 유지합니다.
