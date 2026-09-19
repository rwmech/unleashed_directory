# Port forwarding on an Xfinity gateway

XB6, XB7 and XB8, through the Xfinity app.

> This opens a door into your own network and you are responsible for what
> comes through it. Read [the warnings](/forward) first if you have not.

On a rented Xfinity gateway, port forwarding lives in the mobile app, not in
the gateway's own web page. Comcast states that customers with xFi Gateways can
only set up and adjust port forwarding using the Xfinity app.

## Steps in the app

1. Open the Xfinity app and sign in with a Primary, Manager or Member ID.
2. Select **WiFi**.
3. Select **View WiFi equipment**.
4. Select **Advanced Settings**.
5. Select **Port Forwarding**.
6. Select **Add Port Forward**, then **Continue**.
7. Pick the board from the device list. It must be connected, on IPv4, using
   DHCP.
8. Pick a preset, or select **Manual Setup** to enter ports and protocol.
9. Select **Next** to save.

For a board: choose Manual Setup, external and internal port both `6400`,
protocol TCP. Comcast's article confirms Manual Setup takes port numbers and
settings but does not print the field labels, so the exact wording on screen is
not quoted here.

## The web route, and the local page

The old xFi web pages no longer carry port forwarding. The current
documentation describes the app only.

The local admin page at `http://10.0.0.1` still exists but on XB6 and newer it
is gated behind an app toggle and does not offer port forwarding. To enable it:
**WiFi > View WiFi equipment > Advanced Settings > Admin Tool online access >
Allow Admin Tool access > Save**. The username is `admin`.

## Reserving an address

A forward has to point at an address that does not move. The app binds the rule
to the device you picked rather than showing a reservation screen, and there is
no official Comcast article documenting a reserved-IP control in the app, so
treat any menu path you find for it as unverified. The route people commonly
use is the Admin Tool: **Connected Devices > Devices > Edit > Reserved IP**.
That comes from Comcast's forums, not its documentation.

One caveat from the official article: if the device uses MAC address
randomisation the rule will break, and a forward whose device has gone cannot
be edited, only deleted and recreated. Turn randomisation off for the board.

## Using your own router instead

Put the gateway in Bridge Mode: Admin Tool at `http://10.0.0.1` >
**Gateway > At a Glance > Enable** next to Bridge Mode. Routing stops and the
modem function stays. You lose the gateway's wifi, xFi network management, wifi
extenders and Xfinity CyberSecure, and only one device may connect by Ethernet.
Your own router then does the forwarding.

## When it does not work

- **Xfinity CyberSecure**, previously Advanced Security. When it sees something
  aimed at a device with port forwarding, DMZ or UPnP ports open, it blocks all
  traffic from that device's open ports. Use Allow Access on the device, or
  turn the feature off. This catches people out constantly: the rule is correct
  and the traffic is still dropped.
- **Double NAT.** Your own router behind a gateway that is still routing gives
  two layers, and the forward has to exist on both. Bridge Mode is the fix.
- **CGNAT.** If the gateway's WAN address is in `100.64.0.0/10` and does not
  match an external "what is my IP", inbound forwarding cannot work on that
  plan. Comcast publishes nothing confirming or denying this, so compare the
  two addresses rather than assuming.
- **IPv4 only.** The app's port forwarding is IPv4. Xfinity carries both, so a
  board reachable over IPv6 may still be unreachable over IPv4.

## Sources

- [xFi port forwarding](https://www.xfinity.com/support/articles/xfi-port-forwarding)
- [xFi advanced settings](https://www.xfinity.com/support/articles/xfi-advanced-settings)
- [Admin Tool access](https://www.xfinity.com/support/articles/admin-tool-access)
- [Enable or disable Bridge Mode](https://www.xfinity.com/support/articles/wireless-gateway-enable-disable-bridge-mode)
- [Using xFi Advanced Security](https://www.xfinity.com/support/articles/using-xfinity-xfi-advanced-security)
- [About IPv6](https://www.xfinity.com/support/articles/about-ipv6)
