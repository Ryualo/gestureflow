from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QCursor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.camera_worker import TrackingFramePacket
from core.config_manager import ConfigManager
from core.gesture_engine import GestureType


class ControlPanel(QWidget):
    """Floating modern macOS control panel for GestureFlow."""

    automation_toggled = Signal(bool)
    overlay_toggled = Signal(bool)
    emergency_stop_triggered = Signal()

    def __init__(self, config_manager: ConfigManager) -> None:
        super().__init__(None)
        self._config_mgr = config_manager
        self._calibrating_target: str | None = None
        self._calibration_countdown: int = 0

        self._calib_timer = QTimer(self)
        self._calib_timer.setInterval(1000)
        self._calib_timer.timeout.connect(self._on_calibration_tick)

        self._setup_window()
        self._build_ui()
        self._apply_stylesheet()
        self._sync_ui_from_config()

        # Escape key acts as immediate emergency stop when window has focus
        self._esc_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._esc_shortcut.activated.connect(self._handle_emergency_stop)

    def _setup_window(self) -> None:
        self.setWindowTitle("GestureFlow — TikTok Hand Controller")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.CustomizeWindowHint
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowCloseButtonHint
            | Qt.WindowType.WindowMinimizeButtonHint
        )
        self.setFixedWidth(380)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Header
        header_layout = QHBoxLayout()
        title = QLabel("GestureFlow")
        title.setObjectName("HeaderTitle")
        badge = QLabel("macOS Live Control")
        badge.setObjectName("BadgeLabel")
        header_layout.addWidget(title)
        header_layout.addStretch()
        header_layout.addWidget(badge)
        root.addLayout(header_layout)

        # Live Telemetry Card
        telemetry_box = QGroupBox("Live Telemetry")
        t_grid = QGridLayout(telemetry_box)
        t_grid.setSpacing(8)

        self.lbl_camera_status = QLabel("Initializing...")
        self.lbl_tracking_status = QLabel("No Hands")
        self.lbl_current_gesture = QLabel(GestureType.NONE.value)
        self.lbl_current_gesture.setObjectName("GestureValue")
        self.lbl_fps = QLabel("0.0 FPS")
        self.lbl_last_action = QLabel("None")

        self.stability_bar = QProgressBar()
        self.stability_bar.setRange(0, 100)
        self.stability_bar.setValue(0)
        self.stability_bar.setTextVisible(False)
        self.stability_bar.setFixedHeight(8)

        t_grid.addWidget(QLabel("Camera:"), 0, 0)
        t_grid.addWidget(self.lbl_camera_status, 0, 1)
        t_grid.addWidget(QLabel("Tracking:"), 1, 0)
        t_grid.addWidget(self.lbl_tracking_status, 1, 1)
        t_grid.addWidget(QLabel("FPS:"), 2, 0)
        t_grid.addWidget(self.lbl_fps, 2, 1)
        t_grid.addWidget(QLabel("Gesture:"), 3, 0)
        t_grid.addWidget(self.lbl_current_gesture, 3, 1)
        t_grid.addWidget(QLabel("Hold Lock:"), 4, 0)
        t_grid.addWidget(self.stability_bar, 4, 1)
        t_grid.addWidget(QLabel("Last Trigger:"), 5, 0)
        t_grid.addWidget(self.lbl_last_action, 5, 1)
        root.addWidget(telemetry_box)

        # Primary Controls
        controls_box = QGroupBox("Master Controls")
        c_layout = QVBoxLayout(controls_box)

        toggle_row = QHBoxLayout()
        self.btn_toggle_automation = QPushButton("Enable Gesture Control")
        self.btn_toggle_automation.setCheckable(True)
        self.btn_toggle_automation.clicked.connect(self._on_automation_clicked)

        self.btn_toggle_overlay = QPushButton("Hide Skeleton Overlay")
        self.btn_toggle_overlay.setCheckable(True)
        self.btn_toggle_overlay.clicked.connect(self._on_overlay_clicked)

        toggle_row.addWidget(self.btn_toggle_automation)
        toggle_row.addWidget(self.btn_toggle_overlay)
        c_layout.addLayout(toggle_row)

        self.btn_emergency = QPushButton("EMERGENCY STOP (ESC)")
        self.btn_emergency.setObjectName("EmergencyButton")
        self.btn_emergency.clicked.connect(self._handle_emergency_stop)
        c_layout.addWidget(self.btn_emergency)
        root.addWidget(controls_box)

        # Cursor Calibration
        calib_box = QGroupBox("TikTok Cursor Calibration (3s Hover Capture)")
        cal_grid = QGridLayout(calib_box)

        self.lbl_like_coords = QLabel("(1280, 520)")
        self.btn_set_like = QPushButton("Set Like Position")
        self.btn_set_like.clicked.connect(lambda: self._start_calibration("like"))

        self.lbl_repost_coords = QLabel("(1280, 660)")
        self.btn_set_repost = QPushButton("Set Repost Position")
        self.btn_set_repost.clicked.connect(lambda: self._start_calibration("repost"))

        self.lbl_repost_confirm_coords = QLabel("(1280, 700)")
        self.btn_set_repost_confirm = QPushButton("Set Confirm Position")
        self.btn_set_repost_confirm.clicked.connect(
            lambda: self._start_calibration("repost_confirm")
        )

        cal_grid.addWidget(QLabel("Like Button:"), 0, 0)
        cal_grid.addWidget(self.lbl_like_coords, 0, 1)
        cal_grid.addWidget(self.btn_set_like, 0, 2)

        cal_grid.addWidget(QLabel("Repost Button:"), 1, 0)
        cal_grid.addWidget(self.lbl_repost_coords, 1, 1)
        cal_grid.addWidget(self.btn_set_repost, 1, 2)

        cal_grid.addWidget(QLabel("Confirm Repost:"), 2, 0)
        cal_grid.addWidget(self.lbl_repost_confirm_coords, 2, 1)
        cal_grid.addWidget(self.btn_set_repost_confirm, 2, 2)
        root.addWidget(calib_box)

        # Detection & Scroll Settings
        settings_box = QGroupBox("Sensitivity & Action Settings")
        s_grid = QGridLayout(settings_box)

        self.spin_confidence = QDoubleSpinBox()
        self.spin_confidence.setRange(0.50, 0.95)
        self.spin_confidence.setSingleStep(0.05)
        self.spin_confidence.valueChanged.connect(self._on_settings_changed)

        self.spin_stab_frames = QSpinBox()
        self.spin_stab_frames.setRange(3, 25)
        self.spin_stab_frames.valueChanged.connect(self._on_settings_changed)

        self.spin_cooldown = QDoubleSpinBox()
        self.spin_cooldown.setRange(0.3, 5.0)
        self.spin_cooldown.setSingleStep(0.25)
        self.spin_cooldown.setSuffix(" s")
        self.spin_cooldown.valueChanged.connect(self._on_settings_changed)

        self.combo_scroll = QComboBox()
        self.combo_scroll.addItems(["down_arrow", "mouse_scroll"])
        self.combo_scroll.currentTextChanged.connect(self._on_settings_changed)

        s_grid.addWidget(QLabel("Min Confidence:"), 0, 0)
        s_grid.addWidget(self.spin_confidence, 0, 1)
        s_grid.addWidget(QLabel("Hold Frames:"), 1, 0)
        s_grid.addWidget(self.spin_stab_frames, 1, 1)
        s_grid.addWidget(QLabel("Action Cooldown:"), 2, 0)
        s_grid.addWidget(self.spin_cooldown, 2, 1)
        s_grid.addWidget(QLabel("Next Video Mode:"), 3, 0)
        s_grid.addWidget(self.combo_scroll, 3, 1)
        root.addWidget(settings_box)

        # Gesture Legend Footer
        footer = QFrame()
        f_layout = QVBoxLayout(footer)
        f_layout.setContentsMargins(4, 2, 4, 2)
        legend = QLabel(
            "👍 Like  |  👍👍 Repost  |  👎 Next video  |  ☝️ Previous video"
        )
        legend.setObjectName("LegendLabel")
        legend.setAlignment(Qt.AlignmentFlag.AlignCenter)
        f_layout.addWidget(legend)
        root.addWidget(footer)

    def _apply_stylesheet(self) -> None:
        self.setStyleSheet(
            """
            QWidget {
                background-color: #12151E;
                color: #E8ECF2;
                font-family: "SF Pro Display", -apple-system, sans-serif;
                font-size: 12px;
            }
            #HeaderTitle {
                font-size: 18px;
                font-weight: 700;
                color: #00E6B4;
            }
            #BadgeLabel {
                background-color: #1E2638;
                color: #8AB4F8;
                padding: 3px 8px;
                border-radius: 6px;
                font-size: 11px;
                font-weight: 600;
            }
            QGroupBox {
                border: 1px solid #262D40;
                border-radius: 8px;
                margin-top: 8px;
                padding-top: 10px;
                font-weight: 600;
                color: #9AA5B8;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            #GestureValue {
                font-weight: 700;
                color: #00E6B4;
            }
            QPushButton {
                background-color: #232A3B;
                border: 1px solid #343F57;
                border-radius: 6px;
                padding: 6px 10px;
                font-weight: 600;
            }
            QPushButton:hover {
                background-color: #2D364C;
            }
            QPushButton:checked {
                background-color: #00A884;
                border-color: #00E6B4;
                color: #0B0E14;
            }
            #EmergencyButton {
                background-color: #B81D33;
                border: 1px solid #FF4D64;
                color: #FFFFFF;
                font-weight: 700;
                padding: 8px;
            }
            #EmergencyButton:hover {
                background-color: #D9233E;
            }
            QProgressBar {
                background-color: #1E2433;
                border-radius: 4px;
            }
            QProgressBar::chunk {
                background-color: #00E6B4;
                border-radius: 4px;
            }
            QSpinBox, QDoubleSpinBox, QComboBox {
                background-color: #1B202E;
                border: 1px solid #323B52;
                border-radius: 5px;
                padding: 3px 6px;
            }
            #LegendLabel {
                color: #7E8A9F;
                font-size: 11px;
            }
            """
        )

    def _sync_ui_from_config(self) -> None:
        cfg = self._config_mgr.config
        self.blockSignals(True)

        self.btn_toggle_automation.setChecked(cfg.automation_enabled)
        self._update_automation_button_text(cfg.automation_enabled)

        self.btn_toggle_overlay.setChecked(cfg.overlay_enabled)
        self.btn_toggle_overlay.setText(
            "Overlay: ON" if cfg.overlay_enabled else "Overlay: OFF"
        )

        lx, ly = cfg.like_position.get("x", 1280), cfg.like_position.get("y", 520)
        rx, ry = cfg.repost_position.get("x", 1280), cfg.repost_position.get("y", 660)
        cx, cy = cfg.repost_confirm_position.get("x", 1280), cfg.repost_confirm_position.get("y", 700)
        self.lbl_like_coords.setText(f"({lx}, {ly})")
        self.lbl_repost_coords.setText(f"({rx}, {ry})")
        self.lbl_repost_confirm_coords.setText(f"({cx}, {cy})")

        self.spin_confidence.setValue(cfg.min_tracking_confidence)
        self.spin_stab_frames.setValue(cfg.stabilization_frames)
        self.spin_cooldown.setValue(cfg.cooldown_seconds)
        self.combo_scroll.setCurrentText(cfg.scroll_method)

        self.blockSignals(False)

    def _update_automation_button_text(self, enabled: bool) -> None:
        self.btn_toggle_automation.setText(
            "Gesture Control: ACTIVE" if enabled else "Enable Gesture Control"
        )

    def _on_automation_clicked(self, checked: bool) -> None:
        self._config_mgr.update(automation_enabled=checked)
        self._update_automation_button_text(checked)
        self.automation_toggled.emit(checked)

    def _on_overlay_clicked(self, checked: bool) -> None:
        self._config_mgr.update(overlay_enabled=checked)
        self.btn_toggle_overlay.setText(
            "Overlay: ON" if checked else "Overlay: OFF"
        )
        self.overlay_toggled.emit(checked)

    def _handle_emergency_stop(self) -> None:
        self.btn_toggle_automation.setChecked(False)
        self._update_automation_button_text(False)
        self.lbl_last_action.setText("EMERGENCY STOPPED")
        self.emergency_stop_triggered.emit()

    def _calibration_controls(self):
        return {
            "like": (self.btn_set_like, self.lbl_like_coords, "like_position", "Set Like Position"),
            "repost": (self.btn_set_repost, self.lbl_repost_coords, "repost_position", "Set Repost Position"),
            "repost_confirm": (
                self.btn_set_repost_confirm, self.lbl_repost_confirm_coords,
                "repost_confirm_position", "Set Confirm Position"
            ),
        }

    def _start_calibration(self, target: str) -> None:
        self._calibrating_target = target
        self._calibration_countdown = 3
        btn = self._calibration_controls()[target][0]
        btn.setText(f"Hover now... ({self._calibration_countdown}s)")
        btn.setEnabled(False)
        self._calib_timer.start()

    def _on_calibration_tick(self) -> None:
        self._calibration_countdown -= 1
        btn, label, config_key, default_text = self._calibration_controls()[self._calibrating_target]

        if self._calibration_countdown > 0:
            btn.setText(f"Hover now... ({self._calibration_countdown}s)")
            return

        self._calib_timer.stop()
        pos = QCursor.pos()
        coords = {"x": int(pos.x()), "y": int(pos.y())}

        self._config_mgr.update(**{config_key: coords})
        label.setText(f"({coords['x']}, {coords['y']})")
        btn.setText(default_text)

        btn.setEnabled(True)
        self._calibrating_target = None

    def _on_settings_changed(self) -> None:
        conf = float(self.spin_confidence.value())
        self._config_mgr.update(
            min_detection_confidence=conf,
            min_tracking_confidence=conf,
            stabilization_frames=int(self.spin_stab_frames.value()),
            cooldown_seconds=float(self.spin_cooldown.value()),
            scroll_method=self.combo_scroll.currentText(),
        )

    def update_telemetry(self, packet: TrackingFramePacket) -> None:
        self.lbl_camera_status.setText("Active (No Feed Rendered)" if packet.camera_ok else "Error")
        self.lbl_tracking_status.setText(packet.status_message)
        self.lbl_fps.setText(f"{packet.fps:.1f} FPS")

        eval_state = packet.evaluation
        if eval_state.awaiting_release:
            self.lbl_current_gesture.setText(
                f"{eval_state.raw_gesture.value} [Release Hand]"
            )
        else:
            self.lbl_current_gesture.setText(eval_state.raw_gesture.value)

        self.stability_bar.setValue(int(eval_state.stability_progress * 100))

        if eval_state.triggered_action != GestureType.NONE:
            if self._config_mgr.config.automation_enabled:
                self.lbl_last_action.setText(eval_state.triggered_action.value)
            else:
                self.lbl_last_action.setText(
                    f"{eval_state.triggered_action.value} (Paused)"
                )

    def show_camera_error(self, error_msg: str) -> None:
        self.lbl_camera_status.setText("Camera Permission / Device Error")
        self.lbl_tracking_status.setText(error_msg)

