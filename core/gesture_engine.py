from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import List

import numpy as np

from core.hand_tracker import HandLandmarks


class GestureType(str, Enum):
    NONE = "No Gesture"
    ONE_THUMB_UP = "One Thumbs Up (Like)"
    ONE_THUMB_DOWN = "Thumbs Down (Next Video)"
    ONE_INDEX_UP = "Index Finger Up (Previous Video)"
    BOTH_THUMBS_UP = "Both Thumbs Up (Repost)"


class SingleHandPose(str, Enum):
    NEUTRAL = "NEUTRAL"
    THUMB_UP = "THUMB_UP"
    THUMB_DOWN = "THUMB_DOWN"
    INDEX_UP = "INDEX_UP"


@dataclass(frozen=True)
class GestureEvaluation:
    raw_gesture: GestureType
    stable_gesture: GestureType
    triggered_action: GestureType
    stability_progress: float  # 0.0 to 1.0
    cooldown_remaining: float  # Seconds
    awaiting_release: bool


class GestureEngine:
    """Vector-based hand gesture classifier with stabilization and release latching."""

    def __init__(
        self,
        stabilization_frames: int = 8,
        release_frames: int = 4,
        cooldown_seconds: float = 1.25,
    ) -> None:
        self.stabilization_frames = max(2, stabilization_frames)
        self.release_frames = max(1, release_frames)
        self.cooldown_seconds = max(0.2, cooldown_seconds)

        self._candidate_gesture: GestureType = GestureType.NONE
        self._candidate_count: int = 0
        self._neutral_count: int = 0
        self._awaiting_release: bool = False
        self._last_trigger_time: float = 0.0
        self._active_stable_gesture: GestureType = GestureType.NONE

    @staticmethod
    def classify_single_hand(hand: HandLandmarks) -> SingleHandPose:
        """Classify poses using palm-relative geometry tolerant of small movement."""
        pts = hand.landmarks[:, :2]
        wrist = pts[0]
        palm_scale = float(np.linalg.norm(pts[9] - wrist))
        if palm_scale < 0.035:
            return SingleHandPose.NEUTRAL

        def finger_extended(mcp: int, pip: int, tip: int) -> bool:
            tip_wrist = float(np.linalg.norm(pts[tip] - wrist))
            pip_wrist = float(np.linalg.norm(pts[pip] - wrist))
            tip_mcp = float(np.linalg.norm(pts[tip] - pts[mcp]))
            return tip_wrist > pip_wrist * 1.12 and tip_mcp > palm_scale * 0.85

        index_ext = finger_extended(5, 6, 8)
        middle_ext = finger_extended(9, 10, 12)
        ring_ext = finger_extended(13, 14, 16)
        pinky_ext = finger_extended(17, 18, 20)
        thumb_vec = pts[4] - pts[2]
        thumb_norm = float(np.linalg.norm(thumb_vec))
        thumb_up = thumb_down = False
        if thumb_norm >= palm_scale * 0.30:
            unit = thumb_vec / thumb_norm
            up_angle = float(np.degrees(np.arccos(np.clip(np.dot(unit, np.array([0.0, -1.0])), -1.0, 1.0))))
            down_angle = float(np.degrees(np.arccos(np.clip(np.dot(unit, np.array([0.0, 1.0])), -1.0, 1.0))))
            thumb_up = up_angle <= 52.0 and pts[4][1] < pts[2][1] - 0.08 * palm_scale
            # Wider direction tolerance and palm-relative test reduce dropouts
            # when the user's wrist bobs slightly while holding thumbs-down.
            thumb_down = down_angle <= 58.0 and pts[4][1] > pts[2][1] + 0.06 * palm_scale

        non_thumb_curled = not (index_ext or middle_ext or ring_ext or pinky_ext)
        if non_thumb_curled and thumb_up:
            return SingleHandPose.THUMB_UP
        if non_thumb_curled and thumb_down:
            return SingleHandPose.THUMB_DOWN

        thumb_tip_near_palm = float(np.linalg.norm(pts[4] - pts[5])) < palm_scale * 1.05
        if index_ext and not middle_ext and not ring_ext and not pinky_ext and thumb_tip_near_palm:
            index_vec = pts[8] - pts[5]
            index_norm = float(np.linalg.norm(index_vec))
            if index_norm > 1e-5:
                index_angle = float(np.degrees(np.arccos(np.clip(
                    np.dot(index_vec / index_norm, np.array([0.0, -1.0])), -1.0, 1.0
                ))))
                if index_angle <= 48.0 and pts[8][1] < pts[6][1]:
                    return SingleHandPose.INDEX_UP
        return SingleHandPose.NEUTRAL

    def _resolve_raw_gesture(self, hands: List[HandLandmarks]) -> GestureType:
        if not hands:
            return GestureType.NONE

        poses = [self.classify_single_hand(h) for h in hands]
        up_count = sum(1 for p in poses if p == SingleHandPose.THUMB_UP)
        down_count = sum(1 for p in poses if p == SingleHandPose.THUMB_DOWN)
        index_up_count = sum(1 for p in poses if p == SingleHandPose.INDEX_UP)

        # Priority: two-hand repost > like > next video > previous video.
        if up_count >= 2:
            return GestureType.BOTH_THUMBS_UP
        if up_count == 1 and down_count == 0 and index_up_count == 0:
            return GestureType.ONE_THUMB_UP
        if down_count == 1 and up_count == 0 and index_up_count == 0:
            return GestureType.ONE_THUMB_DOWN
        if index_up_count == 1 and len(hands) == 1 and up_count == 0 and down_count == 0:
            return GestureType.ONE_INDEX_UP
        return GestureType.NONE

    def update(self, hands: List[HandLandmarks]) -> GestureEvaluation:
        now = time.monotonic()
        raw_gesture = self._resolve_raw_gesture(hands)
        cooldown_left = max(
            0.0, self.cooldown_seconds - (now - self._last_trigger_time)
        )

        # Handle release detection latch
        if self._awaiting_release:
            # Exception: allow immediate upgrade from ONE_THUMB_UP to BOTH_THUMBS_UP
            # only if BOTH_THUMBS_UP wasn't the gesture that just fired.
            if raw_gesture == GestureType.NONE:
                self._neutral_count += 1
                if self._neutral_count >= self.release_frames:
                    self._awaiting_release = False
                    self._neutral_count = 0
                    self._candidate_gesture = GestureType.NONE
                    self._candidate_count = 0
                    self._active_stable_gesture = GestureType.NONE
            else:
                self._neutral_count = 0

            return GestureEvaluation(
                raw_gesture=raw_gesture,
                stable_gesture=self._active_stable_gesture,
                triggered_action=GestureType.NONE,
                stability_progress=1.0 if self._active_stable_gesture != GestureType.NONE else 0.0,
                cooldown_remaining=cooldown_left,
                awaiting_release=self._awaiting_release,
            )

        # Normal stabilization state machine
        if raw_gesture == GestureType.NONE:
            self._candidate_gesture = GestureType.NONE
            self._candidate_count = 0
            self._active_stable_gesture = GestureType.NONE
            return GestureEvaluation(
                raw_gesture=GestureType.NONE,
                stable_gesture=GestureType.NONE,
                triggered_action=GestureType.NONE,
                stability_progress=0.0,
                cooldown_remaining=cooldown_left,
                awaiting_release=False,
            )

        if raw_gesture == self._candidate_gesture:
            self._candidate_count += 1
        else:
            # If upgrading from ONE_THUMB_UP to BOTH_THUMBS_UP mid-stabilization,
            # preserve half the accumulated frames for responsive bimanual priority
            if (
                self._candidate_gesture == GestureType.ONE_THUMB_UP
                and raw_gesture == GestureType.BOTH_THUMBS_UP
            ):
                self._candidate_count = max(1, self._candidate_count // 2)
            else:
                self._candidate_count = 1
            self._candidate_gesture = raw_gesture

        # If 2 hands are visible and one is already THUMB_UP, require 2 extra frames
        # before firing ONE_THUMB_UP so the second hand has time to settle into BOTH_THUMBS_UP
        required_frames = self.stabilization_frames
        if raw_gesture == GestureType.ONE_THUMB_UP and len(hands) == 2:
            required_frames += 3

        progress = min(1.0, self._candidate_count / float(required_frames))

        triggered = GestureType.NONE
        if self._candidate_count >= required_frames and cooldown_left <= 0.0:
            self._active_stable_gesture = raw_gesture
            triggered = raw_gesture
            self._last_trigger_time = now
            self._awaiting_release = True
            self._neutral_count = 0

        return GestureEvaluation(
            raw_gesture=raw_gesture,
            stable_gesture=self._active_stable_gesture,
            triggered_action=triggered,
            stability_progress=progress,
            cooldown_remaining=cooldown_left,
            awaiting_release=self._awaiting_release,
        )

    def reset(self) -> None:
        self._candidate_gesture = GestureType.NONE
        self._candidate_count = 0
        self._neutral_count = 0
        self._awaiting_release = False
        self._active_stable_gesture = GestureType.NONE

