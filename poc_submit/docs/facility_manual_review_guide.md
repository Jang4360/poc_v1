# 편의시설 수동 검증 가이드

## 검증 방식

지도 UI에는 검증 필터를 두지 않는다. 지도는 위치와 주변 맥락을 확인하는 용도로만 사용하고, 실제 검증 대상은 CSV 큐에서 고른다.

현재 adopted 편의시설 전체 4,415개를 POI와 카카오맵 검색 결과로 교차검증했다.

## 전체 교차검증 결과

2026-04-26 기준 전체 4,415개에 대해 부산 POI 데이터와 카카오맵 검색 결과를 함께 비교했다.

2026-04-26 1차 반영으로 내부 화장실 제외 후보 418개와 이름 보정 후보 162개는 adopted/ERD/지도 JS에 반영했다. 반영 전 백업은 `archive/20260426_facility_apply_1_2_before`에 보관한다.

| 구분 | 개수 | 처리 방향 |
|---|---:|---|
| 자동 유지 | 3,464 | 장소명, 위치, 카테고리 근거가 충분해 그대로 유지 |
| 위치 샘플 확인 후 유지 | 197 | 전동보장구 충전소. 유지하되 좌표가 충전기 위치인지 대표 시설 위치인지 샘플 확인 |
| 내부 화장실 제외 후보 | 418 | 주유소, 병원, 학교, 아파트 등 내부 화장실 가능성이 높아 정책 확정 후 제외 검토 |
| 이름 보정 후보 | 162 | `일반음식점`, `휴게음식점·제과점`처럼 업종명만 있는 데이터를 POI/카카오명으로 보정 가능 |
| 이름 보정 또는 제외 | 138 | 실제 장소명 복구 가능성은 있으나 카테고리/장소 근거가 섞여 수동 판단 필요 |
| 수동 확인 | 36 | POI와 카카오 결과가 충돌하거나 대표 좌표가 넓어 직접 판단 필요 |

## 반영 전 의사결정 파일

| 파일 | 용도 |
|---|---|
| `data/reports/facility_validation/facility_cross_validation_action_plan.csv` | 전체 4,415개 최종 액션 플랜 |
| `data/reports/facility_validation/facility_cross_validation_human_decision_plan.csv` | 사람 판단이 필요한 754개만 분리 |
| `data/reports/facility_validation/facility_cross_validation_action_summary.csv` | 액션 플랜 요약 |
| `data/reports/facility_validation/facility_cross_validation_all.csv` | POI + 카카오 교차검증 전체 상세 결과 |
| `data/reports/facility_validation/facility_cross_validation_need_review.csv` | 사람 판단 필요 상세 결과 |

## 이번 반영 판단 순서

| 순서 | 대상 | 이유 |
|---:|---|---|
| 1 | 내부 화장실 제외 후보 418개 | 프로젝트에서 화장실을 목적지로 노출할지, 내부 편의시설로만 볼지 기준이 먼저 필요 |
| 2 | 이름 보정 후보 162개 | 보정명이 POI/카카오에서 강하게 잡히므로 빠르게 정리 가능 |
| 3 | 이름 보정 또는 제외 138개 | 실제 장소명 복구와 서비스 노출 여부를 같이 판단해야 함 |
| 4 | 수동 확인 36개 | 관광지/공공기관 등 대표 좌표 충돌이 있어 직접 확인 필요 |
| 5 | 전동보장구 충전소 197개 | 유지 전제로 샘플 좌표 품질만 확인 |

## 1차 반영 결과

| 구분 | 반영 |
|---|---:|
| 내부 화장실 제외 | 418개 |
| POI/카카오 기준 이름 보정 | 162개 |
| 반영 후 편의시설 장소 | 3,997개 |
| 반영 후 ERD 접근성 row | 6,133개 |

