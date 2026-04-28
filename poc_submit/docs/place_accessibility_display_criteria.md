# 장소 접근성 표시 기준

지도 UI는 ERD v3 기준으로 장소 category와 접근성 featureType을 분리해서 보여준다.

## 장소 category 필터

| 지도 표시 | ERD category |
|---|---|
| 음식·카페 | `FOOD_CAFE` |
| 관광지 | `TOURIST_SPOT` |
| 숙박 | `ACCOMMODATION` |
| 의료·보건 | `HEALTHCARE` |
| 복지·돌봄 | `WELFARE` |
| 공공기관 | `PUBLIC_OFFICE` |
| 기타 | `ETC` |

## 빠른 접근성 필터

| 지도 표시 | featureType |
|---|---|
| 장애인 화장실 | `accessibleToilet` |
| 엘리베이터 | `elevator` |
| 전동보장구 충전 가능 | `chargingStation` |

`TOILET`과 `CHARGING_STATION`은 더 이상 장소 category로 쓰지 않는다. 공중화장실 또는 충전소 원천 장소가 지도에 표시될 수는 있지만, DB category는 `ETC`이고 기능 여부는 featureType으로 판단한다.

## 현재 접근성 feature 분포

| featureType | count |
|---|---:|
| `accessibleEntrance` | 10,050 |
| `stepFree` | 9,801 |
| `ramp` | 9,668 |
| `elevator` | 4,922 |
| `accessibleParking` | 3,787 |
| `accessibleToilet` | 3,541 |
| `guidanceFacility` | 475 |
| `chargingStation` | 197 |
| `accessibleRoom` | 124 |
