#include "config.h"          // Pin definitions and constants
#include <EEPROM.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver();

const int   EEPROM_ADDR[NB_SERVOS]      = { 0, 1, 2, 3 };
const int   SERVO_CHANNELS[NB_SERVOS]   = { S_MOTOR_1, S_MOTOR_2, S_MOTOR_3, S_MOTOR_4 };
const char* CATEGORY_NAMES[NB_SERVOS]   = { "canister", "chemical", "applicator", "inhaler" };

int  servoPos[NB_SERVOS];
int  homePos[NB_SERVOS];
bool servoOpen[NB_SERVOS]   = {};
bool servoWired[NB_SERVOS]  = {};
bool motorRunning = false;
bool inActuation  = false;
bool MotorFeedback = false;
bool FeedbackRead = false;

bool systemRunning      = false;
bool eStopActive        = false;
bool lastButtonState    = HIGH;
bool currentButtonState = HIGH;
unsigned long lastDebounceTime = 0;

// ── UV BUTTON STATE ───────────────────────────────────────────
bool uvOn                 = false;
bool lastUVButtonState    = HIGH;
bool currentUVButtonState = HIGH;
unsigned long lastUVDebounceTime = 0;
// ─────────────────────────────────────────────────────────────

// ── DOOR SWITCH STATE ─────────────────────────────────────────
bool door1Closed = true, door2Closed = true;

struct Sensor {
  int           id;
  int           pin;
  bool          raw;
  bool          state;
  bool          triggered;
  unsigned long lastEdge;
};

Sensor sensors[1] = {  { 1, POS_SENSOR_1, LOW, LOW, false, 0 }};

