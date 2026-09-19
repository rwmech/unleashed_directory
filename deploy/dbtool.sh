#!/bin/sh
# ===========================================================================
#  unleashed BBS directory
#  Electronic freedom on a microcontroller.
# ===========================================================================
#
# File:         deploy/dbtool.sh
# Module:       Operations / directory database tool
#
# Purpose:      Look at, tidy up and repair the listings table, for when a
#               board misbehaves or somebody (me, probably) borks it.
#
#               Every command that writes takes a copy of the database
#               first, into /var/backups/unleashed-directory/. Restoring is
#               one command and it is printed every time, because a repair
#               tool you are afraid of is a repair tool you will not run.
#
# Usage:        sudo ./dbtool.sh <command> [argument]
#
#                 status              counts, and what each address holds
#                 list [state]        every listing, or just one state
#                 dupes               addresses holding more than one entry
#                 dedupe              keep the liveliest entry per address,
#                                     delete the rest
#                 prune [days]        delete quiet/queued entries not seen
#                                     for N days (default 7)
#                 promote <id|name>   publish now, skipping the pending wait
#                 forget <id|name>    delete one listing
#                 unstick             release entries stuck in queued
#                 reset               delete every listing (asks twice)
#                 restore <file>      put a backup back
#
# Targets:      the droplet running unleashed-directory
# See also:     INSTALL.md, PROTOCOL.md
#
# Copyright 2026 - Robert Mech
# License:      GNU General Public License v2 or later
# SPDX-License-Identifier: GPL-2.0-or-later
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 2 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, see <https://www.gnu.org/licenses/>. The full
# text is in the LICENSE file at the top of this repository.
# ===========================================================================
set -eu

DB="${DIRECTORY_DB:-/var/lib/unleashed-directory/directory.db}"
BACKUPS="${DIRECTORY_BACKUPS:-/var/backups/unleashed-directory}"
SERVICE=unleashed-directory
YES="${DBTOOL_YES:-0}"

die() { echo "$*" >&2; exit 1; }
q()   { sqlite3 "$DB" "$@"; }

command -v sqlite3 >/dev/null 2>&1 || die "sqlite3 is not installed"
[ -f "$DB" ] || die "no database at $DB (set DIRECTORY_DB to point elsewhere)"

# ---------------------------------------------------------------------------
# A copy before anything that writes. Cheap: the whole table is kilobytes.
# ---------------------------------------------------------------------------
backup() {
    mkdir -p "$BACKUPS"
    stamp="$(date +%Y%m%d-%H%M%S)"
    out="$BACKUPS/directory-$stamp.db"
    # .backup, not cp: it is safe while the server has the file open.
    q ".backup '$out'"
    echo "Backed up to $out"
    echo "  put it back with: sudo $0 restore $out"
    echo
}

confirm() {
    [ "$YES" = "1" ] && return 0
    printf '%s [y/N] ' "$1"
    read -r a
    case "$a" in y|Y|yes|YES) return 0 ;; *) echo "Nothing done."; exit 1 ;; esac
}

# The page is cached in memory, so a change made underneath the server is
# not visible until it is restarted.
bounce() {
    if command -v systemctl >/dev/null 2>&1 && systemctl is-active --quiet "$SERVICE"; then
        systemctl restart "$SERVICE"
        echo "Restarted $SERVICE (that is what drops the page cache)."
    fi
}

show_status() {
    echo "Database: $DB"
    echo
    echo "By state:"
    q -column -header \
      "SELECT state, COUNT(*) AS listings, MAX(beats) AS most_beats
         FROM boards GROUP BY state ORDER BY listings DESC;"
    echo
    echo "By address (more than one is worth a look):"
    q -column -header \
      "SELECT group_key AS address, COUNT(*) AS entries,
              SUM(state IN ('online','pending')) AS live,
              datetime(MAX(last_seen),'unixepoch') AS newest
         FROM boards GROUP BY group_key ORDER BY entries DESC LIMIT 20;"
}

list_rows() {
    where=""
    [ $# -ge 1 ] && where="WHERE state='$1'"
    q -column -header \
      "SELECT id, substr(name,1,22) AS name, state, beats,
              substr(group_key,1,24) AS address,
              datetime(last_seen,'unixepoch') AS last_seen
         FROM boards $where ORDER BY last_seen DESC;"
}

# An id, or a name. Names are how a person thinks about their board.
resolve() {
    case "$1" in
        ''|*[!0-9]*)
            ids="$(q "SELECT id FROM boards WHERE name = '$(echo "$1" | sed "s/'/''/g")';")"
            [ -n "$ids" ] || die "no listing called '$1'"
            echo "$ids"
            ;;
        *) echo "$1" ;;
    esac
}

cmd="${1:-status}"
case "$cmd" in

status) show_status ;;

