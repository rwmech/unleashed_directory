# Put the BBS on your board

Plug an ESP32 into your computer, press a button on this page, and it becomes a
bulletin board. No toolchain, no compiler, no account, nothing to install. The
same page sets up its Wi-Fi afterwards, and changes it later if the board moves
house. The box below says whether there is a release to install yet.

This works because a browser can talk to a serial port. The page reads the chip
on the other end of the cable, writes the firmware to it, and then asks you
which Wi-Fi network it should join. Five minutes, most of it waiting.

::: installer
:::

## Before you start

> **Chrome or Edge, on a desktop or laptop**, is the path to take.
> Firefox can do it from version 151, released in May 2026, on a desktop or
> laptop, but it asks your permission twice and the first prompt is a
> confusing one, so it is the harder road rather than a broken one.
> **Safari cannot do this at all**, and as of September 2026 neither can any
> browser on an iPhone or an iPad. On a Mac, use Chrome or Edge.

Chrome on Android has had the same feature since version 148, in May 2026.
Nobody has flashed a board from a phone with this page yet, so treat that as
untried rather than as a way in.

The part that does the work is Web Serial, a browser feature rather than
anything this site installs. If the box above says your browser cannot do it,
your browser is the thing to change; nothing else on this page will help.

- **An ESP32 with 4 MB of flash.** The reference board is a bare
  ESP32-WROOM-32E. Any dev board with that module and a USB socket works, for
  the price of a sandwich. A board with letters after the name, such as
  ESP32-C3 or ESP32-S2, is a different chip: [the build page](/build) has a
  table of which ones can run a board.
- **A USB cable that carries data.** This is the single most common reason
  the board never appears. Cables sold with phone chargers and battery packs
  are very often power-only: they have the plugs, they light the board up, and
  there is no data pair inside them at all. If nothing shows in the list of
  ports, change the cable before you change anything else.
- **Nothing else holding the port.** A serial monitor, the Arduino IDE,
  `pio device monitor`, or a second tab of this page will each keep the port to
  themselves. Close them first.
- **The name and password of your Wi-Fi**, typed exactly: both are
  case-sensitive.

## What happens, in order

1. **Press the button, and pick the port.** The browser shows a list of the
   serial ports it can see. If you are not sure which is the board, unplug it,
   look at the list, plug it back in, and take the one that appeared.
2. **The page reads the chip.** A board already running version 0.22.1 or
   later of this BBS is greeted by name and version, and offered an update.
   Anything else, a new board, one running other firmware or an older version
   of this one, is offered **Install unleashed BBS**.
3. **The erase question**, unless the board was recognised. It is explained
   in the next section, and on a new board the answer is to tick it.
4. **Writing.** A progress bar. The installer itself says this takes about two
   minutes, and asks you to keep the page visible while it works, because a
   browser slows down a tab you are not looking at.
5. **The first start.** After an erase, the board spends its first few moments
   preparing its own storage before it will answer, and the page shows
   **Wrapping up** while it waits. It waits up to 30 seconds.
6. **Wi-Fi.** The page asks the board which networks it can hear and lists
   them. Choose yours, type the password, and press **Connect**. A network
   that hides its name is under **Join other** at the bottom of the list. The
   board tries for up to 30 seconds. If it gets on, it keeps the network and
   the page says **Device connected to the network!** If it cannot, the page
   says **Unable to connect**, the board does not save it, and you can try
   again.
7. **The address.** The page then offers **Visit Device**, which is a link to
   the board's telnet address: `telnet://`, the board's address on your
   network, and `:6400`. If your computer has a telnet program that opens links
   like that, it opens. If it has not, right-click the link and copy it, and
   the address is in the middle; [making the dial links work](/dialing) has
   the fix for next time.

If the Wi-Fi step never appears, the page stopped waiting before the board was
ready. Close the box, press the button again and pick the same port: the board
listens for the page for as long as it is running, and this time the page will
find it and offer **Connect to Wi-Fi**.

## What it does to what is already on the chip

Worth reading before you press the button, because you may be asked a question
about it and one of the two answers cannot be undone.

When the page does not recognise the board, a box appears headed **Erase
device**, and it starts **unticked**. That is the whole decision:

- **Tick it if this is a new board**, or one that has been running something
  else. A full erase clears the chip completely: any other firmware, anything
  it had stored, the lot. It is also what gives the BBS a clean chip to lay its
  partitions out on, so a first install wants it.
- **Leave it unticked only if the board runs an older version of this BBS**,
  from before 0.22.1, and you are moving it to a newer one. Then the firmware
  and the screens are
  rewritten, and nothing else. Your accounts, your settings, your chat mail and
  your directory listing live on a separate part of the flash that is not
  written to at all, and neither is the caller log, which has a part of its own
  because it is the sysop's record of who called.

A board that is already running version 0.22.1 or later is not asked the
question at all. The page recognises it, offers **Update unleashed BBS**, and
does the second of those two things: new firmware and screens, accounts left
alone.

