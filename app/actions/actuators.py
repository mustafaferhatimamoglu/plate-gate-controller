import json
import logging
from typing import Any, Dict, Optional

import requests


class GateActuator:
    def __init__(self, mode: str = "dry_run", http: Optional[Dict[str, Any]] = None):
        self.mode = mode
        self.http = http or {}

    def open_gate(self, plate: str):
        if self.mode == "http":
            url = self.http.get("open_url")
            if url:
                method = (self.http.get("method") or "POST").upper()
                headers = self.http.get("headers") or {}
                payload = self.http.get("payload_template") or {}
                payload = {**payload, "plate": plate}
                try:
                    if method == "GET":
                        requests.get(url, headers=headers, timeout=5)
                    else:
                        requests.post(url, headers=headers, json=payload, timeout=5)
                except Exception:
                    pass
        # For dry_run or as a fallback, just log via print
        logging.info(f"Gate open requested for plate=%s", plate)

    def close_gate(self, plate: str):
        if self.mode == "http":
            url = self.http.get("close_url")
            if url:
                method = (self.http.get("method") or "POST").upper()
                headers = self.http.get("headers") or {}
                payload = self.http.get("payload_template") or {}
                payload = {**payload, "plate": plate}
                try:
                    if method == "GET":
                        requests.get(url, headers=headers, timeout=5)
                    else:
                        requests.post(url, headers=headers, json=payload, timeout=5)
                except Exception:
                    pass
        logging.info(f"Gate close requested for plate=%s", plate)


class AlarmActuator:
    def __init__(self, mode: str = "dry_run", http: Optional[Dict[str, Any]] = None):
        self.mode = mode
        self.http = http or {}

    def trigger(self, plate: str, reason: str):
        if self.mode == "http":
            url = self.http.get("trigger_url")
            if url:
                method = (self.http.get("method") or "POST").upper()
                headers = self.http.get("headers") or {}
                payload = self.http.get("payload_template") or {}
                payload = {**payload, "plate": plate, "reason": reason}
                try:
                    if method == "GET":
                        requests.get(url, headers=headers, timeout=5)
                    else:
                        requests.post(url, headers=headers, json=payload, timeout=5)
                except Exception:
                    pass
        logging.warning("Alarm triggered for plate=%s reason=%s", plate, reason)
