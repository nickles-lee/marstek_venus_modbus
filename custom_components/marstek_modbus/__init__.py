"""
Main integration setup for Marstek Venus Modbus component.

Handles setting up and unloading config entries, initializing
the data coordinator, and forwarding setup to sensor and select platforms.
"""

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .coordinator import MarstekCoordinator
from .const import SUPPORTED_VERSIONS

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    "sensor",
    "switch",
    "select",
    "button",
    "number",
    "binary_sensor",
] 


@dataclass(slots=True)
class _Rs485MigrationState:
    """State captured while migrating RS485 control from switch to select."""

    entity_id: str | None = None
    disabled_by: Any = None
    restore_disabled_state: bool = False


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """
    General setup of the integration.

    This is called once when Home Assistant starts.
    It does not perform any configuration and always returns True.

    Args:
        hass: Home Assistant instance.
        config: Configuration dict.

    Returns:
        True always.
    """
    return True


def _replace_entity_id_suffix(entity_id: str, old_suffix: str, new_suffix: str) -> str | None:
    """Return an entity ID with a replaced object-id suffix, if it matches."""
    if not entity_id.endswith(old_suffix):
        return None
    return f"{entity_id.removesuffix(old_suffix)}{new_suffix}"


def _replace_entity_id_platform(entity_id: str, old_platform: str, new_platform: str) -> str | None:
    """Return an entity ID with a replaced platform prefix, if it matches."""
    prefix = f"{old_platform}."
    if not entity_id.startswith(prefix):
        return None
    return f"{new_platform}.{entity_id.removeprefix(prefix)}"


def _entity_id_available(
    entity_registry: er.EntityRegistry,
    entity_id: str,
    *,
    current_entity_id: str | None = None,
) -> bool:
    """Return True if entity_id is unused or already belongs to current entity."""
    existing = entity_registry.async_get(entity_id)
    return existing is None or existing.entity_id == current_entity_id


