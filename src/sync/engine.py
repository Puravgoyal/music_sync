"""Unified real-time music-to-light synchronization engine."""

import asyncio
import logging
import threading
import time
from typing import Optional

from src.audio.analyzer import AudioMetrics
from src.audio.capture import AudioCapture, CaptureStats
from src.audio.devices import AudioDevice, get_default_output_device, get_device_by_index
from src.effects import BaseMusicEffect, EffectSettings, get_effect
from src.sync.scheduler import BulbCommandScheduler
from src.sync.state import LightingState, RestorationReport, RestorationResult, SyncStatus
from src.wiz.controller import BulbState, WizBulbController

logger = logging.getLogger(__name__)


class MusicSyncEngine:
    """Coordinates Windows audio capture, DSP analysis, lighting effects, and rate-limited WiZ transmission.

    Features:
    - Transactional startup & clean rollback: failure at any initialization stage safely releases
      all previously acquired resources and permits clean retries.
    - Accurate bulb state restoration: restores the exact active mode (RGB, colortemp, scene, white, power)
      without inventing arbitrary defaults.
    - Thread-safe concurrency: safe effect switching, settings updates, and telemetry access across
      the audio callback thread, asyncio event loop, and GUI threads.
    - Independent scheduling: Audio capture runs in high-priority worker thread,
      effects are computed per audio frame (~46 FPS), and WiZ bulb updates are
      strictly rate-limited and coalesced by BulbCommandScheduler (2-5 Hz).
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

        # Thread synchronization locks
        self._effect_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._lifecycle_lock = asyncio.Lock()

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
        self._last_scheduler_metrics = None

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def current_effect(self) -> BaseMusicEffect:
        with self._effect_lock:
            return self._effect

    @property
    def scheduler(self) -> Optional[BulbCommandScheduler]:
        return self._scheduler

    @property
    def capture(self) -> Optional[AudioCapture]:
        return self._capture

    @property
    def last_metrics(self) -> Optional[AudioMetrics]:
        with self._state_lock:
            return self._last_metrics

    @property
    def last_stats(self) -> Optional[CaptureStats]:
        with self._state_lock:
            return self._last_stats

    def set_effect(self, name: str, settings: Optional[EffectSettings] = None) -> None:
        """Switch active lighting effect on the fly. Thread-safe."""
        with self._effect_lock:
            if settings is not None:
                self.settings = settings
            self._effect = get_effect(name, settings=self.settings)
            self.effect_name = name
        logger.info("Switched active lighting effect to: %s", self._effect.name)

    def set_settings(self, settings: EffectSettings) -> None:
        """Update effect settings for active effect. Thread-safe."""
        settings.validate()
        with self._effect_lock:
            self.settings = settings
            self._effect.settings = settings
        if self._scheduler:
            self._scheduler.rate_hz = settings.update_rate_hz
        logger.info("Updated effect settings: sensitivity=%.2f, max_b=%d", settings.sensitivity, settings.max_brightness)

    async def start(self) -> None:
        """Start the synchronization engine with transactional startup and rollback on error."""
        async with self._lifecycle_lock:
            if self._is_running:
                logger.warning("MusicSyncEngine is already running")
                return

            stages_completed: list[str] = []
            logger.info("Starting WiZ Music Sync Engine...")

            try:
                # Stage 1: Hardware Bulb Connection (unless dry run without bulb IP)
                if not self.dry_run and self.bulb_ip:
                    logger.info("Initializing WiZ controller for %s...", self.bulb_ip)
                    self._controller = WizBulbController(ip=self.bulb_ip)
                    await self._controller.connect()
                    stages_completed.append("controller_connected")

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
                        stages_completed.append("bulb_powered_on")
                elif self.dry_run:
                    logger.info("Running in DRY-RUN mode (hardware transmission disabled)")

                # Stage 2: Bulb Command Scheduler
                self._scheduler = BulbCommandScheduler(
                    controller=self._controller,
                    rate_hz=self.update_rate_hz,
                    dry_run=self.dry_run,
                )
                await self._scheduler.start()
                stages_completed.append("scheduler")

                # Stage 3: Audio Device Resolution
                if self.audio_device_index is not None:
                    self._selected_device = get_device_by_index(self.audio_device_index)
                else:
                    self._selected_device = get_default_output_device()

                device_name = self._selected_device.name if self._selected_device else "Default Output"
                logger.info("Selected audio capture device: %s", device_name)

                # Stage 4: Audio Capture Engine
                self._capture = AudioCapture(
                    device=self._selected_device,
                    frames_per_buffer=1024,
                    on_metrics=self._handle_audio_metrics,
                )
                self._capture.start()
                stages_completed.append("capture")

                self._is_running = True
                logger.info("MusicSyncEngine started successfully")

            except Exception as exc:
                logger.error("Startup failed at stage %s: %s. Initiating transactional rollback...", stages_completed, exc)
                await self._rollback_startup(stages_completed)
                raise

    async def _rollback_startup(self, stages: list[str]) -> None:
        """Safely rollback all previously acquired resources on startup failure."""
        # 1. Stop capture if initialized
        if self._capture:
            try:
                self._capture.stop()
            except Exception as exc:
                logger.debug("Rollback: Error stopping audio capture: %s", exc)
            self._capture = None

        # 2. Stop scheduler if initialized
        if self._scheduler:
            try:
                await self._scheduler.stop()
            except Exception as exc:
                logger.debug("Rollback: Error stopping scheduler: %s", exc)
            self._scheduler = None

        # 3. Restore bulb state if bulb was powered on or modified
        if self._controller:
            if "bulb_powered_on" in stages and self.restore_state and self._pre_sync_state and self._controller.is_connected:
                try:
                    await self._controller.restore_state(self._pre_sync_state)
                except Exception as exc:
                    logger.debug("Rollback: Error restoring bulb state: %s", exc)
            try:
                await self._controller.disconnect()
            except Exception as exc:
                logger.debug("Rollback: Error disconnecting controller: %s", exc)
            self._controller = None

        self._is_running = False
        logger.info("Startup rollback completed cleanly")

    def _handle_audio_metrics(self, metrics: AudioMetrics, stats: CaptureStats) -> None:
        """Callback executed per analyzed audio frame (~46 FPS) from audio worker thread."""
        now = time.perf_counter()
        try:
            with self._effect_lock:
                target_state = self._effect.process(metrics, now)

            with self._state_lock:
                self._last_metrics = metrics
                self._last_stats = stats
                self._last_target_state = target_state

            if self._scheduler:
                self._scheduler.submit(target_state)
        except Exception as exc:
            logger.error("Error processing audio frame in effect: %s", exc, exc_info=True)

    async def stop(self) -> RestorationReport:
        """Gracefully stop synchronization, restore previous bulb state, and disconnect.

        Returns:
            RestorationReport with explicit outcome (SUCCESS, SKIPPED, UNAVAILABLE, FAILED).
        """
        async with self._lifecycle_lock:
            if not self._is_running:
                return RestorationReport(RestorationResult.SKIPPED, "Engine was not running")

            logger.info("Stopping MusicSyncEngine...")
            self._is_running = False

            # 1. Stop audio capture FIRST to cease inbound audio frames
            if self._capture:
                try:
                    self._capture.stop()
                except Exception as exc:
                    logger.error("Error stopping audio capture: %s", exc)
                self._capture = None

            # 2. Stop rate-limited scheduler
            if self._scheduler:
                try:
                    self._last_scheduler_metrics = self._scheduler.get_metrics()
                    await self._scheduler.stop()
                except Exception as exc:
                    logger.error("Error stopping command scheduler: %s", exc)
                self._scheduler = None

            # 3. Restore pre-sync bulb state (no competing network traffic exists now)
            resto_report: RestorationReport
            if self.dry_run:
                resto_report = RestorationReport(RestorationResult.SKIPPED, "Dry-run mode (no hardware modified)")
            elif not self.restore_state:
                resto_report = RestorationReport(RestorationResult.SKIPPED, "User disabled state restoration")
            elif not self._pre_sync_state:
                resto_report = RestorationReport(RestorationResult.UNAVAILABLE, "Pre-sync state was not captured")
            elif not self._controller or not self._controller.is_connected:
                resto_report = RestorationReport(RestorationResult.FAILED, "Bulb controller disconnected prior to restore")
            else:
                try:
                    logger.info("Restoring pre-sync bulb state: %s", self._pre_sync_state)
                    await self._restore_bulb_state(self._pre_sync_state)
                    mode_name = self._pre_sync_state.active_mode or "original"
                    resto_report = RestorationReport(RestorationResult.SUCCESS, f"Restored {mode_name} state")
                except Exception as exc:
                    logger.warning("Failed to restore pre-sync bulb state: %s", exc)
                    resto_report = RestorationReport(RestorationResult.FAILED, str(exc))

            # 4. Disconnect controller
            if self._controller:
                try:
                    await self._controller.disconnect()
                except Exception as exc:
                    logger.error("Error disconnecting WiZ controller: %s", exc)
                self._controller = None

            logger.info("MusicSyncEngine shut down cleanly (Restoration: %s)", resto_report)
            return resto_report

    async def _restore_bulb_state(self, state: BulbState) -> None:
        """Restore bulb to its state before music synchronization began."""
        if not self._controller or not self._controller.is_connected:
            return
        await self._controller.restore_state(state)

    def get_status(self) -> SyncStatus:
        """Retrieve live synchronization status and metrics snapshot. Thread-safe."""
        with self._state_lock:
            target = self._last_target_state

        with self._effect_lock:
            eff_name = self._effect.name

        sched_metrics = (
            self._scheduler.get_metrics() if self._scheduler else self._last_scheduler_metrics
        )
        dev_name = self._selected_device.name if self._selected_device else None

        return SyncStatus(
            is_running=self._is_running,
            current_effect=eff_name,
            bulb_ip=self.bulb_ip,
            audio_device=dev_name,
            target_state=target,
            applied_state=sched_metrics.applied_state if sched_metrics else None,
            updates_per_second=sched_metrics.updates_per_second if sched_metrics else 0.0,
            commands_sent=sched_metrics.commands_sent if sched_metrics else 0,
            commands_failed=sched_metrics.commands_failed if sched_metrics else 0,
            last_command_duration_ms=sched_metrics.last_command_duration_ms if sched_metrics else 0.0,
            is_dry_run=self.dry_run,
            pending_states_count=1 if (sched_metrics and sched_metrics.pending_state) else 0,
        )
