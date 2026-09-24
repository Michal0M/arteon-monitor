"""
Scraper pre bazos.sk / bazos.cz - vyhľadávanie a extrakcia inzerátov podľa config.py.

DÔLEŽITÉ POZNÁMKY Z REÁLNEHO OVEROVANIA ŠTRUKTÚRY STRÁNKY (24.9.2026):

1. Vyhľadávanie cez "krásnu" URL /inzeraty/<slovo>/ zobrazí len 1. stranu výsledkov.
   Akékoľvek ďalšie stránkovanie (aj z ich vlastného formulára) vedie cez
   query parametre hledat=/cenaod=/cenado=/order=/crp=, ktoré ich robots.txt
   pre všeobecných robotov zakazuje. Bez použitia týchto parametrov by sme
   nevedeli získať viac než ~20 najnovšie/TOP-ovaných inzerátov denne, čo je
   pre reálne sledovanie nepoužiteľné pokrytie.
   -> Tento scraper preto používa priamo query-parametrové vyhľadávanie.
   Toto je vedomé rozhodnutie (viď rozhovor s Michalom, 24.9.2026), nie prehliadnutie.

2. Fulltextové vyhľadávanie "arteon" vracia aj úplne iné modely (Golf, Tiguan) -
   filtrovanie podľa title v Pythone PO stiahnutí je nutné, nie voliteľné.

3. Na detail stránke inzerátu sa rovnaká CSS trieda '.inzeratycena' používa
   AJ v sekcii "Podobné inzeráty" na konci stránky. Skutočná cena inzerátu
   sa musí čítať z tabuľky s labelom "Cena:", nie prvým výskytom triedy.

4. Popis inzerátu NIE JE štruktúrovaný jednotne - niektorí predajcovia píšu
   "Motor: ... VIN: ... Farba: ..." riadky, iní súvislý text s emoji, iní
   tabuľku "Technické údaje". Extrakcia roku/km/farby je preto regex-based
   s viacerými pokusmi, nie spoliehanie sa na jednu štruktúru.

5. KRITICKÝ BUG (nájdený a opravený 24.9.2026): detail stránky obsahujú
   dole sekciu "Podobné inzeráty" s ÚPLNE INÝMI inzerátmi (iné autá, iné km,
   iné roky). Keď vlastný popis auta nesedel na žiadny regex vzor (napr. formát
   "Najazdených km: 226 000" namiesto "najazdené 226 000km"), extrakcia
   spadla späť na prvé číslo s "km" KDEKOĽVEK na stránke - čo bolo často
   z tej cudzej "Podobné inzeráty" sekcie. Výsledok: desiatky úplne odlišných
   áut mali v tabuľke identické km/rok (napr. "44079 km" - presne z jedného
   konkrétneho "podobného" inzerátu, ktorý bazos ukazoval ako súvisiaci na
   mnohých iných stránkach). Oprava: `own_ad_text()` orezáva text na všetko
   PRED nadpisom "Podobné inzeráty" a regex sa spúšťa len na tomto úseku.
"""

import json
import re
import time
import urllib.parse
from datetime import datetime

import requests
from bs4 import BeautifulSoup

import config
import db

HEADERS = {
    "User-Agent": config.USER_AGENT,
    "Accept-Language": "sk,cs;q=0.9,en;q=0.8",
}


def throttled_get(url: str) -> requests.Response:
    """GET request s throttlingom a rozumným error handlingom."""
    time.sleep(config.REQUEST_DELAY_SECONDS)
    resp = requests.get(url, headers=HEADERS, timeout=config.REQUEST_TIMEOUT_SECONDS)
    resp.raise_for_status()
    return resp


