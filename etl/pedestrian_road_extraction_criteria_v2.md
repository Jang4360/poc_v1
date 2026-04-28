# Pedestrian Road Extraction Criteria v2

## Purpose

This criteria version defines the reproducible road-boundary extraction path used by
`etl/haeundae_road_boundary.html`.

The v2 target is not a repaired sidewalk graph. It is a road-surface boundary preview:
road centerlines are expanded by road width, merged into road-surface polygons, and
the resulting polygon boundary rings are rendered as segments on a Kakao basemap.

Use this version when the required visual outcome is "draw only the road edge /
road boundary around a district" and when the same method must be replayed for
another gu by changing only the center, radius, and output filenames.

## Inputs

- District center latitude and longitude in `EPSG:4326`.
- District radius in meters, or a radius that safely covers the district.
- Road centerline shapefile under `etl/raw/`.
- Required shapefile sidecars: `.shp`, `.shx`, `.dbf`.
- Source centerline coordinate reference system: `EPSG:5179`.
- Output coordinate reference system: `EPSG:4326`.
- Road width field: `RVWD`.
- Preferred DBF encoding order: `cp949`, `euc-kr`, then `utf-8`.
- Kakao Map SDK is used only for visual validation and browser preview.

## Reference Generation Commands

Haeundae reference output:

```powershell
python -m etl.scripts.13_generate_segment_02c_centerline --variant road-boundary
```

Other district template:

```powershell
python -m etl.scripts.13_generate_segment_02c_centerline `
  --variant road-boundary `
  --center-lat <district_center_lat> `
  --center-lon <district_center_lon> `
  --radius-meter <radius_meter> `
  --output-html etl/<district_slug>_road_boundary.html `
  --output-geojson etl/<district_slug>_road_boundary.geojson
```

Serve the repository and open the generated HTML through localhost:

```powershell
python -m http.server 3000
```

```text
http://localhost:3000/etl/<district_slug>_road_boundary.html
```

## Algorithm

1. Validate that all required shapefile sidecars exist.
2. Open the DBF with the first working encoding from the supported encoding order.
3. Project the requested district center from `EPSG:4326` to `EPSG:5179`.
4. Build a circular clip area from the projected center and requested radius.
5. Iterate source centerline shapes.
6. Read `RVWD` as road width in meters.
7. Compute road half width:
   - valid `RVWD`: `halfWidth=max(RVWD/2,2.5m)`
   - missing, zero, or invalid `RVWD`: `halfWidth=4.0m`
8. Skip shapes whose bbox plus `halfWidth + 1m` does not intersect the clip area.
9. Split multipart shapes into line parts.
10. Drop empty or near-zero line parts.
11. Clip each centerline part to the district clip area.
12. Buffer each clipped centerline in projected meters:
   - distance: computed `halfWidth`
   - cap style: flat
   - join style: mitre
   - mitre limit: `2.0`
   - resolution: `4`
13. Merge every buffered surface with `unary_union`.
14. Simplify the merged road surface with topology preservation:
   - tolerance: `0.25m`
15. Extract polygon boundary rings:
   - exterior rings become `ROAD_BOUNDARY`
   - interior rings become `ROAD_BOUNDARY_INNER`
16. Remove short perpendicular buffer-cap edges at ring extraction time.
17. Remove internal perpendicular edges that look like centerline-width artifacts
    rather than true road boundaries.
18. Split boundary chains wherever artifact edges were removed.
19. Transform boundary coordinates back to `EPSG:4326`.
20. Emit `LineString` segment features and render them in Kakao HTML.

## Artifact Rejection Rules

### Short Buffer-Cap Edge

Remove a ring edge when all conditions are true:

- edge length is `<= 18.0m`
- angle between previous edge and current edge is between `55` and `125` degrees
- angle between current edge and following edge is between `55` and `125` degrees
- previous and following edges are aligned in opposite directions by at least `135` degrees

This removes short rectangular caps created by buffered clipped centerline ends.

### Internal Perpendicular Edge

Remove a boundary edge when all conditions are true:

- edge length is `<= 36.0m`
- edge midpoint is within `16.0m` of the nearest source centerline
- edge direction is near-perpendicular to the nearest centerline direction
- near-perpendicular means the acute angle is between `60` and `90` degrees

This removes vertical or right-angle tabs that appear inside a road surface and are
not part of the actual road edge.

## Output Schema

The generated GeoJSON payload must include:

- `meta`
- `summary`
- `layers.roadNodes`
- `layers.roadSegments`

`layers.roadNodes` is intentionally empty in v2:

```json
{
  "type": "FeatureCollection",
  "features": []
}
```

Each `layers.roadSegments.features[]` item is a `LineString` feature:

```json
{
  "type": "Feature",
  "properties": {
    "edgeId": 1,
    "segmentType": "ROAD_BOUNDARY",
    "lengthMeter": 12.34
  },
  "geometry": {
    "type": "LineString",
    "coordinates": [[129.0, 35.0], [129.1, 35.1]]
  }
}
```

Allowed `segmentType` values:

- `ROAD_BOUNDARY`
- `ROAD_BOUNDARY_INNER`

The v2 output must not emit synthetic topology nodes, gap bridges, corner bridges,
cross-side connectors, or sidewalk repair links.

## Required Meta Fields

