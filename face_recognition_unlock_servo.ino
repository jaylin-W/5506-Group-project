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
#include <Preferences.h>
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
// WiFi is intentionally not stored in flash, so old Preferences values cannot override these two lines.
const char* WIFI_SSID = "iphone1";
const char* WIFI_PASSWORD = "woshinibaba";

// Single-server test mode:
// Use the same HTTPS ngrok URL that the phone opens. Ngrok forwards it to Flask on 127.0.0.1:5000.
// If ngrok prints a new URL after restart, update this value before uploading the sketch.
const char* DEFAULT_SERVER_BASE_URL = "https://panning-snagged-constrict.ngrok-free.dev";
const bool DEFAULT_FORCE_HTTP_FOR_ESP = false;  // Set with SET_HTTP 1 only when the target really accepts HTTP.
const char* DEFAULT_DEVICE_API_TOKEN = "5506-local-device-token";
const char* DEFAULT_PRODUCT_CODE = "5506DEV";  // Universal test activation code for repeated enrollment tests.
const char* DEFAULT_DEVICE_ID = "xiao-esp32s3-sense-5506123";

const unsigned long WIFI_CONNECT_TIMEOUT_MS = 30000;
const unsigned long SERIAL_CONFIG_WINDOW_MS = 6000;
const unsigned long SERIAL_COMMAND_IDLE_MS = 900;
const unsigned long CONFIG_WARNING_INTERVAL_MS = 30000;
const unsigned long DEVICE_STATUS_POLL_MS = 3000;
const unsigned long DEVICE_REMINDER_POLL_MS = 15000;
const unsigned long FACE_ENROLLMENT_COMMAND_POLL_MS = 10000;
const unsigned long DISPENSING_TIMEOUT_MS = 600000UL;
const int IR_ACTIVE_LEVEL = LOW;
const bool ENABLE_DEEP_SLEEP = true;
const int MIN_DEEP_SLEEP_SECONDS = 30;

String lastSeenRemoteUnlockAt = "";
unsigned long lastDeviceStatusPoll = 0;
unsigned long lastReminderPoll = 0;
unsigned long lastFaceEnrollmentPoll = 0;
String activeReminderKey = "";
String completedReminderKey = "";
String activeReminderLabel = "";
String activeReminderTime = "";
int activeDoseQuantity = 1;
int dispensedCount = 0;
unsigned long dispensingStartTime = 0;

Preferences devicePrefs;
bool prefsReady = false;
String wifiSsid = WIFI_SSID;
String wifiPassword = WIFI_PASSWORD;
String serverBaseUrl = DEFAULT_SERVER_BASE_URL;
String deviceApiToken = DEFAULT_DEVICE_API_TOKEN;
String productCode = DEFAULT_PRODUCT_CODE;
String deviceId = DEFAULT_DEVICE_ID;
bool forceHttpForEsp = DEFAULT_FORCE_HTTP_FOR_ESP;
String serialCommandBuffer = "";
unsigned long lastSerialCommandCharAt = 0;
unsigned long lastConfigWarningAt = 0;


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
const int MAX_ENROLLMENT_ATTEMPT_MULTIPLIER = 5;

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
  DISPENSING,
  FACE_ENROLLING
};

SystemState currentState = REMINDER_IDLE;

void allLightsOff();
void loadRuntimeConfig();
void printRuntimeConfig();
void printSerialConfigHelp();
void updateSerialConfigCommands();
void handleSerialConfigCommand(String command);
void probeWebsiteConnection();
bool ensureWiFiConnected();
bool pollReminderState();
bool pollFaceEnrollmentCommand();


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
// Runtime server/device config over Serial + flash
// =====================
void loadRuntimeConfig() {
  if (!prefsReady) {
    prefsReady = devicePrefs.begin("pillbox", false);
  }

  if (!prefsReady) {
    Serial.println("Config storage unavailable. Using sketch defaults only.");
    return;
  }

  wifiSsid = WIFI_SSID;
  wifiPassword = WIFI_PASSWORD;
  serverBaseUrl = devicePrefs.getString("server_url", DEFAULT_SERVER_BASE_URL);
  deviceApiToken = devicePrefs.getString("api_token", DEFAULT_DEVICE_API_TOKEN);
  productCode = devicePrefs.getString("product", DEFAULT_PRODUCT_CODE);
  deviceId = devicePrefs.getString("device_id", DEFAULT_DEVICE_ID);
  forceHttpForEsp = devicePrefs.getBool("force_http", DEFAULT_FORCE_HTTP_FOR_ESP);
}

