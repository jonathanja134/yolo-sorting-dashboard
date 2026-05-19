#include <EEPROM.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver(); // default I2C addr 0x40

// ── CONFIG ───────────────────────────────────────────────────
#define NB_SERVOS 4

// PCA9685 channel numbers (0–15)
// 1: "canister"
// 2: "chemical"
// 3: "applicator"
// 4: "inhaler"


#define S_MOTOR_1  12   // LEFT group
#define S_MOTOR_2  13   // LEFT group
#define S_MOTOR_3  14   // RIGHT group (sensor side)
#define S_MOTOR_4  15   // RIGHT group (sensor side

#define MotorFw 10

#define MotorDw  9

#define POS_SENSOR_1  4
#define POS_SENSOR_2  2
#define RESET_SENSOR  5

#define PULLDOWN_1   7
#define PULLDOWN_2   6
#define PULLDOWN_R  11

// PCA9685 @ 50 Hz → 4096 ticks per 20 ms period
#define SERVO_MIN 150    // ~1000 µs  (≈ 0°)
#define SERVO_MAX 600    // ~2000 µs  (≈ 180°)

// ── SERVO POSITIONS ──────────────────────────────────────────
#define CLOSED_POS      120   // all servos close to this position
#define OPEN_POS_LEFT    80   // channels 12, 13 (idx 0, 1) open position
#define OPEN_POS_RIGHT  160   // channels 14, 15 (idx 2, 3) open position

const unsigned long  SERVO_OPEN_MS  = 500;
const unsigned long  SENSOR_TIMEOUT = 400;
const unsigned long  DEBOUNCE_MS    = 50;

const int EEPROM_ADDR[NB_SERVOS]      = { 0, 1, 2, 3 };
const int SERVO_CHANNELS[NB_SERVOS]   = { S_MOTOR_1, S_MOTOR_2, S_MOTOR_3, S_MOTOR_4 };
const char* CATEGORY_NAMES[NB_SERVOS] = { "canister", "chemical", "applicator", "inhaler" };

const int MotorOnLED = 3;
int  servoPos[NB_SERVOS];
int  homePos[NB_SERVOS];
bool servoOpen[NB_SERVOS] = {};
bool motorRunning = false;
bool inActuation  = false;

// ── SENSOR STATE ─────────────────────────────────────────────
struct Sensor {
  int           id;
  int           pin;
  bool          raw;
  bool          state;
  bool          triggered;
  unsigned long lastEdge;
};

Sensor sensors[2] = {
  { 1, POS_SENSOR_1, LOW, LOW, false, 0 },
  { 2, POS_SENSOR_2, LOW, LOW, false, 0 }
};

// ── HELPERS ──────────────────────────────────────────────────
uint16_t angleToPulse(int angle) {
  angle = constrain(angle, 0, 180);
  angle = 180 - angle;   // invert servo direction
  return map(angle, 0, 180, SERVO_MIN, SERVO_MAX);
}

// Returns the correct open position for a given servo index
int getOpenPos(int idx) {
  return (idx < 2) ? OPEN_POS_LEFT : OPEN_POS_RIGHT;
}

// ── MOVE SERVO via PCA9685 ───────────────────────────────────
void moveServo(int idx, int angle) {
  angle = constrain(angle, 0, 180);
  pwm.setPWM(SERVO_CHANNELS[idx], 0, angleToPulse(angle));
  servoPos[idx] = angle;
}

// ── SETUP ────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);

  pwm.begin();
  pwm.setPWMFreq(50);
  delay(10);
  Serial.println("PCA9685 OK");

  pinMode(PULLDOWN_1, OUTPUT); digitalWrite(PULLDOWN_1, LOW);
  pinMode(PULLDOWN_2, OUTPUT); digitalWrite(PULLDOWN_2, LOW);
  pinMode(PULLDOWN_R, OUTPUT); digitalWrite(PULLDOWN_R, LOW);

  pinMode(POS_SENSOR_1, INPUT);
  pinMode(POS_SENSOR_2, INPUT);
  pinMode(RESET_SENSOR, INPUT);

  pinMode(MotorFw, OUTPUT); digitalWrite(MotorFw, LOW);
  pinMode(MotorDw, OUTPUT); digitalWrite(MotorDw, LOW);
  pinMode(MotorOnLED, OUTPUT); digitalWrite(MotorOnLED, LOW);

  for (int i = 0; i < NB_SERVOS; i++) {
    // Ignore stored EEPROM positions — always start at CLOSED_POS
    homePos[i]  = CLOSED_POS;
    servoPos[i] = CLOSED_POS;
    moveServo(i, CLOSED_POS);
    Serial.print("SERVO:"); Serial.print(i + 1);
    Serial.print(":INIT:CLOSED:"); Serial.println(CLOSED_POS);
  }

  Serial.println("=== Sorting System Ready ===");
}

