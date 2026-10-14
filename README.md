# WiZ Music Sync — Real-Time Windows Audio, Screen Ambience & Smart Lighting

**WiZ Music Sync** is a modern Windows desktop application designed to synchronize Philips Lighting WiZ smart bulbs with system audio playback (Spotify, YouTube, media players, games), screen visuals (movies, streams, gaming Ambilight), and hybrid audio/video synchronization.

- **Phase 1:** Local WiZ UDP protocol control, capability discovery, and hardware verification.
- **Phase 2:** Low-latency Windows WASAPI loopback system audio capture, FFT spectrum analysis, frequency band energy parsing, and musical onset transient detection.
- **Phase 3:** Real-time music-to-light synchronization, 5 reactive lighting modes, rate-limited coalescing WiZ command scheduler, deadband filtering, and pre-sync state restoration.
- **Phase 4:** Polished PySide6 Windows desktop application, transactional startup rollback, accurate active lighting mode restoration, multithreaded async event loop bridge, local preferences persistence, and PyInstaller Windows executable packaging.
- **Phase 4.3:** Enhanced beat detection & vocal suppression (Full Music, Rhythm Focus, Kick Focus), dual-resolution 2048-sample low-frequency FFT, latency-aware beat preservation, adaptive bulb update rate controller, and physical hardware rate benchmarking.
- **Phase 5:** Screen Ambience (Ambilight) and Hybrid Audio/Video synchronization. Windows screen capture (Qt/DWM + DXcam fallbacks) with multi-monitor and DPI scaling awareness, linear sRGB color extraction (Average Screen Color, Dominant Color, Edge-Based Ambience), cinematic processing (black-bar letterbox/pillarbox detection, subtitle resistance, dark scene scaling, stale frame recovery), temporal circular hue smoothing, and Hybrid AV sync (video-driven RGB + audio-driven rhythmic/loudness brightness modulation) orchestrated under a unified synchronization engine.

---

## 1. Supported Hardware, Audio Devices & Displays

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
  - Calibrated physical rate ceiling: ~4.0 Hz safe operating rate

### Audio Output Devices (WASAPI Loopback)
- **Supported Outputs:** Internal Speakers, 3.5mm Headphones, USB DACs, and compatible Bluetooth audio devices (e.g. Stone 1508).
- **Audio Capture Mechanism:** Windows Audio Session API (WASAPI) process-independent system loopback via `PyAudioWPatch`.
- **Microphone Isolation:** Only system playback audio is captured; laptop microphones are completely excluded.

### Displays & Screen Capture (Windows DWM / DXGI)
- **Supported Displays:** Single- and multi-monitor Windows setups with full DPI scaling awareness (100%, 125%, 150%, 200%).
- **Multi-GPU / Hybrid Laptops:** Operates cleanly on systems with integrated Intel/AMD GPUs alongside dedicated NVIDIA GPUs without desktop duplication permission conflicts.
- **Capture Backends:**
  - `QtCaptureBackend` (Default / Recommended): Captures via Windows Desktop Window Manager (DWM) compositor at ~8.5 ms per frame, completely free of session lockouts and GPU vendor bugs.
  - `DXCamCaptureBackend`: Optional high-speed DXGI Desktop Duplication backend for supported interactive sessions.
  - `MockCaptureBackend`: Deterministic synthetic frame generator for automated headless CI/CD testing.

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
1. **Synchronization Source Selector:** Top toggle allowing seamless switching between **🎵 Music Sync**, **🖥️ Screen Sync (Ambilight)**, and **⚡ Hybrid AV Sync**.
2. **WiZ Smart Bulb Connection:** One-click network scan, dropdown bulb selector with IP and MAC, manual IP input, connection testing, and live status.
3. **Audio Capture Source:** Dropdown of Windows WASAPI loopback devices indicating system defaults, with auto-refresh on device plug/unplug.
4. **Screen Ambience Panel (Phase 5):**
   - Display monitor selector (auto-enumerating multi-monitor geometry and scaling).
   - Color extraction strategy: Average Screen Color, Dominant Color, or Edge-Based Ambience.
   - Edge zone selector (Left, Right, Top, Bottom, All) and configurable edge thickness slider (5%–30%).
   - Temporal smoothing preset: Cinematic Smooth, Balanced, or Responsive.
   - Cinematic black-bar letterbox/pillarbox detection checkbox.
   - Minimum and maximum brightness limit sliders.
