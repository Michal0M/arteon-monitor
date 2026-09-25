"""
Scraper pre aaaauto.sk - TRETÍ zdroj popri bazos.sk/cz (scraper.py) a
autobazar.sk (autobazar_scraper.py).

DÔLEŽITÉ ZISTENIA (prieskum 25.9.2026, cez interaktívny prehliadač):

1. Robots.txt (https://www.aaaauto.sk/robots.txt) blokuje len /garage/,
   /car/, /connect/, /payload-preview/, /modal-preview/, /admin-tools/,
   /landingpage/. Vyhľadávacia stránka (/ojazdene-vozidla/volkswagen/arteon/)
   AJ detail stránka (/detail/volkswagen/arteon/<id>) NIE SÚ v zozname -
   crawlovanie je pre oba typy stránok povolené.

2. Detail stránka má ŠTRUKTÚROVANÉ polia s pevným labelom (rovnaká výhoda
   ako autobazar.sk): "Registrácia" (rok), "Tachometer" (km), "Karoséria",
   "Farba", "VIN" (!) priamo ako pole, "Palivo", "Prevodovka", "Motor"
   (napr. "2.0 TDI", "1.5 TSI" - užitočné aj na 1.5 TSI hard-exclude).

3. POZOR na cenu: stránka ukazuje DVE ceny - "Cena" (skutočná hotovostná
   cena, napr. "12 000 €") a "Akciová cena na úver" (splátková/finančná
   cena cez úver, býva NIŽŠIA, napr. "10 500 €" pre to isté auto). Chceme
   VÝHRADNE "Cena" - extract_price() to rieši hľadaním labelu "Cena" ako
   izolovaného riadku (regex vyžaduje, aby za "Cena" nasledovala len
   medzera/nový riadok a potom cena - "Akciová cena na úver" tento vzor
   nesplní, lebo medzi "cena" a číslom je ešte text "na úver").

4. R-Line NIE JE samostatné štruktúrované pole (na rozdiel od autobazar.sk,
   kde tiež nie je, ale aspoň structured "Objem"/"Výkon" pomáhajú). Zisťuje
   sa rovnako ako na bazoši - z voľného textu (title + popis "Výhody
   vozidla"). Overené: časť áut R-Line v texte spomína, časť nie (asi nie
   všetky R-Line kusy majú R-Line explicitne v popise) - nedokonalé, ale
   rovnaký kompromis, aký už akceptujeme na bazoši.

5. Fotky: URL formát POTVRDENÝ priamo v DOM (document.documentElement.
   outerHTML.includes('vshcdn.net') === true, teda je to v serverovom HTML,
   nie len dogenerované JS po načítaní - na rozdiel od autobazar.sk, kde
   fotky v HTML vôbec nie sú):
   https://aaaautoeuimg.vshcdn.net/thumb/<číslo>_<šírka>x<výška>x<kvalita>.jpg

6. Rovnaký bug-vzor ako bug #5 v scraper.py (bazos) - na konci detail
   stránky je sekcia "Ďalšie odporúčané vozidlá" s inými autami, ktoré by
   mohli kontaminovať extrakciu (najmä ceny/km, keby fallback vzory zlyhali
   na vlastnom aute). own_ad_text() preto orezáva text PRED touto sekciou,
   preventívne, aj keď momentálne extrakcia beží na label-based vzoroch,
   ktoré by sa cudzej sekcie nemali dotknúť.

7. Stránkovanie: vyhľadávacia stránka má tlačidlo "Zobraziť viac" (možno
   client-side donačítanie) - NEOVERENÉ, či `?page=N` v URL reálne vracia
   ďalšie výsledky zo servera. Pre VW Arteon aktuálne úplne postačuje prvá
   strana (14 áut celkom, bežne pod limitom jednej stránky). Ak by počet
   niekedy prekročil to, čo vráti prvá strana, run() to nezachytí - toto je
   známe obmedzenie, TODO ak by bolo treba viac ako ~20-30 výsledkov.
"""

import json
import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

import config
import db
import scraper  # zdieľame extract_vin() a is_secondary_color()

