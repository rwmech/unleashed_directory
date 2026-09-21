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
import pathlib
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
SITE_NAME     = os.environ.get("DIRECTORY_NAME", "µnleashed BBS directory")
SITE_URL      = os.environ.get("DIRECTORY_URL", "https://unleashedbbs.com")
# What a paste of the link says about itself, in a forum, a chat or a search
# result. A directory spreads by somebody pasting it somewhere, and until
# now that paste produced a bare link with no title card at all.
SITE_DESC     = ("Bulletin board systems that are up right now. Dial one with "
                 "any telnet client. No account, no tracking, no web.")

# One server, three faces, chosen by the Host header. A deployment with a
# single domain serves the other two under /about and /data, so none of this
# is required to run your own.
LIST_DOMAIN   = os.environ.get("DIRECTORY_LIST_DOMAIN", "")   # the board list
ABOUT_DOMAIN  = os.environ.get("DIRECTORY_ABOUT_DOMAIN", "")  # what this is, and why
DATA_DOMAIN   = os.environ.get("DIRECTORY_DATA_DOMAIN", "")   # the machine-readable side

# Who is allowed to tell us where a request came from.
#
# The server listens on loopback and a reverse proxy faces the internet, so
# the socket address is always the proxy's. The caller's real address is in
# X-Forwarded-For, and that header is supplied by whoever is talking to us,
# which means it can only be believed when the connection itself comes from
# somewhere we trust. Trusting it unconditionally would be worse than not
# reading it at all: three separate things here key off the address, and
# every one of them becomes forgeable.
#
#   - X-Seen-Address is handed back to a board as a rough DDNS. A board
#     could make us tell a different board a wrong address.
#   - One automatic listing per address, per /64 on v6. Claim a fresh
#     address per heartbeat and the cap is gone.
#   - Report dedupe counts distinct reporter networks, which is the whole
#     defence against one person delisting somebody they dislike.
#
# Loopback by default because that is how Caddy reaches this. Accepts bare
# addresses or CIDR, comma separated. Empty means trust nothing, which is
# the right setting for a server facing the internet directly.
TRUSTED_PROXIES = os.environ.get("DIRECTORY_TRUSTED_PROXIES", "127.0.0.1,::1")

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
MIN_SECONDS   = int(os.environ.get("DIRECTORY_MIN_SECONDS", "30"))
# How many extra entries one address may hold beyond its published one,
# waiting for a human. Small on purpose: it is the stop on a board that has
# forgotten its token, or on somebody posting in a loop.
SPARE_ROWS    = int(os.environ.get("DIRECTORY_SPARE_ROWS", "3"))
BODY_MAX      = 4096

# The heartbeats are nothing: a board posts 200 bytes every ten minutes, so
# ten thousand boards is seventeen requests a second. The page is the part
# that could actually be hammered, if somebody links it somewhere busy, so
# it is rendered at most once every PAGE_CACHE seconds and handed out from
# memory in between. A list that changes every few minutes does not need to
# be built fresh for every reader.
PAGE_CACHE    = int(os.environ.get("DIRECTORY_PAGE_CACHE", "10"))
# The board list is a live thing: who is on changes minute to minute, so the
# page reloads itself rather than going stale in a tab somebody left open.
# A meta refresh, not a script, because a reader should not have to run code
# to read a list. /install is the only page here that loads any, and it does
# so only when there is firmware to install; see EWT_SCRIPT. It is cheap: the page
# is rendered at most once every PAGE_CACHE seconds however many ask for it.
LIST_SECONDS  = int(os.environ.get("DIRECTORY_LIST_REFRESH", "60"))
LIST_REFRESH  = (f'<meta http-equiv="refresh" content="{LIST_SECONDS}">'
                 if LIST_SECONDS > 0 else "")
_cache = {}

# --------------------------------------------------------------------------
# Firmware images, for the browser installer on /install.
#
# The directory on disk is the whole of the state. server.py walks it and
# builds the ESP Web Tools manifest from what is actually there, rather than
# reading a list somebody maintains, and that choice buys three things:
#
#   - a release cannot be half-published, because a manifest part is only
#     ever emitted for a file that was just found on disk;
#   - "no firmware available yet" is the absence of files rather than a flag
#     anybody has to remember to flip, so the page cannot lie in either
#     direction;
#   - cutting a release is copying files in, which is the whole of it.
#
# It is the same argument pix_html() already makes about card art: the page
# has to be correct today, with the directory empty, and correct again the
# moment something lands in it.
#
# Pointing this outside the checkout is supported on purpose. deploy/update.sh
# is a git pull, so anything in firmware/ is in the repository and two
# releases is a few megabytes of it; a deployment that would rather keep them
# on a larger volume moves this and nothing else changes.
FIRMWARE_DIR  = pathlib.Path(os.environ.get(
    "DIRECTORY_FIRMWARE_DIR",
    str(pathlib.Path(__file__).resolve().parent / "firmware")))
# How many releases the page offers, newest first. Rob's figure is two. The
# older ones on disk are simply not listed, so a third left behind by
# accident cannot appear on the page.
FIRMWARE_KEEP = int(os.environ.get("DIRECTORY_FIRMWARE_KEEP", "2"))

# A release directory is named for its version and nothing else, which is
# what lets firmware/README.md sit beside the releases without being mistaken
# for one.
FIRMWARE_VER  = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,4})$")
FIRMWARE_CHIP = re.compile(r"^[a-z][a-z0-9]{2,11}$")

# ESP Web Tools is pinned to an exact version, never to a floating tag.
# Their own docs tell you to pin to the major (@10) while the docs page
# itself loads the unpinned URL; a major tag still means the code a visitor
# runs can change under us between one reader and the next, and this is the
# only third-party code anybody loads from this site.
#
# The path matters: dist/web/install-button.js is the self-contained web
# bundle. dist/install-button.js is the NPM entry point and has bare imports
# a browser cannot resolve. "?module" is unpkg's own flag for the ESM build
# and is what the project's documentation shows.
EWT_VERSION = "10.4.0"
EWT_SCRIPT  = ("https://unpkg.com/esp-web-tools@" + EWT_VERSION
               + "/dist/web/install-button.js?module")

# The chip families this can serve, keyed by the directory name a release
# uses. A second family is a directory drop and an entry here, never a
# rewrite: the reference board is a bare ESP32-WROOM-32E and an ESP32-S3
# with PSRAM is the documented upgrade path, so the shape has to survive
# that without being rebuilt around it.
#
# The value is the chipFamily string ESP Web Tools matches against the chip
# it reads out of the board, and that family's bootloader offset. The
# bootloader offset is NOT universal: 0x1000 on the ESP32 and S2, 0x0 on the
# RISC-V parts, which is exactly the kind of number a tutorial written for a
# different board gets wrong.
FLASH_FAMILIES = {
    "esp32":   ("ESP32",    0x1000),
    "esp32s2": ("ESP32-S2", 0x1000),
    "esp32s3": ("ESP32-S3", 0x0),
    "esp32c3": ("ESP32-C3", 0x0),
}

# What gets written, and where. Read out of the firmware repository rather
# than recalled: CONFIG_BOOTLOADER_OFFSET_IN_FLASH and
# CONFIG_PARTITION_TABLE_OFFSET in its generated sdkconfig.esp32dev, and the
# ota_0 and storage rows of its partitions.csv.
#
# None means "this family's bootloader offset", from FLASH_FAMILIES above.
#
# littlefs.bin is the storage partition, which is the screens. The other two
# filesystems are deliberately absent: userdata holds the accounts, the live
# configuration and each plugin's files, and logs holds the caller log. Not
# writing them is what lets somebody reinstall over a board they already run
# without losing it, and it is the same split "pio run -t flashall" respects.
#
# There is no otadata part. With otadata erased the bootloader falls back to
# the first OTA slot, which is where the application is written. The day OTA
# updates land, a board that has already flipped to ota_1 will need that
# thought about again.
FLASH_PARTS = (("bootloader.bin", None),
               ("partitions.bin", 0x8000),
               ("firmware.bin",   0x20000),
               ("littlefs.bin",   0x3C0000))

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


def site_url(target, role, path="/"):
    """A link to one of the three faces: absolute only when it crosses a
    domain, so a single-host deployment is never sent to a name that is not
    configured. With no domain for that face, it is served under its own
    path on this one, which is what /about and /data exist for."""
    host = {"list": LIST_DOMAIN, "about": ABOUT_DOMAIN, "data": DATA_DOMAIN}.get(target, "")
    if target == role:
        return path
    if not host:
        return {"list": "/", "about": "/about", "data": "/data"}.get(target, path)
    return f"https://{host}{path}"


# What is in the menu, in the order a newcomer needs it: what is up, what
# this is, who it suits, what to call one with, what happens when you do,
# how to have one, how to open yours up, how to be listed, the data.
#
# "Who it's for" sits next to the manifesto on purpose, because the two
# answer different questions: the manifesto is why any of this matters, and
# that page is whether it is any use to the person reading. It is a page
# rather than a section of the manifesto because its job is to talk somebody
# into setting a board up, and that wants a link you can paste at a club or
# a school, not an anchor two thirds of the way down a long argument.
NAV = (("list",  "/",          "Boards"),
       ("about", "/",          "What this is"),
       ("list",  "/whofor",    "Who it's for"),
       ("list",  "/terminals", "Terminals"),
       ("list",  "/firstcall", "First call"),
       ("list",  "/build",     "Build one"),
       ("list",  "/forward",   "Go public"),
       ("list",  "/how",       "Get listed"),
       ("data",  "/",          "Data"))

# A page that is not in the menu still has a place in it. Every one of these
# is a child of a section that is, so the section lights up rather than
# nothing. Without it, six pages said nothing about where the reader was and
# two of them said "Boards", which is worse: a nav built entirely around
# reverse-video "you are here" was actively lying on them.
NAV_SECTION = {
    "/dialing":         "/terminals",
    "/privacy":         "/firstcall",
    # Deliberately not in the menu. Both are reached from the page they
    # belong to: a nine item menu is already at the edge of what a phone can
    # carry, and neither is something a general visitor is hunting for.
    # Being off the menu is not the same as being buried, and they are the
    # first and the most prominent links on /whofor.
    "/kids":            "/whofor",
    "/teachers":        "/whofor",
    "/sdcard":          "/build",
    # Putting the firmware on a board is a step of building one, so it
    # lights up the section a reader came from. Not in the menu itself:
    # nine items is already the edge of what a phone can carry, and this is
    # reached from /build and from the footer of every page.
    "/install":         "/build",
    "/forward-netgear": "/forward",
    "/forward-tplink":  "/forward",
    "/forward-asus":    "/forward",
    "/forward-xfinity": "/forward",
    "/forward-mesh":    "/forward",
}


def nav_html(role, here=""):
    here = NAV_SECTION.get(here, here)
    out = []
    for target, path, label in NAV:
        # Matched on the link this deployment would actually serve, not on
        # (face, path): with one domain the about face lives at /about, so
        # comparing the NAV entry's own path would never match it. There is
        # no fallback to the index any more. An unmarked menu is honest; a
        # wrongly marked one is not.
        href = site_url(target, role, path)
        # Built by concatenation rather than an f-string: a backslash is not
        # allowed inside an f-string expression before Python 3.12, and the
        # server has to run on whatever the droplet ships.
        cls = ' class="here"' if href == here else ""
        out.append('<a' + cls + ' href="' + href + '">' + label + '</a>')
    return "<nav>" + "".join(out) + "</nav>"


def head_html(role, here=""):
    """The top of every page: wordmark, then the same menu everywhere."""
    return logo_html() + nav_html(role, here)


def foot_html(role, extra=""):
    """The bottom of every page: the other faces, then the same links.

    Identical on all three so a reader learns it once. Anything specific to
    one page goes in extra, underneath.
    """
    others = other_sites(role)
    # /dialing is in here because it fixes the exact problem a first-time
    # visitor hits: they click an address on the front page and nothing
    # happens. It used to be reachable from one sentence at the bottom of
    # /terminals and from a title= attribute on every dial link, and a
    # title is invisible on every touch device and clickable nowhere.
    links = (f'<a href="{site_url("list", role, "/build")}">Build one</a> &middot; '
             f'<a href="{site_url("list", role, "/install")}">Install</a> &middot; '
             f'<a href="{site_url("list", role, "/terminals")}">Terminals</a> &middot; '
             f'<a href="{site_url("list", role, "/dialing")}">Dial links</a> &middot; '
             f'<a href="{site_url("list", role, "/forward")}">Go public</a> &middot; '
             f'<a href="{site_url("list", role, "/how")}">Get listed</a> &middot; '
             f'<a href="{site_url("list", role, "/rules")}">House rules</a> &middot; '
             f'<a href="{site_url("list", role, "/feed.xml")}">RSS</a> &middot; '
             f'<a href="{site_url("data", role, "/api/boards.json")}">JSON</a>')
    parts = [others, links] if others else [links]
    if extra:
        parts.append(extra)
    return "<br><br>".join(parts)




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
        # Databases made before the busy-hours chart have no offset to
        # bucket by. Zero means UTC, which is what they were doing anyway.
        if "tz_offset" not in have:
            con.execute("ALTER TABLE boards ADD COLUMN tz_offset INTEGER NOT NULL DEFAULT 0")


