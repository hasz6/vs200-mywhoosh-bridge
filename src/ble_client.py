"""
ble_client.py — Główna pętla BLE: połączenie, subskrypcja GATT,
                auto-reconnect po uśpieniu kontrolera, odczyt poziomu baterii.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from bleak import BleakClient, BleakScanner
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice

from .mapper import ButtonMapper

logger = logging.getLogger(__name__)

BATTERY_LEVEL_UUID = "00002a19-0000-1000-8000-00805f9b34fb"


class VS200Bridge:
    """Zarządza połączeniem BLE z VS200 i przekazuje zdarzenia do ButtonMapper."""

    def __init__(
        self,
        cfg: dict[str, Any],
        status_callback: Callable[[str, str, int | None], None] | None = None,
    ):
        self.address: str = cfg["device_address"]
        self.char_uuid: str = cfg["notify_characteristic_uuid"]
        self.mapper = ButtonMapper.from_config(cfg)
        self.status_callback = status_callback
        self.battery_level: int | None = None
        self._disconnect_event = asyncio.Event()
        self._running = True

    def _set_status(self, state: str, message: str, battery: int | None = None) -> None:
        if battery is not None:
            self.battery_level = battery
        if self.status_callback:
            try:
                self.status_callback(state, message, self.battery_level)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Odczyt baterii
    # ------------------------------------------------------------------

    async def read_battery(self, client: BleakClient) -> int | None:
        """Odczytuje poziom baterii (0-100%) z charakterystyki 0x2A19."""
        try:
            val = await client.read_gatt_char(BATTERY_LEVEL_UUID)
            pct = int(val[0])
            self.battery_level = pct
            if pct < 30:
                logger.warning("⚠️ NISKI POZIOM BATERII VS200: %d%%! (Zalecana wymiana CR2032)", pct)
            else:
                logger.info("🔋 Poziom baterii VS200: %d%%", pct)
            return pct
        except Exception as e:
            logger.debug("Nie udało się odczytać baterii: %s", e)
            return None

    # ------------------------------------------------------------------
    # Callbacki
    # ------------------------------------------------------------------

    def _on_disconnect(self, client: BleakClient) -> None:
        logger.warning("⚠ Kontroler rozłączony (uśpienie lub zerwanie połączenia)")
        self._set_status("disconnected", "Rozłączono (uśpienie)")
        self._disconnect_event.set()

    def _on_notification(self, char: BleakGATTCharacteristic, data: bytearray) -> None:
        """Callback wywoływany przez bleak przy każdej notyfikacji GATT."""
        asyncio.get_event_loop().create_task(self.mapper.handle_notification(data))

    # ------------------------------------------------------------------
    # Połączenie i subskrypcja
    # ------------------------------------------------------------------

    async def _connect_and_subscribe(self, device_or_address: BLEDevice | str) -> None:
        """Jedno podłączenie: łączy, odczytuje baterię i subskrybuje notyfikacje."""
        self._disconnect_event.clear()

        logger.info("Łączenie z %s…", self.address)
        self._set_status("connecting", f"Łączenie z {self.address}…")

        async with BleakClient(
            device_or_address,
            disconnected_callback=self._on_disconnect,
            timeout=15.0,
        ) as client:
            if not client.is_connected:
                logger.error("Nie udało się połączyć.")
                self._set_status("disconnected", "Nie udało się połączyć")
                return

            logger.info("✓ Połączono z %s", self.address)

            # Odczyt baterii zaraz po połączeniu
            batt = await self.read_battery(client)
            self._set_status("connected", "Połączono — kontroler aktywny", batt)

            # Subskrypcja przycisków
            await client.start_notify(self.char_uuid, self._on_notification)
            logger.info(
                "🔔 Nasłuch aktywny na UUID %s — kontroler gotowy!",
                self.char_uuid,
            )

            # Czekaj na rozłączenie
            await self._disconnect_event.wait()

    # ------------------------------------------------------------------
    # Auto-reconnect loop
    # ------------------------------------------------------------------

    async def _wait_for_device(self, interval: float = 2.0) -> BLEDevice | None:
        """Pasywne czekanie na wybudzenie VS200."""
        logger.info("🔍 Oczekiwanie na kliknięcie przycisku na VS200…")
        self._set_status("sleeping", "Oczekiwanie na wybudzenie (kliknij przycisk)")

        while self._running:
            device = await BleakScanner.find_device_by_address(
                self.address, timeout=interval
            )
            if device is not None:
                logger.info("📡 VS200 wybudzony — nawiązuję sesję…")
                return device
            await asyncio.sleep(0.3)
        return None

    async def run_forever(self) -> None:
        """Główna pętla: łącz → nasłuchuj → po rozłączeniu czekaj → łącz ponownie."""
        logger.info("=== VS200-MyWhoosh Bridge — START ===")
        logger.info("Adres: %s | Characteristic: %s", self.address, self.char_uuid)
        logger.info("Ctrl+C aby zakończyć.\n")

        # Pierwsze znalezienie urządzenia
        device: BLEDevice | str = self.address
        found = await BleakScanner.find_device_by_address(self.address, timeout=4.0)
        if found:
            device = found

        while self._running:
            try:
                await self._connect_and_subscribe(device)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Błąd połączenia: %s", exc)
                self._set_status("disconnected", f"Błąd: {exc}")
                await asyncio.sleep(1.0)

            if not self._running:
                break

            # Czekaj na wybudzenie
            try:
                fresh_dev = await self._wait_for_device()
                if fresh_dev is not None:
                    device = fresh_dev
            except asyncio.CancelledError:
                break

        logger.info("=== VS200-MyWhoosh Bridge — STOP ===")
        self._set_status("stopped", "Zatrzymano")

    def stop(self) -> None:
        self._running = False
        self._disconnect_event.set()
