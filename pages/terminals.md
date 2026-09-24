# Terminal software

What you call a board with. Any telnet client works, but some are built for
this and look a great deal better doing it.

::: art
term-modern
:::

## Just tell me what to install

**[SyncTERM](https://syncterm.bbsdev.net/)**, on Windows, macOS or Linux. It is
made for calling boards: it speaks ANSI and CP437 properly, handles file
transfers, keeps a dialling directory, and understands `telnet://` links so
clicking an address on this site actually works. If you install one thing,
install this.

On a phone,
**[TERMinator](https://play.google.com/store/apps/details?id=com.terminator.android)**
on Android and
**[MuffinTerm](https://apps.apple.com/us/app/muffinterm/id1583236494)** on iOS
and macOS both do the job and render ANSI art correctly.

A Chromebook is the one machine where none of that installs straight into the
browser. It can call a board through its Linux environment or an Android app,
and on a school or work Chromebook both are settings somebody else owns. It has
its own section further down.

## The rest of the modern options

| Client | Platform | Worth knowing |
|---|---|---|
| [SyncTERM](https://syncterm.bbsdev.net/) | Windows, macOS, Linux | The default recommendation. ANSI, CP437, transfers, dialling directory. |
| [NetRunner](https://www.mysticbbs.com/downloads.html) | Windows, Linux | From the Mystic BBS author. Good ANSI. No Mac or Android build. |
| [mTelnet](https://mt32.bbses.info/) | Windows | Small, fast, built for BBSes. |
| [MuffinTerm](https://apps.apple.com/us/app/muffinterm/id1583236494) | iOS, macOS | Handles PETSCII as well as ANSI. |
| [TERMinator](https://play.google.com/store/apps/details?id=com.terminator.android) | Android, ChromeOS with the Play Store | CP437 art, classic fonts, ZMODEM transfers. |
| [PuTTY](https://www.chiark.greenend.org.uk/~sgtatham/putty/) | Windows, Linux | Everywhere already, but set the character set to CP437 or the art will be wrong. Not built for this. |
| `telnet` | Linux, macOS, BSD | `telnet unleashed.local 6400`. Fine and plain. On Debian or Ubuntu: `sudo apt -y install inetutils-telnet`. |
| `nc` | anywhere | `nc host 6400`. Works, negotiates nothing, and looks it. |

macOS removed its `telnet` command in High Sierra. Install SyncTERM or
MuffinTerm rather than fighting it.

Windows has a Telnet Client too, but it is an optional feature that is off by
default and it renders ANSI poorly. Use something else.

> Whatever you use, remember what you are using it for. Telnet carries every
> keystroke in the clear, including your password. Never reuse a password on a
> telnet board. [What that risks](/privacy).

## Chromebooks

::: art
term-chromebook
:::

A Chromebook you control can usually call a board. A school or work
Chromebook usually cannot, until whoever manages it switches something on.
Chrome on its own never can: no web page and no Chrome extension is allowed to
open the kind of plain network connection telnet needs, so every route below
goes around the browser rather than through it. On a managed Chromebook, every
one of those routes is a setting that belongs to the administrator.

**Find out which kind of Chromebook you have before anything else**, because
it changes the answer. Select the time at the bottom right, then **Settings**,
then **About ChromeOS**, then **Developers**. If there is a **Linux
development environment** row with a **Set up** button, you are fine. If the
row is missing, or the button refuses, the device is managed and an
administrator has turned it off. [A few older Chromebooks never had
it](https://www.chromium.org/chromium-os/chrome-os-systems-supporting-linux/).

### If Linux is available

This is the route that works, and it ends with an ordinary terminal.

1. Select the time at the bottom right, then **Settings**, then **About ChromeOS**, then **Developers**.
2. Next to **Linux development environment**, select **Set up**, and answer the few questions it asks. Google says setup takes ten minutes or more, and that is about right.
3. A **Terminal** window opens when it finishes. What you are looking at is Debian.
4. Install a telnet client: `sudo apt -y install inetutils-telnet`
5. Call a board: `telnet 192.168.1.50 6400`, with the address and port from the listing.

Use the numeric address rather than a `.local` name. The Linux side looks
names up for itself and does not always see what ChromeOS can see, so a name
that works in the browser can fail in the terminal for reasons that have
nothing to do with the board.

### If Linux is blocked

Then it is a conversation with whoever manages the devices, and it goes better
if you ask for the setting by name instead of asking for Linux.

- It lives in the Google Admin console, under **Devices > Chrome > Settings**, on the **User & browser settings** page, in the section **Virtual machines (VMs) and developers**.
- The setting is called **Linux virtual machines (BETA)**. On managed devices it defaults to **Block usage for virtual machines needed to support Linux apps for users**, which is why yours is off.
- The value to ask for is **Allow usage for virtual machines needed to support Linux apps for users**. It can be set for one group of people rather than for everybody.
- If people sign in with accounts from outside the organisation's own domain, the matching setting on the **Devices** page, **Linux virtual machines for unaffiliated users (BETA)**, has to be allowed too, or the first one appears to do nothing.

> [!NOTE]
> Worth saying in that conversation, because it is usually the real question:
> this starts a sandboxed Debian container. It is not developer mode, it does
> not unenrol the device, and by Google's own description a bad Linux app can
> affect other Linux apps and nothing outside them.

### The other ways in, and what each costs

- **An Android app, if the Play Store is switched on.** [TERMinator](https://play.google.com/store/apps/details?id=com.terminator.android) is a BBS terminal that speaks telnet and draws CP437 art properly. On a managed Chromebook the Play Store is its own separate setting, under **Devices > Chrome > Apps & extensions > User app settings**, then **Additional app settings**, then **Android apps on Chrome Devices**, then **Allow users to install Android apps**. On school devices it is frequently off, and it is a bigger thing to ask for than Linux is, because it opens a whole store rather than one program.
- **A Chrome extension cannot do this**, and that is worth knowing before you spend an afternoon looking for one. Google's own Secure Shell is an SSH client and does not speak telnet. Nothing else can either: opening a plain connection was a Chrome Apps ability, not an extension one, and ChromeOS 138, in July 2025, was the last release to support Chrome Apps a user installed themselves. Google's newer route for web apps that need a raw connection, Isolated Web Apps, installs only through an administrator's policy, so it is the administrator's decision like everything else here.
- **A terminal that runs in a web page needs a helper in the middle.** A page cannot open a telnet connection, so clients like [fTelnet](https://www.ftelnet.ca/) connect over WebSocket to a proxy and the proxy makes the telnet connection for them. It works. It also means that proxy reads everything in both directions, which on a telnet board is everything, your password included. Running the proxy yourself on your own network is a fair trade. Using somebody else's is a public conversation with one more listener in it.

If none of those is available to you, a Chromebook cannot call a board, and
there is no trick that gets round it. The machine is doing exactly what it was
set up to do. Borrow a Windows, Mac or Linux computer for the evening, or ask
for the Linux setting, which is the smallest of the three requests.

## Clicking an address instead of typing it

Every board on the list has its address as a link. Whether that link does
anything depends on which program your computer has registered for
`telnet://`, and the default is often wrong or missing. [How to fix
that](/dialing).

The address is ordinary text inside the link, on purpose, so selecting it and
pasting it into a terminal always works, whatever your machine does.

## Calling from something older

This is the more interesting half. A board answers anything that can open a
telnet session, and with a bridge that includes machines built before the
protocol was common.

### Commodore

::: art
term-commodore
:::

| Machine | Software | Onto the wire |
|---|---|---|
| C64, C128 | [CCGMS](https://github.com/mist64/ccgmsterm), [Novaterm](https://commodore.software/downloads/download/19-novaterm/653-novaterm-9-6c), [DesTerm 128](https://csdb.dk/release/?id=171068) | [TeensyROM](https://github.com/SensoriumEmbedded/TeensyROM), [WiModem232](https://www.cbmstuff.com/index.php?route=product/product&path=66&product_id=113), [Comet64](https://www.commodoreserver.com/ProductView.asp?PID=365065CF529B4C408F7D01C08BA34803), [Zimodem](https://github.com/bozimmerman/Zimodem), or an RS-232 cartridge |
| VIC-20, PET, Plus/4 | period terminal software | a user-port RS-232 interface to a bridge |

The board speaks PETSCII natively, at 40 or 80 columns. A Commodore does not
answer the board's probe the way a PC terminal does, so on connect the board
asks you to press DEL, then whether you are on 40 or 80 columns. A C64 gets a
C64 screen, not an approximation of one.

### Atari

::: art
term-atari
:::

| Machine | Software | Onto the wire |
|---|---|---|
| Atari 8-bit | [BobTerm](https://archive.org/details/a8b_misc_bobtrmxp), [Ice-T](https://github.com/itaych/Ice-T) | [FujiNet](https://fujinet.online/atari-8-bit/), or an 850 interface to a bridge |
| Atari ST, Falcon | [UniTerm](https://www.atarimania.com/utility-atari-st-uniterm_33343.html), [CoNnect](https://www.atariuptodate.de/en/984/connect) | the built-in serial port to a bridge |

### Apple and Amiga

::: art
term-apple-amiga
:::

| Machine | Software | Onto the wire |
|---|---|---|
| Apple II, IIgs | [ProTERM](https://en.wikipedia.org/wiki/ProTERM), [ASCII Express](https://en.wikipedia.org/wiki/ASCII_Express), [Spectrum](https://speccie.uk/software/spectrum/) | [Uthernet II](https://a2retrosystems.com/products.htm), or a Super Serial Card to a bridge |
| Classic Mac | [ZTerm](https://www.dalverson.com/zterm/), [White Knight](https://www.macintoshrepository.org/33223-white-knight) | the modem or printer port to a bridge |
| Amiga | [NComm](https://aminet.net/package/comm/term/ncomm307), [term](https://aminet.net/package/comm/term/Term), [JR-Comm](https://archive.org/details/JR-Comm_v1.02_1991_Radigan_John) | the serial port to a bridge, or a TCP/IP stack |

### Everything else

::: art
term-others
:::

| Machine | Software | Onto the wire |
|---|---|---|
| TRS-80 Model 100 | the built-in TELCOM | the RS-232 port to a bridge |
| MSX | [TELNET for UNAPI](https://github.com/ducasp/MSX-Development/tree/master/UNAPI/TELNET) | an ethernet or Wi-Fi UNAPI cartridge |
| ZX Spectrum | [VTX 5000](https://spectrumcomputing.co.uk/entry/11152/ZX-Spectrum/VTX_5000_User_To_User_Communications_Software), [Spectranet](https://spectrum.alioth.net/doc/index.php/Spectranet) clients | a Prism VTX 5000 or a [Spectranet](https://github.com/spectrumero/spectranet) card |
| Amstrad CPC | [EwenTerm](https://ewen.mcneill.gen.nz/programs/cpc/ewenterm/) | a serial interface to a bridge |
| CP/M, S-100 | [Kermit](https://www.kermitproject.org/cpm.html), [MEX](http://www.zimmers.net/anonftp/pub/cpm/comm/mex/index.html) | the machine's serial port to a bridge |
| DOS | [Telix](https://en.wikipedia.org/wiki/Telix), [Procomm Plus](https://en.wikipedia.org/wiki/Datastorm_Technologies), [Qmodem](https://en.wikipedia.org/wiki/Qmodem), [Terminate](https://en.wikipedia.org/wiki/Terminate_%28software%29) | a packet driver and a TCP/IP stack, or a serial bridge |

### Actual terminals

::: art
term-terminals
:::

| Terminal | Onto the wire |
|---|---|
| [DEC VT100](https://en.wikipedia.org/wiki/VT100), [VT220](https://en.wikipedia.org/wiki/VT220), [VT320](https://en.wikipedia.org/wiki/VT320) | a terminal server, a USB serial adapter, or the board's own serial bridge |
| [Wyse WY-60](https://terminals-wiki.org/wiki/index.php/Wyse_WY-60), [Televideo 925](https://terminals-wiki.org/wiki/index.php/TeleVideo_925), [ADM-3A](https://en.wikipedia.org/wiki/ADM-3A), [Heathkit H19](https://terminals-wiki.org/wiki/index.php/Heathkit_H19) | the same |
| [Teletype Model 33 ASR](https://en.wikipedia.org/wiki/Teletype_Model_33) | a current loop converter, at 110 baud, if that is the sort of thing you enjoy |

## What a bridge is

::: art
term-bridge
:::

Most of the machines above have a serial port and no idea what TCP is. A bridge
sits between the two: it takes the serial line on one side and speaks telnet on
the other, so the old machine thinks it is talking to a modem.

Hardware ones for Commodore and Atari are listed above. On anything with a
serial port, a Raspberry Pi running `tcpser`, or an ESP32 running
[Zimodem](https://github.com/bozimmerman/Zimodem), does the same job for a few
dollars. A real modem and a real phone line also still work, if you have both.

## What the board does with all this

It works out what it is talking to when you connect and draws itself to
suit, so a C64 and a modern laptop can be in the same chat room and both see
something that looks right to them. [Your first
call](/firstcall#it-works-out-what-you-are) says how, and what it may ask.
