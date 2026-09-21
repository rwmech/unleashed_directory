<!--
 ===========================================================================
  µnleashed BBS directory
 ===========================================================================

 File:         CHANGELOG.md
 Purpose:      What changed, newest first.

 Copyright 2026 - Robert Mech
 License:      GNU General Public License v2 or later
 SPDX-License-Identifier: GPL-2.0-or-later
 ===========================================================================
-->

# Changelog

## 0.11.0, 2026-09-21

- **Fixed: every numbered step on the router pages was one run-on paragraph.** `md_render` knew `- ` bullets and nothing else, so a line beginning `1. ` fell through to the paragraph branch and consecutive paragraph lines were joined with a space. That is **53 numbered steps across four router pages**, every one of them a wall of text, on the pages somebody reads one step at a time with a router admin page open in the other window. Nothing caught it because the text was all present and in the right order, which is what a grep checks. The dialect has ordered lists now: `/forward-mesh` renders 33 `<li>` across two `<ol>` where it used to render two paragraphs.
- The NETGEAR page's step 4 was five indented sub-bullets, which the dialect does not have and is not gaining: `md_render` tests `line.startswith("- ")` against the un-lstripped line, so they never matched, and with ordered lists in place they would have been swallowed into step 4's own `<li>` as `Fill in: - Service Name: BBS - ...`. They are a table now, which the dialect does support.

## 0.10.2, 2026-09-19

- **Fixed: coming back from a reboot was what delisted a board.** A listing that had gone quiet was demoted from `offline` to `pending` on its next heartbeat, and the public page renders `online` and `offline` but not `pending`. So a board was still listed, shown as quiet, the whole time it was switched off, and vanished the moment it reconnected. It then had to serve the three pending hours over again. Found on the live directory: a board unplugged for an hour to have an SD card wired to it came back and was gone, telling its sysop "public in 2h54m".
- A board that has already earned its listing now keeps it. Back within `DIRECTORY_RELIST_DAYS` (four) and it returns straight to `online` with its streak untouched; past that it serves the hours again, because a board nobody could call for most of a week is worth re-establishing. The window sits inside the seven day expiry on purpose: gone longer than that and there is no row left to relist.
- `public_at` is now filled in when a listing resumes, so a row that was `offline` when that column was added can still reach the feed.
- The self test had no case for the most ordinary thing that happens to a directory: a board keeps its token, goes quiet, and comes back. The nearest test covers a board that *lost* its token and accepts either state deliberately, so it walked straight past this. Eight checks now cover both sides of the window, including that the board is on the page after a day off and not on it after five.

## 0.10.1, 2026-09-19

- **Fixed: the menu shipped with no styling at all.** The stylesheet for it was written in one patch, dropped by a rewrite of that patch, and never checked, so every page ran the menu items together as plain underlined links. It is a menu bar now: reverse video on hover, the current page filled, spacing that makes the items separate things.
- The current item flashes three times on load, the way a Mac menu item did when you let go of the mouse, then settles. Three times rather than for ever, and not at all for anyone who has asked for reduced motion.

## 0.10.0, 2026-09-19

- A **dialing** page explaining why clicking a `telnet://` address often does nothing, and how to fix it. Install SyncTERM first; registry editing last, behind a warning, and using the per-user key that needs no administrator.
- It names the actual trap: Tera Term's installer takes the association but adds a verb of its own rather than replacing `open`, so a browser still reaches the stock handler, which runs a `telnet.exe` that Windows does not install by default. Also that Tera Term only negotiates telnet options on port 23, so it says nothing on a board running anywhere else.
- Linked from the Dial column on every listing and from the terminals page.

## 0.9.0, 2026-09-19

- A **Terminals** page and menu heading: what to call a board with. SyncTERM first for anyone who just wants one that works, then the modern options with their caveats, then the machines this is really for. Commodore, Atari, Apple, Amiga, MSX, Spectrum, CP/M, DOS, and actual terminals down to a Teletype Model 33 at 110 baud. Every mention of terminal software across the site links to it.
- Markdown tables, since a list of machines and what each one needs is a table, and it has to stay readable in the source while somebody edits it. They scroll rather than squeeze on a phone.

## 0.8.0, 2026-09-19

- One header, one menu and one footer on all three faces. Navigation previously existed only as a footer line that differed per page, so getting from the manifesto to the board list meant scrolling to the bottom and hoping. Cross-domain links are absolute and same-domain links relative, so a single-host deployment still works.
- Fixed the width and the floated picture, which were the same mistake: paragraphs were capped at 78ch while the photograph floated at the container edge, so the text column stopped before it reached the picture and nothing wrapped. Articles run the full width now.
- A byline at the top of the manifesto. A manifesto should say who is making the argument.
- **Freedoms gained**: eight of them, each in a box of its own, stated as freedoms rather than as features. Nobody watching, you write the rules, nobody can deplatform you, what you say stops existing when you say so, you can read and change every line, no account or email or phone number, it keeps working when nothing else does, and you choose whether to be findable at all.
- Pull quotes are indented and no longer align flush with the body text.

## 0.7.0, 2026-09-19

