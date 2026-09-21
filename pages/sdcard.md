# Adding an SD card

Optional. A board with no card is a complete board: chat, mail, accounts,
screens, the caller log, a directory listing, the serial bridge. The card is
what you add when you want file areas and screens of your own. Forums
are being built now and will live on it too.

Four wires and a module that costs about two dollars.

## What you need

- A micro SD card module with an SPI breakout. The common red or blue ones
  with a 3V3 regulator and a level shifter are fine and are what the pin
  names below assume.
- A micro SD card, 32 GB or smaller, formatted **FAT32**.
- Four jumper wires, plus two for power.

> Cards larger than 32 GB ship formatted as exFAT, which this does not read.
> Reformat as FAT32 or use a smaller card. Windows will not offer FAT32 for a
> large card in the right-click Format dialog; use `diskpart`, or a smaller
> card, or a third-party formatter.

## The wiring

| Module pin | ESP32 pin | Notes |
|---|---|---|
| `3V3` or `VCC` | `3V3` | **Not VIN.** See the warning below. |
| `GND` | `GND` | |
| `CS` or `SS` | `D5` / GPIO5 | Change it in the config if you need to |
| `MOSI` or `DI` | `D23` / GPIO23 | |
| `SCK` or `CLK` | `D18` / GPIO18 | |
| `MISO` or `DO` | `D19` / GPIO19 | |

> Use the 3V3 pin, not VIN. Many modules have a regulator that will happily
> take 5 V on VIN, but plenty of the cheap ones tie the data lines straight
> through with no level shifting. Feeding 5 V logic into an ESP32 pin will
> damage it. 3V3 works on every module worth buying.

GPIO5 is a strapping pin: the ESP32 reads it at power-on to decide how to
boot. A card module holding it low at exactly the wrong moment can stop the
board booting. If your board will not start with the card attached, move `CS`
to `D4` and set `cs = 4` in the config. Nothing else needs to change.

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

`SD` tells you which of the three common problems it is.

| What it says | What it usually means |
|---|---|
| no card found | The card is not seated, or `CS` is on the wrong pin, or `MISO`/`MOSI` are swapped |
| card found but no FAT filesystem | It is exFAT or NTFS. Reformat as FAT32 |
| card would not mount | Check the 3V3 line and the ground. A module browning out looks like this |

`SD MOUNT` tries again without rebooting. It pauses the whole board for a
moment while it negotiates with the card, which is why it is a command you
type rather than something that retries by itself.

`SD UNMOUNT` flushes and releases the card so you can pull it safely.

## What goes on the card, and what does not

| On the card (FAT32) | On the board (LittleFS) |
|---|---|
| File areas | Accounts and passwords |
| Your own screens | The configuration |
| A copy of the caller log | The caller log |
| Message bases, once they are built | The stock screens |

The split is deliberate. FAT32 is readable on any laptop, which is the whole
point of using it: pull the card, plug it into a PC, and your board's files
are just files. The cost is that FAT is not safe against losing power
mid-write, so nothing that has to survive lives there. Accounts stay on the
board's own flash, which is.

Pulling the card does not break the board. It goes back to the stock screens
and the features that need the card say so.

## Screens of your own

Put a screen in `/sd/screens` with the same name as a stock one and yours is
used instead. A name the card does not have falls back to the one that
shipped, so you can replace a single screen without supplying all of them.

The file extensions are the same as on the board: `.ans` for ANSI, `.asc` for
plain ASCII, `.seq` for PETSCII.

Set `screens = no` in the config if you would rather the card were ignored
for this.
