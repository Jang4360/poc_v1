from __future__ import annotations

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

ROAD_CENTERLINES = V5_ROOT / "busan_road_centerlines.gpkg"

STAGING_DIR = POC_ROOT / "data" / "staging" / "road_polygons"
PREPARED_LINES_GPKG = STAGING_DIR / "busan_road_centerlines_prepared.gpkg"
BUFFERED_GPKG = STAGING_DIR / "busan_road_polygons_5179.gpkg"
SIMPLIFIED_GPKG = STAGING_DIR / "busan_road_polygons_5179_simplified.gpkg"
WGS84_GPKG = STAGING_DIR / "busan_road_polygons_4326.gpkg"


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
        PREPARED_LINES_GPKG,
        BUFFERED_GPKG,
        SIMPLIFIED_GPKG,
        WGS84_GPKG,
    ]:
        unlink_if_exists(path)

    source_layer = QgsVectorLayer(str(ROAD_CENTERLINES), "busan_road_centerlines", "ogr")
    if not source_layer.isValid():
        raise RuntimeError(f"Invalid layer: {ROAD_CENTERLINES}")
    print(f"[centerlines] {int(source_layer.featureCount()):,}")

    processing.run(
        "native:fieldcalculator",
        {
            "INPUT": str(ROAD_CENTERLINES),
            "FIELD_NAME": "road_buf_m",
            "FIELD_TYPE": 0,
            "FIELD_LENGTH": 10,
            "FIELD_PRECISION": 2,
            "FORMULA": 'CASE WHEN "RVWD" IS NULL OR "RVWD" <= 0 THEN 1.5 ELSE "RVWD" / 2 END',
            "OUTPUT": str(PREPARED_LINES_GPKG),
        },
    )
    print(f"[prepared] {layer_count(PREPARED_LINES_GPKG):,}")

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
    print(f"[polygons_5179_simplified] {layer_count(SIMPLIFIED_GPKG):,}")

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
    print(f"[out] {SIMPLIFIED_GPKG}")
    print(f"[out] {WGS84_GPKG}")


def main() -> int:
    app = init_qgis()
    try:
        build_layers()
    finally:
        app.exitQgis()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
