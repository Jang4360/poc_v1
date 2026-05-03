# 08 Gangseo OSM and DEM Attribute Enrichment

> Created: 2026-05-03  
> Purpose: Plan how to enrich `gangseo_road_segments_mapping_v2.csv` using the newly downloaded OSM and DEM geometry sources.

## File Variables

| Alias | Current file | Meaning |
|---|---|---|
| `mapping.csv` | `etl/raw/gangseo_road_segments_mapping_v2.csv` | Current segment attribute mapping target |
| `osm_source.pbf` | `etl/raw/부산광역시_260502.osm.pbf` | Selected OSM source, extracted from Geofabrik South Korea PBF by Busan administrative boundary |
| `osm_source.gpkg` | `etl/raw/south-korea-260502-free.gpkg/south-korea.gpkg` | Same Geofabrik timestamp, processed GIS layer format; use only for inspection or admin boundary extraction |
| `dem_source.tif` | `etl/raw/부산광역시_partial_N35_E128_DEM.tif` | Partial Copernicus DEM tile intersecting Busan west/N35/E128 |
| `braille_source.csv` | `etl/raw/점자블록.csv` | Primary source for tactile paving / braille block state before OSM fallback |
| `mapping_v3.csv` | `etl/raw/gangseo_road_segments_mapping_v3.csv` | New enriched output copied from `mapping.csv`; existing populated values are preserved |

## Source Decision

- `south-korea-260502.osm.pbf` and `south-korea-260502-free.gpkg/south-korea.gpkg` are the same Geofabrik South Korea OSM snapshot timestamp: `2026-05-02T20:21:30Z`.
- Use `osm_source.pbf` as the enrichment source because it keeps raw OSM tags better than the processed free GPKG layers.
- Keep `osm_source.gpkg` only as a convenience source for layer inspection and administrative boundary geometry.
- `dem_source.tif` is not a full Busan DEM. It is only the intersection of Busan bounds with Copernicus tile `N35_E128`.

## Current Extracts

| File | Status | Note |
|---|---|---|
| `etl/raw/부산광역시_260502.osm.pbf` | created | Busan administrative boundary extract from Geofabrik PBF |
| `etl/raw/부산광역시_partial_N35_E128_DEM.tif` | created | Partial GeoTIFF crop from `N35_E128`; does not cover all of Busan |
| `etl/raw/점자블록.csv` | validated | `3,625` rows; columns: `geom`, `brailleBlockState`; values: `yes=3,245`, `no=380` |
| `etl/raw/gangseo_road_segments_mapping_v3.csv` | created | `46,036` rows; generated from v2 with UNKNOWN-only enrichment |
| `runtime/etl/gangseo-osm-dem-attribute-enrichment/report_v3.json` | created | Enrichment report with before/after coverage and source stats |

## Update Policy

- Create `mapping_v3.csv` by copying `mapping.csv` first.
- Preserve all existing populated values in `mapping.csv`.
- Update only target fields that are `UNKNOWN`, blank, or null-like in `mapping.csv`.
- Do not downgrade known values to `UNKNOWN`.
- Do not overwrite existing mapped values from v2 unless a later explicit correction plan defines source priority and conflict rules.
- Record every update source in the report, grouped by source and target column.

## Target Attribute Strategy

| Target column | Primary enrichment source | OSM/DEM fields | Matching rule | Confidence |
|---|---|---|---|---|
| `surfaceState` | `osm_source.pbf` | `surface` | Spatial match OSM ways to `mapping.csv` segment in EPSG:5179. Start at 5m, inspect coverage, then allow 7m and max 10m only if needed. Map paved-like values to `PAVED`, unpaved-like values to `UNPAVED` | medium |
| `widthMeter`, `widthState` | `osm_source.pbf` | `width` | Parse numeric meter width from OSM ways. Start at 5m, inspect coverage, then allow 7m and max 10m only if needed. Recompute `widthState` from width rules | medium |
| `stairsState` | `osm_source.pbf` | `highway=steps`, `step_count`, `ramp`, `handrail` | If OSM step way is within 2m of segment, set `stairsState=YES`; do not propagate beyond direct match | high for YES |
| `signalState` | `osm_source.pbf` | `crossing=traffic_signals`, `crossing:signals=yes`, `traffic_signals=*` | Match crossing/signal nodes or ways only to `segmentType=SIDE_WALK` segments within 5m; set `TRAFFIC_SIGNALS` | medium |
| `audioSignalState` | `osm_source.pbf` | `traffic_signals:sound=yes` | Match signal/crossing node or way only to `segmentType=SIDE_WALK` segments within 5m; set `YES` | medium-high for YES, sparse |
| `brailleBlockState` | `braille_source.csv`, then `osm_source.pbf` fallback | source CSV geometry columns, then OSM `tactile_paving=yes/partial/no` | Load `braille_source.csv` first and match only to `segmentType=SIDE_WALK` segments within 5m. Then update remaining UNKNOWN only from OSM tactile paving within 5m | medium |
| `avgSlopePercent`, `slopeState` | `dem_source.tif`, then `osm_source.pbf` fallback | raster elevation, then OSM `incline` | Sample DEM along segment geometry directly, compute grade percent from endpoint or densified profile, classify with existing slopeState thresholds. Use OSM `incline` fallback only within 10m | low-medium due 30m DEM resolution |
| `walkAccess` | `osm_source.pbf` | pedestrian road tags | Use only positive evidence from pedestrian-accessible OSM features; do not set `NO` from absence | medium |

