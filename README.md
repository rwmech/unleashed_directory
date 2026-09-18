<!--
 ===========================================================================
  µnleashed BBS directory
  A list of boards that are actually up.
 ===========================================================================

 File:         README.md
 Purpose:      What this is, how to run it, and how to run your own.

 Copyright 2026 - Robert Mech
 License:      GNU General Public License v2 or later
 SPDX-License-Identifier: GPL-2.0-or-later
 ===========================================================================
-->

# unleashed BBS directory

A list of BBS boards that are up right now. Boards announce themselves with a small heartbeat every few minutes; this keeps the list and serves it as a web page and as JSON.

It is the server behind [unleashedbbs.com](https://unleashedbbs.com), and it is deliberately small enough that you can run your own instead. The protocol is published, the default directory in the board firmware is a setting, and a board can announce to several directories at once. A list nobody can replace would be the wrong shape for a project about not depending on anybody.

Companion to [µnleashed BBS](https://github.com/rwmech/unleashed_BBS), though it will list anything that speaks the protocol.

## What it does

- Takes `POST /announce` heartbeats from boards.
- Issues each board a token on its first heartbeat, so nobody else can take its listing over.
- Holds a new listing back until it has sustained heartbeats for three hours.
- Shows which boards are up, which have gone quiet, and how long each has been running.
- Tells each board the public address its heartbeat arrived from, which is dynamic DNS as a side effect.

## What it will not do

**It never makes outbound connections.** A directory that connects to whatever host and port a stranger posts to it is a port scanner with a public API, and the first person to notice would point it at somebody's internal network. A listing earns its place by sustaining heartbeats, not by being probed.

## Running it

Nothing to install beyond Python 3. No dependencies, no virtualenv, no build step.

```sh
python3 server.py
```

Then point a board at `http://127.0.0.1:8080/announce`.

Settings come from the environment, so a deployment never edits the code:

| Variable | Default | What it is |
|---|---|---|
| `DIRECTORY_DB` | `directory.db` | SQLite file |
| `DIRECTORY_HOST` | `127.0.0.1` | bind address. Leave it on loopback and put a web server in front |
| `DIRECTORY_PORT` | `8080` | bind port |
| `DIRECTORY_NAME` | `unleashed BBS directory` | the title on the page |
| `DIRECTORY_PENDING_HOURS` | `3` | continuous heartbeats before a listing is public |
| `DIRECTORY_EXPIRE_DAYS` | `7` | silence before a listing is deleted and its name freed |
| `DIRECTORY_PER_ADDRESS` | `1` | automatic listings per address, per `/64` on IPv6. The rest queue for a human |
| `DIRECTORY_MIN_SECONDS` | `30` | minimum gap between accepted heartbeats from one address |

## Tests

```sh
python3 selftest.py
```

Starts a directory on a scratch database and walks a listing through its whole life: first announce, token issue, the pending window, going public, a second board from the same address queueing, an attempted hijack, bad input, and the pages. 28 checks, no network access beyond loopback.

## Deploying it

On a fresh Debian or Ubuntu box:

```sh
git clone https://github.com/rwmech/unleashed_directory.git
cd unleashed_directory
sudo ./deploy/setup.sh
```

That installs Caddy and Python, creates a `directory` system user that owns nothing but its database, installs the service and the web configuration, and opens ports 22, 80 and 443. It is safe to run again after a `git pull`.

⚠️ **The one thing not to change in `deploy/Caddyfile`:** `/announce` must stay reachable over plain HTTP with **no redirect to HTTPS**. Boards are microcontrollers with no TLS stack. Caddy's default is to redirect every `http://` request, and a board that receives a 308 reports it to its sysop as "refused" with no way to find out why. The supplied configuration carves that one path out and sends everything else to HTTPS.

## Moderation

There is no admin interface yet, on purpose. The database is SQLite and the operations are one line each:

```sh
sqlite3 /var/lib/unleashed-directory/directory.db

-- what is waiting for a human
SELECT id, name, owner, address, description FROM boards WHERE state='queued';

-- let one through
UPDATE boards SET state='pending', streak_start=strftime('%s','now') WHERE id=7;

-- remove one, and stop it coming back under the same token
DELETE FROM boards WHERE id=7;

-- what has been reported
SELECT * FROM reports ORDER BY at DESC;
```

## House rules for the instance at unleashedbbs.com

- No hate. A board whose name or description attacks people for who they are does not get listed.
- Be honest about what you are.
- It is public. Everything sent appears on the page.
- Get along.

**These rules bind the directory, not its users.** Anyone can run one with different rules, or none. Delisting a board removes it from one web page; it does not remove it from the internet, and it was never meant to.

## Protocol

See [PROTOCOL.md](PROTOCOL.md). It is one HTTP POST with a JSON body, about 200 bytes. Any software that sends it gets listed.
