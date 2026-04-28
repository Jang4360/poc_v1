# PoC 산출물 인벤토리

## 지도 실행 파일

| 파일 | 설명 |
|---|---|
| `index.html` | 정적 지도 PoC |
| `README.md` | 실행 및 기준 요약 |

## 지도 데이터

| 파일/폴더 | 설명 |
|---|---|
| `assets/data/facilities-data.js` | ERD v3 기준 편의시설 13,564개 |
| `assets/data/accessibility-summary-data.js` | 접근성 featureType 요약 |
| `assets/data/busan-stair-review-keep-review-data.js` | P1/P2 계단 후보 790개 |
| `assets/data/crosswalks-data.js` | 횡단보도 표시 데이터 |
| `assets/data/road-slope-surface/` | 구군별 경사·노면·폭 선형 데이터 |
| `assets/data/road-polygons/` | 구군별 도로면 polygon 데이터, 기본 OFF |

## 최종 CSV

| 파일 | 설명 |
|---|---|
| `data/final/facilities/places_erd.csv` | `places` 반영 후보 13,564개 |
| `data/final/facilities/place_accessibility_features_erd.csv` | 접근성 feature 42,565개 |
| `data/final/stairs/stair_candidates_p1_p2.csv` | 지도 표시 기준 계단 후보 790개 |

## 제출 시 주의

`data/reports/roadview_validation_test`와 같은 로드뷰 캡처/AI 검증 실험 산출물은 최종 지도 실행에 필요하지 않다. 다만 현재 폴더에서는 시행착오 추적을 위해 보존할 수 있다.
