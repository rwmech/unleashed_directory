#!/usr/bin/env python3
"""
===========================================================================
 µnleashed BBS directory
 A list of boards that are actually up.
===========================================================================

File:         server.py
Module:       Directory server

Purpose:      Takes heartbeats from BBS boards and keeps a list of the ones
              that are running. Serves that list as a web page and as JSON.

Design:       Standard library only, SQLite for storage, one file. A
              hobbyist should be able to read the whole thing in an
              afternoon and run their own, because the whole point of the
              protocol is that this server is replaceable.

              It never makes outbound connections. A directory that
              connects to whatever host and port a stranger posts to it is
              a port scanner with a public API, so a listing earns its
              place by sustained heartbeats instead of by being probed.

              Anti-spam, in the order it does the work:
                - a listing is not public until it has sustained
                  heartbeats for PENDING_HOURS
                - one automatic listing per address; the rest queue for a
                  human, counted per /64 on IPv6
                - a rate limit on the endpoint
                - a report link, and a moderator

              The token stops somebody taking over an existing listing. It
              is not a spam control and no token scheme could be: tokens
              are free to mint. Addresses are the scarce thing.

Copyright 2026 - Robert Mech
License:      GNU General Public License v3 or later
SPDX-License-Identifier: GPL-3.0-or-later

This program is free software; you can redistribute it and/or modify it
under the terms of the GNU General Public License as published by the
Free Software Foundation; either version 3 of the License, or (at your
option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General
Public License for more details.

You should have received a copy of the GNU General Public License along
with this program. If not, see <https://www.gnu.org/licenses/>.
===========================================================================
"""

import html
import ipaddress
import itertools
import json
import os
import pathlib
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import sitekit                     # noqa: E402
from sitekit import *              # noqa: E402,F401,F403

# --------------------------------------------------------------------------
# Settings. Environment variables win, so the systemd unit is the only place
# a deployment needs to say anything.
# --------------------------------------------------------------------------
DB_PATH       = os.environ.get("DIRECTORY_DB", "directory.db")
BIND_HOST     = os.environ.get("DIRECTORY_HOST", "127.0.0.1")
BIND_PORT     = int(os.environ.get("DIRECTORY_PORT", "8080"))
SITE_URL      = os.environ.get("DIRECTORY_URL", "https://unleashedbbs.net")

# The name and the one line a link preview shows. sitekit reads them from
# its own module for a page's title, so they are handed to it here.
SITE_NAME     = os.environ.get("DIRECTORY_NAME", "µnleashed BBS directory")
SITE_DESC     = ("Community bulletin boards (BBSes) that are up right now, and how "
                 "to join one with a free app. No ads, no tracking, no platform.")
sitekit.SITE_NAME = SITE_NAME
sitekit.SITE_DESC = SITE_DESC

# The one domain this directory answers as. Until the split (2026-09-26) one
# server was three sites chosen by the Host header, the board list, the
# manifesto and the data; the manifesto and the rest of the project's site
# moved to their own server, so this is one site again, with the data at
# /data. Empty is fine: links are relative, and the canonical and preview
# addresses fall back to DIRECTORY_URL.
LIST_DOMAIN   = os.environ.get("DIRECTORY_LIST_DOMAIN", "")

# The project's own site, for the pages this server no longer has. A path
# that is not the directory's and not a guide is sent there with a 301, so
# an old link to /install on this domain still lands, and the menu names it.
# Empty for a directory that is not part of the project: those paths are
# then simply not found.
HOME_URL      = os.environ.get("DIRECTORY_HOME_URL", "").rstrip("/")

# The guides (unleashed_documentation, CC BY-SA 4.0): Markdown in pages/ and
# the captured board screens in shots/, served at /docs/<page>. Optional:
# a directory without them has no Guides entry and no /docs.
DOCS_DIR      = pathlib.Path(os.environ.get(
    "DIRECTORY_DOCS_DIR", str(pathlib.Path(__file__).resolve().parent / "docs")))

PENDING_HOURS = float(os.environ.get("DIRECTORY_PENDING_HOURS", "3"))
# How long a board that has already earned its listing may stay dark and
# still come straight back on to the page. The pending hours are the spam
# stop and they are meant to be paid once, not every time somebody unplugs
# a board to move a desk. Past this it has been gone long enough that the
# address, the owner and the intent are all worth re-establishing, and it
# serves the hours again. Sits inside EXPIRE_DAYS on purpose: gone longer
# than that and there is no row left to relist.
RELIST_DAYS   = float(os.environ.get("DIRECTORY_RELIST_DAYS", "4"))
EXPIRE_DAYS   = float(os.environ.get("DIRECTORY_EXPIRE_DAYS", "7"))
PER_ADDRESS   = int(os.environ.get("DIRECTORY_PER_ADDRESS", "1"))
# The heartbeat rate limit is per BOARD (site 1.3.12): the least time
# between two accepted announces from one board. A board is its listing when
# it presents a token the directory issued, and otherwise the address it
# posted from plus the port it announced, so two boards behind one home
# address, one per port as the go-public guide says, each have their own
# clock. Until 1.3.12 this was per address, and one board's heartbeat got
# the other board's caller-join update refused.
MIN_SECONDS   = int(os.environ.get("DIRECTORY_MIN_SECONDS", "30"))
# And a ceiling per ADDRESS, the abuse stop the per-board clock is not:
# accepted announces from one address in any one minute. Tokens are free,
# so the per-board clock alone lets one address post as many boards as it
# likes. One address can hold PER_ADDRESS + SPARE_ROWS listings (4 as
# shipped) and each board is held to two announces a minute by MIN_SECONDS,
# so 20 is more than twice what one address full of real boards can send,
# and still caps a loop at one post every three seconds. 0 switches it off.
ADDRESS_PER_MINUTE = int(os.environ.get("DIRECTORY_ADDRESS_PER_MINUTE", "20"))
# How many extra entries one address may hold beyond its published one,
# waiting for a human. Small on purpose: it is the stop on a board that has
# forgotten its token, or on somebody posting in a loop.
SPARE_ROWS    = int(os.environ.get("DIRECTORY_SPARE_ROWS", "3"))
BODY_MAX      = 4096
# The board list is a live thing: who is on changes minute to minute, so the
# page reloads itself rather than going stale in a tab somebody left open.
# A meta refresh, not a script, because a reader should not have to run code
# to read a list. The list does carry a few inline lines now, the badge
# filter's (see BADGE_JS), but they only make it quicker to narrow; the list
# is whole and current without them. The refresh is cheap: the page is
# rendered at most once every PAGE_CACHE seconds however many ask for it.
LIST_SECONDS  = int(os.environ.get("DIRECTORY_LIST_REFRESH", "60"))
LIST_REFRESH  = (f'<meta http-equiv="refresh" content="{LIST_SECONDS}">'
                 if LIST_SECONDS > 0 else "")

# A board is counted offline when it has missed this many of its own
# intervals. Three lets a board reboot, or ride out a flaky evening,
# without losing the hours it spent earning its listing.
MISSED_BEATS  = 3

SCHEMA = """
CREATE TABLE IF NOT EXISTS boards (
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
    interests    TEXT NOT NULL DEFAULT '',
    sd           INTEGER,
    closed       INTEGER NOT NULL DEFAULT 0
);
-- Heartbeats received, one row per board per UTC hour, for the last week
-- and a bit. The steady badge is worked out from it: see steady_boards().
CREATE TABLE IF NOT EXISTS beathours (
    board_id INTEGER NOT NULL,
    hour     INTEGER NOT NULL,          -- seconds since the epoch // 3600
    beats    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (board_id, hour)
);
CREATE TABLE IF NOT EXISTS activity (
    board_id INTEGER NOT NULL,
    hour     INTEGER NOT NULL,          -- 0..23, the board's local hour
    beats    INTEGER NOT NULL DEFAULT 0,
    busy     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (board_id, hour)
);
CREATE TABLE IF NOT EXISTS reports (
    id       INTEGER PRIMARY KEY,
    board_id INTEGER NOT NULL,
    at       INTEGER NOT NULL,
    address  TEXT NOT NULL DEFAULT '',
    reason   TEXT NOT NULL DEFAULT ''
);
-- The rate limit's clocks: when each board last had an announce accepted,
-- keyed "b<id>" for a listing and "p<address> <port>" for a post with no
-- token the directory knows; and each address's current minute. Scratch,
-- a few seconds deep, emptied as it goes stale. Until 1.3.12 this was one
-- table, hits, keyed by address alone; setup() drops it.
CREATE TABLE IF NOT EXISTS beatclock (
    key TEXT PRIMARY KEY,
    at  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS addrminute (
    address TEXT PRIMARY KEY,
    start   INTEGER NOT NULL,
    n       INTEGER NOT NULL
);
"""

CLEAN = re.compile(r"[\x00-\x1f\x7f]")


def role_for(host):
    """Which site a request is asking for. One, since the split: the
    directory. Kept as a function so the handler reads as it always did."""
    return "list"


def docs_names():
    """The guides on disk, by page name, sorted."""
    try:
        return sorted(p.stem for p in (DOCS_DIR / "pages").glob("*.md")
                      if PAGE_NAME.match(p.stem))
    except OSError:
        return []


def site_url(target, role, path="/"):
    """A link to one part of this site, or to the project's own site.

    "list" and "data" are this server's pages, "docs" the guides under
    /docs, and "home" the project's site at DIRECTORY_HOME_URL."""
    if target == "home":
        return HOME_URL + path if HOME_URL else path
    if target == "data":
        return "/data" if path == "/" else path
    if target == "docs":
        return "/docs" if path == "/" else "/docs" + path
    return path


# The menu. The board list first, because it is what this site is; then
# what a sysop needs to be on it; then the data, the guides when this
# directory carries them, and the project's own site when there is one.
NAV = (("list",  "/",       "Communities online"),
       ("list",  "/badges", "Badges"),
       ("list",  "/how",    "Get listed"),
       ("list",  "/rules",  "House rules"),
       ("data",  "/",       "Data"),
       ("docs",  "/",       "Guides"),
       ("home",  "/",       "µnleashed BBS"))

# A page that is not in the menu still has a place in it.
NAV_SECTION = {
    "/directory": "/",
}


def nav_items():
    """The menu as this directory serves it: no Guides without guides, and
    no link home without a home."""
    return tuple(n for n in NAV
                 if (n[0] != "docs" or docs_names())
                 and (n[0] != "home" or HOME_URL))


def nav_here(role, here):
    """The menu entry a page belongs to, as the link that entry is served
    as. Every guide belongs to Guides."""
    if here == "/docs" or here.startswith("/docs/"):
        return "/docs"
    return NAV_SECTION.get(here, here)


def nav_html(role, here=""):
    here = nav_here(role, here)
    out = []
    for target, path, label in nav_items():
        href = site_url(target, role, path)
        cls = ' class="here"' if href == here else ""
        out.append('<a' + cls + ' href="' + href + '">' + label + '</a>')
    return "<nav>" + "".join(out) + "</nav>"


def head_html(role, here=""):
    """The top of every page: wordmark and the freedoms beside it, then the
    same menu everywhere. The wordmark goes to the board list."""
    return ('<div class="masthead">'
            + logo_html("/")
            + ticker_html(nav_index(role, here)) + "</div>"
            + nav_html(role, here))


def nav_index(role, here=""):
    """The position in the menu of the section this page belongs to, or 0
    for a page that belongs to none."""
    here = nav_here(role, here)
    for i, (target, path, _label) in enumerate(nav_items()):
        if site_url(target, role, path) == here:
            return i
    return 0


def foot_html(role, extra=""):
    """The bottom of every page: two rows of links, then the colophon.

    No separator text between the links: each link after the first draws
    its own dot (footer .row a::before), so a wrapped row never ends in a
    dangling one."""
    start = "".join(
        f'<a href="{p}">{t}</a>' for p, t in (
            ("/", "Communities online"), ("/badges", "Badges"),
            ("/how", "Get listed"), ("/rules", "House rules")))
    refer = [(site_url("data", role, "/"), "Data"),
             ("/api/boards.json", "JSON"), ("/feed.xml", "RSS")]
    if docs_names():
        # The fix for the thing a first-time caller hits: they click an
        # address and nothing happens.
        refer.append(("/docs/dialing", "Dial links"))
        refer.append(("/docs", "Guides"))
    refer.append(("https://github.com/rwmech/unleashed_directory", "Run your own"))
    if HOME_URL:
        refer.append((HOME_URL + "/", "µnleashed BBS"))
    links = ('<span class="row"><span class="lbl">Directory</span>' + start + "</span>"
             '<span class="row"><span class="lbl">Reference</span>'
             + "".join(f'<a href="{h}">{t}</a>' for h, t in refer) + "</span>")
    parts = [links]
    if extra:
        parts.append(extra)
    colophon = ('<p class="colophon">'
                + (f'<span>Site version {SITE_VERSION}</span>'
                   if SITE_VERSION else "")
                + "<span>&copy; 2026 Robert Mech</span>"
                '<span><a href="https://www.gnu.org/licenses/gpl-3.0.html">'
                "GNU GPL v3 or later</a></span></p>")
    return "<br><br>".join(parts) + colophon




def db():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def setup():
    with db() as con:
        con.executescript(SCHEMA)
        # The per-address rate limit's table, replaced in 1.3.12 by
        # beatclock and addrminute. Nothing in it outlives thirty seconds.
        con.execute("DROP TABLE IF EXISTS hits")
        # Databases made before the feed existed have no public_at column.
        have = {r["name"] for r in con.execute("PRAGMA table_info(boards)")}
        if "public_at" not in have:
            con.execute("ALTER TABLE boards ADD COLUMN public_at INTEGER NOT NULL DEFAULT 0")
            con.execute("UPDATE boards SET public_at=streak_start WHERE state='online'")
        # Databases made before the busy-hours chart have no offset to
        # bucket by. Zero means UTC, which is what they were doing anyway.
        if "tz_offset" not in have:
            con.execute("ALTER TABLE boards ADD COLUMN tz_offset INTEGER NOT NULL DEFAULT 0")
        # The badge fields (site 0.21.0). Added, never rebuilt: the live
        # table has rows in it, and ADD COLUMN leaves every one of them
        # alone. An old board simply has none of these until it sends them,
        # which is also what a board running old firmware looks like.
        # tracked_since is 0 until the board's first heartbeat after this
        # runs, which is when its hourly tally starts; see steady_boards().
        for col, decl in BADGE_COLUMNS:
            if col not in have:
                con.execute(f"ALTER TABLE boards ADD COLUMN {col} {decl}")


# The columns the badges added, as ALTER TABLE wants them. A column added
# here must also be in SCHEMA, so a new database and a migrated one end up
# with the same table; the self-test compares the two, from a database made
# by the 0.20.2 schema, from one made by the 0.21.1 schema and from one made
# by the 1.0.0 schema. interests came in site 0.22.0; a 0.21.x database has
# every column above it. sd, the SD card's size, came in site 1.1.0 and is
# NULL for "not sent", which every row written before it is. closed came in
# site 1.3.10, 1 while the board's sysop has it closed and 0 otherwise, so
# every row written before it reads as open, which is what those boards were:
# a closed board on firmware 1.1.0 does not announce at all. It is not a
# badge, but it is added the same way, so it lives in the same list.
BADGE_COLUMNS = (("system",        "TEXT NOT NULL DEFAULT ''"),
                 ("terminals",     "TEXT NOT NULL DEFAULT ''"),
                 ("guests",        "INTEGER"),
                 ("features",      "TEXT NOT NULL DEFAULT ''"),
                 ("support",       "TEXT NOT NULL DEFAULT ''"),
                 ("tracked_since", "INTEGER NOT NULL DEFAULT 0"),
                 ("interests",     "TEXT NOT NULL DEFAULT ''"),
                 ("sd",            "INTEGER"),
                 ("closed",        "INTEGER NOT NULL DEFAULT 0"))


def tidy(value, limit):
    """One line of somebody else's text, made safe to store and print."""
    if not isinstance(value, str):
        return ""
    return CLEAN.sub(" ", value).strip()[:limit]


def tidy_label(value, limit):
    """A short label somebody else chose, such as the machine a board runs
    on, made safe to put in a badge.

    Stricter than tidy(), which only knows the ASCII controls. This also
    takes out every Unicode control, format and separator character: the
    bidi overrides that would turn the rest of a table row backwards, the
    zero-width characters that make two labels look alike, and the line and
    paragraph separators. A control or a separator becomes a space, because
    it was separating something; a format character is removed, because a
    zero-width one sits inside a word. Runs of whitespace of any kind become
    one space, and a character can carry at most two combining marks,
    because forty characters of stacked accents is a badge that paints over
    the rows above and below it. Then it is cut to limit.
    """
    if not isinstance(value, str):
        return ""
    out, marks = [], 0
    for ch in value:
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Zl", "Zp"):
            ch, marks = " ", 0
        elif cat[0] == "C":
            continue
        elif cat[0] == "M":
            marks += 1
            if marks > 2:
                continue
        else:
            marks = 0
        out.append(ch)
    return " ".join("".join(out).split())[:limit].rstrip()


def pick(value, allowed, most=16, alias=None):
    """The words in a list that this directory knows, once each and in the
    directory's own order.

    Anything that is not a list, and any entry that is not one of the
    allowed words, is ignored rather than refused: a board running newer
    software than this directory must still be listed, and an unknown word
    is exactly what newer software sends. Only the first `most` entries are
    looked at, so a list of a million strings costs nothing.

    With an alias table (the causes and the interests, site 1.1.0), each
    entry is matched after norm_word() and becomes the code it names, so an
    old slug, an interim one and a code in any case all arrive as the code.
    """
    if not isinstance(value, list):
        return []
    if alias is None:
        got = {v.strip().lower() for v in value[:most] if isinstance(v, str)}
    else:
        got = {alias.get(norm_word(v), "") for v in value[:most]}
    return [a for a in allowed if a in got]


def unpick(stored):
    """A list column as a Python list. Stored comma separated, and only
    words from a fixed list ever reach it, so a comma cannot be data."""
    return [w for w in (stored or "").split(",") if w]


