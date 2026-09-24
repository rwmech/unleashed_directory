<!-- The tested boards page (site 1.2.0). Each "::: board" block is drawn from BOARDS in server.py and from the firmware on disk, so the picture, the build on offer and the buy link here are always the ones the installer's picker shows. The prose under each block is what was tested and what the board adds; the facts in it come from the firmware repository: ESP32_BOARD_CHOICE.md, README.md "Other boards", src/board.h and src/plugins/panel.cpp at 1.1.0-dev, and Rob's bench on 2026-09-24. A board goes on this page only once a build has run on it. Since site 1.2.1 this page also owns the facts /build used to carry: the chip list, the dev board's memory and power (ESP32-WROOM-32E datasheet v2.1, table 16: 379 mA peak on 802.11b transmit, a 0.5 A supply), and the spectrum at the top. The spectrum's prices are about, from listings on 2026-09-24: a single WROOM dev board $9.97 (store.rokland.com), the Waveshare $12.99 on waveshare.com and a little more elsewhere, an SD module about $2 in a five pack. Re-check them when they look wrong. -->
# Tested boards

The boards this firmware has actually run on, each with its own image on [the
installer](/install). Pick yours by the picture: the installer checks the chip,
and a picture is the only way to tell two boards with the same chip apart.

::: art
hardware-spectrum
:::

Three ways to build one. Each is a choice, not a step on a ladder:

- **[A bare ESP32 dev board](#esp32-dev-board)**: functional, and the lowest
  cost. About $10, and about five minutes from the browser. Chat, mail,
  accounts and a directory listing; file areas and forums need a card.
- **[The same board with an SD card](/sdcard)**: economical and usable. About
  $15 with the card module and jumper wires, and about half an hour, most of
  it wiring the card.
- **[The Waveshare S3](#waveshare-esp32-s3-lcd-1-47)**: the most expandable.
  About $15, a screen, a card slot and a drive light on the board, and no
  wiring. It does need BOOT and RESET pressed by hand to install, which is
  why it takes a little longer than the bare board.

The prices are typical listings in September 2026, and they move. A micro SD
card is extra on either board that takes one. The times are for somebody
doing it the first time.

The buy links below are Amazon affiliate links: a purchase through one may
earn the project a small commission, at no extra cost to you. Each goes to the
listing for the board that was tested, and any board that matches the picture
and the chip will do, bought anywhere.

## ESP32 dev board

::: board
esp32
:::

The reference board, and the one every release so far was built and tested
on. A dev board round the ESP32-WROOM-32E module, with 4 MB of flash and a
USB-serial chip beside its socket: most boards sold as "ESP32 DevKit" or
"ESP32-WROOM-32" look like this. A long board, a row of pins down each side,
the module's metal can at one end with its antenna past the edge, and the USB
socket at the other end between two buttons.

- **What was tested:** installing from this site, setting the Wi-Fi from the
  browser, the first-call setup, and callers from PuTTY, SyncTERM and a
  Commodore 64 through a TeensyROM, with an SD card on a module of its own.
- **What it has:** ten caller lines, a busy line and a hidden sysop line.
  520 KB of SRAM and 4 MB of flash, no PSRAM, and Bluetooth switched off.
- **Power:** the USB port you installed it from, a phone charger, or 3V3 on a
  bench supply. It draws about a tenth of an amp while it waits, because the
  firmware keeps the radio listening rather than letting it doze, and a little
  under 400 mA for the instant the radio transmits, so anything that can
  deliver 500 mA is comfortable.
- **What you can add:** an SD card, a two dollar module and four signal wires
  plus power ([Adding an SD card](/sdcard)), and a drive light and a strip of
  pixels for a case ([Lights](/lights)).

## Waveshare ESP32-S3-LCD-1.47

::: board
esp32s3
:::

A USB stick with an ESP32-S3 on it and a small colour screen, the second board
the firmware runs on. Tested on Rob's bench on 24 September 2026 with a 1.1.0
preview: it boots, answers telnet, mounts its SD card, shows the board's
figures on its screen, and runs the drive light on its own LED.

What it adds over the ESP32 dev board:

- **A screen that shows the board's figures.** Its name and the time, callers
  on out of how many lines, the address to dial, how long it has been up, the
  card's free space, and the last login, logoff or page.
- **A drive light already fitted.** The RGB LED on the board is the drive
  light, on from the first start.
- **A card slot on the board.** A TF (micro SD) card goes straight in.
- **More memory:** 16 MB of flash and 8 MB of PSRAM, against the dev board's
  4 MB of flash and none.

No wiring, and none of the build pages: [Adding an SD card](/sdcard) and
[Lights](/lights) are for the dev board. The card goes in the slot, the drive
light is already there, and the screen draws the strip's lamps whether or not
a strip is wired.

It still has ten caller lines, the same as the dev board. The limit is the
network stack's sixteen sockets, and that does not move with the chip.

It carries two version numbers, the core every board shares and its own, and
shows them together, for example `1.1.0 (S3 1.0.0)`. The core number is what
the directory compares when it marks a board as behind.

> **Only this board.** The ESP32-S3-LCD-1.47**B**, with a USB-C socket, moves
> a pin and is not this build, and neither is any other ESP32-S3 board. The
> installer reads the chip, not the board, so it would write this image onto
> any S3: the picture is the check.

It has no USB-serial chip, so it goes on a little differently: [On the
Waveshare S3](/install#on-the-waveshare-s3), on the installer page.

## Other chips

Plenty of chips are sold under the ESP32 name, and not all of them can run a
board. It needs two processor cores and Wi-Fi built into the chip. The BBS
runs on one core while Wi-Fi and the network run on the other, and that split
is what stops the radio's work from making callers' lines lag.

- **ESP32-WROOM-32E: yes, tested.** The dev board above. Every release is
  tested on it.
- **ESP32-S3: yes, on one board.** The Waveshare above. Another S3 board needs
  a build of its own, because the image carries the Waveshare's pins.
- **ESP32-WROVER: should work, not yet tested.** The same original ESP32
  chip, as are other modules built on it, so the dev board's image should run.
  A WROVER adds PSRAM, a second memory chip on the module, which that image
  does not use.
- **ESP32-S2, ESP32-C3 and ESP32-C5: no.** One core each, the C5 even with
  its dual-band Wi-Fi.
- **ESP32-C6: no.** One main core. Its second, low-power core cannot run the
  board.
- **ESP32-H2: no.** One core, and no Wi-Fi.
- **ESP32-P4: no.** No Wi-Fi on the chip. It needs a second chip to reach a
  network.

A single-core chip could be made to run it, but the radio and the callers
would take turns on one core and callers would feel it, and doing that
properly means rebuilding the core of the BBS rather than changing a setting.
A board goes on this page once a build has actually run on it.
