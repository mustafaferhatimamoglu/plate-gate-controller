import io
import logging
from typing import Dict, List, Optional, Tuple

import requests


class TelegramNotifier:
    def __init__(self, enabled: bool, bot_token: str, chat_ids: List[int], group_routes: Optional[Dict[str, List[int]]] = None, send_photos: bool = False, debug_chat_ids: Optional[List[int]] = None):
        self.enabled = enabled
        self.bot_token = bot_token
        self.chat_ids = chat_ids or []
        self.group_routes = group_routes or {}
        self.send_photos = send_photos
        self.debug_chat_ids = debug_chat_ids or []

    def _send(self, method: str, data=None, files=None, target_chat_id: Optional[int] = None, bypass_enabled: bool = False) -> Tuple[bool, str]:
        if (not self.enabled and not bypass_enabled) or not self.bot_token:
            return False, "disabled or missing token"
        url = f"https://api.telegram.org/bot{self.bot_token}/{method}"
        try:
            if files:
                resp = requests.post(url, data=data, files=files, timeout=8)
            else:
                resp = requests.post(url, json=data, timeout=8)
            try:
                j = resp.json()
            except Exception:
                j = {"ok": False, "description": resp.text[:200]}
            ok = bool(j.get("ok")) and resp.status_code == 200
            if not ok:
                desc = j.get("description", "unknown error")
                logging.warning("Telegram API error: status=%s ok=%s desc=%s", resp.status_code, j.get("ok"), desc)
                return False, f"{resp.status_code}:{desc}"
            return True, "ok"
        except requests.RequestException as e:
            logging.warning("Telegram request failed: %s", e)
            return False, str(e)

    def _route_chats(self, group: Optional[str]) -> List[int]:
        if group and group in self.group_routes:
            return self.group_routes[group] or []
        return self.chat_ids

    def send_text(self, text: str, group: Optional[str] = None):
        for chat_id in self._route_chats(group):
            ok, info = self._send("sendMessage", data={"chat_id": chat_id, "text": text})
            if not ok:
                logging.warning("Failed to send Telegram text to %s: %s", chat_id, info)

    def send_debug_text(self, text: str):
        targets = self.debug_chat_ids if self.debug_chat_ids else self.chat_ids
        for chat_id in targets:
            self._send("sendMessage", data={"chat_id": chat_id, "text": text})

    def send_photo(self, image_bgr, caption: str, group: Optional[str] = None):
        if not self.send_photos:
            return self.send_text(caption, group=group)
        import cv2
        _, buf = cv2.imencode('.jpg', image_bgr)
        for chat_id in self._route_chats(group):
            files = {"photo": ("frame.jpg", buf.tobytes(), "image/jpeg")}
            data = {"chat_id": chat_id, "caption": caption}
            ok, info = self._send("sendPhoto", data=data, files=files)
            if not ok:
                logging.warning("Failed to send Telegram photo to %s: %s", chat_id, info)

    def send_photo_debug(self, image_bgr, caption: str):
        import cv2
        if not self.send_photos:
            return self.send_debug_text(caption)
        _, buf = cv2.imencode('.jpg', image_bgr)
        targets = self.debug_chat_ids if self.debug_chat_ids else self.chat_ids
        for chat_id in targets:
            files = {"photo": ("frame.jpg", buf.tobytes(), "image/jpeg")}
            data = {"chat_id": chat_id, "caption": caption}
            ok, info = self._send("sendPhoto", data=data, files=files)
            if not ok:
                logging.warning("Failed to send Telegram debug photo to %s: %s", chat_id, info)

    def diagnose(self, test_message: str = "Diagnostic test", include_main: bool = True, include_debug: bool = True):
        if not self.bot_token:
            logging.error("Telegram diagnose: missing bot token")
            return
        # Check token via getMe
        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/getMe"
            resp = requests.get(url, timeout=8)
            j = resp.json()
            if not j.get("ok"):
                logging.error("Telegram getMe failed: %s", j.get("description"))
            else:
                user = j.get("result", {})
                logging.info("Telegram bot ok: @%s id=%s", user.get("username"), user.get("id"))
        except Exception as e:
            logging.error("Telegram getMe error: %s", e)

        payload = {"text": f"🔧 {test_message}"}
        if include_main:
            for chat_id in self.chat_ids:
                ok, info = self._send("sendMessage", data={"chat_id": chat_id, **payload}, bypass_enabled=True)
                if ok:
                    logging.info("Diagnostic sent to chat_id=%s", chat_id)
                else:
                    logging.error("Diagnostic FAILED to chat_id=%s: %s", chat_id, info)
        if include_debug:
            for chat_id in (self.debug_chat_ids or []):
                ok, info = self._send("sendMessage", data={"chat_id": chat_id, **payload}, bypass_enabled=True)
                if ok:
                    logging.info("Diagnostic sent to debug_chat_id=%s", chat_id)
                else:
                    logging.error("Diagnostic FAILED to debug_chat_id=%s: %s", chat_id, info)
