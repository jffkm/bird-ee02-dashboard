# Bird Inky Dashboard: Raspberry Pi + EE02

This project builds a new bird-of-the-day dashboard on GitHub Actions, publishes
it with GitHub Pages, and displays it on either of these e-paper systems:

- a Pimoroni Inky screen attached to a Raspberry Pi; or
- a Seeed Studio XIAO ESP32-S3 Plus with an EE02 controller and 13.3-inch
  Spectra 6/T133A01 panel.

The renderer and display clients are deliberately separate:

- GitHub renders `today.png`, `today.jpg`, and `today.json` from `birds.json`
  once per day. The JPEG is a six-color, `1200x1600` portrait image for EE02.
- The Raspberry Pi downloads the rendered image, keeps the last good copy for
  offline fallback, updates the Inky display, and optionally shuts down.
- The ESP32 downloads only the JPEG, updates the EE02 panel, and deep-sleeps.

## Project layout

```text
.
├── .github/workflows/build-dashboard.yml  # Daily build and Pages deployment
├── build_dashboard.py                     # Backend image renderer
├── birds.json                             # Bird list
├── requirements.txt                       # Backend dependencies
├── esp32/
│   ├── README.md                         # Arduino setup and flashing
│   └── bird_ee02/
│       ├── bird_ee02.ino                 # Wi-Fi/JPEG/display/sleep sketch
│       ├── config.example.h              # Copy to the ignored config.h
│       └── driver.h                      # EE02 Seeed_GFX selection
└── raspberry_pi/
    ├── display_bird.py                    # Pi download/display program
    ├── bird-inky.service                  # systemd one-shot service
    ├── install.sh                         # Idempotent Pi installer/updater
    ├── requirements.txt                   # Pi hardware dependencies
    └── bird-dashboard.env.example         # Pi configuration template
```

## Test the renderer on a Mac

From the repository directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python build_dashboard.py --date 2026-08-05 --out public --no-birdnet --no-wikipedia
python build_dashboard.py --date 2026-08-05 --width 1200 --height 1600 \
  --out public --no-birdnet --no-wikipedia --image-format jpeg --ee02-palette
open public/index.html
```

The two `--no-*` flags make that first test deterministic and network-free. Omit
them to test live BirdNET and Wikipedia enrichment.

## Enable GitHub Pages

In the GitHub repository, open **Settings > Pages** and set **Source** to
**GitHub Actions**. Then open **Actions**, select **Build Bird Dashboard**, and
run it once with **Run workflow**. The generated files will be available at:

```text
https://YOUR_USERNAME.github.io/bird-ee02-dashboard/today.jpg
https://YOUR_USERNAME.github.io/bird-ee02-dashboard/today.png
https://YOUR_USERNAME.github.io/bird-ee02-dashboard/today.json
```

`today.jpg` is the EE02 image. `today.png` remains available for the existing
Raspberry Pi client.

The scheduled workflow runs at 11:17 UTC each day. GitHub schedules use UTC, so
adjust the cron expression in `.github/workflows/build-dashboard.yml` if a
different local publish time is required.

## Install on the ESP32

See [`esp32/README.md`](esp32/README.md). In short: install `Seeed_GFX` and
`JPEGDEC` in Arduino IDE, open `esp32/bird_ee02/bird_ee02.ino`, copy
`config.example.h` to the ignored `config.h`, enter the Wi-Fi credentials and
Pages JPEG URL, select **XIAO ESP32S3 Plus** with **OPI PSRAM**, and upload.

## Install on the Raspberry Pi

Use Raspberry Pi OS Bookworm or later. Connect the Inky display before the first
hardware test, then run:

```bash
sudo apt update
sudo apt install -y git
cd ~
git clone https://github.com/YOUR_USERNAME/bird-ee02-dashboard.git
cd bird-ee02-dashboard/raspberry_pi
sudo ./install.sh
sudo nano /etc/bird-inky.env
```

Replace `YOUR_USERNAME` in both URLs in `/etc/bird-inky.env`. For the first
test, leave the safe default set to:

```text
BIRD_POWER_OFF=0
```

Reboot once so the I2C/SPI changes made by the installer take effect:

```bash
sudo reboot
```

The service is enabled at boot, so it will run after that reboot. With
`BIRD_POWER_OFF=0`, the Pi stays online for inspection. Check the result with:

```bash
sudo systemctl status bird-inky --no-pager
sudo journalctl -u bird-inky -n 100 --no-pager
```

After the display works, change `BIRD_POWER_OFF=1` in `/etc/bird-inky.env` for
the low-power appliance workflow. Starting the service or booting the Pi will
then update the display and shut the Pi down when it is running on battery.
With the default `BIRD_STAY_AWAKE_ON_USB=1`, the Pi remains online whenever the
PiSugar reports power at its USB-C input. If the PiSugar service cannot be
queried, the script also remains online as a safety precaution.

The external-power check uses PiSugar Power Manager's local Unix socket and its
`battery_power_plugged` status. Connect troubleshooting power to the PiSugar
USB-C input; power applied directly to the Raspberry Pi may not be visible to
the PiSugar input sensor.

### Emergency stay-awake override

If automatic shutdown is enabled and you need to recover the Pi, turn it off,
put the microSD card in another computer, and create an empty file named
`bird-inky-stay-awake` in the root of the visible boot partition. On Raspberry
Pi OS Bookworm this appears at `/boot/firmware/bird-inky-stay-awake` while the
Pi is running. The systemd service will be skipped at boot, leaving the Pi
available for SSH. Remove the file only after setting `BIRD_POWER_OFF=0`.

## Updating the Pi

The installer is safe to rerun. Pull changes and reinstall the managed files:

```bash
cd ~/bird-ee02-dashboard
git pull --ff-only
cd raspberry_pi
sudo ./install.sh
sudo reboot
```

The installer preserves an existing `/etc/bird-inky.env`, so updates do not
overwrite the configured URLs.

## Runtime behavior

- Application: `/opt/bird-inky`
- Python virtual environment: `/opt/bird-inky/venv`
- Persistent last-good image: `/var/lib/bird-inky/today.png`
- Configuration: `/etc/bird-inky.env`
- Service: `/etc/systemd/system/bird-inky.service`

If Wi-Fi or GitHub Pages is temporarily unavailable, the Pi retries the request
and then redisplays the last successfully downloaded image. The display retains
its image after the Pi loses power.

For months-long battery operation, use an RTC-controlled power board to wake the
Pi once daily and cut power after Linux shuts down. A Raspberry Pi does not have
a built-in deep-sleep mode suitable for this use by itself.

## Troubleshooting

If Inky reports that a chip-select pin is already in use, confirm this line is
present in `/boot/firmware/config.txt` and reboot:

```text
dtoverlay=spi0-0cs
```

The installer follows Pimoroni's current Inky setup guidance by enabling I2C and
SPI, using a virtual environment with system packages, and applying that overlay.
See the [official Pimoroni Inky project](https://github.com/pimoroni/inky) for
display-specific hardware troubleshooting.
