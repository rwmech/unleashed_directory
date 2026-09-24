<!-- Every fact on this page was checked against the firmware and the installer, not written from memory: the partition table (unchanged since 0.17.0), the parts the manifest writes (FLASH_PARTS in server.py), the name the board gives the installer (src/main.cpp, since 0.22.1), how ESP Web Tools offers an update and what the Update button's manifest makes it do (the vendored install dialog, and firmware_manifest in server.py), what the backup zip may carry (ziparc.cpp) and how the card's screens are refreshed (sd.cpp, since 0.22.0). Re-check them when any of those change. -->
# Upgrade a board

A board that already runs µnleashed takes a new version from [the installer](/install), over the same USB cable it was installed with, and keeps its accounts. About five minutes, most of it waiting.

On [the board list](/), a µnleashed board older than the newest release here has a small up arrow on the end of its software badge, the one with its version in it, and pressing the arrow brings you to this page.

## Back up first

The update does not write where your accounts are kept, but a copy costs a minute and nothing else can put them back. Open [the backup window](/setup#backup) and download the zip. It holds the settings, the accounts and the screens.

It does not hold the mail or the information pages. The forums and the file areas are on the SD card, which any computer can copy.

## Update

1. **Plug the board in** with a cable that carries data, open [the installer](/install) in Chrome or Edge, choose your board in the card, press **Update my board** and pick the port. On the Waveshare S3, hold BOOT and tap RESET before pressing the button, and press RESET when it has finished. The installer page says [why the S3 needs that](/install#on-the-waveshare-s3).
2. **Press Update unleashed BBS, then Install.** A board running 0.22.1 or later usually tells the installer its name and version, and the page shows both above the button. It may not, if the board is still starting up when the page asks, and that makes no difference here. It does not ask about erasing and it does not erase.
3. **Writing** takes about two minutes. Keep the tab in view while it works.
4. **The board starts on the new version**, on the Wi-Fi network it already knew.

::: next
[Go to the installer](/install)
:::

If the board already runs the version on offer, there is no update to press, and nothing **Update my board** offers can erase it.

### If you pressed Install on a new board instead

That works too. A board the page recognises is offered **Update unleashed BBS** and not asked anything. One it does not recognise is offered **Install or update unleashed BBS**, which does the same thing as long as you leave the box on the next screen unticked. That screen looks like this:

> [!NOTE]
> **Start fresh?** Updating a board you already run? Leave this unticked: your accounts, settings, mail and forums are kept. Tick it only for a brand-new board, or to wipe this one and start over. `[ ]` **Erase everything first**

Leave it unticked and press **Next**. If the page shows **Erase User Data**, because the board already runs the version on offer, leave it alone: it wipes the whole chip.

## What it writes, and what it leaves

The update writes the firmware and the screens, and nothing else.

- **Kept:** the accounts, the settings (Wi-Fi included), the mail, the information pages and the directory listing, all on a part of the flash the update does not write. The caller log has a part of its own and is kept too. So is everything on the SD card: the forums, the file areas and your screens.
- **Back to stock:** the screens in the board's own flash. A screen you changed there, through a backup, goes back to the one that ships with the new version.
- **Screens on the SD card** still play in place of the stock ones. One you edited on the card is yours and is never touched. The stock copies the board put on the card itself follow the new version the next time it starts.

> [!NOTE]
> A card that was in the board before 0.22.0 holds copies of the stock screens the board has no record of putting there, so it leaves them alone, and they keep playing the old screens. Delete the ones you did not change from the `screens` folder on the card, and the next time the board starts it puts the new ones in their place.

## A board older than 0.22.1

Versions before 0.22.1 do not tell the installer who they are, so the page never recognises the board.

- **From 0.17.0 on, use Update my board.** The flash has been laid out the same way since 0.17.0, so the firmware and the screens are rewritten and the accounts stay. Through **Install on a new board** it is the same, with **Erase everything first** left unticked.
- **Before 0.17.0, the erase cannot be avoided.** The flash was laid out differently then, and the new layout does not fit over the old one. Use **Install on a new board** and tick **Erase everything first**. The erase takes the accounts, the settings and the mail with it. Back up first: afterwards the backup is the only copy.
- **Either way, the board needs your Wi-Fi at the end.** Before 0.22.1 the network was built into the firmware, and a release carries none, so the board comes up without one. When the writing is done, press **Next**, then **Connect to Wi-Fi** if the page has not opened the Wi-Fi step by itself. Choose the network and type the password, as on a first install.

## If something goes wrong

- **The board is not back on your network.** A board built from source with its network in `secrets.h` has the same gap as an old one: the release does not carry it. Plug the board in, open [the installer](/install), pick the port and use **Connect to Wi-Fi** or **Change Wi-Fi**, as in [Changing the Wi-Fi later](/install#changing-the-wi-fi-later). Nothing else on the board changes.
- **The update stopped part way**, a cable pulled or the tab closed. Run it again. The chip's own loader is in read-only memory and nothing the page writes can reach it, so a board can always be written again over USB. **Update my board** works whether or not the page still recognises the board, and never erases.
- **Last of all**, **Install on a new board** with **Erase everything first** ticked. That puts the chip back to nothing and takes the accounts with it, so try [the resets on the installer page](/install#if-something-goes-wrong-reset-rather-than-reflash) first.
