# Port forwarding on an ASUS router

RT-AX and RT-AC models on ASUSWRT, firmware 3.0.0.4.384.40000 or later.

> This opens a door into your own network and you are responsible for what
> comes through it. Read [the warnings](/forward) first if you have not.

## Log in

Connect by Ethernet or Wi-Fi, then open `http://www.asusrouter.com` or the
router's address. ASUS's own example is `192.168.50.1`.

Some models use `admin` / `admin`; others print the defaults on a label on the
back or bottom; a router on first boot, or after a reset, makes you create the
login instead.

If the password is unknown there is no recovery. ASUS says so plainly: the only
way back in is a factory reset, holding **RESET** for 5 to 10 seconds until the
power light flashes. That erases everything, including your internet settings.

## Give the board a fixed address

**Advanced Settings > LAN > DHCP Server**:

1. Note the IP pool range, for example `192.168.50.2` to `192.168.50.254`.
2. Set **Enable Manual Assignment** to **Yes**.
3. Under **Manually Assigned IP around the DHCP list**, pick the board from the
   MAC dropdown, or type its MAC in `12:34:56:AA:BC:DE` form.
4. Enter an address inside the pool, for example `192.168.50.75`. DNS is
   optional.
5. Click the `+`, then **Apply**.
6. Reconnect the board so it takes the new lease.

## Add the rule

**Advanced Settings > WAN > Virtual Server / Port Forwarding**:

1. Switch **Enable Port Forwarding** to **ON**. It is off by default, and this
   is the step people miss.
2. Click **Add profile**.
3. **Service Name**: `bbs`
4. **Protocol**: `TCP`
5. **External Port**: `6400`
6. **Internal IP Address**: the address you reserved
7. **Internal Port**: `6400`
8. **Source IP**: leave blank, or set one address to restrict who may connect.
9. **OK**, then **Apply**.

ASUS notes that Internal Port may be left blank, in which case traffic arrives
on the same port; that External Port accepts ranges with a colon (`300:500`),
lists with commas, or both; and that one external port can serve only one
device, so conflicting rules will not run.

Service Name is not documented as mandatory, but some builds refuse to save
without it and reusing a name can overwrite an existing rule. Fill it in with
something unique. That is field experience rather than ASUS documentation.

## The ASUS Router app and AiMesh

ASUS documents in-app port forwarding only for the older Lyra app
(**Settings > Port Forwarding > +**). There is no ASUS page giving the path in
the current ASUS Router app, so the web interface is the authoritative route.

On AiMesh, make every change on the AiMesh router, the one connected to the
modem. ASUS states that router settings can only be made there, not on nodes.
It makes no difference which unit the board is associated with.

## When it does not work

- **Double NAT.** ASUS states that port forwarding needs a public WAN address
  and will not work properly behind another router. If the WAN address starts
  `192.168.`, `10.` or `172.16`-`172.31`, put the ISP device into bridge or IP
  passthrough mode, or forward the port on both.
- **CGNAT.** ASUS names the range explicitly: `100.64.0.0` to
  `100.127.255.255`. No router setting fixes it.
- **IPv6.** ASUS states port forwarding is not supported for IPv6 and that
  there are no plans to support it. Inbound IPv6 is the **IPv6 Firewall**,
  switched on and given its own rules under **Firewall > General**.
- **Firmware.** Anything before 3.0.0.4.384.40000 uses a different page layout
  and a separate ASUS document. Some older models never got the newer one.
- **The board itself.** The rule only moves packets. The board has to be
  listening, which you can confirm from your own network first.

## Sources

- [Virtual Server / Port Forwarding, current firmware](https://www.asus.com/support/faq/1037906/)
- [Same feature, older firmware](https://www.asus.com/support/faq/114093/)
- [DHCP Server, manual assignment](https://www.asus.com/support/faq/1000906/)
- [Web interface access and defaults](https://www.asus.com/us/support/faq/1005263/)
- [Cannot log in, factory reset](https://www.asus.com/support/faq/1044653/)
- [AiMesh, settings on the router only](https://www.asus.com/support/faq/1035087/)
- [Lyra app, port forwarding](https://www.asus.com/support/faq/1036277/)
- [IPv6 Firewall](https://www.asus.com/support/faq/1013638/)
