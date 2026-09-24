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


def listing_card_html(listing: dict, history: list[dict]) -> str:
    photos = json.loads(listing["all_photo_urls"] or "[]")
    main_photo = listing["main_photo_url"] or (photos[0] if photos else "")
    is_sold = listing["status"] != "active"

    badges = []
    if is_sold:
        badges.append('<span class="badge badge-sold">Predané / stiahnuté</span>')
    if listing["needs_photo_check"]:
        badges.append('<span class="badge badge-warn">Skontroluj fotky (facelift?)</span>')
    if listing["source"] == "bazos_cz":
        extra = config.CZ_IMPORT_EXTRA_COST_ESTIMATE_EUR
        badges.append(f'<span class="badge badge-info">CZ auto: +~{extra}€ prepis (odhad)</span>')

    price_display = format_price(listing["current_price"], listing["currency"])
    price_eur_note = ""
    if listing["currency"] != config.CURRENCY_SK and listing["price_eur_est"]:
        price_eur_note = f'<div class="price-eur-note">≈ {listing["price_eur_est"]:,.0f} € (orientačne)</div>'.replace(",", " ")

    return f"""
    <div class="card {'card-sold' if is_sold else ''}" data-price="{listing['current_price'] or 0}" data-year="{listing['year_built'] or 0}" data-km="{listing['km'] or 0}">
      <a href="{listing['url']}" target="_blank" rel="noopener" class="card-photo-link">
        <img class="card-photo" src="{main_photo}" alt="{listing['title']}" loading="lazy" onerror="this.style.opacity=0.3">
      </a>
      <div class="card-body">
        <div class="badges">{''.join(badges)}</div>
        <a href="{listing['url']}" target="_blank" rel="noopener" class="card-title">{listing['title']}</a>
        <div class="card-price">{price_display}</div>
        {price_eur_note}
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
  .controls {{ display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }}
  .controls button {{ background: var(--card-bg); border: 1px solid var(--border); color: var(--text); padding: 6px 12px; border-radius: 6px; cursor: pointer; font-size: 13px; }}
  .controls button.active {{ background: var(--accent); border-color: var(--accent); color: #fff; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; }}
  .card {{ background: var(--card-bg); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; display: flex; flex-direction: column; }}
  .card-sold {{ opacity: 0.5; }}
  .card-photo-link {{ display: block; }}
  .card-photo {{ width: 100%; height: 170px; object-fit: cover; background: #000; display: block; }}
  .card-body {{ padding: 12px; display: flex; flex-direction: column; gap: 6px; }}
  .badges {{ display: flex; gap: 4px; flex-wrap: wrap; }}
  .badge {{ font-size: 10px; padding: 2px 6px; border-radius: 4px; font-weight: 600; }}
  .badge-sold {{ background: var(--red); color: #fff; }}
  .badge-warn {{ background: var(--yellow); color: #000; }}
  .badge-info {{ background: #2a3f5f; color: #9dc4ff; }}
  .card-title {{ color: var(--text); font-weight: 600; font-size: 14px; text-decoration: none; line-height: 1.3; }}
  .card-title:hover {{ color: var(--accent); }}
  .card-price {{ font-size: 20px; font-weight: 700; }}
  .price-eur-note {{ font-size: 11px; color: var(--text-dim); margin-top: -4px; }}
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
  <div class="subtitle">Naposledy aktualizované: {updated_at} · {active_count} aktívnych · {sold_count} predaných/stiahnutých</div>
  <div class="controls">
    <button class="filter-btn active" data-filter="active">Aktívne ({active_count})</button>
    <button class="filter-btn" data-filter="all">Všetky ({total_count})</button>
    <button class="filter-btn" data-filter="sold">Predané ({sold_count})</button>
    <button id="sort-price" class="sort-btn active">Zoradiť: cena ↑</button>
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
    let visibleCount = 0;
    cards.forEach(c => {{
      const isSold = c.classList.contains('card-sold');
      let show = filter === 'all' || (filter === 'active' && !isSold) || (filter === 'sold' && isSold);
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

  let sortAsc = true;
  document.getElementById('sort-price').addEventListener('click', function() {{
    sortAsc = !sortAsc;
    this.textContent = 'Zoradiť: cena ' + (sortAsc ? '↑' : '↓');
    const sorted = cards.slice().sort((a, b) => {{
      const pa = parseFloat(a.dataset.price) || 0;
      const pb = parseFloat(b.dataset.price) || 0;
      return sortAsc ? pa - pb : pb - pa;
    }});
    sorted.forEach(c => grid.appendChild(c));
  }});

  applyFilter('active');
</script>
</body>
</html>
"""


def render():
    with db.connect(config.DB_PATH) as conn:
        listings = db.get_all_listings(conn)
        cards = []
        for listing in listings:
            history = db.get_price_history(conn, listing["id"])
            cards.append(listing_card_html(listing, history))

    active_count = sum(1 for l in listings if l["status"] == "active")
    sold_count = len(listings) - active_count

    html = PAGE_TEMPLATE.format(
        updated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        active_count=active_count,
        sold_count=sold_count,
        total_count=len(listings),
        cards_html="\n".join(cards) if cards else "",
    )

    with open(config.OUTPUT_HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Vygenerované: {config.OUTPUT_HTML_PATH} ({len(listings)} inzerátov)")


if __name__ == "__main__":
    render()
