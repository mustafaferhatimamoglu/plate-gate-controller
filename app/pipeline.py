import time
import logging
import hashlib
from collections import deque
from typing import Dict, Optional, Tuple

import cv2
import numpy as np

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
        notify_unreadable: bool = False,
        unreadable_debounce_sec: int = 10,
        unreadable_dhash_threshold: int = 6,
        unreadable_global_cooldown_sec: int = 8,
        suppress_actuators: bool = False,
        direction_enabled: bool = True,
        direction_axis: str = "y",
        direction_invert: bool = False,
        direction_min_disp: int = 20,
        direction_gate_line: Optional[float] = None,
        # ROI
        roi_enabled: bool = False,
        roi_mode: str = "rectangle",
        roi_rect: Optional[Tuple[float, float, float, float]] = None,
        roi_polygon: Optional[list] = None,
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
        self.notify_unreadable = notify_unreadable
        self.unreadable_debounce_sec = unreadable_debounce_sec
        self.last_unreadable_seen: Dict[str, float] = {}
        self.unreadable_dhash_threshold = unreadable_dhash_threshold
        self.unreadable_global_cooldown_sec = unreadable_global_cooldown_sec
        self._unreadable_memory: Dict[int, float] = {}
        self._last_unreadable_emit_ts: float = 0.0
        # Direction
        self.direction_enabled = direction_enabled
        self.direction_axis = direction_axis.lower() if direction_axis in ("x", "y") else "y"
        self.direction_invert = direction_invert
        self.direction_min_disp = max(0, int(direction_min_disp))
        self.direction_gate_line = direction_gate_line
        self._last_center: Optional[Tuple[float, float]] = None
        self._last_side: Optional[int] = None
        self.suppress_actuators = suppress_actuators
        # ROI
        self.roi_enabled = roi_enabled
        self.roi_mode = roi_mode
        self.roi_rect = roi_rect if roi_rect else (0, 0, 0, 0)
        self.roi_polygon = roi_polygon if roi_polygon else []
        self._roi_mask = None
        self._roi_mask_size = None
        self._roi_dirty = True
        self._rect_anchor = None  # for calibration rectangle clicks

    def _should_emit(self, plate: str) -> bool:
        now = time.time()
        last = self.last_seen.get(plate)
        if last is None or (now - last) > self.debounce_sec:
            self.last_seen[plate] = now
            return True
        return False

    def _roi_hash(self, roi) -> str:
        try:
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        except Exception:
            gray = roi
        small = cv2.resize(gray, (16, 16), interpolation=cv2.INTER_AREA)
        # normalize to reduce lighting variance
        small = cv2.equalizeHist(small)
        return hashlib.sha1(small.tobytes()).hexdigest()

    def _should_emit_unreadable(self, roi_hash: str) -> bool:
        now = time.time()
        last = self.last_unreadable_seen.get(roi_hash)
        if last is None or (now - last) > self.unreadable_debounce_sec:
            self.last_unreadable_seen[roi_hash] = now
            # Optional pruning to keep dict bounded
            if len(self.last_unreadable_seen) > 500:
                # drop oldest ~10%
                for h, _ in sorted(self.last_unreadable_seen.items(), key=lambda x: x[1])[:50]:
                    self.last_unreadable_seen.pop(h, None)
            return True
        return False

    # Robust perceptual hash (dHash) for unreadable ROI, tolerant to small changes
    def _roi_dhash(self, roi) -> int:
        try:
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        except Exception:
            gray = roi
        img = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
        diff = img[:, 1:] > img[:, :-1]
        bits = 0
        for i, v in enumerate(diff.flatten()):
            bits |= (1 if v else 0) << i
        return bits

    def _hamming(self, a: int, b: int) -> int:
        return int(bin(a ^ b).count("1"))

    def _unreadable_duplicate(self, dhash: Optional[int], now: float) -> bool:
        # Global cooldown first
        if now - self._last_unreadable_emit_ts < self.unreadable_global_cooldown_sec:
            return True
        if dhash is None:
            return False
        # Check against recent memory using Hamming distance
        threshold = max(0, int(self.unreadable_dhash_threshold))
        to_delete = []
        window = max(self.unreadable_debounce_sec, self.unreadable_global_cooldown_sec) * 3
        dup = False
        for h, ts in self._unreadable_memory.items():
            if now - ts > window:
                to_delete.append(h)
                continue
            if self._hamming(dhash, h) <= threshold:
                dup = True
                break
        for h in to_delete:
            self._unreadable_memory.pop(h, None)
        return dup

    def _record_unreadable(self, dhash: Optional[int], now: float):
        self._last_unreadable_emit_ts = now
        if dhash is not None:
            self._unreadable_memory[dhash] = now

    def process_frame(self, frame) -> Optional[Tuple[str, str]]:
        work = self._apply_roi_mask(frame) if self.roi_enabled else frame
        boxes = self.detector.detect(work)
        logging.debug("Detected %d candidate regions", len(boxes))
        unreadable_box = None
        unreadable_hash = None
        unreadable_dhash = None
        for (x, y, w, h) in boxes:
            roi = frame[y:y + h, x:x + w]
            plate = self.ocr.read_text(roi) or ""
            plate = plate.strip()
            current_center = (x + w / 2.0, y + h / 2.0)
            direction = self._estimate_direction(current_center)
            if self.roi_enabled and not self._point_in_roi(current_center):
                # outside ROI; skip
                continue
            if not plate or len(plate) < 4:
                logging.debug("Discarded ROI: OCR='%s' len=%d", plate, len(plate))
                if unreadable_box is None:
                    unreadable_box = (x, y, w, h)
                    try:
                        unreadable_hash = self._roi_hash(roi)
                        unreadable_dhash = self._roi_dhash(roi)
                    except Exception:
                        unreadable_hash = None
                        unreadable_dhash = None
                # update direction state for next comparisons
                self._update_direction_state(current_center)
                continue
            decision = decide(self.rules, plate)
            logging.info("Plate %s decision=%s", plate, decision)
            if self._should_emit(plate):
                self._act(frame, (x, y, w, h), plate, decision, direction)
            if self.debug_draw:
                color = (0, 255, 0) if decision == "allow" else (0, 255, 255) if decision == "watch" else (0, 0, 255)
                cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
                label = f"{plate}:{decision}"
                if direction:
                    label += f"({direction})"
                cv2.putText(frame, label, (x, y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
            self._update_direction_state(current_center)
            return plate, decision
        # If we had candidates but couldn't read a plate, optionally notify with dedup
        if unreadable_box and self.notify_unreadable:
            # use center of unreadable box for direction
            ux, uy, uw, uh = unreadable_box
            current_center = (ux + uw / 2.0, uy + uh / 2.0)
            if self.roi_enabled and not self._point_in_roi(current_center):
                return None
            direction = self._estimate_direction(current_center)
            now = time.time()
            if not self._unreadable_duplicate(unreadable_dhash, now):
                if unreadable_hash is None or self._should_emit_unreadable(unreadable_hash):
                    x, y, w, h = unreadable_box
                    dir_text = f" ({direction})" if direction else ""
                    caption = f"Vehicle detected{dir_text}: plate unreadable"
                    if self.debug_draw:
                        cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 0, 0), 2)
                        cv2.putText(frame, f"unreadable{dir_text}", (x, y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
                    self.notifier.send_photo(frame, caption)
                    self._record_unreadable(unreadable_dhash, now)
                    logging.info("Unreadable plate candidate notified")
            self._update_direction_state(current_center)
            return None
        return None

    def _act(self, frame, box, plate: str, decision: str, direction: Optional[str]):
        x, y, w, h = box
        dir_text = f" ({direction})" if direction else ""
        caption = f"Plate {plate}{dir_text} -> {decision.upper()}"
        group = self.rules.watchlist.get(plate)
        # Send notification always
        if decision == "watch":
            self.notifier.send_photo(frame, caption, group=group)
        else:
            self.notifier.send_photo(frame, caption)
        # Suppress actuators if requested (e.g., during calibration)
        if self.suppress_actuators:
            return
        if decision == "allow":
            self.gate.open_gate(plate)
        elif decision == "deny":
            self.alarm.trigger(plate, reason="deny_list")

    def draw_calibration_overlay(self, frame):
        h, w = frame.shape[:2]
        # Draw ROI overlay
        if self.roi_enabled:
            overlay = frame.copy()
            if self.roi_mode == 'rectangle':
                x1, y1, x2, y2 = map(int, self.roi_rect)
                x1, y1 = max(0, min(w - 1, x1)), max(0, min(h - 1, y1))
                x2, y2 = max(0, min(w - 1, x2)), max(0, min(h - 1, y2))
                x1, x2 = sorted([x1, x2])
                y1, y2 = sorted([y1, y2])
                cv2.rectangle(overlay, (x1, y1), (x2, y2), (0, 255, 0), -1)
            else:
                pts = np.array(self.roi_polygon, dtype=np.int32) if self.roi_polygon else None
                if pts is not None and len(pts) >= 3:
                    cv2.fillPoly(overlay, [pts], (0, 255, 0))
            # Blend overlay for semi-transparency
            frame[:] = cv2.addWeighted(overlay, 0.2, frame, 0.8, 0)
            # Draw outline
            if self.roi_mode == 'rectangle':
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 200, 0), 2)
            else:
                if pts is not None and len(pts) >= 2:
                    cv2.polylines(frame, [pts], isClosed=True, color=(0, 200, 0), thickness=2)
        # Draw gate line
        if self.direction_gate_line is not None:
            if self.direction_axis == "y":
                y = int(self.direction_gate_line)
                y = max(0, min(h - 1, y))
                cv2.line(frame, (0, y), (w - 1, y), (0, 165, 255), 3)
            else:
                x = int(self.direction_gate_line)
                x = max(0, min(w - 1, x))
                cv2.line(frame, (x, 0), (x, h - 1), (0, 165, 255), 3)
        # Draw last center
        if self._last_center is not None:
            cx, cy = int(self._last_center[0]), int(self._last_center[1])
            cv2.circle(frame, (cx, cy), 5, (0, 255, 255), -1)
        # OSD text
        info = [
            f"axis={self.direction_axis}",
            f"invert={'on' if self.direction_invert else 'off'}",
            f"min_disp={self.direction_min_disp}",
            f"gate_line={self.direction_gate_line if self.direction_gate_line is not None else 'None'}",
            f"ROI={'on' if self.roi_enabled else 'off'} mode={self.roi_mode}",
            "Mouse: click to set gate_line or ROI. Keys: [x]=axis [i]=invert [+/-]=disp [t]=roi on/off [p]=roi mode [n]=roi clear [w]=save [q]=quit",
        ]
        y0 = 20
        for s in info:
            cv2.putText(frame, s, (10, y0), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            y0 += 22

    def _estimate_direction(self, current_center: Tuple[float, float]) -> Optional[str]:
        if not self.direction_enabled:
            return None
        last = self._last_center
        if last is None:
            return None
        ax = self.direction_axis
        delta = (current_center[0] - last[0]) if ax == "x" else (current_center[1] - last[1])
        if abs(delta) < self.direction_min_disp:
            # not enough movement
            return None
        # If gate_line is provided, prefer side change semantics
        if self.direction_gate_line is not None and self._last_side is not None:
            cur_side = 0 if ((current_center[0] if ax == "x" else current_center[1]) < self.direction_gate_line) else 1
            if cur_side != self._last_side:
                # Determine direction based on crossing direction
                dir_val = "in" if (delta > 0) else "out"
                if self.direction_invert:
                    dir_val = "out" if dir_val == "in" else "in"
                return dir_val
        # Fallback to velocity sign
        dir_val = "in" if (delta > 0) else "out"
        if self.direction_invert:
            dir_val = "out" if dir_val == "in" else "in"
        return dir_val

    def _update_direction_state(self, current_center: Tuple[float, float]):
        self._last_center = current_center
        if self.direction_gate_line is not None:
            ax = self.direction_axis
            val = current_center[0] if ax == "x" else current_center[1]
            self._last_side = 0 if val < self.direction_gate_line else 1

    def _apply_roi_mask(self, frame):
        h, w = frame.shape[:2]
        if self._roi_mask is None or self._roi_mask_size != (w, h) or self._roi_dirty:
            mask = np.zeros((h, w), dtype=np.uint8)
            if self.roi_mode == 'rectangle':
                x1, y1, x2, y2 = map(int, self.roi_rect)
                x1, y1 = max(0, min(w - 1, x1)), max(0, min(h - 1, y1))
                x2, y2 = max(0, min(w - 1, x2)), max(0, min(h - 1, y2))
                x1, x2 = sorted([x1, x2])
                y1, y2 = sorted([y1, y2])
                cv2.rectangle(mask, (x1, y1), (x2, y2), 255, -1)
            else:
                pts = np.array(self.roi_polygon, dtype=np.int32) if self.roi_polygon else None
                if pts is not None and len(pts) >= 3:
                    cv2.fillPoly(mask, [pts], 255)
            self._roi_mask = mask
            self._roi_mask_size = (w, h)
            self._roi_dirty = False
        # apply
        colored = cv2.bitwise_and(frame, frame, mask=self._roi_mask)
        return colored

    def _point_in_roi(self, center: Tuple[float, float]) -> bool:
        if not self.roi_enabled:
            return True
        x, y = int(center[0]), int(center[1])
        if self.roi_mode == 'rectangle':
            x1, y1, x2, y2 = self.roi_rect
            x1, x2 = sorted([x1, x2])
            y1, y2 = sorted([y1, y2])
            return x1 <= x <= x2 and y1 <= y <= y2
        else:
            pts = np.array(self.roi_polygon, dtype=np.int32) if self.roi_polygon else None
            if pts is None or len(pts) < 3:
                return True
            return cv2.pointPolygonTest(pts, (x, y), False) >= 0
