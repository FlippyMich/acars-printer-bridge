"""`python -m acars_bridge` opens the app; with arguments it acts as the CLI."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["ui"]))
