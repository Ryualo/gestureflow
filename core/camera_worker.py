from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import List

import cv2
from PySide6.QtCore import QThread, Signal

from core.config_manager import ConfigManager
from core.gesture_engine import GestureEngine, GestureEvaluation, GestureType
from core.hand_tracker import HandLandmarks, HandTracker


@dataclass(frozen=True)
class TrackingFramePacket:
    hands: List[HandLandmarks]
    evaluation: GestureEvaluation
    fps: float
    camera_ok: bool
    status_message: str


class CameraWorker(QThread):
    """
    Background 30 FPS vision thread.
    Captures from macOS AVFoundation camera, extracts 21 landmarks, runs gesture
    recognition, and emits vector telemetry to the UI and overlay.
    """

    packet_ready = Signal(object)  # Emits TrackingFramePacket
    camera_error = Signal(str)

    def __init__(self, config_manager: ConfigManager, parent=None) -> None:
        super().__init__(parent)
        self._config_mgr = config_manager
        self._running = False

    def stop(self) -> None:
        self._running = False
        self.wait(2000)

    def _open_camera(self, index: int, width: int, height: int, fps: int):
        if sys.platform == "darwin":
            cap = cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
        else:
            cap = cv2.VideoCapture(index)

        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            cap.set(cv2.CAP_PROP_FPS, fps)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def run(self) -> None:
        self._running = True
        cfg = self._config_mgr.config

        tracker = HandTracker(
            min_detection_confidence=cfg.min_detection_confidence,
            min_tracking_confidence=cfg.min_tracking_confidence,
        )
        gesture_engine = GestureEngine(
            stabilization_frames=cfg.stabilization_frames,
            release_frames=cfg.release_frames,
            cooldown_seconds=cfg.cooldown_seconds,
        )

        cap = self._open_camera(
            cfg.camera_index, cfg.frame_width, cfg.frame_height, cfg.target_fps
        )
        if not cap or not cap.isOpened():
            msg = (
                "Camera unavailable. Verify macOS System Settings -> "
                "Privacy & Security -> Camera permission for Terminal/Python."
            )
            self.camera_error.emit(msg)
            tracker.close()
            return

        prev_time = time.monotonic()
        smoothed_fps = float(cfg.target_fps)

        try:
            while self._running:
                loop_start = time.monotonic()
                cfg = self._config_mgr.config

                # Sync dynamic settings
                tracker.update_thresholds(
                    cfg.min_detection_confidence, cfg.min_tracking_confidence
                )
                gesture_engine.stabilization_frames = cfg.stabilization_frames
                gesture_engine.release_frames = cfg.release_frames
                gesture_engine.cooldown_seconds = cfg.cooldown_seconds

                ok, frame = cap.read()
                if not ok or frame is None:
                    self.camera_error.emit("Lost camera stream from FaceTime HD Camera.")
                    time.sleep(0.1)
                    continue

                hands = tracker.process_bgr_frame(frame)
                # Explicitly delete frame reference immediately so webcam image never persists
                del frame

                evaluation = gesture_engine.update(hands)

                now = time.monotonic()
                dt = max(1e-4, now - prev_time)
                prev_time = now
                instant_fps = 1.0 / dt
                smoothed_fps = 0.85 * smoothed_fps + 0.15 * instant_fps

                hand_count = len(hands)
                if hand_count == 0:
                    status = "No Hands Detected"
                elif hand_count == 1:
                    status = f"1 Hand ({hands[0].label} - {hands[0].score:.0%})"
                else:
                    status = (
                        f"2 Hands ({hands[0].label} {hands[0].score:.0%}, "
                        f"{hands[1].label} {hands[1].score:.0%})"
                    )

                packet = TrackingFramePacket(
                    hands=hands,
                    evaluation=evaluation,
                    fps=smoothed_fps,
                    camera_ok=True,
                    status_message=status,
                )
                self.packet_ready.emit(packet)

                # Pace to the configured target without adding delay when processing is behind
                target_frame_time = 1.0 / max(10, cfg.target_fps)
                elapsed = time.monotonic() - loop_start
                sleep_duration = target_frame_time - elapsed
                if sleep_duration > 0.001:
                    time.sleep(sleep_duration)

        finally:
            cap.release()
            tracker.close()

