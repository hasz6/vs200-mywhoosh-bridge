"""
tray.py — Obsługa aplikacji w zasobniku systemowym Windows (System Tray).
Wykorzystuje pystray oraz Pillow do dynamicznych ikonek statusu.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import winreg
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw
import pystray

from .ble_client import VS200Bridge

REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "VS200MyWhooshBridge"


def _create_icon_image(color: str) -> Image.Image:
    """Tworzy okrągłą ikonkę statusu o zadanym kolorze (64x64)."""
    image = Image.new("RGBA", (64, 64), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # Rysuj koło z delikatnym obrysem
    draw.ellipse((4, 4, 60, 60), fill=color, outline="#222222", width=3)
    
    # Dodaj wewnętrzny mały refleks
    draw.ellipse((16, 16, 32, 32), fill="#ffffff", outline=None)
    return image


class TrayApp:
    def __init__(self, cfg: dict[str, Any], config_path: Path):
        self.cfg = cfg
        self.config_path = config_path
        self.current_state = "initializing"
        self.status_text = "Inicjalizacja..."
        self.bridge: VS200Bridge | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.worker_thread: threading.Thread | None = None
        self.icon: pystray.Icon | None = None

        # Ikonki stanów
        self.icons = {
            "connected": _create_icon_image("#28a745"),    # Zielony
            "connecting": _create_icon_image("#17a2b8"),   # Niebieski
            "sleeping": _create_icon_image("#ffc107"),     # Żółty
            "disconnected": _create_icon_image("#dc3545"), # Czerwony
            "default": _create_icon_image("#6c757d"),      # Szary
        }

    # -------------------------------------------------------------
    # Rejestr Windows (Autostart)
    # -------------------------------------------------------------

    def is_autostart_enabled(self) -> bool:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_READ) as key:
                winreg.QueryValueEx(key, APP_NAME)
                return True
        except FileNotFoundError:
            return False
        except Exception:
            return False

    def toggle_autostart(self) -> None:
        enabled = self.is_autostart_enabled()
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_WRITE) as key:
                if enabled:
                    winreg.DeleteValue(key, APP_NAME)
                else:
                    # Ścieżka do aktualnego pliku wykonywalnego
                    exe_path = sys.executable if getattr(sys, "frozen", False) else f'"{sys.executable}" "{Path(__file__).resolve().parent.parent / "tray_main.py"}"'
                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, exe_path)
        except Exception as e:
            print(f"Błąd zmiany autostartu: {e}")

    # -------------------------------------------------------------
    # Status callback
    # -------------------------------------------------------------

    def on_ble_status(self, state: str, message: str) -> None:
        self.current_state = state
        self.status_text = message
        if self.icon:
            img = self.icons.get(state, self.icons["default"])
            self.icon.icon = img
            self.icon.title = f"VS200: {message}"

    # -------------------------------------------------------------
    # Pętla wątku BLE
    # -------------------------------------------------------------

    def _run_ble_loop(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        self.bridge = VS200Bridge(self.cfg, status_callback=self.on_ble_status)

        try:
            self.loop.run_until_complete(self.bridge.run_forever())
        except Exception as e:
            self.on_ble_status("disconnected", f"Błąd: {e}")
        finally:
            self.loop.close()

    # -------------------------------------------------------------
    # Menu Tray
    # -------------------------------------------------------------

    def _open_config(self) -> None:
        try:
            os.startfile(str(self.config_path))
        except Exception:
            pass

    def _exit_app(self) -> None:
        if self.bridge:
            self.bridge.stop()
        if self.icon:
            self.icon.stop()

    def run(self) -> None:
        # Start wątku BLE
        self.worker_thread = threading.Thread(target=self._run_ble_loop, daemon=True)
        self.worker_thread.start()

        def make_menu():
            return pystray.Menu(
                pystray.MenuItem(
                    lambda text: f"Status: {self.status_text}",
                    None,
                    enabled=False,
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    "Autostart z Windows",
                    lambda: self.toggle_autostart(),
                    checked=lambda item: self.is_autostart_enabled(),
                ),
                pystray.MenuItem(
                    "Otwórz config.json",
                    lambda: self._open_config(),
                ),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem(
                    "Zakończ",
                    lambda: self._exit_app(),
                ),
            )

        self.icon = pystray.Icon(
            name="VS200Bridge",
            icon=self.icons["sleeping"],
            title="VS200 MyWhoosh Bridge",
            menu=make_menu(),
        )

        self.icon.run()
