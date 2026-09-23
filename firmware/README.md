<!--
 ===========================================================================
  µnleashed BBS directory
 ===========================================================================

 File:         firmware/README.md
 Purpose:      Where firmware images live, and how to cut a release.

 Copyright 2026 - Robert Mech
 License:      GNU General Public License v2 or later
 SPDX-License-Identifier: GPL-2.0-or-later
 ===========================================================================
-->

# Firmware releases

This directory is what `/install` serves. A release lands here, and the page
offers it; take it out, and the page stops.

**Releases are not committed.** The firmware repository publishes each one as
a GitHub Release, and `deploy/update.sh` on the server fetches the newest with
`deploy/fetch_release.py`, checks every file against its `SHA256SUMS`, and
installs it here. The version directories are git-ignored; only this README is
tracked. **Nothing here is a list somebody
maintains.** `server.py` walks this directory on each render and builds the
ESP Web Tools manifest from what is actually on disk, so a release cannot be
half-published, and the "no release published yet" state on the page is the
absence of files rather than a flag anybody has to remember to flip.

**Do not put a `manifest.json` in here.** The server writes it, from the files
it finds, and serves it at `/install/<version>/manifest.json`. A hand-written
one would be ignored, and one that could be served would be able to name a
file that is not there.

## Layout

```
firmware/
  README.md                      this file
  0.22.1/                        one directory per release, named for the version
    release.txt                  optional: date on line 1, a short note after
    THIRD_PARTY_NOTICES.md       from the firmware repo, with the release
    SHA256SUMS                   the release's own, kept for the record
    esp32/                       one directory per chip family
      bootloader.bin
      partitions.bin
      ota_data_initial.bin
      firmware.bin
      storage.bin
  0.22.0/
    ...
```

Served as:

```
/install/0.22.1/manifest.json            built by server.py, never a file
/install/0.22.1/esp32/<part>.bin         the five parts, same origin as the page
/install/0.22.1/THIRD_PARTY_NOTICES.md
```

Three rules, all enforced by `server.py` rather than by care:

- **A version directory is named `MAJOR.MINOR.PATCH` and nothing else.** Any
  other name in here is ignored, which is why this README can sit beside the
  releases without being mistaken for one.
- **A chip directory is offered only when all five of its parts are present**,
  and none of them is empty.
  A missing or misnamed file means that chip family is not offered, silently
  and safely. It is never offered with a part pointing at a file that is not
  there.
- **Two releases are offered at a time**, newest first by version number.
  `DIRECTORY_FIRMWARE_KEEP` moves that; the extra ones on disk are simply not
  listed, so a third left behind by accident cannot appear.

Four of the five filenames are what PlatformIO produces. The fifth is
`storage.bin`, which PlatformIO calls `littlefs.bin`: a release names it for
the partition it is written to, so it is renamed as it is copied in.

## Chip families

A second chip family is a new directory, not a code change. The directory name
maps to the ESP Web Tools `chipFamily` string, and to that family's bootloader
offset, in `FLASH_FAMILIES` in `server.py`:

| Directory | `chipFamily` | Bootloader offset |
|---|---|---|
| `esp32` | `ESP32` | `0x1000` |
| `esp32s2` | `ESP32-S2` | `0x1000` |
| `esp32s3` | `ESP32-S3` | `0x0` |
| `esp32c3` | `ESP32-C3` | `0x0` |

Only `esp32` is real today. The reference board is a bare ESP32-WROOM-32E and
an ESP32-S3 with PSRAM is the documented upgrade path, so the table is there so
that the day an S3 build exists it is a directory drop and nothing else.

ESP Web Tools reads the chip out of the board it just connected to and picks
the matching entry, so a page offering several families needs no chooser and
the visitor is never asked a question about their hardware that the hardware
can answer.

## The offsets, and where they come from

Read out of the firmware repo, not out of a tutorial:

| Part | Offset | Source |
|---|---|---|
| `bootloader.bin` | `0x1000` (4096) | `CONFIG_BOOTLOADER_OFFSET_IN_FLASH` in `sdkconfig.esp32dev` |
| `partitions.bin` | `0x8000` (32768) | `CONFIG_PARTITION_TABLE_OFFSET` in `sdkconfig.esp32dev` |
| `ota_data_initial.bin` | `0xF000` (61440) | the `otadata` row in `partitions.csv` |
| `firmware.bin` | `0x20000` (131072) | the `ota_0` row in `partitions.csv` |
| `storage.bin` | `0x3C0000` (3932160) | the `storage` row in `partitions.csv` |

The manifest carries them as decimal numbers, which is what ESP Web Tools'
`offset: number` wants; JSON has no hex literal.

`ota_data_initial.bin` is the `otadata` partition in its starting state, which
tells the bootloader to run the first application slot. `firmware.bin` is
always written to that slot, so writing the starting state with it means a
board that had ever switched to the second slot boots what was just installed
rather than what was left there.

`0x1000` is the ESP32's bootloader offset and it is **not** universal: an S3 or
a C3 puts the bootloader at `0x0`. That is why the offset is a property of the
chip family in `FLASH_FAMILIES` and not a constant.

