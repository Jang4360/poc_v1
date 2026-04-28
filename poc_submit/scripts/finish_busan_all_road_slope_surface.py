from __future__ import annotations

import csv
import json
import re
import sys
from pathlib import Path


QGIS_PLUGIN_DIR = r"C:\Program Files\QGIS 3.44.9\apps\qgis-ltr\python\plugins"
sys.path.append(QGIS_PLUGIN_DIR)
sys.path.append(str(Path(__file__).resolve().parent))

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeatureRequest,
    QgsGeometry,
    QgsProject,
    QgsSpatialIndex,
    QgsVectorLayer,
)

from build_busan_all_road_slope_surface import (
    ASSET_DIR,
    DISTRICT_SLUGS,
    INDEX_OUT,
    MASTER_CSV,
    MASTER_GPKG,
    ROAD_CENTERLINES,
    SUMMARY_JSON,
    base_properties,
    init_qgis,
    load_district_boundaries,
    value,
)


TARGET_DISTRICT = "해운대구"


def export_missing_haeundae() -> tuple[str, int]:
    boundaries, _, _ = load_district_boundaries()
    boundary = boundaries[TARGET_DISTRICT]
    slug = DISTRICT_SLUGS[TARGET_DISTRICT]
    output_path = ASSET_DIR / f"road-slope-surface-{slug}-data.js"

    road_layer = QgsVectorLayer(str(ROAD_CENTERLINES), "busan_road_centerlines", "ogr")
    if not road_layer.isValid():
        raise RuntimeError(f"Invalid layer: {ROAD_CENTERLINES}")

    master_layer = QgsVectorLayer(str(MASTER_GPKG), "busan_all_road_slope_surface_master", "ogr")
    if not master_layer.isValid():
        raise RuntimeError(f"Invalid layer: {MASTER_GPKG}")

    road_index = QgsSpatialIndex(road_layer.getFeatures())
    candidate_ids = road_index.intersects(boundary.boundingBox())

    master_lookup = {}
    master_request = QgsFeatureRequest().setFilterFids(candidate_ids)
    for feature in master_layer.getFeatures(master_request):
        fid = int(value(feature, "fid") or feature.id())
        master_lookup[fid] = base_properties(feature, TARGET_DISTRICT, f"{slug}-road-slope:{fid}")

    transformer = QgsCoordinateTransform(
        QgsCoordinateReferenceSystem("EPSG:5179"),
        QgsCoordinateReferenceSystem("EPSG:4326"),
        QgsProject.instance(),
    )

    features = []
    request = QgsFeatureRequest().setFilterFids(candidate_ids)
    for feature in road_layer.getFeatures(request):
        geom = feature.geometry()
        if not geom or geom.isEmpty() or not geom.intersects(boundary):
            continue

        clipped = geom.intersection(boundary)
        if not clipped or clipped.isEmpty():
            continue

        fid = int(value(feature, "fid") or feature.id())
        props = dict(master_lookup.get(fid, {}))
        if not props:
            props = base_properties(feature, TARGET_DISTRICT, f"{slug}-road-slope:{fid}")
        props["sourceId"] = f"{slug}-road-slope:{fid}"
        props["districtGu"] = TARGET_DISTRICT

        clipped_4326 = QgsGeometry(clipped)
        clipped_4326.transform(transformer)
        bbox = clipped_4326.boundingBox()
        features.append(
            {
                "type": "Feature",
                "bbox": [
                    round(bbox.xMinimum(), 7),
                    round(bbox.yMinimum(), 7),
                    round(bbox.xMaximum(), 7),
                    round(bbox.yMaximum(), 7),
                ],
                "geometry": json.loads(clipped_4326.asJson(6)),
                "properties": props,
            }
        )

    collection = {"type": "FeatureCollection", "features": features}
    payload = json.dumps(collection, ensure_ascii=False, separators=(",", ":"))
    output_path.write_text(
        "window.ROAD_SLOPE_SURFACE_BY_DISTRICT = window.ROAD_SLOPE_SURFACE_BY_DISTRICT || {};"
        f"window.ROAD_SLOPE_SURFACE_BY_DISTRICT[{json.dumps(TARGET_DISTRICT, ensure_ascii=False)}] = {payload};\n",
        encoding="utf-8",
    )
    asset_path = f"assets/data/road-slope-surface/{output_path.name}"
    print(f"[asset:{TARGET_DISTRICT}] candidates={len(candidate_ids):,} exported={len(features):,} -> {asset_path}", flush=True)
    return asset_path, len(features)


def count_asset_features(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    return text.count('"type":"Feature"')


def write_index() -> dict[str, int]:
    asset_map = {}
    counts = {}
    for district in sorted(DISTRICT_SLUGS, key=lambda value_: value_):
        slug = DISTRICT_SLUGS[district]
        path = ASSET_DIR / f"road-slope-surface-{slug}-data.js"
        if not path.exists():
            raise FileNotFoundError(f"Missing asset: {path}")
        asset_map[district] = f"assets/data/road-slope-surface/{path.name}"
        counts[district] = count_asset_features(path)

    INDEX_OUT.write_text(
        "window.ROAD_SLOPE_SURFACE_DISTRICT_ASSETS = "
        + json.dumps(asset_map, ensure_ascii=False, separators=(",", ":"))
        + ";\n"
        + "window.ROAD_SLOPE_SURFACE_DISTRICT_COUNTS = "
        + json.dumps(counts, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )
    print(f"[index] {INDEX_OUT}", flush=True)
    return counts


def write_summary(asset_counts: dict[str, int]) -> None:
    summary = {
        "total": 0,
        "walkableSeedCandidates": 0,
        "byDistrict": {},
        "bySurface": {},
        "bySlope": {},
        "byWidth": {},
        "byRisk": {},
        "districtAssetCounts": asset_counts,
        "source": {
            "roadCenterlines": str(ROAD_CENTERLINES),
            "masterGpkg": str(MASTER_GPKG),
            "masterCsv": str(MASTER_CSV),
        },
    }

    with MASTER_CSV.open("r", encoding="utf-8-sig", newline="") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            summary["total"] += 1
            district = row.get("districtGu") or "미분류"
            surface = row.get("pavementQualityLabel") or "미분류"
            slope = row.get("slopeLevel") or "UNKNOWN"
            width = row.get("widthLevel") or "UNKNOWN"
            risk = row.get("riskLevel") or "UNKNOWN"
            summary["byDistrict"][district] = summary["byDistrict"].get(district, 0) + 1
            summary["bySurface"][surface] = summary["bySurface"].get(surface, 0) + 1
            summary["bySlope"][slope] = summary["bySlope"].get(slope, 0) + 1
            summary["byWidth"][width] = summary["byWidth"].get(width, 0) + 1
            summary["byRisk"][risk] = summary["byRisk"].get(risk, 0) + 1
            if row.get("isWalkableSeedCandidate") == "True":
                summary["walkableSeedCandidates"] += 1

    SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[summary] {SUMMARY_JSON}", flush=True)


def main() -> int:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    export_missing_haeundae()
    counts = write_index()
    write_summary(counts)
    return 0


if __name__ == "__main__":
    app = init_qgis()
    try:
        raise SystemExit(main())
    finally:
        app.exitQgis()
