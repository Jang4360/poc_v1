# 해운대구 계단 검수 기준

## 목적

수치지형도에서 계단으로 분류된 객체 중 보행약자 경로 판단에 실제 영향을 줄 가능성이 높은 계단을 우선 검수한다.

## 원천 데이터

| 데이터 | 사용 기준 |
|---|---|
| 계단 | 수치지형도 `N3A_C0390000`, `STRU = SRD001` |
| 도로 | 해운대구 도로중심선 + 도로폭으로 생성한 polygon |
| 횡단보도 | 부산 횡단보도 adopted 데이터 |
| 편의시설 | 보행약자 편의시설 adopted 데이터 |

## 우선순위

| priority | 기준 | reviewStatus |
|---|---|---|
| `P1` | 도로 polygon과 겹치거나 5m 이내 | `CANDIDATE` |
| `P2` | 도로 5~20m 이내이고, 횡단보도 30m 이내 또는 편의시설 50m 이내 | `CANDIDATE` |
| `P3` | 도로 5~20m 이내이나 주변 연결 지표가 약함 | `LOW_PRIORITY` |
| `P4` | 도로 20m 초과 | `LOW_PRIORITY` |

## 보조 기준

| 항목 | 기준 |
|---|---|
| 횡단보도 근접 | 30m 이내 |
| 편의시설 근접 | 50m 이내 |
| 중복 후보 | 계단 간 15m 이내 클러스터 |
| 규모 가점 | 폭 3m 이상 또는 면적 50㎡ 이상 |

## 검수 상태

| status | 의미 |
|---|---|
| `CANDIDATE` | 보행 경로 영향 가능성이 높아 우선 검수 대상 |
| `CONFIRMED` | 수동 검수로 실제 보행 장애 계단 확인 |
| `LOW_PRIORITY` | 계단은 맞지만 경로 영향 가능성이 낮음 |
| `DUPLICATE` | 동일 계단 조각 또는 중복 후보 |
| `EXCLUDED` | 사유지 내부, 시설 내부 등 서비스 경로와 무관 |
| `UNKNOWN` | 판단 보류 |

## 산출물

| 파일 | 설명 |
|---|---|
| `data/reports/stair_review/haeundae_stair_review_candidates.csv` | 검수용 CSV |
| `data/reports/stair_review/haeundae_stair_review_candidates.geojson` | 지도 표시용 GeoJSON |
| `data/reports/stair_review/haeundae_stair_review_summary.json` | 요약 통계 |

