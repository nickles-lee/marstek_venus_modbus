"""Regression tests for HomeBatteryControl-compatible select definitions."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTER_DIR = ROOT / "custom_components" / "marstek_modbus" / "registers"
TRANSLATION_DIR = ROOT / "custom_components" / "marstek_modbus" / "translations"


def test_register_profiles_expose_compatibility_selects() -> None:
    """Every register profile should expose the new compatibility selects."""
    for path in sorted(REGISTER_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text()) or {}
        selects = data.get("SELECT_DEFINITIONS") or {}
        switches = data.get("SWITCH_DEFINITIONS") or {}

        assert "force_mode" not in selects, path
        assert "forcible_charge_discharge" in selects, path
        assert selects["forcible_charge_discharge"]["options"] == {
            "stop": 0,
            "charge": 1,
            "discharge": 2,
        }

        assert "rs485_control_mode" in selects, path
        assert selects["rs485_control_mode"]["options"] == {
            "enable": 21930,
            "disable": 21947,
        }
        assert "rs485_control_mode" not in switches, path


def test_translations_include_new_select_states() -> None:
    """Translations should describe the new select option keys."""
    for path in sorted(TRANSLATION_DIR.glob("*.json")):
        data = json.loads(path.read_text())
        select_translations = data["entity"]["select"]
        switch_translations = data["entity"]["switch"]

        assert "force_mode" not in select_translations, path
        assert "forcible_charge_discharge" in select_translations, path
        assert {"stop", "charge", "discharge"} <= set(
            select_translations["forcible_charge_discharge"]["state"]
        )

        assert "rs485_control_mode" in select_translations, path
        assert {"enable", "disable"} <= set(
            select_translations["rs485_control_mode"]["state"]
        )
        assert "rs485_control_mode" not in switch_translations, path
