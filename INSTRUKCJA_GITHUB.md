# Bot w chmurze: GitHub Actions

Bot uruchamia się na serwerach GitHuba co ok. 20 minut. Nie potrzebujesz włączonego komputera.

Zanim zaczniesz: zrób kroki 2 i 3 z `INSTRUKCJA.md`. Potrzebujesz tokena bota, swojego chat_id (najłatwiej uzyskać je raz na komputerze) i linków do wyszukiwań wpisanych w `config.yaml`.

## 1. Załóż repozytorium
1. Załóż darmowe konto na https://github.com.
2. Kliknij **New repository**, nadaj nazwę, np. `bot-nieruchomosci`.
3. Wybierz **Public**, bo publiczne repozytorium ma nielimitowane darmowe minuty.
   - Token i chat_id będą ukryte w sekretach, więc nikt ich nie zobaczy. Publicznie widoczne będą tylko linki do wyszukiwań z `config.yaml`.
   - Wolisz **Private**? Darmowy limit to 2000 minut miesięcznie. To wystarcza na uruchamianie mniej więcej **co godzinę**, nie co 20 minut. W `bot.yml` zmień wtedy linię cron na `"7 * * * *"`.

## 2. Wgraj pliki
W repozytorium kliknij **Add file → Upload files** i przeciągnij:
`bot_nieruchomosci.py`, `config.yaml`, `requirements.txt`, `.gitignore`.
Na koniec kliknij **Commit changes**.

**Nie wpisuj tokena w `config.yaml`, który wgrywasz.** Zostaw tam tekst zastępczy, bo token trafi do sekretów (krok 4).

## 3. Dodaj plik harmonogramu
1. Kliknij **Add file → Create new file**.
2. Jako nazwę wpisz dokładnie: `.github/workflows/bot.yml`. Ukośniki same utworzą foldery.
3. Wklej zawartość pliku `bot.yml` i kliknij **Commit changes**.

## 4. Dodaj sekrety
Wejdź w **Settings → Secrets and variables → Actions → New repository secret** i dodaj dwa sekrety:
- `TELEGRAM_TOKEN` z tokenem od BotFathera,
- `TELEGRAM_CHAT_ID` ze swoim chat_id.

## 5. Uruchom i sprawdź
1. Wejdź w zakładkę **Actions**. Jeśli GitHub zapyta, zezwól na workflowy.
2. Wybierz **Bot nieruchomosci → Run workflow**.
3. Po minucie lub dwóch kliknij w przebieg i rozwiń krok **„Sprawdź portale”**. Powinieneś zobaczyć „pierwsze uruchomienie – zapamiętano N istniejących ofert” przy każdym linku.
4. Jeśli przy jakimś portalu jest **„HTTP 403”** albo **„0 ofert”**, ten portal blokuje serwery GitHuba. Skopiuj mi wtedy log.

Od tej chwili bot działa sam. Historia ofert (`oferty.db`) zapisuje się w repozytorium po każdym przebiegu.

## Zmiana filtrów
Otwórz `config.yaml` w repozytorium, kliknij ikonę ołówka, zmień plik i zapisz (**Commit changes**). Zmiana działa od następnego przebiegu.

## Dobrze wiedzieć
- GitHub często opóźnia zaplanowane uruchomienia o 5–15 minut, a przy dużym obciążeniu bywa, że pominie jakiś przebieg.
- Jeśli w repozytorium przez 60 dni nic się nie zmieni, GitHub wyłącza harmonogram. Bot sam zapisuje zmiany przy nowych ofertach, więc zwykle to nie grozi. Gdyby jednak harmonogram się wyłączył, w zakładce Actions kliknij **Enable workflow**.
- Bot zatrzymuje się po usunięciu repozytorium albo po kliknięciu **Disable workflow** w zakładce Actions.
