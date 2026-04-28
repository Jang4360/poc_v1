from __future__ import annotations

import csv
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
from processing.core.Processing import Processing
import processing


QgsApplication.setPrefixPath(QGIS_PREFIX, True)

POC_ROOT = Path(__file__).resolve().parents[1]
V5_ROOT = Path("C:/Users/SSAFY/Desktop/busan-sidewalk-slope-5m-red-v5")

ROAD_CENTERLINES = V5_ROOT / "busan_road_centerlines.gpkg"
ROAD_POLYGONS_5179 = POC_ROOT / "data" / "staging" / "road_polygons" / "busan_road_polygons_5179_simplified.gpkg"
SLOPE_RASTER = V5_ROOT / "busan_slope_pct_5m_smoothed.tif"
DISTRICT_BOUNDARIES = V5_ROOT / "busan_district_boundaries.gpkg"

STAGING_DIR = POC_ROOT / "data" / "staging" / "road_master"
MASTER_GPKG = STAGING_DIR / "busan_all_road_slope_surface_master.gpkg"
MASTER_CSV = STAGING_DIR / "busan_all_road_slope_surface_master.csv"
SUMMARY_JSON = STAGING_DIR / "busan_all_road_slope_surface_summary.json"

ASSET_DIR = POC_ROOT / "assets" / "data" / "road-slope-surface"
INDEX_OUT = POC_ROOT / "assets" / "data" / "road-slope-surface-index-data.js"


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

WIDTH_LEVELS = [
    (2, "VERY_NARROW", "2m 미만"),
    (4, "NARROW", "2~4m"),
    (8, "MEDIUM", "4~8m"),
    (10, "WIDE", "8~10m"),
    (float("inf"), "VERY_WIDE", "10m 초과"),
]

SLOPE_LEVELS = [
    (3, "VERY_GENTLE", "0~3%", "매우 완만"),
    (5, "GENTLE", "3~5%", "완만"),
    (8, "CAUTION", "5~8%", "주의"),
    (12, "SLOPED", "8~12%", "경사"),
    (20, "STEEP", "12~20%", "급경사"),
    (35, "VERY_STEEP", "20~35%", "매우 급경사"),
    (float("inf"), "DANGEROUS", "35%+", "위험"),
]

SUMMARY_KEYS = {
    "surface": ["포장", "비포장", "미분류"],
    "slope": [level[1] for level in SLOPE_LEVELS] + ["UNKNOWN"],
    "width": [level[1] for level in WIDTH_LEVELS] + ["UNKNOWN"],
}


def init_qgis() -> QgsApplication:
    app = QgsApplication([], False)
    app.initQgis()
    Processing.initialize()
    return app


def unlink_if_exists(path: Path) -> None:
    if path.exists():
        path.unlink()


def value(feature, name: str):
    if name not in feature.fields().names():
        return None
    val = feature[name]
    return None if val is None else val


def text_value(feature, name: str) -> str:
    val = value(feature, name)
    return "" if val is None else str(val)


def float_value(feature, name: str) -> float | None:
    val = value(feature, name)
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def round_or_none(value_: float | None, digits: int = 2) -> float | None:
    if value_ is None:
        return None
    return round(float(value_), digits)


def classify_width(width: float | None) -> tuple[str, str]:
    if width is None:
        return "UNKNOWN", "미분류"
    for upper, code, label in WIDTH_LEVELS:
        if width < upper:
            return code, label
    return "UNKNOWN", "미분류"


def classify_slope(slope: float | None) -> tuple[str, str, str]:
    if slope is None:
        return "UNKNOWN", "미산출", "경사 미산출"
    for upper, code, range_label, label in SLOPE_LEVELS:
        if slope < upper:
            return code, range_label, label
    return "UNKNOWN", "미산출", "경사 미산출"


def risk_level(slope: float | None, width: float | None, pavement: str) -> str:
    score = 0
    if slope is not None:
        if slope >= 20:
            score += 4
        elif slope >= 12:
            score += 3
        elif slope >= 8:
            score += 2
        elif slope >= 5:
            score += 1
    if width is not None:
        if width < 2:
            score += 2
        elif width < 4:
            score += 1
    if pavement == "RDQ005":
        score += 2
    elif pavement == "RDQ000":
        score += 1

    if score >= 6:
        return "VERY_HIGH"
    if score >= 4:
        return "HIGH"
    if score >= 2:
        return "MEDIUM"
    return "LOW"