def tidy(value, limit):
    """One line of somebody else's text, made safe to store and print."""
    if not isinstance(value, str):
        return ""
    return CLEAN.sub(" ", value).strip()[:limit]


def trusted_nets(spec):
    """The trusted proxy list, as networks. Junk entries are dropped with a
    complaint rather than silently, because a typo here quietly turns the
    address handling back into the broken version."""
    nets = []
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            print(f"ignoring bad DIRECTORY_TRUSTED_PROXIES entry: {part!r}",
                  flush=True)
    return nets


TRUSTED_NETS = trusted_nets(TRUSTED_PROXIES)
# Said once, not once per heartbeat. A board announcing from behind a proxy
# that is not forwarding the caller's address is the exact shape of a bug
# that is otherwise completely silent: every board looks like it lives at
# the proxy, one listing gets published and the rest queue for ever, and
# each one is told its public address is 127.0.0.1.
_warned_no_forward = False


def warn_no_forward(peer):
    global _warned_no_forward
    if _warned_no_forward:
        return
    _warned_no_forward = True
    print(f"WARNING: announce from trusted proxy {peer} carried no "
          "X-Forwarded-For and no X-Real-IP, so every board will look like "
          "it came from that address. Check the reverse proxy configuration; "
          "deploy/Caddyfile is the reference.", flush=True)


def normal_ip(text):
    """One address from a header or a socket, canonical, or "".

    Handles the shapes that actually turn up in a forwarding chain: a bare
    address, one with a port, an IPv6 literal in brackets, and the v4
    mapped form, which has to become plain v4 or group_of would hand it a
    /64 and treat one machine as a whole network.
    """
    s = (text or "").strip()
    if not s:
        return ""
    if s.startswith("["):                      # [::1] or [::1]:443
        s = s[1:].split("]", 1)[0]
    elif s.count(":") == 1:                    # 1.2.3.4:5678, never bare v6
        s = s.split(":", 1)[0]
    try:
        ip = ipaddress.ip_address(s)
    except ValueError:
        return ""
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return str(ip)


def is_trusted(address, nets=None):
    ip = normal_ip(address)
    if not ip:
        return False
    ip = ipaddress.ip_address(ip)
    return any(ip in net for net in (TRUSTED_NETS if nets is None else nets))


def client_ip(peer, forwarded="", real_ip="", nets=None):
    """Who actually made this request.

    The peer is the socket address. When it is not a proxy we trust, that is
    the answer and the headers are not read at all: anything on the internet
    can send an X-Forwarded-For, so a header from a stranger is a claim, not
    evidence.

    When the peer is trusted, walk the chain from the RIGHT. The right hand
    end is the part our own proxy appended and is the only part it vouches
    for; the left hand end is whatever the caller sent us and is entirely
    theirs to choose. Taking the leftmost entry is the classic way to get
    this wrong, and it is what this server did until now. Trusted proxies
    are skipped on the way left, so a chain of our own proxies resolves to
    the caller in front of them.

    Anything malformed stops the walk rather than being stepped over: our
    proxy appends a valid address, so the only way to meet junk is with
    nothing but trusted hops to its right, and falling back to the peer is
    the conservative answer.
    """
    peer_ip = normal_ip(peer)
    if not is_trusted(peer_ip, nets):
        return peer_ip or normal_ip(peer) or str(peer)
    for hop in reversed([h for h in (forwarded or "").split(",") if h.strip()]):
        hop_ip = normal_ip(hop)
        if not hop_ip:
            break                              # junk: stop, do not walk past it
        if is_trusted(hop_ip, nets):
            continue                           # one of ours, keep going left
        return hop_ip
    # Caddy does not set X-Real-IP by itself, so this only fires where the
    # deployment has been told to. Same rule: trusted peer or nothing.
    direct = normal_ip(real_ip)
    if direct:
        return direct
    return peer_ip


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
# A page name is a name, not a path: no slashes, no dots, nothing to
# climb out of the directory with.
PAGE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")

_MD_LINK   = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_MD_CODE   = re.compile(r"`([^`]+)`")
_MD_BOLD   = re.compile(r"\*\*([^*]+)\*\*")
# Italics, run after bold so a "**x**" is already gone by the time this
# looks. The lookarounds keep it off any asterisk that is part of a bold
# marker, and refusing a leading space keeps it off prose that happens to
# use an asterisk for something else. Same known limit as bold, and it has
# never bitten: an asterisk inside an inline `code` span is still seen.
# Fenced blocks are safe, because they never go through md_inline at all.
_MD_ITAL   = re.compile(r"(?<!\*)\*([^*\s][^*]*?)\*(?!\*)")
# "1. " at the start of a line. The router pages are 53 numbered steps that
# somebody follows one at a time with an admin page open in the other window,
# and without this they all fell through to the paragraph branch and were
# joined into a wall of text. Nothing caught it because every word was
# present and in the right order, which is what a grep checks.
_MD_STEP   = re.compile(r"^\d{1,2}\. ")


def md_inline(s):
    """Escape first, then the handful of inline forms we allow."""
    s = html.escape(s)
    s = _MD_CODE.sub(lambda m: f"<code>{m.group(1)}</code>", s)
    s = _MD_BOLD.sub(lambda m: f"<b>{m.group(1)}</b>", s)
    s = _MD_ITAL.sub(lambda m: f"<i>{m.group(1)}</i>", s)

    def link(m):
        text, href = m.group(1), m.group(2)
        # Only schemes a reader can follow safely, and nothing that could
        # turn a page file into a way to run script.
        if not href.startswith(("http://", "https://", "/", "#", "mailto:")):
            return text
        return f'<a href="{href}">{text}</a>'

    return _MD_LINK.sub(link, s)


# The markers are GitHub's rather than invented ones, so a page written
# somewhere else arrives with the right shape. The colours are this site's:
# [!TIP] is --dial, which the palette already spends on "things you can act
# on", and not GitHub's green, because green here means a board is up and
# means nothing else.
#
# [!TIP] is not a small note in a friendly colour. It is the full width
# invitation box with the "-->" marker at its right edge, and it is loud on
# purpose. A quiet remark that is not a warning is [!NOTE].
_MD_CALLOUTS = (("[!NOTE]", "aside"), ("[!TIP]", "tip"))


def md_callout(quote):
    """A run of "> " lines, as one box rather than one box per line.

    Amber by default, because thirteen of the fifteen blockquotes on this
    site are genuine warnings and the style exists to interrupt. The other
    two are reassurances, and an alarm-coloured box around "you never have
    to touch any of this" says the opposite of the words inside it. [!NOTE]
    is the calm version of the same box and [!TIP] is the inviting one,
    which is what a link to a page somebody would actually enjoy needs: an
    invitation in the warning colour is a warning.
    """
    lines = list(quote)
    kind = "warn"
    for marker, cls in _MD_CALLOUTS:
        if lines and lines[0].strip().startswith(marker):
            kind = cls
            lines[0] = lines[0].strip()[len(marker):].lstrip()
            if not lines[0]:
                lines.pop(0)
            break
    return f'<p class="{kind}">' + md_inline(" ".join(lines)) + "</p>"


CARD_BLOCKS = ("cards", "hero")
# Every ":::" block the dialect knows. "installer" is not a card: it is the
# one place on this site that renders a widget rather than prose, and it
# carries no content of its own, because what it should say depends on what
# is in FIRMWARE_DIR rather than on what somebody typed in the page.
BLOCK_NAMES = CARD_BLOCKS + ("installer",)


def md_block(kind, lines):
    """A ":::" block, by name. Cards, or the installer."""
    if kind == "installer":
        return installer_html()
    return md_cards(kind, lines)


def md_cards(kind, lines):
    """A ::: cards block: short boxes rather than continuous prose.

    Written for /kids, where the retro terminal look is a barrier rather
    than a joke: a ten year old has no idea what a BBS is, so the page
    cannot spend its first screen asking them to decode an aesthetic. Short
    units with a payoff each, dippable in any order.

    Each "## " inside the block starts a card, and the grid is auto-fit, so
    a wide screen gets several columns and a phone gets one **without any
    order: tricks**. Source order is reading order, which is what a screen
    reader follows and what somebody tabbing through gets.

    A "?? " line inside a card opens a <details> that runs to the end of
    that card. One per card and always last, which is the only shape a card
    wants anyway, and it means this needs no nested block parsing: the
    dialect has never had nesting and this does not introduce it.

    "hero" is the same thing with one full width card in the warm colours
    the invitation box on /whofor uses, so the page somebody lands on after
    clicking that box opens in the same voice they clicked.
    """
    chunks, cur = [], []
    for ln in lines:
        if ln.startswith("## "):
            if cur:
                chunks.append(cur)
            cur = [ln]
        else:
            cur.append(ln)
    if cur:
        chunks.append(cur)

    out = []
    for chunk in chunks:
        head = chunk[0][3:].strip() if chunk[0].startswith("## ") else ""
        body = chunk[1:] if head else chunk
        # "!! file.png | what it shows" is the card's picture. It is pulled
        # out wherever it is written and always drawn at the top, so the
        # cards stay uniform whatever order somebody types them in, and it
        # comes back empty until the file exists.
        pix, rest = "", []
        for ln in body:
            if ln.startswith("!! "):
                pix = pix or pix_html(ln[3:])
            else:
                rest.append(ln)
        body = rest
        more = None
        for i, ln in enumerate(body):
            if ln.startswith("?? "):
                more, body = (ln[3:].strip(), body[i + 1:]), body[:i]
                break
        inner = pix + (f"<h2>{md_inline(head)}</h2>" if head else "")
        inner += md_render("\n".join(body))
        if more:
            inner += ("<details><summary>" + md_inline(more[0]) + "</summary>"
                      + md_render("\n".join(more[1])) + "</details>")
        out.append('<section class="card">' + inner + "</section>")
    cls = "cards hero" if kind == "hero" else "cards"
    return f'<div class="{cls}">' + "".join(out) + "</div>"


def md_row(line):
    """One table row, as cells, or None. The separator row is not a row."""
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|")):
        return None
    cells = [c.strip() for c in s[1:-1].split("|")]
    if cells and all(set(c) <= set("-: ") and c for c in cells):
        return "SEP"
    return cells


def md_render(text):
    """The small subset of Markdown the pages use."""
    out, para, bullets, code = [], [], [], None
    quote = []            # consecutive "> " lines: one warning, not one per line
    steps = []            # "1. " lines: a numbered list, not a paragraph
    table = None
    card = None           # a "::: cards" block, collected whole
    for raw in text.splitlines():
        line = raw.rstrip()

        # Collected first and raw, so nothing else in the dialect claims a
        # line that belongs to a card. A ":::" at the start of a line closes
        # the block wherever it appears, including inside a fenced example,
        # which is the one thing this shape cannot express.
        if card is not None:
            if line.strip() == ":::":
                out.append(md_block(card[0], card[1]))
                card = None
            else:
                card[1].append(line)
            continue

        if code is not None:                       # inside a fenced block
            if line.startswith("```"):
                out.append("<pre>" + html.escape("\n".join(code)) + "</pre>")
                code = None
            else:
                code.append(raw)
            continue

        row = md_row(line)
        if row is not None:
            if table is None:
                table = []
            if row != "SEP":
                table.append(row)
            continue
        if table is not None:                      # the table just ended
            out.append(md_table(table))
            table = None

        def flush():
            if para:
                out.append("<p>" + md_inline(" ".join(para)) + "</p>")
                para.clear()
            if bullets:
                out.append("<ul>" + "".join(f"<li>{md_inline(b)}</li>"
                                            for b in bullets) + "</ul>")
                bullets.clear()
            if steps:
                out.append("<ol>" + "".join(f"<li>{md_inline(s)}</li>"
                                            for s in steps) + "</ol>")
                steps.clear()
            if quote:
                out.append(md_callout(quote))
                quote.clear()

        if line.startswith("::: ") and line[4:].strip() in BLOCK_NAMES:
            flush()
            card = (line[4:].strip(), [])
            # An unknown name after ":::" deliberately does not match, so it
            # falls through and renders as an ordinary paragraph. A typo is
            # then visible on the page instead of silently swallowing the
            # rest of it.
        elif line.startswith("```"):
            flush()
            code = []
        elif line.startswith("### "):
            flush()
            out.append(f"<h3>{md_inline(line[4:])}</h3>")
        elif line.startswith("## "):
            flush()
            out.append(f"<h2>{md_inline(line[3:])}</h2>")
        elif line.startswith("> "):
            if para or bullets:
                flush()
            quote.append(line[2:])            # consecutive lines are one warning
        elif line.startswith("# "):
            flush()
            out.append(f"<h1>{md_inline(line[2:])}</h1>")
        elif line.startswith("- "):
            if para or steps:
                flush()
            bullets.append(line[2:])
        elif _MD_STEP.match(line):
            if para or bullets:
                flush()
            steps.append(_MD_STEP.sub("", line, count=1))
        elif not line:
            flush()
        elif bullets and raw.startswith("  "):
            bullets[-1] += " " + line.strip()      # a wrapped bullet
        elif steps and raw.startswith("  "):
            steps[-1] += " " + line.strip()        # a wrapped step
        else:
            para.append(line.strip())

    if table is not None:                           # a table at the very end
        out.append(md_table(table))
    if card is not None:                            # unterminated ::: block
        out.append(md_block(card[0], card[1]))
    if code is not None:                            # unterminated fence
        out.append("<pre>" + html.escape("\n".join(code)) + "</pre>")
    if para:
        out.append("<p>" + md_inline(" ".join(para)) + "</p>")
    if bullets:
        out.append("<ul>" + "".join(f"<li>{md_inline(b)}</li>" for b in bullets) + "</ul>")
    if steps:
        out.append("<ol>" + "".join(f"<li>{md_inline(s)}</li>" for s in steps) + "</ol>")
    if quote:
        out.append(md_callout(quote))
    return "".join(out)


