"""
Scraper pre autobazar.sk - DRUHÝ zdroj popri bazos.sk/cz (scraper.py).

DÔLEŽITÉ ROZDIELY OPROTI BAZOSU (zistené prieskumom 24.9.2026):

1. Vyhľadávanie beží cez SUBDOMÉNU tvaru "znacka-model.autobazar.sk"
   (napr. https://volkswagen-arteon.autobazar.sk/), NIE cez query parametre
   ako na bazoši. Stránkovanie je "?p[page]=N". URL je nastavená v
   config.AUTOBAZAR_SEARCH_URL.

2. VEĽKÁ VÝHODA oproti bazošu: rok výroby, km, cena, palivo, karoséria aj
   farba sú na detail stránke ŠTRUKTÚROVANÉ polia s PEVNÝM labelom, ktorý
   generuje šablóna stránky ("Rok výroby:", "Najazdené:", "Palivo:",
   "Karoséria:", "Farba:") - nie voľný text, ktorý si každý predajca píše
   po svojom. Vďaka tomu extrakcia roku/km nepotrebuje desiatky regex
   variantov ako na bazoši - stačí jeden spoľahlivý vzor na label.

3. RIZIKO - NEOVERENÉ V PRODUKCII (dôležité, prečítaj si to): stránka má
   aktívnu F5/TSPD ochranu proti botom (pri každom načítaní vidno desiatky
   requestov na /TSPD/...). Nepodarilo sa mi overiť, či jednoduchý
   `requests.get()` (rovnaký prístup ako pri bazoši, ktorý tam funguje bez
   problémov) dostane reálny obsah, alebo len JS-challenge stránku bez dát.
   Toto sa dá spoľahlivo zistiť len reálnym behom - ak run() opakovane
   hlási "0 inzerátov nájdených" aj keď na stránke reálne inzeráty sú,
   znamená to, že nás TSPD blokuje a treba iný prístup (napr. headless
   prehliadač namiesto requests - výrazne väčšia zmena).

4. Fotky: NEPODARILO sa mi spoľahlivo zistiť skutočný formát URL fotiek
   (galéria sa dohráva cez API volania, ktoré sa v dostupnom network logu
   stratili v TSPD šume). `all_photo_urls`/`main_photo_url` preto zatiaľ
   ostávajú prázdne - dashboard to zvláda bez pádu (karta bez fotky).
   TODO: doplniť, keď budeme mať k dispozícii reálne stiahnuté HTML.

5. VIN: dealerské inzeráty (autobazár ako firma) VIN v štruktúrovanom poli
   nezobrazujú. Súkromné inzeráty ho môžu mať vo voľnom texte poznámky -
   používa sa rovnaká extract_vin() funkcia ako v scraper.py (import).
"""

import re
import time
from datetime import datetime

import requests
from bs4 import BeautifulSoup

import config
import db
import scraper  # zdieľame extract_vin() - VIN sa hľadá rovnako ako na bazoši

SOURCE_NAME = "autobazar_sk"

# Regex priamo na SUROVÉ HTML (nie CSS selektory) - zámerné rozhodnutie.
# Nepodarilo sa mi bezpečne overiť presné CSS triedy kariet vo výsledkoch
# vyhľadávania (viď hlavička súboru - nástroje na kontrolu mi vracali len
# accessibility-tree text, nie surové HTML so class atribútmi). Tvar detail
# URL (https://www.autobazar.sk/<id>/<slug>/) je ale na stránke konzistentný
# a dá sa spoľahlivo vytiahnuť aj bez CSS - nezávisí to od toho, aký layout
# karty použijú.
DETAIL_URL_RE = re.compile(r'href="(https://www\.autobazar\.sk/(\d+)/[^"]+/)"')

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
    base = config.AUTOBAZAR_SEARCH_URL
    return base if page == 1 else f"{base}?p[page]={page}"


