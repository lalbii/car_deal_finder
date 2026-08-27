from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

import numpy as np
import pandas as pd

from analytics.vehicle_semantics import (
    BodyStyle,
    VehicleSemantics,
    extract_vehicle_semantics,
)
from analytics.valuation_eligibility import (
    ValuationEligibility,
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
    body_style_guardrails: bool = True

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
    target_body_style: BodyStyle = BodyStyle.UNKNOWN
    body_style_match_count: int = 0
    known_body_style_mismatch_count: int = 0
    unknown_body_style_count: int = 0
    same_body_style_count: int = 0


@dataclass(frozen=True)
class ComparableUniverse:
    """Canonical active candidate data prepared once for repeated searches."""
    listings: pd.DataFrame
    eligible_by_transmission: dict[TransmissionType, pd.DataFrame]
    eligibility_by_id: dict[str, ValuationEligibility]
    semantics_by_id: dict[str, VehicleSemantics]
    year_by_id: dict[str, int | None]
    mileage_by_id: dict[str, float | None]
    price_by_id: dict[str, float | None]
    transmission_by_id: dict[str, TransmissionType]
    active_count: int
    eligible_count: int
    risk_count: int
    ineligible_count: int


_OUTPUT_COLUMNS = (
    "listing_id", "title", "price", "mileage_km", "year", "transmission",
    "location", "year_distance", "mileage_distance_km", "year_weight",
    "mileage_weight", "target_body_style", "candidate_body_style",
    "body_style_factor", "similarity_weight",
)


def body_style_factor(target: BodyStyle, candidate: BodyStyle) -> float:
    """Return the explicit Comparable Engine v3 body-style factor."""
    if target == BodyStyle.UNKNOWN and candidate == BodyStyle.UNKNOWN:
        return 0.65
    if BodyStyle.UNKNOWN in {target, candidate}:
        return 0.75
    return 1.0 if target == candidate else 0.0


def prepare_comparable_universe(listings: pd.DataFrame) -> ComparableUniverse:
    """Precompute canonical candidate attributes without changing selection rules."""
    required = {
        "listing_id", "price", "mileage_km", "first_registration",
        "transmission", "is_active",
    }
    missing = required.difference(listings.columns)
    if missing:
        raise ValueError(f"Listings are missing required columns: {', '.join(sorted(missing))}")

    source = listings.copy()
    source["listing_id"] = source["listing_id"].astype(str)
    active = source.loc[source["is_active"].eq(1)].copy()
    eligibility_by_id = {
        str(row["listing_id"]): evaluate_valuation_eligibility(row)
        for _, row in active.iterrows()
    }
    semantics_by_id = {
        str(row["listing_id"]): extract_vehicle_semantics(_row_value(row, "title"))
        for _, row in active.iterrows()
    }
    active["valuation_status"] = active["listing_id"].map(
        lambda listing_id: eligibility_by_id[str(listing_id)].status
    )
    active["year"] = active["first_registration"].apply(registration_year)
    active["transmission_group"] = active["transmission"].apply(normalize_transmission)
    active["candidate_body_style"] = active["listing_id"].map(
        lambda listing_id: semantics_by_id[str(listing_id)].body_style.value
    )
    active["_mileage_numeric"] = pd.to_numeric(active["mileage_km"], errors="coerce")
    active["_price_numeric"] = pd.to_numeric(active["price"], errors="coerce")
    eligible_count = int(active["valuation_status"].eq(ValuationStatus.ELIGIBLE).sum())
    risk_count = int(active["valuation_status"].eq(ValuationStatus.ELIGIBLE_WITH_RISK).sum())
    ineligible_count = int(active["valuation_status"].eq(ValuationStatus.INELIGIBLE).sum())
    eligible = active.loc[active["valuation_status"].eq(ValuationStatus.ELIGIBLE)].copy()
    pools = {
        transmission: eligible.loc[eligible["transmission_group"].eq(transmission)].copy()
        for transmission in TransmissionType
    }
    return ComparableUniverse(
        listings=source,
        eligible_by_transmission=pools,
        eligibility_by_id=eligibility_by_id,
        semantics_by_id=semantics_by_id,
        year_by_id=dict(zip(active["listing_id"], active["year"])),
        mileage_by_id=dict(zip(active["listing_id"], active["_mileage_numeric"])),
        price_by_id=dict(zip(active["listing_id"], active["_price_numeric"])),
        transmission_by_id=dict(zip(active["listing_id"], active["transmission_group"])),
        active_count=len(active),
        eligible_count=eligible_count,
        risk_count=risk_count,
        ineligible_count=ineligible_count,
    )


def _empty_comparables(source: pd.DataFrame) -> pd.DataFrame:
    columns = list(dict.fromkeys([*source.columns, *_OUTPUT_COLUMNS]))
    return pd.DataFrame(columns=columns)


def _row_value(row: Mapping | pd.Series, name: str):
    value = row.get(name)
    return None if pd.isna(value) else value


def _find_in_prepared_pool(
    target_id: str, target_year: int, target_mileage: float,
    target_transmission: TransmissionType, target_body_style: BodyStyle,
    universe: ComparableUniverse, cfg: ComparableConfig,
) -> ComparableResult:
    """Apply canonical filters to arrays, materializing only selected rows."""
    pool = universe.eligible_by_transmission[target_transmission]
    ids = pool["listing_id"].to_numpy(dtype=str)
    years = pool["year"].to_numpy(dtype=float)
    mileages = pool["_mileage_numeric"].to_numpy(dtype=float)
    body_styles = pool["candidate_body_style"].to_numpy(dtype=str)
    year_distance = np.abs(years - target_year)
    mileage_distance = np.abs(mileages - float(target_mileage))
    other = ids != target_id
    within_year = other & (year_distance <= cfg.max_year_distance)
    within_mileage = within_year & (mileage_distance <= cfg.max_mileage_distance_km)
    if not cfg.body_style_guardrails:
        factors = np.ones(len(pool), dtype=float)
    elif target_body_style == BodyStyle.UNKNOWN:
        factors = np.where(body_styles == BodyStyle.UNKNOWN.value, 0.65, 0.75)
    else:
        factors = np.where(
            body_styles == target_body_style.value, 1.0,
            np.where(body_styles == BodyStyle.UNKNOWN.value, 0.75, 0.0),
        )
    accepted = within_mileage & (factors > 0.0)
    positions = np.flatnonzero(accepted)
    year_weight = 1.0 / (1.0 + year_distance)
    mileage_weight = 1.0 / (1.0 + mileage_distance / 50_000.0)
    weights = year_weight * mileage_weight * factors
    order = np.lexsort((
        ids[positions], mileage_distance[positions], year_distance[positions],
        -weights[positions],
    ))
    selected = positions[order][:cfg.target_comparables]
    comparables = pool.iloc[selected].copy()
    comparables["year_distance"] = year_distance[selected]
    comparables["mileage_distance_km"] = mileage_distance[selected]
    comparables["target_body_style"] = target_body_style.value
    comparables["body_style_factor"] = factors[selected]
    comparables["year_weight"] = year_weight[selected]
    comparables["mileage_weight"] = mileage_weight[selected]
    comparables["similarity_weight"] = weights[selected]
    comparables = comparables.reset_index(drop=True)
    candidate_count = len(positions)
    accepted_styles = body_styles[accepted]
    return ComparableResult(
        target_id, comparables, candidate_count, len(comparables),
        ComparableStatus.OK if candidate_count >= cfg.min_comparables else ComparableStatus.INSUFFICIENT_COMPARABLES,
        universe.active_count, universe.eligible_count, universe.risk_count,
        universe.ineligible_count, int(other.sum()), int(within_year.sum()),
        int(within_mileage.sum()), target_body_style, candidate_count,
        int((within_mileage & (factors == 0.0)).sum()),
        int((accepted_styles == BodyStyle.UNKNOWN.value).sum()),
        int(target_body_style != BodyStyle.UNKNOWN and (accepted_styles == target_body_style.value).sum()),
    )


def find_comparables(
    target: Mapping | pd.Series,
    listings: pd.DataFrame | None = None,
    config: ComparableConfig | None = None,
    *,
    universe: ComparableUniverse | None = None,
) -> ComparableResult:
    """Select deterministic clean active comparables for one target listing."""
    cfg = config or ComparableConfig()
    target_id_value = _row_value(target, "listing_id")
    target_id = "" if target_id_value is None else str(target_id_value)
    if listings is None and universe is None:
        raise ValueError("Either listings or a prepared comparable universe is required")
    source = universe.listings if universe is not None else listings
    empty = _empty_comparables(source)

    target_price = _row_value(target, "price")
    prepared_eligibility = (
        universe.eligibility_by_id.get(target_id) if universe is not None else None
    )
    prepared_semantics = (
        universe.semantics_by_id.get(target_id) if universe is not None else None
    )
    target_year = (
        universe.year_by_id.get(target_id)
        if universe is not None and target_id in universe.year_by_id
        else registration_year(_row_value(target, "first_registration"))
    )
    target_mileage = _row_value(target, "mileage_km")
    target_transmission = (
        universe.transmission_by_id.get(target_id, TransmissionType.UNKNOWN)
        if universe is not None and target_id in universe.transmission_by_id
        else normalize_transmission(_row_value(target, "transmission"))
    )
    target_body_style = (
        prepared_semantics.body_style
        if prepared_semantics is not None
        else extract_vehicle_semantics(_row_value(target, "title")).body_style
    )
    if (
        target_price is None
        or target_year is None
        or target_mileage is None
        or target_transmission == TransmissionType.UNKNOWN
    ):
        return ComparableResult(target_id, empty, 0, 0, ComparableStatus.TARGET_MISSING_CORE_DATA)
    target_eligibility = prepared_eligibility or evaluate_valuation_eligibility(target)
    if target_eligibility.status != ValuationStatus.ELIGIBLE:
        return ComparableResult(target_id, empty, 0, 0, ComparableStatus.TARGET_INELIGIBLE)

    if universe is not None:
        return _find_in_prepared_pool(
            target_id, target_year, float(target_mileage), target_transmission,
            target_body_style, universe, cfg,
        )
    else:
        required = {
            "listing_id", "price", "mileage_km", "first_registration",
            "transmission", "is_active",
        }
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
        candidates["year"] = candidates["first_registration"].apply(registration_year)
        candidates["transmission_group"] = candidates["transmission"].apply(normalize_transmission)
        candidate_titles = (
            candidates["title"]
            if "title" in candidates
            else pd.Series(None, index=candidates.index)
        )
        candidates["candidate_body_style"] = candidate_titles.apply(
            lambda title: extract_vehicle_semantics(title).body_style.value
        )
        candidates["_mileage_numeric"] = pd.to_numeric(
            candidates["mileage_km"], errors="coerce"
        )
        candidates = candidates.loc[
            candidates["transmission_group"].eq(target_transmission)
        ].copy()
        candidates = candidates.loc[candidates["listing_id"].astype(str).ne(target_id)].copy()
        transmission_match_count = len(candidates)
        candidates["year_distance"] = (candidates["year"] - target_year).abs()
        candidates = candidates.loc[candidates["year_distance"].le(cfg.max_year_distance)].copy()
        year_match_count = len(candidates)
    candidates["mileage_distance_km"] = (
        candidates["_mileage_numeric"] - float(target_mileage)
    ).abs()
    candidates = candidates.loc[
        candidates["mileage_distance_km"].le(cfg.max_mileage_distance_km)
    ].copy()
    mileage_match_count = len(candidates)

    candidates["target_body_style"] = target_body_style.value
    if cfg.body_style_guardrails:
        candidates["body_style_factor"] = pd.Series(
            (
                body_style_factor(target_body_style, BodyStyle(candidate))
                for candidate in candidates["candidate_body_style"]
            ),
            index=candidates.index,
            dtype=float,
        )
        known_body_style_mismatch_count = int(candidates["body_style_factor"].eq(0.0).sum())
        candidates = candidates.loc[candidates["body_style_factor"].gt(0.0)].copy()
    else:
        candidates["body_style_factor"] = 1.0
        known_body_style_mismatch_count = 0
    body_style_match_count = len(candidates)
    unknown_body_style_count = int(
        candidates["candidate_body_style"].eq(BodyStyle.UNKNOWN.value).sum()
    )
    same_body_style_count = int(
        target_body_style != BodyStyle.UNKNOWN
        and candidates["candidate_body_style"].eq(target_body_style.value).sum()
    )

    candidates["year_weight"] = 1.0 / (1.0 + candidates["year_distance"])
    candidates["mileage_weight"] = 1.0 / (1.0 + candidates["mileage_distance_km"] / 50_000.0)
    candidates["similarity_weight"] = (
        candidates["year_weight"]
        * candidates["mileage_weight"]
        * candidates["body_style_factor"]
    )
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
        target_body_style, body_style_match_count,
        known_body_style_mismatch_count, unknown_body_style_count,
        same_body_style_count,
    )
