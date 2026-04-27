#include <EEPROM.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver(); // default I2C addr 0x40

// ── CONFIG ───────────────────────────────────────────────────
#define NB_SERVOS 4

// PCA9685 channel numbers (0–15)
#define S_MOTOR_1  12
#define S_MOTOR_2  13
#define S_MOTOR_3  14
#define S_MOTOR_4  15

#define MotorFw 10
#define MotorDw  9

#define POS_SENSOR_1  4
#define POS_SENSOR_2  2
#define RESET_SENSOR  5

#define PULLDOWN_1   3
#define PULLDOWN_2   6
#define PULLDOWN_R  11

// PCA9685 @ 50 Hz → 4096 ticks per 20 ms period
// Standard servo: 1000 µs (0°) … 2000 µs (180°)
// Adjust SERVO_MIN / SERVO_MAX to match your servos if needed
#define SERVO_MIN  125   // ~1000 µs  (≈ 0°)
#define SERVO_MAX  625   // ~2000 µs  (≈ 180°)

const int            OPEN_OFFSET    = 47;
const unsigned long  SERVO_OPEN_MS  = 400;
const unsigned long  SENSOR_TIMEOUT = 8000;
const unsigned long  DEBOUNCE_MS    = 50;

const int EEPROM_ADDR[NB_SERVOS]      = { 0, 1, 2, 3 };
const int SERVO_CHANNELS[NB_SERVOS]   = { S_MOTOR_1, S_MOTOR_2, S_MOTOR_3, S_MOTOR_4 };
const char* CATEGORY_NAMES[NB_SERVOS] = { "canister", "sharps", "applicator", "inhaler" };

int  servoPos[NB_SERVOS];
int  homePos[NB_SERVOS];
bool servoOpen[NB_SERVOS] = {};
bool motorRunning = false;
bool inActuation  = false;

// ── PNP NO SENSOR STATE ──────────────────────────────────────
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
// Convert 0–180° angle to PCA9685 tick count
uint16_t angleToPulse(int angle) {
  angle = constrain(angle, 0, 180);
  return map(angle, 0, 180, SERVO_MIN, SERVO_MAX);
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

  // PCA9685 init
  pwm.begin();
  pwm.setPWMFreq(50);   // 50 Hz standard for servos
  delay(10);            // let oscillator stabilise

  pinMode(PULLDOWN_1, OUTPUT); digitalWrite(PULLDOWN_1, LOW);
  pinMode(PULLDOWN_2, OUTPUT); digitalWrite(PULLDOWN_2, LOW);
  pinMode(PULLDOWN_R, OUTPUT); digitalWrite(PULLDOWN_R, LOW);

  pinMode(POS_SENSOR_1, INPUT);
  pinMode(POS_SENSOR_2, INPUT);
  pinMode(RESET_SENSOR, INPUT);

  pinMode(MotorFw, OUTPUT); digitalWrite(MotorFw, LOW);
  pinMode(MotorDw, OUTPUT); digitalWrite(MotorDw, LOW);

  for (int i = 0; i < NB_SERVOS; i++) {
    byte stored  = EEPROM.read(EEPROM_ADDR[i]);
    bool hasHome = (stored <= 180);

    if (hasHome) {
      homePos[i]  = (int)stored;
      servoPos[i] = homePos[i];
      moveServo(i, homePos[i]);   // drive PCA9685 channel to stored position
      Serial.print("SERVO:"); Serial.print(i + 1);
      Serial.print(":RESTORED:"); Serial.println(homePos[i]);
    } else {
      homePos[i]  = 90;
      servoPos[i] = 90;
      // NOT written to driver — servo stays physically where it is
      Serial.print("SERVO:"); Serial.print(i + 1);
      Serial.println(":NO_HOME — position manually then send HOME:SAVE");
    }
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
          moveServo(i, homePos[i]);
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

  String cmd = Serial.readStringUntil('\n');
  cmd.trim();

  if (cmd == "HOME:SAVE") {
    for (int i = 0; i < NB_SERVOS; i++) {
      homePos[i] = servoPos[i];   // capture current position as home
      EEPROM.write(EEPROM_ADDR[i], (byte)homePos[i]);
      Serial.print("HOME:SAVED:SERVO:"); Serial.print(i + 1);
      Serial.print(":"); Serial.println(homePos[i]);
    }
    return;
  }

  if (cmd.startsWith("MOTOR:")) {
    String action = cmd.substring(6);
    if (action == "FORWARD") {
      digitalWrite(MotorFw, HIGH);
      digitalWrite(MotorDw, LOW);
      motorRunning = true;
      Serial.println("ACK:MOTOR:FORWARD");
    } else if (action == "STOP") {
      digitalWrite(MotorFw, LOW);
      digitalWrite(MotorDw, LOW);
      motorRunning = false;
      Serial.println("ACK:MOTOR:STOP");
    } else {
      Serial.println("ERR:MOTOR:UNKNOWN");
    }
    return;
  }

  if (!cmd.startsWith("LABEL:")) {
    Serial.println("ERR:UNKNOWN_CMD");
    return;
  }

  String category = cmd.substring(6);
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

  int openPos = constrain(homePos[idx] + OPEN_OFFSET, 0, 180);
  if (openPos == homePos[idx]) {
    Serial.print("WARN:SERVO:"); Serial.print(idx + 1);
    Serial.println(":OPEN_CLAMPED — homePos too high for OPEN_OFFSET");
  }

  moveServo(idx, openPos);
  servoOpen[idx] = true;
  Serial.print("SERVO:"); Serial.print(idx + 1); Serial.println(":OPEN");

  delay(SERVO_OPEN_MS);
  s.triggered = false;

  unsigned long start    = millis();
  bool          detected = false;

  while (millis() - start < SENSOR_TIMEOUT) {
    readSensors();

    if (s.triggered) {
      detected    = true;
      s.triggered = false;
      Serial.print("SERVO:"); Serial.print(idx + 1); Serial.println(":OBJECT_DETECTED");
      break;
    }
  }

  moveServo(idx, homePos[idx]);
  servoOpen[idx] = false;
  inActuation    = false;

  Serial.print("SERVO:"); Serial.print(idx + 1);
  Serial.println(detected ? ":CLOSED_OK" : ":CLOSED_TIMEOUT");
}