SOURCE_NAME = "aaaauto_sk"

DETAIL_URL_RE = re.compile(r'href="(/detail/volkswagen/arteon/(\d+))[#"]')
PHOTO_URL_RE = re.compile(r"https://aaaautoeuimg\.vshcdn\.net/thumb/\d+_\d+x\d+x\d+\.jpg")

HEADERS = {
    "User-Agent": config.USER_AGENT,
    "Accept-Language": "sk,cs;q=0.9,en;q=0.8",
}


def throttled_get(url: str) -> requests.Response:
    time.sleep(config.REQUEST_DELAY_SECONDS)
    resp = requests.get(url, headers=HEADERS, timeout=config.REQUEST_TIMEOUT_SECONDS)
    resp.raise_for_status()
    return resp


def build_search_url(page: int) -> str:
    base = config.AAAAUTO_SEARCH_URL
    return base if page == 1 else f"{base}?page={page}"


def extract_detail_urls(html: str) -> list[tuple[str, str]]:
    """Vráti zoznam (url, id) unikátnych detail-inzerátov nájdených v HTML."""
    seen: dict[str, str] = {}
    for m in DETAIL_URL_RE.finditer(html):
        path, listing_id = m.group(1), m.group(2)
        seen[listing_id] = path
    return [(f"https://www.aaaauto.sk{path}", listing_id) for listing_id, path in seen.items()]


def own_ad_text(body_text: str) -> str:
    """Oreže text pred sekciou 'Ďalšie odporúčané vozidlá' - iné autá na
    konci detail stránky, ktoré by mohli kontaminovať extrakciu (rovnaký
    princíp ako bug #5/#6 v scraper.py pre bazoš)."""
    end_marker = "Ďalšie odporúčané vozidlá"
    idx = body_text.find(end_marker)
    return body_text[:idx] if idx != -1 else body_text


def extract_price(text: str) -> float | None:
    """Skutočná hotovostná cena (label 'Cena' ako izolovaný riadok) - NIE
    'Akciová cena na úver' (splátková, býva nižšia). Viď bod 3 v hlavičke."""
    m = re.search(r"\bCena\b\s*\n\s*([\d\s]{4,7})\s*€", text)
    if m:
        digits = re.sub(r"[^\d]", "", m.group(1))
        return float(digits) if digits else None
    return None


def extract_year(text: str) -> int | None:
    m = re.search(r"Registrácia\s*\n\s*(\d{4})", text, re.IGNORECASE)
    if m:
        year = int(m.group(1))
        if 2000 <= year <= datetime.now().year + 1:
            return year
    return None


def extract_km(text: str) -> int | None:
    m = re.search(r"Tachometer\s*\n\s*([\d\s]{3,7})\s*km", text, re.IGNORECASE)
    if m:
        digits = re.sub(r"[^\d]", "", m.group(1))
        if digits:
            return int(digits)
    return None


def extract_fuel(text: str) -> str | None:
    m = re.search(r"Palivo\s*\n\s*([^\n]+)", text, re.IGNORECASE)
    return m.group(1).strip() if m else None


def extract_body_style(text: str) -> str | None:
    m = re.search(r"Karoséria\s*\n\s*([^\n]+)", text, re.IGNORECASE)
    return m.group(1).strip() if m else None


def extract_engine(text: str) -> str | None:
    """
    Napr. '2.0 TDI', '1.5 TSI' - užitočné najmä na EXCLUDE_ENGINE_REGEX.

    POZOR: label "Motor" sa na stránke objavuje DVAKRÁT - raz ako nadpis
    sekcie (za ním hneď nasleduje "Palivo"), raz ako skutočné pole s
    hodnotou motora (napr. "Motor\\n2.0 TDI\\nVýkon..."). Berieme POSLEDNÝ
    výskyt s hodnotou, ktorá vyzerá ako motor (obsahuje číslicu), nie prvý.
    """
    matches = re.findall(r"\bMotor\s*\n\s*([^\n]+)", text, re.IGNORECASE)
    for value in reversed(matches):
        value = value.strip()
        if re.search(r"\d", value):
            return value
    return None


