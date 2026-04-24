from __future__ import annotations

# SQL 패턴 선택 이유:
# 이 모듈의 INSERT/UPDATE는 ON CONFLICT 절, OVERRIDING SYSTEM VALUE, 다중 컬럼 SET 같은
# 복합 SQL이 필요해 db.insert_row()/db.ewkt() 헬퍼로 표현하기 어렵다.
# 대신 raw SQL 문자열 + psycopg %s placeholder를 사용하고,
# EWKT 변환은 local ewkt_point_from_wkt()로 처리한다.
# 단순 INSERT가 필요한 신규 스크립트에서는 db.insert_row()/db.ewkt()를 사용한다.

import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

import shapefile
from pyproj import Transformer

from etl.common.db import connect


ROOT_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT_DIR / "etl" / "raw"
RUNTIME_DIR = ROOT_DIR / "runtime" / "etl"
REFERENCE_REPORT_DIR = RUNTIME_DIR / "03-reference-load"
CONTINUOUS_REPORT_DIR = RUNTIME_DIR / "continuous-map-load"

PLACE_CANONICAL = RAW_DIR / "place_merged_broad_category_final.csv"
PLACE_ALT = RAW_DIR / "place_merged_final.csv"
PLACE_ACCESSIBILITY = RAW_DIR / "place_accessibility_features_merged_final.csv"
AUDIO_SIGNALS = RAW_DIR / "stg_audio_signals_ready.csv"
CROSSWALKS = RAW_DIR / "stg_crosswalks_ready.csv"
SLOPE_ANALYSIS = RAW_DIR / "slope_analysis_staging.csv"
SUBWAY_ELEVATORS = RAW_DIR / "subway_station_elevators_erd_ready.csv"
LOW_FLOOR_BUSES = RAW_DIR / "부산광역시_시내버스 업체별 연도별 버스 등록대수_20260330.csv"
CONTINUOUS_BUNDLE_DIR = RAW_DIR / "drive-download-20260423T114350Z-3-001"
CENTERLINE_SOURCE = RAW_DIR / "N3L_A0020000_26.shp"

CSV_ENCODINGS = ("utf-8-sig", "cp949", "euc-kr")
SHP_ENCODINGS = ("cp949", "euc-kr", "utf-8")
POINT_AUTO_M = 5.0
POINT_REVIEW_M = 10.0
ELEVATOR_AUTO_M = 15.0
ELEVATOR_REVIEW_M = 30.0
CONTINUOUS_SOURCE_DATASET = "drive-download-20260423T114350Z-3-001"
SLOPE_SOURCE_DATASET = "slope_analysis_staging.csv"
FILTER_POLYGON_SOURCE_DATASET = "N3L_A0020000_26"
FILTER_POLYGON_MATCH_M = 2.0
FILTER_POLYGON_BUFFER_FLOOR_M = 1.0
FILTER_POLYGON_OVERLAP_BUFFER_M = 0.25
N3L_A0033320_OVERLAP_RATIO = 0.30
N3L_A0033320_AUTO_M = 5.0
SLOPE_OVERLAP_RATIO = 0.30
STAIRS_AUTO_M = 5.0
STAIRS_REVIEW_M = 10.0
CONTINUOUS_EVIDENCE_LAYERS = (
    "N3A_A0063321",
    "N3A_A0070000",
    "N3A_A0080000",
    "N3A_A0110020",
    "N3L_A0123373",
)
CONTINUOUS_EVIDENCE_AUTO_M = 5.0
CONTINUOUS_EVIDENCE_REVIEW_M = 10.0
TM5179_TO_WGS84 = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)
_schema_ensured = False

QUAL_TO_SURFACE_STATE = {
    "SWQ000": "UNKNOWN",
    "SWQ001": "PAVED",
    "SWQ002": "PAVED",
    "SWQ003": "BLOCK",
    "SWQ004": "UNPAVED",
    "SWQ005": "OTHER",
    "SWQ999": "OTHER",
}


@dataclass
class LoadStats:
    source_rows: int = 0
    loaded_rows: int = 0
    matched_rows: int = 0
    unmatched_rows: int = 0
    review_rows: int = 0
    conflict_rows: int = 0
    skipped_rows: int = 0
    duplicate_rows: int = 0
    details: dict[str, Any] = field(default_factory=dict)

    def asdict(self) -> dict[str, Any]:
        return {
            "source_rows": self.source_rows,
            "loaded_rows": self.loaded_rows,
            "matched_rows": self.matched_rows,
            "unmatched_rows": self.unmatched_rows,
            "review_rows": self.review_rows,
            "conflict_rows": self.conflict_rows,
            "skipped_rows": self.skipped_rows,
            "duplicate_rows": self.duplicate_rows,
            **self.details,
        }


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_report(path: Path, report: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=json_default) + "\n",
        encoding="utf-8",
    )


def json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(f"Object of type {value.__class__.__name__} is not JSON serializable")


def read_csv_rows(path: Path, *, encodings: Iterable[str] = CSV_ENCODINGS) -> tuple[list[dict[str, str]], str, list[str]]:
    last_error: UnicodeDecodeError | None = None
    for encoding in encodings:
        try:
            with path.open("r", encoding=encoding, newline="") as fh:
                reader = csv.DictReader(fh)
                fieldnames = [normalize_header(item) for item in (reader.fieldnames or [])]
                rows: list[dict[str, str]] = []
                for row in reader:
                    rows.append({normalize_header(key): (value or "").strip() for key, value in row.items()})
            return rows, encoding, fieldnames
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise ValueError(f"no encodings supplied for {path}")


def normalize_header(value: str | None) -> str:
    return (value or "").strip().strip('"')


def parse_bool(value: str) -> bool:
    return value.strip().lower() in {"true", "1", "yes", "y", "예", "가능"}


def parse_optional_float(value: str | None) -> float | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_optional_int(value: str) -> int | None:
    text = (value or "").strip()
    if not text:
        return None
    return int(float(text))


def derive_width_state(width_meter: float | None) -> str:
    if width_meter is None or width_meter <= 0:
        return "UNKNOWN"
    if width_meter >= 1.5:
        return "ADEQUATE_150"
    if width_meter >= 1.2:
        return "ADEQUATE_120"
    return "NARROW"


def surface_state_from_qual(value: str | None) -> str:
    return QUAL_TO_SURFACE_STATE.get((value or "").strip(), "UNKNOWN")


def normalize_provider(value: str) -> str | None:
    text = (value or "").strip()
    return text or None


def filter_polygon_half_width(width_meter: float | None) -> float:
    if width_meter is None or width_meter <= 0:
        return FILTER_POLYGON_BUFFER_FLOOR_M
    return max(width_meter / 2.0, FILTER_POLYGON_BUFFER_FLOOR_M)


def normalize_crossing_state(value: str) -> str:
    text = (value or "").strip().upper()
    if text in {"TRAFFIC_SIGNALS", "NO", "UNKNOWN"}:
        return text
    return "UNKNOWN"


def ewkt_point_from_wkt(value: str) -> str:
    lon, lat = parse_wkt_point(value)
    return f"SRID=4326;POINT({lon:.10f} {lat:.10f})"


def parse_wkt_point(value: str) -> tuple[float, float]:
    text = (value or "").strip()
    if not text:
        raise ValueError("empty POINT WKT")
    body = text.split("POINT", 1)[1].strip()
    body = body.removeprefix("(").removesuffix(")")
    lon, lat = body.split()[:2]
    return float(lon), float(lat)


def point_ewkt(lon: float, lat: float) -> str:
    return f"SRID=4326;POINT({lon:.10f} {lat:.10f})"


def geometry_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def transform_point_5179_to_4326(point: tuple[float, float]) -> tuple[float, float]:
    lon, lat = TM5179_TO_WGS84.transform(point[0], point[1])
    return float(lon), float(lat)


def _ring_wkt(points: list[tuple[float, float]]) -> str:
    if points[0] != points[-1]:
        points = [*points, points[0]]
    return "(" + ",".join(f"{lon:.10f} {lat:.10f}" for lon, lat in points) + ")"


def shape_to_wkt_5179(shape: shapefile.Shape) -> str:
    part_starts = list(shape.parts) + [len(shape.points)]
    parts = [shape.points[start:end] for start, end in zip(part_starts, part_starts[1:], strict=False)]
    parts = [part for part in parts if len(part) >= 2]
    if shape.shapeType in {
        shapefile.POLYLINE,
        shapefile.POLYLINEZ,
        shapefile.POLYLINEM,
    }:
        lines = ["(" + ",".join(f"{lon:.10f} {lat:.10f}" for lon, lat in part) + ")" for part in parts]
        if len(lines) == 1:
            return f"LINESTRING{lines[0]}"
        return "MULTILINESTRING(" + ",".join(lines) + ")"
    raise ValueError(f"unsupported shape type for EPSG:5179 WKT conversion: {shape.shapeTypeName}")


def shape_to_wkt_4326(shape: shapefile.Shape) -> str:
    transformed = [transform_point_5179_to_4326(point) for point in shape.points]
    part_starts = list(shape.parts) + [len(transformed)]
    parts = [transformed[start:end] for start, end in zip(part_starts, part_starts[1:], strict=False)]
    parts = [part for part in parts if len(part) >= 2]
    if shape.shapeType in {
        shapefile.POLYLINE,
        shapefile.POLYLINEZ,
        shapefile.POLYLINEM,
    }:
        lines = ["(" + ",".join(f"{lon:.10f} {lat:.10f}" for lon, lat in part) + ")" for part in parts]
        if len(lines) == 1:
            return f"LINESTRING{lines[0]}"
        return "MULTILINESTRING(" + ",".join(lines) + ")"
    if shape.shapeType in {
        shapefile.POLYGON,
        shapefile.POLYGONZ,
        shapefile.POLYGONM,
    }:
        polygons = [f"({_ring_wkt(part)})" for part in parts if len(part) >= 3]
        if len(polygons) == 1:
            return f"POLYGON{polygons[0]}"
        return "MULTIPOLYGON(" + ",".join(polygons) + ")"
    if shape.shapeType in {shapefile.POINT, shapefile.POINTZ, shapefile.POINTM}:
        lon, lat = transformed[0]
        return f"POINT({lon:.10f} {lat:.10f})"
    raise ValueError(f"unsupported shape type for WKT conversion: {shape.shapeTypeName}")


