"""Tests for BulbCommandScheduler: rate-limiting, coalescing, deadband filter, and error handling."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.sync.scheduler import BulbCommandScheduler
from src.sync.state import LightingState
from src.wiz.controller import WizBulbController, WizConnectionError, WizTimeoutError


class TestSchedulerInitialization:
    """Test scheduler initialization and rate validation."""

    def test_default_rate_is_valid(self) -> None:
        scheduler = BulbCommandScheduler(dry_run=True)
        assert scheduler.rate_hz == 4.0
        assert scheduler.dry_run is True

    @pytest.mark.parametrize("invalid_rate", [0.5, 0.0, -1.0, 11.0, 50.0])
    def test_invalid_rates_raise_value_error(self, invalid_rate: float) -> None:
        with pytest.raises(ValueError, match="between 1.0 and 10.0"):
            BulbCommandScheduler(rate_hz=invalid_rate)

    def test_dynamic_rate_change(self) -> None:
        scheduler = BulbCommandScheduler(rate_hz=4.0)
        scheduler.rate_hz = 8.0
        assert scheduler.rate_hz == 8.0
        with pytest.raises(ValueError):
            scheduler.rate_hz = 0.2


@pytest.mark.asyncio
class TestSchedulerExecution:
    """Async tests for scheduler operations and state management."""

    async def test_coalescing_keeps_latest_state(self) -> None:
        scheduler = BulbCommandScheduler(rate_hz=5.0, dry_run=True)
        # Submit 3 states in rapid succession
        s1 = LightingState(rgb=(255, 0, 0), brightness=100)
        s2 = LightingState(rgb=(0, 255, 0), brightness=150)
        s3 = LightingState(rgb=(0, 0, 255), brightness=200)

        scheduler.submit(s1)
        scheduler.submit(s2)
        scheduler.submit(s3)

        # Before any tick, pending state should be s3
        metrics = scheduler.get_metrics()
        assert metrics.pending_state == s3

    async def test_deadband_suppression_skips_dispatch(self) -> None:
        scheduler = BulbCommandScheduler(rate_hz=5.0, rgb_threshold=5, brightness_threshold=5, dry_run=True)
        # Establish applied state
        initial = LightingState(rgb=(100, 100, 100), brightness=100)
        scheduler.submit(initial)
        await scheduler._process_tick()
        assert scheduler.applied_state == initial
        assert scheduler.get_metrics().commands_sent == 1

        # Submit nearly identical state within thresholds
        similar = LightingState(rgb=(102, 101, 99), brightness=102)
        scheduler.submit(similar)
        await scheduler._process_tick()

        # Should be skipped, commands_sent remains 1
        assert scheduler.get_metrics().commands_sent == 1
        assert scheduler.applied_state == initial

    async def test_deadband_dispatches_when_exceeding_threshold(self) -> None:
        scheduler = BulbCommandScheduler(rate_hz=5.0, rgb_threshold=5, brightness_threshold=5, dry_run=True)
        initial = LightingState(rgb=(100, 100, 100), brightness=100)
        scheduler.submit(initial)
        await scheduler._process_tick()
        assert scheduler.get_metrics().commands_sent == 1

        # Submit state exceeding RGB threshold
        different = LightingState(rgb=(115, 100, 100), brightness=100)
        scheduler.submit(different)
        await scheduler._process_tick()

        # Should be dispatched
        assert scheduler.get_metrics().commands_sent == 2
        assert scheduler.applied_state == different

    async def test_dry_run_does_not_call_controller(self) -> None:
        mock_controller = MagicMock(spec=WizBulbController)
        mock_controller.set_light_state = AsyncMock()
        mock_controller.is_connected = True

        scheduler = BulbCommandScheduler(controller=mock_controller, rate_hz=5.0, dry_run=True)
        target = LightingState(rgb=(200, 50, 50), brightness=150)
        scheduler.submit(target)
        await scheduler._process_tick()

        mock_controller.set_light_state.assert_not_called()
        assert scheduler.applied_state == target
        assert scheduler.get_metrics().commands_sent == 1

    async def test_live_dispatch_calls_controller_set_light_state(self) -> None:
        mock_controller = MagicMock(spec=WizBulbController)
        mock_controller.set_light_state = AsyncMock()
        mock_controller.is_connected = True
        mock_controller.ip = "192.168.1.4"

        scheduler = BulbCommandScheduler(controller=mock_controller, rate_hz=5.0, dry_run=False)
        target = LightingState(rgb=(120, 200, 50), brightness=180)
        scheduler.submit(target)
        await scheduler._process_tick()

        mock_controller.set_light_state.assert_awaited_once_with(
            r=120, g=200, b=50, brightness=180, timeout=scheduler.command_timeout
        )
        assert scheduler.applied_state == target
        assert scheduler.get_metrics().commands_sent == 1
        assert scheduler.get_metrics().commands_failed == 0

    async def test_live_dispatch_error_increments_failure_and_backs_off(self) -> None:
        mock_controller = MagicMock(spec=WizBulbController)
        mock_controller.set_light_state = AsyncMock(side_effect=WizTimeoutError("UDP timeout"))
        mock_controller.is_connected = True
        mock_controller.ip = "192.168.1.4"

        scheduler = BulbCommandScheduler(controller=mock_controller, rate_hz=5.0, dry_run=False)
        target = LightingState(rgb=(120, 200, 50), brightness=180)
        scheduler.submit(target)
        await scheduler._process_tick()

        assert scheduler.get_metrics().commands_failed == 1
        assert scheduler.get_metrics().consecutive_failures == 1
        assert scheduler.applied_state is None

    async def test_scheduler_lifecycle_start_and_stop(self) -> None:
        scheduler = BulbCommandScheduler(rate_hz=8.0, dry_run=True)
        assert not scheduler.is_running
        await scheduler.start()
        assert scheduler.is_running

        # Submit state while worker loop is running
        target = LightingState(rgb=(50, 100, 150), brightness=80)
        scheduler.submit(target)
        await asyncio.sleep(0.15)

        # Worker should have dispatched state
        assert scheduler.applied_state == target
        await scheduler.stop()
        assert not scheduler.is_running
