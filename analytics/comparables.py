from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

import pandas as pd

from analytics.valuation_eligibility import (
    ValuationStatus,
    evaluate_valuation_eligibility,
)
from models.listing import TransmissionType
from normalization.vehicle_fields import normalize_transmission, registration_year


class ComparableStatus(str, Enum):
    OK = "OK"
    INSUFFICIENT_COMPARABLES = "INSUFFICIENT_COMPARABLES"
    TARGET_INELIGIBLE = "TARGET_INELIGIBLE"
    TARGET_MISSING_CORE_DATA = "TARGET_MISSING_CORE_DATA"


@dataclass(frozen=True)
class ComparableConfig:
    max_year_distance: int = 3
    max_mileage_distance_km: int = 100_000
    min_comparables: int = 5
    target_comparables: int = 20

    def __post_init__(self) -> None:
        if self.max_year_distance < 0 or self.max_mileage_distance_km < 0:
            raise ValueError("Comparable distance limits must be non-negative")
        if self.min_comparables < 1 or self.target_comparables < 1:
            raise ValueError("Comparable counts must be positive")


@dataclass(frozen=True)
class ComparableResult:
    target_listing_id: str
    comparables: pd.DataFrame
    candidate_count: int
    comparable_count: int
    status: ComparableStatus
    active_count: int = 0
    eligible_count: int = 0
    risk_count: int = 0
    ineligible_count: int = 0
    transmission_match_count: int = 0
    year_match_count: int = 0
    mileage_match_count: int = 0


_OUTPUT_COLUMNS = (
    "listing_id", "title", "price", "mileage_km", "year", "transmission",
    "location", "year_distance", "mileage_distance_km", "year_weight",
    "mileage_weight", "similarity_weight",
)


def _empty_comparables(source: pd.DataFrame) -> pd.DataFrame:
    columns = list(dict.fromkeys([*source.columns, *_OUTPUT_COLUMNS]))
    return pd.DataFrame(columns=columns)


def _row_value(row: Mapping | pd.Series, name: str):
    value = row.get(name)
    return None if pd.isna(value) else value


def find_comparables(
    target: Mapping | pd.Series,
    listings: pd.DataFrame,
    config: ComparableConfig | None = None,
) -> ComparableResult:
    """Select deterministic clean active comparables for one target listing."""
    cfg = config or ComparableConfig()
    target_id_value = _row_value(target, "listing_id")
    target_id = "" if target_id_value is None else str(target_id_value)
    empty = _empty_comparables(listings)

    target_price = _row_value(target, "price")
    target_year = registration_year(_row_value(target, "first_registration"))
    target_mileage = _row_value(target, "mileage_km")
    target_transmission = normalize_transmission(_row_value(target, "transmission"))
    if (
        target_price is None
        or target_year is None
        or target_mileage is None
        or target_transmission == TransmissionType.UNKNOWN
    ):
        return ComparableResult(target_id, empty, 0, 0, ComparableStatus.TARGET_MISSING_CORE_DATA)
    if evaluate_valuation_eligibility(target).status != ValuationStatus.ELIGIBLE:
        return ComparableResult(target_id, empty, 0, 0, ComparableStatus.TARGET_INELIGIBLE)

    required = {"listing_id", "price", "mileage_km", "first_registration", "transmission", "is_active"}
    missing = required.difference(listings.columns)
    if missing:
        raise ValueError(f"Listings are missing required columns: {', '.join(sorted(missing))}")

    candidates = listings.copy()
    candidates = candidates.loc[candidates["is_active"].eq(1)].copy()
    active_count = len(candidates)
    candidates["valuation_status"] = candidates.apply(
        lambda row: evaluate_valuation_eligibility(row).status, axis=1
    )
    eligible_count = int(candidates["valuation_status"].eq(ValuationStatus.ELIGIBLE).sum())
    risk_count = int(candidates["valuation_status"].eq(ValuationStatus.ELIGIBLE_WITH_RISK).sum())
    ineligible_count = int(candidates["valuation_status"].eq(ValuationStatus.INELIGIBLE).sum())
    candidates = candidates.loc[candidates["valuation_status"].eq(ValuationStatus.ELIGIBLE)].copy()
    candidates = candidates.loc[candidates["listing_id"].astype(str).ne(target_id)].copy()

    candidates["year"] = candidates["first_registration"].apply(registration_year)
    candidates["transmission_group"] = candidates["transmission"].apply(normalize_transmission)
    candidates["year_distance"] = (candidates["year"] - target_year).abs()
    candidates["mileage_distance_km"] = (
        pd.to_numeric(candidates["mileage_km"], errors="coerce") - float(target_mileage)
    ).abs()
    candidates = candidates.loc[candidates["transmission_group"].eq(target_transmission)].copy()
    transmission_match_count = len(candidates)
    candidates = candidates.loc[candidates["year_distance"].le(cfg.max_year_distance)].copy()
    year_match_count = len(candidates)
    candidates = candidates.loc[
        candidates["mileage_distance_km"].le(cfg.max_mileage_distance_km)
    ].copy()
    mileage_match_count = len(candidates)

    candidates["year_weight"] = 1.0 / (1.0 + candidates["year_distance"])
    candidates["mileage_weight"] = 1.0 / (1.0 + candidates["mileage_distance_km"] / 50_000.0)
    candidates["similarity_weight"] = candidates["year_weight"] * candidates["mileage_weight"]
    candidates = candidates.sort_values(
        ["similarity_weight", "year_distance", "mileage_distance_km", "listing_id"],
        ascending=[False, True, True, True], kind="mergesort",
    )
    candidate_count = len(candidates)
    comparables = candidates.head(cfg.target_comparables).copy().reset_index(drop=True)
    status = ComparableStatus.OK if candidate_count >= cfg.min_comparables else ComparableStatus.INSUFFICIENT_COMPARABLES
    return ComparableResult(
        target_id, comparables, candidate_count, len(comparables), status,
        active_count, eligible_count, risk_count, ineligible_count,
        transmission_match_count, year_match_count, mileage_match_count,
    )
