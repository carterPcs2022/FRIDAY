// EDITH Glasses — ESP32-S3 Firmware V2
// Polls FRIDAY for medicine reminders, displays on OLED.
// V2: multi-network WiFi fallback via WiFiMulti.

#include <WiFi.h>
#include <WiFiMulti.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

WiFiMulti wifiMulti;

// ── CONFIG — add every network you might be near ────────
// Order doesn't matter — WiFiMulti automatically picks
// whichever configured network has the strongest signal
// that's actually in range.

struct NetworkInfo {
  const char* ssid;
  const char* password;
  const char* label;  // just for Serial Monitor debugging
};

NetworkInfo knownNetworks[] = {
  {"YOUR_HOME_WIFI_NAME",     "YOUR_HOME_WIFI_PASSWORD",     "Home"},
  {"YOUR_IPHONE_HOTSPOT_NAME","YOUR_HOTSPOT_PASSWORD",       "Phone Hotspot"},
  {"YOUR_SCHOOL_WIFI_NAME",   "YOUR_SCHOOL_WIFI_PASSWORD",   "School"},
  // Add more networks here as needed — just copy the
  // pattern above, comma-separated
};

const char* FRIDAY_URL = "https://friday-3k43.onrender.com/friday/hud/medicine";

// ── OLED setup ───────────────────────────────────────────
#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 32
#define OLED_RESET -1
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, OLED_RESET);

unsigned long lastCheck = 0;
const unsigned long CHECK_INTERVAL = 30000; // 30 seconds

void setup() {
  Serial.begin(115200);

  // Init OLED
  if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println("OLED init failed");
    for(;;);
  }
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 0);
  display.println("EDITH");
  display.println("Scanning networks...");
  display.display();

  // Register every known network with WiFiMulti
  int numNetworks = sizeof(knownNetworks) / sizeof(knownNetworks[0]);
  for (int i = 0; i < numNetworks; i++) {
    wifiMulti.addAP(knownNetworks[i].ssid, knownNetworks[i].password);
    Serial.print("Registered network: ");
    Serial.println(knownNetworks[i].label);
  }

  Serial.println("Connecting to best available network...");
  int attempts = 0;
  while (wifiMulti.run() != WL_CONNECTED && attempts < 30) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  display.clearDisplay();
  display.setCursor(0, 0);
  if (WiFi.status() == WL_CONNECTED) {
    display.println("EDITH online");
    display.println(WiFi.SSID());
    Serial.println("\nConnected to: " + WiFi.SSID());
    Serial.println("IP: " + WiFi.localIP().toString());
  } else {
    display.println("No known WiFi");
    display.println("in range");
    Serial.println("\nNo known network found in range");
  }
  display.display();
  delay(2000);
}

void loop() {
  unsigned long now = millis();

  // WiFiMulti.run() automatically handles reconnection
  // and switching networks if the current one drops —
  // call it every loop to keep the connection maintained
  if (wifiMulti.run() != WL_CONNECTED) {
    showMessage("Searching", "for WiFi...");
    delay(2000);
    return;
  }

  if (now - lastCheck >= CHECK_INTERVAL || lastCheck == 0) {
    lastCheck = now;
    checkFriday();
  }

  delay(100);
}

void checkFriday() {
  if (WiFi.status() != WL_CONNECTED) {
    showMessage("WiFi lost", "reconnecting...");
    WiFi.reconnect();
    return;
  }

  // FRIDAY_URL is https:// (Render) — HTTPClient's plain begin(url)
  // won't complete a TLS handshake without a client that either has a
  // root CA or is told to skip verification. This is a self-hosted
  // reminder tool, not something handling payment data, so skipping
  // cert verification (setInsecure()) is an acceptable tradeoff to
  // avoid tracking Render's CA cert lifecycle on the device.
  WiFiClientSecure client;
  client.setInsecure();

  HTTPClient http;
  http.begin(client, FRIDAY_URL);
  http.setTimeout(10000);

  int httpCode = http.GET();

  if (httpCode == 200) {
    String payload = http.getString();

    StaticJsonDocument<1024> doc;
    DeserializationError error = deserializeJson(doc, payload);

    if (!error) {
      JsonArray due = doc["due"];
      JsonArray missed = doc["missed"];

      if (missed.size() > 0) {
        // Missed dose takes priority — show it
        JsonObject item = missed[0];
        String name = item["name"].as<String>();
        int minutesLate = item["minutes_late"].as<int>();
        showMessage("MISSED: " + name,
                    String(minutesLate) + " min late");
      }
      else if (due.size() > 0) {
        // Show the first due medicine
        JsonObject item = due[0];
        String name = item["name"].as<String>();
        String dosage = item["dosage"].as<String>();
        showMessage("TAKE: " + name, dosage);
      }
      else {
        showIdleScreen();
      }
    } else {
      showMessage("Parse error", "");
    }
  } else {
    showMessage("Connection", "error " + String(httpCode));
  }

  http.end();
}

void showMessage(String line1, String line2) {
  display.clearDisplay();
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println("EDITH");
  display.drawLine(0, 10, 128, 10, SSD1306_WHITE);
  display.setCursor(0, 14);
  display.setTextSize(1);
  display.println(line1);
  display.setCursor(0, 24);
  display.println(line2);
  display.display();

  Serial.println(line1 + " | " + line2);
}

void showIdleScreen() {
  display.clearDisplay();
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println("EDITH");
  display.drawLine(0, 10, 128, 10, SSD1306_WHITE);
  display.setCursor(0, 16);
  display.println("All clear, boss.");
  display.display();
}
