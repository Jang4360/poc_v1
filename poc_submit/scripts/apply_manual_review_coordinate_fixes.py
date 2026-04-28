#!/usr/bin/env python3
"""Apply manual-review coordinate fixes exported from the PoC map.

The map writes coordinate corrections as rows with status=FIX. This script
propagates those fixes to the facility CSV outputs and the map GeoJSON asset.
Run with --dry-run first when reviewing a newly exported file.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


BUSAN_LAT_RANGE = (34.8, 35.5)
BUSAN_LNG_RANGE = (128.6, 129.5)
GEOJSON_PREFIX = "window.FACILITIES_GEOJSON = "


@dataclass(frozen=True)
class CoordinateFix:
    key: str
    target_type: str
    target_id: str
    place_id: str
    source_key: str
    source_id: str
    name: str
    district_gu: str
    original_lat: str
    original_lng: str
    fixed_lat: float
    fixed_lng: float
    fixed_source: str
    fixed_source_url: str
    note: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply status=FIX coordinate rows from a manual_review_*.csv export."
    )
    parser.add_argument(
        "--review-csv",
        required=True,
        type=Path,
        help="Manual review CSV exported from index.html.",
    )
    parser.add_argument(
        "--root",
        default=Path(__file__).resolve().parents[1],
        type=Path,
        help="PoC root directory. Defaults to the parent of scripts/.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report changes without writing output files.",
    )
    return parser.parse_args()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return [], []
        return list(reader.fieldnames), [dict(row) for row in reader]


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def normalize(value: Any) -> str:
    return str(value or "").strip()


def parse_float(value: str, field: str, row_number: int) -> float:
    try:
        return float(normalize(value))
    except ValueError as exc:
        raise ValueError(f"{row_number}행 {field} 값이 숫자가 아닙니다: {value!r}") from exc


def validate_busan_coordinate(lat: float, lng: float, row_number: int) -> None:
    if not (BUSAN_LAT_RANGE[0] <= lat <= BUSAN_LAT_RANGE[1]):
        raise ValueError(f"{row_number}행 fixedLat이 부산 범위를 벗어납니다: {lat}")
    if not (BUSAN_LNG_RANGE[0] <= lng <= BUSAN_LNG_RANGE[1]):
        raise ValueError(f"{row_number}행 fixedLng이 부산 범위를 벗어납니다: {lng}")


def load_coordinate_fixes(review_csv: Path) -> list[CoordinateFix]:
    _, rows = read_csv(review_csv)
    fixes: list[CoordinateFix] = []
    seen_keys: set[str] = set()

    for index, row in enumerate(rows, start=2):
        status = normalize(row.get("status")).upper()
        target_type = normalize(row.get("targetType"))
        if status != "FIX":
            continue
        if target_type != "facility":
            # 계단은 아직 최종 seed 파일과 직접 연결하지 않는다. 필요하면 별도 파이프라인으로 분리한다.
            continue

        fixed_lat = parse_float(row.get("fixedLat", ""), "fixedLat", index)
        fixed_lng = parse_float(row.get("fixedLng", ""), "fixedLng", index)
        validate_busan_coordinate(fixed_lat, fixed_lng, index)

        key = normalize(row.get("key"))
        place_id = normalize(row.get("placeId"))
        source_key = normalize(row.get("sourceKey"))
        target_id = normalize(row.get("targetId"))
        source_id = normalize(row.get("sourceId"))
        dedupe_key = place_id or source_key or source_id or target_id or key
        if not dedupe_key:
            raise ValueError(f"{index}행은 매칭 가능한 키가 없습니다.")
        if dedupe_key in seen_keys:
            raise ValueError(f"{index}행 중복 수정 대상입니다: {dedupe_key}")
        seen_keys.add(dedupe_key)

        fixes.append(
            CoordinateFix(
                key=key,
                target_type=target_type,
                target_id=target_id,
                place_id=place_id,
                source_key=source_key,
                source_id=source_id,
                name=normalize(row.get("name")),
                district_gu=normalize(row.get("districtGu")),
                original_lat=normalize(row.get("lat")),
                original_lng=normalize(row.get("lng")),
                fixed_lat=fixed_lat,
                fixed_lng=fixed_lng,
                fixed_source=normalize(row.get("fixedSource")),
                fixed_source_url=normalize(row.get("fixedSourceUrl")),
                note=normalize(row.get("note")),
            )
        )

    return fixes


def point_wkt(lat: float, lng: float) -> str:
    return f"POINT({lng:.10f} {lat:.10f})"


def coord_text(value: float) -> str:
    return f"{value:.10f}".rstrip("0").rstrip(".")


def build_lookup(fixes: list[CoordinateFix]) -> dict[str, CoordinateFix]:
    lookup: dict[str, CoordinateFix] = {}
    for fix in fixes:
        keys = {
            fix.key,
            fix.target_id,
            fix.place_id,
            fix.source_key,
            fix.source_id,
        }
        if fix.place_id:
            keys.add(f"placeId:{fix.place_id}")
            keys.add(f"facility:{fix.place_id}")
        if fix.source_key:
            keys.add(f"facility:{fix.source_key}")
        for key in {normalize(item) for item in keys if normalize(item)}:
            lookup[key] = fix
    return lookup


def find_fix(row: dict[str, str], lookup: dict[str, CoordinateFix], candidate_fields: list[str]) -> CoordinateFix | None:
    candidates: list[str] = []
    for field in candidate_fields:
        value = normalize(row.get(field))
        if value:
            candidates.append(value)
            candidates.append(f"{field}:{value}")
            if field == "placeId":
                candidates.append(f"facility:{value}")
            if field in {"sourceKey", "place_key"}:
                candidates.append(f"facility:{value}")
    for candidate in candidates:
        fix = lookup.get(candidate)
        if fix:
            return fix
    return None


def apply_csv_updates(
    path: Path,
    lookup: dict[str, CoordinateFix],
    candidate_fields: list[str],
    lat_field: str | None,
    lng_field: str | None,
    point_field: str | None,
    dry_run: bool,
) -> list[dict[str, str]]:
    if not path.exists():
        return []

    fieldnames, rows = read_csv(path)
    changes: list[dict[str, str]] = []
    changed = False

    for row in rows:
        fix = find_fix(row, lookup, candidate_fields)
        if not fix:
            continue

        before_lat = normalize(row.get(lat_field)) if lat_field else ""
        before_lng = normalize(row.get(lng_field)) if lng_field else ""
        before_point = normalize(row.get(point_field)) if point_field else ""

        if lat_field and lat_field in row:
            row[lat_field] = coord_text(fix.fixed_lat)
        if lng_field and lng_field in row:
            row[lng_field] = coord_text(fix.fixed_lng)
        if point_field and point_field in row:
            row[point_field] = point_wkt(fix.fixed_lat, fix.fixed_lng)

        after_lat = normalize(row.get(lat_field)) if lat_field else ""
        after_lng = normalize(row.get(lng_field)) if lng_field else ""
        after_point = normalize(row.get(point_field)) if point_field else ""
        changed = True
        changes.append(
            {
                "file": str(path),
                "matchedBy": ",".join(candidate_fields),
                "placeId": fix.place_id,
                "sourceKey": fix.source_key,
                "sourceId": fix.source_id,
                "name": fix.name,
                "beforeLat": before_lat,
                "beforeLng": before_lng,
                "beforePoint": before_point,
                "afterLat": after_lat,
                "afterLng": after_lng,
                "afterPoint": after_point,
                "fixedSource": fix.fixed_source,
                "fixedSourceUrl": fix.fixed_source_url,
                "note": fix.note,
            }
        )

    if changed and not dry_run:
        write_csv(path, fieldnames, rows)
    return changes


def load_facilities_geojson(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    if not text.startswith(GEOJSON_PREFIX):
        raise ValueError(f"{path} 형식이 예상과 다릅니다.")
    json_text = text[len(GEOJSON_PREFIX) :].strip()
    if json_text.endswith(";"):
        json_text = json_text[:-1]
    return json.loads(json_text)


def write_facilities_geojson(path: Path, data: dict[str, Any]) -> None:
    json_text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    path.write_text(f"{GEOJSON_PREFIX}{json_text};\n", encoding="utf-8")


def geojson_feature_keys(properties: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    for field in ("placeId", "sourceId", "sourceKey", "providerPlaceId"):
        value = normalize(properties.get(field))
        if value:
            keys.append(value)
            keys.append(f"{field}:{value}")
            if field == "placeId":
                keys.append(f"facility:{value}")
            if field in {"sourceId", "sourceKey"}:
                keys.append(f"facility:{value}")
    return keys


def update_facilities_geojson(path: Path, lookup: dict[str, CoordinateFix], dry_run: bool) -> list[dict[str, str]]:
    if not path.exists():
        return []

    data = load_facilities_geojson(path)
    changes: list[dict[str, str]] = []

    for feature in data.get("features", []):
        properties = feature.get("properties") or {}
        fix = next((lookup.get(key) for key in geojson_feature_keys(properties) if lookup.get(key)), None)
        if not fix:
            continue

        geometry = feature.setdefault("geometry", {"type": "Point", "coordinates": []})
        before = geometry.get("coordinates") or []
        before_lng = str(before[0]) if len(before) > 0 else ""
        before_lat = str(before[1]) if len(before) > 1 else ""
        geometry["type"] = "Point"
        geometry["coordinates"] = [fix.fixed_lng, fix.fixed_lat]

        properties["manualFixedLat"] = coord_text(fix.fixed_lat)
        properties["manualFixedLng"] = coord_text(fix.fixed_lng)
        properties["manualFixedSource"] = fix.fixed_source
        if "lat" in properties:
            properties["lat"] = fix.fixed_lat
        if "lng" in properties:
            properties["lng"] = fix.fixed_lng
        if "point" in properties:
            properties["point"] = point_wkt(fix.fixed_lat, fix.fixed_lng)

        changes.append(
            {
                "file": str(path),
                "matchedBy": "geojson.properties",
                "placeId": fix.place_id,
                "sourceKey": fix.source_key,
                "sourceId": fix.source_id,
                "name": fix.name,
                "beforeLat": before_lat,
                "beforeLng": before_lng,
                "beforePoint": "",
                "afterLat": coord_text(fix.fixed_lat),
                "afterLng": coord_text(fix.fixed_lng),
                "afterPoint": "",
                "fixedSource": fix.fixed_source,
                "fixedSourceUrl": fix.fixed_source_url,
                "note": fix.note,
            }
        )

    if changes and not dry_run:
        write_facilities_geojson(path, data)
    return changes


def write_report(root: Path, changes: list[dict[str, str]], dry_run: bool) -> Path:
    report_dir = root / "data" / "reports" / "manual_review"
    report_dir.mkdir(parents=True, exist_ok=True)
    suffix = "dry_run" if dry_run else "applied"
    report_path = report_dir / f"manual_review_coordinate_fix_{suffix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    fieldnames = [
        "file",
        "matchedBy",
        "placeId",
        "sourceKey",
        "sourceId",
        "name",
        "beforeLat",
        "beforeLng",
        "beforePoint",
        "afterLat",
        "afterLng",
        "afterPoint",
        "fixedSource",
        "fixedSourceUrl",
        "note",
    ]
    write_csv(report_path, fieldnames, changes)
    return report_path


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    review_csv = args.review_csv.resolve()
    fixes = load_coordinate_fixes(review_csv)
    if not fixes:
        print("적용할 시설 좌표 수정(status=FIX, targetType=facility)이 없습니다.")
        return 0

    lookup = build_lookup(fixes)
    changes: list[dict[str, str]] = []
    csv_targets = [
        (
            root / "data" / "adopted" / "adopted_places_with_accessibility.csv",
            ["placeId", "sourceKey", "sourceId"],
            "lat",
            "lng",
            "point",
        ),
        (
            root / "data" / "final" / "facilities" / "adopted_places_with_accessibility_final.csv",
            ["placeId", "sourceKey", "sourceId"],
            "lat",
            "lng",
            "point",
        ),
        (
            root / "data" / "adopted" / "places_erd.csv",
            ["placeId", "providerPlaceId"],
            None,
            None,
            "point",
        ),
        (
            root / "data" / "final" / "facilities" / "places_erd.csv",
            ["placeId", "providerPlaceId"],
            None,
            None,
            "point",
        ),
        (
            root / "data" / "adopted" / "adopted_places.csv",
            ["place_key", "source_place_id", "provider_place_id"],
            "latitude",
            "longitude",
            "point_wkt",
        ),
        (
            root / "data" / "final" / "facilities" / "adopted_places_final.csv",
            ["place_key", "source_place_id", "provider_place_id"],
            "latitude",
            "longitude",
            "point_wkt",
        ),
    ]

    for path, candidate_fields, lat_field, lng_field, point_field in csv_targets:
        changes.extend(
            apply_csv_updates(
                path,
                lookup,
                candidate_fields,
                lat_field,
                lng_field,
                point_field,
                args.dry_run,
            )
        )

    changes.extend(
        update_facilities_geojson(
            root / "assets" / "data" / "facilities-data.js",
            lookup,
            args.dry_run,
        )
    )

    report_path = write_report(root, changes, args.dry_run)
    matched_fix_ids = {change["placeId"] or change["sourceKey"] or change["sourceId"] for change in changes}
    unmatched = [
        fix for fix in fixes if (fix.place_id or fix.source_key or fix.source_id) not in matched_fix_ids
    ]

    print(f"수정 요청: {len(fixes)}건")
    print(f"파일 반영 행/피처: {len(changes)}건")
    print(f"보고서: {report_path}")
    if unmatched:
        print(f"주의: 산출물에서 매칭되지 않은 수정 대상 {len(unmatched)}건")
        for fix in unmatched[:20]:
            print(f"  - {fix.name} placeId={fix.place_id} sourceKey={fix.source_key} sourceId={fix.source_id}")
    if args.dry_run:
        print("dry-run 모드라 실제 CSV/JS 파일은 변경하지 않았습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
