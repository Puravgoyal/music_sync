# WiZ Music Sync — Real-Time Windows Audio & Smart Lighting

**WiZ Music Sync** is a modern Windows desktop application designed to synchronize Philips Lighting WiZ smart bulbs with system audio playback (Spotify, YouTube, media players, games).

- **Phase 1:** Local WiZ UDP protocol control, capability discovery, and hardware verification.
- **Phase 2:** Low-latency Windows WASAPI loopback system audio capture, FFT spectrum analysis, frequency band energy parsing, and musical onset transient detection.
- **Phase 3:** Real-time music-to-light synchronization, 5 reactive lighting modes, rate-limited coalescing WiZ command scheduler, deadband filtering, and pre-sync state restoration.
- **Phase 4:** Polished PySide6 Windows desktop application, transactional startup rollback, accurate active lighting mode restoration, multithreaded async event loop bridge, local preferences persistence, and PyInstaller Windows executable packaging.
- **Phase 4.3:** Enhanced beat detection & vocal suppression (Full Music, Rhythm Focus, Kick Focus), dual-resolution 2048-sample low-frequency FFT, latency-aware beat preservation, adaptive bulb update rate controller, and physical hardware rate benchmarking.

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
3. **Synchronization Control & Preview:** Large Start/Stop button, live status badge, target computed color swatch, acknowledged bulb color swatch, updates/sec rate, command count, adaptive rate indicators, and p95 round-trip latency telemetry.
4. **Live Audio Spectrum & Rhythm:** Real-time animated level meters for Bass (20–250 Hz), Mid (250–4000 Hz), Treble (4–16 kHz), Master Loudness, and a live transient hit badge (`⚡ KICK HIT!`, `⚡ PERCUSSION HIT!`, or `⚡ BEAT DETECTED!`).
5. **Audio Focus Selector (Phase 4.3):** Dropdown allowing instant switching between **Full Music**, **Rhythm Focus**, and **Kick Focus** modes to suppress vocal interference and isolate true percussive attacks.
6. **Adaptive Update Rate Control:** Automatic link-quality controller stepping up to 5.0–8.0 Hz on low-latency connections and backing down dynamically to avoid ESP25 UDP packet congestion.
7. **Music Reactive Effect & Tuning:** Dropdown for all 5 effect modes with dynamic descriptions, plus sliders for audio sensitivity, maximum brightness, minimum brightness, color smoothing, attack speed, release speed, beat intensity, and bulb update rate.

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

## 6. Audio Focus Modes & Real-Time DSP (Phase 4.3)

To prevent sustained vocal melodies, podcasts, and speech from causing unnatural light pumping, the audio analysis engine introduces three selectable focus modes:

### Mode A — Full Music (`full`)
- 100% backward-compatible broad-spectrum analysis.
- Computes positive spectral flux across the full 20 Hz – 16 kHz band.
- Normalizes bass, mid, and treble energies evenly.
- Ideal for instrumental, orchestral, and ambient tracks.

### Mode B — Rhythm Focus (`rhythm`)
- **Vocal Suppression via Harmonic Floor Subtraction:** Tracks slowly-varying vocal and melodic energy across the 200–1400 Hz voice fundamental region with an exponential running average ($\alpha \approx 0.1$). Only transient deviations exceeding this baseline register as rhythmic attacks.
- **Percussion-Weighted Spectral Flux:**
  - Kick drum band (40–180 Hz): **1.8x** weight
  - Snare / Clap / Rimshot band (1.5–4.0 kHz): **1.6x** weight
  - Hi-hat / Shaker band (6.0–14.0 kHz): **1.3x** weight
  - Vocal speech band (200–1400 Hz): attenuated to **0.22x** weight
- Produces sharp, clean hits on drums while resting smoothly during vocal passages.

