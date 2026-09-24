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
import threading
import time
import unicodedata
import urllib.parse
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
# to read a list. The list does carry a few inline lines now, the badge
# filter's (see BADGE_JS), but they only make it quicker to narrow; the list
# is whole and current without them. The refresh is cheap: the page is
# rendered at most once every PAGE_CACHE seconds however many ask for it.
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
# for one. A suffix after a hyphen (1.1.0-dev.8) is a pre-release, the name
# a GitHub pre-release is tagged with (site 1.2.0): a preview, offered only
# for a board no full release carries, and never "the newest release". Its
# parts are letters, digits and hyphens between single dots, so the name is
# one path component and can never be "..".
FIRMWARE_VER  = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,4})"
                           r"(?:-([0-9A-Za-z-]{1,20}(?:\.[0-9A-Za-z-]{1,20}){0,3}))?$")
FIRMWARE_CHIP = re.compile(r"^[a-z][a-z0-9]{2,11}$")
# A family's version.txt: one line, the version exactly as that board shows
# it (SYS, ABOUT, Improv), which the firmware's tools/release.py writes from
# BBS_VERSION_SHOWN. The core version alone for the reference ESP32 ("1.0.3"),
# the core then the board profile's own in brackets for a board with one
# ("1.1.0 (S3 1.0.0)"). Plain ASCII, brackets and not a middle dot, because
# a PETSCII or plain ASCII terminal cannot show one.
FIRMWARE_SHOWN = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,4})(-[0-9A-Za-z.-]{1,40})?"
                            r"(?: \(([A-Za-z0-9][A-Za-z0-9 .-]{0,30})\))?$")

# ESP Web Tools, the one piece of JavaScript on this site, served from this
# machine rather than from a CDN.
#
# It used to come from unpkg, pinned to an exact version. Pinning stops the
# code changing between one reader and the next, but it still hands every
# visitor's browser to a third party at the moment they are about to let a
# page write to a device on their desk, and it puts a hole in the claim that
# nothing a visitor loads comes from anywhere but here. So the bundle is in
# the repository, byte for byte as published, under vendor/.
#
# What is in vendor/esp-web-tools/<version>/ is the package's dist/web
# directory and nothing else: install-button.js, which is the self-contained
# browser build, and the chunks it imports. Every import in them is relative
# ("./install-dialog-....js"), so the chunks load from the same directory and
# the bundle needs no import map and no other origin. dist/install-button.js
# is the NPM entry point instead and has bare imports a browser cannot
# resolve, which is why the web directory is the one vendored.
#
# Its licence, and the licences of the libraries built into it, sit beside
# it and are linked from the page. vendor/esp-web-tools/README.md says where
# the files came from, how they were checked, and how to move to a newer
# version.
EWT_VERSION = "10.4.0"
EWT_DIR     = (pathlib.Path(__file__).resolve().parent
               / "vendor" / "esp-web-tools" / EWT_VERSION)
# The path it is served under carries a revision of this site's own beside
# upstream's version, and the revision goes up whenever a file in the
# directory changes. Every file there is cached for a day, and the chunks
# import each other by relative name, so a changed dialog under the same URL
# would reach a browser up to a day late, running beside a page that already
# expects the new one. A new path is fetched fresh, whole. The bare version
# is still served, for a tab left open across a deploy, which has the old
# entry point loaded and fetches the rest of the bundle as it goes.
EWT_REV     = 3
EWT_PATH    = EWT_VERSION + "-" + str(EWT_REV)
EWT_BASE    = "/install/esp-web-tools/" + EWT_PATH + "/"
# Every path the bundle has been served under: the bare version and each
# earlier revision still answer, with today's files, so a tab left open
# across a deploy keeps finding the chunks it asks for.
EWT_PATHS   = (EWT_VERSION,) + tuple(EWT_VERSION + "-" + str(n) for n in range(1, EWT_REV + 1))
EWT_SCRIPT  = EWT_BASE + "install-button.js"
# A chunk name is the only thing a request can choose, and it is checked as a
# name, the way static_file() does it: letters, digits, "-" and "_", then
# ".js". The two licence files are the only other things served from there.
EWT_FILE    = re.compile(r"^[A-Za-z0-9_-]{1,64}\.js$")
EWT_TEXT    = ("LICENSE", "THIRD_PARTY_LICENSES.txt")

