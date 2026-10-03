#!/usr/bin/env python3
"""
Bot nieruchomości – monitoruje wyniki wyszukiwania na portalach
(Otodom, OLX, Gratka, Nieruchomosci-online, Morizon, Adresowo, Domiporta)
i wysyła NOWE oferty spełniające filtry na Telegram.

Użycie:
  python bot_nieruchomosci.py                 # praca ciągła (co interval_minutes)
  python bot_nieruchomosci.py --once          # jedno sprawdzenie (np. dla Harmonogramu zadań / crona)
  python bot_nieruchomosci.py --test          # test: pokazuje co bot widzi, nic nie wysyła i nie zapisuje
  python bot_nieruchomosci.py --chat-id       # pokazuje Twoje chat_id (najpierw napisz coś do bota)
  python bot_nieruchomosci.py --test-telegram # wysyła wiadomość testową
"""
import argparse
import html as htmllib
import json
import logging
import os
import random
import re
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse

import requests
import yaml
from bs4 import BeautifulSoup

# curl_cffi udaje prawdziwą przeglądarkę Chrome – portale rzadziej blokują.
try:
    from curl_cffi import requests as http
    FETCH_KW = {"impersonate": "chrome"}
    HEADERS = {"Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8"}
except ImportError:  # awaryjnie zwykłe requests
    http = requests
    FETCH_KW = {}
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/129.0 Safari/537.36",
        "Accept-Language": "pl-PL,pl;q=0.9,en;q=0.8",
    }

BASE = Path(__file__).resolve().parent
DB_PATH = BASE / "oferty.db"
CONFIG_PATH = BASE / "config.yaml"

log = logging.getLogger("bot")

# Portal -> (regex hosta, regex ścieżki oferty)
PORTALS = {
    "Otodom": (r"otodom\.pl", r"/pl/oferta/[A-Za-z0-9\-]+-ID[0-9A-Za-z]+"),
    "OLX": (r"olx\.pl", r"/d/oferta/[A-Za-z0-9\-]+\.html"),
    "Gratka": (r"gratka\.pl", r"/nieruchomosci/[A-Za-z0-9\-]+/(?:ob|oi)/\d+"),
    "Nieruchomosci-online": (r"[a-z0-9\-]+\.nieruchomosci-online\.pl", r"/[A-Za-z0-9,\-]+/\d{5,}\.html"),
    "Morizon": (r"morizon\.pl", r"/oferta/[A-Za-z0-9\-]+-mzn\d+"),
    "Adresowo": (r"adresowo\.pl", r"/o/[A-Za-z0-9\-]+"),
    "Domiporta": (r"domiporta\.pl", r"/nieruchomosci/[A-Za-z0-9\-]+/\d{5,}"),
}


# ---------------------------------------------------------------- narzędzia
def portal_of(url):
    host = urlparse(url).netloc.lower()
    for name, (h, _) in PORTALS.items():
        if re.fullmatch(r"(?:www\.|m\.)?" + h, host):
            return name
    return None


def offer_key(url):
    p = urlparse(url)
    host = re.sub(r"^(www\.|m\.)", "", p.netloc.lower())
    return host + p.path.rstrip("/")


def clean_url(url):
    p = urlparse(url)
    return urlunparse(("https", p.netloc.lower(), p.path, "", "", ""))


def to_num(val):
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).replace("\u00a0", "").replace(" ", "")
    s = re.sub(r"[^\d,\.]", "", s)
    if not s:
        return None
    # "450.000" -> 450000 ; "52,5" -> 52.5
    if re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def fmt(n, unit=""):
    if n is None:
        return "?"
    txt = f"{n:,.0f}".replace(",", " ") if n >= 100 else f"{n:g}"
    return f"{txt}{unit}"


# ---------------------------------------------------------------- pobieranie
def fetch(url):
    r = http.get(url, headers=HEADERS, timeout=30, **FETCH_KW)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")
    return r.text


