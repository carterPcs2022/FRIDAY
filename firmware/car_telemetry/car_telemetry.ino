// FRIDAY Car Telemetry — ESP32 Firmware
// Reads live OBD-II data over a Bluetooth ELM327 dongle, posts it to
// FRIDAY. Read-only: fuel level, RPM, speed, coolant temp, trouble
// codes. OBD-II has no standard PIDs for locks/starter — this cannot
// and will not control the vehicle.
//
// BOARD: needs a plain ESP32 (WROOM-32 / DevKitC), NOT an ESP32-S3 —
// the S3 dropped classic Bluetooth (BR/EDR) and only has BLE, but
// most $15-20 ELM327 dongles are classic-Bluetooth SPP, not BLE.
//
// SETUP PER CAR: change VEHICLE_NAME below and flash one ESP32 per
// vehicle — one board living in the Maxima, a separate one in the
// Murano, both pointed at the same FRIDAY_URL.

#include <BluetoothSerial.h>
#include <WiFi.h>
#include <WiFiMulti.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// ── CONFIG ────────────────────────────────────────────────
const char* VEHICLE_NAME = "Murano";           // "Murano" or "Maxima" — set per board
const char* ELM327_NAME  = "OBDII";            // Bluetooth device name of your dongle
const char* FRIDAY_URL   = "https://friday-3k43.onrender.com/friday/car/report";

const unsigned long POLL_INTERVAL_MS = 20000;   // fuel/RPM/speed/temp
const unsigned long DTC_INTERVAL_MS  = 300000;  // check-engine codes, checked less often

struct NetworkInfo {
  const char* ssid;
  const char* password;
  const char* label;
};

NetworkInfo knownNetworks[] = {
  {"YOUR_HOME_WIFI_NAME",      "YOUR_HOME_WIFI_PASSWORD",      "Home"},
  {"YOUR_IPHONE_HOTSPOT_NAME", "YOUR_HOTSPOT_PASSWORD",        "Phone Hotspot"},
  // A parked-at-home-only setup is fine for v1 — add a phone hotspot
  // entry above if you want readings to reach FRIDAY while driving too.
};

BluetoothSerial SerialBT;
WiFiMulti wifiMulti;

unsigned long lastPoll = 0;
unsigned long lastDtcPoll = 0;
bool obdConnected = false;

void setup() {
  Serial.begin(115200);

  int numNetworks = sizeof(knownNetworks) / sizeof(knownNetworks[0]);
  for (int i = 0; i < numNetworks; i++) {
    wifiMulti.addAP(knownNetworks[i].ssid, knownNetworks[i].password);
  }

  SerialBT.begin("FRIDAY-OBD", true);  // true = master mode, we initiate the connection
  connectObd();
}

void loop() {
  if (!obdConnected) {
    connectObd();
    delay(2000);
    return;
  }

  unsigned long now = millis();

  if (now - lastPoll >= POLL_INTERVAL_MS || lastPoll == 0) {
    lastPoll = now;
    pollAndReport(false);
  } else if (now - lastDtcPoll >= DTC_INTERVAL_MS) {
    lastDtcPoll = now;
    pollAndReport(true);
  }

  delay(200);
}

void connectObd() {
  Serial.println("Connecting to ELM327...");
  if (SerialBT.connect(ELM327_NAME)) {
    obdInit();
    obdConnected = true;
    Serial.println("OBD connected.");
  } else {
    Serial.println("OBD connect failed, retrying...");
    obdConnected = false;
  }
}

void obdInit() {
  sendObdCommand("ATZ");   // reset
  delay(1000);
  sendObdCommand("ATE0");  // echo off
  sendObdCommand("ATSP0"); // auto-detect protocol
}

// Sends a command, reads until the '>' prompt ELM327 uses to signal
// "done", strips it, returns the raw response.
String sendObdCommand(const char* cmd) {
  SerialBT.print(cmd);
  SerialBT.print("\r");

  String response = "";
  unsigned long start = millis();
  while (millis() - start < 3000) {
    if (SerialBT.available()) {
      char c = SerialBT.read();
      if (c == '>') break;
      response += c;
    }
  }
  response.trim();
  return response;
}

