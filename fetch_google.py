"""
Turkiye'deki tum oto ekspertiz firmalarini Google Maps Places API ile ceker.
Kullanim: python fetch_google.py
"AIzaSyCF8mCaR-wVpNPgN2X0KtNESltXkb-K4Ko"
"""
import httpx
import json
import time

# API anahtarinizi buraya girin
API_KEY = "AIzaSyCF8mCaR-wVpNPgN2X0KtNESltXkb-K4Ko"

# Turkiye'nin buyuk sehirleri - koordinatlar
CITIES = [
    ("Istanbul", 41.0082, 28.9784),
    ("Ankara", 39.9334, 32.8597),
    ("Izmir", 38.4237, 27.1428),
    ("Bursa", 40.1826, 29.0665),
    ("Antalya", 36.8969, 30.7133),
    ("Adana", 37.0000, 35.3213),
    ("Konya", 37.8667, 32.4833),
    ("Gaziantep", 37.0662, 37.3833),
    ("Mersin", 36.8000, 34.6333),
    ("Kayseri", 38.7312, 35.4787),
    ("Eskisehir", 39.7767, 30.5206),
    ("Diyarbakir", 37.9144, 40.2306),
    ("Samsun", 41.2867, 36.3300),
    ("Denizli", 37.7765, 29.0864),
    ("Sanliurfa", 37.1591, 38.7969),
    ("Trabzon", 41.0015, 39.7178),
    ("Malatya", 38.3552, 38.3095),
    ("Erzurum", 39.9208, 41.2671),
    ("Van", 38.4891, 43.4089),
    ("Tekirdag", 40.9833, 27.5167),
    ("Manisa", 38.6191, 27.4289),
    ("Balikesir", 39.6484, 27.8826),
    ("Kocaeli", 40.8533, 29.8815),
    ("Sakarya", 40.7731, 30.3948),
    ("Zonguldak", 41.4564, 31.7987),
    ("Hatay", 36.4018, 36.3498),
    ("Kahramanmaras", 37.5858, 36.9371),
    ("Mugla", 37.2153, 28.3636),
    ("Aydin", 37.8560, 27.8416),
]

BASE_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"

def search_firms_in_city(city_name, lat, lng):
    firms = []
    params = {
        "location": f"{lat},{lng}",
        "radius": 30000,  # 30 km yaricap
        "keyword": "oto ekspertiz",
        "language": "tr",
        "key": API_KEY,
    }
    
    while True:
        try:
            r = httpx.get(BASE_URL, params=params, timeout=15)
            data = r.json()
            
            if data.get("status") not in ["OK", "ZERO_RESULTS"]:
                print(f"  Hata: {data.get('status')} - {data.get('error_message','')}")
                break
            
            results = data.get("results", [])
            for place in results:
                firm = {
                    "id": "gmaps_" + place["place_id"],
                    "name": place.get("name", ""),
                    "address": place.get("vicinity", ""),
                    "phone": "",
                    "website": "",
                    "lat": place["geometry"]["location"]["lat"],
                    "lng": place["geometry"]["location"]["lng"],
                    "city": city_name,
                    "certified": False,
                    "rating": place.get("rating", 0),
                    "reviews": place.get("user_ratings_total", 0),
                    "place_id": place["place_id"],
                }
                firms.append(firm)
            
            # Sonraki sayfa var mi?
            next_token = data.get("next_page_token")
            if not next_token:
                break
            
            time.sleep(2)  # Google next_page_token icin bekle
            params = {"pagetoken": next_token, "key": API_KEY}
            
        except Exception as e:
            print(f"  Hata: {e}")
            break
    
    return firms

def main():
    if API_KEY == "BURAYA_API_ANAHTARINIZI_YAZIN":
        print("HATA: API anahtarinizi girin!")
        print("fetch_google.py dosyasini acin ve API_KEY satirini doldurun.")
        return
    
    all_firms = []
    seen_ids = set()
    
    print(f"Toplam {len(CITIES)} sehir taranacak...\n")
    
    for city_name, lat, lng in CITIES:
        print(f"Taraniyor: {city_name}...")
        firms = search_firms_in_city(city_name, lat, lng)
        
        new_count = 0
        for f in firms:
            if f["id"] not in seen_ids:
                seen_ids.add(f["id"])
                all_firms.append(f)
                new_count += 1
        
        print(f"  {new_count} yeni firma bulundu (toplam: {len(all_firms)})")
        time.sleep(0.5)
    
    print(f"\nToplam {len(all_firms)} firma bulundu!")
    
    with open("firms_google.json", "w", encoding="utf-8") as f:
        json.dump(all_firms, f, ensure_ascii=False, indent=2)
    
    print("firms_google.json kaydedildi!")
    print("\nIlk 10 firma:")
    for firm in all_firms[:10]:
        print(f"  {firm['name']} | {firm['city']} | Puan: {firm['rating']}")

if __name__ == "__main__":
    main()
