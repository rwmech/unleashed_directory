# Your first call

You have a terminal, you have picked a board off the list, and it answered.
Here is what happens next.

::: art
firstcall
:::

## It works out what you are

The board sends a short probe the moment you connect and reads what comes
back. ANSI with CP437 or UTF-8, PETSCII at 40 or 80 columns, or plain ASCII. A
modern terminal answers the probe and you are asked nothing. If yours stays
silent, the board asks you to press DEL or BACKSPACE, which tells it whether
you are on a Commodore or a plain ASCII terminal, and a Commodore is then asked
whether it has 40 or 80 columns. Each machine gets screens made for it, and
they can all sit in the same chat room.

If a board looks like line noise, the probe guessed wrong. Hang up, set your
terminal's character set to CP437, and call again.

## It asks for a handle

A handle is the name other callers see. It is not an email address and it is
not checked against anything.

Type a handle nobody on that board has taken and it offers you up to three
things. A sysop can switch the first two off, so not every board offers all
of them:

- **Register.** Pick a password, typed twice, and fill in a short form. It
  also asks for a name and an email address. Neither is verified, because the
  board cannot send email: other callers can see the name, and only you and the
  board's staff can see the email. The board then keeps an account for you:
  your profile, your messages, and however long the sysop allows you per day.
- **Guest.** No account and no password. You keep the handle you typed for
  that call, you get fifteen minutes on a board with the usual settings, and no
  account is kept. Lists mark you with a `*`.
- **A different handle.** Back to the prompt, if that was not the name you
  meant to type.

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

Your handle, the internet address you called from, and when and for how long,
in a log the sysop keeps so they can see who has been on their own machine. If
you registered, what you typed into the sign-up form and your profile: other
callers can see your name and your profile, and your email, where you are from
and your phone number are visible only to you and the board's staff. And
whatever you wrote there: mail, forum posts, lines in the chat room. That is
the whole list, and the people who run the board can read all of it.