def build_search_url(source: dict, offset: int) -> str:
    """
    Zostaví vyhľadávaciu URL s query parametrami.
    Cenový filter posielame priamo v URL (server-side), aby sme nemuseli
    sťahovať a zahadzovať zjavne nerelevantné (príliš drahé/lacné) inzeráty.
    """
    price_min = config.PRICE_MIN
    price_max = config.PRICE_MAX
    if source["currency"] != config.CURRENCY_SK:
        # Pri CZ zdroji je cena v Kč - orientačný prepočet, aby server filter
        # zbytočne neorezal validné výsledky. Presné filtrovanie robíme
        # aj tak znova v Pythone po prepočte skutočnej ceny inzerátu.
        price_min = 0
        price_max = 999_999_999

    params = {
        "hledat": config.KEYWORD,
        "rubriky": "auto",
        "hlokalita": "",
        "humkreis": "25",
        "cenaod": price_min or "",
        "cenado": price_max or "",
        "Submit": "Hľadať",
        "order": "",
        "crp": str(offset),
        "kitx": "ano",
    }
    return f"{source['base_url']}/?{urllib.parse.urlencode(params)}"


def parse_price(text: str) -> float | None:
    """'  27 799 €' / '599 900 Kč' -> 27799.0 / 599900.0. 'Dohodou' -> None."""
    if not text:
        return None
    digits = re.sub(r"[^\d]", "", text)
    return float(digits) if digits else None


def extract_listing_id(href: str) -> str | None:
    m = re.search(r"/inzerat/(\d+)/", href)
    return m.group(1) if m else None


def parse_search_results(html: str, source: dict) -> list[dict]:
    """Vráti zoznam surových kandidátov zo stránky výsledkov vyhľadávania."""
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for block in soup.select("div.inzeraty.inzeratyflex"):
        link_el = block.select_one("h2.nadpis a")
        if not link_el:
            continue
        href = link_el.get("href", "")
        listing_id = extract_listing_id(href)
        if not listing_id:
            continue

        title = link_el.get_text(strip=True)
        price_el = block.select_one("div.inzeratycena")
        price = parse_price(price_el.get_text() if price_el else "")

        photo_el = block.select_one("div.inzeratynadpis img")
        photo_url = photo_el.get("src") if photo_el else None

        loc_el = block.select_one("div.inzeratylok")
        location = loc_el.get_text(" ", strip=True) if loc_el else None

        desc_el = block.select_one("div.popis")
        snippet = desc_el.get_text(" ", strip=True) if desc_el else ""

        full_url = urllib.parse.urljoin(source["base_url"], href)

        results.append({
            "id": f"{source['name']}_{listing_id}",
            "raw_id": listing_id,
            "source": source["name"],
            "url": full_url,
            "title": title,
            "list_price": price,
            "main_photo_url": photo_url,
            "location": location,
            "snippet": snippet,
        })
    return results


def find_exclusion_reason(text_lower: str) -> str | None:
    """
    Skontroluje text (title+snippet, alebo neskôr celý vlastný popis) proti
    všetkým EXCLUDE_* zoznamom z config.py. Vráti dôvod vylúčenia (na logovanie)
    alebo None, ak nič nesedí.
    """
    for frag in config.EXCLUDE_FUEL_CONTAINS:
        if frag in text_lower:
            return f"motor obsahuje '{frag}'"
    for frag in config.EXCLUDE_BODY_STYLE_CONTAINS:
        if frag in text_lower:
            return f"karoséria obsahuje '{frag}'"
    for pat in config.EXCLUDE_BODY_STYLE_REGEX:
        if re.search(pat, text_lower, re.IGNORECASE):
            return f"karoséria sedí na vzor '{pat}'"
    for frag in config.EXCLUDE_COLOR_FRAGMENTS:
        if frag in text_lower:
            return f"farba obsahuje '{frag}'"
    return None


