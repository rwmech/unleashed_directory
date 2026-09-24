<!-- The lights build page (site 1.2.1, Rob: "one for the LED installs for a 10p and 1p LEDs the exact same way" as /sdcard). Every fact is the firmware's, at 1.1.0-dev.9: src/plugins/lights.h and lights.cpp (the word lists, the pins -1 to 33, 16 pixels at most, 10 as shipped, brightness 10), COMMANDS.md "lights" (the effects, the colours, Power, the refused pins, GPIO13, the example strip pin 14), CHANGELOG 1.1.0-dev.4 and dev.8. The electrical advice is Rob's, settled in the firmware's CLAUDE.md: 5 V pixels on a 3.3 V data pin with no level shifter, a 330 to 470 ohm resistor at the pixel, 100 nF across its supply, and a strip of ten on a supply of its own. Not stated here on purpose: what CONFIG does with a brightness over 30. COMMANDS.md says it asks first, and at dev.9 the CONFIG rows still stop at 30; say it once 1.1.0 is released and the two agree. -->
# Lights

> [!NOTE]
> **The Waveshare S3 needs none of this.** Its drive light is the LED on the
> board, and its screen draws the strip: [the S3](/hardware#waveshare-esp32-s3-lcd-1-47).

Two lights for an ESP32 dev board in a case: a drive light, one pixel that
shows the board's storage at work, and a strip of pixels, ten as shipped, that
shows who is on. Both are optional, and both stay off until you give them a
pin.

::: until 1.1.0
> [!NOTE]
> **The lights arrive with firmware 1.1.0**, which is not released for the
> ESP32 dev board yet. Wiring them now does no harm: they light up once the
> board runs 1.1.0.
:::

## What you need

- **WS2812B pixels**, the kind sold as NeoPixels: one for the drive light, and
  a strip of 1 to 16 for the strip. The common 5 V ones take their data
  straight from the board's 3.3 V pin, with nothing in between.
- **A 330 to 470 ohm resistor** for each, in the data line at the first pixel.
  It keeps the signal clean on a length of wire.
- **A 100 nF capacitor** for each, across the pixel's 5 V and ground.
- **For the strip, a 5 V supply of its own**, rated 1 A or more.
- Jumper wires.

## The drive light

One pixel. Amber when the SD card is read or written, cool white for the
board's own flash, a slow red blink after a storage error, and a dim glow in
between. Every flash is held long enough to see, so a read that takes two
milliseconds still shows.

::: art
lights-drive
:::

| Pixel pin | ESP32 pin | Notes |
|---|---|---|
| `5V` or `VCC` | `VIN` | The 5 V from USB. One pixel draws at most about 60 mA, which it handles |
| `GND` | `GND` | |
| `DIN` | `D13` / GPIO13 | Through the resistor. GPIO13 has no job at boot |

It has four styles, and the colours are the same in each:

- `pc`, as shipped: a short flash on each access and a flicker through a long
  one, like an IBM PC/XT.
- `1541`: lit for the whole access, like the Commodore drive.
- `disk2`: lit for about a second after the last access, like the Apple II
  Disk II, whose motor kept running.
- `breathe`: a slow pulse at rest, with the access colour on top.

## The strip

1 to 16 pixels, 10 as shipped, which is one for each caller line.

> **Give the strip a 5 V supply of its own.** Ten pixels at full white draw
> about 600 mA, and the board needs up to about 400 mA of its own when its
> radio transmits. That is more than a USB port gives: the voltage sags, the
> board restarts, and the port may cut the power altogether. Join the
> supply's ground to the board's ground, connect ground first, and disconnect
> it last.

::: art
lights-strip
:::

| Strip pin | Goes to | Notes |
|---|---|---|
| `5V` | the supply's + | Not the board's VIN |
| `GND` | the supply's - and the board's `GND` | Without the shared ground the data has nothing to be measured against |
| `DIN` | `D14` / GPIO14 | Through the resistor, at the first pixel |

What it shows:

- `nodes`, as shipped: a pixel for each caller line, dark while it is free,
  in the caller's colour from `WHO` while somebody is on, and flickering with
  their traffic.
- `hayes`: a Hayes Smartmodem's front panel on the first eight pixels, from
  the board's real state.
- `blinken`: a front panel's lamps, changing faster the busier the board is.
- `scanner`, `c64`, `boing`, `rainbow`: a sweep, the Commodore badge stripes,
  the Amiga ball, the colours.
- `vu`: the board's traffic as a bar, green, then yellow, then red.
- `wifi`: the board's Wi-Fi signal as a meter, like the bars on a phone.
- `manual`: each pixel its own effect and colour.
- `off`.

## Telling the board about it

Log in as the sysop and type `CONFIG lights`. Switch the plugin on, set
**Drive pin** to 13 and **Strip pin** to 14, and **Strip len** to the number
of pixels you have. Saving puts it live. Or in the file:

```
[plugin:lights]
enabled     = yes
drive_pin   = 13
strip_pin   = 14
strip_count = 10
```

Then type `LIGHTS TEST`. Every pixel shows red, green, blue and then white, a
second each. `LIGHTS` on its own shows each output's pin, effect, brightness
and colour order, and the colours it last sent.

Brightness is a percentage for each output, 10 as shipped. Past 30 is your
call, and it is where the strip's draw goes past what USB gives, which is what
the separate supply is for.

## When it does not work

| What you see | What it usually means |
|---|---|
| Nothing lights | The plugin is off, or the pin is still `-1`. `LIGHTS` shows both |
| Green where the test shows red first | The pixels send their colours in another order. Set **Strip ord** or **Drive ord** to `RGB`, or try `BRG` |
| Random colours, or flicker | The grounds are not joined, or the resistor is missing. A larger capacitor across the strip's supply, 500 to 1000 microfarads, helps a strip that flickers when it changes colour |
| The board restarts when the strip lights up | The strip is running from USB. Give it its own supply |
| The SD card or the blue LED stops working | A lights pin took one of theirs. Keep clear of 2 (the activity LED), 0 (the BOOT button) and the card's 5, 18, 19 and 23 |

The board refuses a pin the flash uses (6 to 11) and one the chip does not
have (20, 24 and 28 to 31), and the two outputs cannot share a pin. Nothing
yet stops a pin taking one the board already uses, which is what the last row
is about.
