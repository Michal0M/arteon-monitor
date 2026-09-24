"""
SQLite vrstva pre uchovávanie inzerátov a histórie cien.

Schéma:
    listings        - jeden riadok = jeden inzerát (aktuálny stav)
    price_history    - jeden riadok = jedna zaznamenaná cena k dátumu (história)

Prečo dve tabuľky namiesto jednej:
    - `listings` drží aktuálny stav (najnovšia cena, status, či je aktívny)
      a je to, čo renderer primárne číta pre zobrazenie tabuľky.
    - `price_history` je append-only log - NIKDY sa nemaže ani neprepisuje,
      len sa doň pridávajú nové riadky. Vďaka tomu vieš kedykoľvek spätne
      vykresliť graf "cena v čase" pre konkrétny inzerát.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id              TEXT PRIMARY KEY,   -- unikátne ID inzerátu (source_name + bazos ID)
    source          TEXT NOT NULL,      -- 'bazos_sk' / 'bazos_cz'
    url             TEXT NOT NULL,
    title           TEXT NOT NULL,
    description_raw TEXT,
    current_price   REAL,
    currency        TEXT,
    price_eur_est   REAL,               -- orientačný prepočet na EUR pre porovnanie SK/CZ
    year_built      INTEGER,
    km              INTEGER,
    color_guess     TEXT,               -- ktorá farba z config.COLORS bola nájdená v texte
    location        TEXT,
    main_photo_url  TEXT,
    all_photo_urls  TEXT,               -- JSON list
    needs_photo_check INTEGER DEFAULT 0, -- 1 = over ručne fotky kvôli faceliftu/palubovke
    status          TEXT DEFAULT 'active', -- 'active' / 'sold_or_removed'
    first_seen_at   TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL,
    removed_at      TEXT
);

CREATE TABLE IF NOT EXISTS price_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id      TEXT NOT NULL,
    price           REAL,
    currency        TEXT,
    recorded_at     TEXT NOT NULL,
    FOREIGN KEY (listing_id) REFERENCES listings(id)
);

CREATE INDEX IF NOT EXISTS idx_price_history_listing ON price_history(listing_id);
CREATE INDEX IF NOT EXISTS idx_listings_status ON listings(status);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: str) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def get_listing(conn, listing_id: str):
    row = conn.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()
    return dict(row) if row else None


def upsert_listing(conn, listing: dict) -> str:
    """
    Vloží nový inzerát alebo aktualizuje existujúci.

    Logika histórie cien:
        - Ak inzerát je nový -> vlož do listings + prvý záznam do price_history.
        - Ak inzerát existuje a cena sa NEZMENILA -> len aktualizuj last_seen_at.
        - Ak inzerát existuje a cena sa ZMENILA -> aktualizuj current_price
          v listings, ale STARÝ záznam v price_history zostáva netknutý,
          pridá sa nový riadok s novou cenou a dnešným dátumom.

    Vracia: 'new' | 'price_changed' | 'unchanged'
    """
    existing = get_listing(conn, listing["id"])
    ts = now_iso()

    if existing is None:
        conn.execute(
            """
            INSERT INTO listings (
                id, source, url, title, description_raw, current_price, currency,
                price_eur_est, year_built, km, color_guess, location,
                main_photo_url, all_photo_urls, needs_photo_check, status,
                first_seen_at, last_seen_at, removed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, NULL)
            """,
            (
                listing["id"], listing["source"], listing["url"], listing["title"],
                listing.get("description_raw"), listing.get("current_price"),
                listing.get("currency"), listing.get("price_eur_est"),
                listing.get("year_built"), listing.get("km"), listing.get("color_guess"),
                listing.get("location"), listing.get("main_photo_url"),
                listing.get("all_photo_urls"), int(listing.get("needs_photo_check", 0)),
                ts, ts,
            ),
        )
        conn.execute(
            "INSERT INTO price_history (listing_id, price, currency, recorded_at) VALUES (?, ?, ?, ?)",
            (listing["id"], listing.get("current_price"), listing.get("currency"), ts),
        )
        return "new"

    # Inzerát existuje - zisti, či sa zmenila cena
    old_price = existing["current_price"]
    new_price = listing.get("current_price")
    price_changed = old_price != new_price and new_price is not None

    conn.execute(
        """
        UPDATE listings SET
            title = ?, description_raw = ?, current_price = ?, currency = ?,
            price_eur_est = ?, year_built = ?, km = ?, color_guess = ?,
            location = ?, main_photo_url = ?, all_photo_urls = ?,
            needs_photo_check = ?, status = 'active', last_seen_at = ?, removed_at = NULL
        WHERE id = ?
        """,
        (
            listing["title"], listing.get("description_raw"), new_price,
            listing.get("currency"), listing.get("price_eur_est"),
            listing.get("year_built"), listing.get("km"), listing.get("color_guess"),
            listing.get("location"), listing.get("main_photo_url"),
            listing.get("all_photo_urls"), int(listing.get("needs_photo_check", 0)),
            ts, listing["id"],
        ),
    )

    if price_changed:
        conn.execute(
            "INSERT INTO price_history (listing_id, price, currency, recorded_at) VALUES (?, ?, ?, ?)",
            (listing["id"], new_price, listing.get("currency"), ts),
        )
        return "price_changed"

    return "unchanged"


def delete_listing(conn, listing_id: str) -> bool:
    """
    Natvrdo vymaže inzerát aj celú jeho cenovú históriu z DB.

    Použije sa vtedy, keď inzerát prestane sedieť na kritériá v config.py
    (napr. sa zmenil filter, alebo cena/km vyšli mimo rozsah) - to NIE je to
    isté ako "predané/stiahnuté" (mark_missing_as_sold). Inzerát, ktorý len
    nesedí na kritériá, sa má z tabuľky úplne stratiť, nie sa zobrazovať pod
    "Predané" - tam patria len tie, čo reálne zmizli z ponuky.
    """
    # POZOR na poradie: price_history má FOREIGN KEY na listings.id a foreign_keys
    # je zapnuté (PRAGMA foreign_keys = ON v connect()) - najprv MUSÍME zmazať
    # "dieťa" (price_history), až potom "rodiča" (listings), inak SQLite to
    # odmietne s IntegrityError: FOREIGN KEY constraint failed.
    conn.execute("DELETE FROM price_history WHERE listing_id = ?", (listing_id,))
    cur = conn.execute("DELETE FROM listings WHERE id = ?", (listing_id,))
    return cur.rowcount > 0


def mark_missing_as_sold(conn, seen_ids: set[str], source: str) -> list[str]:
    """
    Inzeráty z daného zdroja, ktoré boli 'active' pri poslednom behu, ale teraz
    neboli nájdené v aktuálnom výpise -> označ ako 'sold_or_removed'.

    Vracia zoznam ID, ktoré boli takto novo označené (na účely logovania/notifikácie).
    """
    rows = conn.execute(
        "SELECT id FROM listings WHERE source = ? AND status = 'active'", (source,)
    ).fetchall()
    newly_removed = []
    ts = now_iso()
    for row in rows:
        if row["id"] not in seen_ids:
            conn.execute(
                "UPDATE listings SET status = 'sold_or_removed', removed_at = ? WHERE id = ?",
                (ts, row["id"]),
            )
            newly_removed.append(row["id"])
    return newly_removed


def get_price_history(conn, listing_id: str):
    rows = conn.execute(
        "SELECT price, currency, recorded_at FROM price_history WHERE listing_id = ? ORDER BY recorded_at",
        (listing_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_all_listings(conn, status: str | None = None):
    if status:
        rows = conn.execute(
            "SELECT * FROM listings WHERE status = ? ORDER BY current_price ASC", (status,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM listings ORDER BY status ASC, current_price ASC").fetchall()
    return [dict(r) for r in rows]
