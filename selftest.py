#!/usr/bin/env python3
"""
===========================================================================
 µnleashed BBS directory
===========================================================================

File:         selftest.py
Module:       Directory server / tests

Purpose:      Starts a directory on a scratch database and walks it through
              the whole life of a listing: first announce, token issue,
              the pending window, going public, a second board from the
              same address queueing, the rate limit, and going quiet.

Usage:        python3 selftest.py

Copyright 2026 - Robert Mech
License:      GNU General Public License v2 or later
SPDX-License-Identifier: GPL-2.0-or-later
===========================================================================
"""

import html
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

PORT = 8123
BASE = f"http://127.0.0.1:{PORT}"
passed = failed = 0


def has_h(page, level, text):
    """A heading with this text, carrying the id md_render gives it."""
    return re.search(rf'<h{level} id="[a-z0-9-]+">{re.escape(text)}</h{level}>',
                     page) is not None


def check(label, ok):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    if ok:
        passed += 1
    else:
        failed += 1
    return ok


def post(payload):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(f"{BASE}/announce", data=data,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode()), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}"), dict(e.headers)


def get(path, host=None, headers=None):
    req = urllib.request.Request(f"{BASE}{path}")
    if host:
        req.add_header("Host", host)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        # A 404 is an answer, not a failure. Checking that something is
        # absent is as much a test as checking it is there.
        return e.code, e.read().decode(errors="replace")


def fetch(path, base=None):
    """(status, content type, body bytes) for one GET, with no Host games."""
    req = urllib.request.Request(f"{base or BASE}{path}")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()


def seen(path="/health", headers=None):
    """What the server thinks the caller's address is, off the response."""
    req = urllib.request.Request(f"{BASE}{path}")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.headers.get("X-Seen-Address")


def fk_grade(page):
    """Flesch-Kincaid grade level of a rendered page's prose.

    Measured on what a reader sees rather than on the Markdown. Headings,
    code and tables are dropped, because a heading has no full stop and
    would fold into the sentence after it, which flatters the score. A list
    item counts as a sentence, which is what it reads as.

    Syllables come from the usual vowel-group heuristic. It is an estimate,
    and it is the same estimate every implementation of this formula uses,
    so the number is comparable with anybody else's.
    """
    body = page.split("<article>")[1].split("</article>")[0]
    for pat in (r"<h[1-6][^>]*>.*?</h[1-6]>", r"<pre.*?</pre>", r"<table.*?</table>"):
        body = re.sub(pat, " ", body, flags=re.S)
    body = re.sub(r"</(li|p)>", ". ", body)
    text = html.unescape(re.sub(r"<[^>]+>", " ", body))
    text = re.sub(r"\s+", " ", text).strip()

    def syllables(word):
        w = re.sub(r"[^a-z]", "", word.lower())
        n, prev = 0, False
        for ch in w:
            v = ch in "aeiouy"
            if v and not prev:
                n += 1
            prev = v
        if w.endswith("e") and not w.endswith(("le", "ee", "ye")) and n > 1:
            n -= 1
        return max(1, n) if w else 0

    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    words = re.findall(r"[A-Za-z0-9']+", text)
    if not sentences or not words:
        return None
    syl = sum(syllables(w) for w in words)
    return 0.39 * (len(words) / len(sentences)) + 11.8 * (syl / len(words)) - 15.59


# The boards table as it stood before the badges (site 0.20.2 and earlier),
# for the migration check: exactly what CREATE TABLE made then, before the
# ALTERs that setup() applies on start. The live database is one of these.
OLD_SCHEMA = """
CREATE TABLE boards (
    id           INTEGER PRIMARY KEY,
    token        TEXT UNIQUE NOT NULL,
    name         TEXT NOT NULL,
    owner        TEXT NOT NULL DEFAULT '',
    description  TEXT NOT NULL DEFAULT '',
    software     TEXT NOT NULL DEFAULT '',
    version      TEXT NOT NULL DEFAULT '',
    host         TEXT NOT NULL DEFAULT '',
    address      TEXT NOT NULL DEFAULT '',
    group_key    TEXT NOT NULL DEFAULT '',
    port         INTEGER NOT NULL DEFAULT 6400,
    nodes        INTEGER NOT NULL DEFAULT 0,
    busy         INTEGER NOT NULL DEFAULT 0,
    calls24      INTEGER,
    minutes24    INTEGER,
    uptime       INTEGER NOT NULL DEFAULT 0,
    interval_min INTEGER NOT NULL DEFAULT 10,
    state        TEXT NOT NULL DEFAULT 'pending',
    first_seen   INTEGER NOT NULL,
    last_seen    INTEGER NOT NULL,
    streak_start INTEGER NOT NULL,
    public_at    INTEGER NOT NULL DEFAULT 0,
    beats        INTEGER NOT NULL DEFAULT 0,
    note         TEXT NOT NULL DEFAULT ''
);
CREATE TABLE activity (
    board_id INTEGER NOT NULL,
    hour     INTEGER NOT NULL,
    beats    INTEGER NOT NULL DEFAULT 0,
    busy     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (board_id, hour)
);
CREATE TABLE reports (
    id       INTEGER PRIMARY KEY,
    board_id INTEGER NOT NULL,
    at       INTEGER NOT NULL,
    address  TEXT NOT NULL DEFAULT '',
    reason   TEXT NOT NULL DEFAULT ''
);
CREATE TABLE hits (
    address TEXT PRIMARY KEY,
    at      INTEGER NOT NULL
);
"""


def post_from(payload, addr, base=None):
    """An announce that arrives from addr, through the trusted loopback
    proxy, so a test can have boards at different addresses."""
    req = urllib.request.Request(f"{base or BASE}/announce",
                                 data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json",
                                          "X-Forwarded-For": addr})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode() or "{}")


def badge_row(page, name):
    """One board's row of the list, from its name to the end of the row."""
    at = page.find(f"<span class='bname'>{name}</span>")
    return page[at:page.find("</tr>", at)] if at >= 0 else ""


def badges_in(row):
    """(colour class, text) for every lettered badge in a row, in order."""
    return re.findall(r'<span class="bd k-(\w+)"[^>]*>([^<]*)</span>', row)


