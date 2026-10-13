# WiZ Music Sync — Real-Time Windows Audio & Smart Lighting

**WiZ Music Sync** is a high-performance Windows application designed to synchronize Philips Lighting WiZ smart bulbs with system audio playback (Spotify, YouTube, media players, games).

- **Phase 1 (Completed):** Local WiZ discovery, UDP network protocol, capability profiling, and hardware control.
- **Phase 2 (Completed):** Real-time Windows WASAPI loopback system audio capture, FFT spectrum analysis, frequency band separation, loudness normalization, and musical onset/transient detection.

---

## 1. Supported Hardware & Audio Devices

### Smart Bulb Hardware
- **Target Device:** Philips Lighting WiZ Wi-Fi Enabled Smart Bulb (Multicolour), E27
- **Model Identified:** `ESP25_SHRGB_01` (Firmware: `1.38.0`)
- **Capabilities Supported:**
  - Full RGB color control (`0–255` per channel)
  - Tunable White / Color Temperature (`2200K – 6500K`)
  - Dimming / Brightness (`0–255` scale)
  - Power switching (ON / OFF)

### Audio Output Devices (WASAPI Loopback)
- **Supported Outputs:** Internal Speakers, 3.5mm Headphones, USB DACs, and compatible Bluetooth audio devices (e.g. Stone 1508).
- **Audio Capture Mechanism:** Windows Audio Session API (WASAPI) process-independent system loopback via `PyAudioWPatch`.
- **Microphone Isolation:** Only system playback audio is captured; the microphone is completely excluded.

---

## 2. Prerequisites & Python Version

- **Operating System:** Windows 10 / Windows 11 (PowerShell recommended)
- **Python Version:** Python 3.11 or higher
- **Network Requirements:** Computer and bulb on the same 2.4 GHz local Wi-Fi network (UDP port `38899` allowed).

---

## 3. Installation & Setup

Open PowerShell in the project directory:

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

### Dependencies
- [`pywizlight>=0.6.6`](https://pypi.org/project/pywizlight/): Asynchronous UDP control library for WiZ LAN protocol.
- [`pyaudiowpatch>=0.2.12.9`](https://pypi.org/project/pyaudiowpatch/): Windows WASAPI loopback audio capture library.
- [`numpy>=1.26.0`](https://pypi.org/project/numpy/): Vectorized DSP, FFT, and matrix math.
- [`pytest>=8.0.0`](https://pypi.org/project/pytest/): Automated testing framework.
- [`pytest-asyncio>=0.23.0`](https://pypi.org/project/pytest-asyncio/): Asynchronous coroutine test runner.

---

## 4. Phase 2: Real-Time Audio Diagnostics

Launch the live audio diagnostic utility:

```powershell
python -m src.audio_diagnostics
```

### Command-Line Flags

```powershell
# List available audio loopback devices and exit
python -m src.audio_diagnostics --list-devices

# Capture from a specific device index
python -m src.audio_diagnostics --device 17

# Custom buffer size (e.g. 512, 1024, 2048)
python -m src.audio_diagnostics --buffer-size 1024

# Verbose debug logging
python -m src.audio_diagnostics -v
```

### Real-Time Diagnostic Output
```
Device:       Headphones (Stone 1508)
Loudness:     [################--------] 0.65
RMS:          [############------------] 0.51
Bass (20-250) [####################----] 0.82
Mid (250-4k)  [#########---------------] 0.38
Treble (4-16k)[####--------------------] 0.18
Onset:        >>> [BEAT] <<< (Strength: 0.74)
Telemetry:    48000Hz | FPS: 46.9 | Latency: 21.6ms | DSP: 0.2ms | Dropped: 0
```

---

## 5. Phase 1: WiZ Bulb Discovery & Hardware Test

### Automatic Bulb Discovery
```powershell
python -m src.main --discover-only
```

### Interactive Hardware Test Menu
```powershell
python -m src.main
```
*(Or specify manual IP fallback: `python -m src.main --ip <bulb-ip>`)*

### Non-Interactive Automated Hardware Verification
```powershell
# Automatically discovers bulb and runs 12-step verification sequence
python -m src.verify_hardware

# Or with explicit target IP:
python -m src.verify_hardware 192.168.1.4
```

---

## 6. Running Automated Tests

Run the complete test suite (both Phase 1 bulb control and Phase 2 audio DSP):

```powershell
.\.venv\Scripts\pytest -v
```

### Test Coverage (103 Tests Total)
- **`tests/test_audio_analyzer.py` (11 tests):**
  - Pure silence and low-amplitude noise floor detection
  - Pure 80 Hz sine wave (verifies >99% Bass band isolation)
  - Pure 1000 Hz sine wave (verifies >99% Mid band isolation)
  - Pure 8000 Hz sine wave (verifies >99% Treble band isolation)
  - Multi-frequency combinations and stereo interleaved channels
  - Sample rate adaptation (44.1 kHz, 48 kHz, 96 kHz)
  - Buffer length adaptability (512, 1024, 2048 frames)
  - Null/empty buffer handling and state resets
- **`tests/test_beat_detector.py` (6 tests):**
  - Sudden transient onset detection
  - Sustained tone rejection (avoids false repetitive triggers)
  - Refractory cooldown window enforcement (~85ms minimum between beats)
  - Silence rejection and state reset
- **`tests/test_audio_capture.py` (3 tests):**
  - Bounded queue frame dropping under backpressure (drops oldest frame)
  - Stream lifecycle start/stop and clean thread joining
  - Stream initialization failure handling and resource cleanup
- **`tests/test_audio_devices.py` (6 tests):**
  - Device enumeration, clean name formatting, and default selection
  - Missing PyAudio / missing WASAPI graceful fallbacks
- **`tests/test_validation.py` (42 tests):**
  - IPv4 address parsing, validation, and boundary conditions
  - RGB bounds (`0–255`), Brightness bounds (`0–255`), Kelvin bounds (`2200K–6500K`)
- **`tests/test_controller.py` (11 tests):**
  - Mocked WiZ commands (turn_on, turn_off, set_rgb, set_colortemp, set_brightness)
  - Error mapping (connection drops, timeouts, unsupported features)
- **`tests/test_discovery.py` (7 tests):**
  - UDP probe packet generation and parsing
  - Filter verification for loopback / self-echoed broadcast packets

---

## 7. Architecture Overview

```
src/
    audio/
        __init__.py
        devices.py          # WASAPI loopback device enumeration & defaults
        capture.py          # Bounded-queue audio streaming & worker thread
        analyzer.py         # Hann window, FFT spectrum, frequency bands, RMS
        beat_detector.py    # Half-wave spectral flux onset detection
        normalization.py    # Asymmetric attack/release envelope & noise floor
    audio_diagnostics.py    # Real-time CLI diagnostic monitor
    wiz/
        __init__.py
        controller.py       # WiZ LAN bulb controller abstraction
        discovery.py        # Asynchronous UDP broadcast bulb discovery
    utils/
        __init__.py
        logging_config.py   # Application logging
        network.py          # Subnet broadcast resolution & IP validation
    main.py                 # Phase 1 interactive CLI
    verify_hardware.py      # Non-interactive automated hardware verifier
```

---

## 8. Known Limitations (Phase 2)

- **Phase 3 Integration:** Lighting reactivity (mapping audio metrics to WiZ bulb colors/brightness) is intentionally decoupled and deferred to Phase 3.
- **Windows Only:** Audio capture relies on Windows WASAPI loopback.
