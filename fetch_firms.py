"""
Turkiye'deki tum oto ekspertiz firmalarini OpenStreetMap'ten ceker
Kullanim: python fetch_firms.py
"""
import httpx
import json

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

QUERY = """
[out:json][timeout:60];
area["name"="Türkiye"]["admin_level"="2"]->.tr;
(
  node["name"~"ekspertiz",i](area.tr);
  node["shop"="car_inspection"](area.tr);
  node["amenity"="vehicle_inspection"](area.tr);
);
out body;
"""

def build_address(tags):
    parts = []
    for k in ["addr:street","addr:housenumber","addr:district","addr:city","addr:province"]:
        if tags.get(k):
            parts.append(tags[k])
    return ", ".join(parts) if parts else "Adres bilgisi yok"

def fetch_firms():
    print("OpenStreetMap'ten firmalar cekiliyor (30-60 sn)...")
    try:
        r = httpx.post(OVERPASS_URL, data={"data": QUERY}, timeout=90)
        elements = r.json().get("elements", [])
        firms = []
        for el in elements:
            tags = el.get("tags", {})
            name = tags.get("name", "")
            lat = el.get("lat")
            lng = el.get("lon")
            if not name or not lat or not lng:
                continue
            firms.append({
                "id": f"osm_{el['id']}",
                "name": name,
                "address": build_address(tags),
                "phone": tags.get("phone", tags.get("contact:phone", "")),
                "website": tags.get("website", tags.get("contact:website", "")),
                "lat": lat,
                "lng": lng,
                "city": tags.get("addr:city", tags.get("addr:province", "")),
                "certified": False,
                "rating": 0,
                "reviews": 0,
            })
            print(f"  Bulundu: {name}")
        print(f"\nToplam {len(firms)} firma!")
        with open("firms_osm.json", "w", encoding="utf-8") as f:
            json.dump(firms, f, ensure_ascii=False, indent=2)
        print("firms_osm.json kaydedildi!")
        return firms
    except Exception as e:
        print(f"Hata: {e}")
        return []

if __name__ == "__main__":
    fetch_firms()