// ── HELPERS ──────────────────────────────────────────────────
uint16_t angleToPulse(int angle) {
  angle = constrain(angle, 0, 180);
  angle = 180 - angle;
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

// ── ORANGE LAMP ───────────────────────────────────────────────
void updateOrangeLamp() {
  digitalWrite(ORANGE_LAMP_PIN, (!systemRunning && !eStopActive) ? HIGH : LOW);
}

// -- READ MOTOR FEEDBACK (if wired) ───────────────────────────────────
void readMotorFeedback(String action = "") {
  MotorFeedback = (digitalRead(MotorFb) == HIGH);

  if (MotorFeedback) {
    if (!eStopActive && action == "FORWARD") {
      motorRunning = true;
      systemRunning = true;
      Serial.println("ACK:MOTOR:FORWARD");
      FeedbackRead = true;
    }
    else if (action == "STOP") {
      motorRunning = false;
      systemRunning = false;
      Serial.println("ERR:MOTOR:FEEDBACK_MISMATCH");
    }
  }
  else {
    if (!eStopActive && action == "FORWARD") {
      motorRunning = true;
      systemRunning = true;
      Serial.println("ERR:MOTOR:FEEDBACK_MISMATCH");
    }
    else if (action == "STOP") {
      motorRunning = false;
      systemRunning = false;
      Serial.println("ACK:MOTOR:STOP");
      FeedbackRead = true;
    }
  }
}
// ── DOOR SWITCH UPDATE ────────────────────────────────────────
// Called every loop. If either door opens → cut UV immediately.
// If both doors close again → restore UV only if systemRunning
// and uvOn are both true (button state is preserved).
void readDoorSwitches() {
  bool d1 = digitalRead(DOOR_SWITCH_1), d2 = digitalRead(DOOR_SWITCH_2);  // HIGH = closed, LOW = open
  bool newDoor1Closed = (d1 == HIGH)  , newDoor2Closed = (d2 == HIGH); 

  bool stateChanged = (newDoor1Closed != door1Closed) || (newDoor2Closed != door2Closed);

  door1Closed = newDoor1Closed;
  door2Closed = newDoor2Closed;

  if (!stateChanged) return;

  bool bothClosed = door1Closed && door2Closed;

  if (!bothClosed) {
    // At least one door open → force UV off immediately
    digitalWrite(UV_LAMP_PIN, LOW);
    Serial.println("ACK:UV:OFF:DOOR_OPEN");
  } else {
    // Both doors closed → restore UV only if system running and button was ON
    digitalWrite(UV_LAMP_PIN, (systemRunning && uvOn) ? HIGH : LOW);
  }
}

// ── UV BUTTON ────────────────────────────────────────────────
// Blocked entirely when system is not running.
// UV lamp is forced OFF when system stops (see stopSystemMotor).
void readUVButton() {
  bool reading = digitalRead(UV_BUTTON_PIN);

  if (reading != currentUVButtonState) {
    lastUVDebounceTime   = millis();
    currentUVButtonState = reading;
  }

  if ((millis() - lastUVDebounceTime) > BUTTON_DEBOUNCE_MS) {
    if (currentUVButtonState == LOW && lastUVButtonState == HIGH) {// falling edge -> button pressed
      // Only toggle UV if system is running
      if (systemRunning && door1Closed && door2Closed) {
        uvOn = !uvOn;
        digitalWrite(UV_LAMP_PIN, uvOn ? HIGH : LOW);
        Serial.println(uvOn ? "ACK:UV:ON" : "ACK:UV:OFF");
      }
      // If the system is not running, the pressed button is ignored
    }
    lastUVButtonState = currentUVButtonState;
  }
}

// ── SERVO WIRING CHECK ───────────────────────────────────────
bool checkServoWired(int idx) {
  uint16_t pulse = angleToPulse(CLOSED_POS);
  if (pulse < SERVO_CHECK_MIN_PULSE || pulse > SERVO_CHECK_MAX_PULSE) {
    Serial.println("ERR:SERVO:" + String(idx + 1) + (":WIRING:PULSE_OUT_OF_RANGE:" + String(pulse)));
    return false;
  }
  pwm.setPWM(SERVO_CHANNELS[idx], 0, pulse);
  delay(20);
  uint16_t readOff = pwm.getPWM(SERVO_CHANNELS[idx], 1);
  if (readOff < SERVO_CHECK_MIN_PULSE || readOff > SERVO_CHECK_MAX_PULSE) {
    Serial.println("ERR:SERVO:" + String(idx + 1) + (":WIRING:READBACK_FAILED:EXPECTED:" + String(pulse) + ":GOT:" + String(readOff)));
    return false;
  }
  return true;
}

// ── E-STOP ───────────────────────────────────────────────────
void readEStop() {
  bool safe = digitalRead(ESTOP_PIN);   // HIGH = safe, LOW = E-stop
  if (!safe && !eStopActive) {
    // ── Falling edge: E-stop just activated ──────────────────
    eStopActive   = true;
    systemRunning = false;
    motorRunning  = false;

    digitalWrite(MotorFw,    LOW);

    // Close all servos immediately, even mid-actuation
    inActuation = false;
    for (int i = 0; i < NB_SERVOS; i++) {
      moveServo(i, CLOSED_POS);
      servoOpen[i] = false;
    }

    Serial.println("ESTOP:ACTIVE");
  }

  if (safe && eStopActive) {
    // ── Rising edge: E-stop cleared ──────────────────────────
    eStopActive = false;
    Serial.println("ESTOP:CLEARED");
    // System stays stopped — operator must press Start or send
    // MOTOR:FORWARD to resume. This is intentional.
  }
}

// ── MOTOR CONTROL ────────────────────────────────────────────
void startSystemMotor() {
  
  if (eStopActive) {
    Serial.println("ERR:ESTOP:ACTIVE");
    return;
  }
  digitalWrite(MotorFw, HIGH);
  unsigned long t0 = millis();
  while (millis() - t0 < 500) {
    readMotorFeedback("FORWARD");
    readEStop();
    if (FeedbackRead == true) {
      FeedbackRead = false;
      break;
    }
    if (eStopActive) break;
  }
  if (!eStopActive) {
    systemRunning = true;
    motorRunning  = true;
    if (door1Closed && door2Closed) {
      digitalWrite(UV_LAMP_PIN, uvOn ? HIGH : LOW);
    } else {
      digitalWrite(UV_LAMP_PIN, LOW);
      Serial.println("ACK:UV:OFF:DOOR_OPEN");
    }
  }
  updateOrangeLamp();
}

void stopSystemMotor(bool closeServos) {
  systemRunning = false;
  motorRunning = false;
  digitalWrite(MotorFw, LOW);
  unsigned long t0 = millis();
  while (millis() - t0 < 500) {
    readMotorFeedback("STOP");
    readEStop();
    if (FeedbackRead == true) {
      FeedbackRead = false;
      break;
    }
    if (eStopActive) break;
  }
  // Force UV off when system stops, button is also blocked from now on
  uvOn = false;
  digitalWrite(UV_LAMP_PIN, LOW);
  Serial.println("ACK:UV:OFF");

  if (closeServos) {
    for (int i = 0; i < NB_SERVOS; i++) {
      moveServo(i, CLOSED_POS);
      servoOpen[i] = false;
    }
  }
  updateOrangeLamp();
}

// ── START/STOP BUTTON ────────────────────────────────────────
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

void setup() {
  Serial.begin(115200);
  pwm.begin();
  pwm.setPWMFreq(50);
  delay(10);

  pinMode(PULLDOWN_1, OUTPUT); digitalWrite(PULLDOWN_1, LOW);
  pinMode(PULLDOWN_2, OUTPUT); digitalWrite(PULLDOWN_2, LOW);
  pinMode(PULLDOWN_R, OUTPUT); digitalWrite(PULLDOWN_R, LOW);

  pinMode(POS_SENSOR_1, INPUT);

  pinMode(MotorFw,    OUTPUT); digitalWrite(MotorFw,    LOW);
  pinMode(MotorFb,    INPUT);

  pinMode(ORANGE_LAMP_PIN, OUTPUT); digitalWrite(ORANGE_LAMP_PIN, HIGH);
  pinMode(UV_LAMP_PIN,     OUTPUT); digitalWrite(UV_LAMP_PIN,     LOW);
  pinMode(UV_BUTTON_PIN,   INPUT_PULLUP);

  pinMode(START_STOP_PIN, INPUT_PULLUP);
  pinMode(ESTOP_PIN,      INPUT_PULLUP);

  // Door switches
  pinMode(DOOR_SWITCH_1, INPUT_PULLUP);
  pinMode(DOOR_SWITCH_2, INPUT_PULLUP);

  for (int i = 0; i < NB_SERVOS; i++) {
    homePos[i]  = CLOSED_POS;
    servoPos[i] = CLOSED_POS;
    moveServo(i, CLOSED_POS);
    servoWired[i] = checkServoWired(i);
    if (servoWired[i]) {
      Serial.print("SERVO:"); Serial.print(i + 1);
      Serial.print(":INIT:CLOSED:"); Serial.println(CLOSED_POS);
    } else {
      Serial.print("ERR:SERVO:"); Serial.print(i + 1);
      Serial.print(":NOT_WIRED:CATEGORY:"); Serial.println(CATEGORY_NAMES[i]);
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

void updateSensor(Sensor &s) {
  unsigned long now     = millis();
  bool          reading = digitalRead(s.pin);

  if (reading == s.raw) return;// No change in reading -> ignore
  if ((now - s.lastEdge) < DEBOUNCE_MS) return;// Debounce -> ignore changes

  s.raw      = reading;
  s.lastEdge = now;

  if (reading == HIGH && s.state == LOW) {// Rising edge → object detected by sensor
    s.state     = HIGH;
    s.triggered = true;
    Serial.print("SENSOR:"); Serial.print(s.id); Serial.println(":TRIGGERED"); Serial.println("SENSOR: OBJECT_NOT_DETECTED");

  } else if (reading == LOW && s.state == HIGH) { // Falling edge → object left the sensor
    s.state     = LOW;
    s.triggered = false;
  }
}

void readSensors() {
  updateSensor(sensors[0]);
}

void readSerial() {
  if (!Serial.available()) return;

  String rawCmd = Serial.readStringUntil('\n');
  rawCmd.replace("\r", "");
  rawCmd.trim();
  if (rawCmd.length() == 0) return;

  int sep = rawCmd.indexOf(':');

  if (sep <= 0) { Serial.println("ERR:SYSTEM:UNKNOWN_CMD"); return; }

// Check if the command readed command are correct 
  String key = rawCmd.substring(0, sep);
  String arg = rawCmd.substring(sep + 1);
  key.trim(); arg.trim();
  key.toUpperCase();


  // MOTOR:STOP can always run — move it before all guards
  if (key == "MOTOR" && arg == "STOP") {
    stopSystemMotor(true);
    return;
  }

  // Now the safety guards
  if (eStopActive)    { Serial.println("ERR:ESTOP:ACTIVE");          return; }
  if (!systemRunning) { Serial.println("ERR:SYSTEM:IS_NOT_RUNNING"); return; }

  // MOTOR:FORWARD needs the system not estopped (handled inside startSystemMotor already)
  if (key == "MOTOR") {
    if (arg == "FORWARD") {
      startSystemMotor();
      Serial.println("ACK:SYSTEM:STARTED");
    } else {
      Serial.println("ERR:MOTOR:UNKNOWN:" + String(arg)); // Probably unwired motor once feedback wired (to be added)
    }
    return;
  }

  if (key != "LABEL") { Serial.println("ERR:SYSTEM:UNKNOWN_CMD"); return; }  // beyond this point the key is LABEL

  String category = arg; category.toLowerCase(); //lowercase label category name to avoid case sensitivity issues

  // Find servo index for the given category return error if not found

  int idx = -1;
  for (int i = 0; i < NB_SERVOS; i++) {
    if (category == CATEGORY_NAMES[i]) { idx = i; break; }
  }
  if (idx == -1) { Serial.println("ERR:BAD_CATEGORY:"+ String(category)); return; }

// Check if the servo for the category is wired before actuating print error otherwise

  if (!servoWired[idx]) {
    Serial.println("ERR:SERVO:" + String(idx + 1) + (":NOT_WIRED:CATEGORY:")+ String(CATEGORY_NAMES[idx]));
    return;
  }
  Serial.println("ACK:LABEL:" + String(category)); // aknoledged anyway to shown which category is being system 
  actuateServo(idx);
}

void actuateServo(int idx) {
  if (inActuation) return;
  inActuation = true;
  Sensor &s = sensors[0];
  s.triggered = false;
  int openPos = getOpenPos(idx);// return oppen position based on the servo index (left or right)

  moveServo(idx, openPos);
  servoOpen[idx] = true;
  //SERVO:X:OPEN:Y:CATEGORY:<category>:CHANNEL:Z
  Serial.println("SERVO:" + String(idx + 1) + ":OPEN:" + String(openPos) + ":CATEGORY:" + String(CATEGORY_NAMES[idx]) + ":CHANNEL:" + String(SERVO_CHANNELS[idx]));

  delay(SERVO_OPEN_MS);

  unsigned long start    = millis();
  bool detected = false;

// Wait for the sensor trigger or timeout to check if the object was detected in front of the door.
// During this time, no new actuation can start to avoid multiple triggers from the same object
// and to let the servo close properly.

 const unsigned long TIMEOUT = (idx < 2) ? TIMEOUT_1 : TIMEOUT_2; // use different timeouts for the 2 zones since the 2nd zone is further and the object may take more time to reach it
  while (millis() - start < TIMEOUT) {
    readEStop();
    if (eStopActive){
      detected = true;
      break;
    }
    updateSensor(s); // update the sensor state during the wait
    if (s.triggered) {
      detected = true;
      break;
    }
  }
  moveServo(idx, CLOSED_POS);
  servoOpen[idx] = false;
  inActuation    = false;

  //SERVO:X:CLOSED:CATEGORY:<category>:CHANNEL:Z
  Serial.println("SERVO:" + String(idx + 1) + (detected ? ":UNSORTED" : ":SORTED") + ":CATEGORY:" + String(CATEGORY_NAMES[idx]) + ":CHANNEL:" + String(SERVO_CHANNELS[idx]));
}