def group_of(address):
    """What counts as "the same place" for the per-address limit. A whole
    /64 on IPv6, because a single customer is usually given one and
    counting individual addresses there would mean nothing."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return address
    if ip.version == 6:
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


def public_in(row, now):
    """Seconds until a pending listing goes public, 0 once it is."""
    if row["state"] != "pending":
        return 0
    done = row["streak_start"] + int(PENDING_HOURS * 3600)
    return max(0, done - now)


def settle(con, now):
    """Move listings between states. Called on every announce, which is
    often enough for a list that changes every few minutes. Returns how
    many listings moved, so the page cache can be dropped when, and only
    when, the page would actually look different."""
    before = con.total_changes
    grace = f"(interval_min * 60 * {MISSED_BEATS})"
    con.execute(
        f"UPDATE boards SET state='offline' "
        f"WHERE state='online' AND ? - last_seen > {grace}", (now,))
    # public_at is set once, the first time a board earns its listing, so the
    # feed does not re-announce a board every time it comes back from a nap.
    con.execute(
        "UPDATE boards SET state='online', "
        "public_at=CASE WHEN public_at=0 THEN ? ELSE public_at END "
        "WHERE state='pending' AND ? - streak_start >= ?",
        (now, now, int(PENDING_HOURS * 3600)))
    con.execute(
        "DELETE FROM activity WHERE board_id IN "
        "(SELECT id FROM boards WHERE ? - last_seen > ?)",
        (now, int(EXPIRE_DAYS * 86400)))
    con.execute(
        "DELETE FROM beathours WHERE board_id IN "
        "(SELECT id FROM boards WHERE ? - last_seen > ?)",
        (now, int(EXPIRE_DAYS * 86400)))
    con.execute("DELETE FROM boards WHERE ? - last_seen > ?",
                (now, int(EXPIRE_DAYS * 86400)))
    return con.total_changes - before


# How many samples one board's chart keeps before everything is halved.
# 4032 is four weeks of ten minute beats. Halving rather than dropping gives
# a slow fade, so a board that changes its habits is followed within a few
# weeks instead of being judged for ever on its first month.
ACTIVITY_CAP = int(os.environ.get("DIRECTORY_ACTIVITY_CAP", "4032"))


def sample(con, board_id, busy, tz_offset, now):
    """Fold one heartbeat into the board's hour-of-day chart."""
    hour = int(((now + tz_offset * 60) % 86400) // 3600)
    con.execute(
        "INSERT INTO activity(board_id, hour, beats, busy) VALUES(?,?,1,?) "
        "ON CONFLICT(board_id, hour) DO UPDATE SET beats=beats+1, busy=busy+?",
        (board_id, hour, busy, busy))
    total = con.execute("SELECT SUM(beats) AS n FROM activity WHERE board_id=?",
                        (board_id,)).fetchone()["n"] or 0
    if total > ACTIVITY_CAP:
        con.execute("UPDATE activity SET beats=beats/2, busy=busy/2 WHERE board_id=?",
                    (board_id,))
        con.execute("DELETE FROM activity WHERE board_id=? AND beats=0", (board_id,))


# --------------------------------------------------------------------------
# Steady: a board that answered more than 95% of the heartbeats it was due
# over the last seven days.
#
# The directory has always counted a board's heartbeats, but only as one
# running total, which cannot say anything about last week. So each accepted
# heartbeat also goes into beathours, one row per board per UTC hour, and
# rows older than a week are dropped as new ones arrive: 169 small rows a
# board at most.
#
# "Due" is the board's own promise. It says how often it will call
# (interval, in minutes), so over the window it owes window / interval
# heartbeats. "Answered" is what arrived, counted per hour and capped at an
# hour's due (rounded up), so a burst of extra heartbeats (a board pushes one
# early when somebody logs on) cannot paper over an hour it was silent. A cap
# of one more than due looked kinder and let a board be silent one hour in
# seven and still be steady: the self-test's burst check found that.
# The window is the last 168 hourly buckets, the current partial hour
# included, and the due count covers exactly the time those buckets span.
#
# A board earns it only after the directory has watched it for the whole
# week, from the first heartbeat after its tally started (tracked_since):
# a week it was not watched for is not a week it was steady in. That
# includes every board already listed when this arrived, which gets its
# first chance at the badge seven days after the update.
# --------------------------------------------------------------------------
STEADY_DAYS  = 7
STEADY_HOURS = STEADY_DAYS * 24
STEADY_SHARE = 0.95


def tally(con, board_id, now):
    """Count one accepted heartbeat into the board's hourly record, and let
    go of anything older than the steady window."""
    hour = now // 3600
    con.execute(
        "INSERT INTO beathours(board_id, hour, beats) VALUES(?,?,1) "
        "ON CONFLICT(board_id, hour) DO UPDATE SET beats=beats+1",
        (board_id, hour))
    con.execute("DELETE FROM beathours WHERE board_id=? AND hour<?",
                (board_id, hour - STEADY_HOURS))


def steady_share(beats, interval_min, now):
    """What share of its due heartbeats a board answered in the window, from
    {hour: beats}. See the note above for how due and answered are counted."""
    first = now // 3600 - STEADY_HOURS + 1
    span = now - first * 3600
    every = max(1, int(interval_min or 10)) * 60
    due = span / every
    cap = -(-3600 // every)
    heard = sum(min(n, cap) for h, n in beats.items() if h >= first)
    return heard / due if due > 0 else 0.0


def steady_boards(con, rows, now):
    """The ids of the boards in rows that have earned the steady badge."""
    first = now // 3600 - STEADY_HOURS + 1
    beats = {}
    for r in con.execute("SELECT board_id, hour, beats FROM beathours WHERE hour>=?",
                         (first,)):
        beats.setdefault(r["board_id"], {})[r["hour"]] = r["beats"]
    out = set()
    for r in rows:
        since = r["tracked_since"]
        if not since or now - since < STEADY_DAYS * 86400:
            continue
        if steady_share(beats.get(r["id"], {}), r["interval_min"], now) > STEADY_SHARE:
            out.add(r["id"])
    return out


# Enough of a shape to be worth drawing, and enough to stop calling it
# provisional. The first is deliberately low: a directory that shows a board
# nothing for a whole day is a directory nobody believes is working. The
# second is a full day of ten minute beats.
CHART_MIN  = int(os.environ.get("DIRECTORY_CHART_MIN", "18"))
CHART_FIRM = int(os.environ.get("DIRECTORY_CHART_FIRM", "144"))


def hours_for(con, board_id):
    """(24 hourly means, is it settled yet), or None when there is too little.

    A chart drawn from one afternoon is a rumour rather than a forecast, so
    it says so until it has a day behind it. It is still shown, because
    watching it fill in is the only way a sysop can tell the thing works.
    """
    rows = con.execute(
        "SELECT hour, beats, busy FROM activity WHERE board_id=?", (board_id,)).fetchall()
    if not rows:
        return None
    seen = sum(r["beats"] for r in rows)
    if seen < CHART_MIN:
        return None
    out = [0.0] * 24
    for r in rows:
        if r["beats"]:
            out[r["hour"]] = r["busy"] / r["beats"]
    if not any(out):
        return None
    return out, seen >= CHART_FIRM, seen


def spark(hours):
    """The day at a glance, as a small drawing.

    This was block characters, which is the version everybody sees because
    the full chart is behind a click. Half a block is not a shape anybody
    reads as a number, and the ramp lands differently in every font.
    """
    top = max(hours)
    if top <= 0:
        return ""
    W, H = 124.0, 18.0
    slot = W / 24.0
    bar = slot * 0.62
    peak = hours.index(top)
    parts = [f'<svg class="spark" viewBox="0 0 {W:.0f} {H:.0f}" '
             f'role="img" aria-label="Busy hours">']
    parts.append(f'<line class="base" x1="0" y1="{H - 1:.1f}" x2="{W:.0f}" y2="{H - 1:.1f}"/>')
    for h, v in enumerate(hours):
        if v <= 0:
            continue
        height = max(1.5, (H - 2) * (v / top))
        x = slot * h + (slot - bar) / 2.0
        parts.append(f'<rect class="{"b peak" if h == peak else "b"}" '
                     f'x="{x:.1f}" y="{H - 1 - height:.1f}" '
                     f'width="{bar:.1f}" height="{height:.1f}"/>')
    parts.append("</svg>")
    return "".join(parts)


def busiest(hours):
    """The best two hour window, as a human would say it."""
    top, at = -1.0, 0
    for h in range(24):
        pair = hours[h] + hours[(h + 1) % 24]
        if pair > top:
            top, at = pair, h
    if top <= 0:
        return ""
    return f"{at:02d}:00-{(at + 2) % 24:02d}:00"


PAGES_DIR = pathlib.Path(__file__).resolve().parent / "pages"


# --------------------------------------------------------------------------
# The badge filter and the badge search: the third script on the site, on
# two pages, the board list and /badges (site 0.22.0, Rob: "Slick selection
# and searching"). Written here, inline, and pinned by the suite to exactly
# this text.
#
# Both pages are whole without it. The board list's filter is a <details>
# holding a GET form, so with no script the pane still opens and "Show
# boards" asks the server for the filtered list; /badges shows every row.
# What the script adds is speed, and one control that only it can drive:
#
#   - Any input[data-find] narrows the [data-k] items inside the element its
#     data-find names, as you type, by name and slug (every word typed has
#     to appear), hides a [data-g] group left with nothing in it, opens a
#     folded filter row that has a match (0.22.2), and says
#     how many are left in the element data-count names. The search boxes
#     are marked data-js and hidden in the markup, because without the
#     script they could not do anything; the script shows them.
#   - On the board list, a chip filters the rows the moment it is pressed:
#     every row is on the page, carrying its badges in data-b, and the ones
#     that do not pass get the hidden attribute. The line under the button
#     is rewritten, the count on the button too, and the URL follows with
#     history.replaceState, so what is on the screen is always a link that
#     can be shared. "#filter" is added while the pane is open, so the
#     list's own refresh, which reloads that URL, opens it again rather than
#     snapping it shut under somebody who is still choosing.
#   - Only on /directory (site 1.2.8). The front page's form is marked
#     data-go and left alone, so its chips go to the full list. On
#     /directory the name search (q) is part of the form; the URL keeps the
#     search the page was served for, and a changed search is let through
#     to the server, which is the only thing that can answer it. When a
#     search found nothing there is no table, and the chips go to the
#     server too.
#
# It reads the page and nothing else, writes with textContent and the
# hidden attribute only, sends nothing anywhere, stores nothing and never
# navigates. The suite fails it on innerHTML, fetch, XMLHttpRequest,
# sendBeacon, WebSocket, eval, cookies, storage or navigation.
# --------------------------------------------------------------------------
BADGE_JS = (
    "<script>(function(){"
    "var d=document;"
    "function all(s,e){return Array.prototype.slice.call((e||d).querySelectorAll(s));}"
    "function go(){"
    "all('[data-js]').forEach(function(e){e.hidden=false;});"
    "all('input[data-find]').forEach(function(q){"
    "var box=d.querySelector(q.getAttribute('data-find')),"
    "out=d.getElementById(q.getAttribute('data-count')),"
    "items=all('[data-k]',box),noun=' '+q.getAttribute('data-noun');"
    "function find(){"
    "var w=q.value.toLowerCase().split(' ').filter(Boolean),n=0;"
    "items.forEach(function(e){var k=e.getAttribute('data-k'),"
    "hit=w.every(function(x){return k.indexOf(x)>=0;});e.hidden=!hit;if(hit)n++;});"
    "all('[data-g]',box).forEach(function(g){"
    "g.hidden=!g.querySelector('[data-k]:not([hidden])');"
    "if(w.length&&!g.hidden&&g.tagName==='DETAILS')g.open=true;});"
    "out.textContent=!w.length?items.length+noun:"
    "n?n+' of '+items.length+noun:'No badge matches that.';}"
    "q.addEventListener('input',find);find();});"
    "var f=d.getElementById('fform');if(!f||f.hasAttribute('data-go'))return;"
    "var det=d.getElementById('filter'),rows=all('tr[data-b]'),"
    "tab=d.getElementById('boards'),none=d.getElementById('fnone'),"
    "line=d.getElementById('factive'),qi=f.elements.q;if(!tab)return;"
    "function part(k){return line.querySelector('[data-f='+k+']');}"
    "function apply(){"
    "var sel=all('input[name=b]:checked',f),any=f.elements.m.value==='any',n=0;"
    "rows.forEach(function(r){var b=' '+r.getAttribute('data-b')+' ',"
    "has=function(c){return b.indexOf(' '+c.value+' ')>=0;},"
    "ok=!sel.length||(any?sel.some(has):sel.every(has));r.hidden=!ok;if(ok)n++;});"
    "tab.hidden=!n;none.hidden=!!n;line.hidden=!sel.length;"
    "none.textContent='No board with '+(any?'any':'all')+' of those yet.';"
    "part('n').textContent=n+' of '+rows.length+' board'+(rows.length===1?'':'s');"
    "part('m').textContent=(any?'any':'all')+' of';"
    "part('l').textContent=sel.map(function(c){return c.getAttribute('data-n');}).join(', ');"
    "d.getElementById('fcount').textContent=sel.length||'';"
    "var q=sel.map(function(c){return 'b='+encodeURIComponent(c.value);});"
    "if(any&&q.length)q.push('m=any');"
    "if(qi&&qi.defaultValue)q.push('q='+encodeURIComponent(qi.defaultValue));"
    "history.replaceState(null,'',location.pathname+(q.length?'?'+q.join('&'):'')"
    "+(det.open?'#filter':''));}"
    "f.addEventListener('change',apply);"
    "f.addEventListener('submit',function(e){"
    "if(qi&&qi.value!==qi.defaultValue)return;e.preventDefault();det.open=false;});"
    "det.addEventListener('toggle',apply);"
    "all('[data-clear]').forEach(function(a){a.addEventListener('click',function(e){"
    "e.preventDefault();all('input[name=b]',f).forEach(function(c){c.checked=false;});"
    "apply();});});"
    "if(location.hash==='#filter')det.open=true;apply();}"
    "if(d.readyState==='loading')d.addEventListener('DOMContentLoaded',go);else go();"
    "})();</script>")


def _md_whole(text, role, here):
    """A Markdown page's text as a whole page, header and footer included."""
    title, desc = md_meta(text)
    body = "<article>" + md_render(text) + "</article>"
    # The drawings' stylesheet goes in once, and only on a page that has a
    # drawing, the way it always has.
    if "::: art" in text:
        body = ART_CSS + body
    return PAGE.format(refresh="", head="", title=html.escape(title),
                       desc=html.escape(desc, quote=True),
                       body=head_html(role, here) + body,
                       footer=foot_html(role))


def md_page(name, role="list"):
    """One of this server's own pages/ files, as a whole page. None when
    there is no such file."""
    f = PAGES_DIR / (name + ".md")
    if not f.is_file():
        return None
    return _md_whole(f.read_text(encoding="utf-8"), role, "/" + name)


def docs_page(name, role="list"):
    """One guide, from DOCS_DIR/pages, as a whole page, or None."""
    if not PAGE_NAME.match(name or ""):
        return None
    f = DOCS_DIR / "pages" / (name + ".md")
    if not f.is_file():
        return None
    return _md_whole(f.read_text(encoding="utf-8"), role, "/docs/" + name)


def docs_index(role="list"):
    """/docs: the guides' own index page when they carry one, else a list of
    them by title. None when there are no guides here at all."""
    names = docs_names()
    if not names:
        return None
    if "index" in names:
        return docs_page("index", role)
    items = []
    for n in names:
        try:
            text = (DOCS_DIR / "pages" / (n + ".md")).read_text(encoding="utf-8")
        except OSError:
            continue
        head = re.search(r"^# (.+)$", text, re.M)
        items.append(f'<li><a href="/docs/{n}">'
                     f'{md_inline(head.group(1).strip() if head else n)}</a></li>')
    return simple_page(f"Guides - {SITE_NAME}",
                       "<h1>Guides</h1><article><ul>" + "".join(items)
                       + "</ul></article>", role, "/docs")

# The stock display skins on /skins (site 1.3.17): the two zips a sysop
# downloads, skins.zip laid out for the card and skins-upload.zip as the
# pairs the board's Skins file area takes, and a picture of each skin lit.
# Since the split (2026-09-26) they travel with the skins guide, in the
# guides' checkout (unleashed_documentation, skins/), which setup.sh
# installs as DOCS_DIR/skins. Served at /skins/<file> with the same name
# check as everything else, and only these two types.
SKINS_DIR = DOCS_DIR / "skins"
SKINS_TYPES = {".png": "image/png", ".zip": "application/zip"}


def skins_file(name):
    """One file from the guides' skins/, a preview or a zip, or None."""
    return static_file(name, SKINS_DIR, SKINS_TYPES)


def skin_gallery_html(lines):
    """The ::: skins block on /skins: one "file.png | caption" a line, each a
    picture of a stock skin as the board draws it, 480 by 320. A line whose
    file is not in the guides' skins/ renders nothing, the way a card's picture
    does, so the page is whole with none of them."""
    cells = []
    for raw in lines:
        name, _, cap = raw.partition("|")
        name, cap = name.strip(), cap.strip()
        if not name or not cap or not STATIC_OK.match(name):
            continue
        if pathlib.Path(name).suffix.lower() != ".png" or not (SKINS_DIR / name).is_file():
            continue
        alt = re.sub(r"[`*]", "", cap)
        cells.append(f'<figure><img src="/skins/{html.escape(name)}" width="480" '
                     f'height="320" alt="{html.escape(alt, quote=True)}" loading="lazy">'
                     f"<figcaption>{md_inline(cap)}</figcaption></figure>")
    if not cells:
        return ""
    return '<div class="wide gallery skins">' + "".join(cells) + "</div>"


BLOCKS["skins"] = skin_gallery_html


def rate_keys(row, address, port):
    """The clocks an announce is timed on. A post carrying a token the
    directory knows is that board, wherever it posts from. Anything else is
    the address and the port it announced, which tells apart two boards
    behind one address and still holds back a board that has lost its
    token and posts as a stranger every time."""
    return [f"b{row['id']}"] if row else [f"p{address} {port}"]


def rate_refused(con, address, keys, now):
    """Why this announce is refused, or None. Only reads: a refusal moves
    no clock, so a board that is told to slow down and then does is not
    held back a second time for having asked. The first version, from the
    first commit, wrote the clock on every post, refused or not, which
    added nothing a limit needs (a post in a loop is refused either way,
    and the per-address minute is what stops a loop now) and turned one
    early retry into a refusal for the next one too."""
    con.execute("DELETE FROM beatclock WHERE at <= ?", (now - MIN_SECONDS,))
    con.execute("DELETE FROM addrminute WHERE start <= ?", (now - 60,))
    if ADDRESS_PER_MINUTE > 0:
        win = con.execute("SELECT n FROM addrminute WHERE address=?",
                          (address,)).fetchone()
        if win and win["n"] >= ADDRESS_PER_MINUTE:
            return "too many announces from this address"
    marks = ",".join("?" for _ in keys)
    if con.execute(f"SELECT 1 FROM beatclock WHERE key IN ({marks}) AND at > ?",
                   keys + [now - MIN_SECONDS]).fetchone():
        return "slow down"
    return None


def rate_record(con, address, keys, now):
    """An announce was accepted: start its board's clock and count it
    against its address's minute."""
    for key in keys:
        con.execute("REPLACE INTO beatclock(key, at) VALUES(?, ?)", (key, now))
    con.execute(
        "INSERT INTO addrminute(address, start, n) VALUES(?, ?, 1) "
        "ON CONFLICT(address) DO UPDATE SET n=n+1", (address, now))


def rate_record_board(con, board_id, now):
    """A new listing's clock, started by the post that made it."""
    con.execute("REPLACE INTO beatclock(key, at) VALUES(?, ?)", (f"b{board_id}", now))


# --------------------------------------------------------------------------
# The announce endpoint
# --------------------------------------------------------------------------
def announce(payload, address):
    """One heartbeat. Returns (status, body dict, extra headers)."""
    now = int(time.time())
    name = tidy(payload.get("name"), 40)
    if not name:
        return 400, {"error": "a board needs a name"}, {}

    port = payload.get("port", 6400)
    if not isinstance(port, int) or not 1 <= port <= 65535:
        return 400, {"error": "port out of range"}, {}

    token    = tidy(payload.get("token"), 64)
    group    = group_of(address)
    interval = payload.get("interval", 10)
    if not isinstance(interval, int) or not 1 <= interval <= 1440:
        interval = 10

    fields = {
        "name":        name,
        "owner":       tidy(payload.get("owner"), 40),
        "description": tidy(payload.get("description"), 120),
        # Both are shown in a badge since site 1.0.0 ("unleashed 1.0.0"), so
        # they get the badge's cleaning, the same as system does.
        "software":    tidy_label(payload.get("software"), 20),
        "version":     tidy_label(payload.get("version"), 20),
        "host":        tidy(payload.get("host"), 80),
        "address":     address,
        "group_key":   group,
        "port":        port,
        "nodes":       int(payload.get("nodes") or 0),
        "busy":        int(payload.get("busy") or 0),
        "uptime":      int(payload.get("uptime") or 0),
        "interval_min": interval,
    }
    # Minutes east of UTC, so the busy-hours chart can be drawn in the hours
    # this board's own callers keep rather than in UTC. Clamped to the range
    # real timezones occupy, and absent on boards running older firmware.
    tz = payload.get("tz")
    tz = int(tz) if isinstance(tz, int) and -720 <= tz <= 840 else 0
    fields["tz_offset"] = tz

    # Activity is optional and only there when the sysop turned it on.
    for key in ("calls24", "minutes24"):
        value = payload.get(key)
        fields[key] = int(value) if isinstance(value, int) else None

    # The badge fields, all optional and all absent from older boards.
    # Every heartbeat replaces them, so a board that stops sending one loses
    # its badge: features in particular are what is running now, not what
    # ran once. Junk is dropped rather than refused, for the same reason an
    # unknown word in a list is: the listing matters more than the badge.
    # guests has to be a real JSON true or false; "yes" is not true.
    fields["system"]    = tidy_label(payload.get("system"), SYSTEM_MAX)
    fields["terminals"] = ",".join(pick(payload.get("terminals"), TERMINALS))
    guests = payload.get("guests")
    fields["guests"]    = int(guests) if isinstance(guests, bool) else None
    fields["features"]  = ",".join(pick(payload.get("features"), FEATURES))
    # The SD card's size in GB (site 1.1.0): a whole number from 1 to
    # SD_MAX, or nothing. A JSON true is an int in Python and is not a size.
    sd = payload.get("sd")
    fields["sd"] = (sd if isinstance(sd, int) and not isinstance(sd, bool)
                    and 1 <= sd <= SD_MAX else None)
    # Closed by its sysop, "Stop taking calls" (site 1.3.10, firmware 1.1.1):
    # only a JSON true closes a board. Absent, false, "yes", 1 or anything
    # else is open, because a word that might mean closed must not take a
    # board's invitation off the page, and it never costs the heartbeat.
    fields["closed"] = 1 if payload.get("closed") is True else 0
    # The causes and the interests, as codes (site 1.1.0): an old slug or
    # an interim one is read as the code it became, in any case. Left alone,
    # not written empty, when badges.json could not be read at start.
    if BADGE_CODES_OK:
        fields["support"] = ",".join(pick(payload.get("support"), SUPPORT_CODES,
                                          alias=SUPPORT_ALIAS))
        # What the sysop is into (site 0.22.0), exactly as support: codes
        # from the published list, anything else ignored, the first 16
        # read. A code that moved from support to the interests (ham,
        # 0.22.2) is still taken from the support list, and filed here.
        moved = set(pick(payload.get("support"), SUPPORT_MOVED, alias=INTEREST_ALIAS))
        got = set(pick(payload.get("interests"), INTEREST_CODES,
                       alias=INTEREST_ALIAS)) | moved
        fields["interests"] = ",".join(s for s in INTEREST_CODES if s in got)

    with db() as con:
        # Which board this is decides which clock it is timed on, so the
        # token is looked up before the rate limit. Only its id: the row
        # itself is read after settle(), which may have just moved it, and
        # a row read before would write its old state back.
        known = None
        if token:
            known = con.execute("SELECT id FROM boards WHERE token=?", (token,)).fetchone()
        keys = rate_keys(known, address, port)
        why = rate_refused(con, address, keys, now)
        if why:
            return 429, {"error": why}, {}
        rate_record(con, address, keys, now)
        if settle(con, now):
            _cache.clear()                             # somebody came or went

        row = None
        if known:
            row = con.execute("SELECT * FROM boards WHERE id=?", (known["id"],)).fetchone()

        if row:                                        # a board we already know
            sets = ", ".join(f"{k}=?" for k in fields)
            args = list(fields.values())
            state = row["state"]
            streak = row["streak_start"]
            if state == "offline":                     # back after a gap
                # A listing only ever reaches 'offline' from 'online', and
                # 'online' is only reachable by serving the pending hours, so
                # this board has already paid. Sending it round again as
                # 'pending' took it straight off the public page the moment it
                # came back, because the page lists 'online' and 'offline' and
                # not 'pending': an hour of downtime cost three hours of
                # invisibility, and every sysop who reboots paid it. The
                # protocol already promised it would not work this way.
                if now - row["last_seen"] <= RELIST_DAYS * 86400:
                    state = "online"                   # streak untouched
                else:
                    state, streak = "pending", now     # dark too long, serve it again
            elif state == "queued":
                # Whatever was in the way may be long gone. Re-ask on every
                # heartbeat rather than leaving it stuck for ever.
                others = con.execute(
                    "SELECT COUNT(*) AS n FROM boards WHERE group_key=? AND id<>? "
                    "AND state IN ('pending','online')",
                    (row["group_key"], row["id"])).fetchone()["n"]
                if others < PER_ADDRESS:
                    state, streak = "pending", now
            con.execute(
                f"UPDATE boards SET {sets}, last_seen=?, beats=beats+1, "
                f"state=?, streak_start=?, "
                f"public_at=CASE WHEN public_at=0 AND ?='online' THEN ? "
                f"ELSE public_at END, "
                f"tracked_since=CASE WHEN tracked_since=0 THEN ? "
                f"ELSE tracked_since END WHERE id=?",
                args + [now, state, streak, state, now, now, row["id"]])
            sample(con, row["id"], fields.get("busy") or 0, tz, now)
            tally(con, row["id"], now)
            fresh = con.execute("SELECT * FROM boards WHERE id=?", (row["id"],)).fetchone()
            if fresh["state"] != row["state"] or fresh["closed"] != row["closed"]:
                _cache.clear()                         # the page says something new now
            return 200, listing(fresh, now), {"X-Listing-Token": token}

        # A board we have not met before, or one that has forgotten its own
        # token. It still gets an entry of its own rather than taking over
        # the one this address already holds: two unrelated boards can share
        # a public address, which is what CGNAT does to whole towns, and
        # "same address" is nowhere near "same board".
        #
        # What is capped is how many entries an address may accumulate. A
        # board that keeps forgetting its token, or anybody with curl and a
        # loop, would otherwise mint a fresh listing on every post for ever.
        # The cap is the thing that was missing: PER_ADDRESS only ever chose
        # what state a new row got, and then inserted it regardless.
        # At the cap, make room by dropping the deadest entry this address
        # holds rather than refusing outright.
        #
        # Refusing was wrong and I shipped it: a board that legitimately
        # loses its token, which is what a reflash used to do, could then
        # never list again, and it was told "too often, will settle" while
        # settling was the one thing that could not happen.
        #
        # Only an entry that has stopped beating is evicted. One that is
        # still alive is somebody's board, whoever they are, and a stranger
        # arriving from the same address must never be able to push it out.
        held = con.execute(
            "SELECT * FROM boards WHERE group_key=? ORDER BY last_seen ASC",
            (group,)).fetchall()
        if len(held) >= PER_ADDRESS + SPARE_ROWS:
            stalest = held[0]
            gone = now - stalest["last_seen"] > stalest["interval_min"] * 60 * MISSED_BEATS
            if not gone:
                # Everything this address holds is still talking, so this is
                # either a lot of real boards or somebody being a nuisance.
                return 429, {"error": "too many listings from this address"}, {}
            con.execute("DELETE FROM activity WHERE board_id=?", (stalest["id"],))
            con.execute("DELETE FROM beathours WHERE board_id=?", (stalest["id"],))
            con.execute("DELETE FROM boards WHERE id=?", (stalest["id"],))
            held = held[1:]
            _cache.clear()

        # Only entries that are actually alive hold a published slot. A
        # listing that has gone quiet should not keep a returning board out.
        live = 0
        for other in held:
            if other["state"] not in ("pending", "online"):
                continue
            if now - other["last_seen"] > other["interval_min"] * 60 * MISSED_BEATS:
                continue                      # published, but not answering
            live += 1
        state = "pending" if live < PER_ADDRESS else "queued"
        token = secrets.token_hex(16)
        cols  = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        con.execute(
            f"INSERT INTO boards(token, {cols}, state, first_seen, last_seen, "
            f"streak_start, beats, tracked_since) VALUES(?, {marks}, ?, ?, ?, ?, 1, ?)",
            [token] + list(fields.values()) + [state, now, now, now, now])
        fresh = con.execute("SELECT * FROM boards WHERE token=?", (token,)).fetchone()
        # Its clock under its listing too, so the first heartbeat carrying
        # the token it was just given is timed from this one.
        rate_record_board(con, fresh["id"], now)
        sample(con, fresh["id"], fields.get("busy") or 0, tz, now)
        tally(con, fresh["id"], now)
        _cache.clear()                                 # a board we had not met before
        return 200, listing(fresh, now), {"X-Listing-Token": token}


def listing(row, now):
    """What a board is told about itself."""
    return {
        "state":     row["state"],
        "public_in": public_in(row, now),
        "seen":      row["address"],
        "name":      row["name"],
        "beats":     row["beats"],
        "token":     row["token"],
    }
AVATAR_URL = ((f"https://{LIST_DOMAIN}" if LIST_DOMAIN else SITE_URL).rstrip("/")
              + "/avatar.png")
PAGE = (PAGE.replace("@AVATAR_URL@", html.escape(AVATAR_URL, quote=True))
            .replace("@FEED_URL@", "/feed.xml"))
OG_CARD_URL = ((f"https://{LIST_DOMAIN}" if LIST_DOMAIN else SITE_URL).rstrip("/")
               + "/og-card.png")
OG_CARD_ALT = ("The \u00b5nleashed wordmark and the words 'Your own online "
               "community, on a device that fits in your hand', beside a "
               "drawing of the board.")
PAGE = (PAGE.replace("@OG_CARD_URL@", html.escape(OG_CARD_URL, quote=True))
            .replace("@OG_CARD_ALT@", html.escape(OG_CARD_ALT, quote=True))
            # The site's name above a shared link's title (site 1.3.8), with
            # its micro sign. PAGE is still a format string here, so any
            # brace a DIRECTORY_NAME carries is doubled.
            .replace("@SITE_NAME@", html.escape(SITE_NAME, quote=True)
                     .replace("{", "{{").replace("}", "}}")))

# What a shared link to these pages says about itself. None keeps the
# page's own description (the board list carries its live figures).
OG_PAGES = {
    "/": ("Communities running right now", None),
    "/directory": ("Communities running right now", None),
}


def og_fill(body, path):
    """A page's own link preview title and description, when it has one."""
    got = OG_PAGES.get(path)
    if not got:
        return body
    title, desc = got
    body = _OG_TITLE.sub(lambda m: '<meta property="og:title" content="'
                         + html.escape(title, quote=True) + '">', body, count=1)
    if desc:
        body = _OG_DESC.sub(lambda m: '<meta property="og:description" content="'
                            + html.escape(desc, quote=True) + '">', body, count=1)
    return body


def day_chart_svg(hours, firm):
    """The day as a real bar chart.

    Drawn rather than typed: block characters are a terminal affectation on
    a web page, they land differently in every font, and half of one is not
    a shape anybody reads as a number. Still no JavaScript, and still
    scales to a phone, because an SVG with a viewBox does that for free.

    THE VIEWBOX IS SIZED TO THE COLUMN IT LIVES IN, and that is the whole
    reason this was rewritten. The chart sits in the Board cell, which is
    about 412px wide on a desktop and the full card width on a phone. A 720
    unit viewBox in a 412px box scales by 0.57, so an 11px label rendered at
    **6.3px** and the whole chart was 110px tall: measured, not guessed, and
    Rob's verdict on the expanded view was "I cant read any times". On a
    phone it was worse, 2.2px.

    So the viewBox is 380 wide, which lands near 1:1 in the space there
    actually is, and 300 tall, which is where the legibility comes from: the
    chart is three times the height it was and the labels are twice the
    size. Anything typed in here is in viewBox units, so a size set here is
    very nearly a size in pixels, which is the point of choosing 380.
    """
    top = max(hours)
    if top <= 0:
        return ""
    W, H = 380.0, 300.0          # viewBox units, sized to the column
    # left holds a four character y label at 13 units; bottom holds the hour
    # labels and the note under them.
    left, bottom, pad = 40.0, 44.0, 8.0
    plot_w = W - left - pad
    plot_h = H - bottom - pad
    slot = plot_w / 24.0
    bar = slot * 0.7

    parts = [f'<svg class="hours" viewBox="0 0 {W:.0f} {H:.0f}" '
             f'role="img" aria-label="Callers by hour of the day" '
             f'preserveAspectRatio="xMidYMid meet">']

    base = pad + plot_h

    # A faint upright at every labelled hour, so a bar can be traced down to
    # a time rather than counted across from the end.
    for h in range(0, 24, 3):
        x = left + slot * h
        parts.append(f'<line class="tick" x1="{x:.1f}" y1="{pad:.1f}" '
                     f'x2="{x:.1f}" y2="{base:.1f}"/>')

    # Two guide lines and their labels, plus the zero at the foot so the
    # scale has a bottom as well as a top. A count of callers is a count:
    # "8.0" is a decimal where there cannot be one, so a whole number prints
    # whole and only a fraction gets a decimal place.
    def ylabel(v):
        return f"{v:.0f}" if abs(v - round(v)) < 0.05 else f"{v:.1f}"

    for frac in (1.0, 0.5):
        y = pad + plot_h * (1.0 - frac)
        parts.append(f'<line class="grid" x1="{left:.1f}" y1="{y:.1f}" '
                     f'x2="{W - pad:.1f}" y2="{y:.1f}"/>')
        parts.append(f'<text class="ylab" x="{left - 6:.1f}" y="{y + 5:.1f}" '
                     f'text-anchor="end">{ylabel(top * frac)}</text>')
    parts.append(f'<text class="ylab" x="{left - 6:.1f}" y="{base + 5:.1f}" '
                 f'text-anchor="end">0</text>')

    peak = hours.index(top)
    for h in range(24):
        v = hours[h]
        if v <= 0:
            continue
        height = max(2.0, plot_h * (v / top))
        x = left + slot * h + (slot - bar) / 2.0
        y = pad + plot_h - height
        cls = "bar peak" if h == peak else "bar"
        parts.append(f'<rect class="{cls}" x="{x:.1f}" y="{y:.1f}" '
                     f'width="{bar:.1f}" height="{height:.1f}" rx="2">'
                     f'<title>{h:02d}:00 - {v:.1f} callers</title></rect>')

    parts.append(f'<line class="axis" x1="{left:.1f}" y1="{base:.1f}" '
                 f'x2="{W - pad:.1f}" y2="{base:.1f}"/>')
    for h in range(0, 24, 3):
        x = left + slot * h + slot / 2.0
        parts.append(f'<text class="xlab" x="{x:.1f}" y="{base + 18:.1f}" '
                     f'text-anchor="middle">{h:02d}</text>')

    note = ("local time at the board" if firm
            else "local time at the board, still filling in")
    parts.append(f'<text class="foot" x="{W - pad:.1f}" y="{H - 5:.1f}" '
                 f'text-anchor="end">{note}</text>')
    parts.append("</svg>")
    return "".join(parts)


def chart_html(info):
    """A sparkline you can read in the table, and the whole day on a click."""
    if not info:
        return ""
    hours, firm, seen = info
    when = busiest(hours)
    return ("<details class='chart'>"
            f"<summary>{spark(hours)}"
            f"<span class='when'>busiest {html.escape(when)}"
            f"{'' if firm else ' so far'}</span></summary>"
            + day_chart_svg(hours, firm)
            + "<span class='note'>Average callers on, by hour, in this "
            "board's local time. Built from the counts it already publishes; "
            "nothing about any individual caller is collected."
            + ("" if firm else
               f" Still filling in: {seen} readings so far, so treat the "
               "shape as provisional.")
            + "</span></details>")


# --------------------------------------------------------------------------
# Badges: the small marks under a board's name.
#
# Some are sent by the board (what it runs on, what it speaks, whether
# guests may look round, what is running, what the sysop supports) and the
# rest are worked out here from the directory's own record (new, steady,
# how long it has been listed). /badges is the legend and is built from
# these same tables, so the key and the list cannot disagree.
#
# Every badge carries its meaning three ways: a tooltip drawn by CSS from
# data-tip, which a mouse gets on hover and a phone or a keyboard gets on
# focus (hence tabindex); an aria-label, which is what a screen reader
# reads; and the legend page. There is deliberately no title attribute: a
# title draws a second tooltip, the browser's own, on top of this one on a
# desktop, and shows nothing at all on a phone, which is the case it would
# be there for.
# --------------------------------------------------------------------------
SYSTEM_MAX = 40
TERMINALS  = ("ansi", "utf8", "petscii", "ascii", "vt100")
FEATURES   = ("chat", "forums", "files", "mail", "doors", "camera")
NEW_DAYS   = 7
# The SD card's size, in GB, as the board sends it (site 1.1.0, firmware
# 1.1.0): a whole number, already rounded by the board up to the size
# printed on the card, so a "32 GB" card that reports 29.7 arrives as 32.
# Anything outside 1 to SD_MAX is ignored rather than refused.
SD_MAX     = 4096

# The small badges, in the order they appear: key, letters, colour class,
# name, and what it means, which the tooltip says after the name. The first
# nine are sent by the board and the last two are worked out here. The SD
# card's letters here are what the legend and the filter show; on a board's
# row the badge carries the size as well, "SD32". The camera (site 1.2.8,
# Rob: "This BBS can take pictures") has no letters: it is a drawing,
# CAMERA_SVG, in the features' blue, and its tooltip is Rob's sentence,
# from LETTER_TIPS, rather than the name and the meaning run together.
LETTER_BADGES = (
    ("petscii", "P",  "term",   "PETSCII",
     "a Commodore 64 or 128 gets colour and graphics here, not just text."),
    ("guests",  "G",  "guest",  "Guests welcome",
     "you can look around without making an account."),
    ("chat",    "C",  "feat",   "Chat",   "a live chat room, running now."),
    ("forums",  "F",  "feat",   "Forums", "message boards, running now."),
    ("files",   "Fi", "feat",   "Files",  "file areas to download from, running now."),
    ("mail",    "M",  "feat",   "Mail",   "private mail between callers, running now."),
    ("doors",   "D",  "feat",   "Doors",  "games and programs to run, running now."),
    ("camera",  "",   "feat",   "Camera",
     "this BBS can take pictures. A caller takes a snapshot from their "
     "terminal and downloads it a few seconds later. Running now."),
    ("sd",     "SD", "feat",   "SD card",
     "an SD card is in use on the board. On a board's row the badge carries "
     "the card's size in GB, as printed on the card: SD32 is a 32 GB card."),
    ("new",     "N",  "new",    "New",    "listed here for less than a week."),
    ("steady",  "S",  "steady", "Steady",
     "answered more than 95% of the heartbeats it was due over the last seven days."),
)

# A badge whose tooltip is its own sentence rather than "Name: meaning".
LETTER_TIPS = {"camera": "This BBS can take pictures."}

# The camera badge's drawing (site 1.2.8): a camera body with its hump, the
# lens and a glint in it, in the same 24 unit square and line weight as the
# causes and the interests, drawn in the chip's colour. Not the Photography
# interest's camera: that one is rose and says what the sysop likes; this
# one is blue and says what the board can do.
CAMERA_SVG = ('<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
              '<path d="M4.6 8.2 H7.8 L9.4 5.8 H14.6 L16.2 8.2 H19.4 C20.3 8.2 21 8.9'
              ' 21 9.8 V17.4 C21 18.3 20.3 19 19.4 19 H4.6 C3.7 19 3 18.3 3 17.4'
              ' V9.8 C3 8.9 3.7 8.2 4.6 8.2 Z"/>'
              '<circle cx="12" cy="13.5" r="3.5"/>'
              '<circle cx="12" cy="13.5" r="1.1" fill="currentColor" stroke="none"/>'
              "</svg>")

# How long a board has been listed, counted from the day it first went
# public. Only the highest reached is shown. A month is 30 days and a year
# 365, which is near enough for a badge and simple enough to say.
AGES = ((3652, "10y", "for ten years"), (1826, "5y", "for five years"),
        (730, "2y", "for two years"), (365, "1y", "for a year"),
        (182, "6m", "for six months"), (30, "1m", "for a month"))

# What each colour is called on /badges. A badge's colour says what kind of
# thing it is, and its letters say which one.
BADGE_COLOURS = {"soft": "grey", "sys": "white", "term": "purple",
                 "guest": "amber", "feat": "blue", "new": "orange",
                 "steady": "cyan", "age": "lavender", "int": "rose",
                 "upd": "dim cyan"}

# --------------------------------------------------------------------------
# The support and interest badges, by code (site 1.1.0).
#
# Their codes, names, sentences and aliases live in badges.json beside this
# file, and only there, so a separate program can read the same list: the
# firmware builds its CONFIG pick-list from it at build time. This file
# keeps what only a page needs, the drawings, keyed by code below.
#
# A code is what a board sends and what this directory stores and
# publishes: lower case, a to z and 0 to 9, six characters at most, shown in
# upper case on the site (Rob: "like 5 or 6 max", MNTLH for mental health).
# Every slug an earlier version of this site used, and every interim one
# proposed on the way to the codes, is an alias, so a board on firmware
# 1.0.1 that sends "mental-health" keeps its badge and a shared link with
# ?b=electronics still filters. Matching folds the case and drops everything
# that is not a letter or a digit, so "Mental health" typed into a board,
# which the firmware sends as "mentalhealth", is understood too. A stored
# row is read through the same aliases, so a row written before the codes
# needed no migration and is rewritten in codes by its next heartbeat.
#
# The support list is causes a sysop can show support for, and anything not
# in it is ignored, which is what keeps a sysop from putting words of their
# own on the page, slurs included. The first ten are the causes most often
# shown as support badges, ribbons and flair on community sites and
# profiles, picked to be broadly recognised and not party political. The
# next fourteen (site 0.22.2, Rob: "elder care, stuff that people do ... use
# volume as your guide") are the next most common by the same test: causes
# with a well-known ribbon, symbol or awareness day, each checked against
# the organisation that keeps it, and none of them a side in an argument
# between parties. Autism is not one of them because neurodiversity already
# names autistic people, and military families not because veterans already
# names them. Amateur radio was the eleventh until 0.22.2, when it moved to
# the interests, where a hobby belongs; SUPPORT_MOVED keeps a board that
# still sends it as support working.
#
# If badges.json cannot be read the site still starts, with no support or
# interest badges and a line in the journal saying so, and a heartbeat then
# leaves the causes and interests it has stored alone rather than writing
# them empty: every board would otherwise lose its badges to one missing
# file, and get them back only after somebody noticed.
# --------------------------------------------------------------------------
BADGE_FILE = pathlib.Path(__file__).resolve().parent / "badges.json"
CODE_MAX   = 6
_CODE      = re.compile(r"^[a-z0-9]{1,6}$")
# Words that are something else in the filter, so no code or alias may be
# one of them.
_RESERVED  = ({b[0] for b in LETTER_BADGES} | {a[1] for a in AGES}
              | {"update", "software", "system"})


def norm_word(value):
    """A badge word as it is matched: lower case, letters and digits only.
    "Mental health", "mental-health" and "MentalHealth" are all
    "mentalhealth"; anything that is not a string is ""."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _uncap(text):
    """A name as it reads after "Supports": its first letter lower case,
    unless the first word is an acronym, so "LGBTQ+ people" stays whole."""
    if len(text) > 1 and text[1].isupper():
        return text
    return text[:1].lower() + text[1:]


def _badge_codes():
    """The support and interest badges from badges.json: (support,
    interests, interest groups, support aliases, interest aliases, the
    aliases as written, ok).

    support is (code, name, sentence) and interests (code, group, name,
    sentence), each in the file's order. An alias table maps every word a
    board may send, the code itself included, after norm_word, to its code;
    the aliases as written, lower case and hyphens kept, are for the search
    boxes. An entry that breaks a rule is left out with a line saying why,
    and so is an alias that would name a second badge: the rest still load.
    ok is False only when the file could not be read at all."""
    empty = ((), (), (), {}, {}, {}, False)
    try:
        data = json.loads(BADGE_FILE.read_text(encoding="utf-8"))
        entries = data["badges"]
        groups = tuple(g for g in data.get("interest_groups") or ()
                       if isinstance(g, str) and g)
        if not isinstance(entries, list):
            raise ValueError("badges is not a list")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as err:
        print(f"badges: {BADGE_FILE.name} not read ({err}): no support or interest "
              "badges, and heartbeats leave the stored ones alone", flush=True)
        return empty
    support, interests = [], []
    alias = {"support": {}, "interests": {}}
    written = {}                                # code: its aliases as typed
    owner = {}                                  # every word taken, to its code

    def skip(why):
        print(f"badges: {why}, left out", flush=True)

    for e in entries:
        if not isinstance(e, dict):
            skip("an entry that is not an object")
            continue
        code, group, sub = e.get("code"), e.get("group"), e.get("sub", "")
        name, means = e.get("name"), e.get("means")
        if not (isinstance(code, str) and _CODE.match(code)):
            skip(f"code {code!r} is not one to six of a to z and 0 to 9")
            continue
        if (group not in alias or not isinstance(name, str) or not name.strip()
                or not isinstance(means, str) or not means.strip()):
            skip(f"{code}: its group, name or meaning")
            continue
        if group == "interests" and sub not in groups:
            skip(f"{code}: {sub!r} is not one of the interest groups")
            continue
        if code in owner or code in _RESERVED:
            skip(f"{code}: that word is already taken")
            continue
        owner[code] = code
        alias[group][code] = code
        aliases = e.get("aliases") or []
        if not isinstance(aliases, list):
            # A bare string would be read a letter at a time.
            skip(f"{code}: its aliases, which are not a list")
            aliases = []
        for a in aliases:
            w = norm_word(a)
            if not w:
                continue
            if w in _RESERVED or owner.get(w, code) != code:
                skip(f"{code}: its alias {a!r}, which is already taken")
                continue
            owner[w] = code
            alias[group][w] = code
            written.setdefault(code, []).append(a.strip().lower())
        if group == "support":
            support.append((code, name.strip(), means.strip()))
        else:
            interests.append((code, sub, name.strip(), means.strip()))
    return (tuple(support), tuple(interests), groups,
            alias["support"], alias["interests"], written, True)


(SUPPORT, INTERESTS, INTEREST_GROUPS, SUPPORT_ALIAS, INTEREST_ALIAS,
 ALIASES_WRITTEN, BADGE_CODES_OK) = _badge_codes()
SUPPORT_CODES  = tuple(s[0] for s in SUPPORT)
INTEREST_CODES = tuple(i[0] for i in INTERESTS)
# Every word the filter's ?b= understands for a cause or an interest.
FILTER_ALIAS   = {**SUPPORT_ALIAS, **INTEREST_ALIAS}
# Codes that were support causes and are interests now, still accepted in a
# board's "support" list and filed with its interests (site 0.22.2). No
# firmware sent either list when it moved, so this is courtesy rather than
# rescue, but it costs one line and keeps any hand-built board listed as it
# meant to be.
SUPPORT_MOVED = ("ham",)

# The drawings, keyed by code (site 1.1.0; a new cause in badges.json wants
# one here too), in a 24 unit square, line art in the manner of the rest of
# the site: strokes, round ends, no fill except the dots. Each keeps the
# colours its cause is known by, lifted enough to read on the page's black.
# The chip behind them is #0d0d12, which is what "cut" strokes are drawn in:
# the gap where one line passes under another.
_CUT = "#0d0d12"


def _ribbon(colour):
    return (f'<path d="M14.8 9.4 L8.2 20.5" stroke="{colour}"/>'
            f'<path d="M9.2 9.4 L15.8 20.5" stroke="{_CUT}" stroke-width="4"/>'
            f'<path d="M9.2 9.4 L15.8 20.5 M9.2 9.4 C7.4 6.2 9 3.5 12 3.5 '
            f'C15 3.5 16.6 6.2 14.8 9.4" stroke="{colour}"/>')


SUPPORT_ART = {
    # Six arcs of the pride flag.
    "lgbtq": "".join(
        f'<path d="M{12 - r} 17.5 A{r} {r} 0 0 1 {12 + r} 17.5" stroke="{c}" '
        'stroke-width="1.35"/>'
        for r, c in ((10.5, "#ef6a5a"), (9, "#f39a4a"), (7.5, "#f2d54e"),
                     (6, "#5cc478"), (4.5, "#5b9df0"), (3, "#b07ae8"))),
    # The transgender symbol, in the trans flag's blue, pink and white.
    "trans": ('<circle cx="12" cy="13.5" r="4.2" stroke="#eeeef4"/>'
              '<path d="M12 17.7 V22.3 M9.8 20.2 H14.2" stroke="#f5a9b8"/>'
              '<path d="M15 10.5 L19 6.5 M15.8 6.5 H19 V9.7" stroke="#6ccff6"/>'
              '<path d="M9 10.5 L5 6.5 M8.2 6.5 H5 V9.7 M6.2 10.4 L8.6 8"'
              ' stroke="#f5a9b8"/>'),
    # The disability pride flag: five stripes cutting across it corner to
    # corner, in its own muted red, yellow, white, blue and green.
    "dsbld": ('<rect x="3" y="6" width="18" height="12" rx="1.5" stroke="#8a8a8a"'
                ' stroke-width="1.2"/>'
                '<g stroke-width="1.35" stroke-linecap="butt">'
                '<path d="M7.5 6 L21 15" stroke="#d57a86"/>'
                '<path d="M5.25 6 L21 16.5" stroke="#e8d27a"/>'
                '<path d="M3 6 L21 18" stroke="#e6e6ea"/>'
                '<path d="M3 7.5 L18.75 18" stroke="#7ab8e0"/>'
                '<path d="M3 9 L16.5 18" stroke="#4fb487"/></g>'),
    # The neurodiversity infinity, its four quarters in rainbow colours.
    "neuro": ('<path d="M12 12 C10.5 9.5 9 8 7.5 8 C5.5 8 4 9.8 4 12" stroke="#ef6a5a"/>'
                 '<path d="M4 12 C4 14.2 5.5 16 7.5 16 C9 16 10.5 14.5 12 12" stroke="#f2d54e"/>'
                 '<path d="M12 12 C13.5 9.5 15 8 16.5 8 C18.5 8 20 9.8 20 12" stroke="#5cc478"/>'
                 '<path d="M20 12 C20 14.2 18.5 16 16.5 16 C15 16 13.5 14.5 12 12" stroke="#5b9df0"/>'),
    # Awareness ribbons, in the colour each cause is known by: green for
    # mental health, lavender for every cancer, red for HIV and AIDS.
    "mntlh": _ribbon("#5fcf8c"),
    "cancer":  _ribbon("#c6a4f0"),
    "hiv":  _ribbon("#e25a55"),
    # Project Semicolon's mark.
    "scdpv": ('<circle cx="12" cy="7" r="1.9" fill="#5cc6bf" stroke="#5cc6bf"'
                  ' stroke-width="0.6"/>'
                  '<circle cx="12" cy="14" r="1.9" fill="#5cc6bf" stroke="#5cc6bf"'
                  ' stroke-width="0.6"/>'
                  '<path d="M13.8 14.4 C13.9 17.2 12.8 19.5 10.3 21" stroke="#5cc6bf"/>'),
    # A dog tag on its ball chain, with its lines stamped in. Two
    # overlapping tags read as a "copy" icon at this size; one on a chain
    # reads as a tag.
    "vets": ('<path d="M12 11 C7.5 8.5 8 2.5 12 2.5 C16 2.5 16.5 8.5 12 11"'
             ' stroke="#e0a94e" stroke-width="1.3" stroke-dasharray="0.01 1.75"/>'
             '<rect x="6.8" y="10" width="10.4" height="12.2" rx="3.6" stroke="#e0a94e"/>'
             '<circle cx="12" cy="12.6" r="0.9" stroke="#e0a94e" stroke-width="1.1"/>'
             '<path d="M9.6 16 H14.4 M9.6 18.6 H13" stroke="#e0a94e" stroke-width="1.2"'
             ' opacity="0.7"/>'),
    # A paw print.
    "animal": ('<path d="M8 17 C8 14 10 12 12 12 C14 12 16 14 16 17 C16 19 14.4 20 12 20'
            ' C9.6 20 8 19 8 17 Z" stroke="#e3a36b"/>'
            '<ellipse cx="6.2" cy="11" rx="1.6" ry="2.1" transform="rotate(-20 6.2 11)"'
            ' stroke="#e3a36b"/>'
            '<ellipse cx="9.7" cy="7.2" rx="1.7" ry="2.2" stroke="#e3a36b"/>'
            '<ellipse cx="14.3" cy="7.2" rx="1.7" ry="2.2" stroke="#e3a36b"/>'
            '<ellipse cx="17.8" cy="11" rx="1.6" ry="2.1" transform="rotate(20 17.8 11)"'
            ' stroke="#e3a36b"/>'),
    # Site 0.22.2. Ribbons in the colour each cause is known by: pink for
    # breast cancer, gold for childhood cancer, purple for domestic
    # violence, a deeper purple than cancer's lavender.
    "brst": _ribbon("#f28cb8"),
    "chldc": _ribbon("#e8c24a"),
    "dv": _ribbon("#a07ae6"),
    # The forget-me-not: five blue petals round a yellow eye, the petals
    # apart so they read as a flower at a badge's size, not a knot.
    "dmnta": ("".join(
        f'<circle cx="{x}" cy="{y}" r="2.4" stroke="#6fa8f0" stroke-width="1.5"/>'
        for x, y in ((12, 6.8), (16.95, 10.39), (15.06, 16.21), (8.94, 16.21),
                     (7.05, 10.39)))
        + '<circle cx="12" cy="12" r="1.5" fill="#f2d54e" stroke="#f2d54e"'
          ' stroke-width="0.6"/>'),
    # Two cupped hands holding a heart, their thumbs turned in over it so
    # the curve reads as hands and not as a smile.
    "carers": ('<path d="M12 11.6 C9.5 9.9 8.5 8.6 8.5 7.3 C8.5 6.2 9.3 5.4 10.3 5.4'
              ' C11 5.4 11.6 5.8 12 6.4 C12.4 5.8 13 5.4 13.7 5.4 C14.7 5.4 15.5 6.2 15.5 7.3'
              ' C15.5 8.6 14.5 9.9 12 11.6 Z" stroke="#f5a9b8" stroke-width="1.5"/>'
              '<path d="M3.2 9.8 V12.8 C3.2 17.2 7 20.4 12 20.4 C17 20.4 20.8 17.2'
              ' 20.8 12.8 V9.8" stroke="#e6e6ea"/>'
              '<path d="M3.2 9.8 C4.8 10.2 6 11.4 6.6 13.2 M20.8 9.8 C19.2 10.2 18 11.4'
              ' 17.4 13.2" stroke="#e6e6ea" stroke-width="1.5"/>'),
    # The International Diabetes Federation's blue circle.
    "dbts": '<circle cx="12" cy="12" r="7.4" stroke="#5b9df0" stroke-width="2.8"/>',
    # A heart with a beat running through it.
    "heart": ('<path d="M12 20.2 C6.2 15.8 3.2 12.7 3.2 9 C3.2 6.3 5.2 4.3 7.6 4.3'
                  ' C9.5 4.3 11 5.5 12 7.1 C13 5.5 14.5 4.3 16.4 4.3 C18.8 4.3 20.8 6.3'
                  ' 20.8 9 C20.8 12.7 17.8 15.8 12 20.2 Z" stroke="#ef6a5a"/>'
                  '<path d="M6 11.2 H9.2 L10.6 8.4 L12.6 13.8 L14 11.2 H18" stroke="#eeeef4"'
                  ' stroke-width="1.4"/>'),
    # Recovery: a sun coming up over the line, in recovery's purple.
    "rcvry": ('<path d="M7 17 A5 5 0 0 1 17 17" stroke="#b07ae8"/>'
                '<path d="M3 17 H21" stroke="#b07ae8"/>'
                '<path d="M12 10 V8 M16.95 12.05 L18.36 10.64 M7.05 12.05 L5.64 10.64'
                ' M18.47 14.32 L20.3 13.56 M5.53 14.32 L3.7 13.56" stroke="#b07ae8"'
                ' stroke-width="1.5"/>'
                '<path d="M8 20.2 H16" stroke="#b07ae8" stroke-width="1.4" opacity="0.6"/>'),
    # A drop of blood with a green heart in it: blood donation's drop and
    # organ donation's green.
    "donor": ('<path d="M12 3 C12 3 5.5 10.2 5.5 14.4 C5.5 18 8.4 20.8 12 20.8'
             ' C15.6 20.8 18.5 18 18.5 14.4 C18.5 10.2 12 3 12 3 Z" stroke="#ef6a5a"/>'
             '<path d="M12 17.6 C10 16.2 9.2 15.1 9.2 14 C9.2 13.1 9.9 12.5 10.7 12.5'
             ' C11.3 12.5 11.8 12.9 12 13.4 C12.2 12.9 12.7 12.5 13.3 12.5 C14.1 12.5'
             ' 14.8 13.1 14.8 14 C14.8 15.1 14 16.2 12 17.6 Z" stroke="#5cc478"'
             ' stroke-width="1.3"/>'),
    # The adoption triad: a triangle and a heart through it, in foster
    # care's blue with a pink heart.
    "foster": ('<path d="M12 3.5 L20.5 18.3 H3.5 Z" stroke="#6fb0ef"/>'
              '<path d="M12 20.6 C8.3 17.8 6.7 15.8 6.7 13.6 C6.7 11.9 8 10.7 9.5 10.7'
              ' C10.6 10.7 11.5 11.4 12 12.3 C12.5 11.4 13.4 10.7 14.5 10.7 C16 10.7'
              ' 17.3 11.9 17.3 13.6 C17.3 15.8 15.7 17.8 12 20.6 Z" stroke="#f5a9b8"'
              ' stroke-width="1.5"/>'),
    # A house with its door: somewhere to live.
    "hmlss": ('<path d="M3.8 11.2 L12 4 L20.2 11.2 M6 9.4 V20.2 H18 V9.4"'
              ' stroke="#d4a373"/>'
              '<path d="M10 20.2 V15.2 H14 V20.2" stroke="#d4a373" stroke-width="1.5"/>'),
    # A bowl, steaming, in hunger relief's orange.
    "hunger": ('<path d="M3.5 12 H20.5 C20.5 16.6 16.7 19.8 12 19.8 C7.3 19.8 3.5 16.6'
             ' 3.5 12 Z" stroke="#f39a4a"/>'
             '<path d="M8.6 9.2 C7.8 8 9.6 7 8.8 5.4 M12.2 9.2 C11.4 8 13.2 7 12.4 5.4'
             ' M15.8 9.2 C15 8 16.8 7 16 5.4" stroke="#f39a4a" stroke-width="1.3"'
             ' opacity="0.8"/>'),
    # An open book with lines of text on its pages.
    "ltrcy": ('<path d="M12 6.6 C10 5.1 7 4.6 3 5.1 V18.6 C7 18.1 10 18.6 12 20.1'
                 ' C14 18.6 17 18.1 21 18.6 V5.1 C17 4.6 14 5.1 12 6.6 Z M12 6.6 V20.1"'
                 ' stroke="#8fb4ff"/>'
                 '<path d="M5.6 8.8 H9.6 M5.6 11.6 H9.6 M5.6 14.4 H8.6 M14.4 8.8 H18.4'
                 ' M14.4 11.6 H18.4 M14.4 14.4 H17.4" stroke="#8fb4ff" stroke-width="1.2"'
                 ' opacity="0.75"/>'),
    # An emergency beacon: a red lamp throwing blue light, which is every
    # service's rather than one side's.
    "frstr": ('<path d="M7 16.4 V12.4 C7 9.6 9.2 7.4 12 7.4 C14.8 7.4 17 9.6 17 12.4'
               ' V16.4" stroke="#ef6a5a"/>'
               '<path d="M5 16.4 H19 V19.8 H5 Z" stroke="#e6e6ea" stroke-width="1.5"/>'
               '<path d="M12 4.8 V2.8 M6.4 6.6 L5 5.2 M17.6 6.6 L19 5.2 M4 11.4 H2.4'
               ' M20 11.4 H21.6" stroke="#5b9df0" stroke-width="1.5"/>'),
}


def support_svg(key):
    """One support drawing, hidden from a screen reader because the chip it
    sits in is named already."""
    return ('<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
            + SUPPORT_ART[key] + "</svg>")


# --------------------------------------------------------------------------
# Interests (site 0.22.0, Rob): what the sysop is into, the way support is
# what the sysop stands for. Same rules exactly: a board sends codes in its
# "interests" list, anything not in the table is ignored, and only the
# first 16 are read. The list is wide on purpose, because the people who
# call BBSes are into all sorts: electronics and gaming, but also bikes,
# gardens and trains.
#
# The table itself, each with its group, the name a reader sees and one
# plain sentence for /badges, is in badges.json with the support causes
# (site 1.1.0). The groups are the headings on /badges and the rows of the
# board list's filter, in the file's order; within a group the page orders
# by name (see sort_key).
# --------------------------------------------------------------------------


def _dot(x, y, r=1.0):
    """A filled dot in the drawing's own colour: an eye, a lamp, a pellet."""
    return f'<circle cx="{x}" cy="{y}" r="{r}" fill="currentColor" stroke="none"/>'


# The drawings, keyed by code, in the same 24 unit square and the same line
# art as the support symbols, but in one colour, currentColor, which the
# chip sets: rose, a family nothing else on the page uses. Simple enough to
# read at a badge's 17px and a filter chip's 22: one outline and a detail or
# two, never a scene. A dot is the only fill.
INTEREST_ART = {
    # Computing
    "bbs": (  # a rotary telephone: how every board was called
        '<path d="M3.6 8.8 C3.6 6.2 7.4 4.4 12 4.4 C16.6 4.4 20.4 6.2 20.4 8.8'
        ' L19.6 10 H16.4 L15.8 8.2 C13.6 7.7 10.4 7.7 8.2 8.2 L7.6 10 H4.4 Z"/>'
        '<path d="M8.6 10.6 H15.4 L19.4 19.2 C19.6 19.8 19.2 20.4 18.6 20.4 H5.4'
        ' C4.8 20.4 4.4 19.8 4.6 19.2 Z"/>'
        '<circle cx="12" cy="15.2" r="2.7" stroke-width="1.5"/>'
        + _dot(12, 15.2, 0.8)),
    "linux": (  # a penguin: a pale belly, two eyes, a beak and its feet
        '<path d="M12 2.8 C9.6 2.8 8.6 4.8 8.6 7.2 C8.6 8.6 7.9 9.7 7.1 11.1 '
        'C5.9 13.1 5.3 15.1 5.7 17.1 C6.1 19.1 7.8 20.2 9.8 20.2 H14.2 C16.2 20.2 '
        '17.9 19.1 18.3 17.1 C18.7 15.1 18.1 13.1 16.9 11.1 C16.1 9.7 15.4 8.6 '
        '15.4 7.2 C15.4 4.8 14.4 2.8 12 2.8 Z"/>'
        '<path d="M9.5 12.3 C10.2 10.9 13.8 10.9 14.5 12.3 C15.5 14.4 15.3 17.6 12'
        ' 18.2 C8.7 17.6 8.5 14.4 9.5 12.3 Z" fill="currentColor" stroke="none"'
        ' opacity="0.35"/>'
        '<path d="M10.9 8.7 L12 9.7 L13.1 8.7" stroke-width="1.4"/>'
        '<path d="M7 20.8 C7.8 21.8 10 21.9 10.8 20.6 M13.2 20.6 C14 21.9 16.2 21.8'
        ' 17 20.8" stroke-width="1.6"/>'
        + _dot(10.7, 6.5, 0.95) + _dot(13.3, 6.5, 0.95)),
    "oss": (  # the open source keyhole: a ring with its way in
        '<path d="M9.3 20.1 A8.5 8.5 0 1 1 14.7 20.1 L13.1 15.4 '
        'A3.6 3.6 0 1 0 10.9 15.4 Z"/>'),
    "prgrm": (  # angle brackets and a slash
        '<path d="M8.5 7 L3.5 12 L8.5 17 M15.5 7 L20.5 12 L15.5 17 M13.6 4.5 L10.4 19.5"/>'),
    "retro": (  # a monitor on a desktop box
        '<rect x="5.5" y="3.2" width="13" height="10.6" rx="1.4"/>'
        '<rect x="8" y="5.7" width="8" height="5.6" rx="0.6" stroke-width="1.3"/>'
        '<path d="M10 13.8 V16.6 M14 13.8 V16.6"/>'
        '<rect x="3" y="16.6" width="18" height="4.4" rx="1"/>'
        '<path d="M13.4 18.8 H18.2" stroke-width="1.4"/>'),
    # Platforms
    "amiga": (  # the bouncing ball: checked, tilted, with its shadow
        '<g transform="rotate(-18 12 10.6)">'
        '<g fill="currentColor" stroke="none" opacity="0.8">'
        '<path d="M12 6.8 H8.71 A3.8 7.6 0 0 0 8.2 10.6 H12 Z"/>'
        '<path d="M12 10.6 H15.8 A3.8 7.6 0 0 1 15.29 14.4 H12 Z"/>'
        '<path d="M15.29 6.8 H18.58 A7.6 7.6 0 0 1 19.6 10.6 H15.8'
        ' A3.8 7.6 0 0 0 15.29 6.8 Z"/>'
        '<path d="M8.71 14.4 H5.42 A7.6 7.6 0 0 1 4.4 10.6 H8.2'
        ' A3.8 7.6 0 0 0 8.71 14.4 Z"/>'
        '</g>'
        '<circle cx="12" cy="10.6" r="7.6"/>'
        '</g>'
        '<path d="M8.5 21.8 H16.5" stroke-width="1.5" opacity="0.5"/>'),
    "apple2": (  # an apple, from the tree
        '<path d="M12 8.4 C10.2 7 5.4 6.8 5.4 12 C5.4 16.4 8.3 20.8 10.4 20.8 '
        'C11.2 20.8 11.4 20.3 12 20.3 C12.6 20.3 12.8 20.8 13.6 20.8 C15.7 20.8 '
        '18.6 16.4 18.6 12 C18.6 6.8 13.8 7 12 8.4 Z"/>'
        '<path d="M12 8.4 C12 6.6 12.5 4.8 13.6 3.6" stroke-width="1.5"/>'
        '<path d="M13.2 5.6 C14 3.9 15.9 3.3 17.6 3.6 C16.9 5.3 15 6.1 13.2 5.6 Z"'
        ' stroke-width="1.3"/>'),
    "atari": (  # the joystick, stick up, fire button in the corner
        '<rect x="3.8" y="14" width="16.4" height="7" rx="1.6"/>'
        '<path d="M12 14 V7.4"/>'
        '<circle cx="12" cy="5.4" r="2.3"/>'
        '<path d="M5.8 14 V12.2 H9.2 V14" stroke-width="1.5"/>'),
    "c64": (  # the breadbin: a wedge of keyboard, keys and a space bar
        '<path d="M3 18 L5.4 9.8 C5.7 8.8 6.4 8.2 7.5 8.2 H16.5 C17.6 8.2 18.3 '
        '8.8 18.6 9.8 L21 18 V19.4 C21 20.2 20.4 20.8 19.6 20.8 H4.4 C3.6 20.8 '
        '3 20.2 3 19.4 Z M3 18 H21"/>'
        '<path d="M7.2 11.1 H16.8 M6.5 13.6 H17.5" stroke-width="1.5"'
        ' stroke-linecap="butt" stroke-dasharray="1.2 0.9"/>'
        '<path d="M9.4 16 H14.6" stroke-width="1.5"/>'),
    "dos": (  # a floppy disk: the Disk in DOS
        '<path d="M3.6 5 C3.6 4.2 4.2 3.6 5 3.6 H16.4 L20.4 7.6 V19 C20.4 19.8 '
        '19.8 20.4 19 20.4 H5 C4.2 20.4 3.6 19.8 3.6 19 Z"/>'
        '<path d="M7.6 3.6 V8.8 H15.4 V3.6"/>'
        '<path d="M12.9 5.2 V7.2" stroke-width="1.5"/>'
        '<path d="M6.6 20.4 V14.2 H17.4 V20.4"/>'),
    "zx": (  # a flat rubber-key keyboard with the stripes in its corner
        '<rect x="2.6" y="6.8" width="18.8" height="10.4" rx="1.2"/>'
        '<path d="M5.4 9.8 H13.6 M5.4 12.2 H13.6 M5.4 14.6 H12" stroke-width="1.7"'
        ' stroke-dasharray="0.01 2.05"/>'
        '<path d="M14.6 17.2 L21.4 10.4 M16.8 17.2 L21.4 12.6 M19 17.2 L21.4 14.8"'
        ' stroke-width="1.3"/>'),
    # Making
    "3dprt": (  # a nozzle over the layers it has laid
        '<path d="M9.4 3 H14.6 V6.4 L12 9 L9.4 6.4 Z"/>'
        + _dot(12, 11.2, 0.85)
        + '<path d="M6 13.8 H18 M6 17 H18 M6 20.2 H18" stroke-width="1.6"/>'),
    "elctr": (  # a chip on its pins
        '<rect x="7" y="4.4" width="10" height="15.2" rx="1"/>'
        '<path d="M10.6 4.4 A1.4 1.4 0 0 0 13.4 4.4" stroke-width="1.3"/>'
        '<path d="M3.8 7.8 H7 M3.8 12 H7 M3.8 16.2 H7 M17 7.8 H20.2 M17 12 H20.2'
        ' M17 16.2 H20.2"/>'),
    "robot": (  # a robot's head
        '<rect x="5" y="8.2" width="14" height="11" rx="2"/>'
        '<path d="M12 8.2 V5"/>'
        '<circle cx="12" cy="3.9" r="1.1"/>'
        '<path d="M3 12 V15.4 M21 12 V15.4 M9.6 16.3 H14.4"/>'
        + _dot(9.2, 12.6, 1.2) + _dot(14.8, 12.6, 1.2)),
    "solder": (  # the iron, and a wisp off its tip
        '<path d="M3.6 20.4 L8 16" stroke-width="1.5"/>'
        '<path d="M8 16 L10.4 13.6" stroke-width="2.4"/>'
        '<path d="M12 14.8 L20 6.8 A2 2 0 0 0 17.2 4 L9.2 12 Z"/>'
        '<path d="M5.4 12.6 C4.4 11.4 6.4 10.4 5.4 9.2" stroke-width="1.4" opacity="0.7"/>'),
    "wood": (  # a handsaw
        '<path d="M14 8.6 L3.2 12 V15.4 L4.4 16.9 L5.6 15.4 L6.8 16.9 L8 15.4'
        ' L9.2 16.9 L10.4 15.4 L11.6 16.9 L12.8 15.4 L14 16.4"/>'
        '<path d="M14 7 H18.6 C19.9 7 21 8.1 21 9.4 V15.2 C21 16.5 19.9 17.6 18.6'
        ' 17.6 H14 Z"/>'
        '<rect x="16" y="9.6" width="2.8" height="4.8" rx="1.2" stroke-width="1.4"/>'),
    # Games
    "arcade": (  # a cabinet: screen, stick, two buttons
        '<path d="M6.6 21 V11.6 L8.4 9.8 V3 H15.6 V9.8 L17.4 11.6 V21 Z"/>'
        '<rect x="9.8" y="4.6" width="4.4" height="3.8" rx="0.4" stroke-width="1.3"/>'
        '<path d="M6.6 14 H17.4 M10 14 V12.4" stroke-width="1.5"/>'
        + _dot(10, 11.8, 1) + _dot(13.3, 12.6, 0.8) + _dot(15.1, 12.6, 0.8)),
    "brdgm": (  # a meeple
        '<path d="M12 3 C13.7 3 15 4.3 15 6 C15 7 14.6 7.8 14 8.3 C16.5 8.8 20.4'
        ' 10 20.4 12 C20.4 13.3 18.5 13.5 16.8 13.3 L19 19.4 C19.3 20.4 18.8 21'
        ' 18 21 H14.2 L12 17.4 L9.8 21 H6 C5.2 21 4.7 20.4 5 19.4 L7.2 13.3 C5.5'
        ' 13.5 3.6 13.3 3.6 12 C3.6 10 7.5 8.8 10 8.3 C9.4 7.8 9 7 9 6 C9 4.3 10.3'
        ' 3 12 3 Z"/>'),
    "games": (  # a game pad
        '<path d="M7 8 H17 C19.9 8 21.5 11 21.5 14.6 C21.5 17 20.2 18.2 18.6 18.2'
        ' C17.2 18.2 16.4 16.8 15.6 15.4 H8.4 C7.6 16.8 6.8 18.2 5.4 18.2 C3.8 18.2'
        ' 2.5 17 2.5 14.6 C2.5 11 4.1 8 7 8 Z"/>'
        '<path d="M7.4 10.6 V14.6 M5.4 12.6 H9.4" stroke-width="1.6"/>'
        + _dot(15.4, 11.6, 1) + _dot(17.6, 13.6, 1)),
    "rtrgm": (  # the chomper, about to eat a pellet
        '<path d="M17.1 7.9 A7.8 7.8 0 1 0 17.1 16.1 L10.4 12 Z"/>'
        + _dot(10.2, 7.9, 1.1) + _dot(20.9, 12, 1.3)),
    "rpg": (  # a twenty sided die
        '<path d="M12 2.5 L20.2 7.25 V16.75 L12 21.5 L3.8 16.75 V7.25 Z"/>'
        '<path d="M12 7.6 L16.6 15.4 H7.4 Z" stroke-width="1.4"/>'
        '<path d="M12 7.6 L3.8 7.25 M12 7.6 L20.2 7.25 M7.4 15.4 L3.8 16.75'
        ' M7.4 15.4 L12 21.5 M16.6 15.4 L20.2 16.75 M16.6 15.4 L12 21.5 M12 2.5'
        ' V7.6" stroke-width="1.1" opacity="0.8"/>'),
    # Music and art
    "ansi": (  # the shade blocks, light to full
        '<path d="M4.6 4.5 V19.5" stroke-width="3.4" stroke-linecap="butt"'
        ' stroke-dasharray="1 2"/>'
        '<path d="M9.2 4.5 V19.5" stroke-width="3.4" stroke-linecap="butt"'
        ' stroke-dasharray="1.5 1.5"/>'
        '<path d="M13.8 4.5 V19.5" stroke-width="3.4" stroke-linecap="butt"'
        ' stroke-dasharray="2.2 0.8"/>'
        '<path d="M18.4 4.5 V19.5" stroke-width="3.4" stroke-linecap="butt"/>'),
    "chptn": (  # a square wave, the sound of a pulse channel
        '<path d="M2.5 16 H5.6 V8 H10 V16 H14 V8 H18.4 V16 H21.5"/>'
        '<path d="M2.5 20 H21.5" stroke-width="1.2" stroke-dasharray="0.01 2.4"/>'),
    "demo": (  # a sine scroller of dots, and a sparkle
        '<path d="M2.6 13.4 C5 5.8 8.4 5.8 10.8 13.4 S16.6 21 19 13.4"'
        ' stroke-width="2.3" stroke-dasharray="0.01 2.7"/>'
        '<path d="M19.2 2.8 V7.8 M16.7 5.3 H21.7" stroke-width="1.5"/>'),
    "draw": (  # a pencil
        '<path d="M4 20 L5 15.6 L15.6 5 C16.4 4.2 17.7 4.2 18.5 5 L19 5.5 C19.8'
        ' 6.3 19.8 7.6 19 8.4 L8.4 19 Z"/>'
        '<path d="M14 6.6 L17.4 10 M5 15.6 L8.4 19" stroke-width="1.4"/>'),
    "music": (  # two beamed quavers
        '<path d="M9 17.6 V6.4 L19 4.2 V15.6"/>'
        '<ellipse cx="6.8" cy="17.8" rx="2.4" ry="1.9" transform="rotate(-20 6.8 17.8)"'
        ' fill="currentColor"/>'
        '<ellipse cx="16.8" cy="15.8" rx="2.4" ry="1.9" transform="rotate(-20 16.8 15.8)"'
        ' fill="currentColor"/>'),
    "photo": (  # a camera
        '<path d="M3 9 C3 8.2 3.6 7.6 4.4 7.6 H7.4 L9 5 H15 L16.6 7.6 H19.6 C20.4'
        ' 7.6 21 8.2 21 9 V18 C21 18.8 20.4 19.4 19.6 19.4 H4.4 C3.6 19.4 3 18.8'
        ' 3 18 Z"/>'
        '<circle cx="12" cy="13.2" r="3.6"/>'
        + _dot(18.2, 10.2, 0.8)),
    # Radio and sky
    "ham": (  # a lattice mast, calling out both ways; support's drawing
        # until 0.22.2, now in the chip's colour like every other interest
        '<path d="M12 8.5 L8 21 M12 8.5 L16 21 M9.3 17 H14.7 M10.6 12.8 H13.4'
        ' M7 21 H17"/>'
        + _dot(12, 7, 1.2)
        + '<path d="M15.2 4.4 A4.2 4.2 0 0 1 15.2 9.6 M8.8 4.4 A4.2 4.2 0 0 0 8.8 9.6'
        ' M17.6 2.4 A7.25 7.25 0 0 1 17.6 11.6 M6.4 2.4 A7.25 7.25 0 0 0 6.4 11.6"'
        ' stroke-width="1.4"/>'),
    "astro": (  # a ringed planet
        '<circle cx="12" cy="12" r="5"/>'
        '<path d="M7.2 10.7 C3.8 11.8 2.2 13.5 2.9 14.6 C3.9 16.3 10 15.5 15.8'
        ' 13.1 C21.2 10.8 22.3 8.5 21 7.7 C20.2 7.2 18.6 7.3 16.7 7.9"/>'
        '<path d="M5 3.6 V6.4 M3.6 5 H6.4" stroke-width="1.2"/>'),
    "swl": (  # a portable radio with its aerial up
        '<rect x="3" y="9.6" width="18" height="11" rx="2"/>'
        '<circle cx="8.4" cy="15.1" r="3"/>'
        '<path d="M14 13 H18.4 M14 15.6 H18.4 M14 18.2 H16.6" stroke-width="1.4"/>'
        '<path d="M16.2 9.6 L20 2.8"/>'),
    "wthr": (  # the sun behind a cloud
        '<path d="M5.4 11.6 A3.6 3.6 0 1 1 12.1 8.9" stroke-width="1.6"/>'
        '<path d="M8.6 2.4 V3.8 M3 8.4 H4.4 M4.6 4.4 L5.6 5.4 M12.6 4.4 L11.6 5.4"'
        ' stroke-width="1.5"/>'
        '<path d="M8.6 20.4 H17.8 A3.4 3.4 0 0 0 18.2 13.6 A4.8 4.8 0 0 0 9.2 13.8'
        ' A3.3 3.3 0 0 0 8.6 20.4 Z"/>'),
    # Outdoors and more
    "avtn": (  # an aeroplane, from below
        '<path d="M12 2.5 C12.9 2.5 13.3 3.5 13.3 5 V9.5 L21 14 V16 L13.3 13.6 V18.4'
        ' L15.6 20 V21.5 L12 20.5 L8.4 21.5 V20 L10.7 18.4 V13.6 L3 16 V14 L10.7'
        ' 9.5 V5 C10.7 3.5 11.1 2.5 12 2.5 Z"/>'),
    "cars": (  # a car, side on
        '<path d="M4.6 16.6 H2.6 V13.7 C2.6 13 3.1 12.5 3.7 12.4 L6.6 11.9 L9'
        ' 8.4 C9.4 7.9 9.9 7.6 10.6 7.6 H14.6 C15.3 7.6 15.9 7.9 16.3 8.5 L18.4'
        ' 11.8 L20.5 12.4 C21 12.6 21.4 13.1 21.4 13.6 V16.6 H19.4 M9.4 16.6 H14.6"/>'
        '<path d="M6.6 11.9 H18.4 M12.4 7.6 V11.9" stroke-width="1.4"/>'
        '<circle cx="7" cy="16.8" r="2.3"/><circle cx="17" cy="16.8" r="2.3"/>'),
    "cook": (  # a chef's hat
        '<path d="M7 13.2 C4.6 13.2 3 11.2 3 9.1 C3 6.9 4.8 5.1 7 5.1 C7.3 5.1 7.6'
        ' 5.1 7.9 5.2 C8.7 3.4 10.2 2.6 12 2.6 C13.8 2.6 15.3 3.4 16.1 5.2 C16.4'
        ' 5.1 16.7 5.1 17 5.1 C19.2 5.1 21 6.9 21 9.1 C21 11.2 19.4 13.2 17 13.2'
        ' V20.6 H7 Z"/>'
        '<path d="M7 17 H17" stroke-width="1.4"/>'),
    "bike": (  # a bicycle
        '<circle cx="5.9" cy="16.4" r="3.7"/><circle cx="18.1" cy="16.4" r="3.7"/>'
        '<path d="M5.9 16.4 H12 L9.8 9.8 Z M9.8 9.8 H16.2 L12 16.4 M16.2 9.8 L18.1'
        ' 16.4 M9.8 9.8 L9.4 8.2 M8 8.2 H11 M16.2 9.8 L15.6 7.6 H17.8"'
        ' stroke-width="1.5"/>'),
    "fish": (  # a fish
        '<path d="M2.8 12 C5.8 7 12.5 6.4 16.4 12 C12.5 17.6 5.8 17 2.8 12 Z"/>'
        '<path d="M16.4 12 L21.2 8.3 V15.7 Z"/>'
        '<path d="M10.4 9.4 C11.3 10.9 11.3 13.1 10.4 14.6" stroke-width="1.3"/>'
        + _dot(7.2, 11.1, 1)),
    "garden": (  # a seedling
        '<path d="M12 20.6 V11.4"/>'
        '<path d="M12 13.4 C12 9.6 9.2 7.4 5.2 7.4 C5.2 11.2 8 13.4 12 13.4 Z"/>'
        '<path d="M12 11.4 C12 7.4 14.8 4.8 18.8 4.8 C18.8 8.8 16 11.4 12 11.4 Z"/>'
        '<path d="M6.4 20.6 H17.6"/>'),
    "hike": (  # mountains, with snow on the high one
        '<path d="M2 19.6 L8.6 8.4 L12.6 14.8 L15.6 10.6 L22 19.6 Z"/>'
        '<path d="M6.7 11.6 L8.1 12.7 L9.6 11.2 L10.6 12.1" stroke-width="1.3"/>'),
    "trains": (  # a little steam engine on its rail
        '<path d="M3 17 V11 H13.4 V17 M13.4 17 V7 H20.4 V17 M12.6 7 H21.2'
        ' M5.4 11 V7.6 H8 V11 M2 17 H22"/>'
        '<rect x="15.3" y="8.8" width="3.2" height="2.8" rx="0.4" stroke-width="1.3"/>'
        '<circle cx="6.4" cy="19.2" r="1.7" stroke-width="1.5"/>'
        '<circle cx="10.8" cy="19.2" r="1.7" stroke-width="1.5"/>'
        '<circle cx="17" cy="19.2" r="1.7" stroke-width="1.5"/>'),
    # Reading and watching
    "anime": (  # a big eye with a shine in it
        '<path d="M2.8 11.2 C6.4 6.6 17.6 6.6 21.2 11.2 L22.4 9.4"/>'
        '<ellipse cx="12" cy="13.8" rx="4.1" ry="5.2"/>'
        '<ellipse cx="12" cy="15" rx="2" ry="2.6" fill="currentColor"/>'
        '<circle cx="13.5" cy="11.7" r="1.15" fill="#ffffff" stroke="none"/>'
        '<path d="M8.6 20.2 C10.8 20.9 13.2 20.9 15.4 20.2" stroke-width="1.4"/>'),
    "books": (  # an open book
        '<path d="M12 6.6 C10 5.1 7 4.6 3 5.1 V18.6 C7 18.1 10 18.6 12 20.1 C14 18.6'
        ' 17 18.1 21 18.6 V5.1 C17 4.6 14 5.1 12 6.6 Z M12 6.6 V20.1"/>'),
    "movies": (  # a clapperboard
        '<rect x="3.4" y="10" width="17.2" height="10.6" rx="1"/>'
        '<path d="M3.4 10 L2.9 6.9 C2.8 6.3 3.2 5.8 3.8 5.7 L19.4 3.4 C20 3.3 20.5'
        ' 3.7 20.6 4.3 L21 7.4 L3.4 10"/>'
        '<path d="M7.6 5.1 L9.6 8.8 M12 4.5 L14 8.2 M16.4 3.8 L18.4 7.6"'
        ' stroke-width="1.4"/>'),
    "scifi": (  # a flying saucer
        '<path d="M2.6 13.6 C2.6 11.7 7 10.2 12 10.2 C17 10.2 21.4 11.7 21.4 13.6'
        ' C21.4 15.5 17 17 12 17 C7 17 2.6 15.5 2.6 13.6 Z"/>'
        '<path d="M7.6 10.8 C7.6 7.8 9.6 5.6 12 5.6 C14.4 5.6 16.4 7.8 16.4 10.8"/>'
        + _dot(7, 13.7, 0.9) + _dot(12, 14.4, 0.9) + _dot(17, 13.7, 0.9)
        + '<path d="M9 19.4 L8 21.4 M15 19.4 L16 21.4" stroke-width="1.3" opacity="0.6"/>'),
}


def interest_svg(code):
    """One interest drawing, in the chip's colour, hidden from a screen
    reader because the chip it sits in is named already."""
    return ('<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
            + INTEREST_ART[code] + "</svg>")


# --------------------------------------------------------------------------
# Every badge, once, in the one order all three views use: /badges, the
# filter's grid and the badges under a board's name (Rob: alphabetical by
# the name a reader sees, within each group, the groups in their own
# order). Each entry carries its own sort key, worked out once, here, so the
# three views cannot drift apart: they all walk BADGES and none of them
# sorts anything.
#
# A group is "board" (sent by the board), "directory" (worked out here),
# "support" or "interests"; interests have a sub-group as well. The six
# steps of how long a board has been listed are one badge, "Listed", that
# shows its highest step only, so they share its sort key and keep their
# own order, shortest first, among themselves.
# --------------------------------------------------------------------------
BADGE_GROUPS = (("board",     "Sent by the board"),
                ("directory", "Worked out by the directory"),
                ("support",   "Show your support"),
                ("interests", "Interests"))


def sort_key(name):
    """Where a badge sorts in its group: its name as a reader sees it, case
    folded, with a leading digit or symbol set aside, so "3D printing" files
    under D and "Listed 10 years" does not jump ahead of the others."""
    return re.sub(r"^[^a-z]+", "", name.casefold())


def _cap(text):
    return text[0].upper() + text[1:]


def _badge_table():
    """BADGES, built once at start from the tables above."""
    out = []

    def add(group, key, name, cls, sym, means, sent, sub="", tip="", sort=None,
            filt=True, aliases=()):
        out.append({"group": group, "sub": sub, "key": key, "name": name,
                    "cls": cls, "sym": sym, "means": means, "sent": sent,
                    "tip": tip or f"{name}: {means[0].lower() + means[1:]}",
                    "sort": sort_key(name) if sort is None else sort,
                    "filter": filt, "aliases": tuple(aliases)})

    # Sent by the board. The software and the machine are the board's own
    # words, so they have no fixed symbol and nothing to filter on.
    add("board", "software", "Software", "soft", "µnleashed 1.0.0",
        "What the board runs, and which version of it.",
        "<code>software</code> <span class='src'>and <code>version</code></span>",
        tip="Software: µnleashed 1.0.0, as the board reports it.", filt=False)
    add("board", "system", "Machine", "sys", "Compaq 486",
        f"What the board runs on, in its own words, up to {SYSTEM_MAX} characters: "
        "the chip it runs on, or the Compaq 486 in the corner.",
        "<code>system</code> <span class='src'>its own words</span>",
        tip="Runs on: Compaq 486, in the board's own words.", filt=False)
    where = {"petscii": "<code>petscii</code> <span class='src'>in terminals</span>",
             "guests":  "<code>guests</code> <span class='src'>set to true</span>",
             "sd":      "<code>sd</code> <span class='src'>its size in GB</span>"}
    for key, letters, cls, name, means in LETTER_BADGES:
        if key in ("new", "steady"):
            add("directory", key, name, cls, letters, _cap(means),
                "<span class='src'>none: worked out here</span>",
                tip=f"{name}: {means}")
        else:
            add("board", key, name, cls, letters, _cap(means),
                where.get(key, f"<code>{key}</code> <span class='src'>in features</span>"),
                tip=LETTER_TIPS.get(key, f"{name}: {means}"))
    # The six steps of how long a board has been listed are one badge,
    # "Listed", which shows its highest step only; each step is a chip of
    # its own in the filter, meaning that long or longer. They share the
    # badge's sort key, so the family stays together and in its own order.
    for days, label, words in reversed(AGES):
        add("directory", label, "Listed " + words[4:], "age", label,
            f"On this directory {words} or more.",
            "<span class='src'>none: worked out here</span>",
            tip=f"Listed {words}.", sort=sort_key("Listed"))
    # A µnleashed board behind the newest release /install offers (site
    # 1.0.0, Rob: "when an unleashed board is behind, mark on there a subtle
    # up arrow"). On a board's row it is an arrow on the software badge,
    # linked to /upgrade; here and in the filter it is a badge of its own,
    # so a sysop can find which of their boards are behind.
    add("directory", "update", "Update available", "upd", "",
        "A µnleashed board running an older version than the newest one "
        "on the install page. The arrow on its software badge says which, "
        "and links to how to update it.",
        "<span class='src'>none: worked out here</span>",
        tip="Update available: a newer µnleashed release is on the install page.")
    # The causes and the interests (site 1.1.0): keyed by code, which is
    # what the filter's checkboxes and a board's data-b carry, lower case,
    # and shown upper case in the legend's Code column. The aliases ride
    # along so a search for an old slug still finds the badge it became.
    for code, name, sentence in SUPPORT:
        add("support", code, name, "sup", code, sentence,
            f"<code>{html.escape(code.upper())}</code>",
            tip=f"Supports {_uncap(name)}.", aliases=ALIASES_WRITTEN.get(code, ()))
    for code, sub, name, means in INTERESTS:
        add("interests", code, name, "int", code, means,
            f"<code>{html.escape(code.upper())}</code>",
            sub=sub, tip=f"Interest: {name}.", aliases=ALIASES_WRITTEN.get(code, ()))

    group_at = {g: i for i, (g, _t) in enumerate(BADGE_GROUPS)}
    sub_at = {s: i for i, s in enumerate(INTEREST_GROUPS)}
    # sorted() is stable, so badges that share a key keep the order they
    # were added in: the time-listed steps, shortest first.
    return tuple(sorted(out, key=lambda b: (group_at[b["group"]],
                                            sub_at.get(b["sub"], -1), b["sort"])))


BADGES = _badge_table()
BADGE_BY_KEY = {b["key"]: b for b in BADGES}
# Everything a reader can filter the board list on, in the page's order.
FILTER_KEYS = tuple(b["key"] for b in BADGES if b["filter"])

# The order of the small badges on a board's row (site 1.0.0, Rob: "sort
# those so core system ones are always first ... that way they look
# consistent when scrolling"). Fixed, so a badge sits in the same place on
# every row: what it speaks, guests, what is running, what the directory
# worked out, then the causes and the interests, and only those two
# alphabetical, because there a reader is scanning for a name. /badges and
# the filter keep BADGES order; only the row uses this. The SD card (site
# 1.1.0) sits with what is running, after doors, and the camera (site
# 1.2.8) between the two.
ROW_ORDER = ("petscii", "guests", "chat", "mail", "forums", "files", "doors",
             "camera", "sd", "new", "steady")
ROW_SUPPORT = tuple(b for b in BADGES if b["group"] == "support")
ROW_INTERESTS = tuple(sorted((b for b in BADGES if b["group"] == "interests"),
                             key=lambda b: b["sort"]))

# The arrow on the software badge of a board that is behind: line art in
# the badges' own hand, drawn in the chip's colour.
UP_ARROW = ('<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
            '<path d="M12 19.5 V5.5 M6 11.5 L12 5.5 L18 11.5"/></svg>')


def badge_symbol(b):
    """What a badge shows: its letters or its drawing, already markup. A
    cause or an interest with no drawing here, which is a code added to
    badges.json without one, shows its code rather than failing the page."""
    if b["cls"] == "sup" and b["sym"] in SUPPORT_ART:
        return support_svg(b["sym"])
    if b["cls"] == "int" and b["sym"] in INTEREST_ART:
        return interest_svg(b["sym"])
    if b["cls"] in ("sup", "int"):
        return html.escape(b["sym"].upper())
    if b["cls"] == "upd":
        return UP_ARROW
    if b["key"] == "camera":
        return CAMERA_SVG
    return html.escape(b["sym"])


def badge_words(b):
    """What a search matches a badge on, lower case: its name, its key (a
    code, for a cause or an interest), every alias it has with and without
    its hyphens, and its group, so "radio", "ham", "c64", "mntlh", "open
    source", "open-source" and "games" all find something."""
    parts = [b["name"], b["key"], b["sub"]]
    for a in b.get("aliases", ()):
        parts += [a, a.replace("-", " "), a.replace("-", "")]
    return " ".join(dict.fromkeys(p.lower() for p in parts if p))


def software_shown(raw):
    """A board's software as a reader sees it (site 1.3.8, Rob: "why are we
    not saying the right unleashed on the site"). This firmware announces
    itself as "unleashed", in ASCII, because the protocol value is an
    identifier; a person reads the name, which has a micro sign. Only the
    display changes: the database, the API and every comparison keep the
    raw value, and any other program's name is shown as it sent it."""
    raw = raw or ""
    return "µnleashed" if raw.strip().lower() == "unleashed" else raw


def update_for(r, latest):
    """The newer release a board could move to, or "". Only µnleashed
    boards: nothing here knows what another program's newest version is.
    Nothing for a board on the newest release or newer, or one whose
    version is not a version."""
    if (r["software"] or "").strip().lower() != "unleashed":
        return ""
    have, want = version_key(r["version"]), version_key(latest)
    if have is None or want is None or have >= want:
        return ""
    return latest


def update_link(have, newer):
    """The arrow on a behind board's software badge: a link to /upgrade, with
    the badge tooltip saying from which version to which. Plain text in,
    escaped here once for both attributes that carry it."""
    t = html.escape(f"Update available: {have} → {newer}. Plug it in and use "
                    "Update my board on /install.", quote=True)
    return (f'<a class="bu" href="https://unleashedbbs.com/upgrade" aria-label="{t}" data-tip="{t}">'
            + UP_ARROW + "</a>")


def badge(cls, content, tip):
    """One badge. content is markup, already escaped; tip is plain text and
    is escaped here, once, for both of the attributes that carry it."""
    t = html.escape(tip, quote=True)
    return (f'<span class="bd k-{cls}" role="img" tabindex="0" aria-label="{t}" '
            f'data-tip="{t}">{content}</span>')


def day_text(when):
    """A date the way a person writes it: 3 Mar 2025."""
    t = time.gmtime(when)
    return f"{t.tm_mday} {time.strftime('%b %Y', t)}"


def listed_at(r):
    """When a board first went public, or when it was first heard from, for
    a row from before public_at existed."""
    return r["public_at"] or r["first_seen"]


def row_keys(r, now, steady=False, latest=""):
    """Every badge a board carries, as the keys the filter uses: what it
    sent, what the directory worked out, and every step of time listed it
    has reached, so "listed a year" finds a board listed for two. A board's
    row carries these, and the filter matches on them, on the server and in
    the browser alike. latest is the newest release on /install, for
    "update"."""
    keys = set(unpick(r["features"]))
    if "petscii" in unpick(r["terminals"]):
        keys.add("petscii")
    if r["guests"] == 1:
        keys.add("guests")
    age = now - listed_at(r)
    if age < NEW_DAYS * 86400:
        keys.add("new")
    if steady:
        keys.add("steady")
    if update_for(r, latest):
        keys.add("update")
    keys.update(label for days, label, _w in AGES if age >= days * 86400)
    if row_sd(r):
        keys.add("sd")
    keys.update(row_support(r))
    keys.update(row_interests(r))
    return keys


def row_sd(r):
    """The SD card's size in GB a board's row carries, or None (site 1.1.0).
    A row made before the column existed, or a test's own dict without it,
    has none."""
    try:
        sd = r["sd"]
    except (KeyError, IndexError):
        return None
    return sd if isinstance(sd, int) and 1 <= sd <= SD_MAX else None


def row_closed(r):
    """Whether a board's last heartbeat said its sysop has closed it (site
    1.3.10). A row made before the column existed, or a test's own dict
    without it, is open."""
    try:
        return r["closed"] == 1
    except (KeyError, IndexError):
        return False


def shut_now(r):
    """Closed and up: the board is answering heartbeats and turning callers
    away. A closed board that stops heartbeating is quiet like any other,
    and the stale and delisting rules take it from there."""
    return r["state"] == "online" and row_closed(r)


def row_support(r):
    """The causes a board's row carries, as codes, in the directory's order.
    A stored word is read through the aliases, so a row written with the
    long slugs before site 1.1.0 shows the same causes with no migration.
    A code stored in the support column before it moved to the interests
    (ham, site 0.22.2) is left out here and read by row_interests()."""
    got = {SUPPORT_ALIAS.get(norm_word(s)) for s in unpick(r["support"])}
    return [c for c in SUPPORT_CODES if c in got]


def row_interests(r):
    """The interests a board's row carries, as codes, in the directory's
    order, read through the aliases as row_support() does, with any code
    that moved there from support and was stored before it did. Reading
    them this way needs no migration: every heartbeat rewrites both columns
    anyway."""
    got = {INTEREST_ALIAS.get(norm_word(s)) for s in unpick(r["interests"])}
    got.update(c for c in (INTEREST_ALIAS.get(norm_word(s)) for s in unpick(r["support"]))
               if c in SUPPORT_MOVED)
    return [c for c in INTEREST_CODES if c in got]


def board_badges(r, now, steady=False, latest=""):
    """The badges under one board's name, or "" for a board with none.

    Two rows (site 1.0.0). The first is what the board is: its software and
    version, with the update arrow when it is behind, then the machine it
    runs on. The second is the small badges in ROW_ORDER, the same places
    on every row. A board with nothing for a row has no row, not an empty
    one."""
    keys = row_keys(r, now, steady, latest)
    since = listed_at(r)
    age = now - since
    ident, marks = [], []
    if r["software"]:
        what = software_shown(r["software"]) + (" " + r["version"] if r["version"] else "")
        ident.append(badge("soft", html.escape(what),
                           f"Software: {what}, as the board reports it."))
        newer = update_for(r, latest)
        if newer:
            ident.append(update_link(r["version"], newer))
    if r["system"]:
        ident.append(badge("sys", html.escape(r["system"]),
                           f"Runs on: {r['system']}, in the board's own words."))
    for key in ROW_ORDER:
        if key == "sd" and key in keys:
            # The card's size on the badge itself, SD32 (site 1.1.0).
            sd = row_sd(r)
            marks.append(badge("feat", f"SD{sd}",
                               f"SD card: {sd} GB, in use on the board now."))
        elif key in keys:
            b = BADGE_BY_KEY[key]
            marks.append(badge(b["cls"], badge_symbol(b), b["tip"]))
    # One chip for the whole of time listed: the highest step reached.
    for days, label, words in AGES:
        if age >= days * 86400:
            marks.append(badge("age", label, f"Listed {words}: on this directory "
                                             f"since {day_text(since)}."))
            break
    for b in ROW_SUPPORT + ROW_INTERESTS:
        if b["key"] in keys:
            marks.append(badge(b["cls"], badge_symbol(b), b["tip"] + " Chosen by the sysop."))
    rows = ""
    if ident:
        rows += '<span class="bid">' + "".join(ident) + "</span>"
    if marks:
        rows += '<span class="bset">' + "".join(marks) + "</span>"
    return '<span class="badges">' + rows + "</span>" if rows else ""


def legend_html(lines):
    """One group of /badges: its heading, the Markdown under it, and a table
    of its badges, each row the symbol, the name, what a board sends (a
    code, for a cause or an interest) and what it means. The first line of
    the block names the group; the rest is prose.

    Every row carries what a search matches it on, and the section, like
    each sub-group of interests, is marked as a group, so the script can
    hide a group that has nothing left in it. Without the script every row
    is shown."""
    lines = list(lines)
    which = ""
    while lines and not which:
        which = lines.pop(0).strip()
    titles = dict(BADGE_GROUPS)
    if which not in titles:
        return "<p>" + html.escape("badges: " + which) + "</p>"
    prose = md_render("\n".join(lines)) if any(l.strip() for l in lines) else ""

    def row(chips, b, name, means, words):
        colour = BADGE_COLOURS.get(b["cls"]) if b["cls"] not in ("sup", "int") else ""
        cn = f' <span class="cn k-{b["cls"]}">{colour}</span>' if colour else ""
        return (f'<tr data-k="{html.escape(words, quote=True)}">'
                f'<td class="bsym"><span class="chips">{chips}</span></td>'
                f'<td class="bn"><b>{html.escape(name)}</b>{cn}</td>'
                f'<td class="bs">{b["sent"]}</td>'
                f'<td class="bm">{means}</td></tr>')

    def rows(items):
        out, ages = [], [b for b in items if b["cls"] == "age"]
        for b in items:
            if b["cls"] == "age":
                if b is not ages[0]:
                    continue
                chips = "".join(badge("age", a["sym"], a["tip"]) for a in ages)
                out.append(row(chips, b, "Listed",
                               "How long the board has been on this directory: a "
                               "month, six months, then one, two, five and ten "
                               "years. Only the highest reached is shown.",
                               "listed time listed age " + " ".join(a["key"] for a in ages)))
                continue
            chips = badge(b["cls"], badge_symbol(b), b["tip"])
            means = html.escape(b["means"])
            if b["key"] == "steady":
                means += ' <a href="#how-steady-is-worked-out">How</a>.'
            elif b["key"] == "camera":
                means += ' <a href="/docs/camera">How a caller uses it</a>.'
            out.append(row(chips, b, b["name"], means, badge_words(b)))
        return "".join(out)

    # The third column is what a board sends. For a cause or an interest
    # that is its code, upper case (site 1.1.0); for the rest, the field.
    third = "Code" if which in ("support", "interests") else "Sent as"
    head = ('<thead><tr><th scope="col">Badge</th><th scope="col">Name</th>'
            f'<th scope="col">{third}</th><th scope="col">Meaning</th></tr></thead>')
    items = [b for b in BADGES if b["group"] == which]
    if which == "interests":
        body = "".join(
            f'<tbody data-g><tr class="sub"><th colspan="4" scope="rowgroup">'
            f"{html.escape(sub)}</th></tr>"
            + rows([b for b in items if b["sub"] == sub]) + "</tbody>"
            for sub in INTEREST_GROUPS)
    else:
        body = "<tbody>" + rows(items) + "</tbody>"
    return ('<section class="bgroup" data-g>'
            + md_render("## " + titles[which]) + prose
            + f'<table class="btab {html.escape(which)}">' + head + body
            + "</table></section>")


def badge_find_html():
    """The search at the top of /badges, and the page's script. Hidden until
    the script shows it: without the script it could not do anything, and
    every row is on the page anyway."""
    return ('<p class="findbar" data-js hidden><label for="bq">Find a badge</label>'
            '<input type="search" id="bq" data-find="article" data-count="bqn"'
            ' data-noun="badges" autocomplete="off" spellcheck="false"'
            ' placeholder="retro, radio, chat">'
            '<span class="fqn" id="bqn" aria-live="polite"></span></p>'
            + BADGE_JS)


# The directory's own ":::" blocks (see sitekit.BLOCKS): the key to
# the badges on /badges, one group at a time, and the search above it.
BLOCKS.update({
    "badges": legend_html,
    "badgefind": lambda lines: badge_find_html(),
})


TERMINAL_NAMES = {"ansi": "ANSI", "utf8": "UTF-8", "petscii": "PETSCII",
                  "ascii": "ASCII", "vt100": "VT100"}


def about_lines(r):
    """What a board sent about itself, as plain lines of words, for the feed,
    which has no badges and no tooltips. Plain text: the caller escapes."""
    lines = []
    if r["software"]:
        lines.append("Software: " + software_shown(r["software"])
                     + (" " + r["version"] if r["version"] else ""))
    if r["system"]:
        lines.append(f"Runs on: {r['system']}")
    terms = [TERMINAL_NAMES[t] for t in unpick(r["terminals"]) if t in TERMINAL_NAMES]
    if terms:
        lines.append("Speaks: " + ", ".join(terms))
    if r["guests"] == 1:
        lines.append("Guests welcome")
    elif r["guests"] == 0:
        lines.append("No guests: an account is needed")
    if unpick(r["features"]):
        lines.append("Running: " + ", ".join(unpick(r["features"])))
    if row_sd(r):
        lines.append(f"SD card: {row_sd(r)} GB")
    # In the page's order; the words are the ones the tooltip uses.
    chosen = set(row_support(r))
    said = {code: _uncap(name) for code, name, _s in SUPPORT}
    names = [said[b["key"]] for b in BADGES
             if b["group"] == "support" and b["key"] in chosen]
    if names:
        lines.append("Supports: " + ", ".join(names))
    chosen = set(row_interests(r))
    names = [b["name"] for b in BADGES if b["group"] == "interests" and b["key"] in chosen]
    if names:
        lines.append("Interests: " + ", ".join(names))
    return lines


def board_json(r, steady):
    """One board as /api/boards.json gives it. The same fields it always
    had, in the same names, then what the badges are made of: the fields a
    board sent, as lists and a true, false or null rather than the stored
    text, and the two the directory works out. Named field by field rather
    than the whole row, so the token and the moderator's note can never
    leak into it by somebody adding a column."""
    out = {k: r[k] for k in ("name", "owner", "description", "host", "address",
                             "port", "nodes", "busy", "state", "calls24",
                             "minutes24", "streak_start", "last_seen")}
    # What it runs, as the board said (site 1.0.0: the badge shows the
    # version now, so the data says it too).
    out["software"]  = r["software"]
    out["version"]   = r["version"]
    out["system"]    = r["system"]
    out["terminals"] = unpick(r["terminals"])
    out["guests"]    = None if r["guests"] is None else bool(r["guests"])
    out["features"]  = unpick(r["features"])
    # The card's size in GB, or null (site 1.1.0).
    out["sd"]        = row_sd(r)
    # Closed by its sysop, as its last heartbeat said: true or false, never
    # null (site 1.3.10). A quiet board keeps what it last said; state says
    # whether it is still answering.
    out["closed"]    = row_closed(r)
    # Codes, lower case (site 1.1.0), whatever the row was stored with.
    out["support"]   = row_support(r)
    out["interests"] = row_interests(r)
    out["listed_at"] = listed_at(r)
    out["steady"]    = bool(steady)
    return out


def board_matches(keys, sel, any_=False):
    """Whether a board with these badge keys passes the filter: all of the
    chosen badges, or any of them, and every board when none are chosen."""
    if not sel:
        return True
    return any(k in keys for k in sel) if any_ else all(k in keys for k in sel)


def board_rows(rows, now, charts=None, steady=None, sel=(), any_=False, latest=""):
    out = []
    for r in rows:
        # The badges this board carries, for the filter, in the page's order.
        # Every row is sent whatever the filter says, and the ones it leaves
        # out are hidden: that is what lets the script show them again the
        # moment a chip is let go, with no trip back here.
        keys = row_keys(r, now, r["id"] in (steady or ()), latest)
        carried = " ".join(k for k in FILTER_KEYS if k in keys)
        tr = (f'<tr data-b="{html.escape(carried, quote=True)}"'
              + ("" if board_matches(keys, sel, any_) else " hidden") + ">")
        where = r["host"] or r["address"]
        state = r["state"]
        seen = now - r["last_seen"]
        shut = shut_now(r)
        if shut:
            # Closed by its sysop (site 1.3.10): up, and turning callers
            # away. It says so where the callers-on figure would be, and
            # that figure is not shown: a sysop setting the board up can be
            # on it, and "1 of 10 on" reads as an invitation.
            label = "Temporarily closed"
            klass = "closed"
        elif state == "online":
            # Somebody actually being on is the thing worth seeing from across
            # the room, so it gets the bright colour and a board that is up but
            # empty does not.
            if r["nodes"]:
                label = f"{r['busy']} of {r['nodes']} on"
            else:
                label = "up"
            klass = "on" if r["busy"] else "idle"
        elif state == "offline":
            label = f"quiet, {human_ago(seen)}"
            klass = "off"
        else:
            label = state
            klass = "pending"

        # Every figure in this row came from that board's last heartbeat, so
        # say how old the reading is rather than implying it is live. A board
        # reporting every ten minutes cannot be more current than that, and
        # pretending otherwise is the sort of thing this directory is against.
        fresh = (f"<span class='fresh'>{human_short(seen)}</span>"
                 if state == "online" else "")

        # Two deliberate lines rather than one that wraps wherever it lands.
        # "233 calls" is 9 characters and "67h 01m connected" is 17, so the
        # column holds both, and "67h" never ends up on a different line
        # from "01m". A figure split across a line break is two numbers.
        if r["minutes24"] is not None:
            mins = int(r["minutes24"])
            spent = f"{mins // 60}h {mins % 60:02d}m" if mins >= 60 else f"{mins}m"
            if r["calls24"] is not None:
                activity = (f"{r['calls24']} calls", f"{spent} connected")
            else:
                activity = (f"{spent} connected",)
        elif r["calls24"] is not None:
            activity = (f"{r['calls24']} calls",)
        else:
            activity = ()
        act_html = "<br>".join(html.escape(part) for part in activity)

        # An IPv6 literal needs brackets or its own colons run into the port.
        # No listed board hits this today, and pages/dialing.md already
        # brackets correctly in the PowerShell handler it documents, so the
        # site was explaining a URL shape it did not emit.
        target = f"[{where}]" if ":" in where else where
        dial = html.escape(f"telnet://{target}:{r['port']}", quote=True)
        # Three columns, not six. Six of them wrapped at the sizes Rob reads
        # the page at, and a column that wraps is not carrying its own
        # weight: Sysop held one short name and Up-for held one short
        # figure, while the two fields anybody actually scans, Board and
        # State, were squeezed between them. So the fields that belong to a
        # board's identity stack under its name, and the fields that answer
        # "what is it doing" stack under its state.
        #
        # Each stacked line says what it is. A column heading is what used
        # to tell a reader that "Rob" was the sysop and "3d" was an uptime,
        # and stacking them without that would leave three lines in a cell
        # that only read correctly to somebody who remembered the old
        # layout. The labels are --faint and the values keep their own
        # colours, which is the same treatment the phone layout already
        # used for exactly this reason.
        #
        # State stays the first line of its cell, and cells are top
        # aligned, so it still runs straight down the page for somebody
        # scanning for a board with callers on it. That is the one thing a
        # table is for and it is the one thing the restructure had to keep.
        who_runs = (f"<span class='owner'><span class='lbl'>sysop</span> "
                    f"{html.escape(r['owner'])}</span>" if r["owner"] else "")
        act_line = (f"<span class='act'>{act_html}</span>" if activity else
                    "<span class='muted'><span class='lbl'>24h</span> "
                    "not shared</span>")
        # The name on a line of its own, in a box exactly as wide as the
        # name, because that box is what the hover dot flies along. Then the
        # badges, which wrap under it rather than beside it, so however many
        # a board has they grow the row downwards and never push the Dial
        # column: the software badge that used to sit beside the name is one
        # of them.
        out.append(
            tr
            + f"<td class='name' data-label='Board'><span class='bname'>"
            f"{html.escape(r['name'])}</span>"
            + board_badges(r, now, r["id"] in (steady or ()), latest)
            + f"<span class='desc'>{html.escape(r['description'])}</span>"
            + who_runs
            + ((charts or {}).get(r["id"]) or "")
            + "</td>"
            + "<td class='addr' data-label='Address'>"
            + (
                # Closed: the address as words, not a telnet:// link. It is
                # still the board's address, but nothing here should ask a
                # reader to dial a board that will only say it is closed.
                f"<span class='nodial'>{html.escape(where)} {r['port']}</span>"
                if shut else
                f"<a href='{dial}' "
                f"title='Opens your terminal program, if one is registered for "
                f"telnet:// links.'>"
                f"{html.escape(where)} {r['port']}</a>")
            + "</td><td class='status' data-label='State'>"
            + (f"<span class='state closed'><span class='shut'>"
               f"{html.escape(label)}</span> {fresh}</span>" if shut else
               f"<span class='state {klass}'>{html.escape(label)} {fresh}</span>")
            + act_line
            + "<span class='upfor'><span class='lbl'>up for</span> "
            + human_streak(now - r["streak_start"]) + "</span>"
            + "</td>"
            + "</tr>")
    return "".join(out)


# --------------------------------------------------------------------------
# The announcement banner.
#
# One slim line above the board list's heading, in yellow: news, not a
# warning and not an invitation. It must not go live early, and it does not
# depend on anybody remembering to switch it on: it shows only when
# firmware_releases() finds a release at or above BANNER_FROM on disk, which
# is the moment the installer can actually deliver one. With no release, or
# only older ones, or an empty ANNOUNCEMENT, it renders nothing at all, and
# its margin goes with it, so there is no gap where it would have been.
# --------------------------------------------------------------------------
BANNER_FROM = (1, 0, 0)

# The announcement itself, and the one place to change it. It is the page
# dialect's inline Markdown, so the link is [words](/path) and **bold**
# works; "{version}" becomes the newest release on disk, so it stays true
# after a patch release lands. One sentence and one link: it has to fit one
# line on a monitor and two on a phone. "" switches the banner off.
ANNOUNCEMENT = ("\u00b5nleashed BBS {version} is out. "
                "[Install it from your browser.](https://unleashedbbs.com/install)")


def announcement_banner():
    """The announcement banner, or "" when there is nothing to announce."""
    if not ANNOUNCEMENT.strip():
        return ""
    rels = firmware_releases()
    if not rels or rels[0]["sort"] < BANNER_FROM:
        return ""
    # md_inline escapes first, so the version goes in before it does.
    words = md_inline(ANNOUNCEMENT.replace("{version}", rels[0]["version"]))
    return '<div class="banner" role="note"><p>' + words + "</p></div>"


# --------------------------------------------------------------------------
# The directory's figures, as one sentence under its heading.
#
# "3 communities listed, with 5 people connected right now." (site 1.3.0,
# plain words; it was "Unleashed is hosting 3 boards with 5 callers on
# right now".) The communities are every listed board, up or quiet, the
# same count as the page's description; the people are the sum of the
# callers-on figure the table shows for each board that is up. Nothing here
# reaches the JSON or the feed, which keep their own figures.
#
# STAT_SUFFIX goes on the end of the sentence, before its full stop, for
# the day there is something true to add. It is empty on purpose: "across
# the globe" was asked for and left out, because the directory knows
# nothing about where a board is, and with one board listed it would read
# as a boast about nothing.
# --------------------------------------------------------------------------
STAT_SUFFIX = ""


def stat_line(boards, callers):
    """The sentence under the heading, with the two figures in --live."""
    if not boards:
        return '<p class="stat">No communities listed yet.</p>'
    b = (f"<span class='n'>{boards:,}</span> "
         f"communit{'y' if boards == 1 else 'ies'} listed")
    c = ("nobody connected" if not callers else
         f"<span class='n'>{callers:,}</span> "
         f"{'person' if callers == 1 else 'people'} connected")
    return (f'<p class="stat">{b}, with {c} right now'
            + html.escape(STAT_SUFFIX) + ".</p>")


# --------------------------------------------------------------------------
# The filter over the board list (site 0.22.0, Rob: "allow filtering on the
# website based on a badge bento grid that you can select and get a filter.
# I dont want the iconography to show up unless you click a filter button").
#
# A small Filter button above the table and, only while something is
# chosen, one line saying what. The button is a <details>, so the pane
# opens with no script at all; the pane is a GET form of checkboxes, so
# with no script "Show boards" asks the server, which filters on ?b=petscii
# &b=ham and hands back a page that is the filtered list. That makes every
# filtered view a URL that can be shared or bookmarked.
#
# With the script (BADGE_JS) a chip filters the moment it is pressed and the
# URL follows with history.replaceState. Every row is always sent, the ones
# left out marked hidden, so letting go of a chip brings rows back without
# a round trip. The badges' symbols are drawn only inside the pane: closed,
# the page shows no iconography that it did not show before.
#
# Site 0.22.2 condensed it (Rob: "the filter page is unmanageable, it needs
# HUGE condensing ... the hover works, just put em in groups"): the bento of
# labelled tiles became a row per group of small chips, the names in the
# tooltip, the interests' rows two to a line on a desktop. It went from
# about two screens at 1366 x 768 to less than one.
# --------------------------------------------------------------------------
# How many query parameters are read at most. There are fewer badges than
# this; anything past it is somebody seeing what happens.
FILTER_MAX_PARAMS = 100


def filter_query(query):
    """The badges chosen in a query string, in the page's order, and whether
    any of them will do rather than all. Anything that is not a badge this
    directory knows is ignored, so nothing a reader typed into the URL is
    ever put back on the page. A cause or an interest may be named by its
    code in any case or by any of its aliases (site 1.1.0), so a link
    shared with ?b=electronics still finds the boards that are ELCTR now."""
    chosen, any_ = set(), False
    for part in (query or "").split("&")[:FILTER_MAX_PARAMS]:
        name, _eq, value = part.partition("=")
        name = urllib.parse.unquote_plus(name)
        value = urllib.parse.unquote_plus(value).strip().lower()
        if name == "b":
            chosen.add(FILTER_ALIAS.get(norm_word(value), value))
        elif name == "m":
            any_ = value == "any"
    return tuple(k for k in FILTER_KEYS if k in chosen), any_


def filter_chip(b, on):
    """One chip in the filter (site 0.22.2): a checkbox nobody sees, over the
    badge's symbol and nothing else. The name is the checkbox's accessible
    name and is in the tooltip, on hover and on focus; it is not printed
    under the symbol, which is what made the 0.22.0 pane a wall of tiles.
    Chosen is a ring and a notch in the corner, not only a colour; focused
    is the yellow ring every control here gets."""
    name = html.escape(b["name"], quote=True)
    tip = f"{b['name']} or more." if b["cls"] == "age" else b["tip"]
    if b["group"] in ("support", "interests"):
        # The code a sysop would type, upper case, as /badges shows it
        # (site 1.1.0).
        tip += f" Code {b['key'].upper()}."
    return (f'<label class="chip" data-k="{html.escape(badge_words(b), quote=True)}">'
            f'<input type="checkbox" name="b" value="{html.escape(b["key"], quote=True)}"'
            f' data-n="{name}" aria-label="{name}"' + (" checked" if on else "")
            + f'><span class="cb k-{b["cls"]}" data-tip="{html.escape(tip, quote=True)}">'
            f"{badge_symbol(b)}</span></label>")


def filter_row(title, items, chosen, cls="fr"):
    """One group of the filter as a row: its name, then its chips. A
    <details>, open, so a phone can fold a group down to its heading with a
    tap and no script; checkboxes in a folded group are still in the form."""
    return (f'<details class="{cls}" data-g open><summary>{html.escape(title)}</summary>'
            '<div class="chips">'
            + "".join(filter_chip(b, b["key"] in chosen) for b in items)
            + "</div></details>")


# What the pane calls each group; /badges uses the longer headings.
FILTER_TITLES = {"board": "Sent by the board", "directory": "Worked out here",
                 "support": "Support", "interests": "Interests"}


def filter_bar_html(sel, any_, shown, total, go=False, q=""):
    """The Filter button, its pane, the line saying what is chosen, and the
    key to the badges, for the top of the board list.

    Every filter lands on /directory (site 1.2.8). On the front page, which
    shows only the busiest ten, go is true: the form is marked data-go so
    the script leaves it alone, and "Show boards" takes the reader to the
    full list with those badges chosen, rather than narrowing ten rows. On
    /directory the chips filter live, and q, the name search, rides along
    in the form (its box sits outside the pane, tied to it by form=) so a
    search and a filter always travel together."""
    chosen = set(sel)
    clear = "/directory" + ("?q=" + urllib.parse.quote_plus(q) if q else "")
    clear = html.escape(clear, quote=True)
    groups = []
    for group, _heading in BADGE_GROUPS:
        items = [b for b in BADGES if b["group"] == group and b["filter"]]
        if group == "interests":
            # A heading over the interests' own rows, which sit two to a
            # line on a desktop. The wrapper is a group too, so a search
            # that leaves no interest hides the heading with them.
            groups.append(
                f'<div class="fint" data-g><p class="fh">{FILTER_TITLES[group]}</p>'
                '<div class="fsub">'
                + "".join(filter_row(sub, [b for b in items if b["sub"] == sub],
                                     chosen, "fr sub")
                          for sub in INTEREST_GROUPS)
                + "</div></div>")
        else:
            groups.append(filter_row(FILTER_TITLES[group], items, chosen))
    names = ", ".join(BADGE_BY_KEY[k]["name"] for k in sel)
    plural = "" if total == 1 else "s"
    mode = ("any" if any_ else "all")
    radios = "".join(
        f'<label><input type="radio" name="m" value="{v}"'
        + (" checked" if v == mode else "") + f"><span>{v} of them</span></label>"
        for v in ("all", "any"))
    return ('<div class="fbar">'
            '<details class="filter" id="filter"><summary>Filter'
            f'<span class="fc" id="fcount">{len(sel) or ""}</span></summary>'
            '<form class="fpane" id="fform" method="get" action="/directory"'
            + (" data-go" if go else "")
            + ' aria-label="Filter the boards by badge">'
            '<div class="ftop">'
            '<p class="findbar" data-js hidden><label for="fq">Find a badge</label>'
            '<input type="search" id="fq" data-find="#fgrid" data-count="fqn"'
            ' data-noun="badges" autocomplete="off" spellcheck="false"'
            ' placeholder="retro, radio, chat">'
            '<span class="fqn" id="fqn" aria-live="polite"></span></p>'
            '<fieldset class="fmode"><legend>Boards with</legend>' + radios
            + "</fieldset></div>"
            '<div class="frows" id="fgrid">' + "".join(groups) + "</div>"
            '<p class="fgo"><button type="submit">Show boards</button>'
            f'<a href="{clear}" data-clear>Clear all</a></p>'
            "</form></details>"
            '<p class="keylink"><a href="/badges">What the badges mean</a></p>'
            f'<p class="factive" id="factive" aria-live="polite"{"" if sel else " hidden"}>'
            f'<span data-f="n">{shown} of {total} board{plural}</span> with '
            f'<span data-f="m">{mode} of</span>: '
            f'<span data-f="l">{html.escape(names)}</span>. '
            f'<a href="{clear}" data-clear>Clear</a></p>'
            "</div>")


def index_data():
    """What the board list is drawn from, read once per PAGE_CACHE seconds
    however many filtered views are asked for: the rows, their day charts
    and which of them are steady."""
    now = int(time.time())
    with db() as con:
        settle(con, now)                               # keep the list honest on read
        rows = con.execute(
            "SELECT * FROM boards WHERE state IN ('online','offline') "
            # Up first, and of those the ones taking calls: a closed board
            # (site 1.3.10) is not active whatever its figures say, so it
            # follows every open board that is up, busiest or not, and
            # comes before the quiet ones. Quiet is quiet, closed or not.
            "ORDER BY state='online' DESC, (state='online' AND closed=1) ASC, "
            "COALESCE(minutes24, busy * 60, 0) DESC, streak_start ASC, "
            "name COLLATE NOCASE ASC").fetchall()
        charts = {}
        for r in rows:
            hours = hours_for(con, r["id"])
            if hours:
                charts[r["id"]] = chart_html(hours)
        steady = steady_boards(con, rows, now)
    return now, rows, charts, steady


# The name search on /directory (site 1.2.8): a GET form, answered here.
# What a reader types is cut to SEARCH_MAX characters after control and
# format characters are dropped and runs of spaces are closed up, and it is
# only ever put back on the page escaped.
SEARCH_MAX = 60


def search_query(query):
    """The name search in a query string, cleaned and cut to SEARCH_MAX, or
    "" for none. The first q wins."""
    for part in (query or "").split("&")[:FILTER_MAX_PARAMS]:
        name, _eq, value = part.partition("=")
        if urllib.parse.unquote_plus(name) != "q":
            continue
        text = urllib.parse.unquote_plus(value)
        text = "".join(c for c in text if unicodedata.category(c)[0] != "C")
        return " ".join(text.split())[:SEARCH_MAX].strip()
    return ""


def board_found(r, q):
    """Whether a board answers a search: q anywhere in its name, its sysop's
    name or its description, in any case."""
    needle = q.casefold()
    return any(needle in (r[k] or "").casefold()
               for k in ("name", "owner", "description"))


def list_html(rows, now, charts, steady, sel=(), any_=False, go=False, q="", say=""):
    """The filter over the board list and the table under it, for the front
    page (go: its chips go to /directory) and for /directory itself.

    The filter and the key to the badges sit small and right above the
    table, where somebody wondering what "Fi" means is already looking. Not
    in the table's header row, which a phone does not show. When nothing
    passes the filter the table is hidden and a sentence says so, rather
    than a header over nothing."""
    latest = newest_release()
    shown = sum(1 for r in rows
                if board_matches(row_keys(r, now, r["id"] in steady, latest), sel, any_))
    return (filter_bar_html(sel, any_, shown, len(rows), go, q)
            + (f'<p class="topn">{say}</p>' if say else "")
            + '<table id="boards"' + ("" if shown else " hidden") + ">"
            "<tr><th>Board</th><th>Address</th><th>State</th></tr>"
            + board_rows(rows, now, charts, steady, sel, any_, latest) + "</table>"
            + '<p class="none" id="fnone"' + (" hidden" if shown else "") + ">"
            + f"No board with {'any' if any_ else 'all'} of those yet.</p>")


# Under both lists: what the figures on a row mean. Five clauses and sixty
# words with no break, and it is the only place that says what the 24 hour
# figures and "up for" mean. Three lines, one idea each.
LIST_FOOT = ("The 24 hour figures under a board's state are how many calls it "
             "took and how long callers were connected in total.<br>"
             "Caller counts and activity are reported by the boards themselves. "
             "The small figure next to the state is how old that reading is.<br>"
             '"Up for" is measured here and cannot be fudged.')


# The one step between "Try one first" and a board (site 1.3.0): joining
# needs an app, and nothing on a phone or a computer opens a board by
# itself. The apps are /terminals' picks, checked on their stores on
# 2026-09-25: TERMinator (Phil Whittemore) on Google Play and on the App
# Store, free on the App Store; MuffinTerm (Molly Black), free on the App
# Store for iPhone, iPad and Mac; SyncTERM, free software, for Windows,
# macOS and Linux. Termius (site 1.3.1, Rob's own on Android), checked on
# 2026-09-25: termius.com/pricing lists Telnet in every plan, the free
# Starter included, and its App Store listing says the free plan connects
# "with SSH, Mosh, Telnet, Port Forwarding, and SFTP"; termius.com/download
# offers Android, iPhone, iPad, Windows, macOS and Linux.
JOIN_STEP = ('<div class="joinstep" role="note"><h2>First time? You need a free '
             "app to join</h2><p>" + md_inline(
                 "A BBS is not a web page, so you join one with a [[telnet "
                 "client]], a free app that connects to the board's address. "
                 "On a phone: **TERMinator**, for "
                 "[Android](https://play.google.com/store/apps/details?id=com.terminator.android) "
                 "or [iPhone](https://apps.apple.com/us/app/terminator-bbs-terminal/id6759012939), "
                 "or **MuffinTerm** for "
                 "[iPhone](https://apps.apple.com/us/app/muffinterm/id1583236494). "
                 "**Termius**, free for "
                 "[Android](https://play.google.com/store/apps/details?id=com.server.auditor.ssh.client) "
                 "and [iPhone](https://apps.apple.com/us/app/termius-modern-ssh-client/id549039908), "
                 "works well too. "
                 "On a computer: **[SyncTERM](https://syncterm.bbsdev.net/)**, "
                 "for Windows, macOS and Linux.")
             + '</p><p class="more">' + md_inline(
                 "Then type a board's address and port into the app, or click "
                 "the address if your app is set up for links. "
                 "[Apps for joining](/docs/terminals) has more choices, and "
                 "[First call](/docs/firstcall) what to expect when you connect.")
             + "</p></div>")


def directory_page(sel=(), any_=False, q="", data=None):
    """/directory (site 1.2.8, Rob: "a new page which is purely the search
    and directory"): every listed board, the name search and the badge
    filter, and nothing else. sel and any_ are the filter, q the search.
    With none of them it is the same for everybody and cached whole."""
    now, rows, charts, steady = data or index_data()
    # Up and taking calls. A closed board (site 1.3.10) is listed and
    # counted as a community, but its callers-on figure is not added to
    # the people connected, and it is not one of the communities online.
    live = [r for r in rows if r["state"] == "online" and not row_closed(r)]
    on = sum(r["busy"] or 0 for r in live)
    found = [r for r in rows if board_found(r, q)] if q else rows
    qe = html.escape(q, quote=True)
    head = (head_html("list", "/directory")
            + announcement_banner()
            + "<h1>Communities online</h1>"
            + stat_line(len(rows), on)
            + '<p class="lead">Every community board listed here, the busiest '
            'first. Pick one and connect. <a href="/docs/dialing">Did not '
            'connect?</a></p>'
            + JOIN_STEP)
    if not rows:
        body = "<p class='none'>No boards listed yet. Yours could be the first.</p>"
    else:
        # The box sits outside the filter's pane, so it is on the screen
        # without opening anything, and belongs to the pane's form by its
        # form attribute, so a search keeps the badges chosen and the
        # badges keep the search.
        box = ('<div class="findbar bsearch" role="search">'
               '<label for="nq">Find a board</label>'
               f'<input type="search" id="nq" name="q" form="fform" value="{qe}"'
               f' maxlength="{SEARCH_MAX}" autocomplete="off" spellcheck="false"'
               ' placeholder="name, host or description">'
               '<button type="submit" form="fform">Search</button></div>')
        if q:
            keep = "".join("&b=" + urllib.parse.quote_plus(k) for k in sel)
            keep += "&m=any" if any_ and sel else ""
            clear = html.escape("/directory" + ("?" + keep[1:] if keep else ""), quote=True)
            n = len(found)
            said = (f"No board matches &ldquo;{qe}&rdquo;." if not n else
                    f"{n:,} board{' matches' if n == 1 else 's match'} &ldquo;{qe}&rdquo;.")
            box += (f'<p class="qline" aria-live="polite">{said} '
                    f'<a href="{clear}">Clear the search</a></p>')
        if found:
            body = box + list_html(found, now, charts, steady, sel, any_, q=q) + BADGE_JS
        else:
            # No table at all: the filter is still there, and with nothing
            # to narrow, its chips go to the server with the search.
            body = (box + filter_bar_html(sel, any_, 0, 0, q=q) + BADGE_JS)
    n, up = len(rows), len(live)
    desc = (f"{up:,} communit{'y' if up == 1 else 'ies'} online and {on:,} "
            f"{'person' if on == 1 else 'people'} connected right now. Visit "
            "one with a free app on your computer or phone.")
    return PAGE.format(title=html.escape(f"Communities online - {SITE_NAME}"),
                       desc=html.escape(desc, quote=True),
                       body=head + body, footer=foot_html("list", LIST_FOOT),
                       refresh=LIST_REFRESH, head="")


def rss_date(when):
    """RFC 822, which is what RSS wants."""
    return time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime(when))


def feed_xml():
    """New boards, as RSS.

    A feed is the privacy-forward way to follow something: the reader pulls
    when it likes, there is no account, no email address, nothing to
    unsubscribe from and nothing here that knows who is reading. It carries
    exactly what the public page carries.
    """
    now = int(time.time())
    site = f"https://{LIST_DOMAIN}" if LIST_DOMAIN else SITE_URL
    with db() as con:
        settle(con, now)
        rows = con.execute(
            "SELECT * FROM boards WHERE public_at > 0 "
            "ORDER BY public_at DESC LIMIT 40").fetchall()

    items = []
    for r in rows:
        where = html.escape(f"{r['host'] or r['address']} {r['port']}")
        desc = html.escape(r["description"] or "")
        owner = html.escape(r["owner"] or "")
        if shut_now(r):
            # Closed by its sysop (site 1.3.10): said first, and the address
            # given as an address rather than as something to dial.
            body = (f"{desc}<br>Temporarily closed: not taking calls right now."
                    f"<br>Address: {where}")
        else:
            body = f"{desc}<br>Dial: {where}"
        if owner:
            body += f"<br>Sysop: {owner}"
        # What the board has told us about itself, in words: a feed reader
        # has no badges and no tooltips.
        for line in about_lines(r):
            body += "<br>" + html.escape(line)
        items.append(
            "<item>"
            f"<title>{html.escape(r['name'])}</title>"
            f"<link>{site}/</link>"
            f"<guid isPermaLink=\"false\">board-{r['id']}</guid>"
            f"<pubDate>{rss_date(r['public_at'])}</pubDate>"
            f"<description>{html.escape(body)}</description>"
            "</item>")

    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0"><channel>'
            f"<title>{html.escape(SITE_NAME)}</title>"
            f"<link>{site}/</link>"
            "<description>Bulletin boards as they come online</description>"
            f"<lastBuildDate>{rss_date(now)}</lastBuildDate>"
            "<ttl>60</ttl>"
            + "".join(items) +
            "</channel></rss>")


