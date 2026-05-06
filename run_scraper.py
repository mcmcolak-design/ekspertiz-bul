"""
EkspertizBul — Ana Scraper Orkestratörü
Tüm scraperları paralel çalıştırır, sonuçları SQLite/PostgreSQL'e yazar.

Kullanım:
    python run_scraper.py                  # Tüm firmaları tara
    python run_scraper.py --firm otorapor  # Sadece bir firma
    python run_scraper.py --dry-run        # Veritabanına yazma, sadece göster
"""
import asyncio
import argparse
import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

# Scraper importları
from scrapers.base_scraper import FirmResult
from scrapers.otorapor_scraper import OtoraporScraper
from scrapers.autoking_scraper import AutoKingScraper
from scrapers.other_scrapers import DynomossScraper, RSEkspertizScraper, ArabamEkspertizScraper

# ─── Logging ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("orchestrator")


# ─── Kayıtlı scraper listesi ────────────────────────────────
ALL_SCRAPERS = [
    OtoraporScraper,
    AutoKingScraper,
    DynomossScraper,
    RSEkspertizScraper,
    ArabamEkspertizScraper,
]

# Firma ID'ye göre hızlı erişim
SCRAPER_MAP = {cls.FIRM_ID: cls for cls in ALL_SCRAPERS}


# ─── Veritabanı ─────────────────────────────────────────────
DB_PATH = Path(__file__).parent / "ekspertiz_prices.db"

def init_db(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS firms (
            firm_id     TEXT PRIMARY KEY,
            firm_name   TEXT NOT NULL,
            website     TEXT,
            city        TEXT,
            phone       TEXT,
            address     TEXT,
            last_seen   TEXT
        );

        CREATE TABLE IF NOT EXISTS packages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            firm_id         TEXT NOT NULL,
            package_name    TEXT NOT NULL,
            price           REAL,
            points          INTEGER,
            features        TEXT,   -- JSON array
            is_discounted   INTEGER DEFAULT 0,
            original_price  REAL,
            scraped_at      TEXT NOT NULL,
            FOREIGN KEY (firm_id) REFERENCES firms(firm_id)
        );

        CREATE TABLE IF NOT EXISTS scrape_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            firm_id     TEXT NOT NULL,
            scraped_at  TEXT NOT NULL,
            success     INTEGER,
            error       TEXT,
            pkg_count   INTEGER
        );

        CREATE INDEX IF NOT EXISTS idx_packages_firm ON packages(firm_id);
        CREATE INDEX IF NOT EXISTS idx_packages_time ON packages(scraped_at);
    """)
    conn.commit()


def save_result(conn: sqlite3.Connection, result: FirmResult):
    now = result.scraped_at.isoformat()

    # Firma kaydı ekle/güncelle
    conn.execute("""
        INSERT INTO firms (firm_id, firm_name, website, city, phone, address, last_seen)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(firm_id) DO UPDATE SET
            last_seen = excluded.last_seen,
            phone     = COALESCE(excluded.phone, phone),
            address   = COALESCE(excluded.address, address)
    """, (result.firm_id, result.firm_name, result.website,
          result.city, result.phone, result.address, now))

    # Bu çalışmanın paketlerini kaydet
    for pkg in result.packages:
        conn.execute("""
            INSERT INTO packages
                (firm_id, package_name, price, points, features, is_discounted, original_price, scraped_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            result.firm_id,
            pkg.name,
            pkg.price,
            pkg.points,
            json.dumps(pkg.features, ensure_ascii=False),
            int(pkg.is_discounted),
            pkg.original_price,
            now,
        ))

    # Log kaydı
    conn.execute("""
        INSERT INTO scrape_log (firm_id, scraped_at, success, error, pkg_count)
        VALUES (?, ?, ?, ?, ?)
    """, (result.firm_id, now, int(result.success), result.error, len(result.packages)))

    conn.commit()


