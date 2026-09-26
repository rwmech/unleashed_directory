#!/usr/bin/env python3
"""
===========================================================================
 µnleashed BBS: sitekit
 The page engine shared by the directory and the main site.
===========================================================================

File:         sitekit.py
Module:       Shared page engine

Purpose:      Everything the directory (unleashedbbs.net) and the main
              site (unleashedbbs.com, .org) draw pages with, so the two
              look like one site and cannot drift apart: the page shell and
              its stylesheet, the wordmark, the freedoms beside it, the
              glossary, the small Markdown dialect the pages are written
              in, the drawings' stylesheet and shared drawing helpers, the
              static and font file readers, the page cache, the trusted
              proxy rule for a caller's address, and the reader of the
              firmware folder that the installer offers and the guides'
              gates ask about.

Design:       One file, standard library only, no state beyond a few
              registries an app fills in after importing it:
                - BLOCKS and WRAPS, an app's own ":::" blocks;
                - ART, the drawings an "::: art" block can name;
                - SITE_NAME and SITE_DESC, for titles and link previews.
              Nothing here knows about boards, the database, the
              installer's pages or either app's menu.

              The copy in unleashed_directory is the one that is edited.
              The main site carries a byte-for-byte copy, and its suite
              fails when the copy and its recorded hash disagree, or when
              a directory checkout beside it holds a different one.

              SITEKIT_VERSION goes up with every change to this file.

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

SITEKIT_VERSION = "1.0.0"
import struct

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

# The site's name and its one-line description, for a page's title and
# for a link preview. Each app sets its own after importing this module
# (sitekit.SITE_NAME = ...), because md_meta() reads them from here.
SITE_NAME     = "\u00b5nleashed BBS"
# What a paste of the link says about itself, in a forum, a chat or a search
# result. A directory spreads by somebody pasting it somewhere, and until
# now that paste produced a bare link with no title card at all.
SITE_DESC     = ("Community bulletin boards (BBSes) you can run on a $5 device "
                 "and join with a free app. No ads, no tracking, no platform.")

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
TRUSTED_PROXIES = os.environ.get("DIRECTORY_TRUSTED_PROXIES",
                                 os.environ.get("SITE_TRUSTED_PROXIES", "127.0.0.1,::1"))

# The heartbeats are nothing: a board posts 200 bytes every ten minutes, so
# ten thousand boards is seventeen requests a second. The page is the part
# that could actually be hammered, if somebody links it somewhere busy, so
# it is rendered at most once every PAGE_CACHE seconds and handed out from
# memory in between. A list that changes every few minutes does not need to
# be built fresh for every reader.
PAGE_CACHE    = int(os.environ.get("DIRECTORY_PAGE_CACHE",
                                   os.environ.get("SITE_PAGE_CACHE", "10")))
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
#
# Since the split (2026-09-26) the main site owns the installer and the
# fetcher, and the directory reads the same folder read-only, for the
# update arrow and the "::: from" gates in the guides: on the droplet its
# unit points DIRECTORY_FIRMWARE_DIR at the site's firmware folder. A
# directory with no firmware folder simply has no releases, as before.
FIRMWARE_DIR  = pathlib.Path(os.environ.get(
    "SITE_FIRMWARE_DIR", os.environ.get(
        "DIRECTORY_FIRMWARE_DIR",
        str(pathlib.Path(__file__).resolve().parent / "firmware"))))
# How many releases the page offers, newest first. Rob's figure is two. The
# older ones on disk are simply not listed, so a third left behind by
# accident cannot appear on the page.
FIRMWARE_KEEP = int(os.environ.get("SITE_FIRMWARE_KEEP",
                                   os.environ.get("DIRECTORY_FIRMWARE_KEEP", "2")))

# A release directory is named for its version and nothing else, which is
# what lets firmware/README.md sit beside the releases without being mistaken
# for one. A suffix after a hyphen (1.1.0-dev.8) is a pre-release, the name
# a GitHub pre-release is tagged with (site 1.2.0): a preview, offered only
# for a board no full release carries, and never "the newest release". Its
# parts are letters, digits and hyphens between single dots, so the name is
# one path component and can never be "..".
FIRMWARE_VER  = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,4})"
                           r"(?:-([0-9A-Za-z-]{1,20}(?:\.[0-9A-Za-z-]{1,20}){0,3}))?$")
# A set's folder: the chip, then a board after one hyphen for a second
# board on the same chip ("esp32-fncam", firmware 1.1.0). One path
# component, so never "..".
FIRMWARE_CHIP = re.compile(r"^[a-z][a-z0-9]{2,11}(?:-[a-z0-9]{2,11})?$")
# A family's version.txt: one line, the version exactly as that board shows
# it (SYS, ABOUT, Improv), which the firmware's tools/release.py writes from
# BBS_VERSION_SHOWN. The core version alone for the reference ESP32 ("1.0.3"),
# the core then the board profile's own in brackets for a board with one
# ("1.1.0 (S3 1.0.0)"). Plain ASCII, brackets and not a middle dot, because
# a PETSCII or plain ASCII terminal cannot show one.
FIRMWARE_SHOWN = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,4})(-[0-9A-Za-z.-]{1,40})?"
                            r"(?: \(([A-Za-z0-9][A-Za-z0-9 .-]{0,30})\))?$")

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
    # The Freenove ESP32-WROVER camera board (firmware 1.1.0): a second image
    # set on the ESP32's chip family, so ESP Web Tools cannot choose between
    # it and the dev board's by reading the chip. The picker asks instead.
    "esp32-fncam": ("ESP32", 0x1000),
    # The ESP32-CAM, AI-Thinker's design (ESPCAM 1.0.1, a pre-release first,
    # site 1.3.5): the ESP32's chip family again, a third set on it.
    "esp32-cam": ("ESP32", 0x1000),
    "esp32s2": ("ESP32-S2", 0x1000),
    "esp32s3": ("ESP32-S3", 0x0),
    # The Makerfabs ESP32-S3 Parallel TFT 3.5", hardware v1.0 (MF35 1.0.0,
    # a board pre-release first, site 1.3.17): the S3's chip family again,
    # a second set on it, laid out on the same 4 MB as the Waveshare's. Its
    # PSRAM is quad where the Waveshare's is octal, so each image refuses to
    # boot on the other board, and the installer cannot tell them apart.
    "esp32s3-mf35": ("ESP32-S3", 0x0),
    "esp32c3": ("ESP32-C3", 0x0),
}

# What gets written, and where. Where comes from each image set's OWN
# partition table, its partitions.bin, and never from a table in this file
# (firmware 1.1.2, Rob: the S3 has its own 8 MB layout, with the app slots
# at 3 MB and the screens at 0x780000, while the ESP32 keeps its 4 MB one
# with the screens at 0x3C0000; one global table would write an S3's
# screens into the middle of its second app slot).
#
# The five parts, and what places each:
#   bootloader.bin        the chip family's bootloader offset (FLASH_FAMILIES)
#   partitions.bin        the partition table's own offset, 0x8000
#                         (CONFIG_PARTITION_TABLE_OFFSET, the same on every
#                         board this site offers)
#   ota_data_initial.bin  the table's otadata partition, in its starting
#                         state, which says "boot the first app slot":
#                         firmware.bin always goes into that first slot
#   firmware.bin          the table's first app partition (ota_0)
#   storage.bin           the table's "storage" partition, the screens
#                         (PlatformIO's littlefs.bin, named for its
#                         partition)
#
# The other two filesystems, userdata (accounts, the live configuration,
# each plugin's files) and logs (the caller log), are deliberately never
# written: that is what lets somebody reinstall over a board they already
# run without losing it. After a full erase the board formats both.
#
# A set whose table cannot be read, or has no otadata, no app or no
# storage partition, or whose firmware.bin or storage.bin would not fit the
# partition it is written to, is not offered at all: better nothing than a
# part written somewhere it does not belong.
FLASH_PARTS = ("bootloader.bin", "partitions.bin", "ota_data_initial.bin",
               "firmware.bin", "storage.bin")
PT_OFFSET = 0x8000
PT_MAX    = 0xC00       # the table's own partition is 3 KB


def partition_table(path):
    """The partition table in a partitions.bin, as {label: {"type",
    "subtype", "offset", "size"}} in table order, or None when it is not
    one. The format is ESP-IDF's (gen_esp32part.py): 32-byte entries, each
    the magic 0xAA50 (bytes AA 50), a type byte, a subtype byte, the offset
    and the size as little-endian 32-bit numbers at bytes 4 and 8, and a
    16-byte label at byte 12; the table ends at an MD5 entry (EB EB) or at
    erased flash (FF FF)."""
    try:
        raw = pathlib.Path(path).read_bytes()[:PT_MAX]
    except OSError:
        return None
    table = {}
    for at in range(0, len(raw) - 31, 32):
        entry = raw[at:at + 32]
        if entry[:2] != b"\xaa\x50":
            break
        offset, size = struct.unpack_from("<II", entry, 4)
        label = entry[12:28].split(b"\0", 1)[0].decode("ascii", "replace")
        table[label] = {"type": entry[2], "subtype": entry[3],
                        "offset": offset, "size": size}
    return table or None


def set_layout(folder, boot):
    """{part name: (offset, the most it may be)} for one image set, from its
    own partitions.bin, or None when the set cannot be placed."""
    table = partition_table(pathlib.Path(folder) / "partitions.bin")
    if not table:
        return None
    rows = list(table.values())
    app = next((p for p in rows if p["type"] == 0x00 and p["subtype"] in (0x10, 0x00)), None)
    otadata = next((p for p in rows if p["type"] == 0x01 and p["subtype"] == 0x00), None)
    storage = table.get("storage")
    if not (app and otadata and storage and storage["type"] == 0x01):
        return None
    return {"bootloader.bin": (boot, PT_OFFSET - boot),
            "partitions.bin": (PT_OFFSET, PT_MAX),
            "ota_data_initial.bin": (otadata["offset"], otadata["size"]),
            "firmware.bin": (app["offset"], app["size"]),
            "storage.bin": (storage["offset"], storage["size"])}

# How each image set is offered before its first release (site 1.2.9,
# 1.3.7): True, the default, offers the newest preview until a release
# carries the board; False waits for a release; "ahead" waits too, and
# once released is also offered a newer preview first. This was each
# BOARDS entry's "previews" key; it is here since the split so the
# directory answers the guides' board gates the way /install does. The
# site's suite fails if the two disagree.
BOARD_PREVIEWS = {"esp32-fncam": "ahead"}


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
# "::: from|until" takes a version, or since site 1.3.5 a board's image set
# folder ("esp32-cam"), the same shape FIRMWARE_CHIP allows.
_MD_GATE   = re.compile(r"^::: (from|until) (?:(\d+)\.(\d+)\.(\d+)|"
                        r"([a-z][a-z0-9]{2,11}(?:-[a-z0-9]{2,11})?)"
                        r"(?: (\d+)\.(\d+)\.(\d+))?)\s*$")


# --------------------------------------------------------------------------
# The glossary (site 1.3.0, Rob: "we need to bridge them into the lingo for
# BBSes ... even have those pop-ups with dotted underline for terms").
#
# A BBS word keeps its place on the page and is explained where a newcomer
# first meets it: a dotted underline, and a one-line definition that shows
# on hover, on keyboard focus and on a tap (a tap focuses it). One table,
# so a term is always explained in the same words, and each page marks the
# first use it wants explained, in Markdown as [[sysop]] and in this file
# with gl("sysop"). The words inside the brackets are what shows, so a
# plural or another form is written as it reads ([[callers]], [[flashing]])
# and GLOSSARY_FORMS finds its entry. No "|" form, so a term can sit in a
# table cell.
#
# No script and no title attribute, for the badges' reason: title draws
# the browser's own tooltip over ours on a desktop and nothing on a phone.
# The definition is a span inside the term, display:none until wanted, and
# the term points at it with aria-describedby, which a screen reader reads
# even while it is hidden. A term that is not in the table renders as its
# words alone, and the suite fails on one in any page.
# --------------------------------------------------------------------------
GLOSSARY = {
    "BBS": "A bulletin board system: a small online community on one "
           "computer, which people connect to from theirs to chat, leave "
           "messages and share files.",
    "board": "Short for bulletin board, a BBS. On this site, one µnleashed "
             "device and the community that meets on it.",
    "sysop": "The system operator: the host who runs a board, sets its "
             "rules and looks after it.",
    "caller": "Someone connected to a board: a visitor or a member. The word "
              "is from the days when you phoned a board to reach it.",
    "telnet": "The plain way of connecting to a board over a network. It is "
              "not encrypted, so what you type could be read on the way.",
    "telnet client": "A free app for joining a board: it connects to the "
                     "board's address and shows its screens.",
    "terminal": "What you type into a board from: a telnet client on a "
                "phone or PC, an old computer, or a real terminal.",
    "door": "A game or program that a board hands you over to, and brings "
            "you back from when you finish.",
    "ANSI": "The colour and line-drawing codes that PC boards use to draw "
            "their screens.",
    "PETSCII": "The Commodore computers' own character set, with its block "
               "graphics. The board speaks it natively.",
    "flashing": "Writing the software onto the board's chip over a USB "
                "cable. Here your browser does it for you.",
    "firmware": "The software that lives on the board's chip. µnleashed is "
                "firmware: the board runs nothing else.",
    "port forwarding": "A router setting that lets people outside your home "
                       "reach one device inside it, on one numbered port.",
    "handle": "The nickname you use on a board.",
    # Site 1.3.1: SSH is coming on the S3 boards, and the words that say so
    # need it explained where a newcomer meets them.
    "SSH": "An encrypted way of connecting to a board, beside telnet: what "
           "you type is scrambled on the way, so only the board can read it.",
    # Site 1.3.4: choosing a camera board, in plain words.
    "sensor": "The chip in a camera that turns light into a picture. How "
              "many dots it has sets the largest photo it can take.",
    "megapixel": "A million pixels, the dots a photo is made of. A "
                 "2 megapixel photo is about 1600 dots across and 1200 down.",
    "PSRAM": "A second memory chip beside the processor: slower than the "
             "chip's own memory, and far larger.",
}
# Other ways a term is written on a page, lower case, to its entry.
GLOSSARY_FORMS = {
    "bbses": "BBS", "bulletin board": "BBS", "bulletin boards": "BBS",
    "bulletin board system": "BBS", "boards": "board",
    "sysops": "sysop", "callers": "caller",
    "telnet clients": "telnet client", "terminals": "terminal",
    "terminal software": "terminal",
    "doors": "door", "door games": "door",
    "flash": "flashing", "flashed": "flashing", "flash it": "flashing",
    "forward a port": "port forwarding", "forwarding a port": "port forwarding",
    "forward one port": "port forwarding",
    "handles": "handle",
    "sensors": "sensor", "megapixels": "megapixel",
}
_GL_SEQ = itertools.count(1)
_MD_GLOSS = re.compile(r"\[\[([^\[\]|]{1,40})\]\]")


def gloss_key(words):
    """The GLOSSARY entry a written form belongs to, or None."""
    w = " ".join(words.split())
    for key in GLOSSARY:
        if key.lower() == w.lower():
            return key
    return GLOSSARY_FORMS.get(w.lower())


def gl(words, tid=None):
    """A term as it reads on the page, with its definition to hand. The
    words are escaped here; a term not in GLOSSARY is the words alone.
    tid names the tooltip for markup that must render the same every time
    (a board's facts, site 1.3.3); otherwise it is numbered."""
    key = gloss_key(words)
    shown = html.escape(words)
    if key is None:
        return shown
    tid = tid or f"gl{next(_GL_SEQ)}"
    return (f'<span class="gl" tabindex="0" aria-describedby="{tid}">{shown}'
            f'<span class="gt" role="tooltip" id="{tid}">'
            f"{html.escape(GLOSSARY[key])}</span></span>")


def md_inline(s):
    """Escape first, then the handful of inline forms we allow."""
    s = html.escape(s)
    s = _MD_CODE.sub(lambda m: f"<code>{m.group(1)}</code>", s)
    s = _MD_BOLD.sub(lambda m: f"<b>{m.group(1)}</b>", s)
    s = _MD_ITAL.sub(lambda m: f"<i>{m.group(1)}</i>", s)
    # The glossary, before links, so a term never ends up inside one. The
    # words are already escaped, so they are unescaped once before gl()
    # escapes them again.
    s = _MD_GLOSS.sub(lambda m: gl(html.unescape(m.group(1))), s)

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
# Every ":::" block the engine itself knows. An app adds its own to
# BLOCKS (name -> function taking the block's lines, returning HTML), and
# wrapping blocks that hold other blocks, such as the site's
# "::: install-top", to WRAPS. "art" is a drawing by name, from ART;
# "cta" is a page's one primary action; "next" a section's next step.
# An unknown name after ":::" renders as a paragraph, so a typo shows.
BLOCK_NAMES = CARD_BLOCKS + ("art", "cta", "next")
BLOCKS = {}
WRAPS = {}


def block_known(name):
    """Whether a ":::" name opens a block this page can render."""
    return name in BLOCK_NAMES or name in BLOCKS


def md_block(kind, lines):
    """A ":::" block, by name: a drawing, a button or two, an app's own
    block from BLOCKS, or cards."""
    if kind == "art":
        return art_html(lines)
    if kind == "cta":
        return cta_html(lines)
    if kind == "next":
        return next_html(lines)
    fn = BLOCKS.get(kind)
    if fn is not None:
        return fn(lines)
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
# A section's next step, as a button (site 1.2.2, Rob: "Need clearer calls
# to action. The blue blends in").
#
#     ::: next
#     [Choose a board](/hardware)
#     :::
#
# A body link is --dial on --ink, 1.02:1 apart in luminance, so a link that
# IS the thing to do next read as one more word in the paragraph. This is
# the cta's outlined button at a section's size: one or two lines that are a
# link and nothing else, each a button, and nothing else in the block. One a
# section at most, and only where the link is what a reader does next; a
# reference stays a link in the sentence. Class "go", not "btn2", because
# the page's one cta pair is counted by that name.
# --------------------------------------------------------------------------
def next_html(lines):
    """The ::: next block: one or two outlined buttons, nothing else."""
    links = []
    for ln in (l.strip() for l in lines):
        m = _MD_LONE_LINK.match(ln)
        if m and len(links) < 2 and m.group(2).startswith(("/", "#", "https://")):
            links.append(f'<a class="go" href="{html.escape(m.group(2), quote=True)}">'
                         f"{md_inline(m.group(1))}</a>")
    return '<p class="next">' + "".join(links) + "</p>" if links else ""


def art_html(lines):
    """The drawings an "::: art" block names, one per line.

    A name that is not in ART prints as a paragraph, the same rule an
    unknown ":::" block follows: a typo should be visible on the page, not
    a hole where a drawing was meant to be.
    """
    out = []
    for line in (ln.strip() for ln in lines):
        if not line:
            continue
        # A line "#anchor" (site 1.3.15) is an empty anchor where it stands,
        # so a page can link into a numbered list the drawings already
        # break up: /install's guide links its Wi-Fi step to the line after
        # the drawing of the first start, which is where the Wi-Fi item
        # begins. Nothing is drawn for it.
        if re.fullmatch(r"#[a-z0-9-]+", line):
            out.append(f'<span class="anchor" id="{line[1:]}"></span>')
            continue
        out.append(ART.get(line) or "<p>" + html.escape("art: " + line) + "</p>")
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
        # "::: from esp32-cam" (site 1.3.5) gates on a board rather than a
        # release: rendered once the installer offers that board anything,
        # a preview included, which a version gate can never see because a
        # preview never lights one. "::: until esp32-cam" is its other half.
        # "::: from esp32-fncam 1.1.1" (site 1.3.7) gates on a board and a
        # version together: rendered once the installer offers that board
        # something at that version or later, a preview included, so a
        # board's own preview can switch its prose a release early.
        if gate is not None:
            if line.startswith("::: "):
                gate[1] += 1
            elif line.strip() == ":::":
                if gate[1] == 0:
                    if isinstance(gate[0], list):
                        offered = board_offers(gate[0][0])
                        reached = (bool(offered) if gate[0][1] is None else
                                   any(r["sort"] >= gate[0][1] for r in offered))
                    else:
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
            want = ([m.group(5), tuple(int(g) for g in m.groups()[5:8])
                     if m.group(6) else None] if m.group(5)
                    else tuple(int(g) for g in m.groups()[1:4]))
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
                    out.append(WRAPS[beside[2]](beside[1]))
                    beside = None
                    continue
                beside[0] -= 1
            beside[1].append(raw)
            continue
        if (code is None and card is None and line.strip().startswith("::: ")
                and line.strip()[4:] in WRAPS):
            beside = [0, [], line.strip()[4:]]
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
                # "```nowrap" (site 1.2.1): lines that must not break inside
                # a word, such as a URL to clone, scroll sideways on a phone
                # instead of wrapping. Everything else still wraps there.
                cls = ' class="nowrap"' if code_nowrap else ""
                out.append(f"<pre{cls}>" + html.escape("\n".join(code)) + "</pre>")
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

        if line.startswith("::: ") and block_known(line[4:].strip()):
            flush()
            card = (line[4:].strip(), [])
            # An unknown name after ":::" deliberately does not match, so it
            # falls through and renders as an ordinary paragraph. A typo is
            # then visible on the page instead of silently swallowing the
            # rest of it.
        elif line.startswith("```"):
            flush()
            code = []
            code_nowrap = line[3:].strip() == "nowrap"
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
        out.append(WRAPS[beside[2]](beside[1]))
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
                desc = re.sub(r"[*`]|\[|\]\]|\]\([^)]*\)", "", line)[:180]
                break
    return title, desc


STATIC_DIR = pathlib.Path(__file__).resolve().parent / "static"
STATIC_OK  = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
STATIC_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".webp": "image/webp", ".gif": "image/gif", ".svg": "image/svg+xml"}

