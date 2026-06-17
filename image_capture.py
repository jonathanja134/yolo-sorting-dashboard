import time
from datetime import datetime
from pathlib import Path
from picamera2 import Picamera2
from pynput import keyboard

# ── CONFIG ─────────────────────────────────────

SAVE_FOLDER = "images_captured3"
DEBOUNCE_TIME = 0.5

Path(SAVE_FOLDER).mkdir(parents=True, exist_ok=True)

# ── CAMERA SETUP ──────────────────────────────

picam2 = Picamera2()
config = picam2.create_still_configuration(main={"size": (320, 320)})
picam2.configure(config)
picam2.start()
time.sleep(2)  # warm-up

# ── STATE ──────────────────────────────────────

last_trigger = 0
running = True

def on_press(key):
    global last_trigger, running

    if key == keyboard.Key.space:
        now = time.time()
        if now - last_trigger > DEBOUNCE_TIME:
            last_trigger = now
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"{SAVE_FOLDER}/img_{timestamp}.jpg"
            print(f"[TRIGGER] Capturing {filename}")
            picam2.capture_file(filename)
            print("[OK] Saved")

    elif key == keyboard.KeyCode.from_char('q'):
        running = False
        return False  # stops the listener

print("System running... press SPACE to capture, Q to quit")

try:
    with keyboard.Listener(on_press=on_press) as listener:
        while running:
            time.sleep(0.01)
        listener.stop()

finally:
    picam2.close()
    print("\nStopped")