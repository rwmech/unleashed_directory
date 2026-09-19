# Terminal software

What you call a board with. Any telnet client works, but some are built for
this and look a great deal better doing it.

## Just tell me what to install

**[SyncTERM](https://syncterm.bbsdev.net/)**, on Windows, macOS or Linux. It is
made for calling boards: it speaks ANSI and CP437 properly, handles file
transfers, keeps a dialling directory, and understands `telnet://` links so
clicking an address on this site actually works. If you install one thing,
install this.

On a phone, **[NetRunner](https://www.mysticbbs.com/downloads.html)** on Android
and **[MuffinTerm](https://apps.apple.com/us/app/muffinterm/id1583236494)** on
iOS and macOS both do the job and render ANSI art correctly.

## The rest of the modern options

| Client | Platform | Worth knowing |
|---|---|---|
| [SyncTERM](https://syncterm.bbsdev.net/) | Windows, macOS, Linux | The default recommendation. ANSI, CP437, transfers, dialling directory. |
| [NetRunner](https://www.mysticbbs.com/downloads.html) | Windows, Android | From the Mystic BBS author. Good ANSI. |
| [mTelnet](https://mt32.bbses.info/) | Windows | Small, fast, built for BBSes. |
| [MuffinTerm](https://apps.apple.com/us/app/muffinterm/id1583236494) | iOS, macOS | Handles PETSCII as well as ANSI. |
| [PuTTY](https://www.chiark.greenend.org.uk/~sgtatham/putty/) | Windows | Everywhere already, but set the character set to CP437 or the art will be wrong. Not built for this. |
| `telnet` | Linux, macOS, BSD | `telnet unleashed.local 6400`. Fine and plain. On Debian or Ubuntu: `sudo apt -y install inetutils-telnet`. |
| `nc` | anywhere | `nc host 6400`. Works, negotiates nothing, and looks it. |

macOS removed its `telnet` command in High Sierra. Install SyncTERM or
MuffinTerm rather than fighting it.

Windows has a Telnet Client too, but it is an optional feature that is off by
default and it renders ANSI poorly. Use something else.

> Whatever you use, remember what you are using it for. Telnet carries every
> keystroke in the clear, including your password. Never reuse a password on a
> telnet board.

## Clicking an address instead of typing it

Every board on the list has its address as a link. Whether that link does
anything depends on which program your computer has registered for
`telnet://`, and the default is often wrong or missing. [How to fix
that](/dialing).

The address is also plain selectable text on every listing, on purpose, so
copy and paste always works no matter what your machine does.

## Calling from something older

This is the more interesting half. A board answers anything that can open a
telnet session, and with a bridge that includes machines built before the
protocol was common.

### Commodore

| Machine | Software | Onto the wire |
|---|---|---|
| C64, C128 | [CCGMS](https://github.com/mist64/ccgmsterm), [Novaterm](https://commodore.software/downloads/download/19-novaterm/653-novaterm-9-6c), [DesTerm 128](https://csdb.dk/release/?id=171068) | [TeensyROM](https://github.com/SensoriumEmbedded/TeensyROM), [WiModem232](https://www.cbmstuff.com/index.php?route=product/product&path=66&product_id=113), [Comet64](https://www.commodoreserver.com/ProductView.asp?PID=365065CF529B4C408F7D01C08BA34803), [Zimodem](https://github.com/bozimmerman/Zimodem), or an RS-232 cartridge |
| VIC-20, PET, Plus/4 | period terminal software | a user-port RS-232 interface to a bridge |

The board speaks PETSCII natively, at 40 or 80 columns, and works out which on
connect. A C64 gets a C64 screen, not an approximation of one.

### Atari

| Machine | Software | Onto the wire |
|---|---|---|
| Atari 8-bit | [BobTerm](https://archive.org/details/a8b_misc_bobtrmxp), [Ice-T](https://github.com/itaych/Ice-T) | [FujiNet](https://fujinet.online/atari-8-bit/), or an 850 interface to a bridge |
| Atari ST, Falcon | [UniTerm](https://www.atarimania.com/utility-atari-st-uniterm_33343.html), [CoNnect](https://www.atariuptodate.de/en/984/connect) | the built-in serial port to a bridge |

### Apple and Amiga

| Machine | Software | Onto the wire |
|---|---|---|
| Apple II, IIgs | [ProTERM](https://en.wikipedia.org/wiki/ProTERM), [ASCII Express](https://en.wikipedia.org/wiki/ASCII_Express), [Spectrum](https://speccie.uk/software/spectrum/) | [Uthernet II](https://a2retrosystems.com/products.htm), or a Super Serial Card to a bridge |
| Classic Mac | [ZTerm](https://www.dalverson.com/zterm/), [White Knight](https://www.macintoshrepository.org/33223-white-knight) | the modem or printer port to a bridge |
| Amiga | [NComm](https://aminet.net/package/comm/term/ncomm307), [term](https://aminet.net/package/comm/term/Term), [JR-Comm](https://archive.org/details/JR-Comm_v1.02_1991_Radigan_John) | the serial port to a bridge, or a TCP/IP stack |

### Everything else

| Machine | Software | Onto the wire |
|---|---|---|
| TRS-80 Model 100 | the built-in TELCOM | the RS-232 port to a bridge |
| MSX | [TELNET for UNAPI](https://github.com/ducasp/MSX-Development/tree/master/UNAPI/TELNET) | an ethernet or Wi-Fi UNAPI cartridge |
| ZX Spectrum | [VTX 5000](https://spectrumcomputing.co.uk/entry/11152/ZX-Spectrum/VTX_5000_User_To_User_Communications_Software), [Spectranet](https://spectrum.alioth.net/doc/index.php/Spectranet) clients | a Prism VTX 5000 or a [Spectranet](https://github.com/spectrumero/spectranet) card |
| Amstrad CPC | [EwenTerm](https://ewen.mcneill.gen.nz/programs/cpc/ewenterm/) | a serial interface to a bridge |
| CP/M, S-100 | [Kermit](https://www.kermitproject.org/cpm.html), [MEX](http://www.zimmers.net/anonftp/pub/cpm/comm/mex/index.html) | the machine's serial port to a bridge |
| DOS | [Telix](https://en.wikipedia.org/wiki/Telix), [Procomm Plus](https://en.wikipedia.org/wiki/Datastorm_Technologies), [Qmodem](https://en.wikipedia.org/wiki/Qmodem), [Terminate](https://en.wikipedia.org/wiki/Terminate_%28software%29) | a packet driver and a TCP/IP stack, or a serial bridge |

### Actual terminals

| Terminal | Onto the wire |
|---|---|
| [DEC VT100](https://en.wikipedia.org/wiki/VT100), [VT220](https://en.wikipedia.org/wiki/VT220), [VT320](https://en.wikipedia.org/wiki/VT320) | a terminal server, a USB serial adapter, or the board's own serial bridge |
| [Wyse WY-60](https://terminals-wiki.org/wiki/index.php/Wyse_WY-60), [Televideo 925](https://terminals-wiki.org/wiki/index.php/TeleVideo_925), [ADM-3A](https://en.wikipedia.org/wiki/ADM-3A), [Heathkit H19](https://terminals-wiki.org/wiki/index.php/Heathkit_H19) | the same |
| [Teletype Model 33 ASR](https://en.wikipedia.org/wiki/Teletype_Model_33) | a current loop converter, at 110 baud, if that is the sort of thing you enjoy |

## What a bridge is

Most of the machines above have a serial port and no idea what TCP is. A bridge
sits between the two: it takes the serial line on one side and speaks telnet on
the other, so the old machine thinks it is talking to a modem.

Hardware ones for Commodore and Atari are listed above. On anything with a
serial port, a Raspberry Pi running `tcpser`, or an ESP32 running
[Zimodem](https://github.com/bozimmerman/Zimodem), does the same job for a few
pounds. A real modem and a real phone line also still work, if you have both.

## What the board does with all this

It works out what it is talking to when you connect: ANSI with CP437 or UTF-8,
PETSCII at 40 or 80 columns, or plain ASCII, and draws itself accordingly. You
do not configure anything. A C64 and a modern laptop can be in the same chat
room and both see something that looks right to them.
