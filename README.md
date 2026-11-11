# GestureFlow — macOS Hand-Gesture Controller

**Intel Mac (x86_64) is supported. Apple Silicon is also supported; it is not required.** Use Python 3.12 and install the dependencies in the instructions below.

GestureFlow is a local Python desktop app that uses a Mac camera and MediaPipe to draw a live 21-landmark hand skeleton over the desktop and optionally control TikTok. The webcam image is never shown in the overlay.

## Requirements
- macOS with camera access
- Python 3.12 recommended
- TikTok open in a normal desktop browser window

## Install
From Terminal:

```bash
cd ~/Downloads/GestureFlow
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -c "import cv2, mediapipe, PySide6, pyautogui; print('ALL WORKING')"
python main.py
```

Always launch with the virtual environment active. In VS Code, use **Cmd+Shift+P → Python: Select Interpreter → .venv/bin/python**. The yellow import underlines in the editor usually mean VS Code is using a different Python interpreter; they do not necessarily mean the source code is invalid.

## macOS permissions
In **System Settings → Privacy & Security**, allow Camera and Accessibility access for the terminal or IDE used to launch the app. Restart the app after changing permissions.

## Gestures
- One thumbs down: next video (one Down Arrow press; tolerant of small hand movement)
- One index finger pointing up: previous video (one Up Arrow press)
- One thumbs up: move to calibrated Like position and click once
- Both thumbs up: click the calibrated Repost button, wait for TikTok's confirmation UI, then click the separately calibrated confirmation position
- Neutral/no gesture: no action

## Calibration
1. Launch the app with automation disabled.
2. In TikTok, locate the Like button. Click **Set Like Position**, then move the cursor over the Like button during the 3-second countdown.
3. Repeat for **Set Repost Position** (the repost icon/button).
4. Click **Set Confirm Position**, then hover over the Repost confirmation button/menu item that appears after the first repost click.
5. Enable gesture control only after all positions have been checked.

The three positions are saved in `config.json`. The initial coordinates are placeholders and must be calibrated on your display.

## Overlay behavior
The skeleton overlay is transparent and click-through. It uses Qt's always-on-top hint plus native macOS `NSWindow` level and Spaces/full-screen collection behavior. macOS can still restrict overlays over protected/system UI or some exclusive full-screen surfaces.

## Safety
- Gesture automation starts disabled.
- Use the Emergency Stop button if an action misfires.
- Test the Like/Repost coordinates manually before enabling gestures.
- Repost requires two separate calibrated clicks; do not leave the confirmation coordinate at its placeholder.
