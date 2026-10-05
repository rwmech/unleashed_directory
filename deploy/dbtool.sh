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
#                 dedupe              per address, delete the entries past
#                                     its newest that have stopped
#                                     answering. Anything still beating is
#                                     left alone, however many it holds
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
# License:      GNU General Public License v3 or later
# SPDX-License-Identifier: GPL-3.0-or-later
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation; either version 3 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program. If not, see <https://www.gnu.org/licenses/>. The full
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
    # Several listings from one address is ordinary now, up to
    # DIRECTORY_PER_ADDRESS of them: what is worth a look is an address
    # holding more entries than it has live ones. Those extras are husks,
    # and dedupe clears the ones that have gone quiet.
    #
    # More LIVE than PER_ADDRESS is worth a look too, and it does not mean
    # the server is broken: the cap is only read on the way in, and a board
    # coming back from 'offline' is restored straight to 'online' without
    # consulting it (server.py's offline branch). Four published, a fifth
    # queued, one of the four quiet long enough to go offline, the queued
    # one promoted into the gap, then the quiet one returns: five live.
    echo "By address (more entries than live ones is worth a look):"
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

# An id, or a name. Names are how a person thinks about their board, so a
# name is matched without caring about case, and then as a fragment, because
# insisting on the exact spelling of something you can see on screen is a
# tool arguing with you. When nothing matches, show what there is instead of
# just saying no.
resolve() {
    case "$1" in
        ''|*[!0-9]*)
            safe="$(echo "$1" | sed "s/'/''/g")"
            # GROUP_CONCAT, because sqlite3 prints one id per line and those
            # go straight into an SQL "IN (...)" list. Newlines there produce
            # "IN (1 2)", which is a syntax error rather than two ids.
            ids="$(q "SELECT GROUP_CONCAT(id) FROM boards WHERE name = '$safe' COLLATE NOCASE;")"
            [ -n "$ids" ] || ids="$(q "SELECT GROUP_CONCAT(id) FROM boards WHERE name LIKE '%$safe%';")"
            if [ -z "$ids" ]; then
                echo "No listing matching '$1'. What is there:" >&2
                q -column -header "SELECT id, name, state FROM boards ORDER BY id;" >&2
                exit 1
            fi
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
    # The husks, and only the husks (2.0.17). This used to keep the one
    # entry each address was heard from last and delete every other,
    # which was right while a directory published one listing per address
    # and is destructive now that it can publish several: three real
    # boards behind one home router would have lost two of them, and
    # their charts, to a command whose whole job is tidying up after a
    # lost token. An entry that is still beating is somebody's board,
    # which is the rule the server's own eviction already follows, so
    # this uses the same test it does: quiet for more than three of the
    # board's own intervals (MISSED_BEATS in server.py, a literal here
    # because it is not an environment variable; if it is ever made one,
    # the two have to move together or the tool and the server disagree
    # about what "stopped answering" means).
    #
    # The newest entry an address holds is never touched (the test is
    # strict, so everything tied at the newest is spared), which means an
    # address with one listing, dead or alive, keeps it. Age alone is
    # prune's job.
    #
    # The last clause is the one that is easy to leave out, and the code
    # review found it missing from the first cut. A board that has lost its
    # token mints a row on every heartbeat, so it is BY CONSTRUCTION its
    # address's newest entry: with the whole house otherwise dark, say two
    # boards being flashed, every real listing behind it is then "past the
    # newest and quiet" and the only survivor is the worthless row. So a
    # row goes only if it never came back to a token of its own
    # (beats = 1, which is what a row minted by a stranger and abandoned
    # looks like: server.py inserts 1 and only the known-token path
    # increments it), or some established sibling at the address is still
    # answering, which is what tells "this address is up and that row is
    # dead" from "everything here is off".
    #
    # MAX(interval_min,1) and the group_key guard are for a hand-edited or
    # restored database, which is the state this tool exists for: an
    # interval of 0 makes the grace 0, and the empty group_key the schema
    # allows would judge unrelated boards as each other's siblings.
    dead="b.last_seen < (SELECT MAX(c.last_seen) FROM boards c
                          WHERE c.group_key = b.group_key)
          AND b.group_key <> ''
          AND strftime('%s','now') - b.last_seen
                > MAX(b.interval_min, 1) * 60 * 3
          AND (b.beats <= 1
               OR EXISTS (SELECT 1 FROM boards d
                           WHERE d.group_key = b.group_key AND d.beats > 1
                             AND strftime('%s','now') - d.last_seen
                                   <= MAX(d.interval_min, 1) * 60 * 3))"
    # Pin the ids once, the way resolve() does and for a reason the first
    # cut got wrong: q() is one sqlite3 process per call, so the predicate
    # above was evaluated afresh for the count, for the list, and for each
    # delete, with strftime('now') moving between them AND a human's y/N in
    # the middle. A live board that crossed its grace during that wait was
    # deleted without ever being printed, and a row that crossed between
    # two of the deletes lost its chart and kept its listing, which is the
    # orphan class this same change set out to close. Pinned, what is
    # printed is what is counted is what is deleted.
    ids="$(q "SELECT GROUP_CONCAT(b.id) FROM boards b WHERE $dead;")"
    echo "Addresses holding more than one listing:"
    q -column -header \
      "SELECT group_key AS address, COUNT(*) AS entries,
              SUM(state IN ('online','pending')) AS live
         FROM boards GROUP BY group_key HAVING COUNT(*) > 1;"
    echo
    [ -n "$ids" ] || {
        echo "Nothing to do: everything these addresses hold is the newest"
        echo "entry, or still beating, or the only thing still answering"
        echo "there. Remove one by hand with:"
        echo "  sudo $0 forget <id>"
        exit 0
    }
    echo "Entries past an address's newest that have stopped answering:"
    q -column -header \
      "SELECT id, substr(name,1,22) AS name, state, beats,
              substr(group_key,1,24) AS address,
              datetime(last_seen,'unixepoch') AS last_seen
         FROM boards WHERE id IN ($ids) ORDER BY group_key, last_seen;"
    n="$(q "SELECT COUNT(*) FROM boards WHERE id IN ($ids);")"
    confirm "Delete the $n entr(y/ies) above?"
    # Pinned once more after the wait, and only ever NARROWING: a row in
    # the list above that has started answering while the prompt sat there
    # is dropped rather than deleted. So what is deleted is always a subset
    # of what was shown and agreed to, it is still one pinned set for all
    # four deletes, and the one thing this command must never do, take a
    # board that is alive, cannot happen however long the prompt waits.
    ids="$(q "SELECT GROUP_CONCAT(b.id) FROM boards b
               WHERE b.id IN ($ids) AND $dead;")"
    [ -n "$ids" ] || { echo "They are all answering again. Nothing done."; exit 0; }
    gone="$(q "SELECT COUNT(*) FROM boards WHERE id IN ($ids);")"
    [ "$gone" = "$n" ] || echo "$((n - gone)) of them answered again and are left alone."
    backup
    # The chart rows go with the listing. Leaving them orphaned means a
    # board that is deduped away keeps feeding samples nothing can read,
    # and the survivor looks like it has no history at all. boards.id is an
    # INTEGER PRIMARY KEY without AUTOINCREMENT, so SQLite hands a freed
    # rowid to the next new listing, and an orphan row is then inherited by
    # a board that never earned it.
    q "DELETE FROM activity  WHERE board_id IN ($ids);"
    q "DELETE FROM beathours WHERE board_id IN ($ids);"
    q "DELETE FROM reports   WHERE board_id IN ($ids);"
    q "DELETE FROM boards    WHERE id IN ($ids);"
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
    q "DELETE FROM activity WHERE board_id IN
         (SELECT id FROM boards WHERE state IN ('offline','queued')
            AND strftime('%s','now') - last_seen > $days * 86400);"
    q "DELETE FROM beathours WHERE board_id IN
         (SELECT id FROM boards WHERE state IN ('offline','queued')
            AND strftime('%s','now') - last_seen > $days * 86400);"
    q "DELETE FROM reports WHERE board_id IN
         (SELECT id FROM boards WHERE state IN ('offline','queued')
            AND strftime('%s','now') - last_seen > $days * 86400);"
    q "DELETE FROM boards
        WHERE state IN ('offline','queued')
          AND strftime('%s','now') - last_seen > $days * 86400;"
    echo "Removed $n."
    bounce
    ;;

promote)
    [ $# -ge 2 ] || die "usage: $0 promote <id|name>"
    id="$(resolve "$2")"
    # Publishing two listings because a name matched twice is exactly the
    # mess this tool exists to clean up, so it asks rather than guesses.
    case "$id" in
        *,*)
            echo "'$2' matches more than one listing:" >&2
            q -column -header \
              "SELECT id, name, state, datetime(last_seen,'unixepoch') AS last_seen
                 FROM boards WHERE id IN ($id);" >&2
            die "Promote one of them by id, or run dedupe first."
            ;;
    esac
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
    q "DELETE FROM activity  WHERE board_id IN ($id);"
    q "DELETE FROM beathours WHERE board_id IN ($id);"
    q "DELETE FROM reports   WHERE board_id IN ($id);"
    q "DELETE FROM boards    WHERE id IN ($id);"
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
    q "DELETE FROM boards; DELETE FROM reports; DELETE FROM activity;
       DELETE FROM beathours;"
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
