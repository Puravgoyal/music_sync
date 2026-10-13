"""Unified real-time music-to-light synchronization engine."""

import asyncio
import logging
import time
from typing import Optional

from src.audio.analyzer import AudioMetrics
from src.audio.capture import AudioCapture, CaptureStats
from src.audio.devices import AudioDevice, get_default_output_device, get_device_by_index
from src.effects import BaseMusicEffect, EffectSettings, get_effect
from src.sync.scheduler import BulbCommandScheduler
from src.sync.state import LightingState, SyncStatus
from src.wiz.controller import BulbState, WizBulbController

logger = logging.getLogger(__name__)


class MusicSyncEngine:
    """Coordinates Windows audio capture, DSP analysis, lighting effects, and rate-limited WiZ transmission.

    Features:
    - Independent scheduling: Audio capture runs in high-priority worker thread,
      effects are computed per audio frame (~46 FPS), and WiZ bulb updates are
      strictly rate-limited and coalesced by BulbCommandScheduler (2-5 Hz).
    - Dynamic control: Switch effects, adjust sensitivity, brightness, and rates on the fly.
    - Pre-sync bulb state preservation and restoration on shutdown.
    - Robust error recovery and dry-run execution support.
    """

    def __init__(
        self,
        bulb_ip: Optional[str] = None,
        audio_device_index: Optional[int] = None,
        effect_name: str = "spectrum",
        effect_settings: Optional[EffectSettings] = None,
        update_rate_hz: float = 4.0,
        dry_run: bool = False,
        restore_state: bool = True,
    ) -> None:
        self.bulb_ip = bulb_ip
        self.audio_device_index = audio_device_index
        self.effect_name = effect_name
        self.settings = effect_settings or EffectSettings()
        self.update_rate_hz = update_rate_hz
        self.dry_run = dry_run
        self.restore_state = restore_state

        self._effect: BaseMusicEffect = get_effect(self.effect_name, settings=self.settings)
        self._controller: Optional[WizBulbController] = None
        self._scheduler: Optional[BulbCommandScheduler] = None
        self._capture: Optional[AudioCapture] = None
        self._selected_device: Optional[AudioDevice] = None

        self._pre_sync_state: Optional[BulbState] = None
        self._is_running = False
        self._last_metrics: Optional[AudioMetrics] = None
        self._last_stats: Optional[CaptureStats] = None
        self._last_target_state: LightingState = LightingState()

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def current_effect(self) -> BaseMusicEffect:
        return self._effect

    @property
    def scheduler(self) -> Optional[BulbCommandScheduler]:
        return self._scheduler

    @property
    def capture(self) -> Optional[AudioCapture]:
        return self._capture

    @property
    def last_metrics(self) -> Optional[AudioMetrics]:
        return self._last_metrics

    @property
    def last_stats(self) -> Optional[CaptureStats]:
        return self._last_stats

    def set_effect(self, name: str, settings: Optional[EffectSettings] = None) -> None:
        """Switch active lighting effect on the fly."""
        if settings is not None:
            self.settings = settings
        self._effect = get_effect(name, settings=self.settings)
        self.effect_name = name
        logger.info("Switched active lighting effect to: %s", self._effect.name)

    def set_settings(self, settings: EffectSettings) -> None:
        """Update effect settings for active effect."""
        settings.validate()
        self.settings = settings
        self._effect.settings = settings
        if self._scheduler:
            self._scheduler.rate_hz = settings.update_rate_hz
        logger.info("Updated effect settings: sensitivity=%.2f, max_b=%d", settings.sensitivity, settings.max_brightness)

    async def start(self) -> None:
        """Start the synchronization engine."""
        if self._is_running:
            logger.warning("MusicSyncEngine is already running")
            return

        logger.info("Starting WiZ Music Sync Engine...")

        # 1. Hardware Bulb Connection (unless dry run without bulb IP)
        if not self.dry_run and self.bulb_ip:
            logger.info("Initializing WiZ controller for %s...", self.bulb_ip)
            self._controller = WizBulbController(ip=self.bulb_ip)
            await self._controller.connect()

            # Record pre-sync state for clean restoration
            if self.restore_state:
                try:
                    self._pre_sync_state = await self._controller.get_state()
                    logger.info("Captured pre-sync bulb state: %s", self._pre_sync_state)
                except Exception as exc:
                    logger.warning("Could not query pre-sync bulb state: %s", exc)

            # Ensure bulb is powered on for music sync
            if not self._controller.is_on:
                logger.info("Turning bulb ON for synchronization")
                await self._controller.turn_on()
        elif self.dry_run:
            logger.info("Running in DRY-RUN mode (hardware transmission disabled)")

        # 2. Bulb Command Scheduler
        self._scheduler = BulbCommandScheduler(
            controller=self._controller,
            rate_hz=self.update_rate_hz,
            dry_run=self.dry_run,
        )
        await self._scheduler.start()

        # 3. Audio Device Resolution
        if self.audio_device_index is not None:
            self._selected_device = get_device_by_index(self.audio_device_index)
        else:
            self._selected_device = get_default_output_device()

        device_name = self._selected_device.name if self._selected_device else "Default Output"
        logger.info("Selected audio capture device: %s", device_name)

        # 4. Audio Capture Engine
        self._capture = AudioCapture(
            device=self._selected_device,
            frames_per_buffer=1024,
            on_metrics=self._handle_audio_metrics,
        )
        self._capture.start()

        self._is_running = True
        logger.info("MusicSyncEngine started successfully")

    def _handle_audio_metrics(self, metrics: AudioMetrics, stats: CaptureStats) -> None:
        """Callback executed per analyzed audio frame (~46 FPS) from audio worker thread."""
        now = time.perf_counter()
        self._last_metrics = metrics
        self._last_stats = stats

        try:
            # Process effect calculation (fast, sub-millisecond)
            target_state = self._effect.process(metrics, now)
            self._last_target_state = target_state

            # Submit to rate-limited scheduler (thread-safe, non-blocking)
            if self._scheduler:
                self._scheduler.submit(target_state)
        except Exception as exc:
            logger.error("Error processing audio frame in effect: %s", exc, exc_info=True)

    async def stop(self) -> None:
        """Gracefully stop synchronization, restore previous bulb state, and disconnect."""
        if not self._is_running:
            return

        logger.info("Stopping MusicSyncEngine...")
        self._is_running = False

        # 1. Stop audio capture
        if self._capture:
            try:
                self._capture.stop()
            except Exception as exc:
                logger.error("Error stopping audio capture: %s", exc)
            self._capture = None

        # 2. Stop rate-limited scheduler
        if self._scheduler:
            try:
                await self._scheduler.stop()
            except Exception as exc:
                logger.error("Error stopping command scheduler: %s", exc)
            self._scheduler = None

        # 3. Restore pre-sync bulb state
        if not self.dry_run and self._controller and self._controller.is_connected and self.restore_state and self._pre_sync_state:
            try:
                logger.info("Restoring pre-sync bulb state: %s", self._pre_sync_state)
                await self._restore_bulb_state(self._pre_sync_state)
            except Exception as exc:
                logger.warning("Failed to restore pre-sync bulb state: %s", exc)

        # 4. Disconnect controller
        if self._controller:
            try:
                await self._controller.disconnect()
            except Exception as exc:
                logger.error("Error disconnecting WiZ controller: %s", exc)
            self._controller = None

        logger.info("MusicSyncEngine shut down cleanly")

    async def _restore_bulb_state(self, state: BulbState) -> None:
        """Restore bulb to its state before music synchronization began."""
        if not self._controller:
            return

        if not state.is_on:
            await self._controller.turn_off()
            return

        # Bulb was ON
        if state.colortemp is not None and self._controller.capabilities.supports_colortemp:
            await self._controller.set_colortemp(state.colortemp)
            if state.brightness is not None:
                await self._controller.set_brightness(state.brightness)
        elif state.rgb is not None and self._controller.capabilities.supports_rgb:
            r, g, b = state.rgb
            brightness = state.brightness if state.brightness is not None else 128
            await self._controller.set_light_state(r, g, b, brightness)
        elif state.brightness is not None:
            await self._controller.set_brightness(state.brightness)
        else:
            await self._controller.turn_on()

    def get_status(self) -> SyncStatus:
        """Retrieve live synchronization status and metrics snapshot."""
        sched_metrics = self._scheduler.get_metrics() if self._scheduler else None
        dev_name = self._selected_device.name if self._selected_device else None

        return SyncStatus(
            is_running=self._is_running,
            current_effect=self._effect.name,
            bulb_ip=self.bulb_ip,
            audio_device=dev_name,
            target_state=self._last_target_state,
            applied_state=sched_metrics.applied_state if sched_metrics else None,
            updates_per_second=sched_metrics.updates_per_second if sched_metrics else 0.0,
            commands_sent=sched_metrics.commands_sent if sched_metrics else 0,
            commands_failed=sched_metrics.commands_failed if sched_metrics else 0,
            last_command_duration_ms=sched_metrics.last_command_duration_ms if sched_metrics else 0.0,
            is_dry_run=self.dry_run,
            pending_states_count=1 if (sched_metrics and sched_metrics.pending_state) else 0,
        )
