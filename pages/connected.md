# Your board is on the network

The installer's last step sends you here with the board's address, and this is how to call it.

<!-- The address arrives after the # in this page's link (/connected#192.168.0.109:6400), which never reaches the server; a few lines of script on the page read it. Everything inside "::: connected" is what shows when there is no address. -->
::: connected
This page was opened without an address. The installer adds it when it sends
you here, and there are two other places to find it:

- **The board's console.** With the board still on the USB cable, **Logs &
  Console** in the installer, or any serial monitor at 115200 baud, shows a
  line like `online 192.168.0.109  dial in: telnet 192.168.0.109 6400`, with
  your board's address in it.
- **Your router's list of connected devices**, where the board is called
  `unleashed`.

On most home networks `telnet unleashed.local 6400` reaches it by name as
well.
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
