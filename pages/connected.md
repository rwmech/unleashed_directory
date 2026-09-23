# Your board is on the network

The installer's last step sends you here with the board's address, and this is how to call it.

<!-- The address arrives after the # in this page's link (/connected#192.168.0.109:6400), which never reaches the server; a few lines of script on the page read it. Everything inside "::: connected" is what shows when there is no address. Since site 1.0.0 the installer's dashboard always offers Telnet details, and sends a board it read before it joined Wi-Fi here with no address, so these three ways are what many readers will see. Facts from the firmware: mDNS <hostname>.local (main.cpp mdns_hostname_set), hostname "unleashed" as shipped (config.h BBS_HOSTNAME), the "online ... dial in:" line logged when Wi-Fi joins (main.cpp). -->
::: connected
This page was opened without the board's address. That happens when the
installer read the board before it had joined your Wi-Fi, so it had no
address to hand over yet. It joins a few seconds later, and there are three
ways to find it:

1. **By name.** The board gives itself a name on your network, the
   **Hostname** in its settings, which is `unleashed` unless you changed it.
   Add `.local` and most current computers find it with no address at all:
   `telnet unleashed.local 6400`.
2. **From the board itself.** With the board still on the USB cable, open
   **Logs & Console** in the installer, then press the board's reset button
   (often marked EN or RST), or **Reset Device** in the console. As it starts
   it prints a line like
   `online 192.168.0.109  dial in: telnet 192.168.0.109 6400`, with your
   board's address in it. Any serial monitor at 115200 baud shows the same
   line.
3. **From your router.** Its list of connected devices shows the board under
   the same name, `unleashed`, with its address beside it.
:::

## The sysop password

A new board's sysop password is `unleashed`, and it only works from your own
network. Change it on this first call: sign up or log in, and the board asks
for it, then for a password of your own. [The install
page](/install#the-sysop-password) says what that password can and cannot do
until you have.

> **Change it before anything else.** Do not [forward the port](/forward) and
> do not turn on the directory listing until the password is yours.

[Set up your BBS](/setup) goes through every setting after that.
