/**
 * XIAO ESP32S3 Sense
 * Buzzer + Button + LED Status + Face Detection + Servo Unlock Test
 *
 * Flow:
 * 1. ESP32S3 polls the website for the current database-backed reminder
 * 2. A due reminder starts the buzzer
 * 3. User presses button to mute buzzer
 * 4. Yellow LED + White LED turn on
 * 5. ESP32S3 runs face detection
 * 6. Success: Green LED on, Yellow/White off, Servo unlocks
 * 7. Failure: Red LED on, Yellow off, White stays on
 */

#include <ESP32Servo.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <esp_sleep.h>
#include <string.h>

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
#define IR_SENSOR_PIN   8


// =====================
// Website / phone alert linkage
// =====================
// Fill in the WiFi that your XIAO ESP32S3 can reach.
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// Single-server test mode:
// Use the same HTTPS ngrok URL that the phone opens. Ngrok forwards it to Flask on 127.0.0.1:5000.
// If ngrok prints a new URL after restart, update this value before uploading the sketch.
const char* SERVER_BASE_URL = "https://panning-snagged-constrict.ngrok-free.dev";
const char* DEVICE_API_TOKEN = "5506-local-device-token";
const char* DEVICE_ID = "xiao-esp32s3-sense-5506123";

const unsigned long WIFI_CONNECT_TIMEOUT_MS = 15000;
const unsigned long DEVICE_STATUS_POLL_MS = 3000;
const unsigned long DEVICE_REMINDER_POLL_MS = 15000;
const unsigned long DISPENSING_TIMEOUT_MS = 600000UL;
const int IR_ACTIVE_LEVEL = LOW;
const bool ENABLE_DEEP_SLEEP = true;
const int MIN_DEEP_SLEEP_SECONDS = 30;

String lastSeenRemoteUnlockAt = "";
unsigned long lastDeviceStatusPoll = 0;
unsigned long lastReminderPoll = 0;
String activeReminderKey = "";
String completedReminderKey = "";
String activeReminderLabel = "";
String activeReminderTime = "";
int activeDoseQuantity = 1;
int dispensedCount = 0;
unsigned long dispensingStartTime = 0;


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

bool lastIrReading = !IR_ACTIVE_LEVEL;
bool stableIrState = !IR_ACTIVE_LEVEL;
unsigned long lastIrDebounceTime = 0;


// =====================
// Buzzer
// =====================
bool buzzerActive = false;
bool buzzerState = false;
unsigned long lastBuzzerToggle = 0;
const unsigned long BUZZER_INTERVAL_MS = 300;


// =====================
// System state
// =====================
enum SystemState {
  REMINDER_IDLE,
  REMINDER_BUZZING,
  FACE_VERIFYING,
  FACE_SUCCESS,
  FACE_FAILED,
  FACE_REMOTE_UNLOCK_WAITING,
  DISPENSING
};

SystemState currentState = REMINDER_IDLE;

void allLightsOff();


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
  if (currentState == DISPENSING) {
    return;
  }

  if (servoUnlocked && millis() - servoUnlockStartTime >= SERVO_UNLOCK_TIME_MS) {
    lockServo();
    if (currentState == FACE_SUCCESS) {
      allLightsOff();
      currentState = REMINDER_IDLE;
      lastReminderPoll = 0;
      Serial.println("Reminder flow completed. Waiting for the next database reminder.");
    }
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


bool irDoseDetectedOnce() {
  bool reading = digitalRead(IR_SENSOR_PIN);

  if (reading != lastIrReading) {
    lastIrDebounceTime = millis();
  }

  if ((millis() - lastIrDebounceTime) > DEBOUNCE_MS) {
    if (reading != stableIrState) {
      stableIrState = reading;

      if (stableIrState == IR_ACTIVE_LEVEL) {
        lastIrReading = reading;
        return true;
      }
    }
  }

  lastIrReading = reading;
  return false;
}


// =====================
// Website API functions
// =====================
bool websiteConfigured() {
  return strlen(WIFI_SSID) > 0
      && strcmp(WIFI_SSID, "YOUR_WIFI_SSID") != 0
      && strlen(SERVER_BASE_URL) > 0
      && strlen(DEVICE_API_TOKEN) > 0;
}

bool ensureWiFiConnected() {
  if (!websiteConfigured()) {
    Serial.println("Website linkage skipped: set WIFI_SSID, WIFI_PASSWORD, SERVER_BASE_URL, and DEVICE_API_TOKEN first.");
    return false;
  }

  if (WiFi.status() == WL_CONNECTED) {
    return true;
  }

  Serial.print("Connecting WiFi: ");
  Serial.println(WIFI_SSID);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  unsigned long startTime = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - startTime < WIFI_CONNECT_TIMEOUT_MS) {
    delay(300);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi connection failed. Website alert will not be sent.");
    return false;
  }

  Serial.print("WiFi connected. IP: ");
  Serial.println(WiFi.localIP());
  return true;
}

