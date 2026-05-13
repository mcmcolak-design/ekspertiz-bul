from fastapi import FastAPI, Request, Form, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
import json, sqlite3
from pathlib import Path
from models import (init_db, get_conn, hash_password, check_password,
                    create_session, get_session, delete_session)
from notifications import email_yeni_randevu_firma, email_randevu_guncelleme_kullanici
from apscheduler.schedulers.background import BackgroundScheduler
import datetime

init_db()

def auto_complete_appointments():
    """Randevu saatinden 1 saat sonra otomatik tamamla"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        now = datetime.datetime.now()
        # onaylandi durumundaki randevulari al
        cur.execute("""
            SELECT * FROM appointments
            WHERE durum = 'onaylandi'
        """)
        rows = cur.fetchall()
        for r in rows:
            try:
                apt_dt = datetime.datetime.strptime(f"{r['tarih']} {r['saat']}", "%Y-%m-%d %H:%M")
                # 1 saat sonra otomatik tamamla
                if now >= apt_dt + datetime.timedelta(hours=1):
                    cur.execute("UPDATE appointments SET durum='tamamlandi' WHERE id=%s", (r['id'],))
                    # Her iki tarafa bildirim
                    cur.execute("SELECT unvan FROM firm_accounts WHERE id=%s", (r['firm_id'],))
                    firm = cur.fetchone()
                    firma_adi = firm['unvan'] if firm else 'Firma'
                    # Kullaniciya bildirim
                    cur.execute(
                        "INSERT INTO notifications (user_id, tip, mesaj, appointment_id) VALUES (%s,%s,%s,%s)",
                        (r['user_id'], 'otomatik_tamamlandi', f'Randevunuz tamamlandi: {firma_adi} - {r["tarih"]} {r["saat"]}', r['id'])
                    )
                    # Firmaya bildirim
                    cur.execute(
                        "INSERT INTO notifications (firm_id, tip, mesaj, appointment_id) VALUES (%s,%s,%s,%s)",
                        (r['firm_id'], 'otomatik_tamamlandi', f'Randevu otomatik tamamlandi: {r["tarih"]} {r["saat"]}', r['id'])
                    )
            except Exception as e:
                print(f"Auto complete error for apt {r['id']}: {e}")
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Scheduler error: {e}")

# Her 15 dakikada bir kontrol et
scheduler = BackgroundScheduler()
scheduler.add_job(auto_complete_appointments, 'interval', minutes=15)
scheduler.start()
print("Scheduler started")

app = FastAPI()
DB_PATH = Path(__file__).parent / "ekspertiz_prices.db"
FIRMS_JSON = Path(__file__).parent / "firms_google.json"

DEFAULT_FIRMS = [
    {"id":"otorapor","name":"Otorapor Ekspertiz","address":"Bagcilar, Istanbul","phone":"0850 XXX XX XX","website":"https://www.otorapor.com.tr","lat":41.0392,"lng":28.8562,"certified":True,"rating":4.8,"reviews":1243,"city":"Istanbul","place_id":""},
    {"id":"autoking","name":"Auto King Ekspertiz","address":"Sisli, Istanbul","phone":"0212 XXX XX XX","website":"https://www.autoking.com.tr","lat":41.0602,"lng":28.9877,"certified":True,"rating":4.6,"reviews":876,"city":"Istanbul","place_id":""},
    {"id":"dynomoss","name":"Dynomoss Ekspertiz","address":"Kadikoy, Istanbul","phone":"0216 XXX XX XX","website":"https://dynomoss.com.tr","lat":40.9833,"lng":29.0333,"certified":False,"rating":4.5,"reviews":654,"city":"Istanbul","place_id":""},
    {"id":"rs_ekspertiz","name":"RS Oto Ekspertiz","address":"Besiktas, Istanbul","phone":"0212 XXX XX XX","website":"https://rsotoekspertiz.com","lat":41.0430,"lng":29.0070,"certified":True,"rating":4.3,"reviews":412,"city":"Istanbul","place_id":""},
    {"id":"arabam_ekspertiz","name":"Arabam.com Ekspertiz","address":"Maslak, Istanbul","phone":"0850 XXX XX XX","website":"https://www.arabam.com/oto-ekspertiz","lat":41.1057,"lng":29.0157,"certified":True,"rating":4.9,"reviews":2108,"city":"Istanbul","place_id":""},
]

def load_firms():
    firms = []
    if FIRMS_JSON.exists():
        with open(FIRMS_JSON, "r", encoding="utf-8") as f:
            firms = [fi for fi in json.load(f) if fi.get("lat") and fi.get("lng")]
    else:
        firms = list(DEFAULT_FIRMS)

    # app.db'deki onaylanmis firmalari da ekle
    try:
        from models import get_conn as _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM firm_accounts WHERE active=1")
        db_firms = cur.fetchall()
        cur.close()
        conn.close()
        for f in db_firms:
            keys = list(f.keys())
            lat = float(f["lat"]) if f.get("lat") else None
            lng = float(f["lng"]) if f.get("lng") else None
            firms.append({
                "id": f"db_{f['id']}",
                "name": f["unvan"],
                "address": (f.get("adres") or "") + (", " + f["ilce"] if f.get("ilce") else "") + (", " + f["il"] if f.get("il") else ""),
                "phone": f.get("telefon", ""),
                "website": "",
                "lat": lat if lat else 39.9,
                "lng": lng if lng else 32.8,
                "city": f.get("il", ""),
                "certified": False,
                "rating": 0,
                "reviews": 0,
                "place_id": "",
                "db_firm_id": f["id"],
                "no_coords": not lat or not lng,
                "durum": f.get("durum", "aktif"),
                "durum_notu": f.get("durum_notu", ""),
            })
    except Exception as e:
        print(f"DB firms load error: {e}")

    return firms

def get_prices():
    # Oncelikle SQLite DB'den fiyatlari al
    if DB_PATH.exists():
        try:
            import sqlite3 as _sq
            conn = _sq.connect(DB_PATH)
            rows = conn.execute("""
                SELECT f.firm_id, p.package_name, p.price
                FROM packages p JOIN firms f ON f.firm_id = p.firm_id
                WHERE p.scraped_at = (SELECT MAX(p2.scraped_at) FROM packages p2 WHERE p2.firm_id = p.firm_id)
                ORDER BY p.price ASC
            """).fetchall()
            conn.close()
            prices = {}
            for fid, pname, price in rows:
                if fid not in prices:
                    prices[fid] = []
                prices[fid].append({"name": pname, "price": price})
            # PostgreSQL'deki firma paketlerini de ekle
            try:
                pg = get_conn()
                cur = pg.cursor()
                cur.execute("SELECT firm_id, paket_adi, fiyat FROM firm_packages WHERE aktif=1")
                for row in cur.fetchall():
                    fid = f"db_{row['firm_id']}"
                    if fid not in prices:
                        prices[fid] = []
                    prices[fid].append({"name": row['paket_adi'], "price": row['fiyat']})
                cur.close()
                pg.close()
            except:
                pass
            return prices
        except Exception as e:
            print(f"get_prices error: {e}")
    return {}

PAGE = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>EkspertizBul - Turkiye'nin En Buyuk Ekspertiz Platformu</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:Inter,sans-serif;background:#f5f0f0;color:#1a0000}
header{background:linear-gradient(135deg,#1a0000,#3d0000);color:#fff;padding:24px 16px;text-align:center}
h1{font-size:1.7rem;font-weight:800}h1 em{color:#e53535;font-style:normal}
header p{color:#aaa;font-size:.85rem;margin-top:4px}
.stats{display:flex;justify-content:center;gap:30px;margin-top:12px}
.stat{text-align:center}
.stat-n{font-size:1.4rem;font-weight:800;color:#e53535}
.stat-l{font-size:.72rem;color:#888}
.bar{background:#fff;padding:12px 16px;display:flex;align-items:center;gap:8px;box-shadow:0 2px 8px rgba(0,0,0,.07);flex-wrap:wrap}
.locbtn{background:#e53535;border:none;cursor:pointer;padding:10px 16px;border-radius:10px;font-weight:700;font-size:.85rem;color:#000;white-space:nowrap}
.locbtn:hover{background:#ff4444}
.locinfo{color:#666;font-size:.82rem;display:flex;align-items:center;gap:6px;white-space:nowrap}
.dot{width:8px;height:8px;border-radius:50%;background:#ccc;display:inline-block}
.dot.on{background:#e53535;box-shadow:0 0 6px #e53535}
.search-bar{flex:1;min-width:140px}
.search-bar input{width:100%;padding:9px 14px;border:1px solid #ddd;border-radius:10px;font-size:.85rem;outline:none}
.search-bar input:focus{border-color:#e53535}
.sel-wrap{display:flex;gap:6px;flex-wrap:wrap}
.sel-wrap select{padding:9px 10px;border:1px solid #ddd;border-radius:10px;font-size:.82rem;outline:none;background:#fff;cursor:pointer;color:#333;max-width:150px}
.sel-wrap select:focus{border-color:#e53535}
#map{height:260px;border-bottom:3px solid #e53535}
.wrap{max-width:860px;margin:18px auto;padding:0 14px}
.sorts{display:flex;gap:7px;margin-bottom:12px;flex-wrap:wrap;align-items:center}
.sl{color:#888;font-size:.8rem}
.sb{background:#fff;border:1px solid #ddd;padding:6px 12px;border-radius:8px;cursor:pointer;font-size:.78rem}
.sb.on{border-color:#e53535;color:#c41c1c;background:#fff0f0}
.fiyat-btn{background:#fff;border:1px solid #ddd;padding:6px 12px;border-radius:8px;cursor:pointer;font-size:.78rem;margin-left:auto}
.fiyat-btn.on{border-color:#f5a623;color:#b36b00;background:#fff8ee}
.result-info{color:#888;font-size:.82rem;margin-bottom:10px}
.result-info strong{color:#1a0000}
.card{background:#fff;border-radius:12px;padding:16px;margin-bottom:10px;border:2px solid transparent;box-shadow:0 2px 8px rgba(0,0,0,.06)}
.card.top{border-color:#e53535;background:linear-gradient(135deg,#fff,#fff0f0)}
.ct{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;flex-wrap:wrap;margin-bottom:8px}
.fn{font-weight:700;font-size:.95rem;display:flex;align-items:center;gap:5px;flex-wrap:wrap}
.bst{background:#e53535;color:#000;font-size:.6rem;font-weight:700;padding:2px 6px;border-radius:4px;text-transform:uppercase}
.fm{display:flex;gap:8px;flex-wrap:wrap;color:#888;font-size:.76rem;margin-top:2px}
.stars{color:#f5c518}
.db{background:#fff3cd;color:#856404;border:1px solid #ffc107;padding:4px 10px;border-radius:16px;font-weight:700;font-size:.8rem;white-space:nowrap}
.db.nr{background:#d4edda;color:#155724;border-color:#28a745}
.pkgs{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}
.pk{background:#f8f9fa;border:1px solid #eee;border-radius:7px;padding:6px 10px}
.pk.noprice{border-style:dashed;border-color:#f5c5c5}
.pn{color:#888;font-size:.7rem}
.pp{font-weight:700;font-size:.88rem}
.pp.gray{color:#bbb;font-size:.75rem;font-weight:400;font-style:italic}
.acts{display:flex;gap:6px;margin-top:10px;flex-wrap:wrap}
.ag{background:#e53535;border:2px solid #e53535;cursor:pointer;padding:8px 14px;border-radius:8px;font-weight:700;font-size:.8rem;color:#000;text-decoration:none;display:inline-flex;align-items:center;gap:5px}
.ag:hover{background:#ff4444;border-color:#ff4444}
.aw-map{background:#fff;border:2px solid #cc2222;cursor:pointer;padding:8px 12px;border-radius:8px;font-size:.8rem;color:#cc2222;font-weight:600;display:inline-flex;align-items:center;gap:5px}
.aw-map:hover{background:#fff0f0}
.aw-dir{background:#fff;border:2px solid #f97316;cursor:pointer;padding:8px 12px;border-radius:8px;font-size:.8rem;color:#f97316;font-weight:600;display:inline-flex;align-items:center;gap:5px}
.aw-dir:hover{background:#fff7ed}
.aw-tel{background:#fff;border:2px solid #c41c1c;cursor:pointer;padding:8px 14px;border-radius:8px;font-size:.82rem;color:#c41c1c;font-weight:700;display:inline-flex;align-items:center;gap:6px;text-decoration:none}
.aw-tel:hover{background:#fff0f0}
.pagination{display:flex;justify-content:center;gap:6px;margin-top:16px;flex-wrap:wrap;padding-bottom:30px}
.tip-popup{display:none;position:fixed;bottom:80px;left:50%;transform:translateX(-50%);background:#1a0000;color:#fff;padding:12px 16px;border-radius:10px;font-size:.82rem;max-width:85vw;line-height:1.6;z-index:9999;box-shadow:0 4px 20px rgba(0,0,0,.4);text-align:center}
.tip-popup.show{display:block}
.tip-popup-close{display:block;margin-top:8px;font-size:.75rem;color:#ffaaaa;cursor:pointer}
.tipbox{position:fixed;background:#1a0000;color:#fff;padding:8px 12px;border-radius:8px;font-size:.78rem;max-width:220px;line-height:1.5;z-index:9999;pointer-events:none;display:none;box-shadow:0 4px 16px rgba(0,0,0,.3)}
.tipbox::after{content:'';position:absolute;bottom:-6px;left:14px;border:6px solid transparent;border-bottom:none;border-top-color:#1a0000}
.rehber-link{display:inline-block;background:#fff0f0;border:1px solid #e53535;color:#c41c1c;padding:4px 10px;border-radius:6px;font-size:.75rem;font-weight:600;text-decoration:none;margin-left:6px}
.rehber-link:hover{background:#e53535;color:#000}
.cmp-btn{background:#fff;border:2px solid #1a0000;color:#1a0000;padding:6px 14px;border-radius:8px;cursor:pointer;font-size:.78rem;font-weight:700;margin-left:auto}
.cmp-btn:hover{background:#fff0f0}
.modal-bg{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:1000;align-items:center;justify-content:center}
.modal-bg.open{display:flex}
.modal{background:#fff;border-radius:16px;width:95%;max-width:900px;max-height:90vh;overflow:auto;padding:24px;position:relative}
.modal h2{font-size:1.1rem;font-weight:800;margin-bottom:16px;color:#1a0000}
.modal-close{position:absolute;top:14px;right:16px;background:none;border:none;font-size:1.4rem;cursor:pointer;color:#888}
.sel-pkg{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:20px;align-items:flex-end}
.sel-pkg select{padding:8px 10px;border:1px solid #ddd;border-radius:8px;font-size:.82rem;outline:none}
.sel-pkg select:focus{border-color:#6366f1}
.add-pkg-btn{background:#c41c1c;color:#fff;border:none;padding:8px 14px;border-radius:8px;cursor:pointer;font-size:.8rem;font-weight:600}
.add-pkg-btn:hover{background:#a31515}
.cmp-table{width:100%;border-collapse:collapse;font-size:.82rem}
.cmp-table th{background:#1a0000;color:#fff;padding:10px 14px;text-align:left;position:relative}
.cmp-table th .rm{position:absolute;top:6px;right:8px;background:none;border:none;color:#aaa;cursor:pointer;font-size:1rem}
.cmp-table th .rm:hover{color:#fff}
.cmp-table td{padding:9px 14px;border-bottom:1px solid #f0f0f0;vertical-align:top}
.cmp-table tr:nth-child(even) td{background:#fafafa}
.cmp-table .lbl{font-weight:600;color:#555;white-space:nowrap;background:#f8f9fa!important}
.price-big{font-size:1.1rem;font-weight:800;color:#c41c1c}
.empty-cmp{color:#aaa;text-align:center;padding:30px;font-size:.9rem}
.pg{background:#fff;border:1px solid #ddd;padding:7px 12px;border-radius:8px;cursor:pointer;font-size:.8rem}
.pg.on{background:#e53535;border-color:#e53535;color:#000;font-weight:700}
</style>
</head>
<body>
<header>
  <h1>Ekspertiz<em>Bul</em></h1>
  <p>Turkiye'nin En Buyuk Oto Ekspertiz Platformu</p>
  <p style="margin-top:6px;font-size:.75rem;color:#888">Iletisim: <a href="mailto:mcolakai@gmail.com" style="color:#e53535;text-decoration:none">mcolakai@gmail.com</a> &nbsp;|&nbsp; <a href="/rehber" style="color:#e53535;text-decoration:none">&#128218; Rehber</a> &nbsp;|&nbsp; <a href="/giris" style="color:#e53535;text-decoration:none">&#128274; Giris</a> &nbsp;|&nbsp; <a href="/kayit" style="color:#e53535;text-decoration:none">&#128100; Kayit Ol</a></p>
  <div class="stats">
    <div class="stat"><div class="stat-n" id="firmCount">0</div><div class="stat-l">Firma</div></div>
    <div class="stat"><div class="stat-n">81</div><div class="stat-l">Il</div></div>
    <div class="stat"><div class="stat-n">%100</div><div class="stat-l">Ucretsiz</div></div>
  </div>
</header>
<div class="bar">
  <button class="locbtn" onclick="getLoc()">Konumumu Bul</button>
  <div class="locinfo"><span class="dot" id="dot"></span><span id="loctxt">Konum alinmadi</span></div>
  <div class="search-bar"><input type="text" id="searchInput" placeholder="Firma ara..." oninput="applyFilters()"></div>
  <div class="sel-wrap">
    <select id="ilSelect" onchange="onIlChange()"><option value="">Tum Iller</option></select>
    <select id="ilceSelect" onchange="applyFilters()"><option value="">Tum Ilceler</option></select>
  </div>
</div>
<div id="map"></div>
<div class="wrap">
  <div class="sorts">
    <span class="sl">Sirala:</span>
    <button class="sb on" id="b1" onclick="sort('dist','b1')">En Yakin</button>
    <button class="sb" id="b2" onclick="sort('rating','b2')">En Yuksek Puan</button>
    <button class="sb" id="b3" onclick="sort('reviews','b3')">En Cok Yorumlanan</button>
    <button class="fiyat-btn" id="bFiyat" onclick="toggleFiyat()">&#128176; Fiyatli Firmalar</button>
    <button class="cmp-btn" onclick="openCompare()">&#9878; Fiyat Karsilastir</button>
  </div>
  <div class="result-info" id="resultInfo"></div>
  <div id="list"></div>
  <div class="pagination" id="pagination"></div>
</div>
<script>
var ALL_FIRMS=FIRMS_PLACEHOLDER;
var PRICES=PRICES_PLACEHOLDER;
var uLat=null,uLng=null,map=null,um=null,srt='dist';
var filtered=ALL_FIRMS;
var page=1,perPage=20;
var onlyFiyatli=false;

var TERMS = {};
(function(){
  var list = [
    ['DYNO','Dinamometre testi. Motorun gercek beygir gucu ve torkunu olcer. Gizli motor sorunlarini ortaya cikarir.'],
    ['Dinamometre','Motorun gercek performansini olcen cihaz. Beygir gucu ve aktarma organi kayiplarini gosterir.'],
    ['OBD','Aracin elektronik beyin unitesine baglanan teshis sistemi. Ariza kodlarini ve silinen hata kayitlarini okur.'],
    ['ECU','Aracin ana bilgisayari. Motor ve sanziman sistemlerini kontrol eder.'],
    ['Tramer','Trafik Hasar Merkezi kaydi. Sigortali kazalarda olusturulan resmi hasar gecmisi.'],
    ['Kaporta','Aracin dis metal govdesi. Degistirilmis veya boyatilmis parcalari tespit eder.'],
    ['Sase','Aracin ana metal iskeleti. Hasar goren sase ciddi guvenlik riski olusturur.'],
    ['Conta','Motor parcalari arasindaki sizdirmazlik elemani. Kacak motor hasarinin habercisidir.'],
    ['Supansiyon','Aracin yol tutus sistemi. Amortisör, yay ve baglanti elemanlarini icerir.'],
    ['ABS','Fren sirasinda tekerleklerin kilitlenmesini onleyen guvenlik sistemi.'],
    ['ESP','Aracin kontrolden cikmamasi icin devreye giren elektronik denge sistemi.'],
    ['Airbag','Kaza aninda koruyucu hava yastigi. Patlamis airbag tehlikelidir.'],
    ['Alt Mekanik','Aracin alt kismi: rot, rotil, sanziman, diferansiyel ve aks kontrolleri.'],
    ['Mekanik Garanti','Ekspertiz sonrasi belirlenen sure icerisinde cikan arizalarin firma tarafindan karsilanmasi.'],
    ['Hasar Kaydi','TRAMER sistemindeki resmi kaza ve hasar gecmisi sorgusu.'],
    ['OBD_SLASH_Beyin','Elektronik beyin testi. Ariza kodlari, silinen hatalar ve sensor degerleri okunur.'],
    ['OBD_SLASH_ECU','Elektronik beyin testi. Ariza kodlari ve elektronik sorunlar tespit edilir.'],
    ['Fren_SLASH_Supansiyon','Fren ve amortisörlerin ozel platformda olcumlenmesi. Yol guvenligini etkiler.'],
  ];
  list.forEach(function(t){ TERMS[t[0]]=t[1]; });
})();

function showTermPopup(idx){
  var keys=Object.keys(TERMS);
  var key=keys[idx];
  if(!key||!TERMS[key])return;
  var term=key.replace(/_SLASH_/g,'/');
  document.getElementById('tipPopupText').innerHTML='<b>'+term+'</b><br>'+TERMS[key];
  document.getElementById('tipPopup').className='tip-popup show';
}


document.getElementById('firmCount').textContent=ALL_FIRMS.length.toLocaleString('tr');

// IL/ILCE dropdown olustur
(function buildDropdowns(){
  var ilMap={};
  ALL_FIRMS.forEach(function(f){
    var il=(f.city||'').trim();
    if(!il)return;
    if(!ilMap[il])ilMap[il]=new Set();
    if(f.address){
      var parts=f.address.split(',');
      // Son anlamli parcayi ilce say
      for(var i=parts.length-1;i>=0;i--){
        var p=parts[i].trim();
        if(p.length>2&&!/^[0-9]/.test(p)&&p!==il){ilMap[il].add(p);break;}
      }
    }
  });
  var iller=Object.keys(ilMap).sort(function(a,b){return a.localeCompare(b,'tr');});
  var ilSel=document.getElementById('ilSelect');
  iller.forEach(function(il){var o=document.createElement('option');o.value=il;o.textContent=il;ilSel.appendChild(o);});
  window._ilMap=ilMap;
})();

function onIlChange(){
  var il=document.getElementById('ilSelect').value;
  var ilceSel=document.getElementById('ilceSelect');
  ilceSel.innerHTML='<option value="">Tum Ilceler</option>';
  if(il&&window._ilMap[il]){
    Array.from(window._ilMap[il]).sort(function(a,b){return a.localeCompare(b,'tr');}).forEach(function(ilce){
      var o=document.createElement('option');o.value=ilce;o.textContent=ilce;ilceSel.appendChild(o);
    });
  }
  applyFilters();
}

function toggleFiyat(){
  onlyFiyatli=!onlyFiyatli;
  var btn=document.getElementById('bFiyat');
  btn.className='fiyat-btn'+(onlyFiyatli?' on':'');
  btn.innerHTML=onlyFiyatli?'&#128176; Tum Firmalar':'&#128176; Fiyatli Firmalar';
  applyFilters();
}

function applyFilters(){
  var q=document.getElementById('searchInput').value.toLowerCase().trim();
  var il=document.getElementById('ilSelect').value;
  var ilce=document.getElementById('ilceSelect').value;
  filtered=ALL_FIRMS.filter(function(f){
    var matchQ=!q||(f.name&&f.name.toLowerCase().includes(q))||(f.address&&f.address.toLowerCase().includes(q));
    var matchIl=!il||f.city===il;
    var matchIlce=!ilce||(f.address&&f.address.includes(ilce));
    var matchFiyat=!onlyFiyatli||(PRICES[f.id]&&PRICES[f.id].length>0);
    return matchQ&&matchIl&&matchIlce&&matchFiyat;
  });
  page=1;render();
}

function initMap(){
  map=L.map('map').setView([39.9,32.8],6);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'OpenStreetMap'}).addTo(map);
  ALL_FIRMS.slice(0,200).forEach(function(f){
    if(f.no_coords) return;
    L.marker([f.lat,f.lng]).addTo(map).bindPopup('<b>'+f.name+'</b><br>'+(f.address||''));
  });
}

function getLoc(){
  document.getElementById('loctxt').textContent='Aliniyor...';
  if(!navigator.geolocation){alert('Konum desteklenmiyor');return;}
  navigator.geolocation.getCurrentPosition(function(p){
    uLat=p.coords.latitude;uLng=p.coords.longitude;
    document.getElementById('dot').className='dot on';
    document.getElementById('loctxt').textContent='Konum alindi';
    map.setView([uLat,uLng],12);
    if(um)map.removeLayer(um);
    var ic=L.divIcon({html:'<div style="width:12px;height:12px;background:#e53535;border-radius:50%;border:2px solid #fff;box-shadow:0 0 6px #e53535"></div>',iconSize:[12,12],iconAnchor:[6,6]});
    um=L.marker([uLat,uLng],{icon:ic}).addTo(map).bindPopup('Siz').openPopup();
    page=1;render();
  },function(err){
    var msgs={1:'Konum izni reddedildi - telefon ayarlarindan izin verin',2:'Konum alinamadi - GPS acik mi?',3:'Zaman asimi - tekrar deneyin'};
    document.getElementById('loctxt').textContent=msgs[err.code]||'Konum alinamadi ('+err.code+')';
  },{enableHighAccuracy:true,timeout:10000,maximumAge:0});
}

function dist(a,b,c,d){
  var R=6371,dl=(c-a)*Math.PI/180,dg=(d-b)*Math.PI/180;
  var x=Math.sin(dl/2)*Math.sin(dl/2)+Math.cos(a*Math.PI/180)*Math.cos(c*Math.PI/180)*Math.sin(dg/2)*Math.sin(dg/2);
  return R*2*Math.atan2(Math.sqrt(x),Math.sqrt(1-x));
}

function sort(t,id){
  srt=t;['b1','b2','b3'].forEach(function(i){document.getElementById(i).className='sb';});
  document.getElementById(id).className='sb on';page=1;render();
}

function render(){
  var list=filtered.map(function(f){return Object.assign({},f,{d:(uLat&&uLng)?dist(uLat,uLng,f.lat,f.lng):null,pkgs:PRICES[f.id]||[]});});
  list.sort(function(a,b){
    if(srt==='dist'){if(!a.d&&!b.d)return(b.rating||0)-(a.rating||0);if(!a.d)return 1;if(!b.d)return -1;return a.d-b.d;}
    if(srt==='rating')return(b.rating||0)-(a.rating||0);
    if(srt==='reviews')return(b.reviews||0)-(a.reviews||0);
    return 0;
  });
  var total=list.length;
  var pages=Math.ceil(total/perPage)||1;
  var start=(page-1)*perPage;
  var pageItems=list.slice(start,start+perPage);
  document.getElementById('resultInfo').innerHTML='<strong>'+total.toLocaleString('tr')+'</strong> firma bulundu'+(uLat?' - konumunuza gore sirali':'');

  var h='';
  pageItems.forEach(function(f,i){
    var nr=i===0&&f.d!==null&&page===1;
    var ds=f.d!==null?f.d.toFixed(1)+' km':'';
    var stars='';
    if(f.rating){for(var s=0;s<Math.round(f.rating);s++)stars+='&#9733;';}

    // FIX: Fiyat
    var pk='';
    if(f.pkgs&&f.pkgs.length>0){
      f.pkgs.slice(0,2).forEach(function(p){pk+='<div class="pk"><div class="pn">'+p.name+'</div><div class="pp">'+p.price+' TL</div></div>';});
    } else {
      pk='<div class="pk noprice"><div class="pn">Fiyat</div><div class="pp gray">Bilgi yok</div></div>';
    }

    // FIX: Detay butonu
    var detayUrl;
    if(f.website&&f.website.trim()!==''){
      detayUrl=f.website;
    } else if(f.place_id&&f.place_id.trim()!==''){
      detayUrl='https://www.google.com/maps/place/?q=place_id:'+f.place_id;
    } else {
      detayUrl='https://www.google.com/maps/search/'+encodeURIComponent(f.name)+'/@'+f.lat+','+f.lng+',17z';
    }

    h+='<div class="card'+(nr?' top':'')+'">'+
        '<div class="ct"><div>'+
          '<div class="fn">'+f.name+(nr?'<span class="bst">En Yakin</span>':'')+(f.durum==='pasif'?'<span style="background:#dc3545;color:#fff;font-size:.6rem;font-weight:700;padding:2px 6px;border-radius:4px;margin-left:4px">KAPALI</span>':'<span style="background:#28a745;color:#fff;font-size:.6rem;font-weight:700;padding:2px 6px;border-radius:4px;margin-left:4px">ACIK</span>')+'</div>'+
          '<div class="fm">'+(stars?'<span class="stars">'+stars+'</span> '+f.rating+' ('+(f.reviews||0)+') ':'')+
          (f.city||'')+(f.address?' \u2022 '+f.address:'')+(f.phone?' \u2022 <a href="tel:'+f.phone+'" style="color:#c41c1c;text-decoration:none">'+f.phone+'</a>':'')+(f.durum_notu?'<br><span style="color:#dc3545;font-size:.75rem">&#128226; '+f.durum_notu+'</span>':'')+'</div>'+
        '</div>'+(ds?'<div class="db'+(nr?' nr':'')+'">'+ds+'</div>':'')+
        '</div>'+
        '<div class="pkgs">'+pk+'</div>'+
        '<div class="acts">'+
          '<a href="'+detayUrl+'" target="_blank" class="ag">&#128269; Detay</a>'+
          '<a href="/randevu/'+f.id+'" class="ag" style="background:#1a0000;border-color:#1a0000;color:#fff">&#128197; Randevu Al</a>'+
          '<button class="aw-map" onclick="goMap('+f.lat+','+f.lng+')">&#128205; Harita</button>'+
          '<button class="aw-dir" onclick="yol('+f.lat+','+f.lng+')">&#128388; Yol Tarifi</button>'+
          (f.phone?'<a href="tel:'+f.phone+'" class="aw-tel">&#128222; '+f.phone+'</a>':'')+
        '</div></div>';
  });
  document.getElementById('list').innerHTML=h||'<p style="color:#aaa;text-align:center;padding:30px">Sonuc bulunamadi</p>';

  var ph='';
  var sp=Math.max(1,page-2),ep=Math.min(pages,page+2);
  if(sp>1)ph+='<button class="pg" onclick="goPage(1)">1</button>';
  if(sp>2)ph+='<span style="padding:7px 4px;color:#aaa">...</span>';
  for(var i=sp;i<=ep;i++)ph+='<button class="pg'+(i===page?' on':'')+'" onclick="goPage('+i+')">'+i+'</button>';
  if(ep<pages-1)ph+='<span style="padding:7px 4px;color:#aaa">...</span>';
  if(ep<pages)ph+='<button class="pg" onclick="goPage('+pages+')">'+pages+'</button>';
  document.getElementById('pagination').innerHTML=ph;
}

function goPage(p){page=p;render();window.scrollTo({top:0,behavior:'smooth'});}
function goMap(lat,lng){map.setView([lat,lng],15);window.scrollTo({top:0,behavior:'smooth'});}
function yol(lat,lng){window.open(uLat?'https://www.google.com/maps/dir/'+uLat+','+uLng+'/'+lat+','+lng:'https://www.google.com/maps/?q='+lat+','+lng,'_blank');}

initMap();render();


// ============ KARSILASTIRMA MODALI ============
var CMP_DATA = {
  "Otorapor": {
    "website": "https://www.otorapor.com.tr",
    "phone": "0850 222 68 72",
    "packages": [
      {"name":"Kaporta/Boya Paketi","price":4900,"features":["Kaporta Boya Kontrolu","Tramer Sorgusu"]},
      {"name":"Bronz Paket","price":5500,"features":["Kaporta Boya Kontrolu","Motor Testi","Alt Mekanik","Tramer Sorgusu"]},
      {"name":"Silver Paket","price":6900,"features":["Bronz + OBD/Beyin Testi","Tramer Sorgusu"]},
      {"name":"Gold Paket","price":7800,"features":["Silver + DYNO Testi","Fren/Supansiyon","Tramer Sorgusu"]},
      {"name":"Full Paket","price":9000,"features":["Gold + Ic/Dis Ekspertiz","Conta Kaçak Testi","1 Ay Mekanik Garanti"]},
      {"name":"Luxury Paket","price":13000,"features":["Full + Airbag Testi","3 Ay Mekanik Garanti"]},
      {"name":"Premium Paket","price":16000,"features":["Luxury + Elektrikli Arac Paketi"]}
    ]
  },
  "Dynobil": {
    "website": "https://www.dynobil.com",
    "phone": "0850 840 92 92",
    "packages": [
      {"name":"Standart Paket","price":6500,"features":["Kaporta Boya Kontrolu","Arac Alti Kontrolu","Alt Mekanik","Hasar Kaydi Sorgusu"]},
      {"name":"Plus Paket","price":8500,"features":["Standart + DYNO Testi","OBD/ECU Kontrol","Fren Testi","Supansiyon Testi"]},
      {"name":"Pro Paket","price":11500,"features":["Plus + Motor-Sanziman Mekanik","Tam Kapsamli Rapor"]}
    ]
  },
  "AutoKing": {
    "website": "https://www.autoking.com.tr",
    "phone": "0850 333 54 64",
    "packages": [
      {"name":"Eko Paket","price":5000,"features":["Kaporta Boya Kontrolu","Temel Mekanik"]},
      {"name":"Standart Paket","price":7500,"features":["Eko + OBD Kontrol","Alt Mekanik","Fren Testi"]},
      {"name":"Pro Paket","price":10000,"features":["Standart + DYNO Testi","Supansiyon Testi"]},
      {"name":"King Plus Paket","price":13000,"features":["Pro + Airbag","Garanti"]}
    ]
  },
  "Arabam.com": {
    "website": "https://www.arabam.com/oto-ekspertiz",
    "phone": "0850 811 18 18",
    "packages": [
      {"name":"Temel Paket","price":5000,"features":["Kaporta Boya","Hasar Sorgusu"]},
      {"name":"Standart Paket","price":7500,"features":["Temel + Motor","Alt Mekanik","OBD"]},
      {"name":"Full Paket","price":11000,"features":["Standart + DYNO","Fren/Supansiyon","Garanti"]}
    ]
  },
  "Pilot Garage": {
    "website": "https://pilotgarage.com",
    "phone": "0850 303 74 74",
    "packages": [
      {"name":"Temel Paket","price":4500,"features":["Kaporta Boya","Temel Kontrol"]},
      {"name":"Standart Paket","price":7000,"features":["Temel + Motor","Alt Mekanik"]},
      {"name":"Full Paket","price":10500,"features":["Standart + DYNO","OBD","Fren Testi"]}
    ]
  },
  "Yamanlar": {
    "website": "https://yamanlarekspertiz.com.tr",
    "phone": "0232 469 00 00",
    "packages": [
      {"name":"Baz Paket","price":5000,"features":["Kaporta Boya","Hasar Sorgusu"]},
      {"name":"Standart Paket","price":7500,"features":["Baz + Motor","Alt Mekanik","OBD"]},
      {"name":"Yaman+ Plus","price":11000,"features":["Standart + DYNO","Motor Garanti"]}
    ]
  }
};

var cmpSelected = []; // [{firm, pkg}]

function openCompare(){
  // Firma dropdown doldur
  var fs = document.getElementById('cmpFirm');
  fs.innerHTML = '<option value="">Firma sec...</option>';
  Object.keys(CMP_DATA).forEach(function(f){ fs.innerHTML += '<option>'+f+'</option>'; });
  document.getElementById('cmpPkg').innerHTML = '<option value="">Once firma secin...</option>';
  document.getElementById('cmpModal').className = 'modal-bg open';
  renderCmpTable();
}

function closeCompare(){
  document.getElementById('cmpModal').className = 'modal-bg';
}

function onCmpFirmChange(){
  var firm = document.getElementById('cmpFirm').value;
  var ps = document.getElementById('cmpPkg');
  ps.innerHTML = '<option value="">Paket sec...</option>';
  if(firm && CMP_DATA[firm]){
    CMP_DATA[firm].packages.forEach(function(p,i){
      ps.innerHTML += '<option value="'+i+'">'+p.name+' - '+p.price.toLocaleString('tr')+' TL</option>';
    });
  }
}

function addToCompare(){
  var firm = document.getElementById('cmpFirm').value;
  var pkgIdx = document.getElementById('cmpPkg').value;
  if(!firm || pkgIdx==='') return;
  if(cmpSelected.length >= 5){ alert('En fazla 5 paket karsilastirilabilir!'); return; }
  // Ayni paketi iki kez ekleme
  var exists = cmpSelected.some(function(x){ return x.firm===firm && x.pkgIdx==pkgIdx; });
  if(exists) return;
  cmpSelected.push({firm:firm, pkgIdx:parseInt(pkgIdx)});
  renderCmpTable();
}

function removeCmp(i){
  cmpSelected.splice(i,1);
  renderCmpTable();
}

function renderCmpTable(){
  var el = document.getElementById('cmpTable');
  if(cmpSelected.length===0){
    el.innerHTML = '<p class="empty-cmp">Karsilastirmak istediginiz firma ve paketi secip "+ Ekle" butonuna basin.<br>En fazla 5 paket yan yana karsilastirilabilir.</p>';
    return;
  }

  var cols = cmpSelected.map(function(s){ return CMP_DATA[s.firm].packages[s.pkgIdx]; });
  var firms = cmpSelected.map(function(s){ return s.firm; });
  var data = cmpSelected.map(function(s){ return CMP_DATA[s.firm]; });

  var h = '<table class="cmp-table"><thead><tr><th style="background:#f8f9fa;color:#555;width:120px">Ozellik</th>';
  cmpSelected.forEach(function(s,i){
    var pkg = CMP_DATA[s.firm].packages[s.pkgIdx];
    h += '<th>'+s.firm+'<br><span style="font-size:.75rem;font-weight:400;color:#aaa">'+pkg.name+'</span><button class="rm" onclick="removeCmp('+i+')">&#10005;</button></th>';
  });
  h += '</tr></thead><tbody>';

  // Fiyat satiri
  h += '<tr><td class="lbl">Fiyat</td>';
  cols.forEach(function(p){ h += '<td><span class="price-big">'+p.price.toLocaleString('tr')+' TL</span></td>'; });
  h += '</tr>';

  // Kapsam
  h += '<tr><td class="lbl">Kapsam</td>';
  cols.forEach(function(p){
    h += '<td>'+p.features.map(function(f){ return '&#10003; '+f; }).join('<br>')+'</td>';
  });
  h += '</tr>';

  // Telefon
  h += '<tr><td class="lbl">Telefon</td>';
  data.forEach(function(d){ h += '<td><a href="tel:'+d.phone+'" style="color:#c41c1c;font-weight:600">'+d.phone+'</a></td>'; });
  h += '</tr>';

  // Website
  h += '<tr><td class="lbl">Website</td>';
  data.forEach(function(d){ h += '<td><a href="'+d.website+'" target="_blank" style="color:#c41c1c">Siteye Git &#8599;</a></td>'; });
  h += '</tr>';

  h += '</tbody></table>';
  el.innerHTML = h;
  setTimeout(applyTooltips, 50);
}

// Modal disina tiklaninca kapat
document.getElementById('cmpModal').addEventListener('click', function(e){
  if(e.target===this) closeCompare();
});

// ============ TOOLTIP ============
var TERMS = {
  'DYNO': 'Dinamometre testi. Motorun urettigi beygir gucu (HP) ve tork degerini olcer. Gizli guc kayiplarini tespit eder.',
  'Dinamometre': 'Motorun gercek performansini olcen cihaz. Beygir gucu, tork ve aktarma organi kayiplarini gosterir.',
  'OBD': 'On-Board Diagnostics. Aracin elektronik beyin unitesine baglanan teshis sistemi. Ariza kodlarini ve sensor degerlerini okur.',
  'ECU': 'Aracin ana bilgisayari (beyni). Motor, sanziman ve diger sistemleri kontrol eder. OBD ile taranir.',
  'Tramer': 'Trafik Hasar Merkezi kaydi. Aracin gecmiste kazaya karısıp karismadigini ve hasar tutarini gosteren resmi kayit.',
  'Kaporta': 'Aracin dis metal govdesi. Kapi, camurluk, kaput, tavan ve bagaj kapaklarini kapsar.',
  'Sase': 'Aracin ana iskelet yapisi. Hasar gormus sase ciddi guvenlik riski olusturur.',
  'Conta': 'Motor parcalari arasindaki sizdirmazlik elemani. Conta kaçagi motor hasarinin habercisidir.',
  'Supansiyon': 'Aracin yol tutuş sistemini olusturan parcalar. Amortisör, yay ve baglanti elemanlarini icerir.',
  'ABS': 'Anti-lock Braking System. Fren sirasinda tekerleklerin kilitlenmesini onleyen guvenlik sistemi.',
  'ESP': 'Electronic Stability Program. Aracin kontrolden cikmamasi icin devreye giren elektronik denge sistemi.',
  'Airbag': 'Kaza aninda surucu ve yolcuyu koruyan hava yastigi sistemi. Patlamis veya iptal edilmis airbag tehlikelidir.',
  'Alt Mekanik': 'Aracin altta kalan parcalari: rot, rotil, sanziman, diferansiyel, egzoz ve aks kontrollerini kapsar.',
  'Boya Olcumu': 'Mikron cinsinden boya kalinligini olcer. Yuksek deger boyali veya degisik parca olduguna isaret eder.',
  'Hasar Kaydi': 'SGK/TRAMER sistemi uzerinden sorgulanabilen resmi kaza ve hasar gecmisi.',
  'Mekanik Garanti': 'Ekspertizden sonra belirlenen sure icerisinde cikan mekanik arizalarin firma tarafindan karsilanmasi.',
};

var tipEl = document.getElementById('tipbox');

function showTip(e, term){
  if(!TERMS[term]) return;
  tipEl.textContent = TERMS[term];
  tipEl.style.display = 'block';
  moveTip(e);
}
function moveTip(e){
  var x = e.clientX + 12, y = e.clientY - 10;
  if(x + 230 > window.innerWidth) x = e.clientX - 235;
  tipEl.style.left = x + 'px';
  tipEl.style.top = y + 'px';
}
function hideTip(){ tipEl.style.display='none'; }

// Desktop: hover tooltip
document.addEventListener('mouseover', function(e){
  var t = e.target.closest('.tip');
  if(t){
    var raw=t.getAttribute('data-tkey')||'';
    var key=decodeURIComponent(raw);
    if(TERMS[key]) showTip(e, key);
  }
});
document.addEventListener('mousemove', function(e){
  if(tipEl.style.display==='block') moveTip(e);
});
document.addEventListener('mouseout', function(e){
  if(e.target.closest('.tip')) hideTip();
});

// Mobil: tikla popup ac
function closeTipPopup(){ document.getElementById('tipPopup').className='tip-popup'; }
document.addEventListener('click', function(e){
  var t = e.target.closest('.tip');
  if(t){
    var raw=t.getAttribute('data-tkey')||'';
    var key=decodeURIComponent(raw);
    var term = key.replace(/_SLASH_/g,'/');
    var desc = TERMS[key];
    if(!desc) return;
    // Mobilde popup, masaustunde de goster
    tipPopupTextEl.innerHTML = '<b>'+term+'</b><br>'+desc;
    document.getElementById('tipPopup').className='tip-popup show';
    e.stopPropagation();
  } else if(!e.target.closest('#tipPopup')){
    closeTipPopup();
  }
});

</script>
<!-- Tooltip -->
<div class="tipbox" id="tipbox"></div>
<div class="tip-popup" id="tipPopup"><span id="tipPopupText"></span><span class="tip-popup-close" onclick="closeTipPopup()">Kapat &#10005;</span></div>

<!-- Karsilastirma Modal -->
<div class="modal-bg" id="cmpModal">
  <div class="modal">
    <button class="modal-close" onclick="closeCompare()">&#10005;</button>
    <h2>&#9878; Fiyat Karsilastirma</h2>
    <div class="sel-pkg">
      <select id="cmpFirm" onchange="onCmpFirmChange()"><option value="">Firma sec...</option></select>
      <select id="cmpPkg"><option value="">Paket sec...</option></select>
      <button class="add-pkg-btn" onclick="addToCompare()">+ Ekle</button>
    </div>
    <div id="cmpTable"></div>
  </div>
</div>
</body>
</html>"""

