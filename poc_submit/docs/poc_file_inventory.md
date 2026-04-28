# PoC 파일 정리 기준

## 폴더 역할

| 폴더 | 역할 | 정리 기준 |
|---|---|---|
| `assets/data` | `index.html`이 직접 읽는 지도 표시용 JS | 현재 지도에서 참조하는 파일만 유지 |
| `data/adopted` | 채택 데이터, ERD 반영 후보 | 팀 공유 기준 데이터만 유지 |
| `data/source` | 외부/원본 데이터 | 원본명 유지, 가공 파일과 섞지 않음 |
| `data/staging` | 중간 산출물 | 재생성 가능하므로 용량이 커지면 압축/보관 후보 |
| `data/reports` | 검증/분석 산출물 | 의사결정에 필요한 최신 파일 중심으로 유지 |
| `docs` | 기준/결정 문서 | 최종 기준과 현재 판단 근거를 문서화 |
| `scripts` | 재생성 스크립트 | 현재 쓰는 파이프라인만 유지하고 실험 스크립트는 archive 후보 |
| `archive` | 사용 중단한 실험물 | 삭제 대신 보관 |

## 현재 지도 런타임 참조

`index.html`은 현재 아래 파일만 직접 읽는다.

| 파일 | 상태 |
|---|---|
| `assets/data/stairs-data.js` | 사용 중 |
| `assets/data/crosswalks-data.js` | 사용 중 |
| `assets/data/facilities-data.js` | 사용 중 |
| `assets/data/road-polygons-index-data.js` | 사용 중 |
| `assets/data/road-slope-surface-index-data.js` | 사용 중 |
| `assets/data/busan-stair-review-candidates-data.js` | 사용 중 |
| `assets/data/accessibility-summary-data.js` | 사용 중 |

## 정리 완료

| 대상 | 처리 |
|---|---|
| TMAP 횡단보도 실험 파일 | `archive/20260426_tmap_reverted`로 이동 |

## 아직 정리하지 않은 후보

아래는 바로 지우면 재생성 경로나 지도 기능에 영향을 줄 수 있어 보류한다.

| 대상 | 이유 |
|---|---|
| `assets/data/haeundae-road-polygons-data.js` | 현재 `index.html`은 직접 읽지 않지만, 과거 해운대 계단 후보 생성 스크립트가 참조 |
| `data/staging/road_polygons` | 대용량 중간 산출물이지만 도로 표시/계단 후보 생성 재현에 필요할 수 있음 |
| `data/staging/slope_analysis_staging.csv` | 185MB 대용량 중간 산출물. 재생성 가능 여부 확인 후 archive/삭제 판단 |
| `data/source/poi/busan_poi_processed.csv` | 162MB 캐시. 편의시설 재검증 속도 때문에 유지 권장 |
| `data/reports/facility_validation/kakao_search_cache.jsonl` | 카카오 검색 캐시. 재검증 속도 때문에 유지 권장 |

## 삭제하면 안 되는 것

| 대상 | 이유 |
|---|---|
| `data/adopted/*` | 현재 팀 공유/DB 반영 후보 |
| `data/source/*` | 원본 데이터 |
| `assets/data/*-index-data.js` | 지도에서 동적 로딩에 사용 |
| `assets/data/road-polygons/*` | 도로 폭/면 구별 표시 데이터 |
| `assets/data/road-slope-surface/*` | 도로 경사/노면/폭 구별 표시 데이터 |
