"""
Dynomoss Oto Ekspertiz Scraper
Site: https://dynomoss.com.tr
"""
import re
import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from .base_scraper import BaseScraper, FirmResult, PricePackage
from .autoking_scraper import AutoKingScraper  # parse yardımcılarını paylaş


class DynomossScraper(BaseScraper):
    FIRM_ID = "dynomoss"
    FIRM_NAME = "Dynomoss Oto Ekspertiz"
    WEBSITE = "https://dynomoss.com.tr"

    PRICE_URLS = [
        "https://dynomoss.com.tr/fiyat-listesi",
        "https://dynomoss.com.tr/fiyatlar",
        "https://dynomoss.com.tr/hizmetlerimiz",
        "https://dynomoss.com.tr",
    ]

    KNOWN_PACKAGES = [
        PricePackage("Motor & Kaporta Ekspertiz", 3000, 80, ["Özel açılış fiyatı", "Motor kontrolü", "Kaporta tarama"]),
        PricePackage("Standart Ekspertiz", 5500, 150, ["Motor & mekanik", "Kaporta-boya", "OBD tarama"]),
        PricePackage("Full Ekspertiz", 8500, 280, ["Tüm sistemler", "Lift mekanik", "Elektronik tarama"]),
    ]

    async def scrape(self) -> FirmResult:
        helper = AutoKingScraper()
        packages = await helper._try_httpx.__func__(self)  # type: ignore
        if not packages:
            packages = await helper._try_playwright.__func__(self)  # type: ignore
        if not packages:
            return self._make_result(self.KNOWN_PACKAGES, error="Fallback")
        return self._make_result(packages)

    # Parsing yöntemlerini AutoKingScraper'dan miras almak yerine
    # bağımsız çalışsın diye kopyalayabiliriz ya da composition kullanırız.
    # Bu örnekte composition:
    async def _try_httpx(self):
        headers = {"User-Agent": "Mozilla/5.0 Chrome/124", "Accept-Language": "tr-TR"}
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            for url in self.PRICE_URLS:
                try:
                    r = await client.get(url, headers=headers)
                    if r.status_code == 200:
                        packages = self._parse_html(r.text)
                        if packages:
                            return packages
                except:
                    pass
        return []

    async def _try_playwright(self):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            page = await (await browser.new_context(locale="tr-TR")).new_page()
            packages = []
            for url in self.PRICE_URLS:
                try:
                    await page.goto(url, wait_until="networkidle", timeout=18000)
                    await page.wait_for_timeout(1500)
                    packages = self._parse_html(await page.content())
                    if packages:
                        break
                except:
                    pass
            await browser.close()
            return packages

    def _parse_html(self, html: str) -> list[PricePackage]:
        soup = BeautifulSoup(html, "html.parser")
        packages = []
        seen = set()
        for tag in soup.find_all(string=re.compile(r'\d{3,5}')):
            text = str(tag)
            for pat in [r'(\d{1,2}[.,]\d{3})\s*[₺₺]', r'[₺₺]\s*(\d{1,2}[.,]\d{3})', r'(\d{4,5})\s*TL']:
                m = re.search(pat, text)
                if m:
                    raw = m.group(1).replace('.','').replace(',','')
                    try:
                        val = float(raw)
                        if 500 < val < 50000 and val not in seen:
                            seen.add(val)
                            packages.append(PricePackage(name=text[:50].strip(), price=val, points=None))
                    except:
                        pass
        return packages[:8]


