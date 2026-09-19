# Port forwarding on eero and Google Nest Wifi

The two popular app-only mesh systems. Both can do it; neither has a web page
to do it from.

> This opens a door into your own network and you are responsible for what
> comes through it. Read [the warnings](/forward) first if you have not.

## eero

On eero the forward lives inside a device's address reservation, so the
reservation comes first and there is no separate forwarding screen.

1. Open the eero app and tap **Settings**, bottom right.
2. Tap **Advanced networking**.
3. Tap **Reservations & port forwarding**.
4. Add a reservation under **IPv4 Reservations & Port Forwards**.
5. Pick the board from the connected devices, or add it, and set its nickname,
   MAC address and address.
6. Tap **Open a port**, then **Save**.
7. Enter `6400`, give it a nickname, choose **TCP**.
8. Tap **Save**, top right.

eero does not show separate internal and external port boxes, so a 6400 to 6400
forward is one entry. To remove it, return to the same screen, tap the board,
tap the port, tap **Delete port forward**.

Older app builds called that menu **Network settings** rather than **Advanced
networking**, and eero's own pages are inconsistent about it. Trust the label
on your screen.

### Subscription

Port forwarding and reservations are free. Of the advanced settings only
Dynamic DNS needs eero Plus. eero's article never mentions a subscription in
the forwarding flow, and its feature list tags only Dynamic DNS, which is the
basis for saying so.

### Bridge mode

An eero in bridge mode cannot forward ports at all. eero lists reservations and
port forwarding among the features lost. Bridge the ISP box instead, never the
eero.

Once a forward exists, loopback works on eeroOS 3.3.0 and later, so you can
test your public address from inside the house.

## Google Nest Wifi and Google Wifi

Google requires a reserved address before you can forward to a device, and says
so explicitly.

### Reserve the address

**Google Home app > Home > Wifi > Network settings > Advanced Networking >
DHCP IP reservations > Add IP reservations**, pick the board, type the address,
**Save**. The board may need to reconnect before it takes it.

### Add the rule

1. Open the Google Home app.
2. Tap **Home > Wifi > Settings > Advanced Networking**.
3. Tap **Port management > Add**.
4. Choose the **IPv4** tab.
5. Select the board.
6. Internal port `6400`, external port `6400`. Ranges are allowed but internal
   and external ranges must match; only single ports may differ.
7. Choose **TCP**.
8. **Save**.

Google's own two articles disagree about step 2, one saying **Settings** and
one **Network settings**. Both reach **Advanced Networking**.

### Old app, new app, and the hardware

- The Google Wifi app is read-only now. Changes happen in the Google Home app,
  and migrating is not reversible.
- Nest Wifi Pro is Google Home only and will not mesh with Nest Wifi or Google
  Wifi points.
- The port management screen is the same across Google Wifi, Nest Wifi and Nest
  Wifi Pro.
- UPnP is on by default, so plenty of devices open their own ports without any
  of this. That is worth knowing whether or not you wanted it.
- Loopback works, so a forwarded service is reachable by public address from
  inside.

## When it does not work

- **Double NAT.** If the mesh sits behind an ISP modem or router, your forward
  lands on the mesh's private WAN address and nothing from outside reaches it.
  Check the WAN address in the app: `192.168.` or `10.` means a second router.
  Bridge the ISP box. Do not bridge the mesh: eero loses forwarding entirely,
  and a Google mesh with more than one unit cannot be bridged at all.
- **CGNAT.** Neither vendor publishes anything on this. If the WAN address is
  in `100.64.0.0/10`, or does not match an external "what is my IP", the ISP is
  sharing one address between many customers and no setting will help.
- **IPv4 and IPv6 are separate.** An IPv4 forward does nothing for IPv6. On
  eero that is a rule under **IPv6 Firewall Rules**; on Google it is the
  **IPv6** tab, and Google calls it port opening rather than forwarding because
  there is no translation: the port is the same at both ends and the board is
  reached at its own global address, which can change when the ISP's prefix
  changes.

## Sources

- [eero, how do I set up port forwarding](https://eero.com/support/articles/how-do-i-set-up-port-forwarding)
- [eero, advanced networking settings](https://eero.com/support/articles/what-are-the-advanced-networking-settings)
- [eero, features lost in bridge mode](https://eero.com/support/articles/what-features-do-i-lose-if-i-put-my-eeros-in-bridge-mode)
- [eero, hairpin NAT](https://eero.com/support/articles/what-is-hairpin-nat)
- [Google, port forwarding or port opening](https://support.google.com/googlehome/answer/6274503)
- [Google, DHCP IP reservation](https://support.google.com/googlehome/answer/6274660)
- [Google, fix double NAT](https://support.google.com/googlehome/answer/6277579)
- [Google, migrate to the Home app](https://support.google.com/googlehome/answer/9547597)
- [RFC 6598, shared address space](https://www.rfc-editor.org/rfc/rfc6598)
