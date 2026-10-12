"""Frozen-app entry point for Bike Box (PyInstaller).

PyInstaller freezes this script; it just hands control to the normal CLI/GUI
entry so the same code path runs frozen or from source.
"""
import multiprocessing
import sys

from bikebox.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