def data_page():
    """What .net serves: the API, and what is in it."""
    now = int(time.time())
    with db() as con:
        settle(con, now)
        counts = con.execute(
            "SELECT state, COUNT(*) AS n FROM boards GROUP BY state").fetchall()
    tally = {r["state"]: r["n"] for r in counts}
    rows = "".join(
        f"<tr><td>{html.escape(k)}</td><td>{v}</td></tr>"
        for k, v in sorted(tally.items())) or "<tr><td colspan=2>nothing yet</td></tr>"

    return """<h1>Data</h1>
<p class="lead">The directory, machine readable. No key, no signup, no rate limit worth
mentioning. It is a list of hobby BBSes.</p>
<article>

<h2>Right now</h2>
<table><tr><th>State</th><th>Boards</th></tr>""" + rows + """</table>

<h2>Endpoints</h2>
<dl>
<dt><code>GET /api/boards.json</code></dt>
<dd>Every listed board: name, owner, description, where to dial it, how many lines it
has and how many are busy, whether it is up, whether its sysop has closed it for now
(<code>closed</code>, true or false), and how long it has been up. Then what
the <a href="/badges">badges</a> are made of: what the board said it runs and which
version, what it runs on, speaks,
allows and is running, the size of its SD card, what it supports and is into, as
the short codes on the badges page, when it was first listed, and whether it has
been steady this past week. Cached for a few seconds.</dd>
<dt><code>POST /announce</code></dt>
<dd>How a board lists itself. One JSON object, about 200 bytes, repeated every few
minutes. Plain HTTP on purpose: the boards are microcontrollers with no TLS stack.</dd>
<dt><code>GET /health</code></dt>
<dd>Answers <code>ok</code>, for uptime checks.</dd>
</dl>

<h2>What is not in it</h2>
<p>Nothing about callers. Not handles, not addresses, not counts of who did what, not a
word anybody typed. Boards do not send it and this server would drop it if they did.
The activity figures some boards publish are counts of calls and caller-minutes, given
voluntarily by the sysop, and they are marked as self-reported because they are.</p>

<h2>Writing something that lists itself</h2>
<p>The protocol is published and deliberately dull: any software that sends the payload
gets listed, whatever it runs on. It is documented in
<a href="https://github.com/rwmech/unleashed_directory/blob/main/PROTOCOL.md">PROTOCOL.md</a>,
and this whole server is free software, so you can run your own directory instead of
using this one. That is the intended outcome, not a grudging permission.</p>

</article>"""


