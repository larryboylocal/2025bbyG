#!/bin/sh
# Install the verified backbone so the Kraken runtime is available on boot.
set -eu
SRC=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
DEST=/opt/fxjefe-backbone
PYTHON=$(command -v python3)

if [ "$(id -u)" -eq 0 ]; then
  mkdir -p "$DEST"
  cp -a "$SRC"/. "$DEST"/
  "$PYTHON" -m venv "$DEST/.venv"
  "$DEST/.venv/bin/pip" install --no-index --find-links "$DEST/wheels" pandas
  cp "$SRC/kraken-backbone.service" /etc/systemd/system/kraken-backbone.service
  systemctl daemon-reload
  systemctl enable --now kraken-backbone.service
  echo "installed systemd unit kraken-backbone.service"
  exit 0
fi

mkdir -p "$HOME/.local/share/fxjefe-backbone"
cp -a "$SRC"/. "$HOME/.local/share/fxjefe-backbone"/
"$PYTHON" -m venv "$HOME/.local/share/fxjefe-backbone/.venv"
"$HOME/.local/share/fxjefe-backbone/.venv/bin/pip" install --no-index --find-links "$HOME/.local/share/fxjefe-backbone/wheels" pandas
UNIT_DIR="$HOME/.config/systemd/user"
if command -v systemctl >/dev/null 2>&1; then
  mkdir -p "$UNIT_DIR"
  sed "s#/opt/fxjefe-backbone#$HOME/.local/share/fxjefe-backbone#g" "$SRC/kraken-backbone.service" > "$UNIT_DIR/kraken-backbone.service"
  systemctl --user daemon-reload || true
  systemctl --user enable --now kraken-backbone.service || true
  echo "installed user systemd unit"
  exit 0
fi
LINE="@reboot $HOME/.local/share/fxjefe-backbone/launch.sh"
(crontab -l 2>/dev/null | grep -v fxjefe-backbone || true; echo "$LINE") | crontab -
echo "installed crontab @reboot"
