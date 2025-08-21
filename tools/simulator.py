import time
import os
import sys
from typing import List, Tuple, Optional

import numpy as np

# Ensure project root is importable when running directly
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.pipeline import Pipeline
from app.rules import RuleSets


class MockDetector:
    def __init__(self, boxes: List[Tuple[int, int, int, int]]):
        self._boxes = boxes

    def detect(self, frame) -> List[Tuple[int, int, int, int]]:
        return list(self._boxes)


class MockOCR:
    def __init__(self, texts: List[str]):
        # each detection index maps to this text ("" for unreadable)
        self._texts = texts

    def read_text(self, roi) -> str:
        # Pop from list per call
        if self._texts:
            return self._texts.pop(0)
        return ""


class MockGate:
    def __init__(self):
        self.events = []

    def open_gate(self, plate: Optional[str] = None):
        self.events.append(("open_gate", plate))


class MockAlarm:
    def __init__(self):
        self.events = []

    def trigger(self, plate: Optional[str] = None, reason: str = ""):
        self.events.append(("alarm", plate, reason))


class MockNotifier:
    def __init__(self):
        self.texts = []
        self.photos = []

    def send_text(self, text: str):
        self.texts.append(text)

    def send_photo(self, frame, caption: str):
        self.photos.append(("main", caption))

    def send_photo_debug(self, frame, caption: str):
        self.photos.append(("debug", caption))


def run_demo():
    # Create a blank frame
    frame = np.zeros((720, 1280, 3), dtype=np.uint8)

    rules = RuleSets(
        allowed={"ABC123"},
        denied=set(),
        watchlist={},
        ignored={"IGN999"},
    )
    gate = MockGate()
    alarm = MockAlarm()
    notifier = MockNotifier()

    # Instantiate pipeline with placeholders; we'll swap detector/ocr per step
    pipe = Pipeline(
        detector=MockDetector([]),
        ocr=MockOCR([]),
        rules=rules,
        gate=gate,
        alarm=alarm,
        notifier=notifier,
        debounce_sec=0,
        debug_draw=False,
        notify_unreadable=True,
        unreadable_debounce_sec=0,
        unreadable_dhash_threshold=6,
        unreadable_global_cooldown_sec=0,
        direction_enabled=False,
        roi_enabled=True,
        roi_mode="rectangle",
        roi_rect=(200, 300, 600, 700),
        filter_only_in=False,
        unreadable_min_hits=1,
        hit_ttl_sec=1.0,
        center_tolerance_px=40,
        min_box_area_px=5000,
        max_box_area_px=0,
        route_unreadable="debug",
        route_readable="main",
    )

    # 1) Far car (very small bbox) -> should be ignored
    pipe.detector = MockDetector([(50, 600, 40, 15)])
    pipe.ocr = MockOCR([""])
    pipe.process_frame(frame)

    # 2) Inside ROI, readable allowed -> gate open + main photo
    pipe.detector = MockDetector([(300, 400, 160, 50)])
    pipe.ocr = MockOCR(["ABC123"])
    pipe.process_frame(frame)

    # 3) Outside ROI, unreadable -> ignored (no notify)
    pipe.detector = MockDetector([(900, 100, 150, 50)])
    pipe.ocr = MockOCR([""])
    pipe.process_frame(frame)

    # 4) Inside ROI, readable but ignored plate -> no notify/actuate
    pipe.detector = MockDetector([(320, 420, 160, 50)])
    pipe.ocr = MockOCR(["IGN999"])
    pipe.process_frame(frame)

    print("Notifications:", notifier.photos)
    print("Gate events:", gate.events)
    print("Alarm events:", alarm.events)


if __name__ == "__main__":
    run_demo()