def md_table(rows):
    """First row is the header. Cells carry the same inline forms as text."""
    if not rows:
        return ""
    head = "".join("<th>" + md_inline(c) + "</th>" for c in rows[0])
    body = "".join("<tr>" + "".join("<td>" + md_inline(c) + "</td>" for c in r) + "</tr>"
                   for r in rows[1:])
    return '<div class="tablewrap"><table><tr>' + head + "</tr>" + body + "</table></div>"


def md_meta(text):
    """A page's own title and description, out of its Markdown.

    Every page file already carries its title in its first "# " line and
    used to throw it away: seven of twelve pages shared one browser tab
    title, so four router pages open in four tabs were four identical
    unreadable tabs. Page name first and site name second, because a tab
    strip truncates from the right.
    """
    title, desc = SITE_NAME, SITE_DESC
    head = re.search(r"^# (.+)$", text, re.M)
    if head:
        title = f"{head.group(1).strip()} - {SITE_NAME}"
        # The first ordinary line after the heading, which on every page
        # here is the sentence that says what the page is for.
        for line in text[head.end():].splitlines():
            line = line.strip()
            if line and not line.startswith(("#", ">", "-", "|", "`", "*")):
                desc = re.sub(r"[*`]|\[|\]\([^)]*\)", "", line)[:180]
                break
    return title, desc


def md_page(name, role="list"):
    """One of the pages/ files, as a whole page. None when there is no such file."""
    f = PAGES_DIR / (name + ".md")
    if not f.is_file():
        return None
    text = f.read_text(encoding="utf-8")
    title, desc = md_meta(text)
    body = "<article>" + md_render(text) + "</article>"
    # The one script on this site, and the only page that can carry it.
    #
    # Both halves of that condition matter. The page has to ask for the
    # installer, and there has to be something for the installer to install:
    # with FIRMWARE_DIR empty the block renders an explanation rather than
    # the element, and loading a module to drive an element that is not on
    # the page would be a script running on a reader's machine for no
    # reason at all. So the script and the widget arrive together or
    # neither does, which is a property no separate flag could hold.
    #
    # Everything else on this site stays exactly as it was: no other caller
    # of PAGE passes anything here, and the manifesto's claim to ship no
    # JavaScript is still true of the manifesto.
    head = ""
    if "::: installer" in text and firmware_releases():
        head = ('<script type="module" src="' + html.escape(EWT_SCRIPT, quote=True)
                + '"></script>')
    return PAGE.format(refresh="", head=head, title=html.escape(title),
                       desc=html.escape(desc, quote=True),
                       body=head_html(role, "/" + name) + body,
                       footer=foot_html(role))


STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"
STATIC_OK  = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
STATIC_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml"}


# Card art lives in its own folder rather than in static/, for two reasons.
# gallery_html() shows everything in static/ on the manifesto page, and
# blocky card art has no business in a gallery of photographs of real
# hardware; iterdir() skips a subdirectory on its own because it is not a
# file, so this needs no change there. And keeping it separate means the
# name check below is reused exactly as it is against a different base,
# rather than being loosened to understand a path, which is the change that
# would actually be worth getting wrong.
PIX_DIR = pathlib.Path(__file__).resolve().parent / "static" / "kids"


def static_file(name, base=None):
    """One file from static/, or None. Names are checked rather than paths:
    no directories, no dots to climb with, nothing but a plain filename."""
    if not STATIC_OK.match(name or ""):
        return None
    ext = pathlib.Path(name).suffix.lower()
    if ext not in STATIC_TYPES:
        return None
    f = (base or STATIC_DIR) / name
    if not f.is_file():
        return None
    return f.read_bytes(), STATIC_TYPES[ext]


def pix_html(spec):
    """A "!! file.png | what it shows" line inside a card.

    **Renders nothing at all when the file is not there.** The page has to
    read correctly with every image switched off, and it does that now,
    today, with none of them drawn: no broken-image box, no reserved gap,
    no alt text standing in for a picture that was never made. Drop a file
    in and the slot fills on the next render.

    The alt text is required and carries what the picture means rather than
    what it looks like, because somebody who cannot see it needs the point,
    not a description of the pixels.
    """
    name, _, alt = spec.partition("|")
    name, alt = name.strip(), alt.strip()
    if not alt or not STATIC_OK.match(name or ""):
        return ""
    if pathlib.Path(name).suffix.lower() not in STATIC_TYPES:
        return ""
    if not (PIX_DIR / name).is_file():
        return ""
    return (f'<img class="pix" src="/pix/{html.escape(name)}" '
            f'alt="{html.escape(alt, quote=True)}" loading="lazy">')


def gallery_html():
    """Whatever is in static/, captioned by static/captions.txt.

    One line per picture:

        file.jpg | what it is | who made it and under what licence

    The third field is optional and shown in small type under the caption.
    Somebody else's photograph carries a licence whether or not we mention
    it, and a site that argues about who owns what should be the last one
    to be sloppy about attribution. A picture with no caption still shows;
    a caption naming a file that is not there is ignored.
    """
    if not STATIC_DIR.is_dir():
        return ""
    captions, credits = {}, {}
    cap_file = STATIC_DIR / "captions.txt"
    if cap_file.is_file():
        for line in cap_file.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#") or "|" not in line:
                continue
            bits = [b.strip() for b in line.split("|")]
            captions[bits[0]] = bits[1] if len(bits) > 1 else ""
            if len(bits) > 2 and bits[2]:
                credits[bits[0]] = bits[2]

    shots = sorted(f.name for f in STATIC_DIR.iterdir()
                   if f.is_file() and f.suffix.lower() in STATIC_TYPES
                   and STATIC_OK.match(f.name))
    if not shots:
        return ""

    cells = []
    for name in shots:
        cap = html.escape(captions.get(name, ""))
        cred = md_inline(credits[name]) if name in credits else ""
        body = ""
        if cap:
            body += cap
        if cred:
            body += f'<span class="credit">{cred}</span>'
        cells.append(f'<figure><img src="/static/{html.escape(name)}" '
                     f'alt="{cap or html.escape(name)}" loading="lazy">'
                     + (f"<figcaption>{body}</figcaption>" if body else "")
                     + "</figure>")
    kind = "gallery one" if len(cells) == 1 else "wide gallery"
    return (f'<div class="{kind}">' + "".join(cells) + "</div>")


# --------------------------------------------------------------------------
# The browser installer.
#
# Everything below reads FIRMWARE_DIR and nothing else. There is no list of
# releases in this file and none in the database: what is on disk is what is
# offered, and what is not on disk cannot be.


def firmware_builds(vdir):
    """The chip families in one release directory that are complete.

    A family is offered only when every part in FLASH_PARTS is present. A
    missing or misspelled file drops that family out of the manifest
    entirely, which is the behaviour worth having: a manifest naming a file
    that is not there fails in the browser, halfway through, on somebody's
    board, and reads as a broken flasher rather than as a bad upload.
    """
    builds = []
    for chip in sorted(p.name for p in vdir.iterdir() if p.is_dir()):
        if not FIRMWARE_CHIP.match(chip) or chip not in FLASH_FAMILIES:
            continue
        family, boot = FLASH_FAMILIES[chip]
        parts = []
        for name, offset in FLASH_PARTS:
            f = vdir / chip / name
            if not f.is_file() or f.stat().st_size == 0:
                parts = None
                break
            # Relative to the manifest's own URL, which is what ESP Web
            # Tools resolves a part against. Keeping them relative means the
            # binaries are reached on whatever domain the manifest was
            # fetched from, so this needs no knowledge of the site's name
            # and no CORS headers anywhere.
            parts.append({"path": chip + "/" + name,
                          "offset": boot if offset is None else offset})
        if parts:
            builds.append({"chipFamily": family, "parts": parts})
    return builds


def firmware_releases():
    """Every complete release on disk, newest first, capped at FIRMWARE_KEEP.

    A release is complete when at least one chip family in it is complete.
    Anything else in the directory, README.md included, is not a version
    number and is skipped without comment.
    """
    if not FIRMWARE_DIR.is_dir():
        return []
    found = []
    try:
        entries = sorted(FIRMWARE_DIR.iterdir())
    except OSError:
        return []
    for vdir in entries:
        if not vdir.is_dir():
            continue
        m = FIRMWARE_VER.match(vdir.name)
        if not m:
            continue
        builds = firmware_builds(vdir)
        if not builds:
            continue
        date, note, improv = "", "", False
        meta = vdir / "release.txt"
        if meta.is_file():
            lines = meta.read_text(encoding="utf-8", errors="replace").splitlines()
            for i, raw in enumerate(lines):
                s = raw.strip()
                if not s:
                    continue
                # "improv: yes" says this image speaks Improv Wi-Fi Serial.
                # It is a property of the firmware in the directory, not of
                # the site, which is why it is recorded beside the binaries
                # and not in a constant here. Absent means no, which is the
                # safe way round: see firmware_manifest().
                if s.lower().startswith("improv:"):
                    improv = s.split(":", 1)[1].strip().lower() in ("yes", "true", "1")
                elif i == 0 and re.match(r"^\d{4}-\d{2}-\d{2}$", s):
                    date = s
                elif not note:
                    note = s[:160]
        found.append({"version": vdir.name,
                      "sort": tuple(int(g) for g in m.groups()),
                      "date": date, "note": note, "improv": improv,
                      "notices": (vdir / "THIRD_PARTY_NOTICES.md").is_file(),
                      "builds": builds})
    found.sort(key=lambda r: r["sort"], reverse=True)
    return found[:FIRMWARE_KEEP]


def firmware_manifest(version):
    """The ESP Web Tools manifest for one release, or None.

    The schema is theirs and the spellings are not negotiable: the top level
    is snake_case and the keys inside a build are camelCase, which is the
    easiest thing here to get wrong. An offset is a JSON number, decimal,
    because their type is `offset: number` and JSON has no hex literal; a
    string would be handed to the flasher unparsed.
    """
    for rel in firmware_releases():
        if rel["version"] != version:
            continue
        return {
            "name": "unleashed BBS",
            "version": rel["version"],
            # The user is asked rather than erased by default, and that is
            # what lets somebody reinstall over a board they already run
            # without losing their accounts: with this false, every install
            # is a whole-chip erase. The checkbox ESP Web Tools shows starts
            # unticked, so this flips the default from erase to keep, and
            # the page has to say which one a reader wants.
            "new_install_prompt_erase": True,
            # Seconds ESP Web Tools waits after an install for the board to
            # announce itself over Improv Wi-Fi Serial, which is how the
            # browser then offers to set the Wi-Fi up. Zero disables it.
            #
            # Zero unless the release says otherwise, because a board that
            # does not speak Improv makes every install sit on "wrapping up"
            # for ten seconds and then carry on, which reads as a hang. The
            # day the firmware implements it, the release says so and this
            # becomes the default ten.
            "new_install_improv_wait_time": 10 if rel["improv"] else 0,
            "builds": rel["builds"],
        }
    return None


