#define RESET_SENSOR 5
#define PULLDOWN_PIN 6  // bridge pin 6 to pin 5 with a jumper

bool lastState = LOW;
unsigned long lastChange = 0;
const unsigned long DEBOUNCE = 50;

void setup() {
  Serial.begin(9600);
  pinMode(PULLDOWN_PIN, OUTPUT);
  digitalWrite(PULLDOWN_PIN, LOW);
  pinMode(RESET_SENSOR, INPUT);
  Serial.println("=== Sensor Test Ready ===");
}

void loop() {
  unsigned long now = millis();
  bool current = digitalRead(RESET_SENSOR);

  if (current != lastState && (now - lastChange) > DEBOUNCE) {
    lastChange = now;
    lastState  = current;

    if (current == HIGH) {
      Serial.println("TRIGGERED");
    } else {
      Serial.println("CLEAR");
    }
  }
}