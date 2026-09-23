<!--
 ===========================================================================
  µnleashed BBS directory
 ===========================================================================

 File:         PROTOCOL.md
 Purpose:      The wire format, so anything can be listed and anybody can
               run a directory.

 Copyright 2026 - Robert Mech
 License:      GNU General Public License v2 or later
 SPDX-License-Identifier: GPL-2.0-or-later
 ===========================================================================
-->

# The announce protocol

One HTTP POST, a JSON body of about 200 bytes, repeated every few minutes. That is the whole protocol. It is deliberately small enough to implement on a microcontroller with no libraries, and plain enough to implement in any language in an afternoon.

## Why plain HTTP

Because the boards are microcontrollers. A TLS stack costs more memory than the entire announce feature on an ESP32, and every field in the payload is public information by definition: it is a listing, written to be read by strangers. The one thing worth protecting is somebody claiming to be your board, and a token does that without a certificate store.

A directory **must** serve `/announce` over plain HTTP with no redirect. A board that receives a 308 cannot follow it.

## Request

```
POST /announce HTTP/1.1
Host: unleashedbbs.net
User-Agent: unleashed/0.13.0
Content-Type: application/json
Content-Length: 204
Connection: close

{"software":"unleashed","version":"0.13.0",
 "name":"The Rusty Modem","owner":"Sparks",
 "description":"A BBS on a chip in a shack in Illinois",
 "host":"","port":6400,"nodes":6,"busy":0,
 "uptime":3600,"interval":10,"token":""}
```

