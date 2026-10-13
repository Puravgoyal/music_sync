"""Packaging smoke tests verifying the built Windows executable."""

from pathlib import Path
import pytest


def test_dist_executable_exists() -> None:
    project_root = Path(__file__).parent.parent
    dist_dir = project_root / "dist" / "WiZMusicSync"
    exe_file = dist_dir / "WiZMusicSync.exe"

    assert dist_dir.exists(), f"Dist directory not found: {dist_dir}"
    assert exe_file.exists(), f"Executable not found: {exe_file}"
    assert exe_file.stat().st_size > 1024 * 1024, "Executable size is abnormally small (< 1 MB)"


def test_packaged_resources_and_binaries() -> None:
    project_root = Path(__file__).parent.parent
    dist_dir = project_root / "dist" / "WiZMusicSync"

    # Verify dark theme stylesheet was bundled
    qss_file = dist_dir / "_internal" / "src" / "ui" / "themes" / "dark.qss"
    assert qss_file.exists(), f"Bundled QSS stylesheet not found: {qss_file}"

    # Verify PySide6 core binaries are bundled
    internal_dir = dist_dir / "_internal"
    pyside6_dir = internal_dir / "PySide6"
    assert pyside6_dir.exists(), f"PySide6 directory not found in _internal: {pyside6_dir}"