def load_district_boundaries() -> tuple[dict[str, QgsGeometry], QgsSpatialIndex, QgsVectorLayer]:
    layer = QgsVectorLayer(str(DISTRICT_BOUNDARIES), "busan_district_boundaries", "ogr")
    if not layer.isValid():
        raise RuntimeError(f"Invalid layer: {DISTRICT_BOUNDARIES}")

    grouped: dict[str, list[QgsGeometry]] = {}
    for feature in layer.getFeatures():
        district = text_value(feature, "NAME")
        if district in DISTRICT_SLUGS:
            grouped.setdefault(district, []).append(QgsGeometry(feature.geometry()))

    boundaries = {
        district: QgsGeometry.unaryUnion(geometries)
        for district, geometries in grouped.items()
    }
    return boundaries, QgsSpatialIndex(layer.getFeatures()), layer


def district_for_feature(feature, boundaries: dict[str, QgsGeometry]) -> str:
    geom = feature.geometry()
    if not geom or geom.isEmpty():
        return ""
    point = geom.pointOnSurface()
    for district, boundary in boundaries.items():
        if boundary.contains(point) or boundary.intersects(point):
            return district
    for district, boundary in boundaries.items():
        if geom.intersects(boundary):
            return district
    return ""


def run_zonal_stats() -> None:
    if not ROAD_POLYGONS_5179.exists():
        raise FileNotFoundError(f"Missing road polygons. Run build_busan_road_polygons.py first: {ROAD_POLYGONS_5179}")
    if not SLOPE_RASTER.exists():
        raise FileNotFoundError(f"Missing slope raster: {SLOPE_RASTER}")

    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    unlink_if_exists(MASTER_GPKG)

    print(f"[zonal] input polygons: {ROAD_POLYGONS_5179}", flush=True)
    print(f"[zonal] raster: {SLOPE_RASTER}", flush=True)
    processing.run(
        "native:zonalstatisticsfb",
        {
            "INPUT": str(ROAD_POLYGONS_5179),
            "INPUT_RASTER": str(SLOPE_RASTER),
            "RASTER_BAND": 1,
            "COLUMN_PREFIX": "slope_",
            "STATISTICS": [0, 2, 5, 6],
            "OUTPUT": str(MASTER_GPKG),
        },
    )
    print(f"[zonal] output: {MASTER_GPKG}", flush=True)


def base_properties(feature, district: str, source_id: str) -> dict:
    road_division = text_value(feature, "RDDV")
    pavement = text_value(feature, "PVQT")
    lane_count = float_value(feature, "RDLN")
    width = float_value(feature, "RVWD")
    buffer_meter = float_value(feature, "road_buf_m")
    slope_count = float_value(feature, "slope_count")
    slope_mean = float_value(feature, "slope_mean")
    slope_min = float_value(feature, "slope_min")
    slope_max = float_value(feature, "slope_max")
    width_level, width_level_label = classify_width(width)
    slope_level, slope_range, slope_label = classify_slope(slope_mean)
    surface_label = PAVEMENT_LABELS.get(pavement, pavement or "미분류")
    road_division_label = ROAD_DIVISION_LABELS.get(road_division, road_division or "미분류")
    risk = risk_level(slope_mean, width, pavement)
    is_seed_candidate = (
        road_division in {"RDD000", "RDD009"}
        and text_value(feature, "DVYN") == "CSU002"
        and lane_count is not None
        and lane_count <= 2
        and width is not None
        and width <= 10
        and pavement in {"RDQ005", "RDQ006"}
    )

    name = text_value(feature, "NAME")
    road_name = text_value(feature, "RDNM")
    return {
        "sourceId": source_id,
        "districtGu": district,
        "name": name,
        "roadName": road_name,
        "roadDivision": road_division,
        "roadDivisionLabel": road_division_label,
        "pavementQuality": pavement,
        "pavementQualityLabel": surface_label,
        "surfaceType": "PAVED" if pavement == "RDQ006" else "UNPAVED" if pavement == "RDQ005" else "UNKNOWN",
        "laneCount": int(lane_count) if lane_count is not None and lane_count.is_integer() else lane_count,
        "widthMeter": round_or_none(width, 2),
        "widthLevel": width_level,
        "widthLevelLabel": width_level_label,
        "bufferMeter": round_or_none(buffer_meter, 2),
        "slopeCellCount": int(slope_count) if slope_count is not None else 0,
        "slopeMean": round_or_none(slope_mean, 2),
        "slopeMin": round_or_none(slope_min, 2),
        "slopeMax": round_or_none(slope_max, 2),
        "slopeLevel": slope_level,
        "slopeRange": slope_range,
        "slopeLevelLabel": slope_label,
        "riskLevel": risk,
        "isPaved": pavement == "RDQ006",
        "isUnpaved": pavement == "RDQ005",
        "isHighSlope": slope_mean is not None and slope_mean >= 8,
        "isVeryHighSlope": slope_mean is not None and slope_mean >= 12,
        "isNarrowRoadCandidate": width is not None and width <= 4,
        "isWalkableSeedCandidate": is_seed_candidate,
        "scls": text_value(feature, "SCLS"),
        "ufid": text_value(feature, "UFID"),
    }


