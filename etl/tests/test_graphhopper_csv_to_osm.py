import csv
import importlib.util
import sys
import xml.etree.ElementTree as ET
from argparse import Namespace
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "graphhopper" / "scripts" / "csv_to_osm.py"
SPEC = importlib.util.spec_from_file_location("graphhopper_csv_to_osm", SCRIPT)
assert SPEC is not None
assert SPEC.loader is not None
csv_to_osm = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = csv_to_osm
SPEC.loader.exec_module(csv_to_osm)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def conversion_args(tmp_path: Path, segments: Path, nodes: Path) -> Namespace:
    return Namespace(
        segments=segments,
        nodes=nodes,
        output=tmp_path / "gangseo.osm",
        report_json=tmp_path / "report.json",
        endpoint_tolerance_meter=1.0,
        zero_length_meter=0.01,
        small_component_edge_threshold=5,
        sample_limit=20,
    )


def test_convert_writes_osm_nodes_ways_and_ieum_tags(tmp_path: Path) -> None:
    nodes = tmp_path / "nodes.csv"
    segments = tmp_path / "segments.csv"
    write_csv(
        nodes,
        ["vertexId", "sourceNodeKey", "point"],
        [
            {"vertexId": "1", "sourceNodeKey": "a", "point": "SRID=4326;POINT(128.00000000 35.00000000)"},
            {"vertexId": "2", "sourceNodeKey": "b", "point": "SRID=4326;POINT(128.00200000 35.00200000)"},
        ],
    )
    write_csv(
        segments,
        [
            "edgeId",
            "fromNodeId",
            "toNodeId",
            "geom",
            "lengthMeter",
            "walkAccess",
            "avgSlopePercent",
            "widthMeter",
            "brailleBlockState",
            "audioSignalState",
            "slopeState",
            "widthState",
            "surfaceState",
            "stairsState",
            "signalState",
            "segmentType",
        ],
        [
            {
                "edgeId": "10",
                "fromNodeId": "1",
                "toNodeId": "2",
                "geom": "SRID=4326;LINESTRING(128.00000000 35.00000000, 128.00100000 35.00100000, 128.00200000 35.00200000)",
                "lengthMeter": "288.0",
                "walkAccess": "YES",
                "avgSlopePercent": "2.5",
                "widthMeter": "1.4",
                "brailleBlockState": "UNKNOWN",
                "audioSignalState": "YES",
                "slopeState": "FLAT",
                "widthState": "ADEQUATE_120",
                "surfaceState": "PAVED",
                "stairsState": "UNKNOWN",
                "signalState": "TRAFFIC_SIGNALS",
                "segmentType": "SIDE_WALK",
            }
        ],
    )

    report = csv_to_osm.convert(conversion_args(tmp_path, segments, nodes))

    assert report["conversion"]["sourceNodeRows"] == 2
    assert report["conversion"]["sourceSegmentRows"] == 1
    assert report["conversion"]["osmNodes"] == 3
    assert report["conversion"]["syntheticShapeNodes"] == 1
    assert report["conversion"]["osmWays"] == 1
    root = ET.parse(tmp_path / "gangseo.osm").getroot()
    way = root.find("way")
    assert way is not None
    assert [nd.attrib["ref"] for nd in way.findall("nd")] == ["1", "3", "2"]
    tags = {tag.attrib["k"]: tag.attrib["v"] for tag in way.findall("tag")}
    assert tags["highway"] == "footway"
    assert tags["source"] == "mapping.csv"
    assert tags["ieum:edge_id"] == "10"
    assert tags["ieum:audio_signal_state"] == "YES"
    assert tags["ieum:signal_state"] == "TRAFFIC_SIGNALS"


def test_convert_stops_when_validation_has_hard_blockers(tmp_path: Path) -> None:
    nodes = tmp_path / "nodes.csv"
    segments = tmp_path / "segments.csv"
    write_csv(nodes, ["vertexId", "sourceNodeKey", "point"], [])
    write_csv(segments, ["edgeId", "fromNodeId", "toNodeId", "geom", "segmentType"], [])

    args = conversion_args(tmp_path, segments, nodes)

    try:
        csv_to_osm.convert(args)
    except ValueError as exc:
        assert "no rows" in str(exc)
    else:
        raise AssertionError("expected conversion to fail for empty CSV inputs")
