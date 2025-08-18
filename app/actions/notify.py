import io
from typing import Dict, List, Optional

import requests


class TelegramNotifier:
    def __init__(self, enabled: bool, bot_token: str, chat_ids: List[int], group_routes: Optional[Dict[str, List[int]]] = None, send_photos: bool = False, debug_chat_ids: Optional[List[int]] = None):
        self.enabled = enabled
        self.bot_token = bot_token
        self.chat_ids = chat_ids or []
        self.group_routes = group_routes or {}
        self.send_photos = send_photos
        self.debug_chat_ids = debug_chat_ids or []

    def _send(self, method: str, data=None, files=None, target_chat_id: Optional[int] = None):
        if not self.enabled or not self.bot_token:
            return
        url = f"https://api.telegram.org/bot{self.bot_token}/{method}"
        try:
            if files:
                requests.post(url, data=data, files=files, timeout=5)
            else:
                requests.post(url, json=data, timeout=5)
        except Exception:
            pass

    def _route_chats(self, group: Optional[str]) -> List[int]:
        if group and group in self.group_routes:
            return self.group_routes[group] or []
        return self.chat_ids

    def send_text(self, text: str, group: Optional[str] = None):
        for chat_id in self._route_chats(group):
            self._send("sendMessage", data={"chat_id": chat_id, "text": text})

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
            self._send("sendPhoto", data=data, files=files)