def update_summary(summary: dict, district: str, props: dict) -> None:
    summary["total"] += 1
    summary["byDistrict"][district] = summary["byDistrict"].get(district, 0) + 1
    summary["bySurface"][props["pavementQualityLabel"]] = summary["bySurface"].get(props["pavementQualityLabel"], 0) + 1
    summary["bySlope"][props["slopeLevel"]] = summary["bySlope"].get(props["slopeLevel"], 0) + 1
    summary["byWidth"][props["widthLevel"]] = summary["byWidth"].get(props["widthLevel"], 0) + 1
    summary["byRisk"][props["riskLevel"]] = summary["byRisk"].get(props["riskLevel"], 0) + 1
    if props["isWalkableSeedCandidate"]:
        summary["walkableSeedCandidates"] += 1


def export_master_csv(master_layer: QgsVectorLayer, boundaries: dict[str, QgsGeometry]) -> dict:
    fieldnames = [
        "sourceId",
        "districtGu",
        "ufid",
        "name",
        "roadName",
        "roadDivision",
        "roadDivisionLabel",
        "pavementQuality",
        "pavementQualityLabel",
        "surfaceType",
        "laneCount",
        "widthMeter",
        "widthLevel",
        "widthLevelLabel",
        "bufferMeter",
        "slopeCellCount",
        "slopeMean",
        "slopeMin",
        "slopeMax",
        "slopeLevel",
        "slopeRange",
        "slopeLevelLabel",
        "riskLevel",
        "isPaved",
        "isUnpaved",
        "isHighSlope",
        "isVeryHighSlope",
        "isNarrowRoadCandidate",
        "isWalkableSeedCandidate",
        "scls",
    ]
    summary = {
        "total": 0,
        "walkableSeedCandidates": 0,
        "byDistrict": {},
        "bySurface": {},
        "bySlope": {},
        "byWidth": {},
        "byRisk": {},
    }

    with MASTER_CSV.open("w", encoding="utf-8-sig", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for feature in master_layer.getFeatures():
            fid = int(value(feature, "fid") or feature.id())
            district = district_for_feature(feature, boundaries) or "미분류"
            props = base_properties(feature, district, f"all-road-slope:{fid}")
            writer.writerow({key: props.get(key, "") for key in fieldnames})
            update_summary(summary, district, props)
            if summary["total"] % 25000 == 0:
                print(f"[csv] {summary['total']:,}", flush=True)

    return summary


def export_district_asset(
    district: str,
    boundary: QgsGeometry,
    road_layer: QgsVectorLayer,
    master_lookup: dict[int, dict],
    road_index: QgsSpatialIndex,
    transformer: QgsCoordinateTransform,
) -> tuple[str, int, int]:
    slug = DISTRICT_SLUGS[district]
    output_path = ASSET_DIR / f"road-slope-surface-{slug}-data.js"
    candidate_ids = road_index.intersects(boundary.boundingBox())
    request = QgsFeatureRequest().setFilterFids(candidate_ids)
    features = []
    exported_count = 0

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
            props = base_properties(feature, district, f"{slug}-road-slope:{fid}")
        props["sourceId"] = f"{slug}-road-slope:{fid}"
        props["districtGu"] = district

        clipped_4326 = QgsGeometry(clipped)
        clipped_4326.transform(transformer)
        bbox = clipped_4326.boundingBox()
        exported_count += 1
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
        f"window.ROAD_SLOPE_SURFACE_BY_DISTRICT[{json.dumps(district, ensure_ascii=False)}] = {payload};\n",
        encoding="utf-8",
    )
    return f"assets/data/road-slope-surface/{output_path.name}", len(candidate_ids), len(features)


