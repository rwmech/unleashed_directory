# Port forwarding on a NETGEAR router

Nighthawk and R-series, through the web interface at routerlogin.net.

> This opens a door into your own network and you are responsible for what
> comes through it. Read [the warnings](/forward) first if you have not.

## Log in

1. Connect a computer to the router, wired or Wi-Fi.
2. Go to `www.routerlogin.net`, or `routerlogin.com`, or the router's address,
   which NETGEAR gives as `192.168.1.1` or `192.168.0.1`.
3. User name `admin`. The password is the one set during first-time setup.
   Older routers shipped with the factory password `password`. Both are case
   sensitive.

Forgotten the password? Enter wrong credentials three times and the **Router
Password Reset** screen appears. It asks for the router's serial number and the
answers to the two security questions chosen at setup, so it only works if
password recovery was switched on beforehand. Otherwise hold **Reset** for 15
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
| External Ending Port | `6400` |
| Use the same port range for Internal port | leave ticked |
| Internal IP address | the address you reserved |

Rules are matched from the top down and the first match wins, so keep specific
rules above broad ones.

## The Nighthawk app

NETGEAR's port forwarding articles describe the web interface only, and none of
them covers the Nighthawk app. Treat this as a job for the web interface.

## Older genie firmware

The BASIC / ADVANCED layout is genie, and the path above is the same. On
NETGEAR's DSL modem routers the equivalent is **Firewall Rules**, under
**Security** in the menu on the left (**Content Filtering** on older ones).
Define the port first under **Services > Add Custom Service**, then add it as an
inbound service. If you see Firewall Rules instead of Port Forwarding / Port
Triggering, use that.

## When it does not work

Double NAT and CGNAT stop any router's forward, and both are
explained on [the main port forwarding page](/forward#two-things-that-will-stop-it-working).
What NETGEAR adds:

- **Double NAT.** NETGEAR lists port forwarding among the things it breaks. If
  the NETGEAR sits behind an ISP gateway that is also routing, bridge the
  gateway or forward on it instead.
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
- [Reserve an IP address](https://kb.netgear.com/25722/How-do-I-reserve-an-IP-address-on-my-NETGEAR-router)
- [Log in to your router](https://kb.netgear.com/980/How-do-I-log-in-to-my-NETGEAR-router)
- [Find the router's address](https://kb.netgear.com/23664/How-do-I-locate-my-router-s-IP-address)
- [Turn on password recovery](https://kb.netgear.com/20027/Configuring-router-administrative-password-recovery)
- [Reset a forgotten admin password](https://kb.netgear.com/24220/How-to-reset-your-NETGEAR-router-admin-password)
- [Firewall rules on DSL modem routers](https://kb.netgear.com/8219/How-do-I-set-up-firewall-rules-on-my-NETGEAR-DSL-modem-router)
- [Online port scanners and the anti-port-scan feature](https://kb.netgear.com/23416/Port-Forwarding-to-an-IP-camera-on-a-NETGEAR-genie-router)
- [What is double NAT](https://kb.netgear.com/000033731/What-is-double-NAT-and-why-is-it-bad)
- [RFC 6598, shared address space](https://www.rfc-editor.org/rfc/rfc6598)
