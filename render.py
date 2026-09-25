"""
Vygeneruje statickú HTML stránku (docs/index.html) z dát v SQLite databáze.
Táto stránka sa publikuje cez GitHub Pages - žiadny server, žiadne API volania,
všetky dáta sú "zapečené" priamo do HTML pri generovaní.
"""

import json
from datetime import datetime, timezone

import config
import db


def format_price(price, currency):
    if price is None:
        return "Cena na dopyt"
    return f"{price:,.0f} {currency}".replace(",", " ")


def price_trend_html(history: list[dict]) -> str:
    """Malá textová história cien pod hlavnou cenou, napr. '27 799 € → 26 900 €'."""
    if len(history) <= 1:
        return ""
    prices = [h["price"] for h in history if h["price"] is not None]
    if len(prices) <= 1:
        return ""
    arrow = "↓" if prices[-1] < prices[0] else ("↑" if prices[-1] > prices[0] else "→")
    css_class = "price-down" if prices[-1] < prices[0] else ("price-up" if prices[-1] > prices[0] else "")
    chain = " → ".join(f"{p:,.0f}".replace(",", " ") for p in prices)
    return f'<div class="price-history {css_class}">{arrow} história: {chain}</div>'


def vin_dupe_warning_html(listing: dict, dupes_by_vin: dict) -> str:
    """
    Ak má tento inzerát VIN, ktorý sa zhoduje s iným (aktívnym alebo predaným)
    inzerátom v DB, zobrazí výrazné upozornenie s odkazmi na tie druhé
    inzeráty - typicky buď rovnaký predajca inzeruje na viacerých weboch,
    alebo ide o podozrivý klon cudzieho inzerátu (viď find_duplicate_vins v db.py).
    """
    vin = listing.get("vin")
    if not vin:
        return ""
    others = [o for o in dupes_by_vin.get(vin, []) if o["id"] != listing["id"]]
    if not others:
        return ""
    links = " · ".join(
        f'<a href="{o["url"]}" target="_blank" rel="noopener">{o["source"]} #{o["id"].split("_")[-1]}</a>'
        for o in others
    )
    return f'<div class="vin-dupe-warning">⚠️ Rovnaké VIN ako iný inzerát: {links}</div>'


