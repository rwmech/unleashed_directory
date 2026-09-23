# Build one

A board of your own, on hardware that costs less than lunch.

::: cta
[Visit the web installer](/install)
[Build from source](#getting-it-running)
The web installer needs Chrome or Edge, a USB cable and about five minutes,
and no toolchain. The same page sets up the board's Wi-Fi, and [the setup
guide](/setup) covers every setting after that. Building from source is the
longer road, and the one you want once you start changing things.
:::

Nothing here is a kit and nothing is soldered to anything. If you have an ESP32
dev board in a drawer, you already have most of it.

## What you need

- **An ESP32 with 4 MB of flash.** The reference board is a bare
  ESP32-WROOM-32E: 520 KB of SRAM, 4 MB of flash, no PSRAM, Bluetooth off. Not
  every ESP32 can run it, and the table below says which. A dev board with a
  USB-serial chip needs nothing but the cable.
- **A USB cable**, and that is the whole bill of materials for a dev board. A
  bare module also wants 3V3, ground, EN pulled up, GPIO0 to ground while you
  flash it, and a USB-serial adapter on the console pins.
- **Wi-Fi**, 2.4 GHz. The board scans every channel and joins the strongest
  access point with your SSID, so a mesh needs no special handling.
- **Power.** It runs from the USB port you flashed it with, a phone charger, or
  3V3 on a bench supply. It draws about a tenth of an amp while it waits,
  because the firmware keeps the radio listening rather than letting it doze,
  and peaks a little under 400 mA for the instant the radio transmits, so anything
  that can deliver 500 mA is comfortable.

## Which ESP32

Plenty of chips are sold under the ESP32 name, and not all of them can run a
board. It needs two processor cores and Wi-Fi built into the chip. The BBS runs
on one core while Wi-Fi and the network run on the other, and that split is
what stops the radio's work from making callers' lines lag.

| Chip | Runs it? | Why |
|---|---|---|
| ESP32-WROOM-32E | **Yes, tested** | The reference board: ten caller lines, a busy line and a hidden sysop line. The only one anybody has run. [SD card wiring diagram](/sdcard) |
| ESP32-WROVER | Should work, not yet tested | The same original ESP32 chip, and the same goes for other modules built on it. A WROVER adds PSRAM, a second memory chip on the module, which leaves room for more callers, but nobody has measured how many. |
| ESP32-S3 | Should work, not yet tested | Two cores and Wi-Fi, with or without PSRAM. There is no ready-made firmware build for it yet. |
| ESP32-S2 | No | One core. |
| ESP32-C3 | No | One core. |
| ESP32-C5 | No | One core, even with dual-band Wi-Fi. |
| ESP32-C6 | No | One main core. Its second, low-power core cannot run the board. |
| ESP32-H2 | No | One core, and no Wi-Fi. |
| ESP32-P4 | No | No Wi-Fi on the chip. It needs a second chip to reach a network. |

The firmware is built for the original ESP32 and does not run on the others as
it stands. A single-core chip could be made to run it, but the radio and the
callers would take turns on one core and callers would feel it, and doing that
properly means rebuilding the core of the BBS rather than changing a setting.

## Getting it running

```
git clone https://github.com/rwmech/unleashed_BBS
cd unleashed_BBS
cp include/secrets.h.example include/secrets.h     # SSID and passphrase
cp data/system.cfg.example data/system.cfg         # timezone, passwords, limits
pio run -t flashall
pio device monitor
```

The console tells you the address it came up on:

```
online 192.168.0.109  dial in: telnet 192.168.0.109 6400
```

The activity LED holds on for a second once the board is listening, so
you know it is ready without dialling in to find out.

On a normal home network the board also answers to `unleashed.local`, which is
the `hostname` setting doing double duty as the DHCP and mDNS name.

## Calling it

[Any telnet client](/terminals). SyncTERM is the one worth installing if you
have none. A Commodore 64 with a TeensyROM works too, and so does a VT220 on a
serial adapter. The board works out what it is talking to on connect: ANSI with
CP437 or UTF-8, PETSCII at 40 or 80 columns, or plain ASCII, asking a question
or two if the terminal does not answer its probe, and it draws itself
accordingly.

## Keeping it

Firmware updates do not cost you the board. Accounts, settings, chat mail and
your directory listing live on their own flash partition, and `pio run -t
flashall` cannot reach it: the filesystem upload only rewrites the screens.

The backup window is the other half of that. Hold the BOOT button while logged
in as sysop and the board opens an HTTP server for a few minutes: download a zip
with the configuration, the accounts and the screens in it, edit them on a real
keyboard, upload it back. Uploads are staged and applied only after you say yes.

## Putting it on the internet

Forwarding port 6400 from your router is what makes a board callable from
outside, and it is a decision to make deliberately rather than by accident.
This is plain telnet: passwords cross the wire in the clear, and anybody
sharing a network with a caller can read everything they type. The board tells
new callers that before they choose a password, and so should you.

If that is fine with you, it was fine with everybody in 1985 too.

[How to forward a port on your router](/forward), with step by step pages for
NETGEAR, TP-Link, ASUS, Xfinity gateways, eero and Google Nest Wifi, and an
honest list of the things that will stop it working.

## Listing it here

Turn on the `announce` plugin and the board sends a small heartbeat every ten
minutes saying it exists. Nothing about any caller is ever in it. What it
carries is the board's name, who runs it, how to reach it, and how many lines
are busy.

```
CONFIG announce
```

A listing is earned by three hours of sustained heartbeats, not by asking, and
it disappears when the heartbeats stop. `ANNOUNCE TEST` prints the exact
message the board would send and sends nothing, so you can read it before you
trust it.

You do not have to use this directory. The protocol is documented, the server
is a single Python file, and a board can post to several directories at once.
A directory nobody can replace would contradict the whole point.

## Adding an SD card

Optional, four wires, about two dollars. It is what gets you file areas, forums
and screens of your own. Without one the board is still a board. The pin map,
a wiring diagram and what the card's error messages mean are on the
[SD card page](/sdcard).

## The source

Everything is at [github.com/rwmech/unleashed_BBS](https://github.com/rwmech/unleashed_BBS),
GPL v2 or later. The directory server you are reading is at
[github.com/rwmech/unleashed_directory](https://github.com/rwmech/unleashed_directory)
under the same licence, so you can run the whole stack yourself and never speak
to us again.
