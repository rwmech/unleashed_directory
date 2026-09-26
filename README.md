<!--
 ===========================================================================
  µnleashed BBS directory
  A list of boards that are actually up.
 ===========================================================================

 File:         README.md
 Purpose:      What this is, how to run it, and how to run your own.

 Copyright 2026 - Robert Mech
 License:      GNU General Public License v3 or later
 SPDX-License-Identifier: GPL-3.0-or-later
 ===========================================================================
-->

# unleashed BBS directory

A list of BBS boards that are up right now. Boards announce themselves with a small heartbeat every few minutes; this keeps the list and serves it as a web page and as JSON.

It is the server behind [unleashedbbs.net](https://unleashedbbs.net), and it is deliberately small enough that you can run your own instead. The protocol is published, the default directory in the board firmware is a setting, and a board can announce to several directories at once. A list nobody can replace would be the wrong shape for a project about not depending on anybody.

Companion to [µnleashed BBS](https://github.com/rwmech/unleashed_BBS), though it will list anything that speaks the protocol.

## What is in it, and what is not

This repository is the directory and nothing else: the list, the announce
API, the badges, the data and the house rules, and the guides when you give
it them. Until 2026-09-26 the same server was also the project's own site
and its manifesto; those moved to a server of their own at
[unleashedbbs.com](https://unleashedbbs.com) and
[unleashedbbs.org](https://unleashedbbs.org), so running a directory no
longer means hosting anybody's installer or pitch.

| Path | What |
|---|---|
| `/`, `/directory` | the boards that are up, busiest first, with the badge filter and a search |
| `/badges` | what every badge means, searchable |
| `/how`, `/rules` | how to get listed, and the house rules |
| `/data`, `/api/boards.json`, `/feed.xml` | the data: what the API gives, the JSON, and new boards as RSS |
| `/announce` | the heartbeat, `POST` only |
| `/docs/<page>`, `/skins/<file>` | the guides and the stock display skins, when a checkout of [unleashed_documentation](https://github.com/rwmech/unleashed_documentation) is given to it |
| `/health` | `ok`, for uptime checks |

With `DIRECTORY_HOME_URL` set, a path this server does not have (an old
link to `/install`, `/hardware` or the manifesto) is answered with a 301 to
the same path there, and an old top-level guide address (`/setup`,
`/terminals`) with a 301 to `/docs/<page>`. Without it, such a path is
simply not found.

## What it does

- Takes `POST /announce` heartbeats from boards.
- Issues each board a token on its first heartbeat, so nobody else can take its listing over.
- Holds a new listing back until it has sustained heartbeats for three hours.
- Shows which boards are up, which have gone quiet, which their sysop has closed for now (listed as temporarily closed, with no link to dial, after the open ones), and how long each has been running.
- Shows small badges under each board's name: what software and version it runs and what it runs on, what terminals it speaks, whether guests are welcome, what is running, the size of its SD card, the causes its sysop supports (two dozen, from literacy to heart health), what its sysop is into (about forty interests, from the Commodore 64 to amateur radio and gardening), and four the directory works out for itself (new, steady, how long listed, and whether a µnleashed board is behind the newest firmware release). `/badges` explains them all and can be searched.
- Names each cause and interest by a short code of up to six letters and digits, such as `MNTLH` for mental health, read in any case, with the longer names it used before kept as aliases. The whole list, codes, names, meanings and aliases, is one plain JSON file, [badges.json](badges.json), so other software can read the same list.
- Filters the board list by badge: a Filter button opens every badge as small chips, a row per group, and picking some shows the boards carrying all of them, or any. It works without JavaScript, and every filtered view is a link, such as `/?b=petscii&b=ham`, with a search by name, sysop or description (`?q=`).
- Tells each board the public address its heartbeat arrived from, which is dynamic DNS as a side effect.
- Publishes new boards as an RSS feed at `/feed.xml`, so people can follow the list without an account, an email address or anything that knows who is reading.
- Serves the guides at `/docs`, from a checkout of `unleashed_documentation`: joining a board, setting one up, letting people outside your home in, SD cards, lights, cameras and skins. They are written in the same small Markdown dialect as this server's own pages, and the drawings they name are drawn here.
- Knows the newest µnleashed firmware release when it can read the folder the project's installer keeps its images in (`DIRECTORY_FIRMWARE_DIR`, read-only): that release lights the update arrow on a board that is behind, the announcement above the list, and the guides' "from this release" passages. A directory without that folder has none of the three.

## What it will not do

**It never makes outbound connections.** A directory that connects to whatever host and port a stranger posts to it is a port scanner with a public API, and the first person to notice would point it at somebody's internal network. A listing earns its place by sustaining heartbeats, not by being probed.

## Running it

Nothing to install beyond Python 3. No dependencies, no virtualenv, no build step.

```sh
python3 server.py
```

Then point a board at `http://127.0.0.1:8080/announce`.

The page engine (the stylesheet, the wordmark, the glossary and the Markdown dialect) is `sitekit.py`, beside `server.py`. The project's own site carries a byte-for-byte copy of it, and this repository's is the one that is edited: change `SITEKIT_VERSION` with every change.

Settings come from the environment, so a deployment never edits the code:

| Variable | Default | What it is |
|---|---|---|
| `DIRECTORY_DB` | `directory.db` | SQLite file |
| `DIRECTORY_HOST` | `127.0.0.1` | bind address. Leave it on loopback and put a web server in front |
| `DIRECTORY_PORT` | `8080` | bind port |
| `DIRECTORY_NAME` | `µnleashed BBS directory` | the title on the page |
| `DIRECTORY_URL` | `https://unleashedbbs.net` | this directory's own address, for canonical links and link previews when no domain is set |
| `DIRECTORY_LIST_DOMAIN` | | the domain it answers as |
| `DIRECTORY_HOME_URL` | | the project's own site: named in the menu, and where a path this server does not have is sent. Empty for a directory of your own |
| `DIRECTORY_DOCS_DIR` | `docs/` | the guides: a checkout of `unleashed_documentation`, or its `pages/`, `shots/` and `skins/` |
| `DIRECTORY_FIRMWARE_DIR` | `firmware/` | a folder of firmware releases, read-only, for the update arrow and the guides' gates |
| `DIRECTORY_PENDING_HOURS` | `3` | continuous heartbeats before a listing is public |
| `DIRECTORY_EXPIRE_DAYS` | `7` | silence before a listing is deleted and its name freed |
| `DIRECTORY_PER_ADDRESS` | `1` | automatic listings per address, per `/64` on IPv6. The rest queue for a human |
| `DIRECTORY_MIN_SECONDS` | `30` | minimum gap between accepted heartbeats from one board: its token, or its address and port when it has none |
| `DIRECTORY_ADDRESS_PER_MINUTE` | `20` | most accepted announces from one address in a minute, whatever boards it posts as. `0` switches it off |
| `DIRECTORY_PAGE_CACHE` | `10` | seconds the rendered page and feed are reused |

## Keeping it current

```sh
sudo ./deploy/update.sh
```

Pulls, pulls the guides too when `/etc/unleashed-directory/docs` names a
checkout of them, re-installs with the domain the first install was given,
restarts, then proves the site still works and **prints the changelog
entries for whatever it just pulled in**. Safe to run when there is nothing
to do.

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
domains usually publish `v=spf1 -all` to say they send no mail, so anything it
emitted would be correctly rejected. A webhook needs neither.

## Tests

```sh
python3 selftest.py
```

Starts a directory on a scratch database and walks a listing through its whole life: first announce, token issue, the pending window, going public, a second board from the same address queueing, an attempted hijack, bad input, the feed, the pages, the badges, their codes and the filter, databases made by older versions, the guides and the old addresses that lead to them, the update arrow over releases on disk, and the deploy scripts. About 500 checks in a few minutes, no network access beyond loopback. It wants the guides: a checkout of `unleashed_documentation` as `docs/` or beside this one, or `SELFTEST_DOCS` naming it. It binds five ports on 127.0.0.1 from 8123 up; `SELFTEST_PORT=18765 python3 selftest.py` moves them.

## Deploying it

On a fresh Debian or Ubuntu box:

```sh
git clone https://github.com/rwmech/unleashed_directory.git
git clone https://github.com/rwmech/unleashed_documentation.git
sudo install -d /etc/unleashed-directory
echo "$PWD/unleashed_documentation" | sudo tee /etc/unleashed-directory/docs
cd unleashed_directory
sudo ./deploy/setup.sh example.net
```

The domain is the directory's; any more after it are served the same site. With no arguments it serves plain HTTP on port 80, which is enough to try it. Leave out the guides and there is no `/docs`.

Certificates are Caddy's own job. It obtains them on first start and renews them in the background, so there is no certbot here and no cron job to add.

That installs Caddy and Python, creates a `directory` system user that owns nothing but its database, writes its sites into `/etc/caddy/sites/directory.caddy` and a `/etc/caddy/Caddyfile` that gathers every file in that folder (so another service on the same box can add its own), starts the service, and opens ports 22, 80 and 443. Safe to run again after a `git pull`.

The full walkthrough, including making the droplet and pointing DNS at it, is in [INSTALL.md](INSTALL.md).

⚠️ **The one thing not to change in the web configuration:** `/announce` must stay reachable over plain HTTP with **no redirect to HTTPS**. Boards are microcontrollers with no TLS stack. Caddy's default is to redirect every `http://` request, and a board that receives a 308 reports it to its sysop as "refused" with no way to find out why. The supplied configuration carves that one path out and sends everything else to HTTPS. On a box that also serves other domains a board might have been pointed at, those domains must send `/announce` here the same way.

### Upgrading a box set up before 2.0.0

A box set up by an older `setup.sh` was given up to three domains (the list, the manifesto and the data) and wrote one Caddyfile holding all of them. From 2.0.0 it takes the directory's own domain, and its `setup.sh` will not replace an old Caddyfile while that would leave any domain in it unserved: install whatever serves the others first (on the project's droplet, the main site), put this directory's domain alone in `/etc/unleashed-directory/domains`, and run `update.sh`.

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

## House rules for the instance at unleashedbbs.net

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

GNU General Public License v3 or later, the same terms as
[µnleashed BBS](https://github.com/rwmech/unleashed_BBS) itself. Every file
carries an SPDX line. See [LICENSE](LICENSE). The guides it serves are a
separate repository under CC BY-SA 4.0.

## How it was built

Parts of the code and the site were developed with the help of AI tools,
including Claude and ChatGPT. The design, the decisions and the copyright
are Robert Mech's.

## Protocol

See [PROTOCOL.md](PROTOCOL.md). It is one HTTP POST with a JSON body, about 200 bytes. Any software that sends it gets listed.
