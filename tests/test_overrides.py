import pytest

from creality_mcp.overrides import OverrideError, build_override_flags


def test_plain_value():
    assert build_override_flags({"layer_height": 0.28}, {"layer_height"}) == ["--layer-height=0.28"]


def test_bool_values():
    known = {"enable_support"}
    assert build_override_flags({"enable_support": True}, known) == ["--enable-support=1"]
    assert build_override_flags({"enable_support": False}, known) == ["--enable-support=0"]


def test_percent_string():
    assert build_override_flags({"sparse_infill_density": "40%"}, {"sparse_infill_density"}) == [
        "--sparse-infill-density=40%"
    ]


def test_sorted_keys():
    known = {"wall_loops", "layer_height"}
    flags = build_override_flags({"wall_loops": 4, "layer_height": 0.2}, known)
    assert flags == ["--layer-height=0.2", "--wall-loops=4"]


def test_unknown_key_names_close_match():
    with pytest.raises(OverrideError, match="layer_height"):
        build_override_flags({"layer_hieght": 0.2}, {"layer_height"})


@pytest.mark.parametrize("value", ["0.2;0.3", "0.2\n", "0.2\r"])
def test_value_that_would_split(value):
    with pytest.raises(OverrideError):
        build_override_flags({"layer_height": value}, {"layer_height"})


def test_empty():
    assert build_override_flags({}, {"layer_height"}) == []


@pytest.mark.parametrize("key", ["post_process", "filename_format"])
def test_blocked_keys(key):
    with pytest.raises(OverrideError, match="cannot be overridden"):
        build_override_flags({key: "/opt/x.sh"}, {key})
