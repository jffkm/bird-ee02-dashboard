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

// Wake for a successful daily refresh at 7:00 AM Pacific time. This POSIX time
// zone rule automatically switches between PST and PDT.
constexpr char TIMEZONE_RULE[] = "PST8PDT,M3.2.0/2,M11.1.0/2";
constexpr uint8_t DAILY_REFRESH_HOUR = 7;
constexpr uint8_t DAILY_REFRESH_MINUTE = 0;

// Used only if NTP time synchronization fails. Failed image/display attempts
// keep the existing e-paper image visible and use the shorter retry interval.
constexpr uint32_t REFRESH_FALLBACK_MINUTES = 24U * 60U;
constexpr uint32_t ERROR_RETRY_MINUTES = 6U * 60U;
