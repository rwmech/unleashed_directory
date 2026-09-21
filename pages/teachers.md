# For teachers

A bulletin board system is a small server that answers over the network and
talks in plain text. This one runs on an ESP32, costs about as much as a
sandwich, and a class can build, wire, house and operate one over five
sessions.

It is a good teaching object for one specific reason: it is small enough to
understand completely. A student can hold the whole system in their head, from
the socket the caller arrives on to the file on the card the caller downloads.
Very little else on a modern network is like that.

> [!NOTE]
> Everything below works on a classroom network with no internet access at
> all. Nothing here needs a port forwarded, and the section on school networks
> explains why that is fine rather than a compromise.

## What it teaches

Each of these is something students can see happening rather than take on
trust.

| Idea | Where it shows up |
|---|---|
| Client and server | One board, many callers. The words are roles, not machines: the same laptop is a client here and a server in the next lesson |
| Addresses and ports | The board answers on port 6400. Change it and nothing connects until the caller is told. Ports stop being magic |
| Text encoding | The board detects ANSI with CP437 or UTF-8, PETSCII, or plain ASCII, and draws itself differently for each. Text is bytes, and bytes need an agreement |
| Serial protocols | Four wires to the card, and XMODEM and YMODEM for transfers: blocks, checksums, acknowledgments and retries, small enough to trace on paper |
| Filesystems | FAT32 on the card because a laptop can read it, LittleFS on the chip because it survives losing power mid-write |
| Owning versus renting | The user list is a text file on a chip in the room. Compare that with any service the school pays for |
| Version control | The whole project is public and under the GPL. Students can read it, change it, and keep their changes |

## What you need

- **One ESP32 dev board per group.** A few dollars each. Any module with 4 MB
  of flash works.
- **A USB cable per group.** Often already in a drawer.
- **One computer per group** to build and flash from, and a terminal program.
  [The terminals page](/terminals) lists free ones for Windows, macOS, Linux,
  Android and iOS. **If your machines are Chromebooks, read the next section
  before you plan anything**, because a Chromebook needs a setting turned on
  first and it may not be yours to turn on.
- **Optional, for file areas:** a micro SD card module, about two dollars, and
  a card of 32 GB or less. Plus six jumper wires.
- **Optional, for the enclosure:** a 3D printer, or a print service, and a
  browser for TinkerCAD.

One board serves a whole class of callers at once, so you do not need one per
student. A single board plus everybody's laptops is a complete first lesson.

## If your class is on Chromebooks

Check this before you plan the first session. It is the one thing that can
stop session 1 dead, and it is not something you can fix on the day.

Chrome itself cannot call a board. No web page and no Chrome extension is
allowed to open the kind of plain network connection telnet needs. So a
Chromebook needs either the **Linux development environment** turned on, or
the Play Store and an Android terminal app, and on a school Chromebook both of
those are administrator settings that are usually off.

**Test one machine yourself first.** Select the time at the bottom right, then
**Settings**, then **About ChromeOS**, then **Developers**. If there is a
**Linux development environment** row with a **Set up** button, your fleet is
fine, and [the terminals page](/terminals) has the steps from there.

If the row is missing or the button refuses, ask for it by name. The request
is small, specific, and can be granted to one group of users rather than to
the whole school:

- In the Google Admin console, under **Devices > Chrome > Settings**, on the **User & browser settings** page, in the section **Virtual machines (VMs) and developers**.
- The setting is **Linux virtual machines (BETA)**. The value to ask for is **Allow usage for virtual machines needed to support Linux apps for users**.
- It starts a sandboxed Debian container. It is not developer mode, it does not unenrol the device, and by Google's own description a bad Linux app can affect other Linux apps and nothing outside them. That is usually the question underneath the question.

If the answer is no, find that out early rather than improvising in front of
a class. A board on the classroom network is still reachable from any Windows,
Mac or Linux machine in the room, and one machine on the projector with the
chat room open is a perfectly good version of session 1 with the class taking
turns at the keyboard. Sessions 2 and 3 need a computer that can flash a board
over USB in any case, which is a larger job on a Chromebook than calling one
is.

## Five sessions

Written as fifty minute periods. Session 4 is the one that usually runs over,
and it is the one students ask to stay behind for.

### Session 1: Call a board

**50 minutes. Needs:** one board already running on the classroom network,
which you set up beforehand, and a terminal program on each machine.

