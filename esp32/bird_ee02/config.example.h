#pragma once

// Copy this file to config.h, then edit the three values below.
constexpr char WIFI_SSID[] = "YOUR_WIFI_NAME";
constexpr char WIFI_PASSWORD[] = "YOUR_WIFI_PASSWORD";
constexpr char IMAGE_URL[] =
    "https://jffkm.github.io/bird-ee02-dashboard/today.jpg";

// Leave this false for the first bench test so the serial monitor stays open.
// Set it true after the display updates successfully.
constexpr bool ENABLE_DEEP_SLEEP = false;

constexpr uint32_t REFRESH_MINUTES = 24U * 60U;
constexpr uint32_t ERROR_RETRY_MINUTES = 30U;