def get_latest_prices(conn: sqlite3.Connection) -> list[dict]:
    """Her firmadan en son fiyatları çek — karşılaştırma için"""
    rows = conn.execute("""
        SELECT
            f.firm_name,
            f.website,
            p.package_name,
            p.price,
            p.points,
            p.features,
            p.is_discounted,
            p.scraped_at
        FROM packages p
        JOIN firms f ON f.firm_id = p.firm_id
        WHERE p.scraped_at = (
            SELECT MAX(p2.scraped_at)
            FROM packages p2
            WHERE p2.firm_id = p.firm_id
        )
        ORDER BY p.price ASC NULLS LAST
    """).fetchall()

    return [dict(zip([d[0] for d in rows[0].description] if rows else [], row)) for row in rows]


# ─── Paralel çalıştırma ─────────────────────────────────────
async def run_all(firm_ids: list[str] | None = None, dry_run: bool = False) -> list[FirmResult]:
    scrapers_to_run = [
        cls() for cls in ALL_SCRAPERS
        if (firm_ids is None or cls.FIRM_ID in firm_ids)
    ]

    logger.info(f"🚀 {len(scrapers_to_run)} firma taranıyor: {[s.FIRM_ID for s in scrapers_to_run]}")

    # Eş zamanlı çalıştır (max 3 paralel — sunucu yükü için)
    semaphore = asyncio.Semaphore(3)

    async def run_one(scraper):
        async with semaphore:
            logger.info(f"  → {scraper.FIRM_NAME} başlıyor...")
            try:
                result = await scraper.scrape()
                status = "✓" if result.success else "✗ fallback"
                logger.info(f"  {status} {scraper.FIRM_NAME}: {len(result.packages)} paket")
                return result
            except Exception as e:
                logger.error(f"  ✗ {scraper.FIRM_NAME} kritik hata: {e}")
                return scraper._make_error(str(e))

    results = await asyncio.gather(*[run_one(s) for s in scrapers_to_run])

    if not dry_run:
        conn = sqlite3.connect(DB_PATH)
        init_db(conn)
        for r in results:
            save_result(conn, r)
        conn.close()
        logger.info(f"💾 Veritabanı güncellendi: {DB_PATH}")

    return list(results)


def print_summary(results: list[FirmResult]):
    print("\n" + "═" * 60)
    print(f"  EKSPERTİZ FİYATLARI — {datetime.now().strftime('%d.%m.%Y %H:%M')}")
    print("═" * 60)
    for r in results:
        icon = "✓" if r.success else "⚠"
        fallback = " [fallback]" if r.error and "Fallback" in str(r.error) else ""
        print(f"\n{icon} {r.firm_name}{fallback}")
        print(f"   {r.website}")
        if r.packages:
            for pkg in r.packages:
                pts = f" | {pkg.points} nokta" if pkg.points else ""
                price_str = f"₺{pkg.price:,.0f}" if pkg.price else "?"
                disc = " 🏷" if pkg.is_discounted else ""
                print(f"   • {pkg.name:<30} {price_str}{pts}{disc}")
        else:
            print("   (fiyat bulunamadı)")
    print("\n" + "═" * 60)
    success_count = sum(1 for r in results if r.success and not (r.error and "Fallback" in str(r.error or "")))
    print(f"  Sonuç: {success_count}/{len(results)} firma canlı veri — {len(results)-success_count} fallback")
    print("═" * 60 + "\n")


# ─── Entry point ────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EkspertizBul Scraper")
    parser.add_argument("--firm", nargs="*", help=f"Firma ID'leri: {list(SCRAPER_MAP.keys())}")
    parser.add_argument("--dry-run", action="store_true", help="DB'ye yazma")
    parser.add_argument("--json", action="store_true", help="JSON çıktı ver")
    args = parser.parse_args()

    results = asyncio.run(run_all(
        firm_ids=args.firm,
        dry_run=args.dry_run,
    ))

    if args.json:
        import dataclasses
        output = []
        for r in results:
            d = dataclasses.asdict(r)
            d['scraped_at'] = r.scraped_at.isoformat()
            output.append(d)
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        print_summary(results)
