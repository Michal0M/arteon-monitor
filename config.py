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

YEAR_MIN = 2021             # rok výroby / model rok - filtrované až po extrakcii z textu (nie je to filter v URL)

# Farby - hľadáme tieto reťazce (lowercase, bez diakritiky aj s diakritikou) v popise/title
COLORS = [
    "strieborn", "stribrn",              # strieborná / stříbrná
    "biel", "bíl",                       # biela / bílá
    "cierna", "čierna", "cern", "čern",  # čierna / černá
    "cerven", "červen",                  # červená
    "zlt", "žlt", "zlut", "žlut",        # žltá / žlutá
    "kurkuma", "horcicov", "horčicov",   # horčicová / Kurkuma Yellow (oficiálny VW názov)
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
