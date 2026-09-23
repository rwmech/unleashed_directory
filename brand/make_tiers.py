"""Membership level cards for the Buy Me a Coffee page, 250x150 (drawn at
that size, rendered at 2x). Same palette and line work as make_avatar.py
and make_cover.py: a cut-corner frame on the terminal black, one line-art
mark per level, the level's name, and four level segments with as many lit
as the level is high.

Usage:  python3 brand/make_tiers.py brand/
        then render each tier-*.html at 250x150, device scale 2.
"""
import math
import sys
from pathlib import Path

OUT = Path(sys.argv[1])
BG, INK, DIM, RULE = "#0b0b0f", "#c8c8c8", "#8a8a8a", "#1e1e26"
NAME, DIAL, STRUCT, WARM, GOLD = "#b48ef0", "#7fd4ff", "#4ce0e0", "#e0a94e", "#ffd35c"
W, H = 250, 150
MONO = "Consolas, 'DejaVu Sans Mono', 'Courier New', monospace"


def frame(accent):
    k = 9
    g = "".join(f'<line x1="{x}" y1="0" x2="{x}" y2="{H}"/>' for x in range(0, W + 1, 25))
    g += "".join(f'<line x1="0" y1="{y}" x2="{W}" y2="{y}"/>' for y in range(0, H + 1, 25))
    sl = "".join(f'<rect x="0" y="{y}" width="{W}" height="0.5"/>' for y in range(0, H, 3))
    return (f'<rect width="{W}" height="{H}" fill="{BG}"/>'
            f'<g stroke="{RULE}" stroke-width="0.6" opacity="0.7">{g}</g>'
            f'<g fill="#000" opacity="0.25">{sl}</g>'
            f'<path d="M{k + 4},4 H{W - 4} V{H - k - 4} L{W - k - 4},{H - 4} H4 V{k + 4} Z" '
            f'fill="none" stroke="{accent}" stroke-width="1.1" opacity="0.8"/>'
            '<defs><filter id="glow" x="-60%" y="-60%" width="220%" height="220%">'
            '<feGaussianBlur stdDeviation="4"/></filter></defs>')


def mu(cx, cy, u, fill):
    """The favicon's micro sign, centred on (cx, cy)."""
    ox, oy = cx - 6 * u, cy - 7 * u
    r = [(3, 2, 2, 10), (7, 2, 2, 8), (5, 9, 2, 1)]
    rects = "".join(f'<rect x="{ox + x * u:.1f}" y="{oy + y * u:.1f}" width="{w * u:.1f}" height="{h * u:.1f}"/>'
                    for x, y, w, h in r)
    return (f'<g fill="{fill}" opacity="0.6" filter="url(#glow)">{rects}</g>'
            f'<g fill="{fill}">{rects}</g>')


def brackets(x0, y0, x1, y1, col, L=12):
    return (f'<path d="M{x0},{y0 + L} V{y0 + 4} L{x0 + 4},{y0} H{x0 + L} M{x1 - L},{y0} H{x1} V{y0 + L} '
            f'M{x1},{y1 - L} V{y1 - 4} L{x1 - 4},{y1} H{x1 - L} M{x0 + L},{y1} H{x0} V{y1 - L}" '
            f'fill="none" stroke="{col}" stroke-width="1.3" stroke-linecap="round"/>')


def ring(cx, cy, R, col):
    t = []
    for k in range(60):
        a = math.radians(k * 6 - 90)
        lng = k % 5 == 0
        r1 = R - (6 if lng else 3)
        t.append(f'<line x1="{cx + r1 * math.cos(a):.1f}" y1="{cy + r1 * math.sin(a):.1f}" '
                 f'x2="{cx + R * math.cos(a):.1f}" y2="{cy + R * math.sin(a):.1f}" '
                 f'stroke-width="{1.2 if lng else 0.7}" opacity="{0.95 if lng else 0.55}"/>')
    a0, a1 = math.radians(-160), math.radians(-60)
    p0 = (cx + (R + 5) * math.cos(a0), cy + (R + 5) * math.sin(a0))
    p1 = (cx + (R + 5) * math.cos(a1), cy + (R + 5) * math.sin(a1))
    return (f'<g stroke="{DIAL}" stroke-linecap="round">{"".join(t)}</g>'
            f'<circle cx="{cx}" cy="{cy}" r="{R}" fill="none" stroke="{DIAL}" stroke-width="0.9" opacity="0.8"/>'
            f'<path d="M{p0[0]:.1f},{p0[1]:.1f} A{R + 5},{R + 5} 0 0 1 {p1[0]:.1f},{p1[1]:.1f}" fill="none" '
            f'stroke="{col}" stroke-width="2" stroke-linecap="round"/>'
            f'<circle cx="{p1[0]:.1f}" cy="{p1[1]:.1f}" r="2.2" fill="{col}"/>')