async def _async_prepare_entity_registry_migration(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> _Rs485MigrationState:
    """Prepare entity registry entries for compatibility entity renames.

    This migration is intentionally based on config entry IDs, unique IDs, and
    existing registry entity IDs. It never assumes a specific user/device base
    name such as the examples from issue #266.
    """
    entity_registry = er.async_get(hass)
    rs485_state = _Rs485MigrationState()

    # Rename force_mode to forcible_charge_discharge while preserving the
    # user's base entity prefix and customized entity IDs where possible.
    old_force_unique_id = f"{entry.entry_id}_force_mode"
    new_force_unique_id = f"{entry.entry_id}_forcible_charge_discharge"
    old_force_entity_id = entity_registry.async_get_entity_id(
        "select", DOMAIN, old_force_unique_id
    )
    new_force_entity_id = entity_registry.async_get_entity_id(
        "select", DOMAIN, new_force_unique_id
    )

    if old_force_entity_id and not new_force_entity_id:
        new_entity_id = _replace_entity_id_suffix(
            old_force_entity_id,
            "_force_mode",
            "_forcible_charge_discharge",
        )
        update_kwargs = {"new_unique_id": new_force_unique_id}
        if new_entity_id and _entity_id_available(
            entity_registry,
            new_entity_id,
            current_entity_id=old_force_entity_id,
        ):
            update_kwargs["new_entity_id"] = new_entity_id

        entity_registry.async_update_entity(old_force_entity_id, **update_kwargs)
        _LOGGER.info(
            "Migrated select entity %s from unique ID %s to %s%s",
            old_force_entity_id,
            old_force_unique_id,
            new_force_unique_id,
            f" and entity ID {new_entity_id}" if "new_entity_id" in update_kwargs else "",
        )
    elif old_force_entity_id and new_force_entity_id:
        _LOGGER.debug(
            "Skipping force mode migration for entry %s because new entity %s already exists",
            entry.entry_id,
            new_force_entity_id,
        )

    # Convert rs485_control_mode from switch to select. Home Assistant entity
    # registry entries are platform-specific, so remove the stale switch entry
    # before the select platform is set up and preserve the default entity ID
    # shape for a post-setup update.
    rs485_unique_id = f"{entry.entry_id}_rs485_control_mode"
    old_rs485_entity_id = entity_registry.async_get_entity_id(
        "switch", DOMAIN, rs485_unique_id
    )
    new_rs485_entity_id = entity_registry.async_get_entity_id(
        "select", DOMAIN, rs485_unique_id
    )

    if old_rs485_entity_id and not new_rs485_entity_id:
        old_rs485_entry = entity_registry.async_get(old_rs485_entity_id)
        if old_rs485_entry:
            rs485_state.disabled_by = old_rs485_entry.disabled_by
            rs485_state.restore_disabled_state = True
        rs485_state.entity_id = _replace_entity_id_platform(
            old_rs485_entity_id,
            "switch",
            "select",
        )
        entity_registry.async_remove(old_rs485_entity_id)
        _LOGGER.info(
            "Removed legacy RS485 switch entity %s before select migration",
            old_rs485_entity_id,
        )
    elif old_rs485_entity_id and new_rs485_entity_id:
        _LOGGER.debug(
            "Skipping RS485 switch removal for entry %s because select entity %s already exists",
            entry.entry_id,
            new_rs485_entity_id,
        )

    return rs485_state


async def _async_finalize_entity_registry_migration(
    hass: HomeAssistant,
    entry: ConfigEntry,
    rs485_state: _Rs485MigrationState,
) -> None:
    """Apply post-platform registry updates for migrated select entities."""
    if not rs485_state.entity_id and not rs485_state.restore_disabled_state:
        return

    entity_registry = er.async_get(hass)
    rs485_unique_id = f"{entry.entry_id}_rs485_control_mode"
    rs485_entity_id = entity_registry.async_get_entity_id(
        "select", DOMAIN, rs485_unique_id
    )
    if not rs485_entity_id:
        _LOGGER.debug(
            "RS485 select entity for entry %s was not available for post-migration update",
            entry.entry_id,
        )
        return

    update_kwargs = {}
    if rs485_state.entity_id and _entity_id_available(
        entity_registry,
        rs485_state.entity_id,
        current_entity_id=rs485_entity_id,
    ):
        update_kwargs["new_entity_id"] = rs485_state.entity_id
    if rs485_state.restore_disabled_state:
        update_kwargs["disabled_by"] = rs485_state.disabled_by

    if update_kwargs:
        entity_registry.async_update_entity(rs485_entity_id, **update_kwargs)
        _LOGGER.info(
            "Finalized RS485 select migration for %s with updates: %s",
            rs485_entity_id,
            ", ".join(update_kwargs),
        )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Set up a config entry.

    Initializes the coordinator for this entry and stores it in hass.data.
    Forwards setup to platforms (e.g., sensor, select) used by this integration.

    Args:
        hass: Home Assistant instance.
        entry: ConfigEntry to setup.

    Returns:
        True if setup successful, False otherwise.
    """
    try:
        # Migrate legacy device_version tokens in existing config entries to
        # the canonical SUPPORTED_VERSIONS strings. This handles older
        # installations that used tokens like 'v1/v2' or 'v3'.
        raw_version = (entry.data.get("device_version") or "").strip()
        if raw_version:
            normalized = raw_version.lower()
            # Consider anything not listed in SUPPORTED_VERSIONS as legacy/unsupported.
            allowed = {s.lower() for s in SUPPORTED_VERSIONS}
            if normalized not in allowed:
                _LOGGER.warning(
                    "Config entry %s uses unsupported device_version '%s'. Please remove and re-add the device with the correct device version. Supported versions: %s",
                    entry.entry_id,
                    raw_version,
                    ", ".join(SUPPORTED_VERSIONS),
                )
        # Create the coordinator for data management and attempt an initial
        # connection before forwarding platform setup so the client is ready.
        coordinator = MarstekCoordinator(hass, entry)
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

        # Load register definitions off the event loop to avoid blocking
        try:
            await coordinator.async_load_registers(entry.data.get("device_version"))
        except Exception as err:
            _LOGGER.warning("Failed loading register definitions for entry %s: %s", entry.entry_id, err)

        # Establish the Modbus connection upfront so the first refresh does not
        # lazily reconnect on individual sensor reads, and failure is properly
        # tracked from the start.
        await coordinator.async_init()

        try:
            rs485_migration_state = await _async_prepare_entity_registry_migration(hass, entry)
        except Exception as err:
            _LOGGER.warning(
                "Failed preparing entity registry migration for entry %s: %s",
                entry.entry_id,
                err,
            )
            rs485_migration_state = _Rs485MigrationState()

        # Forward setup to all platforms defined in PLATFORMS
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        try:
            await _async_finalize_entity_registry_migration(hass, entry, rs485_migration_state)
        except Exception as err:
            _LOGGER.warning(
                "Failed finalizing entity registry migration for entry %s: %s",
                entry.entry_id,
                err,
            )

        # Perform first refresh to ensure coordinator has up-to-date data
        await coordinator.async_config_entry_first_refresh()

        return True
    except Exception as err:
        _LOGGER.error("Error setting up entry %s: %s", entry.entry_id, err)
        return False


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """
    Unload a config entry and its associated platforms.

    Args:
        hass: Home Assistant instance.
        entry: ConfigEntry to unload.

    Returns:
        True if unload successful, False otherwise.
    """
    try:
        # Unload all platforms for the entry
        unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

        if unload_ok:
            # Retrieve the coordinator and close it before removing
            coordinator = hass.data[DOMAIN][entry.entry_id]
            await coordinator.async_close()
            # Remove coordinator reference from hass data
            hass.data[DOMAIN].pop(entry.entry_id, None)

        return unload_ok
    except Exception as err:
        _LOGGER.error("Error unloading entry %s: %s", entry.entry_id, err)
        return False