def extract_links(page_url, page_html):
    """Wyciąga linki do ofert ze strony wyników (także te w osadzonym JSON)."""
    page_portal = portal_of(page_url)
    text = page_html.replace("\\/", "/").replace("\\u002F", "/")
    found = []
    for name, (h, p) in PORTALS.items():
        for m in re.finditer(r"https?://(?:www\.|m\.)?" + h + p, text):
            found.append(m.group(0))
        if name == page_portal:  # linki względne tylko z „własnego” portalu
            for m in re.finditer(r"(?<=[\"'])" + p + r"(?=[\"'?#])", text):
                found.append(urljoin(page_url, m.group(0)))
    out, keys = [], set()
    for u in found:
        u = clean_url(u)
        k = offer_key(u)
        if k not in keys:
            keys.add(k)
            out.append(u)
    return out


# ---------------------------------------------------------------- parsowanie oferty
PRICE_RE = re.compile(
    r"(\d{1,3}(?:[ \u00a0.]\d{3})+|\d{4,})(?:[,.]\d{1,2})?\s*(?:zł|PLN)(?!\s*/\s*m)", re.I)
AREA_RE = re.compile(r"(\d{1,5}(?:[.,]\d{1,2})?)\s*(?:m²|m2|m\.?\s*kw)", re.I)
ROOMS_RE = re.compile(r"(\d{1,2})\s*[- ]?\s*(?:pok\.?|pokoje|pokoi|pokojowe)", re.I)


def first(regex, text, minimum=None):
    for m in regex.finditer(text or ""):
        v = to_num(m.group(1))
        if v is not None and (minimum is None or v >= minimum):
            return v
    return None


def find_key(data, keys):
    """Rekurencyjnie szuka pierwszej wartości dla jednego z kluczy."""
    if isinstance(data, dict):
        for k in keys:
            if k in data and not isinstance(data[k], (dict, list)):
                return data[k]
            if k in data and isinstance(data[k], list) and data[k] and not isinstance(data[k][0], (dict, list)):
                return data[k][0]
        for v in data.values():
            r = find_key(v, keys)
            if r is not None:
                return r
    elif isinstance(data, list):
        for v in data:
            r = find_key(v, keys)
            if r is not None:
                return r
    return None


def parse_offer(url, page_html):
    soup = BeautifulSoup(page_html, "html.parser")

    def meta(*names):
        for n in names:
            t = soup.find("meta", attrs={"property": n}) or soup.find("meta", attrs={"name": n})
            if t and t.get("content"):
                return t["content"].strip()
        return None

    title = meta("og:title") or (soup.title.get_text(strip=True) if soup.title else url)
    desc = meta("og:description", "description") or ""
    price = area = rooms = None
    full_desc = []   # pełny opis oferty (bez menu, polecanych ofert itp.)
    loc = []         # lokalizacja oferty (miejscowość, gmina, powiat)

    # 1) Otodom i inne strony Next.js – dane w __NEXT_DATA__
    nd = soup.find("script", id="__NEXT_DATA__")
    if nd and nd.string:
        try:
            data = json.loads(nd.string)
            ad = data.get("props", {}).get("pageProps", {}).get("ad", {})
            tgt = ad.get("target", {}) if isinstance(ad, dict) else {}
            price = to_num(tgt.get("Price"))
            area = to_num(tgt.get("Area"))
            r = tgt.get("Rooms_num")
            rooms = to_num(r[0] if isinstance(r, list) and r else r)
            if isinstance(ad, dict):
                full_desc.append(BeautifulSoup(str(ad.get("description") or ""), "html.parser").get_text(" "))
                full_desc.append(str(ad.get("title") or ""))
                loc.append(json.dumps(ad.get("location") or {}, ensure_ascii=False))
                loc.append(str(tgt.get("City") or ""))
        except Exception:
            pass

    # 2) JSON-LD (schema.org)
    for _ in [0]:
        for s in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(s.string or "")
            except Exception:
                continue
            if price is None:
                price = to_num(find_key(data, ["price"]))
            if area is None:
                fs = data.get("floorSize") if isinstance(data, dict) else None
                area = to_num(find_key(fs, ["value"]) if isinstance(fs, dict) else fs)
            if rooms is None:
                rooms = to_num(find_key(data, ["numberOfRooms"]))
            d = find_key(data, ["description"])
            if d:
                full_desc.append(str(d))

    if price is None:
        price = to_num(meta("product:price:amount", "og:price:amount"))

    # OLX i inne: blok z opisem ogłoszenia
    for el in soup.select('[data-cy="ad_description"], [data-testid="ad_description"], '
                          '[data-cy="adPageAdDescription"], [itemprop="description"]'):
        full_desc.append(el.get_text(" ", strip=True))

    # OLX: miejscowość z danych strony (pierwsze wystąpienie = to ogłoszenie)
    raw = page_html.replace('\\"', '"')
    for key in ("cityName", "districtName", "regionName"):
        m = re.search(r'"' + key + r'"\s*:\s*"([^"]{2,60})"', raw)
        if m:
            loc.append(m.group(1))
    for el in soup.select('[data-testid="location-date"], [data-cy="ad-location"], [aria-label*="Adres"], '
                          '[data-sentry-component="Location"], .breadcrumbs, nav[aria-label="breadcrumb"]'):
        loc.append(el.get_text(" ", strip=True))

    # 3) Tekst strony (bez menu/stopki)
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    body = soup.get_text(" ", strip=True)
    head = f"{title} {desc}"
    if price is None:
        price = first(PRICE_RE, head, 300) or first(PRICE_RE, body, 300)
    if area is None:
        area = first(AREA_RE, head, 5) or first(AREA_RE, body, 5)
    if rooms is None:
        rooms = first(ROOMS_RE, head, 1) or first(ROOMS_RE, body, 1)

    return {
        "url": url, "portal": portal_of(url) or urlparse(url).netloc,
        "title": htmllib.unescape(title or ""), "desc": htmllib.unescape(desc),
        "price": price, "area": area, "rooms": rooms,
        "ppm2": (price / area) if price and area else None,
        "text": f"{title} {desc} {body}".lower(),
        # tylko tytuł + opis – do słów kluczowych, żeby nie łapać linków „podobne oferty”
        "core": htmllib.unescape(f"{title} {desc} {' '.join(full_desc)}").lower(),
        "loc": htmllib.unescape(" ".join(loc)).lower(),
    }


