# 부산 전체 계단 검수 기준

## 목적

부산 전체 수치지형도 계단 3,744개 중 보행약자 경로 판단에 영향을 줄 가능성이 높은 계단을 우선 검수한다.

## 원천 데이터

| 데이터 | 사용 기준 |
|---|---|
| 계단 | 수치지형도 `N3A_C0390000`, `STRU = SRD001` |
| 도로 | 부산 전체 도로중심선 252,315개 + 도로폭(`RVWD`)으로 생성한 polygon |
| 횡단보도 | 부산 횡단보도 adopted 데이터 |
| 편의시설 | 보행약자 편의시설 adopted 데이터 |

## 우선순위

| priority | 기준 | reviewStatus |
|---|---|---|
| `P1` | 도로 polygon과 겹치거나 5m 이내 | `CANDIDATE` |
| `P2` | 도로 5~20m 이내이고, 횡단보도 30m 이내 또는 편의시설 50m 이내 | `CANDIDATE` |
| `P3` | 도로 5~20m 이내이나 주변 연결 지표가 약함 | `LOW_PRIORITY` |
| `P4` | 도로 20m 초과 | `LOW_PRIORITY` |

## 산출 결과

| priority | 개수 |
|---|---:|
| `P1` | 728 |
| `P2` | 138 |
| `P3` | 862 |
| `P4` | 2,016 |

우선 검수 대상은 `P1 + P2 = 866개`이다.

## 산출물

| 파일 | 설명 |
|---|---|
| `data/staging/road_polygons/busan_road_polygons_5179_simplified.gpkg` | 검수 계산용 부산 전체 도로 polygon |
| `data/staging/road_polygons/busan_road_polygons_4326.gpkg` | 지도 좌표계 변환본 |
| `data/reports/stair_review/busan_stair_review_candidates.csv` | 부산 전체 계단 검수용 CSV |
| `data/reports/stair_review/busan_stair_review_candidates.geojson` | 지도 표시용 GeoJSON |
| `assets/data/busan-stair-review-candidates-data.js` | `index.html` 표시용 JS |
| `data/reports/stair_review/busan_stair_review_summary.json` | 요약 통계 |

