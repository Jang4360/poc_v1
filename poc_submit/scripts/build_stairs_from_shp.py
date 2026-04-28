from __future__ import annotations

import csv
import json
import math
import struct
from pathlib import Path


POC_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = next(
    (
        path
        for path in (POC_ROOT / "data" / "geo" / "수치지형도", POC_ROOT / "수치지형도")
        if path.exists()
    ),
    POC_ROOT / "data" / "geo" / "수치지형도",
)
OUTPUT_DIR = POC_ROOT / "data" / "adopted"
CSV_OUT = OUTPUT_DIR / "stg_stairs_ready.csv"
GEOJSON_OUT = OUTPUT_DIR / "stg_stairs_ready.geojson"

FIELDS = [
    "sourceId",
    "districtGu",
    "name",
    "point",
    "lat",
    "lng",
    "widthMeter",
    "areaSquareMeter",
    "structureCode",
    "structureName",
    "scls",
    "ufid",
]


def read_dbf(path: Path) -> list[dict[str, str]]:
    data = path.read_bytes()
    num_records = struct.unpack("<I", data[4:8])[0]
    header_len = struct.unpack("<H", data[8:10])[0]
    record_len = struct.unpack("<H", data[10:12])[0]

    fields = []
    offset = 32
    field_offset = 1
    while offset < header_len - 1:
        desc = data[offset : offset + 32]
        if desc[0] == 0x0D:
            break
        name = desc[0:11].split(b"\x00", 1)[0].decode("ascii", errors="ignore")
        field_len = desc[16]
        fields.append((name, field_len, field_offset))
        field_offset += field_len
        offset += 32

    records = []
    for index in range(num_records):
        record = data[header_len + index * record_len : header_len + (index + 1) * record_len]
        if not record or record[0:1] == b"*":
            continue
        row = {}
        for name, field_len, start in fields:
            row[name] = record[start : start + field_len].decode("cp949", errors="ignore").strip()
        records.append(row)
    return records


def read_polygon_shapes(path: Path) -> list[list[list[tuple[float, float]]]]:
    data = path.read_bytes()
    shapes = []
    offset = 100

    while offset < len(data):
        if offset + 8 > len(data):
            break
        content_len_words = struct.unpack(">i", data[offset + 4 : offset + 8])[0]
        content_start = offset + 8
        content_end = content_start + content_len_words * 2
        content = data[content_start:content_end]
        offset = content_end

        if len(content) < 4:
            continue
        shape_type = struct.unpack("<i", content[:4])[0]
        if shape_type == 0:
            shapes.append([])
            continue
        if shape_type not in (5, 15, 25):
            raise ValueError(f"Unsupported shape type {shape_type} in {path}")

        num_parts = struct.unpack("<i", content[36:40])[0]
        num_points = struct.unpack("<i", content[40:44])[0]
        parts_start = 44
        points_start = parts_start + num_parts * 4
        part_indexes = list(struct.unpack(f"<{num_parts}i", content[parts_start:points_start]))
        part_indexes.append(num_points)

        points = []
        for point_index in range(num_points):
            start = points_start + point_index * 16
            points.append(struct.unpack("<2d", content[start : start + 16]))

        rings = []
        for part_index in range(num_parts):
            start = part_indexes[part_index]
            end = part_indexes[part_index + 1]
            rings.append(points[start:end])
        shapes.append(rings)

    return shapes


def ring_area_centroid(points: list[tuple[float, float]]) -> tuple[float, float, float]:
    if len(points) < 3:
        x = sum(point[0] for point in points) / max(len(points), 1)
        y = sum(point[1] for point in points) / max(len(points), 1)
        return 0.0, x, y

    area2 = 0.0
    cx_sum = 0.0
    cy_sum = 0.0
    for idx, current in enumerate(points):
        nxt = points[(idx + 1) % len(points)]
        cross = current[0] * nxt[1] - nxt[0] * current[1]
        area2 += cross
        cx_sum += (current[0] + nxt[0]) * cross
        cy_sum += (current[1] + nxt[1]) * cross

    if abs(area2) < 1e-9:
        x = sum(point[0] for point in points) / len(points)
        y = sum(point[1] for point in points) / len(points)
        return 0.0, x, y

    area = area2 / 2.0
    return area, cx_sum / (3.0 * area2), cy_sum / (3.0 * area2)


def polygon_centroid_area(rings: list[list[tuple[float, float]]]) -> tuple[float, float, float]:
    weighted_x = 0.0
    weighted_y = 0.0
    total_area = 0.0
    fallback_points = []

    for ring in rings:
        area, cx, cy = ring_area_centroid(ring)
        abs_area = abs(area)
        if abs_area > 0:
            weighted_x += cx * abs_area
            weighted_y += cy * abs_area
            total_area += abs_area
        fallback_points.extend(ring)

    if total_area > 0:
        return weighted_x / total_area, weighted_y / total_area, total_area

    if not fallback_points:
        return 0.0, 0.0, 0.0
    x = sum(point[0] for point in fallback_points) / len(fallback_points)
    y = sum(point[1] for point in fallback_points) / len(fallback_points)
    return x, y, 0.0


