"""Profile image for unleashed BBS, in the directory site's line-art style.

The wordmark is drawn from the site's own LOGO_ROWS (server.py), block by
block, so it is the same letterforms as the site header rather than a font.
Everything that matters sits inside a centred circle, so a round avatar crop
loses nothing.

Usage, from the repository root:
    python3 brand/make_avatar.py server.py brand/unleashed-avatar.svg
It writes the SVG and, beside it, an .html page holding it (git-ignored).
The two PNGs the site serves are that page screenshotted in a browser at
1024 and 512 pixels square: unleashed-avatar-1024.png is og:image and
twitter:image, unleashed-avatar-512.png is the apple-touch-icon.
"""
import ast
import math
import re
import sys
from pathlib import Path

SERVER = Path(sys.argv[1])
OUT = Path(sys.argv[2])

BG, INK, DIM, FAINT, RULE = "#0b0b0f", "#c8c8c8", "#8a8a8a", "#6a6a72", "#1e1e26"
NAME, DIAL, STRUCT, WARM = "#b48ef0", "#7fd4ff", "#4ce0e0", "#e0a94e"
S = 1024
C = S / 2

src = SERVER.read_text(encoding="utf-8")
m = re.search(r"^LOGO_ROWS = \((.*?)^\)", src, re.S | re.M)
rows = list(ast.literal_eval("(" + m.group(1) + ")"))


def wordmark(x0, y0, cw, ch):
    """Rects for the block wordmark: full, upper half and lower half cells."""
    out = []
    for r, line in enumerate(rows):
        for c, g in enumerate(line):
            x = x0 + c * cw
            y = y0 + r * ch
            if g == "█":
                out.append((x, y, cw, ch))
            elif g == "▀":
                out.append((x, y, cw, ch / 2))
            elif g == "▄":
                out.append((x, y + ch / 2, cw, ch / 2))
    return "".join(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w + 0.6:.1f}" height="{h + 0.6:.1f}"/>'
                   for x, y, w, h in out)


cols = max(len(r) for r in rows)
cw = 11.6
ch = cw * 2
wm_w = cols * cw
wm_x = C - wm_w / 2
wm_y = 590

parts = []
parts.append(f'<rect width="{S}" height="{S}" fill="{BG}"/>')

# faint grid, the site's rule colour
g = []
for i in range(0, S + 1, 32):
    g.append(f'<line x1="{i}" y1="0" x2="{i}" y2="{S}"/>')
    g.append(f'<line x1="0" y1="{i}" x2="{S}" y2="{i}"/>')
parts.append(f'<g stroke="{RULE}" stroke-width="1" opacity="0.55">{"".join(g)}</g>')

# the dial ring with its tick scale
R = 462
ticks = []
for k in range(120):
    a = math.radians(k * 3 - 90)
    long = k % 10 == 0
    r1 = R - (22 if long else 10)
    x1, y1 = C + r1 * math.cos(a), C + r1 * math.sin(a)
    x2, y2 = C + R * math.cos(a), C + R * math.sin(a)
    ticks.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                 f'stroke-width="{2.2 if long else 1.2}" opacity="{0.95 if long else 0.55}"/>')
parts.append(f'<g stroke="{DIAL}" stroke-linecap="round">{"".join(ticks)}</g>')
parts.append(f'<circle cx="{C}" cy="{C}" r="{R}" fill="none" stroke="{DIAL}" stroke-width="1.6" opacity="0.8"/>')
parts.append(f'<circle cx="{C}" cy="{C}" r="{R - 36}" fill="none" stroke="{DIAL}" stroke-width="1" '
             f'opacity="0.35" stroke-dasharray="2 9"/>')
# a sweep, like the panel's scan line: an arc of the ring picked out
a0, a1 = math.radians(-150), math.radians(-95)
p0 = (C + (R + 12) * math.cos(a0), C + (R + 12) * math.sin(a0))
p1 = (C + (R + 12) * math.cos(a1), C + (R + 12) * math.sin(a1))
parts.append(f'<path d="M{p0[0]:.1f},{p0[1]:.1f} A{R + 12},{R + 12} 0 0 1 {p1[0]:.1f},{p1[1]:.1f}" '
             f'fill="none" stroke="{STRUCT}" stroke-width="3" stroke-linecap="round"/>')
