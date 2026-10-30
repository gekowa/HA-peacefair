"""Connection validation shared by YAML import and UI configuration."""

# HA moved from Voluptuous to Probatio during 2026. Use the schema library
# supplied by the running HA version without installing an extra dependency.
try:
    import probatio as vol
except ImportError:
    import voluptuous as vol

from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers import config_validation as cv

CONNECTION_SCHEMA = vol.Schema(
    {vol.Required(CONF_HOST): str, vol.Required(CONF_PORT): cv.port}
)


def normalize_host(host: str) -> str:
    """Accept a bare IP address or hostname, with no URL or whitespace."""
    host = host.strip()
    if not host or "/" in host or any(character.isspace() for character in host):
        raise ValueError("Enter an IP address or hostname without a URL scheme")
    return host
