"""PyInstaller entry point for the Windows build.

The `omnihear` package lives in ../src, which isn't on sys.path when
PyInstaller analyzes this file directly, so add it before importing.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from omnihear.__main__ import main

if __name__ == "__main__":
    main()