Students connect to an address and a port, choose a handle, and end up in the
chat room together. Give them ten minutes to work out that they are all typing
into the same machine.

Then take it apart on the whiteboard. What is the address. What is the port.
Which machine is the server and which are the clients. Why does the board know
that one of them is on a phone.

**Extension:** have one group set their terminal to the wrong character set
and look at the result. Text encoding lands much harder as a broken screen
than as a definition.

### Session 2: Flash a board

**50 to 90 minutes. Needs:** an ESP32 and USB cable per group, and the build
instructions from [the build page](/build).

Each group builds the firmware and flashes it, gives the board the classroom
wifi, and watches the console print the address it came up on. Then they call
their own board from the machine next to them.

The moment a group calls their own board for the first time is the lesson. Do
not rush past it.

**Watch out for:** driver installation for the USB serial chip, which is the
usual first-lesson time sink. Do it before the period, not during it.

### Session 3: Wire the card

**50 minutes. Needs:** an SD card module, a card of 32 GB or less formatted as
FAT32, and six jumper wires per group.

Four wires carry the data and two carry the power. Students wire it against
[the pin map](/sdcard), mount the card, and set up a file area.

Two things are worth stopping on. The module goes on 3V3 and not VIN, and the
page explains what happens if you get that wrong. And the card is FAT32
specifically so that a laptop can read it afterwards, which students can prove
by pulling the card and plugging it into a computer.

Then have them move a file onto the board and off again, and look at what
XMODEM is doing: a block, a checksum, an acknowledgment, and a retry if it
does not match.

### Session 4: Design the case

**Two 50 minute sessions, plus print time. Needs:** TinkerCAD in a browser,
which is free, and a 3D printer or a print service.

This is the session that turns a circuit board into a thing somebody owns.

Students measure their board, model a case in TinkerCAD, and deal with the
constraints that make it a real design problem rather than a box: a slot for
the USB connector, a window or a light pipe for the LED, somewhere for the
card to go in and out, and a way for the two halves to hold together without
glue.

The first print usually does not fit. That is the most useful part of the
session, and it is worth leaving time to measure, adjust and print again.

**Extension:** ask each group to design for a different constraint. Wall
mounted. Stackable. Fits in a pocket. Looks like it came out of 1984.

### Session 5: Run it

**50 minutes. Needs:** the boards from the sessions above.

Each group becomes the sysop of their own board. They write the welcome
screen, decide the rules, set who is allowed to do what, and look at the
caller log to see who has been on.

Then the discussion that the whole unit was building towards. The user list is
a text file on a chip on the desk. Nobody else has a copy. Nothing is sold,
nothing is measured, and no company can change the terms. Compare that with
any service the school pays for, and ask which parts of the difference matter.

## About your school network

Almost certainly you will not be able to forward a port, and you should not
try. That setting lives on equipment the network administrator owns, and on a
school network the answer is going to be no for good reasons.

This costs you nothing. A board on the classroom network is reachable from
every machine in the room, and every one of the five sessions above works
exactly as written. The only thing you lose is callers from outside the
school, which is not what the unit is about.

If a student wants a board reachable from the internet, that is a project for
home, with a parent, and it is a decision for the adult who owns that
connection. [The page about what opening a port actually does](/forward) is
written for exactly that conversation.

## Things to say out loud

- **Nothing on a board is encrypted.** Everything typed crosses the network in
  the clear, and the sysop can read all of it. Students should know that
  before they type, and it is a better lesson in how networks work than any
  slide about it.
- **Handles, not names.** A made up name is the point. There is no reason for
  a student to type a real name, an address or a phone number into a board,
  including their own.
- **Passwords are not reusable.** If a board asks for one, it should be a
  password used nowhere else. This is worth saying every time.

There is a page written for students directly, at a reading level for about
eleven upwards, covering the same ground in their own terms:
[a board of your own](/kids).

## Where to go next

[Build one](/build) is the full instructions, including flashing and
configuration. [Adding an SD card](/sdcard) has the pin map and the three
things that usually go wrong. [Terminal software](/terminals) covers what to
call a board with, on every platform a classroom is likely to have, including
Chromebooks and what to ask for when one is locked down.

The firmware and the documentation are free software under the GPL, so a
school can use all of it, change any of it, and keep the changes.