def badge_checks(S, db):
    """Site 0.21.0: the badge fields, the badges, the steady record, the
    legend, the zebra rows and the hover, and a database from before."""
    import sqlite3

    # ----------------------------------------------------------------------
    print("Badges: what a board sends about itself")
    full = {"software": "unleashed", "version": "1.0.0", "name": "Badge Board",
            "owner": "Tester", "description": "every badge there is",
            "port": 6400, "nodes": 4, "busy": 1, "interval": 10, "token": "",
            "system": "  Com​paq‮ 486\t<b>&</b>  ",
            "terminals": ["PETSCII", "ansi", "bogus", 7, None, "ansi"],
            "guests": True,
            "features": ["doors", "chat", "Files", "gopher"],
            "support": ["ham", "lgbtq", "<script>alert(1)</script>", "HAM", "nazis"]}
    junk = {"name": "Junk Fields", "port": 6400, "token": "",
            "system": ["not", "a", "string"], "terminals": "petscii",
            "guests": "yes", "features": {"chat": True}, "support": "lgbtq"}
    shut = {"name": "No Guests", "port": 6400, "token": "", "guests": False}
    code, got = post_from(full, "198.51.100.7")
    check("a heartbeat carrying every badge field is accepted", code == 200)
    code, gotj = post_from(junk, "198.51.100.8")
    check("and one with nothing but junk in them is accepted too, not refused",
          code == 200)
    _c, gots = post_from(shut, "198.51.100.9")
    time.sleep(2.5)                                    # the pending window
    post_from(dict(full, token=got.get("token", "")), "198.51.100.7")
    post_from(dict(junk, token=gotj.get("token", "")), "198.51.100.8")
    post_from(dict(shut, token=gots.get("token", "")), "198.51.100.9")
    listed = {b["name"]: b for b in json.loads(get("/api/boards.json")[1])["boards"]}
    bb, jb = listed.get("Badge Board", {}), listed.get("Junk Fields", {})
    check("guests false is kept as false, not as not sent",
          listed.get("No Guests", {}).get("guests") is False)
    check("system: a zero-width and a bidi override removed, a tab made a "
          "space, the ends trimmed",
          bb.get("system") == "Compaq 486 <b>&</b>")
    check("terminals: known words only, once each, any case, in the "
          "directory's order", bb.get("terminals") == ["ansi", "petscii"])
    check("guests: a JSON true is true", bb.get("guests") is True)
    check("features: known words only, in order",
          bb.get("features") == ["chat", "files", "doors"])
    check("support: known slugs only; a made-up one, markup and all, is dropped",
          bb.get("support") == ["lgbtq", "ham"])
    check("a field of the wrong type counts as not sent, and the board is "
          "still listed",
          jb.get("system") == "" and jb.get("terminals") == []
          and jb.get("guests") is None and jb.get("features") == []
          and jb.get("support") == [])
    check("the JSON carries the directory's own two as well",
          isinstance(bb.get("listed_at"), int) and bb.get("steady") is False)
    check("and still no token and no note, now that it is built field by field",
          all("token" not in b and "note" not in b for b in listed.values()))
    check("system is cut to 40 characters",
          len(S.tidy_label("x" * 90, S.SYSTEM_MAX)) == 40 and S.SYSTEM_MAX == 40)
    check("a line separator is a space, a bidi override is nothing",
          S.tidy_label("a b‮c", 40) == "a bc")
    check("a character keeps at most two combining marks",
          S.tidy_label("e" + "́" * 30 + "f", 40) == "é́f")
    check("only the first 16 entries of a list are read",
          S.pick(["x"] * 16 + ["ansi"], S.TERMINALS) == []
          and S.pick(["x"] * 15 + ["ansi"], S.TERMINALS) == ["ansi"])

    # ----------------------------------------------------------------------
    print("Badges on the board list")
    page = get("/")[1]
    row = badge_row(page, "Badge Board")
    found = badges_in(row)
    check("the name has a box of its own, the width of the name",
          "<td class='name' data-label='Board'><span class='bname'>Badge Board</span>"
          "<span class=\"badges\">" in page)
    check("software first, then the machine, then P, G and the features, then N",
          found == [("soft", "unleashed"), ("sys", "Compaq 486 &lt;b&gt;&amp;&lt;/b&gt;"),
                    ("term", "P"), ("guest", "G"), ("feat", "C"), ("feat", "Fi"),
                    ("feat", "D"), ("new", "N")])
    check("each feature that is not running has no badge",
          ("feat", "F") not in found and ("feat", "M") not in found)
    check("and the two support symbols, in the list's order, drawn not typed",
          row.count('class="bd k-sup"') == 2
          and row.index('aria-label="Supports LGBTQ+ people.')
          < row.index('aria-label="Supports amateur radio.')
          and row.count("<svg viewBox=\"0 0 24 24\" aria-hidden=\"true\"") == 2)
    check("nothing a board sent reaches the page unescaped",
          "<b>&</b>" not in page and "<script>alert" not in page
          and 'data-tip="Runs on: Compaq 486 &lt;b&gt;&amp;&lt;/b&gt;, in the '
              "board&#x27;s own words.\"" in row)
    n = row.count('class="bd ')
    check("every badge carries a tooltip, a name for a screen reader, and a "
          "focus stop for a keyboard or a tap",
          n == 10 and row.count("data-tip=\"") == n and row.count("aria-label=\"") == n
          and row.count('tabindex="0"') == n and row.count('role="img"') == n)
    check("and no title, which would draw the browser's tooltip over ours",
          " title=" not in row.split("<span class='desc'>")[0])
    check("a PETSCII board's badge says what it means",
          'aria-label="PETSCII: a Commodore 64 or 128 gets colour and graphics '
          'here, not just text."' in row)
    jrow = badge_row(page, "Junk Fields")
    check("a board that sent nothing usable shows only what the directory "
          "worked out", badges_in(jrow) == [("new", "N")])
    check("the tooltip is CSS, drawn from data-tip, on hover and on focus",
          "content:attr(data-tip);" in page
          and ".bd:hover::after, .bd:focus::after { visibility:visible; opacity:1; }"
          in page and "<script" not in page)
    check("at the page's own type size, and never wider than a phone",
          "font-size:0.875rem; line-height:1.45;" in page
          and "max-width:min(24rem, calc(100vw - 3rem));" in page)
    check("badges wrap under the name rather than pushing the Dial column",
          ".badges { position:relative; display:flex; flex-wrap:wrap;" in page
          and "main > table { table-layout:fixed; }" in page)
    check("a small key to them sits right above the table",
          '<p class="keylink"><a href="/badges">What the badges mean</a></p>'
          "<table>" in page)
    feet = {"list": page, "about": get("/", host="about.example")[1]}
    check("and the footer links the legend on every face",
          '<a href="/badges">Badges</a>' in feet["list"].split("<footer>")[1]
          and '<a href="https://boards.example/badges">Badges</a>'
          in feet["about"].split("<footer>")[1])
    feed = get("/feed.xml")[1]
    check("the feed says it in words, escaped for XML",
          "Runs on: Compaq 486 &amp;lt;b&amp;gt;&amp;amp;&amp;lt;/b&amp;gt;" in feed
          and "Supports: LGBTQ+ people, amateur radio" in feed
          and "Speaks: ANSI, PETSCII" in feed and "Guests welcome" in feed
          and "No guests: an account is needed" in feed)

    # ----------------------------------------------------------------------
    print("Badges the directory works out")
    now = int(time.time())
    con = sqlite3.connect(db)
    bid = con.execute("SELECT id FROM boards WHERE name='Badge Board'").fetchone()[0]
    check("every heartbeat is counted into its hour",
          con.execute("SELECT SUM(beats) FROM beathours WHERE board_id=?",
                      (bid,)).fetchone()[0] == 2)
    check("and the board's tally started with its first heartbeat",
          0 < con.execute("SELECT tracked_since FROM boards WHERE id=?",
                          (bid,)).fetchone()[0] <= now)
    con.execute("UPDATE boards SET public_at=?, tracked_since=? WHERE id=?",
                (now - 400 * 86400, now - 8 * 86400, bid))
    con.executemany("INSERT OR REPLACE INTO beathours(board_id, hour, beats) "
                    "VALUES(?,?,6)", [(bid, h) for h in range(now // 3600 - 170,
                                                              now // 3600 + 1)])
    con.commit()
    row = badge_row(get("/")[1], "Badge Board")
    check("a week with every heartbeat in it earns S", ("steady", "S") in badges_in(row))
    check("a board listed 400 days is no longer new, and shows 1y and only 1y",
          ("new", "N") not in badges_in(row)
          and [t for c, t in badges_in(row) if c == "age"] == ["1y"])
    check("and its tooltip says since when",
          f"Listed for a year: on this directory since {S.day_text(now - 400 * 86400)}."
          in row)
    check("the JSON says steady too",
          {b["name"]: b for b in json.loads(get("/api/boards.json")[1])["boards"]}
          ["Badge Board"]["steady"] is True)
    first = now // 3600 - 100
    con.execute("DELETE FROM beathours WHERE board_id=? AND hour>=? AND hour<?",
                (bid, first, first + 24))
    con.commit()
    check("a silent day in the week loses it",
          ("steady", "S") not in badges_in(badge_row(get("/")[1], "Badge Board")))
    con.execute("UPDATE beathours SET beats=60 WHERE board_id=?", (bid,))
    con.commit()
    check("and a burst of extra heartbeats in the other hours cannot buy it back",
          ("steady", "S") not in badges_in(badge_row(get("/")[1], "Badge Board")))
    con.close()
    # The arithmetic on its own, against a scratch table.
    mem = sqlite3.connect(":memory:")
    mem.row_factory = sqlite3.Row
    mem.executescript(S.SCHEMA)
    hour = now // 3600
    every = {h: 6 for h in range(hour - 167, hour + 1)}
    check("every heartbeat at a ten minute interval is the whole share",
          S.steady_share(every, 10, now) > 0.99)
    check("one a hour is the whole share at a sixty minute interval",
          S.steady_share({h: 1 for h in every}, 60, now) > 0.99)
    check("every other hour at double rate is about half, not all of it",
          0.45 < S.steady_share({h: 12 for h in every if h % 2}, 10, now) < 0.55)
    check("two hours missing in a week is still steady, a day missing is not",
          S.steady_share({h: 6 for h in every if not hour - 50 < h < hour - 47},
                         10, now) > 0.95
          > S.steady_share({h: 6 for h in every if not hour - 50 < h < hour - 25},
                           10, now))
    for h in range(hour - 200, hour + 1):
        S.tally(mem, 1, h * 3600)
    check("the hourly record lets go of anything older than the week",
          mem.execute("SELECT MIN(hour) FROM beathours").fetchone()[0]
          == hour - S.STEADY_HOURS)
    mem.executemany("INSERT OR REPLACE INTO beathours(board_id, hour, beats) "
                    "VALUES(1,?,6)", [(h,) for h in every])
    young = {"id": 1, "tracked_since": now - 3 * 86400, "interval_min": 10}
    old = dict(young, tracked_since=now - 8 * 86400)
    never = dict(young, tracked_since=0)
    check("a board not watched for the whole week cannot be steady yet",
          S.steady_boards(mem, [young, never], now) == set()
          and S.steady_boards(mem, [old], now) == {1})
    mem.close()

    # ----------------------------------------------------------------------
    print("The badges page")
    code, leg = get("/badges")
    check("it is served, with its title", code == 200
          and has_h(leg, 1, "What the badges mean"))
    check("every lettered badge is on it, with its colour named",
          all(f">{letters}</span>" in leg and f"<b>{name}</b>" in leg
              and f'<span class="cn k-{cls}">{S.BADGE_COLOURS[cls]}</span>' in leg
              for _k, letters, cls, name, _m in S.LETTER_BADGES))
    check("and the machine, the software and every time-listed step",
          "<b>Machine</b>" in leg and "<b>Software</b>" in leg
          and all(f">{label}</span>" in leg for _d, label, _w in S.AGES))
    check("each says where it comes from, board or directory",
          leg.count("Sent by the board:") == 9
          and leg.count("Worked out here") == 3)
    check("with the two groups under their own headings",
          has_h(leg, 2, "Sent by the board") and has_h(leg, 2, "Worked out by the directory")
          and has_h(leg, 3, "How steady is worked out")
          and 'href="#how-steady-is-worked-out"' in leg)
    check("then Show your support: every symbol, its slug and its sentence",
          has_h(leg, 2, "Show your support")
          and all(f"<code>{slug}</code>" in leg and html.escape(sentence) in leg
                  for slug, _a, _n, sentence in S.SUPPORT))
    check("eleven of them, amateur radio last",
          len(S.SUPPORT) == 11 and S.SUPPORT[-1][0] == "ham"
          and leg.count('class="bd k-sup"') == 11)
    check("each support slug is a plain lower case word, so a board can type it",
          all(re.fullmatch(r"[a-z][a-z-]{1,23}", s) for s in S.SUPPORT_SLUGS)
          and len(set(S.SUPPORT_SLUGS)) == len(S.SUPPORT_SLUGS))
    check("every drawing named in the list exists",
          all(art in S.SUPPORT_ART for _s, art, _n, _t in S.SUPPORT))
    check("the legend's badges have tooltips too",
          'data-tip="Supports amateur radio."' in leg and "<script" not in leg)
    check("it belongs to Boards in the menu, on the list face",
          '<a class="here" href="/">Boards</a>' in leg)
    about_leg = get("/badges", host="about.example")[1]
    check("and on the about face, not to What this is",
          '<a class="here" href="https://boards.example/">Boards</a>' in about_leg
          and 'class="here" href="/">What this is' not in about_leg)
    check("How to get listed shows the fields and links the legend",
          'href="/badges"' in get("/how")[1] and '"support":["ham"]' in get("/how")[1])

    # ----------------------------------------------------------------------
    print("Rows: every other one striped, and the hover")
    css = get("/")[1].split("<style>")[1].split("</style>")[0]
    check("every other board is a shade lighter, starting on the second",
          "main > table tr:nth-child(odd):not(:first-child) { background:#111116; }" in css)
    hover = css[css.index("@media (hover: hover) and (pointer: fine) {\n  main > table"):]
    hover = hover[:hover.index("\n}\n")]
    check("a hovered row gets a dim --dial outline, which moves nothing",
          "outline:1px solid rgba(127, 212, 255, 0.35);" in hover
          and "outline-offset:-1px;" in hover and "border" not in hover)
    check("hover of any kind only where a pointer hovers, so a tap leaves "
          "nothing lit",
          "@media (hover: hover) and (pointer: fine) {\n  tr:hover td {" in css
          and "\ntr:hover td" not in css)
    fly = css[css.index("@media (prefers-reduced-motion: no-preference) and "
                        "(hover: hover) and (pointer: fine) {"):]
    fly = fly[:fly.index("\n}\n")]
    check("the dot flies once per hover, only where motion is not turned down",
          "main > table tr:hover .bname::after { animation:namedot 1s linear 1 both; }"
          in fly and "main > table tr:hover .bname::before { animation:nametail "
          "1s linear 1 both; }" in fly
          and css.count("animation:namedot") == 1 and css.count("animation:nametail") == 1)
    check("its keyframes live where reduced motion switches them off",
          css.index("@keyframes namedot") > css.index(
              "@media (prefers-reduced-motion: no-preference) {\n  @keyframes nametail"))
    check("at rest the dot and its streak are transparent, so reduced motion "
          "leaves the outline alone",
          ".name > .bname::before, .name > .bname::after { content:\"\"; "
          "position:absolute; left:0;\n        opacity:0;" in css)
    check("it travels the name's own width",
          "85% { left:100%; opacity:1; }" in css
          and ".name > .bname { display:block; width:fit-content;" in css)

    # ----------------------------------------------------------------------
    # The live database has rows in it. The change must add its columns to
    # a table made by the old code, leave every row as it was, and serve.
    print("A database from before the badges")
    old_db = os.path.join(tempfile.gettempdir(), f"dirold{os.getpid()}.db")
    for leftover in (old_db, old_db + "-wal", old_db + "-shm"):
        if os.path.exists(leftover):
            os.remove(leftover)
    con = sqlite3.connect(old_db)
    con.executescript(OLD_SCHEMA)
    con.execute("INSERT INTO boards(token, name, owner, software, port, nodes, "
                "state, first_seen, last_seen, streak_start, public_at, beats) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                ("a" * 32, "Old Timer", "Grandad", "unleashed", 6400, 6, "online",
                 now - 90 * 86400, now, now - 90 * 86400, now - 90 * 86400, 5000))
    con.execute("INSERT INTO activity(board_id, hour, beats, busy) VALUES(1, 20, 30, 12)")
    con.commit()
    con.close()
    port4 = PORT + 3
    base4 = f"http://127.0.0.1:{port4}"
    env4 = dict(os.environ, DIRECTORY_PAGE_CACHE="0", DIRECTORY_DB=old_db,
                DIRECTORY_PORT=str(port4), DIRECTORY_MIN_SECONDS="0")
    server4 = subprocess.Popen([sys.executable, "server.py"], env=env4,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out4 = []
    threading.Thread(target=lambda: [out4.append(l) for l in server4.stdout],
                     daemon=True).start()
    try:
        up4 = None
        for _ in range(60):
            try:
                up4 = fetch("/health", base4)[0]
                break
            except Exception:
                if server4.poll() is not None:
                    break
                time.sleep(0.1)
        home4 = fetch("/", base4) if up4 else (None, "", b"")
        check("the server starts on it and serves the list"
              + ("" if up4 else "  <- " + b"".join(out4[-3:]).decode("utf-8", "replace")),
              up4 == 200 and home4[0] == 200 and b"Old Timer" in home4[2])
        con = sqlite3.connect(old_db)
        con.row_factory = sqlite3.Row
        cols = {r["name"] for r in con.execute("PRAGMA table_info(boards)")}
        fresh = sqlite3.connect(":memory:")
        fresh.executescript(S.SCHEMA)
        want = {r[1] for r in fresh.execute("PRAGMA table_info(boards)")}
        fresh.close()
        check("its table now has exactly the columns a new one has",
              cols == want and all(c in cols for c, _d in S.BADGE_COLUMNS))
        check("and the hourly record's table",
              con.execute("SELECT name FROM sqlite_master WHERE name='beathours'")
              .fetchone() is not None)
        r = con.execute("SELECT * FROM boards WHERE token=?", ("a" * 32,)).fetchone()
        check("the old row is untouched, and simply has no badge fields yet",
              r["name"] == "Old Timer" and r["beats"] == 5000
              and r["first_seen"] == now - 90 * 86400 and r["system"] == ""
              and r["guests"] is None and r["support"] == ""
              and r["tracked_since"] == 0)
        check("its busy hours survived", con.execute(
            "SELECT beats FROM activity WHERE board_id=1").fetchone()[0] == 30)
        con.close()
        check("its row shows the badges it earned without sending any: 1m",
              badges_in(badge_row(home4[2].decode("utf-8"), "Old Timer"))
              == [("soft", "unleashed"), ("age", "1m")])
        code4, _b = post_from({"name": "Old Timer", "port": 6400, "token": "a" * 32,
                               "software": "unleashed", "system": "ESP32-WROOM-32E",
                               "features": ["chat"]}, "192.0.2.44", base4)
        con = sqlite3.connect(old_db)
        con.row_factory = sqlite3.Row
        r = con.execute("SELECT * FROM boards WHERE token=?", ("a" * 32,)).fetchone()
        con.close()
        check("its next heartbeat keeps its listing and adds the new fields",
              code4 == 200 and r["system"] == "ESP32-WROOM-32E" and r["features"] == "chat"
              and r["beats"] == 5001 and r["tracked_since"] > 0)
        S.DB_PATH, was = old_db, S.DB_PATH
        try:
            S.setup()
            S.setup()
            again = True
        except Exception:
            again = False
        S.DB_PATH = was
        check("and starting again on the migrated database changes nothing", again)
    finally:
        server4.terminate()
        try:
            server4.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server4.kill()
        for leftover in (old_db, old_db + "-wal", old_db + "-shm"):
            try:
                os.remove(leftover)
            except OSError:
                pass


def main():
    db = os.path.join(tempfile.gettempdir(), f"dirtest{os.getpid()}.db")
    for leftover in (db, db + "-wal", db + "-shm"):
        if os.path.exists(leftover):
            os.remove(leftover)

    env = dict(os.environ,
               DIRECTORY_PAGE_CACHE="0",   # tests read the page straight after changing it

               DIRECTORY_DB=db,
               DIRECTORY_PORT=str(PORT),
               DIRECTORY_PENDING_HOURS="0.0006",     # about two seconds
               DIRECTORY_MIN_SECONDS="0",
               DIRECTORY_LIST_DOMAIN="boards.example",
               DIRECTORY_ABOUT_DOMAIN="about.example",
               DIRECTORY_DATA_DOMAIN="data.example")
    server = subprocess.Popen([sys.executable, "server.py"], env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    # Drain it. The server logs one blocking print per request from the
    # handler thread, so an undrained pipe fills after a few KB and every
    # thread then blocks inside log_message: the server stays alive and
    # stops answering, which looks exactly like a wedge under load. This
    # suite ran for months just under the buffer and started timing out the
    # moment a few more checks were added. The log is kept so a failure can
    # be explained afterwards.
    server_log = []
    threading.Thread(
        target=lambda: [server_log.append(line.decode("utf-8", "replace").rstrip())
                        for line in server.stdout],
        daemon=True).start()
    try:
        for _ in range(50):                          # wait for it to answer
            try:
                get("/health")
                break
            except Exception:
                time.sleep(0.1)

        # ------------------------------------------------------------------
        # Where a request came from.
        #
        # The server listens on loopback with a reverse proxy in front, so
        # the socket address is always the proxy's and the caller's real one
        # is in X-Forwarded-For. Three things key off that address: the
        # X-Seen-Address a board uses as a rough DDNS, the one-listing-per
        # address cap, and report dedupe. Believing the header from anybody
        # makes all three forgeable, and this server used to take the
        # LEFTMOST entry, which is the end a caller controls completely.
        #
        # client_ip is exercised directly as well as over HTTP, because the
        # untrusted-peer branch cannot be reached from loopback while
        # loopback is the thing being trusted.
        print("Where a request came from")
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import server as S
        loop = S.trusted_nets("127.0.0.1,::1")
        none_ = []
        cases = [
            ("the real caller, not the proxy",
             ("127.0.0.1", "203.0.113.7", "", loop), "203.0.113.7"),
            ("a forged entry ahead of the real one is ignored",
             ("127.0.0.1", "9.9.9.9, 203.0.113.7", "", loop), "203.0.113.7"),
            ("several forged entries, the rightmost still wins",
             ("127.0.0.1", "9.9.9.9, 8.8.8.8, 203.0.113.7", "", loop), "203.0.113.7"),
            ("a forged chain naming a trusted address is still ignored",
             ("127.0.0.1", "9.9.9.9, 127.0.0.1, 203.0.113.7", "", loop), "203.0.113.7"),
            ("our own proxies are stepped over to reach the caller",
             ("127.0.0.1", "203.0.113.7, 127.0.0.1", "", loop), "203.0.113.7"),
            ("an untrusted peer's header is not read at all",
             ("203.0.113.9", "9.9.9.9", "", loop), "203.0.113.9"),
            ("nor is its X-Real-IP",
             ("203.0.113.9", "", "9.9.9.9", loop), "203.0.113.9"),
            ("trusting nobody means the socket address, always",
             ("127.0.0.1", "203.0.113.7", "", none_), "127.0.0.1"),
            ("no header falls back to the socket",
             ("127.0.0.1", "", "", loop), "127.0.0.1"),
            ("junk in the header falls back rather than erroring",
             ("127.0.0.1", "not-an-address", "", loop), "127.0.0.1"),
            ("an entry carrying a port is still an address",
             ("127.0.0.1", "203.0.113.7:51234", "", loop), "203.0.113.7"),
            ("a bracketed IPv6 literal with a port",
             ("127.0.0.1", "[2001:db8::5]:443", "", loop), "2001:db8::5"),
            ("a bare IPv6 address",
             ("127.0.0.1", "2001:db8::5", "", loop), "2001:db8::5"),
            ("a v4-mapped v6 address becomes plain v4",
             ("127.0.0.1", "::ffff:203.0.113.7", "", loop), "203.0.113.7"),
            ("X-Real-IP is used when there is no chain",
             ("127.0.0.1", "", "203.0.113.7", loop), "203.0.113.7"),
        ]
        for label, args, want in cases:
            check(label, S.client_ip(*args) == want)
        check("an IPv6 caller is grouped by /64, not by address",
              S.group_of("2001:db8:1:2:3:4:5:6") == "2001:db8:1:2::/64"
              and S.group_of("2001:db8:1:2::9") == "2001:db8:1:2::/64"
              and S.group_of("2001:db8:1:3::9") != "2001:db8:1:2::/64")
        check("and a v4 caller by its own address",
              S.group_of("203.0.113.7") == "203.0.113.7")

        # Over HTTP now, against the running server, which trusts loopback.
        check("the forwarded address reaches X-Seen-Address",
              seen(headers={"X-Forwarded-For": "203.0.113.7"}) == "203.0.113.7")
        check("and a forged entry in front of it does not",
              seen(headers={"X-Forwarded-For": "9.9.9.9, 203.0.113.7"})
              == "203.0.113.7")
        check("a caller with nothing in front of it is its own address",
              seen() == "127.0.0.1")

        print("A board announces itself")
        board = {"software": "unleashed", "version": "0.13.0",
                 "name": "The Rusty Modem", "owner": "Sparks",
                 "description": "A BBS on a chip in a shack", "host": "",
                 "port": 6400, "nodes": 6, "busy": 2, "uptime": 900,
                 "interval": 10, "calls24": 11, "minutes24": 300, "token": ""}
        code, body, head = post(board)
        check("the first announce is accepted", code == 200)
        token = body.get("token", "")
        check("a token is issued", len(token) >= 16)
        check("the token also comes back as a header", head.get("X-Listing-Token") == token)
        check("it starts out pending", body["state"] == "pending")
        check("and says how long until it is public", body["public_in"] > 0)
        check("the board is told its own address", head.get("X-Seen-Address") == "127.0.0.1")

        print("It is not on the public list yet")
        _, page = get("/")
        check("pending boards are not listed", "Rusty Modem" not in page)

        print("A second board from the same address has to wait for a human")
        code, second, _ = post({"name": "Squatter", "owner": "Nobody",
                                "description": "should queue", "port": 6400})
        check("the second listing is queued, not published", second["state"] == "queued")
        check("and it gets its own token", second["token"] != token)

        print("After the pending window, with heartbeats kept up")
        time.sleep(2.5)
        board["token"] = token
        code, body, head = post(board)
        check("the listing goes public", body["state"] == "online")
        check("the countdown is done", body["public_in"] == 0)
        check("the same token is kept", body["token"] == token)
        check("the state is in the headers too", head.get("X-Listing-State") == "online")

        _, page = get("/")
        check("the board is on the page now", "Rusty Modem" in page)
        check("with its sysop", "Sparks" in page)
        check("and how to dial it", "6400" in page)
        # Spelled out rather than abbreviated: "caller-min/24h" was read
        # as calls per minute, which is a fair reading and a thousand
        # times the truth.
        check("self-reported activity is shown, in words",
              "connected" in page and "calls" in page)
        check("the queued one still is not", "Squatter" not in page)

        # The figures are a sentence under the heading now, not a run of
        # small numbers beside it. One board, reporting two callers on.
        print("The heading's figures")
        check("the heading is the heading, with nothing crammed beside it",
              "<h1>BBS directory</h1>" in page and "listed &middot;" not in page)
        check("and the figures are a sentence under it, counted from the list",
              '<h1>BBS directory</h1><p class="stat">Unleashed is hosting '
              "<span class='n'>1</span> board with <span class='n'>2</span> "
              "callers on right now.</p>" in page)
        check("in --live, the colour that means up",
              "p.stat .n { color:var(--live); }" in page)
        # Plurals, and the two zeros, straight from the function that
        # writes the sentence, since the running server has one board.
        def said(n, m):
            return re.sub(r"<[^>]+>", "", S.stat_line(n, m))
        check("no boards: said as such, with no callers clause to go wrong",
              said(0, 0) == "Unleashed is hosting no boards yet.")
        check("one board, one caller: both singular",
              said(1, 1) == "Unleashed is hosting 1 board with 1 caller on right now.")
        check("one board, nobody on: no callers, not 0 callers",
              said(1, 0) == "Unleashed is hosting 1 board with no callers on right now.")
        check("two boards, five callers: both plural",
              said(2, 5) == "Unleashed is hosting 2 boards with 5 callers on right now.")
        check("a big figure gets its thousands separator",
              said(1200, 3400) == "Unleashed is hosting 1,200 boards with 3,400 "
                                  "callers on right now.")
        # The directory knows nothing about where a board is, so nothing on
        # the page may say "across the globe" until something true can.
        check("the suffix is empty, and nothing claims the globe",
              S.STAT_SUFFIX == "" and "globe" not in page.lower())
        was_suffix = S.STAT_SUFFIX
        S.STAT_SUFFIX = " in three time zones"
        check("and a suffix, once set, goes before the full stop",
              said(2, 5).endswith("callers on right now in three time zones."))
        S.STAT_SUFFIX = was_suffix

        print("The JSON list")
        _, raw = get("/api/boards.json")
        listed = json.loads(raw)["boards"]
        check("one board in the JSON", len(listed) == 1)
        check("it carries no token", "token" not in listed[0])
        check("and no moderator notes", "note" not in listed[0])

        print("A stranger cannot take the listing over")
        code, other, _ = post({"name": "The Rusty Modem", "owner": "Impostor",
                               "description": "hijack attempt", "port": 6400,
                               "token": "0" * 32})
        check("an unknown token makes a new entry, it does not seize one",
              other["token"] != token and other["state"] in ("queued", "pending"))
        _, page = get("/")
        check("the real listing still says who owns it", "Sparks" in page)
        check("the impostor is not published", "Impostor" not in page)

        print("Rubbish is refused")
        code, body, _ = post({"name": "", "port": 6400})
        check("a board with no name is refused", code == 400)
        code, body, _ = post({"name": "Bad Port", "port": 99999})
        check("a silly port is refused", code == 400)

        print("One server, three faces")
        _, page = get("/", host="about.example")
        check("the about domain serves the argument", "Electronic freedom" in page)
        check("with the history on it", "CBBS" in page and "1978" in page)
        check("and points at the other two", "boards.example" in page and "data.example" in page)

        _, page = get("/", host="data.example")
        check("the data domain documents the API", "/api/boards.json" in page)
        check("and says what is not in it", "Nothing about callers" in page)

        _, page = get("/", host="boards.example")
        check("the list domain still lists boards", "Rusty Modem" in page)
        check("the list page owns the board-list heading",
              "Boards that are up right now" in page)

        # The board list's heading used to live in the shared page shell, so
        # it turned up above the manifesto as well. Every page brings its own.
        _, page = get("/", host="about.example")
        check("the about page does not inherit the list heading",
              "Boards that are up right now" not in page)
        _, page = get("/", host="data.example")
        check("nor does the data page",
              "Boards that are up right now" not in page)
        check("the data page has its own heading", "<h1>Data</h1>" in page)
        check("the manifesto has one at all",
              "<h1>What this is</h1>" in get("/", host="about.example")[1])

        # The faces are also paths, so one domain gets all three. There were
        # no path routes: with only a list domain configured, /about and
        # /data were 404, two of seven menu items looped back to the page you
        # were already on, and the manifesto could not be read at all.
        # README.md and INSTALL.md both said otherwise.
        print("The other two faces are reachable by path as well")
        code, page = get("/about", host="boards.example")
        check("the manifesto is reachable without its own domain",
              code == 200 and "A bulletin board is a machine" in page)
        code, page = get("/data", host="boards.example")
        check("and so is the data page", code == 200 and "Endpoints" in page)

        print("The manifesto says what the board actually does")
        _, page = get("/", host="about.example")
        check("ten callers and a hidden eleventh line, not six and a seventh",
              "answers ten at once" in page and "answers six at once" not in page)
        # Nothing on this site states an unbuilt feature as present fact, and
        # nothing calls a built one unbuilt. Somebody decides whether to spend
        # an afternoon and twenty dollars on the strength of these sentences,
        # which makes them the most expensive kind of wrong there is here.
        # Doors are not started, so they stay in the future tense.
        check("doors are named as coming, not as something the board has",
              "doors come after" in page.lower() and ", doors," not in page)
        check("and the features it does list are ones that exist",
              "mail between callers" in page and "file areas on an SD card" in page)
        # Forums shipped in firmware 0.21: FORUMS in COMMANDS.md, PF_SD in
        # forums.cpp, so a card and a sysop who switches them on. The site
        # said "being built" in five places after they were built, which is
        # the same mistake as the opposite one, pointed the other way.
        check("the manifesto lists forums as something the board has",
              "forums on the same card" in page)
        for path in ("/sdcard", "/build", "/kids"):
            _, page = get(path)
            art = page.split("<article>")[1]
            check(f"{path} does not call the forums unbuilt",
                  "being built" not in art and "once they are built" not in art
                  and "not on any board yet" not in art)
            check(f"{path} says forums need the card",
                  "forums" in art.lower() and ("card" in art.lower()))
        # Checked against the sources, 2026-09-22, and each of these was
        # wrong on the live site. Pinned so that a later copy pass cannot put
        # the old figure back.
        _, page = get("/", host="about.example")
        # Byte, November 1978, p.150, in Christensen and Suess's own words:
        # "an 8080 processor with 24 K bytes of memory". The page said 64,
        # and "eight times that memory" was built on it.
        check("CBBS had 24 KB, in the builders' own words, not 64",
              "24 kilobytes" in page and "64 kilobytes" not in page
              and "eight times that" not in page)
        # The firmware holds the radio awake (WIFI_PS_NONE), and Espressif's
        # datasheet puts receive alone at 112 mA. "A few tens of milliamps"
        # was the figure for a radio that dozes, which this one does not.
        every_page = [page] + [get(p)[1] for p in ("/build", "/whofor")]
        check("nothing says the board draws a few tens of milliamps",
              not any("few tens of milliamps" in p for p in every_page))
        # Sign-up requires a name and an email (UF_REQUIRED in users.cpp).
        # The freedom box said signing up was a handle and a password.
        flat_m = " ".join(page.split())
        check("the manifesto does not say sign-up needs no email address",
              "no email address" not in flat_m
              and "none of it is verified" in flat_m)
        # A stock C64 has been made to finish a TLS 1.3 handshake. It takes
        # about 36 minutes, which is the honest version of "cannot".
        check("and no page says a C64 cannot do TLS",
              "cannot do TLS" not in page
              and "never will" not in get("/privacy")[1])
        # Back to the manifesto: the loop above reassigned page, and the check
        # after this one reads it.
        _, page = get("/", host="about.example")
        check("a guest types a handle like everybody else",
              "A guest types a handle and nothing else" in page)

        print("The feed")
        code, feed = get("/feed.xml")
        check("there is an RSS feed", code == 200 and "<rss version=\"2.0\"" in feed)
        check("the board that went public is in it", "Rusty Modem" in feed)
        check("with a date and a stable id", "pubDate" in feed and "board-" in feed)
        check("the queued one is not", "Squatter" not in feed)
        check("the page tells readers where the feed is", "application/rss+xml" in page)

        print("The rest of the site")
        code, page = get("/rules")
        check("the house rules are there", code == 200 and "No hate" in page)
        # Both constants used to go to simple_page() bare, with no <article>
        # wrapper and no "here", so they took the browser's default heading
        # sizes and told the reader they were on Boards.
        check("the house rules are styled like every other prose page",
              "<article>" in page)
        check("and the menu does not claim they are the board list",
              '<a class="here" href="/">Boards</a>' not in page)
        code, page = get("/how")
        check("so is how to get listed", code == 200 and "announce" in page)
        check("get listed is styled like every other prose page",
              "<article>" in page)
        check("and the menu knows which page it is on",
              '<a class="here" href="/how">' in page)
        # HOW is a raw string now: a backslash at the end of a line in an
        # ordinary one is a Python line continuation, so the curl example was
        # served as one long line with its continuations eaten and the
        # following lines still indented as though they were there.
        check("the curl example keeps its line continuations",
              "announce \\\n" in page)

        print("Every page says which page it is")
        code, page = get("/build")
        check("a markdown page takes its title from its own first heading",
              "<title>Build one - " in page)
        code, page = get("/forward-mesh")
        check("so the router pages are not four identical tabs",
              "<title>Port forwarding on eero and Google Nest Wifi - " in page)
        check("and a page with no menu entry lights its own section",
              '<a class="here" href="/forward">' in page)
        code, page = get("/dialing")
        check("dialing belongs to terminals",
              '<a class="here" href="/terminals">' in page)
        code, page = get("/sdcard")
        check("and the SD card page to build one",
              '<a class="here" href="/build">' in page)
        check("a page carries a description and a preview card",
              'name="description"' in page and 'property="og:title"' in page)
        code, page = get("/favicon.svg")
        check("there is an icon, and it is the micro sign",
              code == 200 and "<svg" in page)

        # The site covered finding a board, installing a terminal, building
        # one and listing one, and said nothing about the thirty seconds
        # after a stranger connects: a handle prompt, and no idea whether to
        # register, whether it costs anything, or what a guest is.
        print("What happens after you connect, and what it risks")
        code, page = get("/firstcall")
        check("the first call page exists",
              code == 200 and "A handle is the name other callers see" in page)
        check("and says what a guest actually gets",
              "fifteen minutes" in page)
        code, page = get("/privacy")
        check("the privacy page leads with the radio framing, not a shrug",
              code == 200 and "in the clear" in page and "bar" in page)
        check("and the manifesto points at it",
              "/privacy" in get("/", host="about.example")[1])
        check("so does the terminal page's telnet warning",
              "/privacy" in get("/terminals")[1])
        _, page = get("/", host="about.example")
        check("the limits are explained rather than named",
              "Open communication over the internet is radio" in page
              and "Somebody has to be trying" in page)

        # ------------------------------------------------------------------
        # Freedoms gained. Two columns, and the one claim in it that could
        # do harm if it drifted.
        #
        # The section is the project's position rather than its feature
        # list, and it reaches for words like discreet and hidden. Those are
        # true of the object and false of the wire: the privacy page spends
        # a screen saying anybody on the path can read plain telnet, and a
        # box here implying otherwise would contradict it in the one place
        # somebody is being talked into trusting the thing. So the honest
        # sentence is pinned present, and the dishonest ones are pinned
        # absent by name.
        print("Freedoms gained")
        # Prose wraps in the source, so a sentence that reads as one line on
        # the page is two in the file. These checks are about the words, not
        # about where somebody happened to press return.
        flat = " ".join(page.split())
        check("the freedom boxes are wrapped so they can be laid out",
              '<div class="freedoms">' in page
              and page.count('<div class="freedom">') == 12)
        check("the discreet claim is about the object, and says so",
              "discretion of the object and not of the wire" in flat
              and "telnet is plain text" in flat
              and 'the <a href="/privacy">privacy page</a>' in flat)
        # Not a style opinion. Each of these would tell a reader the wire
        # hides them, which is the one thing this section must never say.
        for wrong in ("undetectable", "untraceable", "invisible on the network",
                      "nobody can see", "nobody can read", "cannot be traced",
                      "impossible to intercept", "off the radar"):
            check("and nothing in the manifesto claims %r" % wrong,
                  wrong not in page.lower())
        # Rob's "use it anywhere" is the no-uplink claim, it is true, and it
        # is the reason the section is shaped the way it is.
        check("it makes the claim that is actually true: no internet needed",
              "It works with no internet at all" in flat
              and "a switch in a room with no uplink" in flat)
        # Mail stopped being deleted on sight in 0.17.12: reading it offers
        # reply, save or delete and touches nothing until a key answers. The
        # manifesto said mail was "gone the moment it is read" in three
        # places, which was true of an older board and is now a promise the
        # software does not keep.
        check("and describes mail the way the board actually handles it",
              "gone the moment it is read" not in flat
              and "gone once it has been read" not in flat
              and "gone when it is read" not in flat
              and "reply to it or delete it" in flat)

        # /dialing fixes the exact problem a first-time visitor hits, and
        # used to be reachable from one sentence at the bottom of /terminals
        # and a title= attribute, which is invisible on every touch device.
        print("Who would actually want one of these")
        code, page = get("/whofor")
        check("the who-it's-for page exists and answers plainly",
              code == 200 and page.index("Everyone.") < page.index("Schools"))
        for who in ("Schools", "Ham radio", "Offices and teams",
                    "One person, one board"):
            check(f"it covers {who.lower()}", f">{who}</h" in page
                  or f">{who}</h3>" in page or who in page)
        check("it says the board is nobody else's to police",
              "king of everything on the board" in page)
        check("and names the things that make that true",
              "deplatform" in page and "decentralized" in page
              and "off grid" in page)
        # Boards do not talk to each other. Linking is queued and unbuilt, so
        # "peer to peer" was the wrong word for what the sentence after it
        # actually describes, which is that nobody needs a network at all.
        check("without calling independent boards peer to peer",
              "peer to peer" not in page)
        # The caller log records when a call started and how long it ran, and
        # the board enforces a daily minute limit, so a claim that nothing
        # measures how long you were on contradicted /firstcall, which names
        # the log plainly.
        check("and without claiming nothing records how long you were on",
              "how long for" not in page and "caller log, and the board is yours" in page)
        check("it ends by telling somebody how to start",
              'href="/build"' in page)
        check("it is in the menu next to the manifesto",
              ">Who it's for</a>" in page)
        _, page = get("/", host="about.example")
        check("and the manifesto points at it",
              'href="/whofor"' in page)

        # ------------------------------------------------------------------
        # The two pages hanging off /whofor. Neither is in the menu: nine
        # items is already at the edge of what a phone header can carry, and
        # neither is what a general visitor is hunting for. Off the menu is
        # not the same as buried, so these check they are prominent where
        # they belong instead.
        print("The pages for children and for teachers")
        _, page = get("/whofor")
        head = page.split("<article>")[1][:900]
        check("the invitation for children is the first thing on the page",
              'class="tip"' in head and '"/kids"' in head)
        # Not a warning, and not a footnote either. It is the full width box
        # with the marker at its right edge, which is the whole point of it:
        # the one link on this site written for a twelve year old used to be
        # a 78ch note indented 30px and it read as an aside.
        #
        # The marker is checked for what it is not as much as for what it
        # is. A warning triangle on the friendliest box on the site would
        # say "be careful here" at the exact moment it means "this way in".
        check("and it is an invitation, not a warning",
              'class="warn"' not in head and "⚠" not in page)
        tip = page.split("article .tip {")[1][:300]
        check("the invitation is the full width of the column, not an aside",
              "max-width:none" in tip and "border-radius:" in tip
              and "margin-left" not in tip)
        check("and carries its marker at the right edge",
              'article .tip::after { content:"-->"' in page
              and "position:absolute" in page.split("article .tip::after {")[1][:200])
        # A pointer that does nothing is worse than no pointer: it costs a
        # reader a click to learn it is decoration, and on a phone it is the
        # first thing they tap. The whole box is one link now, via a
        # stretched ::after on the single anchor the box already had, so
        # there is still one destination and one accessible name.
        #
        # pointer-events on the marker is the load-bearing line and it is
        # the one somebody would delete as noise. The marker is painted
        # last, so without it the marker sits on top of the overlay and
        # swallows the click on the one spot this whole change is about.
        #
        # Verified in Chrome rather than inferred: elementFromPoint at the
        # marker's computed centre resolves to the /kids anchor at 1920,
        # 1366 and 390, the box is live at 2159 of 2160 sampled points, and
        # a real click dispatched at that pixel put a GET /kids in the
        # server log where merely loading the page put none.
        tipcss = page.split("article .tip a::after {")[1][:200]
        check("the whole box is the link, not just the six words in it",
              'content:""' in tipcss and "position:absolute" in tipcss
              and "inset:0" in tipcss)
        check("and the marker lets the click through to it",
              "pointer-events:none"
              in page.split('article .tip::after { content:"-->"')[1][:260])
        check("the box answers a mouse and a keyboard, not just a mouse",
              "article .tip:hover {" in page
              and "article .tip a:focus-visible::after { outline:" in page)
        # Warm, and deliberately not red: red is the grammar of an error
        # box. Rob asked for yellow and orange after seeing it in the site's
        # cyan, which is the structural colour and made it read as
        # furniture. Ratios against the box background, measured: lead
        # 11.4:1, body 12.2:1, link and marker 8.7:1, frame 6.1:1.
        check("and it is warm, which is what makes it read as an invitation",
              "article .tip { color:#f2ddb8; background:#2e1c05;" in page
              and "var(--dial)" not in tip)
        # ------------------------------------------------------------------
        # The kids page, which is cards rather than prose for a reason that
        # is not length. The retro terminal look signals nothing to a ten
        # year old: everywhere else on this site it is doing real work
        # because the audience recognises it, and on that one page it asks a
        # reader to decode an unfamiliar visual language before they have
        # been given a reason to care.
        print("The kids page is cards, and every card stands on its own")
        _, kids = get("/kids")
        check("it is cards, with the headline idea in its own hero",
              '<div class="cards hero">' in kids
              and kids.count('<section class="card">') > 8)
        check("none of the card markers leak onto the page",
              "!!" not in kids.split("<article>")[1]
              and "??" not in kids.split("<article>")[1]
              and ":::" not in kids.split("<article>")[1])
        # <details> is real interactivity for no script at all, and "what is
        # in this one" is most of the appeal at this age. Measured in
        # Chrome: opening one grows the card by 30 to 60px.
        check("and there is something to open, with no script to do it",
              "<details><summary>" in kids and "<script" not in kids)
        # The grid is auto-fit, so the columns come from the width. No
        # order: anywhere, because source order is what a screen reader
        # follows and what somebody tabbing gets. Measured: 3 columns at
        # 1920, 2 at 1366, 1 at 390 and 1 at 200% text, no overflow at any
        # of them.
        check("the cards reflow by width, not by reordering them",
              "grid-template-columns:repeat(auto-fit, minmax(min(21rem, 100%), 1fr))"
              in kids and "article .card" in kids
              and "; order:" not in kids and "{order:" not in kids)
        # Blocky rather than soft, which is the frame this reader already
        # owns, and it costs nothing and no image weight. It has to read as
        # deliberate before any artwork exists, because today none does.
        check("and they are blocky, which is the whole point of the look",
              "article .card { background:#12121a; border:3px solid" in kids
              and "image-rendering:pixelated" in kids)
        # The art slots render NOTHING until a file is there. Not a broken
        # image, not a reserved gap, not alt text standing in for a picture
        # nobody drew. So this passes with the folder empty, which is how it
        # ships today.
        check("an art slot with no file behind it draws nothing at all",
              'img class="pix"' not in kids or "/pix/" in kids)
        # Forums shipped in firmware 0.21, and they need a card and a sysop
        # who switches them on. The page has to say both halves: present,
        # and not on every board, because a reader who calls a board without
        # them should blame the board's setup rather than the software.
        check("forums are described as present, and as not on every board",
              "now forums" in kids.lower()
              and "not every board has them" in kids.lower())
        # The honest privacy line. This is the one claim on this site with
        # the potential to actually harm somebody, so it is pinned: the safe
        # room is the board they host, and a board on the internet is not a
        # private one. It must not drift into "chat is your safe space".
        check("and the page never calls a stranger's chat room private",
              "safe space" not in kids.lower()
              and "nothing you type is private" in kids.lower()
              and '"/privacy"' in kids and '"/forward"' in kids)
        check("the teachers page is linked from the schools section",
              '"/teachers"' in page)
        # The menu, not the body: the first version of this check looked for
        # the link text anywhere on the page and tripped over the perfectly
        # good link to /teachers in the schools section.
        nav = page.split("<nav>")[1].split("</nav>")[0]
        check("neither is in the menu",
              "/kids" not in nav and "/teachers" not in nav)
        for path in ("/kids", "/teachers"):
            _, p2 = get(path)
            check(f"{path} lights the section it belongs to",
                  '<a class="here" href="/whofor">' in p2)
            check(f"{path} does not reintroduce unbuilt features",
                  "message base" not in p2.lower()
                  and "doors" not in p2.split("<article>")[1].lower())

        _, page = get("/kids")
        check("the children's page never asks for anything",
              "<form" not in page and "<input" not in page
              and "email" not in page.split("<article>")[1].lower())
        check("it says plainly that nothing typed is private",
              "Nothing you type is private" in page
              and "plain text" in page)
        check("it names what never to type into a board",
              "Your real name" in page and "Your school" in page
              and "Your phone number" in page)
        check("it says the adult decides about the internet, not the child",
              "That decision belongs to the adult" in page)
        check("and that a board that never goes online is finished work",
              "It is not practice for" in page)
        check("it does not promise the board is safe",
              " is safe" not in page.split("<article>")[1])
        # Measured, not asserted. Flesch-Kincaid on the rendered prose: the
        # brief was a sixth grade reading level, and the point of keeping the
        # check is that an edit six months from now cannot quietly push it to
        # eleventh without anybody noticing.
        grade = fk_grade(page)
        check(f"it reads at grade {grade:.1f}, at or below sixth",
              grade is not None and grade <= 6.5)

        _, page = get("/teachers")
        check("the lesson plans say how long they take",
              page.count("50 minutes") >= 3 or page.count("minutes") >= 5)
        check("and what each one needs",
              page.count("Needs:") >= 5)
        check("the making is treated as part of the project",
              "TinkerCAD" in page and "enclosure" in page.lower())
        check("it names what it teaches, concretely",
              "Client and server" in page and "port 6400" in page
              and "FAT32" in page and "CP437" in page)
        check("and it is straight about school networks",
              "will not be able to forward a port" in page)
        # A board answers ten callers. The page used to say one board serves a
        # whole class, which is wrong for any class over ten and fails in
        # front of one, in session 1, where everybody connects at once. The
        # figure is BBS_MAX_NODES in the firmware and is not a config key.
        check("and honest about how many callers fit on one board",
              "answers ten callers at once" in " ".join(page.split())
              and "serves a whole class" not in page)

        # ------------------------------------------------------------------
        # The project's own vocabulary, used the same way on every page. Two
        # words have moved and one is a trademark the site had spelled four
        # ways.
        print("The site says the same thing in the same words")
        every = {}
        for path in ("/", "/about", "/data", "/rules", "/how", "/build",
                     "/install", "/sdcard", "/terminals", "/dialing",
                     "/firstcall", "/privacy", "/whofor", "/kids",
                     "/teachers", "/forward", "/forward-netgear",
                     "/forward-tplink", "/forward-asus", "/forward-xfinity",
                     "/forward-mesh", "/badges"):
            every[path] = get(path)[1]
        # Forums, not message bases. The feature is the same one; the name
        # changed, and a reader meeting both words assumes they are two
        # things and goes looking for the one that does not exist.
        hits = [p for p, h in every.items() if "message base" in h.lower()]
        if hits:
            print("     message bases still named on:", ", ".join(hits))
        check("forums are called forums, never message bases", not hits)
        # Wi-Fi is the Alliance's own spelling and the one this site uses in
        # prose. "Wifi" and "WiFi" survive only as product names and as
        # labels a reader will see on their own screen: Google Wifi, Nest
        # Wifi, and Xfinity's WiFi menu. A bare lowercase one is ours, and
        # the site had four spellings of it.
        hits = [p for p, h in every.items()
                if re.search(r"(?<![\w-])wifi\b", re.sub(r"<[^>]+>", " ", h))]
        if hits:
            print("     lowercase wifi on:", ", ".join(hits))
        check("and Wi-Fi is spelled one way in prose", not hits)

        # Rob's callsign is not on the site. The examples use a plain
        # illustrative handle instead.
        for path, host in (("/how", None), ("/", "boards.example")):
            _, page = get(path, host=host)
            check(f"no callsign on {path}", "KE9CXN" not in page)

        _, page = get("/")
        check("the front page offers a way out when a dial link does nothing",
              'href="/dialing">Nothing happened?' in page)
        check("and the footer carries it on every page",
              '>Dial links</a>' in page)
        check("the dial link's tooltip no longer reads a URL out as text",
              "See /dialing" not in page)

        # Pages are files in pages/, routed by name. That lookup runs last
        # on purpose: put it earlier and it swallows real endpoints, which
        # is exactly what happened to /health the first time.
        for name in ("build", "forward", "terminals", "dialing", "sdcard",
                     "firstcall", "privacy", "whofor", "kids", "teachers",
                     "forward-netgear", "forward-tplink", "forward-asus",
                     "forward-xfinity", "forward-mesh"):
            code, page = get("/" + name)
            check(f"/{name} renders", code == 200 and "<article>" in page)
        # A numbered step is a step. md_render only knew "- " bullets, so the
        # 53 numbered steps across the four router pages all fell through to
        # the paragraph branch and were joined into a wall of text. Every word
        # was present and in the right order, which is exactly what a grep
        # checks and exactly why nothing caught it.
        code, page = get("/forward-mesh")
        check("numbered steps are a list, not a run-on paragraph",
              "<ol>" in page and "<li>Tap <b>Advanced networking</b>.</li>" in page)
        check("and no step number survives as text", ">1. Open the eero" not in page)
        code, page = get("/forward-netgear")
        # Indented sub-bullets are not in the dialect and are staying out: the
        # five field labels under step 4 are a table now, which is.
        check("the netgear form is a table, not a mangled sub-list",
              "<ol>" in page and "Fill the form in" in page
              and "<td>Service Name</td>" in page)
        code, page = get("/forward")
        check("the forwarding index warns before it instructs",
              'class="warn"' in page and "responsible" in page)
        check("and names the two things that silently stop it working",
              "Double NAT" in page and "CGNAT" in page)
        code, page = get("/sdcard")
        check("the SD page gives the pin map", "<table>" in page and "GPIO5" in page)
        # A blockquote is one warning, not one per line. Each line used to be
        # closed into its own box, so a three line warning rendered as three
        # stacked boxes: border, background and padding repeated, reading as
        # three unrelated alarms. Every warning on the router pages looked
        # like that, and nothing caught it because the text was all present.
        body = page.split("<article>")[1].split("</article>")[0]
        check("a multi-line warning is one box, not one per line",
              body.count('class="warn"') == 2)
        check("and it holds the whole quote",
              "exFAT" in body and "diskpart" in body and
              body.index("exFAT") < body.index("diskpart") <
              body.index("Use the 3V3 pin"))
        # The power advice was "3V3 works on every module worth buying", and
        # the common blue module with an AMS1117 regulator is specified for
        # 4.5 to 5.5 V: on 3V3 its card can sit near 2.2 V. 3V3 is still the
        # starting point, because it cannot damage either kind of module.
        # Measured against the table's own SCK row. The wiring diagram above
        # the table carries a GPIO18 label too, so "the first GPIO18 on the
        # page" stopped meaning the table the day the drawing went in.
        check("and says where to start the power before the wiring table",
              0 <= page.find("Start on 3V3") < page.index("<td><code>SCK</code>"))
        check("without claiming 3V3 suits every module",
              "every module worth buying" not in page and "AMS1117" in page)
        # Espressif's datasheet: GPIO5 is a strapping pin for SDIO slave
        # timing only. Boot mode is GPIO0 and GPIO2.
        check("and without claiming GPIO5 can stop the board booting",
              "does not stop the board booting" in " ".join(page.split())
              and "can stop the board booting" not in " ".join(page.split()))
        # The messages are the firmware's own, from platform_esp32.cpp.
        check("and quotes the card errors the board actually prints",
              "card answered then failed" in page
              and "card would not mount" not in page)
        # diskpart refuses FAT32 over 32 GB; Microsoft lifted the limit for
        # the format command in KB5083631, April 2026, and nothing else.
        check("and does not send Windows users to diskpart for a big card",
              "use `diskpart`" not in page and "refuses it as well" in page)
        code, page = get("/build")
        check("and build links to it", 'href="/sdcard"' in page)

        code, page = get("/terminals")
        check("the terminal page renders its tables",
              "<table>" in page and "SyncTERM" in page)
        check("and the menu carries it on every page",
              ">Terminals</a>" in page)
        code, page = get("/dialing")
        check("the dialing page leads with the fix, not the registry",
              page.index("SyncTERM") < page.index("Registry"))
        check("and warns before any registry editing",
              'class="warn"' in page and "break unrelated associations" in page)
        # Two of its sources are Microsoft URLs ending "(v=vs.85)" and
        # "(v=ws.10)". The link pattern stopped at the first ")", so both
        # hrefs lost their closing parenthesis and 404'd, and the ")" was
        # printed after the link text. Nobody saw it because every word was
        # there.
        check("a link whose URL carries parentheses keeps them",
              'aa767914(v=vs.85)"' in page and 'cc771275(v=ws.10)"' in page
              and "</a>)" not in page)
        code, _ = get("/nosuchpage")
        check("an unknown page is not a page", code == 404)
        code, body = get("/health")
        check("the health endpoint still answers", code == 200 and "ok" in body)

        print("Busy hours")
        # The chart is built from the caller counts a board already
        # publishes, so it needs no new data from anybody and knows nothing
        # about any individual caller. Seeded directly here because the real
        # thing takes a day of heartbeats to say anything.
        import sqlite3
        con = sqlite3.connect(db)
        bid = con.execute("SELECT id FROM boards ORDER BY id LIMIT 1").fetchone()[0]
        for h in range(24):
            busy = {19: 3, 20: 6, 21: 8, 22: 5, 23: 2}.get(h, 0)
            con.execute("INSERT OR REPLACE INTO activity(board_id,hour,beats,busy)"
                        " VALUES(?,?,?,?)", (bid, h, 42, busy * 42))
        con.commit()
        con.close()
        _, page = get("/", host="boards.example")
        check("a board with a day of beats gets a busy-hours chart",
              "class='spark'" in page or 'class="spark"' in page)
        check("and is described by when it is actually busy",
              "busiest 20:00-22:00" in page)
        check("the chart expands without any javascript",
              "<details" in page and "<script" not in page)
        check("and says it is a control before you have clicked it",
              '(click for the day)' in page and '(click to close)' in page)

        # ------------------------------------------------------------------
        # Layout. These pin the rules, which is not the same as proving the
        # page looks right: a CSS assertion only says the string was
        # delivered. The rendering was measured in headless Chrome at 390,
        # 1366 and 1920, and the numbers are in the changelog. What these
        # catch is the failure that has actually happened here, which is a
        # stylesheet edit being dropped by a later rewrite and shipping
        # unstyled with every grep still passing.
        print("The layout rules reach the page")
        _, page = get("/", host="boards.example")
        check("the board list stops being a table on a phone",
              "@media (max-width: 900px)" in page
              and "main > table, main > table > tbody" in page)
        check("and has a column budget on a screen",
              "@media (min-width: 901px)" in page
              and "table-layout:fixed" in page)
        check("the cells carry their own labels, not the column order",
              "data-label='State'" in page and "data-label='Dial'" in page)
        check("activity is two deliberate lines, not one that wraps anywhere",
              "calls<br>" in page and "connected</span>" in page)
        # Three columns, not six. Six of them wrapped once the type grew, and
        # four of those columns were one short value each. What has to
        # survive is the one thing a table is for: State is the first line
        # of its own cell and cells are top aligned, so it still runs
        # straight down the page for somebody scanning for a board with
        # callers on it. Measured in Chrome at 1920 and 1366: all four state
        # lines start at the same x and each is one line.
        check("the board list is three columns, not six",
              "<th>Board</th><th>Dial</th><th>State</th></tr>" in page
              and "<th>Sysop</th>" not in page)
        check("and a stacked value says what it is rather than relying on "
              "its position",
              "<span class='lbl'>sysop</span>" in page
              and "<span class='lbl'>up for</span>" in page)
        check("the state is the first line of its cell, and the loud one",
              "<td class='status' data-label='State'><span class='state "
              in page
              and ".status > .act, .status > .muted, .status > .upfor"
              in page)
        # Direct children. ".status span" also matched the spans nested
        # inside, which put the freshness figure on its own line and split
        # every label from its value. It renders wrong and greps right.
        check("and the stacked lines are direct children only",
              ".status > span, .name > .owner { display:block; }" in page
              and ".status span," not in page)
        check("the page title outranks the text under it",
              "h1 {{ color:var(--ink); font-size:1.25rem".replace("{{", "{")
              in page
              and "article h2 {{ color:var(--struct); font-size:0.9375rem"
                  .replace("{{", "{") in page)
        check("nothing that is words is left below --dim",
              "footer {{ margin-top:1.75rem; color:var(--dim)"
              .replace("{{", "{") in page)
        _, page = get("/sdcard")
        check("a callout is indented from the body text, not flush with it",
              "margin:1.125rem 0 1.125rem 1.875rem" in page)
        # Prose runs the full width of the column on a desktop. This was
        # briefly capped at 78ch on typographic grounds and Rob reversed it
        # after comparing the two, so the check is that the cap is GONE, not
        # that it is some other number. The phone card layout above is a
        # separate thing and stays: wide on a monitor, cards on a phone.
        check("prose runs the full width of the column, with no reading cap",
              "article p, article li, article dd { max-width:none;" in page
              and "main p, main li, main dd" not in page
              and "article pre { max-width" not in page)
        # The boxes keep their own measures, which is where the width the
        # reading cap was after is actually spent. Those were deliberate and
        # are not what Rob reversed.
        check("but the callout, the pull quote and the freedom boxes do not",
              "max-width:78ch" in page and "max-width:70ch" in page
              and "max-width:66ch" in page)
        # Two columns for the freedoms, one below the site's breakpoint.
        # Measured in headless Chrome through exactly sized iframes, because
        # a grid that has not been rendered is a string in a stylesheet: at
        # 1920 two tracks of 682.3px and 61 characters to a line, at 1366 two
        # of 625.8px and 55 characters, at 390 one track of 318.7px and 30
        # characters, which is what every other box on the site gets there.
        # No horizontal overflow at any of the three.
        check("the freedoms are two columns where there is width for two",
              "article .freedoms { display:grid; "
              "grid-template-columns:repeat(2, minmax(0, 1fr));" in page)
        check("and one column below the breakpoint",
              "@media (max-width: 900px) {\n  article .freedoms "
              "{ grid-template-columns:1fr; }" in page)
        # Row major and nothing reordered, so the order down the source is
        # the order across the page. A screen reader follows the source, and
        # these are twelve related claims: a list read in a different order
        # to the one on the screen is a different list.
        check("and nothing reorders them away from their source order",
              "order:" not in page[page.index("article .freedoms {"):
                                   page.index("article .freedoms {") + 400])
        # ------------------------------------------------------------------
        # The manifesto's two diagrams. Both were ASCII art in a <pre>, which
        # is laid out in character cells, so its size was a font size: 61
        # columns in a 358px phone column meant 6px letters, and the animated
        # one was eight whole copies of itself flipped 0.4s apart. They are
        # inline SVG now.
        #
        # Verified by rendering as well as by this: at 1920, 1366 and a real
        # 390 through an exactly sized viewport, no text or shape escapes its
        # viewBox, the page never scrolls sideways, the smallest label is
        # 10.0px at 390 and 16.4px at 1920, and the marker moves 545 to 799
        # across two and a half seconds and does not move at all under
        # reduced motion.
        print("The manifesto's diagrams are drawn, not typed")
        _, page = get("/", host="about.example")
        check("both are inline SVG and no ASCII art is left on the page",
              '<svg class="wire"' in page
              and '<svg class="trace bad"' in page
              and '<svg class="trace good"' in page
              and "[ YOU ]" not in page and 'pre class="chart"' not in page)
        # A viewBox with a negative origin is one number per drawing instead
        # of shifting forty coordinates, and it is what holds the outermost
        # label off the frame. Without it the title sat 6px from the border.
        check("and each viewBox leaves a margin, so nothing sits on the frame",
              'viewBox="-5 -6 354 138"' in page
              and 'viewBox="-6 -8 356 382"' in page
              and 'viewBox="-6 -8 356 216"' in page)
        # 344 units of art inside a 353px phone column is 1:1. Anything wider
        # reads on a monitor and not on a phone, which is what the ASCII
        # versions were; the max-width then stops the same art being blown up
        # to twice size on a 1920 monitor.
        check("they are sized for the phone column and capped on a monitor",
              "svg.wire { display:block; width:100%; max-width:28rem;" in page
              and "svg.trace { display:block; width:100%; max-width:26rem;"
                  in page)
        # The comparison is two panels rather than one drawing, because a
        # viewBox scales and does not lay out again: a single SVG could not
        # stack on a phone. align-items:start is the argument itself, since
        # the left panel is tall because four parties keep a record and the
        # right one is short because one does.
        check("the comparison is two panels that stack at the one breakpoint",
              "grid-template-columns:repeat(2, minmax(0, 26rem))" in page
              and "align-items:start" in page
              and "@media (max-width: 900px) { .compare "
                  "{ grid-template-columns:1fr; } }" in page)
        # Still no JavaScript, and the animation survived the translation.
        check("the connection still animates, and with no script to do it",
              "@keyframes wiretrip" in page
              and "animation:wiretrip 3.2s ease-in-out infinite alternate"
                  in page
              and "<script" not in page)
        # The resting state is not the absence of the diagram: it is what a
        # screenshot, a printout and a reader with motion sensitivity all
        # get, so the marker parks half way along the wire rather than at
        # either end, and the lamp and the caret are lit rather than hidden.
        rm = page[page.index("@media (prefers-reduced-motion: reduce) {\n"
                             "  svg.wire"):][:340]
        check("and it rests half way along the wire when motion is refused",
              "animation:none" in rm and "transform:translateX(82px)" in rm
              and "opacity:1" in rm)
        # Red for a party that keeps a copy of you, green for one that does
        # not. Both come from the palette at the root: the red used to be a
        # literal in the diagram's own stylesheet, which is how a colour
        # carrying an argument drifts away from the site making it.
        check("the red and the green both come from the root palette",
              "--risk:#e06c6c;" in page
              and "svg.trace.bad .keep, svg.trace.bad .pool-box "
                  "{ stroke:var(--risk); }" in page
              and "svg.trace.good .keep { stroke:var(--live); }" in page)
        check("and no diagram colour is typed in as a literal",
              "#e06c6c" not in page.split("--risk:#e06c6c;")[1]
              and "#6ee36e" not in page)
        # An SVG shape with no fill declared is black, and black on #0d0d12
        # is a shape nobody can see. The lines say so explicitly rather than
        # relying on nobody noticing they are closed paths.
        check("every drawn shape declares a fill, including the lines",
              "svg.trace .link { fill:none; stroke:var(--faint);" in page
              and "svg.trace .bus { fill:none;" in page
              and "svg.wire .line { fill:none;" in page
              and "svg.wire .case { fill:none;" in page)
        # role="img" makes the whole drawing one object, so the labels inside
        # it are never announced and the label has to carry the argument. The
        # point of the pair is a list of parties who keep a record against a
        # list of one, so that is what it has to say.
        for want in ('Four of them keep a record',
                     'One record is kept, a text file you can open and read',
                     'there is no third party on the line'):
            check("the drawing says in words what it says in shapes"
                  f"  <- {want[:34]}", want in page)
        check("and each one is announced as a picture, not as decoration",
              page.count('role="img"') >= 3
              and page.count('aria-label="Calling a ') == 2)
        # The day chart's viewBox is sized to the column it lives in. A 720
        # unit box in a 412px cell scaled by 0.57, so an 11px label rendered
        # at 6.3px and the expanded chart was 110px tall.
        _, page = get("/", host="boards.example")
        check("the day chart is drawn at the size of the column it sits in",
              'viewBox="0 0 380 300"' in page)
        check("and its hour labels are set large enough to read",
              "svg.hours text { fill:var(--dim); font-family:inherit; "
              "font-size:13px; }" in page)

        # ------------------------------------------------------------------
        # The sitewide scale. Rob set his browser to 133% and said the board
        # list looked right at that size, so the site is drawn at 133% and
        # the whole page scales, not only the type. Raising the type alone
        # would have grown the words inside a column that did not move and
        # cost a quarter of the characters per line, which is a different
        # change and a worse one.
        #
        # That only holds while every length carrying layout is in rem. One
        # padding added later in px is a piece of the page that stops
        # scaling, and it is invisible until somebody looks at the render.
        # So: find every px left in the stylesheet and insist each one is a
        # border, an outline or text inside an SVG viewBox.
        #
        # Verified in headless Chrome rather than trusted: the old page at a
        # 1444px viewport times 1.33 and the new page at 1920 agree to the
        # decimal on body type (18.62px), column width (1436.4px) and
        # characters per line (140).
        print("The page is drawn at 133%, and all of it scales")
        # Its own name, not "page": the manifesto is the one page carrying
        # both stylesheets, and the checks after this one are still reading
        # the board list. Reusing "page" here quietly moved them onto a page
        # that has no day chart on it at all.
        _, css_page = get("/", host="about.example")
        check("the scale is one number at the root",
              ":root { color-scheme: dark; font-size:133%;" in css_page
              and "@media (max-width: 900px) { :root { font-size:115%; } }"
                  in css_page)
        stray = []
        for block in re.findall(r"<style>(.*?)</style>", css_page, re.S):
            block = re.sub(r"/\*.*?\*/", "", block, flags=re.S)
            for line in block.split("\n"):
                if "px" not in line:
                    continue
                # A media query condition is a viewport width and belongs in
                # px. Borders and rules stay in px too, because a hairline is
                # a hairline at any size.
                #
                # So does anything inside an SVG viewBox: a `px` there is a
                # user unit, not a layout length, and it scales with the
                # drawing already. That covers the day chart's labels, the
                # type in the two manifesto diagrams, and the translate that
                # moves the marker along the wire, which is 164 units of
                # viewBox and not 164 pixels of page. translateY is the same
                # thing on the other axis: the grain falling in the hourglass
                # and the lens going down the listing among the freedoms'
                # drawings, a few units of a 56 unit viewBox each.
                if (line.lstrip().startswith("@media")
                        or "svg.hours text" in line
                        or "svg.wire" in line
                        or "svg.trace" in line
                        or "translateX" in line
                        or "translateY" in line
                        or "outline-offset" in line):
                    continue
                rest = re.sub(r"\d+(?:\.\d+)?px\s+(?:solid|dotted|dashed)",
                              "", line)
                # The floor of a fit-to-viewport clamp is the one length
                # that must NOT scale. The maximum and the gutter should,
                # and do; the minimum exists to stop the art becoming
                # invisible, and in rem it grows with the root font until it
                # is wider than the viewport it was meant to fit inside. At
                # 390px with the browser text at 200% that was a 437px
                # wordmark in a 390px page, and the page scrolled sideways.
                rest = re.sub(r"clamp\(\s*\d+(?:\.\d+)?px\s*,", "clamp(", rest)
                if re.search(r"(?<![\w.-])\d+(?:\.\d+)?px", rest):
                    stray.append(line.strip())
        # The offending lines go in the label, because "a px somewhere in
        # 400 lines of CSS" is not a finding anybody can act on.
        check("and nothing that carries layout is left in px"
              + ("" if not stray else "  <- " + " | ".join(stray[:3])),
              not stray)
        # A count of callers is a count. "8.0" is a decimal where there
        # cannot be one, and the scale had a top but no bottom.
        check("the caller axis counts in whole callers and starts at zero",
              ">8</text>" in page and ">4</text>" in page
              and ">0</text>" in page and ">8.0</text>" not in page)
        # 133 characters in a 358px column is 692px of sideways dragging,
        # which nobody does. pre-wrap inserts nothing, so a copy still gives
        # back the exact original line.
        _, page = get("/dialing")
        check("code blocks wrap on a phone rather than being dragged",
              "article pre { white-space:pre-wrap;" in page)
        # This rule used to carry a :not(.chart) exception for the one <pre>
        # on the site that wrapping would have destroyed, the manifesto's
        # ASCII comparison diagram. That is an SVG now, so every <pre> left
        # in an article is a command somebody may want to copy.
        check("and nothing is excepted from it any more, because nothing is art",
              ":not(.chart)" not in page)
        # Thirteen of the fifteen blockquotes on this site are real
        # warnings. The two that are reassurances were sitting in the same
        # alarm-coloured box, which said the opposite of the words inside.
        check("a reassurance is a calm box, not an alarm",
              'class="aside"' in page and "You never have to touch any of this" in
              page.split('class="aside"')[1][:300])
        check("and the marker never leaks into the page", "[!NOTE]" not in page)
        _, page = get("/forward")
        check("a real warning is still a warning",
              'class="warn"' in page and 'class="aside"' not in page)

        # ------------------------------------------------------------------
        # Coming back after a gap.
        #
        # This is the one that cost a real listing. A board was unplugged for
        # an hour to have an SD card wired to it, and when it came back the
        # server demoted it from 'offline' to 'pending' and restarted the
        # three hour clock. The public page lists 'online' and 'offline' and
        # not 'pending', so reconnecting is what removed it from the page.
        # Taking it offline never had.
        #
        # There was no test for this. The nearest one covers a board that
        # lost its token and accepts either state on purpose, so it walked
        # straight past. A board that keeps its token and goes quiet is the
        # single most ordinary thing that happens to a directory, and it was
        # the untested path.
        print("A board that goes quiet and comes back")
        import sqlite3

        def age(token, seconds, state, streak_back=0):
            """Put one row into the past: last_seen, state, and optionally
            how long ago it started earning its listing."""
            con = sqlite3.connect(db)
            con.execute(
                "UPDATE boards SET last_seen = strftime('%s','now') - ?, "
                "state = ?, streak_start = strftime('%s','now') - ? "
                "WHERE token = ?",
                (seconds, state, streak_back or seconds, token))
            con.commit()
            con.close()

        code, first, _ = post({"name": "The Napping Board", "owner": "Rip",
                               "description": "goes quiet, comes back",
                               "port": 6400, "interval": 10})
        nap = first.get("token", "")
        check("a new board gets a token", len(nap) >= 16)

        # It serves its hours and is published, then goes dark for a day.
        age(nap, 86400, "offline", streak_back=86400 + 4 * 3600)
        code, back, _ = post({"name": "The Napping Board", "owner": "Rip",
                              "description": "goes quiet, comes back",
                              "port": 6400, "interval": 10, "token": nap})
        check("a day off is answered", code == 200)
        check("and it resumes the listing it already earned",
              back.get("state") == "online")
        check("with no probation to serve again", back.get("public_in") == 0)
        _, page = get("/", host="boards.example")
        check("so it is back on the public page", "The Napping Board" in page)

        # Gone long enough and it serves the hours again. That is the spam
        # stop: an address that posts once, vanishes for a week and returns
        # is not a board anybody has been able to call.
        age(nap, int(5 * 86400), "offline", streak_back=int(6 * 86400))
        code, stale, _ = post({"name": "The Napping Board", "owner": "Rip",
                               "description": "goes quiet, comes back",
                               "port": 6400, "interval": 10, "token": nap})
        check("gone past the relist window, it is pending again",
              stale.get("state") == "pending")
        check("and is told how long it has to wait",
              stale.get("public_in", 0) > 0)
        _, page = get("/", host="boards.example")
        check("and is not on the page while it waits",
              "The Napping Board" not in page)

        # Leave nothing behind for the checks that follow.
        con = sqlite3.connect(db)
        con.execute("DELETE FROM boards WHERE token = ?", (nap,))
        con.commit()
        con.close()

        # ------------------------------------------------------------------
        # The browser installer.
        #
        # Two halves, and the split is deliberate. The state a visitor
        # actually meets today is "no firmware published", and that is
        # checked over HTTP against the real server with the repository's
        # own firmware/ directory, because that is the deployment. The state
        # with images in it is checked by pointing the module's FIRMWARE_DIR
        # at a scratch tree: it needs no second server and no second port,
        # and nothing that looks like a firmware image ever goes near the
        # repository.
        S_EWT_VERSION = S.EWT_VERSION
        S_EWT_BASE = S.EWT_BASE
        S_EWT_SCRIPT = S.EWT_SCRIPT
        # Which state the deployment is in decides which checks apply. Before
        # 1.0.0 the firmware repository is private, so the fetcher cannot
        # reach it and a test release (0.23.0) is committed into firmware/
        # by hand, for Rob to flash a fresh board from /install. With it
        # there, "nothing published" is simply not the state any more, and
        # checking for it reported the working page as four failures.
        # os.path, not pathlib: this function imports pathlib further down,
        # which makes the name local here and unbound at this point.
        fw_repo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "firmware")
        published = os.path.isdir(fw_repo) and any(
            os.path.isfile(os.path.join(fw_repo, d, "esp32", "firmware.bin"))
            for d in os.listdir(fw_repo))
        code, inst = get("/install")
        if published:
            print("The installer page, with a release published")
            check("there is an install page", code == 200)
            check("it offers the install button", "<esp-web-install-button" in inst)
            check("and the only script is this site's own copy of ESP Web Tools",
                  "<script" in inst and 'src="/install/esp-web-tools/' in inst
                  and "unpkg" not in inst)
        else:
            print("The installer page, with nothing published")
            check("there is an install page", code == 200)
            check("it says plainly that no release is published yet",
                  "No release published yet" in inst
                  and "no firmware image on this site to install yet" in inst)
            check("and sends a reader to the build page instead",
                  '<div class="installer none">' in inst
                  and 'the <a href="/build">build page</a>' in inst)
            check("it offers no button and no element to press",
                  "<esp-web-install-button" not in inst and 'slot="activate"' not in inst)
            # The whole point of tying the script to the widget: with nothing
            # published there is no widget, so there is no code on the page
            # either. A flag would have had to be remembered.
            check("and loads no script at all", "<script" not in inst)
        check("no release path is served when there is no release",
              get("/install/0.22.1/manifest.json")[0] == 404
              and get("/install/0.22.1/esp32/firmware.bin")[0] == 404)
        check("and the old /firmware/ paths are gone",
              get("/firmware/0.22.1/manifest.json")[0] == 404)
        # The page tells a reader what the installer shows, step by step,
        # and the facts it leans on are the firmware's and the tool's own.
        flat_i = " ".join(inst.split())
        check("the page walks through the install in order",
              has_h(inst, 2, "What happens, in order") and "<ol>" in inst
              and "It waits up to 30 seconds." in flat_i
              and "The board tries for up to 30 seconds." in flat_i)
        check("and says how to change the Wi-Fi later",
              has_h(inst, 2, "Changing the Wi-Fi later")
              and "<b>Change Wi-Fi</b>" in inst)
        check("and which browsers, checked, and that a phone is untried",
              "Firefox can do it from version 151" in flat_i
              and "Chrome on Android has had the same feature since version 148" in flat_i
              and "untried" in flat_i)
        check("and points on to calling the board and forwarding the port",
              'href="/terminals"' in inst and 'href="/forward"' in inst)
        # The one default password, said plainly, with the limits the
        # firmware puts on it and the honest limit of those limits.
        check("the install page gives the default sysop password plainly",
              has_h(inst, 2, "The sysop password")
              and "and it is <code>unleashed</code>" in flat_i)
        check("and says it works only from your own network, and only until changed",
              "It only works from your own network" in flat_i
              and "only until you change it" in flat_i)
        check("and that the board will not list itself while it is set",
              "the board will not put itself on this directory" in flat_i)
        check("and walks through choosing your own on the first call",
              "and asks for the <b>Sysop password</b>. Type <code>unleashed</code>" in flat_i
              and "Choose a sysop password of your own and press F1" in flat_i)
        check("and says local only is a guard, not a wall, and why",
              "is a guard, not a wall" in flat_i
              and "rewrite forwarded traffic" in flat_i
              and "Do not <a href=\"/forward\">forward the port</a>" in flat_i)
        src_i = open(os.path.join("pages", "install.md"), encoding="utf-8").read()
        check("and the TODO it replaced is gone",
              "TODO" not in src_i and "TODO" not in inst)
        check("and the page points on to the setup guide",
              'href="/setup"' in inst)
        # A comment is dropped whole, so one left open would swallow the
        # rest of its page without a word. Every page opens as many as it
        # closes.
        unbalanced = [n for n in sorted(os.listdir("pages")) if n.endswith(".md")
                      and (open(os.path.join("pages", n), encoding="utf-8").read().count("<!--")
                           != open(os.path.join("pages", n), encoding="utf-8").read().count("-->"))]
        check("every page closes the comments it opens"
              + ("" if not unbalanced else "  <- " + ", ".join(unbalanced)),
              not unbalanced)

        # The installer's code, served from here. It is served whether or
        # not a release is published, because it is static; the page with
        # no release never asks for it.
        print("ESP Web Tools, from this machine")
        code, ctype, body = fetch(S_EWT_SCRIPT)
        check("the entry point is served here, as JavaScript",
              code == 200 and ctype.startswith("text/javascript")
              and b"esp-web-install-button" in body)
        ewt_dir = os.path.join("vendor", "esp-web-tools", S_EWT_VERSION)
        chunks = sorted(n for n in os.listdir(ewt_dir) if n.endswith(".js"))
        imported = set()
        for n in chunks:
            text = open(os.path.join(ewt_dir, n), encoding="utf-8").read()
            imported.update(re.findall(r'import\("\./([^"]+)"\)', text))
            imported.update(re.findall(r'from"\./([^"]+)"', text))
            imported.update(re.findall(r'from "\./([^"]+)"', text))
        # Every chunk the bundle can ask for is in the directory and comes
        # back from the server. A missing one fails in the middle of an
        # install, for one chip family, on somebody else's board.
        missing = [n for n in sorted(imported)
                   if n not in chunks or fetch(S_EWT_BASE + n)[0] != 200]
        check("every chunk it imports is here and is served"
              + ("" if not missing else "  <- " + ", ".join(missing)),
              bool(imported) and not missing)
        # Anything absolute inside it is a link for a person to click, never
        # an import: no module is fetched from anywhere but here.
        remote = [n for n in chunks
                  if re.search(r'(import\(|from ?)"(https?:)?//',
                               open(os.path.join(ewt_dir, n), encoding="utf-8").read())]
        check("and nothing in it imports from another origin",
              not remote)
        sums = {}
        for line in open(os.path.join(ewt_dir, "SHA256SUMS"), encoding="utf-8"):
            if line.strip():
                digest, name = line.split(None, 1)
                sums[name.strip().lstrip("*")] = digest
        on_disk = sorted(n for n in os.listdir(ewt_dir) if n != "SHA256SUMS")
        import hashlib
        changed = [n for n in on_disk
                   if sums.get(n) != hashlib.sha256(
                       open(os.path.join(ewt_dir, n), "rb").read()).hexdigest()]
        # Byte for byte as npm published it: a file edited in place, or one
        # added without a line here, is not the thing the README says it is.
        check("and it is byte for byte what SHA256SUMS says, with nothing extra"
              + ("" if not changed else "  <- " + ", ".join(changed[:3])),
              bool(on_disk) and not changed and set(sums) == set(on_disk))
        code, ctype, body = fetch(S_EWT_BASE + "LICENSE")
        check("its licence is served beside it",
              code == 200 and b"Apache License" in body
              and fetch(S_EWT_BASE + "THIRD_PARTY_LICENSES.txt")[0] == 200)
        # Names, not paths: only a chunk-shaped name or a licence file.
        check("and nothing else in or above that directory is reachable",
              fetch(S_EWT_BASE + "SHA256SUMS")[0] == 404
              and fetch(S_EWT_BASE + "nope.js")[0] == 404
              and fetch("/install/esp-web-tools/1.0.0/install-button.js")[0] == 404
              and fetch(S_EWT_BASE + "..%2F..%2F..%2Fserver.py")[0] == 404)
        check("the page is reachable from the build page and the footer",
              "/install" in get("/build")[1] and '/install">Install</a>' in inst)
        # A page off the menu still has to say where it is. Without this the
        # nav marks nothing, or worse marks Boards.
        check("and the menu marks Build one as the section it belongs to",
              '<a class="here" href="/build">Build one</a>' in inst)

        # ------------------------------------------------------------------
        # The setup guide: every CONFIG page, with the board's own screens.
        print("The setup guide")
        code, setup = get("/setup")
        flat_s = " ".join(setup.split())
        check("there is a setup page, under Build one",
              code == 200 and '<a class="here" href="/build">Build one</a>' in setup)
        check("with every core CONFIG page",
              all(has_h(setup, 2, p)
                  for p in ("board", "limits", "accounts", "backup", "staff", "wifi")))
        check("and every plugin page",
              all(has_h(setup, 3, p)
                  for p in ("chat", "files", "forums", "info", "announce", "sd"))
              and has_h(setup, 3, "serial and example"))
        check("it starts with becoming the sysop, and points at the password step",
              has_h(setup, 2, "First, become the sysop")
              and "<code>unleashed</code>" in setup and 'href="/install"' in setup)
        # The screens are the board's own, drawn as the site's art: a grid of
        # text pinned to its columns, not a picture.
        shots = re.findall(r'<svg class="art shot"[^>]*role="img"[^>]*aria-label="[^"]+"', setup)
        check("with eight screens captured from the board, each described",
              len(shots) == 8 and setup.count('lengthAdjust="spacingAndGlyphs"') > 80
              and "<img" not in setup.split("<article>")[1])
        # The prose and the captures cannot disagree about a field's name:
        # every label the board drew on the board and file area forms is a
        # row in the page's tables.
        drawn = []
        for shot in ("config-board", "config-area"):
            doc = json.load(open(os.path.join("shots", shot + ".json"), encoding="utf-8"))
            for row, attr in zip(doc["rows"], doc["attrs"]):
                if row.startswith(" ") and len(row) > 10 and attr[1] in "bc" and row[1:10].strip():
                    drawn.append(row[1:10].strip())
        missing_l = [l for l in drawn if f"<b>{l}</b>" not in setup]
        check("and every field those forms show is explained in a table"
              + ("" if not missing_l else "  <- " + ", ".join(missing_l)),
              len(drawn) >= 12 and not missing_l)
        check("each capture says where it came from",
              all(json.load(open(os.path.join("shots", n), encoding="utf-8"))
                  .get("source", "").startswith("unleashed BBS ")
                  for n in os.listdir("shots") if n.endswith(".json")))
        check("the guide is linked from the build and install pages",
              'href="/setup"' in get("/build")[1] and 'href="/setup"' in get("/install")[1])
        check("and says the listing waits for the password to change",
              "the board will not list itself while the default password is still set"
              in flat_s)

        # ------------------------------------------------------------------
        # Supporting the project: a plain link out, and nothing loaded from
        # the payment company.
        print("The support page")
        code, don = get("/donate")
        flat_d = " ".join(don.split())
        check("there is a support page",
              code == 200 and has_h(don, 1, "Support the project"))
        check("described by its first sentence, not by the drawing above it",
              '<meta name="description" content="µnleashed BBS is free software, and it '
              'stays free.' in don)
        check("with the cover at the top, as an image with words for a screen reader",
              re.search(r'<img class="cover" src="/cover\.svg" width="1600" height="310" '
                        r'alt="[^"]{40,}">', don) is not None
              and don.split("<article>")[1].index('class="cover"')
                  < don.split("<article>")[1].index("is free software, and it stays free"))
        # A plain link, and the page says so: nothing from another origin.
        srcs_d = re.findall(r'src="([^"]+)"', don)
        check("Buy Me a Coffee is a plain link, and nothing on the page is loaded from it",
              '<a href="https://buymeacoffee.com/unleashed_bbs">' in don
              and "<script" not in don and "<iframe" not in don
              and all(u.startswith("/") and not u.startswith("//") for u in srcs_d)
              and "Nothing on this site loads anything from Buy Me a Coffee" in flat_d)
        src_d = open(os.path.join("pages", "donate.md"), encoding="utf-8").read()
        check("its three editor notes stay in the source and none reaches the page",
              src_d.count("<!--") == 3 and "<!--" not in don.split("<article>")[1]
              and "Re-check when this page is edited" not in don)
        # Rob's line: supporters get posts and news, never features or
        # priority, and the page must not say they get nothing.
        check("it says what support buys and what it never buys",
              "Supporters get posts and development news on Buy Me a Coffee" in flat_d
              and "What support never buys is features or priority." in flat_d
              and "Giving buys no features" not in flat_d)
        # Rob, 2026-09-23: only lifetime members are named, on the ABOUT
        # screen and on this page. No list of every supporter, no release
        # notes mention, no page on Unleashed HQ: nobody has time to keep
        # those up, and a promise nobody keeps is worse than none.
        check("and how supporters are thanked: lifetime members named, nobody else listed",
              has_h(don, 2, "Thank you") and "Lifetime members" in flat_d
              and "ABOUT" in flat_d and "Unleashed HQ" not in flat_d
              and "release notes" not in flat_d)
        # The list starts empty, and an empty list says nothing at all.
        check("an empty thanks list shows no list and no heading",
              "The thanks list" not in don and 'class="thanks"' not in don)
        import pathlib
        was_sup = S.SUPPORTERS_FILE
        tmp_sup = os.path.join(tempfile.mkdtemp(prefix="dirsup"), "supporters.txt")
        with open(tmp_sup, "w", encoding="utf-8") as fh:
            fh.write("# a comment\n\nAda <Lovelace>\n  Grace Hopper  \n")
        try:
            S.SUPPORTERS_FILE = pathlib.Path(tmp_sup)
            shown_t = S.thanks_html()
        finally:
            S.SUPPORTERS_FILE = was_sup
        check("and a name, once there, is listed and escaped, comments left out",
              shown_t == '<h3>The thanks list</h3><ul class="thanks">'
                         '<li>Ada &lt;Lovelace&gt;</li><li>Grace Hopper</li></ul>')
        code, ctype, cov = fetch("/cover.svg")
        cov = cov.decode("utf-8", "replace")
        # Laid out for Buy Me a Coffee's crop, with an empty lower half on
        # purpose; the site shows the band, with the frame closed round it.
        check("the cover is served cut to its content, frame redrawn",
              code == 200 and ctype == "image/svg+xml"
              and 'height="310" viewBox="0 0 1600 310"' in cov
              and '<path d="M18,8 H1592 V292 L1582,302 H8 V18 Z"' in cov)
        check("and every face's footer offers it as Donate, in its own colour",
              all(f'<a class="donate" href="{want}donate">Donate</a>' in page
                  for page, want in ((get("/")[1], "/"),
                                     (get("/", host="about.example")[1], "https://boards.example/"),
                                     (get("/", host="data.example")[1], "https://boards.example/"))))

        # The wordmark is the way home, on every page of every face.
        # The first-boot setup, as 0.23.0 does it, in the board's own words.
        check("the setup guide shows the first-boot setup as the board draws it",
              all(f'aria-label="{S.SHOTS[k][1][:30]}' in setup for k in (
                  "shot-setup-offer", "shot-setup-screen", "shot-config-staff",
                  "shot-newsysop-1"))
              and "This board has not been set up yet." in setup
              and "YOU ARE THE SYSOP" in setup)

        # ------------------------------------------------------------------
        # /install, drawn: what is about to happen, step by step.
        print("The install page, drawn")
        inst2 = get("/install")[1]
        art_i = re.findall(r'<svg class="art steps" viewBox="[^"]+" aria-hidden="true"', inst2)
        check("five drawings of what is about to happen, all decoration",
              len(art_i) == 5
              and all(S.ART[k] in inst2 for k in ("install-cable", "install-write",
                                                   "install-boot", "install-wifi",
                                                   "install-setup")))
        # The steps are split by the drawings and still count on.
        check("and the numbered steps carry on across them",
              '<ol start="5">' in inst2 and '<ol start="6">' in inst2
              and '<ol start="7">' in inst2)
        flat_i2 = " ".join(inst2.split())
        check("the reset section: Change Wi-Fi now, a reflash with erase last",
              has_h(inst2, 2, "If something goes wrong, reset rather than reflash")
              and "works while the board is failing to join one" in flat_i2
              and "nothing on the board is erased" in flat_i2
              and "install again with Erase device ticked" in flat_i2)
        # The BOOT button and the Wi-Fi fallback are firmware 1.0.1's, moved
        # there from 0.24.0; 1.0.0 does not have them. The repository carries
        # 0.23.0 at most, so here they must not show; the second server below
        # proves they stay hidden at 1.0.0 and show at 1.0.1.
        src_gate = open(os.path.join("pages", "install.md"), encoding="utf-8").read()
        check("the reset section is gated on 1.0.1, and nothing on 0.24.0",
              "::: from 1.0.1" in src_gate and "0.24" not in src_gate)
        check("and nothing of 1.0.1's shows while the newest release is older",
              "The BOOT button" not in inst2 and S.ART["boot-button"] not in inst2
              and "::: from" not in inst2)
        check("the setup steps name what the board says",
              "This board has not been set up yet" in flat_i2
              and "YOU ARE THE SYSOP" in flat_i2 and "ESC skips it" in flat_i2
              and "The board refuses <code>unleashed</code> here" in flat_i2)

        # ------------------------------------------------------------------
        # Headings carry ids, so a page can be linked part way down: the
        # install card's amber box points at #before-you-start.
        print("Heading ids")
        ids = S.md_render("## Wi-Fi\n\n## Wi-Fi\n\n### A `b` [c](/d)\n\n# Top!")
        check("an id is the heading's words, lower case, runs of anything else one -",
              '<h2 id="wi-fi">Wi-Fi</h2>' in ids
              and '<h3 id="a-b-c">A <code>b</code> <a href="/d">c</a></h3>' in ids
              and '<h1 id="top">Top!</h1>' in ids)
        check("and unique on the page, a second of the same name numbered",
              '<h2 id="wi-fi-2">Wi-Fi</h2>' in ids)
        page_ids = re.findall(r'<h[1-3] id="([^"]+)"', inst2)
        check("including across the pieces a page is rendered in"
              + ("" if len(page_ids) == len(set(page_ids)) else "  <- duplicate ids"),
              len(page_ids) > 10 and len(page_ids) == len(set(page_ids))
              and "before-you-start" in page_ids and "other-browsers" in page_ids)

        # ------------------------------------------------------------------
        # /install's top: the title, the card and the steps, in that order,
        # which is what a phone and a screen reader get; the stylesheet puts
        # the card beside them from 901px up.
        print("The install card")
        top = (inst2.split('<div class="install-top">')[1].split('id="before-you-start"')[0]
               if '<div class="install-top">' in inst2 else "")
        check("the title, the card, then the steps, inside one block",
              top.find('<div class="intro"><h1 ') == 0
              and 0 < top.find('<div class="installer') < top.find('<div class="steps">')
              and top.find('<div class="steps">') < top.find('id="what-happens-in-order"'))
        if published:
            check("the card's amber box is the page's own words, and links down the page",
                  '<div class="pre"><p><b>Before you start:</b> Chrome or Edge' in top
                  and '<a href="#before-you-start">more below</a>' in top)
            check("and it carries its small drawing, the board slot and one version line",
                  '<svg class="art mini"' in top and "Board: ESP32, 4 MB flash" in top
                  and top.count('class="meta ver ') == 1)
            check("the installer's own licence is under Doing it the other way",
                  S.EWT_BASE + "LICENSE" in inst2.split('id="doing-it-the-other-way"')[1]
                  and S.EWT_BASE + "LICENSE" not in top)
        css_i = inst2.split("<style>")[1]
        check("two columns from 901px, the card sticky and level with the title",
              "grid-template-columns:minmax(0, 1fr) 22rem" in css_i
              and "grid-row:1 / span 2" in css_i and "position:sticky" in css_i)
        check("and on a phone the button comes before the amber box",
              "article .installer esp-web-install-button { order:2; }" in css_i
              and "article .installer .pre { order:5; }" in css_i)
        # The board's Improv answer is telnet://, which a browser cannot open.
        check("the last step says Telnet details, not Visit Device",
              "<b>Telnet details</b>" in inst2 and "Visit Device" not in inst2)

        # ------------------------------------------------------------------
        # One primary action on each entry page, drawn like the installer's
        # button, with the other way round beside it as an outlined one. A
        # button that goes somewhere says where it goes: only the button on
        # /install says Install, because only that one installs.
        print("Calls to action")
        for path, alt in (("/build", "#getting-it-running"),
                          ("/setup", "/build#getting-it-running")):
            pg = get(path)[1]
            body = pg.split("</nav>")[1]
            check(f"{path}: Visit the web installer, and Build from source beside it",
                  body.count('class="btn"') == 1 and body.count('class="btn2"') == 1
                  and '<div class="cta"><p class="acts"><a class="btn" href="/install">'
                      "Visit the web installer</a>" in body
                  and f'<a class="btn2" href="{alt}">Build from source</a>' in body)
            check(f"{path}: and no button there says Install",
                  not re.search(r'class="btn2?"[^>]*>[^<]*Install', body))
        check("the from-source button lands on a heading that exists",
              'id="getting-it-running"' in get("/build")[1])
        css_c = get("/build")[1].split("<style>")[1]
        check("on a phone the two stack, the filled one first, full width",
              ".cta .acts { flex-direction:column; align-items:stretch; }" in css_c
              and ".cta a.btn, .cta a.btn2 { display:block; }" in css_c)
        bld = get("/build")[1].split("</nav>")[1]
        check("on /build it comes before anything else on the page",
              bld.index('class="btn"') < bld.index('id="what-you-need"')
              and 'class="tip"' not in bld)
        setp = get("/setup")[1].split("</nav>")[1]
        check("and on /setup before the drawing",
              setp.index('class="btn"') < setp.index('class="art steps"'))
        # The board list is the other way round (0.20.1, Rob: "This seems a
        # bit big for a button there in the middle"). No full size button
        # anywhere in its flow; the way to a board of your own is a small
        # card beside the heading, with two compact buttons in it.
        home = get("/")[1]
        hbody = home.split("</nav>")[1].split("<footer")[0]
        check("the board list has no full size button in its flow",
              'class="btn"' not in hbody and 'class="btn2"' not in hbody
              and 'class="cta"' not in hbody)
        check("it has the Run your own board card instead, with its two ways in",
              '<aside class="runcard" aria-labelledby="run-your-own">'
              '<h2 id="run-your-own">Run your own board</h2>'
              '<p class="say">An ESP32, a USB cable, five minutes.</p>'
              '<p class="acts"><a class="fill" href="/install">Web installer</a>'
              '<a class="line" href="/build#getting-it-running">Build from source</a>'
              in hbody and hbody.count('class="runcard"') == 1)
        check("and neither of its buttons says Install",
              not re.search(r'class="(fill|line)"[^>]*>[^<]*Install', hbody))
        lst = hbody.find("<table>")
        lst = lst if lst >= 0 else hbody.find("No boards listed yet")
        check("the card follows the heading and the lead, and the list follows it",
              0 <= hbody.find("<h1>BBS directory</h1>") < hbody.find('<p class="lead">')
              < hbody.find('<aside class="runcard"') < lst)
        css_h = home.split("<style>")[1]
        check("beside them from 901px as a grid column, not a float",
              ".listtop { display:grid; grid-template-columns:minmax(0, 1fr) 19.5rem;"
              in css_h and not re.search(r"\.runcard[^{]*\{[^}]*float", css_h))
        check("its buttons are the compact ones, in the installer card's shape",
              ".runcard a.fill, .runcard a.line { display:inline-block; font-size:0.75rem;"
              in css_h
              and "border-radius:0.5rem;\n        padding:1.125rem 1.25rem;" in css_h)
        check("and on a phone the card is its title and the two buttons",
              ".runcard .say { display:none; }" in css_h)
        # 0.20.2 (Rob): the card stands out. A wash of --dial over the page
        # rather than a flat block, its border the same blue, and three
        # lamps going slowly round the edge, in CSS alone.
        check("the card is washed in --dial, its border the same blue",
              ".runcard { position:relative; background:rgba(127, 212, 255, 0.12);"
              in css_h and "border:1px solid rgba(127, 212, 255, 0.6);" in css_h
              and "--dial:#7fd4ff;" in css_h)
        check("three lamps on its edge, hidden from a screen reader",
              all(f'<span class="dot d{i}" aria-hidden="true"></span>' in hbody
                  for i in (1, 2, 3))
              and hbody.count('class="dot ') == 3)
        run_moving = css_h[css_h.find("@media (prefers-reduced-motion: no-preference) {\n"
                                      "  @supports (offset-path"):]
        run_moving = run_moving[:run_moving.find("\n}\n")]
        check("they follow the card's own rounded edge, a third of a lap apart",
              "offset-path:inset(0 round 0.5rem);" in css_h
              and ".runcard .d2 { offset-distance:33.333%; }" in css_h
              and ".runcard .d3 { offset-distance:66.667%; }" in css_h)
        check("and move only where reduced motion does not stop them",
              run_moving.startswith("@media (prefers-reduced-motion: no-preference)")
              and ".runcard .dot { animation:runlap 16s linear infinite; }" in run_moving
              and "@keyframes runlap" in run_moving
              and css_h.count("animation:runlap") == 1
              and css_h.count("@keyframes runlap") == 1)
        check("a browser without offset-path gets three still lamps on the edge",
              ".runcard .d1 { top:-0.25rem; left:25%; }" in css_h
              and ".runcard .d2 { top:45%; right:-0.25rem; }" in css_h
              and ".runcard .d3 { bottom:-0.25rem; left:30%; }" in css_h
              and "@supports (offset-path: inset(0 round 0.5rem)) {" in css_h)

        # ------------------------------------------------------------------
        # Upgrading a board that already runs the BBS (0.20.2, Rob: "make
        # sure the website calls out on the flasher page how to upgrade").
        print("Upgrading")
        code, upg = get("/upgrade")
        check("/upgrade is served, under its own heading",
              code == 200 and has_h(upg, 1, "Upgrade a board"))
        check("it lights Build one in the menu, the installer's section",
              '<a class="here" href="/build">Build one</a>' in upg)
        uflat = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", upg)).split())
        check("back up first, through the backup window, said to hold what it holds",
              '<a href="/setup#backup">the backup window</a>' in upg
              and 'id="backup"' in get("/setup")[1]
              and "It does not hold the mail or the information pages." in uflat)
        check("a recognised board is offered the update, with no erase",
              "Update unleashed BBS" in uflat and "0.22.1 or later" in uflat
              and "It does not ask about erasing and it does not erase." in uflat)
        check("what is kept, and the screens that go back to stock",
              "Kept: the accounts, the settings (Wi-Fi included), the mail" in uflat
              and "Back to stock: the screens in the board's own flash." in uflat)
        check("an older board: no erase from 0.17.0 on, an erase before it",
              "From 0.17.0 on, leave Erase device unticked." in uflat
              and "Before 0.17.0, the erase cannot be avoided." in uflat
              and "the page asks for your Wi-Fi at the end" in uflat)
        inst_now = get("/install")[1]
        check("and every section it sends a reader to exists",
              'href="/install#changing-the-wi-fi-later"' in upg
              and 'id="changing-the-wi-fi-later"' in inst_now
              and 'href="/install#if-something-goes-wrong-reset-rather-than-reflash"' in upg
              and 'id="if-something-goes-wrong-reset-rather-than-reflash"' in inst_now)
        check("Upgrade is in the footer's Get started row on every face",
              all(re.search(r'<span class="lbl">Get started</span>.*?'
                            r'>Install</a> &middot; <a href="[^"]*/upgrade">Upgrade</a>'
                            r' &middot; ', p, re.S)
                  for p in (home, inst_now, get("/", host="about.example")[1],
                            get("/", host="data.example")[1])))
        # The call-out on /install opens the steps column: beside the card
        # on a desktop, after it on a phone, so the button keeps its place.
        itop = inst_now.split('<div class="install-top">')[1].split('id="before-you-start"')[0]
        check("/install calls it out first in the steps, linking /upgrade",
              '<div class="steps"><p class="aside"><b>Already running µnleashed?</b> '
              "Plug it in and press <b>Install on my board</b>; it offers an update "
              'and keeps your accounts. <a href="/upgrade">Upgrading a board</a>' in itop
              and itop.find('<div class="steps"><p class="aside">')
                  < itop.find('id="what-happens-in-order"'))
        check("and it is not indented the way a note inside prose is",
              "article .install-top > .steps > p.aside:first-child { margin:0 0 1.25rem; }"
              in inst_now)

        # ------------------------------------------------------------------
        # Rob could not find the donation page. It is in the menu now, last,
        # and first in the footer's second row, as well as being served.
        print("Donate")
        check("the menu offers Donate on every face",
              all('>Donate</a></nav>' in p for p in (
                  get("/")[1], get("/install")[1], get("/", host="about.example")[1],
                  get("/", host="data.example")[1])))
        check("and marks it on the page itself",
              '<a class="here" href="/donate">Donate</a>' in don)

        # ------------------------------------------------------------------
        # /connected: where the installer's last step lands. The address is
        # in the fragment, which never reaches this server, so a few inline
        # lines read it; nothing else on the page runs, and nothing leaves.
        print("The telnet details page")
        code, conn = get("/connected")
        flat_c = " ".join(conn.split())
        scripts_c = re.findall(r"<script[^>]*>(.*?)</script>", conn, re.S)
        check("there is a /connected page, under Build one",
              code == 200 and '<a class="here" href="/build">Build one</a>' in conn)
        check("its one script is the inline one written here, with no src",
              len(scripts_c) == 1 and "<script src" not in conn
              and "<script>" + scripts_c[0] + "</script>" == S.CONNECTED_JS)
        js_c = scripts_c[0] if scripts_c else ""
        check("which reads the fragment, writes only text, and sends nothing",
              "location.hash" in js_c and "textContent" in js_c
              and not any(w in js_c for w in ("innerHTML", "outerHTML", "insertAdjacent",
                                              "document.write", "fetch", "XMLHttpRequest",
                                              "sendBeacon", "WebSocket", "eval", "cookie",
                                              "localStorage", "location.href")))
        check("and takes a dotted IPv4 address and a port, and nothing else",
              r"/^#((?:\d{1,3}\.){3}\d{1,3})(?::(\d{1,5}))?$/" in js_c
              and "+o>255" in js_c and "+v.port>65535" in js_c)
        check("with the address box hidden until it has one",
              '<div class="board-at" id="found" hidden>' in conn
              and '<div class="board-at unknown" id="noaddr">' in conn)
        check("the address box has the command, a link, SyncTERM and PuTTY",
              '<pre>telnet <span data-c="host"></span> <span data-c="port"></span></pre>' in conn
              and 'id="c-link"' in conn
              and '<code>syncterm telnet://<span data-c="host"></span>:' in conn
              and '<code>putty -telnet <span data-c="host"></span> -P ' in conn)
        check("with no address, it says where to find one",
              "115200 baud" in flat_c and "<code>unleashed</code>" in flat_c
              and "telnet unleashed.local 6400" in flat_c)
        check("and gives the default sysop password, the warning, and the setup guide",
              "sysop password is <code>unleashed</code>" in flat_c
              and "Change it before anything else." in flat_c
              and 'href="/setup"' in conn and 'href="/install#the-sysop-password"' in conn)

        # The copy of ESP Web Tools sends a telnet:// address there, and says
        # it was changed, as its licence requires.
        print("The installer's one change")
        dlg = [n for n in os.listdir(os.path.join("vendor", "esp-web-tools", S.EWT_VERSION))
               if n.startswith("install-dialog-")]
        dlg_src = open(os.path.join("vendor", "esp-web-tools", S.EWT_VERSION, dlg[0]),
                       encoding="utf-8").read() if len(dlg) == 1 else ""
        check("the dialog chunk opens with a notice that it was modified, and how",
              dlg_src.startswith("/*\n * MODIFIED FILE.")
              and "Apache License 2.0" in dlg_src[:800]
              and "/connected#<address>:<port>" in dlg_src[:800])
        check("and in both places, a telnet link goes to /connected as Telnet details",
              dlg_src.count('?"/connected#"+this._client.nextUrl.slice(9)') == 2
              and dlg_src.count('?"Telnet details":"Visit Device"') == 2
              and dlg_src.count("href=${this._client.nextUrl}") == 0)
        check("and the vendor README records upstream's checksum for the file",
              "6dcfc30fb4bbf18e19a141c5eb9a694edafc5d4480b45762c221173f47effdb5"
              in open(os.path.join("vendor", "esp-web-tools", "README.md"),
                      encoding="utf-8").read())

        # ------------------------------------------------------------------
        # The footer: two rows, then the colophon, on every face.
        print("The footer")
        log = open("CHANGELOG.md", encoding="utf-8").read()
        newest = re.search(r"^## (\d+\.\d+\.\d+)", log, re.M).group(1)
        check("the site's version is the changelog's newest heading",
              S.SITE_VERSION == newest)
        feet = [p.split("<footer>")[1] for p in (
            get("/")[1], get("/install")[1], get("/", host="about.example")[1],
            get("/", host="data.example")[1])]
        check("every footer has its two rows",
              all('<span class="lbl">Get started</span>' in f
                  and '<span class="lbl">Reference</span>' in f
                  and f.index("Get started") < f.index("Reference") for f in feet))
        check("and the colophon: version, copyright, and the licence linked",
              all(f'<span>Site version {newest}</span> &middot; '
                  '<span>&copy; 2026 Robert Mech</span> &middot; ' in f
                  and '<span><a href="https://www.gnu.org/licenses/old-licenses/gpl-2.0.html">'
                      "GNU GPL v2 or later</a></span></p>" in f
                  and f.rindex('class="colophon"') > f.rindex('class="lbl"')
                  for f in feet))
        check("each piece of it kept whole, so a phone wraps between them",
              "footer .colophon span { white-space:nowrap; }" in get("/")[1])

        # ------------------------------------------------------------------
        # Every page names its own address, on the face it belongs to.
        print("Canonical addresses")
        canon = {("/", None): "https://boards.example/",
                 ("/setup", None): "https://boards.example/setup",
                 ("/", "about.example"): "https://about.example/",
                 ("/about", None): "https://about.example/",
                 ("/", "data.example"): "https://data.example/"}
        wrong = []
        for (path, host), want in canon.items():
            page = get(path, host=host)[1]
            if (f'<link rel="canonical" href="{want}">' not in page
                    or f'<meta property="og:url" content="{want}">' not in page):
                wrong.append(path + " " + (host or "list"))
        check("each page carries a canonical link and og:url for its own face"
              + ("" if not wrong else "  <- " + ", ".join(wrong)),
              not wrong and "@CANONICAL@" not in get("/install")[1])

        # The installer's dialog, dark: Material's own variables, set on the
        # element from this page (checked by eye in a browser as well).
        css0 = get("/install")[1].split("<style>")[1]
        check("the installer's dialog is themed dark from this page",
              "ewt-install-dialog, ewt-no-port-picked-dialog {" in css0
              and "--md-sys-color-surface:#14141b" in css0)

        # ------------------------------------------------------------------
        # The 0.17.0 outage, so it cannot happen again: setup.sh copied only
        # some of what the server reads, and a server missing shots/ died at
        # import. First, the server has to start with nothing beside it.
        print("The server starts with nothing beside it")
        import shutil
        bare = tempfile.mkdtemp(prefix="dirbare")
        shutil.copy("server.py", os.path.join(bare, "server.py"))
        port3 = PORT + 2
        env3 = dict(os.environ, DIRECTORY_PAGE_CACHE="0",
                    DIRECTORY_DB=os.path.join(bare, "d.db"), DIRECTORY_PORT=str(port3))
        server3 = subprocess.Popen([sys.executable, "server.py"], cwd=bare, env=env3,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        out3 = []
        threading.Thread(target=lambda: [out3.append(l) for l in server3.stdout],
                         daemon=True).start()
        up3 = None
        try:
            for _ in range(60):
                try:
                    up3 = fetch("/health", f"http://127.0.0.1:{port3}")[0]
                    break
                except Exception:
                    if server3.poll() is not None:
                        break
                    time.sleep(0.1)
            home3 = fetch("/", f"http://127.0.0.1:{port3}")[0] if up3 else None
            inst3 = fetch("/install", f"http://127.0.0.1:{port3}")[0] if up3 else None
        finally:
            server3.terminate()
            try:
                server3.wait(timeout=5)
            except Exception:
                server3.kill()
            shutil.rmtree(bare, ignore_errors=True)
        check("server.py alone, in an empty directory, starts and serves pages"
              + ("" if up3 else "  <- " + b"".join(out3[-3:]).decode("utf-8", "replace").strip()),
              up3 == 200 and home3 == 200 and inst3 in (200, 404))
        # Second, everything it reads beside itself is installed by setup.sh.
        srv_text = open("server.py", encoding="utf-8").read()
        read = set()
        for m in re.finditer(r'Path\(__file__\)\.resolve\(\)\.parent\s*/\s*"([^"]+)"'
                             r'(?:\s*/\s*"([^"]+)")?', srv_text):
            read.add(m.group(1) + ("/" + m.group(2) if m.group(2) else ""))
        setup_sh = open(os.path.join("deploy", "setup.sh"), encoding="utf-8").read()
        code_part = setup_sh.split('say "Code"')[1].split('say "Service"')[0]
        loop_dirs = set()
        for m in re.finditer(r"for dir in ([^;]+);", code_part):
            loop_dirs.update(m.group(1).split())
        missing_i = []
        for name in sorted(read):
            top = name.split("/")[0]
            named = (top in loop_dirs
                     or re.search(r'\$SRC"?/' + re.escape(top) + r'\b', code_part))
            deep = ("/" not in name or top in loop_dirs
                    or f'cd "$SRC/{top}" && find' in code_part)
            if not (named and deep):
                missing_i.append(name)
        check("everything the server reads beside itself is installed by setup.sh"
              + ("" if not missing_i else "  <- " + ", ".join(missing_i)),
              len(read) >= 8 and not missing_i)

        print("The wordmark goes home")
        homes = {"the board list": (get("/")[1], "/"),
                 "a page": (get("/setup")[1], "/"),
                 "the manifesto": (get("/", host="about.example")[1], "https://boards.example/"),
                 "the data face": (get("/", host="data.example")[1], "https://boards.example/")}
        check("the wordmark links to the board list on every face",
              all(f'<a class="home" href="{want}" aria-label="' in page
                  and '<pre class="logo"' in page.split('<a class="home"')[1].split("</a>")[0]
                  for page, want in homes.values()))

        # The avatar: link previews and the home-screen icon.
        print("The avatar")
        import struct

        def png_size(blob):
            return struct.unpack(">II", blob[16:24]) if blob[:8] == b"\x89PNG\r\n\x1a\n" else None
        code, ctype, blob = fetch("/avatar.png")
        check("the avatar is served as a PNG, 1024 square",
              code == 200 and ctype == "image/png" and png_size(blob) == (1024, 1024))
        code, ctype, blob = fetch("/apple-touch-icon.png")
        check("and the home-screen icon, 512 square",
              code == 200 and ctype == "image/png" and png_size(blob) == (512, 512))
        faces_a = [get("/")[1], get("/setup")[1], get("/", host="about.example")[1],
                   get("/", host="data.example")[1]]
        check("every face names it for link previews, by an absolute address",
              all(re.search(r'<meta property="og:image" content="https://[^"]+/avatar\.png">', p)
                  and '<meta name="twitter:card" content="summary">' in p
                  and re.search(r'<meta name="twitter:image" content="https://[^"]+/avatar\.png">', p)
                  and '<meta property="og:image:alt" content="' in p
                  for p in faces_a))
        check("and as the icon a phone puts on its home screen",
              all('<link rel="apple-touch-icon" href="/apple-touch-icon.png">' in p
                  for p in faces_a))
        # Not in static/, or the manifesto's gallery would show a logo.
        check("and it lives in brand/ with its generator, not in static/",
              os.path.isfile(os.path.join("brand", "make_avatar.py"))
              and os.path.isfile(os.path.join("brand", "unleashed-avatar.svg"))
              and not any("avatar" in n for n in os.listdir("static")))

        print("Every other page is still script-free")
        scripted = [p for p in ("/", "/about", "/data", "/build", "/whofor",
                                "/terminals", "/firstcall", "/forward", "/how",
                                "/rules", "/privacy", "/kids", "/teachers",
                                "/sdcard", "/dialing", "/author", "/donate",
                                "/setup", "/badges")
                    if "<script" in get(p)[1]]
        check("nothing else on the site loads any JavaScript"
              + ("" if not scripted else "  <- " + ", ".join(scripted)),
              not scripted)

        # ------------------------------------------------------------------
        # QuantumRob's name on the manifesto goes to a page about him. Every
        # fact on it is his own account; the checks pin the parts that are
        # easy to break later: the route, the spelling he confirmed, the
        # photographs and what they need to be allowed on the page at all.
        print("The author page")
        code, auth = get("/author")
        check("there is an author page", code == 200)
        check("with his name, both handles and the board he ran",
              "Robert Mech" in auth and "QuantumRob" in auth
              and "Daytona" in auth and "Psyberchat" in auth)
        # The suite runs with an about domain configured, so on the list face
        # the manifesto's menu entry is that domain rather than /about.
        check("and it belongs to the manifesto in the menu",
              '<a class="here" href="https://about.example/">What this is</a>' in auth)
        code, auth_about = get("/author", host="about.example")
        check("it is reachable on the about face too, where the link is",
              code == 200 and '<a class="here" href="/">What this is</a>' in auth_about)
        _, man = get("/", host="about.example")
        check("the manifesto links his name there, byline and both signatures",
              man.count('<a class="author" href="/author">QuantumRob</a>') == 3)
        imgs = re.findall(r"<img [^>]*>", auth)
        check("it shows four photographs", len(imgs) == 4)
        # Wikimedia rejects a hotlinked thumbnail at anything but its
        # standard widths, with an HTML error page the browser shows as a
        # broken image. So every thumb width has to be one of those.
        widths = re.findall(r"/(\d+)px-", " ".join(imgs))
        std = {"20", "40", "60", "120", "250", "330", "500", "960", "1280",
               "1920", "3840"}
        check("every hotlinked thumbnail is at a width Wikimedia serves",
              widths and set(widths) <= std)
        check("every picture is Wikimedia's, holds its space and says what it is",
              all("https://upload.wikimedia.org/" in i and ' alt="' in i
                  and ' width="' in i and ' height="' in i for i in imgs))
        check("and none of them tells Wikimedia which page asked",
              all('referrerpolicy="no-referrer"' in i for i in imgs))
        check("each is credited with its licence and its Commons page",
              auth.count('class="credit"') == 4
              and auth.count("commons.wikimedia.org/wiki/File:") == 4
              and "CC BY 3.0" in auth and "CC0" in auth)
        check("and the page says where the pictures come from",
              "load from Wikimedia Commons" in " ".join(auth.split()))

        # ------------------------------------------------------------------
        # The drawings. Same hand as the connection diagram, and every one
        # of them stands still for somebody who has asked for less motion.
        print("The drawings")
        check("each freedom has its drawing",
              man.count('<svg class="art icon ') == 12
              and man.count('<div class="freedom">') == 12)
        check("and a freedom's drawing is decoration beside its heading",
              man.count('aria-hidden="true" focusable="false">') >= 12)
        # The rule that makes the resting state the drawing: no animation
        # is declared anywhere but inside the no-preference block, so a
        # reader who asked for less motion is given none at all.
        art_css = man.split("svg.art { display:block;")[1].split("</style>")[0]
        moving = art_css.split("@media (prefers-reduced-motion: no-preference) {")
        check("every drawing's animation is inside the no-preference block",
              len(moving) == 2 and "animation:" not in moving[0]
              and moving[1].count("animation:") >= 15)
        bare = re.sub(r"/\*.*?\*/", "", art_css, flags=re.S)
        bare = re.sub(r"@media \([^)]*\)", "", bare)
        bare = re.sub(r"translate[XY]\([^)]*\)", "", bare)
        bare = re.sub(r"\d+px solid", "", bare)
        check("and the stylesheet the drawings share carries no layout px",
              not re.search(r"(?<![\w.-])\d+(?:\.\d+)?px", bare))
        code, fc = get("/firstcall")
        check("the first call page has its three screens",
              '<svg class="art steps"' in fc and 'role="img"' in fc
              and "Handle:" in fc and "ANSI 80x24" in fc)
        check("and says a silent terminal is asked a question, not nothing",
              "press DEL or BACKSPACE" in " ".join(fc.split()))

        # The listing page's warning. Policy, and said to be policy: the
        # software detects nothing and bans nobody by itself.
        code, how = get("/how")
        flat_h = " ".join(how.split())
        check("get listed warns about spam in a stop box with its skull",
              '<aside class="stop">' in how and 'class="art skull"' in how
              and "lifetime IP ban" in flat_h)
        check("and says it is policy applied by hand, not automatic",
              "applied by hand" in flat_h and "detects spam by itself" in flat_h
              and "automatically bans" not in flat_h)
        # The announce plugin stopped reading "name"; the board's name is
        # board_name in the core section. The example set a key the board
        # ignores.
        check("and its config example sets the name the board actually reads",
              "board_name  = The Rusty Modem" in how
              and "name        = The Rusty Modem" not in how)

        # The machines on /terminals: one strip under each heading, each one
        # a picture a screen reader is told about, and none of them cut off.
        _, term = get("/terminals")
        strips = re.findall(r'<svg class="art machines[^"]*" viewBox="([^"]+)" '
                            r'role="img"[^>]*aria-label="([^"]+)">(.*?)</svg>',
                            term, re.S)
        check("the terminals page has a drawing for each of its eight sections",
              len(strips) == 8 and all(len(alt) > 40 for _, alt, _ in strips)
              and "art: term-" not in term)
        # The first version ended three strips on their label baseline and
        # the descenders were cut off. A viewBox is arithmetic, so this is
        # checked as arithmetic rather than by looking.
        short = []
        for box, alt, inner in strips:
            _, top, _, height = (float(v) for v in box.split())
            lowest = max((float(y) for y in re.findall(r'<text [^>]*y="([\d.]+)"', inner)),
                         default=0)
            if lowest + 8 > top + height:
                short.append(alt[:30])
        check("and every one leaves room under its lowest label"
              + ("" if not short else "  <- " + " | ".join(short)),
              not short)
        # The drawings' own no-preference block, found from the drawings'
        # stylesheet: the page stylesheet has one of its own now, for the
        # freedoms in the header, and it comes first.
        check("with the bridge's pulse declared where reduced motion stops it",
              "svg.art.bridge .go { animation:" in
              term.split("svg.art { display:block;")[1]
                  .split("@media (prefers-reduced-motion: no-preference) {")[1])

        # The SD card wiring diagram, on /sdcard beside the pin table it
        # draws, and linked from the board table on /build. The diagram and
        # the table on the same page must never disagree about a pin: the
        # labels at each end of a wire are read out of the drawing and
        # compared with the table's rows. Both come from struct SdPins in
        # the firmware, CS 5, MOSI 23, CLK 18, MISO 19.
        _, sd = get("/sdcard")
        wiring = re.search(r'<svg class="art wiring" viewBox="([^"]+)" role="img"'
                           r'[^>]*aria-label="([^"]+)">(.*?)</svg>', sd, re.S)
        check("the SD page carries the wiring diagram, described for a screen reader",
              wiring is not None
              and all(g in wiring.group(2) for g in ("GPIO5", "GPIO18", "GPIO19", "GPIO23")))
        drawn = {}
        if wiring:
            ends = re.findall(r'<text [^>]*x="(97|245)" y="([\d.]+)"[^>]*>([^<]+)</text>',
                              wiring.group(3))
            by_row = {}
            for x, y, label in ends:
                by_row.setdefault(y, {})[x] = label
            drawn = {row["245"]: row["97"] for row in by_row.values()
                     if "97" in row and "245" in row}
        tabled = {m.group(1): m.group(2) for m in re.finditer(
            r"<td><code>(\w+)</code>[^<]*(?:<code>\w+</code>)?</td><td><code>(\w+)</code>",
            sd)}
        want = {"CS": "D5", "MOSI": "D23", "SCK": "D18", "MISO": "D19",
                "VCC": "3V3", "GND": "GND"}
        check("its pins are the firmware's defaults, end to end",
              {k: drawn.get(k) for k in want} == want)
        check("and the table under it says the same",
              all(tabled.get(k) == v for k, v in want.items() if k not in ("VCC",))
              and tabled.get("3V3") == "3V3")
        if wiring:
            _, top, _, height = (float(v) for v in wiring.group(1).split())
            lowest = max(float(y) for y in re.findall(r'<text [^>]*y="([\d.]+)"',
                                                      wiring.group(3)))
        check("with room under its last line",
              wiring is not None and lowest + 8 <= top + height)
        check("and its pulses declared where reduced motion stops them",
              "svg.art.wiring .p-cs { animation:" in
              sd.split("svg.art { display:block;")[1]
                  .split("@media (prefers-reduced-motion: no-preference) {")[1])
        check("the build page's board table links to it",
              '<a href="/sdcard">SD card wiring diagram</a>' in get("/build")[1])

        # A Chromebook, as it is: one you control usually can, a managed one
        # usually cannot without its administrator, Chrome alone never can.
        flat_t = " ".join(term.split())
        check("the Chromebook section leads with who controls it",
              "A Chromebook you control can usually call a board" in flat_t
              and "Chrome on its own never can" in flat_t
              and "A Chromebook can call a board. Chrome cannot." not in flat_t)
        check("and dates the Chrome Apps change the way Google does",
              "ChromeOS 138, in July 2025, was the last release" in flat_t)
        _, data = get("/data", host="data.example")
        check("the health endpoint is not described as two bytes",
              "Two bytes" not in data)

        # Which ESP32. The rule is two cores and Wi-Fi on the chip, from
        # ESP32_BOARD_CHOICE.md, and only the WROOM-32E has been run. The
        # site used to say any module with 4 MB of flash would do, which is
        # true of a C3 with 4 MB of flash and it will not run the board.
        _, build = get("/build")
        flat_b = " ".join(build.split())
        check("the build page says which ESP32s run it",
              "<td>ESP32-WROOM-32E</td><td><b>Yes, tested</b></td>" in build
              and "<td>ESP32-C3</td><td>No</td>" in build
              and "<td>ESP32-P4</td><td>No</td>" in build
              and "Should work, not yet tested" in build)
        check("and gives no caller count for a part nobody has measured",
              "nobody has measured how many" in flat_b)
        check("no page says any 4 MB module will do",
              "Any module with the same flash will do" not in flat_b
              and "Any module with 4 MB of flash works" not in
                  " ".join(get("/teachers")[1].split()))

        # ------------------------------------------------------------------
        # The freedoms beside the wordmark. The board's own words from its
        # welcome screen, on every page, one at a time for a reader who
        # does not mind motion and standing still for one who does.
        print("The freedoms in the header")
        faces = {"the board list": get("/")[1],
                 "a page from the menu": get("/terminals")[1],
                 "the manifesto": man,
                 "the data face": get("/", host="data.example")[1]}

        def ticker_of(page):
            m = re.search(r'<div class="ticker">(.*?)</ul></div>', page, re.S)
            return m.group(1) if m else ""
        wanted = [(label, note) for _key, label, note in S.FREEDOMS]
        labels = [l for l, _n in wanted]
        head_css = faces["the board list"].split("<style>")[1].split("</style>")[0]
        at = head_css.index(".ticker { display:none; }")
        mv = head_css.index("@media (prefers-reduced-motion: no-preference) {", at)
        resting = head_css[at:mv]
        moving = head_css[mv:head_css.index("\n}\n", mv)]
        check("every face carries the panel beside the wordmark",
              all(re.search(r'<div class="masthead"><a class="home" [^>]*><pre class="logo"', p)
                  and ticker_of(p) for p in faces.values()))
        check("with all eight freedoms, each with the line saying what it means",
              len(wanted) == 8
              and all(all(f"<b>{l}</b> <i>{n}</i>" in ticker_of(p)
                          for l, n in wanted) for p in faces.values()))
        check("in one list, named for a screen reader",
              all(ticker_of(p).count("<li>") == 8
                  and '<ul aria-label="Electronic freedom">' in ticker_of(p)
                  for p in faces.values()))
        # The frame, the heading drawn over it and the eight icons. The
        # words are never hidden: the fade is opacity, which leaves every
        # item in the accessibility tree, where visibility would take it out.
        check("and every picture in it hidden from one, and no word",
              all(ticker_of(p).count('aria-hidden="true"') == 10
                  for p in faces.values())
              and "visibility" not in resting and "visibility" not in moving)
        check("the board's own welcome line and licence are among them",
              all(w in labels for w in ("No web", "No cloud", "No browser",
                                        "Real hardware", "GPL v2 or later")))
        check("and nothing on any face runs a script to move them",
              all("<script" not in p for p in faces.values()))

        # Motion lives only inside the no-preference block, so the markup
        # is the resting state: the first freedom, its segment lit.
        check("the panel's motion is declared only where reduced motion stops it",
              "animation" not in resting
              and head_css.count("animation:tk") == moving.count("animation:tk") == 4)
        check("and standing still, it shows the first freedom and lights its segment",
              ".ticker li:first-child { opacity:1; }" in resting
              and ".tf .sg1 { opacity:1; }" in resting
              and re.search(r"\.ticker li \{[^}]*opacity:0; \}", resting) is not None)
        # Eight freedoms, four seconds each: every item's delay is four
        # seconds after the one before, on one 32 second timeline.
        delays = [float(d) for d in re.findall(
            r"\.ticker li:nth-child\(\d\), \.tf \.sg\d \{ animation-delay:(-?[\d.]+)s; \}",
            moving)]
        check("eight on one 32 second timeline, four seconds apart",
              "tkshow 32s" in moving and "tkseg 32s" in moving
              and len(delays) == 8
              and all(abs(b - a - 4) < 1e-9 for a, b in zip(delays, delays[1:])))
        # Each section of the menu opens on a different freedom, or a reader
        # clicking round would only ever see the first two.
        firsts = []
        for path, host in (("/", None), ("/", "about.example"), ("/whofor", None),
                           ("/terminals", None), ("/firstcall", None),
                           ("/build", None), ("/forward", None), ("/how", None)):
            first = re.search(r"<li>.*?<b>(.*?)</b>",
                              ticker_of(get(path, host=host)[1]), re.S)
            firsts.append(first.group(1) if first else None)
        check("and each section of the menu opens on a different one",
              None not in firsts and len(set(firsts)) == 8)

        # No overflow. The panel is not shown until it fits beside the
        # wordmark, and the width at which it fits is arithmetic, not a
        # guess: the wordmark at its cap in the widest font the stack can
        # land on (0.602em a cell, Menlo and DejaVu Sans Mono), the body's
        # padding each side, the gap and the panel, at the 133% root.
        # Measured in headless Chrome as well: nothing past the right edge
        # at 390, 901, 1100, 1168, 1280, 1366 or 1920.
        cap = float(re.search(
            r"pre\.logo \{[^}]*font-size:clamp\([^,]+,[^,]+,\s*([\d.]+)rem\)",
            head_css).group(1))
        panel = float(re.search(r"\.ticker \{ display:block;[^}]*width:([\d.]+)rem",
                                head_css).group(1))
        gap = float(re.search(r"\.masthead \{[^}]*gap:0 ([\d.]+)rem",
                              head_css).group(1))
        shows = float(re.search(r"@media \(min-width: ([\d.]+)em\) \{\s*\.ticker",
                                head_css).group(1))
        cols = max(len(r) for r in S.LOGO_ROWS)
        need = (cols * 0.602 * cap + 2 * 1 + gap + panel) * 1.33
        check("it only appears at a width where it fits beside the wordmark",
              ".ticker { display:none; }" in resting and need <= shows)
        # And the words fit the panel: the text column is the panel less the
        # left inset, the icon, the gap after it and the right inset.
        bsize, bspace = (float(v) for v in re.search(
            r"\.ticker li b \{[^}]*font-size:([\d.]+)rem;[^}]*letter-spacing:([\d.]+)rem",
            head_css).groups())
        isize = float(re.search(r"\.ticker li i \{[^}]*font-size:([\d.]+)rem",
                                head_css).group(1))
        column = panel - 1 - 2.5 - 0.75 - 0.75
        check("and the longest label and line fit its text column",
              max(len(l) for l in labels) * (0.602 * bsize + bspace) <= column
              and max(len(n) for _l, n in wanted) * 0.602 * isize <= column)

        # ------------------------------------------------------------------
        print("The manifest is built from what is on disk")
        import pathlib
        import shutil
        fwroot = tempfile.mkdtemp(prefix="dirfw")
        was_dir = S.FIRMWARE_DIR

        def put(version, chip, names, extra=None):
            d = os.path.join(fwroot, version, chip)
            os.makedirs(d, exist_ok=True)
            for n in names:
                with open(os.path.join(d, n), "w") as fh:
                    fh.write("placeholder, not firmware\n")
            for n, body in (extra or {}).items():
                with open(os.path.join(fwroot, version, n), "w") as fh:
                    fh.write(body)

        whole = ["bootloader.bin", "partitions.bin", "ota_data_initial.bin",
                 "firmware.bin", "storage.bin"]
        put("0.19.2", "esp32", whole,
            {"release.txt": "2026-09-21\nA short note.\n",
             "THIRD_PARTY_NOTICES.md": "notices\n"})
        put("0.19.1", "esp32", whole,
            {"release.txt": "2026-09-01\nimprov: yes\nOlder.\n"})
        put("0.18.0", "esp32", whole)                  # a third, beyond the cap
        put("9.9.9", "esp32", whole[:4])               # storage.bin missing
        put("0.19.2", "esp32x9", whole)                # not a chip family we know
        os.makedirs(os.path.join(fwroot, "NOT-A-RELEASE", "esp32"), exist_ok=True)

        try:
            S.FIRMWARE_DIR = pathlib.Path(fwroot)
            rels = S.firmware_releases()
            check("two releases are offered, newest first",
                  [r["version"] for r in rels] == ["0.19.2", "0.19.1"])
            # Not merely unlisted. A version left on disk past the cap must
            # not be reachable by typing its number either, or "two live"
            # would be a statement about the page and not about the site.
            check("a third on disk is not offered and is not reachable",
                  S.firmware_manifest("0.18.0") is None
                  and S.firmware_file("0.18.0/esp32/firmware.bin") is None)
            # The property the whole design exists for: a release cannot be
            # half-published, because a part is only ever emitted for a file
            # that was just found on disk.
            check("a release missing one part is not offered at all",
                  S.firmware_manifest("9.9.9") is None)

            man = S.firmware_manifest("0.19.2")
            check("the top level is exactly the keys ESP Web Tools reads",
                  set(man) == {"name", "version", "new_install_prompt_erase",
                               "new_install_improv_wait_time", "builds"})
            check("the person is asked before the chip is erased, not after",
                  man["new_install_prompt_erase"] is True)
            check("only the chip families we know about are in it",
                  [b["chipFamily"] for b in man["builds"]] == ["ESP32"])

            # The offsets, read from the firmware repository's partitions.csv
            # and its generated sdkconfig rather than from a tutorial. The
            # bootloader is at 0x1000 because this is an ESP32; an S3 or a C3
            # would be 0x0, which is why it comes from FLASH_FAMILIES.
            parts = man["builds"][0]["parts"]
            check("the parts are the bootloader, the table, otadata, the app and the screens",
                  [p["path"] for p in parts]
                  == ["esp32/bootloader.bin", "esp32/partitions.bin",
                      "esp32/ota_data_initial.bin", "esp32/firmware.bin",
                      "esp32/storage.bin"])
            check("at the offsets the partition table actually uses",
                  [p["offset"] for p in parts]
                  == [4096, 32768, 61440, 131072, 3932160])
            check("under the name the board reports over Improv",
                  man["name"] == "unleashed BBS" and man["version"] == "0.19.2")
            # Their type is `offset: number`, JSON has no hex literal, and a
            # string would be handed to the flasher unparsed. This is the one
            # mistake in the schema that would write a board at the wrong
            # address, so it is pinned as a type and not only as a value.
            check("and every offset is a number, never a hex string",
                  all(isinstance(p["offset"], int) for p in parts))
            check("nothing that is not a version number is mistaken for one",
                  all(re.match(r"^\d+\.\d+\.\d+$", r["version"]) for r in rels))

            # Every release speaks Improv now, and the first boot after an
            # erase formats two filesystems before it answers.
            check("every release waits thirty seconds for the Wi-Fi step",
                  man["new_install_improv_wait_time"] == 30
                  and S.firmware_manifest("0.19.1")["new_install_improv_wait_time"] == 30)
            check("the date and note beside a release are read from it",
                  rels[0]["date"] == "2026-09-21"
                  and rels[0]["note"] == "A short note.")
            check("and an old improv line is skipped, not shown as the note",
                  rels[1]["note"] == "Older.")

            # Names are checked, not paths, the same way static_file does it.
            climbs = ["../server.py", "0.19.2/../../server.py",
                      "0.19.2/esp32/../../../server.py", "0.19.2/esp32/release.txt",
                      "0.19.2/esp32x9/firmware.bin", "", "manifest.json"]
            climbs += ["0.19.2/esp32/littlefs.bin", "0.19.2/release.txt",
                       "0.19.2/manifest.json/x"]
            check("no path under /install/ climbs out of it, or reaches past the five parts",
                  all(S.firmware_file(c) is None for c in climbs))
            got = S.firmware_file("0.19.2/esp32/firmware.bin")
            check("a real part is served as a binary",
                  got is not None and got[1] == "application/octet-stream")
            got = S.firmware_file("0.19.2/manifest.json")
            check("and the manifest as JSON that parses",
                  got is not None
                  and json.loads(got[0].decode())["version"] == "0.19.2")

            shown = S.installer_html()
            check("with an image published the page offers the element",
                  "<esp-web-install-button" in shown
                  and 'manifest="/install/0.19.2/manifest.json"' in shown)
            check("with our own button and both refusal messages in its slots",
                  'slot="activate"' in shown and 'slot="unsupported"' in shown
                  and 'slot="not-allowed"' in shown)
            # "Kept" means a reader can go back to it, which a link to a
            # JSON file never let them do. It is a choice in the card's
            # board slot now, two native radios and no script: the checked
            # one decides which button, version line and notices link show.
            check("the older release is kept as a choice, the newest picked",
                  'manifest="/install/0.19.1/manifest.json"' in shown
                  and shown.count('name="fwver"') == 2
                  and '<input type="radio" name="fwver" id="fwv0" checked> 0.19.2' in shown
                  and ".installer .r1{display:none}" in shown
                  and ".installer:has(#fwv1:checked) .r1{display:block}" in shown
                  and shown.count('slot="unsupported"') == 2)
            # The card said the version three times: on the button, in a
            # line under it, and again as release.txt's first line.
            check("the card says each version once, not on the button",
                  shown.count('class="meta ver r0"') == 1
                  and "Version 0.19.2, released 2026-09-21." in shown
                  and shown.count(">Install on my board</button>") == 2
                  and "Install 0.19.2" not in shown and "A short note." not in shown)
            check("the board slot names the board and its flash",
                  '<p class="meta board">Board: ESP32, 4 MB flash</p>' in shown)
            check("the words inside the block are the card's amber box",
                  '<div class="pre"><p><b>Before you start:</b> x</p></div>'
                  in S.installer_html(["**Before you start:** x"]))
            check("and the licences of what is being installed are linked",
                  "/install/0.19.2/THIRD_PARTY_NOTICES.md" in shown
                  and S.EWT_BASE + "LICENSE" in S.installer_terms_html()
                  and S.EWT_BASE + "THIRD_PARTY_LICENSES.txt" in S.installer_terms_html())

            # The same, end to end, over HTTP: a second server pointed at
            # the scratch releases, so the route, the content types and the
            # page's script tag are tested as a browser meets them.
            print("The installer page, with a release published")
            port2 = PORT + 1
            base2 = f"http://127.0.0.1:{port2}"
            db2 = os.path.join(tempfile.gettempdir(), f"dirtest{os.getpid()}b.db")
            env2 = dict(os.environ, DIRECTORY_PAGE_CACHE="0", DIRECTORY_DB=db2,
                        DIRECTORY_PORT=str(port2), DIRECTORY_FIRMWARE_DIR=fwroot)
            server2 = subprocess.Popen([sys.executable, "server.py"], env=env2,
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT)
            threading.Thread(target=lambda: [None for _ in server2.stdout],
                             daemon=True).start()
            try:
                for _ in range(50):
                    try:
                        fetch("/health", base2)
                        break
                    except Exception:
                        time.sleep(0.1)
                code, ctype, page2 = fetch("/install", base2)
                page2 = page2.decode("utf-8")
                srcs = re.findall(r'<script[^>]*src="([^"]+)"', page2)
                check("the page offers the button, with the module from here",
                      code == 200 and "<esp-web-install-button" in page2
                      and srcs == [S.EWT_SCRIPT])
                # No script from anywhere else, and none written inline.
                check("and no script from any other origin, nor any inline",
                      all(u.startswith("/") and not u.startswith("//") for u in srcs)
                      and page2.count("<script") == len(srcs)
                      and "unpkg" not in page2)
                code, ctype, body = fetch("/install/0.19.2/manifest.json", base2)
                m2 = json.loads(body.decode()) if code == 200 else {}
                check("the manifest is served at /install/<version>/, as JSON",
                      code == 200 and ctype.startswith("application/json")
                      and m2.get("version") == "0.19.2"
                      and [p["offset"] for p in m2["builds"][0]["parts"]]
                          == [4096, 32768, 61440, 131072, 3932160])
                # Each part fetched the way ESP Web Tools does it: relative to
                # the manifest's own URL.
                got = [fetch("/install/0.19.2/" + p["path"], base2)
                       for p in m2.get("builds", [{}])[0].get("parts", [])]
                check("and every part it names comes back, as a binary",
                      len(got) == 5
                      and all(g[0] == 200 and g[1] == "application/octet-stream"
                              for g in got))
                check("while a version past the cap, or not on disk, does not",
                      fetch("/install/0.18.0/manifest.json", base2)[0] == 404
                      and fetch("/install/9.9.9/manifest.json", base2)[0] == 404)
                check("and the bundle is served to this server too",
                      fetch(S.EWT_SCRIPT, base2)[0] == 200)

                # The announcement banner appears by itself when a release
                # of 1.0.0 or later lands, and not a moment before.
                print("The announcement banner")
                home2 = fetch("/", base2)[2].decode("utf-8")
                check("no banner while the newest release is before 1.0.0",
                      'class="banner"' not in home2)
                check("and none on a directory with no release at all",
                      'class="banner"' not in get("/")[1])
                # Absent means absent: the heading follows the menu directly,
                # with no empty box and no margin standing in for one.
                check("and nothing takes its place: the heading follows the menu",
                      '</nav><div class="listtop"><div class="intro"><h1>BBS directory</h1>'
                      in home2
                      and '</nav><div class="listtop">' in get("/")[1])
                check("and the page has no full size button without it either",
                      'class="btn"' not in home2.split("</nav>")[1]
                      and 'class="runcard"' in home2)
                put("1.0.0", "esp32", whole)
                home2 = fetch("/", base2)[2].decode("utf-8")
                bn = (home2.split('<div class="banner"')[1].split("</div>")[0]
                      if '<div class="banner"' in home2 else "")
                check("the banner shows once a 1.0.0 release is on disk",
                      '<div class="banner" role="note"><p>\u00b5nleashed BBS 1.0.0 is out. '
                      '<a href="/install">Install it from your browser.</a></p></div>'
                      in home2)
                check("above the directory heading, straight under the menu",
                      '</nav><div class="banner"' in home2
                      and home2.index('<div class="banner"')
                          < home2.index("<h1>BBS directory</h1>"))
                check("one sentence and one link: no buttons and no drawing",
                      bn.count("<a ") == 1 and "btn" not in bn and "<svg" not in bn
                      and 'class="btn"' not in home2.split("</nav>")[1])
                check("slim: small type, a hairline, a lamp, and nothing animated",
                      ".banner { display:flex; align-items:center;" in home2
                      and "font-size:0.8125rem;" in home2.split(".banner {")[1].split("}")[0]
                      and ".banner::before {" in home2
                      and "bannerled" not in home2)
                # The words live in one constant, so Rob changes them in one
                # place; empty switches the banner off. In-process, where
                # FIRMWARE_DIR is these same scratch releases.
                was_ann = S.ANNOUNCEMENT
                S.ANNOUNCEMENT = "Version {version}, **now**. [Read](/about)"
                one = S.announcement_banner()
                S.ANNOUNCEMENT = "   "
                none_ann = S.announcement_banner()
                S.ANNOUNCEMENT = was_ann
                check("the words come from one constant, the version filled in",
                      one == '<div class="banner" role="note"><p>Version 1.0.0, '
                             '<b>now</b>. <a href="/about">Read</a></p></div>')
                check("and an empty announcement renders nothing at all",
                      none_ann == "")
                # 1.0.0 sorts above 0.19.2, is served, and is what the card
                # offers first, with the one before it kept as the choice.
                rels_1 = S.firmware_releases()
                code, _ct, man1 = fetch("/install/1.0.0/manifest.json", base2)
                inst4 = fetch("/install", base2)[2].decode("utf-8")
                check("a 1.0.0 release is found, served and offered as the newest",
                      [r["version"] for r in rels_1] == ["1.0.0", "0.19.2"]
                      and code == 200 and json.loads(man1.decode())["version"] == "1.0.0"
                      and 'manifest="/install/1.0.0/manifest.json"' in inst4
                      and 'id="fwv0" checked> 1.0.0 (newest)' in inst4)
                # 1.0.0 has no BOOT button reset: that is 1.0.1's.
                check("with 1.0.0 on disk, the BOOT button section still waits",
                      "The BOOT button" not in inst4 and S.ART["boot-button"] not in inst4
                      and "::: from" not in inst4)
                put("1.0.1", "esp32", whole)
                inst5 = fetch("/install", base2)[2].decode("utf-8")
                flat5 = " ".join(inst5.split())
                check("with a release of 1.0.1 or later, the BOOT button shows",
                      "The BOOT button" in inst5 and S.ART["boot-button"] in inst5
                      and "Press and let go of <b>RESET</b>" in flat5
                      and "goes back to the last network that worked" in flat5
                      and "::: from" not in inst5)
            finally:
                server2.terminate()
                try:
                    server2.wait(timeout=5)
                except Exception:
                    server2.kill()
                for leftover in (db2, db2 + "-wal", db2 + "-shm"):
                    try:
                        os.remove(leftover)
                    except OSError:
                        pass
        finally:
            S.FIRMWARE_DIR = was_dir
            shutil.rmtree(fwroot, ignore_errors=True)

        # ------------------------------------------------------------------
        # The last hop of the build pipeline: update.sh fetches the newest
        # GitHub release and installs it. Tested against a release served
        # from 127.0.0.1, never GitHub, with every way it should refuse.
        print("The release fetcher")
        upd = open(os.path.join("deploy", "update.sh"), encoding="utf-8").read()
        check("update.sh runs the fetcher whether or not the site changed",
              "deploy/fetch_release.py" in upd
              and upd.count("\n    fetch_release\n") == 1
              and upd.count("\nfetch_release\n") == 1)
        import hashlib
        import http.server
        relroot = tempfile.mkdtemp(prefix="dirrel")
        dest = tempfile.mkdtemp(prefix="dirdest")
        rel_state = {"tag": "v1.0.0", "missing": None, "tamper": None, "status": 200,
                     "secret": False}

        def make_release():
            d = os.path.join(relroot, "assets")
            shutil.rmtree(d, ignore_errors=True)
            os.makedirs(d)
            files = {}
            for n in ("bootloader.bin", "partitions.bin", "ota_data_initial.bin",
                      "firmware.bin", "storage.bin"):
                body = (n + rel_state["tag"]).encode() * 64
                if n == "storage.bin":
                    body += (b"\nsysop_password = hunter2\n" if rel_state["secret"]
                             else b"\nsysop_password =\ntoken       =    ; only if\n")
                files[n] = body
            files["THIRD_PARTY_NOTICES.md"] = b"notices\n"
            sums = "".join(f"{hashlib.sha256(b).hexdigest()}  {n}\n" for n, b in files.items())
            files["SHA256SUMS"] = sums.encode()
            if rel_state["tamper"]:
                files[rel_state["tamper"]] = files[rel_state["tamper"]] + b"x"
            for n, b in files.items():
                if n != rel_state["missing"]:
                    with open(os.path.join(d, n), "wb") as fh:
                        fh.write(b)

        class Rel(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                port = self.server.server_address[1]
                if self.path == "/releases/latest":
                    if rel_state["status"] != 200:
                        self.send_response(rel_state["status"])
                        self.end_headers()
                        return
                    names = sorted(os.listdir(os.path.join(relroot, "assets")))
                    body = json.dumps({
                        "tag_name": rel_state["tag"],
                        "published_at": "2026-10-01T12:00:00Z",
                        "assets": [{"name": n, "browser_download_url":
                                    f"http://127.0.0.1:{port}/dl/{n}"} for n in names],
                    }).encode()
                elif self.path.startswith("/dl/"):
                    f = os.path.join(relroot, "assets", self.path[4:])
                    if not os.path.isfile(f):
                        self.send_response(404)
                        self.end_headers()
                        return
                    body = open(f, "rb").read()
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        relsrv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Rel)
        threading.Thread(target=relsrv.serve_forever, daemon=True).start()
        relenv = dict(os.environ, UNLEASHED_RELEASE_API=
                      f"http://127.0.0.1:{relsrv.server_address[1]}/releases/latest")

        def run_fetch():
            r = subprocess.run([sys.executable, os.path.join("deploy", "fetch_release.py"),
                                "--dest", dest], env=relenv, capture_output=True,
                               text=True, timeout=60)
            return r.returncode, r.stdout

        def tree(ver):
            d = os.path.join(dest, ver)
            if not os.path.isdir(d):
                return None
            out = {}
            for root, _dirs, fs in os.walk(d):
                for f in fs:
                    p = os.path.join(root, f)
                    out[os.path.relpath(p, d).replace(os.sep, "/")] = open(p, "rb").read()
            return out

        try:
            make_release()
            rc, out = run_fetch()
            t = tree("1.0.0")
            check("a good release is installed where the installer looks",
                  rc == 0 and "Installed firmware 1.0.0" in out and t is not None
                  and all("esp32/" + n in t for n in ("bootloader.bin", "partitions.bin",
                                                      "ota_data_initial.bin", "firmware.bin",
                                                      "storage.bin"))
                  and "THIRD_PARTY_NOTICES.md" in t and "SHA256SUMS" in t
                  and t.get("release.txt") == b"2026-10-01\n")
            # Read by the server exactly as a hand-placed release would be.
            was_fw = S.FIRMWARE_DIR
            S.FIRMWARE_DIR = pathlib.Path(dest)
            try:
                man_f = S.firmware_manifest("1.0.0")
            finally:
                S.FIRMWARE_DIR = was_fw
            check("and the server builds its manifest from it",
                  man_f is not None and len(man_f["builds"][0]["parts"]) == 5)
            rc, out = run_fetch()
            check("a second run changes nothing and says so",
                  rc == 0 and "already installed" in out and tree("1.0.0") == t)

            # Every refusal leaves 1.0.0 exactly as it was.
            rel_state.update(tag="v1.0.1", tamper="firmware.bin")
            make_release()
            rc, out = run_fetch()
            check("a file that does not match SHA256SUMS installs nothing",
                  rc == 1 and "does not match SHA256SUMS" in out
                  and tree("1.0.1") is None and tree("1.0.0") == t)
            rel_state.update(tamper=None, missing="storage.bin")
            make_release()
            rc, out = run_fetch()
            check("nor does a release missing a part",
                  rc == 1 and "missing storage.bin" in out and tree("1.0.1") is None)
            rel_state.update(missing=None, secret=True)
            make_release()
            rc, out = run_fetch()
            check("nor one whose screens carry a password",
                  rc == 1 and "carries a password" in out and tree("1.0.1") is None)
            rel_state.update(secret=False, tag="1.0.1")
            make_release()
            rc, out = run_fetch()
            check("nor one whose tag is not vX.Y.Z",
                  rc == 1 and "not vX.Y.Z" in out and tree("1.0.1") is None)
            rel_state.update(status=404, tag="v1.0.1")
            rc, out = run_fetch()
            check("and a private repository or no release gets a clear message",
                  rc == 1 and "no public release" in out and "private until 1.0.0" in out
                  and tree("1.0.0") == t)
            check("with nothing left behind from any of them",
                  not [n for n in os.listdir(dest) if n.startswith(".")])

            # Newest two are kept.
            rel_state.update(status=200, tag="v1.0.1")
            make_release()
            run_fetch()
            rel_state.update(tag="v1.1.0")
            make_release()
            rc, out = run_fetch()
            kept = sorted(n for n in os.listdir(dest) if re.match(r"^\d+\.\d+\.\d+$", n))
            check("the newest two releases are kept and the older removed",
                  rc == 0 and kept == ["1.0.1", "1.1.0"] and "Removed older releases: 1.0.0" in out)
        finally:
            relsrv.shutdown()
            shutil.rmtree(relroot, ignore_errors=True)
            shutil.rmtree(dest, ignore_errors=True)
        check("fetched releases are kept out of git",
              "/firmware/[0-9]*/" in open(".gitignore", encoding="utf-8").read())

        # The code a visitor runs is the code in this repository, at an
        # exact version, and cannot change between one reader and the next.
        check("ESP Web Tools is pinned to an exact version, served from here",
              re.match(r"^\d+\.\d+\.\d+$", S.EWT_VERSION) is not None
              and S.EWT_SCRIPT == "/install/esp-web-tools/" + S.EWT_VERSION
                                  + "/install-button.js"
              and "unpkg.com" not in open("server.py", encoding="utf-8").read())
        # A release committed here is published the moment Rob deploys, so
        # the one leak this suite can see is checked on every run: the
        # screens image carries data/system.cfg, and a developer's copy has
        # the staff passwords, the Wi-Fi key and the directory token in it.
        # The keys are there, empty, in every clean build; a value is not.
        leaky = []
        secret = re.compile(
            rb"^[ \t]*(sysop_password|cosysop1_password|cosysop2_password|"
            rb"wifi_ssid|wifi_password)[ \t]*=[ \t]*[^\r\n \t]"
            rb"|^[ \t]*token[ \t]*=[ \t]*[^\r\n \t;#]", re.M)
        for rel in sorted(os.listdir("firmware")):
            if not re.match(r"^\d+\.\d+\.\d+$", rel):
                continue
            for chip in sorted(os.listdir(os.path.join("firmware", rel))):
                img = os.path.join("firmware", rel, chip, "storage.bin")
                if os.path.isfile(img) and secret.search(open(img, "rb").read()):
                    leaky.append(rel + "/" + chip)
        check("no release in firmware/ carries a password, a Wi-Fi key or a token"
              + ("" if not leaky else "  <- " + ", ".join(leaky)),
              not leaky)
        # And the scan finds one when there is one to find.
        check("and the check finds one when it is there",
              secret.search(b"x\nsysop_password = hunter2\n") is not None
              and secret.search(b"token       =              ; only if\n") is None
              and secret.search(b"wifi_password =\n") is None)

        # Last, because it uses up everything one address may hold.
        #
        # This is the bug that put ninety rows on the live directory. A board
        # that forgets its token posts as a stranger every time, and the
        # per-address rule only chose what state the new row got before
        # inserting it regardless, so the table grew on every heartbeat with
        # nothing to stop it. Anybody with curl and a loop could do the same.
        print("A board that lost its token can come back")
        # What actually happened to Rob's board. It was reflashed, lost the
        # token, and posted as a stranger. The cap then refused it for ever
        # while telling him "too often, will settle", and settling was the
        # one thing that could not happen. A dead entry gets out of the way.
        import sqlite3
        con = sqlite3.connect(db)
        con.execute("UPDATE boards SET last_seen = last_seen - 86400")   # all gone quiet
        con.commit()
        con.close()
        code, back, _ = post({"name": "The Dead Zone", "owner": "Mercury",
                              "description": "same board, new token", "port": 6400})
        check("it is not refused", code == 200)
        check("and is listed rather than queued behind its own husk",
              back.get("state") in ("pending", "online"))
        # Put the clock back so the checks after this one do not inherit a
        # directory where every board has been quiet for a day.
        con = sqlite3.connect(db)
        con.execute("UPDATE boards SET last_seen = strftime('%s','now')")
        con.commit()
        con.close()

        print("One address cannot fill the table")
        before = json.loads(get("/api/boards.json", host="data.example")[1])["boards"]
        codes = [post({"name": "Forgetful %d" % i, "port": 6400})[0]
                 for i in range(8)]
        after = json.loads(get("/api/boards.json", host="data.example")[1])["boards"]
        check("a board that keeps forgetting its token is refused eventually",
              429 in codes)
        check("nothing it posted reached the published list",
              [b["name"] for b in after] == [b["name"] for b in before])

        badge_checks(S, db)
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
        for leftover in (db, db + "-wal", db + "-shm"):
            if os.path.exists(leftover):
                os.remove(leftover)

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