def ensure_reference_schema() -> None:
    global _schema_ensured
    if _schema_ensured:
        return
    statements = [
        'ALTER TABLE segment_features ADD COLUMN IF NOT EXISTS "sourceDataset" VARCHAR(160)',
        'ALTER TABLE segment_features ADD COLUMN IF NOT EXISTS "sourceLayer" VARCHAR(80)',
        'ALTER TABLE segment_features ADD COLUMN IF NOT EXISTS "sourceRowNumber" INTEGER',
        'ALTER TABLE segment_features ADD COLUMN IF NOT EXISTS "matchStatus" VARCHAR(30) NOT NULL DEFAULT \'MATCHED\'',
        'ALTER TABLE segment_features ADD COLUMN IF NOT EXISTS "matchScore" NUMERIC(10, 6)',
        'ALTER TABLE segment_features ADD COLUMN IF NOT EXISTS "properties" JSONB NOT NULL DEFAULT \'{}\'::jsonb',
        """
        CREATE INDEX IF NOT EXISTS idx_segment_features_source
            ON segment_features ("sourceDataset", "sourceLayer", "sourceRowNumber")
        """,
        """
        CREATE TABLE IF NOT EXISTS road_segment_filter_polygons (
            "edgeId" BIGINT PRIMARY KEY REFERENCES road_segments ("edgeId") ON DELETE CASCADE,
            "sourceRowNumber" INTEGER NOT NULL,
            "sourceUfid" VARCHAR(34),
            "roadWidthMeter" NUMERIC(8, 2) NOT NULL,
            "bufferHalfWidthMeter" NUMERIC(8, 2) NOT NULL,
            "geom" GEOMETRY(MULTIPOLYGON, 5179) NOT NULL,
            "createdAt" TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_road_segment_filter_polygons_geom
            ON road_segment_filter_polygons USING GIST ("geom")
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_road_segment_filter_polygons_source_ufid
            ON road_segment_filter_polygons ("sourceUfid")
        """,
    ]
    with connect() as conn:
        with conn.cursor() as cur:
            for statement in statements:
                cur.execute(statement)
        conn.commit()
    _schema_ensured = True


def table_exists(cur: Any, table_name: str) -> bool:
    cur.execute("SELECT to_regclass(%s)", (f"public.{table_name}",))
    return cur.fetchone()[0] is not None


def diff_place_csvs() -> dict[str, Any]:
    canonical, canonical_encoding, canonical_headers = read_csv_rows(PLACE_CANONICAL)
    alt, alt_encoding, alt_headers = read_csv_rows(PLACE_ALT)
    canonical_digest = hashlib.sha256(PLACE_CANONICAL.read_bytes()).hexdigest()
    alt_digest = hashlib.sha256(PLACE_ALT.read_bytes()).hexdigest()
    row_diffs: list[dict[str, Any]] = []
    for idx, (left, right) in enumerate(zip(canonical, alt, strict=False), start=1):
        if left != right:
            row_diffs.append({"row_number": idx, "canonical": left, "alternate": right})
        if len(row_diffs) >= 10:
            break
    report = {
        "canonical_file": str(PLACE_CANONICAL),
        "alternate_file": str(PLACE_ALT),
        "canonical_encoding": canonical_encoding,
        "alternate_encoding": alt_encoding,
        "canonical_rows": len(canonical),
        "alternate_rows": len(alt),
        "canonical_headers": canonical_headers,
        "alternate_headers": alt_headers,
        "same_headers": canonical_headers == alt_headers,
        "same_row_count": len(canonical) == len(alt),
        "same_file_digest": canonical_digest == alt_digest,
        "sample_row_diffs": row_diffs,
        "canonical_decision": "place_merged_broad_category_final.csv" if canonical_headers == alt_headers else "review-required",
    }
    write_report(RUNTIME_DIR / "00b_place_csv_diff.json", report)
    return report


def load_places(*, dry_run: bool = False) -> dict[str, Any]:
    rows, encoding, headers = read_csv_rows(PLACE_CANONICAL)
    stats = LoadStats(source_rows=len(rows), details={"encoding": encoding, "headers": headers})
    provider_values = [normalize_provider(row["providerPlaceId"]) for row in rows]
    provider_nonempty = [value for value in provider_values if value is not None]
    stats.details["providerPlaceId_nonempty"] = len(provider_nonempty)
    stats.details["providerPlaceId_duplicates"] = len(provider_nonempty) - len(set(provider_nonempty))
    if dry_run:
        stats.loaded_rows = len(rows)
        return stats.asdict()

    with connect() as conn:
        with conn.cursor() as cur:
            for row in rows:
                cur.execute(
                    """
                    INSERT INTO places ("placeId", "name", "category", "address", "point", "providerPlaceId")
                    OVERRIDING SYSTEM VALUE
                    VALUES (%s, %s, %s, %s, ST_GeomFromEWKT(%s), %s)
                    ON CONFLICT ("placeId") DO UPDATE SET
                        "name" = EXCLUDED."name",
                        "category" = EXCLUDED."category",
                        "address" = EXCLUDED."address",
                        "point" = EXCLUDED."point",
                        "providerPlaceId" = EXCLUDED."providerPlaceId"
                    """,
                    (
                        int(row["placeId"]),
                        row["name"],
                        row["category"],
                        row["address"] or None,
                        ewkt_point_from_wkt(row["point"]),
                        normalize_provider(row["providerPlaceId"]),
                    ),
                )
                stats.loaded_rows += 1
            cur.execute(
                """
                SELECT setval(
                    pg_get_serial_sequence('places', 'placeId'),
                    COALESCE((SELECT MAX("placeId") FROM places), 1),
                    true
                )
                """
            )
        conn.commit()
    return stats.asdict()


def load_place_accessibility(*, dry_run: bool = False) -> dict[str, Any]:
    rows, encoding, headers = read_csv_rows(PLACE_ACCESSIBILITY)
    stats = LoadStats(source_rows=len(rows), details={"encoding": encoding, "headers": headers})
    feature_counts = Counter(row["featureType"] for row in rows)
    stats.details["feature_counts"] = dict(sorted(feature_counts.items()))
    if dry_run:
        stats.loaded_rows = len(rows)
        return stats.asdict()

    with connect() as conn:
        with conn.cursor() as cur:
            for row in rows:
                cur.execute(
                    """
                    INSERT INTO place_accessibility_features ("placeId", "featureType", "isAvailable")
                    VALUES (%s, %s, %s)
                    ON CONFLICT ("placeId", "featureType") DO UPDATE SET
                        "isAvailable" = EXCLUDED."isAvailable"
                    """,
                    (int(row["placeId"]), row["featureType"], parse_bool(row["isAvailable"])),
                )
                stats.loaded_rows += 1
        conn.commit()
    return stats.asdict()