| 파일 | 용도 |
|---|---|
| `data/reports/facility_validation/facility_apply_1_2_summary.json` | 1차 반영 전후 카운트 |
| `data/reports/facility_validation/facility_apply_1_2_excluded.csv` | 제외 반영된 내부 화장실 418개 |
| `data/reports/facility_validation/facility_apply_1_2_renamed.csv` | 이름 보정 반영된 162개 |
| `data/reports/facility_validation/facility_apply_1_2_remaining_manual_174.csv` | 1차 반영 후 남은 수동 판단 174개 |
| `data/reports/facility_validation/facility_apply_1_2_remaining_manual_174_summary.csv` | 남은 수동 판단 174개 요약 |

## 복지·돌봄 수동 반영 결과

복지·돌봄 80개는 전부 처리했다. `무더위쉼터`, `한파쉼터`는 단독 장소명으로 쓰지 않고, 실제 경로당/복지시설명이 확인되는 경우만 유지했다.

| 구분 | 반영 |
|---|---:|
| 사회복지 목적지로 보기 어려워 제거 | 10개 |
| 실제 복지시설명으로 이름 보정 | 49개 |
| 원본명이 더 정확해 유지 | 21개 |
| 반영 후 편의시설 장소 | 3,987개 |
| 반영 후 수동 판단 잔여 | 94개 |

| 파일 | 용도 |
|---|---|
| `data/reports/facility_validation/facility_apply_welfare_summary.json` | 복지·돌봄 반영 전후 카운트 |
| `data/reports/facility_validation/facility_apply_welfare_removed.csv` | 제거한 10개 |
| `data/reports/facility_validation/facility_apply_welfare_renamed.csv` | 이름 보정한 49개 |
| `data/reports/facility_validation/facility_apply_welfare_kept_as_is.csv` | 원본명 유지 21개 |
| `data/reports/facility_validation/facility_apply_welfare_remaining_manual_94.csv` | 잔여 수동 판단 94개 |

## 잔여 수동 판단 반영 결과

복지·돌봄 처리 후 남은 94개도 전부 처리했다. 카테고리 불일치, 건물명/입구명, 좌표 충돌이 큰 데이터는 제거하고, 서비스 목적지로 적합한 의료·숙박·행정·관광·음식점은 이름을 보정했다.

| 구분 | 반영 |
|---|---:|
| 제거 | 41개 |
| 이름 보정 | 51개 |
| 원본명 유지 | 2개 |
| 반영 후 편의시설 장소 | 3,946개 |
| 반영 후 수동 판단 잔여 | 0개 |

| 파일 | 용도 |
|---|---|
| `data/reports/facility_validation/facility_apply_remaining_manual_summary.json` | 잔여 94개 반영 전후 카운트 |
| `data/reports/facility_validation/facility_apply_remaining_manual_removed.csv` | 제거한 41개 |
| `data/reports/facility_validation/facility_apply_remaining_manual_renamed.csv` | 이름 보정한 51개 |
| `data/reports/facility_validation/facility_apply_remaining_manual_kept_as_is.csv` | 원본명 유지 2개 |
| `data/reports/facility_validation/facility_apply_remaining_manual_0.csv` | 빈 파일. 수동 판단 잔여 0개 확인용 |

## 음식점 건물명 표시 정리 결과

음식점으로 분류됐지만 `빌딩`, `상가`, `건축물`, `주택`, `근생`처럼 건물/구조물명으로 보이던 데이터를 추가 정리했다. POI/카카오에서 같은 음식점명이 명확하게 잡히는 경우만 이름을 보정했고, 후보가 충돌하거나 음식점명을 특정할 수 없는 경우는 서비스 노출에서 제거했다.

| 구분 | 반영 |
|---|---:|
| 실제 음식점명으로 보정 | 43개 |
| 상호 특정 불가/후보 충돌로 제거 | 89개 |
| 처리 대상 | 132개 |
| 반영 후 편의시설 장소 | 3,857개 |

