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
            listing_id, price, mileage_km, is_active, view_count, scraped_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """, (
            row.get("listing_id"),
            row.get("price"),
            row.get("mileage_km"),
            int(bool(row.get("is_active"))),
            row.get("view_count"),
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
            last_seen TEXT,
            inactive_at TEXT,
            last_checked_at TEXT
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS listing_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id TEXT,
            price INTEGER,
            mileage_km INTEGER,
            is_active INTEGER,
            scraped_at TEXT,
            view_count INTEGER
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
            posted_date, view_count, first_seen, last_seen, last_checked_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            view_count=excluded.view_count,
            last_checked_at=excluded.last_checked_at
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
            now,
        ))
        conn.commit()

def get_active_listings(limit: int | None = None) -> list[dict]:
    query = """
    SELECT
        listing_id,
        title,
        url,
        price,
        location,
        is_active,
        first_seen,
        last_seen,
        last_checked_at,
        inactive_at
    FROM listings
    WHERE is_active = 1
    ORDER BY last_checked_at ASC
    """

    params = []

    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)

    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()

    return [dict(row) for row in rows]


def mark_listing_checked(listing_id: str):
    now = datetime.now().isoformat()

    with get_connection() as conn:
        conn.execute("""
        UPDATE listings
        SET last_checked_at = ?
        WHERE listing_id = ?
        """, (now, listing_id))
        conn.commit()


def mark_listing_inactive(listing_id: str):
    now = datetime.now().isoformat()

    with get_connection() as conn:
        conn.execute("""
        UPDATE listings
        SET
            is_active = 0,
            inactive_at = ?,
            last_checked_at = ?
        WHERE listing_id = ?
        """, (now, now, listing_id))
        conn.commit()
