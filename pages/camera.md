<!-- The camera page (site 1.2.4, Rob), in the shape of /sdcard and /lights. Every fact is from the firmware repository's internal/PLAN-freenove-cam.md as of 2026-09-24, and only from the sections Rob decided: "Snapshot command, self-timer and timelapse", "Limits, notices and naming" and "Retention", plus the privacy points in the brief. Since site 1.2.7 the sensor and the resolution are stated, from the firmware's FNCAM 1.0.2 (CHANGELOG, COMMANDS.md and src/board.h, 2026-09-25): the Freenove's sensor varies between batches, Freenove document an OV2640 and Rob's kit carries a GalaxyCore GC0308 (640x480 at most, no JPEG encoder, the board encodes: 3.6 to 3.9 s from SNAPSHOT to saved); both drivers are built, and CONFIG offers qvga or vga on either, vga as shipped (off until switched on, staff told of every snap, a lens cap the only real guarantee). Deliberately not stated, because the plan leaves them open: the quality default, the brightness default, the default count limits, the shortest timelapse interval (to be measured), exact wording of the board's messages other than "Download it now? (y/N)", which is Rob's, and the text-art preview (a stretch without a go). The Photos area is readable by everyone as shipped (Rob, in the 1.2.4 brief; the plan's proposal was users). The "until 1.1.0" note follows /lights; if the camera slips past 1.1.0, move the gate to the release that carries it. Since site 1.2.9 the settings, the download question, the flash and the timelapse are the firmware's as built, from COMMANDS.md "camera" and src/plugins/camera.cpp at 1.1.0-dev.15 (FNCAM 1.0.2): off until enabled (no PF_ON), staff told "Node n took a photo.", "Download it now?  [Y]es  [X]modem  [N]o", quality 12 on 4 to 40, 200 kept of each kind, flash off as shipped (the Freenove has no pixel), timelapse every 10 s at the least into area 13. The "from 1.1.0" note says which camera board the installer carries. Since site 1.3.4 (Rob) the ESP32-CAM is a third camera board and "What size photos can I take?" gives each board's largest photo, the same figures as /hardware's "Choosing a camera board": the ESP32-CAM's 1600x1200 from Rob's bench (a genuine OV2640, UXGA) and its board profile being finished (BBS_CAM_SIZES qvga to uxga), the Freenove's 320x240 or 640x480 from its build on either sensor, the S3 camera board's 2048x1536 from the OV3660's datasheet, expected until tested. -->
# Camera

A camera on the board, and anyone you allow can take a picture with it.
Point the board at a bird feeder, a garden or a workbench, and a visitor on a
laptop, or on an Atari 800 from 1979, types `SNAPSHOT` and has the photo a
few seconds later.

::: until 1.1.0
> [!NOTE]
> **The camera arrives with firmware 1.1 for the camera boards**, which is not
> released yet, and no camera board is on the installer. This page describes
> it as it has been designed, so you can plan a board around it.
:::

::: from 1.1.0
> [!NOTE]
> **The Freenove camera board is on [the installer](/install)** from firmware
> 1.1.0. The ESP32-CAM goes on once a release carries its build, and the
> ESP32-S3 camera board once it has been tested.
:::

::: art
camera-snap
:::

## What you need

- **One of the camera boards**: the [Freenove ESP32 camera
  board](/hardware#freenove-esp32-camera-board), the
  [ESP32-CAM](/hardware#esp32-cam) or an [ESP32-S3 camera
  board](/hardware#esp32-s3-camera-board). The camera is on the board, so
  there is nothing to wire. They are side by side in [choosing a camera
  board](/hardware#choosing-a-camera-board).
- **Whichever camera your Freenove came with.** Its sensor varies between
  batches: Freenove's documents name an OV2640, and Rob's kit came
  with a GalaxyCore GC0308, which takes 640x480 pictures at most and has no
  JPEG encoder, so the board encodes each photo itself. The firmware works
  with either, and the `CAMERA` command names the one it found.
- **A micro SD card** in the board's slot. Photos are kept on the card, and
  without one the camera does not start.
- **Somewhere worth pointing it**, within reach of a USB power supply. A phone
  charger will do.

## Taking a picture

Type `SNAPSHOT`, or `SNAP` for short, at the main prompt.

- **It takes the picture straight away.** There is no countdown: whoever typed
  it is somewhere else, not in front of the lens. On a board with a GC0308 the
  photo is saved about 4 seconds later, because the board encodes it itself.
- **It tells you the photo's file name**, that it is in the Photos file area,
  and how many more you may take this hour and today.
- **It asks `Download it now? [Y]es [X]modem [N]o`.** Y sends the photo at
  once by YMODEM and X by plain XMODEM, the same way as any download from the
  file areas, so the picture is on your machine seconds after you asked for
  it. N takes you back to the prompt, and the photo stays in Photos.

A caller who may take pictures but not download them is told where the photo
went and is not asked. A photo is a JPEG, which a PC terminal can save and
open: an 8-bit machine can take the picture, and looking at it is a job for
a PC.

## What size photos can I take?

It depends on the camera on the board. A board offers only the sizes its
camera, and its build, can take, and the sysop picks one of them under
Resolution in the settings below.

- **The ESP32-CAM:** up to 1600x1200, from its 2 megapixel OV2640.
- **The Freenove camera board:** 320x240 or 640x480, whichever camera it
  came with.
- **The ESP32-S3 camera board:** up to 2048x1536 expected, from its
  3 megapixel OV3660, once it has been tested.

The three are side by side, with what each costs and what is on it, in
[choosing a camera board](/hardware#choosing-a-camera-board).

## Photos, file area 12

Every picture goes into **Photos**, file area 12, reached from `FILES` like any
other area. As shipped, everybody can see and download the photos in it,
guests included, and the sysop can change that.

The sysop also chooses how photos are named: by the date and time, by the
date and time with the handle of whoever took it, or in a folder for each
caller, so you can find your own pictures.

## Limits

- **10 pictures an hour and 20 a day for each caller.** Every snap says where
  you stand, and at the limit the board says when the next one is allowed.
- **A guest is counted by address as well as by handle**, so hanging up and
  calling back under another name does not start the count again.
- **The sysop is not counted.**

## Before you point it at anything

A camera callers can use is a window into the room it is in, open to whoever
the sysop lets through. That is the whole of the risk, and it is worth
getting right before any of the settings below.

- **Nobody can use it until the sysop says so.** It is off until it is switched
  on, and then, as shipped, only staff may take a picture.
- **Staff hear about every snap.** Each member of staff on the board sees a
  line naming the node that took one.
- **A light can tell the room.** The camera can light a pixel, or an LED on
  a spare pin, while it takes a picture. The Freenove board has no light of
  its own for this, so it is off as shipped: wire one and switch it on if the
  people in the room should know when a picture is taken.
- **The pictures stay on your card**, not on anybody's server. A picture leaves
  the board when a caller downloads it, and from their machine it can go
  anywhere, like any file.

Low risk is not no risk, and the difference is what is in frame.

> **A lens cap is the only real guarantee.** A setting can be changed by
> anybody who has the sysop password; a cap over the lens cannot. Point it at
> the bird feeder, not the sofa, and cap it when the room is private.

## Settings

`CONFIG camera`, the sysop's alone. The flash, the timelapse and the
picture adjustments are pages of their own inside it.

| Setting | What it does | As shipped |
|---|---|---|
| On | Whether the camera runs at all. | Off |
| Snapshot level | Who may take a picture, from everybody, guests included, up to the sysop alone. | Staff |
| Photos level | Who may see and download the photos in areas 12 and 13. | Everybody |
| Resolution | The sizes the board's camera can take. On the Freenove, 320x240 or 640x480, on either camera; a GC0308 goes no higher. | 640x480 on the Freenove |
| Quality | How sharp the JPEG is, 4 to 40, where lower is sharper. | 12 |
| Watermark | The board's name, the date and who took it, in a corner. | On |
| Name snaps | By date, by date and handle, or a folder for each handle. | By date |
| Keep caller snaps for | Days before a caller's photo is removed. 0 keeps them however old. | 30 days |
| Max caller snaps | How many callers' photos are kept. 0 is no limit. | 200 |
| Card space floor | Free space the camera always leaves on the card for the file areas, the forums and the backups. | 10% of the card or 512 MB, whichever is smaller |
| Flash | Off, a pixel lit white, or a pin driven high for an LED, a relay or a flash unit, while a picture is taken. | Off |
| Timelapse every | Minutes and seconds between the board's own pictures, up to a day. 0 is off, and anything under 10 seconds is 10. | Off |
| Keep timelapse for, max timelapse shots | The same two rules for the timelapse's pictures. | 7 days, 200 |
| Flip, mirror, brightness, contrast, colour, exposure, white balance, effect | For a camera mounted upside down, looking through a mirror, or in a dim room. | Off, or the sensor's own |

The oldest photos go first when any of the last four rules bites, and the
timelapse's go before callers' pictures when the card is short of room.

## Timelapse

Set **Timelapse every** and the board takes pictures by itself: once a minute
for an afternoon of clouds going over, once an hour for a month of a garden
growing. They go into **Timelapse**, file area 13, with their own keep rules,
so a fast timelapse never pushes out the pictures callers took. The shortest
interval is 10 seconds, because the camera has to start up for each picture.

Later, a motion sensor on a spare pin will be able to take a picture the
moment something moves, for the visitor at the feeder nobody was watching
for. That arrives with the sensors, and [the roadmap](/roadmap) has it.

## What goes wrong

- **`SNAPSHOT` is an unknown command.** The camera is switched off in
  `CONFIG camera`, or there is no card in the slot: without a card the camera
  does not start.
- **It says the card is too full.** The camera keeps the card's free space
  above the floor in the settings by removing the oldest photos first. When it
  still cannot make room, it refuses the picture rather than eat the space the
  file areas, the forums and the backups use.
- **It says you have reached your limit.** It also says when the next picture
  is allowed.
- **The picture is upside down or back to front.** Turn on Flip or Mirror.

::: next
[Choose a camera board](/hardware#choosing-a-camera-board)
:::
