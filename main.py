#!/usr/bin/env python3
"""
InstaSum-Image — entry point.

Usage:
    python main.py
"""

import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def main():
    try:
        from app.gui import App
    except ImportError as exc:
        print(f"[ERROR] Missing dependency: {exc}")
        print("Run:  pip install -r requirements.txt")
        sys.exit(1)

    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
