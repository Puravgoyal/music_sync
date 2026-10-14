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
### Mode C — Kick Focus (`kick`)
- **Dual-Resolution FFT:** Runs a dedicated 2048-sample ring buffer computed in real time alongside the primary 1024-sample FFT. This yields a fine 23.44 Hz bin resolution (7 discrete bins in the 40–180 Hz kick range).
- **Temporal Resolution vs. Frequency Resolution Trade-Off:**
  By the Heisenberg-Gabor uncertainty principle ($\Delta f \cdot \Delta t \ge \frac{1}{4\pi}$), isolating fundamental bass kick frequencies (40–180 Hz) without spectral leakage from vocal formants requires narrower frequency bins ($\Delta f = 23.44\text{ Hz}$ with $N=2048$ vs $\Delta f = 46.88\text{ Hz}$ with $N=1024$).
  Because the 2048-sample ring buffer slides forward with each 1024-sample hop ($\approx 21.3\text{ ms}$ at 48 kHz), the added acoustic group delay is only $\frac{N_{2048} - N_{1024}}{2 \cdot f_s} \approx 10.6\text{ ms}$. This ~10.6 ms delay is psychoacoustically imperceptible and well within the bulb's ~250 ms command interval.
- **Attack Slope Differentiation:** Computes instantaneous energy derivative $dE/dt = \max(0, E_{kick} - \text{baseline})$.
- **Sustained Bassline Rejection:** Sub-bass energy concentration checks and adaptive thresholding reject continuous 808 drones and vocal formants after their initial attack, isolating true kick drum hits.

---

## 7. High-Speed Bulb Optimization & Rate Benchmarking

The Philips WiZ E27 multicolour bulb uses an Espressif ESP25 microcontroller (`ESP25_SHRGB_01`, firmware `1.38.0`) communicating over local UDP port `38899`.

### Empirical Rate Benchmark Findings
Benchmarked directly against physical hardware (`192.168.1.4`) with adequately sampled 8-second runs and smooth transitions:
- **4.0 Hz (Default):** **100% Stable.** Achieved 3.90 commands/sec throughput with 100% command success rate. Latency: p50 = 120.9 ms, p95 = 202.5 ms. **0.0%** long-tail delays > 250 ms. **This is retained as the default safe operating rate.**
- **5.0 Hz:** Achieved 4.40 commands/sec throughput (100% success). Latency: p50 = 190.7 ms, p95 = 297.6 ms. **8.3%** packets suffered long-tail delays > 250 ms (max 772 ms) due to ESP25 internal buffer queuing. Classified as degraded/unstable.
- **6.0 Hz:** Achieved 4.87 commands/sec throughput (100% success). Latency: p50 = 169.9 ms, p95 = 227.1 ms. **2.6%** long-tail delays > 250 ms (max 810 ms).
- **8.0 Hz:** Achieved 4.81 commands/sec throughput (100% success). Latency: p50 = 192.9 ms, p95 = 300.4 ms. **7.5%** long-tail delays > 250 ms (max 811 ms).
- **Physical Bottleneck Conclusion:** The hardware throughput ceiling plateaus around **4.4–4.8 Hz**. Pushing update rates beyond 4.0 Hz does not produce faster light updates; instead, datagrams queue up inside the ESP25 microcontroller, inflating p95 latencies past 300 ms and causing irregular long-tail delays.

### Calibrated Adaptive Rate Controller
The adaptive rate controller balances responsive lighting with network congestion:
- **Calibrated Latency Thresholds:** Real-world round-trip UDP command times on the ESP25 average ~110–125 ms.
  - **Step-Up Threshold:** `p95 <= 115.0 ms` with at least 10 consecutive successful commands.
  - **Step-Down Threshold:** `p95 >= 135.0 ms` or any dropped packet.
  - **Hysteresis Band:** A 20 ms margin (115–135 ms) prevents rapid rate oscillation.
  - **Adjustment Cooldown:** Enforces a 4.0-second stabilization window between rate adaptations.
  - **Safe Maximum Cap:** Constrained to 5.0 Hz to protect against queue overflow.

### Latency-Aware Beat Preservation & Expiration
- **Dynamic Age Window:** Instead of a static window that causes beats to expire mid-interval at 4 Hz ($T = 250\text{ ms}$), the scheduler calculates effective maximum beat age dynamically:
  $$\tau = \min\left(0.35, \max\left(0.20, \frac{1.25}{\text{rate\_hz}}\right)\right)$$
  At 4.0 Hz, $\tau = 312.5\text{ ms}$, ensuring any beat arriving during the 250 ms interval is preserved for dispatch on the next available slot.
- **Superseding:** If a stronger beat transient arrives while a weaker beat is pending, the stronger beat supersedes it without extra latency.
- **Expiration on Network Stalls:** If a network lag spike delays transmission beyond $\tau$, the pending beat safely expires to prevent jarring, out-of-time lighting pulses.
- **Deterministic Telemetry:** Tracks `beats_received`, `beats_dispatched`, `beats_expired`, `beats_superseded`, and `beat_dispatch_ratio` (achieving 100% dispatch under normal network timing).

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
        ▼                                                     ├── Rate Limiter (2-5 Hz Safe Cap)
   Lighting Effects Engine                                    └── Non-Overlapping Lock
   (Spectrum, Beat, Bass, Smooth, Ambient)                      │
                                                                ▼
                                                          WiZ Smart Bulb
                                                          (UDP Port 38899)
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
python -m src.music_sync --ip 192.168.1.4 --effect bass --rate 4.0 --adaptive-rate

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

### Complete Test Coverage (225 Passing Tests)
- **`tests/test_beat_expiration.py` (4 tests):** Deterministic arrival offsets within interval, transient superseding, network delay expiration, and 50-interval timing simulation verifying 100% dispatch ratio on healthy timing.
- **`tests/test_audio_eval_dataset.py` (5 tests):** 7-category comparative dataset evaluation (silence, acapella vocals, quiet drums, strong kicks, sustained 808 basslines, acoustic percussion, full instrumental) verifying percussion isolation and vocal rejection.
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
