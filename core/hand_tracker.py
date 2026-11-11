from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple
import time

import cv2
import mediapipe as mp
import numpy as np


@dataclass(frozen=True)
class HandLandmarks:
    """Normalized 21-landmark representation for a single detected hand."""
    label: str  # "Left" or "Right"
    score: float
    landmarks: np.ndarray  # Shape: (21, 3) -> normalized (x, y, z)


class HandTracker:
    """Wraps MediaPipe Hands to extract up to 2 hand skeletons per frame."""

    CONNECTIONS: List[Tuple[int, int]] = list(mp.solutions.hands.HAND_CONNECTIONS)

    def __init__(
        self,
        min_detection_confidence: float = 0.75,
        min_tracking_confidence: float = 0.75,
    ) -> None:
        self._min_det = min_detection_confidence
        self._min_trk = min_tracking_confidence
        self._mp_hands = mp.solutions.hands
        self._detector = self._create_detector()
        # Smooth landmark jitter and briefly bridge one-frame detector dropouts.
        self._smoothed: Dict[str, np.ndarray] = {}
        self._last_seen: Dict[str, float] = {}
        self._hold_seconds = 0.10
        self._smoothing_alpha = 0.72

    def _create_detector(self):
        return self._mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=2,
            model_complexity=0,
            min_detection_confidence=self._min_det,
            min_tracking_confidence=self._min_trk,
        )

    def update_thresholds(
        self,
        min_detection_confidence: float,
        min_tracking_confidence: float,
    ) -> None:
        if (
            abs(min_detection_confidence - self._min_det) > 1e-3
            or abs(min_tracking_confidence - self._min_trk) > 1e-3
        ):
            self._min_det = min_detection_confidence
            self._min_trk = min_tracking_confidence
            self._detector.close()
            self._detector = self._create_detector()

    def process_bgr_frame(self, bgr_frame: np.ndarray) -> List[HandLandmarks]:
        """
        Mirrors the frame horizontally for natural overlay alignment, extracts
        landmarks above confidence thresholds, and discards image buffers.
        """
        mirrored = cv2.flip(bgr_frame, 1)
        rgb_frame = cv2.cvtColor(mirrored, cv2.COLOR_BGR2RGB)
        rgb_frame.flags.writeable = False

        results = self._detector.process(rgb_frame)
        detected_hands: List[HandLandmarks] = []
        now = time.monotonic()

        if not results.multi_hand_landmarks or not results.multi_handedness:
            return self._recent_hands(now)

        for hand_lms, handedness in zip(
            results.multi_hand_landmarks, results.multi_handedness
        ):
            classification = handedness.classification[0]
            score = float(classification.score)
            if score < self._min_trk:
                continue

            coords = np.array(
                [[lm.x, lm.y, lm.z] for lm in hand_lms.landmark],
                dtype=np.float32,
            )
            previous = self._smoothed.get(classification.label)
            if previous is not None:
                coords = self._smoothing_alpha * coords + (1.0 - self._smoothing_alpha) * previous
            self._smoothed[classification.label] = coords
            self._last_seen[classification.label] = now
            detected_hands.append(
                HandLandmarks(
                    label=classification.label,
                    score=score,
                    landmarks=coords,
                )
            )

        # Keep a recently tracked hand visible through very short detection gaps.
        present = {hand.label for hand in detected_hands}
        for hand in self._recent_hands(now):
            if hand.label not in present:
                detected_hands.append(hand)
        return detected_hands

    def _recent_hands(self, now: float) -> List[HandLandmarks]:
        recent: List[HandLandmarks] = []
        expired = []
        for label, last_seen in self._last_seen.items():
            age = now - last_seen
            if age <= self._hold_seconds and label in self._smoothed:
                # Fade confidence slightly while bridging a brief missed frame.
                score = max(0.0, 0.8 - age * 1.5)
                recent.append(HandLandmarks(label, score, self._smoothed[label].copy()))
            elif age > self._hold_seconds:
                expired.append(label)
        for label in expired:
            self._last_seen.pop(label, None)
            self._smoothed.pop(label, None)
        return recent

    def close(self) -> None:
        if self._detector is not None:
            self._detector.close()

