"""Background asynchronous worker bridge coordinating WiZ networking and music sync engine."""

import asyncio
import logging
import threading
from typing import Any, List, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from src.audio.analyzer import AudioMetrics
from src.audio.capture import CaptureStats
from src.effects import EffectSettings
from src.sync.engine import MusicSyncEngine
from src.sync.state import SyncStatus
from src.wiz.controller import WizBulbController
from src.wiz.discovery import DiscoveredDevice, discover_devices

logger = logging.getLogger(__name__)


class SyncWorker(QObject):
    """Qt-to-Asyncio event loop bridge for WiZ bulb networking and audio synchronization."""

    sync_started = Signal(str)  # bulb_ip
    sync_stopped = Signal()
    sync_error = Signal(str)  # error description
    bulbs_discovered = Signal(list)  # list of DiscoveredDevice
    bulb_tested = Signal(bool, str)  # (success, message)
    telemetry_updated = Signal(object, object, object)  # (SyncStatus, Optional[AudioMetrics], Optional[CaptureStats])

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._engine: Optional[MusicSyncEngine] = None
        self._is_syncing = False

        self._start_event_loop()

        # Telemetry polling timer (runs in Qt thread @ ~30 Hz)
        self._telemetry_timer = QTimer(self)
        self._telemetry_timer.setInterval(33)  # ~30 FPS UI refresh
        self._telemetry_timer.timeout.connect(self._poll_telemetry)

    def _start_event_loop(self) -> None:
        """Start a dedicated background thread running an asyncio event loop."""
        ready_event = threading.Event()

        def run_loop() -> None:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            ready_event.set()
            self._loop.run_forever()

        self._thread = threading.Thread(target=run_loop, name="WizAsyncLoopThread", daemon=True)
        self._thread.start()
        ready_event.wait()
        logger.info("Asyncio background loop thread initialized for Qt worker bridge")

    @property
    def is_syncing(self) -> bool:
        return self._is_syncing

    def discover_bulbs(self, timeout: float = 2.0) -> None:
        """Asynchronously scan the local network for WiZ smart bulbs."""
        if not self._loop:
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
        if not self._loop:
            return

        async def _do_test() -> None:
            try:
                controller = WizBulbController(ip=ip, timeout=3.5)
                await controller.connect()
                cap = controller.capabilities
                state = await controller.get_state()
                model = cap.model if cap else "ESP25 WiZ Bulb"
                fw = cap.firmware_version if cap else "Unknown"
                msg = f"Connected to {model} (FW: {fw}, MAC: {controller.mac or 'N/A'}) - Currently {state.is_on and 'ON' or 'OFF'}"
                await controller.disconnect()
                self.bulb_tested.emit(True, msg)
            except Exception as exc:
                self.bulb_tested.emit(False, f"Connection failed to {ip}: {exc}")

        asyncio.run_coroutine_threadsafe(_do_test(), self._loop)

    def start_sync(
        self,
        bulb_ip: Optional[str],
        audio_device_index: Optional[int],
        effect_name: str,
        settings: EffectSettings,
        restore_state: bool = True,
        dry_run: bool = False,
    ) -> None:
        """Start music synchronization on the background asyncio engine."""
        if not self._loop or self._is_syncing:
            return

        async def _do_start() -> None:
            try:
                self._engine = MusicSyncEngine(
                    bulb_ip=bulb_ip,
                    audio_device_index=audio_device_index,
                    effect_name=effect_name,
                    effect_settings=settings,
                    update_rate_hz=settings.update_rate_hz,
                    dry_run=dry_run,
                    restore_state=restore_state,
                )
                await self._engine.start()
                self._is_syncing = True
                self._telemetry_timer.start()
                self.sync_started.emit(bulb_ip or "DRY-RUN")
            except Exception as exc:
                logger.error("Failed to start synchronization: %s", exc, exc_info=True)
                self._is_syncing = False
                self._engine = None
                self.sync_error.emit(str(exc))

        asyncio.run_coroutine_threadsafe(_do_start(), self._loop)

    def stop_sync(self) -> None:
        """Stop music synchronization and restore bulb state."""
        if not self._loop or not self._is_syncing:
            return

        self._telemetry_timer.stop()

        async def _do_stop() -> None:
            try:
                if self._engine:
                    await self._engine.stop()
                    self._engine = None
            except Exception as exc:
                logger.error("Error stopping engine: %s", exc)
            finally:
                self._is_syncing = False
                self.sync_stopped.emit()

        asyncio.run_coroutine_threadsafe(_do_stop(), self._loop)

    def set_effect(self, name: str) -> None:
        """Switch active lighting effect dynamically. Thread-safe."""
        if self._engine and self._is_syncing:
            self._engine.set_effect(name)

    def set_settings(self, settings: EffectSettings) -> None:
        """Update effect settings dynamically. Thread-safe."""
        if self._engine and self._is_syncing:
            self._engine.set_settings(settings)

    def _poll_telemetry(self) -> None:
        """Periodic timer tick gathering status for UI visualization."""
        if not self._engine or not self._is_syncing:
            return

        try:
            status = self._engine.get_status()
            metrics = self._engine.last_metrics
            stats = self._engine.last_stats
            self.telemetry_updated.emit(status, metrics, stats)
        except Exception as exc:
            logger.debug("Telemetry polling skipped tick: %s", exc)

    def shutdown(self) -> None:
        """Cleanly tear down worker and stop event loop thread."""
        self._telemetry_timer.stop()
        if self._engine and self._is_syncing:
            future = asyncio.run_coroutine_threadsafe(self._engine.stop(), self._loop)
            try:
                future.result(timeout=4.0)
            except Exception:
                pass

        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("SyncWorker shutdown completed")
