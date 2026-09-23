#!/bin/sh
# ===========================================================================
#  µnleashed BBS directory
# ===========================================================================
# File:         shots/capture/setupshots.sh
# Purpose:      Capture the first-boot setup screens for /setup and /install,
#               from the firmware's host build, on 127.0.0.1 only.
# Usage:        sh shots/capture/setupshots.sh <firmware worktree> <out dir>
#
# In a worktree of your own, never somebody's working tree:
#   git -C <firmware repo> worktree add <scratch>/fw <commit>
#   sh <scratch>/fw/tools/harness.sh --tag webshots2 --fresh --only=first_setup
# The harness builds host/bbs_host and leaves /tmp/bbs-webshots2 behind with
# no staff passwords. This restores that fresh config (the harness's own run
# set a password), stands the board up on the tag's port, registers a caller,
# takes the setup, and stops the board. Only this tag's board is killed.
# Then:  python shots/capture/shots2json.py <out dir> shots
#
# Copyright 2026 - Robert Mech
# License:      GNU General Public License v2 or later
# SPDX-License-Identifier: GPL-2.0-or-later
# ===========================================================================
set -e
FW="$1"
OUT="$2"
HERE=$(cd "$(dirname "$0")" && pwd)
PORT=$((6500 + $(printf '%s' webshots2 | cksum | cut -d' ' -f1) % 400))
DIR=/tmp/bbs-webshots2
DATA=$DIR/data

pkill -f "bbs_host $DATA" 2>/dev/null || true
sleep 0.3
rm -f "$DATA/user/users.txt"
rm -rf "$DATA/user/p" "$DATA/logs"
# Back to a board on the published default: no staff password lines at all.
sed -i -E '/^(sysop|cosysop1|cosysop2)_password *=/d' "$DATA/user/system.cfg"

mkdir -p "$OUT"
cd "$FW/host"
./bbs_host "$DATA" "$PORT" > "$DIR/shots.log" 2>&1 &
sleep 1.5
python3 -u "$HERE/setupshots.py" "$FW" "$OUT" "$PORT" || true
pkill -f "bbs_host $DATA" 2>/dev/null || true
tail -5 "$DIR/shots.log"
