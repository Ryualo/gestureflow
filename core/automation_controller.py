from __future__ import annotations

import queue
import threading
import time
from typing import Tuple

import pyautogui
from PySide6.QtGui import QGuiApplication

from core.config_manager import ConfigManager
from core.gesture_engine import GestureType

# Configure PyAutoGUI safety
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.02


class AutomationController:
    """
    Non-blocking macOS cursor and scroll controller with Retina coordinate mapping
    and immediate emergency stop capability.
    """

    def __init__(self, config_manager: ConfigManager) -> None:
        self._config_mgr = config_manager
        self._action_queue: queue.Queue[GestureType] = queue.Queue(maxsize=2)
        self._running = True
        self._emergency_stopped = False
        self._worker = threading.Thread(
            target=self._worker_loop, name="AutomationWorker", daemon=True
        )
        self._worker.start()

    @staticmethod
    def map_qt_to_pyautogui(x: int, y: int) -> Tuple[int, int]:
        """
        Translates Qt logical screen coordinates to PyAutoGUI logical point space,
        accounting for macOS Retina scaling and clamping within screen bounds.
        """
        screen = QGuiApplication.primaryScreen()
        py_w, py_h = pyautogui.size()

        if screen is not None:
            geo = screen.geometry()
            qt_w = max(1, geo.width())
            qt_h = max(1, geo.height())
            scale_x = py_w / float(qt_w)
            scale_y = py_h / float(qt_h)
            mapped_x = int(round((x - geo.x()) * scale_x))
            mapped_y = int(round((y - geo.y()) * scale_y))
        else:
            mapped_x, mapped_y = x, y

        # Clamp 5px inside screen corners so we don't accidentally trip PyAutoGUI FAILSAFE
        safe_x = max(5, min(py_w - 6, mapped_x))
        safe_y = max(5, min(py_h - 6, mapped_y))
        return safe_x, safe_y

    def trigger_emergency_stop(self) -> None:
        """Immediately halts automation and clears pending queued actions."""
        self._emergency_stopped = True
        self._config_mgr.update(automation_enabled=False)
        while not self._action_queue.empty():
            try:
                self._action_queue.get_nowait()
            except queue.Empty:
                break

    def clear_emergency_stop(self) -> None:
        self._emergency_stopped = False

    def dispatch(self, gesture: GestureType) -> bool:
        """Enqueues a validated gesture action if automation is enabled."""
        cfg = self._config_mgr.config
        if (
            self._emergency_stopped
            or not cfg.automation_enabled
            or gesture == GestureType.NONE
        ):
            return False

        try:
            self._action_queue.put_nowait(gesture)
            return True
        except queue.Full:
            return False

    def _worker_loop(self) -> None:
        while self._running:
            try:
                gesture = self._action_queue.get(timeout=0.1)
            except queue.Empty:
                continue

            if self._emergency_stopped or not self._config_mgr.config.automation_enabled:
                continue

            try:
                self._execute_gesture(gesture)
            except pyautogui.FailSafeException:
                # User slammed cursor into screen corner -> engage emergency stop
                self.trigger_emergency_stop()
            except Exception as exc:
                print(f"[AutomationController] Execution warning: {exc}")

    def _execute_gesture(self, gesture: GestureType) -> None:
        cfg = self._config_mgr.config

        if gesture == GestureType.ONE_THUMB_UP:
            raw_x = int(cfg.like_position.get("x", 1280))
            raw_y = int(cfg.like_position.get("y", 520))
            target_x, target_y = self.map_qt_to_pyautogui(raw_x, raw_y)
            pyautogui.moveTo(target_x, target_y, duration=0.12, tween=pyautogui.easeOutQuad)
            if not self._emergency_stopped:
                pyautogui.click(target_x, target_y)

        elif gesture == GestureType.BOTH_THUMBS_UP:
            # TikTok's repost flow is a two-step interaction: open the repost
            # confirmation UI, then click its confirmation button. Calibrate both.
            first = cfg.repost_position
            confirm = cfg.repost_confirm_position
            first_xy = self.map_qt_to_pyautogui(
                int(first.get("x", 1280)), int(first.get("y", 660))
            )
            confirm_xy = self.map_qt_to_pyautogui(
                int(confirm.get("x", 1280)), int(confirm.get("y", 700))
            )

            pyautogui.moveTo(*first_xy, duration=0.12, tween=pyautogui.easeOutQuad)
            if self._emergency_stopped:
                return
            pyautogui.click(*first_xy)

            # Give TikTok time to display its confirmation control.
            time.sleep(0.45)
            if self._emergency_stopped or not self._config_mgr.config.automation_enabled:
                return

            pyautogui.moveTo(*confirm_xy, duration=0.12, tween=pyautogui.easeOutQuad)
            if not self._emergency_stopped:
                pyautogui.click(*confirm_xy)

        elif gesture == GestureType.ONE_THUMB_DOWN:
            # One recognized pose produces one next-video action.
            if cfg.scroll_method == "down_arrow":
                pyautogui.press("down")
            else:
                pyautogui.scroll(abs(int(cfg.scroll_amount)))

        elif gesture == GestureType.ONE_INDEX_UP:
            # Index finger pointing up produces one previous-video action.
            if cfg.scroll_method == "down_arrow":
                pyautogui.press("up")
            else:
                pyautogui.scroll(-abs(int(cfg.scroll_amount)))

    def shutdown(self) -> None:
        self._running = False
        self.trigger_emergency_stop()
        if self._worker.is_alive():
            self._worker.join(timeout=1.0)

