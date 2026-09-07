/*
 * Bird of the Day for:
 *   - Seeed Studio XIAO ESP32-S3 Plus
 *   - XIAO ePaper Display Board EE02
 *   - 13.3-inch Spectra 6 / T133A01 panel
 *
 * The device downloads one 1200x1600 JPEG from GitHub Pages, maps its pixels
 * to the panel's six colors, refreshes the panel, and sleeps until the next
 * configured local refresh time.
 */

#include <Arduino.h>

#include "driver.h"

#if __has_include("config.h")
#include "config.h"
#else
#include "config.example.h"
#endif

#include <HTTPClient.h>
#include <JPEGDEC.h>
#include <NetworkClient.h>
#include <TFT_eSPI.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <esp_heap_caps.h>
#include <esp_sleep.h>
#include <time.h>

namespace {

constexpr int PANEL_WIDTH = 1200;
constexpr int PANEL_HEIGHT = 1600;
constexpr size_t FRAMEBUFFER_BYTES =
    static_cast<size_t>(PANEL_WIDTH) * PANEL_HEIGHT / 2;
constexpr size_t MAX_JPEG_BYTES = 4U * 1024U * 1024U;
constexpr uint32_t WIFI_TIMEOUT_MS = 30000;
constexpr uint32_t DOWNLOAD_IDLE_TIMEOUT_MS = 30000;
constexpr uint32_t NTP_TIMEOUT_MS = 20000;
constexpr char PRIMARY_NTP_SERVER[] = "pool.ntp.org";
constexpr char SECONDARY_NTP_SERVER[] = "time.nist.gov";

struct PaletteColor {
  uint8_t r;
  uint8_t g;
  uint8_t b;
  uint8_t panelCode;
};

// Raw four-bit color codes expected by Seeed's T133A01 driver.
constexpr PaletteColor PANEL_PALETTE[] = {
    {255, 255, 255, 0x0},  // white
    {29, 185, 84, 0x2},    // green
    {229, 57, 53, 0x6},    // red
    {255, 216, 0, 0xB},    // yellow
    {0, 76, 255, 0xD},     // blue
    {0, 0, 0, 0xF},        // black
};

EPaper epaper;
JPEGDEC jpeg;
uint8_t *framebuffer = nullptr;

bool configurationIsReady() {
  const String ssid(WIFI_SSID);
  const String url(IMAGE_URL);
  if (ssid.isEmpty() || ssid.startsWith("YOUR_")) {
    Serial.println("[config] Copy config.example.h to config.h and set Wi-Fi credentials");
    return false;
  }
  if (!url.startsWith("https://") || !url.endsWith(".jpg")) {
    Serial.println("[config] IMAGE_URL must be an HTTPS URL ending in .jpg");
    return false;
  }
  if (String(TIMEZONE_RULE).isEmpty() || DAILY_REFRESH_HOUR > 23 ||
      DAILY_REFRESH_MINUTE > 59) {
    Serial.println("[config] Time zone or daily refresh time is invalid");
    return false;
  }
  return true;
}

bool connectToWifi() {
  Serial.printf("[wifi] Connecting to %s", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  const uint32_t startedAt = millis();
  while (WiFi.status() != WL_CONNECTED &&
         millis() - startedAt < WIFI_TIMEOUT_MS) {
    delay(500);
    Serial.print('.');
  }
  Serial.println();

  if (WiFi.status() != WL_CONNECTED) {
    Serial.printf("[wifi] Connection failed (status %d)\n", WiFi.status());
    return false;
  }

  Serial.printf("[wifi] Connected: %s, RSSI %d dBm\n",
                WiFi.localIP().toString().c_str(), WiFi.RSSI());
  return true;
}

bool syncClock() {
  Serial.println("[time] Synchronizing clock with NTP");
  configTzTime(TIMEZONE_RULE, PRIMARY_NTP_SERVER, SECONDARY_NTP_SERVER);

  struct tm localTime = {};
  if (!getLocalTime(&localTime, NTP_TIMEOUT_MS)) {
    Serial.println("[time] NTP sync failed; using the fallback sleep interval");
    return false;
  }

  char timestamp[48] = {};
  strftime(timestamp, sizeof(timestamp), "%Y-%m-%d %H:%M:%S %Z", &localTime);
  Serial.printf("[time] Local time: %s\n", timestamp);
  return true;
}

bool calculateNextDailyWake(uint64_t &wakeAfterUs, char *target,
                            size_t targetSize) {
  const time_t now = time(nullptr);
  struct tm nextLocal = {};
  if (now < 0 || localtime_r(&now, &nextLocal) == nullptr) {
    return false;
  }

  nextLocal.tm_hour = DAILY_REFRESH_HOUR;
  nextLocal.tm_min = DAILY_REFRESH_MINUTE;
  nextLocal.tm_sec = 0;
  nextLocal.tm_isdst = -1;

  time_t nextWake = mktime(&nextLocal);
  if (nextWake == static_cast<time_t>(-1)) {
    return false;
  }
  if (nextWake <= now) {
    nextLocal.tm_mday += 1;
    nextLocal.tm_hour = DAILY_REFRESH_HOUR;
    nextLocal.tm_min = DAILY_REFRESH_MINUTE;
    nextLocal.tm_sec = 0;
    nextLocal.tm_isdst = -1;
    nextWake = mktime(&nextLocal);
  }

  if (nextWake == static_cast<time_t>(-1) || nextWake <= now) {
    return false;
  }

  const uint64_t seconds = static_cast<uint64_t>(nextWake - now);
  wakeAfterUs = seconds * 1000000ULL;
  if (target != nullptr && targetSize > 0) {
    strftime(target, targetSize, "%Y-%m-%d %H:%M:%S %Z", &nextLocal);
  }
  return true;
}

bool downloadJpeg(uint8_t *&data, size_t &size) {
  WiFiClientSecure client;
  client.setInsecure();  // Public image only; see esp32/README.md.

  HTTPClient http;
  http.setConnectTimeout(10000);
  http.setTimeout(DOWNLOAD_IDLE_TIMEOUT_MS);
  http.setFollowRedirects(HTTPC_STRICT_FOLLOW_REDIRECTS);
  http.setUserAgent("bird-ee02-dashboard/1.0");

  if (!http.begin(client, IMAGE_URL)) {
    Serial.println("[image] Could not start HTTPS request");
    return false;
  }
  http.addHeader("Cache-Control", "no-cache");

  const int status = http.GET();
  if (status != HTTP_CODE_OK) {
    Serial.printf("[image] Download failed: HTTP %d\n", status);
    http.end();
    return false;
  }

  const int contentLength = http.getSize();
  if (contentLength <= 0 ||
      static_cast<size_t>(contentLength) > MAX_JPEG_BYTES) {
    Serial.printf("[image] Invalid Content-Length: %d\n", contentLength);
    http.end();
    return false;
  }

  data = static_cast<uint8_t *>(heap_caps_malloc(
      static_cast<size_t>(contentLength), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
  if (data == nullptr) {
    Serial.printf("[image] Could not allocate %d bytes in PSRAM\n", contentLength);
    http.end();
    return false;
  }

  NetworkClient *stream = http.getStreamPtr();
  size_t received = 0;
  uint32_t lastDataAt = millis();

  while (received < static_cast<size_t>(contentLength)) {
    const size_t available = stream->available();
    if (available > 0) {
      const size_t wanted = min(
          available, static_cast<size_t>(contentLength) - received);
      const int count = stream->readBytes(data + received, wanted);
      if (count <= 0) {
        break;
      }
      received += static_cast<size_t>(count);
      lastDataAt = millis();
    } else if (millis() - lastDataAt > DOWNLOAD_IDLE_TIMEOUT_MS) {
      Serial.println("[image] Download timed out");
      break;
    } else {
      delay(1);
    }
  }

  http.end();
  if (received != static_cast<size_t>(contentLength)) {
    Serial.printf("[image] Received %lu of %d bytes\n",
                  static_cast<unsigned long>(received), contentLength);
    heap_caps_free(data);
    data = nullptr;
    return false;
  }

  size = received;
  Serial.printf("[image] Downloaded %lu bytes\n",
                static_cast<unsigned long>(size));
  return true;
}

uint8_t nearestPanelColor(uint8_t r, uint8_t g, uint8_t b) {
  uint32_t bestDistance = UINT32_MAX;
  uint8_t bestCode = 0x0;

  for (const PaletteColor &candidate : PANEL_PALETTE) {
    const int dr = static_cast<int>(r) - candidate.r;
    const int dg = static_cast<int>(g) - candidate.g;
    const int db = static_cast<int>(b) - candidate.b;
    const uint32_t distance = dr * dr + dg * dg + db * db;
    if (distance < bestDistance) {
      bestDistance = distance;
      bestCode = candidate.panelCode;
    }
  }
  return bestCode;
}

void setPackedPixel(int x, int y, uint8_t colorCode) {
  const size_t offset =
      static_cast<size_t>(y) * (PANEL_WIDTH / 2) + (x / 2);
  if ((x & 1) == 0) {
    framebuffer[offset] = static_cast<uint8_t>(
        (framebuffer[offset] & 0x0F) | (colorCode << 4));
  } else {
    framebuffer[offset] = static_cast<uint8_t>(
        (framebuffer[offset] & 0xF0) | colorCode);
  }
}

int drawJpegBlock(JPEGDRAW *draw) {
  for (int blockY = 0; blockY < draw->iHeight; ++blockY) {
    const int y = draw->y + blockY;
    if (y < 0 || y >= PANEL_HEIGHT) {
      continue;
    }

    for (int blockX = 0; blockX < draw->iWidth; ++blockX) {
      const int x = draw->x + blockX;
      if (x < 0 || x >= PANEL_WIDTH) {
        continue;
      }

      const uint16_t pixel =
          draw->pPixels[blockY * draw->iWidth + blockX];
      const uint8_t r = ((pixel >> 11) & 0x1F) * 255 / 31;
      const uint8_t g = ((pixel >> 5) & 0x3F) * 255 / 63;
      const uint8_t b = (pixel & 0x1F) * 255 / 31;
      setPackedPixel(x, y, nearestPanelColor(r, g, b));
    }
  }
  return 1;
}

bool displayJpeg(uint8_t *data, size_t size) {
  epaper.begin();
  if (epaper.width() != PANEL_WIDTH || epaper.height() != PANEL_HEIGHT) {
    Serial.printf("[panel] Expected %dx%d, got %dx%d\n", PANEL_WIDTH,
                  PANEL_HEIGHT, epaper.width(), epaper.height());
    return false;
  }

  framebuffer = static_cast<uint8_t *>(epaper.getPointer());
  if (framebuffer == nullptr) {
    Serial.println("[panel] Framebuffer unavailable; enable OPI PSRAM");
    return false;
  }
  memset(framebuffer, 0x00, FRAMEBUFFER_BYTES);

  if (!jpeg.openRAM(data, static_cast<int>(size), drawJpegBlock)) {
    Serial.printf("[panel] JPEG open failed: %d\n", jpeg.getLastError());
    return false;
  }
  if (jpeg.getWidth() != PANEL_WIDTH || jpeg.getHeight() != PANEL_HEIGHT) {
    Serial.printf("[panel] Expected a %dx%d JPEG, got %dx%d\n", PANEL_WIDTH,
                  PANEL_HEIGHT, jpeg.getWidth(), jpeg.getHeight());
    jpeg.close();
    return false;
  }

  jpeg.setPixelType(RGB565_LITTLE_ENDIAN);
  Serial.println("[panel] Decoding JPEG");
  const bool decoded = jpeg.decode(0, 0, 0);
  const int decodeError = jpeg.getLastError();
  jpeg.close();
  if (!decoded) {
    Serial.printf("[panel] JPEG decode failed: %d\n", decodeError);
    return false;
  }

  Serial.println("[panel] Refreshing display; this can take tens of seconds");
  epaper.update();
  epaper.sleep();
  Serial.println("[panel] Refresh complete");
  return true;
}

void finishCycle(bool succeeded, bool clockSynced) {
  WiFi.disconnect(true);
  WiFi.mode(WIFI_OFF);

  uint64_t wakeAfterUs = 0;
  bool usingDailySchedule = false;

  if (succeeded && clockSynced) {
    char target[48] = {};
    usingDailySchedule =
        calculateNextDailyWake(wakeAfterUs, target, sizeof(target));
    if (usingDailySchedule) {
      Serial.printf("[power] Success; next refresh at %s\n", target);
    }
  }

  if (!usingDailySchedule) {
    const uint32_t minutes =
        succeeded ? REFRESH_FALLBACK_MINUTES : ERROR_RETRY_MINUTES;
    const uint32_t safeMinutes = minutes > 0 ? minutes : 1;
    wakeAfterUs =
        static_cast<uint64_t>(safeMinutes) * 60ULL * 1000000ULL;
    Serial.printf("[power] %s; next attempt in %lu minutes\n",
                  succeeded ? "Success without a synchronized clock"
                            : "Failed; existing display retained",
                  static_cast<unsigned long>(safeMinutes));
  }
  Serial.flush();

  if (ENABLE_DEEP_SLEEP) {
    esp_sleep_enable_timer_wakeup(wakeAfterUs);
    esp_deep_sleep_start();
  }

  Serial.println("[power] Deep sleep is disabled for bench testing");
  while (true) {
    delay(1000);
  }
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(1500);
  Serial.println("\nBird EE02 Dashboard");
  Serial.printf("[memory] PSRAM: %lu bytes\n",
                static_cast<unsigned long>(ESP.getPsramSize()));

  bool succeeded = false;
  bool clockSynced = false;
  uint8_t *jpegData = nullptr;
  size_t jpegSize = 0;

  if (!psramFound()) {
    Serial.println("[memory] PSRAM not found; select OPI PSRAM in Arduino IDE");
  } else if (!configurationIsReady()) {
    Serial.println("[config] Configuration is incomplete");
  } else if (connectToWifi()) {
    clockSynced = syncClock();
    if (downloadJpeg(jpegData, jpegSize)) {
      succeeded = displayJpeg(jpegData, jpegSize);
    }
  }

  if (jpegData != nullptr) {
    heap_caps_free(jpegData);
  }
  finishCycle(succeeded, clockSynced);
}

void loop() {}