# The display face for the front page's pitch (site 1.2.9, Rob: "slightly
# larger, different font (I love technical/scifi looking google fonts)").
# Served from here, never from Google: the site depends on no third-party
# host, for readers' privacy and because a Pi-hole would block it. Three
# faces from github.com/google/fonts, each under the SIL Open Font Licence
# 1.1. Oxanium (500) and Chakra Petch (Medium) are subset to Basic Latin and
# Latin-1 (the micro sign included) at one weight, as WOFF, about 11 KB
# each: neither reserves its name, so a subset may keep it. Orbitron's
# licence reserves the name "Orbitron", and a subset is a Modified Version
# under the OFL, which may not carry a Reserved Font Name, so Orbitron is
# the upstream file exactly as published (Orbitron[wght].ttf, 38 KB).
# Each one's OFL.txt sits beside it in static/fonts/, and
# THIRD_PARTY_NOTICES.md names all three. PITCH_FONT picks the one the page
# uses; the other two are kept so the choice is a one-word change.
# DIRECTORY_PITCH_FONT overrides it, for comparing them side by side.
FONT_DIR = pathlib.Path(__file__).resolve().parent / "static" / "fonts"
FONT_TYPES = {".woff": "font/woff", ".ttf": "font/ttf",
              ".txt": "text/plain; charset=utf-8"}
