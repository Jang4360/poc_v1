from __future__ import annotations

import csv
import json
import math
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
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsSpatialIndex,
    QgsVectorLayer,
)


QgsApplication.setPrefixPath(QGIS_PREFIX, True)

POC_ROOT = Path(__file__).resolve().parents[1]
ADOPTED_DIR = POC_ROOT / "data" / "adopted"
ASSETS_DIR = POC_ROOT / "assets" / "data"
STAGING_DIR = POC_ROOT / "data" / "staging" / "road_polygons"
OUTPUT_DIR = POC_ROOT / "data" / "reports" / "stair_review"

STAIRS_CSV = ADOPTED_DIR / "stg_stairs_ready.csv"
ROAD_POLYGONS_GPKG = STAGING_DIR / "busan_road_polygons_5179_simplified.gpkg"
CROSSWALKS_JS = ASSETS_DIR / "crosswalks-data.js"
FACILITIES_JS = ASSETS_DIR / "facilities-data.js"

CSV_OUT = OUTPUT_DIR / "busan_stair_review_candidates.csv"
GEOJSON_OUT = OUTPUT_DIR / "busan_stair_review_candidates.geojson"
SUMMARY_OUT = OUTPUT_DIR / "busan_stair_review_summary.json"
ASSET_JS_OUT = ASSETS_DIR / "busan-stair-review-candidates-data.js"

OUTPUT_FIELDS = [
    "sourceId",
    "districtGu",
    "name",
    "lat",
    "lng",
    "widthMeter",
    "areaSquareMeter",
    "ufid",
    "nearestRoadDistanceM",
    "nearestRoadSourceId",
    "nearestRoadName",
    "nearestRoadWidthMeter",
    "nearestRoadPavement",
    "nearestCrosswalkDistanceM",
    "nearestCrosswalkSourceId",
    "nearestCrosswalkLabel",
    "nearCrosswalk30m",
    "nearestFacilityDistanceM",
    "nearestFacilitySourceId",
    "nearestFacilityName",
    "nearestFacilityCategory",
    "nearFacility50m",
    "duplicateClusterId",
    "duplicateClusterSize",
    "priority",
    "priorityScore",
    "reviewStatus",
    "reviewReason",
]


def init_qgis() -> QgsApplication:
    app = QgsApplication([], False)
    app.initQgis()
    return app


def load_js_geojson(path: Path, assignment_name: str) -> dict:
    text = path.read_text(encoding="utf-8")
    prefix = f"window.{assignment_name} = "
    if not text.startswith(prefix):
        raise ValueError(f"Unexpected JS assignment in {path}")
    return json.loads(text[len(prefix) :].rstrip(";\n "))


def parse_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def value(feature, name: str) -> str:
    if name not in feature.fields().names():
        return ""
    val = feature[name]
    return "" if val is None else str(val)


def transform_point(transformer: QgsCoordinateTransform, lng: float, lat: float) -> QgsPointXY:
    return transformer.transform(QgsPointXY(lng, lat))


def distance(a: QgsPointXY, b: QgsPointXY) -> float:
    return math.hypot(a.x() - b.x(), a.y() - b.y())


def build_point_features(data: dict, transformer: QgsCoordinateTransform) -> list[dict]:
    features = []
    for feature in data["features"]:
        lng, lat = feature["geometry"]["coordinates"]
        point = transform_point(transformer, float(lng), float(lat))
        features.append(
            {
                "point": point,
                "properties": feature["properties"],
            }
        )
    return features


def nearest_point(point: QgsPointXY, features: list[dict]) -> tuple[float, dict | None]:
    best_distance = math.inf
    best_feature = None
    for feature in features:
        current = distance(point, feature["point"])
        if current < best_distance:
            best_distance = current
            best_feature = feature
    return best_distance, best_feature


def expanded_rect(point: QgsPointXY, radius_m: float) -> QgsRectangle:
    return QgsRectangle(
        point.x() - radius_m,
        point.y() - radius_m,
        point.x() + radius_m,
        point.y() + radius_m,
    )


def nearest_road(
    point: QgsPointXY,
    point_geom: QgsGeometry,
    road_layer: QgsVectorLayer,
    road_index: QgsSpatialIndex,
) -> tuple[float, object | None]:
    candidate_ids: set[int] = set()
    for radius in [5, 20, 50, 100, 250, 500, 1000]:
        candidate_ids.update(road_index.intersects(expanded_rect(point, radius)))
        if candidate_ids:
            break

    if not candidate_ids:
        candidate_ids.update(road_index.nearestNeighbor(point, 50))

    best_distance = math.inf
    best_feature = None
    for feature_id in candidate_ids:
        feature = next(road_layer.getFeatures(QgsFeatureRequest(feature_id)), None)
        if feature is None:
            continue
        geom = feature.geometry()
        if not geom or geom.isEmpty():
            continue
        current = geom.distance(point_geom)
        if current < best_distance:
            best_distance = current
            best_feature = feature

    return best_distance, best_feature


