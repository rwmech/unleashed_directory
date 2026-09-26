<!-- Making display skins (site 1.3.14, Rob: "coming soon for display-enabled boards"). Every fact is from the firmware's panel-skins lane (release-prep/wt-skins, 2026-09-26, not merged, not released): internal/site-draft-make-a-skin-2026-09-26.md for the reader's steps, SKINS.md for the grammar and its limits, tools/mkskin.py for the commands (check, leds, preview, jpeg, pack; Python 3.8, Pillow for all but check), and src/plugins/skin.cpp for the upload shape: skinPath() reads skins/<name>/skin.txt and background.jpg, or skins/<name>.txt and <name>.jpg beside the folders, which is what an upload into the Skins file area gives, and skin::uploaded() rereads the list and the skin on the screen. The Skins file area itself was not yet in files.cpp in that tree, so this page gives it no number. The board is Rob's: the Makerfabs ESP32-S3 Parallel TFT with Touch 3.5" ILI9488, 480x320, confirmed from the board on COM18 (firmware CLAUDE.md, 2026-09-26; SKINS.md still says SPI TFT, which is stale). No firmware version is named because the draft does not settle one: the firmware's CLAUDE.md puts skins and the Makerfabs board in the 1.2.0 hardware release, and COMMANDS.md in the lane says 1.1.2. Once a release carries skins, wrap the status note in "::: until X.Y.Z" and add the version. The stock set: pc, c64, apple2, atari, imsai in skins/stock/, painted by tools/mkskins_stock.py with no maker's name or logo. The zip does not exist yet; see the comment under "The stock skins". No picture of a skin: the renders so far are mock-ups, so the drawing is skin-parts in server.py. -->
# Skins

A board with a screen can dress up as a machine from another decade. A skin is
a picture of a computer, a terminal or a front panel, and the board lights its
lamps for real: the drive lamp flickers when the card is read, a power lamp
blinks with network traffic, a row of panel lamps follows the lights effect,
and the board's name, address and callers appear on the picture's own screen.

You draw the machine. The board makes it glow.