- Five port forwarding guides, one per router family: NETGEAR, TP-Link, ASUS, Xfinity gateways, and the app-only meshes (eero, Google Nest Wifi). Each was researched against the vendor's own documentation, and where a vendor documents nothing the page says so rather than inventing a menu path. A confidently wrong click path wastes more of a reader's time than an honest gap.
- An index page that warns before it instructs: what a port forward actually does to a home network, that telnet carries every password in the clear, that an open port is found by scanners within minutes, and the two things that silently stop it working whatever you click (double NAT, and CGNAT which no router setting can fix).
- Any file in `pages/` is now served at its own name. That lookup runs last in the routing chain on purpose: placed earlier it swallowed `/health`, which is the endpoint `update.sh` uses to decide whether a deployment worked.
- Markdown gained third-level headings and a blockquote that renders as a warning, styled to interrupt rather than blend in.

## 0.6.2, 2026-09-19

- One width across all three faces. `main` was already 1080 everywhere, but `article` capped itself at 78ch, so the pages built from articles sat narrower than the board list and it looked like two different sites. The frame is now one job, and the reading measure applies only to body text.
- The sparkline in the table is drawn rather than typed, like the chart behind it. It is the version everybody actually sees, since the full chart is behind a click.
- Activity says what it means: "11 calls, 7h 20m connected" rather than "440 caller-min/24h", which read as calls per minute and was therefore about a thousand times the truth.
- A photograph of the board, with a caption.

## 0.6.1, 2026-09-19

- Two notes from QuantumRob on the manifesto: starting his career on IBM 4381 mainframes, which sits directly under the paragraph about people who were never given time on one, and an acknowledgement that the project was built with Claude's help.

## 0.6.0, 2026-09-19

- A **Build one** page, written as Markdown in `pages/` and rendered by the server, so the prose lives in a file somebody can edit rather than inside a Python string. What you need, how to flash it, how to call it, and what forwarding a port actually means.
- Pages are 1080 wide instead of 900. The terminal look does not require a column of text a third of the way across a monitor. Prose keeps a readable measure inside that; diagrams and charts get the full width.
- The busy-hours chart is drawn as SVG rather than block characters. Block art reads as an affectation on a web page and lands differently in every font. Same information, still no JavaScript, and it scales to a phone on its own.
- The manifesto has a section about the hardware, because "a five dollar chip" is a good line and not a description: what an ESP32 actually is, how it compares to the 64 KB machine CBBS ran on, and why that is the argument in one object.
- Photographs: drop images in `static/` and they appear on the manifesto, captioned from `static/captions.txt`. The section is simply absent when the folder is empty. Filenames are validated rather than paths, so there is nothing to climb out of.

## 0.5.2, 2026-09-19

- The manifesto carries a note from QuantumRob about meeting Ward Christensen once, at a Maker Faire, before he died in October 2024.
- `dbtool.sh` deletes a listing's chart data along with the listing. Orphaned rows meant a board that was deduped away kept samples nothing could read, while the survivor looked like it had no history.

## 0.5.1, 2026-09-19

- **Fixed: a board that lost its token could never list again.** Yesterday's cap refused any new entry from an address already holding a few, which stopped the table growing but also permanently locked out the ordinary case it was meant to tolerate: a board that was reflashed. Worse, the board reported it as "too often, will settle", and settling was the one thing that could not happen. At the cap the directory now drops the deadest entry that address holds and lets the board in. An entry still sending heartbeats is never evicted, whoever it belongs to, so a stranger sharing an address still cannot push a live board out.
- A listing that has gone quiet no longer holds a published slot against a board that is actually answering.

## 0.5.0, 2026-09-19

When a board is worth calling.

- Every listing can now show when it is actually busy: a sparkline of the day in the table, and a bar chart of all twenty four hours when you click it. Hours run in the board's own local time, so "busiest 20:00-22:00" means the evening where the board is, not somewhere else.
- It needs nothing new from anybody. Every heartbeat already carries how many callers are on, so the chart is built from figures the board is publishing anyway, and nothing about any individual caller is collected, stored or inferred.
- Boards send `tz`, their offset from UTC, so the hours can be bucketed locally. Older boards simply bucket at UTC.
- A board's samples are halved once it has four weeks of them, so a board that changes its habits is followed within a few weeks rather than being judged for ever on its first month. A chart is not drawn at all until there is a day of heartbeats behind it, because a shape drawn from one afternoon is a rumour, not a forecast.
- Still no JavaScript: the chart expands with `<details>`.

## 0.4.0, 2026-09-19

Stops one board being able to fill the table.

