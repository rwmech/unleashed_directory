#!/bin/sh
# ===========================================================================
#  µnleashed BBS directory
# ===========================================================================
# File:         shots/capture/webshots.sh
# Purpose:      Capture the CONFIG screens /setup shows, from the firmware's
#               host build, on 127.0.0.1 only.
# Usage:        sh shots/capture/webshots.sh <firmware worktree> <out dir> [columns]
#
# Build and run in a worktree of your own, never in somebody's working tree:
#   git -C <firmware repo> worktree add <scratch>/fw <commit>
#   sh <scratch>/fw/tools/harness.sh --tag webshots --card --only=config
# The harness builds host/bbs_host and leaves /tmp/bbs-webshots behind; this
# stands the board up again on that tag's port with a config close to what a
# fresh install ships, drives one ANSI session through CONFIG, and stops the
# board. Only this tag's board is ever killed. Then, on any machine:
#   python shots/capture/shots2json.py <out dir> shots
# and remove the worktree.
#
# Copyright 2026 - Robert Mech
# License:      GNU General Public License v2 or later
# SPDX-License-Identifier: GPL-2.0-or-later
# ===========================================================================
set -e
FW="$1"
OUT="$2"
COLS="${3:-48}"
HERE=$(cd "$(dirname "$0")" && pwd)
# The same port tools/harness.sh derives for the tag.
PORT=$((6500 + $(printf '%s' webshots | cksum | cut -d' ' -f1) % 400))
DIR=/tmp/bbs-webshots
DATA=$DIR/data
CARD=$DIR/card

pkill -f "bbs_host $DATA" 2>/dev/null || true
sleep 0.3
rm -f "$DATA/user/users.txt"
rm -rf "$DATA/user/p" "$DATA/logs"
mkdir -p "$CARD/pub/c64" "$CARD/pub/text"

# The shipped config, with a sysop password so CONFIG can be reached, and the
# card plugins given something to show. Keys above the first section.
python3 - "$FW/data/system.cfg.example" "$DATA/user/system.cfg" <<'PY'
import sys
src, dst = sys.argv[1], sys.argv[2]
s = open(src, encoding="utf-8").read()
import re
# 0.23.0 and later ship the line commented out (no line means the
# published default); older ones ship it empty. Either way, a real one.
s = re.sub(r"(?m)^#?[ \t]*sysop_password[ \t]*=.*$", "sysop_password = shots4web", s, count=1)
extra = """[plugin:files]
enabled = yes
area1   = pub/c64 | C64 Downloads
area2   = pub/text | Text Files

[plugin:forums]
enabled = yes
topic1  = general | General | Anything at all

[plugin:info]
page0   = House rules | all

"""
marker = "# Staff access matrix."
s = s.replace(marker, extra + marker, 1)
open(dst, "w", encoding="utf-8").write(s)
PY

mkdir -p "$OUT"
cd "$FW/host"
BBS_SD_DIR="$CARD" ./bbs_host "$DATA" "$PORT" > "$DIR/shots.log" 2>&1 &
sleep 1.5
python3 -u "$HERE/webshots.py" "$FW" "$OUT" "$PORT" "$COLS" || true
pkill -f "bbs_host $DATA" 2>/dev/null || true
tail -5 "$DIR/shots.log"