| 파일 | 용도 |
|---|---|
| `data/reports/facility_validation/facility_restaurant_structural_name_plan.csv` | 음식점 건물명 1차 판정 계획 |
| `data/reports/facility_validation/facility_restaurant_display_cleanup_renamed.csv` | 1차 이름 보정 내역 |
| `data/reports/facility_validation/facility_restaurant_display_cleanup_removed.csv` | 1차 제거 내역 |
| `data/reports/facility_validation/facility_restaurant_extra_structural_cleanup_renamed.csv` | 추가 이름 보정 내역 |
| `data/reports/facility_validation/facility_restaurant_extra_structural_cleanup_removed.csv` | 추가 제거 내역 |
| `data/reports/facility_validation/facility_restaurant_last_structural_cleanup_removed.csv` | 마지막 구조물명 제거 내역 |

## 화장실 공공성 정리 결과

공중화장실 원본에 섞인 주유소, 병원, 은행, 교회, 일반 상가 등 내부/민간시설 화장실 의심 데이터를 정리했다. 1차로 74개를 제거했고, 이후 시장, 지하상가, 고객편의시설, 학교 주변처럼 범위가 넓거나 위치 설명에 가까운 10개도 정확도 우선 기준으로 추가 제거했다. 최종 표시 정책에서는 공공시설 내부 화장실은 유지하되 `시설 내 화장실`로 분리하고, 모텔/마트/고객편의시설처럼 공개성이 낮은 7개를 추가 제외했다. 이후 `화장실 검토 필요` 311개를 다시 검토해 282개는 `공중화장실`/`시설 내 화장실`로 흡수하고, 민간/상업시설 후보와 사용자가 지정한 애매한 항목 29개는 추가 제거했다.

| 구분 | 반영 |
|---|---:|
| 1차 제거 | 74개 |
| 추가 제거 | 10개 |
| 표시 정책 추가 제거 | 7개 |
| 검토 필요 재분류 흡수 | 282개 |
| 검토 필요 추가 제거 | 29개 |
| 처리 대상 | 402개 |
| 현재 최종 편의시설 장소 | 3,692개 |
| 공중화장실 표시 | 482개 |
| 시설 내 화장실 표시 | 1,031개 |
| 기존 검토 대상 잔여 표시 | 0개 |

| 파일 | 용도 |
|---|---|
| `data/reports/facility_validation/toilet_public_private_cleanup_plan.csv` | 화장실 공공성 판정 계획 |
| `data/reports/facility_validation/toilet_public_private_cleanup_removed.csv` | 제거한 74개 |
| `data/reports/facility_validation/toilet_strict_cleanup_removed.csv` | 추가 제거한 10개 |
| `data/reports/facility_validation/toilet_display_scope_policy_classified.csv` | 화장실 표시 기준 분류 결과 |
| `data/reports/facility_validation/toilet_display_scope_policy_removed.csv` | 표시 정책에서 추가 제외한 7개 |
| `data/reports/facility_validation/toilet_review_needed_decisions_applied.csv` | 검토 필요 311개 최종 반영 내역 |
| `data/reports/facility_validation/toilet_review_needed_decisions_removed.csv` | 검토 필요 중 추가 제거한 29개 |

## 음식·카페 표시명 정리 결과

음식·카페 701개를 다시 점검해 건물명, 근린생활시설명, 주유소/조명 등 음식점 목적지로 쓰기 어려운 데이터를 정리했다. 카카오/POI에서 음식점 후보가 명확한 29개는 상호명으로 보정했고, 보정 근거가 없는 건물/비음식점명 20개는 제거했다.

| 구분 | 반영 |
|---|---:|
| 이름 보정 | 29개 |
| 추가 제거 | 20개 |
| 반영 후 음식·카페 | 681개 |

