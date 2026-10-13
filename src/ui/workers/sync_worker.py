"""Background asynchronous worker bridge coordinating WiZ networking and music sync engine."""

import asyncio
from enum import Enum, auto
import logging
import threading
from typing import Any, List, Optional, Tuple

from PySide6.QtCore import QObject, Signal

from src.audio.analyzer import AudioMetrics
from src.audio.capture import CaptureStats
from src.effects import EffectSettings
from src.sync.engine import MusicSyncEngine
from src.sync.state import RestorationReport, RestorationResult, SyncStatus
from src.wiz.controller import WizBulbController
from src.wiz.discovery import DiscoveredDevice, discover_devices

logger = logging.getLogger(__name__)


class SyncState(Enum):
    """Explicit lifecycle states for synchronization engine."""

    IDLE = auto()
    STARTING = auto()
    RUNNING = auto()
    STOPPING = auto()
    CLOSED = auto()


class SyncWorker(QObject):
    """Qt-to-Asyncio event loop bridge for WiZ bulb networking and audio synchronization.

    Guarantees strict Qt thread affinity:
    - All QObject methods and signals execute cleanly without cross-thread QTimer operations.
    - Lifecycle transitions (IDLE -> STARTING -> RUNNING -> STOPPING -> CLOSED) are synchronized
      and race-free.
    """

    state_changed = Signal(object)  # SyncState
    sync_started = Signal(str)  # bulb_ip
    sync_stopped = Signal()
    sync_error = Signal(str)  # error description
    bulbs_discovered = Signal(list)  # list of DiscoveredDevice
    bulb_tested = Signal(bool, str)  # (success, message)
    restoration_completed = Signal(object)  # RestorationReport
    closed = Signal()  # Emitted when background loop and worker are fully terminated

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._engine: Optional[MusicSyncEngine] = None

        self._state_lock = threading.RLock()
        self._state = SyncState.IDLE
        self._stop_requested = False
        self._close_requested = False
        self._last_restoration_report: Optional[RestorationReport] = None

        self._start_event_loop()

    def _start_event_loop(self) -> None:
        """Start a dedicated background thread running an asyncio event loop."""
        ready_event = threading.Event()

        def run_loop() -> None:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            ready_event.set()
            try:
                self._loop.run_forever()
            finally:
                try:
                    # Cancel any lingering tasks and cleanly shut down async generators
                    pending = [t for t in asyncio.all_tasks(self._loop) if not t.done()]
                    for task in pending:
                        task.cancel()
                    if pending:
                        self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    self._loop.run_until_complete(self._loop.shutdown_asyncgens())
                except Exception as exc:
                    logger.debug("Error during event loop task cleanup: %s", exc)
                finally:
                    self._loop.close()
                    logger.info("Asyncio background loop closed cleanly in worker thread")

        self._thread = threading.Thread(target=run_loop, name="WizAsyncLoopThread", daemon=True)
        self._thread.start()
        ready_event.wait()
        logger.info("Asyncio background loop thread initialized for Qt worker bridge")

    @property
    def state(self) -> SyncState:
        with self._state_lock:
            return self._state

    @property
    def is_syncing(self) -> bool:
        with self._state_lock:
            return self._state in (SyncState.STARTING, SyncState.RUNNING)

    @property
    def last_restoration_report(self) -> Optional[RestorationReport]:
        return self._last_restoration_report

    @property
    def thread(self) -> Optional[threading.Thread]:
        """Expose background thread for termination verification in tests."""
        return self._thread

    def discover_bulbs(self, timeout: float = 2.0) -> None:
        """Asynchronously scan the local network for WiZ smart bulbs."""
        if not self._loop or self._state == SyncState.CLOSED:
            return

        async def _do_discover() -> None:
            try:
                logger.info("Scanning for WiZ bulbs (timeout: %.1fs)...", timeout)
                devices: List[DiscoveredDevice] = await discover_devices(timeout=timeout, fetch_details=True)
                self.bulbs_discovered.emit(devices)
            except Exception as exc:
                logger.error("Error during bulb discovery: %s", exc)
                self.bulbs_discovered.emit([])

        asyncio.run_coroutine_threadsafe(_do_discover(), self._loop)

    def test_connection(self, ip: str) -> None:
        """Asynchronously test connectivity and retrieve device profile for a bulb IP."""
        if not self._loop or self._state == SyncState.CLOSED:
            return

        async def _do_test() -> None:
            controller: Optional[WizBulbController] = None
            try:
                controller = WizBulbController(ip=ip, timeout=3.5)
                await controller.connect()
                cap = controller.capabilities
                state = await controller.get_state()
                model = cap.model if cap else "ESP25 WiZ Bulb"
                fw = cap.firmware_version if cap else "Unknown"
                msg = f"Connected to {model} (FW: {fw}, MAC: {controller.mac or 'N/A'}) - Currently {state.is_on and 'ON' or 'OFF'}"
                self.bulb_tested.emit(True, msg)
            except Exception as exc:
                self.bulb_tested.emit(False, f"Connection failed to {ip}: {exc}")
            finally:
                if controller:
                    try:
                        await controller.disconnect()
                    except Exception as disc_exc:
                        logger.debug("Error disconnecting test controller: %s", disc_exc)

        asyncio.run_coroutine_threadsafe(_do_test(), self._loop)

    def start_sync(
        self,
        bulb_ip: Optional[str],
        audio_device_index: Optional[int],
        effect_name: str,
        settings: EffectSettings,
        restore_state: bool = True,
        dry_run: bool = False,
    ) -> bool:
        """Start music synchronization on the background asyncio engine.

        Returns:
            True if startup transition began, False if rejected (e.g. not IDLE).
        """
        if not self._loop:
            return False

        with self._state_lock:
            if self._state != SyncState.IDLE:
                logger.warning("Rejected start_sync: current state is %s", self._state.name)
                return False
            self._state = SyncState.STARTING
            self._stop_requested = False
            self._close_requested = False

        self.state_changed.emit(SyncState.STARTING)

        async def _do_start() -> None:
            try:
                # Check cancellation prior to heavy initialization
                with self._state_lock:
                    if self._stop_requested or self._close_requested:
                        logger.info("Startup cancelled before initialization began")
                        self._state = SyncState.IDLE
                        self.state_changed.emit(SyncState.IDLE)
                        if self._close_requested:
                            self._finalize_closed()
                        return

                engine = MusicSyncEngine(
                    bulb_ip=bulb_ip,
                    audio_device_index=audio_device_index,
                    effect_name=effect_name,
                    effect_settings=settings,
                    update_rate_hz=settings.update_rate_hz,
                    dry_run=dry_run,
                    restore_state=restore_state,
                )
                self._engine = engine
                await engine.start()

                # Check if stop or close was requested during startup
                should_stop = False
                with self._state_lock:
                    if self._stop_requested or self._close_requested:
                        logger.info("Stop or close requested during STARTING; initiating immediate stop.")
                        self._state = SyncState.STOPPING
                        should_stop = True
                    else:
                        self._state = SyncState.RUNNING

                if should_stop:
                    self.state_changed.emit(SyncState.STOPPING)
                    await self._do_stop_coro()
                else:
                    self.sync_started.emit(bulb_ip or "DRY-RUN")
                    self.state_changed.emit(SyncState.RUNNING)

            except Exception as exc:
                logger.error("Failed to start synchronization: %s", exc, exc_info=True)
                with self._state_lock:
                    self._state = SyncState.IDLE
                    self._engine = None
                    was_close_requested = self._close_requested

                self.sync_error.emit(str(exc))
                self.state_changed.emit(SyncState.IDLE)

                if was_close_requested:
                    self._finalize_closed()

        asyncio.run_coroutine_threadsafe(_do_start(), self._loop)
        return True

    def stop_sync(self) -> None:
        """Stop music synchronization and restore bulb state."""
        if not self._loop:
            return

        with self._state_lock:
            if self._state == SyncState.STARTING:
                # Flag to abort/stop as soon as startup completes
                self._stop_requested = True
                logger.info("Stop requested while STARTING. Marked for cancellation.")
                return
            elif self._state != SyncState.RUNNING:
                logger.debug("stop_sync ignored: state is %s", self._state.name)
                return

            self._state = SyncState.STOPPING

        self.state_changed.emit(SyncState.STOPPING)
        asyncio.run_coroutine_threadsafe(self._do_stop_coro(), self._loop)

    async def _do_stop_coro(self) -> None:
        """Internal asynchronous stop and state restoration coroutine."""
        report: Optional[RestorationReport] = None
        try:
            if self._engine:
                report = await self._engine.stop()
                self._last_restoration_report = report
                self._engine = None
        except Exception as exc:
            logger.error("Error stopping engine: %s", exc)
            report = RestorationReport(RestorationResult.FAILED, str(exc))
            self._last_restoration_report = report
        finally:
            with self._state_lock:
                was_close_requested = self._close_requested
                if not was_close_requested:
                    self._state = SyncState.IDLE

            if report:
                self.restoration_completed.emit(report)
            self.sync_stopped.emit()
            if not was_close_requested:
                self.state_changed.emit(SyncState.IDLE)
            else:
                self._finalize_closed()

    def set_effect(self, name: str) -> None:
        """Switch active lighting effect dynamically. Thread-safe."""
        if self._engine and self.is_syncing:
            self._engine.set_effect(name)

    def set_settings(self, settings: EffectSettings) -> None:
        """Update effect settings dynamically. Thread-safe."""
        if self._engine and self.is_syncing:
            self._engine.set_settings(settings)

    def get_telemetry_snapshot(
        self,
    ) -> Tuple[Optional[SyncStatus], Optional[AudioMetrics], Optional[CaptureStats]]:
        """Retrieve thread-safe telemetry snapshot for GUI rendering without cross-thread QTimer."""
        engine = self._engine
        if not engine:
            return None, None, None
        try:
            return engine.get_status(), engine.last_metrics, engine.last_stats
        except Exception as exc:
            logger.debug("Error taking telemetry snapshot: %s", exc)
            return None, None, None

    def request_close(self) -> None:
        """Request graceful shutdown of sync and background loop prior to window close."""
        with self._state_lock:
            if self._state == SyncState.CLOSED:
                return
            self._close_requested = True

            if self._state == SyncState.IDLE:
                self._finalize_closed()
                return
            elif self._state == SyncState.STARTING:
                self._stop_requested = True
                logger.info("Window close requested while STARTING.")
                return
            elif self._state == SyncState.RUNNING:
                self._state = SyncState.STOPPING
                self.state_changed.emit(SyncState.STOPPING)
                asyncio.run_coroutine_threadsafe(self._do_stop_coro(), self._loop)

    def _finalize_closed(self) -> None:
        """Mark worker closed, stop asyncio loop, and emit closed signal."""
        with self._state_lock:
            self._state = SyncState.CLOSED

        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

        self.closed.emit()
        self.state_changed.emit(SyncState.CLOSED)
        logger.info("SyncWorker closed cleanly")

    def shutdown_loop(self, timeout: float = 2.0) -> None:
        """Synchronously stop event loop thread if caller is external."""
        self.request_close()
        if self._thread and self._thread.is_alive() and threading.current_thread() != self._thread:
            self._thread.join(timeout=timeout)