`storage.bin` is the `storage` partition, which is the screens. The other two
filesystems are deliberately not in the image:

- **`userdata` is never flashed.** It is the accounts, the live configuration
  and each plugin's files, and it is the whole reason the partition table is
  split the way it is. An installer that wrote to it would undo that.
- **`logs` is never flashed.** It is the caller log, which is the sysop's
  security record.

Both are left erased on a fresh install and the firmware creates them on first
boot. `syscfg::seed()` copies the shipped `system.cfg` off `storage` onto
`userdata` once, so a fresh board comes up configured.

> **If `partitions.csv` ever moves a partition, `FLASH_PARTS` in `server.py`
> has to move with it.** That is deliberate rather than an oversight: a layout
> change is already a breaking change on the board, needing a full erase and a
> migration note, and the installer is one of the things that has to be told.
> A per-release copy of the offsets would let the two drift quietly instead.

## `release.txt`, and the manifest's two settings

Optional. Absent, a release still installs; the page has less to say about it.

```
2026-09-23
Mail is a place of its own, and the Wi-Fi is set from the browser.
```

- **Line 1, a date**, `YYYY-MM-DD`, shown beside the version on the page.
- **A short note**, one line, shown under it. Keep it to a sentence.

An `improv: yes` line was once how a release switched the Wi-Fi step on. Every
release now speaks Improv Wi-Fi Serial (the firmware has since 0.22.1), so the
line is ignored, and skipped rather than shown as the note.

`new_install_improv_wait_time` is `30` for every release (`EWT_IMPROV_WAIT` in
`server.py`). It is how long the installer waits after writing for the board
to answer over Improv, and the first boot after a full erase formats two
filesystems before the board is listening. A board that answers after the
installer has stopped waiting gets no Wi-Fi step, and the reader has a board
on no network.

`new_install_prompt_erase` is `true` for every release and is not
configurable. It asks the person whether to erase instead of erasing
silently, and the checkbox it produces **starts unticked**, so it flips the
default from erase to keep. That is what lets a sysop reinstall over a board
they already run without losing their accounts. The trade is that a first-time
installer has to tick the box, and `pages/install.md` tells them to in as many
words. Two consequences worth knowing:

- ESP Web Tools goes straight to the Wi-Fi screen only after an install that
  **erased**. After one that did not, it shows its menu, where **Connect to
  Wi-Fi** or **Change Wi-Fi** is one item.
- With the box unticked, only the flash regions named in the manifest are
  written. `userdata` and `logs` are outside all five parts and survive
  untouched. With it ticked, the whole chip goes.
- **A board that already runs 0.22.1 or later is never asked.** ESP Web Tools
  asks the board over Improv what it is running, and when the answer's
  firmware name matches the manifest's `name` (`unleashed BBS`) it offers
  **Update** and writes without erasing, with no question. So a release that
  moves a partition, which needs the full erase, cannot be delivered as an
  ordinary update from this page. Decide how before cutting one: changing the
  manifest `name` for that release makes every board look new and brings the
  erase question back.

## Cutting a release

Steps 1 to 6 happen in the firmware repository. The directory's part is to
fetch it, which `update.sh` does.

1. **Check the source for that version is public.** The binaries are GPL v2 or
   later, so anybody who receives one is owed the corresponding source. The
   firmware repository is private today, so publishing a binary before its
   tagged source is public is a licence violation and not merely untidy. This
   step is a gate, not a formality.

2. **Build from a fresh clone, never from a working tree.** A fresh clone has
   no private credentials in it; a working tree almost certainly has.

   ```sh
   git clone https://github.com/rwmech/unleashed_BBS esp32-bbs-release
   cd esp32-bbs-release
   test ! -e include/secrets.h && echo "no secrets.h, good"
   cp data/system.cfg.example data/system.cfg
   pio run
   pio run -t buildfs
   ```

   Do not delete `include/secrets.h` from a working tree to get the same
   effect. It is not in git, so a deleted one is gone.

   Both copies matter and they leak different things:

   - `include/secrets.h` is optional since 0.22.1, and when it is present it
     is compiled into `firmware.bin` as the fallback network. A build from a
     developer's own tree puts their home SSID and passphrase in the image in
     plaintext, recoverable with `strings`. A release is built without it, and
     the board gets its network from the browser.
   - `data/system.cfg` is built into `littlefs.bin`. A developer's own copy
     carries `sysop_password` and, on a board that is listed, its directory
     token.

   Neither file is in git for exactly this reason, so a fresh clone is already
   correct and only a working tree is dangerous.

3. **Prove the image carries no credentials** before it goes anywhere:

   ```sh
   strings .pio/build/esp32dev/firmware.bin | grep -i -e <your-ssid>
   strings .pio/build/esp32dev/littlefs.bin | grep -i -e _password -e token
   ```

   The first should find nothing. The second should find only the empty keys
   from `system.cfg.example`. If either finds a real value, throw the build
   away and start at step 2; do not edit the binary. `selftest.py` repeats the
   second check on every `storage.bin` placed here, and fails on any
   password, Wi-Fi or token key that has a value.