String websiteUrl(const char* path) {
  String base = SERVER_BASE_URL;
  if (base.endsWith("/")) {
    base.remove(base.length() - 1);
  }
  return base + path;
}

String devicePayload(const char* eventName) {
  String payload = "{";
  payload += "\"device_id\":\"";
  payload += DEVICE_ID;
  payload += "\",\"event\":\"";
  payload += eventName;
  payload += "\"";
  if (activeReminderKey.length() > 0) {
    payload += ",\"reminder_key\":\"";
    payload += activeReminderKey;
    payload += "\"";
    payload += ",\"taken_quantity\":";
    payload += String(dispensedCount);
    payload += ",\"dose_quantity\":";
    payload += String(activeDoseQuantity);
  }
  payload += "}";
  return payload;
}

String postToWebsite(const char* path, const String& payload, int& httpCode) {
  httpCode = -1;

  if (!ensureWiFiConnected()) {
    return "";
  }

  String url = websiteUrl(path);
  HTTPClient http;
  WiFiClient wifiClient;
  WiFiClientSecure secureClient;

  bool began = false;
  if (url.startsWith("https://")) {
    secureClient.setInsecure();  // For ngrok/local demos. Use a root CA for production.
    began = http.begin(secureClient, url);
  } else {
    began = http.begin(wifiClient, url);
  }

  if (!began) {
    Serial.print("HTTP begin failed: ");
    Serial.println(url);
    return "";
  }

  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Token", DEVICE_API_TOKEN);

  httpCode = http.POST(payload);
  String response = httpCode > 0 ? http.getString() : "";
  http.end();

  Serial.print("POST ");
  Serial.print(path);
  Serial.print(" -> HTTP ");
  Serial.println(httpCode);

  if (httpCode < 0) {
    Serial.print("HTTP error: ");
    Serial.println(http.errorToString(httpCode));
  }

  if (response.length() > 0) {
    Serial.print("Response: ");
    Serial.println(response);
  }

  return response;
}

int jsonIntValue(const String& json, const char* key, int fallbackValue) {
  String marker = String("\"") + key + "\":";
  int start = json.indexOf(marker);
  if (start < 0) {
    return fallbackValue;
  }

  start += marker.length();
  while (start < json.length() && (json[start] == ' ' || json[start] == '\t')) {
    start++;
  }

  return json.substring(start).toInt();
}

bool jsonBoolValue(const String& json, const char* key, bool fallbackValue) {
  String marker = String("\"") + key + "\":";
  int start = json.indexOf(marker);
  if (start < 0) {
    return fallbackValue;
  }

  start += marker.length();
  while (start < json.length() && (json[start] == ' ' || json[start] == '\t')) {
    start++;
  }

  if (json.startsWith("true", start)) {
    return true;
  }
  if (json.startsWith("false", start)) {
    return false;
  }

  return fallbackValue;
}

String jsonStringValue(const String& json, const char* key) {
  String marker = String("\"") + key + "\":";
  int start = json.indexOf(marker);
  if (start < 0) {
    return "";
  }

  start += marker.length();
  while (start < json.length() && (json[start] == ' ' || json[start] == '\t')) {
    start++;
  }

  if (start >= json.length() || json.startsWith("null", start) || json[start] != '"') {
    return "";
  }

  start++;
  int end = json.indexOf("\"", start);
  if (end < 0) {
    return "";
  }

  return json.substring(start, end);
}

