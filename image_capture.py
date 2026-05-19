import RPi.GPIO as GPIO
import time
from datetime import datetime
from pathlib import Path
from picamera2 import Picamera2

# ── CONFIG ─────────────────────────────────────

SENSOR_PIN = 27
SAVE_FOLDER = "images_captured"
DEBOUNCE_TIME = 0.5

Path(SAVE_FOLDER).mkdir(parents=True, exist_ok=True)

# ── GPIO SETUP ────────────────────────────────

GPIO.setmode(GPIO.BCM)
GPIO.setup(SENSOR_PIN, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

# ── CAMERA SETUP ──────────────────────────────

picam2 = Picamera2()

config = picam2.create_still_configuration(
    main={"size": (320, 320)}
)

picam2.configure(config)
picam2.start()

time.sleep(2)  # warm-up

# ── STATE ──────────────────────────────────────

last_trigger = 0
sensor_was_high = False

print("System running... waiting for trigger")

try:
    while True:

        sensor_state = GPIO.input(SENSOR_PIN)

        # rising edge detection (LOW → HIGH)
        if sensor_state == GPIO.HIGH and not sensor_was_high:

            now = time.time()

            if now - last_trigger > DEBOUNCE_TIME:

                last_trigger = now

                timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                filename = f"{SAVE_FOLDER}/img_{timestamp}.jpg"

                print(f"[TRIGGER] Capturing {filename}")

                picam2.capture_file(filename)

                print("[OK] Saved")

        sensor_was_high = (sensor_state == GPIO.HIGH)

        time.sleep(0.01)  # fast polling

except KeyboardInterrupt:
    print("\nStopped")

finally:
    picam2.close()
    GPIO.cleanup()