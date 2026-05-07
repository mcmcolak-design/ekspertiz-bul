from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import json, sqlite3
from pathlib import Path

app = FastAPI()
DB_PATH = Path(__file__).parent / "ekspertiz_prices.db"

FIRMS_DATA = [
    {"id":"otorapor","name":"Otorapor Ekspertiz","address":"Bağcılar, İstanbul","phone":"0850 XXX XX XX","website":"https://www.otorapor.com.tr","lat":41.0392,"lng":28.8562,"certified":True,"rating":4.8,"reviews":1243},
    {"id":"autoking","name":"Auto King Ekspertiz","address":"Şişli, İstanbul","phone":"0212 XXX XX XX","website":"https://www.autoking.com.tr","lat":41.0602,"lng":28.9877,"certified":True,"rating":4.6,"reviews":876},
    {"id":"dynomoss","name":"Dynomoss Oto Ekspertiz","address":"Kadıköy, İstanbul","phone":"0216 XXX XX XX","website":"https://dynomoss.com.tr","lat":40.9833,"lng":29.0333,"certified":False,"rating":4.5,"reviews":654},
    {"id":"rs_ekspertiz","name":"RS Oto Ekspertiz","address":"Beşiktaş, İstanbul","phone":"0212 XXX XX XX","website":"https://rsotoekspertiz.com","lat":41.0430,"lng":29.0070,"certified":True,"rating":4.3,"reviews":412},
    {"id":"arabam_ekspertiz","name":"Arabam.com Ekspertiz","address":"Maslak, İstanbul","phone":"0850 XXX XX XX","website":"https://www.arabam.com/oto-ekspertiz","lat":41.1057,"lng":29.0157,"certified":True,"rating":4.9,"reviews":2108},
]

