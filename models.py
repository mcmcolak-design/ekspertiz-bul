"""
Veritabani modelleri - PostgreSQL
"""
import hashlib
import secrets
import os
from datetime import datetime, timedelta

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://ekspertiz_db_user:MXGAj4t9R0JMJxeGdCVZl295KMGw1nJK@dpg-d80jl5jrjlhs73ackl7g-a/ekspertiz_db"
)

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

import psycopg2
from psycopg2.extras import RealDictCursor

def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            ad_soyad TEXT NOT NULL,
            email TEXT UNIQUE,
            telefon TEXT,
            sifre_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            active INTEGER DEFAULT 1
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS firm_accounts (
            id SERIAL PRIMARY KEY,
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
            onay INTEGER DEFAULT 1,
            google_firm_id TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            active INTEGER DEFAULT 1
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER,
            firm_id INTEGER,
            role TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW(),
            expires_at TIMESTAMP NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS appointments (
            id SERIAL PRIMARY KEY,
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
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id SERIAL PRIMARY KEY,
            firm_id INTEGER,
            user_id INTEGER,
            tip TEXT NOT NULL,
            mesaj TEXT NOT NULL,
            okundu INTEGER DEFAULT 0,
            appointment_id INTEGER,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id SERIAL PRIMARY KEY,
            appointment_id INTEGER NOT NULL,
            gonderen_tip TEXT NOT NULL,
            gonderen_id INTEGER NOT NULL,
            mesaj TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS reviews (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            firm_id INTEGER NOT NULL,
            appointment_id INTEGER NOT NULL UNIQUE,
            yorum TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS review_criteria (
            id SERIAL PRIMARY KEY,
            review_id INTEGER NOT NULL,
            kriter_adi TEXT NOT NULL,
            puan INTEGER NOT NULL CHECK(puan BETWEEN 1 AND 5),
            degistirilebilir BOOLEAN DEFAULT FALSE,
            degistirildi BOOLEAN DEFAULT FALSE,
            updated_at TIMESTAMP DEFAULT NOW(),
            FOREIGN KEY (review_id) REFERENCES reviews(id)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS review_criteria_config (
            id SERIAL PRIMARY KEY,
            kriter_adi TEXT NOT NULL UNIQUE,
            degistirilebilir BOOLEAN DEFAULT FALSE,
            aktif BOOLEAN DEFAULT TRUE,
            sira INTEGER DEFAULT 0
        )
    """)
    # Varsayilan kriterler
    cur.execute("""
        INSERT INTO review_criteria_config (kriter_adi, degistirilebilir, sira)
        VALUES
            ('Firma Ilgisi', FALSE, 1),
            ('Islem Suresi', FALSE, 2),
            ('Islemlerin Dogrulugu', TRUE, 3)
        ON CONFLICT (kriter_adi) DO NOTHING
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS firm_packages (
            id SERIAL PRIMARY KEY,
            firm_id INTEGER NOT NULL,
            paket_adi TEXT NOT NULL,
            fiyat INTEGER NOT NULL,
            icerik TEXT,
            aktif INTEGER DEFAULT 1
        )
    """)
    conn.commit()
    cur.close()
    conn.close()
    print("PostgreSQL DB hazir")

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
    expires = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO sessions (token, user_id, firm_id, role, expires_at) VALUES (%s,%s,%s,%s,%s)",
        (token, user_id, firm_id, role, expires)
    )
    conn.commit()
    cur.close()
    conn.close()
    return token

def get_session(token):
    if not token:
        return None
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM sessions WHERE token=%s AND expires_at > NOW()",
        (token,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    return dict(row) if row else None

def delete_session(token):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM sessions WHERE token=%s", (token,))
    conn.commit()
    cur.close()
    conn.close()
