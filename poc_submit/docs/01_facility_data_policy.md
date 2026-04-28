# 편의시설 데이터 정책

이 문서는 PoC 제출본의 최종 편의시설 표시 기준입니다. 정식 기준은 `C:/Users/SSAFY/workspace/S14P31E102/Docs/ADR/2026-04-28_BE_장소_카테고리_및_접근성_필터_정책.md`와 `Docs/ARD/ERD_v3.md`를 따릅니다.

## 최종 category

| category | 표시명 | 기준 |
|---|---|---|
| `FOOD_CAFE` | 음식·카페 | 음식점, 카페, 제과점 등 식음 목적지 |
| `TOURIST_SPOT` | 관광지 | 관광지, 공원, 해변 등 방문 목적지 |
| `ACCOMMODATION` | 숙박 | 관광숙박, 일반숙박, 생활숙박 |
| `HEALTHCARE` | 의료·보건 | 병원, 의원, 치과, 한의원, 보건소, 종합병원 |
| `WELFARE` | 복지·돌봄 | 노인/장애인/아동/사회복지시설, 경로당, 요양시설 |
| `PUBLIC_OFFICE` | 공공기관 | 주민센터, 지자체 청사, 공단, 우체국, 파출소, 지구대 |
| `ETC` | 기타 | 보행약자 편의시설 원천 근거는 있으나 대표 서비스 카테고리로 단정하기 어려운 장소 |

## category에서 제외한 값

| 기존 값 | 최종 처리 |
|---|---|
| `RESTAURANT` | `FOOD_CAFE`로 통합 |
| `TOILET` | category로 사용하지 않고 `accessibleToilet` feature로 관리 |
| `CHARGING_STATION` | category로 사용하지 않고 `chargingStation` feature로 관리 |
| `BARRIER_FREE_FACILITY` | 실제 시설 성격에 따라 7개 category 중 하나로 분류 |
| `BUS_STATION` | 대중교통 도메인에서 관리 |
| `ELEVATOR` | 장소 category가 아니라 접근성 feature 또는 도시철도 엘리베이터 데이터로 관리 |

## 접근성 featureType

| featureType | 표시명 |
|---|---|
| `accessibleToilet` | 장애인 화장실 |
| `elevator` | 엘리베이터 |
| `chargingStation` | 전동보장구 충전 가능 |
| `ramp` | 경사로 |
| `accessibleEntrance` | 접근 가능 출입구 |
| `autoDoor` | 자동문 |
| `accessibleParking` | 장애인 주차장 |
| `stepFree` | 단차 없음 |
| `accessibleRoom` | 장애인 객실 |
| `guidanceFacility` | 안내 설비 |

## 최종 분포

| category | count |
|---|---:|
| `ACCOMMODATION` | 246 |
| `ETC` | 11,287 |
| `FOOD_CAFE` | 814 |
| `HEALTHCARE` | 391 |
| `PUBLIC_OFFICE` | 279 |
| `TOURIST_SPOT` | 244 |
| `WELFARE` | 303 |

전동보장구 충전소 원천 장소 197건은 모두 `category=ETC`와 `featureType=chargingStation`을 함께 가진다.
