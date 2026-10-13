"""Tests for settings persistence and user preferences."""

import json
from pathlib import Path

import pytest

from src.config.preferences import AppPreferences, PreferencesManager


class TestAppPreferencesValidation:
    """Test AppPreferences dataclass validation and bounds clamping."""

    def test_default_preferences_are_valid(self) -> None:
        prefs = AppPreferences()
        prefs.validate()
        assert prefs.sensitivity == 1.0
        assert prefs.min_brightness == 25
        assert prefs.max_brightness == 255
        assert prefs.preferred_effect == "spectrum"
        assert prefs.update_rate_hz == 4.0
        assert prefs.restore_on_stop is True

    def test_clamps_out_of_range_values(self) -> None:
        prefs = AppPreferences(
            sensitivity=10.0,
            min_brightness=-50,
            max_brightness=500,
            color_smoothing=2.0,
            attack_speed=0.0,
            release_speed=5.0,
            beat_strength=-1.0,
            update_rate_hz=25.0,
            preferred_effect="unknown_effect",
        )
        prefs.validate()

        assert prefs.sensitivity == 3.0
        assert prefs.min_brightness == 0
        assert prefs.max_brightness == 255
        assert prefs.color_smoothing == 0.95
        assert prefs.attack_speed == 0.01
        assert prefs.release_speed == 1.0
        assert prefs.beat_strength == 0.0
        assert prefs.update_rate_hz == 10.0
        assert prefs.preferred_effect == "spectrum"

    def test_min_brightness_cannot_exceed_max(self) -> None:
        prefs = AppPreferences(min_brightness=200, max_brightness=100)
        prefs.validate()
        assert prefs.min_brightness == 100
        assert prefs.max_brightness == 100


class TestPreferencesManager:
    """Test JSON loading, atomic saving, and corruption recovery."""

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        config_file = tmp_path / "test_prefs.json"
        mgr = PreferencesManager(filepath=config_file)

        prefs = AppPreferences(
            last_bulb_ip="192.168.1.100",
            last_bulb_mac="aabbccddeeff",
            preferred_effect="beat",
            sensitivity=1.8,
            max_brightness=220,
            min_brightness=40,
            update_rate_hz=5.5,
        )
        assert mgr.save(prefs) is True
        assert config_file.exists()

        # Load in new manager instance
        mgr2 = PreferencesManager(filepath=config_file)
        loaded = mgr2.preferences
        assert loaded.last_bulb_ip == "192.168.1.100"
        assert loaded.last_bulb_mac == "aabbccddeeff"
        assert loaded.preferred_effect == "beat"
        assert loaded.sensitivity == 1.8
        assert loaded.max_brightness == 220
        assert loaded.min_brightness == 40
        assert loaded.update_rate_hz == 5.5

    def test_corrupted_json_recovers_to_defaults(self, tmp_path: Path) -> None:
        config_file = tmp_path / "corrupted_prefs.json"
        with open(config_file, "w", encoding="utf-8") as f:
            f.write("{ invalid json formatting !!!")

        mgr = PreferencesManager(filepath=config_file)
        loaded = mgr.preferences
        assert loaded.sensitivity == 1.0
        assert loaded.preferred_effect == "spectrum"

    def test_non_dict_json_recovers_to_defaults(self, tmp_path: Path) -> None:
        config_file = tmp_path / "array_prefs.json"
        with open(config_file, "w", encoding="utf-8") as f:
            f.write("[\"not\", \"a\", \"dict\"]")

        mgr = PreferencesManager(filepath=config_file)
        loaded = mgr.preferences
        assert loaded.preferred_effect == "spectrum"

    def test_schema_forward_compatibility_ignores_unknown_keys(self, tmp_path: Path) -> None:
        config_file = tmp_path / "future_prefs.json"
        data = {
            "last_bulb_ip": "10.0.0.5",
            "preferred_effect": "bass",
            "future_unrecognized_key": "some_value",
            "another_new_setting": 12345,
        }
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(data, f)

        mgr = PreferencesManager(filepath=config_file)
        loaded = mgr.preferences
        assert loaded.last_bulb_ip == "10.0.0.5"
        assert loaded.preferred_effect == "bass"
        assert not hasattr(loaded, "future_unrecognized_key")
