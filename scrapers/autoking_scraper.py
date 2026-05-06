"""
Auto King Ekspertiz Scraper
Site: https://www.autoking.com.tr
Yapı: Statik HTML — BeautifulSoup yeterli, Playwright fallback
Fiyat sayfası: /fiyat-listesi
"""
import re
import asyncio
import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from .base_scraper import BaseScraper, FirmResult, PricePackage


class AutoKingScraper(BaseScraper):
    FIRM_ID = "autoking"
    FIRM_NAME = "Auto King"
    WEBSITE = "https://www.autoking.com.tr"

    PRICE_URLS = [
        "https://www.autoking.com.tr/fiyat-listesi",
        "https://www.autoking.com.tr/ekspertiz-fiyatlari",
        "https://www.autoking.com.tr/hizmetler",
        "https://www.autoking.com.tr",
    ]

    KNOWN_PACKAGES = [
        PricePackage("Eko Paket", 5200, 100, ["Kaporta-boya", "Motor görsel kontrol", "Alt aksam (lift)"]),
        PricePackage("Mini Paket", 6000, 150, ["Eko içeriği", "Lift alt mekanik", "Ön takım & yürür aksam"]),
        PricePackage("Standart Paket", 7500, 220, ["Mini içeriği", "OBD taraması", "Test sürüşü"]),
        PricePackage("King Plus Paket", 12000, 641, ["Tüm sistemler", "647 nokta kontrol", "Termal kamera"]),
    ]

    async def scrape(self) -> FirmResult:
        # Önce hızlı httpx dene (JS gerektirmeyen sayfalar için)
        packages = await self._try_httpx()
        if packages:
            return self._make_result(packages)

        # JS gerektiriyorsa Playwright
        packages = await self._try_playwright()
        if packages:
            return self._make_result(packages)

        # Fallback
        self.logger.warning("Auto King: fallback fiyatlar kullanılıyor")
        return self._make_result(self.KNOWN_PACKAGES, error="Fallback")

    async def _try_httpx(self) -> list[PricePackage]:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124",
            "Accept-Language": "tr-TR,tr;q=0.9",
        }
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            for url in self.PRICE_URLS:
                try:
                    r = await client.get(url, headers=headers)
                    if r.status_code == 200:
                        packages = self._parse_html(r.text, url)
                        if packages:
                            self.logger.info(f"httpx ✓ {url}")
                            return packages
                except Exception as e:
                    self.logger.debug(f"httpx hata {url}: {e}")
        return []

    async def _try_playwright(self) -> list[PricePackage]:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124",
                locale="tr-TR"
            )
            page = await context.new_page()
            packages = []
            for url in self.PRICE_URLS:
                try:
                    await page.goto(url, wait_until="networkidle", timeout=18000)
                    await page.wait_for_timeout(1500)
                    html = await page.content()
                    packages = self._parse_html(html, url)
                    if packages:
                        break
                except Exception as e:
                    self.logger.debug(f"PW hata {url}: {e}")
            await browser.close()
            return packages

    def _parse_html(self, html: str, source_url: str) -> list[PricePackage]:
        soup = BeautifulSoup(html, "html.parser")
        packages = []

        # Tablo tabanlı fiyat listesi
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            for row in rows:
                cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
                if len(cells) >= 2:
                    name_cell = cells[0]
                    for cell in cells[1:]:
                        price = self._parse_price(cell)
                        if price:
                            packages.append(PricePackage(
                                name=name_cell[:60],
                                price=price,
                                points=self._parse_points(name_cell + " " + cell)
                            ))

        # Kart / div tabanlı
        if not packages:
            price_containers = soup.select(
                ".price-card, .paket, .fiyat, [class*='price'], [class*='paket'], [class*='fiyat']"
            )
            for container in price_containers:
                text = container.get_text(separator="\n", strip=True)
                price = self._parse_price(text)
                name = self._extract_name(text)
                if price and name:
                    packages.append(PricePackage(name=name, price=price, points=self._parse_points(text)))

        # Genel metin tarama fallback
        if not packages:
            seen = set()
            for tag in soup.find_all(text=re.compile(r'[₺].*\d{3}|\d{3}.*[₺TL]')):
                text = str(tag)
                price = self._parse_price(text)
                if price and price not in seen and 500 < price < 50000:
                    seen.add(price)
                    packages.append(PricePackage(
                        name=self._extract_name(text) or "Ekspertiz Paketi",
                        price=price,
                        points=None
                    ))

        return packages[:10]  # Makul limit

    def _parse_price(self, text: str) -> float | None:
        for pat in [
            r'(\d{1,2}[.,]\d{3})\s*[₺]',
            r'[₺]\s*(\d{1,2}[.,]\d{3})',
            r'(\d{4,5})\s*(?:TL|₺)',
            r'(?:TL|₺)\s*(\d{4,5})',
        ]:
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

    def _parse_points(self, text: str) -> int | None:
        m = re.search(r'(\d{2,3})\s*nokta', text, re.IGNORECASE)
        return int(m.group(1)) if m else None

    def _extract_name(self, text: str) -> str:
        keywords = ["eko", "mini", "standart", "king", "plus", "premium",
                    "gold", "silver", "bronz", "full", "kaporta", "paket"]
        for line in text.split('\n'):
            low = line.lower()
            if any(k in low for k in keywords) and 3 < len(line) < 80:
                return line.strip()
        return text.split('\n')[0][:50] if text else "Paket"