# <h1> and the lead sit outside the article, matching data_page(). Everything
# below them is inside one, because md_page() wraps its output in an article
# and these two constants did not: /how's one <h2> got the browser default,
# large and bold, instead of the site's small cyan heading, and neither page
# picked up the article paragraph margins or the 1.62 line height. Two pages
# in the menu and the footer looked like they came from a different site.
RULES = """<h1>House rules</h1>
<p class="lead">This is a list of boards. It does not need many rules.</p>
<article>
<ul>
<li><b>No hate.</b> A board whose name or description attacks people for who they are does not get listed here.</li>
<li><b>Be honest about what you are.</b> The description should describe the board.</li>
<li><b>It is public.</b> Everything you send appears on this page. Assume it is read.</li>
<li><b>Get along.</b> That is the whole of it.</li>
</ul>
<p>These rules bind this directory, not you. The protocol is published, the server is
free software, and anyone can run a directory with different rules or none at all.
Taking a board off this list does not take it off the internet, and it was never
meant to.</p>
</article>"""

# Raw, because a backslash at the end of a line inside an ordinary triple
# quoted string is a Python line continuation: it and the newline after it
# were eaten, so the curl example on the page was served as one long line
# with the continuations missing and the following lines still indented as
# if they were there. There are no other escapes in here.
HOW = r"""<h1>How to get listed</h1>
<p class="lead">Your board announces itself. You do not fill in a form. (There
is one other list worth being on, <a href="#the-telnet-bbs-guide">the Telnet
BBS Guide</a>, and that one does have a form.)</p>
@ART_CSS@
<article>
<pre>board_name  = The Rusty Modem

[plugin:announce]
enabled     = yes
owner       = Sparks
description = A BBS on a chip in a shack in Illinois
servers     = http://unleashedbbs.net/announce</pre>
<p>The name is the board's own setting, <code>board_name</code>, at the top of
<code>system.cfg</code> above the first section, and the announce plugin sends
whatever it is. The rest is the plugin's section. On the board itself,
<code>CONFIG board</code> and <code>CONFIG announce</code> are the same settings
as forms.</p>
<p>Any of this directory's names will take a heartbeat, but <code>.net</code> is the
one meant for machines: <code>.com</code> is the list people read and
<code>.org</code> is what the project is for.</p>
<p>Switch it on and wait. A listing becomes public after three hours of
uninterrupted heartbeats, which is what keeps drive-by spam off the page, and
it disappears when the heartbeats stop. <code>ANNOUNCE</code> on your board
shows how long is left.</p>

<aside class="stop">@SKULL@<p><b>Spam earns a lifetime IP ban.</b> Use this
directory to spam and the address it came from is banned from it for good. That
is this directory's policy rather than something the software does: nothing here
detects spam by itself. The ban is applied by hand, by the person who runs the
directory, and it does not expire. It is not worth it.</p></aside>

<p>What a listing may say is in <a href="/rules">the house rules</a>: four of
them, and short.</p>
<h2>Running something else</h2>

<p>Synchronet, Mystic, WWIV, ENiGMA, Citadel, something you wrote yourself in a
weekend: all welcome, all listed the same way, and what you run, with its
version, is shown under your board's name. This is a directory of boards that are up, not a directory of
one program's users. If it were the second thing it would not be worth running.</p>

<p>There is no plugin to install and no account to make. Post this every few
minutes from anything that can make an HTTP request:</p>

<pre>curl -X POST http://unleashedbbs.net/announce \
  -H 'Content-Type: application/json' \
  -d '{"software":"synchronet","version":"3.20",
       "name":"The Rusty Modem","owner":"Sparks",
       "description":"A BBS in a shack in Illinois",
       "host":"bbs.example.com","port":23,
       "nodes":4,"busy":0,"interval":10,
       "token":""}'</pre>

<p>The reply carries an <code>X-Listing-Token</code> header. Keep it and send it
back in <code>token</code> on every later heartbeat: that is what stops somebody
else taking over your entry. Send it whole. It is 32 characters and a fragment of
one will be refused.</p>

<p><b>Badges, if you want them.</b> Seven optional fields put small badges under
your board's name: what it runs on in your own words, what terminals it speaks,
whether guests can look around, what is running, the size of its SD card, the
causes you support and what you are into. Leave them out and nothing changes. In
the same JSON:</p>

<pre>"system":"Compaq 486", "terminals":["ansi","ascii"], "guests":true,
"features":["chat","files"], "sd":32, "support":["ltrcy"],
"interests":["c64","elctr","ham"]</pre>

<p>Causes and interests are short codes, up to six letters and digits each, in
any case: <code>LTRCY</code> is literacy and <code>ELCTR</code> electronics.
What each badge means, with every code, is on <a href="/badges">the badges
page</a>, and the exact rules for each field are in the protocol.</p>

<p><b>The same rules apply to everyone.</b> Three hours of uninterrupted
heartbeats before a listing goes public, and it disappears when the heartbeats
stop. There is no exception for boards running this firmware, and that is the
whole anti-spam design: staying listed costs a machine that keeps running, which
is exactly what a spammer will not do and exactly what a real board does anyway.</p>

<p>The full protocol, including every field and what the directory does with it,
is in <a href="https://github.com/rwmech/unleashed_directory">the server
repository</a>. It is one Python file and you are welcome to run your own.</p>

<h2 id="the-telnet-bbs-guide">List your community on the Telnet BBS Guide too</h2>

<p>The <a href="https://www.telnetbbsguide.com/">Telnet BBS Guide</a> has listed
bulletin boards for more than twenty years, and it is where many people who
enjoy them look for somewhere new to visit. A listing there is free. An
administrator approves each one, so it may not appear straight away.</p>

<ol>
<li>Change the sysop password and <a href="/docs/forward">let people outside your
home join</a> first, the same as before listing here.</li>
<li>Create an account on <a href="https://www.telnetbbsguide.com/">the
Guide</a>.</li>
<li>Check your board is not already there. If it is, use the Guide's
<b>Contact Us</b> button, say you are its sysop, and the admins link it to your
account.</li>
<li>Choose <b>Add Your BBS</b> and fill it in: your board's name, its address
and port (use a name that stays the same, not a home address that changes),
and µnleashed BBS as the software.</li>
<li>Say what your community is about first, and the software second.</li>
</ol>

<p>The Guide's own steps are on its page
<a href="https://www.telnetbbsguide.com/faqs/how-to-add-your-bbs-listing/">How
To Add Your BBS Listing</a>. It also offers its whole list as a download, so a
listing there can travel further than the site itself.</p>
</article>"""


