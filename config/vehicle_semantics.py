from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path

import yaml

from config.paths import VEHICLE_SEMANTICS_PATH


SUPPORTED_VERSIONS = {1}


class BodyStyle(str, Enum):
    SEDAN = "SEDAN"
    WAGON = "WAGON"
    COUPE = "COUPE"
    CONVERTIBLE = "CONVERTIBLE"
    HATCHBACK = "HATCHBACK"
    SUV = "SUV"
    VAN = "VAN"
    UNKNOWN = "UNKNOWN"


class Drivetrain(str, Enum):
    AWD = "AWD"
    FWD = "FWD"
    RWD = "RWD"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class VehicleSemanticsVocabulary:
    version: int
    body_style: dict[BodyStyle, tuple[str, ...]]
    drivetrain: dict[Drivetrain, tuple[str, ...]]


def _read_yaml(path: Path) -> dict:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Vehicle semantics file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in vehicle semantics {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("Vehicle semantics config must be a mapping")
    return raw


def _load_terms(raw: object, enum_type: type[Enum], field: str) -> dict:
    if not isinstance(raw, dict):
        raise ValueError(f"Vehicle semantics '{field}' must be a mapping")
    loaded = {member: () for member in enum_type}
    for key, terms in raw.items():
        try:
            semantic = enum_type(key)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Unknown {field} class: {key!r}") from exc
        if semantic.value == "UNKNOWN":
            raise ValueError(f"{field} UNKNOWN must not have configured terms")
        if not isinstance(terms, list) or not terms:
            raise ValueError(f"{field} {semantic.value} must contain non-empty terms")
        normalized_terms = tuple(" ".join(term.casefold().split()) for term in terms if isinstance(term, str) and term.strip())
        if len(normalized_terms) != len(terms):
            raise ValueError(f"{field} {semantic.value} terms must be non-empty strings")
        if len(set(normalized_terms)) != len(normalized_terms):
            raise ValueError(f"{field} {semantic.value} contains duplicate terms")
        loaded[semantic] = normalized_terms
    return loaded


@lru_cache(maxsize=None)
def load_vehicle_semantics(
    path: str | Path = VEHICLE_SEMANTICS_PATH,
) -> VehicleSemanticsVocabulary:
    raw = _read_yaml(Path(path).resolve())
    unknown = set(raw) - {"version", "body_style", "drivetrain"}
    if unknown:
        raise ValueError(f"Vehicle semantics contains unknown fields: {', '.join(sorted(unknown))}")
    version = raw.get("version")
    if not isinstance(version, int) or isinstance(version, bool):
        raise ValueError("Vehicle semantics version must be an integer")
    if version not in SUPPORTED_VERSIONS:
        raise ValueError(f"Unsupported vehicle semantics version: {version}")
    return VehicleSemanticsVocabulary(
        version=version,
        body_style=_load_terms(raw.get("body_style"), BodyStyle, "body_style"),
        drivetrain=_load_terms(raw.get("drivetrain"), Drivetrain, "drivetrain"),
    )
