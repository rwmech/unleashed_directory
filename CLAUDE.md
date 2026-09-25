# unleashed directory: project context

The directory server for µnleashed BBS. Boards post a small JSON heartbeat,
this keeps a list of the ones that are up, and serves three faces from one
process. GPL v3 or later, same as the BBS (v2 or later until 2026-09-24).

Read PROTOCOL.md for the wire format, INSTALL.md for a fresh droplet,
README.md for what it is. This file is the process and the design history.

## Processes

Not preferences. The process. Getting these wrong wastes Rob's time.

- **A deploy that fails is retried** (1.2.1). setup.sh writes the commit it
  installed to `/srv/unleashed_directory/.installed` as its last step, and
  update.sh reinstalls whenever that is missing or is not HEAD, even with
  nothing to pull. Before this, a setup.sh that failed on the run whose pull
  moved HEAD was never run again, which is how 1.2.0 sat in the checkout
  while the site stayed old. A setup.sh that keeps failing is therefore
  retried on every update.sh run, apt-get included.
- **The wordmark is `LOGO_SVG`**, drawn at start from `LOGO_ROWS` (1.2.1), a
  cell 6 by 10 units, one rect a run. `LOGO_ROWS` stays the one source:
  brand/make_avatar.py and make_cover.py parse it out of this file, so its
  shape (`LOGO_ROWS = (` ... `)`) must not change.
- **Rob deploys. I never do.** The change goes in this repo and gets pushed;
  Rob runs `sudo /srv/unleashed_directory/deploy/update.sh` on the droplet.
  I have no SSH access and am not to go looking for a way in. "Get it on the
  website" means "get it into the repo".
- **Settings live in the systemd unit, not in the code.** `DIRECTORY_NAME`,
  the three domains, the thresholds. A change to a default in `server.py`
  does nothing on the live box unless `deploy/unleashed-directory.service`
  changes too, because systemd's value wins. This has bitten once already.
- **Tests stay on 127.0.0.1.** Never point anything at the live directory.
- **`python selftest.py` before every commit.** It is the whole test suite,
  it takes seconds, and it needs no network.
- **Drain any server stdout you capture.** The server logs one blocking
  `print` per request from the handler thread, so a `subprocess.PIPE`
  nobody reads fills after a few KB and every thread then blocks inside
  `log_message`: the server stays alive and stops answering, which reads
  exactly like a wedge under load. The suite did this for months just under
  the buffer and started timing out the moment a few checks were added.
- **CHANGELOG.md is updated in the same commit**, not afterwards.
- **Never commit** the database, or anything with a token in it.

## Shape

- Python 3 standard library only. SQLite. One file, `server.py`. No
  framework, no dependencies, because a directory nobody can afford to run
  is not a directory.
