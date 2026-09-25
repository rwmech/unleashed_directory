<!-- What makes it different (site 1.2.4, Rob: "See what Unleashed can do that other BBS systems cant"). Every line links to the page that shows it. No "only" is claimed, because espbbs (github.com/snazzware/espbbs) already runs a telnet BBS on an ESP8266, and the table says so. The power figure is /hardware's: about a tenth of an amp while the dev board waits, at 5 V from USB, 0.5 W, 4.38 kWh a year. Items marked 1.1.0 are the lights on the dev board (1.1.0-dev.4), nightly backups (dev.6) and the BOOT reset (dev.3); the camera is coming soon. The two lists swap on the day a 1.1.0 release is on disk. The URL is /different: one plain word, which says what the page is about and reads the same said aloud. Site 1.2.9 (Rob): the machines named are a varied set from the firmware's CLIENTS.md rather than one favourite; the drive light is optional; the S3's screen is from the firmware's CHANGELOG 1.1.0-dev.10; the card's 32 GB is /sdcard's FAT32 limit; linked chat is on /roadmap under Later and not built. Site 1.3.0 (Rob): plain words with the BBS terms bridged in by the glossary, the BBS table in words a newcomer gets at a glance, and a second table against the places people build a community today (COMPARE_TODAY_ROWS in server.py, whose sources are listed beside it there). "Privacy forward, or a privacy policy" (site 1.3.6, Rob: a table, green "Privacy forward" against "Privacy policies"; it was "What is on those sites", a list) is from each company's own terms and privacy policy, read on 2026-09-25, its rows in PRIVACY_ROWS in server.py; tracker scans (Blacklight, Exodus) could not be run from here, so no counts are quoted. -->
# What a board can do

A whole [[BBS]], a community of your own, on a board about the size of a stick
of gum. It answers a computer from the eighties and a laptop from this year in
the same chat room, runs all year on a phone charger, and goes from the box to
its first visitor in about five minutes. Here is what that adds up to.

::: until 1.1.0
- **[No computer needed.](/hardware)** The board is the whole BBS: no PC, no
  Raspberry Pi, and nothing to keep updating underneath it. The dev board
  costs about $5.
- **[Installed from your browser.](/install)** Plug the board in, press a
  button, and set its Wi-Fi on the same page. No programming tools, and about
  five minutes.
- **[Works with any computer, old or new.](/firstcall)** It works out what
  each visitor is joining from as they connect, and draws its screens to fit.
