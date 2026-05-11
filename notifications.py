"""
Email bildirimleri - Gmail SMTP ile
.env dosyasinda GMAIL_USER ve GMAIL_PASS tanimlanmali
"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_PASS = os.environ.get("GMAIL_PASS", "")

def send_email(to_email, subject, html_body):
    if not GMAIL_USER or not GMAIL_PASS:
        print(f"[EMAIL SKIP] {to_email}: {subject}")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"EkspertizBul <{GMAIL_USER}>"
        msg["To"] = to_email
        msg.attach(MIMEText(html_body, "html", "utf-8"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(GMAIL_USER, GMAIL_PASS)
            s.sendmail(GMAIL_USER, to_email, msg.as_string())
        print(f"[EMAIL OK] {to_email}: {subject}")
        return True
    except Exception as e:
        print(f"[EMAIL FAIL] {e}")
        return False

def email_yeni_randevu_firma(firma_email, firma_unvan, user_adsoyad, tarih, saat, arac, paket):
    subject = f"Yeni Randevu Talebi - {user_adsoyad}"
    body = f"""
    <div style="font-family:Arial,sans-serif;max-width:500px;margin:0 auto">
      <div style="background:#1a0000;color:#fff;padding:20px;text-align:center;border-radius:10px 10px 0 0">
        <h2>EkspertizBul - Yeni Randevu</h2>
      </div>
      <div style="padding:20px;background:#fff;border:1px solid #eee">
        <p>Merhaba <b>{firma_unvan}</b>,</p>
        <p>Yeni bir randevu talebi aldınız:</p>
        <table style="width:100%;border-collapse:collapse;margin:16px 0">
          <tr><td style="padding:8px;background:#f5f5f5;font-weight:bold">Müşteri</td><td style="padding:8px">{user_adsoyad}</td></tr>
          <tr><td style="padding:8px;background:#f5f5f5;font-weight:bold">Tarih</td><td style="padding:8px">{tarih} - {saat}</td></tr>
          <tr><td style="padding:8px;background:#f5f5f5;font-weight:bold">Araç</td><td style="padding:8px">{arac}</td></tr>
          <tr><td style="padding:8px;background:#f5f5f5;font-weight:bold">Paket</td><td style="padding:8px">{paket or 'Belirtilmedi'}</td></tr>
        </table>
        <p>Randevuyu onaylamak veya reddetmek için <a href="https://ekspertiz-bul.onrender.com/firma/panel" style="color:#e53535">firma panelinize</a> giriş yapın.</p>
      </div>
      <div style="padding:12px;text-align:center;color:#888;font-size:12px">EkspertizBul | mcolakai@gmail.com</div>
    </div>
    """
    return send_email(firma_email, subject, body)

def email_randevu_guncelleme_kullanici(user_email, user_ad, firma_unvan, tarih, saat, durum):
    renk = "#28a745" if durum == "onaylandi" else "#dc3545"
    durum_tr = {"onaylandi": "Onaylandı", "reddedildi": "Reddedildi", "tamamlandi": "Tamamlandı"}.get(durum, durum)
    subject = f"Randevunuz {durum_tr} - {firma_unvan}"
    body = f"""
    <div style="font-family:Arial,sans-serif;max-width:500px;margin:0 auto">
      <div style="background:#1a0000;color:#fff;padding:20px;text-align:center;border-radius:10px 10px 0 0">
        <h2>EkspertizBul</h2>
      </div>
      <div style="padding:20px;background:#fff;border:1px solid #eee">
        <p>Merhaba <b>{user_ad}</b>,</p>
        <p><b>{firma_unvan}</b> firmasındaki randevunuz:</p>
        <div style="text-align:center;padding:16px;background:{renk};color:#fff;border-radius:8px;font-size:1.2rem;font-weight:bold;margin:16px 0">
          {durum_tr}
        </div>
        <p>Tarih: <b>{tarih} - {saat}</b></p>
        <p><a href="https://ekspertiz-bul.onrender.com/kullanici/panel" style="color:#e53535">Profilinizi görüntüleyin</a></p>
      </div>
    </div>
    """
    return send_email(user_email, subject, body)
