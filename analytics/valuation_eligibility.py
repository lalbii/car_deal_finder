from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

import pandas as pd

from models.listing import TransmissionType
from normalization.vehicle_fields import normalize_transmission
from validation.listing_quality import (
    DataQuality,
    classify_first_registration,
    classify_mileage,
    classify_price,
)


PLACEHOLDER_PRICE_MAX_EUR = 100
EXTREME_MILEAGE_KM = 400_000
SUSPICIOUSLY_LOW_PRICE_EUR = 1_000


class ValuationStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    ELIGIBLE_WITH_RISK = "ELIGIBLE_WITH_RISK"
    INELIGIBLE = "INELIGIBLE"


class ValuationReason(str, Enum):
    LEASING_TAKEOVER = "LEASING_TAKEOVER"
    PARTS_ONLY = "PARTS_ONLY"
    SEVERE_MECHANICAL_DAMAGE = "SEVERE_MECHANICAL_DAMAGE"
    PROJECT_OR_SCRAP = "PROJECT_OR_SCRAP"
    PLACEHOLDER_PRICE = "PLACEHOLDER_PRICE"
    MISSING_CORE_DATA = "MISSING_CORE_DATA"
    EXTREME_MILEAGE = "EXTREME_MILEAGE"
    SUSPICIOUSLY_LOW_PRICE = "SUSPICIOUSLY_LOW_PRICE"
    ACCIDENT = "ACCIDENT"
    NO_TUV = "NO_TUV"


@dataclass(frozen=True)
class ValuationEligibility:
    status: ValuationStatus
    reasons: tuple[ValuationReason, ...]
    core_data_diagnostics: tuple[str, ...] = ()


_HARD_TEXT_RULES = (
    (ValuationReason.LEASING_TAKEOVER, ("leasingübernahme", "leasinguebernahme", "leasing takeover")),
    (ValuationReason.PARTS_ONLY, ("teileträger", "teiletraeger", "schlachtfahrzeug", "nur teile")),
    (ValuationReason.SEVERE_MECHANICAL_DAMAGE, ("motorschaden", "getriebeschaden")),
    (ValuationReason.PROJECT_OR_SCRAP, ("bastlerfahrzeug", "projektfahrzeug", "schrottfahrzeug")),
)
_RISK_TEXT_RULES = (
    (ValuationReason.ACCIDENT, ("unfallfahrzeug", "unfallschaden", "unfallwagen")),
    (ValuationReason.NO_TUV, ("kein tüv", "kein tuev", "ohne tüv", "ohne tuev", "tüv abgelaufen", "tuev abgelaufen")),
)


def _value(listing: Mapping | pd.Series, name: str):
    value = listing.get(name)
    return None if value is None or pd.isna(value) else value


def _searchable_text(listing: Mapping | pd.Series) -> str:
    return " ".join(
        str(value).casefold()
        for value in (_value(listing, "title"), _value(listing, "description"))
        if value
    )


def evaluate_valuation_eligibility(
    listing: Mapping | pd.Series,
) -> ValuationEligibility:
    """Evaluate the canonical hard exclusions and soft valuation risks."""
    price = _value(listing, "price")
    mileage = _value(listing, "mileage_km")
    registration = _value(listing, "first_registration")
    transmission = _value(listing, "transmission")
    qualities = {
        "price": classify_price(price),
        "mileage_km": classify_mileage(mileage),
        "first_registration": classify_first_registration(registration),
    }
    transmission_group = normalize_transmission(transmission)
    diagnostics = tuple(
        [
            f"{name}:{quality.value}"
            for name, quality in qualities.items()
            if quality in {DataQuality.MISSING, DataQuality.INVALID}
        ]
        + (["transmission:UNKNOWN"] if transmission_group == TransmissionType.UNKNOWN else [])
    )

    text = _searchable_text(listing)
    hard_reasons = [
        reason for reason, terms in _HARD_TEXT_RULES if any(term in text for term in terms)
    ]
    if price is not None and price <= PLACEHOLDER_PRICE_MAX_EUR:
        hard_reasons.append(ValuationReason.PLACEHOLDER_PRICE)
    if diagnostics:
        hard_reasons.append(ValuationReason.MISSING_CORE_DATA)
    if hard_reasons:
        return ValuationEligibility(
            ValuationStatus.INELIGIBLE, tuple(hard_reasons), diagnostics
        )

    risk_reasons = [
        reason for reason, terms in _RISK_TEXT_RULES if any(term in text for term in terms)
    ]
    if mileage > EXTREME_MILEAGE_KM:
        risk_reasons.append(ValuationReason.EXTREME_MILEAGE)
    if price < SUSPICIOUSLY_LOW_PRICE_EUR:
        risk_reasons.append(ValuationReason.SUSPICIOUSLY_LOW_PRICE)
    if any(quality == DataQuality.SUSPECT for quality in qualities.values()):
        if ValuationReason.EXTREME_MILEAGE not in risk_reasons and qualities["mileage_km"] == DataQuality.SUSPECT:
            risk_reasons.append(ValuationReason.EXTREME_MILEAGE)
        if ValuationReason.SUSPICIOUSLY_LOW_PRICE not in risk_reasons and qualities["price"] == DataQuality.SUSPECT:
            risk_reasons.append(ValuationReason.SUSPICIOUSLY_LOW_PRICE)
    if risk_reasons:
        return ValuationEligibility(
            ValuationStatus.ELIGIBLE_WITH_RISK, tuple(risk_reasons), diagnostics
        )
    return ValuationEligibility(ValuationStatus.ELIGIBLE, (), diagnostics)


def valuation_status(
    *,
    price: int | float | None,
    mileage_km: int | float | None,
    first_registration: str | None,
    transmission: str | None,
    title: str | None = None,
    description: str | None = None,
) -> ValuationStatus:
    """Compatibility wrapper returning only the canonical status."""
    return evaluate_valuation_eligibility(
        {
            "price": price,
            "mileage_km": mileage_km,
            "first_registration": first_registration,
            "transmission": transmission,
            "title": title,
            "description": description,
        }
    ).status