| 파일 | 용도 |
|---|---|
| `data/reports/facility_validation/restaurant_current_quality_plan.csv` | 현재 음식·카페 품질 점검 계획 |
| `data/reports/facility_validation/restaurant_current_quality_decisions_renamed.csv` | 보정한 29개 |
| `data/reports/facility_validation/restaurant_current_quality_decisions_removed.csv` | 제거한 20개 |

## 복지·돌봄 현재 품질 정리 결과

복지·돌봄 289개 전체를 현재 최종 데이터 기준으로 다시 점검했다. 외부 POI/카카오 근거가 명확한 53개는 실제 시설명으로 보정했고, `가덕도동 주민센터`는 `PUBLIC_OFFICE`로 재분류했다. 교회로 확인되는 1개는 제거했다. 이후 건물명/마을회관/아파트명으로만 남은 24개는 복지 목적지로 확정하기 어렵다고 판단해 추가 제거했다.

| 구분 | 반영 |
|---|---:|
| 이름 보정 | 53개 |
| 공공기관 재분류 | 1개 |
| 제거 | 1개 |
| 수동 검토 추가 제거 | 24개 |
| 잔여 수동 검토 | 0개 |
| 반영 후 복지·돌봄 | 263개 |

| 파일 | 용도 |
|---|---|
| `data/reports/facility_validation/welfare_current_quality_plan.csv` | 현재 복지·돌봄 전체 점검 결과 |
| `data/reports/facility_validation/welfare_current_quality_decisions_renamed.csv` | 보정한 53개 |
| `data/reports/facility_validation/welfare_current_quality_decisions_recategorized.csv` | 공공기관으로 재분류한 1개 |
| `data/reports/facility_validation/welfare_current_quality_decisions_removed.csv` | 제거한 1개 |
| `data/reports/facility_validation/welfare_remaining_manual_removed.csv` | 수동 검토 후 추가 제거한 24개 |

## 의료·보건 현재 품질 정리 결과

의료·보건 384개 전체를 현재 최종 데이터 기준으로 다시 점검했다. POI/카카오에서 병원, 의원, 치과, 한의원, 요양병원 등 실제 의료기관명이 명확하게 확인되는 85개는 표시명을 보정했다. 이후 수동검토 130개 중 메디컬/메디칼/의료 계열 포괄명 32개는 의료시설 군집 건물로 유지하고, 의료 목적지를 설명하지 못하는 건물명/비의료명 98개는 제거했다. `백양메티칼센터`는 `백양메디칼센터`로 오타 보정했다.

| 구분 | 반영 |
|---|---:|
| 1차 이름 보정 | 85개 |
| 수동검토 유지 | 32개 |
| 수동검토 오타 보정 | 1개 |
| 수동검토 제거 | 98개 |
| 반영 후 의료·보건 | 286개 |
| 잔여 수동 검토 | 0개 |

| 파일 | 용도 |
|---|---|
| `data/reports/facility_validation/healthcare_current_quality_plan.csv` | 현재 의료·보건 전체 점검 결과 |
| `data/reports/facility_validation/healthcare_current_quality_decisions_renamed.csv` | 보정한 85개 |
| `data/reports/facility_validation/healthcare_manual_policy_kept.csv` | 수동검토 후 유지한 32개 |
| `data/reports/facility_validation/healthcare_manual_policy_renamed.csv` | 수동검토 중 오타 보정한 1개 |
| `data/reports/facility_validation/healthcare_manual_policy_removed.csv` | 수동검토 후 제거한 98개 |

## 공공기관 현재 품질 정리 결과

공공기관 273개 전체를 현재 최종 데이터 기준으로 다시 점검했다. 동사무소/주민자치센터/오타/포괄명을 POI·카카오 기준 정식 명칭으로 보정했고, 보건소·보건지소는 `HEALTHCARE`, 건강가정지원센터와 복합건강센터는 `WELFARE`로 재분류했다. 공공기관 목적지로 보기 어려운 `희망마을 수직농장`, `영도 Sea Side Complex Town`, `용호만유람선터미널1`은 제거했다.

