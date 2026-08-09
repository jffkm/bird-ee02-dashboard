#!/usr/bin/env python3
"""
Fetch today's bird dashboard PNG and display it on a Pimoroni Inky screen.

This script is designed to run once at boot. In low-power deployments, an
external RTC/power board wakes the Pi once per day; this script updates the
display and powers the Pi back down.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageOps
from inky.auto import auto


RESAMPLE_LANCZOS = getattr(Image, "Resampling", Image).LANCZOS
IMAGE_URL = os.environ.get("BIRD_IMAGE_URL", "").strip()
META_URL = os.environ.get("BIRD_META_URL", "").strip()
CACHE_DIR = Path(os.environ.get("BIRD_CACHE_DIR", "/var/lib/bird-inky"))
POWER_OFF = os.environ.get("BIRD_POWER_OFF", "1").strip() != "0"
STAY_AWAKE_ON_USB = os.environ.get("BIRD_STAY_AWAKE_ON_USB", "1").strip() != "0"
PISUGAR_SOCKET = Path(os.environ.get("BIRD_PISUGAR_SOCKET", "/tmp/pisugar-server.sock"))
PISUGAR_QUERY_ATTEMPTS = max(1, int(os.environ.get("BIRD_PISUGAR_QUERY_ATTEMPTS", "5")))
DOWNLOAD_TIMEOUT = int(os.environ.get("BIRD_DOWNLOAD_TIMEOUT", "30"))
DOWNLOAD_ATTEMPTS = max(1, int(os.environ.get("BIRD_DOWNLOAD_ATTEMPTS", "4")))
RETRY_DELAY = max(0, int(os.environ.get("BIRD_RETRY_DELAY", "10")))
USER_AGENT = "bird-inky-display/1.0"


def log(message: str) -> None:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"{stamp} {message}", flush=True)


def fetch(url: str, path: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )
    with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
        with path.open("wb") as out:
            out.write(response.read())


def download_today() -> Path:
    if not IMAGE_URL:
        raise RuntimeError("BIRD_IMAGE_URL is not set.")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / "today.png"

    last_error: Exception | None = None

    for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
        with tempfile.NamedTemporaryFile(prefix="today-", suffix=".png", dir=CACHE_DIR, delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            log(f"Downloading {IMAGE_URL} (attempt {attempt}/{DOWNLOAD_ATTEMPTS})")
            fetch(IMAGE_URL, tmp_path)

            with Image.open(tmp_path) as img:
                img.verify()

            tmp_path.replace(cached)
            log(f"Cached image at {cached}")
            return cached
        except Exception as exc:  # noqa: BLE001 - retry, then use the last-good image.
            last_error = exc
            tmp_path.unlink(missing_ok=True)
            log(f"Download attempt {attempt} failed: {exc}")
            if attempt < DOWNLOAD_ATTEMPTS:
                time.sleep(RETRY_DELAY)

    if cached.exists():
        log(f"All downloads failed; using cached image at {cached}")
        return cached

    raise RuntimeError("All image download attempts failed and no cached image exists.") from last_error


def maybe_download_metadata() -> None:
    if not META_URL:
        return

    try:
        meta_path = CACHE_DIR / "today.json"
        fetch(META_URL, meta_path)
        with meta_path.open("r", encoding="utf-8") as f:
            meta = json.load(f)
        bird = meta.get("bird", {})
        name = bird.get("common_name") or bird.get("scientific_name") or "unknown bird"
        log(f"Metadata fetched for {name}")
    except Exception as exc:  # noqa: BLE001 - metadata is nice-to-have.
        log(f"Metadata fetch skipped: {exc}")


def display_image(path: Path) -> None:
    log("Initialising Inky")
    inky = auto(ask_user=False, verbose=True)
    target = tuple(inky.resolution)
    log(f"Inky resolution detected as {target[0]}x{target[1]}")

    with Image.open(path) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        if img.size != target:
            log(f"Resizing image from {img.size[0]}x{img.size[1]} to {target[0]}x{target[1]}")
            img = img.resize(target, RESAMPLE_LANCZOS)
        inky.set_image(img)
        inky.show()

    log("Display updated")


def pisugar_external_power() -> bool | None:
    """Return whether PiSugar USB input is powered, or None if unavailable."""
    for attempt in range(1, PISUGAR_QUERY_ATTEMPTS + 1):
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(2)
                client.connect(str(PISUGAR_SOCKET))
                client.sendall(b"get battery_power_plugged\n")
                response = client.recv(4096).decode("utf-8", errors="replace").strip()

            value = response.rsplit(":", 1)[-1].strip().casefold()
            if value == "true":
                log("PiSugar reports external USB power")
                return True
            if value == "false":
                log("PiSugar reports battery-only power")
                return False
            raise ValueError(f"unexpected response: {response!r}")
        except (OSError, ValueError) as exc:
            log(
                "PiSugar power-source query "
                f"{attempt}/{PISUGAR_QUERY_ATTEMPTS} failed: {exc}"
            )
            if attempt < PISUGAR_QUERY_ATTEMPTS:
                time.sleep(1)

    return None


def poweroff() -> None:
    if not POWER_OFF:
        log("BIRD_POWER_OFF=0; leaving Pi running for testing")
        return

    if STAY_AWAKE_ON_USB:
        external_power = pisugar_external_power()
        if external_power is True:
            log("External USB power is connected; leaving Pi running for troubleshooting")
            return
        if external_power is None:
            log("Could not confirm the power source; leaving Pi running as a safety precaution")
            return

    log("Powering off")
    subprocess.run(["/usr/bin/systemctl", "poweroff"], check=False)


def main() -> int:
    try:
        image_path = download_today()
        maybe_download_metadata()
        display_image(image_path)
        return 0
    except (urllib.error.URLError, TimeoutError) as exc:
        log(f"Network error: {exc}")
        return 2
    except Exception as exc:  # noqa: BLE001 - log before shutdown.
        log(f"Update failed: {exc}")
        return 1
    finally:
        time.sleep(2)
        poweroff()


if __name__ == "__main__":
    sys.exit(main())