@app.get("/", response_class=HTMLResponse)
def index(session: str = Cookie(default=None)):
    firms = load_firms()
    prices = get_prices()
    firms_json = json.dumps(firms, ensure_ascii=False)
    prices_json = json.dumps(prices, ensure_ascii=False)
    html = PAGE.replace("FIRMS_PLACEHOLDER", firms_json).replace("PRICES_PLACEHOLDER", prices_json)
    # Session durumuna gore header linklerini guncelle
    s = get_session(session)
    if s and s["role"] == "user":
        html = html.replace(
            '&#128274; Giris</a> &nbsp;|&nbsp; <a href="/kayit" style="color:#e53535;text-decoration:none">&#128100; Kayit Ol</a>',
            '&#128100; Profilim</a> &nbsp;|&nbsp; <a href="/cikis" style="color:#e53535;text-decoration:none">&#128274; Cikis</a>'
        ).replace('href="/giris"', 'href="/kullanici/panel"')
    elif s and s["role"] == "firma":
        html = html.replace(
            '&#128274; Giris</a> &nbsp;|&nbsp; <a href="/kayit" style="color:#e53535;text-decoration:none">&#128100; Kayit Ol</a>',
            '&#127970; Firma Paneli</a> &nbsp;|&nbsp; <a href="/cikis" style="color:#e53535;text-decoration:none">&#128274; Cikis</a>'
        ).replace('href="/giris"', 'href="/firma/panel"')
    # Tooltip: paket isimlerinde gecen terimleri wrap et
    TERMS_PY = {
        "DYNO": "Dinamometre testi. Motorun gercek beygir gucu ve torkunu olcer.",
        "OBD": "Aracin elektronik beyin teshis sistemi. Ariza kodlarini okur.",
        "Tramer": "Resmi kaza ve hasar gecmisi kaydi.",
        "Kaporta": "Aracin dis metal govdesi. Boya kalinligi olculerek degisik parca tespit edilir.",
        "Sase": "Aracin ana iskeleti. Hasar goren sase ciddi guvenlik riski olusturur.",
        "Conta": "Motor sizdirmazlik elemani. Kacak motor hasarinin habercisi.",
        "Supansiyon": "Yol tutus sistemi. Amortisor ve baglanti elemanlari.",
        "ABS": "Frende tekerleklerin kilitlenmesini onler.",
        "ESP": "Elektronik denge sistemi. Aracin kontrolden cikmamasi icin.",
        "Airbag": "Kaza aninda koruyucu hava yastigi. Patlamis airbag tehlikelidir.",
        "Alt Mekanik": "Aracin alt kismi: rot, rotil, sanziman, diferansiyel ve aks kontrolleri.",
        "Mekanik Garanti": "Ekspertiz sonrasi belirlenen sure icerisinde cikan arizalarin karsilanmasi.",
        "Hasar Kaydi": "TRAMER sistemindeki resmi kaza ve hasar gecmisi sorgusu.",
        "Hasar Sorgusu": "TRAMER uzerinden aracin kaza ve hasar gecmisinin sorgulanmasi.",
    }
    terms_list = list(TERMS_PY.items())
    terms_js = "var TR={" + ",".join([f'"{k}":"{v}"' for k,v in terms_list]) + "};"
    terms_keys_js = "var TRK=Object.keys(TR);"

    html = html.replace("</body></html>", f"""
<style>.tip2{{border-bottom:1px dashed #c41c1c;cursor:pointer;font-weight:700}}</style>
<div id="tpop2" style="display:none;position:fixed;bottom:70px;left:50%;transform:translateX(-50%);background:#1a0000;color:#fff;padding:14px 18px;border-radius:12px;font-size:14px;max-width:88vw;line-height:1.7;z-index:9999;box-shadow:0 4px 24px rgba(0,0,0,.6);text-align:center"></div>
<script>
{terms_js}
{terms_keys_js}
function st(i){{var el=document.getElementById("tpop2");el.innerHTML="<b>"+TRK[i]+"</b><br>"+TR[TRK[i]]+'<br><span onclick="document.getElementById(\'tpop2\').style.display=\'none\'" style="color:#ffaaaa;cursor:pointer;font-size:12px">&#10005; Kapat</span>';el.style.display="block";}}
document.addEventListener("click",function(e){{if(!e.target.closest("#tpop2")&&!e.target.closest(".tip2"))document.getElementById("tpop2").style.display="none";}});
function applyTooltips(){{
  var cmpEl=document.getElementById('cmpTable');
  if(!cmpEl)return;
  cmpEl.querySelectorAll('td').forEach(function(el){{
    if(el.querySelector('.tip2'))return;
    var h=el.innerHTML;
    var changed=false;
    TRK.forEach(function(k,i){{
      if(h.indexOf(k)!==-1){{
        h=h.split(k).join('<span class="tip2" onclick="st('+i+')">'+k+'</span>');
        changed=true;
      }}
    }});
    if(changed)el.innerHTML=h;
  }});
}}
</script>
</body></html>""")
    return html

