"""
Otorapor.com.tr Scraper
Site: https://www.otorapor.com.tr
Yapı: React/Next.js tabanlı (nuxt.otorapor.com.tr)
Fiyat sayfası: /fiyat-listesi veya siparis.otorapor.com.tr

Not: Nuxt.js render — Playwright ile JavaScript beklenecek.
"""
import re
import asyncio
from playwright.async_api import async_playwright, TimeoutError as PWTimeout
from .base_scraper import BaseScraper, FirmResult, PricePackage


class OtoraporScraper(BaseScraper):
    FIRM_ID = "otorapor"
    FIRM_NAME = "Otorapor"
    WEBSITE = "https://www.otorapor.com.tr"

    # Denenen URL'ler (önce denenir, başarısız olursa sıradaki)
    PRICE_URLS = [
        "https://www.otorapor.com.tr/fiyatlar",
        "https://www.otorapor.com.tr/ekspertiz-fiyatlari",
        "https://nuxt.otorapor.com.tr/fiyatlar",
        "https://siparis.otorapor.com.tr",   # sipariş sayfasında fiyat gösterebilir
    ]

    # Bilinen 2026 paket yapısı (fallback — site çekilemezse kullanılır)
    KNOWN_PACKAGES = [
        PricePackage("Kaporta / Boya", 4900, 80, ["Kaporta-boya kontrolü", "Değişen parça tespiti", "Boya mikron ölçümü"]),
        PricePackage("Bronz Paket", 5500, 120, ["Kaporta-boya", "Motor & mekanik temel kontrol", "Alt takım görsel"]),
        PricePackage("Gold Paket", 9000, 250, ["Bronz içeriği", "OBD taraması", "Elektronik sistem", "Alt takım lift"]),
        PricePackage("Full Paket", 13000, 400, ["Tüm sistemler", "Dyno testi", "TRAMER sorgusu", "Kompresyon testi"]),
    ]

    async def scrape(self) -> FirmResult:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
                locale="tr-TR",
            )
            page = await context.new_page()

            packages = []
            last_error = None

            for url in self.PRICE_URLS:
                try:
                    self.logger.info(f"Deneniyor: {url}")
                    await page.goto(url, wait_until="networkidle", timeout=20000)
                    await page.wait_for_timeout(2000)  # JS render bekle

                    packages = await self._parse_page(page)
                    if packages:
                        self.logger.info(f"✓ {len(packages)} paket bulundu: {url}")
                        break

                except PWTimeout:
                    last_error = f"Timeout: {url}"
                    self.logger.warning(last_error)
                except Exception as e:
                    last_error = str(e)
                    self.logger.warning(f"Hata {url}: {e}")

            await browser.close()

            # Canlı veri yoksa known_packages fallback
            if not packages:
                self.logger.warning("Canlı veri alınamadı, bilinen fiyatlar kullanılıyor (fallback)")
                return self._make_result(
                    self.KNOWN_PACKAGES,
                    error=f"Fallback kullanıldı. Son hata: {last_error}"
                )

            return self._make_result(packages)

    async def _parse_page(self, page) -> list[PricePackage]:
        """Sayfadan fiyat tablolarını ayıkla"""
        packages = []

        # Yöntem 1: Tablo satırları
        rows = await page.query_selector_all("table tr, .price-row, .paket-row, [class*='price'], [class*='paket']")
        for row in rows:
            text = (await row.inner_text()).strip()
            price = self._extract_price(text)
            if price and 1000 < price < 50000:
                name = self._extract_name(text)
                packages.append(PricePackage(name=name, price=price, points=None))

        # Yöntem 2: JSON-LD veya __NUXT_DATA__
        if not packages:
            content = await page.content()
            packages = self._parse_json_data(content)

        # Yöntem 3: Genel ₺ içeren metinleri tara
        if not packages:
            elements = await page.query_selector_all("*")
            for el in elements[:200]:
                try:
                    text = (await el.inner_text()).strip()
                    if "₺" in text or "TL" in text:
                        price = self._extract_price(text)
                        if price and 1000 < price < 50000:
                            name = self._extract_name(text) or "Ekspertiz Paketi"
                            packages.append(PricePackage(name=name, price=price, points=None))
                except:
                    pass
            # Tekrarları temizle
            seen = set()
            unique = []
            for p in packages:
                if p.price not in seen:
                    seen.add(p.price)
                    unique.append(p)
            packages = unique

        return packages

    def _extract_price(self, text: str) -> float | None:
        """Metinden TL fiyatını ayıkla"""
        # ₺9.000 / 9.000 TL / 9000₺ / 9,000 TL gibi formatlar
        patterns = [
            r'[\₺\s](\d{1,2}[.,]\d{3})',   # ₺9.000
            r'(\d{1,2}[.,]\d{3})\s*[₺TL]', # 9.000₺
            r'(\d{4,5})\s*[₺TL]',           # 9000₺
            r'[₺\s](\d{4,5})',              # ₺9000
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                raw = m.group(1).replace('.', '').replace(',', '')
                try:
                    val = float(raw)
                    if 500 < val < 100000:
                        return val
                except:
                    pass
        return None

    def _extract_name(self, text: str) -> str:
        """Satırdan paket adını tahmin et"""
        keywords = ["kaporta", "bronz", "silver", "gold", "full", "plus", "premium",
                    "standart", "basic", "eko", "temel", "paket", "ekspertiz"]
        lines = text.split('\n')
        for line in lines:
            low = line.lower()
            if any(k in low for k in keywords) and len(line) < 60:
                return line.strip()
        return lines[0][:50] if lines else "Paket"

    def _parse_json_data(self, html: str) -> list[PricePackage]:
        """__NUXT_DATA__ veya JSON-LD içinden fiyat çek"""
        import json
        packages = []
        # __NUXT_DATA__ bloğunu ara
        m = re.search(r'__NUXT_DATA__\s*=\s*(\[.*?\])\s*<', html, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(1))
                prices_found = [x for x in data if isinstance(x, (int, float)) and 1000 < x < 50000]
                for p in prices_found:
                    packages.append(PricePackage(name="Paket", price=float(p), points=None))
            except:
                pass
        return packages
