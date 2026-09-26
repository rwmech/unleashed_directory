<!--
 ===========================================================================
  µnleashed BBS directory
 ===========================================================================

 File:         INSTALL.md
 Purpose:      Standing a directory up from nothing, on the cheapest
               machine a hosting company will rent you.

 Copyright 2026 - Robert Mech
 License:      GNU General Public License v3 or later
 SPDX-License-Identifier: GPL-3.0-or-later
 ===========================================================================
-->

# Installing a directory

Fifteen minutes, most of it waiting for DNS. Written against a $4 DigitalOcean droplet because that is the cheapest thing that will do it, but any Debian or Ubuntu machine works, including one under your desk.

## What it needs

Almost nothing, and that is the point.

| | |
|---|---|
| RAM | 512 MB is plenty. Caddy takes about 40 MB, the directory about 20 MB |
| Disk | 10 GB. The database is a few hundred kilobytes per thousand boards |
| CPU | one shared core |
| Software | Python 3 and Caddy, both installed by the script |

The load is small enough to be worth stating plainly: **a board sends about 200 bytes every ten minutes.** A thousand listed boards is 1.7 requests a second. Ten thousand is seventeen. This is not a machine that will be working hard.

## 1. Make the droplet

DigitalOcean, Create → Droplet:

- **Image:** Ubuntu LTS
- **Plan:** Basic → Regular → **$4/month** (512 MB, 1 vCPU, 10 GB)
- **Authentication:** SSH key, not a password
- **Hostname:** whatever you like

Note the public address it gives you.

## 2. Point your domains at it

At your registrar, for each domain you own, add:

| Type | Name | Value |
|---|---|---|
| A | `@` | your droplet's address |
| A | `www` | your droplet's address |

All the domains can point at the same address. The setup script takes several and serves them all the same site, which is what you want when you bought the `.net` and the `.org` out of caution.

Give it a few minutes. `dig +short example.com` should come back with your address before you go on, because Caddy asks for certificates on first start and will fail if the names do not resolve yet.

## 3. Install

```bash
ssh root@your.droplet.address

apt-get update -y && apt-get install -y git
git clone https://github.com/rwmech/unleashed_directory.git
# The guides, served at /docs. Optional: leave these two lines out and
# there is simply no /docs.
git clone https://github.com/rwmech/unleashed_documentation.git
install -d /etc/unleashed-directory && echo "$PWD/unleashed_documentation" > /etc/unleashed-directory/docs
cd unleashed_directory
./deploy/setup.sh example.net
```

A fresh cloud image often has no `git`, which is why it is installed first. The
script installs everything else it needs, including `gnupg`, which a minimal
image also tends to lack and which the Caddy step depends on.

If the clone asks for a username and password, the repository is private:
GitHub has not accepted account passwords for git since 2021. Either make the
repository public, or add a read-only deploy key to it and clone over SSH.

The first domain is the directory's own; any more after it are served the same site. The board list is at `/`, the data at `/data`, and the guides at `/docs` when you gave it them. To try it without TLS or domains at all, run `./deploy/setup.sh` with no arguments and it serves plain HTTP on port 80.

Certificates are handled by Caddy: it obtains them on first start and renews them in the background. There is no certbot to install and no renewal cron to add, and adding one would fight it.

The script installs Caddy and Python, creates a `directory` system user that owns nothing but its database, writes the web configuration for your domains into `/etc/caddy/sites/directory.caddy` (with a `/etc/caddy/Caddyfile` that gathers that folder, so another service on the same machine can add its own sites beside it), starts the service, and opens ports 22, 80 and 443. Run it again any time after a `git pull`.

## 4. Check it

```bash
curl -fsS http://127.0.0.1:8080/health          # the app itself
curl -fsS https://example.com/ | head -20        # through Caddy, with TLS
systemctl status unleashed-directory
```

Then point a board at it:

```
[plugin:announce]
enabled = yes
name    = My Board
owner   = Me
servers = http://example.com/announce
```

`ANNOUNCE` on the board should say `pending, public in 2h59m`. That wait is deliberate: it is what keeps drive-by spam off the page, and it costs a real board nothing because it was going to be up anyway.