4. **Note the version.** It is `BBS_VERSION` in `src/config.h`, and the
   release's tag must be `v` and exactly that: the tag names the directory the
   release is installed into.

5. **Copy the third-party notices**, `THIRD_PARTY_NOTICES.md` from the firmware
   repo root. It describes the code in the binaries beside it, so it travels
   with them rather than being linked to a moving target.

6. **Publish a GitHub Release** of `rwmech/unleashed_BBS`, tagged `v` and the
   version (`v1.0.0`), public, with these seven assets:

   ```
   bootloader.bin  partitions.bin  ota_data_initial.bin  firmware.bin
   storage.bin     THIRD_PARTY_NOTICES.md                SHA256SUMS
   ```

   `storage.bin` is PlatformIO's `littlefs.bin` renamed. `SHA256SUMS` is
   `sha256sum`'s own output over the other six. A release without all seven,
   or with a file that does not match its sum, or whose `storage.bin` carries a
   password, a Wi-Fi key or a token, is refused and nothing on the site moves.

7. **Rob runs `sudo /srv/unleashed_directory/deploy/update.sh`** on the
   droplet. It fetches the newest release on every run, whether or not the site
   itself changed, installs it here, and keeps the newest two. A fetch that
   fails says why and leaves the installed release alone.

8. **To check a build locally before it is published**, copy it in by hand;
   the version directory is git-ignored, so it cannot be committed by
   accident. Nothing here talks to the live site.

   ```sh
   V=1.0.0
   S=../esp32-bbs-release/.pio/build/esp32dev
   mkdir -p firmware/$V/esp32
   cp $S/bootloader.bin $S/partitions.bin $S/ota_data_initial.bin \
      $S/firmware.bin firmware/$V/esp32/
   cp $S/littlefs.bin firmware/$V/esp32/storage.bin
   python selftest.py
   DIRECTORY_PORT=8937 python3 server.py > /tmp/dir.log 2>&1 &
   curl -s localhost:8937/install/$V/manifest.json | python3 -m json.tool
   curl -sI localhost:8937/install/$V/esp32/firmware.bin
   ```

   The manifest should name the new version and list five parts, with the
   offsets `4096`, `32768`, `61440`, `131072` and `3932160`. Every part should
   fetch with a 200 and a plausible length.

   Open `http://127.0.0.1:8937/install` in Chrome and check the button is
   live. `127.0.0.1` and `localhost` count as secure contexts, so Web Serial
   works there; a LAN address over plain http does not, and the page will
   correctly tell you so.

   Redirect that log to a file rather than leaving it on a pipe. The server
   prints one blocking line per request from its handler thread, and an
   undrained pipe wedges it in a way that reads exactly like a crash.

9. **Delete the hand-copied release** when you are done, so the next fetch is
   what the page offers.

10. **Flash a real board from the live page** before telling anybody the
    release exists. The installer is the one part of this project that cannot
    be tested on the host: Web Serial needs a browser and a board, and a
    manifest that parses is not a board that boots.

    > **One thing to watch on that first flash, and it is unresolved.** ESP Web
    > Tools writes each part as it finds it and passes `flash_mode`,
    > `flash_freq` and `flash_size` as `keep`, where command-line `esptool`
    > patches those fields into the bootloader header as it writes. Their docs
    > say an ESP-IDF v4-or-later project therefore needs a single merged image;
    > their own README ships four separate parts for the ESP32 and does not
    > merge. Both are in the project's own documentation and they disagree.
    >
    > Our bootloader is built by PlatformIO against a fixed `sdkconfig`, so its
    > header already carries dio / 40m / 4MB and there should be nothing to
    > patch. That is reasoning, not evidence. If the first board flashes and
    > then fails to boot, this is the suspect, and the fix is to merge:
    >
    > ```sh
    > esptool.py --chip esp32 merge_bin -o merged.bin \
    >   --flash_mode dio --flash_freq 40m --flash_size 4MB \
    >   0x1000 bootloader.bin 0x8000 partitions.bin \
    >   0xF000 ota_data_initial.bin 0x20000 firmware.bin \
    >   0x3C0000 storage.bin
    > ```
    >
    > A merged release is one part at offset 0, which `FLASH_PARTS` would have
    > to say. Do not change it on a hunch; change it if a board does not boot.

## Size

A release is roughly 1.1 MB of application and 256 KB of filesystem per chip
family, so the two kept are about 2.7 MB of the server's disk and none of the
repository. To keep them somewhere else, point `DIRECTORY_FIRMWARE_DIR` at
another directory: the server and `fetch_release.py` both read it.

## What still gates the first release

Not the Wi-Fi: since firmware 0.22.1 the network is set from the browser over
Improv Wi-Fi Serial. Not the sysop password either: 1.0.0 ships a default,
`unleashed`, that works only from the board's own network and only until it is
changed, and `pages/install.md` says so. What is left is step 1: the source
has to be public, which for this repository happens at 1.0.0, and until then
`fetch_release.py` finds no public release and says so.
