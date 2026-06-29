#include "config.h"
#include <EEPROM.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include <string.h>

Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver();

const int   EEPROM_ADDR[NB_SERVOS]      = { 0, 1, 2, 3 };
const int   SERVO_CHANNELS[NB_SERVOS]   = { S_MOTOR_12, S_MOTOR_13, S_MOTOR_14, S_MOTOR_15 };
const char* CATEGORY_NAMES[NB_SERVOS]   = { "canister", "chemical", "applicator", "inhaler" };

// Zone 1 = canister (0) + applicator (2) — upstream, right side
// Zone 2 = chemical (1) + inhaler (3)    — downstream, left side
const int ZONE[NB_SERVOS] = { 1, 2, 1, 2 };

// Overlap wait before closing current and opening next in same zone
const unsigned long OVERLAP_Z1 = 500;
const unsigned long OVERLAP_Z2 = 3000;

int  servoPos[NB_SERVOS];
int  homePos[NB_SERVOS];
bool servoOpen[NB_SERVOS]  = {};
bool servoWired[NB_SERVOS] = {};
bool motorRunning           = false;

// Per-zone actuation state — needed because Z2 active + Z1 new is a free case
// where both zones can operate independently at the same time
bool inActuationZ1 = false;
bool inActuationZ2 = false;

// Per-zone queued label (-1 = empty)
// Max depth 1 per zone — conveyor spacing makes deeper queue unnecessary
int queuedIdxZ1 = -1;
int queuedIdxZ2 = -1;

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
  angle = 180 - angle; //upside down servo
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

bool isZone1(int idx) { return ZONE[idx] == 1; }//  upstream zone
bool isZone2(int idx) { return ZONE[idx] == 2; }//  downstrem zone

// Returns true if the zone of idx is currently in actuation
bool zoneActive(int idx) {
  return isZone1(idx) ? inActuationZ1 : inActuationZ2;
}

// Returns the currently open servo index in a zone (-1 if none)
int activeServoInZone(int zone) {
  for (int i = 0; i < NB_SERVOS; i++) {
    if (ZONE[i] == zone && servoOpen[i]) return i;
  }
  return -1;
}
//return orange lanp status
void updateOrangeLamp() {
  digitalWrite(ORANGE_LAMP_PIN, (!systemRunning && !eStopActive) ? HIGH : LOW);
}
//UV INTERLOCK
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

//SERVO WIRING CHECK 
bool checkServoWired(int idx) {
  uint16_t pulse = angleToPulse(CLOSED_POS);  
  // send the servo PWN command
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
  // if E-stop pressed/pulled turn on estop state and turn off everyything else (only software since the current already got physically disconnected)
  if (!safe && !eStopActive) {
    eStopActive   = true;
    systemRunning = false;
    motorRunning  = false;
    uvOn          = false;

    digitalWrite(MotorFw,     LOW);
    digitalWrite(UV_LAMP_PIN, LOW);

    // Close everything immediately queues are voided because safety takes the priority
    inActuationZ1 = false;
    inActuationZ2 = false;
    queuedIdxZ1   = -1;
    queuedIdxZ2   = -1;
    //move each servo back to close position, although command will be physicaly done on E-stop clear 
    for (int i = 0; i < NB_SERVOS; i++) {
      moveServo(i, CLOSED_POS);
      servoOpen[i] = false;
    }
    //print for log status and dashboard status 
    Serial.println("ESTOP:ACTIVE");
  }

  if (safe && eStopActive) {
    eStopActive = false;
    Serial.println("ESTOP:CLEARED");
  }
}

//MOTOR CONTROL 
void startSystemMotor() {
  //not procedded if e-stop active therefore send error for debugging
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

  updateOrangeLamp();
}

