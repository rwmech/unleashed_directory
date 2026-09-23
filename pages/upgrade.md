<!-- Every fact on this page was checked against the firmware and the installer, not written from memory: the partition table (unchanged since 0.17.0), the parts the manifest writes (FLASH_PARTS in server.py), the name the board gives the installer (src/main.cpp, since 0.22.1), how ESP Web Tools offers an update (the vendored install dialog), what the backup zip may carry (ziparc.cpp) and how the card's screens are refreshed (sd.cpp, since 0.22.0). Re-check them when any of those change. -->
# Upgrade a board

A board that already runs µnleashed takes a new version from [the installer](/install), over the same USB cable it was installed with, and keeps its accounts. About five minutes, most of it waiting.

## Back up first

The update does not write where your accounts are kept, but a copy costs a minute and nothing else can put them back. Open [the backup window](/setup#backup) and download the zip. It holds the settings, the accounts and the screens.

It does not hold the mail or the information pages. The forums and the file areas are on the SD card, which any computer can copy.

## Update

1. **Plug the board in** with a cable that carries data, open [the installer](/install) in Chrome or Edge, press **Install on my board** and pick the port.
2. **The page recognises the board.** A board running 0.22.1 or later tells the installer its name and version, and the page shows both and offers **Update unleashed BBS**. Press it. It does not ask about erasing and it does not erase.
3. **Writing** takes about two minutes. Keep the tab in view while it works.
4. **The board starts on the new version**, on the Wi-Fi network it already knew.

If the board already runs the version on offer, there is no update to press. Leave **Erase User Data** alone: it wipes the whole chip.

## What it writes, and what it leaves

The update writes the firmware and the screens, and nothing else.

- **Kept:** the accounts, the settings (Wi-Fi included), the mail, the information pages and the directory listing, all on a part of the flash the update does not write. The caller log has a part of its own and is kept too. So is everything on the SD card: the forums, the file areas and your screens.
- **Back to stock:** the screens in the board's own flash. A screen you changed there, through a backup, goes back to the one that ships with the new version.
- **Screens on the SD card** still play in place of the stock ones. One you edited on the card is yours and is never touched. The stock copies the board put on the card itself follow the new version the next time it starts.

> [!NOTE]
> A card that was in the board before 0.22.0 holds copies of the stock screens the board has no record of putting there, so it leaves them alone, and they keep playing the old screens. Delete the ones you did not change from the `screens` folder on the card, and the next time the board starts it puts the new ones in their place.

## A board older than 0.22.1

Versions before 0.22.1 do not tell the installer who they are, so the page does not recognise the board. It offers **Install unleashed BBS** and then asks whether to erase.

- **From 0.17.0 on, leave Erase device unticked.** The flash has been laid out the same way since 0.17.0, so the firmware and the screens are rewritten and the accounts stay.
- **Before 0.17.0, the erase cannot be avoided.** The flash was laid out differently then, and the new layout does not fit over the old one. The erase takes the accounts, the settings and the mail with it. Back up first: afterwards the backup is the only copy.
- **Either way, the page asks for your Wi-Fi at the end.** Before 0.22.1 the network was built into the firmware, and a release carries none, so the board comes up without one. Choose the network and type the password, as on a first install.

## If something goes wrong

- **The board is not back on your network.** A board built from source with its network in `secrets.h` has the same gap as an old one: the release does not carry it. Plug the board in, open [the installer](/install), pick the port and use **Connect to Wi-Fi** or **Change Wi-Fi**, as in [Changing the Wi-Fi later](/install#changing-the-wi-fi-later). Nothing else on the board changes.
- **The update stopped part way**, a cable pulled or the tab closed. Run it again. The chip's own loader is in read-only memory and nothing the page writes can reach it, so a board can always be written again over USB. If the page no longer recognises the board, choose **Install unleashed BBS** and leave **Erase device** unticked.
- **Last of all**, install with **Erase device** ticked. That puts the chip back to nothing and takes the accounts with it; [the installer's own page](/install#if-something-goes-wrong-reset-rather-than-reflash) has what to try first.
