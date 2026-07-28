ACARS PRINTER BRIDGE 1.1.0
Real paper ACARS for the Fenix A32X in Microsoft Flight Simulator 2024 / 2020
===============================================================================

WHAT IT DOES
    Prints the ACARS and TELEX messages of the Fenix A319/A320/A321 on a cheap
    Bluetooth thermal printer (58 mm), so you can tear off your clearance and
    clip it to the yoke.

WHAT YOU NEED
    - A Bluetooth thermal printer: X6/X6h, GB01/GB02, MX05/MX06, Phomemo-style
      or a generic ESC/POS one.
    - Fenix A32X v2.2.0.351 or newer (that build added physical ACARS printer
      support) with MSFS 2024 or 2020.
    - Windows 10 or 11 with Bluetooth.

HOW TO INSTALL
    1. Switch the thermal printer on, with paper loaded, and make sure no phone
       app is connected to it.
    2. Run APBinstaller.exe and follow the five steps. It finds the printer,
       prints a test page, installs the app and sets it to start with Windows.
    3. In the aircraft, once: EFB -> Settings -> printer -> "ACARS Printer",
       then enable auto-print for ACARS and/or TELEX. Restart MSFS if it was
       already running.

    From then on: switch the printer on, fly. The app starts and stops with the
    simulator by itself.

WINDOWS WARNING
    The executables are not code-signed (certificates cost money, this tool is
    free), so SmartScreen shows "Windows protected your PC" the first time.
    Click "More info" -> "Run anyway".

    The whole project is open source - read it or build it yourself:
    https://github.com/FlippyMich/acars-printer-bridge

IF SOMETHING GOES WRONG
    - Printer not found? Power-cycle it: these printers only advertise for a few
      minutes after being switched on. Close the vendor app on your phone. If you
      ever paired the printer in Windows, remove it from Settings > Bluetooth.
    - Print too faint or smudged? Use CALIBRATE DARKNESS in the app.
    - The EFB does not list "ACARS Printer"? Restart the simulator.
    - Logs: %LOCALAPPDATA%\ACARS Printer Bridge\logs\

HELP AND FEEDBACK
    Discord: https://discord.gg/bFY5wCf6CK
    GitHub:  https://github.com/FlippyMich/acars-printer-bridge

LICENSE
    MIT. Not affiliated with Fenix Simulations or Microsoft.
