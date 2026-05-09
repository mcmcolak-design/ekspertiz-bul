"""
Buyuk ekspertiz zincirlerinin fiyatlarini DB'ye ekler ve
firms_google.json'daki eslesmelere website bilgisi yazar.
Kullanim: python populate_prices.py
"""
import sqlite3
import json
from pathlib import Path

DB_PATH = Path("ekspertiz_prices.db")
FIRMS_JSON = Path("firms_google.json")

# ============================================================
# 2026 GUNCEL FIYAT LISTESI (resmi sitelerden toplandi)
# ============================================================
CHAIN_PRICES = {
    "otorapor": {
        "website": "https://www.otorapor.com.tr",
        "packages": [
            ("Kaporta/Boya Paketi", 4900),
            ("Bronz Paket",         5500),
            ("Silver Paket",        6900),
            ("Gold Paket",          7800),
            ("Full Paket",          9000),
            ("Luxury Paket",       13000),
            ("Premium Paket",      16000),
        ]
    },
    "dynobil": {
        "website": "https://www.dynobil.com",
        "packages": [
            ("Standart Paket",  6500),
            ("Plus Paket",      8500),
            ("Pro Paket",      11500),
        ]
    },
    "autoking": {
        "website": "https://www.autoking.com.tr",
        "packages": [
            ("Eko Paket",       5000),
            ("Standart Paket",  7500),
            ("Pro Paket",      10000),
            ("King Plus Paket",13000),
        ]
    },
    "arabam": {
        "website": "https://www.arabam.com/oto-ekspertiz",
        "packages": [
            ("Temel Paket",     5000),
            ("Standart Paket",  7500),
            ("Full Paket",     11000),
        ]
    },
    "pilot garage": {
        "website": "https://pilotgarage.com",
        "packages": [
            ("Temel Paket",     4500),
            ("Standart Paket",  7000),
            ("Full Paket",     10500),
        ]
    },
    "yamanlar": {
        "website": "https://yamanlarekspertiz.com.tr",
        "packages": [
            ("Baz Paket",       5000),
            ("Standart Paket",  7500),
            ("Yaman+ Plus",    11000),
        ]
    },
}

# Firma adi -> zincir eslesmesi (kucuk harf eslesme anahtarlari)
CHAIN_KEYWORDS = {
    "otorapor":     "otorapor",
    "dynobil":      "dynobil",
    "autoking":     "autoking",
    "auto king":    "autoking",
    "arabam":       "arabam",
    "pilot garage": "pilot garage",
    "pilotgarage":  "pilot garage",
    "yamanlar":     "yamanlar",
}

def setup_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS firms (
            firm_id TEXT PRIMARY KEY,
            firm_name TEXT,
            city TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS packages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            firm_id TEXT,
            package_name TEXT,
            price INTEGER,
            scraped_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (firm_id) REFERENCES firms(firm_id)
        )
    """)
    conn.commit()

def get_chain(name):
    n = name.lower()
    for keyword, chain in CHAIN_KEYWORDS.items():
        if keyword in n:
            return chain
    return None

def main():
    # DB kur
    conn = sqlite3.connect(DB_PATH)
    setup_db(conn)

    # Mevcut fiyatlari temizle (yeniden yukle)
    conn.execute("DELETE FROM packages")
    conn.execute("DELETE FROM firms")
    conn.commit()

    # firms_google.json yukle
    if not FIRMS_JSON.exists():
        print("HATA: firms_google.json bulunamadi!")
        return

    firms = json.load(open(FIRMS_JSON, encoding="utf-8"))
    print(f"Toplam {len(firms)} firma yuklendi\n")

    matched = 0
    chain_counts = {}

    for f in firms:
        chain = get_chain(f.get("name", ""))
        if not chain:
            continue

        firm_id = f["id"]
        chain_data = CHAIN_PRICES[chain]

        # Firma DB'ye ekle
        conn.execute(
            "INSERT OR REPLACE INTO firms (firm_id, firm_name, city) VALUES (?,?,?)",
            (firm_id, f["name"], f.get("city", ""))
        )

        # Paketleri ekle
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for pkg_name, price in chain_data["packages"]:
            conn.execute(
                "INSERT INTO packages (firm_id, package_name, price, scraped_at) VALUES (?,?,?,?)",
                (firm_id, pkg_name, price, now)
            )

        # firms_google.json'a website ekle
        if not f.get("website"):
            f["website"] = chain_data["website"]

        matched += 1
        chain_counts[chain] = chain_counts.get(chain, 0) + 1

    conn.commit()
    conn.close()

    # firms_google.json guncelle (website alanlariyla)
    json.dump(firms, open(FIRMS_JSON, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

    print("Eslesen firmalar:")
    for chain, count in sorted(chain_counts.items(), key=lambda x: -x[1]):
        print(f"  {chain}: {count} sube")
    print(f"\nToplam {matched} firmaya fiyat eklendi!")
    print(f"ekspertiz_prices.db guncellendi")
    print(f"firms_google.json guncellendi (website alanlari dolduruldu)")

    # Ozet kontrol
    conn2 = sqlite3.connect(DB_PATH)
    total_pkgs = conn2.execute("SELECT COUNT(*) FROM packages").fetchone()[0]
    total_firms = conn2.execute("SELECT COUNT(*) FROM firms").fetchone()[0]
    conn2.close()
    print(f"\nDB ozeti: {total_firms} firma, {total_pkgs} fiyat kaydi")

if __name__ == "__main__":
    main()