# ---------------------------------------------------------------- filtry
def passes(o, f):
    """Zwraca (True/False, powód). Brak danych = przepuszczamy (chyba że require_known)."""
    f = f or {}
    strict = f.get("require_known", False)

    def check(val, lo, hi, label):
        if lo is None and hi is None:
            return None
        if val is None:
            return f"brak danych: {label}" if strict else None
        if lo is not None and val < lo:
            return f"{label} {fmt(val)} < {lo}"
        if hi is not None and val > hi:
            return f"{label} {fmt(val)} > {hi}"
        return None

    # Limit metrażu "od góry" nie dotyczy np. całych budynków (lista słów w configu)
    core = o.get("core") or o["text"]
    area_max = f.get("area_max")
    if area_max is not None and any(w.lower() in core for w in f.get("area_max_ignore_if_any") or []):
        area_max = None

    for reason in (
        check(o["price"], f.get("price_min"), f.get("price_max"), "cena"),
        check(o["area"], f.get("area_min"), area_max, "metraż"),
        check(o["ppm2"], f.get("price_per_m2_min"), f.get("price_per_m2_max"), "cena/m²"),
        check(o["rooms"], f.get("rooms_min"), f.get("rooms_max"), "pokoje"),
    ):
        if reason:
            return False, reason

    for w in f.get("exclude_any") or []:
        if w.lower() in core:
            return False, f"zawiera „{w}”"
    places = f.get("location_any") or []
    if places:
        where = f"{o.get('loc', '')} {core}"
        if not any(w.lower() in where for w in places):
            return False, "inna miejscowość"

    inc = f.get("include_any") or []
    if inc and not any(w.lower() in core for w in inc):
        return False, "brak słów z include_any (tytuł/opis)"
    return True, "ok"


# ---------------------------------------------------------------- Telegram
def tg(cfg, method, payload):
    token = cfg["telegram"]["token"]
    for _ in range(3):
        r = requests.post(f"https://api.telegram.org/bot{token}/{method}", json=payload, timeout=20)
        if r.status_code == 429:
            time.sleep(r.json().get("parameters", {}).get("retry_after", 5) + 1)
            continue
        return r
    return r