def nearest_segment(cur: Any, lon: float, lat: float, radius_m: float) -> tuple[int, float, float] | None:
    degree_radius = radius_m / 90_000.0
    cur.execute(
        """
        WITH p AS (
            SELECT ST_SetSRID(ST_MakePoint(%s, %s), 4326) AS geom
        )
        SELECT
            rs."edgeId",
            ST_Distance(rs."geom"::geography, p.geom::geography) AS distance_m,
            ST_Length(rs."geom"::geography) AS edge_length_m
        FROM road_segments rs, p
        WHERE rs."geom" && ST_Expand(p.geom, %s)
          AND ST_DWithin(rs."geom"::geography, p.geom::geography, %s)
        ORDER BY distance_m ASC, rs."edgeId" ASC
        LIMIT 1
        """,
        (lon, lat, degree_radius, radius_m),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return int(row[0]), float(row[1]), float(row[2])


def reset_segment_feature_types(cur: Any, feature_types: Iterable[str]) -> None:
    cur.execute('DELETE FROM segment_features WHERE "featureType" = ANY(%s::text[])', (list(feature_types),))


def insert_segment_feature(
    cur: Any,
    edge_id: int,
    feature_type: str,
    ewkt: str,
    *,
    source_dataset: str | None = None,
    source_layer: str | None = None,
    source_row_number: int | None = None,
    match_status: str = "MATCHED",
    match_score: float | None = None,
    properties: dict[str, Any] | None = None,
) -> None:
    cur.execute(
        """
        INSERT INTO segment_features (
            "edgeId", "featureType", "geom",
            "sourceDataset", "sourceLayer", "sourceRowNumber",
            "matchStatus", "matchScore", "properties"
        )
        VALUES (%s, %s, ST_GeomFromEWKT(%s), %s, %s, %s, %s, %s, %s::jsonb)
        """,
        (
            edge_id,
            feature_type,
            ewkt,
            source_dataset,
            source_layer,
            source_row_number,
            match_status,
            match_score,
            json.dumps(properties or {}, ensure_ascii=False),
        ),
    )


def load_audio_signals(*, dry_run: bool = False) -> dict[str, Any]:
    rows, encoding, headers = read_csv_rows(AUDIO_SIGNALS)
    stats = LoadStats(source_rows=len(rows), details={"encoding": encoding, "headers": headers})
    candidates = [
        row
        for row in rows
        if row["stat"] == "정상동작" and row["audioSignalState"].upper() == "YES" and row["lat"] and row["lng"]
    ]
    stats.details["candidate_rows"] = len(candidates)
    if dry_run:
        stats.skipped_rows = len(rows) - len(candidates)
        return stats.asdict()

    ensure_reference_schema()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute('UPDATE road_segments SET "audioSignalState" = %s::yes_no_unknown', ("UNKNOWN",))
            reset_segment_feature_types(cur, ["AUDIO_SIGNAL"])
            for row in candidates:
                lon = float(row["lng"])
                lat = float(row["lat"])
                match = nearest_segment(cur, lon, lat, POINT_REVIEW_M)
                if match is None:
                    stats.unmatched_rows += 1
                    continue
                edge_id, distance_m, _ = match
                if distance_m <= POINT_AUTO_M:
                    cur.execute(
                        'UPDATE road_segments SET "audioSignalState" = %s::yes_no_unknown WHERE "edgeId" = %s',
                        ("YES", edge_id),
                    )
                    insert_segment_feature(cur, edge_id, "AUDIO_SIGNAL", point_ewkt(lon, lat))
                    stats.matched_rows += 1
                    stats.loaded_rows += 1
                else:
                    stats.review_rows += 1
            stats.skipped_rows = len(rows) - len(candidates)
        conn.commit()
    return stats.asdict()


def load_crosswalks(*, dry_run: bool = False) -> dict[str, Any]:
    rows, encoding, headers = read_csv_rows(CROSSWALKS)
    stats = LoadStats(source_rows=len(rows), details={"encoding": encoding, "headers": headers})
    candidates = [row for row in rows if row["point"]]
    stats.details["candidate_rows"] = len(candidates)
    if dry_run:
        stats.skipped_rows = len(rows) - len(candidates)
        return stats.asdict()

    ensure_reference_schema()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute('UPDATE road_segments SET "crossingState" = %s::crossing_state', ("UNKNOWN",))
            reset_segment_feature_types(cur, ["CROSSWALK"])
            for row in candidates:
                lon, lat = parse_wkt_point(row["point"])
                match = nearest_segment(cur, lon, lat, POINT_REVIEW_M)
                if match is None:
                    stats.unmatched_rows += 1
                    continue
                edge_id, distance_m, edge_length_m = match
                source_length = parse_optional_float(row["lengthMeter"])
                if source_length and source_length > 0:
                    ratio = edge_length_m / source_length
                    if ratio < 0.2 or ratio > 5.0:
                        stats.conflict_rows += 1
                        continue
                if distance_m <= POINT_AUTO_M:
                    cur.execute(
                        """
                        UPDATE road_segments
                        SET "crossingState" = %s::crossing_state,
                            "widthMeter" = COALESCE("widthMeter", %s)
                        WHERE "edgeId" = %s
                        """,
                        (normalize_crossing_state(row.get("crossingState", "")), parse_optional_float(row["widthMeter"]), edge_id),
                    )
                    insert_segment_feature(cur, edge_id, "CROSSWALK", point_ewkt(lon, lat))
                    stats.matched_rows += 1
                    stats.loaded_rows += 1
                else:
                    stats.review_rows += 1
            stats.skipped_rows = len(rows) - len(candidates)
        conn.commit()
    return stats.asdict()


def _deduplicate_elevator_rows(rows: list[dict[str, str]]) -> tuple[list[dict[str, str]], int]:
    valid: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    duplicate_count = 0
    for row in rows:
        key = (row.get("stationId", ""), row.get("entranceNo", ""), row.get("point", ""))
        if key in seen:
            duplicate_count += 1
            continue
        seen.add(key)
        valid.append(row)
    return valid, duplicate_count


def load_subway_elevators(*, dry_run: bool = False) -> dict[str, Any]:
    rows, encoding, headers = read_csv_rows(SUBWAY_ELEVATORS)
    stats = LoadStats(source_rows=len(rows), details={"encoding": encoding, "headers": headers})
    skippable = [row for row in rows if not row.get("elevatorId") or not row.get("point")]
    stats.skipped_rows = len(skippable)
    eligible = [row for row in rows if row.get("elevatorId") and row.get("point")]
    valid, dup_count = _deduplicate_elevator_rows(eligible)
    stats.duplicate_rows = dup_count
    stats.details["unique_station_entrance_point"] = len(valid)
    if dry_run:
        stats.loaded_rows = len(valid)
        return stats.asdict()

    ensure_reference_schema()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute('UPDATE road_segments SET "elevatorState" = %s::yes_no_unknown', ("UNKNOWN",))
            reset_segment_feature_types(cur, ["SUBWAY_ELEVATOR"])
            for row in valid:
                ewkt = ewkt_point_from_wkt(row["point"])
                cur.execute(
                    """
                    INSERT INTO subway_station_elevators (
                        "elevatorId", "stationId", "stationName", "lineName", "entranceNo", "point"
                    )
                    VALUES (%s, %s, %s, %s, %s, ST_GeomFromEWKT(%s))
                    ON CONFLICT ("elevatorId") DO UPDATE SET
                        "stationId" = EXCLUDED."stationId",
                        "stationName" = EXCLUDED."stationName",
                        "lineName" = EXCLUDED."lineName",
                        "entranceNo" = EXCLUDED."entranceNo",
                        "point" = EXCLUDED."point"
                    """,
                    (
                        int(row["elevatorId"]),
                        row["stationId"],
                        row["stationName"],
                        row["lineName"],
                        row["entranceNo"] or None,
                        ewkt,
                    ),
                )
                stats.loaded_rows += 1
                lon, lat = parse_wkt_point(row["point"])
                match = nearest_segment(cur, lon, lat, ELEVATOR_REVIEW_M)
                if match is None:
                    stats.unmatched_rows += 1
                    continue
                edge_id, distance_m, _ = match
                if distance_m <= ELEVATOR_AUTO_M:
                    cur.execute(
                        'UPDATE road_segments SET "elevatorState" = %s::yes_no_unknown WHERE "edgeId" = %s',
                        ("YES", edge_id),
                    )
                    insert_segment_feature(cur, edge_id, "SUBWAY_ELEVATOR", point_ewkt(lon, lat))
                    stats.matched_rows += 1
                else:
                    stats.review_rows += 1
        conn.commit()
    return stats.asdict()


def load_low_floor_bus_routes(*, dry_run: bool = False) -> dict[str, Any]:
    rows, encoding, headers = read_csv_rows(LOW_FLOOR_BUSES)
    stats = LoadStats(source_rows=len(rows), details={"encoding": encoding, "headers": headers})
    routes: dict[str, dict[str, Any]] = {}
    for row in rows:
        route_no = row["인가노선"].strip()
        if not route_no:
            stats.skipped_rows += 1
            continue
        route = routes.setdefault(route_no, {"routeNo": route_no, "hasLowFloor": False, "vehicleCount": 0})
        route["vehicleCount"] += 1
        if row["운행구분"] == "저상":
            route["hasLowFloor"] = True
    stats.details["route_count"] = len(routes)
    stats.details["low_floor_route_count"] = sum(1 for route in routes.values() if route["hasLowFloor"])
    if dry_run:
        stats.loaded_rows = len(routes)
        return stats.asdict()

    with connect() as conn:
        with conn.cursor() as cur:
            for route_no, route in sorted(routes.items()):
                cur.execute(
                    """
                    INSERT INTO low_floor_bus_routes ("routeId", "routeNo", "hasLowFloor")
                    VALUES (%s, %s, %s)
                    ON CONFLICT ("routeId") DO UPDATE SET
                        "routeNo" = EXCLUDED."routeNo",
                        "hasLowFloor" = EXCLUDED."hasLowFloor"
                    """,
                    (route_no, route["routeNo"], route["hasLowFloor"]),
                )
                stats.loaded_rows += 1
        conn.commit()
    return stats.asdict()


def slope_analysis_report() -> dict[str, Any]:
    rows, encoding, headers = read_csv_rows(SLOPE_ANALYSIS)
    source_counts = Counter(row["source_type"] for row in rows)
    missing_geometry = sum(1 for row in rows if not row.get("geometry_wkt_4326"))
    width_values = [parse_optional_float(row.get("width_meter", "")) for row in rows]
    width_nonempty = [value for value in width_values if value is not None]
    report = {
        "source_rows": len(rows),
        "encoding": encoding,
        "headers": headers,
        "source_type_counts": dict(sorted(source_counts.items())),
        "missing_geometry_wkt_4326": missing_geometry,
        "width_nonempty_rows": len(width_nonempty),
        "metric_mean_nonempty_rows": sum(1 for row in rows if row.get("metric_mean")),
        "status": "report-only",
        "reason": "polygon overlay is intentionally kept as a separate heavy ETL step before mutating road_segments",
    }
    write_report(REFERENCE_REPORT_DIR / "slope_analysis_report.json", report)
    return report


def open_shapefile(path: Path) -> tuple[shapefile.Reader, str]:
    last_error: UnicodeDecodeError | None = None
    for encoding in SHP_ENCODINGS:
        try:
            reader = shapefile.Reader(str(path), encoding=encoding)
            if len(reader) > 0:
                reader.record(0)
            return reader, encoding
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise ValueError(f"could not open shapefile: {path}")


def continuous_map_manifest() -> dict[str, Any]:
    layers: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "row_count": 0,
            "shape_types": Counter(),
            "districts": {},
            "field_names": set(),
            "files": [],
            "encodings": Counter(),
        }
    )
    district_dirs = [path for path in CONTINUOUS_BUNDLE_DIR.iterdir() if path.is_dir()]
    for district_dir in sorted(district_dirs):
        for shp_path in sorted(district_dir.glob("**/*.shp")):
            layer_code = shp_path.stem
            reader, encoding = open_shapefile(shp_path)
            field_names = [field[0] for field in reader.fields[1:]]
            layer = layers[layer_code]
            layer["row_count"] += len(reader)
            layer["shape_types"][reader.shapeTypeName] += 1
            layer["districts"][district_dir.name] = layer["districts"].get(district_dir.name, 0) + len(reader)
            layer["field_names"].update(field_names)
            layer["files"].append(str(shp_path))
            layer["encodings"][encoding] += 1

    serializable_layers = {}
    for layer_code, data in sorted(layers.items()):
        serializable_layers[layer_code] = {
            "row_count": data["row_count"],
            "shape_types": dict(data["shape_types"]),
            "districts": dict(sorted(data["districts"].items())),
            "field_names": sorted(data["field_names"]),
            "file_count": len(data["files"]),
            "files": data["files"],
            "encodings": dict(data["encodings"]),
        }
    report = {
        "bundle_dir": str(CONTINUOUS_BUNDLE_DIR),
        "district_count": len(district_dirs),
        "layers": serializable_layers,
    }
    write_report(CONTINUOUS_REPORT_DIR / "continuous_map_manifest.json", report)
    return report