- **[A library on a card.](/hardware#esp32-dev-board-base-sd-card-for-storage)**
  A micro SD card of up to 32 GB holds a shared library of files people can
  download, even to computers from the 1980s.
- **[Hardware you can watch.](/lights)** An optional drive light that flickers
  as the board works and a strip of lights that brightens as visitors arrive,
  on the ESP32 dev board from software version 1.1.0.
- **[A screen of its own, one step up.](/hardware#waveshare-esp32-s3-lcd-1-47)**
  The Waveshare S3, about $20, shows who is on, one row a person, with the
  board's name, address and uptime taking turns at the top, a Wi-Fi antenna
  that fills with the signal, and small icons that appear for waiting mail,
  someone asking for the host and an upload to approve.
- **[A camera visitors can use.](/camera)** Coming soon: type `SNAPSHOT` from
  any computer that connects, and download the picture a few seconds later.
- **[It looks after itself.](/sdcard)** From software version 1.1.0, a backup
  to the SD card every night, and a forgotten host password put right by
  holding the BOOT button, with nothing to reinstall.
- **[It puts itself on the map.](/how)** Switch on the listing and the board
  appears on this directory by itself. There is no form to fill in.
- **[About half a watt.](/hardware#esp32-dev-board-base)** A tenth of an amp from a
  phone charger while it waits, so a year of it is about 4.4 kWh.
- **[Coming: one chat across many boards.](/roadmap)** Chat rooms linked
  between boards, so a quiet board borrows company from a busy one: other
  µnleashed boards, and Diversi-DIAL and GTalk-style systems, in one
  superchat. It is on the roadmap, not built yet.
:::
::: from 1.1.0
- **[No computer needed.](/hardware)** The board is the whole BBS: no PC, no
  Raspberry Pi, and nothing to keep updating underneath it. The dev board
  costs about $5.
- **[Installed from your browser.](/install)** Plug the board in, press a
  button, and set its Wi-Fi on the same page. No programming tools, and about
  five minutes.
- **[Works with any computer, old or new.](/firstcall)** It works out what
  each visitor is joining from as they connect, and draws its screens to fit.
- **[A library on a card.](/hardware#esp32-dev-board-base-sd-card-for-storage)**
  A micro SD card of up to 32 GB holds a shared library of files people can
  download, even to computers from the 1980s.
- **[Hardware you can watch.](/lights)** An optional drive light that flickers
  as the board works and a strip of lights that brightens as visitors arrive.
- **[A screen of its own, one step up.](/hardware#waveshare-esp32-s3-lcd-1-47)**
  The Waveshare S3, about $20, shows who is on, one row a person, with the
  board's name, address and uptime taking turns at the top, a Wi-Fi antenna
  that fills with the signal, and small icons that appear for waiting mail,
  someone asking for the host and an upload to approve.
- **[A camera visitors can use.](/camera)** On the Freenove camera board, type
  `SNAPSHOT` from any computer that connects, and download the picture a few
  seconds later.
- **[It looks after itself.](/install#if-something-goes-wrong-reset-rather-than-reflash)**
  A backup to the SD card every night, and a forgotten host password put
  right by holding the BOOT button, with nothing to reinstall.
- **[It puts itself on the map.](/how)** Switch on the listing and the board
  appears on this directory by itself. There is no form to fill in.
- **[About half a watt.](/hardware#esp32-dev-board-base)** A tenth of an amp from a
  phone charger while it waits, so a year of it is about 4.4 kWh.
- **[Coming: one chat across many boards.](/roadmap)** Chat rooms linked
  between boards, so a quiet board borrows company from a busy one: other
  µnleashed boards, and Diversi-DIAL and GTalk-style systems, in one
  superchat. It is on the roadmap, not built yet.
:::

It is the same idea as the boards of the 1980s, where the computer on the desk
was the BBS: an Apple II, an Atari 800 or a TRS-80 in somebody's spare room.
This time the computer is a chip, Wi-Fi is the phone line, and you can build
one this weekend.

::: next
[Build one](/build)
:::

## How it compares with the apps people use now

Most online communities today live inside somebody else's service: a chat
app, a social media group, a hosted forum. Those are easy to start and easy to
find. A board is the other kind of place, one you own. Here is how the two
compare, with each column checked against the company's own pages.

::: compare-today
:::

## Privacy forward, or a privacy policy

On the left, what a µnleashed board does. On the right, what Discord and Meta,
which runs Facebook Groups, say in their own terms and privacy policies, read
in September 2026. Each name links to the page it is quoted from.

::: privacy-compare
:::

Hosted forums and Mastodon servers depend on whoever runs them, and plenty
are good: Discourse says on [its pricing
page](https://www.discourse.org/pricing) that "your data always belongs to
you" and lets you download a backup, and Mastodon says it "will never serve
ads" and lets an account [move to another
server](https://joinmastodon.org/servers).

A µnleashed board has no ads, no trackers and no outside scripts, and what
members write stays on the host's board. This website runs no analytics
either. The listing tells this directory only what the list shows: the
board's name and description, its host's name, its address and port, how
many lines it has and how many are in use, how long it has been up, its time
zone, and any badges the host chose; the day's call counts only if the host
asks to share them; nothing about who is on; and nothing at all until the
host switches the listing on.

The honest part, because it matters: the words between a member and a board
travel as plain text, the way they always did on a BBS. Anyone in a position
to listen on the way could read them, the way the next table in a café could
hear you. [What that means in practice](/privacy), and the short version: say
what you would say in public, and use a password you use nowhere else. An
encrypted way in, [[SSH]], is coming on the ESP32-S3 boards in firmware
1.2.0, beside telnet rather than instead of it; it is [on the
roadmap](/roadmap) and not released yet.

## How it compares with other BBS software

The BBS programs you are most likely to have met are good software with years
of work in them, and each one runs on a PC with an operating system under it.
µnleashed is [[firmware]], the software that lives on the board, and the $5
board is the whole computer. Each project's name links to its own pages, which
is where its column was checked, in September 2026.

::: compare
:::
