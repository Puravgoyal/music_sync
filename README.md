# WiZ Music Sync — Real-Time Windows Audio & Smart Lighting

**WiZ Music Sync** is a modern Windows desktop application designed to synchronize Philips Lighting WiZ smart bulbs with system audio playback (Spotify, YouTube, media players, games).

- **Phase 1:** Local WiZ UDP protocol control, capability discovery, and hardware verification.
- **Phase 2:** Low-latency Windows WASAPI loopback system audio capture, FFT spectrum analysis, frequency band energy parsing, and musical onset transient detection.
- **Phase 3:** Real-time music-to-light synchronization, 5 reactive lighting modes, rate-limited coalescing WiZ command scheduler, deadband filtering, and pre-sync state restoration.
- **Phase 4:** Polished PySide6 Windows desktop application, transactional startup rollback, accurate active lighting mode restoration, multithreaded async event loop bridge, local preferences persistence, and PyInstaller Windows executable packaging.

---

## 1. Supported Hardware & Audio Devices

### Smart Bulb Hardware
- **Target Device:** Philips Lighting WiZ Wi-Fi Enabled Smart Bulb (Multicolour), E27
- **Model Identified:** `ESP25_SHRGB_01` (Firmware: `1.38.0`)
- **Capabilities Supported:**
  - Full RGB color control (`0–255` per channel)
  - Tunable White / Color Temperature (`2200K – 6500K`)
  - Warm/Cold white discrete LED channel control
  - Dimming / Brightness (`0–255` scale)
  - Single datagram combined RGB + brightness control (`set_light_state`)
  - Power switching (ON / OFF)
  - True pre-sync lighting mode restoration (RGB, Tunable White, White, Dimming, Scene, or Off)

### Audio Output Devices (WASAPI Loopback)
- **Supported Outputs:** Internal Speakers, 3.5mm Headphones, USB DACs, and compatible Bluetooth audio devices (e.g. Stone 1508).
- **Audio Capture Mechanism:** Windows Audio Session API (WASAPI) process-independent system loopback via `PyAudioWPatch`.
- **Microphone Isolation:** Only system playback audio is captured; laptop microphones are completely excluded.

---

## 2. Prerequisites & Installation

- **Operating System:** Windows 10 / Windows 11 (PowerShell recommended)
- **Python Version:** Python 3.11 or higher
- **Local Network:** Computer and bulb on the same 2.4 GHz local Wi-Fi network (UDP port `38899` allowed).

```powershell
# 1. Clone repository
git clone https://github.com/Puravgoyal/music_sync.git
cd music_sync

# 2. Create Python virtual environment
python -m venv .venv

# 3. Activate virtual environment
.\.venv\Scripts\Activate.ps1

# 4. Install dependencies
pip install -r requirements.txt
```

---

## 3. Running the Desktop Application

### Launch GUI from Source
```powershell
python -m src.desktop_app
```

### Desktop UI Layout
The modern dark-themed desktop application provides:
1. **WiZ Smart Bulb Connection:** One-click network scan, dropdown bulb selector with IP and MAC, manual IP input, connection testing, and live status.
2. **Audio Capture Source:** Dropdown of Windows WASAPI loopback devices clearly indicating the system default, with auto-refresh on device plug/unplug.
3. **Synchronization Control & Preview:** Large Start/Stop button, live status badge, target computed color swatch, acknowledged bulb color swatch, updates/sec rate, command count, and latency telemetry.
4. **Live Audio Spectrum & Rhythm:** Real-time animated level meters for Bass (20–250 Hz), Mid (250–4000 Hz), Treble (4–16 kHz), Master Loudness, and a pulsing rhythm onset badge.
5. **Music Reactive Effect & Tuning:** Dropdown for all 5 effect modes with dynamic descriptions, plus sliders for audio sensitivity, maximum brightness, minimum brightness, color smoothing, attack speed, release speed, beat intensity, and bulb update rate.

---

## 4. Packaging the Windows Executable

The application can be packaged into a standalone Windows desktop executable using the automated build script:

```powershell
# Build standalone onedir Windows executable
python build_exe.py
```

The compiled application will be generated in:
```
dist/WiZMusicSync/WiZMusicSync.exe
```

The executable bundles Python 3.11, PySide6 Qt binaries, PyAudioWPatch WASAPI drivers, NumPy, dark theme QSS assets, and requires no external Python installation to run.

---

## 5. Music-Reactive Lighting Effects

1. **Mode 1 — Spectrum RGB (`spectrum`):**
   - Tri-band energy mapped to Bass $\rightarrow$ Red, Mid $\rightarrow$ Green, Treble $\rightarrow$ Blue.
   - Proportional balance normalization ensures high frequencies register cleanly without one band monopolizing the color output.
2. **Mode 2 — Beat Pulse (`beat`):**
   - Steady ambient base color with responsive brightness kicks on detected rhythmic onsets.
   - Smooth exponential decay envelope prevents uncontrolled strobing.
3. **Mode 3 — Bass Reactive (`bass`):**
   - Kick drum and bassline focus.
   - Modulates brightness and drives dynamic crimson-to-orange-to-magenta hue shifts.
4. **Mode 4 — Smooth Spectrum (`smooth`):**
   - Maps spectral balance centroid to continuous circular HSV hue.
   - Tracks loudness for brightness with seamless color wheel interpolation and zero color jumping.
