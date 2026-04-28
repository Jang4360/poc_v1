from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from etl.common import segment_graph_candidate_review_ui, segment_graph_db


DEFAULT_TRAINING_BBOX = (128.815, 35.055, 128.93, 35.135)
DEFAULT_OUTPUT_DIR = segment_graph_db.ROOT_DIR / "runtime" / "etl" / "gangseo-auto-edit"
DEFAULT_REVIEW_HTML = DEFAULT_OUTPUT_DIR / "gangseo_02c_auto_candidate_review.html"
DEFAULT_APPROVED_JSON = DEFAULT_OUTPUT_DIR / "gangseo_02c_approved_manual_edits.json"


def _percentile(values: list[float], ratio: float, default: float) -> float:
    if not values:
        return default
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * ratio))))
    return float(ordered[index])


def _iter_edit_coords(edit: dict[str, Any]) -> list[list[float]]:
    geometry = edit.get("geom") or {}
    coords = geometry.get("coordinates") or []
    if geometry.get("type") == "Point":
        return [[float(coords[0]), float(coords[1])]]
    if geometry.get("type") == "LineString":
        return [[float(lng), float(lat)] for lng, lat in coords]
    return []


def _bbox_from_coords(coords: list[list[float]]) -> tuple[float, float, float, float] | None:
    if not coords:
        return None
    lons = [coord[0] for coord in coords]
    lats = [coord[1] for coord in coords]
    return (min(lons), min(lats), max(lons), max(lats))


def _expand_bbox(
    bbox: tuple[float, float, float, float],
    *,
    padding_degree: float = 0.001,
) -> tuple[float, float, float, float]:
    return (
        bbox[0] - padding_degree,
        bbox[1] - padding_degree,
        bbox[2] + padding_degree,
        bbox[3] + padding_degree,
    )


def _point_in_bbox(coord: list[float], bbox: tuple[float, float, float, float]) -> bool:
    min_lon, min_lat, max_lon, max_lat = bbox
    return min_lon <= coord[0] <= max_lon and min_lat <= coord[1] <= max_lat


def _geometry_in_bbox(geometry: dict[str, Any], bbox: tuple[float, float, float, float]) -> bool:
    geometry_bbox = _geometry_bbox(geometry)
    return _bbox_intersects(geometry_bbox, bbox) if geometry_bbox else False


def _geometry_bbox(geometry: dict[str, Any]) -> tuple[float, float, float, float] | None:
    coords = geometry.get("coordinates") or []
    if geometry.get("type") == "Point":
        return _bbox_from_coords([[float(coords[0]), float(coords[1])]])
    if geometry.get("type") == "LineString":
        return _bbox_from_coords([[float(lng), float(lat)] for lng, lat in coords])
    return None


