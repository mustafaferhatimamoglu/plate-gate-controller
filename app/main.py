import argparse
import logging
import signal
import sys
import time

import cv2

from .config import load_config
from .stream import RTSPStream
from .detector import PlateDetector
from .ocr import PlateOCR
from .rules import load_rules
from .pipeline import Pipeline
from .actions.actuators import GateActuator, AlarmActuator
from .actions.notify import TelegramNotifier
from .logging_telegram import TelegramLogHandler


def setup_logging(level: str):
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def run():
    parser = argparse.ArgumentParser(description="Plate Gate Controller")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--display", action="store_true", help="Show frames with overlays")
    args = parser.parse_args()

    cfg = load_config(args.config)
    setup_logging(cfg.logging.level)

    stream = RTSPStream(cfg.camera.rtsp_url, cfg.camera.frame_resize_width, cfg.camera.read_timeout_sec).start()

    detector = PlateDetector(cfg.detector.cascade_path, cfg.detector.min_area, cfg.detector.debug_draw)
    ocr = PlateOCR(cfg.ocr.enabled, cfg.ocr.tesseract_cmd, cfg.ocr.psm, cfg.ocr.whitelist)
    rules = load_rules(cfg.rules.allowed_csv, cfg.rules.denied_csv, cfg.rules.watchlist_csv)
    gate = GateActuator(cfg.actions_gate.mode, http=cfg.actions_gate.http.__dict__ if hasattr(cfg.actions_gate.http, "__dict__") else None)
    alarm = AlarmActuator(cfg.actions_alarm.mode, http=cfg.actions_alarm.http.__dict__ if hasattr(cfg.actions_alarm.http, "__dict__") else None)
    notifier = TelegramNotifier(
        enabled=cfg.notify.telegram.enabled,
        bot_token=cfg.notify.telegram.bot_token,
        chat_ids=cfg.notify.telegram.chat_ids,
        group_routes=cfg.notify.telegram.group_routes,
        send_photos=cfg.notify.telegram.send_photos,
        debug_chat_ids=cfg.notify.telegram.debug_chat_ids,
    )

    if cfg.logging.forward_to_telegram and cfg.notify.telegram.enabled:
        tg_handler = TelegramLogHandler(notifier, level=getattr(logging, cfg.logging.level.upper(), logging.INFO), prefix="[DEBUG]")
        tg_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logging.getLogger().addHandler(tg_handler)

    # Explicit startup notification (goes to debug channel or fallback to chat_ids)
    try:
        notifier.send_debug_text("🚀 Plate Gate Controller started")
        # Also send a short non-debug notice to main chats
        notifier.send_text("🚀 Plate Gate Controller started")
    except Exception:
        pass

    pipeline = Pipeline(
        detector=detector,
        ocr=ocr,
        rules=rules,
        gate=gate,
        alarm=alarm,
        notifier=notifier,
        debounce_sec=cfg.rules.debounce_sec,
        debug_draw=cfg.detector.debug_draw,
    )

    stopping = False

    def _handle_sig(sig, frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    frame_count = 0
    skip = max(1, cfg.camera.skip_frames)
    last_process = 0.0
    logging.info("Starting Plate Gate Controller")
    try:
        while not stopping:
            frame = stream.read()
            if frame is None:
                time.sleep(0.01)
                continue

            frame_count += 1
            if frame_count % skip == 0:
                pipeline.process_frame(frame)

            if args.display or cfg.detector.debug_draw:
                cv2.imshow("Plate Gate", frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
    except Exception as e:
        logging.exception("Fatal error in main loop: %s", e)
    finally:
        stream.stop()
        cv2.destroyAllWindows()
        try:
            notifier.send_debug_text("🛑 Plate Gate Controller stopped")
        except Exception:
            pass
        logging.info("Stopped Plate Gate Controller")


if __name__ == "__main__":
    run()
