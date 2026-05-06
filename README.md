# EkspertizBul Scraper

Türkiye'deki oto ekspertiz firmalarının fiyatlarını otomatik toplayan Python scripti.

## Desteklenen Firmalar

| Firma | Website | Yöntem | Durum |
|-------|---------|--------|-------|
| Otorapor | otorapor.com.tr | Playwright (Nuxt.js) | ✅ |
| Auto King | autoking.com.tr | httpx + Playwright | ✅ |
| Dynomoss | dynomoss.com.tr | httpx + Playwright | ✅ |
| RS Oto Ekspertiz | rsotoekspertiz.com | Playwright | ✅ |
| Arabam.com Ekspertiz | arabam.com/oto-ekspertiz | Playwright (React) | ✅ |

> Tüm scraperlar **fallback fiyat** içerir — site değişikliğinde
> Şubat 2026 tarihli bilinen fiyatlar döndürülür ve uyarı loglanır.

---

## Kurulum

```bash
# 1. Repo klonla
git clone https://github.com/yourname/ekspertiz-scraper
cd ekspertiz-scraper

# 2. Virtual environment oluştur
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Bağımlılıkları yükle
pip install -r requirements.txt

# 4. Playwright tarayıcılarını indir (sadece ilk seferinde)
playwright install chromium

# 5. scrapers/__init__.py oluştur
touch scrapers/__init__.py
```

---

## Kullanım

```bash
# Tüm firmaları tara
python run_scraper.py

# Sadece belirli firma(lar)
python run_scraper.py --firm otorapor autoking

# DB'ye yazma, sadece ekrana bas
python run_scraper.py --dry-run

# JSON çıktı (API entegrasyonu için)
python run_scraper.py --json > prices.json

# Zamanlayıcıyı başlat (sürekli çalışır)
python scheduler.py
```

---

## Çıktı Örneği

```
══════════════════════════════════════════════════════════════
  EKSPERTİZ FİYATLARI — 06.05.2026 03:15

✓ Otorapor
   https://www.otorapor.com.tr
   • Kaporta / Boya              ₺4.900
   • Bronz Paket                 ₺5.500  | 120 nokta
   • Gold Paket                  ₺9.000  | 250 nokta
   • Full Paket                  ₺13.000 | 400 nokta

✓ Auto King
   • Eko Paket                   ₺5.200  | 100 nokta
   ...
══════════════════════════════════════════════════════════════
```

---

## Veritabanı Sorguları

SQLite DB: `ekspertiz_prices.db`

```sql
-- Şu anki en ucuz temel ekspertiz fiyatları
SELECT firm_name, package_name, price
FROM packages p
JOIN firms f ON f.firm_id = p.firm_id
WHERE package_name LIKE '%Temel%' OR package_name LIKE '%Kaporta%'
ORDER BY price ASC;

-- Fiyat değişim geçmişi
SELECT firm_name, package_name, price, scraped_at
FROM packages p
JOIN firms f ON f.firm_id = p.firm_id
WHERE p.firm_id = 'otorapor'
ORDER BY scraped_at DESC
LIMIT 20;
```

---

## Yeni Firma Ekleme

```python
# scrapers/yeni_firma_scraper.py
from .base_scraper import BaseScraper, FirmResult, PricePackage

class YeniFirmaScraper(BaseScraper):
    FIRM_ID   = "yeni_firma"
    FIRM_NAME = "Yeni Firma Ekspertiz"
    WEBSITE   = "https://www.yenifirma.com.tr"

    KNOWN_PACKAGES = [
        PricePackage("Temel Paket", 5000, 100, ["Özellik 1", "Özellik 2"]),
    ]

    async def scrape(self) -> FirmResult:
        # ... scraping mantığı
        return self._make_result(packages)
```

`run_scraper.py` dosyasına ekle:
```python
from scrapers.yeni_firma_scraper import YeniFirmaScraper
ALL_SCRAPERS.append(YeniFirmaScraper)
```

---

## Mimari

```
ekspertiz_scraper/
├── scrapers/
│   ├── __init__.py
│   ├── base_scraper.py        ← Ortak veri modelleri
│   ├── otorapor_scraper.py    ← Otorapor (Nuxt.js)
│   ├── autoking_scraper.py    ← Auto King
│   └── other_scrapers.py      ← Dynomoss, RS, Arabam
├── run_scraper.py             ← Orkestratör + CLI
├── scheduler.py               ← Otomatik zamanlayıcı
├── ekspertiz_prices.db        ← SQLite (gitignore'a ekle)
├── requirements.txt
└── README.md
```

---

## Önemli Notlar

**Bot Engeli:** Bazı siteler Cloudflare veya benzer koruma kullanır.
Bu durumda `playwright-stealth` kütüphanesini deneyin:
```bash
pip install playwright-stealth
```
```python
from playwright_stealth import stealth_async
await stealth_async(page)
```

**Yasal:** Scraping yalnızca kamu fiyat listelerini hedefler,
giriş gerektiren sayfalar veya kişisel veriler kesinlikle toplanmaz.
Firmaların `robots.txt` dosyaları kontrol edilmelidir.