5. **Hybrid AV Panel (Phase 5):**
   - Hybrid style: Cinematic Hybrid (loudness modulation), Rhythm Hybrid (percussive hits), or Kick Hybrid (low-frequency beats).
   - Audio Focus selector: Full Music, Rhythm Focus, or Kick Focus.
   - Audio contribution slider (0% = pure video color, 100% = full audio brightness modulation).
   - Beat intensity slider.
6. **Live Synchronization Preview & Telemetry:**
   - 3-swatch visual monitor: Captured Screen Color, Target Computed State, and Acknowledged Bulb Output.
   - Real-time command throughput (updates/sec), adaptive rate status, p95 round-trip UDP latency, screen capture FPS, and capture health badge.
7. **Live Audio Spectrum & Rhythm:** Real-time animated level meters for Bass (20–250 Hz), Mid (250–4000 Hz), Treble (4–16 kHz), Master Loudness, and a live transient hit badge (`⚡ KICK HIT!`, `⚡ PERCUSSION HIT!`, or `⚡ BEAT DETECTED!`).
8. **Music Reactive Effect & Tuning:** Dropdown for all 5 music modes with dynamic descriptions, plus sliders for audio sensitivity, attack, release, and rate limits.

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

## 5. Three Unified Synchronization Modes

### Mode A — Music Sync
Transforms system audio into music-reactive lighting effects:
- Preserves all 5 existing music effects: **Spectrum RGB**, **Beat Pulse**, **Bass Reactive**, **Smooth Spectrum**, and **Ambient Flow**.
- Powered by 3 selectable audio focus modes: **Full Music**, **Rhythm Focus**, and **Kick Focus**.
- Rates dynamically managed by the calibrated adaptive rate controller (2.0–5.0 Hz).

### Mode B — Screen Sync (Ambilight)
Transforms on-screen visuals (movies, YouTube, streaming media, games) into real-time ambient lighting:
- Captures frames at 10–15 FPS and downsamples to a high-efficiency 64×36 analysis grid.
- Extracts visual color using Average, Dominant, or Edge-Based algorithms.
- Filters out letterbox black bars and suppresses subtitle flicker.
- Applies temporal smoothing with circular shortest-path hue wrapping.
- Dispatches states to the bulb via the rate-limited coalescing scheduler (~4 Hz).

### Mode C — Hybrid AV Sync
Fuses visual color with acoustic rhythm:
- **Video determines color:** The bulb's hue and base saturation are strictly driven by screen capture.
- **Audio determines dynamic brightness:** Loudness, percussive transients, and kick beats modulate brightness dynamically without shifting the film's palette.
- **Three hybrid styles:**
  - *Cinematic Hybrid:* Master audio loudness modulates brightness smoothly. Ideal for cinematic films and TV shows.
  - *Rhythm Hybrid:* Rhythm Focus isolates snare/clap percussion attacks to create crisp brightness pulses.
  - *Kick Hybrid:* Kick Focus isolates low-frequency kick drum attacks for energetic concerts and music videos.
- **Adjustable Blend:** Audio contribution slider allows continuous blending from 0% (pure screen color) to 100% (full dynamic range audio modulation).

---

## 6. Color Extraction & Cinematic Processing (Phase 5)

### Color Extraction Strategies
1. **Average Screen Color (`average`):**
   - Converts pixels from sRGB to linear-light RGB ($C_{linear} = C_{sRGB}^\gamma$) before computing spatial averages to avoid perceptual dark-bias artifacts.
   - Features **Anti-Gray Saturation Preservation**: When opposing primary colors (e.g. red and blue) appear simultaneously, naive averaging produces washed-out muddy gray. The algorithm calculates scene saturation and boosts the dominant chromatic hue if the average saturation drops below 0.18.
2. **Dominant Color (`dominant`):**
   - Quantizes colors into compact hue-saturation histogram bins.
   - Applies saliency weighting: prioritizes saturated, vivid colors over bland backgrounds.
   - **Subtitle & Overlay Resistance:** Pixels with low saturation ($S < 0.15$) and high luminance ($V > 0.85$) are heavily downweighted, preventing white movie subtitles and desktop UI text from skewing the detected lighting.