String effectiveServerBaseUrl() {
  String base = serverBaseUrl;
  if (forceHttpForEsp && base.startsWith("https://")) {
    base.replace("https://", "http://");
  }
  return base;
}

void printRuntimeConfig() {
  Serial.println();
  Serial.println("Current runtime config:");
  Serial.print("  WiFi SSID: ");
  Serial.println(wifiSsid);
  Serial.print("  WiFi password: ");
  Serial.println(wifiPassword.length() > 0 && wifiPassword != "YOUR_WIFI_PASSWORD" ? "[set from code]" : "[not set]");
  Serial.print("  Server URL: ");
  Serial.println(serverBaseUrl);
  Serial.print("  Effective URL: ");
  Serial.println(effectiveServerBaseUrl());
  Serial.print("  Force HTTP: ");
  Serial.println(forceHttpForEsp ? "true" : "false");
  Serial.print("  Product code: ");
  Serial.println(productCode);
  Serial.print("  Device ID: ");
  Serial.println(deviceId);
  Serial.print("  API token: ");
  Serial.println(deviceApiToken.length() > 0 ? "[saved]" : "[not set]");
}

void printSerialConfigHelp() {
  Serial.println();
  Serial.println("Runtime config commands:");
  Serial.println("  SHOW_CONFIG");
  Serial.println("  SET_URL https://your-ngrok-url");
  Serial.println("  SET_HTTP 0        (recommended for ngrok HTTPS)");
  Serial.println("  SET_HTTP 1        (only if the server really accepts plain HTTP)");
  Serial.println("  SET_TOKEN your-device-api-token");
  Serial.println("  SET_PRODUCT 5506DEV");
  Serial.println("  SET_DEVICE xiao-esp32s3-sense-5506123");
  Serial.println("  RECONNECT");
  Serial.println("  POLL");
  Serial.println("  CLEAR_CONFIG");
}

bool parseConfigBool(String value, bool fallbackValue) {
  value.trim();
  value.toLowerCase();

  if (value == "1" || value == "true" || value == "on" || value == "yes") {
    return true;
  }
  if (value == "0" || value == "false" || value == "off" || value == "no") {
    return false;
  }

  return fallbackValue;
}

void saveStringConfig(const char* key, const String& value) {
  if (prefsReady) {
    devicePrefs.putString(key, value);
  }
}

void saveBoolConfig(const char* key, bool value) {
  if (prefsReady) {
    devicePrefs.putBool(key, value);
  }
}

void resetRuntimeConfigToDefaults() {
  wifiSsid = WIFI_SSID;
  wifiPassword = WIFI_PASSWORD;
  serverBaseUrl = DEFAULT_SERVER_BASE_URL;
  deviceApiToken = DEFAULT_DEVICE_API_TOKEN;
  productCode = DEFAULT_PRODUCT_CODE;
  deviceId = DEFAULT_DEVICE_ID;
  forceHttpForEsp = DEFAULT_FORCE_HTTP_FOR_ESP;
}