@app.get("/rehber", response_class=HTMLResponse)
def rehber():
    return """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ekspertiz Rehberi - EkspertizBul</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:Inter,sans-serif;background:#f5f0f0;color:#1a0000}
header{background:linear-gradient(135deg,#1a0000,#3d0000);color:#fff;padding:20px 16px;text-align:center}
header h1{font-size:1.5rem;font-weight:800}
header h1 em{color:#e53535;font-style:normal}
header p{color:#aaa;font-size:.85rem;margin-top:4px}
.back{display:inline-block;margin:14px 16px;background:#fff;border:1px solid #ddd;padding:7px 14px;border-radius:8px;text-decoration:none;color:#555;font-size:.82rem}
.back:hover{border-color:#e53535;color:#c41c1c}
.wrap{max-width:820px;margin:0 auto;padding:0 16px 40px}
.section{background:#fff;border-radius:14px;padding:22px;margin-bottom:16px;box-shadow:0 2px 8px rgba(0,0,0,.06)}
.section h2{font-size:1.05rem;font-weight:800;color:#1a0000;margin-bottom:14px;padding-bottom:10px;border-bottom:2px solid #e53535}
.term{margin-bottom:14px;padding:12px 14px;background:#f8f9fa;border-radius:10px;border-left:3px solid #e53535}
.term h3{font-size:.9rem;font-weight:700;color:#1a0000;margin-bottom:4px}
.term p{font-size:.82rem;color:#555;line-height:1.6}
.term .tag{display:inline-block;background:#e53535;color:#000;font-size:.65rem;font-weight:700;padding:2px 7px;border-radius:4px;margin-bottom:6px}
.step{display:flex;gap:12px;margin-bottom:14px;align-items:flex-start}
.step-num{background:#e53535;color:#000;width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:.85rem;flex-shrink:0}
.step-txt h3{font-size:.88rem;font-weight:700;margin-bottom:3px}
.step-txt p{font-size:.8rem;color:#666;line-height:1.5}
.pkg-table{width:100%;border-collapse:collapse;font-size:.8rem;margin-top:8px}
.pkg-table th{background:#1a0000;color:#fff;padding:9px 12px;text-align:left}
.pkg-table td{padding:8px 12px;border-bottom:1px solid #eee}
.pkg-table tr:nth-child(even) td{background:#fafafa}
.pkg-table .yes{color:#c41c1c;font-weight:700}
.pkg-table .no{color:#ccc}
.faq{margin-bottom:12px}
.faq h3{font-size:.88rem;font-weight:700;color:#1a0000;margin-bottom:5px;cursor:pointer}
.faq h3:hover{color:#c41c1c}
.faq p{font-size:.82rem;color:#555;line-height:1.6;padding-left:10px;border-left:2px solid #e53535}
</style>
</head>
<body>
<header>
  <h1>Ekspertiz<em>Bul</em> Rehberi</h1>
  <p>Oto ekspertiz hakkinda bilmeniz gereken her sey</p>
</header>
<a href="/" class="back">&#8592; Ana Sayfaya Don</a>
<div class="wrap">

  <!-- TERIMLER -->
  <div class="section">
    <h2>&#128218; Terimler Sozlugu</h2>

    <div class="term"><span class="tag">TEST</span><h3>DYNO / Dinamometre Testi</h3>
    <p>Motorun urettigi gercek beygir gucu (HP) ve torku olcer. Ozel bir dinamometre platfomu uzerinde aracin cekis gucu olculerek performans kaybi, turbo sorunu veya sanziman problemi tespit edilir. Gizli motor sorunlarini ortaya cikarir.</p></div>

    <div class="term"><span class="tag">ELEKTRONIK</span><h3>OBD / ECU Kontrolu</h3>
    <p>OBD (On-Board Diagnostics), aracin elektronik beyin unitesine (ECU) baglanan teshis sistemidir. Ariza kodlari, silinen hata kayitlari, sensor degerleri ve kaza sonrasi sifirlanmis sayaclar okunur. Saticinin gizledigi elektronik sorunlari gosterir.</p></div>

    <div class="term"><span class="tag">RESMI KAYIT</span><h3>Tramer / Hasar Kaydi</h3>
    <p>Trafik Hasar Merkezi (TRAMER) kaydı. Aracin sigortali kazalarda olusturduğu hasar tutarini ve tarihini gosteren resmi veri tabanidir. Sigortasiz kazalar bu sistemde gorunmez, bu nedenle kaporta kontrolu de yapilmalidir.</p></div>

    <div class="term"><span class="tag">GOVDE</span><h3>Kaporta Kontrolu</h3>
    <p>Mikron cinsinden boya kalinlik olcumu yapilarak degistirilmis veya boyatilmis parcalar tespit edilir. Sase, podye, direk gibi ana taşiyici elemanlarin hasar gorip gormedigine bakilir. Trafik kazasi gecmisini ortaya cikarir.</p></div>

    <div class="term"><span class="tag">GOVDE</span><h3>Sase</h3>
    <p>Aracin zemine en yakin ana metal iskeletidir. Hasar goren sase tam olarak duzeltilmesi zor, bazen imkansiz bir yapisal problemdir ve aracin guvenligini dogrudan etkiler. Sase hasari aracin degerini ciddi sekilde dusurebilir.</p></div>

    <div class="term"><span class="tag">MOTOR</span><h3>Conta Kacagi</h3>
    <p>Motor parcalari arasindaki sizdirmazlik elemani olan contanin bozulmasi. Motor yagi, antifriz veya yanma gazlarinin kaçmasi motor hasarinin habercisidir. Conta kacagi erken tespit edilmezse motorun tamamen hasar gormesine yol acabilir.</p></div>

    <div class="term"><span class="tag">GUVENLIK</span><h3>Supansiyon / Amortisör Testi</h3>
    <p>Aracin yol tutusunu saglayan supansiyon sistemi ozel platformlarda test edilir. Amortisör performansi, rotil ve rot basi asınımı, yanal kayma degeri olculur. Bozuk supansiyon fren mesafesini uzatır ve surus guvensizligi yaratir.</p></div>

    <div class="term"><span class="tag">GUVENLIK</span><h3>Airbag Testi</h3>
    <p>Daha once patlamis veya devre disi bırakılmış hava yastıklarının tespiti. Bazi saticilar kaza sonrasi hava yastıgını ucuz yollarla doldurur. Bu durum bir sonraki kazada airbag'in calismamasi anlamına gelir.</p></div>

    <div class="term"><span class="tag">ELEKTRONIK</span><h3>ABS / ESP</h3>
    <p>ABS (Anti-lock Braking System) tekerleklerin frenlemede kilitlenmesini onler. ESP (Electronic Stability Program) aracin kontrolden cikmasini engeller. Bu sistemlerin calısip calismadiginin kontrolu guvenlik acisindan kritiktir.</p></div>

  </div>

  <!-- NASIL EKSPERTIZ YAPTIRILIR -->
  <div class="section">
    <h2>&#128295; Ekspertiz Nasil Yaptirilir?</h2>
    <div class="step"><div class="step-num">1</div><div class="step-txt"><h3>Firma Secin</h3><p>TSE belgeli, bagimsiz bir ekspertiz firmasi secin. Araci satin aldığınız galerinin anlasmali oldugu firma yerine bagimsiz bir firma tercih edin.</p></div></div>
    <div class="step"><div class="step-num">2</div><div class="step-txt"><h3>Paketi Belirleyin</h3><p>Aracin fiyatına ve yaşına gore paket secin. 100.000 TL uzeri araclar icin en az Gold/Full paket onerilir. Ucuz pakette gizli sorun gorunmeyebilir.</p></div></div>
    <div class="step"><div class="step-num">3</div><div class="step-txt"><h3>Randevu Alin</h3><p>Firma ile randevu alın. Ekspertiz merkezi tercihen satıcıya yakin veya notr bir lokasyonda olmali. Satici tarafindan yonlendirilen yere gitmeyin.</p></div></div>
    <div class="step"><div class="step-num">4</div><div class="step-txt"><h3>Ekspertizi Izleyin</h3><p>Mumkunse ekspertiz sirasında bulunun. Teknisyenin aracı lifte kaldirdigini, boya olcumu yaptigini ve OBD'ye baglandigini gorsel olarak doğrulayın.</p></div></div>
    <div class="step"><div class="step-num">5</div><div class="step-txt"><h3>Raporu Inceleyin</h3><p>Raporu detaylıca okuyun. Degisik parca, boya farki veya ariza kodu varsa fiyat muzakeresi yapin ya da alimdan vazgecin. Raporun dijital kopyasini alin.</p></div></div>
  </div>

  <!-- PAKET KARSILASTIRMA -->
  <div class="section">
    <h2>&#128230; Hangi Paket Benim Icin Dogru?</h2>
    <table class="pkg-table">
      <thead><tr><th>Kontrol</th><th>Temel</th><th>Standart</th><th>Full/Gold</th><th>Premium</th></tr></thead>
      <tbody>
        <tr><td>Kaporta/Boya</td><td class="yes">&#10003;</td><td class="yes">&#10003;</td><td class="yes">&#10003;</td><td class="yes">&#10003;</td></tr>
        <tr><td>Tramer Sorgusu</td><td class="yes">&#10003;</td><td class="yes">&#10003;</td><td class="yes">&#10003;</td><td class="yes">&#10003;</td></tr>
        <tr><td>Motor/Alt Mekanik</td><td class="no">&#10005;</td><td class="yes">&#10003;</td><td class="yes">&#10003;</td><td class="yes">&#10003;</td></tr>
        <tr><td>OBD/Beyin Testi</td><td class="no">&#10005;</td><td class="yes">&#10003;</td><td class="yes">&#10003;</td><td class="yes">&#10003;</td></tr>
        <tr><td>DYNO Performans</td><td class="no">&#10005;</td><td class="no">&#10005;</td><td class="yes">&#10003;</td><td class="yes">&#10003;</td></tr>
        <tr><td>Fren/Supansiyon</td><td class="no">&#10005;</td><td class="no">&#10005;</td><td class="yes">&#10003;</td><td class="yes">&#10003;</td></tr>
        <tr><td>Airbag Testi</td><td class="no">&#10005;</td><td class="no">&#10005;</td><td class="no">&#10005;</td><td class="yes">&#10003;</td></tr>
        <tr><td>Mekanik Garanti</td><td class="no">&#10005;</td><td class="no">&#10005;</td><td class="no">&#10005;</td><td class="yes">&#10003;</td></tr>
        <tr><td><b>Tahmini Fiyat</b></td><td>4.500-5.500 TL</td><td>6.500-8.000 TL</td><td>9.000-12.000 TL</td><td>13.000+ TL</td></tr>
      </tbody>
    </table>
  </div>

  <!-- SSS -->
  <div class="section">
    <h2>&#10067; Sik Sorulan Sorular</h2>
    <div class="faq"><h3>Ekspertiz zorunlu mu?</h3><p>Yasal zorunluluk olmamakla birlikte 2018'den itibaren galericilerin ekspertiz raporu sunmasi tavsiye edilmektedir. Ikinci el araclar icin kendi guvenceniz acisindan sidddetle onerilir.</p></div>
    <div class="faq"><h3>Ekspertiz ne kadar surer?</h3><p>Secilen pakete gore 45 dakika ile 2 saat arasinda degisir. DYNO testi ve tam paket yaklasik 90 dakika surer.</p></div>
    <div class="faq"><h3>Ekspertiz raporu kac gun gecerli?</h3><p>Genellikle 30 gun kabul gorur. Rapor tarihinden sonra araca mudahale edilmis olabileceginden eski raporlara guvenmemeniz onerilir.</p></div>
    <div class="faq"><h3>Satici ekspertizi reddederse ne yapmali?</h3><p>Ekspertizi reddeden satici ciddi bir uyari isaretidir. Bu durumda alimdan vazgecmeniz en dogru karar olacaktir.</p></div>
    <div class="faq"><h3>Hangi marka/model icin hangi paket?</h3><p>100.000 TL altı araclar icin Standart, 100-300.000 TL arasi icin Gold/Full, 300.000 TL uzeri ve ithal araclar icin Premium paket onerilir.</p></div>
    <div class="faq"><h3>Ekspertiz firmasini kim denetliyor?</h3><p>TSE (Turk Standartları Enstitusu) HYB-13805 belgesi veren firmalar denetim altındadır. Ekspertiz yaptirmadan once firmanin TSE belgeli olup olmadigini sorgulayabilirsiniz.</p></div>
  </div>

</div>
</body>
</html>"""



# ============================================================
# YARDIMCI FONKSIYONLAR
# ============================================================

def get_unread_count(firm_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM notifications WHERE firm_id=%s AND okundu=0", (firm_id,))
    n = cur.fetchone()
    cur.close(); conn.close()
    return list(n.values())[0] if n else 0

def add_notification(firm_id=None, user_id=None, tip="", mesaj="", appointment_id=None):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO notifications (firm_id, user_id, tip, mesaj, appointment_id) VALUES (%s,%s,%s,%s,%s)",
        (firm_id, user_id, tip, mesaj, appointment_id)
    )
    conn.commit()
    cur.close(); conn.close()

# ============================================================
# AUTH ROUTES
# ============================================================

@app.get("/kayit", response_class=HTMLResponse)
def kayit_page():
    return _kayit_html()

@app.post("/kayit", response_class=HTMLResponse)
async def kayit_post(
    tip: str = Form(...),
    ad_soyad: str = Form(default=""),
    email: str = Form(...),
    telefon: str = Form(default=""),
    sifre: str = Form(...),
    unvan: str = Form(default=""),
    yetkili_ad: str = Form(default=""),
    yetkili_gorev: str = Form(default=""),
    adres: str = Form(default=""),
    il: str = Form(default=""),
    ilce: str = Form(default="")
):
    conn = get_conn()
    cur = conn.cursor()
    if tip == "kullanici":
        cur.execute("SELECT id FROM users WHERE email=%s", (email,))
        if cur.fetchone():
            cur.close(); conn.close()
            return _kayit_html(hata="Bu email zaten kayıtlı.")
        cur.execute(
            "INSERT INTO users (ad_soyad, email, telefon, sifre_hash) VALUES (%s,%s,%s,%s)",
            (ad_soyad, email, telefon, hash_password(sifre))
        )
        conn.commit()
        cur.execute("SELECT id FROM users WHERE email=%s", (email,))
        user = cur.fetchone()
        cur.close(); conn.close()
        token = create_session(user_id=user["id"], role="user")
        resp = RedirectResponse("/kullanici/panel", status_code=303)
        resp.set_cookie("session", token, max_age=604800, httponly=True)
        return resp
    else:
        cur.execute("SELECT id FROM firm_accounts WHERE email=%s", (email,))
        if cur.fetchone():
            cur.close(); conn.close()
            return _kayit_html(hata="Bu email zaten kayıtlı.")
        cur.execute(
            "INSERT INTO firm_accounts (unvan, yetkili_ad, yetkili_gorev, adres, il, ilce, telefon, email, sifre_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (unvan, yetkili_ad, yetkili_gorev, adres, il, ilce, telefon, email, hash_password(sifre))
        )
        conn.commit()
        cur.execute("SELECT id FROM firm_accounts WHERE email=%s", (email,))
        firm = cur.fetchone()
        cur.close(); conn.close()
        token = create_session(firm_id=firm["id"], role="firma")
        resp = RedirectResponse("/firma/panel", status_code=303)
        resp.set_cookie("session", token, max_age=604800, httponly=True)
        return resp

@app.get("/giris", response_class=HTMLResponse)
def giris_page():
    return _giris_html()