def title_matches_criteria(title: str, snippet: str) -> bool:
    """
    Prvý hrubý filter (z výsledkov vyhľadávania, PRED stiahnutím detailu) -
    musí obsahovať kľúčové slovo (napr. 'arteon') A aspoň jeden z
    REQUIRE_TITLE_CONTAINS variantov (napr. 'r-line'), hľadané v title aj
    v krátkom náhľade popisu (R-Line je často len v popise, nie v nadpise).
    Zároveň nesmie sedieť na žiadny EXCLUDE_* vzor (motor/karoséria/farba) -
    toto je len rýchly predbežný filter, detail sa ešte raz overí po stiahnutí
    (find_exclusion_reason na own_ad_text), lebo title/snippet nemusí vždy
    obsahovať všetky detaily.
    """
    combined = f"{title} {snippet}".lower()
    if config.KEYWORD.lower() not in combined:
        return False
    if config.REQUIRE_TITLE_CONTAINS and not any(
        variant.lower() in combined for variant in config.REQUIRE_TITLE_CONTAINS
    ):
        return False
    if find_exclusion_reason(combined):
        return False
    return True


def extract_detail_price(soup: BeautifulSoup) -> float | None:
    """
    Skutočná cena je v riadku tabuľky s labelom 'Cena:'. NEPOUŽÍVAME prvý
    výskyt '.inzeratycena' - ten sa opakuje aj v sekcii Podobné inzeráty.
    """
    for td in soup.find_all("td"):
        if td.get_text(strip=True) == "Cena:":
            next_td = td.find_next_sibling("td")
            if next_td:
                return parse_price(next_td.get_text())
    return None