def send(cfg, text):
    r = tg(cfg, "sendMessage", {
        "chat_id": cfg["telegram"]["chat_id"], "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": False,
    })
    if r.status_code != 200:
        log.error("Telegram: %s %s", r.status_code, r.text[:200])


def offer_msg(o, search_name, highlight=None):
    e = htmllib.escape
    hits = [w for w in (highlight or []) if w.lower() in (o.get("core") or o["text"])]
    star = "⭐ <b>Grunt / wolnostojący</b>\n" if hits else ""
    line = " · ".join(x for x in [
        fmt(o["price"], " zł") if o["price"] else None,
        fmt(o["area"], " m²") if o["area"] else None,
        fmt(o["ppm2"], " zł/m²") if o["ppm2"] else None,
        f"{o['rooms']:g} pok." if o["rooms"] else None,
    ] if x)
    return (star + f"🏠 <b>{e(o['title'][:200])}</b>\n"
            + (f"💰 {line}\n" if line else "")
            + f"📍 {e(o['portal'])} · {e(search_name)}\n{o['url']}")


# ---------------------------------------------------------------- baza
def db_open():
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS seen (key TEXT PRIMARY KEY, url TEXT, search TEXT,
                                         first_seen TEXT, sent INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS scanned (search_url TEXT PRIMARY KEY);
        CREATE TABLE IF NOT EXISTS failures (search_url TEXT PRIMARY KEY, count INTEGER);
    """)
    return db


def note_failure(db, cfg, surl, why):
    row = db.execute("SELECT count FROM failures WHERE search_url=?", (surl,)).fetchone()
    n = (row[0] if row else 0) + 1
    db.execute("INSERT OR REPLACE INTO failures VALUES (?,?)", (surl, n))
    db.commit()
    log.warning("Problem z %s: %s (raz %d z rzędu)", surl, why, n)
    if n == 3:
        send(cfg, f"⚠️ Bot nie może odczytać wyszukiwania (3× z rzędu):\n{surl}\nPowód: {htmllib.escape(why)}")


def clear_failure(db, surl):
    db.execute("DELETE FROM failures WHERE search_url=?", (surl,))
    db.commit()


def pause(a=2.0, b=5.0):
    time.sleep(random.uniform(a, b))


# ---------------------------------------------------------------- główna logika
def run_once(cfg, db):
    max_new = cfg.get("max_new_per_run", 25)
    sent_total = 0
    for s in cfg["searches"]:
        name = s.get("name", "wyszukiwanie")
        for surl in s.get("urls") or []:
            try:
                links = extract_links(surl, fetch(surl))
            except Exception as ex:
                note_failure(db, cfg, surl, str(ex))
                pause()
                continue
            if not links:
                note_failure(db, cfg, surl, "0 ofert na stronie – blokada albo zmiana wyglądu portalu")
                pause()
                continue
            clear_failure(db, surl)
            now = datetime.now().isoformat(timespec="seconds")
            new = [u for u in links
                   if not db.execute("SELECT 1 FROM seen WHERE key=?", (offer_key(u),)).fetchone()]

            first_time = not db.execute("SELECT 1 FROM scanned WHERE search_url=?", (surl,)).fetchone()
            if first_time:
                db.executemany("INSERT OR IGNORE INTO seen VALUES (?,?,?,?,0)",
                               [(offer_key(u), u, name, now) for u in links])
                db.execute("INSERT INTO scanned VALUES (?)", (surl,))
                db.commit()
                log.info("[%s] pierwsze uruchomienie – zapamiętano %d istniejących ofert", name, len(links))
                pause()
                continue

            log.info("[%s] %s: %d ofert, nowych %d", name, portal_of(surl), len(links), len(new))
            for u in new[:max_new]:
                db.execute("INSERT OR IGNORE INTO seen VALUES (?,?,?,?,0)", (offer_key(u), u, name, now))
                db.commit()
                pause()
                try:
                    o = parse_offer(u, fetch(u))
                except Exception as ex:
                    log.warning("Nie udało się otworzyć %s (%s) – wysyłam sam link", u, ex)
                    o = {"url": u, "portal": portal_of(u) or "", "title": "Nowa oferta (brak szczegółów)",
                         "desc": "", "price": None, "area": None, "rooms": None, "ppm2": None, "text": "", "core": "", "loc": ""}
                ok, why = passes(o, s.get("filters"))
                if ok:
                    send(cfg, offer_msg(o, name, (s.get("filters") or {}).get("highlight_any")))
                    db.execute("UPDATE seen SET sent=1 WHERE key=?", (offer_key(u),))
                    db.commit()
                    sent_total += 1
                    log.info("  ✓ wysłano: %s", o["title"][:80])
                else:
                    log.info("  ✗ odrzucono (%s): %s", why, o["title"][:80])
            pause()
    log.info("Koniec przebiegu, wysłano %d ofert.", sent_total)


def run_test(cfg):
    for s in cfg["searches"]:
        print(f"\n=== {s.get('name')} ===")
        for surl in s.get("urls") or []:
            print(f"\n{surl}")
            try:
                links = extract_links(surl, fetch(surl))
            except Exception as ex:
                print(f"  BŁĄD: {ex}")
                continue
            print(f"  znaleziono ofert: {len(links)}")
            for u in links[:3]:
                print(f"   - {u}")
            if links:
                pause(1, 2)
                try:
                    o = parse_offer(links[0], fetch(links[0]))
                    ok, why = passes(o, s.get("filters"))
                    print(f"  przykładowa oferta: {o['title'][:90]}")
                    print(f"    cena={fmt(o['price'])} metraż={fmt(o['area'])} "
                          f"zł/m²={fmt(o['ppm2'])} pokoje={fmt(o['rooms'])} -> filtr: {why}")
                except Exception as ex:
                    print(f"  nie udało się otworzyć oferty: {ex}")
            pause(1, 3)


def main():
    ap = argparse.ArgumentParser(description="Bot nieruchomości → Telegram")
    ap.add_argument("--once", action="store_true", help="jedno sprawdzenie i koniec")
    ap.add_argument("--test", action="store_true", help="podgląd bez wysyłania")
    ap.add_argument("--chat-id", action="store_true", help="pokaż chat_id")
    ap.add_argument("--test-telegram", action="store_true", help="wyślij wiadomość testową")
    ap.add_argument("--config", default=str(CONFIG_PATH))
    a = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler(BASE / "bot.log", encoding="utf-8")])
    with open(a.config, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh)
    # W chmurze (GitHub Actions) token i chat_id podajemy jako sekrety, nie w pliku.
    cfg.setdefault("telegram", {})
    if os.getenv("TELEGRAM_TOKEN"):
        cfg["telegram"]["token"] = os.getenv("TELEGRAM_TOKEN")
    if os.getenv("TELEGRAM_CHAT_ID"):
        cfg["telegram"]["chat_id"] = os.getenv("TELEGRAM_CHAT_ID")

    if a.chat_id:
        r = tg(cfg, "getUpdates", {})
        chats = {(u.get("message") or {}).get("chat", {}).get("id"): (u.get("message") or {}).get("chat", {})
                 for u in r.json().get("result", [])}
        chats.pop(None, None)
        if not chats:
            print("Brak wiadomości. Napisz cokolwiek do swojego bota na Telegramie i uruchom ponownie.")
        for cid, c in chats.items():
            print(f"chat_id: {cid}   ({c.get('first_name') or c.get('title')})")
        return
    if a.test_telegram:
        send(cfg, "✅ Bot nieruchomości działa i może wysyłać wiadomości.")
        print("Wysłano – sprawdź Telegram.")
        return
    if a.test:
        run_test(cfg)
        return

    db = db_open()
    if a.once:
        run_once(cfg, db)
        return
    interval = cfg.get("interval_minutes", 20)
    log.info("Start. Sprawdzam co ok. %d min. Ctrl+C kończy.", interval)
    while True:
        try:
            run_once(cfg, db)
        except Exception as ex:
            log.exception("Nieoczekiwany błąd: %s", ex)
        time.sleep(interval * 60 * random.uniform(0.8, 1.2))


if __name__ == "__main__":
    main()