@app.post("/giris", response_class=HTMLResponse)
async def giris_post(tip: str = Form(...), email: str = Form(...), sifre: str = Form(...)):
    conn = get_conn()
    cur = conn.cursor()
    if tip == "kullanici":
        cur.execute("SELECT * FROM users WHERE email=%s", (email,))
        row = cur.fetchone()
        cur.close(); conn.close()
        if not row or not check_password(sifre, row["sifre_hash"]):
            return _giris_html(hata="Email veya şifre hatalı.")
        token = create_session(user_id=row["id"], role="user")
        resp = RedirectResponse("/kullanici/panel", status_code=303)
        resp.set_cookie("session", token, max_age=604800, httponly=True)
        return resp
    else:
        cur.execute("SELECT * FROM firm_accounts WHERE email=%s", (email,))
        row = cur.fetchone()
        cur.close(); conn.close()
        if not row or not check_password(sifre, row["sifre_hash"]):
            return _giris_html(hata="Email veya şifre hatalı.")
        token = create_session(firm_id=row["id"], role="firma")
        resp = RedirectResponse("/firma/panel", status_code=303)
        resp.set_cookie("session", token, max_age=604800, httponly=True)
        return resp

@app.get("/cikis")
def cikis(session: str = Cookie(default=None)):
    delete_session(session)
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie("session")
    return resp

# ============================================================
# KULLANICI PANELI
# ============================================================

@app.get("/kullanici/panel", response_class=HTMLResponse)
def kullanici_panel(session: str = Cookie(default=None)):
    s = get_session(session)
    if not s or s["role"] != "user":
        return RedirectResponse("/giris?tip=kullanici", status_code=303)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id=%s", (s["user_id"],))
    user = cur.fetchone()
    cur.execute("""
        SELECT a.*, f.unvan as firma_unvan, f.telefon as firma_tel
        FROM appointments a JOIN firm_accounts f ON f.id=a.firm_id
        WHERE a.user_id=%s ORDER BY a.created_at DESC
    """, (s["user_id"],))
    randevular = cur.fetchall()
    cur.close(); conn.close()
    return _kullanici_panel_html(user, randevular)

@app.post("/randevu/olustur")
async def randevu_olustur(
    request: Request,
    firm_id: int = Form(...),
    tarih: str = Form(...),
    saat: str = Form(...),
    arac_marka: str = Form(default=""),
    arac_model: str = Form(default=""),
    arac_yil: str = Form(default=""),
    paket: str = Form(default=""),
    notlar: str = Form(default=""),
    session: str = Cookie(default=None)
):
    s = get_session(session)
    if not s or s["role"] != "user":
        return JSONResponse({"error": "Giris gerekli"}, status_code=401)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id=%s", (s["user_id"],))
    user = cur.fetchone()
    cur.execute("SELECT * FROM firm_accounts WHERE id=%s", (firm_id,))
    firm = cur.fetchone()
    if not firm:
        return JSONResponse({"error": "Firma bulunamadi"}, status_code=404)
    if not paket or not paket.strip():
        return JSONResponse({"error": "Lutfen bir paket secin"})
    # Firma pasif mi?
    if firm.get("durum") == "pasif":
        notu = firm.get("durum_notu") or "Firma simdilik randevu almiyor."
        return JSONResponse({"error": f"Firma su an kapali: {notu}"})
    # Calisma saati kontrolu
    import datetime
    gun_map = {0:"pazartesi",1:"sali",2:"carsamba",3:"persembe",4:"cuma",5:"cumartesi",6:"pazar"}
    try:
        tarih_dt = datetime.datetime.strptime(tarih, "%Y-%m-%d")
        gun_adi = gun_map[tarih_dt.weekday()]
        cur.execute("SELECT * FROM firm_working_hours WHERE firm_id=%s", (firm_id,))
        wh = cur.fetchone()
        if wh:
            if wh[f"{gun_adi}_kapali"]:
                return JSONResponse({"error": f"Firma {tarih} tarihinde kapali."})
            acilis = wh[f"{gun_adi}_acilis"]
            kapanis = wh[f"{gun_adi}_kapanis"]
            if acilis and kapanis and saat:
                if not (acilis <= saat <= kapanis):
                    return JSONResponse({"error": f"Secilen saat calisma saatleri disinda. Calisma saatleri: {acilis} - {kapanis}"})
    except Exception as e:
        print(f"Calisma saati kontrol hatasi: {e}")
    cur.execute(
        "INSERT INTO appointments (user_id,firm_id,tarih,saat,arac_marka,arac_model,arac_yil,paket,notlar) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
        (s["user_id"], firm_id, tarih, saat, arac_marka, arac_model, arac_yil, paket, notlar)
    )
    conn.commit()
    apt = cur.fetchone()
    arac = f"{arac_marka} {arac_model} {arac_yil}".strip() or "Belirtilmedi"
    add_notification(
        firm_id=firm_id,
        tip="yeni_randevu",
        mesaj=f"Yeni randevu: {user['ad_soyad']} - {tarih} {saat} - {arac}",
        appointment_id=apt["id"]
    )
    conn.close()
    if firm:
        email_yeni_randevu_firma(firm["email"], firm["unvan"], user["ad_soyad"], tarih, saat, arac, paket)
    return JSONResponse({"success": True, "message": "Randevu talebiniz gönderildi!"})

# ============================================================
# FIRMA PANELI
# ============================================================

@app.get("/firma/panel", response_class=HTMLResponse)
def firma_panel(session: str = Cookie(default=None)):
    s = get_session(session)
    if not s or s["role"] != "firma":
        return RedirectResponse("/giris?tip=firma", status_code=303)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM firm_accounts WHERE id=%s", (s["firm_id"],))
    firm = cur.fetchone()
    cur.execute("""
        SELECT a.*, u.ad_soyad, u.telefon as user_tel, u.email as user_email
        FROM appointments a JOIN users u ON u.id=a.user_id
        WHERE a.firm_id=%s ORDER BY a.tarih DESC, a.saat DESC
    """, (s["firm_id"],))
    randevular = cur.fetchall()
    cur.execute(
        "SELECT * FROM notifications WHERE firm_id=%s ORDER BY created_at DESC LIMIT 20",
        (s["firm_id"],)
    )
    bildirimler = cur.fetchall()
    cur.execute("SELECT * FROM firm_packages WHERE firm_id=%s AND aktif=1", (s["firm_id"],))
    paketler = cur.fetchall()
    unread = get_unread_count(s["firm_id"])
    cur.close(); conn.close()
    return _firma_panel_html(firm, randevular, bildirimler, paketler, unread)

@app.post("/firma/randevu/guncelle")
async def randevu_guncelle(
    appointment_id: int = Form(...),
    durum: str = Form(...),
    session: str = Cookie(default=None)
):
    s = get_session(session)
    if not s or s["role"] != "firma":
        return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE appointments SET durum=%s WHERE id=%s AND firm_id=%s",
                 (durum, appointment_id, s["firm_id"]))
    cur.execute("""
        SELECT a.*, u.email as user_email, u.ad_soyad, f.unvan
        FROM appointments a JOIN users u ON u.id=a.user_id
        JOIN firm_accounts f ON f.id=a.firm_id
        WHERE a.id=%s
    """, (appointment_id,))
    apt = cur.fetchone()
    if apt:
        add_notification(
            user_id=apt["user_id"],
            tip="randevu_guncelleme",
            mesaj=f"Randevunuz {durum}: {apt['unvan']} - {apt['tarih']} {apt['saat']}",
            appointment_id=appointment_id
        )
        email_randevu_guncelleme_kullanici(
            apt["user_email"], apt["ad_soyad"], apt["unvan"],
            apt["tarih"], apt["saat"], durum
        )
    conn.commit()
    cur.close(); conn.close()
    return JSONResponse({"success": True})

@app.get("/firma/bildirimler", response_class=JSONResponse)
def firma_bildirimler(session: str = Cookie(default=None)):
    s = get_session(session)
    if not s or s["role"] != "firma":
        return JSONResponse({"count": 0, "items": []})
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM notifications WHERE firm_id=%s AND okundu=0 ORDER BY created_at DESC",
        (s["firm_id"],)
    )
    items = cur.fetchall()
    cur.execute("UPDATE notifications SET okundu=1 WHERE firm_id=%s", (s["firm_id"],))
    conn.commit()
    cur.close(); conn.close()
    return JSONResponse({"count": len(items), "items": [dict(i) for i in items]})

@app.post("/firma/paket/ekle")
async def paket_ekle(
    paket_adi: str = Form(...),
    fiyat: int = Form(...),
    icerik: str = Form(default=""),
    session: str = Cookie(default=None)
):
    s = get_session(session)
    if not s or s["role"] != "firma":
        return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO firm_packages (firm_id, paket_adi, fiyat, icerik) VALUES (%s,%s,%s,%s)",
                 (s["firm_id"], paket_adi, fiyat, icerik))
    conn.commit()
    cur.close(); conn.close()
    return JSONResponse({"success": True})

@app.post("/firma/paket/sil")
async def paket_sil(paket_id: int = Form(...), session: str = Cookie(default=None)):
    s = get_session(session)
    if not s or s["role"] != "firma":
        return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE firm_packages SET aktif=0 WHERE id=%s AND firm_id=%s", (paket_id, s["firm_id"]))
    conn.commit()
    cur.close(); conn.close()
    return JSONResponse({"success": True})

# ============================================================
# HTML SAYFALAR
# ============================================================

def _base_style():
    return """
    <style>
    *{margin:0;padding:0;box-sizing:border-box}
    body{font-family:Inter,sans-serif;background:#f5f0f0;color:#1a0000;min-height:100vh}
    .topbar{background:linear-gradient(135deg,#1a0000,#3d0000);color:#fff;padding:14px 20px;display:flex;align-items:center;justify-content:space-between}
    .topbar a{color:#fff;text-decoration:none;font-size:.85rem}
    .topbar h1{font-size:1.1rem;font-weight:800}
    .topbar h1 em{color:#e53535;font-style:normal}
    .back{display:inline-block;margin:14px 16px;background:#fff;border:1px solid #ddd;padding:7px 14px;border-radius:8px;text-decoration:none;color:#555;font-size:.82rem}
    .back:hover{border-color:#e53535;color:#e53535}
    .wrap{max-width:860px;margin:0 auto;padding:16px}
    .card{background:#fff;border-radius:12px;padding:20px;margin-bottom:14px;box-shadow:0 2px 8px rgba(0,0,0,.06)}
    .card h2{font-size:1rem;font-weight:700;margin-bottom:14px;padding-bottom:10px;border-bottom:2px solid #e53535}
    .form-group{margin-bottom:12px}
    .form-group label{display:block;font-size:.82rem;font-weight:600;margin-bottom:4px;color:#555}
    .form-group input,.form-group select,.form-group textarea{width:100%;padding:9px 12px;border:1px solid #ddd;border-radius:8px;font-size:.85rem;outline:none;font-family:inherit}
    .form-group input:focus,.form-group select:focus{border-color:#e53535}
    .btn{background:#e53535;color:#fff;border:none;padding:10px 20px;border-radius:8px;cursor:pointer;font-weight:700;font-size:.85rem}
    .btn:hover{background:#c41c1c}
    .btn-outline{background:#fff;color:#e53535;border:2px solid #e53535;padding:8px 16px;border-radius:8px;cursor:pointer;font-weight:600;font-size:.82rem}
    .btn-outline:hover{background:#fff0f0}
    .btn-green{background:#28a745;color:#fff;border:none;padding:7px 14px;border-radius:8px;cursor:pointer;font-weight:600;font-size:.8rem}
    .btn-red{background:#dc3545;color:#fff;border:none;padding:7px 14px;border-radius:8px;cursor:pointer;font-weight:600;font-size:.8rem}
    .badge{display:inline-block;padding:3px 8px;border-radius:10px;font-size:.72rem;font-weight:700}
    .badge-beklemede{background:#fff3cd;color:#856404}
    .badge-onaylandi{background:#d4edda;color:#155724}
    .badge-reddedildi{background:#f8d7da;color:#721c24}
    .badge-tamamlandi{background:#d1ecf1;color:#0c5460}
    .alert{padding:10px 14px;border-radius:8px;margin-bottom:14px;font-size:.85rem}
    .alert-error{background:#f8d7da;color:#721c24;border:1px solid #f5c6cb}
    .alert-success{background:#d4edda;color:#155724;border:1px solid #c3e6cb}
    .notif-dot{background:#e53535;color:#fff;border-radius:50%;width:20px;height:20px;display:inline-flex;align-items:center;justify-content:center;font-size:.7rem;font-weight:700;margin-left:6px}
    </style>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
    """

def _topbar(title="", back_url="/", back_label="Ana Sayfa"):
    return f"""
    <div class="topbar">
      <div><a href="{back_url}">← {back_label}</a></div>
      <h1>Ekspertiz<em>Bul</em> {title}</h1>
      <a href="/cikis">Çıkış</a>
    </div>"""

def _giris_html(hata=None):
    h = "" if not hata else f'<div class="alert alert-error">{hata}</div>'
    return f"""<!DOCTYPE html><html lang="tr"><head><meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Giriş - EkspertizBul</title>{_base_style()}</head><body>
    {_topbar("Giriş", "/", "Ana Sayfa")}
    <div class="wrap" style="max-width:440px">
    {h}
    <div class="card">
      <h2>Giriş Yap</h2>
      <div style="display:flex;gap:8px;margin-bottom:16px">
        <button onclick="setTip('kullanici')" id="tab-k" class="btn" style="flex:1">Kullanıcı</button>
        <button onclick="setTip('firma')" id="tab-f" class="btn-outline" style="flex:1">Firma</button>
      </div>
      <form method="post" action="/giris">
        <input type="hidden" name="tip" id="tip-input" value="kullanici">
        <div class="form-group"><label>Email</label><input type="email" name="email" required></div>
        <div class="form-group"><label>Şifre</label><input type="password" name="sifre" required></div>
        <button type="submit" class="btn" style="width:100%">Giriş Yap</button>
      </form>
      <p style="text-align:center;margin-top:14px;font-size:.82rem;color:#888">
        Hesabın yok mu? <a href="/kayit" style="color:#e53535">Kayıt Ol</a>
      </p>
    </div></div>
    <script>
    function setTip(t){{
      document.getElementById('tip-input').value=t;
      document.getElementById('tab-k').className=t==='kullanici'?'btn':'btn-outline';
      document.getElementById('tab-f').className=t==='firma'?'btn':'btn-outline';
    }}
    </script></body></html>"""

def _kayit_html(hata=None):
    h = "" if not hata else f'<div class="alert alert-error">{hata}</div>'
    gorevler = ["İş Yeri Sahibi","Müdür","Yetkili Personel","Şube Müdürü","Diğer"]
    gorev_opts = "".join([f'<option>{g}</option>' for g in gorevler])
    return f"""<!DOCTYPE html><html lang="tr"><head><meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Kayıt - EkspertizBul</title>{_base_style()}</head><body>
    {_topbar("Kayıt", "/", "Ana Sayfa")}
    <div class="wrap" style="max-width:500px">
    {h}
    <div class="card">
      <h2>Kayıt Ol</h2>
      <div style="display:flex;gap:8px;margin-bottom:16px">
        <button onclick="setTip('kullanici')" id="tab-k" class="btn" style="flex:1">Kullanıcı</button>
        <button onclick="setTip('firma')" id="tab-f" class="btn-outline" style="flex:1">Firma</button>
      </div>
      <form method="post" action="/kayit">
        <input type="hidden" name="tip" id="tip-input" value="kullanici">
        <div id="kullanici-fields">
          <div class="form-group"><label>Ad Soyad</label><input type="text" name="ad_soyad"></div>
          <div class="form-group"><label>Telefon</label><input type="tel" name="telefon"></div>
        </div>
        <div id="firma-fields" style="display:none">
          <div class="form-group"><label>Firma Ünvanı</label><input type="text" name="unvan"></div>
          <div class="form-group"><label>Yetkili Adı Soyadı</label><input type="text" name="yetkili_ad"></div>
          <div class="form-group"><label>Görevi</label>
            <select name="yetkili_gorev">{gorev_opts}</select></div>
          <div class="form-group"><label>İl</label>
            <select name="il" id="il-select" onchange="loadIlceler(this.value)">
              <option value="">İl seçin...</option>
              <option value="Adana">Adana</option>
<option value="Adıyaman">Adıyaman</option>
<option value="Afyonkarahisar">Afyonkarahisar</option>
<option value="Aksaray">Aksaray</option>
<option value="Amasya">Amasya</option>
<option value="Ankara">Ankara</option>
<option value="Antalya">Antalya</option>
<option value="Ardahan">Ardahan</option>
<option value="Artvin">Artvin</option>
<option value="Aydın">Aydın</option>
<option value="Ağrı">Ağrı</option>
<option value="Balıkesir">Balıkesir</option>
<option value="Bartın">Bartın</option>
<option value="Batman">Batman</option>
<option value="Bayburt">Bayburt</option>
<option value="Bilecik">Bilecik</option>
<option value="Bingöl">Bingöl</option>
<option value="Bitlis">Bitlis</option>
<option value="Bolu">Bolu</option>
<option value="Burdur">Burdur</option>
<option value="Bursa">Bursa</option>
<option value="Denizli">Denizli</option>
<option value="Diyarbakır">Diyarbakır</option>
<option value="Düzce">Düzce</option>
<option value="Edirne">Edirne</option>
<option value="Elazığ">Elazığ</option>
<option value="Erzincan">Erzincan</option>
<option value="Erzurum">Erzurum</option>
<option value="Eskişehir">Eskişehir</option>
<option value="Gaziantep">Gaziantep</option>
<option value="Giresun">Giresun</option>
<option value="Gümüşhane">Gümüşhane</option>
<option value="Hakkari">Hakkari</option>
<option value="Hatay">Hatay</option>
<option value="Isparta">Isparta</option>
<option value="Iğdır">Iğdır</option>
<option value="Kahramanmaraş">Kahramanmaraş</option>
<option value="Karabük">Karabük</option>
<option value="Karaman">Karaman</option>
<option value="Kars">Kars</option>
<option value="Kastamonu">Kastamonu</option>
<option value="Kayseri">Kayseri</option>
<option value="Kilis">Kilis</option>
<option value="Kocaeli">Kocaeli</option>
<option value="Konya">Konya</option>
<option value="Kütahya">Kütahya</option>
<option value="Kırklareli">Kırklareli</option>
<option value="Kırıkkale">Kırıkkale</option>
<option value="Kırşehir">Kırşehir</option>
<option value="Malatya">Malatya</option>
<option value="Manisa">Manisa</option>
<option value="Mardin">Mardin</option>
<option value="Mersin">Mersin</option>
<option value="Muğla">Muğla</option>
<option value="Muş">Muş</option>
<option value="Nevşehir">Nevşehir</option>
<option value="Niğde">Niğde</option>
<option value="Ordu">Ordu</option>
<option value="Osmaniye">Osmaniye</option>
<option value="Rize">Rize</option>
<option value="Sakarya">Sakarya</option>
<option value="Samsun">Samsun</option>
<option value="Siirt">Siirt</option>
<option value="Sinop">Sinop</option>
<option value="Sivas">Sivas</option>
<option value="Tekirdağ">Tekirdağ</option>
<option value="Tokat">Tokat</option>
<option value="Trabzon">Trabzon</option>
<option value="Tunceli">Tunceli</option>
<option value="Uşak">Uşak</option>
<option value="Van">Van</option>
<option value="Yalova">Yalova</option>
<option value="Yozgat">Yozgat</option>
<option value="Zonguldak">Zonguldak</option>
<option value="Çanakkale">Çanakkale</option>
<option value="Çankırı">Çankırı</option>
<option value="Çorum">Çorum</option>
<option value="İstanbul">İstanbul</option>
<option value="İzmir">İzmir</option>
<option value="Şanlıurfa">Şanlıurfa</option>
<option value="Şırnak">Şırnak</option>
            </select></div>
          <div class="form-group"><label>İlçe</label>
            <input type="text" name="ilce" id="ilce-input" placeholder="İlçe giriniz"></div>
          <div class="form-group"><label>Açık Adres</label><textarea name="adres" rows="2" placeholder="Mahalle, cadde, sokak..."></textarea></div>
          <div class="form-group"><label>Telefon</label><input type="tel" name="telefon"></div>
        </div>
        <div class="form-group"><label>Email</label><input type="email" name="email" required></div>
        <div class="form-group"><label>Şifre</label><input type="password" name="sifre" required minlength="6"></div>
        <button type="submit" class="btn" style="width:100%">Kayıt Ol</button>
      </form>
      <p style="text-align:center;margin-top:14px;font-size:.82rem;color:#888">
        Zaten hesabın var mı? <a href="/giris" style="color:#e53535">Giriş Yap</a>
      </p>
    </div></div>
    <script>
    function setTip(t){{
      document.getElementById('tip-input').value=t;
      document.getElementById('tab-k').className=t==='kullanici'?'btn':'btn-outline';
      document.getElementById('tab-f').className=t==='firma'?'btn':'btn-outline';
      document.getElementById('kullanici-fields').style.display=t==='kullanici'?'block':'none';
      document.getElementById('firma-fields').style.display=t==='firma'?'block':'none';
    }}
    </script></body></html>"""