## On 512 MB

Ubuntu on a 512 MB droplet has no swap by default, and `apt` occasionally wants more than it has. One gigabyte of swap costs nothing and prevents an afternoon of confusion:

```bash
fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

## Keeping it

```bash
sudo ~/unleashed_directory/deploy/update.sh
```

That pulls, re-installs using the domains this box was set up with, restarts,
checks the site is actually serving and that `/announce` has not started
redirecting, and prints the changelog for everything it pulled in. Run it any
time; it does nothing when there is nothing to do.

Unattended, for a machine you will not think about again:

```bash
sudo ~/unleashed_directory/deploy/update.sh --install-timer
```

Daily, with a randomised delay, and quiet unless something changed or broke.
`journalctl -u unleashed-directory-update` has the history.

To hear about it, point it at a webhook:

```bash
echo 'https://ntfy.sh/pick-a-topic' > /etc/unleashed-directory/notify
```

Cron mail is the obvious alternative and it will not work here: there is no mail
server on the droplet, and if these domains publish `v=spf1 -all` then anything
sent as `root@yourdomain` is being declared a forgery by your own DNS. A webhook
sidesteps both problems.

🔴 One thing to decide deliberately: an automatic update means whatever is
pushed to that repository runs on this machine. That is fine when it is your own
repository and you control who can push to it. If it ever is not, use `--check`
on a timer instead and update by hand.

Unattended security updates are worth having on a machine you will forget about:

```bash
apt-get install -y unattended-upgrades && dpkg-reconfigure -plow unattended-upgrades
```

## Backing it up

Everything that matters is one SQLite file.

```bash
sqlite3 /var/lib/unleashed-directory/directory.db ".backup /root/directory-$(date +%F).db"
```

Worth a weekly cron job. Losing it means every board re-earns its three hours and gets a new token, which is survivable but rude.

## Moderating

No admin interface, deliberately: there is nothing to moderate until there is.

```bash
sqlite3 /var/lib/unleashed-directory/directory.db

-- waiting for a human, usually a second board from one address
SELECT id, name, owner, address, description FROM boards WHERE state='queued';

-- let one through
UPDATE boards SET state='pending', streak_start=strftime('%s','now') WHERE id=7;

-- remove one
DELETE FROM boards WHERE id=7;
```

## Settings

All of them live in `/etc/systemd/system/unleashed-directory.service` as environment lines. Change one, then `systemctl daemon-reload && systemctl restart unleashed-directory`.

| Variable | Default | What it does |
|---|---|---|
| `DIRECTORY_PENDING_HOURS` | `3` | continuous heartbeats before a listing goes public |
| `DIRECTORY_EXPIRE_DAYS` | `7` | silence before a listing is deleted |
| `DIRECTORY_PER_ADDRESS` | `1` | automatic listings per address, per `/64` on IPv6 |
| `DIRECTORY_MIN_SECONDS` | `30` | minimum gap between accepted heartbeats from one board |
| `DIRECTORY_ADDRESS_PER_MINUTE` | `20` | most accepted announces from one address in a minute. `0` switches it off |
| `DIRECTORY_PAGE_CACHE` | `10` | seconds the rendered page is reused |
| `DIRECTORY_NAME` | | the title on the page |

## If something is wrong

```bash
journalctl -u unleashed-directory -n 50      # the directory
journalctl -u caddy -n 50                    # certificates and routing
caddy validate --config /etc/caddy/Caddyfile
```

**Boards report "refused" but the website works.** Something is redirecting `/announce` to HTTPS. Boards cannot follow it. Check that the `http://` block in `/etc/caddy/sites/directory.caddy` still handles `/announce` before its redirect, and that any other domain on the machine a board could have been pointed at sends `/announce` here the same way.

**Caddy will not get a certificate.** The names have to resolve to this machine before it asks, and ports 80 and 443 have to be open to the internet. `dig +short example.com` and `ufw status`.

**A board never leaves pending.** It has to hold the heartbeat without a gap. Three missed intervals puts it back to the start. `ANNOUNCE` on the board shows whether its heartbeats are landing.