FIRSTCALL_ALT = (
    "Three screens from a first call. The first reads ANSI 80x24 and CP437: the "
    "board has worked out what kind of terminal is calling. The second reads "
    "Handle: with a blinking cursor. The third shows a line from Sparks and a "
    "line from you in the chat room.")

FIRSTCALL_ART = (
    '<svg class="art steps" viewBox="-5 -6 354 130" role="img" '
    'preserveAspectRatio="xMidYMid meet" aria-label="' + FIRSTCALL_ALT + '">'
    + _screen(0,
        '<text class="live p1" x="21" y="26" font-size="9">ANSI 80x24</text>'
        '<text class="p1 p1b" x="21" y="38" font-size="9">CP437</text>'
        '<g class="p1 p1c">'
        '<rect class="c1" x="21" y="45" width="10" height="5" rx="1"/>'
        '<rect class="c2" x="33" y="45" width="10" height="5" rx="1"/>'
        '<rect class="c3" x="45" y="45" width="10" height="5" rx="1"/>'
        '<rect class="c4" x="57" y="45" width="10" height="5" rx="1"/>'
        '</g>')
    + _caption(0, "it works out", "what you are")
    + '<path class="d" d="M109 35 L113 38.5 L109 42"/>'
    + _screen(118,
        '<text class="ink" x="139" y="26" font-size="9">Handle:</text>'
        '<rect class="lf caret" x="178" y="18.5" width="5" height="9"/>')
    + _caption(118, "it asks for", "a handle")
    + '<path class="d" d="M227 35 L231 38.5 L227 42"/>'
    + _screen(236,
        '<text x="257" y="26" font-size="9">#1:Sparks) hi</text>'
        '<text class="ink p3b" x="257" y="38" font-size="9">#2:you) hey</text>')
    + _caption(236, "then", "you are in")
    + "</svg>")


