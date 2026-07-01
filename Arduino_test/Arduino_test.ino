#include "config.h"
#include <EEPROM.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include <string.h>

Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver();

const int   EEPROM_ADDR[NB_SERVOS]      = { 0, 1, 2, 3 };
const int   SERVO_CHANNELS[NB_SERVOS]   = { S_MOTOR_12, S_MOTOR_13, S_MOTOR_14, S_MOTOR_15 };
const char* CATEGORY_NAMES[NB_SERVOS]   = { "canister", "chemical", "applicator", "inhaler" };


int  servoPos[NB_SERVOS];
int  homePos[NB_SERVOS];
bool servoOpen[NB_SERVOS]  = {};
bool servoWired[NB_SERVOS] = {};
bool motorRunning           = false;

// Global actuation state
bool inActuation = false;


bool systemRunning      = false;
bool eStopActive        = false;
bool lastButtonState    = HIGH;
bool currentButtonState = HIGH;
unsigned long lastDebounceTime = 0;

bool uvOn                 = false;
bool lastUVButtonState    = HIGH;
bool currentUVButtonState = HIGH;
unsigned long lastUVDebounceTime = 0;

bool door1Closed = true, door2Closed = true;

struct Sensor {
  int           id;
  int           pin;
  bool          raw;
  bool          state;
  bool          triggered;
  unsigned long lastEdge;
};

Sensor sensors[1] = { { 1, POS_SENSOR_1, LOW, LOW, false, 0 } };

uint16_t angleToPulse(int angle) {
  angle = constrain(angle, 0, 180);
  angle = 180 - angle; // upside down servo
  return map(angle, 0, 180, SERVO_MIN, SERVO_MAX);
}

int getOpenPos(int idx) {
  return (idx < 2) ? OPEN_POS_LEFT : OPEN_POS_RIGHT;
}

void moveServo(int idx, int angle) {
  angle = constrain(angle, 0, 180);
  pwm.setPWM(SERVO_CHANNELS[idx], 0, angleToPulse(angle));
  servoPos[idx] = angle;
}


// UV INTERLOCK
void readDoorSwitches() {
  bool d1 = digitalRead(DOOR_SWITCH_1), d2 = digitalRead(DOOR_SWITCH_2);
  bool newDoor1Closed = (d1 == LOW), newDoor2Closed = (d2 == LOW);
  bool stateChanged = (newDoor1Closed != door1Closed) || (newDoor2Closed != door2Closed);

  door1Closed = newDoor1Closed;
  door2Closed = newDoor2Closed;

  if (!stateChanged) return;

  bool bothClosed = door1Closed && door2Closed;
  if (!bothClosed) {
    digitalWrite(UV_LAMP_PIN, LOW);
    Serial.println("ACK:UV:OFF:DOOR_OPEN");
  } else {
    digitalWrite(UV_LAMP_PIN, (systemRunning && uvOn) ? HIGH : LOW);
    Serial.println("ACK:UV:OFF:SWITCHED");
  }
}

// UV BUTTON
void readUVButton() {
  bool reading = digitalRead(UV_BUTTON_PIN);

  if (reading != currentUVButtonState) {
    lastUVDebounceTime   = millis();
    currentUVButtonState = reading;
  }

  if ((millis() - lastUVDebounceTime) > BUTTON_DEBOUNCE_MS) {
    if (currentUVButtonState == LOW && lastUVButtonState == HIGH) {
      if (systemRunning && door1Closed && door2Closed) {
        uvOn = !uvOn;
        digitalWrite(UV_LAMP_PIN, uvOn ? HIGH : LOW);
        Serial.println(uvOn ? "ACK:UV:ON" : "ACK:UV:OFF");
      } else {
        Serial.println("ACK:UV:BLOCKED");
      }
    }
    lastUVButtonState = currentUVButtonState;
  }
}

// SERVO WIRING CHECK
bool checkServoWired(int idx) {
  uint16_t pulse = angleToPulse(CLOSED_POS);
  // Send the servo PWM command
  pwm.setPWM(SERVO_CHANNELS[idx], 0, pulse);
  delay(20);
  uint16_t readOff = pwm.getPWM(SERVO_CHANNELS[idx], 1);
  // Read servo feedback and send faulty if not readable
  if (readOff < SERVO_CHECK_MIN_PULSE || readOff > SERVO_CHECK_MAX_PULSE) {
    Serial.println("ERR:SERVO:FAULT");
    return false;
  }
  return true;
}

// E-STOP READER
void readEStop() {
  bool safe = digitalRead(ESTOP_PIN);
  // If E-stop pressed/pulled turn on estop state and turn off everything else
  if (!safe && !eStopActive) {
    eStopActive   = true;
    systemRunning = false;
    motorRunning  = false;
    uvOn          = false;

    digitalWrite(MotorFw,     LOW);
    digitalWrite(UV_LAMP_PIN, LOW);

    // Clear actuation state immediately — safety takes priority
    inActuation = false;

    // Move each servo back to closed position
    for (int i = 0; i < NB_SERVOS; i++) {
      moveServo(i, CLOSED_POS);
      servoOpen[i] = false;
    }

    Serial.println("ESTOP:ACTIVE");
  }

  if (safe && eStopActive) {
    eStopActive = false;
    Serial.println("ESTOP:CLEARED");
  }
}