| 구분 | 반영 |
|---|---:|
| 이름 보정 | 17개 |
| 의료·보건 재분류 | 8개 |
| 복지·돌봄 재분류 | 2개 |
| 제거 | 3개 |
| 잔여 수동 검토 | 0개 |
| 반영 후 공공기관 | 260개 |

| 파일 | 용도 |
|---|---|
| `data/reports/facility_validation/public_office_current_quality_plan.csv` | 현재 공공기관 전체 점검 결과 |
| `data/reports/facility_validation/public_office_current_quality_decisions_renamed.csv` | 보정한 17개 |
| `data/reports/facility_validation/public_office_current_quality_decisions_recategorized.csv` | 재분류한 10개 |
| `data/reports/facility_validation/public_office_current_quality_decisions_removed.csv` | 제거한 3개 |

## 숙박 현재 품질 정리 결과

숙박 229개 전체를 현재 최종 데이터 기준으로 다시 점검했다. 축약명, 영문명, 건물명처럼 보이는 숙박 데이터를 POI·카카오 기준 실제 숙박시설명으로 보정했다. 숙박 목적지 근거가 약한 `지엠타워`, `보리선수`는 제거했고, 공식 숙박 원본이거나 생활형숙박시설 근거가 있는 항목은 유지했다.

| 구분 | 반영 |
|---|---:|
| 이름 보정 | 25개 |
| 제거 | 2개 |
| 잔여 수동 검토 | 0개 |
| 반영 후 숙박 | 227개 |

| 파일 | 용도 |
|---|---|
| `data/reports/facility_validation/accommodation_current_quality_plan.csv` | 현재 숙박 전체 점검 결과 |
| `data/reports/facility_validation/accommodation_current_quality_decisions_renamed.csv` | 보정한 25개 |
| `data/reports/facility_validation/accommodation_current_quality_decisions_removed.csv` | 제거한 2개 |

## 관광지 현재 품질 정리 결과

관광지 152개는 공식 관광 원본이므로 대표 장소명을 우선 유지했다. 시장, 도서관, 문화시설, 관광특구처럼 POI가 하위 지점으로 잡히는 경우도 원본 대표명이 서비스 표시에는 더 적합하다고 판단했다. 단일 매장명으로 보이고 관광 목적지 근거가 약한 `광주요` 1개만 제거했다.

| 구분 | 반영 |
|---|---:|
| 이름 보정 | 0개 |
| 제거 | 1개 |
| 잔여 수동 검토 | 0개 |
| 반영 후 관광지 | 151개 |

| 파일 | 용도 |
|---|---|
| `data/reports/facility_validation/tourist_spot_current_quality_plan.csv` | 현재 관광지 전체 점검 결과 |
| `data/reports/facility_validation/tourist_spot_current_quality_decisions_removed.csv` | 제거한 1개 |

## 전동보장구 충전소 현재 품질 정리 결과

전동보장구 충전소는 독립 POI가 아니라 충전기가 설치된 host 시설명으로 표시되는 데이터다. 따라서 역, 복지관, 행정복지센터, 병원 등 시설명 자체는 유지하고, POI/카카오로 명칭 오류와 명확한 중복만 정리했다.

| 구분 | 반영 |
|---|---:|
| 이름 보정 | 14개 |
| 제거 | 3개 |
| 잔여 수동 검토 | 0개 |
| 반영 후 전동보장구 충전소 | 194개 |

제거한 3개는 같은 좌표/주소의 중복이거나 외부 POI가 다른 시설로 확인된 항목이다. `동래구 장애인복지관`은 `동래구장애인복지관`과 중복, `구포역(기차역)`은 `구포역`과 중복, `연산1동행정복지센터`는 같은 주소의 `연산6동행정복지센터`와 중복이고 외부 POI도 연산6동으로 확인되어 제외했다.