def continuous_centerline_compare() -> dict[str, Any]:
    current_reader, current_encoding = open_shapefile(CENTERLINE_SOURCE)
    current_fields = [field[0] for field in current_reader.fields[1:]]
    bundle_files = _layer_paths("N3L_A0020000")
    bundle_row_count = 0
    bundle_districts: dict[str, int] = {}
    bundle_encodings: Counter[str] = Counter()
    bundle_shape_types: Counter[str] = Counter()
    bundle_fields: set[str] = set()
    for shp_path in bundle_files:
        district = shp_path.parents[1].name
        reader, encoding = open_shapefile(shp_path)
        bundle_row_count += len(reader)
        bundle_districts[district] = bundle_districts.get(district, 0) + len(reader)
        bundle_encodings[encoding] += 1
        bundle_shape_types[reader.shapeTypeName] += 1
        bundle_fields.update(field[0] for field in reader.fields[1:])
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM road_segments")
            road_segments_count = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM road_nodes")
            road_nodes_count = int(cur.fetchone()[0])
    report = {
        "current_network_source": CENTERLINE_SOURCE.name,
        "current_source_rows": len(current_reader),
        "current_source_encoding": current_encoding,
        "current_shape_type": current_reader.shapeTypeName,
        "current_fields": current_fields,
        "db_road_segments": road_segments_count,
        "db_road_nodes": road_nodes_count,
        "bundle_layer": "N3L_A0020000",
        "bundle_files": [str(path) for path in bundle_files],
        "bundle_file_count": len(bundle_files),
        "bundle_rows": bundle_row_count,
        "bundle_districts": dict(sorted(bundle_districts.items())),
        "bundle_encodings": dict(bundle_encodings),
        "bundle_shape_types": dict(bundle_shape_types),
        "bundle_fields": sorted(bundle_fields),
        "decision": "compare-only; keep N3L_A0020000_26 as the canonical road_segments source for this POC",
    }
    write_report(CONTINUOUS_REPORT_DIR / "continuous_centerline_compare_report.json", report)
    return report


def _layer_paths(layer_code: str) -> list[Path]:
    return sorted(CONTINUOUS_BUNDLE_DIR.glob(f"**/{layer_code}.shp"))


def _record_to_dict(fields: list[str], record: shapefile.Record) -> dict[str, str]:
    return {field: str(record[idx]).strip() for idx, field in enumerate(fields)}


def _json_properties(properties: dict[str, Any]) -> str:
    return json.dumps(properties, ensure_ascii=False)


def load_road_segment_filter_polygons(*, dry_run: bool = False) -> dict[str, Any]:
    reader, encoding = open_shapefile(CENTERLINE_SOURCE)
    fields = [field[0] for field in reader.fields[1:]]
    stats = LoadStats(
        details={
            "source_dataset": FILTER_POLYGON_SOURCE_DATASET,
            "source_file": str(CENTERLINE_SOURCE),
            "encoding": encoding,
            "shape_type": reader.shapeTypeName,
            "fields": fields,
        }
    )
    source_rows: list[tuple[int, str | None, float, str]] = []
    for source_row_number, shape_record in enumerate(reader.iterShapeRecords(), start=1):
        stats.source_rows += 1
        props = _record_to_dict(fields, shape_record.record)
        width_meter = parse_optional_float(props.get("RVWD"))
        if width_meter is None or width_meter <= 0:
            stats.skipped_rows += 1
            continue
        try:
            geom_wkt_5179 = shape_to_wkt_5179(shape_record.shape)
        except ValueError:
            stats.skipped_rows += 1
            continue
        source_rows.append((source_row_number, props.get("UFID") or None, width_meter, geom_wkt_5179))
    stats.details["candidate_rows"] = len(source_rows)
    stats.details["road_width_meter_stats"] = {
        "min": min((row[2] for row in source_rows), default=None),
        "avg": round(sum(row[2] for row in source_rows) / len(source_rows), 3) if source_rows else None,
        "max": max((row[2] for row in source_rows), default=None),
    }

    ensure_reference_schema()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM road_segments")
            road_segment_count = int(cur.fetchone()[0])
            stats.details["road_segment_count"] = road_segment_count

            cur.execute(
                """
                CREATE TEMP TABLE tmp_centerline_filter_source (
                    "sourceRowNumber" INTEGER NOT NULL,
                    "sourceUfid" TEXT,
                    "roadWidthMeter" DOUBLE PRECISION NOT NULL,
                    "geom" GEOMETRY(GEOMETRY, 5179) NOT NULL
                ) ON COMMIT DROP
                """
            )

            batch: list[tuple[int, str | None, float, str]] = []
            for row in source_rows:
                batch.append(row)
                if len(batch) >= 2000:
                    cur.executemany(
                        """
                        INSERT INTO tmp_centerline_filter_source (
                            "sourceRowNumber", "sourceUfid", "roadWidthMeter", "geom"
                        )
                        VALUES (%s, %s, %s, ST_SetSRID(ST_GeomFromText(%s), 5179))
                        """,
                        batch,
                    )
                    batch.clear()
            if batch:
                cur.executemany(
                    """
                    INSERT INTO tmp_centerline_filter_source (
                        "sourceRowNumber", "sourceUfid", "roadWidthMeter", "geom"
                    )
                    VALUES (%s, %s, %s, ST_SetSRID(ST_GeomFromText(%s), 5179))
                    """,
                    batch,
                )
            cur.execute('CREATE INDEX tmp_centerline_filter_source_geom ON tmp_centerline_filter_source USING GIST ("geom")')
            cur.execute('ANALYZE tmp_centerline_filter_source')

            cur.execute(
                """
                CREATE TEMP TABLE tmp_centerline_filter_source_match AS
                WITH segment_geom AS (
                    SELECT
                        rs."edgeId",
                        ST_Transform(rs."geom", 5179) AS geom_5179
                    FROM road_segments rs
                ),
                candidates AS (
                    SELECT
                        rs."edgeId",
                        src."sourceRowNumber",
                        src."sourceUfid",
                        src."roadWidthMeter",
                        ST_Distance(rs.geom_5179, src."geom") AS distance_m,
                        ST_Length(
                            ST_Intersection(
                                ST_Buffer(rs.geom_5179, %s, 'endcap=flat join=round'),
                                src."geom"
                            )
                        ) AS overlap_m
                    FROM segment_geom rs
                    JOIN tmp_centerline_filter_source src
                      ON src."geom" && ST_Expand(rs.geom_5179, %s)
                     AND ST_DWithin(rs.geom_5179, src."geom", %s)
                ),
                ranked AS (
                    SELECT
                        *,
                        ROW_NUMBER() OVER (
                            PARTITION BY "edgeId"
                            ORDER BY overlap_m DESC, distance_m ASC, "sourceRowNumber" ASC
                        ) AS rn
                    FROM candidates
                )
                SELECT
                    "edgeId",
                    "sourceRowNumber",
                    "sourceUfid",
                    "roadWidthMeter",
                    distance_m,
                    overlap_m
                FROM ranked
                WHERE rn = 1
                """,
                (FILTER_POLYGON_OVERLAP_BUFFER_M, FILTER_POLYGON_MATCH_M, FILTER_POLYGON_MATCH_M),
            )
            cur.execute('CREATE INDEX tmp_centerline_filter_source_match_edge ON tmp_centerline_filter_source_match ("edgeId")')
            cur.execute('CREATE INDEX tmp_centerline_filter_source_match_source ON tmp_centerline_filter_source_match ("sourceRowNumber")')
            cur.execute("SELECT COUNT(*) FROM tmp_centerline_filter_source_match")
            stats.matched_rows = int(cur.fetchone()[0])
            stats.unmatched_rows = max(road_segment_count - stats.matched_rows, 0)
            stats.loaded_rows = stats.matched_rows if dry_run else 0

            cur.execute(
                """
                SELECT
                    ROUND(MIN(distance_m)::numeric, 3),
                    ROUND(AVG(distance_m)::numeric, 3),
                    ROUND(MAX(distance_m)::numeric, 3),
                    ROUND(MIN(overlap_m)::numeric, 3),
                    ROUND(AVG(overlap_m)::numeric, 3),
                    ROUND(MAX(overlap_m)::numeric, 3)
                FROM tmp_centerline_filter_source_match
                """
            )
            row = cur.fetchone()
            stats.details["match_metric_stats"] = {
                "distance_meter": {"min": row[0], "avg": row[1], "max": row[2]},
                "overlap_meter": {"min": row[3], "avg": row[4], "max": row[5]},
            }
            cur.execute(
                """
                SELECT COUNT(*)
                FROM (
                    SELECT "sourceRowNumber"
                    FROM tmp_centerline_filter_source_match
                    GROUP BY "sourceRowNumber"
                    HAVING COUNT(*) > 1
                ) shared
                """
            )
            stats.details["shared_source_row_count"] = int(cur.fetchone()[0])
            cur.execute(
                """
                SELECT rs."edgeId"
                FROM road_segments rs
                LEFT JOIN tmp_centerline_filter_source_match m ON m."edgeId" = rs."edgeId"
                WHERE m."edgeId" IS NULL
                ORDER BY rs."edgeId"
                LIMIT 20
                """
            )
            stats.details["sample_unmatched_edge_ids"] = [int(row[0]) for row in cur.fetchall()]

            if not dry_run:
                cur.execute('TRUNCATE TABLE road_segment_filter_polygons')
                cur.execute(
                    """
                    INSERT INTO road_segment_filter_polygons (
                        "edgeId",
                        "sourceRowNumber",
                        "sourceUfid",
                        "roadWidthMeter",
                        "bufferHalfWidthMeter",
                        "geom"
                    )
                    SELECT
                        match."edgeId",
                        match."sourceRowNumber",
                        match."sourceUfid",
                        ROUND(match."roadWidthMeter"::numeric, 2),
                        ROUND(GREATEST(match."roadWidthMeter" / 2.0, %s)::numeric, 2),
                        ST_Multi(
                            ST_Buffer(
                                ST_Transform(rs."geom", 5179),
                                GREATEST(match."roadWidthMeter" / 2.0, %s),
                                'endcap=flat join=round'
                            )
                        )::geometry(MULTIPOLYGON, 5179)
                    FROM tmp_centerline_filter_source_match match
                    JOIN road_segments rs ON rs."edgeId" = match."edgeId"
                    """,
                    (FILTER_POLYGON_BUFFER_FLOOR_M, FILTER_POLYGON_BUFFER_FLOOR_M),
                )
                stats.loaded_rows = cur.rowcount
                cur.execute(
                    """
                    SELECT
                        COUNT(*),
                        COUNT(*) FILTER (WHERE NOT ST_IsValid("geom")),
                        COUNT(*) FILTER (WHERE ST_SRID("geom") <> 5179),
                        COUNT(*) FILTER (WHERE "roadWidthMeter" <= 0 OR "bufferHalfWidthMeter" <= 0)
                    FROM road_segment_filter_polygons
                    """
                )
                row = cur.fetchone()
                stats.details["table_validation"] = {
                    "row_count": int(row[0]),
                    "invalid_geometry_rows": int(row[1]),
                    "invalid_srid_rows": int(row[2]),
                    "non_positive_width_rows": int(row[3]),
                }
            else:
                stats.details["table_validation"] = {
                    "row_count": stats.matched_rows,
                    "invalid_geometry_rows": 0,
                    "invalid_srid_rows": 0,
                    "non_positive_width_rows": 0,
                }
        conn.commit()

    report = stats.asdict()
    write_report(
        REFERENCE_REPORT_DIR
        / ("road_segment_filter_polygons_dry_run_report.json" if dry_run else "road_segment_filter_polygons_load_report.json"),
        report,
    )
    return report