def _kullanici_panel_html(user, randevular):
    rows = ""
    for r in randevular:
        arac = f"{r['arac_marka']} {r['arac_model']} {r['arac_yil']}".strip() or "-"
        rid = r['id']
        aksiyonlar = ""
        if r['durum'] not in ['tamamlandi','iptal']:
            aksiyonlar += f"<button class='btn-red' style='font-size:.72rem;padding:4px 8px' onclick='iptalEt({rid})'>İptal</button> "
            if r['durum'] == 'beklemede':
                aksiyonlar += f"<button class='btn-outline' style='font-size:.72rem;padding:4px 8px' onclick='saatDegistir({rid})'>Saat</button> "
        if r['durum'] == 'onaylandi':
            aksiyonlar += f"<button class='btn-green' style='font-size:.72rem;padding:4px 8px' onclick='hizmetAldim({rid})'>&#9989; Hizmet Aldim</button> "
        aksiyonlar += f"<button class='btn-outline' style='font-size:.72rem;padding:4px 8px' onclick='iletisim({rid})'>📞</button> "
        aksiyonlar += f"<a href='/randevu/{rid}/mesajlar' class='btn-outline' style='font-size:.72rem;padding:4px 8px'>&#128172; Mesaj</a> "
        if r['durum'] == 'tamamlandi':
            aksiyonlar += f"<a href='/randevu/{rid}/puan' class='btn-green' style='font-size:.72rem;padding:4px 8px;text-decoration:none'>&#11088; Puan</a>"
        rows += f"""<tr>
          <td style="padding:8px">{r['firma_unvan']}</td>
          <td style="padding:8px">{r['tarih']} {r['saat']}</td>
          <td style="padding:8px">{arac}</td>
          <td style="padding:8px">{r['paket'] or '-'}</td>
          <td style="padding:8px"><span class="badge badge-{r['durum']}">{r['durum'].title()}</span></td>
          <td style="padding:8px">{aksiyonlar}</td>
        </tr>"""
    if not rows:
        rows = '<tr><td colspan="6" style="padding:16px;text-align:center;color:#aaa">Henüz randevu yok</td></tr>'
    return f"""<!DOCTYPE html><html lang='tr'><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
    <title>Profilim - EkspertizBul</title>{_base_style()}</head><body>
    {_topbar("", "/", "Ana Sayfa")}
    <div class="wrap">
      <div class="card" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px">
        <div>
          <h2>&#128100; Hosgeldin, {user['ad_soyad']}</h2>
          <p style="font-size:.85rem;color:#666">{user['email']}</p>
        </div>
        <a href='/kullanici/profil' class='btn-outline' style='font-size:.82rem'>&#9998; Profili Duzenle</a>
        <a href='/mesajlarim' class='btn-outline' style='font-size:.82rem;margin-left:8px'>&#128172; Mesajlarim</a>
      </div>
      <div class="card">
        <h2>&#128197; Randevularim</h2>
        <div style="overflow-x:auto">
        <table style="width:100%;border-collapse:collapse;font-size:.82rem">
          <thead><tr style="background:#f5f0f0">
            <th style="padding:8px;text-align:left">Firma</th>
            <th style="padding:8px;text-align:left">Tarih</th>
            <th style="padding:8px;text-align:left">Araç</th>
            <th style="padding:8px;text-align:left">Paket</th>
            <th style="padding:8px;text-align:left">Durum</th>
            <th style="padding:8px;text-align:left">İşlem</th>
          </tr></thead>
          <tbody>{rows}</tbody>
        </table></div>
      </div>
    </div>
    <!-- Iletisim Modal -->
    <div id="iletisimModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:1000;align-items:center;justify-content:center">
      <div style="background:#fff;border-radius:14px;width:90%;max-width:380px;padding:24px;text-align:center">
        <h3 style="margin-bottom:16px">&#128222; Iletisim Bilgisi</h3>
        <div id="iletisimBilgi"></div>
        <button onclick="document.getElementById('iletisimModal').style.display='none'" class="btn" style="margin-top:16px;width:100%">Kapat</button>
      </div>
    </div>
    <!-- Saat Degisiklik Modal -->
    <div id="saatModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:1000;align-items:center;justify-content:center">
      <div style="background:#fff;border-radius:14px;width:90%;max-width:380px;padding:24px">
        <h3 style="margin-bottom:16px">&#128336; Saat Degisikligi</h3>
        <input type="hidden" id="saatAptId">
        <div class="form-group"><label>Yeni Tarih</label><input type="date" id="yeniTarih"></div>
        <div class="form-group"><label>Yeni Saat</label>
          <select id="yeniSaat"><option value='08:00'>08:00</option><option value='09:00'>09:00</option><option value='10:00'>10:00</option><option value='11:00'>11:00</option><option value='12:00'>12:00</option><option value='13:00'>13:00</option><option value='14:00'>14:00</option><option value='15:00'>15:00</option><option value='16:00'>16:00</option><option value='17:00'>17:00</option><option value='18:00'>18:00</option></select></div>
        <button onclick="saatGuncelle()" class="btn" style="width:100%;margin-top:8px">Guncelle</button>
        <button onclick="document.getElementById('saatModal').style.display='none'" class="btn-outline" style="width:100%;margin-top:8px">Vazgec</button>
      </div>
    </div>
    <script>
    function hizmetAldim(id){{
      if(!confirm('Hizmeti aldiginizi onayliyor musunuz? Bu islem geri alinamaz.'))return;
      var fd=new FormData();fd.append('appointment_id',id);fd.append('durum','tamamlandi');
      fetch('/randevu/kullanici-tamamla',{{method:'POST',body:fd}})
        .then(r=>r.json())
        .then(d=>{{if(d.success)location.reload();else alert(d.error);}});
    }}
    function iptalEt(id){{
      if(!confirm('Randevuyu iptal etmek istediginize emin misiniz?'))return;
      var fd=new FormData();fd.append('appointment_id',id);
      fetch('/randevu/iptal',{{method:'POST',body:fd}}).then(r=>r.json()).then(d=>{{
        if(d.success)location.reload();else alert(d.error);
      }});
    }}
    function saatDegistir(id){{
      document.getElementById('saatAptId').value=id;
      document.getElementById('saatModal').style.display='flex';
    }}
    function saatGuncelle(){{
      var fd=new FormData();
      fd.append('appointment_id',document.getElementById('saatAptId').value);
      fd.append('yeni_tarih',document.getElementById('yeniTarih').value);
      fd.append('yeni_saat',document.getElementById('yeniSaat').value);
      if(!fd.get('yeni_tarih')){{alert('Tarih secin!');return;}}
      fetch('/randevu/saat-guncelle',{{method:'POST',body:fd}}).then(r=>r.json()).then(d=>{{
        if(d.success){{document.getElementById('saatModal').style.display='none';location.reload();}}
        else alert(d.error);
      }});
    }}
    function iletisim(id){{
      fetch('/randevu/'+id+'/iletisim').then(r=>r.json()).then(d=>{{
        if(d.error){{alert(d.error);return;}}
        document.getElementById('iletisimBilgi').innerHTML=
          '<p style="font-size:1rem;font-weight:700">'+d.ad+'</p>'+
          '<p style="margin:8px 0"><a href="tel:'+d.telefon+'" style="color:#e53535;font-size:1.1rem;font-weight:700">📞 '+d.telefon+'</a></p>'+
          '<p style="font-size:.85rem;color:#666">'+d.email+'</p>';
        document.getElementById('iletisimModal').style.display='flex';
      }});
    }}
    </script>
    </body></html>"""

def _firma_panel_html(firm, randevular, bildirimler, paketler, unread):
    # Randevu satirlari
    rows = ""
    for r in randevular:
        arac = f"{r['arac_marka']} {r['arac_model']} {r['arac_yil']}".strip() or "-"
        onay_btns = ""
        rid = r['id']
        if r["durum"] == "beklemede":
            onay_btns = f'<button class="btn-green" onclick="updateApt({rid},\'onaylandi\')">Onayla</button> <button class="btn-red" onclick="updateApt({rid},\'reddedildi\')" style="margin-left:4px">Reddet</button>'
        elif r["durum"] == "onaylandi":
            onay_btns = '<span style="color:#28a745;font-size:.78rem;font-weight:600">&#9989; Onaylandi - musteri tamamlayacak</span>'
        else:
            onay_btns = ""
        iletisim_btn = f'<a href="/randevu/{rid}/mesajlar" class="btn-outline" style="font-size:.72rem;padding:4px 8px">&#128172; Mesaj</a>'
        saat_btn = ""
        iptal_btn = ""
        if r["durum"] not in ["tamamlandi","iptal"]:
            saat_btn = f'<button class="btn-outline" style="font-size:.72rem;padding:4px 8px;margin-top:4px" onclick="firmaSaatDegistir({rid})">&#128336; Saat</button>'
            iptal_btn = f'<button class="btn-red" style="font-size:.72rem;padding:4px 8px;margin-top:4px" onclick="firmaIptal({rid})">&#10060; Iptal</button>'
        rows += f"""<tr>
          <td style="padding:8px"><b>{r['ad_soyad']}</b><br><small style="color:#888">&#128222; {r['user_tel'] or 'Tel yok'}</small><br><small style="color:#888">{r['user_email'] or ''}</small></td>
          <td style="padding:8px">{r['tarih']}<br><small>{r['saat']}</small></td>
          <td style="padding:8px">{arac}</td>
          <td style="padding:8px">{r['paket'] or '-'}</td>
          <td style="padding:8px"><span class="badge badge-{r['durum']}">{r['durum'].title()}</span></td>
          <td style="padding:8px">{onay_btns}<br>{iletisim_btn}<br>{saat_btn}<br>{iptal_btn}</td>
        </tr>"""
    if not rows:
        rows = '<tr><td colspan="6" style="padding:16px;text-align:center;color:#aaa">Henüz randevu yok</td></tr>'

    # Paket satirlari
    pkg_rows = ""
    for p in paketler:
        pkg_rows += f"""<tr>
          <td style="padding:8px">{p['paket_adi']}</td>
          <td style="padding:8px">{p['fiyat']:,} TL</td>
          <td style="padding:8px;font-size:.78rem;color:#666">{p['icerik'] or '-'}</td>
          <td style="padding:8px"><button class="btn-red" onclick="silPaket({p['id']})">Sil</button></td>
        </tr>"""

    # Bildirim badge
    notif_badge = f'<span class="notif-dot">{unread}</span>' if unread > 0 else ''

    durum_badge = '<span style="background:#dc3545;color:#fff;font-size:.7rem;padding:2px 8px;border-radius:4px;margin-left:6px">KAPALI</span>' if firm.get('durum')=='pasif' else '<span style="background:#28a745;color:#fff;font-size:.7rem;padding:2px 8px;border-radius:4px;margin-left:6px">ACIK</span>'
    durum_notu_html = f'<div style="font-size:.78rem;color:#dc3545;margin-top:2px">&#128226; {firm.get("durum_notu","")}</div>' if firm.get('durum_notu') else ''
    return f"""<!DOCTYPE html><html lang="tr"><head><meta charset="UTF-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Firma Paneli - EkspertizBul</title>{_base_style()}
    <style>
    .tabs{{display:flex;gap:6px;margin-bottom:16px;flex-wrap:wrap}}
    .tab{{background:#fff;border:2px solid #ddd;padding:8px 16px;border-radius:8px;cursor:pointer;font-size:.82rem;font-weight:600}}
    .tab.on{{border-color:#e53535;color:#e53535;background:#fff0f0}}
    .tab-content{{display:none}}.tab-content.on{{display:block}}
    </style></head><body>
    {_topbar("Firma Paneli", "/", "Ana Sayfa")}

    <!-- Bildirim Popup -->
    <div id="notifModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:1000;align-items:center;justify-content:center">
      <div style="background:#fff;border-radius:14px;width:92%;max-width:500px;max-height:80vh;overflow:auto;padding:20px;position:relative">
        <button onclick="document.getElementById('notifModal').style.display='none'" style="position:absolute;top:12px;right:14px;background:none;border:none;font-size:1.3rem;cursor:pointer">✕</button>
        <h3 style="margin-bottom:14px;color:#1a0000">&#128276; Bildirimler</h3>
        <div id="notifList"></div>
      </div>
    </div>

    <div class="wrap">
      <div class="card" style="display:flex;justify-content:space-between;align-items:center">
        <div>
          <div style="font-weight:800;font-size:1.05rem">{firm['unvan']} {durum_badge}</div>
          <div style="font-size:.82rem;color:#666">{firm['yetkili_ad']} - {firm['yetkili_gorev']}</div>
          {durum_notu_html}
        </div>
        <button class="btn" onclick="showNotifs()">&#128276; Bildirimler{notif_badge}</button>
      </div>

      <div class="tabs">
        <button class="tab on" onclick="showTab('randevular',this)">&#128197; Randevular</button>
        <button class="tab" onclick="showTab('paketler',this)">&#128176; Paketlerim</button>
        <button class="tab" onclick="showTab('profil',this)">&#9881; Profil</button>
      <a href="/firma/calisma-saatleri" class="tab">&#128336; Calisma Saatleri</a>
      <a href="/mesajlarim" class="tab">&#128172; Mesajlarim</a>
      </div>

      <!-- RANDEVULAR -->
      <div id="tab-randevular" class="tab-content on card">
        <h2>&#128197; Randevular</h2>
        <div style="overflow-x:auto">
        <table style="width:100%;border-collapse:collapse;font-size:.82rem">
          <thead><tr style="background:#f5f0f0">
            <th style="padding:8px;text-align:left">Müşteri</th>
            <th style="padding:8px;text-align:left">Tarih/Saat</th>
            <th style="padding:8px;text-align:left">Araç</th>
            <th style="padding:8px;text-align:left">Paket</th>
            <th style="padding:8px;text-align:left">Durum</th>
            <th style="padding:8px;text-align:left">İşlem</th>
          </tr></thead>
          <tbody id="randevu-tbody">{rows}</tbody>
        </table></div>
      </div>

      <!-- PAKETLER -->
      <div id="tab-paketler" class="tab-content card">
        <h2>&#128176; Paketlerim</h2>
        <table style="width:100%;border-collapse:collapse;font-size:.82rem;margin-bottom:16px">
          <thead><tr style="background:#f5f0f0">
            <th style="padding:8px;text-align:left">Paket</th>
            <th style="padding:8px;text-align:left">Fiyat</th>
            <th style="padding:8px;text-align:left">İçerik</th>
            <th style="padding:8px"></th>
          </tr></thead>
          <tbody id="paket-tbody">{pkg_rows or '<tr><td colspan="4" style="padding:12px;text-align:center;color:#aaa">Henüz paket yok</td></tr>'}</tbody>
        </table>
        <div style="background:#f5f0f0;padding:14px;border-radius:10px">
          <div style="font-weight:600;margin-bottom:10px">Yeni Paket Ekle</div>
          <div style="display:flex;gap:8px;flex-wrap:wrap">
            <input id="p-adi" placeholder="Paket adı" style="flex:1;min-width:120px;padding:8px;border:1px solid #ddd;border-radius:8px">
            <input id="p-fiyat" type="number" placeholder="Fiyat (TL)" style="width:120px;padding:8px;border:1px solid #ddd;border-radius:8px">
            <input id="p-icerik" placeholder="İçerik" style="flex:2;min-width:180px;padding:8px;border:1px solid #ddd;border-radius:8px">
            <button class="btn" onclick="paketEkle()">Ekle</button>
          </div>
        </div>
      </div>

      <!-- PROFIL -->
      <div id="tab-profil" class="tab-content card">
        <h2>⚙️ Firma Bilgileri</h2>
        <table style="font-size:.85rem;border-collapse:collapse">
          <tr><td style="padding:6px 12px 6px 0;font-weight:600;color:#888">Ünvan</td><td>{firm['unvan']}</td></tr>
          <tr><td style="padding:6px 12px 6px 0;font-weight:600;color:#888">Yetkili</td><td>{firm['yetkili_ad']} ({firm['yetkili_gorev']})</td></tr>
          <tr><td style="padding:6px 12px 6px 0;font-weight:600;color:#888">Adres</td><td>{firm['adres']}</td></tr>
          <tr><td style="padding:6px 12px 6px 0;font-weight:600;color:#888">Telefon</td><td>{firm['telefon']}</td></tr>
          <tr><td style="padding:6px 12px 6px 0;font-weight:600;color:#888">Email</td><td>{firm['email']}</td></tr>
        </table>
        <a href='/firma/profil' class='btn-outline' style='display:inline-block;margin-top:14px;font-size:.8rem'>&#9998; Profili Duzenle</a>
      </div>
    </div>

    <script>
    function showTab(t, el){{
      document.querySelectorAll('.tab-content').forEach(function(c){{c.classList.remove('on');}});
      document.querySelectorAll('.tab').forEach(function(b){{b.classList.remove('on');}});
      var tc = document.getElementById('tab-'+t);
      if(tc) tc.classList.add('on');
      if(el) el.classList.add('on');
    }}

    function updateApt(id, durum){{
      var fd=new FormData();
      fd.append('appointment_id',id);
      fd.append('durum',durum);
      fetch('/firma/randevu/guncelle',{{method:'POST',body:fd}})
        .then(function(r){{return r.json();}})
        .then(function(){{location.reload();}});
    }}

    function paketEkle(){{
      var adi=document.getElementById('p-adi').value;
      var fiyat=document.getElementById('p-fiyat').value;
      var icerik=document.getElementById('p-icerik').value;
      if(!adi||!fiyat){{alert('Paket adı ve fiyat zorunlu!');return;}}
      var fd=new FormData();
      fd.append('paket_adi',adi);
      fd.append('fiyat',fiyat);
      fd.append('icerik',icerik);
      fetch('/firma/paket/ekle',{{method:'POST',body:fd}})
        .then(function(r){{return r.json();}})
        .then(function(){{location.reload();}});
    }}

    function silPaket(id){{
      if(!confirm('Paketi silmek istediğinize emin misiniz?'))return;
      var fd=new FormData();fd.append('paket_id',id);
      fetch('/firma/paket/sil',{{method:'POST',body:fd}})
        .then(function(){{location.reload();}});
    }}

    function firmaIletisim(id){{
      fetch('/randevu/'+id+'/iletisim').then(r=>r.json()).then(d=>{{
        if(d.error){{alert(d.error);return;}}
        alert('Musteri: '+d.ad+' | Tel: '+d.telefon+' | Email: '+d.email);
      }});
    }}
    function firmaIptal(id){{
      if(!confirm('Randevuyu iptal etmek istediginize emin misiniz? Musteri bilgilendirilecek.'))return;
      var fd=new FormData();fd.append('appointment_id',id);
      fetch('/randevu/iptal',{{method:'POST',body:fd}})
        .then(r=>r.json())
        .then(d=>{{if(d.success)location.reload();else alert(d.error);}});
    }}
    function firmaSaatDegistir(id){{
      var tarih=prompt('Yeni tarih (YYYY-MM-DD):');
      if(!tarih)return;
      var saat=prompt('Yeni saat (HH:00):');
      if(!saat)return;
      var fd=new FormData();
      fd.append('appointment_id',id);
      fd.append('yeni_tarih',tarih);
      fd.append('yeni_saat',saat);
      fetch('/randevu/saat-guncelle',{{method:'POST',body:fd}}).then(r=>r.json()).then(d=>{{
        if(d.success)location.reload();else alert(d.error);
      }});
    }}
    function showNotifs(){{
      fetch('/firma/bildirimler')
        .then(function(r){{return r.json();}})
        .then(function(data){{
          var h='';
          if(data.items.length===0){{
            h='<p style="color:#aaa;text-align:center;padding:20px">Yeni bildirim yok</p>';
          }} else {{
            data.items.forEach(function(n){{
              h+='<div style="padding:10px;border-bottom:1px solid #f0f0f0">'+
                '<div style="font-size:.85rem">'+n.mesaj+'</div>'+
                '<div style="font-size:.75rem;color:#aaa">'+n.created_at+'</div></div>';
            }});
          }}
          document.getElementById('notifList').innerHTML=h;
          document.getElementById('notifModal').style.display='flex';
        }});
    }}

    // 30 saniyede bir bildirim kontrolu
    setInterval(function(){{
      fetch('/firma/bildirimler')
        .then(function(r){{return r.json();}})
        .then(function(data){{
          var dot=document.querySelector('.notif-dot');
          if(data.count>0&&!dot){{
            document.querySelector('[onclick="showNotifs()"]').innerHTML='&#128276; Bildirimler<span class="notif-dot">'+data.count+'</span>';
          }}
        }});
    }}, 30000);
    </script>
    </body></html>"""

@app.post("/scrape")
async def trigger_scrape():
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from run_scraper import run_all
    results = await run_all()
    return {"success": True, "firms": len(results)}


@app.get("/kullanici/profil", response_class=HTMLResponse)
def kullanici_profil(session: str = Cookie(default=None)):
    s = get_session(session)
    if not s or s["role"] != "user":
        return RedirectResponse("/giris", status_code=303)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id=%s", (s["user_id"],))
    user = cur.fetchone()
    cur.close(); conn.close()
    body = _base_style() + "<body>" + _topbar("Profilim", "/kullanici/panel", "Panelim")
    body += "<div class='wrap' style='max-width:500px'><div class='card'><h2>&#128100; Profil Bilgileri</h2>"
    body += "<div id='msg'></div>"
    body += "<div class='form-group'><label>Ad Soyad</label><input type='text' id='ad_soyad' value='" + (user["ad_soyad"] or "") + "'></div>"
    body += "<div class='form-group'><label>Email</label><input type='email' id='email' value='" + (user["email"] or "") + "'></div>"
    body += "<div class='form-group'><label>Telefon</label><input type='tel' id='telefon' value='" + (user["telefon"] or "") + "'></div>"
    body += "<div class='form-group'><label>Yeni Sifre (bos birakin degistirmek istemiyorsaniz)</label><input type='password' id='sifre' placeholder='Yeni sifre'></div>"
    body += "<button class='btn' style='width:100%' onclick='guncelle()'>Guncelle</button></div></div>"
    body += "<script>function guncelle(){var fd=new FormData();fd.append('ad_soyad',document.getElementById('ad_soyad').value);fd.append('email',document.getElementById('email').value);fd.append('telefon',document.getElementById('telefon').value);fd.append('sifre',document.getElementById('sifre').value);fetch('/kullanici/profil/guncelle',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{if(d.success){document.getElementById('msg').innerHTML='<div class=\"alert alert-success\">Bilgileriniz guncellendi!</div>';}else{document.getElementById('msg').innerHTML='<div class=\"alert alert-error\">'+d.error+'</div>';}});}</script>"
    body += "</body></html>"
    return HTMLResponse("<!DOCTYPE html><html lang='tr'><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Profilim</title>" + body)

