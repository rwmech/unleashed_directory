<!-- The tested boards page (site 1.2.0). Each "::: board" block is drawn from BOARDS in server.py and from the firmware on disk, so the picture, the build on offer and the buy link here are always the ones the installer's picker shows. The prose under each block is what was tested and what the board adds; the facts in it come from the firmware repository: ESP32_BOARD_CHOICE.md, README.md "Other boards", src/board.h and src/plugins/panel.cpp at 1.1.0-dev, and Rob's bench on 2026-09-24. A board is listed as tested only once a build has run on it. Since site 1.2.4 the two camera boards wait at the foot of the page, drawn from SOON_BOARDS in server.py with no version (the buy links are Rob's, given for 1.2.5); their facts come from the firmware repository's internal/PLAN-freenove-cam.md: the Freenove FNK0060 (pinout 3.0, ESP32-WROVER-E, OV2640, SDMMC slot, CH340, no NeoPixel: Rob's photo shows only the IO2, RX, TX and ON LEDs; the pixel he meant is on another S3 board, and GPIO 13, 32 and 33 free) (the camera varies between batches: Freenove document an OV2640, and Rob's kit, on his bench 2026-09-25, carries a GalaxyCore GC0308, 640x480 at most with no JPEG encoder, which the firmware's FNCAM 1.0.2 captures raw and encodes on the board in 3.6 to 3.9 s; the firmware supports both, and since site 1.2.7 the Freenove is running there, core, card and camera, though no release carries it yet) and the ESP32-S3-CAM Rob has on order (N16R8, OV3660, two USB-C, an external antenna). The S3 camera board has not run a build yet. Since site 1.2.1 this page also owns the facts /build used to carry: the chip list, the dev board's memory and power (ESP32-WROOM-32E datasheet v2.1, table 16: 379 mA peak on 802.11b transmit, a 0.5 A supply), and the spectrum at the top. The speeds (site 1.2.5) are Rob's expectation, not a measurement: fast, faster for the Freenove's PSRAM, fastest for the S3; replace them with measured figures once the benchmark has run on all three. The spectrum's prices are Rob's, 2026-09-24: a WROOM dev board about $5, the Waveshare about $20, plus an SD module about $2 and jumpers for the middle stop. Re-check them when they look wrong. The seal on each board's picture (site 1.2.5) is Rob's: flash & go for every board here, the S3 camera board expected until tested. Since site 1.2.7 the dev board is two entries (Rob: "esp32 is misleading with flash and go, it has to have an sd card"): bare, flash & go, and with an SD card, the first to wear a little wiring. Both run the one ESP32 image, so the second is drawn from SHOWN_BOARDS in server.py and never reaches the installer's picker. What needs a card is the firmware's own: files and forums are PF_SD (src/plugins/files.cpp, forums.cpp), and backups to the card came in 1.1.0. Since site 1.2.9 (Rob) both dev board entries are "(Base)": one choice on the installer, with or without a card. The Freenove moved into BOARDS in server.py, marked to wait for a release, so its entry is coming soon until a release on disk carries its image set (esp32-fncam, firmware 1.1.0) and tested from then, by the gates below and by what is on disk. Since site 1.3.1 (Rob) the two S3 boards also wear a lock, since site 1.3.3 a seal the size of Flash & go reading "SECURE*", its footnote a Secure row giving the version, until a release carrying SSH is on disk (BOARD_SSH in server.py); Rob set the version on 2026-09-25: SSH ships in firmware 1.2.0; SSH is from the firmware's CLAUDE.md, "An encrypted option ... Queued as an S3 option, not started", 2026-09-24, and is for the S3 profiles only, so the classic ESP32 boards carry no ribbon and no SSH line. Since site 1.3.4 (Rob, 2026-09-25) the ESP32-CAM, from SOON_BOARDS in server.py, and "Choosing a camera board": the ESP32-CAM's facts are Rob's bench and the firmware's board profile being finished (BBS_BOARD_AI_ESP32CAM in src/board.h, the espcam-1.1.1 lane: ESP32-D0WDQ6, 4 MB flash, 4 MB PSRAM, an OV2640 read over SCCB, UXGA frames, a white flash LED on GPIO 4, GPIO 0 the camera clock so no BOOT button); the largest photo sizes are each sensor's own (OV2640 UXGA 1600x1200, OV3660 QXGA 2048x1536 per OmniVision's datasheet, GC0308 VGA) except the Freenove's, which is its build's (BBS_CAM_SIZES "qvga|vga" for either sensor); prices checked 2026-09-25: an ESP32-CAM-MB two-pack about $18 on Amazon (makeradvisor.com), the Freenove FNK0060 $18.99 at store.freenove.com with a 1 GB card, an ESP32-S3-CAM N16R8 with OV3660 about $10 on eBay; no Amazon price could be read. Since site 1.3.5 (Rob, 2026-09-25) the ESP32-CAM is in BOARDS and on the installer as a preview, its entry switched by "::: from esp32-cam" gates, and its PSRAM is 8 MB with 4 MB usable (the 1.3.4 figure of 4 MB was the usable part); its facts are in the comment above its entry. -->
# Which board to buy

The tested boards: the ones this software, the [[firmware]], has actually run
on, each with its own image on [the installer](/install). Each one is small
enough to lose in a drawer, and each
is a whole BBS the moment it has power and Wi-Fi. Pick yours by the picture: the installer checks the chip,
and a picture is the only way to tell two boards with the same chip apart.

::: art
hardware-spectrum
:::

Three ways to build one. Each is a choice, not a step on a ladder:

- **[A bare ESP32 dev board](#esp32-dev-board-base)**: functional, and the lowest
  cost. About $5, and about five minutes from the browser. Chat, mail,
  accounts and a directory listing; file areas and forums need a card.
- **[The same board with an SD card](#esp32-dev-board-base-sd-card-for-storage)**: economical and usable. About
  $8 with the card module and jumper wires, and about half an hour, most of
  it wiring the card.
- **[An ESP32-S3 board](#waveshare-esp32-s3-lcd-1-47)**: advanced
  capabilities. About $20, a screen, a card slot and a drive light on the
  board, and no wiring. It does need BOOT and RESET pressed by hand to install, which is
  why it takes a little longer than the bare board.

::: until 1.1.0
Camera boards are next: three boards with a camera on them, coming soon, so
a visitor can take a picture of whatever the board is looking at and
download it. They are side by side in [choosing a camera
board](#choosing-a-camera-board).
:::

::: from 1.1.0
::: until esp32-cam
And one with a camera: [the Freenove camera
board](#freenove-esp32-camera-board), so a visitor can take a picture of whatever
the board is looking at and download it. Two more camera boards follow: the
ESP32-CAM once its build is published, and one on the ESP32-S3 once it
has been tested. The three are side by side in [choosing a camera
board](#choosing-a-camera-board).
:::

::: from esp32-cam
And two with a camera: [the Freenove camera
board](#freenove-esp32-camera-board) and [the ESP32-CAM](#esp32-cam), so a
visitor can take a picture of whatever the board is looking at and download
it. A third, on the ESP32-S3, follows once it has been tested. The three are
side by side in [choosing a camera board](#choosing-a-camera-board).
:::
:::

The prices are typical listings in September 2026, and they move. A micro SD
card is extra on either board that takes one. The times are for somebody
doing it the first time. The speeds are expected, not measured: fast for
the ESP32 dev board, faster for the Freenove camera board and the ESP32-CAM,
with their PSRAM, and fastest for the ESP32-S3 boards, and measured figures follow once all three kinds of board are
running side by side.

The seal on each picture says how much building there is. **Flash & go**:
everything is on the board, plug it in and install from the browser. **A
little wiring**: a part to add with jumper wires, and a page of steps for it.
The ESP32-S3 boards carry a second seal in the opposite corner: a padlock
and **Secure**, with an asterisk for now. They are the boards getting [[SSH]],
an encrypted way to connect, beside telnet, in firmware 1.2.0. That is not
released yet, which is what the asterisk says; the board's Secure line gives
the version, and the asterisk goes the day a release carries it.

The buy links below are Amazon affiliate links: a purchase through one may
earn the project a small commission, at no extra cost to you. Each goes to the
listing for the board that was tested, or for a camera board, the one being
tested, and any board that matches the picture and the chip will do, bought
anywhere.

## ESP32 dev board (Base)

::: board
esp32
:::

The reference board, and the one every release so far was built and tested
on. With a card wired to it or without, it installs the same image, from the
one **ESP32 dev board (Base)** choice on the installer. A dev board round the ESP32-WROOM-32E module, with 4 MB of flash and a
USB-serial chip beside its socket: most boards sold as "ESP32 DevKit" or
"ESP32-WROOM-32" look like this. A long board, a row of pins down each side,
the module's metal can at one end with its antenna past the edge, and the USB
socket at the other end between two buttons.

- **What it does with no card:** chat, mail, accounts, the information
  pages and a directory listing, straight from the installer.
- **What needs a card:** file areas, forums, backups kept on the card, and
  the photos on a camera board. With no card those are not offered at all.
  The dev board with a card is [the next entry](#esp32-dev-board-base-sd-card-for-storage).
- **What was tested:** installing from this site, setting the Wi-Fi from the
  browser, the first-call setup, and callers from PuTTY, SyncTERM and a
  Commodore 64 through a TeensyROM.
- **How many at once:** ten people, plus a busy line that tells the
  eleventh to try again later, and a hidden line for the [[sysop]], the host.
  Technical details: 520 KB of SRAM and 4 MB of flash, no PSRAM, and
  Bluetooth switched off.
- **Power:** the USB port you installed it from, a phone charger, or 3V3 on a
  bench supply. It draws about a tenth of an amp while it waits, because the
  firmware keeps the radio listening rather than letting it doze, and a little
  under 400 mA for the instant the radio transmits, so anything that can
  deliver 500 mA is comfortable.
- **What you can add:** an SD card, below, and a drive light and a strip of
  pixels for a case, on [the lights page](/lights).

::: next
[Go to the installer](/install)
:::

## ESP32 dev board (Base) + SD card, for storage

::: board
esp32-sd
:::

The same dev board with a micro SD card module wired to it, which is how every
release so far was tested. It installs the same image, from the same **ESP32
dev board (Base)** choice on the installer: the card is what switches the rest
of the board on.

- **What it does:** everything the BBS does. File areas callers can download
  from and upload to, forums, screens of your own, and from firmware 1.1.0
  the board's backups kept on the card, on top of everything the bare board
  does.
- **What it holds:** a card of up to 32 GB is a library on one board: a
  lifetime of disk images, text files and utilities for the machines that
  call in, every one a download by XMODEM or YMODEM.
- **What it costs:** about $8 with the card module and jumper wires, and
  about half an hour the first time, most of it wiring the card. A micro SD
  card of 32 GB or smaller is extra.
- **The wiring:** four signal wires plus power, from the module to the
  board's pins. The diagram, the pins, and what to do if the card will not
  mount are on [the SD card page](/sdcard).

::: next
[Wire the SD card](/sdcard)
:::

## Waveshare ESP32-S3-LCD-1.47

::: board
esp32s3
:::

The ESP32-S3 board, and exactly this one: a USB stick with an ESP32-S3 on it
and a small colour screen, the second board the firmware runs on. Tested on Rob's bench on 24 September 2026 with a 1.1.0
preview: it boots, answers telnet, mounts its SD card, shows the board's
figures on its screen, and runs the drive light on its own LED.

What it adds over the ESP32 dev board:

- **A screen that shows the board's figures.** Its name and the time, callers
  on out of how many lines, the address to dial, how long it has been up, the
  card's free space, and the last login, logoff or page.
- **A drive light already fitted.** The RGB LED on the board is the drive
  light, on from the first start.
- **A card slot on the board.** A TF (micro SD) card goes straight in.
- **Encrypted connections, coming in firmware 1.2.0.** [[SSH]] beside
  telnet, so what a caller types is scrambled on the way. For the S3 boards
  only, and not released yet; telnet stays, for the machines that cannot do
  it. [On the roadmap](/roadmap).
- **More memory:** 16 MB of flash and 8 MB of PSRAM, against the dev board's
  4 MB of flash and none.

No wiring, and none of the build pages: [the SD card page](/sdcard) and [the
lights page](/lights) are for the dev board. The card goes in the slot, the drive
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

It has no USB-serial chip, so it goes on a little differently: BOOT and RESET
pressed by hand, in three steps on the installer page.

::: next
[Steps for this board](/install#on-the-waveshare-s3)
:::

## Choosing a camera board

Three boards with a camera on them, and the camera is what sets them apart.
A camera's [[sensor]] decides the largest photo it can take, and the board
offers only the sizes its sensor, and its build, can take. The ESP32-S3
camera board has not been tested yet, so its table is what is expected.

| ESP32-CAM | |
|---|---|
| Sensor | OmniVision OV2640 |
| [[Megapixels]] | 2 |
| Largest photo | 1600x1200 |
| Price | About $9 a board, sold in pairs |
| On the board | A micro SD slot, a white flash LED, and micro USB on its programmer board |
| Verdict | The best camera for the money |

| Freenove camera board | |
|---|---|
| Sensor | Varies: a GalaxyCore GC0308 on Rob's, an OV2640 in Freenove's documents |
| Megapixels | 0.3 with a GC0308, 2 with an OV2640 |
| Largest photo | 640x480, with either camera |
| Price | About $19, a card included |
| On the board | A micro SD slot and a USB-C socket |
| Verdict | The easiest to set up; check its camera |

| ESP32-S3 camera board (expected) | |
|---|---|
| Sensor | OmniVision OV3660 |
| Megapixels | 3 |
| Largest photo | 2048x1536 |
| Price | From about $10, by seller |
| On the board | Two USB-C sockets; a card slot varies by maker, so check the listing |
| Verdict | The best overall, once tested |

The prices are typical listings in September 2026, and they move. Every one
of these boards needs a micro SD card for its photos.

- **The best camera for the money: [the ESP32-CAM](#esp32-cam).** A genuine
  2 megapixel OV2640 on Rob's, taking photos of 1600x1200, and a pair costs
  about what one Freenove does. It connects to a computer through the
  programmer board it sits on, which comes with it, and its SD card comes out
  while it is installed or updated.
- **The easiest: [the Freenove camera board](#freenove-esp32-camera-board).**
  One board, a USB-C socket, and no programmer board. Check which camera
  came with it, or plan to swap it: its camera varies between batches, and
  the one on Rob's takes 640x480 at most.
- **The best overall, when tested: [the ESP32-S3 camera
  board](#esp32-s3-camera-board).** A 3 megapixel camera, more memory, and
  encrypted connections coming in firmware 1.2.0. Rob's is on order, so this
  is expected, not measured.

## Freenove ESP32 camera board

::: board
esp32-fncam
:::

::: until 1.1.0
**Coming soon.** Freenove's camera kit, FNK0060, and the first of two boards
with a camera on them. It is running on Rob's bench: the board, its SD card
and its camera all work, and callers can take photos with it. It goes on the
installer once a release carries its build.
:::

::: from 1.1.0
Freenove's camera kit, FNK0060, and the first board with a camera on it to go
on the installer. Tested on Rob's bench in September 2026 with the 1.1.0
development builds: the board, its SD card and its camera, with callers taking
photos and downloading them.

> **Same chip as the dev board.** The installer reads the chip, not the
> board, so it cannot tell the two apart: the picture is the check. The
> [steps for this board](/install#on-the-freenove-camera-board) say what
> else is different about installing it.
:::

- **What it has:** an ESP32-WROVER-E with 4 MB of flash and 8 MB of PSRAM, a
  camera on a ribbon, a micro SD slot with a card in the box, a USB-C socket
  with a CH340 USB-serial chip beside it.
- **The camera varies between batches.** Freenove's documents name an
  OV2640, and Rob's kit came with a GalaxyCore GC0308 instead: 0.3 megapixels,
  640x480 at most, and no JPEG encoder of its own, so the board encodes each
  photo itself, in about 4 seconds a picture. The firmware works with either,
  and the `CAMERA` command names the one it found.
- **The camera can be swapped.** It plugs into a 24-pin ribbon socket, and a
  genuine OV2640 module fits it in place of a GC0308. That is a better
  camera, which encodes its own JPEGs, though the Freenove's build takes
  640x480 photos at most with either.
- **No wiring.** The card goes in the slot. There is no free light on the
  board (its one LED shares a pin with the card), so a drive light or a
  photo flash is a pixel you add on a spare pin, as on the dev board.
- **Three pins to spare**, GPIO 13, 32 and 33. The camera and the card use
  nearly every other pin on the board.
- **The camera needs the card.** Photos are kept on it.

::: next
[What callers can do with it](/camera)
:::

## ESP32-CAM

::: board
esp32-cam
:::

<!-- Site 1.3.5 (Rob, 2026-09-25): on the installer as a preview, from the firmware's pre-release v1.1.1-dev.0 (ESPCAM 1.0.1). Facts from Rob's bench that day and src/board.h in the firmware's espcam-1.1.1 lane: ESP32-D0WDQ6 rev 1, 4 MB flash, 8 MB PSRAM with 4 MB mapped, a genuine OV2640, the card over SPI (CS 13, MOSI 15, CLK 14, MISO 2) with a 32 GB SDHC mounted, the white LED on GPIO 4 a pin flash off as shipped ("very bright ... gets hot if left on", board.h), the red LED on GPIO 33 the activity LED, GPIO 0 the camera's clock so no BOOT and no backup button, no pins left for the lights or the serial bridge as shipped. The card-out step: GPIO 2 is the card's line and a boot strap that must be low or floating for the chip's download mode (Espressif, esptool "Boot mode selection"; ESP-IDF "SD pull-up requirements"). The two gates switch by themselves once the installer offers this board anything, a preview included. -->
::: until esp32-cam
**Coming soon.** The ESP32-CAM, a small board first made by AI-Thinker and
now sold under many names; Rob's are an Aideepen two-pack. It runs on Rob's
bench, camera and SD card included, and it goes on [the installer](/install)
once its build is published.
:::

::: from esp32-cam
The ESP32-CAM, a small board first made by AI-Thinker and now sold under many
names; Rob's are an Aideepen two-pack. Tested on Rob's bench in September
2026: the board, its SD card and its camera, taking photos at full size. It
is on [the installer](/install) as a preview: an early build, out for testing
before a full release carries it.

> **Take the SD card out to install it.** Before you install or update, take
> the micro SD card out of its slot. When the installer is done, unplug the
> board, put the card back, and plug it in again. With a card in, the board
> starts up as usual instead of taking the new software. The [steps for this
> board](/install#on-the-esp32-cam) say why, and what you see if the card is
> still in.
:::

Its camera is better than the one on Rob's Freenove: a genuine OmniVision
OV2640, 2 [[megapixels]], taking photos of 1600x1200, where the Freenove's
GC0308 stops at 640x480.

- **What it has:** an ESP32-D0WDQ6 with 4 MB of flash and 8 MB of [[PSRAM]],
  of which the chip can use 4 MB; a camera on a ribbon; a micro SD slot; a
  white LED on the front and a small red one on the back.
- **Its programmer board.** The ESP32-CAM has no USB socket of its own. It
  sits on an ESP32-CAM-MB, a second board with a micro USB socket and a CH340
  USB-serial chip, which is how it connects to a computer and is installed.
  It puts the board into its flashing mode by itself, so there are no buttons
  to press. The two come together.
- **The camera needs the card.** Photos are kept on it. A 32 GB card worked
  on Rob's; the board runs the slot in SPI mode.
- **The white LED is the camera's flash.** It is off as shipped: turn it on
  with the Flash setting in `CONFIG camera`. It is very bright, and it gets
  hot if it is left on.
- **The red LED is the activity light.** It blinks with traffic, like the
  dev board's.
- **No BOOT button recovery.** The camera's clock uses the pin other boards
  give their BOOT button, so on this one no button puts a forgotten sysop
  password back or opens the backup window. `BACKUP SD` still saves a backup
  to the card, and installing is not affected.
- **No pins to spare.** The camera, the card and the memory use nearly every
  pin, so this board has no [lights](/lights) and no serial bridge.

::: next
[What callers can do with it](/camera)
:::

## ESP32-S3 camera board

::: board
esp32s3-cam
:::

**Coming soon.** A board sold as the ESP32-S3-CAM: an ESP32-S3 N16R8, with
16 MB of flash and 8 MB of PSRAM, an OV3660 camera of 3 megapixels, two USB-C
sockets and a lead for an external antenna. Rob's is on order, and it will be
tested when it arrives.

Boards sold under that name are made by several companies, and they are not
all the same board: the pins, the lights and the USB wiring differ. The build
will be for the one that was tested, taken from its own schematic, and this
section will say which it is once it has run. Until then, buying one to run
this firmware is buying ahead of the testing.

As an ESP32-S3 board it is also in line for [[SSH]], encrypted connections
beside telnet, **coming in firmware 1.2.0** with the Waveshare, once this board
has a build of its own.

::: next
[What callers can do with it](/camera)
:::

## Other chips

Plenty of chips are sold under the ESP32 name, and not all of them can run a
board. It needs two processor cores and Wi-Fi built into the chip. The BBS
runs on one core while Wi-Fi and the network run on the other, and that split
is what stops the radio's work from making callers' lines lag.

<!-- The same list twice, so each is one list: the WROVER line changes when a release carries the Freenove's image (firmware 1.1.0). Edit both until then, then drop the "until" one. -->
::: until 1.1.0
- **ESP32-WROOM-32E: yes, tested.** The dev board above. Every release is
  tested on it.
- **ESP32-S3: yes, on one board.** The Waveshare above. Another S3 board needs
  a build of its own, because the image carries the Waveshare's pins.
- **ESP32-WROVER: should work, not yet tested.** The same original ESP32
  chip, as are other modules built on it, so the dev board's image should run.
  A WROVER adds PSRAM, a second memory chip on the module, which that image
  does not use. The Freenove camera board above is built on one, and gets a
  build of its own for its camera and card slot.
- **ESP32-D0WDQ6: yes, on one board.** The ESP32-CAM above: the same
  original ESP32 chip again, with PSRAM beside it, and a build of its own for
  its camera and card slot.
- **ESP32-S2, ESP32-C3 and ESP32-C5: no.** One core each, the C5 even with
  its dual-band Wi-Fi.
- **ESP32-C6: no.** One main core. Its second, low-power core cannot run the
  board.
- **ESP32-H2: no.** One core, and no Wi-Fi.
- **ESP32-P4: no.** No Wi-Fi on the chip. It needs a second chip to reach a
  network.
:::

::: from 1.1.0
- **ESP32-WROOM-32E: yes, tested.** The dev board above. Every release is
  tested on it.
- **ESP32-S3: yes, on one board.** The Waveshare above. Another S3 board needs
  a build of its own, because the image carries the Waveshare's pins.
- **ESP32-WROVER: yes, on one board.** The Freenove camera board above, with a
  build of its own for its camera and card slot. The WROVER is the same
  original ESP32 chip with PSRAM, a second memory chip, on the module, so
  another WROVER board should run the dev board's image, which leaves the
  PSRAM unused. That has not been tested.
- **ESP32-D0WDQ6: yes, on one board.** The ESP32-CAM above: the same
  original ESP32 chip again, with PSRAM beside it, and a build of its own for
  its camera and card slot.
- **ESP32-S2, ESP32-C3 and ESP32-C5: no.** One core each, the C5 even with
  its dual-band Wi-Fi.
- **ESP32-C6: no.** One main core. Its second, low-power core cannot run the
  board.
- **ESP32-H2: no.** One core, and no Wi-Fi.
- **ESP32-P4: no.** No Wi-Fi on the chip. It needs a second chip to reach a
  network.
:::

A single-core chip could be made to run it, but the radio and the callers
would take turns on one core and callers would feel it, and doing that
properly means rebuilding the core of the BBS rather than changing a setting.
A board is listed as tested once a build has actually run on it, and it goes
on the installer then.