MACHINE_MODERN = _machines("", 140,
    "A laptop running a terminal program, its screen reading Connected to a "
    "board and Handle: with a blinking cursor, beside a phone running a "
    "terminal app.",
    '<rect class="o" x="40" y="4" width="164" height="96" rx="5"/>'
    '<rect class="g" x="48" y="11" width="148" height="82" rx="2"/>'
    '<text x="56" y="28" font-size="9">Connected to a board.</text>'
    '<text class="ink" x="56" y="42" font-size="9">Handle:</text>'
    '<rect class="lf caret" x="96" y="34" width="5" height="9"/>'
    '<path class="o" d="M28 100 H216 L226 112 H18 Z"/>'
    + _keyrows(46, 103, 152, 1)
    + '<rect class="o" x="252" y="8" width="56" height="102" rx="8"/>'
    '<rect class="g" x="257" y="19" width="46" height="80" rx="2"/>'
    '<path class="d" d="M273 14 H287 M272 104 H288"/>'
    '<text class="live" x="262" y="34" font-size="9">&gt;</text>'
    '<rect class="lf caret" x="269" y="26" width="4.5" height="9"/>'
    '<path class="d" d="M262 46 H297 M262 54 H290 M262 62 H294 M262 70 H285"/>'
    + _label(122, 126, "a laptop") + _label(280, 126, "a phone"))

