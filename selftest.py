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
              same address queueing, the rate limit (per board, with a
              ceiling per address), and going quiet. Then the directory's
              pages, the guides it serves at /docs from a checkout of
              unleashed_documentation (SELFTEST_DOCS, or docs/ or
              ../unleashed_documentation beside this file), and the 301s
              that send an old address to where its page lives now.

Usage:        python3 selftest.py

Copyright 2026 - Robert Mech
License:      GNU General Public License v3 or later
SPDX-License-Identifier: GPL-3.0-or-later
===========================================================================
"""

import html
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from html.parser import HTMLParser


# Tests stay on 127.0.0.1. Since the split a page that moved answers with a
# 301 to a real address on the internet (the project's site, the
# directory), and urllib follows a redirect by default: this one follows it
# only to loopback, so a move to anywhere else comes back as the 301 itself.
class _LoopbackOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlsplit(newurl).hostname not in ("127.0.0.1", "localhost"):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


urllib.request.install_opener(urllib.request.build_opener(_LoopbackOnly))

# The suite's first port. It uses this and the four after it, all on
# 127.0.0.1, one directory each. SELFTEST_PORT moves the lot, for a machine
# where something else already has 8123 (site 1.1.0).
PORT = int(os.environ.get("SELFTEST_PORT", "8123"))
BASE = f"http://127.0.0.1:{PORT}"
# The guides the directory serves at /docs: a checkout of
# unleashed_documentation. Without one, the checks of the guides are
# skipped and say so; everything the directory itself does is still tested.
HERE_DIR = os.path.dirname(os.path.abspath(__file__))
DOCS_DIR = os.path.abspath(os.environ.get("SELFTEST_DOCS") or next(
    (p for p in (os.path.join(HERE_DIR, "docs"),
                 os.path.join(HERE_DIR, "..", "unleashed_documentation"))
     if os.path.isdir(os.path.join(p, "pages"))),
    os.path.join(HERE_DIR, "docs")))
HAVE_DOCS = os.path.isdir(os.path.join(DOCS_DIR, "pages"))
passed = failed = 0


def has_h(page, level, text):
    """A heading with this text, carrying the id md_render gives it."""
    return re.search(rf'<h{level} id="[a-z0-9-]+">{re.escape(text)}</h{level}>',
                     page) is not None


# Site 1.3.8 (Rob: "why are we not saying the right unleashed on the site").
# The name a person reads is \u00b5nleashed. Plain "unleashed" is allowed only
# where it is an identifier, and this is the allowlist of where that is:
#   - joined to something that makes it a name of another kind, which the
#     pattern itself steps over: unleashed.local, unleashedbbs.com,
#     unleashed_BBS, unleashed-directory, /unleashed, @unleashed;
#   - inside <code>, <pre>, <kbd> or <samp>: a hostname, a password, a
#     command, a protocol value, typed or shown exactly;
#   - inside a screen capture, <svg class="... shot">, which quotes what
#     the board's own screen shows, its hostname field included.
# Anything else a reader meets, text or the attributes a reader or a screen
# reader gets (alt, title, aria-label, data-tip, placeholder, and the meta
# a link preview shows), fails. URLs in href and src are never read.
NAME_WORD = re.compile(r"(?<![\w./@-])unleashed(?![\w.-])", re.I)
NAME_CODE = ("code", "pre", "kbd", "samp")
NAME_ATTRS = ("alt", "title", "aria-label", "data-tip", "placeholder")


class NameSweep(HTMLParser):
    """Every plain "unleashed" a reader would meet on one page, outside the
    allowlist above, as short snippets."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0            # inside <script> or <style>
        self.code = 0              # inside an allowed identifier element
        self.svg = 0               # svg nesting
        self.shot_at = None        # the svg depth of a screen capture
        self.bad = []

    def _allowed(self):
        return self.code > 0 or self.shot_at is not None

    def _look(self, where, text):
        for m in NAME_WORD.finditer(text or ""):
            self.bad.append(where + ": " + " ".join(
                text[max(0, m.start() - 40): m.end() + 30].split()))

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self.hidden += 1
        if tag in NAME_CODE:
            self.code += 1
        if tag == "svg":
            self.svg += 1
            if self.shot_at is None and "shot" in (a.get("class") or "").split():
                self.shot_at = self.svg
        if self._allowed():
            return
        for k in NAME_ATTRS:
            self._look(f"<{tag} {k}>", a.get(k))
        if tag == "meta":
            key = a.get("property") or a.get("name") or ""
            if key.startswith(("og:", "twitter:")) or key == "description":
                self._look(f"<meta {key}>", a.get("content"))

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.hidden:
            self.hidden -= 1
        if tag in NAME_CODE and self.code:
            self.code -= 1
        if tag == "svg" and self.svg:
            if self.shot_at == self.svg:
                self.shot_at = None
            self.svg -= 1

    def handle_data(self, data):
        if not self.hidden and not self._allowed():
            self._look("text", data)


# A partition table as ESP-IDF's gen_esp32part.py writes one: 32-byte
# entries (AA 50, type, subtype, offset and size little-endian, a 16-byte
# label, 4 bytes of flags), an MD5 entry (EB EB), erased flash after it.
# The server places an image set's parts by the set's own table (firmware
# 1.1.2), so a scratch release needs a real one.
ESP32_LAYOUT = (("nvs", 1, 0x02, 0x9000, 0x6000), ("otadata", 1, 0x00, 0xF000, 0x2000),
                ("phy_init", 1, 0x01, 0x11000, 0x1000),
                ("ota_0", 0, 0x10, 0x20000, 0x180000), ("ota_1", 0, 0x11, 0x1A0000, 0x180000),
                ("logs", 1, 0x82, 0x320000, 0x8000), ("userdata", 1, 0x82, 0x328000, 0x98000),
                ("storage", 1, 0x82, 0x3C0000, 0x40000))
# The S3's own 8 MB layout from firmware 1.1.2 (partitions_s3.csv).
S3_LAYOUT = (("nvs", 1, 0x02, 0x9000, 0x6000), ("otadata", 1, 0x00, 0xF000, 0x2000),
             ("phy_init", 1, 0x01, 0x11000, 0x1000),
             ("ota_0", 0, 0x10, 0x20000, 0x300000), ("ota_1", 0, 0x11, 0x320000, 0x300000),
             ("logs", 1, 0x82, 0x620000, 0x8000), ("userdata", 1, 0x82, 0x628000, 0x158000),
             ("storage", 1, 0x82, 0x780000, 0x80000))


def pt_bin(rows):
    import hashlib
    import struct
    body = b"".join(b"\xaa\x50" + bytes([t, s]) + struct.pack("<II", off, size)
                    + name.encode("ascii").ljust(16, b"\0") + b"\0" * 4
                    for name, t, s, off, size in rows)
    md5 = b"\xeb\xeb" + b"\xff" * 14 + hashlib.md5(body).digest()
    return (body + md5).ljust(0xC00, b"\xff")


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


class _Stay(urllib.request.HTTPRedirectHandler):
    """Report a redirect rather than follow it: get() decides where to go."""
    def redirect_request(self, *args, **kwargs):
        return None


_stay = urllib.request.build_opener(_Stay)


def get_raw(path, host=None, headers=None):
    """(status, body, Location) for one GET, following nothing."""
    req = urllib.request.Request(f"{BASE}{path}")
    if host:
        req.add_header("Host", host)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with _stay.open(req, timeout=5) as r:
            return r.status, r.read().decode(), r.headers.get("Location", "")
    except urllib.error.HTTPError as e:
        # A 404 is an answer, not a failure. Checking that something is
        # absent is as much a test as checking it is there.
        return e.code, e.read().decode(errors="replace"), e.headers.get("Location", "")


def get(path, host=None, headers=None):
    """One page as a browser gets it from this server: a 301 to another page
    here (an old guide address, /docs/<page>) is followed, and a 301 that
    leaves this server is returned as it is, never fetched."""
    code, body, loc = get_raw(path, host, headers)
    for _hop in range(3):
        if code not in (301, 302) or not loc.startswith("/"):
            break
        code, body, loc = get_raw(loc, host, headers)
    return code, body


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


# The boards table from site 1.1.0 to 1.3.9, what the live database is before
# 1.3.10: every column but closed. It is 1.0.0's with the SD card added,
# which is all 1.1.0's setup() added; the assert says so.
OLD_SCHEMA_139 = OLD_SCHEMA_100.replace(
    "    interests    TEXT NOT NULL DEFAULT ''\n);",
    "    interests    TEXT NOT NULL DEFAULT '',\n    sd           INTEGER\n);", 1)
assert OLD_SCHEMA_139.count("sd           INTEGER") == 1