def extract_detail_urls(html: str) -> list[tuple[str, str]]:
    """
    Vráti zoznam (url, id) unikátnych detail-inzerátov nájdených v HTML.

    POZOR (bug nájdený 24.9.2026 pri prvom reálnom behu): `seen` je interne
    {id: url} kvôli deduplikácii podľa id, ale von sa MUSÍ vracať v poradí
    (url, id) - presne v tomto poradí to očakáva run() nižšie. Pôvodná verzia
    vracala `list(seen.items())`, čo je (id, url) - opačne, než hovorí tento
    docstring aj kód v run(). Výsledok: run() si pomýlil url a id a poslal
    do requests.get() holé číslo namiesto URL ("Invalid URL '28435138': No
    scheme supplied").
    """
    seen: dict[str, str] = {}
    for m in DETAIL_URL_RE.finditer(html):
        url, listing_id = m.group(1), m.group(2)
        seen[listing_id] = url
    return [(url, listing_id) for listing_id, url in seen.items()]


def own_ad_text(body_text: str) -> str:
    """
    Oreže text po 'ĎALŠIE INZERÁTY PREDAJCU' - to sú iné, cudzie inzeráty
    toho istého predajcu a mohli by kontaminovať extrakciu, rovnaký princíp
    ako own_ad_text() v scraper.py pre bazošovú sekciu "Podobné inzeráty"
    (tento bug nás už raz stál veľa času, tak sa mu radšej vyhneme rovno).
    """
    end_marker = "ĎALŠIE INZERÁTY PREDAJCU"
    idx = body_text.find(end_marker)
    return body_text[:idx] if idx != -1 else body_text


def extract_price(text: str) -> float | None:
    """Prvá cena v € na stránke - to je vždy predajná cena inzerátu (nie
    'Registračný poplatok', ten je vždy AŽ ZA ňou v texte)."""
    m = re.search(r"([\d\s]{4,7})\s*€", text)
    if m:
        digits = re.sub(r"[^\d]", "", m.group(1))
        return float(digits) if digits else None
    return None


def extract_year(text: str) -> int | None:
    """Štruktúrovaný label 'Rok výroby:' - napr. 'Rok výroby: 10/2021'."""
    m = re.search(r"Rok\s+výroby:\s*(?:\d{1,2}\s*/\s*)?(\d{4})", text, re.IGNORECASE)
    if m:
        year = int(m.group(1))
        if 2000 <= year <= datetime.now().year + 1:
            return year
    return None


def extract_km(text: str) -> int | None:
    """Štruktúrovaný label 'Najazdené:' - napr. 'Najazdené: 80 092 km'."""
    m = re.search(r"Najazden[éeí]:?\s*([\d\s]{3,7})\s*km", text, re.IGNORECASE)
    if m:
        digits = re.sub(r"[^\d]", "", m.group(1))
        if digits:
            return int(digits)
    return None


def extract_fuel(text: str) -> str | None:
    m = re.search(r"Palivo:\s*([^\n]+)", text, re.IGNORECASE)
    return m.group(1).strip() if m else None


def extract_body_style(text: str) -> str | None:
    m = re.search(r"Karoséria:\s*([^\n]+)", text, re.IGNORECASE)
    return m.group(1).strip() if m else None


def extract_color(text: str) -> str | None:
    """Farebná paleta config.COLORS (preferované) AJ config.SECONDARY_COLOR_FRAGMENTS
    (červená/modrá - od 24.9.2026 mäkký filter, nie vymazanie, viď config.py),
    hľadaná LEN v hodnote štruktúrovaného poľa 'Farba:' - presnejšie než skenovanie
    celého textu (na tejto stránke to ani nie je treba, lebo pole existuje)."""
    m = re.search(r"Farba:\s*([^\n]+)", text, re.IGNORECASE)
    if not m:
        return None
    value_lower = m.group(1).strip().lower()
    for color_fragment in config.COLORS + config.SECONDARY_COLOR_FRAGMENTS:
        if color_fragment in value_lower:
            return color_fragment
    return None


