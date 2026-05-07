from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import json, sqlite3
from pathlib import Path

app = FastAPI()
DB_PATH = Path(__file__).parent / "ekspertiz_prices.db"

FIRMS = [
    {"id":"otorapor","name":"Otorapor Ekspertiz","address":"Bagcilar, Istanbul","phone":"0850 XXX XX XX","website":"https://www.otorapor.com.tr","lat":41.0392,"lng":28.8562,"certified":True,"rating":4.8,"reviews":1243},
    {"id":"autoking","name":"Auto King Ekspertiz","address":"Sisli, Istanbul","phone":"0212 XXX XX XX","website":"https://www.autoking.com.tr","lat":41.0602,"lng":28.9877,"certified":True,"rating":4.6,"reviews":876},
    {"id":"dynomoss","name":"Dynomoss Ekspertiz","address":"Kadikoy, Istanbul","phone":"0216 XXX XX XX","website":"https://dynomoss.com.tr","lat":40.9833,"lng":29.0333,"certified":False,"rating":4.5,"reviews":654},
    {"id":"rs_ekspertiz","name":"RS Oto Ekspertiz","address":"Besiktas, Istanbul","phone":"0212 XXX XX XX","website":"https://rsotoekspertiz.com","lat":41.0430,"lng":29.0070,"certified":True,"rating":4.3,"reviews":412},
    {"id":"arabam_ekspertiz","name":"Arabam.com Ekspertiz","address":"Maslak, Istanbul","phone":"0850 XXX XX XX","website":"https://www.arabam.com/oto-ekspertiz","lat":41.1057,"lng":29.0157,"certified":True,"rating":4.9,"reviews":2108},
]

def get_prices():
    if not DB_PATH.exists():
        return {}
    conn = sqlite3.connect(DB_PATH)
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
    return prices