// ── LOOP ─────────────────────────────────────────────────────
void loop() {
  readSensors();
  readSerial();
}

// ── SENSOR UPDATE ────────────────────────────────────────────
void updateSensor(Sensor &s, int servoStart, int servoEnd) {
  unsigned long now     = millis();
  bool          reading = digitalRead(s.pin);

  if (reading == s.raw) return;
  if ((now - s.lastEdge) < DEBOUNCE_MS) return;

  s.raw      = reading;
  s.lastEdge = now;

  if (reading == HIGH && s.state == LOW) {
    s.state     = HIGH;
    s.triggered = true;
    Serial.print("SENSOR:"); Serial.print(s.id); Serial.println(":TRIGGERED");

  } else if (reading == LOW && s.state == HIGH) {
    s.state     = LOW;
    s.triggered = false;

    if (!inActuation) {
      for (int i = servoStart; i < servoEnd; i++) {
        if (servoOpen[i]) {
          moveServo(i, CLOSED_POS);
          servoOpen[i] = false;
          Serial.print("SERVO:"); Serial.print(i + 1); Serial.println(":FORCED_CLOSE");
        }
      }
    }
  }
}

void readSensors() {
  updateSensor(sensors[0], 0, 2);
  updateSensor(sensors[1], 2, 4);
}

// ── SERIAL ───────────────────────────────────────────────────
void readSerial() {
  if (!Serial.available()) return;

  String rawCmd = Serial.readStringUntil('\n');
  rawCmd.replace("\r", "");
  rawCmd.trim();

  if (rawCmd.length() == 0) return;

  int sep = rawCmd.indexOf(':');
  if (sep <= 0) {
    Serial.println("ERR:UNKNOWN_CMD");
    return;
  }

  String key = rawCmd.substring(0, sep);
  String arg = rawCmd.substring(sep + 1);
  key.trim();
  arg.trim();
  key.toUpperCase();

  if (key == "MOTOR") {
    arg.toUpperCase();
    if (arg == "FORWARD") {
      digitalWrite(MotorFw, HIGH);
      digitalWrite(MotorOnLED, HIGH);
      digitalWrite(MotorDw, LOW);
      motorRunning = true;
      Serial.println("ACK:MOTOR:FORWARD");
    } else if (arg == "STOP") {
      digitalWrite(MotorFw, LOW);
      digitalWrite(MotorOnLED, LOW);
      digitalWrite(MotorDw, LOW);
      motorRunning = false;
      Serial.println("ACK:MOTOR:STOP");
    } else {
      Serial.println("ERR:MOTOR:UNKNOWN");
    }
    return;
  }

  if (key != "LABEL") {
    Serial.println("ERR:UNKNOWN_CMD");
    return;
  }

  String category = arg;
  category.toLowerCase();

  int idx = -1;
  for (int i = 0; i < NB_SERVOS; i++) {
    if (category == CATEGORY_NAMES[i]) { idx = i; break; }
  }

  if (idx == -1) {
    Serial.print("ERR:BAD_CATEGORY:"); Serial.println(category);
    return;
  }

  Serial.print("ACK:LABEL:"); Serial.println(category);
  actuateServo(idx);
}

// ── SERVO ACTION ─────────────────────────────────────────────
void actuateServo(int idx) {
  inActuation = true;

  Sensor &s = sensors[(idx < 2) ? 0 : 1];
  s.triggered = false;

  int openPos = getOpenPos(idx);

  moveServo(idx, openPos);
  servoOpen[idx] = true;
  Serial.print("SERVO:"); Serial.print(idx + 1);
  Serial.print(":OPEN:"); Serial.print(openPos);
  Serial.print(":CATEGORY:"); Serial.print(CATEGORY_NAMES[idx]);
  Serial.print(":CHANNEL:"); Serial.println(SERVO_CHANNELS[idx]);

  delay(SERVO_OPEN_MS);
  s.triggered = false;

  unsigned long start    = millis();
  bool          detected = false;

  while (millis() - start < SENSOR_TIMEOUT) {
    readSensors();
    if (s.triggered) {
      detected    = true;
      s.triggered = false;
      Serial.print("SERVO:"); Serial.print(idx + 1);
      Serial.print(":OBJECT_DETECTED:");
      Serial.print(CATEGORY_NAMES[idx]);
      Serial.print(":CHANNEL:");
      Serial.println(SERVO_CHANNELS[idx]);
      break;
    }
  }

  moveServo(idx, CLOSED_POS);
  servoOpen[idx] = false;
  inActuation    = false;

  Serial.print("SERVO:"); Serial.print(idx + 1);
  Serial.print(detected ? ":CLOSED_OK" : ":CLOSED_TIMEOUT");
  Serial.print(":CATEGORY:"); Serial.print(CATEGORY_NAMES[idx]);
  Serial.print(":CHANNEL:"); Serial.println(SERVO_CHANNELS[idx]);
}
