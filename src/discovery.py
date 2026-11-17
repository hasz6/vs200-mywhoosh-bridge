"""
discovery.py — BLE Scanner & GATT Calibration Wizard for ThinkRider VS200.

Tryb --discover : skanuje okoliczne urządzenia BLE, filtruje po nazwie/RSSI,
                   zapisuje adres MAC do config.json.
Tryb --calibrate: łączy się z zapisanym MAC, subskrybuje wszystkie notify/indicate
                   characteristics i prowadzi użytkownika przez kalibrację przycisków.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic

# Standardowe serwisy BLE, które pomijamy przy kalibracji
_EXCLUDED_SERVICE_UUIDS = {
    "00001800-0000-1000-8000-00805f9b34fb",  # Generic Access
    "00001801-0000-1000-8000-00805f9b34fb",  # Generic Attribute
    "0000180a-0000-1000-8000-00805f9b34fb",  # Device Information
    "0000180f-0000-1000-8000-00805f9b34fb",  # Battery Service
}

# Nazwy, które mogą identyfikować kontroler — case-insensitive
_KNOWN_DEVICE_NAMES = (
    "vs200", "vs 200", "thinkrider", "think rider",
    "tr_", "tr-", "cycplus", "onelap",
)

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"


def _load_config() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


def _save_config(cfg: dict[str, Any]) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[✓] Konfiguracja zapisana do {CONFIG_PATH}")


def _is_known_device(name: str) -> bool:
    """Sprawdza, czy nazwa urządzenia pasuje do znanych kontrolerów."""
    name_lower = name.lower()
    return any(tag in name_lower for tag in _KNOWN_DEVICE_NAMES)


# ---------------------------------------------------------------------------
# --discover
# ---------------------------------------------------------------------------

async def discover(timeout: float = 15.0) -> str | None:
    """Skanuje urządzenia BLE i pozwala użytkownikowi wybrać VS200.

    Zwraca wybrany adres MAC lub None, jeśli nie znaleziono.
    """
    while True:
        print(f"\n[…] Skanowanie urządzeń BLE ({timeout}s)…")
        print("    Upewnij się, że VS200 jest wybudzony (kliknij przycisk na kierownicy).\n")

        # Aktywne skanowanie — wymusza odpowiedzi Scan Response z pełną nazwą
        try:
            devices = await BleakScanner.discover(
                timeout=timeout,
                return_adv=True,
                scanning_mode="active",
            )
        except TypeError:
            # Starsze wersje bleak mogą nie wspierać scanning_mode
            devices = await BleakScanner.discover(
                timeout=timeout,
                return_adv=True,
            )

        if not devices:
            print("[✗] Nie wykryto żadnych urządzeń BLE.")
            print("    Sprawdź, czy adapter Bluetooth jest włączony w systemie.")
            retry = input("\nSpróbować ponownie? (T/n): ").strip().lower()
            if retry == "n":
                return None
            continue

        # Podziel na: prawdopodobne VS200 i resztę
        likely: list[tuple[Any, Any]] = []
        others: list[tuple[Any, Any]] = []

        for dev, adv in devices.values():
            name = dev.name or adv.local_name or ""
            if _is_known_device(name):
                likely.append((dev, adv))
            else:
                others.append((dev, adv))

        # Sortuj każdą grupę po RSSI malejąco
        def _rssi(item: tuple) -> int:
            return item[1].rssi if item[1].rssi is not None else -100

        likely.sort(key=_rssi, reverse=True)
        others.sort(key=_rssi, reverse=True)

        # Pokaż wyniki
        all_devices = likely + others
        print(f"{'Nr':<4} {'Nazwa':<30} {'Adres MAC':<20} {'RSSI':<6} {'Uwagi'}")
        print("-" * 80)
        for i, (dev, adv) in enumerate(all_devices, 1):
            name = dev.name or adv.local_name or "(brak nazwy)"
            rssi = adv.rssi if adv.rssi is not None else "?"
            note = " ◄ prawdopodobny VS200" if (dev, adv) in likely else ""
            print(f"{i:<4} {name:<30} {dev.address:<20} {rssi:<6}{note}")

        total = len(all_devices)
        print(f"\nZnaleziono {total} urządzeń BLE ({len(likely)} pasujących do VS200).")

        if likely:
            print(f"\n[→] Sugerowane: nr 1 ({likely[0][0].name or likely[0][1].local_name})")

        # Pozwól użytkownikowi wybrać lub ponowić skanowanie
        while True:
            raw = input(
                "\nWpisz numer urządzenia (Enter = 1), "
                "'r' = ponowne skanowanie, 'q' = wyjście: "
            ).strip().lower()

            if raw == "q":
                return None
            if raw == "r":
                break  # ponawia zewnętrzny while
            if raw == "":
                idx = 0
            elif raw.isdigit() and 1 <= int(raw) <= total:
                idx = int(raw) - 1
            else:
                print("  Nieprawidłowy wybór, spróbuj ponownie.")
                continue

            chosen = all_devices[idx][0]

            # Zapis do config
            cfg = _load_config()
            cfg["device_address"] = chosen.address
            cfg["device_name"] = chosen.name or "VS200"
            _save_config(cfg)
            return chosen.address
        # Jeśli 'r' → kontynuuj pętlę while True


# ---------------------------------------------------------------------------
# --calibrate
# ---------------------------------------------------------------------------

async def calibrate() -> None:
    """Łączy się z VS200 i prowadzi użytkownika przez kalibrację przycisków."""
    cfg = _load_config()
    address = cfg.get("device_address", "")

    if not address:
        print("[!] Brak zapisanego adresu MAC. Uruchom najpierw: python main.py --discover")
        sys.exit(1)

    print(f"[…] Łączenie z {address}…")

    async with BleakClient(address, timeout=15.0) as client:
        if not client.is_connected:
            print("[✗] Nie udało się połączyć z urządzeniem.")
            sys.exit(1)

        print(f"[✓] Połączono z {address}")

        # Zbierz notify/indicate characteristics (pomijając standardowe serwisy)
        notify_chars: list[BleakGATTCharacteristic] = []
        print("\n[…] Skanowanie drzewa GATT…\n")
        for service in client.services:
            if service.uuid.lower() in _EXCLUDED_SERVICE_UUIDS:
                continue
            for char in service.characteristics:
                props = [p.lower() for p in char.properties]
                if "notify" in props or "indicate" in props:
                    notify_chars.append(char)
                    print(f"  Serwis {service.uuid}  →  Char {char.uuid}  [{', '.join(char.properties)}]")

        if not notify_chars:
            print("\n[✗] Nie znaleziono żadnych charakterystyk notify/indicate.")
            sys.exit(1)

        # Zmienna do przechwycenia danych
        captured: dict[str, list[tuple[str, str]]] = {"packets": []}

        def _on_notify(char: BleakGATTCharacteristic, data: bytearray) -> None:
            hex_str = data.hex()
            captured["packets"].append((char.uuid, hex_str))

        # Subskrybuj wszystkie naraz
        for ch in notify_chars:
            await client.start_notify(ch.uuid, _on_notify)

        print(f"\n[i] Subskrybowano {len(notify_chars)} charakterystyk.\n")

        # --- Kalibracja [+] ---
        payload_up, uuid_up = await _capture_button(
            captured, "Naciśnij przycisk [+] (shift UP) na kontrolerze VS200"
        )

        # --- Kalibracja [-] ---
        payload_down, uuid_down = await _capture_button(
            captured, "Naciśnij przycisk [-] (shift DOWN) na kontrolerze VS200"
        )

        # Zapis wyników
        if uuid_up != uuid_down:
            print(f"[!] Uwaga: przyciski zgłosiły się na różnych UUID ({uuid_up} vs {uuid_down}).")
            print("    Zapisuję UUID od przycisku [+].")

        cfg["notify_characteristic_uuid"] = uuid_up
        cfg["mappings"]["shift_up"]["ble_payload_hex"] = payload_up
        cfg["mappings"]["shift_down"]["ble_payload_hex"] = payload_down
        _save_config(cfg)

        # Sprzątanie
        for ch in notify_chars:
            try:
                await client.stop_notify(ch.uuid)
            except Exception:
                pass

    print("\n[✓] Kalibracja zakończona pomyślnie!")
    print("    Teraz możesz uruchomić:  python main.py --run")


async def _capture_button(
    captured: dict[str, list[tuple[str, str]]],
    prompt: str,
) -> tuple[str, str]:
    """Czeka na jedno naciśnięcie przycisku, zwraca (payload_hex, char_uuid)."""
    captured["packets"].clear()
    input(f"\n>>> {prompt}, a następnie naciśnij Enter… ")

    # Daj chwilę na przetworzenie notyfikacji BLE
    await asyncio.sleep(0.3)

    if not captured["packets"]:
        print("  [!] Nie odebrano żadnych pakietów. Spróbuj ponownie.")
        return await _capture_button(captured, prompt)

    # Wyświetl odebrane pakiety
    print(f"  Odebrano {len(captured['packets'])} pakiet(ów):")
    for uuid, hex_data in captured["packets"]:
        print(f"    UUID: {uuid}  →  dane: 0x{hex_data}")

    # Bierzemy pierwszy pakiet jako payload
    uuid, payload = captured["packets"][0]
    print(f"  [→] Wybrany payload: 0x{payload} z UUID {uuid}")
    return payload, uuid
