<!-- What makes it different (site 1.2.4, Rob: "See what Unleashed can do that other BBS systems cant"). Every line links to the page that shows it. No "only" is claimed, because espbbs (github.com/snazzware/espbbs) already runs a telnet BBS on an ESP8266, and the table says so. The power figure is /hardware's: about a tenth of an amp while the dev board waits, at 5 V from USB, 0.5 W, 4.38 kWh a year. Items marked 1.1.0 are the lights on the dev board (1.1.0-dev.4), nightly backups (dev.6) and the BOOT reset (dev.3); the camera is coming soon. The two lists swap on the day a 1.1.0 release is on disk. The URL is /different: one plain word, which says what the page is about and reads the same said aloud. Site 1.2.9 (Rob): the machines named are a varied set from the firmware's CLIENTS.md rather than one favourite; the drive light is optional; the S3's screen is from the firmware's CHANGELOG 1.1.0-dev.10 (name, address and uptime taking turns every 3 s at the top, glyphs only while true for the card, a ringing bell, sysop mail, an upload awaiting approval, the backup window, the listing and more, the Wi-Fi antenna, callers one row each); the card's 32 GB is /sdcard's FAT32 limit; linked chat is on /roadmap under Later and not built; and "How it compares" is the COMPARE table in server.py, whose sources are listed beside it there. -->
# What makes it different

A whole BBS on a board about the size of a stick of gum. It answers an 8-bit
computer from the eighties and a laptop from this year in the same chat room,
runs all year on a phone charger, and goes from the box to its first caller in
about five minutes. Here is what that adds up to.

::: until 1.1.0
- **[No computer under it.](/hardware)** The board is the whole BBS: no PC, no
  operating system to keep patched, no Raspberry Pi. The dev board costs about
  $5.
- **[Installed from your browser.](/install)** Plug the board in, press a
  button, and set its Wi-Fi on the same page. No toolchain, and about five
  minutes.
- **[One port for every terminal.](/firstcall)** It works out as you connect
  whether you are on ANSI, UTF-8, PETSCII at 40 or 80 columns or plain ASCII,
  and draws its screens for that.
- **[A library on a card.](/hardware#esp32-dev-board-base-sd-card-for-storage)**
  A micro SD card of up to 32 GB holds a lifetime of disk images, text files
  and utilities for the machines that call in, every one a download by XMODEM
  or YMODEM.
- **[Hardware you can watch.](/lights)** An optional drive light that flickers
  as the board works and a strip of pixels that lights up as callers arrive,
  on the ESP32 dev board from firmware 1.1.0.
- **[A screen of its own, one step up.](/hardware#waveshare-esp32-s3-lcd-1-47)**
  The Waveshare S3, about $20, shows who is on, one row a caller, with the
  board's name, address and uptime taking turns at the top, a Wi-Fi antenna
  that fills with the signal, and small icons that appear for waiting mail, a
  caller ringing for the sysop and an upload to approve.
- **[A camera callers can use.](/camera)** Coming soon: type `SNAPSHOT` from
  any terminal and download the picture a few seconds later.
- **[It looks after itself.](/sdcard)** From firmware 1.1.0, a backup to the SD
  card every night, and a forgotten sysop password put right by holding the
  BOOT button, with no reflash.
- **[It puts itself on the map.](/how)** Switch on the listing and the board
  appears on this directory by itself. There is no form to fill in.
- **[About half a watt.](/hardware#esp32-dev-board-base)** A tenth of an amp from a
  phone charger while it waits, so a year of answering calls is about 4.4 kWh.
- **[Coming: one chat across many boards.](/roadmap)** Chat rooms linked
  between boards, so a quiet board borrows company from a busy one: other
  µnleashed boards, and Diversi-DIAL and GTalk-style systems, in one
  superchat. It is on the roadmap, not built yet.
:::
::: from 1.1.0
- **[No computer under it.](/hardware)** The board is the whole BBS: no PC, no
  operating system to keep patched, no Raspberry Pi. The dev board costs about
  $5.
- **[Installed from your browser.](/install)** Plug the board in, press a
  button, and set its Wi-Fi on the same page. No toolchain, and about five
  minutes.
- **[One port for every terminal.](/firstcall)** It works out as you connect
  whether you are on ANSI, UTF-8, PETSCII at 40 or 80 columns or plain ASCII,
  and draws its screens for that.
- **[A library on a card.](/hardware#esp32-dev-board-base-sd-card-for-storage)**
  A micro SD card of up to 32 GB holds a lifetime of disk images, text files
  and utilities for the machines that call in, every one a download by XMODEM
  or YMODEM.
- **[Hardware you can watch.](/lights)** An optional drive light that flickers
  as the board works and a strip of pixels that lights up as callers arrive.
- **[A screen of its own, one step up.](/hardware#waveshare-esp32-s3-lcd-1-47)**
  The Waveshare S3, about $20, shows who is on, one row a caller, with the
  board's name, address and uptime taking turns at the top, a Wi-Fi antenna
  that fills with the signal, and small icons that appear for waiting mail, a
  caller ringing for the sysop and an upload to approve.
- **[A camera callers can use.](/camera)** On the Freenove camera board, type
  `SNAPSHOT` from any terminal and download the picture a few seconds later.
- **[It looks after itself.](/install#if-something-goes-wrong-reset-rather-than-reflash)**
  A backup to the SD card every night, and a forgotten sysop password put
  right by holding the BOOT button, with no reflash.
- **[It puts itself on the map.](/how)** Switch on the listing and the board
  appears on this directory by itself. There is no form to fill in.
- **[About half a watt.](/hardware#esp32-dev-board-base)** A tenth of an amp from a
  phone charger while it waits, so a year of answering calls is about 4.4 kWh.
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

## How it compares

The BBS programs you are most likely to have met are good software with years
of work in them, and each one runs on a computer with an operating system
under it. µnleashed is firmware: the $5 board is the whole computer. Each
project's name links to its own pages, which is where its column was checked,
in September 2026.

::: compare
:::
