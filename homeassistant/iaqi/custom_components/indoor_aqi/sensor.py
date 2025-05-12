import logging
from datetime import datetime, timedelta, timezone

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.util import slugify

from . import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Indoor AQI borrowed from: https://atmotube.com/atmocube-support/indoor-air-quality-index-iaqi
# For each pollutant, linearly interpolate between breakpoints to get its IAQI
# subindex. They recommend using 1-minute averages.
#
# Breakpoint tables: sorted list of (concentration, IAQI).
# 100 = best (clean), 0 = worst (very polluted).

BREAKPOINTS = {
    "co2": [
        (400, 100),
        (600, 80),
        (1000, 60),
        (1500, 40),
        (2500, 20),
        (4000, 0),
    ],
    "voc": [
        (1, 100),
        (200, 80),
        (250, 60),
        (350, 40),
        (400, 20),
        (500, 0),
    ],
    "nox": [
        (1, 100),
        (50, 80),
        (100, 60),
        (300, 40),
        (350, 20),
        (500, 0),
    ],
    "ch2o": [
        (0, 100),
        (0.06, 80),
        (0.11, 60),
        (0.31, 40),
        (0.76, 20),
        (1.0, 0),
    ],
    "pm1": [
        (0, 100),
        (15, 80),
        (35, 60),
        (62, 40),
        (96, 20),
        (150, 0),
    ],
    "pm25": [
        (0, 100),
        (21, 80),
        (51, 60),
        (91, 40),
        (141, 20),
        (200, 0),
    ],
    "pm10": [
        (0, 100),
        (31, 80),
        (76, 60),
        (126, 40),
        (201, 20),
        (300, 0),
    ],
    "co": [
        (0, 100),
        (1.8, 80),
        (8.8, 60),
        (10.1, 40),
        (15.1, 20),
        (30, 0),
    ],
    "o3": [
        (0, 100),
        (0.026, 80),
        (0.061, 60),
        (0.076, 40),
        (0.101, 20),
        (0.3, 0),
    ],
}


def compute_iaqi(pollutant: str, c: float) -> float | None:
    """
    Given a pollutant name (e.g. 'co2') and measured concentration `c`,
    look up the breakpoints and do piecewise linear interpolation to get IAQI in 0..100.
    If c is below the first bracket => clamp to that bracket's IAQI.
    If c is above the last => clamp to last bracket's IAQI.
    If we can't find the pollutant => returns None.
    """
    bp = BREAKPOINTS.get(pollutant.lower())
    if not bp:
        return None  # unknown pollutant

    # If c is below the first bracket
    if c < bp[0][0]:
        return float(bp[0][1])

    # If c is above the last bracket
    if c > bp[-1][0]:
        return float(bp[-1][1])

    # Otherwise, find i such that bp[i][0] <= c <= bp[i+1][0]
    for i in range(len(bp) - 1):
        cLo, iLo = bp[i]
        cHi, iHi = bp[i + 1]
        if cLo <= c <= cHi:
            # linear interpolation
            if cHi == cLo:
                return float(iLo)
            ratio = (c - cLo) / (cHi - cLo)
            return float(iLo + (iHi - iLo) * ratio)

    return None  # fallback if something was out of the bracket array