def extract_color(text: str) -> str | None:
    m = re.search(r"Farba\s*\n\s*([^\n]+)", text, re.IGNORECASE)
    if not m:
        return None
    value_lower = m.group(1).strip().lower()
    for color_fragment in config.COLORS + config.SECONDARY_COLOR_FRAGMENTS:
        if color_fragment in value_lower:
            return color_fragment
    return None


def extract_photos(html: str) -> list[str]:
    return sorted(set(PHOTO_URL_RE.findall(html)))[:20]


def matches_criteria(own_text: str, title: str) -> str | None:
    """Vráti dôvod vylúčenia (text na logovanie) alebo None, ak inzerát sedí.

    POZOR: farba sa TU nekontroluje - mäkký filter (viď config.py), inzerát
    sa nevymaže, len sa v render.py zaradí do samostatnej kategórie cez
    listing["is_secondary_color"]."""
    combined_lower = f"{title} {own_text}".lower()

    if config.REQUIRE_TITLE_CONTAINS and not any(
        variant.lower() in combined_lower for variant in config.REQUIRE_TITLE_CONTAINS
    ):
        return "chýba R-Line v title/texte"

    fuel_lower = (extract_fuel(own_text) or "").lower()
    for frag in config.EXCLUDE_FUEL_CONTAINS:
        if frag in fuel_lower or frag in combined_lower:
            return f"motor obsahuje '{frag}'"

    engine_lower = (extract_engine(own_text) or "").lower()
    for pat in config.EXCLUDE_ENGINE_REGEX:
        if re.search(pat, engine_lower, re.IGNORECASE) or re.search(pat, combined_lower, re.IGNORECASE):
            return f"motor sedí na vzor '{pat}' (1.5 TSI - nechceme)"

    body_lower = (extract_body_style(own_text) or "").lower()
    for frag in config.EXCLUDE_BODY_STYLE_CONTAINS:
        if frag in body_lower or frag in combined_lower:
            return f"karoséria obsahuje '{frag}'"
    for pat in config.EXCLUDE_BODY_STYLE_REGEX:
        if re.search(pat, combined_lower, re.IGNORECASE):
            return f"karoséria sedí na vzor '{pat}'"

    return None


