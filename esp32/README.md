# ESP32 + Seeed EE02 deployment

This folder is the Arduino IDE implementation for the Seeed Studio XIAO
ESP32-S3 Plus, EE02 controller board, and 13.3-inch Spectra 6/T133A01 panel.
It is intentionally a simple network picture frame:

1. Connect to Wi-Fi.
2. Download `today.jpg` from GitHub Pages.
3. Decode it into the EE02 six-color framebuffer.
4. Refresh the panel.
5. Deep-sleep until the next update.

The dashboard composition, bird selection, facts, resizing, and dithering all
happen in GitHub Actions. The published ESP32 image is exactly `1200x1600`.

## Arduino IDE setup

Install these libraries:

- `Seeed_GFX` 2.0.3 or newer, using Seeed's GitHub/ZIP installation described
  in the EE02 setup guide
- `JPEGDEC` by Larry Bank, using **Tools > Manage Libraries**

Select the board and options:

- Board: **XIAO ESP32S3 Plus**
- PSRAM: **OPI PSRAM**
- USB CDC On Boot: **Enabled** for easier serial diagnostics

No custom partition table or filesystem is required.

## Configure and flash

1. Open `esp32/bird_ee02/bird_ee02.ino` in Arduino IDE.
2. Copy `config.example.h` to `config.h` in the same sketch folder.
3. Set `WIFI_SSID`, `WIFI_PASSWORD`, and `IMAGE_URL` in `config.h`.
4. Leave `ENABLE_DEEP_SLEEP` set to `false` for the first upload.
5. Upload, then open the Serial Monitor at **115200 baud**.
6. After a successful display refresh, set `ENABLE_DEEP_SLEEP` to `true` and
   upload again for daily operation.

For this repository, the Pages image URL is:

```text
https://jffkm.github.io/bird-ee02-dashboard/today.jpg
```

`config.h` is ignored by Git so Wi-Fi credentials are not committed.

## HTTPS note

The sketch uses TLS encryption without certificate validation to keep this
public-image appliance small and avoid maintaining a root certificate in
firmware. Someone able to intercept the network connection could substitute
the displayed image. Do not reuse this pattern for credentials or private data.

## Expected serial output

```text
Bird EE02 Dashboard
[wifi] Connected: ...
[image] Downloaded ... bytes
[panel] Decoding JPEG
[panel] Refreshing display; this can take tens of seconds
[panel] Refresh complete
```

If the download or decode fails, the sketch does not refresh the panel, so the
previous e-paper image remains visible.
