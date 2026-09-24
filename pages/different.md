<!-- What makes it different (site 1.2.4, Rob: "See what Unleashed can do that other BBS systems cant"). Every line links to the page that shows it. The comparison was checked on 2026-09-24 against each program's own pages (Synchronet's platforms from Wikipedia, which the wiki does not list in one place), linked in "How it compares": Synchronet's wiki says PETSCII "cannot be automatically detected during connection" and uses ports of its own (howto:petscii); Mystic's downloads are Windows, Linux (x86 and ARM, Raspberry Pi) and macOS; WWIV is Win32 and Linux; ENiGMA½ is Node.js on Linux, the BSDs, macOS and Windows; Talisman is Linux and Windows; Citadel needs "a modern unix operating system such as Linux or FreeBSD". No "only" is claimed, because espbbs (github.com/snazzware/espbbs) already runs a telnet BBS on an ESP8266, and the page says so. The power figure is /hardware's: about a tenth of an amp while the dev board waits, at 5 V from USB, 0.5 W, 4.38 kWh a year. Items marked 1.1.0 are the lights on the dev board (1.1.0-dev.4), nightly backups (dev.6) and the BOOT reset (dev.3); the camera is coming soon. The two lists swap on the day a 1.1.0 release is on disk. The URL is /different: one plain word, which says what the page is about and reads the same said aloud. -->
# What makes it different

A whole BBS on a board about the size of a stick of gum. It answers a
Commodore 64 and a laptop in the same chat room, runs all year on a phone
charger, and goes from the box to its first caller in about five minutes. Here
is what that adds up to.

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
- **[Hardware you can watch.](/lights)** A drive light that flickers as the
  board works and a strip of pixels that lights up as callers arrive, on the
  ESP32 dev board from firmware 1.1.0, and a status screen on the S3.
- **[A camera callers can use.](/camera)** Coming soon: type `SNAPSHOT` from
  any terminal and download the picture a few seconds later.
- **[It looks after itself.](/sdcard)** From firmware 1.1.0, a backup to the SD
  card every night, and a forgotten sysop password put right by holding the
  BOOT button, with no reflash.
- **[It puts itself on the map.](/how)** Switch on the listing and the board
  appears on this directory by itself. There is no form to fill in.
- **[About half a watt.](/hardware#esp32-dev-board)** A tenth of an amp from a
  phone charger while it waits, so a year of answering calls is about 4.4 kWh.
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
- **[Hardware you can watch.](/lights)** A drive light that flickers as the
  board works, a strip of pixels that lights up as callers arrive, and a
  status screen on the S3.
- **[A camera callers can use.](/camera)** On the camera boards, type
  `SNAPSHOT` from any terminal and download the picture a few seconds later.
- **[It looks after itself.](/install#if-something-goes-wrong-reset-rather-than-reflash)**
  A backup to the SD card every night, and a forgotten sysop password put
  right by holding the BOOT button, with no reflash.
- **[It puts itself on the map.](/how)** Switch on the listing and the board
  appears on this directory by itself. There is no form to fill in.
- **[About half a watt.](/hardware#esp32-dev-board)** A tenth of an amp from a
  phone charger while it waits, so a year of answering calls is about 4.4 kWh.
:::

It is the same idea as the Commodore 64 boards of the 1980s, where the
computer on the desk was the BBS. This time the computer is a chip, Wi-Fi is
the phone line, and you can build one this weekend.

::: next
[Build one](/build)
:::

## How it compares

The BBS programs you are most likely to have met are good software with years
of work in them, and each one runs on a computer with an operating system
under it:

- [Synchronet](https://en.wikipedia.org/wiki/Synchronet) on Windows, Linux and
  the BSDs;
- [Mystic](https://www.mysticbbs.com/downloads.html) on Windows, Linux,
  including a Raspberry Pi, and macOS;
- [WWIV](https://www.wwivbbs.org/) on Windows and Linux;
- [ENiGMA½](https://github.com/NuSkooler/enigma-bbs) on Node.js, under Linux,
  the BSDs, macOS or Windows;
- [Talisman](https://talismanbbs.org/) on Linux and Windows;
- [Citadel](https://www.citadel.org/system_administration_manual.html) on "a
  modern unix operating system such as Linux or FreeBSD".

µnleashed is firmware. There is no operating system to install first, because
the $5 board is the whole computer.

Terminals are the other difference worth a line. Synchronet's own
documentation says [PETSCII cannot be detected when a caller
connects](https://wiki.synchro.net/howto:petscii), so it gives Commodore
callers ports of their own. A µnleashed board takes everybody on one port, and
a terminal that stays silent is asked to press one key.

It is not the only BBS on a microcontroller:
[espbbs](https://github.com/snazzware/espbbs) runs one on an ESP8266, with
room for four callers. What this one adds is the rest of the list above.
