import sqlite3
from datetime import datetime
from pathlib import Path


DB_PATH = Path("data/listings.db")


def get_connection():
    DB_PATH.parent.mkdir(exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db():
    with get_connection() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS listings (
            listing_id TEXT PRIMARY KEY,
            title TEXT,
            price INTEGER,
            mileage_km INTEGER,
            first_registration TEXT,
            fuel TEXT,
            transmission TEXT,
            location TEXT,
            url TEXT,
            is_active INTEGER,
            first_seen TEXT,
            last_seen TEXT
        )
        """)
        conn.commit()


def upsert_listing(row: dict):
    now = datetime.utcnow().isoformat()

    with get_connection() as conn:
        conn.execute("""
        INSERT INTO listings (
            listing_id, title, price, mileage_km, first_registration,
            fuel, transmission, location, url, is_active,
            first_seen, last_seen
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(listing_id) DO UPDATE SET
            title=excluded.title,
            price=excluded.price,
            mileage_km=excluded.mileage_km,
            first_registration=excluded.first_registration,
            fuel=excluded.fuel,
            transmission=excluded.transmission,
            location=excluded.location,
            url=excluded.url,
            is_active=excluded.is_active,
            last_seen=excluded.last_seen
        """, (
            row.get("listing_id"),
            row.get("title"),
            row.get("price"),
            row.get("mileage_km"),
            row.get("first_registration"),
            row.get("fuel"),
            row.get("transmission"),
            row.get("location"),
            row.get("url"),
            int(bool(row.get("is_active"))),
            now,
            now,
        ))
        conn.commit()