### Mode C — Kick Focus (`kick`)
- **Dual-Resolution FFT:** Runs a dedicated 2048-sample ring buffer computed in real time alongside the primary 1024-sample FFT. This yields a fine 23.44 Hz bin resolution (7 discrete bins in the 40–180 Hz kick range) with zero additional phase latency.
- **Attack Slope Differentiation:** Computes instantaneous energy derivative $dE/dt = \max(0, E_{kick} - \text{baseline})$.
- **Sustained Bassline Rejection:** Sustained 808 sub-bass tones and synth pedals are rejected after their initial transient hit, isolating true kick drum hits.

---

## 7. High-Speed Bulb Optimization & Rate Benchmarking

The Philips WiZ E27 multicolour bulb uses an Espressif ESP25 microcontroller (`ESP25_SHRGB_01`, firmware `1.38.0`) communicating over local UDP port `38899`.

### Empirical Rate Benchmark Findings
Benchmarked directly against physical hardware (`192.168.1.4`):
- **3.5 Hz – 4.0 Hz:** Rock-solid stability. Round-trip acknowledgement latencies average ~93.9 ms with 100% command delivery.
- **5.0 Hz – 6.0 Hz:** High performance on clean 2.4 GHz Wi-Fi links. Average latencies ~103–133 ms.
- **8.0 Hz:** Peak attainable throughput (5.91 Hz actual commands executed per second).
- **10.0 Hz:** Saturated ESP25 receive buffer. Commands queue up inside the microcontroller, causing p95 latency to spike to 443 ms and dropping effective command execution to ~4.68 Hz.

### Adaptive Update Rate Controller
- **Link Quality Monitoring:** Computes rolling p95 round-trip latency over the last 20 acknowledged UDP commands.
- **Auto Step-Up:** If latency is low (p95 < 55 ms) and 10+ consecutive packets succeed, the scheduler steps up the update rate by +0.5 Hz.
- **Immediate Step-Down:** If round-trip latency exceeds 110 ms, the rate steps down by -0.5 Hz.
- **Failure Backoff:** If a UDP packet times out or is dropped, the scheduler immediately steps down by -1.0 Hz and backs off.

### Latency-Aware Beat Preservation
- In standard rate limiters, sudden drum hits occurring between rate-limited ticks are either dropped or queued, causing delayed out-of-time flashes.
- `BulbCommandScheduler` tracks incoming beat transients via `BeatEvent`. If a beat event occurs while a tick is pending, the beat state is preserved and dispatched on the very next available tick if fresh ($\le 180\text{ ms}$). Stale beats older than 180 ms are discarded to prevent out-of-time lighting flashes.

---

## 8. Architecture & Reliability

```
┌────────────────────────────────────────────────────────────────────────┐
│                          PySide6 Desktop GUI                           │
│  DevicePanel │ AudioPanel │ EffectsPanel (Focus Combo) │ SpectrumView  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ (Qt Signals / Thread-Safe Slots)
┌───────────────────────────────────▼────────────────────────────────────┐
│                               SyncWorker                               │
│            (Hosts Background Asyncio Event Loop in QThread)            │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
        ┌───────────────────────────┴───────────────────────────┐
        ▼                                                       ▼
 AudioCapture Thread                                     MusicSyncEngine
   (WASAPI Loopback @ ~46.8 FPS)                        ├── Transactional Rollback
        │                                                ├── Thread-Safe Locks
        ▼                                                ├── True Mode Restoration
  AudioAnalyzer                                          └── BulbCommandScheduler
  ├── Primary FFT (1024-pt Hann)                              ├── State Coalescing
  ├── Dual-Res Low-Freq FFT (2048-pt Ring Buffer)             ├── Latency-Aware Beat Preservation
  └── BeatDetector (Full, Rhythm, Kick Modes)                 ├── Adaptive Rate Controller
        │                                                     ├── Deadband Filter (Δ4)
        ▼                                                     ├── Rate Limiter (2-8 Hz)
   Lighting Effects Engine                                    └── Non-Overlapping Lock
   (Spectrum, Beat, Bass, Smooth, Ambient)                      │
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

## 9. Command-Line Interface (CLI)

The non-GUI CLI remains fully operational and supports all focus modes and adaptive rate options:

```powershell
# Run with automatic bulb discovery and Rhythm Focus
python -m src.music_sync --focus rhythm

