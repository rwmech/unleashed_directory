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

Its own code, one other program's browser build and three fonts, which are described in the next two sections. There is no `node_modules`, no lockfile and no build step. Every other file here was written for this project and is under the GNU General Public License v3 or later, the same terms as [µnleashed BBS](https://github.com/rwmech/unleashed_BBS) itself. See [LICENSE](LICENSE).

That is a deliberate choice rather than an accident of scale. A directory that anybody can run has to be a directory anybody can read, and a dependency tree is the fastest way to make a small program unauditable.

### ESP Web Tools, in vendor/, served by /install

**[ESP Web Tools](https://github.com/esphome/esp-web-tools) 10.4.0, Apache License 2.0**, in `vendor/esp-web-tools/10.4.0/`. It is what makes the browser installer possible: the part that talks to a serial port from a web page. It is the only third-party JavaScript anywhere on this site.

The directory is the package's `dist/web` build as published on npm, checked against the registry's SHA-512 for the package before it was copied in, and changed in one file only: `install-dialog-im156JnI.js`, which carries a notice at its top saying so, as the Apache License 2.0 requires. The change sends the link a board offers after the Wi-Fi step to `/connected` on this site when it is a `telnet://` address, which a browser cannot open, and labels it "Telnet details"; `vendor/esp-web-tools/README.md` has the detail and upstream's checksum for the file. `SHA256SUMS` beside the files lets anybody check them again, and `selftest.py` does on every run. The libraries built into that bundle are Espressif's esptool-js, the Improv Wi-Fi serial SDK and Google's Material Web components (all Apache License 2.0), Lit (BSD 3-Clause), tslib (0BSD), pako (MIT and zlib) and atob-lite (MIT). Their licence texts are in `THIRD_PARTY_LICENSES.txt` in the same directory, and the installer page links it and the bundle's own `LICENSE`. `vendor/esp-web-tools/README.md` says where each file came from and how to move to a newer version.

What it costs, exactly:

- **`/install` alone.** Every other page stays HTML and one inline stylesheet, and the server will not emit the script tag for any of them.
- **Only when there is something to install.** With `firmware/` empty the page explains itself instead of offering a button, and no script tag is emitted at all.
- **From this machine.** It used to load from unpkg, pinned to an exact version. Serving it from here means nobody else learns that somebody opened the installer, and nothing it runs can change between one reader and the next unless this repository changes.

### Three display faces, in static/fonts/, served by /font/

The front page's pitch is set in a display face, served from this machine and never from a font service (site 1.2.9). Three faces are kept so that the choice between them is one word in `server.py` (`PITCH_FONT`); the page loads only the chosen one. All three are from [github.com/google/fonts](https://github.com/google/fonts) and under the **SIL Open Font License 1.1**, whose text is beside each face as `OFL-<name>.txt`:

| File | Face | Copyright | Changes |
|---|---|---|---|
| `Oxanium-latin.woff` | [Oxanium](https://github.com/sevmeyer/oxanium) | 2019 The Oxanium Project Authors | subset to Basic Latin and Latin-1, weight 500, as WOFF |
| `ChakraPetch-latin.woff` | [Chakra Petch](https://github.com/m4rc1e/Chakra-Petch) | 2018 The Chakra Petch Project Authors | subset to Basic Latin and Latin-1, Medium, as WOFF |
| `Orbitron.ttf` | [Orbitron](https://github.com/theleagueof/orbitron) | 2018 The Orbitron Project Authors, Reserved Font Name "Orbitron" | none: the upstream `Orbitron[wght].ttf` as published, because a subset is a Modified Version under the licence and may not carry a Reserved Font Name |

Neither Oxanium nor Chakra Petch reserves its name, so their subsets keep it. None of the three is sold, alone or otherwise.

The exception is `firmware/`, when it has anything in it. Those are compiled images of [µnleashed BBS](https://github.com/rwmech/unleashed_BBS), also GPL v3 or later (firmware before 1.1.0 was v2 or later), and each release directory carries its own `THIRD_PARTY_NOTICES.md` describing the code compiled into it, ESP-IDF and its components among them. That file travels with the binaries rather than pointing at a moving target, and the installer page links it beside each version.

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

No web framework, no ORM, no template engine, no font service, no analytics, no tracking of any kind. A page is HTML and one inline stylesheet, and the one web font, the pitch's, comes from this machine.

Three things qualify that, and all are named rather than buried: `/install` runs ESP Web Tools, served from this machine, when there is a firmware image to install, because a web page cannot reach a serial port without it; `/connected` runs a dozen lines written here, inline, to read the board's address out of the part of its own link that never reaches the server; and `/author` shows photographs from Wikimedia Commons. Apart from those photographs, nothing a visitor loads comes from anywhere but the machine you installed this on.