parts.append(f'<circle cx="{p1[0]:.1f}" cy="{p1[1]:.1f}" r="5" fill="{STRUCT}"/>')

# the emblem: the favicon's micro sign, traced from the same 12x12 grid
u = 21.0                      # one favicon unit
ex, ey = C - 6 * u, 150       # the 12x12 box, top-left
mu = [(3, 2, 2, 10), (7, 2, 2, 8), (5, 9, 2, 1)]
mu_rects = "".join(f'<rect x="{ex + x * u:.1f}" y="{ey + y * u:.1f}" width="{w * u:.1f}" height="{h * u:.1f}"/>'
                   for x, y, w, h in mu)
parts.append('<defs><filter id="glow" x="-50%" y="-50%" width="200%" height="200%">'
             '<feGaussianBlur stdDeviation="14"/></filter></defs>')
parts.append(f'<g fill="{NAME}" opacity="0.55" filter="url(#glow)">{mu_rects}</g>')
parts.append(f'<g fill="{NAME}">{mu_rects}</g>')

# brackets round the emblem, cut-corner line work
bx0, by0 = ex + 1.2 * u, ey + 0.4 * u
bx1, by1 = ex + 10.8 * u, ey + 12.8 * u
L = 34
br = (f'M{bx0},{by0 + L} V{by0 + 10} L{bx0 + 10},{by0} H{bx0 + L} '
      f'M{bx1 - L},{by0} H{bx1} V{by0 + L} '
      f'M{bx1},{by1 - L} V{by1 - 10} L{bx1 - 10},{by1} H{bx1 - L} '
      f'M{bx0 + L},{by1} H{bx0} V{by1 - L}')
parts.append(f'<path d="{br}" fill="none" stroke="{DIAL}" stroke-width="2" stroke-linecap="round"/>')
# the scan line across the emblem
parts.append(f'<line x1="{bx0 + 14}" y1="{ey + 7.5 * u:.1f}" x2="{bx1 - 14}" y2="{ey + 7.5 * u:.1f}" '
             f'stroke="{STRUCT}" stroke-width="1.4" opacity="0.7"/>')

# rules either side of the wordmark
parts.append(f'<line x1="{wm_x}" y1="{wm_y - 26}" x2="{wm_x + wm_w}" y2="{wm_y - 26}" '
             f'stroke="{DIAL}" stroke-width="1" opacity="0.5"/>')
parts.append(f'<g fill="{NAME}">{wordmark(wm_x, wm_y, cw, ch)}</g>')
ly = wm_y + len(rows) * ch + 26
parts.append(f'<line x1="{wm_x}" y1="{ly}" x2="{wm_x + wm_w}" y2="{ly}" '
             f'stroke="{DIAL}" stroke-width="1" opacity="0.5"/>')

# the motto, in the heading colour, and the lit segments under it
mono = "Consolas, 'DejaVu Sans Mono', 'Courier New', monospace"
parts.append(f'<text x="{C}" y="{ly + 52}" text-anchor="middle" fill="{STRUCT}" '
             f'font-family="{mono}" font-size="30" letter-spacing="9">ELECTRONIC FREEDOM</text>')
segs = []
n, sw, gap = 8, 30, 10
sx = C - (n * sw + (n - 1) * gap) / 2
for i in range(n):
    col = WARM if i == 2 else DIAL
    op = 1.0 if i == 2 else 0.35
    segs.append(f'<rect x="{sx + i * (sw + gap):.1f}" y="{ly + 78}" width="{sw}" height="6" '
                f'fill="{col}" opacity="{op}"/>')
parts.append("".join(segs))

svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{S}" height="{S}" '
       f'viewBox="0 0 {S} {S}">{"".join(parts)}</svg>')
OUT.write_text(svg, encoding="utf-8")
html = OUT.with_suffix(".html")
html.write_text('<!doctype html><html><head><style>html,body{margin:0;padding:0;background:#0b0b0f}'
                'svg{display:block}</style></head><body>' + svg + "</body></html>", encoding="utf-8")
print("wrote", OUT, "wordmark", round(wm_w), "x", round(len(rows) * ch))