def load_continuous_width_surface(*, dry_run: bool = False) -> dict[str, Any]:
    layer_code = "N3L_A0033320"
    rows: list[tuple[int, str, str | None, float | None, str, str | None, str, str]] = []
    stats = LoadStats(details={"layer": layer_code, "source_dataset": CONTINUOUS_SOURCE_DATASET})
    source_row_number = 0
    for shp_path in _layer_paths(layer_code):
        district = shp_path.parents[1].name
        reader, encoding = open_shapefile(shp_path)
        fields = [field[0] for field in reader.fields[1:]]
        stats.details.setdefault("encodings", Counter())[encoding] += 1
        for shape_record in reader.iterShapeRecords():
            source_row_number += 1
            stats.source_rows += 1
            props = _record_to_dict(fields, shape_record.record)
            width = parse_optional_float(props.get("WIDT"))
            qual = props.get("QUAL")
            surface_state = surface_state_from_qual(qual)
            if width is None and surface_state == "UNKNOWN":
                stats.skipped_rows += 1
                continue
            try:
                wkt = shape_to_wkt_4326(shape_record.shape)
            except ValueError:
                stats.skipped_rows += 1
                continue
            rows.append(
                (
                    source_row_number,
                    district,
                    props.get("UFID") or None,
                    width,
                    surface_state,
                    qual,
                    _json_properties({**props, "district": district}),
                    wkt,
                )
            )
    if isinstance(stats.details.get("encodings"), Counter):
        stats.details["encodings"] = dict(stats.details["encodings"])
    stats.details["candidate_rows"] = len(rows)
    if dry_run:
        stats.loaded_rows = len(rows)
        report = stats.asdict()
        write_report(CONTINUOUS_REPORT_DIR / "continuous_width_surface_dry_run_report.json", report)
        return report

    ensure_reference_schema()
    with connect() as conn:
        with conn.cursor() as cur:
            reset_segment_feature_types(cur, ["WIDTH", "SURFACE"])
            cur.execute(
                "UPDATE road_segments SET \"widthMeter\" = NULL, \"widthState\" = 'UNKNOWN'::width_state, \"surfaceState\" = 'UNKNOWN'"
            )
            cur.execute(
                """
                CREATE TEMP TABLE tmp_n3l_a0033320 (
                    "sourceRowNumber" INTEGER,
                    "district" TEXT,
                    "ufid" TEXT,
                    "widthMeter" NUMERIC,
                    "surfaceState" TEXT,
                    "qual" TEXT,
                    "properties" JSONB,
                    "geom" GEOMETRY(GEOMETRY, 4326)
                ) ON COMMIT DROP
                """
            )
            cur.executemany(
                """
                INSERT INTO tmp_n3l_a0033320 (
                    "sourceRowNumber", "district", "ufid", "widthMeter",
                    "surfaceState", "qual", "properties", "geom"
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, ST_SetSRID(ST_MakeValid(ST_GeomFromText(%s)), 4326))
                """,
                rows,
            )
            cur.execute('CREATE INDEX tmp_n3l_a0033320_geom ON tmp_n3l_a0033320 USING GIST ("geom")')
            cur.execute("ANALYZE tmp_n3l_a0033320")
            cur.execute(
                """
                CREATE TEMP TABLE tmp_n3l_a0033320_match AS
                WITH raw AS (
                    SELECT
                        t.*,
                        rs."edgeId",
                        ST_Length(ST_Transform(ST_Intersection(rs."geom", t."geom"), 5179)) AS overlap_m,
                        NULLIF(ST_Length(ST_Transform(t."geom", 5179)), 0) AS feature_length_m,
                        ST_Distance(rs."geom"::geography, t."geom"::geography) AS distance_m
                    FROM tmp_n3l_a0033320 t
                    JOIN road_segments rs
                      ON rs."geom" && ST_Expand(t."geom", 0.00015)
                     AND ST_DWithin(rs."geom"::geography, t."geom"::geography, %s)
                ),
                ranked AS (
                    SELECT
                        *,
                        CASE
                            WHEN feature_length_m IS NOT NULL AND overlap_m > 0 THEN overlap_m / feature_length_m
                            ELSE 1.0 / (1.0 + distance_m)
                        END AS match_score,
                        ROW_NUMBER() OVER (
                            PARTITION BY "sourceRowNumber"
                            ORDER BY
                                CASE WHEN overlap_m > 0 THEN 0 ELSE 1 END ASC,
                                overlap_m DESC,
                                distance_m ASC,
                                "edgeId" ASC
                        ) AS rn
                    FROM raw
                    WHERE distance_m <= %s
                )
                SELECT *
                FROM ranked
                WHERE rn = 1
                  AND feature_length_m IS NOT NULL
                  AND overlap_m / feature_length_m >= %s
                """,
                (N3L_A0033320_AUTO_M, N3L_A0033320_AUTO_M, N3L_A0033320_OVERLAP_RATIO),
            )
            cur.execute('CREATE INDEX tmp_n3l_a0033320_match_edge ON tmp_n3l_a0033320_match ("edgeId")')
            cur.execute('SELECT COUNT(DISTINCT "sourceRowNumber") FROM tmp_n3l_a0033320_match')
            stats.matched_rows = int(cur.fetchone()[0])
            stats.unmatched_rows = len(rows) - stats.matched_rows

            cur.execute(
                """
                WITH best AS (
                    SELECT DISTINCT ON ("edgeId")
                        "edgeId", "widthMeter"
                    FROM tmp_n3l_a0033320_match
                    WHERE "widthMeter" IS NOT NULL AND "widthMeter" > 0
                    ORDER BY "edgeId", match_score DESC
                )
                UPDATE road_segments rs
                SET
                    "widthMeter" = best."widthMeter",
                    "widthState" = CASE
                        WHEN best."widthMeter" >= 1.5 THEN 'ADEQUATE_150'::width_state
                        WHEN best."widthMeter" >= 1.2 THEN 'ADEQUATE_120'::width_state
                        WHEN best."widthMeter" > 0 THEN 'NARROW'::width_state
                        ELSE 'UNKNOWN'::width_state
                    END
                FROM best
                WHERE rs."edgeId" = best."edgeId"
                """
            )
            stats.details["width_updated_segments"] = cur.rowcount
            cur.execute(
                """
                WITH best AS (
                    SELECT DISTINCT ON ("edgeId")
                        "edgeId", "surfaceState"
                    FROM tmp_n3l_a0033320_match
                    WHERE "surfaceState" <> 'UNKNOWN'
                    ORDER BY "edgeId", match_score DESC
                )
                UPDATE road_segments rs
                SET "surfaceState" = best."surfaceState"
                FROM best
                WHERE rs."edgeId" = best."edgeId"
                """
            )
            stats.details["surface_updated_segments"] = cur.rowcount
            cur.execute(
                """
                INSERT INTO segment_features (
                    "edgeId", "featureType", "geom", "sourceDataset", "sourceLayer",
                    "sourceRowNumber", "matchStatus", "matchScore", "properties"
                )
                SELECT
                    "edgeId", 'WIDTH', "geom", %s, %s,
                    "sourceRowNumber", 'MATCHED', match_score, "properties"
                FROM tmp_n3l_a0033320_match
                WHERE "widthMeter" IS NOT NULL AND "widthMeter" > 0
                """,
                (CONTINUOUS_SOURCE_DATASET, layer_code),
            )
            width_features = cur.rowcount
            cur.execute(
                """
                INSERT INTO segment_features (
                    "edgeId", "featureType", "geom", "sourceDataset", "sourceLayer",
                    "sourceRowNumber", "matchStatus", "matchScore", "properties"
                )
                SELECT
                    "edgeId", 'SURFACE', "geom", %s, %s,
                    "sourceRowNumber", 'MATCHED', match_score, "properties"
                FROM tmp_n3l_a0033320_match
                WHERE "qual" IS NOT NULL AND "qual" <> ''
                """,
                (CONTINUOUS_SOURCE_DATASET, layer_code),
            )
            surface_features = cur.rowcount
            stats.loaded_rows = width_features + surface_features
            stats.details["width_features"] = width_features
            stats.details["surface_features"] = surface_features
        conn.commit()
    report = stats.asdict()
    write_report(CONTINUOUS_REPORT_DIR / "continuous_width_surface_load_report.json", report)
    return report


