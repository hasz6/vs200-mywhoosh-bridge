"""
input_emulator.py — Niskopoziomowy injektor klawiszy Windows (ScanCodes).

Używa ctypes + user32.SendInput z flagą KEYEVENTF_SCANCODE,
co jest wymagane przez silnik Unreal Engine (MyWhoosh), który
ignoruje wysokopoziomowe WM_KEYDOWN z pyautogui.

WAŻNE: Skrypt musi być uruchomiony jako Administrator (Run as Admin),
       bo MyWhoosh działa z podwyższonymi uprawnieniami (UIPI).
"""

from __future__ import annotations

import asyncio
import ctypes
import ctypes.wintypes
import logging
import sys

logger = logging.getLogger(__name__)

# --- Win32 stałe ---

user32 = ctypes.WinDLL("user32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

INPUT_KEYBOARD = 1
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_KEYUP = 0x0002

# Mapowanie nazw klawiszy → scan code (PS/2 Set 1) + virtual key
_KEY_INFO = {
    "i": {"scan": 0x17, "vk": 0x49},
    "k": {"scan": 0x25, "vk": 0x4B},
}


# --- Win32 struktury z prawidłowym sizeof ---
# Wszystkie trzy typy muszą być w unii, żeby sizeof(INPUT) == 40 na x64
# (Windows sprawdza cbSize i ignoruje zdarzenia przy złym rozmiarze)

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.wintypes.LONG),
        ("dy", ctypes.wintypes.LONG),
        ("mouseData", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.wintypes.WORD),
        ("wScan", ctypes.wintypes.WORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.wintypes.DWORD),
        ("wParamL", ctypes.wintypes.WORD),
        ("wParamH", ctypes.wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _anonymous_ = ("_input",)
    _fields_ = [
        ("type", ctypes.wintypes.DWORD),
        ("_input", _INPUT_UNION),
    ]


def _send_input(*inputs: INPUT) -> int:
    """Wysyła zdarzenia wejścia. Zwraca liczbę wstawionych zdarzeń (0 = błąd)."""
    n = len(inputs)
    arr = (INPUT * n)(*inputs)
    result = user32.SendInput(n, arr, ctypes.sizeof(INPUT))
    if result == 0:
        err = ctypes.get_last_error()
        logger.error(
            "SendInput zwrócił 0 — błąd Win32: %d (0x%08X). "
            "Prawdopodobnie brak uprawnień administratora (UIPI).",
            err, err,
        )
    return result


# --- Sprawdzanie uprawnień administratora ---

def is_admin() -> bool:
    """Sprawdza, czy proces działa z uprawnieniami administratora."""
    try:
        return bool(shell32.IsUserAnAdmin())
    except Exception:
        return False


def warn_if_not_admin() -> None:
    """Wypisuje ostrzeżenie, jeśli skrypt nie działa jako administrator."""
    if not is_admin():
        logger.warning(
            "⚠ Skrypt NIE działa jako Administrator! "
            "MyWhoosh (Unreal Engine) działa z podwyższonymi uprawnieniami — "
            "SendInput nie może wstrzyknąć klawiszy do procesów o wyższym poziomie "
            "integralności (Windows UIPI). "
            "Uruchom CMD/PowerShell jako Administrator i spróbuj ponownie."
        )
        return
    logger.info("✓ Skrypt działa z uprawnieniami administratora.")


# --- Sprawdzanie aktywnego okna ---

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)