5. **Mode 5 — Ambient Flow (`ambient`):**
   - Slow atmospheric continuous color drift subtly guided by the music spectrum.
   - Ideal for continuous background mood lighting.

---

## 6. Architecture & Reliability

```
┌────────────────────────────────────────────────────────┐
│                   PySide6 Desktop GUI                   │
│  DevicePanel │ AudioPanel │ EffectsPanel │ SpectrumView │
└──────────────────────────┬─────────────────────────────┘
                           │ (Qt Signals / Thread-Safe Slots)
┌──────────────────────────▼─────────────────────────────┐
│                       SyncWorker                        │
│   (Hosts Background Asyncio Event Loop in QThread)     │
└──────────────────────────┬─────────────────────────────┘
                           │
       ┌───────────────────┴───────────────────┐
       ▼                                       ▼
AudioCapture Thread                    MusicSyncEngine
  (WASAPI Loopback @ ~46.8 FPS)       ├── Transactional Rollback
       │                               ├── Thread-Safe Locks
       ▼                               ├── True Mode Restoration
 AudioAnalyzer                         └── BulbCommandScheduler
 (Hann FFT & Spectral Flux)                  ├── State Coalescing
       │                                     ├── Deadband Filter (Δ4)
       ▼                                     ├── Rate Limiter (2-5 Hz)
  Lighting Effects Engine                    └── Non-Overlapping Lock
  (Spectrum, Beat, Bass, Smooth, Ambient)      │
                                               ▼
                                         WiZ Smart Bulb
                                         (UDP 192.168.1.4)
```

### Key Reliability Safeguards
- **Transactional Startup Rollback:** Failure at any initialization stage (e.g. unreachable bulb, device in-use) safely cancels tasks, stops the scheduler, releases streams, restores pre-sync bulb state, and allows clean immediate retries without restarting the app.
- **Accurate Active Lighting Mode Restoration:** Reads `pilotResult` to detect whether the bulb was in RGB, Tunable White (Kelvin), White LED channel, Scene, Dimming, or Off mode, and restores the exact state without inventing arbitrary defaults.
- **Multithreaded Isolation:** The GUI main thread, background asyncio scheduler, and PyAudio capture thread are strictly decoupled with mutex locks and Qt signals. Network delays or UDP retries never freeze the interface.
- **Local Settings Persistence:** User preferences (last bulb IP, audio device name, preferred effect, sliders, window state) are validated and stored atomically in `%APPDATA%\WiZMusicSync\preferences.json`.

---

## 7. Command-Line Interface (CLI)

The non-GUI CLI remains fully operational:

```powershell
# Run with automatic bulb discovery and Spectrum RGB
python -m src.music_sync

# Run against specific bulb IP with Beat Pulse
python -m src.music_sync --ip 192.168.1.4 --effect beat

# Run with custom update rate and sensitivity
python -m src.music_sync --ip 192.168.1.4 --effect bass --rate 5.0 --sensitivity 1.2

# Run in simulated DRY-RUN mode (zero network packets)
python -m src.music_sync --dry-run --effect smooth

# List available effects and audio devices
python -m src.music_sync --list-effects
python -m src.music_sync --list-devices
```

---

## 8. Automated Testing

Run the full automated test suite:

```powershell
.\.venv\Scripts\pytest -v
```

### Complete Test Coverage (192 Passing Tests)
- **`tests/test_ui.py` (7 tests):** DevicePanel selection, AudioPanel enumeration, EffectsPanel sliders, SpectrumView bars/beat flash, StatusPanel previews, MainWindow lifecycle, and rapid Start/Stop cycles.
- **`tests/test_preferences.py` (7 tests):** AppPreferences defaults, boundary clamping, atomic save/load roundtrips, corrupted JSON recovery, and forward schema compatibility.
- **`tests/test_reliability.py` (9 tests):** Transactional startup rollback on controller error, scheduler error, audio device failure, clean retry, accurate restoration across Off/RGB/Colortemp/Scene/White modes, and concurrent thread-safety stress tests.
- **`tests/test_packaging.py` (2 tests):** Bundled executable existence, binary size check, and bundled dark theme stylesheet presence.
- **`tests/test_effects.py` (32 tests):** All 5 reactive lighting modes, boundary constraints, silence decay, and registry aliases.
- **`tests/test_scheduler.py` (14 tests):** Rate limiting (1–10 Hz), coalescing, deadband filter suppression, adaptive backoff, and lifecycle.
- **`tests/test_sync_engine.py` (6 tests):** Engine lifecycle, dynamic effect switching, and pre-sync state capture.
- **`tests/test_audio_analyzer.py` (27 tests):** Parseval energy sum, synthetic treble tests (6 kHz, 8 kHz, 12 kHz), and band isolation.
- **`tests/test_beat_detector.py` (6 tests):** Onset detection, refractory cooldown windows, and sustained tone rejection.
- **`tests/test_audio_capture.py` (3 tests):** Bounded queue frame dropping and worker lifecycle.
- **`tests/test_audio_devices.py` (6 tests):** WASAPI loopback enumeration and default selection.
- **`tests/test_controller.py` (11 tests):** WiZ controller commands, timeouts, and error mappings.
- **`tests/test_discovery.py` (7 tests):** Broadcast UDP probe datagrams and echo rejection.
- **`tests/test_validation.py` (55 tests):** IP, RGB, brightness, and Kelvin validation.
