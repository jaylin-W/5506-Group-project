/**
 * XIAO ESP32S3 Sense
 * Buzzer + Button + LED Status + Face Detection + Servo Unlock Test
 *
 * Flow:
 * 1. Buzzer starts
 * 2. User presses button to mute buzzer
 * 3. Yellow LED + White LED turn on
 * 4. ESP32S3 runs face detection
 * 5. Success: Green LED on, Yellow/White off, Servo unlocks
 * 6. Failure: Red LED on, Yellow off, White stays on
 */

#include <ESP32Servo.h>

#include <eloquent_esp32cam.h>
#include <eloquent_esp32cam/face/detection.h>
#include <eloquent_esp32cam/face/recognition.h>

using eloq::camera;
using eloq::face::detection;
using eloq::face::recognition;


// =====================
// Pin settings
// 不要用 camera 占用的 GPIO10-18, 38-40, 47, 48
// =====================
#define SERVO_PIN       1

#define RED_LED_PIN     4
#define YELLOW_LED_PIN  2
#define GREEN_LED_PIN   3
#define WHITE_LED_PIN   5

#define BUZZER_PIN      44
#define BUTTON_PIN      9


// =====================
// Servo settings
// =====================
Servo triggerServo;

// 根据你们机械结构调整
const int LOCK_ANGLE = 0;
const int UNLOCK_ANGLE = 90;

// Face detect 成功后，servo 解锁保持多久
const unsigned long SERVO_UNLOCK_TIME_MS = 5000;

bool servoUnlocked = false;
unsigned long servoUnlockStartTime = 0;


// =====================
// Face detection settings
// =====================
const int MAX_FACE_ATTEMPTS = 8;
const int REQUIRED_FACE_SUCCESS = 2;

const unsigned long FACE_ATTEMPT_DELAY_MS = 500;


// =====================
// Button debounce
// =====================
const unsigned long DEBOUNCE_MS = 50;

bool lastButtonReading = HIGH;
bool stableButtonState = HIGH;
unsigned long lastDebounceTime = 0;


// =====================
// Buzzer
// =====================
bool buzzerActive = true;
bool buzzerState = false;
unsigned long lastBuzzerToggle = 0;
const unsigned long BUZZER_INTERVAL_MS = 300;


// =====================
// System state
// =====================
enum SystemState {
  REMINDER_BUZZING,
  FACE_VERIFYING,
  FACE_SUCCESS,
  FACE_FAILED
};

SystemState currentState = REMINDER_BUZZING;


// =====================
// Servo functions
// =====================
void lockServo() {
  triggerServo.write(LOCK_ANGLE);
  servoUnlocked = false;
  Serial.println("Servo LOCKED");
}

void unlockServo() {
  triggerServo.write(UNLOCK_ANGLE);
  servoUnlocked = true;
  servoUnlockStartTime = millis();
  Serial.println("Servo UNLOCKED");
}

void updateServoAutoLock() {
  if (servoUnlocked && millis() - servoUnlockStartTime >= SERVO_UNLOCK_TIME_MS) {
    lockServo();
  }
}


// =====================
// LED helper functions
// =====================
void allLightsOff() {
  digitalWrite(RED_LED_PIN, LOW);
  digitalWrite(YELLOW_LED_PIN, LOW);
  digitalWrite(GREEN_LED_PIN, LOW);
  digitalWrite(WHITE_LED_PIN, LOW);
}

void showWaitingVerification() {
  digitalWrite(RED_LED_PIN, LOW);
  digitalWrite(GREEN_LED_PIN, LOW);
  digitalWrite(YELLOW_LED_PIN, HIGH);
  digitalWrite(WHITE_LED_PIN, HIGH);
}

void showVerificationSuccess() {
  digitalWrite(RED_LED_PIN, LOW);
  digitalWrite(YELLOW_LED_PIN, LOW);
  digitalWrite(WHITE_LED_PIN, LOW);
  digitalWrite(GREEN_LED_PIN, HIGH);
}

void showVerificationFailed() {
  digitalWrite(YELLOW_LED_PIN, LOW);
  digitalWrite(GREEN_LED_PIN, LOW);
  digitalWrite(RED_LED_PIN, HIGH);
  digitalWrite(WHITE_LED_PIN, HIGH);
}


// =====================
// Buzzer functions
// =====================
void startBuzzer() {
  buzzerActive = true;
  Serial.println("Buzzer started.");
}

void stopBuzzer() {
  buzzerActive = false;
  buzzerState = false;
  digitalWrite(BUZZER_PIN, LOW);
  Serial.println("Buzzer stopped.");
}

void updateBuzzer() {
  if (!buzzerActive) {
    digitalWrite(BUZZER_PIN, LOW);
    return;
  }

  if (millis() - lastBuzzerToggle >= BUZZER_INTERVAL_MS) {
    buzzerState = !buzzerState;
    digitalWrite(BUZZER_PIN, buzzerState ? HIGH : LOW);
    lastBuzzerToggle = millis();
  }
}