| 파일 | 용도 |
|---|---|
| `data/reports/facility_validation/charging_station_current_quality_plan.csv` | 현재 전동보장구 충전소 전체 점검 결과 |
| `data/reports/facility_validation/charging_station_current_quality_decisions_renamed.csv` | 보정한 14개 |
| `data/reports/facility_validation/charging_station_current_quality_decisions_removed.csv` | 제거한 3개 |

## 최종 ERD 반영본

최종 DB 반영 후보는 `data/final/facilities/`에 분리했다. `data/adopted`는 작업 기준 채택본으로 유지하고, 팀 공유 또는 DB 적재 검토는 최종 폴더의 파일을 기준으로 한다.

기존 통합 편의시설 카테고리는 최종 카테고리에서 제거했다. 원본 시설 유형과 카카오/POI 근거 기준으로 `HEALTHCARE`, `WELFARE`, `PUBLIC_OFFICE`, `ETC` 등으로 재분류했다.

| 재분류 대상 | 반영 카테고리 | 개수 |
|---|---|---:|
| 병원, 의원, 치과, 한의원, 보건소, 종합병원, 의료시설 군집 건물 | `HEALTHCARE` | 275개 |
| 노인/장애인/아동/사회복지시설, 경로당, 가족센터, 복합건강센터 | `WELFARE` | 263개 |
| 주민센터, 지자체 청사, 공단, 우체국, 파출소, 지구대 | `PUBLIC_OFFICE` | 258개 |
| 대표 서비스 카테고리로 단정하기 어려운 장소 | `ETC` | 82개 |

| 파일 | 용도 |
|---|---|
| `data/final/facilities/places_erd.csv` | DB `places` 반영 후보 |
| `data/final/facilities/place_accessibility_features_erd.csv` | DB `place_accessibility_features` 반영 후보 |
| `data/final/facilities/adopted_places_with_accessibility_final.csv` | 추적/검증용 최종 통합 파일 |
| `data/final/facilities/facility_final_validation_report.json` | 스키마, PK/FK, enum, 좌표, unique 검증 결과 |
| `data/final/facilities/facility_final_quality_warnings.csv` | DB 차단은 아니지만 서비스 표시 전 확인할 품질 경고 |

| 항목 | 값 |
|---|---:|
| 장소 | 3,585개 |
| 장소 row | 3,432개 |
| 접근성 row | 5,337개 |
| 접근성 있는 장소 | 2,507개 |
| 검증 상태 | PASS |
| 품질 경고 | 89건 |

품질 경고는 DB 반영 차단 오류가 아니다. 현재 최종 경고는 중복 이름/주소, 포괄 표시명, 충전소 host 시설명, 접근성 원본 기반 음식점, 동일 좌표 다중 장소처럼 서비스 표시 전 확인할 항목이다.

| 순서 | 대상 | 이유 |
|---:|---|---|
| 1 | `1_높음` | 제외 후보, 이름 애매, 내부 화장실 가능성처럼 데이터 정확도에 직접 영향이 큼 |
| 2 | `2_중간` | 전동보장구 충전소, 경로당 정책 검토, 시설명 보정 후보처럼 확인 후 기준 확정 필요 |
| 3 | `3_낮음` | 유지 가능성이 높지만 샘플링으로 위치/명칭만 확인 |

## 판정 기준

| 판정 | 기준 |
|---|---|
| 유지 | 장소명, 위치, 카테고리가 실제와 크게 다르지 않음 |
| 이름 보정 | 위치는 맞지만 이름이 너무 포괄적이거나 실제 상호와 다름 |
| 카테고리 보정 | 장소는 맞지만 `화장실`, `음식·카페`, `의료·보건` 등 UI 분류가 어색함 |
| 위치 보정 | 장소는 맞지만 지도 좌표가 건물/출입구와 눈에 띄게 어긋남 |
| 제외 후보 | 장소 자체가 불명확하거나 서비스 목적지로 쓰기 어려움 |

