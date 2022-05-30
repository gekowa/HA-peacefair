"""Example integration using DataUpdateCoordinator."""

from datetime import timedelta
import logging
from collections import OrderedDict

# import async_timeout

from homeassistant.components.sensor import (
    SensorStateClass,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)

from homeassistant.const import (
    ELECTRIC_CURRENT_AMPERE,
    ELECTRIC_POTENTIAL_VOLT,
    ENERGY_KILO_WATT_HOUR,
    FREQUENCY_HERTZ,
    POWER_WATT,
)
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .pzwifi import poll

_LOGGER = logging.getLogger(__name__)

SENSOR_TYPES: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        key="voltage",
        name="Voltage",
        icon="mdi:flash",
        native_unit_of_measurement=ELECTRIC_POTENTIAL_VOLT,
    ),
    SensorEntityDescription(
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        key="current",
        name="Current",
        icon="mdi:current-ac",
        native_unit_of_measurement=ELECTRIC_CURRENT_AMPERE,
    ),
    SensorEntityDescription(
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        key="power",
        name="Power",
        icon="mdi:power-plug",
        native_unit_of_measurement=POWER_WATT,
    ),
    SensorEntityDescription(
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        key="power_consumption",
        name="Consumption",
        icon="mdi:home-lightning-bolt",
        native_unit_of_measurement=ENERGY_KILO_WATT_HOUR,
    ),
    SensorEntityDescription(
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        key="power_factor",
        name="Power Factor",
        icon="mdi:decimal",
    ),
    SensorEntityDescription(
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        key="freqency",
        name="Frequency",
        icon="mdi:sine-wave",
        native_unit_of_measurement=FREQUENCY_HERTZ,
    ),
)


async def async_setup_platform(
    hass, conf: OrderedDict, add_entities, discovery_info=None
):
    """Set up the sensor platform."""
    print("PEACEFAIR: async_setup_platform")
    print(conf)
    host = conf.get("host")
    port = conf.get("port")
    print(host, port)

    async def async_update_data():
        return poll(host, port)

    print("PEACEFAIR: DataUpdateCoordinator")
    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        # Name of the data. For logging purposes.
        name="Peacefair Electricity Sensor",
        update_method=async_update_data,
        # Polling interval. Will only be polled if there are subscribers.
        update_interval=timedelta(seconds=5),
    )

    # print("PEACEFAIR: async_config_entry_first_refresh")
    coordinator.async_config_entry_first_refresh()

    entities = [PFSensor(coordinator, description) for description in SENSOR_TYPES]

    print("PEACEFAIR: add_entities")
    add_entities(entities)

    return True


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
        self.entity_id = f"sensor.peacefair_{description.key}"
        super().__init__(coordinator)

    @property
    def native_value(self):
        # print(repr(self.coordinator.data))
        # print(dir(self.coordinator.data))
        return self.coordinator.data.__getattribute__(self.entity_description.key)

    @property
    def native_unit_of_measurement(self):
        return self.entity_description.native_unit_of_measurement