def _bbox_intersects(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> bool:
    return not (left[2] < right[0] or right[2] < left[0] or left[3] < right[1] or right[3] < left[1])


def _bbox_to_dict(bbox: tuple[float, float, float, float]) -> dict[str, float]:
    return {
        "minLon": bbox[0],
        "minLat": bbox[1],
        "maxLon": bbox[2],
        "maxLat": bbox[3],
    }


def _dict_to_bbox(value: dict[str, Any]) -> tuple[float, float, float, float]:
    return (
        float(value["minLon"]),
        float(value["minLat"]),
        float(value["maxLon"]),
        float(value["maxLat"]),
    )


def _candidate_context_bbox(edit: dict[str, Any], padding_degree: float) -> tuple[float, float, float, float] | None:
    bbox = _geometry_bbox(edit.get("geom") or {})
    return _expand_bbox(bbox, padding_degree=padding_degree) if bbox else None


def _row_geometry(row: dict[str, str], key: str) -> dict[str, Any]:
    return segment_graph_db.ewkt_to_geometry(row[key])


def load_csv_graph(
    *,
    node_csv: Path,
    segment_csv: Path,
) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]]]:
    nodes: dict[int, dict[str, Any]] = {}
    with node_csv.open("r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            vertex_id = int(row["vertexId"])
            nodes[vertex_id] = {
                "vertexId": vertex_id,
                "sourceNodeKey": row["sourceNodeKey"],
                "geometry": _row_geometry(row, "point"),
            }

    segments: list[dict[str, Any]] = []
    with segment_csv.open("r", encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            geometry = _row_geometry(row, "geom")
            segments.append(
                {
                    "edgeId": int(row["edgeId"]),
                    "fromNodeId": int(row["fromNodeId"]),
                    "toNodeId": int(row["toNodeId"]),
                    "segmentType": segment_graph_db.normalize_segment_type(row.get("segmentType")),
                    "lengthMeter": float(row["lengthMeter"]),
                    "geometry": geometry,
                }
            )
    return nodes, segments


def build_training_dataset(
    *,
    manual_edits: Path,
    training_bbox: tuple[float, float, float, float] | None = None,
) -> dict[str, Any]:
    document = segment_graph_db.load_json(manual_edits)
    examples: list[dict[str, Any]] = []
    all_coords: list[list[float]] = []

    for edit in document.get("edits", []):
        action = edit.get("action")
        coords = _iter_edit_coords(edit)
        all_coords.extend(coords)
        length_meter = None
        if (edit.get("geom") or {}).get("type") == "LineString":
            length_meter = segment_graph_db.line_length_meter(edit["geom"]["coordinates"])
        segment_type = (
            segment_graph_db.normalize_segment_type(edit.get("segmentType"))
            if edit.get("segmentType") is not None
            else None
        )
        example = {
            "action": action,
            "segmentType": segment_type,
            "lengthMeter": round(length_meter, 2) if length_meter is not None else None,
            "edgeId": edit.get("edgeId"),
            "vertexId": edit.get("vertexId"),
            "motif": _training_motif_for_edit(edit, length_meter),
            "beforeAfterPatch": {
                "operation": edit.get("operation"),
                "entity": edit.get("entity"),
                "hasGeometry": bool(coords),
                "sourceAction": action,
            },
        }
        if action == "add_segment":
            example["fromNodeMode"] = (edit.get("fromNode") or {}).get("mode")
            example["toNodeMode"] = (edit.get("toNode") or {}).get("mode")
        if coords:
            example["bbox"] = _bbox_from_coords(coords)
        examples.append(example)

    inferred_bbox = _bbox_from_coords(all_coords)
    active_bbox = training_bbox or (_expand_bbox(inferred_bbox) if inferred_bbox else DEFAULT_TRAINING_BBOX)
    action_counts = Counter(example["action"] for example in examples)
    segment_type_counts = Counter(example["segmentType"] for example in examples if example["segmentType"])
    motif_counts = Counter(example["motif"] for example in examples if example.get("motif"))

    return {
        "version": "02c_auto_edit_training_dataset",
        "sourceManualEdits": str(manual_edits),
        "createdAt": datetime.now(UTC).isoformat(),
        "trainingBbox": {
            "minLon": active_bbox[0],
            "minLat": active_bbox[1],
            "maxLon": active_bbox[2],
            "maxLat": active_bbox[3],
        },
        "summary": {
            "exampleCount": len(examples),
            "actionCounts": dict(sorted(action_counts.items())),
            "segmentTypeCounts": dict(sorted(segment_type_counts.items())),
            "motifCounts": dict(sorted(motif_counts.items())),
        },
        "examples": examples,
    }


def _training_motif_for_edit(edit: dict[str, Any], length_meter: float | None) -> str:
    action = edit.get("action")
    if action == "delete_segment":
        if length_meter is not None and length_meter <= 18.0:
            return "delete_short_dangling_tail"
        return "delete_intersection_or_outline_cleanup"
    if action == "delete_node":
        return "delete_orphan_or_redundant_node"
    if action == "add_segment":
        from_mode = (edit.get("fromNode") or {}).get("mode")
        to_mode = (edit.get("toNode") or {}).get("mode")
        if from_mode == "existing" and to_mode == "existing":
            return "add_side_gap_bridge"
        return "add_outline_or_corner_connector"
    if action == "add_node":
        return "add_outline_support_node"
    return f"manual_{action or 'unknown'}"


def learn_profile(training_dataset: dict[str, Any]) -> dict[str, Any]:
    delete_lengths = [
        float(example["lengthMeter"])
        for example in training_dataset["examples"]
        if example.get("action") == "delete_segment" and example.get("lengthMeter") is not None
    ]
    add_lengths = [
        float(example["lengthMeter"])
        for example in training_dataset["examples"]
        if example.get("action") == "add_segment" and example.get("lengthMeter") is not None
    ]
    add_type_counts = Counter(
        example.get("segmentType")
        for example in training_dataset["examples"]
        if example.get("action") == "add_segment" and example.get("segmentType")
    )
    add_endpoint_mode_counts = Counter(
        f"{example.get('fromNodeMode', 'unknown')}->{example.get('toNodeMode', 'unknown')}"
        for example in training_dataset["examples"]
        if example.get("action") == "add_segment"
    )
    motif_counts = Counter(
        example.get("motif")
        for example in training_dataset["examples"]
        if example.get("motif")
    )
    learned_add_type = add_type_counts.most_common(1)[0][0] if add_type_counts else "SIDE_WALK"

    delete_max = min(max(_percentile(delete_lengths, 0.75, 35.0), 8.0), 80.0)
    add_min = max(min(_percentile(add_lengths, 0.10, 4.0), 15.0), 2.0)
    add_max = min(max(_percentile(add_lengths, 0.75, 28.0) * 1.25, 12.0), 85.0)

    return {
        "version": "02c_auto_edit_profile",
        "createdAt": datetime.now(UTC).isoformat(),
        "sourceTrainingDataset": training_dataset.get("sourceManualEdits"),
        "trainingBbox": training_dataset["trainingBbox"],
        "summary": training_dataset["summary"],
        "thresholds": {
            "danglingDeleteMaxMeter": round(delete_max, 2),
            "gapAddMinMeter": round(add_min, 2),
            "gapAddMaxMeter": round(add_max, 2),
        },
        "learnedAddSegmentType": learned_add_type,
        "learnedAddEndpointModeCounts": dict(sorted(add_endpoint_mode_counts.items())),
        "learnedMotifCounts": dict(sorted(motif_counts.items())),
        "policy": {
            "mode": "review_required",
            "target": "Gangseo CSV outside training bbox and inside optional generation bbox",
            "output": "motif/evidence manual_edits JSON candidates only; do not apply to CSV before human approval",
        },
    }


def _degree_by_node(segments: list[dict[str, Any]]) -> Counter[int]:
    degree: Counter[int] = Counter()
    for segment in segments:
        degree[int(segment["fromNodeId"])] += 1
        degree[int(segment["toNodeId"])] += 1
    return degree


def _segment_angle_degree(segment: dict[str, Any]) -> float:
    coords = segment["geometry"]["coordinates"]
    start = coords[0]
    end = coords[-1]
    dx = float(end[0]) - float(start[0])
    dy = float(end[1]) - float(start[1])
    if dx == 0 and dy == 0:
        return 0.0
    import math

    return round((math.degrees(math.atan2(dy, dx)) + 360.0) % 180.0, 2)


def _build_point_grid(
    nodes: dict[int, dict[str, Any]],
    *,
    cell_degree: float,
) -> dict[tuple[int, int], list[int]]:
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for node_id, node in nodes.items():
        lng, lat = node["geometry"]["coordinates"]
        grid[(int(lng / cell_degree), int(lat / cell_degree))].append(node_id)
    return grid


def _nearby_node_count(
    *,
    node: dict[str, Any],
    nodes: dict[int, dict[str, Any]],
    grid: dict[tuple[int, int], list[int]],
    cell_degree: float,
    radius_meter: float,
) -> int:
    lng, lat = node["geometry"]["coordinates"]
    cell = (int(lng / cell_degree), int(lat / cell_degree))
    count = 0
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for candidate_id in grid.get((cell[0] + dx, cell[1] + dy), []):
                if candidate_id == node["vertexId"]:
                    continue
                distance = segment_graph_db.point_distance_meter(
                    node["geometry"]["coordinates"],
                    nodes[candidate_id]["geometry"]["coordinates"],
                )
                if distance <= radius_meter:
                    count += 1
    return count


def _segment_direction_at_node(
    segment: dict[str, Any],
    node_id: int,
) -> tuple[list[float], list[float]]:
    coords = segment["geometry"]["coordinates"]
    if node_id == segment["fromNodeId"]:
        return coords[0], coords[min(1, len(coords) - 1)]
    return coords[-1], coords[max(0, len(coords) - 2)]


def _endpoint_gap_alignment(
    *,
    left_segment: dict[str, Any],
    left_node_id: int,
    right_segment: dict[str, Any],
    right_node_id: int,
) -> float:
    left_anchor, left_inside = _segment_direction_at_node(left_segment, left_node_id)
    right_anchor, right_inside = _segment_direction_at_node(right_segment, right_node_id)
    left_gap = (right_anchor[0] - left_anchor[0], right_anchor[1] - left_anchor[1])
    right_gap = (left_anchor[0] - right_anchor[0], left_anchor[1] - right_anchor[1])
    left_inward = (left_inside[0] - left_anchor[0], left_inside[1] - left_anchor[1])
    right_inward = (right_inside[0] - right_anchor[0], right_inside[1] - right_anchor[1])

    def cosine(a: tuple[float, float], b: tuple[float, float]) -> float:
        a_len = (a[0] ** 2 + a[1] ** 2) ** 0.5
        b_len = (b[0] ** 2 + b[1] ** 2) ** 0.5
        if a_len == 0 or b_len == 0:
            return 0.0
        return (a[0] * b[0] + a[1] * b[1]) / (a_len * b_len)

    # A plausible gap bridge points away from the existing segment interior at both endpoints.
    return max(cosine(left_gap, left_inward), cosine(right_gap, right_inward))


def _delete_candidate(
    segment: dict[str, Any],
    reason: str,
    confidence: float,
    *,
    motif: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "action": "delete_segment",
        "entity": "road_segment",
        "operation": "delete",
        "edgeId": segment["edgeId"],
        "fromNodeId": segment["fromNodeId"],
        "toNodeId": segment["toNodeId"],
        "segmentType": segment["segmentType"],
        "geom": segment["geometry"],
        "motif": motif,
        "evidence": evidence,
        "reason": reason,
        "confidence": round(confidence, 3),
        "createdAt": datetime.now(UTC).isoformat(),
    }


def _add_candidate(
    *,
    from_node: dict[str, Any],
    to_node: dict[str, Any],
    segment_type: str,
    distance_meter: float,
    reason: str,
    confidence: float,
    motif: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    from_coord = from_node["geometry"]["coordinates"]
    to_coord = to_node["geometry"]["coordinates"]
    return {
        "action": "add_segment",
        "entity": "road_segment",
        "operation": "insert",
        "tempEdgeId": f"auto-candidate:{from_node['vertexId']}:{to_node['vertexId']}",
        "segmentType": segment_type,
        "fromNode": {
            "mode": "existing",
            "vertexId": from_node["vertexId"],
            "sourceNodeKey": from_node["sourceNodeKey"],
            "geom": from_node["geometry"],
            "snapDistanceMeter": 0,
        },
        "toNode": {
            "mode": "existing",
            "vertexId": to_node["vertexId"],
            "sourceNodeKey": to_node["sourceNodeKey"],
            "geom": to_node["geometry"],
            "snapDistanceMeter": 0,
        },
        "geom": {"type": "LineString", "coordinates": [from_coord, to_coord]},
        "lengthMeter": round(distance_meter, 2),
        "motif": motif,
        "evidence": evidence,
        "reason": reason,
        "confidence": round(confidence, 3),
        "createdAt": datetime.now(UTC).isoformat(),
    }


def attach_review_context(
    *,
    candidate_document: dict[str, Any],
    nodes: dict[int, dict[str, Any]],
    segments: list[dict[str, Any]],
    padding_degree: float = 0.00065,
    max_context_segments: int = 20000,
) -> None:
    context_bboxes = [
        bbox
        for edit in candidate_document.get("edits", [])
        if (bbox := _candidate_context_bbox(edit, padding_degree)) is not None
    ]
    cell_degree = max(padding_degree * 2, 0.0001)
    bbox_grid: dict[tuple[int, int], list[tuple[float, float, float, float]]] = defaultdict(list)

    def bbox_cells(bbox: tuple[float, float, float, float]) -> set[tuple[int, int]]:
        min_x = int(bbox[0] / cell_degree)
        max_x = int(bbox[2] / cell_degree)
        min_y = int(bbox[1] / cell_degree)
        max_y = int(bbox[3] / cell_degree)
        return {(x, y) for x in range(min_x, max_x + 1) for y in range(min_y, max_y + 1)}

    for context_bbox in context_bboxes:
        for cell in bbox_cells(context_bbox):
            bbox_grid[cell].append(context_bbox)

    segment_features: list[dict[str, Any]] = []
    visible_node_ids: set[int] = set()
    for segment in segments:
        segment_bbox = _geometry_bbox(segment["geometry"])
        if segment_bbox is None:
            continue
        possible_bboxes: list[tuple[float, float, float, float]] = []
        for cell in bbox_cells(segment_bbox):
            possible_bboxes.extend(bbox_grid.get(cell, []))
        if not possible_bboxes or not any(_bbox_intersects(segment_bbox, context_bbox) for context_bbox in possible_bboxes):
            continue
        segment_features.append(
            {
                "type": "Feature",
                "properties": {
                    "edgeId": segment["edgeId"],
                    "fromNodeId": segment["fromNodeId"],
                    "toNodeId": segment["toNodeId"],
                    "segmentType": segment["segmentType"],
                    "lengthMeter": segment["lengthMeter"],
                },
                "geometry": segment["geometry"],
            }
        )
        visible_node_ids.add(segment["fromNodeId"])
        visible_node_ids.add(segment["toNodeId"])
        if len(segment_features) >= max_context_segments:
            break
    node_features = [
        {
            "type": "Feature",
            "properties": {
                "vertexId": node["vertexId"],
                "sourceNodeKey": node["sourceNodeKey"],
            },
            "geometry": node["geometry"],
        }
        for node_id, node in nodes.items()
        if node_id in visible_node_ids
    ]
    candidate_document["context"] = {
        "roadNodes": {"type": "FeatureCollection", "features": node_features},
        "roadSegments": {"type": "FeatureCollection", "features": segment_features},
    }
    candidate_document["meta"]["contextCounts"] = {
        "nodes": len(node_features),
        "segments": len(segment_features),
        "maxContextSegments": max_context_segments,
    }


def generate_candidate_edits(
    *,
    node_csv: Path,
    segment_csv: Path,
    profile: dict[str, Any],
    output_add_segment_type: str = "SIDE_WALK",
    max_delete_candidates: int = 500,
    max_add_candidates: int = 300,
    generation_bbox: tuple[float, float, float, float] | None = None,
) -> dict[str, Any]:
    nodes, segments = load_csv_graph(node_csv=node_csv, segment_csv=segment_csv)
    degree = _degree_by_node(segments)
    training_bbox = _dict_to_bbox(profile["trainingBbox"])
    thresholds = profile["thresholds"]
    delete_max_meter = float(thresholds["danglingDeleteMaxMeter"])
    add_min_meter = float(thresholds["gapAddMinMeter"])
    add_max_meter = float(thresholds["gapAddMaxMeter"])
    add_segment_type = (
        profile.get("learnedAddSegmentType", "SIDE_WALK")
        if output_add_segment_type == "learned"
        else output_add_segment_type
    )
    add_segment_type = segment_graph_db.normalize_segment_type(add_segment_type)
    motif_counts = Counter(profile.get("learnedMotifCounts") or {})
    learned_delete_motif = (
        motif_counts.most_common(1)[0][0]
        if motif_counts and motif_counts.most_common(1)[0][0].startswith("delete_")
        else "delete_short_dangling_tail"
    )
    node_grid_cell_degree = max(12.0 / 85000.0, 0.00008)
    node_grid = _build_point_grid(nodes, cell_degree=node_grid_cell_degree)

    delete_candidates: list[dict[str, Any]] = []
    endpoint_segments: dict[int, dict[str, Any]] = {}
    connected_pairs: set[tuple[int, int]] = set()
    for segment in segments:
        connected_pairs.add(tuple(sorted((segment["fromNodeId"], segment["toNodeId"]))))
        if segment["segmentType"] != "SIDE_LINE":
            continue
        if generation_bbox is not None and not _geometry_in_bbox(segment["geometry"], generation_bbox):
            continue
        if _geometry_in_bbox(segment["geometry"], training_bbox):
            continue
        from_degree = degree[segment["fromNodeId"]]
        to_degree = degree[segment["toNodeId"]]
        dangling_count = int(from_degree == 1) + int(to_degree == 1)
        if dangling_count:
            endpoint_segments[segment["fromNodeId"]] = segment
            endpoint_segments[segment["toNodeId"]] = segment
        if dangling_count and segment["lengthMeter"] <= delete_max_meter:
            hub_degree = max(from_degree, to_degree)
            from_nearby_count = _nearby_node_count(
                node=nodes[segment["fromNodeId"]],
                nodes=nodes,
                grid=node_grid,
                cell_degree=node_grid_cell_degree,
                radius_meter=12.0,
            )
            to_nearby_count = _nearby_node_count(
                node=nodes[segment["toNodeId"]],
                nodes=nodes,
                grid=node_grid,
                cell_degree=node_grid_cell_degree,
                radius_meter=12.0,
            )
            nearby_endpoint_count = max(from_nearby_count, to_nearby_count)
            motif = (
                "delete_intersection_overshoot"
                if hub_degree >= 3 or nearby_endpoint_count >= 4 or learned_delete_motif == "delete_intersection_or_outline_cleanup"
                else "delete_short_dangling_tail"
            )
            confidence = 0.45 + min(0.35, (delete_max_meter - segment["lengthMeter"]) / max(delete_max_meter, 1.0) * 0.35)
            if hub_degree >= 3:
                confidence += 0.15
            if motif == "delete_intersection_overshoot":
                confidence += 0.05
            evidence = {
                "lengthMeter": round(segment["lengthMeter"], 2),
                "fromDegree": from_degree,
                "toDegree": to_degree,
                "danglingEndpointCount": dangling_count,
                "hubDegree": hub_degree,
                "nearbyEndpointCount12m": nearby_endpoint_count,
                "angleDegree": _segment_angle_degree(segment),
                "trainingBboxExcluded": True,
                "generationBboxMatched": generation_bbox is not None,
            }
            delete_candidates.append(
                _delete_candidate(
                    segment,
                    f"auto_candidate_{motif}_review_required",
                    min(confidence, 0.95),
                    motif=motif,
                    evidence=evidence,
                )
            )
    delete_edits = sorted(
        delete_candidates,
        key=lambda edit: (-edit["confidence"], edit["evidence"]["lengthMeter"], edit.get("edgeId", 0)),
    )[:max_delete_candidates]

    endpoint_node_ids = [
        node_id
        for node_id, node in nodes.items()
        if degree[node_id] == 1
        and node_id in endpoint_segments
        and not _point_in_bbox(node["geometry"]["coordinates"], training_bbox)
        and (generation_bbox is None or _point_in_bbox(node["geometry"]["coordinates"], generation_bbox))
    ]
    cell_degree = max(add_max_meter / 85000.0, 0.0001)
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for node_id in endpoint_node_ids:
        lng, lat = nodes[node_id]["geometry"]["coordinates"]
        grid[(int(lng / cell_degree), int(lat / cell_degree))].append(node_id)

    add_candidates: list[dict[str, Any]] = []
    seen_pairs: set[tuple[int, int]] = set()
    best_pair_by_node: dict[int, tuple[float, int]] = {}
    for node_id in endpoint_node_ids:
        lng, lat = nodes[node_id]["geometry"]["coordinates"]
        cell = (int(lng / cell_degree), int(lat / cell_degree))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other_id in grid.get((cell[0] + dx, cell[1] + dy), []):
                    if other_id == node_id:
                        continue
                    pair = tuple(sorted((node_id, other_id)))
                    if pair in seen_pairs or pair in connected_pairs:
                        continue
                    distance = segment_graph_db.point_distance_meter(
                        nodes[node_id]["geometry"]["coordinates"],
                        nodes[other_id]["geometry"]["coordinates"],
                    )
                    if distance < add_min_meter or distance > add_max_meter:
                        continue
                    alignment = _endpoint_gap_alignment(
                        left_segment=endpoint_segments[node_id],
                        left_node_id=node_id,
                        right_segment=endpoint_segments[other_id],
                        right_node_id=other_id,
                    )
                    if alignment > -0.15:
                        continue
                    current_best = best_pair_by_node.get(node_id)
                    if current_best is None or distance < current_best[0]:
                        best_pair_by_node[node_id] = (distance, other_id)

    candidate_pairs: list[tuple[float, int, int]] = []
    for node_id, (distance, other_id) in best_pair_by_node.items():
        reverse = best_pair_by_node.get(other_id)
        if reverse is None or reverse[1] != node_id:
            continue
        pair = tuple(sorted((node_id, other_id)))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        candidate_pairs.append((distance, pair[0], pair[1]))

    used_nodes: set[int] = set()
    for distance, node_id, other_id in sorted(candidate_pairs):
        if node_id in used_nodes or other_id in used_nodes:
            continue
        used_nodes.add(node_id)
        used_nodes.add(other_id)
        confidence = 0.55 + max(0.0, (add_max_meter - distance) / max(add_max_meter, 1.0)) * 0.25
        alignment = _endpoint_gap_alignment(
            left_segment=endpoint_segments[node_id],
            left_node_id=node_id,
            right_segment=endpoint_segments[other_id],
            right_node_id=other_id,
        )
        from_nearby_count = _nearby_node_count(
            node=nodes[node_id],
            nodes=nodes,
            grid=node_grid,
            cell_degree=node_grid_cell_degree,
            radius_meter=12.0,
        )
        to_nearby_count = _nearby_node_count(
            node=nodes[other_id],
            nodes=nodes,
            grid=node_grid,
            cell_degree=node_grid_cell_degree,
            radius_meter=12.0,
        )
        motif = (
            "add_crosswalk_or_corner_connector"
            if max(from_nearby_count, to_nearby_count) >= 4
            else "add_side_gap_bridge"
        )
        evidence = {
            "distanceMeter": round(distance, 2),
            "alignmentCosine": round(alignment, 3),
            "fromEndpointDegree": degree[node_id],
            "toEndpointDegree": degree[other_id],
            "fromNearbyEndpointCount12m": from_nearby_count,
            "toNearbyEndpointCount12m": to_nearby_count,
            "fromSourceSegmentId": endpoint_segments[node_id]["edgeId"],
            "toSourceSegmentId": endpoint_segments[other_id]["edgeId"],
            "fromSourceSegmentAngleDegree": _segment_angle_degree(endpoint_segments[node_id]),
            "toSourceSegmentAngleDegree": _segment_angle_degree(endpoint_segments[other_id]),
            "trainingBboxExcluded": True,
            "generationBboxMatched": generation_bbox is not None,
        }
        add_candidates.append(
            _add_candidate(
                from_node=nodes[node_id],
                to_node=nodes[other_id],
                segment_type=add_segment_type,
                distance_meter=distance,
                reason=f"auto_candidate_{motif}_review_required",
                confidence=min(confidence, 0.9),
                motif=motif,
                evidence=evidence,
            )
        )
    add_edits = sorted(
        add_candidates,
        key=lambda edit: (-edit["confidence"], edit["evidence"]["distanceMeter"], edit.get("tempEdgeId", "")),
    )[:max_add_candidates]

    edits = sorted(
        delete_edits + add_edits,
        key=lambda edit: (-edit["confidence"], edit["action"], edit.get("edgeId", 0), edit.get("tempEdgeId", "")),
    )
    for index, edit in enumerate(edits, start=1):
        if edit["action"] == "delete_segment":
            review_id = f"delete_segment:{edit['edgeId']}"
        elif edit["action"] == "add_segment":
            review_id = f"add_segment:{edit['tempEdgeId']}"
        else:
            review_id = f"{edit['action']}:{index}"
        edit["reviewId"] = review_id
        edit["review"] = {
            "approved": False,
            "status": "pending",
            "reviewedAt": None,
        }
    candidate_document = {
        "version": "02c_auto_edit_candidates",
        "sourceHtml": "etl/noksan_sinho_songjeong_hwajeon_segment_02c_graph_edit.html",
        "sourceGeojson": "etl/noksan_sinho_songjeong_hwajeon_segment_02c_graph_materialized.geojson",
        "createdAt": datetime.now(UTC).isoformat(),
        "meta": {
            "reviewRequired": True,
            "doNotApplyWithoutHumanApproval": True,
            "nodeCsv": str(node_csv),
            "segmentCsv": str(segment_csv),
            "trainingBbox": profile["trainingBbox"],
            "profileThresholds": thresholds,
            "generationBbox": _bbox_to_dict(generation_bbox) if generation_bbox else None,
            "candidateCounts": {
                "delete_segment": len(delete_edits),
                "add_segment": len(add_edits),
                "total": len(edits),
            },
            "motifCounts": dict(sorted(Counter(edit.get("motif") for edit in edits if edit.get("motif")).items())),
            "outputJson": str(DEFAULT_OUTPUT_DIR / "gangseo_02c_auto_manual_edit_candidates.json"),
            "approvedOutputJson": str(DEFAULT_APPROVED_JSON),
            "generationRules": [
                "Candidate graph is pre-filtered by generation bbox when supplied, then caps are applied.",
                "Delete candidates are motif/evidence classified short SIDE_LINE dangling or intersection overshoot segments outside the training bbox.",
                "Add candidates are motif/evidence classified nearby degree-1 endpoint bridges outside the training bbox.",
                "Candidates are manual_edits-compatible review inputs, not final CSV mutations.",
            ],
        },
        "edits": edits,
    }
    attach_review_context(candidate_document=candidate_document, nodes=nodes, segments=segments)
    return candidate_document


def write_auto_edit_outputs(
    *,
    manual_edits: Path,
    node_csv: Path,
    segment_csv: Path,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    output_html: Path | None = None,
    training_bbox: tuple[float, float, float, float] | None = DEFAULT_TRAINING_BBOX,
    output_add_segment_type: str = "SIDE_WALK",
    max_delete_candidates: int = 500,
    max_add_candidates: int = 300,
    generation_bbox: tuple[float, float, float, float] | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    training_dataset = build_training_dataset(manual_edits=manual_edits, training_bbox=training_bbox)
    profile = learn_profile(training_dataset)
    candidates = generate_candidate_edits(
        node_csv=node_csv,
        segment_csv=segment_csv,
        profile=profile,
        output_add_segment_type=output_add_segment_type,
        max_delete_candidates=max_delete_candidates,
        max_add_candidates=max_add_candidates,
        generation_bbox=generation_bbox,
    )

    training_path = output_dir / "gangseo_02c_auto_edit_training_data.json"
    profile_path = output_dir / "gangseo_02c_auto_edit_profile.json"
    candidate_path = output_dir / "gangseo_02c_auto_manual_edit_candidates.json"
    review_html_path = output_html or output_dir / "gangseo_02c_auto_candidate_review.html"
    candidates["meta"]["outputJson"] = str(candidate_path)
    candidates["meta"]["reviewHtml"] = str(review_html_path)
    candidates["meta"]["approvedOutputJson"] = str(output_dir / "gangseo_02c_approved_manual_edits.json")
    training_path.write_text(json.dumps(training_dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    candidate_path.write_text(json.dumps(candidates, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    review_html_path.write_text(segment_graph_candidate_review_ui.render_html(candidates), encoding="utf-8")
    diff_html_path = output_dir / "gangseo_02c_auto_candidate_diff_preview.html"
    diff_html_path.write_text(segment_graph_candidate_review_ui.render_diff_html(candidates), encoding="utf-8")
    return {
        "trainingData": str(training_path),
        "profile": str(profile_path),
        "candidates": str(candidate_path),
        "reviewHtml": str(review_html_path),
        "diffPreviewHtml": str(diff_html_path),
        "summary": candidates["meta"]["candidateCounts"],
        "motifs": candidates["meta"]["motifCounts"],
        "thresholds": profile["thresholds"],
    }


def approved_review_document(reviewed_document: dict[str, Any]) -> dict[str, Any]:
    approved_edits = [
        edit
        for edit in reviewed_document.get("edits", [])
        if (edit.get("review") or {}).get("approved") is True
    ]
    meta = dict(reviewed_document.get("meta") or {})
    meta["approvedOnly"] = True
    meta["reviewCounts"] = {
        "approved": len(approved_edits),
        "pending": max(0, len(reviewed_document.get("edits", [])) - len(approved_edits)),
        "total": len(reviewed_document.get("edits", [])),
    }
    return {
        "version": "02c_auto_edit_approved_manual_edits",
        "sourceHtml": reviewed_document.get("sourceHtml"),
        "sourceGeojson": reviewed_document.get("sourceGeojson"),
        "createdAt": datetime.now(UTC).isoformat(),
        "meta": meta,
        "edits": approved_edits,
    }
