#include <Servo.h>

// ── CONFIG ──────────────────────────────────────────────────
#define NB_SERVOS 4

#define S_MOTOR_1  13
#define S_MOTOR_2  12
#define S_MOTOR_3   8
#define S_MOTOR_4   7

#define MotorFw 10
#define MotorDw  9

#define POS_SENSOR_1  4
#define POS_SENSOR_2  2
#define RESET_SENSOR  5

#define PULLDOWN_1   3   // jumper → pin 4
#define PULLDOWN_2   6   // jumper → pin 2
#define PULLDOWN_R  11   // jumper → pin 5

const int OPEN_POS  = 90;
const int CLOSE_POS =  0;
const unsigned long SERVO_OPEN_MS  = 400;
const unsigned long SENSOR_TIMEOUT = 8000;
const unsigned long DEBOUNCE_MS    = 50;

const int SERVO_PINS[NB_SERVOS] = { S_MOTOR_1, S_MOTOR_2, S_MOTOR_3, S_MOTOR_4 };
const char* CATEGORY_NAMES[NB_SERVOS] = { "canister", "sharps", "applicator", "inhaler" };

Servo servos[NB_SERVOS];
bool servoOpen[NB_SERVOS] = { false, false, false, false };
bool motorRunning = false;

// ── SENSOR STATES ────────────────────────────────────────────
bool s1Last    = LOW;
bool s2Last    = LOW;
bool resetLast = LOW;

unsigned long s1LastChange    = 0;
unsigned long s2LastChange    = 0;
unsigned long resetLastChange = 0;

// ── SETUP ────────────────────────────────────────────────────
void setup() {
  Serial.begin(9600);

  // Pulldowns
  pinMode(PULLDOWN_1, OUTPUT); digitalWrite(PULLDOWN_1, LOW);
  pinMode(PULLDOWN_2, OUTPUT); digitalWrite(PULLDOWN_2, LOW);
  pinMode(PULLDOWN_R, OUTPUT); digitalWrite(PULLDOWN_R, LOW);

  // Sensors
  pinMode(POS_SENSOR_1, INPUT);
  pinMode(POS_SENSOR_2, INPUT);
  pinMode(RESET_SENSOR, INPUT);

  // Motor
  pinMode(MotorFw, OUTPUT); digitalWrite(MotorFw, LOW);
  pinMode(MotorDw, OUTPUT); digitalWrite(MotorDw, LOW);

  // Servos
  for (int i = 0; i < NB_SERVOS; i++) {
    servos[i].attach(SERVO_PINS[i]);
    servos[i].write(CLOSE_POS);
  }

  Serial.println("=== Sorting System Ready ===");
}

// ── LOOP ─────────────────────────────────────────────────────
void loop() {
  readSensors();
  readSerial();
}

// ── SENSORS ──────────────────────────────────────────────────
void readSensors() {
  unsigned long now = millis();

  bool s1    = digitalRead(POS_SENSOR_1);
  bool s2    = digitalRead(POS_SENSOR_2);
  bool reset = digitalRead(RESET_SENSOR);

  // ── POS_SENSOR_1 ─────────────────────────────────────────
  if (s1 != s1Last && (now - s1LastChange) > DEBOUNCE_MS) {
    s1Last        = s1;
    s1LastChange  = now;

    if (s1 == HIGH) {
      Serial.println("SENSOR:1:TRIGGERED");
      for (int i = 0; i < 2; i++) {
        if (servoOpen[i]) {
          servos[i].write(CLOSE_POS);
          servoOpen[i] = false;
          Serial.print("SERVO:"); Serial.print(i + 1); Serial.println(":FORCED_CLOSE");
        }
      }
    } else {
      Serial.println("SENSOR:1:CLEAR");
    }
  }

  // ── POS_SENSOR_2 ─────────────────────────────────────────
  if (s2 != s2Last && (now - s2LastChange) > DEBOUNCE_MS) {
    s2Last       = s2;
    s2LastChange = now;

    if (s2 == HIGH) {
      Serial.println("SENSOR:2:TRIGGERED");
      for (int i = 2; i < 4; i++) {
        if (servoOpen[i]) {
          servos[i].write(CLOSE_POS);
          servoOpen[i] = false;
          Serial.print("SERVO:"); Serial.print(i + 1); Serial.println(":FORCED_CLOSE");
        }
      }
    } else {
      Serial.println("SENSOR:2:CLEAR");
    }
  }

  // ── RESET SENSOR ─────────────────────────────────────────
  if (reset != resetLast && (now - resetLastChange) > DEBOUNCE_MS) {
    resetLast       = reset;
    resetLastChange = now;

    if (reset == HIGH) {
      Serial.println("SENSOR:RESET:TRIGGERED");
    }
    // no CLEAR sent — Python doesn't need it
  }
}

// ── SERIAL ───────────────────────────────────────────────────
void readSerial() {
  if (!Serial.available()) return;

  String cmd = Serial.readStringUntil('\n');
  cmd.trim();

  if (cmd.startsWith("MOTOR:")) {
    String action = cmd.substring(6);
    if (action == "FORWARD") {
      digitalWrite(MotorFw, HIGH); digitalWrite(MotorDw, LOW);
      motorRunning = true;
      Serial.println("ACK:MOTOR:FORWARD");
    } else if (action == "STOP") {
      digitalWrite(MotorFw, LOW); digitalWrite(MotorDw, LOW);
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

  if (category == "unrecognized") {
    Serial.println("INFO:UNRECOGNIZED");
    return;
  }

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

// ── SERVO ────────────────────────────────────────────────────
void actuateServo(int idx) {
  servos[idx].write(OPEN_POS);
  servoOpen[idx] = true;
  Serial.print("SERVO:"); Serial.print(idx + 1); Serial.println(":OPEN");

  delay(SERVO_OPEN_MS);

  unsigned long start    = millis();
  bool          detected = false;
  int           sensorPin = (idx < 2) ? POS_SENSOR_1 : POS_SENSOR_2;

  while (millis() - start < SENSOR_TIMEOUT) {
    readSensors();   // ← keeps lastState in sync while blocked
    if (digitalRead(sensorPin) == HIGH) {
      detected = true;
      Serial.print("SERVO:"); Serial.print(idx + 1); Serial.println(":OBJECT_DETECTED");
      break;
    }
    delay(10);
  }

  servos[idx].write(CLOSE_POS);
  servoOpen[idx] = false;
  Serial.print("SERVO:"); Serial.print(idx + 1);
  Serial.println(detected ? ":CLOSED_OK" : ":CLOSED_TIMEOUT");
}