def load_continuous_stairs(*, dry_run: bool = False) -> dict[str, Any]:
    layer_code = "N3A_C0390000"
    rows: list[tuple[int, str, str | None, str | None, str, str]] = []
    stats = LoadStats(details={"layer": layer_code, "source_dataset": CONTINUOUS_SOURCE_DATASET})
    source_row_number = 0
    stand_rows = 0
    for shp_path in _layer_paths(layer_code):
        district = shp_path.parents[1].name
        reader, encoding = open_shapefile(shp_path)
        fields = [field[0] for field in reader.fields[1:]]
        stats.details.setdefault("encodings", Counter())[encoding] += 1
        for shape_record in reader.iterShapeRecords():
            source_row_number += 1
            stats.source_rows += 1
            props = _record_to_dict(fields, shape_record.record)
            if props.get("SCLS") != "C0393323" or props.get("STRU") != "SRD001":
                if props.get("STRU") == "SRD002":
                    stand_rows += 1
                stats.skipped_rows += 1
                continue
            try:
                wkt = shape_to_wkt_4326(shape_record.shape)
            except ValueError:
                stats.skipped_rows += 1
                continue
            rows.append((source_row_number, district, props.get("UFID") or None, props.get("STRU"), _json_properties({**props, "district": district}), wkt))
    if isinstance(stats.details.get("encodings"), Counter):
        stats.details["encodings"] = dict(stats.details["encodings"])
    stats.details["candidate_rows"] = len(rows)
    stats.details["stand_rows"] = stand_rows
    if dry_run:
        stats.loaded_rows = len(rows)
        report = stats.asdict()
        write_report(CONTINUOUS_REPORT_DIR / "continuous_stairs_dry_run_report.json", report)
        return report

    ensure_reference_schema()
    with connect() as conn:
        with conn.cursor() as cur:
            reset_segment_feature_types(cur, ["STAIRS"])
            cur.execute('UPDATE road_segments SET "stairsState" = %s::yes_no_unknown', ("UNKNOWN",))
            cur.execute(
                """
                CREATE TEMP TABLE tmp_n3a_c0390000 (
                    "sourceRowNumber" INTEGER,
                    "district" TEXT,
                    "ufid" TEXT,
                    "stru" TEXT,
                    "properties" JSONB,
                    "geom" GEOMETRY(GEOMETRY, 4326)
                ) ON COMMIT DROP
                """
            )
            cur.executemany(
                """
                INSERT INTO tmp_n3a_c0390000 (
                    "sourceRowNumber", "district", "ufid", "stru", "properties", "geom"
                )
                VALUES (%s, %s, %s, %s, %s::jsonb, ST_SetSRID(ST_MakeValid(ST_GeomFromText(%s)), 4326))
                """,
                rows,
            )
            cur.execute('CREATE INDEX tmp_n3a_c0390000_geom ON tmp_n3a_c0390000 USING GIST ("geom")')
            cur.execute("ANALYZE tmp_n3a_c0390000")
            cur.execute(
                """
                CREATE TEMP TABLE tmp_n3a_c0390000_match AS
                WITH raw AS (
                    SELECT
                        t.*,
                        rs."edgeId",
                        ST_Distance(rs."geom"::geography, t."geom"::geography) AS distance_m
                    FROM tmp_n3a_c0390000 t
                    JOIN road_segments rs
                      ON rs."geom" && ST_Expand(t."geom", 0.00015)
                     AND ST_DWithin(rs."geom"::geography, t."geom"::geography, %s)
                ),
                ranked AS (
                    SELECT
                        *,
                        1.0 / (1.0 + distance_m) AS match_score,
                        ROW_NUMBER() OVER (
                            PARTITION BY "sourceRowNumber"
                            ORDER BY distance_m ASC, "edgeId" ASC
                        ) AS rn
                    FROM raw
                )
                SELECT *
                FROM ranked
                WHERE rn = 1
                """,
                (STAIRS_REVIEW_M,),
            )
            cur.execute('SELECT COUNT(*) FROM tmp_n3a_c0390000_match WHERE distance_m <= %s', (STAIRS_AUTO_M,))
            stats.matched_rows = int(cur.fetchone()[0])
            cur.execute(
                'SELECT COUNT(*) FROM tmp_n3a_c0390000_match WHERE distance_m > %s AND distance_m <= %s',
                (STAIRS_AUTO_M, STAIRS_REVIEW_M),
            )
            stats.review_rows = int(cur.fetchone()[0])
            stats.unmatched_rows = len(rows) - stats.matched_rows - stats.review_rows
            cur.execute(
                """
                UPDATE road_segments rs
                SET "stairsState" = 'YES'::yes_no_unknown
                FROM (
                    SELECT DISTINCT "edgeId"
                    FROM tmp_n3a_c0390000_match
                    WHERE distance_m <= %s
                ) best
                WHERE rs."edgeId" = best."edgeId"
                """,
                (STAIRS_AUTO_M,),
            )
            stats.details["stairs_updated_segments"] = cur.rowcount
            cur.execute(
                """
                INSERT INTO segment_features (
                    "edgeId", "featureType", "geom", "sourceDataset", "sourceLayer",
                    "sourceRowNumber", "matchStatus", "matchScore", "properties"
                )
                SELECT
                    "edgeId", 'STAIRS', "geom", %s, %s,
                    "sourceRowNumber", 'MATCHED', match_score, "properties"
                FROM tmp_n3a_c0390000_match
                WHERE distance_m <= %s
                """,
                (CONTINUOUS_SOURCE_DATASET, layer_code, STAIRS_AUTO_M),
            )
            stats.loaded_rows = cur.rowcount
        conn.commit()
    report = stats.asdict()
    write_report(CONTINUOUS_REPORT_DIR / "continuous_stairs_load_report.json", report)
    return report


