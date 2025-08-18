import logging


class TelegramLogHandler(logging.Handler):
    def __init__(self, notifier, level=logging.INFO, prefix=""):
        super().__init__(level)
        self.notifier = notifier
        self.prefix = prefix

    def emit(self, record: logging.LogRecord):
        try:
            msg = self.format(record)
            if self.prefix:
                msg = f"{self.prefix} {msg}"
            # Telegram limit per message ~4096 chars; chunk if needed
            max_len = 3800
            for i in range(0, len(msg) or 1, max_len):
                chunk = msg[i:i+max_len] if msg else "(empty log message)"
                self.notifier.send_debug_text(chunk)
        except Exception:
            # Avoid raising from logging
            pass