// =====================
// Button function
// Button wiring:
// One side -> BUTTON_PIN
// Other side -> GND
// pinMode = INPUT_PULLUP
// Not pressed = HIGH
// Pressed = LOW
// =====================
bool buttonPressedOnce() {
  bool reading = digitalRead(BUTTON_PIN);

  if (reading != lastButtonReading) {
    lastDebounceTime = millis();
  }

  if ((millis() - lastDebounceTime) > DEBOUNCE_MS) {
    if (reading != stableButtonState) {
      stableButtonState = reading;

      if (stableButtonState == LOW) {
        lastButtonReading = reading;
        return true;
      }
    }
  }

  lastButtonReading = reading;
  return false;
}


// =====================
// Face detection process
// =====================
bool runFaceVerification() {
  showWaitingVerification();

  Serial.println();
  Serial.println("Face verification started...");
  Serial.println("Yellow LED ON, White LED ON");

  delay(300);  // let white fill light stabilize

  int successCount = 0;

  for (int i = 0; i < MAX_FACE_ATTEMPTS; i++) {
    Serial.print("Face detect attempt ");
    Serial.print(i + 1);
    Serial.print(" / ");
    Serial.println(MAX_FACE_ATTEMPTS);

    if (!camera.capture().isOk()) {
      Serial.print("Capture error: ");
      Serial.println(camera.exception.toString());
      delay(FACE_ATTEMPT_DELAY_MS);
      continue;
    }

    if (recognition.detect().isOk()) {
      successCount++;
      Serial.print("Face detected. Success count = ");
      Serial.println(successCount);

      if (successCount >= REQUIRED_FACE_SUCCESS) {
        Serial.println("Face verification PASSED.");
        showVerificationSuccess();

        // 这里就是 face detect 成功后解锁 servo
        unlockServo();

        return true;
      }
    } else {
      Serial.println("No face detected.");
    }

    delay(FACE_ATTEMPT_DELAY_MS);
  }

  Serial.println("Face verification FAILED.");
  showVerificationFailed();
  return false;
}


// =====================
// Setup
// =====================
void setup() {
  delay(3000);
  Serial.begin(115200);

  Serial.println();
  Serial.println("=== Buzzer + Button + LEDs + Face Detect + Servo Test ===");

  pinMode(RED_LED_PIN, OUTPUT);
  pinMode(YELLOW_LED_PIN, OUTPUT);
  pinMode(GREEN_LED_PIN, OUTPUT);
  pinMode(WHITE_LED_PIN, OUTPUT);

  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(BUTTON_PIN, INPUT_PULLUP);

  allLightsOff();
  digitalWrite(BUZZER_PIN, LOW);

  // Servo setup
  triggerServo.setPeriodHertz(50);
  triggerServo.attach(SERVO_PIN, 500, 2500);
  lockServo();

  // Camera setup
  camera.pinout.xiao();
  camera.brownout.disable();

  camera.resolution.face();
  camera.quality.high();

  detection.accurate();

  // 如果检测不到脸，降低到 0.30
  // 如果没有人也触发，提高到 0.45
  detection.confidence(0.35);

  recognition.confidence(0.70);

  Serial.println("Starting camera...");
  while (!camera.begin().isOk()) {
    Serial.print("Camera error: ");
    Serial.println(camera.exception.toString());
    delay(1000);
  }

  Serial.println("Starting face detector...");
  while (!recognition.begin().isOk()) {
    Serial.print("Detector error: ");
    Serial.println(recognition.exception.toString());
    delay(1000);
  }

  Serial.println("Camera OK");
  Serial.println("Face detector OK");

  currentState = REMINDER_BUZZING;
  startBuzzer();

  Serial.println();
  Serial.println("System started.");
  Serial.println("Buzzer is ringing.");
  Serial.println("Press button to stop buzzer and start face detection.");
}


// =====================
// Loop
// =====================
void loop() {
  updateBuzzer();
  updateServoAutoLock();

  if (buttonPressedOnce()) {
    Serial.println();
    Serial.println("Button pressed.");

    if (currentState == REMINDER_BUZZING) {
      stopBuzzer();

      currentState = FACE_VERIFYING;

      bool passed = runFaceVerification();

      if (passed) {
        currentState = FACE_SUCCESS;
        Serial.println("Green LED ON. Verification success. Servo unlocked.");
      } else {
        currentState = FACE_FAILED;
        Serial.println("Red LED ON, White LED ON. Verification failed.");
        Serial.println("Press button again to retry face detection.");
      }
    }

    else if (currentState == FACE_FAILED) {
      Serial.println("Retrying face detection...");

      currentState = FACE_VERIFYING;

      bool passed = runFaceVerification();

      if (passed) {
        currentState = FACE_SUCCESS;
        Serial.println("Green LED ON. Verification success. Servo unlocked.");
      } else {
        currentState = FACE_FAILED;
        Serial.println("Still failed. Red LED ON, White LED ON.");
        Serial.println("Press button again to retry.");
      }
    }

    else if (currentState == FACE_SUCCESS) {
      Serial.println("Already verified.");
    }
  }
}