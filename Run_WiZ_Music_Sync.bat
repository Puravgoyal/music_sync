@echo off
title WiZ Music Sync Launcher
cd /d "%~dp0"
echo Starting WiZ Music Sync Desktop GUI...
start "" "dist\WiZMusicSync\WiZMusicSync.exe" --auto-start
