"""Services for the Aira Home integration."""
from __future__ import annotations

import datetime
from functools import partial
import json
import logging
from typing import Any

from google.protobuf.duration_pb2 import Duration
from google.protobuf.timestamp_pb2 import Timestamp
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr, entity_registry as er
from pyairahome.commands import (
    ActivateHotWaterBoosting,
    DeactivateHotWaterBoosting,
    DisableCoolingFunction,
    EnableCoolingFunction,
    SetAwayMode,
)
import voluptuous as vol

from .const import DOMAIN


_LOGGER = logging.getLogger(__name__)

SERVICE_ACTIVATE_DHW_BOOST = "activate_dhw_boost"
SERVICE_DEACTIVATE_DHW_BOOST = "deactivate_dhw_boost"
SERVICE_SET_AWAY_MODE = "set_away_mode"
SERVICE_DUMP_CONFIG = "dump_config"
SERVICE_ENABLE_COOLING = "enable_cooling"
SERVICE_DISABLE_COOLING = "disable_cooling"

DHW_BOOST_VALID_HOURS = [1, 2, 3, 4, 6, 8, 12, 24]
AWAY_MODE_MIN_DAYS = 3

_TARGET_SCHEMA = {
    vol.Optional("entity_id"): vol.Any(cv.string, [cv.string]),
    vol.Optional("device_id"): vol.Any(cv.string, [cv.string]),
    vol.Optional("area_id"): vol.Any(cv.string, [cv.string]),
}

ACTIVATE_DHW_BOOST_SCHEMA = vol.Schema(
    {
        **_TARGET_SCHEMA,
        vol.Required("hours"): vol.All(vol.Coerce(int), vol.In(DHW_BOOST_VALID_HOURS)),
    }
)

DEACTIVATE_DHW_BOOST_SCHEMA = vol.Schema(_TARGET_SCHEMA)

SET_AWAY_MODE_SCHEMA = vol.Schema({
    **_TARGET_SCHEMA,
    vol.Required("start_date"): cv.date,
    vol.Required("end_date"): cv.date,
})

DUMP_CONFIG_SCHEMA = vol.Schema(_TARGET_SCHEMA)
ENABLE_COOLING_SCHEMA = vol.Schema(_TARGET_SCHEMA)
DISABLE_COOLING_SCHEMA = vol.Schema(_TARGET_SCHEMA)

SERVICES = [
    SERVICE_ACTIVATE_DHW_BOOST,
    SERVICE_DEACTIVATE_DHW_BOOST,
    SERVICE_SET_AWAY_MODE,
    SERVICE_DUMP_CONFIG,
    SERVICE_ENABLE_COOLING,
    SERVICE_DISABLE_COOLING,
]

# Keys worth calling out for the cooling-capability question.
_COOLING_KEY_HINTS = ("cool", "valve", "pump_mode", "heating_cooling")