@app.post("/kullanici/profil/guncelle")
async def kullanici_profil_guncelle(
    ad_soyad: str = Form(...),
    email: str = Form(...),
    telefon: str = Form(default=""),
    sifre: str = Form(default=""),
    session: str = Cookie(default=None)
):
    s = get_session(session)
    if not s or s["role"] != "user":
        return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    conn = get_conn()
    cur = conn.cursor()
    if sifre:
        cur.execute("UPDATE users SET ad_soyad=%s, email=%s, telefon=%s, sifre_hash=%s WHERE id=%s",
                    (ad_soyad, email, telefon, hash_password(sifre), s["user_id"]))
    else:
        cur.execute("UPDATE users SET ad_soyad=%s, email=%s, telefon=%s WHERE id=%s",
                    (ad_soyad, email, telefon, s["user_id"]))
    conn.commit()
    cur.close(); conn.close()
    return JSONResponse({"success": True})


@app.get("/firma/profil", response_class=HTMLResponse)
def firma_profil(session: str = Cookie(default=None)):
    s = get_session(session)
    if not s or s["role"] != "firma":
        return RedirectResponse("/giris", status_code=303)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM firm_accounts WHERE id=%s", (s["firm_id"],))
    firm = cur.fetchone()
    cur.close(); conn.close()
    iller = ["Adana","Adiyaman","Afyonkarahisar","Agri","Amasya","Ankara","Antalya","Artvin","Aydin","Balikesir","Bilecik","Bingol","Bitlis","Bolu","Burdur","Bursa","Canakkale","Cankiri","Corum","Denizli","Diyarbakir","Edirne","Elazig","Erzincan","Erzurum","Eskisehir","Gaziantep","Giresun","Gumushane","Hakkari","Hatay","Isparta","Mersin","Istanbul","Izmir","Kars","Kastamonu","Kayseri","Kirklareli","Kirsehir","Kocaeli","Konya","Kutahya","Malatya","Manisa","Kahramanmaras","Mardin","Mugla","Mus","Nevsehir","Nigde","Ordu","Rize","Sakarya","Samsun","Siirt","Sinop","Sivas","Tekirdag","Tokat","Trabzon","Tunceli","Sanliurfa","Usak","Van","Yozgat","Zonguldak","Aksaray","Bayburt","Karaman","Kirikkale","Batman","Sirnak","Bartin","Ardahan","Igdir","Yalova","Karabuk","Kilis","Osmaniye","Duzce"]
    il_opts = "".join([f"<option value='{il}'" + (" selected" if firm.get('il')==il else "") + f">{il}</option>" for il in sorted(iller)])
    gorevler = ["Is Yeri Sahibi","Mudur","Yetkili Personel","Sube Muduru","Diger"]
    gorev_opts = "".join([f"<option value='{g}'" + (" selected" if firm.get('yetkili_gorev')==g else "") + f">{g}</option>" for g in gorevler])
    body = _base_style() + "<body>" + _topbar("Firma Profili", "/firma/panel", "Panelim")
    body += "<div class='wrap' style='max-width:560px'><div class='card'><h2>&#127970; Firma Bilgileri</h2>"
    body += "<div id='msg'></div>"
    body += "<div class='form-group'><label>Firma Unvani</label><input type='text' id='unvan' value='" + (firm["unvan"] or "") + "'></div>"
    body += "<div class='form-group'><label>Yetkili Ad Soyad</label><input type='text' id='yetkili_ad' value='" + (firm["yetkili_ad"] or "") + "'></div>"
    body += "<div class='form-group'><label>Gorevi</label><select id='yetkili_gorev'>" + gorev_opts + "</select></div>"
    body += "<div class='form-group'><label>Il</label><select id='il'><option value=''>Secin</option>" + il_opts + "</select></div>"
    body += "<div class='form-group'><label>Ilce</label><input type='text' id='ilce' value='" + (firm.get("ilce") or "") + "'></div>"
    body += "<div class='form-group'><label>Acik Adres</label><textarea id='adres' rows='2'>" + (firm["adres"] or "") + "</textarea></div>"
    body += "<div class='form-group'><label>Telefon</label><input type='tel' id='telefon' value='" + (firm["telefon"] or "") + "'></div>"
    body += "<div class='form-group'><label>Email</label><input type='email' id='email' value='" + (firm["email"] or "") + "'></div>"
    body += "<div class='form-group'><label>Yeni Sifre (bos birakin degistirmek istemiyorsaniz)</label><input type='password' id='sifre' placeholder='Yeni sifre'></div>"
    body += "<button class='btn' style='width:100%' onclick='guncelle()'>Guncelle</button></div></div>"
    body += "<script>function guncelle(){var fd=new FormData();['unvan','yetkili_ad','yetkili_gorev','il','ilce','adres','telefon','email','sifre'].forEach(function(k){fd.append(k,document.getElementById(k).value);});fetch('/firma/profil/guncelle',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{if(d.success){document.getElementById('msg').innerHTML='<div class=\"alert alert-success\">Bilgileriniz guncellendi!</div>';}else{document.getElementById('msg').innerHTML='<div class=\"alert alert-error\">'+d.error+'</div>';}});}</script>"
    body += "</body></html>"
    return HTMLResponse("<!DOCTYPE html><html lang='tr'><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Firma Profili</title>" + body)

@app.post("/firma/profil/guncelle")
async def firma_profil_guncelle(
    unvan: str = Form(...),
    yetkili_ad: str = Form(...),
    yetkili_gorev: str = Form(default=""),
    il: str = Form(default=""),
    ilce: str = Form(default=""),
    adres: str = Form(default=""),
    telefon: str = Form(...),
    email: str = Form(...),
    sifre: str = Form(default=""),
    session: str = Cookie(default=None)
):
    s = get_session(session)
    if not s or s["role"] != "firma":
        return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    conn = get_conn()
    cur = conn.cursor()
    if sifre:
        cur.execute(
            "UPDATE firm_accounts SET unvan=%s, yetkili_ad=%s, yetkili_gorev=%s, il=%s, ilce=%s, adres=%s, telefon=%s, email=%s, sifre_hash=%s WHERE id=%s",
            (unvan, yetkili_ad, yetkili_gorev, il, ilce, adres, telefon, email, hash_password(sifre), s["firm_id"])
        )
    else:
        cur.execute(
            "UPDATE firm_accounts SET unvan=%s, yetkili_ad=%s, yetkili_gorev=%s, il=%s, ilce=%s, adres=%s, telefon=%s, email=%s WHERE id=%s",
            (unvan, yetkili_ad, yetkili_gorev, il, ilce, adres, telefon, email, s["firm_id"])
        )
    conn.commit()
    cur.close(); conn.close()
    return JSONResponse({"success": True})


@app.get("/randevu/{firm_id}", response_class=HTMLResponse)
def randevu_page(firm_id: str, session: str = Cookie(default=None)):
    import datetime
    s = get_session(session)
    if not s or s["role"] != "user":
        return RedirectResponse("/giris", status_code=303)
    firm_db_id = None
    firm_name = "Firma"
    if firm_id.startswith("db_"):
        try:
            fid = int(firm_id.replace("db_", ""))
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT * FROM firm_accounts WHERE id=%s", (fid,))
            firm = cur.fetchone()
            cur.close(); conn.close()
            if firm:
                firm_name = firm["unvan"]
                firm_db_id = fid
        except Exception as e:
            print(f"randevu_page: {e}")
    if not firm_db_id:
        return HTMLResponse("<p>Firma bulunamadi. <a href='/'>Ana Sayfa</a></p>", status_code=404)
    # Firma durumu kontrol
    conn2 = get_conn()
    cur2 = conn2.cursor()
    cur2.execute("SELECT durum, durum_notu FROM firm_accounts WHERE id=%s", (firm_db_id,))
    firm_status = cur2.fetchone()
    cur2.close(); conn2.close()
    if firm_status and firm_status["durum"] == "pasif":
        notu = firm_status["durum_notu"] or "Firma su an randevu almiyor."
        return HTMLResponse(f"<!DOCTYPE html><html lang='tr'><head><meta charset='UTF-8'><title>Firma Kapali</title>{_base_style()}</head><body>{_topbar('', '/', 'Ana Sayfa')}<div class='wrap' style='max-width:500px'><div class='card' style='text-align:center'><div style='font-size:3rem'>&#128308;</div><h2 style='margin:16px 0'>Firma Su An Kapali</h2><p style='color:#666'>{notu}</p><a href='/' class='btn' style='display:inline-block;margin-top:16px'>Ana Sayfaya Don</a></div></div></body></html>")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM firm_packages WHERE firm_id=%s AND aktif=1", (firm_db_id,))
    paketler = cur.fetchall()
    cur.close(); conn.close()
    today = datetime.date.today().isoformat()
    markalar = ["","Audi","BMW","Citroen","Dacia","Fiat","Ford","Honda","Hyundai","Kia","Mazda","Mercedes-Benz","Nissan","Opel","Peugeot","Renault","Skoda","Toyota","Volkswagen","Diger"]
    marka_opts = "".join(["<option value='"+m+"'>"+m+"</option>" for m in markalar])
    yil_opts = "".join(["<option value='"+str(y)+"'>"+str(y)+"</option>" for y in range(2025,1989,-1)])
    saat_opts = "".join(["<option value='"+str(h).zfill(2)+":00'>"+str(h).zfill(2)+":00</option>" for h in range(8,19)])
    pkg_opts = "<option value=''>-- Paket secin (zorunlu) --</option>"
    for p in paketler:
        pkg_opts += "<option value='"+str(p["paket_adi"])+"'>"+str(p["paket_adi"])+" - "+str(p["fiyat"])+" TL</option>"
    fid_str = str(firm_db_id)
    body = _base_style()
    body += "<body>" + _topbar("Randevu Al", "/", "Ana Sayfa")
    body += "<div class='wrap' style='max-width:500px'><div class='card'>"
    body += "<h2>&#128197; " + firm_name + " - Randevu Al</h2><div id='msg'></div>"
    body += "<div class='form-group'><label>Tarih</label><input type='date' id='tarih' min='" + today + "'></div>"
    body += "<div class='form-group'><label>Saat</label><select id='saat'>" + saat_opts + "</select></div>"
    body += "<div class='form-group'><label>Arac Markasi</label><select id='marka'>" + marka_opts + "</select></div>"
    body += "<div class='form-group'><label>Model</label><input type='text' id='model' placeholder='Ornek: Clio, Focus'></div>"
    body += "<div class='form-group'><label>Yil</label><select id='yil'>" + yil_opts + "</select></div>"
    body += "<div class='form-group'><label>Paket</label><select id='paket'>" + pkg_opts + "</select></div>"
    body += "<div class='form-group'><label>Notlar</label><textarea id='notlar' rows='2'></textarea></div>"
    body += "<button class='btn' style='width:100%' onclick='submitR()'>Randevu Gonder</button>"
    body += "</div></div>"
    body += "<script>function submitR(){var fd=new FormData();fd.append('firm_id','" + fid_str + "');fd.append('tarih',document.getElementById('tarih').value);fd.append('saat',document.getElementById('saat').value);fd.append('arac_marka',document.getElementById('marka').value);fd.append('arac_model',document.getElementById('model').value);fd.append('arac_yil',document.getElementById('yil').value);fd.append('paket',document.getElementById('paket').value);fd.append('notlar',document.getElementById('notlar').value);if(!fd.get('tarih')){alert('Lutfen tarih secin!');return;}if(!fd.get('paket')){alert('Lutfen bir paket secin!');return;}fetch('/randevu/olustur',{method:'POST',body:fd}).then(r=>r.json()).then(d=>{if(d.success){document.getElementById('msg').innerHTML='<div class=\"alert alert-success\">Randevunuz gonderildi!</div>';setTimeout(()=>window.location='/kullanici/panel',2000);}else{document.getElementById('msg').innerHTML='<div class=\"alert alert-error\">'+d.error+'</div>';}});}</script>"
    body += "</body></html>"
    return HTMLResponse("<!DOCTYPE html><html lang='tr'><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Randevu Al</title>" + body)


# ============================================================
# RANDEVU IPTAL / SAAT DEGISIKLIK / ILETISIM
# ============================================================

@app.post("/randevu/iptal")
async def randevu_iptal(
    appointment_id: int = Form(...),
    session: str = Cookie(default=None)
):
    import datetime
    s = get_session(session)
    if not s:
        return JSONResponse({"error": "Giris gerekli"}, status_code=401)
    conn = get_conn()
    cur = conn.cursor()
    if s["role"] == "user":
        cur.execute("SELECT * FROM appointments WHERE id=%s AND user_id=%s", (appointment_id, s["user_id"]))
    else:
        cur.execute("SELECT * FROM appointments WHERE id=%s AND firm_id=%s", (appointment_id, s["firm_id"]))
    apt = cur.fetchone()
    if not apt:
        cur.close(); conn.close()
        return JSONResponse({"error": "Randevu bulunamadi"}, status_code=404)
    if apt["durum"] in ["tamamlandi", "iptal"]:
        cur.close(); conn.close()
        return JSONResponse({"error": "Bu randevu iptal edilemez"})
    # 24 saat kontrolu
    try:
        apt_dt = datetime.datetime.strptime(f"{apt['tarih']} {apt['saat']}", "%Y-%m-%d %H:%M")
        kalan = apt_dt - datetime.datetime.now()
        if kalan.total_seconds() < 86400:  # 24 saat = 86400 saniye
            cur.close(); conn.close()
            return JSONResponse({"error": f"Randevuya 24 saatten az kaldi. Iptal icin en gec {(apt_dt - datetime.timedelta(hours=24)).strftime('%d.%m.%Y %H:%M')} olmasi gerekiyor."})
    except Exception as e:
        print(f"24h check error: {e}")
    cur.execute("UPDATE appointments SET durum='iptal' WHERE id=%s", (appointment_id,))
    # Karsi tarafa bildirim ve email
    if s["role"] == "user":
        cur.execute("SELECT * FROM firm_accounts WHERE id=%s", (apt["firm_id"],))
        firm = cur.fetchone()
        cur.execute("SELECT * FROM users WHERE id=%s", (s["user_id"],))
        user = cur.fetchone()
        add_notification(firm_id=apt["firm_id"], tip="iptal",
                        mesaj=f"Randevu iptal edildi: {user['ad_soyad']} - {apt['tarih']} {apt['saat']}",
                        appointment_id=appointment_id)
        if firm:
            from notifications import send_email
            send_email(firm["email"], f"Randevu Iptal - {user['ad_soyad']}",
                f"""<div style='font-family:Arial;max-width:500px;margin:0 auto'>
                <div style='background:#1a0000;color:#fff;padding:20px;text-align:center;border-radius:10px 10px 0 0'>
                <h2>EkspertizBul - Randevu Iptal</h2></div>
                <div style='padding:20px;background:#fff;border:1px solid #eee'>
                <p>Merhaba <b>{firm['unvan']}</b>,</p>
                <p><b>{user['ad_soyad']}</b> adli musteri randevusunu iptal etti.</p>
                <p>Tarih: <b>{apt['tarih']} - {apt['saat']}</b></p>
                <p>Arac: {apt.get('arac_marka','')} {apt.get('arac_model','')} {apt.get('arac_yil','')}</p>
                </div></div>""")
    else:
        cur.execute("SELECT * FROM users WHERE id=%s", (apt["user_id"],))
        user = cur.fetchone()
        cur.execute("SELECT * FROM firm_accounts WHERE id=%s", (s["firm_id"],))
        firm = cur.fetchone()
        add_notification(user_id=apt["user_id"], tip="iptal",
                        mesaj=f"Randevunuz iptal edildi: {firm['unvan'] if firm else ''} - {apt['tarih']} {apt['saat']}",
                        appointment_id=appointment_id)
        if user and user.get("email"):
            from notifications import send_email
            firma_adi = firm["unvan"] if firm else "Firma"
            send_email(user["email"], f"Randevunuz Iptal Edildi - {firma_adi}",
                f"""<div style='font-family:Arial;max-width:500px;margin:0 auto'>
                <div style='background:#1a0000;color:#fff;padding:20px;text-align:center;border-radius:10px 10px 0 0'>
                <h2>EkspertizBul - Randevu Iptal</h2></div>
                <div style='padding:20px;background:#fff;border:1px solid #eee'>
                <p>Merhaba <b>{user['ad_soyad']}</b>,</p>
                <p><b>{firma_adi}</b> randevunuzu iptal etti.</p>
                <p>Tarih: <b>{apt['tarih']} - {apt['saat']}</b></p>
                <p>Yeni randevu almak icin <a href='https://ekspertiz-bul.onrender.com'>sitemizi ziyaret edin</a>.</p>
                </div></div>""")
    conn.commit()
    cur.close(); conn.close()
    return JSONResponse({"success": True})

@app.post("/randevu/saat-guncelle")
async def randevu_saat_guncelle(
    appointment_id: int = Form(...),
    yeni_tarih: str = Form(...),
    yeni_saat: str = Form(...),
    session: str = Cookie(default=None)
):
    s = get_session(session)
    if not s:
        return JSONResponse({"error": "Giris gerekli"}, status_code=401)
    conn = get_conn()
    cur = conn.cursor()
    if s["role"] == "user":
        cur.execute("SELECT * FROM appointments WHERE id=%s AND user_id=%s", (appointment_id, s["user_id"]))
    else:
        cur.execute("SELECT * FROM appointments WHERE id=%s AND firm_id=%s", (appointment_id, s["firm_id"]))
    apt = cur.fetchone()
    if not apt or apt["durum"] in ["tamamlandi", "iptal"]:
        cur.close(); conn.close()
        return JSONResponse({"error": "Guncelleme yapilamaz"})
    cur.execute("UPDATE appointments SET tarih=%s, saat=%s, durum='beklemede' WHERE id=%s", (yeni_tarih, yeni_saat, appointment_id))
    if s["role"] == "user":
        add_notification(firm_id=apt["firm_id"], tip="saat_degisiklik", mesaj=f"Randevu saati degistirildi: {yeni_tarih} {yeni_saat}", appointment_id=appointment_id)
    else:
        add_notification(user_id=apt["user_id"], tip="saat_degisiklik", mesaj=f"Randevu saatiniz degistirildi: {yeni_tarih} {yeni_saat}", appointment_id=appointment_id)
    conn.commit()
    cur.close(); conn.close()
    return JSONResponse({"success": True})

@app.get("/randevu/{appointment_id}/iletisim", response_class=JSONResponse)
def randevu_iletisim(appointment_id: int, session: str = Cookie(default=None)):
    s = get_session(session)
    if not s:
        return JSONResponse({"error": "Giris gerekli"}, status_code=401)
    conn = get_conn()
    cur = conn.cursor()
    if s["role"] == "user":
        cur.execute("""
            SELECT f.telefon, f.email, f.unvan as ad
            FROM appointments a JOIN firm_accounts f ON f.id=a.firm_id
            WHERE a.id=%s AND a.user_id=%s
        """, (appointment_id, s["user_id"]))
    else:
        cur.execute("""
            SELECT u.telefon, u.email, u.ad_soyad as ad
            FROM appointments a JOIN users u ON u.id=a.user_id
            WHERE a.id=%s AND a.firm_id=%s
        """, (appointment_id, s["firm_id"]))
    row = cur.fetchone()
    cur.close(); conn.close()
    if not row:
        return JSONResponse({"error": "Bulunamadi"}, status_code=404)
    return JSONResponse(dict(row))

# ============================================================
# PUANLAMA SISTEMI
# ============================================================

@app.get("/randevu/{appointment_id}/puan", response_class=HTMLResponse)
def puan_sayfasi(appointment_id: int, session: str = Cookie(default=None)):
    s = get_session(session)
    if not s or s["role"] != "user":
        return RedirectResponse("/giris", status_code=303)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT a.*, f.unvan, f.telefon as firma_tel
        FROM appointments a JOIN firm_accounts f ON f.id=a.firm_id
        WHERE a.id=%s AND a.user_id=%s
    """, (appointment_id, s["user_id"]))
    apt = cur.fetchone()
    if not apt or apt["durum"] != "tamamlandi":
        cur.close(); conn.close()
        return HTMLResponse("<p>Puan verilemez. <a href='/kullanici/panel'>Geri Don</a></p>")
    # 30 gun kontrolu
    import datetime
    completed = apt["created_at"]
    if isinstance(completed, str):
        completed = datetime.datetime.fromisoformat(completed)
    if (datetime.datetime.now() - completed).days > 30:
        cur.close(); conn.close()
        return HTMLResponse("<p>Puanlama suresi doldu (30 gun). <a href='/kullanici/panel'>Geri Don</a></p>")
    # Mevcut puan var mi
    cur.execute("SELECT * FROM reviews WHERE appointment_id=%s", (appointment_id,))
    existing_review = cur.fetchone()
    existing_criteria = {}
    if existing_review:
        cur.execute("SELECT * FROM review_criteria WHERE review_id=%s", (existing_review["id"],))
        for c in cur.fetchall():
            existing_criteria[c["kriter_adi"]] = dict(c)
    # Kriter listesi
    cur.execute("SELECT * FROM review_criteria_config WHERE aktif=TRUE ORDER BY sira")
    kriterler = cur.fetchall()
    cur.close(); conn.close()

    kriter_html = ""
    for k in kriterler:
        mevcut = existing_criteria.get(k["kriter_adi"], {})
        mevcut_puan = mevcut.get("puan", 0)
        degistirilebilir = k["degistirilebilir"]
        degistirildi = mevcut.get("degistirildi", False)
        disabled = ""
        info = ""
        if existing_review:
            if not degistirilebilir:
                disabled = "disabled"
                info = "<span style='color:#888;font-size:.75rem'>Degistirilemez</span>"
            elif degistirildi:
                disabled = "disabled"
                info = "<span style='color:#888;font-size:.75rem'>Zaten degistirildi</span>"
            else:
                info = "<span style='color:#00a875;font-size:.75rem'>Degistirilebilir (1 kez, 30 gun icinde)</span>"
        stars = ""
        for i in range(1, 6):
            checked = "checked" if mevcut_puan == i else ""
            stars += f"<input type='radio' name='kriter_{k['id']}' value='{i}' {checked} {disabled} style='margin:0 3px'> {i}⭐ "
        kriter_html += f"<div style='margin-bottom:14px;padding:12px;background:#f5f0f0;border-radius:8px'><div style='font-weight:600;margin-bottom:6px'>{k['kriter_adi']} {info}</div><div>{stars}</div></div>"

    btn_label = "Puani Guncelle" if existing_review else "Puan Ver"
    review_id = existing_review["id"] if existing_review else ""

    body = _base_style() + "<body>" + _topbar("Puan Ver", "/kullanici/panel", "Panelim")
    body += f"<div class='wrap' style='max-width:500px'><div class='card'>"
    body += f"<h2>&#11088; {apt['unvan']} - Degerlendirme</h2>"
    body += f"<p style='font-size:.82rem;color:#888;margin-bottom:16px'>{apt['tarih']} {apt['saat']} randevusu</p>"
    body += "<div id='msg'></div>"
    body += kriter_html
    body += f"<button class='btn' style='width:100%' onclick='submitPuan()'>{btn_label}</button>"
    body += "</div></div>"

    kriterler_js = "[" + ",".join([f"{{id:{k['id']},adi:'{k['kriter_adi']}',degistirilebilir:{str(k['degistirilebilir']).lower()}}}" for k in kriterler]) + "]"

    body += f"""<script>
