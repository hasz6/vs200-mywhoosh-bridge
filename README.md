# VS200 to MyWhoosh Bridge

Lekka aplikacja na system Windows umożliwiająca bezpośrednie połączenie bezprzewodowego kontrolera **ThinkRider VS200** (BLE GATT) z grą **MyWhoosh** w celu obsługi wirtualnej zmiany biegów (MyShift: klawisze `I` oraz `K`).

> ⚠️ **WAŻNA INFORMACJA O ZGODNOŚCI:**
> - Aplikacja została **potwierdzona i przetestowana wyłącznie z kontrolerem ThinkRider VS200 oraz MyWhoosh**.
> - Rozwiązanie **NIE było testowane z platformą Zwift**.

---

## ✨ Główne cechy

- **Brak pośredników**: Łączy się bezpośrednio z adapterem Bluetooth w PC, bez udziału trenażera.
- **Wsparcie dla Unreal Engine (DirectInput / ScanCodes)**: Używa niskopoziomowych kodów skanowania Win32 (`user32.SendInput`), dzięki czemu silnik MyWhoosh poprawnie rejestruje wciśnięcia klawiszy.
- **Wbudowany kreator konfiguracji**:
  - `--discover`: automatyczne skanowanie i wykrywanie kontrolera VS200.
  - `--calibrate`: automatyczne rozpoznawanie kodów przycisków `[+]` oraz `[-]`.
- **System Tray (Zasobnik systemowy)**: Wersja `.exe` działa dyskretnie w tle koło zegara, pokazując stan połączenia kolorową ikoną:
  - 🟢 **Zielony**: Kontroler połączony i gotowy do jazdy.
  - 🟡 **Żółty**: Kontroler w trybie uśpienia (oczekuje na kliknięcie przycisku na kierownicy).
  - 🔵 **Niebieski**: Nawiązywanie połączenia.
  - 🔴 **Czerwony**: Rozłączono.
- **Auto-reconnect**: Automatyczne wznawianie sesji BLE po wybudzeniu kontrolera z uśpienia.
- **Autostart**: Opcja uruchamiania aplikacji wraz ze startem systemu Windows.

---

## 🚀 Szybki start (Gotowy plik `.exe`)

W katalogu `dist/` znajduje się skompilowany plik: `VS200-MyWhoosh-Bridge.exe`.

1. Skopiuj plik `config.example.json` jako `config.json` obok pliku `.exe`.
2. Uzupełnij adres MAC urządzenia (lub przeprowadź jednorazową kalibrację skryptem Python).
3. Uruchom `VS200-MyWhoosh-Bridge.exe` (program poprosi o uprawnienia administratora, co jest wymagane do wstrzykiwania klawiszy do gier).
4. Kliknij przycisk na kontrolerze VS200 – ikonka w zasobniku zmieni kolor na zielony.

---

## 🛠️ Uruchomienie ze źródeł (Python)

### Wymagania
- Windows 10 lub 11 z wbudowanym Bluetooth
- Python 3.9+

### Instalacja
```bash
pip install -r requirements.txt
```

### Pierwsza konfiguracja
1. **Wykrycie kontrolera**:
   ```bash
   python main.py --discover
   ```
   (Wybierz kontroler z listy; adres zostanie zapisany do `config.json`).

2. **Kalibracja przycisków**:
   ```bash
   python main.py --calibrate
   ```
   (Postępuj zgodnie z instrukcjami na ekranie, wciskając `[+]` i `[-]`).

3. **Uruchomienie bridge'a**:
   ```bash
   python main.py --run
   ```

---

## 💡 Rozwiązywanie problemów

- **Błąd: `Could not get GATT services: Unreachable`**:
  Oznacza to, że inna aplikacja (lub sam system Windows) trzyma aktywne połączenie z kontrolerem.
  1. Upewnij się, że kontroler **nie jest sparowany bezpośrednio w Ustawieniach Windows (Bluetooth)**. Jeśli jest – kliknij *Usuń urządzenie*.
  2. Sprawdź, czy kontroler nie połączył się automatycznie na ekranie parowania urządzeń w samej grze MyWhoosh. Jeśli tak – odłącz go tam.

- **Klawisze nie zmieniają biegów w grze**:
  MyWhoosh działa z podwyższonymi uprawnieniami. Aplikacja/skrypt musi być uruchamiany z uprawnieniami Administratora (*Uruchom jako administrator*).

---

## 📄 Licencja

Projekt udostępniany na darmowej, otwartej licencji MIT (szczegóły w pliku `LICENSE`).
