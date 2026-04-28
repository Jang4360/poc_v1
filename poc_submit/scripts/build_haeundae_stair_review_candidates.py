import csv
import json
import math
from pathlib import Path


POC_ROOT = Path(__file__).resolve().parents[1]
ADOPTED_DIR = POC_ROOT / "data" / "adopted"
ASSETS_DIR = POC_ROOT / "assets" / "data"
OUTPUT_DIR = POC_ROOT / "data" / "reports" / "stair_review"

STAIRS_CSV = ADOPTED_DIR / "stg_stairs_ready.csv"
ROAD_POLYGONS_JS = ASSETS_DIR / "haeundae-road-polygons-data.js"
CROSSWALKS_JS = ASSETS_DIR / "crosswalks-data.js"
FACILITIES_JS = ASSETS_DIR / "facilities-data.js"

CSV_OUT = OUTPUT_DIR / "haeundae_stair_review_candidates.csv"
GEOJSON_OUT = OUTPUT_DIR / "haeundae_stair_review_candidates.geojson"
SUMMARY_OUT = OUTPUT_DIR / "haeundae_stair_review_summary.json"
ASSET_JS_OUT = ASSETS_DIR / "haeundae-stair-review-candidates-data.js"

DISTRICT = "해운대구"
LAT0 = math.radians(35.18)
LON0 = math.radians(129.16)
EARTH_RADIUS_M = 6_371_008.8

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


def project(lng: float, lat: float) -> tuple[float, float]:
    x = (math.radians(lng) - LON0) * EARTH_RADIUS_M * math.cos(LAT0)
    y = (math.radians(lat) - LAT0) * EARTH_RADIUS_M
    return x, y


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def point_segment_distance(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    px, py = point
    ax, ay = start
    bx, by = end
    dx = bx - ax
    dy = by - ay
    denom = dx * dx + dy * dy
    if denom == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / denom))
    closest = (ax + t * dx, ay + t * dy)
    return distance(point, closest)


def point_in_ring(point: tuple[float, float], ring: list[tuple[float, float]]) -> bool:
    px, py = point
    inside = False
    if len(ring) < 3:
        return False
    prev_x, prev_y = ring[-1]
    for curr_x, curr_y in ring:
        if ((curr_y > py) != (prev_y > py)) and (
            px < (prev_x - curr_x) * (py - curr_y) / ((prev_y - curr_y) or 1e-12) + curr_x
        ):
            inside = not inside
        prev_x, prev_y = curr_x, curr_y
    return inside


def point_in_polygon(point: tuple[float, float], polygon: list[list[tuple[float, float]]]) -> bool:
    if not polygon or not point_in_ring(point, polygon[0]):
        return False
    return not any(point_in_ring(point, hole) for hole in polygon[1:])


def polygon_distance(point: tuple[float, float], polygon: list[list[tuple[float, float]]]) -> float:
    if point_in_polygon(point, polygon):
        return 0.0
    best = math.inf
    for ring in polygon:
        for idx, start in enumerate(ring):
            end = ring[(idx + 1) % len(ring)]
            best = min(best, point_segment_distance(point, start, end))
    return best


def bbox_gap(point: tuple[float, float], bbox: tuple[float, float, float, float]) -> float:
    x, y = point
    min_x, min_y, max_x, max_y = bbox
    dx = max(min_x - x, 0.0, x - max_x)
    dy = max(min_y - y, 0.0, y - max_y)
    return math.hypot(dx, dy)


def project_road_feature(feature: dict) -> dict:
    polygons = []
    xs = []
    ys = []
    coordinates = feature["geometry"]["coordinates"]
    for polygon in coordinates:
        projected_polygon = []
        for ring in polygon:
            projected_ring = [project(lng, lat) for lng, lat in ring]
            projected_polygon.append(projected_ring)
            xs.extend(point[0] for point in projected_ring)
            ys.extend(point[1] for point in projected_ring)
        polygons.append(projected_polygon)
    return {
        "properties": feature["properties"],
        "polygons": polygons,
        "bbox": (min(xs), min(ys), max(xs), max(ys)),
    }


def nearest_road(point: tuple[float, float], road_infos: list[dict]) -> tuple[float, dict | None]:
    best_distance = math.inf
    best_road = None
    for road in road_infos:
        if bbox_gap(point, road["bbox"]) > best_distance:
            continue
        for polygon in road["polygons"]:
            current = polygon_distance(point, polygon)
            if current < best_distance:
                best_distance = current
                best_road = road
                if best_distance == 0:
                    return best_distance, best_road
    return best_distance, best_road


