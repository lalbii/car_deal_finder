import sqlite3
from datetime import datetime
from pathlib import Path


DB_PATH = Path("data/listings.db")


def get_connection():
    DB_PATH.parent.mkdir(exist_ok=True)
    return sqlite3.connect(DB_PATH)

def insert_listing_history(row: dict):
    now = datetime.now().isoformat()

    with get_connection() as conn:
        conn.execute("""
        INSERT INTO listing_history (
            listing_id, price, mileage_km, is_active, scraped_at
        )
        VALUES (?, ?, ?, ?, ?)
        """, (
            row.get("listing_id"),
            row.get("price"),
            row.get("mileage_km"),
            int(bool(row.get("is_active"))),
            now,
        ))
        conn.commit()


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
            posted_date TEXT,
            view_count INTEGER,
            first_seen TEXT,
            last_seen TEXT
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS listing_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id TEXT,
            price INTEGER,
            mileage_km INTEGER,
            is_active INTEGER,
            scraped_at TEXT
        )
        """)
        conn.commit()



def upsert_listing(row: dict):
    now = datetime.now().isoformat()

    with get_connection() as conn:
        conn.execute("""
        INSERT INTO listings (
            listing_id, title, price, mileage_km, first_registration,
            fuel, transmission, location, url, is_active,
            posted_date, view_count, first_seen, last_seen
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            last_seen=excluded.last_seen,
            posted_date=excluded.posted_date,
            view_count=excluded.view_count
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
            row.get("posted_date"),
            row.get("view_count"),
            now,
            now,
        ))
        conn.commit()
