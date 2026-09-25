"""Link preview card for unleashed BBS, 1200x630, in the site's style.

What a shared link to the site shows as its picture (og:image and
twitter:image, with twitter:card summary_large_image): the wordmark, the
front page's headline, a line of facts, the drawing of the board and the
address. It uses the site's own pieces rather than copies of them, so the
card cannot drift from the page: LOGO_SVG and FRONT_BOARD_ART out of
server.py, the palette written out here, and the headline face from
static/fonts. The headline sits left of centre and the address bottom left,
so a platform that crops the card square still shows the words.

Usage, from the repository root:
    python brand/make_ogcard.py
It writes brand/unleashed-og-card.html (git-ignored). The PNG the site
serves at /og-card.png is that page screenshotted in headless Chrome at
exactly 1200x630:
    chrome --headless=new --disable-gpu --hide-scrollbars --no-first-run
           --no-default-browser-check --disable-background-networking
           --user-data-dir=<a scratch profile> --window-size=1200,630
           --screenshot=brand/unleashed-og-card-1200x630.png
           brand/unleashed-og-card.html
selftest.py checks the file is a 1200 x 630 PNG.

Copyright 2026 - Robert Mech
License:      GNU General Public License v3 or later
SPDX-License-Identifier: GPL-3.0-or-later
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import server  # noqa: E402  (reads its files; binds nothing at import)

font = (ROOT / "static" / "fonts" / "Oxanium-latin.woff").as_uri()
page = f"""<!doctype html><html><head><meta charset="utf-8"><style>
@font-face {{ font-family:"Pitch"; src:url("{font}") format("woff"); font-weight:500; }}
html,body{{margin:0;width:1200px;height:630px;background:#0b0b0f;overflow:hidden;}}
.c{{position:relative;box-sizing:border-box;width:1200px;height:630px;padding:64px 72px;
  background:radial-gradient(ellipse at 85% 60%, rgba(127,212,255,0.10), transparent 55%), #0b0b0f;
  font-family:Consolas,Menlo,"DejaVu Sans Mono",monospace;}}
.c .logo{{width:430px;height:auto;display:block;}}
.c h1{{font-family:"Pitch",monospace;font-weight:500;color:#eeeaf8;font-size:58px;
  line-height:1.12;margin:52px 0 0;width:640px;}}
.c h1 em{{font-style:normal;color:#7fd4ff;}}
.c p{{color:#8a8a8a;font-size:22px;letter-spacing:0.04em;margin:28px 0 0;}}
.c p b{{color:#c8c8c8;font-weight:normal;}}
.c .art{{position:absolute;right:60px;top:210px;width:430px;}}
.c .art svg{{width:100%;height:auto;}}
.c .u{{position:absolute;left:72px;bottom:52px;color:#4ce0e0;font-size:22px;letter-spacing:0.14em;}}
</style></head><body><div class="c">{server.LOGO_SVG}
<h1>Your own online community, on a device that <em>fits in your hand</em>.</h1>
<p><b>About $5</b> &middot; <b>five minutes</b> &middot; <b>no ads</b></p>
<div class="art">{server.FRONT_BOARD_ART}</div><div class="u">UNLEASHEDBBS.COM</div></div>
</body></html>"""
out = ROOT / "brand" / "unleashed-og-card.html"
out.write_text(page, encoding="utf-8")
print(out)
