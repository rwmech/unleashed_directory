<!--
 ===========================================================================
  µnleashed BBS directory
 ===========================================================================

 File:         THIRD_PARTY_NOTICES.md
 Purpose:      What this depends on and under what terms. Short, because
               the answer is close to "nothing".

 Copyright 2026 - Robert Mech
 License:      GNU General Public License v2 or later
 SPDX-License-Identifier: GPL-2.0-or-later
 ===========================================================================
-->

# Third party notices

## What is in this repository

Nothing but its own code. There is no vendored library, no bundled dependency, no `node_modules`, no lockfile and no build step. Every file here was written for this project and is under the GNU General Public License v2 or later, the same terms as [µnleashed BBS](https://github.com/rwmech/unleashed_BBS) itself. See [LICENSE](LICENSE).

That is a deliberate choice rather than an accident of scale. A directory that anybody can run has to be a directory anybody can read, and a dependency tree is the fastest way to make a small program unauditable.

## What it runs on

These are installed by the operating system's package manager. They are not distributed with this software and their licences are their own.

| Component | Used for | Licence |
|---|---|---|
| [Python 3](https://www.python.org/) | the server itself, standard library only: `http.server`, `sqlite3`, `json`, `secrets`, `ipaddress`, `html`, `re` | Python Software Foundation License |
| [SQLite](https://sqlite.org/) | storage, through Python's bundled `sqlite3` module | public domain |
| [Caddy](https://caddyserver.com/) | TLS and routing in front of the server, installed by `deploy/setup.sh` from the project's own package repository | Apache License 2.0 |

Caddy is optional. The server speaks plain HTTP on its own and will run behind nginx, Apache, a tunnel, or nothing at all.

## What it does not use

No web framework, no ORM, no template engine, no JavaScript, no web fonts, no analytics, no content delivery network, no tracking of any kind. The page is HTML and one inline stylesheet. Nothing a visitor loads comes from anywhere but the machine you installed it on.
