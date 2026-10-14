"""Unit tests for Phase 5 preferences persistence, validation, and migration."""

import json
from pathlib import Path
import pytest

from src.config.preferences import AppPreferences, PreferencesManager


class TestScreenPreferences:
    """Verify serialization, validation, and backward compatibility of Phase 5 settings."""

    def test_default_preferences_contain_phase5_fields(self) -> None:
        prefs = AppPreferences()
        assert prefs.sync_mode == "music"
        assert prefs.screen_monitor_index == 0
        assert prefs.color_strategy == "average"
        assert prefs.edge_region == "all"
        assert prefs.edge_thickness == 0.15
        assert prefs.smoothing_preset == "cinematic"
        assert prefs.detect_black_bars is True
        assert prefs.hybrid_type == "cinematic"
        assert prefs.audio_contribution == 0.35
        assert prefs.hybrid_audio_focus == "full"
        assert prefs.hybrid_beat_intensity == 1.0

    def test_validation_clamps_invalid_values(self) -> None:
        prefs = AppPreferences(
            sync_mode="invalid_mode",
            screen_monitor_index=-5,
            color_strategy="unsupported",
            edge_region="diagonal",
            edge_thickness=0.99,
            smoothing_preset="hyperdrive",
            audio_contribution=5.0,
            hybrid_audio_focus="invalid_focus",
            hybrid_beat_intensity=99.0,
        )
        prefs.validate()

        assert prefs.sync_mode == "music"
        assert prefs.screen_monitor_index == 0
        assert prefs.color_strategy == "average"
        assert prefs.edge_region == "all"
        assert prefs.edge_thickness <= 0.45
        assert prefs.smoothing_preset == "cinematic"
        assert prefs.audio_contribution == 1.0
        assert prefs.hybrid_audio_focus == "full"
        assert prefs.hybrid_beat_intensity == 2.0

    def test_backward_compatibility_with_phase4_prefs_file(self, tmp_path: Path) -> None:
        # Simulate an older preferences file from Phase 4 that lacks Phase 5 keys
        phase4_data = {
            "last_bulb_ip": "192.168.1.100",
            "preferred_effect": "beat",
            "sensitivity": 1.5,
            "min_brightness": 30,
            "max_brightness": 240,
            "color_smoothing": 0.4,
            "update_rate_hz": 4.5,
            "restore_on_stop": True,
            "dry_run": False,
        }

        prefs_file = tmp_path / "legacy_prefs.json"
        with open(prefs_file, "w", encoding="utf-8") as f:
            json.dump(phase4_data, f)

        mgr = PreferencesManager(filepath=prefs_file)
        loaded = mgr.preferences

        # Preserves legacy values
        assert loaded.last_bulb_ip == "192.168.1.100"
        assert loaded.preferred_effect == "beat"
        assert loaded.min_brightness == 30

        # Successfully defaults new Phase 5 fields without error
        assert loaded.sync_mode == "music"
        assert loaded.color_strategy == "average"
        assert loaded.hybrid_type == "cinematic"
        assert loaded.audio_contribution == 0.35

    def test_atomic_save_and_reload(self, tmp_path: Path) -> None:
        prefs_file = tmp_path / "new_prefs.json"
        mgr = PreferencesManager(filepath=prefs_file)

        mgr.preferences.sync_mode = "hybrid"
        mgr.preferences.screen_monitor_index = 1
        mgr.preferences.color_strategy = "dominant"
        mgr.preferences.smoothing_preset = "responsive"
        mgr.preferences.hybrid_type = "kick"
        mgr.preferences.audio_contribution = 0.65

        assert mgr.save()

        # Reload with fresh manager
        reloaded_mgr = PreferencesManager(filepath=prefs_file)
        reloaded = reloaded_mgr.preferences

        assert reloaded.sync_mode == "hybrid"
        assert reloaded.screen_monitor_index == 1
        assert reloaded.color_strategy == "dominant"
        assert reloaded.smoothing_preset == "responsive"
        assert reloaded.hybrid_type == "kick"
        assert pytest.approx(reloaded.audio_contribution, abs=0.01) == 0.65
