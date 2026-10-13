"""Automated build script for packaging WiZ Music Sync using PyInstaller."""

import os
import shutil
import subprocess
import sys
from pathlib import Path


def build_executable() -> int:
    project_root = Path(__file__).parent.resolve()
    entrypoint = project_root / "src" / "desktop_app.py"
    qss_file = project_root / "src" / "ui" / "themes" / "dark.qss"

    print("=" * 60)
    print(" Building WiZ Music Sync Windows Desktop Executable")
    print("=" * 60)

    dist_dir = project_root / "dist"
    build_dir = project_root / "build"

    # Clean previous builds
    if dist_dir.exists():
        shutil.rmtree(dist_dir, ignore_errors=True)
    if build_dir.exists():
        shutil.rmtree(build_dir, ignore_errors=True)

    # PyInstaller arguments
    # On Windows, data files are separated with semicolon ';'
    data_arg = f"{qss_file};src/ui/themes"

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--windowed",
        "--name",
        "WiZMusicSync",
        "--add-data",
        data_arg,
        "--hidden-import",
        "pyaudiowpatch",
        "--hidden-import",
        "pywizlight",
        "--hidden-import",
        "numpy",
        "--hidden-import",
        "PySide6.QtCore",
        "--hidden-import",
        "PySide6.QtGui",
        "--hidden-import",
        "PySide6.QtWidgets",
        str(entrypoint),
    ]

    print(f"Running command: {' '.join(cmd)}\n")
    result = subprocess.run(cmd, cwd=str(project_root))
    if result.returncode != 0:
        print("\n[!] PyInstaller build failed!")
        return result.returncode

    exe_path = dist_dir / "WiZMusicSync" / "WiZMusicSync.exe"
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / (1024 * 1024)
        print(f"\n[+] Executable build succeeded: {exe_path} ({size_mb:.2f} MB)")
        return 0
    else:
        print("\n[!] Output executable not found in dist directory!")
        return 1


if __name__ == "__main__":
    sys.exit(build_executable())
