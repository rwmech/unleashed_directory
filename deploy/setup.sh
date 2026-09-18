#!/usr/bin/env bash
# ===========================================================================
#  µnleashed BBS directory: first-time setup
# ===========================================================================
#
# File:        deploy/setup.sh
# Purpose:     Turns a fresh Debian or Ubuntu box into a directory server.
#              Safe to run again: every step checks before it acts.
#
# Usage:       sudo ./deploy/setup.sh <list> [about] [data]
#              sudo ./deploy/setup.sh                  (no TLS, port 80 only)
#
#              One server, up to three faces, chosen by the Host header:
#
#                list    the boards that are up              example.com
#                about   what this is, and where it came from example.org
#                data    the API, and what is in it           example.net
#
#              Give one domain and it serves all of it. Give three and each
#              gets its own face. Caddy obtains the certificates itself and
#              renews them in the background: there is no certbot here, no
#              cron job to add, and adding one would fight it.
#
# What it does:
#   - installs everything it needs: python3, sqlite3, curl, gnupg, git, ufw
#     and Caddy. A minimal cloud image has fewer of these than you expect
#   - makes a "directory" system user that owns nothing but its database
#   - copies the code to /srv/unleashed_directory
#   - writes /etc/caddy/Caddyfile for the domains you gave it
#   - installs and starts the service
#   - opens 22, 80 and 443, and nothing else
#
# Tested on a $4 DigitalOcean droplet (512 MB, 1 vCPU), which is more than
# this needs: a board sends 200 bytes every ten minutes, so ten thousand
# boards would be seventeen requests a second.
#
# Copyright 2026 - Robert Mech
# License:     GNU General Public License v2 or later
# SPDX-License-Identifier: GPL-2.0-or-later
# ===========================================================================
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST=/srv/unleashed_directory
DATA=/var/lib/unleashed-directory
DOMAINS=("$@")

say() { printf '\n== %s\n' "$1"; }

[ "$(id -u)" -eq 0 ] || { echo "run this with sudo"; exit 1; }

command -v apt-get >/dev/null || {
    echo "This script installs packages with apt, so it wants Debian or Ubuntu."
    echo "On anything else, install python3 and a web server yourself and run"
    echo "server.py behind it. There is nothing else to it."
    exit 1
}

# Everything used later, including the tools the install itself leans on. A
# minimal cloud image has less than you would expect: gnupg in particular is
# often missing, and the Caddy step pipes a key straight into gpg.
say "Packages"
apt-get update -y
apt-get install -y \
    python3 \
    sqlite3 \
    curl \
    gnupg \
    ca-certificates \
    git \
    ufw \
    debian-keyring \
    debian-archive-keyring \
    apt-transport-https

# Say what is missing rather than failing three steps later inside a pipe.
missing=""
for tool in python3 sqlite3 curl gpg git ufw; do
    command -v "$tool" >/dev/null || missing="$missing $tool"
done
[ -z "$missing" ] || { echo "could not install:$missing"; exit 1; }

if ! command -v caddy >/dev/null; then
    say "Caddy"
    KEYRING=/usr/share/keyrings/caddy-stable-archive-keyring.gpg
    if [ ! -s "$KEYRING" ]; then
        curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
            | gpg --dearmor -o "$KEYRING"
    fi
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -y
    apt-get install -y caddy
    command -v caddy >/dev/null || {
        echo "Caddy did not install. The directory itself is fine without it:"
        echo "run server.py and put any web server in front, but remember that"
        echo "/announce has to stay on plain HTTP with no redirect."
        exit 1
    }
else
    echo "caddy already installed"
fi

# Remember what this install was given, so deploy/update.sh can repeat it
# without being told again and without getting it wrong.
install -d -m 755 /etc/unleashed-directory
printf '%s
' "${DOMAINS[*]:-}" > /etc/unleashed-directory/domains

say "User and directories"
id -u directory >/dev/null 2>&1 || useradd --system --home "$DATA" --shell /usr/sbin/nologin directory
install -d -o directory -g directory -m 750 "$DATA"
install -d -m 755 "$DEST"

# Caddy runs as its own user and writes an access log. A root-owned log
# directory means it cannot open the file, and Caddy treats that as a bad
# config and refuses to start at all: the symptom is nothing listening on
# 80 or 443, and the cause is one line about "setting up custom log".
if id -u caddy >/dev/null 2>&1; then
    install -d -o caddy -g caddy -m 755 /var/log/caddy
else
    install -d -m 755 /var/log/caddy
fi

say "Code"
install -m 644 "$SRC/server.py"   "$DEST/server.py"
install -m 644 "$SRC/selftest.py" "$DEST/selftest.py"

say "Service"
install -m 644 "$SRC/deploy/unleashed-directory.service" \
    /etc/systemd/system/unleashed-directory.service

