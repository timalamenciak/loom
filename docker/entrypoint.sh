#!/bin/sh
set -eu

APP_DIR="${APP_DIR:-/opt/loom}"

fix_owner() {
    path="$1"
    mkdir -p "$path"
    if [ "$(stat -c '%u:%g' "$path")" != "$(id -u loom):$(id -g loom)" ]; then
        chown -R loom:loom "$path"
    fi
}

if [ "$(id -u)" = "0" ]; then
    fix_owner "$APP_DIR/media"
    fix_owner "$APP_DIR/staticfiles"
    fix_owner /home/loom
    exec gosu loom "$@"
fi

exec "$@"
