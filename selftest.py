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
License:      GNU General Public License v3 or later
SPDX-License-Identifier: GPL-3.0-or-later
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

# The suite's first port. It uses this and the four after it, all on
# 127.0.0.1, one directory each. SELFTEST_PORT moves the lot, for a machine
# where something else already has 8123 (site 1.1.0).
PORT = int(os.environ.get("SELFTEST_PORT", "8123"))
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


# The tables as they stood at site 0.21.1, the last version before the
# interests: the badge columns and the hourly record are there, interests is
# not. The live database is one of these now. Exactly what CREATE TABLE made
# then, copied from 0.21.1's server.py.
OLD_SCHEMA_0211 = """
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
    note         TEXT NOT NULL DEFAULT '',
    tz_offset    INTEGER NOT NULL DEFAULT 0,
    system       TEXT NOT NULL DEFAULT '',
    terminals    TEXT NOT NULL DEFAULT '',
    guests       INTEGER,
    features     TEXT NOT NULL DEFAULT '',
    support      TEXT NOT NULL DEFAULT '',
    tracked_since INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE beathours (
    board_id INTEGER NOT NULL,
    hour     INTEGER NOT NULL,
    beats    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (board_id, hour)
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


# The tables as they stood at site 1.0.0, the last version before the codes
# and the SD card: every badge column but sd. The live database is one of
# these now, its causes and interests stored as the long slugs. Exactly what
# CREATE TABLE made then, copied from 1.0.0's server.py.
OLD_SCHEMA_100 = """
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
    note         TEXT NOT NULL DEFAULT '',
    tz_offset    INTEGER NOT NULL DEFAULT 0,
    system       TEXT NOT NULL DEFAULT '',
    terminals    TEXT NOT NULL DEFAULT '',
    guests       INTEGER,
    features     TEXT NOT NULL DEFAULT '',
    support      TEXT NOT NULL DEFAULT '',
    tracked_since INTEGER NOT NULL DEFAULT 0,
    interests    TEXT NOT NULL DEFAULT ''
);
CREATE TABLE beathours (
    board_id INTEGER NOT NULL,
    hour     INTEGER NOT NULL,
    beats    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (board_id, hour)
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


def start_server(db, port):
    """A directory on its own port and database, its output drained, and
    whether it came up. The caller terminates it."""
    env = dict(os.environ, DIRECTORY_PAGE_CACHE="0", DIRECTORY_DB=db,
               DIRECTORY_PORT=str(port), DIRECTORY_MIN_SECONDS="0")
    proc = subprocess.Popen([sys.executable, "server.py"], env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = []
    threading.Thread(target=lambda: [out.append(l) for l in proc.stdout],
                     daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(60):
        try:
            return proc, out, fetch("/health", base)[0] == 200
        except Exception:
            if proc.poll() is not None:
                break
            time.sleep(0.1)
    return proc, out, False


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


def list_rows(page):
    """Every board row on the list: (name, the badge keys it carries, hidden)."""
    return [(name, keys.split(), bool(hid)) for keys, hid, name in re.findall(
        r'<tr data-b="([^"]*)"( hidden)?><td class=\'name\' data-label=\'Board\'>'
        r"<span class='bname'>([^<]*)</span>", page)]


def pane_of(page):
    """The filter's <details>, from its opening tag to its end. Its rows are
    <details> too since 0.22.2, so the end is the one after its form."""
    at = page.find('<details class="filter"')
    end = "</form></details>"
    return page[at:page.find(end, at) + len(end)] if at >= 0 else ""


def badge_checks(S, db):
    """Site 0.21.0: the badge fields, the badges, the steady record, the
    legend, the zebra rows and the hover, and a database from before."""
    import pathlib
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
            "sd": 32,
            # A code in any case, and two old slugs the codes replaced (site
            # 1.1.0): "CHIPTUNE" and "electronics" are aliases of CHPTN and
            # ELCTR, and have to arrive as those.
            "support": ["ham", "lgbtq", "<script>alert(1)</script>", "HAM", "nazis"],
            "interests": ["CHIPTUNE", "c64", "<b>x</b>", "nazis", 64, None,
                          "electronics", "C64"]}
    junk = {"name": "Junk Fields", "port": 6400, "token": "",
            "system": ["not", "a", "string"], "terminals": "petscii",
            "guests": "yes", "features": {"chat": True}, "support": "lgbtq",
            "interests": "c64", "sd": "32"}
    # Site 1.2.8: a board with a camera running says so in its features.
    shut = {"name": "No Guests", "port": 6400, "token": "", "guests": False,
            "sd": True, "features": ["Camera", "webcam"]}
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
    check("camera is a feature, in any case, and an unknown one beside it is "
          "still ignored",
          listed.get("No Guests", {}).get("features") == ["camera"]
          and "camera" not in bb.get("features", []))
    check("support: known codes only; a made-up one, markup and all, is dropped",
          bb.get("support") == ["lgbtq"])
    # Amateur radio moved from support to the interests (site 0.22.2, Rob:
    # "Amateur radio is not a support cause"), keeping its slug; a board that
    # still sends it as support has it filed with its interests, once.
    check("interests: known codes only, once each, any case, an old slug read as "
          "its code; markup, a number, a null and a made-up one dropped; ham sent "
          "as support filed here",
          bb.get("interests") == ["c64", "elctr", "chptn", "ham"]
          and "ham" not in S.SUPPORT_CODES and "ham" in S.INTEREST_CODES
          and S.SUPPORT_MOVED == ("ham",))
    check("sd: the card's size, a whole number of GB, is kept as a number",
          bb.get("sd") == 32)
    check("a field of the wrong type counts as not sent, and the board is "
          "still listed",
          jb.get("system") == "" and jb.get("terminals") == []
          and jb.get("guests") is None and jb.get("features") == []
          and jb.get("support") == [] and jb.get("interests") == []
          and jb.get("sd") is None and listed.get("No Guests", {}).get("sd", 0) is None)
    check("only the first 16 interests are read",
          S.pick(["x"] * 16 + ["c64"], S.INTEREST_CODES, alias=S.INTEREST_ALIAS) == []
          and S.pick(["x"] * 15 + ["c64"], S.INTEREST_CODES,
                     alias=S.INTEREST_ALIAS) == ["c64"])
    check("about forty interests, each a code with a drawing, a group, a name and "
          "a sentence",
          38 <= len(S.INTERESTS) <= 48
          and len(set(S.INTEREST_CODES)) == len(S.INTEREST_CODES)
          and all(s in S.INTEREST_ART and g in S.INTEREST_GROUPS and n and t.endswith(".")
                  for s, g, n, t in S.INTERESTS)
          and set(S.INTEREST_ART) == set(S.INTEREST_CODES))
    check("and none of them is a support cause or another badge's key",
          not set(S.INTEREST_CODES) & (set(S.SUPPORT_CODES) | {
              k for k, *_ in S.LETTER_BADGES} | {a[1] for a in S.AGES})
          and len(S.FILTER_KEYS) == len(set(S.FILTER_KEYS)))
    # Site 0.22.2 (Rob): the support list grows by volume, to about 25, the
    # first ten unchanged, HIV's ribbon still red while Rob decides. Their
    # codes since site 1.1.0.
    first_ten = ("lgbtq", "trans", "dsbld", "neuro", "mntlh", "scdpv", "vets",
                 "cancer", "hiv", "animal")
    check("about 25 causes, the first ten unchanged, each with its own drawing "
          "and a sentence",
          22 <= len(S.SUPPORT) <= 26 and S.SUPPORT_CODES[:10] == first_ten
          and all(code in S.SUPPORT_ART and name and t.endswith(".")
                  for code, name, t in S.SUPPORT)
          and set(S.SUPPORT_ART) == set(S.SUPPORT_CODES)
          and len(set(S.SUPPORT_ART.values())) == len(S.SUPPORT)
          and 'stroke="#e25a55"' in S.SUPPORT_ART["hiv"]
          and all(s in S.SUPPORT_CODES for s in (
              "brst", "chldc", "dmnta", "carers", "dbts", "heart", "dv", "rcvry",
              "donor", "foster", "hmlss", "hunger", "ltrcy", "frstr")))

    # ----------------------------------------------------------------------
    # Site 1.1.0 (Rob: "like 5 or 6 max", MNTLH for mental health): a short
    # code for every cause and interest, in one file a separate program can
    # read, every earlier slug an alias.
    print("Badge codes")
    table = json.load(open("badges.json", encoding="utf-8"))
    entries = table.get("badges", [])
    check("badges.json is the table: 24 causes and 43 interests, each a code, a "
          "group, a name, a meaning and its aliases, and it says whose it is",
          table.get("format") == 1
          and sum(e["group"] == "support" for e in entries) == 24
          and sum(e["group"] == "interests" for e in entries) == 43
          and all(isinstance(e.get("aliases"), list) and e.get("name") and e.get("means")
                  for e in entries)
          and all(e.get("sub") in table["interest_groups"] for e in entries
                  if e["group"] == "interests")
          and table.get("copyright") == "Copyright 2026 - Robert Mech"
          and table.get("license") == "GPL-3.0-or-later")
    check("and the server's tables are exactly what the file says, nothing left out",
          S.BADGE_CODES_OK
          and list(S.SUPPORT_CODES) == [e["code"] for e in entries if e["group"] == "support"]
          and list(S.INTEREST_CODES) == [e["code"] for e in entries
                                         if e["group"] == "interests"]
          and tuple(table["interest_groups"]) == S.INTEREST_GROUPS
          and sum(len(e["aliases"]) for e in entries) + len(entries)
          == len(S.SUPPORT_ALIAS) + len(S.INTEREST_ALIAS))
    codes = list(S.SUPPORT_CODES) + list(S.INTEREST_CODES)
    check("every code is one to six lower case letters and digits, and no two are "
          "the same",
          all(re.fullmatch(r"[a-z0-9]{1,6}", c) for c in codes)
          and len(set(codes)) == len(codes) and len(codes) == 67)
    check("no code or alias is a word the filter already uses for something else",
          not (set(S.FILTER_ALIAS) & ({k for k, *_ in S.LETTER_BADGES}
                                      | {a[1] for a in S.AGES} | {"update"})))
    # Every slug the site used up to 1.0.0, and the code it became. Typed
    # out here, not read from badges.json, so a slip in the file shows.
    old = {"lgbtq": "lgbtq", "trans": "trans", "disability": "dsbld",
           "neurodiversity": "neuro", "mental-health": "mntlh",
           "suicide-prevention": "scdpv", "veterans": "vets", "cancer": "cancer",
           "hiv": "hiv", "animals": "animal", "breast-cancer": "brst",
           "childhood-cancer": "chldc", "dementia": "dmnta", "caregivers": "carers",
           "diabetes": "dbts", "heart-health": "heart", "domestic-violence": "dv",
           "recovery": "rcvry", "donation": "donor", "foster-adoption": "foster",
           "homelessness": "hmlss", "hunger": "hunger", "literacy": "ltrcy",
           "first-responders": "frstr"}
    old_i = {"bbs-history": "bbs", "linux": "linux", "open-source": "oss",
             "programming": "prgrm", "retrocomputing": "retro", "amiga": "amiga",
             "apple2": "apple2", "atari": "atari", "c64": "c64", "dos": "dos",
             "spectrum": "zx", "3d-printing": "3dprt", "electronics": "elctr",
             "robotics": "robot", "soldering": "solder", "woodworking": "wood",
             "arcade": "arcade", "board-games": "brdgm", "gaming": "games",
             "retro-gaming": "rtrgm", "tabletop-rpg": "rpg", "ansi-art": "ansi",
             "chiptune": "chptn", "demoscene": "demo", "drawing": "draw",
             "music": "music", "photography": "photo", "ham": "ham",
             "astronomy": "astro", "swl": "swl", "weather": "wthr",
             "aviation": "avtn", "cars": "cars", "cooking": "cook", "cycling": "bike",
             "fishing": "fish", "gardening": "garden", "hiking": "hike",
             "model-trains": "trains", "anime": "anime", "books": "books",
             "movies": "movies", "scifi": "scifi"}
    # The interim slugs proposed on the way to the codes, none of which
    # shipped, accepted all the same.
    interim = {"access": "dsbld", "mental": "mntlh", "lifeline": "scdpv",
               "hope": "scdpv", "animal": "animal", "bcancer": "brst",
               "breast": "brst", "ccancer": "chldc", "kidca": "chldc",
               "memory": "dmnta", "diabet": "dbts", "sober": "rcvry",
               "homeless": "hmlss", "homes": "hmlss", "read": "ltrcy",
               "1stresp": "frstr", "rescue": "frstr"}
    interim_i = {"code": "prgrm", "3dprint": "3dprt", "3d": "3dprt", "elec": "elctr",
                 "robots": "robot", "boardgm": "brdgm", "meeple": "brdgm",
                 "retrogm": "rtrgm", "retrog": "rtrgm", "ansiart": "ansi",
                 "chip": "chptn", "wx": "wthr", "fly": "avtn"}
    sup_ok = [w for w, c in list(old.items()) + list(interim.items())
              if S.pick([w, w.upper(), w.replace("-", "")], S.SUPPORT_CODES,
                        alias=S.SUPPORT_ALIAS) != [c]]
    int_ok = [w for w, c in list(old_i.items()) + list(interim_i.items())
              if S.pick([w.upper()], S.INTEREST_CODES, alias=S.INTEREST_ALIAS) != [c]
              or S.pick([w.replace("-", "")], S.INTEREST_CODES,
                        alias=S.INTEREST_ALIAS) != [c]]
    check("every old slug, with or without its hyphens, and every interim one is "
          "read as its code, in any case"
          + ("" if not (sup_ok or int_ok) else "  <- " + ", ".join(sup_ok + int_ok)),
          not sup_ok and not int_ok and len(old) == 24 and len(old_i) == 43)
    check("so are a code in capitals and a name typed with its spaces",
          S.pick(["MNTLH"], S.SUPPORT_CODES, alias=S.SUPPORT_ALIAS) == ["mntlh"]
          and S.pick(["Mental health"], S.SUPPORT_CODES, alias=S.SUPPORT_ALIAS) == ["mntlh"]
          and S.pick(["  ElCtR "], S.INTEREST_CODES, alias=S.INTEREST_ALIAS) == ["elctr"])
    fq_bad = [w for w, c in list(old.items()) + list(old_i.items())
              + list(interim.items()) + list(interim_i.items())
              if S.filter_query("b=" + w.upper())[0] != (c,)]
    check("and in a filter link, ?b=electronics finds what is ELCTR now"
          + ("" if not fq_bad else "  <- " + ", ".join(fq_bad)),
          not fq_bad and S.filter_query("b=MNTLH&b=Chiptune&b=petscii")[0]
          == ("petscii", "mntlh", "chptn"))
    check("a word one list knows is not a badge in the other",
          S.pick(["mntlh", "hope"], S.INTEREST_CODES, alias=S.INTEREST_ALIAS) == []
          and S.pick(["elctr", "c64"], S.SUPPORT_CODES, alias=S.SUPPORT_ALIAS) == [])

    # The loader keeps what it can: a bad entry or a taken alias is left out
    # with a line in the journal, and a missing file is no causes at all
    # rather than a server that will not start.
    was_file = S.BADGE_FILE
    bad_file = os.path.join(tempfile.gettempdir(), f"badges{os.getpid()}.json")
    with open(bad_file, "w", encoding="utf-8") as fh:
        json.dump({"interest_groups": ["G"], "badges": [
            {"code": "good", "group": "support", "name": "Good", "means": "Fine.",
             "aliases": ["Nice-One", "chat"]},
            {"code": "toolong", "group": "support", "name": "X", "means": "X.",
             "aliases": []},
            {"code": "dupe", "group": "interests", "sub": "G", "name": "D",
             "means": "D.", "aliases": ["niceone", "dupes"]},
            {"code": "nosub", "group": "interests", "name": "N", "means": "N.",
             "aliases": []},
            {"code": "mail", "group": "support", "name": "P", "means": "P.",
             "aliases": []},
            {"code": "str", "group": "support", "name": "S", "means": "S.",
             "aliases": "abc"}]}, fh)
    try:
        S.BADGE_FILE = pathlib.Path(bad_file)
        got_b = S._badge_codes()
        S.BADGE_FILE = pathlib.Path(bad_file + ".missing")
        got_m = S._badge_codes()
    finally:
        S.BADGE_FILE = was_file
        os.remove(bad_file)
    check("a bad entry, a taken alias and a filter word are left out, the rest "
          "kept, and aliases that are not a list are no aliases, not letters",
          got_b[0] == (("good", "Good", "Fine."), ("str", "S", "S."))
          and got_b[1] == (("dupe", "G", "D", "D."),)
          and got_b[3] == {"good": "good", "niceone": "good", "str": "str"}
          and got_b[4] == {"dupe": "dupe", "dupes": "dupe"} and got_b[6] is True)
    check("and a missing file is no causes and no interests, not a crash",
          got_m[0] == () and got_m[1] == () and got_m[6] is False)
    # With no table the heartbeat must not write the stored causes away:
    # every board would lose its badges to one missing file.
    mem_db = os.path.join(tempfile.gettempdir(), f"dirnotab{os.getpid()}.db")
    was_db, was_ok = S.DB_PATH, S.BADGE_CODES_OK
    try:
        S.DB_PATH = mem_db
        S.setup()
        _st, first, _h = S.announce({"name": "Kept", "port": 6400, "token": "",
                                     "support": ["mntlh"], "interests": ["c64"]},
                                    "192.0.2.90")
        S.BADGE_CODES_OK = False
        # From another address, so the rate limit (30 s in this process)
        # cannot be what left the row alone.
        st2, _b, _h = S.announce({"name": "Kept", "port": 6400, "token": first["token"],
                                  "support": [], "interests": []}, "192.0.2.91")
        con_n = sqlite3.connect(mem_db)
        kept = con_n.execute("SELECT support, interests FROM boards").fetchone()
        con_n.close()
    finally:
        S.DB_PATH, S.BADGE_CODES_OK = was_db, was_ok
        for leftover in (mem_db, mem_db + "-wal", mem_db + "-shm"):
            try:
                os.remove(leftover)
            except OSError:
                pass
    check("and with no table a heartbeat leaves the stored causes and interests alone",
          st2 == 200 and kept == ("mntlh", "c64"))
    check("and the support drawings keep to the house style too",
          all(not re.search(r"\sid=|<script|<text|on\w+=|href", a)
              for a in S.SUPPORT_ART.values()))
    check("the drawings keep to the house style: no ids, no scripts, no text, "
          "colour from the chip",
          all(not re.search(r"\sid=|<script|<text|on\w+=|href", a)
              for a in S.INTEREST_ART.values())
          and all("stroke=\"#" not in a for a in S.INTEREST_ART.values()))
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
    page = get("/directory")[1]
    row = badge_row(page, "Badge Board")
    found = badges_in(row)
    check("the name has a box of its own, the width of the name",
          "<td class='name' data-label='Board'><span class='bname'>Badge Board</span>"
          "<span class=\"badges\">" in page)
    # Site 1.0.0 (Rob: "The unleashed and esp32 should be upfront ... that
    # way they look consistent when scrolling"): the software with its
    # version, then the machine, on a row of their own; then the small
    # badges in a fixed order, PETSCII, guests, the features as C M F Fi D,
    # then new or steady and time listed.
    check("the software with its version and the machine first, then the rest in "
          "their fixed order, the SD card with its size after what is running",
          found == [("soft", "unleashed 1.0.0"),
                    ("sys", "Compaq 486 &lt;b&gt;&amp;&lt;/b&gt;"),
                    ("term", "P"), ("guest", "G"), ("feat", "C"), ("feat", "Fi"),
                    ("feat", "D"), ("feat", "SD32"), ("new", "N")])
    check("the SD card's tooltip says its size",
          'aria-label="SD card: 32 GB, in use on the board now."' in row)
    ident = (row.split('<span class="bid">')[1].split('<span class="bset">')[0]
             if '<span class="bid">' in row else "")
    check("on two rows: what the board is, and the small badges under it",
          row.count('<span class="bid">') == 1 and row.count('<span class="bset">') == 1
          and row.index('<span class="bid">') < row.index('<span class="bset">')
          and badges_in(ident) == [("soft", "unleashed 1.0.0"),
                                   ("sys", "Compaq 486 &lt;b&gt;&amp;&lt;/b&gt;")])
    check("its tooltip says the software and the version, as the board sent them",
          'aria-label="Software: unleashed 1.0.0, as the board reports it."' in row)
    check("each feature that is not running has no badge",
          ("feat", "F") not in found and ("feat", "M") not in found)
    check("then its support symbol, drawn not typed; ham is not a cause any more",
          row.count('class="bd k-sup"') == 1
          and 'aria-label="Supports LGBTQ+ people.' in row
          and "Supports amateur radio" not in row
          and row.split('<span class="bset">')[-1].count(
              "<svg viewBox=\"0 0 24 24\" aria-hidden=\"true\"") == 5)
    labels = re.findall(r'class="bd k-int"[^>]*aria-label="Interest: ([^."]+)\.', row)
    check("then the four interests, in rose, alphabetical by name across their "
          "groups, after the causes",
          labels == ["Amateur radio", "Chiptune", "Commodore 64", "Electronics"]
          and row.rindex('class="bd k-sup"') < row.index('class="bd k-int"'))
    check("the row carries every badge it has for the filter, in the page's order",
          re.search(r'<tr data-b="([^"]*)"><td class=\'name\' data-label=\'Board\'>'
                    r"<span class='bname'>Badge Board</span>", page) is not None
          and re.search(r'<tr data-b="([^"]*)"><td class=\'name\' data-label=\'Board\'>'
                        r"<span class='bname'>Badge Board</span>", page).group(1)
          == "chat doors files guests petscii sd new lgbtq c64 elctr chptn ham")
    # Site 1.2.8 (Rob): "This BBS can take pictures".
    cam_row = badge_row(page, "No Guests")
    check("a board sending camera carries the camera badge, drawn, in the "
          "features' blue, with Rob's sentence",
          '<span class="bd k-feat" role="img" tabindex="0" aria-label="This BBS can '
          'take pictures." data-tip="This BBS can take pictures.">' + S.CAMERA_SVG
          + "</span>" in cam_row)
    check("and a board that does not send it has none",
          "This BBS can take pictures" not in row and S.CAMERA_SVG not in row)
    check("nothing a board sent reaches the page unescaped",
          "<b>&</b>" not in page and "<script>alert" not in page
          and 'data-tip="Runs on: Compaq 486 &lt;b&gt;&amp;&lt;/b&gt;, in the '
              "board&#x27;s own words.\"" in row)
    n = row.count('class="bd ')
    # The update arrow, if this checkout's firmware/ holds a release newer
    # than the 1.0.0 the board sends, is a link with a tooltip of its own.
    arrow = row.count('class="bu"')
    check("every badge carries a tooltip, a name for a screen reader, and a "
          "focus stop for a keyboard or a tap",
          n == 14 and row.count("data-tip=\"") == n + arrow
          and row.count("aria-label=\"") == n + arrow
          and row.count('tabindex="0"') == n and row.count('role="img"') == n)
    check("and no title, which would draw the browser's tooltip over ours",
          " title=" not in row.split("<span class='desc'>")[0])
    check("a PETSCII board's badge says what it means",
          'aria-label="PETSCII: a Commodore 64 or 128 gets colour and graphics '
          'here, not just text."' in row)
    jrow = badge_row(page, "Junk Fields")
    check("a board that sent nothing usable shows only what the directory "
          "worked out", badges_in(jrow) == [("new", "N")])
    check("and with nothing for the first row it has no first row, not an empty one",
          '<span class="bid">' not in jrow and jrow.count('<span class="bset">') == 1)
    check("the tooltip is CSS, drawn from data-tip, on hover and on focus",
          "content:attr(data-tip);" in page
          and ".bd:hover::after, .bd:focus::after, .bu:hover::after, .bu:focus::after {\n"
              "        visibility:visible; opacity:1; }" in page
          and "data-tip" not in S.BADGE_JS and "::after" not in S.BADGE_JS)
    check("at the page's own type size, and never wider than a phone",
          "font-size:0.875rem; line-height:1.45;" in page
          and "max-width:min(24rem, calc(100vw - 3rem));" in page)
    check("badges wrap under the name rather than pushing the Dial column, "
          "each row positioned so a phone's tooltip hangs from it",
          ".badges { display:flex; flex-direction:column;" in page
          and ".badges > .bid, .badges > .bset { position:relative; display:flex; "
              "flex-wrap:wrap;" in page
          and "main > table { table-layout:fixed; }" in page)
    keylink = '<p class="keylink"><a href="/badges">What the badges mean</a></p>'
    check("a small key to them sits right above the table, beside the Filter "
          "button",
          keylink in page and page.index('<div class="fbar">') < page.index(keylink)
          < page.index('<table id="boards">'))
    feet = {"list": page, "about": get("/", host="about.example")[1]}
    check("and the footer links the legend on every face",
          '<a href="/badges">Badges</a>' in feet["list"].split("<footer>")[1]
          and '<a href="https://boards.example/badges">Badges</a>'
          in feet["about"].split("<footer>")[1])
    check("the JSON says what the board runs and which version (site 1.0.0)",
          bb.get("software") == "unleashed" and bb.get("version") == "1.0.0"
          and jb.get("software") == "" and jb.get("version") == "")
    feed = get("/feed.xml")[1]
    check("the feed says it in words, escaped for XML",
          "Software: unleashed 1.0.0" in feed
          and "Runs on: Compaq 486 &amp;lt;b&amp;gt;&amp;amp;&amp;lt;/b&amp;gt;" in feed
          and "Supports: LGBTQ+ people" in feed
          and "Interests: Commodore 64, Electronics, Chiptune, Amateur radio" in feed
          and "SD card: 32 GB" in feed
          and "Speaks: ANSI, PETSCII" in feed and "Guests welcome" in feed
          and "No guests: an account is needed" in feed)

    # ----------------------------------------------------------------------
    # Site 0.22.0 (Rob): a Filter button over the list, a pane of every
    # badge that opens with no script, and the server filtering on ?b=.
    print("The filter over the board list")
    home = get("/directory")[1]
    pane = pane_of(home)
    check("there is a Filter button, a <details>, closed by default",
          '<details class="filter" id="filter"><summary>Filter' in home
          and home.count('<details class="filter"') == 1)
    check("and every badge's symbol is inside it, none outside",
          pane.count('class="chip"') == len(S.FILTER_KEYS)
          and home.count('class="chip"') == pane.count('class="chip"')
          and home.count('<span class="cb ') == pane.count('<span class="cb '))
    # Site 0.22.2 (Rob: "the filter page is unmanageable, it needs HUGE
    # condensing ... the hover works, just put em in groups"): a chip is the
    # symbol and nothing else, its name in the tooltip and as the
    # checkbox's accessible name, never printed under it.
    chips = re.findall(r'<label class="chip" data-k="[^"]*"><input type="checkbox" '
                       r'name="b" value="([^"]+)" data-n="([^"]*)" aria-label="([^"]*)"'
                       r'(?: checked)?><span class="cb k-\w+" data-tip="([^"]+)">', pane)
    check("each chip is its symbol only: the name is its accessible name and its "
          "tooltip, not text under it",
          len(chips) == len(S.FILTER_KEYS)
          and all(n == a and t for _k, n, a, t in chips)
          and 'class="tn"' not in pane and 'class="tile"' not in pane
          and 'data-tip="PETSCII: a Commodore 64 or 128' in pane
          and 'data-tip="Listed a month or more."' in pane
          and 'data-tip="Supports LGBTQ+ people. Code LGBTQ."' in pane
          and 'data-tip="Interest: Electronics. Code ELCTR."' in pane
          and 'value="sd" data-n="SD card"' in pane
          and 'value="camera" data-n="Camera"' in pane
          and '<span class="cb k-feat" data-tip="This BBS can take pictures.">'
              + S.CAMERA_SVG in pane)
    check("the pane is a GET form of checkboxes, one per badge, in the page's "
          "order, with all or any beside them",
          '<form class="fpane" id="fform" method="get" action="/directory"' in pane
          and re.findall(r'<input type="checkbox" name="b" value="([^"]+)"', pane)
          == list(S.FILTER_KEYS)
          and '<input type="radio" name="m" value="all" checked>' in pane
          and '<input type="radio" name="m" value="any">' in pane
          and '<button type="submit">Show boards</button>' in pane)
    check("grouped as on /badges, a row each: the board's own, worked out here, "
          "support, then a heading and a row per group of interests",
          re.findall(r'<details class="fr[^"]*" data-g open><summary>(.*?)</summary>', pane)
          == ["Sent by the board", "Worked out here", "Support"]
             + [html.escape(g) for g in S.INTEREST_GROUPS]
          and re.findall(r"<legend>(.*?)</legend>", pane) == ["Boards with"]
          and '<div class="fint" data-g><p class="fh">Interests</p><div class="fsub">'
              in pane
          and pane.count('<details class="fr sub" data-g open>') == len(S.INTEREST_GROUPS))
    check("its search is labelled, and hidden until the script can drive it",
          '<p class="findbar" data-js hidden><label for="fq">Find a badge</label>'
          '<input type="search" id="fq" data-find="#fgrid"' in pane
          and 'name="q"' not in pane)
    rows = list_rows(home)
    check("with nothing chosen every board is shown, and the line under the "
          "button is hidden",
          rows and not any(h for _n, _k, h in rows)
          and '<p class="factive" id="factive" aria-live="polite" hidden>' in home
          and '<table id="boards">' in home and '<p class="none" id="fnone" hidden>' in home)

    code, one = get("/?b=PETSCII")
    rows1 = list_rows(one)
    shown1 = [n for n, _k, h in rows1 if not h]
    check("?b=petscii shows only boards carrying it, any case, and hides the rest",
          code == 200 and "Badge Board" in shown1 and "Junk Fields" not in shown1
          and all(("petscii" in k) != h for _n, k, h in rows1))
    check("its chip is ticked, the button counts one, and the line says how "
          "many of how many",
          'value="petscii" data-n="PETSCII" aria-label="PETSCII" checked>' in one
          and '<span class="fc" id="fcount">1</span>' in one
          and f'<span data-f="n">{len(shown1)} of {len(rows1)} board' in one
          and '<span data-f="m">all of</span>: <span data-f="l">PETSCII</span>. '
              '<a href="/directory" data-clear>Clear</a>' in one
          and '<p class="factive" id="factive" aria-live="polite">' in one)
    check("and the pane stays closed, so the page is the filtered list",
          '<details class="filter" id="filter"><summary>' in one
          and '<details class="filter" id="filter" open' not in one)
    both = list_rows(get("/?b=petscii&b=ham")[1])
    check("several badges: all of them by default",
          "Badge Board" in [n for n, _k, h in both if not h]
          and all(("petscii" in k and "ham" in k) != h for _n, k, h in both))
    code, none_all = get("/?b=petscii&b=gaming")
    check("nothing with all of them: the table goes and a sentence says so",
          code == 200 and all(h for _n, _k, h in list_rows(none_all))
          and '<table id="boards" hidden>' in none_all
          and '<p class="none" id="fnone">No board with all of those yet.</p>' in none_all)
    any_ = get("/?b=petscii&b=gaming&m=any")[1]
    rows_any = list_rows(any_)
    check("any of them, with m=any: the same two now find a board",
          "Badge Board" in [n for n, _k, h in rows_any if not h]
          and all(("petscii" in k or "gaming" in k) != h for _n, k, h in rows_any)
          and '<input type="radio" name="m" value="any" checked>' in any_
          and '<span data-f="m">any of</span>' in any_
          and '<p class="none" id="fnone" hidden>No board with any of those yet.</p>'
          in any_)
    # Site 1.1.0: the codes in any case, and the old slugs a link may carry.
    q_bad = []
    for q in ("/?b=ELCTR&b=chptn", "/?b=electronics&b=Chiptune", "/?b=Elctr&b=chip"):
        got_q = get(q)[1]
        rq = list_rows(got_q)
        if not ("Badge Board" in [n for n, _k, h in rq if not h]
                and all(("elctr" in k and "chptn" in k) != h for _n, k, h in rq)
                and 'value="elctr" data-n="Electronics" aria-label="Electronics" checked>'
                in got_q
                and 'value="chptn" data-n="Chiptune" aria-label="Chiptune" checked>'
                in got_q
                and '<span data-f="l">Electronics, Chiptune</span>' in got_q
                and "electronics&" not in got_q.split("<form")[0]):
            q_bad.append(q)
    check("a code in any case, or the old slug it replaced, filters the same and "
          "ticks the same chips" + ("" if not q_bad else "  <- " + ", ".join(q_bad)),
          not q_bad)
    sd_rows = list_rows(get("/?b=sd")[1])
    check("and ?b=sd finds the boards with an SD card in use",
          [n for n, _k, h in sd_rows if not h] == ["Badge Board"]
          and all(("sd" in k) != h for _n, k, h in sd_rows))
    check("a slug this directory does not know is ignored",
          list_rows(get("/?b=petscii&b=nazis")[1]) == rows1
          and not any(h for _n, _k, h in list_rows(get("/?b=nazis")[1]))
          and "checked>" not in pane_of(get("/?b=nazis")[1]).replace(
              'value="all" checked>', ""))
    code, evil = get("/?b=%3Cscript%3Ealert(1)%3C%2Fscript%3E&b=%22%3E%3Cimg%20src%3Dx%3E"
                     "&m=%22%3E%3Cx&b=" + "petscii" * 200)
    check("and nothing typed into the address is put back on the page",
          code == 200 and "alert(1)" not in evil and "<img src=x" not in evil
          and '"><x' not in evil and "petsciipetscii" not in evil
          and not any(h for _n, _k, h in list_rows(evil)))
    # Site 1.2.8: a filter is answered on /directory, so that is its page.
    check("a filtered view is still the whole directory to a search engine",
          '<link rel="canonical" href="https://boards.example/directory">' in one)
    check("the rows the filter leaves out stay hidden at every width, and the "
          "stripes count only the rows showing",
          "main [hidden] { display:none !important; }" in home
          and "main > table tr:not(:first-child):nth-child(odd of :not([hidden])) "
              "{ background:#111116; }" in home)
    css_f = home.split("<style>")[1].split("</style>")[0]
    check("a chosen chip shows a ring and a notch in its corner, not only a "
          "colour; focus is the yellow ring",
          ".chip input:checked + .cb { border-color:var(--dial); box-shadow:0 0 0 "
          "0.125rem var(--dial);" in css_f
          and "background-image:linear-gradient(225deg, var(--dial) 0.3125rem, "
              "transparent 0.3125rem); }" in css_f
          and ".chip input:focus-visible + .cb { outline:3px solid #ffd35c;" in css_f
          and ".fmode input:checked + span { background:var(--ink);" in css_f)
    check("a chip is small: the size of a badge on the list, give or take",
          "min-width:1.625rem; height:1.625rem;" in css_f
          and ".chips { display:flex; flex-wrap:wrap; gap:0.25rem; }" in css_f)
    check("its name is the badge tooltip, shown on hover and on focus, hung from "
          "the row so none can push the page sideways, and not drawn until wanted",
          ".cb::after { content:attr(data-tip); position:absolute; left:0;" in css_f
          and "z-index:6; display:none;" in css_f
          and ".chip:hover .cb::after, .chip input:focus + .cb::after { display:block; }"
              in css_f
          and ".fr { position:relative; display:flow-root;" in css_f)
    hov = css_f[css_f.index("@media (hover: hover) and (pointer: fine) {\n  details.filter"):]
    hov = hov[:hov.index("\n}\n")]
    check("a hovered chip lights its edge only where a pointer hovers",
          ".chip:hover .cb {" in hov and css_f.count(".chip:hover .cb {") == 1)
    check("the pane settles in only where motion is wanted",
          css_f.count("animation:panein") == 1
          and css_f.index("animation:panein") > css_f.index(
              "@media (prefers-reduced-motion: no-preference) {\n  details.filter[open]"))
    check("on a desktop a row's name is a column and the interests go two rows "
          "to a line; on a phone the name is a heading to tap",
          "  .fr > summary { float:left; width:10.5rem; }" in css_f
          and ".fsub { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr));"
              in css_f
          and "  .fr > summary { line-height:2rem; }" in css_f
          and ".fr:not([open]) > summary::after { transform:rotate(-45deg);" in css_f
          and not any(w in css_f for w in (".tile", ".tbox", ".bento", ".fg ")))
    check("and a search opens a folded row that has a match",
          "if(w.length&&!g.hidden&&g.tagName==='DETAILS')g.open=true;" in S.BADGE_JS)

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
    row = badge_row(get("/directory")[1], "Badge Board")
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
          ("steady", "S") not in badges_in(badge_row(get("/directory")[1], "Badge Board")))
    con.execute("UPDATE beathours SET beats=60 WHERE board_id=?", (bid,))
    con.commit()
    check("and a burst of extra heartbeats in the other hours cannot buy it back",
          ("steady", "S") not in badges_in(badge_row(get("/directory")[1], "Badge Board")))
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
              for _k, letters, cls, name, _m in S.LETTER_BADGES if letters))
    check("the camera is on it too, drawn, with how a caller uses it linked",
          "<b>Camera</b>" in leg and S.CAMERA_SVG in leg
          and "<code>camera</code> <span class='src'>in features</span>" in leg
          and 'downloads it a few seconds later. Running now. '
              '<a href="/camera">How a caller uses it</a>.' in leg)
    check("and the machine, the software and every time-listed step",
          "<b>Machine</b>" in leg and "<b>Software</b>" in leg
          and all(f">{label}</span>" in leg for _d, label, _w in S.AGES))
    # Site 0.22.0: a searchable table per group, each row the symbol, the
    # name, the slug and the meaning.
    trs = re.findall(r'<tr data-k="([^"]*)"><td class="bsym">.*?</tr>', leg, re.S)
    check("a table per group, each row the badge, its name, what a board sends "
          "and its meaning, under four headings: the field for the first two, "
          "the code for the causes and the interests",
          leg.count('<table class="btab ') == 4
          and leg.count('<th scope="col">Badge</th><th scope="col">Name</th>'
                        '<th scope="col">Sent as</th><th scope="col">Meaning</th>') == 2
          and leg.count('<th scope="col">Badge</th><th scope="col">Name</th>'
                        '<th scope="col">Code</th><th scope="col">Meaning</th>') == 2
          and "Slug</th>" not in leg
          and all(has_h(leg, 2, t) for _g, t in S.BADGE_GROUPS)
          and has_h(leg, 3, "How steady is worked out")
          and 'href="#how-steady-is-worked-out"' in leg)
    check("every row is on the page with no script: one per badge, the steps "
          "of Listed sharing one",
          len(trs) == len(S.BADGES) - 5 == 82
          and '<tr data-k="' in leg and " hidden>" not in leg.split("</nav>")[1]
          .replace("data-js hidden>", ""))
    check("each says where it comes from: the field a board sends, or worked "
          "out here",
          leg.count("none: worked out here") == 4
          and "<code>petscii</code> <span class='src'>in terminals</span>" in leg
          and "<code>chat</code> <span class='src'>in features</span>" in leg
          and "<code>sd</code> <span class='src'>its size in GB</span>" in leg)
    check("the SD card is in the legend, in the features' blue, and says the size "
          "rides on the badge",
          "<b>SD card</b>" in leg and "SD32 is a 32 GB card." in leg
          and 'class="bd k-feat" role="img" tabindex="0" aria-label="SD card: ' in leg)
    # Site 1.0.0: a µnleashed board behind the newest release. On a row it
    # is an arrow on the software badge; here and in the filter, a badge.
    check("Update available is in the legend, in dim cyan, and a chip in the filter",
          "<b>Update available</b>" in leg
          and '<span class="cn k-upd">dim cyan</span>' in leg
          and 'class="bd k-upd"' in leg and S.UP_ARROW in leg
          and 'value="update"' in pane and "update" in S.FILTER_KEYS
          and "<b>Software</b>" in leg and ">unleashed 1.0.0</span>" in leg)
    check("then Show your support: every symbol, its code in capitals and its "
          "sentence",
          all(f"<code>{code.upper()}</code>" in leg and html.escape(sentence) in leg
              for code, _n, sentence in S.SUPPORT)
          and "<code>MNTLH</code>" in leg
          and "<code>mental-health</code>" not in leg.split(
              '<table class="btab support">')[1].split("</table>")[0]
          and leg.count('class="bd k-sup"') == 24 and len(S.SUPPORT) == 24)
    check("each support code is short enough to type on a C64",
          all(re.fullmatch(r"[a-z0-9]{1,6}", s) for s in S.SUPPORT_CODES)
          and len(set(S.SUPPORT_CODES)) == len(S.SUPPORT_CODES))
    check("every cause has its drawing",
          all(code in S.SUPPORT_ART for code, _n, _t in S.SUPPORT))
    check("then the interests: every one, its code in capitals and its sentence, "
          "in rose, under its own group",
          all(f"<code>{code.upper()}</code>" in leg and html.escape(t) in leg
              for code, _g, _n, t in S.INTERESTS)
          and leg.count('class="bd k-int"') == len(S.INTERESTS)
          and [html.unescape(g) for g in re.findall(
              r'<tr class="sub"><th colspan="4" scope="rowgroup">([^<]*)</th></tr>', leg)]
          == list(S.INTEREST_GROUPS)
          and leg.count("<tbody data-g>") == len(S.INTEREST_GROUPS))
    check("the legend's badges have tooltips too",
          'data-tip="Supports LGBTQ+ people."' in leg
          and 'data-tip="Interest: Amateur radio."' in leg
          and 'data-tip="Interest: Commodore 64."' in leg)
    check("its search is labelled, hidden until the script can drive it, and "
          "says how many rows it leaves",
          '<p class="findbar" data-js hidden><label for="bq">Find a badge</label>'
          '<input type="search" id="bq" data-find="article"' in leg
          and '<span class="fqn" id="bqn" aria-live="polite"></span>' in leg
          and all(w == w.lower() for w in trs)
          and any("amateur radio" in w and "ham" in w for w in trs)
          and any("commodore 64" in w and "c64" in w for w in trs))
    check("and finds a cause or an interest by its code or by the old slug, with "
          "or without its hyphens",
          any(w.split()[:2] == ["mental", "health"] and " mntlh " in f" {w} "
              and "mental-health" in w and "mentalhealth" in w for w in trs)
          and any("electronics" in w and " elctr " in f" {w} " for w in trs)
          and any("3d-printing" in w and "3dprt" in w and "3d printing" in w
                  for w in trs))

    # One order everywhere (Rob): alphabetical by the name a reader sees,
    # within each group, a leading digit or symbol set aside, and the three
    # views read it from the one list rather than each sorting for itself.
    in_order = True
    for group, _t in S.BADGE_GROUPS:
        subs = S.INTEREST_GROUPS if group == "interests" else ("",)
        for sub in subs:
            keys = [b["sort"] for b in S.BADGES if b["group"] == group and b["sub"] == sub]
            in_order = in_order and keys == sorted(keys)
    check("BADGES is alphabetical by name within every group and sub-group",
          in_order and S.sort_key("3D printing") == "d printing"
          and S.sort_key("Listed ten years") == "listed ten years"
          and [b["name"] for b in S.BADGES if b["group"] == "support"][:2]
          == ["Addiction recovery", "Animal welfare"]
          and [b["name"] for b in S.BADGES if b["sub"] == "Radio and sky"][0]
          == "Amateur radio")
    want = []
    for b in S.BADGES:
        name = "Listed" if b["cls"] == "age" else b["name"]
        if not want or want[-1] != name:
            want.append(name)
    got_leg = [html.unescape(n) for n in re.findall(r'<td class="bn"><b>([^<]*)</b>', leg)]
    got_tiles = [html.unescape(n) for n in re.findall(r' data-n="([^"]*)"', pane)]
    check("/badges lists them in that order",
          got_leg == want)
    check("the filter's grid lists them in that order",
          got_tiles == [b["name"] for b in S.BADGES if b["filter"]])
    rank = {b["key"]: i for i, b in enumerate(S.BADGES)}
    carried = dict((n, k) for n, k, _h in list_rows(get("/directory")[1])).get("Badge Board", [])
    shown = badge_row(get("/directory")[1], "Badge Board")
    marks = [m for m in re.findall(r'aria-label="(?:Supports |Interest: )([^."]+)\.', shown)]
    check("a board's filter keys are in that order too",
          len(carried) > 5 and carried == sorted(carried, key=rank.get))
    # Its row does not (site 1.0.0): ROW_ORDER, then the causes, then the
    # interests, only those two alphabetical, the interests across groups.
    check("but its row is the fixed order: causes, then interests A to Z",
          marks == ["LGBTQ+ people", "Amateur radio", "Chiptune", "Commodore 64",
                    "Electronics"]
          and S.ROW_ORDER == ("petscii", "guests", "chat", "mail", "forums", "files",
                              "doors", "camera", "sd", "new", "steady")
          and [b["sort"] for b in S.ROW_INTERESTS]
              == sorted(b["sort"] for b in S.ROW_INTERESTS)
          and [b["key"] for b in S.ROW_SUPPORT]
              == [b["key"] for b in S.BADGES if b["group"] == "support"])
    check("it belongs to Communities online in the menu, on the list face",
          '<a class="here" href="/directory">Communities online</a>' in leg)
    about_leg = get("/badges", host="about.example")[1]
    check("and on the about face, not to What this is",
          '<a class="here" href="https://boards.example/directory">Communities online</a>'
          in about_leg
          and 'class="here" href="/">What this is' not in about_leg)
    check("How to get listed shows the fields, in codes, and links the legend",
          'href="/badges"' in get("/how")[1] and '"support":["ltrcy"]' in get("/how")[1]
          and '"interests":["c64","elctr","ham"]' in get("/how")[1]
          and '"sd":32' in get("/how")[1])

    # ----------------------------------------------------------------------
    print("Rows: every other one striped, and the hover")
    css = get("/directory")[1].split("<style>")[1].split("</style>")[0]
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
        home4 = fetch("/directory", base4) if up4 else (None, "", b"")
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

    # ----------------------------------------------------------------------
    # And from 0.21.1, which is what the live database is now: badges and
    # all, but no interests. One column added, nothing else touched.
    print("A database from 0.21.1, before the interests")
    db_0211 = os.path.join(tempfile.gettempdir(), f"dir0211{os.getpid()}.db")
    for leftover in (db_0211, db_0211 + "-wal", db_0211 + "-shm"):
        if os.path.exists(leftover):
            os.remove(leftover)
    con = sqlite3.connect(db_0211)
    con.executescript(OLD_SCHEMA_0211)
    con.execute("INSERT INTO boards(token, name, owner, software, port, nodes, state, "
                "first_seen, last_seen, streak_start, public_at, beats, system, "
                "terminals, guests, features, support, tracked_since) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("b" * 32, "Badge Keeper", "Sparks", "unleashed", 6400, 10, "online",
                 now - 40 * 86400, now, now - 40 * 86400, now - 40 * 86400, 777,
                 "ESP32-WROOM-32E", "ansi,petscii", 1, "chat,files", "ham", now - 9 * 86400))
    con.execute("INSERT INTO beathours(board_id, hour, beats) VALUES(1, ?, 6)",
                (now // 3600,))
    con.commit()
    con.close()
    port5 = PORT + 4
    base5 = f"http://127.0.0.1:{port5}"
    server5, out5, up5 = start_server(db_0211, port5)
    try:
        home5 = fetch("/directory", base5) if up5 else (None, "", b"")
        check("the server starts on it and serves the list"
              + ("" if up5 else "  <- " + b"".join(out5[-3:]).decode("utf-8", "replace")),
              up5 and home5[0] == 200 and b"Badge Keeper" in home5[2])
        con = sqlite3.connect(db_0211)
        con.row_factory = sqlite3.Row
        cols = {r["name"] for r in con.execute("PRAGMA table_info(boards)")}
        fresh = sqlite3.connect(":memory:")
        fresh.executescript(S.SCHEMA)
        want = {r[1] for r in fresh.execute("PRAGMA table_info(boards)")}
        fresh.close()
        was_mem = sqlite3.connect(":memory:")
        was_mem.executescript(OLD_SCHEMA_0211)
        had = {r[1] for r in was_mem.execute("PRAGMA table_info(boards)")}
        was_mem.close()
        check("its table gains interests and sd and nothing else, and matches a new one",
              cols == want and cols - had == {"interests", "sd"} and had <= cols)
        r = con.execute("SELECT * FROM boards WHERE token=?", ("b" * 32,)).fetchone()
        check("the old row keeps every badge it had, and simply has no interests yet",
              r["name"] == "Badge Keeper" and r["beats"] == 777 and r["support"] == "ham"
              and r["features"] == "chat,files" and r["guests"] == 1
              and r["interests"] == "" and r["tracked_since"] == now - 9 * 86400
              and con.execute("SELECT beats FROM beathours WHERE board_id=1")
              .fetchone()[0] == 6)
        con.close()
        row5 = badge_row(home5[2].decode("utf-8"), "Badge Keeper")
        # Its support column says "ham", written before amateur radio moved
        # to the interests (0.22.2). It is read as the interest, with no
        # migration: the row shows it, the filter finds it, the JSON files it.
        check("its row shows what it had, ham now as an interest, and the filter "
              "can find it by it",
              ('term', 'P') in badges_in(row5)
              and 'aria-label="Interest: Amateur radio.' in row5
              and "Supports amateur radio" not in row5
              and "petscii" in dict((n, k) for n, k, _h in list_rows(
                  fetch("/?b=petscii&b=ham", base5)[2].decode("utf-8"))).get("Badge Keeper", []))
        listed5 = {b["name"]: b for b in json.loads(
            fetch("/api/boards.json", base5)[2].decode("utf-8"))["boards"]}
        check("and the JSON files an old support ham with its interests, lists "
              "and never missing fields",
              listed5.get("Badge Keeper", {}).get("interests") == ["ham"]
              and listed5.get("Badge Keeper", {}).get("support") == [])
        code5, _b = post_from({"name": "Badge Keeper", "port": 6400, "token": "b" * 32,
                               "software": "unleashed", "support": ["ham"],
                               "interests": ["c64", "swl"]}, "192.0.2.55", base5)
        con = sqlite3.connect(db_0211)
        con.row_factory = sqlite3.Row
        r = con.execute("SELECT * FROM boards WHERE token=?", ("b" * 32,)).fetchone()
        con.close()
        check("its next heartbeat keeps its listing and stores its interests, the "
              "ham it still sends as support among them",
              code5 == 200 and r["interests"] == "c64,ham,swl" and r["support"] == ""
              and r["beats"] == 778 and r["state"] == "online")
        S.DB_PATH, was = db_0211, S.DB_PATH
        try:
            S.setup()
            again = True
        except Exception:
            again = False
        S.DB_PATH = was
        check("and starting again on it changes nothing", again)
    finally:
        server5.terminate()
        try:
            server5.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server5.kill()
        for leftover in (db_0211, db_0211 + "-wal", db_0211 + "-shm"):
            try:
                os.remove(leftover)
            except OSError:
                pass

    # ----------------------------------------------------------------------
    # And from 1.0.0, which is what the live database is now: every badge
    # column but sd, and the causes and interests stored as the long slugs
    # the codes replaced. One column added; the slugs are read as codes with
    # no migration, and the next heartbeat writes codes.
    print("A database from 1.0.0, before the codes and the SD card")
    db_100 = os.path.join(tempfile.gettempdir(), f"dir100{os.getpid()}.db")
    for leftover in (db_100, db_100 + "-wal", db_100 + "-shm"):
        if os.path.exists(leftover):
            os.remove(leftover)
    con = sqlite3.connect(db_100)
    con.executescript(OLD_SCHEMA_100)
    con.execute("INSERT INTO boards(token, name, owner, software, version, port, nodes, "
                "state, first_seen, last_seen, streak_start, public_at, beats, system, "
                "terminals, guests, features, support, tracked_since, interests) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("c" * 32, "Slug Keeper", "Sparks", "unleashed", "1.0.1", 6400, 10,
                 "online", now - 40 * 86400, now, now - 40 * 86400, now - 40 * 86400, 900,
                 "ESP32", "ansi", 1, "chat,files", "mental-health,literacy",
                 now - 9 * 86400, "electronics,chiptune,3d-printing"))
    con.commit()
    con.close()
    port6 = PORT + 4
    base6 = f"http://127.0.0.1:{port6}"
    server6, out6, up6 = start_server(db_100, port6)
    try:
        home6 = fetch("/directory", base6) if up6 else (None, "", b"")
        check("the server starts on it and serves the list"
              + ("" if up6 else "  <- " + b"".join(out6[-3:]).decode("utf-8", "replace")),
              up6 and home6[0] == 200 and b"Slug Keeper" in home6[2])
        con = sqlite3.connect(db_100)
        con.row_factory = sqlite3.Row
        cols = {r["name"] for r in con.execute("PRAGMA table_info(boards)")}
        fresh = sqlite3.connect(":memory:")
        fresh.executescript(S.SCHEMA)
        want = {r[1] for r in fresh.execute("PRAGMA table_info(boards)")}
        fresh.close()
        was_mem = sqlite3.connect(":memory:")
        was_mem.executescript(OLD_SCHEMA_100)
        had = {r[1] for r in was_mem.execute("PRAGMA table_info(boards)")}
        was_mem.close()
        check("its table gains sd and nothing else, and matches a new one",
              cols == want and cols - had == {"sd"} and had <= cols)
        r = con.execute("SELECT * FROM boards WHERE token=?", ("c" * 32,)).fetchone()
        con.close()
        check("the old row is untouched: its slugs as they were, and no SD card",
              r["support"] == "mental-health,literacy"
              and r["interests"] == "electronics,chiptune,3d-printing"
              and r["sd"] is None and r["beats"] == 900)
        row6 = badge_row(home6[2].decode("utf-8"), "Slug Keeper")
        check("its row shows the causes and interests the old slugs name",
              'aria-label="Supports mental health.' in row6
              and 'aria-label="Supports literacy.' in row6
              and 'aria-label="Interest: Electronics.' in row6
              and 'aria-label="Interest: 3D printing.' in row6
              and 'aria-label="Interest: Chiptune.' in row6
              and ("feat", "SD") not in [(c, t[:2]) for c, t in badges_in(row6)])
        found6 = [n for n, _k, h in list_rows(
            fetch("/?b=MNTLH&b=electronics", base6)[2].decode("utf-8")) if not h]
        check("the filter finds it by the codes and by the old slugs",
              found6 == ["Slug Keeper"])
        listed6 = {b["name"]: b for b in json.loads(
            fetch("/api/boards.json", base6)[2].decode("utf-8"))["boards"]}
        check("and the JSON answers in codes, with no SD card",
              listed6.get("Slug Keeper", {}).get("support") == ["mntlh", "ltrcy"]
              and listed6.get("Slug Keeper", {}).get("interests")
              == ["3dprt", "elctr", "chptn"]
              and listed6.get("Slug Keeper", {}).get("sd", 0) is None)
        code6, _b = post_from({"name": "Slug Keeper", "port": 6400, "token": "c" * 32,
                               "software": "unleashed", "version": "1.1.0",
                               "support": ["mental-health", "LTRCY"],
                               "interests": ["electronics", "C64"], "sd": 64},
                              "192.0.2.66", base6)
        con = sqlite3.connect(db_100)
        con.row_factory = sqlite3.Row
        r = con.execute("SELECT * FROM boards WHERE token=?", ("c" * 32,)).fetchone()
        con.close()
        check("its next heartbeat keeps its listing and stores codes and the card",
              code6 == 200 and r["support"] == "mntlh,ltrcy"
              and r["interests"] == "c64,elctr" and r["sd"] == 64
              and r["beats"] == 901 and r["state"] == "online")
        check("and the row shows SD64",
              ("feat", "SD64") in badges_in(badge_row(
                  fetch("/directory", base6)[2].decode("utf-8"), "Slug Keeper")))
        S.DB_PATH, was = db_100, S.DB_PATH
        try:
            S.setup()
            again = True
        except Exception:
            again = False
        S.DB_PATH = was
        check("and starting again on it changes nothing", again)
    finally:
        server6.terminate()
        try:
            server6.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server6.kill()
        for leftover in (db_100, db_100 + "-wal", db_100 + "-shm"):
            try:
                os.remove(leftover)
            except OSError:
                pass


def directory_checks(S):
    """Site 1.2.8 (Rob: "limit the front page to 10 BBS systems, most active
    and popular. Create a new page which is purely the search and directory.
    Search should include a name search too."). A directory of its own with
    twelve boards, each with a different number of callers on, so the order
    is known and is not the alphabet's."""
    import sqlite3
    print("The busiest ten, and /directory")
    db12 = os.path.join(tempfile.gettempdir(), f"dir128{os.getpid()}.db")
    for leftover in (db12, db12 + "-wal", db12 + "-shm"):
        if os.path.exists(leftover):
            os.remove(leftover)
    now = int(time.time())
    # Busiest first as listed here; the names run against the alphabet.
    names = ["Zulu Station", "Yankee Relay", "X-Ray Vision", "Whiskey Node",
             "Victor Line", "Uniform Hall", "Tango Club", "Sierra Base",
             "Romeo Lounge", "Quebec Corner", "Papa Shack", "Oscar Attic"]
    con = sqlite3.connect(db12)
    con.executescript(S.SCHEMA)
    for i, name in enumerate(names):
        con.execute("INSERT INTO boards(token, name, owner, description, software, "
                    "version, port, nodes, busy, state, first_seen, last_seen, "
                    "streak_start, public_at, features) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (f"{i:032d}", name, "Sysop Hedgehog" if i == 7 else f"Op{i}",
                     "Home of the lighthouse" if i == 9 else "A board",
                     "unleashed", "1.1.0", 6400, 16, 12 - i, "online",
                     now - 86400, now, now - 86400, now - 86400,
                     "chat,files" if i % 2 else "chat"))
    con.commit()
    con.close()
    port7 = PORT + 4
    base7 = f"http://127.0.0.1:{port7}"
    server7, out7, up7 = start_server(db12, port7)
    try:
        def page(path):
            code, _t, body = fetch(path, base7) if up7 else (None, "", b"")
            return code, body.decode("utf-8", "replace")

        # Site 1.3.0: the front page is the pitch, and every board is on
        # /directory, busiest first.
        code, home = page("/")
        check("the front page carries no board list, and no script"
              + ("" if up7 else "  <- " + b"".join(out7[-3:]).decode("utf-8", "replace")),
              code == 200 and list_rows(home) == [] and "<script" not in home
              and '<table id="boards"' not in home)
        code, full = page("/directory")
        check("/directory shows all twelve, busiest first",
              code == 200 and [n for n, _k, _h in list_rows(full)] == names
              and "<h1>Communities online</h1>" in full)
        check("and lights Communities online in the menu",
              '<a class="here" href="/directory">Communities online</a>' in full)
        check("with a search box that belongs to the filter's form",
              '<input type="search" id="nq" name="q" form="fform" value=""'
              f' maxlength="{S.SEARCH_MAX}"' in full
              and '<button type="submit" form="fform">Search</button>' in full
              and '<form class="fpane" id="fform" method="get" action="/directory"'
                  ' aria-label=' in full)
        _c, hit = page("/directory?q=yANKee")
        check("?q= finds a board by its name, in any case",
              [n for n, _k, _h in list_rows(hit)] == ["Yankee Relay"]
              and "1 board matches &ldquo;yANKee&rdquo;." in hit
              and 'value="yANKee"' in hit)
        _c, by = page("/directory?q=hedgehog")
        _c, dsc = page("/directory?q=LIGHTHOUSE")
        check("and by its sysop's name, and by its description",
              [n for n, _k, _h in list_rows(by)] == ["Sierra Base"]
              and [n for n, _k, _h in list_rows(dsc)] == ["Quebec Corner"])
        _c, evil = page("/directory?q=%3Cscript%3Ealert(1)%3C%2Fscript%3E")
        check("a search is only ever put back on the page escaped",
              "<script>alert" not in evil
              and 'value="&lt;script&gt;alert(1)&lt;/script&gt;"' in evil
              and "No board matches &ldquo;&lt;script&gt;alert(1)&lt;/script&gt;"
                  "&rdquo;." in evil)
        check("and one that finds nothing says so, and offers to clear it",
              '<a href="/directory">Clear the search</a>' in evil
              and '<table id="boards"' not in evil
              and 'id="fform"' in evil)
        # "e" is in six of them, by name, sysop or description; four of
        # those six run files.
        _c, both = page("/directory?b=files&q=E")
        shown_b = [n for n, _k, h in list_rows(both) if not h]
        check("a filter and a search narrow together, and the filter keeps the search",
              shown_b == ["Yankee Relay", "Whiskey Node", "Sierra Base", "Quebec Corner"]
              and len(list_rows(both)) == 6
              and 'href="/directory?q=E" data-clear>Clear all</a>' in both
              and '<a href="/directory?b=files">Clear the search</a>' in both)
        _c, long_ = page("/directory?q=" + "a" * 500)
        check("a long search is cut to SEARCH_MAX characters",
              S.SEARCH_MAX == 60 and f'value="{"a" * 60}"' in long_
              and "a" * 61 not in long_
              and S.search_query("q=" + "b" * 500) == "b" * 60
              and S.search_query("q=%00x%E2%80%AEy++z") == "xy z")
        code, loc = None, ""
        try:
            opener = urllib.request.build_opener(NoRedirect)
            opener.open(base7 + "/?b=files&q=E", timeout=5)
        except urllib.error.HTTPError as e:
            code, loc = e.code, e.headers.get("Location", "")
        check("a filter or a search asked of the front page is sent to /directory",
              code == 302 and loc == "/directory?b=files&q=E")
    finally:
        server7.terminate()
        try:
            server7.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server7.kill()
        for leftover in (db12, db12 + "-wal", db12 + "-shm"):
            try:
                os.remove(leftover)
            except OSError:
                pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """An opener that reports a redirect instead of following it."""
    def redirect_request(self, *args, **kwargs):
        return None


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
        _, page = get("/directory")
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

        _, page = get("/directory")
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
              "<h1>Communities online</h1>" in page and "listed &middot;" not in page)
        check("and the figures are a sentence under it, counted from the list",
              '<h1>Communities online</h1><p class="stat">'
              "<span class='n'>1</span> community listed, with <span class='n'>2</span> "
              "people connected right now.</p>" in page)
        check("in --live, the colour that means up",
              "p.stat .n { color:var(--live); }" in page)
        # Plurals, and the two zeros, straight from the function that
        # writes the sentence, since the running server has one board.
        def said(n, m):
            return re.sub(r"<[^>]+>", "", S.stat_line(n, m))
        check("no boards: said as such, with no people clause to go wrong",
              said(0, 0) == "No communities listed yet.")
        check("one board, one person: both singular",
              said(1, 1) == "1 community listed, with 1 person connected right now.")
        check("one board, nobody on: nobody, not 0 people",
              said(1, 0) == "1 community listed, with nobody connected right now.")
        check("two boards, five people: both plural",
              said(2, 5) == "2 communities listed, with 5 people connected right now.")
        check("a big figure gets its thousands separator",
              said(1200, 3400) == "1,200 communities listed, with 3,400 "
                                  "people connected right now.")
        # The directory knows nothing about where a board is, so nothing on
        # the page may say "across the globe" until something true can.
        check("the suffix is empty, and nothing claims the globe",
              S.STAT_SUFFIX == "" and "globe" not in page.lower())
        was_suffix = S.STAT_SUFFIX
        S.STAT_SUFFIX = " in three time zones"
        check("and a suffix, once set, goes before the full stop",
              said(2, 5).endswith("connected right now in three time zones."))
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
        _, page = get("/directory")
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

        _, page = get("/directory", host="boards.example")
        check("the list domain still lists boards", "Rusty Modem" in page)
        check("the list page owns the board-list heading",
              "Communities online" in page)

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
              "doors are still to come" in page.lower() and ", doors," not in page)
        # F8, site 1.2.1: the forums are not the newest part any more (the
        # information pages and mail as a place came after them).
        check("and the forums are not called the newest part",
              "newest part" not in page)
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
              code == 200 and "is the nickname other people on the board see" in page)
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
              ">Who builds one</a>" in page)
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
              "files and forums" in kids.lower()
              and "not every board has them" in kids.lower()
              and "newest part" not in kids.lower())
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
              "answers ten people at once" in " ".join(page.split())
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
                     "/forward-mesh", "/badges", "/hardware"):
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

        _, page = get("/directory")
        check("the board list offers a way out when a dial link does nothing",
              'href="/dialing">Did not connect?' in page)
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

        # Site 1.2.1: /lights, /sdcard's twin for the drive light and the
        # strip, with the same shape: a drawing beside a pin table, and
        # what goes wrong. Reached from /build, /hardware, /teachers.
        print("The lights page")
        code, lp = get("/lights")
        flat_l = " ".join(lp.split())
        check("/lights renders, with a drawing of each light",
              code == 200 and has_h(lp, 1, "Lights")
              and S.ART["lights-drive"] in lp and S.ART["lights-strip"] in lp
              and lp.count('<svg class="art wiring lights"') == 2
              and 'role="img"' in S.ART["lights-drive"].split(">")[0])
        check("with the pins, the resistor, the capacitor and a supply of its own",
              "<code>D13</code> / GPIO13" in lp and "<code>D14</code> / GPIO14" in lp
              and "330 to 470 ohm" in flat_l and "100 nF" in flat_l
              and "a 5 V supply of its own" in flat_l
              and "about 600 mA" in flat_l)
        check("and never tells a reader they need a level shifter",
              "level shifter" not in flat_l.lower())
        check("it lights up Build one, like /sdcard",
              S.NAV_SECTION.get("/lights") == "/build"
              and '<a class="here" href="/build">' in lp)
        for pg in ("/sdcard", "/lights"):
            _, sp = get(pg)
            body = sp.split("<article>")[1]
            check(f"{pg} opens by saying the Waveshare S3 needs none of it",
                  body.index("The Waveshare S3 needs none of this.") < body.index("<h2")
                  and 'href="/hardware#waveshare-esp32-s3-lcd-1-47"' in body)
        check("the SD card's wires are counted the same way everywhere",
              all("six wires" not in get(pg)[1] and "six jumper wires" not in get(pg)[1]
                  for pg in ("/sdcard", "/hardware", "/teachers", "/build"))
              and "four signal wires plus power" in " ".join(get("/sdcard")[1].split()))
        # NEW-2 and NEW-3 of the 1.2.1 review: one answer for the card's
        # power and one for CS on GPIO5, on every page that says either.
        check("no page says the card module never goes on VIN",
              "goes on 3V3 and not VIN" not in get("/teachers")[1])
        check("and none moves CS off GPIO5 to get the board to start",
              "will not start with a card" not in get("/setup")[1]
              and "does not stop the board booting" in " ".join(get("/sdcard")[1].split()))
        # NEW-5: the clone command keeps its words whole on a phone.
        check("/build's commands scroll on a phone rather than break inside a word",
              '<pre class="nowrap">git clone https://github.com/rwmech/unleashed_BBS' in page
              and "article pre.nowrap { white-space:pre; overflow-wrap:normal; }" in page
              and "include/secrets.h" not in page
              and "-e ws_s3_lcd147" in page)
        # NEW-1: /how links the rules it was said to cover.
        check("/how links the house rules, as /setup says it does",
              'href="/rules"' in get("/how")[1]
              and "[the house\nrules](/rules)" in
                  open(os.path.join("pages", "setup.md"), encoding="utf-8").read())

        # ------------------------------------------------------------------
        # Site 1.2.4: the camera boards, /camera, /different and /roadmap.
        print("Camera boards, the camera, what is different, the roadmap")
        _, hwp4 = get("/hardware")
        hw4 = hwp4.split("<article>")[1].split("</article>")[0]
        soon_ok = True
        # Site 1.2.9: the Freenove is in BOARDS, marked to wait for a
        # release, and is coming soon here while no release carries it,
        # which is the case with this suite's firmware/ (0.23.0).
        fncam = S.BOARD_BY_DIR["esp32-fncam"]
        for b in S.SOON_BOARDS + (fncam,):
            anchor = b["page"].split("#")[1]
            sec = hw4.split(f'id="{anchor}"')[1].split("<h2")[0] if f'id="{anchor}"' in hw4 else ""
            soon_ok = soon_ok and (S.board_html([b["dir"]]) in sec
                                   and "coming soon to" in S.board_html([b["dir"]])
                                   and "<b>Coming soon.</b>" in sec
                                   and f'<a href="{b["buy"]}" rel="sponsored">Amazon</a>'
                                   ' (affiliate link)' in sec
                                   and 'href="/camera"' in sec)
        # Site 1.2.5, Rob: both camera boards gained a buy link, shown the
        # way the tested boards show theirs, and stay coming soon.
        check("/hardware lists both camera boards as coming soon, each with its buy link",
              len(S.SOON_BOARDS) == 1 and soon_ok
              and "tested when it arrives" in " ".join(hw4.split())
              and "<b>ESP32-WROVER: should work, not yet tested.</b>" in hw4
              and "<b>ESP32-WROVER: yes, on one board.</b>" not in hw4)
        _, inst4 = get("/install")
        check("and neither is offered on the installer's picker",
              all(b["name"] not in inst4 for b in S.SOON_BOARDS + (fncam,))
              and all(b["dir"] not in {x["dir"] for x in S.BOARDS} for b in S.SOON_BOARDS)
              and fncam.get("previews") is False
              and fncam not in S.picker_boards()
              and 'id="on-the-freenove-camera-board"' not in inst4)
        code, cam = get("/camera")
        flat_c = " ".join(cam.split())
        check("/camera renders, with its drawing and the commands",
              code == 200 and has_h(cam, 1, "Camera")
              and S.ART["camera-snap"] in cam
              and "<code>SNAPSHOT</code>" in cam and "<code>SNAP</code>" in cam
              and "<code>Download it now? [Y]es [X]modem [N]o</code>" in cam)
        # Site 1.2.9: the settings as the firmware built them (COMMANDS.md
        # "camera" at 1.1.0-dev.15), not as the plan left them open.
        check("and says the rules Rob set: area 12, the limits, the card, the defaults",
              "file area 12" in flat_c and "file area 13" in flat_c
              and "10 pictures an hour and 20 a day" in flat_c
              and "without one the camera does not start" in flat_c
              and "<td>12</td>" in cam and "<td>200</td>" in cam
              and "anything under 10 seconds is 10" in flat_c
              and "Not settled yet" not in cam and "not settled" not in flat_c.lower()
              and "A lens cap is the only real guarantee." in flat_c
              and "There is no countdown" in flat_c)
        check("and carries the coming-soon note until a 1.1.0 release is on disk",
              ("arrives with firmware 1.1 for the camera boards" in flat_c)
              == (not any(r["sort"] >= (1, 1, 0) for r in S.firmware_releases())))
        check("it lights Build one, and /build and /whofor link it",
              S.NAV_SECTION.get("/camera") == "/build"
              and '<a class="here" href="/build">' in cam
              and 'href="/camera"' in get("/build")[1]
              and 'href="/camera"' in get("/whofor")[1])
        _, who4 = get("/whofor")
        flat_w = " ".join(who4.split())
        check("/whofor has the camera's uses, motion marked as later",
              has_h(who4, 2, "A board with a camera")
              and "Wildlife." in flat_w and "Outdoors." in flat_w
              and "PIR motion sensor" in flat_w
              and "That one comes later, with the plugin for sensors." in flat_w
              and 'href="/different"' in who4)
        code, dif = get("/different")
        dbody = dif.split("<article>")[1].split('id="how-it-compares-with-the-apps')[0]
        items = re.findall(r'<li><b><a href="([^"]+)">', dbody)
        check("/different renders its list, each line linked to its proof",
              code == 200 and has_h(dif, 1, "What a board can do")
              and 10 <= len(items) <= 12 and len(set(items)) == len(items)
              and all(h.startswith("/") for h in items))
        # Site 1.2.9 (Rob: "get a matrix table going"): the comparison is a
        # table, µnleashed's column first and lit, every rival's column
        # linked to its own pages, and under it the one line that says what
        # the big packages still do better.
        cmp_t = dif.split('<table class="cmp">')[1].split("</table>")[0] \
            if '<table class="cmp">' in dif else ""
        check("and compares in a table, with sources, claiming no 'only'",
              '<div class="cmpwrap" role="region" aria-label="How it compares" '
              'tabindex="0">' in dif
              and '<th scope="col" class="us"><a href="/hardware">\u00b5nleashed</a></th>'
                  in cmp_t
              and all(f'<a href="{h}">' in cmp_t for _n, h in S.COMPARE_COLS[1:])
              and "https://github.com/snazzware/espbbs" in cmp_t
              and cmp_t.count("<tr>") == len(S.COMPARE_ROWS) + 1
              and all(len(c) == len(S.COMPARE_COLS) for _l, c in S.COMPARE_ROWS)
              and cmp_t.count('<td class="us">') == len(S.COMPARE_ROWS)
              and 'aria-label="Yes"' in cmp_t and 'aria-label="No"' in cmp_t
              and 'aria-label="Not in its own documentation">?</span>' in cmp_t
              and " the only BBS that" not in dif.lower()
              and "can't" not in dbody and "cannot do" not in dbody)
        check("and says under it what the big packages still do better",
              '<p class="cmpnote">The big packages still do plenty this board does '
              "not yet: FidoNet-style message networks, door games, ZMODEM" in dif
              and '<a href="/roadmap">The roadmap</a>' in dif.split('class="cmpnote"')[-1])
        check("and its camera row follows the firmware on disk",
              ("coming, on the camera boards" in cmp_t)
              == (not any(r["sort"] >= (1, 1, 0) for r in S.firmware_releases())))
        check("and the table scrolls on a phone with the row names held still",
              "table.cmp th[scope=row] { position:sticky; left:0;" in dif
              and ".cmpwrap { overflow-x:auto;" in dif
              and '<p class="cmphint" aria-hidden="true">The table scrolls sideways' in dif
              and "p.cmphint { display:none;" in dif
              # an upper-cased micro sign is a capital mu: MNLEASHED
              and "table.cmp thead th.us { text-transform:none;" in dif)
        # Site 1.3.0 (Rob): the second table, against the places people
        # build a community today, fair to them: they win on reach, and the
        # note under it says so. Every column's heading links to the page
        # its cells were checked against, and µnleashed's column is lit.
        today = dif.split('<table class="cmp today">')[1].split("</table>")[0] \
            if '<table class="cmp today">' in dif else ""
        check("/different compares with the apps people use now, fairly and with sources",
              '<div class="cmpwrap" role="region" aria-label="How it compares with '
              'the apps" tabindex="0">' in dif
              and all(f'<a href="{h}">' in today for _n, h in S.COMPARE_TODAY_COLS)
              and all(h.startswith(("https://", "/")) for _n, h in S.COMPARE_TODAY_COLS)
              and all("e.g." in n for n, _h in S.COMPARE_TODAY_COLS[1:])
              and today.count("<tr>") == len(S.COMPARE_TODAY_ROWS) + 1
              and all(len(c) == len(S.COMPARE_TODAY_COLS) for _l, c in S.COMPARE_TODAY_ROWS)
              and today.count('<td class="us">') == len(S.COMPARE_TODAY_ROWS)
              and "They win on reach and ease" in dif
              and "Easy for new people to find" in today
              and "Encrypted on the way" in today
              and dif.index('class="cmp today"') < dif.index('<table class="cmp">'))
        check("and says what is on those sites, from their own pages, and on ours",
              has_h(dif, 2, "What is on those sites")
              and 'href="https://discord.com/privacy"' in dif
              and 'href="https://www.facebook.com/terms.php"' in dif
              and "This website runs no analytics" in " ".join(dif.split())
              and 'href="/privacy">What that means in practice' in dif)
        # Site 1.3.1: where encryption comes up, SSH is said to be coming on
        # the S3 boards, and never as a thing already there.
        flat_today = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", today)).split())
        flat_dif = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", dif)).split())
        # Site 1.3.3: with the version Rob set, 1.2.0.
        check("the encryption row and the honest paragraph say SSH is coming on "
              "the S3, in firmware 1.2.0",
              "not yet: plain text, so say only what you would say in public. SSH, "
              "encrypted, is coming on the S3 boards in firmware 1.2.0" in flat_today
              and "An encrypted way in, SSH" in flat_dif
              and "is coming on the ESP32-S3 boards in firmware 1.2.0, beside telnet "
                  "rather than instead of it; it is on the roadmap and not released "
                  "yet." in flat_dif
              and "SSH is supported" not in flat_dif)
        rmp = get("/roadmap")[1]
        check("the roadmap keeps SSH under Later, on the S3 boards, in 1.2.0",
              "<b>An encrypted way in, on the S3 boards, in firmware 1.2.0.</b>" in rmp
              and rmp.index("An encrypted way in") > rmp.index('id="later"')
              and "SSH on the S3, 1.2.0" in S.ROADMAP_LABEL
              and 'href="/hardware#waveshare-esp32-s3-lcd-1-47"' in rmp)
        check("the BBS table says it in plain words, no computer-you-supply",
              "a computer you supply" not in dif
              and "none built in: it runs on a PC you already have" in cmp_t
              and "not built in" in cmp_t)
        home = get("/")[1]
        check("the front page links to it once, from its history",
              home.count('href="/different"') == 1
              and home.index('id="before-social-media"') < home.index('href="/different"'))
        face, _w = S.PITCH_FONTS[S.PITCH_FONT]
        fcode, fctype, fblob = fetch("/font/" + face)
        lcode, _lt, lblob = fetch("/font/OFL-" + face.split("-")[0].split(".")[0] + ".txt")
        notices = open("THIRD_PARTY_NOTICES.md", encoding="utf-8").read()
        check("the pitch is set in its own face, served from here, with its licence",
              '@font-face { font-family:"Pitch"; src:url("/font/' + face + '")' in home
              and '.front h1.hero { font-family:"Pitch",' in home
              and fcode == 200 and fctype.startswith("font/") and len(fblob) > 4000
              and lcode == 200 and b"SIL OPEN FONT LICENSE Version 1.1" in lblob
              and "googleapis" not in home and "gstatic" not in home
              and all(n in notices for n in ("Oxanium", "Chakra Petch", "Orbitron",
                                             "SIL Open Font License 1.1"))
              and all(os.path.isfile(os.path.join("static", "fonts", f))
                      for f, _ in S.PITCH_FONTS.values())
              and fetch("/font/..%2Fserver.py")[0] == 404
              and fetch("/font/server.py")[0] == 404)
        code, rmp = get("/roadmap")
        art_r = rmp.split("svg.art { display:block;")[1].split("</style>")[0]
        still_r, moving_r = art_r.split("@media (prefers-reduced-motion: no-preference) {")
        check("/roadmap renders, with its drawing across and down",
              code == 200 and has_h(rmp, 1, "Roadmap") and S.ART["roadmap"] in rmp
              and rmp.count('<svg class="art roadmap wide"') == 1
              and rmp.count('<svg class="art roadmap tall"') == 1
              and all(rmp.count(">" + html.escape(s) + "</text>") == 2
                      for _k, _t, _s, st in S.ROADMAP for s in st))
        check("and the words say every station again, in three stretches",
              [k for k, *_ in S.ROADMAP] == ["done", "now", "later"]
              and has_h(rmp, 2, "Done") and has_h(rmp, 2, "Later")
              and "Motion-triggered snapshots." in rmp
              and "Home Assistant" not in rmp and "MQTT" not in rmp
              and "captive" not in rmp.lower() and "Lua" not in rmp)
        rm_kf = re.findall(r"@keyframes (rm\w+) \{(.*?)\}\s*\}", art_r, re.S)
        check("and it moves only where reduced motion allows, by transform and opacity",
              "svg.art.roadmap .rlamp { animation:" in moving_r
              and not re.search(r"svg\.art\.roadmap[^{]*\{[^}]*(animation|transition):",
                                still_r)
              and len(rm_kf) == 2
              and all(set(re.findall(r"([a-z-]+):", b)) <= {"transform", "opacity"}
                      for _, b in rm_kf))
        check("the roadmap is in the footer and lights What this is, like /different",
              '>Roadmap</a>' in rmp.split("<footer>")[1]
              and S.NAV_SECTION.get("/roadmap") == "about:/"
              and S.NAV_SECTION.get("/different") == "about:/"
              and re.search(r'<a class="here" href="[^"]*">What this is</a>', rmp)
              and re.search(r'<a class="here" href="[^"]*">What this is</a>', dif))
        about4 = get("/", host="about.example")[1]
        check("What this is links both, in context",
              'href="/different"' in about4 and 'href="/roadmap"' in about4)

        # Site 1.2.0: the tested boards page, a picture and the facts for
        # each board from the same table the installer's picker draws, and
        # the build page's table of chips says the S3 has run.
        # Site 1.2.1: the chips live on /hardware, and /build points there.
        check("build links the tested boards, and the chips are said there",
              'href="/hardware"' in page
              and "<b>ESP32-S3: yes, on one board.</b>" in get("/hardware")[1])
        code, page = get("/hardware")
        body = page.split("<article>")[1].split("</article>")[0] if "<article>" in page else ""
        check("the tested boards page draws each board, its build and where to buy it",
              code == 200 and '<h2 id="esp32-dev-board-base">' in body
              and '<h2 id="waveshare-esp32-s3-lcd-1-47">' in body
              and body.count('<div class="hwb">')
                  == len(S.BOARDS) + len(S.SHOWN_BOARDS) + len(S.SOON_BOARDS)
              and all(b["buy"] in body for b in S.BOARDS)
              and all(S.board_html([b["dir"]]) in body for b in S.BOARDS))
        check("and it is part of Build one, with the drawings' stylesheet and no script",
              '<a class="here" href="/build">' in page and "svg.art.board {" in page
              and "<script" not in page)
        check("and the S3's install steps are on /install, where it points",
              'href="/install#on-the-waveshare-s3"' in body
              and '<h2 id="on-the-waveshare-s3">' in get("/install")[1])

        code, page = get("/terminals")
        check("the terminal page renders its tables",
              "<table>" in page and "SyncTERM" in page)
        check("and the menu carries it on every page",
              ">Apps for joining</a>" in page)
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
        _, page = get("/directory", host="boards.example")
        check("a board with a day of beats gets a busy-hours chart",
              "class='spark'" in page or 'class="spark"' in page)
        check("and is described by when it is actually busy",
              "busiest 20:00-22:00" in page)
        # The page carries the badge filter's script since 0.22.0, and the
        # chart owes it nothing: it is a <details>, and the script never
        # names it.
        check("the chart expands without any javascript",
              "<details class='chart'>" in page
              and "chart" not in S.BADGE_JS and "summary" not in S.BADGE_JS)
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
        _, page = get("/directory", host="boards.example")
        check("the board list stops being a table on a phone",
              "@media (max-width: 900px)" in page
              and "main > table, main > table > tbody" in page)
        check("and has a column budget on a screen",
              "@media (min-width: 901px)" in page
              and "table-layout:fixed" in page)
        check("the cells carry their own labels, not the column order",
              "data-label='State'" in page and "data-label='Address'" in page)
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
              "<th>Board</th><th>Address</th><th>State</th></tr>" in page
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
        _, page = get("/directory", host="boards.example")
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
        _, page = get("/directory", host="boards.example")
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
        _, page = get("/directory", host="boards.example")
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
        # R6, site 1.2.1: the steps with their pictures are /setup's; the
        # install page says what happens and links them.
        check("and sends the reader to the first-call steps on /setup",
              "the board asks for this password by itself, then for one of your own" in flat_i
              and 'href="/setup#first-become-the-sysop"' in inst
              and "<b>This board has not been set up yet</b>" not in flat_i)
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
        srcs_d = re.findall(r'\bsrc="([^"]+)"', don)
        check("Buy Me a Coffee is a plain link, and nothing on the page is loaded from it",
              '<a href="https://buymeacoffee.com/unleashed_bbs">' in don
              and "<script" not in don and "<iframe" not in don
              and all(u.startswith("/") and not u.startswith("//") for u in srcs_d)
              and "Nothing on this site loads anything from Buy Me a Coffee" in flat_d)
        src_d = open(os.path.join("pages", "donate.md"), encoding="utf-8").read()
        check("its editor note stays in the source and does not reach the page",
              src_d.count("<!--") == 1 and "<!--" not in don.split("<article>")[1]
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
        check("four drawings of what is about to happen, all decoration",
              len(art_i) == 4
              and all(S.ART[k] in inst2 for k in ("install-cable", "install-write",
                                                   "install-boot", "install-wifi")))
        # The steps are split by the drawings and still count on.
        check("and the numbered steps carry on across them",
              '<ol start="5">' in inst2 and '<ol start="6">' in inst2
              and '<ol start="7">' in inst2)
        flat_i2 = " ".join(inst2.split())
        check("the reset section: Change Wi-Fi now, a reflash with erase last",
              has_h(inst2, 2, "If something goes wrong, reset rather than reflash")
              and "works while the board is failing to join one" in flat_i2
              and "nothing on the board is erased" in flat_i2
              and "press Install on a new board and tick Erase everything first"
                  in flat_i2)
        # The BOOT button and the Wi-Fi fallback are firmware 1.1.0's (site
        # 1.1.0). They moved there from 0.24.0, then from 1.0.1, which is the
        # badge fields only, then from 1.0.2, which became the restore
        # security fix and has neither. The repository carries 0.23.0 at
        # most, so here they must not show; the second server below proves
        # they stay hidden at 1.0.0, 1.0.1 and 1.0.2 and show at 1.1.0.
        src_gate = open(os.path.join("pages", "install.md"), encoding="utf-8").read()
        check("the reset section is gated on 1.1.0, not on 1.0.2, 1.0.1 or 0.24.0",
              "::: from 1.1.0" in src_gate and "::: from 1.0.2" not in src_gate
              and "::: from 1.0.1" not in src_gate and "0.24" not in src_gate)
        check("and nothing of 1.1.0's shows while the newest release is older",
              "The BOOT button" not in inst2 and S.ART["boot-button"] not in inst2
              and "takes the board off this directory" not in inst2
              and "::: from" not in inst2)
        # "::: until X.Y.Z" (site 1.1.0) is the other half of the gate: what
        # stops being true when that release lands.
        fwd2, set2 = get("/forward")[1], get("/setup")[1]
        flat_f2, flat_s2 = " ".join(fwd2.split()), " ".join(set2.split())
        check("before 1.1.0, /forward says every board listens on 6400 and the "
              "announce page's Port carries the outside number",
              has_h(fwd2, 2, "The same port outside and in")
              and has_h(fwd2, 2, "One board per port")
              and "Every board listens on 6400" in flat_f2
              and "the <b>Port</b> setting on the announce page" in flat_f2
              and "From firmware 1.1.0" not in flat_f2
              and "::: until" not in fwd2 and "::: from" not in fwd2)
        check("and /setup has the wifi page and the announce page's Port, not "
              "Outside",
              has_h(set2, 2, "wifi") and not has_h(set2, 2, "network")
              and "<b>Outside</b>" not in set2
              and "if you forwarded a different one to the" in flat_s2
              and "::: until" not in set2 and "::: from" not in set2)
        check("the setup steps name what the board says, on /setup",
              "This board has not been set up yet." in set2
              and "YOU ARE THE SYSOP" in set2
              and "The board will not take <code>unleashed</code> here." in set2)

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
            # Site 1.2.0: the board picker, every board with its picture,
            # name and "how to tell" line, and one version line for each
            # release a board is offered; a board with nothing on disk says
            # "Coming soon" and has no buttons.
            offered = sum(len(S.board_offers(b["dir"])) for b in S.picker_boards())
            check("and it carries the board picker, a picture a board, and a version "
                  "line for each release offered",
                  '<fieldset class="boards"><legend>Your board <a href="/hardware">'
                  "which is mine?</a></legend>" in top
                  and all(b["art"] in top and html.escape(b["name"]) in top
                          and html.escape(b.get("pick") or b["tell"]) in top
                          for b in S.picker_boards())
                  and top.count('<input type="radio" name="fwboard"')
                      == len(S.picker_boards())
                  and top.count('class="meta ver ') == offered
                  and top.count("Coming soon") == sum(
                      1 for b in S.picker_boards() if not S.board_offers(b["dir"]))
                  and '<svg class="art mini"' not in top)
            check("the installer's own licence is under Doing it the other way",
                  S.EWT_BASE + "LICENSE" in inst2.split('id="doing-it-the-other-way"')[1]
                  and S.EWT_BASE + "LICENSE" not in top)
        css_i = inst2.split("<style>")[1]
        check("two columns from 901px, the card sticky and level with the title",
              "grid-template-columns:minmax(0, 1fr) 26rem" in css_i
              and "grid-row:1 / span 2" in css_i and "position:sticky" in css_i)
        # Site 1.0.0: both buttons on the first screen at 1366 x 768 with a
        # second release offered. Measured with headless Chrome when it was
        # built (the Update button's bottom went from 831px to about 740px);
        # here, the rules that bought the room are pinned. Site 1.2.0 put the
        # board picker where the drawing and the amber box were, and the
        # amber box under the buttons: 665px for the ESP32 and 719px for the
        # S3 under its download-mode note, measured the same way.
        check("the card tightened so both buttons fit the first screen at 1366 x 768",
              "svg.art.mini" not in css_i
              and "article .installer { display:flex; flex-direction:column; gap:0.5rem; }"
                  in css_i
              and "article .installer .bsec { display:flex; flex-direction:column; "
                  "gap:0.5rem; }" in css_i
              and "article .installer .bopt svg.art.board { width:4rem; height:2.5rem; }"
                  in css_i
              and "position:sticky; top:1rem; padding:1rem 1.25rem; }" in css_i
              and "article .installer button.go { padding-top:0.5625rem; "
                  "padding-bottom:0.5625rem; }" in css_i)
        check("each button carries its line-art symbol, at the badges' stroke weight",
              "article .installer button.go svg.bi { flex:none; width:1.25rem; "
              "height:1.25rem; fill:none;\n        stroke:currentColor; stroke-width:1.8;"
              in css_i
              and (not published
                   or (S.BTN_ICON_NEW + "Install on a new board</button>" in inst2
                       and S.BTN_ICON_UPDATE + "Update my board</button>" in inst2)))
        # The picker, then the buttons, then the amber box, in the markup,
        # which is the order a phone gets and, since site 1.2.0, a desktop
        # too: nothing is reordered by the stylesheet any more.
        check("and on a phone the picker and the button come before the amber box",
              "{ order:" not in css_i.split("The install card, laid out")[1].split(
                  "A page's one primary action")[0]
              and (not published
                   or 0 < top.find('<fieldset class="boards">')
                   < top.find("<esp-web-install-button") < top.find('<div class="pre">')))
        # The board's Improv answer is telnet://, which a browser cannot open.
        check("the last step says Telnet details, not Visit Device",
              "<b>Telnet details</b>" in inst2 and "Visit Device" not in inst2)

        # ------------------------------------------------------------------
        # One primary action on each entry page, drawn like the installer's
        # button, with the other way round beside it as an outlined one. A
        # button that goes somewhere says where it goes: only the button on
        # /install says Install, because only that one installs.
        print("Calls to action")
        for path, alt in (("/build", "#for-developers-build-from-source"),
                          ("/setup", "/build#for-developers-build-from-source")):
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
              'id="for-developers-build-from-source"' in get("/build")[1])
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
        # bit big for a button there in the middle"): no full size button
        # anywhere in its flow. It is /directory since site 1.3.0.
        dirp = get("/directory")[1]
        dbody_ = dirp.split("</nav>")[1].split("<footer")[0]
        check("the board list has no full size button in its flow",
              'class="btn"' not in dbody_ and 'class="btn2"' not in dbody_
              and 'class="cta"' not in dbody_)
        # Site 1.3.0 (Rob, marketing round 3): the front page is the pitch.
        # What it is in today's words first, then the hook, then the proof;
        # the words BBS and sysop arrive with their glossary notes.
        home = get("/")[1]
        hbody = home.split("</nav>")[1].split("<footer")[0]
        hflat = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", hbody)).split())
        check("the front page opens with the kicker and the headline",
              '<p class="kicker">Social, before social media'
              '<span class="k2"><span class="kd" aria-hidden="true"> &middot; </span>'
              '<a href="/different#what-is-on-those-sites">Privacy forward</a></span></p>'
              '<h1 class="hero">Your own online community, on a device that '
              "<em>fits in your hand</em>.</h1>" in hbody
              and hbody.find('<section class="hero">') < hbody.find('<p class="kicker">'))
        # Site 1.3.1 (Rob): "Privacy forward" with the kicker, linked to the
        # place on /different that backs it, one line on a desktop and two
        # on a phone, the dot going.
        difp = get("/different")[1]
        check("and Privacy forward links to where /different backs it",
              'id="what-is-on-those-sites"' in difp
              and "No ads, no trackers and no outside scripts" in difp
              and ".front p.kicker .k2 { display:block;" in home
              and ".front p.kicker .kd { display:none; }" in home
              and "Social, before social media · Privacy forward" in hflat)
        check("and the sub-head says where it runs and what people join from",
              "It runs at home or at work" in hflat
              and "People join from a PC, an Android phone or an iPhone with a free app, "
                  "and from old computers and terminals too." in hflat)
        check("two ways on, twice: Build yours and Try one first, neither saying Install",
              hbody.count('<a class="b1" href="/install">Build yours</a>') == 2
              and hbody.count('<a class="b2" href="/directory">Try one first</a>') == 2
              and not re.search(r'class="b[12]"[^>]*>[^<]*Install', hbody))
        check("a line of facts, and a drawing of the board that says it is one",
              "About $5 · About five minutes · No subscription · Free software" in hflat
              and 'role="img" aria-label="Drawing of the ESP32 board' in hbody
              and "(Photo to come.)" in hbody)
        order = [hbody.find(f'id="{k}"') for k in (
            "what-it-is", "who-builds-one", "three-steps", "before-social-media", "see-one")]
        check("the sections in the approved order",
              all(i > 0 for i in order) and order == sorted(order))
        who_ = hbody[order[1]:order[2]]
        check("six examples, each a situation headed For example, with no names or quotes",
              who_.count('<p class="eg">For example</p>') == 6
              and "&ldquo;" not in who_ and "\u201c" not in who_
              and "&quot;" not in who_)
        check("the history is the sourced one: CBBS in 1978, about 60,000 at the peak",
              "<dt>1978</dt>" in hbody and "<dt>1990s</dt>" in hbody
              and "About 60,000 of them in the United States alone." in hbody
              and "CBBS, Chicago, 16 February 1978" in hbody)
        check("BBS and sysop come with their glossary notes, nothing else is a script",
              hbody.count('class="gl"') >= 4 and "<script" not in home
              and 'aria-describedby="gl' in hbody)
        check("and developers get one quiet line, to a heading that exists",
              '<a href="/build#for-developers-build-from-source">build from source</a>'
              in hbody)
        css_h = home.split("<style>")[1]
        check("the front page's rules reach it, one column on a phone",
              '.front section.hero { border-top:0; padding-top:1rem; display:grid;' in css_h
              and ".front .fcards, .front ol.fsteps { grid-template-columns:1fr;" in css_h
              and ".front section.hero, .front section.then { display:block; }" in css_h)
        check("and the old front page's pieces are gone",
              not hasattr(S, "RUN_CARD") and 'class="runcard"' not in home
              and "listtop" not in css_h and "dirrule" not in css_h)

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
        # 0.22.1: Rob's own board, on 0.22.1 firmware, was not recognised
        # and was offered Install, then an erase question that read as
        # "you are about to lose everything". The page says to press Update
        # my board, no longer promises the board is always recognised, and
        # shows the erase screen's new words for a reader who pressed the
        # other button.
        check("the update is Update my board, which never asks or erases",
              "press Update my board and pick the port" in uflat
              and "Press Update unleashed BBS, then Install." in uflat
              and "It does not ask about erasing and it does not erase." in uflat)
        check("and it no longer promises that a 0.22.1 board is always recognised",
              "usually tells the installer its name and version" in uflat
              and "It may not, if the board is still starting up" in uflat
              and "the page recognises the board. A board running 0.22.1" not in uflat)
        check("and shows the erase screen's own words, box unticked, for Install",
              has_h(upg, 3, "If you pressed Install on a new board instead")
              and "Install or update unleashed BBS" in uflat
              and "Start fresh? Updating a board you already run? Leave this "
                  "unticked: your accounts, settings, mail and forums are kept." in uflat
              and "[ ] Erase everything first" in uflat
              and "Erase device" not in uflat)
        check("what is kept, and the screens that go back to stock",
              "Kept: the accounts, the settings (Wi-Fi included), the mail" in uflat
              and "Back to stock: the screens in the board's own flash." in uflat)
        check("an older board: Update from 0.17.0 on, an erase before it",
              "From 0.17.0 on, use Update my board." in uflat
              and "Before 0.17.0, the erase cannot be avoided." in uflat
              and "Use Install on a new board and tick Erase everything first" in uflat
              and "the board needs your Wi-Fi at the end" in uflat)
        inst_now = get("/install")[1]
        check("and every section it sends a reader to exists",
              'href="/install#changing-the-wi-fi-later"' in upg
              and 'id="changing-the-wi-fi-later"' in inst_now
              and 'href="/install#if-something-goes-wrong-reset-rather-than-reflash"' in upg
              and 'id="if-something-goes-wrong-reset-rather-than-reflash"' in inst_now)
        check("Upgrade is in the footer's Get started row on every face",
              all(re.search(r'<span class="lbl">Get started</span>.*?'
                            r'>Install</a><a href="[^"]*/upgrade">Upgrade</a><a ', p, re.S)
                  for p in (home, inst_now, get("/", host="about.example")[1],
                            get("/", host="data.example")[1])))
        # N1, site 1.2.1: /hardware is in the footer, after Build one.
        check("and Hardware is in it, after Build one, on every face",
              all(re.search(r'<span class="lbl">Get started</span><a href="[^"]*/directory">'
                            r'Communities online</a><a href="[^"]*/build">'
                            r'Build one</a><a href="[^"]*/hardware">Hardware</a>', p)
                  for p in (home, inst_now, get("/", host="about.example")[1],
                            get("/", host="data.example")[1])))
        # The call-out on /install opens the steps column: beside the card
        # on a desktop, after it on a phone, so the button keeps its place.
        itop = inst_now.split('<div class="install-top">')[1].split('id="before-you-start"')[0]
        check("/install calls it out first in the steps, linking /upgrade",
              '<div class="steps"><p class="aside"><b>Already running µnleashed?</b> '
              "Press <b>Update my board</b>, pick the port, then <b>Update unleashed "
              "BBS</b> and <b>Install</b>. It never erases: your accounts, settings, "
              "mail and forums stay, and your SD card is never touched. "
              'More on <a href="/upgrade">upgrading a board</a>' in itop
              and itop.find('<div class="steps"><p class="aside">')
                  < itop.find('id="what-happens-in-order"'))
        # The steps no longer promise a recognised board, and name the erase
        # screen by the words it now shows.
        flat_top = " ".join(re.sub(r"<[^>]+>", " ", itop).split())
        check("and the steps name the new buttons and the erase screen's words",
              "Choose your board, press Install on a new board and pick the port."
              in flat_top
              and "offers Install or update unleashed BBS ." in flat_top
              and "may be greeted by name and version" in flat_top
              and "headed Start fresh? , unless the board was recognised" in flat_top
              and "tick Erase everything first ." in flat_top
              and "Erase device" not in flat_top)
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
        # Site 1.0.0: the installer's dashboard sends a board read before it
        # joined Wi-Fi here with no address, so this is a page people land on.
        noaddr = (conn.split('<div class="board-at unknown" id="noaddr">')[1]
                  .split("</div>")[0] if 'id="noaddr"' in conn else "")
        flat_n = " ".join(re.sub(r"<[^>]+>", " ", html.unescape(noaddr)).split())
        check("and says why there is none, and the three ways, in order",
              "before it had joined your Wi-Fi" in flat_n
              and noaddr.count("<li>") == 3 and "<ol>" in noaddr
              and flat_n.index("By name.") < flat_n.index("From the board itself.")
              < flat_n.index("From your router.")
              and "Hostname" in flat_n and "unleashed.local" in flat_n
              and "open Logs & Console in the installer, then press the board's reset "
                  "button" in flat_n
              and "Reset Device" in flat_n
              and "online 192.168.0.109 dial in: telnet 192.168.0.109 6400" in flat_n
              and "list of connected devices" in flat_n)
        check("and gives the default sysop password, the warning, and the setup guide",
              "sysop password is <code>unleashed</code>" in flat_c
              and "Change it before anything else." in flat_c
              and 'href="/setup"' in conn and 'href="/install#the-sysop-password"' in conn)

        # The copy of ESP Web Tools sends a telnet:// address there, and says
        # it was changed, as its licence requires.
        print("The installer's telnet link")
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
        # Site 1.0.0: the dashboard's item is always there. With no URL yet
        # (a board read before it joined Wi-Fi) it is Telnet details to
        # /connected with no fragment; the page after a successful Wi-Fi
        # step keeps its guard, because by then there is a URL or nothing
        # to say.
        dash = (dlg_src[dlg_src.index("_renderDashboard(){"):
                        dlg_src.index("_renderDashboardNoImprov(){")]
                if "_renderDashboard(){" in dlg_src else "")
        check("the dashboard always offers Telnet details, to /connected when the "
              "board has sent no address yet",
              'href=${void 0===this._client.nextUrl?"/connected":/^telnet:\\/\\//i.test('
              'this._client.nextUrl)?"/connected#"+this._client.nextUrl.slice(9)' in dash
              and '${void 0===this._client.nextUrl||/^telnet:\\/\\//i.test(this._client'
                  '.nextUrl)?"Telnet details":"Visit Device"}' in dash
              and 'void 0===this._client.nextUrl?"":s`' not in dash
              and dlg_src.count('void 0===this._client.nextUrl?"":s`') == 1)
        check("and the notice at its top says so",
              "4. The dashboard of a board that answered over Improv always offers"
              in dlg_src[:6000]
              and "and to /connected, which says how to find" in dlg_src[:6000])
        check("and the vendor README records upstream's checksum for the file",
              "6dcfc30fb4bbf18e19a141c5eb9a694edafc5d4480b45762c221173f47effdb5"
              in open(os.path.join("vendor", "esp-web-tools", "README.md"),
                      encoding="utf-8").read())

        # 0.22.1. Rob updated his own board from /install and the dialog
        # asked "Erase device ... All data on the device will be lost",
        # which reads as "you are about to lose everything" to somebody with
        # a board full of accounts. Checked in the chunk as the server hands
        # it to a browser, at the path the page loads it from.
        print("The installer's erase question, and the Update button")
        code, _ct, served = (fetch(S.EWT_BASE + dlg[0]) if len(dlg) == 1
                             else (0, "", b""))
        served = served.decode("utf-8") if code == 200 else ""
        flat_d = " ".join(served.split())
        check("the served dialog asks Start fresh?, in words that say what is kept",
              code == 200 and served == dlg_src
              and '_renderAskErase(){return["Start fresh?",s`' in served
              and "Updating a board you already run? Leave this unticked: your "
                  "accounts, settings, mail and forums are kept. Tick it only for a "
                  "brand-new board, or to wipe this one and start over." in flat_d
              and "Erase everything first </label>" in flat_d)
        check("and no longer says all data on the device will be lost",
              "All data on the device will be lost" not in served
              and "All data on the device will be erased" not in served
              and 'return["Erase device"' not in served)
        check("its Install is Install or update, on both dashboards",
              served.count("`Install or update ${this._manifest.name}`") == 2
              and "`Install ${this._manifest.name}`" not in served)
        # The Update button. Nobody can click through the dialog in a test,
        # so the proof is the shape of the code: the erase flag is written
        # in exactly two places, both of which store false under the key,
        # and the one line that erases reads the argument that is forced
        # false under the key a second time.
        check("with unleashed_update, _startInstall stores false whatever it is asked",
              '_startInstall(e){this._state="INSTALL",this._installErase='
              '!(this._manifest&&this._manifest.unleashed_update)&&e,' in served
              and served.count("_installErase=") == 2
              and "this._installErase=!1," in served)
        check("and _confirmInstall hands the flasher false, the only thing that erases",
              "this._manifest,!this._manifest.unleashed_update&&this._installErase)}"
              in served
              and served.count(".eraseFlash()") == 2
              and 's&&(n({state:"erasing"' in served
              and "!0===this.IS_STUB&&!0===e.eraseAll&&await this.eraseFlash()" in served
              and served.count("eraseAll:!1") == 1 and "eraseAll:!0" not in served)
        check("and neither dashboard opens the erase question or offers Erase User Data",
              "this._isSameFirmware||this._manifest.unleashed_update?this._startInstall(!1)"
              in served
              and "this._manifest.unleashed_update?this._startInstall(!1):"
                  "this._manifest.new_install_prompt_erase" in served
              and "this._isSameVersion&&!this._manifest.unleashed_update?s`" in served
              and "this._isSameVersion&&!this._manifest.unleashed_update)"
                  'e="Erase User Data"' in served)
        check("and the notice at its top lists the change",
              "3. A manifest carrying \"unleashed_update\": true" in dlg_src[:4000]
              and '"Start fresh?"' in dlg_src[:4000]
              and '"Erase everything first"' in dlg_src[:4000])
        # A new path for the changed bundle, so a browser holding the old
        # dialog for its day of cache fetches the new one; the old path
        # still answers, for a tab left open across a deploy.
        check("the bundle is served under a path carrying this site's revision",
              S.EWT_BASE == "/install/esp-web-tools/" + S.EWT_VERSION + "-"
                            + str(S.EWT_REV) + "/"
              and S.EWT_REV >= 3
              and fetch("/install/esp-web-tools/" + S.EWT_VERSION + "/"
                        + dlg[0])[0] == 200)
        # 1.0.0 moved it to -3; a tab still holding -2's entry point fetches
        # the rest of the bundle from -2, so every earlier path answers.
        old_paths = [fetch("/install/esp-web-tools/" + S.EWT_VERSION + "-" + str(n) + "/"
                           + dlg[0]) for n in range(1, S.EWT_REV + 1)]
        check("and every earlier revision's path still answers, with today's files",
              all(c == 200 and b.decode("utf-8") == dlg_src for c, _t, b in old_paths)
              and fetch("/install/esp-web-tools/" + S.EWT_VERSION + "-"
                        + str(S.EWT_REV + 1) + "/" + dlg[0])[0] == 404)

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
              all(f'<span>Site version {newest}</span>'
                  '<span>&copy; 2026 Robert Mech</span>' in f
                  and '<span><a href="https://www.gnu.org/licenses/gpl-3.0.html">'
                      "GNU GPL v3 or later</a></span></p>" in f
                  and f.rindex('class="colophon"') > f.rindex('class="lbl"')
                  for f in feet))
        check("each piece of it kept whole, so a phone wraps between them",
              "footer .colophon span { white-space:nowrap; display:inline-block;"
              in get("/")[1])
        # L3, site 1.2.1: no separator is text any more. A dot is drawn in
        # front of every link but the first, and a row that wraps drops the
        # dot of the link that starts the new line, so no line of the
        # footer ends (or starts) on one.
        css_f = get("/")[1]
        check("the footer's separators are drawn, never text that can dangle",
              all('<span class="row">' in f
                  and "&middot;" not in f[f.index('<span class="row">'):f.index("</footer>")]
                  for f in feet)
              and "footer .row { display:block; overflow:hidden; }" in css_f
              and "footer .row a::before, footer .colophon span + span::before" in css_f
              and "margin-left:-1.5ch" in css_f
              and "footer .row .lbl + a::before { content:none; }" in css_f
              and "line-height:1.6; overflow:hidden; }" in css_f)

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
                  and '<svg class="logo"' in page.split('<a class="home"')[1].split("</a>")[0]
                  for page, want in homes.values()))
        # Site 1.2.1: the wordmark is a drawing made from LOGO_ROWS, named
        # for a screen reader, sized by the stylesheet, and the <pre> is gone.
        mark = S.LOGO_SVG
        rows_on = sum(sum(1 for ch in r if ch in "\u2588\u2580\u2584") for r in S.LOGO_ROWS)
        check("the wordmark is an SVG drawn from LOGO_ROWS, with a name",
              mark.startswith('<svg class="logo" viewBox="0 0 %d %d" role="img" '
                              'aria-label="\u00b5nleashed"'
                              % (6 * max(len(r) for r in S.LOGO_ROWS), 10 * len(S.LOGO_ROWS)))
              and "<title>\u00b5nleashed</title>" in mark
              and mark.count("<g fill=") == len(S.LOGO_ROWS)
              and sum(int(w) for w in re.findall(r'width="(\d+)"', mark)) == 6 * rows_on
              and '<pre class="logo"' not in homes["a page"][0]
              and "svg.logo { display:block; width:min(35rem, calc(100vw - 2.5rem));"
                  in homes["a page"][0])

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
        # Site 1.3.0: link previews use the 1200 x 630 card, large, and the
        # avatar stays the home-screen icon.
        check("every face names the card for link previews, large, by an absolute address",
              all(re.search(r'<meta property="og:image" content="https://[^"]+/og-card\.png">', p)
                  and '<meta property="og:image:width" content="1200">' in p
                  and '<meta property="og:image:height" content="630">' in p
                  and '<meta property="og:image:type" content="image/png">' in p
                  and '<meta name="twitter:card" content="summary_large_image">' in p
                  and re.search(r'<meta name="twitter:image" content="https://[^"]+/og-card\.png">', p)
                  and '<meta property="og:image:alt" content="The \u00b5nleashed wordmark' in p
                  and '<meta property="og:title" content="' in p
                  and '<meta property="og:description" content="' in p
                  for p in faces_a))
        code, ctype, blob = fetch("/og-card.png")
        check("and og:image resolves to a 1200 x 630 PNG",
              code == 200 and ctype == "image/png" and png_size(blob) == (1200, 630)
              and os.path.isfile(os.path.join("brand", "make_ogcard.py")))
        # The pages the round 3 specification gives words of their own.
        def og(path, prop):
            m = re.search(r'<meta property="og:%s" content="([^"]*)">' % prop, get(path)[1])
            return html.unescape(m.group(1)) if m else None
        check("the front page's preview says what it is, not a board count",
              og("/", "title") == "\u00b5nleashed: your own online community, on a "
                                  "device that fits in your hand"
              and og("/", "description").startswith("Chat and messages for your class")
              and "listed" not in og("/", "description"))
        check("/directory's preview carries the live figures",
              og("/directory", "title") == "Communities running right now"
              and re.search(r"^\d+ communit(y|ies) online and \d+ (person|people) "
                            r"connected right now\.", og("/directory", "description")))
        check("and every page in the table has its own title and words",
              all(og(p_, "title") == t_ and (d_ is None or og(p_, "description") == d_)
                  for p_, (t_, d_) in S.OG_PAGES.items()))
        check("and as the icon a phone puts on its home screen",
              all('<link rel="apple-touch-icon" href="/apple-touch-icon.png">' in p
                  for p in faces_a))
        # Not in static/, or the manifesto's gallery would show a logo.
        check("and it lives in brand/ with its generator, not in static/",
              os.path.isfile(os.path.join("brand", "make_avatar.py"))
              and os.path.isfile(os.path.join("brand", "unleashed-avatar.svg"))
              and not any("avatar" in n for n in os.listdir("static")))

        print("Every other page is still script-free")
        scripted = [p for p in ("/", "/different", "/about", "/data", "/build", "/whofor",
                                "/terminals", "/firstcall", "/forward", "/how",
                                "/rules", "/privacy", "/kids", "/teachers",
                                "/sdcard", "/dialing", "/author", "/donate",
                                "/setup", "/upgrade")
                    if "<script" in get(p)[1]]
        check("nothing else on the site loads any JavaScript"
              + ("" if not scripted else "  <- " + ", ".join(scripted)),
              not scripted)
        # The board list and /badges carry the badge filter and search
        # (0.22.0): one inline script each, this site's own, pinned to the
        # text in server.py, and doing nothing but reading and hiding.
        for path in ("/directory", "/badges", "/?b=petscii&b=ham"):
            pg = get(path)[1]
            scr = re.findall(r"<script[^>]*>(.*?)</script>", pg, re.S)
            check(f"{path}: its one script is the badge script written here, with no src",
                  len(scr) == 1 and "<script src" not in pg
                  and "<script>" + scr[0] + "</script>" == S.BADGE_JS)
        js_b = S.BADGE_JS
        check("which writes only text and the hidden attribute, sends nothing, "
              "stores nothing and never navigates",
              "textContent" in js_b and ".hidden=" in js_b
              and "history.replaceState" in js_b
              and not any(w in js_b for w in (
                  "innerHTML", "outerHTML", "insertAdjacent", "document.write", "fetch",
                  "XMLHttpRequest", "sendBeacon", "WebSocket", "eval", "Function(",
                  "cookie", "Storage", "location.href", "location.assign",
                  "location.replace", "location.reload", "window.open", "setTimeout",
                  "setInterval", "import(", "src=", "http")))
        check("and the only things it reads from the address are its path and "
              "its fragment",
              sorted(set(re.findall(r"location\.\w+", js_b)))
              == ["location.hash", "location.pathname"])

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
        check("the build page links to it, as a button",
              '<a class="go" href="/sdcard">Add an SD card</a>' in get("/build")[1])

        # A Chromebook, as it is: one you control usually can, a managed one
        # usually cannot without its administrator, Chrome alone never can.
        flat_t = " ".join(term.split())
        check("the Chromebook section leads with who controls it",
              "A Chromebook you control can usually join a board" in flat_t
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
        _, hwp = get("/hardware")
        flat_h = " ".join(hwp.split())
        # Site 1.2.1 (R1, L1): the chips moved to /hardware as a list, which
        # reads on a phone where the three-column table broke "ESP32-WROOM-32E"
        # over three lines. /build keeps a link and no table of its own.
        check("the tested boards page says which ESP32s run it",
              "<b>ESP32-WROOM-32E: yes, tested.</b>" in hwp
              and "<b>ESP32-S2, ESP32-C3 and ESP32-C5: no.</b>" in hwp
              and "<b>ESP32-P4: no.</b>" in hwp
              and "<b>ESP32-WROVER: should work, not yet tested.</b>" in hwp
              and has_h(hwp, 2, "Other chips"))
        check("and gives no caller count for a part nobody has measured",
              "which that image does not use" in flat_h
              and "room for more callers" not in flat_h)
        check("the build page has no chip table and links the tested boards",
              "<table" not in build.split("<article>")[1]
              and "ESP32-C3" not in build and "ESP32-P4" not in build
              and 'href="/hardware"' in build)
        check("the build page links the SD card and the lights pages",
              'href="/sdcard"' in build and 'href="/lights"' in build)
        # The dev board's facts moved with the chips (R2): memory and power
        # on /hardware, and the bare-module notes stay with the build.
        check("the dev board's memory and power are on the tested boards page",
              "520 KB of SRAM and 4 MB of flash" in flat_h
              and "a little under 400 mA" in flat_h
              and "520 KB" not in flat_b and "400 mA" not in flat_b
              and "EN pulled up" in flat_b)
        # H1, Rob's spectrum: three stops, each with the words the drawing
        # shows said again in the page, with links, because the drawing is
        # aria-hidden.
        spec = S.ART["hardware-spectrum"]
        check("the tested boards page opens with the spectrum",
              spec in hwp
              and hwp.index(spec) < hwp.index('id="esp32-dev-board-base"')
              and spec.startswith('<svg class="art spectrum" viewBox="-4 -2 362 160"')
              and all(f">{s[1]}</text>" in spec and f">{s[3]}</text>" in spec
                      and f">{s[4]}</text>" in spec for s in S.SPECTRUM_STOPS))
        # Site 1.2.5, Rob: a speed per board, "Fast, Faster, Fastest", and
        # every one of them says it is expected, because nothing has been
        # measured yet. In the spectrum (fast, fast, fastest), in each
        # board's facts list, the camera boards included, and in one line
        # of the page's own words.
        spd = re.findall(r'<text class="ink spd"[^>]*>(\w+) <tspan[^>]*>\(expected\)</tspan></text>', spec)
        hw5 = hwp.split("<article>")[1].split("</article>")[0]
        facts_ok = all(
            f"<dt>Speed</dt><dd>{S.BOARD_SPEED[b['dir']]} "
            '<span class="exp">(expected, not yet measured)</span></dd>'
            in S.board_html([b["dir"]]) and S.board_html([b["dir"]]) in hw5
            for b in S.BOARDS + S.SHOWN_BOARDS + S.SOON_BOARDS)
        check("the speeds render, each one marked expected",
              spd == ["fast", "fast", "fastest"]
              and all("Expected to be " in s[7] and "not yet measured" in s[7]
                      for s in S.SPECTRUM_STOPS)
              and facts_ok
              and [S.BOARD_SPEED[d] for d in ("esp32", "esp32-sd", "esp32-fncam",
                                              "esp32s3", "esp32s3-cam")]
                  == ["Fast", "Fast", "Faster", "Fastest", "Fastest"]
              and "The speeds are expected, not measured" in " ".join(hw5.split())
              and "side by side" in " ".join(hw5.split()))
        # Site 1.2.5, Rob: a seal on each board's picture, "flash & go" for
        # all four, the S3 camera board's marked expected, each told to a
        # screen reader in words, and a line in the intro saying what it
        # means. Two levels only: "a little wiring" is for add-ons and no
        # board wears it.
        seals = re.findall(r'<div class="hwpic[^"]*">.*?(<svg class="art seal[^"]*"[^>]*>.*?</svg>)</div>',
                           hw5, re.S)
        # Site 1.2.7: the dev board with a card wears the second level, a
        # little wiring, the first board to, and the intro says both.
        go = [x for x in seals if "FLASH &amp; GO</text>" in x]
        wire = [x for x in seals if ">A LITTLE</text>" in x and ">WIRING</text>" in x]
        check("every board's picture wears its seal, four flash and go, one a little wiring",
              len(seals) == 5 and len(go) == 4 and len(wire) == 1
              and all('role="img" aria-label="Flash and go' in x for x in go)
              and 'role="img" aria-label="A little wiring' in wire[0]
              and sum(">expected</text>" in x for x in seals) == 1
              and ">expected</text>" in S.seal_html(S.BOARD_SEAL["esp32s3-cam"])
              and all(S.BOARD_SEAL[b["dir"]] == "go" for b in S.BOARDS)
              and [d for d, v in S.BOARD_SEAL.items() if v == "wire"] == ["esp32-sd"]
              and "<b>Flash &amp; go</b>:" in hw5 and "<b>A little wiring</b>:" in hw5
              and "svg.art.seal .rb {" in hwp and "article .hwb .hwpic svg.art.seal {" in hwp)
        # Site 1.3.3, Rob: the 1.3.1 ribbon was bigger than the board. A seal
        # the size of FLASH & GO, a padlock and SECURE*, in the opposite
        # corner, on the two S3 boards' pictures and nowhere else; its
        # footnote a Secure row of the facts, SSH with its glossary note and
        # the version linked to the roadmap. Each S3 entry says 1.2.0 in
        # words, and the classic ESP32 entries say nothing about SSH.
        hsecs = {sid: hw5.split(f'id="{sid}"')[1].split("<h2")[0]
                 for sid in ("esp32-dev-board-base",
                             "esp32-dev-board-base-sd-card-for-storage",
                             "waveshare-esp32-s3-lcd-1-47",
                             "freenove-esp32-camera-board", "esp32-s3-camera-board")}
        secs = re.findall(r'<svg class="art seal sec"[^>]*>.*?</svg>', hw5, re.S)
        s3w, s3c = hsecs["waveshare-esp32-s3-lcd-1-47"], hsecs["esp32-s3-camera-board"]
        others = ("esp32-dev-board-base", "esp32-dev-board-base-sd-card-for-storage",
                  "freenove-esp32-camera-board")
        note = ('<dt>Secure</dt><dd>* Encrypted connections (<span class="gl"')
        check("the Secure seal is on the two S3 boards' pictures only, FLASH & GO's "
              "size, bottom right, with its asterisk",
              len(secs) == 2 and "lockr" not in hw5
              and all('viewBox="0 0 72 24"' in x
                      and 'SECURE<tspan class="ast">*</tspan></text>' in x
                      and 'role="img" aria-label="Secure, with an asterisk: encrypted '
                          'connections over SSH are coming in version 1.2.0' in x
                      for x in secs)
              and '<div class="hwpic sec">' in s3w and '<div class="hwpic sec">' in s3c
              and 'class="art seal sec"' in s3w and 'class="art seal sec"' in s3c
              and all('class="art seal sec"' not in hsecs[k]
                      and '<div class="hwpic">' in hsecs[k] for k in others)
              and "article .hwb .hwpic svg.art.seal.sec {" in hwp
              and "svg.art.seal tspan.ast {" in hwp
              and S.BOARD_SSH == {"esp32s3": (1, 2, 0), "esp32s3-cam": (1, 2, 0)}
              and "a padlock and <b>Secure</b>, with an asterisk for now"
                  in " ".join(hw5.split()))
        check("and its footnote is a Secure row of each S3 board's facts, SSH "
              "explained and the version linked to the roadmap",
              all(note in x and '<a href="/roadmap">coming in version 1.2.0</a></dd>' in x
                  and x.index(note) < x.index("</dl>") for x in (s3w, s3c))
              and all("<dt>Secure</dt>" not in hsecs[k] for k in others))
        check("and each S3 entry says SSH comes in firmware 1.2.0, in words",
              "<b>Encrypted connections, coming in firmware 1.2.0.</b>" in s3w
              and "SSH" in s3w and 'class="gl"' in s3w
              and "<b>coming in firmware 1.2.0</b> with the Waveshare"
                  in " ".join(s3c.split())
              and "not built yet" not in " ".join(hw5.split())
              and all("SSH" not in re.sub(r"<[^>]+>", "", hsecs[k]) for k in others)
              and "encrypted" in S.GLOSSARY["SSH"].lower())
        # Site 1.2.7, Rob: "esp32 is misleading with flash and go, it has to
        # have an sd card". The bare board says what it does without one and
        # points at the second entry, which summarises and links /sdcard.
        sda = "esp32-dev-board-base-sd-card-for-storage"
        bare = hw5.split('id="esp32-dev-board-base"')[1].split("<h2")[0]
        sdsec = hw5.split(f'id="{sda}"')[1].split("<h2")[0] if f'id="{sda}"' in hw5 else ""
        flat_sd = " ".join(sdsec.split())
        check("the dev board with an SD card is an entry of its own, a little wiring",
              S.SHOWN_BOARDS[0]["page"] == "/hardware#" + sda
              and S.board_html(["esp32-sd"]) in sdsec
              and 'class="art board big wide"' in sdsec
              and "A LITTLE</text>" in sdsec and "FLASH &amp; GO" not in sdsec
              and f'<a href="{S.BOARDS[0]["buy"]}" rel="sponsored">Amazon</a> (affiliate link) '
                  "for the board; the SD card module is a couple of dollars anywhere" in sdsec
              and "everything the BBS does" in flat_sd and "about $8" in flat_sd
              and "about half an hour" in flat_sd
              and "four signal wires plus power" in flat_sd
              and '<p class="next"><a class="go" href="/sdcard">' in sdsec
              and "svg.art.board.big.wide {" in hwp)
        check("and the bare board says what needs a card, and links it",
              "FLASH &amp; GO" in bare and f'href="#{sda}"' in bare
              and "chat, mail, accounts" in " ".join(bare.split())
              and "file areas, forums, backups kept on the card, and the photos"
                  in " ".join(bare.split()))
        # Site 1.2.7, Rob's bench: the Freenove's sensor is not the OV2640
        # Freenove document. His kit carries a GC0308 (640x480, no JPEG),
        # the firmware drives both, and the board is running, not a port.
        fn = hw5.split('id="freenove-esp32-camera-board"')[1].split("<h2")[0]
        flat_fn = " ".join(fn.split())
        _, cam7 = get("/camera")
        flat_c7 = " ".join(cam7.split())
        fnb = S.BOARD_BY_DIR["esp32-fncam"]
        check("the Freenove's camera varies by batch: GC0308 at 640x480, or OV2640",
              "GC0308" in fnb["camera"] and "OV2640" in fnb["camera"]
              and "640x480" in fnb["camera"]
              and "varies between batches" in flat_fn and "GC0308" in flat_fn
              and "640x480 at most" in flat_fn and "works with either" in flat_fn
              and "varies between batches" in flat_c7 and "GC0308" in flat_c7
              and "works with either" in flat_c7
              and "| Resolution |" not in cam7
              and "<td>320x240 or 640x480, on either camera." in cam7
              and not re.search(r"\b(800x600|1024x768|1600x1200)\b|(?<![\d.])[1-9] ?(MP|megapixels?)\b",
                                flat_fn + flat_c7)
              # every OV2640 on either page shares its sentence with the GC0308
              and all("GC0308" in s for s in re.split(r"(?<=[.:])\s", flat_fn + " " + flat_c7)
                      if "OV2640" in s))
        check("and it is running on the bench, still coming soon to the installer",
              "under way" not in S.board_html(["esp32-fncam"]) and "under way" not in flat_fn
              and "running on Rob's bench" in S.board_html(["esp32-fncam"])
              and "coming soon to" in S.board_html(["esp32-fncam"])
              # Site 1.2.9: in BOARDS, but waiting for a release, so not on
              # the picker while none on disk carries it.
              and "esp32-fncam" not in {b["dir"] for b in S.picker_boards()})
        _, diff5 = get("/different")
        check("and nowhere else",
              "(expected" not in diff5 and "Fastest" not in diff5)
        # Site 1.2.2, Rob: each stop is a link to its board, and the drawing
        # is a group of links a screen reader can reach, each saying in words
        # what its column shows. The overview names the class of board and
        # the section it links to names the exact board.
        stops = re.findall(r'<a class="stp s\d" href="([^"]+)" aria-label="([^"]+)">', spec)
        check("and each stop is a link, told to a screen reader in words",
              'role="group" aria-label="Three ways to build a board"' in spec.split(">")[0]
              and [h for h, _ in stops] == ["#esp32-dev-board-base",
                                          "#esp32-dev-board-base-sd-card-for-storage",
                                          "#waveshare-esp32-s3-lcd-1-47"]
              and all("About $" in a for _, a in stops)
              and 'id="esp32-dev-board-base"' in hwp
              and 'id="waveshare-esp32-s3-lcd-1-47"' in hwp)
        check("the overview says ESP32-S3 board, never the brand",
              ">ESP32-S3 board</text>" in spec and "Waveshare" not in spec
              and "Waveshare" not in hwp.split('id="esp32-dev-board-base"')[0])
        # The motion: every piece of it declared where reduced motion stops
        # it, the lamp at rest on the middle stop, transforms and opacity only.
        art_all = hwp.split("svg.art { display:block;")[1].split("</style>")[0]
        still, moving_s = art_all.split("@media (prefers-reduced-motion: no-preference) {")
        check("and its motion is declared only where reduced motion stops it",
              "svg.art.spectrum .sl { transform-box:fill-box" in moving_s
              and "svg.art.spectrum .sdot { animation:" in moving_s
              and "svg.art.spectrum a:hover .up," in moving_s
              and not re.search(r"svg\.art\.spectrum[^{]*\{[^}]*(animation|transition):",
                                still)
              and f'cx="{S.SPECTRUM_PARK}"' in spec
              and S.SPECTRUM_PARK == S.SPECTRUM_STOPS[1][0])
        spec_kf = re.findall(r"@keyframes (spec\w+) \{(.*?)\}\s*\}", art_all, re.S)
        check("and it moves by transform and opacity alone",
              len(spec_kf) == 6
              and all(set(re.findall(r"([a-z-]+):", body)) <= {"transform", "opacity"}
                      for _, body in spec_kf))
        check("and says it in words too, every figure an estimate",
              "functional, and the lowest cost. About $5" in flat_h
              and "economical and usable. About $8" in flat_h
              and "advanced capabilities. About $20" in flat_h
              and all(s[3].startswith("about ") and s[4].startswith("about ")
                      for s in S.SPECTRUM_STOPS))
        s3sec = hwp.split('id="waveshare-esp32-s3-lcd-1-47"')[1].split('id="other-chips"')[0]
        check("the S3's section says it needs no wiring, and no build pages",
              "No wiring, and none of the build pages" in " ".join(s3sec.split())
              and 'href="/sdcard"' in s3sec and 'href="/lights"' in s3sec)
        check("no page says any 4 MB module will do",
              "Any module with the same flash will do" not in flat_b
              and "Any module with 4 MB of flash works" not in
                  " ".join(get("/teachers")[1].split()))

        # Site 1.2.2, Rob on /build: "Need clearer calls to action. The blue
        # blends in and tested boards reads wierd after 'a board' its a
        # microcontroller and it should read like something like 'A
        # compatible ESP32 board' and then go into it."
        need = build.split('id="what-you-need"')[1].split("<h2")[0]
        flat_n = " ".join(need.split())
        check("/build's What you need leads each item with the thing itself",
              "<li><b>A compatible ESP32 board.</b> A small computer with Wi-Fi built in" in flat_n
              and "<li><b>A USB data cable.</b>" in flat_n
              and "<li><b>2.4 GHz Wi-Fi.</b>" in flat_n
              and "Tested boards</a> has" not in flat_n
              and "special handling" not in flat_n and "EN pulled up" not in flat_n)
        check("and its next step is a button to the tested boards",
              '<p class="next"><a class="go" href="/hardware">Choose a board</a></p>'
              in need and 'href="#on-a-bare-module"' in need
              and 'id="on-a-bare-module"' in build)
        # A next step is a button, one a section at most, and a button that
        # is not the installer's own never says Install.
        crowded, says_install = [], []
        for md in sorted(pathlib.Path("pages").glob("*.md")):
            body = get("/" + md.stem)[1]
            for part in body.split("<h2")[1:] or [body]:
                if part.count('<p class="next">') > 1:
                    crowded.append(md.stem)
            if re.search(r'<a class="go"[^>]*>[^<]*Install', body):
                says_install.append(md.stem)
        check("a section carries one next-step button at most"
              + ("" if not crowded else "  <- " + ", ".join(crowded)), not crowded)
        check("and none of them says Install"
              + ("" if not says_install else "  <- " + ", ".join(says_install)),
              not says_install)
        # A page's title used as a sentence's subject ("Tested boards has the
        # two ...") reads as a typo to anybody who has not seen that page yet.
        subj = []
        for md in sorted(pathlib.Path("pages").glob("*.md")):
            text = re.sub(r"<!--.*?-->", "", md.read_text(encoding="utf-8"), flags=re.S)
            flat_md = " ".join(text.split())
            for m in re.finditer(r"(?:^|[.!?] |\*\* |- )\[([A-Z][^\]]*)\]\((?:/|#)[^)]*\) "
                                 r"(has|have|says|covers|lists|is|are|explains|shows|"
                                 r"goes|takes|names)\b", flat_md):
                subj.append(f"{md.stem}: {m.group(1)}")
        check("no page uses a link's title as a sentence's subject"
              + ("" if not subj else "  <- " + " | ".join(subj)), not subj)
        # The body link is 1.02:1 from the text around it, so the underline is
        # what marks it (WCAG 1.4.1): a deliberate one, heavier under the
        # pointer. The outlined buttons' edge is 4.2:1 on the page.
        css_l = get("/build")[1]
        check("a link is marked by its underline, not its colour alone",
              "a { color:var(--dial); text-decoration-thickness:0.075em;" in css_l
              and "a:hover { text-decoration-thickness:0.14em; }" in css_l
              and "border:1px solid #4a7a99; border-radius:0.375rem;" in css_l
              and ".cta a.btn2 { color:var(--dial); background:transparent; "
                  "border:1px solid #4a7a99; }" in css_l)

        # ------------------------------------------------------------------
        # The freedoms beside the wordmark. The board's own words from its
        # welcome screen, on every page, one at a time for a reader who
        # does not mind motion and standing still for one who does.
        # ------------------------------------------------------------------
        # Site 1.3.0 (Rob: "bridge them into the lingo for BBSes ... pop-ups
        # with dotted underline for terms"). One table of definitions, a
        # BBS word marked where a page wants it explained, no script and no
        # title attribute, and a definition a screen reader is pointed at.
        print("The glossary")
        glossed = {}
        for f in sorted(pathlib.Path("pages").glob("*.md")):
            for m in re.finditer(r"\[\[([^\[\]]+)\]\]", f.read_text(encoding="utf-8")):
                glossed.setdefault(m.group(1), f.name)
        unknown = [f"{w} ({f})" for w, f in glossed.items() if S.gloss_key(w) is None]
        check("every [[term]] in the pages has an entry in the table"
              + ("" if not unknown else "  <- " + ", ".join(unknown)),
              glossed and not unknown)
        check("and every entry is one sentence or two, short enough for the box",
              all(20 <= len(d) <= 160 and d.endswith(".") for d in S.GLOSSARY.values())
              and all(S.gloss_key(k) is not None for k in S.GLOSSARY_FORMS)
              and set(S.GLOSSARY_FORMS.values()) <= set(S.GLOSSARY))
        leaked = [p_ for p_ in ("/", "/directory", "/whofor", "/firstcall", "/build",
                                "/terminals", "/forward", "/install", "/hardware",
                                "/different", "/privacy", "/teachers", "/setup")
                  if "[[" in get(p_)[1].split("</nav>")[1]]
        check("no page shows the markup instead of the term"
              + ("" if not leaked else "  <- " + ", ".join(leaked)), not leaked)
        fc = get("/firstcall")[1]
        term = re.search(r'<span class="gl" tabindex="0" aria-describedby="(gl\d+)">'
                         r'sysop<span class="gt" role="tooltip" id="(gl\d+)">([^<]+)</span></span>',
                         fc)
        check("a term is focusable, points a screen reader at its definition, and says it",
              term is not None and term.group(1) == term.group(2)
              and term.group(3) == html.escape(S.GLOSSARY["sysop"])
              and " title=" not in fc.split("<article>")[1])
        css_g = fc.split("<style>")[1]
        check("the definition shows on focus and a tap, and on hover only with a mouse",
              ".gl:focus .gt { display:block; }" in css_g
              and "@media (hover: hover) and (pointer: fine) {\n  .gl:hover .gt { display:block; }"
                  in css_g
              and ".gl .gt { display:none;" in css_g
              and ".gl { position:relative; border-bottom:1px dotted currentColor;" in css_g)
        check("and on a phone it is a bar across the foot of the screen, not off its edge",
              ".gl .gt { position:fixed; left:1rem; right:1rem; top:auto; bottom:1rem;" in css_g)
        ids = re.findall(r'aria-describedby="(gl\d+)"', get("/different")[1])
        check("ids are unique on a page", ids and len(ids) == len(set(ids)))

        # The one step between "Try one first" and a board.
        print("Joining, on /directory")
        dj = get("/directory")[1]
        js_ = dj.split('<div class="joinstep"')[1].split("</div>")[0] \
            if '<div class="joinstep"' in dj else ""
        check("/directory says, before the list, what app to join with",
              "First time? You need a free app to join" in js_
              and dj.index('class="joinstep"') < dj.index('id="nq"')
              and 'href="https://play.google.com/store/apps/details?id=com.terminator.android"'
                  in js_
              and 'href="https://apps.apple.com/us/app/terminator-bbs-terminal/id6759012939"'
                  in js_
              and 'href="https://apps.apple.com/us/app/muffinterm/id1583236494"' in js_
              and 'href="https://syncterm.bbsdev.net/"' in js_
              and 'href="/terminals">Apps for joining</a>' in js_
              and 'class="gl"' in js_)
        # Site 1.3.1 (Rob's own app on Android): Termius, beside TERMinator,
        # on the join step and on /terminals.
        tp = get("/terminals")[1]
        check("Termius is on the join step and on /terminals, free, with telnet",
              "<b>Termius</b>, free for" in js_ and "works well too." in js_
              and 'href="https://play.google.com/store/apps/details?id=com.server.auditor.ssh.client"'
                  in js_
              and 'href="https://apps.apple.com/us/app/termius-modern-ssh-client/id549039908"'
                  in js_
              and js_.index("TERMinator") < js_.index("Termius") < js_.index("SyncTERM")
              and '<a href="https://termius.com/">Termius</a>' in tp
              and "Telnet is in the free plan." in tp
              and "telnet is in its free plan" in " ".join(tp.split()))
        check("the menu's first entry is Communities online, and the wordmark goes home",
              '<nav><a href="/directory">Communities online</a>' in get("/whofor")[1]
              and '<a class="home" href="/"' in get("/whofor")[1])

        # The Telnet BBS Guide, on /how.
        hw = get("/how")[1]
        check("/how says how to list on the Telnet BBS Guide too, in steps",
              '<h2 id="the-telnet-bbs-guide">List your community on the Telnet BBS '
              "Guide too</h2>" in hw
              and hw.count("<li>", hw.index('id="the-telnet-bbs-guide"')) >= 5
              and "<b>Add Your BBS</b>" in hw and "<b>Contact Us</b>" in hw
              and 'href="https://www.telnetbbsguide.com/faqs/how-to-add-your-bbs-listing/"'
                  in hw
              and 'href="#the-telnet-bbs-guide"' in hw)

        print("The freedoms in the header")
        faces = {"the board list": get("/directory")[1],
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
              all(re.search(r'<div class="masthead"><a class="home" [^>]*><svg class="logo"', p)
                  and ticker_of(p) for p in faces.values()))
        check("with all ten freedoms, each with the line saying what it means",
              len(wanted) == 10
              and all(all(f"<b>{l}</b> <i>{n}</i>" in ticker_of(p)
                          for l, n in wanted) for p in faces.values()))
        check("in one list, named for a screen reader",
              all(ticker_of(p).count("<li>") == 10
                  and '<ul aria-label="Electronic freedom">' in ticker_of(p)
                  for p in faces.values()))
        # The frame, the heading drawn over it and the ten icons. The
        # words are never hidden: the fade is opacity, which leaves every
        # item in the accessibility tree, where visibility would take it out.
        check("and every picture in it hidden from one, and no word",
              all(ticker_of(p).count('aria-hidden="true"') == 12
                  for p in faces.values())
              and "visibility" not in resting and "visibility" not in moving)
        check("the board's own welcome line and licence are among them",
              all(w in labels for w in ("No ads", "No cloud", "Old and new",
                                        "Real hardware", "Free software")))
        # Site 1.3.0 (Rob): "No web" read as a contradiction on a website,
        # and three more were added. Each is true of the board as it ships.
        check("and the ones added for a newcomer, with no web left in them",
              all(w in labels for w in ("No platforms", "No hosting fees",
                                        "No outside costs"))
              and "No web" not in labels and "No browser" not in labels)
        # The board list carries the badge script since 0.22.0; it never
        # touches the panel, and no other face carries a script at all.
        check("and nothing on any face runs a script to move them",
              all("<script" not in p for k, p in faces.items() if k != "the board list")
              and "ticker" not in S.BADGE_JS and ".tf" not in S.BADGE_JS
              and faces["the board list"].count("<script") == 1)

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
            r"\.ticker li:nth-child\(\d+\), \.tf \.sg\d+ \{ animation-delay:(-?[\d.]+)s; \}",
            moving)]
        check("ten on one 40 second timeline, four seconds apart",
              "tkshow 40s" in moving and "tkseg 40s" in moving
              and len(delays) == 10
              and all(abs(b - a - 4) < 1e-9 for a, b in zip(delays, delays[1:])))
        # Each section of the menu opens on a different freedom, or a reader
        # clicking round would only ever see the first two.
        firsts = []
        for path, host in (("/directory", None), ("/", "about.example"), ("/whofor", None),
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
        cap_w = float(re.search(r"svg\.logo \{[^}]*width:min\(([\d.]+)rem,",
                                head_css).group(1))
        panel = float(re.search(r"\.ticker \{ display:block;[^}]*width:([\d.]+)rem",
                                head_css).group(1))
        gap = float(re.search(r"\.masthead \{[^}]*gap:0 ([\d.]+)rem",
                              head_css).group(1))
        shows = float(re.search(r"@media \(min-width: ([\d.]+)em\) \{\s*\.ticker",
                                head_css).group(1))
        need = (cap_w + 2 * 1 + gap + panel) * 1.33
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
            # The Update button's manifest (0.22.1): the same in every key,
            # plus the one the dialog served here reads as "never erase". It
            # keeps new_install_prompt_erase, because ESP Web Tools erases by
            # default without it, and a copy of the dialog that does not know
            # the extra key (upstream's, or a cached one from before 0.22.1)
            # must fall back to asking, box unticked, rather than to erasing.
            upd = S.firmware_manifest("0.19.2", update=True)
            check("the Update manifest is the install one plus unleashed_update",
                  upd is not None and upd.get("unleashed_update") is True
                  and {k: v for k, v in upd.items() if k != "unleashed_update"} == man
                  and "unleashed_update" not in man)
            check("and it still sets new_install_prompt_erase, so no dialog erases by default",
                  upd["new_install_prompt_erase"] is True)
            got = S.firmware_file("0.19.2/manifest-update.json")
            check("it is served beside the other, as JSON that carries the key",
                  got is not None and got[1].startswith("application/json")
                  and json.loads(got[0].decode()).get("unleashed_update") is True
                  and S.firmware_file("0.18.0/manifest-update.json") is None
                  and S.firmware_file("0.19.2/manifest-other.json") is None)
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
                  and 'manifest="/install/0.19.2/esp32/manifest.json"' in shown)
            check("with our own button and both refusal messages in its slots",
                  'slot="activate"' in shown and 'slot="unsupported"' in shown
                  and 'slot="not-allowed"' in shown)
            # "Kept" means a reader can go back to it, which a link to a
            # JSON file never let them do. It is a choice in the card's
            # board slot now, two native radios and no script: the checked
            # one decides which button, version line and notices link show.
            check("the older release is kept as a choice, the newest picked",
                  'manifest="/install/0.19.1/esp32/manifest.json"' in shown
                  and shown.count('name="fwver0"') == 2
                  and '<input type="radio" name="fwver0" id="fwv0_0" checked> 0.19.2'
                      in shown
                  and ".installer .b0 .r1{display:none}" in shown
                  and ".installer:has(#fwv0_1:checked) .b0 .r1{display:block}" in shown
                  and shown.count('<span class="no" slot="unsupported">') == 2)
            # The card said the version three times: on the button, in a
            # line under it, and again as release.txt's first line.
            check("the card says each version once, not on the button",
                  shown.count('class="meta ver r0"') == 1
                  and "Version 0.19.2, released 2026-09-21." in shown
                  and shown.count(">Install on a new board</button>") == 2
                  and "Install 0.19.2" not in shown and "A short note." not in shown)
            # Two buttons per release (0.22.1, Rob): the install as it was,
            # and Update my board on the manifest that can never erase. The
            # update one says nothing of its own on a browser that cannot
            # use it, and hides, so the reason is given once.
            check("each release has Install on a new board and Update my board",
                  shown.count(">Update my board</button>") == 2
                  and '<esp-web-install-button class="r0 upd" manifest="/install/'
                      '0.19.2/esp32/manifest-update.json"><button class="go upd" '
                      'slot="activate">' + S.BTN_ICON_UPDATE + 'Update my board</button>'
                      in shown
                  and 'manifest="/install/0.19.1/esp32/manifest-update.json"' in shown
                  and shown.index('manifest="/install/0.19.2/esp32/manifest.json"')
                      < shown.index('manifest="/install/0.19.2/esp32/manifest-update.json"')
                  and shown.count('<span slot="unsupported"></span>'
                                  '<span slot="not-allowed"></span>') == 2)
            # Site 1.2.0: the board slot is the board picker. The ESP32 is
            # picked to start with and says which firmware it would get; the
            # S3, with nothing on disk, says so and has no buttons.
            check("the picker offers each board, the ESP32 picked, its version said",
                  '<input type="radio" name="fwboard" id="fwb0" checked>'
                  + S.BOARD_ART_ESP32 in shown
                  and '<input type="radio" name="fwboard" id="fwb1">' + S.BOARD_ART_S3
                      in shown
                  and '<span class="bv">Firmware 0.19.2</span>' in shown
                  and '<span class="bv soon">Coming soon<span class="sep"' in shown
                  and '<div class="bsec b1"><p class="soon">There is no image for this '
                      "board on this site yet." in shown
                  and ".installer .bsec.b1{display:none}"
                      ".installer:has(#fwb1:checked) .bsec.b0{display:none}"
                      ".installer:has(#fwb1:checked) .bsec.b1{display:flex}" in shown
                  and "Board: ESP32" not in shown)
            # Site 1.2.7, Rob: the dev board with a card is a second entry on
            # /hardware and a display split only. The picker still has one
            # ESP32, and the new entry names the ESP32's own firmware.
            # Site 1.2.9 (Rob): the dev board is the Base choice, with or
            # without a card, and says so under its name. The Freenove is
            # in BOARDS but waits for a release, so with none carrying it
            # the picker has the same two rows as before.
            check("the picker still offers exactly one ESP32, and the card entry "
                  "takes the ESP32's firmware",
                  shown.count('<input type="radio" name="fwboard"') == 2
                  and shown.count("<b>ESP32 dev board (Base)</b>") == 1
                  and '<span class="tell pick">With or without an SD card: one '
                      "image</span>" in shown
                  and "Two rows of pins and a USB socket" not in shown
                  and all(len(b.get("pick", "")) <= 39 for b in S.BOARDS)
                  and "SD card, for storage" not in shown
                  and "Freenove" not in shown
                  and [b["dir"] for b in S.BOARDS] == ["esp32", "esp32s3", "esp32-fncam"]
                  and [b["dir"] for b in S.picker_boards()] == ["esp32", "esp32s3"]
                  and all("image" not in b for b in S.BOARDS)
                  and "<dt>Firmware</dt><dd>0.19.2 <a href=\"/install\">on the "
                      "installer</a>. The same image as the bare board: choose ESP32 "
                      "dev board (Base) on the installer.</dd>"
                      in S.board_html(["esp32-sd"])
                  and "Each image is for its own chip." in shown
                  and '<p class="meta early' not in shown)
            # Site 1.0.0: a symbol on each button, a fresh chip with a
            # sparkle and a chip in an arrow going round it. Decoration: the
            # words say it, so a screen reader is not told twice.
            check("each button has its symbol before its words, hidden from a "
                  "screen reader",
                  shown.count('slot="activate">' + S.BTN_ICON_NEW
                              + "Install on a new board</button>") == 2
                  and shown.count('slot="activate">' + S.BTN_ICON_UPDATE
                                  + "Update my board</button>") == 2
                  and all(ic.startswith('<svg class="bi" viewBox="0 0 24 24" '
                                        'aria-hidden="true" focusable="false">')
                          and not re.search(r"<text|\sid=|<script|href", ic)
                          for ic in (S.BTN_ICON_NEW, S.BTN_ICON_UPDATE))
                  and S.BTN_ICON_NEW != S.BTN_ICON_UPDATE)
            check("the words inside the block are the card's amber box",
                  '<div class="pre"><p><b>Before you start:</b> x</p></div>'
                  in S.installer_html(["**Before you start:** x"]))
            check("and the licences of what is being installed are linked",
                  "/install/0.19.2/THIRD_PARTY_NOTICES.md" in shown
                  and S.EWT_BASE + "LICENSE" in S.installer_terms_html()
                  and S.EWT_BASE + "THIRD_PARTY_LICENSES.txt" in S.installer_terms_html())

            # ------------------------------------------------------------------
            # Site 1.2.0: one board a manifest, and a preview for a board no
            # release carries. The firmware's pre-release (vX.Y.Z-dev.N)
            # carries both chips; the ESP32 stays on its release, the S3 is
            # offered the preview, and the preview is never "the newest
            # release" (no gates, no banner, no update arrows).
            print("Boards, one manifest each, and a preview")
            put("0.20.0-dev.3", "esp32", whole + ["version.txt"])
            put("0.20.0-dev.3", "esp32s3", whole,
                {"release.txt": "version 0.20.0-dev.3\ncommit abc1234\n",
                 "THIRD_PARTY_NOTICES.md": "notices\n"})
            with open(os.path.join(fwroot, "0.20.0-dev.3", "esp32", "version.txt"), "w") as fh:
                fh.write("0.20.0-dev.3\n")
            with open(os.path.join(fwroot, "0.20.0-dev.3", "esp32s3", "version.txt"),
                      "w") as fh:
                fh.write("0.20.0-dev.3 (S3 1.0.0)\n")
            os.makedirs(os.path.join(fwroot, "0.20.0-", "esp32"), exist_ok=True)
            os.makedirs(os.path.join(fwroot, "0.20.0-a..b", "esp32"), exist_ok=True)
            check("a preview is not a release, and nothing else changes",
                  [r["version"] for r in S.firmware_releases()] == ["0.19.2", "0.19.1"]
                  and S.newest_release() == "0.19.2")
            check("the ESP32 is offered its releases; the S3, which no release "
                  "carries, the preview",
                  [r["version"] for r in S.board_offers("esp32")] == ["0.19.2", "0.19.1"]
                  and [r["version"] for r in S.board_offers("esp32s3")] == ["0.20.0-dev.3"]
                  and S.board_offers("esp32s3")[0]["pre"] is True)
            m3 = S.firmware_manifest("0.20.0-dev.3", chip="esp32s3")
            check("a board's manifest holds that board's build and nothing else",
                  m3 is not None and [b["chipFamily"] for b in m3["builds"]] == ["ESP32-S3"]
                  and [b["chipFamily"] for b in S.firmware_manifest(
                      "0.19.2", chip="esp32")["builds"]] == ["ESP32"])
            check("at the S3's offsets, bootloader at 0, the parts beside it",
                  [(p["path"], p["offset"]) for p in m3["builds"][0]["parts"]]
                  == [("bootloader.bin", 0), ("partitions.bin", 32768),
                      ("ota_data_initial.bin", 61440), ("firmware.bin", 131072),
                      ("storage.bin", 3932160)])
            check("under the version the board shows, from its version.txt",
                  m3["version"] == "0.20.0-dev.3 (S3 1.0.0)"
                  and S.firmware_manifest("0.19.2", chip="esp32")["version"] == "0.19.2")
            check("the Update manifest for a board is the same plus the key that "
                  "forbids the erase",
                  {k: v for k, v in S.firmware_manifest(
                      "0.20.0-dev.3", update=True, chip="esp32s3").items()
                   if k != "unleashed_update"} == m3)
            got3 = S.firmware_file("0.20.0-dev.3/esp32s3/manifest.json")
            check("served from inside the board's own folder",
                  got3 is not None and json.loads(got3[0].decode()) == m3
                  and S.firmware_file("0.20.0-dev.3/esp32s3/firmware.bin") is not None
                  and json.loads(S.firmware_file("0.19.2/esp32/manifest.json")[0]
                                 .decode())["builds"][0]["parts"][0]["path"]
                      == "bootloader.bin")
            check("the old path is the ESP32's alone, and the preview has none",
                  [b["chipFamily"] for b in json.loads(
                      S.firmware_file("0.19.2/manifest.json")[0].decode())["builds"]]
                  == ["ESP32"]
                  and S.firmware_file("0.20.0-dev.3/manifest.json") is None)
            # The preview's own ESP32 set is not offered while the ESP32 has
            # a release, so it is not reachable by guessing either.
            check("a set that is not offered is not served",
                  S.firmware_file("0.20.0-dev.3/esp32/firmware.bin") is None
                  and S.firmware_file("0.20.0-dev.3/esp32/manifest.json") is None
                  and S.firmware_file("0.19.2/esp32s3/manifest.json") is None
                  and S.firmware_file("0.20.0-dev.3/esp32s3/version.txt") is None
                  and S.firmware_file("0.20.0-dev.3/esp32s3/../esp32/firmware.bin") is None)
            check("a pre-release name that is not one is not a version",
                  S.FIRMWARE_VER.match("0.20.0-") is None
                  and S.FIRMWARE_VER.match("0.20.0-a..b") is None
                  and S.FIRMWARE_VER.match("0.20.0-dev.3") is not None
                  and all(r["version"] not in ("0.20.0-", "0.20.0-a..b")
                          for r in S.firmware_sets()))
            check("the firmware's own release.txt is not taken for a note",
                  S.board_offers("esp32s3")[0]["note"] == ""
                  and S.board_offers("esp32s3")[0]["date"] == "")
            pick = S.installer_html()
            check("the picker says preview, and the line under the buttons the "
                  "exact version",
                  '<span class="bv">Firmware 0.20.0 preview (S3 1.0.0)<span class="sep"' in pick
                  and '<p class="meta ver r0">Version 0.20.0-dev.3 (S3 1.0.0), a preview.'
                      "</p>" in pick
                  and 'manifest="/install/0.20.0-dev.3/esp32s3/manifest.json"' in pick
                  and 'manifest="/install/0.20.0-dev.3/esp32s3/manifest-update.json"'
                      in pick
                  and "Coming soon" not in pick)
            check("and the S3's section says download mode first, before its buttons",
                  pick.find('<div class="bsec b1"><p class="first"><b>First:</b> hold '
                            "<b>BOOT</b>, tap <b>RESET</b>, let go of BOOT.")
                  > 0
                  and pick.find('<div class="bsec b1"><p class="first">')
                      < pick.find('manifest="/install/0.20.0-dev.3/esp32s3/manifest.json"')
                  and '<div class="bsec b0"><p class="first">' not in pick)
            hw = S.board_html(["esp32s3"])
            check("the tested boards page draws the same board, build and buy link",
                  S.BOARD_ART_S3.replace('class="art board"', 'class="art board big"')
                  in hw
                  and "<dt>Firmware</dt><dd>0.20.0 preview (S3 1.0.0)" in hw
                  and "the board calls it 0.20.0-dev.3 (S3 1.0.0)" in hw
                  and ('<a href="https://link.amazon/B0bb1oJqt" rel="sponsored">'
                       'Amazon</a> (affiliate link)') in hw
                  and ('<a href="https://link.amazon/B08MTidlU" rel="sponsored">'
                       'Amazon</a> (affiliate link)') in S.board_html(["esp32"])
                  and "<dt>Firmware</dt><dd>0.19.2 " in S.board_html(["esp32"])
                  and S.board_html(["esp32x9"]) == "" and S.board_html([]) == "")
            # A version.txt that is not a version is not read: the folder's
            # name stands in for it.
            with open(os.path.join(fwroot, "0.20.0-dev.3", "esp32s3", "version.txt"),
                      "w") as fh:
                fh.write("<b>0.20.0</b>\n")
            check("a version.txt that is not a version is not believed",
                  S.firmware_manifest("0.20.0-dev.3", chip="esp32s3")["version"]
                  == "0.20.0-dev.3")
            # A release that carries the S3 takes it over from the preview.
            put("0.19.3", "esp32s3", whole)
            check("once a release carries the S3, the preview is not offered at all",
                  [r["version"] for r in S.board_offers("esp32s3")] == ["0.19.3"]
                  and S.firmware_file("0.20.0-dev.3/esp32s3/manifest.json") is None)
            for gone in ("0.19.3", "0.20.0-dev.3", "0.20.0-", "0.20.0-a..b"):
                shutil.rmtree(os.path.join(fwroot, gone), ignore_errors=True)
            check("and with them gone the card is as it was",
                  S.installer_html() == shown)

            # --------------------------------------------------------------
            # Site 1.2.9: firmware 1.1.0, the release that carries three
            # image sets, the Freenove's among them. Before it, nothing of
            # the Freenove shows; with it on disk, the picker offers it, the
            # S3 is a release rather than a preview, /hardware says tested,
            # the "from 1.1.0" gates open, and a .0 release says it is out
            # early for testing until its .1 arrives.
            print("Firmware 1.1.0: three boards, the gates, the early line")
            fw110 = tempfile.mkdtemp(prefix="dirfw110")

            def put110(version, chip, shown, date="2026-09-26"):
                d = os.path.join(fw110, version, chip)
                os.makedirs(d, exist_ok=True)
                for n in whole:
                    with open(os.path.join(d, n), "w") as fh:
                        fh.write("placeholder, not firmware\n")
                with open(os.path.join(d, "version.txt"), "w") as fh:
                    fh.write(shown + "\n")
                with open(os.path.join(fw110, version, "release.txt"), "w") as fh:
                    fh.write(date + "\n")

            def render(name):
                return S.md_render(open(os.path.join("pages", name + ".md"),
                                        encoding="utf-8").read())

            put110("1.0.3", "esp32", "1.0.3", "2026-09-23")
            # A preview carrying the Freenove, and the S3, before 1.1.0.
            put110("1.1.0-dev.15", "esp32s3", "1.1.0-dev.15 (S3 1.1.0)")
            put110("1.1.0-dev.15", "esp32-fncam", "1.1.0-dev.15 (FNCAM 1.0.2)")
            S.FIRMWARE_DIR = pathlib.Path(fw110)
            try:
                pick0 = S.installer_html()
                hw0, inst0, cam0 = render("hardware"), render("install"), render("camera")
                check("before 1.1.0 the Freenove shows nowhere on the installer, "
                      "even with a preview carrying it",
                      S.board_offers("esp32-fncam") == []
                      and [b["dir"] for b in S.picker_boards()] == ["esp32", "esp32s3"]
                      and "Freenove" not in pick0 and "esp32-fncam" not in pick0
                      and S.firmware_file("1.1.0-dev.15/esp32-fncam/manifest.json") is None
                      and S.firmware_file("1.1.0-dev.15/esp32-fncam/firmware.bin") is None
                      and 'id="on-the-freenove-camera-board"' not in inst0
                      and "Each image is for its own chip." in pick0)
                check("and /hardware still calls it coming soon, the S3 a preview",
                      "coming soon to" in S.board_html(["esp32-fncam"])
                      and "<b>Coming soon.</b> Freenove" in hw0
                      and "<b>ESP32-WROVER: should work, not yet tested.</b>" in hw0
                      and "1.1.0 preview (S3 1.1.0)" in S.board_html(["esp32s3"])
                      and "arrives with firmware 1.1 for the camera boards" in cam0
                      and "is on <a href=\"/install\">the installer</a>" not in cam0
                      and S.early_note() == "" and '<p class="meta early' not in pick0)
                # Site 1.3.1: the lock ribbon turns to SUPPORTED on a release
                # only. With SSH marked as from 1.1.0 and only a 1.1.0
                # preview carrying the S3, it still says coming.
                was_ssh = dict(S.BOARD_SSH)
                try:
                    S.BOARD_SSH["esp32s3"] = (1, 1, 0)
                    check("the Secure seal ignores a preview carrying SSH",
                          S.ssh_state("esp32s3") == "coming"
                          and '<tspan class="ast">*</tspan>' in S.secure_seal_html("esp32s3")
                          and "<dt>Secure</dt>" in S.secure_note_html("esp32s3"))
                finally:
                    S.BOARD_SSH.clear()
                    S.BOARD_SSH.update(was_ssh)

                # 1.1.0 lands, with all three sets.
                put110("1.1.0", "esp32", "1.1.0")
                put110("1.1.0", "esp32s3", "1.1.0 (S3 1.1.0)")
                put110("1.1.0", "esp32-fncam", "1.1.0 (FNCAM 1.0.2)")
                pick1 = S.installer_html()
                hw1, inst1, cam1 = render("hardware"), render("install"), render("camera")
                setup1, sd1, lights1 = render("setup"), render("sdcard"), render("lights")
                upg1, who1, dif1 = render("upgrade"), render("whofor"), render("different")
                early = ("1.1.0 is out early for testing; it has not been through the "
                         "full regression yet. 1.1.1 follows with anything it finds.")
                check("with 1.1.0 on disk the picker offers three boards, the "
                      "Freenove by its picture and a line saying why",
                      [b["dir"] for b in S.picker_boards()] == ["esp32", "esp32s3", "esp32-fncam"]
                      and pick1.count('<input type="radio" name="fwboard"') == 3
                      and '<input type="radio" name="fwboard" id="fwb2">'
                          + S.BOARD_ART_FNCAM in pick1
                      and "<b>Freenove ESP32 camera board</b>" in pick1
                      and '<span class="tell pick">Same chip as the dev board: see '
                          "picture</span>" in pick1
                      and '<span class="bv">Firmware 1.1.0 (FNCAM 1.0.2)</span>' in pick1
                      and 'manifest="/install/1.1.0/esp32-fncam/manifest.json"' in pick1
                      and 'manifest="/install/1.1.0/esp32-fncam/manifest-update.json"' in pick1
                      and '<p class="first"><b>Check the picture:</b> the installer '
                          "cannot tell this board from the dev board." in pick1
                      and ".installer:has(#fwb2:checked) .bsec.b2{display:flex}" in pick1)
                check("and says the dev board and the Freenove share a chip, by name",
                      "Each image is for its own chip." not in pick1
                      and "The ESP32 dev board (Base) and the Freenove ESP32 camera "
                          "board have the same chip, so between those the picture is "
                          "the only check." in pick1)
                check("the S3 is a released board now, not a preview",
                      [r["version"] for r in S.board_offers("esp32s3")] == ["1.1.0"]
                      and '<span class="bv">Firmware 1.1.0 (S3 1.1.0)<span class="sep"' in pick1
                      and "preview" not in pick1
                      and S.firmware_file("1.1.0-dev.15/esp32s3/manifest.json") is None)
                man = S.firmware_manifest("1.1.0", chip="esp32-fncam")
                check("the Freenove's manifest holds its own build, at the ESP32's offsets",
                      man is not None and man["version"] == "1.1.0 (FNCAM 1.0.2)"
                      and [b["chipFamily"] for b in man["builds"]] == ["ESP32"]
                      and [(p["path"], p["offset"]) for p in man["builds"][0]["parts"]]
                          == [("bootloader.bin", 4096), ("partitions.bin", 32768),
                              ("ota_data_initial.bin", 61440), ("firmware.bin", 131072),
                              ("storage.bin", 3932160)]
                      and S.firmware_file("1.1.0/esp32-fncam/firmware.bin") is not None
                      and S.firmware_file("1.1.0/esp32-fncam/../esp32/firmware.bin") is None)
                # Site 1.3.3, Rob: on the picker no seal or badge, only the
                # word Secure with a letter-sized lock, a link to the board's
                # section on /hardware, and no footnote. Once BOARD_SSH names
                # a release on disk carrying the board's set, and not before,
                # the seal loses its asterisk and the footnote goes.
                rows1 = pick1.split('<label class="bopt">')[1:]
                was_ssh = dict(S.BOARD_SSH)
                try:
                    S.BOARD_SSH["esp32s3"] = (1, 1, 0)
                    S.BOARD_SSH["esp32s3-cam"] = (1, 1, 0)
                    shipped = (S.ssh_state("esp32s3"), S.secure_seal_html("esp32s3"),
                               S.secure_pick_html(S.BOARD_BY_DIR["esp32s3"]),
                               S.ssh_state("esp32s3-cam"), S.secure_note_html("esp32s3"),
                               S.board_html(["esp32s3"]),
                               S.secure_note_html("esp32s3-cam"))
                    S.BOARD_SSH["esp32s3"] = (1, 2, 0)
                    later = S.ssh_state("esp32s3")
                finally:
                    S.BOARD_SSH.clear()
                    S.BOARD_SSH.update(was_ssh)
                check("the picker says Secure on the S3's row alone: a word and a "
                      "small lock, linking to the board's section, no seal, no footnote",
                      len(rows1) == 3
                      and ['class="secure"' in r for r in rows1] == [False, True, False]
                      and pick1.count('class="secure"') == 1
                      and '<a class="secure" href="/hardware#waveshare-esp32-s3-lcd-1-47" '
                          'aria-label="Secure: encrypted connections over SSH, coming in '
                          'version 1.2.0, on the board\'s page"><svg class="lockg"' in rows1[1]
                      and '<span class="bv">Firmware 1.1.0 (S3 1.1.0)<span class="sep" '
                          'aria-hidden="true"> · </span><a class="secure"' in rows1[1]
                      and "</svg>Secure</a></span></span></label>" in rows1[1]
                      and "seal" not in pick1 and "lockr" not in pick1
                      and "Encrypted connections" not in pick1 and "SECURE" not in pick1
                      and "article .installer .bopt a.secure {{" in S.PAGE
                      and "article .installer .bopt a.secure svg.lockg {{" in S.PAGE)
                check("and SSH shipping takes the asterisk and the footnote away by "
                      "itself, the S3 camera board staying coming with no set",
                      shipped[0] == "supported"
                      and ">SECURE</text>" in shipped[1] and "ast" not in shipped[1]
                      and 'aria-label="Secure: this board takes encrypted' in shipped[1]
                      and "</svg>Secure</a>" in shipped[2] and "coming" not in shipped[2]
                      and shipped[3] == "coming" and shipped[4] == ""
                      and "<dt>Secure</dt>" not in shipped[5]
                      and ">SECURE</text>" in shipped[5]
                      and "<dt>Secure</dt>" in shipped[6] and later == "coming"
                      and S.BOARD_SSH == {"esp32s3": (1, 2, 0), "esp32s3-cam": (1, 2, 0)}
                      and S.secure_seal_html("esp32") == ""
                      and S.secure_seal_html("esp32-fncam") == ""
                      and S.secure_seal_html("esp32-sd") == ""
                      and S.secure_note_html("esp32") == ""
                      and S.secure_pick_html(S.BOARD_BY_DIR["esp32"]) == "")
                check("each board's version line says 1.1.0 is out early, and no other",
                      pick1.count('<p class="meta early r0">' + early + "</p>") == 3
                      and '<p class="meta early r1">' not in pick1
                      and '<p class="early">' + early + "</p>" in upg1)
                fnsec = hw1.split('id="freenove-esp32-camera-board"')[1].split("<h2")[0]
                check("/hardware calls the Freenove tested, with its firmware and "
                      "installer link, and keeps the GC0308",
                      "<dt>Firmware</dt><dd>1.1.0 (FNCAM 1.0.2) <a href=\"/install\">on "
                      "the installer</a></dd>" in fnsec
                      and "coming soon" not in fnsec.lower()
                      and "GC0308" in fnsec
                      and 'href="/install#on-the-freenove-camera-board"' in fnsec
                      and "<b>ESP32-WROVER: yes, on one board.</b>" in hw1
                      and "should work, not yet tested" not in hw1
                      and "coming soon to" in S.board_html(["esp32s3-cam"]))
                check("/install has the Freenove's own steps and the closed board",
                      '<h2 id="on-the-freenove-camera-board">On the Freenove camera '
                      "board</h2>" in inst1
                      and "A new board starts closed." in inst1
                      and "<b>Temporarily stop taking calls</b>" in inst1
                      and "the Freenove camera board has neither" in inst1
                      and "A new board starts closed." not in inst0
                      and "Until you open it, the board is closed to everybody else"
                          in setup1)
                check("the 1.1.0 gates read as released: /camera, /lights, "
                      "backups, the camera row",
                      "arrives with firmware 1.1 for the camera boards" not in cam1
                      and "The Freenove camera board is on" in cam1
                      and "arrive with firmware 1.1.0" not in lights1
                      and "The card can also keep the board" in sd1
                      and "Firmware 1.1.0 gives the card one more job" not in sd1
                      and "on the Freenove camera board" in dif1.split('class="cmp"')[1]
                      and "coming, on the camera boards" not in dif1
                      and "The Freenove camera board</a> lets a" in who1
                      and "SCREENS INSTALL" not in sd1)

                # The .1 lands, for the ESP32 alone: the early line goes
                # everywhere, and the other boards stay on 1.1.0.
                put110("1.1.1", "esp32", "1.1.1", "2026-09-30")
                pick2 = S.installer_html()
                check("and the early line goes once 1.1.1 is on disk, "
                      "and SCREENS INSTALL appears",
                      S.early_note() == "" and "early for testing" not in pick2
                      and '<p class="early">' not in render("upgrade")
                      and [r["version"] for r in S.board_offers("esp32-fncam")] == ["1.1.0"]
                      and "<code>SCREENS INSTALL</code>" in render("sdcard"))
            finally:
                S.FIRMWARE_DIR = pathlib.Path(fwroot)
                shutil.rmtree(fw110, ignore_errors=True)

            # The same, end to end, over HTTP: a second server pointed at
            # the scratch releases, so the route, the content types and the
            # page's script tag are tested as a browser meets them.
            print("The installer page, with a release published")
            port2 = PORT + 1
            base2 = f"http://127.0.0.1:{port2}"
            db2 = os.path.join(tempfile.gettempdir(), f"dirtest{os.getpid()}b.db")
            env2 = dict(os.environ, DIRECTORY_PAGE_CACHE="0", DIRECTORY_DB=db2,
                        DIRECTORY_PORT=str(port2), DIRECTORY_FIRMWARE_DIR=fwroot,
                        # Two boards are listed here to see the update arrow
                        # follow the releases on disk (site 1.0.0).
                        DIRECTORY_PENDING_HOURS="0.0006", DIRECTORY_MIN_SECONDS="0")
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
                # Two boards for the update arrow, announced now so their
                # pending window has passed by the time 1.0.1 is on disk.
                behind = {"software": "unleashed", "version": "1.0.0",
                          "name": "Behind Board", "port": 6400, "token": "",
                          "system": "ESP32-WROOM-32E", "features": ["chat"]}
                other = {"software": "Mystic", "version": "0.0.1",
                         "name": "Other Board", "port": 23, "token": ""}
                t_listed = time.time()
                _c, tb = post_from(behind, "192.0.2.61", base2)
                _c, to = post_from(other, "192.0.2.62", base2)
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
                # The Update button's manifest, over HTTP, as the dialog
                # fetches it: the key that forbids the erase, the prompt
                # kept for any dialog that ignores it, and the same parts.
                code, ctype, body = fetch("/install/0.19.2/manifest-update.json", base2)
                u2 = json.loads(body.decode()) if code == 200 else {}
                check("the Update manifest is served beside it and cannot erase",
                      code == 200 and ctype.startswith("application/json")
                      and u2.get("unleashed_update") is True
                      and u2.get("new_install_prompt_erase") is True
                      and u2.get("builds") == m2.get("builds")
                      and fetch("/install/0.18.0/manifest-update.json", base2)[0] == 404)
                check("and the page offers both buttons, the update one hidden "
                      "where it cannot work",
                      ">Install on a new board</button>" in page2
                      and ">Update my board</button>" in page2
                      and "article .installer esp-web-install-button.upd"
                          "[install-unsupported] { display:none; }" in page2)
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
                check("and nothing takes its place: the pitch follows the menu",
                      '</nav><div class="front"><section class="hero">' in home2
                      and '</nav><div class="front">' in get("/")[1])
                check("and the page has no full size button without it either",
                      'class="btn"' not in home2.split("</nav>")[1]
                      and 'class="b1"' in home2)
                put("1.0.0", "esp32", whole)
                home2 = fetch("/", base2)[2].decode("utf-8")
                bn = (home2.split('<div class="banner"')[1].split("</div>")[0]
                      if '<div class="banner"' in home2 else "")
                check("the banner shows once a 1.0.0 release is on disk",
                      '<div class="banner" role="note"><p>\u00b5nleashed BBS 1.0.0 is out. '
                      '<a href="/install">Install it from your browser.</a></p></div>'
                      in home2)
                dir2 = fetch("/directory", base2)[2].decode("utf-8")
                check("above the pitch and the directory heading, straight under the menu",
                      '</nav><div class="banner"' in home2
                      and home2.index('<div class="banner"')
                          < home2.index('<div class="front">')
                      and '</nav><div class="banner"' in dir2
                      and dir2.index('<div class="banner"')
                          < dir2.index("<h1>Communities online</h1>"))
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
                      and 'manifest="/install/1.0.0/esp32/manifest.json"' in inst4
                      and 'id="fwv0_0" checked> 1.0.0 (newest)' in inst4)
                # 1.0.0 has no BOOT button reset, and neither has 1.0.1,
                # which is the badge fields only: it is 1.0.2's.
                check("with 1.0.0 on disk, the BOOT button section still waits",
                      "The BOOT button" not in inst4 and S.ART["boot-button"] not in inst4
                      and "::: from" not in inst4)
                put("1.0.1", "esp32", whole)
                inst41 = fetch("/install", base2)[2].decode("utf-8")
                check("and with 1.0.1, the badge release, it still waits",
                      'id="fwv0_0" checked> 1.0.1 (newest)' in inst41
                      and "The BOOT button" not in inst41
                      and S.ART["boot-button"] not in inst41
                      and "goes back to the last network that worked" not in inst41
                      and "::: from" not in inst41)

                # ----------------------------------------------------------
                # Site 1.0.0 (Rob: "a version number should apply to all
                # honestly. Then when an unleashed board is behind, mark on
                # there a subtle up arrow"). In-process first, where
                # FIRMWARE_DIR is these scratch releases, newest 1.0.1.
                print("Versions, and the update arrow")
                vk = S.version_key
                check("versions compare part by part: 1.0.10 is newer than 1.0.9",
                      vk("1.0.10") > vk("1.0.9") and vk("1.0.1") == vk("1.0.1")
                      and vk("0.23.0") < vk("1.0.0") < vk("1.0.1") < vk("1.1.0")
                      and vk("v1.0.1") == vk("1.0.1") and vk(" 1.0.1 ") == vk("1.0.1"))
                check("a pre-release is older than its release, and newer than the one "
                      "before; build metadata does not count",
                      vk("1.0.1-rc.2") < vk("1.0.1") and vk("1.0.1-rc.2") > vk("1.0.0")
                      and vk("1.0.1+build.7") == vk("1.0.1"))
                check("anything that is not three numbers is not a version",
                      all(vk(g) is None for g in ("", None, "1.0", "1", "dev", "1.0.0.1",
                                                   "1.0.x", "one.two.three", "1..0",
                                                   "<b>1.0.0</b>", "1.0.0 beta",
                                                   "1.0.0-", "-1.0.0")))
                latest = S.newest_release()

                # A stored row, listed ten days: past new, short of a month,
                # so the directory adds no badge of its own to it.
                def brow(**kw):
                    r = {"software": "unleashed", "version": "1.0.0", "system": "",
                         "terminals": "", "guests": None, "features": "", "support": "",
                         "interests": "", "public_at": int(time.time()) - 10 * 86400,
                         "first_seen": int(time.time()) - 10 * 86400}
                    r.update(kw)
                    return r

                check("the newest release is the one /install offers first",
                      latest == "1.0.1" and latest == S.firmware_releases()[0]["version"])
                check("a board on an older version is behind; one that is equal, newer "
                      "or unparseable is not",
                      S.update_for(brow(version="1.0.0"), latest) == "1.0.1"
                      and S.update_for(brow(version="0.23.0"), latest) == "1.0.1"
                      and S.update_for(brow(version="1.0.1-rc.1"), latest) == "1.0.1"
                      and S.update_for(brow(version="1.0.1"), latest) == ""
                      and S.update_for(brow(version="1.0.2"), latest) == ""
                      and S.update_for(brow(version="1.0.10"), latest) == ""
                      and S.update_for(brow(version="garbage"), latest) == ""
                      and S.update_for(brow(version=""), latest) == "")
                check("other software is never flagged, whatever its version",
                      S.update_for(brow(software="Mystic", version="0.0.1"), latest) == ""
                      and S.update_for(brow(software="unleashed-fork", version="0.0.1"),
                                       latest) == ""
                      and S.update_for(brow(software="", version="0.0.1"), latest) == "")
                check("and nothing is flagged with no release on disk",
                      S.update_for(brow(), "") == "" and "update" not in S.row_keys(
                          brow(), int(time.time()), False, ""))
                bb1 = S.board_badges(brow(system="ESP32"), int(time.time()), False, latest)
                check("a board that is behind has the arrow on its software badge, "
                      "linked to /upgrade, before the machine",
                      '<span class="bid"><span class="bd k-soft" role="img"' in bb1
                      and '>unleashed 1.0.0</span><a class="bu" href="/upgrade" ' in bb1
                      and bb1.index('class="bu"') < bb1.index('class="bd k-sys"')
                      and 'data-tip="Update available: 1.0.0 → 1.0.1. Plug it in and '
                          'use Update my board on /install."' in bb1
                      and 'aria-label="Update available: 1.0.0 → 1.0.1.' in bb1
                      and "update" in S.row_keys(brow(), int(time.time()), False, latest))
                check("and none for a board on the newest, or for other software",
                      'class="bu"' not in S.board_badges(brow(version="1.0.1"),
                                                         int(time.time()), False, latest)
                      and 'class="bu"' not in S.board_badges(
                          brow(software="Mystic", version="0.0.1"), int(time.time()),
                          False, latest))
                ul = S.update_link('1.0.0"><script>x</script>', "1.0.1")
                check("the arrow's tooltip is escaped, once, in both attributes",
                      "<script>" not in ul and '"><' not in ul.split(">", 1)[0]
                      and ul.count("1.0.0&quot;&gt;&lt;script&gt;x&lt;/script&gt;") == 2)
                check("without a system badge the software badge is alone on its row; "
                      "with nothing else there is no second row",
                      S.board_badges(brow(version="1.0.1"), int(time.time()), False, latest)
                      == '<span class="badges"><span class="bid">'
                         + S.badge("soft", "unleashed 1.0.1",
                                   "Software: unleashed 1.0.1, as the board reports it.")
                         + "</span></span>"
                      and S.board_badges(brow(software="", version=""), int(time.time()),
                                         False, latest) == "")
                check("the arrow is drawn in a dim cyan, a link and not an image",
                      ".bu { --bc:#5ab4b4;" in inst41
                      and ".k-upd { --bc:#5ab4b4;" in inst41
                      and 'role="img"' not in ul and "tabindex" not in ul)

                # Over HTTP: the two boards announced when this server
                # started, now past their pending window.
                time.sleep(max(0.0, 2.5 - (time.time() - t_listed)))
                post_from(dict(behind, token=tb.get("token", "")), "192.0.2.61", base2)
                post_from(dict(other, token=to.get("token", "")), "192.0.2.62", base2)
                home3 = fetch("/directory", base2)[2].decode("utf-8")
                brow3, orow3 = badge_row(home3, "Behind Board"), badge_row(home3, "Other Board")
                check("on the list, the board behind carries the arrow and the other "
                      "software does not",
                      '>unleashed 1.0.0</span><a class="bu" href="/upgrade" ' in brow3
                      and "1.0.0 → 1.0.1." in brow3
                      and ">Mystic 0.0.1</span>" in orow3 and 'class="bu"' not in orow3)
                upd_rows = list_rows(fetch("/?b=update", base2)[2].decode("utf-8"))
                check("and the filter finds the boards that are behind",
                      [n for n, _k, h in upd_rows if not h] == ["Behind Board"]
                      and all(("update" in k) != h for _n, k, h in upd_rows))
                j3 = {b["name"]: b for b in json.loads(
                    fetch("/api/boards.json", base2)[2].decode("utf-8"))["boards"]}
                check("and the JSON has each board's software and version",
                      j3.get("Behind Board", {}).get("version") == "1.0.0"
                      and j3.get("Other Board", {}).get("software") == "Mystic"
                      and j3.get("Other Board", {}).get("version") == "0.0.1")
                # 1.0.2 is the restore security fix: still no BOOT reset.
                put("1.0.2", "esp32", whole)
                inst42 = fetch("/install", base2)[2].decode("utf-8")
                check("and with 1.0.2, the security fix, it still waits",
                      'id="fwv0_0" checked> 1.0.2 (newest)' in inst42
                      and "The BOOT button" not in inst42
                      and S.ART["boot-button"] not in inst42
                      and "goes back to the last network that worked" not in inst42)
                check("and the update arrow follows the newest release on disk",
                      "1.0.0 → 1.0.2." in badge_row(fetch("/directory", base2)[2].decode("utf-8"),
                                                         "Behind Board"))
                put("1.1.0", "esp32", whole)
                inst5 = fetch("/install", base2)[2].decode("utf-8")
                flat5 = " ".join(inst5.split())
                check("with a release of 1.1.0 or later, the BOOT button shows",
                      "The BOOT button" in inst5 and S.ART["boot-button"] in inst5
                      and "Press and let go of <b>RESET</b>" in flat5
                      and "goes back to the last network that worked" in flat5
                      and "::: from" not in inst5)
                # The words from the firmware's copy for 1.1.0, section 6: the
                # listing goes with a factory reset, and the box saying so is
                # read before step 1.
                boot = flat5[flat5.index("The BOOT button"):]
                check("with the warning that a factory reset takes the board off the "
                      "directory, above step 1, and the two bullets that say so",
                      "A factory reset also takes the board off this directory." in boot
                      and boot.index("takes the board off this directory")
                      < boot.index("Press and let go of <b>RESET</b>")
                      and '<p class="warn">A factory reset' in boot.split("Press and let go")[0]
                      and "Until you choose a new password, the board keeps itself off "
                          "the directory." in boot
                      and "the accounts, the settings, the Wi-Fi, the mail and the logs "
                          "are wiped" in boot
                      and "is no longer on the directory unless you restore a backup."
                          in boot)
                check("and the arrow now says 1.1.0",
                      "1.0.0 → 1.1.0." in badge_row(fetch("/directory", base2)[2].decode("utf-8"),
                                                         "Behind Board"))
                fwd5 = " ".join(fetch("/forward", base2)[2].decode("utf-8").split())
                set5 = fetch("/setup", base2)[2].decode("utf-8")
                flat_set5 = " ".join(set5.split())
                check("with 1.1.0 on disk, /forward gives each board its own Port and "
                      "explains Outside, and the account for older firmware is gone",
                      "From firmware 1.1.0 that is a setting" in fwd5
                      and "<b>Port</b> (<code>port</code>)" in fwd5
                      and "<b>Outside</b>: The port callers dial from the internet" in fwd5
                      and "Every board listens on 6400" not in fwd5
                      and "::: until" not in fwd5 and "::: from" not in fwd5)
                check("and /setup has the network page with its Port, and Outside on "
                      "the announce page, each list whole",
                      has_h(set5, 2, "network") and not has_h(set5, 2, "wifi")
                      and "<b>Port</b> (<code>port</code>)" in flat_set5
                      and "<b>Outside</b>: The port callers dial" in flat_set5
                      and "if you forwarded a different one to the" not in flat_set5
                      and flat_set5.count("<b>Token</b>") == 1
                      and "::: until" not in set5 and "::: from" not in set5)
                # The gate on its own: from and until are two halves.
                g = S.md_render("::: until 1.1.0\nold\n:::\n\n::: from 1.1.0\nnew\n:::")
                g2 = S.md_render("::: until 9.0.0\nold\n:::\n\n::: from 9.0.0\nnew\n:::")
                check("::: from and ::: until swap on the release, never both, never "
                      "neither", g == "<p>new</p>" and g2 == "<p>old</p>")
                g3 = S.md_render("- a\n::: from 1.0.0\n- b\n:::\n1. c\n::: until 9.0.0\n"
                                 "| x |\n|---|\n| y |\n:::")
                check("and a gate straight after a list stays after it",
                      g3 == "<ul><li>a</li></ul><ul><li>b</li></ul><ol><li>c</li></ol>"
                            '<div class="tablewrap"><table><tr><th>x</th></tr>'
                            "<tr><td>y</td></tr></table></div>")
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
              and len(re.findall(r"\n +fetch_release\n", upd)) == 3)
        # Site 1.2.1: the 1.2.0 deploy stuck on the droplet. The pull moved
        # HEAD, setup.sh failed, and every later run found nothing to pull
        # and never installed. setup.sh now records the commit it installed,
        # last, and update.sh installs whenever that record is not HEAD.
        # The behaviour is exercised in a sandbox by hand (git, stubs for
        # id, systemctl and curl); these pin the shape of it.
        setup_sh2 = open(os.path.join("deploy", "setup.sh"), encoding="utf-8").read()
        check("setup.sh records the commit it installed, after everything else",
              '> "$DEST/.installed.new"' in setup_sh2
              and 'mv "$DEST/.installed.new" "$DEST/.installed"' in setup_sh2
              and setup_sh2.index(".installed.new") > setup_sh2.index('say "Firewall"')
              and setup_sh2.index(".installed.new") > setup_sh2.index("systemctl restart"))
        check("update.sh installs when the last install did not finish",
              'INSTALLED="$(cat "$INSTALLED_FILE" 2>/dev/null || true)"' in upd
              and 'if [ "$INSTALLED" = "$OLD" ]; then' in upd
              and "the last install did not finish" in upd
              and upd.index("the last install did not finish") < upd.index('loud "Installing..."')
              and "/srv/unleashed_directory/.installed" in upd)
        check("and the record is never committed",
              "/.installed" in open(".gitignore", encoding="utf-8").read())
        import hashlib
        import http.server
        relroot = tempfile.mkdtemp(prefix="dirrel")
        dest = tempfile.mkdtemp(prefix="dirdest")
        rel_state = {"tag": "v1.0.0", "missing": None, "tamper": None, "status": 200,
                     "secret": False}
        rel_list = []

        def list_release(tag, fams=("esp32",), pre=False, draft=False, tamper=None,
                         missing=None, versions=None):
            """One release of the list: every set in fams (the ESP32's plain,
            the rest prefixed), version.txt files from versions, notices and
            SHA256SUMS over all of it."""
            d = os.path.join(relroot, "list", tag)
            shutil.rmtree(d, ignore_errors=True)
            os.makedirs(d)
            files = {}
            for fam in fams:
                pre_ = "" if fam == "esp32" else fam + "-"
                for n in ("bootloader.bin", "partitions.bin", "ota_data_initial.bin",
                          "firmware.bin", "storage.bin"):
                    files[pre_ + n] = (fam + n + tag).encode() * 32
            for fam, text in (versions or {}).items():
                files[("" if fam == "esp32" else fam + "-") + "version.txt"] = text.encode()
            files["THIRD_PARTY_NOTICES.md"] = b"notices\n"
            files["SHA256SUMS"] = "".join(
                f"{hashlib.sha256(b).hexdigest()}  {n}\n" for n, b in files.items()).encode()
            if tamper:
                files[tamper] += b"x"
            for n, b in files.items():
                if n != missing:
                    with open(os.path.join(d, n), "wb") as fh:
                        fh.write(b)
            rel_list.append({"tag": tag, "pre": pre, "draft": draft})

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
                if self.path == "/releases":
                    body = json.dumps([
                        {"tag_name": r["tag"], "prerelease": r.get("pre", False),
                         "draft": r.get("draft", False),
                         "published_at": "2026-10-02T12:00:00Z",
                         "assets": [{"name": n, "browser_download_url":
                                     f"http://127.0.0.1:{port}/dl2/{r['tag']}/{n}"}
                                    for n in sorted(os.listdir(
                                        os.path.join(relroot, "list", r["tag"])))]}
                        for r in rel_list]).encode()
                elif self.path.startswith("/dl2/"):
                    tag, _s, name = self.path[5:].partition("/")
                    f = os.path.join(relroot, "list", tag, name)
                    if not os.path.isfile(f):
                        self.send_response(404)
                        self.end_headers()
                        return
                    body = open(f, "rb").read()
                elif self.path == "/releases/latest":
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

            # --------------------------------------------------------------
            # Site 1.2.0: the list of releases, a board to each image set,
            # and a pre-release serving the board no release carries.
            relenv["UNLEASHED_RELEASE_API"] = (
                f"http://127.0.0.1:{relsrv.server_address[1]}/releases")
            shutil.rmtree(dest, ignore_errors=True)
            os.makedirs(dest)
            list_release("v1.3.0-dev.1", ("esp32", "esp32s3"), pre=True)
            list_release("v1.3.0-dev.2", ("esp32", "esp32s3"), pre=True,
                         versions={"esp32": "1.3.0-dev.2\n",
                                   "esp32s3": "1.3.0-dev.2 (S3 1.0.0)\n"})
            list_release("v1.4.0", ("esp32", "esp32s3"), draft=True)
            list_release("v1.2.9", ("esp32", "esp32s3"), pre=True)   # tagged like a release
            list_release("v1.2.0")
            # GitHub lists newest first.
            rel_list.reverse()
            rc, out = run_fetch()
            t12 = tree("1.2.0")
            tp = tree("1.3.0-dev.2")
            check("the latest release is installed, and the S3 from the newest pre-release",
                  rc == 0 and "Installed firmware 1.2.0 for the browser installer." in out
                  and "Installed firmware 1.3.0-dev.2 (a preview, for the esp32s3 image) "
                      "for the browser installer." in out
                  and t12 is not None and "esp32s3/firmware.bin" not in t12
                  and tp is not None
                  and all("esp32s3/" + n in tp for n in ("bootloader.bin", "partitions.bin",
                                                          "ota_data_initial.bin",
                                                          "firmware.bin", "storage.bin"))
                  and tp.get("esp32s3/version.txt") == b"1.3.0-dev.2 (S3 1.0.0)\n"
                  and tp.get("esp32/version.txt") == b"1.3.0-dev.2\n")
            check("never a draft, an older preview, or a pre-release tagged like a release",
                  sorted(os.listdir(dest)) == ["1.2.0", "1.3.0-dev.2"])
            was_fw = S.FIRMWARE_DIR
            S.FIRMWARE_DIR = pathlib.Path(dest)
            try:
                offers = ([r["version"] for r in S.board_offers("esp32")],
                          [r["version"] for r in S.board_offers("esp32s3")])
                m3 = S.firmware_manifest("1.3.0-dev.2", chip="esp32s3")
                newest = S.newest_release()
            finally:
                S.FIRMWARE_DIR = was_fw
            check("and the site serves the ESP32 its release and the S3 the preview",
                  offers == (["1.2.0"], ["1.3.0-dev.2"]) and newest == "1.2.0"
                  and m3["version"] == "1.3.0-dev.2 (S3 1.0.0)"
                  and [b["chipFamily"] for b in m3["builds"]] == ["ESP32-S3"])
            rc, out = run_fetch()
            check("a second run changes nothing",
                  rc == 0 and "Firmware 1.2.0 is already installed." in out
                  and "Firmware 1.3.0-dev.2 is already installed." in out
                  and tree("1.3.0-dev.2") == tp)
            # A preview copied in by hand, which GitHub does not list, stays
            # until a release or a newer preview here carries its board: the
            # daily run must not delete the only copy.
            shutil.copytree(os.path.join(dest, "1.3.0-dev.2"), os.path.join(dest, "1.3.0-dev.9"))
            rc, out = run_fetch()
            check("a preview copied in by hand is kept while it serves its board",
                  rc == 0 and "Removed" not in out
                  and sorted(os.listdir(dest)) == ["1.2.0", "1.3.0-dev.2", "1.3.0-dev.9"])
            shutil.rmtree(os.path.join(dest, "1.3.0-dev.9"))
            # A newer pre-release that is broken leaves the one before serving.
            list_release("v1.3.0-dev.3", ("esp32", "esp32s3"), pre=True,
                         tamper="esp32s3-firmware.bin")
            rel_list.insert(0, rel_list.pop())
            rc, out = run_fetch()
            check("a broken preview installs nothing and the one before stays",
                  rc == 1 and "esp32s3-firmware.bin does not match SHA256SUMS" in out
                  and tree("1.3.0-dev.3") is None and tree("1.3.0-dev.2") == tp
                  and tree("1.2.0") == t12)
            rel_list.pop(0)
            # A half-published S3 set is refused, not half installed.
            list_release("v1.2.1", ("esp32", "esp32s3"), missing="esp32s3-storage.bin")
            rel_list.insert(0, rel_list.pop())
            rc, out = run_fetch()
            check("a release missing part of a set is refused, naming the part",
                  rc == 1 and "missing esp32s3-storage.bin" in out and tree("1.2.1") is None
                  and tree("1.2.0") == t12 and tree("1.3.0-dev.2") == tp)
            rel_list.pop(0)
            # A version.txt the sums name and the release does not carry is a
            # set half published, like a missing part.
            list_release("v1.2.4", ("esp32", "esp32s3"), missing="esp32s3-version.txt",
                         versions={"esp32s3": "1.2.4 (S3 1.0.0)\n"})
            rel_list.insert(0, rel_list.pop())
            rc, out = run_fetch()
            check("and one whose sums name a version.txt it does not carry",
                  rc == 1 and "missing esp32s3-version.txt" in out and tree("1.2.4") is None
                  and tree("1.3.0-dev.2") == tp)
            rel_list.pop(0)
            # A version.txt that does not name a version is refused too.
            list_release("v1.2.2", ("esp32",), versions={"esp32": "<b>hi</b>\n"})
            rel_list.insert(0, rel_list.pop())
            rc, out = run_fetch()
            check("and one whose version.txt is not a version",
                  rc == 1 and "version.txt is not one line naming a version" in out
                  and tree("1.2.2") is None)
            rel_list.pop(0)
            # A release that carries the S3 takes it over, and the preview goes.
            list_release("v1.3.0", ("esp32", "esp32s3"),
                         versions={"esp32s3": "1.3.0 (S3 1.0.0)\n"})
            rel_list.insert(0, rel_list.pop())
            rc, out = run_fetch()
            check("once a release carries the S3, the preview is removed",
                  rc == 0 and "Installed firmware 1.3.0 for the browser installer." in out
                  and sorted(os.listdir(dest)) == ["1.2.0", "1.3.0"]
                  and "Removed older releases: 1.3.0-dev.2." in out
                  and (tree("1.3.0") or {}).get("esp32s3/version.txt") == b"1.3.0 (S3 1.0.0)\n")
            # Two ESP32-only patches after it: the S3 stays on the release
            # that carries it, however old, and is never handed back to a
            # pre-release, and that release is kept past the newest two.
            t130 = tree("1.3.0")
            list_release("v1.3.1")
            rel_list.insert(0, rel_list.pop())
            rc1, out1 = run_fetch()
            list_release("v1.3.2")
            rel_list.insert(0, rel_list.pop())
            rc, out = run_fetch()
            was_fw = S.FIRMWARE_DIR
            S.FIRMWARE_DIR = pathlib.Path(dest)
            try:
                offers = ([r["version"] for r in S.board_offers("esp32")],
                          [r["version"] for r in S.board_offers("esp32s3")])
            finally:
                S.FIRMWARE_DIR = was_fw
            check("a board the newest release lacks stays on the older release that "
                  "carries it, kept past the newest two",
                  rc1 == 0 and rc == 0 and "Removed older releases: 1.2.0." in out1
                  and sorted(os.listdir(dest)) == ["1.3.0", "1.3.1", "1.3.2"]
                  and tree("1.3.0") == t130 and "preview" not in out1 + out
                  and "Removed" not in out
                  and offers == (["1.3.2", "1.3.1"], ["1.3.0"]))
            # Newest by version, not by the order GitHub lists them: a patch
            # to an older line, published last, is not the newest release.
            list_release("v1.2.3")
            rel_list.insert(0, rel_list.pop())
            rc, out = run_fetch()
            check("the newest release is the highest version, not the last published",
                  rc == 0 and "Installed firmware" not in out
                  and sorted(os.listdir(dest)) == ["1.3.0", "1.3.1", "1.3.2"])
            # Site 1.2.9: the Freenove's set, esp32-fncam, from firmware
            # 1.1.0. It waits for a release: a pre-release carrying it is
            # never installed for it, so nothing of it shows early.
            list_release("v1.4.0-dev.1", ("esp32", "esp32s3", "esp32-fncam"), pre=True,
                         versions={"esp32-fncam": "1.4.0-dev.1 (FNCAM 1.0.2)\n"})
            rel_list.insert(0, rel_list.pop())
            rc, out = run_fetch()
            fetch_src = open(os.path.join("deploy", "fetch_release.py"), encoding="utf-8").read()
            check("a pre-release is never taken for the Freenove's set",
                  rc == 0 and 'FAMILIES = ("esp32", "esp32s3", "esp32-fncam")' in fetch_src
                  and 'NO_PREVIEW = ("esp32-fncam",)' in fetch_src
                  and tree("1.4.0-dev.1") is None
                  and sorted(os.listdir(dest)) == ["1.3.0", "1.3.1", "1.3.2"])
            list_release("v1.4.0", ("esp32", "esp32s3", "esp32-fncam"),
                         versions={"esp32": "1.4.0\n", "esp32s3": "1.4.0 (S3 1.1.0)\n",
                                   "esp32-fncam": "1.4.0 (FNCAM 1.0.2)\n"})
            rel_list.insert(0, rel_list.pop())
            rc, out = run_fetch()
            t140 = tree("1.4.0") or {}
            was_fw = S.FIRMWARE_DIR
            S.FIRMWARE_DIR = pathlib.Path(dest)
            try:
                fn_offers = [r["version"] for r in S.board_offers("esp32-fncam")]
                fn_man = S.firmware_manifest("1.4.0", chip="esp32-fncam")
                fn_part = S.firmware_file("1.4.0/esp32-fncam/firmware.bin")
            finally:
                S.FIRMWARE_DIR = was_fw
            check("a release carrying all three installs the Freenove's set, "
                  "from its prefixed assets",
                  rc == 0 and "Installed firmware 1.4.0 for the browser installer." in out
                  and all("esp32-fncam/" + n in t140 for n in (
                      "bootloader.bin", "partitions.bin", "ota_data_initial.bin",
                      "firmware.bin", "storage.bin"))
                  and t140.get("esp32-fncam/version.txt") == b"1.4.0 (FNCAM 1.0.2)\n"
                  and t140.get("esp32-fncam/firmware.bin", b"").startswith(b"esp32-fncamfirmware.bin")
                  and fn_offers == ["1.4.0"]
                  and fn_man is not None and fn_man["version"] == "1.4.0 (FNCAM 1.0.2)"
                  and [b["chipFamily"] for b in fn_man["builds"]] == ["ESP32"]
                  and fn_man["builds"][0]["parts"][0] == {"path": "bootloader.bin",
                                                          "offset": 4096}
                  and fn_part is not None)
        finally:
            relsrv.shutdown()
            shutil.rmtree(relroot, ignore_errors=True)
            shutil.rmtree(dest, ignore_errors=True)
        check("fetched releases are kept out of git",
              "/firmware/[0-9]*/" in open(".gitignore", encoding="utf-8").read())

        # The code a visitor runs is the code in this repository, at an
        # exact version, and cannot change between one reader and the next.
        # The path carries this site's revision of the bundle as well
        # (0.22.1), so a changed file is fetched fresh rather than a day late.
        check("ESP Web Tools is pinned to an exact version, served from here",
              re.match(r"^\d+\.\d+\.\d+$", S.EWT_VERSION) is not None
              and isinstance(S.EWT_REV, int)
              and S.EWT_SCRIPT == "/install/esp-web-tools/" + S.EWT_VERSION
                                  + "-" + str(S.EWT_REV) + "/install-button.js"
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
        directory_checks(S)
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
