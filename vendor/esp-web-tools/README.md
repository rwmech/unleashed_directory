<!--
 ===========================================================================
  µnleashed BBS directory
 ===========================================================================

 File:         vendor/esp-web-tools/README.md
 Purpose:      Where the vendored ESP Web Tools bundle came from, how it was
               checked, and how to move to a newer version.

 Copyright 2026 - Robert Mech
 License:      GNU General Public License v2 or later (this file only; the
               bundle beside it is Apache License 2.0, see its LICENSE)
 SPDX-License-Identifier: GPL-2.0-or-later
 ===========================================================================
-->

# ESP Web Tools, vendored

The browser installer on `/install` is [ESP Web Tools](https://github.com/esphome/esp-web-tools),
served from this site rather than from a CDN. This directory is the only
third-party code in the repository. The only other JavaScript on the site is
the dozen inline lines on `/connected`, written here (`CONNECTED_JS` in
`server.py`).

## What is here

```
vendor/esp-web-tools/
  README.md                    this file
  10.4.0/                      one directory per version, named for it
    install-button.js          the entry point the page loads
    install-dialog-*.js        the dialog, esptool-js and the Improv SDK
    index-*.js, styles-*.js    shared chunks
    esp32*-*.js, stub_flasher_*-*.js
                               per-chip code and Espressif's flasher stubs,
                               loaded only for the chip that is plugged in
    LICENSE                    ESP Web Tools' own, Apache License 2.0
    THIRD_PARTY_LICENSES.txt   the licences of the libraries built into it
    SHA256SUMS                 one line per file above
```

The `.js` files are the package's `dist/web` directory, complete, and
unmodified except for one file, below. Every import between them is relative (`./install-dialog-....js`),
so they load from this one directory and need nothing from anywhere else. The
only absolute URLs inside them are links the dialog shows a person (driver
downloads, the project's own page), never something it fetches.

`server.py` serves them at `/install/esp-web-tools/<version>/<name>` with a
JavaScript content type, which a module script needs or the browser refuses
it. Only names shaped like a chunk (`[A-Za-z0-9_-]+.js`) and the two licence
files are served; `EWT_VERSION` in `server.py` says which directory.

## The one modified file

`10.4.0/install-dialog-im156JnI.js` is changed, and says so in a notice at
its top, as section 4(b) of the Apache License 2.0 requires. Upstream's
SHA-256 for it is
`6dcfc30fb4bbf18e19a141c5eb9a694edafc5d4480b45762c221173f47effdb5`;
`SHA256SUMS` carries the modified file's.

After the Wi-Fi step the dialog offers the link the device sends over
Improv, labelled "Visit Device". A µnleashed board sends
`telnet://<address>:6400`, which no browser opens. So in both places the
dialog shows that link: when it starts `telnet://`, it goes to
`/connected#<address>:<port>` on this site and is labelled "Telnet details".
Any other link is left exactly as upstream has it. The address rides in the
fragment, which a browser never sends, so it is not in this server's logs.

The change is two expressions, each made twice, with a patch that refused
to run on anything but the upstream file. Moving to a new version means
making it again by hand in that version's dialog chunk: search for
`Visit Device`, and check the result by opening the dialog.

## How 10.4.0 was fetched and checked

On 2026-09-23, `10.4.0` was the `latest` tag on npm, published 2026-07-15.

```sh
curl -s https://registry.npmjs.org/esp-web-tools | python3 -c \
  "import sys,json; print(json.load(sys.stdin)['dist-tags'])"
curl -sO https://registry.npmjs.org/esp-web-tools/-/esp-web-tools-10.4.0.tgz
# the registry's integrity field for 10.4.0:
# sha512-3pwkeFFm5Fj7UQo8SJNYK5RXrtNCpq6X9QoI6bMT4GBZWgrJqjn0YvM9ihG74BtMoSFYXfmDtkehuxe50PTMPQ==
python3 -c "import hashlib,base64; print('sha512-' + base64.b64encode(
  hashlib.sha512(open('esp-web-tools-10.4.0.tgz','rb').read()).digest()).decode())"
tar xzf esp-web-tools-10.4.0.tgz
cp package/dist/web/*.js package/LICENSE vendor/esp-web-tools/10.4.0/
```

`THIRD_PARTY_LICENSES.txt` was assembled the same way: each library's npm
tarball, checked against its registry SHA-512, with its licence file copied out
whole. The bundle does not record exactly which version of each library it was
built from, so each text comes from the newest release inside the range
ESP Web Tools 10.4.0 declares. A licence file does not change between patch
releases of these projects.

| Library | Declared licence | Why it is in the bundle |
|---|---|---|
| esptool-js | Apache-2.0 | talks the ESP32 ROM bootloader's protocol, with Espressif's flasher stubs |
| improv-wifi-serial-sdk | Apache-2.0 | the Wi-Fi step, over the same serial line |
| @material/web | Apache-2.0 | the dialog's buttons, lists and fields |
| lit, lit-html, lit-element, @lit/reactive-element, @lit/context | BSD-3-Clause | the web component base |
| tslib | 0BSD | TypeScript's runtime helpers |
| pako | MIT AND Zlib | compresses the image on the way to the chip |
| atob-lite | MIT | base64 decoding inside esptool-js |

## Moving to a newer version

1. Check what is current and read its release notes on
   [GitHub](https://github.com/esphome/esp-web-tools/releases). A new major
   version can rename manifest keys. The keys `server.py` writes are pinned in
   `selftest.py`, and `src/const.ts` in the package's tarball is where the
   installer defines them, so compare the two.
2. Fetch the tarball, check it against the registry's `integrity` field as
   above, and copy `dist/web/*.js` and `LICENSE` into a new directory named for
   the version. Rebuild `THIRD_PARTY_LICENSES.txt` if the dependency list in
   its `package.json` changed.
3. Write `SHA256SUMS` by running
   `sha256sum LICENSE THIRD_PARTY_LICENSES.txt *.js > SHA256SUMS` inside the
   new directory. The suite checks every file against it, and checks that no
   file is there without a line in it.
4. Change `EWT_VERSION` in `server.py`, run `python selftest.py`, and flash a
   real board from a local copy of the page before pushing. `127.0.0.1` counts
   as a secure context, so Web Serial works there.
5. Delete the old version's directory in the same commit. Only the directory
   `EWT_VERSION` names is ever served.

`.gitattributes` declares the version directories binary, so git never rewrites
a line ending inside them and `SHA256SUMS` stays true on every checkout.
