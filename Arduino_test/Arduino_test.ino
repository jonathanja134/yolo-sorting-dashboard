#include <EEPROM.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver();

// ── CONFIG ───────────────────────────────────────────────────
#define NB_SERVOS 4

#define S_MOTOR_1  12
#define S_MOTOR_2  13
#define S_MOTOR_3  14
#define S_MOTOR_4  15

#define MotorFw 10

#define POS_SENSOR_1  4
#define POS_SENSOR_2  2
#define RESET_SENSOR  5

#define PULLDOWN_1   7
#define PULLDOWN_2   6
#define PULLDOWN_R  11

//Switch UV-C door
#define DOOR_SWITCH_1 12 
#define DOOR_SWITCH_2  13

// ── START/STOP BUTTON ────────────────────────────────────────
#define START_STOP_PIN     8
#define BUTTON_DEBOUNCE_MS 50

// ── E-STOP ───────────────────────────────────────────────────
#define ESTOP_PIN 12

// ── ORANGE LAMP ──────────────────────────────────────────────
// ON when system stopped + e-stop NOT active
#define ORANGE_LAMP_PIN 13

// ── UV BUTTON + UV LAMP ──────────────────────────────────────
// UV button only works when systemRunning = true
// UV lamp turns OFF automatically when system stops
#define UV_BUTTON_PIN  3
#define UV_LAMP_PIN    9
// ─────────────────────────────────────────────────────────────

#define SERVO_MIN 150
#define SERVO_MAX 600

#define CLOSED_POS      120
#define OPEN_POS_LEFT    80
#define OPEN_POS_RIGHT  160

#define SERVO_CHECK_MIN_PULSE  100
#define SERVO_CHECK_MAX_PULSE  650

const unsigned long SERVO_OPEN_MS  = 500;
const unsigned long SENSOR_TIMEOUT = 400;
const unsigned long DEBOUNCE_MS    = 50;

const int   EEPROM_ADDR[NB_SERVOS]      = { 0, 1, 2, 3 };
const int   SERVO_CHANNELS[NB_SERVOS]   = { S_MOTOR_1, S_MOTOR_2, S_MOTOR_3, S_MOTOR_4 };
const char* CATEGORY_NAMES[NB_SERVOS]   = { "canister", "chemical", "applicator", "inhaler" };

const int MotorOnLED = 3;
int  servoPos[NB_SERVOS];
int  homePos[NB_SERVOS];
bool servoOpen[NB_SERVOS]   = {};
bool servoWired[NB_SERVOS]  = {};
bool motorRunning = false;
bool inActuation  = false;

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
bool door1Closed = true;
bool door2Closed = true;

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