def _get_foreground_window_title() -> str:
    """Zwraca tytuł aktualnie aktywnego okna."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""
    length = user32.GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def find_mywhoosh_window() -> int | None:
    """Szuka okna MyWhoosh wśród wszystkich okien. Zwraca HWND lub None."""
    result: list[int] = []

    @WNDENUMPROC
    def _enum_callback(hwnd: int, _lparam: int) -> bool:
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
            if "mywhoosh" in title.lower():
                result.append(hwnd)
        return True  # kontynuuj enumerację

    user32.EnumWindows(_enum_callback, 0)
    return result[0] if result else None


def is_target_window_active(target_title: str) -> bool:
    """Sprawdza, czy okno o podanym tytule jest na pierwszym planie."""
    current = _get_foreground_window_title()
    if not current:
        return False
    # Elastyczne dopasowanie — szukamy podciągu
    return target_title.lower() in current.lower()


# --- KeyInjector ---

class KeyInjector:
    """Emuluje naciśnięcia klawiszy przez SendInput z ScanCodes.

    Wysyła zarówno wVk (Virtual Key) jak i wScan (Scan Code) jednocześnie,
    co maksymalizuje kompatybilność — Unreal Engine czyta scan codes,
    inne aplikacje czytają VK.
    """

    def __init__(
        self,
        check_window: bool = True,
        target_window_title: str = "MyWhoosh",
    ):
        self.check_window = check_window
        self.target_window_title = target_window_title
        self._admin_checked = False

    def _ensure_admin_check(self) -> None:
        if not self._admin_checked:
            warn_if_not_admin()
            self._admin_checked = True

    def _make_key_down(self, scan_code: int, vk: int = 0) -> INPUT:
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.ki.wVk = vk
        inp.ki.wScan = scan_code
        inp.ki.dwFlags = KEYEVENTF_SCANCODE
        return inp

    def _make_key_up(self, scan_code: int, vk: int = 0) -> INPUT:
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.ki.wVk = vk
        inp.ki.wScan = scan_code
        inp.ki.dwFlags = KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP
        return inp

    async def tap_key(
        self,
        scan_code: int,
        duration_ms: int = 50,
        key_name: str = "",
    ) -> bool:
        """Wysyła KeyDown → czeka duration_ms → KeyUp.

        Zwraca True, jeśli klawisz został wysłany, False, jeśli pominięto
        (np. aktywne jest inne okno niż MyWhoosh).
        """
        self._ensure_admin_check()

        if self.check_window:
            fg_title = _get_foreground_window_title()
            if not self.target_window_title.lower() in fg_title.lower():
                logger.debug(
                    "Pominięto wysłanie klawisza — aktywne okno: '%s' (oczekiwane: '%s')",
                    fg_title, self.target_window_title,
                )
                return False

        # Spróbuj dopasować VK z tabeli
        vk = 0
        if key_name and key_name.lower() in _KEY_INFO:
            vk = _KEY_INFO[key_name.lower()]["vk"]

        down = self._make_key_down(scan_code, vk)
        up = self._make_key_up(scan_code, vk)

        result_down = _send_input(down)
        await asyncio.sleep(duration_ms / 1000.0)
        result_up = _send_input(up)

        if result_down > 0 and result_up > 0:
            logger.debug(
                "Wysłano ScanCode 0x%02X / VK 0x%02X (hold %d ms) → OK",
                scan_code, vk, duration_ms,
            )
        return result_down > 0

    async def test_keys(self) -> None:
        """Tryb testowy — wysyła 'i' i 'k' z 2-sekundowym odstępem.

        Służy do weryfikacji, czy input injection działa.
        Otwórz Notatnik i obserwuj, czy pojawiają się litery.
        """
        self._ensure_admin_check()

        print("\n[TEST] Za 3 sekundy wyślę klawisz 'I' (shift down)…")
        print("       Otwórz Notatnik i kliknij w pole tekstowe!\n")
        await asyncio.sleep(3.0)

        for key_name, info in _KEY_INFO.items():
            scan = info["scan"]
            vk = info["vk"]
            print(f"  Wysyłam '{key_name.upper()}' (ScanCode=0x{scan:02X}, VK=0x{vk:02X})…")
            down = self._make_key_down(scan, vk)
            up = self._make_key_up(scan, vk)
            r1 = _send_input(down)
            await asyncio.sleep(0.06)
            r2 = _send_input(up)
            status = "OK" if r1 > 0 and r2 > 0 else f"BŁĄD (SendInput → {r1}/{r2})"
            print(f"    → {status}")
            await asyncio.sleep(2.0)

        print("\n[TEST] Zakończono. Czy w Notatniku pojawiły się litery 'i' i 'k'?")
        print("       Jeśli nie — uruchom skrypt jako Administrator (Run as Admin).")
