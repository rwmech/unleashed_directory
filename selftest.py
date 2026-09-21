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
        # Nothing on this site states an unbuilt feature as present fact.
        # Somebody decides whether to spend an afternoon and twenty dollars on
        # the strength of these sentences, which makes them the most expensive
        # kind of wrong there is here. Doors are not started and message bases
        # are being designed. Both are coming and both are part of the
        # argument, so they are in the future tense rather than deleted.
        check("doors are named as coming, not as something the board has",
              "doors come after" in page and ", doors," not in page)
        check("and the features it does list are ones that exist",
              "mail between callers" in page and "file areas on an SD card" in page)
        for path in ("/sdcard", "/build"):
            _, page = get(path)
            check(f"{path} does not promise message bases in the present tense",
                  "want message bases" not in page
                  and "gets you message bases" not in page)
            check(f"{path} says they are still being built",
                  "being built" in page or "once they are built" in page)
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
        # Forums are being built and are not on any board. A feature in the
        # present tense that does not exist is a claim that fails on first
        # contact, and somebody who calls a board looking for it concludes
        # the software is broken rather than that the site ran ahead.
        check("forums are described as being built, never as available",
              "being built" in kids.lower()
              and "not on any board yet" in kids.lower())
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
                     "/forward-mesh"):
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
        check("and warns about 5 V before the wiring table",
              page.index("Not VIN") < page.index("GPIO18"))
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
        # The animated diagram scales rather than scrolling. overflow-x:auto
        # stopped the page sliding sideways and put a scrollbar on the
        # diagram instead, and it was a vertical one: when one axis is not
        # visible, CSS computes the other to auto as well, and five printed
        # lines at 1.5 line height are 105px in a 7.4em box.
        _, page = get("/", host="about.example")
        check("the diagram scales to fit instead of scrolling",
              "overflow:hidden" in page and "clamp(6px" in page
              and "overflow-x:auto;\n         font" not in page)
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
                # a hairline at any size, and svg.hours text is in viewBox
                # units, which scale with the chart already.
                if (line.lstrip().startswith("@media")
                        or "svg.hours text" in line
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
              "article pre:not(.chart) { white-space:pre-wrap;" in page)
        check("but the ascii diagram is left alone, because wrapping breaks it",
              ":not(.chart)" in page)
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
        print("The installer page, with nothing published")
        code, inst = get("/install")
        check("there is an install page", code == 200)
        check("it says plainly that there is nothing to install yet",
              "Not ready yet" in inst and "no firmware image" in inst)
        check("and says why, in its own words rather than as an advisory",
              "only ever join the network of whoever built it" in inst)
        check("it offers no button and no element to press",
              "<esp-web-install-button" not in inst)
        # The whole point of tying the script to the widget: with nothing
        # published there is no widget, so there is no third-party code on
        # the page either. A flag would have had to be remembered.
        check("and loads no script at all", "<script" not in inst)
        check("nothing under /firmware/ is served",
              get("/firmware/0.19.2/manifest.json")[0] == 404
              and get("/firmware/0.19.2/esp32/firmware.bin")[0] == 404)
        check("the page is reachable from the build page and the footer",
              "/install" in get("/build")[1] and '/install">Install</a>' in inst)
        # A page off the menu still has to say where it is. Without this the
        # nav marks nothing, or worse marks Boards.
        check("and the menu marks Build one as the section it belongs to",
              '<a class="here" href="/build">Build one</a>' in inst)

        print("Every other page is still script-free")
        scripted = [p for p in ("/", "/about", "/data", "/build", "/whofor",
                                "/terminals", "/firstcall", "/forward", "/how",
                                "/rules", "/privacy", "/kids", "/teachers",
                                "/sdcard", "/dialing")
                    if "<script" in get(p)[1]]
        check("nothing else on the site loads any JavaScript"
              + ("" if not scripted else "  <- " + ", ".join(scripted)),
              not scripted)

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

        whole = ["bootloader.bin", "partitions.bin", "firmware.bin", "littlefs.bin"]
        put("0.19.2", "esp32", whole,
            {"release.txt": "2026-09-21\nA short note.\n",
             "THIRD_PARTY_NOTICES.md": "notices\n"})
        put("0.19.1", "esp32", whole,
            {"release.txt": "2026-09-01\nOlder.\nimprov: yes\n"})
        put("0.18.0", "esp32", whole)                  # a third, beyond the cap
        put("9.9.9", "esp32", whole[:3])               # littlefs.bin missing
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
            check("the parts are the bootloader, the table, the app and the screens",
                  [p["path"] for p in parts]
                  == ["esp32/bootloader.bin", "esp32/partitions.bin",
                      "esp32/firmware.bin", "esp32/littlefs.bin"])
            check("at the offsets the partition table actually uses",
                  [p["offset"] for p in parts]
                  == [0x1000, 0x8000, 0x20000, 0x3C0000])
            # Their type is `offset: number`, JSON has no hex literal, and a
            # string would be handed to the flasher unparsed. This is the one
            # mistake in the schema that would write a board at the wrong
            # address, so it is pinned as a type and not only as a value.
            check("and every offset is a number, never a hex string",
                  all(isinstance(p["offset"], int) for p in parts))
            check("nothing that is not a version number is mistaken for one",
                  all(re.match(r"^\d+\.\d+\.\d+$", r["version"]) for r in rels))

            # Improv is a property of the image, so it is read from beside
            # the image. Absent means off, because a board that cannot answer
            # makes every install sit for ten seconds and look wedged.
            check("a release that does not speak Improv switches the wait off",
                  man["new_install_improv_wait_time"] == 0)
            check("and one that does gets the ten seconds it needs",
                  S.firmware_manifest("0.19.1")["new_install_improv_wait_time"] == 10)
            check("the date and note beside a release are read from it",
                  rels[0]["date"] == "2026-09-21"
                  and rels[0]["note"] == "A short note.")

            # Names are checked, not paths, the same way static_file does it.
            climbs = ["../server.py", "0.19.2/../../server.py",
                      "0.19.2/esp32/../../../server.py", "0.19.2/esp32/release.txt",
                      "0.19.2/esp32x9/firmware.bin", "", "manifest.json"]
            check("no path under /firmware/ climbs out of it",
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
                  and 'manifest="/firmware/0.19.2/manifest.json"' in shown)
            check("with our own button and both refusal messages in its slots",
                  'slot="activate"' in shown and 'slot="unsupported"' in shown
                  and 'slot="not-allowed"' in shown)
            check("the older release is kept and linked, not hidden",
                  "0.19.1" in shown)
            check("and the licences of what is being installed are linked",
                  "THIRD_PARTY_NOTICES.md" in shown)
        finally:
            S.FIRMWARE_DIR = was_dir
            shutil.rmtree(fwroot, ignore_errors=True)

        # A floating tag means the code a visitor runs can change between one
        # reader and the next. This is the only third-party code on the site,
        # so it is pinned to an exact version and the suite says so.
        check("ESP Web Tools is pinned to an exact version",
              re.search(r"esp-web-tools@\d+\.\d+\.\d+/", S.EWT_SCRIPT) is not None)
        check("and loaded from the self-contained web bundle",
              S.EWT_SCRIPT.endswith("/dist/web/install-button.js?module"))
        # firmware/ ships with no images in it, and that is the release gate:
        # nothing goes on the site until the credentials come out of the
        # build. A binary appearing here by accident would be caught here.
        shipped = [p for p in os.listdir("firmware")
                   if re.match(r"^\d+\.\d+\.\d+$", p)]
        check("and no firmware image is committed to this repository"
              + ("" if not shipped else "  <- " + ", ".join(shipped)),
              not shipped)

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
