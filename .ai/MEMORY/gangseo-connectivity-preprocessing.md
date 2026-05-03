# Gangseo Connectivity Preprocessing

Date: 2026-05-03

## Scope

Four-dong Gangseo graph review scope:

- 신호동
- 녹산동
- 명지동
- 화전동

The editor review scope was later expanded from the tight dong bboxes to each dong bbox plus roughly 1km, then served as a pre-sliced graph payload.

## Source And Runtime Files

Canonical v7 source files:

- `etl/raw/gangseo_road_segments_v7.csv`
- `etl/raw/gangseo_road_nodes_v7.csv`

Backups before the first 0-12m/split apply:

- `runtime/graphhopper/topology/backups/gangseo_road_segments_v7_before_0_12_split_20260503.csv`
- `runtime/graphhopper/topology/backups/gangseo_road_nodes_v7_before_0_12_split_20260503.csv`

Current live editor files:

- `runtime/graphhopper/topology/gangseo_four_dong_plus1km_current_v7_live_0_12_split_segments.csv`
- `runtime/graphhopper/topology/gangseo_four_dong_plus1km_current_v7_live_0_12_split_nodes.csv`
- `runtime/graphhopper/topology/gangseo_four_dong_plus1km_current_v7_live_0_12_split_bridge_1km_only_analysis.json`
- `runtime/graphhopper/topology/gangseo_four_dong_plus1km_current_v7_live_0_12_split_bridge_review.json`

## Pipeline Rule

For automatic connector preprocessing, run in this order:

1. Validate segment/node CSV with `graphhopper/scripts/validate_csv_graph.py`.
2. Analyze connectivity with `graphhopper/scripts/analyze_connectivity.py`.
3. Apply only prerequisite node merge, 0-12m endpoint connector, and split connector.
4. Exclude 12-20m red connectors from automatic apply.
5. Re-validate and re-analyze.
6. Generate proposed bridge candidates from the latest graph.
7. Display proposed bridge candidates in the editor for review, limited to the configured max bridge distance.

The editor `Edit CSV` apply flow now follows the same order after manual edits:

1. Write manual CSV edits.
2. Re-run prerequisite node merge.
3. Re-run 0-12m connector.
4. Re-run split connector.
5. Rebuild proposed bridge overlay.
6. Reload the latest map payload in the browser.

## Current Verified State

Verified from:

```sh
curl -s 'http://127.0.0.1:3003/api/gangseo-connectivity-data?colors=blue&limit=20000'
```

Latest API summary:

- segments: 14,855
- nodes: 12,648
- components: 2
- endpoints: 903
- proposed bridge candidates within 1km: 0

Interpretation: bridge candidate count of 0 is currently expected for the live editor graph. The remaining non-main component does not produce a proposed bridge under the current bridge-generation rule and `GANGSEO_BRIDGE_MAX_DISTANCE_METER=1000`.

## V8 Merge Output

Date: 2026-05-03

The live four-dong plus 1km editor graph was merged back with the rest of the Gangseo v7 source into v8:

- `etl/raw/gangseo_road_segments_v8.csv`
- `etl/raw/gangseo_road_nodes_v8.csv`
- `runtime/graphhopper/topology/gangseo_v8_merge_report.json`
- `runtime/graphhopper/topology/gangseo_v8_validate_report.json`

Merge rule:

1. Read full v7 source CSVs.
2. Read current live four-dong plus 1km editor CSVs.
3. Use the expanded four-dong bboxes from `runtime/graphhopper/topology/gangseo_four_dong_plus1km_slice_report.json`.
4. Remove full v7 segments when their `edgeId` appears in the live slice.
5. Remove full v7 segments when any segment geometry coordinate falls inside one of the expanded four-dong bboxes.
6. Append all live slice segments.
7. Rebuild the node CSV from final segment references, preferring live node rows when a `vertexId` exists in both sources.

V8 merge counts:

- full v7 source: 46,713 segments, 48,911 nodes
- removed from full v7 for replacement: 15,532 segments
- live priority slice inserted: 14,855 segments, 12,648 nodes
- v8 output: 46,036 segments, 47,489 nodes

V8 validation summary:

- bad node geometries: 0
- duplicate node IDs: 0
- bad node references: 0
- bad segment geometries: 0
- endpoint mismatches: 0
- enum violations: 0
- duplicate edge IDs: 0
- self loops: 0
- isolated nodes: 0
- connected components: 5,152
- duplicate node-pair edges: 471

The duplicate node-pair edges are not merge-introduced overlap; full v7 already had 493 duplicate node-pair edges. V8 reduces that count to 471, but global cleanup of pre-existing reverse/parallel edges outside the four-dong working scope was not included in this merge.

## Actual Connector-Minimization Flow

The implemented flow is close to the earlier notes, but the exact behavior is:

1. Analyze the current CSV graph and write a connectivity JSON containing components, endpoints, node-merge candidates, 0-12m connector candidates, 12-20m low-priority candidates, split candidates, and summary counts.
2. Apply prerequisite node merges first.
3. Apply 0-12m endpoint-to-endpoint connectors automatically.
4. Apply split connectors automatically by splitting the target segment and connecting the endpoint to the split node.
5. Do not automatically apply 12-20m connectors.
6. Re-validate and re-analyze the edited graph.
7. Generate proposed bridge candidates from remaining components against the largest/main component.
8. Limit proposed bridge display by `GANGSEO_BRIDGE_MAX_DISTANCE_METER`.
9. Show proposed bridge candidates in the Kakao HTML editor for review, including clickable bridge markers.
10. On `Edit CSV`, repeat manual edit write -> node merge -> 0-12m connector -> split connector -> proposed bridge rebuild -> browser reload.

