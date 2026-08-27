from __future__ import annotations

from dataclasses import dataclass

from config.vehicle_semantics import (
    BodyStyle,
    Drivetrain,
    load_vehicle_semantics,
)


@dataclass(frozen=True)
class VehicleSemantics:
    body_style: BodyStyle
    drivetrain: Drivetrain


def _normalize_text(value: str) -> str:
    return " ".join("".join(character if character.isalnum() else " " for character in value.casefold()).split())


def _matches(text: str, terms: tuple[str, ...]) -> bool:
    padded_text = f" {text} "
    return any(f" {_normalize_text(term)} " in padded_text for term in terms)


def _extract(text: str, vocabulary: dict, unknown):
    matches = [semantic for semantic, terms in vocabulary.items() if terms and _matches(text, terms)]
    return matches[0] if len(matches) == 1 else unknown


def extract_vehicle_semantics(title: str | None) -> VehicleSemantics:
    """Extract conservative, brand-independent semantics from title evidence."""
    if not title:
        return VehicleSemantics(BodyStyle.UNKNOWN, Drivetrain.UNKNOWN)
    text = _normalize_text(str(title))
    vocabulary = load_vehicle_semantics()
    return VehicleSemantics(
        body_style=_extract(text, vocabulary.body_style, BodyStyle.UNKNOWN),
        drivetrain=_extract(text, vocabulary.drivetrain, Drivetrain.UNKNOWN),
    )