# Which domain plays which part, in a drop-in, so the unit that ships in the
# repository never needs editing for a deployment.
mkdir -p /etc/systemd/system/unleashed-directory.service.d
{
    echo "# Written by deploy/setup.sh"
    echo "[Service]"
    [ -n "${DOMAINS[0]:-}" ] && echo "Environment=DIRECTORY_LIST_DOMAIN=${DOMAINS[0]}"
    [ -n "${DOMAINS[1]:-}" ] && echo "Environment=DIRECTORY_ABOUT_DOMAIN=${DOMAINS[1]}"
    [ -n "${DOMAINS[2]:-}" ] && echo "Environment=DIRECTORY_DATA_DOMAIN=${DOMAINS[2]}"
    true
} > /etc/systemd/system/unleashed-directory.service.d/domains.conf

systemctl daemon-reload
systemctl enable unleashed-directory >/dev/null
systemctl restart unleashed-directory

# ---------------------------------------------------------------------------
# The web front end, written for the domains given on the command line.
#
# THE ONE THING NOT TO CHANGE: /announce stays on plain HTTP with no
# redirect. A board is a microcontroller with no TLS stack, and Caddy's
# default of upgrading every http:// request would turn every heartbeat on
# the network into a 308 that boards report as "refused", silently, with no
# way for a sysop to find out why.
# ---------------------------------------------------------------------------
say "Web front end"
CADDY=/etc/caddy/Caddyfile

if [ ${#DOMAINS[@]} -eq 0 ]; then
    echo "no domains given: serving plain HTTP on port 80"
    cat > "$CADDY" <<EOF
# Written by deploy/setup.sh. No domains were given, so there is no TLS.
:80 {
	encode gzip
	reverse_proxy 127.0.0.1:8080
}
EOF
else
    MAIN="${DOMAINS[0]}"
    ALL=""
    HTTP_ALL=""
    for d in "${DOMAINS[@]}"; do
        ALL="${ALL:+$ALL, }$d, www.$d"
        HTTP_ALL="${HTTP_ALL:+$HTTP_ALL, }http://$d, http://www.$d"
    done

    echo "board list: $MAIN"
    [ -n "${DOMAINS[1]:-}" ] && echo "about:      ${DOMAINS[1]}"
    [ -n "${DOMAINS[2]:-}" ] && echo "data:       ${DOMAINS[2]}"
    true

    {
        echo "# Written by deploy/setup.sh. Edit deploy/setup.sh, not this file."
        echo
        echo "# Boards cannot do TLS, so /announce must stay on plain HTTP with"
        echo "# no redirect. Everything else on port 80 goes up to HTTPS."
        echo "$HTTP_ALL {"
        echo "	@announce path /announce"
        echo "	handle @announce {"
        echo "		reverse_proxy 127.0.0.1:8080"
        echo "	}"
        echo "	handle {"
        echo "		redir https://$MAIN{uri} permanent"
        echo "	}"
        echo "}"
        # Every domain is served rather than redirected: the server works out
        # which face to show from the Host header it is handed.
        echo
        echo "$ALL {"
        echo "	encode gzip"
        echo "	reverse_proxy 127.0.0.1:8080"
        echo "	log {"
        echo "		output file /var/log/caddy/directory.log"
        echo "		format console"
        echo "	}"
        echo "}"
    } > "$CADDY"
fi

# A broken Caddyfile that gets installed anyway takes the site down with it.
# Note that validate only reads the file: it cannot tell whether Caddy will
# be allowed to open the log it names, which is checked below instead.
caddy validate --config "$CADDY"
systemctl reload caddy || systemctl restart caddy
sleep 1
if ! systemctl is-active --quiet caddy; then
    echo
    echo "Caddy did not start. The last few lines say why:"
    journalctl -u caddy -n 12 --no-pager || true
    exit 1
fi

say "Firewall"
ufw allow 22/tcp  >/dev/null
ufw allow 80/tcp  >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
ufw status | head -8

say "State"
systemctl --no-pager --lines=3 status unleashed-directory || true
echo
curl -fsS http://127.0.0.1:8080/health >/dev/null && echo "directory answering on 8080"
systemctl is-active --quiet caddy && echo "caddy running on 80 and 443"

if [ ${#DOMAINS[@]} -gt 0 ]; then
    echo
    echo "Point a board at:  http://${DOMAINS[0]}/announce"
    echo "Then wait three hours of heartbeats for it to appear."
    echo
    echo "Certificates are Caddy's own job and it renews them in the"
    echo "background. There is no cron to add for those."
    echo
    echo "To keep the software itself current:"
    echo "  ./deploy/update.sh                  pull, install, check, report"
    echo "  ./deploy/update.sh --install-timer   do that daily, quietly"
fi
