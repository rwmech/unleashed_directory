"""
===========================================================================
 µnleashed BBS directory
===========================================================================
File:         shots/capture/shots2json.py
Purpose:      Turn a captured session into one JSON file per screen in shots/,
              which server.py draws as the site's art.

Copyright 2026 - Robert Mech
License:      GNU General Public License v2 or later
SPDX-License-Identifier: GPL-2.0-or-later
===========================================================================
"""
"""Turn the captured session into one JSON file per screen for the site.

Each file holds the screen as the board drew it: the rows of text, and for
every cell one character of attribute, '0'-'f' for the colour (0-7, plus 8
when bold) and 'g'-'v' for the same colours in reverse video. Blank rows
above and below the screen's content are dropped, and so are columns to the
right of the widest row, so the drawing is only as big as what is on it.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import vt  # noqa: E402

SRC = pathlib.Path(sys.argv[1])
DST = pathlib.Path(sys.argv[2])
DST.mkdir(parents=True, exist_ok=True)
meta = json.loads((SRC / "marks.json").read_text())
data = (SRC / "session.bin").read_bytes()
cols = meta["cols"]

WANT = {
    "config-list": ("CONFIG", 1, None),
    "config-board": ("CONFIG board", 0, None),
    "config-files": ("CONFIG files", 0, None),
    "config-area": ("CONFIG files, then Enter on Area 1", 0, None),
}

for name, (typed, first, last) in WANT.items():
    s = vt.Screen(cols, 24).feed(data[:meta["marks"][name]])
    rows = s.text()
    used = [i for i, r in enumerate(rows) if r.strip()]
    top = max(first, used[0])
    bottom = used[-1] if last is None else last
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
        "source": "unleashed BBS 0.22.3 (947714e), host build, ANSI at "
                  f"{cols} columns, captured 2026-09-23",
        "typed": typed,
        "cols": width,
        "rows": out_rows,
        "attrs": out_attr,
    }
    (DST / (name + ".json")).write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n",
                                        encoding="utf-8")
    codes = sorted(set("".join(out_attr)))
    print(name, width, "x", len(out_rows), "codes", "".join(codes))
