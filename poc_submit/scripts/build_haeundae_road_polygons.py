from __future__ import annotations

import json
import sys
from pathlib import Path


QGIS_PREFIX = r"C:\Program Files\QGIS 3.44.9\apps\qgis-ltr"
QGIS_PLUGIN_DIR = r"C:\Program Files\QGIS 3.44.9\apps\qgis-ltr\python\plugins"
sys.path.append(QGIS_PLUGIN_DIR)

from qgis.core import QgsApplication, QgsCoordinateReferenceSystem, QgsProperty, QgsVectorLayer
from processing.core.Processing import Processing
import processing


QgsApplication.setPrefixPath(QGIS_PREFIX, True)

POC_ROOT = Path(__file__).resolve().parents[1]
V5_ROOT = Path("C:/Users/SSAFY/Desktop/busan-sidewalk-slope-5m-red-v5")

DISTRICT_BOUNDARIES = V5_ROOT / "busan_district_boundaries.gpkg"
ROAD_CENTERLINES = V5_ROOT / "busan_road_centerlines.gpkg"

STAGING_DIR = POC_ROOT / "data" / "staging" / "road_polygons"
ASSET_OUT = POC_ROOT / "assets" / "data" / "haeundae-road-polygons-data.js"

BOUNDARY_GPKG = STAGING_DIR / "haeundae_boundary.gpkg"
CLIPPED_LINES_GPKG = STAGING_DIR / "haeundae_road_centerlines.gpkg"
PREPARED_LINES_GPKG = STAGING_DIR / "haeundae_road_centerlines_prepared.gpkg"
BUFFERED_GPKG = STAGING_DIR / "haeundae_road_polygons_5179.gpkg"
SIMPLIFIED_GPKG = STAGING_DIR / "haeundae_road_polygons_5179_simplified.gpkg"
WGS84_GPKG = STAGING_DIR / "haeundae_road_polygons_4326.gpkg"


ROAD_DIVISION_LABELS = {
    "RDD000": "미분류",
    "RDD001": "고속국도",
    "RDD002": "일반국도",
    "RDD003": "지방도",
    "RDD008": "면리간도로",
    "RDD009": "소로",
}

PAVEMENT_LABELS = {
    "RDQ000": "미분류",
    "RDQ005": "비포장",
    "RDQ006": "포장",
}


def init_qgis() -> QgsApplication:
    app = QgsApplication([], False)
    app.initQgis()
    Processing.initialize()
    return app


def unlink_if_exists(path: Path) -> None:
    if path.exists():
        path.unlink()


def layer_count(path: Path) -> int:
    layer = QgsVectorLayer(str(path), path.stem, "ogr")
    if not layer.isValid():
        raise RuntimeError(f"Invalid layer: {path}")
    return int(layer.featureCount())


