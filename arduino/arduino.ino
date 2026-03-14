// ══════════════════════════════════════════════════════════════
//  Sorting Line — Arduino Mega
//  Serial protocol (9600 baud, newline-terminated):
//
//  Arduino → Pi:
//    SENSOR:1:TRIGGERED\n
//    SENSOR:1:CLEAR\n
//    SENSOR:2:TRIGGERED\n
//    SENSOR:2:CLEAR\n
//
//  Pi → Arduino:
//    LABEL:applicator\n
//    LABEL:inhaler\n
//    LABEL:sharps\n
//    LABEL:hazardous\n
//    LABEL:unrecognized\n   (no actuation)
// ══════════════════════════════════════════════════════════════

#include <Servo.h>

// ── Servo count ──────────────────────────────────────────────
#define NB_SERVOS 4

// ── Servo pins ───────────────────────────────────────────────
#define S_MOTOR_1  13   // applicator  ← active
#define S_MOTOR_2  12   // inhaler     ← active
#define S_MOTOR_3   8   // sharps      ← ready, not wired yet
#define S_MOTOR_4   7   // hazardous   ← ready, not wired yet

// ── Proximity sensor pins ────────────────────────────────────
// Sensor 1 covers servos 1 & 2 (applicator / inhaler)
// Sensor 2 covers servos 3 & 4 (sharps / hazardous)
#define POS_SENSOR_1  4
#define POS_SENSOR_2  2

// ── Servo positions ──────────────────────────────────────────
const int OPEN_POS  = 90;
const int CLOSE_POS =  0;

// ── Timing ───────────────────────────────────────────────────
const unsigned long SERVO_OPEN_MS   =  400;   // time to hold open
const unsigned long SENSOR_TIMEOUT  = 8000;   // ms before force-close
const unsigned long DEBOUNCE_MS     =   50;   // sensor debounce

// ── Category → servo index mapping ──────────────────────────
// Index matches servoPins[] below
const int SERVO_PINS[NB_SERVOS] = {
  S_MOTOR_1,   // 0 → applicator
  S_MOTOR_2,   // 1 → inhaler
  S_MOTOR_3,   // 2 → sharps
  S_MOTOR_4    // 3 → hazardous
};

// Category strings (must match Pi protocol exactly)
const char* CATEGORY_NAMES[NB_SERVOS] = {
  "applicator",
  "inhaler",
  "sharps",
  "hazardous"
};

// Which proximity sensor pin guards each servo
const int SENSOR_PIN_FOR_SERVO[NB_SERVOS] = {
  POS_SENSOR_1,   // 0 applicator
  POS_SENSOR_1,   // 1 inhaler
  POS_SENSOR_2,   // 2 sharps
  POS_SENSOR_2    // 3 hazardous
};

Servo servos[NB_SERVOS];

// ── Sensor state tracking ────────────────────────────────────
bool sensor1LastState = HIGH;
bool sensor2LastState = HIGH;
unsigned long sensor1LastChange = 0;
unsigned long sensor2LastChange = 0;

// ══════════════════════════════════════════════════════════════
//  SETUP
// ══════════════════════════════════════════════════════════════
void setup() {
  Serial.begin(9600);
  Serial.println("=== Arduino Sorting — 4 servos, 2 sensors ===");
  Serial.println("Waiting for LABEL commands from Pi...");

  // Attach & close all servos
  for (int i = 0; i < NB_SERVOS; i++) {
    servos[i].attach(SERVO_PINS[i]);
    servos[i].write(CLOSE_POS);
  }

  // Proximity sensors with internal pull-up
  // (sensor output LOW when object detected)
  pinMode(POS_SENSOR_1, INPUT_PULLUP);
  pinMode(POS_SENSOR_2, INPUT_PULLUP);
}

// ══════════════════════════════════════════════════════════════
//  LOOP
// ══════════════════════════════════════════════════════════════
void loop() {
  readSensors();
  readSerial();
}

// ── Sensor polling & debounce ────────────────────────────────
void readSensors() {
  unsigned long now = millis();

  bool s1 = digitalRead(POS_SENSOR_1);
  bool s2 = digitalRead(POS_SENSOR_2);

  // Sensor 1
  if (s1 != sensor1LastState && (now - sensor1LastChange) > DEBOUNCE_MS) {
    sensor1LastState  = s1;
    sensor1LastChange = now;
    if (s1 == LOW) {
      Serial.println("SENSOR:1:TRIGGERED");
    } else {
      Serial.println("SENSOR:1:CLEAR");
    }
  }

  // Sensor 2
  if (s2 != sensor2LastState && (now - sensor2LastChange) > DEBOUNCE_MS) {
    sensor2LastState  = s2;
    sensor2LastChange = now;
    if (s2 == LOW) {
      Serial.println("SENSOR:2:TRIGGERED");
    } else {
      Serial.println("SENSOR:2:CLEAR");
    }
  }
}

// ── Serial command reader ────────────────────────────────────
void readSerial() {
  if (!Serial.available()) return;

  String cmd = Serial.readStringUntil('\n');
  cmd.trim();

  // Expected format: LABEL:category
  if (!cmd.startsWith("LABEL:")) {
    Serial.print("ERR unknown command: ");
    Serial.println(cmd);
    return;
  }

  String category = cmd.substring(6);   // everything after "LABEL:"
  category.toLowerCase();

  // No actuation for unrecognized
  if (category == "unrecognized") {
    Serial.println("INFO:unrecognized — no actuation");
    return;
  }

  // Find matching servo
  int servoIdx = -1;
  for (int i = 0; i < NB_SERVOS; i++) {
    if (category == CATEGORY_NAMES[i]) {
      servoIdx = i;
      break;
    }
  }

  if (servoIdx == -1) {
    Serial.print("ERR unknown category: ");
    Serial.println(category);
    return;
  }

  Serial.print("ACK:LABEL:");
  Serial.print(category);
  Serial.print(":SERVO:");
  Serial.println(servoIdx + 1);

  actuateServo(servoIdx);
}

// ── Servo actuation ──────────────────────────────────────────
void actuateServo(int idx) {
  int sensorPin = SENSOR_PIN_FOR_SERVO[idx];

  // Open
  servos[idx].write(OPEN_POS);
  Serial.print("SERVO:");
  Serial.print(idx + 1);
  Serial.println(":OPEN");

  delay(SERVO_OPEN_MS);

  // Wait for proximity sensor confirmation or timeout
  Serial.print("SERVO:");
  Serial.print(idx + 1);
  Serial.println(":WAITING_SENSOR");

  unsigned long start = millis();
  bool detected = false;

  while (millis() - start < SENSOR_TIMEOUT) {
    if (digitalRead(sensorPin) == LOW) {
      detected = true;
      Serial.print("SERVO:");
      Serial.print(idx + 1);
      Serial.println(":OBJECT_CONFIRMED");
      break;
    }
    delay(10);
  }

  // Close
  servos[idx].write(CLOSE_POS);
  Serial.print("SERVO:");
  Serial.print(idx + 1);
  if (detected) {
    Serial.println(":CLOSED_AFTER_DETECTION");
  } else {
    Serial.println(":CLOSED_TIMEOUT");
  }
}
