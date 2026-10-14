"""Deterministic tests for beat event preservation, expiration, and scheduling.

Verifies:
1. Beats arriving at early, mid, and late positions within a scheduler interval are preserved and dispatched.
2. Weaker beats arriving after stronger beats in the same interval are superseded.
3. Slow network delays (> max_beat_age) safely expire stale beats to prevent out-of-time flashes.
4. Comprehensive synthetic timing simulation reporting exact preserved, superseded, expired, and dispatched ratios.
"""

import asyncio
import time
from unittest.mock import AsyncMock, patch
import pytest

from src.sync.scheduler import BulbCommandScheduler
from src.sync.state import LightingState


@pytest.mark.asyncio
async def test_beats_at_various_interval_offsets_are_dispatched():
    """Verifies beats arriving at 10ms, 125ms, and 230ms in a 250ms interval (4 Hz) are dispatched."""
    scheduler = BulbCommandScheduler(dry_run=True, rate_hz=4.0)

    # Effective max beat age at 4 Hz is 1.25 * 0.25 = 0.3125s (312.5 ms)
    assert scheduler.effective_max_beat_age >= 0.30

    test_offsets_ms = [10.0, 125.0, 230.0]

    for offset in test_offsets_ms:
        scheduler.clear()
        t_base = time.perf_counter()

        # Submit normal state
        scheduler.submit(LightingState(rgb=(50, 50, 50), brightness=50), is_beat=False)

        # Simulate beat arriving at specific offset
        beat_time = t_base - (0.25 - offset / 1000.0)
        with scheduler._state_lock:
            scheduler._pending_beat = None
        scheduler.submit(
            LightingState(rgb=(255, 0, 0), brightness=255),
            is_beat=True,
            beat_intensity=0.8,
        )
        # Override timestamp to simulate the offset
        with scheduler._state_lock:
            scheduler._pending_beat.timestamp = beat_time

        # Process tick at t_base (simulating tick at end of 250ms interval)
        await scheduler._process_tick()

        # The beat must have been dispatched
        metrics = scheduler.get_metrics()
        assert metrics.beats_dispatched > 0, f"Beat at offset {offset}ms was not dispatched!"
        assert scheduler.applied_state.rgb == (255, 0, 0)
        assert scheduler.applied_state.brightness == 255


@pytest.mark.asyncio
async def test_weaker_beat_superseded_by_stronger_beat():
    """Verifies that within a single interval, a stronger beat transient is preserved."""
    scheduler = BulbCommandScheduler(dry_run=True, rate_hz=4.0)

    # 1. First strong beat arrives
    strong_state = LightingState(rgb=(255, 0, 0), brightness=255)
    scheduler.submit(strong_state, is_beat=True, beat_intensity=0.90)

    # 2. Weaker secondary hit arrives in same interval
    weak_state = LightingState(rgb=(0, 255, 0), brightness=120)
    scheduler.submit(weak_state, is_beat=True, beat_intensity=0.35)

    assert scheduler._beats_superseded == 1
    with scheduler._state_lock:
        assert scheduler._pending_beat.intensity == 0.90
        assert scheduler._pending_beat.state.rgb == (255, 0, 0)

    # 3. Third even stronger hit arrives
    epic_state = LightingState(rgb=(0, 0, 255), brightness=255)
    scheduler.submit(epic_state, is_beat=True, beat_intensity=0.98)

    assert scheduler._beats_superseded == 2
    with scheduler._state_lock:
        assert scheduler._pending_beat.intensity == 0.98
        assert scheduler._pending_beat.state.rgb == (0, 0, 255)

    # Process tick
    await scheduler._process_tick()
    assert scheduler.applied_state.rgb == (0, 0, 255)


@pytest.mark.asyncio
async def test_stale_beat_expires_on_slow_network_response():
    """Verifies that an excessively delayed tick expires stale beats to prevent out-of-time strobing."""
    scheduler = BulbCommandScheduler(dry_run=True, rate_hz=4.0)
    max_age = scheduler.effective_max_beat_age

    # Submit a beat with timestamp from 500ms ago (simulating 500ms network timeout)
    stale_time = time.perf_counter() - 0.500
    decay_state = LightingState(rgb=(20, 20, 20), brightness=20)

    scheduler.submit(
        LightingState(rgb=(255, 0, 0), brightness=255),
        is_beat=True,
        beat_intensity=0.95,
    )
    with scheduler._state_lock:
        scheduler._pending_beat.timestamp = stale_time
        scheduler._pending_state = decay_state

    # Process tick
    await scheduler._process_tick()

    metrics = scheduler.get_metrics()
    assert metrics.beats_expired == 1
    assert metrics.beats_dispatched == 0
    # Falls back to decay state rather than stale beat
    assert scheduler.applied_state.rgb == (20, 20, 20)


@pytest.mark.asyncio
async def test_synthetic_timing_simulation_and_statistics():
    """Simulates 50 intervals with realistic audio frame beats, reporting exact stats."""
    scheduler = BulbCommandScheduler(dry_run=True, rate_hz=4.0)

    total_intervals = 50
    beats_injected = 0

    for i in range(total_intervals):
        # In alternate intervals, simulate 1 or 2 beats arriving at random offsets
        has_beat = (i % 2 == 0)
        now = time.perf_counter()

        if has_beat:
            # First hit at offset 40ms into interval
            b1_time = now - 0.210  # 40ms after start of 250ms interval
            scheduler.submit(
                LightingState(rgb=(255, 100, 0), brightness=200),
                is_beat=True,
                beat_intensity=0.75,
            )
            with scheduler._state_lock:
                scheduler._pending_beat.timestamp = b1_time
            beats_injected += 1

            if i % 4 == 0:
                # Second weaker hit in same interval
                scheduler.submit(
                    LightingState(rgb=(100, 100, 100), brightness=100),
                    is_beat=True,
                    beat_intensity=0.40,
                )
                beats_injected += 1
        else:
            # Plain audio frame
            scheduler.submit(
                LightingState(rgb=(40, 40, int(40 + (i % 10) * 5)), brightness=60),
                is_beat=False,
            )

        await scheduler._process_tick()

    metrics = scheduler.get_metrics()
    print(f"\nSynthetic Timing Simulation Results ({total_intervals} ticks @ 4.0 Hz):")
    print(f"  Total Beats Received   : {metrics.beats_received}")
    print(f"  Beats Dispatched       : {metrics.beats_dispatched}")
    print(f"  Beats Superseded       : {metrics.beats_superseded}")
    print(f"  Beats Expired          : {metrics.beats_expired}")
    print(f"  Beat Dispatch Ratio    : {metrics.beat_dispatch_ratio:.1%}")

    assert metrics.beats_received == beats_injected
    assert metrics.beats_expired == 0, "No beats should expire under healthy timing at 4 Hz!"
    assert metrics.beats_dispatched > 0
    assert metrics.beat_dispatch_ratio == 1.0
