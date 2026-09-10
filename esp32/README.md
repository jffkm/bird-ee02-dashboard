# ESP32 + Seeed EE02 deployment

This folder is the Arduino IDE implementation for the Seeed Studio XIAO
ESP32-S3 Plus, EE02 controller board, and 13.3-inch Spectra 6/T133A01 panel.
It is intentionally a simple network picture frame:

1. Connect to Wi-Fi.
2. Synchronize the clock over NTP.
3. Download `frame.jpg`, GitHub's daily dashboard-or-plate selection.
4. Decode it into the EE02 six-color framebuffer.
5. Refresh the panel.
6. Deep-sleep until 7:00 AM Pacific the next day.

Dashboard composition and bird-plate selection, resizing, and six-color
dithering all happen in GitHub Actions. Both published ESP32 images are exactly
`1200x1600`, so the battery-powered board only downloads and decodes a JPEG.

## 1. Prepare the Wi-Fi network

- Use a **2.4 GHz** Wi-Fi network. The ESP32-S3 cannot join a 5 GHz-only SSID.
- Use a normal password-protected home or IoT network without a browser-based
  captive portal.
- Keep the SSID and password handy; both are case-sensitive.
- For the first test, place the board near the access point and leave it on
  USB power.

## 2. Arduino IDE setup

Install these libraries:

- `Seeed_GFX` 2.0.3 or newer, using Seeed's GitHub/ZIP installation described
  in the EE02 setup guide
- `JPEGDEC` by Larry Bank, using **Tools > Manage Libraries**

Select the board and options:

- Board: **XIAO ESP32S3 Plus**
- PSRAM: **OPI PSRAM**
- USB CDC On Boot: **Enabled** for easier serial diagnostics

No custom partition table or filesystem is required.

## 3. Configure the image and Wi-Fi

1. Open `esp32/bird_ee02/bird_ee02.ino` in Arduino IDE.
2. Copy `config.example.h` to `config.h` in the same sketch folder.
3. Put the network name inside `WIFI_SSID` and its password inside
   `WIFI_PASSWORD`. Do not remove the quotation marks.
4. Leave `IMAGE_URL` set to `DAILY_FRAME_IMAGE_URL` for a daily 50/50 choice.
   To lock the frame to one style, set it to `DASHBOARD_IMAGE_URL` or
   `BIRD_PLATE_IMAGE_URL` instead.
5. Leave `ENABLE_DEEP_SLEEP` set to `false` for the first upload.

The relevant part of `config.h` should look like this:

```cpp
constexpr char WIFI_SSID[] = "Your 2.4 GHz network name";
constexpr char WIFI_PASSWORD[] = "Your Wi-Fi password";
constexpr const char *IMAGE_URL = DAILY_FRAME_IMAGE_URL;
constexpr bool ENABLE_DEEP_SLEEP = false;
```

The complete URLs and sleep intervals already come from the copied example.
`config.h` is ignored by Git, so your credentials will not be committed.

## 4. First upload and Wi-Fi test

1. Connect the EE02 board to the computer over USB-C and turn its power switch
   on.
2. Select **Tools > Board > XIAO ESP32S3 Plus**.
3. Select **Tools > PSRAM > OPI PSRAM**.
4. Set **USB CDC On Boot > Enabled**, then select the board's serial port.
5. Click **Upload**.
6. Open **Tools > Serial Monitor**, select **115200 baud**, and press the EE02
   reset button once if no output appears.
7. Wait for `[wifi] Connected`, `[image] Downloaded`, and `[panel] Refresh
   complete`. A Spectra 6 refresh can take tens of seconds.

If Wi-Fi fails, recheck the exact SSID/password and verify the network supports
2.4 GHz. The printed Wi-Fi status is also listed in the troubleshooting section
below.

## 5. Enable the daily deep-sleep cycle

1. Change `ENABLE_DEEP_SLEEP` to `true` in `config.h`.
2. Keep the default Pacific time-zone rule and 7:00 AM refresh time, or adjust
   them if the frame will be used in a different location.