## Matching Thresholds

| Attribute group | Segment filter | Primary radius / rule | Fallback radius / rule |
|---|---|---|---|
| `signalState`, `audioSignalState`, `brailleBlockState` | `segmentType=SIDE_WALK` only | 5m | no broad fallback without review |
| `stairsState` | all walkable target segments | 2m | none |
| `surfaceState`, `widthMeter`, `widthState` | all target segments | 5m | 7m after coverage review; 10m max |
| `avgSlopePercent`, `slopeState` | all target segments | direct DEM sampling along target segment | OSM `incline` within 10m |

## Guardrails

- Do not penalize `UNKNOWN` directly in routing. Unknown means missing evidence, not bad accessibility.
- Do not infer localized point facilities through neighbor propagation.
- Allowed propagation candidates: `surfaceState`, `widthMeter`, `widthState`, and possibly `avgSlopePercent` only across very short contiguous segments after direct matching.
- Do not propagate: `stairsState`, `signalState`, `audioSignalState`, `brailleBlockState`.
- Preserve source provenance per value in the enrichment report.
- Treat `braille_source.csv` as the primary source for `brailleBlockState`; OSM tactile paving can only fill remaining UNKNOWN values.
- Restrict crossing-specific accessibility facilities to `segmentType=SIDE_WALK`.

## Proposed Implementation Steps

1. Validate `braille_source.csv` columns and value distribution before enrichment. Current source is present with `geom` and `brailleBlockState`.
2. Copy `mapping.csv` to `mapping_v3.csv` as the base output.
3. Load `braille_source.csv` first and fill only UNKNOWN `brailleBlockState` values on `SIDE_WALK` segments within 5m.
4. Build an OSM enrichment extractor that reads `osm_source.pbf` and emits normalized candidate GeoJSON/CSV layers:
   - pedestrian ways
   - step ways
   - crossings and traffic signals
   - tactile paving features
   - width/surface/incline-bearing ways
5. Convert all candidate geometries and `mapping_v3.csv` segment geometries to EPSG:5179.
6. Run spatial matching with the fixed per-attribute thresholds above.
7. Apply only positive evidence to UNKNOWN fields.
8. Recompute derived states only when their base value was newly filled:
   - `widthState` from `widthMeter`
   - `slopeState` from `avgSlopePercent`
9. Add optional conservative 1-hop propagation only for width/surface/slope after direct mapping, behind an explicit flag.
10. Write a report:
   - source candidate counts
   - direct matched counts
   - propagated counts
   - remaining UNKNOWN counts
   - conflict/overwrite counts

## Acceptance Criteria

- `mapping_v3.csv` row count equals `mapping.csv`.
- Geometry and graph columns are unchanged.
- Existing known values from `mapping.csv` are preserved.
- UNKNOWN count decreases for at least `surfaceState`, `widthState`, and `slopeState` without using UNKNOWN penalties.
- `signalState`, `audioSignalState`, and `brailleBlockState` are updated only on `segmentType=SIDE_WALK`.
- `brailleBlockState` uses `braille_source.csv` before OSM fallback.
- `stairsState`, `signalState`, `audioSignalState`, and `brailleBlockState` are updated only from direct spatial evidence.
- A sample route smoke confirms profile divergence does not rely on fabricated UNKNOWN penalties.

## Latest Result

Run date: 2026-05-03

| Check | Result |
|---|---|
| row count | `46,036 -> 46,036` |
| known value overwrite violations | `0` |
| graph validation | passed with same known topology warnings as v2: duplicate node-pair edges `471`, components `5,152` |
| unit tests | `pytest -q etl/tests/test_gangseo_osm_dem_attribute_enrichment.py etl/tests/test_gangseo_v6_attribute_mapping.py` passed |

Coverage changes:

| Attribute | UNKNOWN before | UNKNOWN after | Filled before | Filled after | Delta |
|---|---:|---:|---:|---:|---:|
| `brailleBlockState` | 46,036 | 45,702 | 0 | 334 | +334 |
| `audioSignalState` | 46,031 | 46,031 | 5 | 5 | +0 |
| `stairsState` | 46,000 | 45,996 | 36 | 40 | +4 |
| `signalState` | 45,680 | 45,678 | 356 | 358 | +2 |
| `walkAccess` | 38,057 | 38,057 | 7,979 | 7,979 | +0 |
| `widthMeter / widthState` | 36,165 | 36,162 | 9,871 | 9,874 | +3 |
| `surfaceState` | 26,657 | 26,422 | 19,379 | 19,614 | +235 |
| `avgSlopePercent / slopeState` | 25,908 | 2,384 | 20,128 | 43,652 | +23,524 |
