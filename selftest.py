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

import json
import os
import subprocess
import sys
import tempfile
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


def get(path, host=None):
    req = urllib.request.Request(f"{BASE}{path}")
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        # A 404 is an answer, not a failure. Checking that something is
        # absent is as much a test as checking it is there.
        return e.code, e.read().decode(errors="replace")


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
    try:
        for _ in range(50):                          # wait for it to answer
            try:
                get("/health")
                break
            except Exception:
                time.sleep(0.1)

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
                     "firstcall", "privacy", "whofor",
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
              "calls<br>" in page and "connected</td>" in page)
        check("the page title outranks the text under it",
              "h1 {{ color:var(--ink); font-size:20px" .replace("{{", "{") in page)
        check("nothing that is words is left below --dim",
              "footer {{ margin-top:28px; color:var(--dim)".replace("{{", "{") in page)
        _, page = get("/sdcard")
        check("a callout is indented from the body text, not flush with it",
              "margin:18px 0 18px 30px" in page)
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
