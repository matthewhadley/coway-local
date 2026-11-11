"""Reject malformed measurements received through the real TLS/MQTT broker."""

import asyncio

from .conftest import eventually


async def test_invalid_telemetry_clears_previous_readings(service, fan):
    state = service.states[fan.serial]
    for invalid in (None, True, "1", 1.5, -1, [], {}):
        await asyncio.to_thread(
            fan.report,
            {"A1020.0001": 1, "A1020.0007": 500, "A1020.0011": 25, "A1020.0012": 71},
        )
        await eventually(lambda: state.telemetry.get("pm25") == 1)
        await asyncio.to_thread(
            fan.report,
            {f"A1020.{code}": invalid for code in ("0001", "0007", "0011", "0012")},
        )
        await eventually(lambda: state.telemetry.get("pm25") is None)
        assert state.telemetry == {
            "pm25": None,
            "illuminance": None,
            "prefilter_remaining": None,
            "max2_remaining": None,
        }
    await asyncio.to_thread(fan.report, {"A1020.0001": 0, "A1020.9999": 42})
    await eventually(lambda: state.telemetry.get("pm25") == 0)
    assert set(state.telemetry) == {"pm25", "illuminance", "prefilter_remaining", "max2_remaining"}
