#pragma once

// Copy this file to config.h, then enter your 2.4 GHz Wi-Fi credentials.
constexpr char WIFI_SSID[] = "YOUR_WIFI_NAME";
constexpr char WIFI_PASSWORD[] = "YOUR_WIFI_PASSWORD";

// GitHub Pages replaces these files each morning while their URLs stay fixed.
// DAILY_FRAME_IMAGE_URL makes one stable 50/50 dashboard-or-plate choice per day.
constexpr char DAILY_FRAME_IMAGE_URL[] =
    "https://jffkm.github.io/bird-ee02-dashboard/frame.jpg";
constexpr char DASHBOARD_IMAGE_URL[] =
    "https://jffkm.github.io/bird-ee02-dashboard/today.jpg";
constexpr char BIRD_PLATE_IMAGE_URL[] =
    "https://jffkm.github.io/bird-ee02-dashboard/birdplate.jpg";
constexpr const char *IMAGE_URL = DAILY_FRAME_IMAGE_URL;
// To lock the device to one style, use DASHBOARD_IMAGE_URL or
// BIRD_PLATE_IMAGE_URL instead.

// Leave this false for the first bench test so the serial monitor stays open.
// Set it true after the display updates successfully.
constexpr bool ENABLE_DEEP_SLEEP = false;

// Deep sleep is a relative timer. Upload or reset the board at the morning
// time when you want it to refresh; it will wake about every 24 hours after.
constexpr uint32_t REFRESH_MINUTES = 24U * 60U;
constexpr uint32_t ERROR_RETRY_MINUTES = 6U * 60U;
