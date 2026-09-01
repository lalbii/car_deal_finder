from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from time import perf_counter

import pandas as pd

from analytics.opportunity_snapshots import build_opportunity_snapshot_records
from storage.sqlite import get_known_listings, insert_opportunity_snapshots


@dataclass(frozen=True)
class SnapshotRunResult:
    calculated: int
    inserted: int
    calculation_seconds: float
    write_seconds: float


def calculate_and_persist_opportunity_snapshots(
    observed_at: datetime,
) -> SnapshotRunResult:
    """Build canonical active snapshots once and persist them as one transaction."""
    calculation_started = perf_counter()
    listings = pd.DataFrame(get_known_listings())
    records = build_opportunity_snapshot_records(listings, observed_at)
    calculation_seconds = perf_counter() - calculation_started

    write_started = perf_counter()
    inserted = insert_opportunity_snapshots(records)
    write_seconds = perf_counter() - write_started
    return SnapshotRunResult(
        calculated=len(records),
        inserted=inserted,
        calculation_seconds=calculation_seconds,
        write_seconds=write_seconds,
    )