var KRITERLER={kriterler_js};
var REVIEW_ID="{review_id}";
var APT_ID={appointment_id};
function submitPuan(){{
  var fd=new FormData();
  fd.append('appointment_id',APT_ID);
  fd.append('review_id',REVIEW_ID);
  fd.append('yorum','');
  var ok=true;
  KRITERLER.forEach(function(k){{
    var radios=document.querySelectorAll('input[name="kriter_'+k.id+'"]');
    var val=0;
    radios.forEach(function(r){{if(r.checked)val=r.value;}});
    if(!val&&!radios[0].disabled){{ok=false;}}
    fd.append('kriter_'+k.id,val);
  }});
  if(!ok){{alert('Lutfen tum kriterleri puanlayin!');return;}}
  fetch('/randevu/puan/kaydet',{{method:'POST',body:fd}})
    .then(r=>r.json())
    .then(d=>{{
      if(d.success){{
        document.getElementById('msg').innerHTML='<div class="alert alert-success">Degerlendirmeniz kaydedildi!</div>';
        setTimeout(function(){{window.location.href='/kullanici/panel';}},2000);
      }}else{{
        document.getElementById('msg').innerHTML='<div class="alert alert-error">'+d.error+'</div>';
      }}
    }});
}}
</script></body></html>"""
    return HTMLResponse("<!DOCTYPE html><html lang='tr'><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Puan Ver</title>" + body)

@app.post("/randevu/puan/kaydet")
async def puan_kaydet(request: Request, session: str = Cookie(default=None)):
    s = get_session(session)
    if not s or s["role"] != "user":
        return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    form = await request.form()
    appointment_id = int(form.get("appointment_id"))
    review_id = form.get("review_id", "")
    yorum = form.get("yorum", "")
    import datetime
    conn = get_conn()
    cur = conn.cursor()
    # Randevu kontrolu
    cur.execute("SELECT * FROM appointments WHERE id=%s AND user_id=%s AND durum='tamamlandi'", (appointment_id, s["user_id"]))
    apt = cur.fetchone()
    if not apt:
        cur.close(); conn.close()
        return JSONResponse({"error": "Randevu bulunamadi veya tamamlanmamis"})
    # 30 gun kontrolu
    completed = apt["created_at"]
    if isinstance(completed, str):
        completed = datetime.datetime.fromisoformat(completed)
    if (datetime.datetime.now() - completed).days > 30:
        cur.close(); conn.close()
        return JSONResponse({"error": "Puanlama suresi doldu"})
    # Kriter listesi
    cur.execute("SELECT * FROM review_criteria_config WHERE aktif=TRUE")
    kriterler = cur.fetchall()
    if review_id:
        # Guncelleme
        rid = int(review_id)
        cur.execute("UPDATE reviews SET yorum=%s WHERE id=%s AND user_id=%s", (yorum, rid, s["user_id"]))
        for k in kriterler:
            puan_val = form.get(f"kriter_{k['id']}", "0")
            if puan_val and int(puan_val) > 0:
                cur.execute("SELECT * FROM review_criteria WHERE review_id=%s AND kriter_adi=%s", (rid, k["kriter_adi"]))
                existing = cur.fetchone()
                if existing:
                    if k["degistirilebilir"] and not existing["degistirildi"]:
                        cur.execute("UPDATE review_criteria SET puan=%s, degistirildi=TRUE, updated_at=NOW() WHERE id=%s",
                                   (int(puan_val), existing["id"]))
    else:
        # Yeni puan
        cur.execute("INSERT INTO reviews (user_id, firm_id, appointment_id, yorum) VALUES (%s,%s,%s,%s) RETURNING id",
                   (s["user_id"], apt["firm_id"], appointment_id, yorum))
        rid = cur.fetchone()["id"]
        for k in kriterler:
            puan_val = form.get(f"kriter_{k['id']}", "0")
            if puan_val and int(puan_val) > 0:
                cur.execute("INSERT INTO review_criteria (review_id, kriter_adi, puan, degistirilebilir) VALUES (%s,%s,%s,%s)",
                           (rid, k["kriter_adi"], int(puan_val), k["degistirilebilir"]))
        # Firmaya bildirim
        add_notification(firm_id=apt["firm_id"], tip="yeni_puan", mesaj=f"Yeni degerlendirme aldiniz!", appointment_id=appointment_id)
    conn.commit()
    cur.close(); conn.close()
    return JSONResponse({"success": True})


# ============================================================
# CALISMA SAATLERI VE FIRMA DURUMU
# ============================================================

GUNLER = ['pazartesi','sali','carsamba','persembe','cuma','cumartesi','pazar']
GUN_LABELS = ['Pazartesi','Sali','Carsamba','Persembe','Cuma','Cumartesi','Pazar']

@app.get("/firma/calisma-saatleri", response_class=HTMLResponse)
def calisma_saatleri_page(session: str = Cookie(default=None)):
    s = get_session(session)
    if not s or s["role"] != "firma":
        return RedirectResponse("/giris", status_code=303)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM firm_working_hours WHERE firm_id=%s", (s["firm_id"],))
    wh = cur.fetchone()
    cur.execute("SELECT durum, durum_notu FROM firm_accounts WHERE id=%s", (s["firm_id"],))
    firm = cur.fetchone()
    cur.close(); conn.close()

    durum = firm["durum"] if firm else "aktif"
    durum_notu = firm["durum_notu"] if firm else ""

    saat_opts = "".join([f"<option value='{h:02d}:00'>{h:02d}:00</option>" for h in range(6, 23)])

    gun_rows = ""
    for i, gun in enumerate(GUNLER):
        if wh:
            acilis = wh[f"{gun}_acilis"] or "09:00"
            kapanis = wh[f"{gun}_kapanis"] or "18:00"
            kapali = wh[f"{gun}_kapali"]
        else:
            acilis = "09:00"
            kapanis = "18:00"
            kapali = gun in ["cumartesi", "pazar"]

        acilis_opts = saat_opts.replace(f"value='{acilis}'", f"value='{acilis}' selected")
        kapanis_opts = saat_opts.replace(f"value='{kapanis}'", f"value='{kapanis}' selected")
        kapali_checked = "checked" if kapali else ""

        gun_rows += f"""
        <tr id="row_{gun}" style="{'opacity:.4' if kapali else ''}">
          <td style="padding:8px;font-weight:600;width:110px">{GUN_LABELS[i]}</td>
          <td style="padding:8px"><select name="{gun}_acilis" {'disabled' if kapali else ''}>{acilis_opts}</select></td>
          <td style="padding:8px">-</td>
          <td style="padding:8px"><select name="{gun}_kapanis" {'disabled' if kapali else ''}>{kapanis_opts}</select></td>
          <td style="padding:8px"><label><input type="checkbox" name="{gun}_kapali" value="1" {kapali_checked} onchange="toggleGun('{gun}',this.checked)"> Kapali</label></td>
        </tr>"""

    durum_aktif = "selected" if durum == "aktif" else ""
    durum_pasif = "selected" if durum == "pasif" else ""

    body = _base_style() + "<body>" + _topbar("Calisma Saatleri", "/firma/panel", "Panelim")
    body += "<div class='wrap' style='max-width:600px'>"
    body += "<div class='card'><h2>&#128308; Firma Durumu</h2>"
    body += "<div id='msg'></div>"
    body += f"<div class='form-group'><label>Durum</label><select id='durum'><option value='aktif' {durum_aktif}>&#9989; Aktif - Randevu Aliniyor</option><option value='pasif' {durum_pasif}>🔴 Pasif - Randevu Kapali</option></select></div>"
    body += f"<div class='form-group'><label>Durum Notu (musterilere gorulecek)</label><input type='text' id='durum_notu' value='{durum_notu}' placeholder='Ornek: Izin nedeniyle 3 gun kapali'></div>"
    body += "<button class='btn' onclick='durumGuncelle()'>Durumu Guncelle</button>"
    body += "</div>"
    body += "<div class='card'><h2>&#128336; Calisma Saatleri</h2>"
    body += "<form method='post' action='/firma/calisma-saatleri'>"
    body += "<table style='width:100%;border-collapse:collapse;font-size:.85rem'>"
    body += "<thead><tr style='background:#f5f0f0'><th style='padding:8px;text-align:left'>Gun</th><th style='padding:8px'>Acilis</th><th></th><th style='padding:8px'>Kapanis</th><th style='padding:8px'>Durum</th></tr></thead>"
    body += f"<tbody>{gun_rows}</tbody></table>"
    body += "<button type='submit' class='btn' style='width:100%;margin-top:16px'>Saatleri Kaydet</button>"
    body += "</form></div></div>"
    body += """<script>
function toggleGun(gun, kapali){
  var row=document.getElementById('row_'+gun);
  row.style.opacity=kapali?'0.4':'1';
  row.querySelectorAll('select').forEach(function(s){s.disabled=kapali;});
}
function durumGuncelle(){
  var fd=new FormData();
  fd.append('durum',document.getElementById('durum').value);
  fd.append('durum_notu',document.getElementById('durum_notu').value);
  fetch('/firma/durum-guncelle',{method:'POST',body:fd})
    .then(r=>r.json())
    .then(d=>{
      if(d.success){document.getElementById('msg').innerHTML='<div class="alert alert-success">Durum guncellendi!</div>';}
      else{document.getElementById('msg').innerHTML='<div class="alert alert-error">'+d.error+'</div>';}
    });
}
</script></body></html>"""
    return HTMLResponse("<!DOCTYPE html><html lang='tr'><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Calisma Saatleri</title>" + body)

@app.post("/firma/calisma-saatleri")
async def calisma_saatleri_kaydet(request: Request, session: str = Cookie(default=None)):
    s = get_session(session)
    if not s or s["role"] != "firma":
        return RedirectResponse("/giris", status_code=303)
    form = await request.form()
    conn = get_conn()
    cur = conn.cursor()
    vals = {"firm_id": s["firm_id"]}
    for gun in GUNLER:
        vals[f"{gun}_acilis"] = form.get(f"{gun}_acilis", "09:00")
        vals[f"{gun}_kapanis"] = form.get(f"{gun}_kapanis", "18:00")
        vals[f"{gun}_kapali"] = form.get(f"{gun}_kapali") == "1"
    cur.execute("SELECT id FROM firm_working_hours WHERE firm_id=%s", (s["firm_id"],))
    existing = cur.fetchone()
    if existing:
        set_clause = ", ".join([f"{k}=%s" for k in vals if k != "firm_id"])
        vals_list = [vals[k] for k in vals if k != "firm_id"] + [s["firm_id"]]
        cur.execute(f"UPDATE firm_working_hours SET {set_clause} WHERE firm_id=%s", vals_list)
    else:
        cols = ", ".join(vals.keys())
        placeholders = ", ".join(["%s"] * len(vals))
        cur.execute(f"INSERT INTO firm_working_hours ({cols}) VALUES ({placeholders})", list(vals.values()))
    conn.commit()
    cur.close(); conn.close()
    return RedirectResponse("/firma/panel?msg=calisma_saatleri_kaydedildi", status_code=303)

@app.post("/firma/durum-guncelle")
async def firma_durum_guncelle(
    durum: str = Form(...),
    durum_notu: str = Form(default=""),
    session: str = Cookie(default=None)
):
    s = get_session(session)
    if not s or s["role"] != "firma":
        return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE firm_accounts SET durum=%s, durum_notu=%s WHERE id=%s",
                (durum, durum_notu, s["firm_id"]))
    conn.commit()
    cur.close(); conn.close()
    return JSONResponse({"success": True})

@app.post("/randevu/kullanici-tamamla")
async def kullanici_tamamla(
    appointment_id: int = Form(...),
    durum: str = Form(...),
    session: str = Cookie(default=None)
):
    s = get_session(session)
    if not s or s["role"] != "user":
        return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    if durum != "tamamlandi":
        return JSONResponse({"error": "Gecersiz durum"})
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM appointments WHERE id=%s AND user_id=%s AND durum='onaylandi'",
                (appointment_id, s["user_id"]))
    apt = cur.fetchone()
    if not apt:
        cur.close(); conn.close()
        return JSONResponse({"error": "Randevu bulunamadi veya onaylanmamis"})
    cur.execute("UPDATE appointments SET durum='tamamlandi' WHERE id=%s", (appointment_id,))
    add_notification(
        firm_id=apt["firm_id"],
        tip="tamamlandi",
        mesaj=f"Musteri hizmeti tamamlandi olarak isaretledi. Randevu: {apt['tarih']} {apt['saat']}",
        appointment_id=appointment_id
    )
    conn.commit()
    cur.close(); conn.close()
    return JSONResponse({"success": True})



# ============================================================
# ADMIN SISTEMI
# ============================================================

ADMIN_EMAIL = "mcolakai@gmail.com"
ADMIN_SIFRE = "ekspertiz2024admin"  # Ilk giris sonrasi degistirin

def ensure_admin():
    """Admin yoksa olustur"""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id FROM admins WHERE email=%s", (ADMIN_EMAIL,))
        if not cur.fetchone():
            cur.execute("INSERT INTO admins (email, sifre_hash, ad) VALUES (%s,%s,%s)",
                       (ADMIN_EMAIL, hash_password(ADMIN_SIFRE), "Admin"))
            conn.commit()
            print("Admin olusturuldu:", ADMIN_EMAIL)
        cur.close(); conn.close()
    except Exception as e:
        print(f"ensure_admin error: {e}")

ensure_admin()

@app.get("/admin/giris", response_class=HTMLResponse)
def admin_giris_page():
    body = _base_style() + "<body>" + _topbar("Admin", "/", "Ana Sayfa")
    body += """<div class='wrap' style='max-width:400px'>
    <div class='card'><h2>&#128272; Admin Girisi</h2>
    <div id='msg'></div>
    <div class='form-group'><label>Email</label><input type='email' id='email'></div>
    <div class='form-group'><label>Sifre</label><input type='password' id='sifre'></div>
    <button class='btn' style='width:100%' onclick='giris()'>Giris Yap</button>
    </div></div>
    <script>
    function giris(){
      var fd=new FormData();
      fd.append('email',document.getElementById('email').value);
      fd.append('sifre',document.getElementById('sifre').value);
      fetch('/admin/giris',{method:'POST',body:fd})
        .then(r=>r.json())
        .then(d=>{
          if(d.success)window.location.href='/admin/panel';
          else document.getElementById('msg').innerHTML='<div class="alert alert-error">'+d.error+'</div>';
        });
    }
    </script></body></html>"""
    return HTMLResponse("<!DOCTYPE html><html lang='tr'><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Admin</title>" + body)

@app.post("/admin/giris")
async def admin_giris_post(email: str = Form(...), sifre: str = Form(...)):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM admins WHERE email=%s", (email,))
    admin = cur.fetchone()
    cur.close(); conn.close()
    if not admin or not check_password(sifre, admin["sifre_hash"]):
        return JSONResponse({"error": "Email veya sifre hatali"})
    token = create_session(user_id=admin["id"], role="admin")
    resp = JSONResponse({"success": True})
    resp.set_cookie("session", token, max_age=604800, httponly=True)
    return resp

@app.get("/admin/panel", response_class=HTMLResponse)
def admin_panel(session: str = Cookie(default=None)):
    s = get_session(session)
    if not s or s["role"] != "admin":
        return RedirectResponse("/admin/giris", status_code=303)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT m.*, 
               (SELECT COUNT(*) FROM admin_chat c WHERE c.ticket_id=m.id) as mesaj_sayisi
        FROM admin_messages m ORDER BY m.created_at DESC
    """)
    tickets = cur.fetchall()
    # Istatistikler
    cur.execute("SELECT COUNT(*) as n FROM users")
    user_count = cur.fetchone()["n"]
    cur.execute("SELECT COUNT(*) as n FROM firm_accounts")
    firm_count = cur.fetchone()["n"]
    cur.execute("SELECT COUNT(*) as n FROM appointments")
    apt_count = cur.fetchone()["n"]
    cur.execute("SELECT COUNT(*) as n FROM admin_messages WHERE okundu=FALSE")
    unread_count = cur.fetchone()["n"]
    cur.close(); conn.close()

    ticket_rows = ""
    for t in tickets:
        badge = "badge-beklemede" if not t["cevaplandi"] else "badge-tamamlandi"
        durum = "Bekliyor" if not t["cevaplandi"] else "Cevaplandi"
        okundu_style = "font-weight:700" if not t["okundu"] else ""
        ticket_rows += f"""<tr onclick="window.location='/admin/mesaj/{t['id']}'" style="cursor:pointer">
          <td style="padding:8px;{okundu_style}">{t['sender_name']}</td>
          <td style="padding:8px;{okundu_style}">{t['sender_type']}</td>
          <td style="padding:8px;{okundu_style}">{t['konu']}</td>
          <td style="padding:8px">{t['mesaj_sayisi']} mesaj</td>
          <td style="padding:8px"><span class="badge {badge}">{durum}</span></td>
          <td style="padding:8px;color:#888;font-size:.75rem">{str(t['created_at'])[:16]}</td>
        </tr>"""

    if not ticket_rows:
        ticket_rows = '<tr><td colspan="6" style="padding:16px;text-align:center;color:#aaa">Henuz mesaj yok</td></tr>'

    body = _base_style() + "<body>" + _topbar("Admin Panel", "/", "Ana Sayfa")
    body += f"""<div class='wrap'>
      <div style='display:flex;gap:12px;flex-wrap:wrap;margin-bottom:16px'>
        <div class='card' style='flex:1;min-width:120px;text-align:center'>
          <div style='font-size:1.8rem;font-weight:800;color:#e53535'>{user_count}</div>
          <div style='font-size:.8rem;color:#888'>Kullanici</div>
        </div>
        <div class='card' style='flex:1;min-width:120px;text-align:center'>
          <div style='font-size:1.8rem;font-weight:800;color:#e53535'>{firm_count}</div>
          <div style='font-size:.8rem;color:#888'>Firma</div>
        </div>
        <div class='card' style='flex:1;min-width:120px;text-align:center'>
          <div style='font-size:1.8rem;font-weight:800;color:#e53535'>{apt_count}</div>
          <div style='font-size:.8rem;color:#888'>Randevu</div>
        </div>
        <div class='card' style='flex:1;min-width:120px;text-align:center'>
          <div style='font-size:1.8rem;font-weight:800;color:#e53535'>{unread_count}</div>
          <div style='font-size:.8rem;color:#888'>Okunmamis Mesaj</div>
        </div>
      </div>
      <div class='card'>
        <h2>&#128172; Mesajlar</h2>
        <div style='overflow-x:auto'>
        <table style='width:100%;border-collapse:collapse;font-size:.82rem'>
          <thead><tr style='background:#f5f0f0'>
            <th style='padding:8px;text-align:left'>Gonderen</th>
            <th style='padding:8px;text-align:left'>Tip</th>
            <th style='padding:8px;text-align:left'>Konu</th>
            <th style='padding:8px;text-align:left'>Mesajlar</th>
            <th style='padding:8px;text-align:left'>Durum</th>
            <th style='padding:8px;text-align:left'>Tarih</th>
          </tr></thead>
          <tbody>{ticket_rows}</tbody>
        </table></div>
      </div>
    </div></body></html>"""
    return HTMLResponse("<!DOCTYPE html><html lang='tr'><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Admin Panel</title>" + body)