MACHINE_CHROMEBOOK = _machines("", 134,
    "Two Chromebooks. The one you control shows a terminal with a prompt "
    "reading dollar telnet. The managed one, at a school or a workplace, "
    "shows a padlock on its screen.",
    '<rect class="o" x="14" y="4" width="140" height="90" rx="5"/>'
    '<rect class="g" x="21" y="11" width="126" height="76" rx="2"/>'
    '<text class="live" x="29" y="30" font-size="9">$ telnet</text>'
    '<rect class="lf caret" x="76" y="22" width="5" height="9"/>'
    '<path class="d" d="M29 44 H120 M29 52 H104"/>'
    '<path class="o" d="M6 94 H162 L170 104 H-2 Z"/>'
    + _keyrows(20, 97, 128, 1)
    + '<rect class="o" x="190" y="4" width="140" height="90" rx="5"/>'
    '<rect class="g" x="197" y="11" width="126" height="76" rx="2"/>'
    '<path class="f" d="M252 47 V41 A8 8 0 0 1 268 41 V47"/>'
    '<rect class="f" x="248" y="47" width="24" height="18" rx="2"/>'
    '<path class="f" d="M260 53 V59"/>'
    '<path class="o" d="M182 94 H338 L346 104 H174 Z"/>'
    + _keyrows(196, 97, 128, 1)
    + _label(84, 120, "one you control")
    + _label(260, 120, "managed at school or work"))

MACHINE_COMMODORE = _machines("", 138,
    "A Commodore 64, the breadbin-shaped keyboard computer with a rainbow "
    "stripe near its function keys, beside a 1541 disk drive with a monitor "
    "on top reading READY.",
    '<path class="o" d="M14 108 L24 74 Q26 70 30 70 H182 Q186 70 188 74 L198 108 Z"/>'
    + _keyrows(34, 78, 124, 4, 7)
    + "".join(f'<rect class="d" x="171" y="{y}" width="11" height="4" rx="1"/>'
              for y in (78, 85, 92, 99))
    + '<path class="c3" d="M150 75 L153 71 H155 L152 75 Z"/>'
    '<path class="c4" d="M154 75 L157 71 H159 L156 75 Z"/>'
    '<path class="c2" d="M158 75 L161 71 H163 L160 75 Z"/>'
    '<path class="c1" d="M162 75 L165 71 H167 L164 75 Z"/>'
    '<rect class="o" x="230" y="4" width="98" height="68" rx="6"/>'
    '<rect class="g" x="238" y="11" width="82" height="52" rx="4"/>'
    '<text class="dial" x="245" y="28" font-size="9">READY.</text>'
    '<rect class="c1 caret" x="245" y="33" width="5.5" height="8"/>'
    '<rect class="o" x="256" y="72" width="46" height="5" rx="1"/>'
    '<rect class="o" x="222" y="77" width="114" height="31" rx="3"/>'
    '<path class="d" d="M248 90 H310"/>'
    '<rect class="d" x="273" y="86" width="12" height="8" rx="1"/>'
    '<circle class="lf" cx="231" cy="101" r="1.6"/>'
    + _label(106, 124, "Commodore 64") + _label(279, 124, "1541 and monitor"))

MACHINE_ATARI = _machines("", 138,
    "An Atari 800XL, a slim keyboard computer with a column of five console "
    "keys beside its keyboard and a cartridge slot at the back, next to a "
    "television reading READY.",
    '<path class="o" d="M10 110 L18 70 H228 L236 110 Z"/>'
    '<path class="d" d="M96 75 H150"/>'
    + _keyrows(28, 82, 158, 4, 6)
    + "".join(f'<rect class="d" x="198" y="{y}" width="22" height="3.5" rx="1"/>'
              for y in (80, 86, 92, 98, 104))
    + '<rect class="o" x="256" y="20" width="86" height="66" rx="10"/>'
    '<rect class="g" x="264" y="28" width="60" height="50" rx="8"/>'
    '<circle class="d" cx="334" cy="40" r="3"/>'
    '<circle class="d" cx="334" cy="52" r="3"/>'
    '<path class="o" d="M272 86 L268 96 M326 86 L330 96"/>'
    '<text class="dial" x="271" y="45" font-size="9">READY</text>'
    '<rect class="c1 caret" x="271" y="50" width="5.5" height="8"/>'
    + _label(123, 124, "Atari 800XL") + _label(299, 124, "a TV"))

MACHINE_APPLE_AMIGA = _machines("", 144,
    "An Apple II with a Disk II drive and a green-screen monitor showing its "
    "square bracket prompt, and an Amiga 500 keyboard computer with its "
    "function keys in two groups of five, in front of a monitor showing a "
    "1> prompt.",
    '<rect class="o" x="26" y="4" width="110" height="60" rx="5"/>'
    '<rect class="g" x="33" y="10" width="96" height="48" rx="3"/>'
    '<text class="live" x="40" y="28" font-size="9">]</text>'
    '<rect class="lf caret" x="47" y="20" width="5" height="9"/>'
    '<rect class="o" x="34" y="66" width="64" height="18" rx="2"/>'
    '<path class="d" d="M44 72 H88"/>'
    '<rect class="d" x="60" y="76" width="12" height="5" rx="1"/>'
    '<circle class="lf" cx="40" cy="80" r="1.2"/>'
    '<rect class="o" x="22" y="84" width="132" height="10" rx="2"/>'
    '<path class="o" d="M14 116 L22 94 H154 L162 116 Z"/>'
    + _keyrows(34, 98, 108, 3, 6)
    + '<rect class="o" x="206" y="4" width="116" height="70" rx="5"/>'
    '<rect class="g" x="214" y="11" width="100" height="54" rx="3"/>'
    '<text class="ink" x="221" y="28" font-size="9">1&gt;</text>'
    '<rect class="lf caret" x="234" y="20" width="5" height="9"/>'
    '<rect class="o" x="246" y="74" width="36" height="6" rx="2"/>'
    '<path class="o" d="M186 116 L194 86 H336 L344 116 Z"/>'
    + "".join(f'<rect class="d" x="{x}" y="90" width="9" height="3" rx="1"/>'
              for x in (204, 215, 226, 237, 248, 268, 279, 290, 301, 312))
    + _keyrows(202, 97, 126, 3, 6)
    + _label(88, 130, "Apple II") + _label(265, 130, "Amiga 500"))

MACHINE_OTHERS = _machines("", 144,
    "A DOS PC, a flat system unit with two drive bays and a monitor on top "
    "showing a C colon backslash prompt, with its keyboard in front, and a "
    "TRS-80 Model 100, a flat portable with a small screen above its "
    "keyboard.",
    '<rect class="o" x="34" y="4" width="118" height="54" rx="5"/>'
    '<rect class="g" x="42" y="11" width="102" height="40" rx="3"/>'
    '<text class="ink" x="50" y="28" font-size="9">C:\\&gt;</text>'
    '<rect class="lf caret" x="74" y="20" width="5" height="9"/>'
    '<rect class="o" x="78" y="58" width="30" height="4" rx="1"/>'
    '<rect class="o" x="10" y="62" width="176" height="30" rx="2"/>'
    '<rect class="d" x="120" y="67" width="54" height="8" rx="1"/>'
    '<rect class="d" x="120" y="78" width="54" height="8" rx="1"/>'
    '<path class="d" d="M126 71 H168 M126 82 H168"/>'
    '<circle class="lf" cx="20" cy="85" r="1.4"/>'
    '<path class="o" d="M18 116 L22 100 H174 L178 116 Z"/>'
    + _keyrows(30, 104, 136, 2, 6)
    + '<path class="o" d="M214 116 L220 72 H338 L344 116 Z"/>'
    '<rect class="g" x="226" y="76" width="106" height="18" rx="1.5"/>'
    '<path class="d" d="M232 82 H300 M232 88 H286"/>'
    + _keyrows(226, 99, 106, 3, 5.5)
    + _label(98, 130, "a DOS PC") + _label(279, 130, "TRS-80 Model 100"))

MACHINE_TERMINALS = _machines("", 148,
    "A VT220-style terminal, a monitor on a stand with a separate long "
    "keyboard, and a Teletype Model 33, a printing terminal with a sheet of "
    "paper rising from its cover and a keyboard in front, on a stand.",
    '<rect class="o" x="30" y="4" width="132" height="78" rx="8"/>'
    '<rect class="g" x="40" y="12" width="112" height="60" rx="5"/>'
    '<text class="live" x="48" y="30" font-size="9">Handle:</text>'
    '<rect class="lf caret" x="88" y="22" width="5" height="9"/>'
    '<path class="o" d="M84 82 L80 90 H112 L108 82"/>'
    '<rect class="o" x="70" y="90" width="52" height="4" rx="2"/>'
    '<path class="o" d="M10 118 L16 102 H176 L182 118 Z"/>'
    + _keyrows(26, 106, 140, 2, 6)
    + '<path class="o" d="M252 50 V16 H300 V50"/>'
    '<path class="d" d="M258 24 H292 M258 30 H286 M258 36 H294 M258 42 H280"/>'
    '<path class="gb" d="M214 70 Q214 50 240 48 H316 Q340 50 340 70 V92 H214 Z"/>'
    '<rect class="d" x="220" y="74" width="18" height="10" rx="1"/>'
    '<path class="o" d="M208 92 H346 L342 104 H212 Z"/>'
    + _keyrows(226, 95, 104, 2, 4.5)
    + '<path class="o" d="M228 104 V122 M326 104 V122"/>'
    + _label(96, 134, "a VT220-style terminal")
    + _label(277, 134, "Teletype Model 33"))

MACHINE_BRIDGE = _machines(" bridge", 114,
    "An old computer connected by a serial cable to a small bridge box with "
    "an aerial, which reaches the board over Wi-Fi. A dot travels along the "
    "serial cable.",
    '<path class="o" d="M6 80 L12 56 H86 L92 80 Z"/>'
    + _keyrows(18, 62, 62, 3, 6)
    + '<path class="d" d="M92 68 H170"/>'
    '<rect class="o" x="94" y="63" width="9" height="10" rx="1.5"/>'
    '<rect class="o" x="160" y="63" width="10" height="10" rx="1.5"/>'
    '<g class="go"><circle class="halo" cx="131" cy="68" r="4.2"/>'
    '<circle class="lf" cx="131" cy="68" r="2.2"/></g>'
    '<text x="131" y="56" font-size="10" text-anchor="middle">serial</text>'
    '<rect class="body" x="170" y="52" width="56" height="32" rx="4"/>'
    '<circle class="lf" cx="182" cy="76" r="1.6"/>'
    '<path class="o" d="M218 52 V36"/>'
    '<circle class="lf" cx="218" cy="34" r="1.6"/>'
    '<path class="l" d="M222.6 30.1 A6 6 0 0 1 222.6 37.9 '
    'M226.4 26.9 A11 11 0 0 1 226.4 41.1 M230.3 23.7 A16 16 0 0 1 230.3 44.3"/>'
    '<path class="ld" d="M236 69 H292"/>'
    '<text x="262" y="60" font-size="10" text-anchor="middle">Wi-Fi</text>'
    '<rect class="body" x="292" y="56" width="46" height="26" rx="3"/>'
    '<text x="315" y="73" font-size="9" text-anchor="middle">BBS</text>'
    + _label(49, 100, "old machine") + _label(198, 100, "bridge")
    + _label(315, 100, "the board"))


# ----------------------------------------------------------------------
# The SD card wiring diagram on /sdcard, beside the pin table it draws.
#
# The pins are the firmware's defaults and nothing else: struct SdPins in
# src/platform/platform.h, CS 5, MOSI 23, CLK 18, MISO 19. If those ever
# change, this and the table change in the same commit.
#
# The rows are in the order the common module prints its header (GND, VCC,
# MISO, MOSI, SCK, CS) so every wire runs straight across. The dev board's
# side is drawn in that same order to match, which is NOT the order any
# particular board puts its pins in, and the note under the drawing says
# to go by the printed names for exactly that reason.
#
# Colour means the same thing on the wire, the pin, the label and the pulse.
# Ground is --faint and power --busy; the four data lines take --live,
# --dial, --warm and --name, and never --risk, which on this site means
# somebody keeping a copy of you. The pulses run CS, then clock and MOSI
# together, then MISO back the other way: a transfer in the order it
# happens, declared in the no-preference block like all the others.
# ----------------------------------------------------------------------

_SD_ROWS = (  # y, colour, ESP32 pin, wire label, module pin
    (104, "gnd", "GND", "GND", "GND"),
    (124, "pwr", "3V3", "3V3", "VCC"),
    (144, "miso", "D19", "GPIO19", "MISO"),
    (164, "mosi", "D23", "GPIO23", "MOSI"),
    (184, "sck", "D18", "GPIO18", "SCK"),
    (204, "cs", "D5", "GPIO5", "CS"),
)
_SD_PULSE = {"cs": "p-cs", "sck": "p-out", "mosi": "p-out", "miso": "p-in"}

SD_WIRING_ALT = (
    "Wiring an SD card module to an ESP32 dev board, four signal wires plus "
    "power. Ground to GND. "
    "Power from the 3V3 pin to VCC. GPIO19, printed D19, to MISO. GPIO23, D23, "
    "to MOSI. GPIO18, D18, to SCK. GPIO5, D5, to CS. The module carries a "
    "regulator, a level shifter and a micro SD card in its socket. Start the "
    "power on 3V3, and go by the printed pin names, because boards put their "
    "pins in different orders.")


# The dev board, as the wiring diagrams draw it: the module's can with its
# antenna, a header down the side, two buttons and the USB socket, in the
# box x 8 to 106, y 8 to 234. The wires leave its right edge at x 106.
DEVBOARD_ART = (
    '<rect class="o" x="8" y="8" width="98" height="222" rx="4"/>'
    '<rect class="d" x="20" y="14" width="74" height="16" rx="1"/>'
    '<path class="d" d="M26 22 H34 V18 H40 V26 H46 V18 H52 V26 H58 V18 '
    'H64 V26 H70 V22 H86"/>'
    '<rect class="o" x="20" y="30" width="74" height="58" rx="2"/>'
    '<text x="57" y="63" font-size="10" text-anchor="middle">ESP32</text>'
    + "".join(f'<rect class="k" x="11" y="{y}" width="4" height="4" rx="0.5"/>'
              for y in range(100, 212, 11))
    + '<rect class="d" x="20" y="213" width="8" height="6" rx="1"/>'
    '<rect class="d" x="86" y="213" width="8" height="6" rx="1"/>'
    '<rect class="o" x="44" y="222" width="26" height="12" rx="2"/>')


def _wire_row(y, c, pin, wire, far, far_x=234, label_x=171, gap=None):
    """One wire of a diagram: from the board's edge at 106 to far_x, with a
    pin at each end, the board's pin name, the wire's name over its middle
    and the far end's pin name. gap is (x1, x2), a stretch left open for a
    part drawn on the wire, such as a resistor."""
    path = (f"M108 {y} H{far_x}" if gap is None
            else f"M108 {y} H{gap[0]} M{gap[1]} {y} H{far_x}")
    return (f'<path class="ww s-{c}" d="{path}"/>'
            f'<rect class="f-{c}" x="101" y="{y - 2.5}" width="5" height="5" rx="1"/>'
            f'<rect class="f-{c}" x="{far_x}" y="{y - 2.5}" width="5" height="5" rx="1"/>'
            f'<text class="f-{c}" x="97" y="{y + 3}" font-size="10" '
            f'text-anchor="end">{pin}</text>'
            f'<text class="f-{c}" x="{label_x}" y="{y - 5}" font-size="10" '
            f'text-anchor="middle">{wire}</text>'
            + (f'<text class="f-{c}" x="{far_x + 11}" y="{y + 3}" font-size="10">{far}</text>'
               if far else ""))


def _sd_wiring():
    out = ['<svg class="art wiring" viewBox="-5 -6 354 308" role="img" '
           'preserveAspectRatio="xMidYMid meet" aria-label="'
           + html.escape(SD_WIRING_ALT, quote=True) + '">']
    out.append(DEVBOARD_ART)
    # The module: its PCB, a three legged regulator, a level shifter, the
    # socket, and the card sitting in it.
    out.append(
        '<rect class="o" x="236" y="92" width="104" height="128" rx="4"/>'
        '<rect class="gb" x="300" y="100" width="18" height="12" rx="1"/>'
        '<path class="d" d="M303 112 V116 M309 112 V116 M315 112 V116"/>'
        '<rect class="gb" x="296" y="126" width="26" height="30" rx="1"/>'
        '<path class="d" d="M292 131 H296 M292 137 H296 M292 143 H296 '
        'M292 149 H296 M322 131 H326 M322 137 H326 M322 143 H326 M322 149 H326"/>'
        '<circle class="lf" cx="300" cy="130" r="1"/>'
        '<rect class="o" x="270" y="168" width="62" height="44" rx="2"/>'
        '<path class="d" d="M274 174 H328"/>'
        '<path class="gb" d="M286 186 H318 V228 H286 V198 L290 194 V186 Z"/>'
        '<text x="302" y="216" font-size="9" text-anchor="middle">card</text>')
    # The six wires, each with its pins, its names and, on the data lines,
    # a pulse. The pulse sits mid-wire at rest, under the wire's label.
    for y, c, pin, wire, mod in _SD_ROWS:
        out.append(_wire_row(y, c, pin, wire, mod))
        if c in _SD_PULSE:
            out.append(f'<circle class="f-{c} spi {_SD_PULSE[c]}" '
                       f'cx="171" cy="{y}" r="2.2"/>')
    out.append(
        _label(57, 246, "ESP32 dev board") + _label(288, 246, "SD card module")
        + '<text x="172" y="264" font-size="10" text-anchor="middle">'
        "Power: start on 3V3. Some modules want 5 V: see below.</text>"
        '<text x="172" y="278" font-size="10" text-anchor="middle">'
        "Pin order differs between boards: go by the names.</text>"
        '<text x="172" y="292" font-size="10" text-anchor="middle">'
        "The pins can be changed on CONFIG sd.</text>"
        "</svg>")
    return "".join(out)


SD_WIRING = _sd_wiring()


# ----------------------------------------------------------------------
# The lights on /lights (site 1.2.1), drawn the way the SD card is: the dev
# board on the left, each wire one colour end to end. Power is --busy and
# ground --faint, as on the SD diagram, and the data line --live.
#
# The facts are the firmware's (src/plugins/lights.cpp, COMMANDS.md
# "lights"): GPIO13 for the drive light, which has no job at boot, and 14
# for the strip, the pin COMMANDS.md's example gives it. The resistor, the
# capacitor and the separate supply for the strip are Rob's, settled in the
# firmware's CLAUDE.md. No level shifter, on purpose: 5 V pixels take their
# data from the 3.3 V pin.
# ----------------------------------------------------------------------
LIGHTS_DRIVE_ALT = (
    "Wiring one WS2812B pixel to an ESP32 dev board as the drive light. VIN, "
    "the 5 V from USB, to the pixel's 5V. Ground to GND. GPIO13, printed D13, "
    "through a 330 to 470 ohm resistor to the pixel's DIN. A 100 nF capacitor "
    "across the pixel's 5V and GND, at the pixel.")


def _lights_drive():
    out = ['<svg class="art wiring lights" viewBox="-5 -6 354 308" role="img" '
           'preserveAspectRatio="xMidYMid meet" aria-label="'
           + html.escape(LIGHTS_DRIVE_ALT, quote=True) + '">', DEVBOARD_ART]
    # The pixel on its little board, lit.
    out.append(
        '<rect class="o" x="252" y="100" width="84" height="100" rx="4"/>'
        '<rect class="gb" x="296" y="128" width="28" height="28" rx="2"/>'
        '<circle class="halo" cx="310" cy="142" r="11"/>'
        '<circle class="lf glow" cx="310" cy="142" r="5"/>')
    out.append(_wire_row(124, "pwr", "VIN", "VIN, 5 V", "5V", far_x=250, label_x=150)
               + _wire_row(144, "gnd", "GND", "GND", "GND", far_x=250, label_x=150)
               + _wire_row(164, "dat", "D13", "GPIO13", "DIN", far_x=250, label_x=150,
                           gap=(190, 216)))
    # The resistor in the data line, and the capacitor across the supply.
    out.append(
        '<rect class="gb" x="190" y="160" width="26" height="8" rx="1.5"/>'
        '<text class="f-dat" x="203" y="156" font-size="8.5" '
        'text-anchor="middle">330 to 470 \u03a9</text>'
        '<path class="ww s-pwr" d="M234 124 V131"/>'
        '<path class="ww s-gnd" d="M234 137 V144"/>'
        '<path class="o" d="M227 131 H241 M227 137 H241"/>'
        '<circle class="f-pwr" cx="234" cy="124" r="2.2"/>'
        '<circle class="f-gnd" cx="234" cy="144" r="2.2"/>'
        '<text x="224" y="137" font-size="8.5" text-anchor="end">100 nF</text>')
    out.append(
        _label(57, 246, "ESP32 dev board") + _label(294, 218, "WS2812B pixel")
        + '<text x="172" y="264" font-size="10" text-anchor="middle">'
        "One pixel draws about 60 mA: VIN on USB is fine.</text>"
        '<text x="172" y="278" font-size="10" text-anchor="middle">'
        "Resistor and capacitor at the pixel end.</text>"
        '<text x="172" y="292" font-size="10" text-anchor="middle">'
        "The pin is set on CONFIG lights.</text>"
        "</svg>")
    return "".join(out)


LIGHTS_DRIVE = _lights_drive()

LIGHTS_STRIP_ALT = (
    "Wiring a strip of ten WS2812B pixels to an ESP32 dev board. The strip has "
    "a 5 V supply of its own, rated 1 A or more: its plus to the strip's 5V, "
    "its minus to the strip's GND, and the board's GND joined to that same "
    "ground. GPIO14, printed D14, through a 330 to 470 ohm resistor to the "
    "strip's DIN at the first pixel. A 100 nF capacitor across the strip's 5V "
    "and GND. The board's VIN is not connected to the strip.")


def _lights_strip():
    out = ['<svg class="art wiring lights" viewBox="-5 -6 354 308" role="img" '
           'preserveAspectRatio="xMidYMid meet" aria-label="'
           + html.escape(LIGHTS_STRIP_ALT, quote=True) + '">', DEVBOARD_ART]
    # The supply, with its two terminals at the bottom.
    out.append(
        '<rect class="o" x="236" y="12" width="106" height="50" rx="3"/>'
        '<text class="ink" x="289" y="30" font-size="10" text-anchor="middle">'
        "5 V supply</text>"
        '<text x="289" y="43" font-size="9" text-anchor="middle">1 A or more</text>'
        '<text class="f-gnd" x="300" y="57" font-size="10" text-anchor="middle">-</text>'
        '<text class="f-pwr" x="322" y="57" font-size="10" text-anchor="middle">+</text>')
    # The strip: its pads on the top edge, ten pixels, three of them lit.
    lit = {0: "px1", 1: "px2", 3: "px3"}
    out.append(
        '<rect class="o" x="190" y="176" width="154" height="44" rx="3"/>'
        '<text class="f-dat" x="206" y="190" font-size="8.5" text-anchor="middle">DIN</text>'
        '<text class="f-gnd" x="300" y="190" font-size="8.5" text-anchor="middle">GND</text>'
        '<text class="f-pwr" x="322" y="190" font-size="8.5" text-anchor="middle">5V</text>'
        + "".join(f'<rect class="gb" x="{196 + i * 14.4:g}" y="198" width="10" '
                  f'height="10" rx="1.5"/>' for i in range(10))
        + "".join(f'<circle class="lf {cls}" cx="{201 + i * 14.4:g}" cy="203" r="2.6"/>'
                  for i, cls in lit.items()))
    # Ground: the supply's minus down to the strip, and the board's GND
    # across to meet it. Power: the supply's plus down to the strip, and
    # nothing from the board. Data: D14 through the resistor to DIN.
    out.append(
        '<path class="ww s-gnd" d="M300 64 V174 M108 144 H300"/>'
        '<path class="ww s-pwr" d="M322 64 V174"/>'
        '<path class="ww s-dat" d="M108 164 H150 M176 164 H206 V174"/>'
        '<circle class="f-gnd" cx="300" cy="144" r="3"/>'
        '<rect class="f-gnd" x="101" y="141.5" width="5" height="5" rx="1"/>'
        '<rect class="f-dat" x="101" y="161.5" width="5" height="5" rx="1"/>'
        '<text class="f-gnd" x="97" y="147" font-size="10" text-anchor="end">GND</text>'
        '<text class="f-dat" x="97" y="167" font-size="10" text-anchor="end">D14</text>'
        '<text class="f-gnd" x="200" y="139" font-size="10" text-anchor="middle">'
        "GND, shared</text>"
        '<text class="f-dat" x="128" y="179" font-size="10" text-anchor="middle">GPIO14</text>'
        '<rect class="gb" x="150" y="160" width="26" height="8" rx="1.5"/>'
        '<text class="f-dat" x="163" y="156" font-size="8.5" '
        'text-anchor="middle">330 to 470 \u03a9</text>'
        '<path class="ww s-gnd" d="M300 160 H306"/>'
        '<path class="ww s-pwr" d="M316 160 H322"/>'
        '<path class="o" d="M306 153 V167 M316 153 V167"/>'
        '<circle class="f-gnd" cx="300" cy="160" r="2.2"/>'
        '<circle class="f-pwr" cx="322" cy="160" r="2.2"/>'
        '<text x="296" y="163" font-size="8.5" text-anchor="end">100 nF</text>')
    out.append(
        _label(57, 246, "ESP32 dev board") + _label(267, 238, "the strip, 1 to 16")
        + '<text x="172" y="264" font-size="10" text-anchor="middle">'
        "Ten pixels at full white: about 600 mA.</text>"
        '<text x="172" y="278" font-size="10" text-anchor="middle">'
        "Their own supply, its ground joined to GND.</text>"
        '<text x="172" y="292" font-size="10" text-anchor="middle">'
        "Resistor at the first pixel. Pin on CONFIG lights.</text>"
        "</svg>")
    return "".join(out)


LIGHTS_STRIP = _lights_strip()