def parse_timedelta(value) -> timedelta:
    """Parse an integer or HH:MM:SS string into a timedelta."""
    if isinstance(value, int):
        return timedelta(seconds=value)
    if isinstance(value, str):
        # try parse as integer seconds
        try:
            return timedelta(seconds=int(value))
        except ValueError:
            pass
        # else assume HH:MM:SS
        hh, mm, ss = value.split(":")
        return timedelta(hours=int(hh), minutes=int(mm), seconds=int(ss))

    raise ValueError(f"Invalid stale_time: {value}")


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
):
    """
    Called after __init__.py's async_setup_entry. We'll read the config from
    hass.data[DOMAIN]["yaml_config"], build one or more sensors, and add them.
    """
    integration_data = hass.data.get(DOMAIN, {})
    yaml_cfg = integration_data.get("yaml_config", {})

    # The user might define "monitors" as a list:
    # indoor_aqi:
    #   monitors:
    #     - name: "Rai's room AQI"
    #       unique_id: "rai_s_room_aqi"
    #       sensors:
    #         co2: sensor.xxxx
    #         pm25: sensor.yyyy
    #   stale_time: "3600"

    # We'll look for "monitors" or fallback to a single "sensors" block.
    monitors = yaml_cfg.get("monitors", [])
    if not monitors:
        # Single block fallback:
        # indoor_aqi:
        #   name: "Rai's room AQI"
        #   sensors: ...
        #   stale_time: ...
        if "sensors" in yaml_cfg:
            monitors = [yaml_cfg]

    entities = []
    for m in monitors:
        name = m.get("name", "Indoor AQI")
        unique_id = m.get("unique_id")
        sensor_map = m.get("sensors", {})
        stale_str = m.get("stale_time", yaml_cfg.get("stale_time", "3600"))
        stale_time = parse_timedelta(stale_str)

        ent = IndoorAQISensor(
            hass=hass,
            name=name,
            unique_id=unique_id,
            sensor_map=sensor_map,
            stale_time=stale_time,
        )
        entities.append(ent)

    if not entities:
        _LOGGER.warning(
            "No monitors found in YAML config, no IndoorAQI sensors created."
        )

    async_add_entities(entities, update_before_add=True)


class IndoorAQISensor(SensorEntity):
    """
    Each IndoorAQISensor references one set of pollutant sensors,
    calculates a single IAQI (0..100) = min(subindices),
    sets textual labels, etc.

    'suggested_object_id' is optional
    """

    def __init__(self, hass, name, unique_id, sensor_map, stale_time: timedelta):
        self._hass = hass
        self._attr_name = name
        self._attr_unique_id = unique_id
        self._sensor_map = sensor_map  # dict: pollutant -> entity_id
        self._stale_time = stale_time

        self._state = None  # final IAQI
        self._attrs = {}
        self._icon = "mdi:cloud"

        # Make it numeric so that HA will plot it
        self._attr_native_unit_of_measurement = "IAQI"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def suggested_display_precision(self) -> int:
        return 0

    @property
    def native_value(self) -> float | None:
        return self._state

    @property
    def icon(self):
        return self._icon

    @property
    def extra_state_attributes(self):
        return self._attrs

    def update(self):
        now_utc = datetime.now(timezone.utc)
        sensor_errors = []
        subindices = []

        for pollutant, entity_id in self._sensor_map.items():
            if not entity_id:
                sensor_errors.append(f"{pollutant}: missing entity_id")
                continue

            s_obj = self._hass.states.get(entity_id)
            if not s_obj:
                sensor_errors.append(f"{pollutant}: {entity_id} has no state object")
                continue

            raw = s_obj.state
            if raw in [STATE_UNKNOWN, STATE_UNAVAILABLE, None]:
                sensor_errors.append(f"{pollutant}: unavailable")
                continue

            # check staleness
            if (now_utc - s_obj.last_updated) > self._stale_time:
                sensor_errors.append(f"{pollutant}: stale")
                continue

            # parse float
            try:
                val = float(raw)
            except ValueError:
                sensor_errors.append(f"{pollutant}: not numeric")
                continue

            iaqi = compute_iaqi(pollutant, val)
            if iaqi is None:
                sensor_errors.append(f"{pollutant}: bracket unknown")
            else:
                subindices.append(iaqi)

        if subindices:
            overall = min(subindices)  # 0..100 (lowest=worst, highest=best)
            self._state = overall
        else:
            overall = None
            self._state = None

        if overall is None:
            label = "Unknown"
            color = "grey"
            icon = "mdi:help"
        elif overall > 80:
            label = "Good"
            color = "green"
            icon = "mdi:emoticon-happy"
        elif overall > 60:
            label = "Moderate"
            color = "yellow"
            icon = "mdi:emoticon-neutral"
        elif overall > 40:
            label = "Polluted"
            color = "orange"
            icon = "mdi:emoticon-sad"
        elif overall > 20:
            label = "Very Polluted"
            color = "red"
            icon = "mdi:emoticon-dead"
        else:
            label = "Severely Polluted"
            color = "purple"
            icon = "mdi:emoticon-devil"

        self._icon = icon
        self._attrs = {
            "level": label,
            "color": color,
            "sensor_errors": sensor_errors,
            "subindex_count": len(subindices),
        }

        if sensor_errors:
            _LOGGER.warning("%s partial data: %s", self.name, sensor_errors)
