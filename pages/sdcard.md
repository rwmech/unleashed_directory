# Adding an SD card

Optional. A board with no card is a complete board: chat, mail, accounts,
screens, the caller log, a directory listing, the serial bridge. The card is
what you add when you want file areas, forums and screens of your own.

Four wires and a module that costs about two dollars.

## What you need

- A micro SD card module with an SPI breakout. The pin names below are the
  ones the common modules print on the board.
- A micro SD card, 32 GB or smaller, formatted **FAT32**.
- Four jumper wires, plus two for power.

> Cards larger than 32 GB ship formatted as exFAT, which this does not read.
> Reformat as FAT32 or use a smaller card. Windows will not offer FAT32 above
> 32 GB in the right-click Format dialog, and `diskpart` refuses it as well.
> Windows 11 with the April 2026 update or later can do it from a terminal,
> with `format X: /FS:FAT32` where X is the card's drive letter; otherwise a
> smaller card or a third-party formatter.

## The wiring

::: art
sd-wiring
:::

| Module pin | ESP32 pin | Notes |
|---|---|---|
| `3V3` or `VCC` | `3V3` | **Start on 3V3.** Some modules want 5 V: see below. |
| `GND` | `GND` | |
| `CS` or `SS` | `D5` / GPIO5 | Change it in the config if you need to |
| `MOSI` or `DI` | `D23` / GPIO23 | |
| `SCK` or `CLK` | `D18` / GPIO18 | |
| `MISO` or `DO` | `D19` / GPIO19 | |

> Use the 3V3 pin to start with. It is the choice that cannot damage anything:
> a module with no regulator on it needs 3.3 V, and 5 V on one of those goes
> straight to the card and can reach the ESP32's pins, which are not built for
> it. The common blue module with a small three-legged regulator on it, often
> marked AMS1117, is the exception: it is designed for 5 V on VCC, and from 3V3
> its card can end up short of the voltage it needs and fail to mount. If that
> is your module and it will not mount on 3V3, move VCC to the 5 V pin, which is
> VIN on most dev boards. Its regulator and level shifter keep the card and the
> signals at 3.3 V. Only do that if you can see the regulator on the module.

GPIO5 is one of the ESP32's strapping pins, but the only thing it sets at
power-on is the timing of an SDIO interface this board does not use, so a card
module on it does not stop the board booting. If you would rather CS were on a
pin with no strapping role at all, move it to `D4` and set `cs = 4` in the
config. Nothing else needs to change.

## Telling the board about it

Nothing, if you used the pins above. Wire it up, power cycle, and it mounts
at boot.

To check, log in as sysop and type `SD`:

```
SD card
  SDHC/SDXC at /sd, 20 MHz
  29123 MB free of 30436 MB
  screens: /sd/screens
```

If you moved a pin, `CONFIG` has an `sd` page with all four, or edit the
section directly:

```
[plugin:sd]
cs = 4
mosi = 23
clk = 18
miso = 19
screens = yes
```

## When it does not work

`SD` says which problem it is, in the board's own words.

| What it says | What it usually means |
|---|---|
| no card found | The card is not seated, or `CS` is on the wrong pin, or `MISO`/`MOSI` are swapped |
| card found but no FAT filesystem | It is exFAT or NTFS. Reformat as FAT32 |
| card answered then failed | The card started to talk and then stopped. Check the power line and the ground, and see the note above about modules with a regulator. `CONFIG sd` can also lower the bus speed |
| SPI bus would not start | A pin number in the config is one the board cannot use |

`SD MOUNT` tries again without rebooting. It pauses the whole board for a
moment while it negotiates with the card, which is why it is a command you
type rather than something that retries by itself.

`SD UNMOUNT` flushes and releases the card so you can pull it safely.

## What goes on the card, and what does not

| On the card (FAT32) | On the board (LittleFS) |
|---|---|
| File areas | Accounts and passwords |
| Forums | The configuration |
| Your own screens | The caller log |
| A copy of the caller log | The stock screens |

The split is deliberate. FAT32 is readable on any laptop, which is the whole
point of using it: pull the card, plug it into a PC, and your board's files
are ordinary files. The cost is that FAT is not safe against losing power
mid-write, so nothing that has to survive lives there. Accounts stay on the
board's own flash, which is.

Pulling the card does not break the board. It goes back to the stock screens,
and the file areas and forums are not available until the card is back.

## Screens of your own

Put a screen in `/sd/screens` with the same name as a stock one and yours is
used instead. A name the card does not have falls back to the one that
shipped, so you can replace a single screen without supplying all of them.

The file extensions are the same as on the board: `.ans` for ANSI, `.asc` for
plain ASCII, `.seq` for PETSCII, and `.p40` or `.p80` for a PETSCII screen
drawn for 40 or 80 columns.

Set `screens = no` in the config if you would rather the card were ignored
for this.
