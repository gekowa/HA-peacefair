"""Config flows, legacy entity IDs, and lifecycle against Home Assistant."""

from datetime import timedelta

import pytest

from homeassistant.config_entries import ConfigEntryState, SOURCE_IMPORT, SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.data_entry_flow import FlowManagerIndexView
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

DOMAIN = "peacefair"
CONNECTION = {"host": "192.0.2.10", "port": 9000}
LEGACY_IDS = {
    "sensor.peacefair_voltage": "230",
    "sensor.peacefair_current": "1.234",
    "sensor.peacefair_power": "283.8",
    "sensor.peacefair_power_consumption": "123.456",
    "sensor.peacefair_freqency": "50",
    "sensor.peacefair_power_factor": "0.95",
}


async def setup_entry(hass):
    entry = MockConfigEntry(domain=DOMAIN, data=CONNECTION, title="Peacefair")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_ui_creates_entry_and_preserves_six_legacy_entities(hass, meter):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert set(result["data_schema"].schema) == {"host", "port"}
    fields = FlowManagerIndexView(hass.config_entries.flow)._prepare_result_json(result)["data_schema"]
    assert {field["name"] for field in fields} == {"host", "port"}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CONNECTION)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = result["result"]
    assert dict(entry.data) == CONNECTION
    assert entry.state is ConfigEntryState.LOADED
    assert {state.entity_id: state.state for state in hass.states.async_all("sensor")} == LEGACY_IDS
    registry = er.async_get(hass)
    assert all(registry.async_get(entity_id).unique_id for entity_id in LEGACY_IDS)
    energy = hass.states.get("sensor.peacefair_power_consumption")
    assert energy.attributes["unit_of_measurement"] == "kWh"
    assert energy.attributes["state_class"] == "total_increasing"


@pytest.mark.parametrize("error", [OSError("offline"), TimeoutError("timeout")])
async def test_ui_connection_failure_keeps_form_open(hass, meter, error):
    meter.side_effect = error
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CONNECTION)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_ui_reports_invalid_meter_response(hass, meter):
    from custom_components.peacefair.pzwifi import BadValue

    meter.side_effect = BadValue("invalid frame")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], CONNECTION)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_response"}


@pytest.mark.parametrize("port", [0, 65536, "invalid"])
async def test_ui_rejects_invalid_ports(hass, meter, port):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    with pytest.raises(InvalidData):
        await hass.config_entries.flow.async_configure(
            result["flow_id"], {**CONNECTION, "port": port}
        )
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_ui_rejects_blank_host(hass, meter):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**CONNECTION, "host": "  "}
    )
    assert result["errors"] == {"host": "invalid_host"}
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_yaml_imports_once_even_while_device_is_offline(hass, meter):
    meter.side_effect = OSError("offline")
    assert await async_setup_component(hass, "sensor", {
        "sensor": [{"platform": DOMAIN, **CONNECTION}]
    })
    await hass.async_block_till_done()
    entries = hass.config_entries.async_entries(DOMAIN)
    assert len(entries) == 1
    entry = entries[0]
    assert dict(entry.data) == CONNECTION
    assert entry.state is ConfigEntryState.SETUP_RETRY
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=CONNECTION
    )
    assert result["type"] is FlowResultType.ABORT
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_yaml_upgrade_keeps_legacy_ids_without_duplicate_sensors(hass, meter):
    assert await async_setup_component(hass, "sensor", {
        "sensor": [{"platform": DOMAIN, **CONNECTION}]
    })
    await hass.async_block_till_done()
    assert {state.entity_id: state.state for state in hass.states.async_all("sensor")} == LEGACY_IDS
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert {state.entity_id for state in hass.states.async_all("sensor")} == set(LEGACY_IDS)


async def test_reconfigure_keeps_registry_ids_and_ignores_stale_yaml(hass, meter):
    entry = await setup_entry(hass)
    registry = er.async_get(hass)
    unique_ids = {key: registry.async_get(key).unique_id for key in LEGACY_IDS}
    registry.async_update_entity("sensor.peacefair_voltage", new_entity_id="sensor.my_voltage")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "reconfigure", "entry_id": entry.entry_id}
    )
    replacement = {"host": "192.0.2.20", "port": 9001}
    result = await hass.config_entries.flow.async_configure(result["flow_id"], replacement)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    await hass.async_block_till_done()
    assert dict(entry.data) == replacement
    assert hass.states.get("sensor.my_voltage").state == "230"
    assert registry.async_get("sensor.my_voltage").unique_id == unique_ids.pop("sensor.peacefair_voltage")
    assert all(registry.async_get(key).unique_id == value for key, value in unique_ids.items())
    assert len(hass.states.async_all("sensor")) == 6
    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_IMPORT}, data=CONNECTION
    )
    assert dict(entry.data) == replacement
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_failed_reconfigure_does_not_change_connection(hass, meter):
    entry = await setup_entry(hass)
    meter.side_effect = OSError("offline")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "reconfigure", "entry_id": entry.entry_id}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "192.0.2.20", "port": 9001}
    )
    assert result["errors"] == {"base": "cannot_connect"}
    assert dict(entry.data) == CONNECTION


async def test_second_ui_entry_is_rejected(hass, meter):
    await setup_entry(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_disconnect_recovery_and_unload(hass, meter):
    entry = await setup_entry(hass)
    read = meter.side_effect
    meter.side_effect = OSError("offline")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert all(hass.states.get(key).state == "unavailable" for key in LEGACY_IDS)
    meter.side_effect = read
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert {key: hass.states.get(key).state for key in LEGACY_IDS} == LEGACY_IDS
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_periodic_poll_updates_all_entities(hass, meter, freezer):
    await setup_entry(hass)
    from custom_components.peacefair.pzwifi import PzSensorResult

    meter.side_effect = lambda host, port: PzSensorResult(231, 2, 462, 124, 50, 1)
    freezer.tick(timedelta(seconds=6))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert hass.states.get("sensor.peacefair_voltage").state == "231"
    assert hass.states.get("sensor.peacefair_power_consumption").state == "124"
