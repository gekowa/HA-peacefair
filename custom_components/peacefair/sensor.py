"""Peacefair sensors and the legacy YAML import entry point."""

import logging

from homeassistant.components.sensor import (
    PLATFORM_SCHEMA as SENSOR_PLATFORM_SCHEMA,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.const import (
    CONF_HOST,
    CONF_PORT,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PeacefairConfigEntry, PeacefairCoordinator
from .schema import CONNECTION_SCHEMA

_LOGGER = logging.getLogger(__name__)
PARALLEL_UPDATES = 0
PLATFORM_SCHEMA = SENSOR_PLATFORM_SCHEMA.extend(CONNECTION_SCHEMA.schema)

SENSOR_TYPES: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        key="voltage",
        name="Voltage",
        icon="mdi:flash",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
    ),
    SensorEntityDescription(
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        key="current",
        name="Current",
        icon="mdi:current-ac",
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
    ),
    SensorEntityDescription(
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        key="power",
        name="Power",
        icon="mdi:power-plug",
        native_unit_of_measurement=UnitOfPower.WATT,
    ),
    SensorEntityDescription(
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        key="power_consumption",
        name="Consumption",
        icon="mdi:home-lightning-bolt",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
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
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
    ),
)



async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Convert legacy YAML to a config entry without adding duplicate entities."""
    if hass.config_entries.async_entries(DOMAIN):
        return
    _LOGGER.warning(
        "Importing Peacefair YAML configuration. Once the integration appears in "
        "Settings > Devices & services, remove its sensor platform from YAML; "
        "future connection changes are made using Reconfigure"
    )
    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_IMPORT},
            data={CONF_HOST: config[CONF_HOST], CONF_PORT: config[CONF_PORT]},
        )
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PeacefairConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create the six sensors from the shared coordinator."""
    async_add_entities(PFSensor(entry, description) for description in SENSOR_TYPES)


class PFSensor(CoordinatorEntity[PeacefairCoordinator], SensorEntity):
    """A meter measurement with an identity independent of the IP address."""

    _attr_has_entity_name = True

    def __init__(
        self, entry: PeacefairConfigEntry, description: SensorEntityDescription
    ) -> None:
        super().__init__(entry.runtime_data)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        # Preserve the IDs used by the old YAML platform, including 'freqency'.
        # An existing registry entry (including user renames) takes precedence.
        self.entity_id = f"sensor.peacefair_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Peacefair Electricity",
            manufacturer="Peacefair",
        )

    @property
    def native_value(self) -> float | None:
        if self.coordinator.data is None:
            return None
        return getattr(self.coordinator.data, self.entity_description.key)