def build_layers() -> None:
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    for path in [
        BOUNDARY_GPKG,
        CLIPPED_LINES_GPKG,
        PREPARED_LINES_GPKG,
        BUFFERED_GPKG,
        SIMPLIFIED_GPKG,
        WGS84_GPKG,
    ]:
        unlink_if_exists(path)

    processing.run(
        "native:extractbyexpression",
        {
            "INPUT": str(DISTRICT_BOUNDARIES),
            "EXPRESSION": "\"NAME\" = '해운대구'",
            "OUTPUT": str(BOUNDARY_GPKG),
        },
    )
    print(f"[boundary] {layer_count(BOUNDARY_GPKG):,}")

    processing.run(
        "native:clip",
        {
            "INPUT": str(ROAD_CENTERLINES),
            "OVERLAY": str(BOUNDARY_GPKG),
            "OUTPUT": str(CLIPPED_LINES_GPKG),
        },
    )
    print(f"[centerlines] {layer_count(CLIPPED_LINES_GPKG):,}")

    processing.run(
        "native:fieldcalculator",
        {
            "INPUT": str(CLIPPED_LINES_GPKG),
            "FIELD_NAME": "road_buf_m",
            "FIELD_TYPE": 0,
            "FIELD_LENGTH": 10,
            "FIELD_PRECISION": 2,
            "FORMULA": 'CASE WHEN "RVWD" IS NULL OR "RVWD" <= 0 THEN 1.5 ELSE "RVWD" / 2 END',
            "OUTPUT": str(PREPARED_LINES_GPKG),
        },
    )

    processing.run(
        "native:buffer",
        {
            "INPUT": str(PREPARED_LINES_GPKG),
            "DISTANCE": QgsProperty.fromField("road_buf_m"),
            "SEGMENTS": 1,
            "END_CAP_STYLE": 1,
            "JOIN_STYLE": 1,
            "MITER_LIMIT": 2,
            "DISSOLVE": False,
            "SEPARATE_DISJOINT": False,
            "OUTPUT": str(BUFFERED_GPKG),
        },
    )
    print(f"[polygons_5179] {layer_count(BUFFERED_GPKG):,}")

    processing.run(
        "native:simplifygeometries",
        {
            "INPUT": str(BUFFERED_GPKG),
            "METHOD": 0,
            "TOLERANCE": 0.75,
            "OUTPUT": str(SIMPLIFIED_GPKG),
        },
    )

    processing.run(
        "native:reprojectlayer",
        {
            "INPUT": str(SIMPLIFIED_GPKG),
            "TARGET_CRS": QgsCoordinateReferenceSystem("EPSG:4326"),
            "CONVERT_CURVED_GEOMETRIES": False,
            "OUTPUT": str(WGS84_GPKG),
        },
    )
    print(f"[polygons_4326] {layer_count(WGS84_GPKG):,}")


def value(feature, name: str) -> str:
    val = feature[name] if name in feature.fields().names() else ""
    return "" if val is None else str(val)


def export_js() -> None:
    layer = QgsVectorLayer(str(WGS84_GPKG), "haeundae_road_polygons_4326", "ogr")
    if not layer.isValid():
        raise RuntimeError(f"Invalid layer: {WGS84_GPKG}")

    features = []
    for index, feature in enumerate(layer.getFeatures(), start=1):
        geom = feature.geometry()
        if not geom or geom.isEmpty():
            continue

        bbox = geom.boundingBox()
        road_division = value(feature, "RDDV")
        pavement = value(feature, "PVQT")
        width = value(feature, "RVWD")
        lane_count = value(feature, "RDLN")
        road_buf_m = value(feature, "road_buf_m")

        features.append(
            {
                "type": "Feature",
                "bbox": [
                    round(bbox.xMinimum(), 7),
                    round(bbox.yMinimum(), 7),
                    round(bbox.xMaximum(), 7),
                    round(bbox.yMaximum(), 7),
                ],
                "geometry": json.loads(geom.asJson(7)),
                "properties": {
                    "sourceId": f"haeundae-road-polygon:{index}",
                    "districtGu": "해운대구",
                    "name": value(feature, "NAME"),
                    "roadName": value(feature, "RDNM"),
                    "roadDivision": road_division,
                    "roadDivisionLabel": ROAD_DIVISION_LABELS.get(road_division, road_division),
                    "pavementQuality": pavement,
                    "pavementQualityLabel": PAVEMENT_LABELS.get(pavement, pavement),
                    "laneCount": lane_count,
                    "widthMeter": width,
                    "bufferMeter": road_buf_m,
                    "scls": value(feature, "SCLS"),
                    "ufid": value(feature, "UFID"),
                },
            }
        )

    collection = {"type": "FeatureCollection", "features": features}
    ASSET_OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(collection, ensure_ascii=False, separators=(",", ":"))
    ASSET_OUT.write_text(f"window.HAEUNDAE_ROAD_POLYGONS_GEOJSON = {payload};\n", encoding="utf-8")
    print(f"[js] {len(features):,} features -> {ASSET_OUT} ({ASSET_OUT.stat().st_size:,} bytes)")


def main() -> int:
    app = init_qgis()
    try:
        build_layers()
        export_js()
    finally:
        app.exitQgis()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
