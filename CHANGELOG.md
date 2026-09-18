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
