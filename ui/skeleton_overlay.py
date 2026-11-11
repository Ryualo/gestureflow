from __future__ import annotations

from typing import List

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QWidget

from core.gesture_engine import GestureEvaluation, GestureType
from core.hand_tracker import HandLandmarks, HandTracker


class SkeletonOverlay(QWidget):
    """
    Full-screen transparent, always-on-top, click-through overlay that renders
    MediaPipe 21-landmark skeletons without ever displaying the webcam video feed.
    """

    FINGERTIP_INDICES = {4, 8, 12, 16, 20}

    def __init__(self) -> None:
        super().__init__(None)
        self._hands: List[HandLandmarks] = []
        self._evaluation: GestureEvaluation | None = None
        self._overlay_opacity: float = 0.9

        self._configure_window()
        self._topmost_timer = QTimer(self)
        self._topmost_timer.setInterval(1500)
        self._topmost_timer.timeout.connect(self._apply_macos_topmost)
        self._topmost_timer.start()

    def _configure_window(self) -> None:
        flags = (
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.Tool
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setWindowFlags(flags)
        self.setWindowTitle("GestureFlowTrackingOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)

        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            self.setGeometry(screen.geometry())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Qt's always-on-top hint alone can be demoted by macOS Spaces/full-screen
        # transitions. Apply the native NSWindow level after the window is visible.
        QTimer.singleShot(250, self._apply_macos_topmost)

    def _apply_macos_topmost(self) -> None:
        if not self.isVisible():
            return
        try:
            import AppKit

            app = AppKit.NSApplication.sharedApplication()
            for native_window in app.windows():
                if native_window.title() == "GestureFlowTrackingOverlay":
                    native_window.setLevel_(AppKit.NSStatusWindowLevel)
                    behavior = (
                        AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
                        | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
                        | AppKit.NSWindowCollectionBehaviorStationary
                        | AppKit.NSWindowCollectionBehaviorIgnoresCycle
                    )
                    native_window.setCollectionBehavior_(behavior)
                    native_window.setHidesOnDeactivate_(False)
                    native_window.setIgnoresMouseEvents_(True)
                    break
        except Exception as exc:
            # Keep the Qt always-on-top flags as a fallback on unsupported setups.
            print(f"[GestureFlow] Native macOS overlay pinning unavailable: {exc}")

    def update_state(
        self,
        hands: List[HandLandmarks],
        evaluation: GestureEvaluation,
        opacity: float = 0.9,
    ) -> None:
        self._hands = hands
        self._evaluation = evaluation
        self._overlay_opacity = max(0.2, min(1.0, opacity))
        self.update()

    def clear_overlay(self) -> None:
        self._hands = []
        self._evaluation = None
        self.update()

    def paintEvent(self, event) -> None:
        if not self._hands:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setOpacity(self._overlay_opacity)

        w = float(self.width())
        h = float(self.height())

        # Select bone color based on active gesture state
        bone_color = QColor(0, 230, 180, 210)  # Default Neon Mint
        if self._evaluation is not None:
            if self._evaluation.raw_gesture == GestureType.BOTH_THUMBS_UP:
                bone_color = QColor(255, 195, 0, 235)  # Gold for Repost
            elif self._evaluation.raw_gesture == GestureType.ONE_THUMB_UP:
                bone_color = QColor(255, 65, 130, 235)  # Rose Pink for Like
            elif self._evaluation.raw_gesture == GestureType.ONE_THUMB_DOWN:
                bone_color = QColor(70, 175, 255, 235)  # Electric Blue for Next Video
            elif self._evaluation.raw_gesture == GestureType.ONE_INDEX_UP:
                bone_color = QColor(160, 120, 255, 235)  # Violet for Previous Video

        for hand in self._hands:
            pts = [
                QPointF(float(lm[0]) * w, float(lm[1]) * h)
                for lm in hand.landmarks
            ]

            # 1. Outer glow along skeleton bones
            glow_pen = QPen(
                QColor(bone_color.red(), bone_color.green(), bone_color.blue(), 75),
                5.0,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
            painter.setPen(glow_pen)
            for start_idx, end_idx in HandTracker.CONNECTIONS:
                painter.drawLine(pts[start_idx], pts[end_idx])

            # 2. Crisp inner skeleton connections
            core_pen = QPen(
                bone_color,
                3.0,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
            )
            painter.setPen(core_pen)
            for start_idx, end_idx in HandTracker.CONNECTIONS:
                painter.drawLine(pts[start_idx], pts[end_idx])

            # 3. Draw 21 landmark nodes
            for idx, pt in enumerate(pts):
                if idx == 4:
                    # Highlight Thumb Tip
                    painter.setPen(QPen(QColor(255, 255, 255), 2.0))
                    painter.setBrush(QColor(255, 90, 90))
                    painter.drawEllipse(pt, 6.5, 6.5)
                elif idx in self.FINGERTIP_INDICES:
                    painter.setPen(QPen(QColor(255, 255, 255), 1.5))
                    painter.setBrush(QColor(255, 255, 255))
                    painter.drawEllipse(pt, 5.0, 5.0)
                elif idx == 0:
                    # Wrist anchor
                    painter.setPen(QPen(bone_color, 2.0))
                    painter.setBrush(QColor(25, 30, 40))
                    painter.drawEllipse(pt, 7.0, 7.0)
                else:
                    painter.setPen(QPen(QColor(20, 25, 35), 1.2))
                    painter.setBrush(bone_color)
                    painter.drawEllipse(pt, 3.5, 3.5)

            # 4. Draw subtle hand label & stabilization ring near wrist
            wrist_pt = pts[0]
            painter.setFont(QFont("SF Pro Display", 11, QFont.Weight.Bold))
            painter.setPen(QColor(255, 255, 255, 220))
            label_text = f"{hand.label} ({hand.score:.0%})"
            painter.drawText(
                QPointF(wrist_pt.x() - 35.0, wrist_pt.y() + 26.0),
                label_text,
            )

        painter.end()

