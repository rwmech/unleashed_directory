# Your first call

You have a terminal, you have picked a board off the list, and it answered.
Here is what happens next.

## It works out what you are

The board sends a short probe the moment you connect and reads what comes
back. ANSI with CP437 or UTF-8, PETSCII at 40 or 80 columns, or plain ASCII.
You configure nothing. A Commodore 64 gets a C64 screen and a laptop gets a
laptop one, and the two can sit in the same chat room.

If a board looks like line noise, the probe guessed wrong. Hang up, set your
terminal's character set to CP437, and call again.

## It asks for a handle

A handle is the name other callers see. It is not an email address and it is
not checked against anything.

Type a handle nobody on that board has taken and it offers you three things:

- **Register.** Pick a password, typed twice, and the board keeps an account
  for you: your profile, your messages, and however long the sysop allows you
  per day.
- **Guest.** No account and no password. You keep the handle you typed for
  that call, you get fifteen minutes, and nothing is saved. Lists mark you
  with a `*`.
- **A different handle.** If the one you wanted is taken.

Type a handle that already has an account and it asks for the password
instead. Three wrong tries and the board hangs up.

> Telnet has no encryption. Your password crosses the internet in the clear
> and so does everything you type. Use a password you use nowhere else, and
> say what you would say in public. [The longer version is here](/privacy).

## Then you are in

Type `?` for the menu. Every board is somebody's own arrangement, so the
commands differ, but a few are near universal: `WHO` for who else is on,
`CHAT` for the room, `PAGE` to get another caller's attention, `BYE` to hang
up. A board running this software also has `HELP` sections, so `? chat` shows
only the room commands.

There is a person behind it. If something is broken, or you want a feature,
the sysop's handle is on the listing and they will almost certainly answer.

## What a board knows about you

Your handle, your address, and when you called, in a log the sysop keeps so
they can see who has been on their own machine. If you registered, whatever
you typed into your profile. That is the whole list, and the sysop is the
only person who sees any of it.
