"""Read-only benchmark and equivalence audit for dashboard analytics."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import math
import sqlite3
from time import perf_counter

import pandas as pd

from analytics.comparables import find_comparables, prepare_comparable_universe
from analytics.market_value import MarketValueStatus, estimate_market_value
from analytics.opportunity import calculate_economic_opportunity, calculate_opportunity_score
from analytics.valuation_eligibility import ValuationStatus, evaluate_valuation_eligibility
from config.paths import DB_PATH
from dashboard.views import sort_opportunities


@dataclass(frozen=True)
class BenchmarkResult:
    frame: pd.DataFrame
    comparable_signatures: dict[str, tuple[tuple[str, ...], tuple[float, ...]]]
    db_load_seconds: float
    precompute_seconds: float
    comparable_valuation_seconds: float
    opportunity_seconds: float
    dataframe_seconds: float
    total_seconds: float
    active_count: int
    clean_count: int
    valued_count: int
    scored_count: int


def _load_read_only() -> tuple[pd.DataFrame, float]:
    started = perf_counter()
    path = DB_PATH.resolve()
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5) as connection:
        connection.execute("PRAGMA query_only = ON")
        listings = pd.read_sql_query("SELECT * FROM listings", connection)
    return listings, perf_counter() - started


def _run(listings: pd.DataFrame, db_seconds: float, *, prepared: bool) -> BenchmarkResult:
    total_started = perf_counter()
    listings = listings.copy()
    listings["listing_id"] = listings["listing_id"].astype(str)
    active = listings.loc[listings["is_active"].eq(1)].copy()

    started = perf_counter()
    universe = prepare_comparable_universe(listings) if prepared else None
    precompute_seconds = perf_counter() - started

    started = perf_counter()
    valuations = []
    signatures = {}
    for _, target in active.iterrows():
        comparable = (
            find_comparables(target, universe=universe)
            if prepared
            else find_comparables(target, listings)
        )
        market_value = estimate_market_value(comparable)
        listing_id = str(target["listing_id"])
        signatures[listing_id] = (
            tuple(comparable.comparables["listing_id"].astype(str)),
            tuple(float(value) for value in comparable.comparables["similarity_weight"]),
        )
        valuations.append((target, market_value))
    comparable_valuation_seconds = perf_counter() - started

    started = perf_counter()
    analytics_rows = []
    for target, market_value in valuations:
        listing_id = str(target["listing_id"])
        eligibility = (
            universe.eligibility_by_id[listing_id]
            if universe is not None
            else evaluate_valuation_eligibility(target)
        )
        economic = calculate_economic_opportunity(target.get("price"), market_value)
        score = calculate_opportunity_score(economic, eligibility.status)
        analytics_rows.append({
            "listing_id": listing_id,
            "market_value_status": market_value.status.value,
            "estimated_market_price": market_value.estimated_market_price,
            "valuation_confidence": market_value.confidence.value,
            "comparable_count": market_value.comparable_count,
            "market_gap_eur": economic.market_gap_eur,
            "discount_percent": economic.discount_percent,
            "discount_component": score.discount_component,
            "margin_component": score.margin_component,
            "base_opportunity": score.base_opportunity,
            "confidence_multiplier": score.confidence_multiplier,
            "risk_multiplier": score.risk_multiplier,
            "opportunity_score": score.opportunity_score,
        })
    opportunity_seconds = perf_counter() - started

    started = perf_counter()
    frame = pd.DataFrame(analytics_rows)
    dataframe_seconds = perf_counter() - started
    clean_count = (
        universe.eligible_count
        if universe is not None
        else sum(
            evaluate_valuation_eligibility(row).status == ValuationStatus.ELIGIBLE
            for _, row in active.iterrows()
        )
    )
    valued_count = sum(row["market_value_status"] == MarketValueStatus.OK.value for row in analytics_rows)
    scored_count = int(frame["opportunity_score"].notna().sum()) if not frame.empty else 0
    return BenchmarkResult(
        frame=frame,
        comparable_signatures=signatures,
        db_load_seconds=db_seconds,
        precompute_seconds=precompute_seconds,
        comparable_valuation_seconds=comparable_valuation_seconds,
        opportunity_seconds=opportunity_seconds,
        dataframe_seconds=dataframe_seconds,
        total_seconds=db_seconds + perf_counter() - total_started,
        active_count=len(active),
        clean_count=clean_count,
        valued_count=valued_count,
        scored_count=scored_count,
    )


def _equivalent(left, right) -> bool:
    if left is None or right is None:
        return left is right
    if pd.isna(left) or pd.isna(right):
        return bool(pd.isna(left) and pd.isna(right))
    if isinstance(left, float) or isinstance(right, float):
        return math.isclose(float(left), float(right), rel_tol=1e-12, abs_tol=1e-12)
    return left == right


def _compare(legacy: BenchmarkResult, optimized: BenchmarkResult) -> list[str]:
    differences = []
    columns = [column for column in optimized.frame.columns if column != "listing_id"]
    old = legacy.frame.set_index("listing_id")
    new = optimized.frame.set_index("listing_id")
    for listing_id in new.index:
        old_ids, old_weights = legacy.comparable_signatures[listing_id]
        new_ids, new_weights = optimized.comparable_signatures[listing_id]
        if old_ids != new_ids or len(old_weights) != len(new_weights) or any(
            not _equivalent(left, right) for left, right in zip(old_weights, new_weights)
        ):
            differences.append(f"{listing_id}: comparable IDs/order/weights")
        for column in columns:
            if not _equivalent(old.at[listing_id, column], new.at[listing_id, column]):
                differences.append(f"{listing_id}: {column}")
    old_order = sort_opportunities(legacy.frame)["listing_id"].tolist()
    new_order = sort_opportunities(optimized.frame)["listing_id"].tolist()
    if old_order != new_order:
        differences.append("final dashboard ordering")
    return differences


def _print_result(result: BenchmarkResult) -> None:
    print(f"ACTIVE: {result.active_count}")
    print(f"CLEAN ELIGIBLE: {result.clean_count}")
    print(f"VALUED: {result.valued_count}")
    print(f"SCORED: {result.scored_count}")
    print(f"DB load: {result.db_load_seconds:.3f} s")
    print(f"Precompute: {result.precompute_seconds:.3f} s")
    print(f"Comparable + valuation: {result.comparable_valuation_seconds:.3f} s")
    print(f"Opportunity: {result.opportunity_seconds:.3f} s")
    print(f"DataFrame: {result.dataframe_seconds:.3f} s")
    print(f"TOTAL: {result.total_seconds:.3f} s")
    print(f"targets / second: {result.active_count / result.total_seconds:.1f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--compare-legacy",
        action="store_true",
        help="also run the slower unprepared path and verify all current targets",
    )
    args = parser.parse_args()
    listings, db_seconds = _load_read_only()
    optimized = _run(listings, db_seconds, prepared=True)
    _print_result(optimized)
    if args.compare_legacy:
        print("\nRunning full legacy equivalence audit…")
        legacy = _run(listings, 0.0, prepared=False)
        differences = _compare(legacy, optimized)
        print(f"EQUIVALENCE DIFFERENCES: {len(differences)}")
        for difference in differences[:20]:
            print(f"- {difference}")
        if differences:
            raise SystemExit(1)
        print("EQUIVALENCE: PASS (all active targets and final dashboard ordering)")


if __name__ == "__main__":
    main()
