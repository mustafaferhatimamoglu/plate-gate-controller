import logging
import threading
import time
from typing import Optional

import cv2


class RTSPStream:
    def __init__(self, url: str, resize_width: int = 1280, read_timeout_sec: int = 10):
        self.url = url
        self.resize_width = resize_width
        self.read_timeout_sec = read_timeout_sec
        self.cap: Optional[cv2.VideoCapture] = None
        self.frame = None
        self.stopped = False
        self.thread: Optional[threading.Thread] = None

    def start(self):
        self.cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        self.stopped = False
        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()
        return self

    def _update(self):
        last_ok = time.time()
        while not self.stopped:
            if self.cap is None:
                break
            ok, frame = self.cap.read()
            if ok:
                last_ok = time.time()
                if self.resize_width and self.resize_width > 0:
                    h, w = frame.shape[:2]
                    if w != self.resize_width:
                        scale = self.resize_width / float(w)
                        frame = cv2.resize(frame, (self.resize_width, int(h * scale)))
                self.frame = frame
            else:
                if time.time() - last_ok > self.read_timeout_sec:
                    # Try reconnecting
                    logging.warning("RTSP timeout reached, reconnecting...")
                    try:
                        self.cap.release()
                    except Exception:
                        pass
                    time.sleep(1.0)
                    self.cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)

    def read(self):
        return self.frame

    def stop(self):
        self.stopped = True
        if self.thread is not None:
            self.thread.join(timeout=2)
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
