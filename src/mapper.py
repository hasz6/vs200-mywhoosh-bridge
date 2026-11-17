"""
mapper.py — Dopasowanie payloadu BLE do akcji klawiaturowej z debounce'em.

Odbiera surowy bytearray z notyfikacji GATT, porównuje z zarejestrowanymi
payloadami w config.json, i jeśli pasuje, wywołuje KeyInjector.tap_key()
z odpowiednim scan code.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .input_emulator import KeyInjector

logger = logging.getLogger(__name__)


@dataclass
class MappingEntry:
    """Pojedyncze mapowanie: payload BLE → klawisz."""
    name: str
    payload_hex: str
    key_name: str
    scan_code: int


@dataclass
class ButtonMapper:
    """Dopasowuje payloady BLE do akcji klawiaturowych z debounce'em."""

    mappings: list[MappingEntry] = field(default_factory=list)
    debounce_ms: int = 80
    injector: KeyInjector = field(default_factory=KeyInjector)

    _last_trigger_time: float = field(default=0.0, init=False, repr=False)

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "ButtonMapper":
        """Tworzy mapper z wczytanej konfiguracji (dict z config.json)."""
        mappings_raw = cfg.get("mappings", {})
        entries: list[MappingEntry] = []

        for name, m in mappings_raw.items():
            payload = m.get("ble_payload_hex", "")
            if not payload:
                continue
            entries.append(MappingEntry(
                name=name,
                payload_hex=payload.lower(),
                key_name=m.get("key_name", "?"),
                scan_code=m.get("scan_code", 0),
            ))

        injector = KeyInjector(
            check_window=cfg.get("only_when_mywhoosh_active", True),
            target_window_title=cfg.get("target_window_title", "MyWhoosh"),
        )

        return cls(
            mappings=entries,
            debounce_ms=cfg.get("debounce_ms", 80),
            injector=injector,
        )

    async def handle_notification(self, data: bytearray) -> None:
        """Obsługuje notyfikację BLE — dopasowuje payload i emuluje klawisz."""
        hex_data = data.hex().lower()
        now = time.monotonic()

        for entry in self.mappings:
            if hex_data == entry.payload_hex:
                # Debounce
                elapsed_ms = (now - self._last_trigger_time) * 1000
                if elapsed_ms < self.debounce_ms:
                    logger.debug(
                        "Debounce: pominięto %s (%.0f ms od ostatniego)",
                        entry.name, elapsed_ms,
                    )
                    return

                self._last_trigger_time = now

                logger.info(
                    "⚡ %s  →  klawisz '%s' (ScanCode 0x%02X)",
                    entry.name, entry.key_name, entry.scan_code,
                )
                sent = await self.injector.tap_key(
                    entry.scan_code, key_name=entry.key_name,
                )
                if not sent:
                    logger.info("  (pominięto — MyWhoosh nie jest aktywnym oknem)")
                return

        # Nieznany payload — loguj jako debug
        logger.debug("Nieznany payload BLE: 0x%s", hex_data)