// ── DOOR SWITCH UPDATE ────────────────────────────────────────
// Called every loop. If either door opens → cut UV immediately.
// If both doors close again → restore UV only if systemRunning
// and uvOn are both true (button state is preserved).
void readDoorSwitches() {
  bool d1 = digitalRead(DOOR_SWITCH_1);  // HIGH = closed, LOW = open
  bool d2 = digitalRead(DOOR_SWITCH_2);

  door1Closed = (d1 == HIGH);
  door2Closed = (d2 == HIGH);

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

// ── UV BUTTONblblbl ────────────────────────────────────────────────
// Blocked entirely when system is not running.
// UV lamp is forced OFF when system stops (see stopSystemMotor).
void readUVButton() {
  bool reading = digitalRead(UV_BUTTON_PIN);

  if (reading != currentUVButtonState) {
    lastUVDebounceTime   = millis();
    currentUVButtonState = reading;
  }

  if ((millis() - lastUVDebounceTime) > BUTTON_DEBOUNCE_MS) {
    if (currentUVButtonState == LOW && lastUVButtonState == HIGH) {

      // Only toggle UV if system is running
      if (systemRunning) {
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
    Serial.print("ERR:SERVO:"); Serial.print(idx + 1);
    Serial.print(":WIRING:PULSE_OUT_OF_RANGE:"); Serial.println(pulse);
    return false;
  }
  pwm.setPWM(SERVO_CHANNELS[idx], 0, pulse);
  delay(20);
  uint16_t readOn  = pwm.getPWM(SERVO_CHANNELS[idx], 0);
  uint16_t readOff = pwm.getPWM(SERVO_CHANNELS[idx], 1);
  if (readOff < SERVO_CHECK_MIN_PULSE || readOff > SERVO_CHECK_MAX_PULSE) {
    Serial.print("ERR:SERVO:"); Serial.print(idx + 1);
    Serial.print(":WIRING:READBACK_FAILED:EXPECTED:");
    Serial.print(pulse);
    Serial.print(":GOT:"); Serial.println(readOff);
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
    digitalWrite(MotorOnLED, LOW);

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
  digitalWrite(MotorFw,    HIGH);
  digitalWrite(MotorOnLED, HIGH);
  motorRunning  = true;
  systemRunning = true;
  updateOrangeLamp();
}

void stopSystemMotor(bool closeServos) {
  digitalWrite(MotorFw,    LOW);
  digitalWrite(MotorOnLED, LOW);
  motorRunning  = false;
  systemRunning = false;

  // Force UV off when system stops — button is also blocked from now on
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
  pinMode(POS_SENSOR_2, INPUT);
  pinMode(RESET_SENSOR, INPUT);

  pinMode(MotorFw,    OUTPUT); digitalWrite(MotorFw,    LOW);
  pinMode(MotorOnLED, OUTPUT); digitalWrite(MotorOnLED, LOW);

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

  Serial.println("=== Sorting System Ready ===");
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

    if (!inActuation) { // If not currently actuating, force to close any open servos in this group.
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

void readSerial() {
  if (!Serial.available()) return;

  String rawCmd = Serial.readStringUntil('\n');
  rawCmd.replace("\r", "");
  rawCmd.trim();
  if (rawCmd.length() == 0) return;

  int sep = rawCmd.indexOf(':');

// Check if the command readed command are correct 
  String key = rawCmd.substring(0, sep);
  String arg = rawCmd.substring(sep + 1);
  key.trim(); arg.trim();
  key.toUpperCase();

  if (sep <= 0)       { Serial.println("ERR:SYSTEM:UNKNOWN_CMD");            return; }
  if (key != "LABEL") { Serial.println("ERR:SYSTEM:UNKNOWN_CMD");            return; }

// Check if the system is in a state to accept commands

  if (eStopActive)    { Serial.println("ERR:ESTOP:ACTIVE");           return; }
  if (!systemRunning) { Serial.println("ERR:SYSTEM:IS_NOT_RUNNING");  return; }

  
  // Handle MOTOR commands first since it use a different format

  if (key == "MOTOR") {
    arg.toUpperCase();
    if (arg == "FORWARD") {
      startSystemMotor();
      if (!eStopActive) Serial.println("ACK:MOTOR:FORWARD");
    } else if (arg == "STOP") {
      stopSystemMotor(true);
      Serial.println("ACK:MOTOR:STOP");
    } else {
      Serial.print("ERR:MOTOR:UNKNOWN:"); Serial.println(arg);
    }
    return;
  }

  String category = arg;
  category.toLowerCase();

  // Find servo index for the given category return error if not found

  int idx = -1;
  for (int i = 0; i < NB_SERVOS; i++) {
    if (category == CATEGORY_NAMES[i]) { idx = i; break; }
  }
  if (idx == -1) { Serial.print("ERR:BAD_CATEGORY:"); Serial.println(category); return; }

// Check if the servo for the category is wired before actuating

  if (!servoWired[idx]) {
    Serial.print("ERR:SERVO:"); 
    Serial.print(idx + 1);
    Serial.print(":NOT_WIRED:CATEGORY:"); 
    Serial.println(CATEGORY_NAMES[idx]);
    return;
  }
  Serial.print("ACK:LABEL:"); Serial.println(category); // aknoledged anyway to shown which category is being system 
  actuateServo(idx); // 
}

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

// Wait for the sensor trigger or timeout to check if the object was sorted.
// During this time, no new actuation can start to avoid multiple triggers
// from the same object and to let the servo close properly.

  while (millis() - start < SENSOR_TIMEOUT) {
    readSensors(); // Continuously read sensor to see if the object has reached the servo door 
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