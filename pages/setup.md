# Set up your BBS

Every setting on a µnleashed board can be changed from the board itself, while
you are logged in as the sysop, with one command: `CONFIG`. Nothing needs a
laptop, a text editor or a reflash. This page goes through every page CONFIG
has, and what each setting on it does.

::: cta
[Visit the web installer](/install)
[Build from source](/build#getting-it-running)
If the board is not on your network yet, start with one of those: the web
installer puts the BBS on it and sets up its Wi-Fi.
:::

::: art
setup-steps
:::

## First, become the sysop

A new board has one password, the sysop's, and it is `unleashed`. It only works
from your own network, and only until you change it. The [install
page](/install) says why. On your first call from your own network, the board
asks for it by itself, once you have signed up or logged in:

::: art
shot-setup-offer
:::

The right password makes you the sysop, and the board says so:

::: art
shot-setup-screen
:::

Then the staff passwords form opens by itself. Type a sysop password of your
own and press F1 to save it. The board will not take `unleashed` here.

::: art
shot-config-staff
:::

After that, a short tour of the settings, and then the sysop's prompt:

::: art
shot-newsysop-1
:::

After that, on any call, you become the sysop by typing `BYE` and your password
at the prompt. The board moves you to its sysop node, and the prompt starts
with `[S]`. A wrong password is an ordinary log off, and three wrong from one
address within fifteen minutes locks that address out for fifteen minutes.

## How CONFIG works

Type `CONFIG` on its own and the board lists its settings pages: six of its own,
then one for each plugin, which is a feature the board can switch on or off.

::: art
shot-config-list
:::

Type `CONFIG` and a page's name, such as `CONFIG board`, and that page opens as
a form.

::: art
shot-config-board
:::

- **Tab or the arrow keys** move between fields, as the bottom line says.
- **F1 saves.** Only the fields you changed are written, and the rest of the
  board's settings file is left exactly as it was, comments included.
- **ESC leaves** without saving.
- **Saved means live.** The board reloads the settings at once. The exceptions
  are the Wi-Fi page, the hostname and the NTP server, which are used from the
  next restart.
- **A value outside what a field accepts is refused** before anything is
  written, so a typo cannot take a page down.
- **One sysop at a time.** CONFIG is the sysop's alone: co-sysops do not get it,
  because it can change the staff passwords.

These screens were captured from the board's own software, version 0.23.0,
running on a test machine: the setup at 80 columns and the CONFIG pages at 48.
On a wider terminal the lists are wider; the forms are the same.

## board

The board's name and clock, and where callers land.

- **Board** (`board_name`): The board's name. The welcome screen tells callers
  who they are connecting to, and the directory lists the board under it. Empty
  means the software's own name. Takes up to 40 characters; as shipped, `My
  Board`.
- **Hostname** (`hostname`): The board's name on your network, for the router's
  list of devices and for `name.local` on computers that look those up. Used
  from the next restart. Takes a to z, 0 to 9 and `-`, up to 31 characters; as
  shipped, `unleashed`.
- **Timezone** (`tz`): The local time, as a POSIX time zone string. The number
  is hours **west** of UTC, so US zones are positive. `UTC0` is UTC;
  `EST5EDT,M3.2.0,M11.1.0` is US Eastern; `GMT0BST,M3.5.0/1,M10.5.0` is the UK;
  `CET-1CEST,M3.5.0,M10.5.0/3` is central Europe. Takes up to 40 characters; as
  shipped, `UTC0`.
- **NTP** (`ntp_server`): Where the board gets the time from. Used from the
  next restart. Takes up to 40 characters; as shipped, `pool.ntp.org`.
- **Idle min** (`idle_minutes`): How long a caller can sit at the prompt doing
  nothing before the board hangs up. It warns a minute before. Takes 1 to 240
  minutes; as shipped, `20`.
- **LED gpio** (`activity_led_gpio`): The pin of an LED that blinks with
  network traffic. 2 is the blue LED on the common DOIT-style dev boards. Takes
  0 to 39; as shipped, `2`.
- **Land on** (`landing`): Where a caller goes after logging in, unless their
  own account says otherwise. Takes `main`, `chat` or `forums`; as shipped,
  `main`.

## limits

How long callers can stay.

- **Per call** (`call_minutes`): The longest one call can last. Takes 1 to 1440
  minutes; as shipped, `60`.
- **Per day** (`day_minutes`): The most minutes one account can spend on the
  board in a day, over all its calls. Takes 1 to 1440 minutes; as shipped,
  `480`.
- **WHO min** (`who_refresh_min`): The fastest a caller can make the `WHO` and
  `DASH` screens refresh themselves, in seconds. Takes 1 to 60; as shipped,
  `1`.
- **WHO max** (`who_refresh_max`): The slowest, in seconds. Takes 1 to 60; as
  shipped, `30`.
- **Accounts** (`max_users`): The most accounts the board will hold. When it is
  full, nobody new can sign up. Takes 1 to 250; as shipped, `100`.

Staff can be spared the limits: the `NOLIMITS` permission, which every staff
level has as shipped, means no idle hang-up and no call or daily limit.

## accounts

Who can get in.

- **Sign-ups** (`self_register`): Whether somebody with a handle the board has
  not seen is offered **[R]egister**. With `no`, only staff can create
  accounts, from the `USERS` manager. Takes yes or no; as shipped, `yes`.
- **Guests** (`guest`): Whether that somebody is also offered **[G]uest**: a
  call with no account, where nothing is saved and the handle is marked `*` in
  every list. Takes yes or no; as shipped, `yes`.
- **Guest mn** (`guest_minutes`): How long a guest call can last. Guests have
  no daily limit. Takes 1 to 240 minutes; as shipped, `15`.

## backup

The backup window: a way to copy the board's settings, accounts and screens off
it as one zip file, and to put a copy back, from a computer on your network.

- **Port** (`backup_port`): The web port the window opens on. It cannot be
  6400, which callers use. Takes 1 to 65535; as shipped, `8080`.
- **Open for** (`backup_window_minutes`): How long one press of the button
  keeps the window open. Takes 1 to 60 minutes; as shipped, `5`.
- **Button** (`backup_button_gpio`): The pin of the button that opens it. 0 is
  the BOOT button on a dev board. Takes 0 to 39; as shipped, `0`.

To use it, log in as the sysop, then press BOOT on the board. While the window
is open, from a computer on the same network:

```
curl -o backup.zip http://<board>:8080/backup.zip
curl -T backup.zip http://<board>:8080/restore
```

On Windows, type `curl.exe` rather than `curl`. The first line downloads a
copy, with no question asked. The second sends one back: the board shows what
arrived on the sysop's screen and asks `Accept upload (Y/N)?`, and nothing
changes unless you answer Y within two minutes.

> A backup holds the staff passwords only as three asterisks and account passwords only as
> salted hashes, but it holds the **Wi-Fi password as typed**. That is why the
> board only hands one to an address on your own network. Keep backups
> somewhere private.

The window closes when its minutes are up or when the sysop logs off.

## staff

The three staff passwords. A caller becomes staff by typing `BYE` and one of
these at the prompt.

- **Sysop** (`sysop_password`): Moves you to the sysop node, with every
  permission, CONFIG included. Takes up to 32 characters, case-sensitive; as
  shipped, `unleashed` until you change it.
- **Co-sysop 1** (`cosysop1_password`): Grants co-sysop 1 on the line you are
  already on, with the permissions described below. Takes up to 32
  characters; empty as shipped.
- **Co-sysop 2** (`cosysop2_password`): The same for co-sysop 2, with fewer
  permissions. Takes up to 32 characters; empty as shipped.

Passwords on this page:

- A password already set shows as `********`, and is only written when you type
  a new one.
- An empty password switches that level off.
- Use passwords you use nowhere else. Calls to a BBS are not encrypted, which
  [the privacy page](/privacy) explains in plain terms.

What a co-sysop may do is a table in the board's settings file, not a CONFIG
page. As shipped, both co-sysop levels may list who is on with their addresses,
broadcast, add or take away a caller's time, see the ban list, see the
dashboard, and skip the time limits. Co-sysop 1 may also kick and watch callers,
hide from the lists and manage accounts; only the sysop may lift a ban. To
change that table, edit the settings file inside a backup and send it back
through the backup window.

## wifi

The network the board joins.

- **Network** (`wifi_ssid`): The name of the Wi-Fi network. Takes up to 32
  characters; set to what you chose when installing.
- **Password** (`wifi_password`): Its password. Takes 8 to 64 characters, or
  empty for an open network.

A change here is used from the **next restart**, never straight away, because
changing the network under your own call would drop you, and a typo would leave
nobody on the board to put it right. If the board cannot reach its network, the
fix is the cable: [the install page](/install) changes the Wi-Fi from your
browser.

## The plugin pages

Every plugin's page starts with the same four fields:

| Field | What it does |
|---|---|
| **Enabled** | yes or no. A plugin that is off costs nothing: no commands, no memory. |
| **Read** | Who may use it to look. |
| **Write** | Who may use it to change something. |
| **Admin** | Who may configure it. |

The levels, from widest to narrowest: `all` (anybody, guests too), `users`
(anybody with an account), `staff` (any staff level), `co2`, `co1` and `sysop`.
Each one lets in that level and every level after it.

### chat

The chat room. On as shipped, and anybody may talk, guests included.

- **room**: The room's name. Takes up to 19 characters; as shipped, `Main`.
- **rate**: How many lines a minute one caller may send, with a burst of 8.
  Only the caller who trips it is told. Takes 6 to 600; as shipped, `80`.
- **history**: How many lines the room remembers, shown to whoever joins. Takes
  8 to 2000; as shipped, `48`.
- **mail_slots**: How many messages the board holds at once, for everyone. 0
  switches messages off. Takes 0 to 64; as shipped, `32`.
- **mail_chars**: The longest a message may be. Takes 16 to 512 characters; as
  shipped, `512`.
- **mail_days**: How long an unread message waits before it expires. Takes 1 to
  365 days; as shipped, `14`.

The chat page shows the settings the board's settings file already carries, so
the labels are their own names. The file also sets the room's colours
(`color_node`, `color_text` and so on), each one a colour name: black, white,
red, cyan, purple, green, blue, yellow, orange, brown, ltred, darkgrey, grey,
ltgreen, ltblue or ltgrey.

Messages are not private: the board keeps them as plain text.

### files

File areas: folders on the SD card that callers can list, download from and
upload to. It needs a card, and without one the page is there but the plugin
does not start. Read, Write and Admin are `all`, `staff` and `sysop` as
shipped.

::: art
shot-config-files
:::

There are eight areas, and each one is a button: Enter opens it as a page of its
own.

::: art
shot-config-area
:::

| Field | What it does |
|---|---|
| **Path** | The folder on the card, up to 48 characters. It is never shown to callers, and the board creates it if it is not there. |
| **Name** | What callers see, up to 24 characters. |
| **Read** | Who sees the area in the list. Unset, the plugin's Read. |
| **Upload** | Who may put files in and describe them. Unset, the plugin's Write. |
| **Download** | Who may take files out. Unset, this area's Read. |
| **Delete** | Who may remove files and approve or reject uploads. Unset, the plugin's Admin. |

An upload is invisible to everybody but staff until somebody with Delete
approves it. Saving an area writes all four levels down, so what you saw on the
form is what the area runs under from then on. [The SD card
page](/sdcard) has the wiring.

### forums

The message boards, in topic areas. They need a card, and they are **off** as
shipped, so the topics can be set up first. Read, Write and Admin are `all`,
`users` and `co1`. CONFIG offers four topics, each a button like a file area:

| Field | What it does |
|---|---|
| **Key** | The topic's folder on the card, up to 12 characters. |
| **Name** | What callers see, up to 24 characters. |
| **About** | One line about it, up to 40 characters. |
| **Read** | Who sees the topic. Unset, the plugin's Read. |
| **Start** | Who may start a new subject. Unset, this topic's Reply. |
| **Reply** | Who may add to a subject already started. Unset, the plugin's Write. |
| **Moderate** | Who may moderate the topic, which includes removing posts. Unset, the plugin's Admin. |

Start and Reply are separate so that a topic can be news: Start `co1` and Reply
`users` means staff post, and anybody with an account may answer.

### info

The ten information pages, which callers read with `INFO` and from the chat room
with `/i`. On as shipped: anybody may read them, and only the sysop may write.
CONFIG has a button for each of Page 0 to Page 9:

| Field | What it does |
|---|---|
| **Title** | The page's title in the list, up to 24 characters. |
| **Read** | Who sees it. Unset, the plugin's Read. |

The text itself is not written in CONFIG: `INFO 3 EDIT` at the prompt opens
page 3 in the board's message editor.

### announce

The directory listing: a short message the board sends every few minutes so it
appears on [the board list](/). **Off** as shipped, and the sysop's alone. It
sends the board's name, your name, the description, the port and how busy the
board is, and nothing about who is calling. `ANNOUNCE TEST` shows exactly what
it would send.

> Change the sysop password before you switch this on: the board will not list
> itself while the default password is still set. And [forward the
> port](/forward) first, or callers will find a listing that does not answer.

- **Board**: The name the directory will show. It is the Board field on the
  board page, shown here, not a second copy.
- **Sysop**: Your name, as the directory shows it. Takes up to 40 characters.
- **About**: One line about the board. Takes up to 120 characters.
- **DNS name**: A name of your own that reaches the board, if you have one.
  Empty means the address the directory saw the message come from. Takes up to
  95 characters.
- **Port**: The port callers dial, if you forwarded a different one to the
  board's 6400. Takes 1 to 65535; as shipped, `6400`.
- **Directory**: Where to send it. Comma separated, up to four, so a board can
  be in several directories.
- **Every min**: Minutes between messages. Takes 1 to 1440; as shipped, `10`.
- **Push secs**: When somebody calls or leaves, the board tells the directory
  early, at most this often. 0 leaves only the timed message. Takes 0 to 3600;
  as shipped, `60`.
- **Activity**: Whether to include the board's calls and caller-minutes over
  the last 24 hours. Takes yes or no; as shipped, `no`.
- **Token**: Issued by the directory the first time, and kept so the listing
  survives a reflash. Leave it alone.

[Getting listed](/how) has the rest, including the house rules.

### sd

The SD card. On as shipped, and the sysop's alone. With no card it tries once at
start and then costs nothing.

- **CS pin**: Chip select. Move it to 4 if the board will not start with a card
  fitted. Takes 0 to 33; as shipped, `5`.
- **MOSI pin**: Data to the card. Takes 0 to 33; as shipped, `23`.
- **CLK pin**: The clock. Takes 0 to 33; as shipped, `18`.
- **MISO pin**: Data from the card. Takes 0 to 39; as shipped, `19`.
- **Bus kHz**: The bus speed. Slower is steadier on long jumper wires. Takes
  400 to 40000; as shipped, `20000`.
- **Screens**: Whether screens on the card replace the board's own, file by
  file. Takes yes or no; as shipped, `yes`.

The card holds file areas, the forums and your own screens. The accounts, the
settings and the caller log stay on the board, so a card that fails loses none
of them. [The SD card page](/sdcard) has the wiring.

### serial and example

Both are **off** as shipped. The serial bridge shares a device wired to the
board's second serial port, where one person types and anybody else may watch,
and its page sets the pins, the speed and the format. The example plugin does
nothing useful; it is the template for somebody writing a plugin of their own.

## Then

- [Call the board](/terminals) from anything with a telnet client, and see it
  as your callers will.
- [Forward port 6400](/forward) when you want callers from outside your own
  network, and not before the sysop password is yours.
- [Put it on this list](/how) with the announce page above.
