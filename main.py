from __future__ import annotations

import signal
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from core.automation_controller import AutomationController
from core.camera_worker import CameraWorker, TrackingFramePacket
from core.config_manager import ConfigManager
from core.gesture_engine import GestureType
from ui.control_panel import ControlPanel
from ui.skeleton_overlay import SkeletonOverlay


class GestureFlowCoordinator(QObject):
    """Coordinates signals between CameraWorker, SkeletonOverlay, ControlPanel, and AutomationController."""

    def __init__(self) -> None:
        super().__init__()
        self.config_mgr = ConfigManager(Path(__file__).resolve().parent / "config.json")
        self.automation = AutomationController(self.config_mgr)
        self.overlay = SkeletonOverlay()
        self.panel = ControlPanel(self.config_mgr)
        self.worker = CameraWorker(self.config_mgr)

        self._connect_signals()

    def _connect_signals(self) -> None:
        self.worker.packet_ready.connect(self._on_packet_ready)
        self.worker.camera_error.connect(self._on_camera_error)

        self.panel.overlay_toggled.connect(self._on_overlay_toggled)
        self.panel.automation_toggled.connect(self._on_automation_toggled)
        self.panel.emergency_stop_triggered.connect(self._on_emergency_stop)

    def start(self) -> None:
        if self.config_mgr.config.overlay_enabled:
            self.overlay.show()
        self.panel.show()
        self.worker.start()

    def _on_packet_ready(self, packet: TrackingFramePacket) -> None:
        self.panel.update_telemetry(packet)

        if self.config_mgr.config.overlay_enabled:
            self.overlay.update_state(
                hands=packet.hands,
                evaluation=packet.evaluation,
                opacity=self.config_mgr.config.overlay_opacity,
            )
        else:
            self.overlay.clear_overlay()

        if packet.evaluation.triggered_action != GestureType.NONE:
            self.automation.dispatch(packet.evaluation.triggered_action)

    def _on_camera_error(self, message: str) -> None:
        self.panel.show_camera_error(message)
        self.overlay.clear_overlay()

    def _on_overlay_toggled(self, enabled: bool) -> None:
        if enabled:
            self.overlay.show()
        else:
            self.overlay.clear_overlay()
            self.overlay.hide()

    def _on_automation_toggled(self, enabled: bool) -> None:
        if enabled:
            self.automation.clear_emergency_stop()

    def _on_emergency_stop(self) -> None:
        self.automation.trigger_emergency_stop()

    def shutdown(self) -> None:
        self.worker.stop()
        self.automation.shutdown()
        self.overlay.close()
        self.panel.close()


def main() -> int:
    # Enable High-DPI Retina scaling on macOS
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName("GestureFlow")

    coordinator = GestureFlowCoordinator()
    app.aboutToQuit.connect(coordinator.shutdown)

    # Handle Ctrl+C gracefully from Terminal
    signal.signal(signal.SIGINT, lambda *_: app.quit())

    coordinator.start()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

