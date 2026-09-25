# VW Arteon monitor

Denne prechádza bazos.sk a bazos.cz, hľadá VW Arteon R-Line podľa kritérií
v `config.py`, zapisuje ich do SQLite databázy s históriou cien a generuje
statickú HTML stránku (`docs/index.html`) publikovanú cez GitHub Pages.

## Dôležité upozornenie (prečítaj si pred spustením)

Vyhľadávanie na bazos.sk/cz beží cez query parametre (`hledat=`, `cenaod=`...),
ktoré ich `robots.txt` pre bežných robotov zakazuje. Toto je vedomé rozhodnutie
urobené po zvážení rizika (osobné použitie, nízky objem ~1x denne, throttling
medzi requestami) - nie prehliadnutie. Realistické riziko je dočasné/trvalé
zablokovanie IP adresy GitHub Actions runnera, nie právny problém. Ak sa to
stane, pozri sekciu "Čo robiť, ak to prestane fungovať" nižšie.

## Ako to funguje

1. **`scraper.py`** - stiahne výsledky vyhľadávania, vyfiltruje podľa
   `config.py` (kľúčové slovo, R-Line, cena, km, rok, farba), pre kandidátov
   stiahne aj detail inzerátu a extrahuje presné údaje. Zapíše/aktualizuje
   `data/listings.db`.
2. **`render.py`** - z databázy vygeneruje `docs/index.html` - kartičky
   s fotkou, cenou, históriou cien, a filtrami (aktívne/predané/všetky).
3. **GitHub Actions** (`.github/workflows/daily-scrape.yml`) - spúšťa oba
   skripty raz denne, výsledok commitne späť do repozitára.
4. **GitHub Pages** - servíruje `docs/index.html` ako verejnú (súkromnú, ak
   repo nastavíš ako private) webovú stránku.

## Prvotné nastavenie

1. Vytvor nový repozitár na GitHub (odporúčam **private**, aby tvoje
   sledovanie nebolo verejné).
2. Nahraj tento kód do repozitára:
   ```bash
   cd car-monitor
   git init
   git add .
   git commit -m "Prvotný commit: VW Arteon monitor"
   git branch -M main
   git remote add origin https://github.com/<tvoj-username>/<repo-nazov>.git
   git push -u origin main
   ```
3. V nastaveniach repozitára (Settings → Pages) nastav:
   - Source: **Deploy from a branch**
   - Branch: **main**, priečinok: **/docs**
4. V nastaveniach repozitára (Settings → Actions → General → Workflow
   permissions) over, že je zapnuté **"Read and write permissions"** - inak
   workflow nebude môcť commitnúť výsledky späť.
5. Počkaj na prvý plánovaný beh (6:00 UTC), alebo ho spusti ručne:
   tab **Actions** → **Denný scrape VW Arteon inzerátov** → **Run workflow**.
6. Stránka bude dostupná na `https://<tvoj-username>.github.io/<repo-nazov>/`
   (presný odkaz nájdeš aj v Settings → Pages po prvom úspešnom deploy).

## Úprava kritérií vyhľadávania

Všetko je v `config.py`:
- `KEYWORD` - kľúčové slovo (napr. iný model auta)
- `REQUIRE_TITLE_CONTAINS` - povinné výrazy (napr. "r-line")
- `PRICE_MIN` / `PRICE_MAX`, `KM_MIN` / `KM_MAX`, `YEAR_MIN`
- `COLORS` - zoznam preferovaných farieb, ktoré sa zobrazujú v tabuľke (len na display, neexkludujú nič)
- `SECONDARY_COLOR_FRAGMENTS` - farby, ktoré NIE sú prvá voľba (červená, modrá) - MÄKKÝ filter,
  inzerát sa nevymaže, len sa zobrazí pod samostatnou kategóriou "Červené/Modré" (rovnaký princíp ako `YEAR_MIN`)
- `EXCLUDE_BODY_STYLE_CONTAINS` / `EXCLUDE_BODY_STYLE_REGEX` - karoséria, ktorú nechceme (napr. Shooting Brake/kombi)
- `EXCLUDE_FUEL_CONTAINS` - motor/palivo, ktoré nechceme (napr. TDI, chceme len TSI benzín)
- `EXCLUDE_ENGINE_REGEX` - motorové varianty, ktoré nechceme (napr. 1.5 TSI - tvrdý filter)
- `CZK_TO_EUR_RATE` - over si aktuálny kurz, tento je len orientačný

Po úprave stačí commitnúť a pushnúť - ďalší denný beh použije nové kritériá.

## Čo robiť, ak to prestane fungovať

Scraping statických stránok sa časom pokazí - to je normálne, nie chyba
tohto kódu. Bežné príčiny a čo robiť:

- **Workflow zlyhá s chybou pri sťahovaní (403/429/timeout)** → GitHub
  Actions IP mohla byť dočasne zablokovaná. Skús spustiť ručne o pár hodín
  neskôr. Ak sa to opakuje trvalo, zváž presun scrapera na lokálne
  spúšťanie (Task Scheduler na tvojom PC) - tam máš stabilnú domácu IP.
