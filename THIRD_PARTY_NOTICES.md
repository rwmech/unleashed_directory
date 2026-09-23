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

Its own code, and one other program's browser build, which is described in the next section. There is no `node_modules`, no lockfile and no build step. Every other file here was written for this project and is under the GNU General Public License v2 or later, the same terms as [µnleashed BBS](https://github.com/rwmech/unleashed_BBS) itself. See [LICENSE](LICENSE).

That is a deliberate choice rather than an accident of scale. A directory that anybody can run has to be a directory anybody can read, and a dependency tree is the fastest way to make a small program unauditable.

### ESP Web Tools, in vendor/, served by /install

**[ESP Web Tools](https://github.com/esphome/esp-web-tools) 10.4.0, Apache License 2.0**, in `vendor/esp-web-tools/10.4.0/`. It is what makes the browser installer possible: the part that talks to a serial port from a web page. It is the only JavaScript anywhere on this site.

The directory is the package's `dist/web` build, byte for byte as published on npm, checked against the registry's SHA-512 for the package before it was copied in; `SHA256SUMS` beside the files lets anybody check them again, and `selftest.py` does on every run. The libraries built into that bundle are Espressif's esptool-js, the Improv Wi-Fi serial SDK and Google's Material Web components (all Apache License 2.0), Lit (BSD 3-Clause), tslib (0BSD), pako (MIT and zlib) and atob-lite (MIT). Their licence texts are in `THIRD_PARTY_LICENSES.txt` in the same directory, and the installer page links it and the bundle's own `LICENSE`. `vendor/esp-web-tools/README.md` says where each file came from and how to move to a newer version.

What it costs, exactly:

- **`/install` alone.** Every other page stays HTML and one inline stylesheet, and the server will not emit the script tag for any of them.
- **Only when there is something to install.** With `firmware/` empty the page explains itself instead of offering a button, and no script tag is emitted at all.
- **From this machine.** It used to load from unpkg, pinned to an exact version. Serving it from here means nobody else learns that somebody opened the installer, and nothing it runs can change between one reader and the next unless this repository changes.

The exception is `firmware/`, when it has anything in it. Those are compiled images of [µnleashed BBS](https://github.com/rwmech/unleashed_BBS), also GPL v2 or later, and each release directory carries its own `THIRD_PARTY_NOTICES.md` describing the code compiled into it, ESP-IDF and its components among them. That file travels with the binaries rather than pointing at a moving target, and the installer page links it beside each version.

## One thing loaded from somewhere else

### Photographs on /author, from Wikimedia Commons

`/author` shows four photographs hotlinked from Wikimedia Commons, which permits it. They are not copied into this repository. Each is credited under the picture with its author, its licence and a link to its file page:

| Picture | Author | Licence |
|---|---|---|
| [An operator at an IBM 4381 console, 1987](https://commons.wikimedia.org/wiki/File:A_computer_operator_works_at_an_IBM_4381_four-window_work_station_in_a_computer_room_at_the_Arnold_Engineering_Development_Center,_where_numerous_mainframe_and_super_computers_are_u_-_DPLA_-_b8ef28c4e9b101b7ccc7f2e5ee1a68ed.jpeg) | SMSgt Robert Wickley, US Department of Defense | public domain (US government work) |
| [IBM 4381, Technical Museum of Brno](https://commons.wikimedia.org/wiki/File:IBM_4381.jpg) | [Tycho] (Shansov.net) | CC0 |
| [Printer band](https://commons.wikimedia.org/wiki/File:Printer_band.jpg) | Sadg4000 | CC BY 3.0 |
| [IBM Diskette 1 with envelope](https://commons.wikimedia.org/wiki/File:IBM_Diskette_1_with_envelope.gif) | Crimson Systems | public domain (scan) |

**upload.wikimedia.org sees a request** from anybody who opens `/author`, which is a third party learning that somebody looked at one page. The images are requested with `referrerpolicy="no-referrer"`, so Wikimedia is not told which page asked, and the page says in its own text where the pictures come from. Every other prose page on this site loads nothing from anywhere else.

## What it runs on

These are installed by the operating system's package manager. They are not distributed with this software and their licences are their own.

| Component | Used for | Licence |
|---|---|---|
| [Python 3](https://www.python.org/) | the server itself, standard library only: `http.server`, `sqlite3`, `json`, `secrets`, `ipaddress`, `html`, `re` | Python Software Foundation License |
| [SQLite](https://sqlite.org/) | storage, through Python's bundled `sqlite3` module | public domain |
| [Caddy](https://caddyserver.com/) | TLS and routing in front of the server, installed by `deploy/setup.sh` from the project's own package repository | Apache License 2.0 |

Caddy is optional. The server speaks plain HTTP on its own and will run behind nginx, Apache, a tunnel, or nothing at all.

## What it does not use

No web framework, no ORM, no template engine, no web fonts, no analytics, no tracking of any kind. A page is HTML and one inline stylesheet.

Two things qualify that, and both are named above rather than buried: `/install` runs ESP Web Tools, served from this machine, when there is a firmware image to install, because a web page cannot reach a serial port without it; and `/author` shows photographs from Wikimedia Commons. Apart from those photographs, nothing a visitor loads comes from anywhere but the machine you installed this on.
