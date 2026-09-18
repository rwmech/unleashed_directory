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
License:      GNU General Public License v2 or later
SPDX-License-Identifier: GPL-2.0-or-later

This program is free software; you can redistribute it and/or modify it
under the terms of the GNU General Public License as published by the
Free Software Foundation; either version 2 of the License, or (at your
option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General
Public License for more details.

You should have received a copy of the GNU General Public License along
with this program; if not, see <https://www.gnu.org/licenses/>.
===========================================================================
"""

import html
import ipaddress
import json
import os
import re
import secrets
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# --------------------------------------------------------------------------
# Settings. Environment variables win, so the systemd unit is the only place
# a deployment needs to say anything.
# --------------------------------------------------------------------------
DB_PATH       = os.environ.get("DIRECTORY_DB", "directory.db")
BIND_HOST     = os.environ.get("DIRECTORY_HOST", "127.0.0.1")
BIND_PORT     = int(os.environ.get("DIRECTORY_PORT", "8080"))
SITE_NAME     = os.environ.get("DIRECTORY_NAME", "unleashed BBS directory")
SITE_URL      = os.environ.get("DIRECTORY_URL", "https://unleashedbbs.com")

# One server, three faces, chosen by the Host header. A deployment with a
# single domain gets all three under paths instead, so none of this is
# required to run your own.
LIST_DOMAIN   = os.environ.get("DIRECTORY_LIST_DOMAIN", "")   # the board list
ABOUT_DOMAIN  = os.environ.get("DIRECTORY_ABOUT_DOMAIN", "")  # what this is, and why
DATA_DOMAIN   = os.environ.get("DIRECTORY_DATA_DOMAIN", "")   # the machine-readable side

PENDING_HOURS = float(os.environ.get("DIRECTORY_PENDING_HOURS", "3"))
EXPIRE_DAYS   = float(os.environ.get("DIRECTORY_EXPIRE_DAYS", "7"))
PER_ADDRESS   = int(os.environ.get("DIRECTORY_PER_ADDRESS", "1"))
MIN_SECONDS   = int(os.environ.get("DIRECTORY_MIN_SECONDS", "30"))
BODY_MAX      = 4096

# The heartbeats are nothing: a board posts 200 bytes every ten minutes, so
# ten thousand boards is seventeen requests a second. The page is the part
# that could actually be hammered, if somebody links it somewhere busy, so
# it is rendered at most once every PAGE_CACHE seconds and handed out from
# memory in between. A list that changes every few minutes does not need to
# be built fresh for every reader.
PAGE_CACHE    = int(os.environ.get("DIRECTORY_PAGE_CACHE", "10"))
_cache = {}

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
    note         TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS reports (
    id       INTEGER PRIMARY KEY,
    board_id INTEGER NOT NULL,
    at       INTEGER NOT NULL,
    address  TEXT NOT NULL DEFAULT '',
    reason   TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS hits (
    address TEXT PRIMARY KEY,
    at      INTEGER NOT NULL
);
"""

CLEAN = re.compile(r"[\x00-\x1f\x7f]")


def role_for(host):
    """Which of the three sites a request is asking for."""
    host = (host or "").split(":")[0].lower()
    if host.startswith("www."):
        host = host[4:]
    if ABOUT_DOMAIN and host == ABOUT_DOMAIN:
        return "about"
    if DATA_DOMAIN and host == DATA_DOMAIN:
        return "data"
    return "list"


def other_sites(role):
    """The footer line that points at the other two."""
    bits = []
    if LIST_DOMAIN and role != "list":
        bits.append(f'<a href="https://{LIST_DOMAIN}/">boards that are up</a>')
    if ABOUT_DOMAIN and role != "about":
        bits.append(f'<a href="https://{ABOUT_DOMAIN}/">what this is</a>')
    if DATA_DOMAIN and role != "data":
        bits.append(f'<a href="https://{DATA_DOMAIN}/">the data</a>')
    return " &middot; ".join(bits)


def db():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def setup():
    with db() as con:
        con.executescript(SCHEMA)
        # Databases made before the feed existed have no public_at column.
        have = {r["name"] for r in con.execute("PRAGMA table_info(boards)")}
        if "public_at" not in have:
            con.execute("ALTER TABLE boards ADD COLUMN public_at INTEGER NOT NULL DEFAULT 0")
            con.execute("UPDATE boards SET public_at=streak_start WHERE state='online'")


def tidy(value, limit):
    """One line of somebody else's text, made safe to store and print."""
    if not isinstance(value, str):
        return ""
    return CLEAN.sub(" ", value).strip()[:limit]


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
    con.execute("DELETE FROM boards WHERE ? - last_seen > ?",
                (now, int(EXPIRE_DAYS * 86400)))
    return con.total_changes - before


def rate_limited(con, address, now):
    row = con.execute("SELECT at FROM hits WHERE address=?", (address,)).fetchone()
    con.execute("REPLACE INTO hits(address, at) VALUES(?, ?)", (address, now))
    return bool(row) and (now - row["at"]) < MIN_SECONDS


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
        "software":    tidy(payload.get("software"), 20),
        "version":     tidy(payload.get("version"), 20),
        "host":        tidy(payload.get("host"), 80),
        "address":     address,
        "group_key":   group,
        "port":        port,
        "nodes":       int(payload.get("nodes") or 0),
        "busy":        int(payload.get("busy") or 0),
        "uptime":      int(payload.get("uptime") or 0),
        "interval_min": interval,
    }
    # Activity is optional and only there when the sysop turned it on.
    for key in ("calls24", "minutes24"):
        value = payload.get(key)
        fields[key] = int(value) if isinstance(value, int) else None

    with db() as con:
        if rate_limited(con, address, now):
            return 429, {"error": "slow down"}, {}
        if settle(con, now):
            _cache.clear()                             # somebody came or went

        row = None
        if token:
            row = con.execute("SELECT * FROM boards WHERE token=?", (token,)).fetchone()

        if row:                                        # a board we already know
            sets = ", ".join(f"{k}=?" for k in fields)
            args = list(fields.values())
            state = row["state"]
            streak = row["streak_start"]
            if state == "offline":                     # back after a gap
                state, streak = "pending", now
            con.execute(
                f"UPDATE boards SET {sets}, last_seen=?, beats=beats+1, "
                f"state=?, streak_start=? WHERE id=?",
                args + [now, state, streak, row["id"]])
            fresh = con.execute("SELECT * FROM boards WHERE id=?", (row["id"],)).fetchone()
            if fresh["state"] != row["state"]:
                _cache.clear()                         # the page says something new now
            return 200, listing(fresh, now), {"X-Listing-Token": token}

        # a board we have not met before
        live = con.execute(
            "SELECT COUNT(*) AS n FROM boards WHERE group_key=?", (group,)).fetchone()["n"]
        state = "pending" if live < PER_ADDRESS else "queued"
        token = secrets.token_hex(16)
        cols  = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        con.execute(
            f"INSERT INTO boards(token, {cols}, state, first_seen, last_seen, "
            f"streak_start, beats) VALUES(?, {marks}, ?, ?, ?, ?, 1)",
            [token] + list(fields.values()) + [state, now, now, now])
        fresh = con.execute("SELECT * FROM boards WHERE token=?", (token,)).fetchone()
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


