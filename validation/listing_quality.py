from dataclasses import dataclass
from datetime import date
from enum import Enum
import math

from models.listing import FuelType, Listing, TransmissionType
from normalization.vehicle_fields import (
    normalize_first_registration,
    registration_is_in_future,
)


class DataQuality(str, Enum):
    VALID = "VALID"
    SUSPECT = "SUSPECT"
    INVALID = "INVALID"
    MISSING = "MISSING"


@dataclass(frozen=True)
class ListingQualityReport:
    overall: DataQuality
    fields: dict[str, DataQuality]
    messages: tuple[str, ...]
    is_scorable: bool


def classify_price(value: int | float | None) -> DataQuality:
    """Valid: EUR 500..500k; suspect outside; invalid <=0 or above EUR 5m."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return DataQuality.MISSING
    if value <= 0 or value > 5_000_000:
        return DataQuality.INVALID
    if value < 500 or value > 500_000:
        return DataQuality.SUSPECT
    return DataQuality.VALID


def classify_mileage(value: int | float | None) -> DataQuality:
    """Valid: 500..600k km; suspect to 2m; invalid negative or above 2m."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return DataQuality.MISSING
    if value < 0 or value > 2_000_000:
        return DataQuality.INVALID
    if value < 500 or value > 600_000:
        return DataQuality.SUSPECT
    return DataQuality.VALID


def classify_first_registration(
    value: str | None, today: date | None = None
) -> DataQuality:
    if value is None:
        return DataQuality.MISSING

    normalized = normalize_first_registration(value)
    if normalized is None:
        return DataQuality.INVALID

    year = int(normalized[:4])
    if year < 1900 or registration_is_in_future(normalized, today=today):
        return DataQuality.INVALID
    if year < 1950:
        return DataQuality.SUSPECT
    return DataQuality.VALID


def validate_listing(listing: Listing, today: date | None = None) -> ListingQualityReport:
    fields = {
        "listing_id": DataQuality.VALID if listing.listing_id else DataQuality.MISSING,
        "url": DataQuality.VALID if listing.url else DataQuality.MISSING,
        "title": DataQuality.VALID if listing.title else DataQuality.MISSING,
        "price": classify_price(listing.price),
        "mileage_km": classify_mileage(listing.mileage_km),
        "first_registration": classify_first_registration(
            listing.first_registration, today=today
        ),
        "fuel": (
            DataQuality.MISSING
            if listing.fuel == FuelType.UNKNOWN and not listing.raw_fuel
            else DataQuality.SUSPECT
            if listing.fuel in {FuelType.UNKNOWN, FuelType.OTHER}
            else DataQuality.VALID
        ),
        "transmission": (
            DataQuality.MISSING
            if listing.transmission == TransmissionType.UNKNOWN
            and not listing.raw_transmission
            else DataQuality.SUSPECT
            if listing.transmission == TransmissionType.UNKNOWN
            else DataQuality.VALID
        ),
    }

    messages = tuple(
        f"{field_name} is {quality.value.lower()}"
        for field_name, quality in fields.items()
        if quality != DataQuality.VALID
    )

    qualities = set(fields.values())
    if DataQuality.INVALID in qualities:
        overall = DataQuality.INVALID
    elif DataQuality.MISSING in qualities:
        overall = DataQuality.MISSING
    elif DataQuality.SUSPECT in qualities:
        overall = DataQuality.SUSPECT
    else:
        overall = DataQuality.VALID

    comparable_fields = (
        fields["price"],
        fields["mileage_km"],
        fields["first_registration"],
        fields["transmission"],
    )
    is_scorable = all(quality == DataQuality.VALID for quality in comparable_fields)

    return ListingQualityReport(
        overall=overall,
        fields=fields,
        messages=messages,
        is_scorable=is_scorable,
    )


def validated_record(listing: Listing, report: ListingQualityReport) -> dict:
    """Return a persistence record, masking unequivocally invalid core values."""
    record = listing.to_record()
    for field_name in ("price", "mileage_km", "first_registration"):
        if report.fields[field_name] == DataQuality.INVALID:
            record[field_name] = None

    record["data_quality"] = report.overall.value
    record["is_scorable"] = report.is_scorable
    for field_name, quality in report.fields.items():
        record[f"{field_name}_quality"] = quality.value
    return record
