#!/usr/bin/env bash
# ===========================================================================
#  µnleashed BBS directory: first-time setup
# ===========================================================================
#
# File:        deploy/setup.sh
# Purpose:     Turns a fresh Debian or Ubuntu box into a directory server.
#              Safe to run again: every step checks before it acts.
#
# Usage:       sudo ./deploy/setup.sh <domain> [alias ...]
#              sudo ./deploy/setup.sh                  (no TLS, port 80 only)
#
#              One site: the board list at /, the badges, how to get
#              listed, the house rules, the data, and the guides at /docs
#              when a checkout of unleashed_documentation is named in
#              /etc/unleashed-directory/docs (or given as DOCS_SRC). Any
#              further domains are served the same site. Caddy obtains the
#              certificates itself and renews them in the background: there
#              is no certbot here, no cron job to add, and adding one would
#              fight it.
#
#              Until 2026-09-26 this took three domains, a board list, a
#              manifesto and a data page. The manifesto and the rest of the
#              project's own site moved to their own server; see
#              UPGRADING in README.md for a box set up the old way.
#
# What it does:
#   - installs everything it needs: python3, sqlite3, curl, gnupg, git, ufw
#     and Caddy. A minimal cloud image has fewer of these than you expect
#   - makes a "directory" system user that owns nothing but its database
#   - copies the code to /srv/unleashed_directory
#   - writes /etc/caddy/sites/directory.caddy for the domains you gave it,
#     and a /etc/caddy/Caddyfile that imports every file in that folder, so
#     another service on the same box can add its own sites beside these
#   - installs and starts the service
#   - opens 22, 80 and 443, and nothing else
#
# Tested on a $4 DigitalOcean droplet (512 MB, 1 vCPU), which is more than
# this needs: a board sends 200 bytes every ten minutes, so ten thousand
# boards would be seventeen requests a second.
#
# Copyright 2026 - Robert Mech
# License:     GNU General Public License v3 or later
# SPDX-License-Identifier: GPL-3.0-or-later
# ===========================================================================
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST=/srv/unleashed_directory
DATA=/var/lib/unleashed-directory
DOMAINS=("$@")

say() { printf '\n== %s\n' "$1"; }

[ "$(id -u)" -eq 0 ] || { echo "run this with sudo"; exit 1; }

# The directory must not answer as the site it sends its old paths to: a
# path it does not have is a 301 to DIRECTORY_HOME_URL, and on the same name
# that is a loop. This is also what stops a domains file from before 2.0.0,
# which held the site's names too, from being installed as it stands.
HOME_HOST="$(sed -n 's|^Environment=DIRECTORY_HOME_URL=https\{0,1\}://\([^/]*\).*|\1|p' \
             "$SRC/deploy/unleashed-directory.service" | head -1)"
for d in "${DOMAINS[@]}"; do
    if [ -n "$HOME_HOST" ] && { [ "$d" = "$HOME_HOST" ] || [ "www.$d" = "$HOME_HOST" ]; }; then
        echo "$d is the project's own site (DIRECTORY_HOME_URL), not the directory."
        echo "Give setup.sh the directory's domain alone, and put only that in"
        echo "/etc/unleashed-directory/domains (see UPGRADING in README.md)."
        exit 1
    fi
done

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
# The page engine, shared with the project's own site, which carries a
# byte-for-byte copy of this file.
install -m 644 "$SRC/sitekit.py"  "$DEST/sitekit.py"
install -m 644 "$SRC/selftest.py" "$DEST/selftest.py"
# The site's version is read from the changelog's newest heading at start,
# for the footer. Without the file the server still starts; it just cannot
# say which version it is.
install -m 644 "$SRC/CHANGELOG.md" "$DEST/CHANGELOG.md"
# The causes and interests, with their codes and aliases (site 1.1.0). The
# server starts without it, but shows no causes or interests until it is
# there, so it is installed with the code, every time.
install -m 644 "$SRC/badges.json" "$DEST/badges.json"