def export_district_assets(master_layer: QgsVectorLayer, boundaries: dict[str, QgsGeometry]) -> dict:
    road_layer = QgsVectorLayer(str(ROAD_CENTERLINES), "busan_road_centerlines", "ogr")
    if not road_layer.isValid():
        raise RuntimeError(f"Invalid layer: {ROAD_CENTERLINES}")

    master_lookup: dict[int, dict] = {}
    for feature in master_layer.getFeatures():
        fid = int(value(feature, "fid") or feature.id())
        district = district_for_feature(feature, boundaries) or ""
        master_lookup[fid] = base_properties(feature, district, f"all-road-slope:{fid}")
        if len(master_lookup) % 50000 == 0:
            print(f"[lookup] {len(master_lookup):,}", flush=True)

    road_index = QgsSpatialIndex(road_layer.getFeatures())
    transformer = QgsCoordinateTransform(
        QgsCoordinateReferenceSystem("EPSG:5179"),
        QgsCoordinateReferenceSystem("EPSG:4326"),
        QgsProject.instance(),
    )

    asset_map = {}
    counts = {}
    for district in sorted(DISTRICT_SLUGS, key=lambda value_: value_):
        asset_path, candidates, exported = export_district_asset(
            district,
            boundaries[district],
            road_layer,
            master_lookup,
            road_index,
            transformer,
        )
        asset_map[district] = asset_path
        counts[district] = exported
        print(f"[asset:{district}] candidates={candidates:,} exported={exported:,} -> {asset_path}", flush=True)

    INDEX_OUT.write_text(
        "window.ROAD_SLOPE_SURFACE_DISTRICT_ASSETS = "
        + json.dumps(asset_map, ensure_ascii=False, separators=(",", ":"))
        + ";\n"
        + "window.ROAD_SLOPE_SURFACE_DISTRICT_COUNTS = "
        + json.dumps(counts, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )
    return {"assets": asset_map, "counts": counts}


def main() -> int:
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    ASSET_DIR.mkdir(parents=True, exist_ok=True)

    run_zonal_stats()

    master_layer = QgsVectorLayer(str(MASTER_GPKG), "busan_all_road_slope_surface_master", "ogr")
    if not master_layer.isValid():
        raise RuntimeError(f"Invalid layer: {MASTER_GPKG}")
    print(f"[master] {int(master_layer.featureCount()):,}", flush=True)

    boundaries, _, _ = load_district_boundaries()
    summary = export_master_csv(master_layer, boundaries)
    district_asset_summary = export_district_assets(master_layer, boundaries)
    summary["districtAssetCounts"] = district_asset_summary["counts"]
    summary["source"] = {
        "roadCenterlines": str(ROAD_CENTERLINES),
        "roadPolygons": str(ROAD_POLYGONS_5179),
        "slopeRaster": str(SLOPE_RASTER),
        "districtBoundaries": str(DISTRICT_BOUNDARIES),
    }
    SUMMARY_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[csv] {MASTER_CSV}", flush=True)
    print(f"[summary] {SUMMARY_JSON}", flush=True)
    print(f"[index] {INDEX_OUT}", flush=True)
    return 0


if __name__ == "__main__":
    app = init_qgis()
    try:
        raise SystemExit(main())
    finally:
        app.exitQgis()
