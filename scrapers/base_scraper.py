"""
Base scraper class - tüm firma scraperları bunu miras alır.
"""
import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class PricePackage:
    """Tek bir ekspertiz paketi"""
    name: str               # Paket adı (ör: "Gold Paket")
    price: Optional[float]  # Fiyat (TL)
    points: Optional[int]   # Kontrol nokta sayısı
    features: list[str] = field(default_factory=list)
    is_discounted: bool = False
    original_price: Optional[float] = None


@dataclass
class FirmResult:
    """Bir firmanın scrape sonucu"""
    firm_id: str
    firm_name: str
    website: str
    scraped_at: datetime
    packages: list[PricePackage]
    success: bool
    error: Optional[str] = None
    city: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None


class BaseScraper(ABC):
    FIRM_ID: str = ""
    FIRM_NAME: str = ""
    WEBSITE: str = ""

    def __init__(self):
        self.logger = logging.getLogger(f"scraper.{self.FIRM_ID}")

    @abstractmethod
    async def scrape(self) -> FirmResult:
        """Fiyatları çek ve FirmResult döndür"""
        pass

    def _make_result(self, packages: list[PricePackage], **kwargs) -> FirmResult:
        return FirmResult(
            firm_id=self.FIRM_ID,
            firm_name=self.FIRM_NAME,
            website=self.WEBSITE,
            scraped_at=datetime.now(),
            packages=packages,
            success=True,
            **kwargs
        )

    def _make_error(self, error: str) -> FirmResult:
        self.logger.error(f"{self.FIRM_NAME} scrape hatası: {error}")
        return FirmResult(
            firm_id=self.FIRM_ID,
            firm_name=self.FIRM_NAME,
            website=self.WEBSITE,
            scraped_at=datetime.now(),
            packages=[],
            success=False,
            error=error
        )
