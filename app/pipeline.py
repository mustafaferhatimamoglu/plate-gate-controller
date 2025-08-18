import time
import logging
from collections import deque
from typing import Dict, Optional, Tuple

import cv2

from .detector import PlateDetector
from .ocr import PlateOCR
from .rules import RuleSets, decide
from .actions.actuators import GateActuator, AlarmActuator
from .actions.notify import TelegramNotifier


class Pipeline:
    def __init__(
        self,
        detector: PlateDetector,
        ocr: PlateOCR,
        rules: RuleSets,
        gate: GateActuator,
        alarm: AlarmActuator,
        notifier: TelegramNotifier,
        debounce_sec: int = 15,
        debug_draw: bool = False,
    ):
        self.detector = detector
        self.ocr = ocr
        self.rules = rules
        self.gate = gate
        self.alarm = alarm
        self.notifier = notifier
        self.debounce_sec = debounce_sec
        self.debug_draw = debug_draw
        self.last_seen: Dict[str, float] = {}

    def _should_emit(self, plate: str) -> bool:
        now = time.time()
        last = self.last_seen.get(plate)
        if last is None or (now - last) > self.debounce_sec:
            self.last_seen[plate] = now
            return True
        return False

    def process_frame(self, frame) -> Optional[Tuple[str, str]]:
        boxes = self.detector.detect(frame)
        logging.debug("Detected %d candidate regions", len(boxes))
        for (x, y, w, h) in boxes:
            roi = frame[y:y + h, x:x + w]
            plate = self.ocr.read_text(roi) or ""
            plate = plate.strip()
            if not plate or len(plate) < 4:
                logging.debug("Discarded ROI: OCR='%s' len=%d", plate, len(plate))
                continue
            decision = decide(self.rules, plate)
            logging.info("Plate %s decision=%s", plate, decision)
            if self._should_emit(plate):
                self._act(frame, (x, y, w, h), plate, decision)
            if self.debug_draw:
                color = (0, 255, 0) if decision == "allow" else (0, 255, 255) if decision == "watch" else (0, 0, 255)
                cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
                cv2.putText(frame, f"{plate}:{decision}", (x, y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            return plate, decision
        return None

    def _act(self, frame, box, plate: str, decision: str):
        x, y, w, h = box
        caption = f"Plate {plate} -> {decision.upper()}"
        group = self.rules.watchlist.get(plate)
        if decision == "allow":
            self.gate.open_gate(plate)
            self.notifier.send_photo(frame, caption)
        elif decision == "deny":
            self.alarm.trigger(plate, reason="deny_list")
            self.notifier.send_photo(frame, caption)
        elif decision == "watch":
            self.notifier.send_photo(frame, caption, group=group)
        else:
            # unknown: notify optionally
            self.notifier.send_photo(frame, caption)
