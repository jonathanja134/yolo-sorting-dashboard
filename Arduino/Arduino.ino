
//        NOT USED 

#include <Wire.h>
#include <EEPROM.h>
#include <Adafruit_PWMServoDriver.h>

Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver();

// ── CONFIG ─────────────────────────────────────
#define SERVO_CHANNEL 13   // Applicator servo on PCA9685 channel 14

#define SERVO_MIN 150
#define SERVO_MAX 600

// Saved startup (closed) position in EEPROM
#define EEPROM_ADDR_HOME 0

// Your working positions
#define DEFAULT_CLOSED_POS 160
#define DEFAULT_OPEN_POS   120

#define OPEN_DELAY_MS 1000

int homePos = DEFAULT_CLOSED_POS;
int openPos = DEFAULT_OPEN_POS;

// ── HELPERS ────────────────────────────────────

// Reversed direction mapping (works for your setup)
uint16_t angleToPulse(int angle) {
  angle = constrain(angle, 0, 180);

  return map(angle, 0, 180, SERVO_MAX, SERVO_MIN);
}

void moveServo(int angle) {
  angle = constrain(angle, 0, 180);

  pwm.setPWM(SERVO_CHANNEL, 0, angleToPulse(angle));

  Serial.print("SERVO MOVED TO: ");
  Serial.println(angle);
}

void saveHomePosition(int angle) {
  angle = constrain(angle, 0, 180);

  EEPROM.write(EEPROM_ADDR_HOME, angle);

  Serial.print("HOME POSITION SAVED: ");
  Serial.println(angle);
}

void loadHomePosition() {
  int stored = EEPROM.read(EEPROM_ADDR_HOME);

  if (stored >= 0 && stored <= 180) {
    homePos = stored;

    Serial.print("HOME POSITION LOADED: ");
    Serial.println(homePos);
  } else {
    homePos = DEFAULT_CLOSED_POS;

    Serial.print("NO VALID EEPROM VALUE -> USING DEFAULT: ");
    Serial.println(homePos);
  }
}

void testCycle() {
  Serial.println("STARTING TEST CYCLE");

  // Start closed
  moveServo(homePos);
  delay(1000);

  // Open
  moveServo(openPos);
  Serial.println("SERVO OPEN");
  delay(OPEN_DELAY_MS);

  // Close again
  moveServo(homePos);
  Serial.println("SERVO CLOSED");

  Serial.println("TEST CYCLE DONE");
}

// ── SETUP ──────────────────────────────────────

void setup() {
  Serial.begin(115200);
  delay(500);

  pwm.begin();
  pwm.setPWMFreq(50);
  delay(500);

  Serial.println("=== SERVO STARTUP TEST ===");

  // Load saved startup position
  loadHomePosition();

  // Move immediately to startup position
  moveServo(homePos);

  Serial.println("\nCommands:");
  Serial.println("SAVE_HOME     -> save current closed position");
  Serial.println("TEST          -> closed -> open -> close");
  Serial.println("SET_HOME_160  -> force home = 160");
  Serial.println("SET_OPEN_120  -> force open = 120");
  Serial.println("===========================\n");
}

// ── LOOP ───────────────────────────────────────

void loop() {
  if (!Serial.available()) return;

  String cmd = Serial.readStringUntil('\n');
  cmd.trim();

  if (cmd == "TEST") {
    testCycle();
    return;
  }

  if (cmd == "SAVE_HOME") {
    saveHomePosition(homePos);
    return;
  }

  if (cmd == "SET_HOME") {
    homePos = 120;
    moveServo(homePos);

    Serial.println("HOME POSITION SET TO 160");
    return;
  }

  if (cmd == "SET_OPEN") {
    openPos = 80; //NOTE 80 for right side 160 for left side;

    Serial.println("OPEN POSITION SET TO 120");
    return;
  }

  Serial.println("UNKNOWN COMMAND");
}