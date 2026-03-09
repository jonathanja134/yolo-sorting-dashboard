#include <Servo.h>

#define NB_S_Motor 2

// Outputs (servos)
#define S_Motor_1 13
#define S_Motor_2 12
//#define S_Motor_3 8
//#define S_Motor_4 7

// Proximity sensors
//#define Pos_Sensor_1 4     // pour servos 1 et 2
//#define Pos_Sensor_2 2     // pour servos 3 et 4

const int Open_Position  = 90;
const int Close_Position = 0;


const int servoPins[NB_S_Motor] = {S_Motor_1, S_Motor_2}; //S_Motor_3, S_Motor_4


const char* objectNames[NB_S_Motor] = {
"1",
"2",
};


//int getProximityPin(int servoNum) {
 // if (servoNum == 0 || servoNum == 1) return Pos_Sensor_1;  
 // else                                return Pos_Sensor_2;  
//}

Servo servos[NB_S_Motor];

void setup() {
  Serial.begin(9600);
  Serial.println("=== Arduino Sorting - 2 servos ===");//, 2 proximity sensors
  Serial.println("send devices type");

  for(int i = 0; i < NB_S_Motor; i++) {
    servos[i].attach(servoPins[i]);
    servos[i].write(Close_Position);  
  }

  //pinMode(Pos_Sensor_1, INPUT_PULLUP);
 // pinMode(Pos_Sensor_2, INPUT_PULLUP);
}

void loop() {
  if (Serial.available() > 0) {
    String commande = Serial.readStringUntil('\n');
    commande.trim();
    commande.toLowerCase();

    int num = -1;
    for(int i = 0; i < NB_S_Motor; i++) {
      if (commande == objectNames[i]) {
        num = i;
        break;
      }
    }

    if (num != -1) {
      Serial.print("device : ");
      Serial.print(commande);
      Serial.print(" Servo ");
      Serial.println(num + 1);
      actandwait(num);
    } else {
      Serial.println("unknow");
    }
  }
}

void actandwait(int num) {
  // Open position
  servos[num].write(Open_Position);
 Serial.print("Servo Motor ");
  Serial.print(num + 1);                  
  Serial.print(" Open (");
  Serial.print(objectNames[num]);          
  Serial.println(")");
  delay(400);

  // find adapted sensor
//  int capteurPin = getProximityPin(num);
  Serial.print("   wait for sensor ");
 // Serial.println(capteurPin);

  // wait prox sensor
  //unsigned long debut = millis();
  bool objetDetecte = false;

 // while (millis() - debut < 8000) {
    //if (digitalRead(capteurPin) == LOW) {
     // objetDetecte = true;
     // Serial.println("   device detected");
     // break;
    //}
    delay(5000);
 // }

  if (!objetDetecte) {
    Serial.println("  Close position (timeout)");
  }

  //Close
  servos[num].write(Close_Position);

  if (objetDetecte) {
    Serial.println("  closing after detection");
  } else {
    Serial.println("closing causing by timeout");
  }

}