> [!NOTE]
> **Skins are coming soon for display-enabled boards.** The first is the
> [Makerfabs ESP32-S3 Parallel TFT
> 3.5"](https://www.makerfabs.com/esp32-s3-parallel-tft-with-touch-ili9488.html),
> with a 480 by 320 screen, and more display boards will follow. This page
> describes skins as they have been built, so you can start drawing now.

::: art
skin-parts
:::

## What a skin is

Two files in a folder on the SD card:

- **A picture**, `background.jpg`, exactly the size of the screen: 480 by 320
  pixels on the Makerfabs. Any machine you like, painted, drawn or
  photographed, as long as the art is yours.
- **A small text file**, `skin.txt`, that says where the lights are on the
  picture and where the board writes its status text.

The board lights the lamps itself, drawn as light rather than paint, with a
soft glow round each lens. They follow the same modes as [the lights you can
wire to a board](/lights):

- **The drive light** shows the storage at work: amber for the SD card, cool
  white for the board's own memory, a slow red blink after an error. It
  behaves in the style you pick: `pc` flickers like a PC's hard disk lamp,
  `1541` stays lit for the whole access, `disk2` stays on for a second after,
  like the Apple II's Disk II, and `breathe` pulses slowly at rest.
- **The activity light** blinks with network traffic, in any colour you give
  it. A power lamp or a turbo lamp on the picture makes a good one.
- **The strip** is up to 16 lamps showing whatever the strip effect is:
  `nodes` with a lamp for each caller line, `hayes` like a modem's front
  panel, `blinken` like a mainframe's, and the rest. No LED strip needs to be
  wired for it.

Nothing in a skin can break the board. If a skin is missing or has a mistake
in it, the screen shows the board's built-in layout, called `status`, and the
board says what was wrong and on which line.

## What you need

- **A board with a display**, and an **SD card** in its slot. Skins live on
  the card.
- **A paint program.** Any image editor, photo editor or pixel art tool that
  shows the X and Y of the spot under the mouse pointer.
- **A text editor** that saves plain text: Notepad, TextEdit in plain text
  mode, nano.
- **The helper tool, `mkskin.py`, optional but worth it.** It checks a skin
  by the board's own rules, turns any picture into a JPEG the board takes,
  finds the lights for you and shows the skin lit, before anything goes near
  the card. It needs Python 3.8 or later and, for everything but `check`, the
  Pillow imaging library, on Windows, a Mac or Linux.

The tool will be in the `tools` folder of [the firmware's
repository](https://github.com/rwmech/unleashed_BBS) when skins are released.
Download the whole repository (the green **Code** button, then **Download
ZIP**) and run the tool from inside it, because its preview borrows the
screen's font from the repository. Pillow installs with:

```
python -m pip install pillow
```

On Windows the command may be `py` rather than `python`. On Debian or Ubuntu,
if `pip` refuses, use `sudo apt install -y python3-pil` instead.

## Making one, step by step

1. **Start from the template.** Copy one of the stock skins' folders and name
   the copy after your skin, for example `my_tower`. A skin's name is 1 to 24
   letters, digits, `_` or `-`, and cannot be `status`.
2. **Paint it.** Replace `background.jpg` with your own picture, exactly 480
   by 320 pixels. Paint every lamp dark, the way it looks switched off: the
   board adds light on top and never takes any away, so a dark red lens glows
   red when lit and looks like an unlit lamp when not. Leave the machine's
   screen dark and plain, because the status text goes there. If your editor
   saves JPEGs the board refuses, let the tool make it:

```
python tools/mkskin.py jpeg my_art.png -o my_tower/background.jpg
```

3. **Mark the lights.** Either paint key colours and let the tool measure
   them, as the next section shows, or write the positions into `skin.txt`
   yourself with the reference further down.
4. **Check it**, and look at it lit:

```
python tools/mkskin.py check my_tower
python tools/mkskin.py preview my_tower -o my_tower.png
```

5. **Put it on the board**, on the card or by upload, as [the last
   section](#putting-it-on-the-board) shows.

A few rules about the picture, because the board draws it with a small JPEG
decoder built into the chip:

- **Exactly the screen's size.** The board does not resize, and a picture of
  any other size is refused.
- **Baseline, not progressive.** If your editor's save dialog has a
  **Progressive** option, turn it off.
- **Colour.** A greyscale JPEG is refused, and so is CMYK, a printing setting.

The `jpeg` command gets all three right. It stretches a picture of any other
shape to 480 by 320, so crop your art to 3:2 first, or draw it at 480 by 320
from the start.

## Marking the lights with key colours

Finding the centre of a small lens by hovering the mouse over it gets tedious
by the third lamp. The tool can find them: paint a dot of a bright colour over
each lamp on a copy of your picture, and it measures each dot and writes the
lines.

1. Copy your picture at full size and save the copy as a PNG. Work on the
   copy only. A JPEG blurs colours, which is why the copy is a PNG.
2. Paint a solid dot the size of the lens over each lamp, and a filled
   rectangle where the status text goes. Use a colour for each kind that
   appears nowhere else in the picture, and turn antialiasing off in the
   brush settings if you can.
3. Run the tool, naming each colour and the drive light's style:

```nowrap
python tools/mkskin.py leds keyed.png --key drive=#FF00FF --key activity=#00FFFF --key led=#FFFF00 --key text=#00FF00 --style 1541
```

4. It prints the lines for `skin.txt`. Copy them into your skin's file with a
   text editor, then add what the tool cannot guess: a `name`, the colours,
   and the `lines` you want shown.

| Paint | Key | How many |
|---|---|---|
| The drive light | magenta `#FF00FF` | One dot |
| The activity light | cyan `#00FFFF` | One dot |
| The strip lamps | yellow `#FFFF00` | Up to 16 dots |
| The text rectangle | green `#00FF00` | One filled rectangle |

Strip lamps are numbered the way you read a panel: the top row left to right,
then the next row down. A clock can be placed the same way with `--key
clock=#RRGGBB`, its dot marking the clock's top left corner. If a colour is
not found, the tool says so and leaves that light out.

> In Windows PowerShell, do not send the tool's output to a file with `>`:
> PowerShell writes a kind of text file the board refuses. Copy the lines from
> the window instead.

## skin.txt

One line for each thing on the picture. This is the stock beige tower's,
complete:

```
skin 1
panel 480 320
name Beige tower
; the hard disk lamp, a flicker for every read
drive 428 210 6 pc halo=5
; the turbo lamp, here for traffic
activity 392 210 6 colour=#FFC020 halo=5
; the monitor's tube, grey on black
text 46 58 224 128 colour=#C8C8C0 background=none
lines name address uptime callers today heap who
clock 222 38 colour=#C8C8C0
```

Positions are in pixels from the picture's top left corner: X across to the
right, Y down.

| Line | What it does |
|---|---|
| `skin 1` | The format. Always the first line |
| `panel 480 320` | The screen it is drawn for, width then height. Must match the picture |
| `name TEXT` | A description, up to 24 characters |
| `drive X Y D STYLE` | The drive light: its centre, the lens's diameter, and `pc`, `1541`, `disk2` or `breathe` |
| `activity X Y D` | The activity light. Green unless you give it a `colour=` |
| `strip N` | How many strip lamps, 1 to 16. A `led` line for each follows |
| `led I X Y D` | Strip lamp number I: its centre and diameter, each from 1 to N once |
| `text X Y W H` | The rectangle for the status text: top left corner, width, height |
| `lines WORD ...` | What the rectangle shows, top to bottom, one word a row |
| `clock X Y` | The time, as HH:MM, with its top left corner at X Y |

Every line but `skin` and `panel` is optional, and each appears once. Options
go after the fixed values as `name=value`, with no spaces round the `=`:

- `halo=N`, on any light: how far its glow spreads past the lens, 0 to 32
  pixels. Half the lens if you leave it out.
- `colour=#RRGGBB` (or `color=`), on a light, the text or the clock.
- `size=small` or `size=big`, for the text and the clock: 8 by 16 or 16 by 32
  pixel letters.
- `shadow=#RRGGBB` and `background=#RRGGBB`, for text over a busy picture.
  Both are `none` if you leave them out.
- `align=left`, `centre` or `right`, for the text.

The words for `lines`:

| Word | Shows |
|---|---|
| `name` | The board's name |
| `address` | The address and port callers dial |
| `uptime` | How long since the board started |
| `callers` | Callers on, out of the lines there are, such as `Callers 2/11` |
| `today` | Calls since midnight |
| `heap` | Free memory |
| `card` | Free space on the SD card |
| `clock` and `date` | The time and the date |
| `last` | The latest login, logoff or page |
| `ring` | Who is ringing for the sysop, empty when nobody is |
| `blank` | An empty row |
| `who` | Who is on, one caller a row, in every row left. So it goes last |

The details that catch people out:

- **Nothing may overlap.** Each light takes a square box, its lens plus its
  halo on every side, and no two boxes may share a pixel, nor a box and the
  text or the clock. Lamps close together want a smaller halo.
- **The rectangle must be tall enough**: 16 pixels a row for small letters,
  32 for big. A row wider than the rectangle is cut at its edge.
- A line starting with `#` is a comment, and so is anything after a `;`.
- Plain text only, at most 120 characters a line and 4 KB for the file.
- The drive light and the strip come from the lights plugin, so switch it on
  in `CONFIG lights`, even with nothing wired. A skin with more than 10 strip
  lamps wants **Strip len** set to match.

## The stock skins

Five skins come with the feature, drawn for the 480 by 320 screen:

| Skin | What it shows |
|---|---|
| A PC | A beige tower with its monitor. The hard disk lamp is the drive light |
| A 1980s home computer | The computer with its disk drive and monitor |
| An Apple ][ | The computer with its Disk II drives and a green screen |
| An Atari 400/800 | The computer with its 810 drive and a wood-grain television |
| An IMSAI 8080 | The front panel. Its 16 address lamps are the strip |

Each one is a starting point: copy its folder, repaint it, move the lamps.

**Download: coming soon.** The stock set goes up here as one zip once skins
are released. A later firmware puts them on the card by itself as well.

<!-- When the stock zip exists, replace the "Download: coming soon" paragraph above with this one line, pointing at the real file:
[Download the stock skins](ZIP-URL), one zip to unpack onto the top of your SD card.
-->

**No logos, and no trademark art.** None of the stock skins carries a
maker's badge, logo or name: they are drawings of a kind of machine, not of a
product. A skin you make or share must not use them either. Use art you made
or have the right to use: a photo from a web search belongs to whoever took
it. A drawing of a beige tower is yours to give away. A company's badge on it
is not.

## Putting it on the board

**On the card:**

1. Log in as the sysop and type `SD UNMOUNT`, so the card can come out
   safely.
2. Copy your skin's folder into the `skins` folder at the top of the card.
   Make the `skins` folder if it is not there.
3. Put the card back and type `SD MOUNT`.
4. Type `CONFIG panel`, step the **Skin** row to your skin with Space, and
   save.

**Or over the line, without taking the card out:** as the sysop, upload the
two files into the board's **Skins** file area, named after the skin:
`my_tower.txt` for `skin.txt` and `my_tower.jpg` for the picture. Then choose
it in `CONFIG panel`. The board reads its list of skins again after an upload,
and reloads a skin that is already on the screen.

The board loads a skin in the background, so callers are never held up, and
the `status` layout stays on the screen until the skin is ready. The **Skin**
row lists only skins drawn for this screen's size whose `skin.txt` reads
cleanly, so if yours is missing from it, run `check` on it.

**Changed a skin already on the screen?** The board keeps it in memory. After
copying a new version onto the card, choose `status`, save, then choose your
skin again. Restarting the board works too.

## When it does not show

Type `PANEL`. A line says which skin is on the screen, and when it is not the
one you chose, a red line says why:

```
Skin status
Not my_tower: skin.txt line 9: led 2's box overlaps led 1's (line 8)
```

| PANEL says | What to do |
|---|---|
| `background.jpg is 640x480; the panel is 480x320` | Make the picture exactly the screen's size. `mkskin.py jpeg` does it |
| `progressive JPEG` | Save it again with progressive off, or use `mkskin.py jpeg` |
| `led 2's box overlaps led 1's` | Move the lamps apart, or give them a smaller `halo` |
| `a character that is not plain ASCII (byte 239)` | The editor saved "UTF-8 with BOM". Save it as plain text |
| `no skins/my_tower/skin.txt on the card` | The folder is not in `skins` at the top of the card, or its name differs by a letter |
| `loading` | Nothing is wrong. Give it a second |

The line numbers count every line of `skin.txt`, blank lines and comments
included, the way a text editor numbers them. After fixing a skin that
failed, the board does not try it again by itself: type `SD UNMOUNT` and `SD
MOUNT`, or restart the board.

## Sharing a skin

When it looks right, the tool packs it for somebody else:

```
python tools/mkskin.py pack my_tower -o my_tower.zip
```

It checks the skin first and refuses to pack one with a mistake in it. The zip
holds `skins/my_tower/` with both files, so whoever receives it unzips it onto
the top of their card. A `README.txt` in the skin's folder goes into the zip
too, which is a good place to say who drew it.

::: next
[The lights](/lights)
:::