3. **Edge-Based Ambience (`edge`):**
   - Analyzes perimeter zones corresponding to physical bulb placement: Left, Right, Top, Bottom, or All edges.
   - Configurable depth margin (5% to 30% of screen dimensions).
   - Accurately reduces the selected perimeter to a single cohesive color suitable for single-bulb illumination.

### Cinematic Processing Improvements
- **Black-Bar Detection:** Scans top, bottom, and lateral borders for persistent letterbox ($2.39:1$ anamorphic) or pillarbox ($4:3$ classic) black bars ($V < 0.08$) and crops them out to prevent black bars from dragging down ambient brightness.
- **Dark Scene Brightness Scaling:** When a scene becomes genuinely dark, brightness smoothly scales down toward the user-configured minimum brightness floor. The bulb never abruptly shuts off or cycles power.
- **Capture Failure & Stale Frame Recovery:** If screen capture stalls or window access is interrupted, the engine holds the last known color for 1.5 seconds, then smoothly transitions to a safe ambient warm white fallback, logging health warnings in the UI.

---

## 7. Temporal Color Smoothing & Transition Presets

To prevent harsh flickering caused by rapid film scene cuts or fast-moving game objects, `TemporalColorSmoother` applies time-domain filtering:

- **Circular Shortest-Path Hue Interpolation:**
  Because hue is a circular angle ($0^\circ \equiv 360^\circ$), linear interpolation across red ($355^\circ \to 5^\circ$) would incorrectly swing 350 degrees through greens and cyans. The smoother computes the circular shortest angular delta:
  $$\Delta h = ((h_{target} - h_{current} + 0.5) \pmod{1.0}) - 0.5$$
- **Asymmetrical Attack/Release Brightness:**
  Light levels rise quickly on sudden illumination (attack) and decay gently into darkness (release), replicating human visual persistence.
- **Selectable Presets:**
  - **Cinematic Smooth (Default):** Slow, atmospheric transitions ($\alpha_{color} = 0.12$, $\alpha_{att} = 0.25$, $\alpha_{rel} = 0.10$). Eliminates all micro-flickering during dialogue and slow-panning scenes.
  - **Balanced:** Moderate responsiveness ($\alpha_{color} = 0.25$, $\alpha_{att} = 0.45$, $\alpha_{rel} = 0.20$). Ideal for general streaming and TV shows.
  - **Responsive:** Fast reaction time ($\alpha_{color} = 0.50$, $\alpha_{att} = 0.75$, $\alpha_{rel} = 0.40$). Best suited for high-tempo gaming and action films.

---

## 8. Screen Capture Architecture, Performance & Privacy

### Architecture & Backend Selection
```
┌────────────────────────────────────────────────────────────────────────┐
│                         ScreenCaptureManager                           │
│   ├── Auto Backend Selector                                            │
│   │    ├── Primary: QtCaptureBackend (DWM Compositor via QScreen)      │
│   │    ├── Fallback: DXCamCaptureBackend (DXGI Desktop Duplication)    │
│   │    └── Test Harness: MockCaptureBackend                            │
│   └── Multi-Monitor Enumeration (Geometry, Physical Size, DPI Scaling) │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ (64x36 Downsampled Frame @ ~12 FPS)
┌───────────────────────────────────▼────────────────────────────────────┐
│                         ScreenColorAnalyzer                            │
│   ├── Cinematic Processing (Black-bar cropping, subtitle filtering)    │
│   ├── Color Extraction (Average, Dominant, Edge algorithms)            │
│   ├── Dark Scene Brightness Scaling                                    │
│   ├── TemporalColorSmoother (Circular hue wrapping, attack/release)    │
│   └── CaptureFallbackManager (Stale frame fadeout)                     │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ LightingState (RGB, Brightness)
                                    ▼
                          BulbCommandScheduler
```