# Seconds ESP Web Tools waits, after writing an image, for the board to
# answer over Improv Wi-Fi Serial, which is how the browser offers to set
# up the Wi-Fi. The board speaks Improv from firmware 0.22.1 on, so every
# release offered here does.
#
# Thirty rather than the tool's default ten because the first boot after a
# full erase formats two filesystems before the board is listening, and a
# board that answers after the page has stopped asking gets no Wi-Fi step at
# all: the reader is left with a board that never joined anything and no
# idea why. Waiting longer than needed costs a spinner.
EWT_IMPROV_WAIT = 30

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
# otadata, ota_0 and storage rows of its partitions.csv.
#
# None means "this family's bootloader offset", from FLASH_FAMILIES above.
#
# ota_data_initial.bin is the otadata partition in its starting state, which
# says "boot the first application slot". It is written because firmware.bin
# always goes into that first slot, and a board that had ever switched to
# the second one would otherwise go on booting whatever was left there.
# PlatformIO builds it alongside the application.
#
# storage.bin is the storage partition, which is the screens. PlatformIO
# calls the file littlefs.bin; a release names it after the partition it is
# written to. The other two filesystems are deliberately absent: userdata
# holds the accounts, the live configuration and each plugin's files, and
# logs holds the caller log. Not writing them is what lets somebody
# reinstall over a board they already run without losing it, and it is the
# same split "pio run -t flashall" respects. After a full erase the board
# formats both on its first boot.
FLASH_PARTS = (("bootloader.bin",       None),
               ("partitions.bin",       0x8000),
               ("ota_data_initial.bin", 0xF000),
               ("firmware.bin",         0x20000),
               ("storage.bin",          0x3C0000))

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
    sd           INTEGER
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
CREATE TABLE IF NOT EXISTS hits (
    address TEXT PRIMARY KEY,
    at      INTEGER NOT NULL
);
"""

CLEAN = re.compile(r"[\x00-\x1f\x7f]")


# The site's version is the newest heading in CHANGELOG.md, read once at
# start. Not a constant here as well: two copies of a version number are two
# chances to disagree, and the changelog is the one that gets written. A
# deployment without the file (it has to be installed beside this one; see
# deploy/setup.sh) shows no version rather than failing to start.
def _site_version():
    try:
        text = (pathlib.Path(__file__).resolve().parent / "CHANGELOG.md").read_text(
            encoding="utf-8")
    except OSError:
        return ""
    m = re.search(r"^## (\d+\.\d+\.\d+)", text, re.M)
    return m.group(1) if m else ""


SITE_VERSION = _site_version()


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
#
# Donate is last, and it is in the menu because Rob looked for it and could
# not find it: it was one word in the middle of the footer's second row. The
# menu had been held at nine on the grounds that a phone could carry no
# more, which was measured when it was written and is not true of this one:
# at 390px "Donate" lands on the row "Get listed" and "Data" already share,
# and at 1366 and 1920 the menu is still one row.
NAV = (("list",  "/",          "Boards"),
       ("about", "/",          "What this is"),
       ("list",  "/whofor",    "Who it's for"),
       ("list",  "/terminals", "Terminals"),
       ("list",  "/firstcall", "First call"),
       ("list",  "/build",     "Build one"),
       ("list",  "/forward",   "Go public"),
       ("list",  "/how",       "Get listed"),
       ("data",  "/",          "Data"),
       ("list",  "/donate",    "Donate"))

# A page that is not in the menu still has a place in it. Every one of these
# is a child of a section that is, so the section lights up rather than
# nothing. Without it, six pages said nothing about where the reader was and
# two of them said "Boards", which is worse: a nav built entirely around
# reverse-video "you are here" was actively lying on them.
NAV_SECTION = {
    "/dialing":         "/terminals",
    "/privacy":         "/firstcall",
    # Deliberately not in the menu. Both are reached from the page they
    # belong to: a ten item menu is already at the edge of what a phone can
    # carry, and neither is something a general visitor is hunting for.
    # Being off the menu is not the same as being buried, and they are the
    # first and the most prominent links on /whofor.
    "/kids":            "/whofor",
    "/teachers":        "/whofor",
    "/sdcard":          "/build",
    # Putting the firmware on a board is a step of building one, so it
    # lights up the section a reader came from. Not in the menu itself:
    # ten items is already the edge of what a phone can carry, and this is
    # the button at the top of /build and /setup, the card beside the board
    # list's heading, and in the footer of every page.
    "/install":         "/build",
    # The setup guide is the step after installing, so it is Build one too.
    "/setup":           "/build",
    # The boards that have run the firmware, with pictures, linked from the
    # installer's picker and from /build's table of chips (site 1.2.0).
    "/hardware":        "/build",
    # Where the installer's last step lands, with the board's address.
    "/connected":       "/build",
    # Putting a new version on a board that already runs one: the
    # installer's other job, so the same section.
    "/upgrade":         "/build",
    "/forward-netgear": "/forward",
    "/forward-tplink":  "/forward",
    "/forward-asus":    "/forward",
    "/forward-xfinity": "/forward",
    "/forward-mesh":    "/forward",
    # The key to the board list belongs to the board list. Written with its
    # face because "/" alone is every face's own home, and on the about
    # face that would light "What this is" for a page about badges.
    "/badges":          "list:/",
}


def nav_here(role, here):
    """The menu entry a page belongs to, as the link that entry is served
    as on this face. A section written "face:/path" names a face."""
    here = NAV_SECTION.get(here, here)
    if ":" in here and not here.startswith("http"):
        face, path = here.split(":", 1)
        here = site_url(face, role, path)
    return here


def nav_html(role, here=""):
    here = nav_here(role, here)
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
    """The top of every page: wordmark and the freedoms beside it, then the
    same menu everywhere."""
    return ('<div class="masthead">'
            + logo_html(site_url("list", role, "/"))
            + ticker_html(nav_index(role, here)) + "</div>"
            + nav_html(role, here))


def nav_index(role, here=""):
    """The position in the menu of the section this page belongs to, or 0
    for a page that belongs to none. Matched exactly the way nav_html marks
    the current item, so the two cannot disagree about where a reader is."""
    here = nav_here(role, here)
    for i, (target, path, _label) in enumerate(NAV):
        if site_url(target, role, path) == here:
            return i
    return 0


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
    # Two rows, because eleven links in one run read as a list of
    # everything: the pages somebody works through to get a board going,
    # and the pages they come back to.
    start = " &middot; ".join(
        f'<a href="{site_url("list", role, p)}">{t}</a>' for p, t in (
            ("/build", "Build one"), ("/install", "Install"), ("/upgrade", "Upgrade"),
            ("/setup", "Set up"),
            ("/terminals", "Terminals"), ("/dialing", "Dial links"),
            ("/forward", "Go public"), ("/how", "Get listed")))
    # "Donate", first in its row and in the warm colour, as well as last in
    # the menu, because Rob looked for it and could not find it. It was
    # "Support", in the middle of the row, the same colour as everything
    # round it, and "Support" reads as help with a problem as often as it
    # reads as money. The word people scan for is the one on the link now.
    refer = " &middot; ".join(
        [f'<a class="donate" href="{site_url("list", role, "/donate")}">Donate</a>']
        + [f'<a href="{site_url("list", role, p)}">{t}</a>' for p, t in (
            ("/rules", "House rules"), ("/badges", "Badges"), ("/feed.xml", "RSS"))]
        + [f'<a href="{site_url("data", role, "/api/boards.json")}">JSON</a>'])
    links = ('<span class="row"><span class="lbl">Get started</span> ' + start + "</span>"
             '<br><span class="row"><span class="lbl">Reference</span> ' + refer + "</span>")
    parts = [others, links] if others else [links]
    if extra:
        parts.append(extra)
    # The colophon, last and smallest: which version of the site this is,
    # whose it is, and the terms it is under, on every page. Each of the
    # three is one unbreakable piece, so a phone gets two tidy rows rather
    # than a licence name broken across a line.
    colophon = ('<p class="colophon">'
                + (f'<span>Site version {SITE_VERSION}</span> &middot; '
                   if SITE_VERSION else "")
                + "<span>&copy; 2026 Robert Mech</span> &middot; "
                '<span><a href="https://www.gnu.org/licenses/old-licenses/gpl-2.0.html">'
                "GNU GPL v2 or later</a></span></p>")
    return "<br><br>".join(parts) + colophon




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
# NULL for "not sent", which every row written before it is.
BADGE_COLUMNS = (("system",        "TEXT NOT NULL DEFAULT ''"),
                 ("terminals",     "TEXT NOT NULL DEFAULT ''"),
                 ("guests",        "INTEGER"),
                 ("features",      "TEXT NOT NULL DEFAULT ''"),
                 ("support",       "TEXT NOT NULL DEFAULT ''"),
                 ("tracked_since", "INTEGER NOT NULL DEFAULT 0"),
                 ("interests",     "TEXT NOT NULL DEFAULT ''"),
                 ("sd",            "INTEGER"))


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
# A page name is a name, not a path: no slashes, no dots, nothing to
# climb out of the directory with.
PAGE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")

# The target may carry one level of balanced parentheses, and must not carry
# a space. Microsoft's archived documentation lives at URLs like
# ".../aa767914(v=vs.85)", and the old pattern stopped at the first ")": the
# href lost its closing parenthesis and 404'd, and the ")" it left behind
# was printed after the link text. Two of the sources on /dialing rendered
# like that for as long as the page existed.
_MD_LINK   = re.compile(r"\[([^\]]+)\]\(((?:[^()\s]|\([^()\s]*\))+)\)")
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
_MD_GATE   = re.compile(r"^::: (from|until) (\d+)\.(\d+)\.(\d+)\s*$")


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
#
# "art" is a drawing by name: "::: art" on one line, the name on the next,
# ":::" to close. The markup lives in ART in this file rather than in the
# page, because the dialect has no inline HTML on purpose and an SVG typed
# into a Markdown file would be the first exception to that.
#
# "cta" is a page's one primary action, drawn as a button: see cta_html().
# "connected" is the box on /connected that shows a board's address, and
# "installer-terms" is the line naming the installer's code and its licence.
# "badges" is one group of the key to the board list's badges on /badges:
# "board", "directory", "support" or "interests" on the first line inside
# it, then the Markdown that goes under the group's heading. "badgefind" is
# the search at the top of that page, with its script. Both are built from
# the tables the board list draws with. "board" is one tested board's
# picture and facts on /hardware, the board's folder name on the first line
# inside it, built from BOARDS and what is on disk (site 1.2.0).
BLOCK_NAMES = CARD_BLOCKS + ("installer", "art", "thanks", "cta", "connected",
                             "installer-terms", "badges", "badgefind", "board")


# --------------------------------------------------------------------------
# The thanks list on /donate: supporters who said yes to being named, one
# per line in supporters.txt beside this file. It is read on each render,
# so adding a name is editing a text file and nothing else.
#
# An empty list renders nothing at all, heading included. A heading over an
# empty list reads as "nobody has helped", which is not a thing a page
# should say on anybody's behalf, and the list starts empty.
# --------------------------------------------------------------------------
SUPPORTERS_FILE = pathlib.Path(__file__).resolve().parent / "supporters.txt"


def thanks_html():
    try:
        lines = SUPPORTERS_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    names = [l.strip() for l in lines if l.strip() and not l.strip().startswith("#")]
    if not names:
        return ""
    return ('<h3>The thanks list</h3><ul class="thanks">'
            + "".join(f"<li>{html.escape(n[:80])}</li>" for n in names)
            + "</ul>")


def md_block(kind, lines):
    """A ":::" block, by name. Cards, the installer, a drawing, or the
    thanks list."""
    if kind == "installer":
        return installer_html(lines)
    if kind == "installer-terms":
        return installer_terms_html()
    if kind == "thanks":
        return thanks_html()
    if kind == "art":
        return art_html(lines)
    if kind == "cta":
        return cta_html(lines)
    if kind == "connected":
        return connected_html(lines)
    if kind == "badges":
        return legend_html(lines)
    if kind == "badgefind":
        return badge_find_html()
    if kind == "board":
        return board_html(lines)
    return md_cards(kind, lines)


# --------------------------------------------------------------------------
# A page's one primary action, as a button, with the other way round beside
# it as a quieter, outlined one.
#
#     ::: cta
#     [Visit the web installer](/install)
#     [Build from source](#getting-it-running)
#     A line or two under the buttons, in the page's own words.
#     :::
#
# The first line that is a link and nothing else is the filled button, the
# second such line is the outlined one, and anything else is the note under
# them. One filled button a page, which is the point: an entry page with two
# things shouting at the same size has not decided what it is for, and Rob
# could not find the browser installer on /build because it was the third
# sentence of a box. On a phone the two stack, filled first, full width.
#
# A button that goes somewhere says where it goes. Only the button on
# /install says "Install", because only that one installs: Rob, on the
# first version of these, which said "Install from your browser" and then
# showed another page with another button on it.
# --------------------------------------------------------------------------
_MD_LONE_LINK = re.compile(r"^\[([^\]]+)\]\(((?:[^()\s]|\([^()\s]*\))+)\)$")


def cta_html(lines):
    """The ::: cta block: one filled button, an outlined one beside it, and a
    note under both. The home page builds one the same way, from a list."""
    button, alt, note = "", "", []
    for ln in (l.strip() for l in lines):
        m = _MD_LONE_LINK.match(ln)
        if m and not (button and alt) and m.group(2).startswith(("/", "#", "https://")):
            href = html.escape(m.group(2), quote=True)
            text = md_inline(m.group(1))
            if not button:
                button = f'<a class="btn" href="{href}">{text}</a>'
            else:
                alt = f'<a class="btn2" href="{href}">{text}</a>'
        elif ln:
            note.append(ln)
    out = '<div class="cta"><p class="acts">' + button + alt + "</p>"
    if note:
        out += '<p class="note">' + md_inline(" ".join(note)) + "</p>"
    return out + "</div>"


# --------------------------------------------------------------------------
# /connected: where the installer's last step lands.
#
# A board answers the installer's Wi-Fi step with its own address as
# telnet://<ip>:6400. ESP Web Tools offers that as a link, and a browser
# cannot open telnet://, so the copy of it vendored here was changed to
# send a telnet address to /connected#<ip>:<port> instead (see the notice
# at the top of vendor/esp-web-tools/10.4.0/install-dialog-*.js).
#
# The address travels in the fragment on purpose. A fragment never leaves
# the browser: it is not in the request, not in the server's log, and not
# in a Referer, so a reader's home network address is never recorded here.
# That is also why this is the second page on the site with JavaScript and
# the first with any written here: nothing but the page itself can read a
# fragment. The script is a dozen lines, reads nothing else, sends nothing
# anywhere, and writes with textContent only, so a fragment somebody made
# up cannot put markup on the page. It accepts a dotted IPv4 address and
# an optional port, which is all the firmware sends (main.cpp sendUrl), and
# ignores anything else.
#
# With no fragment, or no script, the box shows the Markdown inside the
# block instead: how to find the address another way. Since site 1.0.0 the
# dialog's dashboard always offers Telnet details, and a board it read
# before it joined Wi-Fi has sent no address yet, so that dashboard sends a
# reader here with no fragment at all: the Markdown is the three ways to
# find the board, and it is a page people will actually land on.
# --------------------------------------------------------------------------
CONNECTED_JS = (
    "<script>(function(){"
    "var m=/^#((?:\\d{1,3}\\.){3}\\d{1,3})(?::(\\d{1,5}))?$/.exec(location.hash);"
    "if(!m||m[1].split('.').some(function(o){return +o>255;}))return;"
    "var v={host:m[1],port:m[2]||'6400'};"
    "if(+v.port<1||+v.port>65535)return;"
    "v.url='telnet://'+v.host+':'+v.port;"
    "document.querySelectorAll('#found [data-c]').forEach(function(e){"
    "e.textContent=v[e.getAttribute('data-c')];});"
    "document.getElementById('c-link').href=v.url;"
    "document.getElementById('found').hidden=false;"
    "document.getElementById('noaddr').hidden=true;"
    "})();</script>")


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
    "var f=d.getElementById('fform');if(!f)return;"
    "var det=d.getElementById('filter'),rows=all('tr[data-b]'),"
    "tab=d.getElementById('boards'),none=d.getElementById('fnone'),"
    "line=d.getElementById('factive');"
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
    "history.replaceState(null,'',location.pathname+(q.length?'?'+q.join('&'):'')"
    "+(det.open?'#filter':''));}"
    "f.addEventListener('change',apply);"
    "f.addEventListener('submit',function(e){e.preventDefault();det.open=false;});"
    "det.addEventListener('toggle',apply);"
    "all('[data-clear]').forEach(function(a){a.addEventListener('click',function(e){"
    "e.preventDefault();all('input[name=b]',f).forEach(function(c){c.checked=false;});"
    "apply();});});"
    "if(location.hash==='#filter')det.open=true;apply();}"
    "if(d.readyState==='loading')d.addEventListener('DOMContentLoaded',go);else go();"
    "})();</script>")


def connected_html(lines):
    """The address box on /connected, and the way to find the address when
    the page was not given one. Every place the address appears is an empty
    element marked data-c="host", "port" or "url", which the script fills."""
    missing = md_render("\n".join(lines)) if any(l.strip() for l in lines) else ""
    host, port = '<span data-c="host"></span>', '<span data-c="port"></span>'
    return ('<div class="board-at" id="found" hidden>'
            '<p class="lbl">Your board is at</p>'
            f'<p class="where"><code>{host}</code> port <code>{port}</code></p>'
            "<p>From a command line:</p>"
            f"<pre>telnet {host} {port}</pre>"
            '<ul><li><b>As a link</b>: <a id="c-link" href="/dialing" '
            'data-c="url"></a>, which opens if your computer has a telnet '
            'program that takes links. <a href="/dialing">Making the dial links '
            "work</a> sets one up.</li>"
            f"<li><b>SyncTERM</b>: <code>syncterm telnet://{host}:{port}</code>, "
            "or a new entry in its dialing directory, type Telnet, with this "
            "address and port.</li>"
            f"<li><b>PuTTY</b>: <code>putty -telnet {host} -P {port}</code>, or "
            "this address and port with the connection type set to Other: "
            "Telnet, and Window, Translation set to CP437 so the art draws "
            "right.</li></ul>"
            '<p class="note">That address came from your own browser, not from '
            "this site: the part of a link after the # never leaves your "
            "computer.</p></div>"
            # Not class "none": that is the board list's empty line, faint
            # and padded, and it took this box's words with it.
            '<div class="board-at unknown" id="noaddr">' + missing + "</div>"
            + CONNECTED_JS)


def art_html(lines):
    """The drawings an "::: art" block names, one per line.

    A name that is not in ART prints as a paragraph, the same rule an
    unknown ":::" block follows: a typo should be visible on the page, not
    a hole where a drawing was meant to be.
    """
    out = []
    for name in (ln.strip() for ln in lines):
        if not name:
            continue
        out.append(ART.get(name) or "<p>" + html.escape("art: " + name) + "</p>")
    return "".join(out)


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
        inner = pix + (f'<h2 id="{md_id(head)}">{md_inline(head)}</h2>' if head else "")
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


# --------------------------------------------------------------------------
# Heading ids, so a page can be linked to part way down: the amber box in
# the install card points at "#before-you-start", and a troubleshooting
# section is something people send each other a link to.
#
# The slug is the heading's visible text, lower case, with every run of
# anything but a-z and 0-9 turned into one "-" and the ends trimmed. It is
# unique per page: a second "Wi-Fi" heading becomes "wi-fi-2". A page is
# rendered in pieces (a gated block, a card, the column beside the install
# card are each rendered by a nested md_render), so the set of ids already
# used lives for the whole of the outermost call rather than for one piece,
# per thread, because the server answers requests on several at once.
# --------------------------------------------------------------------------
_md_ctx = threading.local()


def md_id(text):
    """The id for a heading whose Markdown source is `text`."""
    seen = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)      # a link's words
    seen = re.sub(r"[*`]", "", seen)
    slug = re.sub(r"[^a-z0-9]+", "-", seen.lower()).strip("-") or "section"
    used = getattr(_md_ctx, "ids", None)
    if used is None:
        return slug
    got, n = slug, 2
    while got in used:
        got, n = f"{slug}-{n}", n + 1
    used.add(got)
    return got


def md_render(text):
    """The small subset of Markdown the pages use."""
    top = getattr(_md_ctx, "ids", None) is None
    if top:
        _md_ctx.ids = set()
    try:
        return _md_render(text)
    finally:
        if top:
            _md_ctx.ids = None


def _md_render(text):
    out, para, bullets, code = [], [], [], None
    quote = []            # consecutive "> " lines: one warning, not one per line
    steps = []            # "1. " lines: a numbered list, not a paragraph
    first_step = [1]      # its first number, so a list split by a drawing carries on
    gate = None           # "::: from|until X.Y.Z": [version, depth, lines, until]
    beside = None         # "::: install-top": [depth, lines]
    table = None
    card = None           # a "::: cards" block, collected whole
    comment = False       # inside "<!-- ... -->": a note for whoever edits the page

    def flush():
        if para:
            out.append("<p>" + md_inline(" ".join(para)) + "</p>")
            para.clear()
        if bullets:
            out.append("<ul>" + "".join(f"<li>{md_inline(b)}</li>"
                                        for b in bullets) + "</ul>")
            bullets.clear()
        if steps:
            start = f' start="{first_step[0]}"' if first_step[0] != 1 else ""
            out.append(f"<ol{start}>" + "".join(f"<li>{md_inline(s)}</li>"
                                                 for s in steps) + "</ol>")
            steps.clear()
        if quote:
            out.append(md_callout(quote))
            quote.clear()

    for raw in text.splitlines():
        line = raw.rstrip()

        # "::: from 1.0.2" ... ":::" is prose for a firmware not yet
        # released: rendered only once a release at that version or later
        # is on disk, the way the announcement banner waits for 1.0.0. It
        # may hold a drawing, so it counts ":::" pairs rather than ending
        # at the first. "::: until 1.1.0" (site 1.1.0) is the other half:
        # prose that stops being true when that release lands, rendered
        # only while the newest release on disk is older, or there is none.
        # A pair of them swaps one account for the other on the day the
        # release is published, with nobody editing the page.
        if gate is not None:
            if line.startswith("::: "):
                gate[1] += 1
            elif line.strip() == ":::":
                if gate[1] == 0:
                    rels = firmware_releases()
                    reached = bool(rels) and rels[0]["sort"] >= gate[0]
                    if reached != gate[3]:
                        out.append(md_render("\n".join(gate[2])))
                    gate = None
                    continue
                gate[1] -= 1
            gate[2].append(raw)
            continue
        if code is None and card is None and _MD_GATE.match(line):
            # Whatever was open before it ends here, so a gate straight
            # after a list or a paragraph cannot land in front of it.
            if table is not None:
                out.append(md_table(table))
                table = None
            flush()
            m = _MD_GATE.match(line)
            want = tuple(int(g) for g in m.groups()[1:])
            gate = [want, 0, [], m.group(1) == "until"]
            continue

        # "::: install-top" ... ":::" is the top of /install: the steps in
        # one column and the install card beside them. It holds drawings
        # and the "::: installer" block itself, so it counts ":::" pairs
        # the way the gate does. See install_top_html().
        if beside is not None:
            if line.startswith("::: "):
                beside[0] += 1
            elif line.strip() == ":::":
                if beside[0] == 0:
                    out.append(install_top_html(beside[1]))
                    beside = None
                    continue
                beside[0] -= 1
            beside[1].append(raw)
            continue
        if code is None and card is None and line.strip() == "::: install-top":
            beside = [0, []]
            continue

        # A comment is dropped whole and never reaches the page. It exists
        # for notes that belong beside the words they are about, such as a
        # step that must not be written until the firmware can do it. It
        # has to start a line outside a fenced block or a card: inside those
        # "<!--" is content and is left alone. An unclosed one would swallow
        # the rest of the page, so selftest.py counts them in every page.
        if comment:
            if "-->" in line:
                comment = False
            continue
        if code is None and card is None and line.lstrip().startswith("<!--"):
            if "-->" not in line:
                comment = True
            continue

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
            out.append(f'<h3 id="{md_id(line[4:])}">{md_inline(line[4:])}</h3>')
        elif line.startswith("## "):
            flush()
            out.append(f'<h2 id="{md_id(line[3:])}">{md_inline(line[3:])}</h2>')
        elif line.startswith("> "):
            if para or bullets:
                flush()
            quote.append(line[2:])            # consecutive lines are one warning
        elif line.startswith("# "):
            flush()
            out.append(f'<h1 id="{md_id(line[2:])}">{md_inline(line[2:])}</h1>')
        elif line.startswith("- "):
            if para or steps:
                flush()
            bullets.append(line[2:])
        elif _MD_STEP.match(line):
            if para or bullets:
                flush()
            if not steps:
                first_step[0] = int(line.split(".", 1)[0])
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
    if beside is not None:                          # unterminated install-top
        out.append(install_top_html(beside[1]))
    if card is not None:                            # unterminated ::: block
        out.append(md_block(card[0], card[1]))
    if code is not None:                            # unterminated fence
        out.append("<pre>" + html.escape("\n".join(code)) + "</pre>")
    if para:
        out.append("<p>" + md_inline(" ".join(para)) + "</p>")
    if bullets:
        out.append("<ul>" + "".join(f"<li>{md_inline(b)}</li>" for b in bullets) + "</ul>")
    if steps:
        start = f' start="{first_step[0]}"' if first_step[0] != 1 else ""
        out.append(f"<ol{start}>" + "".join(f"<li>{md_inline(s)}</li>" for s in steps)
                   + "</ol>")
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
        # here is the sentence that says what the page is for. A drawing or
        # a comment can come first, and neither is a sentence: without
        # skipping them, a page opening with its cover was described to
        # every link preview as "::: art".
        in_block = False
        for line in text[head.end():].splitlines():
            line = line.strip()
            if in_block:
                in_block = line != ":::"
                continue
            if line.startswith("::: "):
                in_block = True
                continue
            if line.startswith("<!--"):
                continue
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
    # The drawings' stylesheet goes in once, and only on a page that has a
    # drawing, the way DIAGRAM_CSS rides with the manifesto rather than
    # living in PAGE and costing every page on the site.
    # The install card carries a small drawing of its own, so a page with the
    # installer on it needs the sheet whether or not it has an "::: art".
    wants_installer = re.search(r"^::: installer\s*$", text, re.M) is not None
    if ("::: art" in text or wants_installer
            or re.search(r"^::: board\s*$", text, re.M)):
        body = ART_CSS + body
    # The installer's script, and the only page that can carry it. (The two
    # other scripts on the site are written here and ride with a block of
    # their own: the dozen lines on /connected with "::: connected", see
    # CONNECTED_JS, and the badge search on /badges with "::: badgefind",
    # see BADGE_JS, which the board list carries as well.)
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
    # JavaScript is still true of the manifesto. The script itself comes
    # from this machine; see EWT_SCRIPT.
    head = ""
    if wants_installer and firmware_offered():
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


def _firmware_pre_key(suffix):
    """A pre-release suffix as something to sort by: dot-separated parts,
    numbers compared as numbers and before words, the way semantic versions
    order them, so dev.10 is after dev.9."""
    return tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in suffix.split("."))


def _firmware_shown(vdir, chip):
    """The version one image set says it is, exactly as the board shows it,
    or "" when the set does not say. version.txt first, which is what the
    firmware's release writes into every family's folder since 1.1.0 and the
    fetcher installs from the release's assets; then the per-family
    manifest.json that the same release writes for trying images by hand.
    Neither is trusted beyond its shape: a line that is not a version, and
    anything longer than one, is not read."""
    f = vdir / chip / "version.txt"
    try:
        if f.is_file() and f.stat().st_size <= 128:
            line = f.read_text(encoding="ascii", errors="replace").strip()
            if FIRMWARE_SHOWN.match(line):
                return line
    except OSError:
        pass
    f = vdir / chip / "manifest.json"
    try:
        if f.is_file() and f.stat().st_size <= 8192:
            v = json.loads(f.read_text(encoding="utf-8")).get("version")
            if isinstance(v, str) and FIRMWARE_SHOWN.match(v.strip()):
                return v.strip()
    except (OSError, ValueError, AttributeError):
        pass
    return ""


def _firmware_sets(vdir):
    """{chip directory: its image set} for one release directory, complete
    sets only, in directory order. A set is the chip family, the five parts
    with their offsets (paths relative to the set's own folder), and the
    version it says it is.

    A family is offered only when every part in FLASH_PARTS is present. A
    missing or misspelled file drops that family out entirely, which is the
    behaviour worth having: a manifest naming a file that is not there fails
    in the browser, halfway through, on somebody's board, and reads as a
    broken flasher rather than as a bad upload."""
    sets = {}
    try:
        chips = sorted(p.name for p in vdir.iterdir() if p.is_dir())
    except OSError:
        return sets
    for chip in chips:
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
            parts.append({"path": name,
                          "offset": boot if offset is None else offset})
        if parts:
            sets[chip] = {"family": family, "parts": parts,
                          "shown": _firmware_shown(vdir, chip) or vdir.name}
    return sets


def firmware_sets():
    """Every version directory on disk holding at least one complete image
    set, releases and previews alike, newest first.

    A preview is a directory named for a pre-release (1.1.0-dev.8). It sorts
    below the release it leads to and above the one before, and it is never
    what firmware_releases() calls a release. Anything else in the
    directory, README.md included, is not a version and is skipped without
    comment.
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
        sets = _firmware_sets(vdir)
        if not sets:
            continue
        date, note = "", ""
        meta = vdir / "release.txt"
        if meta.is_file():
            lines = meta.read_text(encoding="utf-8", errors="replace").splitlines()
            for i, raw in enumerate(lines):
                s = raw.strip()
                if not s:
                    continue
                # "improv: yes" used to switch the Wi-Fi step on per
                # release. Every release now speaks Improv, so the line
                # means nothing; it is skipped rather than shown as the
                # release's note, which is what it would otherwise become.
                # "version ..." and "commit ..." are the firmware's own
                # release.txt, written into release/<ver>/install/ for a
                # copy made by hand: the version is the directory's name
                # and the commit is for the record, so neither is a note.
                low = s.lower()
                if low.startswith(("improv:", "version ", "commit ")):
                    continue
                if re.match(r"^\d{4}-\d{2}-\d{2}$", s) and not date and not note:
                    date = s
                elif not note:
                    note = s[:160]
        sort = tuple(int(g) for g in m.groups()[:3])
        pre = m.group(4) or ""
        found.append({"version": vdir.name,
                      "sort": sort,
                      "key": sort + ((0, _firmware_pre_key(pre)) if pre else (1,)),
                      "pre": bool(pre),
                      "date": date, "note": note,
                      "notices": (vdir / "THIRD_PARTY_NOTICES.md").is_file(),
                      "sets": sets,
                      "builds": [{"chipFamily": s["family"],
                                  "parts": [dict(p, path=chip + "/" + p["path"])
                                            for p in s["parts"]]}
                                 for chip, s in sets.items()]})
    found.sort(key=lambda r: r["key"], reverse=True)
    return found


def firmware_releases():
    """Every complete release on disk, newest first, capped at FIRMWARE_KEEP.

    A release is complete when at least one chip family in it is complete.
    Releases only: a preview is never one, so it never lights a "::: from"
    gate, the announcement banner or a board's update arrow, all of which
    read "the newest release" from here.
    """
    return [r for r in firmware_sets() if not r["pre"]][:FIRMWARE_KEEP]


def board_offers(chip):
    """What /install offers for one board: the releases that carry its image
    set, newest first, up to FIRMWARE_KEEP; or, when no release on disk
    carries it, the newest preview that does, alone. Each board is looked
    at on its own, so the ESP32 stays on its newest release while a board
    only a preview carries is offered that preview."""
    every = firmware_sets()
    full = [r for r in every if not r["pre"] and chip in r["sets"]]
    if full:
        return full[:FIRMWARE_KEEP]
    return [r for r in every if r["pre"] and chip in r["sets"]][:1]


def firmware_offered():
    """Whether /install has anything to install at all, on any board."""
    return any(board_offers(b["dir"]) for b in BOARDS)


def firmware_manifest(version, update=False, chip=None):
    """The ESP Web Tools manifest for one board's image set in one release,
    or None.

    One board a manifest, and only that board's build in it (site 1.2.0).
    ESP Web Tools picks a build by the chip family it reads out of the
    board, so a manifest naming both would hand any ESP32-S3 the Waveshare
    image with the Waveshare's pins. With one build, a board of the other
    family is refused before anything is written ("Your ESP32 board is not
    supported."), and the picture in the picker covers a different board of
    the same family.

    chip names the board's set, and the manifest is served from inside its
    folder, /install/<version>/<chip>/manifest.json, so the parts are bare
    names. With no chip it is the ESP32's, served where every manifest was
    before 1.2.0, /install/<version>/manifest.json, with its folder in each
    path: a page cached from before, or a link written down, still gets the
    reference board and nothing else.

    The version is the set's own, as the board shows it ("1.1.0 (S3
    1.0.0)"), because ESP Web Tools compares it with what the board says
    over Improv to decide whether the board already runs it.

    The schema is theirs and the spellings are not negotiable: the top level
    is snake_case and the keys inside a build are camelCase, which is the
    easiest thing here to get wrong. An offset is a JSON number, decimal,
    because their type is `offset: number` and JSON has no hex literal; a
    string would be handed to the flasher unparsed.

    With update=True it is the Update button's manifest: the same in every
    key, plus "unleashed_update": true, which the copy of the dialog served
    here reads as "never erase, never ask". It keeps
    new_install_prompt_erase on purpose. ESP Web Tools erases the whole chip
    by default unless that key is set, so a manifest that left it out
    because this one does not ask would erase on any copy of the dialog
    that does not know the extra key: upstream's, or this site's own from
    before 0.22.1, still in a browser's cache. With it set, the worst an
    old copy can do is ask, with the box unticked.
    """
    board = chip or "esp32"
    for rel in board_offers(board):
        if rel["version"] != version:
            continue
        s = rel["sets"][board]
        where = "" if chip else board + "/"
        man = {
            "name": "unleashed BBS",
            "version": s["shown"],
            # The user is asked rather than erased by default, and that is
            # what lets somebody reinstall over a board they already run
            # without losing their accounts: with this false, every install
            # is a whole-chip erase. The checkbox ESP Web Tools shows starts
            # unticked, so this flips the default from erase to keep, and
            # the page has to say which one a reader wants.
            "new_install_prompt_erase": True,
            # Seconds to wait after an install for the board to answer over
            # Improv Wi-Fi Serial. See EWT_IMPROV_WAIT for why it is thirty.
            "new_install_improv_wait_time": EWT_IMPROV_WAIT,
            "builds": [{"chipFamily": s["family"],
                        "parts": [dict(p, path=where + p["path"]) for p in s["parts"]]}],
        }
        if update:
            man["unleashed_update"] = True
        return man
    return None


# The two install buttons' symbols (site 1.0.0): a fresh chip with a
# sparkle for a new board, and a chip inside an arrow going round it for an
# update. Line art in a 24 unit square at the stroke weight the badges'
# drawings use, drawn in the button's own colour, and hidden from a screen
# reader because the button's words say it already.
BTN_ICON_NEW = (
    '<svg class="bi" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
    '<rect x="4" y="9" width="11" height="11" rx="1.5"/>'
    '<path d="M7 9 V6.5 M12 9 V6.5 M7 20 V22.5 M12 20 V22.5 M4 12.5 H1.5 '
    'M4 16.5 H1.5 M15 12.5 H17.5 M15 16.5 H17.5"/>'
    '<circle cx="7" cy="12" r="0.9" fill="currentColor" stroke="none"/>'
    '<path d="M19.5 1.2 C19.5 3.8 20.2 4.5 22.8 4.5 C20.2 4.5 19.5 5.2 19.5 7.8 '
    'C19.5 5.2 18.8 4.5 16.2 4.5 C18.8 4.5 19.5 3.8 19.5 1.2 Z"/></svg>')
BTN_ICON_UPDATE = (
    '<svg class="bi" viewBox="0 0 24 24" aria-hidden="true" focusable="false">'
    '<rect x="9" y="9" width="6" height="6" rx="1"/>'
    '<path d="M10.5 9 V7.8 M13.5 9 V7.8 M10.5 15 V16.2 M13.5 15 V16.2 M9 10.5 H7.8 '
    'M9 13.5 H7.8 M15 10.5 H16.2 M15 13.5 H16.2"/>'
    '<path d="M17.66 17.66 A8 8 0 1 1 17.66 6.34"/>'
    '<path d="M17.38 3.15 L17.66 6.34 L14.47 6.06"/></svg>')


# The boards (site 1.2.0, Rob: "update the flasher to select the board type
# ... include an image for confirmation so the user flashes the right one.
# Small picture in the pick list"). Two pictures, drawn here in the hand of
# the site's other drawings: the same classes, the same stroke weights,
# 96 x 60 units so the picker shows them at about 1:1 and the tested boards
# page at twice that, which is the scale the step drawings reach on a
# desktop. Decoration beside words that say the same thing, so each is
# aria-hidden: the name and the "how to tell" line carry the meaning.
#
# The ESP32 dev board, the reference: a long board with a header down each
# side, the module's metal can at one end with its antenna past the edge of
# the board, the USB socket at the other end between the two buttons.
BOARD_ART_ESP32 = (
    '<svg class="art board" viewBox="0 0 96 60" aria-hidden="true" focusable="false" '
    'preserveAspectRatio="xMidYMid meet">'
    '<rect class="o" x="8" y="14" width="80" height="32" rx="2"/>'
    '<rect class="g" x="11" y="15.5" width="72" height="4" rx="1"/>'
    '<rect class="g" x="11" y="40.5" width="72" height="4" rx="1"/>'
    '<path class="d" d="' + " ".join(
        f"M{13 + i * 5} 14 V9.5 M{13 + i * 5} 46 V50.5" for i in range(15)) + '"/>'
    '<rect class="o" x="57" y="21.5" width="36" height="17" rx="1"/>'
    '<rect class="k" x="58.5" y="23" width="23" height="14" rx="0.8"/>'
    '<path class="d" d="M84.5 24 H91 V27 H85 V30 H91 V33 H85 V36 H91"/>'
    '<rect class="gb" x="3" y="25" width="10" height="10" rx="1"/>'
    '<rect class="d" x="4.5" y="27.5" width="3.5" height="5" rx="0.6"/>'
    '<rect class="o" x="15" y="21.5" width="5" height="5" rx="0.8"/>'
    '<circle class="k" cx="17.5" cy="24" r="1.4"/>'
    '<rect class="o" x="15" y="33.5" width="5" height="5" rx="0.8"/>'
    '<circle class="k" cx="17.5" cy="36" r="1.4"/>'
    '<rect class="d" x="26" y="25.5" width="9" height="9" rx="0.8"/>'
    '<circle class="lf" cx="42" cy="30" r="1.4"/>'
    "</svg>")

# The Waveshare ESP32-S3-LCD-1.47: a USB-A stick, drawn the way its screen
# is used, portrait with the plug at the top (the firmware's own
# ESP32_BOARD_CHOICE.md): the plug's shell with its two windows, the body,
# and the screen on it showing lines of figures and the row of lamps the
# firmware's status panel draws along the bottom.
BOARD_ART_S3 = (
    '<svg class="art board" viewBox="0 0 96 60" aria-hidden="true" focusable="false" '
    'preserveAspectRatio="xMidYMid meet">'
    '<rect class="o" x="38" y="2" width="20" height="13" rx="1"/>'
    '<rect class="d" x="41.5" y="5.5" width="4.5" height="3"/>'
    '<rect class="d" x="50" y="5.5" width="4.5" height="3"/>'
    '<rect class="o" x="34" y="15" width="28" height="43" rx="3"/>'
    '<rect class="g" x="37.5" y="18.5" width="21" height="35" rx="1"/>'
    '<path class="lt" d="M40.5 23 H51"/>'
    '<path class="d" d="M40.5 28 H55.5 M40.5 32.5 H52 M40.5 37 H54 M40.5 41.5 H49"/>'
    '<circle class="lf" cx="41.5" cy="48.5" r="1.1"/>'
    '<circle class="c5" cx="45.5" cy="48.5" r="1.1"/>'
    '<circle class="c1" cx="49.5" cy="48.5" r="1.1"/>'
    '<circle class="lf" cx="53.5" cy="48.5" r="1.1"/>'
    "</svg>")

# The boards /install offers, in the order its picker lists them. A board
# is an image set, the folder a release keeps that board's five parts in,
# which is the firmware's own name for the build (tools/release.py, BUILDS).
# A second board on the same chip would be a second folder and a second row
# here, never a second name for one folder: the manifest picks a build by
# chip family alone.
#
# "tell" is the one line that says which board a reader has, beside the
# picture, and it is short on purpose: the card is 26rem wide. "before" is
# what a board needs done before either button, in the card's own Markdown,
# and the steps on /install say why. "buy" is where Rob bought the one that
# was tested, for the tested boards page.
BOARDS = (
    {"dir": "esp32", "name": "ESP32 dev board",
     "part": "ESP32-WROOM-32E, 4 MB flash",
     "tell": "Two rows of pins and a USB socket",
     "art": BOARD_ART_ESP32,
     "page": "/hardware#esp32-dev-board",
     "buy": "https://link.amazon/B08MTidlU",
     "before": ""},
    {"dir": "esp32s3", "name": "Waveshare ESP32-S3-LCD-1.47",
     "part": "ESP32-S3R8, 16 MB flash, 8 MB PSRAM",
     "tell": "A USB stick with a colour screen",
     "art": BOARD_ART_S3,
     "page": "/hardware#waveshare-esp32-s3-lcd-1-47",
     "buy": "https://link.amazon/B0bb1oJqt",
     # From Rob's bench: the stick has no USB-serial chip, and on his PC the
     # installer's automatic reset did not reach it.
     "before": ("**First:** hold **BOOT**, tap **RESET**, let go of BOOT. "
                "**When it is done:** press **RESET**. [Why](#on-the-waveshare-s3)")},
)
BOARD_BY_DIR = {b["dir"]: b for b in BOARDS}


def board_version(rel, chip):
    """The version one board's image set says it is, for a reader: exactly as
    the board shows it for a release ("1.0.3", "1.1.0 (S3 1.0.0)"), and
    "1.1.0 preview" in place of the pre-release name for a preview, the
    board's own part kept. The exact string is on the version line under
    the buttons, so it can be matched against the board's SYS screen."""
    shown = rel["sets"][chip]["shown"]
    if not rel["pre"]:
        return shown
    m = FIRMWARE_SHOWN.match(shown)
    core = ".".join(str(n) for n in rel["sort"])
    return core + " preview" + (f" ({m.group(5)})" if m and m.group(5) else "")


def installer_html(lines=()):
    """The ::: installer block: the install card, or an honest account of
    why there is no button.

    There is deliberately no third state. Either something installable is
    on disk and the page offers it, or nothing is and the page says so;
    nothing here can render a button that fetches a file that does not
    exist.

    The lines inside the block are the short list of things to have ready,
    written in the page's own Markdown and shown in the card's amber box, so
    the words stay in pages/install.md with the rest of the page's words.

    Since site 1.2.0 the card opens with the board picker: each board in
    BOARDS as a native radio, with its picture, its name, one line on how to
    tell it, and the version this page would put on it. The checked one
    decides which buttons, version line and notices show, with no script,
    the way a kept older release always has; each board's buttons fetch a
    manifest holding that board's build and nothing else. A board with
    nothing on disk says "coming soon" and has no buttons.

    The card is laid out for /install's layout spec
    (internal/tty-ux-install-page-2026-09-23.md in the firmware repository):
    the amber box, the picker, the buttons, one version line and the notices
    link, in that order on a desktop. On a phone the stylesheet reorders it
    so the picker and the buttons come first.
    """
    offers = [(b, board_offers(b["dir"])) for b in BOARDS]
    if not any(o for _b, o in offers):
        # No button, and no element for a button to live in: a control that
        # cannot do anything is a puzzle, and a reader who presses it learns
        # nothing about why.
        return (
            '<div class="installer none">'
            "<h2>No release published yet</h2>"
            "<p>There is no firmware image on this site to install yet. "
            "The installer is ready and the board is ready for it: what is "
            "missing is the first published release. When one is put here, "
            "this box becomes a button, and nothing else about this page "
            "changes.</p>"
            "<p>Until then, a board takes about ten minutes to build "
            'yourself, and the <a href="/build">build page</a> has every '
            "step.</p>"
            "</div>")

    out = ['<div class="installer">']

    # The picker. The first board with something to install is chosen to
    # start with, which is the reference ESP32 whenever it has a release.
    first = next(j for j, (_b, o) in enumerate(offers) if o)
    out.append('<fieldset class="boards"><legend>Your board '
               '<a href="/hardware">which is mine?</a></legend>')
    for j, (b, o) in enumerate(offers):
        ver = ("Firmware " + board_version(o[0], b["dir"])) if o else "Coming soon"
        out.append(f'<label class="bopt"><input type="radio" name="fwboard" id="fwb{j}"'
                   + (" checked" if j == first else "") + ">"
                   + b["art"]
                   + '<span class="bt"><b>' + html.escape(b["name"]) + "</b>"
                   + '<span class="tell">' + html.escape(b["tell"]) + "</span>"
                   + '<span class="bv' + ("" if o else " soon") + '">'
                   + html.escape(ver) + "</span></span></label>")
    out.append("</fieldset>")

    for j, (b, o) in enumerate(offers):
        out.append(f'<div class="bsec b{j}">')
        if not o:
            out.append('<p class="soon">There is no image for this board on this '
                       "site yet. When one is published, its buttons appear here. "
                       f'<a href="{b["page"]}">About this board</a>.</p>')
            out.append("</div>")
            continue
        if len(o) > 1:
            # Short labels, so both fit on one line of the card: the line
            # under the buttons says the rest.
            out.append(f'<p class="vers" role="radiogroup" aria-label="Version">')
            for i, rel in enumerate(o):
                v = html.escape(rel["version"])
                what = " (newest)" if i == 0 else ""
                out.append(f'<label><input type="radio" name="fwver{j}" id="fwv{j}_{i}"'
                           + (" checked" if i == 0 else "") + f"> {v}{what}</label>")
            out.append("</p>")
        if b["before"]:
            out.append('<p class="first">' + md_inline(b["before"]) + "</p>")
        d = html.escape(b["dir"], quote=True)
        for i, rel in enumerate(o):
            v = html.escape(rel["version"], quote=True)
            # Our own button in the activate slot. The element exports three
            # colour variables and no ::part(), so anything beyond a colour
            # means supplying the element, and this page is monospace on
            # black rather than a rounded blue pill. The version is not on
            # the button: the line under it says which, once.
            #
            # Two buttons, two manifests (0.22.1, Rob: "just offer an
            # upgrade button ... then we dont have anyone freaked out"). The
            # first is the install as it always was, erase question and all.
            # The second fetches manifest-update.json, whose one extra key
            # makes the copy of the dialog served here skip the erase
            # question and refuse to erase on every path; see
            # firmware_manifest() and the notice at the top of the dialog
            # chunk. It needs no fallback text of its own: the first
            # button's says it once, and the second hides itself on a
            # browser that cannot use it.
            out.append(f'<esp-web-install-button class="r{i}" manifest="/install/{v}/{d}'
                       '/manifest.json"><button class="go" slot="activate">'
                       + BTN_ICON_NEW + "Install on a new board</button>"
                       # Both fallbacks are given rather than left to the
                       # component's defaults, which name Firefox first and
                       # say nothing about what to do next. The precedence
                       # in their code is insecure-context first, so
                       # "not-allowed" is the one a reader sees over plain
                       # http and never the other.
                       '<span class="no" slot="unsupported">This browser cannot talk '
                       "to a serial port. Chrome or Edge on a desktop or laptop can, "
                       "and so can Firefox from version 151; there is more about "
                       'that <a href="#other-browsers">below</a>.</span>'
                       '<span class="no" slot="not-allowed">This page has to be '
                       "served over https for a browser to allow it near a serial "
                       "port.</span></esp-web-install-button>")
            out.append(f'<esp-web-install-button class="r{i} upd" manifest="/install/{v}/{d}'
                       '/manifest-update.json"><button class="go upd" slot="activate">'
                       + BTN_ICON_UPDATE + "Update my board</button>"
                       '<span slot="unsupported"></span><span slot="not-allowed"></span>'
                       "</esp-web-install-button>")
        for i, rel in enumerate(o):
            meta = "Version " + html.escape(rel["sets"][b["dir"]]["shown"])
            if rel["pre"]:
                meta += ", a preview"
                if rel["date"]:
                    meta += ", published " + html.escape(rel["date"])
            elif rel["date"]:
                meta += ", released " + html.escape(rel["date"])
            out.append(f'<p class="meta ver r{i}">' + meta + ".</p>")
        for i, rel in enumerate(o):
            if rel["notices"]:
                out.append(f'<p class="meta notices r{i}"><a href="/install/'
                           + html.escape(rel["version"], quote=True)
                           + '/THIRD_PARTY_NOTICES.md">What is inside it, and under '
                           "what terms</a></p>")
        out.append("</div>")

    out.append('<p class="meta fam">Each image is for its own chip. The installer '
               "reads the board first and stops, writing nothing, if it is the "
               "other kind.</p>")
    # The amber box comes after the buttons since site 1.2.0, on a desktop
    # as it already did on a phone: the picker took the room it had, and
    # Rob's rule for the card is both buttons on the first screen at 1366 x
    # 768 (site 1.0.0).
    pre = "\n".join(lines).strip()
    if pre:
        out.append('<div class="pre">' + md_render(pre) + "</div>")

    # The rules that make the radios work, generated for what is on the
    # page: the board picked shows its section and hides the one picked to
    # start with; inside a section, a version picked shows its buttons, line
    # and link and hides the newest's. Without :has() the board picked to
    # start with stays showing, which is the reference board.
    rules = []
    for j, (_b, o) in enumerate(offers):
        if j != first:
            rules.append(f".installer .bsec.b{j}{{display:none}}"
                         f".installer:has(#fwb{j}:checked) .bsec.b{first}{{display:none}}"
                         f".installer:has(#fwb{j}:checked) .bsec.b{j}{{display:flex}}")
        for i in range(1, len(o)):
            rules.append(f".installer .b{j} .r{i}{{display:none}}"
                         f".installer:has(#fwv{j}_{i}:checked) .b{j} .r0{{display:none}}"
                         f".installer:has(#fwv{j}_{i}:checked) .b{j} .r{i}{{display:block}}")
    if rules:
        out.append("<style>" + "".join(rules) + "</style>")
    out.append("</div>")
    return "".join(out)


def board_html(lines):
    """The ::: board block on the tested boards page: one board's picture
    and its facts, from BOARDS and from what is on disk, so the page and the
    installer's picker can never name different versions. The first line
    inside the block is the board's folder name ("esp32", "esp32s3"); an
    unknown one renders nothing, the way an unknown drawing does."""
    name = next((l.strip() for l in lines if l.strip()), "")
    b = BOARD_BY_DIR.get(name)
    if b is None:
        return ""
    o = board_offers(b["dir"])
    if o:
        ver = board_version(o[0], b["dir"])
        exact = o[0]["sets"][b["dir"]]["shown"]
        build = (html.escape(ver) + ' <a href="/install">on the installer</a>'
                 + (f"; the board calls it {html.escape(exact)}" if exact != ver else ""))
    else:
        build = 'coming soon to <a href="/install">the installer</a>'
    return ('<div class="hwb">' + b["art"].replace('class="art board"',
                                                    'class="art board big"', 1)
            + "<dl>"
            + "<dt>Firmware</dt><dd>" + build + "</dd>"
            + "<dt>Chip</dt><dd>" + html.escape(b["part"]) + "</dd>"
            + "<dt>Looks like</dt><dd>" + html.escape(b["tell"]) + "</dd>"
            + '<dt>Buy one</dt><dd><a href="' + html.escape(b["buy"], quote=True)
            + '" rel="sponsored">Amazon</a> (affiliate link)</dd>'
            + "</dl></div>")


def installer_terms_html():
    """The installer's own terms: somebody else's code, running on this
    page, with changes made here, so its licence is linked as plainly as
    the firmware's notices are. It used to sit in the install card, which
    is for installing; it lives under "Doing it the other way" now. With no
    release on disk there is no installer on the page, so nothing to say."""
    if not firmware_offered():
        return ""
    return ('<p class="meta terms">The installer on this page is '
            '<a href="https://github.com/esphome/esp-web-tools">ESP Web '
            "Tools</a> " + html.escape(EWT_VERSION) + ", served from this site, "
            "with three changes made here: it always offers the board's "
            "telnet details instead of trying to open an address a browser "
            "cannot, its erase question is worded for somebody updating a "
            "board they already run, and the Update button never erases. "
            '<a href="' + EWT_BASE + 'LICENSE">Its licence</a> and '
            '<a href="' + EWT_BASE + 'THIRD_PARTY_LICENSES.txt">the '
            "libraries inside it</a>.</p>")


def install_top_html(lines):
    """The top of /install: the page's title and lead, the install card, and
    the steps, in that order in the markup.

    That order is what a phone and a screen reader get: title, what the page
    does, the button, then what happens when it is pressed. From 901px up
    the stylesheet makes it two columns, the title and the steps on the
    left and the card on the right, spanning both, level with the title and
    sticky, so the button is on the first screen at 1366 x 768 and stays
    beside whichever step a reader has got to. A grid rather than a float,
    because sticky does not work on a float.

    Level with the title rather than with the steps, which is what the spec
    drew, because the amber box as written is seven lines at the card's
    width rather than the five the spec allowed for, and that put the
    button under the fold at 768."""
    before, after, inside, card = [], [], None, None
    for raw in lines:
        s = raw.strip()
        if inside is not None:
            if s == ":::":
                card = installer_html(inside)
                inside = None
            else:
                inside.append(raw)
            continue
        if s == "::: installer" and card is None:
            inside = []
            continue
        (before if card is None else after).append(raw)
    if inside is not None:                          # unterminated installer
        card = installer_html(inside)
    return ('<div class="install-top"><div class="intro">'
            + md_render("\n".join(before)) + "</div>" + (card or "")
            + '<div class="steps">' + md_render("\n".join(after)) + "</div></div>")


def ewt_file(name):
    """One file of the vendored ESP Web Tools bundle, as (bytes, content
    type), or None. Served whether or not a release is published: it is
    static code, and a page with no release never asks for it."""
    if name in EWT_TEXT:
        f = EWT_DIR / name
        ctype = "text/plain; charset=utf-8"
    elif EWT_FILE.match(name):
        f = EWT_DIR / name
        # A module script is refused by the browser unless it arrives with
        # a JavaScript type, which is the one header here that is load
        # bearing rather than polite.
        ctype = "text/javascript; charset=utf-8"
    else:
        return None
    if not f.is_file():
        return None
    return f.read_bytes(), ctype


def firmware_file(rest):
    """One file of a release under /install/, as (bytes, content type), or
    None. `rest` is the path after "/install/".

    Names are checked rather than paths, the way static_file() does it, and
    the shapes accepted are the only ones the page ever links:

        <version>/<chip>/manifest.json         one board's, since site 1.2.0
        <version>/<chip>/manifest-update.json  the same, never erases
        <version>/<chip>/<one of FLASH_PARTS>
        <version>/THIRD_PARTY_NOTICES.md
        <version>/manifest.json                the ESP32's, where it was
        <version>/manifest-update.json         before 1.2.0

    A board's manifests sit in its own folder, so the bare part names they
    carry resolve to that folder's files; the two older paths carry the
    folder in each part's path and resolve to the same files.

    Anything is served only for a version /install offers for that board
    (board_offers), so a version left on disk past FIRMWARE_KEEP, or a
    preview's ESP32 set while the ESP32 has a release, is not reachable by
    guessing its name either.
    """
    bits = [b for b in rest.split("/") if b]
    if not bits or not FIRMWARE_VER.match(bits[0]):
        return None
    offered = {b["dir"]: [r["version"] for r in board_offers(b["dir"])] for b in BOARDS}
    manifests = ("manifest.json", "manifest-update.json")
    vdir = FIRMWARE_DIR / bits[0]

    if len(bits) == 2 and bits[1] in manifests:
        man = firmware_manifest(bits[0], update=bits[1] == "manifest-update.json")
        if man is None:
            return None
        return (json.dumps(man, indent=1).encode("utf-8"),
                "application/json; charset=utf-8")

    if len(bits) == 2 and bits[1] == "THIRD_PARTY_NOTICES.md":
        if not any(bits[0] in v for v in offered.values()):
            return None
        f = vdir / bits[1]
        if not f.is_file():
            return None
        return f.read_bytes(), "text/plain; charset=utf-8"

    if (len(bits) == 3 and FIRMWARE_CHIP.match(bits[1])
            and bits[0] in offered.get(bits[1], ())):
        if bits[2] in manifests:
            man = firmware_manifest(bits[0], update=bits[2] == "manifest-update.json",
                                    chip=bits[1])
            if man is None:
                return None
            return (json.dumps(man, indent=1).encode("utf-8"),
                    "application/json; charset=utf-8")
        if bits[2] in [name for name, _ in FLASH_PARTS]:
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
                f"ELSE public_at END, "
                f"tracked_since=CASE WHEN tracked_since=0 THEN ? "
                f"ELSE tracked_since END WHERE id=?",
                args + [now, state, streak, state, now, now, row["id"]])
            sample(con, row["id"], fields.get("busy") or 0, tz, now)
            tally(con, row["id"], now)
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
<meta property="og:url" content="@CANONICAL@">
<link rel="canonical" href="@CANONICAL@">
<meta property="og:image" content="@AVATAR_URL@">
<meta property="og:image:width" content="1024">
<meta property="og:image:height" content="1024">
<meta property="og:image:alt" content="The µnleashed wordmark inside a circle, over the words Electronic freedom.">
<meta name="twitter:card" content="summary">
<meta name="twitter:image" content="@AVATAR_URL@">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
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
  --struct:#4ce0e0; /* structure only: headings and column names */
  /* The one colour on this site that means somebody else is keeping a
     copy of you. It is the red the manifesto's comparison diagram was
     already drawn in, promoted out of that one block's stylesheet and
     into the palette, because the argument it carries belongs to the site
     and not to a diagram. Nothing on the board list is ever this colour:
     a board that is down is dim, not alarming. */
  --risk:#e06c6c; }}
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
/* The wordmark and the freedoms panel share one row. flex-wrap is the
   safety net rather than the plan: the panel only appears at a width where
   it fits (below), so it should never need to wrap, and if some font the
   stack lands on is wider than measured, wrapping is what happens instead
   of the header running off the side of the page. */
