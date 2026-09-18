#!/usr/bin/env bash
# ===========================================================================
#  µnleashed BBS directory: update
# ===========================================================================
#
# File:        deploy/update.sh
# Purpose:     Pull, re-install, restart, check it still works, and say what
#              changed. Safe to run when there is nothing to do.
#
# Usage:       sudo ./deploy/update.sh                 update now, say everything
#              sudo ./deploy/update.sh --quiet         only speak up if something
#                                                      changed or broke: for cron
#              sudo ./deploy/update.sh --check         is there an update? change
#                                                      nothing
#              sudo ./deploy/update.sh --install-timer install a daily timer and
#                                                      exit
#
# It reuses the domains the install was given, remembered in
# /etc/unleashed-directory/domains, so an update never has to be told them
# again and cannot get them wrong.
#
# Exit codes:  0 nothing to do, or updated and healthy
#              1 something went wrong (cron will notice)
#              2 an update is available (--check only)
#
# Copyright 2026 - Robert Mech
# License:     GNU General Public License v2 or later
# SPDX-License-Identifier: GPL-2.0-or-later
# ===========================================================================
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOMAINS_FILE=/etc/unleashed-directory/domains
QUIET=0
CHECK=0

for arg in "$@"; do
    case "$arg" in
        --quiet) QUIET=1 ;;
        --check) CHECK=1 ;;
        --install-timer) INSTALL_TIMER=1 ;;
        *) echo "unknown option: $arg"; exit 1 ;;
    esac
done

say()  { [ "$QUIET" -eq 1 ] || printf '%s\n' "$1"; }
loud() { printf '%s\n' "$1"; }          # said even in quiet mode

[ "$(id -u)" -eq 0 ] || { loud "run this with sudo"; exit 1; }

# ---------------------------------------------------------------------------
# --install-timer: a daily unattended update, for a box you will forget about.
# ---------------------------------------------------------------------------
if [ "${INSTALL_TIMER:-0}" -eq 1 ]; then
    cat > /etc/systemd/system/unleashed-directory-update.service <<EOF
[Unit]
Description=Update the unleashed BBS directory
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=$SRC/deploy/update.sh --quiet
EOF
    cat > /etc/systemd/system/unleashed-directory-update.timer <<'EOF'
[Unit]
Description=Update the unleashed BBS directory daily

[Timer]
OnCalendar=daily
RandomizedDelaySec=2h
Persistent=true

[Install]
WantedBy=timers.target
EOF
    systemctl daemon-reload
    systemctl enable --now unleashed-directory-update.timer
    loud "Daily update timer installed."
    loud "It runs quietly and only says anything when something changes or breaks."
    loud "Next run:"
    systemctl list-timers unleashed-directory-update.timer --no-pager | sed -n '2p'
    loud ""
    loud "Watch it with: journalctl -u unleashed-directory-update"
    loud "Turn it off with: systemctl disable --now unleashed-directory-update.timer"
    exit 0
fi

cd "$SRC"
[ -d .git ] || { loud "$SRC is not a git checkout, so there is nothing to pull"; exit 1; }

OLD="$(git rev-parse HEAD)"
git fetch --quiet origin
NEW="$(git rev-parse '@{u}')"

if [ "$OLD" = "$NEW" ]; then
    say "Already up to date at $(git log -1 --format='%h %s')"
    exit 0
fi

if [ "$CHECK" -eq 1 ]; then
    loud "An update is available:"
    git log --oneline "$OLD..$NEW" | sed 's/^/  /'
    exit 2
fi

# --ff-only rather than a merge: if the checkout has been edited on the box,
# stop and say so instead of inventing a merge commit nobody asked for.
if ! git merge --ff-only "$NEW" >/dev/null 2>&1; then
    loud "Cannot update: this checkout has local changes or has diverged."
    loud "Look at it with: cd $SRC && git status"
    exit 1
fi

loud "Updated $(git log -1 --format='%h' "$OLD") -> $(git log -1 --format='%h %s')"

