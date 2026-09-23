"""
===========================================================================
 µnleashed BBS directory
===========================================================================
File:         shots/capture/webshots.py
Purpose:      Drive one ANSI session through CONFIG on the webshots board and
              save the raw bytes and the offsets of each finished screen.

Copyright 2026 - Robert Mech
License:      GNU General Public License v2 or later
SPDX-License-Identifier: GPL-2.0-or-later
===========================================================================
"""
"""Capture real CONFIG screens from the host build, for the setup guide.

Runs in WSL against the board the webshots tag stands up (port 6670, data
in /tmp/bbs-webshots). Saves the raw byte stream of one ANSI session, with
a marker file listing the offsets at which each screen is complete, so the
rendering can be done later by a screen model that keeps colours. Nothing
here talks to anything but 127.0.0.1.

Usage: webshots.py <worktree> <outdir> <port> [columns]
"""
import json
import os
import sys

FW, OUT, PORT = sys.argv[1], sys.argv[2], sys.argv[3]
COLS = int(sys.argv[4]) if len(sys.argv) > 4 else 48
os.environ["BBS_DATA"] = "/tmp/bbs-webshots/data"
sys.argv = ["webshots", "127.0.0.1", PORT]
sys.path.insert(0, os.path.join(FW, "tools"))
import testclient as tc  # noqa: E402

SYSOP = "shots4web"
ESC = b"\x1b"

c = tc.Caller(ansi=True, utf8=True)
# Tell the board the window size before it says anything, the way a terminal
# that speaks NAWS does.
c.s.sendall(b"\xff\xfb\x1f\xff\xfa\x1f\x00" + bytes([COLS]) + b"\x00\x18\xff\xf0")
c.wait_for(b"Enter your handle", 12)
print("login", tc.login(c, "Sparks"))
c.send(b"bye " + SYSOP.encode() + b"\r")
c.wait_for(b"Sysop", 6)
c.pump(1.5)

marks = {}


def shot(name, keys, settle=2.5, then=None):
    c.send(keys)
    c.pump(settle)
    marks[name] = len(c.buf)
    if then is not None:
        c.send(then)
        c.pump(1.5)


shot("start", b"cls\r", 1.0)
shot("config-list", b"config\r")
shot("config-board", b"cls\rconfig board\r", then=ESC)
shot("config-files", b"cls\rconfig files\r")
# Down to Area 1 and open it: the row is a button, the parts are a page.
shot("config-area", tc.DOWN * 4 + b"\r", then=ESC)
c.send(ESC)
c.pump(1.5)
shot("config-announce", b"cls\rconfig announce\r", then=ESC)
shot("config-chat", b"cls\rconfig chat\r", then=ESC)
c.pump(1.0)
with open(os.path.join(OUT, "session.bin"), "wb") as fh:
    fh.write(bytes(c.buf))
with open(os.path.join(OUT, "marks.json"), "w") as fh:
    json.dump({"cols": COLS, "marks": marks}, fh)
print("bytes", len(c.buf), marks)
c.close()
