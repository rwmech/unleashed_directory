#!/usr/bin/env python3
"""
===========================================================================
 µnleashed BBS directory
===========================================================================

File:         deploy/fetch_release.py
Purpose:      Fetch the newest public release of the firmware from GitHub
              and put it where /install looks for it. The last hop of the
              build pipeline: the firmware repository builds and publishes a
              release, and this installs it on the directory. update.sh runs
              it; it can also be run by hand.

Usage:        python3 deploy/fetch_release.py [--dest DIR] [--quiet]
                --dest    the firmware directory the server reads
                          (default: $DIRECTORY_FIRMWARE_DIR, else firmware/
                          beside this script's repository)
                --quiet   say nothing unless something changed or failed

The contract, which the firmware side publishes to:
  - a GitHub Release of rwmech/unleashed_BBS, tagged vX.Y.Z, public
  - assets bootloader.bin, partitions.bin, ota_data_initial.bin,
    firmware.bin, storage.bin, THIRD_PARTY_NOTICES.md and SHA256SUMS
  - SHA256SUMS in sha256sum's own format, one line per other asset

What it does, in the order that keeps a bad download harmless:
  1. asks GitHub for the latest release (public releases only: no token,
     because until 1.0.0 the repository is private and after it nothing
     needs one)
  2. downloads every asset into a staging directory inside the firmware
     directory, so the final move is a rename on one filesystem
  3. checks every file against SHA256SUMS, and checks the screens image
     carries no password, Wi-Fi key or token
  4. only then moves the release into firmware/<version>/, as the installer
     expects it: esp32/<the five parts>, THIRD_PARTY_NOTICES.md, release.txt
  5. keeps the newest two versions and removes the rest

Anything that fails before step 4 deletes the staging directory and leaves
the release already there exactly as it was.

Exit codes:   0 installed, or already had it
              1 nothing changed, and here is why

Copyright 2026 - Robert Mech
License:      GNU General Public License v2 or later
SPDX-License-Identifier: GPL-2.0-or-later
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
# Overridable so the self-test can point it at a release served from
# 127.0.0.1. Nothing else about the script changes when it is.
API = os.environ.get("UNLEASHED_RELEASE_API",
                     "https://api.github.com/repos/" + REPO + "/releases/latest")
PARTS = ("bootloader.bin", "partitions.bin", "ota_data_initial.bin",
         "firmware.bin", "storage.bin")
NOTICES = "THIRD_PARTY_NOTICES.md"
SUMS = "SHA256SUMS"
CHIP = "esp32"
KEEP = 2
TAG = re.compile(r"^v(\d{1,3})\.(\d{1,3})\.(\d{1,4})$")
VERSION = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,4})$")
SUM_LINE = re.compile(r"^([0-9a-fA-F]{64}) [ *]([^\s/\\]+)$")
# A 4 MB flash cannot hold a larger part, so anything bigger is not ours.
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


def latest_release():
    try:
        return json.loads(fetch(API, "application/vnd.github+json").decode("utf-8"))
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
        raise Refused(f"GitHub answered {e.code} for the latest release.")
    except urllib.error.URLError as e:
        raise Refused(f"Could not reach GitHub: {e.reason}.")
    except ValueError:
        raise Refused("GitHub's answer about the latest release was not JSON.")


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


def complete(dest, version):
    d = os.path.join(dest, version, CHIP)
    return all(os.path.isfile(os.path.join(d, p)) and os.path.getsize(os.path.join(d, p))
               for p in PARTS)


def stage(dest, release, version):
    """Download and check everything into a staging directory. Returns its
    path; the caller moves it into place. Raises Refused, having removed it,
    on anything wrong."""
    assets = {a.get("name"): a.get("browser_download_url")
              for a in release.get("assets", []) if a.get("name")}
    missing = [n for n in PARTS + (NOTICES, SUMS) if not assets.get(n)]
    if missing:
        raise Refused(f"Release v{version} is missing {', '.join(missing)}.")

    staging = tempfile.mkdtemp(prefix=".incoming-", dir=dest)
    try:
        sums_text = fetch(assets[SUMS], "application/octet-stream").decode("utf-8", "replace")
        sums = parse_sums(sums_text)
        unsummed = [n for n in PARTS + (NOTICES,) if n not in sums]
        if unsummed:
            raise Refused(f"SHA256SUMS has no line for {', '.join(unsummed)}.")
        os.makedirs(os.path.join(staging, CHIP))
        for name in PARTS + (NOTICES,):
            try:
                blob = fetch(assets[name], "application/octet-stream")
            except urllib.error.URLError as e:
                raise Refused(f"Could not download {name}: {getattr(e, 'reason', e)}.")
            if not blob:
                raise Refused(f"{name} downloaded empty.")
            got = hashlib.sha256(blob).hexdigest()
            if got != sums[name]:
                raise Refused(f"{name} does not match SHA256SUMS "
                              f"(got {got[:16]}..., expected {sums[name][:16]}...). "
                              "A download went wrong, or the release was changed "
                              "after its sums were written.")
            if name == "storage.bin" and SECRET.search(blob):
                raise Refused("storage.bin carries a password, a Wi-Fi key or a "
                              "directory token. It was built from a working tree, "
                              "not a fresh clone, and must not be published.")
            where = os.path.join(staging, CHIP if name in PARTS else "", name)
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


def prune(dest):
    """Keep the newest KEEP versions and remove the rest. Only directories
    named like a version are ever considered, so README.md and anything else
    a person put there are left alone."""
    found = []
    for name in os.listdir(dest):
        m = VERSION.match(name)
        if m and os.path.isdir(os.path.join(dest, name)):
            found.append((tuple(int(g) for g in m.groups()), name))
    found.sort(reverse=True)
    gone = []
    for _key, name in found[KEEP:]:
        shutil.rmtree(os.path.join(dest, name), ignore_errors=True)
        gone.append(name)
    return gone


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser(description="Install the newest firmware release.")
    ap.add_argument("--dest", default=os.environ.get(
        "DIRECTORY_FIRMWARE_DIR", os.path.join(here, "firmware")))
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    dest = os.path.abspath(args.dest)

    def say(msg):
        if not args.quiet:
            print(msg)

    try:
        if not os.path.isdir(dest):
            raise Refused(f"{dest} is not a directory.")
        release = latest_release()
        tag = str(release.get("tag_name", ""))
        m = TAG.match(tag)
        if not m:
            raise Refused(f"The latest release is tagged {tag!r}, not vX.Y.Z.")
        version = ".".join(m.groups())
        if complete(dest, version) and installed_sums(dest, version) is not None:
            sums_url = next((a.get("browser_download_url") for a in release.get("assets", [])
                             if a.get("name") == SUMS), None)
            if sums_url:
                remote = fetch(sums_url, "application/octet-stream").decode("utf-8", "replace")
                if parse_sums(remote) == parse_sums(installed_sums(dest, version)):
                    say(f"Firmware {version} is already installed.")
                    return 0
        staging = stage(dest, release, version)
        put_in_place(dest, staging, version)
        gone = prune(dest)
        print(f"Installed firmware {version} for the browser installer.")
        if gone:
            print("Removed older releases: " + ", ".join(sorted(gone)) + ".")
        return 0
    except Refused as e:
        print(f"Firmware release not updated: {e}")
        print("The release already installed, if there is one, is untouched.")
        return 1
    except Exception as e:                               # noqa: BLE001
        print(f"Firmware release not updated: {type(e).__name__}: {e}")
        print("The release already installed, if there is one, is untouched.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