void clearActiveReminderState() {
  activeReminderKey = "";
  activeReminderLabel = "";
  activeReminderTime = "";
  activeDoseQuantity = 1;
  dispensedCount = 0;
  dispensingStartTime = 0;
}

bool completeActiveReminderOnWebsite() {
  if (activeReminderKey.length() == 0) {
    return false;
  }

  String closingReminderKey = activeReminderKey;
  int httpCode = -1;
  String response = postToWebsite("/api/device/reminder-complete", devicePayload("reminder_completed"), httpCode);
  bool reported = httpCode == 200 && response.length() > 0;
  completedReminderKey = closingReminderKey;
  Serial.print("Reminder completed: ");
  Serial.println(closingReminderKey);
  if (!reported) {
    Serial.println("Warning: website did not confirm reminder completion.");
  }

  clearActiveReminderState();
  return reported;
}

bool timeoutActiveReminderOnWebsite() {
  if (activeReminderKey.length() == 0) {
    return false;
  }

  String closingReminderKey = activeReminderKey;
  int httpCode = -1;
  String response = postToWebsite("/api/device/reminder-timeout", devicePayload("reminder_timeout"), httpCode);
  bool reported = httpCode == 200 && response.length() > 0;
  completedReminderKey = closingReminderKey;
  Serial.print("Reminder missed after timeout: ");
  Serial.println(closingReminderKey);
  if (!reported) {
    Serial.println("Warning: website did not confirm reminder timeout.");
  }

  clearActiveReminderState();
  return reported;
}

void startDispensingFlow(const char* source) {
  dispensedCount = 0;
  dispensingStartTime = millis();
  currentState = DISPENSING;
  showVerificationSuccess();
  unlockServo();

  Serial.print("DISPENSING started by ");
  Serial.println(source);
  Serial.print("Dose target: ");
  Serial.println(activeDoseQuantity);
  Serial.print("IR sensor is counting pills for up to ");
  Serial.print(DISPENSING_TIMEOUT_MS / 1000);
  Serial.println(" seconds.");
}

void continueAfterWebsitePinUnlock() {
  Serial.println("Website PIN confirmed. Continuing pill box dispensing flow.");
  if (activeReminderKey.length() == 0) {
    Serial.println("No active reminder is stored locally. Polling the website before dispensing.");
    currentState = REMINDER_IDLE;
    pollReminderState();
    return;
  }
  startDispensingFlow("website PIN unlock");
}

void enterDeepSleepSeconds(int sleepSeconds) {
  if (!ENABLE_DEEP_SLEEP || sleepSeconds < MIN_DEEP_SLEEP_SECONDS) {
    return;
  }

  Serial.print("Entering deep sleep for ");
  Serial.print(sleepSeconds);
  Serial.println(" seconds until the next planned wake window.");

  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);
  esp_sleep_enable_timer_wakeup((uint64_t)sleepSeconds * 1000000ULL);
  delay(100);
  esp_deep_sleep_start();
}

