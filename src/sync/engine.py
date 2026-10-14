"""Unified real-time synchronization engine for Music, Screen Ambience, and Hybrid AV."""

import asyncio
from enum import Enum
import logging
import threading
import time
from typing import Optional

from src.audio.analyzer import AudioMetrics
from src.audio.beat_detector import AudioFocus
from src.audio.capture import AudioCapture, CaptureStats
from src.audio.devices import AudioDevice, get_default_output_device, get_device_by_index
from src.effects import BaseMusicEffect, EffectSettings, get_effect
from src.effects.hybrid_av import HybridAVProcessor, HybridAVSettings, HybridType
from src.screen.analyzer import ScreenAnalyzerSettings, ScreenColorAnalyzer
from src.screen.capture import BaseCaptureBackend, CaptureStats as ScreenStats, ScreenCaptureManager
from src.screen.devices import ScreenMonitor, get_available_monitors, get_monitor_by_index
from src.sync.scheduler import BulbCommandScheduler
from src.sync.state import LightingState, RestorationReport, RestorationResult, SyncStatus
from src.wiz.controller import BulbState, WizBulbController

logger = logging.getLogger(__name__)


class SyncMode(Enum):
    """Synchronization source modes."""

    MUSIC = "music"
    SCREEN = "screen"
    HYBRID = "hybrid"


