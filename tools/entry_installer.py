"""PyInstaller entry point for APBinstaller.exe (the setup wizard)."""

import multiprocessing
import sys

from acars_bridge import config
from acars_bridge.ui.wizard import launch

if __name__ == "__main__":
    multiprocessing.freeze_support()
    launch(config.load())
    sys.exit(0)
