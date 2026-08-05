#!/usr/bin/env bash
set -Eeuo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly APP_DIR="/opt/bird-inky"
readonly VENV_DIR="${APP_DIR}/venv"
readonly STATE_DIR="/var/lib/bird-inky"
readonly ENV_FILE="/etc/bird-inky.env"
readonly SERVICE_FILE="/etc/systemd/system/bird-inky.service"

log() {
    printf '[bird-inky] %s\n' "$*"
}

fail() {
    printf '[bird-inky] ERROR: %s\n' "$*" >&2
    exit 1
}

if [[ ${EUID} -ne 0 ]]; then
    fail "Run this installer with sudo: sudo ./install.sh"
fi

for source_file in \
    display_bird.py \
    bird-inky.service \
    requirements.txt \
    bird-dashboard.env.example; do
    [[ -f "${SCRIPT_DIR}/${source_file}" ]] || fail "Missing ${SCRIPT_DIR}/${source_file}"
done

command -v apt-get >/dev/null 2>&1 || fail "This installer requires Raspberry Pi OS or another apt-based OS."
command -v systemctl >/dev/null 2>&1 || fail "systemd is required."

log "Installing operating-system packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y git python3 python3-pip python3-venv

if command -v raspi-config >/dev/null 2>&1; then
    log "Enabling I2C and SPI"
    raspi-config nonint do_i2c 0
    raspi-config nonint do_spi 0
else
    log "WARNING: raspi-config was not found; enable I2C and SPI manually."
fi

boot_config=""
if [[ -f /boot/firmware/config.txt ]]; then
    boot_config="/boot/firmware/config.txt"
elif [[ -f /boot/config.txt ]]; then
    boot_config="/boot/config.txt"
fi

if [[ -n ${boot_config} ]] && ! grep -Fqx 'dtoverlay=spi0-0cs' "${boot_config}"; then
    backup_path="${boot_config}.pre-bird-inky"
    if [[ ! -f ${backup_path} ]]; then
        cp --preserve=mode,ownership,timestamps "${boot_config}" "${backup_path}"
        log "Backed up boot configuration to ${backup_path}"
    fi
    printf '\n# Required by Pimoroni Inky (gpiod-managed chip select)\ndtoverlay=spi0-0cs\n' >>"${boot_config}"
    log "Added dtoverlay=spi0-0cs to ${boot_config}"
elif [[ -z ${boot_config} ]]; then
    log "WARNING: config.txt was not found; add dtoverlay=spi0-0cs manually if Inky reports a pin conflict."
fi

log "Installing the application"
install -d -m 0755 "${APP_DIR}" "${STATE_DIR}"
install -m 0755 "${SCRIPT_DIR}/display_bird.py" "${APP_DIR}/display_bird.py"
install -m 0644 "${SCRIPT_DIR}/requirements.txt" "${APP_DIR}/requirements.txt"

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
    log "Creating Python virtual environment"
    python3 -m venv --system-site-packages "${VENV_DIR}"
fi

log "Installing Python dependencies"
"${VENV_DIR}/bin/python" -m pip install --upgrade pip
"${VENV_DIR}/bin/python" -m pip install -r "${APP_DIR}/requirements.txt"

install -m 0644 "${SCRIPT_DIR}/bird-inky.service" "${SERVICE_FILE}"

if [[ ! -f "${ENV_FILE}" ]]; then
    install -m 0644 "${SCRIPT_DIR}/bird-dashboard.env.example" "${ENV_FILE}"
    log "Created ${ENV_FILE}; edit its GitHub Pages URLs before testing."
else
    log "Preserving existing ${ENV_FILE}"
fi

systemctl daemon-reload
systemctl enable bird-inky.service

log "Installation complete."
log "Edit ${ENV_FILE}, keep BIRD_POWER_OFF=0 for the first test, and reboot."
log "After reboot, inspect logs with: sudo journalctl -u bird-inky -n 100 --no-pager"