# ---------------------------------------------------------------------------
# What changed, in words rather than commit subjects. The changelog is the
# thing worth reading on a machine you have not looked at in a month.
# ---------------------------------------------------------------------------
if git diff --quiet "$OLD" "$NEW" -- CHANGELOG.md; then
    loud ""
    loud "Commits:"
    git log --oneline "$OLD..$NEW" | sed 's/^/  /'
else
    loud ""
    loud "From the changelog:"
    git diff --unified=0 "$OLD" "$NEW" -- CHANGELOG.md \
        | grep -E '^\+' | grep -v '^+++' | sed 's/^+//' | sed 's/^/  /'
fi

# ---------------------------------------------------------------------------
# Re-run the installer with the domains it was given the first time, so one
# code path does the work and an update cannot drift from an install.
# ---------------------------------------------------------------------------
DOMAINS=""
[ -f "$DOMAINS_FILE" ] && DOMAINS="$(cat "$DOMAINS_FILE")"

loud ""
loud "Installing..."
# shellcheck disable=SC2086
if [ "$QUIET" -eq 1 ]; then
    "$SRC/deploy/setup.sh" $DOMAINS > /tmp/unleashed-update.log 2>&1 || {
        loud "The install failed. Last lines:"
        tail -20 /tmp/unleashed-update.log | sed 's/^/  /'
        exit 1
    }
else
    "$SRC/deploy/setup.sh" $DOMAINS
fi

# ---------------------------------------------------------------------------
# Prove it still works. An update that reports success while the site is down
# is worse than no update at all, and neither systemd nor caddy validate will
# tell you: both of today's bugs passed every check except looking at it.
# ---------------------------------------------------------------------------
fail=0
check() {
    if eval "$2" >/dev/null 2>&1; then
        say "  ok    $1"
    else
        loud "  FAIL  $1"
        fail=1
    fi
}

loud ""
loud "Checking:"
check "the directory answers"      "curl -fsS --max-time 10 http://127.0.0.1:8080/health"
check "the service is running"     "systemctl is-active --quiet unleashed-directory"
check "caddy is running"           "systemctl is-active --quiet caddy"

for d in $DOMAINS; do
    check "$d serves a page"       "curl -fsS --max-time 20 https://$d/"
done

# The one that matters most: a board cannot follow a redirect to TLS it does
# not have, so /announce must still be answered over plain HTTP.
first="$(echo $DOMAINS | awk '{print $1}')"
if [ -n "$first" ]; then
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "http://$first/announce" || true)"
    if [ "$code" = "404" ] || [ "$code" = "405" ] || [ "$code" = "400" ]; then
        say "  ok    /announce still reachable over plain HTTP"
    else
        loud "  FAIL  /announce returned $code over plain HTTP (a redirect breaks every board)"
        fail=1
    fi
fi

# ---------------------------------------------------------------------------
# Optionally say so somewhere. Not email: that needs a mail server on the box,
# and a directory's own domains usually publish "v=spf1 -all", which tells the
# world they send no mail. A webhook needs neither.
#
#   echo 'https://ntfy.sh/your-topic' > /etc/unleashed-directory/notify
#
# Works with ntfy, Discord, Slack, Gotify or anything that takes a POST.
# ---------------------------------------------------------------------------
NOTIFY_FILE=/etc/unleashed-directory/notify
if [ -s "$NOTIFY_FILE" ]; then
    url="$(head -1 "$NOTIFY_FILE")"
    summary="$(git log -1 --format='%h %s')"
    state=$([ "$fail" -eq 0 ] && echo "updated and healthy" || echo "UPDATE PROBLEM")
    curl -fsS --max-time 15 -X POST "$url"          -H 'Content-Type: text/plain'          -d "$(hostname): directory $state
$summary" >/dev/null 2>&1 || loud "  (could not reach the notify URL)"
fi

loud ""
if [ "$fail" -eq 0 ]; then
    loud "Update complete and healthy."
else
    loud "Update finished but something is wrong. Look at:"
    loud "  journalctl -u unleashed-directory -n 30"
    loud "  journalctl -u caddy -n 30"
    exit 1
fi