The generated payload `meta` should expose enough information to compare district
runs and detect accidental parameter drift:

- `title`
- `centerLat`
- `centerLon`
- `radiusMeter`
- `sourceShp`
- `sourceEncoding`
- `outputHtml`
- `outputGeojson`
- `localhostUrl`
- `stage`
- `sourceShapeCount`
- `clippedPartCount`
- `bufferedPartCount`
- `skippedPartCount`
- `widthFallbackCount`
- `boundaryRule`
- `halfWidthRule`
- `simplifyMeter`
- `capRemovalMaxMeter`
- `internalPerpendicularPruneCount`
- `internalPerpendicularMaxMeter`
- `internalPerpendicularCenterlineMaxMeter`

Expected `stage` value:

```text
road-boundary-buffer-union
```

Expected `boundaryRule` meaning:

```text
buffer clipped centerlines by RVWD/2, union all road surfaces, then render polygon boundary rings
```

## Visual Acceptance Criteria

Open the generated HTML on the Kakao basemap and scan across the target district.
The output is acceptable only when the following are true:

- red segments follow visible road edges, not road centerlines
- wide roads are represented as road-surface boundaries
- small blank gaps inside ordinary road corridors are mostly filled by the buffer union
- short perpendicular tabs inside roads are removed
- arbitrary cross-road connectors are not introduced
- private apartment blocks, parks, and building courtyards are not treated as roads
  unless the source road centerline and width imply a road surface there
- dense intersections remain readable and do not become a mesh of unrelated links
- `ROAD_BOUNDARY_INNER` is used only for polygon holes created by the road surface union

## Automated Validation

Run focused tests after changing extraction code or thresholds:

```powershell
python -m pytest etl/tests/test_segment_centerline_02c.py -q
```

Run repository verification before finalizing documentation or structural changes:

```powershell
& "C:\Program Files\Git\bin\bash.exe" scripts/verify.sh
```

For every generated district, inspect the command output and HTML summary panel.
Unexpected changes in these fields require review:

- `widthFallbackCount`
- `clippedPartCount`
- `bufferedPartCount`
- `internalPerpendicularPruneCount`
- `summary.segmentCount`
- `summary.segmentTypeCounts`

## Portability Rules For Other Gu

To reproduce the same method in another gu:

1. Keep `--variant road-boundary`.
2. Change only `--center-lat`, `--center-lon`, `--radius-meter`, `--output-html`,
   and `--output-geojson`.
3. Keep the same shapefile source when comparing Busan districts.
4. Keep the same width field semantics: `RVWD` is full road width in meters.
5. Keep all thresholds unchanged for the first run.
6. Tune thresholds only after the same artifact appears repeatedly across the new
   district, not from a single visual exception.
7. Record every district-specific threshold change in a follow-up criteria version
   or a district-specific note.

Recommended output naming:

```text
etl/<district_slug>_road_boundary.html
etl/<district_slug>_road_boundary.geojson
```

Examples:

```text
etl/haeundae_road_boundary.html
etl/suyeong_road_boundary.html
etl/dongnae_road_boundary.html
```

## Tuning Guide

Use this table only after visual inspection confirms a systematic issue.

| Problem | First parameter to inspect | Default | Direction |
| --- | --- | ---: | --- |
| many road-edge gaps remain | `RVWD` coverage and source centerline continuity | source data | verify data first |
| short perpendicular caps remain | `ROAD_BOUNDARY_CAP_MAX_M` | `18.0m` | increase cautiously |
| long right-angle tabs remain inside roads | `ROAD_BOUNDARY_INTERNAL_CAP_MAX_M` | `36.0m` | increase cautiously |
| true side-road entrances disappear | `ROAD_BOUNDARY_INTERNAL_CAP_MAX_M` | `36.0m` | decrease |
| real road boundary corners are over-smoothed | `ROAD_BOUNDARY_SIMPLIFY_M` | `0.25m` | decrease |
| too many tiny jagged pieces appear | `ROAD_BOUNDARY_SIMPLIFY_M` | `0.25m` | increase cautiously |
| narrow alleys disappear | `ROAD_BOUNDARY_MIN_HALF_WIDTH_M` | `2.5m` | decrease only with evidence |
| missing width data creates too-wide roads | `ROAD_BOUNDARY_FALLBACK_HALF_WIDTH_M` | `4.0m` | decrease |

## Known Limits

- v2 derives road boundaries from centerline and width data, not surveyed curbs.
- Kakao basemap geometry is a visual reference, not the extraction source.
- Source centerline omissions cannot be fully recovered by v2.
- Very complex private roads, apartment internal roads, and underground/stacked roads
  may require source-data-specific handling.
- The method favors district-scale visual continuity over centimeter-level curb accuracy.

## Haeundae Reference Snapshot

The accepted Haeundae preview was generated with:

- variant: `road-boundary`
- center: `35.16332, 129.1588705`
- radius: `5000m`
- stage: `road-boundary-buffer-union`
- half-width rule: `halfWidth=max(RVWD/2,2.5m); fallback=4.0m`
- simplify tolerance: `0.25m`
- cap removal max length: `18.0m`
- internal perpendicular removal max length: `36.0m`
- internal perpendicular centerline search: `16.0m`

This snapshot is a reference baseline. Other districts should start from the same
parameters and change only location, radius, and output filenames.