bool pollReminderState() {
  int httpCode = -1;
  String response = postToWebsite("/api/device/reminder-state", devicePayload("poll_reminder"), httpCode);
  if (httpCode != 200 || response.length() == 0) {
    return false;
  }

  String action = jsonStringValue(response, "device_action");
  String reminderKey = jsonStringValue(response, "reminder_key");
  int doseQuantity = jsonIntValue(response, "dose_quantity", jsonIntValue(response, "target_quantity", 1));
  int sleepSeconds = jsonIntValue(response, "sleep_seconds", 0);

  if (action == "wait_for_pin") {
    if (reminderKey.length() > 0 && activeReminderKey.length() == 0) {
      activeReminderKey = reminderKey;
      activeReminderLabel = jsonStringValue(response, "supplement_name");
      activeReminderTime = jsonStringValue(response, "take_time");
      activeDoseQuantity = max(1, doseQuantity);
    }
    if (currentState == REMINDER_IDLE || currentState == FACE_FAILED) {
      currentState = FACE_REMOTE_UNLOCK_WAITING;
      showVerificationFailed();
      Serial.println("Server says website PIN unlock is required.");
    }
    return true;
  }

  if (action == "ring_reminder" && reminderKey.length() > 0) {
    if (reminderKey == completedReminderKey) {
      return true;
    }

    if (currentState == REMINDER_IDLE || currentState == FACE_SUCCESS) {
      activeReminderKey = reminderKey;
      activeReminderLabel = jsonStringValue(response, "supplement_name");
      activeReminderTime = jsonStringValue(response, "take_time");
      activeDoseQuantity = max(1, doseQuantity);
      dispensedCount = 0;
      currentState = REMINDER_BUZZING;
      startBuzzer();

      Serial.println();
      Serial.println("Database reminder is due.");
      Serial.print("Reminder: ");
      Serial.print(activeReminderLabel.length() > 0 ? activeReminderLabel : "Supplement");
      Serial.print(" at ");
      Serial.println(activeReminderTime.length() > 0 ? activeReminderTime : "scheduled time");
      Serial.print("Dose quantity: ");
      Serial.println(activeDoseQuantity);
      Serial.println("Buzzer is ringing. Press button to start face detection.");
    }
    return true;
  }

  if (action == "idle" && currentState == REMINDER_IDLE) {
    Serial.println("No database reminder is due now.");
    enterDeepSleepSeconds(sleepSeconds);
  }

  return true;
}

bool refreshDeviceStatus(bool baselineOnly) {
  int httpCode = -1;
  String response = postToWebsite("/api/face-unlock/device-status", devicePayload("status"), httpCode);
  if (httpCode != 200 || response.length() == 0) {
    return false;
  }

  String lastUnlockAt = jsonStringValue(response, "last_unlock_at");
  bool unlockRequired = jsonBoolValue(response, "unlock_required", false);
  int failedAttempts = jsonIntValue(response, "failed_attempts", 0);
  int threshold = jsonIntValue(response, "failure_threshold", 3);

  Serial.print("Server status: failed_attempts=");
  Serial.print(failedAttempts);
  Serial.print(" / ");
  Serial.print(threshold);
  Serial.print(", unlock_required=");
  Serial.println(unlockRequired ? "true" : "false");

  if (baselineOnly) {
    lastSeenRemoteUnlockAt = lastUnlockAt;
    return false;
  }

  if (lastUnlockAt.length() > 0 && lastUnlockAt != lastSeenRemoteUnlockAt) {
    lastSeenRemoteUnlockAt = lastUnlockAt;
    continueAfterWebsitePinUnlock();
    return true;
  }

  return false;
}

bool reportFaceFailureToWebsite() {
  int httpCode = -1;
  String response = postToWebsite("/api/face-unlock/failure", devicePayload("face_failed"), httpCode);
  if (httpCode != 200 || response.length() == 0) {
    return false;
  }

  int failedAttempts = jsonIntValue(response, "failed_attempts", 0);
  int threshold = jsonIntValue(response, "failure_threshold", 3);
  bool unlockRequired = jsonBoolValue(response, "unlock_required", false);

  Serial.print("Website face failure count: ");
  Serial.print(failedAttempts);
  Serial.print(" / ");
  Serial.println(threshold);

  if (unlockRequired) {
    Serial.println("Face failed 3 times. Phone push and web alert should be active.");
  }

  return unlockRequired;
}

void reportFaceSuccessToWebsite() {
  int httpCode = -1;
  postToWebsite("/api/face-unlock/success", devicePayload("face_success"), httpCode);
}

void handleFaceFailureResult() {
  bool websiteUnlockRequired = reportFaceFailureToWebsite();

  if (websiteUnlockRequired) {
    currentState = FACE_REMOTE_UNLOCK_WAITING;
    Serial.println("Red LED ON, White LED ON. Waiting for website PIN unlock.");
    Serial.println("Open the phone notification or website alert, enter the pill box unlock PIN, then this device will continue.");
    return;
  }

  currentState = FACE_FAILED;
  Serial.println("Red LED ON, White LED ON. Verification failed.");
  Serial.println("Press button again to retry face verification.");
}


