from __future__ import annotations

import csv
import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any


POC_ROOT = Path(__file__).resolve().parents[1]
DATA_ADOPTED = POC_ROOT / "data" / "adopted"
ASSETS_DATA = POC_ROOT / "assets" / "data"
REPORT_DIR = POC_ROOT / "data" / "reports" / "facility_validation"
ARCHIVE_DIR = POC_ROOT / "archive" / "20260427_toilet_review_needed_decisions_before"

ADOPTED_ALL = DATA_ADOPTED / "adopted_places_with_accessibility.csv"
ADOPTED_PLACES = DATA_ADOPTED / "adopted_places.csv"
ADOPTED_ACCESSIBILITY = DATA_ADOPTED / "adopted_place_accessibility.csv"
ERD_PLACES = DATA_ADOPTED / "places_erd.csv"
ERD_ACCESSIBILITY = DATA_ADOPTED / "place_accessibility_features_erd.csv"
FACILITIES_JS = ASSETS_DATA / "facilities-data.js"
ACCESSIBILITY_SUMMARY_JS = ASSETS_DATA / "accessibility-summary-data.js"

PLAN_CSV = REPORT_DIR / "toilet_review_needed_policy_plan.csv"
OUT_APPLIED = REPORT_DIR / "toilet_review_needed_decisions_applied.csv"
OUT_REMOVED = REPORT_DIR / "toilet_review_needed_decisions_removed.csv"
OUT_SUMMARY = REPORT_DIR / "toilet_review_needed_decisions_summary.json"

ERD_FEATURE_TYPES = ("ramp", "autoDoor", "elevator", "accessibleToilet", "chargingStation", "stepFree")
ERD_ACCESSIBILITY_LABELS = {
    "ramp": "경사로",
    "autoDoor": "자동문",
    "elevator": "엘리베이터",
    "accessibleToilet": "전용 화장실",
    "chargingStation": "전동보장구 충전",
    "stepFree": "단차 없음",
}

USER_REMOVE_NAMES = {
    "올드머그",
    "우호적무관심",
    "연산 해수피아",
    "태종아리랑",
    "개금다락방",
    "연밭",
    "죽순",
    "월내2",
    "이동1",
    "동백1",
}