def listing_card_html(listing: dict, history: list[dict], dupes_by_vin: dict) -> str:
    photos = json.loads(listing["all_photo_urls"] or "[]")
    main_photo = listing["main_photo_url"] or (photos[0] if photos else "")
    is_sold = listing["status"] != "active"
    # "Staršie ako YEAR_MIN" - MÄKKÁ kategória (auto sa neodmietlo, len sa nezaradí
    # medzi "Aktívne" - viď poznámka pri YEAR_MIN v config.py a v scraper.py run_source)
    is_old_year = listing["year_built"] is not None and listing["year_built"] < config.YEAR_MIN
    # "Červené/Modré" - MÄKKÁ kategória (pridané 24.9.2026, viď config.py
    # SECONDARY_COLOR_FRAGMENTS) - rovnaký princíp ako staršie ročníky.
    is_secondary_color = bool(listing["is_secondary_color"])

    badges = []
    if is_sold:
        badges.append('<span class="badge badge-sold">Predané / stiahnuté</span>')
    if is_secondary_color:
        badges.append('<span class="badge badge-color">Červená/Modrá</span>')
    if is_old_year:
        badges.append(f'<span class="badge badge-old">Staršie ako {config.YEAR_MIN}</span>')
    if listing["needs_photo_check"]:
        badges.append('<span class="badge badge-warn">Skontroluj fotky (facelift?)</span>')
    if listing["source"] == "bazos_cz":
        extra = config.CZ_IMPORT_EXTRA_COST_ESTIMATE_EUR
        badges.append(f'<span class="badge badge-info">CZ auto: +~{extra}€ prepis (odhad)</span>')

    price_display = format_price(listing["current_price"], listing["currency"])
    price_eur_note = ""
    if listing["currency"] != config.CURRENCY_SK and listing["price_eur_est"]:
        price_eur_note = f'<div class="price-eur-note">≈ {listing["price_eur_est"]:,.0f} € (orientačne)</div>'.replace(",", " ")

    # Pri predaných/stiahnutých autách je current_price posledná známa
    # INZEROVANÁ cena (nikdy sa neprepisuje na nič iné, keď inzerát zmizne) -
    # reálna dohodnutá cena pri kúpe mohla byť nižšia (dojednávanie na mieste),
    # toto je len posledná vyvesená suma pred stiahnutím inzerátu.
    sold_price_note = ""
    if is_sold:
        sold_price_note = (
            '<div class="sold-price-note">Posledná inzerovaná cena pred stiahnutím '
            "(skutočná dohodnutá cena mohla byť iná)</div>"
        )

    card_classes = " ".join(filter(None, [
        "card",
        "card-sold" if is_sold else "",
        "card-old" if is_old_year else "",
        "card-color" if is_secondary_color else "",
    ]))
    # Keď nemáme fotku (napr. autobazar_sk), nevykresľuj <img src=""> - prázdny
    # src si prehliadač vyloží ako odkaz na aktuálnu stránku a zobrazí "rozbitú"
    # ikonku namiesto ničoho. Namiesto toho placeholder div bez src.
    if main_photo:
        photo_html = f'<img class="card-photo" src="{main_photo}" alt="{listing["title"]}" loading="lazy" onerror="this.style.display=\'none\';this.nextElementSibling.style.display=\'flex\';"><div class="card-photo card-photo-placeholder" style="display:none;">Bez fotky</div>'
    else:
        photo_html = f'<div class="card-photo card-photo-placeholder">Bez fotky</div>'

    return f"""
    <div class="{card_classes}" data-price="{listing['current_price'] or 0}" data-year="{listing['year_built'] or 0}" data-km="{listing['km'] or 0}">
      <a href="{listing['url']}" target="_blank" rel="noopener" class="card-photo-link">
        {photo_html}
      </a>
      <div class="card-body">
        <div class="badges">{''.join(badges)}</div>
        <a href="{listing['url']}" target="_blank" rel="noopener" class="card-title">{listing['title']}</a>
        <div class="card-price">{price_display}</div>
        {price_eur_note}
        {sold_price_note}
        {vin_dupe_warning_html(listing, dupes_by_vin)}
        {price_trend_html(history)}
        <div class="card-meta">
          <span>{listing['year_built'] or '?'}</span> ·
          <span>{f"{listing['km']:,.0f} km".replace(',', ' ') if listing['km'] else '? km'}</span> ·
          <span>{listing['color_guess'] or 'farba ?'}</span> ·
          <span>{listing['location'] or ''}</span>
        </div>
        <div class="card-footer">
          <span class="source-tag">{listing['source']}</span>
          <span class="dates">videné od {listing['first_seen_at'][:10]} · naposledy {listing['last_seen_at'][:10]}</span>
        </div>
      </div>
    </div>"""


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="sk">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VW Arteon monitor</title>
<style>
  :root {{
    --bg: #0f1115; --card-bg: #1a1d24; --border: #2a2e38; --text: #e8eaed;
    --text-dim: #9aa0aa; --accent: #4f9dff; --green: #3ecf8e; --red: #ff5c5c; --yellow: #f5c518;
  }}
  * {{ box-sizing: border-box; }}
  body {{ background: var(--bg); color: var(--text); font-family: -apple-system, "Segoe UI", Roboto, sans-serif; margin: 0; padding: 16px; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  .subtitle {{ color: var(--text-dim); font-size: 13px; margin-bottom: 16px; }}
  .controls {{ display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; align-items: center; }}
  .controls button {{ background: var(--card-bg); border: 1px solid var(--border); color: var(--text); padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 13px; }}
  .controls button.active, .controls button.sort-btn-active {{ background: var(--accent); border-color: var(--accent); color: #fff; }}
  .sort-label {{ color: var(--text-dim); font-size: 13px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; }}
  .card {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; display: flex; flex-direction: column; }}
  .card-sold {{ opacity: 0.5; }}
  .card-photo-link {{ display: block; }}
  .card-photo {{ width: 100%; height: 170px; object-fit: cover; background: #000; display: block; }}
  .card-photo-placeholder {{ align-items: center; justify-content: center; color: var(--text-dim); font-size: 12px; background: #15171c; }}
  .card-body {{ padding: 12px; display: flex; flex-direction: column; gap: 6px; }}
  .badges {{ display: flex; gap: 4px; flex-wrap: wrap; }}
  .badge {{ font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: 600; }}
  .badge-sold {{ background: var(--red); color: #fff; }}
  .badge-warn {{ background: var(--yellow); color: #000; }}
  .badge-info {{ background: #2a3f5f; color: #9dc4ff; }}
  .badge-old {{ background: #4a3a1a; color: #f0c070; }}
  .badge-color {{ background: #4a1a2a; color: #f08fb0; }}
  .card-title {{ color: var(--text); font-weight: 600; font-size: 14px; text-decoration: none; line-height: 1.3; }}
  .card-title:hover {{ color: var(--accent); }}
  .card-price {{ font-size: 20px; font-weight: 700; }}
  .price-eur-note {{ font-size: 11px; color: var(--text-dim); margin-top: -4px; }}
  .sold-price-note {{ font-size: 11px; color: var(--red); font-weight: 600; }}
  .vin-dupe-warning {{ font-size: 11px; color: var(--red); font-weight: 600; background: rgba(255,92,92,0.12); border: 1px solid var(--red); border-radius: 6px; padding: 4px 6px; }}
  .vin-dupe-warning a {{ color: var(--red); text-decoration: underline; }}
  .price-history {{ font-size: 11px; color: var(--text-dim); }}
  .price-history.price-down {{ color: var(--green); }}
  .price-history.price-up {{ color: var(--red); }}
  .card-meta {{ font-size: 12px; color: var(--text-dim); }}
  .card-footer {{ display: flex; justify-content: space-between; font-size: 10px; color: var(--text-dim); margin-top: 4px; border-top: 1px solid var(--border); padding-top: 6px; }}
  .source-tag {{ text-transform: uppercase; letter-spacing: 0.5px; }}
  .empty-state {{ color: var(--text-dim); padding: 40px; text-align: center; }}
</style>
</head>
<body>
  <h1>🚗 VW Arteon R-Line monitor</h1>
  <div class="subtitle">Naposledy aktualizované: {updated_at} · {active_count} aktívnych · {color_count} červených/modrých · {old_count} starších ako {year_min} · {sold_count} predaných/stiahnutých</div>
  <div class="controls">
    <button class="filter-btn active" data-filter="active">Aktívne ({active_count})</button>
    <button class="filter-btn" data-filter="color">Červené/Modré ({color_count})</button>
    <button class="filter-btn" data-filter="old">Staršie ako {year_min} ({old_count})</button>
    <button class="filter-btn" data-filter="all">Všetky ({total_count})</button>
    <button class="filter-btn" data-filter="sold">Predané ({sold_count})</button>
  </div>
  <div class="controls">
    <span class="sort-label">Zoradiť:</span>
    <button id="sort-price" class="sort-btn sort-btn-active" data-field="price">Cena ↑</button>
    <button id="sort-km" class="sort-btn" data-field="km">Km ↑</button>
  </div>
  <div id="grid" class="grid">
    {cards_html}
  </div>
  <div id="empty" class="empty-state" style="display:none;">Žiadne inzeráty v tomto filtri.</div>

<script>
  const filterBtns = document.querySelectorAll('.filter-btn');
  const grid = document.getElementById('grid');
  const empty = document.getElementById('empty');
  const cards = Array.from(grid.children);

  function applyFilter(filter) {{
    // Priorita kategórií (rovnaká ako v render.py počítaní): sold > color > old > active.
    // Auto, ktoré je aj staršie AJ červené/modré, sa zaradí pod "Červené/Modré",
    // nie pod obe naraz - tab-filtre sú navzájom sa vylučujúce (okrem "Všetky").
    let visibleCount = 0;
    cards.forEach(c => {{
      const isSold = c.classList.contains('card-sold');
      const isColor = c.classList.contains('card-color');
      const isOld = c.classList.contains('card-old');
      let show;
      if (filter === 'all') show = true;
      else if (filter === 'sold') show = isSold;
      else if (filter === 'color') show = !isSold && isColor;
      else if (filter === 'old') show = !isSold && !isColor && isOld;
      else show = !isSold && !isColor && !isOld;  // 'active'
      c.style.display = show ? '' : 'none';
      if (show) visibleCount++;
    }});
    empty.style.display = visibleCount === 0 ? 'block' : 'none';
  }}

  filterBtns.forEach(btn => {{
    btn.addEventListener('click', () => {{
      filterBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      applyFilter(btn.dataset.filter);
    }});
  }});

  // Radenie - dve tlačidlá (cena / km), každé so svojím smerom, aktívne je
  // vždy len jedno naposledy kliknuté pole.
  const sortBtns = document.querySelectorAll('.sort-btn');
  const sortState = {{ field: 'price', asc: true }};

  function applySort() {{
    const sorted = cards.slice().sort((a, b) => {{
      const pa = parseFloat(a.dataset[sortState.field]) || 0;
      const pb = parseFloat(b.dataset[sortState.field]) || 0;
      return sortState.asc ? pa - pb : pb - pa;
    }});
    sorted.forEach(c => grid.appendChild(c));
  }}

  function updateSortLabels() {{
    sortBtns.forEach(btn => {{
      const isActiveField = btn.dataset.field === sortState.field;
      btn.classList.toggle('sort-btn-active', isActiveField);
      const label = btn.dataset.field === 'price' ? 'Cena' : 'Km';
      btn.textContent = label + ' ' + (isActiveField ? (sortState.asc ? '↑' : '↓') : '');
    }});
  }}

  sortBtns.forEach(btn => {{
    btn.addEventListener('click', () => {{
      if (sortState.field === btn.dataset.field) {{
        sortState.asc = !sortState.asc;
      }} else {{
        sortState.field = btn.dataset.field;
        sortState.asc = true;
      }}
      updateSortLabels();
      applySort();
    }});
  }});

  updateSortLabels();
  applyFilter('active');
</script>
</body>
</html>
"""


def render():
    with db.connect(config.DB_PATH) as conn:
        listings = db.get_all_listings(conn)
        dupes_by_vin = db.find_duplicate_vins(conn)
        cards = []
        for listing in listings:
            history = db.get_price_history(conn, listing["id"])
            cards.append(listing_card_html(listing, history, dupes_by_vin))

    def is_old(l):
        return l["year_built"] is not None and l["year_built"] < config.YEAR_MIN

    def is_color(l):
        return bool(l["is_secondary_color"])

    # Rovnaká priorita ako filter tlačidlá v JS: sold > color > old > active.
    # Auto staršie AJ červené/modré sa počíta len raz, pod "Červené/Modré".
    sold_count = sum(1 for l in listings if l["status"] != "active")
    color_count = sum(1 for l in listings if l["status"] == "active" and is_color(l))
    old_count = sum(1 for l in listings if l["status"] == "active" and not is_color(l) and is_old(l))
    active_count = len(listings) - sold_count - color_count - old_count

    html = PAGE_TEMPLATE.format(
        updated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        active_count=active_count,
        color_count=color_count,
        old_count=old_count,
        sold_count=sold_count,
        total_count=len(listings),
        year_min=config.YEAR_MIN,
        cards_html="\n".join(cards) if cards else "",
    )

    with open(config.OUTPUT_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Vygenerované: {config.OUTPUT_HTML_PATH} ({len(listings)} inzerátov)")


if __name__ == "__main__":
    render()
