import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone

from config.paths import DB_PATH


def get_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def _timestamp(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError("Database timestamps must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat()


def insert_listing_history(row: dict):
    observed_at = row.get("scraped_at") or _timestamp()

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
            observed_at,
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
    now = row.get("scraped_at") or _timestamp()

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
            inactive_at=NULL,
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


def get_known_listings() -> list[dict]:
    query = """
    SELECT
        listings.*,
        detail_history.last_detail_at
    FROM listings
    LEFT JOIN (
        SELECT listing_id, MAX(scraped_at) AS last_detail_at
        FROM listing_history
        GROUP BY listing_id
    ) AS detail_history
        ON detail_history.listing_id = listings.listing_id
    """

    with get_connection() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query).fetchall()

    return [dict(row) for row in rows]


def mark_listings_seen(
    listing_ids: Iterable[str],
    *,
    seen_at: datetime | None = None,
) -> int:
    unique_ids = sorted(set(listing_ids))
    if not unique_ids:
        return 0

    timestamp = _timestamp(seen_at)
    with get_connection() as conn:
        before = conn.total_changes
        conn.executemany(
            """
            UPDATE listings
            SET last_seen = ?, is_active = 1, inactive_at = NULL
            WHERE listing_id = ?
            """,
            [(timestamp, listing_id) for listing_id in unique_ids],
        )
        updated = conn.total_changes - before
        conn.commit()
    return updated

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


def mark_listing_checked(listing_id: str, *, checked_at: datetime | None = None):
    now = _timestamp(checked_at)

    with get_connection() as conn:
        conn.execute("""
        UPDATE listings
        SET last_checked_at = ?
        WHERE listing_id = ?
        """, (now, listing_id))
        conn.commit()


def mark_listing_inactive(listing_id: str, *, checked_at: datetime | None = None):
    now = _timestamp(checked_at)

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