void handleSerialConfigCommand(String command) {
  command.trim();
  if (command.length() == 0) {
    return;
  }

  if (command == "HELP" || command == "?") {
    printSerialConfigHelp();
    return;
  }

  if (command == "SHOW_CONFIG") {
    printRuntimeConfig();
    return;
  }

  if (command == "CLEAR_CONFIG") {
    if (prefsReady) {
      devicePrefs.clear();
    }
    resetRuntimeConfigToDefaults();
    WiFi.disconnect(true);
    Serial.println("Runtime config cleared. Defaults restored.");
    printRuntimeConfig();
    return;
  }

  if (command == "RECONNECT") {
    WiFi.disconnect(true);
    delay(300);
    ensureWiFiConnected();
    return;
  }

  if (command == "POLL") {
    pollFaceEnrollmentCommand();
    pollReminderState();
    return;
  }

  if (command.startsWith("SET_URL ")) {
    serverBaseUrl = command.substring(strlen("SET_URL "));
    serverBaseUrl.trim();
    saveStringConfig("server_url", serverBaseUrl);
    lastReminderPoll = 0;
    lastFaceEnrollmentPoll = 0;
    Serial.print("Server URL saved. Effective URL: ");
    Serial.println(effectiveServerBaseUrl());
    return;
  }

  if (command.startsWith("SET_HTTP ")) {
    forceHttpForEsp = parseConfigBool(command.substring(strlen("SET_HTTP ")), forceHttpForEsp);
    saveBoolConfig("force_http", forceHttpForEsp);
    Serial.print("Force HTTP saved: ");
    Serial.println(forceHttpForEsp ? "true" : "false");
    Serial.print("Effective URL: ");
    Serial.println(effectiveServerBaseUrl());
    return;
  }

  if (command.startsWith("SET_TOKEN ")) {
    deviceApiToken = command.substring(strlen("SET_TOKEN "));
    deviceApiToken.trim();
    saveStringConfig("api_token", deviceApiToken);
    Serial.println("Device API token saved.");
    return;
  }

  if (command.startsWith("SET_PRODUCT ")) {
    productCode = command.substring(strlen("SET_PRODUCT "));
    productCode.trim();
    saveStringConfig("product", productCode);
    Serial.print("Product code saved: ");
    Serial.println(productCode);
    return;
  }

  if (command.startsWith("SET_DEVICE ")) {
    deviceId = command.substring(strlen("SET_DEVICE "));
    deviceId.trim();
    saveStringConfig("device_id", deviceId);
    Serial.print("Device ID saved: ");
    Serial.println(deviceId);
    return;
  }

  Serial.print("Unknown config command: ");
  Serial.println(command);
  Serial.println("Send HELP to list commands.");
}

void updateSerialConfigCommands() {
  while (Serial.available() > 0) {
    char c = Serial.read();
    lastSerialCommandCharAt = millis();

    if (c == '\n' || c == '\r') {
      if (serialCommandBuffer.length() > 0) {
        handleSerialConfigCommand(serialCommandBuffer);
        serialCommandBuffer = "";
      }
      continue;
    }

    if (serialCommandBuffer.length() < 240) {
      serialCommandBuffer += c;
    } else {
      serialCommandBuffer = "";
      Serial.println("Serial config command too long. Buffer cleared.");
    }
  }

  if (serialCommandBuffer.length() > 0
      && millis() - lastSerialCommandCharAt >= SERIAL_COMMAND_IDLE_MS) {
    handleSerialConfigCommand(serialCommandBuffer);
    serialCommandBuffer = "";
  }
}


// =====================
// Website API functions
// =====================
bool websiteConfigured() {
  bool shouldPrint = lastConfigWarningAt == 0 || millis() - lastConfigWarningAt >= CONFIG_WARNING_INTERVAL_MS;
  bool ok = true;

  if (wifiSsid.length() == 0 || wifiSsid == "YOUR_WIFI_SSID") {
    if (shouldPrint) {
      Serial.println("Config missing: WiFi SSID. Edit WIFI_SSID in the sketch and upload again.");
    }
    ok = false;
  }

  if (wifiPassword.length() == 0 || wifiPassword == "YOUR_WIFI_PASSWORD") {
    if (shouldPrint) {
      Serial.println("Config missing: WiFi password. Edit WIFI_PASSWORD in the sketch and upload again.");
    }
    ok = false;
  }

  if (serverBaseUrl.length() == 0) {
    if (shouldPrint) {
      Serial.println("Config missing: Server URL. Use SET_URL https://your-ngrok-url.");
    }
    ok = false;
  }

  if (deviceApiToken.length() == 0) {
    if (shouldPrint) {
      Serial.println("Config missing: Device API token. Use SET_TOKEN your-device-api-token.");
    }
    ok = false;
  }

  if (!ok && shouldPrint) {
    lastConfigWarningAt = millis();
  }

  return ok;
}