def start_server(db, port):
    """A directory on its own port and database, its output drained, and
    whether it came up. The caller terminates it."""
    env = dict(os.environ, DIRECTORY_PAGE_CACHE="0", DIRECTORY_DB=db,
               DIRECTORY_PORT=str(port), DIRECTORY_MIN_SECONDS="0",
               DIRECTORY_ADDRESS_PER_MINUTE="0")
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
    was_db, was_ok, was_min = S.DB_PATH, S.BADGE_CODES_OK, S.MIN_SECONDS
    try:
        S.DB_PATH = mem_db
        S.setup()
        _st, first, _h = S.announce({"name": "Kept", "port": 6400, "token": "",
                                     "support": ["mntlh"], "interests": ["c64"]},
                                    "192.0.2.90")
        S.BADGE_CODES_OK = False
        # The rate limit is per board since 1.3.12, so another address no
        # longer gets this past it: the clock is switched off instead, so
        # the rate limit cannot be what left the row alone.
        S.MIN_SECONDS = 0
        st2, _b, _h = S.announce({"name": "Kept", "port": 6400, "token": first["token"],
                                  "support": [], "interests": []}, "192.0.2.91")
        con_n = sqlite3.connect(mem_db)
        kept = con_n.execute("SELECT support, interests FROM boards").fetchone()
        con_n.close()
    finally:
        S.DB_PATH, S.BADGE_CODES_OK, S.MIN_SECONDS = was_db, was_ok, was_min
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
          found == [("soft", "\u00b5nleashed 1.0.0"),
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
          and badges_in(ident) == [("soft", "\u00b5nleashed 1.0.0"),
                                   ("sys", "Compaq 486 &lt;b&gt;&amp;&lt;/b&gt;")])
    check("its tooltip says the software and the version, as the board sent them",
          'aria-label="Software: \u00b5nleashed 1.0.0, as the board reports it."' in row)
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
    feet = {"list": page, "data": get("/data")[1]}
    check("and the footer links the legend on every face",
          all('<a href="/badges">Badges</a>' in f.split("<footer>")[1] for f in feet.values()))
    check("the JSON says what the board runs and which version (site 1.0.0)",
          bb.get("software") == "unleashed" and bb.get("version") == "1.0.0"
          and jb.get("software") == "" and jb.get("version") == "")
    feed = get("/feed.xml")[1]
    check("the feed says it in words, escaped for XML",
          "Software: \u00b5nleashed 1.0.0" in feed
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
          '<link rel="canonical" href="https://boards.example/">' in one)
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
              '<a href="/docs/camera">How a caller uses it</a>.' in leg)
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
          and "<b>Software</b>" in leg and ">\u00b5nleashed 1.0.0</span>" in leg)
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
          '<a class="here" href="/badges">Badges</a>' in leg)
    check("and on the about face, not to What this is",
          "What this is" not in leg)
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
                DIRECTORY_PORT=str(port4), DIRECTORY_MIN_SECONDS="0",
                DIRECTORY_ADDRESS_PER_MINUTE="0")
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
              == [("soft", "µnleashed"), ("age", "1m")])
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
        check("its table gains interests, sd and closed and nothing else, and "
              "matches a new one",
              cols == want and cols - had == {"interests", "sd", "closed"} and had <= cols)
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
        check("its table gains sd and closed and nothing else, and matches a new one",
              cols == want and cols - had == {"sd", "closed"} and had <= cols)
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
              code == 200 and [n for n, _k, _h in list_rows(home)] == names)
        code, full = page("/directory")
        check("/directory shows all twelve, busiest first",
              code == 200 and [n for n, _k, _h in list_rows(full)] == names
              and "<h1>Communities online</h1>" in full)
        check("and lights Communities online in the menu",
              '<a class="here" href="/">Communities online</a>' in full)
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
        _c, fq = page("/?b=files&q=E")
        check("a filter or a search asked of the front page is sent to /directory",
              _c == 200 and [n for n, _k, h in list_rows(fq) if not h]
              == [n for n, _k, h in list_rows(both) if not h])
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