| Field | Type | Required | Meaning |
|---|---|---|---|
| `software` | string | no | what is running. `unleashed` from this firmware; a directory should accept anything |
| `version` | string | no | its version |
| `name` | string | **yes** | the board's name, up to 40 characters |
| `owner` | string | no | who runs it, up to 40 characters |
| `description` | string | no | one line, up to 120 characters |
| `host` | string | no | the name to list. Empty means "use the address this arrived from" |
| `port` | number | **yes** | the port callers dial, 1 to 65535 |
| `nodes` | number | no | how many caller lines the board has |
| `busy` | number | no | how many are in use right now |
| `uptime` | number | no | seconds since the board booted |
| `tz` | number | no | minutes east of UTC, daylight saving applied. Only used to bucket this board's own busy hours into local time. Ignored outside -720..840 |
| `interval` | number | no | minutes between heartbeats. Tells the directory when to call the board quiet. Default 10 |
| `token` | string | no | empty on the first announce, then whatever the directory issued |
| `calls24` | number | no | calls in the last 24 hours. Only when the sysop opted in |
| `minutes24` | number | no | caller-minutes in the last 24 hours. Only when the sysop opted in |
| `system` | string | no | the machine the board runs on, up to 40 printable characters. See [Badges](#badges) |
| `terminals` | array of strings | no | what the board can speak to a caller: any of `ansi`, `utf8`, `petscii`, `ascii`, `vt100` |
| `guests` | boolean | no | `true` if a caller can look around without an account, `false` if not |
| `features` | array of strings | no | what is running right now: any of `chat`, `forums`, `files`, `mail`, `doors` |
| `support` | array of strings | no | causes the sysop shows support for, as slugs from the directory's published list |
| `interests` | array of strings | no | what the sysop is into, as slugs from the directory's published list |

**No field identifies a caller, and none ever should.** Not handles, not addresses, not what anybody typed. A directory receiving such a field should drop it.

## Badges

The last six fields in the table are optional and describe the board rather than its state. A directory may show them as badges beside the board's name; the one at unleashedbbs.com does, and explains each at `/badges`. Old boards send none of them and are listed exactly as before. A directory ignores any field it does not know, so a board may send these to any directory.

```
{"software":"unleashed","version":"1.0.0",
 "name":"The Rusty Modem","owner":"Sparks",
 "description":"A BBS on a chip in a shack in Illinois",
 "host":"","port":6400,"nodes":6,"busy":0,
 "uptime":3600,"interval":10,"token":"",
 "system":"ESP32-WROOM-32E",
 "terminals":["ansi","utf8","petscii","ascii"],
 "guests":true,
 "features":["chat","forums","files","mail"],
 "support":["lgbtq","literacy"],
 "interests":["c64","electronics","ham"]}
```

| Field | Rules |
|---|---|
| `system` | Free text, the board's own words: a board that knows its hardware can report it, and any board can say `Compaq 486`. The directory removes control and format characters (the bidirectional overrides and zero-width characters included), collapses runs of spaces, keeps at most two combining marks on a character, and cuts what is left to 40 characters. |
| `terminals` | Lower case words from the list above. `utf8` means UTF-8 ANSI; `ansi` means CP437 ANSI. |
| `guests` | A JSON `true` or `false` and nothing else. A string such as `"yes"` counts as not sent. |
| `features` | Only what is running when the heartbeat is sent. A board that switches its file areas off should stop sending `files`. |
| `support` | Slugs from the list the directory publishes. The one at unleashedbbs.com publishes its list at `/badges`. |
| `interests` | Slugs from the list the directory publishes, exactly as `support`: hobbies and interests rather than causes, such as `c64`, `electronics`, `gaming` or `gardening`. The one at unleashedbbs.com publishes its list at `/badges`. A slug a directory moves from one list to the other should still be understood in the list it came from: unleashedbbs.com moved `ham` from `support` to `interests` and reads it in either. |

For the four lists: case does not matter, duplicates count once, a word the directory does not know is ignored rather than refused, and only the first 16 entries are read; an entry that is not a string is skipped. A field of the wrong type, a list where a string belongs or a string where a list belongs, counts as not sent. None of this ever makes a heartbeat fail: a board with a bad badge field is listed without that badge.

**A directory may drop any value it cannot show.** A word it does not know, a machine name in a script its page cannot draw, a cause it does not carry: the listing stands and the badge does not. That is also why `support` and `interests` are lists of slugs and not free text: a directory publishes the causes and interests it will show, and nobody can put words of their own on its page.

**Every heartbeat replaces them.** Send them every time, or the badge goes. That is the point for `features`, which says what is running now, and it costs nothing for the rest: with all six the example above is about 450 bytes, and this directory refuses only a body over 4,096 bytes, with `413`. Sixteen of each list at the longest slugs still comes in well under it.

A directory works out some badges for itself, from its own records, and a board cannot send them: at unleashedbbs.com, **new** (listed less than a week), **steady** (answered more than 95% of the heartbeats its own `interval` said were due over the last seven days) and **time listed** (one month up to ten years). They appear in `/api/boards.json` as `listed_at` and `steady`.

`software` and `version` are shown together, as the board sent them, on the board's first badge ("unleashed 1.0.0", "Mystic 1.12"), and both are in `/api/boards.json`. When `software` is `unleashed` and `version` is older than the newest release the directory itself offers for installing, unleashedbbs.com marks that badge with a small arrow, **update available**, linked to how to update. Versions are compared as three numbers, part by part, so 1.0.10 is newer than 1.0.9, and a pre-release such as `1.0.1-rc.1` is older than `1.0.1`; a version that is not three numbers is never marked. Other software is never marked, because a directory cannot know another program's newest version.

The board list at unleashedbbs.com can be filtered on any of these badges, by a person or by a link: `/?b=petscii&b=ham` lists the boards carrying all of them, and adding `&m=any` lists the boards carrying any of them. The keys are the support and interest slugs, the feature words, `petscii`, `guests`, `new`, `steady`, `update`, and `1m`, `6m`, `1y`, `2y`, `5y` or `10y` for listed at least that long. That is a convenience of this directory's page, not part of the protocol.

## Response

`200` means listed. Anything else is a refusal and boards report it to their sysop as such.

```
HTTP/1.1 200 OK
Content-Type: application/json
X-Seen-Address: 203.0.113.9
X-Listing-Token: 1935bc3ca80c43fcd52bacf6d3db6673
X-Listing-State: pending
X-Listing-Public-In: 9840

{"state":"pending","public_in":9840,"seen":"203.0.113.9",
 "name":"The Rusty Modem","beats":1,
 "token":"1935bc3ca80c43fcd52bacf6d3db6673"}
```

| Header | Meaning |
|---|---|
| `X-Seen-Address` | the address the request arrived from. A board behind a changing home address learns its public address this way, which is the cheapest dynamic DNS there is. Sending it costs nothing and is good manners |
| `X-Listing-Token` | the token for this listing. On the first announce this is newly minted; the board **must** save it and send it from then on |
| `X-Listing-State` | `pending`, `online`, `offline` or `queued` |
| `X-Listing-Public-In` | seconds until a pending listing appears. Lets a board show `public in 2h41m` instead of silence |

The same values are in the JSON body, for implementations that would rather parse one thing than two.

| Status | Meaning |
|---|---|
| `200` | listed or updated |
| `400` | the payload is malformed, has no name, or an impossible port |
| `413` | body too large |
| `429` | heartbeats are arriving too fast |

## The token

Minted by the directory on the first announce, random, and tied to that listing. A board saves it and sends it forever after.

**What it is for:** stopping somebody taking over your listing.

**What it is not for:** stopping spam. Tokens are free to mint, so anyone can have as many as they like. Do not build a spam defence on them.

**What it must not be:** derived from anything public. A token computed from the board's name, or from its MAC address, is a lock whose key is printed on the door, and since both the firmware and this server are open source, everybody has the algorithm. Random, server-issued, or it is decoration.

A directory that receives an unknown token treats the request as a brand new listing. It never transfers an existing one.

## Listing states

| State | Meaning |
|---|---|
| `pending` | heartbeats are accumulating. Not on the public list |
| `online` | public, and a heartbeat has arrived within three of the board's own intervals |
| `offline` | public but marked quiet. A reboot or a bad evening must not cost a board the hours it spent becoming public |
| `queued` | waiting for a human, usually because another listing already exists at that address |

An `offline` board that comes back within four days returns to `online` and
keeps the hours it already served. The pending hours are a spam stop, and a
spam stop is paid once: charging it again every time somebody unplugs a board
to move a desk punishes the sysops who are actually there. Past four days it
goes back to `pending` and serves them again, because a board nobody could
call for most of a week is worth re-establishing.

Silence for seven days deletes the listing and frees its name and token.

## What a directory is expected to do

- Record the listing against the source address, or against `host` when the board supplies one.
- Hold a new listing back until it has sustained heartbeats for a few hours. This is the anti-spam measure that costs a spammer real infrastructure and costs a real board nothing, because it was going to be up anyway.
- Charge those hours once. A board that has already earned its listing and then goes quiet for a while should come back to it, not re-earn it. Getting this wrong is worse than it sounds: if the public list does not render the holding state, then reconnecting, rather than disconnecting, is what removes a board from the page.
- Limit automatic listings per source address, counting per `/64` on IPv6, and queue the rest for a human. Addresses are the scarce resource, which makes this the control that actually bites.
- Rate limit the endpoint.
- Never publish anything the board did not send.
- Never connect outwards to verify a listing. See the README for why.
- Treat activity figures as self-reported, because they are. If you rank by them, say so, and pair them with something you measured yourself, such as how long the board has been continuously up.

## Implementing it elsewhere

Any software that sends this payload gets listed. There is nothing µnleashed-specific in it, and `software` is a free-text field precisely so other BBS packages can announce themselves. If you implement it and something here is ambiguous, that is a bug in this document.