## 우선 확인 기준

| 분류 | 먼저 볼 것 |
|---|---|
| 화장실 | 빌딩, 은행, 주유소, 아파트, 호텔, 병원, 학교, 종교시설 등 내부 화장실 후보 |
| 음식·카페 | 상호명이 아니라 `일반음식점`, `휴게음식점`처럼 업종명만 있는 데이터 |
| 의료·보건 | 병원명이 아니라 `의원·치과의원...`처럼 시설 유형명만 있는 데이터 |
| 복지·돌봄 | 실제 시설명 여부, 경로당을 목적지로 노출할지 여부 |
| 전동보장구 충전소 | 좌표가 실제 충전 위치 또는 시설 대표 위치로 쓸 수 있는지 |
| 관광지 | 대표 좌표가 너무 넓거나 입구와 멀지 않은지 |

## 확인 방법

1. `facility_validation_high_first_pass.csv`에서 `first_pass_decision`이 있는 행부터 본다.
2. `map_url`로 지도 위치를 확인하고, 필요하면 `roadview_url`로 주변을 본다.
3. `review_status`에는 `KEEP`, `RENAME`, `RECATEGORY`, `RELOCATE`, `EXCLUDE`, `NEEDS_DECISION` 중 하나를 적는다.
4. `review_note`에는 판단 근거를 짧게 적는다.

## 1차 판정 초안

`facility_validation_high_first_pass.csv`의 `first_pass_decision`은 실제 반영값이 아니라 초안이다.

| 값 | 의미 |
|---|---|
| `LIKELY_EXCLUDE` | 내부 화장실 가능성이 높아 제외 가능성이 큼 |
| `EXCLUDE_UNLESS_NAME_MATCHED` | 실제 상호를 복구하지 못하면 제외 |
| `RENAME_OR_EXCLUDE` | 실제 기관명을 복구하면 이름 보정, 못 하면 제외 |
| `LOCATION_REVIEW` | 구군/위치 판별이 약해 위치 확인 필요 |

## P2 처리 기준

P2는 전체 276개다. 전수 로드뷰 검증 대상이 아니라, 유형별 정책을 먼저 정하고 샘플만 확인한다.

| 유형 | 개수 | 처리 방향 |
|---|---:|---|
| 전동보장구 충전소 | 194 | 서비스 목적지로 유지. 명칭 오류와 명확한 중복은 정리 완료 |
| 복지·돌봄 이름 보정 | 26 | 실제 시설명 복구 가능 여부 확인. 복구 불가 시 제외 후보 |
| 경로당 정책 검토 | 12 | 경로당을 일반 목적지로 노출할지 정책 결정 |
| 화장실 공공성/이름 보정 | 26 | 공공 이용 가능성 확인 후 유지/이름보정/제외 결정 |
| 숙박 이름 보정 | 10 | 실제 숙박시설명 복구 가능 여부 확인 |
| 의료·보건 이름 보정 | 4 | 실제 의료기관명 복구 가능 여부 확인 |
| 위치 확인 | 4 | 구군 미분류 또는 위치 판별 약한 데이터 확인 |

## P1/P2 판정 방식

P1/P2 전체 848개는 전수 판정 대상이다. 다만 전부 로드뷰로 보는 것이 아니라, 먼저 판정 방식으로 나눈다.

