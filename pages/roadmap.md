<!-- The roadmap (site 1.2.4, Rob: "a roadmap page in there with fancy line art graphics of our current roadmap in non-technical user format"). Only what is decided, and no dates. Sources, all in the firmware repository as of 2026-09-24: CHANGELOG.md for what is done (the installer from 0.23.0 and 1.0.0; the S3 and its screen, 1.1.0-dev.8 and dev.10; lights, dev.4; SD backups and restore, dev.6 and dev.9; 80-column forms, dev.12, and 80-column lists since 0.17.10); CLAUDE.md for what is next and later (silent mode and missed sysop pages to one account in the 1.1.0 lane notes; the camera boards, internal/PLAN-freenove-cam.md; the network update, "Queued for 1.1.0 ... the board updates itself", placed under Later in Rob's brief for this page; SSH on the S3, "Queued as an S3 option, not started", and since site 1.3.3 in firmware 1.2.0, Rob's version, 2026-09-25; sensors and camera triggers under the GPIO plugin; doors on a second board over serial; board linking, DDial style). Nothing private, and nothing Rob rejected (no captive portal, no Lua doors, no Home Assistant or MQTT). The drawing is ROADMAP in server.py: change a station there and here together. -->
# Roadmap

Where µnleashed has got to and where it goes next, in plain words and with no
dates. Every station on the line is decided; nothing on it is a maybe.

::: art
roadmap
:::

Done means built and working on a board. Some of it reaches the ESP32 dev
board with firmware 1.1.0, together with everything under Now.

## Done

- **[A browser installer](/install).** Plug a board into a computer, press a
  button, and a few minutes later it is a BBS on your Wi-Fi. No toolchain, no
  command line.
- **[An S3 board with its own screen](/hardware#waveshare-esp32-s3-lcd-1-47).**
  A USB stick with a colour screen that shows who is on, the address to dial
  and how long the board has been up.
- **[Lights](/lights).** An optional drive light that flickers as the board works, and a
  strip of pixels that lights up as callers arrive. A board in a case looks
  alive.
- **[Backups to the SD card](/sdcard).** Every night once you switch them on,
  and a restore from the card that waits until nobody is on.
- **80-column screens.** Forms, lists and menus use the whole width of a PC
  terminal, while a 40-column machine keeps a layout made for its screen.

## Now, with firmware 1.1.0

- **The sysop's dashboard.** The live view of the board, laid out for the
  screen it is on, 40 columns or 80.
- **Silent mode.** One switch, or a set of quiet hours, turns off every light
  the board controls, the S3's screen included, for a board that lives in a
  bedroom. (The power light is wired to the supply, and only tape stops that
  one.)
- **[Camera boards](/camera).** Boards with a camera on them. A caller types
  `SNAPSHOT` and downloads the picture.
- **Missed pages go to mail.** Ring for the sysop when nobody answers, and your
  note is waiting in the sysop's mail.

## Later

- **The board updates itself.** It fetches a new version, checks that it is
  genuine, and puts it on when the sysop says yes. No USB cable.
- **An encrypted way in, on the S3 boards, in firmware 1.2.0.** [[SSH]] beside telnet, for
  callers whose machines can do it, on the [Waveshare and the S3 camera
  board](/hardware#waveshare-esp32-s3-lcd-1-47). Telnet stays, for the machines that cannot, and
  [the privacy page](/privacy) says why that matters.
- **Sensors.** Temperature, humidity, light, motion and switches on the board's
  pins, named and shown on screen without writing any code.
- **Motion-triggered snapshots.** A motion sensor sees a visitor at the feeder,
  and the camera takes its picture by itself.
- **Doors on a second board.** Programs a caller can go into, running on a
  second small board plugged into the first, the way big BBSes once ran their
  doors on machines of their own.
- **Linked chat, one superchat.** Chat rooms joined across boards, the way
  [Diversi-DIAL](https://www.ddial.com/archives.php) linked its systems, so a
  quiet board borrows company from a busy one: µnleashed boards, and
  Diversi-DIAL and GTalk-style systems, in one room.

Want to be on the air when the next station opens? A board takes an
afternoon, and most of that is deciding what to call it.

::: next
[Build one](/build)
:::
