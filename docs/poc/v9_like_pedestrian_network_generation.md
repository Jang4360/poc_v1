# v9-like pedestrian network candidate generation

Date: 2026-05-04

## Goal

강서구 `road_segments_v9.csv`에서 수작업으로 확인된 보행자 네트워크 품질을 기준으로, 다른 구/동에 대해 최소 수작업 검토만 남기는 후보 보행 네트워크를 생성한다.

이 문서는 `etl/scripts/31_generate_pedestrian_network_candidate.py`를 재현 가능하게 실행하기 위한 규칙과 명령을 정리한다.

## Current rule

1. 기준 프로파일은 `etl/raw/gangseo_road_segments_v9.csv`와 `etl/raw/gangseo_road_nodes_v9.csv`에서 계산한다.
2. 후보 생성은 polygon boundary 방식과 `side_graph_loader_02b` 방식 여러 개를 모두 실행한다.
3. 각 방법별로 v9 구조 프로파일과 후보 validation 프로파일을 비교한다.
4. 가장 높은 `similarityPercent` 방법을 최종 CSV/HTML로 복사한다.
5. 후보 그래프에는 `SIDE_LINE`만 생성한다.
6. `SIDE_WALK`/횡단보도 자동 생성은 현재 제외한다. 원천 crosswalk 점을 그대로 사용하면 일부 구간에서 튀어나온 segment가 생겨 검토 비용이 커졌기 때문이다.
7. 후보 생성 직후 Gangseo editor의 `Edit CSV` 자동 보정 순서를 그대로 적용한다.
8. `bridge_remaining_components.py`의 bridge 후보는 최종 segment에 자동 반영하지 않는다. 도로 형태를 따라가지 않는 직선 연결이 생길 수 있으므로 proposed bridge overlay로만 남긴다.
9. 최종 HTML에는 기존 segment와 남은 proposed bridge만 표시한다. proposed bridge는 시작점/끝점 마커와 우선순위 라벨을 함께 그려 연결이 필요한 두 지점을 확인할 수 있게 한다.

## Topology preprocessing rule

`etl/noksan_sinho_songjeong_hwajeon_segment_02c_graph_edit.html`의 `Edit CSV` 버튼에서 검증된 자동 보정 순서를 후보 생성 파이프라인에 반영한다.

1. prerequisite node merge
   - `node_merge_meter=2.0`
   - endpoint 주변 기존 node가 merge 반경 안에 있으면 connector line을 만들지 않고 node를 먼저 병합한다.
2. 0-12m connector
   - `endpoint_candidate_max_meter=12.0`
   - orange connector만 자동 적용한다.
   - red 12-20m 후보는 자동 적용하지 않는다.
3. split connector
   - `split_connector_max_meter=1.0`
   - endpoint가 다른 segment 내부에 거의 닿아 있으면 target segment를 split한 뒤 연결한다.

이 세 단계는 `analyze_connectivity.py`로 후보를 만들고 `apply_connectivity_candidates.py`에 `include_node_merges=True`, `include_low_priority=True`를 주는 방식으로 실행한다.

## Visual cleanup rule from Daejeo1 screenshots

캡처에서 확인된 실패 유형은 다음과 같다.

- 가까운 endpoint가 분리되어 network component가 쪼개짐
- bridge 후보가 최종 segment로 들어가면서 도로 선형을 따르지 않는 직선 연결이 생김
- proposed bridge가 두 연결 지점을 명확히 보여주지 못함

따라서 현재 규칙은 다음을 우선한다.

- 12m 이하의 짧은 topology gap은 node merge, endpoint connector, split connector로만 해결한다.
- bridge 후보는 segment로 자동 편입하지 않고 overlay로 남겨 수작업 판단 대상으로 둔다.
- overlay는 candidate line, 시작점, 끝점, priority label을 함께 표시한다.
- 도로 외 연결이 보이면 bridge 자동 적용을 늘리지 말고 road polygon/source boundary 정제 또는 수작업 review로 넘긴다.

## Similarity metrics

`similarityPercent`는 다음 항목을 가중 비교한다.

