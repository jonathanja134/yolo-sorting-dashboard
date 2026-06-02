#pragma once

// ── SERVO CHANNELS ───────────────────────────────────────────
#define NB_SERVOS    4
#define S_MOTOR_1   12
#define S_MOTOR_2   13
#define S_MOTOR_3   14
#define S_MOTOR_4   15

// ── MOTOR ────────────────────────────────────────────────────
#define MotorFw     10

// ── SENSORS ──────────────────────────────────────────────────
#define POS_SENSOR_1  4
#define POS_SENSOR_2  2
#define RESET_SENSOR  5

// ── PULLDOWNS ────────────────────────────────────────────────
#define PULLDOWN_1   7
#define PULLDOWN_2   6
#define PULLDOWN_R  11

// ── DOOR SWITCHES ────────────────────────────────────────────
#define DOOR_SWITCH_1  12   // ⚠ conflict with S_MOTOR_1 and ESTOP_PIN
#define DOOR_SWITCH_2  13   // ⚠ conflict with S_MOTOR_2 and ORANGE_LAMP_PIN

// ── BUTTONS ──────────────────────────────────────────────────
#define START_STOP_PIN      8
#define BUTTON_DEBOUNCE_MS 50
#define ESTOP_PIN          12   // ⚠ conflict with S_MOTOR_1 and DOOR_SWITCH_1
#define UV_BUTTON_PIN       3   // ⚠ conflict with MotorOnLED

// ── LAMPS ────────────────────────────────────────────────────
#define ORANGE_LAMP_PIN  13   // ⚠ conflict with S_MOTOR_2 and DOOR_SWITCH_2
#define UV_LAMP_PIN       9

// ── SERVO POSITIONS ──────────────────────────────────────────
#define SERVO_MIN              150
#define SERVO_MAX              600
#define CLOSED_POS             120
#define OPEN_POS_LEFT           80
#define OPEN_POS_RIGHT         160
#define SERVO_CHECK_MIN_PULSE  100 
#define SERVO_CHECK_MAX_PULSE  650

// ── TIMING ───────────────────────────────────────────────────
const unsigned long SERVO_OPEN_MS      = 500; // Time to wait for a servo to open before checking the sensor
const unsigned long SENSOR_TIMEOUT_1   = 1000; // Time to wait for the object to be detected by the sensor after opening the servo in the 1st zone (closer, so shorter timeout)
const unsigned long SENSOR_TIMEOUT_2   = 4000; // Time to wait for the object to be detected by the sensor after opening the servo in the 2nd zone (further, so longer timeout)
const unsigned long DEBOUNCE_MS        = 50; // Debounce time for buttons and sensors to avoid multiple triggers from a single press or object