- **Execution Speed:** Downsampled frame capture and NumPy-based color analysis execute in under **10 ms** per frame on standard hardware, consuming less than 2% CPU.
- **DPI Scaling & Multi-Monitors:** Multi-monitor setups and non-standard DPI scaling factors (125%, 150%) are automatically detected via Qt/Win32 APIs and correctly normalized.
- **Privacy Assurance:**
  - 100% in-memory processing.
  - No screenshots or video frames are ever saved to disk.
  - No screen pixels are transmitted over the local network or internet.
  - Zero cloud APIs, telemetry, or external analytics services.
- **Hardware & Windows Limitations:**
  - **Protected Content (DRM):** Hardware-accelerated DRM streams (Netflix, Disney+, protected Blu-ray players) enforce HDCP encryption via Windows graphics sub-systems. Pixels inside protected windows capture as solid black. This is an intentional Windows security safeguard and is not bypassed.
  - **Single Bulb Representation:** The physical hardware is a single WiZ bulb. While edge zones allow spatial mapping (e.g. tracking the right side of the screen), the physical bulb renders a single representative color rather than multiple simultaneous spatial zones.

---

## 9. Music-Reactive Lighting Effects & Focus Modes (Phases 1–4.3)

1. **Mode 1 — Spectrum RGB (`spectrum`):** Tri-band energy mapped to Bass $\to$ Red, Mid $\to$ Green, Treble $\to$ Blue.
2. **Mode 2 — Beat Pulse (`beat`):** Steady ambient base color with responsive brightness kicks on detected rhythmic onsets.
3. **Mode 3 — Bass Reactive (`bass`):** Kick drum and bassline focus driving dynamic crimson-to-orange-to-magenta hue shifts.
4. **Mode 4 — Smooth Spectrum (`smooth`):** Maps spectral balance centroid to continuous circular HSV hue with seamless interpolation.
5. **Mode 5 — Ambient Flow (`ambient`):** Slow atmospheric continuous color drift subtly guided by the music spectrum.

### Audio Focus DSP Modes
- **Full Music (`full`):** 100% broad-spectrum analysis across 20 Hz – 16 kHz.
- **Rhythm Focus (`rhythm`):** Vocal suppression via harmonic floor subtraction ($\alpha \approx 0.1$) across 200–1400 Hz voice fundamental region; percussion-weighted spectral flux.
- **Kick Focus (`kick`):** Dual-resolution 2048-sample ring buffer FFT ($23.44\text{ Hz}$ bin resolution) isolating fundamental bass kick frequencies (40–180 Hz) and attack slope differentiation.

---

## 10. High-Speed Bulb Optimization & Rate Benchmarking

The Philips WiZ E27 multicolour bulb uses an Espressif ESP25 microcontroller (`ESP25_SHRGB_01`, firmware `1.38.0`) communicating over local UDP port `38899`.

### Empirical Rate Benchmark Findings
Benchmarked directly against physical hardware (`192.168.1.4`):
- **4.0 Hz (Default):** **100% Stable.** Achieved 3.90 commands/sec throughput with 100% command success rate. Latency: p50 = 120.9 ms, p95 = 202.5 ms. **0.0%** long-tail delays > 250 ms. **Retained as the default safe operating rate.**
- **5.0 Hz – 8.0 Hz:** Throughput plateaus around 4.4–4.8 Hz; datagrams queue inside the microcontroller, inflating p95 latencies past 300 ms with long-tail lag spikes up to 810 ms.
- **Calibrated Adaptive Rate Controller:** Monitors p95 round-trip latency (`p95 <= 115 ms` steps up; `p95 >= 135 ms` steps down) with a 20 ms hysteresis band and 4.0-second cooldown.
- **Latency-Aware Beat Preservation:** Dynamically sizes the beat expiration window ($\tau = \min(0.35, \max(0.20, 1.25 / \text{rate\_hz}))$) so musical onsets arriving between ticks are guaranteed dispatch without mid-interval expiration.

---

## 11. Unified Synchronization Architecture & Reliability