def matches_criteria(own_text: str, title: str) -> str | None:
    """
    Vráti dôvod vylúčenia (text na logovanie) alebo None, ak inzerát sedí.

    POZOR: farba sa TU už nekontroluje - od 24.9.2026 je to mäkký filter
    (viď config.py), inzerát sa nevymaže, len sa v render.py zaradí do
    samostatnej kategórie cez listing["is_secondary_color"].
    """
    combined_lower = f"{title} {own_text}".lower()

    if config.REQUIRE_TITLE_CONTAINS and not any(
        variant.lower() in combined_lower for variant in config.REQUIRE_TITLE_CONTAINS
    ):
        return "chýba R-Line v title/texte"

    fuel_lower = (extract_fuel(own_text) or "").lower()
    for frag in config.EXCLUDE_FUEL_CONTAINS:
        if frag in fuel_lower or frag in combined_lower:
            return f"motor obsahuje '{frag}'"
    for pat in config.EXCLUDE_ENGINE_REGEX:
        if re.search(pat, combined_lower, re.IGNORECASE):
            return f"motor sedí na vzor '{pat}' (1.5 TSI - nechceme)"

    body_lower = (extract_body_style(own_text) or "").lower()
    for frag in config.EXCLUDE_BODY_STYLE_CONTAINS:
        if frag in body_lower or frag in combined_lower:
            return f"karoséria obsahuje '{frag}'"
    for pat in config.EXCLUDE_BODY_STYLE_REGEX:
        if re.search(pat, combined_lower, re.IGNORECASE):
            return f"karoséria sedí na vzor '{pat}'"

    return None


_DEBUG_PHOTO_PRINTS_LEFT = 3  # dočasné - vypni/zmaž po tom, čo nájdeme fotky (viď TODO bod 4 v hlavičke)


def _debug_print_image_urls(html: str, listing_id: str) -> None:
    """
    DOČASNÉ (24.9.2026): keďže sa nepodarilo zistiť formát URL fotiek cez
    interaktívne prehliadačové nástroje (network log ich nezachytil, JS
    injection v danej session nefungoval), skúšame to najspoľahlivejšie -
    priamo na surovom HTML, ktoré scraper reálne stiahne cez requests.get()
    (na rozdiel od interaktívneho prehliadača tu nič neblokuje TSPD ani iná
    ochrana - to je už overené produkčne). Vypíše prvých pár nájdených
    obrázkových URL do GitHub Actions logu pre prvé 3 spracované inzeráty,
    aby sme videli skutočný formát a mohli ho zakódovať do parse_detail_page().
    Po vyriešení fotiek túto funkciu aj jej volanie v run() ZMAZAŤ.
    """
    global _DEBUG_PHOTO_PRINTS_LEFT
    if _DEBUG_PHOTO_PRINTS_LEFT <= 0:
        return

    # Kolo 1 (prvý pokus - NEUSPEŠNÉ): hľadanie čistých "https://...jpg" URL
    # v surovom HTML nenašlo nič relevantné, len 2 statické ikonky webu na
    # inzerát (logo, ikonka splátok) - žiadne fotky auta. To znamená, že
    # skutočné URL fotiek buď (a) nie sú v statickom HTML vôbec (JS/API
    # dohráva galériu po načítaní), alebo (b) SÚ v HTML, ale v inom tvare,
    # než "https://" - napr. JSON s escapovanými lomkami "https:\/\/...",
    # cesta bez protokolu "//cdn.../x.jpg", alebo v <script type="application/ld+json">.
    #
    # Kolo 2 (toto): namiesto hádania presného tvaru URL len vypíšeme SUROVÝ
    # KONTEXT okolo každého výskytu prípony obrázku (.jpg/.jpeg/.webp/.png)
    # kdekoľvek v HTML - nech vidíme skutočný tvar (escapovanie, protokol,
    # doménu) a podľa toho napíšeme presný regex.
    ext_positions = [m.start() for m in re.finditer(r"\.(?:jpg|jpeg|webp|png)", html, re.IGNORECASE)]
    print(f"[{SOURCE_NAME}] DEBUG FOTKY kolo 2 (inzerát {listing_id}) - {len(ext_positions)} výskytov prípony obrázku, kontext okolo prvých 12:")
    for pos in ext_positions[:12]:
        start = max(0, pos - 90)
        end = min(len(html), pos + 10)
        snippet = html[start:end].replace("\n", " ").replace("\r", " ")
        print(f"    ...{snippet}...")
    _DEBUG_PHOTO_PRINTS_LEFT -= 1