def rate_checks(S):
    """Site 1.3.12. The heartbeat rate limit is per board, not per address:
    Rob runs Unleashed HQ on 6400 and The Rusty Antenna on 6405 behind one
    home address, and one board's heartbeat got the other's caller-join
    update refused. In this process, on a scratch database, with the
    shipped 30 s clock; time passes by ageing the rate tables, which is
    how the rest of the suite moves a clock it does not own."""
    import sqlite3
    print("The rate limit is per board")
    dbr = os.path.join(tempfile.gettempdir(), f"dirrate{os.getpid()}.db")
    for leftover in (dbr, dbr + "-wal", dbr + "-shm"):
        if os.path.exists(leftover):
            os.remove(leftover)
    was = (S.DB_PATH, S.MIN_SECONDS, S.ADDRESS_PER_MINUTE)
    home = "198.51.100.7"

    def beat(name, port, token="", addr=home):
        st, body, _h = S.announce({"name": name, "port": port, "token": token}, addr)
        return st, body

    def age(seconds):
        con_a = sqlite3.connect(dbr)
        con_a.execute("UPDATE beatclock SET at = at - ?", (seconds,))
        con_a.execute("UPDATE addrminute SET start = start - ?", (seconds,))
        con_a.commit()
        con_a.close()

    try:
        S.DB_PATH, S.MIN_SECONDS, S.ADDRESS_PER_MINUTE = dbr, 30, 20
        S.setup()
        st_hq, hq = beat("Unleashed HQ", 6400)
        st_tra, tra = beat("The Rusty Antenna", 6405)
        check("two boards behind one address, on two ports, are both listed "
              "at once", st_hq == 200 and st_tra == 200)
        st_hq2, hq2 = beat("Unleashed HQ", 6400, hq.get("token", ""))
        check("one board posting twice inside 30 s is still refused, "
              "the post with its new token timed from the one that made it",
              st_hq2 == 429 and hq2.get("error") == "slow down")
        st_again, _b = beat("Unleashed HQ", 6400)
        check("and so is a board that forgot its token, posting again from "
              "the same address and port", st_again == 429)
        age(31)
        st_hq3, _b = beat("Unleashed HQ", 6400, hq["token"])
        st_tra3, _b = beat("The Rusty Antenna", 6405, tra["token"])
        check("each heartbeats inside 30 s of the other and both are accepted",
              st_hq3 == 200 and st_tra3 == 200)
        age(20)
        st_early, _b = beat("Unleashed HQ", 6400, hq["token"])
        age(11)
        st_later, _b = beat("Unleashed HQ", 6400, hq["token"])
        check("a refused post does not restart the clock: 20 s early is "
              "refused, and 11 s after that refusal is accepted",
              st_early == 429 and st_later == 200)
        age(31)
        st_moved, _b = beat("Unleashed HQ", 6400, hq["token"], "203.0.113.50")
        st_moved2, _b = beat("Unleashed HQ", 6400, hq["token"], "198.51.100.7")
        check("a board is its token wherever it posts from: a new address "
              "does not buy it a second heartbeat", st_moved == 200 and st_moved2 == 429)

        print("A ceiling per address")
        S.ADDRESS_PER_MINUTE = 3
        busy = "198.51.100.8"
        codes = [beat(f"Busy {i}", 7000 + i, addr=busy) for i in range(4)]
        check("past the ceiling an address is refused, whatever board it "
              "says it is", [c for c, _b in codes] == [200, 200, 200, 429]
              and codes[3][1].get("error") == "too many announces from this address")
        st_other, _b = beat("Elsewhere", 6400, addr="198.51.100.9")
        check("and another address is not", st_other == 200)
        age(61)
        st_next, _b = beat("Busy 3", 7003, addr=busy)
        check("the next minute it is heard again, the refusal not counted",
              st_next == 200)
        con_r = sqlite3.connect(dbr)
        n_now = con_r.execute("SELECT n FROM addrminute WHERE address=?",
                              (busy,)).fetchone()
        tables = {r[0] for r in con_r.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        con_r.close()
        check("a refused post counts nothing against its address",
              n_now == (1,))
        check("the old per-address table is gone, and the two clocks are there",
              "hits" not in tables and {"beatclock", "addrminute"} <= tables)
        S.ADDRESS_PER_MINUTE = 0
        many = [beat(f"Many {i}", 8000 + i, addr="198.51.100.10")[0] for i in range(4)]
        check("0 switches the ceiling off", many == [200] * 4)
    finally:
        S.DB_PATH, S.MIN_SECONDS, S.ADDRESS_PER_MINUTE = was
        for leftover in (dbr, dbr + "-wal", dbr + "-shm"):
            try:
                os.remove(leftover)
            except OSError:
                pass


def closed_checks(S):
    """Site 1.3.10 (Rob: a board whose sysop has closed it shows as
    "Temporarily closed"; if its heartbeats stop, the stale and delisting
    rules apply as now). A directory of its own, seeded so the order is
    known: two open boards up, a closed one up that is busier than both, a
    quiet one and a quiet closed one, and a board for every way of sending
    closed, each stored as closed first so that open has to be written."""
    import inspect
    import sqlite3
    print("Closed boards")
    dbc = os.path.join(tempfile.gettempdir(), f"dirclosed{os.getpid()}.db")
    for leftover in (dbc, dbc + "-wal", dbc + "-shm"):
        if os.path.exists(leftover):
            os.remove(leftover)
    now = int(time.time())
    # name, token, state, busy, minutes24, closed, seconds since last seen
    seed = [("Busy Open", "b" * 32, "online", 3, 300, 0, 0),
            ("Idle Open", "i" * 32, "online", 0, None, 0, 0),
            ("Shut Shop", "s" * 32, "online", 5, 900, 1, 0),
            ("Quiet Place", "q" * 32, "offline", 0, 50, 0, 7200),
            ("Quiet Shut", "u" * 32, "offline", 0, 2000, 1, 7200)]
    # Every way of sending closed, each board stored closed until it speaks.
    sends = [("True Board", True), ("False Board", False), ("Missing Board", None),
             ("Junk Yes", "yes"), ("Junk One", 1), ("Junk Null", "null"),
             ("Junk List", [True]), ("Junk Text", "true"), ("Junk Map", {"closed": True})]
    for i, (name, _v) in enumerate(sends):
        seed.append((name, f"{i:032d}", "online", 0, None, 1, 0))
    con = sqlite3.connect(dbc)
    con.executescript(S.SCHEMA)
    for name, token, state, busy, mins, closed, ago in seed:
        con.execute("INSERT INTO boards(token, name, owner, description, software, "
                    "version, host, port, nodes, busy, minutes24, state, first_seen, "
                    "last_seen, streak_start, public_at, features, closed) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (token, name, "Op", "A board", "unleashed", "1.1.1",
                     name.lower().replace(" ", "-") + ".example", 6400, 10, busy, mins,
                     state, now - 86400, now - ago, now - 86400, now - 86400,
                     "chat", closed))
    con.commit()
    con.close()
    portc = PORT + 4
    basec = f"http://127.0.0.1:{portc}"
    serverc, outc, upc = start_server(dbc, portc)

    def page(path):
        code, _t, body = fetch(path, basec) if upc else (None, "", b"")
        return code, body.decode("utf-8", "replace")

    def stored(name):
        c = sqlite3.connect(dbc)
        c.row_factory = sqlite3.Row
        r = c.execute("SELECT * FROM boards WHERE name=?", (name,)).fetchone()
        c.close()
        return r

    def api():
        return {b["name"]: b for b in json.loads(page("/api/boards.json")[1])["boards"]}

    try:
        check("the server starts on a seeded directory"
              + ("" if upc else "  <- " + b"".join(outc[-3:]).decode("utf-8", "replace")),
              upc)
        codes = []
        for i, (name, value) in enumerate(sends):
            body = {"name": name, "port": 6400, "token": f"{i:032d}", "nodes": 10,
                    "busy": 2 if name == "True Board" else 0,
                    "host": name.lower().replace(" ", "-") + ".example"}
            if value is not None:
                body["closed"] = value
            codes.append(post_from(body, f"203.0.113.{40 + i}", basec)[0])
        check("a heartbeat with closed true, false, missing or junk is accepted, "
              "never refused", codes == [200] * len(sends))
        check("only a JSON true is stored as closed: false, missing, \"yes\", 1, "
              "\"null\", a list, \"true\" and an object are all open",
              stored("True Board")["closed"] == 1
              and all(stored(n)["closed"] == 0 for n, _v in sends[1:]))
        codeN, gotN = post_from({"name": "New And Shut", "port": 6400, "closed": True},
                                "203.0.113.90", basec)
        check("a board new to the directory can arrive closed, and still earns its "
              "listing the way any board does",
              codeN == 200 and gotN.get("state") == "pending"
              and stored("New And Shut")["closed"] == 1)

        listed = api()
        check("/api/boards.json carries closed on every board, true or false, never null",
              all(isinstance(b.get("closed"), bool) for b in listed.values())
              and listed.get("True Board", {}).get("closed") is True
              and listed.get("Shut Shop", {}).get("closed") is True
              and listed.get("False Board", {}).get("closed") is False
              and listed.get("Junk Yes", {}).get("closed") is False
              and "New And Shut" not in listed)
        check("a quiet board keeps what it last said, beside its state",
              listed.get("Quiet Shut", {}).get("closed") is True
              and listed.get("Quiet Shut", {}).get("state") == "offline")

        code, full = page("/directory")
        shut = badge_row(full, "Shut Shop")
        busy = badge_row(full, "Busy Open")
        check("a closed board that is up says Temporarily closed where its "
              "callers-on figure would be",
              code == 200
              and "<td class='status' data-label='State'><span class='state closed'>"
                  "<span class='shut'>Temporarily closed</span>" in shut
              and "of 10 on" not in shut and "5 of" not in shut)
        check("and its address is words, not a telnet:// link to dial",
              "<span class='nodial'>shut-shop.example 6400</span>" in shut
              and "telnet://" not in shut and "<a href='telnet" not in shut)
        check("an open board keeps its callers-on figure and its link",
              "3 of 10 on" in busy
              and "<a href='telnet://busy-open.example:6400'" in busy
              and "Temporarily closed" not in busy and "nodial" not in busy)
        check("the marker has its own style: the human colour, in a box, and the "
              "address in --dim with no dotted rule",
              ".state.closed .shut { display:inline-block; color:var(--warm);" in full
              and ".addr .nodial { color:var(--dim);" in full)
        order = [n for n, _k, _h in list_rows(full)]
        up_open = [n for n, b in listed.items()
                   if b["state"] == "online" and not b["closed"]]
        up_shut = [n for n, b in listed.items() if b["state"] == "online" and b["closed"]]
        quiet = [n for n, b in listed.items() if b["state"] == "offline"]
        check("the list: every open board that is up, then the closed ones, busier "
              "or not, then the quiet ones",
              len(order) == len(listed)
              and set(order[:len(up_open)]) == set(up_open)
              and set(order[len(up_open):len(up_open) + len(up_shut)])
              == {"Shut Shop", "True Board"} == set(up_shut)
              and set(order[len(up_open) + len(up_shut):]) == set(quiet)
              and order[0] == "Busy Open")
        check("a quiet board that was closed is quiet like any other: no marker, "
              "its link as a quiet board's is",
              "quiet, " in badge_row(full, "Quiet Shut")
              and "Temporarily closed" not in badge_row(full, "Quiet Shut")
              and "<a href='telnet://quiet-shut.example:6400'" in badge_row(full, "Quiet Shut"))
        # Busy Open's 3; Shut Shop's 5 and True Board's 2 are not added.
        n_listed = len(listed)
        check("it counts as listed, but its callers are not added to the people "
              "connected",
              f"<span class='n'>{n_listed}</span> communities listed, with "
              "<span class='n'>3</span> people connected right now." in full)
        check("and the page's description counts only the open boards that are up",
              f'content="{len(up_open)} communities online and 3 people connected' in full)
        _c, chat = page("/directory?b=chat")
        check("closed is not a badge, so the filter neither offers it nor loses the "
              "board: a closed board with chat is found by chat",
              "closed" not in S.FILTER_KEYS
              and "Shut Shop" in [n for n, _k, h in list_rows(chat) if not h])

        _c, feed = page("/feed.xml")
        item = feed[feed.find("<title>Shut Shop</title>"):]
        item = item[:item.find("</item>")]
        open_item = feed[feed.find("<title>Busy Open</title>"):]
        open_item = open_item[:open_item.find("</item>")]
        check("the feed says a closed board is closed, and gives its address rather "
              "than a number to dial",
              "Temporarily closed: not taking calls right now." in item
              and "Address: shut-shop.example 6400" in item and "Dial:" not in item
              and "Dial: busy-open.example 6400" in open_item
              and "Temporarily closed" not in open_item)

        # It opens again: the next heartbeat without closed takes the marker
        # away, and its figures put it back at the top.
        post_from({"name": "Shut Shop", "port": 6400, "token": "s" * 32, "nodes": 10,
                   "busy": 5, "minutes24": 900, "host": "shut-shop.example"},
                  "203.0.113.70", basec)
        _c, again = page("/directory")
        row = badge_row(again, "Shut Shop")
        check("opened again, the next heartbeat takes the marker away and puts back "
              "its figure, its link and its place",
              "Temporarily closed" not in row and "5 of 10 on" in row
              and "<a href='telnet://shut-shop.example:6400'" in row
              and [n for n, _k, _h in list_rows(again)][0] == "Shut Shop"
              and api().get("Shut Shop", {}).get("closed") is False)

        # Its heartbeats stop: stale on the same clock as any board, then gone.
        c = sqlite3.connect(dbc)
        c.execute("UPDATE boards SET last_seen=? WHERE name='True Board'",
                  (now - 10 * 60 * S.MISSED_BEATS - 60,))
        c.commit()
        c.close()
        _c, stale = page("/directory")
        gone_quiet = api().get("True Board", {})
        check("a closed board whose heartbeats stop goes quiet, as any board does",
              gone_quiet.get("state") == "offline"
              and "quiet, " in badge_row(stale, "True Board")
              and "Temporarily closed" not in badge_row(stale, "True Board"))
        c = sqlite3.connect(dbc)
        c.execute("UPDATE boards SET last_seen=? WHERE name='True Board'",
                  (now - int(S.EXPIRE_DAYS * 86400) - 60,))
        c.commit()
        c.close()
        check("and is delisted on the same clock too", "True Board" not in api())

        check("row_closed and shut_now: a row with no column is open, and a quiet "
              "board is never shown closed",
              S.row_closed({}) is False and S.row_closed({"closed": 1}) is True
              and not S.shut_now({"state": "offline", "closed": 1})
              and S.shut_now({"state": "online", "closed": 1}))
        proto = open("PROTOCOL.md", encoding="utf-8").read()
        check("PROTOCOL.md documents closed: a boolean, only true closes, and not a "
              "listing state",
              "| `closed` | boolean | no |" in proto and "## Closed boards" in proto
              and "Only `true` closes" in proto and "It is not a listing state" in proto)
        check("and the data page says the JSON carries it",
              "(<code>closed</code>, true or false)" in inspect.getsource(S.data_page))

    finally:
        serverc.terminate()
        try:
            serverc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            serverc.kill()
        for leftover in (dbc, dbc + "-wal", dbc + "-shm"):
            try:
                os.remove(leftover)
            except OSError:
                pass

    # ----------------------------------------------------------------------
    # And from 1.1.0 to 1.3.9, which is the live database now: every column
    # but closed. One column added, every row open, and the next heartbeat
    # can close it.
    print("A database from 1.3.9, before closed")
    db_139 = os.path.join(tempfile.gettempdir(), f"dir139{os.getpid()}.db")
    for leftover in (db_139, db_139 + "-wal", db_139 + "-shm"):
        if os.path.exists(leftover):
            os.remove(leftover)
    con = sqlite3.connect(db_139)
    con.executescript(OLD_SCHEMA_139)
    con.execute("INSERT INTO boards(token, name, owner, software, version, host, port, "
                "nodes, busy, state, first_seen, last_seen, streak_start, public_at, "
                "beats, sd) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                ("d" * 32, "Before Closed", "Sparks", "unleashed", "1.1.0",
                 "before.example", 6400, 10, 1, "online", now - 30 * 86400, now,
                 now - 30 * 86400, now - 30 * 86400, 700, 32))
    con.commit()
    con.close()
    port8 = PORT + 3
    base8 = f"http://127.0.0.1:{port8}"
    server8, out8, up8 = start_server(db_139, port8)
    try:
        home8 = fetch("/directory", base8) if up8 else (None, "", b"")
        check("the server starts on it and serves the list"
              + ("" if up8 else "  <- " + b"".join(out8[-3:]).decode("utf-8", "replace")),
              up8 and home8[0] == 200 and b"Before Closed" in home8[2])
        con = sqlite3.connect(db_139)
        con.row_factory = sqlite3.Row
        cols = {r["name"] for r in con.execute("PRAGMA table_info(boards)")}
        r = con.execute("SELECT * FROM boards WHERE token=?", ("d" * 32,)).fetchone()
        con.close()
        fresh = sqlite3.connect(":memory:")
        fresh.executescript(S.SCHEMA)
        want = {x[1] for x in fresh.execute("PRAGMA table_info(boards)")}
        fresh.close()
        was_mem = sqlite3.connect(":memory:")
        was_mem.executescript(OLD_SCHEMA_139)
        had = {x[1] for x in was_mem.execute("PRAGMA table_info(boards)")}
        was_mem.close()
        check("its table gains closed and nothing else, and matches a new one",
              cols == want and cols - had == {"closed"} and had <= cols)
        check("the old row is untouched and reads as open",
              r["closed"] == 0 and r["sd"] == 32 and r["beats"] == 700
              and r["state"] == "online")
        row8 = badge_row(home8[2].decode("utf-8"), "Before Closed")
        listed8 = {b["name"]: b for b in json.loads(
            fetch("/api/boards.json", base8)[2].decode("utf-8"))["boards"]}
        check("its row and the JSON say open",
              "1 of 10 on" in row8 and "<a href='telnet://before.example:6400'" in row8
              and listed8.get("Before Closed", {}).get("closed") is False)
        code8, _b = post_from({"name": "Before Closed", "port": 6400, "token": "d" * 32,
                               "nodes": 10, "busy": 0, "host": "before.example",
                               "software": "unleashed", "version": "1.1.1",
                               "closed": True}, "192.0.2.77", base8)
        con = sqlite3.connect(db_139)
        con.row_factory = sqlite3.Row
        r = con.execute("SELECT * FROM boards WHERE token=?", ("d" * 32,)).fetchone()
        con.close()
        row8 = badge_row(fetch("/directory", base8)[2].decode("utf-8"), "Before Closed")
        check("its next heartbeat, closed, keeps its listing and shows it closed",
              code8 == 200 and r["closed"] == 1 and r["beats"] == 701
              and r["state"] == "online" and "Temporarily closed" in row8
              and "telnet://" not in row8)
        S.DB_PATH, was = db_139, S.DB_PATH
        try:
            S.setup()
            again = True
        except Exception:
            again = False
        S.DB_PATH = was
        check("and starting again on it changes nothing", again)
    finally:
        server8.terminate()
        try:
            server8.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server8.kill()
        for leftover in (db_139, db_139 + "-wal", db_139 + "-shm"):
            try:
                os.remove(leftover)
            except OSError:
                pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """An opener that reports a redirect instead of following it."""
    def redirect_request(self, *args, **kwargs):
        return None


