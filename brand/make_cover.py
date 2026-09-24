"""Cover banner for unleashed BBS, 1600x400, in the site's line-art style.

The wide companion to make_avatar.py: the same wordmark, traced block by
block from LOGO_ROWS in server.py, the same palette, the same line work.
Black like a terminal, with the faint scan lines of one. Used where a
profile page wants a cover (Buy Me a Coffee asks for 1600x400 or more) and
anywhere else a wide header fits.

Usage:  python3 brand/make_cover.py server.py brand/unleashed-cover.svg
        then render the .html beside it at 1600x400 (and 2x for 3200x800).
"""
import ast
import math
import re
import sys
from pathlib import Path

SERVER = Path(sys.argv[1])
OUT = Path(sys.argv[2])

BG, INK, DIM, FAINT, RULE = "#0b0b0f", "#c8c8c8", "#8a8a8a", "#6a6a72", "#1e1e26"
NAME, DIAL, STRUCT, WARM, LIVE = "#b48ef0", "#7fd4ff", "#4ce0e0", "#e0a94e", "#5ddc7a"
W, H = 1600, 400
MONO = "Consolas, 'DejaVu Sans Mono', 'Courier New', monospace"

src = SERVER.read_text(encoding="utf-8")
m = re.search(r"^LOGO_ROWS = \((.*?)^\)", src, re.S | re.M)
rows = list(ast.literal_eval("(" + m.group(1) + ")"))


def wordmark(x0, y0, cw, ch):
    out = []
    for r, line in enumerate(rows):
        for c, g in enumerate(line):
            x, y = x0 + c * cw, y0 + r * ch
            if g == "█":
                out.append((x, y, cw, ch))
            elif g == "▀":
                out.append((x, y, cw, ch / 2))
            elif g == "▄":
                out.append((x, y + ch / 2, cw, ch / 2))
    return "".join(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w + 0.6:.1f}" height="{h + 0.6:.1f}"/>'
                   for x, y, w, h in out)


def text(x, y, s, fill, size=18, anchor="start", spacing=0, weight="normal"):
    s = s.replace("&", "&amp;").replace("<", "&lt;")
    return (f'<text x="{x}" y="{y}" fill="{fill}" font-family="{MONO}" font-size="{size}" '
            f'text-anchor="{anchor}" letter-spacing="{spacing}" font-weight="{weight}">{s}</text>')


p = [f'<rect width="{W}" height="{H}" fill="{BG}"/>']

# the grid, and a terminal's scan lines over it
g = [f'<line x1="{x}" y1="0" x2="{x}" y2="{H}"/>' for x in range(0, W + 1, 40)]
g += [f'<line x1="0" y1="{y}" x2="{W}" y2="{y}"/>' for y in range(0, H + 1, 40)]
p.append(f'<g stroke="{RULE}" stroke-width="1" opacity="0.6">{"".join(g)}</g>')
sl = "".join(f'<rect x="0" y="{y}" width="{W}" height="1"/>' for y in range(0, H, 4))
p.append(f'<g fill="#000" opacity="0.28">{sl}</g>')

# the outer frame, two corners cut
c = 18
p.append(f'<path d="M{c},8 H{W - 8} V{H - c} L{W - c},{H - 8} H8 V{c} Z" fill="none" '
         f'stroke="{DIAL}" stroke-width="1.4" opacity="0.7"/>')

# left: the micro sign emblem in its brackets, as on the avatar
u = 14.5
ex, ey = 80, 58
mu = [(3, 2, 2, 10), (7, 2, 2, 8), (5, 9, 2, 1)]
mr = "".join(f'<rect x="{ex + x * u:.1f}" y="{ey + y * u:.1f}" width="{w * u:.1f}" height="{h * u:.1f}"/>'
             for x, y, w, h in mu)
p.append('<defs><filter id="glow" x="-50%" y="-50%" width="200%" height="200%">'
         '<feGaussianBlur stdDeviation="12"/></filter></defs>')
p.append(f'<g fill="{NAME}" opacity="0.55" filter="url(#glow)">{mr}</g><g fill="{NAME}">{mr}</g>')
bx0, by0, bx1, by1, L = ex + 1.2 * u, ey + 0.4 * u, ex + 10.8 * u, ey + 12.8 * u, 30
p.append(f'<path d="M{bx0},{by0 + L} V{by0 + 9} L{bx0 + 9},{by0} H{bx0 + L} '
         f'M{bx1 - L},{by0} H{bx1} V{by0 + L} M{bx1},{by1 - L} V{by1 - 9} L{bx1 - 9},{by1} H{bx1 - L} '
         f'M{bx0 + L},{by1} H{bx0} V{by1 - L}" fill="none" stroke="{DIAL}" stroke-width="2" '
         f'stroke-linecap="round"/>')
