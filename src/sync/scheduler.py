"""Rate-limited, coalescing command scheduler for WiZ UDP bulb communications."""

import asyncio
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional, Tuple

from src.sync.state import LightingState
from src.wiz.controller import (
    WizBulbController,
    WizConnectionError,
    WizControllerError,
    WizTimeoutError,
)

logger = logging.getLogger(__name__)


@dataclass
class SchedulerMetrics:
    """Live telemetry metrics for the bulb command scheduler."""

    commands_sent: int = 0
    commands_failed: int = 0
    consecutive_failures: int = 0
    last_command_duration_ms: float = 0.0
    average_duration_ms: float = 0.0
    updates_per_second: float = 0.0
    pending_state: Optional[LightingState] = None
    applied_state: Optional[LightingState] = None
    is_dry_run: bool = False
    rate_hz: float = 4.0


class BulbCommandScheduler:
    """Coordinates and rate-limits outbound WiZ network commands.

    Key capabilities:
    - Strictly limits outbound UDP transmission rate (1.0 - 10.0 Hz).
    - Guarantees non-overlapping commands using an execution lock.
    - Coalesces pending commands to always dispatch the latest target state.
    - Deadband suppression: skips transmission when RGB and brightness deltas
      are below perceptual thresholds compared to currently applied bulb state.
    - Adaptive backoff during network dropped packets / timeouts.
    - Thread-safe state submission from audio callbacks.
    - Fully functional dry-run mode for simulation and testing.
    """

    def __init__(
        self,
        controller: Optional[WizBulbController] = None,
        rate_hz: float = 4.0,
        rgb_threshold: int = 4,
        brightness_threshold: int = 4,
        command_timeout: float = 1.2,
        dry_run: bool = False,
    ) -> None:
        if not (1.0 <= rate_hz <= 10.0):
            raise ValueError(f"Rate must be between 1.0 and 10.0 Hz, got {rate_hz}")

        self.controller = controller
        self._rate_hz = float(rate_hz)
        self.rgb_threshold = rgb_threshold
        self.brightness_threshold = brightness_threshold
        self.command_timeout = command_timeout
        self.dry_run = dry_run

        self._pending_state: Optional[LightingState] = None
        self._applied_state: Optional[LightingState] = None
        self._state_lock = threading.Lock()
        self._send_lock = asyncio.Lock()

        self._running = False
        self._worker_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Telemetry
        self._commands_sent = 0
        self._commands_failed = 0
        self._consecutive_failures = 0
        self._last_duration_ms = 0.0
        self._duration_history: Deque[float] = deque(maxlen=20)
        self._timestamp_history: Deque[float] = deque(maxlen=30)

    @property
    def rate_hz(self) -> float:
        return self._rate_hz

    @rate_hz.setter
    def rate_hz(self, value: float) -> None:
        if not (1.0 <= value <= 10.0):
            raise ValueError(f"Rate must be between 1.0 and 10.0 Hz, got {value}")
        self._rate_hz = float(value)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def applied_state(self) -> Optional[LightingState]:
        return self._applied_state

    def submit(self, state: LightingState) -> None:
        """Submit a new target lighting state. Thread-safe and non-blocking.

        Always overwrites any unhandled pending state with the newest state.
        """
        with self._state_lock:
            self._pending_state = state

    async def start(self) -> None:
        """Start the rate-limited command dispatch worker loop."""
        if self._running:
            return
        self._running = True
        self._loop = asyncio.get_running_loop()
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info(
            "BulbCommandScheduler started (Rate: %.1f Hz, DryRun: %s)",
            self._rate_hz,
            self.dry_run,
        )

    async def stop(self) -> None:
        """Gracefully stop the scheduler worker loop."""
        if not self._running:
            return
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        logger.info("BulbCommandScheduler stopped cleanly")

    async def _worker_loop(self) -> None:
        """Background loop executing rate-limited command dispatches."""
        while self._running:
            start_time = time.perf_counter()
            try:
                await self._process_tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Unexpected error in scheduler worker tick: %s", exc, exc_info=True)

            elapsed = time.perf_counter() - start_time
            target_interval = 1.0 / self._rate_hz

            # Adaptive backoff if consecutive failures occur
            if self._consecutive_failures > 0:
                backoff_extra = min(1.0, 0.2 * self._consecutive_failures)
                target_interval += backoff_extra

            sleep_duration = max(0.005, target_interval - elapsed)
            try:
                await asyncio.sleep(sleep_duration)
            except asyncio.CancelledError:
                break

    async def _process_tick(self) -> None:
        """Process a single rate-limited dispatch tick."""
        with self._state_lock:
            target = self._pending_state
            self._pending_state = None

        if target is None:
            return

        # Deadband suppression: skip if perceptually identical to applied bulb state
        if target.is_similar_to(
            self._applied_state,
            rgb_threshold=self.rgb_threshold,
            brightness_threshold=self.brightness_threshold,
        ):
            logger.debug("Skipping dispatch (deadband match): %s", target)
            return

        # Ensure non-overlapping command execution
        async with self._send_lock:
            t0 = time.perf_counter()
            if self.dry_run:
                # Dry run mode: simulate successful transmission
                await asyncio.sleep(0.001)
                duration_ms = (time.perf_counter() - t0) * 1000.0
                self._applied_state = target
                self._commands_sent += 1
                self._consecutive_failures = 0
                self._record_telemetry(duration_ms)
                logger.debug("[DRY-RUN] Dispatched state: %s (%.1f ms)", target, duration_ms)
                return

            if self.controller is None or not self.controller.is_connected:
                self._commands_failed += 1
                self._consecutive_failures += 1
                logger.warning("Scheduler cannot dispatch: WiZ controller not connected")
                return

            try:
                r, g, b = target.rgb
                await self.controller.set_light_state(
                    r=r,
                    g=g,
                    b=b,
                    brightness=target.brightness if target.is_on else 0,
                    timeout=self.command_timeout,
                )
                duration_ms = (time.perf_counter() - t0) * 1000.0
                self._applied_state = target
                self._commands_sent += 1
                self._consecutive_failures = 0
                self._record_telemetry(duration_ms)
                logger.debug(
                    "Dispatched to bulb %s: %s (%.1f ms)",
                    self.controller.ip,
                    target,
                    duration_ms,
                )
            except (WizTimeoutError, WizConnectionError, WizControllerError, Exception) as exc:
                duration_ms = (time.perf_counter() - t0) * 1000.0
                self._commands_failed += 1
                self._consecutive_failures += 1
                self._last_duration_ms = duration_ms
                logger.warning(
                    "WiZ dispatch failed (%d consecutive): %s (%.1f ms)",
                    self._consecutive_failures,
                    exc,
                    duration_ms,
                )

    def _record_telemetry(self, duration_ms: float) -> None:
        """Update latency history and actual updates-per-second rate."""
        now = time.perf_counter()
        self._last_duration_ms = duration_ms
        self._duration_history.append(duration_ms)
        self._timestamp_history.append(now)

    def get_metrics(self) -> SchedulerMetrics:
        """Retrieve snapshot of scheduler metrics and performance."""
        now = time.perf_counter()
        # Compute sliding window updates per second (within last 3.0 seconds)
        recent_timestamps = [t for t in self._timestamp_history if now - t <= 3.0]
        if len(recent_timestamps) >= 2:
            time_span = recent_timestamps[-1] - recent_timestamps[0]
            rate = (len(recent_timestamps) - 1) / max(0.01, time_span)
        else:
            rate = 0.0

        avg_dur = (
            sum(self._duration_history) / len(self._duration_history)
            if self._duration_history
            else 0.0
        )

        with self._state_lock:
            pending = self._pending_state

        return SchedulerMetrics(
            commands_sent=self._commands_sent,
            commands_failed=self._commands_failed,
            consecutive_failures=self._consecutive_failures,
            last_command_duration_ms=self._last_duration_ms,
            average_duration_ms=avg_dur,
            updates_per_second=rate,
            pending_state=pending,
            applied_state=self._applied_state,
            is_dry_run=self.dry_run,
            rate_hz=self._rate_hz,
        )