void stopSystemMotor(bool closeServos) {
  systemRunning = false;
  motorRunning  = false;
  digitalWrite(MotorFw, LOW);

  uvOn = false;
  digitalWrite(UV_LAMP_PIN, LOW);
  Serial.println("ACK:UV:OFF");

  // delete the queues when system stopped so pending actuations are aborted
  queuedIdxZ1 = -1;
  queuedIdxZ2 = -1;

  if (closeServos) {
    for (int i = 0; i < NB_SERVOS; i++) {
      moveServo(i, CLOSED_POS);
      servoOpen[i] = false;
    }
  }

  updateOrangeLamp();
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

//ACTUATION 

// Shared overlap wait that keeps checking E-stop so safety is never blocked during the delay
bool overlapWait(unsigned long ms) {
  unsigned long start = millis();
  while (millis() - start < ms) {
    readEStop();
    if (eStopActive) return false;
    delay(10);
  }
  return true;
}

// Core servo actuation open, wait for sensor, close
// Called after any overlap handling is done
void runServo(int idx) {
  Sensor &s  = sensors[0];
  s.triggered = false;
  int openPos = getOpenPos(idx);

  moveServo(idx, openPos);
  servoOpen[idx] = true;
  Serial.println("SERVO:" + String(idx + 1) + ":OPEN:" + String(openPos) +
                 ":CATEGORY:" + String(CATEGORY_NAMES[idx]) +
                 ":CHANNEL:"  + String(SERVO_CHANNELS[idx]));

  delay(SERVO_OPEN_MS);

  // Wait for end-of-line sensor — only used to log whether object was sorted
  unsigned long start   = millis();
  bool          detected = false;
  unsigned long timeout  = isZone2(idx) ? TIMEOUT_2 : TIMEOUT_1;

  while (millis() - start < timeout) {
    readEStop();
    if (eStopActive) { detected = true; break; }
    updateSensor(s);
    if (s.triggered) { detected = true; break; }
  }

  moveServo(idx, CLOSED_POS);
  servoOpen[idx] = false;

  Serial.println("SERVO:" + String(idx + 1) +
                 (detected ? ":UNSORTED" : ":SORTED") +
                 ":CATEGORY:" + String(CATEGORY_NAMES[idx]) +
                 ":CHANNEL:"  + String(SERVO_CHANNELS[idx]));
}

// Handles all zone logic before delegating to runServo
// This is the only entry point for actuation from readSerial
void actuateServo(int idx) {
  int  zone        = ZONE[idx];
  bool &inActZone  = (zone == 1) ? inActuationZ1 : inActuationZ2;
  int  &queuedZone = (zone == 1) ? queuedIdxZ1   : queuedIdxZ2;

  int  otherZone        = (zone == 1) ? 2 : 1;
  bool &inActOtherZone  = (zone == 1) ? inActuationZ2 : inActuationZ1;
  int  &queuedOtherZone = (zone == 1) ? queuedIdxZ2   : queuedIdxZ1;

  //CASE: when the same zone is already active 
  if (inActZone) {
    // if there is a queued zone, do nothing
    if (queuedZone != -1) { return;}
    // set the queued zone to the current zone if there are no already active object
    queuedZone = idx;
    return;
  }
  // CASE: when the opposite zone is active (Z1 new, Z2 active or Z2 new, Z1 active) 
  if (inActOtherZone) {
    if (zone == 1) {
      // Z2 active + Z1 new physically no overlap so both run freely
      // Z1 actuation starts without waiting for Z2 to finish
      inActZone = true;
      runServo(idx);
      inActZone = false;

      // Execute Z1 queue if one was waiting
      if (queuedZone != -1 && !eStopActive) {
        int next    = queuedZone;
        queuedZone  = -1;
        unsigned long ov = OVERLAP_Z1;
        if (overlapWait(ov)) {
          runServo(next);
        }
      }
      return;
    } else {
      // Z1 active + Z2 new then Z1 is upstream so we close it and drop any Z1 queued  before opening any Z2 servo
      int activeZ1 = activeServoInZone(1);
      if (queuedOtherZone != -1) {
        queuedOtherZone = -1;
      }
      if (activeZ1 != -1) {
        moveServo(activeZ1, CLOSED_POS);
        servoOpen[activeZ1] = false;
        inActOtherZone = false;
      }
      // Now open Z2 normally
      inActZone = true;
      runServo(idx);
      inActZone = false;

      if (queuedZone != -1 && !eStopActive) {
        int next   = queuedZone;
        queuedZone = -1;
        if (overlapWait(OVERLAP_Z2)) {
          runServo(next);
        }
      }
      return;
    }
  }
  // CASE zone free then normal actuation 
  inActZone = true;
  runServo(idx);
  // After closing, we check if a same-zone object was queued during actuation
  while (queuedZone != -1 && !eStopActive) {
    int next   = queuedZone;
    queuedZone = -1;
    unsigned long ov = (zone == 1) ? OVERLAP_Z1 : OVERLAP_Z2;
    if (!overlapWait(ov)) break; // E-stop fired during overlap wait
    runServo(next);
  }
  inActZone = false;
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

   //read MOTOR:FORWARD and MOTOR:STOP
  if (key == "MOTOR") {
    if (arg == "FORWARD") {
      startSystemMotor();
      Serial.println("ACK:SYSTEM:STARTED");
    } else if (arg =="STOP"){
      stopSystemMotor(true);
      Serial.println("ACK:SYSTEM:STOPPED");
    } else {
      Serial.println("ERR:MOTOR:UNKNOWN:" + String(arg));
    }
    return;
  }
  if (eStopActive)    { Serial.println("ERR:ESTOP:ACTIVE"); return; }
  if (!systemRunning) { Serial.println("ERR:SYSTEM:IS_NOT_RUNNING"); return; }

  //past this point serial key must be LABEL , unknow command otherwise 
  if (key != "LABEL") { Serial.println("ERR:SYSTEM:UNKNOWN_CMD"); return; }

  String category = arg;
  category.toLowerCase();

  int idx = -1;
  for (int i = 0; i < NB_SERVOS; i++) {
    if (category == CATEGORY_NAMES[i]) { idx = i; break; }
  }
  //return an error CATEGORY if the categorie arg is not recognized
  if (idx == -1) {
    Serial.println("ERR:BAD_CATEGORY:" + String(category)); return; 
  }
  //return an error if any servo is not wired
  if (!servoWired[idx]) {
    Serial.println("ERR:SERVO:" + String(idx + 1) + ":NOT_WIRED:CATEGORY:" + String(CATEGORY_NAMES[idx]));
    return;
  }
  //if no error triggerd then feedback showcase acknoledgement 
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
  digitalWrite(ORANGE_LAMP_PIN, HIGH);pinMode(ORANGE_LAMP_PIN, OUTPUT); 
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
  updateOrangeLamp();
  readSensors();
  readSerial();
}