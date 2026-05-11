"""
Veritabani modelleri - app.db
"""
import sqlite3
import hashlib
import secrets
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "app.db"

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ad_soyad TEXT NOT NULL,
            email TEXT UNIQUE,
            telefon TEXT,
            sifre_hash TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS firm_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            unvan TEXT NOT NULL,
            yetkili_ad TEXT NOT NULL,
            yetkili_gorev TEXT NOT NULL,
            adres TEXT NOT NULL,
            il TEXT DEFAULT '',
            ilce TEXT DEFAULT '',
            lat REAL DEFAULT 0,
            lng REAL DEFAULT 0,
            telefon TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            sifre_hash TEXT NOT NULL,
            onay INTEGER DEFAULT 0,
            google_firm_id TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            active INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER,
            firm_id INTEGER,
            role TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            expires_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            firm_id INTEGER NOT NULL,
            tarih TEXT NOT NULL,
            saat TEXT NOT NULL,
            arac_marka TEXT,
            arac_model TEXT,
            arac_yil TEXT,
            paket TEXT,
            notlar TEXT,
            durum TEXT DEFAULT 'beklemede',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (firm_id) REFERENCES firm_accounts(id)
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            firm_id INTEGER,
            user_id INTEGER,
            tip TEXT NOT NULL,
            mesaj TEXT NOT NULL,
            okundu INTEGER DEFAULT 0,
            appointment_id INTEGER,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            appointment_id INTEGER NOT NULL,
            gonderen_tip TEXT NOT NULL,
            gonderen_id INTEGER NOT NULL,
            mesaj TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            firm_id INTEGER NOT NULL,
            appointment_id INTEGER NOT NULL UNIQUE,
            puan INTEGER NOT NULL CHECK(puan BETWEEN 1 AND 5),
            yorum TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS firm_packages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            firm_id INTEGER NOT NULL,
            paket_adi TEXT NOT NULL,
            fiyat INTEGER NOT NULL,
            icerik TEXT,
            aktif INTEGER DEFAULT 1,
            FOREIGN KEY (firm_id) REFERENCES firm_accounts(id)
        );
    """)
    conn.commit()
    conn.close()
    print("DB hazir:", DB_PATH)

def hash_password(sifre):
    salt = secrets.token_hex(16)
    h = hashlib.sha256((salt + sifre).encode()).hexdigest()
    return f"{salt}:{h}"

def check_password(sifre, sifre_hash):
    try:
        salt, h = sifre_hash.split(":")
        return hashlib.sha256((salt + sifre).encode()).hexdigest() == h
    except:
        return False

def create_session(user_id=None, firm_id=None, role="user"):
    token = secrets.token_urlsafe(32)
    from datetime import datetime, timedelta
    expires = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    conn.execute(
        "INSERT INTO sessions (token, user_id, firm_id, role, expires_at) VALUES (?,?,?,?,?)",
        (token, user_id, firm_id, role, expires)
    )
    conn.commit()
    conn.close()
    return token

def get_session(token):
    if not token:
        return None
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM sessions WHERE token=? AND expires_at > datetime('now')",
        (token,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None

def delete_session(token):
    conn = get_conn()
    conn.execute("DELETE FROM sessions WHERE token=?", (token,))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
