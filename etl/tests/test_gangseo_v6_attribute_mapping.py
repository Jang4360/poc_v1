import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "23_map_gangseo_v6_attributes.py"
SPEC = importlib.util.spec_from_file_location("gangseo_v6_attribute_mapping", SCRIPT)
assert SPEC is not None
assert SPEC.loader is not None
mapping = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mapping
SPEC.loader.exec_module(mapping)


def test_derive_slope_state_thresholds() -> None:
    assert mapping.derive_slope_state(None) == "UNKNOWN"
    assert mapping.derive_slope_state(2.99) == "FLAT"
    assert mapping.derive_slope_state(3.0) == "MODERATE"
    assert mapping.derive_slope_state(5.55) == "MODERATE"
    assert mapping.derive_slope_state(5.56) == "STEEP"
    assert mapping.derive_slope_state(8.32) == "STEEP"
    assert mapping.derive_slope_state(8.33) == "RISK"


def test_state_normalizers() -> None:
    assert mapping.derive_width_state(None) == "UNKNOWN"
    assert mapping.derive_width_state(0) == "UNKNOWN"
    assert mapping.derive_width_state(1.19) == "NARROW"
    assert mapping.derive_width_state(1.2) == "ADEQUATE_120"
    assert mapping.derive_width_state(1.5) == "ADEQUATE_150"
    assert mapping.normalize_surface_state("PAVED") == "PAVED"
    assert mapping.normalize_surface_state("UNPAVED") == "UNPAVED"
    assert mapping.normalize_surface_state("UNKOWN") == "UNKNOWN"


def test_validate_mapping_inputs_accepts_current_v8_sources() -> None:
    assert mapping.validate_mapping_inputs(mapping.RAW_DIR / "gangseo_road_segments_v8.csv") == []


def test_crosswalk_signal_radii_are_expanded_for_centerline_points() -> None:
    assert mapping.AUDIO_SIGNAL_RADIUS_METER == 20.0
    assert mapping.CROSSWALK_SIGNAL_RADIUS_METER == 20.0