- **Workflow prebehne, ale nájde 0 inzerátov** → štruktúra stránky sa
  pravdepodobne zmenila (zmenili CSS triedy). Treba znova overiť HTML
  štruktúru (rovnaký postup, akým sme to robili pri stavbe - cez prehliadač,
  `document.querySelector`) a upraviť selektory v `scraper.py`
  (funkcie `parse_search_results` a `parse_detail_page`).
- **Ceny/roky/km vychádzajú nezmyselne** → extrakcia z voľného textu
  (`extract_year`, `extract_km`, `extract_color` v `scraper.py`) je
  regex-based a nepokrýva úplne každý formát popisu. Priebežne dopĺňaj
  vzory podľa toho, čo sa v praxi objaví.

## História cien a "za koľko sa predalo"

Databáza nikdy neprepisuje staré ceny - každá zmena ceny sa pridá ako nový
riadok do `price_history`, pôvodné zostávajú. Keď inzerát zmizne (predané/
stiahnuté), zostáva viditeľný v tabuľke (filter "Predané") aj so všetkými
detailmi (km, rok, farba, fotky) a jeho **poslednou inzerovanou cenou pred
stiahnutím** - to je najbližšia dostupná informácia k reálnej predajnej cene,
ktorú vieme zo statického inzerátu získať. Skutočná dohodnutá cena (po
prípadnom zjednávaní na mieste) sa nedá zistiť automaticky - bazos ju nikde
nezverejňuje.

## Detekcia duplicitných VIN (podozrenie na klon inzerátu)

Ak sa v texte inzerátu nájde VIN (pri labeli "VIN:"), uloží sa a porovnáva
naprieč VŠETKÝMI inzerátmi v databáze (aj naprieč zdrojmi - pripravené aj na
budúce ďalšie stránky, nie len bazos.sk/cz). Ak má inzerát rovnaké VIN ako
iný inzerát (aktívny alebo predaný), zobrazí sa na karte výrazné červené
upozornenie s odkazmi na tie ostatné inzeráty. Nemusí to vždy znamenať scam -
môže ísť aj o predajcu/bazár, ktorý to isté auto legitímne inzeruje na
viacerých weboch - ale keď sa k tomu pridá iné meno/telefón a mierne odlišná
cena, je to silný signál na overenie pred kontaktovaním. Funguje len pre
inzeráty, ktoré VIN vôbec uvádzajú - chýbajúci VIN sa nedá porovnať.

## Kategória "Červené/Modré"

Rovnaká logika ako "Staršie ako {YEAR_MIN}" - auto v červenej alebo modrej farbe
(`config.SECONDARY_COLOR_FRAGMENTS`) sa NEVYMAŽE, len sa v tabuľke zobrazí pod
samostatnou záložkou "Červené/Modré" namiesto "Aktívne". Dôvod: aj keď to nie
je prvá voľba farby, pri dostatočne výhodnej ponuke prichádza do úvahy kúpa.

## Známe obmedzenia

- **Fotky z autobazar.sk sa zatiaľ nezobrazujú** - nepodarilo sa spoľahlivo
  zistiť formát URL fotiek (galéria sa dohráva cez API volania mimo dosahu
  dostupných nástrojov). `main_photo_url`/`all_photo_urls` sú pre tento zdroj
  zatiaľ prázdne, karta sa zobrazí bez fotky.
- **"Nová palubovka" (facelift interiér)** sa nedá spoľahlivo zistiť z textu
  inzerátu. Autá s rokom výroby pred `FACELIFT_CHECK_YEAR_THRESHOLD` majú
  v tabuľke badge "Skontroluj fotky" - over si to ručne pri kandidátoch.
- **CZ ceny** sa prepočítavajú na EUR orientačne podľa `CZK_TO_EUR_RATE`
  v `config.py` - nie live kurz. Pred reálnym rozhodovaním o kúpe si over
  aktuálny kurz aj náklady na prepis (`CZ_IMPORT_EXTRA_COST_ESTIMATE_EUR`
  je hrubý odhad, nie overená suma).
- Scraper pokrýva **bazos.sk, bazos.cz a autobazar.sk**. Iné SK/CZ autobazáre
  (sauto.cz, autoscout24.sk, mobile.de) majú v `robots.txt` plošný zákaz
  crawlovania a neboli zahrnuté.
- **aaaauto.sk je v kóde (`aaaauto_scraper.py`), ale VYPNUTÝ** - stránka
  blokuje jednoduché `requests.get()` sťahovanie cez anti-bot ochranu
  Anubis (JS proof-of-work challenge, overené 25.9.2026 priamo v produkčnom
  behu). Bez headless prehliadača (Playwright) sa to nedá obísť - viď bod 8
  v hlavičke `aaaauto_scraper.py`.