# ─────────────────────────────────────────────────────────────
class RSEkspertizScraper(BaseScraper):
    """
    RS Oto Ekspertiz
    Site: https://rsotoekspertiz.com
    MR teknolojisi kullanan zincir firma
    """
    FIRM_ID = "rs_ekspertiz"
    FIRM_NAME = "RS Oto Ekspertiz"
    WEBSITE = "https://rsotoekspertiz.com"

    PRICE_URLS = [
        "https://rsotoekspertiz.com/fiyat-listesi",
        "https://rsotoekspertiz.com/ekspertiz-paketleri",
        "https://rsotoekspertiz.com/hizmetler",
        "https://rsotoekspertiz.com",
    ]

    KNOWN_PACKAGES = [
        PricePackage("Temel Paket", 4500, 100, ["Kaporta-boya", "Görsel mekanik", "TRAMER sorgu"]),
        PricePackage("Standart Paket", 7000, 200, ["OBD tarama", "Lift mekanik", "Elektronik"]),
        PricePackage("MR Paketi", 11000, 350, ["MR teknolojisi", "Termal analiz", "Full sistem"]),
        PricePackage("Premium MR", 15000, 500, ["En kapsamlı", "3D analiz", "Tüm sistemler"]),
    ]

    async def scrape(self) -> FirmResult:
        packages = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/124",
                locale="tr-TR"
            )
            page = await ctx.new_page()
            for url in self.PRICE_URLS:
                try:
                    await page.goto(url, wait_until="networkidle", timeout=18000)
                    await page.wait_for_timeout(2000)
                    html = await page.content()
                    soup = BeautifulSoup(html, "html.parser")

                    # RS'in kart yapısını hedef al
                    cards = soup.select(".paket-card, .price-box, [class*='paket'], [class*='price']")
                    for card in cards:
                        text = card.get_text(separator="\n", strip=True)
                        price = self._extract_price(text)
                        if price:
                            packages.append(PricePackage(
                                name=self._extract_name(text),
                                price=price,
                                points=self._extract_points(text),
                                features=self._extract_features(card)
                            ))

                    if packages:
                        break
                except Exception as e:
                    self.logger.debug(f"RS hata {url}: {e}")

            await browser.close()

        if not packages:
            return self._make_result(self.KNOWN_PACKAGES, error="Fallback")
        return self._make_result(packages)

    def _extract_price(self, text):
        for pat in [r'(\d{1,2}[.,]\d{3})\s*[₺]', r'[₺]\s*(\d{1,2}[.,]\d{3})', r'(\d{4,5})\s*TL']:
            m = re.search(pat, text)
            if m:
                try:
                    val = float(m.group(1).replace('.','').replace(',',''))
                    if 500 < val < 50000:
                        return val
                except:
                    pass
        return None

    def _extract_name(self, text):
        keywords = ["temel","standart","premium","mr","paket","ekspertiz","full","plus"]
        for line in text.split('\n'):
            if any(k in line.lower() for k in keywords) and len(line) < 80:
                return line.strip()
        return "Paket"

    def _extract_points(self, text):
        m = re.search(r'(\d{2,3})\s*nokta', text, re.I)
        return int(m.group(1)) if m else None

    def _extract_features(self, tag) -> list[str]:
        features = []
        for li in tag.find_all("li"):
            t = li.get_text(strip=True)
            if t and len(t) < 100:
                features.append(t)
        return features[:8]


# ─────────────────────────────────────────────────────────────
class ArabamEkspertizScraper(BaseScraper):
    """
    Arabam.com Oto Ekspertiz
    Site: https://www.arabam.com/oto-ekspertiz
    React SPA — Playwright zorunlu
    """
    FIRM_ID = "arabam_ekspertiz"
    FIRM_NAME = "Arabam.com Ekspertiz"
    WEBSITE = "https://www.arabam.com/oto-ekspertiz"

    KNOWN_PACKAGES = [
        PricePackage("Temel Ekspertiz", 4990, 120, ["Online indirimli fiyat", "Kaporta-boya", "Temel mekanik"]),
        PricePackage("Kapsamlı Ekspertiz", 7990, 250, ["Online indirimli", "OBD tarama", "Tüm sistemler"]),
        PricePackage("Full Ekspertiz", 12990, 400, ["Online indirimli", "Dyno", "TRAMER", "TSE belgeli"]),
    ]

    async def scrape(self) -> FirmResult:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            ctx = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124",
                locale="tr-TR"
            )
            page = await ctx.new_page()

            packages = []
            try:
                await page.goto(self.WEBSITE, wait_until="networkidle", timeout=25000)
                await page.wait_for_timeout(3000)  # React render bekle

                # arabam.com React SPA — veriyi çekmeye çalış
                # Fiyat içeren elementleri ara
                price_elements = await page.query_selector_all(
                    "[class*='price'], [class*='fiyat'], [class*='paket'], .pricing"
                )
                seen = set()
                for el in price_elements:
                    text = await el.inner_text()
                    price = self._find_price(text)
                    if price and price not in seen:
                        seen.add(price)
                        packages.append(PricePackage(
                            name=self._find_name(text) or "Arabam.com Paketi",
                            price=price,
                            points=None,
                            is_discounted=("indirim" in text.lower() or "%" in text)
                        ))

            except Exception as e:
                self.logger.warning(f"Arabam.com hata: {e}")
            finally:
                await browser.close()

        if not packages:
            return self._make_result(self.KNOWN_PACKAGES, error="Fallback")
        return self._make_result(packages)

    def _find_price(self, text):
        for pat in [r'(\d{1,2}[.,]\d{3})\s*[₺]', r'[₺]\s*(\d{1,2}[.,]\d{3})', r'(\d{4,5})\s*TL']:
            m = re.search(pat, text)
            if m:
                try:
                    val = float(m.group(1).replace('.','').replace(',',''))
                    if 1000 < val < 50000:
                        return val
                except:
                    pass
        return None

    def _find_name(self, text):
        for line in text.split('\n'):
            if any(k in line.lower() for k in ["ekspertiz","paket","kontrol","temel","full"]) and len(line) < 80:
                return line.strip()
        return None