def korea_unified_to_wgs84(x: float, y: float) -> tuple[float, float]:
    # EPSG:5179 parameters from the source PRJ.
    a = 6378137.0
    inv_f = 298.257222101
    f = 1.0 / inv_f
    e2 = 2 * f - f * f
    ep2 = e2 / (1 - e2)
    lat0 = math.radians(38.0)
    lon0 = math.radians(127.5)
    k0 = 0.9996
    false_easting = 1_000_000.0
    false_northing = 2_000_000.0

    m0 = meridional_arc(lat0, a, e2)
    m = m0 + (y - false_northing) / k0
    mu = m / (a * (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))

    phi1 = (
        mu
        + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
        + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
        + (151 * e1**3 / 96) * math.sin(6 * mu)
        + (1097 * e1**4 / 512) * math.sin(8 * mu)
    )

    sin_phi1 = math.sin(phi1)
    cos_phi1 = math.cos(phi1)
    tan_phi1 = math.tan(phi1)
    n1 = a / math.sqrt(1 - e2 * sin_phi1**2)
    r1 = a * (1 - e2) / ((1 - e2 * sin_phi1**2) ** 1.5)
    t1 = tan_phi1**2
    c1 = ep2 * cos_phi1**2
    d = (x - false_easting) / (n1 * k0)

    lat = phi1 - (n1 * tan_phi1 / r1) * (
        d**2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * ep2) * d**4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1**2 - 252 * ep2 - 3 * c1**2) * d**6 / 720
    )
    lon = lon0 + (
        d
        - (1 + 2 * t1 + c1) * d**3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1**2 + 8 * ep2 + 24 * t1**2) * d**5 / 120
    ) / cos_phi1

    return math.degrees(lat), math.degrees(lon)


def meridional_arc(phi: float, a: float, e2: float) -> float:
    return a * (
        (1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256) * phi
        - (3 * e2 / 8 + 3 * e2**2 / 32 + 45 * e2**3 / 1024) * math.sin(2 * phi)
        + (15 * e2**2 / 256 + 45 * e2**3 / 1024) * math.sin(4 * phi)
        - (35 * e2**3 / 3072) * math.sin(6 * phi)
    )


def parse_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def district_from_path(path: Path) -> str:
    parts = list(path.parts)
    try:
        return parts[parts.index("수치지형도") + 1]
    except (ValueError, IndexError):
        return ""


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    shp_paths = sorted(SOURCE_ROOT.rglob("N3A_C0390000.shp"))
    rows = []
    features = []
    total_records = 0
    skipped_non_stairs = 0

    for shp_path in shp_paths:
        dbf_path = shp_path.with_suffix(".dbf")
        district_gu = district_from_path(shp_path)
        records = read_dbf(dbf_path)
        shapes = read_polygon_shapes(shp_path)
        if len(records) != len(shapes):
            raise ValueError(f"Record mismatch: {shp_path} dbf={len(records)} shp={len(shapes)}")

        for record, rings in zip(records, shapes):
            total_records += 1
            if record.get("STRU") != "SRD001":
                skipped_non_stairs += 1
                continue

            x, y, area = polygon_centroid_area(rings)
            lat, lng = korea_unified_to_wgs84(x, y)
            source_id = f"stairs:{len(rows) + 1}"
            name = record.get("NAME") or "계단"
            width = parse_float(record.get("WIDT", ""))

            row = {
                "sourceId": source_id,
                "districtGu": district_gu,
                "name": name,
                "point": f"POINT({lng:.7f} {lat:.7f})",
                "lat": f"{lat:.7f}",
                "lng": f"{lng:.7f}",
                "widthMeter": "" if width is None else f"{width:.2f}",
                "areaSquareMeter": f"{area:.2f}",
                "structureCode": record.get("STRU", ""),
                "structureName": "계단",
                "scls": record.get("SCLS", ""),
                "ufid": record.get("UFID", ""),
            }
            rows.append(row)
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [round(lng, 7), round(lat, 7)]},
                    "properties": {key: value for key, value in row.items() if key not in ("point", "lat", "lng")},
                }
            )

    with CSV_OUT.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    GEOJSON_OUT.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"source shapefiles: {len(shp_paths)}")
    print(f"source records: {total_records}")
    print(f"stairs records: {len(rows)}")
    print(f"skipped non-stairs: {skipped_non_stairs}")
    print(f"csv: {CSV_OUT}")
    print(f"geojson: {GEOJSON_OUT}")


if __name__ == "__main__":
    main()