MANUAL_FACILITY_TERMS = [
    "초소",
    "도서",
    "지소",
    "정수장",
    "양로원",
    "교육진흥원",
    "정거장",
    "도로환경팀",
    "위원회",
    "배드민턴장",
    "국제신문",
    "국세청",
    "선원",
    "고용노동지청",
    "영업소",
    "연수원",
    "연구소",
    "보건",
    "과학관",
    "장관청",
    "구장",
    "복합청사",
    "민원실",
    "운전면허시험장",
    "교육지원청",
    "노동지청",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def split_pipe(value: str) -> list[str]:
    return [item for item in (value or "").split("|") if item]


def append_pipe(value: str, item: str) -> str:
    values = split_pipe(value)
    if item not in values:
        values.append(item)
    return "|".join(values)


def backup_files(paths: list[Path]) -> None:
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    for path in paths:
        if not path.exists():
            continue
        destination = ARCHIVE_DIR / path.relative_to(POC_ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copy2(path, destination)


def load_plan() -> dict[str, dict[str, str]]:
    return {row["sourceKey"]: row for row in read_csv(PLAN_CSV)}


def manual_target_label(name: str) -> tuple[str, str]:
    for term in MANUAL_FACILITY_TERMS:
        if term in name:
            return "시설 내 화장실", f"수동 검토 후 시설 내부 화장실로 흡수: {term}"
    return "공중화장실", "수동 검토 후 공중화장실로 흡수"


def decide(row: dict[str, str], plan_row: dict[str, str]) -> tuple[str, str, str]:
    action = plan_row["proposedAction"]
    if action == "REMOVE_CANDIDATE":
        return "REMOVE", "", plan_row["proposedReason"]
    if action == "PROMOTE_PUBLIC_TOILET":
        return "KEEP", "공중화장실", plan_row["proposedReason"]
    if action == "PROMOTE_FACILITY_TOILET":
        return "KEEP", "시설 내 화장실", plan_row["proposedReason"]
    if action == "MANUAL_REVIEW" and row["name"] in USER_REMOVE_NAMES:
        return "REMOVE", "", "사용자 수동 검토 결과 제거"
    if action == "MANUAL_REVIEW":
        label, reason = manual_target_label(row["name"])
        return "KEEP", label, reason
    return "KEEP", row.get("toiletScopeLabel") or row.get("facilityCategory") or "화장실", "기존 분류 유지"


def update_adopted_all(plan: dict[str, dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, Any]]]:
    rows = read_csv(ADOPTED_ALL)
    fieldnames = list(rows[0].keys())
    for extra in ["toiletScope", "toiletScopeLabel", "toiletScopeReason"]:
        if extra not in fieldnames:
            fieldnames.append(extra)

    kept: list[dict[str, str]] = []
    removed: list[dict[str, str]] = []
    applied: list[dict[str, Any]] = []

    for row in rows:
        plan_row = plan.get(row["sourceKey"])
        if row["dbCategory"] != "TOILET" or row.get("toiletScope") != "REVIEW_TOILET" or not plan_row:
            kept.append(row)
            continue

        decision, label, reason = decide(row, plan_row)
        applied.append(
            {
                "sourceKey": row["sourceKey"],
                "placeIdBefore": row["placeId"],
                "name": row["name"],
                "districtGu": row["districtGu"],
                "address": row["address"],
                "planAction": plan_row["proposedAction"],
                "finalDecision": decision,
                "finalLabel": label,
                "finalReason": reason,
            }
        )

        if decision == "REMOVE":
            out = dict(row)
            out["removeReason"] = reason
            out["planAction"] = plan_row["proposedAction"]
            removed.append(out)
            continue

        row["toiletScope"] = "PUBLIC_TOILET" if label == "공중화장실" else "FACILITY_TOILET"
        row["toiletScopeLabel"] = label
        row["toiletScopeReason"] = reason
        row["facilityCategory"] = label
        row["uiCategory"] = label
        row["reviewFlags"] = append_pipe(row.get("reviewFlags", ""), "toilet_review_needed_decision_applied")
        row["reviewReasons"] = append_pipe(row.get("reviewReasons", ""), reason)
        kept.append(row)

    for idx, row in enumerate(kept, start=1):
        row["placeId"] = str(idx)

    write_csv(ADOPTED_ALL, kept, fieldnames)
    return kept, removed, applied


def update_adopted_places(kept_rows: list[dict[str, str]]) -> None:
    by_key = {row["sourceKey"]: row for row in kept_rows}
    rows = read_csv(ADOPTED_PLACES)
    fieldnames = list(rows[0].keys())
    for extra in ["toilet_scope", "toilet_scope_label", "toilet_scope_reason"]:
        if extra not in fieldnames:
            fieldnames.append(extra)

    out_rows: list[dict[str, str]] = []
    for row in rows:
        adopted = by_key.get(row["place_key"])
        if not adopted:
            continue
        row["ui_category"] = adopted["uiCategory"]
        row["toilet_scope"] = adopted.get("toiletScope", "")
        row["toilet_scope_label"] = adopted.get("toiletScopeLabel", "")
        row["toilet_scope_reason"] = adopted.get("toiletScopeReason", "")
        out_rows.append(row)
    write_csv(ADOPTED_PLACES, out_rows, fieldnames)


def update_adopted_accessibility(kept_rows: list[dict[str, str]]) -> None:
    by_key = {row["sourceKey"]: row for row in kept_rows}
    rows = read_csv(ADOPTED_ACCESSIBILITY)
    fieldnames = list(rows[0].keys())
    out_rows: list[dict[str, str]] = []
    for row in rows:
        adopted = by_key.get(row["place_key"])
        if not adopted:
            continue
        row["ui_category"] = adopted["uiCategory"]
        out_rows.append(row)
    write_csv(ADOPTED_ACCESSIBILITY, out_rows, fieldnames)


def write_erd(kept_rows: list[dict[str, str]]) -> None:
    place_rows = [
        {
            "placeId": row["placeId"],
            "name": row["name"],
            "category": row["dbCategory"],
            "address": row["address"],
            "point": row["point"],
            "providerPlaceId": row["providerPlaceId"],
        }
        for row in kept_rows
    ]
    write_csv(ERD_PLACES, place_rows, ["placeId", "name", "category", "address", "point", "providerPlaceId"])

    feature_rows: list[dict[str, str]] = []
    next_id = 1
    for row in kept_rows:
        for feature_type in split_pipe(row.get("erdAccessibilityTypes", "")):
            feature_rows.append(
                {
                    "id": str(next_id),
                    "placeId": row["placeId"],
                    "featureType": feature_type,
                    "isAvailable": "true",
                }
            )
            next_id += 1
    write_csv(ERD_ACCESSIBILITY, feature_rows, ["id", "placeId", "featureType", "isAvailable"])


def load_facilities_geojson() -> dict[str, Any]:
    text = FACILITIES_JS.read_text(encoding="utf-8").strip()
    prefix = "window.FACILITIES_GEOJSON = "
    if not text.startswith(prefix):
        raise ValueError("Unexpected facilities JS format")
    if text.endswith(";"):
        text = text[:-1]
    return json.loads(text[len(prefix) :])


def update_facilities_js(kept_rows: list[dict[str, str]]) -> None:
    by_key = {row["sourceKey"]: row for row in kept_rows}
    geojson = load_facilities_geojson()
    features = []
    for feature in geojson["features"]:
        props = feature["properties"]
        adopted = by_key.get(props.get("sourceId", ""))
        if not adopted:
            continue
        props["placeId"] = adopted["placeId"]
        props["facilityCategory"] = adopted["facilityCategory"]
        props["uiCategory"] = adopted["uiCategory"]
        props["displaySource"] = adopted["facilityCategory"]
        props["toiletScope"] = adopted.get("toiletScope", "")
        props["toiletScopeLabel"] = adopted.get("toiletScopeLabel", "")
        props["toiletScopeReason"] = adopted.get("toiletScopeReason", "")
        if adopted["dbCategory"] == "TOILET":
            flags = props.get("reviewFlags", [])
            if isinstance(flags, list) and "toilet_review_needed_decision_applied" not in flags:
                flags.append("toilet_review_needed_decision_applied")
                props["reviewFlags"] = flags
            reason = adopted.get("toiletScopeReason", "")
            reasons = props.get("reviewReasons", [])
            if isinstance(reasons, list) and reason and reason not in reasons:
                reasons.append(reason)
                props["reviewReasons"] = reasons
        features.append(feature)
    geojson["features"] = features
    FACILITIES_JS.write_text(
        "window.FACILITIES_GEOJSON = "
        + json.dumps(geojson, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )


def write_accessibility_summary(kept_rows: list[dict[str, str]]) -> None:
    counter: Counter[str] = Counter()
    places_with_access = 0
    for row in kept_rows:
        values = split_pipe(row.get("erdAccessibilityTypes", ""))
        if values:
            places_with_access += 1
            counter.update(values)
    summary = {
        "totalRows": sum(counter.values()),
        "totalPlaces": places_with_access,
        "items": [
            {"featureType": key, "label": ERD_ACCESSIBILITY_LABELS.get(key, key), "count": counter[key]}
            for key in sorted(counter.keys(), key=lambda item: counter[item], reverse=True)
        ],
        "availableFeatureTypes": [
            {"featureType": key, "label": ERD_ACCESSIBILITY_LABELS.get(key, key), "count": counter[key]}
            for key in ERD_FEATURE_TYPES
        ],
    }
    ACCESSIBILITY_SUMMARY_JS.write_text(
        "window.ACCESSIBILITY_SUMMARY = "
        + json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )


def main() -> None:
    plan = load_plan()
    affected = [
        ADOPTED_ALL,
        ADOPTED_PLACES,
        ADOPTED_ACCESSIBILITY,
        ERD_PLACES,
        ERD_ACCESSIBILITY,
        FACILITIES_JS,
        ACCESSIBILITY_SUMMARY_JS,
    ]
    backup_files(affected)

    before_rows = read_csv(ADOPTED_ALL)
    before_toilets = [row for row in before_rows if row["dbCategory"] == "TOILET"]

    kept_rows, removed, applied = update_adopted_all(plan)
    update_adopted_places(kept_rows)
    update_adopted_accessibility(kept_rows)
    write_erd(kept_rows)
    update_facilities_js(kept_rows)
    write_accessibility_summary(kept_rows)

    write_csv(
        OUT_APPLIED,
        applied,
        [
            "sourceKey",
            "placeIdBefore",
            "name",
            "districtGu",
            "address",
            "planAction",
            "finalDecision",
            "finalLabel",
            "finalReason",
        ],
    )
    write_csv(
        OUT_REMOVED,
        [
            {
                "sourceKey": row["sourceKey"],
                "sourceDataset": row["sourceDataset"],
                "placeIdBefore": row["placeId"],
                "name": row["name"],
                "districtGu": row["districtGu"],
                "address": row["address"],
                "planAction": row.get("planAction", ""),
                "removeReason": row.get("removeReason", ""),
            }
            for row in removed
        ],
        ["sourceKey", "sourceDataset", "placeIdBefore", "name", "districtGu", "address", "planAction", "removeReason"],
    )

    after_toilets = [row for row in kept_rows if row["dbCategory"] == "TOILET"]
    summary = {
        "before": {
            "places": len(before_rows),
            "toilets": len(before_toilets),
            "toiletScopeLabels": dict(Counter(row.get("toiletScopeLabel", "") for row in before_toilets)),
        },
        "after": {
            "places": len(kept_rows),
            "toilets": len(after_toilets),
            "toiletScopeLabels": dict(Counter(row.get("toiletScopeLabel", "") for row in after_toilets)),
            "facilityCategoryCounts": dict(Counter(row["facilityCategory"] for row in kept_rows)),
        },
        "applied": dict(Counter(row["finalDecision"] for row in applied)),
        "appliedLabels": dict(Counter(row["finalLabel"] for row in applied if row["finalLabel"])),
        "removedCount": len(removed),
        "outputs": {"applied": str(OUT_APPLIED), "removed": str(OUT_REMOVED)},
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