| 판정 방식 | 개수 | 의미 |
|---|---:|---|
| `NAME_DATA_INVALID` | 182 | 이름이 업종명뿐이라 로드뷰 확인보다 이름 데이터 복구/제외 판단이 먼저 |
| `NEEDS_SOURCE_NAME_RECOVERY` | 92 | 실제 시설명이 아니라 유형명이라 원본/주소 기반 이름 복구 필요 |
| `WELFARE_POLICY_REVIEW` | 12 | 경로당 등 서비스 노출 정책 결정 필요 |
| `INTERNAL_TOILET_POLICY_REVIEW` | 350 | 내부 화장실 가능성이 높아 서비스에서 제외할지 정책 결정 필요 |
| `KEEP_BUT_LOCATION_SAMPLE_REVIEW` | 197 | 유지 후보지만 좌표 품질 확인 필요 |
| `PUBLIC_TOILET_VISUAL_REVIEW` | 14 | 공공 화장실로 유지 가능한지 지도/로드뷰 확인 필요 |
| `LOCATION_VISUAL_REVIEW` | 1 | 좌표/구군 확인 필요 |

`needs_visual_check`는 실제 존재 확정 여부가 아니라 지도/로드뷰 확인이 필요한지 여부다.

## POI 매칭 기준

POI 매칭은 전체 4,415개에 적용한다. 로드뷰보다 먼저 사용해서 장소명, 주소, 좌표, 카테고리 맥락을 확인한다.

| 값 | 의미 |
|---|---|
| `MATCH_STRONG` | 원본 좌표 근처 POI와 이름/주소/카테고리 점수가 강하게 맞음 |
| `MATCH_MEDIUM` | 매칭 가능성이 높지만 이름 또는 거리 확인 필요 |
| `MATCH_WEAK` | 가까운 POI는 있으나 이름/주소/카테고리 확인 필요 |
| `MATCH_REVIEW` | 이름 또는 주소 단서가 일부 있어 수동 확인 필요 |
| `NEARBY_ONLY` | 근처 POI만 있고 매칭 근거가 약함 |
| `NO_MATCH` | 300m 이내 POI 후보 없음 |

## 산출 파일

| 파일 | 용도 |
|---|---|
| `data/reports/facility_validation/facility_validation_queue.csv` | 전체 편의시설 검증 큐 |
| `data/reports/facility_validation/facility_validation_queue_high.csv` | 전체 우선 검증 572개 |
| `data/reports/facility_validation/facility_validation_high_first_pass.csv` | 전체 우선 검증 572개에 대한 1차 판정 초안 |
| `data/reports/facility_validation/facility_validation_queue_medium.csv` | P2 중간 검증 276개 |
| `data/reports/facility_validation/facility_validation_medium_grouped_summary.csv` | P2 유형별 묶음 요약 |
| `data/reports/facility_validation/facility_validation_review_targets_p1_p2.csv` | P1/P2 전체 848개 판정 방식 분리 |
| `data/reports/facility_validation/facility_validation_review_targets_p1_p2_summary.csv` | P1/P2 판정 방식 요약 |
| `data/reports/facility_validation/facility_validation_review_targets_all_with_poi.csv` | 전체 4,415개 POI 매칭 결과 |
| `data/reports/facility_validation/facility_validation_review_targets_p1_p2_with_poi.csv` | P1/P2 848개 POI 매칭 결과 |
| `data/reports/facility_validation/facility_validation_review_targets_p3_with_poi.csv` | P3 3,567개 POI 매칭 결과 |
| `data/reports/facility_validation/facility_validation_poi_match_summary.json` | POI 매칭 요약 |
| `data/reports/facility_validation/facility_validation_district_summary.csv` | 구별 검증 대상 개수 요약 |
| `data/reports/facility_validation/district_high/` | 구별 우선 검증 대상 파일 |
| `data/reports/facility_validation/facility_validation_queue_haeundae.csv` | 해운대구 검증 큐 |
| `data/reports/facility_validation/facility_validation_queue_haeundae_high.csv` | 해운대구 우선 검증 59개만 분리한 작업 파일 |
| `data/reports/facility_validation/facility_validation_haeundae_high_first_pass.csv` | 해운대구 우선 검증 59개에 대한 1차 판정 초안 |
| `data/reports/facility_validation/facility_validation_summary.json` | 우선순위/조치별 요약 |
