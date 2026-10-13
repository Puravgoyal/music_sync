"""WiZ smart bulb controller abstraction and safe command management."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from pywizlight import PilotBuilder, PilotParser, wizlight
from pywizlight.exceptions import (
    WizLightConnectionError,
    WizLightMethodNotFound,
    WizLightTimeOutError,
)

from src.utils.network import validate_ip

logger = logging.getLogger("wiz_music_sync.controller")


class WizControllerError(Exception):
    """Base exception for WiZ bulb controller errors."""


class WizConnectionError(WizControllerError):
    """Raised when connection to bulb fails or is unreachable."""


class WizTimeoutError(WizControllerError):
    """Raised when communication with bulb times out."""


class UnsupportedFeatureError(WizControllerError):
    """Raised when requesting a feature not supported by the bulb hardware."""


class ValidationError(WizControllerError, ValueError):
    """Raised when command inputs fail validation."""


@dataclass
class BulbCapabilities:
    """Hardware capabilities of a WiZ bulb."""

    supports_rgb: bool = True
    supports_colortemp: bool = True
    supports_brightness: bool = True
    supports_effects: bool = True
    kelvin_range: Tuple[int, int] = (2200, 6500)
    model: Optional[str] = None
    firmware_version: Optional[str] = None
    bulb_class: Optional[str] = None


@dataclass
class BulbState:
    """Current state of a WiZ bulb."""

    is_on: bool
    brightness: Optional[int] = None  # 0 - 255 scale
    brightness_percent: Optional[int] = None  # 0 - 100% scale
    rgb: Optional[Tuple[int, int, int]] = None
    colortemp: Optional[int] = None  # Kelvin
    scene_id: Optional[int] = None
    warm_white: Optional[int] = None
    cold_white: Optional[int] = None
    active_mode: Optional[str] = None  # 'scene', 'colortemp', 'rgb', 'white', 'dimming', 'off', 'unknown'
    raw_pilot: Optional[Dict[str, Any]] = None

    def __str__(self) -> str:
        status_str = "ON" if self.is_on else "OFF"
        b_str = f"{self.brightness}/255 ({self.brightness_percent}%)" if self.brightness is not None else "Unknown"
        mode_str = f"Mode: {self.active_mode}" if self.active_mode else ""
        rgb_str = f"RGB: {self.rgb}" if self.rgb else ""
        ct_str = f"Color Temp: {self.colortemp}K" if self.colortemp else ""
        details = [p for p in (status_str, mode_str, f"Brightness: {b_str}", rgb_str, ct_str) if p]
        return " | ".join(details)


class WizBulbController:
    """Reusable, validated controller for local WiZ smart bulbs."""

    def __init__(self, ip: str, mac: Optional[str] = None, timeout: float = 7.0) -> None:
        """Initialize controller with validated IP.

        Args:
            ip: Target bulb IP address.
            mac: Optional hardware MAC address.
            timeout: Network operation timeout in seconds (default 7.0s to accommodate UDP retries).
        """
        self.ip = validate_ip(ip)
        self.mac = mac
        self.timeout = float(timeout)
        self._light: Optional[wizlight] = None
        self.capabilities: Optional[BulbCapabilities] = None
        self._is_connected = False

    @property
    def is_connected(self) -> bool:
        """Whether controller is connected and initialized."""
        return self._is_connected

    @property
    def is_on(self) -> bool:
        """Whether bulb is reported as turned on."""
        return bool(self._light and getattr(self._light, "status", False))

    async def connect(self) -> None:
        """Initialize connection, retrieve hardware profile and initial state."""
        logger.info("Connecting to WiZ bulb at %s...", self.ip)
        self._light = wizlight(self.ip, mac=self.mac)
        
        try:
            # Query bulb type and capabilities
            bulb_type = await self._safe_call(self._light.get_bulbtype())
            if bulb_type:
                model_name = getattr(bulb_type, "name", None)
                fw_ver = getattr(bulb_type, "fw_version", None)
                bulb_cls = getattr(bulb_type.bulb_type, "value", str(bulb_type.bulb_type)) if hasattr(bulb_type, "bulb_type") else None
                
                k_min, k_max = 2200, 6500
                kr = getattr(bulb_type, "kelvin_range", None)
                if kr and hasattr(kr, "min") and hasattr(kr, "max"):
                    try:
                        k_min = int(kr.min)
                        k_max = int(kr.max)
                    except (TypeError, ValueError):
                        k_min, k_max = 2200, 6500
                    
                feats = getattr(bulb_type, "features", None)
                self.capabilities = BulbCapabilities(
                    supports_rgb=bool(getattr(feats, "color", True)) if feats else True,
                    supports_colortemp=bool(getattr(feats, "color_tmp", True)) if feats else True,
                    supports_brightness=bool(getattr(feats, "brightness", True)) if feats else True,
                    supports_effects=bool(getattr(feats, "effect", True)) if feats else True,
                    kelvin_range=(k_min, k_max),
                    model=model_name,
                    firmware_version=fw_ver,
                    bulb_class=bulb_cls,
                )
            else:
                # Default fallback capabilities if type query returned None
                self.capabilities = BulbCapabilities()

            # Retrieve MAC if missing
            if not self.mac:
                try:
                    self.mac = await self._safe_call(self._light.getMac())
                except Exception as exc:
                    logger.debug("MAC query failed on %s: %s", self.ip, exc)

            # Mark connected before reading initial state
            self._is_connected = True

            # Query initial state
            await self.get_state()
            logger.info("Successfully connected to WiZ bulb %s (MAC: %s)", self.ip, self.mac or "Unknown")

        except Exception:
            self._is_connected = False
            await self.close()
            raise

    async def _safe_call(self, coro: Any, timeout: Optional[float] = None) -> Any:
        """Execute a WiZ coroutine with timeout and unified error mapping."""
        effective_timeout = timeout if timeout is not None else self.timeout
        try:
            return await asyncio.wait_for(coro, timeout=effective_timeout)
        except (asyncio.TimeoutError, WizLightTimeOutError) as exc:
            logger.error("WiZ bulb %s operation timed out after %.1fs", self.ip, effective_timeout)
            raise WizTimeoutError(f"Operation timed out after {effective_timeout}s on bulb {self.ip}") from exc
        except (WizLightConnectionError, OSError) as exc:
            logger.error("Connection error communicating with WiZ bulb %s: %s", self.ip, exc)
            raise WizConnectionError(f"Connection error to bulb {self.ip}: {exc}") from exc
        except WizLightMethodNotFound as exc:
            logger.error("Unsupported method on WiZ bulb %s: %s", self.ip, exc)
            raise UnsupportedFeatureError(f"Method not supported by bulb: {exc}") from exc

    def _ensure_connected(self) -> wizlight:
        """Verify connection state and return underlying wizlight instance."""
        if not self._light or not self._is_connected:
            raise WizConnectionError("Bulb controller is not connected. Call connect() first.")
        return self._light

    async def get_state(self) -> BulbState:
        """Retrieve the current state of the bulb.

        Returns:
            BulbState dataclass with power, brightness, RGB, and Kelvin.
        """
        light = self._ensure_connected()
        states = await self._safe_call(light.updateState())
        is_on = bool(light.status)

        brightness_val: Optional[int] = None
        brightness_pct: Optional[int] = None
        rgb_val: Optional[Tuple[int, int, int]] = None
        ct_val: Optional[int] = None
        scene_id: Optional[int] = None
        ww_val: Optional[int] = None
        cw_val: Optional[int] = None
        active_mode: Optional[str] = "off" if not is_on else "unknown"
        raw_pilot: Optional[Dict[str, Any]] = None

        if states and states[0]:
            parser: PilotParser = states[0]
            brightness_val = parser.get_brightness()
            if brightness_val is not None:
                brightness_pct = round((brightness_val / 255.0) * 100)
            
            raw_rgb = parser.get_rgb()
            if raw_rgb and all(v is not None for v in raw_rgb):
                rgb_val = (int(raw_rgb[0]), int(raw_rgb[1]), int(raw_rgb[2]))
                
            ct_val = parser.get_colortemp()
            scene_id = parser.get_scene_id()
            ww_val = parser.get_warm_white()
            cw_val = parser.get_cold_white()

            pilot_dict = getattr(parser, "pilotResult", {}) or {}
            raw_pilot = dict(pilot_dict) if isinstance(pilot_dict, dict) else None

            # Determine actual active lighting mode
            if not is_on:
                active_mode = "off"
            elif scene_id is not None and scene_id > 0:
                active_mode = "scene"
            elif ct_val is not None and "temp" in pilot_dict:
                active_mode = "colortemp"
            elif rgb_val is not None and any(c > 0 for c in rgb_val) and "temp" not in pilot_dict:
                active_mode = "rgb"
            elif (ww_val is not None and ww_val > 0) or (cw_val is not None and cw_val > 0):
                active_mode = "white"
            elif brightness_val is not None:
                active_mode = "dimming"
            else:
                active_mode = "unknown"

        return BulbState(
            is_on=is_on,
            brightness=brightness_val,
            brightness_percent=brightness_pct,
            rgb=rgb_val,
            colortemp=ct_val,
            scene_id=scene_id,
            warm_white=ww_val,
            cold_white=cw_val,
            active_mode=active_mode,
            raw_pilot=raw_pilot,
        )

    async def restore_state(self, state: BulbState) -> None:
        """Restore bulb to the specified pre-sync state without inventing fallback values.

        Args:
            state: Pre-sync BulbState captured prior to music synchronization.

        Raises:
            WizConnectionError: If controller is not connected.
            WizControllerError: On communication or timeout errors.
        """
        light = self._ensure_connected()

        if not state.is_on:
            logger.info("[%s] Restoring pre-sync state: Power OFF", self.ip)
            await self._safe_call(light.turn_off())
            return

        logger.info("[%s] Restoring pre-sync state (Mode: %s)...", self.ip, state.active_mode or "unknown")

        # 1. Scene mode restoration
        if state.active_mode == "scene" and state.scene_id:
            builder = PilotBuilder(scene=state.scene_id, brightness=state.brightness)
            await self._safe_call(light.turn_on(builder))
            return

        # 2. Color Temperature (Tunable White) restoration
        if (state.active_mode == "colortemp" or (state.colortemp is not None and state.rgb is None)) and state.colortemp:
            if self.capabilities and not self.capabilities.supports_colortemp:
                logger.warning("[%s] Bulb hardware profile does not support color temp restoration", self.ip)
            else:
                builder = PilotBuilder(colortemp=state.colortemp, brightness=state.brightness)
                await self._safe_call(light.turn_on(builder))
                return

        # 3. RGB mode restoration
        if state.active_mode == "rgb" or (state.rgb is not None and any(c > 0 for c in state.rgb)):
            if self.capabilities and not self.capabilities.supports_rgb:
                logger.warning("[%s] Bulb hardware profile does not support RGB restoration", self.ip)
            else:
                r, g, b = state.rgb
                if state.brightness is not None:
                    await self.set_light_state(r, g, b, state.brightness)
                else:
                    builder = PilotBuilder(rgb=(r, g, b))
                    await self._safe_call(light.turn_on(builder))
                return

        # 4. White channel restoration (warm/cold white)
        if state.active_mode == "white" or (state.warm_white is not None or state.cold_white is not None):
            builder = PilotBuilder(warm_white=state.warm_white, cold_white=state.cold_white, brightness=state.brightness)
            await self._safe_call(light.turn_on(builder))
            return

        # 5. Brightness only
        if state.brightness is not None:
            await self.set_brightness(state.brightness)
            return

        # 6. Minimal fallback: turn bulb ON if state was ON
        await self.turn_on()

    async def turn_on(self) -> None:
        """Turn the bulb ON."""
        light = self._ensure_connected()
        logger.info("[%s] Sending command: TURN ON", self.ip)
        await self._safe_call(light.turn_on())

    async def turn_off(self) -> None:
        """Turn the bulb OFF."""
        light = self._ensure_connected()
        logger.info("[%s] Sending command: TURN OFF", self.ip)
        await self._safe_call(light.turn_off())

    async def set_brightness(self, brightness: int) -> None:
        """Set the bulb brightness.

        Args:
            brightness: Integer in the range [0, 255].
                        0 turns the bulb off. 1-255 sets brightness.

        Raises:
            ValidationError: If brightness is not an integer or outside [0, 255].
        """
        if not isinstance(brightness, int) or isinstance(brightness, bool):
            raise ValidationError(
                f"Brightness must be an integer, got {type(brightness).__name__}: {brightness}"
            )
        if not (0 <= brightness <= 255):
            raise ValidationError(
                f"Brightness must be in range [0, 255], got {brightness}"
            )

        if self.capabilities and not self.capabilities.supports_brightness:
            raise UnsupportedFeatureError("Bulb hardware does not support brightness adjustments.")

        light = self._ensure_connected()
        if brightness == 0:
            logger.info("[%s] Brightness 0 specified; turning bulb OFF", self.ip)
            await self._safe_call(light.turn_off())
        else:
            logger.info("[%s] Sending command: SET BRIGHTNESS %d/255", self.ip, brightness)
            await self._safe_call(light.turn_on(PilotBuilder(brightness=brightness)))

    async def set_rgb(self, r: int, g: int, b: int) -> None:
        """Set the bulb RGB color.

        Args:
            r: Red channel [0, 255].
            g: Green channel [0, 255].
            b: Blue channel [0, 255].

        Raises:
            ValidationError: If any channel is not an integer or outside [0, 255].
            UnsupportedFeatureError: If bulb does not support RGB color.
        """
        for name, val in (("Red", r), ("Green", g), ("Blue", b)):
            if not isinstance(val, int) or isinstance(val, bool):
                raise ValidationError(f"{name} channel must be an integer, got {type(val).__name__}: {val}")
            if not (0 <= val <= 255):
                raise ValidationError(f"{name} channel must be in range [0, 255], got {val}")

        if self.capabilities and not self.capabilities.supports_rgb:
            raise UnsupportedFeatureError(f"Bulb at {self.ip} does not support RGB color control.")

        light = self._ensure_connected()
        logger.info("[%s] Sending command: SET RGB (%d, %d, %d)", self.ip, r, g, b)
        await self._safe_call(light.turn_on(PilotBuilder(rgb=(r, g, b))))

    async def set_light_state(
        self,
        r: int,
        g: int,
        b: int,
        brightness: int,
        timeout: Optional[float] = None,
    ) -> None:
        """Set both RGB color and brightness in a single combined UDP message.

        Args:
            r: Red channel [0, 255].
            g: Green channel [0, 255].
            b: Blue channel [0, 255].
            brightness: Brightness level [0, 255]. If 0, turns bulb off.
            timeout: Optional custom timeout in seconds (useful for low-latency streaming).
        """
        for name, val in (("Red", r), ("Green", g), ("Blue", b)):
            if not isinstance(val, int) or isinstance(val, bool):
                raise ValidationError(f"{name} channel must be an integer, got {type(val).__name__}: {val}")
            if not (0 <= val <= 255):
                raise ValidationError(f"{name} channel must be in range [0, 255], got {val}")

        if not isinstance(brightness, int) or isinstance(brightness, bool):
            raise ValidationError(f"Brightness must be an integer, got {type(brightness).__name__}: {brightness}")
        if not (0 <= brightness <= 255):
            raise ValidationError(f"Brightness must be in range [0, 255], got {brightness}")

        if self.capabilities and not self.capabilities.supports_rgb:
            raise UnsupportedFeatureError(f"Bulb at {self.ip} does not support RGB color control.")

        light = self._ensure_connected()
        if brightness == 0:
            logger.debug("[%s] Streaming command: TURN OFF", self.ip)
            await self._safe_call(light.turn_off(), timeout=timeout)
        else:
            logger.debug("[%s] Streaming command: SET RGB (%d, %d, %d) @ %d/255", self.ip, r, g, b, brightness)
            builder = PilotBuilder(rgb=(r, g, b), brightness=brightness)
            await self._safe_call(light.turn_on(builder), timeout=timeout)

    async def set_colortemp(self, kelvin: int) -> None:
        """Set color temperature (tunable white) in Kelvin.

        Args:
            kelvin: Color temperature in Kelvin within the bulb's supported range.

        Raises:
            ValidationError: If kelvin is not an integer or outside supported range.
            UnsupportedFeatureError: If bulb does not support tunable white.
        """
        if not isinstance(kelvin, int) or isinstance(kelvin, bool):
            raise ValidationError(f"Color temperature must be an integer, got {type(kelvin).__name__}: {kelvin}")

        if self.capabilities and not self.capabilities.supports_colortemp:
            raise UnsupportedFeatureError(f"Bulb at {self.ip} does not support color temperature control.")

        min_k, max_k = (2200, 6500)
        if self.capabilities and self.capabilities.kelvin_range:
            min_k, max_k = self.capabilities.kelvin_range

        if not (min_k <= kelvin <= max_k):
            raise ValidationError(
                f"Color temperature {kelvin}K out of supported range [{min_k}K, {max_k}K]"
            )

        light = self._ensure_connected()
        logger.info("[%s] Sending command: SET COLOR TEMPERATURE %dK", self.ip, kelvin)
        await self._safe_call(light.turn_on(PilotBuilder(colortemp=kelvin)))

    async def close(self) -> None:
        """Clean up network socket and close connection."""
        self._is_connected = False
        if self._light:
            try:
                await self._light.async_close()
            except Exception as exc:
                logger.debug("Exception closing bulb %s: %s", self.ip, exc)
            finally:
                self._light = None

    async def disconnect(self) -> None:
        """Alias for close()."""
        await self.close()

    async def __aenter__(self) -> "WizBulbController":
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()
