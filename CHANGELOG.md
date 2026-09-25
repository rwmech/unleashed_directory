<!--
 ===========================================================================
  µnleashed BBS directory
 ===========================================================================

 File:         CHANGELOG.md
 Purpose:      What changed, newest first.

 Copyright 2026 - Robert Mech
 License:      GNU General Public License v3 or later
 SPDX-License-Identifier: GPL-3.0-or-later
 ===========================================================================
-->

# Changelog

## 1.2.7, 2026-09-25

The ESP32 dev board is two entries on /hardware (Rob: "esp32 is misleading
with flash and go, it has to have an sd card"), and the Freenove camera
board's sensor is corrected from Rob's bench.

- **ESP32 dev board** keeps its flash & go seal, and says what it does with
  no card (chat, mail, accounts, the information pages, a directory
  listing) and what needs one: file areas, forums, backups kept on the
  card, and photos on a camera board.
- **ESP32 dev board + SD card, for storage** is the new second entry: the
  same board with a micro SD module beside it in the picture, and the first
  board to wear the **a little wiring** seal. Everything the BBS does, about
  $8 and about half an hour, four signal wires plus power. Its buy link is
  the dev board's, with a line that the card module is a couple of dollars
  anywhere, and its button goes to /sdcard, which still owns the wiring.
- A display split only. Both entries run the one ESP32 image, so the new
  one lives in a table of its own, `SHOWN_BOARDS`, and takes its firmware
  version from the dev board's image set. `BOARDS`, which feeds the
  installer's picker and the release fetcher, is unchanged: the picker
  still offers one ESP32.
- The spectrum's middle stop and the intro's middle line link to the new
  entry rather than straight to /sdcard, and the intro's line about the
  seal now describes both levels.
- **The Freenove's camera varies between batches.** Freenove document an
  OV2640; Rob's kit carries a GalaxyCore GC0308, 0.3 MP, 640x480 at most and
  no JPEG encoder, so the board encodes each photo itself, about 4 seconds a
  snap (firmware FNCAM 1.0.2). /hardware and /camera say so, say the
  firmware drives both, and /camera's settings table gives the resolution:
  320x240 or 640x480, 640x480 as shipped. Nothing claims more than a GC0308
  can do.
- **The Freenove is running, not being ported.** Core, SD card and camera
  work on Rob's bench, and photos are being taken on it. It stays coming
  soon to the installer until a release carries its build.

## 1.2.6, 2026-09-24

- /hardware no longer says the Freenove camera board has a NeoPixel. It
  does not: its LEDs are IO2 (which shares the card's pin), RX, TX and
  power. A drive light or photo flash on it is a pixel you add on a spare
  pin, the same as on the dev board.

## 1.2.5, 2026-09-24

A speed and a seal for each board on /hardware, and buy links for the two
camera boards.

- **Fast, faster, fastest** (Rob: "instead of numbers for now"). The ESP32
  dev board, bare or with a card, is fast; the Freenove camera board is
  faster, because its 8 MB of PSRAM takes the Wi-Fi buffers off internal
  memory, although the classic ESP32 reaches PSRAM more slowly than the S3;
  the ESP32-S3 boards, the Waveshare and the S3 camera board, are fastest.
- **Every one says "expected".** Nothing has been measured: a benchmark
  runs once all three kinds of board are running side by side. The
  spectrum gains a fourth row under the work, "fast (expected)", "fast
  (expected)", "fastest (expected)", inside the rising labels so it moves
  with them, and each stop's screen-reader label says the same in words.
  Each board's facts list, the two coming-soon camera boards included, has
  a Speed row reading "(expected, not yet measured)", from a new
  `BOARD_SPEED` table kept apart from `BOARDS` so the installer is
  untouched. One sentence under the prices says the speeds are expected
  and measured figures follow.
- **A seal on each board's picture** (Rob: "So people know these boards
  like the Freenove are literally flash and go"): a line-art ribbon over the
  picture's top-left corner reading FLASH & GO, on all four boards, the S3
  camera board's with "expected" under it until it has been tested. Each is
  `role="img"` with the level said in words, and one line in the intro says
  what it means. Two levels only: "a little wiring" is for the add-ons, and
  /sdcard and /lights carry wiring diagrams with the ESP32 drawn in the
  corner a seal would cover, so they get none.
- **Buy links for the camera boards**, Rob's Amazon affiliate links, shown
  as the other two boards show theirs. Both stay coming soon to the
  installer, and the intro's line on the links says a camera board's goes
  to the one being tested.
- Nowhere else: /different and the rest of the site are unchanged.
- Self-test: the three speeds render in the spectrum, every board's facts
  list carries its tier marked expected, the page says so in words, and
  /different does not; every board picture wears its seal, one of them
  expected; both camera boards show their buy link.

## 1.2.4, 2026-09-24

Camera boards on the way, a page for the camera, a page on what sets the
board apart, and a roadmap.

- **Two camera boards on /hardware, coming soon** (Rob): the Freenove ESP32
  camera board (FNK0060: ESP32-WROVER-E, 4 MB flash, 8 MB PSRAM, OV2640, a
  card slot, USB-C with a CH340, a NeoPixel), on Rob's bench with its port
  under way, and an ESP32-S3 camera board (N16R8, OV3660 3 MP, two USB-C, an
  external antenna), on order and tested when it arrives, named generically
  because clone boards differ. Each has its own line-art picture and a
  `::: board` block whose Firmware row says "coming soon to the installer",
  from a new `SOON_BOARDS` table kept apart from `BOARDS`, so the installer's
  picker and the release fetcher do not change. No buy links: none given.
  The spectrum keeps its three stops and gets a line under it instead.
- **/camera**, in the shape of /sdcard and /lights: `SNAPSHOT` (`SNAP`) with
  no countdown and "Download it now? (y/N)", Photos as file area 12 readable
  by everybody as shipped, 10 an hour and 20 a day per caller, the settings
  in `CONFIG camera` with "not settled yet" where the firmware has not fixed
  a value, timelapse, retention, the card being required, and the privacy
  case with a lens cap as the only real guarantee. A note that it arrives
  with firmware 1.1 shows until a 1.1.0 release is on disk, as /lights does.
  Linked from /hardware, /build and /whofor; Build one in the menu.
- **/different**, what the board does that the familiar BBS software does
  not: eight lines, each linked to the page that shows it, then how it
  compares, with sources: Synchronet, Mystic, WWIV, ENiGMA½, Talisman and
  Citadel all run on an operating system, and Synchronet's own wiki says
  PETSCII cannot be detected on connect. No "only": espbbs runs a BBS on an
  ESP8266, and the page says so. The 1.1.0 items swap their wording when
  1.1.0 is released. The home page has one button to it, "See what
  µnleashed can do", and /whofor and What this is link it in context.
- **/roadmap**: a line-art signal line in three stretches, done, now (1.1.0)
  and later, drawn across on a desktop and down on a phone, CSS animation
  with reduced motion honoured, and a sentence for each station below it.
  Only what is decided, and no dates. In the footer's Reference row and
  linked from What this is.
- **/whofor** gains a board with a camera: outdoors, wildlife and
  timelapses, and motion-triggered snapshots marked as coming with the
  sensors. /sdcard says what nightly backups are (from 1.1.0), and /lights
  says what the strip does when a caller dials in.

## 1.2.3, 2026-09-24

The site and the firmware are GPL v3 or later.

- **GPL v3 or later** (Rob, 2026-09-24: "make this v3 now across the
  board ... no benefit to keep gpl v2+"). The directory relicenses with the
  firmware (from 1.1.0), because the firmware links Apache-2.0 code, and
  Apache-2.0 combines cleanly with GPLv3 and not with GPLv2. `LICENSE` is
  the GPLv3 text; every SPDX line, file notice and `badges.json` say
  GPL-3.0-or-later; the footer reads "GNU GPL v3 or later" and links the
  GPLv3; the freedoms panel, the cover (SVG and both PNGs, from
  `brand/make_cover.py`) and /build, /install, /donate and /about say v3.
  The released 0.23.0 images under `firmware/` keep their notices as
  shipped.

## 1.2.2, 2026-09-24

The things to do next look like things to do, the pages stop using a page's
title as a sentence's subject, and the spectrum on /hardware moves. Wording
and presentation only: no fact on the site changed.

- **/build's What you need, rewritten** (Rob: "tested boards reads wierd
  after 'a board' its a microcontroller"). Each item leads with the thing
  itself: **A compatible ESP32 board**, **A USB data cable**, **2.4 GHz
  Wi-Fi**, one short sentence each, and a **Choose a board** button under
  them. The bare module's wiring moved to its own short section under
  Getting it running, linked from the cable item; the mesh sentence went,
  because /forward-mesh already says it makes no difference which unit the
  board joins.
- **A next step is a button** (Rob: "The blue blends in"). A new block,
  `::: next`, draws one or two outlined buttons, at most one block a
  section, and only where the link is what a reader does next:
  - /build: Choose a board, Add an SD card and Add lights, Choose a
    terminal, Read before you forward a port;
  - /hardware: Go to the installer under the dev board, Steps for this
    board under the S3;
  - /install: Choose a terminal (After it boots), Set up your BBS (Then);
  - /upgrade: Go to the installer, after the steps;
  - /connected: Set up your BBS; /whofor: Build one; /terminals: Get
    SyncTERM; the manifesto: Build one.
  None of them says Install: only the button on /install does.
- **Links are marked by their underline.** A body link is --dial on --ink,
  1.02:1 apart in luminance, and no blue that is 4.5:1 on the page can be
  3:1 from that text, so colour alone could never mark one (WCAG 1.4.1).
  The underline is now deliberate: 0.075em, 0.22em below the text, 0.14em
  under the pointer. The outlined buttons' edge went from #35566b, 2.5:1 on
  the page, to #4a7a99, 4.2:1, over the 3:1 a control needs.
- **No page title as a sentence's subject.** "Tested boards has the two",
  "Getting listed has the rest", "Build one is the instructions", 28 of
  them on 10 pages, now say what is there and link the words that name it.
  The router pages call /forward "the main port forwarding page".
- **The third stop is an ESP32-S3 board in every overview** (Rob: "dont
  reference 'waveshare' but an S3 board ... which we can go into"): the
  spectrum, /hardware's three ways, /build, the run card ("An ESP32 board,
  a USB cable, five minutes"). Its line is "advanced capabilities". The
  brand stays where it is a safety fact: the tested board's own section,
  its warning and buy link, the installer's picker and the steps for it.
- **The spectrum moves** (Rob: "how about some animations here"), CSS only:
  the line draws in 0.8 s, each stop's tick grows out of it and its figures
  rise in, a quarter second apart, and then a lamp like the run card's goes
  along the line and back, 7 s the round trip; the arrows breathe. Each
  stop is a link to its board, the whole column the target, its name
  underlined, lifting and turning --dial under the pointer, with the yellow
  focus ring round the column. With reduced motion nothing moves and the
  lamp sits on the middle stop. Transforms and opacity only, in a fixed
  viewBox.
- The suite checks each of these, including a scan of every page for a
  link title used as a subject, which finds all 28 in 1.2.1.

## 1.2.1, 2026-09-24

The pages say each thing once, a lights page joins the SD card page, the
wordmark is a drawing, and a failed install on the droplet is no longer
stuck. From the site review of 2026-09-24 and its fact-check.

- **One home per fact.** Facts that were on three to five pages now live on
  one, and the others give a line and a link:
  - which ESP32 chips run a board: /hardware, as a list, with the dev
    board's memory and power moved beside it (/build keeps the bare-module
    notes);
  - how the board detects a terminal: /firstcall;
  - taking a new board over with the default password: /setup (/install
    keeps the password, the local-only rule and the warning);
  - what an update keeps: /upgrade;
  - getting listed: /how;
  - the Chromebook admin setting: /terminals;
  - double NAT and CGNAT: /forward (each router page keeps what is
    particular to its vendor);
  - the freedoms: /about (/whofor keeps its point about decentralisation).
  /about keeps the privacy framing and drops the sentence it shared word for
  word with /privacy. The pages that were here before say about 480 words
  fewer between them (30,319 to 29,838 as a reader sees them), after
  /hardware took on the chips, the spectrum and the dev board's facts.
- **/hardware opens with a spectrum**, Rob's: a bare ESP32, the same board
  with an SD card, and the Waveshare S3, on one line in the site's line art,
  "functional, lowest cost", "economical and usable", "most expandable", with
  an estimated cost and setup time under each. Every figure says "about";
  it is a choice, not a ranking.
- **/lights, a build page for the drive light and the strip**, in the shape
  of /sdcard: a wiring drawing for each, the pins, a 330 to 470 ohm resistor
  and 100 nF at the pixel, a 5 V supply of its own for the strip, the
  effects, and what goes wrong. It lights up Build one. /sdcard and /lights
  both open by saying the Waveshare S3 needs neither, and /hardware's S3
  section says the same the other way round.
- **SD card and lights linked where they are mentioned**: /build, /hardware,
  /setup, /teachers, /install, /donate. The SD card's wires are "four signal
  wires plus power" everywhere a count is given.
- **Two contradictions settled from primary sources.** CS stays on GPIO5:
  Espressif's datasheet gives GPIO5 one job at power-on, the timing of an
  SDIO interface the board does not use, so /setup no longer says to move it
  to 4 to get the board to start. And the card module starts on 3V3, moving
  to VIN only for a module with an AMS1117 regulator, which needs about a
  volt more in than it gives out: /teachers no longer says "not VIN".
- **Wrong or stale:** /donate said the S3 was untested, and now also sends
  firmware bugs to the firmware's issue tracker. /teachers installs from
  /install rather than building from source, and says plainly that nobody
  has installed a board from a Chromebook here yet. /build's source steps
  lose `secrets.h`, which is only a fallback now, and give the S3's
  `-e ws_s3_lcd147`. "The newest part" is gone from the forums on /kids and
  /about. /connected mentions the S3's screen. /how links the house rules,
  as /setup said it did.
- **Hardware in the footer**, after Build one. The footer's separators are
  drawn rather than typed, so a phone no longer ends a wrapped row on a
  dangling dot.
- **The wordmark is an SVG**, made at start from the same `LOGO_ROWS`, so
  there is still one source. On a phone the text version showed the font's
  line gaps as stripes; the drawing has none, is sharp at any density, and
  keeps its name for a screen reader.
- **/build's commands scroll sideways on a phone** instead of breaking
  `unleashed_BBS` over two lines: a fenced block written ```` ```nowrap ````
  keeps its lines whole.
- **Deploy: a failed install is retried.** update.sh installed only on the
  run whose pull moved HEAD, so when setup.sh failed on that run, every
  later run said "Already up to date" and the site stayed on the old
  version, which is what happened to 1.2.0 on the droplet. setup.sh now
  writes the commit it installed to `/srv/unleashed_directory/.installed`
  once it has finished, and update.sh installs whenever that is missing or
  is not HEAD, saying "Installing <hash>: the last install did not finish".

## 1.2.0, 2026-09-24

A second board: /install asks which board you have, with a picture of each,
and serves the Waveshare ESP32-S3-LCD-1.47 its own image. A new page,
/hardware, shows the tested boards.

- **A board picker on /install** (Rob: "update the flasher to select the
  board type ... include an image for confirmation so the user flashes the
  right one. Small picture in the pick list"). The card opens with a radio
  list, one row a board: a small line-art picture, the name, one line on how
  to tell it ("Two rows of pins and a USB socket", "A USB stick with a colour
  screen") and the firmware this page would put on it. The chosen row
  decides which buttons, version line and notices show, with native radios
  and CSS and no script, the way a kept older release always has. A board
  with nothing to install says **Coming soon** and has no buttons. A line
  under the buttons says the installer reads the chip first and stops,
  writing nothing, if it is the other kind, and "which is mine?" links to
  /hardware.
- **One manifest a board.** Each choice's buttons fetch
  `/install/<version>/<board>/manifest.json` (and `manifest-update.json`),
  holding that board's build and nothing else: ESP Web Tools picks a build
  by chip family alone, so a manifest naming both would give any ESP32-S3
  the Waveshare's image and pins. A board of the other family is refused
  before anything is written ("Your ESP32-S3 board is not supported."). The
  manifest's version is the set's `version.txt`, exactly as the board shows
  it over Improv ("1.1.0 (S3 1.0.0)"), because ESP Web Tools compares the two
  to decide whether the board already runs it. `/install/<version>/manifest.json`
  still answers, the ESP32's alone.
- **Previews.** A directory named for a pre-release (`1.1.0-dev.8`) is a
  preview: offered only for a board no release carries, labelled "1.1.0
  preview (S3 1.0.0)" in the picker with the exact version under the
  buttons, and never counted as the newest release, so it lights no
  `::: from` gate, no announcement banner and no update arrow. Its set for a
  board that has a release is neither offered nor served. Once a release
  carries the board, the preview is not offered at all.
- **The fetcher reads the list of releases, not only the latest.** It
  installs the newest release by version, every board's set it carries (the
  ESP32's assets plain, another board's prefixed: `esp32s3-firmware.bin`),
  and each set's `version.txt` when the release has one, checked against
  SHA256SUMS like everything else. A board the newest release does not carry
  is served from the newest older release that does, so an ESP32-only patch
  never takes the S3 off its release; a board no release carries at all,
  from the newest pre-release that carries it, installed under its own name.
  A release missing part of a set, or with a `version.txt` that is not a
  version, is refused and nothing moves, and so is one whose sums name a
  `version.txt` it does not carry. The newest two releases are kept, plus
  whatever release or preview is serving a board, read off the disk the way
  the page reads it, so a preview copied in by hand stays until a release or
  a newer preview carries its board; after any refusal every preview on
  disk is kept. Releases before 1.1.0 read exactly as before.
- **The S3's own steps.** Its section of the card says first to hold BOOT,
  tap RESET and let go of BOOT, and to press RESET when the install has
  finished: the stick has no USB-serial chip, and on Rob's PC the automatic
  reset did not reach it. A new section of /install, **On the Waveshare
  S3**, says why, quotes the installer's own messages and Espressif's
  documentation, and says plainly that setting the Wi-Fi from this page is
  not yet confirmed on this board, with the two ways round it: **Update my
  board** with the board running normally, or `CONFIG network`. /upgrade and
  the driver advice point at it.
- **The amber "before you start" box is under the buttons**, on a desktop as
  on a phone: the picker took its room, and both buttons still sit on the
  first screen at 1366 x 768 (the ESP32's Update button ends at 665px, the
  S3's at 719px). The card's column is 26rem, from 24. The small laptop and
  board drawing that opened the card is gone; the pictures in the picker
  replace it.
- **/hardware, the tested boards.** Each board's picture at twice the
  picker's size, the firmware /install offers it, its chip, how to tell it,
  and a buy link (Amazon), drawn by a new `::: board` block from the same
  table as the picker, so the two cannot disagree; then what was tested on
  it and what it adds. The Waveshare's: its screen of figures, the onboard
  LED as the drive light, a TF slot with no wiring, 16 MB of flash and 8 MB
  of PSRAM, and still ten caller lines, because sockets cap it the same as
  the ESP32. It warns that the 1.47B and every other S3 board are not this
  build. In the Build one section of the menu.
- **/build's table** says the ESP32-S3 has run, on one board, and links
  /hardware; "What you need" names the second board.
- **The BOOT-hold reset, waiting for firmware 1.1.0, is worded for both
  boards**: the ESP32 dev board shows each stage on its activity LED; the S3
  has none, so you count the seconds, and either prints each stage on its
  serial console.
- 731 checks, up from 698.

## 1.1.0, 2026-09-24

Short codes for every cause and interest, an SD card badge, one board per
port on the go-public guide, and the BOOT-hold reset waiting for firmware
1.1.0.

- **Every cause and interest has a short code** (Rob: "like 5 or 6 max",
  `MNTLH` for mental health). Six letters and digits at most, a real word
  kept whole where it fits (`HAM`, `C64`, `LINUX`, `CANCER`), otherwise a
  consonant code (`MNTLH`, `ELCTR`, `LTRCY`). /badges shows them upper case
  in a **Code** column, and the filter's chips say the code in their
  tooltip. A board sends them, and the directory stores and publishes them,
  in lower case; they are read in any case, in a heartbeat, in a `?b=`
  link and in the search boxes.
- **Every older slug still works.** The long slugs up to site 1.0.0
  (`mental-health`, `electronics`) and the interim ones proposed on the
  way (`hope`, `meeple`, `wx`) are aliases: a board on firmware 1.0.1 that
  sends `electronics` keeps its badge, and a shared link with
  `?b=electronics` still filters. A word is matched with its case folded
  and everything but letters and digits dropped, so `Mental health`,
  `mental-health` and `MNTLH` are one badge. A row stored with the old
  slugs is read through the same aliases, with no migration, and its next
  heartbeat writes codes. `/api/boards.json` answers in codes.
- **The table is one file, `badges.json`**, beside server.py: each badge's
  code, group (and sub-group for an interest), name, meaning and aliases,
  plus the rules, in plain JSON a separate program can read. The firmware
  can build its CONFIG pick-list from it. The drawings stay in server.py,
  keyed by code. setup.sh installs the file with the code. Without it the
  site still starts, shows no causes or interests, says so in the journal,
  and leaves the causes and interests boards have stored alone rather than
  writing them empty.
- **An SD card badge.** A new optional announce field, `sd`: the size of the
  card in use, in GB, already rounded by the board to the size printed on
  the card. Shown as `SD32` in the features' blue, after what is running;
  a filter chip (`?b=sd`) and a row on /badges; in the JSON as `sd` and in
  the feed as "SD card: 32 GB". A value that is not a whole number from 1 to
  4096 counts as not sent. In PROTOCOL.md, with the codes.
- **/forward explains one board per port.** Two new sections: the same
  port outside and in, and why a router with one port box (eero) needs it;
  and one outside port per board at one address. From firmware 1.1.0 a
  board's port is a setting, **Port** on the network page of CONFIG, and
  the announce page's **Outside** is the number callers dial through the
  router, empty meaning the same as Port. Until a 1.1.0 release is out the
  page says what older firmware can do instead. It also says, plainly,
  that this directory lists one board per address by itself and a second
  waits for a person.
- **/setup** gets the same: the wifi page becomes **network** with its
  **Port**, and the announce page's Port becomes **Outside**, on the day a
  1.1.0 release is on disk. The backup port's note no longer assumes 6400,
  and the announce page mentions the causes and interests from firmware
  1.0.1.
- **/install's reset section waits for firmware 1.1.0**, not 1.0.2, which
  became the restore security fix and has no BOOT-hold reset. It carries the
  firmware's 1.1.0 wording: a warning, read before step 1, that a factory
  reset takes the board off this directory until a backup is restored; the
  7 to 15 second band keeps the board off the directory until a new
  password is chosen; the 15 to 20 second band wipes the Wi-Fi too.
- **`::: until X.Y.Z`**, the other half of `::: from`: prose shown only
  while the newest release on disk is older, or there is none. A pair swaps
  one account for the other on the day the release lands. A gate now also
  closes whatever list, paragraph or table came before it, so it can follow
  a list directly.
- /badges: the note that the firmware sends none of these was out of date
  since firmware 1.0.1 and is gone; the page says where a µnleashed sysop
  types the codes. /how's example is in codes, with `sd`.
- `SELFTEST_PORT` moves the suite's five ports off 8123, for a machine where
  something else has it.
- 698 checks, up from 663, with a database made by 1.0.0 among them.

## 1.0.0, 2026-09-23

The site's 1.0.0 marks the public launch of the µnleashed firmware at 1.0.0.
It is Rob's call, and it is the last time the two numbers move together:
from here the site and the firmware each keep their own version, and a
site release says nothing about which firmware is out.

- **A board's badges are two rows, in the same places on every board**
  (Rob: "The unleashed and esp32 should be upfront ... sort those so core
  system ones are always first, etc. that way they look consistent when
  scrolling"). The first row is what the board is: its software and
  version, then the machine it runs on. The second is the small badges in
  a fixed order: PETSCII, guests, what is running (chat, mail, forums,
  files, doors), new or steady, time listed, then the causes and the
  interests. Only those last two are alphabetical, by name. A board with
  nothing for a row has no row. /badges and the filter keep their order.
- **The software badge carries the version** the board sends: "unleashed
  1.0.0", "Mystic 1.12", or the name alone when no version came.
  `software` and `version` are cleaned the way `system` is, and both are
  in `/api/boards.json` now, and in the feed as "Software:".
- **Update available.** A µnleashed board older than the newest release on
  /install gets a small arrow on the end of its software badge, in a dim
  cyan, with the tooltip "Update available: 1.0.0 → 1.0.1. Plug it in and
  use Update my board on /install.", and the arrow links to /upgrade.
  Versions are compared part by part, so 1.0.10 is newer than 1.0.9; a
  pre-release is older than its release; a version that is not three
  numbers, and any other software, never gets one. It is a badge in its
  own right in the filter and on /badges, **Update available** (`?b=update`),
  so a sysop can find which of their boards are behind. /upgrade says what
  the arrow is.
- **Icons on the two install buttons**: a fresh chip with a sparkle on
  **Install on a new board**, and a chip inside an arrow going round it on
  **Update my board**, line art at the badges' stroke weight.
- **Both buttons are on the first screen at 1366 x 768**, with a second
  release offered, which is the tallest the card gets. The card's column is
  two rem wider, which takes a line off the amber box; the drawing is held
  to 3.5rem tall; the gaps and padding are smaller and the buttons a
  little shorter. The Update button ended at 831px and ends at about
  740px. A phone still gets the buttons first.
- **The installer always offers Telnet details.** The dialog often reads a
  board while it is still starting, before it has joined Wi-Fi and so
  before it has an address, and its dashboard then offered **Connect to
  Wi-Fi** and nothing to call. The item is always there now: with an
  address it goes to `/connected#<address>:<port>` as before, and without
  one to `/connected`, which says plainly the three ways to find the
  board: `unleashed.local` (or whatever Hostname it was given), the line
  it prints in **Logs & Console** when it starts (press reset with the
  console open), and the router's list of devices. The notice at the top
  of the dialog chunk says so, and the bundle moved to
  `/install/esp-web-tools/10.4.0-3/` so a browser fetches the new dialog
  at once. Every earlier path still answers.
- The short badge codes Rob asked for (`MNTLH` for mental health) were
  worked out for this release and then held back, to ship with firmware
  1.0.2 as a site version of their own. The slugs are unchanged here.

## 0.22.2, 2026-09-23

The filter condensed to a screen, amateur radio moved to the interests,
fourteen more causes to support, and the BOOT reset gated on firmware
1.0.2.

- **The filter pane is small chips in rows** (Rob: "the filter page is
  unmanageable, it needs HUGE condensing ... the hover works, just put em
  in groups"). A chip is the badge's symbol or letters and nothing else;
  its name is in the tooltip on hover and on focus, and is the checkbox's
  name for a screen reader. Each group is one row, its name in a column on
  a desktop, with the interests as a heading and a row per sub-group, two
  to a line. On a phone a group's name is a heading, and a tap folds the
  group away; a search opens any folded group that has a match. Chosen is
  a ring round the chip and a notch in its corner, so colour is never the
  only sign. Measured with the pane open: 1,538px tall at 1366 x 768 before
  and 460px after; 3,256px at 390 before and 1,130px after. It still works
  with no JavaScript, and the chips are still checkboxes in a GET form.
- **Amateur radio is an interest, not a support cause** (Rob). It sits
  with the radio and the sky, drawn in the interests' rose, and keeps its
  slug, `ham`. A board that sends `ham` in its support list has it filed
  with its interests, and a row stored before the move is read the same
  way, so nothing needed migrating.
- **Fourteen more causes to support**, chosen by how often each is worn
  as a ribbon, badge or profile frame, and kept to causes that belong to
  no political party: addiction recovery, blood and organ donation, breast
  cancer awareness, carers and caregivers, children with cancer,
  dementia, diabetes, domestic violence, first responders, foster care
  and adoption, heart health, hunger relief, literacy, and people without
  a home. Each is a line drawing in the colour or symbol it is known by:
  the pink, gold and purple ribbons, the forget-me-not, the blue circle,
  the adoption triad. Twenty-four in all. The first ten are unchanged, and
  HIV's ribbon stays red.
- **/install's BOOT button reset now waits for firmware 1.0.2.** It moved
  there from 1.0.1, which is the badge fields only, so a 1.0.1 release on
  disk no longer shows a reset the board does not have. The CONFIG Wi-Fi
  fallback in the same block moved with it.
- 634 checks, up from 627 (which 0.22.1 left out of its changelog entry).

## 0.22.1, 2026-09-23

An Update button that cannot erase, and an erase question that does not
frighten somebody updating a board full of accounts (Rob, after updating
his own board from /install: "clean up the messaging, that an end user
understands this it would freak me the fuck out").

- **Two buttons in the install card.** **Install on a new board** is the
  install as it was, erase question and all. **Update my board** fetches
  `/install/<version>/manifest-update.json`, which is the ordinary manifest
  plus `"unleashed_update": true`, and the copy of the dialog served here
  reads that key as "never erase, never ask": `_startInstall()` stores
  false whatever it is asked for, `_confirmInstall()` hands the flasher
  false whatever is stored, both dashboards skip the erase question and
  say **Update unleashed BBS**, and **Erase User Data** is not offered. A
  board the installer does not recognise is updated the same way. The
  update manifest keeps `new_install_prompt_erase: true` on purpose: ESP
  Web Tools erases by default without it, so a copy of the dialog that does
  not know the new key, upstream's or a cached one, asks with the box
  unticked rather than erasing.
- **The erase question in plain words.** "Erase device ... All data on the
  device will be lost." is now **Start fresh?**: "Updating a board you
  already run? Leave this unticked: your accounts, settings, mail and
  forums are kept. Tick it only for a brand-new board, or to wipe this one
  and start over." The checkbox is **Erase everything first**, "Install
  unleashed BBS" is **Install or update unleashed BBS**, and the
  confirmation and **Erase User Data** screens say what an erase takes and
  that the SD card is not touched. The vendored dialog's notice lists every
  string, and the vendor README says how each change was proved without
  clicking.
- **Why Rob's board was offered Install, as far as it is known**: the
  dialog gives a board 1.5 seconds to answer over Improv when it opens, and
  opening the port resets an ESP32, so a board still starting up is not
  recognised. Not confirmed. The Update button makes it not matter.
- **The bundle has a new path**, `/install/esp-web-tools/10.4.0-2/`
  (`EWT_REV` in server.py), because every file in it is cached for a day
  and a browser holding the old dialog would otherwise run it beside a page
  offering the Update button. The bare `10.4.0/` path still answers, for a
  tab left open across the deploy.
- **/install and /upgrade** say which button to press and what the dialog
  will show. The note at the top of the steps sends an existing board to
  **Update my board**. /upgrade no longer promises a 0.22.1 board is always
  recognised, shows the new erase screen's words for a reader who pressed
  Install instead, and sends a board from 0.17.0 on to Update. The drawing
  of the dialog shows the new labels.

## 0.22.0, 2026-09-23

Interests, a badge filter over the board list, /badges as a searchable
table, one order for every badge, and the card's lamps redrawn (Rob).

- **Interests**, a sixth optional announce field, `interests`, handled
  exactly like `support`: slugs from a published list, anything else
  ignored, the first 16 read. Forty-two of them in eight groups: Computing
  (BBS history, Linux, open source, programming, retrocomputing),
  Platforms (Amiga, Apple II, Atari, Commodore 64, DOS, ZX Spectrum),
  Making (3D printing, electronics, robotics, soldering, woodworking),
  Games (arcade and pinball, board games, gaming, retro gaming, tabletop
  RPGs), Music and art (ANSI art, chiptune, demoscene, drawing, music,
  photography), Radio and sky (astronomy, shortwave listening, weather),
  Outdoors and more (aviation, cars, cooking, cycling, fishing, gardening,
  hiking, model trains) and Reading and watching (anime, books, movies,
  science fiction). Each is a small line drawing in rose, a colour nothing
  else on the page uses, with a one-line meaning. In PROTOCOL.md beside
  `support`, in the JSON as `interests`, and in the feed as "Interests:".
  Amateur radio stays in support; the ten support badges and their colours
  are unchanged.
- **A filter over the board list.** A small Filter button above the table,
  with the key to the badges beside it. Pressed, it opens a bento grid of
  every badge, a box per group and one per group of interests, each badge
  a tile with its symbol and name, and a search box that narrows the tiles
  by name or slug. Picking tiles shows the boards carrying all of them, or
  any of them with the toggle; "N of M boards with all of: ... Clear" says
  what is chosen, and "No board with all of those yet." says when nothing
  is. None of the badge symbols is on the page until the pane is opened.
  **It works with no JavaScript**: the button is a `<details>`, the tiles
  are checkboxes in a GET form, and the server filters on
  `?b=petscii&b=ham` (and `&m=any`), so every filtered view is a link to
  share or bookmark. A badge the directory does not know is ignored, and
  nothing typed into the address is put back on the page. With the script,
  a tile filters the moment it is pressed and the address follows. A
  chosen tile shows a tick and a brighter frame as well as a colour;
  focus is the yellow ring; three tiles a row on a phone. The pane settles
  in only where motion is wanted.
- **/badges is a table per group**, each row the symbol, the name, the
  slug and what it means, the four groups under their headings and the
  interests under their own. A search box at the top narrows the rows as
  you type and says how many are left. Every row is on the page without a
  script; the search box appears only when the script can drive it.
- **One order for every badge** (Rob): alphabetical by the name a reader
  sees within each group, a leading digit or symbol set aside, the groups
  in their own order, on /badges, in the filter's grid and under a board's
  name alike. One list in server.py, `BADGES`, carries each badge's sort
  key, and all three views walk it. So a row now reads C, D, Fi, G, the
  machine, P, then the software, and amateur radio comes first among the
  support symbols. The six steps of time listed are one badge, "Listed",
  kept together and in order.
- **The third script on the site**, inline and pinned by the suite to its
  exact text: it reads the page, writes only text and the hidden
  attribute, sends nothing, stores nothing and never navigates. The board
  list and /badges carry it; every other page is still script-free.
- **The "Run your own board" card's lamps**, to the UX spec: two lamps half
  a lap apart instead of three a third apart, which looked scattered
  because a rectangle has no three-fold symmetry. Each is the row hover's
  lamp with a tail of three beads that bends round the corners, 20 seconds
  a lap. With reduced motion, or without offset-path, two still lamps by
  opposite corners.
- **Migration**: one column, `interests`, added with `ALTER TABLE ... ADD
  COLUMN` when missing. The suite now starts a server on a database made
  by the 0.21.1 schema as well as the 0.20.2 one, and checks it gains
  exactly that column, keeps every row and badge, and takes the next
  heartbeat's interests.
- 610 checks, up from 563.

## 0.21.1, 2026-09-23

- **/terminals: "Just tell me what to install" sits under the drawing**
  (Rob: "it feels like its floating with no direction now"). The laptop
  and phone drawing follows the page's opening line, and the heading comes
  after it, directly above the SyncTERM paragraph it introduces. The
  drawing's labels are inside its frame, so nothing was left behind; the
  gap above the heading is the heading's own 1.75rem, checked at 1366 and
  at 390.

## 0.21.0, 2026-09-23

Badges on the board list (Rob), and the list's rows striped and lit on
hover.

- **Five optional announce fields**, in PROTOCOL.md with an example and
  their limits: `system` (the machine, up to 40 printable characters),
  `terminals`, `guests`, `features` and `support`. Old boards send none
  and are listed as before. Junk is dropped rather than refused, so a bad
  badge field never costs a listing: control and format characters out of
  `system` (bidi overrides and zero-width characters included), at most two
  combining marks a character, and only known words, once each, from the
  first 16 entries of a list. `guests` has to be a real JSON boolean.
- **Badges under each board's name**, wrapping so they never push the Dial
  column. The software badge moved into the same row, then the machine as
  text, then one or two letters in colours from the palette: P (PETSCII,
  purple), G (guests, amber), C, F, Fi, M, D (chat, forums, files, mail,
  doors: blue, only what is running now), and three the directory works out
  for itself: N (listed under a week, orange), S (steady, cyan) and how long
  listed, 1m to 10y, highest only (lavender). Then the support symbols.
- **Steady** is a new hourly record, `beathours`: each accepted heartbeat is
  counted into its UTC hour, and a week is kept. A board is steady when the
  heartbeats that arrived over the last 168 hours are more than 95% of what
  its own `interval` said were due, each hour counted at most up to its own
  due, so a burst cannot cover a silent hour. It needs a full week of record
  first, so every board already listed gets its first chance a week after
  this is deployed.
- **The support list**: eleven causes a sysop can show, as line-art
  symbols in their causes' own colours, one table in server.py (`SUPPORT`).
  LGBTQ+ (rainbow), transgender people (the trans symbol), disabled people
  (the disability pride flag), neurodiversity (infinity), mental health
  (green ribbon), suicide prevention (semicolon), veterans (a dog tag),
  cancer (lavender ribbon), HIV (red ribbon), animal welfare (paw) and
  amateur radio (a mast). Only these slugs are shown, so nobody can put
  words of their own on the page.
- **Tooltips, CSS only**, from `data-tip`, on hover and on focus, so a tap or
  a keyboard gets one too; each badge also has an aria-label and a tabindex.
  No title attribute: it drew the browser's own tooltip on top on a desktop
  and nothing on a phone. Below the breakpoint the tooltip hangs from the
  start of the row and is never wider than the screen.
- **/badges**, the legend: every badge, its colour, what it means and where
  it comes from, how steady is worked out, and "Show your support" with each
  symbol, its slug and a sentence. Built from the same tables as the list.
  Linked from a small "What the badges mean" above the table and from the
  footer. The menu lights Boards on it, on any face.
- The JSON gains `system`, `terminals`, `guests`, `features`, `support`,
  `listed_at` and `steady`, and is now built field by field so a new column
  can never leak the token or the note. The feed says the same in words.
- **Zebra rows**: every other board `#111116`, a few percent over the page;
  every text colour keeps its contrast grade (--dim 5.45:1, --ink 11.25:1).
- **Row hover**: a `--dial` outline at 35% alpha, so nothing moves, and one
  of the site's small blue lamps flies once under the board's name trailing
  a fading streak, sized to the name's own width. Hover only where a pointer
  hovers, so a tap on a phone leaves nothing lit; the flight only without
  reduced motion.
- **Migration**: six columns added with `ALTER TABLE ... ADD COLUMN` when
  missing, and a new table; no rebuild. The suite starts a server on a
  database made by the old schema and checks it serves, gains exactly a new
  database's columns, keeps its rows, and takes the next heartbeat.
- 563 checks, up from 491.

## 0.20.2, 2026-09-23

- **The "Run your own board" card stands out** (Rob). A wash of the
  site's action blue over the page rather than a flat block, its border in
  the same blue, and three small blue lamps going slowly round its edge, a
  third of a lap apart, one lap every 16 seconds. CSS only: each lamp
  follows the card's own rounded rectangle with `offset-path`. With
  reduced motion asked for they stand still a third of the way round from
  each other; a browser without `offset-path` gets three still lamps set on
  the edge by hand. Buttons and layout unchanged: the card is still level
  with the heading at 1366 and under the lead at 390.
- **How to upgrade, at the top of /install** (Rob: "make sure the website
  calls out on the flasher page how to upgrade"). A short note opens the
  steps column, beside the install card on a desktop and just after it on a
  phone, so the install button keeps its place: "Already running
  µnleashed? Plug it in and press Install on my board; it offers an update
  and keeps your accounts."
- **/upgrade, a page of its own**: back up first, what a recognised board
  is offered, what the update writes and what it leaves, the screens on the
  SD card, a board older than 0.22.1, and what to do when it goes wrong.
  Each fact was checked against the firmware and the installer rather than
  written from memory: the partition table has not moved since 0.17.0, the
  update writes the five parts the manifest names and nothing else, a board
  running 0.22.1 or later reports "unleashed BBS" over Improv and ESP Web
  Tools then offers **Update** with no erase, the backup zip takes only the
  settings, the accounts and the screens, and since 0.22.0 the board
  refreshes the stock screens it put on a card and leaves edited ones
  alone. In the footer's Get started row, after Install.
- The README gains a "How it was built" section.
- 491 checks, up from 476.

## 0.20.1, 2026-09-23

The board list's top, redone (Rob, on 0.20.0: "This seems a bit big for a
button there in the middle ... The way that looks is terrible.").

- **The announcement banner is one slim line above the heading**: a
  hairline, a yellow lamp, small type, and one link. "µnleashed BBS 1.0.0
  is out. Install it from your browser." goes to /install. It still shows
  only once a 1.0.0 or later release is on disk, and with none there is no
  box and no gap. The words are `ANNOUNCEMENT` in `server.py`, one string
  of the page dialect's inline Markdown, so changing the announcement is
  changing one line; an empty string switches it off. One line at 1366
  and 1920, two at 390.
- **"Run your own board" is a small card beside the heading**, in the
  install card's box: the title, "An ESP32, a USB cable, five minutes.",
  and two compact buttons, **Web installer** filled and **Build from
  source** outlined. A grid column from 901px, level with the heading; on a
  phone it follows the lead as the title and the two buttons on one row.
  19.5rem rather than the 18 asked for, because at 18 the buttons stacked
  and the card stood half as tall again as the text beside it. The full
  size button pair and 0.20.0's drawing are gone from the board list;
  /build and /setup keep theirs.
- **The figures are a sentence under the heading**: "Unleashed is hosting
  1 board with 1 caller on right now.", both figures in the colour that
  means up, singular and plural right, "no callers" when nobody is on and
  "no boards yet" on an empty directory. The callers are the sum of what
  the table shows; the JSON and the feed are unchanged. `STAT_SUFFIX` can
  add to the end of it later and is empty: nothing here knows where a
  board is, so the page does not say "across the globe".
- The board list's table header is at y=526 at 1366 x 768 (613 with the
  first cut of the card), and the first board is on the first screen at
  390 x 844.
- 476 checks, up from 459.

## 0.20.0, 2026-09-23

- **The BOOT button reset and the CONFIG Wi-Fi fallback wait for firmware
  1.0.1**, where they moved from 0.24.0. /install's section on them was
  gated on 0.24.0, which 1.0.0 is past, so it would have promised both the
  moment 1.0.0 landed. It is gated on 1.0.1 now, and nothing on the site
  says either is in 1.0.0. The suite checks 1.0.0 on disk hides it and 1.0.1
  shows it.
- **The announcement banner says "µnleashed BBS 1.0.0 is out"**, above the
  board list, only once a 1.0.0 or later release is on disk, and carries the
  list's two buttons, Visit the web installer and Build from source, rather
  than sitting under a second pair. On a phone its drawing is left out, so
  the buttons are on the first screen.
- **The footer's licence reads "GNU GPL v2 or later"**, linked, and each of
  version, copyright and licence is kept whole, so a phone gets two tidy rows
  instead of a licence name broken across three.
- **Checked for 1.0.0**: a `v1.0.0` tag is fetched into `firmware/1.0.0/`,
  sorts above the 0.x releases, gets a manifest, and is what the install
  card offers first, with the one before it as the choice. The suite now
  says so in one check.
- 459 checks, up from 453.

## 0.19.1, 2026-09-23

- **The entry pages' buttons say where they go** (Rob). 0.19.0's said
  "Install from your browser" and opened another page with another button on
  it: two presses and a page change for one action. The rule now is that a
  button that goes somewhere says where, and only the button on /install
  says Install, because only that one installs.
- **Two buttons side by side** on /build, /setup and the board list:
  **Visit the web installer**, filled, to /install, and **Build from
  source**, outlined in the style of the installer card's older-release
  button, to /build#getting-it-running. On a phone they stack, filled
  first, each the full width. Both are on the first screen of /build at
  1366 x 768 and 390 x 844.
- 453 checks, up from 448.

## 0.19.0, 2026-09-23

For the firmware's 1.0.0 release (Rob): the installer easy to find, the
donation page easy to find, /install laid out as a page you act on, and
somewhere for the installer's last step to go.

- **One button on each entry page.** /build, /setup and the board list each
  open with one primary action, drawn like the installer's own button:
  **Install from your browser** (on the board list, **Run your own board**),
  with the manual route beside it as a plain link. On /build it replaces the
  invitation box whose third sentence was the link Rob could not find. All
  three are on the first screen at 1366 x 768 and 390 x 844. A new
  `::: cta` block in the page dialect draws it.
- **Donate is in the menu**, last, and first in the footer's second row in
  the warm colour, renamed from "Support". The menu is ten items now: at
  390px "Donate" lands on the row "Get listed" and "Data" already share, and
  at 1366 and 1920 the menu is still one row.
- **/install, two columns.** From 901px the page is the title and the steps
  on the left and a sticky install card on the right, 22rem wide and level
  with the title: a small drawing, the "before you start" box, the board
  (ESP32, 4 MB flash), the button, one version line and the notices link.
  The version was on the card three times and is on it once, and the button
  no longer carries it. On a phone the card sits between the title and the
  steps with the button first. The installer's own licence moved to "Doing
  it the other way". Laid out to the tty-ux spec, with Rob's two calls: the
  box goes after the button on a phone, and the card is a grid column, not a
  float. One departure, measured: level with the title rather than with the
  steps, because the box as written is seven lines at the card's width and
  that put the button under the fold at 768.
- **A kept older release is a choice in the card**, two radios with no
  script, where it used to be a second button. The labels are short so both
  fit on one line; two lines put the button under the fold.
- **Headings have ids on every page**, the heading's words in lower case
  with every other run of characters one "-", unique on the page. The
  install card's box links to #before-you-start.
- **"Visit Device" is "Telnet details", and goes to /connected.** A board
  answers the Wi-Fi step with `telnet://<address>:6400`, which no browser
  opens. The vendored copy of ESP Web Tools is changed in one file to send a
  telnet link to `/connected#<address>:<port>` instead, and says so in a
  notice at its top, as the Apache License requires; the vendor README has
  upstream's checksum for the file.
- **/connected**: the board's address, the telnet command, a telnet link,
  SyncTERM and PuTTY one line each, the default sysop password with the
  warning to change it first, and the setup guide. The address stays in the
  part of the link after the #, which a browser never sends, so it is in no
  log here. A dozen inline lines read it, write it with textContent only and
  send nothing; anything but a dotted IPv4 address and a port is ignored.
  With no address the page says where to find it: the board's console, the
  router's device list, or `unleashed.local`. It is the second page on the
  site with a script, and the suite pins what that script may do.
- The no-release box on /install was in the faint colour, borrowed from the
  board list's empty line by sharing its class name; it is --dim.
- 448 checks, up from 416.

## 0.18.0, 2026-09-23

- **A check that would have caught the 0.17.x outage, and does now.** The
  self-test starts `server.py` alone in an empty directory and requires it to
  answer, and it reads every path the server opens beside itself and requires
  `deploy/setup.sh` to install each one. Proved against 0.17.1's `server.py`,
  which fails it with the outage's own error. Writing it found two more gaps,
  both fixed in setup.sh: `CHANGELOG.md`, which the footer now reads, and
  `static/kids/`, because the static copy only took files at the top level.
- **/install, drawn.** Five line drawings of what is about to happen, in
  order: the data cable, the installer's Install, erase and progress bar, the
  first start making its storage, the Wi-Fi step and its thirty seconds, and
  the first call's setup. Decoration beside steps that say the same in words.
  A numbered list split by a drawing now carries its numbering on.
- **"If something goes wrong, reset rather than reflash"** (Rob): Change
  Wi-Fi over the cable, which works while the board is failing to join, and a
  reflash with erase as the last resort. The CONFIG Wi-Fi fallback and the
  BOOT button's hold-to-reset, with a drawing of the buttons and the LED's
  stages against the seconds, are written for firmware 0.24.0 and appear only
  once a release of 0.24.0 or later is on disk, the way the announcement
  banner waits for 1.0.0 (`::: from 0.24.0` in the page).
- **The first-call setup as 0.23.0 does it**, on /install and /setup: the
  board asks a local caller for the sysop password after they sign up or log
  in, then the setup screen, the staff passwords form and the tour. /setup
  shows all four as captured from 0.23.0, and its CONFIG screens were
  re-captured from 0.23.0 too.
- **The footer** has two rows, Get started and Reference, and under them the
  site's version (the changelog's newest heading, read at start), the
  copyright and the licence.
- **Every page names its own address**: a canonical link and `og:url`, on the
  face the page belongs to.
- **The installer's dialog is dark and monospace**, through Material's own
  colour variables set from this page, checked by opening its "No port
  selected" dialog in a browser.
- 416 checks, up from 404.

## 0.17.2, 2026-09-23

- **Fixed the outage the 0.15-0.17 updates caused.** `deploy/setup.sh`
  installs into `/srv/unleashed_directory` and copied only `server.py`,
  `selftest.py`, `pages/` and `static/`. The server reads `shots/` at import
  with no guard, so on a droplet whose checkout is not the install
  directory it died on start and every check failed with a 502. setup.sh
  now installs `shots/`, `brand/`, `vendor/`, `supporters.txt` and any
  release in `firmware/`; `shot_svg` costs a picture, not the server, when
  a capture is missing; and `update.sh` points the release fetcher at the
  directory the server reads. Found by Rob's first update after 0.14; the
  web rounds had never run the install end to end, as their reports said.

## 0.17.1, 2026-09-23

- **Firmware 0.23.0 on /install, committed by hand** into `firmware/0.23.0/`
  (past the ignore rule) while the firmware repository is private and the
  fetcher cannot reach it. It comes out at 1.0.0, when the fetcher takes
  over. The self-test checks whichever installer state the checkout is in.
- **Thank-yous narrowed (Rob):** only lifetime members are named, on the
  ABOUT screen and on /donate.
- Membership level cards for Buy Me a Coffee in `brand/`, with
  `make_tiers.py`.

## 0.17.0, 2026-09-23

- **/donate, "Support the project"**, the copywriter's page, served like the
  others and linked as Support in every footer. Buy Me a Coffee is a plain
  link: nothing on the site loads anything from it, and the suite checks
  every image and script on the page is this site's own.
- **What support buys, in Rob's words**: posts and development news on Buy Me
  a Coffee, some for members only, and never features or priority.
- **Thank you**: supporters who agree are named on a thanks list on the page,
  in the release notes of the version they supported, and on an information
  page on Unleashed HQ; lifetime members are also credited on the firmware's
  ABOUT screen. The list is `supporters.txt` and starts empty, and an empty
  list shows nothing, heading included.
- **The cover** heads /donate, from `brand/make_cover.py`. It is laid out for
  Buy Me a Coffee's crop, so the site serves it cut to the band that has
  content, with its frame closed round it. The avatar stays the link preview.
- A page that opens with a drawing is no longer described to link previews
  as "::: art".
- 404 checks, up from 393.

## 0.16.0, 2026-09-23

For the firmware's 1.0.0 release (Rob).

- **/install says the default sysop password plainly**: `unleashed`, which
  works only from the board's own network and only until it is changed. The
  first call from the same network asks for it and then for a password of your
  own; the board will not list itself while the default is set; and the page
  is honest that "local only" is a guard, not a wall, because a router that
  rewrites forwarded traffic can make an outside caller look local. It
  replaces the TODO comment that held the place. These are the firmware
  side's facts for 1.0.0.
- **/setup, "Set up your BBS"**: every CONFIG page and every setting, board,
  limits, accounts, backup, staff and wifi, then chat, files, forums, info,
  announce and sd, with serial and example noted as off. Every fact from the
  firmware source and COMMANDS.md at 0.22.3; "as shipped" values from the
  shipped `system.cfg`. Linked from /install, /build and the announcement
  banner, under Build one in the menu.
- **The board's own screens on /setup**, captured from the firmware's host
  build on 127.0.0.1 in a worktree of its own, and drawn as the site's line
  art rather than pictures: `shots/<name>.json` keeps every cell's character,
  colour and reverse video, and `shot_svg()` pins each run to its columns.
  `shots/capture/` is how to do it again. A three-step drawing opens the page.
- **The wordmark links to the board list** on every page and every face.
- **The announcement banner**: a yellow box above the board list saying
  µnleashed BBS is released, with line art and links to build one, flash it
  and set it up. It renders only when a firmware release of 1.0.0 or later is
  on disk, so it cannot go live early and appears by itself when one lands.
- **update.sh fetches the firmware release** (`deploy/fetch_release.py`): the
  latest public GitHub Release of rwmech/unleashed_BBS, tagged vX.Y.Z, seven
  assets. Every file is checked against SHA256SUMS, and the screens image for
  credentials, in a staging directory before anything moves; any failure
  leaves the installed release untouched. The newest two are kept. It runs on
  every update, and a failed fetch says why without failing the update.
  Fetched releases are git-ignored.
- **The avatar**: the wordmark in the site's line art, inside a circle. In
  `brand/` with its generator, served at `/avatar.png` (og:image,
  twitter:image) and `/apple-touch-icon.png`.
- 393 checks, up from 355, including the release fetcher against a release
  served from 127.0.0.1 with every way it should refuse. The banner threshold
  and the checksum check were proved by breaking each.

## 0.15.0, 2026-09-23

Rob: "Have the website agent get the web flasher running." The firmware
speaks Improv Wi-Fi Serial from 0.22.1, so the installer page can now do what
it was built for: flash a board and set its Wi-Fi, from the browser.

- **ESP Web Tools is served from this site, not from unpkg.** 10.4.0, the
  current release on npm, checked against the registry's SHA-512 and copied
  into `vendor/esp-web-tools/10.4.0/` byte for byte: the package's `dist/web`
  build, 26 files, all of whose imports are relative. Served at
  `/install/esp-web-tools/10.4.0/` as JavaScript. Its Apache 2.0 licence and
  the licences of the eleven libraries built into it sit beside it and are
  linked from the page. `SHA256SUMS` is checked on every self-test run, and
  `.gitattributes` keeps the directory binary so no line ending changes. It is
  still the only JavaScript on the site, still only on `/install`, and still
  only emitted when a release is published.
- **A release is five parts, served same origin under `/install/<version>/`.**
  `bootloader.bin` at 4096, `partitions.bin` at 32768,
  `ota_data_initial.bin` at 61440 (new: it points the board at the slot the
  application is written to), `firmware.bin` at 131072 and `storage.bin` at
  3932160, read from the firmware's `partitions.csv` and generated
  `sdkconfig`. The server builds the manifest from the files it finds, with
  `new_install_prompt_erase` true and `new_install_improv_wait_time` 30 for
  every release, because every release now speaks Improv and the first boot
  after an erase formats storage before it answers. Nothing is served from
  `/firmware/` any more.
- **With no release published, the page says so and offers no button.** The
  old reason, the Wi-Fi being compiled in, is gone from the copy because it is
  no longer true.
- **`/install` rewritten against the installer's own source**: which browsers
  (Chrome and Edge on a desktop; Firefox from 151 with its extra prompt;
  Chrome on Android from 148, said to be untried; nothing on iOS), the cable
  and the drivers, the steps in order with the words the dialog uses, the
  30 second waits, what happens to an already-installed board (0.22.1 and
  later is updated with no erase question, and **Erase User Data** wipes the
  whole chip), changing the Wi-Fi later, and where to go next.
- **The sysop password step is a marked TODO in the page source, and nothing
  on the page.** A web-installed board has no sysop password yet and no way
  to set one; the page promises nothing until the firmware can do it.
- **The Markdown dialect gained comments**, `<!-- ... -->`, dropped whole, so
  that TODO can sit where the step goes. The suite counts them in every page,
  because an unclosed one would swallow the rest of it.
- **An older release kept on disk has its own button**, "Install 0.22.0
  instead", where it used to be a link to a JSON file nobody could use.
- **The suite reads every committed `storage.bin`** and fails if a staff
  password, Wi-Fi key or directory token in it has a value. It replaces the
  check that failed on any release at all, which was the right gate while the
  Wi-Fi was compiled in and is the wrong one now.
- 355 checks, up from 335, including a second server started against a
  scratch release to test the route, the content types, every part the
  manifest names and the page's script tag end to end. The vendored bundle's
  checks were proved by deleting a chunk and editing a byte.

## 0.14.0, 2026-09-22

Rob: "In the header ... of the hero unleashed, put one of those ... line
drawings with text and icons that rotate through that highlight the
'freedoms' that we have. GPL2+, etc. It cant be very wide it just needs to be
on the right side ... Retro scifi."

- **The board's freedoms, beside the wordmark on every page.** A narrow panel
  to the right of µnleashed, headed with the board's motto, Electronic
  freedom, showing one freedom at a time with a line drawing and a short line
  saying what it means:
  - No web: a BBS, not a website
  - No cloud: nobody else's server
  - No browser: a C64 can call in
  - Real hardware: a chip on your shelf
  - GPL v2 or later: free software
  - No internet needed: a local network is enough
  - You write the rules: and you are the appeal
  - Run your own directory: this one is free software

  The first five are the board's own welcome screen (`tools/mkscreens.py` in
  the firmware): its tagline, its ANSI line and its licence line. The other
  three are the manifesto's, and each was already checked there.
- **Retro sci-fi line work, and nothing from LCARS.** Thin `--dial` lines
  with two corners cut, brackets round the drawing with a scan line sweeping
  down inside them, a scale under the words with a caret that crosses it
  once per freedom, and eight segments that light in turn. Site palette
  only; the heading is `--name`, the wordmark's own colour.
- **CSS only, no script.** Four seconds each on one 32 second timeline. The
  change is out and then in, 0.3 seconds each, rather than both at once:
  two lines of different words at half strength on top of each other read
  as a smudge. All of the motion is inside
  `prefers-reduced-motion: no-preference`, so a reader who has asked for
  less motion sees one freedom, standing still.
- **A screen reader gets all eight, in order**, as one list named
  "Electronic freedom". The fade is opacity, which leaves every word in the
  accessibility tree; the drawings are hidden from it.
- **Each section of the menu opens on a different freedom**, from its
  position in the menu, because the timeline starts again on every page
  load and a reader clicking round would otherwise only ever see the first
  two.
- **It appears only where it fits beside the wordmark**, from 73em. In em,
  so the breakpoint follows a reader's own default text size along with the
  wordmark. The figure is the wordmark in the widest font the stack can land
  on, the padding, the gap and the panel, and the suite does that sum
  against the stylesheet. Below it the panel is not shown, rather than
  stacked under the wordmark, because stacked it would push the menu down on
  every page on a phone; the manifesto says the same things at length.
  Measured in headless Chrome at 390, 901, 1100, 1168, 1280, 1366 and 1920:
  nothing past the right edge at any of them, and at the widths that show
  it, the panel shares the wordmark's top and bottom.
- Two checks found the drawings' reduced-motion block by taking the first
  one on the page. The page stylesheet has its own now, for the panel, and
  it comes first, so they look inside the drawings' stylesheet.
- 335 checks, up from 323. The two that guard the reduced-motion gate and
  the breakpoint were proved by breaking each and watching it fail.

## 0.13.2, 2026-09-22

Rob: "under build one, love the table, add some of those awesome graphics on a
linked page from the table that says SD Card wiring diagram and include a bad
ass wiring diagram, chips, card, etc on there."

- **A wiring diagram on `/sdcard`, directly above the pin table it draws**,
  rather than a second page that could drift from the first. The ESP32 dev
  board with its module can, antenna and headers; the SD module with its
  regulator, level shifter, socket and the card in it; and six wires between
  them, each one colour from pin to pin with its name at both ends and on the
  wire. Ground is `--faint` and power `--busy`; the data lines take four
  palette colours and never `--risk`.
- **The pins are the firmware's defaults and nothing else**: `struct SdPins`
  in `src/platform/platform.h`, CS 5, MOSI 23, CLK 18, MISO 19. The rows run
  in the order the common module prints its header, so every wire is
  straight, and the note under the drawing says to go by the printed names
  because no board promises that order. The power line says what the page
  already says: start on 3V3, some modules want 5 V, see the note below.
- **A check reads the pin names at both ends of every wire out of the
  drawing and compares them with the table on the same page**, so the two
  cannot disagree. Proved against a drawing with MISO and MOSI swapped.
- A pulse runs the data lines in the order a transfer happens: CS, then the
  clock and MOSI together, then MISO back. It stops under reduced motion like
  every other drawing here; two frames 1.2 s apart are identical with motion
  reduced.
- **`SD card wiring diagram`** is a link in the board table on `/build`, in
  the reference board's row. `/build` and `/teachers` both said the SD page
  had "the three things that usually go wrong", which went stale when its
  error table grew to four real messages in 0.13.0; they name the pin map,
  the diagram and the error messages now.
- Labels are 10 units, about 9.6px on a phone. Measured through sized iframes
  at 390, 1366 and 1920 on `/sdcard` and `/build`: no horizontal overflow, the
  diagram 340px wide on a phone and 640px on a desktop.
- The check that the power advice comes before the wiring table looked for
  the first `GPIO18` on the page, which is now a label in the drawing; it
  measures against the table's own SCK row.
- 6 new checks, 323 in total.

## 0.13.1, 2026-09-22

Rob: "get some of those awesome line graphics on the terminals page. try to
make pictures for the different systems, atari, commodore, chromebooks, etc."

- **Eight drawings on `/terminals`, one under each heading**, in the hand of
  the rest: a laptop and a phone; a Chromebook you control beside a managed one
  with a padlock on its screen; a Commodore 64 with a 1541 and a monitor
  reading READY.; an Atari 800XL and a television; an Apple II with its Disk II
  and bracket prompt beside an Amiga 500; a DOS PC and a TRS-80 Model 100; a
  VT220-style terminal and a Teletype Model 33; and the bridge, an old machine
  on a serial cable to a small box with an aerial, reaching the board over
  Wi-Fi.
- **Only machines the page names, and no logos.** The Commodore's rainbow is
  four stripes in the site's own colours, not a badge, and each machine is
  recognised by its shape: the breadbin, the 800XL's column of console keys,
  the Apple II's `]` prompt, the A500's function keys in two groups of five.
  The labels are machine names and nothing else, so the drawings add no
  claims to the page.
- The only motion is the screens' carets and a dot travelling the bridge's
  serial cable, both declared inside the no-preference block like every other
  drawing here. Each is 354 units wide, 1:1 in a phone column, and at most
  24rem on a desktop.
- **Measured, not assumed:** through exactly sized iframes at 390, 1366 and
  1920, `scrollWidth` equals `clientWidth` and no element extends past the
  right edge. The drawings are 340px wide on a phone and 513px on a desktop.
- **The first cut ended three strips on their label baseline**, and the
  descenders were cut off. The render showed it; a check now does the
  arithmetic on every strip, lowest label plus eight units inside the viewBox,
  and fails on the first-draft heights.
- 3 new checks, 317 in total.

## 0.13.0, 2026-09-22

Rob's standard for this one, verbatim: "Check factuality on every assertion on
the website. Fix issues, make no mistakes." Every page was read against a
primary source or against the firmware at 0.21.6, and what was wrong is fixed
below. Also an author page, and drawings across the site in the hand of the
connection diagram.

**What was wrong, and what it rested on:**

- **CBBS had 24 kilobytes, not 64.** Christensen and Suess's own article in
  Byte, November 1978, page 150: "an 8080 processor with 24 K bytes of memory,
  single floppy disk". The manifesto said 64, and "this has eight times that
  memory" was built on it. It is more than twenty times. The blizzard stays,
  because Wikipedia carries it from an early interview, but it "dumped record
  snow across the Midwest" rather than "shut the city down", which nothing
  supports: Chicago got 12 to 13 inches.
- **"A few tens of milliamps", in three places, is the figure for a radio that
  dozes.** This firmware holds it awake with `WIFI_PS_NONE`, and Espressif's
  WROOM-32E datasheet (v2.1, table 16) puts receive alone at 112 mA. It is
  "about a tenth of an amp" now, and `/build` gives the transmit peak, which the
  same table puts at 379 mA.
- **Signing up asks for a name and an email address.** Both are `UF_REQUIRED`
  in `users.cpp`. The freedom box headed "No account, no email address, no
  phone number" said sign-up was a handle and a password. It is "Nobody checks
  who you are" now, which is the true and better claim: neither field is
  verified, because the board cannot send email. `/firstcall` says the same,
  and its "what a board knows about you" said the sysop was the only person who
  sees any of it, which `WHOIS` contradicts: other callers see your name and
  profile.
- **"A Commodore 64 cannot do TLS" and "never will" are both false.** A stock
  C64 has finished a TLS 1.3 handshake in 6502 assembly
  ([JC-000/c64-https](https://github.com/JC-000/c64-https)), in about 36
  minutes. The manifesto and `/privacy` say that now, which is the stronger
  argument anyway.
- **Forums were "being built" in five places after they were built.** They
  shipped in firmware 0.21: `FORUMS` in COMMANDS.md, `PF_SD` in `forums.cpp`,
  so a card and a sysop who switches them on. The checks that pinned "being
  built" now pin the opposite.
- **Connecting is not always silent.** A terminal that does not answer the
  probe is asked to press DEL or BACKSPACE, and a Commodore is then asked for 40
  or 80 columns (`detect.cpp`). Four pages said you configure nothing, and
  `/terminals` said the board works out 40 or 80 by itself.
- **`/how`'s config example set a key the board ignores.** The announce plugin
  stopped reading `name`; the board's name is `board_name` in the core section.
- **The Chromebook section led with a sentence Rob did not believe, and was
  right not to.** It leads with who controls the machine now: one you control
  usually can, a managed one usually cannot without its administrator, Chrome
  alone never can. Google's own help confirms every setting name on the page.
  Two details were tightened: ChromeOS 138 was the *last* release to support
  user-installed Chrome Apps, and Secure Shell "does not" speak telnet rather
  than "has never", since the present is what its source tree shows. Isolated
  Web Apps, Chrome's newer route to a raw socket, install only by
  administrator policy, and the page says so rather than leaving it to be
  found.
- **`/sdcard` had four wrong things in it.** GPIO5 is a strapping pin for SDIO
  slave timing only (Espressif datasheet, section 4), so a card module cannot
  stop the board booting through it. The third error it quoted, "card would not
  mount", does not exist in the firmware; the real strings are in the table now.
  `diskpart` refuses FAT32 above 32 GB, so sending Windows users to it was
  wrong; Microsoft lifted the limit for the `format` command only, in
  KB5083631 in April 2026. And "3V3 works on every module worth buying" is not
  true of the common blue module with an AMS1117 regulator, which is specified
  for 4.5 to 5.5 V. 3V3 stays the starting point, because it cannot damage
  either kind.
- **`/whofor` still said one board serves the class**, the claim 0.12.2 fixed
  on `/teachers` and missed here. And "there is no client to install" is not
  true on a Mac or a Windows machine.
- **`/install`**: a partition move has needed the full erase twice, at 0.14 and
  0.17, not once; "every browser on iOS is Safari underneath" is not true in
  the EU and is dropped for the claim that matters, dated; and the Wi-Fi section
  describes the installer as it will be, so it says so. `/build`'s invitation to
  the installer no longer says it works today.
- **The router pages**, against every vendor article they cite. NETGEAR now
  names the "External Ending Port" field the page said it did not name, reaches
  password recovery by three wrong logins rather than CANCEL, and moved its
  reservation article, which now redirects to an error page. TP-Link recovers
  passwords through a TP-Link ID and does not document Tether's menus. ASUS
  documents `asusrouter.com`, not `router.asus.com`, and puts the IPv6 firewall
  under Firewall > General. Google no longer says a reservation is required.
  Xfinity's article names no gateway models. Every changed claim has its source
  in the page's list.
- The smaller ones: "sixty-five years on" from 1960 is sixty-six; the 60,000
  boards were InfoWorld's 1994 estimate, not a count at the peak; the ESP32
  "runs at up to" 240 MHz, and this firmware runs it at 160; `/health` answers
  three bytes, not two; guests leave a line in the caller log.

**A renderer bug, found by checking the links.** A Markdown link target with
parentheses in it, which every archived Microsoft document has, lost its
closing parenthesis, so two sources on `/dialing` 404'd with a stray ")" after
them. One level of balanced parentheses is allowed in a link now.

**`/author`**, from QuantumRob's name in the byline and both signatures.
Everything on it is Rob's own account, the Psyberchat spelling confirmed by
him; nothing was added from searching his name, which is common enough that a
namesake is a real risk. Four photographs are hotlinked from Wikimedia Commons,
credited with author, licence and file page, requested with no referrer, at
Wikimedia's standard thumbnail widths, because Wikimedia rejects any other
width with an error page a browser shows as a broken image. The page says where
its pictures come from, and THIRD_PARTY_NOTICES.md lists them.

**Drawings, in the hand of the connection diagram.** One per freedom on the
manifesto, three screens on `/firstcall`, and a skull in a new amber stop box
on `/how`, which says spam earns a lifetime IP ban and says that it is policy
applied by hand, because nothing in the software detects spam. The rule that
makes them safe: every animation is declared inside
`prefers-reduced-motion: no-preference` and nowhere else, so the drawing as
written is the resting state and has to say its whole piece standing still.
Checked by rendering: two frames 1.2 s apart differ by thousands of pixels with
motion allowed and by none without. A first version declared the icons'
animations against a class on the wrong element and none of them moved; the
frame comparison is what showed it.

`::: art` is new in the dialect: a drawing by name, so a Markdown page can
carry one without the dialect gaining inline HTML.

**Which ESP32, as a table on `/build`** (Rob). Two cores and Wi-Fi on the chip,
because the BBS loop runs on core 1 while Wi-Fi owns core 0, from
ESP32_BOARD_CHOICE.md in the firmware repo; each chip's core count and radio
checked against Espressif's own product pages. The WROOM-32E is the only one
anybody has run and the table says so; the WROVER and the S3 are "should work,
not yet tested", with no caller count, because the old estimates came from an
older session size and were never measured; the S2, C3, C5, C6 and H2 have one
core (the C6's second core is a low-power one that cannot run the board), and
the P4 has no Wi-Fi. The C5 is not in the firmware's document and is here
because its dual-band Wi-Fi is exactly what makes somebody reach for it. It
replaces "any module with the same flash will do" on `/build` and "any module
with 4 MB of flash works" on `/teachers`, both of which were true of a 4 MB C3.

38 new checks, 314 in total. The two that matter most were proved to fail
against the bug they pin: the link check against the old pattern, and the
animation check against an animation declared outside the block.

## 0.12.3, 2026-09-22

The manifesto's two diagrams were hand-drawn ASCII in a `<pre>`. They are
inline SVG now, drawn properly, and the animated one still animates.

- **ASCII art on a web page has a font size for a width, and that is the whole
  problem.** The art is laid out in character cells, so the only lever for
  making 61 columns fit a 358px phone column was shrinking the type until the
  letters were 6px, which is what `.scene`'s `clamp(6px, ...)` was doing. Every
  monospace font renders the same block a few percent differently, so the fit
  was a guess in the first place. A viewBox fits any width for free.
- **The connection diagram was eight whole copies of itself**, flipped 0.4s
  apart with `steps(1,end)` and eight `animation-delay` values: a flipbook, and
  45 lines of markup to move one character four positions and back. It is one
  marker on one wire now, translated across 164 units of viewBox with
  `ease-in-out`, so the motion is smooth rather than in four steps and the round
  trip reads as a round trip.
- **It gained two things it could not have had as text.** A terminal with a
  blinking caret, and a chip with pins and a lamp that lights at the instant the
  marker reaches it: the lamp's cycle is 6.4s against the marker's 3.2s
  `alternate`, so the two are locked together by arithmetic rather than nudged
  into agreement.
- **The resting state is a design requirement, not a fallback.** Under
  `prefers-reduced-motion` the marker parks half way along the wire, the lamp is
  lit and the caret is solid. That is also what a screenshot and a printout get,
  so the drawing has to make its point with nothing moving, and parking the
  marker at either end would have said something the diagram does not mean.
  Verified by sampling the marker's position four times over two seconds: 683px,
  unmoved, against 545 to 799 with motion allowed.
- **The comparison is two SVGs, not one, and that is forced rather than
  chosen.** A viewBox scales; it does not lay out again. One drawing could never
  stack on a phone, so it is two panels in a grid that goes to one column at the
  site's single 900px breakpoint. `align-items:start` keeps them at their own
  heights, which is the argument itself: the left panel is 596px tall because
  four parties keep a record and the right one is 338px because one does, and
  the paragraph under it already says "the right-hand column has no boxes to
  add".
- **The red was a literal in one block's stylesheet.** `#e06c6c` is `--risk` at
  the root now, documented as the one colour on this site meaning somebody else
  is keeping a copy of you, and the green is the existing `--live`. A colour
  carrying an argument should not be able to drift away from the site making it.
  `#6ee36e`, the old diagram green, is gone.
- **Every shape declares a fill, including the lines.** An SVG shape with no
  fill is black, and black on `#0d0d12` is a shape nobody can see. Checked by
  render rather than by reading: 61 shapes across the three drawings, none
  computing to `rgb(0, 0, 0)`.
- **The viewBox origins are negative** (`-5 -6 354 138`, `-6 -8 356 382`,
  `-6 -8 356 216`). The frame is a CSS border on the SVG, so the only way to
  hold the outermost label off it is inside the coordinate system, and a
  negative origin is one number per drawing against shifting forty coordinates.
  Before it, the titles sat 6px from the border.
- **`role="img"` makes the whole drawing one object**, so nothing inside it is
  announced and the `aria-label` has to carry the entire argument: five parties
  who keep a record, named, against one that keeps a text file. 427 characters
  and 168, not "a diagram".
- `article pre:not(.chart)` is `article pre` again. The exception existed for
  the one `<pre>` on the site that wrapping would have destroyed, and there is
  no longer such a `<pre>`.
- **Measured at three widths in both colour schemes and both motion settings,
  twelve combinations, in headless Chrome at an exactly sized viewport.** No
  text or shape escapes its viewBox in any of them;
  `documentElement.scrollWidth` equals the viewport at 1920, 1366 and a real
  390, so nothing scrolls sideways; the smallest label is **10.0px at 390** and
  16.4px at 1920 against an 18.6px body. The two colour schemes render
  byte-identical, which is the expected answer for a site that declares
  `color-scheme: dark` and carries no `prefers-color-scheme` rule anywhere.
- **The one thing that did not survive the translation:** the ASCII version drew
  the four "what it keeps" boxes hanging under their party with a `+---+---+---+`
  join underneath. Laid out vertically that join would have crossed three boxes,
  so it is a bus running down the right edge with a stub per box. Same claim,
  different shape.
- 12 new checks, 276 in total. The px scan now exempts `svg.wire` and
  `svg.trace` alongside `svg.hours text`, for the reason it already exempted
  that one: a `px` inside a viewBox is a user unit and scales with the drawing.

## 0.12.2, 2026-09-21

A copy pass over all twenty-one pages. Words only: no layout, no CSS, nothing
restructured. Three things came out of it that are not tidying.

- **The teachers page told a teacher one board serves a whole class.** It does not: a board answers ten callers, `BBS_MAX_NODES` in the firmware, and it is not a config key. Session 1 is thirty students all connecting at once, so the page would have failed in front of a class, on the first exercise, with no way to recover in the room. It now says ten, and says what to do about it: pairs, threes, or a second board. Pinned by a check.
- **Forums, not message bases.** `/build` and `/sdcard` still used the old name for the same unbuilt feature while `/kids` and `/about` used the new one, so a reader meeting both words assumes they are two things and goes looking for the one that does not exist. A check now walks every page and fails on "message base" anywhere.
- **Wi-Fi was spelled four ways**, 9 Wi-Fi, 17 wifi, 14 Wifi and 4 WiFi. It is Wi-Fi in prose everywhere now. `Google Wifi`, `Nest Wifi`, `Nest Wifi Pro` and Xfinity's `WiFi` menu stay exactly as they are, because those are product names and labels a reader will see on their own screen, and a check that flagged them would be a check telling us to make the instructions wrong. So the check matches a bare lowercase `wifi` only.
- The manifesto: "What was lost was not the modem noise" in place of "The thing that was lost was"; one sentence in "What this is" cut, because it repeated the drawer sentence in the freedoms box almost word for word; "Privacy forward, and what that means"; the RS-232 sentence split at its first "and".
- `/whofor`: two sentences tightened, "Just a socket and some characters" is now "A socket and some characters", and a real grammar fix, "Solar, a battery and a wifi access point **is** a working board" was a plural subject on a singular verb. `neighborhood` to `neighbourhood`, the site's only other US spelling being `decentralized`, which a check pins and which is left alone.
- `/privacy`: three "actually"s gone, including two section headings, and one sentence that said the same thing twice ("none of it happens by itself, none of it is automatic"). The page's register is unchanged: it is not there to reassure anybody.
- `/build`: "Nothing about any caller is ever in it: the board's name, who runs it..." read as a list of what is **not** sent, which is the opposite of what those four items are. Also a sentence fragment with a dangling modifier in the power bullet, which is the one line somebody sizes a supply from.
- `/kids`: six small cuts, all of them shortening sentences. Flesch-Kincaid moved from grade 3.7 to **3.6**, against a ceiling of 6.5.
- `/dialing`: "Here is why, and the fix, in the order most people should try them" had no antecedent for "them".
- `/terminals`, `/install`, `/forward`, `/forward-asus`, `/forward-netgear`: one filler word each.
- Verified by rendering all twenty-one pages and checking the prose for leaked Markdown, not by grepping the source. Clean on every page.
- 3 new checks, 264 in total.

## 0.12.1, 2026-09-21

- **"Freedoms gained" is two columns, and it is a position rather than a feature list.** Rob asked for both in one sentence, and the second half was the larger job. The boxes are about 60 characters wide in a 130 character column, so one to a row left half the page black and made a short list four screens long.
- **CSS grid, not `column-count`.** Multi-column would let a box break across the boundary, and each of these is one claim that has to stay whole; it also fills the first column before the second, so the reading order would depend on how tall the boxes happened to be. Grid is row major, so the order down the source is the order across the page. Nothing uses `order:`, deliberately: a screen reader follows the source, and twelve related claims read in a different order to the one on screen is a different list. `minmax(0, 1fr)` rather than `1fr`, because a track's default minimum is its content and one long unbroken string would widen its column and narrow the other. One column at 900px, the site's single breakpoint, where two columns would be two gutters and fifteen characters a line.
- **Rob's words were covert, hides in plain sight, mobile, discreet, use it anywhere. One of those is a claim this site must never make.** The privacy page spends a screen saying that telnet is plain text and anybody on the path between a caller and a board can read it. Copy implying the network hides you would contradict it in the one place somebody is being talked into trusting the thing, and would mislead exactly the reader who most needs the truth.
- **So the section is written to what is actually the case, which is stronger anyway.** Nobody has to say yes: no application, no review, no API key, no app store. It works with no internet at all: an office network, a hotspot, a mesh, a switch in a room with no uplink, and the board is the same board. It fits in a pocket and runs off a battery. It does not announce itself as anything, and that box says in as many words that this is discretion of the object and not of the wire, with a link to the privacy page. Independence and self-reliance, not evading observation.
- Twelve boxes now, from eight. Four new, four kept, four rewritten, and two of those were making claims the software no longer makes.
- **A stale claim, fixed in three places: mail is not "gone the moment it is read".** That stopped being true at firmware 0.17.12, where reading a message offers reply, save or delete and touches nothing until a key answers. The manifesto said it in the freedoms box, in "What this is" and in the privacy section, and each one was a promise the board does not keep. It also said that the only people who know a sensitive meeting happened are the people who were in the room, which is true on a local network and an overclaim on a public one. That sentence is gone.
- Measured in headless Chrome through exactly sized iframes, not grepped: at 1920, two tracks of 682.3px at 61 characters to a line; at 1366, two of 625.8px at 55; at 390, one track of 318.7px at 30, which is what every other box on the site gets there. Zero horizontal overflow at any of the three, and source order matches visual order at all three.
- 15 new checks, 261 in total. Eight of them pin phrases the section must never contain, by name.

## 0.12.0, 2026-09-21

- **A browser installer at `/install`, in the shape WLED's is: plug an ESP32 in, click a button, have a BBS.** Everything is built except the one thing that cannot be built yet, which is the firmware image itself. The page, the manifest, the release directory, the serving, the copy and the process are all here and tested; `firmware/` ships empty and the page says so.
- **Why it ships empty, and it is not caution.** Wi-Fi credentials are compiled into the firmware from `include/secrets.h`, so any image built from the current tree carries one person's home network name and passphrase in plaintext, recoverable with `strings`, and is useless to a stranger because it can only ever try to join a network that is not theirs. The fix is Improv Wi-Fi Serial, which moves the credentials out of the build and lets the browser set them over the same cable it just flashed with. That is queued firmware work. **A second leak was found while writing the release process and it is not the same one:** `data/system.cfg` carries `sysop_password` and is built into the filesystem image, so a release has to be built from `system.cfg.example` as well as from `secrets.h.example`. Both are steps in the process, with a `strings` check that proves it before anything is published.
- **The state is the directory, not a list.** `server.py` walks `firmware/` on each render and builds the ESP Web Tools manifest from what is actually there. A chip family is offered only when all four of its parts are present, so **a release cannot be half-published**: a manifest part is only ever emitted for a file just found on disk, and a manifest naming a file that is not there fails in the browser, halfway through, on somebody's board. "Nothing available yet" is the absence of files rather than a flag somebody has to remember to flip, which is the same argument `pix_html()` already makes about card art.
- **Two releases live, and a third on disk is not merely unlisted.** It is not reachable by typing its version number either, or "two live" would be a statement about the page rather than about the site.
- **The offsets were read, not recalled**, out of the firmware repository's `partitions.csv` and its **generated** `sdkconfig.esp32dev`: bootloader `0x1000`, partition table `0x8000`, application `0x20000` (the `ota_0` row), screens `0x3C0000` (the `storage` row). The bootloader offset is a property of the chip family rather than a constant, because an S3 or a C3 puts it at `0x0`, and `FLASH_FAMILIES` is what makes a second chip family a directory drop instead of a rewrite. `offset` is a decimal JSON number: their type is `offset: number`, JSON has no hex literal, and `"0x20000"` would be handed to the flasher unparsed. The suite pins it as a type as well as a value, because that is the one mistake in this schema that writes a board at the wrong address.
- **`userdata` and `logs` are not in the manifest, and that is the feature.** Only the four regions named get written, so somebody reinstalling over a board they already run keeps their accounts, their settings, their chat mail, their directory listing and their caller log. It is the same split `pio run -t flashall` respects and the reason the 0.14.0 partition rebalance was worth doing. `new_install_prompt_erase` is `true`, which makes the tool ask rather than erase silently, and the checkbox it produces **starts unticked**, so it flips the default from erase to keep. The page says which answer a reader wants in as many words, because the newcomer and the returning sysop want opposite ones.
- **`improv: yes` in a release's `release.txt` is the only knob**, and it fails safe. Absent, `new_install_improv_wait_time` is `0`; without that, ESP Web Tools waits ten seconds after every install for a board that will never answer, sitting on "wrapping up" and then carrying on, which reads as a hang. It is a property of the firmware in that directory, so it is recorded beside the binaries and not in a constant here.
- **The first JavaScript on this site, and it is fenced by construction rather than by care.** ESP Web Tools, pinned at `10.4.0`, from unpkg, on `/install` and nowhere else. **The script tag is emitted only when the page carries `::: installer` and `firmware/` actually holds a release**, so the script and the widget arrive together or neither does: a page with no button cannot ship third-party code, and a button cannot appear without the code that drives it. One condition in `md_page()`, not a flag to keep in step. Today, with nothing published, the whole site is still script-free, and the suite walks fifteen pages and fails on a `<script>` in any of them.
- Pinned to an exact version rather than to the major their own documentation suggests, because a major tag still means the code a visitor runs can change between one reader and the next. THIRD_PARTY_NOTICES.md now carries all of this **above** its claim that nothing a visitor loads comes from anywhere else, rather than leaving the claim quietly false.
- **`::: installer` is the third `:::` block and the only one that is not prose.** It carries no content of its own, because what it should say depends on what is in `firmware/` and not on what somebody typed into the page. Blocks dispatch through `md_block()` now; an unknown name after `:::` still falls through to a paragraph, so a typo stays visible instead of swallowing the rest of the page.
- **The copy corrects something that was handed to it as settled, and the correction matters to a reader on a Mac.** Web Serial is not Chrome and Edge only any more: **Firefox 151 shipped it in May 2026**, desktop only, with an extra permission step Chrome does not have. Checked against MDN's own `browser-compat-data` rather than recalled. Safari still cannot, and neither can anything on iOS, since every browser there is Safari underneath whatever name is on the icon. The page says Chrome or Edge is the path that works, Firefox is the harder road rather than a broken one, and Safari is a dead end.
- The rest of the page is the things that actually go wrong: a charge-only USB cable, which is the single most common cause of "no device found"; something else holding the serial port; the CP210x and CH340 drivers; holding BOOT; and what a full erase takes with it. `/build` leads with an invitation to it and it is in the footer of every page, but not in the menu, because nine items is already the edge of what a phone can carry.
- Paths under `/firmware/` are checked as names rather than as paths, the way `static_file()` does it, so nothing climbs out; the suite tries six ways.
- Measured in headless Chrome at 1920, 1366 and a genuine 390 through an exactly sized iframe, in both states. Root font 21.28px, 21.28px, 18.40px; body 18.62px, 18.62px, 16.10px; zero horizontal overflow on any of them. With an image present the custom element upgrades, sets `install-supported` on itself, and draws our own button in `--dial` on monospace rather than a sky blue pill: 340px wide at 1920, and 290px inside a 338px column at 390.
- 32 new checks, 246 in total.

## 0.11.8, 2026-09-21

- **Chromebooks appeared nowhere on this site, which for the audience `/teachers` is written for was the largest gap on it.** School fleets are overwhelmingly Chromebooks, and every terminal the page recommended is one a Chromebook cannot install. `/terminals` has a Chromebook section now, and `/teachers` has a short one that sends teachers to it before they plan a lesson around machines that may not be able to take part.
- **The honest answer is the useful one, and it is sometimes no.** Chrome cannot open a plain connection and no extension can either: `chrome.sockets.tcp` was a Chrome Apps ability rather than an extension one, and user-installed Chrome Apps stopped working on ChromeOS in July 2025 at ChromeOS 138. Google's own Secure Shell is an SSH client and has never spoken telnet. So a Chromebook needs the Linux development environment, or the Play Store and an Android app, or a proxy somebody runs, and on a locked fleet all three belong to somebody else. The page says that plainly instead of listing hopeful steps that fail at step one, because a teacher who follows instructions that cannot work concludes the project is broken and does not try again.
- **It names the setting, so the request can be specific.** Google Admin console, **Devices > Chrome > Settings**, the **User & browser settings** page, section **Virtual machines (VMs) and developers**, setting **Linux virtual machines (BETA)**, which on managed devices defaults to **Block usage for virtual machines needed to support Linux apps for users**. The matching device-level setting for accounts from outside the organisation's own domain is named too, because without it the first one appears to do nothing. All of it read off Google's own policy help rather than recalled, along with the Play Store path and the sandbox wording an administrator will actually ask about.
- **The browser route is given with its cost attached.** A web page cannot open a telnet connection, so fTelnet and anything like it hands the connection to a WebSocket proxy, and that proxy reads everything in both directions, password included. A fair trade on a proxy you run yourself, a public conversation with one more listener on one you do not, and it is written that way rather than left for the reader to work out.
- **Two stale facts on `/terminals`, found while checking the rest of it.** NetRunner was listed as Windows and Android; its author ships Windows and Linux and there is no Android or Mac build, so a phone reader was being sent to a download that does not exist for them. Android points at TERMinator now, which is current, is a real BBS terminal with CP437 and ZMODEM, and is also what a Chromebook with the Play Store can run. Re-checked and still correct: macOS has had no `telnet` since High Sierra, Windows ships one as an optional feature that is off by default and renders ANSI poorly, and `inetutils-telnet` is still the package on Debian stable.
- No new checks. 214 in total, unchanged.

## 0.11.7, 2026-09-21

- **The children's page is cards now, and the reason is not that it was long.** Rob: "sure it looks like a BBS but they dont know what that is!" The retro terminal look is an in-joke that only lands if you already know what a BBS is. Everywhere else on this site it does real work, because the audience recognises it; on the one page written for a ten year old it asked a reader to decode an unfamiliar visual language before giving them a reason to care. Twelve short boxes, one idea and one payoff each, readable in any order.
- **The headline is that they can run one, and that is Rob's insight rather than mine.** "I would call out in that kid page that they can host it for their friends." He is right that it beats "you can call a board": nowhere else in their life do they get to own the room. It leads with the comparison that does more work than the rest of the page combined, which is that somebody who has run a game server for their friends already understands this entire project and is only missing a word. **The comparison stays in running prose and never in a heading, a filename, an alt text or the page title, and no art may reproduce anything owned by Mojang or Microsoft.** That constraint is written into `static/kids/README.md` so it is inherited rather than rediscovered.
- **Chat is framed as the reason to run your own board, not as a feature of somebody else's.** This is the one claim on the site with the potential to actually harm somebody if it were written the obvious way. A chat room on a board in this directory is a public room on a stranger's machine, unencrypted, shared with whoever dialled in; calling that a safe space, on the page aimed at children, would contradict this site's own privacy page to the audience least able to spot it. The safe room is the board **they host**, and the honest version is the better pitch anyway. The suite pins it: the phrase "safe space" must not appear on the page, "Nothing you type is private" must, and both `/privacy` and `/forward` must be linked.
- **No named enemy**, settled by Rob. The page is written from what the reader gets rather than what they are escaping: your board, your room, you decide who gets in. Naming an out-group invites a reader to file themselves under victim rather than owner, and it dates fast.
- The grown-up thread is logistics rather than permission: it runs on hardware in their house, on their internet, and opening a port is their call. Everything the old page pinned is still pinned, including "That decision belongs to the adult", "It is not practice for a real one", and the list of things never to type into a board. Measured at **Flesch-Kincaid grade 3.7**, against a suite limit of 6.5.
- **Forums are named as being built, never as present.** A feature in the present tense that does not exist is a claim that fails on first contact: somebody who calls a board looking for it concludes the software is broken rather than that the website ran ahead. The manifesto and the SD card page already carried "what is coming" in a sentence of its own, outside the list of what a caller can do today, so only the name was stale. The new checks fail if the page ever says forums are available.
- **Four additions to the Markdown dialect**, and they are the mechanism rather than decoration. `::: cards` ... `:::` is the grid, with each `## ` starting a card and `::: hero` giving one full width card. `?? Summary` inside a card opens a `<details>` that runs to the end of it: real interactivity for no script at all, and "what is in this one" is most of the appeal at this age. One per card and always last, which is the only shape a card wants and is what let this avoid nested block parsing entirely, since the dialect has never had nesting. `!! file.png | alt text` is the card's picture. And inline `*italics*`, which Rob asked for and which simply did not exist: `*you*` was printing literally.
- **The art slots render nothing at all until a file exists.** No broken image, no reserved gap, no alt text standing in for a picture nobody drew. The page is correct today with `static/kids/` empty, which is how it ships, and correct again the moment a file lands. Served from `/pix/` rather than `/static/`, because `gallery_html()` puts everything in `static/` into the manifesto's photo gallery and blocky card art has no business among photographs of real hardware; the name check is reused exactly as it is against a different folder rather than loosened to understand a path. Traversal attempts all 404.
- Blocky rather than soft: square corners and 3px borders instead of the site's rounded hairlines, `image-rendering:pixelated` so a browser cannot smooth pixel art into mush, and one aspect ratio, 4:1, for every slot including the hero. It reads as deliberate before any artwork exists, which matters because today none does.
- **A real overflow bug, found only by measuring at 200% text.** The wordmark's fit-to-viewport `clamp()` had its floor converted to rem in 0.11.5 along with everything else. A floor must not scale: at 390px with the browser text at 200% it grew to a 437px wordmark in a 390px page and the whole site scrolled sideways, on every page, not just this one. Both clamps are floored in px again and the suite allows that one px and no other.
- The card boundary went from the site's hairline colour to `#5c5c70`, measured at 3.01:1 against the page. 1.43:1 is fine for a 1px rule inside a paragraph and is not fine as the only thing separating a card from the background.
- Measured in Chrome at 1920, 1366 and a genuine 390, and at 200% text on the last two: three columns, two, one, one; zero overflow everywhere on `/kids`, `/whofor` and the board list. Contrast on the cards: body 11.1:1, headings 11.6:1, links 11.3:1; on the hero, body 12.3:1, heading 11.5:1, link 8.7:1, frame 6.2:1.
- 8 new checks, 214 in total.

## 0.11.6, 2026-09-21

- **The arrow on the /whofor callout was a trap, and Rob found it in seconds.** "The fucking arrow should be clickable if you have a damn arrow there. LMAO I cant beieve it was just text." He is right, and the reasoning that produced it was sound and still wrong: it was a CSS `::after` so that no text could ever run under it, which solved the layout problem and shipped an affordance that looks interactive and does nothing. A pointer that is not a target costs a reader a click to learn it is decoration, and on a phone it is the first thing they tap.
- **The whole box is the link now, not the arrow.** An `<a>` around the glyph would be a 36px target against the 44px touch guidance asks for, and a third link in a box with one destination; an `<a>` around the box is not available, because the box already contains one and anchors do not nest. So the single anchor keeps its text, which Rob asked to leave alone, and a stretched `::after` on it covers the box. One anchor, one destination, one accessible name, and the entire box live. The marker is `pointer-events:none`, which is the load-bearing line: it is painted last, so without it it sits on top of the overlay and swallows the click on the one spot this change is about.
- **Checked by clicking it, not by reading the stylesheet.** `elementFromPoint` at the marker's computed centre resolves to the `/kids` anchor at 1920, 1366 and a genuine 390, as do both glyph edges, both top corners, the box centre and the empty padding; the box is live at 2159 of 2160 sampled points. Then a real `MouseEvent` dispatched at that pixel put a `GET /kids` in the server log, where merely loading the page put none.
- Hover lights the whole box, and the keyboard gets a focus ring around the box rather than around six words of it. The ring goes on the stretched overlay, which already is the box, so it needs no `:has()` and works wherever `::after` does. A box that is clickable by mouse only is the same bug in a different costume.
- **The cost, stated rather than hidden:** an overlay across the text makes the paragraph awkward to select by dragging, and there is no way around that without script. Three lines of invitation that exist to be clicked are the right place to accept it; a page of commands would not be.
- **Warm palette, and deliberately no red.** Rob: "the colors need to be something brighter, yellow, orange, reds". It was in `--dial`, the site's structural cyan, and in it the box read as furniture. It is gold on a warm near-black in a bright orange frame now. Red is left out on purpose: red is the visual grammar of an error box, and this one points a twelve year old at a page written for them, which is the same argument that kept the warning triangle off it. It shares the warm range with `.warn` and is told apart by everything else, because `.warn` is a narrow indented note marked on one edge and this is the full column in a bright frame with a marker in it.
- Contrast measured against the box background rather than judged by eye: lead 11.4:1, body 12.2:1, link and marker 8.7:1, frame 6.1:1. AA asks 4.5:1 for text and 3:1 for a boundary.
- 4 new checks, 206 in total.

## 0.11.5, 2026-09-21

- **The whole site is drawn a third larger, and all of it scales, not only the type.** Rob's words: "seriously everything on directory looks great 33% bigger", arrived at by setting his browser to 133% and looking at the board list. How he got there is the important part, because raising the type by a third is a different change and a worse one: the words grow, the 1080px column does not, and about a quarter of the characters per line disappear. Browser zoom moves the column too, which is why 133% reads as bigger rather than as cramped.
  So the stylesheet is in `rem` off a single `:root { font-size:133% }`, and nothing that carries layout is left in px: the column is `67.5rem` and not 1080px, the gutter is `1rem` and not 16px, and the wordmark's clamp, the sparkline, the day chart's cap, the nav padding and every margin followed. What stays in px is borders and rules, because a hairline is a hairline at any size, and the text inside the SVG charts, which is in viewBox units and already scales with the chart.
  **Verified by rendering, not by reading the stylesheet.** The old page at a 1444px viewport times 1.33, which is exactly what 133% zoom on a 1920 monitor produces, against the new page at 1920 and 100%: body type 18.62px against 18.62px, content column 1436.4px against 1436.4px, wordmark 19.95px against 19.95px, characters per line 140 against 140. At 1366 the column is 1323.5px and 129 characters both ways. That equality is the requirement, stated as a test.
- **A phone gets 115%, not 133%, and the difference is deliberate.** A monitor has width to spend on larger type and a 390px screen does not: at 133% the measure falls to 31 characters a line against 42 today. 115% is 14px to 16.1px, measured at 39 characters on the board list. Two numbers, one per breakpoint, both easy to move.
- **One breakpoint instead of two.** 620 and 900 were two guesses at the same question, is there room here for a wide layout, and with the type a third larger they answer it at the same width. The float, the callout indents, the wrapping of long commands, the table's label column and the board list all switch together at 900 now, so there is no band where the page is half one layout and half the other.
- **The board list is three columns, not six.** Rob: "adjust what you need to keep it from wrapping the long line or break it into 2 lines so it looks right. Such as the Sysop could go under the Name." Six columns each needed a width in characters and the sum stopped fitting once the type grew, and four of them held one short value each. The columns are now what a reader actually asks, in order: which board, how do I reach it, what is it doing. The sysop stacks under the board name, the 24 hour figures and the uptime stack under the state, and the address is alone in the middle because it is the one thing here that is copied rather than read.
- **Every stacked line says what it is.** A column heading is what used to tell a reader that "Rob" was a sysop and "3d" was an uptime. Stacking them without that would leave three lines in a cell that only read correctly to somebody who remembered the old table, so the labels moved into the row in `--faint` with the values keeping their own colours. That is the same treatment the phone layout already used, for exactly this reason.
- **State is still scannable straight down the page**, which is the one thing a table is for and the one thing the restructure had to keep. It is the first line of its cell, cells are top aligned, and it is the only line in that cell set at full size, with the 24 hour figures and the uptime smaller and quieter under it. Measured in Chrome at 1920 and 1366: all four state lines start at the same x and every one of them is a single line.
- The restructure paid for the phone layout rather than costing one. Pairing the fields deliberately at desktop width **is** the mobile layout, so the six-way cell ordering, the per-column type sizes and the generated `::before` labels are all gone. What is pinned top right on a phone is now the state *line* rather than the whole cell it sits in.
- **Fixed before it shipped, and only the render showed it:** `.status span` also matched the spans nested inside, so the freshness figure dropped off the end of the state line onto its own row and every label was separated from the value it labels, "sysop" on one line and the name on the next. Direct child selectors now. The markup greps correctly either way, which is the whole argument for measuring the rendered page.
- **The invitation for under-18s on /whofor is a box, not a footnote.** Rob: "it's honestly lost in here calling out for a kid." It was a 78ch note indented 30px with a small floppy-disk emoji, holding the one link on this site written for a twelve year old, and it read as an aside. It is now the full width of the column, framed on all four sides, with a corner radius, its lead sentence on its own line a size up in `--dial`, and a marker at the right edge.
  **The marker is `-->` and not a warning triangle.** A triangle is the glyph for "something is wrong", and this is the friendliest box on the site: it would say "be careful here" at the exact moment the design means "this way in". The arrow is the board's own idiom for the room speaking to a caller, it is ASCII so it lands identically in every monospace font on every device, and it points the way the reader is being asked to go.
  **The type stays monospace.** A different face for one element on a site whose whole identity is one face reads as a mistake rather than a choice, so the lead earns its rank on size, colour and its own line instead. It is a CSS `::after` with its space reserved by padding, so the markdown dialect needed no new shape and no text can ever run under the glyph. On a phone that reserve would be a quarter of the column, so the marker moves to the bottom right corner and the reserve becomes padding-bottom, which puts it after the link rather than beside it.
- `[!TIP]` now means that box. It is loud on purpose and it is the only callout on the site that is not a smaller, quieter version of the paragraph above it; a quiet remark that is not a warning is still `[!NOTE]`.
- 8 new checks, 202 in total. The one that matters most walks both stylesheets, strips the comments, and insists every remaining `px` is a border, an outline or SVG viewBox text. One padding added later in px is a piece of the page that silently stops scaling, and nothing else would catch it.

## 0.11.4, 2026-09-21

- **Fixed: every request was attributable to whoever asked, and the server believed them.** `caller()` read `X-Forwarded-For` and took the **leftmost** entry, from any peer at all. The leftmost entry is the end the caller writes; the rightmost is the only part our own proxy vouches for. Taking the left end is the classic way to get this wrong, and it made three separate things forgeable by anybody with `curl`:
  - `X-Seen-Address`, which a board uses as a rough dynamic DNS. A board could have made the directory hand a **different** board a wrong public address.
  - One automatic listing per address, per `/64` on v6. Claim a fresh address on each heartbeat and the cap did not exist.
  - Report dedupe and rate limiting, which count distinct reporter networks. That is the entire defence against one person delisting a board they dislike, and it was the abuse vector the moderation design was written to resist.
  Demonstrated rather than reasoned about: against the previous commit, a request carrying `X-Forwarded-For: 9.9.9.9` behind a proxy that appended the real `203.0.113.7` was attributed to **9.9.9.9**. It is attributed to `203.0.113.7` now.
- **The rule now:** a forwarded address is believed only when the connection itself comes from a trusted proxy, and then the rightmost entry that is not itself a trusted proxy wins. From anywhere else the socket address is used and the headers are not read at all. Trusted proxies are `DIRECTORY_TRUSTED_PROXIES`, defaulting to loopback because that is how Caddy reaches this, and it is in the systemd unit with the other settings rather than in the code. Bare addresses or CIDR. Empty means trust nobody, which is correct for a server facing the internet directly.
- Addresses are normalized on the way in: an entry with a port, an IPv6 literal in brackets, and the v4-mapped form, which had to become plain v4 or `group_of` would have handed one machine a `/64` and treated it as a whole network. Malformed entries stop the walk and fall back to the socket address rather than being stepped over.
- **What Rob actually saw, and the part that is not in the code.** Every address on the live directory was the same. The server has read `X-Forwarded-For` since the first commit, so the code alone does not explain it, and the collapse it produces is severe: with every board sharing one `group_key`, exactly **one** listing can ever be published and every other board queues for ever, the fifth distinct board evicts the stalest entry, and with a shared rate limit bucket any two announces inside `DIRECTORY_MIN_SECONDS` get a 429. That points at the header not arriving. So the deployment side is now explicit rather than relying on a default: `deploy/Caddyfile` and the one `deploy/setup.sh` writes both set `header_up X-Real-IP {remote_host}` and say in a comment what happens if the forwarded headers ever stop arriving.
- **It cannot fail silently again.** Startup prints the trusted proxy list, and an announce that arrives from a trusted proxy with no `X-Forwarded-For` and no `X-Real-IP` logs one warning naming the cause. Once, not once per heartbeat, and only on `/announce`, so a local health check does not trip it.
- **`selftest.py` was one buffer away from the wedge this project has already documented.** It captured the server's stdout with `subprocess.PIPE` and never read it, and the server logs one blocking `print` per request from the handler thread. Adding checks pushed the pipe past its buffer, every thread blocked inside `log_message`, and the suite timed out against a server that was alive and had simply stopped answering. The pipe is drained on a thread now and the log is kept for diagnosis.
- 21 new checks: the forged-entry cases, an untrusted peer, chained proxies, ports, IPv6 in brackets, v4-mapped addresses, `/64` grouping, and the same behaviour over HTTP. Separately, a scratch harness stood the server behind a real reverse proxy process and proved all of it end to end, including that two boards at two addresses both publish where before only one could.

## 0.11.3, 2026-09-21

- **A new page for children, `/kids`**, reached from a callout at the very top of `/whofor` and deliberately not in the menu. It explains what a BBS is in plain words, what you can do with one, what the parts cost, and why building one is a good weekend. **Measured rather than asserted:** Flesch-Kincaid on the rendered prose is **grade 5.7**, or 5.2 counting list items as sentences, with a reading ease of 79. The brief was a sixth grade level and it sits just under, which is the safe side to err on. The measurement is a test now, so a later edit cannot quietly push it to eleventh grade.
  The duties that come with writing for children are part of the page rather than a disclaimer at the bottom of it. Going on the internet is never the goal: a board on the home wifi "is finished work, it is not practice for a real one", and opening a port is stated as the adult's decision and not the child's, with a link to the page that explains what it does. The adult is a collaborator rather than a gatekeeper, and the page gives reasons instead of a rule. It says plainly that nothing typed on a board is private, that whoever runs a board can read everything on it, and that a password used anywhere else should never be used on one. Calling somebody else's board is named as a different activity that involves strangers, with a list of what never to type into any board and what to do if somebody asks for it anyway. The page asks for nothing, contains no form or input of any kind, and never says a board is safe.
- **A new page for teachers, `/teachers`**, linked from the schools section of `/whofor` and also not in the menu. Five sessions written as fifty minute periods, each with a duration and an equipment list: call a board, flash a board, wire the card, design the case, run it. A table of what it teaches against where each idea actually shows up, covering client and server, addresses and ports, text encoding, serial protocols, filesystems, owning versus renting, and version control. What a set of boards costs, using the figures already on the build and SD card pages.
  The enclosure is a session of its own rather than a footnote, because for a lot of classrooms the 3D printer is the hook: measure the board, model it in TinkerCAD, and deal with the USB slot, the LED, the card and holding two halves together without glue. "The first print usually does not fit. That is the most useful part of the session."
  It is also straight about school networks. You will not be able to forward a port, you should not try, and it costs you nothing, because every one of the five sessions works on the classroom network exactly as written.
- **`[!TIP]`, the inviting callout.** `[!NOTE]` gave the dialect a calm box in 0.11.2, and an invitation needs a third register: a link to a page somebody would enjoy does not belong in the colour the router pages use to say a port forward is your responsibility. It is `--dial`, which the palette already spends on "things you can act on", and not GitHub's green, because green here means a board is up and means nothing else.
- Neither page is in the header nav, which is already nine items and 154px tall on a phone. Both are mapped to `/whofor` in the section table, so the menu still says where the reader is, and both are the most prominent link on the page they belong to.

## 0.11.2, 2026-09-21

- **Fixed: the site stated two features the board does not have.** This is the most expensive kind of wrong there is here, because somebody spends an afternoon and twenty dollars on the strength of these sentences. The manifesto listed **doors** among what the board has; there is no DOOR verb anywhere in the firmware and the word appears only in comments. `/sdcard` said the card is what you add "when you want message bases, file areas and screens of your own" and listed Message bases in a table as fact, and `/build` repeated the claim; message bases are being designed right now and do not exist. Both are genuinely coming and both are part of the argument, so neither is deleted: they are in the future tense. The manifesto now names what is actually built, including file areas and mail between callers, which it had never mentioned.
- **`/whofor` overclaimed in four places**, all of them sentences rather than the argument:
  - "the who-broke-the-laser-cutter **thread**" implied threaded messages. The board has a live chat room and point to point mail and no threads at all. It is the argument about who broke the laser cutter now.
  - "It is **peer to peer** in the way that matters" was the wrong word, and the sentence after it gave the right one away: every board being independent with no central server is decentralized. Boards do not talk to each other, linking is queued and unbuilt, and the page says so plainly now rather than implying a network that is not there.
  - "without anything measuring what you looked at or **how long for**" contradicted `/firstcall` and `/privacy`, both of which name the caller log plainly. The log records when a call started and how long it ran, and the board enforces a daily minute limit, so duration is recorded. The line now says the only record is the board's own caller log, and the board is yours, which is both true and the better argument.
  - British idiom that appears nowhere else in `pages/`: "neighbourhood" was the only `-our` spelling on the site, and "an allotment" and "store cupboard" do not parse for a US reader. Also "flash it in the time it takes to make tea", which is hyperbole on a page that is otherwise careful with concrete claims; a clean ESP-IDF build is not that quick.
- **A reassurance no longer sits in an alarm-coloured box.** Every `> ` blockquote rendered as the amber warning box, and thirteen of the fifteen on the site are genuine warnings, so amber stays the default. The other two are reassurances, and "You never have to touch any of this" in a warning box says the opposite of the words inside it. A blockquote whose first line is `[!NOTE]`, which is GitHub's marker rather than an invention, gets a calm neutral box instead. That is the only addition to the dialect, and it is used on `/whofor` and `/dialing`.
- **The caller axis counts callers.** It read "8.0" and "4.0" for a count of people, and the scale had a top but no bottom. Whole numbers now, with a zero at the foot, and a fraction still gets its decimal place if one ever turns up.
- **Code blocks wrap on a phone instead of being dragged sideways.** Measured at 390: `/dialing` needed **692px** of horizontal dragging inside the block, `/build` 284px, `/how` 68px. All three are **0** now. `pre-wrap` inserts nothing, so copying a command still returns the exact original line, and the alternative was a command nobody could read. The ASCII diagram on the manifesto is excluded, because wrapping would destroy it: it scrolls inside its own box the way the Markdown tables do, and the page does not move. Restoring the full prose width in 0.11.1 had already fixed the same thing on a desktop, where `/dialing` needed 316px of dragging and now needs none.
- Corrected the chart figures published in 0.11.1. They were measured against a tree three commits older than the one the fix replaced, and contradicted the same paragraph's own statement that the Board cell is 369px wide. The fix is larger than claimed on a desktop and smaller on a phone: hour labels went 5.4px to 12.1px rather than 6.3px to 12.1px, and 3.6px to 12.3px rather than 2.2px to 12.3px.
- **The callsign is out of the working tree but it is still in git history**, in the commits that introduced it and the one that removed it. This repository is public, so anybody reading the log will find it. Rewriting history would break every existing clone and is not something to do on a guess; if it has to go from the history as well, that is a deliberate decision with a cost attached.

## 0.11.1, 2026-09-21

- **Reverted: prose is full width again on a desktop.** 0.11.0 capped it at 78ch on typographic grounds. Rob compared the two and reversed it, and the wide setting is the house style on every page. Measured at 1366 and 1920, every prose page is back to **1080px, 140 characters**, exactly what it was before 0.11.0: what this is, who it's for, first call, build one, go public, get listed, data, terminals, dialing, SD card, privacy, house rules and all five router pages. The `article pre` cap went with it, so code blocks are full width too. A phone was never affected and is unchanged at 358px. **The board list's card layout below 900px stays**, because it is a different problem with a different fix: wide on a monitor, cards on a phone, and the two were never in conflict. The `.warn` box is back at its original 78ch measure as well, keeping only the 30px indent that 0.11.0 was actually there to add.
- **Fixed: the animated diagram on the manifesto had a scrollbar.** 0.11.0 put `overflow-x:auto` on `.scene` to stop the art pushing the page sideways. It did stop that, and it produced a scrollbar on the diagram: a **vertical** one, on a fix aimed at horizontal overflow. When one axis is not `visible`, CSS computes the other to `auto` as well, and five printed lines at 1.5 line height are 105px against a 7.4em box, so the diagram overflowed its own height by one pixel at every width. It scales instead of scrolling now, the same `clamp()` trick the wordmark already uses, because art with a fixed character count can simply be made to fit. Measured: `overflow` is `hidden` on both axes with **zero scrollable overflow at 390, 1366 and 1920**, no page-level horizontal scroll anywhere, and at 390 the whole diagram is visible at 9.35px type rather than being clipped or dragged sideways.
- **Fixed: the expanded activity chart was unreadable.** Rob: "I cant read any times." The chart lives in the Board cell, which is 369px wide, and the SVG carried a 720 unit viewBox, so everything in it was scaled by 0.49 and an 11px hour label **rendered at 5.4px** in a chart 95px tall. On a phone the cell padding squeezed it further and the labels rendered at **3.6px**. The viewBox is 380x300 now, sized to the column it actually sits in, so the scale is near 1:1 and a size set in the drawing code is very nearly a size in pixels. Measured against the commit this replaced:

  | | before | after |
  |---|---|---|
  | desktop | 355 x 95px, labels 5.4px | **355 x 281px, labels 12.1px** |
  | phone (390) | 237 x 64px, labels 3.6px | **360 x 285px, labels 12.3px** |

  A faint upright at every labelled hour lets a bar be traced down to a time, the caller axis counts in whole callers rather than "8.0", and it has a zero line as well as a top. On a phone the chart also takes back the 16ch of cell padding that reserves room for the state badge, which is one line at the top of the card and nowhere near it; that alone was costing a third of the width.
- **A new page: Who it's for**, in the menu next to the manifesto. The answer is everyone, and it says so, then covers who is already well served by it: schools and STEM teaching, where a board is the internet with the lid off and is community driven rather than engagement driven; clubs and groups, with ham radio first and a long list after it; offices and teams, where it runs on anything with a terminal and the discussion stays in the building; and one person with a file area, a chat room and a board of their own. Then the part that is the actual argument: on your own board you answer to nobody, there is no provider whose terms you are operating under, nobody can deplatform you, every board is independent of every other, and it works on a local network with no internet at all. It is a page rather than a section of the manifesto because its job is to talk somebody into setting a board up, and that wants a link you can paste at a club or a school, not an anchor two thirds of the way down a long argument. Linked from the manifesto in two places.
- Rob's callsign is off the site. The `/how` and `PROTOCOL.md` examples use a plain illustrative handle instead.

## 0.11.0, 2026-09-21

- **Fixed: every numbered step on the router pages was one run-on paragraph.** `md_render` knew `- ` bullets and nothing else, so a line beginning `1. ` fell through to the paragraph branch and consecutive paragraph lines were joined with a space. That is **53 numbered steps across four router pages**, every one of them a wall of text, on the pages somebody reads one step at a time with a router admin page open in the other window. Nothing caught it because the text was all present and in the right order, which is what a grep checks. The dialect has ordered lists now: `/forward-mesh` renders 33 `<li>` across two `<ol>` where it used to render two paragraphs.
- **Fixed: the board list did not fit a phone, and the part that was cut off was the product.** Six columns have a minimum content width of 627px and a phone gives them 358, so the page scrolled sideways by 257px: State, Activity and Up-for were off the screen, which means the one question a directory exists to answer, is this board up and is anybody on it, was the part a visitor could not see. Below 900px the table is a list of boards now, one column per row, with the state pinned top right. Measured in headless Chrome at a true 390: `scrollWidth` 647 against a `clientWidth` of 390 with 53 overflowing elements, now 390 against 390 with none, and eight boards visible in one scroll instead of one truncated one.
- **The desktop table has a column budget.** `table-layout` was left at `auto`, so every column was negotiated from whatever text the listed boards happened to carry. State got 10 characters to hold a 14 character figure, so `quiet, 7` ended up on one line and `h ago` on the next, and a figure split across a line break is not a figure, it is two numbers. Five columns are fixed at their known shape and Board absorbs the rest: State is 81.8px and now 146.8, Up-for 51.5 and now 77.6, and the `Up for` header no longer wraps onto two lines. Activity is two deliberate lines rather than one that wraps wherever it lands.
- **Fixed: the callout boxes were not indented from the body text.** `margin:14px 0` is a shorthand, so it set `margin-left` to 0 explicitly and every warning's left border landed flush with every paragraph on the page, reading as a paragraph that had shifted slightly rather than as a box. They sit at 30px now, the indent `.freedom` already used, with the measure dropped to 70ch so the box still ends before the body text does, and flush again below 620px where 30px out of a 343px column is a real bite. The 0.8.0 fix for this aimed at `article .pull`, which is a different element; `article .warn` had never been touched since it was written.
- **Prose has a reading measure again.** Every paragraph on the site ran to 140 characters, because one page has a floated photograph and the whole site was given full width to suit it. Measured: the float is 367px in a 1080px column and a 78ch paragraph is 600px, so 600 + 367 + 30px of margin still fits and the float keeps its text beside it. `main p` rather than `article p`, because the lead and the byline on the manifesto sit outside the article element and an article-scoped rule misses the two paragraphs at the top of the page it matters most on. Code is 92ch, slightly wider than prose, which is the right relationship.
- **The page title outranks the text under it.** `h1` was 13px against a 15px `article h2`, so a section heading four screens down outranked the page's own name, and on the board list the live figures were the smallest and faintest thing above the fold. `h1` is 20px, `article h3` drops to `--dim` so it stops being level with it.
- **Contrast.** The footer was `#555` at 2.6:1 and every small annotation was `--faint` at 3.7:1 and 11px, both failing AA on a dark background, and one of the things set that way was how old a reading is, which the footer spends four lines insisting matters. Nothing that is words goes below `--dim` now, which passes at 5.7:1, and the 11px sizes are 12px. `--faint` is kept for rules, hairlines and the phone layout's field labels, where it is structure rather than text.
- **Tap targets.** The menu was 26px, the footer links 21px, and the dial link, which is the primary action of the whole site, 21px with no padding at all. They are 40, 36 and 36 now. A footer link is one object: at 390 the text used to break mid-link, so `House rules` rendered as `House` on one line and `rules` on the next, which looks like a rendering fault whether or not it is one.
- **Fixed: the manifesto's animated diagram pushed the whole page sideways on a phone.** `.scene pre` is absolutely positioned and unsets the global `pre` rule's background and border but not its `overflow-x`, and an absolutely positioned box with no width shrink-wraps to its content: 61 characters, so 470px, in a 358px column. The about page scrolled sideways by 96px, header and footer included. `.scene` is already `position:relative`, so one `overflow-x:auto` on it contains the diagram and the page stops moving. Measured: 486 against 390, now 390 against 390.
- `width:100%` moved off the bare `table` selector and onto `main > table`. It is right for the board list, which is the product, and wrong for a two column table inside an article: the data page's "Right now" table was 1080px wide to hold the word `offline` and the digit `2`, putting 571px between a label and its value. It is 162px now. Markdown tables size to their content too, and every one of them fits a 390px phone without scrolling inside its wrapper, which the machine table on `/terminals` did not manage before.
- The sparkline on the board list says it is a control before you have clicked it, rather than only admitting it afterwards, and its `summary` has a focus ring.
- `.gallery img` declares an aspect ratio, so the box is reserved before a lazily loaded photograph arrives and the paragraphs beside it stop jumping.
- **Fixed: a deployment with one domain lost the manifesto and the data page, and three places said it did not.** There were no path routes at all. With only `DIRECTORY_LIST_DOMAIN` set, `/about` and `/data` returned 404, two of the seven menu items were loops back to the page you were already on, and the manifesto, which is the single best argument the project has, could not be read. `server.py`'s own comment, `README.md` and `INSTALL.md` all promised otherwise, so anybody following the install guide to run their own directory got that while believing the docs. `/about` and `/data` are real routes now and the Host header only chooses the default. Verified end to end against a server with one domain configured: all three faces answer and each lights its own menu item.
- **Fixed: `deploy/Caddyfile` would have taken two of the three faces off the air.** It gave `.com` a `reverse_proxy` block and redirected `.net` and `.org` at it, so the app would never see either Host header and `role_for()` would answer `list` for everything. `deploy/setup.sh` does not use that file: it writes `/etc/caddy/Caddyfile` from a heredoc that proxies every domain. The two disagreed and the one in the repository was the wrong one, which is worse than no file because it reads as authoritative. It now matches what `setup.sh` generates and says at the top that it is a reference copy.
- **`/how` and `/rules` were styled differently from every other prose page.** `md_page()` wraps its output in an `<article>` and these two constants did not, so `/how`'s one `<h2>` got the browser default, large and bold, instead of the site's small cyan heading, and neither picked up the article margins or line height. Two pages in the menu and the footer looked like they came from a different site.
- **Fixed: the curl example on `/how` was losing its line continuations.** `HOW` was an ordinary triple quoted string, so a backslash at the end of a line was a Python line continuation and was eaten along with the newline: the page served one long line that scrolled sideways on a phone, with the lines after it still indented as though the continuations were there. The string is raw now.
- **Two pages lit the wrong menu item and six lit nothing.** `nav_html` treated an empty `here` as the index, so any page that forgot to declare itself claimed to be the board list: a reader on "Get listed" was told they were on "Boards", with the menu blinking three times on load to draw the eye to it. The fallback is gone, the routes pass `here`, and the seven pages that are not in the menu light the section they belong to. An unmarked menu is honest; a wrongly marked one is not.
- **Seven of twelve pages shared one browser tab title.** Every Markdown page already carried its title in its first `# ` line and threw it away, so four router pages open in four tabs were four identical unreadable tabs. Page name first and site name second, because a tab strip truncates from the right.
- **The manifesto had no `<h1>`.** It is the page the whole argument lives on and it started at `h2`: no document outline, no heading for a screen reader to land on, and nothing on screen saying what the page was called.
- **The site had no description, no preview card and no icon.** A directory spreads by somebody pasting the link into a forum or a chat, and that paste produced a bare link. Every page carries a description and Open Graph tags now, the board list's generated from the live figures, and the icon is the micro sign traced out of the wordmark as three rectangles of SVG. It is served from `/favicon.svg` rather than `static/`, because `gallery_html()` shows every image in `static/` and a favicon does not belong in the manifesto's photo gallery.
- **The manifesto said the board answers six callers.** It is ten, plus a hidden eleventh line the sysop comes in on, and has been since 0.17.0. "Fits in a megabyte" is "about a megabyte": the image is 68.4% of a 1.5 MB slot. `pages/build.md` said six too.
- **"A guest does not even need that" was wrong.** A guest types a handle like everybody else and keeps it for the call; what they skip is the password and the account. Fifteen minutes, nothing saved.
- **A new page, First call**, and a menu entry for it between Terminals and Build one. The site covered finding a board, installing a terminal, building a board and listing a board, and said nothing at all about the thirty seconds after a stranger connects to one: they get a handle prompt with no idea whether to register, whether it costs anything, or what a guest is. It covers terminal detection, the register/guest/other-handle choice, what the first commands are, and what a board actually knows about a caller.
- **A new page, The real risks of open communications**, and "Honest about the limits" on the manifesto rewritten to lead into it. The old paragraph named the limitation and left the reader to imagine the risk, which they do badly in both directions. The framing now: open communication over the internet is radio; somebody has to be trying; the real risk is low and not zero and the comparison that helps is a bar rather than a website that records everything by design; so say what you would say in public and use a password you use nowhere else. Linked from the manifesto, from the terminal page's telnet warning and from First call.
- **`/dialing` was nearly unreachable**, which matters because it fixes the exact problem a first-time visitor hits: they click an address and nothing happens. It was linked from one sentence at the bottom of `/terminals` and from a `title=` attribute on every dial link that read "See /dialing if nothing happens" as bare text, and a `title` is invisible on every touch device and clickable nowhere. It is in the footer now, and named in the index lead as "Nothing happened?".
- The dialing page said "Every address on this site is plain selectable text next to the link". The address **is** the link text: there is no separate plain copy beside it, and drag-selecting over an anchor starts a drag in most browsers. Both that page and the weaker version of the claim on `/terminals` now say what is actually true.
- Currency and idiom: the site is written from Illinois and prices things in dollars, so a bridge costs "a few dollars" rather than "a few pounds", and a board costs "less than lunch" rather than "less than a takeaway", which is British for takeout.
- The index footer note was five clauses and sixty words in one block, under a table that had just used six column headings, and it is the only place that says what "Activity" and "Up for" mean. Three lines, one idea each.
- An IPv6 literal in a `telnet://` link is bracketed. No listed board hits this today, and `pages/dialing.md` already brackets correctly in the PowerShell handler it documents, so the site was explaining a URL shape it did not emit.
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
