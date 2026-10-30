"""Add, import, or reconfigure the Peacefair meter."""

import logging
from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT

from . import pzwifi
from .const import DOMAIN
from .schema import CONNECTION_SCHEMA, normalize_host, vol

_LOGGER = logging.getLogger(__name__)


class PeacefairConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configure the single meter while keeping existing entity IDs."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        return await self._async_connection_step("user", user_input)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_connection_step("reconfigure", user_input)

    async def _async_connection_step(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        errors = {}
        entry = self._get_reconfigure_entry() if step_id == "reconfigure" else None
        if user_input is not None:
            data = dict(user_input)
            try:
                data[CONF_HOST] = normalize_host(data[CONF_HOST])
            except ValueError:
                errors[CONF_HOST] = "invalid_host"
            else:
                try:
                    await self.hass.async_add_executor_job(
                        pzwifi.poll, data[CONF_HOST], data[CONF_PORT]
                    )
                except OSError:
                    errors["base"] = "cannot_connect"
                except (pzwifi.CRCError, pzwifi.BadValue):
                    errors["base"] = "invalid_response"
                except Exception:
                    _LOGGER.exception("Unexpected error validating the Peacefair meter")
                    errors["base"] = "unknown"
                else:
                    title = f"Peacefair ({data[CONF_HOST]}:{data[CONF_PORT]})"
                    if entry is not None:
                        return self.async_update_reload_and_abort(
                            entry, data_updates=data, title=title
                        )
                    if self._async_current_entries():
                        return self.async_abort(reason="single_instance_allowed")
                    return self.async_create_entry(title=title, data=data)

        suggested = user_input or (entry.data if entry else {CONF_PORT: 9000})
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(CONNECTION_SCHEMA, suggested),
            errors=errors,
        )

    async def async_step_import(self, user_input: dict[str, Any]) -> ConfigFlowResult:
        """Import YAML once, including while the meter is temporarily offline."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        try:
            data = CONNECTION_SCHEMA(user_input)
            data[CONF_HOST] = normalize_host(data[CONF_HOST])
        except (vol.Invalid, ValueError):
            _LOGGER.error("Invalid Peacefair YAML: specify a host and a port from 1 to 65535")
            return self.async_abort(reason="invalid_config")
        return self.async_create_entry(
            title=f"Peacefair ({data[CONF_HOST]}:{data[CONF_PORT]})", data=data
        )
