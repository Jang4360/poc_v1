import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "graphhopper" / "scripts" / "validate_csv_graph.py"
SPEC = importlib.util.spec_from_file_location("graphhopper_csv_validation", SCRIPT)
assert SPEC is not None
assert SPEC.loader is not None
validation = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = validation
SPEC.loader.exec_module(validation)


def test_default_graphhopper_csv_inputs_use_current_mapping_generation() -> None:
    assert validation.DEFAULT_SEGMENTS == Path("etl/raw/gangseo_road_segments_mapping_v2.csv")
    assert validation.DEFAULT_NODES == Path("etl/raw/gangseo_road_nodes_v8.csv")


def test_width_state_enum_matches_current_mapping_contract() -> None:
    assert validation.ALLOWED_ENUMS["widthState"] == {
        "ADEQUATE_150",
        "ADEQUATE_120",
        "NARROW",
        "UNKNOWN",
    }
