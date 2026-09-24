<!-- The tested boards page (site 1.2.0). Each "::: board" block is drawn from BOARDS in server.py and from the firmware on disk, so the picture, the build on offer and the buy link here are always the ones the installer's picker shows. The prose under each block is what was tested and what the board adds; the facts in it come from the firmware repository: ESP32_BOARD_CHOICE.md, README.md "Other boards", src/board.h and src/plugins/panel.cpp at 1.1.0-dev, and Rob's bench on 2026-09-24. A board goes on this page only once a build has run on it. -->
# Tested boards

The boards this firmware has actually run on, each with its own image on [the
installer](/install). Pick yours by the picture: the installer checks the chip,
and a picture is the only way to tell two boards with the same chip apart.

Each one's buy link goes to the listing for the board that was tested. Any
board that matches the picture and the chip will do.

The buy links are Amazon affiliate links: a purchase through one may earn
the project a small commission, at no extra cost to you. Buying the same
board anywhere else works just as well.

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
- **What it has:** ten caller lines, a busy line and a hidden sysop line. An
  SD card is a two dollar module and six wires: [the wiring](/sdcard). A drive
  light is a WS2812B pixel of your own on a free pin.

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
- **A card slot on the board.** A TF (micro SD) card goes straight in: no
  module and no wiring.
- **More memory:** 16 MB of flash and 8 MB of PSRAM, against the dev board's
  4 MB of flash and none.

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

## Other boards

[Which ESP32](/build#which-esp32), on the build page, says which chips can run
a board and why. A board goes on this page once a build has actually run on
it.
