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

- **A board.** [Tested boards](/hardware) has the two this firmware runs on,
  with pictures, what each costs, and which other ESP32 chips can and cannot
  run it.
- **A USB cable that carries data**, and that is the whole bill of materials
  for a dev board. A bare module also wants 3V3, ground, EN pulled up, GPIO0
  to ground while you flash it, and a USB-serial adapter on the console pins.
- **Wi-Fi**, 2.4 GHz. The board scans every channel and joins the strongest
  access point with your SSID, so a mesh needs no special handling.

## Adding to it

The ESP32 dev board takes two additions, each with a page of its own:

- [An SD card](/sdcard), for file areas, forums and screens of your own: a
  module that costs about two dollars, and four signal wires plus power.
- [Lights](/lights), for a board in a case: a drive light that shows the
  storage at work, and a strip of pixels that shows the callers.

The Waveshare S3 needs neither page: its card slot and its drive light are on
the board.

## Getting it running

You need [PlatformIO](https://platformio.org/) and git. For the ESP32 dev
board:

```nowrap
git clone https://github.com/rwmech/unleashed_BBS
cd unleashed_BBS
cp data/system.cfg.example data/system.cfg
pio run -t flashall
pio device monitor
```

`data/system.cfg` holds the timezone, the limits and the rest of the settings.
For the Waveshare S3, add `-e ws_s3_lcd147` to both `pio` commands. If it will
not start writing, hold BOOT, tap RESET, let go of BOOT and try again, as [the
installer page](/install#on-the-waveshare-s3) explains.

A new board has no network yet. Give it one from [the installer](/install):
press **Update my board**, which never erases anything, and use its Wi-Fi
step. Or fill in `wifi_ssid` and `wifi_password` in `data/system.cfg` before
you flash.

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
serial adapter. [Your first call](/firstcall) says what happens when you
connect.

## Keeping it

A new version does not cost you the accounts, the settings or the mail:
`pio run -t flashall` rewrites the firmware and the screens and cannot reach
them. [Upgrading a board](/upgrade) says the same for the browser, and how to
take a backup first.

## Putting it on the internet

Forwarding a port on your router is what lets callers from outside reach the
board. Calls are not encrypted, so read [what opening a port does](/forward)
first, and [the privacy page](/privacy) for what that means to your callers.

## Listing it here

Switch on the `announce` plugin with `CONFIG announce`, and the board is listed
after three hours of heartbeats. [Getting listed](/how) has the rest.

## The source

Everything is at [github.com/rwmech/unleashed_BBS](https://github.com/rwmech/unleashed_BBS),
GPL v2 or later. The directory server you are reading is at
[github.com/rwmech/unleashed_directory](https://github.com/rwmech/unleashed_directory)
under the same licence, so you can run the whole stack yourself and never speak
to us again.
