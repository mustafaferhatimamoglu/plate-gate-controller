Plate Gate Controller

Overview

- Connects to an RTSP camera, detects license plates, OCRs them, and decides actions based on datasets (allow/deny/watch).
- Triggers actuators (gate open/close, alarm) and sends Telegram notifications to configured groups.

Quick Start

1) Install Python 3.9+ and Tesseract OCR (optional but recommended)
   - Windows: Install Tesseract and add to PATH (or set `tesseract_cmd` in config)
   - Linux: `sudo apt-get install tesseract-ocr`

2) Create virtualenv and install dependencies
   - python -m venv .venv
   - .venv\\Scripts\\activate (Windows) or source .venv/bin/activate (Linux/Mac)
   - pip install -r requirements.txt

3) Configure
   - Edit `config.yaml` with your RTSP URL, plate rules, actuators, and Telegram settings.
   - Place any cascade/model files under `models/` and set their paths in config if using.

4) Run
   - python -m app.main

Project Structure

- app/
  - main.py: Entry point
  - config.py: Loads and validates configuration
  - stream.py: RTSP frame capture
  - detector.py: Plate detection (cascade or contour-based fallback)
  - ocr.py: Plate OCR via Tesseract
  - rules.py: Dataset loading and decision logic
  - pipeline.py: End-to-end inference loop and actions
  - actions/
    - actuators.py: Gate and alarm actuators (HTTP/dry-run)
    - notify.py: Telegram notifications
- data/
  - allowed.csv, denied.csv, watchlist.csv: Sample datasets
- config.yaml: Configuration
- requirements.txt: Python dependencies

Notes

- Detection: If you have a plate-specific model/cascade, set `detector.cascade_path` in config. Otherwise, the fallback uses basic contour heuristics.
- OCR: Requires Tesseract installed; otherwise pipeline runs but OCR returns empty.
- Telegram: Provide `bot_token` and `chat_ids` in `config.yaml`. The app batches and debounces notifications to avoid spam.
- Actuators: HTTP endpoints are optional; by default, actions are logged (dry-run). Configure as needed.

Debug via Telegram

- To forward logs to Telegram (instead of showing a debug window), set:
  - `logging.level: "DEBUG"`
  - `logging.forward_to_telegram: true`
  - `notify.telegram.enabled: true`
  - Optionally set `notify.telegram.debug_chat_ids` to route debug logs; otherwise `chat_ids` are used.
  - You can disable `--display` and rely entirely on Telegram logs and photos.

Diagnostics

- Run startup diagnostics to verify token and chat IDs:
  - Enable in config: `notify.telegram.diagnose_on_start: true`, or
  - CLI: `python -m app.main --diag-telegram`
- The app calls `getMe` and sends a test message to `chat_ids` and `debug_chat_ids`, logging any Telegram API errors like:
  - `Bad Request: chat not found` → wrong `chat_id` or bot not added to the group/channel
  - `Forbidden: bot was blocked by the user` → user blocked bot; DM won’t work
  - `Forbidden: bot is not a member of the channel chat` → add bot to channel/group and grant rights

Unreadable Plate Notifications

- To receive a photo when a vehicle is detected but the plate cannot be read:
  - `notify.telegram.notify_unreadable: true`
  - `notify.telegram.unreadable_debounce_sec: 10` (adjust to control frequency)
  - The pipeline sends a frame with a caption “Vehicle detected: plate unreadable”.

Dedup for Unreadable Vehicles

- The app uses perceptual hashing (dHash) to avoid sending duplicate unreadable vehicles across frames.
- Tuning options in `config.yaml`:
  - `notify.telegram.unreadable_dhash_threshold: 6` — Max Hamming distance to consider two ROIs the same car.
  - `notify.telegram.unreadable_global_cooldown_sec: 8` — Global minimum seconds between unreadable notifications.
  - `notify.telegram.unreadable_debounce_sec: 10` — Per-ROI hash debounce window.

Direction Estimation

- Configure how inbound/outbound is labeled in captions:
  - `direction.enabled: true`
  - `direction.axis: "y"`  (use "x" for left↔right movement; "y" for up↕down)
  - `direction.invert: false` (set true if labels look flipped for your camera)
  - `direction.min_displacement: 20` pixels minimal motion to consider
  - `direction.gate_line: null` (set to an `x` or `y` coordinate on the chosen axis to detect line crossings)
- Captions now include the direction, e.g., `Plate ABC123 (in) -> ALLOW` or `Vehicle detected (out): plate unreadable`.

Calibration Helper

- Launch: `python -m app.main --calibrate`
- Purpose: Visually set `axis`, `invert`, `min_displacement`, and `gate_line` without editing files.
- Mouse:
  - Left click: Edit ROI. For rectangle mode: first click = corner 1, second click = corner 2. For polygon mode: each click adds a vertex.
  - Ctrl + Left click: Set `gate_line` on the active axis at the clicked coordinate.
- Keys:
  - `x`: Toggle axis (`y` ↔ `x`)
  - `i`: Toggle invert (swap IN/OUT)
  - `+` / `-`: Increase/decrease `min_displacement`
  - `t`: Toggle ROI enabled/disabled
  - `p`: Toggle ROI mode (rectangle ↔ polygon)
  - `n`: Clear ROI (reset rectangle/polygon)
  - `w`: Save current direction settings into `config.yaml`
  - `q`: Quit calibration
- Overlay: Shows orange gate line, last detection center (yellow), and current settings as text.
- Safety: In calibration mode, actuators (gate/alarm) are suppressed; Telegram bildirimleri gönderilmeye devam eder.

ROI Basics

- Limit detections to a smaller area to avoid road traffic alerts.
- Config section:
  - `roi.enabled: true|false`
  - `roi.mode: rectangle|polygon`
  - `roi.rect: [x1, y1, x2, y2]`
  - `roi.polygon: [[x, y], ...]`

Startup/Shutdown Notices

- The app sends a startup (`🚀`) and shutdown (`🛑`) message via Telegram.
- If you don't see messages:
  - Start a chat with your bot and send any message first (so the bot can DM you).
  - Use numeric chat IDs. For channels/supergroups, add the bot and use negative IDs (e.g., `-1001234567890`).
  - Ensure `notify.telegram.enabled: true` and `bot_token` is correct.

ESP32 GPIO Example (HTTP)

- Many ESP32 sketches expose a simple HTTP API like `/gpio?pin=12&state=1`.
- You can drive the gate via existing HTTP actuator in `config.yaml`:

```
actions:
  gate:
    mode: "http"
    http:
      open_url:  "http://<ESP32-IP>/gpio?pin=12&state=1"
      close_url: "http://<ESP32-IP>/gpio?pin=12&state=0"
      method: "GET"
  alarm:
    mode: "http"
    http:
      trigger_url: "http://<ESP32-IP>/gpio?pin=27&state=1"
      method: "GET"
```

- If your firmware expects POST/JSON, set `method: "POST"` and fill `payload_template` fields; the app adds `{"plate": "XYZ"}` automatically.
