# 편의시설 최종 ERD v3 반영본

2026-04-28 장소 카테고리 및 접근성 필터 정책 기준으로 재생성한 산출물이다.

## 기준

- 장소 category는 `FOOD_CAFE`, `TOURIST_SPOT`, `ACCOMMODATION`, `HEALTHCARE`, `WELFARE`, `PUBLIC_OFFICE`, `ETC` 7개만 사용한다.
- `TOILET`, `CHARGING_STATION`, `BARRIER_FREE_FACILITY`, `RESTAURANT`는 최종 category로 사용하지 않는다.
- 장애인 화장실과 전동보장구 충전 가능 여부는 `place_accessibility_features.featureType`으로 관리한다.

## 최종 개수

- 장소: `13,564`개
- 접근성 row: `42,565`개
- 접근성 있는 장소: `12,309`개
