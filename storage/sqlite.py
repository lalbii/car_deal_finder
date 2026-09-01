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
        conn.execute("""
        CREATE TABLE IF NOT EXISTS scrape_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            search_name TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            succeeded INTEGER NOT NULL,
            listings_discovered INTEGER NOT NULL DEFAULT 0,
            new_listings INTEGER NOT NULL DEFAULT 0,
            detail_requests INTEGER NOT NULL DEFAULT 0,
            details_succeeded INTEGER NOT NULL DEFAULT 0,
            retry_requests INTEGER NOT NULL DEFAULT 0,
            blocking_failures INTEGER NOT NULL DEFAULT 0,
            duration_seconds REAL NOT NULL DEFAULT 0,
            stopped_reason TEXT,
            error_message TEXT
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS opportunity_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            asking_price REAL NOT NULL,
            estimated_market_price REAL NOT NULL,
            market_gap_eur REAL NOT NULL,
            discount_percent REAL NOT NULL,
            opportunity_score REAL NOT NULL,
            score_version TEXT NOT NULL,
            opportunity_status TEXT NOT NULL,
            valuation_status TEXT NOT NULL,
            valuation_confidence TEXT NOT NULL,
            market_value_status TEXT NOT NULL,
            comparable_count INTEGER NOT NULL,
            strong_comparable_count INTEGER NOT NULL,
            discount_component REAL NOT NULL,
            margin_component REAL NOT NULL,
            base_opportunity REAL NOT NULL,
            confidence_multiplier REAL NOT NULL,
            risk_multiplier REAL NOT NULL,
            valuation_vocabulary_version INTEGER NOT NULL,
            vehicle_semantics_version INTEGER NOT NULL,
            comparable_version TEXT NOT NULL,
            UNIQUE(listing_id, observed_at)
        )
        """)
        conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_opportunity_snapshots_listing_observed
        ON opportunity_snapshots(listing_id, observed_at DESC)
        """)
        legacy_runs = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = ? AND name = ?",
            ("table", "collector_runs"),
        ).fetchone()
        if legacy_runs:
            conn.execute("INSERT OR IGNORE INTO scrape_runs SELECT * FROM collector_runs")
        conn.commit()


_OPPORTUNITY_SNAPSHOT_COLUMNS = (
    "listing_id", "observed_at", "asking_price", "estimated_market_price",
    "market_gap_eur", "discount_percent", "opportunity_score", "score_version",
    "opportunity_status", "valuation_status", "valuation_confidence",
    "market_value_status", "comparable_count", "strong_comparable_count",
    "discount_component", "margin_component", "base_opportunity",
    "confidence_multiplier", "risk_multiplier", "valuation_vocabulary_version",
    "vehicle_semantics_version", "comparable_version",
)


def insert_opportunity_snapshots(rows: Iterable[dict]) -> int:
    """Insert derived analytics idempotently for one or more observation times."""
    records = list(rows)
    if not records:
        return 0
    placeholders = ", ".join("?" for _ in _OPPORTUNITY_SNAPSHOT_COLUMNS)
    columns = ", ".join(_OPPORTUNITY_SNAPSHOT_COLUMNS)
    values = [
        tuple(record.get(column) for column in _OPPORTUNITY_SNAPSHOT_COLUMNS)
        for record in records
    ]
    with get_connection() as conn:
        before = conn.total_changes
        conn.executemany(
            f"INSERT OR IGNORE INTO opportunity_snapshots ({columns}) "
            f"VALUES ({placeholders})",
            values,
        )
        inserted = conn.total_changes - before
        conn.commit()
    return inserted


def record_collector_run(*, search_name: str, succeeded: bool, listings_discovered: int = 0,
                         new_listings: int = 0, detail_requests: int = 0, details_succeeded: int = 0,
                         retry_requests: int = 0, blocking_failures: int = 0, duration_seconds: float = 0,
                         stopped_reason: str | None = None, error_message: str | None = None,
                         finished_at: datetime | None = None) -> None:
    init_db()
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO scrape_runs (search_name, finished_at, succeeded, listings_discovered,
                new_listings, detail_requests, details_succeeded, retry_requests, blocking_failures,
                duration_seconds, stopped_reason, error_message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (search_name, _timestamp(finished_at), int(succeeded), listings_discovered, new_listings,
              detail_requests, details_succeeded, retry_requests, blocking_failures, duration_seconds,
              stopped_reason, error_message))
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