const char* wifiStatusName(wl_status_t status) {
  switch (status) {
    case WL_IDLE_STATUS:
      return "WL_IDLE_STATUS";
    case WL_NO_SSID_AVAIL:
      return "WL_NO_SSID_AVAIL";
    case WL_SCAN_COMPLETED:
      return "WL_SCAN_COMPLETED";
    case WL_CONNECTED:
      return "WL_CONNECTED";
    case WL_CONNECT_FAILED:
      return "WL_CONNECT_FAILED";
    case WL_CONNECTION_LOST:
      return "WL_CONNECTION_LOST";
    case WL_DISCONNECTED:
      return "WL_DISCONNECTED";
    default:
      return "WL_UNKNOWN";
  }
}

void scanForConfiguredWiFi() {
  Serial.println("Scanning nearby WiFi networks...");
  int networkCount = WiFi.scanNetworks(false, true);
  bool found = false;

  if (networkCount <= 0) {
    Serial.println("No WiFi networks found by scan.");
    return;
  }

  for (int i = 0; i < networkCount; i++) {
    String ssid = WiFi.SSID(i);
    if (ssid == wifiSsid) {
      found = true;
      Serial.print("Found configured SSID. RSSI=");
      Serial.print(WiFi.RSSI(i));
      Serial.print(" dBm, channel=");
      Serial.println(WiFi.channel(i));
    }
  }

  if (!found) {
    Serial.println("Configured SSID was not found. Check hotspot name, 2.4GHz compatibility, and whether Personal Hotspot is visible.");
  }
}

bool ensureWiFiConnected() {
  if (!websiteConfigured()) {
    Serial.println("Website linkage skipped: set WiFi in code, plus Server URL and Device API token.");
    Serial.println("Send HELP in Serial Monitor to configure this device without uploading again.");
    return false;
  }

  if (WiFi.status() == WL_CONNECTED) {
    return true;
  }

  Serial.print("Connecting WiFi: ");
  Serial.println(wifiSsid);

  WiFi.persistent(false);
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.disconnect(true, true);
  delay(500);
  scanForConfiguredWiFi();

  WiFi.begin(wifiSsid.c_str(), wifiPassword.c_str());

  unsigned long startTime = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - startTime < WIFI_CONNECT_TIMEOUT_MS) {
    delay(300);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() != WL_CONNECTED) {
    Serial.print("WiFi connection failed. Final status: ");
    Serial.println(wifiStatusName(WiFi.status()));
    Serial.println("Website alert will not be sent.");
    return false;
  }

  Serial.print("WiFi connected. IP: ");
  Serial.println(WiFi.localIP());
  Serial.print("Gateway: ");
  Serial.println(WiFi.gatewayIP());
  Serial.print("DNS: ");
  Serial.println(WiFi.dnsIP());
  probeWebsiteConnection();
  return true;
}

String websiteUrl(const char* path) {
  String base = effectiveServerBaseUrl();
  if (base.endsWith("/")) {
    base.remove(base.length() - 1);
  }
  return base + path;
}

String websiteHost() {
  String base = effectiveServerBaseUrl();
  base.replace("https://", "");
  base.replace("http://", "");
  int slash = base.indexOf("/");
  if (slash >= 0) {
    base = base.substring(0, slash);
  }
  int colon = base.indexOf(":");
  if (colon >= 0) {
    base = base.substring(0, colon);
  }
  return base;
}

int websitePort() {
  String base = effectiveServerBaseUrl();
  if (base.startsWith("https://")) {
    return 443;
  }
  if (base.startsWith("http://")) {
    return 80;
  }
  return 443;
}

void probeWebsiteConnection() {
  String host = websiteHost();
  int port = websitePort();

  Serial.print("Website host: ");
  Serial.println(host);
  Serial.print("Website port: ");
  Serial.println(port);

  IPAddress resolvedIp;
  if (WiFi.hostByName(host.c_str(), resolvedIp)) {
    Serial.print("Website DNS resolved IP: ");
    Serial.println(resolvedIp);
  } else {
    Serial.println("Website DNS lookup failed.");
    return;
  }

  if (port == 443) {
    WiFiClientSecure probeClient;
    probeClient.setInsecure();
    probeClient.setTimeout(8000);
    Serial.println("Testing HTTPS/TLS connection to website host...");
    if (probeClient.connect(host.c_str(), port)) {
      Serial.println("HTTPS/TLS connection probe OK.");
      probeClient.stop();
    } else {
      Serial.println("HTTPS/TLS connection probe FAILED. Try another WiFi/hotspot, refresh ngrok, or test HTTP mode.");
    }
  } else {
    WiFiClient probeClient;
    probeClient.setTimeout(8000);
    Serial.println("Testing HTTP TCP connection to website host...");
    if (probeClient.connect(host.c_str(), port)) {
      Serial.println("HTTP TCP connection probe OK.");
      probeClient.stop();
    } else {
      Serial.println("HTTP TCP connection probe FAILED.");
    }
  }
}

