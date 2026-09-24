<!-- "::: install-top" is the top of the page: the title, the install card and the steps, side by side on a desktop and one after another on a phone. The words inside "::: installer" are the card's amber box; the rest of the card (the two buttons, version, notices) comes from what is in firmware/. -->
::: install-top
# Put the BBS on your board

Install the BBS on an ESP32 from this page over a USB cable, then tell it which Wi-Fi network to join. About five minutes, most of it waiting.

::: installer
**Before you start:** Chrome or Edge, on a desktop or laptop. A USB cable
that carries data, not a charge-only one. Close anything else using the
serial port. Your Wi-Fi name and password, exactly
([more below](#before-you-start)).
:::

<!-- The upgrade call-out is the first thing in the steps column, not in the intro: beside the card on a desktop, and after the card on a phone, so it does not push the install button down the first screen. -->
> [!NOTE]
> **Already running µnleashed?** Press **Update my board**, pick the port,
> then **Update unleashed BBS** and **Install**. It never erases: your
> accounts, settings, mail and forums stay, and your SD card is never
> touched. [Upgrading a board](/upgrade), including one older than 0.22.1.

## What happens, in order

::: art
install-cable
:::

1. **Press Install on a new board and pick the port.** The browser lists the
   serial ports it can see. If you are not sure which one is the board,
   unplug it, look at the list, plug it back in, and take the one that
   appeared.
2. **The page reads the chip** and offers **Install or update unleashed
   BBS**. A board already running version 0.22.1 or later of this BBS may be
   greeted by name and version and offered **Update unleashed BBS** instead.
   The page does not always catch a board while it is starting up, and
   nothing is erased either way unless you ask.
3. **The erase question**, headed **Start fresh?**, unless the board was
   recognised. On a new board, tick **Erase everything first**. The section
   of that name, further down, says why and when not to.
4. **Writing.** A progress bar. The installer says this takes about two
   minutes, and asks you to keep the page in view while it works, because a
   browser slows down a tab you are not looking at.

::: art
install-write
:::

5. **The first start.** After an erase, the board spends its first few
   moments preparing its own storage before it will answer, and the page shows
   **Wrapping up** while it waits. It waits up to 30 seconds.

::: art
install-boot
:::

6. **Wi-Fi.** The page asks the board which networks it can hear and lists
   them. Choose yours, type the password, and press **Connect**. A network
   that hides its name is under **Join other** at the bottom of the list. The
   board tries for up to 30 seconds. If it gets on, it keeps the network and
   the page says **Device connected to the network!** If it cannot, the page
   says **Unable to connect**, the board does not save it, and you can try
   again.

::: art
install-wifi
:::

7. **The address.** The page offers **Telnet details**. It opens a page here
   with the board's address on your network and how to call it: the telnet
   command, a link, and the settings for SyncTERM and PuTTY. The address goes
   from the board to your browser and no further; this site never receives
   it. If the board had not joined your Wi-Fi yet when the installer read
   it, there is no address to pass on, and that page says the three ways to
   find it instead.

If the Wi-Fi step never appears, the page stopped waiting before the board was
ready. Close the box, press **Update my board** and pick the same port. The
board listens for the page for as long as it is running, so this time the page
finds it and offers **Connect to Wi-Fi**, and nothing that button offers can
erase the board.
:::

## Before you start

There is nothing to install and no account to make. The installer uses Web
Serial, a feature built into the browser, so the browser is the one thing on
your computer that has to be right.

- **An ESP32 with 4 MB of flash.** The reference board is a bare
  ESP32-WROOM-32E, and any dev board with that module and a USB socket works,
  for about the price of a sandwich. A name with letters after it, such as
  ESP32-C3 or ESP32-S2, is a different chip: [the build page](/build) has a
  table of which ones can run a board.
- **Chrome or Edge, on a desktop or laptop.** Other browsers are below this
  list.
- **A USB cable that carries data.** This is the most common reason the board
  never appears. Cables that come with phone chargers and battery packs are
  very often power-only: they fit, they light the board up, and there are no
  data wires inside them at all. If nothing shows in the list of ports, change
  the cable before you change anything else.
- **Nothing else holding the port.** A serial monitor, the Arduino IDE,
  `pio device monitor`, or a second tab of this page each keep the port to
  themselves. Close them first.
- **Your Wi-Fi name and password**, typed exactly: both are case-sensitive.
  The radio in every ESP32 is 2.4 GHz only, so the board cannot join a 5 GHz
  network. A network that runs both bands under one name is fine: the board
  finds the 2.4 GHz side by itself.

### Other browsers

- Firefox can do it from version 151, released in May 2026, on a desktop or
  laptop. It asks your permission twice and the first prompt is a confusing
  one, so it is the harder road rather than a broken one.
- **Safari cannot do this at all**, and as of September 2026 neither can any
  browser on an iPhone or an iPad. On a Mac, use Chrome or Edge.
- Chrome on Android has had the same feature since version 148, in May 2026.
  Nobody has installed a board from a phone with this page yet, so treat it as
  untried.

If the installer says your browser cannot do it, the browser is the thing to
change. Nothing else on this page will help.

## When the board does not appear

In the order worth trying.

1. **Change the cable.** A charge-only cable is the cause more often than
   everything below put together. A cable you have used to move files off a
   phone is known good; one that came in the box with something is not.
2. **Close whatever else is using the port.** Serial monitors hold it open.
3. **Try the other USB socket**, and prefer one on the computer itself over a
   hub or a monitor.
4. **Install the USB-serial driver.** The ESP32 does not talk USB itself.
   A second chip on the board does, usually the small square one next to the
   USB socket. Most boards use a
   [CP210x](https://www.silabs.com/software-and-tools/usb-to-uart-bridge-vcp-drivers)
   or a [CH340](https://www.wch-ic.com/downloads/CH341SER_ZIP.html); newer
   ones often use a [CH9102](https://www.wch-ic.com/downloads/CH343SER_ZIP.html).
   Linux usually has the driver built in; Windows and macOS sometimes need
   the download.
5. **On Linux, give yourself the serial port.** Your user has to be in the
   group that owns it, which on most systems is `dialout`. Run
   `sudo usermod -a -G dialout $USER`, then log out and back in.
6. **Hold the BOOT button** while you pick the port, and let go once the page
   has read the chip. Boards that cannot be put into their flashing mode over
   the cable need this, and it does no harm on the ones that can.
7. **Use a powered hub or a different port** if the board drops off partway
   through. A board that disconnects at the same point every time is usually
   short of power rather than broken.

If you press the button and pick nothing, the installer shows its own list of
these, with the same drivers linked.

## The erase question

When you press **Install on a new board** and the page does not recognise the
board, it shows a box headed **Start fresh?** with one checkbox, **Erase
everything first**, and the box starts **unticked**. One of the two answers
cannot be undone, so read this before you press the button.

- **Tick it if this is a new board**, or one that has been running something
  else. A full erase clears the chip completely: any other firmware, anything
  it had stored, the lot. It also gives the BBS a clean chip to lay its
  partitions out on, which a first install wants.
- **Leave it unticked if the board already runs this BBS** and you are moving
  it to a newer version. The firmware and the screens are rewritten and
  nothing else. Your accounts, your settings, your chat mail and your
  directory listing live on a separate part of the flash that is not written
  to at all. Neither is the caller log, which has a part of its own because it
  is the sysop's record of who called. The SD card is never touched.

**Update my board** never shows this question and never erases, whether the
page recognises the board or not: it always does the second of those two
things, new firmware and screens, accounts left alone. So does **Install on a
new board** for a board the page recognises, which it offers **Update
unleashed BBS**.

> When the board already runs the version on offer, **Install on a new board**
> shows **Erase User Data**. **Update my board** does not offer it. It is not
> a small reset: it erases the whole chip,
> accounts, settings, mail and Wi-Fi included, and installs the BBS again from
> nothing. Nothing on this page can put back what an erase removed. If the
> board holds something you care about, copy it off first.

The one exception to the update rule is a release that moves a partition. That
has happened twice, at versions 0.14 and 0.17. Those need the full erase and
take the accounts with them. If it happens again, the release notes will say
so plainly, along with what to do.

## Where your Wi-Fi password goes

The board has no screen and no keyboard, so it is told which network to join
over the same cable you installed it with. The name and password go from your
computer, down the cable, to the board, and nowhere else. This site never sees
them and has nowhere to put them if it did.

The board keeps them in its own settings, on the part of the flash an update
does not touch, which is why an update does not ask again. It keeps them as
you typed them, so a backup of the board's settings holds your Wi-Fi password
too. Keep backups somewhere private.

## After it boots

The board joins your network and listens for calls on port 6400. The activity
LED holds on for a second once it is listening. In your router's list of
connected devices it is called `unleashed`.

[Call it with any telnet client](/terminals). The board works out what it is
talking to when you connect, so SyncTERM, PuTTY, a Commodore 64 through a
TeensyROM and a VT220 on a serial adapter each get a screen drawn for them. If
this is your first time, [what to expect on a first call](/firstcall) takes two
minutes to read.

## The sysop password

A new board has one password, the sysop's, and it is `unleashed`. The sysop is
whoever runs the board: the person who can change every setting on it.

That password is written here, on a page anybody can read, so on its own it
protects nothing, and the board treats it that way. It only works from your
own network, from a computer on the same Wi-Fi or wired network as the board,
and only until you change it. While it is still set, the board will not put
itself on this directory.

You take the board over on your first call:

::: art
install-setup
:::

1. From a computer on the same network, [call the board](/terminals).
2. Sign up for an account, or log in if you already have one. The board says
   **This board has not been set up yet** and asks for the **Sysop
   password**. Type `unleashed`. A wrong one asks again; ESC skips it, and
   `BYE unleashed` at the prompt, from the same network, does it later.
3. A screen headed **YOU ARE THE SYSOP** explains what comes next, and the
   **staff passwords** form opens by itself. Choose a sysop password of your
   own and press F1 to save it. The board refuses `unleashed` here. Choose one
   you use nowhere else: calls to a BBS are not encrypted, and [the privacy
   page](/privacy) says what that means in plain terms.
4. A short tour of the other settings follows, and then you are at the sysop's
   prompt. [Set up your BBS](/setup) is the long version of that tour.

> **Change it before anything else.** Do not [forward the port](/forward) and
> do not turn on the directory listing until you have. "Only from your own
> network" is a guard, not a wall: the board goes by the address a call arrives
> from, and some routers rewrite forwarded traffic so that a caller from
> outside arrives with an address from inside. On a router like that, an open
> port and the default password would let a stranger in as the sysop. A
> password of your own closes that, whatever the router does.

## Changing the Wi-Fi later

A new router, a new password, or the board moving to somebody else's house:

1. Plug the board into a computer with the same kind of cable.
2. Open this page and press **Update my board**, which cannot erase anything.
3. Pick the port. The page recognises the board and shows **Change Wi-Fi**,
   or **Connect to Wi-Fi** if the board is not on a network right now.
4. Choose the network and type the password, as before.

Nothing else on the board changes. The board only moves to the new network if
it can get on it; if it cannot, it keeps the one it had.

## If something goes wrong, reset rather than reflash

A mistake while setting a board up does not mean starting again. Most are put
right with a reset, and your accounts and settings stay where they are.

- **The wrong Wi-Fi network, or its password typed wrong.** Do what
  **Changing the Wi-Fi later** says, above. This works while the board is
  failing to join one, because it listens on the cable for as long as it is
  running, and nothing on the board is erased.

<!-- The CONFIG Wi-Fi fallback and the BOOT button reset ship in firmware 1.1.0. 1.0.2 is the restore security fix and has neither, so this block shows by itself once a 1.1.0 release is on disk and not before (site 1.1.0; it was gated on 1.0.2). Copy from the firmware repo's internal/copy-1.1.0-2026-09-23.md section 6: the directory warning sits above step 1 so it is read before anybody starts counting. -->
::: from 1.1.0
- **A network changed in CONFIG that does not work.** If the board cannot get
  on it within a minute of starting, it goes back to the last network that
  worked, so a typo in CONFIG does not leave it stranded.
- **The BOOT button.** For a forgotten sysop password, or a board you want
  back to how it arrived. The order matters:

> A factory reset also takes the board off this directory. The listing is
> tied to the board's settings, which the reset erases, so afterwards the
> directory sees a new board: three hours before it is listed again, like
> the first time. Restore a backup taken before the reset, within four
> days, and the listing carries on where it was.

1. Press and let go of **RESET**, which many boards label EN or RST.
2. Then press **BOOT** and keep holding it. Holding BOOT while RESET is let go
   starts the chip's own flashing mode instead, which is why RESET comes first.
3. Let go when the activity LED shows the stage you want.

::: art
boot-button
:::

- **Under 7 seconds**, the LED blinks slowly, and letting go does nothing.
- **7 to 15 seconds**, the LED flashes rapidly, as a warning. Letting go puts
  the sysop password back to the published default. Accounts, forums, mail and
  settings are kept, and you take the board over again as on the first call.
  Until you choose a new password, the board keeps itself off the
  directory.
- **15 to 20 seconds**, the LED stays on. Letting go is a factory reset:
  the accounts, the settings, the Wi-Fi, the mail and the logs are wiped,
  and the screens, the firmware and the SD card are kept. The board starts
  again like a fresh install, waiting for this page's Wi-Fi step, and it
  is no longer on the directory unless you restore a backup.
- **At 20 seconds** the LED goes off and the reset is abandoned. Letting go
  does nothing.
:::

- **Last of all, press Install on a new board and tick Erase everything
  first.** That puts the chip
  back to nothing before the firmware goes on, so it takes the accounts, the
  settings, the mail and the caller log with it. **The erase question**,
  above, has the details.

## Doing it the other way

The browser is the short path, not the only one. The same firmware is a
`git clone` and a `pio run -t flashall` away, which is the route you want once
you start changing things. [The build page](/build) has it, along with the
hardware, the SD card and how to put the board on the internet.

The source is at
[github.com/rwmech/unleashed_BBS](https://github.com/rwmech/unleashed_BBS),
GPL v2 or later. Anything this page installs, you can build yourself and check.

::: installer-terms
:::

## Then

- [Set up your BBS](/setup): every setting, page by page, all of it from the
  board with `CONFIG`.
- For callers from outside your own network, [forward port 6400](/forward) on
  your router, once the sysop password is yours. That page covers the common
  routers step by step, and says what it opens before it says how.
