"""Example integration using DataUpdateCoordinator."""

from datetime import timedelta
import logging

import async_timeout

from homeassistant.components.sensor import STATE_CLASS_MEASUREMENT, STATE_CLASS_TOTAL_INCREASING, SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.const import ATTR_VOLTAGE, DEVICE_CLASS_ENERGY, DEVICE_CLASS_FREQUENCY, DEVICE_CLASS_POWER_FACTOR, ELECTRIC_CURRENT_AMPERE, ELECTRIC_POTENTIAL_VOLT, DEVICE_CLASS_VOLTAGE, DEVICE_CLASS_POWER, DEVICE_CLASS_CURRENT, ENERGY_KILO_WATT_HOUR, FREQUENCY_HERTZ, POWER_WATT
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)



from .const import DOMAIN

from .pzwifi import poll

_LOGGER = logging.getLogger(__name__)

SENSOR_TYPES: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        device_class=DEVICE_CLASS_VOLTAGE,
        state_class=STATE_CLASS_MEASUREMENT,
        key='voltage',
        name="Voltage",
        icon="mdi:flash",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
    ),
    SensorEntityDescription(
        device_class=DEVICE_CLASS_CURRENT,
        state_class=STATE_CLASS_MEASUREMENT,
        key='current',
        name="Current",
        icon="mdi:current-ac",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
    ),
    SensorEntityDescription(
        device_class=DEVICE_CLASS_POWER,
        state_class=STATE_CLASS_MEASUREMENT,
        key='power',
        name="Power",
        icon="mdi:power-plug",
        native_unit_of_measurement=POWER_WATT,
    ),
    SensorEntityDescription(
        device_class=DEVICE_CLASS_ENERGY,
        state_class=STATE_CLASS_TOTAL_INCREASING,
        key='power_consumption',
        name="Consumption",
        icon="mdi:home-lightning-bolt",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        device_class=DEVICE_CLASS_POWER_FACTOR,
        state_class=STATE_CLASS_MEASUREMENT,
        key='power_factor',
        name="Power Factor",
        icon="mdi:decimal",
    ),
    SensorEntityDescription(
        device_class=DEVICE_CLASS_FREQUENCY,
        state_class=STATE_CLASS_MEASUREMENT,
        key='freqency',
        name="Frequency",
        icon="mdi:sine-wave",
        native_unit_of_measurement=FREQUENCY_HERTZ
    ),

)


async def async_setup_entry(hass, entry, async_add_entities):
    """Config entry example."""
    # assuming API object stored here by __init__.py
    (host, port) = hass.data[DOMAIN][entry.entry_id]

    async def async_update_data():
        return poll(host, port)

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        # Name of the data. For logging purposes.
        name="Peacefair Electricity Sensor",
        update_method=async_update_data,
        # Polling interval. Will only be polled if there are subscribers.
        update_interval=timedelta(seconds=5),
    )

    #
    # Fetch initial data so we have data when entities subscribe
    #
    # If the refresh fails, async_config_entry_first_refresh will
    # raise ConfigEntryNotReady and setup will try again later
    #
    # If you do not want to retry setup on failure, use
    # coordinator.async_refresh() instead
    #
    await coordinator.async_config_entry_first_refresh()

    # async_add_entities(
    #     [PFVoltageSensor(coordinator)]
    # )

    entities = [
        PFSensor(coordinator, description) for description in SENSOR_TYPES
    ]

    async_add_entities(entities)


class PFSensor(CoordinatorEntity, SensorEntity):
    """An entity using CoordinatorEntity.

    The CoordinatorEntity class provides:
        should_poll
        async_update
        async_added_to_hass
        available

    """

    def __init__(self, coordinator, description):
        self.entity_description = description
        self._attr_name = description.name
        self.entity_id = f'sensor.peacefair_{description.key}'
        super().__init__(coordinator)

    @property
    def native_value(self):
        # print(repr(self.coordinator.data))
        # print(dir(self.coordinator.data))
        return self.coordinator.data.__getattribute__(self.entity_description.key)

    @property
    def native_unit_of_measurement(self):
        return self.entity_description.native_unit_of_measurement
