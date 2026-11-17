#!/usr/bin/env python3
"""
tray_main.py — Główny punkt wejścia aplikacji uruchamianej w tle (System Tray).
Działa bez konsoli, ukrywa się w zasobniku systemowym Windows.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Jeśli aplikacja jest skompilowana przez PyInstaller, folderem bazowym
# jest folder z plikiem .exe, a nie tymczasowy katalog rozpakowania _MEIxxxxxx
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

CONFIG_PATH = BASE_DIR / "config.json"


def main() -> None:
    if not CONFIG_PATH.exists():
        # Jeśli brak configu w folderze exe, spróbuj znaleźć obok
        fallback = Path("config.json").resolve()
        if fallback.exists():
            target_config = fallback
        else:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0,
                f"Nie znaleziono pliku config.json w:\n{CONFIG_PATH}\n\nUruchom najpierw konfigurację lub skopiuj plik config.json.",
                "VS200 Bridge - Błąd",
                0x10,  # MB_ICONERROR
            )
            sys.exit(1)
    else:
        target_config = CONFIG_PATH

    with open(target_config, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    from src.tray import TrayApp

    app = TrayApp(cfg, target_config)
    app.run()


if __name__ == "__main__":
    main()