p.append(f'<line x1="{bx0 + 12}" y1="{ey + 7.5 * u:.1f}" x2="{bx1 - 12}" y2="{ey + 7.5 * u:.1f}" '
         f'stroke="{STRUCT}" stroke-width="1.3" opacity="0.7"/>')

# Where things go is set by how Buy Me a Coffee shows a cover: it crops
# the top 60 or so pixels, and lays its About and Support cards over the
# middle from about y 200 down, between x 370 and 1225 (Rob's screenshot).
# So everything that says anything sits in the band y 64..196 across the
# middle, and only the emblem and the terminal box, at the sides where no
# card lands, run lower. The first cut put the wordmark 161px tall with the
# motto under it, and the cards covered the motto.

# centre: the wordmark, in the band, with a rule over it
cols = max(len(r) for r in rows)
cw = 9.0
ch = cw * 2
ww = cols * cw
wx = 330
wy = 86
p.append(f'<line x1="{wx}" y1="{wy - 14}" x2="{wx + ww}" y2="{wy - 14}" stroke="{DIAL}" '
         f'stroke-width="1" opacity="0.5"/>')
p.append(f'<g fill="{NAME}">{wordmark(wx, wy, cw, ch)}</g>')
ly = wy + len(rows) * ch + 12
p.append(f'<line x1="{wx}" y1="{ly}" x2="{wx + ww}" y2="{ly}" stroke="{DIAL}" stroke-width="1" opacity="0.5"/>')

# beside it, not under it: the motto, the tagline and the segments
tx = wx + ww + 38
p.append(text(tx, wy + 34, "ELECTRONIC FREEDOM", STRUCT, 22, spacing=5))
p.append(text(tx, wy + 66, "No web. No cloud. No browser.", DIM, 16, spacing=1))
for i in range(8):
    col, op = (WARM, 1.0) if i == 3 else (DIAL, 0.35)
    p.append(f'<rect x="{tx + i * 34:.1f}" y="{wy + 86}" width="26" height="5" '
             f'fill="{col}" opacity="{op}"/>')

# right: a terminal readout in a cut-corner box, a tick ruler under it with
# its caret, the way the site's freedoms panel carries one
bxl, byt, bw, bh, k = 1290, 70, 250, 180, 12
p.append(f'<path d="M{bxl + k},{byt} H{bxl + bw} V{byt + bh - k} L{bxl + bw - k},{byt + bh} '
         f'H{bxl} V{byt + k} Z" fill="{BG}" fill-opacity="0.85" stroke="{DIAL}" stroke-width="1.4"/>')
lines = [("CONNECT 2400", LIVE), ("NODE 1 OF 10", INK), ("TELNET PETSCII ANSI", DIAL),
         ("ESP32  GPL v3+", WARM), ("[1] Main:", STRUCT)]
for i, (s, col) in enumerate(lines):
    p.append(text(bxl + 18, byt + 32 + i * 31, s, col, 18, spacing=1))
# the block cursor after the prompt, where the next key would land
p.append(f'<rect x="{bxl + 18 + 10 * 11.0:.1f}" y="{byt + 32 + 4 * 31 - 15}" width="10" height="18" '
         f'fill="{INK}" opacity="0.85"/>')
ry = byt + bh + 28
rt = [f'<line x1="{x}" y1="{ry - (12 if (x - bxl) % 50 == 0 else 6)}" x2="{x}" y2="{ry}"/>'
      for x in range(bxl, bxl + bw + 1, 10)]
p.append(f'<g stroke="{DIAL}" stroke-width="1.2" opacity="0.7">{"".join(rt)}</g>')
p.append(f'<line x1="{bxl}" y1="{ry}" x2="{bxl + bw}" y2="{ry}" stroke="{DIAL}" stroke-width="1" opacity="0.5"/>')
cxr = bxl + 150
p.append(f'<path d="M{cxr - 6},{ry + 12} L{cxr},{ry + 3} L{cxr + 6},{ry + 12} Z" fill="{WARM}"/>')

svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
       f'viewBox="0 0 {W} {H}">{"".join(p)}</svg>')
OUT.write_text(svg, encoding="utf-8")
OUT.with_suffix(".html").write_text(
    '<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;padding:0;'
    'background:#0b0b0f}svg{display:block}</style></head><body>' + svg + "</body></html>",
    encoding="utf-8")
print("wrote", OUT, "wordmark", round(ww), "x", round(len(rows) * ch))