# Pages are prose in Markdown and are replaced on every install, because the
# repository is where they get edited.
install -d -m 755 "$DEST/pages"
# A page removed from the repository goes from the install too: before the
# split (2.0.0) the guides were pages here, and one left behind would be
# served in place of the 301 to /docs. Only when the checkout is not the
# install itself, where git has already removed it.
if [ "$(cd "$SRC" && pwd -P)" != "$(cd "$DEST" && pwd -P)" ]; then
    rm -f "$DEST"/pages/*.md
fi
for page in "$SRC"/pages/*.md; do
    [ -f "$page" ] && install -m 644 "$page" "$DEST/pages/"
done

# Everything else the server reads from beside itself: brand/, the avatar
# and the link preview card. Replaced on every install, because the
# repository is where they are edited. A server started without a folder it
# read at import died once (the 2026-09-23 outage), so anything the server
# reads beside itself is installed here, and the suite checks that it is.
# Copied to a .new and moved into place so a checkout that IS the
# destination still ends up with its files.
for dir in brand; do
    if [ -d "$SRC/$dir" ]; then
        rm -rf "$DEST/$dir.new"
        cp -r "$SRC/$dir" "$DEST/$dir.new"
        chmod -R a+rX "$DEST/$dir.new"
        rm -rf "$DEST/$dir"
        mv "$DEST/$dir.new" "$DEST/$dir"
    fi
done

# The guides (unleashed_documentation, CC BY-SA 4.0), served at /docs: their
# pages/ and shots/, from the checkout named in DOCS_SRC, or in
# /etc/unleashed-directory/docs (which deploy/update.sh also pulls). Without
# one there is no /docs and no Guides entry in the menu, and nothing else
# changes. Replaced whole, so a guide removed upstream is removed here.
DOCS_SRC="${DOCS_SRC:-$(cat /etc/unleashed-directory/docs 2>/dev/null || true)}"
if [ -n "$DOCS_SRC" ] && [ -d "$DOCS_SRC/pages" ]; then
    rm -rf "$DEST/docs.new"
    install -d -m 755 "$DEST/docs.new/pages" "$DEST/docs.new/shots"
    for page in "$DOCS_SRC"/pages/*.md; do
        [ -f "$page" ] && install -m 644 "$page" "$DEST/docs.new/pages/"
    done
    for shot in "$DOCS_SRC"/shots/*.json; do
        [ -f "$shot" ] && install -m 644 "$shot" "$DEST/docs.new/shots/"
    done
    # The stock skins' pictures and zips, served at /skins/<file>.
    if [ -d "$DOCS_SRC/skins" ]; then
        install -d -m 755 "$DEST/docs.new/skins"
        for f in "$DOCS_SRC"/skins/*.png "$DOCS_SRC"/skins/*.zip; do
            [ -f "$f" ] && install -m 644 "$f" "$DEST/docs.new/skins/"
        done
    fi
    rm -rf "$DEST/docs"
    mv "$DEST/docs.new" "$DEST/docs"
    echo "guides from $DOCS_SRC"
else
    echo "no guides: /docs is not served (see DOCS_SRC in this script)"
fi

say "Service"
install -m 644 "$SRC/deploy/unleashed-directory.service" \
    /etc/systemd/system/unleashed-directory.service

# The domain it answers as, in a drop-in, so the unit that ships in the
# repository never needs editing for a deployment.
mkdir -p /etc/systemd/system/unleashed-directory.service.d
{
    echo "# Written by deploy/setup.sh"
    echo "[Service]"
    [ -n "${DOMAINS[0]:-}" ] && echo "Environment=DIRECTORY_LIST_DOMAIN=${DOMAINS[0]}"
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
SITES=/etc/caddy/sites
MINE="$SITES/directory.caddy"
install -d -m 755 "$SITES"

# A domain another service on this box already serves cannot be ours as
# well: Caddy refuses two sites with one name, and the refusal would take
# every site on the box down with it. This is also what stops a domains file
# written by the old three-face installer (list, about and data) from
# claiming the project's own site on a shared box.
for d in "${DOMAINS[@]}"; do
    for other in "$SITES"/*.caddy; do
        [ -f "$other" ] && [ "$other" != "$MINE" ] || continue
        if grep -Eq "(^|[ ,/])(www\.)?${d//./\\.}([ ,{]|$)" "$other"; then
            echo "$d is already served by $other."
            echo "Give this directory its own domain: sudo ./deploy/setup.sh <domain>"
            echo "(and put that domain in /etc/unleashed-directory/domains)."
            exit 1
        fi
    done
done

if [ ${#DOMAINS[@]} -eq 0 ]; then
    echo "no domains given: serving plain HTTP on port 80"
    {
        echo "# Written by deploy/setup.sh (unleashed_directory). No domains were"
        echo "# given, so there is no TLS."
        echo ":80 {"
        echo "	encode gzip"
        echo "	reverse_proxy 127.0.0.1:8080"
        echo "}"
    } > "$MINE.new"
else
    ALL=""
    HTTP_ALL=""
    for d in "${DOMAINS[@]}"; do
        ALL="${ALL:+$ALL, }$d, www.$d"
        HTTP_ALL="${HTTP_ALL:+$HTTP_ALL, }http://$d, http://www.$d"
    done
    echo "directory: ${DOMAINS[*]}"
    {
        echo "# Written by deploy/setup.sh (unleashed_directory). Edit that, not this."
        echo
        echo "# Boards cannot do TLS, so /announce must stay on plain HTTP with"
        echo "# no redirect. Everything else on port 80 goes up to HTTPS, on the"
        echo "# name it was asked for."
        echo "$HTTP_ALL {"
        echo "	@announce path /announce"
        echo "	handle @announce {"
        echo "		reverse_proxy 127.0.0.1:8080 {"
        echo "			header_up X-Real-IP {remote_host}"
        echo "		}"
        echo "	}"
        echo "	handle {"
        echo "		redir https://{host}{uri} permanent"
        echo "	}"
        echo "}"
        echo
        # Caddy appends X-Forwarded-For by itself; X-Real-IP it does not,
        # and the directory reads both. Neither is believed unless the
        # connection came from a trusted proxy, which is loopback.
        echo "$ALL {"
        echo "	encode gzip"
        echo "	reverse_proxy 127.0.0.1:8080 {"
        echo "		header_up X-Real-IP {remote_host}"
        echo "	}"
        echo "	log {"
        echo "		output file /var/log/caddy/directory.log"
        echo "		format console"
        echo "	}"
        echo "}"
    } > "$MINE.new"
fi
mv "$MINE.new" "$MINE"

# The main Caddyfile only gathers the sites. Each service on the box writes
# its own file in /etc/caddy/sites, so updating one never rewrites the
# other's. A Caddyfile this script wrote before the split held every domain
# itself; it is replaced here, at the same moment the sites folder takes
# over, so there is no moment with a domain served twice or not at all.
#
# Before replacing a Caddyfile that still holds sites of its own (one from
# before the split), every name it serves must be served by a file in the
# sites folder once the new one is in, or that name would go dark. On the
# project's droplet that means the main site's setup has written site.caddy
# first; for anybody else it means a domain they forgot to hand over.
if [ -f "$CADDY" ] && ! grep -q "^import /etc/caddy/sites/" "$CADDY"; then
    dark=""
    for name in $(grep -E '^[a-z:/]' "$CADDY" | grep -oE '[a-z0-9-]+(\.[a-z0-9-]+)+' \
                  | sed -e 's/^www\.//' | sort -u); do
        grep -Eq "(^|[ ,/])(www\.)?${name//./\\.}([ ,{]|$)" "$SITES"/*.caddy 2>/dev/null \
            || dark="$dark $name"
    done
    if [ -n "$dark" ]; then
        echo "The Caddyfile serves$dark, and nothing in $SITES would after this."
        echo "Install whatever serves those first (on the project's droplet, the"
        echo "main site: unleashed_site's deploy/setup.sh), then run this again."
        exit 1
    fi
fi
{
    echo "# Written by deploy/setup.sh. Every service on this box writes its own"
    echo "# sites into /etc/caddy/sites/, and this file only gathers them."
    echo "import /etc/caddy/sites/*.caddy"
} > "$CADDY.new"
cp "$CADDY" "$CADDY.before-split" 2>/dev/null || true
mv "$CADDY.new" "$CADDY"

# A broken Caddyfile that gets installed anyway takes the site down with it.
# Note that validate only reads the file: it cannot tell whether Caddy will
# be allowed to open the log it names, which is checked below instead.
if ! caddy validate --config "$CADDY"; then
    echo "The new web configuration does not validate; putting the old one back."
    [ -f "$CADDY.before-split" ] && cp "$CADDY.before-split" "$CADDY"
    exit 1
fi
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

# The commit this run installed, written last, when every step above has
# worked: set -e has already stopped the script at any that did not. It is
# how deploy/update.sh tells a checkout that was pulled and installed from
# one that was pulled and then failed to install (site 1.2.1). Before that,
# a failed install was never retried: the pull had already moved HEAD, so
# every later run said "Already up to date" and the site stayed on the old
# version. Written through a .new and a rename, so it is never half there.
if INSTALLED_REV="$(git -C "$SRC" rev-parse HEAD 2>/dev/null)"; then
    printf '%s\n' "$INSTALLED_REV" > "$DEST/.installed.new"
    mv "$DEST/.installed.new" "$DEST/.installed"
    echo "installed $INSTALLED_REV"
fi
# And the guides' commit, the same way, so an update to the guides alone is
# installed by deploy/update.sh and a failed one is retried.
if [ -n "$DOCS_SRC" ] && DOCS_REV="$(git -C "$DOCS_SRC" rev-parse HEAD 2>/dev/null)"; then
    printf '%s\n' "$DOCS_REV" > "$DEST/.installed-docs.new"
    mv "$DEST/.installed-docs.new" "$DEST/.installed-docs"
    echo "installed guides $DOCS_REV"
fi

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
