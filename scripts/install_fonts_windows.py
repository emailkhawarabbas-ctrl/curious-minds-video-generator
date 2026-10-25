"""Install the bundled brand fonts for the current Windows user (no admin rights needed).

On Windows, Cairo finds fonts through DirectWrite, which only sees installed fonts, so the
fontconfig setup used on Linux/CI does not apply and text silently falls back to Arial.

    python scripts/install_fonts_windows.py            # install (copy + HKCU registry entry)
    python scripts/install_fonts_windows.py --remove   # undo
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"
FONTS = {"LilitaOne-Regular.ttf": "Lilita One (TrueType)", "LuckiestGuy-Regular.ttf": "Luckiest Guy (TrueType)",
         "PatrickHand-Regular.ttf": "Patrick Hand (TrueType)"}
REG_KEY = r"Software\Microsoft\Windows NT\CurrentVersion\Fonts"


def main() -> int:
    if os.name != "nt":
        print("Not Windows: nothing to do (fontconfig picks up assets/fonts automatically).")
        return 0
    import winreg
    dest = Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Windows" / "Fonts"
    dest.mkdir(parents=True, exist_ok=True)
    remove = "--remove" in sys.argv
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, REG_KEY) as key:
        for fname, name in FONTS.items():
            target = dest / fname
            if remove:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
                target.unlink(missing_ok=True)
                print("removed", name)
            else:
                shutil.copy2(FONT_DIR / fname, target)
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(target))
                print("installed", name, "->", target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
