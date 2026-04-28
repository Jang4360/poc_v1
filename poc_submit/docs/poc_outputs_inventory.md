# PoC 산출물 인벤토리

## 최종 사용 파일

| 파일 | 상태 | 설명 |
|---|---|---|
| `data/adopted/places_erd.csv` | 최종 | DB `places` seed 후보 |
| `data/adopted/place_accessibility_features_erd.csv` | 최종 | DB `place_accessibility_features` seed 후보 |
| `data/adopted/adopted_places_with_accessibility.csv` | 최종 | 원천 추적 포함 장소+접근성 통합본 |
| `data/adopted/adopted_places.csv` | 최종 | 장소 테이블형 산출물 |
| `data/adopted/adopted_place_accessibility.csv` | 최종 | 접근성 속성 테이블형 산출물 |
| `assets/data/facilities-data.js` | 최종 | 지도 표시용 편의시설 GeoJSON |
| `assets/data/accessibility-summary-data.js` | 최종 | 지도 범례/요약용 접근성 집계 |

## 주요 검증 리포트

| 파일 | 설명 |
|---|---|
| `data/reports/facility_validation/facility_kakao_first_refresh_all.csv` | 최종 후보 3,585개에 카카오/POI 매칭을 붙인 리포트 |
| `data/reports/facility_validation/facility_kakao_poi_existence_rule_all.csv` | 카카오/POI 존재성 단순 규칙 재분류 |
| `data/reports/facility_validation/facility_kakao_poi_existence_rule_removed_applied.csv` | 존재성 근거 약한 65개 제거 내역 |
| `data/reports/facility_validation/facility_toilet_context_remove_rule_removed_applied.csv` | 역/터미널/민간/학교 등 화장실 58개 제거 내역 |
| `data/reports/facility_validation/facility_kakao_poi_existence_rule_apply_summary.json` | 65개 제거 반영 요약 |
| `data/reports/facility_validation/facility_toilet_context_remove_rule_summary.json` | 화장실 맥락 제거 반영 요약 |

## 재현용 핵심 스크립트

| 스크립트 | 설명 |
|---|---|
| `scripts/build_source_places_accessibility.py` | 원본 장소/접근성 병합 및 최초 adopted/ERD/지도 데이터 생성 |
| `scripts/build_facility_kakao_first_refresh.py` | 최종 후보 기준 카카오 우선 + POI 보조 매칭 리포트 생성 |
| `scripts/classify_facility_kakao_poi_existence_rule.py` | 카카오/POI 둘 중 하나라도 있으면 유지, 둘 다 약하면 제거 검토 |
| `scripts/apply_facility_existence_remove_candidates.py` | 존재성 근거 약한 65개를 최종 산출물에서 제거 |
| `scripts/apply_facility_toilet_context_remove_rules.py` | 역/터미널/민간/학교 등 화장실 맥락 제거 규칙 반영 |

## 중간 산출물 취급

`data/reports/facility_validation/` 아래 대부분의 CSV는 검토 과정 중 생성된 중간 리포트다.

보존 가치는 있지만, 팀원 공유 시에는 다음 파일만 우선 보면 된다.

```text
facility_kakao_first_refresh_all.csv
facility_kakao_poi_existence_rule_all.csv
facility_kakao_poi_existence_rule_removed_applied.csv
facility_toilet_context_remove_rule_removed_applied.csv
```

나머지는 특정 카테고리 수동 검토 흔적이므로, 삭제하지 말고 `reports`에 보관한다.