# Run against specific bulb IP with Beat Pulse and Kick Focus
python -m src.music_sync --ip 192.168.1.4 --effect beat --focus kick

# Run with adaptive update rate enabled (steps up on low latency, backs off on congestion)
python -m src.music_sync --ip 192.168.1.4 --effect bass --rate 5.0 --adaptive-rate

# Run in simulated DRY-RUN mode (zero network packets)
python -m src.music_sync --dry-run --effect smooth --focus rhythm

# List available effects and audio devices
python -m src.music_sync --list-effects
python -m src.music_sync --list-devices
```

---

## 10. Automated Testing & Verification

Run the full automated test suite:

```powershell
.\.venv\Scripts\pytest -v
```

### Complete Test Coverage (216 Passing Tests)
- **`tests/test_audio_focus.py` (9 tests):** Multi-mode audio focus initialization, harmonic vocal floor subtraction, kick transient slope differentiation, beat preservation in scheduler, and adaptive update rate stepping.
- **`tests/test_verification_defects.py` (4 tests):** Falsification tests ensuring vocal tones never trigger rhythm onset hits, sustained basslines do not trigger kick hits, and scheduler never drops transient beats on tick boundaries.
- **`tests/test_lifecycle_and_thread_affinity.py` (10 tests):** Qt thread affinity verification, safe timer activation on GUI thread, async event loop shutdown, and race-free window close.
- **`tests/test_ui.py` (7 tests):** DevicePanel selection, AudioPanel enumeration, EffectsPanel sliders, SpectrumView bars/beat flash, StatusPanel previews, MainWindow lifecycle, and rapid Start/Stop cycles.
- **`tests/test_preferences.py` (7 tests):** AppPreferences defaults, boundary clamping, atomic save/load roundtrips, corrupted JSON recovery, and forward schema compatibility.
- **`tests/test_reliability.py` (9 tests):** Transactional startup rollback on controller error, scheduler error, audio device failure, clean retry, accurate restoration across Off/RGB/Colortemp/Scene/White modes, and concurrent thread-safety stress tests.
- **`tests/test_packaging.py` (3 tests):** Bundled executable existence, binary size check, bundled dark theme stylesheet presence, `--version` CLI, and subprocess packaged GUI smoke test with diagnostic report verification.
- **`tests/test_effects.py` (32 tests):** All 5 reactive lighting modes across Full Music, Rhythm, and Kick focus settings, boundary constraints, silence decay, and registry aliases.
- **`tests/test_scheduler.py` (14 tests):** Rate limiting (1–10 Hz), coalescing, deadband filter suppression, adaptive backoff, and lifecycle.
- **`tests/test_sync_engine.py` (6 tests):** Engine lifecycle, dynamic effect switching, and pre-sync state capture.
- **`tests/test_audio_analyzer.py` (27 tests):** Parseval energy sum, dual-resolution 2048-sample low-frequency FFT bins, synthetic treble tests (6 kHz, 8 kHz, 12 kHz), and band isolation.
- **`tests/test_beat_detector.py` (6 tests):** Onset detection, refractory cooldown windows, and sustained tone rejection.
- **`tests/test_audio_capture.py` (3 tests):** Bounded queue frame dropping and worker lifecycle.
- **`tests/test_audio_devices.py` (6 tests):** WASAPI loopback enumeration and default selection.
- **`tests/test_controller.py` (11 tests):** WiZ controller commands, timeouts, and error mappings.
- **`tests/test_discovery.py` (7 tests):** Broadcast UDP probe datagrams and echo rejection.
- **`tests/test_validation.py` (55 tests):** IP, RGB, brightness, and Kelvin validation.
