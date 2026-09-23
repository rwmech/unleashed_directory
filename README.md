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

## One server, three faces

The same process serves three sites, chosen by the `Host` header, so one small
machine covers all of it:

| Role | Serves |
|---|---|
| **list** | the boards that are up right now, the house rules, how to get listed |
| **about** | what this is and where it came from, at length |
| **data** | the API and what is in it |

Give the installer three domains and each gets its own face. Give it one and
that domain serves the board list, with the other two faces under `/about` and
`/data`. Nothing about the split is required to run your own.

## What it does

- Takes `POST /announce` heartbeats from boards.
- Issues each board a token on its first heartbeat, so nobody else can take its listing over.
- Holds a new listing back until it has sustained heartbeats for three hours.
- Shows which boards are up, which have gone quiet, and how long each has been running.
- Shows small badges under each board's name: what it runs on, what terminals it speaks, whether guests are welcome, what is running, the causes its sysop supports, and three the directory works out for itself (new, steady, how long listed). `/badges` explains them all.
- Tells each board the public address its heartbeat arrived from, which is dynamic DNS as a side effect.
- Publishes new boards as an RSS feed at `/feed.xml`, so people can follow the list without an account, an email address or anything that knows who is reading.
- Hosts the browser installer at `/install`, which writes the BBS firmware to an ESP32 over USB from a Chrome or Edge tab, with no toolchain to set up. The images it serves live in [firmware/](firmware/README.md), which is empty today; the page says so rather than offering a download that is not there.

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
| `DIRECTORY_PAGE_CACHE` | `10` | seconds the rendered page and feed are reused |
| `DIRECTORY_FIRMWARE_DIR` | `firmware/` | where the browser installer's firmware images live |
| `DIRECTORY_FIRMWARE_KEEP` | `2` | how many releases `/install` offers, newest first |
| `DIRECTORY_LIST_DOMAIN` | | the domain that shows the board list |
| `DIRECTORY_ABOUT_DOMAIN` | | the domain that shows what this is |
| `DIRECTORY_DATA_DOMAIN` | | the domain that shows the API |

## Keeping it current

```sh
sudo ./deploy/update.sh
```

Pulls, re-installs with the domains the first install was given, restarts, then
proves the site still works and **prints the changelog entries for whatever it
just pulled in**. Safe to run when there is nothing to do.

| | |
|---|---|
| `--check` | is there an update? change nothing. Exits 2 if there is |
| `--quiet` | say nothing unless something changed or broke |
| `--install-timer` | run it daily, quietly, via a systemd timer |

For a box you will forget about:

```sh
sudo ./deploy/update.sh --install-timer
```

Daily, with a randomised delay so every directory in the world does not pull at
the same second. Watch it with `journalctl -u unleashed-directory-update`.

To be told when it happens, drop a webhook URL in place:

```sh
echo 'https://ntfy.sh/your-topic' > /etc/unleashed-directory/notify
```

Not email. Email would need a mail server on the box, and a directory's own
domains usually publish `v=spf1 -all` to say they send none, so anything it
emitted would be correctly rejected. A webhook needs neither.

## Tests

```sh
python3 selftest.py
```

Starts a directory on a scratch database and walks a listing through its whole life: first announce, token issue, the pending window, going public, a second board from the same address queueing, an attempted hijack, bad input, the three faces, the feed and the pages. 39 checks, no network access beyond loopback.

## Deploying it

On a fresh Debian or Ubuntu box:

```sh
git clone https://github.com/rwmech/unleashed_directory.git
cd unleashed_directory
sudo ./deploy/setup.sh example.com example.org example.net
```

The domains are positional and map to the three faces: **list**, **about**, **data**. With no arguments it serves plain HTTP on port 80, which is enough to try it.

Certificates are Caddy's own job. It obtains them on first start and renews them in the background, so there is no certbot here and no cron job to add.

That installs Caddy and Python, creates a `directory` system user that owns nothing but its database, writes the web configuration for your domains, starts the service, and opens ports 22, 80 and 443. Safe to run again after a `git pull`.

The full walkthrough, including making the droplet and pointing DNS at it, is in [INSTALL.md](INSTALL.md).

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

## Documentation

| File | For |
|---|---|
| [INSTALL.md](INSTALL.md) | standing one up from nothing, on a $4 droplet |
| [PROTOCOL.md](PROTOCOL.md) | the wire format, for other implementations |
| [CHANGELOG.md](CHANGELOG.md) | what changed |
| [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) | what it depends on, which is close to nothing |

## Licence

GNU General Public License v2 or later, the same terms as
[µnleashed BBS](https://github.com/rwmech/unleashed_BBS) itself. Every file
carries an SPDX line. See [LICENSE](LICENSE).

## How it was built

Parts of the code and the site were developed with the help of AI tools,
including Claude and ChatGPT. The design, the decisions and the copyright
are Robert Mech's.

## Protocol

See [PROTOCOL.md](PROTOCOL.md). It is one HTTP POST with a JSON body, about 200 bytes. Any software that sends it gets listed.