class MusicSyncEngine:
    """Unified engine coordinating Audio Capture, Screen Capture, Effects, and rate-limited WiZ transmission.

    Supports three primary synchronization modes:
    1. Mode A - Music Sync: WASAPI -> Audio Analysis -> Music Effect -> LightingState -> Scheduler -> WiZ.
    2. Mode B - Screen Sync: Windows Display -> Color Extraction -> Temporal Smoother -> LightingState -> Scheduler -> WiZ.
    3. Mode C - Hybrid AV Sync: Screen Video (RGB) + WASAPI Audio (Loudness/Beats) -> AV Fusion -> LightingState -> Scheduler -> WiZ.

    Core architectural guarantees:
    - Exactly one active session controls the WiZ bulb.
    - Exactly one rate-limited BulbCommandScheduler transmits to the bulb (conservative 4 Hz default).
    - No overlapping UDP network commands.
    - Original bulb state is captured once on start and restored accurately on stop.
    - Transactional startup rollback on failure.
    - Thread-safe across GUI, audio worker, screen capture, and asyncio event loop threads.
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
        audio_focus: AudioFocus = AudioFocus.FULL_MUSIC,
        adaptive_rate: bool = False,
        sync_mode: SyncMode = SyncMode.MUSIC,
        screen_monitor_index: int = 0,
        color_strategy: str = "average",
        edge_region: str = "all",
        edge_thickness: float = 0.15,
        smoothing_preset: str = "cinematic",
        detect_black_bars: bool = True,
        hybrid_type: str = "cinematic",
        audio_contribution: float = 0.35,
        screen_capture_fps: float = 12.0,
        custom_capture_backend: Optional[BaseCaptureBackend] = None,
    ) -> None:
        self.bulb_ip = bulb_ip
        self.audio_device_index = audio_device_index
        self.effect_name = effect_name
        self.settings = effect_settings or EffectSettings()
        self.update_rate_hz = update_rate_hz
        self.dry_run = dry_run
        self.restore_state = restore_state
        self.audio_focus = audio_focus
        self.adaptive_rate = adaptive_rate
        self.settings.audio_focus = self.audio_focus

        # Screen & Hybrid configuration
        if isinstance(sync_mode, str):
            try:
                self.sync_mode = SyncMode(sync_mode.lower())
            except Exception:
                self.sync_mode = SyncMode.MUSIC
        else:
            self.sync_mode = sync_mode

        self.screen_monitor_index = screen_monitor_index
        self.color_strategy = color_strategy
        self.edge_region = edge_region
        self.edge_thickness = edge_thickness
        self.smoothing_preset = smoothing_preset
        self.detect_black_bars = detect_black_bars
        self.hybrid_type = hybrid_type
        self.audio_contribution = audio_contribution
        self.screen_capture_fps = screen_capture_fps
        self.custom_capture_backend = custom_capture_backend

        # Thread synchronization locks
        self._effect_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._lifecycle_lock = asyncio.Lock()

        # Audio effect
        self._effect: BaseMusicEffect = get_effect(self.effect_name, settings=self.settings)

        # Screen analyzer
        analyzer_settings = ScreenAnalyzerSettings(
            color_strategy=self.color_strategy,
            edge_region=self.edge_region,
            edge_thickness=self.edge_thickness,
            smoothing_preset=self.smoothing_preset,
            detect_black_bars=self.detect_black_bars,
            min_brightness=self.settings.min_brightness,
            max_brightness=self.settings.max_brightness,
        )
        self._screen_analyzer = ScreenColorAnalyzer(settings=analyzer_settings)

        # Hybrid AV processor
        try:
            ht = HybridType(self.hybrid_type.lower())
        except Exception:
            ht = HybridType.CINEMATIC
        hybrid_settings = HybridAVSettings(
            hybrid_type=ht,
            audio_contribution=self.audio_contribution,
            beat_intensity=self.settings.beat_strength,
            min_brightness=self.settings.min_brightness,
            max_brightness=self.settings.max_brightness,
            audio_focus=self.audio_focus,
        )
        self._hybrid_processor = HybridAVProcessor(settings=hybrid_settings)

        # Hardware and engine subcomponents
        self._controller: Optional[WizBulbController] = None
        self._scheduler: Optional[BulbCommandScheduler] = None
        self._capture: Optional[AudioCapture] = None
        self._screen_capture: Optional[ScreenCaptureManager] = None
        self._selected_device: Optional[AudioDevice] = None
        self._selected_monitor: Optional[ScreenMonitor] = None

        self._pre_sync_state: Optional[BulbState] = None
        self._is_running = False

        # Live telemetry buffers
        self._last_metrics: Optional[AudioMetrics] = None
        self._last_stats: Optional[CaptureStats] = None
        self._last_screen_stats: Optional[ScreenStats] = None
        self._last_video_state: LightingState = LightingState()
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
    def screen_capture(self) -> Optional[ScreenCaptureManager]:
        return self._screen_capture

    @property
    def screen_analyzer(self) -> ScreenColorAnalyzer:
        return self._screen_analyzer

    @property
    def hybrid_processor(self) -> HybridAVProcessor:
        return self._hybrid_processor

    @property
    def last_metrics(self) -> Optional[AudioMetrics]:
        with self._state_lock:
            return self._last_metrics

    @property
    def last_stats(self) -> Optional[CaptureStats]:
        with self._state_lock:
            return self._last_stats

    @property
    def last_screen_stats(self) -> Optional[ScreenStats]:
        if self._screen_capture:
            return self._screen_capture.stats
        return self._last_screen_stats

    def set_effect(self, name: str, settings: Optional[EffectSettings] = None) -> None:
        """Switch active music lighting effect on the fly. Thread-safe."""
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
        if getattr(settings, "audio_focus", None) is not None:
            self.set_audio_focus(settings.audio_focus)
        if self._scheduler:
            self._scheduler.rate_hz = settings.update_rate_hz

        # Propagate brightness limits to screen analyzer and hybrid processor
        analyzer_settings = ScreenAnalyzerSettings(
            color_strategy=self.color_strategy,
            edge_region=self.edge_region,
            edge_thickness=self.edge_thickness,
            smoothing_preset=self.smoothing_preset,
            detect_black_bars=self.detect_black_bars,
            min_brightness=settings.min_brightness,
            max_brightness=settings.max_brightness,
        )
        self._screen_analyzer.update_settings(analyzer_settings)

        h_settings = HybridAVSettings(
            hybrid_type=self._hybrid_processor.settings.hybrid_type,
            audio_contribution=self.audio_contribution,
            beat_intensity=settings.beat_strength,
            min_brightness=settings.min_brightness,
            max_brightness=settings.max_brightness,
            audio_focus=self.audio_focus,
        )
        self._hybrid_processor.update_settings(h_settings)

        logger.info("Updated effect settings: sensitivity=%.2f, max_b=%d", settings.sensitivity, settings.max_brightness)

    def set_audio_focus(self, focus: AudioFocus) -> None:
        """Switch audio focus mode (full, rhythm, kick) on the fly."""
        self.audio_focus = focus
        if self._capture:
            self._capture.audio_focus = focus
        with self._effect_lock:
            self.settings.audio_focus = focus
            if self._effect:
                self._effect.settings.audio_focus = focus
        self._hybrid_processor.settings.audio_focus = focus
        logger.info("Switched active audio focus mode to: %s", getattr(focus, "value", focus))

    def set_screen_settings(
        self,
        color_strategy: Optional[str] = None,
        edge_region: Optional[str] = None,
        edge_thickness: Optional[float] = None,
        smoothing_preset: Optional[str] = None,
        detect_black_bars: Optional[bool] = None,
    ) -> None:
        """Update screen color extraction settings on the fly."""
        if color_strategy is not None:
            self.color_strategy = color_strategy
        if edge_region is not None:
            self.edge_region = edge_region
        if edge_thickness is not None:
            self.edge_thickness = edge_thickness
        if smoothing_preset is not None:
            self.smoothing_preset = smoothing_preset
        if detect_black_bars is not None:
            self.detect_black_bars = detect_black_bars

        settings = ScreenAnalyzerSettings(
            color_strategy=self.color_strategy,
            edge_region=self.edge_region,
            edge_thickness=self.edge_thickness,
            smoothing_preset=self.smoothing_preset,
            detect_black_bars=self.detect_black_bars,
            min_brightness=self.settings.min_brightness,
            max_brightness=self.settings.max_brightness,
        )
        self._screen_analyzer.update_settings(settings)
        logger.info("Updated screen settings: strategy=%s, preset=%s", self.color_strategy, self.smoothing_preset)

    def set_hybrid_settings(
        self,
        hybrid_type: Optional[str] = None,
        audio_contribution: Optional[float] = None,
    ) -> None:
        """Update hybrid AV parameters on the fly."""
        if hybrid_type is not None:
            self.hybrid_type = hybrid_type
            try:
                self._hybrid_processor.settings.hybrid_type = HybridType(hybrid_type.lower())
            except Exception:
                pass
        if audio_contribution is not None:
            self.audio_contribution = max(0.0, min(1.0, float(audio_contribution)))
            self._hybrid_processor.settings.audio_contribution = self.audio_contribution
        logger.info("Updated hybrid settings: type=%s, contrib=%.2f", self.hybrid_type, self.audio_contribution)

    def set_adaptive_rate(self, enabled: bool) -> None:
        """Toggle adaptive update rate mode on the fly."""
        self.adaptive_rate = enabled
        if self._scheduler:
            self._scheduler.adaptive_rate = enabled
        logger.info("Adaptive update rate set to: %s", enabled)

    async def start(self) -> None:
        """Start the synchronization engine with transactional startup and rollback on error."""
        async with self._lifecycle_lock:
            if self._is_running:
                logger.warning("MusicSyncEngine is already running")
                return

            stages_completed: list[str] = []
            logger.info("Starting WiZ Sync Engine (Mode: %s)...", self.sync_mode.value.upper())

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

                    # Ensure bulb is powered on for synchronization
                    if not self._controller.is_on:
                        logger.info("Turning bulb ON for synchronization")
                        await self._controller.turn_on()
                        stages_completed.append("bulb_powered_on")
                elif self.dry_run:
                    logger.info("Running in DRY-RUN mode (hardware transmission disabled)")

                # Stage 2: Shared rate-limited Bulb Command Scheduler
                self._scheduler = BulbCommandScheduler(
                    controller=self._controller,
                    rate_hz=self.update_rate_hz,
                    dry_run=self.dry_run,
                    adaptive_rate=self.adaptive_rate,
                )
                await self._scheduler.start()
                stages_completed.append("scheduler")

                # Stage 3: Audio Capture initialization (for MUSIC and HYBRID modes)
                if self.sync_mode in (SyncMode.MUSIC, SyncMode.HYBRID):
                    if self.audio_device_index is not None:
                        self._selected_device = get_device_by_index(self.audio_device_index)
                    else:
                        self._selected_device = get_default_output_device()

                    device_name = self._selected_device.name if self._selected_device else "Default Output"
                    logger.info("Selected audio capture device: %s", device_name)

                    self._capture = AudioCapture(
                        device=self._selected_device,
                        frames_per_buffer=1024,
                        on_metrics=self._handle_audio_metrics,
                        audio_focus=self.audio_focus,
                    )
                    self._capture.start()
                    stages_completed.append("audio_capture")

                # Stage 4: Screen Capture initialization (for SCREEN and HYBRID modes)
                if self.sync_mode in (SyncMode.SCREEN, SyncMode.HYBRID):
                    self._selected_monitor = get_monitor_by_index(self.screen_monitor_index)
                    logger.info("Selected screen capture monitor: %s", self._selected_monitor.display_name)

                    self._screen_analyzer.reset()
                    self._screen_capture = ScreenCaptureManager(
                        monitor_index=self.screen_monitor_index,
                        target_fps=self.screen_capture_fps,
                        downsample_size=(64, 36),
                        on_frame=self._handle_screen_frame,
                        custom_backend=self.custom_capture_backend,
                    )
                    if not self._screen_capture.start():
                        raise RuntimeError(f"Failed to initialize screen capture on monitor {self.screen_monitor_index}")
                    stages_completed.append("screen_capture")

                self._is_running = True
                logger.info("SyncEngine started successfully in %s mode", self.sync_mode.value.upper())

            except Exception as exc:
                logger.error("Startup failed at stage %s: %s. Initiating transactional rollback...", stages_completed, exc)
                await self._rollback_startup(stages_completed)
                raise

    async def _rollback_startup(self, stages: list[str]) -> None:
        """Safely rollback all previously acquired resources on startup failure."""
        # 1. Stop screen capture if initialized
        if self._screen_capture:
            try:
                self._screen_capture.stop()
            except Exception as exc:
                logger.debug("Rollback: Error stopping screen capture: %s", exc)
            self._screen_capture = None

        # 2. Stop audio capture if initialized
        if self._capture:
            try:
                self._capture.stop()
            except Exception as exc:
                logger.debug("Rollback: Error stopping audio capture: %s", exc)
            self._capture = None

        # 3. Stop scheduler if initialized
        if self._scheduler:
            try:
                await self._scheduler.stop()
            except Exception as exc:
                logger.debug("Rollback: Error stopping scheduler: %s", exc)
            self._scheduler = None

        # 4. Restore bulb state if bulb was powered on or modified
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

    def _handle_screen_frame(self, frame, timestamp: float) -> None:
        """Callback executed per analyzed screen frame (~10-15 FPS) from screen capture thread."""
        try:
            target_state = self._screen_analyzer.process_frame(frame, timestamp)

            with self._state_lock:
                self._last_video_state = target_state

            if self.sync_mode == SyncMode.SCREEN:
                with self._state_lock:
                    self._last_target_state = target_state

                if self._scheduler:
                    self._scheduler.submit(target_state, is_beat=False, beat_intensity=0.0)

            elif self.sync_mode == SyncMode.HYBRID:
                with self._state_lock:
                    cur_metrics = self._last_metrics

                fused_state, is_beat, beat_str = self._hybrid_processor.process(
                    target_state, cur_metrics, timestamp
                )

                with self._state_lock:
                    self._last_target_state = fused_state

                if self._scheduler:
                    self._scheduler.submit(fused_state, is_beat=is_beat, beat_intensity=beat_str)

        except Exception as exc:
            logger.error("Error processing screen frame in analyzer: %s", exc, exc_info=True)

    def _handle_audio_metrics(self, metrics: AudioMetrics, stats: CaptureStats) -> None:
        """Callback executed per analyzed audio frame (~46 FPS) from audio worker thread."""
        now = time.perf_counter()
        try:
            with self._state_lock:
                self._last_metrics = metrics
                self._last_stats = stats

            if self.sync_mode == SyncMode.MUSIC:
                with self._effect_lock:
                    target_state = self._effect.process(metrics, now)

                with self._state_lock:
                    self._last_target_state = target_state

                if self._scheduler:
                    focus = getattr(metrics, "audio_focus", self.audio_focus)
                    if focus == "rhythm" or getattr(focus, "value", None) == "rhythm":
                        is_beat = metrics.is_percussion
                        beat_str = metrics.percussion_strength
                    elif focus == "kick" or getattr(focus, "value", None) == "kick":
                        is_beat = metrics.is_kick
                        beat_str = metrics.kick_strength
                    else:
                        is_beat = metrics.is_onset
                        beat_str = metrics.onset_strength
                    self._scheduler.submit(target_state, is_beat=is_beat, beat_intensity=beat_str)

            elif self.sync_mode == SyncMode.HYBRID:
                with self._state_lock:
                    video_state = self._last_video_state

                fused_state, is_beat, beat_str = self._hybrid_processor.process(
                    video_state, metrics, now
                )

                with self._state_lock:
                    self._last_target_state = fused_state

                if self._scheduler:
                    self._scheduler.submit(fused_state, is_beat=is_beat, beat_intensity=beat_str)

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

            logger.info("Stopping SyncEngine...")
            self._is_running = False

            # 1. Stop screen capture
            if self._screen_capture:
                try:
                    self._last_screen_stats = self._screen_capture.stats
                    self._screen_capture.stop()
                except Exception as exc:
                    logger.error("Error stopping screen capture: %s", exc)
                self._screen_capture = None

            # 2. Stop audio capture
            if self._capture:
                try:
                    self._capture.stop()
                except Exception as exc:
                    logger.error("Error stopping audio capture: %s", exc)
                self._capture = None

            # 3. Stop rate-limited scheduler
            if self._scheduler:
                try:
                    self._last_scheduler_metrics = self._scheduler.get_metrics()
                    await self._scheduler.stop()
                except Exception as exc:
                    logger.error("Error stopping command scheduler: %s", exc)
                self._scheduler = None

            # 4. Restore pre-sync bulb state
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

            # 5. Disconnect controller
            if self._controller:
                try:
                    await self._controller.disconnect()
                except Exception as exc:
                    logger.error("Error disconnecting WiZ controller: %s", exc)
                self._controller = None

            logger.info("SyncEngine shut down cleanly (Restoration: %s)", resto_report)
            return resto_report

    async def _restore_bulb_state(self, state: BulbState) -> None:
        """Restore bulb to its state before synchronization began."""
        if not self._controller or not self._controller.is_connected:
            return
        await self._controller.restore_state(state)

    def get_status(self) -> SyncStatus:
        """Retrieve live synchronization status and metrics snapshot. Thread-safe."""
        with self._state_lock:
            target = self._last_target_state
            raw_rgb = self._screen_analyzer.last_raw_rgb

        with self._effect_lock:
            if self.sync_mode == SyncMode.MUSIC:
                eff_name = self._effect.name
            elif self.sync_mode == SyncMode.SCREEN:
                eff_name = f"Screen Ambience ({self.color_strategy.capitalize()})"
            else:
                eff_name = f"Hybrid AV ({self.hybrid_type.capitalize()})"

        sched_metrics = (
            self._scheduler.get_metrics() if self._scheduler else self._last_scheduler_metrics
        )
        dev_name = self._selected_device.name if self._selected_device else None
        mon_name = self._selected_monitor.name if self._selected_monitor else None

        screen_fps = 0.0
        if self._screen_capture:
            screen_fps = self._screen_capture.stats.actual_fps

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
            audio_focus=getattr(self.audio_focus, "value", str(self.audio_focus)),
            adaptive_rate=sched_metrics.adaptive_rate if sched_metrics else self.adaptive_rate,
            p95_duration_ms=sched_metrics.p95_duration_ms if sched_metrics else 0.0,
            sync_mode=self.sync_mode.value,
            screen_fps=screen_fps,
            screen_color=raw_rgb,
            screen_monitor=mon_name,
            capture_health="OK" if self._screen_capture and self._screen_capture.is_running else "IDLE",
        )


# Forward compatibility alias
UnifiedSyncEngine = MusicSyncEngine
