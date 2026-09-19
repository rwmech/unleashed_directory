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
                 "name": "The Rusty Modem", "owner": "KE9CXN",
                 "description": "A BBS on a chip in a shack", "host": "",
                 "port": 6400, "nodes": 6, "busy": 2, "uptime": 900,
                 "interval": 10, "minutes24": 300, "token": ""}
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
        check("with its sysop", "KE9CXN" in page)
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
        check("the real listing still says who owns it", "KE9CXN" in page)
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
        code, page = get("/how")
        check("so is how to get listed", code == 200 and "announce" in page)

        # Pages are files in pages/, routed by name. That lookup runs last
        # on purpose: put it earlier and it swallows real endpoints, which
        # is exactly what happened to /health the first time.
        for name in ("build", "forward", "terminals", "dialing", "forward-netgear",
                     "forward-tplink", "forward-asus", "forward-xfinity",
                     "forward-mesh"):
            code, page = get("/" + name)
            check(f"/{name} renders", code == 200 and "<article>" in page)
        code, page = get("/forward")
        check("the forwarding index warns before it instructs",
              'class="warn"' in page and "responsible" in page)
        check("and names the two things that silently stop it working",
              "Double NAT" in page and "CGNAT" in page)
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