- largest component edge ratio
- small component edge ratio
- component density
- duplicate node-pair ratio
- SIDE_WALK ratio
- segment length quantiles: q05, q50, q95
- CSV validation clean 여부

현재 후보 생성 규칙은 `SIDE_WALK`를 생성하지 않으므로, `SIDE_WALK ratio` 점수는 낮게 나올 수 있다. 대신 visual cleanup과 topology 안정성을 우선한다.

## Haeundae U-dong reproduction

```sh
python etl/scripts/31_generate_pedestrian_network_candidate.py \
  --district 해운대구 \
  --source-js poc_submit/assets/data/road-polygons/road-polygons-haeundae-data.js \
  --target-name haeundae_udong \
  --bbox 129.1260,35.1510,129.1665,35.1810 \
  --output-segments etl/raw/haeundae_udong_road_segments_v9_candidate.csv \
  --output-nodes etl/raw/haeundae_udong_road_nodes_v9_candidate.csv \
  --report-json etl/haeundae_udong_v9_candidate_report.json \
  --output-html etl/haeundae_udong_v9_candidate_bridge_view.html \
  --output-data etl/haeundae_udong_v9_candidate_bridge_view_data.json
```

HTML:

```text
http://127.0.0.1:3000/etl/haeundae_udong_v9_candidate_bridge_view.html
```

## Gangseo Daejeo1-dong reproduction

대저1동 bbox는 기존 Gangseo editor의 `GANGSEO_DONG_AREAS["daejeo1"]` 값을 따른다.

```sh
python etl/scripts/31_generate_pedestrian_network_candidate.py \
  --district 강서구 \
  --source-js poc_submit/assets/data/road-polygons/road-polygons-gangseo-data.js \
  --target-name gangseo_daejeo1 \
  --bbox 128.94,35.19,129.005,35.235 \
  --output-segments etl/raw/gangseo_daejeo1_road_segments_v9_candidate.csv \
  --output-nodes etl/raw/gangseo_daejeo1_road_nodes_v9_candidate.csv \
  --report-json etl/gangseo_daejeo1_v9_candidate_report.json \
  --output-html etl/gangseo_daejeo1_v9_candidate_bridge_view.html \
  --output-data etl/gangseo_daejeo1_v9_candidate_bridge_view_data.json \
  --methods side_graph_3200m_converge_15m
```

HTML:

```text
http://127.0.0.1:3000/etl/gangseo_daejeo1_v9_candidate_bridge_view.html
```

Latest run result:

- method: `side_graph_3200m_converge_15m`
- similarity: `74.26%`
- segments: `17,087`
- nodes: `14,916`
- segment types: `SIDE_LINE=17,087`
- connected components: `97`
- largest component edge ratio: `0.921051`
- preprocessing applied: `497` orange connectors, `138` split nodes, `138` yellow node merges, `1,445` duplicate removals
- proposed bridges: `96`
- proposed bridge split: `auto=57`, `review=11`, `held=28`

## Validation commands

```sh
python graphhopper/scripts/validate_csv_graph.py \
  --segments etl/raw/gangseo_daejeo1_road_segments_v9_candidate.csv \
  --nodes etl/raw/gangseo_daejeo1_road_nodes_v9_candidate.csv \
  --report-json etl/gangseo_daejeo1_v9_candidate_validation_report.json

python -m pytest \
  etl/tests/test_district_road_boundary_from_polygons.py \
  etl/tests/test_gangseo_connectivity_analysis.py \
  etl/tests/test_graphhopper_csv_validation.py
```

## Interpretation

- `proposed bridges`는 자동 수렴 후에도 남은 연결 후보다.
- `autoBridgeCandidates`는 다음 자동 수렴 파라미터에서 붙일 수 있는 후보지만, 최종 리포트에서는 `apply_auto=False`로 조회한 잔여 후보 수다.
- `reviewBridgeCandidates`는 거리상 자동 연결보다는 수작업 검토가 안전한 후보다.
- `heldBridgeCandidates`는 현재 review 거리 밖이거나 우선순위가 낮은 후보다.
