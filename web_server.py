"""
EkspertizBul — Web Sunucusu
Tarayıcıdan http://localhost:8000 adresinde açılır
"""
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import json, sqlite3, asyncio
from pathlib import Path
from datetime import datetime

app = FastAPI()
DB_PATH = Path(__file__).parent / "ekspertiz_prices.db"

# ── Veritabanından fiyatları oku ─────────────────────────────
def get_prices():
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT f.firm_name, f.website, p.package_name, p.price, p.points, p.scraped_at
        FROM packages p
        JOIN firms f ON f.firm_id = p.firm_id
        WHERE p.scraped_at = (
            SELECT MAX(p2.scraped_at) FROM packages p2 WHERE p2.firm_id = p.firm_id
        )
        ORDER BY p.price ASC
    """).fetchall()
    conn.close()
    return rows

# ── Ana sayfa ────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def index():
    rows = get_prices()

    # Firma bazında grupla
    firms = {}
    for firm_name, website, pkg_name, price, points, scraped_at in rows:
        if firm_name not in firms:
            firms[firm_name] = {"website": website, "packages": [], "scraped_at": scraped_at}
        firms[firm_name]["packages"].append({
            "name": pkg_name, "price": price, "points": points
        })

    # Kart HTML'leri oluştur
    cards_html = ""
    for i, (firm_name, data) in enumerate(firms.items()):
        pkgs_html = ""
        for pkg in data["packages"]:
            pts = f" · {pkg['points']} nokta" if pkg['points'] else ""
            price_str = f"₺{pkg['price']:,.0f}" if pkg['price'] else "?"
            pkgs_html += f"""
            <div class="pkg-row">
                <span class="pkg-name">{pkg['name']}</span>
                <span class="pkg-price">{price_str}{pts}</span>
            </div>"""

        badge = '<span class="badge">En Uygun</span>' if i == 0 else ''
        cards_html += f"""
        <div class="card {'best' if i==0 else ''}">
            <div class="card-header">
                <div>
                    <div class="firm-name">{firm_name} {badge}</div>
                    <a href="{data['website']}" target="_blank" class="firm-url">{data['website']}</a>
                </div>
                <div class="rank">#{i+1}</div>
            </div>
            <div class="packages">{pkgs_html}</div>
        </div>"""

    updated = rows[0][5][:16].replace("T", " ") if rows else "Henüz taranmadı"
    firm_count = len(firms)

    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>EkspertizBul</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:'Inter',sans-serif; background:#f0f2f5; color:#1a1a2e; }}
header {{
    background: linear-gradient(135deg, #1a1a2e, #16213e);
    color:white; padding:40px 20px; text-align:center;
}}
header h1 {{ font-size:2.2rem; font-weight:800; margin-bottom:8px; }}
header h1 span {{ color:#00e5a0; }}
header p {{ color:#aaa; font-size:0.95rem; }}
.meta {{ display:flex; justify-content:center; gap:30px; margin-top:20px; }}
.meta-item {{ text-align:center; }}
.meta-num {{ font-size:1.5rem; font-weight:800; color:#00e5a0; }}
.meta-label {{ font-size:0.75rem; color:#888; }}
.container {{ max-width:900px; margin:30px auto; padding:0 20px; }}
.toolbar {{
    display:flex; justify-content:space-between; align-items:center;
    margin-bottom:20px; flex-wrap:wrap; gap:10px;
}}
.update-info {{ color:#888; font-size:0.85rem; }}
.scrape-btn {{
    background:#00e5a0; border:none; cursor:pointer;
    padding:10px 24px; border-radius:10px;
    font-weight:700; font-size:0.9rem; color:#000;
    transition:all 0.2s;
}}
.scrape-btn:hover {{ background:#00ffa8; transform:translateY(-1px); }}
.card {{
    background:white; border-radius:16px;
    padding:24px; margin-bottom:16px;
    border:2px solid transparent;
    box-shadow:0 2px 12px rgba(0,0,0,0.06);
    transition:all 0.2s;
}}
.card:hover {{ transform:translateY(-2px); box-shadow:0 8px 24px rgba(0,0,0,0.1); }}
.card.best {{ border-color:#00e5a0; background:linear-gradient(135deg,#fff,#f0fff8); }}
.card-header {{ display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:16px; }}
.firm-name {{ font-weight:700; font-size:1.1rem; display:flex; align-items:center; gap:8px; }}
.badge {{
    background:#00e5a0; color:#000;
    font-size:0.65rem; font-weight:700;
    padding:2px 8px; border-radius:4px; text-transform:uppercase;
}}
.firm-url {{ color:#888; font-size:0.8rem; text-decoration:none; }}
.firm-url:hover {{ color:#00e5a0; }}
.rank {{ font-size:1.8rem; font-weight:800; color:#e0e0e0; }}
.card.best .rank {{ color:#00e5a0; }}
.pkg-row {{
    display:flex; justify-content:space-between; align-items:center;
    padding:10px 0; border-bottom:1px solid #f0f0f0;
}}
.pkg-row:last-child {{ border-bottom:none; }}
.pkg-name {{ color:#666; font-size:0.9rem; }}
.pkg-price {{ font-weight:700; font-size:1rem; color:#1a1a2e; }}
.card.best .pkg-price {{ color:#00a875; }}
.empty {{
    text-align:center; padding:60px 20px; color:#888;
    background:white; border-radius:16px;
}}
.loading {{ display:none; text-align:center; padding:20px; color:#888; }}
</style>
</head>
<body>
<header>
    <h1>Ekspertiz<span>Bul</span></h1>
    <p>Türkiye'nin Oto Ekspertiz Fiyat Karşılaştırma Platformu</p>
    <div class="meta">
        <div class="meta-item">
            <div class="meta-num">{firm_count}</div>
            <div class="meta-label">Firma</div>
        </div>
        <div class="meta-item">
            <div class="meta-num">{len(rows)}</div>
            <div class="meta-label">Fiyat Kaydı</div>
        </div>
        <div class="meta-item">
            <div class="meta-num">%100</div>
            <div class="meta-label">Ücretsiz</div>
        </div>
    </div>
</header>

<div class="container">
    <div class="toolbar">
        <div class="update-info">🕐 Son güncelleme: {updated}</div>
        <button class="scrape-btn" onclick="scrapeNow()">🔄 Fiyatları Güncelle</button>
    </div>

    <div id="loading" class="loading">⏳ Siteler taranıyor, lütfen bekleyin (1-2 dakika)...</div>

    <div id="cards">
        {''.join([cards_html]) if firms else '<div class="empty"><h3>Henüz fiyat yok</h3><p>Fiyatları Güncelle butonuna basın</p></div>'}
    </div>
</div>

<script>
async function scrapeNow() {{
    document.getElementById('loading').style.display = 'block';
    document.querySelector('.scrape-btn').disabled = true;
    document.querySelector('.scrape-btn').textContent = '⏳ Taranıyor...';
    try {{
        const r = await fetch('/scrape', {{method:'POST'}});
        const d = await r.json();
        alert('✅ Tamamlandı! Sayfa yenileniyor...');
        location.reload();
    }} catch(e) {{
        alert('Hata: ' + e);
    }} finally {{
        document.getElementById('loading').style.display = 'none';
    }}
}}
</script>
</body>
</html>"""

# ── Scrape tetikleyici ───────────────────────────────────────
@app.post("/scrape")
async def trigger_scrape():
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from run_scraper import run_all
    results = await run_all()
    return {"success": True, "firms": len(results)}

# ── Başlat ───────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