def load_continuous_evidence_layers(*, dry_run: bool = False) -> dict[str, Any]:
    rows: list[tuple[int, str, str, str | None, str, str]] = []
    stats = LoadStats(details={"layers": list(CONTINUOUS_EVIDENCE_LAYERS), "source_dataset": CONTINUOUS_SOURCE_DATASET})
    per_layer: dict[str, dict[str, Any]] = {
        layer_code: {
            "source_rows": 0,
            "candidate_rows": 0,
            "matched_rows": 0,
            "review_rows": 0,
            "unmatched_rows": 0,
            "skipped_rows": 0,
            "loaded_rows": 0,
        }
        for layer_code in CONTINUOUS_EVIDENCE_LAYERS
    }
    source_row_number = 0
    encodings: Counter[str] = Counter()
    for layer_code in CONTINUOUS_EVIDENCE_LAYERS:
        for shp_path in _layer_paths(layer_code):
            district = shp_path.parents[1].name
            reader, encoding = open_shapefile(shp_path)
            encodings[encoding] += 1
            fields = [field[0] for field in reader.fields[1:]]
            for shape_record in reader.iterShapeRecords():
                source_row_number += 1
                stats.source_rows += 1
                per_layer[layer_code]["source_rows"] += 1
                props = _record_to_dict(fields, shape_record.record)
                try:
                    wkt = shape_to_wkt_4326(shape_record.shape)
                except ValueError:
                    stats.skipped_rows += 1
                    per_layer[layer_code]["skipped_rows"] += 1
                    continue
                per_layer[layer_code]["candidate_rows"] += 1
                rows.append(
                    (
                        source_row_number,
                        layer_code,
                        district,
                        props.get("UFID") or None,
                        _json_properties({**props, "district": district}),
                        wkt,
                    )
                )
    stats.details["encodings"] = dict(encodings)
    stats.details["candidate_rows"] = len(rows)
    if dry_run:
        stats.loaded_rows = len(rows)
        stats.details["per_layer"] = per_layer
        report = stats.asdict()
        write_report(CONTINUOUS_REPORT_DIR / "continuous_evidence_layers_dry_run_report.json", report)
        return report

    ensure_reference_schema()
    feature_types = [f"CONTINUOUS_MAP_{layer_code}" for layer_code in CONTINUOUS_EVIDENCE_LAYERS]
    with connect() as conn:
        with conn.cursor() as cur:
            reset_segment_feature_types(cur, feature_types)
            cur.execute(
                """
                CREATE TEMP TABLE tmp_continuous_evidence (
                    "sourceRowNumber" INTEGER,
                    "sourceLayer" TEXT,
                    "district" TEXT,
                    "ufid" TEXT,
                    "properties" JSONB,
                    "geom" GEOMETRY(GEOMETRY, 4326)
                ) ON COMMIT DROP
                """
            )
            cur.executemany(
                """
                INSERT INTO tmp_continuous_evidence (
                    "sourceRowNumber", "sourceLayer", "district", "ufid", "properties", "geom"
                )
                VALUES (%s, %s, %s, %s, %s::jsonb, ST_SetSRID(ST_MakeValid(ST_GeomFromText(%s)), 4326))
                """,
                rows,
            )
            cur.execute('CREATE INDEX tmp_continuous_evidence_geom ON tmp_continuous_evidence USING GIST ("geom")')
            cur.execute("ANALYZE tmp_continuous_evidence")
            cur.execute(
                """
                CREATE TEMP TABLE tmp_continuous_evidence_match AS
                WITH raw AS (
                    SELECT
                        t.*,
                        rs."edgeId",
                        ST_Distance(rs."geom"::geography, t."geom"::geography) AS distance_m
                    FROM tmp_continuous_evidence t
                    JOIN road_segments rs
                      ON rs."geom" && ST_Expand(t."geom", 0.00015)
                     AND ST_DWithin(rs."geom"::geography, t."geom"::geography, %s)
                ),
                ranked AS (
                    SELECT
                        *,
                        1.0 / (1.0 + distance_m) AS match_score,
                        ROW_NUMBER() OVER (
                            PARTITION BY "sourceRowNumber"
                            ORDER BY distance_m ASC, "edgeId" ASC
                        ) AS rn
                    FROM raw
                )
                SELECT *
                FROM ranked
                WHERE rn = 1
                """,
                (CONTINUOUS_EVIDENCE_REVIEW_M,),
            )
            cur.execute(
                """
                SELECT
                    "sourceLayer",
                    COUNT(*) FILTER (WHERE distance_m <= %s) AS matched,
                    COUNT(*) FILTER (WHERE distance_m > %s AND distance_m <= %s) AS review
                FROM tmp_continuous_evidence_match
                GROUP BY "sourceLayer"
                """,
                (CONTINUOUS_EVIDENCE_AUTO_M, CONTINUOUS_EVIDENCE_AUTO_M, CONTINUOUS_EVIDENCE_REVIEW_M),
            )
            for layer_code, matched, review in cur.fetchall():
                per_layer[layer_code]["matched_rows"] = int(matched)
                per_layer[layer_code]["review_rows"] = int(review)
            for layer_code, layer_stats in per_layer.items():
                layer_stats["unmatched_rows"] = (
                    layer_stats["candidate_rows"] - layer_stats["matched_rows"] - layer_stats["review_rows"]
                )
            stats.matched_rows = sum(layer_stats["matched_rows"] for layer_stats in per_layer.values())
            stats.review_rows = sum(layer_stats["review_rows"] for layer_stats in per_layer.values())
            stats.unmatched_rows = sum(layer_stats["unmatched_rows"] for layer_stats in per_layer.values())
            cur.execute(
                """
                INSERT INTO segment_features (
                    "edgeId", "featureType", "geom", "sourceDataset", "sourceLayer",
                    "sourceRowNumber", "matchStatus", "matchScore", "properties"
                )
                SELECT
                    "edgeId", 'CONTINUOUS_MAP_' || "sourceLayer", "geom", %s, "sourceLayer",
                    "sourceRowNumber", 'MATCHED', match_score, "properties"
                FROM tmp_continuous_evidence_match
                WHERE distance_m <= %s
                """,
                (CONTINUOUS_SOURCE_DATASET, CONTINUOUS_EVIDENCE_AUTO_M),
            )
            stats.loaded_rows = cur.rowcount
            cur.execute(
                """
                SELECT "sourceLayer", COUNT(*)
                FROM tmp_continuous_evidence_match
                WHERE distance_m <= %s
                GROUP BY "sourceLayer"
                """,
                (CONTINUOUS_EVIDENCE_AUTO_M,),
            )
            for layer_code, loaded in cur.fetchall():
                per_layer[layer_code]["loaded_rows"] = int(loaded)
        conn.commit()
    stats.details["per_layer"] = per_layer
    report = stats.asdict()
    write_report(CONTINUOUS_REPORT_DIR / "continuous_evidence_layers_load_report.json", report)
    return report


def load_slope_analysis(*, dry_run: bool = False) -> dict[str, Any]:
    rows, encoding, headers = read_csv_rows(SLOPE_ANALYSIS)
    stats = LoadStats(source_rows=len(rows), details={"encoding": encoding, "headers": headers})
    temp_rows: list[tuple[int, float | None, float | None, str, str]] = []
    for idx, row in enumerate(rows, start=1):
        geom = row.get("geometry_wkt_4326", "")
        if not geom:
            stats.skipped_rows += 1
            continue
        metric_mean = parse_optional_float(row.get("metric_mean"))
        width = parse_optional_float(row.get("width_meter"))
        if metric_mean is None and width is None:
            stats.skipped_rows += 1
            continue
        temp_rows.append((idx, metric_mean, width, _json_properties(row), geom))
    stats.details["candidate_rows"] = len(temp_rows)
    if dry_run:
        stats.loaded_rows = len(temp_rows)
        report = stats.asdict()
        write_report(REFERENCE_REPORT_DIR / "slope_analysis_dry_run_report.json", report)
        return report

    ensure_reference_schema()
    with connect() as conn:
        with conn.cursor() as cur:
            reset_segment_feature_types(cur, ["SLOPE_ANALYSIS"])
            cur.execute('UPDATE road_segments SET "avgSlopePercent" = NULL')
            cur.execute(
                """
                CREATE TEMP TABLE tmp_slope_analysis (
                    "sourceRowNumber" INTEGER,
                    "metricMean" NUMERIC,
                    "widthMeter" NUMERIC,
                    "properties" JSONB,
                    "geom" GEOMETRY(GEOMETRY, 4326)
                ) ON COMMIT DROP
                """
            )
            cur.executemany(
                """
                INSERT INTO tmp_slope_analysis (
                    "sourceRowNumber", "metricMean", "widthMeter", "properties", "geom"
                )
                VALUES (%s, %s, %s, %s::jsonb, ST_SetSRID(ST_MakeValid(ST_GeomFromText(%s)), 4326))
                """,
                temp_rows,
            )
            cur.execute('CREATE INDEX tmp_slope_analysis_geom ON tmp_slope_analysis USING GIST ("geom")')
            cur.execute("ANALYZE tmp_slope_analysis")
            cur.execute(
                """
                CREATE TEMP TABLE tmp_slope_analysis_match AS
                WITH raw AS (
                    SELECT
                        t.*,
                        rs."edgeId",
                        ST_Length(ST_Transform(ST_Intersection(rs."geom", t."geom"), 5179)) AS overlap_m,
                        NULLIF(rs."lengthMeter", 0) AS edge_length_m
                    FROM tmp_slope_analysis t
                    JOIN road_segments rs
                      ON rs."geom" && t."geom"
                     AND ST_Intersects(rs."geom", t."geom")
                ),
                ranked AS (
                    SELECT
                        *,
                        overlap_m / edge_length_m AS match_score,
                        ROW_NUMBER() OVER (
                            PARTITION BY "sourceRowNumber"
                            ORDER BY overlap_m DESC, "edgeId" ASC
                        ) AS rn
                    FROM raw
                    WHERE overlap_m > 0 AND edge_length_m IS NOT NULL
                )
                SELECT *
                FROM ranked
                WHERE rn = 1
                """
            )
            cur.execute('CREATE INDEX tmp_slope_analysis_match_edge ON tmp_slope_analysis_match ("edgeId")')
            cur.execute('SELECT COUNT(DISTINCT "sourceRowNumber") FROM tmp_slope_analysis_match WHERE match_score >= %s', (SLOPE_OVERLAP_RATIO,))
            stats.matched_rows = int(cur.fetchone()[0])
            cur.execute('SELECT COUNT(DISTINCT "sourceRowNumber") FROM tmp_slope_analysis_match WHERE match_score < %s', (SLOPE_OVERLAP_RATIO,))
            low_overlap_skipped = int(cur.fetchone()[0])
            stats.details["low_overlap_skipped"] = low_overlap_skipped
            stats.unmatched_rows = len(temp_rows) - stats.matched_rows - low_overlap_skipped
            cur.execute(
                """
                WITH agg AS (
                    SELECT
                        "edgeId",
                        AVG("metricMean") FILTER (WHERE "metricMean" IS NOT NULL) AS avg_metric,
                        AVG("widthMeter") FILTER (WHERE "widthMeter" IS NOT NULL AND "widthMeter" > 0) AS avg_width
                    FROM tmp_slope_analysis_match
                    WHERE match_score >= %s
                    GROUP BY "edgeId"
                )
                UPDATE road_segments rs
                SET
                    "avgSlopePercent" = ROUND(agg.avg_metric, 2),
                    "widthMeter" = CASE
                        WHEN rs."widthMeter" IS NULL AND agg.avg_width IS NOT NULL THEN ROUND(agg.avg_width, 2)
                        ELSE rs."widthMeter"
                    END,
                    "widthState" = CASE
                        WHEN rs."widthMeter" IS NULL AND agg.avg_width >= 1.5 THEN 'ADEQUATE_150'::width_state
                        WHEN rs."widthMeter" IS NULL AND agg.avg_width >= 1.2 THEN 'ADEQUATE_120'::width_state
                        WHEN rs."widthMeter" IS NULL AND agg.avg_width > 0 THEN 'NARROW'::width_state
                        ELSE rs."widthState"
                    END
                FROM agg
                WHERE rs."edgeId" = agg."edgeId"
                """,
                (SLOPE_OVERLAP_RATIO,),
            )
            stats.details["slope_updated_segments"] = cur.rowcount
            cur.execute(
                """
                INSERT INTO segment_features (
                    "edgeId", "featureType", "geom", "sourceDataset", "sourceLayer",
                    "sourceRowNumber", "matchStatus", "matchScore", "properties"
                )
                SELECT
                    "edgeId", 'SLOPE_ANALYSIS', "geom", %s, 'slope_analysis_staging',
                    "sourceRowNumber", 'MATCHED', match_score, "properties"
                FROM tmp_slope_analysis_match
                WHERE match_score >= %s
                """,
                (SLOPE_SOURCE_DATASET, SLOPE_OVERLAP_RATIO),
            )
            stats.loaded_rows = cur.rowcount
        conn.commit()
    report = stats.asdict()
    write_report(REFERENCE_REPORT_DIR / "slope_analysis_load_report.json", report)
    return report


