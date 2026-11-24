#!/usr/bin/env python3
"""
main.py — Punkt wejścia VS200-MyWhoosh Bridge.

Użycie:
    python main.py --discover     Skanuje urządzenia BLE, zapisuje MAC do config.json
    python main.py --calibrate    Łączy z VS200, kalibruje przyciski [+]/[-]
    python main.py --run          Uruchamia bridge: nasłuch BLE → emulacja klawiszy
    python main.py --battery      Sprawdza aktualny poziom baterii kontrolera VS200
    python main.py --test-keys    Testuje wstrzykiwanie klawiszy w Notatniku
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s │ %(levelname)-7s │ %(message)s",
        datefmt="%H:%M:%S",
    )


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        print(f"[✗] Brak pliku konfiguracji: {CONFIG_PATH}")
        print("    Uruchom najpierw: python main.py --discover")
        sys.exit(1)
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _validate_config_for_run(cfg: dict) -> None:
    """Sprawdza, czy config ma wystarczające dane do trybu --run."""
    errors: list[str] = []
    if not cfg.get("device_address"):
        errors.append("Brak device_address — uruchom --discover")
    if not cfg.get("notify_characteristic_uuid"):
        errors.append("Brak notify_characteristic_uuid — uruchom --calibrate")
    for name in ("shift_up", "shift_down"):
        m = cfg.get("mappings", {}).get(name, {})
        if not m.get("ble_payload_hex"):
            errors.append(f"Brak ble_payload_hex dla {name} — uruchom --calibrate")
    if errors:
        print("[✗] Konfiguracja niekompletna:")
        for e in errors:
            print(f"    • {e}")
        sys.exit(1)


async def cmd_discover() -> None:
    from src.discovery import discover
    address = await discover()
    if address:
        print(f"\n[✓] Gotowe! Adres VS200: {address}")
        print("    Następny krok: python main.py --calibrate")


async def cmd_calibrate() -> None:
    from src.discovery import calibrate
    await calibrate()


async def cmd_battery() -> None:
    """Sprawdza poziom baterii kontrolera VS200."""
    cfg = _load_config()
    address = cfg.get("device_address")
    if not address:
        print("[✗] Brak device_address w config.json — uruchom najpierw --discover")
        sys.exit(1)

    from bleak import BleakClient, BleakScanner

    print(f"🔍 Łączenie z kontrolerem {address}...")
    print("👉 Klikaj przyciski na VS200, aby go wybudzić!")

    device = await BleakScanner.find_device_by_address(address, timeout=10.0)
    target = device if device else address

    try:
        async with BleakClient(target, timeout=15.0) as client:
            if not client.is_connected:
                print("[✗] Nie udało się połączyć.")
                return

            print("✓ Połączono z VS200!")
            battery_uuid = "00002a19-0000-1000-8000-00805f9b34fb"
            val = await client.read_gatt_char(battery_uuid)
            pct = int(val[0])
            print(f"\n🔋 Poziom baterii: {pct}%")
            if pct < 30:
                print("⚠️ UWAGA: Poziom baterii poniżej 30%! Zalecana wymiana baterii CR2032.")
            else:
                print("✓ Stan baterii prawidłowy.")
    except Exception as e:
        print(f"[✗] Błąd odczytu baterii: {e}")


async def cmd_run() -> None:
    cfg = _load_config()
    _validate_config_for_run(cfg)

    from src.ble_client import VS200Bridge
    from src.input_emulator import warn_if_not_admin

    warn_if_not_admin()
    bridge = VS200Bridge(cfg)

    # Graceful shutdown on Ctrl+C
    loop = asyncio.get_running_loop()

    def _signal_handler() -> None:
        print("\n[i] Otrzymano sygnał zakończenia — zamykam…")
        bridge.stop()

    try:
        loop.add_signal_handler(signal.SIGINT, _signal_handler)
        loop.add_signal_handler(signal.SIGTERM, _signal_handler)
    except NotImplementedError:
        pass

    await bridge.run_forever()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="vs200-mywhoosh-bridge",
        description="Bridge BLE ThinkRider VS200 → MyWhoosh (emulacja klawiszy)",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--discover",
        action="store_true",
        help="Skanuj urządzenia BLE i zapisz adres VS200",
    )
    group.add_argument(
        "--calibrate",
        action="store_true",
        help="Kalibruj przyciski [+] i [-] kontrolera",
    )
    group.add_argument(
        "--battery",
        action="store_true",
        help="Sprawdź poziom baterii kontrolera VS200",
    )
    group.add_argument(
        "--run",
        action="store_true",
        help="Uruchom bridge (nasłuch BLE → emulacja klawiszy)",
    )
    group.add_argument(
        "--test-keys",
        action="store_true",
        help="Testuj wstrzykiwanie klawiszy (otwórz Notatnik i obserwuj)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Szczegółowe logowanie (DEBUG)",
    )

    args = parser.parse_args()
    _setup_logging(args.verbose)

    if args.discover:
        asyncio.run(cmd_discover())
    elif args.calibrate:
        asyncio.run(cmd_calibrate())
    elif args.battery:
        asyncio.run(cmd_battery())
    elif args.test_keys:
        from src.input_emulator import KeyInjector
        injector = KeyInjector(check_window=False)
        asyncio.run(injector.test_keys())
    elif args.run:
        try:
            asyncio.run(cmd_run())
        except KeyboardInterrupt:
            print("\n[i] Zakończono (Ctrl+C).")


if __name__ == "__main__":
    main()