def eagle(cx, cy, col):
    """A spread eagle in straight strokes: wings, body, tail, head, beak."""
    wing = [(-5, -8), (-18, -20), (-40, -27), (-35, -18), (-39, -12), (-31, -7),
            (-33, -1), (-22, -1), (-6, 3)]
    L = " ".join(f"{cx + x},{cy + y}" for x, y in wing)
    R = " ".join(f"{cx - x},{cy + y}" for x, y in wing)
    body = (f"M{cx},{cy - 15} L{cx + 6},{cy - 3} L{cx},{cy + 13} L{cx - 6},{cy - 3} Z")
    tail = "".join(f'<line x1="{cx}" y1="{cy + 13}" x2="{cx + dx}" y2="{cy + 23}"/>' for dx in (-6, 0, 6))
    feathers = "".join(
        f'<line x1="{cx + s * a}" y1="{cy + b}" x2="{cx + s * c}" y2="{cy + d}"/>'
        for s in (1, -1) for a, b, c, d in ((-12, -10, -30, -14), (-11, -5, -26, -6)))
    art = (f'<polyline points="{L}"/><polyline points="{R}"/><path d="{body}"/>{tail}{feathers}'
           f'<circle cx="{cx}" cy="{cy - 19}" r="3.6"/>'
           f'<path d="M{cx + 3.4},{cy - 20} L{cx + 8},{cy - 17.5} L{cx + 3},{cy - 16.5}"/>')
    style = f'fill="none" stroke="{col}" stroke-width="1.4" stroke-linejoin="round" stroke-linecap="round"'
    return (f'<g {style} opacity="0.55" filter="url(#glow)">{art}</g><g {style}>{art}</g>')


def star(cx, cy, R, r, col):
    pts = []
    for i in range(10):
        a = math.radians(i * 36 - 90)
        rr = R if i % 2 == 0 else r
        pts.append(f"{cx + rr * math.cos(a):.1f},{cy + rr * math.sin(a):.1f}")
    s = " ".join(pts)
    return (f'<polygon points="{s}" fill="none" stroke="{col}" stroke-width="3" opacity="0.5" filter="url(#glow)"/>'
            f'<polygon points="{s}" fill="{col}" fill-opacity="0.12" stroke="{col}" stroke-width="1.6" '
            f'stroke-linejoin="round"/>'
            f'<circle cx="{cx}" cy="{cy}" r="{R + 9}" fill="none" stroke="{DIAL}" stroke-width="0.8" '
            f'opacity="0.5" stroke-dasharray="1.5 4"/>')


def label(lines, col, level):
    out = []
    for i, s in enumerate(lines):
        out.append(f'<text x="128" y="{62 + i * 16}" fill="{col}" font-family="{MONO}" font-size="12" '
                   f'letter-spacing="1.6">{s}</text>')
    for i in range(4):
        lit = i < level
        out.append(f'<rect x="{128 + i * 24}" y="{96 if len(lines) > 1 else 80}" width="18" height="3.5" '
                   f'fill="{col if lit else DIAL}" opacity="{1 if lit else 0.3}"/>')
    return "".join(out)


TIERS = [
    ("tier-1-supporter", NAME, 1, ["SUPPORTER", "OF FREEDOM"],
     lambda: mu(66, 76, 4.2, NAME) + brackets(34, 40, 98, 112, DIAL)
     + f'<line x1="40" y1="84" x2="92" y2="84" stroke="{STRUCT}" stroke-width="0.9" opacity="0.7"/>'),
    ("tier-2-sustaining", STRUCT, 2, ["SUSTAINING", "FREEDOM"],
     lambda: ring(66, 76, 38, STRUCT) + mu(66, 78, 2.6, NAME)),
    ("tier-3-eagles", WARM, 3, ["EAGLES", "CLUB"],
     lambda: eagle(66, 78, WARM)),
    ("tier-4-lifetime", GOLD, 4, ["LIFETIME", "MEMBER"],
     lambda: star(66, 76, 30, 13, GOLD)),
]

for name, col, level, lines, art in TIERS:
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
           + frame(col) + art() + label(lines, col, level) + "</svg>")
    (OUT / f"{name}.svg").write_text(svg, encoding="utf-8")
    # The page shows it at twice the size: Chrome will not open a window as
    # small as 250x150, so a device-scale render of the real size came out
    # blank. 500x300 is the same card at 2x, which is what gets uploaded.
    big = svg.replace(f'width="{W}" height="{H}"', f'width="{2 * W}" height="{2 * H}"', 1)
    (OUT / f"{name}.html").write_text(
        '<!doctype html><html><head><meta charset="utf-8"><style>html,body{margin:0;padding:0;'
        'background:#0b0b0f}svg{display:block}</style></head><body>' + big + "</body></html>",
        encoding="utf-8")
    print("wrote", name)
