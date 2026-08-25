import re
from datetime import date

from models.listing import FuelType, TransmissionType


GERMAN_MONTHS = {
    "januar": 1,
    "februar": 2,
    "märz": 3,
    "maerz": 3,
    "april": 4,
    "mai": 5,
    "juni": 6,
    "juli": 7,
    "august": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "dezember": 12,
}


def normalize_price(value: str | None) -> int | None:
    """Normalize a complete German EUR asking-price string."""
    if not value:
        return None

    text = value.replace("\xa0", " ").strip()
    match = re.fullmatch(
        r"(?P<number>\d{1,3}(?:[. ]\d{3})+|\d+)(?:,\d{1,2})?\s*"
        r"(?:€|EUR)(?:\s*(?:VB|VHB))?",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None

    digits = re.sub(r"[^\d]", "", match.group("number"))
    return int(digits) if digits else None


def normalize_mileage(value: str | None) -> int | None:
    """Normalize a complete mileage string containing a km unit."""
    if not value:
        return None

    text = value.replace("\xa0", " ").strip()
    match = re.fullmatch(
        r"(?P<number>\d{1,3}(?:[., ]\d{3})+|\d+)\s*km",
        text,
        re.IGNORECASE,
    )
    if not match:
        return None

    digits = re.sub(r"[^\d]", "", match.group("number"))
    return int(digits) if digits else None


def normalize_transmission(value: str | None) -> TransmissionType:
    if not value:
        return TransmissionType.UNKNOWN

    text = value.casefold().strip()
    if any(term in text for term in ("automatik", "automatic")):
        return TransmissionType.AUTOMATIC
    if any(term in text for term in ("manuell", "manual", "schaltgetriebe")):
        return TransmissionType.MANUAL
    return TransmissionType.UNKNOWN


def normalize_fuel(value: str | None) -> FuelType:
    if not value:
        return FuelType.UNKNOWN

    text = value.casefold().strip()
    mappings = {
        "diesel": FuelType.DIESEL,
        "benzin": FuelType.PETROL,
        "petrol": FuelType.PETROL,
        "hybrid": FuelType.HYBRID,
        "elektro": FuelType.ELECTRIC,
        "electric": FuelType.ELECTRIC,
    }
    for term, fuel_type in mappings.items():
        if term in text:
            return fuel_type
    return FuelType.OTHER


def normalize_first_registration(value: str | None) -> str | None:
    """Return YYYY-MM when month is known, otherwise YYYY."""
    if not value:
        return None

    text = re.sub(r"\s+", " ", str(value)).strip()

    canonical_match = re.fullmatch(r"(19\d{2}|20\d{2})-(0[1-9]|1[0-2])", text)
    if canonical_match:
        return text

    numeric_match = re.fullmatch(r"(0?[1-9]|1[0-2])[/.](19\d{2}|20\d{2})", text)
    if numeric_match:
        month, year = numeric_match.groups()
        return f"{year}-{int(month):02d}"

    month_match = re.fullmatch(r"([A-Za-zÄÖÜäöüß]+)\s+(19\d{2}|20\d{2})", text)
    if month_match:
        month_name, year = month_match.groups()
        month = GERMAN_MONTHS.get(month_name.casefold())
        if month is None:
            return None
        return f"{year}-{month:02d}"

    if re.fullmatch(r"(?:19|20)\d{2}", text):
        return text

    return None


def registration_is_in_future(value: str, today: date | None = None) -> bool:
    current = today or date.today()
    year = int(value[:4])
    month = int(value[5:7]) if len(value) == 7 else 1
    return (year, month) > (current.year, current.month)
