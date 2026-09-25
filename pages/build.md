# Build one

A board of your own, on hardware that costs less than lunch.

::: cta
[Visit the web installer](/install)
[Build from source](#for-developers-build-from-source)
The web installer needs Chrome or Edge, a USB cable and about five minutes,
and no programming tools. It installs the software, the [[firmware]], by
[[flashing]] it onto the board, and the same page sets up the board's Wi-Fi.
Every setting after that is in [the setup guide](/setup). Building from
source is the
longer road, and the one you want once you start changing things.
:::

Nothing here is a kit and nothing is soldered to anything. If you have an ESP32
dev board in a drawer, you already have most of it.

## What you need

- **A compatible ESP32 board.** A small computer with Wi-Fi built in, on a
  circuit board with a USB socket. Not every ESP32 can run the BBS, so choose
  one of the two it has been tested on.
- **A USB data cable.** Some cables only charge, and your computer never sees
  the board through one of those. A bare ESP32 module, rather than a dev board, needs [a
  little more](#on-a-bare-module).
- **2.4 GHz Wi-Fi.** The board's radio cannot join a 5 GHz network, and a
  router that offers both bands under one name is fine.

::: next
[Choose a board](/hardware)
:::

## Adding to it

Two additions for the ESP32 dev board, both optional, each with a page of its
own:

- **An SD card**, for file areas, forums and screens of your own: a module that
  costs about two dollars, and four signal wires plus power.
- **Lights**, for a board in a case: a drive light that shows the storage at
  work, and a strip of pixels that shows the callers.

::: next
[Add an SD card](/sdcard)
[Add lights](/lights)
:::

The other tested board, an ESP32-S3 board with a screen, needs neither: its
card slot and its drive light are built in.

Coming soon, two camera boards add a third: a camera on the board, so a
visitor can snap a picture of whatever it is pointed at, from any computer that
connects. The boards are on [the tested boards
page](/hardware#freenove-esp32-camera-board), and what visitors can do with
them is on [the camera page](/camera).

## For developers: build from source

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

### On a bare module

A bare ESP32 module, without a dev board around it, also wants 3V3, ground, EN
pulled up, GPIO0 to ground while you flash it, and a USB-serial adapter on the
console pins.

## Joining it

Any [[telnet client]], a free app for joining, will do, and SyncTERM is the one
worth installing on a computer if you have none; on a phone, TERMinator. So
does an Atari 800 through a FujiNet, an Apple II with an Uthernet card, or a
VT220 on a serial adapter. Before you connect, read [what happens on your
first call](/firstcall).

::: next
[Choose an app for joining](/terminals)
:::

## Keeping it

A new version does not cost you the accounts, the settings or the mail:
`pio run -t flashall` rewrites the firmware and the screens and cannot reach
them. An update from the browser keeps them too, and [the upgrade
page](/upgrade) says how, and how to take a backup first.

## Letting people outside your home join

[[Port forwarding]], one setting on your router, is what lets people outside
your home reach the board. It opens a door in your network, and what they type
is not encrypted. The port forwarding page starts with what that risks, and
[the privacy page](/privacy) says what it means for your visitors.

::: next
[Read before you forward a port](/forward)
:::

## Listing it here

Switch on the `announce` plugin with `CONFIG announce`, and the board is listed
after three hours of heartbeats. The rest is on [the getting listed
page](/how).

## The source

Everything is at [github.com/rwmech/unleashed_BBS](https://github.com/rwmech/unleashed_BBS),
GPL v3 or later. The directory server you are reading is at
[github.com/rwmech/unleashed_directory](https://github.com/rwmech/unleashed_directory)
under the same licence, so you can run the whole stack yourself and never speak
to us again.
