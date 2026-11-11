from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict


@dataclass
class Point2D:
    x: int = 1280
    y: int = 520


@dataclass
class AppConfig:
    camera_index: int = 0
    target_fps: int = 30
    frame_width: int = 480
    frame_height: int = 360
    min_detection_confidence: float = 0.65
    min_tracking_confidence: float = 0.65
    stabilization_frames: int = 8
    release_frames: int = 4
    cooldown_seconds: float = 1.25
    like_position: Dict[str, int] = field(
        default_factory=lambda: {"x": 1280, "y": 520}
    )
    repost_position: Dict[str, int] = field(
        default_factory=lambda: {"x": 1280, "y": 660}
    )
    repost_confirm_position: Dict[str, int] = field(
        default_factory=lambda: {"x": 1280, "y": 700}
    )
    scroll_method: str = "down_arrow"  # Options: "down_arrow" or "mouse_scroll"
    scroll_amount: int = -6
    overlay_enabled: bool = True
    automation_enabled: bool = False
    overlay_opacity: float = 0.9


class ConfigManager:
    """Thread-safe JSON configuration loader and saver."""

    def __init__(self, config_path: str | Path = "config.json") -> None:
        self._path = Path(config_path)
        self._lock = threading.RLock()
        self.config = AppConfig()
        self.load()

    def load(self) -> AppConfig:
        with self._lock:
            if not self._path.exists():
                self.save()
                return self.config
            try:
                raw = json.loads(self._path.read_text(encoding="utf-8"))
                valid_keys = asdict(self.config).keys()
                filtered = {k: v for k, v in raw.items() if k in valid_keys}
                self.config = AppConfig(**filtered)
            except (json.JSONDecodeError, OSError, TypeError):
                # Fall back to safe defaults and overwrite corrupted file
                self.config = AppConfig()
                self.save()
            return self.config

    def save(self) -> None:
        with self._lock:
            self._path.write_text(
                json.dumps(asdict(self.config), indent=2),
                encoding="utf-8",
            )

    def update(self, **kwargs) -> AppConfig:
        with self._lock:
            for key, value in kwargs.items():
                if hasattr(self.config, key):
                    setattr(self.config, key, value)
            self.save()
            return self.config

