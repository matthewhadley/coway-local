import pytest

from custom_components.coway_local.telemetry import decode_report


def test_report_converts_filter_usage_to_remaining():
    report = {"A1020.0001": 0, "A1020.0007": 617, "A1020.0011": 25, "A1020.0012": 100}
    assert decode_report(report) == {
        "pm25": 0,
        "illuminance": 617,
        "prefilter_remaining": 75,
        "max2_remaining": 0,
    }


def test_absent_and_unknown_fields_are_left_out():
    assert decode_report({"A1020.0001": 2, "A1020.9999": 42}) == {"pm25": 2}


@pytest.mark.parametrize("invalid", [None, True, "1", 1.5, -1, [], {}])
def test_invalid_readings_become_unknown(invalid):
    report = {f"A1020.{code}": invalid for code in ("0001", "0007", "0011", "0012")}
    assert set(decode_report(report).values()) == {None}


def test_filter_usage_above_100_is_unknown():
    assert decode_report({"A1020.0011": 101}) == {"prefilter_remaining": None}
