"""Read all six measurements without blocking Home Assistant's event loop."""

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import pzwifi

_LOGGER = logging.getLogger(__name__)

type PeacefairConfigEntry = ConfigEntry[PeacefairCoordinator]


class PeacefairCoordinator(DataUpdateCoordinator[pzwifi.PzSensorResult]):
    """Share one TCP poll between the meter's six entities."""

    def __init__(self, hass: HomeAssistant, entry: PeacefairConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name="Peacefair Electricity",
            update_interval=timedelta(seconds=5),
        )
        self.host = entry.data[CONF_HOST]
        self.port = entry.data[CONF_PORT]

    async def _async_update_data(self) -> pzwifi.PzSensorResult:
        try:
            return await self.hass.async_add_executor_job(
                pzwifi.poll, self.host, self.port
            )
        except (OSError, pzwifi.CRCError, pzwifi.BadValue) as err:
            raise UpdateFailed(f"Cannot read meter at {self.host}:{self.port}: {err}") from err
