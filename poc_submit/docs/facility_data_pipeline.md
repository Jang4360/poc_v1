# 보행약자 편의시설 데이터 정리 흐름

## 목적

보행약자 서비스에 표시할 편의시설 장소와 장소별 접근성 속성을 확정하기 위한 PoC 정리 문서다.

핵심 원칙은 다음과 같다.

- 장소 존재성/최신 명칭은 카카오맵을 우선 확인한다.
- 카카오맵과 POI 중 하나라도 근거가 있으면 일단 유지한다.
- 카카오맵과 POI 모두 근거가 약하면 제거 검토 대상으로 둔다.
- 접근성 속성은 공공데이터 원본을 근거로 유지한다.
- 역/터미널 화장실처럼 서비스에서 별도 장소로 표시할 가치가 낮은 항목은 제거한다.

## 원본 데이터

최초 통합 원본은 `data/source/source_places_with_accessibility.csv` 기준이다.

| 구분 | 개수 |
|---|---:|
| 전체 원본 장소 | 13,570 |
| 관광지 | 158 |
| 음식·카페 | 811 |
| 숙박 | 231 |
| 행정·공공기관 | 278 |
| 의료·보건 | 390 |
| 복지·돌봄 | 299 |
| 화장실 | 2,051 |
| 전동보장구 충전소 | 197 |
| 미채택/기타 원천 분류 | 9,155 |

주요 원천은 다음과 같다.

| sourceDataset | 개수 | 설명 |
|---|---:|---|
| `barrier_free_facility` | 10,998 | 장애인편의시설 공공데이터 기반 |
| `public_toilet` | 2,010 | 부산 공중화장실 데이터 |
| `charging_station` | 197 | 전동보장구 충전소 |
| `tourist_spot` | 158 | 접근 가능 관광지 |
| `subway_station` | 114 | 도시철도역 접근성 원천 |
| `restaurant` | 51 | 접근 가능 음식점 |
| `accommodation` | 42 | 접근 가능 숙박 |

## 1차 채택 기준

실제 서비스에서 표시할 카테고리만 채택했다.

최종 서비스 카테고리는 다음을 사용한다.

| DB category | UI category |
|---|---|
| `TOILET` | 공중화장실, 시설 내 화장실 |
| `RESTAURANT` | 음식·카페 |
| `TOURIST_SPOT` | 관광지 |
| `ACCOMMODATION` | 숙박 |
| `CHARGING_STATION` | 전동보장구 충전소 |
| `HEALTHCARE` | 의료·보건 |
| `WELFARE` | 복지·돌봄 |
| `PUBLIC_OFFICE` | 공공기관 |

이 단계에서 원본 13,570개 중 서비스 카테고리에 해당하지 않는 항목을 제외하고, 이후 카테고리 보정/명칭 정리/화장실 범위 정리를 거쳤다.

## 검증 대상 큐

편의시설 검증 큐는 `data/reports/facility_validation/facility_validation_review_targets_all.csv` 기준 4,415개였다.

| 카테고리 | 검증 큐 개수 |
|---|---:|
| 화장실 | 2,051 |
| 음식·카페 | 811 |
| 의료·보건 | 390 |
| 복지·돌봄 | 299 |
| 행정·공공기관 | 278 |
| 숙박 | 231 |
| 전동보장구 충전소 | 197 |
| 관광지 | 158 |

## 카카오맵 우선 검증

최종 채택 후보 3,585개에 대해 카카오맵 검색과 POI 매칭을 수행했다.

카카오맵 검색은 다음 순서로 쿼리했다.

```text
장소명 + 주소
장소명 + 도로명/번지
장소명 + 구
장소명
주소
```

카카오 후보 점수는 거리, 이름 유사도, 주소 토큰 일치, 카테고리 일치를 기준으로 계산했다.

초기 판정 결과는 다음과 같다.

| 판정 | 개수 | 의미 |
|---|---:|---|
| `KEEP` | 1,426 | 카카오 기준으로 유지 가능 |
| `RENAME_REVIEW` | 1,009 | 카카오 명칭과 원본 명칭이 달라 보정 검토 |
| `CATEGORY_REVIEW` | 729 | 카카오 장소는 있으나 카테고리 확인 필요 |
| `POI_ONLY_RECHECK` | 198 | 카카오 근거 약함, POI만 강함 |
| `POI_ONLY_CATEGORY_RECHECK` | 98 | POI만 있고 카테고리도 애매 |
| `MANUAL_REVIEW` | 87 | 카카오/POI 모두 애매 |
| `REMOVE_REVIEW` | 10 | 카카오/POI 모두 약함 |
| `REVIEW_OR_REMOVE` | 28 | 내부시설/건물 맥락 |

관련 파일:

- `data/reports/facility_validation/facility_kakao_first_refresh_all.csv`
- `data/reports/facility_validation/facility_kakao_first_refresh_summary.json`

## 카카오/POI 존재성 기준 재분류

팀 논의 후 기준을 단순화했다.

```text
카카오 + POI 둘 다 있음 -> 유지, 카카오 기준 우선
카카오만 있음 -> 유지, 카카오 기준
POI만 있음 -> 유지, POI 기준
둘 다 없음/약함 -> 제거 검토
```

이 기준으로 3,585개를 재분류했다.

| 존재성 판정 | 개수 |
|---|---:|
| 유지 | 3,520 |
| 제거 검토 | 65 |

유지 근거는 다음과 같다.

| 근거 | 개수 |
|---|---:|
| 카카오 + POI 둘 다 있음, 카카오 우선 | 3,159 |
| 카카오만 있음 | 36 |
| POI만 있음 | 325 |
| 둘 다 없음/약함 | 65 |

