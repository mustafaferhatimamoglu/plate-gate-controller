import re
from typing import Optional

import cv2
import numpy as np
import pytesseract


class PlateOCR:
    def __init__(self, enabled: bool = True, tesseract_cmd: str = "", psm: int = 7, whitelist: str = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"):
        self.enabled = enabled
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        self.psm = psm
        self.whitelist = whitelist

    def _preprocess(self, roi):
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        gray = cv2.bilateralFilter(gray, 11, 17, 17)
        # Adaptive threshold helps under varying light
        th = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY, 31, 15)
        th = cv2.medianBlur(th, 3)
        return th

    def _clean(self, text: str) -> str:
        text = text.upper()
        # Keep only A-Z and 0-9
        text = re.sub(r"[^A-Z0-9]", "", text)
        # Common OCR confusions
        text = text.replace("O", "0") if text.count("O") and text.count("0") == 0 else text
        text = text.replace("I", "1") if text.count("I") and text.count("1") == 0 else text
        return text

    def read_text(self, roi) -> Optional[str]:
        if not self.enabled:
            return None
        try:
            proc = self._preprocess(roi)
            config = f"--oem 3 --psm {self.psm} -c tessedit_char_whitelist={self.whitelist}"
            raw = pytesseract.image_to_string(proc, config=config)
            cleaned = self._clean(raw)
            return cleaned or None
        except Exception:
            return None