PAGE = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>EkspertizBul</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:Inter,sans-serif;background:#f0f2f5;color:#1a1a2e}
header{background:linear-gradient(135deg,#1a1a2e,#16213e);color:#fff;padding:24px 16px;text-align:center}
h1{font-size:1.7rem;font-weight:800}h1 em{color:#00e5a0;font-style:normal}
header p{color:#aaa;font-size:.85rem;margin-top:4px}
.bar{background:#fff;padding:12px 16px;display:flex;align-items:center;gap:10px;box-shadow:0 2px 8px rgba(0,0,0,.07);flex-wrap:wrap}
.locbtn{background:#00e5a0;border:none;cursor:pointer;padding:10px 20px;border-radius:10px;font-weight:700;font-size:.88rem;color:#000}
.locbtn:hover{background:#00ffa8}
.locinfo{color:#666;font-size:.82rem;display:flex;align-items:center;gap:6px}
.dot{width:8px;height:8px;border-radius:50%;background:#ccc;display:inline-block}
.dot.on{background:#00e5a0;box-shadow:0 0 6px #00e5a0}
#map{height:260px;border-bottom:3px solid #00e5a0}
.wrap{max-width:860px;margin:18px auto;padding:0 14px}
.sorts{display:flex;gap:7px;margin-bottom:12px;flex-wrap:wrap;align-items:center}
.sl{color:#888;font-size:.8rem}
.sb{background:#fff;border:1px solid #ddd;padding:6px 12px;border-radius:8px;cursor:pointer;font-size:.78rem}
.sb.on{border-color:#00e5a0;color:#00a875;background:#f0fff8}
.card{background:#fff;border-radius:12px;padding:16px;margin-bottom:10px;border:2px solid transparent;box-shadow:0 2px 8px rgba(0,0,0,.06)}
.card.top{border-color:#00e5a0;background:linear-gradient(135deg,#fff,#f0fff8)}
.ct{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;flex-wrap:wrap;margin-bottom:8px}
.fn{font-weight:700;font-size:.95rem;display:flex;align-items:center;gap:5px;flex-wrap:wrap}
.bst{background:#00e5a0;color:#000;font-size:.6rem;font-weight:700;padding:2px 6px;border-radius:4px;text-transform:uppercase}
.bce{background:#e8e4ff;color:#6c47ff;font-size:.6rem;font-weight:700;padding:2px 6px;border-radius:4px;text-transform:uppercase}
.fm{display:flex;gap:8px;flex-wrap:wrap;color:#888;font-size:.76rem;margin-top:2px}
.db{background:#fff3cd;color:#856404;border:1px solid #ffc107;padding:4px 10px;border-radius:16px;font-weight:700;font-size:.8rem;white-space:nowrap}
.db.nr{background:#d4edda;color:#155724;border-color:#28a745}
.pkgs{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}
.pk{background:#f8f9fa;border:1px solid #eee;border-radius:7px;padding:6px 10px}
.pn{color:#888;font-size:.7rem}
.pp{font-weight:700;font-size:.88rem}
.acts{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap}
.ag{background:#00e5a0;border:none;cursor:pointer;padding:7px 14px;border-radius:8px;font-weight:600;font-size:.8rem;color:#000;text-decoration:none;display:inline-block}
.aw{background:none;border:1px solid #ddd;cursor:pointer;padding:7px 12px;border-radius:8px;font-size:.8rem;color:#555}
.aw:hover{border-color:#00e5a0;color:#00a875}
</style>
</head>
<body>
<header>
  <h1>Ekspertiz<em>Bul</em></h1>
  <p>Konumunuza En Yakin Oto Ekspertiz Firmalarini Bulun</p>
</header>
<div class="bar">
  <button class="locbtn" id="locbtn" onclick="getLoc()">Konumumu Bul</button>
  <div class="locinfo"><span class="dot" id="dot"></span><span id="loctxt">Konum alinmadi</span></div>
</div>
<div id="map"></div>
<div class="wrap">
  <div class="sorts">
    <span class="sl">Sirala:</span>
    <button class="sb on" id="b1" onclick="sort('dist','b1')">En Yakin</button>
    <button class="sb" id="b2" onclick="sort('price','b2')">En Ucuz</button>
    <button class="sb" id="b3" onclick="sort('rating','b3')">En Yuksek Puan</button>
  </div>
  <div id="list"></div>
</div>
<script>
var F=FIRMS_PLACEHOLDER;
var P=PRICES_PLACEHOLDER;
var uLat=null,uLng=null,map=null,um=null,srt='dist';
function initMap(){
  map=L.map('map').setView([39.9,32.8],6);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'OpenStreetMap'}).addTo(map);
  F.forEach(function(f){L.marker([f.lat,f.lng]).addTo(map).bindPopup('<b>'+f.name+'</b><br>'+f.address);});
}
function getLoc(){
  document.getElementById('loctxt').textContent='Alinıyor...';
  if(!navigator.geolocation){alert('Konum desteklenmiyor');return;}
  navigator.geolocation.getCurrentPosition(function(p){
    uLat=p.coords.latitude;uLng=p.coords.longitude;
    document.getElementById('dot').className='dot on';
    document.getElementById('loctxt').textContent='Konum alindi';
    map.setView([uLat,uLng],12);
    if(um)map.removeLayer(um);
    var ic=L.divIcon({html:'<div style="width:12px;height:12px;background:#00e5a0;border-radius:50%;border:2px solid #fff;box-shadow:0 0 6px #00e5a0"></div>',iconSize:[12,12],iconAnchor:[6,6]});
    um=L.marker([uLat,uLng],{icon:ic}).addTo(map).bindPopup('Siz').openPopup();
    render();
  },function(){document.getElementById('loctxt').textContent='Konum alinamadi - izin verin';});
}
function dist(a,b,c,d){
  var R=6371,dl=(c-a)*Math.PI/180,dg=(d-b)*Math.PI/180;
  var x=Math.sin(dl/2)*Math.sin(dl/2)+Math.cos(a*Math.PI/180)*Math.cos(c*Math.PI/180)*Math.sin(dg/2)*Math.sin(dg/2);
  return R*2*Math.atan2(Math.sqrt(x),Math.sqrt(1-x));
}
function sort(t,id){
  srt=t;
  ['b1','b2','b3'].forEach(function(i){document.getElementById(i).className='sb';});
  document.getElementById(id).className='sb on';
  render();
}
function render(){
  var list=F.map(function(f){return Object.assign({},f,{d:(uLat&&uLng)?dist(uLat,uLng,f.lat,f.lng):null,pkgs:P[f.id]||[]});});
  list.sort(function(a,b){
    if(srt==='dist'){if(!a.d)return 1;if(!b.d)return -1;return a.d-b.d;}
    if(srt==='price'){return(a.pkgs[0]?a.pkgs[0].price:99999)-(b.pkgs[0]?b.pkgs[0].price:99999);}
    return b.rating-a.rating;
  });
  var h='';
  list.forEach(function(f,i){
    var nr=i===0&&f.d!==null;
    var ds=f.d!==null?f.d.toFixed(1)+' km':'Konum yok';
    var pk='';
    f.pkgs.slice(0,3).forEach(function(p){pk+='<div class="pk"><div class="pn">'+p.name+'</div><div class="pp">'+p.price+'TL</div></div>';});
    if(!pk)pk='<div class="pk"><div class="pn">Fiyat yukleniyor</div></div>';
    h+='<div class="card'+(nr?' top':'')+'"><div class="ct"><div><div class="fn">'+f.name+(nr?'<span class="bst">En Yakin</span>':'')+(f.certified?'<span class="bce">Sertifikali</span>':'')+'</div><div class="fm"><span>'+f.rating+' ('+f.reviews+')</span><span>'+f.address+'</span></div></div><div class="db'+(nr?' nr':'')+'">'+ds+'</div></div><div class="pkgs">'+pk+'</div><div class="acts"><a href="'+f.website+'" target="_blank" class="ag">Randevu Al</a><button class="aw" onclick="goMap('+f.lat+','+f.lng+')">Haritada Gor</button><button class="aw" onclick="yol('+f.lat+','+f.lng+')">Yol Tarifi</button></div></div>';
  });
  document.getElementById('list').innerHTML=h;
}
function goMap(lat,lng){map.setView([lat,lng],15);window.scrollTo({top:0,behavior:'smooth'});}
function yol(lat,lng){window.open(uLat?'https://www.google.com/maps/dir/'+uLat+','+uLng+'/'+lat+','+lng:'https://www.google.com/maps/?q='+lat+','+lng,'_blank');}
initMap();render();
</script>
</body>
</html>"""

@app.get("/", response_class=HTMLResponse)
def index():
    prices = get_prices()
    firms_json = json.dumps(FIRMS, ensure_ascii=False)
    prices_json = json.dumps(prices, ensure_ascii=False)
    html = PAGE.replace("FIRMS_PLACEHOLDER", firms_json).replace("PRICES_PLACEHOLDER", prices_json)
    return html

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
    