def get_prices():
    if not DB_PATH.exists():
        return {}
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT f.firm_id, p.package_name, p.price, p.points
        FROM packages p JOIN firms f ON f.firm_id = p.firm_id
        WHERE p.scraped_at = (SELECT MAX(p2.scraped_at) FROM packages p2 WHERE p2.firm_id = p.firm_id)
        ORDER BY p.price ASC
    """).fetchall()
    conn.close()
    prices = {}
    for firm_id, pkg_name, price, points in rows:
        if firm_id not in prices:
            prices[firm_id] = []
        prices[firm_id].append({"name": pkg_name, "price": price, "points": points})
    return prices

@app.get("/", response_class=HTMLResponse)
def index():
    prices = get_prices()
    firms_json = json.dumps(FIRMS_DATA, ensure_ascii=False)
    prices_json = json.dumps(prices, ensure_ascii=False)
    
    html = HTML_TEMPLATE.replace("__FIRMS__", firms_json).replace("__PRICES__", prices_json)
    return html

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>EkspertizBul</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',sans-serif;background:#f0f2f5;color:#1a1a2e}
header{background:linear-gradient(135deg,#1a1a2e,#16213e);color:white;padding:28px 20px;text-align:center}
header h1{font-size:1.8rem;font-weight:800;margin-bottom:4px}
header h1 span{color:#00e5a0}
header p{color:#aaa;font-size:0.85rem}
.loc-bar{background:white;padding:14px 20px;display:flex;align-items:center;gap:12px;box-shadow:0 2px 8px rgba(0,0,0,.08);flex-wrap:wrap}
.loc-btn{background:#00e5a0;border:none;cursor:pointer;padding:11px 22px;border-radius:10px;font-weight:700;font-size:.9rem;color:#000;transition:all .2s}
.loc-btn:hover{background:#00ffa8;transform:translateY(-1px)}
.loc-status{color:#666;font-size:.82rem;display:flex;align-items:center;gap:6px}
.loc-dot{width:8px;height:8px;border-radius:50%;background:#ccc}
.loc-dot.on{background:#00e5a0;box-shadow:0 0 8px #00e5a0}
#map{height:280px;width:100%;border-bottom:3px solid #00e5a0}
.container{max-width:900px;margin:20px auto;padding:0 16px}
.sort-bar{display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap;align-items:center}
.sort-label{color:#888;font-size:.82rem}
.sort-btn{background:white;border:1px solid #ddd;padding:7px 13px;border-radius:8px;cursor:pointer;font-size:.8rem;transition:all .2s}
.sort-btn:hover,.sort-btn.active{border-color:#00e5a0;color:#00a875;background:#f0fff8}
.card{background:white;border-radius:14px;padding:18px;margin-bottom:10px;border:2px solid transparent;box-shadow:0 2px 10px rgba(0,0,0,.06);transition:all .2s}
.card:hover{transform:translateY(-2px);box-shadow:0 8px 20px rgba(0,0,0,.1)}
.card.best{border-color:#00e5a0;background:linear-gradient(135deg,#fff,#f0fff8)}
.card-top{display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:10px;gap:10px;flex-wrap:wrap}
.firm-name{font-weight:700;font-size:.98rem;display:flex;align-items:center;gap:6px;flex-wrap:wrap}
.badge{font-size:.62rem;font-weight:700;padding:2px 7px;border-radius:4px;text-transform:uppercase}
.b-best{background:#00e5a0;color:#000}
.b-cert{background:#e8e4ff;color:#6c47ff}
.firm-meta{display:flex;gap:10px;flex-wrap:wrap;color:#888;font-size:.78rem;margin-top:3px}
.dist{background:#fff3cd;color:#856404;border:1px solid #ffc107;padding:5px 12px;border-radius:20px;font-weight:700;font-size:.82rem;white-space:nowrap}
.dist.near{background:#d4edda;color:#155724;border-color:#28a745}
.pkgs{display:flex;gap:7px;flex-wrap:wrap;margin-top:8px}
.pkg{background:#f8f9fa;border:1px solid #eee;border-radius:8px;padding:7px 11px;font-size:.78rem}
.pkg-p{font-weight:700;color:#1a1a2e;font-size:.9rem}
.pkg-n{color:#888;font-size:.72rem}
.actions{display:flex;gap:7px;margin-top:10px;flex-wrap:wrap}
.btn-g{background:#00e5a0;border:none;cursor:pointer;padding:8px 16px;border-radius:8px;font-weight:600;font-size:.82rem;color:#000;text-decoration:none;display:inline-block;transition:all .2s}
.btn-g:hover{background:#00ffa8}
.btn-w{background:none;border:1px solid #ddd;cursor:pointer;padding:8px 14px;border-radius:8px;font-size:.82rem;color:#666;transition:all .2s}
.btn-w:hover{border-color:#00e5a0;color:#00a875}
</style>
</head>
<body>
<header>
  <h1>Ekspertiz<span>Bul</span></h1>
  <p>Konumunuza En Yakın Oto Ekspertiz Firmalarını Bulun</p>
</header>
<div class="loc-bar">
  <button class="loc-btn" onclick="getLocation()">📍 Konumumu Bul</button>
  <div class="loc-status">
    <div class="loc-dot" id="locDot"></div>
    <span id="locText">Konum alınmadı — butona basın</span>
  </div>
</div>
<div id="map"></div>
<div class="container">
  <div class="sort-bar">
    <span class="sort-label">Sırala:</span>
    <button class="sort-btn active" id="s1" onclick="sortBy('distance','s1')">📍 En Yakın</button>
    <button class="sort-btn" id="s2" onclick="sortBy('price','s2')">💰 En Ucuz</button>
    <button class="sort-btn" id="s3" onclick="sortBy('rating','s3')">⭐ En Yüksek Puan</button>
  </div>
  <div id="cards"></div>
</div>
<script>
var FIRMS = __FIRMS__;
var PRICES = __PRICES__;
var uLat = null, uLng = null, map = null, uMarker = null, sortMode = 'distance';

function initMap() {
  map = L.map('map').setView([39.9, 32.8], 6);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {attribution: '© OpenStreetMap'}).addTo(map);
  FIRMS.forEach(function(f) {
    L.marker([f.lat, f.lng]).addTo(map).bindPopup('<b>' + f.name + '</b><br>' + f.address);
  });
}

function getLocation() {
  document.getElementById('locText').textContent = 'Konum alınıyor...';
  if (!navigator.geolocation) { alert('Tarayıcınız konum desteklemiyor.'); return; }
  navigator.geolocation.getCurrentPosition(
    function(p) {
      uLat = p.coords.latitude;
      uLng = p.coords.longitude;
      document.getElementById('locDot').classList.add('on');
      document.getElementById('locText').textContent = 'Konumunuz alındı ✓';
      map.setView([uLat, uLng], 12);
      if (uMarker) map.removeLayer(uMarker);
      var icon = L.divIcon({html: '<div style="background:#00e5a0;width:14px;height:14px;border-radius:50%;border:3px solid white;box-shadow:0 0 8px #00e5a0"></div>', iconSize:[14,14], iconAnchor:[7,7]});
      uMarker = L.marker([uLat, uLng], {icon: icon}).addTo(map).bindPopup('📍 Siz buradasınız').openPopup();
      renderCards();
    },
    function() { document.getElementById('locText').textContent = 'Konum alınamadı — izin verin'; renderCards(); }
  );
}

function calcDist(a, b, c, d) {
  var R = 6371, dL = (c-a)*Math.PI/180, dG = (d-b)*Math.PI/180;
  var x = Math.sin(dL/2)*Math.sin(dL/2) + Math.cos(a*Math.PI/180)*Math.cos(c*Math.PI/180)*Math.sin(dG/2)*Math.sin(dG/2);
  return R * 2 * Math.atan2(Math.sqrt(x), Math.sqrt(1-x));
}

function sortBy(t, btnId) {
  sortMode = t;
  ['s1','s2','s3'].forEach(function(id) { document.getElementById(id).classList.remove('active'); });
  document.getElementById(btnId).classList.add('active');
  renderCards();
}

function renderCards() {
  var firms = FIRMS.map(function(f) {
    return Object.assign({}, f, {
      distance: (uLat && uLng) ? calcDist(uLat, uLng, f.lat, f.lng) : null,
      prices: PRICES[f.id] || []
    });
  });

  firms.sort(function(a, b) {
    if (sortMode === 'distance') {
      if (!a.distance) return 1;
      if (!b.distance) return -1;
      return a.distance - b.distance;
    }
    if (sortMode === 'price') {
      var pa = a.prices[0] ? a.prices[0].price : 99999;
      var pb = b.prices[0] ? b.prices[0].price : 99999;
      return pa - pb;
    }
    return b.rating - a.rating;
  });

  var html = '';
  firms.forEach(function(f, i) {
    var near = (i === 0 && f.distance !== null);
    var dstr = f.distance !== null ? f.distance.toFixed(1) + ' km uzakta' : 'Konum alınmadı';
    var pkgs = '';
    var plist = f.prices.slice(0, 3);
    if (plist.length > 0) {
      plist.forEach(function(p) {
        pkgs += '<div class="pkg"><div class="pkg-n">' + p.name + '</div><div class="pkg-p">₺' + (p.price ? p.price.toLocaleString('tr') : '?') + '</div></div>';
      });
    } else {
      pkgs = '<div class="pkg"><div class="pkg-n">Fiyat yükleniyor...</div></div>';
    }
    html += '<div class="card' + (near ? ' best' : '') + '">';
    html += '<div class="card-top"><div>';
    html += '<div class="firm-name">' + f.name;
    if (near) html += '<span class="badge b-best">En Yakın</span>';
    if (f.certified) html += '<span class="badge b-cert">Sertifikalı</span>';
    html += '</div>';
    html += '<div class="firm-meta"><span>⭐ ' + f.rating + ' (' + f.reviews.toLocaleString('tr') + ')</span><span>📍 ' + f.address + '</span><span>📞 ' + f.phone + '</span></div>';
    html += '</div><div class="dist' + (near ? ' near' : '') + '">📍 ' + dstr + '</div></div>';
    html += '<div class="pkgs">' + pkgs + '</div>';
    html += '<div class="actions">';
    html += '<a href="' + f.website + '" target="_blank" class="btn-g">Randevu Al</a>';
    html += '<button class="btn-w" onclick="goMap(' + f.lat + ',' + f.lng + ')">🗺️ Haritada Gör</button>';
    html += '<button class="btn-w" onclick="yolTarifi(' + f.lat + ',' + f.lng + ')">🧭 Yol Tarifi</button>';
    html += '</div></div>';
  });
  document.getElementById('cards').innerHTML = html;
}

function goMap(lat, lng) {
  map.setView([lat, lng], 15);
  window.scrollTo({top: 0, behavior: 'smooth'});
}

function yolTarifi(lat, lng) {
  var url = uLat ? 'https://www.google.com/maps/dir/' + uLat + ',' + uLng + '/' + lat + ',' + lng : 'https://www.google.com/maps/search/' + lat + ',' + lng;
  window.open(url, '_blank');
}

initMap();
renderCards();
</script>
</body>
</html>"""

@app.post("/scrape")
async def trigger_scrape():
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from run_scraper import run_all
    results = await run_all()
    return {"success": True, "firms": len(results)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