void finishDispensingSuccess() {
  Serial.println("Dose quantity reached. Completing reminder and locking servo.");
  completeActiveReminderOnWebsite();
  lockServo();
  allLightsOff();
  currentState = REMINDER_IDLE;
  lastReminderPoll = 0;
  pollReminderState();
}

void finishDispensingTimeout() {
  Serial.println("Dispensing timeout. Marking this reminder as missed and locking servo.");
  timeoutActiveReminderOnWebsite();
  lockServo();
  allLightsOff();
  currentState = REMINDER_IDLE;
  lastReminderPoll = 0;
  pollReminderState();
}

void updateDispensingFlow() {
  if (currentState != DISPENSING) {
    return;
  }

  if (irDoseDetectedOnce()) {
    dispensedCount++;
    Serial.print("IR dose count: ");
    Serial.print(dispensedCount);
    Serial.print(" / ");
    Serial.println(activeDoseQuantity);

    if (dispensedCount >= activeDoseQuantity) {
      finishDispensingSuccess();
      return;
    }
  }

  if (millis() - dispensingStartTime >= DISPENSING_TIMEOUT_MS) {
    finishDispensingTimeout();
  }
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
  pinMode(IR_SENSOR_PIN, INPUT_PULLUP);

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

  if (ensureWiFiConnected()) {
    refreshDeviceStatus(true);
    pollReminderState();
  }

  if (currentState != REMINDER_BUZZING && currentState != FACE_REMOTE_UNLOCK_WAITING) {
    currentState = REMINDER_IDLE;
  }

  Serial.println();
  Serial.println("System started.");
  Serial.println("Waiting for the website database reminder.");
  Serial.println("Add a due supplement schedule on the website to start the buzzer.");
}


// =====================
// Loop
// =====================
void loop() {
  updateBuzzer();
  updateDispensingFlow();
  updateServoAutoLock();

  if (currentState == REMINDER_IDLE
      && millis() - lastReminderPoll >= DEVICE_REMINDER_POLL_MS) {
    lastReminderPoll = millis();
    pollReminderState();
  }

  if (currentState == FACE_REMOTE_UNLOCK_WAITING
      && millis() - lastDeviceStatusPoll >= DEVICE_STATUS_POLL_MS) {
    lastDeviceStatusPoll = millis();
    refreshDeviceStatus(false);
  }

  if (buttonPressedOnce()) {
    Serial.println();
    Serial.println("Button pressed.");

    if (currentState == REMINDER_IDLE) {
      Serial.println("No active website reminder yet. Waiting for a due database schedule.");
      pollReminderState();
    }

    else if (currentState == REMINDER_BUZZING) {
      stopBuzzer();

      currentState = FACE_VERIFYING;

      bool passed = runFaceVerification();

      if (passed) {
        reportFaceSuccessToWebsite();
        startDispensingFlow("face recognition");
        Serial.println("Green LED ON. Verification success. Servo unlocked for dispensing.");
      } else {
        handleFaceFailureResult();
      }
    }

    else if (currentState == FACE_FAILED) {
      Serial.println("Retrying face detection...");

      currentState = FACE_VERIFYING;

      bool passed = runFaceVerification();

      if (passed) {
        reportFaceSuccessToWebsite();
        startDispensingFlow("face recognition retry");
        Serial.println("Green LED ON. Verification success. Servo unlocked for dispensing.");
      } else {
        handleFaceFailureResult();
      }
    }

    else if (currentState == FACE_SUCCESS) {
      Serial.println("Already verified.");
    }

    else if (currentState == DISPENSING) {
      Serial.print("Dispensing in progress. IR count ");
      Serial.print(dispensedCount);
      Serial.print(" / ");
      Serial.println(activeDoseQuantity);
    }

    else if (currentState == FACE_REMOTE_UNLOCK_WAITING) {
      Serial.println("Waiting for website PIN unlock. Polling server now...");
      refreshDeviceStatus(false);
    }
  }
}
