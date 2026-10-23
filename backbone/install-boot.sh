#!/bin/sh
# Install the verified backbone so the Kraken runtime is available on boot.
# A later run is an update: the installed tree is replaced, then the machine reboots
# so the process that comes back is the new copy.
set -eu
SRC=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
PYTHON=$(command -v python3)

if [ -n "${FXJEFE_BOOT_DEST:-}" ]; then
  DEST=$FXJEFE_BOOT_DEST
elif [ "$(id -u)" -eq 0 ]; then
  DEST=/opt/fxjefe-backbone
else
  DEST=$HOME/.local/share/fxjefe-backbone
fi

if [ -n "${FXJEFE_SELF_CHECK_CMD:-}" ]; then
  sh -c "$FXJEFE_SELF_CHECK_CMD"
else
  "$SRC/launch.sh" --self-check
fi

updating=0
if [ -e "$DEST" ]; then
  updating=1
fi

stage=$(mktemp -d "${TMPDIR:-/tmp}/fxjefe-backbone.XXXXXX")
cleanup() {
  if [ -n "${stage:-}" ] && [ -d "$stage" ]; then
    rm -rf "$stage"
  fi
}
trap cleanup EXIT

cp -a "$SRC"/. "$stage"/
rm -rf "$stage/.venv"
rm -f "$stage/kraken.env"
if [ -f "$DEST/kraken.env" ]; then
  cp "$DEST/kraken.env" "$stage/kraken.env"
fi

if [ "${FXJEFE_SKIP_VENV:-}" != 1 ]; then
  "$PYTHON" -m venv "$stage/.venv"
  if [ "${FXJEFE_SKIP_PIP:-}" != 1 ]; then
    "$stage/.venv/bin/pip" install --no-index --find-links "$stage/wheels" pandas
  fi
fi

install_unit() {
  if [ "${FXJEFE_SKIP_SYSTEMD:-}" = 1 ]; then
    return
  fi
  rendered=$(mktemp)
  sed "s#/opt/fxjefe-backbone#$DEST#g" "$SRC/kraken-backbone.service" > "$rendered"
  if [ "$(id -u)" -eq 0 ]; then
    cp "$rendered" /etc/systemd/system/kraken-backbone.service
    rm -f "$rendered"
    systemctl daemon-reload
    systemctl enable kraken-backbone.service
    if [ "$updating" -eq 0 ]; then
      systemctl start kraken-backbone.service
    fi
    return
  fi
  if command -v systemctl >/dev/null 2>&1; then
    unit_dir=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
    mkdir -p "$unit_dir"
    cp "$rendered" "$unit_dir/kraken-backbone.service"
    rm -f "$rendered"
    systemctl --user daemon-reload || true
    systemctl --user enable kraken-backbone.service || true
    if [ "$updating" -eq 0 ]; then
      systemctl --user start kraken-backbone.service || true
    fi
    return
  fi
  rm -f "$rendered"
  line="@reboot $DEST/launch.sh"
  (crontab -l 2>/dev/null | grep -v fxjefe-backbone || true; echo "$line") | crontab -
}

stop_running() {
  if [ "${FXJEFE_SKIP_SYSTEMD:-}" = 1 ]; then
    return
  fi
  if [ "$(id -u)" -eq 0 ]; then
    systemctl stop kraken-backbone.service || true
    return
  fi
  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user stop kraken-backbone.service || true
  fi
}

reboot_after_update() {
  echo "update installed; rebooting so the new backbone is the runtime"
  if [ -n "${FXJEFE_REBOOT_CMD:-}" ]; then
    sh -c "$FXJEFE_REBOOT_CMD"
    return
  fi
  if [ "$(id -u)" -eq 0 ]; then
    systemctl reboot
    return
  fi
  if command -v sudo >/dev/null 2>&1 && sudo -n systemctl reboot; then
    return
  fi
  echo "update is on disk; reboot this machine so the new backbone replaces the running runtime" >&2
  exit 1
}

mkdir -p "$(dirname "$DEST")"
if [ "$updating" -eq 1 ]; then
  stop_running
  previous=$DEST.previous
  rm -rf "$previous"
  mv "$DEST" "$previous"
  if ! mv "$stage" "$DEST"; then
    mv "$previous" "$DEST"
    stage=
    echo "update swap failed; previous backbone restored" >&2
    exit 1
  fi
  stage=
  install_unit
  reboot_after_update
  exit 0
fi

mv "$stage" "$DEST"
stage=
install_unit
echo "installed $DEST"
