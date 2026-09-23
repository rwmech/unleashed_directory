"""
===========================================================================
 µnleashed BBS directory
===========================================================================
File:         shots/capture/shots2json.py
Purpose:      Turn a captured session into one JSON file per screen in shots/,
              which server.py draws as the site's art.

Usage:        shots2json.py <capture dir> <out dir> <set> <source>
                set      config (webshots.sh) or setup (setupshots.sh)
                source   what it was captured from, for the record, such as
                         "unleashed BBS 0.23.0 (461cb65)"

Each file holds the screen as the board drew it: the rows of text, and for
every cell one character of attribute, '0'-'f' for the colour (0-7, plus 8
when bold) and 'g'-'v' for the same colours in reverse video. Rows outside
the part that matters are dropped, and so are columns right of the widest
row, so the drawing is only as big as what is on it.

Copyright 2026 - Robert Mech
License:      GNU General Public License v2 or later
SPDX-License-Identifier: GPL-2.0-or-later
===========================================================================
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import vt  # noqa: E402

SRC = pathlib.Path(sys.argv[1])
DST = pathlib.Path(sys.argv[2])
SET = sys.argv[3] if len(sys.argv) > 3 else "config"
SOURCE = sys.argv[4] if len(sys.argv) > 4 else "unleashed BBS"
DST.mkdir(parents=True, exist_ok=True)
meta = json.loads((SRC / "marks.json").read_text())
data = (SRC / "session.bin").read_bytes()
cols = meta["cols"]

# name: (caption under the glass, first row's text or None for the top,
#        last row's text or None for the bottom). A row is found by the
#        start of its text, the first match from the top.
SETS = {
    "config": {
        "config-list": ("typed: CONFIG", "[S] Sysop: config", None),
        "config-board": ("typed: CONFIG board", None, None),
        "config-files": ("typed: CONFIG files", None, None),
        "config-area": ("typed: CONFIG files, then Enter on Area 1", None, None),
    },
    "setup": {
        "setup-offer": ("after signing up, from the board's own network",
                        "This board has not been set up yet.", "Sysop password"),
        "setup-screen": ("the default password, typed at that question", None, None),
        "config-staff": ("then the staff passwords form, by itself", None, None),
        "newsysop-1": ("saved: the tour, page 1 of 2", None, None),
    },
}

for name, (caption, first, last) in SETS[SET].items():
    s = vt.Screen(cols, 24).feed(data[:meta["marks"][name]])
    rows = s.text()
    used = [i for i, r in enumerate(rows) if r.strip()]
    top = used[0] if first is None else next(
        i for i, r in enumerate(rows) if r.strip().startswith(first))
    bottom = used[-1] if last is None else next(
        i for i in range(top, len(rows)) if rows[i].strip().startswith(last))
    width = max(len(rows[i]) for i in range(top, bottom + 1))
    out_rows, out_attr = [], []
    for y in range(top, bottom + 1):
        text, attr = "", ""
        for x in range(width):
            ch, fg, bold, rev = s.grid[y][x]
            code = fg + (8 if bold else 0)
            text += ch
            attr += ("0123456789abcdef"[code] if not rev else "ghijklmnopqrstuv"[code])
        out_rows.append(text)
        out_attr.append(attr)
    doc = {
        "source": f"{SOURCE}, host build, ANSI at {cols} columns, captured 2026-09-23",
        "caption": caption,
        "cols": width,
        "rows": out_rows,
        "attrs": out_attr,
    }
    with open(DST / (name + ".json"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    codes = sorted(set("".join(out_attr)))
    print(name, width, "x", len(out_rows), "codes", "".join(codes))
