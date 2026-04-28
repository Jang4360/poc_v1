from __future__ import annotations

import json
import sys
from pathlib import Path


QGIS_PREFIX = r"C:\Program Files\QGIS 3.44.9\apps\qgis-ltr"
QGIS_PLUGIN_DIR = r"C:\Program Files\QGIS 3.44.9\apps\qgis-ltr\python\plugins"
sys.path.append(QGIS_PLUGIN_DIR)

from qgis.core import (
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeatureRequest,
    QgsGeometry,
    QgsProject,
    QgsSpatialIndex,
    QgsVectorLayer,
)


QgsApplication.setPrefixPath(QGIS_PREFIX, True)

POC_ROOT = Path(__file__).resolve().parents[1]
V5_ROOT = Path("C:/Users/SSAFY/Desktop/busan-sidewalk-slope-5m-red-v5")

DISTRICT_BOUNDARIES = V5_ROOT / "busan_district_boundaries.gpkg"
ROAD_POLYGONS_5179 = POC_ROOT / "data" / "staging" / "road_polygons" / "busan_road_polygons_5179_simplified.gpkg"
ASSET_DIR = POC_ROOT / "assets" / "data" / "road-polygons"
INDEX_OUT = POC_ROOT / "assets" / "data" / "road-polygons-index-data.js"


DISTRICT_SLUGS = {
    "강서구": "gangseo",
    "금정구": "geumjeong",
    "기장군": "gijang",
    "남구": "nam",
    "동구": "dong",
    "동래구": "dongnae",
    "부산진구": "busanjin",
    "북구": "buk",
    "사상구": "sasang",
    "사하구": "saha",
    "서구": "seo",
    "수영구": "suyeong",
    "연제구": "yeonje",
    "영도구": "yeongdo",
    "중구": "jung",
    "해운대구": "haeundae",
}

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
    return app


def value(feature, name: str) -> str:
    if name not in feature.fields().names():
        return ""
    val = feature[name]
    return "" if val is None else str(val)


def load_district_boundaries() -> dict[str, QgsGeometry]:
    layer = QgsVectorLayer(str(DISTRICT_BOUNDARIES), "busan_district_boundaries", "ogr")
    if not layer.isValid():
        raise RuntimeError(f"Invalid layer: {DISTRICT_BOUNDARIES}")

    by_district: dict[str, list[QgsGeometry]] = {}
    for feature in layer.getFeatures():
        district = value(feature, "NAME")
        if district in DISTRICT_SLUGS:
            by_district.setdefault(district, []).append(QgsGeometry(feature.geometry()))

    return {
        district: QgsGeometry.unaryUnion(geometries)
        for district, geometries in by_district.items()
    }


def road_properties(feature, district: str, index: int) -> dict:
    road_division = value(feature, "RDDV")
    pavement = value(feature, "PVQT")
    return {
        "sourceId": f"{DISTRICT_SLUGS[district]}-road-polygon:{index}",
        "districtGu": district,
        "name": value(feature, "NAME"),
        "roadName": value(feature, "RDNM"),
        "roadDivision": road_division,
        "roadDivisionLabel": ROAD_DIVISION_LABELS.get(road_division, road_division),
        "pavementQuality": pavement,
        "pavementQualityLabel": PAVEMENT_LABELS.get(pavement, pavement),
        "laneCount": value(feature, "RDLN"),
        "widthMeter": value(feature, "RVWD"),
        "bufferMeter": value(feature, "road_buf_m"),
        "scls": value(feature, "SCLS"),
        "ufid": value(feature, "UFID"),
    }


def export_district(
    district: str,
    boundary: QgsGeometry,
    road_layer: QgsVectorLayer,
    road_index: QgsSpatialIndex,
    transformer: QgsCoordinateTransform,
) -> tuple[str, int, int]:
    slug = DISTRICT_SLUGS[district]
    output_path = ASSET_DIR / f"road-polygons-{slug}-data.js"
    candidate_ids = road_index.intersects(boundary.boundingBox())
    request = QgsFeatureRequest().setFilterFids(candidate_ids)
    features = []
    clipped_count = 0

    for feature in road_layer.getFeatures(request):
        geom = feature.geometry()
        if not geom or geom.isEmpty() or not geom.intersects(boundary):
            continue

        clipped = geom.intersection(boundary)
        if not clipped or clipped.isEmpty():
            continue

        clipped_count += 1
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
                "properties": road_properties(feature, district, clipped_count),
            }
        )

    collection = {"type": "FeatureCollection", "features": features}
    payload = json.dumps(collection, ensure_ascii=False, separators=(",", ":"))
    output_path.write_text(
        "window.ROAD_POLYGONS_BY_DISTRICT = window.ROAD_POLYGONS_BY_DISTRICT || {};"
        f"window.ROAD_POLYGONS_BY_DISTRICT[{json.dumps(district, ensure_ascii=False)}] = {payload};\n",
        encoding="utf-8",
    )
    return f"assets/data/road-polygons/{output_path.name}", len(candidate_ids), len(features)


def main() -> int:
    if not ROAD_POLYGONS_5179.exists():
        raise FileNotFoundError(f"Run build_busan_road_polygons.py first: {ROAD_POLYGONS_5179}")

    ASSET_DIR.mkdir(parents=True, exist_ok=True)

    road_layer = QgsVectorLayer(str(ROAD_POLYGONS_5179), "busan_road_polygons_5179_simplified", "ogr")
    if not road_layer.isValid():
        raise RuntimeError(f"Invalid layer: {ROAD_POLYGONS_5179}")
    print(f"[roads] {int(road_layer.featureCount()):,}")
    road_index = QgsSpatialIndex(road_layer.getFeatures())

    boundaries = load_district_boundaries()
    transformer = QgsCoordinateTransform(
        QgsCoordinateReferenceSystem("EPSG:5179"),
        QgsCoordinateReferenceSystem("EPSG:4326"),
        QgsProject.instance(),
    )

    asset_map = {}
    counts = {}
    for district in sorted(DISTRICT_SLUGS, key=lambda value: value):
        asset_path, candidates, exported = export_district(
            district,
            boundaries[district],
            road_layer,
            road_index,
            transformer,
        )
        asset_map[district] = asset_path
        counts[district] = exported
        print(f"[{district}] candidates={candidates:,} exported={exported:,} -> {asset_path}")

    INDEX_OUT.write_text(
        "window.ROAD_POLYGON_DISTRICT_ASSETS = "
        + json.dumps(asset_map, ensure_ascii=False, separators=(",", ":"))
        + ";\n"
        + "window.ROAD_POLYGON_DISTRICT_COUNTS = "
        + json.dumps(counts, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )
    print(f"[index] {INDEX_OUT}")
    return 0


if __name__ == "__main__":
    app = init_qgis()
    try:
        raise SystemExit(main())
    finally:
        app.exitQgis()