Differences from the earlier written procedure:

- Approval was not required for 0-12m and split candidates in this final editor flow; they are automatically applied after manual edits.
- 12-20m red connectors are intentionally excluded from automatic apply and from the current bridge-only display.
- Proposed bridge is generated after automatic connector minimization and is review/display-only unless a later workflow explicitly applies it.
- The current graph does not apply bridge candidates because the latest four-dong plus 1km live graph has 0 proposed bridge candidates under the 1km rule.

## Main Files To Modify

Use these files to continue development:

- `etl/noksan_sinho_songjeong_hwajeon_segment_02c_graph_edit.html`: Kakao map editor UI, connector layer toggles, bridge marker rendering, edit reload behavior.
- `etl/scripts/27_serve_gangseo_connector_editor.py`: editor API server, payload slicing, edit CSV apply flow, auto connectivity and bridge recomputation.
- `graphhopper/scripts/analyze_connectivity.py`: 0-12m, 12-20m, split, and node-merge candidate analysis.
- `graphhopper/scripts/apply_connectivity_candidates.py`: candidate application into segment/node CSV.
- `graphhopper/scripts/bridge_remaining_components.py`: proposed bridge candidate generation.
- `graphhopper/scripts/validate_csv_graph.py`: CSV graph validation.

## Current Editor Run Command

```sh
GANGSEO_GRAPH_PAYLOAD_PRESLICED=1 \
GANGSEO_GRAPH_BBOX_BUFFER_METER=1000 \
GANGSEO_BRIDGE_MAX_DISTANCE_METER=1000 \
python3 etl/scripts/27_serve_gangseo_connector_editor.py \
  --host 127.0.0.1 \
  --port 3003 \
  --segment-csv runtime/graphhopper/topology/gangseo_four_dong_plus1km_current_v7_live_0_12_split_segments.csv \
  --node-csv runtime/graphhopper/topology/gangseo_four_dong_plus1km_current_v7_live_0_12_split_nodes.csv \
  --analysis-json runtime/graphhopper/topology/gangseo_four_dong_plus1km_current_v7_live_0_12_split_bridge_1km_only_analysis.json \
  --review-json runtime/graphhopper/topology/gangseo_four_dong_plus1km_current_v7_live_0_12_split_bridge_review.json \
  --graph-segment-csv runtime/graphhopper/topology/gangseo_four_dong_plus1km_current_v7_live_0_12_split_segments.csv \
  --graph-node-csv runtime/graphhopper/topology/gangseo_four_dong_plus1km_current_v7_live_0_12_split_nodes.csv
```

Static editor URL:

```text
http://127.0.0.1:3000/etl/noksan_sinho_songjeong_hwajeon_segment_02c_graph_edit.html?v=20260503-plus1km-bridge-only
```

## Reproduction Prompt

Use this prompt in a future Codex session:

```text
작업 위치는 /Users/jangjooyoon/Desktop/JooYoon/ssafy/poc_v1 입니다.

목표:
Gangseo v7 도로 그래프에서 신호동, 녹산동, 명지동, 화전동 4개 동을 대상으로 connector 전처리와 Kakao SDK HTML 검수 편집기를 재현/개선해주세요.

반드시 먼저 읽을 파일:
- .ai/MEMORY/gangseo-connectivity-preprocessing.md
- etl/noksan_sinho_songjeong_hwajeon_segment_02c_graph_edit.html
- etl/scripts/27_serve_gangseo_connector_editor.py
- graphhopper/scripts/analyze_connectivity.py
- graphhopper/scripts/apply_connectivity_candidates.py
- graphhopper/scripts/bridge_remaining_components.py
- graphhopper/scripts/validate_csv_graph.py

기준 CSV:
- etl/raw/gangseo_road_segments_v7.csv
- etl/raw/gangseo_road_nodes_v7.csv

현재 live 검수 CSV:
- runtime/graphhopper/topology/gangseo_four_dong_plus1km_current_v7_live_0_12_split_segments.csv
- runtime/graphhopper/topology/gangseo_four_dong_plus1km_current_v7_live_0_12_split_nodes.csv

원하는 처리 순서:
1. CSV validate
2. connectivity analyze
3. prerequisite node merge 적용
4. 0-12m connector 적용
5. split connector 적용
6. 12-20m connector는 자동 적용하지 않음
7. 최신 graph 기준으로 proposed bridge 재계산
8. proposed bridge는 HTML 지도에서 검수용으로만 표시
9. Edit CSV 시에도 manual edit 반영 후 3~8번이 자동 재실행되도록 유지

현재 편집기 실행 조건:
- GANGSEO_GRAPH_PAYLOAD_PRESLICED=1
- GANGSEO_GRAPH_BBOX_BUFFER_METER=1000
- GANGSEO_BRIDGE_MAX_DISTANCE_METER=1000
- API port 3003
- static HTML port 3000

확인할 것:
- /api/gangseo-connectivity-data?colors=blue&limit=20000 응답의 segment/node/component/bridge count
- HTML에서 proposed bridge marker가 보이고 클릭 가능한지
- scripts/verify.sh 통과 여부
```