def cluster_stairs(rows: list[dict], threshold_m: float = 15.0) -> None:
    parent = list(range(len(rows)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left = find(left)
        root_right = find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    by_district: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        by_district.setdefault(row["districtGu"], []).append(index)

    for indexes in by_district.values():
        for left_pos, left in enumerate(indexes):
            for right in indexes[left_pos + 1 :]:
                if distance(rows[left]["_point"], rows[right]["_point"]) <= threshold_m:
                    union(left, right)

    clusters: dict[int, list[int]] = {}
    for index in range(len(rows)):
        clusters.setdefault(find(index), []).append(index)

    next_id = 1
    for members in clusters.values():
        district = rows[members[0]]["districtGu"]
        cluster_id = f"STC-{next_id:04d}"
        next_id += 1
        for index in members:
            rows[index]["duplicateClusterId"] = cluster_id
            rows[index]["duplicateClusterSize"] = str(len(members))
            rows[index]["duplicateClusterDistrict"] = district


def classify(row: dict) -> tuple[str, int, str, str]:
    road_distance = float(row["nearestRoadDistanceM"])
    crosswalk_distance = float(row["nearestCrosswalkDistanceM"])
    facility_distance = float(row["nearestFacilityDistanceM"])
    width = parse_float(row.get("widthMeter")) or 0.0
    area = parse_float(row.get("areaSquareMeter")) or 0.0

    score = 0
    reasons = []
    if road_distance == 0:
        score += 60
        reasons.append("도로 polygon과 겹침")
    elif road_distance <= 5:
        score += 50
        reasons.append("도로 polygon 5m 이내")
    elif road_distance <= 20:
        score += 25
        reasons.append("도로 polygon 20m 이내")
    else:
        reasons.append("도로 polygon 20m 초과")

    if crosswalk_distance <= 30:
        score += 20
        reasons.append("횡단보도 30m 이내")
    if facility_distance <= 50:
        score += 15
        reasons.append("편의시설 50m 이내")
    if width >= 3 or area >= 50:
        score += 5
        reasons.append("폭/면적 기준 큼")

    if road_distance <= 5:
        priority = "P1"
        status = "CANDIDATE"
    elif road_distance <= 20 and (crosswalk_distance <= 30 or facility_distance <= 50):
        priority = "P2"
        status = "CANDIDATE"
    elif road_distance <= 20:
        priority = "P3"
        status = "LOW_PRIORITY"
    else:
        priority = "P4"
        status = "LOW_PRIORITY"

    if int(row["duplicateClusterSize"]) > 1:
        reasons.append("15m 이내 계단 클러스터")

    return priority, score, ", ".join(reasons), status


def round_meter(value: float) -> str:
    return f"{value:.1f}"


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    if not ROAD_POLYGONS_GPKG.exists():
        raise FileNotFoundError(f"Run build_busan_road_polygons.py first: {ROAD_POLYGONS_GPKG}")

    src_crs = QgsCoordinateReferenceSystem("EPSG:4326")
    dst_crs = QgsCoordinateReferenceSystem("EPSG:5179")
    transformer = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())

    road_layer = QgsVectorLayer(str(ROAD_POLYGONS_GPKG), "busan_road_polygons_5179_simplified", "ogr")
    if not road_layer.isValid():
        raise RuntimeError(f"Invalid layer: {ROAD_POLYGONS_GPKG}")
    print(f"[roads] {int(road_layer.featureCount()):,}")
    road_index = QgsSpatialIndex(road_layer.getFeatures())

    with STAIRS_CSV.open("r", encoding="utf-8-sig", newline="") as file:
        stairs = list(csv.DictReader(file))
    print(f"[stairs] {len(stairs):,}")

    crosswalk_data = load_js_geojson(CROSSWALKS_JS, "CROSSWALKS_GEOJSON")
    facility_data = load_js_geojson(FACILITIES_JS, "FACILITIES_GEOJSON")
    crosswalks = build_point_features(crosswalk_data, transformer)
    facilities = build_point_features(facility_data, transformer)
    print(f"[crosswalks] {len(crosswalks):,}")
    print(f"[facilities] {len(facilities):,}")

    rows = []
    for index, stair in enumerate(stairs, start=1):
        lat = float(stair["lat"])
        lng = float(stair["lng"])
        point = transform_point(transformer, lng, lat)
        point_geom = QgsGeometry.fromPointXY(point)

        road_distance, road = nearest_road(point, point_geom, road_layer, road_index)
        crosswalk_distance, crosswalk = nearest_point(point, crosswalks)
        facility_distance, facility = nearest_point(point, facilities)

        road_props = road if road else None
        crosswalk_props = crosswalk["properties"] if crosswalk else {}
        facility_props = facility["properties"] if facility else {}

        road_name = ""
        if road_props:
            raw_name = value(road_props, "NAME")
            raw_road_name = value(road_props, "RDNM")
            road_name = "" if raw_name == "NULL" else raw_name
            if not road_name:
                road_name = "" if raw_road_name == "NULL" else raw_road_name

        row = {
            "sourceId": stair["sourceId"],
            "districtGu": stair["districtGu"],
            "name": stair["name"],
            "lat": stair["lat"],
            "lng": stair["lng"],
            "widthMeter": stair["widthMeter"],
            "areaSquareMeter": stair["areaSquareMeter"],
            "ufid": stair["ufid"],
            "nearestRoadDistanceM": round_meter(road_distance),
            "nearestRoadSourceId": "" if not road_props else f"busan-road-polygon:{road_props.id()}",
            "nearestRoadName": road_name,
            "nearestRoadWidthMeter": "" if not road_props else value(road_props, "RVWD"),
            "nearestRoadPavement": "" if not road_props else value(road_props, "PVQT"),
            "nearestCrosswalkDistanceM": round_meter(crosswalk_distance),
            "nearestCrosswalkSourceId": crosswalk_props.get("sourceId", ""),
            "nearestCrosswalkLabel": crosswalk_props.get("locationLabel", ""),
            "nearCrosswalk30m": str(crosswalk_distance <= 30).lower(),
            "nearestFacilityDistanceM": round_meter(facility_distance),
            "nearestFacilitySourceId": facility_props.get("sourceId", ""),
            "nearestFacilityName": facility_props.get("name", ""),
            "nearestFacilityCategory": facility_props.get("facilityCategory", ""),
            "nearFacility50m": str(facility_distance <= 50).lower(),
            "_point": point,
        }
        rows.append(row)

        if index % 500 == 0:
            print(f"[progress] {index:,}/{len(stairs):,}")

    cluster_stairs(rows)

    for row in rows:
        priority, score, reason, status = classify(row)
        row["priority"] = priority
        row["priorityScore"] = str(score)
        row["reviewStatus"] = status
        row["reviewReason"] = reason

    rows.sort(
        key=lambda row: (
            row["districtGu"],
            row["priority"],
            -int(row["priorityScore"]),
            float(row["nearestRoadDistanceM"]),
            row["sourceId"],
        )
    )

    with CSV_OUT.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in OUTPUT_FIELDS})

    geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [float(row["lng"]), float(row["lat"])],
                },
                "properties": {field: row.get(field, "") for field in OUTPUT_FIELDS if field not in {"lat", "lng"}},
            }
            for row in rows
        ],
    }
    GEOJSON_OUT.write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")
    ASSET_JS_OUT.write_text(
        "window.BUSAN_STAIR_REVIEW_GEOJSON = "
        + json.dumps(geojson, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )

    summary: dict[str, object] = {
        "scope": "부산 전체",
        "stairs": len(rows),
        "roads": int(road_layer.featureCount()),
        "crosswalks": len(crosswalks),
        "facilities": len(facilities),
        "priorityCounts": {},
        "reviewStatusCounts": {},
        "districtPriorityCounts": {},
        "roadDistanceBuckets": {
            "overlap": 0,
            "within5m": 0,
            "within20m": 0,
            "over20m": 0,
        },
    }
    for row in rows:
        priority = row["priority"]
        district = row["districtGu"]
        status = row["reviewStatus"]
        summary["priorityCounts"][priority] = summary["priorityCounts"].get(priority, 0) + 1
        summary["reviewStatusCounts"][status] = summary["reviewStatusCounts"].get(status, 0) + 1
        summary["districtPriorityCounts"].setdefault(district, {})
        summary["districtPriorityCounts"][district][priority] = summary["districtPriorityCounts"][district].get(priority, 0) + 1
        road_distance = float(row["nearestRoadDistanceM"])
        if road_distance == 0:
            summary["roadDistanceBuckets"]["overlap"] += 1
        elif road_distance <= 5:
            summary["roadDistanceBuckets"]["within5m"] += 1
        elif road_distance <= 20:
            summary["roadDistanceBuckets"]["within20m"] += 1
        else:
            summary["roadDistanceBuckets"]["over20m"] += 1

    SUMMARY_OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[csv] {CSV_OUT}")
    print(f"[geojson] {GEOJSON_OUT}")
    print(f"[asset js] {ASSET_JS_OUT}")
    print(f"[summary] {SUMMARY_OUT}")
    print(json.dumps(summary["priorityCounts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    app = init_qgis()
    try:
        raise SystemExit(main())
    finally:
        app.exitQgis()