3. Upload this final version at any time.
4. Let the first image finish. The sketch then sleeps the panel, turns Wi-Fi
   off, and puts the ESP32-S3 into timer deep sleep until the next 7:00 AM.

On every wake, the board gets local time from an internet time server and
recalculates the interval to the next 7:00 AM. The refresh therefore does not
drift later by the time spent connecting, downloading, and updating the panel.
The supplied Pacific time-zone rule also handles the PST/PDT transition.
Pressing reset or uploading new firmware still causes one immediate refresh;
afterward, the device returns to the 7:00 AM schedule. If time synchronization
fails after a successful update, it falls back to 24 hours. If a download or
display update fails, the old e-paper image remains visible and the default
configuration retries after six hours.

The scheduling values in `config.h` are:

```cpp
constexpr char TIMEZONE_RULE[] = "PST8PDT,M3.2.0/2,M11.1.0/2";
constexpr uint8_t DAILY_REFRESH_HOUR = 7;
constexpr uint8_t DAILY_REFRESH_MINUTE = 0;
constexpr uint32_t REFRESH_FALLBACK_MINUTES = 24U * 60U;
constexpr uint32_t ERROR_RETRY_MINUTES = 6U * 60U;
```

GitHub schedules the new image for 12:37 AM Pacific using an explicit
`America/Los_Angeles` time zone. That leaves more than six hours for delayed
Actions runs and the Pages deployment before the frame requests it at 7:00 AM.

## 6. Move to battery power

1. Use a protected, single-cell **3.7 V Li-ion/LiPo** battery with the EE02's
   **JST 2.0 mm 2-pin** connector. Verify the connector polarity before plugging
   it in; JST housings from different vendors are not always wired alike.
2. Charge through USB-C with the battery connected, using the EE02's onboard
   charging circuit.
3. Disconnect USB-C and leave the EE02 battery switch on.
4. Confirm one final wake/update cycle. The e-paper image remains visible while
   the ESP32 and panel electronics sleep.

Actual battery life depends heavily on cell capacity, Wi-Fi signal quality,
panel refresh current, and the EE02 board's regulator losses. Measure current on
your finished assembly before relying on a runtime estimate.

## Published image URLs

For this repository, the Pages image URL is:

```text
https://jffkm.github.io/bird-ee02-dashboard/today.jpg
https://jffkm.github.io/bird-ee02-dashboard/birdplate.jpg
https://jffkm.github.io/bird-ee02-dashboard/frame.jpg
```

Use `frame.jpg` for the daily mix. You can preview all three URLs in a browser;
their filenames stay the same while GitHub replaces their content each morning.

## HTTPS note

The sketch uses TLS encryption without certificate validation to keep this
public-image appliance small and avoid maintaining a root certificate in
firmware. Someone able to intercept the network connection could substitute
the displayed image. Do not reuse this pattern for credentials or private data.

## Expected serial output

```text
Bird EE02 Dashboard
[wifi] Connected: ...
[time] Synchronizing clock with NTP
[time] Local time: ...
[image] Downloaded ... bytes
[panel] Decoding JPEG
[panel] Refreshing display; this can take tens of seconds
[panel] Refresh complete
[power] Success; next refresh at ... 07:00:00 PDT
```

If the download or decode fails, the sketch does not refresh the panel, so the
previous e-paper image remains visible.

## Troubleshooting

- `Configuration is incomplete`: `config.h` is missing, or the SSID still
  starts with `YOUR_`.
- Wi-Fi status `1` (`WL_NO_SSID_AVAIL`): wrong SSID, insufficient signal, or a
  5 GHz-only network.
- Wi-Fi status `4` (`WL_CONNECT_FAILED`): usually a wrong password or unsupported
  network authentication.
- `NTP sync failed`: confirm the network allows internet time traffic. The
  image still updates and the board uses the 24-hour fallback interval.
- `Invalid Content-Length`: the URL did not return the expected JPEG or the
  image exceeded the 4 MiB safety limit.
- `PSRAM not found`: select **OPI PSRAM** and upload again.
- Need to upload while deep sleep is enabled: press reset to wake the board,
  then start the upload; if necessary, use the board's bootloader procedure.
