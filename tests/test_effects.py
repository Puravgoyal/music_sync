"""Tests for music-reactive lighting effects and color translation."""

import pytest

from src.audio.analyzer import AudioMetrics
from src.effects import (
    AmbientFlowEffect,
    BassReactiveEffect,
    BeatPulseEffect,
    EffectSettings,
    SmoothSpectrumEffect,
    SpectrumRGBEffect,
    get_effect,
    list_effects,
)


def _make_metrics(
    rms: float = 0.5,
    loudness: float = 0.5,
    bass: float = 0.5,
    mid: float = 0.5,
    treble: float = 0.5,
    is_onset: bool = False,
    onset_strength: float = 0.0,
    is_silent: bool = False,
) -> AudioMetrics:
    return AudioMetrics(
        rms=rms,
        loudness=loudness,
        bass=bass,
        mid=mid,
        treble=treble,
        spectral_flux=0.1,
        is_onset=is_onset,
        onset_strength=onset_strength,
        is_silent=is_silent,
    )


class TestEffectSettings:
    """Test EffectSettings validation and constraints."""

    def test_default_settings_valid(self) -> None:
        settings = EffectSettings()
        settings.validate()
        assert settings.sensitivity == 1.0
        assert settings.min_brightness == 25
        assert settings.max_brightness == 255
        assert settings.update_rate_hz == 4.0

    @pytest.mark.parametrize(
        "kwargs,match",
        [
            ({"sensitivity": 0.05}, "Sensitivity"),
            ({"sensitivity": 3.5}, "Sensitivity"),
            ({"min_brightness": -5}, "Min brightness"),
            ({"max_brightness": 300}, "Max brightness"),
            ({"min_brightness": 200, "max_brightness": 100}, "cannot exceed"),
            ({"attack_speed": 0.0}, "Attack speed"),
            ({"release_speed": 1.5}, "Release speed"),
            ({"update_rate_hz": 0.5}, "Update rate"),
            ({"update_rate_hz": 15.0}, "Update rate"),
        ],
    )
    def test_invalid_settings_raise_value_error(self, kwargs: dict, match: str) -> None:
        settings = EffectSettings(**kwargs)
        with pytest.raises(ValueError, match=match):
            settings.validate()


class TestEffectRegistry:
    """Test effect registration and lookup."""

    def test_list_effects_contains_all_modes(self) -> None:
        effects = list_effects()
        ids = [e["id"] for e in effects]
        assert "spectrum" in ids
        assert "beat" in ids
        assert "bass" in ids
        assert "smooth" in ids
        assert "ambient" in ids

    @pytest.mark.parametrize(
        "name,expected_cls",
        [
            ("spectrum", SpectrumRGBEffect),
            ("spectrum-rgb", SpectrumRGBEffect),
            ("SPECTRUM", SpectrumRGBEffect),
            ("beat", BeatPulseEffect),
            ("beat_pulse", BeatPulseEffect),
            ("bass", BassReactiveEffect),
            ("smooth", SmoothSpectrumEffect),
            ("ambient", AmbientFlowEffect),
        ],
    )
    def test_get_effect_aliases(self, name: str, expected_cls: type) -> None:
        effect = get_effect(name)
        assert isinstance(effect, expected_cls)

    def test_get_unknown_effect_raises_key_error(self) -> None:
        with pytest.raises(KeyError, match="Unknown effect"):
            get_effect("non_existent_effect_mode")


class TestSpectrumRGBEffect:
    """Test Mode 1: Spectrum RGB."""

    def test_bass_dominance_yields_red(self) -> None:
        effect = SpectrumRGBEffect()
        metrics = _make_metrics(bass=0.9, mid=0.05, treble=0.05, loudness=0.8)
        state = effect.process(metrics, current_time=1.0)
        # Red channel should be higher than green and blue
        r, g, b = state.rgb
        assert r > g
        assert r > b
        assert state.brightness >= 25

    def test_mid_dominance_yields_green(self) -> None:
        effect = SpectrumRGBEffect()
        metrics = _make_metrics(bass=0.05, mid=0.9, treble=0.05, loudness=0.8)
        state = effect.process(metrics, current_time=1.0)
        r, g, b = state.rgb
        assert g > r
        assert g > b

    def test_treble_dominance_yields_blue(self) -> None:
        effect = SpectrumRGBEffect()
        metrics = _make_metrics(bass=0.05, mid=0.05, treble=0.9, loudness=0.8)
        state = effect.process(metrics, current_time=1.0)
        r, g, b = state.rgb
        assert b > r
        assert b > g

    def test_silence_decays_brightness_to_min(self) -> None:
        effect = SpectrumRGBEffect(settings=EffectSettings(min_brightness=20))
        # Warm up with loud audio
        effect.process(_make_metrics(loudness=0.9), current_time=0.0)
        # Process silence over time
        state = None
        for t in range(1, 20):
            state = effect.process(_make_metrics(is_silent=True, loudness=0.0), current_time=float(t) * 0.1)
        assert state is not None
        assert state.brightness <= 40  # Decayed close to min_brightness