def run_all(*, dry_run: bool = False) -> dict[str, Any]:
    if not dry_run:
        ensure_reference_schema()
    places_result = load_places(dry_run=dry_run)
    if not dry_run and places_result.get("loaded_rows", 0) == 0:
        raise RuntimeError("load_places loaded 0 rows — aborting run_all to prevent orphan FK errors")
    report = {
        "dry_run": dry_run,
        "places": places_result,
        "road_segment_filter_polygons": load_road_segment_filter_polygons(dry_run=dry_run),
        "place_accessibility_features": load_place_accessibility(dry_run=dry_run),
        "audio_signals": load_audio_signals(dry_run=dry_run),
        "crosswalks": load_crosswalks(dry_run=dry_run),
        "subway_elevators": load_subway_elevators(dry_run=dry_run),
        "low_floor_bus_routes": load_low_floor_bus_routes(dry_run=dry_run),
        "slope_analysis": load_slope_analysis(dry_run=dry_run),
        "continuous_map_manifest": continuous_map_manifest(),
        "continuous_width_surface": load_continuous_width_surface(dry_run=dry_run),
        "continuous_stairs": load_continuous_stairs(dry_run=dry_run),
        "continuous_evidence_layers": load_continuous_evidence_layers(dry_run=dry_run),
    }
    write_report(REFERENCE_REPORT_DIR / ("dry_run_report.json" if dry_run else "load_report.json"), report)
    return report


def db_counts() -> dict[str, int]:
    tables = [
        "places",
        "place_accessibility_features",
        "road_nodes",
        "road_segments",
        "road_segment_filter_polygons",
        "segment_features",
        "low_floor_bus_routes",
        "subway_station_elevators",
    ]
    counts: dict[str, int] = {}
    with connect() as conn:
        with conn.cursor() as cur:
            for table in tables:
                if not table_exists(cur, table):
                    counts[table] = 0
                    continue
                cur.execute(f'SELECT COUNT(*) FROM "{table}"')
                counts[table] = int(cur.fetchone()[0])
    return counts


def post_load_validate() -> dict[str, Any]:
    ensure_reference_schema()
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM place_accessibility_features paf
                LEFT JOIN places p ON p."placeId" = paf."placeId"
                WHERE p."placeId" IS NULL
                """
            )
            orphan_place_features = int(cur.fetchone()[0])
            cur.execute(
                """
                SELECT "featureType", COUNT(*)
                FROM segment_features
                GROUP BY "featureType"
                ORDER BY "featureType"
                """
            )
            segment_feature_counts = {row[0]: int(row[1]) for row in cur.fetchall()}
            cur.execute('SELECT COUNT(*) FROM road_segments WHERE "audioSignalState" = %s', ("YES",))
            audio_yes = int(cur.fetchone()[0])
            cur.execute('SELECT COUNT(*) FROM road_segments WHERE "crossingState" <> %s', ("UNKNOWN",))
            crossing_known = int(cur.fetchone()[0])
            cur.execute('SELECT COUNT(*) FROM road_segments WHERE "elevatorState" = %s', ("YES",))
            elevator_yes = int(cur.fetchone()[0])
            cur.execute('SELECT COUNT(*) FROM road_segments WHERE "avgSlopePercent" IS NOT NULL')
            avg_slope_known = int(cur.fetchone()[0])
            cur.execute('SELECT COUNT(*) FROM road_segments WHERE "widthMeter" IS NOT NULL')
            width_known = int(cur.fetchone()[0])
            cur.execute('SELECT COUNT(*) FROM road_segments WHERE "widthState" <> %s', ("UNKNOWN",))
            width_state_known = int(cur.fetchone()[0])
            cur.execute('SELECT COUNT(*) FROM road_segments WHERE "surfaceState" <> %s', ("UNKNOWN",))
            surface_state_known = int(cur.fetchone()[0])
            cur.execute('SELECT COUNT(*) FROM road_segments WHERE "stairsState" = %s', ("YES",))
            stairs_yes = int(cur.fetchone()[0])
            cur.execute(
                """
                SELECT COUNT(*)
                FROM segment_features sf
                LEFT JOIN road_segments rs ON rs."edgeId" = sf."edgeId"
                WHERE rs."edgeId" IS NULL
                """
            )
            orphan_segment_features = int(cur.fetchone()[0])
            cur.execute('SELECT COUNT(*) FROM segment_features WHERE "matchStatus" IS NULL')
            missing_match_status = int(cur.fetchone()[0])
            cur.execute(
                """
                SELECT
                    sf."featureId",
                    sf."edgeId",
                    sf."featureType",
                    sf."matchStatus",
                    ST_Intersects(rs."geom", sf."geom") AS intersects,
                    ROUND(ST_Distance(rs."geom"::geography, sf."geom"::geography)::numeric, 2) AS distance_m
                FROM segment_features sf
                JOIN road_segments rs ON rs."edgeId" = sf."edgeId"
                WHERE sf."featureType" IN (
                    'SLOPE_ANALYSIS',
                    'WIDTH',
                    'SURFACE',
                    'STAIRS',
                    'CONTINUOUS_MAP_N3A_A0063321',
                    'CONTINUOUS_MAP_N3A_A0070000',
                    'CONTINUOUS_MAP_N3A_A0080000',
                    'CONTINUOUS_MAP_N3A_A0110020',
                    'CONTINUOUS_MAP_N3L_A0123373'
                )
                ORDER BY sf."featureId"
                LIMIT 10
                """
            )
            sample_match_checks = [
                {
                    "featureId": int(row[0]),
                    "edgeId": int(row[1]),
                    "featureType": row[2],
                    "matchStatus": row[3],
                    "intersects": bool(row[4]),
                    "distanceMeter": float(row[5]),
                }
                for row in cur.fetchall()
            ]
            road_segment_filter_polygon_summary: dict[str, Any] | None = None
            if table_exists(cur, "road_segment_filter_polygons"):
                cur.execute(
                    """
                    SELECT
                        COUNT(*),
                        COUNT(*) FILTER (WHERE NOT ST_IsValid("geom")),
                        COUNT(*) FILTER (WHERE ST_SRID("geom") <> 5179),
                        COUNT(*) FILTER (WHERE "roadWidthMeter" <= 0 OR "bufferHalfWidthMeter" <= 0)
                    FROM road_segment_filter_polygons
                    """
                )
                row = cur.fetchone()
                cur.execute(
                    """
                    SELECT COUNT(*)
                    FROM road_segment_filter_polygons rp
                    LEFT JOIN road_segments rs ON rs."edgeId" = rp."edgeId"
                    WHERE rs."edgeId" IS NULL
                    """
                )
                road_segment_filter_polygon_summary = {
                    "row_count": int(row[0]),
                    "invalid_geometry_rows": int(row[1]),
                    "invalid_srid_rows": int(row[2]),
                    "non_positive_width_rows": int(row[3]),
                    "orphan_edge_rows": int(cur.fetchone()[0]),
                }
    report = {
        "counts": db_counts(),
        "orphan_place_accessibility_features": orphan_place_features,
        "orphan_segment_features": orphan_segment_features,
        "segment_features_missing_match_status": missing_match_status,
        "road_segment_filter_polygons": road_segment_filter_polygon_summary,
        "sample_match_checks": sample_match_checks,
        "segment_feature_counts": segment_feature_counts,
        "road_segment_state_counts": {
            "audioSignalState_yes": audio_yes,
            "crossingState_known": crossing_known,
            "elevatorState_yes": elevator_yes,
            "avgSlopePercent_known": avg_slope_known,
            "widthMeter_known": width_known,
            "widthState_known": width_state_known,
            "surfaceState_known": surface_state_known,
            "stairsState_yes": stairs_yes,
        },
    }
    write_report(REFERENCE_REPORT_DIR / "post_load_validate.json", report)
    if orphan_place_features:
        raise RuntimeError(f"orphan place accessibility rows: {orphan_place_features}")
    if orphan_segment_features:
        raise RuntimeError(f"orphan segment feature rows: {orphan_segment_features}")
    if missing_match_status:
        raise RuntimeError(f"segment feature rows missing matchStatus: {missing_match_status}")
    if road_segment_filter_polygon_summary is not None:
        if road_segment_filter_polygon_summary["invalid_geometry_rows"]:
            raise RuntimeError(
                f'road_segment_filter_polygons invalid geometries: {road_segment_filter_polygon_summary["invalid_geometry_rows"]}'
            )
        if road_segment_filter_polygon_summary["invalid_srid_rows"]:
            raise RuntimeError(
                f'road_segment_filter_polygons invalid SRID rows: {road_segment_filter_polygon_summary["invalid_srid_rows"]}'
            )
        if road_segment_filter_polygon_summary["orphan_edge_rows"]:
            raise RuntimeError(
                f'road_segment_filter_polygons orphan edges: {road_segment_filter_polygon_summary["orphan_edge_rows"]}'
            )
    return report