@app.get("/admin/mesaj/{ticket_id}", response_class=HTMLResponse)
def admin_mesaj_detay(ticket_id: int, session: str = Cookie(default=None)):
    s = get_session(session)
    if not s or s["role"] != "admin":
        return RedirectResponse("/admin/giris", status_code=303)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM admin_messages WHERE id=%s", (ticket_id,))
    ticket = cur.fetchone()
    if not ticket:
        cur.close(); conn.close()
        return HTMLResponse("<p>Mesaj bulunamadi</p>", status_code=404)
    cur.execute("UPDATE admin_messages SET okundu=TRUE WHERE id=%s", (ticket_id,))
    cur.execute("SELECT * FROM admin_chat WHERE ticket_id=%s ORDER BY created_at", (ticket_id,))
    chats = cur.fetchall()
    conn.commit()
    cur.close(); conn.close()

    chat_html = ""
    for c in chats:
        is_admin = c["gonderen"] == "admin"
        align = "flex-end" if is_admin else "flex-start"
        bg = "#e53535" if is_admin else "#f0f0f0"
        color = "#fff" if is_admin else "#333"
        label = "Admin" if is_admin else ticket["sender_name"]
        chat_html += f"""<div style='display:flex;flex-direction:column;align-items:{align};margin-bottom:12px'>
          <div style='font-size:.72rem;color:#888;margin-bottom:3px'>{label} - {str(c['created_at'])[:16]}</div>
          <div style='background:{bg};color:{color};padding:10px 14px;border-radius:12px;max-width:80%;font-size:.85rem'>{c['mesaj']}</div>
        </div>"""

    if not chat_html:
        chat_html = f"""<div style='padding:16px;background:#f5f0f0;border-radius:8px;margin-bottom:16px'>
          <b>Ilk Mesaj:</b> {ticket['mesaj']}
        </div>"""

    body = _base_style() + "<body>" + _topbar("Mesaj Detay", "/admin/panel", "Admin Panel")
    body += f"""<div class='wrap' style='max-width:700px'>
      <div class='card'>
        <h2>&#128172; {ticket['konu']}</h2>
        <p style='font-size:.82rem;color:#888;margin-bottom:16px'>
          {ticket['sender_name']} ({ticket['sender_type']}) - {str(ticket['created_at'])[:16]}
        </p>
        <div style='height:400px;overflow-y:auto;border:1px solid #eee;border-radius:8px;padding:14px;margin-bottom:16px' id='chatbox'>
          {chat_html}
        </div>
        <div style='display:flex;gap:8px'>
          <textarea id='cevap' rows='3' style='flex:1;padding:8px;border:1px solid #ddd;border-radius:8px;font-family:inherit;font-size:.85rem' placeholder='Cevabinizi yazin...'></textarea>
          <button class='btn' onclick='adminCevapla()' style='align-self:flex-end'>Gonder</button>
        </div>
      </div>
    </div>
    <script>
    function adminCevapla(){{
      var msg=document.getElementById('cevap').value.trim();
      if(!msg)return;
      var fd=new FormData();
      fd.append('ticket_id','{ticket_id}');
      fd.append('mesaj',msg);
      fetch('/admin/cevapla',{{method:'POST',body:fd}})
        .then(r=>r.json())
        .then(d=>{{if(d.success)location.reload();else alert(d.error);}});
    }}
    document.getElementById('chatbox').scrollTop=document.getElementById('chatbox').scrollHeight;
    </script></body></html>"""
    return HTMLResponse("<!DOCTYPE html><html lang='tr'><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Mesaj</title>" + body)

@app.post("/admin/cevapla")
async def admin_cevapla(
    ticket_id: int = Form(...),
    mesaj: str = Form(...),
    session: str = Cookie(default=None)
):
    s = get_session(session)
    if not s or s["role"] != "admin":
        return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM admin_messages WHERE id=%s", (ticket_id,))
    ticket = cur.fetchone()
    if not ticket:
        cur.close(); conn.close()
        return JSONResponse({"error": "Mesaj bulunamadi"})
    cur.execute("INSERT INTO admin_chat (ticket_id, gonderen, mesaj) VALUES (%s,'admin',%s)",
               (ticket_id, mesaj))
    cur.execute("UPDATE admin_messages SET cevaplandi=TRUE, updated_at=NOW() WHERE id=%s", (ticket_id,))
    # Gondericiye bildirim
    if ticket["sender_type"] == "kullanici":
        add_notification(user_id=ticket["sender_id"], tip="admin_cevap",
                        mesaj=f"Admin mesajinizi cevapladi: {ticket['konu']}")
    else:
        add_notification(firm_id=ticket["sender_id"], tip="admin_cevap",
                        mesaj=f"Admin mesajinizi cevapladi: {ticket['konu']}")
    conn.commit()
    cur.close(); conn.close()
    return JSONResponse({"success": True})

@app.post("/mesaj/admin-gonder")
async def mesaj_admin_gonder(
    konu: str = Form(...),
    mesaj: str = Form(...),
    session: str = Cookie(default=None)
):
    s = get_session(session)
    if not s:
        return JSONResponse({"error": "Giris gerekli"}, status_code=401)
    conn = get_conn()
    cur = conn.cursor()
    if s["role"] == "user":
        cur.execute("SELECT ad_soyad FROM users WHERE id=%s", (s["user_id"],))
        row = cur.fetchone()
        sender_name = row["ad_soyad"] if row else "Kullanici"
        sender_id = s["user_id"]
        sender_type = "kullanici"
    else:
        cur.execute("SELECT unvan FROM firm_accounts WHERE id=%s", (s["firm_id"],))
        row = cur.fetchone()
        sender_name = row["unvan"] if row else "Firma"
        sender_id = s["firm_id"]
        sender_type = "firma"
    cur.execute(
        "INSERT INTO admin_messages (sender_type, sender_id, sender_name, konu, mesaj) VALUES (%s,%s,%s,%s,%s)",
        (sender_type, sender_id, sender_name, konu, mesaj)
    )
    conn.commit()
    # Ilk mesaji chat'e de ekle
    cur.execute("SELECT id FROM admin_messages WHERE sender_id=%s ORDER BY created_at DESC LIMIT 1", (sender_id,))
    ticket = cur.fetchone()
    if ticket:
        cur.execute("INSERT INTO admin_chat (ticket_id, gonderen, mesaj) VALUES (%s,%s,%s)",
                   (ticket["id"], sender_name, mesaj))
        conn.commit()
    cur.close(); conn.close()
    # Admin'e email
    from notifications import send_email
    send_email(ADMIN_EMAIL, f"Yeni Mesaj: {konu} - {sender_name}",
              f"<p><b>{sender_name}</b> ({sender_type}) yeni mesaj gonderdi.</p><p><b>Konu:</b> {konu}</p><p><b>Mesaj:</b> {mesaj}</p><p><a href='https://ekspertiz-bul.onrender.com/admin/panel'>Admin paneline git</a></p>")
    return JSONResponse({"success": True})

@app.get("/mesajlarim", response_class=HTMLResponse)
def mesajlarim(session: str = Cookie(default=None)):
    s = get_session(session)
    if not s or s["role"] not in ["user", "firma"]:
        return RedirectResponse("/giris", status_code=303)
    conn = get_conn()
    cur = conn.cursor()
    if s["role"] == "user":
        cur.execute("SELECT * FROM admin_messages WHERE sender_type='kullanici' AND sender_id=%s ORDER BY created_at DESC", (s["user_id"],))
    else:
        cur.execute("SELECT * FROM admin_messages WHERE sender_type='firma' AND sender_id=%s ORDER BY created_at DESC", (s["firm_id"],))
    tickets = cur.fetchall()
    cur.close(); conn.close()

    ticket_html = ""
    for t in tickets:
        badge = "badge-beklemede" if not t["cevaplandi"] else "badge-tamamlandi"
        durum = "Bekliyor" if not t["cevaplandi"] else "Cevaplandi"
        ticket_html += f"""<div class='card' style='cursor:pointer' onclick="window.location='/mesajlarim/{t['id']}'">
          <div style='display:flex;justify-content:space-between;align-items:center'>
            <div>
              <div style='font-weight:700'>{t['konu']}</div>
              <div style='font-size:.78rem;color:#888'>{str(t['created_at'])[:16]}</div>
            </div>
            <span class='badge {badge}'>{durum}</span>
          </div>
          <p style='font-size:.82rem;color:#666;margin-top:8px'>{t['mesaj'][:100]}{'...' if len(t['mesaj'])>100 else ''}</p>
        </div>"""

    back_url = "/kullanici/panel" if s["role"] == "user" else "/firma/panel"
    body = _base_style() + "<body>" + _topbar("Mesajlarim", back_url, "Panelim")
    body += "<div class='wrap' style='max-width:700px'>"
    body += """<div class='card'>
      <h2>&#128172; Yeni Mesaj Gonder</h2>
      <div id='msg'></div>
      <div class='form-group'><label>Konu</label>
        <select id='konu'>
          <option value='Sikayet'>Sikayet</option>
          <option value='Dilek/Istek'>Dilek/Istek</option>
          <option value='Teknik Sorun'>Teknik Sorun</option>
          <option value='Firma Dogrulama'>Firma Dogrulama</option>
          <option value='Diger'>Diger</option>
        </select>
      </div>
      <div class='form-group'><label>Mesaj</label>
        <textarea id='mesaj' rows='4' placeholder='Mesajinizi yazin...'></textarea>
      </div>
      <button class='btn' onclick='gonder()'>Gonder</button>
    </div>"""
    body += ticket_html if ticket_html else "<div class='card'><p style='color:#aaa;text-align:center'>Henuz mesaj yok</p></div>"
    body += """<script>
    function gonder(){
      var fd=new FormData();
      fd.append('konu',document.getElementById('konu').value);
      fd.append('mesaj',document.getElementById('mesaj').value);
      if(!fd.get('mesaj').trim()){alert('Mesaj bos olamaz!');return;}
      fetch('/mesaj/admin-gonder',{method:'POST',body:fd})
        .then(r=>r.json())
        .then(d=>{
          if(d.success){document.getElementById('msg').innerHTML='<div class="alert alert-success">Mesajiniz gonderildi!</div>';
            document.getElementById('mesaj').value='';setTimeout(()=>location.reload(),1500);}
          else document.getElementById('msg').innerHTML='<div class="alert alert-error">'+d.error+'</div>';
        });
    }
    </script></body></html>"""
    return HTMLResponse("<!DOCTYPE html><html lang='tr'><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Mesajlarim</title>" + body)

@app.get("/mesajlarim/{ticket_id}", response_class=HTMLResponse)
def mesaj_detay_kullanici(ticket_id: int, session: str = Cookie(default=None)):
    s = get_session(session)
    if not s or s["role"] not in ["user", "firma"]:
        return RedirectResponse("/giris", status_code=303)
    conn = get_conn()
    cur = conn.cursor()
    if s["role"] == "user":
        cur.execute("SELECT * FROM admin_messages WHERE id=%s AND sender_type='kullanici' AND sender_id=%s", (ticket_id, s["user_id"]))
    else:
        cur.execute("SELECT * FROM admin_messages WHERE id=%s AND sender_type='firma' AND sender_id=%s", (ticket_id, s["firm_id"]))
    ticket = cur.fetchone()
    if not ticket:
        cur.close(); conn.close()
        return HTMLResponse("<p>Bulunamadi</p>", status_code=404)
    cur.execute("SELECT * FROM admin_chat WHERE ticket_id=%s ORDER BY created_at", (ticket_id,))
    chats = cur.fetchall()
    cur.close(); conn.close()

    chat_html = ""
    for c in chats:
        is_admin = c["gonderen"] == "admin"
        align = "flex-end" if not is_admin else "flex-start"
        bg = "#e53535" if is_admin else "#f0f0f0"
        color = "#fff" if is_admin else "#333"
        label = "Admin" if is_admin else "Siz"
        chat_html += f"""<div style='display:flex;flex-direction:column;align-items:{align};margin-bottom:12px'>
          <div style='font-size:.72rem;color:#888;margin-bottom:3px'>{label} - {str(c['created_at'])[:16]}</div>
          <div style='background:{bg};color:{color};padding:10px 14px;border-radius:12px;max-width:80%;font-size:.85rem'>{c['mesaj']}</div>
        </div>"""

    back_url = "/mesajlarim"
    body = _base_style() + "<body>" + _topbar(ticket["konu"], back_url, "Mesajlarim")
    body += f"""<div class='wrap' style='max-width:700px'>
      <div class='card'>
        <div style='height:400px;overflow-y:auto;border:1px solid #eee;border-radius:8px;padding:14px;margin-bottom:16px' id='chatbox'>
          {chat_html}
        </div>
        <div style='display:flex;gap:8px'>
          <textarea id='cevap' rows='3' style='flex:1;padding:8px;border:1px solid #ddd;border-radius:8px;font-family:inherit;font-size:.85rem' placeholder='Mesajinizi yazin...'></textarea>
          <button class='btn' onclick='yanıtla()' style='align-self:flex-end'>Gonder</button>
        </div>
      </div>
    </div>
    <script>
    function yanıtla(){{
      var msg=document.getElementById('cevap').value.trim();
      if(!msg)return;
      var fd=new FormData();
      fd.append('ticket_id','{ticket_id}');
      fd.append('mesaj',msg);
      fetch('/mesajlarim/yanitla',{{method:'POST',body:fd}})
        .then(r=>r.json())
        .then(d=>{{if(d.success)location.reload();else alert(d.error);}});
    }}
    document.getElementById('chatbox').scrollTop=document.getElementById('chatbox').scrollHeight;
    </script></body></html>"""
    return HTMLResponse("<!DOCTYPE html><html lang='tr'><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Mesaj</title>" + body)

@app.post("/mesajlarim/yanitla")
async def mesaj_yanitla(
    ticket_id: int = Form(...),
    mesaj: str = Form(...),
    session: str = Cookie(default=None)
):
    s = get_session(session)
    if not s or s["role"] not in ["user", "firma"]:
        return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    conn = get_conn()
    cur = conn.cursor()
    if s["role"] == "user":
        cur.execute("SELECT * FROM admin_messages WHERE id=%s AND sender_type='kullanici' AND sender_id=%s", (ticket_id, s["user_id"]))
    else:
        cur.execute("SELECT * FROM admin_messages WHERE id=%s AND sender_type='firma' AND sender_id=%s", (ticket_id, s["firm_id"]))
    ticket = cur.fetchone()
    if not ticket:
        cur.close(); conn.close()
        return JSONResponse({"error": "Bulunamadi"})
    cur.execute("INSERT INTO admin_chat (ticket_id, gonderen, mesaj) VALUES (%s,%s,%s)",
               (ticket_id, ticket["sender_name"], mesaj))
    cur.execute("UPDATE admin_messages SET cevaplandi=FALSE, updated_at=NOW() WHERE id=%s", (ticket_id,))
    conn.commit()
    cur.close(); conn.close()
    from notifications import send_email
    send_email(ADMIN_EMAIL, f"Yeni Yanit: {ticket['konu']} - {ticket['sender_name']}",
              f"<p><b>{ticket['sender_name']}</b> mesajinizi yanıtladi.</p><p>{mesaj}</p><p><a href='https://ekspertiz-bul.onrender.com/admin/mesaj/{ticket_id}'>Goruntule</a></p>")
    return JSONResponse({"success": True})


# ============================================================
# RANDEVU MESAJLASMA
# ============================================================

@app.get("/randevu/{appointment_id}/mesajlar", response_class=HTMLResponse)
def randevu_mesajlar(appointment_id: int, session: str = Cookie(default=None)):
    s = get_session(session)
    if not s or s["role"] not in ["user", "firma"]:
        return RedirectResponse("/giris", status_code=303)
    conn = get_conn()
    cur = conn.cursor()
    # Randevuyu dogrula
    if s["role"] == "user":
        cur.execute("""
            SELECT a.*, f.unvan as karsi_ad, f.telefon as karsi_tel
            FROM appointments a JOIN firm_accounts f ON f.id=a.firm_id
            WHERE a.id=%s AND a.user_id=%s
        """, (appointment_id, s["user_id"]))
        benim_tip = "user"
        benim_id = s["user_id"]
    else:
        cur.execute("""
            SELECT a.*, u.ad_soyad as karsi_ad, u.telefon as karsi_tel
            FROM appointments a JOIN users u ON u.id=a.user_id
            WHERE a.id=%s AND a.firm_id=%s
        """, (appointment_id, s["firm_id"]))
        benim_tip = "firma"
        benim_id = s["firm_id"]
    apt = cur.fetchone()
    if not apt:
        cur.close(); conn.close()
        return HTMLResponse("<p>Randevu bulunamadi. <a href='/'>Ana Sayfa</a></p>", status_code=404)
    # Mesajlari getir
    cur.execute("SELECT * FROM messages WHERE appointment_id=%s ORDER BY created_at", (appointment_id,))
    mesajlar = cur.fetchall()
    cur.close(); conn.close()

    chat_html = ""
    for m in mesajlar:
        benim = (m["gonderen_tip"] == benim_tip and m["gonderen_id"] == benim_id)
        align = "flex-end" if benim else "flex-start"
        bg = "#e53535" if benim else "#f0f0f0"
        color = "#fff" if benim else "#333"
        label = "Siz" if benim else apt["karsi_ad"]
        chat_html += f"""<div style='display:flex;flex-direction:column;align-items:{align};margin-bottom:10px'>
          <div style='font-size:.7rem;color:#888;margin-bottom:2px'>{label} - {str(m['created_at'])[:16]}</div>
          <div style='background:{bg};color:{color};padding:10px 14px;border-radius:12px;max-width:75%;font-size:.85rem;word-break:break-word'>{m['mesaj']}</div>
        </div>"""

    if not chat_html:
        chat_html = "<p style='text-align:center;color:#aaa;padding:30px'>Henuz mesaj yok. Ilk mesaji siz gonderebilirsiniz.</p>"

    back_url = "/kullanici/panel" if s["role"] == "user" else "/firma/panel"
    arac = f"{apt.get('arac_marka','')} {apt.get('arac_model','')} {apt.get('arac_yil','')}".strip() or "Belirtilmedi"

    body = _base_style()
    body += """<style>
    .chat-container{height:calc(100vh - 280px);min-height:300px;overflow-y:auto;border:1px solid #eee;border-radius:8px;padding:14px;margin-bottom:12px;background:#fafafa}
    </style>"""
    body += "<body>" + _topbar("Mesajlar", back_url, "Panelim")
    body += f"""<div class='wrap' style='max-width:650px'>
      <div class='card' style='margin-bottom:8px;padding:12px'>
        <div style='font-weight:700'>{apt['karsi_ad']}</div>
        <div style='font-size:.78rem;color:#888'>{apt['tarih']} {apt['saat']} - {arac} - <span class='badge badge-{apt['durum']}'>{apt['durum'].title()}</span></div>
      </div>
      <div class='chat-container' id='chatbox'>{chat_html}</div>
      <div style='display:flex;gap:8px'>
        <textarea id='msg' rows='2' style='flex:1;padding:10px;border:1px solid #ddd;border-radius:10px;font-family:inherit;font-size:.88rem;resize:none' placeholder='Mesajinizi yazin...' onkeydown='if(event.ctrlKey&&event.key==="Enter")gonder()'></textarea>
        <button class='btn' onclick='gonder()' style='align-self:flex-end;padding:10px 20px'>Gonder</button>
      </div>
      <div style='font-size:.72rem;color:#aaa;margin-top:4px'>Ctrl+Enter ile gonderebilirsiniz</div>
    </div>
    <script>
    var APT_ID={appointment_id};
    function gonder(){{
      var msg=document.getElementById('msg').value.trim();
      if(!msg)return;
      var fd=new FormData();
      fd.append('appointment_id',APT_ID);
      fd.append('mesaj',msg);
      fetch('/randevu/mesaj/gonder',{{method:'POST',body:fd}})
        .then(r=>r.json())
        .then(d=>{{
          if(d.success){{
            document.getElementById('msg').value='';
            location.reload();
          }} else alert(d.error);
        }});
    }}
    document.getElementById('chatbox').scrollTop=document.getElementById('chatbox').scrollHeight;
    </script></body></html>"""
    return HTMLResponse("<!DOCTYPE html><html lang='tr'><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Mesajlar</title>" + body)

@app.post("/randevu/mesaj/gonder")
async def randevu_mesaj_gonder(
    appointment_id: int = Form(...),
    mesaj: str = Form(...),
    session: str = Cookie(default=None)
):
    s = get_session(session)
    if not s or s["role"] not in ["user", "firma"]:
        return JSONResponse({"error": "Yetkisiz"}, status_code=401)
    conn = get_conn()
    cur = conn.cursor()
    # Randevuyu dogrula
    if s["role"] == "user":
        cur.execute("SELECT * FROM appointments WHERE id=%s AND user_id=%s", (appointment_id, s["user_id"]))
        gonderen_tip = "user"
        gonderen_id = s["user_id"]
    else:
        cur.execute("SELECT * FROM appointments WHERE id=%s AND firm_id=%s", (appointment_id, s["firm_id"]))
        gonderen_tip = "firma"
        gonderen_id = s["firm_id"]
    apt = cur.fetchone()
    if not apt:
        cur.close(); conn.close()
        return JSONResponse({"error": "Randevu bulunamadi"})
    cur.execute(
        "INSERT INTO messages (appointment_id, gonderen_tip, gonderen_id, mesaj) VALUES (%s,%s,%s,%s)",
        (appointment_id, gonderen_tip, gonderen_id, mesaj)
    )
    # Karsi tarafa bildirim
    if gonderen_tip == "user":
        cur.execute("SELECT ad_soyad FROM users WHERE id=%s", (gonderen_id,))
        row = cur.fetchone()
        ad = row["ad_soyad"] if row else "Kullanici"
        add_notification(firm_id=apt["firm_id"], tip="yeni_mesaj",
                        mesaj=f"Yeni mesaj: {ad} - Randevu {apt['tarih']} {apt['saat']}",
                        appointment_id=appointment_id)
    else:
        cur.execute("SELECT unvan FROM firm_accounts WHERE id=%s", (gonderen_id,))
        row = cur.fetchone()
        ad = row["unvan"] if row else "Firma"
        add_notification(user_id=apt["user_id"], tip="yeni_mesaj",
                        mesaj=f"Yeni mesaj: {ad} - Randevu {apt['tarih']} {apt['saat']}",
                        appointment_id=appointment_id)
    conn.commit()
    cur.close(); conn.close()
    return JSONResponse({"success": True})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