// MOTOR CONTROL
void startSystemMotor() {
  if (eStopActive) { Serial.println("ERR:ESTOP:ACTIVE"); return; }

  digitalWrite(MotorFw, HIGH);
  systemRunning = true;
  motorRunning  = true;

  if (door1Closed && door2Closed) {
    digitalWrite(UV_LAMP_PIN, uvOn ? HIGH : LOW);
  } else {
    digitalWrite(UV_LAMP_PIN, LOW);
    Serial.println("ACK:UV:OFF:DOOR_OPEN");
  }


}

void stopSystemMotor(bool closeServos) {
  systemRunning = false;
  motorRunning  = false;
  digitalWrite(MotorFw, LOW);

  uvOn = false;
  digitalWrite(UV_LAMP_PIN, LOW);
  Serial.println("ACK:UV:OFF");

  // Abort any pending actuation
  if (closeServos) {
    for (int i = 0; i < NB_SERVOS; i++) {
      moveServo(i, CLOSED_POS);
      servoOpen[i] = false;
    }
  }

  
}

// START/STOP BUTTON
void readStartStopButton() {
  bool reading = digitalRead(START_STOP_PIN);

  if (reading != currentButtonState) {
    lastDebounceTime   = millis();
    currentButtonState = reading;
  }

  if ((millis() - lastDebounceTime) > BUTTON_DEBOUNCE_MS) {
    if (currentButtonState == LOW && lastButtonState == HIGH) {
      if (!systemRunning) {
        startSystemMotor();
        Serial.println("ACK:SYSTEM:STARTED");
      } else {
        stopSystemMotor(false);
        Serial.println("ACK:SYSTEM:STOPPED");
      }
    }
    lastButtonState = currentButtonState;
  }
}

// SENSOR
void updateSensor(Sensor &s) {
  unsigned long now     = millis();
  bool          reading = digitalRead(s.pin);

  if (reading == s.raw) return;
  if ((now - s.lastEdge) < DEBOUNCE_MS) return;

  s.raw      = reading;
  s.lastEdge = now;

  if (reading == HIGH && s.state == LOW) {
    s.state     = HIGH;
    s.triggered = true;
    Serial.println("SENSOR:END:OBJECT_NOT_DETECTED");
  } else if (reading == LOW && s.state == HIGH) {
    s.state     = LOW;
    s.triggered = false;
  }
}

void readSensors() {
  updateSensor(sensors[0]);
}

// ACTUATION

enum ActuationState { ACT_IDLE, ACT_OPENING, ACT_WAITING_SENSOR, ACT_CLOSING };

ActuationState actState = ACT_IDLE;
int            actIdx   = -1;
unsigned long  actTimer = 0;

// Core servo actuation: open, wait for sensor, close
void startActuation(int idx) {
  // If a servo is currently open, close it immediately before starting the new one
  for (int i = 0; i < NB_SERVOS; i++) {
    if (servoOpen[i]) {
      moveServo(i, CLOSED_POS);
      servoOpen[i] = false;
    }
  }

  actIdx               = idx;
  actState             = ACT_OPENING;
  actTimer             = millis();
  sensors[0].triggered = false;

  int openPos = getOpenPos(idx);
  moveServo(idx, openPos);
  servoOpen[idx] = true;

  Serial.println("SERVO:" + String(idx + 1) + ":OPEN:" + String(openPos) +
                 ":CATEGORY:" + String(CATEGORY_NAMES[idx]) +
                 ":CHANNEL:"  + String(SERVO_CHANNELS[idx]));
}

void updateActuation() {
  if (actState == ACT_IDLE) return;

  // E-stop aborts everything immediately
  if (eStopActive) {
    actState    = ACT_IDLE;
    inActuation = false;
    return;
  }

  unsigned long now     = millis();
  unsigned long elapsed = now - actTimer;

  if (actState == ACT_OPENING) {
    if (elapsed >= SERVO_OPEN_MS) {
      actState = ACT_WAITING_SENSOR;
      actTimer = now;
    }
    return;
  }

  if (actState == ACT_WAITING_SENSOR) {
    // Wait for end-of-line sensor — used to log whether object was sorted
    // Servos 0-1 use TIMEOUT_1, servos 2-3 use TIMEOUT_2
    unsigned long timeout  = (actIdx == 0 || actIdx == 2) ? TIMEOUT_1 : TIMEOUT_2;
    bool          detected = sensors[0].triggered || (elapsed >= timeout);

    if (detected) {
      bool sorted = !sensors[0].triggered; // timed out = not detected = sorted
      Serial.println("SERVO:" + String(actIdx + 1) +
                     (sorted ? ":SORTED" : ":UNSORTED") +
                     ":CATEGORY:" + String(CATEGORY_NAMES[actIdx]) +
                     ":CHANNEL:"  + String(SERVO_CHANNELS[actIdx]));

      moveServo(actIdx, CLOSED_POS);
      servoOpen[actIdx] = false;
      actState          = ACT_CLOSING;
      actTimer          = now;
    }
    return;
  }

  if (actState == ACT_CLOSING) {
    // Small settling delay, then back to idle
    if (elapsed >= 50) {
      actState    = ACT_IDLE;
      inActuation = false;
    }
    return;
  }
}