관련 파일:

- `data/reports/facility_validation/facility_kakao_poi_existence_rule_all.csv`
- `data/reports/facility_validation/facility_kakao_poi_existence_rule_remove_candidates.csv`

## 제거 1차 반영

카카오와 POI 모두 존재 근거가 약한 65개를 제거했다.

| 제거 카테고리 | 개수 |
|---|---:|
| 시설 내 화장실 | 34 |
| 공중화장실 | 23 |
| 전동보장구 충전소 | 3 |
| 관광지 | 2 |
| 음식·카페 | 2 |
| 공공기관 | 1 |

적용 후 장소 수는 3,585개에서 3,520개로 줄었다.

관련 파일:

- `data/reports/facility_validation/facility_kakao_poi_existence_rule_removed_applied.csv`
- `scripts/apply_facility_existence_remove_candidates.py`

## 화장실 맥락 제거 규칙

추가로 화장실 계열에서 서비스 노이즈가 큰 항목을 제거했다.

적용한 규칙은 다음과 같다.

| 규칙 | 처리 |
|---|---|
| 지하철역/철도역/터미널 화장실 | 제거 |
| 음식점/카페/주유소/호텔/빌딩/아파트 내부 화장실 | 제거 후보로 보고 제거 |
| 학교/예비군/군부대/사유시설 화장실 | 제거 후보로 보고 제거 |

추가 제거 결과는 다음과 같다.

| 제거 규칙 | 개수 |
|---|---:|
| `REMOVE_TRANSIT_TOILET` | 43 |
| `REMOVE_PRIVATE_COMMERCIAL_TOILET` | 10 |
| `REMOVE_SCHOOL_MILITARY_PRIVATE_TOILET` | 5 |

적용 후 장소 수는 3,520개에서 3,462개로 줄었다.

관련 파일:

- `data/reports/facility_validation/facility_toilet_context_remove_rule_removed_applied.csv`
- `scripts/apply_facility_toilet_context_remove_rules.py`

## 카테고리/표시명 최종 보정

카카오/POI 근거가 있지만 서비스 대표 카테고리로 단정하기 어려운 항목은 `ETC`로 보존했다. 회사, 공구/테크, 산업, 제조/유통 지점처럼 사용자 목적지로 보기 어려운 5건은 제거했다.

우선 수동검증 대상 중 `MANUAL_REVIEW`, `STATUS_NOT_KEEP`로 남아 있던 25건은 서비스 표시 위험이 커서 제거했다. 이후 `RENAME_REVIEW` 978건은 카카오맵 후보명을 기준으로 표시명을 보정했다.

관련 파일:

- `data/reports/facility_validation/facility_policy_category_decisions_applied.csv`
- `data/reports/facility_validation/facility_non_destination_remove_rule_removed_applied.csv`
- `data/reports/facility_validation/facility_priority_manual_removed_applied.csv`
- `data/reports/facility_validation/facility_kakao_rename_review_applied.csv`

## 최종 결과

현재 최종 채택본은 `data/adopted/adopted_places_with_accessibility.csv` 기준 3,432개다.

| 카테고리 | 최종 개수 |
|---|---:|
| `TOILET` | 1,376 |
| `RESTAURANT` | 625 |
| `HEALTHCARE` | 275 |
| `WELFARE` | 263 |
| `PUBLIC_OFFICE` | 258 |
| `ACCOMMODATION` | 226 |
| `CHARGING_STATION` | 191 |
| `TOURIST_SPOT` | 136 |
| `ETC` | 82 |

UI 카테고리 기준은 다음과 같다.

| UI category | 최종 개수 |
|---|---:|
| 시설 내 화장실 | 943 |
| 음식·카페 | 625 |
| 공중화장실 | 433 |
| 의료·보건 | 275 |
| 복지·돌봄 | 263 |
| 공공기관 | 258 |
| 숙박 | 226 |
| 전동보장구 충전소 | 191 |
| 관광지 | 136 |
| 기타 편의시설 | 82 |

## 최종 산출물

팀원 공유/DB seed/import 기준 파일은 다음이다.

| 파일 | 용도 |
|---|---|
| `data/adopted/places_erd.csv` | ERD `places` seed 후보 |
| `data/adopted/place_accessibility_features_erd.csv` | ERD `place_accessibility_features` seed 후보 |
| `data/adopted/adopted_places_with_accessibility.csv` | 원천 추적/지도/검토용 통합 최종본 |
| `data/adopted/adopted_places.csv` | 장소 테이블형 최종본 |
| `data/adopted/adopted_place_accessibility.csv` | 원본 접근성 속성 테이블형 최종본 |
| `assets/data/facilities-data.js` | `index.html` 지도 표시용 GeoJSON |
| `assets/data/accessibility-summary-data.js` | 지도 UI 접근성 요약 |

최종 ERD 결과는 다음과 같다.

| 항목 | 개수 |
|---|---:|
| `places_erd.csv` | 3,432 |
| `place_accessibility_features_erd.csv` | 5,337 |
| 지도 feature | 3,432 |
| ERD FK 오류 | 0 |

## 현재 남은 의사결정

다음 항목은 아직 정책 확인 여지가 있다.

- 시설 내 화장실 943개를 계속 장소로 둘지, 일부를 상위 장소 접근성으로 흡수할지 결정해야 한다.
- `GENERIC_NAME` 1,665건은 존재 근거가 있어 유지했지만, 표시명/좌표 품질은 서비스 오픈 전 추가 검토 여지가 있다.
- 전동보장구 충전소는 카카오/POI 누락 가능성이 크므로 공공데이터 원본 우선 유지 정책을 유지할지 확인이 필요하다.
