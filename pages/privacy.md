# The real risks of open communications

A [[BBS]] carries everything in the clear. This page says what that means, what it
does not mean, and what to do about it. It is longer than the one
paragraph on the front page because the short version leaves people to guess,
and people guess badly in both directions.

## What "in the clear" means

When you connect to a board, your keystrokes travel as plain bytes. Your
nickname, your
password, what you type in the chat room, what you read. Anybody who can see
the traffic on the path between you and the board can read all of it.

There is no encryption to turn on. The protocol is [[telnet]], from 1969, and the
machines this is built for cannot do much better: somebody has made a stock
Commodore 64 finish a modern TLS handshake, and it takes
[about half an hour](https://github.com/JC-000/c64-https). The honest move is to
say so rather than to add a padlock that means nothing.

## Who can see it

Not "anybody on the internet". Somebody on the path, running a tool, on purpose.
In practice that is:

- Anybody on the same Wi-Fi as you, if it is open or if they have the key.
  Coffee shops, hotels, conferences, airports.
- Whoever runs the network you are on. An employer, a university, a landlord.
- Your internet provider, and the board's.
- Anybody who has got into a router between the two of you.

Being able to listen and listening are different things. Every one of those
requires a person choosing to point a tool at your traffic. None of it happens
by itself, and none of it is collected and kept by default, which is the part
that makes this different from the web.

## What it is not

It is not a website. A website logs your address, sets an identifier in your
browser, records what you read and how long for, hands it to an analytics
company, and keeps it under a retention policy you never read. All of that is
by design and all of it happens whether or not anybody is interested in you.

A board does none of that. There is no third party in the middle because there
is nowhere for a copy to go. The trade is real, and it runs both ways: the
conversation is readable by somebody who is trying, and it is not being
harvested by anybody who is not.

## The comparison that helps

Think of a bar, or a coffee house. You talk, and the next table could hear you
if they cared to. Most of the time nobody does. You still would not read your
bank details out loud, and you would still say most of what you came to say.

That is the right model for a BBS. It is a public room. Somebody could be
parked outside with equipment, and for almost everybody that is an edge case
rather than a plan.

## What to do

> Use a password you use nowhere else. This is the one that matters. A password
> read off the wire is only worth what it unlocks elsewhere, so make that
> nothing.

- Say what you would say in public. Treat the chat room as a room, because it
  is one.
- Do not type anything into a board that would hurt you if it were read out.
  Card numbers, other passwords, an address you would not give a stranger.
- On a network you do not trust, assume somebody could be looking. Open Wi-Fi is
  the realistic case.
- If a conversation genuinely has to be private, this is the wrong tool. Put
  the board behind a VPN, or keep it on your own network, or use something
  built for secrecy.

## If you run a board

Tell your members, your [[callers]], before they pick a password, not
afterwards. A board running
this software does that by itself: it warns at sign-up, offers to explain, and
the `PRIVACY` command replays the explanation any time.

Keep in mind what your own caller log holds. Nicknames, addresses and call times
are a record of who has been on your machine, which is why it exists, and it is
yours to look after.