// Extracts the hex data bytes from a "41 0C 1A F8"-style response,
// skipping the two-byte mode/PID echo.
bool parsePidBytes(String response, int expectedBytes, int* out) {
  response.replace("\r", " ");
  response.replace("\n", " ");
  response.trim();

  int values[8];
  int count = 0;
  int start = 0;
  while (start < response.length() && count < 8) {
    int space = response.indexOf(' ', start);
    String token = (space == -1) ? response.substring(start) : response.substring(start, space);
    token.trim();
    if (token.length() > 0) {
      values[count++] = strtol(token.c_str(), NULL, 16);
    }
    if (space == -1) break;
    start = space + 1;
  }

  // Expect at least mode-echo + PID-echo + expectedBytes of data.
  if (count < 2 + expectedBytes) return false;
  for (int i = 0; i < expectedBytes; i++) {
    out[i] = values[2 + i];
  }
  return true;
}

float readRpm() {
  int b[2];
  if (!parsePidBytes(sendObdCommand("010C"), 2, b)) return -1;
  return ((b[0] * 256) + b[1]) / 4.0;
}

float readSpeed() {
  int b[1];
  if (!parsePidBytes(sendObdCommand("010D"), 1, b)) return -1;
  return b[0];  // km/h
}

float readFuelLevel() {
  int b[1];
  if (!parsePidBytes(sendObdCommand("012F"), 1, b)) return -1;
  return b[0] * 100.0 / 255.0;  // percent
}

float readCoolantTemp() {
  int b[1];
  if (!parsePidBytes(sendObdCommand("0105"), 1, b)) return -1;
  return b[0] - 40;  // Celsius
}

// Mode 03 returns 0-3 stored trouble codes per line as two-byte pairs.
// First two bits of the high byte pick the code family (P/C/B/U);
// the rest is the four-digit code, e.g. 0x0143 -> "P0143".
String decodeDtc(int high, int low) {
  const char* families[] = {"P", "C", "B", "U"};
  String family = families[(high >> 6) & 0x03];
  char code[6];
  snprintf(code, sizeof(code), "%s%04X", family.c_str(), ((high & 0x3F) << 8) | low);
  return String(code);
}

void readDtcCodes(JsonArray& out) {
  String response = sendObdCommand("03");
  response.replace("\r", " ");
  response.trim();

  // Strip the "43" mode-echo prefix if present, then walk byte pairs.
  int values[32];
  int count = 0;
  int start = 0;
  while (start < response.length() && count < 32) {
    int space = response.indexOf(' ', start);
    String token = (space == -1) ? response.substring(start) : response.substring(start, space);
    token.trim();
    if (token.length() > 0) values[count++] = strtol(token.c_str(), NULL, 16);
    if (space == -1) break;
    start = space + 1;
  }

  for (int i = 1; i + 1 < count; i += 2) {
    if (values[i] == 0 && values[i + 1] == 0) continue;  // padding
    out.add(decodeDtc(values[i], values[i + 1]));
  }
}

void pollAndReport(bool includeDtc) {
  StaticJsonDocument<512> doc;
  doc["vehicle"] = VEHICLE_NAME;

  float fuel = readFuelLevel();
  float rpm = readRpm();
  float speed = readSpeed();
  float temp = readCoolantTemp();

  if (fuel >= 0) doc["fuel_level"] = fuel;
  if (rpm >= 0) doc["rpm"] = rpm;
  if (speed >= 0) doc["speed"] = speed;
  if (temp > -40) doc["coolant_temp"] = temp;

  if (includeDtc) {
    JsonArray codes = doc.createNestedArray("dtc_codes");
    readDtcCodes(codes);
  }

  postToFriday(doc);
}

void postToFriday(JsonDocument& doc) {
  if (wifiMulti.run() != WL_CONNECTED) {
    Serial.println("No WiFi — skipping this report.");
    return;
  }

  String payload;
  serializeJson(doc, payload);

  // Same tradeoff as edith_glasses.ino: skip TLS cert verification
  // rather than track Render's CA cert lifecycle on the device. This
  // is read-only telemetry, not payment data.
  WiFiClientSecure client;
  client.setInsecure();

  HTTPClient http;
  http.begin(client, FRIDAY_URL);
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(10000);

  int httpCode = http.POST(payload);
  Serial.printf("Reported to FRIDAY: %d\n", httpCode);
  http.end();
}
