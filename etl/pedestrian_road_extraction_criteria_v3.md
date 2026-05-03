# Pedestrian Road Extraction Criteria v3

## Purpose

This criteria version extends `pedestrian_road_extraction_criteria_v2.md` for the
CSV-backed manual editor.

v2 remains the source-of-truth road-surface extraction method: centerlines are
buffered by road width, merged into road-surface polygons, and polygon boundary
rings are emitted as `ROAD_BOUNDARY` and `ROAD_BOUNDARY_INNER` LineStrings.

v3 adds a graph-adapter layer on top of the v2 boundary output. Its goal is to
make the editor usable by creating only meaningful graph nodes while keeping the
road-boundary segments visually continuous on the basemap.

Use v3 when the required output is an editable node/segment CSV generated from
v2 road-boundary geometry.

## Inputs

The v3 graph adapter consumes the v2 GeoJSON payload:

- `layers.roadSegments.features[]` from v2.
- Allowed `segmentType`: `ROAD_BOUNDARY`, `ROAD_BOUNDARY_INNER`.
- Each source feature geometry must be a `LineString`.
- `layers.roadNodes` from v2 is ignored because v2 intentionally leaves it empty.

The v2 extraction inputs and artifact rejection rules still apply unchanged.

## Graph Adapter Algorithm

1. Select the target dong or district area by bbox.
2. Keep only v2 boundary features intersecting that area.
3. Process each source `LineString` independently.
4. Remove consecutive duplicate coordinates.
5. Simplify source coordinates with Ramer-Douglas-Peucker:
   - default tolerance: `0.00002` degrees
   - simplification must preserve first and last coordinates
6. Detect candidate corner coordinates inside each simplified source line:
   - turn angle must be `>= 55` degrees
   - both adjacent legs must be `>= 15m`
   - keep at most `1` representative corner per source line by default
7. Build segment pieces by splitting the source line at:
   - line start
   - accepted representative corner
   - line end
8. Preserve line shape between graph nodes:
   - each output segment keeps the source shape coordinates between its endpoints
   - shape coordinates are capped to `5` points per segment by default
   - endpoint coordinates are later replaced by the snapped representative node
9. Collect every segment endpoint and accepted corner as raw node candidates.
10. Snap raw node candidates into representative graph nodes:
    - default snap radius: `8m`
    - candidates within the radius belong to the same node cluster
    - cluster representative is the candidate closest to the cluster centroid
    - do not create multiple black node markers for one visible junction cluster
11. Rebuild every output segment using snapped node ids:
    - `fromNodeId` and `toNodeId` must reference the snapped representative nodes
    - segment geometry first and last coordinates must match those node coordinates
    - intermediate geometry coordinates keep the simplified source road-boundary shape
12. Drop degenerate self-loop segments only when both endpoints snap into the same
    representative node.
13. Recompute node degree after snapping.
14. Emit CSV-compatible `roadNodes` and `roadSegments`.

## Node Rules

Create graph nodes only for:

- source line start and end after simplification
- accepted representative corners
- snapped representative junction clusters

Do not create graph nodes for:

- every coordinate in a curved source line
- tiny zigzag vertices shorter than the minimum corner-leg threshold
- multiple nearly overlapping endpoints at the same visible junction
- artifact edges already rejected by v2

## Segment Connectivity Rules

Reducing nodes must not leave visible road-boundary gaps.

- A segment must exist between every consecutive pair of retained anchors on a
  source line.
- When two raw anchors snap into one representative node, all incident segments
  must reference that same node id.
- When an anchor is removed because it is not meaningful enough to become a node,
  the surrounding source shape must remain inside the segment geometry.
- Do not infer arbitrary cross-road connectors between different source features.
  Nearby features become connected only by sharing the snapped representative node.

## Default Parameters

```text
cornerAngleDegrees=55
lineToleranceDegrees=0.00002
maxShapePoints=5
minCornerLegMeter=15
maxCornerNodesPerLine=1
nodeSnapMeter=8
```

Tune these defaults only after the same visual failure repeats across several
areas. Record any changed threshold in the output metadata and in a follow-up
criteria note.

## Output Schema

v3 emits the same CSV-compatible graph schema used by the manual editor:

- `layers.roadNodes.features[]`: `Point` features with `vertexId`, `sourceNodeKey`,
  `nodeType`, and `degree`
- `layers.roadSegments.features[]`: `LineString` features with `edgeId`,
  `fromNodeId`, `toNodeId`, `segmentType`, and `lengthMeter`

Allowed segment types remain:

- `ROAD_BOUNDARY`
- `ROAD_BOUNDARY_INNER`

v3 must not emit synthetic sidewalk repair links such as transition connectors,
gap bridges, cross-side corner bridges, or crossing links.

## Visual Acceptance Criteria

Open the generated HTML on the Kakao basemap and scan the target area.

The output is acceptable only when:

- red segments continue to follow visible road edges from v2
- dense intersections do not show many black nodes piled on the same location
- a right-angle or clearly angled road-boundary turn has one representative node,
  not several adjacent duplicate nodes
- curved road edges use segment shape coordinates instead of many graph nodes
- node reduction does not create visible breaks along a source road-boundary line
- nearby line endpoints at the same visible junction share one graph node
- arbitrary diagonal or triangular connectors between unrelated source lines are
  not introduced
- `ROAD_BOUNDARY_INNER` remains limited to holes from the v2 road-surface union

## Automated Validation

Run the Daejeo1 focused graph-adapter tests after changing v3 implementation:

```powershell
python -m pytest etl/tests/test_daejeo1_simplified_test_csv.py -q
```

Validate generated CSV payloads before opening the editor:

```powershell
python - <<'PY'
from pathlib import Path
from etl.common import segment_graph_db

payload = segment_graph_db.build_csv_payload(
    node_csv=Path("etl/daejeo1_road_nodes_simplified_test.csv"),
    segment_csv=Path("etl/daejeo1_road_segments_simplified_test.csv"),
)
print(segment_graph_db.validate_payload(payload))
PY
```

Run repository verification before finalizing documentation or structural changes:

```powershell
scripts/verify.sh
```