def skins_checks(S):
    """Site 1.3.14, rewritten in 1.3.17. /skins, making display skins: coming
    soon for display boards, the firmware with skins in testing, the stock
    set to download now with a picture of each, the upload route through
    the Skins file area first, then the card, and the skin.txt reference."""
    print("The skins page")
    code, sk = get("/skins")
    body = sk.split("<article>")[1].split("</article>")[0] if "<article>" in sk else ""
    flat = " ".join(body.split())
    check("/skins renders, with its drawing",
          code == 200 and has_h(sk, 1, "Skins")
          and S.ART["skin-parts"] in sk
          and 'role="img"' in S.ART["skin-parts"].split(">")[0]
          and "svg.art.skinart { width:100%; max-width:30rem;" in sk)
    note = body.split('<p class="aside">')[1].split("</p>")[0] if '<p class="aside">' in body else ""
    flat_note = " ".join(note.split())
    check("it opens with the status: coming soon, the firmware in testing, the Makerfabs "
          "first, linked to its entry on /hardware",
          body.index('<p class="aside">') < body.index("<h2")
          and "Skins are coming soon for display-enabled boards: the firmware with skins "
              "is in testing." in flat_note
          and 'href="https://unleashedbbs.com/hardware#makerfabs-esp32-s3-parallel-tft-3-5-v1-0"' in note
          and "480 by 320" in flat_note
          and not re.search(r"firmware \d", note))

    def sec(anchor):
        return (body.split(f'id="{anchor}"')[1].split("<h2")[0]
                if f'id="{anchor}"' in body else "")
    stock = sec("the-stock-skins")
    names = ("pc", "c64", "apple2", "atari", "imsai")
    check("the stock skins: a picture of each, from the guides' skins/, with its name",
          stock.count("<figure>") == 5 and '<div class="wide gallery skins">' in stock
          and all(f'<img src="/skins/skin-{n}.png" width="480" height="320" alt="{n}: '
                  in stock and f"<figcaption><code>{n}</code>:" in stock for n in names)
          and all(os.path.isfile(os.path.join(DOCS_DIR, "skins", f"skin-{n}.png"))
                  for n in names)
          and ".gallery.skins img {{ aspect-ratio:3 / 2; }}" in S.PAGE)
    check("and the two zips as links, still marked coming soon for display boards",
          '<a href="/skins/skins.zip">Download the stock skins for the card</a>' in stock
          and '<a href="/skins/skins-upload.zip">Download them as pairs to send</a>' in stock
          and "<b>Coming soon for display-enabled boards: the firmware with skins is in "
              "testing.</b>" in " ".join(stock.split())
          and all(os.path.isfile(os.path.join(DOCS_DIR, "skins", z))
                  for z in ("skins.zip", "skins-upload.zip"))
          and "ZIP-URL" not in sk and "STOCK-SKINS-ZIP" not in sk
          and "Download: coming soon" not in sk)
    zc = zipfile.ZipFile(os.path.join(DOCS_DIR, "skins", "skins.zip")).namelist()
    zu = zipfile.ZipFile(os.path.join(DOCS_DIR, "skins", "skins-upload.zip")).namelist()
    check("skins.zip is laid out for the card, skins-upload.zip in pairs",
          sorted(zc) == sorted(f"skins/{n}/{f}" for n in names
                               for f in ("skin.txt", "background.jpg"))
          and sorted(zu) == sorted(f"{n}.{e}" for n in names for e in ("txt", "jpg")))
    served = {}
    for f in ("skins.zip", "skin-pc.png", "../server.py", "nope.zip", "skin-pc.txt"):
        try:
            with urllib.request.urlopen(f"{BASE}/skins/{f}", timeout=10) as r:
                served[f] = (r.status, r.headers.get("Content-Type"), r.read())
        except urllib.error.HTTPError as e:
            served[f] = (e.code, None, b"")
    check("and they are served from here at /skins/, zips and pictures only",
          served["skins.zip"][:2] == (200, "application/zip")
          and served["skins.zip"][2] == open(os.path.join(DOCS_DIR, "skins", "skins.zip"),
                                             "rb").read()
          and served["skin-pc.png"][:2] == (200, "image/png")
          and served["../server.py"][0] == 404 and served["nope.zip"][0] == 404
          and served["skin-pc.txt"][0] == 404
          and not os.path.exists(os.path.join("static", "skins", "skin-pc.png")))
    check("no logos: said for the stock skins and for yours",
          "<b>No logos, and no trademark art.</b>" in stock
          and "must not use them either" in " ".join(stock.split())
          and "<b>Leave makers&#x27; logos and names off the machine.</b>" in body)
    five = sec("the-five-minute-version")
    check("the upload route comes first: the five-minute version ends by sending the "
          "pair through the Skins area",
          body.index('id="the-five-minute-version"') < body.index('id="get-the-tool"')
          < body.index('id="sending-it-to-the-board"')
          < body.index('id="or-copy-it-onto-the-card"')
          and five.index("mkskin.py check my_tower") < five.index("mkskin.py pair my_tower")
          < five.index("<code>FILES 12</code>") < five.index("<code>CONFIG panel</code>")
          and 'start="6"' in five)
    send = sec("sending-it-to-the-board")
    flat_send = " ".join(send.split())
    check("sending: area 12 on the Makerfabs, the pair's names, mkskin.py pair, YMODEM",
          "12 on the Makerfabs 3.5 inch board, and 14 on a board that also has a camera"
          in flat_send
          and "<code>my_tower.txt</code>" in send and "<code>my_tower.jpg</code>" in send
          and "python tools/mkskin.py pair my_tower -o to_send" in send
          and "YMODEM" in send and "<b>A folder beats a pair.</b>" in flat_send)
    card = sec("or-copy-it-onto-the-card")
    check("the card route is still there, SD UNMOUNT first",
          "<code>SD UNMOUNT</code>" in card and "<code>SD MOUNT</code>" in card)
    check("it says what a skin is, and the lights' modes",
          "<code>background.jpg</code>" in body and "<code>skin.txt</code>" in body
          and 'href="/docs/lights"' in body
          and all(f"<code>{w}</code>" in body for w in ("pc", "1541", "disk2", "breathe"))
          and "It works with no LED strip wired to the board at all." in flat)
    check("the key colours go through mkskin.py leds, written with -o",
          '<pre class="nowrap">python tools/mkskin.py leds keyed.png' in body
          and "--key drive=#FF00FF" in body and "-o my_tower/skin.txt" in body)
    ref = sec("skin-txt")
    words = sec("the-text-and-the-clock")
    check("skin.txt's reference is tables, every directive and every lines word",
          ref.count("<table>") == 2
          and all(f"<td><code>{d}" in ref for d in ("skin 1", "panel 480 320", "name ",
                  "drive X Y D STYLE", "activity X Y D", "strip N", "led I X Y D",
                  "text X Y W H", "lines ...", "clock X Y"))
          and all(f"<code>{w}</code>" in words for w in ("name", "address", "uptime",
                  "callers", "today", "heap", "card", "clock", "date", "last",
                  "ring", "blank", "who")))
    # The stock skin's own name is c64, and that is what CONFIG lists, so it
    # appears as a name; the machine is never named in prose.
    prose = re.sub(r"<code>c64</code>|skin-c64\.png|alt=\"c64:", "", flat)
    check("the page names no C64 in prose and no firmware version",
          "C64" not in prose and "Commodore" not in prose and "c64" not in prose
          and not re.search(r"\b1\.[12]\.\d+\b", flat))
    check("no word from the banned list, and no em dash",
          "\u2014" not in body
          and not re.search(r"\b(simply|just|easy|easily|of course|obviously)\b",
                            flat, re.I))
    check("it lights Build one, and /build and /lights link it",
          '<a class="here" href="/docs">' in sk
          and 'href="/docs/skins"' in get("/docs/lights")[1])
    setup = open(os.path.join("deploy", "setup.sh"), encoding="utf-8").read()
    check("setup.sh installs every file under static/, so static/skins/ reaches the server",
          'for f in "$DOCS_SRC"/skins/*.png "$DOCS_SRC"/skins/*.zip; do' in setup
          and 'install -m 644 "$f" "$DEST/docs.new/skins/"' in setup)


