#!/usr/bin/env python3
"""
===========================================================================
 µnleashed BBS directory
===========================================================================

File:         deploy/fetch_release.py
Purpose:      Fetch the firmware's public releases from GitHub and put them
              where /install looks for them. The last hop of the build
              pipeline: the firmware repository builds and publishes a
              release, and this installs it on the directory. update.sh runs
              it; it can also be run by hand.

Usage:        python3 deploy/fetch_release.py [--dest DIR] [--quiet]
                --dest    the firmware directory the server reads
                          (default: $DIRECTORY_FIRMWARE_DIR, else firmware/
                          beside this script's repository)
                --quiet   say nothing unless something changed or failed

The contract, which the firmware side publishes to (its tools/release.py):
  - GitHub Releases of rwmech/unleashed_BBS, public. A release is tagged
    vX.Y.Z; a pre-release is tagged with a suffix, vX.Y.Z-dev.N, and GitHub
    marks it as one.
  - one image set per board, five parts each. The reference ESP32's are
    bootloader.bin, partitions.bin, ota_data_initial.bin, firmware.bin and
    storage.bin; another board's carry its folder as a prefix,
    esp32s3-bootloader.bin, esp32-fncam-bootloader.bin,
    esp32-cam-bootloader.bin and so on (FAMILIES below).
  - optionally, since firmware 1.1.0, each set's version.txt (the S3's as
    esp32s3-version.txt): one line, the version as that board shows it,
    "1.0.3" or "1.1.0 (S3 1.0.0)".
  - THIRD_PARTY_NOTICES.md, and SHA256SUMS in sha256sum's own format, one
    line per other asset

Which releases, since site 1.2.0. Each board is served on its own:
  - the newest release by version (not a draft, not a pre-release) is
    installed, every set it carries;
  - a board it does not carry is served from the newest older release that
    does, so an ESP32-only patch never takes a board off its release;
  - a board no release carries at all is served from the newest pre-release
    that carries it, installed under its real name (firmware/1.1.0-dev.8/),
    which the site shows as a preview and never counts as the newest
    release. That is how the Waveshare S3 arrives before 1.1.0 is released,
    while the ESP32 stays on the latest release.
  - except a board in NO_PREVIEW, which waits for a release: the Freenove
    camera board, which was to show nowhere before firmware 1.1.0.
  - and a board in AHEAD, once a release carries it, is also served from the
    newest pre-release that carries it and is newer than every release
    naming it, beside that release (site 1.3.7). The Freenove again: firmware
    1.1.1-dev.1 goes on the installer as its 1.1.1 preview while 1.1.0 is
    its release. The ESP32 and the S3 are not in it, so a pre-release never
    goes ahead of their releases.

What it does, for each release it wants, in the order that keeps a bad
download harmless:
  1. downloads every asset of the sets it carries into a staging directory
     inside the firmware directory, so the final move is a rename on one
     filesystem
  2. checks every file against SHA256SUMS, and checks each screens image
     carries no password, Wi-Fi key or token
  3. only then moves the release into firmware/<version>/, as the installer
     expects it: <set>/<the five parts>, <set>/version.txt when the release
     has one, THIRD_PARTY_NOTICES.md, SHA256SUMS, release.txt
  4. keeps the newest two releases, an older release while it is the one
     serving some board, and a pre-release only while it is the one serving
     some board, and removes the rest

Anything that fails before step 3 deletes the staging directory and leaves
the release already there exactly as it was.

Exit codes:   0 installed, or already had it
              1 something was not installed, and here is why

Copyright 2026 - Robert Mech
License:      GNU General Public License v3 or later
SPDX-License-Identifier: GPL-3.0-or-later
===========================================================================
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.error
import urllib.request

REPO = "rwmech/unleashed_BBS"
# Overridable so the self-test can point it at releases served from
# 127.0.0.1. Nothing else about the script changes when it is. The list, not
# /releases/latest, because the latest leaves out every pre-release; an
# answer that is one release rather than a list is read as a list of one.
API = os.environ.get("UNLEASHED_RELEASE_API",
                     "https://api.github.com/repos/" + REPO + "/releases?per_page=30")
PARTS = ("bootloader.bin", "partitions.bin", "ota_data_initial.bin",
         "firmware.bin", "storage.bin")
VERSION_TXT = "version.txt"
NOTICES = "THIRD_PARTY_NOTICES.md"
SUMS = "SHA256SUMS"
# The image sets a release can carry, by the folder the directory keeps each
# in, which is the firmware's own name for the build (tools/release.py) and
# a board in the site's BOARDS. The first is the reference ESP32, whose
# assets carry no prefix, as every release before 1.1.0 had them; any other
# set's are "<folder>-<part>". esp32-fncam is the Freenove ESP32-WROVER
# camera board, from firmware 1.1.0: the ESP32's chip family, a set of its
# own. esp32-cam is the ESP32-CAM, AI-Thinker's design (site 1.3.5): the same
# family again, and it arrives on a pre-release first, so it is served as a
# preview until a release carries it, and is not in NO_PREVIEW.
# esp32s3-mf35 is the Makerfabs ESP32-S3 Parallel TFT 3.5", hardware v1.0
# (site 1.3.17): the S3's chip family, arriving on a board pre-release
# (v1.1.1-mf35.1) that carries its set alone, so it is a preview the same
# way. Its assets are "esp32s3-mf35-<part>", which no other set's name is a
# prefix of: the Waveshare's are "esp32s3-<part>", matched whole.
FAMILIES = ("esp32", "esp32s3", "esp32-fncam", "esp32-cam", "esp32s3-mf35")
# Sets never taken from a pre-release while no release carries them: the
# site waits for a release before offering them at all (server.py,
# "previews": False or "ahead").
NO_PREVIEW = ("esp32-fncam",)
# Sets that, once a release carries them, also take the newest pre-release
# carrying them that is newer than every release naming them, as a preview
# beside that release (server.py, "previews": "ahead"; site 1.3.7, Rob: the
# Freenove gets firmware 1.1.1-dev.1 as its 1.1.1 preview).
AHEAD = ("esp32-fncam",)
KEEP = 2
TAG = re.compile(r"^v(\d{1,3})\.(\d{1,3})\.(\d{1,4})"
                 r"(?:-([0-9A-Za-z-]{1,20}(?:\.[0-9A-Za-z-]{1,20}){0,3}))?$")
VERSION = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,4})"
                     r"(?:-([0-9A-Za-z-]{1,20}(?:\.[0-9A-Za-z-]{1,20}){0,3}))?$")
# What a version.txt may say: the server reads the same shape.
SHOWN = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,4}(?:-[0-9A-Za-z.-]{1,40})?"
                   r"(?: \([A-Za-z0-9][A-Za-z0-9 .-]{0,30}\))?$")
SUM_LINE = re.compile(r"^([0-9a-fA-F]{64}) [ *]([^\s/\\]+)$")
# The S3's parts are laid out for the same 4 MB as the ESP32's, and a 4 MB
# flash cannot hold a larger part, so anything bigger is not ours.
MAX_ASSET = 8 * 1024 * 1024
# The same test selftest.py runs on anything already in firmware/: the
# screens image carries system.cfg, and a developer's copy carries the staff
# passwords, the Wi-Fi key and the directory token. The keys are there,
# empty, in every clean build; a value is not.
SECRET = re.compile(
    rb"^[ \t]*(sysop_password|cosysop1_password|cosysop2_password|"
    rb"wifi_ssid|wifi_password)[ \t]*=[ \t]*[^\r\n \t]"
    rb"|^[ \t]*token[ \t]*=[ \t]*[^\r\n \t;#]", re.M)


class Refused(Exception):
    """A reason to change nothing, worded for the person reading it."""


def prefix(family):
    return "" if family == FAMILIES[0] else family + "-"


def fetch(url, accept):
    req = urllib.request.Request(url, headers={
        "Accept": accept,
        # GitHub's API refuses a request without one.
        "User-Agent": "unleashed-directory-release-fetch"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read(MAX_ASSET + 1)
    if len(data) > MAX_ASSET:
        raise Refused(f"{url} is larger than any firmware part can be")
    return data


def list_releases():
    """Every release GitHub will show without a token, in the order it lists
    them, newest first. Drafts are never shown without one, and are skipped
    anyway."""
    try:
        got = json.loads(fetch(API, "application/vnd.github+json").decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise Refused(
                f"GitHub has no public release of {REPO} (it answered 404). "
                "The repository is private until 1.0.0, or has not published "
                "a release yet.")
        if e.code in (403, 429):
            raise Refused(
                f"GitHub refused the request ({e.code}), which is usually its "
                "rate limit for requests without a token. Try again in an hour.")
        raise Refused(f"GitHub answered {e.code} for the list of releases.")
    except urllib.error.URLError as e:
        raise Refused(f"Could not reach GitHub: {e.reason}.")
    except ValueError:
        raise Refused("GitHub's answer about the releases was not JSON.")
    if isinstance(got, dict):
        got = [got]
    if not isinstance(got, list):
        raise Refused("GitHub's answer about the releases was not a list.")
    return [r for r in got if isinstance(r, dict) and not r.get("draft")]


def version_key(version):
    """A version directory's name as something to sort by: three numbers,
    then a release above any pre-release of it, and pre-releases by their
    parts, numbers as numbers, so dev.10 is after dev.9."""
    m = VERSION.match(version)
    nums = tuple(int(g) for g in m.groups()[:3])
    if not m.group(4):
        return nums + ((1,),)
    return nums + ((0,) + tuple((0, int(p), "") if p.isdigit() else (1, 0, p)
                                for p in m.group(4).split(".")),)


def asset_urls(release):
    return {a.get("name"): a.get("browser_download_url")
            for a in release.get("assets", []) if a.get("name")}


def carried(release):
    """The image sets a release carries whole, in FAMILIES order. A set with
    some of its parts and not others, or a release with none of the
    reference set's parts and no other set, is half published, and refused
    rather than skipped, because the reason is worth reading."""
    assets = asset_urls(release)
    sets = []
    others = any(assets.get(prefix(f) + p) for f in FAMILIES[1:] for p in PARTS)
    for fam in FAMILIES:
        have = [p for p in PARTS if assets.get(prefix(fam) + p)]
        if len(have) == len(PARTS):
            sets.append(fam)
        elif have or (fam == FAMILIES[0] and not others):
            missing = [prefix(fam) + p for p in PARTS if p not in have]
            raise Refused(f"Release {release.get('tag_name')} is missing "
                          f"{', '.join(missing)}.")
    return sets


def parse_sums(text):
    sums = {}
    for n, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        m = SUM_LINE.match(line)
        if not m:
            raise Refused(f"SHA256SUMS line {n} is not '<sha256>  <name>'.")
        sums[m.group(2)] = m.group(1).lower()
    return sums


def installed_sums(dest, version):
    f = os.path.join(dest, version, SUMS)
    if not os.path.isfile(f):
        return None
    with open(f, encoding="utf-8") as fh:
        return fh.read()


def complete(dest, version, families, sums=None):
    """Every part of every set on disk, and every version.txt the release's
    sums name: one that was named and not installed would leave the board's
    manifest on the directory's name for ever, since the sums would go on
    matching."""
    for fam in families:
        d = os.path.join(dest, version, fam)
        if not all(os.path.isfile(os.path.join(d, p)) and os.path.getsize(os.path.join(d, p))
                   for p in PARTS):
            return False
        if sums and prefix(fam) + VERSION_TXT in sums \
                and not os.path.isfile(os.path.join(d, VERSION_TXT)):
            return False
    return True


def set_complete(path):
    """Whether one set folder on disk holds all five parts, the way the
    server decides a set is there to offer."""
    return all(os.path.isfile(os.path.join(path, p)) and os.path.getsize(os.path.join(path, p))
               for p in PARTS)


def stage(dest, release, version, families):
    """Download and check everything into a staging directory. Returns its
    path; the caller moves it into place. Raises Refused, having removed it,
    on anything wrong."""
    assets = asset_urls(release)
    for n in (NOTICES, SUMS):
        if not assets.get(n):
            raise Refused(f"Release v{version} is missing {n}.")

    staging = tempfile.mkdtemp(prefix=".incoming-", dir=dest)
    try:
        sums_text = fetch(assets[SUMS], "application/octet-stream").decode("utf-8", "replace")
        sums = parse_sums(sums_text)
        wanted = [(fam, p, prefix(fam) + p) for fam in families for p in PARTS]
        unsummed = [a for _f, _p, a in wanted if a not in sums]
        if NOTICES not in sums:
            unsummed.append(NOTICES)
        if unsummed:
            raise Refused(f"SHA256SUMS has no line for {', '.join(unsummed)}.")
        # version.txt is optional, and only ever installed as checked: one
        # the sums do not cover is left out, not trusted. One the sums name
        # and the release does not have is a set half published, the same as
        # a missing part: the board's manifest would carry the wrong version.
        for fam in families:
            a = prefix(fam) + VERSION_TXT
            if a in sums and not assets.get(a):
                raise Refused(f"Release v{version} is missing {a}.")
            if assets.get(a) and a in sums:
                wanted.append((fam, VERSION_TXT, a))
        for fam in families:
            os.makedirs(os.path.join(staging, fam))
        for fam, name, asset in wanted + [(None, NOTICES, NOTICES)]:
            try:
                blob = fetch(assets[asset], "application/octet-stream")
            except urllib.error.URLError as e:
                raise Refused(f"Could not download {asset}: {getattr(e, 'reason', e)}.")
            if not blob:
                raise Refused(f"{asset} downloaded empty.")
            got = hashlib.sha256(blob).hexdigest()
            if got != sums[asset]:
                raise Refused(f"{asset} does not match SHA256SUMS "
                              f"(got {got[:16]}..., expected {sums[asset][:16]}...). "
                              "A download went wrong, or the release was changed "
                              "after its sums were written.")
            if name == "storage.bin" and SECRET.search(blob):
                raise Refused(f"{asset} carries a password, a Wi-Fi key or a "
                              "directory token. It was built from a working tree, "
                              "not a fresh clone, and must not be published.")
            if name == VERSION_TXT:
                line = blob.decode("ascii", "replace").strip()
                if len(blob) > 128 or not SHOWN.match(line):
                    raise Refused(f"{asset} is not one line naming a version.")
            where = os.path.join(staging, fam or "", name)
            with open(where, "wb") as fh:
                fh.write(blob)
        with open(os.path.join(staging, SUMS), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(sums_text if sums_text.endswith("\n") else sums_text + "\n")
        date = str(release.get("published_at") or "")[:10]
        if re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            with open(os.path.join(staging, "release.txt"), "w",
                      encoding="utf-8", newline="\n") as fh:
                fh.write(date + "\n")
        # Readable by the service, whatever umask this ran under.
        for root, dirs, files in os.walk(staging):
            os.chmod(root, 0o755)
            for f in files:
                os.chmod(os.path.join(root, f), 0o644)
        return staging
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def put_in_place(dest, staging, version):
    """Rename the staged release to firmware/<version>. A release already
    there under that version is moved aside first and put back if the rename
    fails, so there is no moment with neither."""
    target = os.path.join(dest, version)
    aside = None
    if os.path.exists(target):
        aside = os.path.join(dest, f".old-{version}-{int(time.time())}")
        os.rename(target, aside)
    try:
        os.rename(staging, target)
    except OSError:
        if aside:
            os.rename(aside, target)
        raise
    if aside:
        shutil.rmtree(aside, ignore_errors=True)


def prune(dest, keep_also=()):
    """Keep the newest KEEP releases, whatever on disk is serving a board,
    and anything in keep_also, and remove the rest. Only directories named
    like a version are ever considered, so README.md and anything else a
    person put there are left alone.

    Serving is read off the disk the way the server reads it, not off what
    GitHub listed today: for each board, the newest release here carrying
    its set, and failing that the newest pre-release here carrying it. So a
    preview copied in by hand stays until a release or a newer preview here
    carries its board, and an older release still serving a board stays
    past the newest KEEP."""
    found = []
    for name in os.listdir(dest):
        m = VERSION.match(name)
        if m and os.path.isdir(os.path.join(dest, name)):
            found.append((version_key(name), name, bool(m.group(4))))
    found.sort(reverse=True)
    keep = set([name for _k, name, pre in found if not pre][:KEEP]) | set(keep_also)
    for fam in FAMILIES:
        full = [n for _k, n, pre in found
                if not pre and set_complete(os.path.join(dest, n, fam))]
        pre = [n for _k, n, p in found if p and fam not in NO_PREVIEW
               and set_complete(os.path.join(dest, n, fam))]
        if full or pre:
            keep.add((full or pre)[0])
        # A board that takes a preview ahead of its release keeps the newest
        # preview here that is newer than that release, as the server offers.
        if full and fam in AHEAD:
            top = version_key(full[0])
            ahead = [n for _k, n, p in found if p and version_key(n) > top
                     and set_complete(os.path.join(dest, n, fam))]
            if ahead:
                keep.add(ahead[0])
    gone = []
    for _key, name, _pre in found:
        if name not in keep:
            shutil.rmtree(os.path.join(dest, name), ignore_errors=True)
            gone.append(name)
    return gone


def install(dest, release, version, families, say):
    """One release into place. True when it was installed now, False when
    it was there already; Refused when it could not be."""
    have = installed_sums(dest, version)
    if have is not None and complete(dest, version, families, parse_sums(have)):
        sums_url = asset_urls(release).get(SUMS)
        if sums_url:
            remote = fetch(sums_url, "application/octet-stream").decode("utf-8", "replace")
            if parse_sums(remote) == parse_sums(have):
                say(f"Firmware {version} is already installed.")
                return False
    staging = stage(dest, release, version, families)
    put_in_place(dest, staging, version)
    return True


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser(description="Install the newest firmware releases.")
    ap.add_argument("--dest", default=os.environ.get(
        "DIRECTORY_FIRMWARE_DIR", os.path.join(here, "firmware")))
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    dest = os.path.abspath(args.dest)

    def say(msg):
        if not args.quiet:
            print(msg)

    def refused(version, why):
        print(f"Firmware {version} not installed: {why}" if version
              else f"Firmware release not updated: {why}")
        print("The release already installed, if there is one, is untouched.")

    try:
        if not os.path.isdir(dest):
            raise Refused(f"{dest} is not a directory.")
        releases = list_releases()
    except Refused as e:
        refused("", e)
        return 1
    except Exception as e:                               # noqa: BLE001
        refused("", f"{type(e).__name__}: {e}")
        return 1

    failed = False
    # (release, version, the sets it carries, the ones it is wanted for,
    # whether it is a preview), in the order they are installed.
    wanted = []
    served = set()
    # Every board some release names at all, whole or not. A preview never
    # serves one of these: a broken release leaves its board on whatever is
    # installed, and never hands it to a pre-release.
    claimed = set()
    newest_named = {}

    # The releases, newest version first. Version order rather than the
    # order GitHub lists them in, which is when each was made: a patch to an
    # older line published after a newer release is not the newest release,
    # and the site orders them by version too. The one GitHub lists first is
    # the one a sysop just published, so a bad tag there is reported; an old
    # one further down is only skipped.
    full = []
    first = True
    for r in releases:
        if r.get("prerelease"):
            continue
        tag = str(r.get("tag_name", ""))
        m = TAG.match(tag)
        assets = asset_urls(r)
        named = [FAMILIES[0]] + [f for f in FAMILIES[1:]
                                 if any(assets.get(prefix(f) + p) for p in PARTS)]
        claimed.update(named)
        # The newest release naming each board, whole or not, for AHEAD: a
        # preview goes ahead of a board's release only when it is newer than
        # every release naming it, so a broken release is never overtaken
        # by an older pre-release.
        if m and not m.group(4):
            for f in named:
                if f not in newest_named or version_key(tag[1:]) > newest_named[f]:
                    newest_named[f] = version_key(tag[1:])
        if not m or m.group(4):
            if first:
                failed = True
                refused("", f"The latest release is tagged {tag!r}, not vX.Y.Z.")
            else:
                say(f"Release {tag} not used: it is not tagged vX.Y.Z.")
            first = False
            continue
        first = False
        full.append((version_key(tag[1:]), r, tag[1:]))
    full.sort(key=lambda c: c[0], reverse=True)

    # The newest release is installed, every set it carries. A board it does
    # not carry is served from the newest older release that does, so an
    # ESP32-only patch to an older line never takes a board off the release
    # that carries it.
    for i, (_k, r, version) in enumerate(full):
        try:
            fams = carried(r)
        except Refused as e:
            if i == 0:
                failed = True
                refused("", e)
            else:
                say(f"Release {version} not used: {e}")
            continue
        needed = [f for f in fams if f not in served]
        if i == 0 or needed:
            wanted.append((r, version, fams, needed, False))
            served.update(fams)

    # A board no release carries: the newest pre-release that carries it,
    # under its real name. A pre-release tagged like a release would land in
    # a directory the site takes for a release, so it is never used.
    candidates = []
    for r in releases:
        if not r.get("prerelease"):
            continue
        tag = str(r.get("tag_name", ""))
        m = TAG.match(tag)
        if not m or not m.group(4):
            continue
        try:
            fams = carried(r)
        except Refused as e:
            say(f"Pre-release {tag} not used: {e}")
            continue
        candidates.append((version_key(tag[1:]), r, tag[1:], fams))
    candidates.sort(key=lambda c: c[0], reverse=True)
    # And a board in AHEAD that a release carries: the newest pre-release
    # carrying it that is newer than every release naming it, beside its
    # release (site 1.3.7).
    ahead_done = set()
    for k, r, version, fams in candidates:
        needed = [f for f in fams
                  if (f not in served and f not in claimed and f not in NO_PREVIEW)
                  or (f in AHEAD and f in served and f not in ahead_done
                      and f in newest_named and k > newest_named[f])]
        if needed:
            wanted.append((r, version, fams, needed, True))
            served.update(needed)
            ahead_done.update(f for f in needed if f in AHEAD)

    if not wanted and not failed:
        refused("", f"GitHub has no public release of {REPO} (the list is empty). "
                    "The repository is private until 1.0.0, or has not published "
                    "a release yet.")
        return 1

    serving = []
    for r, version, fams, needed, preview in wanted:
        try:
            if install(dest, r, version, fams, say):
                what = ""
                if preview:
                    what = (" (a preview, for the " + " and ".join(needed) + " image"
                            + ("s" if len(needed) > 1 else "") + ")")
                print(f"Installed firmware {version}{what} for the browser installer.")
        except Refused as e:
            failed = True
            refused(version, e)
        except Exception as e:                           # noqa: BLE001
            failed = True
            refused(version, f"{type(e).__name__}: {e}")
        # Kept by prune whatever its age: an older release still serving a
        # board, and the preview serving one.
        if os.path.isdir(os.path.join(dest, version)):
            serving.append(version)
    # Anything that could not be installed leaves what was serving its board
    # where it is: prune reads that off the disk. And after any refusal every
    # pre-release already here is kept as well, until a run goes through.
    if failed:
        serving += [n for n in os.listdir(dest)
                    if VERSION.match(n) and VERSION.match(n).group(4)]
    gone = prune(dest, keep_also=serving)
    if gone:
        print("Removed older releases: " + ", ".join(sorted(gone)) + ".")
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(main())
