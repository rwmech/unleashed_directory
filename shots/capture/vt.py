"""
===========================================================================
 µnleashed BBS directory
===========================================================================
File:         shots/capture/vt.py
Purpose:      A small ANSI screen model for turning a captured session into
              site art. See shots/capture/webshots.sh.

Copyright 2026 - Robert Mech
License:      GNU General Public License v3 or later
SPDX-License-Identifier: GPL-3.0-or-later
===========================================================================
"""
"""A small ANSI screen model that keeps colour and reverse video per cell,
for turning a captured session into site art. Handles what the board sends:
cursor addressing and moves, erase in line and display, SGR, save and
restore, CR, LF with scrolling, BS, UTF-8, and telnet commands."""
import re

CSI = re.compile(rb"\x1b\[([0-9;?]*)([A-Za-z@])")


class Screen:
    def __init__(self, cols=40, rows=24):
        self.cols, self.rows = cols, rows
        self.blank = (" ", 7, False, 0)
        self.grid = [[self.blank] * cols for _ in range(rows)]
        self.x = self.y = 0
        self.fg, self.bold, self.rev = 7, False, 0
        self.saved = (0, 0)

    def _scroll(self):
        self.grid.pop(0)
        self.grid.append([self.blank] * self.cols)

    def _lf(self):
        if self.y == self.rows - 1:
            self._scroll()
        else:
            self.y += 1

    def _put(self, ch):
        if self.x >= self.cols:
            self.x = 0
            self._lf()
        self.grid[self.y][self.x] = (ch, self.fg, self.bold, self.rev)
        self.x += 1

    def _sgr(self, params):
        ps = [int(p) for p in params.split(";") if p.isdigit()] or [0]
        for p in ps:
            if p == 0:
                self.fg, self.bold, self.rev = 7, False, 0
            elif p == 1:
                self.bold = True
            elif p == 22:
                self.bold = False
            elif p == 7:
                self.rev = 1
            elif p == 27:
                self.rev = 0
            elif 30 <= p <= 37:
                self.fg = p - 30
            elif p == 39:
                self.fg = 7

    def _csi(self, params, final):
        p = [int(v) if v.isdigit() else 0 for v in params.replace("?", "").split(";")] if params else []
        n = (p[0] if p and p[0] else 1)
        if final in "Hf":
            self.y = max(0, min(self.rows - 1, (p[0] - 1) if p and p[0] else 0))
            self.x = max(0, min(self.cols - 1, (p[1] - 1) if len(p) > 1 and p[1] else 0))
        elif final == "A":
            self.y = max(0, self.y - n)
        elif final == "B":
            self.y = min(self.rows - 1, self.y + n)
        elif final == "C":
            self.x = min(self.cols - 1, self.x + n)
        elif final == "D":
            self.x = max(0, self.x - n)
        elif final == "G":
            self.x = max(0, min(self.cols - 1, n - 1))
        elif final == "J":
            mode = p[0] if p else 0
            if mode == 2:
                self.grid = [[self.blank] * self.cols for _ in range(self.rows)]
            elif mode == 0:
                for xx in range(self.x, self.cols):
                    self.grid[self.y][xx] = self.blank
                for yy in range(self.y + 1, self.rows):
                    self.grid[yy] = [self.blank] * self.cols
        elif final == "K":
            mode = p[0] if p else 0
            rng = range(self.x, self.cols) if mode == 0 else (
                range(0, self.x + 1) if mode == 1 else range(self.cols))
            for xx in rng:
                if xx < self.cols:
                    self.grid[self.y][xx] = self.blank
        elif final == "m":
            self._sgr(params)
        elif final == "s":
            self.saved = (self.x, self.y)
        elif final == "u":
            self.x, self.y = self.saved

    def feed(self, data):
        data = bytes(data)
        i, n = 0, len(data)
        while i < n:
            b = data[i]
            if b == 0xFF:                      # telnet
                if i + 1 < n and data[i + 1] == 0xFA:
                    j = data.find(b"\xff\xf0", i)
                    i = n if j < 0 else j + 2
                elif i + 1 < n and data[i + 1] == 0xFF:
                    i += 2
                else:
                    i += 3
                continue
            if b == 0x1B:
                m = CSI.match(data, i)
                if m:
                    self._csi(m.group(1).decode(), m.group(2).decode())
                    i = m.end()
                    continue
                if i + 1 < n and data[i + 1] in b"78":
                    if data[i + 1] == ord("7"):
                        self.saved = (self.x, self.y)
                    else:
                        self.x, self.y = self.saved
                    i += 2
                    continue
                i += 2
                continue
            if b == 0x0D:
                self.x = 0
            elif b == 0x0A:
                self._lf()
            elif b == 0x08:
                self.x = max(0, self.x - 1)
            elif b == 0x07:
                pass
            elif b >= 0x20:
                if b < 0x80:
                    self._put(chr(b))
                else:
                    ln = 2 if b < 0xE0 else (3 if b < 0xF0 else 4)
                    self._put(data[i:i + ln].decode("utf-8", "replace"))
                    i += ln
                    continue
            i += 1
        return self

    def text(self):
        return ["".join(c[0] for c in row).rstrip() for row in self.grid]
