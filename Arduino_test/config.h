#pragma once

// SERVO CHANNELS
#define NB_SERVOS    4
// servo driver pin so no conflict with door switch 1 and estop pin
#define S_MOTOR_12   12
#define S_MOTOR_13   13 
#define S_MOTOR_14   14
#define S_MOTOR_15   15

// MOTOR
#define MotorFw     10
#define CONVEYOR_1_PIN  9
// SENSORS
#define POS_SENSOR_1  4

//  PULLDOWNS 
#define PULLDOWN_1   7
#define PULLDOWN_2   6
#define PULLDOWN_R  11

//  DOOR SWITCHES 
#define DOOR_SWITCH_1  18   
#define DOOR_SWITCH_2  19   

// BUTTONS 
#define START_STOP_PIN      8
#define BUTTON_DEBOUNCE_MS 50
#define ESTOP_PIN          25   
#define UV_BUTTON_PIN       3   

// LAMPS    
#define UV_LAMP_PIN       2

//  SERVO POSITIONS
#define SERVO_MIN              150
#define SERVO_MAX              600
#define CLOSED_POS             120
#define OPEN_POS_LEFT           80
#define OPEN_POS_RIGHT         160
#define SERVO_CHECK_MIN_PULSE  100 
#define SERVO_CHECK_MAX_PULSE  650

//  TIMING  
const unsigned long SERVO_OPEN_MS  = 2000;  // Time to wait for a servo to open before checking the sensor
const unsigned long TIMEOUT_1      = 1500; // Time to wait for the object to be detected by the sensor after opening the servo in the 1st zone (closer, so shorter timeout)
const unsigned long TIMEOUT_2      = 5500; // Time to wait for the object to be detected by the sensor after opening the servo in the 2nd zone (further, so longer timeout)
const unsigned long DEBOUNCE_MS    = 500;   // Debounce time for buttons and sensors to avoid multiple triggers from a single press or ob

//Pin map in 

//UV_LAMP_PIN         2
//UV_BUTTON_PIN       3   
//POS_SENSOR_1        4
//PULLDOWN_2          6
//PULLDOWN_1          7
//START_STOP_PIN      8
//CONVEYOR_1_PIN      9
//MotorFw             10
//PULLDOWN_R          11
//ESTOP_PIN           12  
//DOOR_SWITCH_2       18  
//DOOR_SWITCH_1       19
