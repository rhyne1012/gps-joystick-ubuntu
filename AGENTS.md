# AI / Developer Handoff Guide — GPS Joystick Ubuntu

This file documents everything a future AI agent or developer needs to operate, troubleshoot, and extend **GPS Joystick Ubuntu**.

## Locations & Links

- **Local repository**: `/home/rhyne-dynabook/.gemini/antigravity/scratch/gps-joystick-ubuntu`
- **Public GitHub repo**: `https://github.com/rhyne1012/gps-joystick-ubuntu`
- **Ubuntu Desktop shortcut**: `/home/rhyne-dynabook/Desktop/gps-joystick-ubuntu.desktop`
- **Launcher script**: `/home/rhyne-dynabook/.gemini/antigravity/scratch/gps-joystick-ubuntu/scripts/launch-gps-joystick.sh`
- **Web UI URL**: `http://127.0.0.1:8765`

## Verified Target Environment

- **Host OS**: Ubuntu 24.04.5 LTS, Python 3.12, `uv`, `usbmuxd`
- **Tested iPhone**: iPhone 13 (`iPhone14,5`), **iOS 27.2.1**
- **iOS Bridge**: `pymobiledevice3 >= 11.63.1` (verified on `11.63.1`)
- **Privilege model**: **No `sudo` required** (`PreferredRsdTunnel` uses `pymobiledevice3`'s pure-Python userspace tunnel).

## How to Launch & Use

1. **Interactive Web UI** (opens browser automatically at `http://127.0.0.1:8765`):
   ```bash
   cd /home/rhyne-dynabook/.gemini/antigravity/scratch/gps-joystick-ubuntu
   uv run gps-joystick-ubuntu
   ```
   - Pass `--app` to launch in Chrome/Chromium standalone window mode.
   - Pass `--no-browser` for headless/daemon startup.
   - Or run `./scripts/launch-gps-joystick.sh` (used by the Desktop `.desktop` shortcut; if `127.0.0.1:8765` is already listening, it simply opens the UI via `xdg-open` instead of failing on port conflict).

2. **CLI Diagnostic & Single-Shot GPS Probe** (`probe_iphone.py`):
   ```bash
   uv run python probe_iphone.py                  # Check lsusb, usbmuxd, pairing, Developer Mode
   uv run python probe_iphone.py pair             # Trigger USB Trust prompt on iPhone
   uv run python probe_iphone.py reveal-dev-mode  # Reveal Developer Mode toggle in iOS Settings
   uv run python probe_iphone.py mount-ddi        # Mount Personalized Developer Disk Image
   uv run python probe_iphone.py probe --test-location  # Set Taipei 101 for 2s, then clear()
   ```

3. **Tests**:
   ```bash
   uv run python -m unittest discover -s tests -v
   ```

## Architecture Overview

- `src/gps_joystick_ubuntu/navigation.py` — `GeoPoint`, `StickInput`, `NavigationEngine` (WGS-84 geodesic motion, deadzone, trail cap).
- `src/gps_joystick_ubuntu/iphone_session.py` — Async `IPhoneSessionManager` (`usbmux.list_devices`, `create_using_usbmux`, `PreferredRsdTunnel`, `DvtProvider`, `LocationSimulation`, `AmfiService`, `auto_mount`).
- `src/gps_joystick_ubuntu/search.py` — Keyless geocoding via Photon (`photon.komoot.io`) with Nominatim fallback.
- `src/gps_joystick_ubuntu/server.py` — FastAPI app + 30Hz simulation loop + 0.25s throttled iPhone sync + automatic `clear()` on disconnect/shutdown.
- `src/gps_joystick_ubuntu/static/` — Leaflet 1.9.4 dark UI (`index.html`, `style.css`, `app.js`, `icon.svg`).

## Critical Operational Notes / Gotchas

1. **Always restore real GPS**: When testing or closing sessions, ensure `LocationSimulation.clear()` runs (`恢復定位` / `中斷連線` in UI, or clean server shutdown).
2. **USB cable & port check**: If `lsusb` shows no `05ac:*` Apple device and `usbmuxd` stays `inactive`, verify the cable supports data (not charge-only), unlock the iPhone, and prefer direct USB-A/host ports if a Type-C port shows `ucsi_acpi` errors.
3. **Map tiles**: Do **not** revert to `basemaps.cartocdn.com/dark_all/...` — Carto's keyless endpoint returns `"API KEY REQUIRED"` placeholder PNGs. Keep `tile.openstreetmap.org` with `.map-dark-tiles` CSS filter (`style.css`).
4. **Scope**: USB GPS location joystick only (Bluetooth HealthKit step sync from the macOS inspiration repo `gift-1215/GPSJoystick` is intentionally excluded).
