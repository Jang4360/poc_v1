import importlib


enrichment = importlib.import_module("etl.scripts.29_enrich_gangseo_mapping_v3")


def test_state_derivation_rules() -> None:
    assert enrichment.derive_width_state(None) == "UNKNOWN"
    assert enrichment.derive_width_state(1.1) == "NARROW"
    assert enrichment.derive_width_state(1.2) == "ADEQUATE_120"
    assert enrichment.derive_width_state(1.5) == "ADEQUATE_150"
    assert enrichment.derive_slope_state(None) == "UNKNOWN"
    assert enrichment.derive_slope_state(2.99) == "FLAT"
    assert enrichment.derive_slope_state(3.0) == "MODERATE"
    assert enrichment.derive_slope_state(5.56) == "STEEP"
    assert enrichment.derive_slope_state(8.33) == "RISK"


def test_osm_value_normalization() -> None:
    assert enrichment.normalize_surface("asphalt") == "PAVED"
    assert enrichment.normalize_surface("unpaved") == "UNPAVED"
    assert enrichment.normalize_surface("mystery") == "UNKNOWN"
    assert enrichment.parse_width("1.5 m") == 1.5
    assert enrichment.parse_width("0,9") == 0.9
    assert enrichment.parse_width("wide") is None
    assert enrichment.parse_incline_percent("6%") == 6
    assert enrichment.parse_incline_percent("up") is None


def test_set_unknown_preserves_existing_values() -> None:
    row = {"brailleBlockState": "YES"}
    assert not enrichment.set_unknown(row, "brailleBlockState", "NO")
    assert row["brailleBlockState"] == "YES"

    row = {"brailleBlockState": "UNKNOWN"}
    assert enrichment.set_unknown(row, "brailleBlockState", "NO")
    assert row["brailleBlockState"] == "NO"
