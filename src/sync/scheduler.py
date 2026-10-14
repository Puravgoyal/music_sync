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
class BeatEvent:
    """Latency-aware preserved beat transient event."""

    timestamp: float
    state: LightingState
    intensity: float = 0.0


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
    adaptive_rate: bool = False
    p95_duration_ms: float = 0.0
    consecutive_successes: int = 0


class BulbCommandScheduler:
    """Coordinates and rate-limits outbound WiZ network commands.

    Key capabilities:
    - Strictly limits outbound UDP transmission rate (1.0 - 10.0 Hz).
    - Guarantees non-overlapping commands using an execution lock.
    - Preserves fast beat-events between rate-limited ticks without unbounded queueing.
    - Configurable Adaptive Update Rate: steps up when link latency is low and stable,
      steps down immediately on packet loss or high round-trip latency.
    - Deadband suppression: skips transmission when RGB and brightness deltas
      are below perceptual thresholds compared to currently applied bulb state.
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
        adaptive_rate: bool = False,
        min_rate_hz: float = 3.5,
        max_rate_hz: float = 8.0,
        max_beat_age_s: float = 0.18,
    ) -> None:
        if not (1.0 <= rate_hz <= 10.0):
            raise ValueError(f"Rate must be between 1.0 and 10.0 Hz, got {rate_hz}")

        self.controller = controller
        self._rate_hz = float(rate_hz)
        self.rgb_threshold = rgb_threshold
        self.brightness_threshold = brightness_threshold
        self.command_timeout = command_timeout
        self.dry_run = dry_run
        self.adaptive_rate = adaptive_rate
        self.min_rate_hz = float(min_rate_hz)
        self.max_rate_hz = float(max_rate_hz)
        self.max_beat_age_s = float(max_beat_age_s)

        self._pending_state: Optional[LightingState] = None
        self._pending_beat: Optional[BeatEvent] = None
        self._applied_state: Optional[LightingState] = None
        self._state_lock = threading.Lock()
        self._send_lock = asyncio.Lock()

        self._running = False
        self._worker_task: Optional[asyncio.Task] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        # Telemetry & performance
        self._commands_sent = 0
        self._commands_failed = 0
        self._consecutive_failures = 0
        self._consecutive_successes = 0
        self._last_duration_ms = 0.0
        self._p95_duration_ms = 0.0
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

    def submit(
        self,
        state: LightingState,
        is_beat: bool = False,
        beat_intensity: float = 0.0,
    ) -> None:
        """Submit a new target lighting state. Thread-safe and non-blocking.

        If is_beat is True, preserves the beat event so fast audio attacks
        are not overwritten by subsequent decay frames between network dispatches.
        """
        now = time.perf_counter()
        with self._state_lock:
            self._pending_state = state
            if is_beat:
                if (
                    self._pending_beat is None
                    or (now - self._pending_beat.timestamp > self.max_beat_age_s)
                    or beat_intensity >= self._pending_beat.intensity
                ):
                    self._pending_beat = BeatEvent(timestamp=now, state=state, intensity=beat_intensity)

    async def start(self) -> None:
        """Start the rate-limited command dispatch worker loop."""
        if self._running:
            return
        self._running = True
        self._loop = asyncio.get_running_loop()
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info(
            "BulbCommandScheduler started (Rate: %.1f Hz, Adaptive: %s, DryRun: %s)",
            self._rate_hz,
            self.adaptive_rate,
            self.dry_run,
        )

    def clear(self) -> None:
        """Atomically discard any queued pending state or beat events."""
        with self._state_lock:
            self._pending_state = None
            self._pending_beat = None

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
        with self._state_lock:
            self._pending_state = None
            self._pending_beat = None
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
        """Process a single rate-limited dispatch tick with beat preservation."""
        now = time.perf_counter()
        target: Optional[LightingState] = None
        with self._state_lock:
            # Check for fresh preserved beat event first
            if self._pending_beat is not None:
                if (now - self._pending_beat.timestamp) <= self.max_beat_age_s:
                    target = self._pending_beat.state
                self._pending_beat = None

            if target is None:
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
                self._consecutive_successes += 1
                self._record_telemetry(duration_ms)
                if self.adaptive_rate:
                    self._adapt_rate_on_success()
                logger.debug("[DRY-RUN] Dispatched state: %s (%.1f ms)", target, duration_ms)
                return

            if self.controller is None or not self.controller.is_connected:
                self._commands_failed += 1
                self._consecutive_failures += 1
                self._consecutive_successes = 0
                if self.adaptive_rate:
                    self._adapt_rate_on_failure()
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
                self._consecutive_successes += 1
                self._record_telemetry(duration_ms)
                if self.adaptive_rate:
                    self._adapt_rate_on_success()
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
                self._consecutive_successes = 0
                self._last_duration_ms = duration_ms
                if self.adaptive_rate:
                    self._adapt_rate_on_failure()
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

        if len(self._duration_history) >= 5:
            sorted_durations = sorted(self._duration_history)
            idx = int(0.95 * len(sorted_durations))
            self._p95_duration_ms = sorted_durations[min(idx, len(sorted_durations) - 1)]
        else:
            self._p95_duration_ms = duration_ms

    def _adapt_rate_on_success(self) -> None:
        """Evaluate link conditions and step up or step down rate in adaptive mode."""
        if self._consecutive_successes >= 10 and len(self._duration_history) >= 8:
            if self._p95_duration_ms < 55.0 and self._rate_hz < self.max_rate_hz:
                new_rate = min(self.max_rate_hz, round(self._rate_hz + 0.5, 1))
                if new_rate != self._rate_hz:
                    logger.info("Adaptive rate stepped UP: %.1f Hz -> %.1f Hz (p95: %.1f ms)", self._rate_hz, new_rate, self._p95_duration_ms)
                    self._rate_hz = new_rate
                    self._consecutive_successes = 0
            elif self._p95_duration_ms > 110.0 and self._rate_hz > self.min_rate_hz:
                new_rate = max(self.min_rate_hz, round(self._rate_hz - 0.5, 1))
                if new_rate != self._rate_hz:
                    logger.info("Adaptive rate stepped DOWN due to latency: %.1f Hz -> %.1f Hz (p95: %.1f ms)", self._rate_hz, new_rate, self._p95_duration_ms)
                    self._rate_hz = new_rate
                    self._consecutive_successes = 0

    def _adapt_rate_on_failure(self) -> None:
        """Immediately drop rate on transmission failure or timeout."""
        if self._rate_hz > self.min_rate_hz:
            new_rate = max(self.min_rate_hz, round(self._rate_hz - 1.0, 1))
            if new_rate != self._rate_hz:
                logger.warning("Adaptive rate stepped DOWN due to failure: %.1f Hz -> %.1f Hz", self._rate_hz, new_rate)
                self._rate_hz = new_rate

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
            adaptive_rate=self.adaptive_rate,
            p95_duration_ms=self._p95_duration_ms,
            consecutive_successes=self._consecutive_successes,
        )
