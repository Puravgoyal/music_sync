# WiZ Music Sync — Phase 1: Local Discovery & Bulb Control

**WiZ Music Sync** is an application for Windows designed to synchronize Philips Lighting WiZ smart bulbs with audio playback.

This repository represents **Phase 1** of the project: a reliable, robust local network discovery and LAN control foundation for compatible WiZ smart bulbs **without requiring the WiZ mobile app to remain open**.

---

## 1. Supported Hardware

- **Primary Target:** Philips Lighting WiZ Wi-Fi Enabled Smart Bulb (Multicolour), E27
- **Model Identified:** `ESP25_SHRGB_01` (Firmware: `1.38.0`)
- **Capabilities Supported:**
  - Full RGB color control (0–255 per channel)
  - Tunable White / Color Temperature (2200K – 6500K)
  - Dimming / Brightness (0–255 scale)
  - Power switching (ON / OFF)
  - Real-time hardware state querying

---

## 2. Prerequisites & Python Version

- **Operating System:** Windows 10 / Windows 11 (PowerShell recommended)
- **Python Version:** Python 3.11 or higher
- **Network Requirements:**
  - Bulb and computer must be connected to the **same 2.4 GHz local Wi-Fi network**.
  - Local UDP communication on port `38899` must not be blocked by router AP client isolation or host firewalls.

---

## 3. Installation & Setup

Open PowerShell in the project directory:

```powershell
# 1. Clone or navigate to the repository
git clone https://github.com/Puravgoyal/music_sync.git
cd music_sync

# 2. Create Python virtual environment
python -m venv .venv

# 3. Activate the virtual environment
.\.venv\Scripts\Activate.ps1

# 4. Install dependencies
pip install -r requirements.txt
```

### Dependencies

- [`pywizlight>=0.6.6`](https://pypi.org/project/pywizlight/): Asynchronous UDP control library for WiZ local LAN protocol.
- [`pytest>=8.0.0`](https://pypi.org/project/pytest/): Automated test framework.
- [`pytest-asyncio>=0.23.0`](https://pypi.org/project/pytest-asyncio/): Asynchronous test runner for asyncio coroutines.

---

## 4. Usage Instructions

### A. Automatic Bulb Discovery

To automatically scan your local network for compatible WiZ bulbs and inspect their model, power state, brightness, and capabilities:

```powershell
python -m src.main --discover-only
```

To run discovery and immediately launch the interactive hardware test menu upon finding the bulb:

```powershell
python -m src.main
```

### B. Manual IP Fallback Mode

If your Wi-Fi router blocks UDP broadcast packets or you prefer connecting directly to a known bulb IP:

```powershell
python -m src.main --ip 192.168.1.4
```

You can also specify custom timeouts or broadcast targets:

```powershell
# Custom discovery timeout (e.g. 5 seconds)
python -m src.main --timeout 5.0

# Explicit subnet broadcast address
python -m src.main --broadcast 192.168.1.255

# Verbose debug logging
python -m src.main -v
```

---

## 5. Interactive Hardware Test Utility

Once connected to your bulb, the program presents an interactive CLI test menu:

```
=======================================================
           WiZ Music Sync — Hardware Test
=======================================================
Target Bulb:  192.168.1.4 (MAC: cc4085d19ea0)
Model:        ESP25_SHRGB_01 (RGB Tunable, 2200K-6500K)
Firmware:     1.38.0
Kelvin Range: 2200K - 6500K
=======================================================

Options:
 1.  Get bulb state
 2.  Turn bulb ON
 3.  Turn bulb OFF
 4.  Set RED
 5.  Set GREEN
 6.  Set BLUE
 7.  Set WHITE
 8.  Set brightness
 9.  Set custom RGB
 10. Test color temperature
 11. Run RGB test sequence
 12. Device information & capabilities
 0.  Exit

Enter selection [0-12]:
```

### Test Actions

1. **Option 1 (`Get bulb state`):** Queries live power state, brightness, RGB, and Kelvin.
2. **Option 2 (`Turn bulb ON`):** Sends power ON command.
3. **Option 3 (`Turn bulb OFF`):** Sends power OFF command.
4. **Option 4 (`Set RED`):** Sets bulb to pure red `(255, 0, 0)`.
5. **Option 5 (`Set GREEN`):** Sets bulb to pure green `(0, 255, 0)`.
6. **Option 6 (`Set BLUE`):** Sets bulb to pure blue `(0, 0, 255)`.
7. **Option 7 (`Set WHITE`):** Sets bulb to pure white `(255, 255, 255)`.
8. **Option 8 (`Set brightness`):** Prompts for brightness `0–255` (`0` turns the bulb off).
9. **Option 9 (`Set custom RGB`):** Prompts for three channel values `R G B` (`0–255` each).
10. **Option 10 (`Test color temperature`):** Prompts for Kelvin temperature within the bulb's supported range (`2200K–6500K`).
11. **Option 11 (`Run RGB test sequence`):** Conservatively cycles `RED -> GREEN -> BLUE -> WHITE` with 1.5-second pauses between transitions.
12. **Option 12 (`Device information`):** Displays hardware model, MAC, firmware, and supported feature flags.
13. **Option 0 (`Exit`):** Gracefully closes socket connections and exits.

---

## 6. Running Automated Tests

The automated test suite runs independently of any physical bulb by mocking network communication and verifying validation logic:

```powershell
.\.venv\Scripts\pytest -v
```

### Test Coverage

- **`tests/test_validation.py`:**
  - IPv4 address format validation, rejecting invalid IPs, loopbacks, multicasts, and empty strings.
  - Brightness bounds validation (`0–255`) and rejection of negative values, overflows, and non-integers.
  - RGB channel validation (`0–255` per channel) and type enforcement.
  - Kelvin color temperature validation (`2200K–6500K`) and type enforcement.
- **`tests/test_controller.py`:**
  - Initialization, capability parsing, and state querying.
  - Power ON / OFF command dispatch.
  - Setting brightness, RGB, and color temperature.
  - Graceful handling of hardware with unsupported capabilities.
  - Timeout and connection error handling.
  - Async context manager cleanup.
- **`tests/test_discovery.py`:**
  - UDP probe packet generation and parsing.
  - Filter verification for loopback / self-echoed broadcast packets.
  - Rejection of malformed / non-WiZ UDP packets.
  - Graceful degradation when querying bulbs with partial attributes.
  - Local subnet broadcast address detection on Windows.

---

## 7. Troubleshooting

| Issue | Cause | Solution |
| :--- | :--- | :--- |
| **No devices found during discovery** | Computer is on a 5 GHz band while bulb is on 2.4 GHz | Ensure your computer is connected to the same 2.4 GHz Wi-Fi SSID. |
| **Router AP Isolation active** | Router prevents LAN clients from talking to each other | Disable AP Isolation / Client Isolation in router admin settings, or use manual IP fallback. |
| **Broadcast blocked by firewall** | Windows Firewall blocking UDP 38899 broadcast | Run with `--ip <bulb-ip>` for direct unicast control. |
| **Timeout when connecting to IP** | Bulb is powered off at wall switch or assigned a new DHCP IP | Verify bulb is turned on and check router DHCP client table for current IP. |

---

## 8. Known Limitations (Phase 1)

- **Local LAN only:** Operates directly over local UDP; does not rely on or sync with WiZ cloud servers.
- **Audio & GUI:** Audio capture (WASAPI), FFT, beat detection, and GUI will be implemented in subsequent phases.
