<!--
 ===========================================================================
  µnleashed BBS directory
 ===========================================================================

 File:         THIRD_PARTY_NOTICES.md
 Purpose:      What this depends on and under what terms. Short, because
               the answer is close to "nothing".

 Copyright 2026 - Robert Mech
 License:      GNU General Public License v3 or later
 SPDX-License-Identifier: GPL-3.0-or-later
 ===========================================================================
-->

# Third party notices

## What is in this repository

Its own code and nothing else. There is no `node_modules`, no lockfile, no vendored code and no build step. Every file here was written for this project and is under the GNU General Public License v3 or later, the same terms as [µnleashed BBS](https://github.com/rwmech/unleashed_BBS) itself. See [LICENSE](LICENSE).

That is a deliberate choice rather than an accident of scale. A directory that anybody can run has to be a directory anybody can read, and a dependency tree is the fastest way to make a small program unauditable.

Until 2026-09-26 this repository was also the project's own site, and carried ESP Web Tools for the browser installer, three display fonts and firmware images. Those moved with the site. What this server serves beside its own pages comes from two places a deployment gives it, and neither is part of this repository:

- **the guides**, a checkout of [unleashed_documentation](https://github.com/rwmech/unleashed_documentation), under the Creative Commons Attribution-ShareAlike 4.0 International licence, served at `/docs` with the stock display skins' pictures and zips at `/skins`;
- **firmware releases**, read and never served, only to know the newest version: compiled images of µnleashed BBS, GPL v3 or later, each carrying its own notices.

## What it runs on

These are installed by the operating system's package manager. They are not distributed with this software and their licences are their own.

| Component | Used for | Licence |
|---|---|---|
| [Python 3](https://www.python.org/) | the server itself, standard library only: `http.server`, `sqlite3`, `json`, `secrets`, `ipaddress`, `html`, `re` | Python Software Foundation License |
| [SQLite](https://sqlite.org/) | storage, through Python's bundled `sqlite3` module | public domain |
| [Caddy](https://caddyserver.com/) | TLS and routing in front of the server, installed by `deploy/setup.sh` from the project's own package repository | Apache License 2.0 |

Caddy is optional. The server speaks plain HTTP on its own and will run behind nginx, Apache, a tunnel, or nothing at all.

## What it does not use

No web framework, no ORM, no template engine, no font service, no analytics, no tracking of any kind. A page is HTML and one inline stylesheet.

One thing qualifies that, and it is named rather than buried: the board list and `/badges` run a few dozen lines written here, inline, that narrow the list and the badges as a reader picks and types. Both pages are whole without them. Nothing a visitor loads comes from anywhere but the machine you installed this on.
