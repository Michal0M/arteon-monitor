"""
Oznámenia na Discord cez webhook - VW Arteon monitor.

Rovnaký vzor ako v rental-monitor-bb (notify.py), prispôsobené pre autá.

Webhook URL je TAJOMSTVO: berie sa iba z premennej prostredia (GitHub Secret
DISCORD_WEBHOOK_AUTO), nikdy nie z kódu. Chyba pri odosielaní NIKDY neukončí
scraper - len sa vypíše do logu.

Rozsah (rozhodnuté s Michalom 26.9.2026): notifikuje sa VŠETKO, čo prejde cez
scraper do DB - všetky tri zdroje rovnako (bazos_sk, bazos_cz, autobazar_sk;
aaaauto_sk je momentálne vypnutý, viď aaaauto_scraper.py) AJ "Červené/Modré"
kategória (is_secondary_color). Jediné, čo sa nikdy neoznámi, je inzerát,
ktorý nesedí na tvrdé kritériá - ten sa do DB vôbec nedostane (viď scraper.py/
autobazar_scraper.py), takže sem sa ani nedostane na posúdenie.
"""

import os
import re
import time

import requests

import config

SECRET_ENV = "DISCORD_WEBHOOK_AUTO"
COLORS = {"new": 0x2ECC71, "price_drop": 0xF1C40F, "price_up": 0xE67E22, "reappeared": 0x3498DB}
HEADINGS = {"new": "🆕 Nový inzerát", "price_drop": "📉 Zľava", "price_up": "📈 Zvýšená cena",
            "reappeared": "🔁 Opäť v ponuke"}
SOURCE_LABELS = {
    "bazos_sk": "bazos.sk", "bazos_cz": "bazos.cz",
    "autobazar_sk": "autobazar.sk", "aaaauto_sk": "aaaauto.sk",
}

# Best-effort odhad motora z voľného textu PRE ZOBRAZENIE v notifikácii - v DB
# nemáme štruktúrované pole "motor" pri bazos_sk/bazos_cz/autobazar_sk (len sa
# proti nemu kontrolujú EXCLUDE_* vzory, výsledok sa nikde neukladá). Keďže
# vylúčenie TDI/hybrid/1.5 TSI už prebehlo v scraperi PREDTÝM, než sa inzerát
# vôbec dostal do DB, čo sa tu nájde, by malo byť legitímny variant (typicky
# "2.0 TSI"). Ak nič nenájde, pole sa v embede jednoducho vynechá - nehádame.
ENGINE_RE = re.compile(r"\d[.,]\d\s*tsi", re.IGNORECASE)


def kind_for(result: str, old_price, new_price) -> str | None:
    """Zmapuje výsledok upsertu na druh oznámenia (None = neoznamovať)."""
    if result == "new":
        return "new"
    if result == "reappeared":
        return "reappeared"
    if result == "price_changed" and old_price is not None and new_price is not None:
        return "price_drop" if new_price < old_price else "price_up"
    return None


def guess_engine(listing: dict) -> str | None:
    text = f"{listing.get('title') or ''} {listing.get('description_raw') or ''}"
    m = ENGINE_RE.search(text)
    return m.group(0).upper().replace(",", ".") if m else None


def fmt_price(price, currency) -> str:
    if price is None:
        return "Cena na dopyt"
    return f"{price:,.0f} {currency}".replace(",", " ")


def build_embed(item: dict) -> dict:
    l, kind = item["listing"], item["kind"]
    price = fmt_price(l.get("current_price"), l.get("currency"))
    if kind in ("price_drop", "price_up") and item.get("old_price") is not None:
        price = (f"~~{fmt_price(item['old_price'], l.get('currency'))}~~ → "
                 f"**{fmt_price(l.get('current_price'), l.get('currency'))}**")
    if l.get("currency") not in (None, config.CURRENCY_SK) and l.get("price_eur_est"):
        price += f" (≈ {fmt_price(l['price_eur_est'], config.CURRENCY_SK)} orientačne)"

    facts = []
    if l.get("year_built"):
        facts.append(str(l["year_built"]))
        if l["year_built"] < config.YEAR_MIN:
            facts.append(f"⚠️ staršie ako {config.YEAR_MIN}")
    if l.get("km") is not None:
        facts.append(f"{l['km']:,.0f} km".replace(",", " "))
    if l.get("color_guess"):
        facts.append(l["color_guess"])
    if l.get("is_secondary_color"):
        facts.append("⚠️ červená/modrá")
    engine = guess_engine(l)
    if engine:
        facts.append(engine)
    source_label = SOURCE_LABELS.get(l.get("source"), l.get("source"))
    if source_label:
        facts.append(source_label)

    embed = {
        "title": (l.get("title") or "Inzerát")[:250],
        "url": l["url"],
        "description": f"{HEADINGS[kind]}\n**{price}**\n" + " · ".join(facts),
        "color": COLORS[kind],
    }
    if l.get("main_photo_url"):
        embed["thumbnail"] = {"url": l["main_photo_url"]}
    return embed


def _post(url: str, payload: dict) -> bool:
    for attempt in range(3):
        try:
            r = requests.post(url, json=payload, timeout=15)
        except requests.RequestException as e:
            print(f"[notify] chyba siete: {type(e).__name__}")  # bez URL, aby sa tajomstvo nedostalo do logu
            return False
        if r.status_code == 429:
            try:
                wait = float(r.json().get("retry_after", 2))
            except Exception:
                wait = 2
            time.sleep(min(wait, 30) + 0.5)
            continue
        if r.status_code >= 300:
            print(f"[notify] Discord vrátil HTTP {r.status_code}")
            return False
        return True
    return False


def send_notifications(items: list[dict], webhook: str | None = None) -> int:
    """Pošle oznámenia (po 5 embedov v správe, max NOTIFY_MAX_PER_RUN). Vracia počet odoslaných."""
    webhook = webhook or os.environ.get(SECRET_ENV)
    if not items:
        return 0
    if not webhook:
        print(f"[notify] {len(items)} oznámení preskočených - chýba premenná {SECRET_ENV}")
        return 0
    shown = items[:config.NOTIFY_MAX_PER_RUN]
    sent = 0
    for i in range(0, len(shown), 5):
        chunk = shown[i:i + 5]
        payload = {"username": "VW Arteon monitor", "embeds": [build_embed(x) for x in chunk]}
        if i == 0 and len(items) > len(shown):
            payload["content"] = f"Dnes {len(items)} zmien, zobrazených prvých {len(shown)} - zvyšok na stránke."
        if _post(webhook, payload):
            sent += len(chunk)
        time.sleep(1)
    print(f"[notify] odoslaných {sent}/{len(items)} oznámení")
    return sent


def send_test(webhook: str | None = None) -> bool:
    webhook = webhook or os.environ.get(SECRET_ENV)
    if not webhook:
        print(f"Chýba premenná {SECRET_ENV}")
        return False
    return _post(webhook, {"username": "VW Arteon monitor", "content": "✅ Testovacia správa: Discord notifikácie fungujú."})


if __name__ == "__main__":
    import sys
    sys.exit(0 if send_test() else 1)
