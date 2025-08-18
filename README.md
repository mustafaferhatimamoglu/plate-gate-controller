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
