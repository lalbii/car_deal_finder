from dataclasses import dataclass
from enum import Enum


class FuelType(str, Enum):
    DIESEL = "DIESEL"
    PETROL = "PETROL"
    HYBRID = "HYBRID"
    ELECTRIC = "ELECTRIC"
    OTHER = "OTHER"
    UNKNOWN = "UNKNOWN"


class TransmissionType(str, Enum):
    AUTOMATIC = "AUTOMATIC"
    MANUAL = "MANUAL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SearchListing:
    listing_id: str | None
    url: str
    title: str
    location: str | None
    price: int | None
    raw_price: str | None

    def to_record(self) -> dict:
        return {
            "listing_id": self.listing_id,
            "search_title": self.title,
            "search_price_text": self.raw_price,
            "location": self.location,
            "url": self.url,
        }


@dataclass(frozen=True)
class Listing:
    listing_id: str | None
    url: str
    title: str | None = None
    location: str | None = None
    price: int | None = None
    mileage_km: int | None = None
    first_registration: str | None = None
    fuel: FuelType = FuelType.UNKNOWN
    transmission: TransmissionType = TransmissionType.UNKNOWN
    posted_date: str | None = None
    view_count: int | None = None
    is_active: bool = True
    description: str = ""
    raw_price: str | None = None
    raw_mileage: str | None = None
    raw_first_registration: str | None = None
    raw_fuel: str | None = None
    raw_transmission: str | None = None

    def to_record(self) -> dict:
        return {
            "listing_id": self.listing_id,
            "url": self.url,
            "title": self.title,
            "location": self.location,
            "price": self.price,
            "mileage_km": self.mileage_km,
            "first_registration": self.first_registration,
            "fuel": self.fuel.value,
            "transmission": self.transmission.value,
            "posted_date": self.posted_date,
            "view_count": self.view_count,
            "is_active": self.is_active,
            "description": self.description,
            "price_text": self.raw_price,
            "mileage_text": self.raw_mileage,
            "first_registration_text": self.raw_first_registration,
            "fuel_text": self.raw_fuel,
            "transmission_text": self.raw_transmission,
        }
