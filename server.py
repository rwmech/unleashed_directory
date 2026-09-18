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

PENDING_HOURS = float(os.environ.get("DIRECTORY_PENDING_HOURS", "3"))
EXPIRE_DAYS   = float(os.environ.get("DIRECTORY_EXPIRE_DAYS", "7"))
PER_ADDRESS   = int(os.environ.get("DIRECTORY_PER_ADDRESS", "1"))
MIN_SECONDS   = int(os.environ.get("DIRECTORY_MIN_SECONDS", "30"))
BODY_MAX      = 4096

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


def db():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    return con


def setup():
    with db() as con:
        con.executescript(SCHEMA)


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
    often enough for a list that changes every few minutes."""
    grace = f"(interval_min * 60 * {MISSED_BEATS})"
    con.execute(
        f"UPDATE boards SET state='offline' "
        f"WHERE state='online' AND ? - last_seen > {grace}", (now,))
    con.execute(
        "UPDATE boards SET state='online' "
        "WHERE state='pending' AND ? - streak_start >= ?",
        (now, int(PENDING_HOURS * 3600)))
    con.execute("DELETE FROM boards WHERE ? - last_seen > ?",
                (now, int(EXPIRE_DAYS * 86400)))


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
        settle(con, now)

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


def index_page():
    now = int(time.time())
    with db() as con:
        settle(con, now)
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
    footer = ('<a href="/how">How to get listed</a> &middot; '
              '<a href="/rules">House rules</a> &middot; '
              '<a href="/api/boards.json">JSON</a><br><br>'
              'Activity figures are reported by the boards themselves. '
              '"Up for" is measured here and cannot be fudged.')
    return PAGE.format(title=html.escape(SITE_NAME), count=len(rows), body=body, footer=footer)


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


def simple_page(title, body):
    return PAGE.format(title=html.escape(title), count="", body=body, footer='<a href="/">Back to the list</a>')


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
        if path == "/":
            self.reply(200, index_page())
        elif path == "/rules":
            self.reply(200, simple_page("House rules", RULES))
        elif path == "/how":
            self.reply(200, simple_page("How to get listed", HOW))
        elif path == "/api/boards.json":
            now = int(time.time())
            with db() as con:
                settle(con, now)
                rows = con.execute(
                    "SELECT name, owner, description, host, address, port, nodes, busy, "
                    "state, calls24, minutes24, streak_start, last_seen FROM boards "
                    "WHERE state IN ('online','offline')").fetchall()
            out = [dict(r) for r in rows]
            self.reply(200, json.dumps({"boards": out}, indent=1),
                       "application/json; charset=utf-8")
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
