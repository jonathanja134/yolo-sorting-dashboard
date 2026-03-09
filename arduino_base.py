import serial
import time

# Open Arduino serial port
arduino = serial.Serial('/dev/ttyACM0', 9600, timeout=1)
time.sleep(4)  # wait for Arduino to reset

# Send a command
arduino.write(b'Hello Arduino\n')

# Read response
while True:
    if arduino.in_waiting > 0:
        line = arduino.readline().decode('utf-8').strip()
        print("Arduino:", line)