.masthead {{ display:flex; flex-wrap:wrap; align-items:flex-start; gap:0 1.5rem; }}
.masthead pre.logo {{ flex:none; }}
/* The wordmark is the way home. No underline and no colour change, because
   it is already the most recognisable thing on the page; the focus ring is
   the one thing a link has to show, for somebody moving by keyboard. */
.masthead a.home {{ flex:none; display:block; text-decoration:none; color:inherit; }}
.masthead a.home:focus-visible {{ outline:3px solid #ffd35c; outline-offset:4px; }}
/* The announcement banner: one quiet line above the board list's heading,
   and only while there is something to announce (see announcement_banner).
   Yellow, which nothing else on the site is, because it is news rather
   than a warning (amber) or an invitation (the tip box). A strip, not a
   box: a hairline round it, a lit lamp at the front, small type. 0.20.0's
   was a box with a drawing and two buttons in it, and it put the board
   list a screen further down than the news was worth. One line on a
   monitor, two at most on a phone. */
.banner {{ display:flex; align-items:center; gap:0.625rem; margin:0 0 1.125rem;
        padding:0.375rem 0.75rem; background:#15130a; border:1px solid #4a3f17;
        border-left:3px solid #ffd35c; border-radius:0.25rem; color:#fbe7a1;
        font-size:0.8125rem; line-height:1.45; }}
.banner::before {{ content:""; flex:none; width:0.4375rem; height:0.4375rem;
        border-radius:50%; background:#ffd35c; }}
.banner p {{ margin:0; min-width:0; }}
.banner a {{ color:#ffd35c; }}
.banner a:focus-visible {{ outline:3px solid #ffd35c; outline-offset:2px; }}
/* The freedoms, one at a time, beside the wordmark.

   Shown only from 73em up. In em, not px, because em in a media query is
   the reader's own default text size: somebody who has set their browser
   to a larger font has a larger wordmark and a larger panel, and the width
   at which the two fit side by side moves with them. 73em is the wordmark
   in the widest font the stack reaches (Menlo, 46.5em of the default),
   the body padding, the gap and the panel, rounded up.

   Below that it is not shown at all rather than stacked under the
   wordmark. Stacked, it would push the menu down on every page on a phone,
   and the manifesto, which is in the menu, says the same things at length. */
.ticker {{ display:none; }}
@media (min-width: 73em) {{
  .ticker {{ display:block; position:relative; flex:none; width:16rem; height:5.625rem;
          margin-left:auto; }}
}}
.ticker svg.tf {{ position:absolute; top:0; left:0; width:100%; height:100%;
          overflow:visible; }}
.tf .fr {{ fill:none; stroke:var(--dial); stroke-width:1; opacity:0.3; }}
.tf .ac {{ fill:none; stroke:var(--dial); stroke-width:1.5; }}
.tf .dm {{ fill:none; stroke:var(--dial); stroke-width:1; opacity:0.45; }}
.tf .nt {{ fill:var(--name); }}
.tf .sg {{ fill:var(--dial); opacity:0.2; }}
.tf .sg1 {{ opacity:1; }}
.tf .sc {{ fill:none; stroke:var(--dial); stroke-width:1; opacity:0; }}
.tf .ct {{ fill:var(--dial); }}
.ticker p.th {{ position:absolute; left:1rem; top:0.1875rem; margin:0; font-size:0.5625rem;
          line-height:1rem; letter-spacing:0.1875rem; text-transform:uppercase;
          color:var(--name); white-space:nowrap; }}
.ticker ul {{ list-style:none; margin:0; padding:0; }}
.ticker li {{ position:absolute; left:1rem; right:0.75rem; top:1.875rem; height:2.5rem;
          display:flex; align-items:center; gap:0.75rem; opacity:0; }}
.ticker li:first-child {{ opacity:1; }}
.ticker li b {{ display:block; font-weight:normal; color:var(--ink); font-size:0.6875rem;
          line-height:1.35; letter-spacing:0.0625rem; text-transform:uppercase;
          white-space:nowrap; }}
.ticker li i {{ display:block; font-style:normal; color:var(--dim); font-size:0.625rem;
          line-height:1.35; white-space:nowrap; }}
.ticker svg.ti {{ flex:none; width:2.5rem; height:2.5rem; fill:none; stroke:var(--dial);
          stroke-width:1.4; stroke-linecap:round; stroke-linejoin:round; }}
.ticker svg.ti .d {{ opacity:0.6; }}
.ticker svg.ti .xb {{ stroke:var(--bg); stroke-width:4.5; opacity:1; }}
.ticker svg.ti .pn {{ fill:var(--bg); }}
/* Eight freedoms, four seconds each. Every item runs the same 32 second
   timeline and starts four seconds after the one before it. The change is
   out and then in, 0.3 seconds each, rather than both at once: two lines
   of different words at half strength on top of each other read as a
   smudge, not as a change. The first starts 0.6 seconds in, so a page
   opens with a freedom already showing rather than an empty frame. The lit
   segment runs the same timing, the caret crosses the scale once per
   freedom, and the scan line in the icon's brackets keeps its own pace.

   All of it is in here, so a reader who has asked for less motion gets the
   markup's resting state: the first freedom, its segment lit, nothing
   moving. */
@media (prefers-reduced-motion: no-preference) {{
  .ticker li {{ opacity:0; animation:tkshow 32s linear infinite both; }}
  .tf .sg {{ animation:tkseg 32s linear infinite both; }}
  .ticker li:nth-child(1), .tf .sg1 {{ animation-delay:-0.6s; }}
  .ticker li:nth-child(2), .tf .sg2 {{ animation-delay:3.4s; }}
  .ticker li:nth-child(3), .tf .sg3 {{ animation-delay:7.4s; }}
  .ticker li:nth-child(4), .tf .sg4 {{ animation-delay:11.4s; }}
  .ticker li:nth-child(5), .tf .sg5 {{ animation-delay:15.4s; }}
  .ticker li:nth-child(6), .tf .sg6 {{ animation-delay:19.4s; }}
  .ticker li:nth-child(7), .tf .sg7 {{ animation-delay:23.4s; }}
  .ticker li:nth-child(8), .tf .sg8 {{ animation-delay:27.4s; }}
  .tf .ct {{ animation:tkcaret 4s linear -0.6s infinite; }}
  .tf .sc {{ animation:tkscan 2.6s ease-in-out infinite; }}
  @keyframes tkshow {{
    0%, 0.9375% {{ opacity:0; }}  1.875%, 12.5% {{ opacity:1; }}
    13.4375%, 100% {{ opacity:0; }}
  }}
  @keyframes tkseg {{
    0%, 0.9375% {{ opacity:0.2; }}  1.875%, 12.5% {{ opacity:1; }}
    13.4375%, 100% {{ opacity:0.2; }}
  }}
  @keyframes tkcaret {{
    from {{ transform:translateX(0); }}
    to {{ transform:translateX(168px); }}
  }}
  @keyframes tkscan {{
    0% {{ transform:translateY(0); opacity:0; }}
    20% {{ opacity:0.7; }}  80% {{ opacity:0.7; }}
    100% {{ transform:translateY(40px); opacity:0; }}
  }}
}}
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
p.lead {{ color:var(--dim); margin:0 0 1.25rem; }}
/* The board list's figures, as a sentence under its heading rather than a
   run of small faint numbers beside it: "Unleashed is hosting 3 boards
   with 5 callers on right now." The two figures are --live, the colour
   that means up; they are the product, and they are the only colour in
   the line. */
p.stat {{ color:var(--ink); margin:0 0 0.5rem; }}
p.stat .n {{ color:var(--live); }}
/* The top of the board list: the heading, the figures and the lead on the
   left, the "Run your own board" card on the right. From the site's one
   breakpoint up it is a grid column, the way /install's card is, and not a
   float; the card is top aligned, level with the heading, so the table
   starts under whichever of the two is taller. Below it the card follows
   the lead, full width and short.

   19.5rem rather than 18: at 18 the two buttons stacked, which made the
   card half as tall again as the text beside it and pushed the list down
   by the difference. 19.5 holds both on one row, and the line of copy on
   one line, in Menlo, the widest face the font stack reaches (0.602em a
   character against Consolas's 0.55). */
.listtop {{ margin:0 0 1.25rem; }}
.listtop p.lead {{ margin:0; }}
/* The card stands out in --dial, the colour of things you can act on (Rob,
   0.20.2): a wash of it over the page rather than a flat bright block, and
   its border in the same blue. rgba() rather than the variable because a
   custom property cannot take an alpha; 127, 212, 255 is --dial. */
.runcard {{ position:relative; background:rgba(127, 212, 255, 0.12);
        border:1px solid rgba(127, 212, 255, 0.6); border-radius:0.5rem;
        padding:1.125rem 1.25rem; margin:1rem 0 0; }}
/* Two lamps going slowly round the card's edge, half a lap apart, each
   with a short tail of three beads (0.22.0, to the UX spec). Three lamps a
   third of a lap apart looked scattered, because a rectangle has no
   three-fold symmetry; two half a lap apart are always the reflection of
   each other through the card's centre, so on any card shape they read as
   a pair. The head is the row hover's lamp exactly: the same object at a
   different tempo, 20s a lap and linear, because easing lurches at a
   loop's seam.

   Each follows the card's own rounded rectangle with offset-path, on the
   border line. The tail is three beads on the same path rather than a
   gradient bar, because a bar pokes out past every corner and beads bend
   round it. All delays are negative, so nothing jumps at load, and the
   beads are invisible outside the motion block: standing still, with
   reduced motion or without offset-path, it is two lamps, just past the
   top left and bottom right corners, like corner marks. */
.runcard .dot {{ position:absolute; width:0.375rem; height:0.375rem; border-radius:50%;
        background:var(--dial); box-shadow:0 0 0.375rem rgba(127, 212, 255, 0.8);
        pointer-events:none; }}
.runcard .dot.t1 {{ width:0.25rem; height:0.25rem; }}
.runcard .dot.t2 {{ width:0.1875rem; height:0.1875rem; }}
.runcard .dot.t3 {{ width:0.125rem; height:0.125rem; }}
.runcard .t1, .runcard .t2, .runcard .t3 {{ opacity:0;
        box-shadow:0 0 0.25rem rgba(127, 212, 255, 0.6); }}
.runcard .la {{ top:-0.25rem; left:0.5rem; }}
.runcard .lb {{ bottom:-0.25rem; right:0.5rem; }}
@supports (offset-path: inset(0 round 0.5rem)) {{
  .runcard .dot {{ top:0; left:0; right:auto; bottom:auto;
        offset-path:inset(0 round 0.5rem); offset-anchor:center; offset-rotate:0deg; }}
  .runcard .la {{ offset-distance:0%; }}
  .runcard .lb {{ offset-distance:50%; }}
}}
@media (prefers-reduced-motion: no-preference) {{
  @supports (offset-path: inset(0 round 0.5rem)) {{
    .runcard .dot {{ animation:runlap 20s linear infinite; }}
    .runcard .la {{ animation-delay:-0.36s; }}
    .runcard .la.t1 {{ animation-delay:-0.24s; opacity:0.7; }}
    .runcard .la.t2 {{ animation-delay:-0.12s; opacity:0.45; }}
    .runcard .la.t3 {{ animation-delay:0s; opacity:0.2; }}
    .runcard .lb {{ animation-delay:-10.36s; }}
    .runcard .lb.t1 {{ animation-delay:-10.24s; opacity:0.7; }}
    .runcard .lb.t2 {{ animation-delay:-10.12s; opacity:0.45; }}
    .runcard .lb.t3 {{ animation-delay:-10s; opacity:0.2; }}
  }}
  @keyframes runlap {{ from {{ offset-distance:0%; }} to {{ offset-distance:100%; }} }}
}}
.runcard h2 {{ color:var(--struct); font-size:0.875rem; font-weight:normal;
        margin:0 0 0.125rem; }}
.runcard p {{ margin:0; }}
.runcard .say {{ color:var(--dim); font-size:0.75rem; }}
.runcard .acts {{ display:flex; flex-wrap:wrap; gap:0.5rem; margin:0.625rem 0 0; }}
/* Compact, on purpose: the card is a way off the page for the few who
   came to build one, and the board list is what the page is for. The
   installer's full size button lives on /install, where it is the point. */
.runcard a.fill, .runcard a.line {{ display:inline-block; font-size:0.75rem;
        border-radius:0.375rem; padding:0.3125rem 0.5625rem; text-decoration:none;
        text-align:center; white-space:nowrap; }}
.runcard a.fill {{ color:#04212c; background:var(--dial); border:1px solid #9fdfff; }}
.runcard a.fill:hover {{ background:#a7e2ff; }}
.runcard a.line {{ color:var(--dial); background:transparent; border:1px solid #35566b; }}
.runcard a.line:hover {{ border-color:var(--dial); }}
.runcard a.fill:focus-visible, .runcard a.line:focus-visible {{
        outline:3px solid #ffd35c; outline-offset:2px; }}
@media (min-width: 901px) {{
  .listtop {{ display:grid; grid-template-columns:minmax(0, 1fr) 19.5rem;
        column-gap:2rem; align-items:start; }}
  .runcard {{ margin:0; }}
}}
/* On a phone the card is the title and the two buttons: the line of copy
   is left out, so the list keeps its place on the first screen. */
@media (max-width: 900px) {{
  .runcard {{ padding:0.75rem 1rem; }}
  .runcard .say {{ display:none; }}
  .runcard .acts {{ margin:0.5rem 0 0; }}
}}
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
/* Hover only where there is a pointer that hovers. A phone turns a tap into
   a hover that stays until the next tap somewhere else, which left a row
   lit for no reason; (hover: hover) is false there, so nothing sticks. */
@media (hover: hover) and (pointer: fine) {{
  tr:hover td {{ background:#111; }}
}}
.name {{ color:var(--name); }}
/* overflow-wrap, so a 44 character hostname breaks inside its own column
   instead of dictating the geometry of the whole table. */
.addr a {{ color:var(--dial); text-decoration:none; border-bottom:1px dotted #35566b;
        display:inline-block; padding:0.375rem 0; overflow-wrap:anywhere; }}
.addr a:hover {{ border-bottom-style:solid; }}
.desc {{ color:var(--dim); }}
/* --------------------------------------------------------------------
   The badges under a board's name (board_badges() builds them, /badges
   explains them).

   The name has a line to itself, in a box exactly as wide as the name
   (width:fit-content), which is what the hover dot below flies along.
   Then the badges, a flex row that wraps, so a board with fifteen of
   them grows downwards and never pushes the Dial column. Among them is
   the software badge, which used to sit beside the name: what a board
   runs, said quietly, because every board is welcome here and a
   directory that only ever shows one name does not look like it means
   that.

   Two rows since site 1.0.0 (Rob: "The unleashed and esp32 should be
   upfront ... that way they look consistent when scrolling"). .bid is
   what the board is, the software and its version, then the machine;
   .bset is the small badges in ROW_ORDER, the same places on every row.
   Each row is positioned, so on a phone a tooltip hangs from its own
   row.

   One or two letters, or a small drawing, in a colour that says what
   kind of thing it is: purple for what a board speaks, amber for
   guests, blue for what is running, orange for new, cyan for steady,
   lavender for how long it has been listed. The colour is the letters
   and the border over a faint wash of itself; each wash is written out
   as rgba() of its colour, because a custom property cannot take an
   alpha. The k- classes hold the colours so the legend's colour names
   can wear them too.
   -------------------------------------------------------------------- */
.name > .bname {{ display:block; width:fit-content; max-width:100%; position:relative; }}
.name > .desc {{ display:block; }}
.badges {{ display:flex; flex-direction:column; gap:0.25rem; margin:0.375rem 0 0.375rem; }}
.badges > .bid, .badges > .bset {{ position:relative; display:flex; flex-wrap:wrap;
        align-items:center; gap:0.25rem; }}
.bd {{ display:inline-flex; align-items:center; justify-content:center;
        box-sizing:border-box; min-width:1.375rem; min-height:1.25rem; max-width:100%;
        padding:0.0625rem 0.3125rem; border:1px solid var(--bb); border-radius:0.1875rem;
        background:var(--bt); color:var(--bc); font-size:0.6875rem; line-height:1.2;
        letter-spacing:0.03125rem; overflow-wrap:anywhere; cursor:help; }}
.k-soft, .k-sys, .k-term, .k-guest, .k-feat, .k-new, .k-steady, .k-age, .k-sup {{
        --bc:var(--dim); --bb:#2c2c38; --bt:transparent; }}
.k-sys {{ --bc:var(--ink); --bb:#3a3a4a; --bt:rgba(200, 200, 200, 0.05); }}
.k-term {{ --bc:#b48ef0; --bb:rgba(180, 142, 240, 0.55); --bt:rgba(180, 142, 240, 0.12); }}
.k-guest {{ --bc:#e0a94e; --bb:rgba(224, 169, 78, 0.55); --bt:rgba(224, 169, 78, 0.12); }}
.k-feat {{ --bc:#7fd4ff; --bb:rgba(127, 212, 255, 0.5); --bt:rgba(127, 212, 255, 0.1); }}
.k-new {{ --bc:#ef8b5a; --bb:rgba(239, 139, 90, 0.55); --bt:rgba(239, 139, 90, 0.12); }}
.k-steady {{ --bc:#4ce0e0; --bb:rgba(76, 224, 224, 0.5); --bt:rgba(76, 224, 224, 0.1); }}
.k-age {{ --bc:#e2d4ff; --bb:rgba(226, 212, 255, 0.45); --bt:rgba(226, 212, 255, 0.08); }}
.k-sup {{ --bt:#0d0d12; }}
/* Interests (0.22.0) are rose, a family nothing else here uses: the
   drawing is currentColor, so the chip's own colour draws it. */
.k-int {{ --bc:#f096c4; --bb:rgba(240, 150, 196, 0.5); --bt:rgba(240, 150, 196, 0.1); }}
/* Update available (site 1.0.0): a dim cyan, quieter than steady's, because
   it is news for one sysop rather than something every caller wants. */
.k-upd {{ --bc:#5ab4b4; --bb:rgba(90, 180, 180, 0.4); --bt:rgba(90, 180, 180, 0.06); }}
.bd.k-soft, .bd.k-sys {{ font-size:0.75rem; letter-spacing:0; }}
.bd.k-sup, .bd.k-int {{ padding:0 0.125rem; }}
.bd.k-sup svg, .bd.k-int svg, .cb svg {{ display:block; width:1.0625rem; height:1.0625rem;
        fill:none; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; }}
.k-int svg, .k-upd svg {{ stroke:currentColor; }}
/* The arrow on the end of a behind board's software badge: a link to
   /upgrade, joined to the badge by giving back the row's gap and having no
   left edge of its own. */
.bu {{ --bc:#5ab4b4; display:inline-flex; align-items:center; box-sizing:border-box;
        min-height:1.25rem; margin-left:-0.25rem; padding:0 0.1875rem;
        border:1px solid rgba(90, 180, 180, 0.4); border-left:0;
        border-radius:0 0.1875rem 0.1875rem 0; background:rgba(90, 180, 180, 0.06);
        color:var(--bc); text-decoration:none; }}
.bu svg, .bd.k-upd svg {{ display:block; width:0.8125rem; height:0.8125rem; fill:none;
        stroke:currentColor; stroke-width:2.2; stroke-linecap:round; stroke-linejoin:round; }}
.bu:hover {{ color:#8fe3e3; background:rgba(90, 180, 180, 0.16); }}
.bd:focus, .bu:focus {{ outline:none; }}
.bd:focus-visible, .bu:focus-visible {{ outline:3px solid #ffd35c; outline-offset:2px; }}
/* The tooltip, CSS only, from data-tip: on hover for a mouse, and on focus
   for a keyboard or a tap, which is what the tabindex is for. At the
   page's own type size, in a dark box edged in the badge's colour. On a
   desktop it hangs from the badge; below the breakpoint the badge is not
   positioned, so it hangs from the start of the row instead and is never
   wider than the screen, which stops a badge at the right edge pushing the
   page sideways. It takes no pointer events, so it never sits between the
   mouse and whatever is under it. */
.bd::after, .bu::after {{ content:attr(data-tip); position:absolute; left:0;
        top:calc(100% + 0.375rem);
        z-index:5; width:max-content; max-width:min(24rem, calc(100vw - 3rem));
        box-sizing:border-box; padding:0.4375rem 0.625rem; background:#16161e;
        border:1px solid var(--bc); border-radius:0.25rem; color:var(--ink);
        font-size:0.875rem; line-height:1.45; letter-spacing:0; text-align:left;
        white-space:normal; overflow-wrap:normal; box-shadow:0 0.25rem 1rem rgba(0, 0, 0, 0.6);
        visibility:hidden; opacity:0; pointer-events:none; }}
.bd:hover::after, .bd:focus::after, .bu:hover::after, .bu:focus::after {{
        visibility:visible; opacity:1; }}
@media (min-width: 901px) {{
  .bd, .bu {{ position:relative; }}
}}
@media (prefers-reduced-motion: no-preference) {{
  .bd::after, .bu::after {{ transition:opacity 0.12s, visibility 0.12s; }}
}}
/* Anything the page marks hidden stays hidden, whatever display a rule
   below gives it: the filter hides rows, the searches hide tiles, rows and
   groups, and a table row on a phone is display:flex. */
main [hidden] {{ display:none !important; }}
/* --------------------------------------------------------------------
   The filter over the board list (0.22.0; filter_bar_html builds it).

   Closed, it is one small outlined button, "Filter", with the number of
   badges chosen beside it, the key to the badges at the right of the same
   line, and, only while something is chosen, one line under them saying
   how many boards that leaves and which badges, with a way to clear them.
   None of the badges' symbols is on the page until the pane opens.

   Open (0.22.2), the pane is a row per group: the group's name, then its
   chips, small, symbol only, the name in the tooltip on hover and on
   focus. The interests are a heading and a row per sub-group, two rows to
   a line on a desktop. A chip is a checkbox that cannot be seen, over the
   badge's symbol, and shows its state in shapes as well as colour: chosen
   is a ring round it and a notch in its corner; focused is the yellow ring
   every control here gets; hovered is a lighter edge, only where a pointer
   hovers. Every group is a <details>, open: on a phone a tap on its name
   folds it away.
   -------------------------------------------------------------------- */
.fbar {{ position:relative; margin:0 0 0.625rem; }}
.fbar p.keylink {{ position:absolute; top:0; right:0; margin:0; line-height:2rem;
        font-size:0.75rem; }}
details.filter > summary {{ display:inline-flex; align-items:center; gap:0.5rem;
        box-sizing:border-box; min-height:2rem; padding:0.25rem 0.75rem;
        border:1px solid #35566b; border-radius:0.375rem; color:var(--dial);
        font-size:0.75rem; letter-spacing:0.0625rem; text-transform:uppercase;
        list-style:none; cursor:pointer; user-select:none; }}
details.filter > summary::-webkit-details-marker {{ display:none; }}
/* A chevron drawn with two borders, pointing down, then up once open. */
details.filter > summary::after {{ content:""; width:0.375rem; height:0.375rem;
        border:solid currentColor; border-width:0 0.125rem 0.125rem 0;
        transform:translateY(-0.125rem) rotate(45deg); }}
details.filter[open] > summary::after {{ transform:translateY(0.125rem) rotate(-135deg); }}
details.filter[open] > summary {{ border-color:var(--dial);
        background:rgba(127, 212, 255, 0.12); }}
details.filter > summary:focus {{ outline:none; }}
details.filter > summary:focus-visible {{ outline:3px solid #ffd35c; outline-offset:2px; }}
.fc {{ min-width:1.25rem; padding:0 0.3125rem; border-radius:0.625rem; box-sizing:border-box;
        background:var(--dial); color:#04212c; font-size:0.6875rem; line-height:1.25rem;
        text-align:center; letter-spacing:0; }}
.fc:empty {{ display:none; }}
p.factive {{ margin:0.5rem 0 0; color:var(--dim); font-size:0.75rem; }}
p.factive [data-f="n"] {{ color:var(--ink); }}
.fpane {{ margin:0.625rem 0 0.25rem; padding:0.75rem 0.875rem; background:#0f0f15;
        border:1px solid #26303a; border-radius:0.5rem; }}
.ftop {{ display:flex; flex-wrap:wrap; align-items:center; gap:0.625rem 1.5rem;
        margin:0 0 0.625rem; }}
.findbar {{ display:flex; flex-wrap:wrap; align-items:center; gap:0.375rem 0.625rem;
        margin:0; }}
.fpane .findbar {{ flex:1 1 20rem; }}
.findbar label {{ color:var(--dim); font-size:0.75rem; }}
/* 0.875rem is 16px on a phone, where anything smaller makes iOS zoom the
   page the moment the box is touched. */
.findbar input {{ flex:1 1 11rem; min-width:0; box-sizing:border-box; font:inherit;
        font-size:0.875rem; color:var(--ink); background:var(--bg);
        border:1px solid #35566b; border-radius:0.375rem; padding:0.375rem 0.625rem; }}
.findbar input::placeholder {{ color:var(--faint); }}
.findbar input:focus {{ outline:none; border-color:var(--dial); }}
.findbar input:focus-visible {{ outline:3px solid #ffd35c; outline-offset:1px; }}
.fqn {{ color:var(--dim); font-size:0.75rem; }}
/* All of them or any of them, as two small segments. The chosen one is in
   reverse video, which is a change of fill and not only of colour. */
.fmode {{ display:flex; flex-wrap:wrap; align-items:center; gap:0.25rem; margin:0;
        padding:0; border:0; min-width:0; }}
.fmode legend {{ float:left; margin:0 0.375rem 0 0; padding:0; color:var(--dim);
        font-size:0.75rem; }}
.fmode label {{ position:relative; display:block; }}
.fmode input {{ position:absolute; top:0; left:0; width:100%; height:100%;
        margin:0; opacity:0; cursor:pointer; }}
.fmode span {{ display:block; padding:0.25rem 0.625rem; border:1px solid #35566b;
        border-radius:0.375rem; color:var(--dim); font-size:0.75rem; }}
.fmode input:checked + span {{ background:var(--ink); border-color:var(--ink);
        color:var(--bg); }}
.fmode input:focus-visible + span {{ outline:3px solid #ffd35c; outline-offset:2px; }}
/* The rows. A group's name is a column of its own on a desktop and a
   heading over its chips on a phone; the interests' rows go two to a line
   on a desktop, where each of them fits on one. */
.frows {{ display:flex; flex-direction:column; gap:0.3125rem; }}
.fr {{ position:relative; display:flow-root; margin:0; }}
.fr > summary {{ list-style:none; cursor:pointer; user-select:none;
        color:var(--struct); font-size:0.6875rem; letter-spacing:0.0625rem;
        text-transform:uppercase; line-height:1.625rem; }}
.fr > summary::-webkit-details-marker {{ display:none; }}
/* The Filter button's chevron, smaller: down while the row is open, right
   once it is folded, so a folded row says it has more in it. */
.fr > summary::after {{ content:""; display:inline-block; width:0.3125rem;
        height:0.3125rem; margin:0 0 0.1875rem 0.5rem; border:solid currentColor;
        border-width:0 0.125rem 0.125rem 0; transform:rotate(45deg); opacity:0.7; }}
.fr:not([open]) > summary::after {{ transform:rotate(-45deg); margin-bottom:0.0625rem; }}
.fr > summary:focus {{ outline:none; }}
.fr > summary:focus-visible {{ outline:3px solid #ffd35c; outline-offset:2px; }}
.fr.sub > summary {{ color:var(--dim); }}
.fint {{ margin:0.25rem 0 0; }}
.fh {{ margin:0 0 0.125rem; color:var(--struct); font-size:0.75rem;
        letter-spacing:0.0625rem; text-transform:uppercase; }}
.fsub {{ display:flex; flex-direction:column; gap:0.3125rem; }}
.chips {{ display:flex; flex-wrap:wrap; gap:0.25rem; }}
.chip {{ display:block; }}
/* The checkbox, out of sight but still the thing that is focused and
   ticked; the label round it is what a click or a tap lands on. */
.chip input {{ position:absolute; width:0.0625rem; height:0.0625rem; margin:0; opacity:0;
        pointer-events:none; }}
.cb {{ display:flex; align-items:center; justify-content:center; box-sizing:border-box;
        min-width:1.625rem; height:1.625rem; padding:0 0.25rem; border:1px solid var(--bb);
        border-radius:0.25rem; background-color:var(--bt); color:var(--bc);
        font-size:0.6875rem; letter-spacing:0.03125rem; cursor:pointer; }}
.chip input:checked + .cb {{ border-color:var(--dial); box-shadow:0 0 0 0.125rem var(--dial);
        background-color:rgba(127, 212, 255, 0.16);
        background-image:linear-gradient(225deg, var(--dial) 0.3125rem, transparent 0.3125rem); }}
.chip input:focus-visible + .cb {{ outline:3px solid #ffd35c; outline-offset:0.25rem; }}
/* A chip's tooltip is a badge's, hanging under the row the chip is in
   rather than from the chip, so one near the right edge can never push the
   page sideways, and not drawn at all until it is wanted, so a hidden one
   takes up no room either. */
.cb::after {{ content:attr(data-tip); position:absolute; left:0; top:calc(100% + 0.25rem);
        z-index:6; display:none; width:max-content; max-width:min(100%, 24rem);
        box-sizing:border-box; padding:0.375rem 0.625rem; background:#16161e;
        border:1px solid var(--bc); border-radius:0.25rem; color:var(--ink);
        font-size:0.8125rem; line-height:1.4; letter-spacing:0; text-transform:none;
        white-space:normal; box-shadow:0 0.25rem 1rem rgba(0, 0, 0, 0.6);
        pointer-events:none; }}
.chip:hover .cb::after, .chip input:focus + .cb::after {{ display:block; }}
@media (min-width: 901px) {{
  .fr > summary {{ float:left; width:10.5rem; }}
  .cb::after {{ left:10.5rem; max-width:min(calc(100% - 10.5rem), 24rem); }}
  .fsub {{ display:grid; grid-template-columns:repeat(2, minmax(0, 1fr));
        gap:0.3125rem 1.5rem; }}
}}
.fgo {{ display:flex; flex-wrap:wrap; align-items:center; gap:0.5rem 1.25rem;
        margin:0.625rem 0 0; }}
.fgo button {{ font:inherit; font-size:0.75rem; color:#04212c; background:var(--dial);
        border:1px solid #9fdfff; border-radius:0.375rem; padding:0.375rem 0.875rem;
        cursor:pointer; }}
.fgo button:focus-visible, .fgo a:focus-visible, p.factive a:focus-visible {{
        outline:3px solid #ffd35c; outline-offset:2px; }}
.fgo a {{ font-size:0.75rem; }}
@media (hover: hover) and (pointer: fine) {{
  details.filter > summary:hover {{ border-color:var(--dial); }}
  .chip:hover .cb {{ border-color:#7a94a8; }}
  .fmode label:hover span {{ border-color:var(--dial); }}
  .fgo button:hover {{ background:#a7e2ff; }}
}}
/* The pane settles in rather than appearing; only where motion is
   wanted, so with reduced motion it simply opens. */
@media (prefers-reduced-motion: no-preference) {{
  details.filter[open] > .fpane {{ animation:panein 0.18s ease-out; }}
  @keyframes panein {{ from {{ opacity:0; transform:translateY(-0.375rem); }}
        to {{ opacity:1; transform:none; }} }}
}}
/* On a phone: a group's name is a heading over its chips, tall enough to
   tap, and a tap folds the group away. The chips wrap under it. */
@media (max-width: 900px) {{
  .fpane {{ padding:0.625rem; }}
  .fr > summary {{ line-height:2rem; }}
  .chips {{ gap:0.3125rem; padding:0 0 0.25rem; }}
}}
/* --------------------------------------------------------------------
   /badges: every badge in a table, a table per group, each row the
   symbol, the name, the slug and what it means (legend_html builds it).
   A search at the top narrows the rows. On a phone a row becomes a small
   card, the symbol on the left and the rest stacked beside it.
   -------------------------------------------------------------------- */
article .findbar {{ margin:1rem 0 0.5rem; }}
article table.btab {{ width:100%; margin:0.75rem 0 1.5rem; }}
table.btab th {{ font-size:0.75rem; }}
table.btab td {{ vertical-align:top; }}
table.btab td.bsym {{ position:relative; width:7rem; white-space:normal; }}
table.btab .chips {{ display:flex; flex-wrap:wrap; gap:0.25rem; }}
table.btab .bd.k-sup svg, table.btab .bd.k-int svg {{ width:1.5rem; height:1.5rem; }}
table.btab td.bn {{ color:var(--ink); }}
table.btab .cn {{ color:var(--bc); font-size:0.75rem; margin-left:0.25rem; }}
table.btab .src {{ color:var(--dim); font-size:0.75rem; }}
table.btab code {{ white-space:nowrap; }}
table.btab tr.sub th {{ padding-top:1rem; color:var(--dim); font-size:0.6875rem;
        letter-spacing:0.0625rem; text-transform:uppercase; }}
/* The same columns in every group's table, so Slug and Meaning run
   straight down the page rather than jumping at each heading. */
@media (min-width: 901px) {{
  table.btab {{ table-layout:fixed; }}
  table.btab thead th:nth-child(1) {{ width:7.5rem; }}
  table.btab thead th:nth-child(2) {{ width:12rem; }}
  table.btab thead th:nth-child(3) {{ width:14rem; }}
  article .findbar input {{ flex:0 1 26rem; }}
}}
@media (max-width: 900px) {{
  table.btab, table.btab > tbody {{ display:block; }}
  table.btab > thead {{ display:none; }}
  table.btab tr {{ display:grid; grid-template-columns:4.75rem minmax(0, 1fr);
        column-gap:0.75rem; padding:0.625rem 0; border-bottom:1px solid #161616; }}
  table.btab td, table.btab th {{ display:block; padding:0; border:0; }}
  table.btab td.bsym {{ grid-row:1 / span 3; width:auto; }}
  table.btab tr.sub {{ display:block; padding:0.875rem 0 0.25rem; }}
  table.btab tr.sub th {{ padding:0; }}
  table.btab td.bm {{ margin-top:0.125rem; }}
}}
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
     command somebody cannot read at all. It used to except the class the
     ASCII comparison diagram wore, because wrapping would have destroyed
     it; that diagram is an SVG now and the exception went with it. */
  article pre {{ white-space:pre-wrap; overflow-wrap:anywhere; }}
}}
/* The stop box: .tip's shape in .warn's colours, with a drawing where the
   tip has its arrow. Full width, framed on all four sides and rounded,
   because this one is meant to be read before anything else on the page,
   and amber because it is a warning. The drawing sits in space held open
   by padding, the same arrangement as the tip's marker, so text never runs
   under it; on a phone it moves to the bottom right corner and the
   reserve becomes padding-bottom.

   It is not a link and nothing in it is clickable, which is the other half
   of why it is a separate class rather than a colour variant of .tip: the
   tip's stretched overlay would make the whole warning a target. */
article .stop {{ display:block; color:#f0c674; background:#241d10;
        border:1px solid #8a6d39; border-radius:0.625rem;
        padding:1rem 6.75rem 1.125rem 1.25rem; margin:1.375rem 0 1.625rem;
        position:relative; }}
article .stop p {{ margin:0; }}
article .stop b:first-child {{ display:block; color:#ffd35c; font-size:1rem;
        letter-spacing:0.03125rem; margin:0 0 0.3125rem; }}
article .stop svg.skull {{ position:absolute; right:1.25rem; top:50%;
        transform:translateY(-50%); width:4.25rem; height:4.25rem; }}
@media (max-width: 900px) {{
  article .stop {{ padding:0.875rem 1rem 5rem; }}
  article .stop svg.skull {{ top:auto; bottom:0.625rem; right:1rem;
        transform:none; width:3.75rem; height:3.75rem; }}
}}
/* QuantumRob's name, linked to /author from the byline and both
   signatures. The byline keeps its warm colour and the signature its
   quieter one, underlined in both places so the name reads as a link
   without taking the cyan every other link on the page is in. */
.byline a.author {{ color:var(--warm); text-underline-offset:0.1875rem; }}
article .pull .sig a.author {{ color:var(--dim);
        text-underline-offset:0.1875rem; }}
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
/* --------------------------------------------------------------------
   Freedoms gained, in two columns wherever there is width for two.

   The boxes are about 60 characters wide in a 130 character column, so
   one to a row left half the page black and made a list of twelve short
   claims four screens long. Twelve boxes in two columns is six rows and
   reads as one block, which is what it is: a position, not an index.

   Grid and not multi-column. `column-count` would let a box break across
   the boundary, and each of these is one claim that has to stay whole;
   it also fills the first column before the second, so the reading order
   would depend on how tall the boxes happened to be. Grid is row major,
   so the order down the source is the order across the page, and
   somebody listening to it gets the same list in the same order as
   somebody looking at it. Nothing here uses `order:`, deliberately.

   minmax(0, 1fr) and not 1fr: a grid track's default minimum is its
   content, so one long unbroken string in one box would widen its track
   and narrow the other.

   The wrapper takes the indent and the gap takes the spacing, so two
   boxes in a row start at the same height whatever length their text is.
   The row gap is the 1.125rem the collapsed margins used to give, so the
   single column below the breakpoint is spaced exactly as it was.
   -------------------------------------------------------------------- */
article .freedoms {{ display:grid; grid-template-columns:repeat(2, minmax(0, 1fr));
        gap:1.125rem 1.5rem; margin:1.125rem 0 1.125rem 1.875rem; }}
article .freedoms .freedom {{ margin:0; }}
/* The site's one breakpoint. Two columns on a phone is two gutters and
   about fifteen characters a line, which is not a layout. */
@media (max-width: 900px) {{
  article .freedoms {{ grid-template-columns:1fr; }}
}}
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
/* The footer's two rows, each led by what it is, and the colophon under
   them in small type. The labels are the faint colour: structure, not
   something to click. */
footer .lbl {{ color:var(--faint); margin-right:0.5rem; text-transform:uppercase;
        letter-spacing:0.0625rem; font-size:0.75rem; }}
footer .colophon {{ margin:1.25rem 0 0; font-size:0.6875rem; color:var(--faint);
        line-height:1.6; }}
footer .colophon a {{ display:inline; padding:0; color:var(--dim); }}
footer .colophon span {{ white-space:nowrap; }}
/* The installer's dialog is somebody else's element, drawn in light
   Material colours by default. It takes its colours from Material's own
   custom properties, which a rule on the element from this page overrides,
   so it is dark and monospace here without touching its code. */
ewt-install-dialog, ewt-no-port-picked-dialog {{
  --md-sys-color-surface:#14141b; --md-sys-color-surface-container:#14141b;
  --md-sys-color-surface-container-high:#1a1a23;
  --md-sys-color-surface-container-highest:#22222c;
  --md-sys-color-secondary-container:#22222c;
  --md-sys-color-on-surface:#c8c8c8; --md-sys-color-on-surface-variant:#8a8a8a;
  --md-sys-color-outline-variant:#2c2c38; --md-sys-color-scrim:#000;
  --md-sys-color-primary:#7fd4ff; --md-sys-color-on-primary:#04212c;
  --text-color:#c8c8c8; --danger-color:#ff7a7a;
  --md-ref-typeface-brand:ui-monospace,Menlo,Consolas,monospace;
  --md-ref-typeface-plain:ui-monospace,Menlo,Consolas,monospace;
  color:#c8c8c8;
}}
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
/* Every other board a shade lighter than the page, just enough to tell one
   entry from the next. The header is the first row, so the stripe starts
   on the second board. #111116 against the page's #0b0b0f: --dim text is
   5.45:1 on it against 5.69:1 on the page, --ink 11.25 against 11.74 and
   the board's name 7.23 against 7.55, so every line keeps the contrast
   grade it had (AA and better; --faint labels stay the structural 3.5 they
   were chosen as). On the row, not its cells, so on a phone the whole card
   is striped. */
main > table tr:nth-child(odd):not(:first-child) {{ background:#111116; }}
/* With a filter on, the rows it leaves out are still in the table, hidden,
   and a plain nth-child counts them: two striped boards could end up next
   to each other. "of" counts only the rows that are showing. A browser that
   does not know "of" drops these two rules and keeps the one above, which
   is right whenever nothing is filtered. */
main > table tr:not(:first-child):nth-child(even of :not([hidden])) {{ background:transparent; }}
main > table tr:not(:first-child):nth-child(odd of :not([hidden])) {{ background:#111116; }}
/* Hovering a board: a hairline round the row in --dial at low alpha, as an
   outline, so nothing moves by the width of a border; and one of the
   site's small blue lamps flies once along under the board's name,
   trailing a short fading streak, and fades out past the end of it.

   The dot and its streak are the name box's two pseudo-elements. They
   travel by left, from 0 to 100% of that box, which is the name's own
   width, so a long name and a short one both get a whole pass; the streak
   is pinned to the dot by translateX(-100%) and grows to full length in
   the first third, so it never pokes out behind the name's first letter.
   At rest both are transparent. Once per hover, not a loop: the animation
   is applied only while the row is hovered, so it starts afresh on the
   next hover and nothing is left running.

   All of it only where a pointer hovers, so a tap on a phone lights
   nothing that then stays lit; and the flight only where motion is not
   turned down, so with reduced motion a hover is the outline alone. */
.name > .bname::before, .name > .bname::after {{ content:""; position:absolute; left:0;
        opacity:0; pointer-events:none; }}
.name > .bname::before {{ bottom:-0.1875rem; width:1.75rem; height:0.125rem;
        border-radius:0.0625rem; transform:translateX(-100%);
        background:linear-gradient(to right, rgba(127, 212, 255, 0), rgba(127, 212, 255, 0.7)); }}
.name > .bname::after {{ bottom:-0.3125rem; width:0.375rem; height:0.375rem;
        margin-left:-0.1875rem; border-radius:50%; background:var(--dial);
        box-shadow:0 0 0.375rem rgba(127, 212, 255, 0.8); }}
@media (hover: hover) and (pointer: fine) {{
  main > table tr:not(:first-child):hover {{ outline:1px solid rgba(127, 212, 255, 0.35);
        outline-offset:-1px; }}
}}
@media (prefers-reduced-motion: no-preference) {{
  @keyframes nametail {{
    0% {{ left:0; width:0; opacity:0; }}
    10% {{ opacity:1; }}
    30% {{ width:1.75rem; }}
    85% {{ left:100%; opacity:1; }}
    100% {{ left:calc(100% + 1.25rem); width:1.75rem; opacity:0; }}
  }}
  @keyframes namedot {{
    0% {{ left:0; opacity:0; }}
    10% {{ opacity:1; }}
    85% {{ left:100%; opacity:1; }}
    100% {{ left:calc(100% + 1.25rem); opacity:0; }}
  }}
}}
@media (prefers-reduced-motion: no-preference) and (hover: hover) and (pointer: fine) {{
  main > table tr:hover .bname::before {{ animation:nametail 1s linear 1 both; }}
  main > table tr:hover .bname::after {{ animation:namedot 1s linear 1 both; }}
}}
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
  /* Half a rem each side, so a striped card's words do not sit flush on
     the edge of its stripe. The pinned state moves in by the same. */
  main > table tr {{ display:flex; flex-direction:column; position:relative;
        padding:0.875rem 0.5rem 1rem; border-bottom:1px solid var(--rule); }}
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
  main > table td.status .state {{ position:absolute; right:0.5rem; top:0.875rem;
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
/* --dim, not the --faint the board list's ".none" line would lend it by
   sharing the class name: these are sentences somebody has to read. */
article .installer.none {{ border-color:#3a3a46; color:var(--dim); }}
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
/* The older release's button: the same element, quieter, because it is the
   way back rather than the way in. */
esp-web-install-button.older {{ margin:0.375rem 0 0; }}
article .installer button.older {{ font:inherit; font-size:0.8125rem;
        color:var(--dial); background:transparent; border:1px solid #2c3a44;
        border-radius:0.375rem; padding:0.5rem 0.875rem; cursor:pointer; }}
article .installer button.older:hover {{ border-color:var(--dial); }}
article .installer button.older:focus-visible {{ outline:3px solid #ffd35c;
        outline-offset:2px; }}
article .installer button.go:focus-visible {{ outline:3px solid #ffd35c;
        outline-offset:2px; }}
/* The two fallbacks the element shows instead of the button. Amber, the
   same as every other warning here, because that is exactly what they
   are: the reason nothing is going to happen on this browser. */
article .installer .no {{ display:block; color:#f0c674; background:#241d10;
        border-left:3px solid #8a6d39; padding:0.625rem 0.875rem;
        border-radius:0.25rem; }}
/* --------------------------------------------------------------------
   The install card, laid out to the /install spec
   (internal/tty-ux-install-page-2026-09-23.md in the firmware repository).

   One column of parts with one gap between them, rather than a margin on
   each: a small drawing, the amber "before you start" box, the board
   slot, the two buttons, one version line, the notices link. The buttons
   are the full width of the card, because they are the things in it to
   press.
   -------------------------------------------------------------------- */
article .installer {{ display:flex; flex-direction:column; gap:0.5rem; }}
article .installer > *, article .installer .meta {{ margin:0; }}
article .installer button.go {{ width:100%; text-align:center; display:flex;
        align-items:center; justify-content:center; gap:0.5rem; }}
/* The buttons' symbols (1.0.0): the badges' line weight, the button's own
   colour, a little taller than the words beside them. */
article .installer button.go svg.bi {{ flex:none; width:1.25rem; height:1.25rem; fill:none;
        stroke:currentColor; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; }}
/* Update my board: the same size and shape as the install button, so it
   reads as the other of two choices rather than as a lesser one, and
   outlined so the two are told apart at a glance. A browser that cannot
   use it gets the first button's explanation, once, and not a second
   empty box. */
article .installer button.go.upd {{ color:var(--dial); background:transparent;
        border:1px solid var(--dial); }}
article .installer button.go.upd:hover {{ background:#102630; }}
article .installer esp-web-install-button.upd[install-unsupported] {{ display:none; }}
article .installer .pre {{ color:#f0c674; background:#241d10;
        border-left:3px solid #8a6d39; border-radius:0.25rem;
        padding:0.625rem 0.875rem; font-size:0.8125rem; }}
article .installer .pre p {{ margin:0; line-height:1.45; }}
article .installer .pre b {{ color:#ffd35c; }}
/* The board picker (site 1.2.0, Rob: "select the board type ... include an
   image for confirmation so the user flashes the right one. Small picture
   in the pick list"). A fieldset of native radios, one row a board: the
   radio, the picture, then the name, how to tell it and the version this
   page would put on it. The chosen row is outlined in --dial on the
   buttons' own dark blue, and keyboard focus rings the whole row. A
   board's buttons, version line and notices are its own section, .bsec,
   shown by the rules under the card. */
article .installer fieldset.boards {{ border:0; margin:0; padding:0; min-width:0;
        display:flex; flex-direction:column; gap:0.25rem; }}
article .installer fieldset.boards legend {{ padding:0; margin:0 0 0.25rem;
        font-size:0.8125rem; color:var(--dim); }}
article .installer fieldset.boards legend a {{ margin-left:0.5rem; }}
article .installer .bopt {{ display:flex; align-items:center; gap:0.625rem;
        padding:0.25rem 0.625rem 0.25rem 0.5rem; border:1px solid #2c3a44;
        border-radius:0.375rem; cursor:pointer; }}
article .installer .bopt input {{ flex:none; margin:0; accent-color:var(--dial); }}
article .installer .bopt:has(input:checked) {{ border-color:var(--dial);
        background:#102630; }}
article .installer .bopt:has(input:focus-visible) {{ outline:3px solid #ffd35c;
        outline-offset:2px; }}
article .installer .bopt .bt {{ display:flex; flex-direction:column; min-width:0;
        font-size:0.8125rem; line-height:1.25; }}
article .installer .bopt .bt b {{ color:var(--ink); }}
article .installer .bopt svg.art.board {{ width:4rem; height:2.5rem; }}
article .installer .bopt .tell {{ color:var(--dim); font-size:0.75rem; }}
article .installer .bopt .bv {{ color:var(--dial); font-size:0.75rem; }}
article .installer .bopt .bv.soon {{ color:var(--faint); }}
article .installer .bsec {{ display:flex; flex-direction:column; gap:0.5rem; }}
article .installer .bsec > * {{ margin:0; }}
/* What a board needs done before either button: an instruction rather than
   a warning, so the calm box and not the amber one. */
article .installer .first {{ color:var(--ink); background:#12121a;
        border-left:3px solid #2c5a70; border-radius:0.25rem;
        padding:0.5rem 0.75rem; font-size:0.8125rem; line-height:1.45; }}
article .installer .first b {{ color:var(--dial); }}
/* A board with nothing to install: says so, in the quiet colours of the
   card with no release, and has no buttons. */
article .installer p.soon {{ color:var(--dim); border:1px dashed #3a3a46;
        border-radius:0.375rem; padding:0.625rem 0.75rem; font-size:0.8125rem; }}
article .installer .vers {{ display:flex; flex-wrap:wrap; gap:0.25rem 1rem;
        margin:0.25rem 0 0; font-size:0.8125rem; color:var(--ink); }}
article .installer .vers label {{ cursor:pointer; }}
/* The title, the card and the steps, and from the site's one breakpoint up
   two columns: title and steps on the left, the card on the right spanning
   both, level with the title. A grid rather than a float, because sticky
   does not work on a float; sticky so the button stays beside whichever
   step a reader has reached. The markup order is title, card, steps, which
   is the order a phone and a screen reader get. */
article .install-top > .installer {{ margin:1.25rem 0 1.5rem; }}
/* The upgrade call-out opens the steps column: beside the card on a
   desktop, and after it on a phone, where the markup puts it. Not indented
   the way a note inside prose is, because nothing above it is prose. */
article .install-top > .steps > p.aside:first-child {{ margin:0 0 1.25rem; }}
/* Site 1.0.0 tightened the card so both buttons are on the first screen at
   1366 x 768 with a second release offered, which is the tallest the card
   gets: a column two rem wider, which takes a line off the amber box; the
   drawing held to 3.5rem tall rather than growing with the width; smaller
   gaps, a little less padding and buttons 0.25rem shorter. The Update
   button went from ending at 831px to about 740px. Re-measure it after
   changing anything in the card or the amber box's words.
   Site 1.2.0 put the board picker at the top of the card and moved the
   amber box under the buttons, and the column is 26rem so a board's name
   and its version line each keep to one line beside the picture. Measured
   with two releases for the ESP32: its Update button ends at 665px, and
   the S3's, under its download-mode note, at 719px. */
@media (min-width: 901px) {{
  article .install-top {{ display:grid; grid-template-columns:minmax(0, 1fr) 26rem;
        grid-template-rows:auto 1fr; column-gap:2rem; align-items:start; }}
  article .install-top > .intro {{ grid-column:1; grid-row:1; }}
  article .install-top > .installer {{ grid-column:2; grid-row:1 / span 2; margin:0;
        position:sticky; top:1rem; padding:1rem 1.25rem; }}
  article .installer button.go {{ padding-top:0.5625rem; padding-bottom:0.5625rem; }}
  article .install-top > .steps {{ grid-column:1; grid-row:2; }}
  article .install-top .steps svg.art.steps {{ margin:1rem 0 1.25rem; }}
}}
/* On a phone the card is one column above the steps, and the picker and
   the buttons come first: the menu already takes the top third of the
   screen, and the "before you start" box ahead of the button would push it
   under the fold of a smaller phone. Rob's call, from the spec's own
   disagreement. Since site 1.2.0 that is the markup's own order, on a
   desktop too, so there is nothing to reorder. */
/* A tested board on /hardware (site 1.2.0): its picture beside what it is,
   the build the installer offers for it and where to buy one, from BOARDS
   and the firmware on disk. The facts wrap under the picture on a phone. */
article .hwb {{ display:flex; flex-wrap:wrap; align-items:flex-start;
        gap:0.875rem 1.5rem; margin:0.75rem 0 1.25rem; }}
article .hwb dl {{ flex:1 1 18rem; min-width:0; margin:0; display:grid;
        grid-template-columns:auto minmax(0, 1fr); gap:0.25rem 1rem; }}
article .hwb dt, article .hwb dd {{ margin:0; line-height:1.5; }}
article .hwb dt {{ color:var(--dim); }}
/* A page's one primary action, drawn like the installer's button, with
   the other way round beside it outlined, the way the installer card draws
   a kept older release, and a note under both. On a phone the two stack,
   filled first, each the full width of the column. */
.cta {{ margin:1.25rem 0 1.5rem; }}
.cta p {{ margin:0; }}
.cta .acts {{ display:flex; flex-wrap:wrap; align-items:center; gap:0.75rem 1rem; }}
.cta a.btn, .cta a.btn2 {{ display:inline-block; font-size:0.9375rem;
        border-radius:0.375rem; padding:0.6875rem 1.25rem; text-decoration:none;
        text-align:center; }}
.cta a.btn {{ color:#04212c; background:var(--dial); border:1px solid #9fdfff; }}
.cta a.btn:hover {{ background:#a7e2ff; }}
.cta a.btn2 {{ color:var(--dial); background:transparent; border:1px solid #35566b; }}
.cta a.btn2:hover {{ border-color:var(--dial); }}
.cta a.btn:focus-visible, .cta a.btn2:focus-visible {{ outline:3px solid #ffd35c;
        outline-offset:2px; }}
.cta .note {{ color:var(--dim); margin:0.75rem 0 0; }}
@media (max-width: 900px) {{
  .cta .acts {{ flex-direction:column; align-items:stretch; }}
  .cta a.btn, .cta a.btn2 {{ display:block; }}
}}
/* /connected: the board's address, in the installer card's colours. */
article .board-at {{ background:#12121a; border:1px solid #2c3a44;
        border-radius:0.5rem; padding:1.125rem 1.25rem; margin:1.25rem 0 1.5rem; }}
article .board-at.unknown {{ border-color:#3a3a46; }}
article .board-at > :last-child {{ margin-bottom:0; }}
article .board-at .lbl {{ margin:0; color:var(--dim); font-size:0.75rem;
        letter-spacing:0.0625rem; text-transform:uppercase; }}
article .board-at .where {{ margin:0.25rem 0 1rem; font-size:1.25rem; }}
article .board-at .where code {{ color:var(--live); }}
article .board-at .note {{ color:var(--dim); font-size:0.8125rem; }}
/* The installer's own terms, under "Doing it the other way" on /install. */
article p.terms {{ color:var(--dim); font-size:0.8125rem; }}
/* Donate, in the footer, in the warm colour: the one link there that is
   an ask rather than a reference. */
footer a.donate {{ color:var(--warm); }}
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


def logo_html(home="/"):
    """The wordmark, one <i> per row, as a link to the board list: the home
    page of the site, on every page and every face. No newlines inside the
    <pre>, because each row is a block element, so nothing depends on
    source whitespace.

    The link carries its own name, because a link whose only content is a
    picture is announced by a screen reader as the picture, and "µnleashed"
    says nothing about where it goes."""
    return ('<a class="home" href="' + html.escape(home, quote=True)
            + '" aria-label="\u00b5nleashed: the board list">'
            + '<pre class="logo" role="img" aria-label="\u00b5nleashed">'
            + "".join(f"<i>{row}</i>" for row in LOGO_ROWS)
            + "</pre></a>")


# --------------------------------------------------------------------------
# The freedoms beside the wordmark, one at a time.
#
# The board says these on its own welcome screen: the motto, "no web, no
# cloud, no browser, real hardware", and the GPL line (tools/mkscreens.py in
# the firmware). The header says them too, with three the manifesto argues
# at length. Each one is true of the board as it ships, and each short line
# under it says what the slogan means, because "no cloud" on its own is a
# poster and "nobody else's server" is a fact somebody can check.
#
# Rules this keeps, and a check in selftest.py holds it to them:
#   - Labels are 22 characters at most and the line under them 26. The
#     panel is 16rem, and the widest of the fonts the stack can land on
#     (Menlo, 0.602em a cell) fills 11rem of text column at those lengths.
#   - Every word is in the markup. The fade is opacity, and opacity does not
#     take anything out of the accessibility tree, so a screen reader reads
#     the whole list in order however far the animation has got.
#   - Nothing moves unless the reader's system says motion is welcome. The
#     markup, with no animation applied, shows the first freedom and stops.
#
# Each section of the menu starts the list at a different place: its
# position in the menu, so Boards opens on the first freedom, What this is
# on the second, and so on. The fade starts again on every page load, so
# without this a reader clicking round the site would see the first two of
# eight and never the rest. Data is ninth and wraps round to the first.
# --------------------------------------------------------------------------
FREEDOMS = (
    ("web", "No web", "a BBS, not a website"),
    ("cloud", "No cloud", "nobody else's server"),
    ("browser", "No browser", "a C64 can call in"),
    ("chip", "Real hardware", "a chip on your shelf"),
    ("gpl", "GPL v2 or later", "free software"),
    ("lan", "No internet needed", "a local network is enough"),
    ("rules", "You write the rules", "and you are the appeal"),
    ("list", "Run your own directory", "this one is free software"),
)

# 32 units square, drawn at 2.5rem. Stroke and colour come from the page
# stylesheet, so these are shapes only. "xb" is the gap cut under a slash so
# the slash reads as crossing the drawing rather than joining it, and "pn" is
# the pen's body, filled with the page colour so it sits in front of the
# lines it is writing.
_SLASH = '<path class="xb" d="M5 27 L27 5"/><path d="M5 27 L27 5"/>'
TICKER_ICONS = {
    # A globe, struck out.
    "web": ('<circle cx="16" cy="16" r="11"/>'
            '<ellipse cx="16" cy="16" rx="4.5" ry="11"/>'
            '<path class="d" d="M5 16 H27 M6.5 10.5 H25.5 M6.5 21.5 H25.5"/>'
            + _SLASH),
    # The cloud from the manifesto's "no internet" drawing, struck out.
    "cloud": ('<path transform="translate(-11.8 3.5)" d="M18.5 22 C14 22 14 15.5'
              ' 18.5 15.5 C19 10.5 25.5 9 28 12.5 C30 8 37 8.5 37.5 14 C42 14'
              ' 42 22 37.5 22 Z"/>' + _SLASH),
    # A browser window with its three buttons, struck out.
    "browser": ('<rect x="4" y="7" width="24" height="18" rx="1.5"/>'
                '<path d="M4 11.5 H28"/>'
                '<path d="M7 9.25 H7.01 M9.5 9.25 H9.51 M12 9.25 H12.01"/>'
                '<path class="d" d="M8 15.5 H20 M8 19 H16"/>' + _SLASH),
    # A module the way a WROOM looks: the antenna trace across the top and
    # the metal can under it, with pins down both sides.
    "chip": ('<rect x="7" y="3" width="18" height="26" rx="1"/>'
             '<path class="d" d="M9.5 8.5 V5.5 H12.5 V8.5 H15.5 V5.5 H18.5'
             ' V8.5 H21.5 V5.5 H22.5"/>'
             '<rect x="9.5" y="11.5" width="13" height="14.5" rx="0.8"/>'
             '<path class="d" d="M7 14 H4.5 M7 18 H4.5 M7 22 H4.5 M7 26 H4.5'
             ' M25 14 H27.5 M25 18 H27.5 M25 22 H27.5 M25 26 H27.5"/>'),
    # Copyleft: a C turned to face the other way.
    "gpl": ('<circle cx="16" cy="16" r="12"/>'
            '<path d="M12.27 10.68 A6.5 6.5 0 1 1 12.27 21.32"/>'),
    # A house with a Wi-Fi mark inside it: the network ends at the walls.
    "lan": ('<path d="M4.5 15 L16 5.5 L27.5 15"/>'
            '<path d="M8 12.5 V27 H24 V12.5"/>'
            '<path d="M16 24 H16.01"/>'
            '<path d="M13.53 21.53 A3.5 3.5 0 0 1 18.47 21.53"/>'
            '<path d="M11.4 19.4 A6.5 6.5 0 0 1 20.6 19.4"/>'),
    # A page of rules with a pen on it.
    "rules": ('<path d="M5 3 H18 L23 8 V29 H5 Z"/>'
              '<path class="d" d="M18 3 V8 H23"/>'
              '<path class="d" d="M8.5 12 H19 M8.5 16 H19 M8.5 20 H14"/>'
              '<path class="pn" d="M16 25 L25.5 15.5 L28.5 18.5 L19 28 Z"/>'
              '<path d="M16 25 L14.5 29.5 L19 28"/>'),
    # A listing: a heading rule and three rows, each with its marker.
    "list": ('<rect x="4" y="5" width="24" height="22" rx="1.5"/>'
             '<path d="M4 10 H28"/>'
             '<path d="M8 14.5 H9.5 M8 19 H9.5 M8 23.5 H9.5"/>'
             '<path class="d" d="M13 14.5 H24 M13 19 H24 M13 23.5 H20"/>'),
}


def _ticker_frame():
    """The panel's line work, in a 256 x 90 viewBox, which is the panel's own
    16rem x 5.625rem at 16 units to the rem. So a coordinate here and a
    position in the stylesheet are the same number over 16, and the icon
    sits inside its brackets without anybody measuring a render."""
    ticks = " ".join(f"M{x} 80.5 V{74 if (x - 68) % 32 == 0 else 77.5}"
                     for x in range(68, 237, 8))
    segs = "".join(f'<rect class="sg sg{i + 1}" x="{180 + 7 * i}" y="8" '
                   'width="5" height="6"/>' for i in range(len(FREEDOMS)))
    return (
        '<svg class="tf" viewBox="0 0 256 90" aria-hidden="true" '
        'focusable="false">'
        # Faint outline, cut across two corners, and the same cut picked out
        # brighter where the eye lands first and last.
        '<path class="fr" d="M10.5 0.5 H255.5 V79.5 L245.5 89.5 H0.5 V10.5 Z"/>'
        '<path class="ac" d="M0.5 26 V10.5 L10.5 0.5 H42"/>'
        '<path class="ac" d="M255.5 64 V79.5 L245.5 89.5 H214"/>'
        '<rect class="nt" x="6" y="6.5" width="2.5" height="9"/>'
        # One segment per freedom, lit for the one showing.
        + segs +
        # Brackets round the icon, and the line that sweeps down inside them.
        '<path class="dm" d="M13.5 34 V27.5 H20 M52 27.5 H58.5 V34'
        ' M58.5 66 V72.5 H52 M20 72.5 H13.5 V66"/>'
        '<path class="sc" d="M15 30 H57"/>'
        # A scale under the words, and a caret that crosses it once for each
        # freedom: the time until the next one.
        f'<path class="dm" d="M68 80.5 H236 {ticks}"/>'
        '<path class="ct" d="M68 82 L65 86.5 H71 Z"/>'
        "</svg>")


TICKER_FRAME = _ticker_frame()


def ticker_html(start=0):
    """The freedoms panel, with the list starting at freedom number start.
    The visual list and the one a screen reader gets are the same list: see
    the note above FREEDOMS."""
    start %= len(FREEDOMS)
    order = FREEDOMS[start:] + FREEDOMS[:start]
    items = "".join(
        '<li><svg class="ti" viewBox="0 0 32 32" aria-hidden="true" '
        f'focusable="false">{TICKER_ICONS[key]}</svg>'
        f"<span><b>{label}</b> <i>{note}</i></span></li>"
        for key, label, note in order)
    return ('<div class="ticker">' + TICKER_FRAME
            + '<p class="th" aria-hidden="true">Electronic freedom</p>'
            + '<ul aria-label="Electronic freedom">' + items + "</ul></div>")


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

# The avatar: the wordmark in the site's line art, inside a circle, made by
# brand/make_avatar.py from LOGO_ROWS and this file's palette. It is what a
# link preview shows (og:image, twitter:image) and what a phone puts on its
# home screen (apple-touch-icon). Everything that matters sits inside the
# circle, so the round crops those places make lose nothing.
#
# Its own routes and its own folder, for the favicon's reason: gallery_html()
# shows every image in static/, and a logo does not belong in that gallery.
# og:image has to be an absolute address, and it is the board list's,
# because that is the face a shared link most often points at; the route
# answers on every face anyway.
BRAND_DIR = pathlib.Path(__file__).resolve().parent / "brand"


def _brand(name):
    try:
        return (BRAND_DIR / name).read_bytes()
    except OSError:
        return None


AVATAR_PNG = _brand("unleashed-avatar-1024.png")

# The cover, made by brand/make_cover.py. It is laid out for Buy Me a
# Coffee, which cuts off the top and lays its own cards over the lower
# half, so the content sits in a band near the top and the bottom is empty
# on purpose. On this site the empty half would be a black stripe, so the
# drawing is cut to the band and its frame redrawn to fit: the viewBox ends
# at 310 and the frame's bottom edge moves up with it. Done by replacing
# the frame and the size exactly; if make_cover.py ever draws them
# differently the replace finds nothing and the whole cover is served
# rather than a broken one, and selftest.py fails on the height.
COVER_H = 310


def _cover(svg):
    if svg is None:
        return None
    frame = '<path d="M18,8 H1592 V382 L1582,392 H8 V18 Z"'
    size = 'height="400" viewBox="0 0 1600 400"'
    if frame not in svg or size not in svg:
        return svg
    return (svg.replace(frame, f'<path d="M18,8 H1592 V{COVER_H - 18} '
                               f'L1582,{COVER_H - 8} H8 V18 Z"', 1)
               .replace(size, f'height="{COVER_H}" viewBox="0 0 1600 {COVER_H}"', 1))


_cover_raw = _brand("unleashed-cover.svg")
COVER_SVG = _cover(_cover_raw.decode("utf-8")) if _cover_raw else None
TOUCH_PNG = _brand("unleashed-avatar-512.png")
AVATAR_URL = ((f"https://{LIST_DOMAIN}" if LIST_DOMAIN else SITE_URL).rstrip("/")
              + "/avatar.png")
PAGE = PAGE.replace("@AVATAR_URL@", html.escape(AVATAR_URL, quote=True))


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
FEATURES   = ("chat", "forums", "files", "mail", "doors")
NEW_DAYS   = 7
# The SD card's size, in GB, as the board sends it (site 1.1.0, firmware
# 1.1.0): a whole number, already rounded by the board up to the size
# printed on the card, so a "32 GB" card that reports 29.7 arrives as 32.
# Anything outside 1 to SD_MAX is ignored rather than refused.
SD_MAX     = 4096

# The small badges, in the order they appear: key, letters, colour class,
# name, and what it means, which the tooltip says after the name. The first
# eight are sent by the board and the last two are worked out here. The SD
# card's letters here are what the legend and the filter show; on a board's
# row the badge carries the size as well, "SD32".
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
    ("sd",      "SD", "feat",   "SD card",
     "an SD card is in use on the board. On a board's row the badge carries "
     "the card's size in GB, as printed on the card: SD32 is a 32 GB card."),
    ("new",     "N",  "new",    "New",    "listed here for less than a week."),
    ("steady",  "S",  "steady", "Steady",
     "answered more than 95% of the heartbeats it was due over the last seven days."),
)

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
    add("board", "software", "Software", "soft", "unleashed 1.0.0",
        "What the board runs, and which version of it.",
        "<code>software</code> <span class='src'>and <code>version</code></span>",
        tip="Software: unleashed 1.0.0, as the board reports it.", filt=False)
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
                tip=f"{name}: {means}")
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
# 1.1.0) sits with what is running, after doors.
ROW_ORDER = ("petscii", "guests", "chat", "mail", "forums", "files", "doors",
             "sd", "new", "steady")
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


# --------------------------------------------------------------------------
# Versions (site 1.0.0). A board's software badge says which version it
# runs, and a µnleashed board behind the newest release /install offers
# carries an arrow saying so.
# --------------------------------------------------------------------------
_VERSION = re.compile(r"^v?(\d{1,6})\.(\d{1,6})\.(\d{1,6})(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$")


def version_key(text):
    """A version as something to compare, or None when it is not one.

    Three numbers, compared part by part, so 1.0.10 is newer than 1.0.9. A
    pre-release (1.0.1-rc.1) is older than the release it leads to, and
    build metadata after a "+" does not count. Anything else, "1.0", "dev"
    or nothing at all, is not a version, and a board sending it is never
    told it is behind: a guess that nags somebody wrongly is worse than no
    arrow."""
    m = _VERSION.match((text or "").strip())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), 0 if m.group(4) else 1)


def newest_release():
    """The version /install offers first, found the way /install finds it,
    or "" when nothing is published."""
    rels = firmware_releases()
    return rels[0]["version"] if rels else ""


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
    return (f'<a class="bu" href="/upgrade" aria-label="{t}" data-tip="{t}">'
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
        what = r["software"] + (" " + r["version"] if r["version"] else "")
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
            ' placeholder="c64, radio, chat">'
            '<span class="fqn" id="bqn" aria-live="polite"></span></p>'
            + BADGE_JS)


TERMINAL_NAMES = {"ansi": "ANSI", "utf8": "UTF-8", "petscii": "PETSCII",
                  "ascii": "ASCII", "vt100": "VT100"}


def about_lines(r):
    """What a board sent about itself, as plain lines of words, for the feed,
    which has no badges and no tooltips. Plain text: the caller escapes."""
    lines = []
    if r["software"]:
        lines.append("Software: " + r["software"]
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
                "[Install it from your browser.](/install)")


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
# The board list's figures, as one sentence under its heading.
#
# "Unleashed is hosting 3 boards with 5 callers on right now." The boards
# are every listed board, up or quiet, the same count as the page's
# description; the callers are the sum of the callers-on figure the table
# shows for each board that is up. Nothing here reaches the JSON or the
# feed, which keep their own figures.
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
        return '<p class="stat">Unleashed is hosting no boards yet.</p>'
    b = (f"<span class='n'>{boards:,}</span> "
         f"board{'' if boards == 1 else 's'}")
    c = ("no callers" if not callers else
         f"<span class='n'>{callers:,}</span> "
         f"caller{'' if callers == 1 else 's'}")
    return (f'<p class="stat">Unleashed is hosting {b} with {c} on right now'
            + html.escape(STAT_SUFFIX) + ".</p>")


# The way to a board of your own, as a small card beside the heading rather
# than a pair of full size buttons across the page. The board list is the
# product; this is the side door for the few who came to build one. The
# buttons say where they go, and neither says Install: only the button on
# /install does, because only that one installs.
RUN_CARD = ('<aside class="runcard" aria-labelledby="run-your-own">'
            '<h2 id="run-your-own">Run your own board</h2>'
            '<p class="say">An ESP32, a USB cable, five minutes.</p>'
            '<p class="acts"><a class="fill" href="/install">Web installer</a>'
            '<a class="line" href="/build#getting-it-running">Build from source</a>'
            "</p>"
            # The two lamps that go round its edge, half a lap apart, each a
            # head and three beads of tail (site 0.22.0, from the UX spec:
            # three lamps a third of a lap apart looked scattered, because a
            # rectangle has no three-fold symmetry, and two half a lap apart
            # are always a pair through its centre). Decoration, so hidden
            # from a screen reader, and after the words so they come first.
            + "".join(f'<span class="dot {lamp}{bead}" aria-hidden="true"></span>'
                      for lamp in ("la", "lb")
                      for bead in ("", " t1", " t2", " t3"))
            + "</aside>")


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


def filter_bar_html(sel, any_, shown, total):
    """The Filter button, its pane, the line saying what is chosen, and the
    key to the badges, for the top of the board list."""
    chosen = set(sel)
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
            '<form class="fpane" id="fform" method="get" action="/"'
            ' aria-label="Filter the boards by badge">'
            '<div class="ftop">'
            '<p class="findbar" data-js hidden><label for="fq">Find a badge</label>'
            '<input type="search" id="fq" data-find="#fgrid" data-count="fqn"'
            ' data-noun="badges" autocomplete="off" spellcheck="false"'
            ' placeholder="c64, radio, chat">'
            '<span class="fqn" id="fqn" aria-live="polite"></span></p>'
            '<fieldset class="fmode"><legend>Boards with</legend>' + radios
            + "</fieldset></div>"
            '<div class="frows" id="fgrid">' + "".join(groups) + "</div>"
            '<p class="fgo"><button type="submit">Show boards</button>'
            '<a href="/" data-clear>Clear all</a></p>'
            "</form></details>"
            '<p class="keylink"><a href="/badges">What the badges mean</a></p>'
            f'<p class="factive" id="factive" aria-live="polite"{"" if sel else " hidden"}>'
            f'<span data-f="n">{shown} of {total} board{plural}</span> with '
            f'<span data-f="m">{mode} of</span>: '
            f'<span data-f="l">{html.escape(names)}</span>. '
            '<a href="/" data-clear>Clear</a></p>'
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
            "ORDER BY state='online' DESC, "
            "COALESCE(minutes24, busy * 60, 0) DESC, streak_start ASC").fetchall()
        charts = {}
        for r in rows:
            hours = hours_for(con, r["id"])
            if hours:
                charts[r["id"]] = chart_html(hours)
        steady = steady_boards(con, rows, now)
    return now, rows, charts, steady


def index_page(sel=(), any_=False, data=None):
    """The board list. sel is the badges chosen in the filter, any_ whether
    one of them is enough; with none chosen it is the whole list, which is
    the page almost everybody gets and the one that is cached whole."""
    now, rows, charts, steady = data or index_data()
    live = [r for r in rows if r["state"] == "online"]
    # The same figure each row's state shows as "N of M on", summed.
    on = sum(r["busy"] or 0 for r in live)

    # The announcement, when there is one, sits above everything else the
    # page says; then the heading, its figures and the lead, with the small
    # "Run your own board" card beside them; then the list, which is still
    # the first big thing on the screen at every width.
    head = (head_html("list", "/")
            + announcement_banner()
            + '<div class="listtop"><div class="intro">'
            + "<h1>BBS directory</h1>"
            + stat_line(len(rows), on)
            + '<p class="lead">Boards that are up right now. '
            'Dial one with <a href="/terminals">any telnet client</a>, or click '
            'an address if you have one installed. '
            '<a href="/dialing">Nothing happened?</a> '
            '<a href="/firstcall">Never called one before?</a></p></div>'
            + RUN_CARD + "</div>")
    if rows:
        # The filter and the key to the badges, small and right above the
        # table, where somebody wondering what "Fi" means is already
        # looking. Not in the table's header row, which a phone does not
        # show. When nothing passes the filter the table is hidden and a
        # sentence says so, rather than a header over nothing.
        latest = newest_release()
        shown = sum(1 for r in rows
                    if board_matches(row_keys(r, now, r["id"] in steady, latest), sel, any_))
        body = (filter_bar_html(sel, any_, shown, len(rows))
                + '<table id="boards"' + ("" if shown else " hidden") + ">"
                "<tr><th>Board</th><th>Dial</th><th>State</th></tr>"
                + board_rows(rows, now, charts, steady, sel, any_, latest) + "</table>"
                + '<p class="none" id="fnone"' + (" hidden" if shown else "") + ">"
                + f"No board with {'any' if any_ else 'all'} of those yet.</p>"
                + BADGE_JS)
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
has and how many are busy, whether it is up, and how long it has been up. Then what
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
<p class="lead">Your board announces itself. You do not fill in a form.</p>
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
</article>"""


# ----------------------------------------------------------------------
# The two diagrams on the manifesto, drawn rather than typed.
#
# Both used to be ASCII art in a <pre>. That is the right idiom for a
# terminal and the wrong one for a web page: the art is laid out in
# character cells, so its size is a font size, every font renders it a few
# percent differently, and the only way to make 61 columns fit a 358px
# phone column was to shrink the type until the letters were 6px. The
# connection diagram was eight whole copies of itself flipped 0.4s apart,
# which is a flipbook, and the comparison was a 53 column block that
# scrolled sideways inside its own box.
#
# Inline SVG instead. No request and no external file (there is no CSP on
# this site to block one: that used to be claimed here and was never true,
# which /author's hotlinked photographs depend on), themeable because every fill is a custom
# property, and it fits any width for free because that is what a viewBox
# does. Still no JavaScript: the motion is CSS keyframes on an SVG
# element, where a length in `px` is a user unit inside the viewBox and
# not a layout length.
#
# THE VIEWBOX IS 344 UNITS WIDE FOR BOTH, and that is the one number worth
# defending. A phone column here is about 353px, so a 344 unit box lands
# at 1.03:1 and an 11.5px label renders at 11.8px. Anything wider is a
# diagram that reads on a monitor and not on a phone, which is exactly
# what the ASCII versions were. The max-widths below then stop the same
# art being blown up to twice size on a 1920 monitor: 26rem puts the panel
# text at 18.5px against an 18.6px body, which is the size it should have
# been all along.
#
# Every shape carries an explicit fill, including `fill:none` on the
# lines, because an SVG shape with no fill declared is black, and black on
# #0d0d12 is a shape nobody can see.
# ----------------------------------------------------------------------

DIAGRAM_CSS = """
<style>
/* ---- the connection, at the top of the page ---------------------- */
svg.wire { display:block; width:100%; max-width:28rem; height:auto;
        margin:1.125rem auto 1.5rem; background:#0d0d12;
        border:1px solid var(--rule); }
svg.wire text { font-family:inherit; fill:var(--dim); font-size:11px; }
svg.wire text.end { fill:var(--ink); font-size:12px; letter-spacing:1.2px; }
svg.wire text.cap { fill:var(--faint); font-size:10.5px; }
svg.wire text.prompt { fill:var(--live); font-size:12px; }
svg.wire text.chip { fill:var(--faint); font-size:10px; letter-spacing:1px; }
svg.wire .case { fill:none; stroke:var(--dial); stroke-width:1.4; }
svg.wire .glass { fill:var(--bg); stroke:var(--dial); stroke-width:1; }
svg.wire .keys { fill:var(--dial); opacity:0.3; }
svg.wire .caret { fill:var(--live); }
svg.wire .line { fill:none; stroke:var(--live); stroke-width:1.4;
        stroke-dasharray:3 5; opacity:0.45; }
svg.wire .body { fill:var(--bg); stroke:var(--live); stroke-width:1.4; }
svg.wire .pin { fill:var(--live); opacity:0.55; }
svg.wire .pin1 { fill:var(--live); opacity:0.45; }
svg.wire .led { fill:var(--live); }
svg.wire .dot { fill:var(--live); }
svg.wire .halo { fill:var(--live); opacity:0.18; }
/* The marker crosses the 164 units of wire in 3.2s and `alternate` brings
   it back, so a round trip is 6.4s and the chip's lamp lights at the half
   way mark, which is the instant the marker is standing on it. Three
   animations rather than one, because a drawing of a live connection
   should look live: the terminal's caret blinks, the marker travels, the
   chip answers. */
@keyframes wiretrip { from { transform:translateX(0); }
                      to   { transform:translateX(164px); } }
@keyframes wireled  { 0%, 44%  { opacity:0.25; }
                      50%      { opacity:1; }
                      56%, 100%{ opacity:0.25; } }
@keyframes wirecaret{ 0%, 49%  { opacity:1; }
                      50%, 100%{ opacity:0; } }
svg.wire .pulse { animation:wiretrip 3.2s ease-in-out infinite alternate; }
svg.wire .led   { animation:wireled 6.4s ease-in-out infinite; }
svg.wire .caret { animation:wirecaret 1.6s steps(1,end) infinite; }
/* The resting state has to make the point on its own, because it is also
   what a screenshot and a printout get: the marker parks half way along
   the wire, the lamp is lit, the caret is solid. Nothing is hidden and
   nothing moves. */
@media (prefers-reduced-motion: reduce) {
  svg.wire .pulse, svg.wire .led, svg.wire .caret { animation:none; }
  svg.wire .pulse { transform:translateX(82px); }
  svg.wire .led, svg.wire .caret { opacity:1; }
}

/* ---- the two traces, side by side -------------------------------- */
/* The site's one breakpoint, and the same shape as .freedoms further
   down. align-items:start is the argument rather than a detail: the two
   panels are not the same height and must not be stretched to look as
   though they are. The left one is tall because four parties keep a
   record; the right one is short because one does. */
.compare { display:grid; grid-template-columns:repeat(2, minmax(0, 26rem));
        justify-content:center; gap:1.125rem 1.5rem; align-items:start;
        margin:1.25rem 0 1.5rem; }
@media (max-width: 900px) { .compare { grid-template-columns:1fr; } }
svg.trace { display:block; width:100%; max-width:26rem; height:auto;
        margin:0 auto; background:#0d0d12; border:1px solid var(--rule); }
svg.trace text { font-family:inherit; fill:var(--ink); font-size:11.5px; }
svg.trace text.title { font-size:12px; letter-spacing:1.4px; }
svg.trace text.kept { font-size:11px; }
svg.trace text.pool { font-size:10.5px; }
svg.trace text.verdict { font-size:11.5px; letter-spacing:0.6px; }
svg.trace .node { fill:#12121a; stroke:var(--faint); stroke-width:1; }
svg.trace .link { fill:none; stroke:var(--faint); stroke-width:1; }
svg.trace .head { fill:var(--faint); stroke:none; }
svg.trace .keep, svg.trace .pool-box { fill:#12121a; stroke:var(--faint);
        stroke-width:1; }
svg.trace .bus { fill:none; stroke:var(--faint); stroke-width:1; opacity:0.75; }
svg.trace .bhead { fill:var(--faint); stroke:none; }
/* Red for a party that keeps a copy of you, green for one that does not.
   Both come from the palette at the root rather than being typed in here,
   so the diagram cannot drift away from the rest of the site. */
svg.trace.bad text.title, svg.trace.bad text.kept,
svg.trace.bad text.pool, svg.trace.bad text.verdict { fill:var(--risk); }
svg.trace.bad .keep, svg.trace.bad .pool-box { stroke:var(--risk); }
svg.trace.bad .bus { stroke:var(--risk); }
svg.trace.bad .bhead { fill:var(--risk); }
svg.trace.good text.title, svg.trace.good text.kept,
svg.trace.good text.verdict { fill:var(--live); }
svg.trace.good .keep { stroke:var(--live); }
svg.trace.good .bus { stroke:var(--live); }
svg.trace.good .bhead { fill:var(--live); }
</style>"""


# role="img" makes the whole drawing one object to a screen reader, so the
# labels inside it are never announced and the aria-label has to carry the
# entire argument by itself. "A diagram" would be worse than nothing: the
# point of the pair below is a list of parties who keep a record against a
# list of one, so that is what it says. They are built here rather than
# typed into the markup so the source can wrap and the attribute cannot.
WIRE_ALT = (
    "One connection, with nothing in between. On the left, any terminal, "
    "anywhere. On the right, a chip on a shelf. A single marker travels the "
    "wire from one to the other and back again, and there is no third party "
    "on the line for it to pass through.")

BAD_ALT = (
    "Calling a website. Five parties handle the request in turn: you, DNS, a "
    "CDN, a load balancer, and the application. Four of them keep a record - "
    "who asked and when, edge logs of your IP address, a session fingerprint, "
    "and your account history - and all four records flow on into analytics, "
    "an ad exchange, a data broker, model training, a retention policy, and a "
    "breach disclosure in eighteen months. You cannot audit any of it.")

GOOD_ALT = (
    "Calling a board. Three parties handle the request: you, your router, and "
    "a chip you own. One record is kept, a text file you can open and read. "
    "That is the entire list.")


WIRE = """
<svg class="wire" viewBox="-5 -6 354 138" role="img"
     preserveAspectRatio="xMidYMid meet" aria-label=\"""" + WIRE_ALT + """">
  <text class="end" x="6" y="15">YOU</text>
  <text class="end" x="338" y="15" text-anchor="end">THE BOARD</text>

  <rect class="case" x="10" y="31" width="80" height="58" rx="5"/>
  <rect class="glass" x="16" y="37" width="68" height="36" rx="2"/>
  <text class="prompt" x="23" y="59">&gt;</text>
  <rect class="caret" x="33" y="50" width="7" height="11"/>
  <rect class="keys" x="16" y="78" width="68" height="5" rx="2"/>
  <path class="case" d="M40 89 L36 99 H64 L60 89 Z"/>
  <rect class="case" x="30" y="99" width="40" height="4" rx="2"/>

  <line class="line" x1="90" y1="60" x2="254" y2="60"/>

  <rect class="pin" x="254" y="42" width="8" height="4" rx="1"/>
  <rect class="pin" x="254" y="58" width="8" height="4" rx="1"/>
  <rect class="pin" x="254" y="74" width="8" height="4" rx="1"/>
  <rect class="body" x="262" y="34" width="58" height="52" rx="4"/>
  <rect class="pin" x="320" y="42" width="8" height="4" rx="1"/>
  <rect class="pin" x="320" y="58" width="8" height="4" rx="1"/>
  <rect class="pin" x="320" y="74" width="8" height="4" rx="1"/>
  <circle class="pin1" cx="269" cy="42" r="2.5"/>
  <text class="chip" x="291" y="57" text-anchor="middle">BBS</text>
  <circle class="led" cx="291" cy="71" r="3.5"/>

  <g class="pulse">
    <circle class="halo" cx="90" cy="60" r="7"/>
    <circle class="dot" cx="90" cy="60" r="3.2"/>
  </g>

  <text class="cap" x="6" y="118">any terminal, anywhere</text>
  <text class="cap" x="338" y="118" text-anchor="end">a chip on a shelf</text>
</svg>"""


# Two panels rather than one drawing, because a single SVG cannot reflow:
# a viewBox scales, it does not lay out again. Two of them in a grid stack
# on a phone and sit side by side on a monitor, which is the only way this
# is readable at 390px without dragging it sideways.
TRACE = """
<div class="compare">
<svg class="trace bad" viewBox="-6 -8 356 382" role="img"
     preserveAspectRatio="xMidYMid meet" aria-label=\"""" + BAD_ALT + """">
  <text class="title" x="4" y="16">CALLING A WEBSITE</text>

  <rect class="node" x="4" y="32" width="124" height="26" rx="3"/>
  <text x="14" y="49">you</text>
  <path class="link" d="M66 58 V71"/>
  <polygon class="head" points="62.5,71 69.5,71 66,76"/>

  <rect class="node" x="4" y="76" width="124" height="26" rx="3"/>
  <text x="14" y="93">DNS</text>
  <path class="link" d="M66 102 V115"/>
  <polygon class="head" points="62.5,115 69.5,115 66,120"/>
  <path class="link" d="M128 89 H145"/>
  <polygon class="head" points="145,85.5 145,92.5 150,89"/>
  <rect class="keep" x="152" y="76" width="176" height="26" rx="3"/>
  <text class="kept" x="161" y="93">who asked, and when</text>

  <rect class="node" x="4" y="120" width="124" height="26" rx="3"/>
  <text x="14" y="137">CDN</text>
  <path class="link" d="M66 146 V159"/>
  <polygon class="head" points="62.5,159 69.5,159 66,164"/>
  <path class="link" d="M128 133 H145"/>
  <polygon class="head" points="145,129.5 145,136.5 150,133"/>
  <rect class="keep" x="152" y="120" width="176" height="26" rx="3"/>
  <text class="kept" x="161" y="137">edge logs your IP</text>

  <rect class="node" x="4" y="164" width="124" height="26" rx="3"/>
  <text x="14" y="181">load balancer</text>
  <path class="link" d="M66 190 V203"/>
  <polygon class="head" points="62.5,203 69.5,203 66,208"/>
  <path class="link" d="M128 177 H145"/>
  <polygon class="head" points="145,173.5 145,180.5 150,177"/>
  <rect class="keep" x="152" y="164" width="176" height="26" rx="3"/>
  <text class="kept" x="161" y="181">session fingerprint</text>

  <rect class="node" x="4" y="208" width="124" height="26" rx="3"/>
  <text x="14" y="225">the app</text>
  <path class="link" d="M128 221 H145"/>
  <polygon class="head" points="145,217.5 145,224.5 150,221"/>
  <rect class="keep" x="152" y="208" width="176" height="26" rx="3"/>
  <text class="kept" x="161" y="225">account history</text>

  <path class="bus" d="M328 89 H336 V244 H172 V247"/>
  <path class="bus" d="M328 133 H336"/>
  <path class="bus" d="M328 177 H336"/>
  <path class="bus" d="M328 221 H336"/>
  <polygon class="bhead" points="168.5,247 175.5,247 172,253"/>

  <rect class="pool-box" x="4" y="254" width="336" height="62" rx="3"/>
  <text class="pool" x="172" y="274" text-anchor="middle">analytics \u00b7 ad exchange \u00b7 data broker</text>
  <text class="pool" x="172" y="290" text-anchor="middle">model training \u00b7 retention policy</text>
  <text class="pool" x="172" y="306" text-anchor="middle">breach disclosure in eighteen months</text>

  <path class="bus" d="M172 316 V330"/>
  <polygon class="bhead" points="168.5,330 175.5,330 172,336"/>
  <text class="verdict" x="172" y="352" text-anchor="middle">you cannot audit any of it</text>
</svg>

<svg class="trace good" viewBox="-6 -8 356 216" role="img"
     preserveAspectRatio="xMidYMid meet" aria-label=\"""" + GOOD_ALT + """">
  <text class="title" x="4" y="16">CALLING A BOARD</text>

  <rect class="node" x="4" y="32" width="124" height="26" rx="3"/>
  <text x="14" y="49">you</text>
  <path class="link" d="M66 58 V71"/>
  <polygon class="head" points="62.5,71 69.5,71 66,76"/>

  <rect class="node" x="4" y="76" width="124" height="26" rx="3"/>
  <text x="14" y="93">your router</text>
  <path class="link" d="M66 102 V115"/>
  <polygon class="head" points="62.5,115 69.5,115 66,120"/>

  <rect class="node" x="4" y="120" width="124" height="26" rx="3"/>
  <text x="14" y="137">a chip you own</text>
  <path class="bus" d="M128 133 H145"/>
  <polygon class="bhead" points="145,129.5 145,136.5 150,133"/>
  <rect class="keep" x="152" y="114" width="176" height="38" rx="3"/>
  <text class="kept" x="161" y="130">a text file you</text>
  <text class="kept" x="161" y="145">can open and read</text>

  <text class="verdict" x="172" y="184" text-anchor="middle">that is the entire list</text>
</svg>
</div>"""


# ----------------------------------------------------------------------
# The small drawings: one per freedom on the manifesto, the three screens
# on /firstcall, and the skull on /how.
#
# Drawn by the same rules as WIRE above, so they read as one hand: an
# object is a --dial outline at stroke 1.4 with details at 1, anything
# alive (a lamp, a caret, data moving) is --live, anything absent or
# secondary is --faint, and every shape declares its fill. The tile they
# sit on is the same #0d0d12 panel with a hairline border.
#
# An icon's viewBox is 56 units and it is drawn at 4.25rem, which on a
# desktop is 90px: a scale of 1.6, against the 1.68 the connection diagram
# is drawn at, so a 1.4 stroke lands at the same weight in both.
#
# THE RESTING STATE IS THE DRAWING. Every animation is declared inside
# prefers-reduced-motion: no-preference and nowhere else, so somebody who
# has asked for less motion gets no animation at all, and what they see is
# the markup exactly as written. Each drawing is therefore made to say its
# whole piece standing still: the gate is up, the lamp is lit, the caret is
# solid, the calendar reads 365. The motion only adds the verb.
#
# No px anywhere in here. Motion is opacity, rotation and skew about the
# shape's own box (transform-box: fill-box), translation, and dash offsets
# against a pathLength, and type sizes are attributes on the <text>. The
# two translate distances are user units inside a viewBox, which is why the
# suite's px scan exempts translateX and translateY.
# ----------------------------------------------------------------------

ART_CSS = """
<style>
svg.art { display:block; background:#0d0d12; border:1px solid var(--rule); }
svg.art text { font-family:inherit; fill:var(--dim); }
svg.art text.ink { fill:var(--ink); }
svg.art text.live { fill:var(--live); }
svg.art .o { fill:none; stroke:var(--dial); stroke-width:1.4;
        stroke-linecap:round; stroke-linejoin:round; }
svg.art .d { fill:none; stroke:var(--dial); stroke-width:1;
        stroke-linecap:round; stroke-linejoin:round; opacity:0.6; }
svg.art .g { fill:var(--bg); stroke:var(--dial); stroke-width:1; }
svg.art .gb { fill:var(--bg); stroke:var(--dial); stroke-width:1.4;
        stroke-linejoin:round; }
svg.art .k { fill:var(--dial); opacity:0.3; }
svg.art .l { fill:none; stroke:var(--live); stroke-width:1.4;
        stroke-linecap:round; stroke-linejoin:round; }
svg.art .lt { fill:none; stroke:var(--live); stroke-width:1.2;
        stroke-linecap:round; }
svg.art .lw { fill:none; stroke:var(--live); stroke-width:2.4;
        stroke-linecap:round; }
svg.art .ld { fill:none; stroke:var(--live); stroke-width:1.4;
        stroke-dasharray:2 2.5; opacity:0.5; }
svg.art .lf { fill:var(--live); }
svg.art .halo { fill:var(--live); opacity:0.18; }
svg.art .body { fill:var(--bg); stroke:var(--live); stroke-width:1.4; }
svg.art .pin { fill:var(--live); opacity:0.55; }
svg.art .f { fill:none; stroke:var(--faint); stroke-width:1;
        stroke-linecap:round; stroke-linejoin:round; }
svg.art .c1 { fill:var(--dial); }
svg.art .c2 { fill:var(--live); }
svg.art .c3 { fill:var(--busy); }
svg.art .c4 { fill:var(--name); }
svg.art .c5 { fill:var(--warm); }
svg.art text.warm { fill:var(--warm); }
svg.art text.busy { fill:var(--busy); }
svg.art .timer { stroke-dasharray:30 30; }
/* The calendar's first two readings are hidden at rest, so a still
   drawing reads 365: a year has passed and the lamp is still lit. */
svg.art .n1, svg.art .n2 { opacity:0; }

/* One per freedom, top right of its box, the text wrapping round it. On
   a phone the box is a third the width and a full-size icon squeezes the
   heading beside it to a dozen characters a line, so it is drawn smaller
   there, at the site's one breakpoint. */
article .freedom svg.icon { float:right; width:4.25rem; height:4.25rem;
        margin:0.125rem 0 0.5rem 1rem; }
@media (max-width: 900px) {
  article .freedom svg.icon { width:3.25rem; height:3.25rem;
        margin:0 0 0.375rem 0.75rem; }
}

/* The first call, three screens in a row. 354 units wide for the same
   reason the connection diagram is: a phone column is about 353px, so a
   phone draws it at 1:1 and the smallest type lands at about 9px. */
svg.art.steps { width:100%; max-width:34rem; height:auto;
        margin:1.125rem auto 1.5rem; }
/* The boards (site 1.2.0): 96 x 60 units, shown at about 1:1 in the
   install card's picker and at twice that on /hardware, which is the scale
   the step drawings reach on a desktop, so the lines are the same weight. */
svg.art.board { flex:none; width:4.5rem; height:2.8125rem; margin:0; }
svg.art.board.big { width:9rem; height:5.625rem; }

/* The machines on /terminals, one strip under each heading. Narrower
   than the first call strip, because there are eight of them on one page
   and each has only to say which machine the section is about. */
svg.art.machines { width:100%; max-width:24rem; height:auto;
        margin:0.75rem auto 1.125rem; }
svg.art text.dial { fill:var(--dial); }

/* The SD card wiring diagram on /sdcard. Each wire's colour is its wire,
   its two pins, its three labels and its pulse, so a reader can follow one
   colour from end to end. Ground is --faint and power --busy; the data
   lines take four palette colours and never --risk. */
svg.art.wiring { width:100%; max-width:30rem; height:auto;
        margin:1rem auto 1.25rem; }
svg.art .ww { fill:none; stroke-width:2.2; stroke-linecap:round; }
svg.art .s-gnd { stroke:var(--faint); }
svg.art .s-pwr { stroke:var(--busy); }
svg.art .s-miso { stroke:var(--live); }
svg.art .s-mosi { stroke:var(--dial); }
svg.art .s-sck { stroke:var(--warm); }
svg.art .s-cs { stroke:var(--name); }
svg.art .f-gnd { fill:var(--dim); }
svg.art .f-pwr { fill:var(--busy); }
svg.art .f-miso { fill:var(--live); }
svg.art .f-mosi { fill:var(--dial); }
svg.art .f-sck { fill:var(--warm); }
svg.art .f-cs { fill:var(--name); }

/* The skull is drawn in the warning box's own amber, on its background,
   so it belongs to the box it sits in rather than to the page. */
svg.art.skull { background:none; border:0; }
svg.art .a { fill:none; stroke:#f0c674; stroke-width:1.4;
        stroke-linecap:round; stroke-linejoin:round; }
svg.art .af { fill:#241d10; stroke:#f0c674; stroke-width:1.4;
        stroke-linejoin:round; }
svg.art .aff { fill:#f0c674; }

@keyframes artpass  { 0% { transform:translateX(-11px); opacity:0; }
                      15%, 85% { opacity:1; }
                      100% { transform:translateX(11px); opacity:0; } }
@keyframes artwest  { 0% { transform:translateX(-3.5px); opacity:0; }
                      20%, 80% { opacity:1; }
                      100% { transform:translateX(3.5px); opacity:0; } }
@keyframes arteast  { 0% { transform:translateX(3.5px); opacity:0; }
                      20%, 80% { opacity:1; }
                      100% { transform:translateX(-3.5px); opacity:0; } }
@keyframes artfeed  { 0% { transform:translateX(-7px); opacity:0; }
                      15%, 85% { opacity:1; }
                      100% { transform:translateX(7px); opacity:0; } }
@keyframes artpulse { 0%, 100% { opacity:0.35; } 50% { opacity:1; } }
@keyframes artglow  { 0%, 100% { opacity:0.15; } 50% { opacity:1; } }
@keyframes artwave  { from { transform:skewY(0deg) scaleX(1); }
                      to   { transform:skewY(-6deg) scaleX(0.93); } }
@keyframes artwrite { 0% { stroke-dashoffset:10; opacity:1; }
                      12% { stroke-dashoffset:0; }
                      80% { stroke-dashoffset:0; opacity:1; }
                      92%, 100% { stroke-dashoffset:0; opacity:0; } }
@keyframes artsay   { 0%, 100% { opacity:0.3; } 20%, 50% { opacity:1; } }
@keyframes artcaret { 0%, 49% { opacity:1; } 50%, 100% { opacity:0; } }
@keyframes artfall  { 0% { transform:translateY(-3px); opacity:0; }
                      20%, 80% { opacity:1; }
                      100% { transform:translateY(5px); opacity:0; } }
@keyframes artscan  { from { transform:translateY(-9px); }
                      to   { transform:translateY(9px); } }
@keyframes artday   { 0% { opacity:0; } 5%, 30% { opacity:1; }
                      35%, 100% { opacity:0; } }
@keyframes artring  { 0% { opacity:0; } 10%, 55% { opacity:1; }
                      70%, 100% { opacity:0; } }
@keyframes artshow  { 0% { opacity:0; } 8%, 85% { opacity:1; }
                      95%, 100% { opacity:0; } }
@keyframes artserial { 0% { transform:translateX(-26px); opacity:0; }
                      15%, 85% { opacity:1; }
                      100% { transform:translateX(26px); opacity:0; } }
@keyframes artspiout { 0% { transform:translateX(-56px); opacity:0; }
                      6% { opacity:1; }
                      40% { transform:translateX(56px); opacity:1; }
                      46%, 100% { transform:translateX(56px); opacity:0; } }
@keyframes artspiin { 0% { transform:translateX(56px); opacity:0; }
                      6% { opacity:1; }
                      40% { transform:translateX(-56px); opacity:1; }
                      46%, 100% { transform:translateX(-56px); opacity:0; } }

/* The board's own screens on /setup: a bezel, a dark glass, and the
   terminal's colours. As wide as a comfortable reading column at most;
   a phone draws them at nearly 1:1. */
svg.art.shot { width:100%; height:auto; margin:1rem auto 1.5rem; }
/* The cover on /donate: the full width of the column, never taller than
   its own proportions. */
img.cover { display:block; width:100%; height:auto; margin:0.5rem 0 1.5rem; }
svg.art.shot .scr { fill:#06060a; stroke:var(--dial); stroke-width:1; }
svg.art.shot text.cap { fill:var(--dial); }
svg.art.shot text.cz { fill:#06060a; }
svg.art.shot text.c0 { fill:#2a2a2a; }  svg.art.shot rect.b0 { fill:#2a2a2a; }
svg.art.shot text.c1 { fill:#b04848; }  svg.art.shot rect.b1 { fill:#b04848; }
svg.art.shot text.c2 { fill:#3fae5a; }  svg.art.shot rect.b2 { fill:#3fae5a; }
svg.art.shot text.c3 { fill:#b58a2e; }  svg.art.shot rect.b3 { fill:#b58a2e; }
svg.art.shot text.c4 { fill:#4f78c0; }  svg.art.shot rect.b4 { fill:#4f78c0; }
svg.art.shot text.c5 { fill:#9a6fd8; }  svg.art.shot rect.b5 { fill:#9a6fd8; }
svg.art.shot text.c6 { fill:#3fb8b8; }  svg.art.shot rect.b6 { fill:#3fb8b8; }
svg.art.shot text.c7 { fill:#c0c0c0; }  svg.art.shot rect.b7 { fill:#c0c0c0; }
svg.art.shot text.c8 { fill:#6a6a72; }  svg.art.shot rect.b8 { fill:#6a6a72; }
svg.art.shot text.c9 { fill:#ff7a7a; }  svg.art.shot rect.b9 { fill:#ff7a7a; }
svg.art.shot text.ca { fill:#6ee88a; }  svg.art.shot rect.ba { fill:#6ee88a; }
svg.art.shot text.cb { fill:#ffe066; }  svg.art.shot rect.bb { fill:#ffe066; }
svg.art.shot text.cc { fill:#7fa8ff; }  svg.art.shot rect.bc { fill:#7fa8ff; }
svg.art.shot text.cd { fill:#c8a0ff; }  svg.art.shot rect.bd { fill:#c8a0ff; }
svg.art.shot text.ce { fill:#7fe8e8; }  svg.art.shot rect.be { fill:#7fe8e8; }
svg.art.shot text.cf { fill:#ffffff; }  svg.art.shot rect.bf { fill:#ffffff; }

@keyframes artgrow { 0% { transform:scaleX(0.04); } 70%, 100% { transform:scaleX(1); } }
@keyframes arttimer { from { stroke-dashoffset:30; } to { stroke-dashoffset:0; } }

@media (prefers-reduced-motion: no-preference) {
  /* /install: a progress bar filling, storage being made, the Wi-Fi timer */
  svg.art .grow { transform-box:fill-box; transform-origin:left center;
        animation:artgrow 3.2s ease-in-out infinite; }
  svg.art .grow.g2 { animation-delay:0.8s; }
  svg.art .timer { animation:arttimer 6s linear infinite; }
  /* nobody has to say yes: the gate is up and things go through it */
  svg.art.i-gate .go { animation:artpass 3.2s ease-in-out infinite; }
  /* no internet: traffic on the local links, nothing on the cloud */
  svg.art.i-net .dw { animation:artwest 1.6s linear infinite; }
  svg.art.i-net .de { animation:arteast 1.6s linear 0.8s infinite backwards; }
  /* a battery: charge going down the cable, the lamp answering */
  svg.art.i-bat .go { animation:artfeed 1.6s linear infinite; }
  svg.art.i-bat .led { animation:artpulse 1.6s ease-in-out infinite; }
  /* on a shelf: the one sign of life is a small lamp */
  svg.art.i-shelf .led { animation:artglow 4s ease-in-out infinite; }
  /* nobody can deplatform you: your flag, on your chip, still flying */
  svg.art.i-flag .wave { transform-box:fill-box; transform-origin:0% 50%;
        animation:artwave 1.8s ease-in-out infinite alternate; }
  /* you write the rules: line by line, by you */
  svg.art.i-rules .w { stroke-dasharray:10;
        animation:artwrite 6.4s ease-out infinite backwards; }
  svg.art.i-rules .w2 { animation-delay:0.8s; }
  svg.art.i-rules .w3 { animation-delay:1.6s; }
  svg.art.i-rules .w4 { animation-delay:2.4s; }
  /* nobody is mining it: people talk, and the eye stays shut */
  svg.art.i-eye .b1 { animation:artsay 4s ease-in-out infinite; }
  svg.art.i-eye .b2 { animation:artsay 4s ease-in-out 2s infinite backwards; }
  /* nobody checks who you are: a handle and a cursor, nothing else */
  svg.art .caret { animation:artcaret 1.6s steps(1,end) infinite; }
  /* what you keep: the sand runs, and the message goes when it runs out */
  svg.art.i-keep .grain { animation:artfall 1.2s linear infinite; }
  /* read every line: the lens goes down the listing and back */
  svg.art.i-code .lens { animation:artscan 3.6s ease-in-out infinite alternate; }
  /* keeps working: the days go by, the lamp does not go out */
  svg.art.i-year .n { animation:artday 6s linear infinite backwards; }
  svg.art.i-year .n2 { animation-delay:2s; }
  svg.art.i-year .n3 { animation-delay:4s; }
  /* found or not: it calls out, and then it is quiet */
  svg.art.i-cast .r { animation:artring 4.8s ease-out infinite backwards; }
  svg.art.i-cast .r2 { animation-delay:0.35s; }
  svg.art.i-cast .r3 { animation-delay:0.7s; }
  /* the first call: it works out what you are, asks, lets you in */
  svg.art .p1 { animation:artshow 4.8s ease-out infinite backwards; }
  svg.art .p1b { animation-delay:0.6s; }
  svg.art .p1c { animation-delay:1.2s; }
  svg.art .p3b { animation:artshow 4.8s ease-out 1.4s infinite backwards; }
  /* the bridge: bytes going down the serial cable to the box */
  svg.art.bridge .go { animation:artserial 2.4s linear infinite; }
  /* the SD card: select it, clock the command out, read the answer back */
  svg.art.wiring .p-cs { animation:artspiout 3.2s linear infinite backwards; }
  svg.art.wiring .p-out { animation:artspiout 3.2s linear 0.4s infinite backwards; }
  svg.art.wiring .p-in { animation:artspiin 3.2s linear 1.2s infinite backwards; }
}
</style>"""


def _icon(name, inner):
    """One freedom's drawing. aria-hidden, because the heading beside it
    already says what it means and a screen reader should not be handed
    twelve descriptions of pictures on the way to twelve sentences."""
    return (f'<svg class="art icon i-{name}" viewBox="0 0 56 56" '
            'aria-hidden="true" focusable="false">' + inner + "</svg>")


ICONS = {
    # A barrier with its arm up, and something going through. The short
    # post on the far side is where the arm would come down, which is what
    # makes an arm in the air read as a gate that is open.
    "gate": _icon("gate", """
  <path class="f" d="M4 47 H52"/>
  <rect class="d" x="47" y="39" width="4" height="8" rx="1"/>
  <g class="go"><circle class="halo" cx="31" cy="42" r="4.2"/><circle class="lf" cx="31" cy="42" r="2.2"/></g>
  <rect class="o" x="8" y="29" width="7" height="18" rx="1.5"/>
  <g transform="rotate(-60 11.5 30)">
    <rect class="o" x="11.5" y="28" width="26" height="4" rx="2"/>
    <path class="d" d="M19 28 V32 M26 28 V32 M33 28 V32"/>
  </g>
  <circle class="lf" cx="11.5" cy="30" r="1.6"/>"""),
    # Two terminals and a board on a local link, and a cloud struck out.
    "net": _icon("net", """
  <path class="f" d="M18.5 22 C14 22 14 15.5 18.5 15.5 C19 10.5 25.5 9 28 12.5 C30 8 37 8.5 37.5 14 C42 14 42 22 37.5 22 Z"/>
  <path class="f" d="M15 7 L42 26"/>
  <rect class="o" x="3" y="31" width="12" height="10" rx="1.5"/>
  <rect class="g" x="5" y="33" width="8" height="6" rx="0.8"/>
  <path class="d" d="M9 41 V43.5 M6 43.5 H12"/>
  <rect class="o" x="41" y="31" width="12" height="10" rx="1.5"/>
  <rect class="g" x="43" y="33" width="8" height="6" rx="0.8"/>
  <path class="d" d="M47 41 V43.5 M44 43.5 H50"/>
  <path class="ld" d="M15 36 H22 M34 36 H41"/>
  <rect class="body" x="22" y="31" width="12" height="10" rx="1.5"/>
  <circle class="lf" cx="28" cy="36" r="1.5"/>
  <circle class="lf dw" cx="18.5" cy="36" r="1.3"/>
  <circle class="lf de" cx="37.5" cy="36" r="1.3"/>"""),
    # A power bank feeding a board down a cable.
    "battery": _icon("bat", """
  <rect class="o" x="9" y="15" width="6" height="3" rx="1"/>
  <rect class="o" x="4" y="18" width="16" height="27" rx="2"/>
  <rect class="lf" x="7" y="22" width="10" height="5" rx="1" opacity="0.35"/>
  <rect class="lf" x="7" y="29" width="10" height="5" rx="1"/>
  <rect class="lf" x="7" y="36" width="10" height="5" rx="1"/>
  <path class="d" d="M20 31.5 H34"/>
  <rect class="pin" x="50" y="26" width="3" height="2" rx="0.5"/>
  <rect class="pin" x="50" y="30.5" width="3" height="2" rx="0.5"/>
  <rect class="pin" x="50" y="35" width="3" height="2" rx="0.5"/>
  <rect class="body" x="34" y="23" width="16" height="17" rx="2"/>
  <circle class="lf led" cx="42" cy="31.5" r="1.8"/>
  <circle class="lf go" cx="27" cy="31.5" r="1.4"/>"""),
    # A shelf of books, and a small board among them.
    "shelf": _icon("shelf", """
  <path class="o" d="M4 42 H52"/>
  <path class="d" d="M10 42 V47 M46 42 V47"/>
  <rect class="o" x="8" y="18" width="5" height="24" rx="0.8"/>
  <rect class="o" x="14" y="22" width="4" height="20" rx="0.8"/>
  <rect class="o" x="19" y="15" width="6" height="27" rx="0.8"/>
  <path class="d" d="M19 20 H25 M19 37 H25"/>
  <path class="o" d="M26 42 L32.5 20 L36.5 21.2 L30 42 Z"/>
  <rect class="o" x="38" y="34" width="12" height="8" rx="1"/>
  <path class="d" d="M40 38 H45"/>
  <circle class="lf led" cx="47.5" cy="37" r="1.1"/>"""),
    # A flag planted on a board.
    "flag": _icon("flag", """
  <path class="o" d="M22 38 V7"/>
  <path class="l wave" d="M22 8.5 H43 L38 14.5 L43 20.5 H22"/>
  <rect class="pin" x="19" y="49" width="2" height="3.5" rx="0.5"/>
  <rect class="pin" x="25" y="49" width="2" height="3.5" rx="0.5"/>
  <rect class="pin" x="31" y="49" width="2" height="3.5" rx="0.5"/>
  <rect class="pin" x="37" y="49" width="2" height="3.5" rx="0.5"/>
  <rect class="body" x="15" y="38" width="26" height="11" rx="2"/>
  <circle class="lf" cx="34" cy="43.5" r="1.6"/>"""),
    # A page being written, and the pencil writing it.
    "rules": _icon("rules", """
  <path class="o" d="M10 6 H32 L40 14 V50 H10 Z"/>
  <path class="d" d="M32 6 V14 H40"/>
  <path class="lt w w1" d="M15 21 H34" pathLength="10"/>
  <path class="lt w w2" d="M15 27 H34" pathLength="10"/>
  <path class="lt w w3" d="M15 33 H28" pathLength="10"/>
  <path class="lt w w4" d="M15 39 H31" pathLength="10"/>
  <path class="gb" d="M38 47 L49 36 L52.5 39.5 L41.5 50.5 Z"/>
  <path class="o" d="M38 47 L35.5 53 L41.5 50.5"/>
  <path class="d" d="M46.5 38.5 L50 42"/>"""),
    # An eye that is shut, over two people talking.
    "eye": _icon("eye", """
  <path class="o" d="M13 14 Q28 25 43 14"/>
  <path class="d" d="M17.5 16.8 L15.8 20.3 M22.5 18.8 L21.6 22.8 M28 19.5 V23.7 M33.5 18.8 L34.4 22.8 M38.5 16.8 L40.2 20.3"/>
  <g class="b1"><path class="gb" d="M9 30 H27 A3 3 0 0 1 30 33 V37 A3 3 0 0 1 27 40 H15 L10 44 V40 H9 A3 3 0 0 1 6 37 V33 A3 3 0 0 1 9 30 Z"/><path class="lt" d="M11 35 H24"/></g>
  <g class="b2"><path class="gb" d="M29 39 H47 A3 3 0 0 1 50 42 V46 A3 3 0 0 1 47 49 H46 V53 L41 49 H29 A3 3 0 0 1 26 46 V42 A3 3 0 0 1 29 39 Z"/><path class="lt" d="M31 44 H44"/></g>"""),
    # A name badge with a handle on it and a cursor after it.
    "badge": _icon("badge", """
  <rect class="d" x="24" y="6" width="8" height="6" rx="1"/>
  <rect class="o" x="6" y="12" width="44" height="32" rx="3"/>
  <path class="k" d="M9 12 H47 A3 3 0 0 1 50 15 V21 H6 V15 A3 3 0 0 1 9 12 Z"/>
  <text class="ink" x="10" y="35" font-size="9">Sparks</text>
  <rect class="lf caret" x="43.5" y="27.5" width="3.5" height="8.5"/>
  <path class="f" d="M10 39 H46"/>"""),
    # A letter, and an hourglass running.
    "keep": _icon("keep", """
  <rect class="o" x="3" y="18" width="30" height="21" rx="1.5"/>
  <path class="d" d="M3.5 19 L18 30 L32.5 19"/>
  <path class="o" d="M37 9 H53 M37 47 H53"/>
  <path class="o" d="M39.5 9 C39.5 20 44 24 45 28 C44 32 39.5 36 39.5 47 M50.5 9 C50.5 20 46 24 45 28 C46 32 50.5 36 50.5 47"/>
  <path class="lf" d="M42 14.5 H48 C47.3 19.5 46.2 22.8 45 25.2 C43.8 22.8 42.7 19.5 42 14.5 Z" opacity="0.45"/>
  <path class="lf" d="M41 47 C41.8 42 43.8 39.3 45 38.5 C46.2 39.3 48.2 42 49 47 Z"/>
  <circle class="lf grain" cx="45" cy="32" r="0.9"/>"""),
    # A listing with a lens going over it.
    "code": _icon("code", """
  <path class="o" d="M7 6 H31 L39 14 V50 H7 Z"/>
  <path class="d" d="M31 6 V14 H39"/>
  <path class="d" d="M12 19 H21 M15 24 H32 M15 29 H28 M12 34 H19 M15 39 H33 M12 44 H23"/>
  <g class="lens"><circle class="l" cx="35" cy="31" r="7"/><path class="lw" d="M40 36 L48 44"/></g>"""),
    # A calendar counting the days, and a board with its lamp on.
    "year": _icon("year", """
  <rect class="o" x="3" y="12" width="28" height="31" rx="2"/>
  <path class="k" d="M5 12 H29 A2 2 0 0 1 31 14 V20 H3 V14 A2 2 0 0 1 5 12 Z"/>
  <path class="o" d="M10 8 V15 M24 8 V15"/>
  <text class="ink n n1" x="17" y="36" font-size="11" text-anchor="middle">1</text>
  <text class="ink n n2" x="17" y="36" font-size="11" text-anchor="middle">182</text>
  <text class="ink n n3" x="17" y="36" font-size="11" text-anchor="middle">365</text>
  <rect class="pin" x="51" y="28" width="3" height="2" rx="0.5"/>
  <rect class="pin" x="51" y="32.5" width="3" height="2" rx="0.5"/>
  <rect class="pin" x="51" y="37" width="3" height="2" rx="0.5"/>
  <rect class="body" x="36" y="25" width="15" height="17" rx="2"/>
  <circle class="halo" cx="43.5" cy="33.5" r="4"/>
  <circle class="lf" cx="43.5" cy="33.5" r="1.8"/>"""),
    # A board with an aerial, calling out, and then quiet.
    "cast": _icon("cast", """
  <path class="l r r1" d="M32.6 19.1 A6 6 0 0 1 32.6 26.9 M23.4 19.1 A6 6 0 0 0 23.4 26.9"/>
  <path class="l r r2" d="M36.4 15.9 A11 11 0 0 1 36.4 30.1 M19.6 15.9 A11 11 0 0 0 19.6 30.1"/>
  <path class="l r r3" d="M40.3 12.7 A16 16 0 0 1 40.3 33.3 M15.7 12.7 A16 16 0 0 0 15.7 33.3"/>
  <path class="o" d="M28 35 V25"/>
  <circle class="lf" cx="28" cy="23" r="1.6"/>
  <rect class="pin" x="23" y="47" width="2" height="3.5" rx="0.5"/>
  <rect class="pin" x="31" y="47" width="2" height="3.5" rx="0.5"/>
  <rect class="body" x="20" y="35" width="16" height="12" rx="2"/>
  <circle class="lf" cx="31" cy="41" r="1.4"/>"""),
}


def _screen(x0, inner):
    """One terminal of the first-call strip, the same build as WIRE's:
    a case, a glass, a row of keys, a neck and a foot."""
    return (f'<rect class="o" x="{x0 + 10}" y="6" width="90" height="64" rx="5"/>'
            f'<rect class="g" x="{x0 + 16}" y="12" width="78" height="46" rx="2"/>'
            f'<rect class="k" x="{x0 + 16}" y="62" width="78" height="4" rx="2"/>'
            f'<path class="o" d="M{x0 + 47} 70 L{x0 + 43} 80 H{x0 + 67} L{x0 + 63} 70 Z"/>'
            f'<rect class="o" x="{x0 + 37}" y="80" width="36" height="4" rx="2"/>'
            + inner)


def _caption(x0, first, second):
    return (f'<text x="{x0 + 55}" y="102" font-size="10.5" text-anchor="middle">{first}</text>'
            f'<text x="{x0 + 55}" y="115" font-size="10.5" text-anchor="middle">{second}</text>')


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


# ----------------------------------------------------------------------
# The machines on /terminals, one strip per section of the page, drawn in
# the same hand as everything above: --dial outlines, --live for anything
# alive, a glass on every screen, keys as translucent strips.
#
# Only machines the page actually names, and no logos: the Commodore's
# rainbow is four stripes in the site's own colours rather than a badge,
# and a machine is recognised by its shape (the breadbin, the 800XL's
# column of console keys, the Apple II's bracket prompt, the A500's split
# row of function keys) rather than by anything anybody owns.
#
# Each is 354 units wide for the same reason the first call strip is: a
# phone column is about 353px, so a phone draws it at 1:1. The only motion
# is the carets and the dot on the bridge's serial cable, both declared in
# the no-preference block like every other drawing here.
# ----------------------------------------------------------------------

def _machines(cls, height, alt, inner):
    # height is the viewBox height from its origin at -6, and every strip
    # ends 8 units below its lowest label's baseline. The first cut ended
    # three of them on the baseline and cut the descenders off.
    return (f'<svg class="art machines{cls}" viewBox="-5 -6 354 {height}" role="img" '
            'preserveAspectRatio="xMidYMid meet" aria-label="'
            + html.escape(alt, quote=True) + '">' + inner + "</svg>")


def _label(x, y, text):
    return (f'<text x="{x}" y="{y}" font-size="10.5" text-anchor="middle">'
            + text + "</text>")


def _keyrows(x, y, w, rows, step=6):
    return "".join(f'<rect class="k" x="{x}" y="{y + i * step}" width="{w}" '
                   'height="3.5" rx="1.5"/>' for i in range(rows))


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
    "Wiring an SD card module to an ESP32 dev board, six wires. Ground to GND. "
    "Power from the 3V3 pin to VCC. GPIO19, printed D19, to MISO. GPIO23, D23, "
    "to MOSI. GPIO18, D18, to SCK. GPIO5, D5, to CS. The module carries a "
    "regulator, a level shifter and a micro SD card in its socket. Start the "
    "power on 3V3, and go by the printed pin names, because boards put their "
    "pins in different orders.")


def _sd_wiring():
    out = ['<svg class="art wiring" viewBox="-5 -6 354 308" role="img" '
           'preserveAspectRatio="xMidYMid meet" aria-label="'
           + html.escape(SD_WIRING_ALT, quote=True) + '">']
    # The dev board: module can with its antenna, two headers, buttons, USB.
    out.append(
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
        out.append(
            f'<path class="ww s-{c}" d="M108 {y} H234"/>'
            f'<rect class="f-{c}" x="101" y="{y - 2.5}" width="5" height="5" rx="1"/>'
            f'<rect class="f-{c}" x="234" y="{y - 2.5}" width="5" height="5" rx="1"/>'
            f'<text class="f-{c}" x="97" y="{y + 3}" font-size="10" '
            f'text-anchor="end">{pin}</text>'
            f'<text class="f-{c}" x="171" y="{y - 5}" font-size="10" '
            f'text-anchor="middle">{wire}</text>'
            f'<text class="f-{c}" x="245" y="{y + 3}" font-size="10">{mod}</text>')
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
SHOTS_DIR = pathlib.Path(__file__).resolve().parent / "shots"
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

# ----------------------------------------------------------------------
# /install, drawn step by step (0.18.0). Rob: "the install button looks fine
# but some of those cool graphics showing what's about to happen is fun."
# The same hand as the first call strip: --dial outlines, --live for what
# is alive, 354 units wide so a phone draws them at 1:1. Each is decoration
# beside a step that says the same thing in words, so each is aria-hidden;
# nothing a reader needs is only in a drawing. The motion (a lamp, a
# progress bar, two storage bars and a timer) is in the no-preference
# block like every other drawing's, so the markup is the resting state.
# ----------------------------------------------------------------------
def _deco(height, inner):
    return (f'<svg class="art steps" viewBox="-5 -6 354 {height}" aria-hidden="true" '
            'focusable="false" preserveAspectRatio="xMidYMid meet">' + inner + "</svg>")


def _board(x, y, lamp_class="lf caret"):
    """A dev board, 120 x 52, module can, antenna, pins, a USB socket on
    its left edge and its lamp."""
    return (f'<rect class="o" x="{x}" y="{y}" width="120" height="52" rx="3"/>'
            + '<path class="d" d="' + " ".join(
                f"M{x + 8 + i * 9} {y} V{y - 4} M{x + 8 + i * 9} {y + 52} V{y + 56}"
                for i in range(12)) + '"/>'
            f'<rect class="g" x="{x + 36}" y="{y + 8}" width="44" height="34" rx="1.5"/>'
            f'<path class="d" d="M{x + 40} {y + 14} H{x + 44} V{y + 11} H{x + 49} V{y + 14}'
            f' H{x + 54} V{y + 11} H{x + 59} V{y + 14} H{x + 64} V{y + 11} H{x + 69}'
            f' V{y + 14} H{x + 76}"/>'
            f'<rect class="gb" x="{x - 6}" y="{y + 20}" width="10" height="12" rx="1"/>'
            f'<circle class="{lamp_class}" cx="{x + 108}" cy="{y + 42}" r="2.5"/>')


INSTALL_CABLE = _deco(118,
    # A laptop with the page open, the button on its screen.
    '<rect class="o" x="8" y="8" width="112" height="72" rx="4"/>'
    '<rect class="g" x="14" y="14" width="100" height="58" rx="2"/>'
    '<rect class="k" x="32" y="34" width="64" height="18" rx="3"/>'
    '<text class="ink" x="64" y="46.5" font-size="9" text-anchor="middle">Install</text>'
    '<path class="o" d="M0 84 H128 L122 91 H6 Z"/>'
    # The cable: two conductors drawn inside the sleeve, because a cable
    # that carries data is the whole point of the step.
    '<path class="o" d="M124 84 C160 84 166 64 208 64"/>'
    '<path class="lt" d="M126 87 C161 87 167 67 208 67"/>'
    + _board(214, 40) +
    '<text x="150" y="108" font-size="9" text-anchor="middle">a cable that carries data</text>')

INSTALL_WRITE = _deco(112,
    # Three moments of the installer's own dialog, as a new board meets
    # them: Install, the erase question, the progress bar. The labels are
    # the dialog's own since 0.22.1: "Install or update", "Start fresh?"
    # and "Erase everything first", the last on two lines to fit its box.
    '<rect class="o" x="0" y="6" width="104" height="72" rx="4"/>'
    '<text class="ink" x="8" y="21" font-size="8">unleashed BBS</text>'
    '<rect class="k" x="8" y="30" width="88" height="16" rx="2"/>'
    '<text class="ink" x="13" y="41" font-size="7.5">Install or update</text>'
    '<text x="14" y="62" font-size="7.5">Logs &amp; Console</text>'
    '<path class="d" d="M108 38 L112 42 L108 46"/>'
    '<rect class="o" x="118" y="6" width="104" height="72" rx="4"/>'
    '<text class="ink" x="126" y="21" font-size="8">Start fresh?</text>'
    '<rect class="o" x="128" y="33" width="11" height="11" rx="1.5"/>'
    '<path class="l" d="M130.5 38.5 L133.5 41.5 L137 35.5"/>'
    '<text class="ink" x="144" y="41" font-size="7.5">Erase everything</text>'
    '<text class="ink" x="144" y="50" font-size="7.5">first</text>'
    '<text x="126" y="64" font-size="7.5">new board: tick it</text>'
    '<path class="d" d="M226 38 L230 42 L226 46"/>'
    '<rect class="o" x="236" y="6" width="108" height="72" rx="4"/>'
    '<text class="ink" x="244" y="21" font-size="8">Installing</text>'
    '<rect class="o" x="244" y="32" width="92" height="10" rx="3"/>'
    '<rect class="lf grow" x="246" y="34" width="60" height="6" rx="2"/>'
    '<text x="244" y="64" font-size="7.5">about two minutes</text>'
    '<text x="52" y="98" font-size="9" text-anchor="middle">install</text>'
    '<text x="170" y="98" font-size="9" text-anchor="middle">erase, the first time</text>'
    '<text x="290" y="98" font-size="9" text-anchor="middle">writing</text>')

INSTALL_BOOT = _deco(108,
    _board(6, 28)
    + '<path class="d" d="M140 54 L148 54 M144 50 L148 54 L144 58"/>'
    # The flash, three parts: the screens arrive written, the other two
    # are made on the first start.
    '<rect class="o" x="160" y="6" width="182" height="86" rx="3"/>'
    '<text class="ink" x="170" y="21" font-size="8.5">first start</text>'
    '<rect class="k" x="170" y="30" width="162" height="12" rx="2"/>'
    '<text class="ink" x="175" y="39" font-size="7.5">screens: installed</text>'
    '<rect class="o" x="170" y="48" width="162" height="12" rx="2"/>'
    '<rect class="lf grow g1" x="171" y="49" width="160" height="10" rx="1.5" opacity="0.35"/>'
    '<text class="ink" x="175" y="57" font-size="7.5">accounts, settings: formatting</text>'
    '<rect class="o" x="170" y="66" width="162" height="12" rx="2"/>'
    '<rect class="lf grow g2" x="171" y="67" width="160" height="10" rx="1.5" opacity="0.35"/>'
    '<text class="ink" x="175" y="75" font-size="7.5">caller log: formatting</text>')

INSTALL_WIFI = _deco(118,
    '<rect class="o" x="0" y="6" width="210" height="98" rx="4"/>'
    '<text class="ink" x="10" y="21" font-size="8.5">Configure Wi-Fi</text>'
    '<rect class="k" x="10" y="28" width="190" height="14" rx="2"/>'
    + "".join(
        f'<path class="d" d="M16 {y + 2} A5 5 0 0 1 24 {y + 2} M18 {y + 4.5} A2.5 2.5 0 0 1 22 {y + 4.5}"/>'
        f'<text class="{cls}" x="30" y="{y + 6}" font-size="8">{name}</text>'
        for y, name, cls in ((32, "your network", "ink"), (48, "a neighbour", ""),
                             (64, "Join other...", "")))
    + '<rect class="o" x="10" y="78" width="120" height="16" rx="2"/>'
    '<text class="ink" x="16" y="89" font-size="8" letter-spacing="1">&#8226;&#8226;&#8226;&#8226;&#8226;&#8226;&#8226;&#8226;</text>'
    '<rect class="k" x="140" y="78" width="60" height="16" rx="3"/>'
    '<text class="ink" x="170" y="89" font-size="8" text-anchor="middle">Connect</text>'
    # The board tries for up to thirty seconds.
    '<circle class="d" cx="276" cy="48" r="26"/>'
    '<circle class="l timer" cx="276" cy="48" r="26" pathLength="30"/>'
    '<text class="ink" x="276" y="52" font-size="11" text-anchor="middle">30 s</text>'
    '<text x="276" y="94" font-size="8.5" text-anchor="middle">tries for up to</text>'
    '<text x="276" y="106" font-size="8.5" text-anchor="middle">thirty seconds</text>')

INSTALL_SETUP = _deco(130,
    _screen(0,
        '<text class="ink" x="21" y="23" font-size="7">not set up yet</text>'
        '<text x="21" y="32" font-size="7">you are local</text>'
        '<text class="dial" x="21" y="43" font-size="7">Sysop password:</text>'
        '<text class="ink" x="21" y="52" font-size="7">********</text>')
    + _caption(0, "it asks for", "the password")
    + '<path class="d" d="M109 35 L113 38.5 L109 42"/>'
    + _screen(118,
        '<text class="dial" x="139" y="24" font-size="7">STAFF PASSWORDS</text>'
        '<path class="d" d="M139 27 H206"/>'
        '<text class="ink" x="139" y="39" font-size="7">Sysop</text>'
        '<rect class="k" x="163" y="33" width="42" height="8" rx="1"/>'
        '<rect class="lf caret" x="165" y="34" width="3" height="6"/>'
        '<text x="139" y="51" font-size="7">Co-sysop</text>')
    + _caption(118, "you choose", "your own")
    + '<path class="d" d="M227 35 L231 38.5 L227 42"/>'
    + _screen(236,
        '<text class="dial" x="257" y="24" font-size="7">YOUR BOARD</text>'
        '<path class="d" d="M257 27 H324 M257 34 H316 M257 40 H320 M257 46 H300"/>'
        '<text x="257" y="54" font-size="6.5">Page 1 of 2</text>')
    + _caption(236, "then a short", "tour"))

# The BOOT button, for firmware 1.0.2 and later: the two buttons and the
# order to press them in, then what the lamp does against the seconds held.
# Axis 0 to 22 s across x 20 to 340, 14.55 units a second.
def _bx(sec):
    return round(20 + sec * 320 / 22, 1)


BOOT_BUTTON = _deco(206,
    '<rect class="o" x="30" y="8" width="284" height="58" rx="3"/>'
    '<circle class="o" cx="100" cy="36" r="10"/><circle class="k" cx="100" cy="36" r="6"/>'
    '<text class="ink" x="100" y="20" font-size="8" text-anchor="middle">RESET</text>'
    '<circle class="o" cx="190" cy="36" r="10"/><circle class="k" cx="190" cy="36" r="6"/>'
    '<text class="ink" x="190" y="20" font-size="8" text-anchor="middle">BOOT</text>'
    '<circle class="lf" cx="276" cy="36" r="4"/>'
    '<text x="276" y="20" font-size="8" text-anchor="middle">LED</text>'
    '<text class="dial" x="100" y="80" font-size="8.5" text-anchor="middle">1 press, let go</text>'
    '<text class="dial" x="190" y="80" font-size="8.5" text-anchor="middle">2 press and hold</text>'
    # The timeline.
    f'<path class="d" d="M{_bx(0)} 118 H{_bx(22)}"/>'
    + "".join(f'<path class="d" d="M{_bx(s)} 114 V122"/>'
              f'<text x="{_bx(s)}" y="133" font-size="8" text-anchor="middle">{s} s</text>'
              for s in (0, 7, 15, 20))
    # 0 to 7: slow blink. 7 to 15: rapid. 15 to 20: solid. 20 on: off.
    + "".join(f'<circle class="lf" cx="{_bx(s)}" cy="104" r="2.2"/>'
              for s in (0.8, 2.6, 4.4, 6.2))
    + "".join(f'<circle class="c5" cx="{_bx(7.5 + i * 0.52)}" cy="104" r="1.6"/>'
              for i in range(15))
    + f'<rect class="c3" x="{_bx(15)}" y="101" width="{_bx(20) - _bx(15)}" height="6" rx="2"/>'
    f'<circle class="f" cx="{_bx(21)}" cy="104" r="2.2"/>'
    + f'<text x="{_bx(3.5)}" y="152" font-size="8" text-anchor="middle">slow blink:</text>'
    f'<text class="ink" x="{_bx(3.5)}" y="163" font-size="8" text-anchor="middle">nothing</text>'
    f'<text x="{_bx(11)}" y="152" font-size="8" text-anchor="middle">rapid flash:</text>'
    f'<text class="warm" x="{_bx(11)}" y="163" font-size="8" text-anchor="middle">sysop password</text>'
    f'<text class="warm" x="{_bx(11)}" y="174" font-size="8" text-anchor="middle">back to default</text>'
    f'<text x="{_bx(17.5)}" y="152" font-size="8" text-anchor="middle">solid:</text>'
    f'<text class="busy" x="{_bx(17.5)}" y="163" font-size="8" text-anchor="middle">factory</text>'
    f'<text class="busy" x="{_bx(17.5)}" y="174" font-size="8" text-anchor="middle">reset</text>'
    f'<text x="{_bx(21.2)}" y="152" font-size="8" text-anchor="middle">off:</text>'
    f'<text class="ink" x="{_bx(21.2)}" y="163" font-size="7" text-anchor="middle">abandoned</text>'
    f'<text x="{_bx(11)}" y="190" font-size="8" text-anchor="middle">what letting go of BOOT does, by seconds held</text>')

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

ART = {"firstcall": FIRSTCALL_ART,
       "install-cable": INSTALL_CABLE,
       "install-write": INSTALL_WRITE,
       "install-boot": INSTALL_BOOT,
       "install-wifi": INSTALL_WIFI,
       "install-setup": INSTALL_SETUP,
       "boot-button": BOOT_BUTTON,
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
       # The cover at the top of /donate. An image rather than inline, so
       # it is fetched once and cached, and it is vector either way.
       "cover": ('<img class="cover" src="/cover.svg" width="1600" height="310" '
                 'alt="The \u00b5nleashed wordmark, with the words Electronic '
                 'freedom and No web. No cloud. No browser., beside a terminal '
                 'panel reading CONNECT 2400, NODE 1 OF 10, TELNET PETSCII ANSI '
                 'and ESP32 GPL v2+.">')}
ART.update({key: shot_svg(name, alt) for key, (name, alt) in SHOTS.items()})

HOW = HOW.replace("@ART_CSS@", ART_CSS).replace("@SKULL@", SKULL)


# The h1 is not decoration. This is the page the whole argument lives on and
# it used to start at h2, so it had no document outline, no heading for a
# screen reader to land on, and nothing on screen saying what it was called.
ABOUT = """<h1>What this is</h1>
<p class="lead">Electronic freedom on a microcontroller. No web, no cloud, no browser.</p>

<p class="byline">Written and built by <a class="author" href="/author">QuantumRob</a>, who has been doing this
since the 4381 was the computer in the room. The argument below is his; the
software is free for anybody who agrees with it, and for anybody who does
not.</p>
""" + DIAGRAM_CSS + ART_CSS + WIRE + """
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
Great Blizzard of 1978, which dumped record snow across the Midwest that January,
handed them the quiet weeks to build it. Their own write-up in
<a href="https://archive.org/details/byte-magazine-1978-11">Byte that
November</a> specified an 8080 on the S-100 bus with 24 kilobytes of memory and a
single floppy disk, and it answered one caller at a time.</p>

<p class="pull">I met Ward Christensen once, at a Maker Faire. I did not know it
would be the only time. He died on
<a href="https://www.theregister.com/offbeat/2024/10/15/rip-ward-christensen-co-developer-of-the-cbss/492871">11
October 2024</a>, and I wish I had spent longer talking to him while I had the
chance. If you get to meet the person who built the thing you love, take the extra
hour.<br><br><span class="sig">&mdash; <a class="author" href="/author">QuantumRob</a></span></p>

<p>Thousands of boards followed. Each one was somebody's own idea of what a
community should look like: a music board, a board for one town, a board that was its
sysop and eleven friends.
<a href="https://en.wikipedia.org/wiki/Bulletin_board_system">InfoWorld
estimated</a> 60,000 of them in the United States alone in 1994, and
<a href="https://en.wikipedia.org/wiki/FidoNet">FidoNet</a> tied tens of thousands
into a store-and-forward network that moved mail around the world overnight, when
the long-distance rates were lowest, run by hobbyists.</p>

<p>Almost all of them ran on hardware weaker than the five dollar chip this software
runs on.</p>

<h2>The whole computer</h2>

<p>This is an <a href="https://en.wikipedia.org/wiki/ESP32">ESP32-WROOM-32E</a>. It
is a microcontroller about the size of a postage stamp with a radio on it: a
dual-core processor that runs at up to 240 MHz, <b>520 kilobytes</b> of RAM, four
megabytes of flash, and Wi-Fi. It costs a few dollars, draws about a tenth of an
amp while it listens for callers, and runs from a phone charger.</p>

<p>CBBS answered one caller at a time on 24 kilobytes. This has more than twenty
times that memory and answers ten at once, with a hidden eleventh line the sysop
comes in on. There is no operating system underneath it worth the name, no web
stack, no database, no container: the whole board is one program that fits in
about a megabyte, and its sessions and buffers are set aside when it starts rather
than asked for while callers are on.</p>

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

<p class="pull">What was lost was not the modem noise. It was that the system
belonged to somebody you could name.</p>

<h2>What this is</h2>

<p>A telnet BBS that runs on a bare ESP32 and grows into an IoT terminal server
through plugins. Nodes, handles, a user list, a chat room in the style of DDial and
Gtalk, mail between callers, file areas on an SD card, forums on the same card, a
caller log, a sysop who can page you. The forums are the newest part: topic areas
a sysop sets up, with conversations inside each one, read at the same prompt as
everything else. Doors come after them.</p>

<p><b>The board is yours.</b> Not an account on somebody's platform, not a tenant on a
server farm, not a feature that can be deprecated out from under you. A chip you own,
on a port you chose, running software you can read all of in an afternoon and change
when you disagree with it.</p>

<p>The user list is a text file. The settings are a text file. Mail goes from one caller
to another through a chip on your shelf, and the caller it was sent to decides whether
to keep it. There is no account to create, nothing to subscribe to, and no vendor who
can change the deal. It is GPL, so nobody can take it away from you later, including
the person who wrote it.</p>

<h2>Privacy forward, and what that means</h2>

<p>Every system you use was built by somebody, and the question worth asking is who it
was built to serve. A board is built to serve the person who owns it. That is the whole
of the privacy argument, and everything else follows from it.</p>

<p><b>There is no third party in the middle.</b> Not a company, not a platform, not an
advertiser, not a model being trained. A message goes from one caller to another through
a chip on somebody's shelf and stays there until one of them deletes it or it
expires. Nobody is
standing between those two people taking a copy, because there is nowhere for a copy to
go and nobody whose business it would be.</p>

<p>Here is the difference, drawn out.</p>

""" + TRACE + """

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

<p>None of this is granted to you. It is what is left when there is nobody in the
middle: no company, no platform, no landlord. Every item below is something you
cannot have on a service at any price, because the service's business depends on
you not having it.</p>

<div class="freedoms">

<div class="freedom">
@ICON gate@
<h4>Nobody has to say yes</h4>
<p>No application, no review, no waiting list, no API key, no app store, no terms
you agree to by scrolling past them. You buy a chip that costs a few dollars, you
flash it, and it is running. There is no step in that sequence where somebody else
decides whether you are allowed, because there is nobody else in it.</p>
</div>

<div class="freedom">
@ICON net@
<h4>It works with no internet at all</h4>
<p>A board needs no cloud, no domain and no hosting company. Stand it up on an
office network, a phone hotspot, a mesh, or a switch in a room with no uplink,
and anybody on that network calls it exactly as they would over the wire. A
school, a hackerspace, a campsite, a festival, a boat, a basement. When the line
to the outside world goes down, or was never there, it is the same board.</p>
</div>

<div class="freedom">
@ICON battery@
<h4>It fits in a pocket and runs off a battery</h4>
<p>The whole system is a chip the size of a postage stamp and a USB cable, drawing
about a tenth of an amp. A phone charger runs it, and so does a power bank or a
car socket. You can carry a community in a coat pocket and stand it up wherever
you are, which is not something anybody says about a server.</p>
</div>

<div class="freedom">
@ICON shelf@
<h4>It does not announce itself as anything</h4>
<p>No rack, no fan noise, no sign on the door, nothing to explain to anybody. A
board is a small circuit board on a shelf, indistinguishable from the other things
somebody has left plugged in. That is discretion of the object and not of the
wire: telnet is plain text, anybody on the path between a caller and the board can
read it, and the <a href="/privacy">privacy page</a> goes through what that does
and does not mean. What hides in plain sight is the machine.</p>
</div>

<div class="freedom">
@ICON flag@
<h4>Nobody can deplatform you</h4>
<p>No account to suspend, no host to complain to, no payment processor to lean on,
no app store to delist you from, no head office to write to about you. The board
is a chip you own on a connection you pay for. The only person who can switch it
off is you, and the only thing that can take it down is the electricity bill.</p>
</div>

<div class="freedom">
@ICON rules@
<h4>You write the rules, and you are the appeal</h4>
<p>No terms of service drafted by somebody else's lawyers, no content policy that
changes next quarter, no decision handed down by a department you cannot reach.
You decide what the board is called, what it is for, who is welcome and what is
allowed. The old answer to anybody who disagreed was that they could go and run
their own, and here that is not a brush-off. It is an afternoon and a USB
cable.</p>
</div>

<div class="freedom">
@ICON eye@
<h4>Nobody is mining it</h4>
<p>No analytics, no telemetry, no engagement metric, no recommendation engine, no
advertiser, no model being trained on what you said. Nothing ranks the
conversation, because nothing is reading it. It works like radio rather than like
a service: what is said in the room is heard by whoever is in the room, and
nothing is filed away somewhere you cannot reach.</p>
</div>

<div class="freedom">
@ICON badge@
<h4>Nobody checks who you are</h4>
<p>A guest types a handle and nothing else, gets fifteen minutes, and no account
is kept. Signing up asks for a password, a name and an email address, and none of
it is verified: the board cannot send email, so there is no confirmation link and
no code to type back. The phone number on the form is optional. No identity is
being assembled anywhere. Being unknown to a system is the ordinary condition of
being a person, and it should not take effort.</p>
</div>

<div class="freedom">
@ICON keep@
<h4>What you keep is what you chose to keep</h4>
<p>Mail sits on the chip until the caller it was sent to reads it and says whether
to keep it, reply to it or delete it, and it expires on its own after a fortnight
either way. There is no copy in a data centre, no backup nobody mentioned, no
"deactivated but retained for legitimate business purposes". Wipe the flash and it
is gone. Forgetting is the default, which is how conversation worked for the whole
of human history until about twenty years ago.</p>
</div>

<div class="freedom">
@ICON code@
<h4>You can read every line of it, and change any of them</h4>
<p>It is free software under the GPL. Not source-available, not "open" with a
licence that revokes itself if you compete: free. Read it, change it, run the
changed version, give it to somebody else. If this project goes somewhere you
hate, take the last version you liked and carry on without asking.</p>
</div>

<div class="freedom">
@ICON year@
<h4>It keeps working when nothing else does</h4>
<p>No certificate to renew, no API to be deprecated, no subscription to lapse, no
company to be acquired and shut down. Leave the board in a drawer for a year, plug
it in, and it answers, because there is nothing at the other end that has to still
exist. Software that outlives the company that made it used to be ordinary.</p>
</div>

<div class="freedom">
@ICON cast@
<h4>You can be found, or not, entirely as you choose</h4>
<p>List the board in a directory and strangers can call it. Leave it off and it
exists only for the people you tell. Take it off the internet and it serves your
own house. Nobody makes that decision but you, and nothing decides how visible you
are once you have made it.</p>
</div>

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
a sealed envelope. Telnet has no encryption, and the machines this is built for
cannot carry much: a stock Commodore 64 has been made to finish a modern TLS
handshake, and it takes
<a href="https://github.com/JC-000/c64-https">about half an hour</a>. Pretending
otherwise would be worse than saying so.</p>

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

<p>One static binary. Sessions and buffers laid out when the board starts, a fixed
memory budget on a chip with 520 KB of RAM. No web stack, no scripting runtime, two
pinned libraries on top of Espressif's own framework rather than a package tree to
audit at two in the morning, no telemetry, no update that arrives without you.
What is not built cannot be exploited, and what fits in one head can be trusted by the
person whose head it fits in.</p>

<h2>Serial did not die</h2>

<p><a href="https://en.wikipedia.org/wiki/RS-232">RS-232</a> was standardised by the
EIA in 1960. It still runs the console and management ports on network equipment,
industrial controllers and test gear, and its framing survives on nearly every
microcontroller made since as a
<a href="https://en.wikipedia.org/wiki/Universal_asynchronous_receiver-transmitter">TTL-level
UART</a>. More than sixty years on, the way a machine from 1982 talks is still the way you
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
you.<br><br><span class="sig">&mdash; <a class="author" href="/author">QuantumRob</a></span></p>

<h2>You can do this today</h2>

<p>Not as a re-enactment: as a live system with callers on it tonight. Flash a board,
give it your Wi-Fi, forward one port on your router, and you are running a public BBS.
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

# Each freedom's drawing goes in where its box names it. Done once, here,
# rather than pasted into the markup above, so the prose still reads as
# prose, and a misspelt name is a KeyError at import instead of a hole on
# somebody's screen.
ABOUT = re.sub(r"@ICON (\w+)@", lambda m: ICONS[m.group(1)], ABOUT)


# ----------------------------------------------------------------------
# /author: who QuantumRob is, reached from his name on the manifesto.
#
# Every fact on it is Rob's own account, cleaned up for grammar and not
# embellished, plus dates that were checked: the 4381 was announced in
# September 1983, and Ward Christensen died on 11 October 2024. Nothing was
# added from searching for his name. It is common enough that a namesake is
# a real risk, and a page about a person is the last place to guess.
#
# The photographs are hotlinked from Wikimedia Commons, which permits it,
# and that makes this the one prose page on the site that loads anything
# from anywhere else. The page says so under the pictures, the images go
# out with no referrer so Wikimedia is not told which page asked, and
# THIRD_PARTY_NOTICES.md lists it. Two rules came out of wiring them up:
#
# - Wikimedia serves thumbnails at a fixed set of widths (20, 40, 60, 120,
#   250, 330, 500, 960, 1280, 1920, 3840) and rejects a hotlink at any
#   other width with an HTML error page, which a browser shows as a broken
#   image. Every URL below is one of those widths or the original file.
# - Every picture carries width and height, so the space is held while it
#   loads, and alt text that says what it shows. If Wikimedia is down the
#   page loses its pictures and nothing else: the captions and the text
#   say everything the photographs do.
# ----------------------------------------------------------------------

AUTHOR_CSS = """
<style>
.photos { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr));
        gap:1.5rem 1.5rem; margin:1.5rem 0 1.75rem; align-items:start; }
@media (max-width: 900px) { .photos { grid-template-columns:1fr; } }
.photos figure { margin:0; }
.photos img { display:block; width:100%; height:auto; background:#0d0d12;
        border:1px solid var(--rule); color:var(--dim); }
.photos figcaption { color:var(--dim); font-size:0.8125rem; margin-top:0.5rem;
        line-height:1.5; }
.photos .credit { display:block; font-size:0.75rem; margin-top:0.25rem; }
.photonote { color:var(--dim); font-size:0.8125rem; }
</style>"""

_WM = "https://upload.wikimedia.org/wikipedia/commons/"


def _photo(thumb, full_w, full_h, alt, caption, credit):
    """One figure. thumb is the path under /thumb/ up to the filename, or a
    full URL for a picture small enough to use as it is."""
    if thumb.startswith("http"):
        src, srcset = thumb, ""
        w, h = full_w, full_h
    else:
        base = _WM + "thumb/" + thumb
        name = thumb.rsplit("/", 1)[1]
        w, h = 960, round(960 * full_h / full_w)
        src = f"{base}/960px-{name}"
        srcset = (f' srcset="{base}/500px-{name} 500w, {base}/960px-{name} 960w"'
                  ' sizes="(max-width: 900px) 100vw, 34rem"')
    return (f'<figure><img src="{src}"{srcset} width="{w}" height="{h}" '
            f'alt="{html.escape(alt, quote=True)}" loading="lazy" decoding="async" '
            'referrerpolicy="no-referrer">'
            f'<figcaption>{caption}<span class="credit">{credit}</span></figcaption>'
            "</figure>")


AUTHOR_PHOTOS = (
    '<div class="photos">'
    + _photo(
        "5/5f/A_computer_operator_works_at_an_IBM_4381_four-window_work_station_in_a_computer_room_at_the_Arnold_Engineering_Development_Center%2C_where_numerous_mainframe_and_super_computers_are_u_-_DPLA_-_b8ef28c4e9b101b7ccc7f2e5ee1a68ed.jpeg",
        2820, 1880,
        "An operator in a red shirt seated at an IBM 4381 console in 1987. The "
        "screen glows red-orange with several windows of text, and the wall "
        "behind him is lined with reels of magnetic tape.",
        "What the job looked like: an operator at an IBM 4381's console in "
        "1987, at the Arnold Engineering Development Center in Tennessee, with "
        "the reel tape on the wall behind him.",
        'Photo: SMSgt Robert Wickley, US Department of Defense. Public domain. '
        '<a href="https://commons.wikimedia.org/wiki/File:A_computer_operator_works_at_an_IBM_4381_four-window_work_station_in_a_computer_room_at_the_Arnold_Engineering_Development_Center,_where_numerous_mainframe_and_super_computers_are_u_-_DPLA_-_b8ef28c4e9b101b7ccc7f2e5ee1a68ed.jpeg">Wikimedia Commons</a>')
    + _photo(
        "2/27/IBM_4381.jpg", 6000, 3378,
        "A row of tall blue and cream IBM 4381 cabinets in a museum hall, with a "
        "terminal on a stand in front of them.",
        "An IBM 4381, kept at the Technical Museum in Brno.",
        'Photo: <a href="https://commons.wikimedia.org/wiki/User:Shansov.net">[Tycho]</a>, '
        '<a href="https://creativecommons.org/publicdomain/zero/1.0/">CC0</a>. '
        '<a href="https://commons.wikimedia.org/wiki/File:IBM_4381.jpg">Wikimedia Commons</a>')
    + _photo(
        "9/9b/Printer_band.jpg", 1600, 770,
        "A curved steel band carrying rows of raised characters, lying on a sheet "
        "of printed test patterns.",
        "A print band: the loop of engraved characters a band printer is named "
        "for. It spins across the page and hammers strike the paper against it. "
        "This one came out of a Data Products B600.",
        'Photo: Sadg4000, '
        '<a href="https://creativecommons.org/licenses/by/3.0/">CC BY 3.0</a>. '
        '<a href="https://commons.wikimedia.org/wiki/File:Printer_band.jpg">Wikimedia Commons</a>')
    + _photo(
        _WM + "1/1a/IBM_Diskette_1_with_envelope.gif", 627, 600,
        "An IBM Diskette 1, an 8-inch floppy disk half out of its grey paper "
        "sleeve, labelled with its part number and a record length of 128 bytes.",
        "An 8-inch IBM diskette, the size those controllers booted from.",
        'Scan: Crimson Systems. Public domain. '
        '<a href="https://commons.wikimedia.org/wiki/File:IBM_Diskette_1_with_envelope.gif">Wikimedia Commons</a>')
    + "</div>")

AUTHOR = """<h1>About the author</h1>
<p class="lead">Robert Mech. Handles: QuantumRob and Daytona.</p>
""" + AUTHOR_CSS + """
<article>

<p>He built µnleashed BBS and the directory you are reading. The argument for
both is on <a href="/about">What this is</a>; this page is the person.</p>

<h2>On the boards</h2>

<p>In the 1990s he ran Psyberchat, a
<a href="http://www.bbsdocumentary.com/software/IBM/DOS/GTALK/bbs_gtalk_history.html">GTalk</a>
chat system: ten lines, community supported. He frequented God's Country, a
<a href="https://en.wikipedia.org/wiki/Diversi-Dial">DDial</a>, and many other
boards over the years.</p>

<h2>In the machine room</h2>

<p>He started his career in 1989 as a systems operator on an
<a href="https://en.wikipedia.org/wiki/IBM_4300">IBM 4381</a> mainframe. He
worked with DASD, which is what IBM called its disk drives, reel tape drives, a
tape library, two band printers, and network controllers that booted from 8-inch
floppies. If you were in a machine room then, you know the one.</p>

""" + AUTHOR_PHOTOS + """

<h2>After that</h2>

<p>He worked in software development in the healthcare and banking industries,
then moved into delivery leadership and project management, which is the work he
still does today.</p>

<h2>Still at it</h2>

<p>Electronics and programming are still a passion of his. He had the privilege
of meeting <a href="https://en.wikipedia.org/wiki/Ward_Christensen">Ward
Christensen</a> once, at a Maker Faire, before Ward died in October 2024.</p>

<p class="photonote">The photographs load from Wikimedia Commons, so opening this
page asks Wikimedia's servers for them. They are the only thing on this page that
does not come from this server, and they are sent without saying which page
asked.</p>

</article>"""

AUTHOR_DESC = ("Robert Mech, QuantumRob: a GTalk sysop in the 1990s, a mainframe "
               "operator from 1989, and the person who built this.")


ABOUT_DESC =("A bulletin board is a machine that answers a phone number. "
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


def author_page(role):
    """Who wrote this. It belongs to the manifesto, so the menu lights What
    this is: the link that entry is served as on this face, whatever that
    is, rather than a path that only matches on one kind of deployment."""
    return simple_page(f"About the author - {SITE_NAME}", AUTHOR, role,
                       site_url("about", role, "/"), AUTHOR_DESC)


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
        """This page's own address, absolute, on the face it belongs to.

        Filled in at reply time rather than by every page builder, because
        only the request knows the path and the host it came in on, and a
        page is cached once and served on any face. /about and /data are
        pages of their own faces wherever they are asked for."""
        role = role_for(self.headers.get("Host", ""))
        path = self.path.split("?", 1)[0]
        target, p = {"/about": ("about", "/"), "/data": ("data", "/")}.get(path, (role, path))
        url = site_url(target, role, p)
        if url.startswith("http"):
            return url
        dom = {"list": LIST_DOMAIN, "about": ABOUT_DOMAIN, "data": DATA_DOMAIN}.get(role, "")
        base = f"https://{dom}" if dom else SITE_URL.rstrip("/")
        return base + url

    def reply(self, code, body, ctype="text/html; charset=utf-8", extra=None):
        if isinstance(body, str) and "@CANONICAL@" in body:
            body = body.replace("@CANONICAL@", html.escape(self.canonical(), quote=True))
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
                # A filtered view is built for its own request, from the
                # same cached rows, so a thousand different filters cost a
                # thousand renders and not a thousand database reads. The
                # plain list, which is what nearly everybody asks for, is
                # still cached whole.
                sel, any_ = filter_query(self.path.partition("?")[2])
                if sel:
                    self.reply(200, index_page(sel, any_, cached(
                        "indexdata", PAGE_CACHE, index_data)))
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
        # Who wrote it, reached from his name on the manifesto. A route and
        # not a pages/ file, because the dialect has no images and this page
        # is mostly photographs with their credits. On every face, since the
        # link that leads here is relative.
        elif path == "/author":
            self.reply(200, author_page(role))
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
        elif path == "/cover.svg":
            if COVER_SVG is None:
                self.reply(404, "no such file\n", "text/plain; charset=utf-8")
            else:
                self.reply(200, COVER_SVG, "image/svg+xml",
                           {"Cache-Control": "public, max-age=86400"})
        elif path in ("/avatar.png", "/apple-touch-icon.png"):
            blob = AVATAR_PNG if path == "/avatar.png" else TOUCH_PNG
            if blob is None:
                self.reply(404, "no such file\n", "text/plain; charset=utf-8")
            else:
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(blob)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(blob)
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
        # Everything the installer on /install fetches, all of it from
        # here: the vendored ESP Web Tools bundle, and each release's
        # manifest, notices and images. ESP Web Tools fetches the manifest
        # and then each part relative to it, so keeping them under the
        # page's own path and origin is what makes the whole install same
        # origin, with no CORS headers anywhere.
        #
        # Ahead of the generic page branch for the same reason every other
        # real endpoint is: a pages/ file must not be able to shadow it.
        # Nothing is cached in memory; a manifest is a few hundred bytes
        # built from a directory listing, and a binary is fetched once per
        # install rather than once per reader.
        elif path.startswith("/install/"):
            rest = path[len("/install/"):]
            bits = rest.split("/")
            if (len(bits) == 3 and bits[0] == "esp-web-tools"
                    and bits[1] in EWT_PATHS):
                got = ewt_file(bits[2])
            else:
                got = firmware_file(rest)
            if got is None:
                self.reply(404, "no such file\n", "text/plain; charset=utf-8")
            else:
                blob, ctype = got
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(blob)))
                # Immutable, both kinds: a release's bytes never change,
                # because a change is a new version, and the bundle's path
                # carries its version and this site's revision of it
                # (EWT_REV), which goes up when a file in it changes. The
                # manifests name the version they belong to and are just as
                # fixed.
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
