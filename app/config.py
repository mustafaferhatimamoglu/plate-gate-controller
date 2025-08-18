import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import yaml


@dataclass
class CameraConfig:
    rtsp_url: str
    read_timeout_sec: int = 10
    frame_resize_width: int = 1280
    skip_frames: int = 3


@dataclass
class DetectorConfig:
    cascade_path: str = ""
    min_area: int = 2000
    debug_draw: bool = False


@dataclass
class OCRConfig:
    enabled: bool = True
    tesseract_cmd: str = ""
    psm: int = 7
    whitelist: str = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


@dataclass
class RulesConfig:
    allowed_csv: str = "data/allowed.csv"
    denied_csv: str = "data/denied.csv"
    watchlist_csv: str = "data/watchlist.csv"
    debounce_sec: int = 15


@dataclass
class HTTPConfig:
    open_url: str = ""
    close_url: str = ""
    trigger_url: str = ""
    method: str = "POST"
    headers: Dict[str, str] = field(default_factory=dict)
    payload_template: Dict[str, str] = field(default_factory=dict)


@dataclass
class GateConfig:
    mode: str = "dry_run"  # dry_run | http
    http: HTTPConfig = field(default_factory=HTTPConfig)


@dataclass
class AlarmConfig:
    mode: str = "dry_run"  # dry_run | http
    http: HTTPConfig = field(default_factory=HTTPConfig)


@dataclass
class TelegramConfig:
    enabled: bool = False
    bot_token: str = ""
    chat_ids: List[int] = field(default_factory=list)
    group_routes: Dict[str, List[int]] = field(default_factory=dict)
    send_photos: bool = False
    debug_chat_ids: List[int] = field(default_factory=list)


@dataclass
class NotifyConfig:
    telegram: TelegramConfig = field(default_factory=TelegramConfig)


@dataclass
class LoggingConfig:
    level: str = "INFO"
    forward_to_telegram: bool = False


@dataclass
class AppConfig:
    camera: CameraConfig = field(default_factory=CameraConfig)
    detector: DetectorConfig = field(default_factory=DetectorConfig)
    ocr: OCRConfig = field(default_factory=OCRConfig)
    rules: RulesConfig = field(default_factory=RulesConfig)
    actions_gate: GateConfig = field(default_factory=GateConfig)
    actions_alarm: AlarmConfig = field(default_factory=AlarmConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def _dict_to_dataclass(d: dict) -> AppConfig:
    camera = CameraConfig(**d.get("camera", {}))
    detector = DetectorConfig(**d.get("detector", {}))
    ocr = OCRConfig(**d.get("ocr", {}))
    rules = RulesConfig(**d.get("rules", {}))
    actions = d.get("actions", {})
    gate = GateConfig(**{k: v for k, v in actions.get("gate", {}).items() if k != "http"})
    gate.http = HTTPConfig(**actions.get("gate", {}).get("http", {}))
    alarm = AlarmConfig(**{k: v for k, v in actions.get("alarm", {}).items() if k != "http"})
    alarm.http = HTTPConfig(**actions.get("alarm", {}).get("http", {}))
    telegram = TelegramConfig(**d.get("notify", {}).get("telegram", {}))
    notify = NotifyConfig(telegram=telegram)
    logging_cfg = LoggingConfig(**d.get("logging", {}))
    return AppConfig(
        camera=camera,
        detector=detector,
        ocr=ocr,
        rules=rules,
        actions_gate=gate,
        actions_alarm=alarm,
        notify=notify,
        logging=logging_cfg,
    )


def load_config(path: str = "config.yaml") -> AppConfig:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    # Allow simple env overrides
    rtsp_env = os.getenv("RTSP_URL")
    if rtsp_env:
        data.setdefault("camera", {})["rtsp_url"] = rtsp_env

    bot_env = os.getenv("TELEGRAM_BOT_TOKEN")
    if bot_env:
        data.setdefault("notify", {}).setdefault("telegram", {})["bot_token"] = bot_env

    return _dict_to_dataclass(data)
