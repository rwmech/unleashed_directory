#!/usr/bin/env bash
# ===========================================================================
#  µnleashed BBS directory: first-time setup
# ===========================================================================
#
# File:        deploy/setup.sh
# Purpose:     Turns a fresh Debian or Ubuntu box into the directory server.
#              Safe to run again: every step checks before it acts.
#
# Usage:       sudo ./deploy/setup.sh
#
# What it does:
#   - installs Caddy and python3
#   - makes a "directory" system user that owns nothing but its database
#   - copies the code to /srv/unleashed_directory
#   - installs the service unit and the Caddy configuration
#   - opens 22, 80 and 443, and nothing else
#
# Copyright 2026 - Robert Mech
# License:     GNU General Public License v2 or later
# SPDX-License-Identifier: GPL-2.0-or-later
# ===========================================================================
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST=/srv/unleashed_directory
DATA=/var/lib/unleashed-directory

say() { printf '\n== %s\n' "$1"; }

[ "$(id -u)" -eq 0 ] || { echo "run this with sudo"; exit 1; }

say "Packages"
apt-get update -y
apt-get install -y python3 curl debian-keyring debian-archive-keyring apt-transport-https ufw

if ! command -v caddy >/dev/null; then
    say "Caddy"
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        | tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
    apt-get update -y
    apt-get install -y caddy
else
    echo "caddy already installed"
fi

say "User and directories"
id -u directory >/dev/null 2>&1 || useradd --system --home "$DATA" --shell /usr/sbin/nologin directory
install -d -o directory -g directory -m 750 "$DATA"
install -d -m 755 "$DEST"
install -d -m 755 /var/log/caddy

say "Code"
install -m 644 "$SRC/server.py"   "$DEST/server.py"
install -m 644 "$SRC/selftest.py" "$DEST/selftest.py"

say "Service"
install -m 644 "$SRC/deploy/unleashed-directory.service" \
    /etc/systemd/system/unleashed-directory.service
systemctl daemon-reload
systemctl enable unleashed-directory
systemctl restart unleashed-directory

say "Web front end"
install -m 644 "$SRC/deploy/Caddyfile" /etc/caddy/Caddyfile
# A broken Caddyfile that gets installed anyway takes the site down, so it is
# checked before anything is reloaded.
caddy validate --config /etc/caddy/Caddyfile
systemctl reload caddy || systemctl restart caddy

say "Firewall"
ufw allow 22/tcp  >/dev/null
ufw allow 80/tcp  >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
ufw status verbose | head -12

say "State"
systemctl --no-pager --lines=3 status unleashed-directory || true
echo
echo "Local check:"
curl -fsS http://127.0.0.1:8080/health && echo "  directory answering on 8080"
echo
echo "Done. Point a board at http://unleashedbbs.com/announce and wait three hours."