String jsonEscape(const String& value) {
  String escaped = "";
  for (size_t i = 0; i < value.length(); i++) {
    char c = value[i];
    if (c == '"' || c == '\\') {
      escaped += '\\';
      escaped += c;
    } else if (c == '\n') {
      escaped += "\\n";
    } else if (c == '\r') {
      escaped += "\\r";
    } else {
      escaped += c;
    }
  }
  return escaped;
}

String devicePayload(const char* eventName) {
  String payload = "{";
  payload += "\"device_id\":\"";
  payload += deviceId;
  payload += "\",\"product_code\":\"";
  payload += productCode;
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
  Serial.print("Request URL: ");
  Serial.println(url);
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
  http.addHeader("X-Device-Token", deviceApiToken);

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

String postBinaryToWebsite(const String& path, uint8_t* data, size_t length, const char* contentType, int& httpCode) {
  httpCode = -1;

  if (!ensureWiFiConnected()) {
    return "";
  }

  String url = websiteUrl(path.c_str());
  Serial.print("Request URL: ");
  Serial.println(url);
  HTTPClient http;
  WiFiClient wifiClient;
  WiFiClientSecure secureClient;

  bool began = false;
  if (url.startsWith("https://")) {
    secureClient.setInsecure();
    began = http.begin(secureClient, url);
  } else {
    began = http.begin(wifiClient, url);
  }

  if (!began) {
    Serial.print("HTTP begin failed: ");
    Serial.println(url);
    return "";
  }

  http.addHeader("Content-Type", contentType);
  http.addHeader("X-Device-Token", deviceApiToken);
  http.addHeader("X-Device-Id", deviceId);
  http.addHeader("X-Product-Code", productCode);

  httpCode = http.POST(data, length);
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

bool reportFaceEnrollmentResult(const String& sessionId, const char* status, int capturedSamples, const String& message) {
  String payload = "{";
  payload += "\"device_id\":\"";
  payload += deviceId;
  payload += "\",\"event\":\"face_enrollment_result\"";
  payload += ",\"session_id\":\"";
  payload += jsonEscape(sessionId);
  payload += "\",\"status\":\"";
  payload += status;
  payload += "\",\"captured_samples\":";
  payload += String(capturedSamples);
  payload += ",\"message\":\"";
  payload += jsonEscape(message);
  payload += "\"}";

  int httpCode = -1;
  String response = postToWebsite("/api/face-enrollment/device-result", payload, httpCode);
  return httpCode == 200 && response.length() > 0;
}

bool uploadCurrentEnrollmentPhoto(const String& sessionId, int photoIndex) {
  if (!camera.hasFrame() || camera.frame == NULL || camera.frame->buf == NULL || camera.frame->len == 0) {
    Serial.println("No camera frame available for enrollment photo upload.");
    return false;
  }

  String path = "/api/face-enrollment/device-photo/";
  path += sessionId;
  path += "?device_id=";
  path += deviceId;
  path += "&product_code=";
  path += productCode;
  path += "&photo_index=";
  path += String(photoIndex);
  path += "&device_photo_id=esp32s3-";
  path += sessionId;
  path += "-";
  path += String(photoIndex);

  int httpCode = -1;
  String response = postBinaryToWebsite(path, camera.frame->buf, camera.frame->len, "image/jpeg", httpCode);
  return httpCode == 200 && response.length() > 0;
}

void runFaceEnrollment(const String& sessionId, const String& personName, int requestedSamples) {
  if (sessionId.length() == 0 || personName.length() == 0) {
    return;
  }

  stopBuzzer();
  lockServo();
  showWaitingVerification();
  currentState = FACE_ENROLLING;

  int targetSamples = max(1, requestedSamples);
  int maxAttempts = max(targetSamples * MAX_ENROLLMENT_ATTEMPT_MULTIPLIER, targetSamples);
  int capturedSamples = 0;

  Serial.println();
  Serial.print("Face enrollment started for ");
  Serial.print(personName);
  Serial.print(" session ");
  Serial.println(sessionId);

  reportFaceEnrollmentResult(sessionId, "started", 0, "ESP32 is enrolling face samples.");

  for (int attempt = 1; attempt <= maxAttempts && capturedSamples < targetSamples; attempt++) {
    Serial.print("Enrollment capture attempt ");
    Serial.print(attempt);
    Serial.print(" / ");
    Serial.println(maxAttempts);

    if (!camera.capture().isOk()) {
      Serial.print("Capture error: ");
      Serial.println(camera.exception.toString());
      delay(FACE_ATTEMPT_DELAY_MS);
      continue;
    }

    if (!recognition.detect().isOk()) {
      Serial.println("No face detected for enrollment.");
      delay(FACE_ATTEMPT_DELAY_MS);
      continue;
    }

    if (!recognition.enroll(personName).isOk()) {
      Serial.print("Enrollment error: ");
      Serial.println(recognition.exception.toString());
      delay(FACE_ATTEMPT_DELAY_MS);
      continue;
    }

    capturedSamples++;
    Serial.print("Enrollment sample saved locally: ");
    Serial.print(capturedSamples);
    Serial.print(" / ");
    Serial.println(targetSamples);

    if (uploadCurrentEnrollmentPhoto(sessionId, capturedSamples)) {
      Serial.println("Enrollment photo uploaded.");
    } else {
      Serial.println("Enrollment photo upload failed.");
    }

    reportFaceEnrollmentResult(
      sessionId,
      "started",
      capturedSamples,
      "Captured enrollment sample " + String(capturedSamples) + " of " + String(targetSamples) + "."
    );
    delay(FACE_ATTEMPT_DELAY_MS);
  }

  if (capturedSamples >= targetSamples) {
    showVerificationSuccess();
    reportFaceEnrollmentResult(sessionId, "completed", capturedSamples, "Face enrollment completed and photos were linked to this account.");
    Serial.println("Face enrollment completed.");
  } else {
    showVerificationFailed();
    reportFaceEnrollmentResult(sessionId, "failed", capturedSamples, "Face enrollment failed before enough samples were captured.");
    Serial.println("Face enrollment failed.");
  }

  delay(800);
  allLightsOff();
  currentState = REMINDER_IDLE;
  lastFaceEnrollmentPoll = millis();
  lastReminderPoll = 0;
}

bool pollFaceEnrollmentCommand() {
  int httpCode = -1;
  String response = postToWebsite("/api/face-enrollment/device-command", devicePayload("poll_face_enrollment"), httpCode);
  if (httpCode != 200 || response.length() == 0) {
    return false;
  }

  String command = jsonStringValue(response, "command");
  if (command != "enroll") {
    return false;
  }

  String sessionId = jsonStringValue(response, "session_id");
  String personName = jsonStringValue(response, "person_name");
  int requestedSamples = jsonIntValue(response, "requested_samples", 3);
  runFaceEnrollment(sessionId, personName, requestedSamples);
  return true;
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
  loadRuntimeConfig();
  printRuntimeConfig();
  printSerialConfigHelp();

  Serial.print("Serial config window: ");
  Serial.print(SERIAL_CONFIG_WINDOW_MS / 1000);
  Serial.println(" seconds. Send commands now if the ngrok URL changed.");
  unsigned long configWindowStarted = millis();
  while (millis() - configWindowStarted < SERIAL_CONFIG_WINDOW_MS) {
    updateSerialConfigCommands();
    delay(20);
  }

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
    pollFaceEnrollmentCommand();
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
  updateSerialConfigCommands();
  updateBuzzer();
  updateDispensingFlow();
  updateServoAutoLock();

  if (currentState == REMINDER_IDLE
      && millis() - lastFaceEnrollmentPoll >= FACE_ENROLLMENT_COMMAND_POLL_MS) {
    lastFaceEnrollmentPoll = millis();
    pollFaceEnrollmentCommand();
  }

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
