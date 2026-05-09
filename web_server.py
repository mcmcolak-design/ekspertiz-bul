from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import json, sqlite3
from pathlib import Path

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
    if FIRMS_JSON.exists():
        with open(FIRMS_JSON, "r", encoding="utf-8") as f:
            firms = json.load(f)
            return [fi for fi in firms if fi.get("lat") and fi.get("lng")]
    return DEFAULT_FIRMS

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
<title>EkspertizBul - Turkiye'nin En Buyuk Ekspertiz Platformu</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:Inter,sans-serif;background:#f0f2f5;color:#1a1a2e}
header{background:linear-gradient(135deg,#1a1a2e,#16213e);color:#fff;padding:24px 16px;text-align:center}
h1{font-size:1.7rem;font-weight:800}h1 em{color:#00e5a0;font-style:normal}
header p{color:#aaa;font-size:.85rem;margin-top:4px}
.stats{display:flex;justify-content:center;gap:30px;margin-top:12px}
.stat{text-align:center}
.stat-n{font-size:1.4rem;font-weight:800;color:#00e5a0}
.stat-l{font-size:.72rem;color:#888}
.bar{background:#fff;padding:12px 16px;display:flex;align-items:center;gap:8px;box-shadow:0 2px 8px rgba(0,0,0,.07);flex-wrap:wrap}
.locbtn{background:#00e5a0;border:none;cursor:pointer;padding:10px 16px;border-radius:10px;font-weight:700;font-size:.85rem;color:#000;white-space:nowrap}
.locbtn:hover{background:#00ffa8}
.locinfo{color:#666;font-size:.82rem;display:flex;align-items:center;gap:6px;white-space:nowrap}
.dot{width:8px;height:8px;border-radius:50%;background:#ccc;display:inline-block}
.dot.on{background:#00e5a0;box-shadow:0 0 6px #00e5a0}
.search-bar{flex:1;min-width:140px}
.search-bar input{width:100%;padding:9px 14px;border:1px solid #ddd;border-radius:10px;font-size:.85rem;outline:none}
.search-bar input:focus{border-color:#00e5a0}
.sel-wrap{display:flex;gap:6px;flex-wrap:wrap}
.sel-wrap select{padding:9px 10px;border:1px solid #ddd;border-radius:10px;font-size:.82rem;outline:none;background:#fff;cursor:pointer;color:#333;max-width:150px}
.sel-wrap select:focus{border-color:#00e5a0}
#map{height:260px;border-bottom:3px solid #00e5a0}
.wrap{max-width:860px;margin:18px auto;padding:0 14px}
.sorts{display:flex;gap:7px;margin-bottom:12px;flex-wrap:wrap;align-items:center}
.sl{color:#888;font-size:.8rem}
.sb{background:#fff;border:1px solid #ddd;padding:6px 12px;border-radius:8px;cursor:pointer;font-size:.78rem}
.sb.on{border-color:#00e5a0;color:#00a875;background:#f0fff8}
.result-info{color:#888;font-size:.82rem;margin-bottom:10px}
.result-info strong{color:#1a1a2e}
.card{background:#fff;border-radius:12px;padding:16px;margin-bottom:10px;border:2px solid transparent;box-shadow:0 2px 8px rgba(0,0,0,.06)}
.card.top{border-color:#00e5a0;background:linear-gradient(135deg,#fff,#f0fff8)}
.ct{display:flex;justify-content:space-between;align-items:flex-start;gap:10px;flex-wrap:wrap;margin-bottom:8px}
.fn{font-weight:700;font-size:.95rem;display:flex;align-items:center;gap:5px;flex-wrap:wrap}
.bst{background:#00e5a0;color:#000;font-size:.6rem;font-weight:700;padding:2px 6px;border-radius:4px;text-transform:uppercase}
.fm{display:flex;gap:8px;flex-wrap:wrap;color:#888;font-size:.76rem;margin-top:2px}
.stars{color:#f5c518}
.db{background:#fff3cd;color:#856404;border:1px solid #ffc107;padding:4px 10px;border-radius:16px;font-weight:700;font-size:.8rem;white-space:nowrap}
.db.nr{background:#d4edda;color:#155724;border-color:#28a745}
.pkgs{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}
.pk{background:#f8f9fa;border:1px solid #eee;border-radius:7px;padding:6px 10px}
.pk.noprice{border-style:dashed;border-color:#ddd}
.pn{color:#888;font-size:.7rem}
.pp{font-weight:700;font-size:.88rem}
.pp.gray{color:#bbb;font-size:.75rem;font-weight:400;font-style:italic}
.acts{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap}
.ag{background:#00e5a0;border:none;cursor:pointer;padding:7px 14px;border-radius:8px;font-weight:600;font-size:.8rem;color:#000;text-decoration:none;display:inline-block}
.ag:hover{background:#00ffa8}
.aw{background:none;border:1px solid #ddd;cursor:pointer;padding:7px 12px;border-radius:8px;font-size:.8rem;color:#555}
.aw:hover{border-color:#00e5a0;color:#00a875}
.pagination{display:flex;justify-content:center;gap:6px;margin-top:16px;flex-wrap:wrap;padding-bottom:30px}
.pg{background:#fff;border:1px solid #ddd;padding:7px 12px;border-radius:8px;cursor:pointer;font-size:.8rem}
.pg.on{background:#00e5a0;border-color:#00e5a0;color:#000;font-weight:700}
</style>
</head>
<body>
<header>
  <h1>Ekspertiz<em>Bul</em></h1>
  <p>Turkiye'nin En Buyuk Oto Ekspertiz Platformu</p>
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

function applyFilters(){
  var q=document.getElementById('searchInput').value.toLowerCase().trim();
  var il=document.getElementById('ilSelect').value;
  var ilce=document.getElementById('ilceSelect').value;
  filtered=ALL_FIRMS.filter(function(f){
    var matchQ=!q||(f.name&&f.name.toLowerCase().includes(q))||(f.address&&f.address.toLowerCase().includes(q));
    var matchIl=!il||f.city===il;
    var matchIlce=!ilce||(f.address&&f.address.includes(ilce));
    return matchQ&&matchIl&&matchIlce;
  });
  page=1;render();
}

function initMap(){
  map=L.map('map').setView([39.9,32.8],6);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'OpenStreetMap'}).addTo(map);
  ALL_FIRMS.slice(0,200).forEach(function(f){
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
    var ic=L.divIcon({html:'<div style="width:12px;height:12px;background:#00e5a0;border-radius:50%;border:2px solid #fff;box-shadow:0 0 6px #00e5a0"></div>',iconSize:[12,12],iconAnchor:[6,6]});
    um=L.marker([uLat,uLng],{icon:ic}).addTo(map).bindPopup('Siz').openPopup();
    page=1;render();
  },function(){document.getElementById('loctxt').textContent='Konum alinamadi - izin verin';});
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
          '<div class="fn">'+f.name+(nr?'<span class="bst">En Yakin</span>':'')+'</div>'+
          '<div class="fm">'+(stars?'<span class="stars">'+stars+'</span> '+f.rating+' ('+(f.reviews||0)+') ':'')+
          (f.city||'')+(f.address?' \u2022 '+f.address:'')+'</div>'+
        '</div>'+(ds?'<div class="db'+(nr?' nr':'')+'">'+ds+'</div>':'')+
        '</div>'+
        '<div class="pkgs">'+pk+'</div>'+
        '<div class="acts">'+
          '<a href="'+detayUrl+'" target="_blank" class="ag">Detay</a>'+
          '<button class="aw" onclick="goMap('+f.lat+','+f.lng+')">Harita</button>'+
          '<button class="aw" onclick="yol('+f.lat+','+f.lng+')">Yol Tarifi</button>'+
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
</script>
</body>
</html>"""

@app.get("/", response_class=HTMLResponse)
def index():
    firms = load_firms()
    prices = get_prices()
    firms_json = json.dumps(firms, ensure_ascii=False)
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
