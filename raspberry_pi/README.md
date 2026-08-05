# Raspberry Pi software

This directory is the installable Raspberry Pi half of the bird e-ink
dashboard. Run `sudo ./install.sh` on Raspberry Pi OS after cloning the full
repository.

The installer copies the application to `/opt/bird-inky`, creates its virtual
environment, enables the `bird-inky` systemd service, and creates
`/etc/bird-inky.env` on the first run. It deliberately does not start the
service immediately, because the normal configuration powers the Pi off after
updating the display.

See the repository's top-level `README.md` for the complete GitHub, Raspberry
Pi, first-test, update, and troubleshooting instructions.