class TestBeatPulseEffect:
    """Test Mode 2: Beat Pulse."""

    def test_onset_triggers_brightness_pulse(self) -> None:
        effect = BeatPulseEffect(settings=EffectSettings(min_brightness=20, max_brightness=250))
        # Baseline frame without beat
        s1 = effect.process(_make_metrics(is_onset=False, loudness=0.2), current_time=0.1)
        # Onset transient frame
        s2 = effect.process(
            _make_metrics(is_onset=True, onset_strength=0.9, loudness=0.2),
            current_time=0.15,
        )
        assert s2.brightness > s1.brightness

    def test_decay_after_beat(self) -> None:
        effect = BeatPulseEffect()
        effect._last_time = 0.0
        # Trigger beat pulses to reach peak
        s_peak = effect.process(_make_metrics(is_onset=True, onset_strength=1.0, loudness=0.8), current_time=0.1)
        for t in range(2, 5):
            s_peak = effect.process(_make_metrics(is_onset=True, onset_strength=1.0, loudness=0.8), current_time=float(t) * 0.1)
        peak_b = s_peak.brightness

        # Settle without beats
        s_decay = None
        for t in range(5, 30):
            s_decay = effect.process(_make_metrics(is_onset=False, loudness=0.05), current_time=float(t) * 0.1)
        assert s_decay is not None
        assert s_decay.brightness < peak_b


class TestBassReactiveEffect:
    """Test Mode 3: Bass Reactive."""

    def test_bass_intensity_modulates_brightness(self) -> None:
        effect = BassReactiveEffect(settings=EffectSettings(min_brightness=30, max_brightness=250))
        low_bass = effect.process(_make_metrics(bass=0.1), current_time=0.1)
        # Higher bass
        high_bass = None
        for t in range(2, 10):
            high_bass = effect.process(_make_metrics(bass=0.95), current_time=float(t) * 0.1)
        assert high_bass is not None
        assert high_bass.brightness > low_bass.brightness

    def test_bass_hue_output_valid_rgb(self) -> None:
        effect = BassReactiveEffect()
        state = effect.process(_make_metrics(bass=0.8), current_time=0.1)
        r, g, b = state.rgb
        assert 0 <= r <= 255
        assert 0 <= g <= 255
        assert 0 <= b <= 255


class TestSmoothSpectrumEffect:
    """Test Mode 4: Smooth Spectrum."""

    def test_smooth_hue_transitions_without_clamping_errors(self) -> None:
        effect = SmoothSpectrumEffect()
        state1 = effect.process(_make_metrics(bass=0.8, mid=0.1, treble=0.1), current_time=0.1)
        state2 = effect.process(_make_metrics(bass=0.1, mid=0.8, treble=0.1), current_time=0.3)
        assert all(0 <= c <= 255 for c in state1.rgb)
        assert all(0 <= c <= 255 for c in state2.rgb)

    def test_brightness_clamps_between_min_and_max(self) -> None:
        settings = EffectSettings(min_brightness=40, max_brightness=200)
        effect = SmoothSpectrumEffect(settings=settings)
        state = effect.process(_make_metrics(loudness=1.0), current_time=0.5)
        assert state.brightness <= 200
        assert state.brightness >= 40


class TestAmbientFlowEffect:
    """Test Mode 5: Ambient Flow."""

    def test_color_drifts_over_time(self) -> None:
        effect = AmbientFlowEffect()
        state1 = effect.process(_make_metrics(loudness=0.4), current_time=0.0)
        state2 = effect.process(_make_metrics(loudness=0.4), current_time=5.0)
        # Over 5 seconds, hue should drift resulting in different RGB
        assert state1.rgb != state2.rgb

    def test_valid_brightness_and_rgb_bounds(self) -> None:
        effect = AmbientFlowEffect(settings=EffectSettings(min_brightness=15, max_brightness=220))
        for t in range(10):
            state = effect.process(_make_metrics(loudness=0.6), current_time=float(t) * 0.2)
            assert 15 <= state.brightness <= 220
            assert all(0 <= c <= 255 for c in state.rgb)