PITCH_FONTS = {"oxanium": ("Oxanium-latin.woff", 500),
               "chakrapetch": ("ChakraPetch-latin.woff", 500),
               "orbitron": ("Orbitron.ttf", 500)}
PITCH_FONT = os.environ.get("SITE_PITCH_FONT",
                            os.environ.get("DIRECTORY_PITCH_FONT", "oxanium"))
if PITCH_FONT not in PITCH_FONTS:
    PITCH_FONT = "oxanium"


def font_file(name):
    """One file from static/fonts/, a face or its licence, or None, by the
    same name check as static_file()."""
    return static_file(name, FONT_DIR, FONT_TYPES)


# Card art lives in its own folder rather than in static/, for two reasons.
# gallery_html() shows everything in static/ on the manifesto page, and
# blocky card art has no business in a gallery of photographs of real
# hardware; iterdir() skips a subdirectory on its own because it is not a
# file, so this needs no change there. And keeping it separate means the
# name check below is reused exactly as it is against a different base,
# rather than being loosened to understand a path, which is the change that
# would actually be worth getting wrong.
PIX_DIR = pathlib.Path(__file__).resolve().parent / "static" / "kids"


def static_file(name, base=None, types=None):
    """One file from static/, or None. Names are checked rather than paths:
    no directories, no dots to climb with, nothing but a plain filename."""
    types = types or STATIC_TYPES
    if not STATIC_OK.match(name or ""):
        return None
    ext = pathlib.Path(name).suffix.lower()
    if ext not in types:
        return None
    f = (base or STATIC_DIR) / name
    if not f.is_file():
        return None
    return f.read_bytes(), types[ext]


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

    A family is offered only when every part in FLASH_PARTS is present, its
    partitions.bin places every one, and each fits where it goes. A
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
        # Where each part goes is this set's own partition table's to say,
        # and how much room it has there (firmware 1.1.2: the S3's layout is
        # not the ESP32's).
        layout = set_layout(vdir / chip, boot)
        if layout is None:
            continue
        parts = []
        for name in FLASH_PARTS:
            f = vdir / chip / name
            if (not f.is_file() or f.stat().st_size == 0
                    or f.stat().st_size > layout[name][1]):
                parts = None
                break
            # Relative to the manifest's own URL, which is what ESP Web
            # Tools resolves a part against. Keeping them relative means the
            # binaries are reached on whatever domain the manifest was
            # fetched from, so this needs no knowledge of the site's name
            # and no CORS headers anywhere.
            parts.append({"path": name, "offset": layout[name][0]})
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
    mode = BOARD_PREVIEWS.get(chip, True)
    if full:
        # A board marked "previews": "ahead" (the Freenove, site 1.3.7) is
        # offered the newest preview carrying it that is newer than its
        # newest release, first, with that release beside it as the way
        # back. Every other board with a release is offered releases only.
        if mode == "ahead":
            pre = [r for r in every if r["pre"] and chip in r["sets"]
                   and r["key"] > full[0]["key"]][:1]
            return (pre + full)[:FIRMWARE_KEEP]
        return full[:FIRMWARE_KEEP]
    # A board marked "previews": False or "ahead" waits for a release and
    # is never offered a preview before one (the Freenove, Rob: nothing of
    # it shows before 1.1.0).
    if mode is not True:
        return []
    return [r for r in every if r["pre"] and chip in r["sets"]][:1]


# --------------------------------------------------------------------------
# The web page. Dark, monospace, the same colours as the board.
# --------------------------------------------------------------------------
PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="{desc}">
<meta property="og:site_name" content="@SITE_NAME@">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{desc}">
<meta property="og:type" content="website">
<meta property="og:url" content="@CANONICAL@">
<link rel="canonical" href="@CANONICAL@">
<meta property="og:image" content="@OG_CARD_URL@">
<meta property="og:image:type" content="image/png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:image:alt" content="@OG_CARD_ALT@">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="@OG_CARD_URL@">
<meta name="twitter:image:alt" content="@OG_CARD_ALT@">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
{refresh}<link rel="alternate" type="application/rss+xml" title="New boards" href="@FEED_URL@">
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
@PITCH_FACE@
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
/* The wordmark, drawn from LOGO_ROWS as an SVG (site 1.2.1). It was the
   same rows as half-block text in a <pre>, and on a phone the font's line
   gaps showed through as stripes and its size was the font's guess. As a
   drawing it has no gaps, is sharp at any density, and its width is set
   here: the width 62 cells of 0.6em at 0.9375rem made, 35rem, and never
   more than the column on a phone. */
svg.logo {{ display:block; width:min(35rem, calc(100vw - 2.5rem)); height:auto;
       margin:0 0 0.375rem; }}
/* The wordmark and the freedoms panel share one row. flex-wrap is the
   safety net rather than the plan: the panel only appears at a width where
   it fits (below), so it should never need to wrap, and if some font the
   stack lands on is wider than measured, wrapping is what happens instead
   of the header running off the side of the page. */
.masthead {{ display:flex; flex-wrap:wrap; align-items:flex-start; gap:0 1.5rem; }}
.masthead svg.logo {{ flex:none; }}
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
/* Ten freedoms, four seconds each (eight until site 1.3.0). Every item
   runs the same 40 second timeline and starts four seconds after the one
   before it. The change is
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
  .ticker li {{ opacity:0; animation:tkshow 40s linear infinite both; }}
  .tf .sg {{ animation:tkseg 40s linear infinite both; }}
  .ticker li:nth-child(1), .tf .sg1 {{ animation-delay:-0.6s; }}
  .ticker li:nth-child(2), .tf .sg2 {{ animation-delay:3.4s; }}
  .ticker li:nth-child(3), .tf .sg3 {{ animation-delay:7.4s; }}
  .ticker li:nth-child(4), .tf .sg4 {{ animation-delay:11.4s; }}
  .ticker li:nth-child(5), .tf .sg5 {{ animation-delay:15.4s; }}
  .ticker li:nth-child(6), .tf .sg6 {{ animation-delay:19.4s; }}
  .ticker li:nth-child(7), .tf .sg7 {{ animation-delay:23.4s; }}
  .ticker li:nth-child(8), .tf .sg8 {{ animation-delay:27.4s; }}
  .ticker li:nth-child(9), .tf .sg9 {{ animation-delay:31.4s; }}
  .ticker li:nth-child(10), .tf .sg10 {{ animation-delay:35.4s; }}
  .tf .ct {{ animation:tkcaret 4s linear -0.6s infinite; }}
  .tf .sc {{ animation:tkscan 2.6s ease-in-out infinite; }}
  @keyframes tkshow {{
    0%, 0.75% {{ opacity:0; }}  1.5%, 10% {{ opacity:1; }}
    10.75%, 100% {{ opacity:0; }}
  }}
  @keyframes tkseg {{
    0%, 0.75% {{ opacity:0.2; }}  1.5%, 10% {{ opacity:1; }}
    10.75%, 100% {{ opacity:0.2; }}
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
/* Site 1.3.0: the labels say what a newcomer will do ("Communities online",
   "Apps for joining"), 21 characters longer in all, so the cell's sides
   went from 0.75 to 0.5rem and the letter-spacing halved to keep the menu
   one row at 1366 (measured in Consolas; Menlo, a little wider, wraps
   there and fits at 1440). The height, and so the tap target, is as it
   was. */
