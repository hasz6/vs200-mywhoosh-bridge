"""
check_battery.py — Prototyp diagnostyczny do badania poziomu baterii w ThinkRider VS200.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-7s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("battery_checker")

CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"
BATTERY_SERVICE_UUID = "0000180f-0000-1000-8000-00805f9b34fb"


def load_target_address() -> str:
    if CONFIG_PATH.exists():
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            addr = cfg.get("device_address")
            if addr:
                return addr
        except Exception:
            pass
    return ""


async def wait_and_get_device(address: str, timeout_total: float = 60.0) -> BLEDevice | None:
    logger.info("🔍 Szukam kontrolera %s w eterze...", address)
    logger.info("👉 KLIKAJ TERAZ przycisk [+] lub [-] na kontrolerze, aby go wybudzić!")
    
    start_time = asyncio.get_event_loop().time()
    while (asyncio.get_event_loop().time() - start_time) < timeout_total:
        device = await BleakScanner.find_device_by_address(address, timeout=2.0)
        if device is not None:
            logger.info("📡 WYKRYTO KONTROLER: %s (RSSI: %s)", device.name or "VS200", getattr(device, "rssi", "?"))
            return device
        print(".", end="", flush=True)
    print()
    return None


async def inspect_advertisement_data(device: BLEDevice) -> None:
    logger.info("\n📊 [KROK 1] Analiza danych rozgłoszeniowych (Advertisement)...")
    adv_details = getattr(device, "details", None)
    logger.info("Szczegóły urządzenia: %s", adv_details)


async def inspect_gatt(device: BLEDevice) -> None:
    logger.info("\n🔌 [KROK 2] Łączenie z VS200...")
    logger.info("👉 Cały czas kliknij przycisk raz na 2-3 sekundy, żeby nie zasnął podczas łączenia!")

    # Używamy świeżego obiektu BLEDevice
    async with BleakClient(device, timeout=15.0) as client:
        if not client.is_connected:
            logger.error("Nie udało się połączyć.")
            return

        logger.info("✓ Połączono pomyślnie!\n")

        battery_found = False
        readable_chars = []
        notify_chars = []

        logger.info("--- PRZEGLĄD SERWISÓW I CHARAKTERYSTYK ---")
        for service in client.services:
            is_battery_srv = service.uuid.lower() == BATTERY_SERVICE_UUID.lower()
            srv_label = " [BATTERY SERVICE]" if is_battery_srv else ""
            logger.info("Serwis: %s (%s)%s", service.uuid, service.description, srv_label)

            for char in service.characteristics:
                props = ",".join(char.properties)
                is_battery_char = char.uuid.lower() == BATTERY_LEVEL_UUID.lower()
                char_label = " ⭐ BATTERY LEVEL" if is_battery_char else ""
                logger.info("   ├─ Char: %s (%s) [%s]%s", char.uuid, char.description, props, char_label)

                if "read" in char.properties:
                    readable_chars.append(char)
                if "notify" in char.properties or "indicate" in char.properties:
                    notify_chars.append(char)

                if is_battery_char:
                    battery_found = True

        logger.info("-------------------------------------------\n")

        # Krok 3: Próba odczytu standardowej baterii
        logger.info("🔋 [KROK 3] Próba bezpośredniego odczytu standardowej baterii (0x2A19)...")
        if battery_found:
            try:
                val = await client.read_gatt_char(BATTERY_LEVEL_UUID)
                pct = int(val[0])
                logger.info("🎉 SUKCES! Odczytano poziom baterii: %d%% (surowe bajty: 0x%s)", pct, val.hex())
            except Exception as e:
                logger.warning("Błąd odczytu charakterystyki baterii: %s", e)
        else:
            logger.info("ℹ Urządzenie nie udostępnia standardowej charakterystyki Battery Service (0x180F / 0x2A19).")

        # Krok 4: Odczyt pozostałych charakterystyk z flagą 'read'
        logger.info("\n📖 [KROK 4] Próba odczytu pozostałych charakterystyk z flagą 'read'...")
        for ch in readable_chars:
            if ch.uuid.lower() == BATTERY_LEVEL_UUID.lower():
                continue
            try:
                data = await client.read_gatt_char(ch.uuid)
                hex_val = data.hex()
                text_val = ""
                try:
                    text_val = f" (tekst: '{data.decode('utf-8', errors='ignore')}')"
                except Exception:
                    pass
                logger.info("   Char %s -> 0x%s%s", ch.uuid, hex_val, text_val)
            except Exception as e:
                logger.debug("   Char %s -> pominięto (%s)", ch.uuid, e)

        # Krok 5: Nasłuch notyfikacji (kliknięcia przycisków)
        logger.info("\n👂 [KROK 5] Nasłuch notyfikacji przez 12 sekund.")
        logger.info("👉 Kliknij przycisk [+] 2-3 razy, a potem [-] 2-3 razy:")

        def on_notify(c: BleakGATTCharacteristic, data: bytearray):
            logger.info("   [NOTIFY %s] Odebrano (%d bajtów): 0x%s", c.uuid, len(data), data.hex())
            if len(data) >= 4:
                logger.info("       Bajt po bajcie (dec): %s", list(data))

        for ch in notify_chars:
            try:
                await client.start_notify(ch.uuid, on_notify)
            except Exception as e:
                logger.warning("Nie udało się subskrybować %s: %s", ch.uuid, e)

        await asyncio.sleep(12.0)

        for ch in notify_chars:
            try:
                await client.stop_notify(ch.uuid)
            except Exception:
                pass

        logger.info("\n✓ Zakończono analizę.")


async def main():
    addr = load_target_address()
    if not addr:
        logger.error("Brak adresu MAC w config.json.")
        return

    logger.info("Adres kontrolera: %s", addr)
    device = await wait_and_get_device(addr, timeout_total=45.0)
    if not device:
        logger.error("\nNie udało się wykryć kontrolera. Upewnij się, że Bluetooth w Windows jest włączony i klikasz przyciski.")
        return

    await inspect_gatt(device)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\nPrzerwano (Ctrl+C).")
