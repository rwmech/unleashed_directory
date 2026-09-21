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
- **CHANGELOG.md is updated in the same commit**, not afterwards.
- **Never commit** the database, or anything with a token in it.

## Shape

- Python 3 standard library only. SQLite. One file, `server.py`. No
  framework, no dependencies, because a directory nobody can afford to run
  is not a directory.
- Listens on loopback. Caddy faces the internet and holds the certificates.
- `role_for(host)` serves three faces from one process by Host header: the
  board list, the argument (the manifesto), and the machine-readable data.
- Pages are cached and the cache is dropped only when `settle()` actually
  moved something, so the page is never stale but is also not rebuilt for
  every reader.
- No JavaScript anywhere on the site. The manifesto page makes a point of
  it, so anything that would add a script needs a better reason than
  convenience. The ASCII animation is CSS.
- `pages/*.md` are written in a deliberately small Markdown dialect that
  `md_render()` implements in about sixty lines. What exists: `#`, `##`,
  `###`, `- ` bullets, `1. ` ordered lists, `> ` blockquotes (consecutive
  lines are **one** warning box, not one each), fenced code, pipe tables,
  and inline `**bold**`, `` `code` `` and `[links](/path)`. A bullet or a
  step wraps by indenting the continuation two spaces. What does not exist,
  on purpose: nested lists, images, inline HTML, headings below `###`.
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
- **A CSS or copy change is not verified until the rendered page has been
  looked at.** grep on the HTML proves a string is present, not that a rule
  applied, an element is positioned or a menu is readable. Two of the worst
  bugs found here were invisible to grep: the menu shipping with no
  stylesheet at all, and the board list being 627px wide in a 358px phone
  column with the State column off the screen.

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
