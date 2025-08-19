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
    parser.add_argument("--diag-telegram", action="store_true", help="Run Telegram diagnostics at startup")
    parser.add_argument("--calibrate", action="store_true", help="Calibration helper UI for direction settings")
    args = parser.parse_args()

    cfg = load_config(args.config)
    setup_logging(cfg.logging.level)

    stream = RTSPStream(cfg.camera.rtsp_url, cfg.camera.frame_resize_width, cfg.camera.read_timeout_sec).start()

    detector = PlateDetector(cfg.detector.cascade_path, cfg.detector.min_area, cfg.detector.debug_draw)
    ocr = PlateOCR(cfg.ocr.enabled, cfg.ocr.tesseract_cmd, cfg.ocr.psm, cfg.ocr.whitelist)
    rules = load_rules(cfg.rules.allowed_csv, cfg.rules.denied_csv, cfg.rules.watchlist_csv)
    gate = GateActuator(cfg.actions_gate.mode, http=cfg.actions_gate.http.__dict__ if hasattr(cfg.actions_gate.http, "__dict__") else None)
    alarm = AlarmActuator(cfg.actions_alarm.mode, http=cfg.actions_alarm.http.__dict__ if hasattr(cfg.actions_alarm.http, "__dict__") else None)
    notifier_main = TelegramNotifier(
        enabled=cfg.notify.telegram.enabled,
        bot_token=cfg.notify.telegram.bot_token,
        chat_ids=cfg.notify.telegram.chat_ids,
        group_routes=cfg.notify.telegram.group_routes,
        send_photos=cfg.notify.telegram.send_photos,
        debug_chat_ids=cfg.notify.telegram.debug_chat_ids,
    )
    # Optional second bot for debug routing
    notifier_debug = None
    if getattr(cfg.notify, 'telegram_debug', None) and cfg.notify.telegram_debug.bot_token:
        notifier_debug = TelegramNotifier(
            enabled=cfg.notify.telegram_debug.enabled,
            bot_token=cfg.notify.telegram_debug.bot_token,
            chat_ids=cfg.notify.telegram_debug.chat_ids,
            group_routes={},
            send_photos=True,
            debug_chat_ids=[],
        )

    if cfg.logging.forward_to_telegram and (cfg.notify.telegram.enabled or (getattr(cfg.notify, 'telegram_debug', None) and cfg.notify.telegram_debug.enabled)):
        # Prefer debug bot for logs if configured
        log_notifier = notifier_debug if (notifier_debug and notifier_debug.enabled) else notifier_main
        tg_handler = TelegramLogHandler(log_notifier, level=getattr(logging, cfg.logging.level.upper(), logging.INFO), prefix="[DEBUG]")
        tg_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logging.getLogger().addHandler(tg_handler)

    # Explicit startup notification (goes to debug channel or fallback to chat_ids)
    try:
        if notifier_debug and notifier_debug.enabled:
            notifier_debug.send_text("🚀 Plate Gate Controller started")
        notifier_main.send_text("🚀 Plate Gate Controller started")
    except Exception:
        pass

    # Optional diagnostics
    if args.diag_telegram or getattr(cfg.notify.telegram, 'diagnose_on_start', False):
        notifier.diagnose(test_message="Bot diag: startup check", include_main=True, include_debug=True)

    pipeline = Pipeline(
        detector=detector,
        ocr=ocr,
        rules=rules,
        gate=gate,
        alarm=alarm,
        notifier=notifier_main,
        debounce_sec=cfg.rules.debounce_sec,
        debug_draw=cfg.detector.debug_draw,
        notify_unreadable=cfg.notify.telegram.notify_unreadable,
        unreadable_debounce_sec=getattr(cfg.notify.telegram, 'unreadable_debounce_sec', 10),
        unreadable_dhash_threshold=getattr(cfg.notify.telegram, 'unreadable_dhash_threshold', 6),
        unreadable_global_cooldown_sec=getattr(cfg.notify.telegram, 'unreadable_global_cooldown_sec', 8),
        direction_enabled=getattr(cfg.direction, 'enabled', True),
        direction_axis=getattr(cfg.direction, 'axis', 'y'),
        direction_invert=getattr(cfg.direction, 'invert', False),
        direction_min_disp=getattr(cfg.direction, 'min_displacement', 20),
        direction_gate_line=getattr(cfg.direction, 'gate_line', None),
        suppress_actuators=args.calibrate,  # block actuators in calibration; keep notifications
        roi_enabled=getattr(cfg.roi, 'enabled', False),
        roi_mode=getattr(cfg.roi, 'mode', 'rectangle'),
        roi_rect=tuple(getattr(cfg.roi, 'rect', [0,0,0,0])),
        roi_polygon=getattr(cfg.roi, 'polygon', []),
        # Filters and routes
        filter_only_in=bool(getattr(cfg, 'notify_filters', {}).get('only_in_direction', False)),
        unreadable_min_hits=int(getattr(cfg, 'notify_filters', {}).get('unreadable_min_hits', 1)),
        hit_ttl_sec=float(getattr(cfg, 'notify_filters', {}).get('hit_ttl_sec', 1.5)),
        center_tolerance_px=int(getattr(cfg, 'notify_filters', {}).get('center_tolerance_px', 40)),
        dir_require_cross=bool(getattr(cfg.direction, 'require_line_cross', False)),
        route_unreadable=str(getattr(cfg, 'notify_routes', {}).get('unreadable', 'debug')),
        route_readable=str(getattr(cfg, 'notify_routes', {}).get('readable', 'main')),
    )
    # Attach optional debug notifier for routing
    pipeline.notifier_main = notifier_main
    pipeline.notifier_debug = notifier_debug

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
        # Mouse callback for calibration
        if args.calibrate:
            win = "Plate Gate"
            def on_mouse(event, mx, my, flags, param):
                if event == cv2.EVENT_LBUTTONDOWN:
                    # Set gate line on current axis
                    if flags & cv2.EVENT_FLAG_CTRLKEY:
                        # CTRL+Click: set gate line
                        if pipeline.direction_axis == 'y':
                            pipeline.direction_gate_line = my
                        else:
                            pipeline.direction_gate_line = mx
                    else:
                        # ROI edit
                        pipeline.roi_enabled = True
                        pipeline._roi_dirty = True
                        if pipeline.roi_mode == 'rectangle':
                            if pipeline._rect_anchor is None:
                                pipeline._rect_anchor = (mx, my)
                                pipeline.roi_rect = (mx, my, mx, my)
                            else:
                                ax, ay = pipeline._rect_anchor
                                pipeline.roi_rect = (ax, ay, mx, my)
                                pipeline._rect_anchor = None
                        else:
                            # polygon
                            if pipeline.roi_polygon is None:
                                pipeline.roi_polygon = []
                            pipeline.roi_polygon.append([mx, my])
            cv2.namedWindow(win)
            cv2.setMouseCallback(win, on_mouse)

        while not stopping:
            frame = stream.read()
            if frame is None:
                time.sleep(0.01)
                continue

            frame_count += 1
            if frame_count % skip == 0:
                pipeline.process_frame(frame)

            if args.calibrate:
                # Draw calibration overlays
                pipeline.draw_calibration_overlay(frame)

            if args.display or cfg.detector.debug_draw or args.calibrate:
                cv2.imshow("Plate Gate", frame)
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    break
                if args.calibrate and key != 255:
                    if key == ord('x'):
                        pipeline.direction_axis = 'x' if pipeline.direction_axis == 'y' else 'y'
                        pipeline._last_center = None
                        pipeline._last_side = None
                    elif key == ord('i'):
                        pipeline.direction_invert = not pipeline.direction_invert
                    elif key == ord('+') or key == ord('='):
                        pipeline.direction_min_disp = min(200, pipeline.direction_min_disp + 2)
                    elif key == ord('-') or key == ord('_'):
                        pipeline.direction_min_disp = max(0, pipeline.direction_min_disp - 2)
                    elif key == ord('t'):
                        pipeline.roi_enabled = not pipeline.roi_enabled
                        pipeline._roi_dirty = True
                    elif key == ord('p'):
                        pipeline.roi_mode = 'polygon' if pipeline.roi_mode == 'rectangle' else 'rectangle'
                        pipeline._roi_dirty = True
                    elif key == ord('n'):
                        # clear ROI
                        pipeline.roi_polygon = []
                        pipeline.roi_rect = (0, 0, 0, 0)
                        pipeline._rect_anchor = None
                        pipeline._roi_dirty = True
                    elif key == ord('w'):
                        try:
                            _write_direction_to_config(args.config, pipeline)
                            _write_roi_to_config(args.config, pipeline)
                            logging.info("Calibration settings saved to %s", args.config)
                            notifier.send_debug_text("💾 Calibration saved to config.yaml")
                        except Exception as e:
                            logging.error("Failed to save direction to config: %s", e)
    except Exception as e:
        logging.exception("Fatal error in main loop: %s", e)
    finally:
        stream.stop()
        cv2.destroyAllWindows()
        try:
            if notifier_debug and notifier_debug.enabled:
                notifier_debug.send_text("🛑 Plate Gate Controller stopped")
            notifier_main.send_text("🛑 Plate Gate Controller stopped")
        except Exception:
            pass
        logging.info("Stopped Plate Gate Controller")

def _write_direction_to_config(path: str, pipeline):
    import yaml
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    data.setdefault('direction', {})
    data['direction']['enabled'] = True
    data['direction']['axis'] = pipeline.direction_axis
    data['direction']['invert'] = bool(pipeline.direction_invert)
    data['direction']['min_displacement'] = int(pipeline.direction_min_disp)
    # gate_line can be None
    data['direction']['gate_line'] = None if pipeline.direction_gate_line is None else float(pipeline.direction_gate_line)
    with open(path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(data, f, sort_keys=False)

def _write_roi_to_config(path: str, pipeline):
    import yaml
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}
    data.setdefault('roi', {})
    data['roi']['enabled'] = bool(pipeline.roi_enabled)
    data['roi']['mode'] = pipeline.roi_mode
    if pipeline.roi_mode == 'rectangle':
        x1, y1, x2, y2 = pipeline.roi_rect
        data['roi']['rect'] = [int(x1), int(y1), int(x2), int(y2)]
        data['roi']['polygon'] = []
    else:
        data['roi']['polygon'] = [[int(x), int(y)] for x, y in (pipeline.roi_polygon or [])]
    with open(path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(data, f, sort_keys=False)


if __name__ == "__main__":
    run()
