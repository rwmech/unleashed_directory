# What the badges mean

The small marks under a board's name on the [board list](/). Some are sent by the board itself, and the rest are worked out here, from this directory's own record of that board. Point at one, or tap it, and it says what it is.

<!-- The badges below are drawn from the same tables in server.py that the board list uses (LETTER_BADGES, AGES, SUPPORT), so the key cannot disagree with the list. Change a badge there, not here. -->

## Sent by the board

A board says these about itself in every heartbeat, so each one is as current as the board's last word. A board that stops sending one loses the badge. Nothing here checks them: they are the sysop's word, the same as the board's name and description.

::: badges
board
:::

## Worked out by the directory

A board cannot set these. The directory works them out from what it has seen for itself: when the board was first listed, and which of its heartbeats arrived.

::: badges
directory
:::

### How steady is worked out

Every heartbeat says how often the board will call in. Over seven days that adds up to a number of heartbeats due: a board that calls every ten minutes owes 1,008 a week. The directory counts the ones that actually arrive, hour by hour, and a board that answered more than 95% of what it owed gets the badge. An hour with extra heartbeats cannot make up for a silent one, because no hour counts for more than it was due.

The directory has to have watched a board for the whole week before it can earn it. A board that goes quiet for an afternoon loses it, and gets it back after a steady week.

## Show your support

Add these badges to show what your board stands for. They come from a fixed list, chosen by the directory rather than typed in by a board, which is what stops anybody putting words of their own on the page.

A board sends the slugs, the short word after each name below, in the `support` list of its heartbeat, described in [the protocol](https://github.com/rwmech/unleashed_directory/blob/main/PROTOCOL.md). For a sysop that means typing them, separated by commas, into wherever their BBS software keeps its directory settings. A slug this directory does not know is ignored.

::: support
:::

The first ten are the causes most often shown as support badges, ribbons and flair on community sites and profiles, picked because they are widely recognised and belong to no political party. The last is amateur radio, this hobby's oldest neighbour.

> [!NOTE]
> The µnleashed firmware does not send any of the fields on this page yet. Until a release does, µnleashed boards show only the badges the directory works out for itself.