def parse_detail_page(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    body_text = soup.get_text("\n", strip=True)
    own_text = own_ad_text(body_text)

    title = soup.title.string.strip() if soup.title and soup.title.string else ""
    title = re.sub(r"\s*\|\s*Autobazar\.sk\s*$", "", title, flags=re.IGNORECASE)

    return {
        "title": title,
        "description_raw": own_text[:4000],
        "detail_price": extract_price(own_text),
        "year_built": extract_year(own_text),
        "km": extract_km(own_text),
        "color_guess": extract_color(own_text),
        "is_secondary_color": scraper.is_secondary_color(extract_color(own_text)),
        "vin": scraper.extract_vin(own_text),
        # TODO fotky - viď bod 4 v hlavičke súboru
        "all_photo_urls": "[]",
        "main_photo_url": None,
    }


def run(conn) -> dict:
    """Spracuje autobazar.sk. Vráti rovnaký typ štatistík ako scraper.run_source."""
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
        new_on_page = [(u, i) for u, i in found if i not in all_detail]
        if not new_on_page:
            print(f"[{SOURCE_NAME}] Žiadne nové inzeráty na tejto stránke, koniec stránkovania.")
            break
        for url, listing_id in new_on_page:
            all_detail[listing_id] = url

    if not all_detail:
        print(
            f"[{SOURCE_NAME}] POZOR: 0 inzerátov nájdených na vyhľadávacej stránke "
            f"({config.AUTOBAZAR_SEARCH_URL}). Buď model naozaj nemá inzeráty, ALEBO "
            f"nás blokuje TSPD bot-ochrana (viď bod 3 v hlavičke súboru) - over si to "
            f"ručne v prehliadači, či tam inzeráty reálne sú."
        )

    for listing_id, url in all_detail.items():
        full_id = f"{SOURCE_NAME}_{listing_id}"
        try:
            detail_resp = throttled_get(url)
        except requests.RequestException as e:
            print(f"[{SOURCE_NAME}] Nepodarilo sa načítať detail {url}: {e}")
            continue

        _debug_print_image_urls(detail_resp.text, listing_id)  # DOČASNÉ - viď komentár pri funkcii
        detail = parse_detail_page(detail_resp.text)
        title = detail["title"] or url

        reason = matches_criteria(detail["description_raw"], title)
        if reason:
            print(f"[{SOURCE_NAME}] VYLÚČENÉ ({reason}): {title}")
            db.delete_listing(conn, full_id)
            stats["skipped_criteria"] += 1
            continue

        price_eur = detail["detail_price"]  # autobazar.sk ceny sú vždy v EUR
        if price_eur is None or not (config.PRICE_MIN <= price_eur <= config.PRICE_MAX):
            db.delete_listing(conn, full_id)
            stats["skipped_criteria"] += 1
            continue
        if detail["km"] is not None and not (config.KM_MIN <= detail["km"] <= config.KM_MAX):
            db.delete_listing(conn, full_id)
            stats["skipped_criteria"] += 1
            continue
        # POZOR: YEAR_MIN je rovnako ako v scraper.py MÄKKÝ filter - staršie autá
        # sa neodmietnu, len sa zobrazia pod "Staršie ako {YEAR_MIN}" v render.py.

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
