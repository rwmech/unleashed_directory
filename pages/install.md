# Put the BBS on your board

Plug an ESP32 into your computer, click a button on this page, and it becomes a
bulletin board. No toolchain, no compiler, no account, nothing to install.

This works because Chrome can talk to a serial port. The page reads the chip on
the other end of the cable, writes the firmware to it, and then asks you which
Wi-Fi network it should join. Five minutes, most of it waiting.

::: installer
:::

## Before you start

> **Chrome or Edge, on a desktop or laptop**, is the path that works.
> Firefox can do it from version 151, released in May 2026, but it asks your
> permission twice and the first prompt is a confusing one, so it is the harder
> road rather than a broken one. **Safari cannot do this at all**, and neither
> can anything on an iPhone or an iPad: every browser on iOS is Safari
> underneath whatever name is on the icon. On a Mac, use Chrome or Edge.

The part that does the work is Web Serial, a browser feature rather than
anything this site installs. If the button below says your browser cannot do
it, your browser is the thing to change; nothing else on this page will help.

- **An ESP32 with 4 MB of flash.** The reference board is a bare
  ESP32-WROOM-32E. Any dev board with that module and a USB socket works, and
  those are the ones sold as "ESP32 DevKit" for the price of a sandwich.
- **A USB cable that carries data.** This is the single most common reason
  the board never appears. Cables sold with phone chargers and battery packs
  are very often power-only: they have the plugs, they light the board up, and
  there is no data pair inside them at all. If nothing shows in the list of
  ports, change the cable before you change anything else.
- **Nothing else holding the port.** A serial monitor, the Arduino IDE,
  `pio device monitor`, or a second tab of this page will each keep the port to
  themselves. Close them first.

## What it does to what is already on the chip

Worth reading before you click, because you are asked a question about it and
one of the two answers cannot be undone.

Partway through, a box appears headed **Erase device**, and it starts
**unticked**. That is the whole decision:

- **Tick it if this is a new board**, or one that has been running something
  else. A full erase clears the chip completely: any other firmware, anything
  it had stored, the lot. It is also what gives the BBS a clean chip to lay its
  partitions out on, so a first install wants it.
- **Leave it unticked if you already run a µnleashed board** and are moving it
  to a newer version. Then only the firmware and the screens are rewritten.
  Your accounts, your settings, your chat mail and your directory listing live
  on a separate flash partition that is not written to at all, and neither is
  the caller log, which has a partition of its own because it is the sysop's
  security record.

That split is not a happy accident of this page: it is why the partition table
is arranged the way it is, and it is the same rule `pio run -t flashall`
follows on the command line.

> Nothing on this page can put back what a full erase removed. If the board
> currently holds something you care about, copy it off first.

The one case that breaks the second rule is a release that moves a partition.
That has happened once and will be said plainly in the release notes when it
happens again: those need the full erase, and they take the accounts with them.

## Wi-Fi

The board has no screen and no keyboard, so it is told which network to join
over the same cable you just flashed it with. Once the firmware is on and the
board has restarted, the browser asks for the network name and the passphrase
and hands them straight to it.

They are kept on the board's own filesystem rather than built into the
firmware, which is what makes them yours instead of whoever produced the image,
and it is why they survive an update. They go from your machine down the cable
to your board and nowhere else. This site never sees them and has nowhere to
put them if it did.

That step follows the erase choice above: it appears on a fresh install,
because a chip that was just wiped has no network to remember. Update an
existing board without erasing and you are not asked, because your board
already knows.

2.4 GHz only, which is not a limitation of this project but of the radio in
every ESP32. A network that runs both bands under one name is fine: the board
finds the 2.4 GHz side on its own.

## When the board does not appear

In the order worth trying.

1. **Change the cable.** A charge-only cable is the cause more often than
   everything below put together. A cable you have used to move files off a
   phone is known good; one that came in the box with something is not.
2. **Close whatever else is using the port.** Serial monitors hold it open.
3. **Try the other USB socket**, and prefer one on the machine itself over a
   hub or a monitor.
4. **Install the USB-serial driver.** The ESP32 does not talk USB itself;
   there is a second chip on the board that does. Most boards use a
   [CP210x](https://www.silabs.com/developer-tools/usb-to-uart-bridge-vcp-drivers)
   or a [CH340](https://www.wch-ic.com/downloads/CH341SER_ZIP.html), and the
   square chip next to the USB socket is labelled with which. Linux has both
   already; Windows and macOS sometimes need the download.
5. **Hold the BOOT button** while you click connect, and let go once it starts.
   Boards that cannot be reset into the bootloader over the cable need this,
   and it costs nothing to try on the ones that do not.
6. **Use a powered hub or a different port** if the board browns out partway
   through. A board that disconnects at the same point every time is usually
   being starved rather than broken.

## Doing it the other way

The browser is the short path, not the only one. Everything here is also a
`git clone` and `pio run -t flashall`, which is what you want anyway once you
start changing things: the [build page](/build) has that, along with the
hardware, the SD card and how to put the board on the internet.

The source is at
[github.com/rwmech/unleashed_BBS](https://github.com/rwmech/unleashed_BBS),
GPL v2 or later. Anything this page installs, you can build yourself and check.

## After it boots

The board comes up, joins your network and starts listening on port 6400. The
activity LED holds on for a second once the board is listening.

[Call it with any telnet client](/terminals). It works out what it is talking
to on connect, so SyncTERM, PuTTY, a Commodore 64 through a TeensyROM and a
VT220 on a serial adapter all get a screen drawn for them rather than a
compromise. If this is your first time, [what to expect on a first
call](/firstcall) is two minutes long.

Then, if you want it on this list, turn on the `announce` plugin and
[forward port 6400](/forward).