def extract_year(text: str) -> int | None:
    """Skúša viacero bežných formátov: 'rok výroby 11/2020, model 2021', 'r.v.: 9/2022', 'Vyrobeno: 2017'."""
    patterns = [
        r"model\s+(20\d{2})",
        r"r\.?v\.?\s*:?\s*\d{1,2}\s*/\s*(20\d{2})",
        r"rok\s+výroby\D{0,10}(20\d{2})",
        r"rok\s+vyroby\D{0,10}(20\d{2})",
        r"vyrobeno\s*:?\s*(20\d{2})",
        # "Rok výroby: 17.10.2017" - celý dátum d.m.rrrr formát
        r"\d{1,2}\.\d{1,2}\.(20\d{2})",
        r"\b\d{1,2}/(20\d{2})\b",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            year = int(m.group(1))
            if 2000 <= year <= datetime.now().year + 1:
                return year
    return None


def extract_km(text: str) -> int | None:
    # Niektorí predajcovia schválne zahmlievajú presné km písmenom "x" namiesto
    # číslic (napr. "66xxx km" = 66 000-66 999, "200 xxx km" = 200 000-200 999).
    # Toto sa musí skúsiť PRED bežnými číselnými vzormi nižšie, lebo tie na "x"
    # vôbec nereagujú a inak by to vôbec nič nenašli (auto by vypadlo z výsledkov,
    # namiesto aby sme použili aspoň orientačný odhad).
    m = re.search(r"(\d{1,3})\s?([xX]{2,5})\s*km", text)
    if m:
        estimated = int(m.group(1) + "0" * len(m.group(2)))  # dolný odhad rozsahu
        if 100 <= estimated <= 900_000:
            return estimated

    patterns = [
        # "najazdené 117 354km" / "najazdených ... 226 000 km" (číslo PRED "km")
        r"najazden\w*\D{0,15}?([\d\s]{3,7})\s*km",
        # "Najazdených km: 226 000" (label "km" PRED číslom, žiadna jednotka za ním -
        # bežný formát štruktúrovaných VW inzerátov, pôvodné vzory toto nechytali vôbec)
        r"najazden\w*\s*km\D{0,10}([\d\s]{3,7})",
        r"nájazd\D{0,10}?([\d\s]{3,7})\s*km",
        r"stav\s+tachometr\w*\D{0,10}?([\d\s]{3,7})\s*km",
        r"([\d\s]{3,7})\s*km",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            digits = re.sub(r"[^\d]", "", m.group(1))
            if digits and 100 <= int(digits) <= 900_000:
                return int(digits)
    return None


def extract_color(text: str) -> str | None:
    text_lower = text.lower()
    # Priorita: hodnota priamo pri labeli "Farba:" je oveľa spoľahlivejšia než
    # hľadanie farebného slova kdekoľvek v texte (kde môže ísť napr. o farbu
    # ambientného osvetlenia, nie karosérie).
    m = re.search(r"farba\s*:?\s*([a-zA-ZáäčďéíľňóôŕšťúýžÁÄČĎÉÍĽŇÓÔŔŠŤÚÝŽ/ -]{2,30})", text)
    if m:
        label_value = m.group(1).lower()
        for color_fragment in config.COLORS:
            if color_fragment in label_value:
                return color_fragment
    for color_fragment in config.COLORS:
        if color_fragment in text_lower:
            return color_fragment
    return None


def own_ad_text(body_text: str) -> str:
    """
    Oreže celý textový obsah stránky len na vlastný inzerát - všetko
    OD nadpisu "Podobné inzeráty" ĎALEJ sú iné, cudzie inzeráty, ktorých
    km/rok/farba/motor by inak kontaminovali extrakciu (viď bug #5 v hlavičke
    súboru). Ak marker nenájde (iný layout stránky), vráti celý text - radšej
    nefiltrovať nič, než niečo uřezať zle.
    """
    marker = "Podobné inzeráty"
    idx = body_text.find(marker)
    return body_text[:idx] if idx != -1 else body_text


def parse_detail_page(html: str, image_base_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    # Hlavný text popisu - berieme celý textový obsah stránky (jednoduchšie
    # a spoľahlivejšie než hádať presnú CSS triedu, ktorá sa medzi inzerátmi líši),
    # ale extrakcia beží LEN na own_ad_text() časti - viď own_ad_text() vyššie.
    body_text = soup.get_text("\n", strip=True)
    own_text = own_ad_text(body_text)

    # POZNÁMKA: Veľa fotiek je na stránke lazy-loaded (nie sú v atribúte src,
    # ale v JS/inom atribúte) - hľadanie len cez <img src=...> ich väčšinu
    # vynechá (overené: 3 z 22 reálnych). Regex nad celým HTML je spoľahlivejší.
    photo_paths = set(re.findall(r"/img/\d+/\d+/\d+\.jpg", html))
    photos = [f"{image_base_url}{p}" for p in photo_paths]

    return {
        "description_raw": own_text[:4000],  # orezané, nech DB nepuchne
        "detail_price": extract_detail_price(soup),
        "year_built": extract_year(own_text),
        "km": extract_km(own_text),
        "color_guess": extract_color(own_text),
        "all_photo_urls": json.dumps(sorted(set(photos))[:20]),
    }


def to_eur_estimate(price: float | None, currency: str) -> float | None:
    if price is None:
        return None
    if currency == config.CURRENCY_SK:
        return price
    if currency == config.CURRENCY_CZ:
        # ORIENTAČNÝ prepočet CZK->EUR. Kurz sa mení - uprav CZK_TO_EUR_RATE
        # v config.py podľa aktuálneho kurzu, ak chceš presnejšie porovnanie.
        return round(price * config.CZK_TO_EUR_RATE, 0)
    return price


def run_source(source: dict, conn) -> dict:
    """Spracuje jeden zdroj (bazos_sk / bazos_cz). Vráti štatistiky behu."""
    stats = {"new": 0, "price_changed": 0, "unchanged": 0, "skipped_criteria": 0, "sold": 0}
    seen_ids = set()

    for page_num in range(config.MAX_PAGES_PER_SOURCE):
        offset = page_num * 20
        search_url = build_search_url(source, offset)
        print(f"[{source['name']}] Sťahujem stránku {page_num + 1} ({search_url})")

        try:
            resp = throttled_get(search_url)
        except requests.RequestException as e:
            print(f"[{source['name']}] CHYBA pri sťahovaní: {e}")
            break

        candidates = parse_search_results(resp.text, source)
        if not candidates:
            print(f"[{source['name']}] Žiadne ďalšie výsledky, koniec stránkovania.")
            break

        for candidate in candidates:
            if not title_matches_criteria(candidate["title"], candidate["snippet"]):
                stats["skipped_criteria"] += 1
                continue

            # Hrubý cenový filter už z listu (šetrí zbytočný detail request)
            list_price_eur = to_eur_estimate(candidate["list_price"], source["currency"])
            if list_price_eur is not None:
                if list_price_eur < config.PRICE_MIN * 0.85 or list_price_eur > config.PRICE_MAX * 1.15:
                    # tolerancia +-15%, presný filter urobíme až po detail parse
                    stats["skipped_criteria"] += 1
                    continue

            try:
                detail_resp = throttled_get(candidate["url"])
            except requests.RequestException as e:
                print(f"[{source['name']}] Nepodarilo sa načítať detail {candidate['url']}: {e}")
                continue

            detail = parse_detail_page(detail_resp.text, source["image_base_url"])

            # Druhé kolo EXCLUDE kontroly na CELOM vlastnom texte inzerátu (nielen
            # title+snippet ako v title_matches_criteria) - motor/karoséria/farba
            # sa často spomína až v detaile, nie v krátkom náhľade z výpisu.
            own_text_lower = f"{candidate['title']} {detail['description_raw']}".lower()
            exclusion_reason = find_exclusion_reason(own_text_lower)
            if exclusion_reason:
                print(f"[{source['name']}] VYLÚČENÉ ({exclusion_reason}): {candidate['title']}")
                stats["skipped_criteria"] += 1
                continue

            final_price = detail["detail_price"] or candidate["list_price"]
            price_eur = to_eur_estimate(final_price, source["currency"])

            # Finálne tvrdé filtre podľa config.py
            if price_eur is None or not (config.PRICE_MIN <= price_eur <= config.PRICE_MAX):
                stats["skipped_criteria"] += 1
                continue
            if detail["km"] is not None and not (config.KM_MIN <= detail["km"] <= config.KM_MAX):
                stats["skipped_criteria"] += 1
                continue
            if detail["year_built"] is not None and detail["year_built"] < config.YEAR_MIN:
                stats["skipped_criteria"] += 1
                continue

            needs_check = (
                detail["year_built"] is None
                or detail["year_built"] < config.FACELIFT_CHECK_YEAR_THRESHOLD
            )

            listing = {
                "id": candidate["id"],
                "source": source["name"],
                "url": candidate["url"],
                "title": candidate["title"],
                "description_raw": detail["description_raw"],
                "current_price": final_price,
                "currency": source["currency"],
                "price_eur_est": price_eur,
                "year_built": detail["year_built"],
                "km": detail["km"],
                "color_guess": detail["color_guess"],
                "location": candidate["location"],
                "main_photo_url": candidate["main_photo_url"],
                "all_photo_urls": detail["all_photo_urls"],
                "needs_photo_check": needs_check,
            }

            result = db.upsert_listing(conn, listing)
            stats[result] = stats.get(result, 0) + 1
            seen_ids.add(candidate["id"])
            print(f"[{source['name']}] {result.upper()}: {candidate['title']} - {final_price} {source['currency']}")

        if len(candidates) < 20:
            break  # posledná stránka

    removed = db.mark_missing_as_sold(conn, seen_ids, source["name"])
    stats["sold"] = len(removed)
    return stats


def main():
    db.init_db(config.DB_PATH)
    with db.connect(config.DB_PATH) as conn:
        for source in config.SOURCES:
            print(f"\n=== Zdroj: {source['name']} ===")
            stats = run_source(source, conn)
            print(f"[{source['name']}] Súhrn: {stats}")


if __name__ == "__main__":
    main()
