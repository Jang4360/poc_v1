# 02. 편의시설 검증 로그

## 원본 통합

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

원천별 개수는 다음과 같다.

| sourceDataset | 개수 |
|---|---:|
| `barrier_free_facility` | 10,998 |
| `public_toilet` | 2,010 |
| `charging_station` | 197 |
| `tourist_spot` | 158 |
| `subway_station` | 114 |
| `restaurant` | 51 |
| `accommodation` | 42 |

## 검증 큐

검증 큐는 `data/reports/facility_validation/facility_validation_review_targets_all.csv` 기준 4,415개였다.

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

카카오맵 검색 쿼리 우선순위는 다음과 같다.

```text
장소명 + 주소
장소명 + 도로명/번지
장소명 + 구
장소명
주소
```

카카오 후보 점수는 거리, 이름 유사도, 주소 토큰 일치, 카테고리 일치를 기준으로 계산했다.

초기 판정 결과는 다음과 같다.

| 판정 | 개수 |
|---|---:|
| `KEEP` | 1,426 |
| `RENAME_REVIEW` | 1,009 |
| `CATEGORY_REVIEW` | 729 |
| `POI_ONLY_RECHECK` | 198 |
| `POI_ONLY_CATEGORY_RECHECK` | 98 |
| `MANUAL_REVIEW` | 87 |
| `REMOVE_REVIEW` | 10 |
| `REVIEW_OR_REMOVE` | 28 |

## 카카오/POI 존재성 재분류

팀 논의 후 기준을 단순화했다.

```text
카카오 + POI 둘 다 있음 -> 유지, 카카오 기준 우선
카카오만 있음 -> 유지, 카카오 기준
POI만 있음 -> 유지, POI 기준
둘 다 없음/약함 -> 제거 검토
```

재분류 결과는 다음과 같다.

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

## 화장실 맥락 제거 반영

추가로 역/터미널/민간/학교/사유시설 화장실을 제거했다.

| 제거 규칙 | 개수 |
|---|---:|
| `REMOVE_TRANSIT_TOILET` | 43 |
| `REMOVE_PRIVATE_COMMERCIAL_TOILET` | 10 |
| `REMOVE_SCHOOL_MILITARY_PRIVATE_TOILET` | 5 |

적용 후 장소 수는 3,520개에서 3,462개로 줄었다.

## 카테고리 정책 보정

카카오/POI 근거가 있지만 서비스 카테고리와 직접 일치하지 않는 249개를 정책 기준으로 재검토했다.

| 처리 | 개수 |
|---|---:|
| 기존 카테고리 유지 | 163 |
| `ETC`로 보정 | 86 |

`ETC` 보정 대상은 도서관/문화원/교육원 계열, 대표 관광지로 단정하기 어려운 문화·상업·종교시설, 병원 단일 장소로 보기 어려운 메디컬 빌딩/센터/타워 계열이다.

적용 후 장소 수는 3,462개로 유지되고, 카테고리만 보정됐다.

## 회사/비방문 목적지 제거 반영

원천은 음식점/휴게음식점 계열이지만 카카오/POI 확인 결과 회사, 공구/테크, 산업, 제조/유통 지점으로 판단되는 5개를 제거했다.

| 제거 규칙 | 개수 |
|---|---:|
| `REMOVE_COMPANY_NON_DESTINATION` | 5 |

제거 대상은 `티앤에이치`, `굿모닝공구테크`, `한국미쓰도요(주)`, `세우루브`, `(주)대한이씨아이`다.

적용 후 장소 수는 3,462개에서 3,457개로 줄었다.

## 우선 수동검증 25건 제거 반영

검증 필요 보고서에서 `MANUAL_REVIEW`, `STATUS_NOT_KEEP`로 남아 있던 25건은 서비스 표시 위험이 크다고 판단해 제거했다.

| 제거 사유 | 개수 |
|---|---:|
| `MANUAL_REVIEW` | 14 |
| `STATUS_NOT_KEEP` | 11 |

| 제거 카테고리 | 개수 |
|---|---:|
| `TOILET` | 22 |
| `ACCOMMODATION` | 1 |
| `PUBLIC_OFFICE` | 1 |
| `TOURIST_SPOT` | 1 |

적용 후 장소 수는 3,457개에서 3,432개로 줄었다.

## 카카오명 표시명 보정

남은 `RENAME_REVIEW` 대상은 장소를 제거하지 않고 카카오맵 후보명을 기준으로 표시명을 보정했다.

| 처리 | 개수 |
|---|---:|
| 카카오명 기준 표시명 보정 | 978 |

보정 후 검증 필요 보고서는 `GENERIC_NAME` 1,665건만 남았다. 이 항목은 원천명이 포괄적이지만 카카오/POI 존재 근거가 있으므로 일단 유지한다.

## 최종 결과

현재 최종 채택본은 `data/adopted/adopted_places_with_accessibility.csv` 기준 3,432개다.

| DB category | 최종 개수 |
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

## 검증/적용 파일

| 파일 | 설명 |
|---|---|
| `data/reports/facility_validation/facility_kakao_first_refresh_all.csv` | 카카오 우선 + POI 보조 매칭 리포트 |
| `data/reports/facility_validation/facility_kakao_poi_existence_rule_all.csv` | 카카오/POI 존재성 기준 재분류 |
| `data/reports/facility_validation/facility_kakao_poi_existence_rule_removed_applied.csv` | 존재성 근거 약한 65개 제거 내역 |
| `data/reports/facility_validation/facility_toilet_context_remove_rule_removed_applied.csv` | 역/터미널/민간/학교 화장실 58개 제거 내역 |
| `data/reports/facility_validation/facility_policy_category_decisions_applied.csv` | 애매한 카테고리 249개 정책 보정 내역 |
| `data/reports/facility_validation/facility_non_destination_remove_rule_removed_applied.csv` | 회사/비방문 목적지 5개 제거 내역 |
| `data/reports/facility_validation/facility_priority_manual_removed_applied.csv` | 우선 수동검증 25건 제거 내역 |
| `data/reports/facility_validation/facility_kakao_rename_review_applied.csv` | 카카오명 기준 표시명 978건 보정 내역 |
| `data/reports/facility_validation/facility_manual_review_required_cases.csv` | 현재 남은 검증 필요 보고서, `GENERIC_NAME` 1,665건 |
