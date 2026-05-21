// Smart Gomoku Arduino Feedback Module
// Commands:
// 'B' = black move detected
// 'W' = white move detected
// 'E' = error / invalid detection
// 'R' = reset / all off
// 'G' = game over / both LEDs stay on

const int BLACK_LED = 8;
const int WHITE_LED = 9;
const int BUZZER = 6;

void setup() {
  pinMode(BLACK_LED, OUTPUT);
  pinMode(WHITE_LED, OUTPUT);
  pinMode(BUZZER, OUTPUT);

  digitalWrite(BLACK_LED, LOW);
  digitalWrite(WHITE_LED, LOW);

  Serial.begin(9600);
  Serial.println("Arduino feedback module ready");
}

void beepShort() {
  tone(BUZZER, 1200, 120);
  delay(150);
}

void beepError() {
  tone(BUZZER, 500, 180);
  delay(220);
  tone(BUZZER, 500, 180);
  delay(220);
}

void flashBoth() {
  for (int i = 0; i < 3; i++) {
    digitalWrite(BLACK_LED, HIGH);
    digitalWrite(WHITE_LED, HIGH);
    delay(150);
    digitalWrite(BLACK_LED, LOW);
    digitalWrite(WHITE_LED, LOW);
    delay(150);
  }
}

void showBlackMove() {
  digitalWrite(BLACK_LED, HIGH);
  digitalWrite(WHITE_LED, LOW);
  beepShort();
}

void showWhiteMove() {
  digitalWrite(BLACK_LED, LOW);
  digitalWrite(WHITE_LED, HIGH);
  beepShort();
}

void showGameOver() {
  digitalWrite(BLACK_LED, HIGH);
  digitalWrite(WHITE_LED, HIGH);
  tone(BUZZER, 1000, 120);
  delay(160);
  tone(BUZZER, 1400, 120);
  delay(160);
}

void resetFeedback() {
  digitalWrite(BLACK_LED, LOW);
  digitalWrite(WHITE_LED, LOW);
}

void loop() {
  if (Serial.available() > 0) {
    char command = Serial.read();

    if (command == 'B') {
      showBlackMove();
      Serial.println("ACK:B");
    }
    else if (command == 'W') {
      showWhiteMove();
      Serial.println("ACK:W");
    }
    else if (command == 'E') {
      flashBoth();
      beepError();
      resetFeedback();
      Serial.println("ACK:E");
    }
    else if (command == 'G') {
      showGameOver();
      Serial.println("ACK:G");
    }
    else if (command == 'R') {
      resetFeedback();
      Serial.println("ACK:R");
    }
  }
}
