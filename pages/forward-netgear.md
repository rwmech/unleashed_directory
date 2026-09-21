# Port forwarding on a NETGEAR router

Nighthawk and R-series, through the web interface at routerlogin.net.

> This opens a door into your own network and you are responsible for what
> comes through it. Read [the warnings](/forward) first if you have not.

## Log in

1. Connect a computer to the router, wired or Wi-Fi.
2. Go to `www.routerlogin.net`, or `routerlogin.com`, or the router's address,
   usually `192.168.1.1` or `192.168.0.1`.
3. User name `admin`. The password is the one set during first-time setup, not
   the factory `password`. Both are case sensitive.

Forgotten the password? Click **CANCEL** at the prompt to reach Router Password
Recovery, which needs the serial number and your security answers, and only
works if recovery was enabled beforehand. Otherwise hold **Reset** for about 15
seconds, which erases every setting including your Wi-Fi name and password.

The router's own address is shown under **ADVANCED**, in **Router Information**.

## Give the board a fixed address

A forward points at an address. If the board gets a different one from DHCP
later, the rule quietly stops working.

1. Find the board under **BASIC > Attached Devices**. Match on MAC address.
2. Go to **ADVANCED > Setup > LAN Setup**. Some models label the first menu
   **Settings** rather than **ADVANCED**.
3. In **Address Reservation**, click **Add**.
4. Enter the **IP Address** you want, inside the router's own range, for
   example `192.168.1.50`, and the board's **MAC Address**.
5. Click **Apply**.

The reservation applies the next time the board asks for a lease, so reboot it.

## Add the rule

1. Go to **ADVANCED > Advanced Setup > Port Forwarding / Port Triggering**.
2. Leave **Port Forwarding** selected.
3. Port 6400 has no predefined entry, so click **Add Custom Service**.
4. Fill the form in as the table below sets out.
5. Click **Apply**.

| Field | Value |
|---|---|
| Service Name | `BBS` |
| Service Type | `TCP` |
| External Starting Port | `6400` |
| the ending port field | `6400` |
| Use the same port range for Internal port | leave ticked |
| Internal IP address | the address you reserved |

NETGEAR's documentation names **External Starting Port** explicitly but not the
label on the ending field, so that one is described rather than quoted.

Rules are matched from the top down and the first match wins, so keep specific
rules above broad ones.

## The Nighthawk app

NETGEAR's description of the app covers parental controls, Armor, guest Wi-Fi
and general settings. It does not document port forwarding, and there is no
NETGEAR article describing it there. Treat this as a job for the web interface.

## Older genie firmware

The BASIC / ADVANCED layout is genie, and the path above is the same. On some
older gateway and DSL models the equivalent lives under **ADVANCED > Security >
Firewall Rules**, where you add a custom service and then use **Inbound
Services**. If you see Firewall Rules instead of Port Forwarding / Port
Triggering, use that.

## When it does not work

- **Double NAT.** NETGEAR lists port forwarding among the things it breaks. If
  the NETGEAR sits behind an ISP gateway that is also routing, bridge the
  gateway or forward on it instead.
- **CGNAT.** If the WAN address does not match an external "what is my IP", or
  sits in `100.64.0.0/10`, no setting will help. NETGEAR has no article on this.
- **Testing from inside.** Many routers do not loop back, so your own public
  address may fail from your own network while working fine from outside. Test
  from a phone on mobile data. NETGEAR also notes its anti-port-scan feature can
  make external scanners report a working port as closed.
- **A changing address.** Unless you pay for a static one, your public address
  moves. Use dynamic DNS, or let the directory listing track it for you.
- **The board itself.** Check it is answering on your own network first.

## Sources

- [Set up port forwarding to a local server](https://kb.netgear.com/24289/How-do-I-set-up-port-forwarding-to-a-local-server-on-my-NETGEAR-router)
- [Add a custom port forwarding service](https://kb.netgear.com/24290/How-do-I-add-a-custom-port-forwarding-service-on-my-NETGEAR-router)
- [Reserve a LAN IP address](https://kb.netgear.com/24091/How-do-I-reserve-a-LAN-IP-address-on-my-Nighthawk-router)
- [Log in to your router](https://kb.netgear.com/980/How-do-I-log-in-to-my-NETGEAR-router)
- [Password recovery](https://kb.netgear.com/20027/Configuring-router-administrative-password-recovery)
- [What is double NAT](https://kb.netgear.com/000033731/What-is-double-NAT-and-why-is-it-bad)
- [RFC 6598, shared address space](https://www.rfc-editor.org/rfc/rfc6598)