def installer_html():
    """The ::: installer block: the button, or an honest account of why not.

    There is deliberately no third state. Either a complete release is on
    disk and the page offers it, or it is not and the page says so; nothing
    here can render a button that fetches a file that does not exist.
    """
    rels = firmware_releases()
    if not rels:
        return (
            '<div class="installer none">'
            "<h2>Not ready yet</h2>"
            "<p>There is no firmware image to install from this page today. "
            "The installer is finished; the images are not, because the "
            "board's Wi-Fi details are currently built into the firmware "
            "rather than set from the browser, and an image built that way "
            "would only ever join the network of whoever built it.</p>"
            "<p>That is the piece being worked on. When it is done the "
            "images appear here and this box becomes a button. Until then, "
            "a board takes about ten minutes to build yourself and the "
            '<a href="/build">build page</a> has every step.</p>'
            "</div>")

    newest = rels[0]
    out = ['<div class="installer">']
    out.append('<esp-web-install-button manifest="/firmware/'
               + html.escape(newest["version"], quote=True)
               + '/manifest.json">')
    # Our own button in the activate slot. The element exports three colour
    # variables and no ::part(), so anything beyond a colour means supplying
    # the element, and this page is monospace on black rather than a rounded
    # blue pill.
    out.append('<button class="go" slot="activate">Install '
               + html.escape(newest["version"]) + " on my board</button>")
    # Both fallbacks are given rather than left to the component's defaults,
    # which name Firefox first and say nothing about what to do next. The
    # precedence in their code is insecure-context first, so "not-allowed"
    # is the one a reader sees over plain http and never the other.
    out.append('<span class="no" slot="unsupported">This browser cannot talk '
               "to a serial port. Chrome or Edge on a desktop or laptop "
               "can; there is more about that below.</span>")
    out.append('<span class="no" slot="not-allowed">This page has to be '
               "served over https for a browser to allow it near a serial "
               "port.</span>")
    out.append("</esp-web-install-button>")

    meta = "Version " + html.escape(newest["version"])
    if newest["date"]:
        meta += ", " + html.escape(newest["date"])
    chips = ", ".join(b["chipFamily"] for b in newest["builds"])
    meta += ". " + html.escape(chips) + "."
    out.append('<p class="meta">' + meta + "</p>")
    if newest["note"]:
        out.append('<p class="meta">' + html.escape(newest["note"]) + "</p>")

    older = rels[1:]
    if older:
        bits = []
        for rel in older:
            bits.append('<a href="/firmware/' + html.escape(rel["version"], quote=True)
                        + '/manifest.json">' + html.escape(rel["version"]) + "</a>")
        out.append('<p class="meta">Also kept: ' + ", ".join(bits)
                   + ". Point the installer at one of these only if the "
                   "newest has a problem on your board.</p>")
    lic = []
    for rel in rels:
        if rel["notices"]:
            lic.append('<a href="/firmware/' + html.escape(rel["version"], quote=True)
                       + '/THIRD_PARTY_NOTICES.md">' + html.escape(rel["version"])
                       + "</a>")
    if lic:
        out.append('<p class="meta">What is in the image, and under what '
                   "terms: " + ", ".join(lic) + ".</p>")
    out.append("</div>")
    return "".join(out)


def firmware_file(rest):
    """One file under /firmware/, as (bytes, content type), or None.

    Names are checked rather than paths, the way static_file() does it, and
    the shapes accepted are the only three the page ever links:

        <version>/manifest.json
        <version>/THIRD_PARTY_NOTICES.md
        <version>/<chip>/<one of FLASH_PARTS>

    A binary is served only when its release is one firmware_releases()
    would offer, so a version left on disk past FIRMWARE_KEEP is not
    reachable by guessing its number either.
    """
    bits = [b for b in rest.split("/") if b]
    if not bits or not FIRMWARE_VER.match(bits[0]):
        return None
    offered = [r["version"] for r in firmware_releases()]
    if bits[0] not in offered:
        return None
    vdir = FIRMWARE_DIR / bits[0]

    if len(bits) == 2 and bits[1] == "manifest.json":
        man = firmware_manifest(bits[0])
        if man is None:
            return None
        return (json.dumps(man, indent=1).encode("utf-8"),
                "application/json; charset=utf-8")

    if len(bits) == 2 and bits[1] == "THIRD_PARTY_NOTICES.md":
        f = vdir / bits[1]
        if not f.is_file():
            return None
        return f.read_bytes(), "text/plain; charset=utf-8"

    if (len(bits) == 3 and FIRMWARE_CHIP.match(bits[1])
            and bits[1] in FLASH_FAMILIES
            and bits[2] in [name for name, _ in FLASH_PARTS]):
        f = vdir / bits[1] / bits[2]
        if not f.is_file():
            return None
        return f.read_bytes(), "application/octet-stream"

    return None


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
                f"ELSE public_at END WHERE id=?",
                args + [now, state, streak, state, now, row["id"]])
            sample(con, row["id"], fields.get("busy") or 0, tz, now)
            fresh = con.execute("SELECT * FROM boards WHERE id=?", (row["id"],)).fetchone()
            if fresh["state"] != row["state"]:
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
            f"streak_start, beats) VALUES(?, {marks}, ?, ?, ?, ?, 1)",
            [token] + list(fields.values()) + [state, now, now, now])
        fresh = con.execute("SELECT * FROM boards WHERE token=?", (token,)).fetchone()
        sample(con, fresh["id"], fields.get("busy") or 0, tz, now)
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
<meta name="description" content="{desc}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:type" content="website">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
{refresh}<link rel="alternate" type="application/rss+xml" title="New boards" href="/feed.xml">
<style>
/* Everything on this site is sized in rem off this one number, so the whole
   page scales the way a browser's own zoom scales it: type, padding,
   gutters, column width, the wordmark, the charts. 133% is Rob's figure and
   he arrived at it the honest way, by setting the browser to 133% and
   looking at the board list.

   Raising only the type would have been a different change and would have
   looked wrong without being easy to name: the words grow, the 1080px
   column does not, and a quarter of the characters per line disappear. Zoom
   moves the column too, which is why 133% reads as bigger rather than as
   cramped. So the column is 67.5rem and not 1080px, the gutter is 1rem and
   not 16px, and nothing that carries layout is left in px. What stays in px
   is borders and rules, because a hairline is a hairline at any size, and
   the text inside the SVG charts, which is in viewBox units and already
   scales with the chart.

   Percent rather than a pixel figure, so somebody who has set a larger
   default font in their browser keeps the benefit of it instead of having
   it overridden.

   A phone is the one place this is not simply better. 133% on a 390px
   screen is 31 characters to a line against 42 before, because a monitor
   has width to spend on larger type and a phone has none. 115% is the same
   change in kind, 14px to 16.1px, at 36 characters a line. One number each,
   and both easy to move. */