# The camera on /camera (site 1.2.4): a terminal types SNAPSHOT, the word
# goes down the line to the camera board, its pixel flashes white for the
# shot, and the lens looks out at a bird feeder. 354 units wide like the
# first call strip, so a phone draws it at about 1:1.
CAMERA_ART = (
    '<svg class="art camsnap" viewBox="0 0 354 124" role="img" '
    'aria-label="A terminal types SNAPSHOT, the word goes down the line to the '
    'camera board, its light flashes for the shot, and the lens looks at a bird '
    'feeder." preserveAspectRatio="xMidYMid meet">'
    # the terminal
    '<rect class="o" x="8" y="12" width="88" height="62" rx="4"/>'
    '<rect class="g" x="14" y="18" width="76" height="48" rx="1.5"/>'
    '<text class="live" x="20" y="33" font-size="9.5">SNAPSHOT</text>'
    '<text x="20" y="46" font-size="8.5">Download it</text>'
    '<text x="20" y="57" font-size="8.5">now? (y/N)</text>'
    '<rect class="lf caret" x="70" y="50.5" width="5" height="7"/>'
    '<path class="o" d="M52 74 V82 M36 82 H68"/>'
    # the line, and the word going down it
    '<path class="ld" d="M100 43 H170"/>'
    '<g class="go"><circle class="halo" cx="135" cy="43" r="4.5"/>'
    '<circle class="lf" cx="135" cy="43" r="2.3"/></g>'
    # the camera board
    '<rect class="o" x="174" y="20" width="74" height="46" rx="2"/>'
    '<path class="d" d="' + " ".join(
        f"M{180 + i * 6} 20 V16 M{180 + i * 6} 66 V70" for i in range(12)) + '"/>'
    '<rect class="o" x="190" y="30" width="26" height="26" rx="1.5"/>'
    '<circle class="o" cx="203" cy="43" r="9"/>'
    '<circle class="d" cx="203" cy="43" r="5"/>'
    '<circle class="c1" cx="200.6" cy="40.6" r="1.2"/>'
    '<rect class="o" x="228" y="28" width="9" height="9" rx="1"/>'
    '<circle class="flash fl" cx="232.5" cy="32.5" r="7"/>'
    '<circle class="lf" cx="232.5" cy="32.5" r="2.2"/>'
    # what the lens sees
    '<path class="f" d="M212 38 L294 26 M212 48 L294 80"/>'
    # the feeder, and who is on it
    '<path class="o" d="M322 112 V87 M298 62 L322 48 L346 62 Z"/>'
    '<rect class="o" x="302" y="82" width="40" height="5" rx="1"/>'
    '<path class="d" d="M306 62 V82 M338 62 V82"/>'
    '<ellipse class="o" cx="316" cy="76" rx="6.5" ry="4.2"/>'
    '<circle class="o" cx="322.5" cy="71.5" r="2.8"/>'
    '<path class="o" d="M325.2 71.5 L328.2 72.3 M309.8 75 L305.5 72.5"/>'
    '<circle class="c5" cx="323.3" cy="70.9" r="0.7"/>'
    # captions
    '<text x="52" y="100" font-size="10.5" text-anchor="middle">you type SNAPSHOT</text>'
    '<text x="211" y="100" font-size="10.5" text-anchor="middle">the board takes it</text>'
    '<text x="322" y="121" font-size="10.5" text-anchor="middle">the feeder</text>'
    "</svg>")


# The skins page, /skins (site 1.3.14): a picture of a machine with its
# lamps painted dark, the skin.txt that says where they are, and the board's
# screen with the same picture lit, the drive lamp amber and the activity lamp
# green, and status lines on the monitor. A generic machine: no maker's shape
# and no badge, which is the page's own rule for skins. 354 units wide like
# the camera strip, so a phone draws it at about 1:1.
def _skin_machine(lit):
    """The machine in a 96 x 64 frame, its lamps dark or lit."""
    out = ('<rect class="o" x="20" y="22" width="40" height="30" rx="2"/>'
           '<rect class="g" x="24" y="26" width="32" height="22" rx="1"/>'
           '<path class="o" d="M40 52 V56 M32 56 H48"/>'
           '<rect class="o" x="66" y="38" width="30" height="20" rx="1.5"/>'
           '<path class="d" d="M70 45 H92"/>'
           '<rect class="o" x="18" y="62" width="46" height="9" rx="1.5"/>'
           '<path class="d" d="M22 66.5 H60"/>')
    if not lit:
        return out + ('<circle class="d" cx="90" cy="52" r="2"/>'
                      '<circle class="d" cx="72" cy="52" r="2"/>')
    return out + (
        # the status lines on the monitor, in the text's own colour
        '<path class="lt" d="M27.5 31 H48 M27.5 36 H44 M27.5 41 H50"/>'
        # the drive lamp, amber, and the activity lamp, green
        '<g class="glow"><circle class="c5" cx="90" cy="52" r="5" opacity="0.25"/>'
        '<circle class="c5" cx="90" cy="52" r="2"/></g>'
        '<g class="glow2"><circle class="halo" cx="72" cy="52" r="5"/>'
        '<circle class="lf" cx="72" cy="52" r="2"/></g>')


SKIN_ART = (
    '<svg class="art skinart" viewBox="0 0 354 124" role="img" '
    'aria-label="A picture of a computer with its lamps painted dark, plus a '
    'skin.txt file saying where the lamps and the text go, becomes the board\'s '
    'screen showing the same picture with its lamps lit and status lines on '
    'its monitor." preserveAspectRatio="xMidYMid meet">'
    # the picture
    '<rect class="o" x="8" y="14" width="96" height="64" rx="1.5"/>'
    + _skin_machine(False)
    + '<path class="d" d="M109 42.5 L113 46 L109 49.5"/>'
    # skin.txt
    '<path class="o" d="M120 14 H180 L190 24 V78 H120 Z"/>'
    '<path class="d" d="M180 14 V24 H190"/>'
    '<text class="ink" x="125" y="31" font-size="7.5">skin 1</text>'
    '<text class="live" x="125" y="43" font-size="7.5">drive 90 52</text>'
    '<text class="live" x="125" y="55" font-size="7.5">activity</text>'
    '<text x="125" y="67" font-size="7.5">text 24 26</text>'
    '<path class="d" d="M195 42.5 L199 46 L195 49.5"/>'
    # the board: a circuit board with the screen on it, and the picture lit
    '<rect class="o" x="204" y="8" width="142" height="76" rx="3"/>'
    '<rect class="gb" x="210" y="14" width="100" height="68" rx="1.5"/>'
    '<g transform="translate(206 2)">' + _skin_machine(True) + "</g>"
    '<rect class="o" x="318" y="30" width="20" height="20" rx="1"/>'
    '<path class="d" d="M322 30 V26 M327 30 V26 M332 30 V26 M322 50 V54 '
    'M327 50 V54 M332 50 V54"/>'
    '<rect class="o" x="340" y="60" width="9" height="12" rx="1"/>'
    # captions
    '<text class="ink" x="56" y="100" font-size="10.5" text-anchor="middle">your picture</text>'
    '<text x="56" y="113" font-size="9.5" text-anchor="middle">lamps dark</text>'
    '<text class="ink" x="155" y="100" font-size="10.5" text-anchor="middle">skin.txt</text>'
    '<text x="155" y="113" font-size="9.5" text-anchor="middle">says where</text>'
    '<text class="ink" x="275" y="100" font-size="10.5" text-anchor="middle">the board</text>'
    '<text x="275" y="113" font-size="9.5" text-anchor="middle">lights it</text>'
    "</svg>")


# The skull for the warning box on /how. Crossbones first, so the skull,
# filled with the box's own background, sits in front of the crossing.
# Not animated: a warning that moves is a warning that looks like an
# advertisement.
SKULL = """<svg class="art skull" viewBox="0 0 48 48" aria-hidden="true" focusable="false">
  <path class="a" d="M9 22 L39 38 M39 22 L9 38"/>
  <circle class="af" cx="7.2" cy="22.8" r="1.9"/><circle class="af" cx="8.7" cy="20.1" r="1.9"/>
  <circle class="af" cx="39.3" cy="39.9" r="1.9"/><circle class="af" cx="40.8" cy="37.3" r="1.9"/>
  <circle class="af" cx="40.8" cy="22.8" r="1.9"/><circle class="af" cx="39.3" cy="20.1" r="1.9"/>
  <circle class="af" cx="8.7" cy="39.9" r="1.9"/><circle class="af" cx="7.2" cy="37.3" r="1.9"/>
  <path class="af" d="M12 19 C12 10.5 17.5 4.5 24 4.5 C30.5 4.5 36 10.5 36 19 C36 24 33.5 26.5 31 27.5 V33 H17 V27.5 C14.5 26.5 12 24 12 19 Z"/>
  <ellipse class="aff" cx="19" cy="18" rx="3.4" ry="3.8"/>
  <ellipse class="aff" cx="29" cy="18" rx="3.4" ry="3.8"/>
  <path class="aff" d="M24 22.5 L22.3 26 H25.7 Z"/>
  <path class="a" d="M20.5 33 V29.5 M24 33 V29.5 M27.5 33 V29.5"/>
</svg>"""


# What "::: art <name>" can draw on a Markdown page.
# ----------------------------------------------------------------------
# Screens captured from the board itself, for /setup.
#
# Not raster images and not redrawn by hand: tools on the firmware side ran
# the host build on 127.0.0.1, drove a real session, and the screen model
# kept each cell's character, colour and reverse video. shots/<name>.json
# holds the result, and this draws it as the site's art: the characters on
# a grid, each run of one colour a <text> pinned to its columns with
# textLength so the font's own width cannot drift it, and reverse video as
# a filled cell behind dark text.
#
# The colours are the terminal's, not the site's palette, because they are
# what a caller sees. Two kinds of class, text.cN and rect.bN, one per ANSI
# colour and brightness, 0 to f.
# ----------------------------------------------------------------------
#
# The captures travel with the guides (unleashed_documentation), in
# DOCS_DIR/shots; a shots/ folder beside this file is read when the
# guides have none, for a checkout that still carries one.
SHOTS_DIR = (DOCS_DIR / "shots" if (DOCS_DIR / "shots").is_dir()
             else pathlib.Path(__file__).resolve().parent / "shots")
SHOT_CELL, SHOT_LINE, SHOT_PAD = 6, 12, 8


def shot_svg(name, alt):
    """One captured screen as a drawing, in a monitor's bezel, with what
    was typed to get it written under the glass."""
    # A missing or broken capture costs one picture, never the server. This
    # runs at import, and with no guard a deployment without shots/ died
    # before it answered anything (the 2026-09-23 outage).
    try:
        doc = json.loads((SHOTS_DIR / (name + ".json")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return f'<p class="shot-missing">{html.escape(alt)}</p>'
    cols, rows, attrs = doc["cols"], doc["rows"], doc["attrs"]
    gw = cols * SHOT_CELL + 2 * SHOT_PAD
    gh = len(rows) * SHOT_LINE + 2 * SHOT_PAD
    x0, y0 = 10, 10
    # Sized so the type lands near the page's own, about 1.7 times its
    # 10 unit size, whatever the width of the capture: a 39 column form
    # and a 47 column list then read at the same size.
    width_rem = round((gw + 20) * 0.08, 2)
    out = [f'<svg class="art shot" style="max-width:{width_rem}rem" '
           f'viewBox="0 0 {gw + 20} {gh + 40}" role="img" '
           'preserveAspectRatio="xMidYMid meet" aria-label="'
           + html.escape(alt, quote=True) + '">',
           f'<rect class="o" x="4" y="4" width="{gw + 12}" height="{gh + 12}" rx="6"/>',
           f'<rect class="scr" x="{x0}" y="{y0}" width="{gw}" height="{gh}" rx="2"/>']
    for r, (text, attr) in enumerate(zip(rows, attrs)):
        top = y0 + SHOT_PAD + r * SHOT_LINE
        base = top + 9.5
        c = 0
        while c < len(text):
            code = attr[c]
            e = c
            while e < len(text) and attr[e] == code:
                e += 1
            run = text[c:e]
            x = x0 + SHOT_PAD + c * SHOT_CELL
            w = (e - c) * SHOT_CELL
            rev = code >= "g"
            hexcode = "0123456789abcdef"["ghijklmnopqrstuv".index(code)] if rev else code
            if rev:
                out.append(f'<rect class="b{hexcode}" x="{x}" y="{top}" '
                           f'width="{w}" height="{SHOT_LINE}"/>')
            if run.strip():
                out.append(f'<text class="{"cz" if rev else "c" + hexcode}" x="{x}" '
                           f'y="{base}" font-size="10" textLength="{w}" '
                           'lengthAdjust="spacingAndGlyphs" xml:space="preserve">'
                           + html.escape(run) + "</text>")
            c = e
    caption = doc.get("caption") or ("typed: " + doc.get("typed", ""))
    out.append(f'<text class="cap" x="{x0 + 2}" y="{gh + 32}" font-size="9">'
               + html.escape(caption) + "</text>")
    out.append(f'<circle class="lf" cx="{gw + 4}" cy="{gh + 29}" r="2"/>')
    out.append("</svg>")
    return "".join(out)


SHOTS = {
    "shot-config-list": ("config-list",
        "The board's answer to CONFIG: a list of settings pages. board, "
        "limits, accounts, backup, staff and wifi, each with one line saying "
        "what it holds, then one page per plugin: sd, files, forums, info, "
        "example, chat, serial and announce."),
    "shot-config-board": ("config-board",
        "CONFIG board: a form headed BOARD with the fields Board, Hostname, "
        "Timezone, NTP, Idle min, LED gpio and Land on, holding My Board, "
        "unleashed, UTC0, pool.ntp.org, 20, 2 and main, with Save and "
        "Cancel under them and the keys on the bottom line."),
    "shot-config-files": ("config-files",
        "CONFIG files: Enabled, Read, Write and Admin, then Area 1 to Area 8 "
        "as buttons. The first two carry the names C64 Downloads and Text "
        "Files; the rest say not set."),
    "shot-setup-offer": ("setup-offer",
        "What a new board says to a caller on its own network after they sign "
        "up: This board has not been set up yet. You are on its own network, "
        "so you can do it now. The sysop password is on the install page. "
        "Then: Sysop password (ESC skips)."),
    "shot-setup-screen": ("setup-screen",
        "The setup screen, headed YOU ARE THE SYSOP: welcome, the job of "
        "changing the default password first in the staff passwords form, "
        "no port forward and no directory listing until that is done, and "
        "that a short tour follows."),
    "shot-config-staff": ("config-staff",
        "The staff passwords form, opened by the setup: Sysop, showing stars, "
        "and the two co-sysop passwords, blank, with Save and Cancel."),
    "shot-newsysop-1": ("newsysop-1",
        "The first page of the tour, SETTING UP YOUR BOARD: what CONFIG does, "
        "and one line for each settings page, board, limits, accounts, "
        "backup, staff and wifi, then the plugins."),
    "shot-config-area": ("config-area",
        "Area 1 opened from CONFIG files: a form headed FILE AREA 1 with Path "
        "pub/c64, Name C64 Downloads, and the levels Read all, Upload staff, "
        "Download all and Delete sysop."),
}

SETUP_ALT = (
    "Three steps. A board on a USB cable, flashed from the browser. Wi-Fi "
    "waves, where the board is told your network. A screen showing the BOARD "
    "settings form, where CONFIG sets the rest up.")

# The same hand as the first call strip: three panels, captions under
# them, and one caret that blinks in the last.
SETUP_ART = (
    '<svg class="art steps" viewBox="-5 -6 354 130" role="img" '
    'preserveAspectRatio="xMidYMid meet" aria-label="' + SETUP_ALT + '">'
    # A dev board on its cable, lamp lit.
    '<rect class="o" x="22" y="14" width="66" height="44" rx="3"/>'
    '<path class="d" d="M28 14 V10 M36 14 V10 M44 14 V10 M52 14 V10 M60 14 V10'
    ' M68 14 V10 M76 14 V10 M84 14 V10 M28 58 V62 M36 58 V62 M44 58 V62'
    ' M68 58 V62 M76 58 V62 M84 58 V62"/>'
    '<rect class="g" x="38" y="20" width="34" height="24" rx="1.5"/>'
    '<path class="d" d="M41 25 H44 V22 H48 V25 H52 V22 H56 V25 H60 V22 H64 V25 H69"/>'
    '<rect class="gb" x="50" y="56" width="10" height="7" rx="1"/>'
    '<path class="o" d="M55 63 V70 Q55 78 47 78 H18"/>'
    '<circle class="lf" cx="81" cy="51" r="2"/>'
    + _caption(0, "flash it", "from the browser")
    + '<path class="d" d="M109 35 L113 38.5 L109 42"/>'
    # Wi-Fi, three arcs over a dot.
    '<path class="o" d="M166.87 52.86 A8 8 0 0 1 179.13 52.86"/>'
    '<path class="o" d="M159.98 47.07 A17 17 0 0 1 186.02 47.07"/>'
    '<path class="o" d="M153.08 41.28 A26 26 0 0 1 192.92 41.28"/>'
    '<circle class="lf" cx="173" cy="60" r="2.6"/>'
    + _caption(118, "tell it", "your Wi-Fi")
    + '<path class="d" d="M227 35 L231 38.5 L227 42"/>'
    + _screen(236,
        '<text class="dial" x="257" y="23" font-size="8">BOARD</text>'
        '<path class="d" d="M257 26.5 H326"/>'
        '<text class="ink" x="257" y="37" font-size="8">Board</text>'
        '<rect class="k" x="284" y="30" width="41" height="9" rx="1"/>'
        '<rect class="lf caret" x="286" y="31" width="3.5" height="7"/>'
        '<text x="257" y="50" font-size="8">Idle</text>'
        '<path class="d" d="M284 48.5 H325"/>')
    + _caption(236, "set it up", "with CONFIG")
    + "</svg>")

# The drawings the directory's pages and the guides name in "::: art".
ART.update({
    "firstcall": FIRSTCALL_ART,
    "setup-steps": SETUP_ART,
    "term-modern": MACHINE_MODERN,
    "term-chromebook": MACHINE_CHROMEBOOK,
    "term-commodore": MACHINE_COMMODORE,
    "term-atari": MACHINE_ATARI,
    "term-apple-amiga": MACHINE_APPLE_AMIGA,
    "term-others": MACHINE_OTHERS,
    "term-terminals": MACHINE_TERMINALS,
    "term-bridge": MACHINE_BRIDGE,
    "sd-wiring": SD_WIRING,
    "lights-drive": LIGHTS_DRIVE,
    "lights-strip": LIGHTS_STRIP,
    "camera-snap": CAMERA_ART,
    "skin-parts": SKIN_ART,
})
ART.update({key: shot_svg(name, alt) for key, (name, alt) in SHOTS.items()})

HOW = HOW.replace("@ART_CSS@", ART_CSS).replace("@SKULL@", SKULL)
DATA_DESC  = ("The directory, machine readable. No key, no signup, no rate "
              "limit worth mentioning. It is a list of hobby BBSes.")


def simple_page(title, body, role="list", here="", desc=SITE_DESC):
    """Any page that is a block of prose. The header and footer are added
    here and nowhere else, so no page carries its own copy of either."""
    return PAGE.format(refresh="", head="", title=html.escape(title),
                       desc=html.escape(desc, quote=True),
                       body=head_html(role, here) + body,
                       footer=foot_html(role))


# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "unleashed-directory/1.0"

    def log_message(self, fmt, *args):      # one tidy line, not two
        print(f"{self.caller()} {fmt % args}", flush=True)

    def caller(self):
        """The address this request actually came from.

        getattr rather than self.headers, because log_message runs for a
        request line that never parsed into headers at all, and an
        AttributeError raised inside the logger is a bad way to find out.
        """
        head = getattr(self, "headers", None)
        peer = self.client_address[0] if self.client_address else ""
        if head is None:
            return normal_ip(peer) or str(peer)
        return client_ip(peer,
                         head.get("X-Forwarded-For", ""),
                         head.get("X-Real-IP", ""))

    def canonical(self):
        """This page's own address, absolute. The board list answers at /
        and at /directory; / is the one a link should name."""
        path = self.path.split("?", 1)[0]
        if path == "/directory":
            path = "/"
        base = f"https://{LIST_DOMAIN}" if LIST_DOMAIN else SITE_URL.rstrip("/")
        return base + path

    def reply(self, code, body, ctype="text/html; charset=utf-8", extra=None):
        if isinstance(body, str) and "@CANONICAL@" in body:
            body = body.replace("@CANONICAL@", html.escape(self.canonical(), quote=True))
            body = og_fill(body, self.path.split("?", 1)[0])
        raw = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("X-Seen-Address", self.caller())
        for key, value in (extra or {}).items():
            self.send_header(key, str(value))
        self.end_headers()
        self.wfile.write(raw)

    def moved(self, url):
        """A permanent redirect, for a page that lives somewhere else now."""
        self.reply(301, "moved\n", "text/plain; charset=utf-8", {"Location": url})

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        query = self.path.partition("?")[2]
        role = role_for(self.headers.get("Host", ""))
        # The board list, at / and at /directory, with the name search and
        # the badge filter. A filtered or searched view is built for its own
        # request from the same cached rows; the plain list is cached whole.
        if path in ("/", "/directory"):
            (sel, any_), q = filter_query(query), search_query(query)
            if sel or q:
                self.reply(200, directory_page(sel, any_, q, cached(
                    "indexdata", PAGE_CACHE, index_data)))
            else:
                self.reply(200, cached("directory", PAGE_CACHE, lambda: directory_page(
                    data=cached("indexdata", PAGE_CACHE, index_data))))
        elif path == "/data":
            self.reply(200, cached("datapage", PAGE_CACHE,
                                   lambda: simple_page(f"Data - {SITE_NAME}",
                                                       data_page(), role,
                                                       "/data", DATA_DESC)))
        elif path == "/favicon.svg":
            self.reply(200, FAVICON, "image/svg+xml",
                       {"Cache-Control": "public, max-age=86400"})
        elif path in ("/avatar.png", "/apple-touch-icon.png", "/og-card.png"):
            blob = {"/avatar.png": AVATAR_PNG, "/og-card.png": OG_CARD_PNG}.get(path, TOUCH_PNG)
            if blob is None:
                self.reply(404, "no such file\n", "text/plain; charset=utf-8")
            else:
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(blob)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(blob)
        elif path.startswith("/font/"):
            got = font_file(path[len("/font/"):])
            if got is None:
                self.reply(404, "no such file\n", "text/plain; charset=utf-8")
            else:
                blob, ctype = got
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(blob)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(blob)
        elif path == "/rules":
            self.reply(200, simple_page(f"House rules - {SITE_NAME}", RULES,
                                        role, "/rules"))
        elif path == "/how":
            self.reply(200, simple_page(f"How to get listed - {SITE_NAME}", HOW,
                                        role, "/how"))
        elif path == "/api/boards.json":
            def build():
                now = int(time.time())
                with db() as con:
                    settle(con, now)
                    rows = con.execute(
                        "SELECT * FROM boards "
                        "WHERE state IN ('online','offline')").fetchall()
                    steady = steady_boards(con, rows, now)
                return json.dumps({"boards": [board_json(r, r["id"] in steady)
                                              for r in rows]}, indent=1)
            self.reply(200, cached("json", PAGE_CACHE, build),
                       "application/json; charset=utf-8")
        elif path == "/feed.xml":
            self.reply(200, cached("feed", PAGE_CACHE, feed_xml),
                       "application/rss+xml; charset=utf-8")
        elif path == "/health":
            self.reply(200, "ok\n", "text/plain; charset=utf-8")
        elif path.startswith("/skins/"):
            # The stock skins' zips and pictures (site 1.3.17), from the
            # guides' skins/ and nowhere else: see SKINS_DIR.
            got = skins_file(path[len("/skins/"):])
            if got is None:
                self.reply(404, "no such file\n", "text/plain; charset=utf-8")
            else:
                blob, ctype = got
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(blob)))
                if ctype == "application/zip":
                    self.send_header("Content-Disposition", "attachment; filename="
                                     + path[len("/skins/"):])
                self.send_header("Cache-Control", "public, max-age=3600")
                self.end_headers()
                self.wfile.write(blob)
        # The guides, from unleashed_documentation (the split, 2026-09-26).
        elif path in ("/docs", "/docs/"):
            page = docs_index(role)
            if page is None:
                self.reply(404, "no such page\n", "text/plain; charset=utf-8")
            else:
                self.reply(200, page)
        elif path.startswith("/docs/"):
            page = docs_page(path[len("/docs/"):], role)
            if page is None:
                self.reply(404, "no such page\n", "text/plain; charset=utf-8")
            else:
                self.reply(200, page)
        # Last, deliberately. Every branch above is a real endpoint, and a
        # generic page lookup placed before them silently swallows whichever
        # ones happen to look like a page name. It took /health the first
        # time, which is precisely the endpoint update.sh uses to decide
        # whether a deployment worked.
        #
        # A name that is not one of this server's pages is either a guide,
        # which used to live at the top level and now lives under /docs, or
        # a page of the project's own site, which moved to its own server:
        # both are a 301, so no old link breaks.
        # /announce is POST only. Answered here, before the catch-all below,
        # which would take "announce" for a page name and 301 it to the
        # project's site: update.sh's plain-HTTP check GETs it and must see
        # the directory, never a redirect.
        elif path == "/announce":
            self.reply(405, "POST only\n", "text/plain; charset=utf-8", {"Allow": "POST"})
        elif PAGE_NAME.match(path[1:] or ""):
            name = path[1:]
            page = md_page(name, role)
            if page is not None:
                self.reply(200, page)
            elif name in docs_names():
                self.moved("/docs/" + name + ("?" + query if query else ""))
            elif HOME_URL:
                self.moved(HOME_URL + self.path)
            else:
                self.reply(404, "no such page\n", "text/plain; charset=utf-8")
        # The installer, its firmware, the gallery and the donate cover moved
        # with the project's site.
        elif HOME_URL and (path.startswith(("/install/", "/static/", "/pix/"))
                           or path == "/cover.svg"):
            self.moved(HOME_URL + self.path)
        else:
            self.reply(404, simple_page(f"Not here - {SITE_NAME}",
                                        "<h1>Not here</h1>", role))

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > BODY_MAX:
            self.reply(413, json.dumps({"error": "body size"}),
                       "application/json; charset=utf-8")
            return
        raw = self.rfile.read(length)

        if path == "/announce":
            # Only on this endpoint: a local health check is a legitimate
            # direct request with no forwarded headers, and warning about it
            # would be noise. A heartbeat is the one place the address has
            # consequences.
            peer = self.client_address[0] if self.client_address else ""
            if (is_trusted(peer) and not self.headers.get("X-Forwarded-For")
                    and not self.headers.get("X-Real-IP")):
                warn_no_forward(normal_ip(peer) or peer)
            try:
                payload = json.loads(raw.decode("utf-8", "replace"))
                if not isinstance(payload, dict):
                    raise ValueError("not an object")
            except Exception:
                self.reply(400, json.dumps({"error": "bad json"}),
                           "application/json; charset=utf-8")
                return
            code, body, extra = announce(payload, self.caller())
            if code == 200:
                extra = dict(extra or {})
                extra["X-Listing-State"] = body["state"]
                extra["X-Listing-Public-In"] = body["public_in"]
            self.reply(code, json.dumps(body), "application/json; charset=utf-8", extra)
        else:
            self.reply(404, json.dumps({"error": "no such endpoint"}),
                       "application/json; charset=utf-8")


def main():
    setup()
    print(f"directory on {BIND_HOST}:{BIND_PORT}, db {DB_PATH}, "
          f"pending {PENDING_HOURS}h, {PER_ADDRESS} per address", flush=True)
    print("trusting forwarded addresses from: "
          + (", ".join(str(n) for n in TRUSTED_NETS) if TRUSTED_NETS
             else "nobody, so every request is attributed to its socket address"),
          flush=True)
    ThreadingHTTPServer((BIND_HOST, BIND_PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
