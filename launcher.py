"""Production/dev launcher for Angelique."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch Angelique")
    parser.add_argument("--gui", action="store_true", help="Launch the desktop GUI")
    parser.add_argument("--headless", action="store_true", help="Validate imports without opening the GUI")
    args = parser.parse_args()
    os.environ["ANGELIQUE_LAUNCHED"] = "1"
    if args.headless:
        import brain.cognitive_loop  # noqa: F401
        from skills.trading_skill import service  # noqa: F401
        return 0
    # Default to GUI because this launcher is the documented desktop entrypoint.
    from gui.angelique_desktop import main as gui_main
    gui_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
