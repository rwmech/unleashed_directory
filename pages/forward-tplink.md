# Port forwarding on a TP-Link router

Archer series through the web interface, and Deco mesh through its app.

> This opens a door into your own network and you are responsible for what
> comes through it. Read [the warnings](/forward) first if you have not.

## Log in

Default address is `http://tplinkwifi.net`, or `192.168.0.1` or `192.168.1.1`
depending on model. Deco uses `192.168.68.1`. If none work, read the default
gateway from a client: Windows calls it Default Gateway, macOS and iOS call it
Router, Android calls it Gateway.

Some models use `admin` / `admin`. Others have no default and make you create a
password at setup. There is no password lookup: some newer models can recover
it through a linked TP-Link ID, and otherwise you hold **Reset** for about 10
seconds with the router powered on, which wipes Wi-Fi settings, internet
settings, the admin password and any forwarding rules you already had.

## Give the board a fixed address

Go to **Advanced > Network > DHCP Server > Address Reservation**, click **Add**,
enter the board's MAC address and the address you want, then enable the entry.
The address must be inside the router's own range. Some models want a reboot.

## Add the rule

The menu depends on which interface generation your model runs, so check the
screen rather than the model number.

- **Older models** (TL-WR840N, TL-WR940N, Archer C20, C50):
  **Forwarding > Virtual Servers > Add New**. Fields are Service Port, Internal
  Port, IP Address, Protocol, Status.
- **Most current Archers** (A9, C7, AX10, AX6000):
  **Advanced > NAT Forwarding > Virtual Servers > Add**. Fields are Service
  Type, External Port, Internal Port, Internal IP, Protocol.
- **Newer premium models** (Archer A8, AX55, AX90, AX11000):
  **Advanced > NAT Forwarding > Port Forwarding > Add**. Fields are Service
  Name, External Port, Internal Port, Device IP Address, Protocol.

For a board on the middle interface: External Port `6400`, Internal Port `6400`,
Internal IP the address you reserved, Protocol `TCP`, then **Save**.

The same page also holds Port Triggering, DMZ and UPnP. Virtual Servers wins
over all three when rules overlap. Do not use DMZ.

## The Tether app

TP-Link's port forwarding documentation covers the web interface only, and does
not describe forwarding in the Tether app. Use the web interface.

## Deco mesh

Documented, and different: **Deco app > More > Advanced > NAT Forwarding > Port
Forwarding**, then the `+` icon. Fields are Service Type (or Custom plus a
Service Name), Internal IP, External Port, Internal Port. Leave Internal Port
blank and it matches the external one.

Deco will not accept a typed address: the board must already be connected and
holding a lease so you can pick it from the list. Some models cap out at 64
rules.

## When it does not work

Double NAT and CGNAT stop any router's forward, and [the main
page](/forward#two-things-that-will-stop-it-working) explains both. What TP-Link adds:

- **Where the WAN address is.** **Advanced > Status > Internet**, or on Deco
  **More > Internet Connection > IPv4**. A private one means another router
  upstream: forward the same port there too, or bridge the ISP modem.
- **The host firewall.** A blocked listener, or a network profile set to
  Public, looks exactly like a broken router rule.
- **IPv4 only.** Virtual Servers and Port Forwarding are IPv4 NAT features.
  What a TP-Link router does with inbound IPv6 is not covered by its
  forwarding documentation and varies by model, so check yours.
- **Testing from inside.** Loopback is inconsistent. Test from a phone on
  mobile data.
- **Firmware.** Field names, and whether the page is called Virtual Servers or
  Port Forwarding, change between firmware versions on the same hardware.

## Sources

- [Port forwarding, three interface generations](https://www.tp-link.com/us/support/faq/1379/)
- [Virtual Servers on Wi-Fi routers](https://www.tp-link.com/us/support/faq/1106/)
- [Archer A7/C7 user guide, NAT forwarding](https://www.tp-link.com/us/user-guides/archer-a7&c7_v5/chapter-13-nat-forwarding)
- [Deco port forwarding](https://www.tp-link.com/us/support/faq/1797/)
- [Private WAN address, CGNAT, firewall](https://www.tp-link.com/us/support/faq/785/)
- [Address Reservation](https://www.tp-link.com/us/support/faq/182/)
- [Finding the router address](https://www.tp-link.com/us/support/faq/2392/)
- [Forgotten password and factory reset](https://www.tp-link.com/us/support/faq/426/)