- Listens on loopback. Caddy faces the internet and holds the certificates.
- **The socket address is always Caddy's, so the caller's comes from
  `X-Forwarded-For`, and that header is believed only when the connection
  is from a trusted proxy.** `DIRECTORY_TRUSTED_PROXIES` is the list,
  loopback by default, and it lives in the systemd unit. From an untrusted
  peer the header is not read at all; from a trusted one the **rightmost**
  entry that is not itself a trusted proxy wins. The rightmost is the part
  our own proxy appended and the only part it vouches for; the leftmost is
  whatever the caller typed, and taking it is how this was wrong until
  0.11.4. Three things key off the address, so getting it wrong is not
  cosmetic: `X-Seen-Address` (a board's rough DDNS), the one listing per
  address cap, and report dedupe.
- **If the forwarded headers ever stop arriving, the directory can publish
  exactly one board.** Every heartbeat collapses to one `group_key`, so one
  listing goes public and the rest queue for ever, the fifth distinct board
  evicts the stalest, and a shared rate limit bucket 429s any two announces
  inside `DIRECTORY_MIN_SECONDS`. The server prints its trusted list at
  startup and logs one warning on an announce with no forwarded headers, so
  this is visible in the journal rather than silent.
- `role_for(host)` serves three faces from one process by Host header: the
  board list, the argument (the manifesto), and the machine-readable data.
- Pages are cached and the cache is dropped only when `settle()` actually
  moved something, so the page is never stale but is also not rebuilt for
  every reader.
- No JavaScript anywhere on the site, with exactly three exceptions, and the
  shape of the exceptions is the rule.
  **The third: the board list and /badges run `BADGE_JS`** (0.22.0, Rob
  asked for "slick selection and searching"). Both pages are whole without
  it: the filter is a `<details>` holding a GET form, so the pane opens and
  "Show boards" asks the server with no script, and /badges shows every
  row. The script adds speed and the two search boxes, which are marked
  `data-js hidden` in the markup and shown by it, because a search box that
  cannot search is a dead control. It reads the page, writes with
  `textContent` and the `hidden` attribute only, updates the URL with
  `history.replaceState`, and reads nothing from `location` but the path
  and the fragment. The suite pins both pages to exactly `BADGE_JS` and
  fails it on innerHTML, fetch, XMLHttpRequest, sendBeacon, WebSocket, eval,
  cookies, storage, timers or navigation.
  **The second: `/connected` runs a dozen inline lines written here**
  (`CONNECTED_JS`, 0.19.0). The installer's last step sends a reader to
  `/connected#<address>:<port>`, and the fragment never reaches a server,
  which is the point: a reader's LAN address is in no log here. Nothing but
  the page can read a fragment, so it is script or nothing, the same test
  the installer passed. The script reads `location.hash`, accepts a dotted
  IPv4 address and a port only, writes with `textContent` only, and sends
  nothing; the suite pins it to exactly `CONNECTED_JS` and fails on
  innerHTML, fetch, XMLHttpRequest, sendBeacon, WebSocket, eval, cookies,
  storage or navigation in it. The manifesto's two diagrams are
  inline SVG moved by CSS keyframes, the day chart is an SVG, the board
  list reloads with a meta refresh.
  **The exception: `/install` runs ESP Web Tools** (Rob, 2026-09-23: "get
  the web flasher running"). **Why it clears the bar, and nothing else
  does:** a web page cannot reach a serial port without JavaScript. Web
  Serial is a script API and there is no HTML or CSS route to it, so the
  installer is script or it is nothing. Convenience is not a reason, and
  nothing else on the site gets a script without Rob.
  **It is served from this machine, not a CDN** (since 0.15.0; it was a
  pinned unpkg URL before that): `vendor/esp-web-tools/<version>/` is the
  package's `dist/web` build, byte for byte except one file (below), served at
  `/install/esp-web-tools/<version>/` with a JavaScript content type, which
  a module script needs. All its imports are relative, so no other origin
  is involved; its only absolute URLs are links a person can click. Its
  licence and the bundled libraries' licences sit beside it and the page
  links both. `SHA256SUMS` in that directory is checked by the suite, and
  `.gitattributes` keeps the directory binary so no line ending moves.
  `vendor/esp-web-tools/README.md` is how to move to a new version.
  **One file is modified** (0.19.0, Rob; four changes by site 1.0.0, listed
  in its notice and the vendor README): `install-dialog-*.js`, where the
  device link the dialog offers after the Wi-Fi step, "Visit Device", goes
  to `/connected#<address>:<port>` and reads "Telnet details" when the
  board's Improv answer is `telnet://`, which a browser cannot open. The file
  opens with a notice saying what changed (Apache-2.0 section 4(b)), the
  vendor README records upstream's SHA-256 for it, and SHA256SUMS carries
  the modified file's. A new ESP Web Tools version needs the change made
  again: search its dialog chunk for `Visit Device`.
  **The same file carries two more changes since 0.22.1** (Rob, after his
  own update from /install offered "Install" and then "Erase device ...
  All data on the device will be lost"): the erase question reads **Start
  fresh?** with **Erase everything first**, and a manifest with
  `"unleashed_update": true` can never erase. That key comes only from
  `/install/<ver>/manifest-update.json`, behind the card's **Update my
  board** button. The erase flag has two writes in the file (the
  constructor and `_startInstall`) and one reader that erases (the argument
  `_confirmInstall` hands the flasher), and all three are forced false
  under the key; the suite pins each. **The update manifest keeps
  `new_install_prompt_erase: true`**: ESP Web Tools erases the whole chip
  by default without it, so a dialog that ignores the new key must fall
  back to asking, never to erasing. Nobody can click through the dialog in
  a test here: prove a change by reading, and by importing the chunk in a
  page in headless Chrome, constructing `ewt-install-dialog`, setting
  `_manifest` and calling its methods (the vendor README says how).
  **The bundle's path carries `EWT_REV`**, this site's own revision, and it
  goes up whenever a file in the directory changes: everything there is
  cached for a day, so a changed dialog under the old path reaches a
  browser a day late. The bare version path still answers.
  **The script is emitted only when the page carries `::: installer` *and*
  `firmware/` actually holds a release.** Both halves, so the script and
  the widget arrive together or neither does: a page with no button runs
  no code, and a button cannot appear without the code that drives it.
  That is one condition in `md_page()` rather than a flag somebody has to
  keep in step. `selftest.py` walks every other page and fails on a
  `<script>` in any of them, and fails on a script from any other origin
  on this one.
- **The installer's state is the `firmware/` directory and nothing else.**
  `server.py` walks it per render and builds the ESP Web Tools manifest
  from what it finds, so a release cannot be half-published, "nothing
  available yet" is the absence of files rather than a flag, and cutting a
  release is copying files in. The offsets come from the firmware repo's
  `partitions.csv` and its **generated** `sdkconfig.esp32dev`, live in
  `FLASH_PARTS` and `FLASH_FAMILIES`, and a bootloader offset is per chip
  family: 0x1000 on the ESP32, 0x0 on the RISC-V parts. `offset` is a
  decimal JSON number; their type is `offset: number` and a hex string
  would be handed to the flasher unparsed. Full process in
  `firmware/README.md`.
  **Releases arrive from GitHub, not from commits** (0.16.0). The firmware
  repository publishes a GitHub Release of `rwmech/unleashed_BBS`, tagged
  `vX.Y.Z`, with the ESP32's five parts `bootloader.bin`, `partitions.bin`,
  `ota_data_initial.bin`, `firmware.bin`, `storage.bin` (and, from 1.1.0,
  `version.txt` and the same six prefixed `esp32s3-` for the S3),
  `THIRD_PARTY_NOTICES.md` and `SHA256SUMS`. `deploy/update.sh` runs
  `deploy/fetch_release.py` on every run, including one where the site had
  nothing new, and that installs the latest release as (an S3 set is an
  `esp32s3/` folder beside `esp32/`, bootloader at 0x0):

  ```
  firmware/<version>/esp32/bootloader.bin         0x1000    4096
  firmware/<version>/esp32/partitions.bin         0x8000    32768
  firmware/<version>/esp32/ota_data_initial.bin   0xF000    61440
  firmware/<version>/esp32/firmware.bin           0x20000   131072
  firmware/<version>/esp32/storage.bin            0x3C0000  3932160
  firmware/<version>/THIRD_PARTY_NOTICES.md
  firmware/<version>/SHA256SUMS                   kept, for the record
  firmware/<version>/release.txt                  the release's date
  ```

  **Every file is checked against SHA256SUMS in a staging directory
  before anything moves**, and so is `storage.bin` for staff passwords, a
  Wi-Fi key or a token with a value; any failure deletes the staging
  directory and leaves the installed release as it was. The move is a
  rename on one filesystem. The newest two versions are kept. Public
  releases only, no token: the repository is private until 1.0.0, and a
  404 gets a message that says so. A fetch failure is reported and does
  not fail the site update. `firmware/<version>/` is git-ignored, so a
  fetched release never shows in `git status` and a binary cannot be
  committed by accident; `firmware/README.md` stays tracked. The suite
  runs the fetcher against a release served from 127.0.0.1, including every
  way it should refuse. Dropping files in by hand still works, for testing.
  `storage.bin` is PlatformIO's `littlefs.bin`, renamed for its partition.
  **The manifests are the server's**: it builds one a board from the five
  files and serves it at `/install/<version>/<board>/manifest.json` (and
  `manifest-update.json`), with `name` "unleashed BBS",
  `new_install_prompt_erase` true and `new_install_improv_wait_time` 30. A
  `manifest.json` on disk (release.py writes one into each folder for
  trying images by hand) is never served. A family missing any part, or
  with an empty part, is not offered.
  **Boards (site 1.2.0, Rob: "select the board type ... include an image
  for confirmation ... Small picture in the pick list").** A board is an
  image set folder, named as the firmware's `tools/release.py` names the
  build, plus an entry in `BOARDS` in server.py: its line-art picture
  (`BOARD_ART_ESP32`, `BOARD_ART_S3`, 96 x 60 units, the art classes and
  stroke weights), name, a "how to tell" line, the /hardware anchor, the
  buy link, and a "before" note in Markdown (the S3's download mode). Today
  `esp32` (the reference dev board) and `esp32s3` (the Waveshare
  ESP32-S3-LCD-1.47, bootloader at 0x0). **One manifest a board, holding
  only that board's build**: ESP Web Tools picks a build by chip family
  alone, so a combined manifest would give any ESP32-S3 the Waveshare's
  pins; with one build, the other family is refused before writing.
  `/install/<version>/manifest.json` and `manifest-update.json` still
  answer, the ESP32's alone with its folder in each path, for a page or a
  link from before 1.2.0. A second board on the same chip is a second
  folder and a second `BOARDS` row, never a shared folder.
  **The card's picker** is a fieldset of native radios (`fwboard`, ids
  `fwb<j>`), each row the picture, name, tell line and "Firmware 1.0.3";
  each board's buttons, version radios (`fwver<j>`, ids `fwv<j>_<i>`),
  version line and notices are its `.bsec.b<j>`, shown by `:has()` rules
  generated under the card. Without `:has()` the first board with a set
  stays showing. `.bd` and `.chip` were taken (badges, filter chips), which
  is why the names are `.bsec` and `.fam`: check a class name against the
  whole stylesheet before using it. The amber box moved under the buttons
  on a desktop too, and the column is 26rem, to keep both buttons on the
  first screen at 1366 x 768 (ESP32 Update ends 665px, S3 719px).
  **Versions.** A set's `version.txt`, one line exactly as the board shows
  it ("1.0.3", "1.1.0 (S3 1.0.0)", brackets because a PETSCII terminal has
  no middle dot), is the manifest's `version`, because ESP Web Tools
  compares it with Improv's answer to decide whether to offer Update.
  Without it, the folder's manifest.json version, then the directory name.
  `FIRMWARE_SHOWN` is the shape; anything else is not read.
  **Previews.** A directory named with a pre-release suffix
  (`1.1.0-dev.8`, `FIRMWARE_VER`) is a preview. `firmware_releases()` is
  releases only, so a preview is never "the newest release": no gate,
  banner or update arrow. `board_offers(dir)` gives a board the releases
  carrying its set, newest first, up to FIRMWARE_KEEP, else the newest
  preview carrying it, alone; `firmware_file()` serves only what
  `board_offers` offers, so a preview's ESP32 set is unreachable while the
  ESP32 has a release. The picker says "1.1.0 preview (S3 1.0.0)" and the
  line under the buttons the exact version.
  **The fetcher reads `/releases`, not `/releases/latest`** (which leaves
  out pre-releases; a single release object is still read as a list of
  one). It installs the newest release by version (not GitHub's list order)
  with every set it carries (the ESP32's assets plain, another's prefixed:
  `esp32s3-firmware.bin`, `esp32s3-version.txt`); for each board that
  release does not carry, the newest older release carrying it; and only
  for a board no release names at all, the newest pre-release carrying it,
  under its own name. A pre-release tagged like a release is never used. A
  half-published set, a version.txt the sums name but the release lacks, or
  a bad version.txt refuses that release; after any refusal every preview
  on disk is kept. Prune keeps the newest two releases plus whatever is
  serving a board **read off the disk the way board_offers reads it** (the
  newest release here carrying the set, else the newest preview here), not
  off what GitHub listed today, so a preview copied in by hand is not
  deleted by the nightly run while it is the only copy (code review,
  2026-09-24).
  **/hardware** is `pages/hardware.md`, the tested boards: `::: board`
  then the folder name draws `board_html()`, the picture at 9rem, the
  build /install offers, the chip, the tell line and the buy link, from
  `BOARDS` and the disk, so the page and the picker cannot disagree. A
  board is listed as tested once a build has actually run on it.
  **Boards on the way are `SOON_BOARDS`** (1.2.4, the two camera boards):
  the same `::: board` block, a `status` line in place of a version, a
  `camera` row, no buy link, and deliberately not in `BOARDS`, so the
  picker and the fetcher ignore them. When one ships, move it to
  `BOARDS` with its image-set folder; the Freenove shares the ESP32's
  chip family, so the picker has to ask which board.
  **/camera, /different and /roadmap** (1.2.4). /camera owns camera
  usage and says "not settled yet" for any default the firmware plan
  leaves open. /different claims no "only": espbbs runs a BBS on an
  ESP8266, and each comparison links its source. /roadmap's drawing is
  `ROADMAP` in server.py, drawn twice (across above 900px, down below);
  change a station there and in pages/roadmap.md together, only what the
  firmware's CLAUDE.md has decided, and never a date.
  **The sysop password on /install** (1.0.0, Rob): a board ships with one
  default password, the sysop's, `unleashed`. It works only from the
  board's own network and only until changed; the first sign-up or login
  from the same network asks for it and then for a password of the
  caller's own; the board will not list itself while it is still set. The
  page says all of that and says "local only" is a guard, not a wall,
  because a router that rewrites forwarded traffic can make an outside
  caller look local. These are the firmware side's facts for 1.0.0, not
  read off 0.22.3, which predates them: re-read them against the firmware
  when 1.0.0 is tagged.
  **A board that runs 0.22.1 or later is updated without the erase
  question**: ESP Web Tools matches the firmware name the board reports
  over Improv against the manifest `name` and goes straight to Update. A
  release that moves a partition needs deciding before it is cut.
- `pages/*.md` are written in a deliberately small Markdown dialect that
  `md_render()` implements in about sixty lines. What exists: `#`, `##`,
  `###`, `- ` bullets, `1. ` ordered lists, `> ` blockquotes (consecutive
  lines are **one** warning box, not one each), fenced code, pipe tables,
  and inline `**bold**`, `` `code` `` and `[links](/path)`. A bullet or a
  step wraps by indenting the continuation two spaces. A blockquote's first
  line can be `[!NOTE]` for the calm box or `[!TIP]` for the inviting one,
  instead of the amber default: most blockquotes here are genuine warnings,
  which is why amber is the default, and a reassurance or an invitation in
  the warning colour says the opposite of the words inside it. The markers
  are GitHub's, the colours are this site's, and `[!TIP]` is `--dial`
  rather than GitHub's green because green here means a board is up and
  means nothing else. **`[!TIP]` is not a small note in a friendly colour**:
  it is the full width invitation box with the `-->` marker at its right
  edge, and it is loud on purpose. A quiet remark that is not a warning is
  `[!NOTE]`. What does not exist, on purpose: nested lists, images, inline
  HTML, headings below `###`.
  **Cards**, added for `/kids`: `::: cards` ... `:::` is a grid of short
  boxes, each `## ` inside it starting one, and `::: hero` is the same with
  one full width card in the warm colours. Inside a card, `?? Summary`
  opens a `<details>` that runs to the end of that card, one per card and
  always last, which is the only shape a card wants and means this needed
  no nested block parsing. `!! file.png | alt text` is the card's picture
  and **renders nothing at all until the file exists**, so the page is
  correct today with `static/kids/` empty. Inline `*italics*` came with
  them, after `**bold**` so the two cannot collide.
  Why cards exist at all: the retro terminal look signals nothing to a ten
  year old. Everywhere else it is doing real work because the audience
  recognises it; on that one page it asked a reader to decode an
  unfamiliar visual language before being given a reason to care.
  **`<!-- ... -->` is a comment and never renders**, for a note that
  belongs beside the words it is about (it held the sysop password TODO on
  /install until 1.0.0 answered it). It must start a line outside a fence or a card, and the suite
  counts openers against closers in every page, because an unclosed one
  swallows the rest of the page.
  **`::: installer` ... `:::`** is the third block and the only one that is
  not prose: it renders the install card, or an honest account of why
  there is nothing to flash. What the card offers (button, version line,
  notices, the older release as a radio choice) depends on what is in
  `firmware/` rather than on what somebody typed into the page. Since
  0.19.0 the Markdown inside the block is the card's amber "before you
  start" box, so the words stay in the page. `:::`
  blocks dispatch through `md_block()`; an unknown name after `:::` still
  falls through to a paragraph so a typo is visible rather than swallowing
  the rest of the page.
  **`::: install-top` ... `:::`** (0.19.0) wraps the top of /install: what
  comes before the `::: installer` inside it is the intro (title and lead),
  then the card, then the steps. That markup order is what a phone and a
  screen reader get; from 901px the stylesheet makes it two columns with the
  card on the right, spanning both rows, sticky. It counts `:::` pairs, so
  it holds drawings. The card is level with the title, not the steps: the
  amber box as written is seven lines and anything lower put the button
  under the fold at 1366 x 768. Re-measure the button after changing the
  box's words.
  **`::: cta`** (0.19.0) is a page's one primary action: the first line
  that is only a link is the filled button, the second is an outlined one
  beside it (they stack on a phone, filled first), anything else is the
  note under both. One per page. /build and /setup have one: **Visit the
  web installer** and **Build from source**. The board list has none since
  0.20.1 (below): no full size button belongs in its flow, and the suite
  fails on one there.
  **A button that goes somewhere says where it goes, and only the button
  on /install says "Install"** (Rob, 0.19.1). 0.19.0 labelled the
  navigation "Install from your browser", which landed on a page with a
  second button to press: two presses for one action. The suite fails on
  any cta button whose label contains Install.
  **`::: next`** (1.2.2, Rob: "Need clearer calls to action. The blue
  blends in") is a section's next step: one or two lines that are a link
  and nothing else, each an outlined button (`a.go`), and nothing else in
  the block. One a section at most, and only where the link is what a
  reader does next; a reference stays a link in its sentence. It goes after
  a list, never inside one. The suite fails on two in one section and on a
  label with Install in it. Class `go` and not `btn2`, because the cta pair
  is counted by those names.
  **A page's title is never a sentence's subject** (1.2.2): "Tested boards
  has the two" read as a typo to anybody who had not seen that page. Say
  what is there and link the words that name it ("the tested boards page
  has", "choose from [the two tested boards]"). The suite scans every page.
  **A body link is marked by its underline** (1.2.2): --dial on --ink is
  1.02:1, and no blue 4.5:1 on the page can be 3:1 from the text, so the
  underline is the cue and must never be taken off an in-text link.
  **`::: installer-terms`** is ESP Web Tools' licence line, under "Doing it
  the other way", and nothing when there is no release.
  **`::: connected`** is the address box on /connected with its script; the
  Markdown inside it is what shows when there is no address.
  **A fenced block written ```` ```nowrap ```` keeps its lines whole on a
  phone** (1.2.1): every other `<pre>` wraps anywhere at the 900px breakpoint,
  which broke `git clone .../unleashed_BBS` into two lines that each read as
  a command. Use it for short commands whose words must not break, not for
  long ones, which should still wrap.
  **Headings carry ids** (0.19.0): the words, lower case, every other run of
  characters one "-", unique per page across the nested renders (a
  thread-local set lives for the outermost `md_render`). Link to a section
  as `/page#its-id`.
  **A form that is not in the dialect does not fail, it renders as a
  paragraph**, which is how 53 numbered steps across the router pages were
  a wall of text for four versions with every word present and in the right
  order. If a page needs a shape the dialect does not have, use a table or
  add the shape; do not indent and hope.
- **The stylesheet lives inside the `PAGE` constant, which is consumed with
  `.format()`, so every literal `{` and `}` in the CSS is doubled.** A
  single un-doubled brace raises `KeyError` at the first page render rather
  than at import, so the server starts fine and then 500s on the first
  request. After any CSS edit, curl `/health` **and** `/`, because `/health`
  never touches `PAGE`.
- **Drawings are inline SVG, never ASCII art in a `<pre>`.** Art laid out
  in character cells has a font size for a width, so 61 columns in a 358px
  phone column meant 6px letters, and the only lever was shrinking the
  type. An SVG viewBox fits any width for free. The rules that came out of
  building the two on the manifesto: size the viewBox to the **phone**
  column (about 353px here, so 344 to 356 units lands at 1:1) and cap the
  wide case with `max-width`, because the failure runs the other way and is
  invisible on a monitor; give every shape an explicit fill, since a shape
  with none is black and black on `#0d0d12` cannot be seen; hold the art
  off the frame with a negative viewBox origin rather than by moving forty
  coordinates; and remember that one SVG cannot reflow, so anything that
  has to stack on a phone is two SVGs in a grid.
  **The small drawings (0.13.0) add three rules.** They live in `ART_CSS`,
  `ICONS`, `FIRSTCALL_ART` and `SKULL`, share the connection diagram's
  palette and stroke weights, and a Markdown page reaches one with
  `::: art` then the name on its own line then `:::`; `ART` is the list of
  names. First, **every animation is declared inside
  `@media (prefers-reduced-motion: no-preference)` and nowhere else**, so
  the markup as written is the resting state and each drawing has to make
  its point standing still. The suite fails if an `animation:` appears
  outside that block. Second, **no px in `ART_CSS`**: motion is opacity,
  rotation and skew with `transform-box: fill-box`, dash offsets against a
  `pathLength`, and translate, whose px are viewBox units and exempt; type
  sizes are `font-size` attributes on the `<text>`. Third, **a class on the
  `<svg>` itself is matched as `svg.art.i-name`, not `svg.art .i-name`**. The
  first version wrote the descendant form, nothing moved, and it looked
  finished in every still screenshot. Check motion by rendering frames and
  diffing them, with and without `--force-prefers-reduced-motion`. **Do not
  rely on `--virtual-time-budget` to advance the animations**: on
  2026-09-22 it gave identical frames seconds apart even on the manifesto,
  whose drawings certainly move, so a diff of None proved nothing. What
  works is a test-only copy of the page with a script appended that calls
  `document.getAnimations()`, pauses each and sets `currentTime`, which also
  reports how many animations are running (none, under reduced motion).
  The site itself still carries no script; the copy lives in the scratch
  directory.
- **`/author` is the one prose page that loads anything from elsewhere**:
  four photographs hotlinked from Wikimedia Commons, credited under each,
  sent with `referrerpolicy="no-referrer"`, and listed in
  THIRD_PARTY_NOTICES.md. **Wikimedia serves hotlinked thumbnails only at
  its standard widths** (20, 40, 60, 120, 250, 330, 500, 960, 1280, 1920,
  3840) and answers any other width with an HTML error page, which a
  browser shows as a broken image. `_photo()` only builds 500 and 960, and
  the suite checks every width on the page. There is no CSP on this site;
  a comment used to say there was.
- **The wordmark is a link to the front page** on every page and every
  face (0.16.0), `site_url("list", role, "/")`, with an `aria-label` of its
  own because a link whose only content is a picture is announced as the
  picture. The front page was the board list until site 1.3.0; the list
  is /directory now.
- **The front page is the pitch (site 1.3.0, marketing round 3, Rob's
  approved mockup).** `front_html()` and the `FRONT_*` constants: kicker,
  headline, a sub-head that says it runs at home or at work and that people
  join from a PC, an Android phone or an iPhone with a free app, and from old
  computers and terminals; Build yours (/install) and Try one first
  (/directory), twice; what it is, who builds one (six "For example"
  situations, never names or quotes), three steps, the history (sourced from
  the firmware README), a closing band. No list, no script, no meta refresh.
  The drawing of the board is `FRONT_BOARD_ART`, shared with the link
  preview card. Rules for its copy: true claims only, no favourite machine,
  "your community" never "your people", coming-soon features marked.
- **/directory is the board list**, headed "Find a community BBS", and the
  menu's first entry is "Find a community". Before the search sits
  `JOIN_STEP`, the free app to join with (TERMinator, MuffinTerm, SyncTERM,
  checked on their stores 2026-09-25). `site_url()` keeps a list-face path
  when there is no list domain (it used to send every list link to "/").
- **The glossary (site 1.3.0, Rob: bridge newcomers into the BBS words,
  do not remove them).** `GLOSSARY` is the one table of definitions and
  `GLOSSARY_FORMS` maps plurals and other forms to it. A page marks the
  first use it wants explained, `[[sysop]]` in Markdown and `gl("sysop")` in
  server.py (`@GL sysop@` in the manifesto). It renders a focusable span with
  a dotted underline and the definition in a `role="tooltip"` span pointed
  at by aria-describedby, shown on :focus (a tap) and on :hover only inside
  the fine-pointer query, and fixed across the foot of the screen below
  901px. No title attribute and no script. The suite fails on a `[[term]]`
  with no entry and on markup left showing.
- **Link previews (site 1.3.0)**: every page names `/og-card.png`, 1200 x
  630, with `twitter:card` summary_large_image. `brand/make_ogcard.py`
  writes `brand/unleashed-og-card.html` from LOGO_SVG and FRONT_BOARD_ART,
  and the PNG is that page screenshotted in headless Chrome at exactly
  1200x630 (the command is in the script). `OG_PAGES` gives the pages that
  have them their own og:title and og:description, applied at reply time
  like the canonical link. The avatar stays the apple-touch-icon.
- **The announcement banner** (0.20.1, Rob: "a banner up there for
  announcements ... above the directory, it should be elegant") is one
  slim yellow line between the menu and the board list's heading: a
  hairline, a lamp, small type, one sentence and one link. **The words are
  `ANNOUNCEMENT` in `server.py` and nowhere else**: one string of inline
  Markdown, `{version}` filled in with the newest release on disk, `""`
  for no banner. It must fit one line at 1366 and two at 390, so keep it
  to a sentence and a link. No buttons and no drawing in it: 0.20.0's box
  carried both and Rob called it terrible.
  `announcement_banner()` renders it only when `firmware_releases()` finds
  a release at or above `BANNER_FROM` (1.0.0) on disk, so it cannot go
  live early and appears by itself when the release lands. Absent means no
  box and no margin: the heading follows the menu directly. Yellow
  (`#ffd35c`) is used for nothing else on the site apart from focus rings:
  amber is a warning and the tip box an invitation. Call it the
  announcement banner in docs.
- **Gone in site 1.3.0, kept for the history: the top of the board
  list** (0.20.1) was a grid from 901px: the
  heading, its figures and the lead on the left, and `RUN_CARD` on the
  right, "Run your own board" in the install card's box with two compact
  buttons (Web installer, Build from source; classes `fill` and `line`, not
  the full size `btn` pair). 19.5rem, because at 18 the buttons stacked in
  Menlo and the card stood half as tall again as the text beside it. On a
  phone it follows the lead, title and buttons only. The table has to be
  the first big thing on the screen at 1366 x 768 and 390 x 844: re-measure
  after changing anything above it.
  **The figures are `stat_line()`**, "Unleashed is hosting N boards with M
  callers on right now." N is every listed board, up or quiet; M is the sum
  of the callers-on figure each up board shows. `STAT_SUFFIX` goes before
  the full stop and is empty on purpose: "across the globe" was asked for
  and left out, because nothing here knows where a board is.
  **The card's lamps** (0.20.2, Rob: the card must stand out; redrawn in
  0.22.0, below) are `span.dot`s, not pseudo-elements, because a box has
  only two of those: eight now, two lamps of a head and three beads each.
  Each follows `offset-path:inset(0 round 0.5rem)`, the card's own rounded
  rectangle, with the card `position:relative` so it is the containing
  block. The lap, `runlap`, is declared only inside the no-preference
  block. Without `offset-path` support the `@supports` block does not apply
  and each lamp sits where `top`/`left`/`right` put it. Check motion by
  pausing the animation at chosen moments in a test copy and reading each
  lamp's position: a screenshot of the running page proves nothing.
  The wash is `rgba(127, 212, 255, ...)`, which is `--dial` written out,
  because a custom property cannot take an alpha.
- **/upgrade** (0.20.2) is `pages/upgrade.md`, linked from a note that opens
  /install's steps column and from the footer's Get started row. The note
  is in the steps, not the intro, on purpose: in the intro it pushed the
  install button 170px down a phone screen. Every fact on the page was
  checked against the firmware (partitions.csv unchanged since 0.17.0, the
  Improv name in `src/main.cpp` since 0.22.1, ziparc's allow list, sd.cpp's
  `.seeded` record since 0.22.0) and the vendored install dialog (a
  recognised board gets `_startInstall(false)`, no erase question); the
  page's opening comment lists them. Re-check it when any of those change,
  and above all when a release moves a partition. **A 0.22.1 board is not
  always recognised** (Rob's own was not): the dialog gives Improv 1.5 s
  when it opens, and opening the port resets an ESP32. So since 0.22.1 the
  page sends an existing board to **Update my board**, which never asks
  and never erases whether the board is recognised or not, and never
  promises recognition.
- **Anything the server reads beside itself must be installed by
  `deploy/setup.sh`, in the same change** (the 0.17.x outage). setup.sh
  copies into `/srv/unleashed_directory` and the droplet's checkout is
  elsewhere, so a folder the server opens that setup.sh does not copy is a
  folder the live server does not have. 0.17.0 read `shots/` at import with
  no guard and every check on the droplet was a 502. The suite now starts
  `server.py` alone in an empty directory and requires it to serve, and
  requires every `Path(__file__).resolve().parent / "..."` in server.py to be
  named in setup.sh's Code section (nested paths need a recursive copy).
  Anything read at import must degrade, never raise.
- **`::: from X.Y.Z` ... `:::`** renders its Markdown only once the newest
  release on disk is at least that version, for writing about firmware that
  is not out yet. It may hold drawings (it counts `:::` pairs). A numbered
  list split by a drawing keeps counting (`<ol start>`). /install's BOOT
  button reset and CONFIG Wi-Fi fallback are `::: from 1.1.0` (they moved
  from 0.24.0 to firmware 1.0.1, then to 1.0.2 when 1.0.1 became the badge
  fields only, then to 1.1.0 in site 1.1.0 when 1.0.2 became the restore
  security fix; 1.0.0 to 1.0.2 do not have them). The gate has to move
  before the release it would wrongly light up is published.
  **`::: until X.Y.Z` ... `:::`** (site 1.1.0) is the other half: rendered
  only while the newest release on disk is older, or there is none. A
  `from`/`until` pair on the same version swaps one account for the other
  the day the release lands; /forward's one-board-per-port and /setup's
  network and announce pages use pairs on 1.1.0. Drop the `until` half once
  the release is out and settled. **A gate closes whatever was open before
  it** (paragraph, list, steps, warning, table), since site 1.1.0: before
  that a gate straight after a list rendered in front of the list, which is
  why every gate used to sit after a blank line. `flush()` is defined once,
  before the loop, so the gate can call it. A gated block is rendered on its
  own, so a list that runs into a gate is two lists: /setup's announce list
  is written out whole in each half for that reason.
- **The footer** is two rows, Get started and Reference, then the colophon:
  the site version from the newest `## X.Y.Z` in CHANGELOG.md, read once at
  start (so CHANGELOG.md is installed beside server.py), the copyright and
  "GNU GPL v3 or later", linked, each piece a nowrap span so a phone wraps
  between them. Bumping the site version is writing the changelog entry.
- **Canonical links** are filled in at reply time (`Handler.canonical`), not
  by each page builder, because a cached page is served on any face; `/about`
  and `/data` are canonical on their own faces wherever they are asked for.
- **The installer's dialog is themed from PAGE's stylesheet**: its Material
  `--md-sys-color-*` variables set on `ewt-install-dialog` and
  `ewt-no-port-picked-dialog`, which beat the component's own `:host` values.
  A new ESP Web Tools version can rename them; check by opening a dialog.
- **The /setup captures are 0.23.0's** (461cb65): CONFIG pages with
  `shots/capture/webshots.sh` at 48 columns, the first-boot setup with
  `setupshots.sh` at 80 (harness tag `webshots2 --fresh`), then
  `shots2json.py <capture> shots <config|setup> "<source>"`.
- **/donate, "Support the project"** (0.17.0): written by the copywriter,
  wired as an ordinary page. Since 0.19.0 it is "Donate", last in the menu
  and first in the footer's Reference row in the warm colour, because Rob
  could not find it as "Support" in the middle of the footer. The menu is
  ten items; measured, the tenth adds no row at 390, 1366 or 1920.
  **Buy Me a Coffee is a plain link and nothing more**: no widget, no
  script, nothing loaded from them, and the page says so in as many words,
  so embedding their button would make the page lie. The suite checks
  every `src` on the page is this site's. The page's three `<!-- -->`
  notes are for editors and must stay. Rob's line on what support buys:
  posts and development news on Buy Me a Coffee, members-only ones
  included, and never features or priority.
  **The thanks list** is `supporters.txt`, one name per line, only people
  who said yes; `::: thanks` renders it, and an empty file renders nothing
  at all, heading included, which is how it starts.
  **The cover** at the top of /donate is `brand/unleashed-cover.svg` from
  `make_cover.py`, laid out for Buy Me a Coffee's crop with an empty lower
  half on purpose. `/cover.svg` serves it cut to the band that has content
  (`COVER_H`, 310) with the frame's bottom edge redrawn; if the generator
  changes the frame or the size, the cut quietly falls back to the whole
  cover and the suite fails on the height. Not a link preview: at 4:1 it
  would be cropped by every card that shows it, so the avatar stays the
  one preview image.
  `md_meta` skips `:::` blocks and comments when it looks for a page's
  description, because a page that opens with a drawing was otherwise
  described as "::: art".
- **The avatar** is `brand/`: `make_avatar.py` draws the wordmark from
  LOGO_ROWS and the palette in this file into `unleashed-avatar.svg`, and
  the two PNGs are that screenshotted at 1024 and 512. Served at
  `/avatar.png` (og:image and twitter:image, absolute, on the list face's
  address) and `/apple-touch-icon.png`, from their own routes and not
  from `static/`, because `gallery_html()` shows every image in `static/`
  on the manifesto. Everything important is inside a centred circle, so
  round crops are safe.
- **/setup is the setup guide**: every CONFIG page and setting, with the
  board's own screens. Every fact came from the firmware source
  (`bbs_sysop.cpp` kPages and the cfg tables, the plugins' settings) and
  COMMANDS.md at 0.22.3, and the "as shipped" values from
  `data/system.cfg.example`, which is what a release's `storage.bin`
  carries. Where CONFIG's range and the parser's disagree the page gives
  the one the board honours (backup window and WHO max: 1 to 60).
  **The screens are captured, not drawn**: `shots/capture/webshots.sh`
  runs the firmware's host build in a worktree of its own (harness tag
  `webshots`, port 6670) on 127.0.0.1, drives an ANSI session at 48
  columns, and `shots2json.py` keeps each cell's character, colour and
  reverse video in `shots/<name>.json`. `shot_svg()` draws that as the
  site's art, each run a `<text>` pinned with `textLength` so the font
  cannot drift it. The suite checks every field label the captured forms
  show is explained on the page, so the prose and the screens cannot
  disagree. Re-capture when CONFIG changes; the capture says which
  version it came from.
- **The freedoms beside the wordmark (0.14.0) are the board's own words**,
  and every one is a claim. `FREEDOMS` in `server.py` is the list; the
  first five come from the board's welcome screen (`tools/mkscreens.py` in
  the firmware), the rest from the manifesto. Before adding one, check it
  is true of the board as it ships: "your data on a card you can pull" was
  considered and is false, because accounts and settings live on internal
  flash, and "no account needed" is only true while the sysop leaves
  guests on. Labels 22 characters, the line under them 26, or the panel's
  text column overflows in the widest font; the suite does the arithmetic.
  The panel shows from `min-width: 73em`, in em so a reader's larger
  default text moves the breakpoint with the wordmark, and is not shown
  below it rather than stacked, so a phone's menu does not move down.
- **A CSS or copy change is not verified until the rendered page has been
  looked at.** grep on the HTML proves a string is present, not that a rule
  applied, an element is positioned or a menu is readable. Three of the
  worst bugs found here were invisible to grep: the menu shipping with no
  stylesheet at all, the board list being 627px wide in a 358px phone
  column with the State column off the screen, and `.status span` matching
  its own nested spans so every label was split from its value.
- **The site is drawn in `rem` off one number, `:root { font-size:133% }`,
  and nothing that carries layout may be in px.** Borders and rules stay in
  px, because a hairline is a hairline at any size, and so does text inside
  an SVG viewBox, which scales with the chart. One `padding:12px` added
  later is a piece of the page that quietly stops scaling; `selftest.py`
  walks both stylesheets and fails on any other px.
  How to check a scale change, and it is the only check that answers the
  question: render the old page at `viewport / 1.33` and multiply every
  length by 1.33, then render the new page at the full viewport. They
  should agree to the decimal. Headless Chrome will not open a window
  narrower than about 500px, so a 390 measurement has to go through an
  exactly sized iframe or it is silently a 504 measurement.
  **A `px` inside an SVG viewBox is a user unit and not a layout
  length**, so it is exempt and has to be: it scales with the drawing
  already. That covers the day chart's labels, the type in the two
  manifesto diagrams, and the `translateX(164px)` that walks the marker
  along the wire, which is 164 units of a 354 unit viewBox. The exemption
  is by selector (`svg.hours text`, `svg.wire`, `svg.trace`), so a px that
  wanders out of an SVG rule is still caught.
  **The floor of a fit-to-viewport `clamp()` must stay in px.** The maximum
  and the gutter scale; the minimum exists to stop art becoming invisible,
  and in rem it grows with the root font until it is wider than the
  viewport it was meant to fit inside. At 390px with the browser text at
  200% that was a 437px wordmark in a 390px page. `selftest.py` allows
  exactly that one px and no other.
- **Badges (0.21.0, Rob).** Five optional announce fields (`system`,
  `terminals`, `guests`, `features`, `support`, in PROTOCOL.md) and three
  badges worked out here (new, steady, time listed). **Everything is in
  tables and /badges is built from the same tables**: `LETTER_BADGES`,
  `AGES` and `BADGE_COLOURS` in server.py; since site 1.1.0 the causes and
  the interests in `badges.json` (see Badge codes, below) and their
  drawings in `SUPPORT_ART` and `INTEREST_ART`, keyed by code; all gathered
  into `BADGES` (below). /badges is a searchable table per group since
  0.22.0. Changing the support list is editing an entry of `badges.json`; a
  new cause needs a drawing in `SUPPORT_ART` too. Rob reviews that list
  before it goes live, and it is the directory's list, not a board's: an
  unknown code is ignored, which is what keeps free text (and slurs) off
  the page.
  **Junk is dropped, never refused**: a bad badge field must not cost a
  listing. `tidy_label` is stricter than `tidy`: Unicode controls, format
  characters (bidi overrides, zero-width) and separators, two combining
  marks at most. `pick` reads known words from the first 16 entries.
  **Steady** is `beathours`, one row per board per UTC hour for a week,
  written by `tally()` on every accepted heartbeat. Answered over due, each
  hour capped at its own due: a cap of due plus one let a board be silent
  one hour in seven and stay steady. Needs a whole week of record
  (`tracked_since`), so boards listed before 0.21.0 could first earn it a
  week after that deploy.
  **Tooltips are CSS from `data-tip`**, on :hover and :focus (tabindex so a
  tap focuses), with an aria-label. **No title attribute**, deliberately: it
  draws the browser's tooltip over ours on a desktop and nothing on a phone.
  From 901px a badge is positioned and its tooltip hangs from it; below, it
  hangs from the row (or the legend's dt) and is capped at `100vw - 3rem`.
  The colours live on `k-` classes so the legend's colour names wear them.
  The name is `span.bname`, `width:fit-content`, because the hover dot's
  travel is `left` 0 to 100% of it.
  **Row hover and zebra** (0.21.0): odd rows after the header `#111116`, on
  the `tr` so a phone's card is striped (and the card gained 0.5rem side
  padding, the pinned state moving in with it). Hover is an outline, never a
  border, and every hover rule is inside `(hover: hover) and (pointer:
  fine)` so a tap cannot leave a row lit. The dot's keyframes are in the
  no-preference block and its resting state is transparent, so reduced
  motion is the outline alone. Check the flight by pausing it at negative
  delays in a test copy (`base href` to the local server, CSS appended).
- **Interests, one order, and the filter (0.22.0, Rob).** `interests` is a
  sixth badge field, handled exactly as `support`: codes (slugs until site
  1.1.0) from `INTERESTS` (code, group, name, sentence, now read from
  `badges.json`; 43 of them with amateur radio, in eight groups, from
  Computing to Reading and watching), drawings in `INTEREST_ART` keyed by
  code, drawn
  in `currentColor` so the chip's rose (`k-int`, a family nothing else
  uses) colours them. One outline and a detail or two each, no ids, no
  text; check new ones on a contact sheet at 17, 30 and 72px, because a
  drawing that reads at 72 can be a blob at 17 (the first Amiga ball read as
  a web globe and the first penguin as a bottle).
  **`BADGES` is every badge once, in the order /badges and the filter's
  grid use**, and neither sorts. Rob: alphabetical by the name a reader
  sees within each group, a leading digit or symbol set aside
  (`sort_key`), the groups in their own order, so "3D printing" files
  under D. The six time-listed steps are one badge, "Listed", sharing one
  key, so they stay together and in duration order. **A board's row does
  not use it since site 1.0.0** (Rob: "The unleashed and esp32 should be
  upfront ... sort those so core system ones are always first ... that way
  they look consistent when scrolling"): `board_badges` draws two rows,
  `.bid` (the software with its version, the update arrow, the machine)
  and `.bset` (`ROW_ORDER`: P, G, C M F Fi D, N, S, then time listed, then
  `ROW_SUPPORT` and `ROW_INTERESTS`, the only two alphabetical, the
  interests across their sub-groups). A board with nothing for a row has
  no row. The row's `data-b` filter keys stay in BADGES order.
  `FILTER_KEYS` is every badge a reader can filter on; software and machine
  are free text and are not.
  **The filter**: `filter_bar_html` draws a small Filter button (a
  `<details>`), the key to the badges beside it, and, only while something
  is chosen, one line: "N of M boards with all of: ... Clear". Closed, no
  badge symbol is on the page that was not there before; the tiles live
  only inside the pane. Every row is always sent, carrying its keys in
  `data-b` (`row_keys`, which counts every time-listed step reached), and
  the ones that fail get `hidden`, so the script can bring them back with
  no round trip; `main [hidden]` is `display:none !important` because a
  phone's row is `display:flex`. Stripes use `:nth-child(odd of
  :not([hidden]))` so they count only rows showing. `?b=` and `m=any` are
  read by `filter_query`, which keeps only known keys, so nothing typed into
  the address is echoed. A filtered view renders per request from
  `cached("indexdata")`; the plain list is still cached whole. While the
  pane is open the script adds `#filter` to the URL, so the meta refresh
  reopens it instead of snapping it shut.
  **The pane is chips in rows since 0.22.2** (Rob: "the filter page is
  unmanageable, it needs HUGE condensing ... the hover works, just put em
  in groups"). A chip (`filter_chip`) is the symbol only, 1.625rem, the
  name its checkbox's `aria-label` and its tooltip; a group is a row
  (`filter_row`, a `<details open>`), its name a floated 10.5rem column on
  a desktop and a heading a phone can tap to fold. The interests are a
  heading and a row per sub-group, two to a line from 901px. Chosen is a
  ring and a corner notch; the tooltip hangs under the row, not the chip,
  and is `display:none` until wanted, so no chip at the right edge can
  widen the page. Measured with the pane open: 1,538px to 460px at 1366,
  3,256px to 1,130px at 390. **No `aria-pressed`**, though it was asked
  for: the chips are native checkboxes, which already say checked to a
  screen reader, and ARIA in HTML does not allow `aria-pressed` on one.
  A search opens a folded row that has a match.
- **Support and interests since 0.22.2.** Amateur radio moved to the
  interests (Radio and sky), slug unchanged; `SUPPORT_MOVED` files a `ham`
  still sent as support with the interests, and `row_support` /
  `row_interests` read a row stored before the move the same way, so no
  migration. Support went from eleven to 24 by volume (Rob: "use volume as
  your guide"): the ten, then breast cancer (pink ribbon), childhood cancer
  (gold), dementia (forget-me-not), carers, diabetes (blue circle), heart
  health, domestic violence (purple ribbon), addiction recovery (purple
  sunrise), blood and organ donation, foster care and adoption (the triad),
  homelessness, hunger relief (orange), literacy and first responders (a
  beacon, deliberately not the thin blue line). Autism is covered by
  neurodiversity and military families by veterans. HIV's ribbon stays red
  until Rob decides.
- **Versions and the update arrow (site 1.0.0, Rob: "a version number
  should apply to all honestly. Then when an unleashed board is behind,
  mark on there a subtle up arrow").** The software badge reads "unleashed
  1.0.0" or "Mystic 1.12"; `software` and `version` are cleaned with
  `tidy_label` like `system`, and both are in the JSON and the feed.
  `version_key` compares three numbers part by part (1.0.10 > 1.0.9), a
  pre-release below its release, `+build` ignored, anything else None and
  never flagged. `update_for` flags only `software == unleashed` older than
  `newest_release()`, which is `firmware_releases()[0]`, the one /install
  offers first, so the arrow follows whatever is on disk. `update_link` is
  an `<a class="bu">` to /upgrade joined to the software badge (negative
  margin, no left border), dim cyan, with the badges' CSS tooltip, and is
  deliberately not `role="img"`. It is also a directory badge, "Update
  available" (`update`, `k-upd`), on /badges and in the filter, so a sysop
  can find their boards that are behind. `row_keys` takes `latest`, and
  `index_page` works it out once per render.
- **Badge codes (site 1.1.0, Rob: "like 5 or 6 max", MNTLH).** Every cause
  and interest is a code: a to z and 0 to 9, six at most, unique across both
  lists and never a word the filter uses (`_RESERVED`), shown upper case on
  /badges (the **Code** column; the board and directory tables say **Sent
  as**) and in a filter chip's tooltip ("Supports mental health. Code
  MNTLH."), stored, sent and published lower case. The mapping is the
  firmware repo's `internal/badge-codes-proposal-2026-09-23.md`, as approved.
  **`badges.json` is the one table**: code, group, sub (interests), name
  (as /badges shows it; the tooltip's "Supports ..." phrase is `_uncap()`
  of it), means, aliases, plus `copyright`, `license`, `format` and the
  rules as prose, so a separate program can read it: the firmware builds
  its CONFIG pick-list from it. server.py keeps only the drawings,
  `SUPPORT_ART` and `INTEREST_ART`, **keyed by code**; a new code needs a
  drawing there (without one the chip shows the code in letters, and the
  suite fails). `_badge_codes()` loads it at import, leaves out an entry
  that breaks a rule or an alias that would name a second badge with a
  journal line, and **if the file cannot be read** returns
  `BADGE_CODES_OK = False`: no causes or interests on the page, and
  `announce()` then leaves the stored `support` and `interests` columns
  alone rather than writing every board's badges away. setup.sh installs it.
  **Aliases**: every slug up to site 1.0.0 and every interim one from the
  proposal. `norm_word()` folds case and drops everything that is not a
  letter or digit before matching, so hyphenless forms (`mentalhealth`,
  what the firmware sends for "Mental health") need no entries of their
  own. Read in four places: `pick(..., alias=)` on an announce,
  `row_support()`/`row_interests()` on a stored row (so the 1.0.0 database's
  long slugs needed no migration; the next heartbeat writes codes),
  `filter_query()` through `FILTER_ALIAS`, and `badge_words()` for the two
  search boxes, which carries each alias as written, with spaces and with
  its hyphens dropped. `/api/boards.json` answers in codes. **The firmware's
  own badge test** (`tools/testclient.py`, the directory badges block)
  expects long slugs back from the JSON and needs changing: sending them
  still works, but the answer is `ltrcy` and `elctr` now.
- **The SD card badge (site 1.1.0).** `sd` in the announce: a whole number
  of GB, 1 to `SD_MAX` (4096), a JSON `true` refused (Python's bool is an
  int), anything else not sent. The `sd` column is NULL for "not sent".
  `row_sd()` reads it and tolerates a row or a test dict without the
  column. On a row it is `SD32` in the features' blue, placed after doors in
  `ROW_ORDER`; `LETTER_BADGES` carries it as "SD", which is what the legend
  and the filter chip (`?b=sd`, any card) show. JSON `sd`, feed "SD card:
  32 GB".
- **The installer always offers Telnet details (site 1.0.0).** The fourth
  change to the vendored dialog: `_renderDashboard` renders the link item
  whether or not the device sent a URL, to `/connected` with no fragment
  when it sent none. /connected's no-address box is the three ways to find
  a board (`<hostname>.local`, the console line at boot, the router), and
  is now a page people land on, not a fallback. `EWT_REV` 3; `EWT_PATHS`
  keeps every earlier revision's path answering with today's files.
- **The install card fits 1366 x 768 with both buttons** (site 1.0.0): a
  24rem column, the drawing held to 3.5rem, gap 0.5rem, shorter buttons,
  each with a line-art symbol (`BTN_ICON_NEW`, `BTN_ICON_UPDATE`). Measured
  with two releases offered, the tallest the card gets: the Update button
  ends near 740px. Re-measure after touching the card or the amber box.
  Since site 1.2.0 the drawing is gone, the board picker opens the card,
  the amber box is under the buttons and the column is 26rem: the ESP32's
  Update button ends at 665px, the S3's at 719px. Measure with the
  installer's module left out of a test copy and its `.no` spans hidden,
  or the undefined element shows both refusal messages and reads 200px
  tall; and a second server started on the same port on Windows binds
  beside a stale one that keeps answering, so stop it by its pid.
- **The card's lamps (0.22.0, from the UX spec)**: two lamps half a lap
  apart, each a head and three beads, 20s a lap, linear. Three a third of a
  lap apart looked scattered because a rectangle has no three-fold
  symmetry; two half a lap apart always mirror through the centre. Beads
  are invisible outside the motion block; reduced motion and no
  offset-path both leave two still lamps by opposite corners. Checked by
  pausing every `runlap` animation at 2s and 7s in a test copy and reading
  the positions: A (143,0) and B (272,157) on a 415x157 card.
- **Migrations are additive and tested from an old file.** `setup()` adds a
  missing column with ALTER TABLE and nothing else; `BADGE_COLUMNS` must
  match SCHEMA, and the suite builds databases with the 0.20.2 schema
  (`OLD_SCHEMA`), the 0.21.1 schema (`OLD_SCHEMA_0211`) and the 1.0.0
  schema (`OLD_SCHEMA_100`, with long slugs stored, which the live database
  has), each copied from that version's server.py, starts a server on each,
  and compares its columns with a fresh one's. Add the next migration's old
  schema the same way.
- **The suite's ports.** `SELFTEST_PORT` (default 8123) is the first of five
  consecutive ports on 127.0.0.1 the suite binds, plus one ephemeral one for
  the release fetcher. Agents here run it as `SELFTEST_PORT=18765`.

## Anti-spam, and why it is shaped this way

- A listing is earned by three hours of sustained heartbeats, not by asking.
- One automatic listing per address, per `/64` on IPv6.
- **Never an outbound probe.** A directory that connects to whatever address
  a stranger posts is a port scanner with a public API.
- Tokens are anti-hijack only and PROTOCOL.md says so plainly. They are
  server-issued and random, never derived from a name or a MAC, because
  anything derivable is forgeable by anyone reading the source, and the
  source is public on purpose.

## Known holes

- `PER_ADDRESS` counts rows of any state, so a board that loses its token is
  queued behind its own dead listing until the 7 day reaper clears it.
- `queued` is a dead end: `settle()` only promotes `pending`, and the update
  path only moves `offline` back to `pending`. A queued board heartbeats
  forever, so it never expires either, and never gets promoted.
- Both are the same root cause: state transitions were written in one
  direction only. Fix is to skip `offline` rows in the admission count and
  re-evaluate `queued` on each heartbeat. Not yet done, Rob has seen it.

## Reference

- The BBS side lives in `esp32-bbs`, plugin `src/plugins/announce.cpp`.
- Boards announce to the data face (`.net`), not the list face.
