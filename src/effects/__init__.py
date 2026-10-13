"""Music-reactive lighting effects library."""

from typing import Dict, List, Optional, Type

from src.effects.base import BaseMusicEffect, EffectSettings
from src.effects.ambient import AmbientFlowEffect
from src.effects.bass_reactive import BassReactiveEffect
from src.effects.beat_pulse import BeatPulseEffect
from src.effects.smooth_spectrum import SmoothSpectrumEffect
from src.effects.spectrum import SpectrumRGBEffect

EFFECT_REGISTRY: Dict[str, Type[BaseMusicEffect]] = {
    "spectrum": SpectrumRGBEffect,
    "beat": BeatPulseEffect,
    "bass": BassReactiveEffect,
    "smooth": SmoothSpectrumEffect,
    "ambient": AmbientFlowEffect,
}

EFFECT_ALIASES: Dict[str, str] = {
    "spectrum-rgb": "spectrum",
    "spectrum_rgb": "spectrum",
    "beat-pulse": "beat",
    "beat_pulse": "beat",
    "bass-reactive": "bass",
    "bass_reactive": "bass",
    "smooth-spectrum": "smooth",
    "smooth_spectrum": "smooth",
    "ambient-flow": "ambient",
    "ambient_flow": "ambient",
}


def get_effect(name: str, settings: Optional[EffectSettings] = None) -> BaseMusicEffect:
    """Retrieve an initialized effect instance by name or alias.

    Args:
        name: Name or alias of the effect (case-insensitive).
        settings: Optional EffectSettings overrides.

    Returns:
        Instance of BaseMusicEffect.

    Raises:
        KeyError: If effect name is not registered.
    """
    key = name.strip().lower()
    canonical = EFFECT_ALIASES.get(key, key)
    if canonical not in EFFECT_REGISTRY:
        available = ", ".join(sorted(EFFECT_REGISTRY.keys()))
        raise KeyError(f"Unknown effect '{name}'. Available effects: {available}")
    effect_cls = EFFECT_REGISTRY[canonical]
    return effect_cls(settings=settings)


def list_effects() -> List[Dict[str, str]]:
    """List all registered effects with descriptions."""
    return [
        {
            "id": key,
            "name": cls.name,
            "description": cls.description,
        }
        for key, cls in EFFECT_REGISTRY.items()
    ]


__all__ = [
    "BaseMusicEffect",
    "EffectSettings",
    "SpectrumRGBEffect",
    "BeatPulseEffect",
    "BassReactiveEffect",
    "SmoothSpectrumEffect",
    "AmbientFlowEffect",
    "EFFECT_REGISTRY",
    "get_effect",
    "list_effects",
]