def nearest_point(point: tuple[float, float], features: list[dict]) -> tuple[float, dict | None]:
    best_distance = math.inf
    best_feature = None
    for feature in features:
        lng, lat = feature["geometry"]["coordinates"]
        current = distance(point, project(lng, lat))
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

    for left in range(len(rows)):
        for right in range(left + 1, len(rows)):
            if distance(rows[left]["_point"], rows[right]["_point"]) <= threshold_m:
                union(left, right)

    clusters: dict[int, list[int]] = {}
    for index in range(len(rows)):
        clusters.setdefault(find(index), []).append(index)

    next_id = 1
    for members in clusters.values():
        cluster_id = f"HSTC-{next_id:03d}"
        next_id += 1
        for index in members:
            rows[index]["duplicateClusterId"] = cluster_id
            rows[index]["duplicateClusterSize"] = str(len(members))


def classify(row: dict) -> tuple[str, int, str]:
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


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with STAIRS_CSV.open("r", encoding="utf-8-sig", newline="") as file:
        stairs = [row for row in csv.DictReader(file) if row["districtGu"] == DISTRICT]

    road_data = load_js_geojson(ROAD_POLYGONS_JS, "HAEUNDAE_ROAD_POLYGONS_GEOJSON")
    crosswalk_data = load_js_geojson(CROSSWALKS_JS, "CROSSWALKS_GEOJSON")
    facility_data = load_js_geojson(FACILITIES_JS, "FACILITIES_GEOJSON")

    road_infos = [
        project_road_feature(feature)
        for feature in road_data["features"]
        if feature["properties"].get("districtGu") == DISTRICT
    ]
    crosswalks = [
        feature
        for feature in crosswalk_data["features"]
        if feature["properties"].get("districtGu") == DISTRICT
    ]
    facilities = [
        feature
        for feature in facility_data["features"]
        if feature["properties"].get("districtGu") == DISTRICT
    ]

    rows = []
    for stair in stairs:
        lat = float(stair["lat"])
        lng = float(stair["lng"])
        point = project(lng, lat)

        road_distance, road = nearest_road(point, road_infos)
        crosswalk_distance, crosswalk = nearest_point(point, crosswalks)
        facility_distance, facility = nearest_point(point, facilities)

        road_props = road["properties"] if road else {}
        crosswalk_props = crosswalk["properties"] if crosswalk else {}
        facility_props = facility["properties"] if facility else {}

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
            "nearestRoadSourceId": road_props.get("sourceId", ""),
            "nearestRoadName": road_props.get("name") if road_props.get("name") != "NULL" else road_props.get("roadName", ""),
            "nearestRoadWidthMeter": road_props.get("widthMeter", ""),
            "nearestRoadPavement": road_props.get("pavementQualityLabel", ""),
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

    cluster_stairs(rows)

    for row in rows:
        priority, score, reason, status = classify(row)
        row["priority"] = priority
        row["priorityScore"] = str(score)
        row["reviewStatus"] = status
        row["reviewReason"] = reason

    rows.sort(
        key=lambda row: (
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
        "window.HAEUNDAE_STAIR_REVIEW_GEOJSON = "
        + json.dumps(geojson, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )

    summary: dict[str, object] = {
        "districtGu": DISTRICT,
        "stairs": len(rows),
        "roads": len(road_infos),
        "crosswalks": len(crosswalks),
        "facilities": len(facilities),
        "priorityCounts": {},
        "reviewStatusCounts": {},
        "roadDistanceBuckets": {
            "overlap": 0,
            "within5m": 0,
            "within20m": 0,
            "over20m": 0,
        },
    }
    for row in rows:
        summary["priorityCounts"][row["priority"]] = summary["priorityCounts"].get(row["priority"], 0) + 1
        summary["reviewStatusCounts"][row["reviewStatus"]] = summary["reviewStatusCounts"].get(row["reviewStatus"], 0) + 1
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

    print(f"stairs: {len(rows)}")
    print(f"roads: {len(road_infos)}")
    print(f"crosswalks: {len(crosswalks)}")
    print(f"facilities: {len(facilities)}")
    print(f"csv: {CSV_OUT}")
    print(f"geojson: {GEOJSON_OUT}")
    print(f"asset js: {ASSET_JS_OUT}")
    print(f"summary: {SUMMARY_OUT}")


if __name__ == "__main__":
    main()