def _leaves(obj: Any, path: str = "") -> dict[str, Any]:
    """Flatten scalar leaves of a nested dict/list into dotted-path -> value."""
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(_leaves(v, f"{path}.{k}" if path else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(_leaves(v, f"{path}[{i}]"))
    else:
        out[path] = obj
    return out


def _cooling_summary(config_inner: dict, state_inner: dict) -> dict[str, Any]:
    """Pull out the fields relevant to whether cooling is configured/possible."""
    flat = _leaves(config_inner)
    cooling_fields = {
        p: v for p, v in flat.items()
        if any(h in p.lower() for h in _COOLING_KEY_HINTS)
    }
    return {
        "configured_pump_modes": state_inner.get("configured_pump_modes"),
        "allowed_pump_mode_state": state_inner.get("allowed_pump_mode_state"),
        "pump_active_state": state_inner.get("pump_active_state"),
        "outdoor_unit_size": config_inner.get("outdoor_unit_size"),
        "cooling_related_config": cooling_fields or "none found",
    }


def _get_aira_instances_from_target(hass: HomeAssistant, call: ServiceCall) -> list:
    """Resolve service call target (entity_id and/or device_id) to the AiraHome instances associated with those entities/devices. Remove duplicates if multiple entities/devices belong to the same config entry."""
    
    domain_data: dict = hass.data.get(DOMAIN, {})
    seen_entry_ids: set[str] = set()
    aira_instances = []

    entity_ids = call.data.get("entity_id", [])
    if isinstance(entity_ids, str):
        entity_ids = [entity_ids]
    for entity_id in entity_ids:
        entity = er.async_get(hass).async_get(entity_id)
        if not entity or not entity.config_entry_id:
            _LOGGER.error("Entity %s not found or has no config entry", entity_id)
            continue
        entry_id = entity.config_entry_id
        if entry_id in seen_entry_ids or entry_id not in domain_data:
            continue
        seen_entry_ids.add(entry_id)
        aira_instances.append(domain_data[entry_id]["aira"])

    device_ids = call.data.get("device_id", [])
    if isinstance(device_ids, str):
        device_ids = [device_ids]
    for device_id in device_ids:
        device = dr.async_get(hass).async_get(device_id)
        if not device:
            _LOGGER.error("Device %s not found", device_id)
            continue
        entry_id = next(
            (eid for eid in device.config_entries if eid in domain_data), None
        )
        if not entry_id or entry_id in seen_entry_ids:
            continue
        seen_entry_ids.add(entry_id)
        aira_instances.append(domain_data[entry_id]["aira"])

    return aira_instances


async def _handle_activate_dhw_boost(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle the activate_dhw_boost service call."""
    hours: int = call.data["hours"]

    for aira in _get_aira_instances_from_target(hass, call):
        _LOGGER.debug("Activating DHW boost for %d hour(s)", hours)
        command_in = ActivateHotWaterBoosting(
            hot_water_boost_duration=Duration(seconds=hours * 3600)
        )
        try:
            updates = [x async for x in await aira.ble._run_command(command_in=command_in)]  # type: ignore
            if "succeeded" in updates[-1]:
                _LOGGER.debug("DHW boost activated for %d hour(s)", hours)
            elif "error" in updates[-1]:
                raise HomeAssistantError(f"Failed to activate DHW boost: {updates[-1]['error']}")
        except RuntimeError as e:
            raise HomeAssistantError(f"Error activating DHW boost: {e}") from e


def _date_to_timestamp(d: datetime.date) -> Timestamp:
    # Aira uses timestamps with time set to 00.00.00 for dates
    dt = datetime.datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=datetime.timezone.utc)
    ts = Timestamp()
    ts.FromDatetime(dt)
    return ts


async def _handle_set_away_mode(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle the set_away_mode service call."""
    start_date: datetime.date = call.data["start_date"]
    end_date: datetime.date = call.data["end_date"]

    if start_date < datetime.date.today():
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="away_mode_start_in_past",
        )

    if (end_date - start_date).days < AWAY_MODE_MIN_DAYS:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="away_mode_dates_too_close",
            translation_placeholders={"min_days": str(AWAY_MODE_MIN_DAYS)},
        )

    for aira in _get_aira_instances_from_target(hass, call):
        _LOGGER.debug("Setting away mode from %s to %s", start_date, end_date)
        command_in = SetAwayMode(
            current_time=_date_to_timestamp(start_date),
            end_time=_date_to_timestamp(end_date),
            target_room_temperature=0.0, # apparently normal app behavior is to set target temp to 0 when activating away mode, the user can't do anything about it officially
        )
        try:
            updates = [x async for x in await aira.ble._run_command(command_in=command_in)]  # type: ignore
            if "succeeded" in updates[-1]:
                _LOGGER.debug("Away mode set from %s to %s", start_date, end_date)
            elif "error" in updates[-1]:
                raise HomeAssistantError(f"Failed to set away mode: {updates[-1]['error']}")
        except RuntimeError as e:
            raise HomeAssistantError(f"Error setting away mode: {e}") from e


async def _handle_deactivate_dhw_boost(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle the deactivate_dhw_boost service call."""
    for aira in _get_aira_instances_from_target(hass, call):
        _LOGGER.debug("Deactivating DHW boost")
        command_in = DeactivateHotWaterBoosting()
        try:
            updates = [x async for x in await aira.ble._run_command(command_in=command_in)]  # type: ignore
            if "succeeded" in updates[-1]:
                _LOGGER.debug("DHW boost deactivated")
            elif "error" in updates[-1]:
                raise HomeAssistantError(f"Failed to deactivate DHW boost: {updates[-1]['error']}")
        except RuntimeError as e:
            raise HomeAssistantError(f"Error deactivating DHW boost: {e}") from e


async def _handle_dump_config(hass: HomeAssistant, call: ServiceCall) -> ServiceResponse:
    """Read-only: dump the device's live CCV configuration and pump-mode state.

    Reuses the integration's existing (proxy-backed) BLE connection, so it works
    through an ESPHome Bluetooth proxy without opening a second link to the pump.
    Sends no commands and changes nothing on the device.
    """
    domain_data: dict = hass.data.get(DOMAIN, {})
    seen_entry_ids: set[str] = set()

    # Resolve targets to (entry_id, aira, coordinator) so we can label results.
    targets: list[tuple[str, Any, Any]] = []

    entity_ids = call.data.get("entity_id", [])
    if isinstance(entity_ids, str):
        entity_ids = [entity_ids]
    device_ids = call.data.get("device_id", [])
    if isinstance(device_ids, str):
        device_ids = [device_ids]

    resolved_entry_ids: list[str] = []
    for entity_id in entity_ids:
        entity = er.async_get(hass).async_get(entity_id)
        if entity and entity.config_entry_id:
            resolved_entry_ids.append(entity.config_entry_id)
    for device_id in device_ids:
        device = dr.async_get(hass).async_get(device_id)
        if device:
            eid = next((e for e in device.config_entries if e in domain_data), None)
            if eid:
                resolved_entry_ids.append(eid)
    # Fall back to every configured device if no target was given.
    if not resolved_entry_ids:
        resolved_entry_ids = list(domain_data.keys())

    for entry_id in resolved_entry_ids:
        if entry_id in seen_entry_ids or entry_id not in domain_data:
            continue
        seen_entry_ids.add(entry_id)
        targets.append((entry_id, domain_data[entry_id]["aira"], domain_data[entry_id]["coordinator"]))

    if not targets:
        raise ServiceValidationError("No configured Aira device matched the target")

    results: dict[str, Any] = {}
    for entry_id, aira, coordinator in targets:
        entry_result: dict[str, Any] = {}
        try:
            configuration = await aira.ble._get_configuration()  # type: ignore
            state = await aira.ble._get_states()  # type: ignore
            config_inner = configuration.get("config", configuration) if isinstance(configuration, dict) else {}
            state_inner = state.get("state", state) if isinstance(state, dict) else {}
            entry_result["summary"] = _cooling_summary(config_inner, state_inner)
            entry_result["full_config"] = config_inner
        except Exception as err:  # noqa: BLE001 - diagnostic: report instead of raising
            _LOGGER.exception("dump_config failed for entry %s", entry_id)
            entry_result["error"] = repr(err)
        results[entry_id] = entry_result

    # Ensure the response is plain JSON (protobuf-derived dicts may carry enums etc.)
    return json.loads(json.dumps(results, default=str))


async def _toggle_cooling_function(hass: HomeAssistant, call: ServiceCall, enable: bool) -> None:
    """Enable/disable the global cooling function (reversible).

    Toggles the pump's allowed-mode cooling function via BLE. This is the
    reversible counterpart pair: enable_cooling / disable_cooling. It does NOT
    write the CCV config or per-zone cooling.enabled flags.
    """
    action = "enable" if enable else "disable"
    for aira in _get_aira_instances_from_target(hass, call):
        _LOGGER.debug("%s cooling function", action)
        command_in = EnableCoolingFunction() if enable else DisableCoolingFunction()
        try:
            updates = [x async for x in await aira.ble._run_command(command_in=command_in)]  # type: ignore
            if "succeeded" in updates[-1]:
                _LOGGER.info("Cooling function %sd", action)
            elif "error" in updates[-1]:
                raise HomeAssistantError(f"Failed to {action} cooling function: {updates[-1]['error']}")
        except RuntimeError as e:
            raise HomeAssistantError(f"Error trying to {action} cooling function: {e}") from e


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register airahome services."""
    hass.services.async_register(
        DOMAIN,
        SERVICE_ACTIVATE_DHW_BOOST,
        partial(_handle_activate_dhw_boost, hass),
        schema=ACTIVATE_DHW_BOOST_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DEACTIVATE_DHW_BOOST,
        partial(_handle_deactivate_dhw_boost, hass),
        schema=DEACTIVATE_DHW_BOOST_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_AWAY_MODE,
        partial(_handle_set_away_mode, hass),
        schema=SET_AWAY_MODE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DUMP_CONFIG,
        partial(_handle_dump_config, hass),
        schema=DUMP_CONFIG_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ENABLE_COOLING,
        partial(_toggle_cooling_function, hass, enable=True),
        schema=ENABLE_COOLING_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_DISABLE_COOLING,
        partial(_toggle_cooling_function, hass, enable=False),
        schema=DISABLE_COOLING_SCHEMA,
    )


def async_unload_services(hass: HomeAssistant) -> None:
    """Remove airahome services."""
    for service in SERVICES:
        hass.services.async_remove(DOMAIN, service)