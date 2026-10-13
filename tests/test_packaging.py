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


def test_executable_runtime_execution() -> None:
    """Smoke test executing the frozen Windows executable in a subprocess."""
    import subprocess

    project_root = Path(__file__).parent.parent
    exe_file = project_root / "dist" / "WiZMusicSync" / "WiZMusicSync.exe"
    assert exe_file.exists(), f"Executable not found: {exe_file}"

    # Verify --version flag prints application version and exits cleanly (code 0)
    result = subprocess.run(
        [str(exe_file), "--version"],
        capture_output=True,
        text=True,
        timeout=15.0,
    )
    assert result.returncode == 0, f"Executable failed with code {result.returncode}: {result.stderr}"
    assert "WiZ Music Sync" in result.stdout

    # Verify --smoke-test flag executes entrypoint and exits with 0
    res_smoke = subprocess.run(
        [str(exe_file), "--smoke-test"],
        capture_output=True,
        text=True,
        timeout=15.0,
    )
    assert res_smoke.returncode == 0, f"Smoke test failed: {res_smoke.stderr}"
    assert "SMOKE TEST OK" in res_smoke.stdout