nav a {{ color:var(--dim); text-decoration:none; font-size:0.75rem;
        letter-spacing:0.03125rem; text-transform:uppercase; padding:0.6875rem 0.5rem;
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
/* The glossary (site 1.3.0): a BBS word with a dotted underline, and its
   one-line definition under it on hover, on focus and on a tap. The
   definition is in the markup and display:none until wanted, so it costs
   no layout; aria-describedby reads it to a screen reader either way.
   From the breakpoint down it is a bar fixed across the foot of the
   screen, because a box hanging from a word near the right edge of a phone
   would run off it. Hover lives inside the fine-pointer query, so a tap
   cannot leave one showing; focus is what a tap gives, and it clears when
   the reader taps anywhere else. */
.gl {{ position:relative; border-bottom:1px dotted currentColor; cursor:help; }}
.gl:focus {{ outline:none; }}
.gl:focus-visible {{ outline:3px solid #ffd35c; outline-offset:2px; }}
.gl .gt {{ display:none; position:absolute; left:0; top:100%; z-index:20;
       margin-top:0.375rem; width:max-content; max-width:18rem; padding:0.5rem 0.75rem;
       background:#15151d; border:1px solid #4a7a99; border-radius:0.375rem;
       color:var(--ink); font-size:0.75rem; line-height:1.5; font-weight:normal;
       font-style:normal; letter-spacing:0; text-transform:none; text-align:left;
       white-space:normal; box-shadow:0 0.25rem 1rem rgba(0, 0, 0, 0.6); }}
.gl:focus .gt {{ display:block; }}
@media (hover: hover) and (pointer: fine) {{
  .gl:hover .gt {{ display:block; }}
}}
@media (max-width: 900px) {{
  .gl .gt {{ position:fixed; left:1rem; right:1rem; top:auto; bottom:1rem;
         width:auto; max-width:none; margin:0; }}
}}
/* The board list's figures, as a sentence under its heading rather than a
   run of small faint numbers beside it: "Unleashed is hosting 3 boards
   with 5 callers on right now." The two figures are --live, the colour
   that means up; they are the product, and they are the only colour in
   the line. */
p.stat {{ color:var(--ink); margin:0 0 0.5rem; }}
p.stat .n {{ color:var(--live); }}
/* /directory's search: the badge search's box and label, with a button in
   the Filter button's outline, and under it a line saying what it found. */
.findbar.bsearch {{ max-width:36rem; margin:0 0 0.75rem; }}
.bsearch button {{ font:inherit; font-size:0.75rem; letter-spacing:0.0625rem;
        text-transform:uppercase; color:var(--dial); background:transparent;
        border:1px solid #35566b; border-radius:0.375rem; min-height:2.125rem;
        padding:0.25rem 0.875rem; cursor:pointer; }}
.bsearch button:hover {{ border-color:var(--dial); }}
.bsearch button:focus-visible {{ outline:3px solid #ffd35c; outline-offset:2px; }}
p.qline {{ color:var(--dim); font-size:0.8125rem; margin:-0.25rem 0 0.75rem; }}
/* On a phone the label takes its own line, so the box and its button share
   the next one rather than the button dropping under the box alone. */
@media (max-width: 900px) {{
  .bsearch label {{ flex-basis:100%; }}
}}
p.qline a:focus-visible {{ outline:3px solid #ffd35c; outline-offset:2px; }}
/* The front page (site 1.3.0, Rob's approved round 3 mockup): the pitch,
   and nothing else. The board list moved to /directory. Six sections, each
   under a hairline in --rule: the hero (a kicker, the headline in PITCH_FONT,
   the sub-head, two buttons, a line of facts, and the drawing of the board
   beside it), what it is, who builds one, three steps, the history, and a
   closing band with the two buttons again. From the one breakpoint down
   everything is one column in reading order: the drawing follows the
   buttons, the timeline follows its paragraph. */
.front {{ margin:0.5rem 0 0; }}
.front section {{ padding:2.25rem 0; border-top:1px solid var(--rule); }}
.front section.hero {{ border-top:0; padding-top:1rem; display:grid;
        grid-template-columns:minmax(0, 1fr) 22rem; column-gap:2.5rem; align-items:center; }}
.front h2.sec {{ font-family:"Pitch",ui-monospace,Menlo,Consolas,monospace; font-weight:500;
        color:#eeeaf8; font-size:1.375rem; letter-spacing:0.005em; text-transform:none;
        margin:0 0 0.375rem; }}
.front p.seclead {{ color:var(--dim); font-size:0.8125rem; margin:0 0 1.125rem; max-width:44rem; }}
.front p.kicker {{ color:var(--struct); text-transform:uppercase; letter-spacing:0.14em;
        font-size:0.6875rem; margin:0 0 0.75rem; }}
/* Site 1.3.1: the second phrase is a link to where it is backed, drawn in
   the kicker's own colour with a dotted rule so it stays one line of type. */
.front p.kicker a {{ color:inherit; text-decoration:underline dotted; text-underline-offset:0.25em; }}
.front p.kicker a:hover {{ color:var(--dial); }}
.front p.kicker a:focus-visible {{ outline:3px solid #ffd35c; outline-offset:2px; }}
@media (max-width: 900px) {{
  .front p.kicker .k2 {{ display:block; margin-top:0.375rem; }}
  .front p.kicker .kd {{ display:none; }}
}}
.front h1.hero {{ font-family:"Pitch",ui-monospace,Menlo,Consolas,monospace; font-weight:500;
        color:#eeeaf8; font-size:2.375rem; line-height:1.15; letter-spacing:0.005em;
        text-transform:none; margin:0 0 0.875rem; }}
.front h1.hero em {{ font-style:normal; color:var(--dial); }}
.front p.sub {{ color:var(--ink); font-size:0.9375rem; line-height:1.6; margin:0; max-width:44rem; }}
.front p.btns {{ display:flex; flex-wrap:wrap; gap:0.75rem; margin:1.375rem 0 0; }}
.front a.b1, .front a.b2 {{ font-size:0.875rem; border-radius:0.375rem;
        padding:0.625rem 1.25rem; text-decoration:none; text-align:center; }}
.front a.b1 {{ color:#04212c; background:var(--dial); border:1px solid #9fdfff; }}
.front a.b1:hover {{ background:#a7e2ff; }}
.front a.b2 {{ color:var(--dial); border:1px solid #4a7a99; background:rgba(127, 212, 255, 0.06); }}
.front a.b2:hover {{ border-color:var(--dial); }}
.front a.b1:focus-visible, .front a.b2:focus-visible {{ outline:3px solid #ffd35c; outline-offset:2px; }}
.front p.facts {{ color:var(--faint); font-size:0.6875rem; letter-spacing:0.06em; margin:0.875rem 0 0; }}
.front p.facts b {{ color:var(--dim); font-weight:normal; }}
/* The quiet way on under the buttons (site 1.3.10): the site's own link,
   a little smaller than the buttons' words, lined up with them on the left,
   and on a phone centred under the two full width buttons. The padding
   makes it a tap target without making it look like one. */
.front p.diff {{ font-size:0.8125rem; margin:0.625rem 0 0; }}
.front p.diff a {{ display:inline-block; padding:0.25rem 0; }}
.front p.diff a:focus-visible {{ outline:3px solid #ffd35c; outline-offset:2px; }}
.front figure.board {{ margin:0; text-align:center; }}
.front figure.board svg {{ width:100%; height:auto; max-width:22rem; }}
.front figure.board figcaption {{ color:var(--faint); font-size:0.625rem; margin:0.5rem 0 0; }}
.front .fcards {{ display:grid; gap:0.875rem; grid-template-columns:repeat(3, minmax(0, 1fr)); }}
.front .fcard {{ border:1px solid #23232e; border-top:2px solid var(--fc, var(--struct));
        background:rgba(255, 255, 255, 0.02); border-radius:0.375rem; padding:0.875rem 1rem 1rem; }}
.front .fcard h3 {{ color:#e6e6ee; font-size:0.875rem; font-weight:600; margin:0 0 0.375rem;
        text-transform:none; letter-spacing:0; }}
.front .fcard p {{ color:var(--dim); font-size:0.75rem; line-height:1.55; margin:0; }}
.front .c1 {{ --fc:var(--struct); }} .front .c2 {{ --fc:var(--dial); }} .front .c3 {{ --fc:var(--name); }}
.front .c4 {{ --fc:var(--warm); }} .front .c5 {{ --fc:var(--live); }} .front .c6 {{ --fc:var(--busy); }}
.front .fcard p.eg {{ color:var(--fc); font-size:0.625rem; letter-spacing:0.12em;
        text-transform:uppercase; margin:0 0 0.375rem; }}
.front ol.fsteps {{ list-style:none; padding:0; margin:0; display:grid; gap:0.875rem;
        grid-template-columns:repeat(3, minmax(0, 1fr)); }}
.front ol.fsteps li {{ position:relative; padding:0.25rem 0 0 3.25rem; }}
.front ol.fsteps .n {{ position:absolute; left:0; top:0; font-family:"Pitch",ui-monospace,Menlo,Consolas,monospace;
        font-weight:500; font-size:2rem; line-height:1; color:var(--dial); }}
.front ol.fsteps h3 {{ color:#e6e6ee; font-size:0.9375rem; font-weight:600; margin:0.25rem 0 0.375rem;
        text-transform:none; letter-spacing:0; }}
.front ol.fsteps p {{ color:var(--dim); font-size:0.75rem; line-height:1.55; margin:0; }}
.front section.then {{ display:grid; grid-template-columns:minmax(0, 1fr) 20rem;
        column-gap:2.5rem; align-items:center; }}
.front section.then p {{ color:var(--ink); font-size:0.8125rem; line-height:1.65;
        margin:0 0 0.75rem; max-width:44rem; }}
.front section.then p.mut {{ color:var(--dim); }}
.front .crt {{ border:1px solid #2c2c38; border-radius:0.75rem; padding:0.875rem 1rem;
        background:#07070a; box-shadow:inset 0 0 1.5rem rgba(127, 212, 255, 0.06); }}
.front .crt dl {{ margin:0; font-size:0.6875rem; line-height:1.5; color:var(--dim);
        display:grid; grid-template-columns:auto minmax(0, 1fr); gap:0.625rem 0.75rem; }}
.front .crt dt {{ color:var(--struct); }}
.front .crt dd {{ margin:0; }}
.front .crt i {{ color:var(--warm); font-style:normal; }}
.front .crt p.cap {{ color:var(--faint); font-size:0.5625rem; letter-spacing:0.1em;
        text-transform:uppercase; margin:0.625rem 0 0; }}
.front section.end {{ text-align:center; }}
.front section.end h2.sec {{ font-size:1.625rem; }}
.front section.end p.seclead {{ margin-left:auto; margin-right:auto; }}
.front section.end p.btns {{ justify-content:center; }}
.front section.end p.dev {{ color:var(--faint); font-size:0.6875rem; margin:1rem 0 0; }}
.front section.end p.dev a {{ color:var(--dim); }}
@media (max-width: 900px) {{
  .front section {{ padding:1.75rem 0; }}
  .front section.hero, .front section.then {{ display:block; }}
  .front h1.hero {{ font-size:1.75rem; }}
  .front p.sub {{ font-size:0.875rem; }}
  .front figure.board {{ margin:1.5rem 0 0; }}
  .front figure.board svg {{ max-width:16rem; }}
  .front .fcards, .front ol.fsteps {{ grid-template-columns:1fr; gap:0.625rem; }}
  .front ol.fsteps li {{ padding-left:2.75rem; }}
  .front .crt {{ margin:1rem 0 0; }}
  .front p.btns a {{ flex:1 1 100%; }}
  .front p.diff {{ text-align:center; margin-top:0.75rem; }}
  .front p.diff a {{ padding:0.5rem 0; }}
}}
/* /directory's first step for somebody who has never joined a board: the
   app to use, in one box, before the search and the list (site 1.3.0).
   The quiet blue of the aside, not the amber of a warning. */
.joinstep {{ border:1px solid #35566b; background:rgba(127, 212, 255, 0.06);
        border-radius:0.5rem; padding:0.875rem 1.125rem; margin:0 0 1.25rem; max-width:48rem; }}
.joinstep h2 {{ color:var(--struct); font-size:0.875rem; font-weight:normal; margin:0 0 0.25rem;
        text-transform:none; letter-spacing:0; }}
.joinstep p {{ margin:0.25rem 0 0; color:var(--ink); font-size:0.8125rem; }}
.joinstep p.more {{ color:var(--dim); }}
/* A link in the text is --dial on --ink, and the two are 1.02:1 apart in
   luminance: no blue that is also 4.5:1 on the page can be 3:1 from the
   text, so colour alone can never tell a reader which words are links. The
   underline does (WCAG 1.4.1), so it is a deliberate one, a little heavier
   than the browser's hairline and clear of the descenders, and it thickens
   under the pointer. A link that is the thing to do next is a button, a
   ::: next block (site 1.2.2). */
a {{ color:var(--dial); text-decoration-thickness:0.075em;
        text-underline-offset:0.22em; }}
a:hover {{ text-decoration-thickness:0.14em; }}
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
/* A closed board's address (site 1.3.10): words in --dim, the same box as
   the link so the row does not move, and no dotted rule under it, because
   the rule is what says "press this". */
.addr .nodial {{ color:var(--dim); display:inline-block; padding:0.375rem 0;
        overflow-wrap:anywhere; }}
/* Closed by its sysop: a marker in the human colour, boxed so it reads as a
   state and not as a callers figure, and inline-block so on a phone, where
   the state is pinned at 15ch, it wraps inside its box. */
.state.closed .shut {{ display:inline-block; color:var(--warm);
        border:1px solid rgba(224, 169, 78, 0.5); border-radius:0.25rem;
        padding:0 0.25rem; font-size:0.75rem; line-height:1.5; }}
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
.k-int svg, .k-upd svg, .k-feat svg {{ stroke:currentColor; }}
/* The camera (site 1.2.8), the one feature drawn rather than lettered: a
   point smaller than a cause's drawing, and the chip's side padding given
   back, so it sits the height and near the width of C or Fi beside it. */
.bd.k-feat svg {{ display:block; width:1rem; height:1rem; margin:0 -0.125rem;
        fill:none; stroke-width:1.8; stroke-linecap:round; stroke-linejoin:round; }}
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
/* The stock skins on /skins (site 1.3.17): each the panel's own 3:2, and
   two across a desktop column rather than three, so a lamp is still a lamp. */
.gallery.skins {{ grid-template-columns:repeat(auto-fit, minmax(17rem, 1fr)); }}
.gallery.skins img {{ aspect-ratio:3 / 2; }}
.tablewrap {{ overflow-x:auto; margin:1rem 0; }}
article table td {{ vertical-align:top; }}
/* /different's comparison (site 1.2.9). A table that scrolls sideways
   inside its own box on a narrow screen, the row names held at the left
   edge so a cell is never read without its question. The µnleashed column
   lit with the --dial wash the run card uses, and its name in --dial. The
   marks are line art at the text's size: a tick in --live, a cross in
   --risk, a question mark in --faint, each with its meaning for a screen
   reader. */
.cmpwrap {{ overflow-x:auto; margin:0.75rem 0 0.5rem; border:1px solid var(--rule);
        border-radius:0.375rem; }}
.cmpwrap:focus-visible {{ outline:3px solid #ffd35c; outline-offset:2px; }}
article table.cmp {{ width:100%; min-width:52rem; border-collapse:separate;
        border-spacing:0; font-size:0.8125rem; }}
table.cmp th, table.cmp td {{ padding:0.5rem 0.625rem; border-bottom:1px solid var(--rule);
        vertical-align:top; text-align:left; }}
table.cmp tbody tr:last-child th, table.cmp tbody tr:last-child td {{ border-bottom:0; }}
table.cmp thead th {{ color:var(--struct); font-size:0.75rem; letter-spacing:0.0625rem;
        text-transform:uppercase; white-space:nowrap; }}
table.cmp thead th a {{ color:inherit; }}
table.cmp th[scope=row] {{ position:sticky; left:0; z-index:1; background:var(--bg);
        color:var(--ink); width:11rem; min-width:9rem; font-weight:normal;
        border-right:1px solid var(--rule); }}
table.cmp thead th:first-child {{ position:sticky; left:0; z-index:2; background:var(--bg); }}
table.cmp td {{ color:var(--dim); }}
table.cmp .us {{ background:rgba(127, 212, 255, 0.10); color:var(--ink); }}
table.cmp thead th.us, table.cmp thead th.us a {{ color:var(--dial); }}
/* Not in capitals: an upper-cased micro sign is a Greek capital mu, and
   the name would read MNLEASHED. */
table.cmp thead th.us {{ text-transform:none; letter-spacing:0; font-size:0.8125rem; }}
table.cmp .cm {{ display:inline-block; width:0.9375rem; height:0.9375rem;
        margin:0 0.375rem 0 0; vertical-align:-0.125rem; }}
table.cmp svg.cm path {{ fill:none; stroke-width:2; stroke-linecap:round;
        stroke-linejoin:round; }}
table.cmp svg.cm.y path {{ stroke:var(--live); }}
table.cmp svg.cm.n path {{ stroke:var(--risk); }}
table.cmp .cm.q {{ color:var(--faint); text-align:center; font-weight:bold; line-height:0.9375rem; }}
@media (hover: hover) and (pointer: fine) {{
  table.cmp tr:hover td, table.cmp tr:hover th {{ background:#111; }}
  table.cmp tr:hover td.us {{ background:rgba(127, 212, 255, 0.16); }}
}}
/* The second table (site 1.3.0): its column names are categories with an
   example, too long to hold on one line, so they wrap, and every column
   has a floor so the lit one is never squeezed to a word a line. */
table.cmp.today thead th {{ white-space:normal; }}
table.cmp.today td, table.cmp.today thead th[scope=col] {{ min-width:8.5rem; }}
table.cmp.today td.us, table.cmp.today thead th.us {{ min-width:11rem; }}
p.cmpnote {{ color:var(--dim); font-size:0.8125rem; margin:0.5rem 0 1.5rem; }}
/* On a phone the row names narrow, so µnleashed's column and the next are
   both in view beside them, and a line over the table says it scrolls. */
p.cmphint {{ display:none; color:var(--faint); font-size:0.75rem; margin:0.75rem 0 -0.5rem; }}
@media (max-width: 900px) {{
  p.cmphint {{ display:block; }}
  article table.cmp {{ min-width:44rem; font-size:0.75rem; }}
  table.cmp th[scope=row] {{ width:6.5rem; min-width:6.5rem; }}
  table.cmp th, table.cmp td {{ padding:0.4375rem 0.5rem; }}
  table.cmp.today td, table.cmp.today thead th[scope=col] {{ min-width:8rem; }}
  table.cmp.today td.us, table.cmp.today thead th.us {{ min-width:9rem; }}
}}
/* /different's privacy table (site 1.3.6): two columns, "Privacy
   forward" in --live on the left, the same green the /privacy diagram
   gives a party that keeps no copy of you, and "Privacy policies" in the
   ordinary column-name colour. A µnleashed cell carries a faint --live
   wash, the way the other tables light their µnleashed column. On a phone
   (600px and under) every row stacks: the topic, then each cell under its
   column's name, repeated in the cell, since a label column and two cells
   side by side at 390px would leave each cell a few words a line. */
.pvwrap {{ margin:0.75rem 0; border:1px solid var(--rule); border-radius:0.375rem; }}
article table.pv {{ width:100%; border-collapse:separate; border-spacing:0;
        font-size:0.8125rem; }}
table.pv th, table.pv td {{ padding:0.5rem 0.625rem; border-bottom:1px solid var(--rule);
        vertical-align:top; text-align:left; white-space:normal; }}
table.pv tbody tr:last-child th, table.pv tbody tr:last-child td {{ border-bottom:0; }}
table.pv thead th {{ color:var(--struct); font-size:0.75rem; letter-spacing:0.0625rem;
        text-transform:uppercase; }}
table.pv thead th.fwd {{ color:var(--live); }}
table.pv th[scope=row] {{ color:var(--ink); width:10rem; font-weight:normal;
        border-right:1px solid var(--rule); }}
table.pv td.fwd {{ background:rgba(93, 220, 122, 0.07); color:var(--ink); width:38%; }}
table.pv td.pol {{ color:var(--dim); }}
table.pv .pvl {{ display:block; }}
table.pv .pvl + .pvl {{ margin-top:0.375rem; }}
table.pv .pvh {{ display:none; }}
@media (max-width: 600px) {{
  table.pv, table.pv tbody, table.pv tr, table.pv th, table.pv td {{ display:block; width:auto; }}
  table.pv thead {{ position:absolute; width:0.0625rem; height:0.0625rem; overflow:hidden;
        clip:rect(0 0 0 0); }}
  table.pv th[scope=row] {{ width:auto; border-right:0; border-bottom:0; padding-bottom:0.25rem;
        color:var(--struct); font-size:0.875rem; }}
  table.pv td, table.pv td.fwd {{ border-bottom:0; width:auto; }}
  table.pv tbody tr {{ border-bottom:1px solid var(--rule); }}
  table.pv tbody tr:last-child {{ border-bottom:0; }}
  table.pv .pvh {{ display:block; font-size:0.6875rem; letter-spacing:0.0625rem;
        text-transform:uppercase; color:var(--struct); margin-bottom:0.25rem; }}
  table.pv td.fwd .pvh {{ color:var(--live); }}
}}
.vh {{ position:absolute; width:0.0625rem; height:0.0625rem; overflow:hidden; clip:rect(0 0 0 0);
        white-space:nowrap; }}
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
  /* Except a block marked "```nowrap": commands whose tokens must stay
     whole, where a short sideways scroll beats "unleashed_" and "BBS" on
     two lines reading as two broken commands (site 1.2.1). */
  article pre.nowrap {{ white-space:pre; overflow-wrap:normal; }}
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
/* The separators (site 1.2.1). Each link after the first carries a dot in
   the 1.5ch its neighbour's margin leaves, drawn outside its own box by a
   negative margin. A link that starts a wrapped line starts at the row's
   edge, so its dot lands outside the row and overflow:hidden drops it: no
   row ends on a dangling dot, and none starts on one. The dot is an
   inline-block, so the link's underline does not run under it. */
footer .row {{ display:block; overflow:hidden; }}
footer .row a {{ margin-right:1.5ch; }}
footer .row a::before, footer .colophon span + span::before {{ content:"\u00b7";
        display:inline-block; width:1.5ch; margin-left:-1.5ch; text-align:center;
        color:var(--faint); }}
footer .row .lbl + a::before {{ content:none; }}
footer .row a:focus-visible {{ outline-offset:-0.125rem; }}
/* The footer's two rows, each led by what it is, and the colophon under
   them in small type. The labels are the faint colour: structure, not
   something to click. */
footer .lbl {{ color:var(--faint); margin-right:0.5rem; text-transform:uppercase;
        letter-spacing:0.0625rem; font-size:0.75rem; }}
footer .colophon {{ margin:1.25rem 0 0; font-size:0.6875rem; color:var(--faint);
        line-height:1.6; overflow:hidden; }}
footer .colophon a {{ display:inline; padding:0; color:var(--dim); }}
footer .colophon span {{ white-space:nowrap; display:inline-block; margin-right:1.5ch; }}
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
  .addr a, .addr .nodial {{ padding:0.5rem 0; }}
  /* "Temporarily closed" is wider than the pinned 15ch, so it takes two
     lines; min-content keeps its box tight round them rather than 15ch
     wide with a gap down its left side. */
  .state.closed .shut {{ width:min-content; }}
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
/* BUY (site 1.3.18, Rob): a tiny filled red button, the size of the
   picks' tags, beside each board that has a buy link, on /install and on
   /hardware. Not --risk: that red means somebody keeping a copy of you,
   and this is a shop. White on #c62828 is 5.6:1, the hover #d32f2f 5.0:1.
   Bold capitals with almost no padding: it is there for somebody who has
   not got the board, and must not look like the Install button's rival. */
article a.buy {{ display:inline-block; font-size:0.625rem; font-weight:700;
        line-height:1.2; letter-spacing:0.04em; padding:0 0.2em;
        color:#fff; background:#c62828; border-radius:0.1875rem;
        text-decoration:none; white-space:nowrap; vertical-align:0.08em; }}
article a.buy:hover {{ background:#d32f2f; color:#fff; }}
article a.buy:focus-visible {{ outline:3px solid #ffd35c; outline-offset:2px; }}
@media (forced-colors: active) {{
  article a.buy {{ border:1px solid LinkText; }}
}}
/* On /install the row's label and its BUY share a box, the button outside
   the label so pressing it never picks a board, at the right-hand end of
   the row's last line, the version line, level with its words. The button
   stands mostly in the row's own right padding, and the version line ends
   1.125rem short of the words' column, which is all the room it needs. */
article .installer .brow {{ position:relative; }}
article .installer .brow > a.buy {{ position:absolute; right:0.1875rem;
        bottom:0.125rem; }}
article .installer .brow:has(> a.buy) .bv {{ padding-right:1.125rem; }}
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
/* Site 1.3.5: a fourth board (the ESP32-CAM) put the Update button past
   the first screen at 1366 x 768, so each row is tighter: an eighth of a
   rem of padding above and below where it was a quarter, and the three
   lines at 1.15 rather than 1.25. About 12px a row.
   Site 1.3.17: a fifth board (the Makerfabs) did it again, so again each
   row is tighter: no padding above and below, the lines at 1.05, and the
   picture at 2.375rem tall, the text's own height. About 9px a row. */
article .installer .bopt {{ display:flex; align-items:center; gap:0.625rem;
        padding:0 0.625rem 0 0.5rem; border:1px solid #2c3a44;
        border-radius:0.375rem; cursor:pointer; }}
article .installer .bopt input {{ flex:none; margin:0; accent-color:var(--dial); }}
article .installer .bopt:has(input:checked) {{ border-color:var(--dial);
        background:#102630; }}
article .installer .bopt:has(input:focus-visible) {{ outline:3px solid #ffd35c;
        outline-offset:2px; }}
article .installer .bopt .bt {{ display:flex; flex-direction:column; min-width:0;
        font-size:0.8125rem; line-height:1.05; flex:1 1 12rem; }}
article .installer .bopt .bt b {{ color:var(--ink); }}
article .installer .bopt svg.art.board {{ width:3.8rem; height:2.375rem; }}
article .installer .bopt .tell {{ color:var(--dim); font-size:0.75rem; }}
article .installer .bopt .tell.pick {{ color:var(--ink); }}
article .installer .bopt .bv {{ color:var(--dial); font-size:0.75rem; }}
article .installer .bopt .bv.soon {{ color:var(--faint); }}
/* Our picks (site 1.3.15, Rob): a thin gold frame, the amber box's own bar
   colour, and the pick's label in --warm sitting on the frame's top edge
   at the right, the card's own colour behind it, the way a label sits on
   a border. Out of the row's flow, so the row lays out exactly as it did
   before: in the flow it widened the words and pushed a long name under
   the picture, and inside the row's corner it ran over the longest name
   at 1366. A picked row still turns cyan as it always has. */
article .installer .bopt.rec {{ position:relative; border-color:#8a6d39; }}
article .installer .bopt .rec {{ position:absolute; top:-0.45em; right:0.625rem;
        padding:0 0.3em; background:#12121a;
        font-size:0.625rem; line-height:0.9; text-transform:uppercase;
        letter-spacing:0.04em; color:var(--warm); }}
/* Windows' high contrast drops the gold, so the frame is heavier and the
   tag boxed: the words still say "our pick". */
@media (forced-colors: active) {{
  article .installer .bopt.rec {{ border:2px solid CanvasText; }}
  article .installer .bopt .rec {{ border:1px solid CanvasText; padding:0 0.25em; }}
}}
/* Secure (site 1.3.3) after an S3 board's version, in the row's own small
   type, so the row is no taller for it; the lock no taller than its
   letters. */
article .installer .bopt {{ flex-wrap:wrap; }}
article .installer .bopt .bv .sep {{ color:var(--faint); }}
article .installer .bopt a.secure {{ white-space:nowrap; }}
article .installer .bopt a.secure svg.lockg {{ width:0.6em; height:0.76em;
        margin:0 0.3em 0 0; vertical-align:-0.06em; overflow:visible; }}
article .installer .bopt a.secure svg.lockg .lk {{ fill:none; stroke:currentColor;
        stroke-width:1.8; stroke-linejoin:round; stroke-linecap:round; }}
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
/* The guided path at the top of /install (site 1.3.15, Rob: "a more guided
   process which starts with pick your board, then flash your board"): four
   numbered steps down the left column, each a ring in --struct with a thin
   line to the next, its title in --struct and one short line under it. On
   a phone it comes before the card, where the markup puts it. The first
   step carries our picks, each board's name a label for its radio in the
   card (--dial, dotted, filled like its row when that board is picked). */
article ol.guide {{ list-style:none; margin:1.25rem 0 0.5rem; padding:0; }}
article ol.guide > li {{ position:relative; display:grid;
        grid-template-columns:1.75rem minmax(0, 1fr); column-gap:0.75rem;
        margin:0; padding:0 0 0.875rem; }}
article ol.guide > li:last-child {{ padding-bottom:0; }}
article ol.guide > li:not(:last-child)::before {{ content:""; position:absolute;
        left:0.875rem; top:2rem; bottom:0.25rem; border-left:1px solid #2c3a44; }}
article ol.guide .n {{ display:flex; align-items:center; justify-content:center;
        width:1.75rem; height:1.75rem; box-sizing:border-box;
        border:1px solid var(--struct); border-radius:50%; color:var(--struct);
        font-size:0.875rem; line-height:1; }}
article ol.guide .gs {{ min-width:0; }}
article ol.guide p.t {{ margin:0; color:var(--struct); font-size:0.9375rem;
        line-height:1.75rem; }}
article ol.guide p.d {{ margin:0; font-size:0.875rem; line-height:1.5; }}
article ol.guide .side {{ display:none; }}
@media (min-width: 901px) {{
  article ol.guide .side {{ display:inline; }}
  article ol.guide .under {{ display:none; }}
}}
article ol.guide ul.uc {{ list-style:none; margin:0.375rem 0 0; padding:0;
        font-size:0.8125rem; line-height:1.5; }}
article ol.guide ul.uc li {{ margin:0; padding-left:2ch; }}
article ol.guide .uc .ul {{ display:block; margin-left:-2ch; color:var(--warm); }}
article ol.guide .uc label {{ margin-left:-0.25em; padding:0 0.25em;
        border-radius:0.2em; color:var(--dial); cursor:pointer;
        text-decoration:underline dotted; text-underline-offset:0.2em; }}
article ol.guide .uc .why {{ margin-left:0.5ch; }}
article ol.guide p.else {{ margin:0.375rem 0 0; font-size:0.8125rem; line-height:1.5; }}
@media (min-width: 1200px) {{
  article ol.guide ul.uc {{ display:grid;
        grid-template-columns:max-content max-content minmax(0, 1fr);
        column-gap:2ch; }}
  article ol.guide ul.uc li {{ display:contents; }}
  article ol.guide .uc .ul {{ margin-left:0; }}
  article ol.guide .uc label {{ justify-self:start; }}
  article ol.guide .uc .why {{ margin-left:0; }}
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
article .hwb dd .exp {{ color:var(--dim); }}
/* The seal (site 1.2.5): a ribbon over the picture's top-left corner,
   sitting a little outside it so it reads as laid on, not drawn in. */
article .hwb .hwpic {{ position:relative; flex:none; padding:0.5rem 0 0 0.5rem; }}
article .hwb .hwpic svg.art.seal {{ position:absolute; left:0; top:0;
        width:5.25rem; height:auto; margin:0; }}
/* The Secure seal (site 1.3.3): FLASH & GO's size, in the opposite corner,
   bottom right, sitting as far outside the picture as FLASH & GO does. */
article .hwb .hwpic.sec {{ padding:0.5rem 0.5rem 0.5rem 0.5rem; }}
article .hwb .hwpic svg.art.seal.sec {{ left:auto; top:auto; right:0; bottom:0; }}
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
.cta a.btn2 {{ color:var(--dial); background:transparent; border:1px solid #4a7a99; }}
.cta a.btn2:hover {{ border-color:var(--dial); }}
.cta a.btn:focus-visible, .cta a.btn2:focus-visible {{ outline:3px solid #ffd35c;
        outline-offset:2px; }}
.cta .note {{ color:var(--dim); margin:0.75rem 0 0; }}
/* A section's next step (::: next, site 1.2.2): the cta's outlined button
   at a section's size, on a faint wash of --dial so it reads as a thing to
   press rather than a boxed word. The border is 4.2:1 on the page, over
   the 3:1 a control's edge needs; #35566b, which the outlined buttons had
   before, was 2.5:1. It stays its own width on a phone. */
.next {{ display:flex; flex-wrap:wrap; gap:0.625rem 0.75rem; margin:0.875rem 0 1.25rem; }}
article li + .next, article ul + .next, article ol + .next {{ margin-top:0.5rem; }}
a.go {{ display:inline-block; font-size:0.875rem; line-height:1.4;
        color:var(--dial); background:rgba(127, 212, 255, 0.07);
        border:1px solid #4a7a99; border-radius:0.375rem;
        padding:0.5rem 1rem; text-decoration:none; }}
a.go::after {{ content:" →"; }}
a.go:hover {{ border-color:var(--dial); background:rgba(127, 212, 255, 0.14); }}
a.go:focus-visible {{ outline:3px solid #ffd35c; outline-offset:2px; }}
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


# The wordmark as a drawing, made once at start from LOGO_ROWS, so the rows
# stay the one source (brand/make_avatar.py and make_cover.py read them too).
# A cell is 6 units wide and 10 tall, which is the 0.6em by 1em a monospace
# cell had in the <pre>: a full block is one rect the height of a cell, and
# a half block one half as tall, at the top or the bottom. A run of equal
# cells is one rect, so the whole mark is a few dozen. One colour per row,
# the six the <pre> swept down it. crispEdges, so two rects that meet leave
# no hairline between them at any zoom.
LOGO_COLOURS = ("#e2d4ff", "#b48ef0", "#8f7ae8", "#6f84e0", "#4a7fc8", "#3f6cab")


def _logo_svg():
    cols = max(len(r) for r in LOGO_ROWS)
    kinds = {"\u2588": (0, 10), "\u2580": (0, 5), "\u2584": (5, 5)}
    out = []
    for i, row in enumerate(LOGO_ROWS):
        rects, x = [], 0
        while x < len(row):
            kind = kinds.get(row[x])
            if kind is None:
                x += 1
                continue
            end = x
            while end < len(row) and kinds.get(row[end]) == kind:
                end += 1
            dy, h = kind
            rects.append(f'<rect x="{x * 6}" y="{i * 10 + dy}" width="{(end - x) * 6}" '
                         f'height="{h}"/>')
            x = end
        out.append(f'<g fill="{LOGO_COLOURS[i % len(LOGO_COLOURS)]}">'
                   + "".join(rects) + "</g>")
    return (f'<svg class="logo" viewBox="0 0 {cols * 6} {len(LOGO_ROWS) * 10}" '
            'role="img" aria-label="\u00b5nleashed" shape-rendering="crispEdges">'
            "<title>\u00b5nleashed</title>" + "".join(out) + "</svg>")


LOGO_SVG = _logo_svg()


def logo_html(home="/"):
    """The wordmark as a link to the board list: the home page of the site,
    on every page and every face.

    The link carries its own name, because a link whose only content is a
    picture is announced by a screen reader as the picture, and "µnleashed"
    says nothing about where it goes. The drawing inside keeps its own,
    role="img" with the name, for anything that reads the picture alone."""
    return ('<a class="home" href="' + html.escape(home, quote=True)
            + '" aria-label="\u00b5nleashed: the board list">'
            + LOGO_SVG + "</a>")


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
#
# Site 1.3.0 (Rob): "No web: a BBS, not a website" read as a contradiction
# to somebody standing on a website, so it became No ads, and three more
# were added in the same spirit: No platforms, No hosting fees and No
# outside costs. Each is true of the board as it ships: it runs on its
# host's own network and power, nothing sits between a caller and it, the
# listing here is free, and nothing is paid for by the month. "Old and new"
# replaced "No browser" for the same reason as No ads, and "Run your own
# directory" came off: it matters to very few readers.
FREEDOMS = (
    ("ads", "No ads", "no one sells your time"),
    ("platform", "No platforms", "nobody in the middle"),
    ("fees", "No hosting fees", "it runs at your place"),
    ("costs", "No outside costs", "your power, your Wi-Fi"),
    ("cloud", "No cloud", "nobody else's server"),
    ("oldnew", "Old and new", "a 1980s computer can join"),
    ("chip", "Real hardware", "a chip on your shelf"),
    ("gpl", "Free software", "GPL v3 or later"),
    ("lan", "No internet needed", "a local network is enough"),
    ("rules", "You write the rules", "and you are the appeal"),
)

# 32 units square, drawn at 2.5rem. Stroke and colour come from the page
# stylesheet, so these are shapes only. "xb" is the gap cut under a slash so
# the slash reads as crossing the drawing rather than joining it, and "pn" is
# the pen's body, filled with the page colour so it sits in front of the
# lines it is writing.
_SLASH = '<path class="xb" d="M5 27 L27 5"/><path d="M5 27 L27 5"/>'
TICKER_ICONS = {
    # A megaphone, struck out.
    "ads": ('<path d="M6 13 V19 H10 L20 25 V7 L10 13 Z"/>'
            '<path class="d" d="M23.5 12.5 A5 5 0 0 1 23.5 19.5"/>'
            + _SLASH),
    # Three layers stacked, a platform, struck out.
    "platform": ('<path d="M16 5 L28 11 L16 17 L4 11 Z"/>'
                 '<path class="d" d="M4 16 L16 22 L28 16 M4 21 L16 27 L28 21"/>'
                 + _SLASH),
    # A coin with a dollar sign, struck out.
    "fees": ('<circle cx="16" cy="16" r="11"/>'
             '<path class="d" d="M19.5 12 C18.5 10.5 13 10.5 13 13.25 C13 16'
             ' 19.5 15.5 19.5 18.75 C19.5 21.5 14 21.5 12.5 20 M16 8.5 V23.5"/>'
             + _SLASH),
    # A month on a calendar, the monthly bill, struck out.
    "costs": ('<rect x="5" y="7" width="22" height="20" rx="1.5"/>'
              '<path d="M5 12.5 H27 M10.5 4.5 V9 M21.5 4.5 V9"/>'
              '<path class="d" d="M9.5 17 H11 M15 17 H16.5 M20.5 17 H22'
              ' M9.5 21.5 H11 M15 21.5 H16.5"/>' + _SLASH),
    # An old monitor on its stand beside a phone: both can join.
    "oldnew": ('<rect x="3" y="7" width="16" height="13" rx="1.5"/>'
               '<path d="M8 24 H14 M11 20 V24"/>'
               '<rect x="21" y="10" width="8" height="15" rx="1.5"/>'
               '<path class="d" d="M6 11 H13 M6 14 H11 M24 22 H26"/>'),
    # The cloud from the manifesto's "no internet" drawing, struck out.
    "cloud": ('<path transform="translate(-11.8 3.5)" d="M18.5 22 C14 22 14 15.5'
              ' 18.5 15.5 C19 10.5 25.5 9 28 12.5 C30 8 37 8.5 37.5 14 C42 14'
              ' 42 22 37.5 22 Z"/>' + _SLASH),
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
TOUCH_PNG = _brand("unleashed-avatar-512.png")

# The link preview card (site 1.3.0, marketing round 3): 1200 x 630, the
# size the large preview wants, where the square avatar was shown as a small
# thumbnail and the front page's description was a board count. Drawn by
# brand/make_ogcard.py from LOGO_SVG, FRONT_BOARD_ART and the site's
# palette and face, then screenshotted with headless Chrome; served from its
# own route like the avatar, so it never joins the manifesto's gallery.
# Every page shares it until photographs are taken; OG_PAGES gives the
# pages that have one their own title and description.
OG_CARD_PNG = _brand("unleashed-og-card-1200x630.png")
_OG_TITLE = re.compile(r'<meta property="og:title" content="[^"]*">')
_OG_DESC = re.compile(r'<meta property="og:description" content="[^"]*">')
# The pitch's face (site 1.2.9), from PITCH_FONT: one @font-face, doubled
# braces because PAGE is formatted on every render. font-display:swap, so
# the pitch shows at once in the page's own face and changes when the file
# arrives, about 10 KB, rather than staying blank.
_face, _weight = PITCH_FONTS[PITCH_FONT]
PAGE = PAGE.replace("@PITCH_FACE@", (
    '@font-face {{ font-family:"Pitch"; src:url("/font/%s") format("%s"); '
    'font-weight:%d; font-style:normal; font-display:swap; }}'
    % (_face, "truetype" if _face.endswith(".ttf") else "woff", _weight)))


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


def cached(key, seconds, build):
    hit = _cache.get(key)
    now = time.time()
    if hit and now - hit[0] < seconds:
        return hit[1]
    value = build()
    _cache[key] = (now, value)
    return value


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
/* The dev board with its card module (site 1.2.7): 144 x 66 units, so the
   board in it is drawn at exactly the scale of the one above it. */
svg.art.board.big.wide { width:13.5rem; height:6.1875rem; }
/* The seal on a board's picture (site 1.2.5): --live, the site's colour
   for up and working, on the page's own background so the board's lines
   stop at its edge. */
svg.art.seal .rb { fill:var(--bg); stroke:var(--live); stroke-width:1.4;
        stroke-linejoin:round; }
svg.art.seal text.sl1 { fill:var(--live); font-weight:bold; letter-spacing:0.04em; }
svg.art.seal text.sl2 { fill:var(--dim); }
/* The Secure seal (site 1.3.3): the seal, with a padlock in its stroke,
   and the asterisk in amber while SSH is still to ship, so the seal
   cannot be read as a promise already kept. */
svg.art.seal .lk { fill:none; stroke:var(--live); stroke-width:1.8;
        stroke-linejoin:round; stroke-linecap:round; }
svg.art.seal tspan.ast { fill:var(--warm); }
/* NOT SUPPORTED (site 1.3.11), on a board /hardware says not to buy:
   the same ribbon in amber, the site's caution colour. */
svg.art.seal.no .rb { stroke:var(--warm); }
svg.art.seal.no text.sl1 { fill:var(--warm); }

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
/* The lights diagrams on /lights: the data line is --live. */
svg.art .s-dat { stroke:var(--live); }
svg.art .f-dat { fill:var(--live); }
/* The spectrum at the top of /hardware, as wide as the wiring diagrams.
   Each column is a link (site 1.2.2): the whole column is the target, its
   tick brightens and its name turns --dial under the pointer, and keyboard
   focus draws the site's yellow ring round the column rather than the
   browser's round a stray box. The lamp is the run card's: --dial, with a
   glow. Since site 1.3.9 two drawings of it, across and down, the
   roadmap's way, and the stretch out to the fourth stop is dashed, because
   not all of that build exists yet. */
svg.art.spectrum { width:100%; height:auto; margin:0.75rem auto 1rem; }
svg.art.spectrum.wide { max-width:42rem; }
svg.art.spectrum.tall { display:none; max-width:24rem; }
@media (max-width: 900px) {
  svg.art.spectrum.wide { display:none; }
  svg.art.spectrum.tall { display:block; }
}
svg.art.spectrum .later { stroke-dasharray:4 5; }
svg.art.spectrum a { outline:none; cursor:pointer; }
svg.art.spectrum .hit { fill:transparent; stroke:none; }
svg.art.spectrum .tk { stroke-width:1.6; opacity:0.7; }
svg.art.spectrum .nm { text-decoration:underline; }
svg.art.spectrum a:hover .tk, svg.art.spectrum a:focus-visible .tk { opacity:1;
        stroke-width:2.6; }
svg.art.spectrum a:hover .nm, svg.art.spectrum a:focus-visible .nm { fill:var(--dial); }
svg.art.spectrum a:hover .hit { fill:rgba(127, 212, 255, 0.05); }
svg.art.spectrum a:focus-visible .hit { stroke:#ffd35c; stroke-width:1.5; }
svg.art.spectrum .sdot { pointer-events:none; }
svg.art.spectrum .dh { fill:var(--dial); opacity:0.22; }
svg.art.spectrum .dc { fill:var(--dial); }
svg.art.spectrum tspan.exp { fill:var(--dim); }

/* The roadmap on /roadmap (site 1.2.4): one line in three stretches,
   done in --live, now in --dial, later dashed in --faint. Two drawings of
   it, across on a desktop and down on a phone, one shown at a time. */
svg.art.roadmap { width:100%; height:auto; margin:1rem auto 1.5rem; }
svg.art.roadmap.wide { max-width:46rem; }
svg.art.roadmap.tall { display:none; max-width:24rem; }
@media (max-width: 900px) {
  svg.art.roadmap.wide { display:none; }
  svg.art.roadmap.tall { display:block; }
}
svg.art.roadmap .rl { fill:none; stroke-width:2; stroke-linecap:round; }
svg.art.roadmap .rm-done { stroke:var(--live); }
svg.art.roadmap .rm-now { stroke:var(--dial); }
svg.art.roadmap .rm-later { stroke:var(--faint); stroke-dasharray:4 5; }
svg.art.roadmap .rd, svg.art.roadmap .rj { stroke-width:1.6; }
svg.art.roadmap .rd-done { fill:var(--live); stroke:var(--live); }
svg.art.roadmap .rd-now { fill:var(--bg); stroke:var(--dial); }
svg.art.roadmap .rd-later { fill:var(--bg); stroke:var(--faint); }
svg.art.roadmap .rj.rd-done { fill:var(--bg); }
svg.art.roadmap text.rt-done, svg.art.roadmap text.rt-now { fill:var(--ink); }
svg.art.roadmap text.hd { letter-spacing:0.08em; }
svg.art.roadmap text.hd.rt-done { fill:var(--live); }
svg.art.roadmap text.hd.rt-now { fill:var(--dial); }
svg.art.roadmap text.hd.rt-later { fill:var(--dim); }
svg.art.roadmap .rlamp { pointer-events:none; }
svg.art.roadmap .dh { fill:var(--dial); opacity:0.25; }
svg.art.roadmap .dc { fill:var(--dial); }

/* The camera on /camera (site 1.2.4): the shot's flash is white, and off
   at rest. */
svg.art.camsnap { width:100%; max-width:30rem; height:auto;
        margin:0.75rem auto 1.25rem; }
svg.art.camsnap .fl { fill:#ffffff; opacity:0; }
/* The skins on /skins (site 1.3.14): the same strip's size, and the lit
   picture's two lamps glow the way the lights page's do. */
svg.art.skinart { width:100%; max-width:30rem; height:auto;
        margin:0.75rem auto 1.25rem; }

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
/* The spectrum on /hardware (site 1.2.2). The lamp's two ends are the
   first and last stops, measured from the stop it rests on, and set per
   drawing in --from and --to (site 1.3.9): across on a desktop, down on
   a phone. */
@keyframes specdraw { from { transform:scaleX(0); } to { transform:scaleX(1); } }
@keyframes specgrow { from { transform:scaleY(0); } to { transform:scaleY(1); } }
@keyframes specrise { from { opacity:0; transform:translateY(5px); }
                      to { opacity:1; transform:translateY(0px); } }
@keyframes specin { from { opacity:0; } to { opacity:1; } }
@keyframes specgo { from { transform:translateX(var(--from)); }
                    to { transform:translateX(var(--to)); } }
@keyframes specgoy { from { transform:translateY(var(--from)); }
                     to { transform:translateY(var(--to)); } }
@keyframes specair { from { opacity:1; } to { opacity:0.5; } }
/* The roadmap (site 1.2.4): the lamp runs the "now" stretch, its length
   set per drawing in --run. The camera's flash lands as the word arrives. */
@keyframes rmrun { 0%, 10% { transform:translateY(0px); opacity:1; }
                   80% { transform:translateY(var(--run)); opacity:1; }
                   95%, 100% { transform:translateY(var(--run)); opacity:0; } }
@keyframes rmin { from { opacity:0; transform:translateY(-4px); }
                  to { opacity:1; transform:translateY(0px); } }
@keyframes camflash { 0%, 82% { opacity:0; } 88% { opacity:0.85; } 100% { opacity:0; } }

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
  /* the lights: the drive light pulses, and two of the strip's callers
     have traffic */
  svg.art.lights .glow { animation:artpulse 2.4s ease-in-out infinite; }
  svg.art.lights .px2 { animation:artpulse 0.9s ease-in-out infinite; }
  svg.art.lights .px3 { animation:artpulse 1.3s ease-in-out 0.4s infinite backwards; }
  /* the spectrum: the line draws, each stop grows out of it in turn, and
     a lamp goes along it and back at about the pace it had with three
     stops, 12s the round trip across and 8s down */
  svg.art.spectrum .sl { transform-box:fill-box; transform-origin:left center;
        animation:specdraw 0.8s ease-out both; }
  svg.art.spectrum.tall .sl { transform-origin:center top; animation-name:specgrow; }
  svg.art.spectrum .tk { transform-box:fill-box; transform-origin:center;
        animation:specgrow 0.35s ease-out 0.8s both; }
  svg.art.spectrum.tall .tk { animation-name:specdraw; }
  svg.art.spectrum .lab { animation:specrise 0.45s ease-out 0.9s both; }
  svg.art.spectrum .s1 .tk { animation-delay:1.05s; }
  svg.art.spectrum .s1 .lab { animation-delay:1.15s; }
  svg.art.spectrum .s2 .tk { animation-delay:1.3s; }
  svg.art.spectrum .s2 .lab { animation-delay:1.4s; }
  svg.art.spectrum .s3 .tk { animation-delay:1.55s; }
  svg.art.spectrum .s3 .lab { animation-delay:1.65s; }
  svg.art.spectrum .sdot { animation:specin 0.6s ease-out 2.15s both,
        specgo 6s ease-in-out -3s infinite alternate; }
  svg.art.spectrum.tall .sdot { animation:specin 0.6s ease-out 2.15s both,
        specgoy 4s ease-in-out -2s infinite alternate; }
  svg.art.spectrum .arr { animation:specair 2.4s ease-in-out 2s infinite alternate backwards; }
  /* the roadmap: the line draws, each stretch's stations come in down it,
     one stretch after another, then the lamp runs down "now" */
  svg.art.roadmap .seg { transform-box:fill-box; transform-origin:left center;
        animation:specdraw 0.7s ease-out both; }
  svg.art.roadmap.wide .br { transform-box:fill-box; transform-origin:center top;
        animation:specgrow 0.5s ease-out 0.7s both; }
  svg.art.roadmap.tall .br { transform-box:fill-box; transform-origin:center top;
        animation:specgrow 0.9s ease-out both; }
  svg.art.roadmap .st { animation:rmin 0.4s ease-out 0.9s both; }
  svg.art.roadmap .b1 .st { animation-delay:1.3s; }
  svg.art.roadmap .b2 .st { animation-delay:1.7s; }
  svg.art.roadmap .rlamp { animation:specin 0.5s ease-out 2.2s both,
        rmrun 3.2s ease-in-out 2.7s infinite; }
  /* the camera: the word goes down the line and the pixel flashes */
  svg.art.camsnap .go { animation:artserial 2.4s linear infinite; }
  svg.art.camsnap .fl { animation:camflash 2.4s linear infinite; }
  /* the skin: the drive lamp flickers, the activity lamp pulses */
  svg.art.skinart .glow { animation:artpulse 0.9s ease-in-out infinite; }
  svg.art.skinart .glow2 { animation:artpulse 2.4s ease-in-out 0.4s infinite backwards; }
  svg.art.spectrum .up { transition:transform 0.2s ease-out; }
  svg.art.spectrum a:hover .up,
  svg.art.spectrum a:focus-visible .up { transform:translateY(-2px); }
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


# --------------------------------------------------------------------------
# What an "::: art" block can draw, by name. Empty here: each app adds the
# drawings its own pages use (ART.update({...})), so a drawing lives beside
# the pages that show it.
# --------------------------------------------------------------------------
ART = {}


# Everything, underscored helpers included, so an app's "from sitekit
# import *" sees the engine exactly as the one-file server did.
__all__ = [n for n in list(globals()) if not n.startswith("__")]