def main():
    if not HAVE_DOCS:
        print("This suite checks the guides the directory serves at /docs too: it\n"
              "wants a checkout of unleashed_documentation as docs/ or beside this\n"
              "one, or SELFTEST_DOCS naming it.")
        return 1
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
               DIRECTORY_ADDRESS_PER_MINUTE="0",
               DIRECTORY_LIST_DOMAIN="boards.example",
               DIRECTORY_HOME_URL="https://unleashedbbs.com",
               DIRECTORY_DOCS_DIR=DOCS_DIR,
               # No releases on disk: the suite makes its own where it needs one.
               DIRECTORY_FIRMWARE_DIR=os.path.join(tempfile.gettempdir(),
                                                   f"dirtest-nofw{os.getpid()}"))
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

        # One site since the split (2026-09-26): the board list at / and at
        # /directory, the data at /data. The manifesto and the rest of the
        # project's site are on their own server, and an old address for
        # one of their pages is answered here with a 301 to it.
        print("One site: the list, and the data at /data")
        _, page = get("/data")
        check("the data domain documents the API", "/api/boards.json" in page)
        check("and says what is not in it", "Nothing about callers" in page)

        _, page = get("/directory", host="boards.example")
        check("the list domain still lists boards", "Rusty Modem" in page)
        check("the list page owns the board-list heading",
              "Communities online" in page)
        _, home = get("/", host="boards.example")
        check("the front page of the directory is the board list",
              "Rusty Modem" in home and "<h1>Communities online</h1>" in home)

        # The board list's heading used to live in the shared page shell, so
        # it turned up above other pages as well. Every page brings its own.
        _, page = get("/data")
        check("nor does the data page",
              "Boards that are up right now" not in page)
        check("the data page has its own heading", "<h1>Data</h1>" in page)
        code, page = get("/data", host="boards.example")
        check("and so is the data page", code == 200 and "Endpoints" in page)

        # Everything that moved, answered with a 301 to its new home.
        print("Old addresses are sent where their pages live now")
        moved = {"/about": "https://unleashedbbs.com/about",
                 "/author": "https://unleashedbbs.com/author",
                 "/install": "https://unleashedbbs.com/install",
                 "/hardware": "https://unleashedbbs.com/hardware",
                 "/whofor": "https://unleashedbbs.com/whofor",
                 "/install/esp-web-tools/10.4.0/install-button.js":
                     "https://unleashedbbs.com/install/esp-web-tools/10.4.0/install-button.js",
                 "/static/esp32.jpg": "https://unleashedbbs.com/static/esp32.jpg",
                 "/cover.svg": "https://unleashedbbs.com/cover.svg",
                 "/build?x=1": "https://unleashedbbs.com/build?x=1"}
        wrong = [p for p, want in moved.items()
                 if get_raw(p)[0] != 301 or get_raw(p)[2] != want]
        check("a page of the project's site is sent there with a 301"
              + ("" if not wrong else "  <- " + ", ".join(wrong)), not wrong)
        # update.sh GETs /announce over plain HTTP and fails the deploy on
        # anything but 400/404/405: the catch-all must not 301 it (2.0.1).
        check("GET /announce is 405, never a redirect",
              get_raw("/announce")[0] == 405)
        if HAVE_DOCS:
            gone = [p for p in ("/setup", "/terminals", "/forward-asus", "/privacy",
                                "/sdcard", "/camera", "/skins")
                    if get_raw(p)[:3:2] != (301, "/docs" + p)]
            check("an old guide address is sent to /docs with a 301"
                  + ("" if not gone else "  <- " + ", ".join(gone)), not gone)
            code, idx = get("/docs")
            check("/docs lists the guides and lights Guides in the menu",
                  code == 200 and '<a class="here" href="/docs">Guides</a>' in idx
                  and 'href="/docs/setup"' in idx and 'href="/docs/terminals"' in idx)
        code, _b, _l = get_raw("/nothing-at-all")
        check("a name that is nobody's page is sent to the project's site, which "
              "says whether it has one", code == 301)
        code, _b, _l = get_raw("/docs/nothing-at-all")
        check("and a guide that does not exist is not found", code == 404)

        print("The feed")
        code, feed = get("/feed.xml")
        check("there is an RSS feed", code == 200 and "<rss version=\"2.0\"" in feed)
        check("the board that went public is in it", "Rusty Modem" in feed)
        check("with a date and a stable id", "pubDate" in feed and "board-" in feed)
        check("the queued one is not", "Squatter" not in feed)
        check("the page tells readers where the feed is",
              "application/rss+xml" in get("/directory")[1])

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
        code, page = get("/badges")
        check("a markdown page takes its title from its own first heading",
              "<title>What the badges mean - " in page)
        code, page = get("/forward-mesh")
        check("so the router pages are not four identical tabs",
              "<title>Port forwarding on eero and Google Nest Wifi - " in page)
        check("and a page with no menu entry lights its own section",
              '<a class="here" href="/docs">' in page)
        code, page = get("/dialing")
        check("dialing belongs to terminals",
              '<a class="here" href="/docs">' in page
              and has_h(page, 1, "Making the dial links work"))
        code, page = get("/sdcard")
        check("and the SD card page to build one",
              '<a class="here" href="/docs">' in page
              and has_h(page, 1, "Adding an SD card"))
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
        check("so does the terminal page's telnet warning",
              "/privacy" in get("/terminals")[1])




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
              'href="/docs/dialing">Did not connect?' in page)
        check("and the footer carries it on every page",
              '>Dial links</a>' in page)
        check("the dial link's tooltip no longer reads a URL out as text",
              "See /dialing" not in page)

        # Pages are files in pages/, routed by name. That lookup runs last
        # on purpose: put it earlier and it swallows real endpoints, which
        # is exactly what happened to /health the first time.
        for name in ("badges", "docs/forward", "docs/terminals", "docs/dialing",
                     "docs/sdcard", "docs/firstcall", "docs/privacy", "docs/setup",
                     "docs/lights", "docs/camera", "docs/skins",
                     "docs/forward-netgear", "docs/forward-tplink", "docs/forward-asus",
                     "docs/forward-xfinity", "docs/forward-mesh"):
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
              '<a class="here" href="/docs">' in lp)
        for pg in ("/sdcard", "/lights"):
            _, sp = get(pg)
            body = sp.split("<article>")[1]
            check(f"{pg} opens by saying the Waveshare S3 needs none of it",
                  body.index("The Waveshare S3 needs none of this.") < body.index("<h2")
                  and 'href="https://unleashedbbs.com/hardware#waveshare-esp32-s3-lcd-1-47"' in body)
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
        # NEW-1: /how links the rules it was said to cover.
        check("/how links the house rules, as /setup says it does",
              'href="/rules"' in get("/how")[1]
              and "[the house\nrules](/rules)" in
                  open(os.path.join(DOCS_DIR, "pages", "setup.md"), encoding="utf-8").read())


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
        print("The day chart")
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
        print("The setup guide")
        code, setup = get("/setup")
        flat_s = " ".join(setup.split())
        check("there is a setup page, under Build one",
              code == 200 and '<a class="here" href="/docs">Guides</a>' in setup)
        check("with every core CONFIG page",
              all(has_h(setup, 2, p)
                  for p in ("board", "limits", "accounts", "backup", "staff", "wifi")))
        check("and every plugin page",
              all(has_h(setup, 3, p)
                  for p in ("chat", "files", "forums", "info", "announce", "sd"))
              and has_h(setup, 3, "serial and example"))
        check("it starts with becoming the sysop, and points at the password step",
              has_h(setup, 2, "First, become the sysop")
              and "<code>unleashed</code>" in setup and 'href="https://unleashedbbs.com/install"' in setup)
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
            doc = json.load(open(os.path.join(DOCS_DIR, "shots", shot + ".json"),
                                 encoding="utf-8"))
            for row, attr in zip(doc["rows"], doc["attrs"]):
                if row.startswith(" ") and len(row) > 10 and attr[1] in "bc" and row[1:10].strip():
                    drawn.append(row[1:10].strip())
        missing_l = [l for l in drawn if f"<b>{l}</b>" not in setup]
        check("and every field those forms show is explained in a table"
              + ("" if not missing_l else "  <- " + ", ".join(missing_l)),
              len(drawn) >= 12 and not missing_l)
        check("each capture says where it came from",
              all(json.load(open(os.path.join(DOCS_DIR, "shots", n), encoding="utf-8"))
                  .get("source", "").startswith("unleashed BBS ")
                  for n in os.listdir(os.path.join(DOCS_DIR, "shots")) if n.endswith(".json")))
        check("and says the listing waits for the password to change",
              "the board will not list itself while the default password is still set"
              in flat_s)
        body_s = setup.split("</nav>")[1]
        check("/setup: Visit the web installer, and Build from source beside it",
              body_s.count('class="btn"') == 1 and body_s.count('class="btn2"') == 1
              and '<div class="cta"><p class="acts"><a class="btn" '
                  'href="https://unleashedbbs.com/install">Visit the web installer</a>' in body_s
              and '<a class="btn2" href="https://unleashedbbs.com/build'
                  '#for-developers-build-from-source">Build from source</a>' in body_s)
        check("/setup: and no button there says Install",
              not re.search(r'class="btn2?"[^>]*>[^<]*Install', body_s))
        check("the setup guide shows the first-boot setup as the board draws it",
              all(f'aria-label="{S.SHOTS[k][1][:30]}' in setup for k in (
                  "shot-setup-offer", "shot-setup-screen", "shot-config-staff",
                  "shot-newsysop-1"))
              and "This board has not been set up yet." in setup
              and "YOU ARE THE SYSOP" in setup)



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
        page_ids = re.findall(r'<h[1-3] id="([^"]+)"', get("/docs/setup")[1])
        check("including across the pieces a page is rendered in"
              + ("" if len(page_ids) == len(set(page_ids)) else "  <- duplicate ids"),
              (not HAVE_DOCS) or (len(page_ids) > 10 and len(page_ids) == len(set(page_ids))
                                  and "first-become-the-sysop" in page_ids
                                  and "board" in page_ids))








        # ------------------------------------------------------------------
        # The footer: two rows, then the colophon, on every face.
        print("The footer")
        log = open("CHANGELOG.md", encoding="utf-8").read()
        newest = re.search(r"^## (\d+\.\d+\.\d+)", log, re.M).group(1)
        check("the site's version is the changelog's newest heading",
              S.SITE_VERSION == newest)
        feet = [p.split("<footer>")[1] for p in (
            get("/")[1], get("/data")[1], get("/badges")[1])
            + ((get("/docs/setup")[1],) if HAVE_DOCS else ())]
        check("every footer has its two rows",
              all('<span class="lbl">Directory</span>' in f
                  and '<span class="lbl">Reference</span>' in f
                  and f.index("Directory") < f.index("Reference") for f in feet))
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
                 ("/directory", None): "https://boards.example/",
                 ("/data", None): "https://boards.example/data",
                 ("/badges", None): "https://boards.example/badges"}
        if HAVE_DOCS:
            canon[("/docs/setup", None)] = "https://boards.example/docs/setup"
        wrong = []
        for (path, host), want in canon.items():
            page = get(path, host=host)[1]
            if (f'<link rel="canonical" href="{want}">' not in page
                    or f'<meta property="og:url" content="{want}">' not in page):
                wrong.append(path + " " + (host or "list"))
        check("each page carries a canonical link and og:url for its own face"
              + ("" if not wrong else "  <- " + ", ".join(wrong)),
              not wrong and "@CANONICAL@" not in get("/how")[1])


        # ------------------------------------------------------------------
        # The 0.17.0 outage, so it cannot happen again: setup.sh copied only
        # some of what the server reads, and a server missing shots/ died at
        # import. First, the server has to start with nothing beside it.
        print("The server starts with nothing beside it")
        import shutil
        bare = tempfile.mkdtemp(prefix="dirbare")
        shutil.copy("server.py", os.path.join(bare, "server.py"))
        shutil.copy("sitekit.py", os.path.join(bare, "sitekit.py"))
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
        srv_text = (open("server.py", encoding="utf-8").read()
                    + open("sitekit.py", encoding="utf-8").read())
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
        # What this repository carries: the engine also reads folders only
        # the main site has (static/, firmware/), and the guides arrive from
        # their own checkout (docs/), all of which it does without.
        for name in sorted(n for n in read if os.path.exists(n)):
            top = name.split("/")[0]
            named = (top in loop_dirs
                     or re.search(r'\$SRC"?/' + re.escape(top) + r'\b', code_part))
            deep = ("/" not in name or top in loop_dirs
                    or f'cd "$SRC/{top}" && find' in code_part)
            if not (named and deep):
                missing_i.append(name)
        check("everything the server reads beside itself is installed by setup.sh"
              + ("" if not missing_i else "  <- " + ", ".join(missing_i)),
              len(read) >= 4 and not missing_i)

        print("The wordmark goes home")
        homes = {"the board list": (get("/")[1], "/"),
                 "a page": (get("/data")[1], "/")}
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
        faces_a = [get("/")[1], get("/data")[1], get("/badges")[1]]
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
              code == 200 and ctype == "image/png" and png_size(blob) == (1200, 630))
        # The pages the round 3 specification gives words of their own.
        def og(path, prop):
            m = re.search(r'<meta property="og:%s" content="([^"]*)">' % prop, get(path)[1])
            return html.unescape(m.group(1)) if m else None
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

        print("Every other page is still script-free")
        scripted = [p for p in ("/data", "/how", "/rules", "/docs", "/docs/terminals",
                                "/docs/firstcall", "/docs/forward", "/docs/privacy",
                                "/docs/sdcard", "/docs/dialing", "/docs/setup",
                                "/docs/lights", "/docs/camera", "/docs/skins")
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
        # The drawings. Same hand as the connection diagram, and every one
        # of them stands still for somebody who has asked for less motion.
        print("The drawings")
        # The rule that makes the resting state the drawing: no animation
        # is declared anywhere but inside the no-preference block, so a
        # reader who asked for less motion is given none at all.
        art_css = get("/docs/terminals" if HAVE_DOCS else "/how")[1].split(
            "svg.art { display:block;")[1].split("</style>")[0]
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

        # A Chromebook, as it is: one you control usually can, a managed one
        # usually cannot without its administrator, Chrome alone never can.
        flat_t = " ".join(term.split())
        check("the Chromebook section leads with who controls it",
              "A Chromebook you control can usually join a board" in flat_t
              and "Chrome on its own never can" in flat_t
              and "A Chromebook can call a board. Chrome cannot." not in flat_t)
        check("and dates the Chrome Apps change the way Google does",
              "ChromeOS 138, in July 2025, was the last release" in flat_t)
        _, data = get("/data")
        check("the health endpoint is not described as two bytes",
              "Two bytes" not in data)

        # Which ESP32. The rule is two cores and Wi-Fi on the chip, from
        # ESP32_BOARD_CHOICE.md, and only the WROOM-32E has been run. The
        # site used to say any module with 4 MB of flash would do, which is
        # true of a C3 with 4 MB of flash and it will not run the board.
        _, cam7 = get("/camera")
        c7 = (cam7.split('id="what-size-photos-can-i-take"')[1].split("<h2")[0]
              if 'id="what-size-photos-can-i-take"' in cam7 else "")
        flat_c7s = " ".join(c7.split())
        check("/camera says what size photos each board takes, and points at the table",
              "only the sizes its camera, and its build, can take" in flat_c7s
              and "up to 1600x1200" in flat_c7s and "320x240 or 640x480" in flat_c7s
              and "up to 2048x1536 expected" in flat_c7s
              and 'href="https://unleashedbbs.com/hardware#choosing-a-camera-board"' in c7
              and 'href="https://unleashedbbs.com/hardware#esp32-cam"' in cam7
              and '<a class="go" href="https://unleashedbbs.com/hardware#choosing-a-camera-board">' in cam7
              and all(S.gloss_key(w) for w in ("sensor", "megapixels", "PSRAM")))
        # A next step is a button, one a section at most, and a button that
        # is not the installer's own never says Install.
        crowded, says_install = [], []
        own_md = sorted(pathlib.Path("pages").glob("*.md"))
        docs_md = sorted(pathlib.Path(DOCS_DIR, "pages").glob("*.md")) if HAVE_DOCS else []
        for md in own_md + docs_md:
            body = get(("/docs/" if md in docs_md else "/") + md.stem)[1]
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
        for md in own_md + docs_md:
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
        css_l = get("/data")[1]
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
        # ------------------------------------------------------------------
        # Site 1.3.8: the name a reader sees is \u00b5nleashed, everywhere,
        # and every page is served as UTF-8 so the sign never arrives as
        # mojibake. See NAME_WORD for the allowlist.
        print("The name, with its micro sign")
        check("a board's software shows as \u00b5nleashed, and nothing else changes",
              S.software_shown("unleashed") == "\u00b5nleashed"
              and S.software_shown(" Unleashed ") == "\u00b5nleashed"
              and S.software_shown("Mystic") == "Mystic"
              and S.software_shown("unleashed-fork") == "unleashed-fork"
              and S.software_shown("") == "" and S.software_shown(None) == "")
        sweep_paths = sorted({"/", "/directory", "/badges", "/data", "/how", "/rules",
                              "/docs", "/docs/no-such-page"}
                             | {"/" + n[:-3] for n in os.listdir("pages")
                                if n.endswith(".md")}
                             | ({"/docs/" + n[:-3] for n in os.listdir(os.path.join(DOCS_DIR, "pages"))
                                 if n.endswith(".md")} if HAVE_DOCS else set()))
        slipped, not_utf8 = [], []
        for path in sweep_paths:
            for host in (None, "boards.example"):
                if host and path != "/":
                    continue
                req = urllib.request.Request(BASE + path)
                if host:
                    req.add_header("Host", host)
                try:
                    with urllib.request.urlopen(req, timeout=5) as r:
                        ctype, body = r.headers.get("Content-Type", ""), r.read()
                except urllib.error.HTTPError as e:
                    ctype, body = e.headers.get("Content-Type", ""), e.read()
                if "text/html" not in ctype:
                    continue
                where = (host or "") + path
                text = body.decode("utf-8")
                if ctype.replace(" ", "").lower() != "text/html;charset=utf-8" \
                        or not text.startswith('<!doctype html>\n<html lang="en">'
                                               '<head><meta charset="utf-8">'):
                    not_utf8.append(where)
                sweeper = NameSweep()
                sweeper.feed(text)
                slipped += [where + " " + b for b in sweeper.bad]
        check("no page shows a plain unleashed outside the identifier allowlist"
              + ("" if not slipped else "  <- " + " | ".join(slipped[:4])),
              len(sweep_paths) > (20 if HAVE_DOCS else 6) and not slipped)
        check("every page says UTF-8, in its header and first thing in its head"
              + ("" if not not_utf8 else "  <- " + ", ".join(not_utf8[:4])),
              not not_utf8)
        front = get("/")[1]
        check("and the name arrives as the micro sign, in the title and the preview",
              "- \u00b5nleashed BBS directory</title>" in front
              and '<meta property="og:site_name" content="%s">'
                  % html.escape(S.SITE_NAME, quote=True) in front
              and S.SITE_NAME.startswith("\u00b5nleashed"))
        probe = NameSweep()
        probe.feed('<p>Run unleashed.local and <code>unleashed</code>, see '
                   'unleashedbbs.com and unleashed_BBS.</p>'
                   '<svg class="art shot" aria-label="Hostname unleashed">'
                   '<text>unleashed</text></svg><p title="unleashed BBS">x</p>'
                   '<p>Update unleashed BBS</p>')
        check("the sweep itself: identifiers pass, a display name does not",
              [b.split(":")[0] for b in probe.bad] == ["<p title>", "text"])
        # The protocol value is untouched: the API and the database keep
        # what the board sent.
        api = json.loads(get("/api/boards.json")[1] or "[]")
        api_rows = api if isinstance(api, list) else api.get("boards", [])
        check("the API still carries the raw software value",
              all(b.get("software") != "\u00b5nleashed" for b in api_rows)
              and '"\u00b5nleashed' not in get("/api/boards.json")[1]
              and "\\u00b5nleashed" not in get("/api/boards.json")[1])

        print("The glossary")
        glossed = {}
        for f in (sorted(pathlib.Path("pages").glob("*.md"))
                  + (sorted(pathlib.Path(DOCS_DIR, "pages").glob("*.md")) if HAVE_DOCS else [])):
            for m in re.finditer(r"\[\[([^\[\]]+)\]\]", f.read_text(encoding="utf-8")):
                glossed.setdefault(m.group(1), f.name)
        unknown = [f"{w} ({f})" for w, f in glossed.items() if S.gloss_key(w) is None]
        check("every [[term]] in the pages has an entry in the table"
              + ("" if not unknown else "  <- " + ", ".join(unknown)),
              (glossed or not HAVE_DOCS) and not unknown)
        check("and every entry is one sentence or two, short enough for the box",
              all(20 <= len(d) <= 160 and d.endswith(".") for d in S.GLOSSARY.values())
              and all(S.gloss_key(k) is not None for k in S.GLOSSARY_FORMS)
              and set(S.GLOSSARY_FORMS.values()) <= set(S.GLOSSARY))
        leaked = [p_ for p_ in ("/", "/directory", "/badges", "/data", "/how")
                  + (("/docs/firstcall", "/docs/terminals", "/docs/forward",
                      "/docs/privacy", "/docs/setup") if HAVE_DOCS else ())
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
        ids = re.findall(r'aria-describedby="(gl\d+)"', get("/docs/terminals")[1])
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
              and 'href="/docs/terminals">Apps for joining</a>' in js_
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
                 "a page from the menu": get("/how")[1],
                 "the data page": get("/data")[1]}

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
        sections_ = [("/directory", None), ("/badges", None), ("/how", None),
                     ("/rules", None), ("/data", None)] + ([("/docs/setup", None)] if HAVE_DOCS else [])
        for path, host in sections_:
            first = re.search(r"<li>.*?<b>(.*?)</b>",
                              ticker_of(get(path, host=host)[1]), re.S)
            firsts.append(first.group(1) if first else None)
        check("and each section of the menu opens on a different one",
              None not in firsts and len(set(firsts)) == len(sections_))

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
        # Releases on disk. The main site's installer keeps them; the
        # directory reads the same folder (DIRECTORY_FIRMWARE_DIR), for the
        # update arrow on a board that is behind, the banner above the list,
        # and the guides' "::: from" gates. In-process first, then over HTTP
        # against a second directory pointed at scratch releases.
        print("Versions, and the update arrow")
        import shutil
        import sitekit as K
        fwroot = tempfile.mkdtemp(prefix="dirfw")
        whole = ["bootloader.bin", "partitions.bin", "ota_data_initial.bin",
                 "firmware.bin", "storage.bin"]

        def put(version, chip, names):
            d_ = os.path.join(fwroot, version, chip)
            os.makedirs(d_, exist_ok=True)
            for n in names:
                with open(os.path.join(d_, n), "wb") as fh:
                    fh.write(pt_bin(ESP32_LAYOUT) if n == "partitions.bin"
                             else b"placeholder, not firmware\n")

        put("1.0.0", "esp32", whole)
        put("1.0.1", "esp32", whole)
        was_dir = S.FIRMWARE_DIR
        S.FIRMWARE_DIR = K.FIRMWARE_DIR = pathlib.Path(fwroot)
        try:
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
                  and '>µnleashed 1.0.0</span><a class="bu" href="https://unleashedbbs.com/upgrade" ' in bb1
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
                     + S.badge("soft", "µnleashed 1.0.1",
                               "Software: µnleashed 1.0.1, as the board reports it.")
                     + "</span></span>"
                  and S.board_badges(brow(software="", version=""), int(time.time()),
                                     False, latest) == "")

            # Over HTTP: a second directory, pointed at the scratch releases,
            # with two boards announced to it.
            port2 = PORT + 1
            base2 = f"http://127.0.0.1:{port2}"
            db2 = os.path.join(tempfile.gettempdir(), f"dirtest{os.getpid()}b.db")
            env2 = dict(os.environ, DIRECTORY_PAGE_CACHE="0", DIRECTORY_DB=db2,
                        DIRECTORY_PORT=str(port2), DIRECTORY_FIRMWARE_DIR=fwroot,
                        DIRECTORY_DOCS_DIR=DOCS_DIR,
                        DIRECTORY_HOME_URL="https://unleashedbbs.com",
                        DIRECTORY_PENDING_HOURS="0.0006", DIRECTORY_MIN_SECONDS="0",
                        DIRECTORY_ADDRESS_PER_MINUTE="0")
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
                behind = {"software": "unleashed", "version": "1.0.0",
                          "name": "Behind Board", "port": 6400, "token": "",
                          "system": "ESP32-WROOM-32E", "features": ["chat"]}
                other = {"software": "Mystic", "version": "0.0.1",
                         "name": "Other Board", "port": 23, "token": ""}
                _c, tb = post_from(behind, "192.0.2.61", base2)
                _c, to = post_from(other, "192.0.2.62", base2)
                time.sleep(2.5)
                post_from(dict(behind, token=tb.get("token", "")), "192.0.2.61", base2)
                post_from(dict(other, token=to.get("token", "")), "192.0.2.62", base2)
                home3 = fetch("/directory", base2)[2].decode("utf-8")
                brow3, orow3 = badge_row(home3, "Behind Board"), badge_row(home3, "Other Board")
                check("on the list, the board behind carries the arrow and the other "
                      "software does not",
                      '>µnleashed 1.0.0</span><a class="bu" href="https://unleashedbbs.com/upgrade" ' in brow3
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
                check("the arrow is drawn in a dim cyan, a link and not an image",
                      ".bu { --bc:#5ab4b4;" in home3
                      and ".k-upd { --bc:#5ab4b4;" in home3
                      and 'role="img"' not in ul and "tabindex" not in ul)
                check("the banner shows once a 1.0.0 release is on disk",
                      '<div class="banner" role="note"><p>µnleashed BBS 1.0.1 is out. '
                      '<a href="https://unleashedbbs.com/install">Install it from your '
                      'browser.</a></p></div>' in home3
                      and home3.index('<div class="banner"')
                          < home3.index("<h1>Communities online</h1>"))
                check("and none on a directory with no release at all",
                      'class="banner"' not in get("/")[1])
                put("1.0.2", "esp32", whole)
                check("and the update arrow follows the newest release on disk",
                      "1.0.0 → 1.0.2." in badge_row(fetch("/directory", base2)[2].decode("utf-8"),
                                                         "Behind Board"))
                put("1.1.0", "esp32", whole)
                check("and the arrow now says 1.1.0",
                      "1.0.0 → 1.1.0." in badge_row(fetch("/directory", base2)[2].decode("utf-8"),
                                                         "Behind Board"))
                fwd5 = " ".join(fetch("/docs/forward", base2)[2].decode("utf-8").split())
                set5 = fetch("/docs/setup", base2)[2].decode("utf-8")
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
            S.FIRMWARE_DIR = K.FIRMWARE_DIR = was_dir
            shutil.rmtree(fwroot, ignore_errors=True)

        # ------------------------------------------------------------------
        # Deploying it. Site 1.2.1: the 1.2.0 deploy stuck on the droplet.
        # The pull moved HEAD, setup.sh failed, and every later run found
        # nothing to pull and never installed. setup.sh records the commit it
        # installed, last, and update.sh installs whenever that record is not
        # HEAD, for this repository and, since the split, for the guides.
        print("Deploying it")
        upd = open(os.path.join("deploy", "update.sh"), encoding="utf-8").read()
        setup_sh2 = open(os.path.join("deploy", "setup.sh"), encoding="utf-8").read()
        check("setup.sh records the commit it installed, after everything else",
              '> "$DEST/.installed.new"' in setup_sh2
              and 'mv "$DEST/.installed.new" "$DEST/.installed"' in setup_sh2
              and setup_sh2.index(".installed.new") > setup_sh2.index('say "Firewall"')
              and setup_sh2.index(".installed.new") > setup_sh2.index("systemctl restart"))
        check("update.sh installs when the last install did not finish",
              'INSTALLED="$(cat "$INSTALLED_FILE" 2>/dev/null || true)"' in upd
              and '[ "$INSTALLED" != "$OLD" ] && stale=1' in upd
              and "the last install did not finish" in upd
              and upd.index("the last install did not finish") < upd.index('loud "Installing..."')
              and "/srv/unleashed_directory/.installed" in upd)
        check("and the record is never committed",
              "/.installed" in open(".gitignore", encoding="utf-8").read())
        check("update.sh pulls the guides named in /etc/unleashed-directory/docs, and "
              "installs when they moved or their last install did not finish",
              "DOCS_FILE=/etc/unleashed-directory/docs" in upd
              and 'git -C "$DOCS" merge --ff-only "$DOCS_NEW"' in upd
              and '[ "$INSTALLED_DOCS" != "$DOCS_OLD" ] && stale=1' in upd
              and 'DOCS_SRC="$DOCS" "$SRC/deploy/setup.sh" $DOMAINS' in upd
              and '"$DEST/.installed-docs"' in setup_sh2)
        check("and no longer fetches firmware, which is the main site's",
              "fetch_release" not in upd and not os.path.exists(
                  os.path.join("deploy", "fetch_release.py")))
        # One Caddy file per service, and /announce never redirected.
        caddy_part = setup_sh2[setup_sh2.index('say "Web front end"'):
                               setup_sh2.index('say "Firewall"')]
        check("setup.sh writes its own sites file and a Caddyfile that gathers them",
              'MINE="$SITES/directory.caddy"' in caddy_part
              and "import /etc/caddy/sites/*.caddy" in caddy_part
              and "caddy validate" in caddy_part)
        check("with /announce answered over plain HTTP and everything else sent "
              "up to HTTPS on the name it was asked for",
              caddy_part.index("@announce path /announce")
              < caddy_part.index("redir https://{host}{uri} permanent"))
        check("and it refuses a domain another service already serves, and will "
              "not replace an old Caddyfile that would leave a name unserved",
              "is already served by" in caddy_part
              and "and nothing in $SITES would after this" in caddy_part)
        check("and it refuses the site's own domain, which would loop its 301s, and "
              "clears guides left in the install from before the split",
              "is the project's own site (DIRECTORY_HOME_URL), not the directory." in setup_sh2
              and setup_sh2.index("(DIRECTORY_HOME_URL), not the directory")
                  < setup_sh2.index('say "Packages"')
              and 'rm -f "$DEST"/pages/*.md' in setup_sh2)
        unit = open(os.path.join("deploy", "unleashed-directory.service"),
                    encoding="utf-8").read()
        check("the unit names the site, the guides and the site's firmware folder",
              "Environment=DIRECTORY_URL=https://unleashedbbs.net" in unit
              and "Environment=DIRECTORY_HOME_URL=https://unleashedbbs.com" in unit
              and "Environment=DIRECTORY_DOCS_DIR=/srv/unleashed_directory/docs" in unit
              and "Environment=DIRECTORY_FIRMWARE_DIR=/srv/unleashed_site/firmware" in unit)

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
        closed_checks(S)
        rate_checks(S)
        skins_checks(S)
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