list)   list_rows "${2:-}" ;;

dupes)
    echo "Addresses holding more than one listing:"
    q -column -header \
      "SELECT group_key AS address, COUNT(*) AS entries,
              GROUP_CONCAT(id) AS ids
         FROM boards GROUP BY group_key HAVING COUNT(*) > 1;"
    ;;

dedupe)
    echo "Addresses holding more than one listing:"
    q -column -header \
      "SELECT group_key AS address, COUNT(*) AS entries FROM boards
        GROUP BY group_key HAVING COUNT(*) > 1;"
    n="$(q "SELECT COUNT(*) FROM boards WHERE id NOT IN
              (SELECT id FROM boards b WHERE b.last_seen =
                 (SELECT MAX(c.last_seen) FROM boards c WHERE c.group_key = b.group_key)
               GROUP BY b.group_key);")"
    [ "$n" = "0" ] && { echo "Nothing to do."; exit 0; }
    confirm "Delete $n duplicate listing(s), keeping the most recently seen for each address?"
    backup
    # Keep the entry each address heard from last: that is the board still
    # talking. The rest are the husks it left behind.
    q "DELETE FROM boards WHERE id NOT IN
         (SELECT id FROM boards b WHERE b.last_seen =
            (SELECT MAX(c.last_seen) FROM boards c WHERE c.group_key = b.group_key)
          GROUP BY b.group_key);"
    echo "Removed $n."
    bounce
    ;;

prune)
    days="${2:-7}"
    n="$(q "SELECT COUNT(*) FROM boards
             WHERE state IN ('offline','queued')
               AND strftime('%s','now') - last_seen > $days * 86400;")"
    [ "$n" = "0" ] && { echo "Nothing older than $days days to prune."; exit 0; }
    confirm "Delete $n quiet or queued listing(s) not seen for $days days?"
    backup
    q "DELETE FROM boards
        WHERE state IN ('offline','queued')
          AND strftime('%s','now') - last_seen > $days * 86400;"
    echo "Removed $n."
    bounce
    ;;

promote)
    [ $# -ge 2 ] || die "usage: $0 promote <id|name>"
    id="$(resolve "$2")"
    confirm "Publish listing $id now, without waiting out the pending hours?"
    backup
    # Backdate the streak rather than forcing the state: settle() then
    # promotes it by its own rules on the next beat and sets public_at, so
    # the feed and the page stay consistent with everything else.
    q "UPDATE boards
          SET state='pending',
              streak_start = strftime('%s','now') - 86400
        WHERE id IN ($id);"
    echo "Done. It goes public on the next heartbeat or page load."
    bounce
    ;;

forget)
    [ $# -ge 2 ] || die "usage: $0 forget <id|name>"
    id="$(resolve "$2")"
    q -column -header "SELECT id, name, state FROM boards WHERE id IN ($id);"
    confirm "Delete the listing(s) above?"
    backup
    q "DELETE FROM boards WHERE id IN ($id);"
    echo "Gone. If that board is still running it will list itself again."
    bounce
    ;;

unstick)
    # queued used to be a dead end. Anything left in it from before the fix
    # can be released by hand.
    n="$(q "SELECT COUNT(*) FROM boards WHERE state='queued';")"
    [ "$n" = "0" ] && { echo "Nothing is queued."; exit 0; }
    confirm "Release $n queued listing(s) so they can earn their place?"
    backup
    q "UPDATE boards SET state='pending', streak_start=strftime('%s','now')
        WHERE state='queued';"
    echo "Released $n. Each now has to sustain heartbeats like any other."
    bounce
    ;;

reset)
    n="$(q "SELECT COUNT(*) FROM boards;")"
    echo "This deletes all $n listing(s). Every board has to earn its place again."
    confirm "Really wipe the whole table?"
    confirm "Last chance. Wipe $n listing(s)?"
    backup
    q "DELETE FROM boards; DELETE FROM reports;"
    echo "Table emptied."
    bounce
    ;;

restore)
    [ $# -ge 2 ] || die "usage: $0 restore <backup file>"
    [ -f "$2" ] || die "no such file: $2"
    confirm "Replace $DB with $2?"
    backup
    if command -v systemctl >/dev/null 2>&1; then systemctl stop "$SERVICE" || true; fi
    cp "$2" "$DB"
    # The server runs as its own user and must still be able to write.
    if id -u directory >/dev/null 2>&1; then chown directory:directory "$DB"; fi
    rm -f "$DB-wal" "$DB-shm"
    if command -v systemctl >/dev/null 2>&1; then systemctl start "$SERVICE" || true; fi
    echo "Restored from $2."
    ;;

*)
    sed -n '/^# Usage:/,/^# Targets:/p' "$0" | sed 's/^# \{0,1\}//;$d'
    exit 1
    ;;
esac
