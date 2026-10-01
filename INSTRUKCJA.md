# Bot nieruchomości → Telegram: instrukcja

## 1. Zainstaluj Pythona
- Windows: pobierz z https://www.python.org/downloads/ i przy instalacji zaznacz **„Add Python to PATH”**.
- Mac: `brew install python` albo instalator z python.org.

Wszystkie pliki (`bot_nieruchomosci.py`, `config.yaml`, `requirements.txt`, `start_windows.bat`) włóż do jednego folderu, np. `C:\bot`.

W tym folderze otwórz terminal (Windows: w pasku adresu folderu wpisz `cmd` i Enter) i wykonaj:
```
pip install -r requirements.txt
```

## 2. Utwórz bota na Telegramie
1. W Telegramie znajdź **@BotFather** i wyślij `/newbot`.
2. Podaj nazwę, np. „Moje Mieszkania”, i login kończący się na `bot`.
3. Dostaniesz **token** (np. `7123456789:AAH...`). Wklej go do `config.yaml` w polu `token`.
4. Otwórz swojego nowego bota i napisz do niego cokolwiek, np. „hej”.
5. W terminalu uruchom:
   ```
   python bot_nieruchomosci.py --chat-id
   ```
   Skopiuj wyświetlony numer do `config.yaml` w polu `chat_id`.
6. Sprawdź połączenie:
   ```
   python bot_nieruchomosci.py --test-telegram
   ```

## 3. Ustaw wyszukiwania
Dla każdego portalu:
1. Wejdź na portal i ustaw filtry na stronie (miasto, typ, cena, metraż itd.).
2. Ustaw sortowanie **od najnowszych**.
3. Skopiuj link z paska adresu i wklej go do `config.yaml` w sekcji `urls`.

W sekcji `filters` ustaw dodatkowe kryteria, które bot sprawdza sam: cenę, metraż, cenę za m², pokoje, słowa wymagane i wykluczone. Możesz mieć kilka wyszukiwań, np. osobno mieszkania i działki.

Uwaga: w pliku YAML liczy się wcięcie. Zachowaj spacje tak, jak w przykładzie.

## 4. Test
```
python bot_nieruchomosci.py --test
```
Przy każdym linku zobaczysz, ile ofert bot znalazł, oraz przykładową cenę i metraż. Jeśli przy którymś portalu jest „0 ofert” albo błąd, daj mi znać, co się wyświetliło.

## 5. Uruchomienie
```
python bot_nieruchomosci.py
```
Na Windowsie możesz też po prostu kliknąć dwukrotnie `start_windows.bat`.

- **Pierwszy przebieg** tylko zapamiętuje oferty, które już są na portalach, więc nie dostaniesz setek starych ogłoszeń. Powiadomienia przychodzą od drugiego przebiegu i dotyczą wyłącznie nowych ofert.
- Bot działa, dopóki okno jest otwarte, a komputer nie śpi.
- Historia ofert zapisuje się w `oferty.db`, a dziennik w `bot.log`. Jeśli usuniesz `oferty.db`, bot zacznie od nowa.
- Jeśli któryś portal 3 razy z rzędu się nie wczyta, dostaniesz ostrzeżenie na Telegramie.

### Automatyczny start (opcjonalnie)
Windows: Harmonogram zadań → Utwórz zadanie podstawowe → „Przy logowaniu” → program `python`, argument `bot_nieruchomosci.py`, katalog startowy to Twój folder.