# --------------------------------------------------------------------------
# The web page. Dark, monospace, the same colours as the board.
# --------------------------------------------------------------------------
PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<link rel="alternate" type="application/rss+xml" title="New boards" href="/feed.xml">
<style>
:root {{ color-scheme: dark; }}
body {{ background:#0b0b0f; color:#c8c8c8; font:14px/1.5 ui-monospace,Menlo,Consolas,monospace;
       margin:0; padding:16px; }}
main {{ max-width:900px; margin:0 auto; }}
h1 {{ color:#4ce0e0; font-size:18px; margin:0 0 4px; }}
h1 span {{ color:#666; }}
p.lead {{ color:#888; margin:0 0 20px; }}
a {{ color:#6cf; }}
table {{ border-collapse:collapse; width:100%; }}
th {{ text-align:left; color:#4ce0e0; border-bottom:1px solid #222; padding:6px 8px; font-weight:normal; }}
td {{ padding:6px 8px; border-bottom:1px solid #161616; vertical-align:top; }}
tr:hover td {{ background:#111; }}
.name {{ color:#6ee36e; }}
.addr {{ color:#e8e8e8; }}
.desc {{ color:#8a8a8a; }}
.owner {{ color:#d0b050; }}
.on {{ color:#6ee36e; }}
.off {{ color:#666; }}
.pending {{ color:#d0b050; }}
.none {{ color:#666; padding:24px 8px; }}
footer {{ margin-top:28px; color:#555; border-top:1px solid #222; padding-top:12px; }}
article {{ max-width:70ch; }}
article h2 {{ color:#4ce0e0; font-size:15px; margin:28px 0 6px; font-weight:normal; }}
article p {{ margin:0 0 14px; }}
article b {{ color:#e8e8e8; font-weight:normal; }}
article .pull {{ color:#6ee36e; border-left:2px solid #234; padding-left:12px; margin:18px 0; }}
pre {{ background:#111; border:1px solid #222; padding:12px; overflow-x:auto; color:#9fb; }}
code {{ color:#9fb; }}
dl {{ margin:0 0 14px; }} dt {{ color:#d0b050; margin-top:10px; }} dd {{ margin:2px 0 0 16px; }}
</style></head><body><main>
<h1>{title} <span>{count} boards</span></h1>
<p class="lead">Boards that are up right now. Dial them with any telnet client.</p>
{body}
<footer>{footer}</footer>
</main></body></html>"""


def human_ago(seconds):
    if seconds < 90:
        return "just now"
    if seconds < 5400:
        return f"{seconds // 60} min ago"
    if seconds < 172800:
        return f"{seconds // 3600} h ago"
    return f"{seconds // 86400} d ago"


def human_streak(seconds):
    if seconds < 5400:
        return f"{max(1, seconds // 60)}m"
    if seconds < 172800:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def board_rows(rows, now):
    out = []
    for r in rows:
        where = r["host"] or r["address"]
        state = r["state"]
        klass = {"online": "on", "offline": "off", "pending": "pending"}.get(state, "off")
        if state == "online":
            label = f"up, {r['busy']}/{r['nodes']} in use" if r["nodes"] else "up"
        elif state == "offline":
            label = f"quiet, {human_ago(now - r['last_seen'])}"
        else:
            label = state
        activity = ""
        if r["minutes24"] is not None:
            activity = f"{r['minutes24']} caller-min/24h"
        elif r["calls24"] is not None:
            activity = f"{r['calls24']} calls/24h"
        out.append(
            "<tr>"
            f"<td class='name'>{html.escape(r['name'])}<br>"
            f"<span class='desc'>{html.escape(r['description'])}</span></td>"
            f"<td class='addr'>{html.escape(where)} {r['port']}</td>"
            f"<td class='owner'>{html.escape(r['owner'])}</td>"
            f"<td class='{klass}'>{html.escape(label)}</td>"
            f"<td class='desc'>{html.escape(activity)}</td>"
            f"<td class='desc'>{human_streak(now - r['streak_start'])}</td>"
            "</tr>")
    return "".join(out)


def cached(key, seconds, build):
    hit = _cache.get(key)
    now = time.time()
    if hit and now - hit[0] < seconds:
        return hit[1]
    value = build()
    _cache[key] = (now, value)
    return value


def index_page():
    now = int(time.time())
    with db() as con:
        settle(con, now)                               # keep the list honest on read
        rows = con.execute(
            "SELECT * FROM boards WHERE state IN ('online','offline') "
            "ORDER BY state='online' DESC, "
            "COALESCE(minutes24, busy * 60, 0) DESC, streak_start ASC").fetchall()
    if rows:
        body = ("<table><tr><th>Board</th><th>Dial</th><th>Sysop</th>"
                "<th>State</th><th>Activity</th><th>Up for</th></tr>"
                + board_rows(rows, now) + "</table>")
    else:
        body = "<p class='none'>No boards listed yet. Yours could be the first.</p>"
    links = other_sites("list")
    footer = ((links + "<br><br>") if links else "") + (
              '<a href="/how">How to get listed</a> &middot; '
              '<a href="/rules">House rules</a> &middot; '
              '<a href="/feed.xml">RSS</a> &middot; '
              '<a href="/api/boards.json">JSON</a><br><br>'
              'Activity figures are reported by the boards themselves. '
              '"Up for" is measured here and cannot be fudged.')
    return PAGE.format(title=html.escape(SITE_NAME), count=len(rows), body=body, footer=footer)


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
        body = f"{desc}<br>Dial: {where}"
        if owner:
            body += f"<br>Sysop: {owner}"
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
has and how many are busy, whether it is up, and how long it has been up. Cached for
a few seconds.</dd>
<dt><code>POST /announce</code></dt>
<dd>How a board lists itself. One JSON object, about 200 bytes, repeated every few
minutes. Plain HTTP on purpose: the boards are microcontrollers with no TLS stack.</dd>
<dt><code>GET /health</code></dt>
<dd>Two bytes, for uptime checks.</dd>
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


RULES = """<h1>House rules</h1>
<p class="lead">This is a list of boards. It does not need many rules.</p>
<ul>
<li><b>No hate.</b> A board whose name or description attacks people for who they are does not get listed here.</li>
<li><b>Be honest about what you are.</b> The description should describe the board.</li>
<li><b>It is public.</b> Everything you send appears on this page. Assume it is read.</li>
<li><b>Get along.</b> That is the whole of it.</li>
</ul>
<p>These rules bind this directory, not you. The protocol is published, the server is
free software, and anyone can run a directory with different rules or none at all.
Taking a board off this list does not take it off the internet, and it was never
meant to.</p>"""

HOW = """<h1>How to get listed</h1>
<p class="lead">Your board announces itself. You do not fill in a form.</p>
<pre>[plugin:announce]
enabled     = yes
name        = The Rusty Modem
owner       = KE9CXN
description = A BBS on a chip in a shack in Illinois
servers     = http://unleashedbbs.com/announce</pre>
<p>Switch it on and wait. A listing becomes public after three hours of
uninterrupted heartbeats, which is what keeps drive-by spam off the page, and
it disappears when the heartbeats stop. <code>ANNOUNCE</code> on your board
shows how long is left.</p>
<p>Running something other than µnleashed? The protocol is a single HTTP POST and
it is documented in <a href="https://github.com/rwmech/unleashed_directory">the
server repository</a>. Anything that speaks it gets listed.</p>"""


ANIM = """
<style>
.scene { position:relative; height:7.4em; margin:18px 0 22px; }
.scene pre { position:absolute; left:0; top:0; margin:0; opacity:0;
             color:#6ee36e; background:none; border:0; padding:0;
             animation: flip 3.2s steps(1,end) infinite; }
.scene pre:nth-child(1) { animation-delay:0.0s }
.scene pre:nth-child(2) { animation-delay:0.4s }
.scene pre:nth-child(3) { animation-delay:0.8s }
.scene pre:nth-child(4) { animation-delay:1.2s }
.scene pre:nth-child(5) { animation-delay:1.6s }
.scene pre:nth-child(6) { animation-delay:2.0s }
.scene pre:nth-child(7) { animation-delay:2.4s }
.scene pre:nth-child(8) { animation-delay:2.8s }
@keyframes flip { 0%,12.4% { opacity:1 } 12.5%,100% { opacity:0 } }
@media (prefers-reduced-motion: reduce) {
  .scene { height:auto }
  .scene pre { position:static; opacity:1; animation:none }
  .scene pre:not(:first-child) { display:none }
}
.chart { color:#8a8a8a; background:#0d0d12; border:1px solid #1d1d24;
         padding:14px; overflow-x:auto; line-height:1.35; }
.chart b { color:#e06c6c; font-weight:normal; }
.chart i { color:#6ee36e; font-style:normal; }
</style>
<div class="scene">
<pre>   [ YOU ]                                   [ THE BOARD ]
     |                                              |
     |  o--------------------------------------     |
     |                                              |
   40 columns of text                       a chip on a shelf</pre>
<pre>   [ YOU ]                                   [ THE BOARD ]
     |                                              |
     |  ---o-----------------------------------     |
     |                                              |
   40 columns of text                       a chip on a shelf</pre>
<pre>   [ YOU ]                                   [ THE BOARD ]
     |                                              |
     |  -------o-------------------------------     |
     |                                              |
   40 columns of text                       a chip on a shelf</pre>
<pre>   [ YOU ]                                   [ THE BOARD ]
     |                                              |
     |  -----------o---------------------------     |
     |                                              |
   40 columns of text                       a chip on a shelf</pre>
<pre>   [ YOU ]                                   [ THE BOARD ]
     |                                              |
     |     ---------------------------o--------     |
     |                                              |
   40 columns of text                       a chip on a shelf</pre>
<pre>   [ YOU ]                                   [ THE BOARD ]
     |                                              |
     |     -----------------------o------------     |
     |                                              |
   40 columns of text                       a chip on a shelf</pre>
<pre>   [ YOU ]                                   [ THE BOARD ]
     |                                              |
     |     -----------------o------------------     |
     |                                              |
   40 columns of text                       a chip on a shelf</pre>
<pre>   [ YOU ]                                   [ THE BOARD ]
     |                                              |
     |     -----------o------------------------     |
     |                                              |
   40 columns of text                       a chip on a shelf</pre>
</div>"""


ABOUT = """<h1>&micro;nleashed</h1>
<p class="lead">Electronic freedom on a microcontroller. No web, no cloud, no browser.</p>
""" + ANIM + """
<article>

<p><b>A bulletin board is a machine that answers a phone number.</b> Somebody put a
spare computer in a spare room, hung a modem off it, and other people called it.
No terms of service. No algorithm deciding what you saw. No third party keeping a
copy for later. The sysop was a person you could ring up and argue with, and if
you did not like how a board was run you started your own, because the barrier to
entry was a second phone line.</p>

<h2>Where this came from</h2>

<p><a href="https://en.wikipedia.org/wiki/CBBS">CBBS</a> went online in Chicago on
16 February 1978, written by Ward Christensen with hardware by Randy Suess. The
January blizzard that shut the city down handed them the quiet weeks to finish it.
It ran on an S-100 machine with 64 kilobytes of memory and answered one caller at
a time.</p>

<p>Thousands of boards followed. Each one was somebody's own idea of what a
community should look like: a music board, a board for one town, a board that was
really just its sysop and eleven friends. At the
<a href="https://en.wikipedia.org/wiki/Bulletin_board_system">peak in the
mid-1990s</a> an estimated 60,000 were running in the United States alone, and
<a href="https://en.wikipedia.org/wiki/FidoNet">FidoNet</a> tied tens of thousands
of them into a store-and-forward network that moved mail around the world overnight,
for free, run entirely by hobbyists.</p>

<p>Almost all of them ran on hardware weaker than the five dollar chip this software
runs on.</p>

<h2>What replaced it</h2>

<p>The web arrived and it was better at almost everything, and then it consolidated.
Now the conversation lives on machines you cannot see, indexed, scraped to train
something, ranked, monetised, and deleted at somebody else's discretion. You do not
own the room, the member list, the history, or the right to keep any of it. You rent
all of it, and the rent is paid in attention and data.</p>

<p class="pull">The thing that was lost was not the modem noise. It was that the
system belonged to somebody you could name.</p>

<h2>What this is</h2>

<p>A telnet BBS that runs on a bare ESP32, a microcontroller the size of a postage
stamp, and grows into an IoT terminal server through plugins. Nodes, handles, a user
list, a chat room in the style of DDial and Gtalk, messages, doors, a caller log, a
sysop who can page you.</p>

<p><b>The board is yours.</b> Not an account on somebody's platform, not a tenant on a
server farm, not a feature that can be deprecated out from under you. A chip you own,
on a port you chose, running software you can read all of in an afternoon and change
when you disagree with it. Switch it off and it is off. Leave it in a drawer for a
year, plug it back in, and it still works, because there is nothing at the other end
that has to still exist.</p>

<p>The user list is a text file. The settings are a text file. A message goes from one
caller to another through a chip on your shelf and is gone the moment it is read.
There is no account to create, nothing to subscribe to, and no vendor who can change
the deal. It is GPL, so nobody can take it away from you later, including the person
who wrote it.</p>

<h2>Privacy forward, and what that actually means</h2>

<p>Every system you use was built by somebody, and the question worth asking is who it
was built to serve. A board is built to serve the person who owns it. That is the whole
of the privacy argument, and everything else follows from it.</p>

<p><b>There is no third party in the middle.</b> Not a company, not a platform, not an
advertiser, not a model being trained. A message goes from one caller to another through
a chip on somebody's shelf and it is gone when it is read. Nobody is standing between
those two people taking a copy, because there is nowhere for a copy to go and nobody
whose business it would be.</p>

<p>Here is the difference, drawn out.</p>

<pre class="chart">  CALLING A WEBSITE

  you  -->  DNS  -->  CDN  -->  load balancer  -->  the app
             |         |             |                 |
             v         v             v                 v
         <b>who asked</b>  <b>edge logs</b>   <b>session</b>          <b>account</b>
         <b>and when</b>   <b>your IP</b>     <b>fingerprint</b>      <b>history</b>
             |         |             |                 |
             +---------+------+------+-----------------+
                              |
                              v
                <b>analytics . ad exchange . data broker</b>
                <b>model training . retention policy</b>
                <b>breach disclosure in eighteen months</b>
                              |
                              v
                    <b>you cannot audit any of it</b>


  CALLING A BOARD

  you  -->  your router  -->  <i>a chip you own</i>
                                    |
                                    v
                            <i>a text file you</i>
                            <i>can open and read</i>

                     <i>that is the entire list</i></pre>

<p>The left-hand column is not a conspiracy. Every box on it exists for a reason
somebody could defend, and most of them were added by decent engineers solving a real
problem. It is simply what a modern service is made of, and the effect of all those
reasonable decisions together is that you cannot say who holds what about you, or for
how long, or what it will be used for next year.</p>

<p>The right-hand column has no boxes to add. There is no account system to breach, no
analytics to leak, no retention policy to change, no company to be acquired by somebody
with different ideas. What is not built cannot be exploited, and what was never
collected cannot be handed over.</p>

<h2>The power is in your hands, literally</h2>

<p>You flash the firmware. You set the password. You decide who gets a handle, what the
board is called, what the rules are, and whether it is on the internet at all. You can
read every line of the software before you trust it, and change the parts you disagree
with, and nobody can stop you, because the licence says so and the source is right
there.</p>

<p class="pull">If you switch it off, it is off. Nobody else gets a say in that.</p>

<p>Turn the board off and the service ends. Not "your account is deactivated but we
retain your data for legitimate business purposes" — ends. Pull the plug and the chip
stops answering. Wipe the flash and the user list is gone. That is what owning something
means, and it is startling how unusual it has become.</p>

<h2>Honest about the limits</h2>

<p>Telnet is plain text, because a Commodore 64 cannot do TLS and pretending otherwise
would be worse than saying so. This keeps a board off the public internet's record;
it does not keep it off the wire. If a conversation has to survive somebody watching
the link, put the board behind a VPN or leave it on the local network. Privacy you can
explain in one sentence beats privacy you have to take on faith.</p>

<h2>Small on purpose</h2>

<p>One static binary. Static allocation, no heap in the main loop, a fixed memory
budget on a chip with 520 KB of RAM. No web stack, no scripting runtime, no package
tree to audit at two in the morning, no telemetry, no update that arrives without you.
What is not built cannot be exploited, and what fits in one head can be trusted by the
person whose head it fits in.</p>

<h2>Serial did not die</h2>

<p><a href="https://en.wikipedia.org/wiki/RS-232">RS-232</a> was standardised by the
EIA in 1960 and still runs the console and management ports on network equipment,
industrial controllers and test gear, and its asynchronous framing survives on nearly
every microcontroller made since as a
<a href="https://en.wikipedia.org/wiki/Universal_asynchronous_receiver-transmitter">TTL-level
UART</a>. Sixty-five years on, the way a machine from 1982 talks is still the way you
talk to the switch in the rack. That is why a
<a href="https://en.wikipedia.org/wiki/Commodore_64">Commodore 64</a> and a laptop
bought this year can both call one of these boards, and why a board can turn round and
drive whatever is hanging off its own serial port.</p>

<h2>Why the micro sign</h2>

<p>Because it runs on a microcontroller, and because microcomputers are what put
computing into the hands of people who were never going to be given time on a
mainframe. The <a href="https://en.wikipedia.org/wiki/Altair_8800">Altair 8800</a> in
1975, then the Apple II, the Commodore PET and the TRS-80 in
<a href="https://en.wikipedia.org/wiki/History_of_personal_computers#1977_and_the_emergence_of_the_%22Trinity%22">1977</a>,
took the computer out of the raised-floor room that somebody else controlled and put it
on a kitchen table. This is the same move, one more time, on a chip you can lose in a
drawer. Where the symbol cannot be shown, it is written <code>unleashed</code>.</p>

<h2>You can do this today</h2>

<p>Not as a re-enactment: as a live system with callers on it tonight. Flash a board,
give it your wifi, forward one port on your router, and you are running a public BBS.
No hosting bill, no domain required, no provider to ask permission from, no account
with anybody. A chip on a shelf and one line in your router.</p>

<p><a href="https://github.com/rwmech/unleashed_BBS">The source, the documentation and
the build instructions are here.</a> It is free software under the GNU General Public
License, version 2 or later.</p>

</article>"""


def simple_page(title, body, role="list"):
    links = other_sites(role)
    return PAGE.format(title=html.escape(title), count="", body=body,
                       footer=links or '<a href="/">Back to the list</a>')


# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "unleashed-directory/1.0"

    def log_message(self, fmt, *args):      # one tidy line, not two
        print(f"{self.caller()} {fmt % args}", flush=True)

    def caller(self):
        forwarded = self.headers.get("X-Forwarded-For", "")
        if forwarded:                        # behind Caddy, the real address is here
            return forwarded.split(",")[0].strip()
        return self.client_address[0]

    def reply(self, code, body, ctype="text/html; charset=utf-8", extra=None):
        raw = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("X-Seen-Address", self.caller())
        for key, value in (extra or {}).items():
            self.send_header(key, str(value))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        role = role_for(self.headers.get("Host", ""))
        if path == "/":
            if role == "about":
                self.reply(200, simple_page("unleashed", ABOUT, "about"))
            elif role == "data":
                self.reply(200, cached("data", PAGE_CACHE,
                                       lambda: simple_page("Data", data_page(), "data")))
            else:
                self.reply(200, cached("index", PAGE_CACHE, index_page))
        elif path == "/rules":
            self.reply(200, simple_page("House rules", RULES))
        elif path == "/how":
            self.reply(200, simple_page("How to get listed", HOW))
        elif path == "/api/boards.json":
            def build():
                now = int(time.time())
                with db() as con:
                    settle(con, now)
                    rows = con.execute(
                        "SELECT name, owner, description, host, address, port, nodes, busy, "
                        "state, calls24, minutes24, streak_start, last_seen FROM boards "
                        "WHERE state IN ('online','offline')").fetchall()
                return json.dumps({"boards": [dict(r) for r in rows]}, indent=1)
            self.reply(200, cached("json", PAGE_CACHE, build),
                       "application/json; charset=utf-8")
        elif path == "/feed.xml":
            self.reply(200, cached("feed", PAGE_CACHE, feed_xml),
                       "application/rss+xml; charset=utf-8")
        elif path == "/health":
            self.reply(200, "ok\n", "text/plain; charset=utf-8")
        else:
            self.reply(404, simple_page("Not here", "<h1>Not here</h1>"))

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > BODY_MAX:
            self.reply(413, json.dumps({"error": "body size"}),
                       "application/json; charset=utf-8")
            return
        raw = self.rfile.read(length)

        if path == "/announce":
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
    ThreadingHTTPServer((BIND_HOST, BIND_PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