:root {{ color-scheme: dark; font-size:133%;
  --bg:#0b0b0f; --ink:#c8c8c8; --dim:#8a8a8a; --faint:#6a6a72; --rule:#1e1e26;
  --live:#5ddc7a;   /* up, and nothing else */
  --warm:#e0a94e;   /* the human: sysop, and a board still earning its place */
  --name:#b48ef0;   /* a board's own identity */
  --dial:#7fd4ff;   /* things you can act on */
  --busy:#ef8b5a;   /* activity */
  --struct:#4ce0e0; /* structure only: headings and column names */ }}
/* 900 is the site's one breakpoint. It used to have two, 620 and 900, which
   were two guesses at the same question: is there room here for a wide
   layout. With the type a third larger they answer it at the same width, so
   the float, the callout indents, the wrapping of long commands, the table
   label column and the board list all switch together now. One line to move
   if it is ever wrong, and no band where the page is half one layout and
   half the other. */
@media (max-width: 900px) {{ :root {{ font-size:115%; }} }}
body {{ background:var(--bg); color:var(--ink); font:0.875rem/1.5 ui-monospace,Menlo,Consolas,monospace;
       margin:0; padding:1rem; }}
main {{ max-width:67.5rem; margin:0 auto; }}
/* The wordmark is 62 columns of half-block art. Monospace cells are about
   0.6em wide, so the type scales with the viewport and never overflows a
   phone, instead of scrolling sideways or being cut off. */
pre.logo {{ background:none; border:0; padding:0; margin:0 0 0.375rem; overflow:visible;
       line-height:1; font-size:clamp(5px, calc((100vw - 2.75rem) / 38), 0.9375rem); }}
pre.logo i {{ font-style:normal; display:block; }}
pre.logo i:nth-child(1) {{ color:#e2d4ff; }}
pre.logo i:nth-child(2) {{ color:#b48ef0; }}
pre.logo i:nth-child(3) {{ color:#8f7ae8; }}
pre.logo i:nth-child(4) {{ color:#6f84e0; }}
pre.logo i:nth-child(5) {{ color:#4a7fc8; }}
pre.logo i:nth-child(6) {{ color:#3f6cab; }}
/* The menu, as a menu bar rather than a run of links.
   Reverse video is how a terminal shows a selection and how a Mac menu
   showed the item you picked, so hovering fills the cell and the current
   page stays filled. The current item also blinks three times when the page
   loads, the way a Mac menu item flashed when you let go of the mouse, then
   settles. Three times, not for ever: a permanently blinking thing on a page
   is an irritation rather than a signal. */
nav {{ margin:0.625rem 0 1.5rem; padding:0.625rem 0; display:flex; flex-wrap:wrap;
        gap:0.375rem 0.25rem; border-top:1px solid var(--rule);
        border-bottom:1px solid var(--rule); }}
/* 12px of text plus 22px of padding is a 34px tap target, 40 with the row
   gap. Nothing on this site used to be one: the menu was 26px and the dial
   link, which is the primary action of the whole directory, was 21px with
   no padding at all. */
nav a {{ color:var(--dim); text-decoration:none; font-size:0.75rem;
        letter-spacing:0.0625rem; text-transform:uppercase; padding:0.6875rem 0.75rem;
        white-space:nowrap; }}
nav a:hover, nav a:focus {{ background:var(--ink); color:var(--bg); }}
nav a.here {{ background:var(--name); color:var(--bg);
        animation:macblink 0.16s steps(1) 3; }}
@keyframes macblink {{
  0%, 100% {{ background:var(--name); color:var(--bg); }}
  50%      {{ background:transparent; color:var(--name); }}
}}
/* Somebody who has asked for less motion gets the selection without the
   flash. The reverse video carries the meaning on its own. */
@media (prefers-reduced-motion: reduce) {{
  nav a.here {{ animation:none; }}
}}
/* The page title outranks the text under it. It used not to: h1 was 13px
   against a 15px article h2, so a section heading four screens down
   outranked the page's own name, and on the board list the live figures
   were the smallest and faintest thing above the fold. 20px is the least
   that visibly beats the h2 without competing with the wordmark. */
h1 {{ color:var(--ink); font-size:1.25rem; font-weight:normal; letter-spacing:0.125rem;
     margin:0 0 0.375rem; text-transform:uppercase; }}
h1 span {{ color:var(--dim); font-size:0.8125rem; letter-spacing:0;
     text-transform:none; }}
h1 .count {{ color:var(--live); }}
p.lead {{ color:var(--dim); margin:0 0 1.25rem; }}
a {{ color:var(--dial); }}
table {{ border-collapse:collapse; }}
/* Full width is right for the board list, which is the product, and wrong
   for every table inside an article: the two column "Right now" table on the
   data page put the word "offline" 705px away from the digit that answers
   it. The board list gets the width; an article table takes what it needs. */
main > table {{ width:100%; }}
article table, article .tablewrap table {{ width:auto; min-width:0; }}
/* Room between a label and its value, but only where there is room to
   give: 3ch in place of 8px is about 17px a cell, which on a phone is what
   tips a table that fitted its wrapper into one that scrolls inside it. */
@media (min-width: 901px) {{
  article table th, article table td {{ padding-right:3ch; }}
}}
th {{ text-align:left; color:var(--struct); border-bottom:1px solid var(--rule); padding:0.375rem 0.5rem; font-weight:normal; }}
td {{ padding:0.375rem 0.5rem; border-bottom:1px solid #161616; vertical-align:top; }}
tr:hover td {{ background:#111; }}
.name {{ color:var(--name); }}
/* overflow-wrap, so a 44 character hostname breaks inside its own column
   instead of dictating the geometry of the whole table. */
.addr a {{ color:var(--dial); text-decoration:none; border-bottom:1px dotted #35566b;
        display:inline-block; padding:0.375rem 0; overflow-wrap:anywhere; }}
.addr a:hover {{ border-bottom-style:solid; }}
.desc {{ color:var(--dim); }}
/* What a board runs, said quietly next to its name. Every board is
   welcome here, and a directory that only ever shows one name does not
   look like it means that. */
.soft {{ color:var(--dim); font-size:0.75rem; margin-left:0.5rem;
        border:1px solid var(--rule); border-radius:0.1875rem; padding:0.0625rem 0.3125rem; }}
.act {{ color:var(--busy); }}
.owner {{ color:var(--warm); }}
.on {{ color:var(--live); }}
.idle {{ color:var(--dim); }}
.off {{ color:var(--faint); }}
.muted {{ color:var(--faint); }}
/* Nothing that is words goes below --dim. --faint is 3.7:1 against the page
   and fails AA; it is kept for rules, hairlines and the field labels on the
   phone layout, where it is doing structural work rather than carrying
   text. The 11px sizes went with it: 11px at 3.7:1 is not a size and a
   contrast anybody reads, it is one that says "ignore this", and how old a
   reading is happens to be the thing the footer insists matters. */
.fresh {{ color:var(--dim); font-size:0.75rem; }}
details.chart {{ margin-top:0.1875rem; }}
details.chart summary {{ list-style:none; cursor:pointer; }}
details.chart summary::-webkit-details-marker {{ display:none; }}
details.chart summary:focus-visible {{ outline:2px solid var(--dial);
        outline-offset:2px; }}
svg.spark {{ width:7.75rem; height:1.125rem; vertical-align:-0.1875rem; }}
svg.spark .b {{ fill:var(--busy); opacity:0.7; }}
svg.spark .b.peak {{ opacity:1; }}
svg.spark .base {{ stroke:#2c2c38; stroke-width:1; }}
.when {{ color:var(--dim); font-size:0.75rem; margin-left:0.5rem; }}
/* The sparkline is an SVG inside a summary with list-style:none, so there is
   no disclosure triangle and nothing that reads as clickable. It used to
   admit it was a control only once you had already found it. */
details.chart summary .when::after {{ content:" (click for the day)"; }}
details.chart[open] summary .when::after {{ content:" (click to close)"; }}
svg.hours {{ display:block; width:100%; max-width:45rem; height:auto;
        background:#0d0d12; border:1px solid var(--rule); margin:0.5rem 0 0.25rem; }}
svg.hours .bar {{ fill:var(--busy); opacity:0.75; }}
svg.hours .bar.peak {{ opacity:1; }}
svg.hours .grid {{ stroke:#20202a; stroke-width:1; }}
svg.hours .tick {{ stroke:#191922; stroke-width:1; }}
svg.hours .axis {{ stroke:#2c2c38; stroke-width:1; }}
/* Units, not pixels: this is inside a viewBox. It reads as roughly its own
   number in px because the viewBox is sized to the column, which is what
   the rewrite of day_chart_svg was for. */
svg.hours text {{ fill:var(--dim); font-family:inherit; font-size:13px; }}
svg.hours text.foot {{ font-size:11px; }}
details.chart .note {{ color:var(--dim); font-size:0.75rem; }}
.pending {{ color:var(--warm); }}
.none {{ color:var(--faint); padding:1.5rem 0.5rem; }}
footer {{ margin-top:1.75rem; color:var(--dim); border-top:1px solid var(--rule);
        padding-top:0.75rem; line-height:1.7; }}
article {{ max-width:none; }}
/* Full width, so a floated picture has text on both sides of it rather than
   a column that stops before it starts. Line height carries the longer
   measure.

   This was briefly capped at 78ch on typographic grounds and Rob reversed
   it after comparing the two: the wide setting is the house style, on every
   page, and it is not up for relitigating. The width the reading measure
   was meant to protect is instead spent where it was always spent, on the
   floated photograph on the manifesto and on the boxes below, which carry
   their own measures on purpose.

   Note this is the DESKTOP measure and has nothing to do with the phone.
   The board list still becomes a card layout under 900px, which is a
   different problem with a different fix. Wide on a monitor, cards on a
   phone; the two were never in conflict. */
article p, article li, article dd {{ max-width:none; line-height:1.62; }}
/* Anything drawn rather than written gets the whole width: diagrams and
   charts are not prose and should not be squeezed into its measure. */
article figure, article .wide {{ max-width:none; margin:1.25rem 0; }}
/* Photographs sit on a grid that reflows rather than a fixed row, so a
   phone gets one across and a monitor gets three. */
.gallery {{ display:grid; gap:0.875rem; margin:1.25rem 0;
        grid-template-columns:repeat(auto-fit, minmax(15rem, 1fr)); }}
/* One picture belongs in the text, not across it: float it and let the
   paragraphs wrap, the way any article would set a photograph. A source
   image straight off a phone is several thousand pixels wide, so it is
   capped here rather than trusted to be sensible. */
.gallery.one {{ display:block; float:right; width:min(34%, 23.75rem);
        margin:0.375rem 0 1.125rem 1.875rem; }}
.gallery figure {{ margin:0; }}
/* The box is reserved before the file arrives. Nothing declared a shape, so
   a lazily loaded photograph pushed the paragraphs beside it down when it
   landed. */
.gallery img {{ width:100%; height:auto; display:block; aspect-ratio:4 / 3;
        border:1px solid var(--rule); }}
.gallery.one img {{ max-height:26.25rem; object-fit:cover; }}
/* A float on a phone is just a very narrow column of text beside a picture,
   so below that width it goes back to being a block. */
@media (max-width: 900px) {{
  .gallery.one {{ float:none; width:100%; margin:1.125rem 0; }}
}}
.gallery figcaption {{ color:var(--dim); font-size:0.75rem; margin-top:0.375rem; }}
.tablewrap {{ overflow-x:auto; margin:1rem 0; }}
article table td {{ vertical-align:top; }}
article table td:first-child {{ color:var(--ink); white-space:nowrap; }}
/* A label column that will not wrap is right where there is width to spare
   and wrong on a phone, where it is what turns a table that fitted into one
   that has to be dragged sideways. Wrapping beats scrolling at 390. */
@media (max-width: 900px) {{
  article table td:first-child {{ white-space:normal; }}
}}
.gallery .credit {{ display:block; color:var(--dim); font-size:0.75rem; margin-top:0.1875rem; }}
article h2 {{ color:var(--struct); font-size:0.9375rem; margin:1.75rem 0 0.375rem; font-weight:normal; }}
/* Below the h2, not level with the h1. It used to be the same size, the
   same colour and the same uppercase treatment as the page title, so a
   section four screens down was indistinguishable from the page's name. */
article h3 {{ color:var(--dim); font-size:0.8125rem; margin:1.25rem 0 0.25rem; font-weight:normal;
        letter-spacing:0.0625rem; text-transform:uppercase; }}
/* A warning that is styled like everything else is a warning nobody
   reads. This one is meant to interrupt.

   It also has to be a box rather than a paragraph that shifted slightly.
   "margin:14px 0" is a shorthand, so it set margin-left to 0 explicitly and
   the left border landed flush with every paragraph on the page. 30px is
   the indent .freedom already uses, and the measure drops to 70ch so the
   box still ends before the body text does once it starts 30px later. The
   earlier attempt at this moved article .pull, which is a different
   element, and article .warn has never been touched since it was written. */
article .warn {{ color:#f0c674; background:#241d10; border-left:3px solid #8a6d39;
        padding:0.625rem 1rem; margin:1.125rem 0 1.125rem 1.875rem; max-width:78ch; }}
/* The calm half of the same idea. Same box, no alarm: a reassurance in the
   warning colour says the opposite of the words inside it. Neutral rather
   than another colour, because the palette already spends every colour it
   has on one meaning each and a note is not a new meaning. */
article .aside {{ color:var(--ink); background:#12121a;
        border-left:3px solid #2c2c38;
        padding:0.625rem 1rem; margin:1.125rem 0 1.125rem 1.875rem; max-width:78ch; }}
/* The inviting one, and the only callout here that is not a smaller,
   quieter version of the paragraph above it.

   The other two interrupt: they are narrower than the text, indented from
   it, and marked with one edge, because a warning wants to be an aside you
   cannot skip. This one invites, and an invitation that is smaller than
   everything around it is an invitation nobody takes. It was a 78ch note
   indented 30px, holding the one link on the site aimed at a twelve year
   old, and it read as a footnote.

   So: the full column rather than a measure, a frame on all four sides
   rather than one, a corner radius, and a marker at the right edge.

   Warm, not the site's cyan. --dial means "something you can act on"
   everywhere else here, but it is also the site's structural colour, and
   in it this box read as furniture. Yellow and orange read as "look
   here". Red is deliberately not in it: red is the grammar of an error
   box, and this one points a twelve year old at a page written for them,
   which is the same argument that kept the warning triangle out of it.
   It shares that range with .warn and is told apart by everything else:
   .warn is a narrow indented note marked on one edge, this is the full
   column in a bright frame with a marker in it.

   Measured against the box background rather than judged: lead 11.4:1,
   body 12.2:1, link and marker 8.7:1, frame 6.1:1. AA wants 4.5 for text
   and 3 for a boundary.

   The marker is "-->" and not a warning triangle. A triangle is the glyph
   for "something is wrong", and this box exists to say "this way in": the
   arrow is the board's own idiom for the room speaking to the caller, it
   is ASCII so it lands identically in every monospace font on every
   device, and it points the way the reader is being asked to go. It is
   ::after rather than markup so md_render needs no new shape for it.

   Reserved space, not overlap: padding-right holds the 2rem glyph's column
   open (1.25 of offset, 3.25 of glyph, 1.5 of gap), so text can never run
   under it however it wraps. On a phone that reserve would be a quarter of
   the column, so the marker moves to the bottom right corner and the
   reserve becomes padding-bottom instead, which puts it after the link
   rather than beside it. */
article .tip {{ color:#f2ddb8; background:#2e1c05;
        border:1px solid #d98f24; border-radius:0.625rem;
        padding:1rem 6rem 1.125rem 1.25rem; margin:1.375rem 0 1.625rem; max-width:none;
        position:relative; }}
/* The family stays monospace, because that is the site's identity and one
   element in a different face reads as a mistake rather than a choice. The
   lead sentence earns its rank on size, colour and its own line instead. */
article .tip b:first-child {{ display:block; color:#ffd35c;
        font-size:1rem; letter-spacing:0.03125rem; margin:0 0 0.3125rem; }}
article .tip a {{ color:#ffab52; text-decoration:underline;
        text-underline-offset:0.1875rem; }}
/* The whole box is the link, and the arrow is part of it.

   Drawing a pointer that does nothing is worse than drawing no pointer:
   it costs a reader a click to learn it is decoration, and on a phone it
   is the first thing they tap. Rob found it immediately.

   Not an <a> around the arrow, which would be a 36px target under the
   44px touch guidance asks for, and a third link in a box with one
   destination. Not an <a> around the box either, because the box already
   contains one and anchors do not nest. So: the one real link keeps its
   text, and an ::after on it stretches to the box's padding box. One
   anchor, one destination, one accessible name, the entire box live.

   The arrow is pointer-events:none so the hit falls through to that
   overlay. Without it the arrow is painted last, sits on top, and swallows
   the click on the one spot this whole change is about.

   The cost, stated rather than hidden: an overlay across the text makes
   the paragraph awkward to select by dragging. There is no way around
   that without script. It is three lines of invitation that exist to be
   clicked, not reference text somebody copies, so it is the right trade
   here and would not be on a page of commands. */
article .tip a::after {{ content:""; position:absolute; inset:0;
        border-radius:0.625rem; }}
article .tip::after {{ content:"-->"; position:absolute;
        right:1.25rem; top:50%; transform:translateY(-50%);
        color:#ffab52; font-size:2rem; line-height:1;
        letter-spacing:-0.1875rem; pointer-events:none; }}
/* A box that is clickable by mouse only is the same bug in a different
   costume, so the whole box lights on hover and the keyboard gets a ring
   around the box rather than around six words of it. The ring goes on the
   stretched overlay, which already is the box, so this needs no :has()
   and works wherever ::after does. */
article .tip:hover {{ background:#3a2408; border-color:#f0a52e; }}
article .tip:hover::after {{ color:#ffc77e; }}
article .tip a:focus-visible {{ outline:none; }}
article .tip a:focus-visible::after {{ outline:3px solid #ffd35c;
        outline-offset:-3px; }}
/* Same breakpoint as .gallery.one, and after the rule it overrides rather
   than before it: both selectors are (0,1,1), so source order decides and
   an earlier media query would simply have lost. 30px out of a 343px phone
   column is a real bite, and the border and the background carry a callout
   on their own at that width. */
@media (max-width: 900px) {{
  article .warn, article .aside {{ margin-left:0; }}
  article .tip {{ padding:0.875rem 1rem 2.75rem; }}
  article .tip::after {{ top:auto; bottom:0.5625rem; right:1rem;
        transform:none; font-size:1.625rem; letter-spacing:-0.0625rem; }}
  /* A 133 character command in a 358px column is 692px of dragging, which
     nobody does. It wraps on a phone instead. pre-wrap inserts nothing, so
     a copy still yields the exact original line, and the alternative is a
     command somebody cannot read at all. .chart is excluded because it is
     an ASCII diagram and wrapping would destroy it; it scrolls inside its
     own box, the way the markdown tables do. */
  article pre:not(.chart) {{ white-space:pre-wrap; overflow-wrap:anywhere; }}
}}
/* The ordered lists md_render now emits, spaced like the bullets beside
   them. */
article ol, article ul {{ margin:0 0 0.875rem; padding-left:1.75rem; }}
article ol li, article ul li {{ margin:0 0 0.375rem; }}
/* --------------------------------------------------------------------
   Cards, which exist for /kids and nowhere else so far.

   The problem they solve is not length, it is that the retro terminal
   look signals nothing to a ten year old. Everywhere else on this site it
   is doing real work, because the audience recognises it; on that one page
   it is an in-joke that asks a reader to decode an unfamiliar visual
   language before they have been given a reason to care. Short boxes with
   one idea and one payoff each, readable in any order.

   Blocky rather than soft: square corners and a 3px border instead of the
   rounded 1px the rest of the site uses. That reads as games rather than
   as documents, which is the frame this reader already owns, and it costs
   nothing and no image weight. It is the reason the borders here stay in
   px while everything else is in rem: a chunky border is chunky at any
   size, the same argument as a hairline.

   auto-fit with minmax gives three columns at 1920, two at 1366 and one on
   a phone with **no order: tricks**, so source order is reading order for
   a screen reader and for anybody tabbing. min() inside the minmax is not
   decoration: a bare minmax(21rem, 1fr) lays out a 21rem track in a 353px
   phone column and overflows the page sideways. It also means text zoomed
   to 200% simply drops to fewer columns, because the track is in rem.
   -------------------------------------------------------------------- */
article .cards {{ display:grid; gap:1rem; margin:1.5rem 0 1.75rem;
        grid-template-columns:repeat(auto-fit, minmax(min(21rem, 100%), 1fr)); }}
article .card {{ background:#12121a; border:3px solid #5c5c70;
        padding:1.125rem 1.25rem 1.25rem; }}
article .card h2 {{ margin:0 0 0.5rem; color:var(--struct); font-size:1rem;
        letter-spacing:0.03125rem; }}
article .card p, article .card ul, article .card ol {{ margin:0 0 0.75rem; }}
article .card ul, article .card ol {{ padding-left:1.375rem; }}
article .card > :last-child {{ margin-bottom:0; }}
/* Pixel art, kept pixelated: a browser smoothing blocky art is the one
   thing that would make it look like a mistake. Nothing here reserves a
   gap for a picture that does not exist, because pix_html renders nothing
   at all until the file is there; aspect-ratio only stops a picture that
   IS there from shoving the text down as it loads.

   One ratio for every slot, 4:1, including the hero. Two ratios would
   mean Rob drawing two shapes and object-fit cropping whichever one is in
   the wrong place, and a banner cropped from 4:1 to 2:1 loses the sides of
   the picture on exactly the screen with least room to spare. 4:1 is
   110px tall in a three column card, 162px in a two column one and 88px on
   a phone, which is a decorative strip on top of a card rather than a
   poster competing with the words under it. */
article .card img.pix {{ display:block; height:auto; aspect-ratio:4 / 1;
        object-fit:cover; image-rendering:pixelated;
        border-bottom:3px solid #5c5c70;
        margin:-1.125rem -1.25rem 0.875rem; width:calc(100% + 2.5rem); }}
/* The hero: one full width card in the warm colours the invitation box on
   /whofor uses, so the page somebody lands on opens in the voice they
   clicked. Square and chunky like the rest of them. */
article .cards.hero {{ grid-template-columns:1fr; }}
article .cards.hero .card {{ background:#2e1c05; border-color:#d98f24;
        color:#f2ddb8; }}
article .cards.hero .card h2 {{ color:#ffd35c; font-size:1.125rem; }}
article .cards.hero .card a {{ color:#ffab52; }}
article .cards.hero .card b {{ color:#ffd35c; }}
article .cards.hero .card img.pix {{ border-color:#d98f24; }}
/* Tap to open, with no script. "What is in this one" is most of the
   appeal at this age, and <details> is real interactivity for nothing.
   The marker is +/- rather than the browser triangle so it matches the
   ASCII the rest of the project is built from. */
article .card details {{ border-top:3px solid #5c5c70; margin-top:0.75rem;
        padding-top:0.5rem; }}
article .cards.hero .card details {{ border-top-color:#d98f24; }}
article .card summary {{ cursor:pointer; color:var(--dial); list-style:none;
        padding:0.375rem 0; }}
article .cards.hero .card summary {{ color:#ffab52; }}
article .card summary::-webkit-details-marker {{ display:none; }}
article .card summary::before {{ content:"[+] "; }}
article .card details[open] summary::before {{ content:"[-] "; }}
article .card summary:focus-visible {{ outline:2px solid var(--dial);
        outline-offset:2px; }}
article .cards.hero .card summary:focus-visible {{ outline-color:#ffd35c; }}
article .freedom {{ background:#1d1a10; border:1px solid #4a411f;
        border-radius:0.5rem; padding:0.875rem 1.25rem 0.25rem; margin:1.125rem 0 1.125rem 1.875rem;
        max-width:66ch; }}
article .freedom h4 {{ color:#e8c65c; font-size:0.8125rem; font-weight:normal;
        letter-spacing:0.0625rem; text-transform:uppercase; margin:0 0 0.375rem; }}
article .freedom p {{ color:#cfc7ae; margin:0 0 0.75rem; }}
article p {{ margin:0 0 0.875rem; }}
article b {{ color:#e8e8e8; font-weight:normal; }}
article .byline {{ color:var(--dim); border-bottom:1px solid var(--rule);
        padding-bottom:1rem; margin-bottom:1.375rem; }}
article .byline b {{ color:var(--warm); font-weight:normal; }}
article .pull {{ color:var(--name); border-left:2px solid #4a3d73;
        padding:0.25rem 0 0.25rem 1.25rem; margin:1.375rem 0 1.375rem 2.25rem; max-width:70ch;
        font-style:normal; }}
article .pull .sig {{ color:var(--faint); }}
pre {{ background:#111; border:1px solid var(--rule); padding:0.75rem; overflow-x:auto; color:#9fb; }}
code {{ color:var(--live); }}
dl {{ margin:0 0 0.875rem; }} dt {{ color:var(--warm); margin-top:0.625rem; }} dd {{ margin:0.125rem 0 0 1rem; }}
/* A link is one object. At 390 the footer broke inside a link, so "House
   rules" rendered as "House" on one line and "rules" on the next, which
   looks like a rendering fault whether or not it is one. The run wraps
   between links now, never inside one. */
footer a {{ display:inline-block; padding:0.375rem 0; white-space:nowrap; }}
/* --------------------------------------------------------------------
   The board list, which is the product, at two widths.

   Three columns, not six. Six of them each had to be given a width in
   characters and the sum did not fit once the type grew: Sysop spent a
   whole column on one short name and Up-for on one short figure, while
   Board and State, which are the two fields anybody reads, were squeezed
   between them. Stacking is what a field that is one short value wants.

   So the columns are what a reader actually asks, in order: which board,
   how do I reach it, what is it doing. Everything that describes the board
   stacks under its name, everything that describes its state stacks under
   its state, and the one field that must never be interfered with, the
   address, is alone in the middle.

   Two fixed columns and Board absorbing the rest. 28ch for Dial holds
   "bbs.unleashedbbs.com 6400" at 25 characters with room over; 20ch for
   State holds "67h 01m connected" at 17, which is the longest line that
   column can carry. Board is what is left: 75ch at 1920, 64ch at 1366 and
   23ch at the 901px edge, where it is tight and still above the 21 the old
   six column layout needed.

   The address is the one thing here that is copied rather than read, so it
   keeps overflow-wrap as a last resort rather than nowrap. An address
   longer than its column has to either break or overlap the column beside
   it, and of those two a break is the one that still shows every
   character.
   -------------------------------------------------------------------- */
@media (min-width: 901px) {{
  main > table {{ table-layout:fixed; }}
  main > table th:nth-child(1), main > table td:nth-child(1) {{ width:auto; }}
  main > table th:nth-child(2), main > table td:nth-child(2) {{ width:28ch; }}
  main > table th:nth-child(3), main > table td:nth-child(3) {{ width:20ch; }}
}}
/* The stacked lines. Each is its own line, and each says what it is: the
   heading a stacked field used to have is gone, so position alone would
   only read correctly to somebody who remembered the old table.

   The state keeps the body size and its own colour and the rest drops to
   0.75rem in --dim or --faint, so the cell has one loud line and two quiet
   ones rather than three lines of equal weight. That is what keeps the
   State column scannable straight down the page: it is the first line of
   every cell, cells are top aligned, and it is the only thing in its cell
   set at full size. */
/* Direct children only. ".status span" also matched the spans nested
   inside these ones, so the freshness figure dropped off the end of the
   state line onto its own row and every label was separated from the value
   it labels: "sysop" on one line and the name on the next. It renders as
   four broken lines rather than three good ones, and it is invisible in
   the markup, which is the whole reason the render gets measured. */
.status > span, .name > .owner {{ display:block; }}
.status > .act, .status > .muted, .status > .upfor,
.name > .owner {{ font-size:0.75rem; }}
.status > .upfor {{ color:var(--dim); }}
.lbl {{ color:var(--faint); }}
/* Below 900px the table stops being a table and becomes a list of boards,
   one field per line, with the state pinned top right where somebody
   scanning looks for it.

   This is the fix that matters most on the whole site: the six column
   version needed 627px of content width against the 358 a phone gives, so
   the page scrolled sideways and State, Activity and Up-for were off the
   screen entirely. The one question a directory exists to answer was the
   part you could not see.

   What is pinned is the state line rather than the whole cell it sits in,
   which is what the three column layout bought here. Stacking the fields
   deliberately at desktop width gave the phone its layout for free: the
   per column ordering, the per column type sizes and the generated labels
   are all gone, because the fields are already paired and already labelled
   at every width. */
@media (max-width: 900px) {{
  main > table, main > table > tbody {{ display:block; }}
  main > table tr {{ display:flex; flex-direction:column; position:relative;
        padding:0.875rem 0 1rem; border-bottom:1px solid var(--rule); }}
  main > table tr:first-child {{ display:none; }}          /* the header row */
  main > table td {{ display:block; border:0; padding:0.0625rem 0; width:auto; }}
  main > table td.name {{ order:1; padding-right:16ch; }}
  main > table td.status {{ order:2; }}
  main > table td.addr {{ order:3; margin-top:0.375rem; }}
  /* The 16ch keeps the name clear of the state pinned top right, and that
     is one line at the top of the card. The day chart is well below it, so
     it takes the width back rather than drawing itself 16 characters
     narrower than the card for no reason. */
  main > table td.name details.chart {{ margin-right:-16ch; }}
  main > table td.status .state {{ position:absolute; right:0; top:0.875rem;
        max-width:15ch; text-align:right; }}
  /* The one field a phone has no heading for and no label inside it. */
  main > table td.addr::before {{ content:attr(data-label) " ";
        color:var(--faint); }}
  .addr a {{ padding:0.5rem 0; }}
}}
/* --------------------------------------------------------------------
   The browser installer, and it is the only thing on this site that
   renders a third party's element.

   Two states, styled as two different things on purpose. With an image
   available it is a box you act on, in the colours the rest of the site
   uses for that; with none it is a box that explains itself, in the
   quieter aside colours, because a grey box nobody can press is honest
   and a greyed-out button is a puzzle.

   esp-web-install-button exports three colour variables and no ::part(),
   so a button that belongs on a monospace black page has to be supplied
   through its "activate" slot rather than themed. The variables are set
   anyway: they are what the element falls back to if the slot is ever
   empty, and a sky blue pill would be visible from orbit here.
   -------------------------------------------------------------------- */
article .installer {{ background:#12121a; border:1px solid #2c3a44;
        border-radius:0.5rem; padding:1.125rem 1.25rem; margin:1.5rem 0 1.75rem; }}
article .installer.none {{ border-color:#3a3a46; }}
article .installer h2 {{ margin:0 0 0.5rem; color:var(--struct);
        font-size:1rem; }}
article .installer p {{ margin:0 0 0.75rem; }}
article .installer > :last-child {{ margin-bottom:0; }}
article .installer .meta {{ color:var(--dim); font-size:0.8125rem;
        margin:0.625rem 0 0; }}
esp-web-install-button {{ --esp-tools-button-color:#102630;
        --esp-tools-button-text-color:var(--dial);
        --esp-tools-button-border-radius:0.375rem;
        display:block; margin:0 0 0.25rem; }}
article .installer button.go {{ font:inherit; font-size:0.9375rem;
        color:#04212c; background:var(--dial); border:1px solid #9fdfff;
        border-radius:0.375rem; padding:0.6875rem 1.25rem; cursor:pointer;
        text-align:left; }}
article .installer button.go:hover {{ background:#a7e2ff; }}
article .installer button.go:focus-visible {{ outline:3px solid #ffd35c;
        outline-offset:2px; }}
/* The two fallbacks the element shows instead of the button. Amber, the
   same as every other warning here, because that is exactly what they
   are: the reason nothing is going to happen on this browser. */
article .installer .no {{ display:block; color:#f0c674; background:#241d10;
        border-left:3px solid #8a6d39; padding:0.625rem 0.875rem;
        border-radius:0.25rem; }}
</style>{head}</head><body><main>
{body}
<footer>{footer}</footer>
</main></body></html>"""


# --------------------------------------------------------------------------
# The wordmark: a 6x12 pixel face drawn with half-block characters, which
# carry two pixels per cell vertically and so allow a real stroke weight
# instead of the chunky squares a plain block font gives.
#
# The capitals stand 10 pixels tall and sit on a baseline two rows from the
# bottom. The micro sign is a lowercase letter, so it is set to an x-height:
# its bowl starts lower, lands on that same baseline, and the left stem
# carries on below it. The last row is empty under every other letter, which
# is what a descender is meant to look like.
#
# Six rows, 62 columns, one <i> per row so the colour can sweep down it.
# --------------------------------------------------------------------------
LOGO_ROWS = (
    "       \u2588\u2588  \u2588\u2588 \u2588\u2588     \u2588\u2588\u2588\u2588\u2588\u2588 \u2584\u2588\u2580\u2580\u2588\u2584 \u2584\u2588\u2580\u2580\u2580\u2588 \u2588\u2588  \u2588\u2588 \u2588\u2588\u2588\u2588\u2588\u2588 \u2588\u2588\u2580\u2580\u2588\u2584",
    "\u2588\u2588  \u2588\u2588 \u2588\u2588\u2588 \u2588\u2588 \u2588\u2588     \u2588\u2588     \u2588\u2588  \u2588\u2588 \u2588\u2588     \u2588\u2588  \u2588\u2588 \u2588\u2588     \u2588\u2588  \u2588\u2588",
    "\u2588\u2588  \u2588\u2588 \u2588\u2588\u2588\u2584\u2588\u2588 \u2588\u2588     \u2588\u2588\u2588\u2588\u2588  \u2588\u2588\u2588\u2588\u2588\u2588  \u2580\u2588\u2588\u2588\u2584 \u2588\u2588\u2588\u2588\u2588\u2588 \u2588\u2588\u2588\u2588\u2588  \u2588\u2588  \u2588\u2588",
    "\u2588\u2588  \u2588\u2588 \u2588\u2588 \u2588\u2588\u2588 \u2588\u2588     \u2588\u2588     \u2588\u2588  \u2588\u2588 \u2584\u2584  \u2588\u2588 \u2588\u2588  \u2588\u2588 \u2588\u2588     \u2588\u2588  \u2588\u2588",
    "\u2588\u2588\u2584\u2584\u2588\u2588 \u2588\u2588 \u2580\u2588\u2588 \u2588\u2588\u2588\u2588\u2588\u2588 \u2588\u2588\u2588\u2588\u2588\u2588 \u2588\u2588  \u2588\u2588 \u2580\u2588\u2588\u2588\u2588  \u2588\u2588  \u2588\u2588 \u2588\u2588\u2588\u2588\u2588\u2588 \u2588\u2588\u2584\u2584\u2588\u2580",
    "\u2588\u2588",
)


def logo_html():
    """The wordmark, one <i> per row. No newlines inside the <pre>, because
    each row is a block element, so nothing depends on source whitespace."""
    return ('<pre class="logo" role="img" aria-label="\u00b5nleashed">'
            + "".join(f"<i>{row}</i>" for row in LOGO_ROWS)
            + "</pre>")


# The micro sign out of the wordmark, at 12x12, which is the one glyph that
# carries the whole identity at favicon size. Traced off LOGO_ROWS rather
# than set in a font: at 16px a font falls back to whatever the renderer has
# and the stroke weight is a lottery. Three rectangles, and the left stem
# carries on below the baseline because that descender is the point of using
# a lowercase letter.
#
# Served from its own route rather than from static/, because gallery_html()
# shows every image file in static/ and a favicon does not belong in the
# manifesto's photo gallery.
FAVICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 12 12" '
           'shape-rendering="crispEdges">'
           '<rect width="12" height="12" fill="#0b0b0f"/>'
           '<rect x="3" y="2" width="2" height="10" fill="#b48ef0"/>'
           '<rect x="7" y="2" width="2" height="8" fill="#b48ef0"/>'
           '<rect x="5" y="9" width="2" height="1" fill="#b48ef0"/>'
           "</svg>")


def human_ago(seconds):
    if seconds < 90:
        return "just now"
    if seconds < 5400:
        return f"{seconds // 60} min ago"
    if seconds < 172800:
        return f"{seconds // 3600} h ago"
    return f"{seconds // 86400} d ago"


def human_short(seconds):
    """An age in as few characters as possible: for freshness, not prose."""
    if seconds < 90:
        return "now"
    if seconds < 5400:
        return f"{seconds // 60}m"
    if seconds < 172800:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def human_streak(seconds):
    if seconds < 5400:
        return f"{max(1, seconds // 60)}m"
    if seconds < 172800:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


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


def board_rows(rows, now, charts=None):
    out = []
    for r in rows:
        where = r["host"] or r["address"]
        state = r["state"]
        seen = now - r["last_seen"]
        if state == "online":
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
        out.append(
            "<tr>"
            f"<td class='name' data-label='Board'>{html.escape(r['name'])}"
            + (f"<span class='soft'>{html.escape(r['software'])}</span>"
               if r["software"] else "")
            + "<br>"
            + f"<span class='desc'>{html.escape(r['description'])}</span>"
            + who_runs
            + ((charts or {}).get(r["id"]) or "")
            + "</td>"
            f"<td class='addr' data-label='Dial'><a href='{dial}' "
            f"title='Opens your terminal program, if one is registered for "
            f"telnet:// links.'>"
            f"{html.escape(where)} {r['port']}</a></td>"
            f"<td class='status' data-label='State'>"
            f"<span class='state {klass}'>{html.escape(label)} {fresh}</span>"
            + act_line
            + "<span class='upfor'><span class='lbl'>up for</span> "
            + human_streak(now - r["streak_start"]) + "</span>"
            + "</td>"
            + "</tr>")
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
    live = [r for r in rows if r["state"] == "online"]
    on = sum(r["busy"] or 0 for r in live)
    # --live, the colour that means "up" everywhere else on the page. This
    # figure is the product and it used to be set in the smallest, faintest
    # type above the fold.
    who = (f" &middot; <span class='count'>{on} caller"
           f"{'' if on == 1 else 's'} on</span>"
           if on else " &middot; nobody on right now")
    with db() as con:
        charts = {}
        for r in rows:
            hours = hours_for(con, r["id"])
            if hours:
                charts[r["id"]] = chart_html(hours)

    head = (head_html("list", "/")
            + f"<h1>BBS directory <span>&middot; {len(rows)} listed{who}</span></h1>"
            + '<p class="lead">Boards that are up right now. '
            'Dial one with <a href="/terminals">any telnet client</a>, or click '
            'an address if you have one installed. '
            '<a href="/dialing">Nothing happened?</a> '
            '<a href="/firstcall">Never called one before?</a></p>')
    if rows:
        body = ("<table><tr><th>Board</th><th>Dial</th><th>State</th></tr>"
                + board_rows(rows, now, charts) + "</table>")
    else:
        body = "<p class='none'>No boards listed yet. Yours could be the first.</p>"
    body = head + body
    # Five clauses and sixty words with no break, and it is the only place
    # that says what the 24 hour figures and "up for" mean. Three lines, one
    # idea each.
    footer = foot_html("list",
        "The 24 hour figures under a board's state are how many calls it "
        "took and how long callers were connected in total.<br>"
        "Caller counts and activity are reported by the boards themselves. "
        "The small figure next to the state is how old that reading is.<br>"
        '"Up for" is measured here and cannot be fudged.')
    desc = (f"{len(rows)} bulletin board{'' if len(rows) == 1 else 's'} listed, "
            f"{len(live)} up right now, {on} caller{'' if on == 1 else 's'} on. "
            "Dial one with any telnet client.")
    return PAGE.format(title=html.escape(SITE_NAME), desc=html.escape(desc, quote=True),
                       body=body, footer=footer, refresh=LIST_REFRESH, head="")


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
<p class="lead">Your board announces itself. You do not fill in a form.</p>
<article>
<pre>[plugin:announce]
enabled     = yes
name        = The Rusty Modem
owner       = Sparks
description = A BBS on a chip in a shack in Illinois
servers     = http://unleashedbbs.net/announce</pre>
<p>Any of this directory's names will take a heartbeat, but <code>.net</code> is the
one meant for machines: <code>.com</code> is the list people read and
<code>.org</code> is what the project is for.</p>
<p>Switch it on and wait. A listing becomes public after three hours of
uninterrupted heartbeats, which is what keeps drive-by spam off the page, and
it disappears when the heartbeats stop. <code>ANNOUNCE</code> on your board
shows how long is left.</p>
<h2>Running something else</h2>

<p>Synchronet, Mystic, WWIV, ENiGMA, Citadel, something you wrote yourself in a
weekend: all welcome, all listed the same way, and what you run is shown next to
your board's name. This is a directory of boards that are up, not a directory of
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

<p><b>The same rules apply to everyone.</b> Three hours of uninterrupted
heartbeats before a listing goes public, and it disappears when the heartbeats
stop. There is no exception for boards running this firmware, and that is the
whole anti-spam design: staying listed costs a machine that keeps running, which
is exactly what a spammer will not do and exactly what a real board does anyway.</p>

<p>The full protocol, including every field and what the directory does with it,
is in <a href="https://github.com/rwmech/unleashed_directory">the server
repository</a>. It is one Python file and you are welcome to run your own.</p>
</article>"""


ANIM = """
<style>
/* The diagram is 61 characters of fixed-width art, so 470px at the body's
   14px. A phone column is 358, and .scene pre is position:absolute with no
   width, so it shrink-wrapped to its content and pushed the whole about
   page sideways by 96px, header and footer included.

   It scales instead of scrolling. Same trick the wordmark already uses:
   the type shrinks with the viewport so 61 characters always fit, which is
   the right answer for art with a fixed character count. An earlier attempt
   put overflow-x:auto here, and that did stop the page moving but produced
   a scrollbar on the diagram, because the five printed lines at 1.5 line
   height are 105px against a 7.4em box, and when one axis is not visible
   CSS computes the other to auto as well. So it was a VERTICAL scrollbar on
   a fix aimed at horizontal overflow.

   overflow:hidden is the backstop rather than the mechanism: with the
   clamp, nothing should reach it, and if an unusual monospace font renders
   a few percent wider then a decorative diagram loses a character off the
   end, which beats a scrollbar and beats a page that slides sideways.

   The divisor: 61 characters at 0.55em each is 33.6em, so (100vw - 44px)
   over 37 leaves a margin and reaches the 14px cap at about 560px wide. */
.scene { position:relative; margin:1.125rem 0 1.375rem; overflow:hidden;
         font-size:clamp(6px, calc((100vw - 2.75rem) / 37), 0.875rem);
         height:7.9em; }
.scene pre { position:absolute; left:0; top:0; margin:0; opacity:0;
             font-family:inherit; font-size:inherit; line-height:1.5;
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
         padding:0.875rem; overflow-x:auto; line-height:1.35; }
.chart b { color:#e06c6c; font-weight:normal; }
.chart i { color:#6ee36e; font-style:normal; }
</style>
<div class="scene">
<pre>   [ YOU ]                                   [ THE BOARD ]
     |                                              |
     |  o--------------------------------------     |
     |                                              |
   any terminal, anywhere                   a chip on a shelf</pre>
<pre>   [ YOU ]                                   [ THE BOARD ]
     |                                              |
     |  ---o-----------------------------------     |
     |                                              |
   any terminal, anywhere                   a chip on a shelf</pre>
<pre>   [ YOU ]                                   [ THE BOARD ]
     |                                              |
     |  -------o-------------------------------     |
     |                                              |
   any terminal, anywhere                   a chip on a shelf</pre>
<pre>   [ YOU ]                                   [ THE BOARD ]
     |                                              |
     |  -----------o---------------------------     |
     |                                              |
   any terminal, anywhere                   a chip on a shelf</pre>
<pre>   [ YOU ]                                   [ THE BOARD ]
     |                                              |
     |     ---------------------------o--------     |
     |                                              |
   any terminal, anywhere                   a chip on a shelf</pre>
<pre>   [ YOU ]                                   [ THE BOARD ]
     |                                              |
     |     -----------------------o------------     |
     |                                              |
   any terminal, anywhere                   a chip on a shelf</pre>
<pre>   [ YOU ]                                   [ THE BOARD ]
     |                                              |
     |     -----------------o------------------     |
     |                                              |
   any terminal, anywhere                   a chip on a shelf</pre>
<pre>   [ YOU ]                                   [ THE BOARD ]
     |                                              |
     |     -----------o------------------------     |
     |                                              |
   any terminal, anywhere                   a chip on a shelf</pre>
</div>"""


# The h1 is not decoration. This is the page the whole argument lives on and
# it used to start at h2, so it had no document outline, no heading for a
# screen reader to land on, and nothing on screen saying what it was called.
ABOUT = """<h1>What this is</h1>
<p class="lead">Electronic freedom on a microcontroller. No web, no cloud, no browser.</p>

<p class="byline">Written and built by <b>QuantumRob</b>, who has been doing this
since the 4381 was the computer in the room. The argument below is his; the
software is free for anybody who agrees with it, and for anybody who does
not.</p>
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

<p class="pull">I met Ward Christensen once, at a Maker Faire. I did not know it
would be the only time. He died on
<a href="https://www.theregister.com/offbeat/2024/10/15/rip-ward-christensen-co-developer-of-the-cbss/492871">11
October 2024</a>, and I wish I had spent longer talking to him while I had the
chance. If you get to meet the person who built the thing you love, take the extra
hour.<br><br><span class="sig">&mdash; QuantumRob</span></p>

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

<h2>The whole computer</h2>

<p>This is an <a href="https://en.wikipedia.org/wiki/ESP32">ESP32-WROOM-32E</a>. It
is a microcontroller about the size of a postage stamp with a radio on it: a
240 MHz dual-core processor, <b>520 kilobytes</b> of RAM, four megabytes of flash,
and Wi-Fi. It costs a few dollars, draws a few tens of milliamps, and runs from a
phone charger.</p>

<p>CBBS answered one caller at a time on 64 kilobytes. This has eight times that
memory and answers ten at once, with a hidden eleventh line the sysop comes in
on. There is no operating system underneath it worth the name, no web stack, no
database, no container: the whole board is one program that fits in about a
megabyte and never allocates memory while a caller is typing.</p>

<p>That is the argument in one object. A community does not need a data centre.
It needs a machine somebody owns, on a connection somebody pays for, run by a
person who can be reached. This one fits in a pocket and you can build it in an
afternoon.</p>

<p>Schools, clubs, ham radio, offices, and one person with eleven friends:
<a href="/whofor">who it's for, and why you might want one</a>.</p>

@GALLERY@

<p><a href="/build">Build one</a> if you want to. Everything needed is a dev
board and a USB cable.</p>

<h2>What replaced it</h2>

<p>The web arrived and it was better at almost everything, and then it consolidated.
Now the conversation lives on machines you cannot see, indexed, scraped to train
something, ranked, monetised, and deleted at somebody else's discretion. You do not
own the room, the member list, the history, or the right to keep any of it. You rent
all of it, and the rent is paid in attention and data.</p>

<p class="pull">The thing that was lost was not the modem noise. It was that the
system belonged to somebody you could name.</p>

<h2>What this is</h2>

<p>A telnet BBS that runs on a bare ESP32 and grows into an IoT terminal server
through plugins. Nodes, handles, a user list, a chat room in the style of DDial and
Gtalk, mail between callers, file areas on an SD card, a caller log, a sysop who can
page you. Forums are being built now: topic areas a sysop sets up, with
conversations inside each one, read at the same prompt as everything
else; doors come after them.</p>

<p><b>The board is yours.</b> Not an account on somebody's platform, not a tenant on a
server farm, not a feature that can be deprecated out from under you. A chip you own,
on a port you chose, running software you can read all of in an afternoon and change
when you disagree with it. Leave it in a drawer for a year, plug it back in, and it
still works, because there is nothing at the other end that has to still exist.</p>

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

<h2>Freedoms gained</h2>

<p>Every one of these is something you cannot have on a platform, at any price,
because the platform's business depends on you not having it.</p>

<div class="freedom">
<h4>Nobody is watching, and everything is public anyway</h4>
<p>There is no analytics, no telemetry, no model being trained, and nobody
between you and the person you are talking to. It works like radio rather than
like a service: what is said in the room is heard by whoever is in the room,
and nothing is recorded anywhere you cannot reach. Hold a meeting about
something sensitive and the only people who know it happened are the people who
were there.</p>
</div>

<div class="freedom">
<h4>You define the terms, and the theme, and the rules</h4>
<p>No terms of service written by somebody else's lawyers. No content policy
that changes next quarter. No appeals process you did not design. You decide
what the board is called, what it is for, who is welcome, what is allowed and
what is not. If somebody disagrees strongly enough, the correct answer has
always been that they can run their own, and here they actually can.</p>
</div>

<div class="freedom">
<h4>Nobody can deplatform you</h4>
<p>There is no account to suspend, no host to complain to, no payment processor
to lean on, no app store to delist you from. The board is a chip you own on a
connection you pay for. The only person who can switch it off is you, and the
only thing that can take it down is the electricity bill.</p>
</div>

<div class="freedom">
<h4>What you say stops existing when you say it should</h4>
<p>A message goes from one caller to another through a chip on your shelf and is
gone once it has been read. Delete the user list and it is deleted. Wipe the
flash and there is no backup in a data centre, no retention policy, no
"deactivated but retained for legitimate business purposes". Forgetting is the
default, which is how conversation worked for the whole of human history until
about twenty years ago.</p>
</div>

<div class="freedom">
<h4>You can read every line of it, and change any of them</h4>
<p>It is free software under the GPL. Not source-available, not "open" with a
licence that revokes itself if you compete: actually free. Read it, change it,
run the changed version, give it to somebody else. If this project goes in a
direction you hate, take the last version you liked and carry on without
asking.</p>
</div>

<div class="freedom">
<h4>No account, no email address, no phone number</h4>
<p>A caller types a handle and picks a password, and that is the whole of
signing up. A guest types a handle and nothing else, gets fifteen minutes, and
leaves nothing behind. Nothing is verified because there is nothing to verify
against, and no identity is being assembled anywhere. Being unknown to a system
is the normal condition of being a person, and it should not require effort.</p>
</div>

<div class="freedom">
<h4>It keeps working when nothing else does</h4>
<p>No certificate to renew, no API to be deprecated, no subscription to lapse,
no company to be acquired and shut down. Leave the board in a drawer for a
year, plug it in, and it answers, because there is nothing at the other end
that has to still exist. Software that outlives the company that made it used
to be ordinary.</p>
</div>

<div class="freedom">
<h4>You can be found, or not, entirely as you choose</h4>
<p>List the board in a directory and strangers can call it. Leave it off and it
exists only for people you tell. Take it off the internet and it serves your own
house. Nobody makes that decision but you, and no algorithm decides how visible
you are once you have made it.</p>
</div>

<h2>The power is in your hands, literally</h2>

<p>You flash the firmware. You set the password. You decide who gets a handle, what the
board is called, what the rules are, and whether it is on the internet at all. You can
read every line of the software before you trust it, and change the parts you disagree
with, and nobody can stop you, because the licence says so and the source is right
there.</p>

<p class="pull">If you switch it off, it is off. Nobody else gets a say in that.</p>

<p>Not "your account is deactivated but we retain your data for legitimate business
purposes". Pull the plug and the chip stops answering. Wipe the flash and the user
list is gone.</p>

<h2>Honest about the limits</h2>

<p><b>Open communication over the internet is radio.</b> You transmit, whoever
is on the channel hears you, and that is the whole of it. A walkie-talkie, not
a sealed envelope. Telnet has no encryption, because a Commodore 64 cannot do
TLS and pretending otherwise would be worse than saying so.</p>

<p><b>Somebody has to be trying.</b> Being able to listen is not the same as
listening. It takes a packet sniffer or the equivalent, placed somewhere on the
path between a caller and the board. The board decides who hears what; the wire
carries it in the clear. If the radio is not switched on and tuned in, nobody
heard you.</p>

<p><b>The real risk is low and it is not zero, and the comparison is the
point.</b> These are public conversations. What would you say in a bar, or in a
coffee house, knowing the next table can hear? Now weigh that against a website
that records and ranks everything you do by design. A board is the bar. Yes,
somebody could be parked outside with equipment, and for almost everybody that
is an edge case. Saying so is more honest than implying it is either safe or
dangerous.</p>

<p><b>So: say what you would say in public, and use a password you use nowhere
else.</b> If a conversation has to survive somebody watching the link, put the
board behind a VPN or leave it on the local network. Privacy you can explain in
one sentence beats privacy you have to take on faith.</p>

<p><a href="/privacy">Read about the real risks of open communications</a></p>

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

<p class="pull">In 1989 I was working on
<a href="https://en.wikipedia.org/wiki/IBM_4300">IBM 4381 mainframes</a>. I have
stood inside the raised-floor room, and the point is that it was somebody else's
room. You booked time on that machine. You did not own it, you could not take it
home, and what you were allowed to do with it was decided by people who were not
you.<br><br><span class="sig">&mdash; QuantumRob</span></p>

<h2>You can do this today</h2>

<p>Not as a re-enactment: as a live system with callers on it tonight. Flash a board,
give it your wifi, forward one port on your router, and you are running a public BBS.
No hosting bill, no domain required, no provider to ask permission from, no account
with anybody. A chip on a shelf and one line in your router.</p>

<p><a href="/whofor">Who it's for</a> is the short version of why you might:
a classroom, a club, an office, a shelf in your own house, and the fact that
on your own board you answer to nobody.</p>

<p><a href="https://github.com/rwmech/unleashed_BBS">The source, the documentation and
the build instructions are here.</a> It is free software under the GNU General Public
License, version 2 or later.</p>

<h2>How it was built</h2>

<p>I built this with <a href="https://www.anthropic.com/claude">Claude</a>, and I
want that said plainly rather than left for somebody to work out. I have spent
thirty years writing software and I could have written this alone. What I did not
have was the time. A BBS, a directory server, a protocol and the documentation for
all three do not come out of the evenings left over after a working week.</p>

<p>The decisions are mine: what it should be, what it should refuse to do, what
goes in and what stays out. A great deal of the typing is not, and quite a lot of
the arguing was two-sided. Credit where it is due.</p>

</article>"""


ABOUT_DESC = ("A bulletin board is a machine that answers a phone number. "
              "Why that still matters, and what it takes to run one: a "
              "telnet BBS on a five dollar microcontroller.")
DATA_DESC  = ("The directory, machine readable. No key, no signup, no rate "
              "limit worth mentioning. It is a list of hobby BBSes.")


def about_page(role, here):
    """The manifesto. The gallery is whatever is in static/ right now, so it
    goes in at request time rather than being baked into the constant."""
    return simple_page(f"What this is - {SITE_NAME}",
                       ABOUT.replace("@GALLERY@", gallery_html()),
                       role, here, ABOUT_DESC)


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
                self.reply(200, about_page("about", "/"))
            elif role == "data":
                self.reply(200, cached("data", PAGE_CACHE,
                                       lambda: simple_page(f"Data - {SITE_NAME}",
                                                           data_page(), "data",
                                                           "/", DATA_DESC)))
            else:
                self.reply(200, cached("index", PAGE_CACHE, index_page))
        # The other two faces, under their own paths, so a deployment with
        # one domain has all three. There were no path routes at all: with
        # only DIRECTORY_LIST_DOMAIN set, /about and /data returned 404, two
        # of the seven menu items were loops back to the page you were
        # already on, and the manifesto, which is the whole argument for the
        # project, could not be read. README.md and INSTALL.md both said
        # otherwise. PAGE_NAME is ^[a-z0-9][a-z0-9-]{0,39}$ and the generic
        # page branch runs last, so neither name can be shadowed by a file
        # in pages/, and neither can shadow /health.
        elif path == "/about":
            self.reply(200, about_page(role, "/about"))
        elif path == "/data":
            # Keyed on the role: the same path is reachable on any of the
            # three domains and the nav and the footer differ on each.
            self.reply(200, cached("datapage:" + role, PAGE_CACHE,
                                   lambda: simple_page(f"Data - {SITE_NAME}",
                                                       data_page(), role,
                                                       "/data", DATA_DESC)))
        elif path == "/favicon.svg":
            self.reply(200, FAVICON, "image/svg+xml",
                       {"Cache-Control": "public, max-age=86400"})
        elif path.startswith("/static/") or path.startswith("/pix/"):
            # /pix/ is the card art on /kids. Same name check, same types,
            # a different folder: see PIX_DIR for why it is not in static/.
            if path.startswith("/pix/"):
                got = static_file(path[len("/pix/"):], PIX_DIR)
            else:
                got = static_file(path[len("/static/"):])
            if got is None:
                self.reply(404, "no such file\n", "text/plain; charset=utf-8")
            else:
                blob, ctype = got
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(blob)))
                self.send_header("Cache-Control", "public, max-age=3600")
                self.end_headers()
                self.wfile.write(blob)
        # The firmware images and the manifests that describe them, for the
        # installer on /install. Ahead of the generic page branch for the
        # same reason every other real endpoint is: a pages/ file must not
        # be able to shadow it. Nothing is cached here; a manifest is a few
        # hundred bytes built from a directory listing, and a binary is
        # fetched once per install rather than once per reader.
        elif path.startswith("/firmware/"):
            got = firmware_file(path[len("/firmware/"):])
            if got is None:
                self.reply(404, "no such firmware file\n",
                           "text/plain; charset=utf-8")
            else:
                blob, ctype = got
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(blob)))
                # An image is immutable: a version's bytes never change,
                # because a change is a new version. The manifest names the
                # version it belongs to and is just as fixed.
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(blob)
        elif path == "/build":
            page = md_page("build", role)
            if page is None:
                self.reply(404, "no such page\n", "text/plain; charset=utf-8")
            else:
                self.reply(200, page)
        # role and here, both of which these two were missing. Without here,
        # nav_html fell into its index fallback and filled BOARDS as the
        # current page, so a reader on "Get listed" was told they were on
        # "Boards", with the menu blinking three times to draw the eye to
        # it. Without role, a reader who arrived on the about domain got the
        # list face's footer.
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
        # Last, deliberately. Every branch above is a real endpoint, and a
        # generic page lookup placed before them silently swallows whichever
        # ones happen to look like a page name. It took /health the first
        # time, which is precisely the endpoint update.sh uses to decide
        # whether a deployment worked.
        elif PAGE_NAME.match(path[1:] or ""):
            page = md_page(path[1:], role)
            if page is None:
                self.reply(404, "no such page\n", "text/plain; charset=utf-8")
            else:
                self.reply(200, page)
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
