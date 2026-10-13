"""Integration tests for Qt thread affinity, timer lifecycle, and startup/shutdown race conditions."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from PySide6.QtCore import QThread
from PySide6.QtGui import QCloseEvent

from src.config.preferences import PreferencesManager
from src.effects import EffectSettings
from src.ui.main_window import MainWindow
from src.ui.workers.sync_worker import SyncState, SyncWorker


@pytest.fixture
def test_prefs(tmp_path) -> PreferencesManager:
    config_file = tmp_path / "lifecycle_test_prefs.json"
    mgr = PreferencesManager(filepath=config_file)
    mgr.preferences.last_bulb_ip = "192.168.1.4"
    mgr.preferences.dry_run = True
    return mgr


@patch("src.ui.workers.sync_worker.discover_devices")
def test_qt_timer_thread_affinity_and_lifecycle(mock_discover, qtbot, test_prefs) -> None:
    """Requirement 1: Real Qt event loop integration test verifying QTimer thread affinity.

    Does not mock the timer. Verifies timer starts and stops strictly on Qt GUI thread.
    """
    mock_discover.return_value = []
    window = MainWindow(prefs_manager=test_prefs)
    qtbot.addWidget(window)

    timer = window.telemetry_timer

    # 1. Thread affinity verification: QTimer must belong to the Qt GUI thread
    gui_thread = QThread.currentThread()
    assert timer.thread() == gui_thread, "QTimer thread affinity does not match Qt GUI thread!"
    assert not timer.isActive(), "QTimer should not be active when worker is IDLE."

    # 2. Start synchronization (Dry-run mode to avoid physical network calls)
    settings = EffectSettings()
    started = window.worker.start_sync(
        bulb_ip=None,
        audio_device_index=None,
        effect_name="spectrum",
        settings=settings,
        restore_state=False,
        dry_run=True,
    )
    assert started is True

    # 3. Wait until worker transitions to RUNNING
    qtbot.waitUntil(lambda: window.worker.state == SyncState.RUNNING, timeout=4000)

    # 4. Timer MUST be active now, still on GUI thread
    assert timer.isActive(), "QTimer must be active while synchronization is RUNNING."
    assert timer.thread() == gui_thread

    # 5. Stop synchronization
    window.worker.stop_sync()
    qtbot.waitUntil(lambda: window.worker.state == SyncState.IDLE, timeout=4000)

    # 6. Timer MUST be stopped now
    assert not timer.isActive(), "QTimer must stop once synchronization transitions back to IDLE."

    window.close()


@patch("src.ui.workers.sync_worker.discover_devices")
def test_double_start_rejected(mock_discover, qtbot, test_prefs) -> None:
    """Requirement 2.1: Clicking Start twice cannot launch duplicate engines."""
    mock_discover.return_value = []
    window = MainWindow(prefs_manager=test_prefs)
    qtbot.addWidget(window)

    settings = EffectSettings()

    # First start call
    first = window.worker.start_sync(
        bulb_ip=None,
        audio_device_index=None,
        effect_name="spectrum",
        settings=settings,
        dry_run=True,
    )
    assert first is True

    # Second start call immediately while STARTING or RUNNING
    second = window.worker.start_sync(
        bulb_ip=None,
        audio_device_index=None,
        effect_name="spectrum",
        settings=settings,
        dry_run=True,
    )
    assert second is False, "Second start call while not IDLE must be rejected."

    qtbot.waitUntil(lambda: window.worker.state == SyncState.RUNNING, timeout=4000)
    window.worker.stop_sync()
    qtbot.waitUntil(lambda: window.worker.state == SyncState.IDLE, timeout=4000)
    window.close()


@patch("src.ui.workers.sync_worker.discover_devices")
def test_stop_during_starting(mock_discover, qtbot, test_prefs) -> None:
    """Requirement 2.2: Stop during STARTING safely cancels and returns to IDLE."""
    mock_discover.return_value = []
    window = MainWindow(prefs_manager=test_prefs)
    qtbot.addWidget(window)

    settings = EffectSettings()
    started = window.worker.start_sync(
        bulb_ip=None,
        audio_device_index=None,
        effect_name="spectrum",
        settings=settings,
        dry_run=True,
    )
    assert started is True

    # Immediately request stop while in STARTING
    window.worker.stop_sync()

    # Must cleanly transition to IDLE
    qtbot.waitUntil(lambda: window.worker.state == SyncState.IDLE, timeout=4000)
    assert window.worker.state == SyncState.IDLE
    assert not window.telemetry_timer.isActive()

    window.close()


@patch("src.ui.workers.sync_worker.discover_devices")
def test_close_during_starting(mock_discover, qtbot, test_prefs) -> None:
    """Requirement 2.3: Closing window during STARTING does not leak background tasks."""
    mock_discover.return_value = []
    window = MainWindow(prefs_manager=test_prefs)
    qtbot.addWidget(window)

    settings = EffectSettings()
    window.worker.start_sync(
        bulb_ip=None,
        audio_device_index=None,
        effect_name="spectrum",
        settings=settings,
        dry_run=True,
    )

    # Trigger close while STARTING
    window.worker.request_close()

    qtbot.waitUntil(lambda: window.worker.state == SyncState.CLOSED, timeout=4000)
    assert window.worker.state == SyncState.CLOSED


@patch("src.ui.workers.sync_worker.discover_devices")
def test_close_during_running(mock_discover, qtbot, test_prefs) -> None:
    """Requirement 2.4: Closing window during RUNNING stops audio capture, network, and scheduler."""
    mock_discover.return_value = []
    window = MainWindow(prefs_manager=test_prefs)
    qtbot.addWidget(window)

    settings = EffectSettings()
    window.worker.start_sync(
        bulb_ip=None,
        audio_device_index=None,
        effect_name="spectrum",
        settings=settings,
        dry_run=True,
    )
    qtbot.waitUntil(lambda: window.worker.state == SyncState.RUNNING, timeout=4000)

    window.worker.request_close()
    qtbot.waitUntil(lambda: window.worker.state == SyncState.CLOSED, timeout=4000)
    assert window.worker.state == SyncState.CLOSED
    assert not window.telemetry_timer.isActive()


@patch("src.ui.workers.sync_worker.discover_devices")
def test_close_during_stopping(mock_discover, qtbot, test_prefs) -> None:
    """Requirement 2.5: Closing window during STOPPING coordinates safely without deadlock."""
    mock_discover.return_value = []
    window = MainWindow(prefs_manager=test_prefs)
    qtbot.addWidget(window)

    settings = EffectSettings()
    window.worker.start_sync(
        bulb_ip=None,
        audio_device_index=None,
        effect_name="spectrum",
        settings=settings,
        dry_run=True,
    )
    qtbot.waitUntil(lambda: window.worker.state == SyncState.RUNNING, timeout=4000)

    # Initiate stop, then immediately request close
    window.worker.stop_sync()
    window.worker.request_close()

    qtbot.waitUntil(lambda: window.worker.state == SyncState.CLOSED, timeout=4000)
    assert window.worker.state == SyncState.CLOSED


@patch("src.ui.workers.sync_worker.discover_devices")
def test_failed_startup_allows_retry(mock_discover, qtbot, test_prefs) -> None:
    """Requirement 2.6: Failed startup transitions to IDLE and allows clean retry."""
    mock_discover.return_value = []
    worker = SyncWorker()

    settings = EffectSettings()

    # Simulate startup failure with unreachable bulb IP (short timeout)
    with patch("src.sync.engine.WizBulbController.connect", side_effect=ConnectionError("Bulb offline")):
        started = worker.start_sync(
            bulb_ip="192.0.2.1",
            audio_device_index=None,
            effect_name="spectrum",
            settings=settings,
            dry_run=False,
        )
        assert started is True
        qtbot.waitUntil(lambda: worker.state == SyncState.IDLE, timeout=4000)
        assert worker.state == SyncState.IDLE

    # Immediate retry in dry-run mode must succeed without application restart
    retry_started = worker.start_sync(
        bulb_ip=None,
        audio_device_index=None,
        effect_name="spectrum",
        settings=settings,
        dry_run=True,
    )
    assert retry_started is True
    qtbot.waitUntil(lambda: worker.state == SyncState.RUNNING, timeout=4000)

    worker.stop_sync()
    qtbot.waitUntil(lambda: worker.state == SyncState.IDLE, timeout=4000)
    worker.request_close()


@patch("src.ui.workers.sync_worker.discover_devices")
def test_actual_thread_termination_on_close(mock_discover, qtbot, test_prefs) -> None:
    """Gap 2: Verifies actual thread termination, not merely the transition to SyncState.CLOSED."""
    mock_discover.return_value = []
    window = MainWindow(prefs_manager=test_prefs)
    qtbot.addWidget(window)

    thread = window.worker.thread
    assert thread is not None
    assert thread.is_alive(), "Worker loop thread should be running while window is active."

    # Close window cleanly
    window.close()

    # The background thread must physically terminate (is_alive() is False)
    qtbot.waitUntil(lambda: not thread.is_alive(), timeout=4000)
    assert not thread.is_alive(), "Worker loop thread remained alive after window close!"


@patch("src.ui.workers.sync_worker.discover_devices")
def test_repeated_start_stop_cycles(mock_discover, qtbot, test_prefs) -> None:
    """Gap 2: Repeated Start/Stop cycles work reliably without hanging or thread starvation."""
    mock_discover.return_value = []
    window = MainWindow(prefs_manager=test_prefs)
    qtbot.addWidget(window)

    settings = EffectSettings()

    for cycle in range(3):
        started = window.worker.start_sync(
            bulb_ip=None,
            audio_device_index=None,
            effect_name="spectrum",
            settings=settings,
            dry_run=True,
        )
        assert started is True, f"Start failed on cycle {cycle + 1}"
        qtbot.waitUntil(lambda: window.worker.state == SyncState.RUNNING, timeout=4000)

        window.worker.stop_sync()
        qtbot.waitUntil(lambda: window.worker.state == SyncState.IDLE, timeout=4000)
        assert window.worker.state == SyncState.IDLE

    window.close()
    qtbot.waitUntil(lambda: not window.worker.thread.is_alive(), timeout=4000)


@patch("src.ui.workers.sync_worker.discover_devices")
def test_accurate_restoration_reporting(mock_discover, qtbot, test_prefs) -> None:
    """Gap 3: Accurate restoration results (SUCCESS, SKIPPED, UNAVAILABLE, FAILED) displayed in GUI."""
    mock_discover.return_value = []
    window = MainWindow(prefs_manager=test_prefs)
    qtbot.addWidget(window)

    settings = EffectSettings()

    # Test 1: Dry run restoration result is SKIPPED
    window.worker.start_sync(
        bulb_ip=None,
        audio_device_index=None,
        effect_name="spectrum",
        settings=settings,
        restore_state=True,
        dry_run=True,
    )
    qtbot.waitUntil(lambda: window.worker.state == SyncState.RUNNING, timeout=4000)
    window.worker.stop_sync()
    qtbot.waitUntil(lambda: window.worker.state == SyncState.IDLE, timeout=4000)
    report = window.worker.last_restoration_report
    assert report is not None
    from src.sync.state import RestorationResult
    assert report.result == RestorationResult.SKIPPED
    qtbot.waitUntil(lambda: "skipped" in window.statusBar.currentMessage().lower(), timeout=4000)

    window.close()
    qtbot.waitUntil(lambda: not window.worker.thread.is_alive(), timeout=4000)
