"""Allow ``python -m pymart``."""
import sys

from pymart.cli import main

if __name__ == "__main__":
    sys.exit(main())
