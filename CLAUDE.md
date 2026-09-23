# unleashed directory: project context

The directory server for µnleashed BBS. Boards post a small JSON heartbeat,
this keeps a list of the ones that are up, and serves three faces from one
process. GPL v2 or later, same as the BBS.

Read PROTOCOL.md for the wire format, INSTALL.md for a fresh droplet,
README.md for what it is. This file is the process and the design history.

## Processes

Not preferences. The process. Getting these wrong wastes Rob's time.

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
- No JavaScript anywhere on the site, with exactly one exception, and the
  shape of the exception is the rule. The manifesto's two diagrams are
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
  package's `dist/web` build byte for byte, served at
  `/install/esp-web-tools/<version>/` with a JavaScript content type, which
  a module script needs. All its imports are relative, so no other origin
  is involved; its only absolute URLs are links a person can click. Its
  licence and the bundled libraries' licences sit beside it and the page
  links both. `SHA256SUMS` in that directory is checked by the suite, and
  `.gitattributes` keeps the directory binary so no line ending moves.
  `vendor/esp-web-tools/README.md` is how to move to a new version.
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
  **Where a release goes, for whoever cuts one** (the firmware side does,
  from a fresh clone):

  ```
  firmware/<BBS_VERSION>/esp32/bootloader.bin         0x1000    4096
  firmware/<BBS_VERSION>/esp32/partitions.bin         0x8000    32768
  firmware/<BBS_VERSION>/esp32/ota_data_initial.bin   0xF000    61440
  firmware/<BBS_VERSION>/esp32/firmware.bin           0x20000   131072
  firmware/<BBS_VERSION>/esp32/storage.bin            0x3C0000  3932160
  firmware/<BBS_VERSION>/THIRD_PARTY_NOTICES.md       from the firmware repo
  firmware/<BBS_VERSION>/release.txt                  optional: date, one-line note
  ```

  `storage.bin` is PlatformIO's `littlefs.bin`, renamed for its partition.
  **No `manifest.json` goes in the folder**: the server builds it from the
  five files and serves it at `/install/<version>/manifest.json`, with
  `name` "unleashed BBS", `new_install_prompt_erase` true and
  `new_install_improv_wait_time` 30. The chip directory is `esp32` so an
  S3 build is a second directory (`esp32s3`, bootloader at 0x0) and not a
  code change. A family missing any part, or with an empty part, is not
  offered. Two releases are offered, newest first; commit the new one and
  `git rm` the oldest in the same change.
  **The suite reads every committed `storage.bin`** and fails if a staff
  password, a Wi-Fi key or a directory token in it has a value, because
  `data/system.cfg` is built into that image and a developer's copy has
  all three. `firmware.bin` cannot be checked the same way: a build with a
  developer's `include/secrets.h` carries their network, and only building
  from a fresh clone prevents that.
  **A web-installed board has no sysop password yet**, and no way to set
  one from the board. `pages/install.md` has a `TODO(sysop password)`
  comment where the step goes and says nothing about it until the firmware
  can do it. Do not write that step, or send a reader to CONFIG or the
  announce plugin from that page, before then.
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
  belongs beside the words it is about (the sysop password TODO on
  /install). It must start a line outside a fence or a card, and the suite
  counts openers against closers in every page, because an unclosed one
  swallows the rest of the page.
  **`::: installer` ... `:::`** is the third block and the only one that is
  not prose: it renders the flasher widget, or an honest account of why
  there is nothing to flash. It carries **no content of its own**, and that
  is the point, because what it should say depends on what is in
  `firmware/` rather than on what somebody typed into the page. `:::`
  blocks dispatch through `md_block()`; an unknown name after `:::` still
  falls through to a paragraph so a typo is visible rather than swallowing
  the rest of the page.
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
