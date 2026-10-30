"""Set up the Peacefair electricity meter integration."""

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import PeacefairConfigEntry, PeacefairCoordinator

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: PeacefairConfigEntry) -> bool:
    """Read the first sample before adding the sensor platform."""
    coordinator = PeacefairCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: PeacefairConfigEntry) -> bool:
    """Unload entities and stop the coordinator's subscriptions."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
