"""
EkspertizBul — Otomatik Zamanlayıcı
Her gece 03:00'te ve önemli değişikliklerde çalışır.

Kurulum:
    pip install apscheduler
    python scheduler.py

Ya da cron ile (pip apscheduler olmadan):
    0 3 * * * cd /path/to/ekspertiz_scraper && python run_scraper.py
"""
import asyncio
import logging
import smtplib
import sqlite3
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from run_scraper import run_all, DB_PATH, get_latest_prices, init_db

logger = logging.getLogger("scheduler")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


# ─── Fiyat değişiklik tespiti ───────────────────────────────
def detect_price_changes(conn: sqlite3.Connection, hours: int = 25) -> list[dict]:
    """Son X saatte fiyatı değişen paketleri bul"""
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
    rows = conn.execute("""
        SELECT
            p_new.firm_id,
            f.firm_name,
            p_new.package_name,
            p_old.price  AS old_price,
            p_new.price  AS new_price,
            p_new.scraped_at
        FROM packages p_new
        JOIN firms f ON f.firm_id = p_new.firm_id
        JOIN packages p_old ON (
            p_old.firm_id      = p_new.firm_id AND
            p_old.package_name = p_new.package_name AND
            p_old.scraped_at   < p_new.scraped_at
        )
        WHERE p_new.scraped_at >= ?
          AND p_new.price != p_old.price
          AND p_old.scraped_at = (
              SELECT MAX(p3.scraped_at) FROM packages p3
              WHERE p3.firm_id = p_old.firm_id
                AND p3.package_name = p_old.package_name
                AND p3.scraped_at < p_new.scraped_at
          )
        ORDER BY ABS(p_new.price - p_old.price) DESC
    """, (cutoff,)).fetchall()

    changes = []
    for row in rows:
        changes.append({
            "firm_id": row[0],
            "firm_name": row[1],
            "package_name": row[2],
            "old_price": row[3],
            "new_price": row[4],
            "change_pct": round(((row[4] - row[3]) / row[3]) * 100, 1) if row[3] else 0,
            "scraped_at": row[5],
        })
    return changes


# ─── Bildirim göndericisi ────────────────────────────────────
class Notifier:
    def __init__(self, config: dict):
        self.config = config

    def send_email(self, subject: str, body: str):
        """Fiyat değişikliklerini e-posta ile bildir"""
        if not self.config.get("email_enabled"):
            logger.info(f"[E-posta devre dışı] {subject}")
            return

        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = self.config["smtp_from"]
        msg["To"] = self.config["smtp_to"]

        try:
            with smtplib.SMTP_SSL(self.config["smtp_host"], self.config["smtp_port"]) as s:
                s.login(self.config["smtp_user"], self.config["smtp_pass"])
                s.send_message(msg)
            logger.info(f"📧 E-posta gönderildi: {subject}")
        except Exception as e:
            logger.error(f"E-posta hatası: {e}")

    def format_changes(self, changes: list[dict]) -> str:
        lines = [f"EkspertizBul — Fiyat Değişiklikleri ({datetime.now().strftime('%d.%m.%Y %H:%M')})\n"]
        for c in changes:
            arrow = "↑" if c["new_price"] > c["old_price"] else "↓"
            lines.append(
                f"{arrow} {c['firm_name']} — {c['package_name']}\n"
                f"   {c['old_price']:,.0f}₺  →  {c['new_price']:,.0f}₺  ({c['change_pct']:+.1f}%)\n"
            )
        return "\n".join(lines)


# ─── Zamanlı görevler ───────────────────────────────────────
NOTIFIER_CONFIG = {
    "email_enabled": False,   # True yapınca aktif olur
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 465,
    "smtp_user": "your@gmail.com",
    "smtp_pass": "app_password",
    "smtp_from": "ekspertiz@yourdomain.com",
    "smtp_to":   "admin@yourdomain.com",
}

notifier = Notifier(NOTIFIER_CONFIG)


async def nightly_scrape():
    """Her gece 03:00 — tam tarama"""
    logger.info("🌙 Gece taraması başlıyor...")
    results = await run_all()

    # Değişiklik kontrolü
    conn = sqlite3.connect(DB_PATH)
    changes = detect_price_changes(conn)
    conn.close()

    success = sum(1 for r in results if r.success)
    logger.info(f"✓ Tamamlandı: {success}/{len(results)} firma, {len(changes)} değişiklik")

    if changes:
        body = notifier.format_changes(changes)
        notifier.send_email(
            subject=f"[EkspertizBul] {len(changes)} Fiyat Değişikliği Tespit Edildi",
            body=body
        )
        logger.info(f"💰 Değişiklikler:\n{body}")


async def hourly_check():
    """Saatlik hızlı kontrol — sadece Otorapor (en büyük firma)"""
    logger.info("⏱ Saatlik kontrol: Otorapor...")
    await run_all(firm_ids=["otorapor"])


# ─── Scheduler başlatma ─────────────────────────────────────
def start():
    scheduler = AsyncIOScheduler(timezone="Europe/Istanbul")

    # Her gece 03:00 — tam tarama
    scheduler.add_job(
        nightly_scrape,
        CronTrigger(hour=3, minute=0),
        id="nightly_scrape",
        name="Gece Tam Tarama",
        max_instances=1,
        coalesce=True,
    )

    # Her 6 saatte bir — hızlı kontrol
    scheduler.add_job(
        hourly_check,
        CronTrigger(hour="*/6", minute=15),
        id="hourly_check",
        name="Saatlik Hızlı Kontrol",
        max_instances=1,
    )

    scheduler.start()
    logger.info("📅 Zamanlayıcı aktif:")
    logger.info("   → Her gece 03:00'te tam tarama")
    logger.info("   → Her 6 saatte Otorapor kontrolü")

    try:
        asyncio.get_event_loop().run_forever()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
        logger.info("Zamanlayıcı durduruldu.")


if __name__ == "__main__":
    # İlk çalıştırmada DB oluştur
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    conn.close()
    start()