// Entry point for all actuation from readSerial
void actuateServo(int idx) {
  inActuation = true;
  startActuation(idx);
}

// SERIAL PROTOCOL READER
void readSerial() {
  if (!Serial.available()) return;
  String rawCmd = Serial.readStringUntil('\n');
  rawCmd.replace("\r", "");
  rawCmd.trim();
  if (rawCmd.length() == 0) return;
  int sep = rawCmd.indexOf(':');
  if (sep <= 0) { Serial.println("ERR:SYSTEM:UNKNOWN_CMD"); return; }
  String key = rawCmd.substring(0, sep);
  String arg  = rawCmd.substring(sep + 1);
  key.trim(); arg.trim();
  key.toUpperCase(); arg.toUpperCase();

  // Read MOTOR:FORWARD and MOTOR:STOP
  if (key == "MOTOR") {
    if (arg == "FORWARD") {
      startSystemMotor();
      Serial.println("ACK:SYSTEM:STARTED");
    } else if (arg == "STOP") {
      stopSystemMotor(true);
      Serial.println("ACK:SYSTEM:STOPPED");
    } else {
      Serial.println("ERR:MOTOR:UNKNOWN:" + String(arg));
    }
    return;
  }
  if (eStopActive)    { Serial.println("ERR:ESTOP:ACTIVE"); return; }
  if (!systemRunning) { Serial.println("ERR:SYSTEM:IS_NOT_RUNNING"); return; }

  // Past this point serial key must be LABEL, unknown command otherwise
  if (key != "LABEL") { Serial.println("ERR:SYSTEM:UNKNOWN_CMD"); return; }

  String category = arg;
  category.toLowerCase();

  int idx = -1;
  for (int i = 0; i < NB_SERVOS; i++) {
    if (category == CATEGORY_NAMES[i]) { idx = i; break; }
  }
  // Return an error if the category arg is not recognised
  if (idx == -1) {
    Serial.println("ERR:BAD_CATEGORY:" + String(category)); return;
  }
  // Return an error if the servo is not wired
  if (!servoWired[idx]) {
    Serial.println("ERR:SERVO:" + String(idx + 1) + ":NOT_WIRED:CATEGORY:" + String(CATEGORY_NAMES[idx]));
    return;
  }
  // Acknowledge and actuate
  Serial.println("ACK:LABEL:" + String(category));
  actuateServo(idx);
}

void setup() {
  Serial.begin(115200);
  pwm.begin();
  pwm.setPWMFreq(50);
  delay(10);

  pinMode(PULLDOWN_1, OUTPUT); digitalWrite(PULLDOWN_1, LOW);
  pinMode(PULLDOWN_2, OUTPUT); digitalWrite(PULLDOWN_2, LOW);
  pinMode(PULLDOWN_R, OUTPUT); digitalWrite(PULLDOWN_R, LOW);

  pinMode(POS_SENSOR_1,    INPUT);
  digitalWrite(MotorFw,         LOW); pinMode(MotorFw,         OUTPUT);
  digitalWrite(UV_LAMP_PIN,     LOW); pinMode(UV_LAMP_PIN,     OUTPUT);
  pinMode(UV_BUTTON_PIN,   INPUT_PULLUP);
  pinMode(START_STOP_PIN,  INPUT_PULLUP);
  pinMode(ESTOP_PIN,       INPUT_PULLUP);
  pinMode(DOOR_SWITCH_1,   INPUT_PULLUP);
  pinMode(DOOR_SWITCH_2,   INPUT_PULLUP);

  for (int i = 0; i < NB_SERVOS; i++) {
    homePos[i]    = CLOSED_POS;
    servoPos[i]   = CLOSED_POS;
    moveServo(i, CLOSED_POS);
    servoWired[i] = checkServoWired(i);
    if (servoWired[i]) {
      Serial.println("SERVO:" + String(i + 1) + ":INIT:CLOSED:" + String(CLOSED_POS));
    } else {
      Serial.print("ERR:SERVO:" + String(i + 1) + ":NOT_WIRED:CATEGORY:" + String(CATEGORY_NAMES[i]));
    }
  }

  Serial.println("========= Sorting System Ready =========");
}

void loop() {
  readEStop();
  readStartStopButton();
  readUVButton();
  readDoorSwitches();
  readSensors();
  updateActuation();
  readSerial();
}
