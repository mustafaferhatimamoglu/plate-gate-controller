from typing import List, Tuple

import cv2
import numpy as np


class PlateDetector:
    def __init__(self, cascade_path: str = "", min_area: int = 2000, debug_draw: bool = False):
        self.cascade = None
        self.min_area = min_area
        self.debug_draw = debug_draw
        if cascade_path:
            try:
                self.cascade = cv2.CascadeClassifier(cascade_path)
            except Exception:
                self.cascade = None

    def detect(self, frame) -> List[Tuple[int, int, int, int]]:
        # Returns list of bounding boxes (x, y, w, h)
        if self.cascade is not None and not self.cascade.empty():
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            plates = self.cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=3, minSize=(60, 20))
            return [(int(x), int(y), int(w), int(h)) for (x, y, w, h) in plates]

        # Fallback heuristic: find rectangular contours likely to be plates
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        edged = cv2.Canny(blur, 50, 150)
        edged = cv2.dilate(edged, None, iterations=1)
        contours, _ = cv2.findContours(edged, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < self.min_area:
                continue
            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
            x, y, w, h = cv2.boundingRect(approx)
            aspect = w / float(h + 1e-6)
            if 2.0 < aspect < 6.0 and h > 20 and w > 60:
                candidates.append((x, y, w, h))
        return candidates