- **Fixed: a board that forgot its token created a new listing on every heartbeat.** The per-address rule only ever decided what *state* a new row was given, and then inserted it regardless, so nothing bounded the table. A live directory reached ninety rows for one board in fourteen hours. An address may now hold a small number of entries and is refused beyond that. This was also a spam hole needing no board at all: curl in a loop would have done it.
- A listing stuck in `queued` is re-considered on every heartbeat. Previously `settle()` only promoted `pending` and the update path only moved `offline` back to `pending`, so a queued board heartbeated for ever, never expired, and never got in.
- An unknown token still never takes over an existing listing. That guarantee is deliberate: two unrelated boards can share one public address, which is what carrier-grade NAT does to whole towns, so "same address" is nowhere near "same board".
- The board list refreshes itself once a minute. Who is on changes minute to minute and a list left open in a tab should not quietly go stale. A meta refresh, not a script, because this site still ships no JavaScript.
- The list shows how many callers are on each board, and how old that reading is, since a board reporting every ten minutes cannot be more current than that. The heading totals the callers across the whole directory.
- `deploy/dbtool.sh`: status, list, dupes, dedupe, prune, promote, forget, unstick, reset and restore. Everything that writes takes a backup first and prints the command to undo it.

## 0.3.0, 2026-09-18

The site gets a face.

- A wordmark across all three domains: a 6x12 pixel face drawn with half-block characters, which carry two pixels per cell vertically and so allow a real stroke weight instead of the chunky squares a plain block font gives. The capitals sit on a baseline two rows from the bottom and the micro sign is set at an x-height with its stem carrying on below, so it is a real descender rather than a letter squashed to fit. It scales with the viewport, so it never overflows a phone.
- The micro sign is in the name now. The page was always UTF-8, the default name just never used it. The systemd unit carries it too, otherwise the unit wins and the code change does nothing.
- A board's address is a `telnet://` link. No browser ships a telnet client; they hand the scheme to whatever the operating system registered, which for this audience is usually SyncTERM or mTelnet. The address stays plain selectable text, so the link costs nothing for anyone without one. Still no JavaScript anywhere on the site.
- Colours: each one now has exactly one job. Green previously meant board name, online, pull quote and code all at once, which is the same as meaning nothing. Green is live, amber is the human, violet is a board's own identity, blue is something you can act on, orange is activity, cyan is structure.

## 1.2.0, 2026-09-18

- `deploy/update.sh`: pull, re-install with the domains this box was set up with, restart, and then prove the site still works. It prints the changelog entries for whatever it pulled in, which is the thing actually worth reading on a machine you have not looked at in a month.
- `--install-timer` runs it daily through a systemd timer, with a randomised delay and quiet unless something changed or broke. `--check` reports whether an update exists without touching anything.
- An optional webhook in `/etc/unleashed-directory/notify` says when it happened. Not email: that needs a mail server on the box, and a directory's own domains usually publish `v=spf1 -all`, which declares that they send none.
- The update verifies the thing that matters most before calling itself a success: that `/announce` is still answered over plain HTTP. A redirect there breaks every board on the network silently.
- `setup.sh` remembers the domains it was given in `/etc/unleashed-directory/domains`, so updates cannot drift from the install.
- Fixed: the deploy scripts were committed without the executable bit, so `./deploy/setup.sh` gave permission denied on a fresh clone.

## 1.1.0, 2026-09-18

- One server, three faces, chosen by the `Host` header: the board list, a page explaining what this is and where it came from, and a page documenting the API. A single domain still serves all of it.
- The about page carries the argument at length: the history from CBBS in 1978 to the 60,000 boards of the mid-1990s, what replaced them, what this hands back, and a privacy section that draws the difference as two ASCII flowcharts. Calling a website passes through DNS, a CDN, a load balancer, analytics, an ad exchange and a data broker; calling a board goes through your router to a chip you own. There is also a repeating ASCII animation, done in CSS, because the site still has no JavaScript in it and that is worth keeping true.
- `/feed.xml`: newly public boards as RSS. A feed is the privacy-forward way to follow something, since the reader pulls when it likes and nothing here knows who is reading. `public_at` is stamped once, the first time a board earns its listing, so a board coming back from a nap is not re-announced.
- Existing databases are migrated for `public_at` on start.

## 1.0.0, 2026-09-18

First working directory.

- `POST /announce` takes heartbeats and keeps a list of the boards sending them.
- A token is issued on the first heartbeat and the board saves it, so nobody else can take a listing over. Stated plainly in the protocol that this is not a spam control, because tokens are free to mint.
- A listing is held back until it has sustained heartbeats for three hours, then goes `online`. Missing three of its own intervals marks it `offline` rather than deleting it, so a reboot does not cost a board the hours it spent becoming public. Seven days of silence frees the name.
- One automatic listing per address, counted per `/64` on IPv6. Further ones queue for a human.
- Rate limit on the endpoint, and a size cap on the body.
- `X-Seen-Address` tells a board the public address its heartbeat came from, which makes this a rough dynamic DNS as a side effect.
- The public page, the house rules, how to get listed, and `/api/boards.json`. Dark, monospace, no JavaScript, no fonts, no trackers.
- The page and the JSON are rendered at most once every ten seconds and served from memory in between, and the cache is dropped the moment a listing changes state, so a board that has just gone public appears immediately.
- It never makes outbound connections, so it cannot be pointed at somebody's internal network.
- `selftest.py`: 28 checks covering the whole life of a listing, including an attempted hijack.
- `deploy/setup.sh` takes the domains on the command line and writes the web configuration for them, so somebody else can run a directory without editing anything. INSTALL.md walks through it on a $4 droplet.
- PROTOCOL.md documents the wire format for other implementations.
