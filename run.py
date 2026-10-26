"""Start DocFiller from a source checkout: ``python run.py``.

Also serves as the PyInstaller entry point, which is why it puts ``src`` on the
import path itself instead of relying on how it was invoked.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from docfiller.ui.app import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
