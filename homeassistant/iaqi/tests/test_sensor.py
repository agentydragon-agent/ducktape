"""Tests for the Indoor AQI sensor component."""

from datetime import datetime, timedelta, timezone

import pytest
from hamcrest import assert_that, close_to, contains_inanyorder, has_entries
from homeassistant.const import STATE_UNAVAILABLE

from custom_components.indoor_aqi.sensor import IndoorAQISensor, compute_iaqi


@pytest.fixture
def now():
    return datetime.now(timezone.utc)


@pytest.mark.parametrize(
    "co2_value, pm25_value, expected_iaqi, expected_bottleneck",
    [
        # CO2 is the bottleneck (1500 ppm = IAQI 40, PM25 30 μg/m³ = IAQI ~73)
        ("1500", "30", 40.0, "CO₂: 1500.0 ppm"),
        # CO2 bigger bottleneck than PM2.5 (CO2: IAQI 60, PM2.5: IAQI 60.66)
        ("1000", "51", 60.0, "CO₂: 1000.0 ppm, PM2.5: 51.0 μg/m³"),
    ],
)
async def test_sensor_update(
    hass, co2_value, pm25_value, expected_iaqi, expected_bottleneck, now
):
    """Test sensor updates with different pollutant values."""
    # Create actual sensor entities with constant values
    hass.states.async_set(
        "sensor.co2",
        co2_value,
        {"unit_of_measurement": "ppm", "last_updated": now},
    )

    hass.states.async_set(
        "sensor.pm25",
        pm25_value,
        {"unit_of_measurement": "μg/m³", "last_updated": now},
    )

    # Create our sensor using the real hass instance
    sensor = IndoorAQISensor(
        hass=hass,
        name="Test AQI",
        unique_id="test_aqi",
        sensor_map={"co2": "sensor.co2", "pm25": "sensor.pm25"},
        stale_time=timedelta(hours=1),
    )

    # Update the sensor
    sensor.update()

    # Check the results
    assert_that(sensor.native_value, close_to(expected_iaqi, 0.1))
    assert_that(
        sensor.extra_state_attributes,
        has_entries(
            bottleneck_string=expected_bottleneck,
            iaqi_co2=compute_iaqi("co2", float(co2_value)),
            iaqi_pm25=compute_iaqi("pm25", float(pm25_value)),
            raw_co2=float(co2_value),
            raw_pm25=float(pm25_value),
        ),
    )


# Test edge cases and error handling
async def test_sensor_error_handling(hass, now):
    """Test sensor behavior with invalid or missing data."""
    # Normal sensor
    hass.states.async_set(
        "sensor.co2",
        "800",
        {"unit_of_measurement": "ppm", "last_updated": now},
    )

    # Unavailable sensor
    hass.states.async_set(
        "sensor.unavailable", STATE_UNAVAILABLE, {"last_updated": now}
    )

    # Stale sensor
    hass.states.async_set(
        "sensor.stale",
        "100",
        # Stale (>1 hour old)
        {"unit_of_measurement": "ppb", "last_updated": now - timedelta(hours=2)},
    )

    # Non-numeric sensor
    hass.states.async_set("sensor.non_numeric", "not a number", {"last_updated": now})

    # Unknown pollutant type sensor
    hass.states.async_set(
        "sensor.unknown_type",
        "50",
        {"unit_of_measurement": "unknown", "last_updated": now},
    )

    # Create our sensor
    sensor = IndoorAQISensor(
        hass=hass,
        name="Test AQI",
        unique_id="test_aqi",
        sensor_map={
            "co2": "sensor.co2",
            "pm25": "sensor.missing",
            "voc": "sensor.unavailable",
            "nox": "sensor.stale",
            "o3": "sensor.non_numeric",
            "unknown": "sensor.unknown_type",
        },
        stale_time=timedelta(hours=1),
    )

    sensor.update()

    # Check results - only CO2 at 800 ppm (IAQI 60) should be valid
    assert_that(sensor.native_value, close_to(60.0, 0.1))

    assert_that(
        sensor.extra_state_attributes["sensor_errors"],
        contains_inanyorder(
            "pm25: sensor.missing has no state object",
            "voc: unavailable",
            "o3: not numeric",
            "unknown: bracket unknown",
        ),
    )
