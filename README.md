# WiZ Music Sync — Real-Time Windows Audio & Smart Lighting

**WiZ Music Sync** is a high-performance Windows application designed to synchronize Philips Lighting WiZ smart bulbs with system audio playback (Spotify, YouTube, media players, games).

- **Phase 1 (Completed):** Local WiZ discovery, UDP network protocol, capability profiling, and hardware control.
- **Phase 2 (Completed):** Real-time Windows WASAPI loopback system audio capture, FFT spectrum analysis, frequency band separation, loudness normalization, and musical onset/transient detection.
- **Phase 3 (Completed):** End-to-end real-time music-to-light synchronization, 5 music-reactive lighting modes, rate-limited coalescing WiZ command scheduler, deadband filtering, pre-sync state preservation and restoration.

---

## 1. Supported Hardware & Audio Devices

### Smart Bulb Hardware
- **Target Device:** Philips Lighting WiZ Wi-Fi Enabled Smart Bulb (Multicolour), E27
- **Model Identified:** `ESP25_SHRGB_01` (Firmware: `1.38.0`)
- **Capabilities Supported:**
  - Full RGB color control (`0–255` per channel)
  - Tunable White / Color Temperature (`2200K – 6500K`)
  - Dimming / Brightness (`0–255` scale)
  - Combined RGB + brightness control in a single UDP datagram (`set_light_state`)
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

---

## 4. Phase 3: Real-Time Music Synchronization CLI

Launch the music synchronization engine:

```powershell
# Run with automatic bulb discovery and default Spectrum RGB effect
python -m src.music_sync

# Run against a specific bulb IP with Beat Pulse mode
python -m src.music_sync --ip 192.168.1.4 --effect beat

# Run with custom update rate (e.g. 5.0 Hz) and sensitivity
python -m src.music_sync --ip 192.168.1.4 --effect bass --rate 5.0 --sensitivity 1.2

# Run in simulated DRY-RUN mode (computes states without transmitting UDP packets)
python -m src.music_sync --dry-run --effect smooth

# List all available lighting modes
python -m src.music_sync --list-effects

# List available Windows loopback audio output devices
python -m src.music_sync --list-devices
```

### CLI Command-Line Options
| Flag | Description | Default |
| --- | --- | --- |
| `--ip <IP>` | Target WiZ bulb IP address (scans Wi-Fi if omitted) | Auto-discovered |
| `--device <INDEX>` | Audio output device index | System Default |
| `--effect <NAME>` | Lighting effect: `spectrum`, `beat`, `bass`, `smooth`, `ambient` | `spectrum` |
| `--sensitivity <FLOAT>` | Audio responsiveness sensitivity multiplier `[0.1, 3.0]` | `1.0` |
| `--min-brightness <INT>` | Resting / silence brightness floor `[0, 255]` | `25` |
| `--max-brightness <INT>` | Peak brightness ceiling `[0, 255]` | `255` |
| `--rate <FLOAT>` | WiZ bulb command dispatch rate in Hz `[1.0, 10.0]` | `4.0` |
| `--duration <SECONDS>` | Automatic stop duration in seconds | Indefinite (Ctrl+C) |
| `--dry-run` | Simulate lighting states without network transmission | `False` |
| `--no-restore` | Do not restore bulb state upon exit | Restore on exit |
| `--list-effects` | Show registered lighting effects and descriptions | - |
| `--list-devices` | Show enumerated Windows loopback audio devices | - |
| `-v`, `--verbose` | Enable debug logging | Warning |

---

## 5. Music-Reactive Lighting Effects

1. **Mode 1 — Spectrum RGB (`spectrum`):**
   - Direct tri-band energy mapping: Bass $\rightarrow$ Red, Mid $\rightarrow$ Green, Treble $\rightarrow$ Blue.
   - Proportional balance normalization ensures high frequencies register cleanly without one band permanently dominating.
2. **Mode 2 — Beat Pulse (`beat`):**
   - Steady ambient base color with responsive brightness kicks on detected rhythmic onsets.
   - Smooth decay envelope prevents uncontrolled strobing.
3. **Mode 3 — Bass Reactive (`bass`):**
   - Low-frequency kick drum and bassline focus.
   - Modulates brightness and drives fiery crimson-to-orange-to-magenta hue shifts.
4. **Mode 4 — Smooth Spectrum (`smooth`):**
   - Maps spectral balance centroid to continuous circular HSV hue.
   - Tracks loudness for brightness with smooth transitions and zero color jumps.
5. **Mode 5 — Ambient Flow (`ambient`):**
   - Atmospheric continuous color drift subtly guided by the music spectrum.
   - Ideal for continuous background mood lighting.

---

## 6. Architecture & Rate Limiting

```
Windows Audio Playback
         │
         ▼ (WASAPI Loopback)
  AudioCapture (~46.8 FPS)
         │
         ▼ (FFT & Flux Analysis)
   AudioAnalyzer
         │
         ▼ (AudioMetrics)
  Lighting Effects Engine
  (Spectrum, Beat, Bass, Smooth, Ambient)
         │
         ▼ (LightingState: RGB + Brightness)
 BulbCommandScheduler
  ├── State Coalescing (keeps only latest frame)
  ├── Deadband Filter (suppresses negligible jitter)
  ├── Rate Limiter (2-5 Hz, configurable 1-10 Hz)
  └── Non-Overlapping Lock & Adaptive Error Backoff
         │
         ▼ (set_light_state UDP datagram)
   Physical WiZ Bulb
```

---

## 7. Automated Testing

Run the full automated test suite:

```powershell
.\.venv\Scripts\pytest -v
```

### Complete Test Coverage (167 Tests Passing)
- **`tests/test_effects.py` (32 tests):**
  - Settings range validation and error checking
  - Registry alias lookup and error cases
  - Tri-band spectrum color balance (Bass/Mid/Treble dominance)
  - Beat pulse onset triggering and smooth decay
  - Bass reactive hue modulation and brightness clamping
  - Smooth spectrum circular hue interpolation
  - Ambient flow drift and boundary constraints
- **`tests/test_scheduler.py` (14 tests):**
  - Rate-limiting intervals (1.0 to 10.0 Hz)
  - State coalescing (retains freshest state)
  - Deadband suppression (skips imperceptible updates)
  - Dry-run execution isolation
  - Live UDP command dispatch with controller mocks
  - Timeout error handling and adaptive backoff
  - Worker lifecycle start and stop
- **`tests/test_sync_engine.py` (6 tests):**
  - Engine initialization and default configurations
  - Dynamic on-the-fly effect and settings switching
  - Audio callback routing to scheduler
  - Pre-sync state preservation and clean restoration
- **`tests/test_audio_analyzer.py` (23 tests):**
  - Silence & noise floor rejection
  - Synthetic treble tests (6 kHz, 8 kHz, 12 kHz) with Parseval energy balance
  - Band isolation (80 Hz, 1 kHz, 8 kHz)
- **`tests/test_beat_detector.py` (6 tests):**
  - Onset transient detection and cooldown enforcement
- **`tests/test_audio_capture.py` (3 tests):**
  - Bounded queue frame dropping and capture lifecycle
- **`tests/test_audio_devices.py` (6 tests):**
  - Windows loopback device enumeration
- **`tests/test_controller.py` (11 tests):**
  - WiZ controller commands, timeouts, and connection errors
- **`tests/test_discovery.py` (7 tests):**
  - UDP broadcast discovery protocol
- **`tests/test_validation.py` (59 tests):**
  - IP, RGB, brightness, and Kelvin validation
