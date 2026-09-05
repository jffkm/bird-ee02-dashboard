#pragma once

// Copy this file to config.h, then enter your 2.4 GHz Wi-Fi credentials.
constexpr char WIFI_SSID[] = "YOUR_WIFI_NAME";
constexpr char WIFI_PASSWORD[] = "YOUR_WIFI_PASSWORD";

// Pick one image. GitHub Pages replaces both files each morning, while these
// URLs stay constant, so the ESP32 does not need to understand the catalog.
constexpr char DASHBOARD_IMAGE_URL[] =
    "https://jffkm.github.io/bird-ee02-dashboard/today.jpg";
constexpr char BIRD_PLATE_IMAGE_URL[] =
    "https://jffkm.github.io/bird-ee02-dashboard/birdplate.jpg";
constexpr bool SHOW_BIRD_PLATE = false;
constexpr const char *IMAGE_URL =
    SHOW_BIRD_PLATE ? BIRD_PLATE_IMAGE_URL : DASHBOARD_IMAGE_URL;

// Leave this false for the first bench test so the serial monitor stays open.
// Set it true after the display updates successfully.
constexpr bool ENABLE_DEEP_SLEEP = false;

// Deep sleep is a relative timer. Upload or reset the board at the morning
// time when you want it to refresh; it will wake about every 24 hours after.
constexpr uint32_t REFRESH_MINUTES = 24U * 60U;
constexpr uint32_t ERROR_RETRY_MINUTES = 6U * 60U;
