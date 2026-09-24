"""
Kritériá vyhľadávania a nastavenia projektu.
Uprav tento súbor, keď budeš chcieť sledovať iné auto alebo iné parametre.
"""

# --- Čo hľadáme ---
KEYWORD = "arteon"          # kľúčové slovo pre vyhľadávanie
REQUIRE_TITLE_CONTAINS = ["r-line", "r line", "rline"]  # aspoň jedno z toho musí byť v title/popise (case-insensitive)

PRICE_MIN = 19000
PRICE_MAX = 28000
CURRENCY_SK = "EUR"
CURRENCY_CZ = "CZK"

KM_MIN = 0
KM_MAX = 120_000

YEAR_MIN = 2021             # rok výroby - MÄKKÝ filter: staršie autá sa NEZAHODIA, len sa
                             # v tabuľke zobrazia pod samostatnou kategóriou "Staršie ako {YEAR_MIN}"
                             # (pozri render.py), nie medzi "Aktívne"

# Farby - hľadáme tieto reťazce (lowercase, bez diakritiky aj s diakritikou) v popise/title
COLORS = [
    "strieborn", "stribrn",              # strieborná / stříbrná
    "biel", "bíl",                       # biela / bílá
    "cierna", "čierna", "cern", "čern",  # čierna / černá
    "zlt", "žlt", "zlut", "žlut",        # žltá / žlutá
    "kurkuma", "horcicov", "horčicov",   # horčicová / Kurkuma Yellow (oficiálny VW názov)
]

# Farby ktoré NECHCEME - tvrdý filter, inzerát sa vôbec nezobrazí, aj keby inak
# sedel na všetky ostatné kritériá. Hľadá sa ako podreťazec kdekoľvek v popise/title,
# takže to nie je 100% neomylné (napr. text "nie je červená" by tiež vyhodil), ale
# v praxi je to zriedkavé a bezpečnejšie než falošne NEVYFILTROVAŤ nechcenú farbu.
EXCLUDE_COLOR_FRAGMENTS = ["cerven", "červen", "modr"]  # červená, modrá

# Karoséria "veľký kufor" (kombi / Shooting Brake) - NECHCEME, len klasický liftback/sedan.
# "sb" sa kontroluje ako samostatné slovo (regex \bsb\b), nie ako podreťazec,
# aby to nevyhodilo niečo, čo náhodou obsahuje "sb" v inom slove.
EXCLUDE_BODY_STYLE_CONTAINS = ["shooting brake", "kombi", "kombík"]
EXCLUDE_BODY_STYLE_REGEX = [r"\bsb\b"]

# Motor - chceme len čisté benzínové TSI, nie naftu (TDI) ani hybrid (eHybrid/PHEV
# - Arteon eHybrid je 1.4 TSI + elektromotor/batéria, nie to isté ako čisté 2.0 TSI).
# Bazos fulltext vyhľadávanie "arteon r-line" vracia všetky varianty, treba ich
# odfiltrovať sami.
EXCLUDE_FUEL_CONTAINS = [
    "tdi", "bitdi", "biturbo tdi", "diesel", "nafta",
    "ehybrid", "e-hybrid", "hybrid", "phev", "gte",
]

# --- Poznámka k "nová palubovka" (facelift interiér) ---
# Toto sa nedá spoľahlivo zistiť z textu inzerátu ani z URL parametrov.
# Aplikácia to NEFILTRUJE automaticky - v tabuľke bude stĺpec "skontroluj fotky",
# ktorý sa nastaví na True pri autách s rokom výroby nižším ako tento prah,
# kde je najvyššie riziko starej palubovky pred faceliftom.
FACELIFT_CHECK_YEAR_THRESHOLD = 2022  # ročníky < tohto roka sa označia na manuálnu kontrolu

# --- Zdroje ---
SOURCES = [
    {
        "name": "bazos_sk",
        "base_url": "https://auto.bazos.sk",
        "image_base_url": "https://www.bazos.sk",
        "currency": CURRENCY_SK,
        "country": "SK",
    },
    {
        "name": "bazos_cz",
        "base_url": "https://auto.bazos.cz",
        "image_base_url": "https://www.bazos.cz",
        "currency": CURRENCY_CZ,
        "country": "CZ",
    },
]

# --- Prepočet CZK -> EUR pre porovnanie SK/CZ inzerátov ---
# ORIENTAČNÝ kurz, NIE live dáta. Kurz sa v čase mení - over si aktuálny
# (napr. ecb.europa.eu) a uprav podľa potreby. Používa sa len na hrubé
# porovnanie/filtrovanie, nie na finálne rozhodovanie o kúpe.
CZK_TO_EUR_RATE = 0.040  # cca k 09/2026, OVERIŤ pred reálnym použitím

# --- Odhad nákladov na prepis auta z ČR do SR ---
# Toto sú HRUBÉ orientačné odhady, NEOVERENÉ aktuálne sadzby (menia sa, závisia od kW motora,
# roku výroby a regionálnych poplatkov). Priprav sa, že si presné sumy budeš musieť dohľadať sám
# pred reálnym rozhodnutím o kúpe - toto číslo slúži len na hrubú orientáciu v tabuľke.
CZ_IMPORT_EXTRA_COST_ESTIMATE_EUR = 400  # evidenčná kontrola + STK/EK + poplatok za prvú evidenciu (ODHAD, OVERIŤ)

# --- Technické nastavenia scrapera ---
REQUEST_DELAY_SECONDS = 4        # pauza medzi requestami (throttling, aby sme nespamovali server)
REQUEST_TIMEOUT_SECONDS = 15
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
MAX_PAGES_PER_SOURCE = 10         # bezpečnostný strop, aby sa scraper nezacyklil pri chybe parsovania

DB_PATH = "data/listings.db"
OUTPUT_HTML_PATH = "docs/index.html"