def parse_detail_page(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    body_text = soup.get_text("\n", strip=True)
    own_text = own_ad_text(body_text)

    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    title = re.sub(r"\s*\|\s*Autobazar AAA AUTO\s*$", "", title, flags=re.IGNORECASE)

    color_guess = extract_color(own_text)
    photos = extract_photos(html)

    return {
        "title": title,
        "description_raw": own_text[:4000],
        "detail_price": extract_price(own_text),
        "year_built": extract_year(own_text),
        "km": extract_km(own_text),
        "color_guess": color_guess,
        "is_secondary_color": scraper.is_secondary_color(color_guess),
        "vin": scraper.extract_vin(own_text),
        "all_photo_urls": json.dumps(photos),
        "main_photo_url": photos[0] if photos else None,
    }


def run(conn) -> dict:
    """Spracuje aaaauto.sk. Vráti rovnaký typ štatistík ako scraper.run_source."""
    stats = {"new": 0, "price_changed": 0, "unchanged": 0, "skipped_criteria": 0, "sold": 0}
    seen_ids = set()
    all_detail: dict[str, str] = {}

    for page_num in range(1, config.MAX_PAGES_PER_SOURCE + 1):
        search_url = build_search_url(page_num)
        print(f"[{SOURCE_NAME}] Sťahujem stránku {page_num} ({search_url})")
        try:
            resp = throttled_get(search_url)
        except requests.RequestException as e:
            print(f"[{SOURCE_NAME}] CHYBA pri sťahovaní: {e}")
            break

        found = extract_detail_urls(resp.text)
        if page_num == 1 and not found:
            # DOČASNÉ (25.9.2026): prvý reálny beh vrátil 0 inzerátov - potrebujeme
            # zistiť PREČO priamo zo surového HTML, ktoré requests.get() reálne dostal
            # (rovnaký princíp ako debug pri fotkách na autobazar.sk - žiadne hádanie).
            html = resp.text
            print(f"[{SOURCE_NAME}] DEBUG: dĺžka stiahnutého HTML = {len(html)} znakov")
            print(f"[{SOURCE_NAME}] DEBUG: počet výskytov '/detail/' v HTML = {html.count('/detail/')}")
            print(f"[{SOURCE_NAME}] DEBUG: počet výskytov 'Arteon' v HTML = {html.count('Arteon')}")
            print(f"[{SOURCE_NAME}] DEBUG: prvých 1500 znakov HTML:\n{html[:1500]}")
        new_on_page = [(u, i) for u, i in found if i not in all_detail]
        if not new_on_page:
            print(f"[{SOURCE_NAME}] Žiadne nové inzeráty na tejto stránke, koniec stránkovania.")
            break
        for url, listing_id in new_on_page:
            all_detail[listing_id] = url

    if not all_detail:
        print(
            f"[{SOURCE_NAME}] POZOR: 0 inzerátov nájdených na vyhľadávacej stránke "
            f"({config.AAAAUTO_SEARCH_URL}). Over si ručne v prehliadači, či tam inzeráty reálne sú."
        )

    for listing_id, url in all_detail.items():
        full_id = f"{SOURCE_NAME}_{listing_id}"
        try:
            detail_resp = throttled_get(url)
        except requests.RequestException as e:
            print(f"[{SOURCE_NAME}] Nepodarilo sa načítať detail {url}: {e}")
            continue

        detail = parse_detail_page(detail_resp.text)
        title = detail["title"] or url

        reason = matches_criteria(detail["description_raw"], title)
        if reason:
            print(f"[{SOURCE_NAME}] VYLÚČENÉ ({reason}): {title}")
            db.delete_listing(conn, full_id)
            stats["skipped_criteria"] += 1
            continue

        price_eur = detail["detail_price"]  # aaaauto.sk ceny sú vždy v EUR
        if price_eur is None or not (config.PRICE_MIN <= price_eur <= config.PRICE_MAX):
            db.delete_listing(conn, full_id)
            stats["skipped_criteria"] += 1
            continue
        if detail["km"] is not None and not (config.KM_MIN <= detail["km"] <= config.KM_MAX):
            db.delete_listing(conn, full_id)
            stats["skipped_criteria"] += 1
            continue
        # POZOR: YEAR_MIN je MÄKKÝ filter (rovnako ako v scraper.py a
        # autobazar_scraper.py) - staršie autá sa neodmietnu, len sa
        # zobrazia pod "Staršie ako {YEAR_MIN}" v render.py.

        needs_check = (
            detail["year_built"] is None
            or detail["year_built"] < config.FACELIFT_CHECK_YEAR_THRESHOLD
        )

        listing = {
            "id": full_id,
            "source": SOURCE_NAME,
            "url": url,
            "title": title,
            "description_raw": detail["description_raw"],
            "current_price": price_eur,
            "currency": "EUR",
            "price_eur_est": price_eur,
            "year_built": detail["year_built"],
            "km": detail["km"],
            "color_guess": detail["color_guess"],
            "is_secondary_color": detail["is_secondary_color"],
            "vin": detail["vin"],
            "location": None,
            "main_photo_url": detail["main_photo_url"],
            "all_photo_urls": detail["all_photo_urls"],
            "needs_photo_check": needs_check,
        }

        result = db.upsert_listing(conn, listing)
        stats[result] = stats.get(result, 0) + 1
        seen_ids.add(full_id)
        print(f"[{SOURCE_NAME}] {result.upper()}: {title} - {price_eur} EUR")

    removed = db.mark_missing_as_sold(conn, seen_ids, SOURCE_NAME)
    stats["sold"] = len(removed)
    return stats


if __name__ == "__main__":
    db.init_db(config.DB_PATH)
    with db.connect(config.DB_PATH) as conn:
        result_stats = run(conn)
        print(f"[{SOURCE_NAME}] Súhrn: {result_stats}")