```
┌────────────────────────────────────────────────────────────────────────┐
│                          PySide6 Desktop GUI                           │
│  Mode Selector │ Screen Panel │ Hybrid Panel │ Audio Panel │ Previews  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ (Qt Signals / Thread-Safe Slots)
┌───────────────────────────────────▼────────────────────────────────────┐
│                               SyncWorker                               │
│            (Hosts Background Asyncio Event Loop in QThread)            │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                         MusicSyncEngine                                │
│                   (Unified Synchronization Engine)                     │
│  ├── SyncMode State Machine (MUSIC / SCREEN / HYBRID)                  │
│  ├── Transactional Rollback Lifecycle                                  │
│  ├── Pre-Sync Bulb State Capture & Restoration                         │
│  │                                                                     │
│  ├── [Mode A: Music]   ──> AudioCapture + AudioAnalyzer + MusicEffects │
│  ├── [Mode B: Screen]  ──> ScreenCaptureManager + ScreenColorAnalyzer  │
│  └── [Mode C: Hybrid]  ──> Screen Analyzer + Audio DSP + HybridAVProc │
│                                                                        │
│  └── Single BulbCommandScheduler Invariant                             │
│       ├── Rate-Limiter (4 Hz Safe Cap)                                 │
│       ├── Deadband Filter (Δ4)                                         │
│       ├── State Coalescing                                             │
│       └── Non-Overlapping UDP Execution Lock                           │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Single UDP Socket
                                    ▼
                             WiZ Smart Bulb
                            (UDP Port 38899)
```

### Architectural Safeguards
- **Single Scheduler / Single Controller Invariant:** Regardless of whether Music, Screen, or Hybrid mode is active, exactly one `WizBulbController` instance and one `BulbCommandScheduler` communicate with the bulb. Mode switches never spawn competing network tasks.
- **Transactional Startup Rollback:** If bulb connection, screen capture initialization, or audio loopback fails, all allocated resources are cleanly rolled back, and pre-sync bulb state is restored.
- **True Lighting State Restoration:** Accurately detects and restores RGB, Tunable White, Kelvin, Scene, Dimming, or Off states when synchronization terminates.
- **Thread Decoupling:** GUI main thread, asyncio scheduling loop, WASAPI capture thread, and screen capture worker run in isolated threads with mutex locks, ensuring the interface never stutters.

---

## 12. Command-Line Interface (CLI)

The CLI supports all music sync, focus modes, and adaptive rate parameters:

```powershell
# Run with automatic bulb discovery and Rhythm Focus
python -m src.music_sync --focus rhythm

# Run against specific bulb IP with Beat Pulse and Kick Focus
python -m src.music_sync --ip 192.168.1.4 --effect beat --focus kick

# Run with adaptive update rate enabled
python -m src.music_sync --ip 192.168.1.4 --effect bass --rate 4.0 --adaptive-rate

# Run in simulated DRY-RUN mode (zero network packets)
python -m src.music_sync --dry-run --effect smooth --focus rhythm

# List available effects and audio devices
python -m src.music_sync --list-effects
python -m src.music_sync --list-devices
```

---

## 13. Automated Testing & Verification

Run the full automated test suite:

```powershell
.\.venv\Scripts\pytest -v
```

### Complete Test Coverage (265 Passing Tests)
- **`tests/test_color_extraction.py` (9 tests):** Linear sRGB conversions, average color extraction with anti-gray saturation preservation, dominant color extraction with histogram binning and subtitle resistance, and directional perimeter slicing for edge ambience.
- **`tests/test_smoothing.py` (7 tests):** Circular shortest-path hue wrapping across 0°/360° boundary, asymmetric attack/release brightness dynamics, scene cut acceleration, and preset configurations (Cinematic, Balanced, Responsive).
- **`tests/test_screen_capture.py` (8 tests):** ScreenCaptureManager backend lifecycle, multi-monitor enumeration, DPI scaling awareness, frame downsampling to 64×36, black-bar letterbox/pillarbox detection and cropping, and capture fallback fadeout.
- **`tests/test_hybrid_av.py` (7 tests):** HybridAVProcessor mode routing (Cinematic, Rhythm, Kick), video color dominance, audio loudness modulation, rhythm onset pulses, kick transients, and audio contribution weighting (0% to 100%).
- **`tests/test_unified_sync_engine.py` (5 tests):** Unified engine mode transitions (MUSIC, SCREEN, HYBRID), single scheduler invariant enforcement, transactional startup rollback, and pre-sync state capture/restoration.
- **`tests/test_screen_preferences.py` (4 tests):** Screen and Hybrid configuration schema serialization, JSON round-tripping, boundary clamping, and migration defaults.
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
