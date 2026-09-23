"""
===========================================================================
 µnleashed BBS directory
===========================================================================
File:         shots/capture/setupshots.py
Purpose:      Capture the first-boot setup screens (firmware 0.23.0 and
              later) for /setup and /install: the setup offer, the setup
              screen, CONFIG staff and the first page of the tour.

Runs in WSL against a board that `tools/harness.sh --tag webshots2 --fresh`
stood up and left behind (no staff passwords, so the board is on the
published default): see setupshots.sh. 80 columns, because the setup and
tour screens are 80 column ANSI art. Nothing here talks to anything but
127.0.0.1.

Usage: setupshots.py <worktree> <outdir> <port>

Copyright 2026 - Robert Mech
License:      GNU General Public License v2 or later
SPDX-License-Identifier: GPL-2.0-or-later
===========================================================================
"""
import json
import os
import sys

FW, OUT, PORT = sys.argv[1], sys.argv[2], sys.argv[3]
COLS = 80
os.environ["BBS_DATA"] = "/tmp/bbs-webshots2/data"
os.environ["BBS_FRESH"] = "1"
sys.argv = ["setupshots", "127.0.0.1", PORT]
sys.path.insert(0, os.path.join(FW, "tools"))
import testclient as tc  # noqa: E402

c = tc.Caller(ansi=True, utf8=True)
c.s.sendall(b"\xff\xfb\x1f\xff\xfa\x1f\x00" + bytes([COLS]) + b"\x00\x18\xff\xf0")
c.wait_for(b"Enter your handle", 12)
print("registered", tc.login(c, "Sparks", wait_main=False))
marks = {}


def page_until(text, tries=8):
    """Press SPACE through page breaks until text is on the screen."""
    for _ in range(tries):
        if text in tc.plain(c.buf):
            return True
        p = tc.plain(c.buf)
        if b"Press SPACE" in p or b"PRESS SPACE" in p:
            c.send(b" ")
        c.pump(1.0)
    return text in tc.plain(c.buf)


print("offer", c.wait_for(b"Sysop password", 10))
c.pump(1.0)
marks["setup-offer"] = len(c.buf)

c.send(b"unleashed\r")
print("staff form", page_until(b"STAFF PASSWORDS"))
c.pump(1.5)
marks["config-staff"] = len(c.buf)
# The setup screen plays and the form clears it at once, so it is never on
# the glass when a capture could be taken. Its end is the form's own clear
# screen: everything before that is the setup screen as it was drawn.
form = bytes(c.buf).find(b"STAFF PASSWORDS", marks["setup-offer"])
marks["setup-screen"] = bytes(c.buf).rfind(b"\x1b[2J", marks["setup-offer"], form)
print("setup screen ends at", marks["setup-screen"])

c.send(b"fresh1234" + tc.F1)
print("tour", c.wait_for(b"SETTING UP YOUR BOARD", 10))
c.pump(2.0)
marks["newsysop-1"] = len(c.buf)
page_until(b"Sysop:", 12)
c.pump(1.0)

with open(os.path.join(OUT, "session.bin"), "wb") as fh:
    fh.write(bytes(c.buf))
with open(os.path.join(OUT, "marks.json"), "w") as fh:
    json.dump({"cols": COLS, "marks": marks}, fh)
print("bytes", len(c.buf), marks)
c.close()
