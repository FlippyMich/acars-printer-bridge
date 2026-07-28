# flightsim.to listing — copy/paste source

Written in English on purpose: that is what the flightsim.to audience reads.

---

## Title

```
ACARS Printer Bridge — Real Paper ACARS for the Fenix A32X
```

## Short description (card text)

```
Prints your Fenix A32X ACARS and TELEX messages on a cheap Bluetooth thermal printer. Automatic printer detection, one-click setup, starts with MSFS on its own.
```

## Category / tags

- Category: **Tools & Utilities** (or Liveries→no; use Utilities/Miscellaneous)
- Tags: `fenix` `a320` `acars` `printer` `thermal printer` `bluetooth` `utility` `tool` `msfs2024` `immersion` `hardware` `cockpit`

## Compatibility

- Microsoft Flight Simulator **2024** and **2020**
- Fenix A319 / A320 / A321, **v2.2.0.351 or newer**
- Windows 10 / 11

---

## Full description

### Tear off your clearance. For real.

Your first officer reads the ACARS message off the MCDU. You press PRINT. The printer next to
your throttle whirrs, and a strip of paper comes out with the METAR on it — the one you just
requested in the sim, on actual paper, that you can tear off and clip to your yoke.

That is what this does. It connects the Fenix A32X's ACARS printer to one of those €15
Bluetooth thermal printers you find everywhere, and then gets out of your way.

### What you need

- A **Bluetooth thermal printer** (58 mm paper). The X6/X6h class works, so do GB01/GB02,
  MX05/MX06, Phomemo-style ones and generic ESC/POS printers — see the list below.
- **Fenix A32X v2.2.0.351 or newer** — that is the build where Fenix added support for a
  physical ACARS printer.
- Windows 10 or 11 with Bluetooth.

No Python, no command line, no drivers to hunt for. The download is a single installer.

### Why a bridge is needed at all

If you already tried plugging one of these printers into Windows, you know it does not work.
Three separate walls are in the way:

1. **The Fenix only prints to Windows printers** — the EFB list is the Windows printer list.
2. **Your printer is not a Windows printer.** It appears under Bluetooth devices but never
   really "connects", because it exposes no printer profile and has no driver. It is a
   Bluetooth Low Energy device that takes commands on a GATT characteristic.
3. **Most of them do not even speak ESC/POS.** The X6 class has no built-in fonts at all: it
   only accepts images, one 384-dot row at a time, inside binary packets with a checksum.

This tool knocks all three down: it creates a virtual Windows printer the EFB can see, catches
the print job, draws the message as a bitmap and speaks the printer's own protocol over
Bluetooth.

### Installation

1. Run **APBinstaller.exe**.
2. It asks you to switch the printer on, then finds it by itself and prints a test page so you
   can set how dark you want it.
3. It creates the Windows printer, the shortcuts and the startup entry, and launches the app.

Then, once, inside the aircraft: **EFB → Settings → printer → "ACARS Printer"**, and turn on
auto-print for ACARS and/or TELEX.

From that moment on you only switch the printer on. The app wakes up with MSFS and releases the
printer when you quit, so your phone can use it again.

### Features

- **Automatic printer detection** — scans Bluetooth and shows only the devices that really are
  thermal printers, best match first. Your earbuds, TV and phone are filtered out.
- **Two protocols, picked automatically** — cat-printer raster and classic ESC/POS.
- **Darkness calibration** — prints the same line at several heat levels so you can pick the
  crispest one. No more guessing with cheap paper.
- **Follows the simulator** — online when MSFS starts, offline when it closes.
- **Nothing is lost** — if the bridge is not running, Windows keeps the job queued and prints it
  when it comes up. Every printout is also saved as text.
- **Print anything else** — drop a text file in the spool folder for your SimBrief OFP,
  clearances or checklists.
- **Cockpit-style panel** — status lamps, live log, preflight checklist, print settings.
- **Reconfigure any time** — changed printer? One button.
- Free and **open source** (MIT).

### Supported printers

| Family | Status |
|---|---|
| X6, X6h, GB01, GB02, GT01, MX05, MX06, YHK, Phomemo-style and clones | **Verified on X6h** |
| Generic BLE ESC/POS: Goojprt, Zjiang, XPrinter, MTP, RPP, ISSC/Microchip modules | Supported |
| Classic Bluetooth (SPP) printers on a COM port | Supported |

80 mm paper works too — one setting.

If your printer is not recognised automatically you can still pick it from the full device list,
and I would like to hear about it so it can be added.

### A note on the Windows warning

The app is not code-signed yet — a certificate costs real money and this is free — so
SmartScreen will say "Windows protected your PC" the first time. Click **More info → Run
anyway**.

You do not have to take my word for it: **the whole thing is open source**. Read the code,
or build the executable yourself and compare it with the one you downloaded.

GitHub: https://github.com/FlippyMich/acars-printer-bridge

### Support and feedback

Questions, a printer model that needs adding, or a photo of your printout — come say hi:

**Discord: https://discord.gg/bFY5wCf6CK**

### Credits

Protocol work verified against the open-source projects rbaron/catprinter and
NaitLee/Cat-Printer. Bluetooth via bleak. Not affiliated with Fenix Simulations or Microsoft.

---

## Version / changelog field

```
1.1.0 - First public release.
Automatic thermal printer detection, setup wizard, cat-printer and ESC/POS support,
darkness calibration, follows MSFS automatically, print any text file from the spool folder.
```