> The same page shows **Erase User Data** when the board already runs the
> version on offer. That is not a small reset: it erases the whole chip,
> accounts, settings, mail and Wi-Fi included, and installs the BBS again from
> nothing. Nothing on this page can put back what an erase removed. If the
> board holds something you care about, copy it off first.

The one case that breaks the update rule is a release that moves a partition.
That has happened twice, at versions 0.14 and 0.17. Those need the full erase
and take the accounts with them, and when it happens again the release notes
will say so plainly, along with what to do.

## Wi-Fi

The board has no screen and no keyboard, so it is told which network to join
over the same cable you flashed it with. The network name and password go from
your machine, down the cable, to your board, and nowhere else. This site never
sees them and has nowhere to put them if it did.

The board keeps them in its own settings, on the part of the flash an update
does not touch, which is why an update does not ask again. It keeps them as
written, so a backup of the board's settings holds your Wi-Fi password too:
keep backups somewhere private.

2.4 GHz only, which is not a limitation of this project but of the radio in
every ESP32. A network that runs both bands under one name is fine: the board
finds the 2.4 GHz side on its own.

## Changing the Wi-Fi later

A new router, a new password, or the board moving to somebody else's house:

1. Plug the board into a computer with the same kind of cable.
2. Open this page and press the button.
3. Pick the port. The page recognises the board and shows **Change Wi-Fi**,
   or **Connect to Wi-Fi** if the board is not on a network right now.
4. Choose the network and type the password, as before.

Nothing else on the board changes. The board only swaps to the new network if
it gets on with it; if it cannot, it keeps the one it had.

## When the board does not appear

In the order worth trying.

1. **Change the cable.** A charge-only cable is the cause more often than
   everything below put together. A cable you have used to move files off a
   phone is known good; one that came in the box with something is not.
2. **Close whatever else is using the port.** Serial monitors hold it open.
3. **Try the other USB socket**, and prefer one on the machine itself over a
   hub or a monitor.
4. **Install the USB-serial driver.** The ESP32 does not talk USB itself;
   there is a second chip on the board that does, and it is the square chip
   next to the USB socket. Most boards use a
   [CP210x](https://www.silabs.com/software-and-tools/usb-to-uart-bridge-vcp-drivers)
   or a [CH340](https://www.wch-ic.com/downloads/CH341SER_ZIP.html); newer
   ones often use a [CH9102](https://www.wch-ic.com/downloads/CH343SER_ZIP.html).
   Linux usually has what it needs built in; Windows and macOS sometimes need
   the download.
5. **On Linux, give yourself the serial port.** Your user has to be in the
   group that owns it, which on most systems is `dialout`. Run
   `sudo usermod -a -G dialout $USER`, then log out and back in.
6. **Hold the BOOT button** while you pick the port, and let go once it starts.
   Boards that cannot be reset into the bootloader over the cable need this,
   and it costs nothing to try on the ones that do not.
7. **Use a powered hub or a different port** if the board browns out partway
   through. A board that disconnects at the same point every time is usually
   being starved rather than broken.

If you press the button and pick nothing, the installer shows its own list of
these, with the same drivers linked.

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
activity LED holds on for a second once the board is listening. In your
router's list of connected devices it is called `unleashed`.

[Call it with any telnet client](/terminals). It works out what it is talking
to on connect, so SyncTERM, PuTTY, a Commodore 64 through a TeensyROM and a
VT220 on a serial adapter all get a screen drawn for them rather than a
compromise. If this is your first time, [what to expect on a first
call](/firstcall) is two minutes long.

## The sysop password

A new board has one password, the sysop's, and it is `unleashed`. The sysop is
whoever runs the board: the person who can change every setting on it.

That password is written here, on a page anybody can read, so on its own it
protects nothing, and the board treats it that way. It only works from your
own network, from a computer on the same Wi-Fi or wired network as the board,
and only until you change it. While it is still set, the board will not put
itself on this directory.

Taking the board over is part of your first call:

1. From a computer on the same network, [call the board](/terminals).
2. Sign up for an account, or log in if you already have one.
3. The board asks for the sysop password to set itself up. Type `unleashed`.
4. It then asks you to choose your own. Choose one you use nowhere else:
   calls to a BBS are not encrypted, and [the privacy page](/privacy) says
   what that means in plain terms.

> **Change it before anything else.** Do not [forward the port](/forward) and
> do not turn on the directory listing until you have. "Only from your own
> network" is a guard, not a wall: the board goes by the address a call arrives
> from, and some routers rewrite forwarded traffic so that a caller from
> outside arrives with an address from inside. On a router like that, an open
> port and the default password would let a stranger in as the sysop. A
> password of your own closes that, whatever the router does.

## Then

- [Set up your BBS](/setup): every setting, page by page, all of it from the
  board with `CONFIG`.
- For callers from outside your own network, [forward port 6400](/forward) on
  your router, once the sysop password is yours. That page covers the common
  routers step by step, and says what it opens before it says how.
